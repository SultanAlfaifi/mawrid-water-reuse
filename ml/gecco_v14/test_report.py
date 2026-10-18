"""Synthetic V14 reporting contracts; no actual run, models or source values."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from ml.gecco_v9.diagnose import compare_rows
from ml.gecco_v14 import report, diagnose


def write(path, value):
    path.write_text(json.dumps(value))


def if_evidence():
    return {'prior_and_attached_fitted_states_identical': True,
            'representation_is_in_sample_not_cross_fitted': True,
            'original_if_refitted_by_audit': False}


def weight_evidence():
    return {'quantile':.95,'quantile_method':'linear','window_offsets_samples':[0,1,2],
            'q95':.6,'label_onset_bonus_mass':0.,'bonus_redistributed_to_event_uniform':False,'confirmed_tail_pulses':8,'censored_tail_episodes':2,
            'eligible_bonus_segments':3,'eligible_bonus_pulses':4,'eligible_bonus_rows':8,
            'normal_weight_mass':.5,'positive_weight_mass':.5,'unknown_weight_mass':0.,
            'point_component_mass':.125,'event_component_mass':.125,'pulse_component_mass':.25,
            **{key:True for key in report.PULSE_AUDIT_FLAGS}}


def design_fixture(root):
    return {key:{'path':str(root/name),'sha256':'synthetic-'+key}
            for key,name in (('protocol','protocol.json'),('training_support','training-support.json'))}


def independent_summary(result,diagnosis):
    facts=report.user_objectives(result,diagnosis)
    h={v.lower():item['all_periods_and_pools_retain_event_ids'] for v,item in facts['historical_retention'].items()}
    c=facts['v8_improvement_checks']
    return {'historical_event_retention_by_version':h,'all_historical_event_ids_retained':all(h.values()),
        'passes_v8_user_objective':facts['user_v8_improvement_objective_met'],
        'v8_user_objective_checks':{
            'all19_periods_and_source_pools_evaluated':True,
            'every_period_and_pool_preserves_v8_event_ids':c['all_periods_and_pools_retain_original_event_ids'],
            'every_period_and_pool_availability_equal':c['all_periods_and_pools_keep_availability'],
            'every_period_and_pool_extra_delay_within120':c['all_paired_event_delays_at_most120s'],
            'every_period_and_pool_fp_runs_nonincreasing':c['no_scope_increases_false_fragments'],
            'every_period_and_pool_fp_duration_nonincreasing':c['no_scope_increases_false_duration'],
            'strictly_fewer_pooled_false_runs':c['strictly_fewer_pooled_false_fragments'],
            'false_run_reduction_in_at_least_two_periods':c['false_fragment_reduction_in_at_least_two_periods']}}


def manifest(run):
    result = {'candidate_version':'V14','complete_cases':19,'expected_cases':19,
        'all_prespecified_cases_complete':True,'completed_at_utc':'2026-01-01T00:00:00Z',
        'development_only':True,'fresh_validation':False,'maximum_allowed_extra_delay_seconds':120,
        'historical_retention_required':True,'v8_user_objective_required':True,
        'periods':[{'case':name} for name in report.EXPECTED_NAMES]}
    plan = {'scope':'all','limit_cases':19,'expected_cases':19,'attempt':report.ATTEMPT,'case_order':report.EXPECTED_NAMES,'design_protocol_sha256':report.PROTOCOL_SHA256,
        'input_sha256':{report.PROTOCOL_RELATIVE:report.PROTOCOL_SHA256}}
    write(run/'results.json',result);write(run/'plan.json',plan)
    audit = {'passed':True,'failed_checks':0,'complete_replayed_cases':19,
        'audit_version':report.AUDIT_VERSION,'attempt':report.ATTEMPT,
        'hashes':{key:report.sha(run/key) for key in ('results.json','plan.json')},
        'if_evidence_audit_by_case':{name:if_evidence() for name in report.EXPECTED_NAMES},
        'sensor_tail_pulse_weighting_audit_by_case':{name:weight_evidence() for name in report.EXPECTED_NAMES}}
    write(run/'audit.json',audit)
    return result,plan,audit


def objectives_fixture():
    labels=np.array([0,1,1,1,1,0,0,0,0,1,1,0],np.int8)
    before=np.array([0,1,0,0,0,1,0,0,0,1,0,0],np.int8)
    after=before.copy();after[5]=0
    pair=compare_rows(labels,before,after);pair['noninferior']=True
    original={key:deepcopy(pair) for key in report.PAIRS}
    result={'periods':[{'case':name,'comparisons':deepcopy(original)} for name in report.EXPECTED_NAMES],
        'sources':{name:deepcopy(original) for name in ('2017','2018','2019','WaterHub')},
        'summary':{key:{'baseline':pair['baseline'],'candidate':pair['candidate'],
                       'checks':{'strictly_more_pooled_events':False},'passes_declared_development_gate':False} for key in report.PAIRS},
        'completed_at_utc':'2026-01-01T00:00:00Z'}
    historical={v.lower()+'_vs_v14':deepcopy(pair) for v in report.HISTORICAL}
    diagnosis={'cross_run_period_comparison':[{'case':name,**deepcopy(historical)} for name in report.EXPECTED_NAMES],
        'cross_run_source_comparison':{name:deepcopy(historical) for name in result['sources']}}
    return result,diagnosis,pair


class CompletedAuditGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.run=Path(self.tmp.name);self.result,self.plan,self.audit=manifest(self.run)
        self.folders={v.lower():self.run/v.lower() for v in report.HISTORICAL}
        self.parent=patch.object(report,'load_v13_verified',return_value=({'version':'V13'},None,None,{}))
        self.mock_parent=self.parent.start();self.addCleanup(self.parent.stop)

    def test_only_matching_complete_new_audit_accepts(self):
        value=report.load_verified(self.run,self.folders)
        self.assertEqual(value[0]['candidate_version'],'V14')
        self.assertEqual(value[3],{'V13':{'version':'V13'}})
        self.mock_parent.assert_called_once_with(self.folders['v13'],self.folders)

    def test_replay_audit_filename_supported(self):
        (self.run/'audit.json').rename(self.run/'replay_audit.json')
        self.assertEqual(report.load_verified(self.run,self.folders)[1].name,'replay_audit.json')

    def test_partial_duplicate_reordered_and_failed_runs_rejected_before_parent(self):
        for kind in ('partial','duplicate','reordered','failed'):
            with self.subTest(kind=kind):
                result=deepcopy(self.result)
                if kind=='partial':result['complete_cases']=18
                elif kind=='duplicate':result['periods'][-1]=result['periods'][0]
                elif kind=='reordered':result['periods'].reverse()
                else:write(self.run/'failed_case.json',{'case':'a'})
                write(self.run/'results.json',result)
                with self.assertRaises(ValueError):report.load_verified(self.run,self.folders)
                (self.run/'failed_case.json').unlink(missing_ok=True)
        self.mock_parent.assert_not_called()

    def test_missing_failed_wrong_version_or_stale_audit_is_not_success(self):
        for kind in ('missing','failed','wrong_version','wrong_attempt','partial_audit','stale_result','stale_plan'):
            with self.subTest(kind=kind):
                audit=deepcopy(self.audit)
                if kind=='failed':audit['passed']=False
                elif kind=='wrong_version':audit['audit_version']='v12_frozen_if_evidence_full_raw_sensor_batch_replay_v1'
                elif kind=='wrong_attempt':audit['attempt']='other'
                elif kind=='partial_audit':audit['complete_replayed_cases']=18
                elif kind=='stale_result':audit['hashes']['results.json']='0'*64
                elif kind=='stale_plan':audit['hashes']['plan.json']='0'*64
                write(self.run/'audit.json',audit)
                if kind=='missing':(self.run/'audit.json').unlink()
                with self.assertRaises(ValueError):report.load_verified(self.run,self.folders)
        self.mock_parent.assert_not_called()

    def test_pulse_contract_and_original_if_must_each_be_verified(self):
        for section,key,value in [
            ('sensor_tail_pulse_weighting_audit_by_case','quantile',.9),
            ('sensor_tail_pulse_weighting_audit_by_case','quantile_method','nearest'),
            ('sensor_tail_pulse_weighting_audit_by_case','window_offsets_samples',[0,1,2,3]),
            ('sensor_tail_pulse_weighting_audit_by_case','label_onset_bonus_mass',.25),
            ('sensor_tail_pulse_weighting_audit_by_case','bonus_redistributed_to_event_uniform',None),
            *[('sensor_tail_pulse_weighting_audit_by_case',key,False) for key in report.PULSE_AUDIT_FLAGS],
            ('if_evidence_audit_by_case','prior_and_attached_fitted_states_identical',False)]:
            with self.subTest(key=key):
                audit=deepcopy(self.audit);audit[section][report.EXPECTED_NAMES[0]][key]=value
                write(self.run/'audit.json',audit)
                with self.assertRaises(ValueError):report.load_verified(self.run,self.folders)
        audit=deepcopy(self.audit);audit['sensor_tail_pulse_weighting_audit_by_case'].pop(report.EXPECTED_NAMES[-1]);write(self.run/'audit.json',audit)
        with self.assertRaises(ValueError):report.load_verified(self.run,self.folders)

    def test_protocol_hash_must_match_both_plan_pins_before_parent(self):
        for key in ('design_protocol_sha256','input_sha256'):
            plan=deepcopy(self.plan)
            if key=='input_sha256':plan[key][report.PROTOCOL_RELATIVE]='0'*64
            else:plan[key]='0'*64
            write(self.run/'plan.json',plan)
            audit=deepcopy(self.audit);audit['hashes']['plan.json']=report.sha(self.run/'plan.json');write(self.run/'audit.json',audit)
            with self.assertRaises(ValueError):report.load_verified(self.run,self.folders)
        self.mock_parent.assert_not_called()

    def test_parent_audit_failure_propagates(self):
        self.mock_parent.side_effect=ValueError('parent audit missing')
        with self.assertRaisesRegex(ValueError,'parent audit'):report.load_verified(self.run,self.folders)


class ExactUserObjectiveTests(unittest.TestCase):
    def test_retention_and_v8_improvement_pass_without_redefining_strong_gate(self):
        result,diagnosis,_=objectives_fixture();before=deepcopy(result['summary'])
        facts=report.user_objectives(result,diagnosis)
        self.assertTrue(facts['current_user_retention_and_false_alarm_goal_met'])
        self.assertTrue(facts['user_v8_improvement_objective_met'])
        self.assertEqual(result['summary'],before)
        self.assertFalse(any(x['passes_declared_development_gate'] for x in result['summary'].values()))

    def test_equal_aggregate_event_count_cannot_hide_exact_v8_id_loss(self):
        result,diagnosis,_=objectives_fixture();c=diagnosis['cross_run_period_comparison'][0]['v8_vs_v14']
        self.assertEqual(c['baseline']['confirmed_events'],c['candidate']['confirmed_events'])
        c['lost_baseline_event_ids']=[1];c['new_candidate_event_ids']=[3]
        facts=report.user_objectives(result,diagnosis)
        self.assertFalse(facts['exact_historical_event_retention_met'])
        self.assertTrue(facts['v8_improvement_checks']['strictly_fewer_pooled_false_fragments'])
        self.assertFalse(facts['user_v8_improvement_objective_met'])
        self.assertFalse(facts['current_user_retention_and_false_alarm_goal_met'])

    def test_retention_all_versions_and_source_pools_is_required(self):
        for version in ('v8','v9','v10','v11','v12','v13'):
            with self.subTest(version=version):
                result,d,_=objectives_fixture();d['cross_run_source_comparison']['WaterHub'][version+'_vs_v14']['lost_baseline_event_ids']=[83]
                self.assertFalse(report.user_objectives(result,d)['exact_historical_event_retention_met'])
        result,d,_=objectives_fixture();result['periods'][0]['comparisons']['v6_vs_v7']['lost_baseline_event_ids']=[4]
        self.assertFalse(report.user_objectives(result,d)['exact_historical_event_retention_met'])

    def test_pooled_gain_never_pays_for_one_period_v8_false_alarm_increase(self):
        for field in ('false_positive_runs','fp_duration_seconds'):
            with self.subTest(field=field):
                result,d,_=objectives_fixture();c=d['cross_run_period_comparison'][0]['v8_vs_v14']
                c['candidate'][field]=c['baseline'][field]+1
                self.assertFalse(report.user_objectives(result,d)['user_v8_improvement_objective_met'])

    def test_source_pool_delay_availability_and_strict_fp_reduction(self):
        for kind in ('duration','fragments','delay','availability','no_strict_reduction'):
            with self.subTest(kind=kind):
                result,d,_=objectives_fixture();c=d['cross_run_source_comparison']['WaterHub']['v8_vs_v14']
                if kind=='duration':c['candidate']['fp_duration_seconds']=c['baseline']['fp_duration_seconds']+60
                elif kind=='fragments':c['candidate']['false_positive_runs']=c['baseline']['false_positive_runs']+1
                elif kind=='delay':c['paired_extra_delays'][0]['extra_delay_seconds']=180
                elif kind=='availability':c['sensor_availability_equal']=False
                else:
                    for scopes in d['cross_run_source_comparison'].values():
                        pair=scopes['v8_vs_v14'];pair['candidate']['false_positive_runs']=pair['baseline']['false_positive_runs']
                self.assertFalse(report.user_objectives(result,d)['user_v8_improvement_objective_met'])
        result,d,_=objectives_fixture();d['cross_run_period_comparison'][0]['v8_vs_v14']['paired_extra_delays'][0]['extra_delay_seconds']=120
        self.assertTrue(report.user_objectives(result,d)['user_v8_improvement_objective_met'])

    def test_v8_false_fragment_reduction_must_span_two_periods(self):
        result,d,_=objectives_fixture()
        for item in d['cross_run_period_comparison'][1:]:
            pair=item['v8_vs_v14'];pair['candidate']['false_positive_runs']=pair['baseline']['false_positive_runs']
        facts=report.user_objectives(result,d)
        self.assertTrue(facts['v8_improvement_checks']['strictly_fewer_pooled_false_fragments'])
        self.assertFalse(facts['v8_improvement_checks']['false_fragment_reduction_in_at_least_two_periods'])
        self.assertFalse(facts['user_v8_improvement_objective_met'])

    def test_independent_retention_is_separate_from_original_reference_retention(self):
        result,d,_=objectives_fixture()
        result['periods'][0]['comparisons']['v6_vs_v7']['lost_baseline_event_ids']=[4]
        facts=report.user_objectives(result,d)
        audit={'historical_comparisons':{'summary':independent_summary(result,d)}}
        self.assertFalse(facts['exact_historical_event_retention_met'])
        self.assertTrue(audit['historical_comparisons']['summary']['all_historical_event_ids_retained'])
        report.verify_independent_objectives(audit,facts)

    def test_independent_mismatch_is_rejected_instead_of_publishing_a_win(self):
        result,d,_=objectives_fixture();facts=report.user_objectives(result,d)
        base=independent_summary(result,d)
        corruptions=[('historical_event_retention_by_version','v13'),
            ('summary','all_historical_event_ids_retained'),('summary','passes_v8_user_objective'),
            *[('v8_user_objective_checks',key) for key in base['v8_user_objective_checks']]]
        for section,key in corruptions:
            with self.subTest(section=section,key=key):
                summary=deepcopy(base)
                if section=='summary':summary[key]=False
                else:summary[section][key]=False
                with self.assertRaises(ValueError):report.verify_independent_objectives(
                    {'historical_comparisons':{'summary':summary}},facts)
        for version in report.HISTORICAL:
            summary=deepcopy(base);summary['historical_event_retention_by_version'].pop(version.lower())
            with self.assertRaises(ValueError):report.verify_independent_objectives(
                {'historical_comparisons':{'summary':summary}},facts)

    def test_render_preserves_nine_models_and_separates_user_success_from_strong_gate(self):
        result,d,pair=objectives_fixture()
        selected={'status':'earlier_reference_retained','decision':'reference','low_threshold':None,
            'high_threshold':None,'confirmation_delay_seconds':0,'pending_after_clear':False,
            'certification_rejection_reasons':[]}
        policies=[]
        for p in result['periods']:
            p['selected']=deepcopy(selected)
            p['conditional_block_test_coverage']={'observed_on_reference_available_rows':12,'reference_available_rows':12}
            policies.append({'case':p['case'],'pending_grid_feasible_trials':0,'pending_grid_trials':0})
        d.update(policy_evidence_by_period=policies,timing_comparison=[],pending_selected_periods=[])
        history={}
        for v in report.HISTORICAL:
            old=deepcopy(result)
            for p in old['periods']:
                for key in report.PAIRS:p['comparisons'][key]['candidate']=deepcopy(pair['baseline'])
            for scopes in old['sources'].values():
                for key in report.PAIRS:scopes[key]['candidate']=deepcopy(pair['baseline'])
            for key in report.PAIRS:old['summary'][key]['candidate']=deepcopy(pair['baseline'])
            history[v]=old
        audit={'if_evidence_audit_by_case':{name:if_evidence() for name in report.EXPECTED_NAMES},
               'sensor_tail_pulse_weighting_audit_by_case':{name:weight_evidence() for name in report.EXPECTED_NAMES},
               'historical_comparisons':{'summary':independent_summary(result,d)}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(report,'sha',return_value='synthetic-only'):
            run=Path(tmp);folders={v.lower():run/v.lower() for v in (*report.HISTORICAL,'V14')}
            args=(run,run/'report.html',result,run/'audit.json',audit,history,folders,run/'post_test_diagnosis.json',d)
            proof={'bundled_path':str(run/'evidence/verification-v3.json'),'sha256':'synthetic-proof'}
            html,status=report.render(*args,software_verification=proof,design=design_fixture(run))
            self.assertEqual(status['phase'],'retention_goal_met_strong_gate_failed')
            self.assertTrue(status['current_user_retention_and_false_alarm_goal_met'])
            self.assertFalse(status['passes_declared_development_gate'])
            self.assertFalse(status['strong_gate_changed'])
            self.assertEqual(status['added_feature_count'],0)
            self.assertFalse(status['v14_live_stream_tested'])
            self.assertEqual(status['statistical_base_version'],'V12')
            self.assertTrue(status['independent_historical_objectives_crosschecked'])
            self.assertIn('جميع نبضات ذيل IF المؤكدة',html)
            self.assertIn('V13 مقارنة تاريخية',html)
            self.assertNotIn('وزنًا نسبيًا 5 مقابل 1',html)
            self.assertIn('protocol.json',html);self.assertIn('training-support.json',html)
            for model in report.MODELS:self.assertIn('<th>'+model+'</th>',html)
            self.assertIn('verification-v3',html)
            self.assertIn('href="evidence/verification-v3.json"',html)
            self.assertNotIn('../../mawrid-system/verification-v3.json',html)
            self.assertEqual(status['artifact_hashes']['software_verification_v3'],'synthetic-proof')
            self.assertIn('غير متاح',html)  # Missing audit counts are not zero.
            self.assertIn('0 من 0',html)
            self.assertIn('q95',html)
            d['cross_run_period_comparison'][0]['v8_vs_v14']['lost_baseline_event_ids']=[1]
            audit['historical_comparisons']['summary']=independent_summary(result,d)
            _,failed=report.render(*args,software_verification=proof,design=design_fixture(run))
            self.assertEqual(failed['phase'],'current_retention_goal_failed')
            self.assertFalse(failed['current_user_retention_and_false_alarm_goal_met'])

    def test_diagnostic_score_comparison_is_v12_and_not_an_inference_operation(self):
        import pandas as pd
        current=pd.DataFrame({'label':[0,1,-1,0],'reference':[0,1,0,-1],'long_context':[.2,.8,.4,.9]})
        previous=current.copy();previous['long_context']=[.1,.7,.3,.1]
        values=diagnose.score_description(current,previous)
        self.assertEqual(values['normal']['rows'],1)
        self.assertIn('v12_raw_confidence',values['normal']);self.assertIn('v14_raw_confidence',values['normal'])
        self.assertEqual(values['unknown']['rows'],1)
        values13=diagnose.score_description(current,previous,'v13')
        self.assertIn('v13_raw_confidence',values13['positive'])
        self.assertNotIn('v12_raw_confidence',values13['positive'])
        self.assertEqual(values13['positive']['v14_raw_confidence'],values['positive']['v14_raw_confidence'])

    def test_partial_diagnosis_stops_before_any_prediction_or_calibration_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);write(run/'results.json',{'candidate_version':'V14','complete_cases':18})
            with patch.object(diagnose.pd,'read_csv',side_effect=AssertionError('partial row access')) as rows:
                with self.assertRaises(ValueError):diagnose.describe(run,{v:run/v for v in diagnose.HISTORICAL})
                rows.assert_not_called()


class PinnedDesignEvidenceTests(unittest.TestCase):
    def test_design_and_support_links_have_exact_pinned_hashes_and_no_test_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);protocol=root/report.PROTOCOL_RELATIVE;support=root/report.TRAINING_SUPPORT_RELATIVE
            protocol.parent.mkdir(parents=True)
            protocol.write_bytes(b'{"candidate":"V14"}\n')
            scope={key:False for key in ('source_measurements_decoded','calibration_or_test_rows_decoded',
                'model_refitted','new_weights_computed','alternate_policy_executed','q95_selected_from_this_diagnosis')}
            write(support,scope)
            with patch.object(report,'ROOT',root),patch.object(report,'PROTOCOL_SHA256',report.sha(protocol)),\
                 patch.object(report,'TRAINING_SUPPORT_SHA256',report.sha(support)):
                evidence=report.design_evidence()
                self.assertEqual(evidence['protocol'],{'path':str(protocol),'sha256':report.sha(protocol)})
                self.assertEqual(evidence['training_support']['sha256'],report.sha(support))
                support.write_text(support.read_text()+' ')
                with self.assertRaisesRegex(ValueError,'changed'):report.design_evidence()
                scope['calibration_or_test_rows_decoded']=True;write(support,scope)
                with patch.object(report,'TRAINING_SUPPORT_SHA256',report.sha(support)):
                    with self.assertRaisesRegex(ValueError,'descriptive'):report.design_evidence()

    def test_invalid_design_never_publishes_or_copies_engineering_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'output/mawrid-system/verification-v3.json'
            source.parent.mkdir(parents=True);source.write_bytes(b'{}')
            destination=root/'output/ml/gecco-v14/report.html'
            with patch.object(report,'ROOT',root),patch.object(report,'load_verified',return_value=({},None,{},{})),\
                 patch.object(report,'load_diagnosis',return_value=(None,{})),\
                 patch.object(report,'design_evidence',side_effect=ValueError('design changed')):
                with self.assertRaisesRegex(ValueError,'design changed'):report.build(root/'run',destination)
            self.assertFalse(destination.parent.exists())


class PortableSoftwareEvidenceTests(unittest.TestCase):
    def test_builder_copies_exact_bytes_and_records_hash_after_all_audit_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'output/mawrid-system/verification-v3.json'
            source.parent.mkdir(parents=True);payload=b'{ "scope": "V9 only", "field_ready": false }\r\n';source.write_bytes(payload)
            destination=root/'output/ml/gecco-v14/report.html'
            def rendered(*args,software_verification,design):
                return report.link(Path(software_verification['bundled_path']),destination,'proof'), {
                    'software_verification_evidence':software_verification,
                    'artifact_hashes':{'software_verification_v3':software_verification['sha256']}}
            with patch.object(report,'ROOT',root),patch.object(report,'load_verified',return_value=({},None,{},{})) as gate,\
                 patch.object(report,'load_diagnosis',return_value=(None,{})),patch.object(report,'design_evidence',return_value=design_fixture(root)),patch.object(report,'render',side_effect=rendered):
                status=report.build(root/'run',destination)
                gate.assert_called_once()
                bundled=destination.parent/'evidence/verification-v3.json'
                self.assertEqual(bundled.read_bytes(),payload)
                digest=hashlib.sha256(payload).hexdigest()
                self.assertEqual(status['artifact_hashes']['software_verification_v3'],digest)
                self.assertEqual(json.loads((destination.parent/'status.json').read_text())['software_verification_evidence']['sha256'],digest)
                self.assertEqual(destination.read_text(),'<a href="evidence/verification-v3.json">proof</a>')
                # Existing reports remain protected, including their bundled proof.
                source.write_bytes(b'{"changed":true}')
                with self.assertRaises(FileExistsError):report.build(root/'run',destination)
                self.assertEqual(bundled.read_bytes(),payload)

    def test_missing_or_mismatched_proof_never_generates_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();destination=root/'output/ml/gecco-v14/report.html'
            with patch.object(report,'ROOT',root),patch.object(report,'load_verified',return_value=({},None,{},{})),\
                 patch.object(report,'load_diagnosis',return_value=(None,{})),patch.object(report,'design_evidence',return_value=design_fixture(root)),patch.object(report,'render') as renderer:
                with self.assertRaises(FileNotFoundError):report.build(root/'run',destination)
                source=root/'output/mawrid-system/verification-v3.json';source.parent.mkdir(parents=True);source.write_bytes(b'{}')
                bundled=destination.parent/'evidence/verification-v3.json';bundled.parent.mkdir(parents=True);bundled.write_bytes(b'{"old":true}')
                with self.assertRaises(FileExistsError):report.build(root/'run',destination)
                renderer.assert_not_called();self.assertFalse(destination.exists())

    def test_failed_audit_does_not_bundle_or_publish_software_evidence(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(report,'load_verified',side_effect=ValueError('audit incomplete')),\
             patch.object(report,'software_evidence') as evidence:
            with self.assertRaises(ValueError):report.build(Path(tmp)/'run',Path(tmp)/'report.html')
            evidence.assert_not_called();self.assertEqual(list(Path(tmp).iterdir()),[])


if __name__=='__main__':unittest.main()
