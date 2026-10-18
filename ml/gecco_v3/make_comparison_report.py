"""Compare frozen baseline/V2/V3 predictions without selecting on final test.

Do not run before the experiment owner authorizes opening the completed final
results. Both versions' final result/freezes and the pre-test release choice
must exist before any prediction CSV is read. No raw dataset or estimator is
loaded, trained, rescored, or tuned. Metrics are recomputed from saved outputs
on one three-model availability intersection, while retaining native coverage.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
METRICS_PATH = ROOT / "ml/gecco_baseline/metrics.py"
sys.path.insert(0, str(METRICS_PATH.parent))
from metrics import evaluate

ROLES = ("baseline", "v2", "v3")
NAMES = {"baseline": "خط الأساس", "v2": "V2", "v3": "V3"}
CHECK_METRICS = ("sample_count", "valid_count", "tp", "fp", "fn", "tn",
                 "true_events", "confirmed_new_alarm_inside_events", "false_positive_runs")


def esc(value):
    return html.escape(str(value), quote=True)


def finite(value):
    return value is not None and math.isfinite(float(value))


def num(value, digits=0):
    return f"{value:,.{digits}f}" if finite(value) else "غير قابل للقياس"


def pct(value):
    return f"{100*value:.2f}%" if finite(value) else "غير قابل للقياس"


def events(result, key="confirmed_new_alarm_inside_events", denominator="true_events"):
    if not result.get(denominator):
        return "غير قابل للقياس — 0 أحداث"
    return f'<bdi>{num(result.get(key))} / {num(result[denominator])}</bdi> حدث'


def table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + "".join(
        "<th>"+esc(h)+"</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>"+"".join("<td>"+str(c)+"</td>" for c in row)+"</tr>" for row in rows) + "</tbody></table></div>"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def iso(value):
    return datetime.fromisoformat(value)


def required_artifacts(dirs, out):
    required = [out/"release_choice.json"]
    for directory in dirs.values():
        required += [directory/"walk_forward_results.json", directory/"walk_forward_predictions.csv.gz"]
        for partition in [f"fold_{i}" for i in range(1, 7)]+["external_2019"]:
            required += [directory/partition/"freeze.json", directory/partition/"test_results.json"]
        required.append(directory/"external_2019/test_predictions.csv.gz")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Both final experiments must be complete before reporting. Missing: " + ", ".join(missing))


def load_and_check_records(dirs, out):
    """Read records first, then authorize access to saved final predictions."""
    required_artifacts(dirs, out)
    choice = read_json(out/"release_choice.json")
    if choice.get("final_test_opened_before_choice") is not False:
        raise ValueError("Release choice does not attest to selection before final test")
    if choice.get("selected_version") not in ("v2", "v3"):
        raise ValueError("Unsupported release version")
    records = {}
    metrics_hash = digest(METRICS_PATH)
    for version, directory in dirs.items():
        records[version] = {"aggregate": read_json(directory/"walk_forward_results.json"), "partitions": {}}
        for partition in [f"fold_{i}" for i in range(1, 7)]+["external_2019"]:
            frozen = read_json(directory/partition/"freeze.json")
            result = read_json(directory/partition/"test_results.json")
            if frozen.get("test_used_for_selection") is not False:
                raise ValueError(f"{version}/{partition}: test was not excluded from selection")
            if iso(frozen["frozen_at_utc"]) > iso(result["scored_at_utc"]):
                raise ValueError(f"{version}/{partition}: scoring predates freeze")
            if frozen["selected"]["family"] != result["selected_family"]:
                raise ValueError(f"{version}/{partition}: result differs from frozen family")
            if frozen["code_sha256"].get("ml/gecco_baseline/metrics.py") != metrics_hash:
                raise ValueError("Reporting metric implementation differs from frozen experiment metrics")
            if frozen["protocol_sha256"] != records[version]["aggregate"]["protocol_sha256"]:
                raise ValueError("A partition refers to another protocol")
            records[version]["partitions"][partition] = {"freeze": frozen, "results": result}
        external = records[version]["partitions"]["external_2019"]
        if digest(directory/"external_2019/freeze.json") != choice["freeze_sha256"][version]:
            raise ValueError("Release choice freeze hash does not match the frozen external model")
        if not iso(external["freeze"]["frozen_at_utc"]) <= iso(choice["chosen_at_utc"]) <= iso(external["results"]["scored_at_utc"]):
            raise ValueError("Release choice was not between model freeze and final scoring")
    selected = records[choice["selected_version"]]["partitions"]["external_2019"]["freeze"]
    if choice["selected_family"] != selected["selected"]["family"]:
        raise ValueError("Release choice selected family differs from its frozen family")
    if choice["selected_model_sha256"] != selected["model_sha256"][choice["selected_version"]]:
        raise ValueError("Release choice model hash differs from the frozen model hash")
    return records, choice


def binary_values(series):
    if pd.api.types.is_bool_dtype(series):
        return series.to_numpy(dtype=bool)
    values = series.astype(str).str.lower()
    if not values.isin(["true", "false", "0", "1"]).all():
        raise ValueError("Unexpected EVENT encoding in saved predictions")
    return values.isin(["true", "1"]).to_numpy()


def prediction_values(series):
    values = pd.to_numeric(series, errors="raise").to_numpy()
    if not np.isin(values, [-1, 0, 1]).all():
        raise ValueError("Saved predictions must be -1, 0, or 1")
    return values.astype(int)


def read_aligned_predictions(dirs, relative):
    """Align by exact saved acquisition axis; never sort wall-clock timestamps."""
    frames = {}
    for version, directory in dirs.items():
        columns = ["sample_index", "timestamp_original", "EVENT", "baseline_prediction", f"{version}_prediction"]
        frames[version] = pd.read_csv(directory/relative, usecols=columns)
    a, b = frames["v2"], frames["v3"]
    if len(a) != len(b) or not np.array_equal(a.sample_index.to_numpy(), b.sample_index.to_numpy()):
        raise ValueError("V2/V3 sample axes differ; no silent join or row removal is allowed")
    index = a.sample_index.to_numpy(dtype=int)
    if index.size and not np.array_equal(index, np.arange(index[0], index[0]+len(index))):
        raise ValueError("Saved prediction axis is not a contiguous acquisition-order sequence")
    if not np.array_equal(a.timestamp_original.to_numpy(), b.timestamp_original.to_numpy()):
        raise ValueError("V2/V3 original timestamps differ")
    y, y3 = binary_values(a.EVENT), binary_values(b.EVENT)
    if not np.array_equal(y, y3):
        raise ValueError("V2/V3 saved original labels differ")
    baseline = prediction_values(a.baseline_prediction)
    if not np.array_equal(baseline, prediction_values(b.baseline_prediction)):
        raise ValueError("Baseline predictions differ between experiments; comparison requires reconciliation")
    return {"sample_index": index, "labels": y, "predictions": {
        "baseline": baseline, "v2": prediction_values(a.v2_prediction), "v3": prediction_values(b.v3_prediction)}}


def assess_three(data, mask=None):
    if mask is None:
        mask = np.ones(len(data["labels"]), dtype=bool)
    y = data["labels"][mask]
    predictions = {role: data["predictions"][role][mask] for role in ROLES}
    common = np.logical_and.reduce([p >= 0 for p in predictions.values()])
    return {"sample_count": len(y), "common_available_count": int(common.sum()),
            "native": {role:evaluate(y, p) for role,p in predictions.items()},
            "common_three": {role:evaluate(y, np.where(common, p, -1)) for role,p in predictions.items()}}


def check_native(comparison, saved, version):
    for role in ("baseline", version):
        for key in CHECK_METRICS:
            if comparison["native"][role][key] != saved["native"][role][key]:
                raise ValueError(f"Recomputed native {role}/{key} differs from saved experiment result")


def build_comparison(dirs, out):
    records, choice = load_and_check_records(dirs, out)
    # Both final result records and the pre-test selection have passed checks.
    walk_data = read_aligned_predictions(dirs, "walk_forward_predictions.csv.gz")
    external_data = read_aligned_predictions(dirs, "external_2019/test_predictions.csv.gz")
    walk, external = assess_three(walk_data), assess_three(external_data)
    folds = []
    for index in range(1,7):
        name = f"fold_{index}"
        a = records["v2"]["partitions"][name]["results"]
        b = records["v3"]["partitions"][name]["results"]
        if (a["source_start_index"], a["source_end_index"]) != (b["source_start_index"], b["source_end_index"]):
            raise ValueError("Fold boundaries differ between versions")
        mask = (walk_data["sample_index"] >= a["source_start_index"]) & (walk_data["sample_index"] < a["source_end_index"])
        if int(mask.sum()) != a["source_end_index"]-a["source_start_index"]:
            raise ValueError("Aggregate prediction file does not cover a complete fold")
        result = assess_three(walk_data, mask)
        for version in ("v2","v3"):
            check_native(result,records[version]["partitions"][name]["results"],version)
        folds.append({"name":name,"source_start_index":a["source_start_index"],"source_end_index":a["source_end_index"],
                      "frozen_choices":{version:records[version]["partitions"][name]["freeze"]["selected"] for version in ("v2","v3")},
                      **result})
    for version in ("v2","v3"):
        check_native(walk, records[version]["aggregate"], version)
        check_native(external, records[version]["partitions"]["external_2019"]["results"], version)
    comparison = {
        "method": "All three models use the same intersection of available decisions; original labels and event denominators retained",
        "metric_code_sha256": digest(METRICS_PATH),
        "checks": {"both_final_results_existed_before_csv_read":True, "sample_axes_match":True,
                   "labels_match":True,"baseline_predictions_match":True,"native_metrics_match_saved_results":True,
                   "release_choice_precedes_both_final_tests":True,"freeze_hashes_match_release_choice":True},
        "release_choice":choice,"retrospective_2018":walk,"folds":folds,
        "external_2019_method_retrained":external,
        "frozen_metadata": {version: {name:{"frozen_at_utc":p["freeze"]["frozen_at_utc"],
                     "scored_at_utc":p["results"]["scored_at_utc"],"test_used_for_selection":p["freeze"]["test_used_for_selection"],
                     "selected_family":p["freeze"]["selected"]["family"],"selected_policy":p["freeze"]["selected"]["policy"]}
                     for name,p in records[version]["partitions"].items()} for version in ("v2","v3")}}
    return comparison, records


def targets(result):
    rate,duration = result.get("false_alarm_runs_per_normal_day"),result.get("normal_time_under_alarm")
    if not finite(rate) or not finite(duration):
        return None
    return bool(rate <= 1 and duration <= .01)


def selected_verdict(comparison):
    version = comparison["release_choice"]["selected_version"]
    ext = comparison["external_2019_method_retrained"]
    common,native = ext["common_three"][version],ext["native"][version]
    if not common["true_events"]:
        return "neutral", f"الترشيح المسبق {version.upper()}: الكشف غير قابل للقياس بلا أحداث", "يمكن تقييم الإنذارات الكاذبة والتغطية فقط في هذه الفترة."
    failed=[]
    if targets(common) is False:
        failed.append("لم يستوفِ سقفي الإنذار الكاذب معاً على الدقائق المشتركة")
    if targets(native) is False:
        failed.append("لم يستوفِ السقفين معاً على تغطيته الأصلية")
    if not finite(common["recall"]) or common["recall"] <= 0:
        failed.append("لم يحقق استدعاءً غير صفري للدقائق الموسومة القابلة للتقييم")
    if failed:
        return "caution",f"الترشيح المسبق {version.upper()} لم يجتز جميع الشروط المقاسة في الاختبار النهائي","؛ ".join(failed)+". لا يُستبدل الترشيح لاحقاً باختيار يعتمد على نتائج هذا الاختبار."
    if targets(common) is None or targets(native) is None:
        return "neutral",f"نتيجة الترشيح المسبق {version.upper()} غير حاسمة","تعذّر حساب واحد أو أكثر من مقاييس التعرض والإنذار الكاذب."
    return "good",f"في اختبار 2019، حقق الترشيح المسبق {version.upper()} سقفي الإنذار الكاذب مع كشف غير صفري",(
        f'الاستدعاء {pct(common["recall"])}، وF1 {pct(common["f1"])}، والبدايات المؤكدة '
        f'{num(common["confirmed_new_alarm_inside_events"])} من {num(common["true_events"])} حدثاً. '
        "لم يُعلن حد قبول هندسي مرتفع للاستدعاء؛ تحقق هذه الشروط لا يثبت الجاهزية الميدانية.")


def change_sentence(result, version):
    base,new = result["common_three"]["baseline"],result["common_three"][version]
    if not new["true_events"] or not finite(base["f1"]) or not finite(new["f1"]):
        return f"{version.upper()}: لا توجد مقارنة مكتملة لـF1 واستدعاء الأحداث في هذا النطاق."
    delta=(new["f1"]-base["f1"])*100
    word="ارتفع" if delta>0 else "انخفض" if delta<0 else "لم يتغير"
    value=f" بمقدار {num(abs(delta),2)} نقطة مئوية" if delta else ""
    operating="تحقق سقفا الإنذار الكاذب" if targets(new) is True else "لم يتحقق السقفان معاً" if targets(new) is False else "تعذر تقييم السقفين"
    return (f'{version.upper()}: {word} F1{value} مقابل خط الأساس؛ {operating}. '
            f'البدايات المؤكدة {num(new["confirmed_new_alarm_inside_events"])} من {num(new["true_events"])} حدثاً.')


def metric_table(result):
    metrics=result["common_three"]
    rows=[]
    for label,key,formatter in [
        ("Precision — دقة الإنذارات","precision",pct),
        ("Recall — استدعاء الدقائق الموسومة المتاحة","recall",pct),
        ("F1 — دون تعديل النقاط","f1",pct),
        ("مقاطع الإنذار الكاذب","false_positive_runs",num),
        ("مقاطع كاذبة / يوم طبيعي متاح","false_alarm_runs_per_normal_day",lambda v:num(v,3)),
        ("دقائق الإنذار الكاذب FP","fp",num),
        ("نسبة الوقت الطبيعي تحت إنذار كاذب","normal_time_under_alarm",pct),
        ("دقائق شاذة مع إنذار TP","tp",num),
        ("دقائق شاذة دون إنذار FN","fn",num),
        ("دقائق طبيعية دون إنذار TN","tn",num),
        ("الدقائق ذات القرار المشترك","valid_count",num),
        ("التغطية المشتركة من كامل المحور","prediction_coverage",pct),
        ("دقائق دون قرار في المقارنة المشتركة","unavailable_count",num),
        ("الأيام الطبيعية المتاحة — مقام معدل الإنذار","eligible_normal_days",lambda v:num(v,3)),
        ("وسيط تأخر أول تغطية، دقيقة","median_detection_delay_minutes",lambda v:num(v,2)),
        ("المئين95 لتأخر أول تغطية، دقيقة","p95_detection_delay_minutes",lambda v:num(v,2)),
    ]:
        rows.append([label]+[formatter(metrics[role].get(key)) for role in ROLES])
    rows[3:3]=[
        ["أحداث تغطيها أي إشارة إنذار"]+[events(metrics[r],"detected_events") for r in ROLES],
        ["أحداث ببداية مؤكدة جديدة 0→1"]+[events(metrics[r]) for r in ROLES],
        ["أحداث كاملة ببداية مؤكدة جديدة"]+[events(metrics[r],"complete_confirmed_new_alarm_inside_events","complete_events") for r in ROLES],
        ["أحداث غير قابلة للتقييم بالكامل"]+[num(metrics[r].get("fully_unscorable_events")) for r in ROLES],
    ]
    return table(["المقياس"]+[NAMES[r] for r in ROLES],rows)


def native_table(result):
    rows=[]
    for role in ROLES:
        r=result["native"][role]
        rows.append([NAMES[role],num(r["sample_count"]),num(r["valid_count"]),num(r["unavailable_count"]),
                     pct(r["prediction_coverage"]),pct(r["precision"]),pct(r["recall"]),pct(r["f1"])])
    return table(["النموذج","إجمالي الدقائق","قرار متاح","غير متاح","التغطية الأصلية","Precision","Recall","F1"],rows)


def burden_table(result):
    rows=[]
    for scope,label in (("common_three","المشترك الثلاثي"),("native","الأصلي لكل نموذج")):
        for role in ROLES:
            r=result[scope][role]
            state=targets(r)
            rows.append([label,NAMES[role],num(r["false_positive_runs"]),num(r["fp"]),
                         num(r["false_alarm_runs_per_normal_day"],3),pct(r["normal_time_under_alarm"]),
                         "متحققان" if state is True else "غير متحققين معاً" if state is False else "غير قابل للقياس"])
    return table(["النطاق","النموذج","مقاطع كاذبة","دقائق كاذبة","مقاطع/يوم","نسبة الوقت","السقفان"],rows)


def fold_table(folds):
    rows=[]
    for i,fold in enumerate(folds,1):
        for role in ROLES:
            r=fold["common_three"][role]
            family="Baseline IF" if role=="baseline" else fold["frozen_choices"][role]["family"]
            rows.append([f"{i} · {30+i*10}–{40+i*10}%",NAMES[role],esc(family),pct(r["precision"]),
                         pct(r["recall"]),pct(r["f1"]),events(r),
                         num(r["false_alarm_runs_per_normal_day"],3),pct(r["normal_time_under_alarm"])])
    return table(["الفترة","النسخة","اختيار المعايرة","Precision","Recall","F1","بدايات/أحداث","كاذب/يوم","وقت كاذب"],rows)


def plot_comparison(out,folds):
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,
                         "axes.spines.top":False,"axes.spines.right":False})
    fig,axes=plt.subplots(3,1,figsize=(13,10.5),sharex=True,layout="constrained")
    x=np.arange(1,7)
    styles=[("baseline","Baseline (refit)","#7c8b9a","o",-22),
            ("v2","V2", "#9363b5","D",0),("v3","V3", "#087b6d","s",20)]
    for role,label,color,marker,offset in styles:
        ms=[fold["common_three"][role] for fold in folds]
        values=[
            [m["f1"] if m["true_events"] and finite(m["f1"]) else np.nan for m in ms],
            [m["confirmed_new_alarm_inside_event_recall"] if m["true_events"] else np.nan for m in ms],
            [m["false_alarm_runs_per_normal_day"] if finite(m["false_alarm_runs_per_normal_day"]) else np.nan for m in ms]]
        for ax,ys in zip(axes,values):
            ax.plot(x,ys,color=color,marker=marker,lw=2,ms=6,label=label)
        for i,m in enumerate(ms):
            if m["true_events"]:
                axes[1].annotate(f'{m["confirmed_new_alarm_inside_events"]}/{m["true_events"]}',
                                 (x[i],values[1][i]),textcoords="offset points",xytext=(0,offset),
                                 ha="center",fontsize=8.5,color=color,
                                 bbox={"boxstyle":"round,pad=.15","facecolor":"white","edgecolor":"none","alpha":.85})
    for i,fold in enumerate(folds):
        if not fold["common_three"]["baseline"]["true_events"]:
            for ax in axes[:2]:
                ax.text(i+1,.45,"N/A\n0 events",ha="center",va="center",color="#6b7280")
    axes[0].set_title("A. Unadjusted point F1 on the same three-model availability intersection",loc="left",weight="bold")
    axes[1].set_title("B. Confirmed new alarm starts inside original events (counts annotated)",loc="left",weight="bold")
    axes[2].set_title("C. False-alarm segments per eligible normal day",loc="left",weight="bold")
    axes[0].set_ylabel("F1");axes[1].set_ylabel("Event-start recall");axes[2].set_ylabel("False segments / day")
    for ax in axes[:2]:
        ax.set_ylim(-.17,1.19);ax.set_yticks(np.arange(0,1.01,.2))
    axes[2].axhline(1,color="#c66e35",lw=1.5,ls="--",label="Target ≤ 1/day")
    axes[2].set_ylim(bottom=0)
    for ax in axes:
        ax.grid(alpha=.16);ax.set_xlim(.65,6.35)
    axes[0].legend(loc="upper left",frameon=False,ncol=3)
    axes[2].legend(loc="upper left",frameon=False,ncol=4,fontsize=8.5)
    axes[2].set_xticks(x,[f"Fold {i}\n{30+i*10}–{40+i*10}%" for i in x])
    axes[2].set_xlabel("2018 acquisition-order test periods — retrospective comparison")
    buffer=io.BytesIO();fig.savefig(buffer,format="png",dpi=180,facecolor="white");plt.close(fig)
    picture=buffer.getvalue();(out/"comparison.png").write_bytes(picture)
    return base64.b64encode(picture).decode("ascii")


def local_link(path,out,label):
    return '<a href="'+esc(os.path.relpath(path,out))+'">'+esc(label)+"</a>"


def render_html(comparison,records,dirs,out,embedded):
    choice=comparison["release_choice"]
    version=choice["selected_version"]
    walk=comparison["retrospective_2018"]
    ext=comparison["external_2019_method_retrained"]
    selected=ext["common_three"][version]
    history_counts = {role: walk["common_three"][role]["confirmed_new_alarm_inside_events"] for role in ROLES}
    history_total = walk["common_three"]["baseline"]["true_events"]
    style,title,body=selected_verdict(comparison)
    external_baseline = ext["common_three"]["baseline"]
    if finite(selected["f1"]) and finite(external_baseline["f1"]) and selected["f1"] > external_baseline["f1"]:
        overall_title = "تحسّن واضح في الاختبار الإضافي، لكن الثبات عبر الفترات لم يثبت"
    else:
        overall_title = "نتائج الاختبار الإضافي لا تثبت تحسناً ثابتاً عبر الفترات"
    cal_rows=[]
    for role in ("v2","v3"):
        c=choice["calibration_candidates"][role]
        cal_rows.append([role.upper(),esc(c.get("family",records[role]["partitions"]["external_2019"]["freeze"]["selected"]["family"])),
                         events(c),pct(c.get("f1")),num(c.get("fp")),
                         num(c.get("false_alarm_runs_per_normal_day"),3),pct(c.get("normal_time_under_alarm")),
                         "الترشيح المحفوظ" if role==version else "مرشح آخر، مع إظهار نتيجته"])
    choice_table=table(["النسخة","العائلة","بدايات/أحداث المعايرة","F1 المعايرة","FP دقيقة","كاذب/يوم","وقت كاذب","القرار قبل الاختبار"],cal_rows)
    selected_path=Path(choice["selected_model_path"])
    if not selected_path.is_absolute():selected_path=ROOT/selected_path
    evidence_rows=[]
    for role in ("v2","v3"):
        f=records[role]["partitions"]["external_2019"]["freeze"]
        r=records[role]["partitions"]["external_2019"]["results"]
        evidence_rows.append([role.upper(),f'<bdi>{esc(f["frozen_at_utc"])}</bdi>',
                              f'<bdi>{esc(r["scored_at_utc"])}</bdi>',
                              local_link(dirs[role]/"external_2019/freeze.json",out,"freeze")+" · "+
                              local_link(dirs[role]/"external_2019/test_results.json",out,"results")+" · "+
                              local_link(dirs[role]/"external_2019/test_predictions.csv.gz",out,"predictions")])
    final_evidence=table(["النسخة","تجميد النموذج UTC","تقييم النهائي UTC","الأدلة"],evidence_rows)
    fold_links="".join("<li>"+f"الفترة {i}: "+" · ".join(
        local_link(dirs[role]/f"fold_{i}/freeze.json",out,role.upper()+" freeze")+" · "+
        local_link(dirs[role]/f"fold_{i}/test_results.json",out,role.upper()+" results")
        for role in ("v2","v3"))+"</li>" for i in range(1,7))
    return f'''<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>مورد — المقارنة النهائية للمحاولتين V2 وV3</title><style>
:root{{--ink:#19383e;--muted:#657579;--teal:#087b6d;--line:#dce7e4;--bg:#edf3f1}}*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:Tahoma,Arial,sans-serif;font-size:15px;line-height:1.9}}
main{{max-width:1180px;margin:32px auto;padding:42px 48px;background:white;border-top:8px solid var(--teal);box-shadow:0 10px 40px #19383e0b}}
header{{padding-bottom:22px;border-bottom:1px solid var(--line)}}.kicker{{color:var(--teal);font-weight:bold;font-size:13px}}h1{{font-size:34px;line-height:1.45;margin:10px 0}}h2{{font-size:22px;line-height:1.6;margin:32px 0 12px}}h3{{font-size:17px;margin:23px 0 9px}}p{{margin:10px 0}}.muted,figcaption{{font-size:13px;color:var(--muted)}}
.outcome{{padding:20px 24px;margin:26px 0;border:1px solid;border-radius:9px}}.outcome h2{{margin:0 0 9px}}.good{{background:#eff8f3;border-color:#8ab7a6}}.caution{{background:#fff3e9;border-color:#d5a685}}.neutral{{background:#f2f5f8;border-color:#aabac8}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:23px 0}}.card{{padding:17px 20px;border:1px solid var(--line);border-radius:8px}}.card strong{{font-size:26px;display:block;color:var(--teal)}}.note{{padding:13px 18px;background:#f0f7f4;border-right:4px solid #86afa3}}
.table-wrap{{overflow:auto;margin:12px 0 20px}}table{{width:100%;border-collapse:collapse;font-size:13px;line-height:1.65}}th,td{{padding:9px 10px;text-align:right;vertical-align:top;border-bottom:1px solid var(--line)}}th{{background:#eaf3ef}}tbody tr:nth-child(even){{background:#f8fbfa}}td{{font-variant-numeric:tabular-nums}}figure{{margin:21px 0}}img{{display:block;width:100%;height:auto}}figcaption{{padding-top:9px}}a{{color:#086c62;text-decoration:none;border-bottom:1px solid #a6c7bc}}ul,ol{{padding-right:24px}}li{{margin:9px 0}}code,pre{{font-family:ui-monospace,Menlo,monospace;direction:ltr;unicode-bidi:embed;font-size:12px}}pre{{text-align:left;overflow:auto;padding:16px;background:#f3f7f5;border:1px solid var(--line);line-height:1.8}}.hash{{display:block;word-break:break-all}}footer{{border-top:1px solid var(--line);padding-top:18px;margin-top:33px}}
@media(max-width:740px){{main{{margin:0;padding:23px 18px}}h1{{font-size:27px}}.cards{{grid-template-columns:1fr}}th,td{{padding:7px}}}}
@page{{size:A4;margin:15mm 12mm}}@media print{{body{{background:white;font-size:10pt}}main{{padding:0;margin:0;box-shadow:none;border-top:4px solid var(--teal)}}h1{{font-size:23pt}}h2{{font-size:15pt;break-after:avoid}}h3{{break-after:avoid}}table{{font-size:8pt}}th,td{{padding:6px}}.table-wrap{{overflow:visible}}thead{{display:table-header-group}}tr,.outcome,.card,figure{{break-inside:avoid}}.hash{{font-size:7pt}}a{{color:inherit;border:0}}pre{{white-space:pre-wrap;font-size:8pt}}.cards{{gap:8px}}}}
</style></head><body><main>
<header><div class="kicker">مورد · سجل المحاولات والنتيجة النهائية · Baseline / V2 / V3</div>
<h1>المحاولتان ظاهرتان<br>والحكم من اختبار محفوظ</h1>
<p>مقارنة موحدة لخط الأساس وV2 وV3 على الدقائق نفسها، مع إبقاء التغطية الأصلية ظاهرة. ترشيح الإصدار حُفظ من المعايرة قبل اختبار 2019؛ لا يعاد اختيار الإصدار من النتيجة النهائية.</p>
<p class="muted">2018 مقارنة استعادية عبر ست فترات · 2019 تقييم منفصل بعد إعادة تدريب المنهج · V3 أحدث محاولة، ولا تعني الأحدث أنها الأفضل.</p></header>
<section class="outcome caution"><h2>{overall_title}</h2><p><strong>{title}</strong></p><p>{body}</p>
<p><strong>المقارنة الاستعادية2018:</strong> خط الأساس <bdi>{num(history_counts["baseline"])} / {num(history_total)}</bdi> حدثاً ببداية مؤكدة؛ V2 <bdi>{num(history_counts["v2"])} / {num(history_total)}</bdi>؛ V3 <bdi>{num(history_counts["v3"])} / {num(history_total)}</bdi>.</p>
<p><strong>الاختبار الإضافي2019:</strong> الإصدار المرشح {events(selected)}؛ منها {num(selected["fully_unscorable_events"])} أحداث غير قابلة للتقييم بالكامل، وبقيت ضمن مقام {num(selected["true_events"])}. هذه عينة أحداث صغيرة؛ لا يثبت تحسنها أن النموذج أصبح قوياً بوجه عام.</p></section>
<div class="cards"><div class="card">الإصدار المرشح قبل الاختبار<strong>{version.upper()}</strong><span class="muted">اختيار من المعايرة فقط</span></div><div class="card">F1 النهائي على المشترك الثلاثي<strong>{pct(selected["f1"])}</strong><span class="muted">للإصدار المرشح</span></div><div class="card">بدايات مؤكدة في النهائي<strong>{events(selected)}</strong><span class="muted">مقام الأحداث الأصلية ظاهر</span></div></div>
<p class="note"><strong>حجم الدليل محدود:</strong> يتضمن اختبار2019 {num(selected["true_events"])} حدثاً فقط. منها {num(selected["fully_unscorable_events"])} أحداث لا تتوفر لها أي دقيقة قابلة للتقييم، وقد بقيت في المقام. تغطية القرار في المقارنة الثلاثية {pct(selected["prediction_coverage"])}؛ المقاييس على الدقائق المتاحة لا تشمل فترة الفقد وكأنها تشغيل طبيعي.</p>
<p><strong>لم تثبت النتائج ثبات التحسن عبر الفترات:</strong> في مقارنة2018 الاستعادية سجلت V2 بدايات مؤكدة في {num(history_counts["v2"])} من {num(history_total)} حدثاً، وV3 في {num(history_counts["v3"])}، مقابل {num(history_counts["baseline"])} لخط الأساس. لذلك يُقرأ تحسن اختبار2019 بوصفه نتيجة لذلك الاختبار، مع إبقاء التباين السابق ظاهراً.</p>
<h2>1. تاريخ التطوير: لماذا توجد محاولتان؟</h2>
<p>بدأت V2 بمرشحين يعتمدون المستويات الحالية والميزات الزمنية، إضافة إلى مرشح تغيرات دون إشراف. بعد مراجعة نتائج V2 وظهور حدودها، بُنيت V3 حول تغيرات مطبّعة سببياً، مع ثلاثة مصنفات ومرشح من خط الأساس مع استمرارية. جرى تطوير V3 داخل تقسيمات ملف تدريب 2019 فقط؛ لم يُفتح الاختبار النهائي أثناء ذلك.</p>
<p>تُعرض نتائج V2 وV3 كاملة هنا، بما فيها الفترات الضعيفة. جميع مقارنات 2018 استعادية: سبق الاطلاع على نتائج من هذه السلسلة في V1 وV2، ولذلك لا نسمّي إعادة التقسيم معياراً مستقلاً جديداً. ظل اختبار 2019 النهائي مغلقاً حتى تجميد النسختين وحفظ الترشيح من المعايرة.</p>
<p class="note">V3 هي أحدث محاولة في تاريخ العمل. الإصدار المرشح هنا هو {version.upper()} وفق قرار سابق للاختبار؛ لا تعني كلمة «أحدث» ولا أعلى نتيجة منفردة تلقائياً أنه الاختيار الأفضل أو أنه جاهز ميدانياً.</p>
<h2>2. الترشيح الذي حُفظ قبل الاختبار النهائي</h2>
<p>وقت القرار UTC: <bdi>{esc(choice["chosen_at_utc"])}</bdi>. القاعدة: بدايات أحداث مؤكدة في المعايرة، ثم F1، ثم دقائق FP أقل، ثم V2 عند التعادل. يرد النص المحفوظ حرفياً في <a href="release_choice.json">release_choice.json</a>.</p>
{choice_table}
<p>العائلة المرشحة: <code>{esc(choice["selected_family"])}</code>. {local_link(selected_path,out,"ملف النموذج المرشح")}. بصمته المحفوظة:</p><code class="hash">{esc(choice["selected_model_sha256"])}</code>
{final_evidence}
<p>تحقق منشئ التقرير من بصمتي سجلي التجميد المرتبطين بالقرار، ومن أن قرار الترشيح جاء بعد تجميد النسختين وقبل تقييم النهائي لكليهما. هذا تحقق من سجلات التنفيذ؛ لم يُعد تدريب النماذج أو تغيير الترشيح.</p>
<h2>3. كيف أصبحت المقارنة عادلة؟</h2>
<p>تحققنا من تطابق ترتيب <code>sample_index</code> والطوابع الزمنية وعلامات EVENT والتنبؤ المرجعي بين الملفين. ثم أعدنا حساب مقاييس النماذج الثلاثة على <strong>تقاطع الدقائق التي توفر فيها قرار لها جميعاً</strong>. هذا يزيل اختلاف التعرض من مقارنة Precision وRecall وF1 والإنذارات الكاذبة.</p>
<p>لم تُحذف الأحداث الأصلية من مقامات مقاييس الأحداث؛ يظل الحدث غير المتاح بالكامل ضمن المقام. وتُعرض التغطية الأصلية لكل نموذج منفصلة حتى لا يخفي التقاطع فقد دقائق بسبب نافذة أطول أو سياسة استمرارية. القرارات غير المتاحة <code>-1</code> لا تُعد طبيعية.</p>
<p>في كل فترة: تدريب على الماضي، ثم معايرة واختيار، ثم تجميد، ثم تقييم الفترة التالية. تُفصل الحدود بفجوات 120 دقيقة ويعاد بدء تاريخ الميزات والسياسة. يُعاد تدريب خط الأساس على الفترة السابقة نفسها؛ لا يُستخدم نموذج مدرّب على مستقبل الاختبار. لا يوجد توسيع للعلامات أو تعديل نقاط بأثر رجعي أو دمج إنذارات باستخدام المستقبل.</p>
<h2>4. ست فترات من 2018: عرض المحاولتين كاملاً</h2>
<figure><img src="data:image/png;base64,{embedded}" alt="مقارنة النماذج الثلاثة في F1 وبدايات الأحداث المؤكدة والإنذارات الكاذبة عبر ست فترات"><figcaption>المقارنة على التقاطع الثلاثي نفسه. الأرقام عند الأحداث تذكر البسط والمقام؛ N/A تعني غياب أحداث قابلة لقياس الاستدعاء. <a href="comparison.png">الرسم PNG</a>.</figcaption></figure>
{fold_table(comparison["folds"])}
<h2>5. تجميع 2018 الاستعادي</h2>
<p>{change_sentence(walk,"v2")}</p><p>{change_sentence(walk,"v3")}</p>
{metric_table(walk)}
<h3>التغطية والمقاييس الأصلية لكل نموذج</h3>{native_table(walk)}{burden_table(walk)}
<p>جُمعت التنبؤات على المحور الأصلي 40–100% قبل تعريف الأحداث المتصلة؛ لا تجمع أعداد أحداث الفترات يدوياً، لأن حدثاً قد يلامس أو يعبر حد فترة. المقاييس الأصلية هنا تحققها التقرير مقابل JSON المحفوظ لكل تجربة، ثم حسب المقارنة المشتركة الثلاثية من جديد.</p>
<h2>6. اختبار 2019 النهائي — قسم مستقل</h2>
<p>قنوات 2019 الست هي <code>Tp, pH, Cond, Turb, SAC, PFM</code>. هذا تقييم للمنهج بعد إعادة تدريب ومعايرة على هذه القنوات، وليس نقلاً لنقطة تحقق 2018. رُتّبت ملفات التدريب والمعايرة والاختبار وفق التواريخ الفعلية بعد فحص التداخل؛ أسماء الملفات وحدها ليست دليلاً على ترتيبها.</p>
<p>{change_sentence(ext,"v2")}</p><p>{change_sentence(ext,"v3")}</p>
{metric_table(ext)}
<h3>التغطية الأصلية وعبء الإنذار في النهائي</h3>{native_table(ext)}{burden_table(ext)}
<p class="note">هذه الأرقام تصف الاختبار النهائي المحفوظ للمحاولتين. لا يُستبدل الترشيح المسبق بمرشح آخر بسبب هذه النتائج؛ أي قرار جديد مستند إليها يصبح مرحلة تطوير لاحقة تحتاج تقييماً مستقلاً جديداً. ولا تُدمج أرقام 2019 و2018 في نسبة نجاح واحدة.</p>
<h2>7. كيف تُقرأ الأرقام؟</h2>
<ul><li><strong>تغطية حدث:</strong> وجود أي إنذار داخل مدته، ولو بدأ قبله. <strong>بداية مؤكدة جديدة:</strong> انتقال معروف 0→1 داخل الحدث؛ الانتقال من -1 إلى1 أو بدء السلسلة لا يحتسب بداية مؤكدة.</li><li><strong>0 أحداث:</strong> استدعاء الأحداث غير قابل للقياس؛ يمكن قياس الإنذار الكاذب على الدقائق الطبيعية المتاحة.</li><li><strong>التأخر:</strong> وسيط زمن أول تغطية للأحداث المغطاة فقط، وقد يكون صفراً لإنذار سابق مستمر. دقة البيانات دقيقة؛ لا يثبت إغلاق صمام خلال ثوانٍ.</li><li><strong>مقاطع الإنذار الكاذب:</strong> سلاسل متصلة من الإنذارات خارج الأحداث؛ حدود الأحداث والفقد تفصل المقاطع. ذيل الإنذار بعد الحدث يُحتسب كاذباً. المقام اليومي هو الدقائق الطبيعية المتاحة ÷1,440.</li><li><strong>سقفا التشغيل:</strong> ≤1 مقطع كاذب لكل يوم طبيعي متاح و≤1% من الوقت الطبيعي المتاح تحت إنذار كاذب. تحققهما مع استدعاء ضعيف لا يكفي لقبول السلامة.</li><li><strong>Accuracy:</strong> ارتفاعها، حتى قرب99%، لا يثبت نجاح الكشف إذا كان الطبيعي هو الغالب؛ لذلك يُعرض Precision وRecall وF1 ومقامات الأحداث والتغطية والإنذار الكاذب.</li></ul>
<h2>8. حدود الدليل</h2>
<p>هذه تجربة لكشف EVENT الثنائي في بيانات منشورة، وليست تصنيفاً للأعطال الخمسة. الحدث لا يثبت وحده عطل حساس؛ قد يعكس تغيراً حقيقياً أو صيانة أو أحداث التحدي. ليست قياساً للبكتيريا أو شهادة مطابقة مياه ري أو إثباتاً على مياه وضوء ميدانية.</p>
<p>لا تتضمن النتائج قياس سرعة على Raspberry Pi، أو اختبار صمامات وسلسلة أمان، أو دمجاً ثلاثي الأبعاد. القرار0 يعني أن النموذج لم يطلق إنذاراً وفق شروطه، ولا يمنح إذناً بفتح صمام. اختلاف القنوات أو المواقع أو المواسم يتطلب تحققاً مستقلاً.</p>
<h2>9. الأدلة والملفات</h2>
<p><a href="comparison.json">جميع المقاييس والفحوص المشتقة JSON</a> · <a href="release_choice.json">اختيار الإصدار قبل الاختبار</a> · {local_link(dirs["v2"]/"protocol.json",out,"بروتوكول V2")} · {local_link(dirs["v3"]/"protocol.json",out,"بروتوكول V3")}</p>
<p>{local_link(dirs["v2"]/"walk_forward_predictions.csv.gz",out,"تنبؤات V2 لعام2018")} · {local_link(dirs["v3"]/"walk_forward_predictions.csv.gz",out,"تنبؤات V3 لعام2018")}</p>
<ul>{fold_links}</ul>
<p>قرأ التقرير سجلات التجميد والنتائج والتنبؤات المحفوظة فقط. لم يقرأ بيانات المستشعرات الخام أو يُعِد حساب درجات النماذج؛ أعاد حساب مقاييس القرار على التقاطع الثلاثي باستخدام تنفيذ المقاييس المطابق لبصمة التجربتين.</p>
<p class="muted">SHA-256 لتنفيذ المقاييس: <code class="hash">{esc(comparison["metric_code_sha256"])}</code></p>
<p>إعادة إصدار التقرير من النتائج المكتملة، من جذر المشروع:</p><pre>ml/gecco_baseline/.venv/bin/python ml/gecco_v3/make_comparison_report.py</pre>
<footer class="muted">مورد · تاريخ المحاولتين كامل، والترشيح محفوظ قبل الاختبار. الصورة مضمنة داخل HTML؛ روابط الأدلة تحتاج بقاء ملفات النتائج في مواقعها. القيم غير القابلة للحساب لا تستبدل بأصفار.</footer>
</main></body></html>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-dir",type=Path,default=ROOT/"output/ml/gecco-v2")
    parser.add_argument("--v3-dir",type=Path,default=ROOT/"output/ml/gecco-v3")
    parser.add_argument("--output-dir",type=Path,default=ROOT/"output/ml/gecco-comparison")
    args=parser.parse_args()
    dirs={"v2":args.v2_dir.resolve(),"v3":args.v3_dir.resolve()};out=args.output_dir.resolve()
    comparison,records=build_comparison(dirs,out)
    # release_choice.json already exists in this output directory; never overwrite it.
    embedded=plot_comparison(out,comparison["folds"])
    comparison["selected_final_verdict"]={"style":selected_verdict(comparison)[0],
                                          "title":selected_verdict(comparison)[1],"explanation":selected_verdict(comparison)[2]}
    (out/"comparison.json").write_text(json.dumps(comparison,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    (out/"report.html").write_text(render_html(comparison,records,dirs,out,embedded),encoding="utf-8")
    print(json.dumps({"report":str(out/"report.html"),"metrics":str(out/"comparison.json"),
                      "plot":str(out/"comparison.png"),"selected_final_verdict":selected_verdict(comparison)[1]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
