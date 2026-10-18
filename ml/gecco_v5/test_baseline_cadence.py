"""Synthetic tests only; no reserved source or external labels are read."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from baseline_cadence import select_baseline, predict, COMPACT_KEYS

spec = importlib.util.spec_from_file_location(
    "original_baseline_for_cadence_test", HERE.parent / "gecco_v2" / "alarm_policy.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


class BaselineCadenceTests(unittest.TestCase):
    def assert_old_parity(self, labels, scores):
        old, old_trials = legacy.select(labels, scores, baseline=True)
        new, new_trials = select_baseline(labels, scores, 60)
        old_keys = tuple(old)
        self.assertEqual(old, {key: new[key] for key in old_keys})
        self.assertEqual(old_trials, [{key: row[key] for key in old_keys} for row in new_trials])
        np.testing.assert_array_equal(
            legacy.predict(scores, old["threshold"], old["policy"]),
            predict(scores, new["threshold"], new["policy"]))

    @staticmethod
    def cadence_fixture():
        labels = np.zeros(600, bool)
        labels[200:210] = True
        scores = np.zeros(600)
        scores[202:210] = .8
        scores[50] = .9
        return labels, scores

    def test_60_second_exact_parity_with_events_missing_and_ties(self):
        rng = np.random.default_rng(713)
        labels = np.zeros(6000, bool)
        labels[500:520] = True
        labels[1300:1350] = True
        labels[4100:4130] = True
        scores = np.round(rng.normal(0, .1, len(labels)), 2)
        scores[labels] += .6
        scores[[0, 501, 502, 2500]] = np.nan
        scores[2100] = np.inf
        scores[2101] = -np.inf
        self.assert_old_parity(labels, scores)

    def test_60_second_exact_parity_without_events(self):
        scores = np.linspace(0, 1, 2000)
        scores[80:90] = np.nan
        self.assert_old_parity(np.zeros(len(scores), bool), scores)

    def test_60_second_exact_parity_constant_scores(self):
        labels = np.zeros(2000, bool)
        labels[100:110] = True
        self.assert_old_parity(labels, np.ones(len(labels)))

    def test_15_minute_budget_changes_feasible_operating_point(self):
        y, s = self.cadence_fixture()
        minute, _ = select_baseline(y, s, 60)
        quarter, _ = select_baseline(y, s, 900)
        self.assertGreater(minute["threshold"], .9)
        self.assertEqual(quarter["threshold"], .8)
        self.assertEqual((quarter["tp"], quarter["fp"], quarter["fn"]), (8, 1, 2))
        self.assertAlmostEqual(quarter["false_alarm_runs_per_normal_day"], 86400 / (590 * 900))
        self.assertAlmostEqual(quarter["normal_time_under_alarm"], 1 / 590)

    def test_15_minute_delays_and_duration_are_minutes(self):
        y, s = self.cadence_fixture()
        chosen, _ = select_baseline(y, s, 900)
        self.assertEqual(chosen["median_detection_delay_minutes"], 30)
        self.assertEqual(chosen["p95_detection_delay_minutes"], 30)
        self.assertEqual(chosen["normal_alarm_minutes"], 15)
        self.assertEqual(chosen["normal_observed_minutes"], 590 * 15)
        self.assertAlmostEqual(chosen["eligible_normal_days"], 590 * 900 / 86400)

    def test_cadence_changes_only_time_units_for_each_fixed_trial(self):
        y, s = self.cadence_fixture()
        _, minute = select_baseline(y, s, 60)
        _, quarter = select_baseline(y, s, 900)
        self.assertEqual(len(minute), len(quarter))
        for left, right in zip(minute, quarter):
            self.assertEqual(left["threshold"], right["threshold"])
            for key in COMPACT_KEYS:
                if key not in ("eligible_normal_days", "false_alarm_runs_per_normal_day"):
                    self.assertEqual(left[key], right[key])
            self.assertAlmostEqual(left["eligible_normal_days"] * 15, right["eligible_normal_days"])
            self.assertAlmostEqual(left["false_alarm_runs_per_normal_day"] / 15,
                                   right["false_alarm_runs_per_normal_day"])

    def test_normal_alarm_fraction_budget_is_cadence_independent(self):
        y, s = self.cadence_fixture()
        s[50:57] = .9
        chosen, trials = select_baseline(y, s, 900)
        trial = next(row for row in trials if row["threshold"] == .8)
        self.assertLess(trial["false_alarm_runs_per_normal_day"], 1)
        self.assertGreater(trial["normal_time_under_alarm"], .01)
        self.assertFalse(trial["feasible"])
        self.assertGreater(chosen["threshold"], .9)

    def test_unavailable_rows_are_excluded_from_normal_exposure(self):
        y, s = self.cadence_fixture()
        s[300:400] = np.nan
        chosen, _ = select_baseline(y, s, 900)
        self.assertEqual(chosen["normal_valid_count"], 490)
        self.assertEqual(chosen["unavailable_count"], 100)
        self.assertAlmostEqual(chosen["eligible_normal_days"], 490 * 900 / 86400)
        self.assertAlmostEqual(chosen["false_alarm_runs_per_normal_day"], 86400 / (490 * 900))

    def test_frozen_prediction_needs_no_future_labels_and_is_prefix_causal(self):
        y, calibration = self.cadence_fixture()
        chosen, _ = select_baseline(y, calibration, 900)
        future = np.array([0., .9, np.nan, .7, .85, np.inf, .1])
        prefix = predict(future[:4], chosen["threshold"], chosen["policy"])
        full = predict(future, chosen["threshold"], chosen["policy"])
        np.testing.assert_array_equal(prefix, full[:4])
        changed = future.copy(); changed[4:] = 1e9
        np.testing.assert_array_equal(prefix, predict(changed, chosen["threshold"], chosen["policy"])[:4])
        with patch("builtins.open", side_effect=AssertionError("no data reads permitted")):
            repeated, _ = select_baseline(y, calibration, 900)
            self.assertEqual(chosen, repeated)

    def test_all_unavailable_or_no_normal_exposure_cannot_establish_budget(self):
        with self.assertRaises(ValueError):
            select_baseline(np.zeros(10, bool), np.full(10, np.nan), 900)
        with self.assertRaises(ValueError):
            select_baseline(np.ones(10, bool), np.arange(10), 900)
        with self.assertRaises(ValueError):
            select_baseline(np.array([0, 0, 1], bool), [np.nan, np.nan, .8], 900)

    def test_rejects_invalid_cadence_and_labels(self):
        for cadence in (0, -1, np.nan, np.inf, True, None, [900]):
            with self.subTest(cadence=cadence), self.assertRaises(ValueError):
                select_baseline([0, 1], [.1, .8], cadence)
        for labels in ([0., 1.], [0, 2], [[0, 1]], [0]):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                select_baseline(labels, [.1, .8], 900)


if __name__ == "__main__":
    unittest.main()
