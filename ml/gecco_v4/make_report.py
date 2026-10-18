"""Build the Arabic V4 evidence report from completed saved results only.

No raw GECCO measurements or labels are read, no estimator is loaded, and no
threshold is selected. Both six-period result sets and a frozen protocol must
exist. Figures are embedded in the HTML; links to audit files are relative.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ML_OUT = ROOT / "output/ml"
COLORS = {"baseline": "#8497aa", "v4": "#007c78"}


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def esc(value):
    return html.escape(str(value), quote=True)


def pct(value, places=2):
    return "—" if value is None else f"{100 * value:.{places}f}%"


def number(value, places=2):
    return "—" if value is None else f"{value:,.{places}f}"


def events(metrics, key="confirmed_new_alarm_inside_events"):
    count, total = metrics[key], metrics["true_events"]
    return f"{count}/{total}" if total else "0/0 · غير قابل للقياس"


def link(path, out, label):
    path = Path(path)
    if not path.exists():
        return f'<span class="muted">{esc(label)} · غير موجود</span>'
    return f'<a href="{esc(os.path.relpath(path, out))}">{esc(label)}</a>'


def compact(metrics):
    return {k: v for k, v in metrics.items() if not k.endswith("records")}


def copy_linked_sources(out, protocol):
    """Package read-only audit copies so links survive an output/ml HTTP root."""
    paths = [ROOT / "ml/gecco_v4/evaluation_contract.json", ROOT / "ml/gecco_baseline/metrics.py",
             ROOT / "ml/gecco_v4/run_evaluation.py", ROOT / "ml/gecco_v4/make_report.py",
             ROOT / "ml/gecco_v4/checked_predict.py", ROOT / "ml/gecco_v4/USAGE.txt"]
    manifest = {}
    for original in paths:
        relative = original.relative_to(ROOT)
        actual = digest(original)
        frozen = protocol["code_sha256"].get(str(relative))
        if frozen is not None:
            assert frozen == actual, f"Frozen source changed: {relative}"
        target = out / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        assert digest(target) == actual
        manifest[str(relative)] = {"packaged_copy": str(target.relative_to(out)), "sha256": actual,
                                   "matched_frozen_protocol": frozen == actual if frozen is not None else None}
    (out / "source/manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {str(p.relative_to(ROOT)): out / "source" / p.relative_to(ROOT) for p in paths}


def check_results(protocol_path, results):
    protocol_hash = digest(protocol_path)
    for label, result in results.items():
        assert result["protocol_sha256"] == protocol_hash, f"Protocol mismatch: {label}"
        assert len(result["folds"]) == 6, f"Incomplete periods: {label}"
        for part in [result, *result["folds"]]:
            for scope in ("native", "common"):
                b, v = (part[scope][name] for name in ("baseline", "v4"))
                assert b["sample_count"] == v["sample_count"]
                assert b["true_events"] == v["true_events"], "Event denominators changed"
                if scope == "common":
                    assert b["valid_count"] == v["valid_count"], "Common availability mismatch"
            for name in ("baseline", "v4"):
                assert part["common"][name]["valid_count"] <= part["native"][name]["valid_count"]
        assert isinstance(result["gates"]["stable_joint_improvement"], bool)
    return protocol_hash


def metric_table(part):
    rows = []
    for scope, scope_ar in (("common", "زمن مشترك"), ("native", "تغطية أصلية")):
        for name in ("baseline", "v4"):
            m = part[scope][name]
            cells = [f'<strong dir="ltr">{name}</strong>', scope_ar, events(m),
                     events(m, "detected_events"), pct(m["precision"]), pct(m["recall"]), pct(m["f1"]),
                     str(m["false_positive_runs"]), number(m["false_alarm_runs_per_normal_day"], 3),
                     f'{m["fp"]:,} / {pct(m["normal_time_under_alarm"],4)}',
                     pct(m["prediction_coverage"]), str(m["fully_unscorable_events"]),
                     number(m["median_detection_delay_minutes"], 1)]
            rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    headers = ["النموذج", "نطاق القياس", "بدايات مؤكدة / أحداث", "أحداث مغطاة", "Precision", "Recall", "F1",
               "حلقات كاذبة", "حلقات / يوم طبيعي", "دقائق كاذبة / نسبتها", "التغطية", "أحداث غير قابلة للتقييم", "تأخر وسيط · دقيقة"]
    return table(headers, rows)


def table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{esc(h)}</th>" for h in headers) + \
           "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"


def fold_table(result, directory, out):
    rows = []
    gate = result["gates"]
    for i, part in enumerate(result["folds"], 1):
        b, v = (part["common"][name] for name in ("baseline", "v4"))
        pair = lambda key, fmt: f'<span dir="ltr">{fmt(b[key])} → {fmt(v[key])}</span>'
        cells = [link(directory / f"fold_{i}/test_results.json", out, f"الفترة {i}"),
                 f'<span dir="ltr">{events(b)} → {events(v)}</span>', pair("f1", pct),
                 pair("false_alarm_runs_per_normal_day", lambda x: number(x, 3)),
                 pair("normal_time_under_alarm", lambda value:pct(value,4)), pct(v["prediction_coverage"]),
                 "تحقق" if gate["noninferior_periods"][i - 1] else "لم يتحقق",
                 "ضمن الحدين" if gate["operating_budget_pass_per_period"][i - 1] else "تجاوز حدًا أو غير قابل للقياس"]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return table(["الفترة", "بدايات / أحداث · baseline → v4", "F1", "إنذارات كاذبة / يوم", "الوقت الطبيعي تحت إنذار", "التغطية المشتركة", "عدم التراجع المشترك", "ميزانية V4 الأصلية"], rows)


def result_section(result, key, title, subtitle, out):
    g = result["gates"]
    m = result["common"]["v4"]
    directory = out / key
    verdict = "تحقق التحسن المشترك المستقر وفق الشرط المحدد" if g["stable_joint_improvement"] else "لم يتحقق شرط التحسن المشترك المستقر"
    details = []
    for i, part in enumerate(result["folds"], 1):
        details.append(f'<details><summary>تفاصيل الفترة {i}: التغطية الأصلية والمشتركة</summary>' + metric_table(part) +
                       '<p class="small">' + link(directory / f"fold_{i}/freeze.json", out, "التجميد قبل تقييم الفترة") + " · " +
                       link(directory / f"fold_{i}/test_predictions.csv.gz", out, "درجات وتنبؤات الفترة") + "</p></details>")
    return f'''<section><div class="eyebrow">{esc(subtitle)}</div><h2>{esc(title)}</h2>
      <p class="verdict">{esc(verdict)}. عدم التراجع في {g['noninferior_period_count']}/6 فترات؛
      حدود التشغيل في {sum(g['operating_budget_pass_per_period'])}/6 فترات.</p>
      <div class="cards"><div><span>بدايات مؤكدة · V4، زمن مشترك</span><strong>{events(m)}</strong></div>
      <div><span>إنذارات كاذبة لكل يوم طبيعي</span><strong>{number(m['false_alarm_runs_per_normal_day'], 3)}</strong></div>
      <div><span>وقت طبيعي تحت إنذار</span><strong>{pct(m['normal_time_under_alarm'],4)}</strong></div>
      <div><span>التغطية المشتركة</span><strong>{pct(m['prediction_coverage'])}</strong></div></div>
      <h3>المقارنة المجملة</h3>{metric_table(result)}
      <p class="note">المقارنة الأساسية على تقاطع الصفوف التي أصدر فيها النموذجان تنبؤًا. الصفوف غير المتاحة لا تدخل مقاييس النقاط،
      لكن كل حدث موسوم يبقى في مقام الأحداث. التغطية الأصلية تكشف مقدار البيانات التي استبعدها كل نموذج.</p>
      <h3>الفترات الست</h3>{fold_table(result, directory, out)}
      <p class="small">الأسهم تعرض baseline ثم V4. صفر أحداث يعني أن حساسية كشف الأحداث غير قابلة للقياس، ويظل قياس الإنذارات الكاذبة مهمًا.</p>
      {''.join(details)}<p class="small">{link(directory/'results.json',out,'النتائج الكاملة')} ·
      {link(directory/'predictions.csv.gz',out,'التنبؤات الكاملة')}</p></section>'''


def make_figure(results, path):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titleweight": "bold", "savefig.facecolor": "white"})
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    specs = [("confirmed_new_alarm_inside_event_recall", "Confirmed event starts / all events", 100),
             ("false_alarm_runs_per_normal_day", "False alarm runs / normal day", 1),
             ("f1", "Unadjusted point F1 (%)", 100)]
    x = np.arange(1, 7)
    for row, (label, result) in enumerate(results.items()):
        for col, (metric, title, scale) in enumerate(specs):
            ax = axes[row, col]
            for role, offset in (("baseline", -.17), ("v4", .17)):
                vals = [f["common"][role][metric] for f in result["folds"]]
                yy = [np.nan if z is None else z * scale for z in vals]
                bars = ax.bar(x + offset, yy, width=.32, label=role, color=COLORS[role])
                if col == 0:
                    for bar, fold in zip(bars, result["folds"]):
                        m = fold["common"][role]
                        if m["true_events"]:
                            ax.annotate(f'{m["confirmed_new_alarm_inside_events"]}/{m["true_events"]}',
                                        (bar.get_x()+bar.get_width()/2, bar.get_height()), ha="center", va="bottom", fontsize=8, rotation=0)
            if col == 0:
                ax.set_ylim(0, 119)
                for j, fold in enumerate(result["folds"], 1):
                    if not fold["common"]["v4"]["true_events"]:
                        ax.text(j, 8, "No events", ha="center", rotation=90, fontsize=8, color="#6e7781")
            if col == 1:
                ax.axhline(1, ls="--", lw=1, color="#c07920", label="1/day reference")
                ax.set_ylim(bottom=0)
            if col == 2:
                ax.set_ylim(0, 110)
            ax.set_xticks(x)
            ax.set_xlabel("Period")
            ax.set_title(title)
            ax.grid(axis="y", alpha=.2)
            ax.set_axisbelow(True)
            if col == 0:
                ax.set_ylabel(label)
    fig.suptitle("Common-availability comparison — all labeled events retained\n2017: newly withheld historical source; 2018: disclosed development", fontsize=13)
    fig.legend(handles=[Patch(color=COLORS['baseline'],label='baseline'),Patch(color=COLORS['v4'],label='v4'),
                        Line2D([0],[0],ls='--',color='#c07920',label='1 false alarm run/day reference')],
               loc='lower center',bbox_to_anchor=(.5,-.04),ncol=3,frameon=False)
    fig.savefig(path, dpi=180, bbox_inches='tight')
    plt.close(fig)
    return base64.b64encode(path.read_bytes()).decode()


def diagnostic_section(out):
    folder = ML_OUT / "gecco-v4-diagnostics"
    d = read(folder / "diagnosis.json")
    a = d["partitions"]["external_2019"]["availability"]["test"]
    rows = []
    for n in (1, 15, 61):
        reasons = a[f"complete_{n}_unavailable_reasons"]
        values = [f"نافذة كاملة {n}", str(a[f"complete_{n}_unavailable_rows"]), pct(a[f"complete_{n}_coverage"]),
                  str(reasons["protocol_gap"]["rows"]), str(reasons["initial_history_warmup"]["rows"]),
                  str(reasons["raw_missing_after_warmup"]["rows"]), str(reasons["propagated_history_missing"]["rows"])]
        rows.append("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in values) + "</tr>")
    return f'''<section><div class="eyebrow">تصحيح وتفسير من الأدلة السابقة</div><h2>الفجوة المقصودة تختلف عن فقد قياسات الحساس</h2>
    <p><strong>الأحداث الثلاثة غير القابلة للتقييم في اختبار 2019 السابق وقعت داخل أول 120 صفًا المستبعدة بالبروتوكول.</strong>
    مجموعها 33 دقيقة، وبقيت ضمن مقام 12 حدثًا. لم يكن فقد الحساس سبب استبعاد تلك الأحداث.</p>
    <p>في البيانات نفسها {a['raw_incomplete_rows']} صفًا ناقصًا فعليًا و{a['raw_incomplete_event_rows']} دقيقة حدث ناقصة فعليًا.
    اشتراط نافذة كاملة من 61 صفًا وسّع عدم التوافر إلى {a['complete_61_unavailable_rows']:,} صفًا:
    فجوة 120 + تهيئة 60 + نقص فعلي 70 + أثر تاريخي ممتد 4083. لا تعني هذه الصفوف كلها فقدًا فعليًا.</p>
    {table(['اشتراط التاريخ','غير متاح','التغطية','الفجوة','تهيئة البداية','نقص فعلي','امتداد النقص في التاريخ'],rows)}
    <p>التشخيص أظهر تغيرًا في مستويات القنوات وأشكال الأحداث بين الفترات، ومعايرة قليلة الأحداث في بعض النوافذ.
    هذا يفسر دافع السمات النسبية والمعايرة متعددة الكتل؛ الارتباط بتغير التوزيع لا يثبت أنه السبب الوحيد للفشل.</p>
    <p class="small">{link(folder/'diagnosis.json',out,'التشخيص الكامل')} · {link(folder/'distribution_shift.csv',out,'تغير توزيعات القنوات')} ·
    {link(folder/'event_signatures.csv',out,'أشكال الأحداث')} · {link(folder/'channel_missingness.csv',out,'فقد القنوات')}</p></section>'''


def trial_section(out, protocol):
    supervised = ML_OUT / "gecco-v4-supervised-development"
    adaptive = ML_OUT / "gecco-v4-adaptive-development"
    s = read(supervised / "development_summary.json")
    adaptive_attempts = [adaptive / "results.json", *sorted(adaptive.glob("attempt*/results.json"))]
    adaptive_recipes = []
    rows, summary = [], []
    def add(family, recipe, period, m, note):
        row = {"family": family, "recipe": recipe, "scope": period, "metrics": compact(m), "note": note}
        summary.append(row)
        cells = [family, f'<span dir="ltr">{esc(recipe)}</span>', period, events(m), pct(m["f1"]),
                 number(m["false_alarm_runs_per_normal_day"], 3), pct(m["normal_time_under_alarm"],4),
                 pct(m["prediction_coverage"]), note]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    for recipe in ("relative", "ensemble"):
        add("مشرف", recipe, "2018 · ست فترات", s[recipe], "الوصفة ثابتة؛ الحساسية منخفضة")
        add("مشرف", recipe, "2019 · مكشوف للتطوير", s["2019"][recipe]["metrics"], "بقاء كل 12 حدثًا في المقام")
    stopped = read(supervised / "attempt2_invariant_first1/results.json")["results"][0]
    add("مشرف", "invariant", "2018 · الفترة الأولى فقط", stopped["metrics"], "توقفت بعد الفشل؛ ليست نتيجة ست فترات")
    for source in adaptive_attempts:
        a = read(source)
        for recipe in a["all_tried_recipes"]:
            assert recipe not in adaptive_recipes, "Duplicate development recipe"
            adaptive_recipes.append(recipe)
            note = "مرشح للفحص الإضافي؛ ليس ترقية معتمدة" if recipe == protocol["recipe"] else "نتيجة تطوير؛ لا دليل مستقل"
            if recipe == "anchored_long720":
                note = "رُفض: الحساسية والمدة لم تحسنا التوازن"
            add("تكيفي", recipe, "2018 · ست فترات", a["2018_pooled"][recipe]["native"], note)
            external = next(r for r in a["results"] if r["case"] == "2019_disclosed_final" and r["config_id"] == recipe)
            add("تكيفي", recipe, "2019 · مكشوف للتطوير", external["native"], "مستخدم لاختيار الوصفة قبل 2017")
    assert len(adaptive_recipes) == 6, "Expected all six disclosed adaptive recipes"
    attempt_links = " · ".join(link(source, out, f"سجل التكيفي {i}") for i, source in enumerate(adaptive_attempts, 1))
    section = f'''<section><div class="eyebrow">سجل المحاولات · نتائج تطوير مكشوفة</div><h2>المحاولات الناجحة والضعيفة معًا</h2>
    <p>كل بيانات 2018 و2019 ونتائجها كانت معروفة أثناء هذا التطوير. اختُبرت ثلاث وصفات مشرفة وست وصفات تكيفية.
    سُجلت محاولة السمات المجمعة <span dir="ltr">invariant</span> التي توقفت بعد الفترة الأولى؛ لا تُعرض كأنها اجتازت الفترات الست.</p>
    {table(['المسار','الوصفة','الفترة','بدايات / أحداث','F1','حلقات كاذبة / يوم','الوقت الطبيعي تحت إنذار','تغطية أصلية','التفسير'],rows)}
    <p class="note">هذا سجل التغطية الأصلية لكل وصفة، وليس مقارنة عادلة على تقاطع واحد بين جميع المحاولات.
    لا يجوز تفسير فرق هذه الصفوف وحده كفوز نهائي. المقارنة الأساسية في هذا التقرير تستخدم runner واحدًا وتقاطع baseline/V4.</p>
    <p>المشرف النسبي والمعايرة متعددة الكتل خفّضا الإنذارات، لكنهما لم يستعيدا حساسية الأحداث في 2018.
    نجاح وصفة على 2019 وحده لم يُستخدم لإعلان الثبات العام. اختيار V4 النهائي مسجل في البروتوكول قبل قراءة وسوم المصدر الجديد.</p>
    <p><strong>سبب الترشيح للفحص الإضافي:</strong> حافظت <span dir="ltr">return_gated_channel_median5</span> على 31/37 بداية مؤكدة في تطوير 2018،
    وخفضت معدل الحلقات الكاذبة إلى نحو 0.302/يوم والوقت الطبيعي تحت إنذار إلى 0.1862%، مع تحسن أضعف فترة ذات أحداث من 0/6 إلى 1/6.
    المقابل واضح: كانت نتيجة 2019 المكشوفة 7/12 مقابل 8/12 للوصفة السابقة <span dir="ltr">symmetric_return_gated180</span>.
    لذلك كان الاختيار لتقييم توازن أفضل على التطوير، ولم يكن إعلانًا بأن الثبات تحقق. وصفة <span dir="ltr">anchored_long720</span> محفوظة ضمن السجل رغم رفضها.</p>
    <p class="small">{link(supervised/'results.json',out,'كل تجارب المشرف')} · {link(supervised/'development_summary.json',out,'تجميع المشرف')} ·
    {link(supervised/'attempt2_invariant_first1/results.json',out,'المحاولة الموقوفة')} · {attempt_links} ·
    {link(ML_OUT/'gecco-comparison/report.html',out,'السجل السابق v1/v2/v3')}</p></section>'''
    return section, summary


def post_audit_section(out, sources, protocol_hash):
    audit = read(out / "final_audit.json")
    diagnosis = read(out / "external_failure_diagnosis.json")
    release = read(out / "release_status.json")
    assert audit["declared_protocol_sha256"] == protocol_hash
    assert diagnosis["protocol_sha256"] == protocol_hash
    assert release["original_benchmark_unchanged"] is True
    assert release["guarded_benchmark_performance_not_claimed"] is True
    assert digest(sources["ml/gecco_v4/checked_predict.py"]) == release["guard_source_sha256"]
    first, second = diagnosis["fold1"], diagnosis["fold2"]
    rejected = [r for r in release["records"] if not r["calibration_ready"]]
    reason_ar = {"calibration_constraints_not_established": "لم تثبت قيود المعايرة في جميع الكتل",
                 "calibration_missed_all_events_in_a_block": "فقدت المعايرة كل أحداث كتلة ذات أحداث"}
    rows = []
    for r in rejected:
        cells = ["2017" if r["scope"] == "external_2017" else "2018", str(r["fold"]), reason_ar.get(r["guard_reason"],r["guard_reason"])]
        rows.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in cells) + "</tr>")
    status_ar = "اجتاز" if audit["status"] == "pass" else "لم يجتز"
    block = f'''<section><div class="eyebrow">تفسير بعد التقييم · النتائج المجمدة باقية</div><h2>لماذا فقدت الفترتان الأوليان حساسية الكشف؟</h2>
    <p><strong>الفترة الأولى:</strong> كانت كتلة معايرة كاملة من {first['calibration_block2_rows']:,} صفًا بلا قياسات في القنوات التسع.
    لم تنجح أي نقطة تشغيل من أصل {first['calibration_operating_points_tried']} في إثبات القيود على كل الكتل، فطبّق البروتوكول المجمد العتبة الاحتياطية الأعلى من جميع درجات المعايرة.
    بقيت {first['test_event_minutes_with_available_scores']} دقيقة حدث في التقييم ذات درجات متاحة، لكن لم تتجاوز أي منها العتبة؛ النتيجة {first['test_confirmed_events']}/{first['test_true_events']}.</p>
    <p><strong>الفترة الثانية:</strong> وُجدت {second['feasible_operating_points']} نقطة تشغيل مستوفية للقيود من أصل {second['calibration_operating_points_tried']}،
    لكن جميعها أعطت حساسية صفرًا في كتلة معايرة تحتوي أحداثًا. الاختيار المجمد التقط {second['selected_calibration_confirmed_events']}/{second['selected_calibration_complete_events']}
    حدثًا سابقًا إجمالًا، مع فقد أحداث كتلة كاملة، ثم كشف {second['test_confirmed_events']}/{second['test_true_events']} فقط في الفترة التالية.</p>
    <p class="note">هذا تفسير لفشل التجربة بعد انتهائها. لا يحوّل الإخفاق إلى نجاح، ولا يغير النموذج أو العتبات أو المقام.
    غياب بيانات كتلة المعايرة في الفترة الأولى يختلف عن فقد أحداث الاختبار بسبب نقص القياسات؛ كانت درجات أحداث الاختبار متاحة وبقيت تحت العتبة.</p>
    <p class="small">{link(out/'external_failure_diagnosis.json',out,'تشخيص فشل المصدر الإضافي')} · {link(out/'final_audit.json',out,'التدقيق النهائي')}</p>
    <h3>التدقيق الحسابي اجتاز، واختبار الثبات لم ينجح</h3>
    <p>{status_ar} التدقيق {audit['checks_performed']:,} فحصًا للمقاييس والبصمات وتسلسل التجميد والسجلات.
    <strong>هذه مطابقة حسابية، وليست تحققًا من جودة الكشف أو الجاهزية الميدانية.</strong> عدد الملاحظات المسجلة: {len(audit['findings'])}.</p>
    <h3>واجهة تحجب التشغيل عند معايرة غير صالحة</h3>
    <p>أُضيفت <span dir="ltr">checked_predict.py</span> بعد مراجعة النتيجة، وتتحقق من بصمة النموذج وسجل المعايرة.
    تعيد <code>-1</code> مع سبب صريح عند عدم إثبات قيود المعايرة، أو عند حساسية صفر في كتلة معايرة ذات أحداث.
    بذلك تحجب {len(rejected)}/{len(release['records'])} نقاط تشغيل محفوظة بدل إصدار قيمة قد تُفهم كحالة طبيعية.</p>
    {table(['المصدر','الفترة','سبب الحجب في الواجهة اللاحقة'],rows)}
    <p><strong>هذه حماية لاحقة وليست نموذجًا محسنًا مقاس الأداء.</strong> اجتازت {release['guard_tests']} اختبارات صناعية،
    ولم يُعَد احتساب نتائج benchmark بها. جميع أرقام الأداء والرسم أعلاه تخص التجربة المجمدة الأصلية.
    قبول المعايرة في الواجهة لا يثبت سلامة المياه أو صلاحية فتح صمام. حالة الإصدار: <span dir="ltr">{esc(release['model_status'])}</span>.</p>
    <p class="small">{link(out/'release_status.json',out,'حالة الإصدار والحجب')} · {link(sources['ml/gecco_v4/checked_predict.py'],out,'شيفرة الواجهة اللاحقة')} ·
    {link(sources['ml/gecco_v4/USAGE.txt'],out,'دليل الاستخدام وحدود الاستنتاج')}</p></section>'''
    return block, {"audit_status":audit["status"],"audit_checks":audit["checks_performed"],
                   "guarded_operating_points_rejected":len(rejected),"operating_points":len(release["records"]),
                   "model_status":release["model_status"],"guarded_performance_not_claimed":True}


CSS = """
:root{--ink:#172b3c;--muted:#536675;--teal:#007c78;--line:#dbe4e8;--cream:#f5f8f8;--warn:#8b4c09}
*{box-sizing:border-box}body{margin:0;background:var(--cream);color:var(--ink);font:16px/1.85 Tahoma,Arial,sans-serif}
main{max-width:1370px;margin:auto;padding:30px 26px 80px}header{background:#16364a;color:white;padding:38px;border-radius:22px;margin-bottom:22px}
h1{font-size:35px;line-height:1.55;max-width:1030px;margin:12px 0 18px}h2{font-size:25px;line-height:1.6;margin:6px 0 18px}h3{font-size:19px;margin:27px 0 12px}
p{margin:12px 0}.eyebrow{font-size:12px;letter-spacing:.06em;color:var(--teal);font-weight:bold}header .eyebrow{color:#8ee2d6}.subtitle{color:#d0e0e8;max-width:1060px}
section{background:white;border:1px solid var(--line);border-radius:18px;margin:22px 0;padding:28px}.banner{border-right:5px solid #d49b47;background:#fff3df;padding:18px 22px;border-radius:10px;font-size:21px;font-weight:bold}
.banner.pass{background:#e5f4ee;border-color:var(--teal)}.banner p{font-weight:normal;font-size:15px;margin-bottom:0}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0}.cards>div{background:#f0f6f6;border:1px solid #dbe8e7;padding:18px;border-radius:12px}.cards span{display:block;font-size:13px;color:var(--muted)}.cards strong{font-size:26px;display:block;direction:ltr;text-align:right}
.table-wrap{overflow-x:auto;margin:16px 0}table{width:100%;border-collapse:collapse;font-size:12px;line-height:1.6}th{background:#edf4f5;text-align:right;white-space:normal;padding:12px 8px;color:#294b5e}td{padding:11px 8px;border-bottom:1px solid var(--line);vertical-align:top}tr:nth-child(even)td{background:#fafcfc}.note{background:#f0f5f8;border-right:3px solid #7e98ac;padding:13px 16px;font-size:14px}.small,.muted{font-size:13px;color:var(--muted)}.verdict{font-weight:bold}.figure{width:100%;height:auto}a{color:#006e80;text-decoration:underline;text-underline-offset:3px}details{border:1px solid var(--line);border-radius:8px;padding:13px;margin:10px 0}summary{cursor:pointer;font-weight:bold}code{direction:ltr;unicode-bidi:embed;overflow-wrap:anywhere;font-size:12px}footer{font-size:12px;color:var(--muted);padding:16px}
@media(max-width:800px){main{padding:15px}header,section{padding:20px}.cards{grid-template-columns:repeat(2,1fr)}h1{font-size:27px}.banner{font-size:19px}}
@media print{body{background:white;font-size:11pt}main{padding:0;max-width:none}header{border-radius:0;padding:20px;print-color-adjust:exact}section{break-inside:auto;border-radius:0;padding:16px;margin:12px 0}.cards{break-inside:avoid}.table-wrap{overflow:visible}table{font-size:8pt}tr,figure{break-inside:avoid}thead{display:table-header-group}h2,h3{break-after:avoid}details{display:block}summary{list-style:none}.figure{max-height:160mm;object-fit:contain}a{color:inherit}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ML_OUT / "gecco-v4")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    required = [out / "protocol.json", out / "external_2017/results.json", out / "development_2018/results.json",
                out / "final_audit.json", out / "external_failure_diagnosis.json", out / "release_status.json"]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("Completed frozen results required; missing: " + ", ".join(missing))
    protocol, external, development = [read(p) for p in required[:3]]
    results = {"2017 historical check": external, "2018 development": development}
    protocol_hash = check_results(required[0], results)
    assert protocol["new_source_event_values_read_before_freeze"] is False
    sources = copy_linked_sources(out, protocol)
    audit_html, audit_summary = post_audit_section(out, sources, protocol_hash)
    figure = make_figure(results, out / "period_comparison.png")
    trials_html, trials = trial_section(out, protocol)
    stable_external = external["gates"]["stable_joint_improvement"]
    stable_development = development["gates"]["stable_joint_improvement"]
    if stable_external and stable_development:
        headline = "تحسن مشترك عبر الفترات في المقارنة المحددة؛ الدليل ما زال تاريخيًا"
    elif stable_external:
        headline = "تحسن في التحقق التاريخي الإضافي، لكن الثبات عبر كل الفترات لم يثبت"
    elif external["gates"]["pooled_joint_improvement"]:
        headline = "تحسن إجمالي في التحقق الإضافي، دون ثبات مشترك في الفترات الست"
    else:
        headline = "لم يثبت تحسن مستقر يجمع كشف أحداث أكثر وإنذارات أقل"
    budget = external["gates"]["all_period_operating_budget_pass"]
    budget_text = "تحققت ميزانية الإنذارات في كل الفترات الست." if budget else "لم تتحقق ميزانية الإنذارات في كل الفترات الست؛ راجع الفترات المتجاوزة."
    base_external, candidate_external = external["common"]["baseline"], external["common"]["v4"]
    if candidate_external["confirmed_new_alarm_inside_events"] < base_external["confirmed_new_alarm_inside_events"]:
        tradeoff = (f"في المصدر الإضافي 2017 انخفض عدد الأحداث ذات البداية المؤكدة من {events(base_external)} إلى {events(candidate_external)}، "
                    f"وانخفض F1 من {pct(base_external['f1'])} إلى {pct(candidate_external['f1'])}. "
                    f"انخفضت الحلقات الكاذبة من {number(base_external['false_alarm_runs_per_normal_day'],3)} إلى "
                    f"{number(candidate_external['false_alarm_runs_per_normal_day'],3)} لكل يوم طبيعي، لكن ذلك جاء مع فقد واضح في حساسية الكشف.")
    else:
        tradeoff = (f"في المصدر الإضافي 2017: بدايات مؤكدة {events(candidate_external)} مقابل {events(base_external)} لخط الأساس؛ "
                    f"F1={pct(candidate_external['f1'])}. تقييم الثبات يعتمد أيضًا على كل فترة وعلى مدة الإنذارات الكاذبة.")
    promotion = "لا تدعم هذه النتيجة ترقية النموذج أو ربطه بواجهة 3D." if not stable_external else "هذه نتيجة تحقق تاريخي محدد، ولا تمنح وحدها جاهزية ميدانية أو إذن ربط تحكم."
    generated = datetime.now(timezone.utc).isoformat()
    body = f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>مورد | مراجعة الثبات — GECCO V4</title><style>{CSS}</style></head><body><main>
    <header><div class="eyebrow">مورد / أدلة تعلم الآلة / الإصدار الرابع</div><h1>نتائج تحسين كشف الشذوذ واختبار ثباته</h1>
    <p class="subtitle">مقارنة نموذج ثابت مع خط الأساس، بعد تجميد الوصفة وقياس ست فترات متعاقبة. الأرقام هنا تصف كشف حدث ثنائي في بيانات GECCO، ولا تثبت تشغيلًا ميدانيًا.</p>
    <p class="small" style="color:#d0e0e8">الوصفة المجمدة: <span dir="ltr">{esc(protocol['family'])} / {esc(protocol['recipe'])}</span> · تجميد <span dir="ltr">{esc(protocol['frozen_at_utc'])}</span></p></header>
    <div class="banner {'pass' if stable_external and stable_development else ''}">{headline}<p>{tradeoff}</p>
    <p><strong>{promotion}</strong> {budget_text} الحكم مستمد من بوابات المقارنة المسجلة، ولا يساوي جاهزية هندسية عامة.</p></div>
    <section><div class="eyebrow">كيف يُقرأ الحكم</div><h2>النجاح يجمع ثلاثة شروط، ولا يعتمد على F1 وحده</h2>
    <p>في الزمن المشترك: يزيد عدد الأحداث ذات بداية إنذار مؤكدة، وتنخفض حلقات الإنذار الكاذب لكل يوم طبيعي، ولا تزيد نسبة الوقت الطبيعي تحت إنذار.
    ولتسمية التحسن مستقرًا يجب أيضًا ألا يتراجع أي من المقاييس الثلاثة في أي فترة من الفترات الست مقارنة بخط الأساس.</p>
    <p>ميزانية التشغيل منفصلة: بحد أقصى حلقة كاذبة واحدة لكل يوم طبيعي و1% من الوقت الطبيعي تحت إنذار، في كل فترة، حسب التغطية الأصلية لـV4.
    ارتفاع الدقة العامة بسبب كثرة الدقائق الطبيعية لا يُعد نجاحًا. تغطية حدث بإنذار قديم لا تساوي بدء إنذار جديد؛ البداية المؤكدة تتطلب انتقالًا معروفًا من 0 إلى 1.</p>
    <p class="note">GECCO2017 مصدر جديد للتحقق في هذا المشروع، لكنه أقدم تاريخيًا من 2018/2019. صُممت الوصفة باستخدام المعلومات اللاحقة المكشوفة 2018/2019؛
    لذلك هذا تحقق تاريخي محجوب سابقًا، وليس محاكاة نشر إلى المستقبل أو دليلًا على موقع جديد. الفترات الست داخل مصدر واحد وليست ست تجارب ميدانية مستقلة.</p></section>
    {result_section(external,'external_2017','المصدر التاريخي الإضافي · GECCO2017','لم تُفتح وسومه قبل تجميد الوصفة',out)}
    {audit_html}
    <section><h2>شكل النتائج عبر الفترات</h2><img class="figure" src="data:image/png;base64,{figure}" alt="Six-period comparison of confirmed event starts, false alarm runs per normal day and point F1 for2017and2018">
    <p class="small">الرسم يستخدم الزمن المشترك. أعداد الأحداث مكتوبة فوق الأعمدة؛ الفترات بلا أحداث موسومة صراحة. خط1/يوم مرجع بصري، بينما حكم ميزانية التشغيل في الجداول يستخدم التغطية الأصلية.</p></section>
    {result_section(development,'development_2018','إعادة القياس على GECCO2018','تطوير مكشوف · ليس اختبارًا مستقلاً',out)}
    {diagnostic_section(out)}{trials_html}
    <section><div class="eyebrow">المنهجية وحدود الاستنتاج</div><h2>الماضي يختار التشغيل، ثم يُجمّد قبل الفترة التالية</h2>
    <p>في كل فترة: تدريب من بداية السلسلة حتى ما قبل 20% سابقة، ثم أربع كتل معايرة متتالية تمثل 5% لكل كتلة، ثم تقييم 10% التالية.
    يتوسع التدريب مع الزمن. تختار المعايرة العتبة وسياسة الاستمرار السببية على الكتل الماضية، تحت الحدين في كل كتلة؛ تُقدّم أضعف حساسية حدث في كتلة ثم الحساسية المجمعة ثم F1.
    الفترات بلا أحداث تقيّد الإنذارات أيضًا، وعند غياب كل الأحداث يُفضّل التشغيل المحافظ وفق القاعدة نفسها.</p>
    <p>تُحفظ أول 120 صفًا من كل كتلة كتنبؤات غير متاحة، ثم تُهيّأ السمات من السياق الماضي. المقام لا يسقط أحداث الفجوة أو النقص.
    لا ملء مستقبلي ولا تعديل للتنبؤات بعد رؤية الحدث. تُجمّد عائلة النموذج والسمات قبل المصدر الإضافي، وتُجمّد العتبة لكل فترة قبل وسومها.</p>
    <p>كل نموذج يُعاد تدريبه داخل الفترات؛ هذه مقارنة لمنهج الكشف وليست نقلًا مباشرًا لنقطة تحقق واحدة.
    الحدث الموسوم وحدة تقييم في بيانات GECCO؛ لا تحدد الوسمة وحدها سببًا فيزيائيًا أو تثبت تلوثًا فعليًا.
    ليست النتيجة تصنيفًا لخمسة أعطال، أو إثباتًا على Raspberry Pi، أو دليل جودة مياه ميداني، أو إذنًا بفتح صمام. لم يُربط أي نموذج بواجهة 3D.</p>
    <p>التأخر معروض بالدقائق وبشرط وجود كشف؛ تأخر صفر يعني نفس عينة الدقيقة ولا يعني استجابة آنية. الإنذار الممتد خارج الحدث يُحتسب زمنًا كاذبًا وحلقة كاذبة بحسب التعريف الأصلي.</p>
    <p class="small">{link(out/'protocol.json',out,'البروتوكول وبصمات الشيفرة')} · {link(sources['ml/gecco_v4/evaluation_contract.json'],out,'عقد التقييم')} ·
    {link(sources['ml/gecco_baseline/metrics.py'],out,'تعريف المقاييس')} · {link(sources['ml/gecco_v4/run_evaluation.py'],out,'runner')} ·
    {link(sources['ml/gecco_v4/make_report.py'],out,'مولّد هذا التقرير')} · {link(out/'source/manifest.json',out,'بصمات النسخ المرجعية المرفقة')}</p>
    <p class="small">إعادة إنشاء العرض فقط: <code>ml/gecco_baseline/.venv/bin/python -B ml/gecco_v4/make_report.py</code>.
    لا يقرأ مولّد التقرير البيانات الخام ولا يعيد التدريب أو اختيار العتبات. ملفات joblib المحلية الموثوقة فقط إذا استُخدمت لاحقًا.</p></section>
    <section><h2>ملفات التجربة</h2><p><a href="../mawrid-ai-v4-evaluation.zip">تنزيل حزمة التقييم كاملة</a></p>
    <p class="small">تحتفظ الحزمة بالأدلة والمحاولات والنتيجة السلبية؛ لا تعني حالة الإصدار ترقية النموذج. تُحفظ الروابط النسبية داخل بنية المجلدات المرفقة.</p></section>
    <footer>أنشئ {esc(generated)} · بصمة البروتوكول <code>{protocol_hash}</code><br>الصورة وCSS مضمنان؛ روابط الأدلة نسبية وتتطلب بقاء مجلدات المشروع.</footer>
    </main></body></html>'''
    (out / "report.html").write_text(body)
    summary = {"generated_at_utc": generated, "headline": headline, "tradeoff": tradeoff, "promotion_decision": promotion, "protocol_sha256": protocol_hash,
               "source_inputs_sha256": {str(p.relative_to(ROOT)): digest(p) for p in required},
               "external_2017": {"gates": external["gates"], **{scope: {name: compact(m) for name, m in external[scope].items()} for scope in ("native", "common")}},
               "development_2018": {"gates": development["gates"], **{scope: {name: compact(m) for name, m in development[scope].items()} for scope in ("native", "common")}},
               "all_v4_development_recipes": trials, "post_audit":audit_summary,"3d_connected": False}
    (out / "report_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"report": str(out / "report.html"), "figure": str(out / "period_comparison.png"), "headline": headline}, ensure_ascii=False))


if __name__ == "__main__":
    main()
