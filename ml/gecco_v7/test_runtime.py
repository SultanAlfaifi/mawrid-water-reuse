"""Adversarial synthetic tests for V7's batch evaluation interface only.

Reference inference is replaced by an instrumented causal fake. Actual V6/V7
bundle parity is checked separately by the full independent replay audit.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v7 import runtime
from ml.gecco_v7.calibration import predict as calibrated_predict


class CausalLongModel:
    def __init__(self, channels=("p1", "p2")):
        self.channels = list(channels)
        self.calls = []

    def score_components(self, frame):
        self.calls.append(frame.copy())
        values = frame[self.channels[0]].rolling(3, min_periods=3).mean().to_numpy()
        return {"long_context": values}


def bundle(policy="instant", low=.3, high=.8, gap=5):
    return {"long_model": CausalLongModel(),
            "reference_bundle": {"local_model": SimpleNamespace(channels=["p1", "p2"])},
            "selected": {"decision": "reference" if low is None and high is None else "candidate",
                         "low_threshold": low, "high_threshold": high, "policy": policy},
            "gap_samples": gap}


def reference_fake(reference_bundle, frame, *, gap_samples):
    channels = reference_bundle["local_model"].channels
    valid = np.isfinite(frame[channels].to_numpy()).all(axis=1)
    ignored = np.arange(len(frame)) < gap_samples
    prediction = np.where(valid & ~ignored, (frame[channels[0]].to_numpy() >= .5).astype(np.int8), -1).astype(np.int8)
    return pd.DataFrame({"baseline_prediction": prediction.copy(), "prediction": prediction,
                         "available": prediction >= 0, "ignored_gap": ignored}, index=frame.index)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"p1": np.r_[np.zeros(5), .8, .9, .8, .1, .2, .7, .8, .9, .1, .2],
                                   "p2": np.ones(15)}, index=pd.date_range("2020-01-01", periods=15, freq="min"))

    def test_gap_discarded_before_long_features_and_passed_to_reference(self):
        state = bundle()
        with patch.object(runtime, "reference_predict", side_effect=reference_fake) as reference:
            result = runtime.predict_frame(state, self.frame)
        supplied = state["long_model"].calls[0]
        pd.testing.assert_frame_equal(supplied, self.frame.iloc[5:].reset_index(drop=True))
        self.assertEqual(reference.call_args.kwargs["gap_samples"], 5)
        self.assertTrue(np.isnan(result.long_context.iloc[:5]).all())
        self.assertTrue((result.prediction.iloc[:5] == -1).all())
        self.assertTrue(result.index.equals(self.frame.index))

    def test_gap_override_and_short_or_empty_periods(self):
        for n in (0, 1, 4, 5, 6, 15):
            for gap in (0, 3, 20):
                state = bundle(gap=12)
                with patch.object(runtime, "reference_predict", side_effect=reference_fake):
                    result = runtime.predict_frame(state, self.frame.iloc[:n], gap_samples=gap)
                self.assertEqual(len(result), n)
                self.assertEqual(len(state["long_model"].calls[0]), max(n - gap, 0))
                self.assertTrue(np.isnan(result.long_context.iloc[:min(n, gap)]).all())

    def test_labels_and_extra_columns_never_reach_either_model(self):
        state = bundle()
        extra = self.frame.assign(EVENT=np.arange(len(self.frame)) % 2, label=-1, timestamp="ignored")
        calls = []
        def spy(*args, **kwargs):
            calls.append(args[1].copy())
            return reference_fake(*args, **kwargs)
        with patch.object(runtime, "reference_predict", side_effect=spy):
            first = runtime.predict_frame(state, extra)
            second = runtime.predict_frame(state, extra.assign(EVENT=99, label=999, timestamp="changed"))
        pd.testing.assert_frame_equal(first, second)
        self.assertTrue(all(frame.columns.tolist() == ["p1", "p2"] for frame in calls + state["long_model"].calls))

    def test_input_column_order_is_canonicalized(self):
        with patch.object(runtime, "reference_predict", side_effect=reference_fake):
            normal = runtime.predict_frame(bundle(), self.frame)
            shuffled = runtime.predict_frame(bundle(), self.frame[["p2", "p1"]])
        pd.testing.assert_frame_equal(normal, shuffled)

    def test_exact_availability_and_reference_unknown_score_fallback(self):
        state = bundle(low=.8, high=.9)
        frame = self.frame.copy()
        frame.iloc[10, frame.columns.get_loc("p2")] = np.nan
        with patch.object(runtime, "reference_predict", side_effect=reference_fake):
            result = runtime.predict_frame(state, frame)
        np.testing.assert_array_equal(result.prediction >= 0, result.reference_prediction >= 0)
        np.testing.assert_array_equal(result.available, result.prediction >= 0)
        self.assertEqual(result.prediction.iloc[10], -1)
        # Long history is not yet available, but reference alarm is preserved.
        self.assertTrue(np.isnan(result.long_context.iloc[5]))
        self.assertEqual(result.reference_prediction.iloc[5], 1)
        self.assertEqual(result.prediction.iloc[5], 1)

    def test_runtime_matches_exact_calibrated_predictor_for_all_policies(self):
        for policy in ("instant", "2of3", "3of5"):
            for low, high in ((None, None), (.4, None), (None, .8), (.3, .8)):
                state = bundle(policy, low, high)
                with patch.object(runtime, "reference_predict", side_effect=reference_fake):
                    result = runtime.predict_frame(state, self.frame)
                expected = calibrated_predict(result.reference_prediction.to_numpy(np.int8), result.long_context.to_numpy(), state["selected"])
                np.testing.assert_array_equal(result.prediction, expected)
                self.assertEqual(result.prediction.dtype, np.int8)

    def test_prefix_and_future_mutation_cannot_change_earlier_outputs(self):
        for policy in ("instant", "2of3", "3of5"):
            state = bundle(policy)
            with patch.object(runtime, "reference_predict", side_effect=reference_fake):
                whole = runtime.predict_frame(state, self.frame)
                for stop in (0, 1, 5, 6, 10, 14):
                    prefix = runtime.predict_frame(state, self.frame.iloc[:stop])
                    pd.testing.assert_frame_equal(prefix, whole.iloc[:stop])
                    changed = self.frame.copy()
                    changed.iloc[stop:, :] = 10000
                    altered = runtime.predict_frame(state, changed)
                    pd.testing.assert_frame_equal(altered.iloc[:stop], whole.iloc[:stop])

    def test_mutating_discarded_gap_cannot_change_any_output(self):
        changed = self.frame.copy()
        changed.iloc[:5, :] = -999999
        with patch.object(runtime, "reference_predict", side_effect=reference_fake):
            original = runtime.predict_frame(bundle(), self.frame)
            altered = runtime.predict_frame(bundle(), changed)
        pd.testing.assert_frame_equal(original, altered)

    def test_calls_reset_state_and_do_not_mutate_inputs(self):
        state = bundle()
        original_frame = self.frame.copy(deep=True)
        original_selection = state["selected"].copy()
        with patch.object(runtime, "reference_predict", side_effect=reference_fake):
            first = runtime.predict_frame(state, self.frame)
            runtime.predict_frame(state, self.frame * 500)
            repeated = runtime.predict_frame(state, self.frame)
        pd.testing.assert_frame_equal(first, repeated)
        pd.testing.assert_frame_equal(self.frame, original_frame)
        self.assertEqual(state["selected"], original_selection)

    def test_invalid_bundle_gap_and_channel_geometry_are_rejected(self):
        with patch.object(runtime, "reference_predict", side_effect=reference_fake):
            for invalid in (None, {}, {"long_model": CausalLongModel()}):
                with self.assertRaises(ValueError): runtime.predict_frame(invalid, self.frame)
            for gap in (-1, 1.5, True, np.nan):
                with self.assertRaises(ValueError): runtime.predict_frame(bundle(), self.frame, gap_samples=gap)
            with self.assertRaises(ValueError): runtime.predict_frame(bundle(), self.frame[["p1"]])
            with self.assertRaises(ValueError): runtime.predict_frame(bundle(), self.frame.to_numpy())
            state = bundle(); state["reference_bundle"]["local_model"].channels.reverse()
            with self.assertRaises(ValueError): runtime.predict_frame(state, self.frame)

    def test_malformed_long_score_shape_is_rejected(self):
        state = bundle()
        with patch.object(runtime, "reference_predict", side_effect=reference_fake), patch.object(
                state["long_model"], "score_components", return_value={"long_context": np.zeros(11)}):
            with self.assertRaises(ValueError): runtime.predict_frame(state, self.frame)


if __name__ == "__main__":
    unittest.main()
