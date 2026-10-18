"""Render frozen GECCO results; never fit a model or choose a threshold.

Reads only the six named experiment artifacts in INPUTS. The PNG is also
embedded into the Arabic HTML, so report.html remains independently viewable.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parents[1] / "output/ml/gecco-baseline-v1"
INPUTS = (
    "data_manifest.json", "freeze.json", "validation_results.json",
    "test_results.json", "test_predictions.csv.gz", "validation_threshold_sweep.csv",
)


def esc(value):
    return html.escape(str(value), quote=True)


def number(value, decimals=0):
    if value is None or not math.isfinite(float(value)):
        return "غير معرّف"
    return f"{value:,.{decimals}f}"


def percent(value):
    return "غير معرّف" if value is None else number(100 * value, 2) + "%"


def numeric(value):
    return value is not None and math.isfinite(float(value))


def bool_array(series):
    if pd.api.types.is_bool_dtype(series):
        return series.to_numpy(dtype=bool)
    values = series.astype(str).str.lower()
    if not values.isin(["true", "false", "1", "0"]).all():
        raise ValueError("Unexpected Boolean values in saved predictions")
    return values.isin(["true", "1"]).to_numpy()


def intervals(mask):
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    return zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1))


def read_inputs(out):
    missing = [name for name in INPUTS if not (out / name).is_file()]
    if missing:
        raise SystemExit("Results are not complete; missing: " + ", ".join(missing))
    values = {}
    for name in INPUTS:
        path = out / name
        values[name] = (json.loads(path.read_text(encoding="utf-8"))
                        if name.endswith(".json") else pd.read_csv(path))
    return values


def check_consistency(manifest, frozen, test, predictions):
    """Check artifact agreement without loading the estimator or recomputing metrics."""
    if len(predictions) != test["sample_count"]:
        raise ValueError("Prediction row count differs from saved test metrics")
    if not np.isclose(test["threshold"], frozen["threshold"], rtol=0, atol=0):
        raise ValueError("Test threshold differs from frozen threshold")
    for key in ("source_sha256", "protocol_sha256"):
        if manifest[key] != frozen[key]:
            raise ValueError(f"Manifest and freeze disagree: {key}")
    if test.get("test_used_for_selection") is not False or frozen.get("test_used_for_selection") is not False:
        raise ValueError("Artifacts do not attest to an untouched selection holdout")
    prediction_values = predictions["prediction"].to_numpy(dtype=int)
    if not np.isin(prediction_values, [-1, 0, 1]).all():
        raise ValueError("Invalid saved prediction values")
    split = manifest["splits"]["test"]
    if int(predictions.row_id.iloc[0]) != split["first_row_id"] or int(predictions.row_id.iloc[-1]) != split["last_row_id"]:
        raise ValueError("Saved prediction boundaries differ from the data manifest")


def plot_overview(out, validation, test, frozen, predictions):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 1, figsize=(13.2, 8.5),
                             gridspec_kw={"height_ratios": [1, 1.65]}, layout="constrained")
    ax = axes[0]
    keys = ["precision", "recall", "f1"]
    x = np.arange(3)
    for offset, values, label, color in [(-.19, validation, "Validation (threshold selection)", "#769eb7"),
                                         (.19, test, "Held-out test", "#0d665e")]:
        heights = [values.get(key) if values.get(key) is not None else 0 for key in keys]
        bars = ax.bar(x + offset, heights, width=.36, label=label, color=color)
        for bar, key in zip(bars, keys):
            value = values.get(key)
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height()+.025,
                    "N/A" if value is None else f"{value:.3f}", ha="center", fontsize=10)
    ax.set_xticks(x, ["Precision", "Recall", "F1"])
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Point metric (eligible minutes)")
    ax.set_title("A. Frozen model: validation vs. held-out test", loc="left", weight="bold")
    ax.grid(axis="y", alpha=.18)
    ax.legend(loc="upper right", frameon=False, fontsize=9)

    ax = axes[1]
    scores = pd.to_numeric(predictions.anomaly_score, errors="coerce").to_numpy()
    truth = bool_array(predictions.EVENT)
    predicted = predictions.prediction.to_numpy(dtype=int)
    days = np.arange(len(predictions)) / 1440
    for start, end in intervals(truth):
        ax.axvspan(start/1440, end/1440, color="#77b8e0", alpha=.24, lw=0)
    for start, end in intervals(predicted == -1):
        ax.axvspan(start/1440, end/1440, color="#6b7280", alpha=.23, lw=0)
    ax.plot(days, scores, color="#264652", lw=.7, rasterized=True, label="Anomaly score")
    false_mask = (predicted == 1) & ~truth
    ax.scatter(days[false_mask], scores[false_mask], color="#c8463b", s=8,
               alpha=.65, linewidths=0, rasterized=True, label="False-alarm minutes")
    ax.axhline(frozen["threshold"], color="#b36a18", lw=1.5, ls="--", label="Frozen threshold")
    ax.set_title("B. Held-out test timeline (acquisition order)", loc="left", weight="bold")
    ax.set_xlabel("Nominal elapsed days from test start (1 row = 1 minute; not reconstructed UTC)")
    ax.set_ylabel("Anomaly score (higher = more abnormal)")
    ax.set_xlim(0, len(predictions)/1440)
    ax.grid(alpha=.15)
    handles, labels = ax.get_legend_handles_labels()
    handles += [Patch(facecolor="#77b8e0", alpha=.4), Patch(facecolor="#6b7280", alpha=.35)]
    labels += ["Original true-event interval", "Prediction unavailable"]
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0, -.18), ncol=3,
              frameon=False, fontsize=9)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=180, facecolor="white")
    picture = buffer.getvalue()
    (out / "overview.png").write_bytes(picture)
    plt.close(fig)
    return base64.b64encode(picture).decode("ascii")


def table(headers, rows, css=""):
    return '<div class="table-wrap"><table class="' + css + '"><thead><tr>' + "".join(
        "<th>" + esc(c) + "</th>" for c in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join("<td>" + str(c) + "</td>" for c in row) + "</tr>"
        for row in rows) + "</tbody></table></div>"


def metric_table(validation, test):
    definitions = [
        ("Precision — دقة الإنذارات", "precision", percent),
        ("Recall — استدعاء الدقائق الشاذة المتاحة", "recall", percent),
        ("F1 — توازن الدقة والاستدعاء", "f1", percent),
        ("تغطية الأحداث بأي إنذار متداخل", "event_recall", percent),
        ("أحداث شهدت بداية مؤكدة جديدة 0→1", "confirmed_new_alarm_inside_event_recall", percent),
        ("الأحداث الكاملة: التغطية", "complete_event_coverage", percent),
        ("الأحداث الكاملة: بداية مؤكدة جديدة", "complete_confirmed_new_alarm_start_recall", percent),
        ("مقاطع الإنذار الكاذب لكل يوم طبيعي متاح", "false_alarm_runs_per_normal_day", lambda v:number(v, 3)),
        ("نسبة الوقت الطبيعي المتاح تحت إنذار كاذب", "normal_time_under_alarm", percent),
        ("تغطية التنبؤ — نسبة الدقائق القابلة للتقييم", "prediction_coverage", percent),
        ("عدد الدقائق دون تنبؤ", "unavailable_count", number),
        ("جميع الأحداث الأصلية", "true_events", number),
        ("أحداث مغطاة بإنذار", "detected_events", number),
        ("أحداث ببداية مؤكدة جديدة 0→1", "confirmed_new_alarm_inside_events", number),
        ("أحداث ببداية إنذار خام، بما فيها حالة سابقة مجهولة", "new_alarm_inside_events", number),
        ("أحداث كان الإنذار نشطاً عند بدايتها", "covered_at_onset_events", number),
        ("أحداث تلامس حدود التقسيم", "boundary_censored_events", number),
        ("أحداث لا تتوفر لها أي دقيقة قابلة للتقييم", "fully_unscorable_events", number),
        ("مقاطع الإنذار الكاذب", "false_positive_runs", number),
        ("جميع مقاطع الإنذار الخام", "alarm_runs", number),
        ("الأيام الطبيعية المتاحة — مقام معدل الإنذار الكاذب", "eligible_normal_days", lambda v:number(v, 3)),
        ("وسيط زمن أول تغطية للأحداث المغطاة فقط، دقيقة", "median_detection_delay_minutes", lambda v:number(v, 1)),
        ("المئين 95 لزمن أول تغطية، دقيقة", "p95_detection_delay_minutes", lambda v:number(v, 1)),
    ]
    event_counts = {
        "event_recall": ("detected_events", "true_events"),
        "confirmed_new_alarm_inside_event_recall": ("confirmed_new_alarm_inside_events", "true_events"),
        "complete_event_coverage": ("complete_detected_events", "complete_events"),
        "complete_confirmed_new_alarm_start_recall": ("complete_confirmed_new_alarm_inside_events", "complete_events"),
    }
    rows = []
    for label, key, fmt in definitions:
        values = []
        for result in (validation, test):
            if key in event_counts:
                numerator, denominator = event_counts[key]
                values.append(f'<bdi>{number(result.get(numerator))} / {number(result.get(denominator))}</bdi> حدث')
            else:
                values.append(fmt(result.get(key)))
        rows.append([label, *values])
    return table(["المقياس", "التحقق Validation", "الاختبار المحجوب Test"], rows)


def outcome(test):
    rate = test.get("false_alarm_runs_per_normal_day")
    duration = test.get("normal_time_under_alarm")
    recall = test.get("recall")
    if not all(numeric(v) for v in (rate, duration, recall)):
        return "warn", "نتيجة غير حاسمة", "تعذر حساب واحد أو أكثر من مقاييس التشغيل والاستدعاء؛ لا يصح إعلان تحقيق الأهداف."
    failures = []
    if rate > 1:
        failures.append("تجاوز مقطع إنذار كاذب واحد لكل يوم طبيعي متاح")
    if duration > .01:
        failures.append("تجاوز 1% من الوقت الطبيعي المتاح تحت إنذار كاذب")
    if recall <= 0:
        failures.append("لم يكتشف أي دقيقة شاذة قابلة للتقييم")
    if failures:
        return "fail", "لم يحقق الاختبار أهداف خط الأساس", "؛ ".join(failures) + "."
    return "pass", "حقق قيود التشغيل المحددة مع استدعاء غير صفري", (
        "هذه نتيجة محدودة بهذا الاختبار: لم يتجاوز سقفي الإنذار الكاذب، واستدعاء الدقائق الشاذة "
        + percent(recall) + ". لم يُحدَّد مسبقاً حد قبول مرتفع للاستدعاء؛ لذلك لا تعني النتيجة كفاية الكشف أو الجاهزية الهندسية.")


def build_report(out, manifest, frozen, validation, test, predictions, sweep, embedded):
    state, title, explanation = outcome(test)
    split_names = {"train":"التدريب", "validation":"التحقق واختيار العتبة", "test":"الاختبار المحجوب"}
    split_rows = []
    for key in ("train", "validation", "test"):
        s = manifest["splits"][key]
        split_rows.append([split_names[key], f'<bdi>{s["first_row_id"]:,}–{s["last_row_id"]:,}</bdi>',
                           number(s["rows"]), number(s["eligible_rows"]), number(s["raw_incomplete_rows"]),
                           number(s["original_event_minutes"]), number(s["fit_rows"])])
    split_table = table(["القسم", "معرّفات المصدر", "الدقائق", "متاحة للتقييم", "قياس خام ناقص", "دقائق EVENT", "دقائق ملاءمة النموذج"], split_rows)
    confusion = table(["العدد على الدقائق المتاحة فقط", "Validation", "Test"],
                      [[label, number(validation[key]), number(test[key])] for label,key in [
                          ("TP — شاذة مع إنذار", "tp"), ("FP — طبيعية مع إنذار", "fp"),
                          ("FN — شاذة دون إنذار", "fn"), ("TN — طبيعية دون إنذار", "tn")]])
    targets = table(["الهدف المحدد", "نتيجة Test", "الحكم"], [
        ["≤ 1 مقطع إنذار كاذب / يوم طبيعي متاح", number(test.get("false_alarm_runs_per_normal_day"), 3),
         "متحقق" if numeric(test.get("false_alarm_runs_per_normal_day")) and test["false_alarm_runs_per_normal_day"] <= 1 else "غير متحقق أو غير قابل للحساب"],
        ["≤ 1% من الوقت الطبيعي المتاح تحت إنذار", percent(test.get("normal_time_under_alarm")),
         "متحقق" if numeric(test.get("normal_time_under_alarm")) and test["normal_time_under_alarm"] <= .01 else "غير متحقق أو غير قابل للحساب"],
        ["استدعاء غير صفري؛ لا يوجد حد قبول هندسي محدد", percent(test.get("recall")),
         "غير صفري" if numeric(test.get("recall")) and test["recall"] > 0 else "صفر أو غير معرّف"]])
    quality = manifest.get("quality", {})
    missing_table = table(["القناة", "القيم المفقودة في المصدر"],
                          [[esc(k), number(v)] for k,v in quality.get("missing_by_channel", {}).items()])
    reference = test.get("all_normal_reference", {})
    reference_table = table(["مقارنة Test", "Accuracy", "Recall", "F1"], [
        ["النموذج المجمد", percent(test.get("accuracy")), percent(test.get("recall")), percent(test.get("f1"))],
        ["مرجع يتنبأ بالطبيعي دائماً على الدقائق المتاحة", percent(reference.get("accuracy")),
         percent(reference.get("recall")), percent(reference.get("f1"))]])
    runtime = test.get("runtime", {})
    runtime_table = table(["قياس على جهاز التنفيذ المحلي فقط", "القيمة"], [
        ["النظام", esc(runtime.get("system", "غير مسجل"))],
        ["المعمارية", esc(runtime.get("machine", "غير مسجل"))],
        ["وقت ملاءمة النموذج، ثانية", number(frozen.get("fit_seconds"), 2)],
        ["التقييم الدفعي للاختبار، ثانية", number(runtime.get("batch_scoring_seconds"), 2)],
        ["وسيط تقييم صف منفرد، مللي ثانية", number(runtime.get("single_row_median_ms"), 2)],
        ["المئين 95 لتقييم صف منفرد، مللي ثانية", number(runtime.get("single_row_p95_ms"), 2)],
        ["عدد صفوف قياس الزمن المنفرد", number(runtime.get("single_row_benchmark_count"))],
        ["حجم النموذج، MiB", number(frozen.get("model_size_bytes", 0)/(1024**2), 2)]])
    hashes = table(["الأثر المسجّل وقت التجميد", "SHA-256"],
                   [[label, '<code class="hash">'+esc(frozen.get(key, "غير مسجل"))+"</code>"]
                    for label,key in [("المصدر", "source_sha256"), ("البروتوكول", "protocol_sha256"),
                                      ("شفرة التدريب", "training_code_sha256"), ("شفرة المقاييس", "metrics_code_sha256"),
                                      ("النموذج", "model_sha256")]])
    features = frozen.get("features", manifest.get("features", []))
    channel_count = len({name.split("__", 1)[0] for name in features})
    versions = " · ".join(f"{k} {v}" for k,v in manifest.get("versions", {}).items())
    selected = np.isclose(sweep["threshold"].to_numpy(), frozen["threshold"], rtol=1e-12, atol=1e-15)
    threshold_note = "توجد العتبة المجمدة في سجل بحث التحقق." if selected.any() else "تنبيه: لم تظهر العتبة المجمدة ضمن سجل البحث المقروء."
    best_logged = sweep.loc[sweep["f1"].idxmax()]
    test_days = manifest["splits"]["test"]["nominal_days"]
    test_event_minutes = manifest["splits"]["test"]["original_event_minutes"]
    event_note = (
        f'ضم الاختبار {number(test.get("true_events"))} حدثاً متصلاً، بإجمالي {number(test_event_minutes)} دقيقة موسومة، '
        f'خلال {number(test_days, 2)} يوماً اسمياً. غُطّي {number(test.get("detected_events"))} من {number(test.get("true_events"))} '
        f'حدث؛ وفي التحقق غُطّي {number(validation.get("detected_events"))} من {number(validation.get("true_events"))}. '
        'عدد الأحداث صغير جداً لتعميم قدرة اكتشاف الأحداث؛ تُعرض الأعداد صراحةً ولا تُسوّق كنسبة نجاح.'
    )
    single_event_note = ""
    if test.get("true_events") == 1 and test.get("event_records"):
        record = test["event_records"][0]
        if record.get("alarm_started_at_onset") and record.get("confirmed_new_alarm_inside_event"):
            single_event_note = "في حدث الاختبار الوحيد بدأت بالفعل إشارة إنذار مؤكدة عند أول عينة موسومة. التأخر المسجل صفر دقيقة على دقة عينة واحدة كل دقيقة؛ لا يثبت استجابة فورية أو أقل من ثانية أو زمن إغلاق صمام."
    source_rows = number(manifest["source_rows"])
    return f'''<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>مورد — نتائج خط الأساس GECCO</title><style>
:root{{--ink:#173239;--muted:#5b6b70;--teal:#0d665e;--line:#dbe5e5;--paper:#fff;--bg:#f1f5f4;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Tahoma,Arial,sans-serif;line-height:1.85;font-size:15px}}
main{{max-width:1100px;margin:32px auto;padding:38px 46px;background:white;border-top:7px solid var(--teal);box-shadow:0 8px 40px #17323910}}
header{{padding-bottom:20px;border-bottom:1px solid var(--line)}}.eyebrow{{font-size:13px;color:var(--teal);letter-spacing:.03em}}h1{{font-size:31px;line-height:1.45;margin:9px 0}}h2{{font-size:21px;margin:32px 0 12px}}h3{{font-size:17px;margin:18px 0 7px}}p{{margin:10px 0}}.muted,.caption{{color:var(--muted);font-size:13px}}.status{{padding:18px 22px;border:1px solid;border-radius:8px;margin:24px 0}}.status h2{{margin:0 0 7px}}.fail{{background:#fff1ee;border-color:#d18f80}}.pass{{background:#eef7f3;border-color:#80b4a2}}.warn{{background:#fff7e8;border-color:#c8a464}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:22px 0}}.card{{padding:15px;border:1px solid var(--line);border-radius:7px}}.card strong{{display:block;font-size:25px;color:var(--teal)}}.table-wrap{{overflow:auto;margin:12px 0}}table{{width:100%;border-collapse:collapse;font-size:13px;line-height:1.65}}th{{background:#eaf2f1;text-align:right;color:#234e4a}}th,td{{padding:9px 11px;border-bottom:1px solid var(--line);vertical-align:top}}tbody tr:nth-child(even){{background:#f8faf9}}td:not(:first-child){{font-variant-numeric:tabular-nums}}ul,ol{{padding-right:25px}}li{{margin:8px 0}}figure{{margin:20px 0}}img{{display:block;width:100%;height:auto}}a{{color:#0b6a65;text-decoration:none;border-bottom:1px solid #9cc8c2}}code,pre{{direction:ltr;unicode-bidi:embed;font-family:ui-monospace,Menlo,monospace;font-size:12px}}pre{{text-align:left;overflow:auto;background:#f3f6f5;padding:16px;line-height:1.7;border:1px solid var(--line)}}.hash{{display:block;word-break:break-all}}.note{{border-right:4px solid #80a6a1;background:#f1f7f5;padding:12px 16px}}footer{{border-top:1px solid var(--line);padding-top:15px;margin-top:32px}}@media(max-width:700px){{main{{margin:0;padding:24px 18px}}h1{{font-size:25px}}.cards{{grid-template-columns:1fr}}table{{font-size:12px}}}}
@page{{size:A4;margin:15mm 13mm}}@media print{{body{{background:white;font-size:10pt}}main{{padding:0;margin:0;box-shadow:none;border-top:4px solid var(--teal);max-width:none}}h1{{font-size:23pt}}h2{{font-size:15pt;break-after:avoid}}h3{{break-after:avoid}}.status,.card,figure,tr{{break-inside:avoid}}table{{font-size:8.5pt}}th,td{{padding:6px}}thead{{display:table-header-group}}.table-wrap{{overflow:visible}}a{{color:inherit;border:0}}pre{{white-space:pre-wrap;word-break:break-word;font-size:8pt}}.cards{{gap:8px}}.hash{{font-size:7.5pt}}}}
</style></head><body><main>
<header><div class="eyebrow">مورد · نموذج تجريبي أول · نتائج فعلية من ملفات التشغيل</div>
<h1>كشف الشذوذ في حساسات المياه<br>تقرير خط الأساس GECCO 2018</h1>
<p>خط أساس قابل لإعادة التشغيل: <bdi>{esc(manifest.get("experiment", "gecco-baseline-v1"))}</bdi> باستخدام Isolation Forest؛ {number(channel_count)} قنوات تنتج {number(len(features))} ميزة سببية. العتبة اختيرت من التحقق ثم جُمّدت قبل الاختبار.</p>
<p class="muted">وقت التجميد كما سُجّل (UTC): <bdi>{esc(frozen.get("frozen_at_utc", "غير مسجل"))}</bdi><br>وقت تقييم الاختبار (UTC): <bdi>{esc(test.get("scored_at_utc", "غير مسجل"))}</bdi></p></header>
<section class="status {state}"><h2>{title}</h2><p>{explanation}</p><p>هذا حكم على تجربة كشف شذوذ في بيانات منشورة؛ ليس اعتماد سلامة للمياه أو إثباتاً لعمل مورد في الميدان.</p></section>
<div class="cards"><div class="card">استدعاء دقائق الاختبار<strong>{percent(test.get("recall"))}</strong></div><div class="card">الإنذارات الكاذبة / يوم طبيعي متاح<strong>{number(test.get("false_alarm_runs_per_normal_day"), 3)}</strong></div><div class="card">الوقت الطبيعي تحت إنذار كاذب<strong>{percent(test.get("normal_time_under_alarm"))}</strong></div></div>
<p class="note">{event_note}</p>
<h2>1. ما اختُبر وما بقي خارج التجربة</h2>
<p>المدخلات قراءات حساسات من بيانات GECCO المنشورة على <a href="https://zenodo.org/records/3884398">Zenodo</a>، بعلامة حدث ثنائية <code>EVENT</code>. النموذج يتعلم من نوافذ التدريب الطبيعية المكتملة، ثم يعطي درجة شذوذ؛ القرار إنذار عندما تبلغ الدرجة العتبة المجمدة أو تتجاوزها.</p>
<p class="note">هذه ليست تجربة تصنيف أنواع الأعطال الخمسة، ولا قياساً للبكتيريا أو مطابقة مياه الري، ولا اختباراً على Raspberry Pi، ولا تجربة على مياه وضوء حقيقية. علامات EVENT لا تثبت سبب كل حدث أو أنه عطل حساس تحديداً.</p>
<h2>2. البيانات والتقسيم ومنع تسرب المستقبل</h2>
<p>المصدر يحتوي {source_rows} صفاً. استُخدم ترتيب المعرّفات الأصلي، مع استبعاد {number(manifest.get("excluded_gap_rows"))} صفاً في فجوتي الفصل. يبدأ حساب النوافذ من داخل كل قسم، ولا تمتد نافذة عبر حد التقسيم. الميزات: قيمة كل قناة، مقدار تغير الدقيقة السابقة، البعد عن المتوسط المتحرك، والانحراف المعياري المتحرك؛ النوافذ سببية وتشمل الدقيقة الحالية.</p>
{split_table}
<p>تظهر الساعة المحلية مكررة في المصدر؛ عدد القيم الزمنية المكررة الإضافية {number(quality.get("duplicate_wall_clock_values"))}، ومعرّف بداية انقلاب الساعة <bdi>{esc(", ".join(map(str, manifest.get("clock_reversal_row_ids", []))))}</bdi>. لا يعاد ترتيب الزمن المحلي ولا حذف الدقائق المكررة. «اليوم» في الحساب هو 1,440 عينة اسمية؛ لم يُعاد بناء UTC.</p>
<details><summary>القيم المفقودة بحسب القناة في كامل المصدر</summary>{missing_table}</details>
<p>الدقائق ذات قياس ناقص، أو نافذة ميزات ناقصة، أو فترة إحماء لا تنتج تنبؤاً (<code>-1</code>). لا تعوّض بقيم مستقبلية ولا تُحسب طبيعية. جدول النتائج يعرض مقدار التغطية؛ مصفوفة الالتباس تستبعد غير المتاح، بينما مقام تغطية الأحداث يبقي جميع الأحداث الأصلية.</p>
<h2>3. اختيار العتبة والحكم على الاختبار</h2>
<p>العتبة المجمدة <code>{frozen["threshold"]:.12g}</code>. بحث التحقق المسجّل يضم {number(len(sweep))} عتبة، واختيرت أعلى F1 بين المرشحين الملتزمين بسقفي الإنذار الكاذب؛ عند التعادل يقل عدد FP ثم ترتفع العتبة. {threshold_note} لم يستخدم الاختبار لاختيار العتبة، ولم ينفذ هذا التقرير أي بحث جديد.</p>
<p>تفسير المقايضة من سجل التحقق فقط: أعلى F1 مسجلة دون فرض قيدي الإنذار كانت {percent(best_logged["f1"])}, مع {number(best_logged["false_alarm_runs_per_normal_day"], 2)} مقطع إنذار كاذب لكل يوم طبيعي متاح. أما العتبة المختارة فحققت F1 قدرها {percent(validation.get("f1"))} في التحقق. هذه قراءة للسجل السابق تفسّر تحفظ العتبة؛ ليست نتيجة اختبار ولا تقييماً لنموذج بديل، ولم تُستخدم لتغيير العتبة بعد الاختبار.</p>
{targets}
<figure><img src="data:image/png;base64,{embedded}" alt="مقارنة Precision وRecall وF1 بين التحقق والاختبار، ثم خط زمني لدرجات الاختبار مع العتبة والأحداث والإنذارات الكاذبة"><figcaption class="caption">الرسم من النتائج والتنبؤات المحفوظة؛ المقاييس على الدقائق المتاحة فقط. الخلفية الزرقاء للأحداث الأصلية، والحمراء لنقاط الإنذار الكاذب، والرمادية لغياب التنبؤ. <a href="overview.png">تنزيل الرسم PNG</a>.</figcaption></figure>
<h2>4. المقاييس الكاملة: التحقق مقابل الاختبار</h2>
{metric_table(validation, test)}
<h3>كيف تُقرأ تغطية الأحداث والبدايات الجديدة؟</h3>
<p><strong>تغطية الحدث</strong> تعني وجود أي دقيقة إنذار داخل مدته. قد يكون الإنذار قد بدأ قبل الحدث واستمر خلاله؛ لذلك لا تعني التغطية إطلاق إنذار جديد عند كل حدث. <strong>البداية المؤكدة الجديدة</strong> تستلزم انتقالاً معروفاً من 0 إلى 1 داخل الحدث. البداية بعد فقد التنبؤ (<code>-1→1</code>) أو عند أول صف لا تُحتسب بداية مؤكدة. المقياس الخام يعرض هذه الحالات بصورة منفصلة.</p>
<p>الأحداث التي تلامس أول القسم أو آخره موضحة كأحداث عند الحدود؛ تُعرض أيضاً مقاييس الأحداث الكاملة. تأخر الكشف هو زمن أول تغطية للأحداث المغطاة فقط، وقد يكون صفراً لأن إنذاراً سابقاً كان نشطاً. لا يساوي هذا زمن استجابة صمام أو قياس تأخر هندسي.</p>
<p class="note">{single_event_note}</p>
<p>مقطع الإنذار الكاذب سلسلة متصلة من دقائق الإنذار خارج أحداث الحقيقة؛ حدود الحدث وغياب التنبؤ تفصل المقاطع، بما في ذلك ذيل إنذار طويل بعد نهاية الحدث. المقام اليومي هو زمن القياس الطبيعي المتاح، لا إجمالي أيام التقويم. نسبة الوقت الكاذب = FP ÷ الدقائق الطبيعية المتاحة.</p>
<h3>مصفوفة الالتباس على الدقائق المتاحة</h3>{confusion}
<h3>لماذا لا تكفي Accuracy مرتفعة؟</h3>{reference_table}
<p>قد يحقق التنبؤ بالطبيعي دائماً Accuracy مرتفعة عندما تكون الدقائق الطبيعية أكثر عدداً، مع فقد جميع الدقائق الشاذة. حتى Accuracy بنسبة 99% وحدها لا تعني نجاح الكشف؛ تُقرأ معها Precision وRecall وF1 وعبء الإنذار وتغطية القياس.</p>
<h2>5. حدود الدليل وما تعنيه لمورد</h2>
<ul><li>هذه نتيجة مجموعة واحدة وتقسيم زمني واحد؛ ليست تقديراً مستقلاً للأداء في كل محطة أو موسم.</li><li>الوحدة الزمنية دقيقة، فلا تختبر البيانات شرط الإغلاق خلال 10 ثوانٍ. لا يوجد اختبار صمام أو سلسلة أمان كهربائية في هذه التجربة.</li><li>الدرجات الشاذة لا تعيّن نوع العطل ولا تفرّق وحدها بين عطل حساس وتغير حقيقي في الماء. هذا يحتاج وسوماً وتجارب إضافية.</li><li>نجاح حدود الإنذار الكاذب، إن تحقق، لا يكفي لقبول السلامة؛ لا يوجد في هذه التجربة حد قبول هندسي مسبق مرتفع للاستدعاء.</li><li>عدم توفر تنبؤ حالة معلنة وليست موافقة على جودة الماء. تحديد التصرف الآمن في الجهاز عمل هندسي منفصل.</li><li>أي تعديل للنموذج أو العتبة بعد مشاهدة الاختبار يصبح تجربة لاحقة، ويحتاج اختباراً مستقلاً جديداً؛ لا يعاد استخدام هذه النتيجة بوصفها اختباراً محجوباً لاختيار لاحق.</li></ul>
<h2>6. الأداء الحاسوبي المحلي</h2>{runtime_table}
<p>هذه الأزمنة على جهاز التنفيذ المسجل فقط، ولا تشمل تجهيز الميزات أو قراءة الحساسات أو الاتصال أو الصمام. لم تُقَس على Raspberry Pi. حجم النموذج وزمنه لا يثبتان قابلية نشره على الجهاز دون قياس مستقل.</p>
<h2>7. الملفات وإعادة إصدار التقرير</h2>
<p><a href="model.joblib">النموذج المجمد</a> · <a href="data_manifest.json">بيان البيانات والتقسيم</a> · <a href="freeze.json">سجل التجميد</a> · <a href="test_predictions.csv.gz">تنبؤات الاختبار الكاملة</a> · <a href="test_results.json">مقاييس الاختبار JSON</a> · <a href="validation_results.json">مقاييس التحقق JSON</a> · <a href="validation_threshold_sweep.csv">بحث العتبة على التحقق</a></p>
<p>يقرأ هذا التقرير ستة ملفات نتائج فقط؛ لا يحمّل النموذج ولا يعيد التدريب أو التنبؤ أو اختيار العتبة. تحقّق من تطابق معرّفات حدود الاختبار وعدد التنبؤات والعتبة وبصمتي المصدر والبروتوكول بين البيانات المقروءة. البصمات التالية من سجل التجميد؛ لا يدّعي التقرير أنه أعاد حساب بصمة النموذج.</p>
{hashes}
<p class="muted"><bdi>{esc(versions)}</bdi></p>
<p>لإعادة إصدار HTML والرسم من النتائج القائمة، من جذر المشروع:</p>
<pre>ml/gecco_baseline/.venv/bin/python ml/gecco_baseline/make_report.py</pre>
<p>مراحل التشغيل الأصلية هي <code>prepare</code> ثم <code>train</code> ثم <code>test</code> في <code>run_baseline.py</code>. التشغيل المحفوظ يرفض استبدال نموذج مجمد أو إعادة فتح اختبار مسجّل. إعادة تجربة مستقلة تتطلب إصداراً ومجلد نتائج جديدين مع بروتوكول محدد قبل تقييم الاختبار.</p>
<footer class="muted">مورد · تقرير تجربة أولية قابل للمراجعة. القيم غير القابلة للحساب معروضة «غير معرّف» ولا تستبدل بأصفار. صورة النتائج مضمنة داخل HTML؛ الروابط إلى الأدلة تحتاج بقاء الملفات بجواره.</footer>
</main></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    data = read_inputs(out)
    manifest, frozen = data["data_manifest.json"], data["freeze.json"]
    validation, test = data["validation_results.json"], data["test_results.json"]
    predictions, sweep = data["test_predictions.csv.gz"], data["validation_threshold_sweep.csv"]
    check_consistency(manifest, frozen, test, predictions)
    embedded = plot_overview(out, validation, test, frozen, predictions)
    rendered = build_report(out, manifest, frozen, validation, test, predictions, sweep, embedded)
    (out / "report.html").write_text(rendered, encoding="utf-8")
    print(json.dumps({"report": str(out/"report.html"), "overview": str(out/"overview.png"),
                      "outcome": outcome(test)[1]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
