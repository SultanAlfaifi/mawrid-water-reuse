"""Synthetic aggregation regression checks; no dataset reads."""
import unittest
import numpy as np

from empty_periods import assess_sparse_series_allow_empty
from sparse_evaluation import assess_sparse_series


class EmptyPeriodContracts(unittest.TestCase):
    def test_nonempty_exact_parity(self):
        rng=np.random.default_rng(20261016)
        for _ in range(30):
            y=rng.random(150)<.2;b=rng.choice([-1,0,1],150);c=b.copy()
            c[(c==1)&(rng.random(150)<.3)]=0
            slots=26016+np.cumsum(rng.choice([1,3],150))
            bounds=[0,25,50,75,100,125,150]
            self.assertEqual(assess_sparse_series_allow_empty(y,b,c,slots,bounds),
                             assess_sparse_series(y,b,c,slots,bounds))

    def test_empty_period_retained_and_unmeasurable(self):
        y=np.array([0,1,0,0,0],bool);b=np.array([0,1,0,1,0]);c=b.copy()
        out=assess_sparse_series_allow_empty(y,b,c,np.array([10,11,12,30,31]),[0,3,3,5])
        self.assertEqual(len(out['periods']),3)
        empty=out['periods'][1]
        for role in ['baseline','candidate']:
            self.assertEqual(empty[role]['sample_count'],0)
            self.assertEqual(empty[role]['true_events'],0)
            self.assertEqual(empty[role]['normal_valid_count'],0)
            self.assertIsNone(empty[role]['false_alarm_runs_per_normal_day'])
        self.assertFalse(empty['normal_exposure_measurable'])
        self.assertFalse(empty['noninferior'])
        self.assertFalse(out['gates']['pooled_joint_improvement'])
        self.assertFalse(out['gates']['stable_joint_improvement'])
        self.assertEqual(out['gates']['totals']['baseline']['sample_count'],5)

    def test_all_empty_periods(self):
        out=assess_sparse_series_allow_empty(np.array([],bool),np.array([],int),
            np.array([],int),np.array([],int),[0,0,0,0,0,0,0])
        self.assertEqual(len(out['periods']),6)
        self.assertEqual(out['gates']['noninferior_periods'],[False]*6)
        self.assertEqual(out['pooled']['baseline']['true_events'],0)
        self.assertFalse(out['gates']['stable_joint_improvement'])

    def test_original_event_across_empty_period_counted_once(self):
        y=np.array([0,1,1,1,1,0],bool);b=np.array([0,1,0,1,0,0]);c=b.copy()
        slots=np.array([100,101,102,120,121,122])
        out=assess_sparse_series_allow_empty(y,b,c,slots,[0,3,3,6])
        self.assertEqual(out['pooled']['baseline']['true_events'],1)
        self.assertEqual(out['pooled']['baseline']['confirmed_new_alarm_inside_events'],1)
        self.assertEqual(out['gates']['period_event_occurrences'],2)
        self.assertEqual(out['gates']['totals']['baseline']['true_events'],1)
        record=out['pooled']['baseline']['event_records'][0]
        self.assertEqual(record['missing_slots_inside_event'],17)

    def test_hidden_rows_and_false_alarm_improvement_do_not_erase_empty_period(self):
        y=np.zeros(6,bool);b=np.array([0,1,0,0,1,0]);c=np.zeros(6,int)
        out=assess_sparse_series_allow_empty(y,b,c,np.arange(6),[0,3,3,6])
        self.assertLess(out['pooled']['candidate']['false_positive_runs'],out['pooled']['baseline']['false_positive_runs'])
        self.assertFalse(out['gates']['pooled_joint_improvement'])
        self.assertFalse(out['gates']['stable_joint_improvement'])
        c[0]=-1
        hidden=assess_sparse_series_allow_empty(y,b,c,np.arange(6),[0,3,3,6])
        self.assertEqual(hidden['gates']['hidden_baseline_observed_rows'],1)
        self.assertFalse(hidden['periods'][0]['noninferior'])

    def test_invalid_bounds_rejected_including_unsigned_decrease(self):
        y=np.zeros(4,bool);p=np.zeros(4,int);slots=np.arange(4)
        bad=[[0,3,2,4],[1,4],[0,3],[0,4,5],[0,1.5,4],[0],
             np.array([0,3,2,4],dtype=np.uint64)]
        for bounds in bad:
            with self.assertRaises(ValueError):assess_sparse_series_allow_empty(y,p,p,slots,bounds)


if __name__=='__main__':unittest.main()
