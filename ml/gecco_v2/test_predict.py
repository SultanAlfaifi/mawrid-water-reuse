"""Synthetic inference tests; no dataset labels or evaluation artifacts read."""
from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from predict import predict_frame, build_features


class BaselineStub:
    def score_samples(self, X):
        return -np.asarray(X[:, 0])


class SupervisedStub:
    classes_ = np.array([0, 1])

    def predict_proba(self, X):
        score = np.clip(np.asarray(X[:, 0]), 0, 1)
        return np.c_[1-score, score]


class ChangeStub:
    history_rows = 1

    def __init__(self, channels):
        self.channels = channels

    def score(self, frame):
        assert list(frame.columns) == self.channels
        return frame[self.channels[0]].to_numpy(dtype=float)


def bundle(family="if_normalized_changes_w30", policy="instant", channels=None):
    channels = ["a", "b"] if channels is None else channels
    if family == "baseline":
        model = BaselineStub()
    elif family == "if_normalized_changes_w30":
        model = ChangeStub(channels)
    else:
        model = SupervisedStub()
    return {"family": family, "model": model, "channels": channels,
            "threshold": .5, "policy": policy,
            "feature_set": {"baseline": "baseline15",
                            "if_normalized_changes_w30": "normalized_causal_changes_w30"}.get(family, "multiscale"),
            "model_id": "synthetic-test", "limitations": ["synthetic detection-only stub"]}


class PredictTests(unittest.TestCase):
    def test_expected_policy_outputs_and_missing_reset(self):
        scores = [.9, .1, .8, .9, np.nan, .9, .9, .1, .1, .9]
        frame = pd.DataFrame({"a": scores, "b": 1.})
        expected = {
            "instant": [1, 0, 1, 1, -1, 1, 1, 0, 0, 1],
            "2of3": [-1, -1, 1, 1, -1, -1, -1, 1, 0, 0],
            "3of5": [-1, -1, -1, -1, -1, -1, -1, -1, -1, 1],
        }
        for policy, values in expected.items():
            with self.subTest(policy=policy):
                result = predict_frame(bundle(policy=policy), frame)
                np.testing.assert_array_equal(result.prediction, values)
                self.assertEqual(result.reason.iloc[4], "current_measurement_missing")
                if policy != "instant":
                    self.assertTrue(result.score_available.iloc[5])
                    self.assertEqual(result.reason.iloc[5], "policy_history_unavailable")

    def test_batch_prefix_equality_all_families_and_policies(self):
        rng = np.random.default_rng(42)
        frame = pd.DataFrame({"a": rng.uniform(size=125), "b": rng.normal(size=125)},
                             index=np.arange(1000, 1125))
        frame.iloc[72, 1] = np.nan
        for family in ("baseline", "extra_trees", "hist_gradient_boosting", "logistic", "if_normalized_changes_w30"):
            for policy in ("instant", "2of3", "3of5"):
                artifact = bundle(family, policy)
                full = predict_frame(artifact, frame)
                for stop in (0, 1, 14, 15, 59, 60, 61, 72, 73, 74, 90, 125):
                    with self.subTest(family=family, policy=policy, stop=stop):
                        prefix = predict_frame(artifact, frame.iloc[:stop])
                        pd.testing.assert_frame_equal(full.iloc[:stop], prefix)

    def test_labels_and_extra_columns_are_ignored(self):
        frame = pd.DataFrame({"a": np.tile([.1, .9], 70), "b": 1.,
                              "EVENT": [object() for _ in range(140)],
                              "future_label": ["not a number"]*140})
        for family in ("baseline", "extra_trees", "if_normalized_changes_w30"):
            artifact = bundle(family)
            expected = predict_frame(artifact, frame[["a", "b"]])
            actual = predict_frame(artifact, frame)
            pd.testing.assert_frame_equal(actual, expected)
            self.assertEqual(list(actual.columns), ["score", "prediction", "score_available", "reason"])
            self.assertTrue(actual.attrs["detect_only"])

    def test_future_changes_cannot_change_prefix(self):
        frame = pd.DataFrame({"a": np.tile([.1, .9], 70), "b": 1.})
        altered = frame.copy(); altered.iloc[100:] = 9000
        for policy in ("instant", "2of3", "3of5"):
            artifact = bundle("extra_trees", policy)
            left = predict_frame(artifact, frame).iloc[:100]
            right = predict_frame(artifact, altered).iloc[:100]
            pd.testing.assert_frame_equal(left, right)

    def test_missing_window_and_nonfinite_measurements(self):
        frame = pd.DataFrame({"a": np.full(145, .9), "b": 1.})
        frame.loc[70, "b"] = np.inf
        result = predict_frame(bundle("extra_trees"), frame)
        self.assertFalse(result.score_available.iloc[:59].any())
        self.assertTrue(result.score_available.iloc[69])
        self.assertFalse(result.score_available.iloc[70:130].any())
        self.assertTrue(result.score_available.iloc[130])
        self.assertEqual(result.reason.iloc[70], "current_measurement_missing")
        self.assertEqual(result.reason.iloc[71], "missing_value_in_feature_window")

    def test_explicit_channel_order(self):
        frame = pd.DataFrame({"b": np.full(80, .1), "a": np.full(80, .9)})
        artifact = bundle("baseline", channels=["a", "b"])
        result = predict_frame(artifact, frame)
        np.testing.assert_allclose(result.score.iloc[14:], .9)

    def test_reject_label_channel_and_missing_channel(self):
        with self.assertRaisesRegex(ValueError, "Label columns"):
            predict_frame(bundle(channels=["EVENT"]), pd.DataFrame({"EVENT": [0, 1]}))
        with self.assertRaisesRegex(ValueError, "Missing required"):
            predict_frame(bundle(), pd.DataFrame({"a": [0., 1.]}))

    def test_no_water_safety_or_valve_output(self):
        result = predict_frame(bundle(), pd.DataFrame({"a": [0.], "b": [1.]}))
        self.assertEqual(result.prediction.iloc[0], 0)
        self.assertTrue(result.attrs["normal_prediction_is_not_water_safety_or_valve_permission"])
        self.assertFalse(any("valve" in column or "safe" in column for column in result.columns))

    def test_cli_with_small_fitted_model_and_ignored_label(self):
        rng = np.random.default_rng(19)
        raw = pd.DataFrame({"a": rng.normal(size=100), "b": rng.normal(size=100)})
        X, eligible, _ = build_features(raw, "baseline15", channels=["a", "b"])
        model = IsolationForest(n_estimators=8, max_samples=32, random_state=19, n_jobs=1)
        model.fit(X[eligible])
        artifact = bundle("baseline", "2of3")
        artifact["model"] = model
        expected = predict_frame(artifact, raw)
        raw["EVENT"] = "unused label data"
        with tempfile.TemporaryDirectory(prefix="mawrid-inference-test-") as temporary:
            directory = Path(temporary)
            joblib.dump(artifact, directory/"trusted.joblib")
            raw.to_csv(directory/"input.csv", index=False)
            run = subprocess.run([sys.executable, str(HERE/"predict.py"),
                                  "--model", str(directory/"trusted.joblib"),
                                  "--input", str(directory/"input.csv"),
                                  "--output", str(directory/"predictions.csv")],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            actual = pd.read_csv(directory/"predictions.csv")
            np.testing.assert_allclose(actual.score, expected.score, equal_nan=True)
            np.testing.assert_array_equal(actual.prediction, expected.prediction)
            np.testing.assert_array_equal(actual.score_available, expected.score_available)
            self.assertEqual(list(actual.columns), ["score", "prediction", "score_available", "reason"])
            self.assertIn('"detect_only": true', run.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
