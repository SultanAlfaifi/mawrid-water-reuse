"""Synthetic-only V10 causal policy, pulse certificate and selection tests."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import numpy as np

from ml.gecco_v7 import calibration_delayed as delayed
from ml.gecco_v7 import calibration_certified as old_certified
from ml.gecco_v7.test_calibration_delayed import confirmation_fixture
from ml.gecco_v10 import calibration as cal


def four_blocks():
    blocks=confirmation_fixture()+confirmation_fixture()
    for i,b in enumerate(blocks):
        b['source_start']=i*len(b['labels']);b['block_id']=str(i)
    return blocks


def scalar_oracle(reference,scores,choice,rescue):
    """Independent record/state implementation, with no production helpers."""
    result=[];active=None;waiting=[]
    low,high=choice['low_threshold'],choice['high_threshold']
    deadline=choice['confirmation_samples'];pending=choice['pending_after_clear']
    m,width={'instant':(1,1),'2of3':(2,3),'3of5':(3,5)}[choice['policy']]
    for i,(r,score) in enumerate(zip(reference,scores)):
        if r < 0:
            active=None;waiting=[];value=-1
        else:
            if r == 0 and active is not None:
                if pending and not active['released']:
                    waiting.append(active)
                active=None
            if r == 1:
                if active is None:active={'start':i,'released':False}
                if low is None or not np.isfinite(score) or score >= low or i-active['start'] >= deadline:
                    active['released']=True
                value=int(active['released'])
            else:value=0
            remaining=[]
            for record in waiting:
                if i > record['start']+deadline:continue
                if np.isfinite(score) and score >= low:
                    value=1
                else:remaining.append(record)
            waiting=remaining
            if high is not None and i+1 >= width:
                window=np.asarray(rescue[i-width+1:i+1])
                if np.isfinite(window).all() and (window >= high).sum() >= m and rescue[i] >= high:
                    value=1
        result.append(value)
    return np.asarray(result,np.int8)


def pending_fixture():
    blocks=four_blocks()
    for b in blocks:
        b['reference'][802:805]=0;b['reference'][802]=1
        b['long_scores'][803]=.9
    return blocks


class PendingPredictionTests(unittest.TestCase):
    def test_exact_deadline_clear_unknown_cancel_and_new_pulse_examples(self):
        choice=cal._choice(.5,confirmation_samples=2,pending_after_clear=True)
        cases=[([1,0,0],[.1,.8,.1],[0,1,0]),
               ([1,0,0],[.1,.1,.8],[0,0,1]),
               ([1,0,0,0],[.1,.1,.1,.8],[0,0,0,0]),
               ([1,0,0],[.1,np.nan,.1],[0,0,0]),
               ([1,-1,0],[.1,.9,.9],[0,-1,0]),
               ([1,1,1,1,0],[.1]*5,[0,0,1,1,0]),
               ([1,0,1,1,1,0],[.1]*6,[0,0,0,0,1,0]),
               ([1,1,0,0],[.1,np.nan,.9,.9],[0,1,0,0]),
               ([1,0,1,0],[.1,.1,.8,.1],[0,0,1,0])]
        for r,s,expected in cases:
            np.testing.assert_array_equal(cal.predict(np.asarray(r,np.int8),s,choice),expected)

    def test_scalar_oracle_all_paths_persistence_unknown_and_prefix(self):
        rng=np.random.default_rng(20261017)
        for _ in range(30):
            reference=rng.choice([-1,0,1],100).astype(np.int8)
            scores=rng.random(100);scores[::11]=np.nan;scores[::17]=np.inf
            rescue=rng.random(100);rescue[::13]=np.nan
            for deadline in (1,2):
                for pending in (False,True):
                    for policy in ('instant','2of3','3of5'):
                        for high in (None,.8):
                            choice=cal._choice(.5,high,policy,deadline,60,pending)
                            whole=cal.predict(reference,scores,choice,rescue)
                            np.testing.assert_array_equal(whole,scalar_oracle(reference,scores,choice,rescue))
                            for stop in (0,1,2,3,47,99):
                                np.testing.assert_array_equal(cal.predict(reference[:stop],scores[:stop],choice,rescue[:stop]),whole[:stop])

    def test_future_sensor_or_reference_mutation_cannot_change_prior_prediction(self):
        rng=np.random.default_rng(89);r=rng.choice([-1,0,1],120).astype(np.int8);s=rng.random(120)
        selected=cal._choice(.5,.8,'2of3',2,60,True)
        expected=cal.predict(r,s,selected,s)
        for stop in (0,1,2,5,20,80):
            rr=r.copy();ss=s.copy();rr[stop:]=1;ss[stop:]=1
            np.testing.assert_array_equal(cal.predict(rr,ss,selected,ss)[:stop],expected[:stop])

    def test_disabled_pending_exactly_matches_frozen_delayed_predictor(self):
        rng=np.random.default_rng(76);r=rng.choice([-1,0,1],100).astype(np.int8);s=rng.random(100);s[::9]=np.nan
        for low,deadline in ((None,0),(.5,1),(.5,2)):
            for high in (None,.8):
                for policy in ('instant','2of3','3of5'):
                    choice=cal._choice(low,high,policy,deadline)
                    np.testing.assert_array_equal(cal.predict(r,s,choice,s),delayed.predict(r,s,choice,s))

    def test_trace_attributes_old_release_without_resetting_new_episode(self):
        r=np.array([1,0,1,1,0],np.int8);s=np.array([.1,.1,.8,.1,.1])
        output,base,origins=cal._confirmation(r,s,.5,2,True)
        np.testing.assert_array_equal(output,[0,0,1,1,0])
        np.testing.assert_array_equal(base,[0,0,1,1,0])
        self.assertEqual(origins[2],0)
        self.assertEqual(np.count_nonzero(origins >= 0),1)

    def test_rescue_never_releases_confirmation_latch_and_needs_current_evidence(self):
        r=np.ones(5,np.int8);s=np.zeros(5);rescue=np.array([.9,.1,.1,.1,.1])
        selected=cal._choice(.5,.8,confirmation_samples=2,pending_after_clear=True)
        np.testing.assert_array_equal(cal.predict(r,s,selected,rescue),[1,0,1,1,1])
        for policy in ('2of3','3of5'):
            r=np.zeros(7,np.int8);rescue=np.array([1,1,1,1,1,.1,np.nan])
            p=cal.predict(r,np.ones(7),cal._choice(None,.8,policy),rescue)
            self.assertEqual(p[-2],0);self.assertEqual(p[-1],0)

    def test_availability_and_cadence_validation(self):
        r=np.array([-1,0,1,0,-1,0],np.int8)
        for pending in (False,True):
            p=cal.predict(r,np.ones(6),cal._choice(.5,.8,confirmation_samples=2,pending_after_clear=pending))
            np.testing.assert_array_equal(r >= 0,p >= 0)
        for choice in (cal._choice(pending_after_clear=True),cal._choice(.5,confirmation_samples=1,cadence_seconds=300,pending_after_clear=True),
                       cal._choice(.5,confirmation_samples=2,cadence_seconds=90,pending_after_clear=True),
                       {**cal._choice(.5,confirmation_samples=2),'pending_after_clear':1}):
            with self.assertRaises(ValueError):cal.predict(r,np.ones(6),choice)


class PulseAssessmentTests(unittest.TestCase):
    def scope(self,labels,reference,seed,origins=None,choice=None):
        r=np.array(reference,np.int8);p=np.array(seed,np.int8)
        return cal._pulse_scope(np.array(labels,np.int8),r,p,np.full(len(r),-1,np.int64) if origins is None else np.array(origins,np.int64),
                                choice or cal._choice(.5,confirmation_samples=2,pending_after_clear=True),0)

    def test_later_same_episode_alarm_beyond120_is_not_pulse_retention(self):
        result=self.scope([0]+[1]*8,[0]+[1]*8,[0,0,0,0,1,1,1,1,1])
        self.assertFalse(result['passed'])
        exact=self.scope([0]+[1]*8,[0]+[1]*8,[0,0,0,1,1,1,1,1,1])
        self.assertTrue(exact['passed'])

    def test_each_positive_segment_intersection_is_a_separate_obligation(self):
        result=self.scope([0,1,1,-1,1,1,0],[0,1,1,1,1,1,0],[0,1,1,0,0,0,0])
        self.assertEqual(result['obligations'],2)
        self.assertEqual(result['retained_obligations'],1)
        self.assertFalse(result['passed'])

    def test_postclear_alarm_needs_trace_same_segment_and_own_deadline(self):
        good=self.scope([0,1,1,1,0],[0,1,0,0,0],[0,0,0,1,0],[-1,-1,-1,1,-1])
        self.assertTrue(good['passed'])
        unrelated=self.scope([0,1,1,1,0],[0,1,0,0,0],[0,0,0,1,0])
        self.assertFalse(unrelated['passed'])
        unknown=self.scope([0,1,-1,1,0],[0,1,0,0,0],[0,0,0,1,0],[-1,-1,-1,1,-1])
        self.assertFalse(unknown['passed'])
        too_late=self.scope([0,1,1,1,1],[0,1,0,0,0],[0,0,0,0,1],[-1,-1,-1,-1,1])
        self.assertFalse(too_late['passed'])

    def test_censored_positive_fragments_are_not_hidden(self):
        first=self.scope([1,1,0],[1,1,0],[0,0,0])
        postunknown=self.scope([0,1,1],[-1,1,1],[-1,0,0])
        self.assertEqual(first['censored_fragment_obligations'],1)
        self.assertEqual(postunknown['censored_fragment_obligations'],1)
        self.assertFalse(first['passed']);self.assertFalse(postunknown['passed'])


class TemporalSelectionTests(unittest.TestCase):
    def test_pending_recovery_is_selected_on_earlier_blocks_and_certified_once(self):
        blocks=pending_fixture();saved=deepcopy(blocks)
        selected,trials=cal.calibrate(blocks)
        self.assertTrue(selected['pending_after_clear'])
        self.assertTrue(selected['certification_passed'])
        self.assertEqual(selected['confirmation_samples'],2)
        self.assertEqual(selected['events'],12)
        self.assertEqual(selected['false_runs'],0)
        self.assertEqual(selected['certification']['pending']['coverage_event_ids'],[3,6])
        self.assertEqual(selected['certification']['pending']['first_addition_blocks'],[0,1])
        self.assertTrue(all(t['pending_added_normal_rows'] == 0 for t in trials[:-1] if t['feasible']))
        self.assertEqual(selected['certification_attempts'],1)
        json.dumps(selected,allow_nan=False)
        for before,after in zip(saved,blocks):
            for key in ('labels','reference','long_scores','rescue_scores'):np.testing.assert_array_equal(before[key],after[key])

    def test_redundant_positive_pulse_constraint_participates_in_earlier_feasibility(self):
        blocks=four_blocks()
        for b in blocks:
            b['reference'][208]=1;b['long_scores'][208]=.2
            b['long_scores'][1000]=.3
        old,_=delayed.calibrate(blocks[:2])
        selected,trials=cal.select_earlier(blocks[:2])
        self.assertGreater(old['low_threshold'],.2)
        self.assertLessEqual(selected['low_threshold'],.2)
        self.assertEqual(selected['events'],6)
        rejected=[t for t in trials if t['low_threshold'] is not None and t['low_threshold'] > .2]
        self.assertTrue(rejected)
        self.assertTrue(all(not t['feasible'] for t in rejected))
        self.assertTrue(any('positive_pulse:' in reason for t in rejected for reason in t['rejection_reasons']))

    def test_later_failure_cannot_retune_or_retry_an_alternative(self):
        blocks=pending_fixture();expected,_=cal.select_earlier(blocks[:2])
        for b in blocks[2:]:b['long_scores'][803]=.1
        with patch.object(cal,'select_earlier',wraps=cal.select_earlier) as selector:
            selected,_=cal.calibrate(blocks)
        self.assertEqual(selector.call_count,1);self.assertEqual(len(selector.call_args.args[0]),2)
        self.assertEqual(selected['earlier_selected'],expected)
        self.assertEqual(selected['final_selected'],cal._choice())
        self.assertFalse(selected['certification_passed'])
        self.assertEqual(selected['status'],'certification_failed_reference_retained')

    def test_pending_cannot_spend_normal_suppression_credit(self):
        blocks=pending_fixture()[2:]
        for b in blocks:b['long_scores'][1001]=.9
        choice=cal._choice(.5,confirmation_samples=2,pending_after_clear=True)
        check=cal.certify(choice,blocks)
        self.assertTrue(check['candidate']['passed'])
        self.assertTrue(check['pure_confirmation_seed']['passed'])
        self.assertEqual(check['pending']['added_known_normal_rows'],2)
        self.assertEqual(check['pending']['added_known_normal_rows_by_block'],[1,1])
        self.assertFalse(check['passed'])

    def test_pending_evidence_needs_two_distinct_primary_events_in_two_blocks(self):
        blocks=pending_fixture()[2:]
        blocks[1]['reference'][802:805]=1
        check=cal.certify(cal._choice(.5,confirmation_samples=2,pending_after_clear=True),blocks)
        self.assertEqual(len(check['pending']['coverage_event_ids']),1)
        self.assertFalse(check['pending']['passed'])
        self.assertFalse(check['passed'])

    def test_unknown_added_rows_are_not_normal_and_cannot_supply_positive_evidence(self):
        blocks=pending_fixture()[2:]
        for b in blocks:
            b['long_scores'][1001]=.9;b['labels'][1001]=-1
        check=cal.certify(cal._choice(.5,confirmation_samples=2,pending_after_clear=True),blocks)
        self.assertEqual(check['pending']['added_known_normal_rows'],0)
        self.assertEqual(len(check['pending']['coverage_event_ids']),2)
        self.assertTrue(check['pending']['passed'])
        for b in blocks:b['labels'][800:812]=-1
        check=cal.certify(cal._choice(.5,confirmation_samples=2,pending_after_clear=True),blocks)
        self.assertEqual(check['pending']['coverage_event_ids'],[])
        self.assertFalse(check['pending']['passed'])

    def test_rescue_cannot_mask_positive_pulse_loss_in_confirmation_seed(self):
        blocks=four_blocks()[2:]
        for b in blocks:
            b['reference'][208]=1;b['long_scores'][208]=.1;b['rescue_scores'][208]=.9
        check=cal.certify(cal._choice(.5,.8,confirmation_samples=2),blocks)
        self.assertTrue(check['candidate']['passed'])
        self.assertTrue(check['pure_confirmation_seed']['passed'])
        self.assertTrue(check['rescue']['passed'])
        self.assertFalse(check['positive_reference_pulses']['passed'])
        self.assertFalse(check['passed'])

    def test_allfour_global_pulse_deadline_catches_block_reset_censoring(self):
        blocks=four_blocks()
        blocks[1]['labels'][-20:]=1;blocks[2]['labels'][:10]=1
        blocks[1]['reference'][-19:-16]=1;blocks[1]['long_scores'][-19:-16]=.9
        blocks[1]['reference'][-1]=1;blocks[2]['reference'][:5]=1
        fixed=cal._choice(.5,confirmation_samples=2)
        fake={**fixed,'evidence':{'synthetic':True}}
        with patch.object(cal,'select_earlier',return_value=(fake,[{**fixed,'feasible':True,'rejection_reasons':[]}])):
            selected,_=cal.calibrate(blocks)
        self.assertTrue(selected['certification']['passed'])
        self.assertTrue(selected['global_veto']['all_four_candidate']['passed'])
        self.assertFalse(selected['global_veto']['all_four_positive_reference_pulses']['passed'])
        self.assertEqual(selected['decision'],'reference')

    def test_primary_event_crossing_two_blocks_has_one_added_path_owner(self):
        blocks=confirmation_fixture()
        for b in blocks:b['reference'][:]=0;b['long_scores'][:]=.1
        blocks[0]['labels'][3295:]=1;blocks[1]['labels'][:10]=1
        blocks[0]['reference'][3297]=1;blocks[0]['long_scores'][3298]=.9
        blocks[1]['reference'][1]=1;blocks[1]['long_scores'][2]=.9
        selected=cal._choice(.5,confirmation_samples=2,pending_after_clear=True)
        p,a0,_=cal._seed_blocks(blocks,selected)
        evidence=cal._added_evidence(blocks,p,a0,True,'pending',60)
        self.assertEqual(len(evidence['coverage_event_ids']),1)
        self.assertEqual(evidence['first_addition_blocks'],[0])
        self.assertFalse(evidence['passed'])
        old=old_certified._rescue_evidence(blocks,p,a0,{'high_threshold':.5},60)
        self.assertEqual(evidence['coverage_event_ids'],old['coverage_event_ids'])
        self.assertEqual(evidence['first_addition_blocks'],old['first_addition_blocks'])

    def test_actual_event_delay_is_independent_of_per_episode_timer(self):
        blocks=four_blocks()[2:]
        for b in blocks:
            b['labels'][500:530]=1;b['reference'][500:530]=0
            b['reference'][501]=1;b['reference'][510:515]=1
        check=cal.certify(cal._choice(.5,confirmation_samples=2,pending_after_clear=True),blocks)
        self.assertFalse(check['candidate']['passed'])
        self.assertEqual(check['candidate']['scopes'][0]['max_paired_extra_delay_seconds'],660)
        self.assertFalse(check['positive_reference_pulses']['passed'])

    def test_missing_evidence_fallback_cadence_and_geometry_are_not_relaxed(self):
        blocks=four_blocks()
        selected,trials=cal.calibrate(blocks,cadence_seconds=300)
        self.assertEqual(selected['decision'],'reference')
        self.assertTrue(all(t['confirmation_samples'] == 0 and not t['pending_after_clear'] for t in trials))
        for b in blocks:b['labels'][:]=-1
        selected,trials=cal.calibrate(blocks)
        self.assertEqual(selected['decision'],'reference')
        self.assertFalse(selected['certification']['evidence']['enough_observed_normal_exposure'])
        self.assertEqual(selected['selection_trial_count'],1)
        with self.assertRaises(ValueError):cal.calibrate(blocks[:3])
        with self.assertRaises(ValueError):cal.select_earlier(blocks)
        blocks[2]['source_start']+=1
        with self.assertRaises(ValueError):cal.calibrate(blocks)


if __name__ == '__main__':unittest.main()
