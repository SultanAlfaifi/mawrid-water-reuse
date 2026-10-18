"""Synthetic accounting tests; no sensor source, annotation file or result is read."""
import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np

from unknown_label_metrics import stats, comparison, _stats, _comparison


def oracle(labels, predictions):
    """Small scalar reference on the original axis, independent of vector masks."""
    result = dict(tp=0, fp=0, fn=0, tn=0, false_positive_runs=0,
                  available_rows=0, true_events=0, confirmed_event_ids=[],
                  confirmed_times=[], known_positive_segments=0)
    previous_false = False
    for label, prediction in zip(labels, predictions):
        if prediction != -1:
            result["available_rows"] += 1
        false = label == 0 and prediction == 1
        if false and not previous_false:
            result["false_positive_runs"] += 1
        previous_false = false
        if label != -1 and prediction != -1:
            key = { (1, 1): "tp", (0, 1): "fp", (1, 0): "fn", (0, 0): "tn" }[
                (int(label), int(prediction))]
            result[key] += 1
    index = 0
    while index < len(labels):
        if labels[index] != 1:
            index += 1
            continue
        start = index
        while index < len(labels) and labels[index] == 1:
            index += 1
        result["known_positive_segments"] += 1
        segment_id = result["known_positive_segments"]
        if start == 0 or labels[start - 1] != 0:
            continue
        result["true_events"] += 1
        for t in range(start, index):
            if predictions[t] == 1 and predictions[t - 1] == 0:
                result["confirmed_event_ids"].append(segment_id)
                result["confirmed_times"].append(t)
                break
    return result


class UnknownLabelMetricsTests(unittest.TestCase):
    def test_known_positive_segments_do_not_invent_onsets_across_unknowns(self):
        y = [0, 1, 1, -1, 1, 1, 0, 1, 0]
        p = [0, 1, 1, 0, 1, 1, 0, 1, 0]
        result = stats(y, p, 10)
        self.assertEqual(result["known_positive_segments"], 3)
        self.assertEqual(result["true_events"], 2)
        self.assertEqual(result["primary_event_ids"], [1, 3])
        self.assertEqual(result["left_censored_segment_ids"], [2])
        self.assertEqual(result["confirmed_event_ids"], [1, 3])
        self.assertEqual(result["confirmed_times"], [1, 7])
        self.assertEqual(result["left_censored_positive_rows"], 2)
        self.assertEqual(result["left_censored_positive_alarm_coverage"], 1)
        self.assertTrue(result["known_positive_segment_details"][0]["right_censored"])

    def test_first_row_positive_has_no_established_onset(self):
        result = stats([1, 1, 0, 1, 1, 0], [0, 1, 0, 1, 1, 0])
        self.assertEqual(result["known_positive_segments"], 2)
        self.assertEqual(result["true_events"], 1)
        self.assertEqual(result["confirmed_event_ids"], [2])
        censored = result["known_positive_segment_details"][0]
        self.assertEqual(censored["left_censor_reason"], "series_start")
        self.assertEqual(censored["confirmed_transition_index"], 1)
        self.assertEqual(result["left_censored_positive_observed_fraction"], 1)

    def test_right_censoring_does_not_remove_an_established_onset(self):
        for y in ([0, 1, 1], [0, 1, 1, -1]):
            with self.subTest(y=y):
                result = stats(y, [0, 1, 1, 0][:len(y)])
                self.assertEqual(result["true_events"], 1)
                self.assertEqual(result["confirmed_events"], 1)
                self.assertEqual(result["right_censored_positive_segments"], 1)
                self.assertEqual(result["fully_bounded_positive_segments"], 0)

    def test_confirmed_start_requires_adjacent_original_zero_to_one(self):
        for p in ([1, 1, 1, 0], [0, -1, 1, 0], [-1, 1, 1, 0]):
            with self.subTest(p=p):
                result = stats([0, 1, 1, 0], p)
                self.assertEqual(result["confirmed_events"], 0)
                self.assertEqual(result["primary_events_with_any_alarm"], 1)
        result = stats([0, 1, 1, 1, 0], [1, 1, 0, 1, 0], 5)
        self.assertEqual(result["confirmed_times"], [3])
        self.assertEqual(result["confirmed_latency_seconds"], [10])

    def test_no_compression_of_unknown_label_rows_into_a_new_transition(self):
        # Compressing to known labels would place p=0 beside p=1 falsely.
        result = stats([0, -1, 1, 1, 0], [0, 1, 1, 1, 0])
        self.assertEqual(result["sensor_confirmed_alarm_starts"], 1)
        self.assertEqual(result["true_events"], 0)
        self.assertEqual(result["confirmed_events"], 0)
        self.assertEqual(result["known_positive_segment_details"][0]["confirmed_transition_index"], None)

    def test_false_runs_break_at_unknown_labels_without_masking_predictions(self):
        result = stats([0, -1, 0, 0], [1, 1, 1, 1], 10)
        self.assertEqual(result["false_positive_runs"], 2)
        self.assertEqual(result["sensor_confirmed_alarm_starts"], 0)
        self.assertEqual(result["fp"], 3)
        self.assertEqual(result["fp_duration_seconds"], 30)
        self.assertEqual(result["normal_observed_seconds"], 30)
        self.assertEqual(result["false_runs_per_day"], 5760)
        self.assertEqual(result["available_rows"], 4)
        self.assertEqual(result["unknown_label_observed_rows"], 1)

    def test_false_runs_break_at_unavailable_sensor_prediction(self):
        result = stats([0, 0, 0], [1, -1, 1], 30)
        self.assertEqual(result["false_positive_runs"], 2)
        self.assertEqual(result["normal_observed_seconds"], 60)
        self.assertEqual(result["normal_unavailable_rows"], 1)

    def test_point_counts_require_both_known_label_and_available_prediction(self):
        result = stats([-1, -1, 0, 1, 0, 1, 0, 1], [1, 0, 1, 0, 0, 1, -1, -1])
        self.assertEqual([result[k] for k in ("tp", "fp", "fn", "tn")], [1, 1, 1, 1])
        self.assertEqual(result["known_observed_rows"], 4)
        self.assertEqual(result["available_rows"], 6)
        self.assertEqual(result["known_label_rows"], 6)
        self.assertEqual(result["unknown_label_rows"], 2)
        self.assertEqual(result["point_positive_observed_fraction"], 2 / 3)
        self.assertEqual(result["point_positive_alarm_coverage"], 1 / 3)
        self.assertEqual(result["precision"], .5)
        self.assertEqual(result["recall_observed_positive"], .5)
        self.assertEqual(result["f1_observed_points"], .5)

    def test_conditional_point_recall_does_not_hide_missing_positive_coverage(self):
        result = stats([0, 1, 1, 0], [0, 1, -1, 0])
        self.assertEqual(result["recall_observed_positive"], 1)
        self.assertEqual(result["point_positive_observed_fraction"], .5)
        self.assertEqual(result["point_positive_alarm_coverage"], .5)
        self.assertEqual(result["positive_unavailable_rows"], 1)
        self.assertEqual(result["true_events"], 1)

    def test_fully_unavailable_events_remain_in_primary_denominator(self):
        result = stats([0, 1, 1, 0, 1, 0], [-1] * 6)
        self.assertEqual(result["true_events"], 2)
        self.assertEqual(result["primary_events_fully_unobserved"], 2)
        self.assertEqual(result["confirmed_event_recall"], 0)
        self.assertEqual(result["point_positive_observed_fraction"], 0)
        self.assertEqual(result["tp"] + result["fp"] + result["fn"] + result["tn"], 0)
        self.assertIsNone(result["normal_alarm_fraction"])
        self.assertIsNone(result["false_runs_per_day"])
        self.assertIsNone(result["recall_observed_positive"])

    def test_all_unknown_labels_do_not_hide_sensor_coverage(self):
        result = stats([-1, -1, -1], [0, 1, -1])
        self.assertEqual(result["available_rows"], 2)
        self.assertEqual(result["known_observed_rows"], 0)
        self.assertEqual(result["false_positive_runs"], 0)
        self.assertEqual(result["normal_observed_seconds"], 0)
        self.assertIsNone(result["confirmed_event_recall"])
        self.assertIsNone(result["false_runs_per_day"])
        self.assertIsNone(result["known_label_observed_fraction"])

    def test_loss_list_uses_id_not_equal_event_totals(self):
        y = [0, 1, 1, 0, 1, 1, 0]
        base = [0, 1, 0, 1, 1, 1, 0]
        candidate = [0, 0, 0, 0, 1, 1, 0]
        result = comparison(y, base, candidate)
        self.assertEqual(result["baseline"]["confirmed_events"], 1)
        self.assertEqual(result["candidate"]["confirmed_events"], 1)
        self.assertEqual(result["lost_baseline_event_ids"], [1])
        self.assertEqual(result["new_candidate_event_ids"], [2])
        self.assertEqual(result["paired_extra_delays"], [])

    def test_detection_in_censored_continuation_does_not_rescue_lost_onset(self):
        result = comparison([0, 1, -1, 1, 0], [0, 1, 0, 1, 0], [0, 0, 0, 1, 0])
        self.assertEqual(result["lost_baseline_event_ids"], [1])
        self.assertEqual(result["candidate"]["confirmed_events"], 0)
        self.assertEqual(result["new_candidate_event_ids"], [])

    def test_paired_delays_use_original_indices_and_same_interval(self):
        y = [0, 1, 1, 1, 0, -1, 0, 1, 1, 1, 0]
        base = [0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 0]
        candidate = [0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0]
        result = comparison(y, base, candidate, .5)
        self.assertEqual(result["retained_baseline_event_ids"], [1, 2])
        self.assertEqual([x["extra_delay_seconds"] for x in result["paired_extra_delays"]], [1, -1])
        self.assertEqual([x["candidate_confirmation_index"] for x in result["paired_extra_delays"]], [3, 7])
        self.assertEqual(result["baseline"]["confirmed_latency_seconds"], [0, 1])

    def test_availability_comparison_is_independent_of_label_knowledge(self):
        base, candidate = [0, 1, -1, 0], [-1, 1, 0, 0]
        unknown = comparison([-1] * 4, base, candidate)
        known = comparison([0] * 4, base, candidate)
        for key in ("hidden_baseline_rows", "added_candidate_available_rows",
                    "sensor_availability_equal", "common_sensor_available_rows"):
            self.assertEqual(unknown[key], known[key])
        self.assertEqual(unknown["hidden_baseline_rows"], 1)
        self.assertEqual(unknown["added_candidate_available_rows"], 1)
        self.assertFalse(unknown["sensor_availability_equal"])
        self.assertEqual(unknown["common_known_observed_rows"], 0)

    def test_empty_integer_arrays_and_zero_denominators_are_explicit(self):
        empty = np.empty(0, dtype=np.int8)
        result = stats(empty, empty)
        self.assertEqual(result["true_events"], 0)
        self.assertEqual(result["known_positive_segments"], 0)
        self.assertEqual(result["available_rows"], 0)
        for key in ("false_runs_per_day", "confirmed_event_recall", "normal_alarm_fraction",
                    "sensor_available_fraction", "point_positive_observed_fraction"):
            self.assertIsNone(result[key])
        self.assertTrue(comparison(empty, empty, empty)["sensor_availability_equal"])
        json.dumps(result, allow_nan=False)

    def test_cadence_scaling_changes_duration_rate_and_latency_only(self):
        y, p = [0, 1, 1, 1, 0], [1, 0, 0, 1, 1]
        slow, fast = stats(y, p, 60), stats(y, p, 10)
        for key in ("tp", "fp", "fn", "tn", "true_events", "confirmed_times"):
            self.assertEqual(slow[key], fast[key])
        self.assertEqual(slow["normal_observed_seconds"], 6 * fast["normal_observed_seconds"])
        self.assertEqual(slow["fp_duration_seconds"], 6 * fast["fp_duration_seconds"])
        self.assertEqual(slow["confirmed_latency_seconds"][0], 6 * fast["confirmed_latency_seconds"][0])
        self.assertEqual(fast["false_runs_per_day"], 6 * slow["false_runs_per_day"])

    def test_v5_keys_match_on_known_binary_labels_with_established_first_onset(self):
        path = Path(__file__).resolve().parents[1] / "gecco_v5" / "calibration.py"
        spec = importlib.util.spec_from_file_location("v5_source_reference_for_metrics_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rng = np.random.default_rng(501)
        for _ in range(30):
            y = rng.integers(0, 2, 60, dtype=np.int8)
            y[0] = 0
            p = rng.integers(-1, 2, 60, dtype=np.int8)
            actual, prior = stats(y, p, 10), module._stats(y, p, 10)
            for key, value in prior.items():
                self.assertEqual(actual[key], value, key)

    def test_scalar_oracle_on_varied_unknown_and_missing_patterns(self):
        rng = np.random.default_rng(19)
        for n in (0, 1, 2, 3, 4, 7, 30, 80):
            for _ in range(30):
                y = rng.integers(-1, 2, n, dtype=np.int8)
                p = rng.integers(-1, 2, n, dtype=np.int8)
                actual = stats(y, p, 15)
                for key, value in oracle(y, p).items():
                    self.assertEqual(actual[key], value, (n, key))
                self.assertEqual(actual["known_observed_rows"], sum(actual[k] for k in ("tp", "fp", "fn", "tn")))
                json.dumps(actual, allow_nan=False)

    def test_shapes_dtypes_values_and_cadence_are_validated(self):
        invalid_arrays = (np.array([0., 1.]), np.array([0, 2]), np.array([[0, 1]]),
                          np.array(["0", "1"]), np.array([0, 1], dtype=object))
        for bad in invalid_arrays:
            for label_bad in (True, False):
                with self.subTest(bad=repr(bad), label_bad=label_bad):
                    with self.assertRaises(ValueError):
                        stats(bad if label_bad else [0, 1], [0, 1] if label_bad else bad)
        with self.assertRaises(ValueError):
            stats([0, 1], [0])
        with self.assertRaises(ValueError):
            comparison([0, 1], [0, 1], [0])
        for cadence in (0, -1, np.nan, np.inf, -np.inf, True, "60", [60], np.array(60)):
            with self.subTest(cadence=repr(cadence)):
                with self.assertRaises(ValueError):
                    stats([0, 1], [0, 1], cadence)
        with self.assertRaises(ValueError):
            stats([0, 1], [0, 1], np.finfo(float).max)

    def test_inputs_unchanged_and_v5_wrappers_work(self):
        y = np.array([0, 1, -1, 1, 0], dtype=np.int8)
        p = np.array([0, 1, 0, 1, -1], dtype=np.int8)
        before_y, before_p = y.copy(), p.copy()
        y.flags.writeable = False
        p.flags.writeable = False
        self.assertEqual(_stats(y, p, cadence_seconds=10), stats(y, p, 10))
        self.assertEqual(_comparison(y, p, p, 10), comparison(y, p, p, 10))
        np.testing.assert_array_equal(y, before_y)
        np.testing.assert_array_equal(p, before_p)


if __name__ == "__main__":
    unittest.main()
