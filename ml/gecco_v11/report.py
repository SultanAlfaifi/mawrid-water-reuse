"""Six-model V11 report gated on complete results, matching audits and axes."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
from ml.gecco_v8.report import EXPECTED_NAMES,PAIRS,METRIC_HEAD,audit_count,esc,link,ltr,maximum_delay,metric_row,number,pct,read,sha,load_verified as load_v8_verified
from ml.gecco_v10.report import load_verified as load_v10_verified,objective_facts,prototype_evidence

ROOT=Path(__file__).resolve().parents[2]
MODELS=('IF','V6','V8','V9','V10','V11')


def load_verified(run,parent,previous,earlier):
    result,plan=read(run/'results.json'),read(run/'plan.json')
    if (result.get('candidate_version')!='V11' or result.get('complete_cases')!=19 or result.get('expected_cases')!=19
        or result.get('all_prespecified_cases_complete') is not True or not result.get('completed_at_utc')
        or [p.get('case') for p in result.get('periods',[])]!=EXPECTED_NAMES or (run/'failed_case.json').exists()
        or result.get('development_only') is not True or result.get('fresh_validation') is not False
        or result.get('model_refitted') is not False or result.get('maximum_allowed_extra_delay_seconds')!=120
        or plan.get('scope')!='all' or plan.get('limit_cases')!=19 or plan.get('attempt')!='v11_run01_preserve_retained_if_pulses'):
        raise ValueError('All19 unchanged V11 disclosed-development results required')
    audit_path=next((run/n for n in ('audit.json','replay_audit.json') if (run/n).is_file()),None)
    if audit_path is None:raise ValueError('Awaiting V11 independent audit')
    audit=read(audit_path)
    if (audit.get('passed') is not True or audit.get('failed_checks')!=0 or audit.get('complete_replayed_cases')!=19
        or audit.get('audit_version')!='v11_retained_if_full_raw_sensor_replay_v1' or audit.get('attempt')!=plan['attempt']
        or audit.get('hashes',{}).get('results.json')!=sha(run/'results.json') or audit.get('hashes',{}).get('plan.json')!=sha(run/'plan.json')):
        raise ValueError('Exact all19 passing V11 audit required')
    if (ROOT/plan['parent_run']).resolve()!=parent:raise ValueError('V10 parent mismatch')
    v10,parent_audit_path,parent_audit,v9,_,_=load_v10_verified(parent,previous)
    v8,_,_=load_v8_verified(earlier)
    for name in ('plan.json','results.json','audit.json'):
        digest=sha(parent/name)
        if plan['parent_sha256'].get(name)!=digest or audit['hashes'].get('parent/'+name)!=digest:raise ValueError('Passing V10 parent lineage mismatch')
    protected=audit.get('retained_if_protection_by_case',{})
    if set(protected)!=set(EXPECTED_NAMES):raise ValueError('Independent protection accounting requires all19 cases')
    for item in protected.values():
        if item['protected_rows_withheld_by_unextended_seed']!=0 or item['unextended_seed_alarm_rows_outside_reference_alarm']!=0:raise ValueError('Independent protected-seed invariants failed')
    return result,audit_path,audit,{'V8':v8,'V9':v9,'V10':v10}


def load_diagnosis(run,folders,result):
    path=run/'post_test_diagnosis.json';d=read(path)
    if (d.get('candidate_version')!='V11' or d.get('cross_run_axis_verified') is not True or d.get('v9_v10_scores_exactly_unchanged') is not True
        or any(d.get(k) is not False for k in ('fresh_validation','new_source_accessed','model_refitted','thresholds_changed','policies_reexecuted_for_diagnosis'))):raise ValueError('Unchanged same-axis V11 diagnosis required')
    for version,folder in folders.items():
        if Path(d['comparison_runs'][version]).resolve()!=folder or d['cross_run_input_sha256'].get(str(folder/'results.json'))!=sha(folder/'results.json'):raise ValueError('Diagnosis run identity changed')
    for relative,digest in d['input_sha256'].items():
        if sha(run/relative)!=digest:raise ValueError('Diagnosis input changed')
    for absolute,digest in d['cross_run_input_sha256'].items():
        if sha(Path(absolute))!=digest:raise ValueError('Cross-run input changed')
    for key in ('cross_run_period_comparison','policy_evidence_by_period','protection_by_period','conditional_coverage_by_period'):
        if [p['case'] for p in d[key]]!=EXPECTED_NAMES:raise ValueError('Missing or reordered diagnostic periods')
    if set(d['cross_run_source_comparison'])!=set(result['sources']):raise ValueError('Missing connected source axis')
    return path,d


def across(values):return ltr(' | '.join(name+' '+str(value) for name,value in zip(MODELS,values)))
def table_models(metrics):return ''.join(metric_row(name,metric) for name,metric in zip(MODELS,metrics))
def comparison_text(comps,key):return ltr(' | '.join(name+' '+str(comp[key]) for name,comp in comps))


def historical_retention(result,diagnosis):
    out={}
    for version in ('v8','v9','v10'):
        scopes=[p[version+'_vs_v11'] for p in diagnosis['cross_run_period_comparison']]+[s[version+'_vs_v11'] for s in diagnosis['cross_run_source_comparison'].values()]
        out[version.upper()]={'all_periods_and_pools_retain_event_ids':all(not c['lost_baseline_event_ids'] for c in scopes),
            'all_periods_and_pools_noninferior_with120s':all(c['noninferior_with_120s_limit'] for c in scopes),
            'lost_ids_by_period':{p['case']:p[version+'_vs_v11']['lost_baseline_event_ids'] for p in diagnosis['cross_run_period_comparison'] if p[version+'_vs_v11']['lost_baseline_event_ids']},
            'lost_ids_by_source':{name:c[version+'_vs_v11']['lost_baseline_event_ids'] for name,c in diagnosis['cross_run_source_comparison'].items() if c[version+'_vs_v11']['lost_baseline_event_ids']}}
    return out


def outcome_evidence(run,destination):
    path=run/'policy_outcome_followup.json'
    if not path.is_file():return '',None
    d=read(path)
    if (d.get('candidate_version')!='V11' or d.get('status')!='post_test_saved_grid_and_row_equality_only'
        or any(d.get(key) is not False for key in ('new_source_accessed','model_refitted','thresholds_changed','policy_reexecuted'))
        or d.get('input_sha256',{}).get(str(run/'results.json'))!=sha(run/'results.json')
        or [p['case'] for p in d.get('cases',[])]!=EXPECTED_NAMES):raise ValueError('Outcome follow-up must match the unchanged all19 V11 run')
    for absolute,digest in d['input_sha256'].items():
        if sha(Path(absolute))!=digest:raise ValueError('Outcome follow-up input changed')
    rows=[]
    for p in d['cases']:
        ref=p['early_reference']
        rows.append('<tr><th>'+ltr(p['case'])+'</th><td>'+str(p['candidate_reference_row_mismatches'])+'</td><td>'+ltr(str(ref['fp'])+' / '+str(ref['false_runs']))+'</td><td>'+str(p['early_feasible_confirmation_trials'])+'</td><td>'+ltr(number(p['minimum_feasible_confirmation_false_rows'])+' / '+number(p['minimum_feasible_confirmation_false_fragments']))+'</td><td>'+str(p['early_known_normal_reference_alarm_rows_protected_by_if'])+' من '+str(p['early_known_normal_reference_alarm_rows'])+'</td></tr>')
    html=('<h3>هل تغير القرار فعلًا؟</h3><p>عدد صفوف V11 المخالفة لـV6 في الفترات التسع عشرة: '+str(d['total_candidate_reference_row_mismatches'])+'. يشمل هذا الإنذار والسكون وعدم الإتاحة. فترات التأكيد النشط: '+ltr(str(d['active_confirmation_periods']))+'. الجدول يصف شبكة الماضي المحفوظة؛ لا يختار عتبة بعد الاختبار. عند تعادل المرشحين في المقاييس يفضل الترتيب الثابت المسار الأبسط.</p><table><thead><tr><th>الفترة</th><th>اختلاف صفوف الاختبار عن V6</th><th>الماضي: صفوف/مقاطع كاذبة للمرجع</th><th>وصفات تأكيد مجتازة مبكرًا</th><th>أقل صفوف/مقاطع كاذبة بينها</th><th>صفوف المرجع الطبيعية المحمية بـIF</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table><p>'+link(path,destination,'تفصيل الاختيار وتطابق الصفوف وبصماته')+'</p>')
    return html,{'path':str(path),'sha256':sha(path),'total_candidate_reference_row_mismatches':d['total_candidate_reference_row_mismatches'],'active_confirmation_periods':d['active_confirmation_periods']}


def render(run,destination,result,audit_path,audit,historical,folders,diagnosis_path,d):
    summary=result['summary'];strong=all(summary[p]['passes_declared_development_gate'] for p in PAIRS)
    facts=objective_facts(result);history=historical_retention(result,d)
    historical_ids=all(item['all_periods_and_pools_retain_event_ids'] for item in history.values())
    current_goal=historical_ids and all(facts[p]['retention_and_false_alarm_objective_met'] for p in PAIRS)
    # This narrower factual conjunction is explicit; the original strong gate
    # remains unchanged and is never replaced by this user-objective status.
    heading='V11: نتيجة تطوير تحتاج تحققًا خارجيًا جديدًا'
    if not current_goal:heading='V11 لم تحقق هدف تقليل الإنذارات دون فقد أحداث'
    elif not strong:heading='V11 حققت الاحتفاظ وتقليل الإنذارات؛ بوابة زيادة الاكتشاف لم تجتز'
    pairs={p['case']:p for p in d['cross_run_period_comparison']};policies={p['case']:p for p in d['policy_evidence_by_period']}
    historical_periods={version:{p['case']:p for p in value['periods']} for version,value in historical.items()}
    aggregate=[summary['if_vs_v7']['baseline'],summary['v6_vs_v7']['baseline'],*[historical[v]['summary']['v6_vs_v7']['candidate'] for v in ('V8','V9','V10')],summary['v6_vs_v7']['candidate']]
    for version,value in historical.items():
        for pair in PAIRS:
            if value['summary'][pair]['baseline']!=summary[pair]['baseline']:raise ValueError('Historical baseline changed')
    period_rows=[];loss_rows=[];policy_rows=[];protection=[];coverage=[]
    for p in result['periods']:
        name=p['case'];a=p['comparisons']['if_vs_v7'];b=p['comparisons']['v6_vs_v7'];comps=[('IF',a),('V6',b)];ms=[a['baseline'],b['baseline']]
        for version in ('V8','V9','V10'):
            c=pairs[name][version.lower()+'_vs_v11'];saved=historical_periods[version][name]['comparisons']['v6_vs_v7']['candidate']
            if c['baseline']!=saved or c['candidate']!=b['candidate']:raise ValueError('Period metric mismatch')
            ms.append(saved);comps.append((version,c))
        ms.append(b['candidate'])
        period_rows.append('<tr><th>'+ltr(name)+'</th><td>'+str(ms[-1]['true_events'])+'</td><td>'+across([m['confirmed_events'] for m in ms])+'</td><td>'+across([m['false_positive_runs'] for m in ms])+'</td><td>'+across([number(m['fp_duration_seconds']/60) for m in ms])+'</td><td>'+pct(ms[-1]['f1_observed_points'])+'</td><td>'+ltr(' | '.join(v+' '+str(c.get('noninferior_with_120s_limit',c.get('noninferior'))) for v,c in comps))+'</td></tr>')
        loss_rows.append('<tr><th>'+ltr(name)+'</th><td>'+comparison_text(comps,'lost_baseline_event_ids')+'</td><td>'+ltr(' | '.join(v+' '+number(maximum_delay(c))+' s' for v,c in comps))+'</td><td>'+comparison_text(comps,'lost_positive_alarm_rows')+'</td></tr>')
        s=p['selected'];q=policies[name]
        if s.get('retained_if_protection') is not True:raise ValueError('Selected protection tag missing')
        policy_rows.append('<tr><th>'+ltr(name)+'</th><td>'+ltr(s['status'])+'</td><td>'+ltr('low '+number(s['low_threshold'])+' | high '+number(s['high_threshold'])+' | '+number(s['confirmation_delay_seconds'])+' s | pending '+str(s['pending_after_clear']))+'</td><td>'+ltr(str(q['pending_grid_feasible_trials'])+' / '+str(q['pending_grid_trials']))+'</td><td>'+esc('؛ '.join(s['certification_rejection_reasons']) or '—')+'</td></tr>')
        ap=audit['retained_if_protection_by_case'][name];observed=next(x['test'] for x in d['protection_by_period'] if x['case']==name)
        if ap['retained_if_protected_rows']!=observed['retained_if_trigger_rows'] or ap['final_alarm_rows_on_if_one_reference_zero']!=observed['final_alarm_on_v6_removed_if_rows']:raise ValueError('Protection audit and saved masks disagree')
        protection.append('<tr><th>'+ltr(name)+'</th><td>'+str(ap['retained_if_protected_rows'])+'</td><td>'+str(ap['protected_rows_withheld_by_unextended_seed'])+'</td><td>'+str(ap['unextended_seed_alarm_rows_outside_reference_alarm'])+'</td><td>'+str(ap['pending_seed_alarm_rows_on_reference_zero'])+'</td><td>'+str(ap['final_alarm_rows_on_if_one_reference_zero'])+'</td></tr>')
        cov=p['conditional_block_test_coverage'];supported=audit.get('conditional_audit_by_case',{}).get(name,{}).get('supported')
        coverage.append('<tr><th>'+ltr(name)+'</th><td>'+('غير متاح' if supported is None else ('مدعوم' if supported else 'غير مدعوم'))+'</td><td>'+str(cov['observed_on_reference_available_rows'])+' من '+str(cov['reference_available_rows'])+'</td></tr>')
    sources=[]
    for source,scopes in result['sources'].items():
        comps=[('IF',scopes['if_vs_v7']),('V6',scopes['v6_vs_v7'])];ms=[comps[0][1]['baseline'],comps[1][1]['baseline']]
        for version in ('V8','V9','V10'):
            c=d['cross_run_source_comparison'][source][version.lower()+'_vs_v11']
            if c['baseline']!=historical[version]['sources'][source]['v6_vs_v7']['candidate'] or c['candidate']!=scopes['v6_vs_v7']['candidate']:raise ValueError('Source metric mismatch')
            ms.append(c['baseline']);comps.append((version,c))
        ms.append(scopes['v6_vs_v7']['candidate'])
        sources.append('<h3>'+ltr(source)+'</h3><table>'+METRIC_HEAD+'<tbody>'+table_models(ms)+'</tbody></table><p>معرّفات مفقودة: '+comparison_text(comps,'lost_baseline_event_ids')+'؛ أقصى تأخير مقترن '+ltr(' | '.join(v+' '+number(maximum_delay(c))+' s' for v,c in comps))+'</p>')
    gates=''.join('<h3>'+label+'</h3><ul class="checks">'+''.join('<li class="'+('ok' if value else 'bad')+'">'+esc(key)+': '+str(value)+'</li>' for key,value in summary[pair]['checks'].items())+'</ul>' for pair,label in (('if_vs_v7','مقابل IF'),('v6_vs_v7','مقابل V6')))
    timing_rows=[]
    for event in d['timing_comparison']:
        states=[];scores=[];baseline=[]
        for version in ('v8','v9','v10','v11'):
            t=event[version];states.append(version.upper()+' '+('detected' if t['confirmed_index'] is not None else 'missed'))
            scores.append(version.upper()+' low '+number(t['fixed_low_threshold'])+'; '+str([p['confidence_first_values_including_after_pulse'][0] for p in t['reference_pulses']]))
            baseline.append(version.upper()+' '+str([p['baseline_alarm_rows_inside_reference_pulse'] for p in t['reference_pulses']]))
        timing_rows.append('<tr><th>'+ltr(event['case'])+'</th><td>'+str(event['event_id'])+'</td><td>'+ltr(' | '.join(states))+'</td><td>'+ltr(' | '.join(scores))+'</td><td>'+ltr(' | '.join(baseline))+'</td></tr>')
    if not timing_rows:timing_rows.append('<tr><td colspan="5">لا تغير في معرّفات الكشف بين الإصدارات المقارنة ولا فقد مرجعي في هذه الفترات.</td></tr>')
    statuses=dict(Counter(p['selected']['status'] for p in result['periods']));pending=d['pending_selected_periods']
    prototype_html,prototype_artifacts=prototype_evidence(destination)
    outcome_html,outcome_info=outcome_evidence(run,destination)
    historical_loss_html=''.join('<p>'+ltr(v)+': '+esc(json.dumps(item['lost_ids_by_period'],ensure_ascii=False))+'</p>' for v,item in history.items())
    current_loss={pair:{p['case']:p['comparisons'][pair]['lost_baseline_event_ids'] for p in result['periods'] if p['comparisons'][pair]['lost_baseline_event_ids']} for pair in PAIRS}
    maximum={pair:max((x['extra_delay_seconds'] for scope in [p['comparisons'] for p in result['periods']]+list(result['sources'].values()) for x in scope[pair]['paired_extra_delays']),default=None) for pair in PAIRS}
    phase=('development_pass_needs_fresh_validation' if strong and current_goal else 'retention_goal_met_strong_gate_failed' if current_goal else 'current_retention_goal_failed')
    status={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'candidate':'V11','run':str(run),'phase':phase,
        'complete_cases':19,'independent_replay_audit_passed':True,'parent_v10_replay_audit_passed':True,
        'passes_declared_development_gate':strong,'strong_gate_changed':False,'current_user_retention_and_false_alarm_goal_met':current_goal,
        'current_goal_definition':'All IF/V6/V8/V9/V10 original event IDs retained in every period and source pool; original IF/V6 availability, <=120s paired delay, no false fragment/duration increase per scope and strictly fewer pooled false fragments. Historical false costs and delays also shown separately. Original strong gate is unchanged.',
        'original_comparator_objective_facts':facts,'historical_retention':history,'summary':summary,
        'historical_candidates':{v:historical[v]['summary']['v6_vs_v7']['candidate'] for v in historical},
        'lost_events_by_period':current_loss,'maximum_paired_extra_delay_seconds':maximum,
        'policy_status_counts':statuses,'pending_selected_periods':pending,'retained_if_protection_by_case':audit['retained_if_protection_by_case'],
        'fresh_external_validation_performed':False,'deployment_approved':False,'three_d_connected':False,'v11_live_stream_tested':False,
        'prototype_scope':'Prior V9 only: GECCO2019 first1600 prefix PASS, WaterHub score fidelity FAIL; no all-period or V11 stream validation.','prototype_artifacts':prototype_artifacts,
        'post_test_diagnosis':str(diagnosis_path),'policy_outcome_followup':outcome_info,'cross_run_source_comparison':d['cross_run_source_comparison'],
        'artifact_hashes':{'results':sha(run/'results.json'),'plan':sha(run/'plan.json'),'audit':sha(audit_path),'diagnosis':sha(diagnosis_path),'v10_audit':sha(folders['v10']/'audit.json'),**{v+'_results':sha(folder/'results.json') for v,folder in folders.items()}},'report':str(destination)}
    public=ROOT/'output/ml/gecco-v8-source-search/public_only_followup_v2.json';public_html=link(public,destination,'مراجعة المصادر العامة السابقة') if public.is_file() else 'لم يُستخدم مصدر جديد'
    doc=f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — V11</title><style>body{{margin:0;background:#eff4f4;color:#17323a;font:17px/1.8 system-ui,sans-serif}}main{{max-width:1700px;margin:auto;padding:24px}}header{{padding:26px;background:#08444d;color:white;border-radius:15px}}section{{background:white;margin:20px 0;padding:22px;border-radius:14px;overflow:auto}}.notice{{padding:18px;background:#fff1d6;border-right:5px solid #b77b14;margin:20px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;border-bottom:1px solid #d9e4e4;text-align:right;vertical-align:top;white-space:nowrap}}thead{{background:#e8f1f2}}.ltr{{direction:ltr;unicode-bidi:isolate;display:inline-block}}.checks{{direction:ltr;text-align:left;font:14px/1.8 monospace}}.ok{{color:#176346}}.bad{{color:#aa3028}}a{{color:#08717a}}summary{{cursor:pointer;font-weight:bold}}</style><main>
<header><h1>{heading}</h1><p>19 فترة مكتملة، مع تدقيق مستقل مطابق. لا ربط بالـ3D أو بالصمام.</p></header>
<div class="notice">بيانات تطوير سبق كشفها، وليست تحققًا خارجيًا جديدًا. التدريب والمعايرة يسبقان الاختبار داخل كل تقسيم، لكن تصميم هذه المحاولة استفاد من نتائج سابقة. اجتياز التدقيق يعني مطابقة الحسابات التي فُحصت، لا قبول النموذج إحصائيًا.</div>
<section><h2>المقارنة الفعلية للإصدارات الستة</h2><table>{METRIC_HEAD}<tbody>{table_models(aggregate)}</tbody></table><p>عدم التراجع أمام V6: {summary['v6_vs_v7']['noninferior_periods']} من 19؛ أمام IF: {summary['if_vs_v7']['noninferior_periods']} من 19. تشمل الجداول التالية V8 وV9 وV10 أيضًا. F1 مقياس للقراءات ولا يمثل احتمال سلامة المياه.</p></section>
<section><h2>هدف الاحتفاظ مقابل بوابة التطوير الأصلية</h2><p>تحقق اقتران حفظ كل المعرّفات السابقة مع شروط تقليل الإنذارات أمام IF وV6: {ltr(str(current_goal))}. يشمل فحص المعرّفات أحداث V8 الإضافية؛ لا نصف النتيجة بأنها «دون فقد» إذا بقي أي منها مفقودًا. جميع تكاليف الإصدارات السابقة والتأخيرات ظاهرة للمقارنة.</p><p>اجتياز البوابة الأصلية: {ltr(str(strong))}. لم نغيرها؛ تشترط فوق عدم التراجع زيادة الأحداث المجمعة، وتحسن الكشف في فترتين على الأقل، وانخفاض الإنذارات المجمعة وفي فترتين. لا يحل نجاح الاحتفاظ وحده محلها.</p>{gates}<h3>معرّفات فقدها V11 مقارنة بالإصدارات اللاحقة للمرجع</h3>{historical_loss_html}</section>
<section><h2>تغيير واحد في سياسة القرار</h2><p>تبقى نماذج V9 ودرجاتها الموروثة عبر V10 كما هي، دون إعادة تدريب. عندما ينبه IF ويكون V6 قد أبقى التنبيه في الصف نفسه، تُحرر حلقة التأكيد فورًا وتبقى نشطة حتى ينتهي إنذار V6. قد تصل الحماية أثناء الحلقة، ولا تعتمد على الدرجة الطويلة. لا تعيد الحماية تنبيه IF الذي حذفه V6، ولا تنبه حين يكون المرجع غير متاح.</p><p>تدخل الحماية قبل تقييم مرشحي أول كتلتين، ثم تخضع الوصفة المختارة نفسها لشهادة الكتلتين اللاحقتين وفحص الكتل الأربع دون إعادة اختيار. تبقى بوابات النبضات والأحداث والتأخير ≤120 ثانية والإتاحة وكلفة الإنذارات كما هي. الحلقة المحررة لا تصبح pending بعد زوالها. عدد الفترات التي اختارت pending فعليًا: {len(pending)}؛ {ltr(str(pending))}.</p><p>المحدد العملي: أخطاء IF التي أبقاها V6 تحظى بالحماية أيضًا؛ لذلك قد يقل مجال تخفيض الإنذارات. هذه شهادة للسياسة الإضافية مشروطة بمرجع اختير سابقًا بالكتل الأربع، وليست تحققًا مستقلاً للمنظومة كاملة.</p></section>
<section><h2>كل الفترات</h2><table><thead><tr><th>الفترة</th><th>الحقيقية</th><th>المكتشفة</th><th>المقاطع الكاذبة</th><th>الدقائق الكاذبة</th><th>F1 لـV11</th><th>عدم التراجع</th></tr></thead><tbody>{''.join(period_rows)}</tbody></table></section>
<section><h2>كل الفقد والتأخير الفعلي</h2><p>المعرّفات تخص محور الفترة. الحدث المفقود لا يدخل التأخير المقترن؛ الصفر في التأخير لا يخفي الفقد. القراءات الموجبة المحذوفة وصف للتكلفة، لا شرط قبول جديد بعد السماح بالتأكيد.</p><table><thead><tr><th>الفترة</th><th>معرّفات مفقودة من كل إصدار</th><th>أقصى تأخير إضافي مقترن</th><th>قراءات موجبة أزيلت</th></tr></thead><tbody>{''.join(loss_rows)}</tbody></table></section>
<section><h2>المصادر المتصلة</h2><p>تُجمع الصفوف على محور المصدر قبل الحساب حتى لا يتكرر حدث يعبر حدود الفترات. معيار الحدث الأساسي يتطلب انتقال سكون إلى إنذار داخل جزء موجب معلوم البداية؛ لا تعوضه تغطية دقائق إضافية.</p>{''.join(sources)}</section>
<section><h2>الحماية وإحياء الصفوف المحذوفة: مساران مختلفان</h2><p>يفحص المدقق المستقل التأكيد المحمي دون pending أو rescue (A0). يجب أن يكون عدد إنذاراته خارج reference=1 صفرًا. القرار المركب قد يضيف إنذارًا عبر pending أو rescue، فلا ننسبه للحماية لمجرد اتفاق IF معه. الجدول يفصل الحالتين.</p><table><thead><tr><th>الفترة</th><th>صفوف IF/V6 المحمية</th><th>حجبها A0</th><th>إنذارات A0 خارج إنذار المرجع</th><th>pending على مرجع ساكن</th><th>القرار النهائي: IF=1 وV6=0</th></tr></thead><tbody>{''.join(protection)}</tbody></table></section>
<section><h2>الاختيار والشهادة والرجوع</h2><p>{esc(json.dumps(statuses,ensure_ascii=False))}</p><details><summary>كل الوصفات وأسبابها</summary><table><thead><tr><th>الفترة</th><th>الحالة</th><th>الوصفة</th><th>pending المجتازة من المجربة مبكرًا</th><th>أسباب الرفض</th></tr></thead><tbody>{''.join(policy_rows)}</tbody></table></details></section>
<section><h2>تشخيص وصفي بعد الاختبار</h2><p>هذه مشاهدات من النتائج الثابتة، دون تجربة وصفة بديلة أو تغيير عتبة. درجات V9 وV10 وV11 متطابقة؛ تحسن القرار إن ظهر قد يأتي من الحماية أو الاختيار أو الرجوع، ولا يُنسب لتحسن الثقة. عدد إنذارات IF داخل كل نبضة موضح بجانب الدرجة.</p><table><thead><tr><th>الفترة</th><th>الحدث</th><th>الكشف</th><th>العتبات ودرجات بدايات النبضات</th><th>صفوف IF داخل النبضات المرجعية</th></tr></thead><tbody>{''.join(timing_rows)}</tbody></table><p>{link(diagnosis_path,destination,'التشخيص الكامل وبصمات المقارنة')}</p>{outcome_html}</section>
<section><h2>توفر الخصائص الموروثة</h2><p>الجزء الشرطي بين الحساسات وأوزان البدايات ثابتان. التغطية أدناه وصف لدليل إضافي، ولا تغير إتاحة المرجع أو مقام الأحداث. HGB مع إشراف وبواقي Ridge طبيعية نموذج هجين، ودرجته ليست احتمال سلامة معايرًا.</p><table><thead><tr><th>الفترة</th><th>دعم التدريب</th><th>صفوف الدليل من المرجع المتاح</th></tr></thead><tbody>{''.join(coverage)}</tbody></table></section>
<section><h2>التدقيق وجاهزية البرمجيات</h2><p>أُعيد فحص {audit_count(audit,'replayed_rows')} صف اختبار و{audit_count(audit,'calibration_sensor_rows_replayed')} صف معايرة، مع مطابقة النموذج الموروث ومسار القرار وشهادة النبضات ومقاييس المحاور الأصلية. {link(audit_path,destination,'تدقيق V11')} · {link(folders['v10']/'audit.json',destination,'تدقيق V10 الأصل')}.</p><p>{prototype_html}</p><p><strong>لم يُختبر V11 كبث حي.</strong> الاختبارات البرمجية السابقة لا تثبت زمن Raspberry Pi أو جاهزية ميدانية.</p></section>
<section><h2>حدود الاستنتاج والأرشيف</h2><p>{public_html}. لا قياسات من مصدر جديد في هذه المحاولة. لا تثبت النتائج تصنيف الأعطال الخمسة أو صلاحية مياه الوضوء أو سلامة مياه بعينها. لا صلاحية لفتح الصمام.</p><p>{link(run/'plan.json',destination,'الخطة المثبتة')} · {link(run/'results.json',destination,'النتائج الكاملة')} · {link(ROOT/'output/ml/gecco-v10/report.html',destination,'تقرير V10')} · {link(ROOT/'output/ml/gecco-v9/report.html',destination,'تقرير V9')} · {link(ROOT/'output/ml/gecco-v8/report.html',destination,'تقرير V8')}</p></section><footer>{ltr(result['completed_at_utc'])} · جميع المحاولات السابقة محفوظة.</footer></main></html>'''
    return doc,status


def build(run,destination,*,parent=None,previous=None,earlier=None,status_path=None):
    run,destination=Path(run).resolve(),Path(destination).resolve()
    folders={'v11':run,'v10':Path(parent).resolve() if parent else ROOT/'output/ml/gecco-v10-development/run_01',
        'v9':Path(previous).resolve() if previous else ROOT/'output/ml/gecco-v9-development/run_01',
        'v8':Path(earlier).resolve() if earlier else ROOT/'output/ml/gecco-v8-development/run_01'}
    result,audit_path,audit,historical=load_verified(run,folders['v10'],folders['v9'],folders['v8'])
    diagnosis_path,d=load_diagnosis(run,folders,result)
    doc,status=render(run,destination,result,audit_path,audit,historical,folders,diagnosis_path,d)
    status_path=Path(status_path).resolve() if status_path else destination.parent/'status.json';allowed=ROOT/'output/ml/gecco-v11'
    if not destination.is_relative_to(allowed) or not status_path.is_relative_to(allowed) or destination==status_path:raise ValueError('Only new V11 report outputs allowed')
    if destination.exists() or status_path.exists():raise FileExistsError('Preserve previous report/status before explicit regeneration')
    destination.parent.mkdir(parents=True,exist_ok=True);status_path.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(doc);status_path.write_text(json.dumps(status,indent=2,ensure_ascii=False,allow_nan=False)+'\n');return status


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for name in ('parent','previous','earlier'):p.add_argument('--'+name,type=Path)
    a=p.parse_args();s=build(a.run,a.output,parent=a.parent,previous=a.previous,earlier=a.earlier)
    print(json.dumps({'report':s['report'],'phase':s['phase'],'strong_gate':s['passes_declared_development_gate'],'current_goal':s['current_user_retention_and_false_alarm_goal_met']}))


if __name__=='__main__':main()
