"""Synthetic runner/calibration contracts; never reads any real GECCO source."""
from __future__ import annotations

import contextlib
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_evaluation as runner
import supervised_explore as calibration


class SyntheticOnlyModel:
    def fit(self, frame, labels):
        assert list(frame.columns) == runner.CHANNELS
        assert len(frame) == len(labels)
        self.fit_rows_ = len(frame)
        return self

    def score(self, frame):
        assert list(frame.columns) == runner.CHANNELS
        assert not any(c in frame for c in ["EVENT", "Time", "sample_index"])
        return (frame.Tp.to_numpy() % 100) / 100


class RunnerContracts(unittest.TestCase):
    def test_gap_retains_every_source_label_and_hides_scoring_metadata(self):
        n = 200
        frame = pd.DataFrame({c:np.arange(n) for c in runner.CHANNELS})
        frame["EVENT"] = False; frame.loc[1:7, "EVENT"] = True
        frame["Time"] = "unused"
        scores = runner.score_with_gap(SyntheticOnlyModel(), frame)
        self.assertEqual(len(scores), n)
        self.assertTrue(np.isnan(scores[:runner.GAP]).all())
        predictions = np.where(np.isfinite(scores), 0, -1)
        result = runner.assess(frame.EVENT.to_numpy(), {"baseline":predictions, "v4":predictions})
        self.assertEqual(result["native"]["v4"]["true_events"], 1)
        self.assertEqual(result["native"]["v4"]["fully_unscorable_events"], 1)
        self.assertEqual(result["native"]["v4"]["sample_count"], n)

    def test_global_axis_counts_boundary_event_once(self):
        labels = np.zeros(30, dtype=bool); labels[12:19] = True
        predictions = np.zeros(30, dtype=int); predictions[13:15] = 1; predictions[15:17] = -1; predictions[18] = 1
        full = runner.assess(labels, {"baseline":predictions, "v4":predictions})
        split_count = sum(runner.assess(labels[a:b], {"baseline":predictions[a:b], "v4":predictions[a:b]})["native"]["v4"]["true_events"] for a,b in [(0,15),(15,30)])
        self.assertEqual(split_count, 2)
        self.assertEqual(full["native"]["v4"]["true_events"], 1)
        self.assertEqual(full["native"]["v4"]["confirmed_new_alarm_inside_events"], 1)

    def test_unavailable_or_no_normal_exposure_cannot_pass_gates(self):
        for labels in [np.zeros(30,dtype=bool), np.ones(30,dtype=bool)]:
            unavailable = np.full(30, -1, dtype=int)
            result = runner.assess(labels, {"baseline":unavailable, "v4":unavailable})
            gate = runner.gates(result, [result]*6)
            self.assertFalse(gate["pooled_joint_improvement"])
            self.assertFalse(gate["stable_joint_improvement"])
            self.assertFalse(gate["all_period_operating_budget_pass"])
            self.assertEqual(gate["noninferior_period_count"], 0)

    def test_declared_source_reads_only_prefix_then_frozen_test_all_six(self):
        # All paths, data, hash targets and models are synthetic temporary files.
        with tempfile.TemporaryDirectory(prefix="mawrid-v4-contract-") as tmp:
            base = Path(tmp); source = base / "synthetic.csv"; out = base / "output"
            n = 6000
            data = pd.DataFrame({c:np.arange(n,dtype=float) for c in runner.CHANNELS})
            data["Time"] = pd.date_range("2000-01-01", periods=n, freq="min").astype(str)
            data["EVENT"] = (np.arange(n)%100 >= 80)
            data.to_csv(source,index=False)
            out.mkdir(); (out/"protocol.json").write_text('{"synthetic":true}\n')
            protocol = {"family":"supervised", "recipe":"relative"}
            original_read = pd.read_csv
            observed = []
            def read_spy(path, *args, **kwargs):
                if Path(path) == source:
                    if kwargs.get("usecols") == ["Time"]:
                        observed.append(("timestamps", kwargs.get("nrows")))
                    else:
                        call = sum(kind == "labels" for kind, _ in observed)
                        fold = call//2+1
                        frozen_path = out/f"external_2017/fold_{fold}/freeze.json"
                        is_test_read = call%2 == 1
                        self.assertEqual(frozen_path.exists(), is_test_read)
                        expected = n*((call//2)+4+int(is_test_read))//10
                        self.assertEqual(kwargs.get("nrows"), expected)
                        observed.append(("labels", kwargs["nrows"]))
                return original_read(path,*args,**kwargs)
            chosen = {"threshold":.8,"policy":"instant"}
            buffer = io.StringIO()
            with patch.dict(runner.SOURCES, {"2017":source}), \
                 patch.object(runner,"check",return_value=protocol), \
                 patch.object(runner,"candidate",return_value=SyntheticOnlyModel()), \
                 patch.object(runner,"fit_baseline",return_value=SyntheticOnlyModel()), \
                 patch.object(runner,"score_baseline",side_effect=lambda m,f:m.score(f)), \
                 patch.object(runner,"select",return_value=(chosen.copy(),[])), \
                 patch.object(calibration,"calibrate",return_value=(chosen.copy(),[])), \
                 patch.object(pd,"read_csv",side_effect=read_spy), contextlib.redirect_stdout(buffer):
                runner.run(out,"2017")
            self.assertEqual(sum(kind == "labels" for kind,_ in observed),12)
            lines = buffer.getvalue().splitlines()
            self.assertEqual(len(lines),7)
            self.assertTrue(all("NO_METRICS_DISCLOSED" in line for line in lines[:6]))
            self.assertEqual(lines[-1],"ALL_SIX_PERIODS_COMPLETE_RESULTS_MAY_NOW_BE_REVIEWED")
            saved = original_read(out/"external_2017/predictions.csv.gz")
            np.testing.assert_array_equal(saved.sample_index,np.arange(n*4//10,n))
            np.testing.assert_array_equal(saved.EVENT,data.EVENT.iloc[n*4//10:])


class CalibrationContracts(unittest.TestCase):
    def test_no_event_calibration_does_not_consume_false_alarm_budget(self):
        blocks = [(np.zeros(2000,dtype=bool), np.linspace(.01,.99,2000)) for _ in range(3)]
        chosen,_ = calibration.calibrate(blocks)
        self.assertGreater(chosen["threshold"],.99)
        self.assertEqual(chosen["fp_minutes"],0)
        self.assertTrue(chosen["feasible_all_blocks"])

    def test_all_missing_calibration_remains_unavailable(self):
        labels = np.zeros(200,dtype=bool); labels[100:110]=True
        chosen,_ = calibration.calibrate([(labels,np.full(200,np.nan))])
        self.assertEqual(chosen["calibration_status"],"no_available_scores")
        self.assertFalse(chosen["feasible_all_blocks"])
        self.assertEqual(chosen["block_metrics"][0]["valid_count"],0)

    def test_missing_normal_exposure_does_not_relax_constraint(self):
        labels = np.ones(200,dtype=bool)
        chosen,_ = calibration.calibrate([(labels,np.linspace(.01,.99,200))])
        self.assertEqual(chosen["calibration_status"],"no_feasible_operating_point_all_silent")
        self.assertFalse(chosen["feasible_all_blocks"])
        self.assertGreater(chosen["threshold"],.99)

    def test_selected_threshold_obeys_every_past_block(self):
        rng=np.random.default_rng(42)
        blocks=[]
        for loc in [.05,.15,.35]:
            y=np.zeros(2000,dtype=bool); y[500:520]=True
            scores=np.clip(rng.normal(loc,.03,2000),0,1); scores[y]=.95
            blocks.append((y,scores))
        chosen,_=calibration.calibrate(blocks)
        self.assertTrue(chosen["feasible_all_blocks"])
        for result in chosen["block_metrics"]:
            self.assertLessEqual(result["false_alarm_runs_per_normal_day"],1.)
            self.assertLessEqual(result["normal_time_under_alarm"],.01)


class OfflineInferenceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location("v4_offline_predict_contract",HERE/"predict.py")
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)

    def test_acquisition_order_and_metadata_exclusion(self):
        values=np.array([70.,10.,90.,30.])
        frame=pd.DataFrame({c:values for c in runner.CHANNELS})
        frame["EVENT"]=[True,False,True,False];frame["Time"]=[4,3,2,1]
        bundle={"channels":runner.CHANNELS,"family":"adaptive","model":SyntheticOnlyModel(),"threshold":.5,"policy":"instant"}
        result=self.module.predict_frame(bundle,frame)
        np.testing.assert_allclose(result.score,values/100,rtol=0,atol=0)
        np.testing.assert_array_equal(result.prediction,[1,0,1,0])

    def test_missing_required_channel_is_rejected(self):
        bundle={"channels":runner.CHANNELS,"family":"adaptive","model":SyntheticOnlyModel(),"threshold":.5,"policy":"instant"}
        with self.assertRaises(ValueError):self.module.predict_frame(bundle,pd.DataFrame({"Tp":[1.]}))

    def test_untrained_reason_is_preserved(self):
        class Untrained:
            fit_status_="insufficient_normal_training"
            def score(self,frame):return np.full(len(frame),np.nan)
        frame=pd.DataFrame({c:np.arange(10,dtype=float) for c in runner.CHANNELS})
        bundle={"channels":runner.CHANNELS,"family":"supervised","model":Untrained(),"threshold":.5,"policy":"instant"}
        result=self.module.predict_frame(bundle,frame)
        self.assertTrue((result.prediction==-1).all())
        self.assertTrue((result.reason=="insufficient_normal_training").all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
