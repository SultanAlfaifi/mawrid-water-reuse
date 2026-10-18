"""Synthetic-only adversarial checks of the independent V15 audit."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from ml.gecco_v15 import audit as a, runtime, calibration, checks


def blocks(n=3000):
    out=[]
    for i in range(4):
        y=np.zeros(n,np.int8);v=np.zeros(n,np.int8);s=np.full(n,.1)
        for start in [10,100,200]: y[start:start+5]=1;v[start]=1;s[start:start+5]=.9
        v[50]=1
        out.append({'labels':y,'v6':v.copy(),'v8':v.copy(),'scores':s,'source_start':1000+i*n,'block_id':str(i)})
    return out


class ScalarAuditTests(unittest.TestCase):
    def test_scalar_randomized_matches_vectorized_with_no_future_dependence(self):
        rng=np.random.default_rng(90615)
        for _ in range(35):
            v6=rng.choice([-1,0,1],80,p=[.08,.52,.4]).astype(np.int8)
            v8=rng.choice([-1,0,1],80,p=[.08,.52,.4]).astype(np.int8)
            scores=rng.choice([np.nan,np.inf,-np.inf,.1,.5,.9],80)
            for low in [None,.2,.8]:
                for high in [None,.2,.8]:
                    choice=a._choice(low,high);actual=runtime.components(v6,v8,scores,choice);expected=a.scalar_components(v6,v8,scores,choice)
                    for k in expected: np.testing.assert_array_equal(actual[k],expected[k])
                    cut=37;prefix=a.scalar_components(v6[:cut],v8[:cut],scores[:cut],choice)
                    for k in expected:np.testing.assert_array_equal(prefix[k],expected[k][:cut])
                    changed=scores.copy();changed[cut:]=1.0
                    np.testing.assert_array_equal(a.scalar_components(v6,v8,changed,choice)['final'][:cut],expected['final'][:cut])

    def test_new_pulse_cancels_old_pending_before_same_row_hit(self):
        v6=np.array([0,1,0,1,1,0],np.int8);v8=np.array([0,0,0,1,0,0],np.int8)
        scores=np.array([0,.1,.1,.9,.9,.9]);result=a.scalar_components(v6,v8,scores,a._choice(None,.8))
        self.assertEqual(result['recovery'].tolist(),[0,0,0,0,0,0])
        np.testing.assert_array_equal(result['final'],v8)

    def test_postclear_at_deadline_can_restore_suppressed_anchor_but_not_later(self):
        v6=np.array([0,1,0,0,0],np.int8);v8=np.array([0,0,0,1,1],np.int8)
        early=a.scalar_components(v6,v8,np.array([0,.1,.1,.7,.9]),a._choice(.8,.6))
        self.assertEqual(early['seed'].tolist(),[0,0,0,0,1]);self.assertEqual(early['recovery'].tolist(),[0,0,0,1,0])
        late=a.scalar_components(v6,v8,np.array([0,.1,.1,.1,.9]),a._choice(.8,.6))
        self.assertFalse((late['recovery']==1).any())

    def test_unknown_reference_cancels_latch_and_unknown_score_only_preserves_anchor(self):
        v6=np.array([0,1,1,1,1,1],np.int8);v8=np.array([0,0,0,-1,0,1],np.int8)
        result=a.scalar_components(v6,v8,np.array([0,.9,.1,.9,.9,np.nan]),a._choice(.8,.8))
        self.assertEqual(result['recovery'].tolist(),[0,1,1,-1,0,0]);self.assertEqual(result['seed'][-1],1)
        np.testing.assert_array_equal(result['final']>=0,v8>=0)
        unknown=a.scalar_components(np.array([0,1,0],np.int8),np.zeros(3,np.int8),np.full(3,np.nan),a._choice(None,.8))
        self.assertFalse((unknown['recovery']==1).any())

    def test_continuous_anchor_forces_at_two_samples_but_short_pulse_does_not(self):
        ref=np.array([0,1,1,1,1,0,1,0],np.int8)
        out=a.scalar_components(ref,ref,np.zeros(8),a._choice(.8,None))['seed']
        self.assertEqual(out.tolist(),[0,0,0,1,1,0,0,0])

    def test_censored_and_midpulse_disagreement_never_trigger_recovery(self):
        v6=np.array([1,1,-1,1,1,1,0],np.int8);v8=np.array([0,0,0,1,0,0,0],np.int8)
        out=a.scalar_components(v6,v8,np.ones(7),a._choice(None,.2))
        self.assertFalse((out['recovery']==1).any())

    def test_independent_thresholds_and_validation(self):
        for choice in [a._choice(True,None),{**a._choice(),'cadence_seconds':300},a._choice(None,float('inf'))]:
            with self.assertRaises(ValueError):a.scalar_components(np.zeros(3,np.int8),np.zeros(3,np.int8),np.zeros(3),choice)
        choice=a._choice(.9,.2)
        for key,result in a.scalar_components(np.zeros(0,np.int8),np.zeros(0,np.int8),np.zeros(0),choice).items():self.assertEqual(result.shape,(0,))


class MetricAuditTests(unittest.TestCase):
    def test_full_test_metrics_and_summary_match_frozen_metric_contract(self):
        from ml.gecco_v7.recalibrate_delayed import assess,summarize
        y=np.array([0,1,1,-1,1,0,0,1,1,0],np.int8)
        baseline=np.array([0,1,0,-1,1,0,1,0,1,0],np.int8)
        v6=np.array([0,1,1,-1,1,0,0,0,1,0],np.int8)
        final=np.array([0,0,1,-1,1,0,0,1,0,0],np.int8)
        expected=a.comparisons(y,baseline,v6,final);actual=assess(y,baseline,v6,final)
        a.Evidence().tree('all original metrics',actual,expected)
        periods=[{'comparisons':expected} for _ in range(19)];sources={'synthetic':expected}
        a.Evidence().tree('full summary',summarize(periods,sources),a.summary(periods,sources))

    def test_OR_can_erase_true_onset_even_when_both_experts_have_alarms(self):
        y=np.array([0,0,1,1,0],np.int8);v6=np.array([0,1,0,1,0],np.int8);v8=np.array([0,1,1,0,0],np.int8)
        merged=np.maximum(v6,v8);b={'labels':y,'v6':v6,'v8':v8,'scores':np.ones(5),'source_start':0,'block_id':'0'}
        result=a.joint_assessment([b],[merged])
        self.assertFalse(result['passed']);self.assertEqual(result['lost_union_event_ids'],[1])
        self.assertTrue(result['scopes'][0]['references']['v6']['positive_pulses']['passed'])

    def test_recovery_coverage_does_not_count_as_new_confirmed_event(self):
        b=blocks(300)[:2];seeds=[x['v8'].copy() for x in b];finals=[x.copy() for x in seeds]
        for p in finals:p[11:14]=1
        expected=a.recovery_evidence(b,seeds,finals,True)
        self.assertEqual(expected['new_confirmed_event_ids'],[]);self.assertFalse(expected['passed'])
        a.Evidence().tree('independent recovery schema',checks.recovery_evidence(b,seeds,finals,True),expected)

    def test_recovery_ownership_uses_first_final_confirmation_not_onset(self):
        y=np.zeros(20,np.int8);y[2:6]=1;y[8:16]=1
        final=np.zeros(20,np.int8);final[4]=1;final[12]=1
        b=[{'labels':y[i:i+10],'v6':final[i:i+10],'v8':np.zeros(10,np.int8),'scores':np.zeros(10),'source_start':100+i,'block_id':str(i//10)} for i in [0,10]]
        r=a.recovery_evidence(b,[np.zeros(10,np.int8)]*2,[final[:10],final[10:]],True)
        self.assertTrue(r['passed']);self.assertEqual(r['first_confirmation_blocks'],[0,1]);self.assertEqual(r['new_confirmed_event_ids'],[1,2])
        self.assertEqual(r['restored_reference_event_ids'],[1,2]);self.assertEqual(r['novel_beyond_reference_union_event_ids'],[])
        a.Evidence().tree('boundary ownership',checks.recovery_evidence(b,[np.zeros(10,np.int8)]*2,[final[:10],final[10:]],True),r)

    def test_unknown_positive_segments_remain_pulses_without_inventing_events(self):
        y=np.array([0,1,-1,1,1,0],np.int8);r=np.array([0,1,0,1,0,0],np.int8);p=np.zeros(6,np.int8)
        pulse=a.pulse_evidence(y,r,p,77)
        self.assertEqual(pulse['obligations'],2);self.assertEqual(pulse['censored_fragment_obligations'],1)
        self.assertEqual(a.metric(y,r)['true_events'],1)
        p[4]=1;self.assertEqual(a.pulse_evidence(y,r,p,77)['retained_obligations'],1)

    def test_exposure_requires_known_normal_and_global_known_onset(self):
        b=blocks();expected=a.exposure(b[:2]);self.assertTrue(expected['passed'])
        a.Evidence().tree('exposure',checks.exposure(b[:2]),expected)
        b[0]['labels'][:]=-1;self.assertFalse(a.exposure(b[:2])['checks']['enough_observed_normal_exposure'])
        y=np.zeros(6200,np.int8);y[0:4]=1;y[3099:3103]=1;y[4000:4004]=1
        b=[{'labels':y[i:i+3100],'v6':np.zeros(3100,np.int8),'v8':np.zeros(3100,np.int8),'scores':np.zeros(3100),'source_start':i,'block_id':str(i)} for i in [0,3100]]
        e=a.exposure(b);self.assertEqual(e['primary_events'],2);self.assertEqual(e['eventful_blocks'],[0,1])

    def test_all_grid_winner_and_veto_match_without_production_calls_in_oracle(self):
        b=blocks();expected,trials=a.oracle_calibrate(b);actual,actual_trials=calibration.calibrate(b)
        evidence=a.Evidence();evidence.tree('trials',actual_trials,trials);evidence.tree('selection',actual,expected)
        self.assertTrue(expected['accepted']);self.assertGreater(expected['choice']['anchor_threshold'],.1);self.assertLessEqual(expected['choice']['anchor_threshold'],.9)
        with patch.object(runtime,'components',side_effect=AssertionError('production inference called')),patch.object(checks,'assess',side_effect=AssertionError('production accounting called')):
            again,_=a.oracle_calibrate(b)
        self.assertEqual(again['choice'],expected['choice'])

    def test_supported_recovery_restores_seed_losses_with_final_joint_guards(self):
        b=blocks()
        for block in b:
            block['scores'][100]=.1
            block['v6'][100]=0;block['v6'][101]=1
        expected,trials=a.oracle_calibrate(b);actual,actual_trials=calibration.calibrate(b)
        a.Evidence().tree('supported recovery trials',actual_trials,trials);a.Evidence().tree('supported recovery selection',actual,expected)
        self.assertTrue(expected['accepted']);self.assertIsNotNone(expected['choice']['recovery_threshold'])
        proof=expected['later_certificate']
        self.assertTrue(proof['final']['passed']);self.assertEqual(proof['final']['lost_union_event_ids'],[])
        self.assertTrue(proof['seed']['lost_union_event_ids'])
        self.assertEqual(proof['recovery']['first_confirmation_blocks'],[0,1]);self.assertEqual(len(proof['recovery']['restored_reference_event_ids']),2)

    def test_late_veto_falls_back_without_new_selection(self):
        b=blocks();early,_=a.oracle_calibrate(b)
        for block in b[2:]: block['labels'][50:55]=1
        late,trials=a.oracle_calibrate(b)
        self.assertEqual(late['proposed'],early['proposed']);self.assertFalse(late['accepted']);self.assertEqual(late['choice'],a._choice())
        actual,actual_trials=calibration.calibrate(b);a.Evidence().tree('later veto',actual,late);a.Evidence().tree('unchanged early trials',actual_trials,trials)


class EvidenceAuditTests(unittest.TestCase):
    def test_changed_frozen_input_is_rejected_before_any_numeric_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();run=root/'run';run.mkdir();source=root/'pinned-score.csv.gz';source.write_bytes(b'original')
            digest=a.sha(source);source.write_bytes(b'changed');code=root/'code.py';code.write_text('# synthetic')
            plan={'version':'v15_joint_reference_bounded_recovery','attempt':'v15_run01_frozen_score_policy_only',
                'case_order':a.NAMES,'expected_cases':19,'development_only':True,'fresh_validation':False,
                'all_sources_previously_disclosed':True,'no_model_fit':True,'new_raw_sensor_replay':False,
                'protocol_sha256':a.PROTOCOL_SHA,'no_3d_or_actuation_promotion':True,
                'code_sha256':{'code.py':a.sha(code)},'input_sha256':{'pinned-score.csv.gz':digest}}
            (run/'plan.json').write_text(json.dumps(plan))
            with patch.object(a,'ROOT',root),patch.object(a,'csv',side_effect=AssertionError('numeric CSV must not open')) as reader:
                self.assertEqual(a.execute('calibration',run),1)
            reader.assert_not_called();result=json.loads((run/'calibration-audit.json').read_text())
            self.assertIn('frozen pinned-score.csv.gz',result['error']);self.assertEqual(result['numeric_files_read'],[])

    def test_auditor_imports_only_frozen_metric_module_not_v15_production(self):
        tree=ast.parse(Path(a.__file__).read_text());imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertFalse(any(x and x.startswith('ml.gecco_v15') for x in imports))
        self.assertIn('ml.gecco_v6.unknown_label_metrics',imports)

    def test_frozen_policy_requires_all19_and_all_three_output_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'plan.json').write_text('{}');policies={}
            for name in a.NAMES:
                folder=root/name;folder.mkdir();(folder/'selection.json').write_text(json.dumps({'choice':a._choice(),'accepted':False}));(folder/'trials.json').write_text('[]');(folder/'calibration_predictions.csv.gz').write_bytes(b'synthetic')
                policies[name]={'choice':a._choice(),'accepted':False,'selection_sha256':a.sha(folder/'selection.json'),
                    'trials_sha256':a.sha(folder/'trials.json'),'calibration_predictions_sha256':a.sha(folder/'calibration_predictions.csv.gz')}
            frozen={'all19_calibration_complete':True,'outer_test_numeric_values_opened':False,'plan_sha256':a.sha(root/'plan.json'),'policies':policies}
            (root/'policies-frozen.json').write_text(json.dumps(frozen));a.validate_frozen(root,a.Evidence())
            (root/a.NAMES[0]/'trials.json').write_text('[1]')
            with self.assertRaisesRegex(AssertionError,'trials.json'):a.validate_frozen(root,a.Evidence())
            (root/a.NAMES[0]/'trials.json').write_text('[]');del frozen['policies'][a.NAMES[-1]];(root/'policies-frozen.json').write_text(json.dumps(frozen))
            with self.assertRaisesRegex(AssertionError,'identities'):a.validate_frozen(root,a.Evidence())

    def test_calibration_stage_refuses_after_test_start_before_any_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);(run/'test-started.json').write_text('{}');(run/'plan.json').write_text('{}');(run/'policies-frozen.json').write_text('{}')
            with patch.object(a,'verify_plan',return_value=({},{})),patch.object(a,'validate_frozen',return_value={}),patch.object(a,'csv',side_effect=AssertionError('numeric CSV must not open')) as reader:
                self.assertEqual(a.execute('calibration',run),1)
            reader.assert_not_called();result=json.loads((run/'calibration-audit.json').read_text())
            self.assertFalse(result['passed']);self.assertIn('no test access',result['error']);self.assertEqual(result['numeric_files_read'],[])

    def test_exact_tree_rejects_boolean_pass_fabrication_and_metric_drift(self):
        for actual,expected in [({'passed':1},{'passed':True}),({'tp':2},{'tp':1}),({'confirmed_event_ids':[2]},{'confirmed_event_ids':[1]})]:
            with self.assertRaises(AssertionError):a.Evidence().tree('bad',actual,expected)


if __name__=='__main__': unittest.main()
