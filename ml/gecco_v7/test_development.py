"""Independent synthetic review of the V7 development/evaluation boundary."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v7 import development as d


class ScoreSpy:
    def __init__(self, channels):
        self.channels = channels
        self.fit_status_ = "fitted"
        self.fit_frames = []
        self.score_frames = []

    def fit(self, frame, labels):
        self.fit_frames.append((frame.copy(), np.asarray(labels).copy()))
        return self

    def score_components(self, frame):
        self.score_frames.append(frame.copy())
        return {"long_context": np.full(len(frame), .5)}

    def inspection(self):
        return {"synthetic": True}


class DevelopmentTests(unittest.TestCase):
    def test_package_imports_do_not_resolve_to_v5_calibration(self):
        self.assertEqual(d.calibrate.__module__, "ml.gecco_v7.calibration")
        self.assertEqual(d.predict.__module__, "ml.gecco_v7.calibration")
        self.assertEqual(d.v6_predict.__module__, "joint_calibration_v2")

    def test_gap_is_discarded_before_model_observes_features(self):
        for n in (0, 119, 120, 121, 170):
            model = ScoreSpy(["p1"])
            frame = pd.DataFrame({"p1": np.arange(n)})
            score = d.score_gap(model, frame)
            self.assertEqual(len(score), n)
            self.assertTrue(np.isnan(score[:min(n, 120)]).all())
            self.assertEqual(model.score_frames[0].p1.tolist(), list(range(120, n)))
            self.assertEqual(model.score_frames[0].index.tolist(), list(range(max(n - 120, 0))))

    def test_waterhub_geometry_and_deferred_test_loading(self):
        reads = []
        geometry = [{"name": "synthetic_month", "train": [0, 20],
                     "calibration_boundaries": [20, 25, 30, 35, 40], "test": [40, 50]}]
        frame = pd.DataFrame({"p1": np.arange(50), "p2": np.arange(50),
                              "p3": np.arange(50), "p4": np.arange(50), "label": np.zeros(50, np.int8)})
        def read_csv(path, **kwargs):
            reads.append(kwargs["nrows"])
            return frame.iloc[:kwargs["nrows"]].copy()
        with patch.object(d, "sha", return_value=d.WATERHUB_SHA), patch.object(d, "waterhub_geometry", return_value=geometry), patch.object(d.pd, "read_csv", side_effect=read_csv):
            case = next(d.cases("waterhub"))
            self.assertEqual(reads, [40])
            self.assertEqual(case["train"].p1.tolist(), list(range(20)))
            self.assertEqual([part.p1.tolist() for part in case["cal"]], [list(range(a, a + 5)) for a in (20, 25, 30, 35)])
            self.assertFalse(case["continuous_cal"])
            self.assertEqual(case["load_test"]().p1.tolist(), list(range(40, 50)))
            self.assertEqual(reads, [40, 50])

    def _run_synthetic(self, continuous):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); out = root / "out"; out.mkdir(); old = root / "prior"; old.mkdir()
            train_end = 200; cal_starts = [200, 370, 540, 710]; test_start = 880; test_end = 1050
            frame = pd.DataFrame({"p1": np.arange(test_end), "EVENT": np.zeros(test_end, np.int8)})
            (out / "plan.json").write_text("{}")
            prior = {"selected": {"seed": "baseline", "rescue": None, "threshold": None, "policy": "instant"},
                     "max_fit_index": train_end - 1, "max_calibration_index": test_start - 1}
            (old / "bundle.joblib").write_bytes(b"synthetic-prior")
            (old / "freeze.json").write_text(json.dumps({
                "train": [0, train_end], "calibration_starts": cal_starts,
                "test": [test_start, test_end], "bundle_sha256": d.sha(old / "bundle.joblib")}))
            pd.DataFrame({"sample_index": np.arange(train_end, test_start), "EVENT": 0,
                          "baseline": 0, "guarded": 0}).to_csv(old / "calibration_scores.csv.gz", index=False)
            pd.DataFrame({"sample_index": np.arange(test_start, test_end), "EVENT": 0,
                          "baseline": 0, "candidate": 0}).to_csv(old / "predictions.csv.gz", index=False)
            recorded = {"calibrations": []}
            model = ScoreSpy(["p1"])
            selected = {"decision": "reference", "low_threshold": None,
                        "high_threshold": None, "policy": "instant"}
            def calibrate(blocks, **kwargs):
                recorded["calibrations"].append(blocks)
                self.assertFalse((out / "synthetic" / "freeze.json").exists())
                self.assertEqual(model.fit_frames[0][0].p1.tolist(), list(range(train_end)))
                return selected, [{**selected, "feasible": True}]
            def load_test():
                folder = out / "synthetic"
                self.assertTrue((folder / "bundle.joblib").is_file())
                frozen = json.loads((folder / "freeze.json").read_text())
                self.assertEqual(frozen["test"], [test_start, test_end])
                self.assertEqual(frozen["selected"], selected)
                self.assertEqual(len(recorded["calibrations"]), 1)
                self.assertTrue(all(f.p1.max() < test_start for f in model.score_frames if len(f)))
                recorded["outer_opened_after_freeze"] = True
                return frame.iloc[test_start:test_end]
            case = {"name": "synthetic", "source": "synthetic", "target": "EVENT", "prior": old,
                    "train": frame.iloc[:train_end], "cal": [frame.iloc[a:a + 170] for a in cal_starts],
                    "cal_starts": cal_starts, "test_start": test_start, "test_end": test_end,
                    "load_test": load_test, "channels": ["p1"], "continuous_cal": continuous}
            old_hashes = {p.name: d.sha(p) for p in old.iterdir()}
            def dump(bundle, path, **kwargs):
                self.assertEqual(bundle["max_fit_index"], train_end - 1)
                self.assertEqual(bundle["max_calibration_index"], test_start - 1)
                Path(path).write_bytes(b"synthetic-fitted-bundle")
            with patch.object(d, "ROOT", root), patch.object(d, "LongContextEventScorer", return_value=model), patch.object(d, "verify"), patch.object(d, "calibrate", side_effect=calibrate), patch.object(d.joblib, "load", return_value=prior), patch.object(d.joblib, "dump", side_effect=dump):
                result, rows = d.run_case(case, out, {})
            self.assertTrue(recorded["outer_opened_after_freeze"])
            self.assertEqual([len(f) for f in model.score_frames], [560, 50] if continuous else [50, 50, 50, 50, 50])
            self.assertEqual([len(b["labels"]) for b in recorded["calibrations"][0]], [170] * 4)
            self.assertEqual([b["source_start"] for b in recorded["calibrations"][0]], cal_starts)
            self.assertEqual(rows.sample_index.tolist(), list(range(test_start, test_end)))
            self.assertTrue(result["development_only"])
            self.assertEqual({p.name: d.sha(p) for p in old.iterdir()}, old_hashes)

    def test_independent_cal_blocks_fit_only_training_and_freeze_before_test(self):
        self._run_synthetic(False)

    def test_2019_continuous_cal_context_has_one_gap_and_same_split(self):
        self._run_synthetic(True)

    def test_pooled_event_axis_does_not_duplicate_boundary_event(self):
        y = np.array([0, 1, 1, 1, 0], np.int8)
        p = np.array([0, 1, 1, 1, 0], np.int8)
        whole = d.comparisons(y, p, p, p)
        parts = [d.comparisons(y[:2], p[:2], p[:2], p[:2]), d.comparisons(y[2:], p[2:], p[2:], p[2:])]
        self.assertEqual(whole["v6_vs_v7"]["baseline"]["true_events"], 1)
        self.assertEqual([part["v6_vs_v7"]["baseline"]["true_events"] for part in parts], [1, 0])

    def test_summarize_uses_source_pooled_fp_runs_and_requires_complete_scope(self):
        y = np.zeros(4, np.int8); p = np.array([0, 1, 1, 0], np.int8)
        whole = d.comparisons(y, p, p, p)
        periods = [{"comparisons": d.comparisons(y[a:b], p[a:b], p[a:b], p[a:b])} for a, b in ((0, 2), (2, 4))]
        result = d.summarize(periods, {"synthetic": whole}, expected_cases=19)
        self.assertEqual(result["v6_vs_v7"]["baseline"]["false_positive_runs"], 1)
        self.assertFalse(result["v6_vs_v7"]["checks"]["all_prespecified_cases_complete"])
        self.assertFalse(result["v6_vs_v7"]["passes_declared_development_gate"])
        complete = d.summarize(periods, {"synthetic": whole}, expected_cases=2)
        self.assertTrue(complete["v6_vs_v7"]["checks"]["all_prespecified_cases_complete"])

    def test_fair_comparisons_include_unknowns_and_positive_point_loss(self):
        y = np.array([0, 1, 1, -1, 0, 0], np.int8)
        first = np.array([0, 1, 1, 1, 0, -1], np.int8)
        ref = first.copy(); candidate = np.array([0, 1, 0, 1, 0, -1], np.int8)
        result = d.comparisons(y, first, ref, candidate)
        self.assertEqual(set(result), {"if_vs_v6", "if_vs_v7", "v6_vs_v7"})
        self.assertEqual(result["v6_vs_v7"]["lost_positive_alarm_rows"], 1)
        self.assertEqual(result["v6_vs_v7"]["candidate"]["unknown_label_observed_rows"], 1)
        self.assertTrue(result["v6_vs_v7"]["sensor_availability_equal"])

    def test_inherited_v6_point_loss_is_not_new_v7_regression(self):
        y = np.array([0, 1, 1, 1, 0], np.int8)
        first = np.array([0, 1, 1, 1, 0], np.int8)
        reference = np.array([0, 1, 0, 1, 0], np.int8)
        whole = d.comparisons(y, first, reference, reference)
        summary = d.summarize([{"comparisons": whole}], {"synthetic": whole}, expected_cases=1)
        self.assertEqual(whole["if_vs_v7"]["lost_positive_alarm_rows"], 1)
        self.assertFalse(whole["if_vs_v7"]["lost_baseline_event_ids"])
        self.assertEqual(whole["v6_vs_v7"]["lost_positive_alarm_rows"], 0)
        key = "no_additional_positive_alarm_row_loss_relative_v6"
        self.assertTrue(summary["v6_vs_v7"]["checks"][key])
        self.assertNotIn(key, summary["if_vs_v7"]["checks"])
        # An actual incremental loss against V6 must fail the dedicated gate.
        candidate = np.array([0, 1, 0, 0, 0], np.int8)
        changed = d.comparisons(y, first, reference, candidate)
        changed_summary = d.summarize([{"comparisons": changed}], {"synthetic": changed}, expected_cases=1)
        self.assertFalse(changed_summary["v6_vs_v7"]["checks"][key])

    def test_freeze_verification_checks_both_code_and_inputs(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "code.py").write_text("original")
            (root / "input.csv").write_text("past")
            plan = {"code_sha256": {"code.py": d.sha(root / "code.py")},
                    "input_sha256": {"input.csv": d.sha(root / "input.csv")}}
            with patch.object(d, "ROOT", root):
                d.verify(plan)
                (root / "input.csv").write_text("changed")
                with self.assertRaises(RuntimeError): d.verify(plan)
                (root / "input.csv").write_text("past")
                (root / "code.py").write_text("changed")
                with self.assertRaises(RuntimeError): d.verify(plan)


if __name__ == "__main__":
    unittest.main()
