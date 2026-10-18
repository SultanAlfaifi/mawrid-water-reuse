"""Nine-model Arabic V14 report; complete results and exact PASS audits only.

Reads saved results, audits and hashed descriptive diagnostics. It never fits,
reads source measurements, evaluates a different policy or opens partial rows.
V14 is a new HGB fit: historical confidence/model identity is not assumed.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from ml.gecco_v8.report import EXPECTED_NAMES,PAIRS,METRIC_HEAD,audit_count,esc,link,ltr,maximum_delay,metric_row,number,pct,read,sha
from ml.gecco_v10.report import objective_facts
from ml.gecco_v13.report import load_verified as load_v13_verified

ROOT=Path(__file__).resolve().parents[2]
HISTORICAL=('V8','V9','V10','V11','V12','V13')
MODELS=('IF','V6',*HISTORICAL,'V14')
ATTEMPT='v14_run01_sensor_tail_pulse_weights'
AUDIT_VERSION='v14_sensor_tail_pulse_full_raw_sensor_batch_replay_v1'
PROTOCOL_RELATIVE='output/ml/gecco-v14-design/protocol.json'
PROTOCOL_SHA256='c0a9098be7fc107aa883e8e2b31f25acfe462b58648af7c4530371c92367c2e4'
TRAINING_SUPPORT_RELATIVE='output/ml/gecco-v14-design/training-support.json'
TRAINING_SUPPORT_SHA256='2d36320f2312c6711d117e26ce8997cc280018af1fdc08a7954147f419a94a0b'
PULSE_AUDIT_FLAGS=('tail_inclusive','all_confirmed_pulses','truncate_at_tail_end',
    'previous_finite_below_required','no_label_boundary_reset','q95_uses_training_only',
    'normal_uniform','unknown_weights_zero','segment_pulse_row_balancing',
    'global_no_bonus_fallback','if_state_unchanged','no_classifier_or_if_refit_by_auditor')


def validate_weighting_audit(audit):
    weighting=audit.get('sensor_tail_pulse_weighting_audit_by_case',{})
    if set(weighting)!=set(EXPECTED_NAMES):raise ValueError('All19 independent sensor-tail pulse weight audits required')
    for item in weighting.values():
        if (item.get('quantile')!=.95 or item.get('quantile_method')!='linear'
            or item.get('window_offsets_samples')!=[0,1,2]
            or item.get('label_onset_bonus_mass')!=0.
            or type(item.get('bonus_redistributed_to_event_uniform')) is not bool
            or any(item.get(k) is not True for k in PULSE_AUDIT_FLAGS)):
            raise ValueError('Sensor-tail pulse weighting audit contract mismatch')


def load_verified(run,folders):
    result,plan=read(run/'results.json'),read(run/'plan.json')
    if (result.get('candidate_version')!='V14' or result.get('complete_cases')!=19 or result.get('expected_cases')!=19
        or result.get('all_prespecified_cases_complete') is not True or not result.get('completed_at_utc')
        or [p.get('case') for p in result.get('periods',[])]!=EXPECTED_NAMES or (run/'failed_case.json').exists()
        or result.get('development_only') is not True or result.get('fresh_validation') is not False
        or result.get('maximum_allowed_extra_delay_seconds')!=120
        or result.get('historical_retention_required') is not True or result.get('v8_user_objective_required') is not True
        or plan.get('case_order') != EXPECTED_NAMES
        or plan.get('scope')!='all' or plan.get('limit_cases')!=19 or plan.get('expected_cases')!=19 or plan.get('attempt')!=ATTEMPT
        or plan.get('design_protocol_sha256')!=PROTOCOL_SHA256
        or plan.get('input_sha256',{}).get(PROTOCOL_RELATIVE)!=PROTOCOL_SHA256):
        raise ValueError('All19 fixed V14 disclosed-development results required')
    audit_path=next((run/n for n in ('audit.json','replay_audit.json') if (run/n).is_file()),None)
    if audit_path is None:raise ValueError('Awaiting V14 independent audit')
    audit=read(audit_path)
    if (audit.get('passed') is not True or audit.get('failed_checks')!=0 or audit.get('complete_replayed_cases')!=19
        or audit.get('audit_version')!=AUDIT_VERSION or audit.get('attempt')!=ATTEMPT
        or audit.get('hashes',{}).get('results.json')!=sha(run/'results.json')
        or audit.get('hashes',{}).get('plan.json')!=sha(run/'plan.json')):
        raise ValueError('Exact all19 passing V14 audit required')
    evidence=audit.get('if_evidence_audit_by_case',{})
    if set(evidence)!=set(EXPECTED_NAMES):raise ValueError('Original IF evidence accounting requires all19 cases')
    for item in evidence.values():
        if (item.get('prior_and_attached_fitted_states_identical') is not True
            or item.get('representation_is_in_sample_not_cross_fitted') is not True
            or item.get('original_if_refitted_by_audit') is not False):raise ValueError('Original IF lineage or representation audit mismatch')
    validate_weighting_audit(audit)
    v13,_,_,older=load_v13_verified(folders['v13'],folders)
    # Historical audits are comparators, not a claim that V14 inherited their
    # fitted HGB, scores or V11 hard-protection policy.
    return result,audit_path,audit,{**older,'V13':v13}


def design_evidence():
    """Pinned design and train-only description; no new measurement access."""
    result={}
    for key,relative,digest in (('protocol',PROTOCOL_RELATIVE,PROTOCOL_SHA256),
                               ('training_support',TRAINING_SUPPORT_RELATIVE,TRAINING_SUPPORT_SHA256)):
        path=ROOT/relative
        if sha(path)!=digest:raise ValueError('Pinned V14 design evidence changed: '+key)
        value=read(path)
        if key=='training_support' and any(value.get(k) is not False for k in (
            'source_measurements_decoded','calibration_or_test_rows_decoded','model_refitted',
            'new_weights_computed','alternate_policy_executed','q95_selected_from_this_diagnosis')):
            raise ValueError('Training-support scope is not purely descriptive')
        result[key]={'path':str(path),'sha256':digest}
    return result


def load_diagnosis(run,folders,result):
    path=run/'post_test_diagnosis.json';d=read(path)
    if (d.get('candidate_version')!='V14' or d.get('cross_run_axis_verified') is not True
        or d.get('original_if_v6_predictions_unchanged') is not True or d.get('experiment_refitted_hgb') is not True
        or any(d.get(k) is not False for k in ('experiment_refitted_original_if','fresh_validation','new_source_accessed',
            'model_refitted_by_diagnosis','thresholds_changed','policies_reexecuted_for_diagnosis'))):
        raise ValueError('Read-only same-axis diagnosis of newly fitted V14 HGB required')
    for version,folder in folders.items():
        if Path(d['comparison_runs'][version]).resolve()!=folder or d['cross_run_input_sha256'].get(str(folder/'results.json'))!=sha(folder/'results.json'):
            raise ValueError('Diagnosis run identity changed')
    for relative,digest in d['input_sha256'].items():
        if sha(run/relative)!=digest:raise ValueError('Diagnosis input changed')
    for absolute,digest in d['cross_run_input_sha256'].items():
        if sha(Path(absolute))!=digest:raise ValueError('Cross-run diagnosis input changed')
    for key in ('cross_run_period_comparison','policy_evidence_by_period','conditional_coverage_by_period','score_comparison_by_period','row_identity_by_period'):
        if [p['case'] for p in d[key]]!=EXPECTED_NAMES:raise ValueError('Missing or reordered diagnostic periods')
    if set(d['cross_run_source_comparison'])!=set(result['sources']):raise ValueError('Missing connected source axis')
    active={p['case'] for p in result['periods'] if p['selected']['decision']!='reference'}
    if {p['case'] for p in d['active_periods']}!=active or {p['case'] for p in d['fallbacks']}!=set(EXPECTED_NAMES)-active:
        raise ValueError('Active/reference diagnostic coverage mismatch')
    return path,d


def across(values):return ltr(' | '.join(name+' '+str(value) for name,value in zip(MODELS,values)))
def table_models(metrics):return ''.join(metric_row(name,metric) for name,metric in zip(MODELS,metrics))
def comparison_text(comps,key):return ltr(' | '.join(name+' '+str(comp[key]) for name,comp in comps))


def historical_retention(d):
    out={}
    for version in HISTORICAL:
        key=version.lower()+'_vs_v14'
        scopes=[p[key] for p in d['cross_run_period_comparison']]+[s[key] for s in d['cross_run_source_comparison'].values()]
        out[version]={'all_periods_and_pools_retain_event_ids':all(not c['lost_baseline_event_ids'] for c in scopes),
            'all_periods_and_pools_noninferior_with120s':all(c['noninferior_with_120s_limit'] for c in scopes),
            'lost_ids_by_period':{p['case']:p[key]['lost_baseline_event_ids'] for p in d['cross_run_period_comparison'] if p[key]['lost_baseline_event_ids']},
            'lost_ids_by_source':{name:c[key]['lost_baseline_event_ids'] for name,c in d['cross_run_source_comparison'].items() if c[key]['lost_baseline_event_ids']}}
    return out


def user_objectives(result, diagnosis):
    """Prespecified facts; historical retention and V8 cost are separate gates."""
    original = objective_facts(result)
    history = historical_retention(diagnosis)
    original_retained = all(v['all_periods_and_pools_retain_original_event_ids'] for v in original.values())
    retained = original_retained and all(v['all_periods_and_pools_retain_event_ids'] for v in history.values())
    scopes = [p['v8_vs_v14'] for p in diagnosis['cross_run_period_comparison']]
    pools = [s['v8_vs_v14'] for s in diagnosis['cross_run_source_comparison'].values()]
    v8 = {
        'all_periods_and_pools_retain_original_event_ids': all(not s['lost_baseline_event_ids'] for s in scopes+pools),
        'all_periods_and_pools_keep_availability': all(s['sensor_availability_equal'] for s in scopes+pools),
        'all_paired_event_delays_at_most120s': all(d['extra_delay_seconds'] <= 120 for s in scopes+pools for d in s['paired_extra_delays']),
        'no_scope_increases_false_fragments': all(s['candidate']['false_positive_runs'] <= s['baseline']['false_positive_runs'] for s in scopes+pools),
        'no_scope_increases_false_duration': all(s['candidate']['fp_duration_seconds'] <= s['baseline']['fp_duration_seconds'] for s in scopes+pools),
        'strictly_fewer_pooled_false_fragments': sum(s['candidate']['false_positive_runs'] for s in pools) < sum(s['baseline']['false_positive_runs'] for s in pools),
        'false_fragment_reduction_in_at_least_two_periods': sum(s['candidate']['false_positive_runs'] < s['baseline']['false_positive_runs'] for s in scopes) >= 2,
    }
    v8_met = all(v8.values())
    original_met = all(v['retention_and_false_alarm_objective_met'] for v in original.values())
    return {'exact_historical_event_retention_met': retained,
            'original_comparator_objective_facts': original, 'historical_retention': history,
            'v8_improvement_checks': v8, 'user_v8_improvement_objective_met': v8_met,
            'original_if_v6_retention_and_false_alarm_objective_met': original_met,
            'current_user_retention_and_false_alarm_goal_met': bool(retained and original_met and v8_met)}


def verify_independent_objectives(audit,objectives):
    """Cross-check independently recomputed history, separate from IF/V6."""
    summary=audit.get('historical_comparisons',{}).get('summary',{})
    expected={v.lower():item['all_periods_and_pools_retain_event_ids']
              for v,item in objectives['historical_retention'].items()}
    if summary.get('historical_event_retention_by_version')!=expected:
        raise ValueError('Independent historical event-ID retention disagrees')
    if summary.get('all_historical_event_ids_retained') is not all(expected.values()):
        raise ValueError('Independent historical retention summary disagrees')
    if summary.get('passes_v8_user_objective') is not objectives['user_v8_improvement_objective_met']:
        raise ValueError('Independent V8 user objective disagrees')
    mapping={
        'every_period_and_pool_preserves_v8_event_ids':'all_periods_and_pools_retain_original_event_ids',
        'every_period_and_pool_availability_equal':'all_periods_and_pools_keep_availability',
        'every_period_and_pool_extra_delay_within120':'all_paired_event_delays_at_most120s',
        'every_period_and_pool_fp_runs_nonincreasing':'no_scope_increases_false_fragments',
        'every_period_and_pool_fp_duration_nonincreasing':'no_scope_increases_false_duration',
        'strictly_fewer_pooled_false_runs':'strictly_fewer_pooled_false_fragments',
        'false_run_reduction_in_at_least_two_periods':'false_fragment_reduction_in_at_least_two_periods',
    }
    checks=summary.get('v8_user_objective_checks',{})
    if checks.get('all19_periods_and_source_pools_evaluated') is not True or any(
        checks.get(a) is not objectives['v8_improvement_checks'][b] for a,b in mapping.items()):
        raise ValueError('Independent V8 objective checks disagree')


def software_evidence(destination):
    """Prepare a byte-identical portable software proof, without publishing it."""
    source=ROOT/'output/mawrid-system/verification-v3.json'
    payload=source.read_bytes()
    json.loads(payload)  # Copy bytes unchanged; reject a non-JSON error response.
    bundled=destination.parent/'evidence/verification-v3.json'
    if not bundled.resolve().is_relative_to(destination.parent.resolve()):
        raise ValueError('Bundled software evidence must remain within the report directory')
    if bundled.exists() and bundled.read_bytes()!=payload:
        raise FileExistsError('Preserve differing bundled software evidence before regeneration')
    return payload,{'source':str(source),'bundled_path':str(bundled),
        'sha256':hashlib.sha256(payload).hexdigest(),
        'scope':'Earlier local V9 research lab and rule-based virtual SCADA twin only; no V14 inference, model acceptance or 3D qualification.'}


def render(run,destination,result,audit_path,audit,historical,folders,diagnosis_path,d,*,software_verification,design):
    summary=result['summary'];strong=all(summary[p]['passes_declared_development_gate'] for p in PAIRS)
    objectives=user_objectives(result,d)
    verify_independent_objectives(audit,objectives)
    facts=objectives['original_comparator_objective_facts'];history=objectives['historical_retention']
    current_goal=objectives['current_user_retention_and_false_alarm_goal_met']
    heading=('V14: تحسن تطويري يحتاج تحققًا خارجيًا جديدًا' if strong and current_goal else
        'V14 حققت الاحتفاظ وتقليل الإنذارات؛ بوابة زيادة الاكتشاف لم تجتز' if current_goal else
        'V14 لم تحقق هدف تقليل الإنذارات دون فقد أحداث')
    paired={p['case']:p for p in d['cross_run_period_comparison']};policies={p['case']:p for p in d['policy_evidence_by_period']}
    historical_periods={v:{p['case']:p for p in value['periods']} for v,value in historical.items()}
    aggregate=[summary['if_vs_v7']['baseline'],summary['v6_vs_v7']['baseline'],
        *[historical[v]['summary']['v6_vs_v7']['candidate'] for v in HISTORICAL],summary['v6_vs_v7']['candidate']]
    for value in historical.values():
        for pair in PAIRS:
            if value['summary'][pair]['baseline']!=summary[pair]['baseline']:raise ValueError('Historical IF/V6 metrics changed')
    period_rows=[];loss_rows=[];policy_rows=[];evidence_rows=[]
    for p in result['periods']:
        name=p['case'];a=p['comparisons']['if_vs_v7'];b=p['comparisons']['v6_vs_v7'];comps=[('IF',a),('V6',b)];ms=[a['baseline'],b['baseline']]
        for v in HISTORICAL:
            c=paired[name][v.lower()+'_vs_v14'];saved=historical_periods[v][name]['comparisons']['v6_vs_v7']['candidate']
            if c['baseline']!=saved or c['candidate']!=b['candidate']:raise ValueError('Period metric mismatch')
            ms.append(saved);comps.append((v,c))
        ms.append(b['candidate'])
        period_rows.append('<tr><th>'+ltr(name)+'</th><td>'+str(ms[-1]['true_events'])+'</td><td>'+across([m['confirmed_events'] for m in ms])+'</td><td>'+across([m['false_positive_runs'] for m in ms])+'</td><td>'+across([number(m['fp_duration_seconds']/60) for m in ms])+'</td><td>'+pct(ms[-1]['f1_observed_points'])+'</td><td>'+ltr(' | '.join(v+' '+str(c.get('noninferior_with_120s_limit',c.get('noninferior'))) for v,c in comps))+'</td></tr>')
        loss_rows.append('<tr><th>'+ltr(name)+'</th><td>'+comparison_text(comps,'lost_baseline_event_ids')+'</td><td>'+ltr(' | '.join(v+' '+number(maximum_delay(c))+' s' for v,c in comps))+'</td><td>'+comparison_text(comps,'lost_positive_alarm_rows')+'</td></tr>')
        s=p['selected'];q=policies[name]
        policy_rows.append('<tr><th>'+ltr(name)+'</th><td>'+ltr(s['status'])+'</td><td>'+ltr('low '+number(s['low_threshold'])+' | high '+number(s['high_threshold'])+' | '+number(s['confirmation_delay_seconds'])+' s | pending '+str(s['pending_after_clear']))+'</td><td>'+str(q['pending_grid_feasible_trials'])+' من '+str(q['pending_grid_trials'])+'</td><td>'+esc('؛ '.join(s['certification_rejection_reasons']) or '—')+'</td></tr>')
        evidence=audit['if_evidence_audit_by_case'][name];cov=p['conditional_block_test_coverage'];weighting=audit['sensor_tail_pulse_weighting_audit_by_case'][name]
        evidence_rows.append('<tr><th>'+ltr(name)+'</th><td>'+audit_count(evidence,'original_known_normal_training_windows')+'</td><td>'+audit_count(evidence,'observed_if_rows')+' من '+audit_count(evidence,'rows')+'</td><td>'+str(evidence['prior_and_attached_fitted_states_identical'])+'</td><td>'+str(cov['observed_on_reference_available_rows'])+' من '+str(cov['reference_available_rows'])+'</td><td>'+number(weighting.get('q95'))+'</td><td>'+'مؤكدة '+audit_count(weighting,'confirmed_tail_pulses')+'؛ مبتورة '+audit_count(weighting,'censored_tail_episodes')+'</td><td>'+'أجزاء '+audit_count(weighting,'eligible_bonus_segments')+'؛ نبضات '+audit_count(weighting,'eligible_bonus_pulses')+'؛ صفوف '+audit_count(weighting,'eligible_bonus_rows')+'</td><td>'+esc('نعم' if weighting['bonus_redistributed_to_event_uniform'] else 'لا')+'</td><td>'+ltr('normal '+number(weighting.get('normal_weight_mass'))+' | point '+number(weighting.get('point_component_mass'))+' | event '+number(weighting.get('event_component_mass'))+' | pulse '+number(weighting.get('pulse_component_mass')))+'</td></tr>')
    sources=[]
    for source,scopes in result['sources'].items():
        comps=[('IF',scopes['if_vs_v7']),('V6',scopes['v6_vs_v7'])];ms=[c['baseline'] for _,c in comps]
        for v in HISTORICAL:
            c=d['cross_run_source_comparison'][source][v.lower()+'_vs_v14']
            if c['baseline']!=historical[v]['sources'][source]['v6_vs_v7']['candidate'] or c['candidate']!=scopes['v6_vs_v7']['candidate']:raise ValueError('Source metric mismatch')
            ms.append(c['baseline']);comps.append((v,c))
        ms.append(scopes['v6_vs_v7']['candidate'])
        sources.append('<h3>'+ltr(source)+'</h3><table>'+METRIC_HEAD+'<tbody>'+table_models(ms)+'</tbody></table><p>معرّفات مفقودة: '+comparison_text(comps,'lost_baseline_event_ids')+'؛ أقصى تأخير مقترن '+ltr(' | '.join(v+' '+number(maximum_delay(c))+' s' for v,c in comps))+'</p>')
    gates=''.join('<h3>'+label+'</h3><ul class="checks">'+''.join('<li class="'+('ok' if value else 'bad')+'">'+esc(key)+': '+str(value)+'</li>' for key,value in summary[pair]['checks'].items())+'</ul>' for pair,label in (('if_vs_v7','مقابل IF'),('v6_vs_v7','مقابل V6')))
    timing_rows=[]
    for event in d['timing_comparison']:
        states=[];scores=[];crossings=[]
        for v in (*[x.lower() for x in HISTORICAL],'v14'):
            t=event[v];states.append(v.upper()+' '+('detected' if t['confirmed_index'] is not None else 'missed'))
            scores.append(v.upper()+' low '+number(t['fixed_low_threshold'])+'; '+str([p['confidence_first_values_including_after_pulse'] for p in t['reference_pulses']]))
            crossings.append(v.upper()+' '+str([p['first_raw_confidence_crossing_seconds_before_event_end'] for p in t['reference_pulses']]))
        timing_rows.append('<tr><th>'+ltr(event['case'])+'</th><td>'+str(event['event_id'])+'</td><td>'+ltr(' | '.join(states))+'</td><td>'+ltr(' | '.join(scores))+'</td><td>'+ltr(' | '.join(crossings))+'</td></tr>')
    if not timing_rows:timing_rows.append('<tr><td colspan="5">لا تغير في معرّفات الكشف المقارنة ولا فقد مرجعي في هذه الفترات.</td></tr>')
    statuses=dict(Counter(p['selected']['status'] for p in result['periods']));pending=d['pending_selected_periods']
    current_loss={pair:{p['case']:p['comparisons'][pair]['lost_baseline_event_ids'] for p in result['periods'] if p['comparisons'][pair]['lost_baseline_event_ids']} for pair in PAIRS}
    maximum={pair:max((x['extra_delay_seconds'] for scope in [p['comparisons'] for p in result['periods']]+list(result['sources'].values()) for x in scope[pair]['paired_extra_delays']),default=None) for pair in PAIRS}
    historical_loss_html=''.join('<p>'+ltr(v)+': '+esc(json.dumps(item['lost_ids_by_period'],ensure_ascii=False))+'</p>' for v,item in history.items())
    noninferior=' | '.join(label+' '+str(sum(p['comparisons'][pair]['noninferior'] for p in result['periods']))+' من 19' for pair,label in (('if_vs_v7','IF'),('v6_vs_v7','V6')))
    phase=('development_pass_needs_fresh_validation' if strong and current_goal else 'retention_goal_met_strong_gate_failed' if current_goal else 'current_retention_goal_failed')
    status={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'candidate':'V14','run':str(run),'phase':phase,
        'complete_cases':19,'independent_replay_audit_passed':True,'historical_v8_v9_v10_v11_v12_v13_audits_passed':True,
        'passes_declared_development_gate':strong,'strong_gate_changed':False,'current_user_retention_and_false_alarm_goal_met':current_goal,
        'current_goal_definition':'All IF/V6/V8/V9/V10/V11/V12/V13 original event IDs retained in every period and source pool. Original IF/V6 objective unchanged. Separately, V8 availability exact, paired event delay<=120s, no FP fragment/duration increase in any period or source pool, strictly fewer pooled FP fragments, and FP fragment reduction in at least two periods. Original strong gate unchanged.',
        **objectives,'summary':summary,
        'historical_candidates':{v:historical[v]['summary']['v6_vs_v7']['candidate'] for v in HISTORICAL},
        'lost_events_by_period':current_loss,'maximum_paired_extra_delay_seconds':maximum,'policy_status_counts':statuses,'pending_selected_periods':pending,
        'experiment_refitted_hgb':True,'original_if_refitted':False,'added_feature_count':0,
        'statistical_base_version':'V12',
        'single_statistical_change':'Relative to V12, replace positive label-onset bonus0.25 with all-confirmed sensor-tail pulse bonus0.25, balanced by eligible segment then pulse then row. q95 is linear from all finite known-normal original training IF scores. Full-axis confirmed starts require previous finite below q95; offsets0,1,2 truncate at tail end without label reset or availability shift. Global no-support fallback moves0.25 to event-uniform mass. Normal0.5 remains uniform; positive point0.125/event0.125 remain. No original IF refit or new feature; HGB refitted.',
        'difference_from_v13':'V13 is a historical comparator. Its normal-tail5:1 emphasis is removed as V14 returns to the V12 uniform-normal recipe; positive label-onset emphasis is replaced.',
        'confidence_lag_cause_established':False,'pulse_tail_threshold_from_test':False,
        'if_evidence_audit_by_case':audit['if_evidence_audit_by_case'],'if_representation_cross_fitted':False,
        'sensor_tail_pulse_weighting_audit_by_case':audit['sensor_tail_pulse_weighting_audit_by_case'],
        'training_bonus_redistributed_periods':[name for name,item in audit['sensor_tail_pulse_weighting_audit_by_case'].items()
            if item['bonus_redistributed_to_event_uniform']],
        'independent_historical_objectives_crosschecked':True,'design_evidence':design,
        'fresh_external_validation_performed':False,'new_source_accepted':False,'deployment_approved':False,'three_d_connected':False,'v14_live_stream_tested':False,
        'prototype_scope':'V14 audit is batch only. Earlier prototype checks belong to other versions and limited prefixes; no all-period streaming or Raspberry Pi latency claim.',
        'numeric_context_limitation':'Prefix causality does not establish cropped pandas IF feature or persistent streaming score parity.',
        'software_verification_evidence':software_verification,
        'post_test_diagnosis':str(diagnosis_path),'cross_run_source_comparison':d['cross_run_source_comparison'],
        'artifact_hashes':{'results':sha(run/'results.json'),'plan':sha(run/'plan.json'),'audit':sha(audit_path),'diagnosis':sha(diagnosis_path),
            'software_verification_v3':software_verification['sha256'],
            'design_protocol':design['protocol']['sha256'],'training_support':design['training_support']['sha256'],
            **{v+'_results':sha(folder/'results.json') for v,folder in folders.items()}},'report':str(destination)}
    public=ROOT/'output/ml/gecco-v8-source-search/public_only_followup_v2.json'
    public_html=link(public,destination,'مراجعة المصادر العامة السابقة') if public.is_file() else 'لم يُستخدم مصدر جديد'
    archive=' · '.join(link(ROOT/f'output/ml/gecco-{v.lower()}/report.html',destination,'تقرير '+v) for v in HISTORICAL)
    design_html=(link(Path(design['protocol']['path']),destination,'البروتوكول المثبت قبل التشغيل')+' · '+
        link(Path(design['training_support']['path']),destination,'قياس دعم التدريب الوصفي وبصمات مدخلاته'))
    prototype_html=('برنامج مورد المحلي له دليل هندسي منفصل: مختبر بيانات عامة يستخدم V9 وتوأم SCADA افتراضي تحميه قواعد تشغيل. '
        'دليل verification-v3 لا يؤهل نموذج V14 ولا يثبت بثه أو ربطه بالـ3D. '+link(Path(software_verification['bundled_path']),destination,'نطاق التحقق الهندسي السابق verification-v3'))
    doc=f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — V14</title><style>body{{margin:0;background:#eff4f4;color:#17323a;font:17px/1.8 system-ui,sans-serif}}main{{max-width:1800px;margin:auto;padding:24px}}header{{padding:26px;background:#08444d;color:white;border-radius:15px}}section{{background:white;margin:20px 0;padding:22px;border-radius:14px;overflow:auto}}.notice{{padding:18px;background:#fff1d6;border-right:5px solid #b77b14;margin:20px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;border-bottom:1px solid #d9e4e4;text-align:right;vertical-align:top;white-space:nowrap}}thead{{background:#e8f1f2}}.ltr{{direction:ltr;unicode-bidi:isolate;display:inline-block}}.checks{{direction:ltr;text-align:left;font:14px/1.8 monospace}}.ok{{color:#176346}}.bad{{color:#aa3028}}a{{color:#08717a}}summary{{cursor:pointer;font-weight:bold}}</style><main>
<header><h1>{heading}</h1><p>19 فترة مكتملة، مع تدقيق مستقل مطابق. لم يُربط V14 بالـ3D أو بالصمام.</p></header>
<div class="notice">جميع المصادر سبق كشفها في التطوير؛ هذا ليس تحققًا خارجيًا جديدًا. اجتياز التدقيق يعني مطابقة التنفيذ والحساب، ولا يعني أن النموذج نجح في الهدف.</div>
<section><h2>النتيجة على المحور نفسه</h2><table>{METRIC_HEAD}<tbody>{table_models(aggregate)}</tbody></table><p>الفترات غير المتراجعة أمام المرجعين الأصليين: {ltr(noninferior)}. يحتفظ الجدول بالفترات التي رجعت إلى V6 كما هي.</p></section>
<section><h2>الاحتفاظ بالأحداث وبوابات التحسن</h2><p>الاحتفاظ بمعرّفات IF وV6 واتحادها مع V8 وكل الإصدارات حتى V13: {ltr(objectives["exact_historical_event_retention_met"])}. الهدف الكامل للمستخدم: {ltr(current_goal)}.</p><p>هدف V8 المنفصل: {ltr(objectives["user_v8_improvement_objective_met"])}؛ لا زيادة في المقاطع الكاذبة أو مدتها في أي فترة أو مصدر متصل، مع خفض المقاطع المجمعة فعلًا وخفض المقاطع في فترتين على الأقل وتطابق الإتاحة وحد التأخير المقترن 120 ثانية.</p><ul class="checks">{"".join("<li>"+esc(k)+": "+str(v)+"</li>" for k,v in objectives["v8_improvement_checks"].items())}</ul><p>بوابة التطوير الأصلية أمام IF/V6: {ltr(strong)}؛ تتطلب أيضًا زيادة الاكتشاف عبر أكثر من فترة. لم تتغير البوابة ولم تُستبدل بهدف V8 أو بالاحتفاظ فقط.</p><p>الفقد مقابل IF/V6: {esc(json.dumps(current_loss,ensure_ascii=False))}. الفقد مقابل كل إصدار لاحق:</p>{historical_loss_html}{gates}</section>
<section><h2>التغيير الوحيد مقارنةً بـV12: موضع مكافأة الأحداث</h2><p>لم تُضف سمات جديدة. بقيت كتلة الطبيعي 0.5 موزعة بالتساوي، وكتلتا الموجب 0.125 للصفوف و0.125 للأجزاء الموجبة. استُبدلت مكافأة بداية الحدث الموسومة 0.25 بمكافأة حول <strong>جميع نبضات ذيل IF المؤكدة</strong>: بالتساوي على الأجزاء الموجبة ذات الدليل المؤهل، ثم النبضات داخل كل جزء، ثم الصفوف المؤهلة داخل نافذة كل نبضة.</p><p>تُحسب q95 بطريقة linear من جميع درجات IF المحدودة للصفوف الطبيعية المعروفة في التدريب فقط، بما فيها غير المؤهلة لـHGB. يبدأ الذيل عند درجة تساوي العتبة أو تتجاوزها؛ بداية مؤكدة تتطلب الصف السابق مباشرةً محدودًا وأقل منها. أول السلسلة وما بعد فقد الدرجة لا يُمنحان مكافأة بداية. تُحدد النبضات على المحور الأصلي دون إعادة بدء عند حدود الوسوم. النافذة هي الإزاحات 0 و1 و2 فقط، وتنتهي عند انتهاء النبضة؛ لا تتحرك إذا غابت قراءة أو سمة. عند غياب أي نافذة مؤهلة عالميًا، تُضاف 0.25 إلى كتلة الأجزاء بالتساوي لتصبح 0.375؛ وزن unknown صفر.</p><p>أُعيد تدريب HGB على الماضي، مع بقاء IF الأصلي والسمات والمراجع وRidge وإعدادات HGB والإتاحة وسياسة V10 ثابتة. درجة IF التدريبية داخل العينة وليست cross-fitted. V13 مقارنة تاريخية؛ أوزانه الإضافية للطبيعي لا تنتقل إلى V14. هذه فرضية لمحاذاة التدريب مع دليل الحساس، وليست سببًا مثبتًا لتأخر الثقة أو ضمانًا لعلاجه. ثلاث عينات تدريبية لا تعني ضمان استجابة خلال 120 ثانية، ودرجة HGB ليست احتمال سلامة معايرًا.</p><p>{design_html}</p><p>قياس الدعم وصفي من تدريب V13 المجمد فقط؛ لا يختار أوزانًا أو نوافذ بديلة. صفوف ذيل IF ليست نبضات V6 المعايرة نفسها. بيانات التدريب المتوسعة متداخلة، فلا تُجمع كأمثلة مستقلة.</p></section>
<section><h2>كل الفترات</h2><table><thead><tr><th>الفترة</th><th>الأحداث الحقيقية</th><th>الأحداث المكتشفة</th><th>المقاطع الكاذبة</th><th>الدقائق الكاذبة</th><th>F1 لـV14</th><th>عدم التراجع أمام كل إصدار</th></tr></thead><tbody>{''.join(period_rows)}</tbody></table></section>
<section><h2>المعرّفات المفقودة والتأخير الفعلي</h2><p>الحدث المفقود لا يدخل التأخير المقترن؛ لذلك لا يخفي التأخير الصفري فقد حدث. الحد المقبول للمقارنة 120 ثانية. القراءات الموجبة المحذوفة تكلفة وصفية، وليست شرطًا جديدًا بعد السماح بالتأكيد.</p><table><thead><tr><th>الفترة</th><th>معرّفات مفقودة</th><th>أقصى تأخير إضافي</th><th>قراءات موجبة أزيلت</th></tr></thead><tbody>{''.join(loss_rows)}</tbody></table></section>
<section><h2>المصادر على محور متصل</h2><p>تُجمع الصفوف أولًا قبل حساب الحدث؛ لا يتكرر حدث يعبر حدود الفترات. يتطلب معيار الكشف الأساسي انتقال سكون إلى إنذار داخل جزء موجب معلوم البداية. تغطية دقائق أكثر ومقياس F1 لا يحلان محل معرّفات الأحداث.</p>{''.join(sources)}</section>
<section><h2>الشهادة والرجوع إلى المرجع</h2><p>تختار أول كتلتين وصفة واحدة. تفحص الكتلتان اللاحقتان الوصفة نفسها دون إعادة اختيار، ثم تفحص الكتل الأربع على محورها الأصلي. يلزم حفظ النبضات الموجبة ومعرّفات الأحداث والإتاحة والتأخير وكلفة الإنذارات. الشهادة مشروطة بـV6 الذي اختير أصلًا بالكتل الأربع، وليست تحققًا مستقلًا للمنظومة كاملة.</p><p>إذا اختير pending، يحتفظ بموعد النبضة الأصلي ≤120 ثانية، ويحتاج عبورًا فعليًا للثقة بعد زوالها؛ لا يجبر تنبيهًا بعد زوالها. إضافات pending وrescue لا يجوز أن تضيف صفوفًا طبيعية في معايرة الماضي، وتحتاج دعم أحداث عبر كتلتين. عدد الفترات التي اختارت pending: {len(pending)}؛ {ltr(str(pending))}.</p><p>{esc(json.dumps(statuses,ensure_ascii=False))}</p><details><summary>جميع الوصفات وأسباب الرجوع</summary><table><thead><tr><th>الفترة</th><th>الحالة</th><th>الوصفة</th><th>pending المجتازة من المجربة مبكرًا</th><th>أسباب الرفض</th></tr></thead><tbody>{''.join(policy_rows)}</tbody></table></details></section>
<section><h2>تشخيص وصفي بعد الاختبار</h2><p>قد تتغير درجات HGB والعتبات المختارة في V14 لأنه نموذج أعيد تدريبه بمكافأة موجبة عند نبضات الحساس. يقارن التشخيص V12 كأساس إحصائي وV13 كمحاولة سابقة، إلى جانب كل الإصدارات الأقدم. الجدول يعرض الدرجات والقرارات الفعلية، ولا يجرب عتبة بديلة. ارتفاع الدرجة الخام وحده لا يثبت تحسن الفصل عن الطبيعي. يعرض الملف المرفق أيضًا توزيعات الدرجات الطبيعية والموجبة والمجهولة لكل فترة.</p><details><summary>تفاصيل الأحداث التي اختلف كشفها</summary><table><thead><tr><th>الفترة</th><th>الحدث</th><th>الكشف</th><th>العتبات وأول خمس درجات عند النبضات</th><th>زمن أول عبور للعتبة بالثواني</th></tr></thead><tbody>{''.join(timing_rows)}</tbody></table></details><p>{link(diagnosis_path,destination,'التشخيص الكامل وبصمات كل المقارنات')}</p></section>
<section><h2>دليل IF والأوزان والخصائص الشرطية</h2><p>عمود درجة IF أدناه يخص <strong>صفوف التدريب</strong> التي أعاد المدقق حسابها، وليس تغطية الاختبار. عمود الخصائص الشرطية يخص صفوف الاختبار المتاحة للمرجع؛ كلاهما وصف للدليل، ولا يغير مقام الأحداث.</p><table><thead><tr><th>الفترة</th><th>نوافذ تدريب IF الطبيعية الأصلية</th><th>درجة IF المتوفرة في صفوف التدريب</th><th>حالة IF مطابقة للأصل</th><th>الخصائص الشرطية في الاختبار</th><th>q95 التدريبية</th><th>نبضات مؤكدة ومبتورة البداية</th><th>أجزاء ونبضات وصفوف المكافأة</th><th>أعيدت المكافأة للأجزاء بالتساوي</th><th>كتل الأوزان</th></tr></thead><tbody>{''.join(evidence_rows)}</tbody></table></section>
<section><h2>التدقيق وجاهزية البرنامج</h2><p>أُعيد فحص {audit_count(audit,'replayed_rows')} صف اختبار و{audit_count(audit,'calibration_sensor_rows_replayed')} صف معايرة. شمل التدقيق السمات والمراجع وq95 التدريبية ونبضات الذيل ونوافذها وتوازن مكافأة الأحداث وعودة الطبيعي المتساوي وIF المجمد والقرار وشهادة النبضات ومقاييس المحاور الأصلية. {link(audit_path,destination,'تدقيق V14 المطابق')}.</p><p>تعتمد سمات IF على الحالة العددية لـpandas في كامل البادئة المعطاة. السببية لا تثبت أن قص التاريخ يعطي درجات مطابقة، ولا تثبت مطابقة البث المستمر.</p><p>{prototype_html}</p><p><strong>V14 مُدقّق على دفعات فقط؛ لا ادعاء باختبار بث جميع الفترات أو قياس زمن Raspberry Pi.</strong> جاهزية برنامج أولي لا تعني قبول النموذج إحصائيًا.</p></section>
<section><h2>الحدود والأرشيف</h2><p>{public_html}. لم يُقبل مصدر قياسات جديد في هذه المحاولة. لا تثبت النتائج تصنيف الأعطال الخمسة أو ملاءمة مياه الوضوء أو سلامة مياه بعينها. لا صلاحية لفتح الصمام.</p><p>{link(run/'plan.json',destination,'الخطة المثبتة')} · {link(run/'results.json',destination,'النتائج الكاملة')} · {archive}</p></section><footer>{ltr(result['completed_at_utc'])} · جميع المحاولات السابقة محفوظة.</footer></main></html>'''
    return doc,status


def build(run,destination,*,historical_runs=None,status_path=None):
    run,destination=Path(run).resolve(),Path(destination).resolve()
    supplied=historical_runs or {}
    folders={'v14':run,**{v.lower():Path(supplied.get(v.lower(),ROOT/f'output/ml/gecco-{v.lower()}-development/run_01')).resolve() for v in HISTORICAL}}
    result,audit_path,audit,historical=load_verified(run,folders)
    diagnosis_path,d=load_diagnosis(run,folders,result)
    status_path=Path(status_path).resolve() if status_path else destination.parent/'status.json';allowed=ROOT/'output/ml/gecco-v14'
    if not destination.is_relative_to(allowed) or not status_path.is_relative_to(allowed) or destination==status_path:raise ValueError('Only new V14 report outputs allowed')
    if destination.exists() or status_path.exists():raise FileExistsError('Preserve previous report/status before explicit regeneration')
    payload,software_verification=software_evidence(destination)
    design=design_evidence()
    doc,status=render(run,destination,result,audit_path,audit,historical,folders,diagnosis_path,d,software_verification=software_verification,design=design)
    bundled=Path(software_verification['bundled_path']);bundled.parent.mkdir(parents=True,exist_ok=True)
    if not bundled.exists():
        with bundled.open('xb') as f:f.write(payload)
    if sha(bundled)!=software_verification['sha256']:raise ValueError('Bundled software proof changed')
    destination.parent.mkdir(parents=True,exist_ok=True);status_path.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x') as f:f.write(doc)
    with status_path.open('x') as f:json.dump(status,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
    return status


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for v in HISTORICAL:p.add_argument('--'+v.lower(),type=Path)
    a=p.parse_args();s=build(a.run,a.output,historical_runs={v.lower():getattr(a,v.lower()) for v in HISTORICAL if getattr(a,v.lower()) is not None})
    print(json.dumps({'report':s['report'],'phase':s['phase'],'strong_gate':s['passes_declared_development_gate'],'current_goal':s['current_user_retention_and_false_alarm_goal_met']}))


if __name__=='__main__':main()
