"""Seven-model Arabic V12 report; complete results and exact PASS audits only.

Reads saved results, audits and hashed descriptive diagnostics. It never fits,
reads source measurements, evaluates a different policy or opens partial rows.
V12 is a new HGB fit: historical confidence/model identity is not assumed.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
from ml.gecco_v8.report import EXPECTED_NAMES,PAIRS,METRIC_HEAD,audit_count,esc,link,ltr,maximum_delay,metric_row,number,pct,read,sha
from ml.gecco_v10.report import objective_facts
from ml.gecco_v11.report import load_verified as load_v11_verified

ROOT=Path(__file__).resolve().parents[2]
HISTORICAL=('V8','V9','V10','V11')
MODELS=('IF','V6',*HISTORICAL,'V12')
ATTEMPT='v12_run01_if_raw_score_feature_hgb'
AUDIT_VERSION='v12_frozen_if_evidence_full_raw_sensor_batch_replay_v1'


def load_verified(run,folders):
    result,plan=read(run/'results.json'),read(run/'plan.json')
    if (result.get('candidate_version')!='V12' or result.get('complete_cases')!=19 or result.get('expected_cases')!=19
        or result.get('all_prespecified_cases_complete') is not True or not result.get('completed_at_utc')
        or [p.get('case') for p in result.get('periods',[])]!=EXPECTED_NAMES or (run/'failed_case.json').exists()
        or result.get('development_only') is not True or result.get('fresh_validation') is not False
        or result.get('maximum_allowed_extra_delay_seconds')!=120
        or plan.get('scope')!='all' or plan.get('limit_cases')!=19 or plan.get('expected_cases')!=19 or plan.get('attempt')!=ATTEMPT):
        raise ValueError('All19 fixed V12 disclosed-development results required')
    audit_path=next((run/n for n in ('audit.json','replay_audit.json') if (run/n).is_file()),None)
    if audit_path is None:raise ValueError('Awaiting V12 independent audit')
    audit=read(audit_path)
    if (audit.get('passed') is not True or audit.get('failed_checks')!=0 or audit.get('complete_replayed_cases')!=19
        or audit.get('audit_version')!=AUDIT_VERSION or audit.get('attempt')!=ATTEMPT
        or audit.get('hashes',{}).get('results.json')!=sha(run/'results.json')
        or audit.get('hashes',{}).get('plan.json')!=sha(run/'plan.json')):
        raise ValueError('Exact all19 passing V12 audit required')
    evidence=audit.get('if_evidence_audit_by_case',{})
    if set(evidence)!=set(EXPECTED_NAMES):raise ValueError('Original IF evidence accounting requires all19 cases')
    for item in evidence.values():
        if (item.get('prior_and_attached_fitted_states_identical') is not True
            or item.get('representation_is_in_sample_not_cross_fitted') is not True
            or item.get('original_if_refitted_by_audit') is not False):raise ValueError('Original IF lineage or representation audit mismatch')
    v11,_,_,older=load_v11_verified(folders['v11'],folders['v10'],folders['v9'],folders['v8'])
    # Historical audits are comparators, not a claim that V12 inherited their
    # fitted HGB, scores or V11 hard-protection policy.
    return result,audit_path,audit,{**older,'V11':v11}


def load_diagnosis(run,folders,result):
    path=run/'post_test_diagnosis.json';d=read(path)
    if (d.get('candidate_version')!='V12' or d.get('cross_run_axis_verified') is not True
        or d.get('original_if_v6_predictions_unchanged') is not True or d.get('experiment_refitted_hgb') is not True
        or any(d.get(k) is not False for k in ('experiment_refitted_original_if','fresh_validation','new_source_accessed',
            'model_refitted_by_diagnosis','thresholds_changed','policies_reexecuted_for_diagnosis'))):
        raise ValueError('Read-only same-axis diagnosis of newly fitted V12 HGB required')
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
        key=version.lower()+'_vs_v12'
        scopes=[p[key] for p in d['cross_run_period_comparison']]+[s[key] for s in d['cross_run_source_comparison'].values()]
        out[version]={'all_periods_and_pools_retain_event_ids':all(not c['lost_baseline_event_ids'] for c in scopes),
            'all_periods_and_pools_noninferior_with120s':all(c['noninferior_with_120s_limit'] for c in scopes),
            'lost_ids_by_period':{p['case']:p[key]['lost_baseline_event_ids'] for p in d['cross_run_period_comparison'] if p[key]['lost_baseline_event_ids']},
            'lost_ids_by_source':{name:c[key]['lost_baseline_event_ids'] for name,c in d['cross_run_source_comparison'].items() if c[key]['lost_baseline_event_ids']}}
    return out


def render(run,destination,result,audit_path,audit,historical,folders,diagnosis_path,d):
    summary=result['summary'];strong=all(summary[p]['passes_declared_development_gate'] for p in PAIRS)
    facts=objective_facts(result);history=historical_retention(d)
    current_goal=all(v['all_periods_and_pools_retain_event_ids'] for v in history.values()) and all(facts[p]['retention_and_false_alarm_objective_met'] for p in PAIRS)
    heading=('V12: تحسن تطويري يحتاج تحققًا خارجيًا جديدًا' if strong and current_goal else
        'V12 حققت الاحتفاظ وتقليل الإنذارات؛ بوابة زيادة الاكتشاف لم تجتز' if current_goal else
        'V12 لم تحقق هدف تقليل الإنذارات دون فقد أحداث')
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
            c=paired[name][v.lower()+'_vs_v12'];saved=historical_periods[v][name]['comparisons']['v6_vs_v7']['candidate']
            if c['baseline']!=saved or c['candidate']!=b['candidate']:raise ValueError('Period metric mismatch')
            ms.append(saved);comps.append((v,c))
        ms.append(b['candidate'])
        period_rows.append('<tr><th>'+ltr(name)+'</th><td>'+str(ms[-1]['true_events'])+'</td><td>'+across([m['confirmed_events'] for m in ms])+'</td><td>'+across([m['false_positive_runs'] for m in ms])+'</td><td>'+across([number(m['fp_duration_seconds']/60) for m in ms])+'</td><td>'+pct(ms[-1]['f1_observed_points'])+'</td><td>'+ltr(' | '.join(v+' '+str(c.get('noninferior_with_120s_limit',c.get('noninferior'))) for v,c in comps))+'</td></tr>')
        loss_rows.append('<tr><th>'+ltr(name)+'</th><td>'+comparison_text(comps,'lost_baseline_event_ids')+'</td><td>'+ltr(' | '.join(v+' '+number(maximum_delay(c))+' s' for v,c in comps))+'</td><td>'+comparison_text(comps,'lost_positive_alarm_rows')+'</td></tr>')
        s=p['selected'];q=policies[name]
        policy_rows.append('<tr><th>'+ltr(name)+'</th><td>'+ltr(s['status'])+'</td><td>'+ltr('low '+number(s['low_threshold'])+' | high '+number(s['high_threshold'])+' | '+number(s['confirmation_delay_seconds'])+' s | pending '+str(s['pending_after_clear']))+'</td><td>'+str(q['pending_grid_feasible_trials'])+' من '+str(q['pending_grid_trials'])+'</td><td>'+esc('؛ '.join(s['certification_rejection_reasons']) or '—')+'</td></tr>')
        evidence=audit['if_evidence_audit_by_case'][name];cov=p['conditional_block_test_coverage']
        evidence_rows.append('<tr><th>'+ltr(name)+'</th><td>'+audit_count(evidence,'original_known_normal_training_windows')+'</td><td>'+audit_count(evidence,'observed_if_rows')+' من '+audit_count(evidence,'rows')+'</td><td>'+str(evidence['prior_and_attached_fitted_states_identical'])+'</td><td>'+str(cov['observed_on_reference_available_rows'])+' من '+str(cov['reference_available_rows'])+'</td></tr>')
    sources=[]
    for source,scopes in result['sources'].items():
        comps=[('IF',scopes['if_vs_v7']),('V6',scopes['v6_vs_v7'])];ms=[c['baseline'] for _,c in comps]
        for v in HISTORICAL:
            c=d['cross_run_source_comparison'][source][v.lower()+'_vs_v12']
            if c['baseline']!=historical[v]['sources'][source]['v6_vs_v7']['candidate'] or c['candidate']!=scopes['v6_vs_v7']['candidate']:raise ValueError('Source metric mismatch')
            ms.append(c['baseline']);comps.append((v,c))
        ms.append(scopes['v6_vs_v7']['candidate'])
        sources.append('<h3>'+ltr(source)+'</h3><table>'+METRIC_HEAD+'<tbody>'+table_models(ms)+'</tbody></table><p>معرّفات مفقودة: '+comparison_text(comps,'lost_baseline_event_ids')+'؛ أقصى تأخير مقترن '+ltr(' | '.join(v+' '+number(maximum_delay(c))+' s' for v,c in comps))+'</p>')
    gates=''.join('<h3>'+label+'</h3><ul class="checks">'+''.join('<li class="'+('ok' if value else 'bad')+'">'+esc(key)+': '+str(value)+'</li>' for key,value in summary[pair]['checks'].items())+'</ul>' for pair,label in (('if_vs_v7','مقابل IF'),('v6_vs_v7','مقابل V6')))
    timing_rows=[]
    for event in d['timing_comparison']:
        states=[];scores=[];crossings=[]
        for v in (*[x.lower() for x in HISTORICAL],'v12'):
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
    status={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'candidate':'V12','run':str(run),'phase':phase,
        'complete_cases':19,'independent_replay_audit_passed':True,'historical_v8_v9_v10_v11_audits_passed':True,
        'passes_declared_development_gate':strong,'strong_gate_changed':False,'current_user_retention_and_false_alarm_goal_met':current_goal,
        'current_goal_definition':'All IF/V6/V8/V9/V10/V11 original event IDs retained in every period and source pool; original IF/V6 availability, <=120s paired delay, no false fragment/duration increase per scope and strictly fewer pooled false fragments. Historical false costs/delays shown separately; original strong gate unchanged.',
        'original_comparator_objective_facts':facts,'historical_retention':history,'summary':summary,
        'historical_candidates':{v:historical[v]['summary']['v6_vs_v7']['candidate'] for v in HISTORICAL},
        'lost_events_by_period':current_loss,'maximum_paired_extra_delay_seconds':maximum,'policy_status_counts':statuses,'pending_selected_periods':pending,
        'experiment_refitted_hgb':True,'original_if_refitted':False,'added_feature_count':2,'added_features':['one original IF raw anomaly score','one finite-observed bit'],
        'if_evidence_audit_by_case':audit['if_evidence_audit_by_case'],'if_representation_cross_fitted':False,
        'fresh_external_validation_performed':False,'new_source_accepted':False,'deployment_approved':False,'three_d_connected':False,'v12_live_stream_tested':False,
        'prototype_scope':'V12 audit is batch only. Earlier prototype checks belong to other versions and limited prefixes; no all-period streaming or Raspberry Pi latency claim.',
        'numeric_context_limitation':'Prefix causality does not establish cropped pandas IF feature or persistent streaming score parity.',
        'post_test_diagnosis':str(diagnosis_path),'cross_run_source_comparison':d['cross_run_source_comparison'],
        'artifact_hashes':{'results':sha(run/'results.json'),'plan':sha(run/'plan.json'),'audit':sha(audit_path),'diagnosis':sha(diagnosis_path),
            **{v+'_results':sha(folder/'results.json') for v,folder in folders.items()}},'report':str(destination)}
    public=ROOT/'output/ml/gecco-v8-source-search/public_only_followup_v2.json'
    public_html=link(public,destination,'مراجعة المصادر العامة السابقة') if public.is_file() else 'لم يُستخدم مصدر جديد'
    archive=' · '.join(link(ROOT/f'output/ml/gecco-{v.lower()}/report.html',destination,'تقرير '+v) for v in HISTORICAL)
    prototype_html=('أدلة البث السابقة تخص إصدارات ومحاور محدودة: اجتازت بادئة GECCO2019 القديمة، وظهر إخفاق عددي في بادئة WaterHub القديمة قبل تطوير محول مستقل. '
        'هذه المحاولة لا تعيد تقييم ذلك المحول ولا تنقل اجتيازه إلى V12. '+link(ROOT/'output/ml/gecco-v11/report.html',destination,'سجل النطاق والأدلة السابقة'))
    doc=f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — V12</title><style>body{{margin:0;background:#eff4f4;color:#17323a;font:17px/1.8 system-ui,sans-serif}}main{{max-width:1800px;margin:auto;padding:24px}}header{{padding:26px;background:#08444d;color:white;border-radius:15px}}section{{background:white;margin:20px 0;padding:22px;border-radius:14px;overflow:auto}}.notice{{padding:18px;background:#fff1d6;border-right:5px solid #b77b14;margin:20px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;border-bottom:1px solid #d9e4e4;text-align:right;vertical-align:top;white-space:nowrap}}thead{{background:#e8f1f2}}.ltr{{direction:ltr;unicode-bidi:isolate;display:inline-block}}.checks{{direction:ltr;text-align:left;font:14px/1.8 monospace}}.ok{{color:#176346}}.bad{{color:#aa3028}}a{{color:#08717a}}summary{{cursor:pointer;font-weight:bold}}</style><main>
<header><h1>{heading}</h1><p>19 فترة مكتملة، مع تدقيق مستقل مطابق. لم يُربط V12 بالـ3D أو بالصمام.</p></header>
<div class="notice">جميع المصادر سبق كشفها في التطوير؛ هذا ليس تحققًا خارجيًا جديدًا. اجتياز التدقيق يعني مطابقة التنفيذ والحساب، ولا يعني أن النموذج نجح في الهدف.</div>
<section><h2>النتيجة على المحور نفسه</h2><table>{METRIC_HEAD}<tbody>{table_models(aggregate)}</tbody></table><p>الفترات غير المتراجعة أمام المرجعين الأصليين: {ltr(noninferior)}. يحتفظ الجدول بالفترات التي رجعت إلى V6 كما هي.</p></section>
<section><h2>الاحتفاظ بالأحداث وبوابة التحسن</h2><p>هدف الاحتفاظ بكل معرّفات IF وV6 والإصدارات اللاحقة مع تقليل الإنذارات أمام IF/V6: {ltr(current_goal)}. بوابة التطوير الأصلية التي تتطلب أيضًا زيادة الاكتشاف عبر أكثر من فترة: {ltr(strong)}. لم تتغير البوابة أو تُستبدل بالهدف الأضيق.</p><p>الفقد مقابل IF/V6: {esc(json.dumps(current_loss,ensure_ascii=False))}. الفقد مقابل كل إصدار لاحق:</p>{historical_loss_html}{gates}</section>
<section><h2>التغيير الوحيد في التمثيل</h2><p>أُضيفت ميزتان إلى سمات V9: <strong>درجة شذوذ خام واحدة من IF الأصلي المجمد، وبت واحد يحدد توفرها</strong>. ليستا درجتين. أُعيد تدريب HGB على كتلة التدريب الأصلية فقط، مع بقاء المراجع الطبيعية وأوزان بدايات الأحداث وRidge وإعدادات HGB والإتاحة كما هي. لم يُعد تدريب IF، ولم يُنقل قرار العتبة أو غلاف الكاشف إليه.</p><p>درجة IF التي تراها صفوف تدريب HGB هي تمثيل داخل العينة، وليست درجة من تدريب متقاطع أو دليلًا مستقلًا. لا تعني درجة HGB احتمال سلامة معايرًا. يتبع القرار سياسة V10، دون قاعدة الحماية الصلبة التي جُربت في V11.</p></section>
<section><h2>كل الفترات</h2><table><thead><tr><th>الفترة</th><th>الأحداث الحقيقية</th><th>الأحداث المكتشفة</th><th>المقاطع الكاذبة</th><th>الدقائق الكاذبة</th><th>F1 لـV12</th><th>عدم التراجع أمام كل إصدار</th></tr></thead><tbody>{''.join(period_rows)}</tbody></table></section>
<section><h2>المعرّفات المفقودة والتأخير الفعلي</h2><p>الحدث المفقود لا يدخل التأخير المقترن؛ لذلك لا يخفي التأخير الصفري فقد حدث. الحد المقبول للمقارنة 120 ثانية. القراءات الموجبة المحذوفة تكلفة وصفية، وليست شرطًا جديدًا بعد السماح بالتأكيد.</p><table><thead><tr><th>الفترة</th><th>معرّفات مفقودة</th><th>أقصى تأخير إضافي</th><th>قراءات موجبة أزيلت</th></tr></thead><tbody>{''.join(loss_rows)}</tbody></table></section>
<section><h2>المصادر على محور متصل</h2><p>تُجمع الصفوف أولًا قبل حساب الحدث؛ لا يتكرر حدث يعبر حدود الفترات. يتطلب معيار الكشف الأساسي انتقال سكون إلى إنذار داخل جزء موجب معلوم البداية. تغطية دقائق أكثر ومقياس F1 لا يحلان محل معرّفات الأحداث.</p>{''.join(sources)}</section>
<section><h2>الشهادة والرجوع إلى المرجع</h2><p>تختار أول كتلتين وصفة واحدة. تفحص الكتلتان اللاحقتان الوصفة نفسها دون إعادة اختيار، ثم تفحص الكتل الأربع على محورها الأصلي. يلزم حفظ النبضات الموجبة ومعرّفات الأحداث والإتاحة والتأخير وكلفة الإنذارات. الشهادة مشروطة بـV6 الذي اختير أصلًا بالكتل الأربع، وليست تحققًا مستقلًا للمنظومة كاملة.</p><p>إذا اختير pending، يحتفظ بموعد النبضة الأصلي ≤120 ثانية، ويحتاج عبورًا فعليًا للثقة بعد زوالها؛ لا يجبر تنبيهًا بعد زوالها. إضافات pending وrescue لا يجوز أن تضيف صفوفًا طبيعية في معايرة الماضي، وتحتاج دعم أحداث عبر كتلتين. عدد الفترات التي اختارت pending: {len(pending)}؛ {ltr(str(pending))}.</p><p>{esc(json.dumps(statuses,ensure_ascii=False))}</p><details><summary>جميع الوصفات وأسباب الرجوع</summary><table><thead><tr><th>الفترة</th><th>الحالة</th><th>الوصفة</th><th>pending المجتازة من المجربة مبكرًا</th><th>أسباب الرفض</th></tr></thead><tbody>{''.join(policy_rows)}</tbody></table></details></section>
<section><h2>تشخيص وصفي بعد الاختبار</h2><p>قد تتغير درجات HGB والعتبات المختارة في V12 لأنه نموذج أعيد تدريبه بتمثيل إضافي. الجدول يعرض الدرجات والقرارات الفعلية، ولا يجرب عتبة بديلة. ارتفاع الدرجة الخام وحده لا يثبت تحسن الفصل عن الطبيعي. يعرض الملف المرفق أيضًا توزيعات الدرجات الطبيعية والموجبة والمجهولة لكل فترة.</p><details><summary>تفاصيل الأحداث التي اختلف كشفها</summary><table><thead><tr><th>الفترة</th><th>الحدث</th><th>الكشف</th><th>العتبات وأول خمس درجات عند النبضات</th><th>زمن أول عبور للعتبة بالثواني</th></tr></thead><tbody>{''.join(timing_rows)}</tbody></table></details><p>{link(diagnosis_path,destination,'التشخيص الكامل وبصمات كل المقارنات')}</p></section>
<section><h2>دليل IF والخصائص الشرطية</h2><p>عمود درجة IF أدناه يخص <strong>صفوف التدريب</strong> التي أعاد المدقق حسابها، وليس تغطية الاختبار. عمود الخصائص الشرطية يخص صفوف الاختبار المتاحة للمرجع؛ كلاهما وصف للدليل، ولا يغير مقام الأحداث.</p><table><thead><tr><th>الفترة</th><th>نوافذ تدريب IF الطبيعية الأصلية</th><th>درجة IF المتوفرة في صفوف التدريب</th><th>حالة IF مطابقة للأصل</th><th>الخصائص الشرطية في الاختبار</th></tr></thead><tbody>{''.join(evidence_rows)}</tbody></table></section>
<section><h2>التدقيق وجاهزية البرنامج</h2><p>أُعيد فحص {audit_count(audit,'replayed_rows')} صف اختبار و{audit_count(audit,'calibration_sensor_rows_replayed')} صف معايرة. شمل التدقيق السمات والمراجع والأوزان وIF المجمد والقرار وشهادة النبضات ومقاييس المحاور الأصلية. {link(audit_path,destination,'تدقيق V12 المطابق')}.</p><p>تعتمد سمات IF على الحالة العددية لـpandas في كامل البادئة المعطاة. السببية لا تثبت أن قص التاريخ يعطي درجات مطابقة، ولا تثبت مطابقة البث المستمر.</p><p>{prototype_html}</p><p><strong>V12 مُدقّق على دفعات فقط؛ لا ادعاء باختبار بث جميع الفترات أو قياس زمن Raspberry Pi.</strong> جاهزية برنامج أولي لا تعني قبول النموذج إحصائيًا.</p></section>
<section><h2>الحدود والأرشيف</h2><p>{public_html}. لم يُقبل مصدر قياسات جديد في هذه المحاولة. لا تثبت النتائج تصنيف الأعطال الخمسة أو ملاءمة مياه الوضوء أو سلامة مياه بعينها. لا صلاحية لفتح الصمام.</p><p>{link(run/'plan.json',destination,'الخطة المثبتة')} · {link(run/'results.json',destination,'النتائج الكاملة')} · {archive}</p></section><footer>{ltr(result['completed_at_utc'])} · جميع المحاولات السابقة محفوظة.</footer></main></html>'''
    return doc,status


def build(run,destination,*,historical_runs=None,status_path=None):
    run,destination=Path(run).resolve(),Path(destination).resolve()
    supplied=historical_runs or {}
    folders={'v12':run,**{v.lower():Path(supplied.get(v.lower(),ROOT/f'output/ml/gecco-{v.lower()}-development/run_01')).resolve() for v in HISTORICAL}}
    result,audit_path,audit,historical=load_verified(run,folders)
    diagnosis_path,d=load_diagnosis(run,folders,result)
    doc,status=render(run,destination,result,audit_path,audit,historical,folders,diagnosis_path,d)
    status_path=Path(status_path).resolve() if status_path else destination.parent/'status.json';allowed=ROOT/'output/ml/gecco-v12'
    if not destination.is_relative_to(allowed) or not status_path.is_relative_to(allowed) or destination==status_path:raise ValueError('Only new V12 report outputs allowed')
    if destination.exists() or status_path.exists():raise FileExistsError('Preserve previous report/status before explicit regeneration')
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
