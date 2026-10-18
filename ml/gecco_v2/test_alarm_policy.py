"""Behavioral tests using synthetic scores only; no benchmark data is loaded."""
from __future__ import annotations

import unittest

import numpy as np

from alarm_policy import predict, select


class PredictionTests(unittest.TestCase):
    def test_instant_threshold_and_nonfinite_values(self):
        actual = predict([.1, .5, .8, np.nan, np.inf, -np.inf], .5)
        np.testing.assert_array_equal(actual, [0, 1, 1, -1, -1, -1])

    def test_two_of_three_votes_and_warmup(self):
        actual = predict([1, 0, 1, 0, 0, 1], .5, "2of3")
        np.testing.assert_array_equal(actual, [-1, -1, 1, 0, 0, 0])

    def test_three_of_five_votes_and_warmup(self):
        actual = predict([1, 0, 1, 0, 1, 0, 1], .5, "3of5")
        np.testing.assert_array_equal(actual, [-1, -1, -1, -1, 1, 0, 1])

    def test_missing_resets_complete_window(self):
        for missing in [np.nan, np.inf, -np.inf]:
            actual = predict([1, 1, 1, missing, 1, 1, 1], .5, "2of3")
            np.testing.assert_array_equal(actual, [-1, -1, 1, -1, -1, -1, 1])

    def test_future_changes_cannot_change_past_predictions(self):
        original = np.array([.2, .8, .7, .1, np.nan, .8, .9, .1, .7, .8, .9])
        changed = original.copy()
        changed[7:] = [np.nan, 100, -100, 20]
        for policy in ["instant", "2of3", "3of5"]:
            np.testing.assert_array_equal(predict(original, .5, policy)[:7],
                                          predict(changed, .5, policy)[:7])
            np.testing.assert_array_equal(predict(original[:7], .5, policy),
                                          predict(original, .5, policy)[:7])

    def test_empty_and_insufficient_history(self):
        self.assertEqual(predict([], .5).size, 0)
        np.testing.assert_array_equal(predict([1, 1], .5, "3of5"), [-1, -1])

    def test_invalid_inputs_fail_explicitly(self):
        with self.assertRaises(ValueError):
            predict([[1, 0]], .5)
        with self.assertRaises(ValueError):
            predict([1], np.nan)
        with self.assertRaises(ValueError):
            predict([1], .5, "unknown")


class SelectionTests(unittest.TestCase):
    def test_baseline_exact_quantile_grid_and_instant_policy(self):
        scores = np.linspace(.1, .9, 5000)
        labels = np.zeros(5000, dtype=bool)
        labels[4900:4950] = True
        _, trials = select(labels, scores, baseline=True)
        quantiles = np.unique(np.r_[0, .5, .75, np.linspace(.8, .99, 191),
                                    np.linspace(.99, 1, 201)])
        expected = np.unique(np.r_[np.quantile(scores, quantiles),
                                    np.nextafter(scores.max(), np.inf)])
        np.testing.assert_array_equal([trial["threshold"] for trial in trials], expected)
        self.assertEqual({trial["policy"] for trial in trials}, {"instant"})

    def test_voting_recovers_event_without_accepting_frequent_spikes(self):
        labels = np.zeros(6000, dtype=bool)
        labels[3000:3030] = True
        scores = np.zeros(6000)
        scores[3000:3030] = .8
        scores[np.arange(100, 2100, 200)] = .99
        baseline, _ = select(labels, scores, baseline=True)
        chosen, trials = select(labels, scores)
        self.assertEqual(baseline["recall"], 0)
        self.assertEqual(chosen["policy"], "2of3")
        self.assertEqual(chosen["confirmed_new_alarm_inside_event_recall"], 1)
        self.assertGreater(chosen["recall"], .9)
        self.assertLessEqual(chosen["false_alarm_runs_per_normal_day"], 1)
        self.assertLessEqual(chosen["normal_time_under_alarm"], .01)
        self.assertTrue(any(not row["feasible"] for row in trials))
        self.assertTrue(all(not key.endswith("records") for row in trials for key in row))

    def test_long_false_alarm_rejected_even_when_episode_rate_passes(self):
        labels = np.zeros(6000, dtype=bool)
        labels[1000:1010] = True
        scores = np.zeros(6000)
        scores[1000:1010] = .8
        scores[2000:2200] = .9
        chosen, trials = select(labels, scores)
        self.assertEqual(chosen["fp"], 0)
        self.assertEqual(chosen["recall"], 0)
        self.assertTrue(any(row["false_alarm_runs_per_normal_day"] <= 1
                            and row["normal_time_under_alarm"] > .01
                            and not row["feasible"] for row in trials))

    def test_no_events_uses_lowest_feasible_two_of_three_threshold(self):
        labels = np.zeros(6000, dtype=bool)
        scores = np.zeros(6000)
        scores[np.arange(500, 5501, 1000)] = 1
        chosen, trials = select(labels, scores)
        feasible = [r["threshold"] for r in trials
                    if r["feasible"] and r["policy"] == "2of3"]
        self.assertTrue(chosen["no_events"])
        self.assertEqual(chosen["policy"], "2of3")
        self.assertEqual(chosen["threshold"], min(feasible))
        self.assertLessEqual(chosen["threshold"], scores.max())
        baseline, _ = select(labels, scores, baseline=True)
        self.assertEqual(baseline["policy"], "instant")
        self.assertGreater(baseline["threshold"], scores.max())

    def test_selection_rejects_unmeasurable_constraints(self):
        with self.assertRaises(ValueError):
            select([False, False], [np.nan, np.nan])
        with self.assertRaises(ValueError):
            select(np.ones(20, dtype=bool), np.linspace(0, 1, 20))
        with self.assertRaises(ValueError):
            select([False], [0, 1])


if __name__ == "__main__":
    unittest.main()
