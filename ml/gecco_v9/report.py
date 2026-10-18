"""Arabic V9 report gated on all19 cases, exact replay audit, and axis diagnosis.

Metadata and artifact hashes only; no fitting, threshold choice or source data.
Old reports remain separate. Software readiness is not statistical acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from ml.gecco_v8.report import (EXPECTED_NAMES, PAIRS, METRIC_HEAD, audit_count, esc,
    link, ltr, maximum_delay, metric_row, number, pct, read, sha,
    load_verified as load_v8_verified)


ROOT = Path(__file__).resolve().parents[2]


def load_verified(run):
    result_path, plan_path = run/'results.json', run/'plan.json'
    if not result_path.is_file(): raise ValueError('Report awaits all19 V9 results')
    result, plan = read(result_path), read(plan_path)
    if (result.get('candidate_version') != 'V9' or result.get('complete_cases') != 19
            or result.get('expected_cases') != 19 or result.get('all_prespecified_cases_complete') is not True
            or [p.get('case') for p in result.get('periods', [])] != EXPECTED_NAMES
            or not result.get('completed_at_utc') or (run/'failed_case.json').exists()
            or plan.get('scope') != 'all' or plan.get('limit_cases') != 19):
        raise ValueError('Report requires every fixed V9 period, including failures')
    if (result.get('development_only') is not True or result.get('fresh_validation') is not False
            or result.get('maximum_allowed_extra_delay_seconds') != 120):
        raise ValueError('Expected disclosed development and unchanged120s event-delay criterion')
    audit_path = next((run/name for name in ('audit.json', 'replay_audit.json') if (run/name).is_file()), None)
    if audit_path is None: raise ValueError('Report awaits independent V9 replay audit')
    audit = read(audit_path)
    if (audit.get('passed') is not True or audit.get('complete_replayed_cases') != 19
            or audit.get('audit_version') != 'v9_conditional_full_raw_sensor_batch_replay_v1'
            or audit.get('attempt') != plan.get('attempt')
            or audit.get('hashes', {}).get('results.json') != sha(result_path)
            or audit.get('hashes', {}).get('plan.json') != sha(plan_path)):
        raise ValueError('All19 independent replay cases must PASS for these exact V9 results/plan')
    return result, audit_path, audit


def load_diagnosis(run, prior_run, result):
    path = run/'post_test_diagnosis.json'
    if not path.is_file(): raise ValueError('Report awaits same-axis V8/V9 diagnosis')
    diagnosis = read(path)
    if (diagnosis.get('candidate_version') != 'V9' or diagnosis.get('cross_run_axis_verified') is not True
            or diagnosis.get('input_sha256', {}).get('results.json') != sha(run/'results.json')
            or Path(diagnosis.get('previous_run', '')).resolve() != prior_run
            or any(diagnosis.get(key) is not False for key in
                   ('fresh_validation', 'new_source_accessed', 'model_refitted', 'thresholds_changed'))):
        raise ValueError('Diagnosis must be tied to the unchanged V9/V8 development artifacts')
    for relative, digest in diagnosis['input_sha256'].items():
        if sha(run/relative) != digest: raise ValueError('Diagnosis input changed: '+relative)
    for absolute, digest in diagnosis['cross_run_input_sha256'].items():
        if sha(Path(absolute)) != digest: raise ValueError('Cross-run diagnosis input changed')
    if (diagnosis['cross_run_input_sha256'].get(str(prior_run/'results.json')) != sha(prior_run/'results.json')
            or diagnosis['cross_run_input_sha256'].get(str(run/'results.json')) != sha(run/'results.json')
            or [p['case'] for p in diagnosis.get('cross_run_period_comparison', [])] != EXPECTED_NAMES
            or [p['case'] for p in diagnosis.get('conditional_coverage_by_period', [])] != EXPECTED_NAMES
            or set(diagnosis.get('cross_run_source_comparison', {})) != set(result['sources'])):
        raise ValueError('Diagnosis must preserve all19 paired periods and every source pool')
    expected_active = {p['case'] for p in result['periods'] if p['selected']['decision'] != 'reference'}
    if ({p['case'] for p in diagnosis['active_periods']} != expected_active
            or {p['case'] for p in diagnosis['fallbacks']} != set(EXPECTED_NAMES)-expected_active
            or len(diagnosis['active_periods'])+len(diagnosis['fallbacks']) != 19):
        raise ValueError('Diagnosis must retain active policies and all reference fallbacks')
    saved = {p['case']: p for p in result['periods']}
    for p in diagnosis['active_periods']:
        if [event['event_id'] for event in p['lost_events']] != saved[p['case']]['comparisons']['v6_vs_v7']['lost_baseline_event_ids']:
            raise ValueError('Diagnosis lost IDs disagree with exact results')
    return path, diagnosis


def quadruple(values):
    return ltr(' | '.join(f'{version} {value}' for version, value in zip(('IF', 'V6', 'V8', 'V9'), values)))


def compare_text(first, reference, prior, key):
    return ltr(' | '.join(f'{version} {value}' for version, value in
                         (('IF', first[key]), ('V6', reference[key]), ('V8', prior[key]))))


def model_rows(first, reference, old, candidate):
    return ''.join(metric_row(name, metrics) for name, metrics in
                   (('IF: النموذج الأول',first), ('V6: المرجع المجمد',reference),
                    ('V8: أوزان البداية',old), ('V9: بواقي العلاقات بين الحساسات',candidate)))


def render(run, destination, result, audit_path, audit, prior_run, previous, diagnosis_path, diagnosis, public_search=None):
    summary = result['summary']
    accepted = all(summary[key]['passes_declared_development_gate'] for key in PAIRS)
    periods = result['periods']; previous_periods = {p['case']: p for p in previous['periods']}
    paired_periods = {p['case']: p['v8_vs_v9'] for p in diagnosis['cross_run_period_comparison']}
    first = summary['if_vs_v7']['baseline']; reference = summary['v6_vs_v7']['baseline']
    candidate = summary['v6_vs_v7']['candidate']; old = previous['summary']['v6_vs_v7']['candidate']
    # Row-level equivalence has already been checked in the saved diagnosis;
    # verify the report metadata continues to describe those identical models.
    if previous['summary']['v6_vs_v7']['baseline'] != reference:
        raise ValueError('Historical V6 aggregate differs across paired runs')
    for p in periods:
        pair = paired_periods[p['case']]
        if (pair['baseline'] != previous_periods[p['case']]['comparisons']['v6_vs_v7']['candidate']
                or pair['candidate'] != p['comparisons']['v6_vs_v7']['candidate']):
            raise ValueError('Paired diagnosis metrics no longer match result metadata')
    all_comps = [p['comparisons'] for p in periods]+list(result['sources'].values())
    delays = {key: max((d['extra_delay_seconds'] for c in all_comps for d in c[key]['paired_extra_delays']), default=None) for key in PAIRS}
    losses = {key: {p['case']: p['comparisons'][key]['lost_baseline_event_ids'] for p in periods
                     if p['comparisons'][key]['lost_baseline_event_ids']} for key in PAIRS}
    heading = 'اجتازت V9 شروط التطوير؛ يلزم تحقق خارجي جديد' if accepted else 'V9 لم تثبت التحسّن الثابت المطلوب'
    if any(losses.values()): heading = 'V9 لم تُقبل: فُقدت أحداث كان المرجع يكتشفها'
    elif any(v is not None and v > 120 for v in delays.values()): heading = 'V9 لم تُقبل: تجاوز التأخير الفعلي دقيقتين'
    period_rows, retention_rows, coverage_rows, policy_rows = [], [], [], []
    for p in periods:
        name = p['case']; a, b = p['comparisons']['if_vs_v7'], p['comparisons']['v6_vs_v7']; v = paired_periods[name]
        models = [a['baseline'], b['baseline'], v['baseline'], b['candidate']]
        period_rows.append('<tr><th>'+ltr(name)+'</th><td>'+str(models[-1]['true_events'])+'</td><td>'
            +quadruple([m['confirmed_events'] for m in models])+'</td><td>'
            +quadruple([m['false_positive_runs'] for m in models])+'</td><td>'
            +quadruple([number(m['fp_duration_seconds']/60) for m in models])+'</td><td>'+pct(models[-1]['f1_observed_points'])
            +'</td><td>'+ltr(f"IF {a['noninferior']} | V6 {b['noninferior']} | V8 {v['noninferior_with_120s_limit']}")+'</td></tr>')
        retention_rows.append('<tr><th>'+ltr(name)+'</th><td>'+compare_text(a,b,v,'lost_baseline_event_ids')+'</td><td>'
            +ltr(' | '.join(f'{label} {number(maximum_delay(c))} s' for label,c in (('IF',a),('V6',b),('V8',v))))
            +'</td><td>'+compare_text(a,b,v,'lost_positive_alarm_rows')+'</td></tr>')
        cov = p['conditional_block_test_coverage']; denom = cov['reference_available_rows']; count = cov['observed_on_reference_available_rows']
        support = audit.get('conditional_audit_by_case', {}).get(name, {}).get('supported')
        support_text = 'غير متاح' if support is None else ('مدعوم' if support else 'غير مدعوم')
        coverage_rows.append('<tr><th>'+ltr(name)+'</th><td>'+support_text+'</td><td>'+str(count)+' من '+str(denom)
            +'</td><td>'+pct(count/denom if denom else None)+'</td><td>'+str(cov['current_observed_rows_after_gap'])+'</td></tr>')
        selected = p['selected']
        policy_rows.append('<tr><th>'+ltr(name)+'</th><td>'+ltr(selected['status'])+'</td><td>'
            +ltr(number(selected['confirmation_delay_seconds'])+' s')+'</td><td>'
            +esc('؛ '.join(selected.get('certification_rejection_reasons', [])) or '—')+'</td></tr>')
    source_html = []
    for source, comp in result['sources'].items():
        a,b = comp['if_vs_v7'],comp['v6_vs_v7']; v=diagnosis['cross_run_source_comparison'][source]
        if v['baseline'] != previous['sources'][source]['v6_vs_v7']['candidate'] or v['candidate'] != b['candidate']:
            raise ValueError('Source comparison must retain its original connected axis')
        source_html.append('<h3>'+ltr(source)+'</h3><table>'+METRIC_HEAD+'<tbody>'
            +model_rows(a['baseline'],b['baseline'],v['baseline'],b['candidate'])+'</tbody></table><p>المعرّفات المفقودة: '
            +compare_text(a,b,v,'lost_baseline_event_ids')+'. أقصى تأخير إضافي: '
            +ltr(' | '.join(f'{label} {number(maximum_delay(c))} s' for label,c in (('IF',a),('V6',b),('V8',v))))
            +'. عدم التراجع: '+ltr(f"IF {a['noninferior']} | V6 {b['noninferior']} | V8 {v['noninferior_with_120s_limit']}")+'</p>')
    checks_html = ''.join('<h3>'+esc(label)+'</h3><ul class="checks">'+''.join(
        f'<li class="{"ok" if passed else "bad"}">{esc(key)}: {"PASS" if passed else "FAIL"}</li>'
        for key,passed in summary[pair]['checks'].items())+'</ul>'
        for pair,label in (('if_vs_v7','V9 مقابل IF'),('v6_vs_v7','V9 مقابل V6')))
    timing_rows = []
    for event in diagnosis['timing_comparison']:
        versions = []
        for version in ('v8','v9'):
            data=event[version]; confirmed=data['confirmed_index']
            versions.append('مكتشف' if confirmed is not None else 'غير مكتشف')
        flags = event['v9']['descriptive_cause_flags']
        observed = []
        if flags['no_candidate_alarm_inside_event']: observed.append('لا إنذار داخل الحدث')
        if flags['alarm_inside_event_but_no_qualified_quiet_to_alarm_transition']: observed.append('تغطية دون انتقال اكتشاف مؤهل')
        if flags['some_short_reference_pulse_removed']: observed.append('أزيلت نبضة مرجعية قصيرة')
        score_text, crossing_text = [], []
        for version in ('v8','v9'):
            data=event[version]; pulses=data['reference_pulses']
            values=[p['confidence_first_values_including_after_pulse'][0] for p in pulses]
            scores=' / '.join(number(value) for value in values) if values else 'no reference pulse'
            score_text.append(version.upper()+' '+scores+'; low '+number(data['fixed_low_threshold']))
            crossings=[p['first_raw_confidence_crossing_seconds_before_event_end'] for p in pulses]
            crossing_text.append(version.upper()+' '+(' / '.join(number(value)+' s' for value in crossings) if pulses else 'no reference pulse'))
        timing_rows.append('<tr><th>'+ltr(event['case'])+'</th><td>'+str(event['event_id'])+'</td><td>'
            +esc(versions[0])+'</td><td>'+esc(versions[1])+'</td><td>'+ltr(' | '.join(score_text))
            +'</td><td>'+ltr(' | '.join(crossing_text))+'</td><td>'+esc('؛ '.join(observed) or 'راجع الدرجات المحفوظة')+'</td></tr>')
    if not timing_rows:
        timing_rows.append('<tr><td colspan="7">لم تتغير معرّفات الاكتشاف بين V8 وV9، ولم يسجل أي منهما فقدًا مقابل V6 في هذه الفترات.</td></tr>')
    early_html=''; early_info=None
    early_path=run/'early_confidence_followup.json'
    if early_path.is_file():
        early=read(early_path)
        if (early.get('candidate_version') != 'V9' or early.get('status') != 'descriptive_post_test_onset_comparison_only'
                or any(early.get(key) is not False for key in ('fresh_validation','new_source_accessed','model_refitted','thresholds_changed'))
                or early.get('input_sha256',{}).get(str(run/'results.json')) != sha(run/'results.json')
                or early.get('input_sha256',{}).get(str(prior_run/'results.json')) != sha(prior_run/'results.json')):
            raise ValueError('Early-score followup must match the unchanged paired runs')
        for path,digest in early['input_sha256'].items():
            if sha(Path(path)) != digest: raise ValueError('Early-score diagnostic input changed')
        raw=early['period_local_aggregate_first_onset_score_change']
        rank=early['period_local_aggregate_first_onset_normal_percentile_change']
        early_html=(f'<p>عند {raw["count"]} بداية حدث مؤهلة للمقارنة، ارتفعت الدرجة الخام في {raw["increased"]} '
            f'وانخفضت في {raw["decreased"]}. لكن ترتيب البداية مقارنة بقراءات كل نموذج الطبيعية تحسن في {rank["increased"]} '
            f'وتراجع في {rank["decreased"]}؛ وسيط فرق الترتيب {number(rank["median_change"])}. '
            'ارتفاع الدرجة وحده لا يثبت تحسن الفصل. هذه أوصاف بعد الاختبار تستخدم بدايات الفترات، وليست عدد أحداث المصادر المجمعة أو عتبات جديدة. '
            +link(early_path,destination,'مقارنة الثقة المبكرة وحدودها')+'</p>')
        early_info={'path':str(early_path),'sha256':sha(early_path),'raw_onset_change':raw,'normal_percentile_change':rank}
    public_html = 'لم تُستخدم قياسات مصدر جديد في هذه التجربة. يحتاج التحقق الخارجي إلى بيانات لم تدخل قرارات التطوير، بوسوم مستقلة وترتيب زمني وتواتر مناسبين.'
    if public_search is not None and public_search.is_file():
        public_html += ' '+link(public_search,destination,'مراجعة المصادر العامة السابقة وحدود التأهيل')
    paired_noninferior = sum(v['noninferior_with_120s_limit'] for v in paired_periods.values())
    status = {'generated_at_utc':datetime.now(timezone.utc).isoformat(),'candidate':'V9','run':str(run),
        'phase':'development_pass_needs_fresh_validation' if accepted else 'development_failed',
        'complete_cases':19,'independent_replay_audit_passed':True,'replay_audit_proves_model_acceptance':False,
        'passes_declared_development_gate':bool(accepted),'fresh_external_validation_performed':False,
        'deployment_approved':False,'three_d_connected':False,
        'prototype_software_readiness':'Separate assessment; this report does not establish persistent-stream operation or RaspberryPi latency.',
        'summary':summary,'v8_candidate':old,'v8_vs_v9_noninferior_periods_descriptive':paired_noninferior,
        'lost_events_by_period':losses,'maximum_paired_extra_delay_seconds':delays,
        'policy_status_counts':dict(Counter(p['selected']['status'] for p in periods)),
        'conditional_coverage_by_period':[{'case':p['case'],**p['conditional_block_test_coverage']} for p in periods],
        'cross_run_source_comparison':diagnosis['cross_run_source_comparison'],
        'artifact_hashes':{'results.json':sha(run/'results.json'),'plan.json':sha(run/'plan.json'),
                          'audit':sha(audit_path),'diagnosis':sha(diagnosis_path),'v8_results':sha(prior_run/'results.json')},
        'post_test_diagnosis':str(diagnosis_path),'early_confidence_followup':early_info,'report':str(destination)}
    doc=f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — تقييم V9</title>
<style>body{{margin:0;background:#f1f5f5;color:#18333c;font:17px/1.75 system-ui,sans-serif}}main{{max-width:1600px;margin:auto;padding:28px 22px}}header{{background:#073f49;color:white;border-radius:16px;padding:28px}}h1{{font-size:30px}}h2{{font-size:23px}}section{{background:white;border-radius:14px;padding:22px;margin:20px 0;overflow-x:auto}}.notice{{background:#fff1d6;border-right:5px solid #ae740e;padding:18px;margin:20px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{text-align:right;vertical-align:top;border-bottom:1px solid #dce5e6;padding:10px;white-space:nowrap}}thead{{background:#e8f1f2}}a{{color:#086b72}}.ltr{{unicode-bidi:isolate;direction:ltr;display:inline-block}}.checks{{direction:ltr;text-align:left;font:14px/1.8 monospace}}.ok{{color:#166044}}.bad{{color:#a02c24}}.muted{{color:#52666d}}details summary{{cursor:pointer;font-weight:bold}}</style>
<main><header><div>مورد · كشف الشذوذ · {ltr(run.name)}</div><h1>{heading}</h1><p>19 فترة مكتملة مع تدقيق مستقل مطابق. لم يُربط النموذج بالـ3D أو بالصمام.</p></header>
<div class="notice"><strong>نتائج تطوير على بيانات سبق كشفها.</strong> التدريب والمعايرة داخل كل تقسيم يسبقان الاختبار زمنيًا، لكن تصميم هذه المحاولة استفاد من نتائج المحاولات السابقة. التدقيق المستقل للحسابات لا يجعل البيانات اختبارًا خارجيًا جديدًا.</div>
<section><h2>المقارنة الفعلية على المحور نفسه</h2><table>{METRIC_HEAD}<tbody>{model_rows(first,reference,old,candidate)}</tbody></table><p>فترات عدم التراجع: مقابل V6 {summary['v6_vs_v7']['noninferior_periods']} من 19؛ مقابل IF {summary['if_vs_v7']['noninferior_periods']} من 19. المقارنة الوصفية مقابل V8: {paired_noninferior} من 19.</p><p>أقصى فرق تأخير مقترن: {ltr('IF '+number(delays['if_vs_v7'])+' s | V6 '+number(delays['v6_vs_v7'])+' s')}. الحد المقبول 120 ثانية. F1 مقياس للقراءات، وليس «دقة سلامة المياه». الكشف الأساسي يتطلب انتقالًا من السكون إلى الإنذار داخل حدث معلوم البداية؛ تغطية دقائق إضافية لا تعوّض فقد حدث.</p></section>
<section><h2>إضافة واحدة إلى V8</h2><p>أضفنا لكل حساس فرق قراءته الحالية عن القيمة المتوقعة من الحساسات الأخرى، وقيمة الفرق المطلقة، وعلامة توفر هذا الدليل. تتعلم علاقة Ridge من قراءات التدريب الطبيعية المعروفة والمكتملة فقط، بإعدادات ثابتة. بقيت الخصائص السابقة وأوزان بداية الحدث وإعدادات HGB والمراجع والمعايرة وسياسة القرار كما هي.</p><p>النموذج يجمع مصنف أحداث يتعلم من الوسوم مع بواقي علاقات تتعلم من الطبيعي فقط؛ درجته ليست احتمال سلامة معايرًا. يشترط الجزء الجديد دعم جميع الحساسات و128 قراءة طبيعية مكتملة على الأقل. الفقد أو الفشل العددي يجعل هذا الجزء غير متاح دون تغيير توفر القرار الأصلي. قد يبدو عطل مترابط بين الحساسات طبيعيًا لهذه العلاقة؛ ويظل التحسن فرضية تختبرها النتائج.</p></section>
<section><h2>شروط القبول</h2><p>الحفاظ على معرّفات كل الأحداث التي اكتشفها IF وV6 وعلى توفر القرار؛ تأخير إضافي مقترن لا يتجاوز 120 ثانية؛ وعدم زيادة عدد مقاطع الإنذار الكاذب أو مدتها في أي فترة أو مصدر. يلزم أيضًا تحسن إجمالي وزيادة أحداث وتقليل مقاطع كاذبة في فترتين على الأقل. مقارنة V8 وصفية ولا تغيّر هذه الشروط.</p><p>مهلة التأكيد قد تزيل قراءات موجبة أولى؛ نعرضها ولا نخفيها. حد مؤقت النبضة المستمرة لا يضمن الاحتفاظ بحدث يعتمد على نبضة قصيرة، لذلك نقيس فقد الحدث وتأخيره الفعلي بشكل منفصل.</p>{checks_html}</section>
<section><h2>الفترات التسع عشرة</h2><table><thead><tr><th>الفترة</th><th>الأحداث الحقيقية</th><th>الأحداث المكتشفة</th><th>مقاطع كاذبة</th><th>دقائق كاذبة</th><th>F1 لـV9</th><th>عدم التراجع</th></tr></thead><tbody>{''.join(period_rows)}</tbody></table></section>
<section><h2>كل الأحداث المفقودة والتكلفة الزمنية</h2><p>المعرّفات هنا تخص محور كل فترة. الحدث المفقود لا يدخل التأخير المقترن؛ لا يمكن استعمال تأخير منخفض لإخفاء فقده. عمود القراءات الموجبة وصفٌ لحذف تنبيهات موجبة، لا شرط قبول إضافي.</p><table><thead><tr><th>الفترة</th><th>معرّفات مفقودة</th><th>أقصى تأخير مقترن</th><th>قراءات تنبيه موجبة أزيلت</th></tr></thead><tbody>{''.join(retention_rows)}</tbody></table></section>
<section><h2>المصادر على محاورها المتصلة</h2><p>تُحسب محاور المصادر قبل الجمع كي لا نكرر حدثًا أو مقطع إنذار يعبر حدود الفترات.</p>{''.join(source_html)}</section>
<section><h2>توفر الخصائص الجديدة</h2><p>هذه تغطية دليل إضافي وليست نسبة دقة أو تغييرًا لمقام الأحداث. النسبة محسوبة فقط بين الصفوف التي كان قرار V6 متاحًا فيها؛ العمود الأخير يحفظ أيضًا كامل توفر الجزء الجديد بعد فجوة البداية.</p><table><thead><tr><th>الفترة</th><th>دعم العلاقة أثناء التدريب</th><th>صفوف الدليل / الصفوف المرجعية المتاحة</th><th>النسبة</th><th>كل صفوف الدليل بعد الفجوة</th></tr></thead><tbody>{''.join(coverage_rows)}</tbody></table></section>
<section><h2>تشخيص التوقيت مقارنة بـV8</h2><p>يعرض التشخيص الدرجات عند العتبات المثبتة لكل إصدار، وطول النبضات المرجعية وتوفر الخصائص. لا يختار عتبة بعد الاختبار ولا يعيد التدريب. يحفظ جميع حالات الرجوع للمرجع، ويحلل الاختيار المبكر والشهادة اللاحقة والاختبار للسياسات النشطة. التغير في توقيت الثقة وصفٌ للنتيجة وليس إثباتًا منفردًا لسببها. بلوغ العتبة بعد انتهاء النبضة ليس إنذارًا منفذًا؛ اختلاف العتبات بين الإصدارين يمنع نسبة كل تغير في التوقيت إلى الخصائص وحدها.</p>{early_html}<details><summary>الأحداث المتغيرة أو المفقودة</summary><table><thead><tr><th>الفترة</th><th>معرّف الحدث</th><th>V8</th><th>V9</th><th>درجة بداية كل نبضة مرجعية وعتبتها</th><th>أول بلوغ للعتبة بعد كل نبضة</th><th>ملاحظة من السجل</th></tr></thead><tbody>{''.join(timing_rows)}</tbody></table></details><p>{link(diagnosis_path,destination,'التشخيص الكامل وبصمات المقارنة')} · {link(prior_run/'results.json',destination,'نتائج V8 المحفوظة')} · {link(ROOT/'output/ml/gecco-v8/report.html',destination,'تقرير V8 السابق')} · {link(ROOT/'output/ml/gecco-v7-development/run_04/results.json',destination,'أرشيف V7 run04')}</p></section>
<section><h2>الاختيار الزمني والرجوع للمرجع</h2><p>تختار أول كتلتين ماضيتين وصفة واحدة، وتفحصها الكتلتان اللاحقتان دون إعادة ضبط. أي إخفاق يعيد V6 كاملًا. نفحص التأكيد وحده والقرار المركب أيضًا على الكتل الأربع معًا. هذه شهادة للسياسة الإضافية مشروطة بمرجع V6 الذي اختير سابقًا بكل الكتل الأربع؛ ليست عينة مستقلة عن المنظومة كاملة.</p><details><summary>كل الحالات وأسبابها</summary><table><thead><tr><th>الفترة</th><th>الحالة</th><th>مهلة التأكيد</th><th>أسباب الرفض</th></tr></thead><tbody>{''.join(policy_rows)}</tbody></table></details></section>
<section><h2>التدقيق وجاهزية البرنامج</h2><p>أعاد المدقق المستقل حساب {audit_count(audit,'replayed_rows')} صف اختبار و{audit_count(audit,'calibration_sensor_rows_replayed')} صف معايرة، وفحص مراجع التدريب وأوزان البداية وعلاقات Ridge والسمات والأقنعة والمقارنات. اجتياز هذا التدقيق يثبت الحسابات التي فُحصت؛ قبول أداء النموذج قرار منفصل. تشغيل نموذج برمجي مبسط كذلك لا يعني قبولًا إحصائيًا أو جاهزية ميدانية.</p><p>هذا التقرير يعتمد إعادة تشغيل بدفعات؛ لا يثبت زمن الاستجابة على Raspberry Pi أو تشغيلًا مستمرًا لحساس فعلي. {link(audit_path,destination,'سجل التدقيق')} · {link(run/'plan.json',destination,'الخطة المثبتة')} · {link(run/'results.json',destination,'جميع النتائج')}</p></section>
<section><h2>حدود الاستخدام</h2><p>{public_html}</p><p>لا تثبت التجارب تصنيف الأنواع الخمسة لأعطال الحساسات، أو صلاحية مياه الوضوء، أو سلامة مياه بعينها. لا توجد صلاحية لفتح الصمام، ولم تُدمج المحاولة مع المحاكاة.</p></section>
<footer class="muted">اكتملت التجربة {ltr(result['completed_at_utc'])}. تبقى جميع المحاولات السابقة وإخفاقاتها محفوظة.</footer></main></html>'''
    return doc,status


def build(run, destination, *, status_path=None, prior_run=None, public_search=None):
    run,destination = Path(run).resolve(),Path(destination).resolve()
    prior_run = Path(prior_run).resolve() if prior_run else ROOT/'output/ml/gecco-v8-development/run_01'
    public_search = Path(public_search).resolve() if public_search else ROOT/'output/ml/gecco-v8-source-search/public_only_followup_v2.json'
    result,audit_path,audit = load_verified(run)
    previous,_,_ = load_v8_verified(prior_run)
    diagnosis_path,diagnosis = load_diagnosis(run,prior_run,result)
    doc,status = render(run,destination,result,audit_path,audit,prior_run,previous,diagnosis_path,diagnosis,public_search)
    encoded = json.dumps(status,indent=2,allow_nan=False)+'\n'
    status_path = Path(status_path).resolve() if status_path else destination.parent/'status.json'
    protected = {run/'results.json',run/'plan.json',audit_path,diagnosis_path,prior_run/'results.json',prior_run/'plan.json',
                 ROOT/'output/ml/gecco-v8/report.html',ROOT/'output/ml/gecco-v8/status.json',ROOT/'output/ml/gecco-v7/report.html'}
    if destination in protected or status_path in protected or destination == status_path:
        raise ValueError('Report outputs must be new V9 artifacts and preserve historical artifacts')
    destination.parent.mkdir(parents=True,exist_ok=True); status_path.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(doc); status_path.write_text(encoded)
    return status


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--status',type=Path); parser.add_argument('--previous',type=Path)
    args=parser.parse_args()
    status=build(args.run,args.output,status_path=args.status,prior_run=args.previous)
    print(json.dumps({k:status[k] for k in ('phase','complete_cases','passes_declared_development_gate','report')}))
