"""Synthetic-only batch/stream parity tests; no source, fitting, or bundle I/O."""
import copy
import unittest

import numpy as np
import pandas as pd

from runtime_v4 import (predict_frame, StreamingPredictor, RecoveryEventDetector,
                        baseline_predict, suppression_predict, guarded_shape,
                        corroborated_scores, joint_predict)


CHANNELS = ["base", "shape", "level", "jump", "sustained"]


class FakeClassifier:
    def predict_proba(self, X):
        values = X[:, 0]
        return np.column_stack([1. - values, values])


class FakePrior(RecoveryEventDetector):
    def __init__(self):
        self.channels = list(CHANNELS)
        self.max_lookback_ = 60
        self.shape_ = FakeClassifier()

    def _baseline_score(self, frame):
        return frame.base.to_numpy(float)

    def features(self, frame):
        values = frame[["shape"]].to_numpy(float)
        return values, np.isfinite(values[:, 0])

    def score_components(self, frame):
        raise AssertionError("Runtime must call the raw parent, not the supported override")


class FakeLocal:
    def __init__(self, bounded_history=False):
        self.channels = list(CHANNELS)
        self.max_lookback_ = 74
        self.bounded_history = bounded_history

    def score_components(self, frame):
        result = {k: frame[k].to_numpy(float) for k in ("level", "jump", "sustained")}
        if self.bounded_history:
            result["sustained"] = frame.sustained.shift(74).to_numpy(float)
        return result


def bundle(*, history=False, guard_policy="instant", rescue="level", rescue_policy="instant"):
    return {"local_model": FakeLocal(history),
            "prior_bundle": {"model": FakePrior(), "baseline_threshold": .5, "baseline_policy": "instant"},
            "guard_selected": {"decision": "candidate", "threshold": .5, "policy": guard_policy},
            "shape_support_threshold": .5,
            "selected": {"seed": "guarded", "rescue": rescue, "threshold": 2., "policy": rescue_policy}}


def frame(n=350):
    return pd.DataFrame({"base": np.full(n, .1), "shape": np.full(n, .1),
                         "level": np.full(n, .2), "jump": np.full(n, .2),
                         "sustained": np.full(n, .2)})


class RuntimeV4Tests(unittest.TestCase):
    def assert_equal(self, actual, expected):
        pd.testing.assert_frame_equal(actual, expected, check_exact=False, rtol=1e-12, atol=1e-12)

    def test_batch_matches_explicit_runner_pipeline(self):
        b = bundle(guard_policy="2of3", rescue_policy="3of5")
        f = frame()
        f.loc[145:155, ["level", "jump", "shape"]] = [3., 3., .8]
        f.loc[180:320, "base"] = .8
        f.loc[190, "shape"] = np.nan
        tail = f.iloc[120:].reset_index(drop=True)
        local = b["local_model"].score_components(tail)
        raw = RecoveryEventDetector.score_components(b["prior_bundle"]["model"], tail)
        scores = {k: np.r_[np.full(120, np.nan), v] for k, v in local.items()}
        scores["shape_raw"] = np.r_[np.full(120, np.nan), raw["shape"]]
        base = baseline_predict(np.r_[np.full(120, np.nan), raw["baseline"]], .5)
        guard = guarded_shape(scores, scores["shape_raw"])
        seed = suppression_predict(guard, base, b["guard_selected"])
        rescue = corroborated_scores(scores, .5)
        result = joint_predict(base, seed, rescue, b["selected"])
        actual = predict_frame(b, f)
        np.testing.assert_array_equal(actual.baseline_prediction, base)
        np.testing.assert_array_equal(actual.guarded_prediction, seed)
        np.testing.assert_array_equal(actual.prediction, result)
        for key, value in scores.items():
            np.testing.assert_allclose(actual[key], value, equal_nan=True)

    def test_stream_equals_batch_with_long_alarm_and_reset(self):
        b = bundle(rescue=None)
        f = frame(420)
        f.loc[10:250, "base"] = .8
        f.loc[10, "shape"] = .8  # Retained start; after that the gate says suppress.
        f.loc[260:400, "base"] = .8  # New alarm is fully suppressed after reset.
        actual_stream = StreamingPredictor(b, gap_samples=0)
        actual = actual_stream.update_frame(f)
        expected = predict_frame(b, f, gap_samples=0)
        self.assert_equal(actual, expected)
        self.assertTrue((actual.guarded_prediction.iloc[10:251] == 1).all())
        self.assertTrue((actual.guarded_prediction.iloc[260:401] == 0).all())
        self.assertEqual(len(actual_stream.sensor_rows), 75)
        self.assertEqual(len(actual_stream.score_history), 5)

    def test_all_persistence_policies_and_unknowns_stream_exactly(self):
        f = frame(125)
        f.loc[15:28, "base"] = .8
        f.loc[45:95, "base"] = .8
        f.loc[50:55, "shape"] = np.nan
        f.loc[75, "base"] = np.nan
        f.loc[80:84, "shape"] = .8
        f.loc[100:110, ["level", "jump", "shape"]] = [3., 3., .8]
        f.loc[104, "jump"] = np.nan
        for policy in ("instant", "2of3", "3of5"):
            with self.subTest(policy=policy):
                b = bundle(guard_policy=policy, rescue_policy=policy)
                b["prior_bundle"]["baseline_policy"] = policy
                self.assert_equal(StreamingPredictor(b, gap_samples=0).update_frame(f),
                                  predict_frame(b, f, gap_samples=0))

    def test_suppressed_alarm_does_not_reopen_when_history_slides(self):
        b = bundle(guard_policy="3of5", rescue=None)
        f = frame(200)
        f.loc[20:190, "base"] = .8
        actual = StreamingPredictor(b, gap_samples=0).update_frame(f)
        self.assert_equal(actual, predict_frame(b, f, gap_samples=0))
        self.assertTrue((actual.guarded_prediction.iloc[20:191] == 0).all())

    def test_gap_rows_never_enter_sensor_or_policy_context(self):
        b = bundle(history=True, rescue=None)
        f = frame(250)
        f.loc[:119] = 1e6
        full = predict_frame(b, f)
        independent = predict_frame(b, f.iloc[120:], gap_samples=0)
        self.assert_equal(full.iloc[120:], independent)
        self.assertTrue((full.prediction.iloc[:120] == -1).all())
        self.assertTrue(full.ignored_gap.iloc[:120].all())
        self.assertTrue(full.sustained.iloc[120:194].isna().all())
        stream = StreamingPredictor(b)
        first = stream.update_frame(f.iloc[:120])
        self.assertEqual(len(stream.sensor_rows), 0)
        self.assertEqual(len(stream.score_history), 0)
        remaining = stream.update_frame(f.iloc[120:])
        self.assert_equal(pd.concat([first, remaining]), full)

    def test_stream_chunks_prefix_and_suffix_mutation(self):
        rng = np.random.default_rng(8)
        f = frame(310)
        f["base"] = rng.choice([.1, .8, np.nan], len(f), p=[.5, .45, .05])
        f["shape"] = rng.choice([.1, .8, np.nan], len(f), p=[.4, .55, .05])
        f["level"] = rng.choice([.2, 3.], len(f))
        f["jump"] = rng.choice([.2, 3.], len(f))
        b = bundle(history=True, guard_policy="2of3", rescue_policy="3of5")
        full = predict_frame(b, f, gap_samples=7)
        stream = StreamingPredictor(b, gap_samples=7)
        pieces = [stream.update_frame(f.iloc[a:z]) for a, z in [(0, 2), (2, 50), (50, 150), (150, 310)]]
        self.assert_equal(pd.concat(pieces), full)
        for cut in (0, 1, 7, 40, 150, 309):
            self.assert_equal(predict_frame(b, f.iloc[:cut], gap_samples=7), full.iloc[:cut])
        mutated = f.copy()
        mutated.iloc[200:] = np.nan
        self.assert_equal(predict_frame(b, mutated, gap_samples=7).iloc[:200], full.iloc[:200])

    def test_no_shape_support_disables_rescue_but_not_baseline(self):
        b = bundle()
        b["shape_support_threshold"] = None
        b["guard_selected"] = {"decision": "baseline"}
        f = frame(40)
        f.loc[10:20, ["level", "jump", "shape"]] = [3., 3., .8]
        f.loc[25:30, "base"] = .8
        actual = predict_frame(b, f, gap_samples=0)
        np.testing.assert_array_equal(actual.prediction, actual.baseline_prediction)
        self.assertTrue(actual["rescue__level"].isna().all())
        self.assert_equal(StreamingPredictor(b, gap_samples=0).update_frame(f), actual)

    def test_rescue_requires_current_evidence_and_observed_baseline(self):
        b = bundle(rescue_policy="3of5")
        f = frame(25)
        f.loc[5:9, ["level", "jump", "shape"]] = [3., 3., .8]
        f.loc[8, "base"] = np.nan
        actual = predict_frame(b, f, gap_samples=0)
        self.assertEqual(actual.prediction.iloc[7], 1)
        self.assertEqual(actual.prediction.iloc[8], -1)
        self.assertEqual(actual.prediction.iloc[10], 0)
        np.testing.assert_array_equal(actual.available, actual.baseline_prediction >= 0)

    def test_labels_and_extra_metadata_are_ignored(self):
        b = bundle()
        f = frame(30)
        original = predict_frame(b, f, gap_samples=0)
        f["EVENT"] = np.arange(len(f)) % 2
        f["future_label"] = "never read"
        self.assert_equal(predict_frame(b, f, gap_samples=0), original)
        self.assert_equal(StreamingPredictor(b, gap_samples=0).update_frame(f), original)

    def test_reset_restarts_gap_and_latch(self):
        b = bundle(rescue=None)
        f = frame(40)
        f.loc[10:, ["base", "shape"]] = [.8, .8]
        stream = StreamingPredictor(b, gap_samples=3)
        expected = stream.update_frame(f)
        self.assertTrue(stream.baseline_alarm_latched)
        stream.reset()
        self.assertFalse(stream.baseline_alarm_latched)
        self.assertEqual(stream.samples_seen, 0)
        self.assert_equal(stream.update_frame(f), expected)

    def test_explicit_usage_errors_and_short_periods(self):
        b = bundle()
        for gap in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                predict_frame(b, frame(1), gap_samples=gap)
        with self.assertRaises(ValueError):
            predict_frame(b, frame(2).drop(columns="shape"))
        bad = copy.deepcopy(b)
        bad["local_model"].max_lookback_ = 90
        with self.assertRaises(ValueError):
            StreamingPredictor(bad)
        for n in (0, 1, 119, 120):
            actual = predict_frame(b, frame(n))
            self.assertEqual(len(actual), n)
            self.assertTrue((actual.prediction == -1).all())
            self.assert_equal(StreamingPredictor(b).update_frame(frame(n)), actual)


if __name__ == "__main__":
    unittest.main()
