"""Build a modest Arabic RTL report from completed result artifacts.

Default invocation reads disclosed development only. --include-ponds is an
explicit operator action after the root declares all fresh results ready;
without it no fresh path is opened, tested for existence or enumerated.
--include-reserved additionally requires --include-ponds and an explicit root
declaration that all312 extension periods are ready. It never auto-discovers
partial results. The extension remains separate from the four primary cohorts.
Importing this module performs no filesystem reads. It never imports a runner,
fits a model, accesses raw measurements or changes any frozen artifact.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from html import escape
import io
import json
import math
import os
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]


def h(value):
    return escape(str(value), quote=True)


def number(value, digits=0):
    if value is None:
        return 'غير متاح'
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Report metrics must be finite numbers or null')
    return f'{value:,.{digits}f}'


def numeric(value, digits=0):
    return f'<bdi class="numeric">{number(value, digits)}</bdi>'


def pair(a, b, digits=0):
    return f'<bdi class="numeric">{number(a, digits)} → {number(b, digits)}</bdi>'


def event_count(metrics):
    return (f'<bdi class="numeric">{number(metrics["confirmed_new_alarm_inside_events"])}'
            f' / {number(metrics["true_events"])}</bdi>')


def percent(value):
    return None if value is None else value * 100


def label(text, kind='neutral'):
    return f'<span class="badge {kind}">{h(text)}</span>'


def link(text, target):
    return f'<a href="{h(target)}">{h(text)}</a>'


def comparison_table(rows, caption, include_status=True):
    """Rows are (display name, compare_period-compatible metrics)."""
    body = []
    for name, row in rows:
        b, c = row['baseline'], row['candidate']
        lost = len(row['lost_baseline_events'])
        qualified = row.get('baseline_calibration_qualified', True)
        status = (label('غير قابل للتقييم', 'warn') if not row['normal_exposure_measurable'] else
                  label('حفظ المقارنة', 'ok') if row['noninferior'] else label('تراجع', 'bad'))
        if not qualified:
            status += ' ' + label('معايرة غير مؤهلة', 'warn')
        body.append('<tr><th scope="row">' + h(name) + '</th>'
                    + '<td>' + event_count(b) + '</td><td>' + event_count(c) + '</td>'
                    + '<td>' + pair(b['false_positive_runs'], c['false_positive_runs']) + '</td>'
                    + '<td>' + pair(b['false_alarm_runs_per_normal_day'], c['false_alarm_runs_per_normal_day'], 3) + '</td>'
                    + '<td>' + pair(b['normal_alarm_minutes'], c['normal_alarm_minutes'], 1) + '</td>'
                    + '<td>' + pair(percent(b['normal_time_under_alarm']), percent(c['normal_time_under_alarm']), 3) + '%</td>'
                    + '<td>' + numeric(lost) + '</td>'
                    + ('<td>' + status + '</td>' if include_status else '') + '</tr>')
    return ('<div class="table-wrap"><table><caption>' + h(caption) + '</caption>'
            '<thead><tr><th>المجموعة / الفترة</th><th>أحداث IF</th><th>أحداث q50</th>'
            '<th>إنذارات كاذبة<br>IF → q50</th><th>إنذارات / يوم<br>IF → q50</th>'
            '<th>دقائق الإنذار الكاذب<br>IF → q50</th><th>الوقت الطبيعي تحت الإنذار<br>IF → q50</th>'
            '<th>أحداث IF المفقودة</th>' + ('<th>المقارنة</th>' if include_status else '')
            + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>')


def overall_row(name, aggregate):
    b, c = aggregate['totals']['baseline'], aggregate['totals']['candidate']
    return ('<tr><th scope="row">' + h(name) + '</th><td>' + event_count(c) + '</td>'
            '<td>' + pair(b['false_positive_runs'], c['false_positive_runs']) + '</td>'
            '<td>' + pair(b['normal_alarm_minutes'], c['normal_alarm_minutes'], 0) + '</td>'
            '<td>' + numeric(aggregate['lost_baseline_events']) + '</td></tr>')


def fresh_section(fresh, refs):
    if fresh is None:
        return ('<section id="external"><div class="section-title"><span class="eyebrow">الفحص الجديد</span>'
                '<h2>النتيجة غير مدرجة</h2></div><p>هذا العرض مبني على التطوير المكشوف فقط. '
                'لم يقرأ مولّد هذا العرض ملفات نتائج الاختبار الجديد. تُضاف النتائج بعد اكتمال '
                'الفترات الأربع والعشرين وإعلان جاهزيتها، دون إعادة اختيار الطريقة بناءً عليها.</p></section>')
    if fresh.get('completed_cases') != 24 or len(fresh.get('periods', [])) != 24:
        raise ValueError('Refusing to report partial Ponds evaluation; all 24 periods are required')
    if len(fresh.get('sources', {})) != 4:
        raise ValueError('Expected four predeclared Ponds cohorts')
    gate = fresh['overall']
    expected = bool(gate['stable_joint_improvement'] and fresh['sufficient_evidence'])
    if fresh['primary_acceptance_passed'] is not expected:
        raise ValueError('Acceptance flag disagrees with stability and evidence fields')
    if expected:
        headline = 'اجتاز معيار هذا الاختبار المحدد'
        verdict = ('حافظ على كل أحداث IF وتوافره في الفترات المقاسة، مع خفض إجمالي للإنذارات '
                   'الكاذبة واستيفاء الحد الأدنى للدليل. يظل الاستنتاج محصورًا في هذه البيانات والوسوم.')
        badge = label('اجتياز محدود بنطاق الاختبار', 'ok')
    else:
        headline = 'لم يجتز معيار القبول المحدد'
        reasons = []
        if gate['lost_baseline_events']:
            reasons.append('فقد أحداثًا كان IF قد اكتشفها')
        if gate['hidden_baseline_observed_rows']:
            reasons.append('أخفى بعض الصفوف التي كان IF قادرًا على تقييمها')
        if not gate['stable_joint_improvement']:
            reasons.append('لم يتحقق الخفض الإجمالي الصارم للإنذارات الكاذبة رغم عدم التراجع في الفترات'
                           if all(gate['noninferior_periods']) else
                           'لم يتحقق شرط عدم التراجع في جميع الفترات مع خفض إجمالي صارم للإنذارات الكاذبة')
        if not fresh['sufficient_evidence']:
            reasons.append('لم يكتمل الحد الأدنى للدليل أو تأهيل المعايرة')
        verdict = '؛ '.join(reasons) + '. تُحفظ هذه النتيجة كما هي؛ أي تعديل لاحق يجعل هذه البيانات جزءًا من التطوير.'
        badge = label('لا يجيز الانتقال إلى الاستخدام الميداني', 'bad')
    b, c = gate['totals']['baseline'], gate['totals']['candidate']
    evidence = fresh['evidence']
    cards = ('<div class="cards"><article><span>الأحداث المؤكدة: IF / q50</span><strong>'
             + event_count(b) + ' / ' + event_count(c) + '</strong></article><article><span>الإنذارات الكاذبة</span>'
             '<strong>' + pair(b['false_positive_runs'], c['false_positive_runs']) + '</strong></article>'
             '<article><span>أحداث IF المفقودة</span><strong>' + numeric(gate['lost_baseline_events'])
             + '</strong></article><article><span>F1 على مستوى العينات: IF → q50</span><strong>'
             + pair(b['f1'], c['f1'], 4) + '</strong></article></div>')
    cohorts = [(name, item['pooled']) for name, item in fresh['sources'].items()]
    periods = [(item['case'], item) for item in fresh['periods']]
    qualified = evidence['all_baseline_calibrations_qualified']
    decisions = Counter(item['selection_decision'] for item in fresh['periods'])
    unqualified = sum(not item['baseline_calibration_qualified'] for item in fresh['periods'])
    identity_note = ''
    if decisions['baseline'] == 24:
        identity_note = ('<p>رجعت الطريقة إلى IF في الفترات الأربع والعشرين، فتطابقت النتيجة معه. '
                         'لم تنخفض الإنذارات الكاذبة: ' + pair(b['false_positive_runs'], c['false_positive_runs']) + '.</p>')
    if b['true_events'] == 1:
        identity_note += ('<p>رُصد حدث موسوم واحد فقط. نتيجة ' + event_count(c)
                          + ' لا تقدّر موثوقية الكشف بصورة مستقرة، حتى عندما يُكتشف الحدث الوحيد.</p>')
    identity_note += ('<p class="small">على مستوى العينات، أصاب المرشح ' + numeric(c['tp'])
                      + ' من ' + numeric(c['tp'] + c['fn']) + ' عينة حدث متاحة للتقييم. '
                      'وجود بداية إنذار داخل حدث لا يعني تغطية جميع عيناته؛ لذلك يُعرض F1 إلى جانب عدد الأحداث.</p>')
    artifacts = [link('البروتوكول المجمد', refs['fresh_protocol']),
                 link('سجل أول وصول', refs['fresh_access']),
                 link('النتائج الكاملة', refs['fresh_results']),
                 link('مجلد حزم النماذج وملفات الفترات', refs['fresh_models'])]
    if refs.get('fresh_audit'):
        artifacts.append(link('تدقيق الاختبار الجديد', refs['fresh_audit']))
    return ('<section id="external"><div class="section-title"><span class="eyebrow">Ponds · 24 فترة</span>'
            '<h2>' + headline + '</h2></div>' + badge + '<p>' + h(verdict) + '</p>' + cards
            + '<p class="small">الدليل: ' + numeric(evidence['baseline_detected_events']) + ' أحداث اكتشفها IF، عبر '
            + numeric(evidence['eventful_cohorts']) + ' مجموعات و' + numeric(evidence['eventful_periods'])
            + ' فترات ذات أحداث. جميع معايرات IF مؤهلة: ' + ('نعم' if qualified else 'لا') + '.</p>'
            + '<p class="small">الرجوع إلى IF: ' + numeric(decisions['baseline']) + ' من 24 فترة؛ '
            + 'بوابة المرشح مفعّلة في ' + numeric(decisions['candidate']) + '؛ معايرة IF غير مؤهلة في '
            + numeric(unqualified) + ' فترة. جميعها باقية في العرض والمقامات.</p>'
            + identity_note
            + comparison_table(cohorts, 'النتيجة على المحور الأصلي لكل مجموعة؛ الأحداث العابرة للفترات لا تُضاعف')
            + '<details open><summary>تفصيل الفترات الأربع والعشرين</summary>'
            + comparison_table(periods, 'كل فترة تحتفظ بوسومها الأصلية والمفقود وفاصل البداية') + '</details>'
            + '<p class="small">«حفظ المقارنة» يعني عدم فقد حدث من IF أو توافره، وعدم زيادة المعدل أو مدة الإنذار الكاذب '
            'في تلك الفترة؛ لا يعني تحسنًا صارمًا في كل فترة. تشترك المجموعات الأربع في تجربة أحواض واحدة.</p>'
            + '<p class="artifact-links">' + ' · '.join(artifacts) + '</p>'
            + '<p class="small">بصمة البروتوكول: <bdi class="hash">' + h(fresh['protocol_sha256'])
            + '</bdi></p></section>')


def reserved_groups(result):
    """Validate the declared extension dimensions using supplied objects only."""
    periods, sources = result.get('periods', []), result.get('sources', {})
    if result.get('completed_cases') != 312 or len(periods) != 312:
        raise ValueError('Refusing partial reserved evaluation; all312 periods are required')
    if result.get('completed_cohorts') != 52 or len(sources) != 52:
        raise ValueError('Exactly52 completed reserved cohorts are required')
    source_ids = [tuple(item['cohort_identity']) for item in sources.values()]
    if len(set(source_ids)) != 52 or any(len(key) != 5 for key in source_ids):
        raise ValueError('Reserved source identities must be52 unique five-field tuples')
    by_identity = {identity: [] for identity in source_ids}
    case_names = set()
    for period in periods:
        identity = tuple(period['cohort_identity'])
        if identity not in by_identity or period['case'] in case_names:
            raise ValueError('Duplicate period name or undeclared reserved cohort')
        if period['selection_decision'] not in ('baseline', 'candidate'):
            raise ValueError('Unrecognized selection decision; cannot hide an outcome')
        by_identity[identity].append(period)
        case_names.add(period['case'])
    if any(len(rows) != 6 for rows in by_identity.values()):
        raise ValueError('Every reserved cohort must retain all six planned periods')
    phases = sorted({str(identity[-1]) for identity in source_ids})
    if set(result['strata']) != {f'phase_{phase}' for phase in phases}:
        raise ValueError('Phase summaries do not cover every reserved cohort')
    return phases, by_identity


def reserved_periods_csv(result):
    """All312 periods, including fallback/unqualified cases; no data access."""
    reserved_groups(result)
    columns = ['case', 'pond', 'sonde', 'treatment', 'replicate', 'phase',
               'baseline_calibration_qualified', 'selection_decision', 'selection_status',
               'true_events', 'baseline_confirmed_events', 'candidate_confirmed_events',
               'baseline_false_runs', 'candidate_false_runs',
               'baseline_false_runs_per_normal_day', 'candidate_false_runs_per_normal_day',
               'baseline_FP_minutes', 'candidate_FP_minutes',
               'baseline_point_f1', 'candidate_point_f1',
               'baseline_normal_alarm_fraction', 'candidate_normal_alarm_fraction',
               'baseline_valid_rows', 'candidate_valid_rows',
               'lost_baseline_event_ids', 'hidden_baseline_observed_rows',
               'normal_exposure_measurable', 'unmeasurable_period', 'noninferior', 'max_extra_delay_minutes']
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(columns)
    for period in result['periods']:
        b, c = period['baseline'], period['candidate']
        delays = [item['extra_delay_minutes'] for item in period['paired_detection_delays']]
        values = [period['case'], *period['cohort_identity'],
                  period['baseline_calibration_qualified'], period['selection_decision'], period['selection_status'],
                  b['true_events'], b['confirmed_new_alarm_inside_events'], c['confirmed_new_alarm_inside_events'],
                  b['false_positive_runs'], c['false_positive_runs'],
                  b['false_alarm_runs_per_normal_day'], c['false_alarm_runs_per_normal_day'],
                  b['normal_alarm_minutes'], c['normal_alarm_minutes'],
                  b['f1'], c['f1'],
                  b['normal_time_under_alarm'], c['normal_time_under_alarm'],
                  b['valid_count'], c['valid_count'],
                  json.dumps([item['event_id'] for item in period['lost_baseline_events']]),
                  period['baseline_observed_rows_hidden_by_candidate'], period['normal_exposure_measurable'],
                  not period['normal_exposure_measurable'],
                  period['noninferior'], max(delays) if delays else None]
        # Keep identifiers safe if opened in a spreadsheet. Numeric metric
        # values remain numeric; no negative number is converted into a string.
        values = ["'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r'))
                  else value for value in values]
        writer.writerow(values)
    return stream.getvalue()


def reserved_section(result, refs):
    if result is None:
        return ''
    phases, by_identity = reserved_groups(result)
    gate = result['overall']
    expected = bool(gate['stable_joint_improvement'] and result['sufficient_evidence'])
    if result['primary_acceptance_passed'] is not expected:
        raise ValueError('Reserved acceptance flag disagrees with stability/evidence')
    periods = result['periods']
    decisions = Counter(period['selection_decision'] for period in periods)
    qualified = sum(period['baseline_calibration_qualified'] for period in periods)
    unmeasurable = sum(not period['normal_exposure_measurable'] for period in periods)
    improved = sum(period['candidate']['false_positive_runs'] < period['baseline']['false_positive_runs'] for period in periods)
    noninferior = sum(period['noninferior'] for period in periods)
    verdict = ('اجتاز معيار التوسعة المحدد' if expected else 'لم يجتز معيار التوسعة المحدد')
    status = label('استنتاج داخل التجربة نفسها فقط', 'ok') if expected else label('نتيجة غير مجتازة محفوظة', 'bad')
    b, c = gate['totals']['baseline'], gate['totals']['candidate']
    summary = ('<p>حُفظت الفترات كلها، بما فيها ' + numeric(312 - qualified) + ' ذات معايرة IF غير مؤهلة. '
               'رجعت الطريقة إلى IF في ' + numeric(decisions['baseline']) + ' من 312 فترة ('
               + numeric(100 * decisions['baseline'] / 312, 1) + '%)، وفُعّلت بوابة المرشح في '
               + numeric(decisions['candidate']) + '. عدد الفترات التي لم تتراجع: ' + numeric(noninferior)
               + '؛ غير القابلة للتقييم لغياب زمن طبيعي مرصود مؤهل: ' + numeric(unmeasurable)
               + '؛ والفترات التي انخفض فيها عدد الإنذارات الكاذبة فعليًا: ' + numeric(improved) + '.</p>'
               '<p class="small">غياب التعرض الطبيعي الكافي لا يثبت تدهور الأداء، لكنه لا يسمح باعتبار الفترة '
               'نجاحًا. تبقى هذه الفترات في شرط القبول المجمد وفي ملف الفترات الكامل.</p>')
    if decisions['baseline'] == 312:
        summary += ('<p><strong>لم تتفعّل بوابة المرشح في أي فترة.</strong> بقيت النتيجة عند IF: '
                    + pair(b['false_positive_runs'], c['false_positive_runs']) + ' إنذارًا كاذبًا. '
                    'لا توجد إضافة أداء مثبتة من q50 في هذه التوسعة.</p>')
    summary += ('<p>رغم وجود بداية إنذار في ' + event_count(c) + ' أحداث، أصاب المرشح '
                + numeric(c['tp']) + ' من ' + numeric(c['tp'] + c['fn']) + ' عينة حدث متاحة فقط. '
                'عدد الأحداث القليل واكتشاف بداياتها لا يكفيان للحكم على موثوقية الكشف؛ '
                'F1 على مستوى العينات هو ' + numeric(c['f1'], 6) + '.</p>')
    rows, groups = [], []
    for phase in phases:
        phase_periods = [period for period in periods if str(period['cohort_identity'][-1]) == phase]
        phase_sources = [(name, source) for name, source in result['sources'].items()
                         if str(source['cohort_identity'][-1]) == phase]
        totals = result['strata'][f'phase_{phase}']['totals']
        pb, pc = totals['baseline'], totals['candidate']
        counts = Counter(period['selection_decision'] for period in phase_periods)
        unqualified = sum(not period['baseline_calibration_qualified'] for period in phase_periods)
        phase_unmeasurable = sum(not period['normal_exposure_measurable'] for period in phase_periods)
        rows.append('<tr><th scope="row">' + h(phase) + '</th><td>' + numeric(len(phase_sources))
                    + '</td><td>' + numeric(len(phase_periods)) + '</td><td>' + numeric(unqualified)
                    + '</td><td>' + numeric(phase_unmeasurable)
                    + '</td><td>' + numeric(counts['baseline']) + '</td><td>' + numeric(counts['candidate'])
                    + '</td><td>' + event_count(pb) + '</td><td>' + event_count(pc)
                    + '</td><td>' + pair(pb['false_positive_runs'], pc['false_positive_runs'])
                    + '</td><td>' + pair(pb['normal_alarm_minutes'], pc['normal_alarm_minutes'], 1)
                    + '</td><td>' + pair(pb['f1'], pc['f1'], 4)
                    + '</td><td>' + numeric(result['strata'][f'phase_{phase}']['lost_baseline_events']) + '</td></tr>')
        cohort_rows = []
        for name, source in phase_sources:
            row = dict(source['pooled'])
            row['baseline_calibration_qualified'] = source['baseline_calibrations_qualified']
            cohort_rows.append((name, row))
        reason_counts = Counter(period['selection_status'] for period in phase_periods)
        reasons = ' · '.join(f'<bdi>{h(key)}</bdi>: {numeric(count)}' for key, count in sorted(reason_counts.items()))
        groups.append('<details><summary>المرحلة ' + h(phase) + ' — ' + str(len(phase_sources))
                      + ' مجموعة / ' + str(len(phase_periods)) + ' فترة</summary>'
                      + comparison_table(cohort_rows, 'كل مجموعة على محور أحداثها الأصلي؛ علامة المعايرة تخص جميع فتراتها')
                      + '<p class="small">أسباب قرار المعايرة عبر جميع فترات المرحلة: ' + reasons + '</p></details>')
    phase_table = ('<div class="table-wrap"><table><caption>كل مرحلة كما خُططت؛ لا تُحذف فترات المعايرة غير المؤهلة</caption>'
                   '<thead><tr><th>المرحلة</th><th>المجموعات</th><th>الفترات</th><th>معايرة غير مؤهلة</th><th>غير قابل للتقييم</th>'
                   '<th>رجوع إلى IF</th><th>بوابة مفعّلة</th><th>أحداث IF</th><th>أحداث q50</th>'
                   '<th>إنذارات كاذبة<br>IF → q50</th><th>دقائق الإنذار الكاذب<br>IF → q50</th>'
                   '<th>F1 للعينات<br>IF → q50</th>'
                   '<th>أحداث IF المفقودة</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
    repair_links = [link('سجل توقف المحاولة الأصلية', refs['reserved_failure'])]
    if refs.get('reserved_replay_audit'):
        repair_links.append(link('تدقيق مطابقة التنبؤات بعد الإصلاح', refs['reserved_replay_audit']))
    repair_note = ('<aside class="scope small"><strong>إصلاح تشغيلي موثق.</strong> توقفت المحاولة الأصلية '
                   'قبل اكتمال 312 فترة عند تجميع حدود فترة خالية تمامًا من الملاحظات الأصلية. '
                   'أُعيد التشغيل بعد إصلاح التعامل مع هذه الحالة؛ تُحفظ الفترة الخالية كفترة غير قابلة '
                   'للحكم، دون تغيير معيار القبول. يبقى مجلد المحاولة المتوقفة محفوظًا. '
                   'تُوثق مقارنة تنبؤات الفترات الـ210 المكتملة سابقًا بالتنبؤات المعادة في تدقيق منفصل؛ '
                   'لا تُستنتج المطابقة من نجاح التشغيل وحده. '
                   + ' · '.join(repair_links) + '.</aside>')
    return ('<section id="reserved"><div class="section-title"><span class="eyebrow">توسعة Ponds · 52 مجموعة / 312 فترة</span>'
            '<h2>' + verdict + '</h2></div>' + status
            + '<p><strong>هذه توسعة داخل تجربة الأحواض نفسها، وليست مصدرًا مستقلًا ثانيًا.</strong> '
            'تشترك المراحل في أحواض وأجهزة وظروف التجربة؛ لا تمثل 312 عملية نشر مستقلة. '
            'تبقى نتيجة المجموعات الأربع الأولى أعلاه منفصلة ومحفوظة، ولا تستبدلها نتيجة التوسعة أو تدمج بها لإخفاء فشلها.</p>'
            + repair_note +
            '<div class="cards"><article><span>الأحداث المؤكدة: IF / q50</span><strong>' + event_count(b)
            + ' / ' + event_count(c) + '</strong></article><article><span>الإنذارات الكاذبة: IF → q50</span><strong>'
            + pair(b['false_positive_runs'], c['false_positive_runs']) + '</strong></article>'
            '<article><span>دقائق الإنذار الكاذب: IF → q50</span><strong>'
            + pair(b['normal_alarm_minutes'], c['normal_alarm_minutes'], 1) + '</strong></article>'
            '<article><span>F1 على مستوى العينات: IF → q50</span><strong>'
            + pair(b['f1'], c['f1'], 4) + '</strong></article></div>'
            + summary + phase_table + ''.join(groups)
            + '<p><a download href="' + h(refs['reserved_csv']) + '">تنزيل جدول الفترات الـ312 كاملًا بصيغة CSV</a>'
            ' — يتضمن قرار المعايرة، التأهيل، أحداث IF المفقودة، التوافر، مدة الإنذار بالدقائق، والكمون لكل فترة. '
            'لا يقتصر على الفترات الناجحة أو القابلة للتقييم.</p>'
            + '<p class="small">نجاح معيار التوسعة يتطلب عدم التراجع في كل فترة مع خفض إجمالي صارم '
            'للإنذارات الكاذبة، واستيفاء الحد الأدنى للدليل وتأهيل جميع معايرات IF؛ '
            'لا يشترط تحسنًا صارمًا في كل فترة، ولا يكفي ارتفاع المتوسط أو كثرة الفترات.</p>'
            + '<p class="artifact-links">' + ' · '.join([
                link('بروتوكول التوسعة', refs['reserved_protocol']), link('سجل أول وصول للتوسعة', refs['reserved_access']),
                link('كل النتائج الأصلية', refs['reserved_results']), link('التدقيق النهائي للتوسعة', refs['reserved_audit']),
                link('حزم التوسعة وملفات الفترات', refs['reserved_models'])])
            + '</p><p class="small">بصمة بروتوكول التوسعة: <bdi class="hash">'
            + h(result['protocol_sha256']) + '</bdi></p></section>')


def build_document(development, initial, v4_diagnosis, refs, fresh=None, generated_at=None, reserved=None):
    """Pure rendering function; accepts objects already loaded by the caller."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    if reserved is not None and fresh is None:
        raise ValueError('Reserved extension cannot replace or omit the primary Ponds result')
    overall = development['overall']
    q50, q95 = overall['support_q50'], overall['support_q95']
    baseline, candidate = q50['totals']['baseline'], q50['totals']['candidate']
    improved_periods = []
    eventless_improvements = []
    source_rows, period_rows = [], []
    for source, configs in development['sources'].items():
        result = configs['support_q50']
        source_rows.append((f'GECCO {source}', result['pooled']))
        for index, period in enumerate(result['periods'], 1):
            name = f'{source} · الفترة {index}'
            period_rows.append((name, period))
            if period['candidate']['false_positive_runs'] < period['baseline']['false_positive_runs']:
                improved_periods.append(name)
                if not period['baseline']['true_events']:
                    eventless_improvements.append(name)
    gain_text = (f'انخفض عدد الإنذارات الكاذبة في {len(improved_periods)} من {len(period_rows)} فترة؛ '
                 f'منها {len(eventless_improvements)} بلا أحداث موسومة.')
    if improved_periods:
        gain_text += ' الفترات ذات الخفض: ' + '، '.join(improved_periods) + '.'
    q50_status = ('حفظ الحساسية المقاسة مع خفض محدود للإنذارات' if q50['stable_joint_improvement']
                  else 'لم يثبت الحفاظ على الحساسية والتحسن معًا')
    event_recall = (100 * candidate['confirmed_new_alarm_inside_events'] / candidate['true_events']
                    if candidate['true_events'] else None)
    noninferior_count = sum(q50['noninferior_periods'])
    initial_invariant = initial['overall']['shape_invariant']
    v4 = v4_diagnosis['primary_result']
    source_scope = ('بدأ الفحص بأربع سلاسل، ثم توسّع إلى 52 مجموعة كانت غير مستخدمة قبل التوسعة من تجربة أحواض Eawag Ponds نفسها، '
                    if reserved is not None else
                    'الفحص الأول المحدد في البروتوكول يستخدم أربع سلاسل من تجربة أحواض Eawag Ponds، ')
    outcome_note = ''
    if fresh is not None and not fresh['primary_acceptance_passed'] and (reserved is None or not reserved['primary_acceptance_passed']):
        outcome_note = ('<p class="outcome"><strong>الهدف لم يتحقق على Ponds.</strong> '
                        'لم يثبت الاختبار تحسنًا يحقق معيار القبول. لا تعني المحافظة على إنذارات IF أن q50 أضاف كشفًا '
                        'أو خفّض الإنذارات الكاذبة، ولا يجيز هذا التقرير الانتقال إلى الاستخدام الميداني.</p>')
    body = ('<header><span class="eyebrow">مورد · تقييم كشف الشذوذ</span><h1>ما الذي تحسن، وما الذي لم يثبت؟</h1>'
            '<p class="lead">تقرير تجريبي يوازن اكتشاف الأحداث مع عدد الإنذارات الكاذبة ومدتها، '
            'ويحتفظ بنتائج الطرق التي فشلت.</p>' + outcome_note + '<nav aria-label="أقسام التقرير">'
            '<a href="#scope">المصدر والحدود</a><a href="#external">الفحص الأول</a>'
            + ('<a href="#reserved">توسعة التجربة نفسها</a>' if reserved is not None else '') +
            '<a href="#development">التطوير</a><a href="#failures">أسباب الاستبعاد</a>'
            '<a href="#method">المنهج والتوثيق</a></nav></header>'
            '<section id="scope" class="scope"><span class="eyebrow">نطاق الاستنتاج أولًا</span>'
            '<h2>شذوذ ملاحظات التوصيلية الكهربائية، بفاصل 15 دقيقة</h2>'
            '<p>' + source_scope + 'بثماني قنوات. الوسم يدل على وجود قراءة توصيلية في المدخل المنشور حُذفت من نسخة الخبراء المنقحة؛ '
            'لا يغطي جميع الأعطال أو الملوثات. القراءة الأصلية المفقودة تظل هدفًا غير معروف.</p>'
            '<p><strong>معالجة المصدر السابقة غير مكتملة التوثيق.</strong> المدخلات المنشورة سبق أن خضعت لمعالجة، '
            'ولم تُثبت سببيتها كاملةً من الجهاز إلى الملف. التحقق هنا يخص العزل الزمني للطريقة على هذه المدخلات. '
            'النوافذ 15 و60 عينة تعادل 225 و900 دقيقة عند هذا المصدر، وفاصل الفصل 120 دقيقة.</p>'
            '<p>هذه ليست نسبة ثقة بسلامة المياه، ولا إثبات أداء ميداني لمورد أو تصنيف خمسة أعطال فيزيائية. '
            'يُعاد تدريب الطريقة نفسها على الماضي المحلي في كل فترة؛ لا يُختبر نقل أوزان GECCO دون تدريب.</p></section>'
            + fresh_section(fresh, refs)
            + reserved_section(reserved, refs)
            + '<section id="development"><div class="section-title"><span class="eyebrow">GECCO 2017 / 2018 / 2019 · تطوير مكشوف</span>'
            '<h2>' + h(q50_status) + '</h2></div><p>جميع بيانات GECCO التالية أصبحت جزءًا من التطوير، '
            'واستُخدمت لاختيار الوصفة؛ لا تُعرض كاختبار مستقل جديد. مرجع المقارنة هو IF الأصلي، مع نفس التدريب '
            'والدرجات والمعايرة المثبتة.</p><div class="cards"><article><span>الأحداث المؤكدة: IF</span><strong>'
            + event_count(baseline) + '</strong></article><article><span>الأحداث المؤكدة: q50</span><strong>'
            + event_count(candidate) + '</strong><span>استدعاء أحداث: ' + numeric(event_recall, 1)
            + '%؛ ليس مقياس دقة.</span></article><article><span>الإنذارات الكاذبة: IF → q50</span><strong>'
            + pair(baseline['false_positive_runs'], candidate['false_positive_runs']) + '</strong></article></div>'
            '<p>لم تتراجع المقارنة في ' + numeric(noninferior_count) + ' من ' + numeric(len(period_rows))
            + ' فترة. ' + h(gain_text) + ' عدم التراجع لا يعني تحسنًا متكررًا؛ ولا تُفهم النتيجة على أنها خفض ثابت '
            'للإنذارات عبر جميع الظروف.</p>'
            + comparison_table(source_rows, 'ملخص التطوير لكل سنة، على المحور الأصلي')
            + '<details><summary>تفصيل فترات التطوير الثلاث عشرة</summary>'
            + comparison_table(period_rows, 'تفاصيل q50 مقارنة بالمرجع الثابت') + '</details></section>'
            '<section id="failures"><div class="section-title"><span class="eyebrow">النتائج المستبعدة محفوظة</span>'
            '<h2>تقليل الإنذارات لا يكفي إذا ضاعت الأحداث</h2></div>'
            '<div class="table-wrap"><table><caption>المقارنة عبر فترات التطوير نفسها؛ كل رقم لهوية حدث أصلية</caption>'
            '<thead><tr><th>الوصفة</th><th>الأحداث المؤكدة</th><th>الإنذارات الكاذبة<br>IF → المرشح</th>'
            '<th>دقائق الإنذار الكاذب<br>IF → المرشح</th><th>أحداث IF المفقودة</th></tr></thead><tbody>'
            + overall_row('q50 · المرشح المختار من التطوير', q50)
            + overall_row('q95 · مستبعد عند فقد أحداث', q95)
            + overall_row('V5 الأول: shape_invariant · مستبعد', initial_invariant)
            + overall_row('V5 الأول: shape_channel_relative · مستبعد', initial['overall']['shape_channel_relative'])
            + '</tbody></table></div><p>فقد q95 عدد ' + numeric(q95['lost_baseline_events'])
            + ' أحداث من المرجع، وفقد المرشح الأول من V5 عدد ' + numeric(initial_invariant['lost_baseline_events'])
            + '؛ انخفاض الإنذارات عندهما لا يحقق شرط الحفاظ على الحساسية.</p>'
            '<h3>لماذا تراجع V4؟</h3><p>في فحصه التاريخي، وعلى التوافر المشترك المستخدم آنذاك، '
            'اكتشف IF ' + event_count(v4['baseline']) + ' مقابل ' + event_count(v4['v4']) + ' لـV4. '
            'احتوت المعايرة الأولى كتلة كاملة مفقودة، فقادت قاعدة عدم وجود عتبة مؤهلة إلى عتبة صامتة، '
            'وضاعت أحداث الفترة رغم توافر درجاتها. وفي الفترة التالية لم تنتقل عتبة الماضي جيدًا إلى درجات '
            'الأحداث اللاحقة. توثيق هذا الفشل يفسر اعتماد V5 على الاحتفاظ بإنذار IF عند ضعف الدليل أو جهل الشكل.</p>'
            '<p class="small">أرقام V4 التاريخية تخص مقياس التوافر المشترك الخاص به؛ لا تُخلط مباشرةً بأرقام V5 الأصلية أعلاه.</p></section>'
            '<section id="method"><div class="section-title"><span class="eyebrow">كيف تُقرأ الأرقام؟</span>'
            '<h2>الأحداث والوقت والمفقود تبقى في الحساب</h2></div><ul>'
            '<li>الحدث المؤكد يحتاج انتقالًا في التنبؤ من بلا إنذار (0) إلى إنذار (1) داخل حدث موسوم. '
            'هذا وصف لخرج الكاشف، لا إثبات لسلامة الماء قبل الإنذار. بدء إنذار بعد غياب لا يعد انتقالًا مؤكدًا.</li>'
            '<li>مقام الاستدعاء يحتفظ بكل حدث أصلي، بما فيه غير القابل للتقييم وفاصل البداية؛ لا توسيع للوسوم أو تعديل للتنبؤات بأثر رجعي.</li>'
            '<li>«الوقت الطبيعي» في المقاييس هو زمن الصفوف غير الموسومة كأحداث والقابلة للتقييم، وليس إثباتًا لسلامة المياه. '
            'مدة الإنذار مقدّرة من عدد العينات تحت الإنذار × زمن العينة: 15 دقيقة في Ponds ودقيقة في GECCO؛ '
            'لا تثبت العينات مدةً فيزيائية متصلة. الفجوات لا تُملأ ولا تضيف زمنًا إلى هذا المقام.</li>'
            '<li>القيمة 0/0 تعني غياب أحداث موسومة، ولذلك لا يمكن قياس استدعاء الأحداث في تلك الفترة. '
            'شارة عدم التراجع في فترة بلا أحداث لا تثبت حساسية الكشف فيها.</li>'
            '<li>اختيار العتبة وسياسة الإنذار يتم على كتل سابقة فقط. الاختبار اللاحق لا يدخل في اختيار تلك الفترة.</li>'
            '<li>نجاح التدقيق يثبت اتساق الحسابات والبصمات المحددة، ولا يثبت صحة النموذج أو جودة الوسوم أو سلامة المياه.</li></ul>'
            '<p class="artifact-links">' + ' · '.join([
                link('خطة تطوير q50/q95 وبصماتها', refs['development_plan']),
                link('نتائج التطوير', refs['development_results']),
                link('تدقيق المحاولة المدعومة', refs['supported_audit']),
                link('تدقيق V5 الأول', refs['initial_audit']),
                link('تشخيص فشل V4', refs['v4_diagnosis']),
                link('مجلد حزم التطوير', refs['development_models']),
            ]) + '</p><p class="small">في المحاولة الأولى من V5 لم تُحفظ نسخة المعايرة المحمّلة حرفيًا؛ '
            'هذا القيد موثق ولا يُنقل إلى ادعاء قابلية إعادة إنتاج كاملة. في المحاولة المدعومة حُفظت المصادر والحزم، '
            'وطابقت بصمات البيانات الخام مراجعها السابقة ضمن تدقيق لاحق للتشغيل.</p></section>'
            '<footer>تاريخ إنشاء العرض (UTC): <bdi>' + h(generated_at)
            + '</bdi><br>تقرير ثابت من ملفات نتائج محفوظة؛ لا تدريب ولا تحديث للقرارات عند فتحه.</footer>')
    return ('<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="light"><title>مورد — تقرير التقييم V5</title>'
            '<style>' + CSS + '</style></head><body><main>' + body + '</main></body></html>')


CSS = '''
:root{--ink:#172f36;--muted:#546971;--line:#d8e2e4;--paper:#fff;--bg:#f1f5f4;--teal:#17655f;--red:#8e3436;--amber:#805800}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:Tahoma,Arial,sans-serif;line-height:1.9;font-size:16px}
main{max-width:1240px;margin:0 auto;padding:40px 24px}header{padding:22px 0 30px}h1{font-size:clamp(28px,4vw,44px);line-height:1.45;margin:10px 0 12px;font-weight:700;letter-spacing:-.6px}h2{font-size:24px;line-height:1.55;margin:4px 0 16px}h3{font-size:20px;margin:24px 0 6px}p{margin:12px 0;max-width:1030px}.lead{font-size:19px;color:var(--muted)}.outcome{border-inline-start:4px solid var(--red);background:#fff5f4;padding:14px 18px}.eyebrow{color:var(--teal);font-size:13px;font-weight:bold}.small{font-size:13px;color:var(--muted)}nav{display:flex;gap:8px 20px;flex-wrap:wrap;margin-top:24px}a{color:var(--teal);text-decoration:underline;text-underline-offset:4px}a:hover{color:#0b3a37}a:focus-visible,summary:focus-visible{outline:3px solid #d99c16;outline-offset:4px}
section{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:28px;margin:20px 0;scroll-margin-top:20px}.scope{border-inline-start:5px solid #ba8c2d;background:#fffdf7}.section-title{margin-bottom:12px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:22px 0}.cards article{background:#f4f8f7;border:1px solid var(--line);border-radius:10px;padding:17px}.cards span{display:block;font-size:13px;color:var(--muted)}.cards strong{display:block;font-size:26px;font-weight:600;margin-top:6px}.numeric{font-variant-numeric:tabular-nums;white-space:nowrap;direction:ltr;unicode-bidi:isolate}.badge{display:inline-block;border-radius:5px;font-size:12px;padding:2px 9px;font-weight:bold}.ok{color:#205f4f;background:#eaf5ee}.bad{color:var(--red);background:#f9eaea}.warn{color:var(--amber);background:#fff1cb}.neutral{color:var(--muted);background:#eef2f3}
.table-wrap{overflow-x:auto;margin:20px 0;border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;min-width:920px;width:100%;font-size:13px}caption{text-align:right;padding:13px 15px;background:#f5f8f8;color:var(--muted);font-size:13px}th,td{padding:11px 12px;border-bottom:1px solid var(--line);text-align:right;vertical-align:middle}thead th{background:#edf3f3;font-weight:bold;color:#304f57;font-size:12px}tbody th{font-weight:normal}tbody tr:last-child>*{border-bottom:0}tbody tr:nth-child(even){background:#fafcfc}details{margin-top:18px}summary{cursor:pointer;font-weight:bold;color:var(--teal)}ul{padding-inline-start:24px;max-width:1020px}li{margin:9px 0}.artifact-links{font-size:14px;line-height:2.3}.hash{overflow-wrap:anywhere;font-size:11px}footer{font-size:12px;color:var(--muted);padding:18px 4px 30px;border-top:1px solid var(--line)}
@media(max-width:700px){main{padding:20px 12px}section{padding:20px 16px}.cards{grid-template-columns:1fr}.cards strong{font-size:24px}h2{font-size:21px}body{font-size:15px}}
@media print{body{background:white;font-size:11px}main{max-width:none;padding:0}section{break-inside:avoid;border-radius:0;margin:12px 0;padding:14px}nav{display:none}.cards{grid-template-columns:repeat(3,1fr)}table{min-width:0;font-size:9px}th,td{padding:6px}.table-wrap{overflow:visible}a{color:var(--ink)}h1{font-size:27px}h2{font-size:19px}}
'''


def references(output):
    """Create relative hyperlinks lexically; do not inspect target paths."""
    paths = {
        'development_plan': 'output/ml/gecco-v5-supported-development/plan.json',
        'development_results': 'output/ml/gecco-v5-supported-development/results.json',
        'supported_audit': 'output/ml/gecco-v5-calibration-development/supported_audit.json',
        'initial_audit': 'output/ml/gecco-v5-calibration-development/initial_development_audit.json',
        'v4_diagnosis': 'output/ml/gecco-v4/external_failure_diagnosis.json',
        'development_models': 'output/ml/gecco-v5-supported-development/',
        'fresh_protocol': 'output/ml/gecco-v5-ponds-frozen/protocol.json',
        'fresh_access': 'output/ml/gecco-v5-ponds-frozen/source_access_started.json',
        'fresh_results': 'output/ml/gecco-v5-ponds-frozen/results.json',
        'fresh_audit': 'output/ml/gecco-v5-ponds-frozen/final_audit.json',
        'fresh_models': 'output/ml/gecco-v5-ponds-frozen/',
        'reserved_protocol': 'output/ml/gecco-v5-ponds-reserved-repaired/protocol.json',
        'reserved_access': 'output/ml/gecco-v5-ponds-reserved-repaired/source_access_started.json',
        'reserved_results': 'output/ml/gecco-v5-ponds-reserved-repaired/results.json',
        'reserved_audit': 'output/ml/gecco-v5-ponds-reserved-repaired/final_audit.json',
        'reserved_models': 'output/ml/gecco-v5-ponds-reserved-repaired/',
        'reserved_failure': 'output/ml/gecco-v5-ponds-reserved-frozen/failure_record.json',
        'reserved_replay_audit': 'output/ml/gecco-v5-ponds-reserved-repaired/replay_audit.json',
    }
    refs = {key: quote(os.path.relpath(ROOT / path, output.parent), safe='/') for key, path in paths.items()}
    refs['reserved_csv'] = quote(output.stem + '-reserved-periods.csv', safe='')
    return refs


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/ml/gecco-v5/report.html')
    parser.add_argument('--include-ponds', action='store_true',
                        help='Only after root declares the complete fresh results ready; enables reading that one result JSON.')
    parser.add_argument('--include-reserved', action='store_true',
                        help='Only after root declares all312 extension periods ready; requires --include-ponds.')
    args = parser.parse_args()
    if args.include_reserved and not args.include_ponds:
        parser.error('--include-reserved requires --include-ponds to retain the primary result')
    development = read_json('output/ml/gecco-v5-supported-development/results.json')
    initial = read_json('output/ml/gecco-v5-recovery-development/results.json')
    diagnosis = read_json('output/ml/gecco-v4/external_failure_diagnosis.json')
    fresh = read_json('output/ml/gecco-v5-ponds-frozen/results.json') if args.include_ponds else None
    reserved = read_json('output/ml/gecco-v5-ponds-reserved-repaired/results.json') if args.include_reserved else None
    output = args.output.absolute()
    document = build_document(development, initial, diagnosis, references(output), fresh, reserved=reserved)
    period_csv = reserved_periods_csv(reserved) if reserved is not None else None
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding='utf-8')
    csv_output = output.with_name(output.stem + '-reserved-periods.csv') if period_csv is not None else None
    if csv_output is not None:
        csv_output.write_text(period_csv, encoding='utf-8-sig', newline='')
    print(json.dumps({'report': str(output), 'includes_fresh_results': fresh is not None,
                      'includes_reserved_results': reserved is not None,
                      'reserved_periods_csv': str(csv_output) if csv_output else None}, ensure_ascii=False))


if __name__ == '__main__':
    main()
