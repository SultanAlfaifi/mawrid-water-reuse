"""Synthetic tests for the single V11 retained-IF protection change."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import numpy as np
from ml.gecco_v10 import calibration as old
from ml.gecco_v10.test_calibration import four_blocks as old_blocks, pending_fixture as old_pending_fixture
from ml.gecco_v11 import calibration as cal


def blocks(pending=False):
    result=old_pending_fixture() if pending else old_blocks()
    for b in result:b['baseline']=np.zeros(len(b['labels']),np.int8)
    return result


def without_static_tag(value):
    if isinstance(value,dict):return {k:without_static_tag(v) for k,v in value.items() if k!='retained_if_protection'}
    if isinstance(value,list):return [without_static_tag(v) for v in value]
    return value


def scalar_paths(reference,confidence,baseline,choice,rescue):
    """Independent forward state machine, never consulting production helpers."""
    low,high=choice['low_threshold'],choice['high_threshold'];deadline=choice['confirmation_samples']
    count,width={'instant':(1,1),'2of3':(2,3),'3of5':(3,5)}[choice['policy']]
    state=None;waiting=[];output=[];unextended=[];traces=[]
    for i,(r,s,b) in enumerate(zip(reference,confidence,baseline)):
        trace=-1
        if r==-1:
            state=None;waiting=[];base=-1;value=-1
        else:
            if r==0 and state is not None:
                if choice['pending_after_clear'] and not state['released']:waiting.append(state)
                state=None
            if r==1:
                if state is None:state={'start':i,'released':False}
                if b==1 or low is None or not np.isfinite(s) or s>=low or i-state['start']>=deadline:
                    state['released']=True
                base=int(state['released'])
            else:base=0
            value=base;remaining=[]
            for pending in waiting:
                if i>pending['start']+deadline:continue
                if np.isfinite(s) and s>=low:value=1;trace=pending['start']
                else:remaining.append(pending)
            waiting=remaining
        unextended.append(base);output.append(value);traces.append(trace)
    final=np.asarray(output,np.int8).copy()
    if high is not None:
        for i in range(len(reference)):
            window=np.asarray(rescue[max(0,i-width+1):i+1])
            if reference[i]>=0 and len(window)==width and np.isfinite(window).all() and rescue[i]>=high and (window>=high).sum()>=count:
                final[i]=1
    return final,np.asarray(output,np.int8),np.asarray(unextended,np.int8),np.asarray(traces,np.int64)


class ProtectedPredictionTests(unittest.TestCase):
    def test_protection_immediate_and_latched_when_it_arrives_later(self):
        r=np.array([0,1,1,1,0,1,1,0],np.int8);baseline=np.array([1,0,1,0,1,1,0,1],np.int8)
        s=np.zeros(len(r));choice=cal._choice(.5,confirmation_samples=2,pending_after_clear=True)
        np.testing.assert_array_equal(cal.predict(r,s,choice,baseline=baseline),[0,0,1,1,0,1,1,0])
        np.testing.assert_array_equal(s,np.zeros(len(r)))

    def test_no_resurrection_of_quiet_or_unknown_reference(self):
        r=np.array([-1,0,1,0,-1,1,0],np.int8);b=np.ones(len(r),np.int8)
        for pending in (False,True):
            selected=cal._choice(.5,confirmation_samples=2,pending_after_clear=pending)
            np.testing.assert_array_equal(cal.predict(r,np.zeros(len(r)),selected,baseline=b),r)
        b=np.full(len(r),-1,np.int8)
        np.testing.assert_array_equal(cal.predict(r,np.zeros(len(r)),cal._choice(.5,confirmation_samples=2),baseline=b),[-1,0,0,0,-1,0,0])

    def test_protected_pulse_never_becomes_its_own_pending_record(self):
        r=np.array([1,0,0,1,1,0,0],np.int8);b=np.array([1,0,0,0,1,0,0],np.int8)
        s=np.array([.1,.9,.9,.1,.1,.9,.9]);choice=cal._choice(.5,confirmation_samples=2,pending_after_clear=True)
        p,a0,trace=cal._confirmation(r,s,.5,2,True,b)
        np.testing.assert_array_equal(p,[1,0,0,0,1,0,0]);np.testing.assert_array_equal(p,a0)
        self.assertTrue((trace==-1).all())
        np.testing.assert_array_equal(cal.predict(r,s,choice,baseline=b),p)

    def test_old_pending_release_does_not_cancel_new_protected_pulse_identity(self):
        r=np.array([1,0,1,1,0],np.int8);b=np.array([0,0,1,0,0],np.int8);s=np.array([.1,.1,.8,.1,.1])
        p,a0,trace=cal._confirmation(r,s,.5,2,True,b)
        np.testing.assert_array_equal(p,[0,0,1,1,0]);np.testing.assert_array_equal(a0,p)
        np.testing.assert_array_equal(trace,[-1,-1,0,-1,-1])

    def test_independent_scalar_oracle_all_paths_traces_and_prefixes(self):
        rng=np.random.default_rng(20261018)
        for _ in range(20):
            r=rng.choice([-1,0,1],80).astype(np.int8);b=rng.choice([-1,0,1],80).astype(np.int8)
            s=rng.random(80);s[::9]=np.nan;s[::13]=np.inf;rescue=rng.random(80);rescue[::11]=np.nan
            for low,deadline in ((None,0),(.5,1),(.5,2)):
                for pending in ([False] if low is None else [False,True]):
                    for high in (None,.8):
                        for policy in ('instant','2of3','3of5'):
                            choice=cal._choice(low,high,policy,deadline,60,pending)
                            expected,p,a0,trace=scalar_paths(r,s,b,choice,rescue)
                            np.testing.assert_array_equal(cal.predict(r,s,choice,rescue,baseline=b),expected)
                            for actual,wanted in zip(cal._confirmation(r,s,low,deadline,pending,b),(p,a0,trace)):
                                np.testing.assert_array_equal(actual,wanted)
                            for stop in (0,1,2,3,37,79):
                                np.testing.assert_array_equal(cal.predict(r[:stop],s[:stop],choice,rescue[:stop],baseline=b[:stop]),expected[:stop])

    def test_future_baseline_reference_and_score_mutation_cannot_change_past(self):
        rng=np.random.default_rng(67);r=rng.choice([-1,0,1],100).astype(np.int8);b=rng.choice([-1,0,1],100).astype(np.int8);s=rng.random(100)
        choice=cal._choice(.5,.8,'2of3',2,60,True);expected=cal.predict(r,s,choice,s,baseline=b)
        for at in (0,1,3,17,71):
            rr=r.copy();bb=b.copy();ss=s.copy();rr[at:]=1;bb[at:]=1;ss[at:]=1
            np.testing.assert_array_equal(cal.predict(rr,ss,choice,ss,baseline=bb)[:at],expected[:at])

    def test_all_zero_or_unknown_baseline_is_exact_v10_parity(self):
        rng=np.random.default_rng(91);r=rng.choice([-1,0,1],150).astype(np.int8);s=rng.random(150);s[::9]=np.nan
        for low,deadline in ((None,0),(.5,1),(.5,2)):
            for pending in ([False] if low is None else [False,True]):
                for high in (None,.8):
                    for policy in ('instant','2of3','3of5'):
                        selected=cal._choice(low,high,policy,deadline,60,pending)
                        expected=old.predict(r,s,selected,s)
                        for value in (0,-1):
                            np.testing.assert_array_equal(cal.predict(r,s,selected,s,baseline=np.full(len(r),value,np.int8)),expected)

    def test_disabled_choice_exact_reference_for_any_baseline(self):
        r=np.array([-1,0,1,1,0,-1],np.int8);s=np.zeros(6)
        for value in (-1,0,1):np.testing.assert_array_equal(cal.predict(r,s,cal._choice(),baseline=np.full(6,value,np.int8)),r)
        np.testing.assert_array_equal(cal.predict(np.array([],np.int8),[],cal._choice(),baseline=np.array([],np.int8)),[])

    def test_baseline_presence_shape_and_ternary_validation(self):
        r=np.array([0,1],np.int8);s=np.ones(2);selected=cal._choice()
        with self.assertRaises(TypeError):cal.predict(r,s,selected)
        for invalid in (None,[0],[[0,1]],[0.,1.],[0,2],[0,np.nan],['0','1']):
            with self.subTest(value=invalid),self.assertRaises(ValueError):cal.predict(r,s,selected,baseline=invalid)
        for flag in (False,0,1,None):
            with self.assertRaises(ValueError):cal.predict(r,s,{**selected,'retained_if_protection':flag},baseline=r)

    def test_rescue_never_uses_baseline_to_release_or_extend_reference_episode(self):
        r=np.ones(5,np.int8);b=np.zeros(5,np.int8);s=np.zeros(5);rescue=np.array([.9,0,0,0,0])
        selected=cal._choice(.5,.8,confirmation_samples=2,pending_after_clear=True)
        np.testing.assert_array_equal(cal.predict(r,s,selected,rescue,baseline=b),[1,0,1,1,1])
        r=np.zeros(5,np.int8);b[:]=1
        np.testing.assert_array_equal(cal.predict(r,s,selected,np.zeros(5),baseline=b),np.zeros(5,np.int8))


class ProtectedCalibrationTests(unittest.TestCase):
    def test_zero_baseline_preserves_entire_v10_selection_certificate_and_trials(self):
        data=blocks(pending=True);snapshot=deepcopy(data)
        selected,trials=cal.calibrate(data);before,before_trials=old.calibrate(data)
        self.assertEqual(without_static_tag(selected),before)
        self.assertEqual(without_static_tag(trials),before_trials)
        for b,s in zip(data,snapshot):
            for key in ('labels','reference','baseline','long_scores','rescue_scores'):np.testing.assert_array_equal(b[key],s[key])

    def test_protection_participates_in_first_two_candidate_feasibility(self):
        data=blocks()
        for b in data:
            b['reference'][208]=1;b['long_scores'][208]=.2;b['long_scores'][1000]=.3;b['baseline'][208]=1
        selected,trials=cal.select_earlier(data[:2]);before,_=old.select_earlier(data[:2])
        self.assertLessEqual(before['low_threshold'],.2);self.assertGreater(selected['low_threshold'],.2)
        self.assertTrue(selected['retained_if_protection'])
        self.assertTrue(all(t['lost_positive_pulse_obligations']==0 for t in trials if t['feasible']))
        final,_=cal.calibrate(data)
        self.assertTrue(final['certification_passed'])
        self.assertTrue(final['global_veto']['all_four_positive_reference_pulses']['passed'])
        for b in data:
            output=cal.predict(b['reference'],b['long_scores'],final,b['rescue_scores'],baseline=b['baseline'])
            self.assertEqual(output[208],1)

    def test_protection_does_not_supply_pending_evidence_after_release(self):
        data=blocks(pending=True)[2:]
        for b in data:b['baseline'][802]=1
        check=cal.certify(cal._choice(.5,confirmation_samples=2,pending_after_clear=True),data)
        self.assertTrue(check['positive_reference_pulses']['passed'])
        self.assertFalse(check['pending']['passed']);self.assertEqual(check['pending']['coverage_event_ids'],[])
        self.assertEqual(check['pending']['added_known_normal_rows'],0)

    def test_later_baseline_cannot_change_earlier_choice_and_veto_never_retries(self):
        data=blocks()
        for b in data:
            b['reference'][208]=1;b['long_scores'][208]=.2;b['long_scores'][1000]=.3;b['baseline'][208]=1
        expected,_=cal.select_earlier(data[:2])
        for b in data[2:]:b['baseline'][208]=0
        with patch.object(cal,'select_earlier',wraps=cal.select_earlier) as select:
            final,_=cal.calibrate(data)
        self.assertEqual(select.call_count,1);self.assertEqual(final['earlier_selected'],expected)
        self.assertFalse(final['certification_passed']);self.assertEqual(final['decision'],'reference')
        self.assertFalse(final['certification']['positive_reference_pulses']['passed'])

    def test_baseline_required_for_every_calibration_entry_and_duplicate_axes_rejected(self):
        for entry,args in ((cal.calibrate,blocks()),(cal.select_earlier,blocks()[:2]),(lambda x:cal.certify(cal._choice(),x),blocks()[2:])):
            for invalid in ('missing',None,[0],np.zeros((2,2),np.int8),[1.0]):
                modified=deepcopy(args)
                if isinstance(invalid,str):modified[0].pop('baseline')
                else:modified[0]['baseline']=invalid
                with self.subTest(invalid=str(invalid)),self.assertRaises(ValueError):entry(modified)
        data=blocks();data[1]=deepcopy(data[0])
        with self.assertRaises(ValueError):cal.calibrate(data)
        data=blocks();data[2]['source_start']+=1
        with self.assertRaises(ValueError):cal.calibrate(data)

    def test_no_evidence_and_slow_cadence_keep_frozen_fallback(self):
        data=blocks()
        for b in data:b['labels'][:]=-1;b['baseline'][:]=1
        final,trials=cal.calibrate(data)
        self.assertEqual(final['decision'],'reference');self.assertEqual(final['selection_trial_count'],1)
        self.assertFalse(final['certification']['evidence']['enough_observed_normal_exposure'])
        data=blocks();final,trials=cal.calibrate(data,cadence_seconds=300)
        self.assertTrue(all(t['confirmation_samples']==0 for t in trials))
        self.assertTrue(all(not t['pending_after_clear'] for t in trials))

    def test_allfour_global_pulse_deadline_still_rejects_block_reset(self):
        data=blocks()
        data[1]['labels'][-20:]=1;data[2]['labels'][:10]=1
        data[1]['reference'][-19:-16]=1;data[1]['long_scores'][-19:-16]=.9
        data[1]['reference'][-1]=1;data[2]['reference'][:5]=1
        fixed=cal._choice(.5,confirmation_samples=2)
        fake={**fixed,'evidence':{'synthetic':True}}
        with patch.object(cal,'select_earlier',return_value=(fake,[{**fixed,'feasible':True,'rejection_reasons':[]}])):
            selected,_=cal.calibrate(data)
        self.assertTrue(selected['certification']['passed'])
        self.assertTrue(selected['global_veto']['all_four_candidate']['passed'])
        self.assertFalse(selected['global_veto']['all_four_positive_reference_pulses']['passed'])
        self.assertEqual(selected['decision'],'reference')

    def test_actual_event_delay_constraint_is_not_replaced_by_protection(self):
        data=blocks()[2:]
        for b in data:
            b['labels'][500:530]=1;b['reference'][500:530]=0
            b['reference'][501]=1;b['reference'][510:515]=1
            b['baseline'][510]=1
        check=cal.certify(cal._choice(.5,confirmation_samples=2),data)
        self.assertFalse(check['candidate']['passed'])
        self.assertEqual(check['candidate']['scopes'][0]['max_paired_extra_delay_seconds'],540)
        self.assertFalse(check['positive_reference_pulses']['passed'])

    def test_inference_has_no_label_dependency(self):
        data=blocks()[0];selected=cal._choice(.5,confirmation_samples=2)
        expected=cal.predict(data['reference'],data['long_scores'],selected,baseline=data['baseline'])
        data['labels'][:]=-1
        np.testing.assert_array_equal(cal.predict(data['reference'],data['long_scores'],{**selected,'labels':np.ones(7)},baseline=data['baseline']),expected)


if __name__=='__main__':unittest.main()
