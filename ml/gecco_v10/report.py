"""Arabic V10 report: exact all19 audit, parent audit and same-axis diagnosis.

No model/calibration execution. Historical reports are immutable inputs.
Statistical acceptance, descriptive retention and software readiness stay distinct.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from ml.gecco_v8.report import (EXPECTED_NAMES, PAIRS, METRIC_HEAD, audit_count, esc, link, ltr,
    maximum_delay, metric_row, number, pct, read, sha, load_verified as load_v8_verified)
from ml.gecco_v9.report import load_verified as load_v9_verified

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ('IF', 'V6', 'V8', 'V9', 'V10')


def load_verified(run, parent):
    result, plan = read(run/'results.json'), read(run/'plan.json')
    if (result.get('candidate_version') != 'V10' or result.get('complete_cases') != 19 or result.get('expected_cases') != 19
            or result.get('all_prespecified_cases_complete') is not True or not result.get('completed_at_utc')
            or [p.get('case') for p in result.get('periods', [])] != EXPECTED_NAMES or (run/'failed_case.json').exists()
            or result.get('development_only') is not True or result.get('fresh_validation') is not False
            or result.get('model_refitted') is not False or result.get('maximum_allowed_extra_delay_seconds') != 120
            or plan.get('scope') != 'all' or plan.get('limit_cases') != 19
            or plan.get('attempt') != 'v10_run01_positive_pulse_pending_certification'):
        raise ValueError('Report requires all19 fixed V10 disclosed-development results without refitting')
    audit_path = next((run/n for n in ('audit.json','replay_audit.json') if (run/n).is_file()), None)
    if audit_path is None: raise ValueError('Report awaits V10 independent audit')
    audit = read(audit_path)
    if (audit.get('passed') is not True or audit.get('failed_checks') != 0 or audit.get('complete_replayed_cases') != 19
            or audit.get('audit_version') != 'v10_pending_pulse_full_raw_sensor_replay_v1'
            or audit.get('attempt') != plan['attempt']
            or audit.get('hashes', {}).get('results.json') != sha(run/'results.json')
            or audit.get('hashes', {}).get('plan.json') != sha(run/'plan.json')):
        raise ValueError('V10 all19 audit must PASS for these exact results/plan')
    if (ROOT/plan['parent_run']).resolve() != parent: raise ValueError('Parent run mismatch')
    previous, parent_audit_path, parent_audit = load_v9_verified(parent)
    for filename in ('plan.json','results.json','audit.json'):
        digest = sha(parent/filename)
        if plan['parent_sha256'].get(filename) != digest or audit['hashes'].get('parent/'+filename) != digest:
            raise ValueError('Exact passing parent V9 lineage required')
    return result, audit_path, audit, previous, parent_audit_path, parent_audit


def load_diagnosis(run, parent, earlier, result):
    path = run/'post_test_diagnosis.json'; diagnosis = read(path)
    if (diagnosis.get('candidate_version') != 'V10' or diagnosis.get('cross_run_axis_verified') is not True
            or diagnosis.get('v9_scores_exactly_unchanged') is not True
            or Path(diagnosis.get('previous_run','')).resolve() != parent
            or Path(diagnosis.get('earlier_run','')).resolve() != earlier
            or any(diagnosis.get(k) is not False for k in ('fresh_validation','new_source_accessed','model_refitted','thresholds_changed','policies_reexecuted_for_diagnosis'))):
        raise ValueError('Diagnosis must certify fixed V8/V9/V10 axes without new fits or policy runs')
    for relative,digest in diagnosis['input_sha256'].items():
        if sha(run/relative) != digest: raise ValueError('Diagnosis input changed')
    for absolute,digest in diagnosis['cross_run_input_sha256'].items():
        if sha(Path(absolute)) != digest: raise ValueError('Cross-run diagnosis input changed')
    for folder in (run,parent,earlier):
        if diagnosis['cross_run_input_sha256'].get(str(folder/'results.json')) != sha(folder/'results.json'):
            raise ValueError('Missing exact cross-run result hash')
    for key in ('cross_run_period_comparison','conditional_coverage_by_period','policy_evidence_by_period'):
        if [p['case'] for p in diagnosis[key]] != EXPECTED_NAMES: raise ValueError('Diagnosis requires all19 period identities')
    if set(diagnosis['cross_run_source_comparison']) != set(result['sources']): raise ValueError('Missing source pools')
    active = {p['case'] for p in result['periods'] if p['selected']['decision'] != 'reference'}
    if {p['case'] for p in diagnosis['active_periods']} != active or {p['case'] for p in diagnosis['fallbacks']} != set(EXPECTED_NAMES)-active:
        raise ValueError('Active/fallback coverage mismatch')
    return path,diagnosis


def all_models(metrics):
    return ''.join(metric_row(version, metric) for version,metric in zip(VERSIONS,metrics))


def counts(values):
    return ltr(' | '.join(f'{version} {value}' for version,value in zip(VERSIONS,values)))


def objective_facts(result):
    facts = {}
    all_scopes = [p['comparisons'] for p in result['periods']]+list(result['sources'].values())
    for pair in PAIRS:
        scopes = [scope[pair] for scope in all_scopes]; summary = result['summary'][pair]
        facts[pair] = {
            'all_periods_and_pools_retain_original_event_ids': all(not x['lost_baseline_event_ids'] for x in scopes),
            'all_periods_and_pools_keep_availability': all(x['sensor_availability_equal'] for x in scopes),
            'all_paired_event_delays_at_most120s': all(d['extra_delay_seconds'] <= 120 for x in scopes for d in x['paired_extra_delays']),
            'no_scope_increases_false_fragments_or_duration': all(x['candidate']['false_positive_runs'] <= x['baseline']['false_positive_runs'] and x['candidate']['fp_duration_seconds'] <= x['baseline']['fp_duration_seconds'] for x in scopes),
            'strictly_fewer_pooled_false_fragments': summary['candidate']['false_positive_runs'] < summary['baseline']['false_positive_runs']}
        facts[pair]['retention_and_false_alarm_objective_met'] = all(facts[pair].values())
    return facts


def prototype_evidence(destination):
    paths = [ROOT/'output/ml/gecco-v9/prototype-demo/streaming_audit_gecco2019_only_v2.json',
             ROOT/'output/ml/gecco-v9-development/run_01/streaming_audit.json',
             ROOT/'output/ml/gecco-v9-development/run_01/streaming_failure_diagnosis.json']
    available = {p.name: {'path':str(p),'sha256':sha(p)} for p in paths if p.is_file()}
    text = ('اختبار البث السابق يخص V9: اجتاز بادئة GECCO2019 التي تضم 1600 صف فقط، بينما أخفق اختبار WaterHub في مطابقة الدرجات عند التسامح العددي المعلن. '
        'هذا لا يثبت بث جميع الفترات أو بث V10. لم يُقَس زمن Raspberry Pi، وجاهزية الواجهة البرمجية لا تعني قبول النموذج إحصائيًا.')
    if all(p.is_file() for p in paths):
        passed,failed,detail = [read(p) for p in paths]
        if passed.get('passed') is not True or failed.get('passed') is not False or detail.get('case') != '2019-04':
            raise ValueError('Prototype evidence changed; review both success and failure before reporting')
        text += ' '+ ' · '.join(link(p,destination,label) for p,label in zip(paths,('البادئة المجتازة','سجل إخفاق البث','تشخيص اختلاف الدرجات')))
    else:
        text += ' بعض ملفات أدلة البث غير متاحة؛ لا يُستنتج منها اجتياز جديد.'
    return text,available


def support_evidence(run,destination):
    path=run/'suppression_support.json'
    if not path.is_file(): return '',None
    support=read(path)
    if (support.get('candidate_version')!='V10' or support.get('status')!='post_test_saved_confirmation_support_only'
            or support.get('input_sha256',{}).get(str(run/'results.json'))!=sha(run/'results.json')
            or any(support.get(k) is not False for k in ('new_source_accessed','model_refitted','thresholds_changed','policy_reexecuted'))):
        raise ValueError('Support diagnosis must describe only unchanged saved V10 artifacts')
    for absolute,digest in support['input_sha256'].items():
        if sha(Path(absolute))!=digest: raise ValueError('Support diagnosis input changed')
    rows=[]
    for case in support['cases']:
        for b in case['blocks']:
            rows.append('<tr><th>'+ltr(case['case'])+'</th><td>'+str(b['block']+1)+'</td><td>'+str(b['positive_reference_pulses'])+'</td><td>'+str(b['pulses_with_any_positive_confidence_below_low'])+'</td><td>'+str(b['positive_response_delayed_pulses'])+'</td><td>'+str(b['positive_response_absent_inside_pulse'])+'</td><td>'+str(b['positive_alarm_rows_removed'])+'</td></tr>')
    lost=''.join('<p>'+ltr(e['case']+' #'+str(e['event_id']))+': درجة نبضته المرجعية '+ltr(str(e['raw_confidence']))+'؛ مساواة الدرجة المحمية والخام '+ltr(str(e['guarded_equals_raw_on_pulse']))+'، وتوفر الخصائص الشرطية في كل صفوف النبضة '+ltr(str(e['conditional_observed_on_every_pulse_row']))+'.</p>' for e in support['lost_event_score_evidence'])
    html=('<h3>الدعم الفعلي للتأكيد في الماضي</h3><p>الكتلتان 1 و2 للاختيار، و3 و4 للشهادة. الأعداد تخص نبضات مرجعية تتقاطع مع قراءات موجبة، وليست عدد أحداث مستقلة؛ قد تنقسم النبضة عند حد كتلة. هذه أوصاف من التوقعات المحفوظة دون تجربة قرار بديل.</p><table><thead><tr><th>الفترة</th><th>الكتلة</th><th>نبضات موجبة</th><th>فيها درجات موجبة دون العتبة</th><th>استجابة موجبة مؤخرة</th><th>لا استجابة موجبة داخل النبضة</th><th>صفوف موجبة محذوفة</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'+lost+'<p>'+link(path,destination,'ملحق الدعم وبصماته')+'</p>')
    return html,{'path':str(path),'sha256':sha(path)}


def render(run,destination,result,audit_path,audit,parent,previous,earlier,old,diagnosis_path,diagnosis):
    summary = result['summary']; accepted = all(summary[p]['passes_declared_development_gate'] for p in PAIRS)
    facts = objective_facts(result); periods = result['periods']
    historical = {'v8':{p['case']:p for p in old['periods']}, 'v9':{p['case']:p for p in previous['periods']}}
    paired = {p['case']:p for p in diagnosis['cross_run_period_comparison']}
    policy = {p['case']:p for p in diagnosis['policy_evidence_by_period']}
    metrics = [summary['if_vs_v7']['baseline'],summary['v6_vs_v7']['baseline'],old['summary']['v6_vs_v7']['candidate'],previous['summary']['v6_vs_v7']['candidate'],summary['v6_vs_v7']['candidate']]
    for prior in (old,previous):
        for pair in PAIRS:
            if prior['summary'][pair]['baseline'] != summary[pair]['baseline']: raise ValueError('Historical baseline differs')
    losses = {pair:{p['case']:p['comparisons'][pair]['lost_baseline_event_ids'] for p in periods if p['comparisons'][pair]['lost_baseline_event_ids']} for pair in PAIRS}
    delay = {pair:max((d['extra_delay_seconds'] for scope in [p['comparisons'] for p in periods]+list(result['sources'].values()) for d in scope[pair]['paired_extra_delays']),default=None) for pair in PAIRS}
    heading = 'V10 اجتازت بوابة التطوير؛ يلزم تحقق خارجي جديد' if accepted else 'V10 لم تحقق شروط التحسن الثابت'
    if any(losses.values()): heading = 'V10 غير مقبولة: بقي فقد أحداث مرجعية'
    period_rows=[]; retained_rows=[]; policy_rows=[]; coverage_rows=[]
    for p in periods:
        name=p['case']; a=p['comparisons']['if_vs_v7']; b=p['comparisons']['v6_vs_v7']; c=paired[name]
        previous_metrics=[]
        comparisons=[('IF',a),('V6',b)]
        for version in ('v8','v9'):
            pair=c[version+'_vs_v10']; saved=historical[version][name]['comparisons']['v6_vs_v7']['candidate']
            if pair['baseline'] != saved or pair['candidate'] != b['candidate']: raise ValueError('Same-axis metadata mismatch')
            previous_metrics.append(saved); comparisons.append((version.upper(),pair))
        ms=[a['baseline'],b['baseline'],*previous_metrics,b['candidate']]
        period_rows.append('<tr><th>'+ltr(name)+'</th><td>'+str(ms[-1]['true_events'])+'</td><td>'+counts([m['confirmed_events'] for m in ms])+'</td><td>'+counts([m['false_positive_runs'] for m in ms])+'</td><td>'+counts([number(m['fp_duration_seconds']/60) for m in ms])+'</td><td>'+pct(ms[-1]['f1_observed_points'])+'</td><td>'+ltr(' | '.join(v+' '+str(x.get('noninferior_with_120s_limit',x.get('noninferior'))) for v,x in comparisons))+'</td></tr>')
        retained_rows.append('<tr><th>'+ltr(name)+'</th><td>'+ltr(' | '.join(v+' '+str(x['lost_baseline_event_ids']) for v,x in comparisons))+'</td><td>'+ltr(' | '.join(v+' '+number(maximum_delay(x))+' s' for v,x in comparisons))+'</td><td>'+ltr(' | '.join(v+' '+str(x['lost_positive_alarm_rows']) for v,x in comparisons))+'</td></tr>')
        s=p['selected']; detail=policy[name]; pending=detail['pending_at_earlier_chosen_other_settings']
        ptext='غير مطبق' if not pending else '؛ '.join('normal='+str(x['pending_added_normal_rows'])+', events='+str(x['pending_coverage_event_ids'])+', blocks='+str(x['pending_coverage_blocks']) for x in pending)
        policy_rows.append('<tr><th>'+ltr(name)+'</th><td>'+ltr(s['status'])+'</td><td>'+ltr('low '+number(s['low_threshold'])+' | high '+number(s['high_threshold'])+' | '+number(s['confirmation_delay_seconds'])+' s | pending '+str(s['pending_after_clear']))+'</td><td>'+ltr(str(detail['pending_grid_feasible_trials'])+' / '+str(detail['pending_grid_trials']))+'</td><td>'+esc(ptext)+'</td><td>'+esc('؛ '.join(s['certification_rejection_reasons']) or '—')+'</td></tr>')
        cov=p['conditional_block_test_coverage']; supported=audit.get('conditional_audit_by_case',{}).get(name,{}).get('supported')
        coverage_rows.append('<tr><th>'+ltr(name)+'</th><td>'+('غير متاح' if supported is None else ('مدعوم' if supported else 'غير مدعوم'))+'</td><td>'+str(cov['observed_on_reference_available_rows'])+' من '+str(cov['reference_available_rows'])+'</td></tr>')
    source_html=[]
    for source,scopes in result['sources'].items():
        historical_metrics=[]; info=[]
        for version,prior in (('v8',old),('v9',previous)):
            comp=diagnosis['cross_run_source_comparison'][source][version+'_vs_v10']
            if comp['baseline'] != prior['sources'][source]['v6_vs_v7']['candidate'] or comp['candidate'] != scopes['v6_vs_v7']['candidate']: raise ValueError('Pooled source mismatch')
            historical_metrics.append(comp['baseline']); info.append((version.upper(),comp))
        comps=[('IF',scopes['if_vs_v7']),('V6',scopes['v6_vs_v7']),*info]
        source_html.append('<h3>'+ltr(source)+'</h3><table>'+METRIC_HEAD+'<tbody>'+all_models([scopes['if_vs_v7']['baseline'],scopes['v6_vs_v7']['baseline'],*historical_metrics,scopes['v6_vs_v7']['candidate']])+'</tbody></table><p>معرّفات مفقودة: '+ltr(' | '.join(v+' '+str(c['lost_baseline_event_ids']) for v,c in comps))+'؛ أقصى تأخير: '+ltr(' | '.join(v+' '+number(maximum_delay(c))+' s' for v,c in comps))+'</p>')
    gate_html=''.join('<h3>'+label+'</h3><ul class="checks">'+''.join('<li class="'+('ok' if value else 'bad')+'">'+esc(key)+': '+str(value)+'</li>' for key,value in summary[pair]['checks'].items())+'</ul>' for pair,label in (('if_vs_v7','مقابل IF'),('v6_vs_v7','مقابل V6')))
    timing_rows=[]
    for e in diagnosis['timing_comparison']:
        states=[]; pulse_scores=[]; crossing=[]
        for version in ('v8','v9','v10'):
            t=e[version]; states.append(version.upper()+' '+('detected' if t['confirmed_index'] is not None else 'missed'))
            ps=t['reference_pulses']; pulse_scores.append(version.upper()+' low '+number(t['fixed_low_threshold'])+'; '+' / '.join(number(p['confidence_first_values_including_after_pulse'][0]) for p in ps))
            crossing.append(version.upper()+' '+' / '.join(number(p['first_raw_confidence_crossing_seconds_before_event_end'])+' s' for p in ps))
        timing_rows.append('<tr><th>'+ltr(e['case'])+'</th><td>'+str(e['event_id'])+'</td><td>'+ltr(' | '.join(states))+'</td><td>'+ltr(' | '.join(pulse_scores))+'</td><td>'+ltr(' | '.join(crossing))+'</td></tr>')
    diagnostic_html=[]
    for detail in diagnosis['policy_evidence_by_period']:
        s=detail['v10_final']; old_choice=detail['v9_earlier_choice_in_v10_saved_grid']
        if detail['v9_status'] != detail['v10_status'] or s['low_threshold'] is not None:
            old_fail='؛ '.join(reason for row in old_choice for reason in row['rejection_reasons']) or 'لا رفض مبكر للوصفة السابقة'
            pending=detail['pending_at_earlier_chosen_other_settings']
            pending_note='؛ '.join(f"صفوف طبيعية إضافية {row['pending_added_normal_rows']}، أحداث تغطية {row['pending_coverage_event_ids']}، كتل {row['pending_coverage_blocks']}" for row in pending) or 'لا خيار تأكيد مبكر نشط'
            diagnostic_html.append('<p><strong>'+ltr(detail['case'])+'</strong>: '+ltr(detail['v9_status']+' → '+detail['v10_status'])+'. رفض وصفة V9 في الشبكة المبكرة: '+esc(old_fail)+'. دليل pending عند بقية إعدادات الوصفة المبكرة: '+esc(pending_note)+'.</p>')
    statuses=dict(Counter(p['selected']['status'] for p in periods)); pending_count=sum(p['selected']['pending_after_clear'] for p in periods)
    prototype_html,prototype_artifacts=prototype_evidence(destination)
    support_html,support_info=support_evidence(run,destination)
    public=ROOT/'output/ml/gecco-v8-source-search/public_only_followup_v2.json'
    public_html=link(public,destination,'مراجعة المصادر العامة السابقة') if public.is_file() else 'لم يُستخدم مصدر قياسات جديد'
    status={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'candidate':'V10','run':str(run),
        'phase':'development_pass_needs_fresh_validation' if accepted else 'development_failed','complete_cases':19,
        'independent_replay_audit_passed':True,'parent_v9_replay_audit_passed':True,
        'passes_declared_development_gate':accepted,'retention_false_alarm_objective_facts':facts,
        'strong_gate_changed':False,'replay_audit_proves_model_acceptance':False,
        'fresh_external_validation_performed':False,'deployment_approved':False,'three_d_connected':False,
        'summary':summary,'historical_candidates':{'V8':metrics[2],'V9':metrics[3]},
        'lost_events_by_period':losses,'maximum_paired_extra_delay_seconds':delay,'policy_status_counts':statuses,
        'pending_selected_periods':diagnosis['pending_selected_periods'],
        'cross_run_source_comparison':diagnosis['cross_run_source_comparison'],
        'prototype_assessment':'V9 GECCO2019 prefix passed; WaterHub score fidelity failed. Not all-period/V10 stream validation or RaspberryPi evidence.',
        'prototype_artifacts':prototype_artifacts,'post_test_diagnosis':str(diagnosis_path),'suppression_support':support_info,
        'artifact_hashes':{'results':sha(run/'results.json'),'plan':sha(run/'plan.json'),'audit':sha(audit_path),'diagnosis':sha(diagnosis_path),'v9_results':sha(parent/'results.json'),'v9_audit':sha(parent/'audit.json'),'v8_results':sha(earlier/'results.json')},'report':str(destination)}
    doc=f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — V10</title>
<style>body{{margin:0;background:#eff4f4;color:#17323a;font:17px/1.8 system-ui,sans-serif}}main{{max-width:1680px;margin:auto;padding:24px}}header{{padding:25px;border-radius:15px;background:#07424b;color:white}}section{{background:white;padding:22px;margin:20px 0;border-radius:14px;overflow:auto}}.notice{{padding:18px;background:#fff1d6;border-right:5px solid #b77b14;margin:20px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{text-align:right;vertical-align:top;padding:10px;border-bottom:1px solid #d9e4e4;white-space:nowrap}}thead{{background:#e8f1f2}}.ltr{{direction:ltr;unicode-bidi:isolate;display:inline-block}}.checks{{direction:ltr;text-align:left;font:14px/1.8 monospace}}.ok{{color:#176346}}.bad{{color:#aa3028}}a{{color:#08717a}}summary{{cursor:pointer;font-weight:bold}}</style>
<main><header><h1>{heading}</h1><p>19 فترة مكتملة؛ تدقيق مستقل مطابق ناجح. لا ربط بالـ3D أو بالصمام.</p></header>
<div class="notice">هذه نتائج تطوير على بيانات سبق كشفها. التدريب والمعايرة يسبقان الاختبار داخل كل تقسيم، لكن التصميم استفاد من المحاولات السابقة. التدقيق المستقل يعيد فحص الحسابات ولا يحول هذه البيانات إلى تحقق خارجي جديد.</div>
<section><h2>المقارنة على المحور الأصلي نفسه</h2><table>{METRIC_HEAD}<tbody>{all_models(metrics)}</tbody></table><p>عدم التراجع مقابل V6: {summary['v6_vs_v7']['noninferior_periods']} من 19؛ مقابل IF: {summary['if_vs_v7']['noninferior_periods']} من 19. أقصى تأخير إضافي مقترن: {ltr('IF '+number(delay['if_vs_v7'])+' s | V6 '+number(delay['v6_vs_v7'])+' s')}. الحد 120 ثانية. الحدث المفقود مستقل عن حساب التأخير؛ لا يخفيه متوسط أو حد منخفض.</p></section>
<section><h2>هدف الاحتفاظ والإنذارات، وبوابة التطوير</h2><p>الاحتفاظ بكل المعرّفات مع عدم زيادة المقاطع أو المدة الكاذبة في أي فترة أو مصدر، وتقليل المقاطع المجمعة، يُعرض كحقيقة منفصلة: {ltr('IF '+str(facts['if_vs_v7']['retention_and_false_alarm_objective_met'])+' | V6 '+str(facts['v6_vs_v7']['retention_and_false_alarm_objective_met']))}. بوابة التطوير الأصلية أوسع: تشترط أيضًا زيادة إجمالي الأحداث وتحسن كشف الأحداث في فترتين على الأقل، مع بقية القيود. لم نغيرها حتى لو اجتازت تجربة ما عدم التراجع في الفترات كلها.</p>{gate_html}</section>
<section><h2>ما تغير في V10</h2><p>النماذج ودرجات V9 ثابتة حرفيًا، دون إعادة تدريب. أُضيف شرط حفظ كل نبضة مرجعية تتقاطع مع جزء موجب معلوم خلال 120 ثانية وفي الجزء الموجب نفسه، إلى اختيار أول كتلتين ماضيتين، وشهادة الكتلتين التاليتين، والفحص المشترك للكتل الأربع. يفحص الشرط مسار التأكيد قبل إنقاذ مستقل، فلا يخفي الإنقاذ فقد النبضة.</p><p>خيار pending يحتفظ بالدليل بعد انتهاء النبضة حتى موعدها الأصلي فقط؛ يحتاج درجة حالية منتهية تتجاوز العتبة ولا يفرض إنذارًا بعد زوال النبضة. لا تعيد نبضة جديدة ضبط الموعد، وعدم توفر المرجع يلغي الانتظار. يتطلب الخيار صفر صف طبيعي إضافي ودليل تغطية لحدثين أصليين في كتلتين، مبكرًا وفي الشهادة اللاحقة. عدد الفترات التي اختير فيها فعليًا: {pending_count}.</p><p>يختار الماضي المبكر وصفة واحدة، ثم تقبلها الشهادة أو تعيد V6 كله دون البحث عن بديل. هذه شهادة للسياسة الإضافية مشروطة بمرجع V6 الذي سبق ضبطه بالكتل الأربع؛ ليست عينة مستقلة للمنظومة كاملة.</p></section>
<section><h2>الفترات التسع عشرة</h2><table><thead><tr><th>الفترة</th><th>الأحداث الحقيقية</th><th>المكتشفة</th><th>المقاطع الكاذبة</th><th>الدقائق الكاذبة</th><th>F1 لـV10</th><th>عدم التراجع أمام الإصدارات</th></tr></thead><tbody>{''.join(period_rows)}</tbody></table></section>
<section><h2>كل الفقد والتأخير</h2><p>المعرّفات هنا على محور كل فترة. القراءات الموجبة المحذوفة وصف للتكلفة، وليست شرطًا جديدًا بعد السماح بالتأكيد لمدة دقيقتين. الكشف الأساسي يتطلب انتقال سكون إلى إنذار داخل حدث معلوم البداية؛ تغطية دقائق إضافية لا تعوض معرّفًا مفقودًا.</p><table><thead><tr><th>الفترة</th><th>المعرّفات المفقودة</th><th>أقصى تأخير مقترن</th><th>قراءات موجبة حُذفت</th></tr></thead><tbody>{''.join(retained_rows)}</tbody></table></section>
<section><h2>المصادر على محاورها المتصلة</h2><p>تُجمع الصفوف قبل حساب المقاييس حتى لا يتكرر حدث يعبر حدود الفترات. F1 للقراءات، وليس احتمال سلامة المياه.</p>{''.join(source_html)}</section>
<section><h2>القرارات وأسباب الدعم أو الرجوع</h2><p>{esc(json.dumps(statuses,ensure_ascii=False))}</p><details><summary>الوصفات والأدلة لكل الفترات</summary><table><thead><tr><th>الفترة</th><th>الحالة</th><th>الوصفة النهائية</th><th>وصفات pending المجتازة من المجربة مبكرًا</th><th>دليل pending عند بقية إعدادات الاختيار المبكر</th><th>أسباب الرجوع</th></tr></thead><tbody>{''.join(policy_rows)}</tbody></table></details>{''.join(diagnostic_html)}</section>
<section><h2>تشخيص التوقيت عند العتبات المثبتة</h2><p>الدرجات الخام لـV9 وV10 متطابقة؛ الفرق من سياسة القرار أو الرجوع. أول بلوغ للعتبة بعد زوال نبضة ليس إنذارًا منفذًا إذا كان pending غير مختار. يعرض التشخيص كامل المحاولات السابقة المحفوظة، ولا يختبر عتبة أو وصفة بديلة بعد النتائج.</p><table><thead><tr><th>الفترة</th><th>الحدث</th><th>الكشف</th><th>العتبة ودرجات بداية النبضات</th><th>أول بلوغ منذ بداية النبضة</th></tr></thead><tbody>{''.join(timing_rows)}</tbody></table><p>{link(diagnosis_path,destination,'التشخيص الكامل وبصمات مدخلاته')}</p>{support_html}</section>
<section><h2>دليل العلاقات بين الحساسات</h2><p>هذا الجزء نفسه الموروث من V9: بواقي Ridge متعلم من القراءات الطبيعية، مع مصنف HGB ذي إشراف وأوزان للبدايات. الدرجة ليست احتمال سلامة معايرًا. التغطية أدناه لا تغير إتاحة المرجع أو مقام الأحداث.</p><table><thead><tr><th>الفترة</th><th>دعم التدريب</th><th>صفوف الدليل من الصفوف المرجعية المتاحة</th></tr></thead><tbody>{''.join(coverage_rows)}</tbody></table></section>
<section><h2>التدقيق وجاهزية البرمجيات</h2><p>أُعيد فحص {audit_count(audit,'replayed_rows')} صف اختبار و{audit_count(audit,'calibration_sensor_rows_replayed')} صف معايرة، مع مطابقة النماذج الموروثة والدرجات، ومسار pending وشهادة النبضات والمقاييس. التدقيق ناجح، لكن هذا منفصل عن قبول أداء النموذج.</p><p>{prototype_html}</p><p>{link(audit_path,destination,'تدقيق V10')} · {link(parent/'audit.json',destination,'تدقيق V9 الأصل')} · {link(run/'plan.json',destination,'الخطة المثبتة')} · {link(run/'results.json',destination,'النتائج الكاملة')}</p></section>
<section><h2>حدود النتيجة والأرشيف</h2><p>{public_html}. لم تدخل قياسات مصدر جديد؛ يلزم تحقق خارجي لم يستخدم في التصميم. لا تثبت هذه التجارب تصنيف أنواع الأعطال الخمسة، أو صلاحية مياه الوضوء، أو تشغيلًا ميدانيًا. لا صلاحية لفتح الصمام.</p><p>{link(ROOT/'output/ml/gecco-v9/report.html',destination,'تقرير V9')} · {link(ROOT/'output/ml/gecco-v8/report.html',destination,'تقرير V8')} · {link(ROOT/'output/ml/gecco-v7-development/run_04/results.json',destination,'V7 run04')}</p></section><footer>{ltr(result['completed_at_utc'])} · المحاولات السابقة وإخفاقاتها محفوظة.</footer></main></html>'''
    return doc,status


def build(run,destination,*,parent=None,earlier=None,status_path=None):
    run,destination=Path(run).resolve(),Path(destination).resolve()
    parent=Path(parent).resolve() if parent else ROOT/'output/ml/gecco-v9-development/run_01'
    earlier=Path(earlier).resolve() if earlier else ROOT/'output/ml/gecco-v8-development/run_01'
    result,audit_path,audit,previous,_,_=load_verified(run,parent)
    old,_,_=load_v8_verified(earlier)
    diagnosis_path,diagnosis=load_diagnosis(run,parent,earlier,result)
    doc,status=render(run,destination,result,audit_path,audit,parent,previous,earlier,old,diagnosis_path,diagnosis)
    status_path=Path(status_path).resolve() if status_path else destination.parent/'status.json'
    allowed=ROOT/'output/ml/gecco-v10'
    if not destination.is_relative_to(allowed) or not status_path.is_relative_to(allowed) or destination==status_path:
        raise ValueError('Report outputs must remain in the new V10 report folder')
    if destination.exists() or status_path.exists(): raise FileExistsError('Preserve existing report/status before explicit regeneration')
    destination.parent.mkdir(parents=True,exist_ok=True);status_path.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(doc);status_path.write_text(json.dumps(status,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    return status


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--parent',type=Path);parser.add_argument('--earlier',type=Path)
    args=parser.parse_args();status=build(args.run,args.output,parent=args.parent,earlier=args.earlier)
    print(json.dumps({'report':status['report'],'phase':status['phase'],'gates':status['passes_declared_development_gate']}))


if __name__=='__main__':main()
