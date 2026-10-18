"""Render the frozen V2 comparison from result JSON files only.

This script never reads raw datasets, labels, prediction CSVs, or model files.
It requires all six 2018 folds, their freezes, the aggregate result, and the
2019 final result/freeze. It does not train, rescore, select, or tune anything.
Outputs: report.html (standalone embedded PNG), overview.png, report_summary.json.
Run only after the experiment owner confirms the final results are available.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "output/ml/gecco-v2"
MODEL_NAMES = {"baseline": "خط الأساس", "extra_trees": "ExtraTrees",
               "hist_gradient_boosting": "HistGradientBoosting",
               "logistic": "Logistic Regression",
               "if_normalized_changes_w30": "Isolation Forest · normalized changes"}
METRIC_FIELDS = ("sample_count", "valid_count", "unavailable_count", "prediction_coverage",
                 "precision", "recall", "f1", "tp", "fp", "fn", "tn", "true_events",
                 "detected_events", "confirmed_new_alarm_inside_events",
                 "confirmed_new_alarm_inside_event_recall", "false_positive_runs",
                 "false_alarm_runs_per_normal_day", "normal_time_under_alarm",
                 "median_detection_delay_minutes")


def esc(value):
    return html.escape(str(value), quote=True)


def finite(value):
    return value is not None and math.isfinite(float(value))


def number(value, digits=0):
    return f"{value:,.{digits}f}" if finite(value) else "غير قابل للقياس"


def pct(value):
    return f"{100*value:.2f}%" if finite(value) else "غير قابل للقياس"


def event_count(result, numerator="confirmed_new_alarm_inside_events", denominator="true_events"):
    n, d = result.get(numerator), result.get(denominator)
    if not d:
        return "غير قابل للقياس — 0 أحداث"
    return f'<bdi>{number(n)} / {number(d)}</bdi> حدث'


def table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + "".join(
        "<th>" + esc(h) + "</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join("<td>" + str(cell) + "</td>" for cell in row) + "</tr>"
        for row in rows) + "</tbody></table></div>"


def load_required(out):
    paths = ["walk_forward_results.json"]
    paths += [f"fold_{fold}/{name}.json" for fold in range(1, 7) for name in ("test_results", "freeze")]
    paths += [f"external_2019/{name}.json" for name in ("test_results", "freeze")]
    missing = [p for p in paths if not (out/p).is_file()]
    if missing:
        raise SystemExit("Final results incomplete; report not generated. Missing: " + ", ".join(missing))
    # A strict allowlist: no raw data, label columns, prediction files or models.
    contents = {p: json.loads((out/p).read_text(encoding="utf-8")) for p in paths}
    walk = contents["walk_forward_results.json"]
    folds = [{"name": f"fold_{i}", "results": contents[f"fold_{i}/test_results.json"],
              "freeze": contents[f"fold_{i}/freeze.json"]} for i in range(1, 7)]
    external = {"name": "external_2019", "results": contents["external_2019/test_results.json"],
                "freeze": contents["external_2019/freeze.json"]}
    for result in [walk] + [f["results"] for f in folds] + [external["results"]]:
        for scope in ("native", "common"):
            for role in ("baseline", "v2"):
                absent = set(METRIC_FIELDS)-set(result[scope][role])
                if absent:
                    raise ValueError(f"Incomplete metrics for {scope}/{role}: {sorted(absent)}")
            if result[scope]["baseline"]["sample_count"] != result[scope]["v2"]["sample_count"]:
                raise ValueError("Models were not evaluated on the same full time axis")
        if result["common"]["baseline"]["valid_count"] != result["common"]["v2"]["valid_count"]:
            raise ValueError("Common-available exposure differs between models")
    for partition in folds+[external]:
        frozen, result = partition["freeze"], partition["results"]
        if frozen.get("test_used_for_selection") is not False:
            raise ValueError("Freeze does not confirm exclusion of test from selection")
        if frozen["protocol_sha256"] != walk["protocol_sha256"]:
            raise ValueError("Partitions refer to different frozen protocols")
        if frozen["selected"]["family"] != result["selected_family"]:
            raise ValueError("Saved result family differs from its frozen selection")
        if datetime.fromisoformat(frozen["frozen_at_utc"]) > datetime.fromisoformat(result["scored_at_utc"]):
            raise ValueError("A result is dated before its freeze")
    return walk, folds, external


def target_status(result):
    rate, duration = result.get("false_alarm_runs_per_normal_day"), result.get("normal_time_under_alarm")
    if not finite(rate) or not finite(duration):
        return None
    return bool(rate <= 1 and duration <= .01)


def compact_result(result):
    return {k:v for k,v in result.items() if not k.endswith("records")}


def comparison(result):
    baseline, v2 = result["common"]["baseline"], result["common"]["v2"]
    delta = (v2["f1"]-baseline["f1"])*100 if finite(v2["f1"]) and finite(baseline["f1"]) else None
    confirmed_delta = (v2["confirmed_new_alarm_inside_events"]-baseline["confirmed_new_alarm_inside_events"])
    return {"common": {"baseline": compact_result(baseline), "v2": compact_result(v2)},
            "native": {role:compact_result(result["native"][role]) for role in ("baseline", "v2")},
            "f1_delta_percentage_points": delta, "confirmed_event_count_delta": confirmed_delta,
            "v2_common_operating_targets_met": target_status(v2),
            "v2_native_operating_targets_met": target_status(result["native"]["v2"])}


def verdict(result):
    b, v = result["common"]["baseline"], result["common"]["v2"]
    checks = target_status(v)
    if v["true_events"] == 0:
        title = "لا توجد أحداث لقياس تحسن الكشف في هذه الفترة"
        body = "يمكن قياس عبء الإنذار الكاذب والتغطية، لكن استدعاء الأحداث غير قابل للقياس؛ الصفر ليس دليلاً على غياب المخاطر."
        return "neutral", title, body
    if not finite(v["f1"]) or not finite(b["f1"]):
        return "neutral", "لا تكفي المقاييس المتاحة لحكم مقارنة مكتمل", "بعض النسب غير قابلة للحساب؛ تُعرض مقامات الأحداث والدقائق المتاحة أدناه."
    delta = (v["f1"]-b["f1"])*100
    if delta > 1e-8:
        title = f"ارتفع F1 بمقدار {number(delta, 2)} نقطة مئوية"
    elif delta < -1e-8:
        title = f"انخفض F1 بمقدار {number(-delta, 2)} نقطة مئوية"
    else:
        title = "لم يتغير F1 على الدقائق المشتركة"
    event_text = (f'البدايات المؤكدة الجديدة: {number(v["confirmed_new_alarm_inside_events"])} من '
                  f'{number(v["true_events"])} حدثاً لـV2، مقابل {number(b["confirmed_new_alarm_inside_events"])} '
                  f'من {number(b["true_events"])} لخط الأساس.')
    if checks is True:
        body = "تحقّق سقفا عبء الإنذار الكاذب على الدقائق المشتركة. " + event_text
    elif checks is False:
        title += "؛ ولم تتحقق قيود الإنذار الكاذب كاملة"
        body = "تجاوزت V2 واحداً أو كلا السقفين: مقطع كاذب واحد لكل يوم طبيعي متاح، و1% من وقته. " + event_text
    else:
        body = "تعذر الحكم على أحد سقفي عبء الإنذار الكاذب. " + event_text
    style = "good" if delta > 0 and checks is True and v["confirmed_new_alarm_inside_events"] >= b["confirmed_new_alarm_inside_events"] else "caution"
    return style, title, body


def metrics_table(result, scope="common"):
    b, v = result[scope]["baseline"], result[scope]["v2"]
    rows = []
    for label, key, formatter in [
        ("Precision — دقة الإنذارات", "precision", pct),
        ("Recall — استدعاء الدقائق الموسومة المتاحة", "recall", pct),
        ("F1 — دون تعديل النقاط أو توسيع العلامات", "f1", pct),
        ("عدد مقاطع الإنذار الكاذب", "false_positive_runs", number),
        ("مقاطع كاذبة / يوم طبيعي متاح", "false_alarm_runs_per_normal_day", lambda x:number(x, 3)),
        ("دقائق الإنذار الكاذب FP", "fp", number),
        ("الوقت الطبيعي المتاح تحت إنذار كاذب", "normal_time_under_alarm", pct),
        ("دقائق شاذة مع إنذار TP", "tp", number),
        ("دقائق شاذة دون إنذار FN", "fn", number),
        ("دقائق طبيعية دون إنذار TN", "tn", number),
        ("تغطية القرار — من كامل المحور الزمني", "prediction_coverage", pct),
        ("دقائق دون قرار -1", "unavailable_count", number),
        ("زمن طبيعي متاح، أيام اسمية", "eligible_normal_days", lambda x:number(x, 3)),
        ("وسيط تأخر أول تغطية، دقائق — للأحداث المغطاة فقط", "median_detection_delay_minutes", lambda x:number(x, 2)),
        ("المئين 95 لتأخر أول تغطية، دقائق", "p95_detection_delay_minutes", lambda x:number(x, 2)),
    ]:
        rows.append([label, formatter(b.get(key)), formatter(v.get(key))])
    rows[3:3] = [
        ["أحداث تغطيها أي إشارة إنذار", event_count(b,"detected_events"),event_count(v,"detected_events")],
        ["أحداث ببداية مؤكدة جديدة 0→1", event_count(b), event_count(v)],
        ["أحداث كاملة ببداية مؤكدة جديدة", event_count(b,"complete_confirmed_new_alarm_inside_events","complete_events"),
          event_count(v,"complete_confirmed_new_alarm_inside_events","complete_events")],
        ["أحداث لا تتوفر لها أي دقيقة قابلة للتقييم", number(b.get("fully_unscorable_events")),number(v.get("fully_unscorable_events"))],
        ["أحداث تلامس حدود محور التقييم", number(b.get("boundary_censored_events")), number(v.get("boundary_censored_events"))],
    ]
    return table(["المقياس", "خط الأساس المعاد تدريبه", "V2 — اختيار من الماضي فقط"], rows)


def coverage_table(result):
    rows = []
    for role, label in (("baseline", "خط الأساس"), ("v2", "V2")):
        r = result["native"][role]
        rows.append([label, number(r["sample_count"]), number(r["valid_count"]),
                     number(r["unavailable_count"]), pct(r["prediction_coverage"]),
                     pct(r["precision"]), pct(r["recall"]), pct(r["f1"])])
    return table(["النموذج", "إجمالي الدقائق", "قرار متاح", "غير متاح", "التغطية الأصلية", "Precision", "Recall", "F1"], rows)


def operational_table(result):
    rows=[]
    for scope,label in (("common","المشترك"),("native","الأصلي لكل نموذج")):
        for role,name in (("baseline","خط الأساس"),("v2","V2")):
            r=result[scope][role]
            state=target_status(r)
            rows.append([label,name,number(r["false_positive_runs"]),number(r["false_alarm_runs_per_normal_day"],3),
                         number(r["fp"]),pct(r["normal_time_under_alarm"]),
                         "متحققان" if state is True else "غير متحققين معاً" if state is False else "غير قابل للقياس"])
    return table(["نطاق المقارنة","النموذج","مقاطع كاذبة","مقاطع / يوم","دقائق كاذبة","نسبة الوقت الكاذب","السقفان"],rows)


def fold_table(folds):
    rows=[]
    for index,partition in enumerate(folds,1):
        r, frozen=partition["results"],partition["freeze"]
        b,v=r["common"]["baseline"],r["common"]["v2"]
        selected=frozen["selected"]
        rows.append([f"{index} · {30+index*10}–{40+index*10}%",esc(MODEL_NAMES.get(selected["family"],selected["family"])),
                     f'<bdi>{esc(selected["policy"])}</bdi>',number(v["true_events"]),
                     f'<bdi>{pct(b["f1"])} → {pct(v["f1"])}</bdi>',
                     f'<bdi>{number(b["confirmed_new_alarm_inside_events"])} → {number(v["confirmed_new_alarm_inside_events"])}</bdi>' if v["true_events"] else "غير قابل للقياس",
                     f'<bdi>{number(b["false_alarm_runs_per_normal_day"],2)} → {number(v["false_alarm_runs_per_normal_day"],2)}</bdi>',
                     pct(r["native"]["v2"]["prediction_coverage"])])
    return table(["الفترة من 2018","العائلة المختارة مسبقاً","السياسة","الأحداث","F1: أساس → V2","بدايات مؤكدة: أساس → V2","كاذب/يوم: أساس → V2","تغطية V2 الأصلية"],rows)


def plot_folds(out,folds):
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,
                         "axes.spines.top":False,"axes.spines.right":False})
    fig,axes=plt.subplots(3,1,figsize=(12.5,10.4),sharex=True,layout="constrained")
    x=np.arange(1,7)
    for role,label,color,marker in [("baseline","Baseline (refit)","#71869e","o"),
                                    ("v2","V2 (past-selected)","#087b6d","s")]:
        metrics=[p["results"]["common"][role] for p in folds]
        f1=[m["f1"] if m["true_events"] and finite(m["f1"]) else np.nan for m in metrics]
        event=[m["confirmed_new_alarm_inside_event_recall"] if m["true_events"] else np.nan for m in metrics]
        rate=[m["false_alarm_runs_per_normal_day"] if finite(m["false_alarm_runs_per_normal_day"]) else np.nan for m in metrics]
        for ax,values in zip(axes,[f1,event,rate]):
            ax.plot(x,values,color=color,marker=marker,lw=2,ms=7,label=label)
        for i,m in enumerate(metrics):
            if m["true_events"]:
                offset=13 if role=="v2" else -20
                axes[1].annotate(f'{m["confirmed_new_alarm_inside_events"]}/{m["true_events"]}',
                                 (x[i],event[i]),textcoords="offset points",xytext=(0,offset),
                                 ha="center",fontsize=9,color=color,
                                 bbox={"boxstyle":"round,pad=.15","facecolor":"white","alpha":.8,"edgecolor":"none"})
    for i,p in enumerate(folds):
        if p["results"]["common"]["v2"]["true_events"]==0:
            for ax in axes[:2]:
                ax.text(x[i],.45,"N/A\n0 events",ha="center",va="center",color="#666",fontsize=9)
    axes[0].set_title("A. Unadjusted point F1 — common-available minutes",loc="left",weight="bold")
    axes[0].set_ylabel("F1")
    axes[1].set_title("B. Confirmed new alarm starts inside original events",loc="left",weight="bold")
    axes[1].set_ylabel("Event-start recall")
    axes[2].set_title("C. False-alarm segments per eligible normal day",loc="left",weight="bold")
    axes[2].set_ylabel("False segments / day")
    axes[2].axhline(1,color="#bd663c",ls="--",lw=1.4,label="Operating target ≤ 1/day")
    for ax in axes[:2]:
        ax.set_ylim(-.12,1.16)
        ax.set_yticks(np.arange(0,1.01,.2))
    axes[2].set_ylim(bottom=0)
    for ax in axes:
        ax.grid(alpha=.16)
        ax.set_xlim(.65,6.35)
    axes[0].legend(loc="upper left",frameon=False,ncol=2)
    axes[2].legend(loc="upper left",frameon=False,fontsize=9)
    axes[2].set_xticks(x,[f"Fold {i}\n{30+i*10}–{40+i*10}%" for i in x])
    axes[2].set_xlabel("2018 chronological test periods (retrospective; no outer-driven model selection)")
    buffer=io.BytesIO()
    fig.savefig(buffer,format="png",dpi=180,facecolor="white")
    plt.close(fig)
    picture=buffer.getvalue()
    (out/"overview.png").write_bytes(picture)
    return base64.b64encode(picture).decode("ascii")


def partition_evidence(partition):
    r,f=partition["results"],partition["freeze"]
    name=partition["name"]
    selected=f["selected"]
    rows=[
        ["النموذج المختار",esc(MODEL_NAMES.get(selected["family"],selected["family"]))],
        ["العتبة والسياسة",f'<code>{selected["threshold"]:.12g}</code> · <code>{esc(selected["policy"])}</code>'],
        ["دقائق التدريب / المعايرة",f'<bdi>{number(f["training_rows"])} / {number(f["calibration_rows"])}</bdi>'],
        ["دقائق EVENT في المعايرة فقط",number(f["calibration_event_minutes"])],
        ["تاريخ أول وآخر عينة اختبار كما حُفظ",f'<bdi>{esc(r["timestamp_start"])} → {esc(r["timestamp_end"])}</bdi>'],
        ["وقت التجميد UTC",f'<bdi>{esc(f["frozen_at_utc"])}</bdi>'],
        ["وقت تقييم الاختبار UTC",f'<bdi>{esc(r["scored_at_utc"])}</bdi>'],
        ["بصمة النموذج V2 وقت التجميد",'<code class="hash">'+esc(f["model_sha256"]["v2"])+"</code>"],
    ]
    links=(f'<a href="{name}/freeze.json">سجل التجميد</a> · '
           f'<a href="{name}/test_results.json">مقاييس JSON</a> · '
           f'<a href="{name}/test_predictions.csv.gz">تنبؤات محفوظة للمراجعة</a> · '
           f'<a href="{name}/v2_model.joblib">نموذج V2</a> · '
           f'<a href="{name}/baseline_model.joblib">نموذج الأساس</a>')
    return table(["الدليل","القيمة"],rows)+"<p>"+links+"</p>"


def report_html(walk,folds,external,embedded):
    style,title,body=verdict(walk)
    extstyle,exttitle,extbody=verdict(external["results"])
    b,v=walk["common"]["baseline"],walk["common"]["v2"]
    nativev=walk["native"]["v2"]
    pass_folds=sum(target_status(p["results"]["common"]["v2"]) is True for p in folds)
    families=Counter(p["freeze"]["selected"]["family"] for p in folds)
    family_text="، ".join(f'{esc(MODEL_NAMES.get(k,k))}: {n} فترة' for k,n in families.items())
    evidence="".join(f'<details><summary>الفترة {i}: سجل الاختيار والتجميد</summary>{partition_evidence(p)}</details>'
                      for i,p in enumerate(folds,1))
    models_available=[f'<a href="fold_{i}/v2_model.joblib">V2 للفترة {i}</a>' for i in range(1,7)]
    native_note=("تحقّق السقفان أيضاً عند حساب التغطية الأصلية لـV2." if target_status(nativev) is True
                 else "لم يتحقق السقفان معاً عند حساب التغطية الأصلية لـV2." if target_status(nativev) is False
                 else "تعذّر تقييم أحد السقفين على التغطية الأصلية لـV2.")
    return f'''<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>مورد — مقارنة النماذج V2</title><style>
:root{{--ink:#18383e;--muted:#63767a;--teal:#087b6d;--line:#dce8e5;--paper:#fff;--bg:#edf3f1}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Tahoma,Arial,sans-serif;font-size:15px;line-height:1.9}}
main{{max-width:1160px;margin:34px auto;padding:42px 48px;background:white;box-shadow:0 12px 50px #18383e0b;border-top:8px solid var(--teal)}}
header{{border-bottom:1px solid var(--line);padding-bottom:24px}}.kicker{{color:var(--teal);font-size:13px;font-weight:bold}}h1{{font-size:34px;line-height:1.45;margin:12px 0}}h2{{font-size:22px;margin:34px 0 12px;line-height:1.6}}h3{{font-size:17px;margin:22px 0 8px}}p{{margin:10px 0}}.muted,figcaption{{font-size:13px;color:var(--muted)}}
.outcome{{border:1px solid;border-radius:10px;padding:20px 24px;margin:25px 0}}.outcome h2{{margin:0 0 10px}}.good{{background:#eff8f3;border-color:#8dbdab}}.caution{{background:#fff5eb;border-color:#d6ad87}}.neutral{{background:#f1f5f8;border-color:#aab9c9}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:24px 0}}.card{{border:1px solid var(--line);border-radius:8px;padding:17px 20px}}.card strong{{font-size:28px;display:block;color:var(--teal)}}.note{{border-right:4px solid #7aa89e;background:#f0f7f4;padding:14px 18px}}
.table-wrap{{overflow:auto;margin:12px 0 18px}}table{{width:100%;border-collapse:collapse;font-size:13px;line-height:1.65}}th,td{{padding:9px 11px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th{{background:#e9f3ef;font-weight:bold}}tbody tr:nth-child(even){{background:#f8fbfa}}td{{font-variant-numeric:tabular-nums}}figure{{margin:20px 0}}img{{width:100%;height:auto;display:block}}figcaption{{padding:8px 2px}}a{{color:#086e63;text-decoration:none;border-bottom:1px solid #aacbc1}}ul,ol{{padding-right:25px}}li{{margin:9px 0}}code,pre{{font-family:ui-monospace,Menlo,monospace;font-size:12px;direction:ltr;unicode-bidi:embed}}pre{{background:#f2f6f4;padding:16px;border:1px solid var(--line);overflow:auto;text-align:left;line-height:1.8}}.hash{{display:block;word-break:break-all}}details{{margin:14px 0;border:1px solid var(--line);padding:14px 18px;border-radius:7px}}summary{{cursor:pointer;font-weight:bold;color:var(--teal)}}footer{{border-top:1px solid var(--line);margin-top:35px;padding-top:18px}}
@media(max-width:720px){{main{{margin:0;padding:24px 18px}}h1{{font-size:27px}}.cards{{grid-template-columns:1fr}}th,td{{padding:7px}}}}
@page{{size:A4;margin:15mm 12mm}}@media print{{body{{background:white;font-size:10pt}}main{{padding:0;margin:0;box-shadow:none;border-top:4px solid var(--teal)}}h1{{font-size:23pt}}h2{{font-size:15pt;break-after:avoid}}h3{{break-after:avoid}}table{{font-size:8pt}}th,td{{padding:6px}}.table-wrap{{overflow:visible}}thead{{display:table-header-group}}tr,.outcome,.card,figure{{break-inside:avoid}}.hash{{font-size:7pt}}a{{color:inherit;border:0}}pre{{white-space:pre-wrap;font-size:8pt}}.cards{{gap:8px}}}}
</style></head><body><main>
<header><div class="kicker">مورد · مقارنة قابلة للمراجعة · GECCO V2</div>
<h1>هل تحسّن كشف الأحداث؟<br>ست فترات زمنية وتقييم منفصل بعد إعادة التدريب</h1>
<p>مقارنة خط الأساس مع إجراء V2 الذي يختار النموذج والعتبة وسياسة الاستمرارية من الماضي، ثم يجمّدها قبل تقييم الفترة التالية. الأرقام في هذا التقرير مستخرجة من ملفات نتائج التشغيل المحفوظة.</p>
<p class="muted">2018: تقييم زمني استعادي عبر 40–100% من السلسلة · 2019: تقييم المنهج بعد تدريب ومعايرة مستقلين على ست قنوات.</p></header>
<section class="outcome {style}"><h2>{title}</h2><p>{body}</p><p>هذا الحكم يخص تجميع 2018 على الدقائق التي توفر فيها قرار للنموذجين. {native_note} تحقّق السقفان في {pass_folds} من الفترات الست على المقارنة المشتركة.</p></section>
<div class="cards"><div class="card">F1 على الدقائق المشتركة<strong>{pct(v["f1"])}</strong><span class="muted">خط الأساس: {pct(b["f1"])}</span></div><div class="card">بدايات مؤكدة جديدة<strong><bdi>{number(v["confirmed_new_alarm_inside_events"])} / {number(v["true_events"])}</bdi></strong><span class="muted">الأحداث الأصلية، لا نسبة تسويقية</span></div><div class="card">إنذارات كاذبة / يوم طبيعي متاح<strong>{number(v["false_alarm_runs_per_normal_day"],3)}</strong><span class="muted">السقف المحدد: ≤ 1</span></div></div>
<p class="note">نتائج 2018 استعادية لأن نتيجة اختبار سابق من V1 كانت قد شوهدت. إعادة التقسيم الزمني والتجميد داخل كل فترة لا تحول هذه البيانات إلى معيار مستقل جديد. نتائج 2019 أدناه منفصلة، ولا تُدمج معها لإنتاج نسبة واحدة.</p>
<h2>1. ماذا تغيّر في المنهج؟</h2>
<p>استُكشف التطوير في أول 40% من بيانات 2018 فقط: ثلاثة مرشحين بإشراف ثنائي وخمسة إعدادات دون إشراف. بعد ذلك ثُبّتت عائلات المقارنة: ExtraTrees وHistGradientBoosting وLogistic Regression، وIsolation Forest على تغيرات مطبّعة سببياً. بقيت نتائج التطوير منفصلة عن نتائج الفترات الخارجية.</p>
<ol><li>لكل فترة، تدريب على جزء سابق متزايد، ثم معايرة على الجزء الذي يليه، مع فجوة 120 دقيقة عند حدود الفصل.</li><li>تختار المعايرة النموذج والعتبة وسياسة <code>instant</code> أو <code>2of3</code> أو <code>3of5</code>. الهدف إعطاء الأولوية لبدايات الأحداث المؤكدة، ثم F1 الخام، ضمن سقفي الإنذار الكاذب. عند غياب أحداث المعايرة يُستخدم ترتيب العائلات الثابت، وأدنى عتبة ممكنة ضمن القيود مع سياسة <code>2of3</code>؛ لا يُستدل من هذه المعايرة على استدعاء أحداث.</li><li>يُحفظ النموذج وبصماته ووقت التجميد قبل تقييم الفترة التالية. لا تدخل نتائج تلك الفترة في تعديل المرشحين أو العتبات.</li><li>يعاد تدريب خوارزمية V1 في كل فترة على الماضي نفسه، بميزاتها ذات 15 دقيقة وهدف F1 الأصلي وسياسة فورية، كي لا يتسرّب نموذج مدرّب على مستقبل الفترة.</li></ol>
<p>الميزات سببية؛ أعلى تاريخ مطلوب 60 دقيقة سابقة. لا يُستخدم <code>EVENT</code> كميزة، ولا تُوسّع علاماته، ولا تُعدّل النقاط بأثر رجعي. لا توجد تسوية للإنذارات عبر بيانات مفقودة: تحتاج سياسة الاستمرارية نافذة مكتملة، وإلا يكون القرار <code>-1</code>.</p>
<h2>2. الفترات الست: ثبات النتيجة أهم من متوسط واحد</h2>
<figure><img src="data:image/png;base64,{embedded}" alt="مقارنة F1 وبدايات الأحداث المؤكدة ومقاطع الإنذار الكاذب لكل يوم في ست فترات زمنية"><figcaption>الرسم يعرض المقارنة على الدقائق المشتركة. تسميات البدايات المؤكدة تذكر البسط والمقام؛ عندما لا توجد أحداث، يظهر N/A. خط الإنذار المتقطع هو السقف المحدد. <a href="overview.png">تنزيل PNG</a>.</figcaption></figure>
{fold_table(folds)}
<p>اختيارات العائلة عبر الفترات: {family_text}. اختلافها نتيجة إجراء الاختيار السابق لكل فترة، وليس اختيار النموذج الأفضل بعد الاطلاع على نتيجتها.</p>
<h2>3. نتيجة 2018 المجمّعة على الدقائق المشتركة</h2>
<p>المشترك هو تقاطع الدقائق التي أصدرت فيها الطريقتان قراراً. بذلك تُقارن الدقة والاستدعاء وعبء الإنذار على التعرض نفسه. تبقى جميع الأحداث الأصلية في المقام، حتى لو لم تتوفر لها أي دقيقة قابلة للتقييم.</p>
{metrics_table(walk)}
<h3>التغطية الأصلية لكل نموذج</h3>
{coverage_table(walk)}
<p>قد تفقد V2 دقائق إضافية بسبب طول نافذة الميزات أو الاستمرارية. لا يُخفى هذا الفرق داخل المقارنة المشتركة: «غير متاح» لا يعني «طبيعي»، ولا تدخل هذه الدقائق في TP/FP/FN/TN. المقاييس الأصلية لكل نموذج تعتمد على دقائق توفر قراره هو.</p>
{operational_table(walk)}
<p>جُمّعت تنبؤات الفترات على محور 40–100% الأصلي، بما فيه الفجوات والقرارات غير المتاحة. تُعرّف الأحداث المتصلة مرة واحدة على هذا المحور؛ لذلك لا تُجمع أعداد أحداث الفترات حسابياً إذا امتد حدث عبر حد فاصل.</p>
<h2>4. تقييم 2019: المنهج بعد إعادة التدريب على ست قنوات</h2>
<section class="outcome {extstyle}"><h2>{exttitle}</h2><p>{extbody}</p></section>
<p>تغيّر مخطط القنوات إلى <code>Tp, pH, Cond, Turb, SAC, PFM</code>. أُعيد تدريب المرشحين ثم اختيارهم ومعايرتهم على ملفات 2019 السابقة زمنياً. جُمّد الاختيار قبل فتح علامات ملف الاختبار الأحدث. هذه تجربة للمنهج بعد إعادة التدريب، وليست نقلاً مباشراً لنقطة تحقق 2018 أو إثباتاً لتعميمه على موقع ميداني جديد.</p>
<p>استُخدم ترتيب التواريخ الفعلية الذي تحقق منه فحص التداخل قبل التقييم: تدريب ثم معايرة ثم اختبار. أسماء الملفات وحدها ليست أساس الترتيب. يبقى هذا القسم مستقلاً عن تجميع 2018.</p>
{metrics_table(external["results"])}
<h3>التغطية الأصلية وعبء الإنذار في 2019</h3>{coverage_table(external["results"])}{operational_table(external["results"])}
{partition_evidence(external)}
<h2>5. تعريفات تمنع قراءة النتيجة على نحو مضلل</h2>
<ul><li><strong>تغطية حدث:</strong> وجود أي إنذار داخل حدوده. قد يكون الإنذار بدأ قبل الحدث؛ لا تعني التغطية بداية جديدة.</li><li><strong>بداية مؤكدة جديدة:</strong> انتقال معروف من 0 إلى 1 داخل الحدث. بداية السلسلة أو الانتقال من <code>-1</code> إلى 1 لا يُحتسبان بداية مؤكدة.</li><li><strong>التأخر:</strong> المقياس المعروض هو أول تغطية للأحداث المغطاة فقط، وقد يكون صفراً بسبب إنذار سابق مستمر. دقة البيانات دقيقة؛ لا يثبت الرقم إغلاق صمام خلال ثوانٍ.</li><li><strong>الإنذار الكاذب:</strong> مقطع متصل من إنذارات خارج الأحداث الموسومة. حدود الحدث والفقد تفصل المقاطع، وذيل الإنذار بعد الحدث يُحتسب. المقام اليومي هو الدقائق الطبيعية المتاحة ÷ 1,440؛ ونسبة الوقت الكاذب هي FP ÷ الدقائق الطبيعية المتاحة.</li><li><strong>لا أحداث:</strong> يكون استدعاء الأحداث غير قابل للقياس. قد تظل الدقائق الطبيعية مفيدة لقياس الإنذارات الكاذبة.</li><li><strong>Accuracy ليست حكم النجاح:</strong> قد تكون مرتفعة لأن الطبيعي غالب، حتى مع فقد أحداث. لذلك يتقدم التقرير بالمقامات وPrecision وRecall وF1 والإنذار الكاذب والتغطية.</li></ul>
<h2>6. ما تثبته التجربة وما لا تثبته</h2>
<p>توثق التجربة مقارنة قابلة لإعادة التشغيل لكشف علامة الحدث الثنائية في بيانات منشورة. لا تصنّف الأعطال الخمسة، ولا تميّز كل حدث بين خلل حساس وتغير حقيقي في الماء أو صيانة. ليست شهادة مطابقة لمياه الري أو قياساً للبكتيريا، ولا تجربة مياه وضوء ميدانية.</p>
<p>لم تُقَس سرعة هذه المقارنة على Raspberry Pi، ولم تُختبر معها صمامات أو سلسلة أمان، ولم تُدمج في نموذج ثلاثي الأبعاد. لا يجوز أن يُفسَّر قرار «لا إنذار» على أنه إذن بفتح صمام. أي تعديل لاحق بعد هذه النتائج يحتاج تقييماً جديداً مناسباً بدلاً من إعادة تسمية النتيجة الحالية كاختبار محجوب جديد.</p>
<h2>7. الأدلة وإعادة إصدار التقرير</h2>
<p><a href="walk_forward_results.json">نتيجة 2018 المجمعة JSON</a> · <a href="walk_forward_predictions.csv.gz">تنبؤات 2018 المجمعة</a> · <a href="protocol.json">البروتوكول المعلن</a> · <a href="report_summary.json">خلاصة مشتقة JSON</a></p>
<p>{" · ".join(models_available)}</p>
<p class="muted">بصمة البروتوكول المشتركة كما وردت في التجميد: <code class="hash">{esc(walk["protocol_sha256"])}</code></p>
{evidence}
<p>قرأ منشئ هذا التقرير JSON للنتائج والتجميد فقط؛ لم يقرأ البيانات الخام أو أعمدة العلامات أو ملفات التنبؤ أو النماذج، ولم يعد حساب درجات النماذج. تحقق من اتفاق بصمة البروتوكول والعائلة المختارة، وأن وقت التقييم يلي التجميد. البصمات المعروضة محفوظة في سجلات التشغيل؛ لا يدعي التقرير إعادة حساب بصمات النماذج.</p>
<p>لإعادة إصدار التقرير من النتائج المكتملة، من جذر المشروع:</p><pre>ml/gecco_baseline/.venv/bin/python ml/gecco_v2/make_report.py</pre>
<footer class="muted">مورد · نتائج كشف أحداث، لا ضمان سلامة مياه. الصورة مضمنة داخل HTML ويمكن فتحه مستقلاً؛ الروابط إلى الأدلة تتطلب بقاء ملفات النتائج في مواقعها. الأرقام غير القابلة للحساب لا تستبدل بأصفار.</footer>
</main></body></html>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,default=OUT)
    args=parser.parse_args()
    out=args.output_dir.resolve()
    walk,folds,external=load_required(out)
    embedded=plot_folds(out,folds)
    summary={"source":"saved result JSON only; no rescoring",
             "retrospective_2018":comparison(walk), "external_2019_method_retrained":comparison(external["results"]),
             "folds":[{"name":p["name"],"selected_family":p["results"]["selected_family"],
                       "policy":p["freeze"]["selected"]["policy"],**comparison(p["results"])} for p in folds],
             "2018_verdict":verdict(walk)[1:],"2019_verdict":verdict(external["results"])[1:],
             "protocol_sha256":walk["protocol_sha256"]}
    (out/"report_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    (out/"report.html").write_text(report_html(walk,folds,external,embedded),encoding="utf-8")
    print(json.dumps({"report":str(out/"report.html"),"plot":str(out/"overview.png"),
                      "2018_outcome":verdict(walk)[1],"2019_outcome":verdict(external["results"])[1]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
