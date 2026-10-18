import unittest
import numpy as np
from evaluation import compare_period, gates, assess_series


class AcceptanceTests(unittest.TestCase):
    def test_same_event_count_does_not_hide_changed_identity(self):
        y = np.array([0,1,1,0,0,1,1,0], bool)
        p = compare_period(y, np.array([0,1,0,0,0,0,0,0]), np.array([0,0,0,0,0,1,0,0]))
        self.assertEqual(p['baseline']['confirmed_new_alarm_inside_events'], 1)
        self.assertEqual(p['candidate']['confirmed_new_alarm_inside_events'], 1)
        self.assertEqual(len(p['lost_baseline_events']), 1)
        self.assertFalse(p['noninferior'])

    def test_abstention_cannot_hide_false_alarms(self):
        y = np.zeros(6, bool)
        p = compare_period(y, np.array([0,1,0,1,0,0]), np.array([0,-1,0,-1,0,0]))
        self.assertEqual(p['baseline_observed_rows_hidden_by_candidate'], 2)
        self.assertFalse(gates([p])['stable_joint_improvement'])

    def test_longer_false_alarm_cannot_win_on_fewer_runs(self):
        y = np.array([0,0,0,0,0,0,0,0,1,1,0], bool)
        b = np.array([0,1,0,1,0,0,0,0,1,0,0])
        c = np.array([0,1,1,1,1,0,0,0,1,0,0])
        p = compare_period(y,b,c)
        self.assertLess(p['candidate']['false_positive_runs'],p['baseline']['false_positive_runs'])
        self.assertFalse(gates([p])['stable_joint_improvement'])

    def test_period_regression_cannot_hide_behind_pooling(self):
        y = np.array([0,1,1,0,0,0,0,0], bool)
        first = compare_period(y,np.array([0,1,0,1,0,1,0,0]),np.array([0,1,0,0,0,0,0,0]))
        second = compare_period(y,np.array([0,1,0,0,0,0,0,0]),np.array([0,1,0,1,0,0,0,0]))
        r = gates([first,second])
        self.assertTrue(r['pooled_joint_improvement'])
        self.assertFalse(r['stable_joint_improvement'])

    def test_real_reduction_with_event_preservation_passes(self):
        y = np.array([0,1,1,0,0,0], bool)
        p = compare_period(y,np.array([0,1,0,1,0,0]),np.array([0,0,1,0,0,0]))
        r = gates([p])
        self.assertTrue(r['stable_joint_improvement'])
        self.assertEqual(p['paired_detection_delays'][0]['extra_delay_minutes'],1)

    def test_unavailable_events_stay_in_denominator(self):
        y = np.array([0,1,1,0,0,0], bool)
        p = compare_period(y,np.array([0,-1,-1,0,0,0]),np.array([0,-1,-1,0,0,0]))
        self.assertEqual(gates([p])['totals']['candidate']['true_events'],1)

    def test_no_invented_transition_between_disjoint_periods(self):
        a = compare_period(np.array([0,0],bool), np.array([0,0]),np.array([0,0]))
        b = compare_period(np.array([1,1,0],bool), np.array([1,1,0]),np.array([1,1,0]))
        self.assertEqual(gates([a,b])['totals']['candidate']['confirmed_new_alarm_inside_events'],0)

    def test_cadence_changes_days_and_latency_not_event_identity(self):
        y = np.array([0,1,1,0,0,0],bool)
        b = np.array([0,1,0,1,0,0]);c = np.array([0,0,1,0,0,0])
        minute = compare_period(y,b,c)
        hourly = compare_period(y,b,c,sample_seconds=3600)
        self.assertAlmostEqual(hourly['baseline']['false_alarm_runs_per_normal_day'],minute['baseline']['false_alarm_runs_per_normal_day']/60)
        self.assertEqual(hourly['paired_detection_delays'][0]['extra_delay_minutes'],60)
        self.assertEqual(gates([hourly])['totals']['baseline']['normal_alarm_minutes'],60)
        self.assertTrue(gates([hourly])['stable_joint_improvement'])

    def test_cross_period_event_is_only_counted_once_in_totals(self):
        y = np.array([0,1,1,1,1,0],bool)
        b = np.array([0,1,0,0,1,0])
        r = assess_series(y,b,b,[0,3,6])
        self.assertEqual(r['gates']['period_event_occurrences'],2)
        self.assertEqual(r['gates']['totals']['baseline']['true_events'],1)
        self.assertEqual(r['gates']['totals']['baseline']['confirmed_new_alarm_inside_events'],1)

if __name__ == '__main__':unittest.main()
