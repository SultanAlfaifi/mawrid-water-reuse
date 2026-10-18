"""Synthetic original-row identity, elapsed time and full-grid policy contracts."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from calibration import calibrate,predict
from evaluation import evaluate_at_cadence,compare_period,assess_series
from sparse_evaluation import evaluate_sparse,compare_sparse,assess_sparse_series
from sparse_calibration import calibrate_sparse,_stats,_comparison


def fixtures():
    blocks=[]
    for k in range(2):
        y=np.zeros(1000,bool);s=np.full(1000,.05);b=np.zeros(1000,np.int8)
        for a in (100,300,500):y[a:a+10]=True;s[a:a+10]=.9;b[a:a+10]=1
        for a in (50,200,400,700):b[a:a+2]=1;s[a:a+2]=.1
        blocks.append(dict(labels=y,scores=s,baseline_predictions=b,source_start=k*1000,block_id=str(k),
                           observed=np.ones(1000,bool),slots=np.arange(k*1000,(k+1)*1000)))
    return blocks


SMALL=dict(min_normal_minutes_per_block=10,min_total_normal_minutes=20,min_observed_blocks=2)


class SparseEvaluationTests(unittest.TestCase):
    def test_contiguous_schema_and_all_metrics_exact_parity(self):
        rng=np.random.default_rng(20)
        for cadence in (60,900):
            for n in (0,1,1000):
                y=rng.random(n)<.2;b=rng.choice([-1,0,1],n);c=rng.choice([-1,0,1],n)
                slots=np.arange(n)+123
                self.assertEqual(evaluate_sparse(y,b,slots,cadence),evaluate_at_cadence(y,b,cadence))
                self.assertEqual(compare_sparse(y,b,c,slots,cadence),compare_period(y,b,c,cadence))

    def test_original_event_is_not_split_by815_missing_slots(self):
        m=evaluate_sparse(np.array([0,1,1,0]),np.array([0,1,1,0]),np.array([0,1,817,818]))
        self.assertEqual(m['true_events'],1)
        r=m['event_records'][0]
        self.assertEqual(r['missing_slots_inside_event'],815)
        self.assertEqual(r['duration_minutes'],30)
        self.assertEqual(r['elapsed_span_minutes'],817*15)
        self.assertTrue(r['time_gap_censored'])

    def test_gap_does_not_confirm_zero_to_one(self):
        m=evaluate_sparse(np.array([0,1,1]),np.array([0,1,0]),np.array([0,10,11]))
        self.assertEqual(m['confirmed_new_alarm_inside_events'],0)
        self.assertEqual(m['raw_new_alarm_inside_events'],1)
        self.assertTrue(m['event_records'][0]['new_alarm_previous_unknown'])

    def test_later_adjacent_zero_to_one_can_confirm_same_original_event(self):
        m=evaluate_sparse(np.array([0,1,1,1]),np.array([0,1,0,1]),np.array([0,10,11,12]))
        self.assertEqual(m['true_events'],1)
        self.assertEqual(m['confirmed_new_alarm_inside_events'],1)
        self.assertEqual(m['event_records'][0]['confirmed_new_alarm_delay_minutes'],30)

    def test_false_alarm_runs_split_at_missing_time_without_exposure(self):
        m=evaluate_sparse(np.zeros(4,bool),np.ones(4,int),np.array([0,1,9,10]))
        self.assertEqual(m['false_positive_runs'],2)
        self.assertEqual(m['alarm_runs'],2)
        self.assertEqual(m['normal_alarm_minutes'],60)
        self.assertAlmostEqual(m['eligible_normal_days'],1/24)
        self.assertAlmostEqual(m['false_alarm_runs_per_normal_day'],48)

    def test_paired_latency_uses_elapsed_slots(self):
        y=np.array([0,1,1,1,1,0]);slots=np.array([0,1,2,100,101,102])
        result=compare_sparse(y,np.array([0,1,1,0,0,0]),np.array([0,0,0,0,1,0]),slots)
        self.assertEqual(result['paired_detection_delays'][0]['extra_delay_minutes'],1500)
        self.assertEqual(result['lost_baseline_events'],[])

    def test_cross_period_original_event_only_counted_once(self):
        y=np.array([0,1,1,1,1,0]);p=np.array([0,1,0,0,1,0]);slots=np.array([0,1,2,100,101,102])
        result=assess_sparse_series(y,p,p,slots,[0,3,6])
        self.assertEqual(result['pooled']['baseline']['true_events'],1)
        self.assertEqual(result['gates']['totals']['baseline']['true_events'],1)
        self.assertEqual(result['gates']['period_event_occurrences'],2)

    def test_hidden_observed_rows_rejected_by_gate(self):
        r=compare_sparse(np.zeros(3,bool),np.array([0,1,0]),np.array([0,-1,0]),np.array([0,5,6]))
        self.assertEqual(r['baseline_observed_rows_hidden_by_candidate'],1)
        self.assertFalse(r['noninferior'])

    def test_duplicate_noninteger_or_reversed_slots_rejected(self):
        for s in (np.array([0.,1.]),np.array([0,0]),np.array([1,0])):
            with self.assertRaises(ValueError):evaluate_sparse(np.zeros(2,bool),np.zeros(2,int),s)

    def test_fast_calibration_statistics_match_independent_sparse_metrics(self):
        y=np.array([0,1,1,0,0,1,1,0]);p=np.array([0,1,0,1,1,0,1,-1]);slots=np.array([0,1,2,10,20,21,22,23])
        a=_stats(y,p,slots,900);m=evaluate_sparse(y,p,slots,900)
        self.assertEqual(a['confirmed_events'],m['confirmed_new_alarm_inside_events'])
        self.assertEqual(a['false_positive_runs'],m['false_positive_runs'])
        self.assertEqual(a['fp_duration_seconds'],m['normal_alarm_minutes']*60)
        self.assertAlmostEqual(a['false_runs_per_day'],m['false_alarm_runs_per_normal_day'])


class SparseCalibrationTests(unittest.TestCase):
    def test_all_observed60s_selected_trials_and_predictions_exact_parity(self):
        b=fixtures()
        for policies in [('instant',),('2of3',),('3of5',),('instant','2of3','3of5')]:
            left,lt=calibrate(b,policies=policies,**SMALL)
            right,rt=calibrate_sparse(b,cadence_seconds=60,policies=policies,**SMALL)
            self.assertEqual(left,right);self.assertEqual(lt,rt)
            for block in b:np.testing.assert_array_equal(predict(block['scores'],block['baseline_predictions'],left),predict(block['scores'],block['baseline_predictions'],right))

    def test_event_denominator_is_observed_axis_not_filled_grid(self):
        block=dict(labels=np.array([0,1,0,0,1]),scores=np.array([.1,.9,np.nan,np.nan,.9]),
            baseline_predictions=np.array([0,1,-1,-1,1]),observed=np.array([1,1,0,0,1],bool),slots=np.arange(5),source_start=0)
        choice,_=calibrate_sparse([block])
        self.assertEqual(choice['evidence']['reference']['true_events'],1)
        self.assertEqual(choice['evidence']['reference']['confirmed_events'],1)

    def test_all_inserted_block_is_unavailable_evidence(self):
        b=fixtures();empty=dict(labels=np.zeros(1000,bool),scores=np.full(1000,np.nan),baseline_predictions=np.full(1000,-1),observed=np.zeros(1000,bool),slots=np.arange(1000,2000),source_start=1000,block_id='gap')
        b[1]['source_start']=2000;b[1]['slots']+=1000
        chosen,_=calibrate_sparse([b[0],empty,b[1]],cadence_seconds=60,**SMALL)
        self.assertEqual(chosen['decision'],'candidate')
        self.assertEqual(chosen['evidence']['unobserved_block_ids'],['gap'])
        self.assertEqual(chosen['evidence']['reference']['true_events'],6)

    def test_policy_decisions_require_full_grid_before_projection(self):
        scores=np.array([0.,0.,np.nan,1.]);base=np.array([1,1,-1,1]);observed=np.array([1,1,0,1],bool)
        choice=dict(decision='candidate',threshold=.5,policy='2of3')
        full=predict(scores,base,choice)[observed]
        compressed=predict(scores[observed],base[observed],choice)
        self.assertEqual(full[-1],1)
        self.assertEqual(compressed[-1],0)

    def test_invalid_inserted_scores_or_missing_grid_slots_rejected(self):
        for field in ('scores','baseline_predictions','slots'):
            b=fixtures();b[0]['observed'][30]=False;b[0]['scores'][30]=np.nan;b[0]['baseline_predictions'][30]=-1
            if field=='scores':b[0]['scores'][30]=0
            elif field=='baseline_predictions':b[0]['baseline_predictions'][30]=0
            else:b[0]['slots'][30]+=1
            with self.assertRaises(ValueError):calibrate_sparse(b,**SMALL)

    def test_calibration900s_exposure_counts_only_observed_samples(self):
        b=fixtures();chosen,_=calibrate_sparse(b,**SMALL)
        ref=chosen['evidence']['reference']
        self.assertEqual(ref['normal_observed_seconds'],1940*900)
        self.assertEqual(ref['fp_duration_seconds'],16*900)


if __name__=='__main__':unittest.main(verbosity=2)
