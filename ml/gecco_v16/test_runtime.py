"""Synthetic V16 batch-wrapper contract; no source reads or fitted estimators.

Legacy V8 and the head are stubs. These tests exercise routing, provenance,
sensor-only inputs and the actual unchanged V15 policy, not model quality.
"""
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from ml.gecco_v15.runtime import predict as policy_predict
from ml.gecco_v16 import runtime


def choice(low=.5, high=.7):
    return {"anchor_threshold": low, "recovery_threshold": high, "cadence_seconds": 60}


class HeadStub:
    channels = ["a", "b"]

    def __init__(self, scores):
        self.scores = np.asarray(scores, float)
        self.calls = []
        self.fit = Mock(side_effect=AssertionError("Inference must never fit"))
        self.fit_final = Mock(side_effect=AssertionError("Inference must never fit_final"))

    def score(self, frame, v6, v8, *, gap_samples):
        if list(frame.columns) != self.channels:
            raise AssertionError("Head received non-sensor columns or reordered sensors")
        self.calls.append((frame.copy(deep=True), v6.copy(), v8.copy(), gap_samples))
        return self.scores[:len(frame)].copy()


def fixture(low=.5, high=.7):
    v6 = np.array([-1, 0, 1, 1, 0, 0, 1, 0, -1, 1, 0, 0], np.int8)
    v8 = np.array([-1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0], np.int8)
    scores = np.array([np.nan, .1, .8, .1, .1, .8, .1, .8, .9, np.nan, .1, .1])
    index = pd.date_range("2020-01-01", periods=len(v6), freq="min")
    frame = pd.DataFrame({"b": np.arange(len(v6), dtype=float) + 10,
                          "label": np.arange(len(v6)), "a": np.arange(len(v6), dtype=float),
                          "EVENT": -77, "row_id": 999}, index=index)
    legacy = pd.DataFrame({"baseline_prediction": v6.copy(),
        "reference_prediction": v6.copy(), "prediction": v8.copy(),
        "long_context": np.linspace(.01, .12, len(v6)),
        "level": np.arange(len(v6), dtype=float),
        # Deliberately stale availability proves V16 recomputes its own field.
        "available": False}, index=index)
    head = HeadStub(scores)
    reference_bundle = {"fixture": "frozen V8"}
    bundle = {"version": runtime.VERSION, "sample_seconds": 60, "gap_samples": 120,
              "reference_bundle": reference_bundle, "model": head,
              "selected": {"choice": choice(low, high)}}

    def old_reference(passed_bundle, sensors, *, gap_samples):
        if passed_bundle is not reference_bundle:
            raise AssertionError("Wrong inherited reference bundle")
        if list(sensors.columns) != head.channels:
            raise AssertionError("Reference received non-sensor columns")
        return legacy.iloc[:len(sensors)]

    return frame, legacy, head, bundle, old_reference


class RuntimeTests(unittest.TestCase):
    def test_real_fixed_policy_and_availability_match(self):
        frame, legacy, head, bundle, reference = fixture()
        with patch.object(runtime, "reference_frame", side_effect=reference):
            actual = runtime.predict_frame(bundle, frame)
        expected = policy_predict(legacy.reference_prediction.to_numpy(np.int8),
            legacy.prediction.to_numpy(np.int8), head.scores, bundle["selected"]["choice"])
        np.testing.assert_array_equal(actual.prediction, expected)
        np.testing.assert_array_equal(actual.available, expected >= 0)
        np.testing.assert_array_equal(actual.available, legacy.prediction.to_numpy() >= 0)
        self.assertEqual(actual.prediction.dtype, np.dtype("int8"))
        self.assertEqual(actual.available.dtype, np.dtype("bool"))
        self.assertTrue((actual.prediction.to_numpy() != legacy.prediction.to_numpy()).any())

    def test_v8_output_and_score_provenance_are_preserved_separately(self):
        frame, legacy, head, bundle, reference = fixture()
        before = legacy.copy(deep=True)
        with patch.object(runtime, "reference_frame", side_effect=reference):
            actual = runtime.predict_frame(bundle, frame)
        pd.testing.assert_series_equal(actual.v8_prediction, before.prediction, check_names=False)
        pd.testing.assert_series_equal(actual.original_v8_long_context, before.long_context, check_names=False)
        np.testing.assert_array_equal(actual.long_context, head.scores)
        for name in ("baseline_prediction", "reference_prediction", "level"):
            pd.testing.assert_series_equal(actual[name], before[name])
        pd.testing.assert_frame_equal(legacy, before)
        actual.iloc[0, actual.columns.get_loc("level")] = 999
        pd.testing.assert_frame_equal(legacy, before)

    def test_only_ordered_sensors_reach_both_dependencies_and_index_is_preserved(self):
        frame, legacy, head, bundle, reference = fixture()
        with patch.object(runtime, "reference_frame", side_effect=reference) as called:
            actual = runtime.predict_frame(bundle, frame)
        expected = frame.loc[:, head.channels]
        pd.testing.assert_frame_equal(called.call_args.args[1], expected)
        pd.testing.assert_frame_equal(head.calls[0][0], expected)
        pd.testing.assert_index_equal(actual.index, frame.index)
        np.testing.assert_array_equal(head.calls[0][1], legacy.reference_prediction)
        np.testing.assert_array_equal(head.calls[0][2], legacy.prediction)

    def test_future_and_current_label_columns_never_enter_inference(self):
        frame, _, _, bundle, reference = fixture()
        with patch.object(runtime, "reference_frame", side_effect=reference):
            first = runtime.predict_frame(bundle, frame)
            altered = frame.copy(deep=True)
            altered["EVENT"] = np.nan; altered["label"] = 1 - np.arange(len(frame))
            altered["row_id"] = -1; altered["future_truth"] = "do not use"
            second = runtime.predict_frame(bundle, altered)
        pd.testing.assert_frame_equal(first, second)

    def test_gap_is_forwarded_identically_without_dropping_rows_in_wrapper(self):
        for gap in (0, 17, 120):
            with self.subTest(gap=gap):
                frame, _, head, bundle, reference = fixture()
                with patch.object(runtime, "reference_frame", side_effect=reference) as called:
                    actual = runtime.predict_frame(bundle, frame, gap_samples=gap)
                self.assertEqual(len(actual), len(frame))
                self.assertEqual(called.call_args.kwargs, {"gap_samples": gap})
                self.assertEqual(head.calls[0][3], gap)

    def test_unknown_head_scores_preserve_v8_and_cannot_recover(self):
        frame, legacy, head, bundle, reference = fixture()
        head.scores[:] = np.nan
        with patch.object(runtime, "reference_frame", side_effect=reference):
            actual = runtime.predict_frame(bundle, frame)
        np.testing.assert_array_equal(actual.prediction, legacy.prediction)
        np.testing.assert_array_equal(actual.available, legacy.prediction.to_numpy() >= 0)
        self.assertTrue(actual.long_context.isna().all())

    def test_invalid_version_or_cadence_fails_before_any_scoring(self):
        for key, value in (("version", "v15"), ("version", None), ("sample_seconds", 300),
                           ("sample_seconds", 0), ("sample_seconds", True), ("sample_seconds", np.nan)):
            with self.subTest(key=key, value=value):
                frame, _, head, bundle, _ = fixture()
                bundle[key] = value
                with patch.object(runtime, "reference_frame") as called:
                    with self.assertRaises(ValueError): runtime.predict_frame(bundle, frame)
                called.assert_not_called(); self.assertEqual(head.calls, [])

    def test_fixed_policy_rejects_a_non_one_minute_choice(self):
        frame, _, _, bundle, reference = fixture()
        bundle["selected"]["choice"]["cadence_seconds"] = 300
        with patch.object(runtime, "reference_frame", side_effect=reference):
            with self.assertRaises(ValueError): runtime.predict_frame(bundle, frame)

    def test_missing_or_duplicate_sensor_is_rejected_before_scoring(self):
        frame, _, head, bundle, _ = fixture()
        invalid = [frame.drop(columns="a"), pd.concat([frame, frame[["a"]]], axis=1),
                   frame.to_numpy()]
        for value in invalid:
            with self.subTest(kind=type(value).__name__):
                with patch.object(runtime, "reference_frame") as called:
                    with self.assertRaises(ValueError): runtime.predict_frame(bundle, value)
                called.assert_not_called(); self.assertEqual(head.calls, [])

    def test_inputs_scores_choice_and_reference_are_unmodified_and_no_fit_called(self):
        frame, legacy, head, bundle, reference = fixture()
        before_frame, before_legacy = frame.copy(deep=True), legacy.copy(deep=True)
        before_scores = head.scores.copy(); before_choice = deepcopy(bundle["selected"])
        with patch.object(runtime, "reference_frame", side_effect=reference):
            first = runtime.predict_frame(bundle, frame)
            second = runtime.predict_frame(bundle, frame)
        pd.testing.assert_frame_equal(first, second)
        pd.testing.assert_frame_equal(frame, before_frame); pd.testing.assert_frame_equal(legacy, before_legacy)
        np.testing.assert_array_equal(head.scores, before_scores)
        self.assertEqual(bundle["selected"], before_choice)
        head.fit.assert_not_called(); head.fit_final.assert_not_called()

    def test_prefix_calls_reset_policy_and_keep_original_axis(self):
        frame, _, _, bundle, reference = fixture()
        with patch.object(runtime, "reference_frame", side_effect=reference):
            full = runtime.predict_frame(bundle, frame)
            for stop in (0, 1, 2, 3, 7, len(frame)):
                prefix = runtime.predict_frame(bundle, frame.iloc[:stop])
                pd.testing.assert_frame_equal(prefix, full.iloc[:stop])


if __name__ == "__main__":
    unittest.main()
