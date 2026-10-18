"""Build a small Arabic report from preserved V7 experiment artifacts."""
from pathlib import Path
import argparse
import html
import json
import os


def esc(value): return html.escape(str(value))
def pct(value): return '—' if value is None else f'{100*value:.2f}%'
def ltr(value): return f'<span class="ltr" dir="ltr">{esc(value)}</span>'
def counts(first, reference, candidate):
    return ltr(f'IF {first} | V6 {reference} | V7 {candidate}')
def paired_delay(comparison):
    values = [row['extra_delay_seconds'] for row in comparison['paired_extra_delays']]
    return max(values) if values else None
def delay_text(value): return '—' if value is None else f'{value:g} s'
def choice_text(value):
    return {'earlier_reference_retained': 'احتفاظ بالمرجع من مرحلة الاختيار',
            'certification_failed_reference_retained': 'رفض الإضافة بعد التحقق؛ رجوع إلى V6',
            'temporally_certified_confirmation_policy_selected': 'إضافة اجتازت التحقق الزمني',
            'bounded_confirmation_operating_point_selected': 'اختيار مهلة تأكيد من المعايرة',
            'joint_operating_point_selected': 'اختيار من المعايرة',
            'reference_retained': 'احتفاظ بالمرجع',
            'insufficient_observed_normal_exposure': 'بيانات الطبيعي غير كافية',
            'insufficient_primary_event_representation': 'أحداث المعايرة غير كافية'}.get(value, value)
def relative_link(path, destination):
    return esc(Path(os.path.relpath(path, destination.parent)).as_posix())
def optional_json(path):
    return json.loads(path.read_text()) if path.exists() else None
def audit_evidence(run):
    for name in ('audit.json', 'replay_audit.json'):
        path = run / name
        if path.exists(): return path, json.loads(path.read_text())
    return None, None

def metric_row(label, stats):
    return f'<tr><th>{esc(label)}</th><td>{stats["confirmed_events"]} من {stats["true_events"]}</td><td>{pct(stats["confirmed_event_recall"])}</td><td>{stats["false_positive_runs"]}</td><td>{stats["fp_duration_seconds"]/60:g}</td><td>{pct(stats["f1_observed_points"])}</td></tr>'


def render(run, destination, result=None):
    result = result if result is not None else json.loads((run / 'results.json').read_text())
    summary = result['summary']; against_v6 = summary['v6_vs_v7']; against_if = summary['if_vs_v7']
    delayed = result.get('maximum_allowed_extra_delay_seconds') == 120
    certified = any('certification' in p['selected'] for p in result['periods'])
    allowance = 120 if delayed else 0
    passed = against_v6['passes_declared_development_gate'] and against_if['passes_declared_development_gate']
    heading = 'اجتازت التجربة شروط التطوير المعلنة' if passed else 'التحسّن الثابت لم يثبت بعد'
    model_rows = ''.join([metric_row('النموذج الأول IF', against_if['baseline']),
                          metric_row('النسخة السابقة V6', against_v6['baseline']),
                          metric_row('مرشح V7', against_v6['candidate'])])
    period_rows = []; retention_rows = []
    all_comparisons = [p['comparisons'] for p in result['periods']] + list(result['sources'].values())
    maxima = {key: max((d['extra_delay_seconds'] for comp in all_comparisons for d in comp[key]['paired_extra_delays']), default=None)
              for key in ('if_vs_v7', 'v6_vs_v7')}
    observed_delays = [value for value in maxima.values() if value is not None]
    maximum_delay = max(observed_delays) if observed_delays else None
    rejection_notice = ''
    if delayed and maximum_delay is not None and maximum_delay > allowance:
        heading = 'لم تُقبل التجربة: تأخر اكتشاف بعض الأحداث أكثر من دقيقتين'
        rejection_notice = (f'<div class="notice"><strong>بلغ أقصى تأخير إضافي فعلي لحدث مقترن '
            f'{maximum_delay:g} ثانية ({maximum_delay/60:g} دقيقة)، متجاوزًا الحد المسموح 120 ثانية.</strong> '
            'حد الانتظار لكل نبضة مرجعية بقي دقيقتين، لكن اختفاء نبضة قصيرة قد يؤخر اكتشاف الحدث '
            'إلى نبضة لاحقة. لذلك لا تكفي سلامة مؤقت النبضة لقبول هذه النتيجة، رغم تحسن الأعداد المجمعة.</div>')
    losses = {key: sum(comp[key]['lost_positive_alarm_rows'] for comp in result['sources'].values())
              for key in ('if_vs_v7', 'v6_vs_v7')}
    for period in result['periods']:
        comp = period['comparisons']['v6_vs_v7']; original_comp = period['comparisons']['if_vs_v7']
        old = original_comp['baseline']; before, after = comp['baseline'], comp['candidate']
        stable = comp['noninferior'] and (delayed or comp['lost_positive_alarm_rows'] == 0)
        choice = period['selected']
        period_rows.append(f'<tr><th dir="ltr">{esc(period["case"])}</th><td>{after["true_events"]}</td>'
            f'<td>{counts(old["confirmed_events"],before["confirmed_events"],after["confirmed_events"])}</td>'
            f'<td>{counts(old["false_positive_runs"],before["false_positive_runs"],after["false_positive_runs"])}</td>'
            f'<td>{counts(old["fp"],before["fp"],after["fp"])}</td><td>{pct(after["f1_observed_points"])}</td>'
            f'<td class="{"ok" if stable else "bad"}">{"دون تراجع وفق شروط التجربة" if stable else "يوجد تراجع"}</td>'
            f'<td>{esc(choice_text(choice["status"]))}</td></tr>')
        ids = 'IF ' + str(original_comp['lost_baseline_event_ids']) + ' | V6 ' + str(comp['lost_baseline_event_ids'])
        loss = f'IF {original_comp["lost_positive_alarm_rows"]} | V6 {comp["lost_positive_alarm_rows"]}'
        delay = f'IF {delay_text(paired_delay(original_comp))} | V6 {delay_text(paired_delay(comp))}'
        retention_rows.append(f'<tr><th dir="ltr">{esc(period["case"])}</th><td>{ltr(ids)}</td>'
            f'<td>{ltr(delay)}</td><td>{ltr(loss)}</td><td>{ltr(delay_text(choice.get("confirmation_delay_seconds", 0)))}</td></tr>')
    checks = ''.join('<h3>'+esc(title)+'</h3><ul>'+''.join(
        f'<li class="{"ok" if yes else "bad"}">{esc(name)}: {"PASS" if yes else "FAIL"}</li>'
        for name, yes in item['checks'].items())+'</ul>'
        for title, item in [('مقارنة V7 مع V6', against_v6), ('مقارنة V7 مع IF', against_if)])
    source_sections = []
    for name, comparisons in result['sources'].items():
        a, b = comparisons['if_vs_v7'], comparisons['v6_vs_v7']
        lost = 'IF ' + str(a['lost_baseline_event_ids']) + ' | V6 ' + str(b['lost_baseline_event_ids'])
        source_sections.append(f'<h3 dir="ltr">{esc(name)}</h3><table><thead><tr><th>النموذج</th><th>أحداث مكتشفة / كل الأحداث</th><th>نسبة كشف الأحداث</th><th>مقاطع إنذار كاذب</th><th>دقائق إنذار كاذب</th><th>F1 للنقاط</th></tr></thead><tbody>'+metric_row('IF',a['baseline'])+metric_row('V6',b['baseline'])+metric_row('V7',b['candidate'])+'</tbody></table>'
            +'<p>معرّفات الأحداث المفقودة على محور المصدر المتصل: '+ltr(lost)+'.</p>')
    audit_path, audit = audit_evidence(run)
    audit_text = 'لم تُحفظ مراجعة إعادة التشغيل لهذه التجربة بعد.'
    audit_link = ''
    if audit is not None:
        audit_text = ('نجحت' if audit.get('passed') else 'لم تنجح') + ' مراجعة إعادة التشغيل. '
        if 'replayed_rows' in audit:
            audit_text += f'أُعيد حساب {audit["replayed_rows"]:,} قراءة من النماذج المحفوظة. '
        audit_text += 'هذا يثبت تطابق النتائج ضمن نطاق التدقيق، ولا يثبت نجاح النموذج أو اختبار مصدر جديد.'
        audit_link = f' · <a href="{relative_link(audit_path,destination)}">سجل إعادة التشغيل</a>'
    relative = relative_link(run, destination)
    if delayed:
        rule_text = ('بموافقتك، تختبر هذه المحاولة تأكيد إنذار الحساس لمدة أقصاها دقيقتان. '
            'إذا استمر إنذار المرجع، يُطلَق عند المهلة المختارة أو قبلها عند ظهور الثقة؛ والثقة المجهولة تُبقي إنذار المرجع فورًا. '
            'قد تختفي نبضة مرجعية قصيرة، لذلك يظل فقد أي حدث سببًا لرفض النتيجة. '
            'لا نسمح بزيادة مقاطع الإنذار الكاذب أو مدته في أي فترة، ولا بإضافة إنذارات كاذبة من مسار الكشف الإضافي أثناء المعايرة.')
        point_rule = 'إزالة دقائق التنبيه الموجبة الأولى مسموحة وصفيًا في تجربة التأكيد فقط؛ لا نستخدم شرط الحفاظ على كل دقيقة موجبة لرفضها. يبقى الحفاظ على كل حدث وحد التأخير شرطي قبول مستقلين.'
    else:
        rule_text = ('تختار المعايرة خفض الإنذارات وإضافة الكشف معًا، مع الحفاظ على أحداث V6 دون تأخير إضافي، '
            'وعلى كل دقيقة تنبيه موجبة من V6. لا يجوز زيادة الإنذارات الكاذبة في أي كتلة معايرة، '
            'ولا تمويل إنذارات كاذبة جديدة من مسار الكشف الإضافي بتوفير إنذارات أخرى.')
        point_rule = 'في هذه المحاولة الفورية، الحفاظ على دقائق التنبيه الموجبة بالنسبة إلى V6 شرط قبول. الفرق الموروث بين IF وV6 يُعرض وصفيًا.'
    delay_intro = ('اختبار انتظار النبضة المرجعية حتى 120 ثانية' if delayed else 'تجربة فورية: لا تأخير إضافي مسموح')
    certification_note = ''
    if certified:
        active = sum(p['selected']['decision'] != 'reference' for p in result['periods'])
        vetoed = sum(p['selected']['status'] == 'certification_failed_reference_retained' for p in result['periods'])
        certification_note = (f'<section class="card"><h2>فصل الاختيار عن التحقق الزمني</h2>'
            '<p>تختار أول كتلتين من المعايرة وصفة واحدة. تفحص الكتلتان اللاحقتان هذه الوصفة دون تعديلها؛ '
            'الفشل أو ضعف الدليل يعيد المرجع V6 كاملًا. نفحص البوابة وحدها أيضًا كي لا يخفي الكشف الإضافي فقد حدث، '
            'ثم نفحص الكتل الأربع متصلة لحماية الأحداث العابرة للحدود.</p>'
            f'<p>بقيت الإضافة فعالة في <b>{active} من {len(result["periods"])} فترة</b>، '
            f'ورُفضت بعد التحقق في <b>{vetoed} فترة</b>. الرجوع إلى المرجع إجراء تحفظي، وليس تحسنًا في الكشف بحد ذاته.</p>'
            '<p>هذا تحقق للقرار الإضافي مشروط بمرجع V6 المجمد؛ عُيّن المرجع نفسه سابقًا باستخدام كتل المعايرة الأربع. '
            'لذلك لا نعد هذا الفصل اختبارًا مستقلاً جديدًا للمنظومة.</p></section>')
    history_rows = []
    for prior in sorted(run.parent.glob('run_*')):
        previous = optional_json(prior / 'results.json')
        if previous is not None:
            old_summary = previous['summary']['v6_vs_v7']; candidate = old_summary['candidate']
            label = 'تأكيد حتى 120 ثانية' if previous.get('maximum_allowed_extra_delay_seconds') == 120 else 'تجربة فورية'
            if any('certification' in p['selected'] for p in previous['periods']):
                label = 'اختيار مبكر + تحقق لاحق + رجوع تحفظي'
            gate = previous['summary']['if_vs_v7']['passes_declared_development_gate'] and old_summary['passes_declared_development_gate']
            pa, _ = audit_evidence(prior)
            links = f'<a href="{relative_link(prior / "results.json",destination)}">النتائج</a>'
            if pa: links += f' · <a href="{relative_link(pa,destination)}">التدقيق</a>'
            supplement = prior / 'model_lineage_supplement.json'
            if supplement.exists():
                links += f' · <a href="{relative_link(supplement,destination)}">ملحق مطابقة النماذج</a>'
            history_rows.append(f'<tr><th dir="ltr">{esc(prior.name)}</th><td>{label}</td><td>{previous["complete_cases"]}</td>'
                f'<td>{candidate["confirmed_events"]}</td><td>{candidate["false_positive_runs"]}</td><td>{candidate["fp"]}</td>'
                f'<td>{"اجتازت شروط التطوير" if gate else "لم تجتز شروط التطوير"}</td><td>{links}</td></tr>')
        elif (prior / 'interrupted_diagnosis.json').exists():
            incomplete = optional_json(prior / 'interrupted_diagnosis.json')
            history_rows.append(f'<tr><th dir="ltr">{esc(prior.name)}</th><td>محاولة متوقفة</td><td>{incomplete["complete_cases_analyzed"]}</td>'
                '<td>—</td><td>—</td><td>—</td><td>غير مكتملة؛ لا نتيجة كاملة</td>'
                f'<td><a href="{relative_link(prior / "interrupted_diagnosis.json",destination)}">التشخيص المحفوظ</a></td></tr>')
    run02 = run.parent / 'run_02'
    causes = ''
    if (run02 / 'diagnosis.json').exists():
        causes = ('<p>في المحاولة الفورية السابقة '+ltr('run_02')+' تحسّن كشف الأحداث وF1 للقراءات، لكن تغير درجات الطبيعي بين الفترات أطال إنذارات كاذبة. '
            'في نوفمبر WaterHub انتقل المئين 99 لدرجة الطبيعي من 0.545 في المعايرة إلى 0.969 في الاختبار، أعلى من عتبة الكشف 0.935. '
            'وفي إحدى فترات 2018 بدأ التنبيه قبل الحدث واستمر داخله؛ زادت تغطية الحدث، لكن اختفى انتقال التنبيه الذي يثبت بداية اكتشافه. '
            'كما أخفى خفض الإنذارات ثلاث نبضات مرجعية قصيرة كانت تثبت أحداثًا حقيقية. '
            f'<a href="{relative_link(run02 / "diagnosis.json",destination)}">تشخيص الدرجات</a> · '
            f'<a href="{relative_link(run02 / "guard_diagnosis.json",destination)}">تحليل الأحداث المفقودة</a>.</p>')
    aggregation_path = run.parent.parent / 'gecco-v7-diagnosis/aggregation_audit.json'
    aggregation = optional_json(aggregation_path)
    if aggregation is not None:
        early = aggregation['totals']['known_positive_earlier_only']; total = aggregation['totals']['known_positive_minutes']
        fraction = aggregation['earlier_only_fraction_of_known_positive_minutes']; intervals = aggregation['positive_interval_totals']
        causes += (f'<p>لم يدعم التدقيق فرضية أن اختيار آخر قراءة في الدقيقة هو السبب العام لضعف الكشف: '
            f'كان وسم الحدث موجبًا في وقت أسبق فقط داخل {early} من {total:,} دقيقة موجبة ({pct(fraction)})، '
            f'ولم يختفِ بهذه الآلية أي حدث كامل من {intervals["known_normal_preceded_intervals"]} حدثًا. '
            'هذا يدحض التفسير العام بفقد التوقيت؛ فائدة ملخصات التغير داخل الدقيقة ما تزال فرضية غير مختبرة. '
            f'<a href="{relative_link(aggregation_path,destination)}">تدقيق التجميع</a>.</p>')
    current_diagnosis = run / 'post_test_diagnosis.json'
    if certified and current_diagnosis.exists():
        causes += ('<p><strong>تشخيص محاولة التحقق الزمني الحالية:</strong> فُقد حدثان بسبب انتهاء نبضات المرجع القصيرة '
            'قبل التأكيد، مع انخفاض ثقة المصنف وقت النبضة. في اختبار 2019 كانت الإشارتان اللتان تثبتان أحد الأحداث '
            'بطول دقيقتين لكل منهما؛ وفي ديسمبر كانت الإشارة الوحيدة دقيقة واحدة. ارتفاع الثقة في أوقات أخرى داخل الحدث '
            'لم ينقذه لأن مسار الكشف الإضافي كان معطلاً. إذن تزامن الثقة مع الإشارة مهم، ومتوسط جودة ترتيب الدرجات '
            'لا يكفي وحده لإثبات الحفاظ على الأحداث. '
            f'<a href="{relative_link(current_diagnosis,destination)}">تفاصيل الحدثين وكل قرارات الرجوع</a>.</p>')
    doc = f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — تقييم V7</title>
<style>body{{margin:0;background:#f3f6f7;color:#162b35;font:17px/1.75 system-ui,-apple-system,sans-serif}}main{{max-width:1400px;margin:auto;padding:32px 24px}}header{{background:#083c47;color:white;padding:28px;border-radius:16px}}h1{{font-size:30px;margin:5px 0}}h2{{font-size:23px;margin-top:32px}}h3{{text-align:right}}.notice{{background:#fff1d8;border-right:5px solid #bb770c;padding:18px;margin:20px 0;border-radius:9px}}.card{{background:white;padding:24px;border-radius:14px;margin:20px 0;overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:15px}}th,td{{padding:12px 10px;border-bottom:1px solid #dce4e7;text-align:right;white-space:nowrap}}thead{{background:#e8f0f2}}.ok{{color:#11634d}}.bad{{color:#a02d27}}a{{color:#086979}}.muted{{color:#516670}}code,.ltr{{direction:ltr;unicode-bidi:isolate;display:inline-block}}ul{{padding-right:24px}}.checks{{direction:ltr;text-align:left;font:14px/1.8 monospace}}footer{{font-size:14px}}details summary{{cursor:pointer;font-weight:650}}</style>
<main><header><div>مورد · تجربة تطوير V7 · {ltr(run.name)}</div><h1>{heading}</h1><p>{delay_intro}. مقارنة فعلية على {result['complete_cases']} فترة زمنية. لا ربط بمحاكاة 3D ولا تحكم بصمام.</p></header>{rejection_notice}
<div class="notice"><strong>هذه بيانات تطوير مكشوفة سابقًا.</strong> التدريب واختيار العتبات داخل كل فترة يستخدمان الماضي فقط، لكن منهج V7 صُمّم بعد رؤية نتائج GECCO وWaterHub. إعادة اختبارها لا تجعلها اختبارًا مستقلاً جديدًا. {"اجتياز التطوير لا يكفي لاعتماد النموذج؛ يلزم اختبار مستقل جديد." if passed else "هذه المحاولة لا تحقق اعتماد النموذج."}</div>
<section class="card"><h2>النتائج المجمّعة</h2><p>يُحسب كل مصدر على تسلسله الأصلي قبل جمع الأعداد. F1 هنا على القراءات، وليس «دقة» أو ضمانًا لسلامة المياه. معيار الحدث الأساسي يتطلب انتقالًا فعليًا من السكون إلى التنبيه داخل حدوده؛ زيادة تغطية دقائق الحدث لا تعوّض فقد هذا الانتقال.</p><table><thead><tr><th>النموذج</th><th>أحداث مكتشفة / كل الأحداث</th><th>نسبة كشف الأحداث</th><th>مقاطع إنذار كاذب</th><th>دقائق إنذار كاذب</th><th>F1 للنقاط</th></tr></thead><tbody>{model_rows}</tbody></table><p>فترات زيادة كشف الأحداث مقابل V6: <b>{against_v6['event_gain_periods']}</b>، وفترات تقليل مقاطع الإنذار الكاذب: <b>{against_v6['false_run_reduction_periods']}</b>، وفترات عدم التراجع وفق حد التأخير المعلن: <b>{against_v6['noninferior_periods']} من {against_v6['periods']}</b>.</p><p>أقصى فرق تأخير للأحداث المقترنة، عبر الفترات والمصادر: {ltr('IF '+delay_text(maxima['if_vs_v7'])+' | V6 '+delay_text(maxima['v6_vs_v7']))}. الحد المقبول: {ltr(str(allowance)+' s')}. دقائق تنبيه موجبة أزيلت على محاور المصادر المتصلة: {ltr('IF '+str(losses['if_vs_v7'])+' | V6 '+str(losses['v6_vs_v7']))}.</p></section>
<section class="card"><h2>السياسة المختبرة</h2><p>أضفنا مراجع طبيعية متعلّمة من التدريب ونوافذ سببية من 15 إلى 1440 عينة، مع أوزان تجمع بين مدة الحدث وتمثيل كل حدث. {rule_text}</p><p>{point_rule}</p><p>نجاح المعايرة لا يضمن النجاح في فترة لاحقة. حد الانتظار لكل نبضة لا يضمن وحده الحفاظ على الحدث: فقد نبضة قصيرة قد يؤخر اكتشافه إلى نبضة لاحقة؛ لذلك نقيس تأخير الأحداث ونرفض التجربة عند تجاوزه الحد.</p><p class="muted">WaterHub على شبكة زمنية منتظمة كل 60 ثانية. زمن GECCO محسوب بفاصل الاكتساب الاسمي 60 ثانية؛ احتُفظ بساعة الحائط الملتبسة في جزء من 2018، فلا نستخدمها لإثبات مهلة ميدانية مطلقة.</p></section>{certification_note}
<section class="card"><h2>كل الفترات، بما فيها الإخفاقات</h2><p>كل عدد موسوم باسم نموذجه. الاختلاف بين مجموع الصفوف والمجموع المتصل، إن وُجد، يعود إلى أحداث تمتد عبر حدود الفترات.</p><table><thead><tr><th>الفترة</th><th>أحداث حقيقية</th><th>الأحداث المكتشفة</th><th>مقاطع الإنذار الكاذب</th><th>دقائق الإنذار الكاذب</th><th>F1 لـV7</th><th>مقابل V6</th><th>قرار المعايرة</th></tr></thead><tbody>{''.join(period_rows)}</tbody></table></section>
<section class="card"><h2>الأحداث المفقودة والتأخير وتكلفة التأكيد</h2><p>المعرّفات هنا تخص محور كل فترة؛ معرّفات المصدر المتصل معروضة في القسم التالي. القائمة الفارغة تعني عدم فقد حدث. الحدث المفقود لا يدخل حساب التأخير المقترن، ويظل سبب رفض مستقلًا.</p><table><thead><tr><th>الفترة</th><th>كل معرّفات الأحداث المفقودة</th><th>أقصى فرق تأخير مقترن</th><th>دقائق تنبيه موجبة أزيلت</th><th>مهلة التأكيد المختارة</th></tr></thead><tbody>{''.join(retention_rows)}</tbody></table></section>
<section class="card"><h2>حسب المصدر</h2>{''.join(source_sections)}</section>
<section class="card"><h2>ما الذي كشفه تشخيص المحاولة السابقة؟</h2>{causes or '<p>لا يوجد تشخيص مستقل محفوظ لهذه المحاولة بعد.</p>'}</section>
<section class="card"><h2>منع التسريب والتحقق</h2><ul><li>تدريب على الجزء الأقدم، ثم أربع كتل معايرة لاحقة، ثم اختبار زمني لاحق.</li><li>المراجع وأوزان التصنيف تُتعلّم من التدريب فقط؛ العتبات ومهلة التأكيد من المعايرة فقط.</li><li>الوسوم المجهولة تُستبعد من الإشراف وحساب الطبيعي، وتظل حالة توفر الحساس مستقلة عنها.</li><li>تُحفظ الشيفرة وبصمات الملفات والنموذج والعتبات قبل تقييم كل جزء اختبار. إعادة استخدام نموذج محفوظ لا تعني إعادة تدريبه.</li><li>لا نمدّد الوسوم حول الأحداث؛ يُحسب الكشف على المحور الأصلي قبل أي تجميع.</li><li>{esc(audit_text)}</li></ul><div class="checks">{checks}</div></section>
<section class="card"><h2>سجل المحاولات المحفوظ</h2><p>تبقى نتائج المحاولة الفورية السابقة وتدقيقها متاحة؛ تحديث التقرير لا يحذف إخفاقاتها أو يحولها إلى اختبار جديد.</p><table><thead><tr><th>المحاولة</th><th>السياسة</th><th>فترات مكتملة</th><th>أحداث V7</th><th>مقاطع كاذبة</th><th>دقائق كاذبة</th><th>الحالة</th><th>الملفات</th></tr></thead><tbody>{''.join(history_rows)}</tbody></table></section>
<section class="card"><h2>حدود النتيجة</h2><p>GECCO قراءات شبكة مياه شرب، وWaterHub ضغوط نظام معالجة؛ لا تمثل هذه النتائج تجربة مياه وضوء ميدانية. الوسوم لا تثبت الفصل بين حدث جودة وخمسة أنواع أعطال. لم تُقَس سرعة Raspberry Pi، ولم يُمنح النموذج صلاحية فتح صمام أو يُربط بمحاكاة 3D. إعادة التشغيل هنا دفعات محفوظة، وليست إثباتًا لتطبيق تدفق دائم على الجهاز.</p></section>
<footer><p><a href="{relative}/results.json">النتائج الكاملة</a> · <a href="{relative}/plan.json">الخطة وبصمات الشيفرة</a>{audit_link}</p><p class="muted">اكتملت التجربة: <span dir="ltr">{esc(result['completed_at_utc'])}</span></p></footer></main></html>'''
    return doc


def build(run, destination):
    doc = render(run, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(doc)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--run', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); build(args.run.resolve(), args.output.resolve())
