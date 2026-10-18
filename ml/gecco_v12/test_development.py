"""Synthetic V12 runner/runtime boundary tests; no real-source values or fitting."""
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from ml.gecco_v12 import development as d, runtime
from ml.gecco_v7 import runtime_v2, runtime_delayed
from ml.gecco_v10.calibration import _choice, predict
from ml.gecco_v7.evidence import separate_scores


class SensorOnlySpy:
    def __init__(self, channels=("p1", "p2")):
        self.channels = list(channels)
        self.fit_status_ = "synthetic_fitted"
        self.fit_calls = []; self.score_calls = []

    def fit(self, frame, labels):
        if list(frame.columns) != self.channels:
            raise AssertionError("Only ordered sensor columns may enter model.fit")
        self.fit_calls.append((frame.copy(), np.asarray(labels).copy()))
        return self

    def score_components(self, frame):
        if list(frame.columns) != self.channels:
            raise AssertionError("Only ordered sensor columns may enter scoring")
        self.score_calls.append(frame.copy())
        score = (frame.p1 % 13 / 12).rolling(3, min_periods=3).mean().to_numpy()
        return {"long_context": score}

    def inspection(self):
        return {"fit_status": self.fit_status_, "synthetic_only": True}

    def conditional_observed(self, frame):
        if list(frame.columns) != self.channels:
            raise AssertionError("Only sensor columns may enter conditional coverage")
        return np.isfinite(frame.to_numpy()).all(axis=1)


def reference_fake(bundle, frame, *, gap_samples):
    if list(frame.columns) != list(bundle["local_model"].channels):
        raise AssertionError("Labels or unrelated columns reached the reference model")
    value = frame.p1.to_numpy()
    ignored = np.arange(len(frame)) < gap_samples
    available = np.isfinite(frame.to_numpy()).all(axis=1) & ~ignored
    ref = np.where(available, (value % 11 < 5).astype(np.int8), -1).astype(np.int8)
    level = np.full(len(frame), .5)
    jump = np.where(value % 7 < 3, 2., .5)
    sustained = np.where(value % 17 == 0, np.nan, .5)
    level[ignored] = np.nan; jump[ignored] = np.nan; sustained[ignored] = np.nan
    return pd.DataFrame({"baseline_prediction": ref.copy(), "prediction": ref,
                         "available": available, "ignored_gap": ignored,
                         "level": level, "jump": jump, "sustained": sustained}, index=frame.index)


class V12DevelopmentTests(unittest.TestCase):
    def _run(self, *, continuous=False, waterhub=False, mutate_plan=None, mutate_prior=False, mutate_if=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); out = root / "out"; out.mkdir(); old = root / "prior"; old.mkdir()
            train_end = 200; width = 190; starts = [train_end + width * i for i in range(4)]
            test_start = starts[-1] + width; test_end = test_start + width
            target = "label" if waterhub else "EVENT"
            frame = pd.DataFrame({"p1": np.arange(test_end, dtype=float), "p2": 1.,
                                  target: np.where(np.arange(test_end) % 29 < 8, 1, 0).astype(np.int8),
                                  "unrelated": "must_not_reach_model"})
            frame.loc[37:40, target] = -1
            channels = ["p1", "p2"]
            reference_bundle = {"selected": {"seed": "baseline", "rescue": None, "threshold": None, "policy": "instant"},
                                "local_model": SimpleNamespace(channels=channels),
                                "prior_bundle": {"model": SimpleNamespace(baseline_=SimpleNamespace(marker="frozen"))},
                                "max_fit_index": train_end - 1, "max_calibration_index": test_start - 1}
            joblib.dump(reference_bundle, old / "bundle.joblib")
            geometry = {"train": [0, train_end], "test": [test_start, test_end]}
            if waterhub:
                geometry["calibration_boundaries"] = starts + [test_start]
                frozen = {"case": geometry}
            else:
                geometry["calibration_starts"] = starts
                frozen = geometry.copy()
            frozen["bundle_sha256"] = d.sha(old / "bundle.joblib")
            (old / "freeze.json").write_text(json.dumps(frozen))
            cal_saved = []
            for start in starts:
                part = frame.iloc[start:start + width]
                ref = reference_fake(reference_bundle, part[channels], gap_samples=d.GAP)
                cal_saved.append(pd.DataFrame({"sample_index": np.arange(start, start + width),
                    target: part[target].to_numpy(), "baseline": ref.prediction.to_numpy(), "guarded": ref.prediction.to_numpy(),
                    **{key: ref[key].to_numpy() for key in ("level", "jump", "sustained")}}))
            pd.concat(cal_saved, ignore_index=True).to_csv(old / "calibration_scores.csv.gz", index=False)
            test_ref = reference_fake(reference_bundle, frame.iloc[test_start:][channels], gap_samples=d.GAP)
            first, final = ("baseline_prediction", "prediction") if waterhub else ("baseline", "candidate")
            pd.DataFrame({"sample_index": np.arange(test_start, test_end), target: frame.iloc[test_start:][target].to_numpy(),
                          first: test_ref.prediction.to_numpy(), final: test_ref.prediction.to_numpy(),
                          **{key: test_ref[key].to_numpy() for key in ("level", "jump", "sustained")}}).to_csv(old / "predictions.csv.gz", index=False)
            for name in ("code.py", "input.csv"):
                (root / name).write_text("frozen")
            plan = {"code_sha256": {"code.py": d.sha(root / "code.py")},
                    "input_sha256": {"input.csv": d.sha(root / "input.csv")},
                    "reference_sha256": {"synthetic": {"folder": "prior",
                        "files": {name: d.sha(old / name) for name in d.REFERENCE_FILES}}}}
            (out / "plan.json").write_text(json.dumps(plan))
            model = SensorOnlySpy(channels)
            def make_scorer(actual_channels, baseline_estimator):
                self.assertEqual(actual_channels, channels)
                self.assertEqual(baseline_estimator.marker, "frozen")
                model.baseline_estimator_ = baseline_estimator
                return model
            if mutate_if:
                previous_fit = model.fit
                def mutated_fit(*args, **kwargs):
                    result = previous_fit(*args, **kwargs)
                    model.baseline_estimator_.marker = "mutated"
                    return result
                model.fit = mutated_fit
            selected = {**_choice(.4, .7, "2of3", 2), "status": "synthetic_selected"}
            recorded = {"calibrations": [], "test_opened": False}
            def calibrate(blocks, *, cadence_seconds):
                self.assertEqual(cadence_seconds, 60)
                self.assertFalse((out / "synthetic" / "freeze.json").exists())
                self.assertEqual(len(model.fit_calls), 1)
                pd.testing.assert_frame_equal(model.fit_calls[0][0], frame.iloc[:train_end][channels])
                np.testing.assert_array_equal(model.fit_calls[0][1], frame.iloc[:train_end][target].to_numpy())
                self.assertTrue(all(part.p1.max() < test_start for part in model.score_calls if len(part)))
                recorded["calibrations"].append(blocks)
                for index, block in enumerate(blocks):
                    self.assertEqual(block["source_start"], starts[index])
                    np.testing.assert_array_equal(block["labels"], frame.iloc[starts[index]:starts[index] + width][target])
                    local = {key: cal_saved[index][key].to_numpy() for key in ("level", "jump", "sustained")}
                    masks = separate_scores(local, block["long_scores"])
                    np.testing.assert_allclose(block["rescue_scores"], masks["rescue_long_context"], rtol=0, atol=0, equal_nan=True)
                if mutate_plan: (root / mutate_plan).write_text("changed_after_selection")
                return selected, [{**selected, "feasible": True}]
            def load_test():
                folder = out / "synthetic"
                self.assertTrue((folder / "bundle.joblib").is_file())
                self.assertTrue((folder / "calibration_scores.csv.gz").is_file())
                frozen = json.loads((folder / "freeze.json").read_text())
                self.assertEqual(frozen["selected"], selected)
                self.assertEqual(frozen["test"], [test_start, test_end])
                self.assertEqual(frozen["bundle_sha256"], d.sha(folder / "bundle.joblib"))
                bundle = joblib.load(folder / "bundle.joblib")
                self.assertEqual(bundle["selected"], selected)
                self.assertEqual(bundle["max_fit_index"], train_end - 1)
                self.assertEqual(bundle["max_calibration_index"], test_start - 1)
                self.assertEqual(len(recorded["calibrations"]), 1)
                self.assertTrue(all(part.p1.max() < test_start for part in model.score_calls if len(part)))
                recorded["test_opened"] = True
                if mutate_prior: (old / "bundle.joblib").write_bytes(b"changed_after_freeze")
                return frame.iloc[test_start:test_end].copy()
            case = {"name": "synthetic", "source": "WaterHub" if waterhub else "synthetic",
                    "target": target, "prior": old, "train": frame.iloc[:train_end],
                    "cal": [frame.iloc[start:start + width] for start in starts], "cal_starts": starts,
                    "test_start": test_start, "test_end": test_end, "load_test": load_test,
                    "channels": channels, "continuous_cal": continuous}
            hashes = {p.name: d.sha(p) for p in old.iterdir()}
            with patch.object(d, "ROOT", root), patch.object(d.prior, "ROOT", root), \
                 patch.object(d, "BaselineEvidenceHGBScorer", side_effect=make_scorer), \
                 patch.object(d, "calibrate", side_effect=calibrate), \
                 patch.object(d, "verify", wraps=d.verify) as verification:
                if mutate_plan or mutate_prior or mutate_if:
                    with self.assertRaises(RuntimeError if mutate_plan else AssertionError):
                        d.run_case(case, out, plan)
                    self.assertEqual(recorded["test_opened"], bool(mutate_prior))
                    return
                result, rows = d.run_case(case, out, plan)
            self.assertGreaterEqual(verification.call_count, 2)
            self.assertTrue(recorded["test_opened"])
            self.assertEqual([len(part) for part in model.score_calls], [640, 70] if continuous else [70] * 5)
            self.assertEqual({p.name: d.sha(p) for p in old.iterdir()}, hashes)
            self.assertEqual(result["fit_status"], "synthetic_fitted")
            saved_cal = pd.read_csv(out / "synthetic" / "calibration_scores.csv.gz", float_precision="round_trip")
            self.assertEqual(rows.sample_index.tolist(), list(range(test_start, test_end)))
            for index, block in enumerate(recorded["calibrations"][0]):
                part = saved_cal.iloc[index * width:(index + 1) * width]
                local = {key: cal_saved[index][key].to_numpy() for key in ("level", "jump", "sustained")}
                masks = separate_scores(local, part.long_context.to_numpy())
                for key, values in masks.items():
                    np.testing.assert_allclose(part[key], values, rtol=0, atol=0, equal_nan=True)
                expected = predict(block["reference"], block["long_scores"], selected, block["rescue_scores"])
                np.testing.assert_array_equal(part.candidate, expected)
                # Policy resets per block while the continuous-cal feature
                # context can span blocks. Replay the exact scored block.
                scored = pd.DataFrame({"reference_prediction": part.reference.to_numpy(),
                    "baseline_prediction": part.baseline.to_numpy(), "prediction": part.reference.to_numpy(),
                    "long_context": part.long_context.to_numpy(), **local})
                with patch.object(runtime, "score_frame", return_value=scored):
                    replay = runtime.predict_frame({"version": "v12_if_evidence_hgb_pulse_certified_120s", "sample_seconds": 60,
                        "selected": selected}, pd.DataFrame(index=np.arange(width)))
                np.testing.assert_array_equal(replay.prediction, part.candidate)
            if continuous:
                self.assertTrue(saved_cal.long_context.iloc[:120].isna().all())
                self.assertTrue(np.isfinite(saved_cal.long_context.iloc[width]))
            else:
                for index in range(4): self.assertTrue(saved_cal.long_context.iloc[index * width:index * width + 120].isna().all())
            bundle = joblib.load(out / "synthetic" / "bundle.joblib")
            with patch.object(runtime_v2, "reference_predict", side_effect=reference_fake):
                replay = runtime.predict_frame(bundle, frame.iloc[test_start:test_end])
            np.testing.assert_array_equal(replay.prediction, rows.candidate)
            np.testing.assert_array_equal(replay.reference_prediction, rows.reference)
            for column in ("long_context", "guarded_long_context", "rescue_long_context"):
                np.testing.assert_allclose(replay[column], rows[column], rtol=0, atol=0, equal_nan=True)

    def test_independent_blocks_sensor_only_training_freeze_before_test_and_runtime_parity(self):
        self._run()

    def test_continuous_cal_features_keep_one_gap_but_policy_resets_per_block(self):
        self._run(continuous=True)

    def test_waterhub_geometry_and_cached_reference_column_schema(self):
        self._run(waterhub=True)

    def test_changed_code_or_input_rejected_before_outer_test_is_loaded(self):
        for filename in ("code.py", "input.csv"):
            with self.subTest(filename=filename): self._run(mutate_plan=filename)

    def test_changed_prior_artifact_after_freeze_is_rejected(self):
        self._run(mutate_prior=True)

    def test_if_mutation_is_rejected_before_calibration_or_test(self):
        self._run(mutate_if=True)

    def test_imported_selection_and_inference_are_exact_frozen_certified_policy(self):
        self.assertEqual(d.calibrate.__module__, "ml.gecco_v10.calibration")
        self.assertIs(d.predict, predict)
        self.assertIs(d.cases, d.prior.cases)

    def test_score_gap_discards_before_sensor_only_features_including_empty_periods(self):
        for n in (0, 119, 120, 121, 190):
            model = SensorOnlySpy()
            frame = pd.DataFrame({"p1": np.arange(n), "p2": 1., "label": -1})
            values = d.score_gap(model, frame)
            self.assertEqual(len(values), n)
            self.assertTrue(np.isnan(values[:min(n, 120)]).all())
            pd.testing.assert_frame_equal(model.score_calls[0], frame.iloc[120:][model.channels].reset_index(drop=True))


class V12RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"p1": np.arange(160, dtype=float), "p2": 1., "label": -1, "EVENT": 1},
                                  index=pd.date_range("2020-01-01", periods=160, freq="min"))

    def _bundle(self):
        return {"version": "v12_if_evidence_hgb_pulse_certified_120s", "sample_seconds": 60, "gap_samples": 120,
                "selected": _choice(.4, .7, "2of3", 2), "long_model": SensorOnlySpy(),
                "reference_bundle": {"local_model": SimpleNamespace(channels=["p1", "p2"])}}

    def test_labels_never_reach_either_model_and_mutation_does_not_change_prediction(self):
        bundle = self._bundle(); original = bundle["selected"].copy()
        with patch.object(runtime_v2, "reference_predict", side_effect=reference_fake):
            first = runtime.predict_frame(bundle, self.frame)
            second = runtime.predict_frame(bundle, self.frame.assign(label=999, EVENT=-999))
        pd.testing.assert_frame_equal(first, second)
        self.assertTrue(all(list(frame.columns) == ["p1", "p2"] for frame in bundle["long_model"].score_calls))
        self.assertEqual(bundle["selected"], original)
        np.testing.assert_array_equal(first.prediction >= 0, first.reference_prediction >= 0)
        self.assertTrue(first.long_context.iloc[:120].isna().all())

    def test_runtime_rejects_wrong_version_declared_cadence_and_actual_timestamp_cadence(self):
        with self.assertRaises(ValueError): runtime.predict_frame({"version": "wrong"}, self.frame)
        bundle = self._bundle(); bundle["sample_seconds"] = 300
        with self.assertRaises(ValueError): runtime.predict_frame(bundle, self.frame)
        frame = self.frame.copy(); frame.index = pd.date_range("2020-01-01", periods=len(frame), freq="5min")
        with self.assertRaises(ValueError): runtime.predict_frame(self._bundle(), frame)
        frame.index = pd.date_range("2020-01-01", periods=len(frame), freq="min").where(np.arange(len(frame)) != 4)
        with self.assertRaises(ValueError): runtime.predict_frame(self._bundle(), frame)

    def test_current_local_masks_and_predictor_parity_across_persistence_policies(self):
        for policy in ("instant", "2of3", "3of5"):
            bundle = self._bundle(); bundle["selected"]["policy"] = policy
            with patch.object(runtime_v2, "reference_predict", side_effect=reference_fake):
                result = runtime.predict_frame(bundle, self.frame, gap_samples=5)
            masks = separate_scores({key: result[key].to_numpy() for key in ("level", "jump", "sustained")}, result.long_context.to_numpy())
            for key, values in masks.items():
                np.testing.assert_allclose(result[key], values, rtol=0, atol=0, equal_nan=True)
            expected = predict(result.reference_prediction.to_numpy(), result.long_context.to_numpy(), bundle["selected"], masks["rescue_long_context"])
            np.testing.assert_array_equal(result.prediction, expected)
            self.assertTrue(np.isfinite(result.guarded_long_context).any())
            self.assertTrue(np.isfinite(result.rescue_long_context).any())
            self.assertFalse((np.isfinite(result.guarded_long_context) & np.isfinite(result.rescue_long_context)).any())


if __name__ == "__main__":
    unittest.main()
