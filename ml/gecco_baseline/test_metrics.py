"""Regression checks for unavailable samples and unadjusted alarm metrics."""

import json
import unittest

import numpy as np

try:
    from .metrics import evaluate, run_intervals
except ImportError:
    from metrics import evaluate, run_intervals


class RunIntervalsTests(unittest.TestCase):
    def test_runs_at_both_edges_and_singletons(self):
        self.assertEqual(
            run_intervals([True, True, False, True, False, True, True]),
            [(0, 2), (3, 4), (5, 7)],
        )

    def test_empty_all_false_and_all_true(self):
        self.assertEqual(run_intervals([]), [])
        self.assertEqual(run_intervals([False, False]), [])
        self.assertEqual(run_intervals([True, True]), [(0, 2)])


class EvaluateTests(unittest.TestCase):
    def test_always_alarm_on_normal_data_is_one_run_but_all_time_under_alarm(self):
        result = evaluate(np.zeros(2880, dtype=bool), np.ones(2880, dtype=int))
        self.assertEqual(result["false_positive_runs"], 1)
        self.assertEqual(result["alarm_runs"], 1)
        self.assertEqual(result["eligible_normal_days"], 2)
        self.assertEqual(result["false_alarm_runs_per_normal_day"], 0.5)
        self.assertEqual(result["normal_time_under_alarm"], 1)
        self.assertEqual(result["false_positive_rate"], 1)
        self.assertEqual(result["fp"], 2880)
        self.assertEqual(result["precision"], 0)
        self.assertEqual(result["f1"], 0)
        self.assertIsNone(result["event_recall"])

    def test_event_crossing_unavailability_keeps_original_start_and_delay(self):
        result = evaluate(
            [False, True, True, True, True, False],
            [0, -1, -1, 0, 1, 0],
        )
        self.assertEqual((result["tp"], result["fp"], result["fn"], result["tn"]), (1, 0, 1, 2))
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["event_recall"], 1)
        self.assertEqual(result["median_detection_delay_minutes"], 3)
        self.assertEqual(result["new_alarm_inside_events"], 1)
        self.assertEqual(result["event_records"][0]["valid_count"], 2)
        self.assertEqual(result["event_records"][0]["first_alarm_index"], 4)

    def test_normal_tails_are_separate_false_alarm_runs(self):
        result = evaluate(
            [False, False, True, True, False, False],
            [1, 1, 1, 1, 1, 1],
        )
        self.assertEqual(result["alarm_runs"], 1)
        self.assertEqual(result["false_positive_runs"], 2)
        self.assertEqual(result["false_alarm_records"], [
            {"start": 0, "end": 2, "duration_minutes": 2},
            {"start": 4, "end": 6, "duration_minutes": 2},
        ])
        self.assertEqual(result["false_alarm_runs_per_normal_day"], 720)

    def test_no_anomalies_and_no_alarms_has_undefined_event_recall(self):
        result = evaluate([False, False, False], [0, -1, 0])
        self.assertEqual(result["true_events"], 0)
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["unavailable_count"], 1)
        self.assertEqual(result["accuracy"], 1)
        self.assertEqual(result["normal_time_under_alarm"], 0)
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["recall"])
        self.assertIsNone(result["f1"])
        self.assertIsNone(result["event_recall"])
        self.assertIsNone(result["median_detection_delay_minutes"])
        json.dumps(result, allow_nan=False)

    def test_long_alarm_spanning_two_events_counts_onset_coverage(self):
        result = evaluate(
            [False, True, True, False, False, True, True, False],
            [1, 1, 1, 1, 1, 1, 1, 1],
        )
        self.assertEqual(result["alarm_runs"], 1)
        self.assertEqual(result["true_events"], 2)
        self.assertEqual(result["detected_events"], 2)
        self.assertEqual(result["covered_at_onset_events"], 2)
        self.assertEqual(result["new_alarm_inside_events"], 0)
        self.assertEqual(result["event_recall"], 1)
        self.assertEqual(result["new_alarm_inside_event_recall"], 0)
        self.assertEqual(result["confirmed_new_alarm_inside_event_recall"], 0)
        self.assertEqual(result["complete_event_coverage"], 1)
        self.assertEqual(result["complete_event_new_alarm_start_recall"], 0)
        self.assertEqual(result["false_positive_runs"], 3)
        self.assertEqual(result["median_detection_delay_minutes"], 0)
        self.assertTrue(all(not event["alarm_started_at_onset"] for event in result["event_records"]))

    def test_new_alarm_at_onset_and_after_unavailability_are_explicit(self):
        result = evaluate(
            [False, True, True, False, True, True, False],
            [0, 1, 1, -1, 1, 1, 0],
        )
        self.assertEqual(result["new_alarm_inside_event_recall"], 1)
        self.assertEqual(result["raw_new_alarm_inside_event_recall"], 1)
        self.assertEqual(result["raw_new_alarm_inside_events"], 2)
        self.assertEqual(result["complete_raw_new_alarm_start_recall"], 1)
        self.assertEqual(result["confirmed_new_alarm_inside_events"], 1)
        self.assertEqual(result["confirmed_new_alarm_inside_event_recall"], 0.5)
        self.assertEqual(result["complete_confirmed_new_alarm_start_recall"], 0.5)
        self.assertEqual(result["covered_at_onset_events"], 2)
        first, second = result["event_records"]
        self.assertTrue(first["alarm_started_at_onset"])
        self.assertFalse(first["new_alarm_previous_unavailable"])
        self.assertTrue(first["confirmed_new_alarm_inside_event"])
        self.assertEqual(first["confirmed_new_alarm_index"], 1)
        self.assertEqual(first["confirmed_new_alarm_delay_minutes"], 0)
        self.assertTrue(second["alarm_started_at_onset"])
        self.assertTrue(second["new_alarm_previous_unavailable"])
        self.assertTrue(second["new_alarm_previous_unknown"])
        self.assertFalse(second["confirmed_new_alarm_inside_event"])
        self.assertIsNone(second["confirmed_new_alarm_index"])
        self.assertIsNone(second["confirmed_new_alarm_delay_minutes"])

    def test_confirmed_start_after_an_unconfirmed_start_has_its_own_delay(self):
        result = evaluate(
            [False, True, True, True, True, False],
            [-1, 1, 1, 0, 1, 0],
        )
        event = result["event_records"][0]
        self.assertEqual(event["new_alarm_start_index"], 1)
        self.assertTrue(event["new_alarm_previous_unavailable"])
        self.assertTrue(event["confirmed_new_alarm_inside_event"])
        self.assertEqual(event["confirmed_new_alarm_index"], 4)
        self.assertEqual(event["confirmed_new_alarm_delay_minutes"], 3)
        self.assertEqual(result["confirmed_new_alarm_inside_event_recall"], 1)

    def test_onset_coverage_and_later_restart_are_independent(self):
        result = evaluate([False, True, True, True, False], [1, 1, 0, 1, 0])
        event = result["event_records"][0]
        self.assertTrue(event["covered_at_onset"])
        self.assertTrue(event["new_alarm_inside_event"])
        self.assertFalse(event["alarm_started_at_onset"])
        self.assertEqual(event["detection_delay_minutes"], 0)
        self.assertEqual(event["new_alarm_delay_minutes"], 2)
        self.assertEqual(event["new_alarm_start_index"], 3)

    def test_boundary_censored_events_remain_in_overall_recall(self):
        result = evaluate(
            [True, False, True, True, False, True],
            [1, 0, 0, 1, 0, -1],
        )
        self.assertEqual(result["boundary_censored_events"], 2)
        self.assertEqual(result["complete_events"], 1)
        self.assertEqual(result["event_recall"], 2 / 3)
        self.assertEqual(result["new_alarm_inside_event_recall"], 2 / 3)
        self.assertEqual(result["confirmed_new_alarm_inside_event_recall"], 1 / 3)
        self.assertEqual(result["complete_event_coverage"], 1)
        self.assertEqual(result["complete_event_new_alarm_start_recall"], 1)
        self.assertEqual(result["complete_confirmed_new_alarm_start_recall"], 1)
        self.assertTrue(result["event_records"][0]["new_alarm_previous_unknown"])
        self.assertFalse(result["event_records"][0]["confirmed_new_alarm_inside_event"])
        self.assertFalse(result["event_records"][1]["boundary_censored"])

    def test_unscorable_events_are_not_removed_from_event_recall(self):
        result = evaluate(
            [True, True, False, True, False, True, True],
            [-1, -1, 0, 1, 0, -1, 0],
        )
        self.assertEqual(result["true_events"], 3)
        self.assertEqual(result["fully_unscorable_events"], 1)
        self.assertEqual(result["undetected_events"], 2)
        self.assertEqual(result["event_recall"], 1 / 3)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["event_records"][0]["detection_kind"], "undetected")
        self.assertIsNone(result["event_records"][0]["detection_delay_minutes"])
        self.assertEqual(result["median_detection_delay_minutes"], 0)

    def test_delay_percentile_uses_detected_events_only(self):
        result = evaluate(
            [True, True, False, True, True, True, True, False, True],
            [0, 1, 0, 0, 0, 0, 1, 0, 0],
        )
        self.assertEqual(result["detected_events"], 2)
        self.assertEqual(result["undetected_events"], 1)
        self.assertEqual(result["median_detection_delay_minutes"], 2)
        self.assertAlmostEqual(result["p95_detection_delay_minutes"], 2.9)

    def test_unavailable_normal_samples_do_not_inflate_eligible_days(self):
        result = evaluate([False] * 6, [1, 1, -1, 1, 0, -1])
        self.assertEqual(result["normal_valid_count"], 4)
        self.assertEqual(result["false_positive_runs"], 2)
        self.assertEqual(result["normal_time_under_alarm"], 0.75)
        self.assertEqual(result["false_alarm_runs_per_normal_day"], 720)

    def test_empty_and_all_unavailable_results_are_json_safe(self):
        for result in (evaluate([], []), evaluate([True, True, False], [-1, -1, -1])):
            self.assertEqual(result["valid_count"], 0)
            self.assertIsNone(result["accuracy"])
            self.assertIsNone(result["normal_time_under_alarm"])
            self.assertIsNone(result["false_alarm_runs_per_normal_day"])
            json.dumps(result, allow_nan=False)

    def test_invalid_shapes_values_and_types_are_rejected(self):
        for labels, predictions in (
            ([True], [0, 1]),
            ([[True]], [[1]]),
            ([True], [2]),
            ([True], [0.0]),
            ([2], [1]),
            ([np.nan], [1]),
        ):
            with self.subTest(labels=labels, predictions=predictions):
                with self.assertRaises(ValueError):
                    evaluate(labels, predictions)


if __name__ == "__main__":
    unittest.main()
