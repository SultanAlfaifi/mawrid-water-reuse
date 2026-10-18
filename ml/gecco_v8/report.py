"""Arabic V8 development report, gated on all 19 results and verified replay.

This builder reads saved result/audit metadata only, never source measurements,
row labels, model bundles or partial case outputs. Audit success is not model
success. Older reports and experiment artifacts are left untouched.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_NAMES = [f"{year}_fold_{fold}" for year in (2017, 2018) for fold in range(1, 7)]
EXPECTED_NAMES += ["2019_disclosed_test", "2018-11", "2018-12", "2019-01", "2019-02", "2019-03", "2019-04"]
PAIRS = ("if_vs_v7", "v6_vs_v7")


def esc(value): return html.escape(str(value))
def ltr(value): return '<span dir="ltr" class="ltr">' + esc(value) + '</span>'
def pct(value): return "—" if value is None else f"{100 * value:.2f}%"
def number(value): return "—" if value is None else f"{value:g}"
def audit_count(audit, key):
    value = audit.get(key)
    return "غير متاح" if value is None else f"{value:,}"
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def link(path, destination, label):
    relative = Path(os.path.relpath(path, destination.parent)).as_posix()
    return f'<a href="{esc(relative)}">{esc(label)}</a>'
def triplet(first, reference, candidate): return ltr(f"IF {first} | V6 {reference} | V8 {candidate}")
def maximum_delay(comparison):
    return max((item["extra_delay_seconds"] for item in comparison["paired_extra_delays"]), default=None)


def load_verified(run):
    """Reject incomplete, failed, stale or missing audit before report output."""
    result_path, plan_path = run / "results.json", run / "plan.json"
    if not result_path.is_file():
        raise ValueError("Report awaits the complete 19-case results.json")
    result = read(result_path)
    if (result.get("candidate_version") != "V8" or result.get("complete_cases") != 19
            or result.get("expected_cases") != 19 or result.get("all_prespecified_cases_complete") is not True
            or [p.get("case") for p in result.get("periods", [])] != EXPECTED_NAMES
            or not result.get("completed_at_utc") or (run / "failed_case.json").exists()):
        raise ValueError("Report requires all 19 fixed V8 cases, including every failure")
    audit_path = next((run / name for name in ("audit.json", "replay_audit.json") if (run / name).is_file()), None)
    if audit_path is None:
        raise ValueError("Report awaits the independent replay audit")
    audit = read(audit_path)
    if audit.get("passed") is not True or audit.get("complete_replayed_cases") != 19:
        raise ValueError("Independent replay audit must finish and pass all 19 cases")
    if (audit.get("hashes", {}).get("results.json") != sha(result_path)
            or audit.get("hashes", {}).get("plan.json") != sha(plan_path)):
        raise ValueError("Independent audit must match these exact results and plan")
    if result.get("development_only") is not True or result.get("fresh_validation") is not False:
        raise ValueError("This reporter only describes disclosed development experiments")
    if result.get("maximum_allowed_extra_delay_seconds") != 120:
        raise ValueError("Expected unchanged 120-second event-delay acceptance criterion")
    return result, audit_path, audit


def metric_row(name, metrics):
    return (f'<tr><th>{esc(name)}</th><td>{metrics["confirmed_events"]} من {metrics["true_events"]}</td>'
            f'<td>{pct(metrics["confirmed_event_recall"])}</td><td>{metrics["false_positive_runs"]}</td>'
            f'<td>{number(metrics["fp_duration_seconds"] / 60)}</td><td>{pct(metrics["f1_observed_points"])}</td></tr>')


METRIC_HEAD = '<thead><tr><th>النموذج</th><th>أحداث مكتشفة / كل الأحداث</th><th>كشف الأحداث</th><th>مقاطع إنذار كاذب</th><th>دقائق إنذار كاذب</th><th>F1 للقراءات</th></tr></thead>'


def optional_diagnosis(run, destination, result):
    """Summarize only saved diagnosis metadata bound to the current result."""
    path = run / "post_test_diagnosis.json"
    if not path.is_file():
        return "", None
    diagnosis = read(path)
    if (diagnosis.get("candidate_version") != "V8"
            or diagnosis.get("input_sha256", {}).get("results.json") != sha(run / "results.json")
            or diagnosis.get("fresh_validation") is not False
            or diagnosis.get("new_source_accessed") is not False
            or diagnosis.get("model_refitted") is not False
            or diagnosis.get("thresholds_changed") is not False):
        raise ValueError("Optional diagnosis must describe these exact unchanged V8 development results")
    expected_active = {p["case"] for p in result["periods"] if p["selected"]["decision"] != "reference"}
    active = diagnosis.get("active_periods", [])
    fallback = diagnosis.get("fallbacks", [])
    if ({p["case"] for p in active} != expected_active
            or {p["case"] for p in fallback} != set(EXPECTED_NAMES) - expected_active
            or len(active) + len(fallback) != 19):
        raise ValueError("Diagnosis must retain every active and unchanged period")
    expected_lost = {p["case"]: p["comparisons"]["v6_vs_v7"]["lost_baseline_event_ids"] for p in result["periods"]}
    for period in active:
        if [event["event_id"] for event in period["lost_events"]] != expected_lost[period["case"]]:
            raise ValueError("Diagnosis lost-event IDs disagree with the completed result")
    loss_periods = sum(bool(period["lost_events"]) for period in active)
    timing_doc = ""
    timing_path = run / "timing_followup.json"
    if timing_path.is_file():
        timing = read(timing_path)
        for name, digest in timing["input_sha256"].items():
            if sha(run / name) != digest:
                raise ValueError("Timing diagnosis input no longer matches")
        expected_pairs = {(case, event) for case, events in expected_lost.items() for event in events}
        if {(e["case"], e["event_id"]) for e in timing["lost_events"]} != expected_pairs:
            raise ValueError("Timing diagnosis must retain every lost reference event")
        timing_rows = []
        for event in timing["lost_events"]:
            crossings = [p["first_raw_confidence_crossing_seconds"] for p in event["pulses"]]
            first = min((v for v in crossings if v is not None), default=None)
            crossing_text = "لم تبلغها قبل نهاية الحدث" if first is None else f"بعد {number(first)} ثانية"
            within = any(p["raw_confidence_can_confirm_within120s"] for p in event["pulses"])
            timing_rows.append('<tr><td>'+ltr(event["case"])+'</td><td>'+str(event["event_id"])
                +'</td><td>'+crossing_text+'</td><td>'+("نعم" if within else "لا")+'</td></tr>')
        timing_doc = ('<h3>هل يكفي إبقاء الانتظار لدقيقتين؟</h3><table><thead><tr><th>الفترة</th>'
            '<th>الحدث المفقود</th><th>أول بلوغ لعتبة الثقة بعد نبضة المرجع</th><th>خلال 120 ثانية</th>'
            '</tr></thead><tbody>'+''.join(timing_rows)+'</tbody></table><p>هذه قراءة للدرجات المحفوظة عند '
            'العتبات المثبتة، وليست اختبارًا لسياسة جديدة. تبين أن تعديل المؤقّت وحده لا يستعيد هذين الحدثين '
            'ضمن الحد المسموح؛ يلزم تحسين دليل الثقة أو شروط قبول حجب الإنذار. '
            +link(timing_path,destination,"تفاصيل التوقيت وبصمات المدخلات")+'</p>')
    doc = (f'<section><h2>التشخيص المحفوظ بعد الاختبار</h2><p>يحلل التشخيص {len(active)} سياسة نشطة '
           f'ويحفظ {len(fallback)} قرارًا بالرجوع إلى المرجع. سجل فقد أحداث مرجعية في {loss_periods} فترة نشطة. '
           'تعرض التفاصيل توزيعات الدرجات في الاختيار والشهادة والاختبار، وطول النبضات المرجعية وثقتها، '
           'ومقارنة الأحداث مع V7. هذه قراءة وصفية بعد الاختبار؛ لم تُغيّر النموذج أو العتبات ولم تفتح مصدرًا جديدًا.</p><p>'
           +link(path,destination,"التشخيص الكامل المرتبط بهذه النتائج")+'</p>'+timing_doc+'</section>')
    return doc, {"path": str(path), "sha256": sha(path), "active_policies": len(active),
                 "reference_retention_decisions": len(fallback), "active_periods_with_lost_reference_events": loss_periods}


def render(run, destination, result, audit_path, audit, prior_run, public_search):
    summary = result["summary"]
    accepted = all(summary[key]["passes_declared_development_gate"] for key in PAIRS)
    heading = "اجتازت V8 شروط التطوير؛ التحقق المستقل ما زال مطلوبًا" if accepted else "V8 لم تثبت التحسّن الثابت المطلوب"
    comparisons = [p["comparisons"] for p in result["periods"]] + list(result["sources"].values())
    max_delays = {key: max((delay["extra_delay_seconds"] for comp in comparisons
                          for delay in comp[key]["paired_extra_delays"]), default=None) for key in PAIRS}
    lost = {key: {p["case"]: p["comparisons"][key]["lost_baseline_event_ids"] for p in result["periods"]
                  if p["comparisons"][key]["lost_baseline_event_ids"]} for key in PAIRS}
    if any(value is not None and value > 120 for value in max_delays.values()):
        heading = "V8 لم تُقبل: تأخير فعلي يتجاوز دقيقتين"
    elif lost["if_vs_v7"] or lost["v6_vs_v7"]:
        heading = "V8 لم تُقبل: فُقدت أحداث كان المرجع يكتشفها"
    first = summary["if_vs_v7"]["baseline"]
    reference, candidate = summary["v6_vs_v7"]["baseline"], summary["v6_vs_v7"]["candidate"]
    current_rows = metric_row("IF: النموذج الأول", first) + metric_row("V6: المرجع المجمد", reference) + metric_row("V8: أوزان بداية الحدث", candidate)
    period_rows = []; retention_rows = []; selection_rows = []
    for period in result["periods"]:
        a, b = period["comparisons"]["if_vs_v7"], period["comparisons"]["v6_vs_v7"]
        old, ref, new = a["baseline"], b["baseline"], b["candidate"]
        period_rows.append(f'<tr><th>{ltr(period["case"])}</th><td>{new["true_events"]}</td>'
            f'<td>{triplet(old["confirmed_events"],ref["confirmed_events"],new["confirmed_events"])}</td>'
            f'<td>{triplet(old["false_positive_runs"],ref["false_positive_runs"],new["false_positive_runs"])}</td>'
            f'<td>{triplet(number(old["fp_duration_seconds"]/60),number(ref["fp_duration_seconds"]/60),number(new["fp_duration_seconds"]/60))}</td>'
            f'<td>{pct(new["f1_observed_points"])}</td><td>{ltr("IF " + str(a["noninferior"]) + " | V6 " + str(b["noninferior"]))}</td></tr>')
        retention_rows.append(f'<tr><th>{ltr(period["case"])}</th>'
            f'<td>{ltr("IF " + str(a["lost_baseline_event_ids"]) + " | V6 " + str(b["lost_baseline_event_ids"]))}</td>'
            f'<td>{ltr("IF " + number(maximum_delay(a)) + " s | V6 " + number(maximum_delay(b)) + " s")}</td>'
            f'<td>{ltr("IF " + str(a["lost_positive_alarm_rows"]) + " | V6 " + str(b["lost_positive_alarm_rows"]))}</td></tr>')
        selected = period["selected"]
        selection_rows.append(f'<tr><th>{ltr(period["case"])}</th><td>{ltr(selected["status"])}</td>'
            f'<td>{ltr(number(selected["confirmation_delay_seconds"]) + " s")}</td>'
            f'<td>{esc("؛ ".join(selected.get("certification_rejection_reasons", [])) or "—")}</td></tr>')
    sources = []
    for name, comp in result["sources"].items():
        a, b = comp["if_vs_v7"], comp["v6_vs_v7"]
        sources.append('<h3>'+ltr(name)+'</h3><table>'+METRIC_HEAD+'<tbody>'
            +metric_row("IF",a["baseline"])+metric_row("V6",b["baseline"])+metric_row("V8",b["candidate"])
            +'</tbody></table><p>معرّفات الأحداث المفقودة على محور المصدر: '
            +ltr("IF " + str(a["lost_baseline_event_ids"]) + " | V6 " + str(b["lost_baseline_event_ids"]))
            +'. أقصى تأخير إضافي مقترن: '+ltr("IF " + number(maximum_delay(a)) + " s | V6 " + number(maximum_delay(b)) + " s")
            +'. عدم التراجع: '+ltr("IF " + str(a["noninferior"]) + " | V6 " + str(b["noninferior"]))+'</p>')
    check_html = []
    for key, name in (("if_vs_v7", "مقارنة V8 مع IF"), ("v6_vs_v7", "مقارنة V8 مع V6")):
        rows = ''.join(f'<li class="{"ok" if passed else "bad"}">{esc(check)}: {"PASS" if passed else "FAIL"}</li>'
                       for check, passed in summary[key]["checks"].items())
        check_html.append(f'<h3>{name}</h3><ul class="checks">{rows}</ul>')
    previous = read(prior_run / "results.json")
    prior_metrics = previous["summary"]["v6_vs_v7"]["candidate"]
    # Comparisons remain fair only when the historical reference aggregate and
    # all case identities match the current experiment.
    same_cases = [p["case"] for p in previous["periods"]] == EXPECTED_NAMES
    keys = ("true_events", "confirmed_events", "false_positive_runs", "fp_duration_seconds", "tp", "fp", "fn")
    same_ref = all(previous["summary"]["v6_vs_v7"]["baseline"][key] == reference[key] for key in keys)
    if not same_cases or not same_ref:
        raise ValueError("V7 run04 comparison requires identical cases and frozen V6 reference aggregates")
    prior_comparison = ('<table>'+METRIC_HEAD+'<tbody>'+metric_row("V7 run04",prior_metrics)+metric_row("V8",candidate)+'</tbody></table>'
        '<p>التجربتان تستخدمان الفترات نفسها ومرجع V6 نفسه. تغيرت أوزان التدريب فقط؛ '
        'نجاح شهادة المعايرة الماضية لا يضمن الاحتفاظ بأحداث الفترة التالية. '
        +link(prior_run / "results.json",destination,"نتائج V7 run04 المحفوظة")+' · '
        +link(prior_run / "post_test_diagnosis.json",destination,"تشخيص النبضات القصيرة المفقودة")+'</p>')
    public_info = read(public_search)
    public_html = ('لم يُثبت البحث العام حتى الآن مصدر جودة مياه طويلًا متاحًا فورًا، بوسوم أحداث مستقلة وتواتر مناسب، يحقق جميع شروط التحقق. '
        'ورد WDSEventDB كتجربة عمليات مياه قصيرة، وUWO S1 كمصدر طويل بفاصل خمس دقائق؛ لكل منهما نطاق مختلف وحدود تمنع وصفه وحده بإثبات كامل للكشف خلال دقيقتين وثبات الإنذارات. '
        'لم يُستخدم مصدر جديد في تجربة V8. '+link(public_search,destination,"مذكرة المصادر العامة وحدودها"))
    for option in public_info.get("public_water_options", []):
        if option.get("primary_record"):
            public_html += f' · <a href="{esc(option["primary_record"])}">{esc(option["name"])}</a>'
    hai_qualification = public_search.parent / 'hai23/qualification.json'
    if hai_qualification.exists():
        public_html += ('<br><br>اكتمل أيضًا فحص تواريخ وبصمات ملفات HAI23 العامة دون استخدام قيمها للتدريب: '
            'أسماء train وtest لا تطابق ترتيبًا زمنيًا صالحًا، ووسوم أحد الاختبارين بدقة الدقيقة فقط. '
            'لم تُثبت هندسة تستوفي بروتوكول V8 الحالي. يتطلب الاختيار المبكر والشهادة اللاحقة كلٌ منهما '
            '96 ساعة طبيعية مرصودة، أي 192 ساعة معًا؛ هذا يصحح فرضية المعايرة السابقة في مذكرة المصادر. '
            +link(hai_qualification,destination,'تفاصيل تأهيل HAI وحدوده'))
    diagnosis_html, diagnosis_info = optional_diagnosis(run,destination,result)
    status = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "candidate": "V8", "run": str(run),
              "phase": "development_pass_needs_fresh_validation" if accepted else "development_failed",
              "complete_cases": 19, "independent_replay_audit_passed": True,
              "replay_audit_proves_model_acceptance": False, "passes_declared_development_gate": bool(accepted),
              "fresh_external_validation_performed": False, "deployment_approved": False, "three_d_connected": False,
              "summary": summary, "lost_events_by_period": lost, "maximum_paired_extra_delay_seconds": max_delays,
              "policy_status_counts": dict(Counter(p["selected"]["status"] for p in result["periods"])),
              "v7_run04_candidate": prior_metrics, "post_test_diagnosis": diagnosis_info, "report": str(destination)}
    doc = f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — تقييم V8</title>
<style>body{{margin:0;background:#f1f5f5;color:#18333c;font:17px/1.75 system-ui,sans-serif}}main{{max-width:1450px;margin:auto;padding:28px 22px}}header{{background:#073f49;color:white;border-radius:16px;padding:28px}}h1{{font-size:30px}}h2{{font-size:23px}}section{{background:white;border-radius:14px;padding:22px;margin:20px 0;overflow-x:auto}}.notice{{background:#fff1d6;border-right:5px solid #ae740e;padding:18px;margin:20px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{text-align:right;vertical-align:top;border-bottom:1px solid #dce5e6;padding:10px;white-space:nowrap}}thead{{background:#e8f1f2}}a{{color:#086b72}}.ltr{{unicode-bidi:isolate;direction:ltr;display:inline-block}}.checks{{direction:ltr;text-align:left;font:14px/1.8 monospace}}.ok{{color:#166044}}.bad{{color:#a02c24}}.muted{{color:#52666d}}details summary{{cursor:pointer;font-weight:bold}}</style>
<main><header><div>مورد · تطوير كشف الشذوذ · {ltr(run.name)}</div><h1>{heading}</h1><p>19 فترة مكتملة، مع إعادة تشغيل مستقلة للنتائج. لا ربط بالـ3D أو بالصمام.</p></header>
<div class="notice"><strong>هذه تجربة تطوير على بيانات سبق كشف نتائجها.</strong> يُستخدم الماضي داخل كل تقسيم للتدريب والمعايرة، لكن تصميم المحاولات استفاد من النتائج السابقة. تدقيق الحسابات وإعادة التشغيل لا يحوّلان ذلك إلى اختبار مصدر خارجي لم يُستخدم.</div>
<section><h2>النتائج الفعلية</h2><table>{METRIC_HEAD}<tbody>{current_rows}</tbody></table><p>فترات عدم التراجع مقابل V6: {summary['v6_vs_v7']['noninferior_periods']} من 19. مقابل IF: {summary['if_vs_v7']['noninferior_periods']} من 19. أقصى فرق تأخير فعلي للأحداث المقترنة: {ltr('IF '+number(max_delays['if_vs_v7'])+' s | V6 '+number(max_delays['v6_vs_v7'])+' s')}، والحد المقبول 120 ثانية.</p><p>F1 هنا للقراءات، وليس «دقة النموذج» ولا ضمان سلامة المياه. الكشف الأساسي يتطلب انتقالًا من السكون إلى الإنذار داخل حدث معلوم البداية. لا نعوّض فقد حدث بزيادة تغطية دقائق حدث آخر.</p></section>
<section><h2>ما الذي تغيّر؟</h2><p>ركز V8 أوزان التدريب على بداية الحدث لمواجهة المشكلة التي كشفها V7: قد تكون درجات النموذج مرتفعة داخل الحدث، لكن منخفضة وقت نبضة الحساس القصيرة التي تثبت اكتشافه. بقيت الخصائص السببية والمراجع وإعدادات HGB والمعايرة وسياسة القرار نفسها.</p><p>نصف الوزن للقراءات الطبيعية. نصف الوزن الموجب موزع إلى 0.125 للقراءات، و0.125 بالتساوي بين المقاطع، و0.25 لبدايات الأحداث المعروفة. نافذة البداية أول ثلاث عينات فعلية؛ لا تُنقل إلى وقت لاحق إذا تعذر رصدها. المقاطع التي تبدأ بعد وسم مجهول أو عند أول السلسلة لا تحصل على مكافأة البداية. إذا غابت كل البدايات المؤهلة، يعود وزنها إلى توزيع المقاطع.</p><p>نافذة التدريب ثلاث عينات؛ عند فاصل دقيقة تكون الإزاحات 0 و60 و120 ثانية. هذا تركيز تدريبي وليس ضمانًا لزمن اكتشاف الحدث.</p></section>
<section><h2>المقارنة بالمحاولة السابقة</h2>{prior_comparison}</section>
{diagnosis_html}
<section><h2>شروط القبول بقيت كما هي</h2><p>نطلب الحفاظ على كل حدث اكتشفه المرجع وعلى توفر الحساس، وألا يزيد التأخير المقترن على 120 ثانية أو يزيد عدد مقاطع الإنذار الكاذب ومدتها في أي فترة أو مصدر. ويلزم تحسن إجمالي وفي فترتين على الأقل لكل من زيادة الكشف وتقليل المقاطع الكاذبة، أمام IF وV6 معًا.</p><p>يسمح اختبار التأكيد بحذف دقائق موجبة أولى، وتُعرض تكلفتها أدناه. مؤقت نبضة مرجعية مستمرة لمدة دقيقتين لا يضمن حفظ حدث يعتمد على نبضة أقصر؛ لذلك يبقى فقد الحدث أو تأخيره الفعلي سببًا مستقلًا للرفض.</p>{''.join(check_html)}</section>
<section><h2>كل الفترات</h2><table><thead><tr><th>الفترة</th><th>الأحداث الحقيقية</th><th>الأحداث المكتشفة</th><th>المقاطع الكاذبة</th><th>الدقائق الكاذبة</th><th>F1 لـV8</th><th>عدم التراجع</th></tr></thead><tbody>{''.join(period_rows)}</tbody></table></section>
<section><h2>الأحداث المفقودة والتأخير</h2><p>القائمة الفارغة تعني عدم فقد حدث. الحدث المفقود مستبعد من التأخير المقترن، ولذلك لا يمكن استعمال انخفاض التأخير لإخفاء فقده. معرّفات هذا الجدول تخص محور الفترة.</p><table><thead><tr><th>الفترة</th><th>كل معرّفات الأحداث المفقودة</th><th>أقصى فرق تأخير مقترن</th><th>دقائق تنبيه موجبة أزيلت</th></tr></thead><tbody>{''.join(retention_rows)}</tbody></table></section>
<section><h2>المصادر على محاورها المتصلة</h2><p>نحسب كل مصدر قبل جمع الأعداد كي لا نكرر أحداثًا أو مقاطع تعبر حدود الفترات.</p>{''.join(sources)}</section>
<section><h2>الاختيار الزمني وحالات الرجوع للمرجع</h2><p>تختار أول كتلتين ماضيتين وصفة واحدة؛ تفحصها الكتلتان اللاحقتان دون إعادة ضبط. أي ضعف دليل أو إخفاق يعيد V6 كاملًا. نفحص أيضًا سياسة التأكيد وحدها والقرار المركب على محور الكتل الأربع، لحماية الأحداث العابرة لحد الفصل. هذه شهادة للسياسة الإضافية مشروطة بمرجع V6 المجمد؛ V6 نفسه اختير سابقًا بكل الكتل الأربع.</p><details><summary>عرض كل قرارات المعايرة وأسباب الرفض</summary><table><thead><tr><th>الفترة</th><th>الحالة</th><th>مهلة التأكيد</th><th>الأسباب المحفوظة</th></tr></thead><tbody>{''.join(selection_rows)}</tbody></table></details></section>
<section><h2>ما الذي تحقق منه التدقيق؟</h2><p>نجحت إعادة التشغيل المستقلة للفترات19، وشملت قراءات اختبار عددها {audit_count(audit,'replayed_rows')}، وقراءات معايرة عددها {audit_count(audit,'calibration_sensor_rows_replayed')}. طابقت النتائج المحفوظة وأوزان التدريب والمراجع والبوابات ضمن نطاق المدقق. هذا تحقق من التنفيذ والحسابات، ولا يعني قبول أداء النموذج أو اختبار مصدر جديد. التنفيذ المعاد دفعات؛ لم يُثبت تشغيلًا دائمًا على Raspberry Pi.</p><p>{link(audit_path,destination,'سجل التدقيق المستقل')} · {link(run/'plan.json',destination,'الخطة وبصمات الشيفرة')} · {link(run/'results.json',destination,'كل النتائج')}</p></section>
<section><h2>التحقق الخارجي التالي</h2><p>{public_html}</p><p>لا تثبت GECCO وWaterHub أداءً ميدانيًا على مياه الوضوء أو فصلًا موثوقًا بين حدث جودة وخمسة أنواع أعطال. لا توجد صلاحية لفتح الصمام، ولم تُدمج هذه المحاولة مع المحاكاة.</p></section>
<footer class="muted">اكتملت التجربة {ltr(result['completed_at_utc'])}. النتائج السابقة محفوظة، ولا تُحذف الإخفاقات عند تحديث التقرير.</footer></main></html>'''
    return doc, status


def build(run, destination, *, status_path=None, prior_run=None, public_search=None):
    run, destination = Path(run).resolve(), Path(destination).resolve()
    prior_run = Path(prior_run).resolve() if prior_run else ROOT / "output/ml/gecco-v7-development/run_04"
    public_search = Path(public_search).resolve() if public_search else ROOT / "output/ml/gecco-v8-source-search/public_only_followup_v2.json"
    result, audit_path, audit = load_verified(run)
    doc, status = render(run,destination,result,audit_path,audit,prior_run,public_search)
    encoded_status = json.dumps(status, indent=2, allow_nan=False) + "\n"
    status_path = Path(status_path).resolve() if status_path else destination.parent / "status.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(doc)
    status_path.write_text(encoded_status)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status", type=Path)
    args = parser.parse_args()
    result = build(args.run,args.output,status_path=args.status)
    print(json.dumps({key:result[key] for key in ("phase","complete_cases","passes_declared_development_gate","report")}))
