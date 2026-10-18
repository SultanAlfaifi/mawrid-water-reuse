"""Render completed, audited V6 evidence without changing frozen methods."""
from pathlib import Path
from datetime import datetime, timezone
import json, html

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / 'output/ml/gecco-v6-development'
FRESH = ROOT / 'output/ml/gecco-v6-waterhub-first-use'
OUT = ROOT / 'output/ml/gecco-v6'

def read(p): return json.loads(p.read_text())
def percent(x): return 'غير متاح' if x is None else f'{100*x:.1f}%'
def change(a, b): return f'<span dir="ltr">{a} → {b}</span>'
def link(href, title): return f'<a href="{href}">{title}</a>'
def number(x): return 'غير متاح' if x is None else f'{x:.4f}'
def minutes(stats): return stats['fp_duration_seconds'] / 60
def normal_days(stats):
    seconds = stats.get('normal_observed_seconds')
    return None if seconds is None else seconds / 86400
def period_judgement(result):
    exposure = min(result[name]['normal_observed_seconds'] for name in ('baseline', 'candidate'))
    if exposure <= 0: return 'غير قابل لتقييم الإنذارات الكاذبة'
    if not result['noninferior']: return 'تراجع وفق المقاييس المحددة'
    if exposure < 1440 * 60: return 'بلا تراجع مرصود؛ تعرض طبيعي معلوم غير كافٍ'
    return 'بلا تراجع وفق المقاييس المحددة'

def main():
    audit = read(FRESH / 'audit.json')
    if audit.get('passed') is not True:
        raise RuntimeError('Independent audit must pass before reading evaluation results')
    dev = read(DEV / 'run_04/results.json'); fresh = read(FRESH / 'results.json')
    if (len(fresh['periods']) != 6 or len({r['case'] for r in fresh['periods']}) != 6
            or fresh['acceptance']['checks'].get('six_complete_periods') is not True):
        raise RuntimeError('Six distinct completed periods are required for this report')
    b, c = [dev['overall']['totals'][name] for name in ('baseline', 'candidate')]
    fb, fc = [fresh['pooled'][name] for name in ('baseline', 'candidate')]
    passed = fresh['acceptance']['passes_fresh_validation_requirements']
    decision = 'اجتاز شروط التحسن على المصدر الجديد' if passed else 'لم يجتز شرط التحسن الثابت على المصدر الجديد'
    event_total = b['true_events']
    dev_b_events, dev_c_events = [m['confirmed_new_alarm_inside_events'] for m in (b, c)]
    dev_gate = dev['v6_acceptance']
    dev_days = [m['normal_valid_count'] / 1440 for m in (b, c)]
    dev_rates = [m['false_positive_runs'] / days if days else None for m, days in zip((b, c), dev_days)]
    dev_rate_note = ('بقي معدل V6 أعلى من إنذار واحد لكل يوم طبيعي مرصود.'
                     if dev_rates[1] is not None and dev_rates[1] > 1 else '')
    fresh_rate_note = ('بقي معدل V6 أعلى من إنذار واحد لكل يوم طبيعي معلوم مرصود.'
                       if fc['false_runs_per_day'] is not None and fc['false_runs_per_day'] > 1 else '')
    period_rows = []
    for r in fresh['periods']:
        l, rr = r['baseline'], r['candidate']
        period_rows.append(f'<tr><td>{link("../gecco-v6-waterhub-first-use/"+r["case"]+"/results.json",r["case"])}</td><td>{change(l["confirmed_events"],rr["confirmed_events"])} / {l["true_events"]}</td><td>{change(l["false_positive_runs"],rr["false_positive_runs"])}</td><td>{change(f"{minutes(l):g}",f"{minutes(rr):g}")}</td><td>{l["normal_observed_seconds"]/60:g}</td><td>{len(r["lost_baseline_event_ids"])}</td><td>{period_judgement(r)}</td></tr>')
    dev_rows = []
    for folder in sorted((DEV / 'run_04').iterdir()):
        if not (folder / 'results.json').exists(): continue
        r = read(folder / 'results.json'); l, rr = r['baseline'], r['candidate']
        dev_rows.append(f'<tr><td>{folder.name}</td><td>{change(l["confirmed_new_alarm_inside_events"],rr["confirmed_new_alarm_inside_events"])} / {l["true_events"]}</td><td>{change(l["false_positive_runs"],rr["false_positive_runs"])}</td><td>{change(l["fp"],rr["fp"])}</td></tr>')
    attempts = []
    for i in range(1,5):
        r = read(DEV / f'run_{i:02d}/results.json'); t = r['overall']['totals']['candidate']
        attempts.append(f'<tr><td>{i}</td><td>{t["confirmed_new_alarm_inside_events"]}/{t["true_events"]}</td><td>{t["false_positive_runs"]}</td><td>{t["normal_alarm_minutes"]:g}</td><td>{sum(r["overall"]["noninferior_periods"])}/{len(r["overall"]["noninferior_periods"])}</td></tr>')
    check_names = {
        'six_complete_periods':'اكتمال الأشهر الستة',
        'each_period_has_one_day_observed_known_normal':'1440 دقيقة موسومة طبيعيًا وقابلة للرصد على الأقل في كل شهر',
        'all_periods_and_pool_noninferior':'كل شهر والمجموع يحفظان هويات أحداث الأساسي وتوافره، بلا تأخير إضافي أو زيادة عدد الإنذارات الكاذبة ومدتها',
        'strictly_more_pooled_events':'زيادة إجمالي الأحداث المكتشفة',
        'strictly_fewer_pooled_false_runs':'خفض إجمالي الإنذارات الكاذبة',
        'event_gain_in_at_least_two_periods':'زيادة اكتشاف الأحداث في شهرين على الأقل',
        'false_run_reduction_in_at_least_two_periods':'خفض الإنذارات الكاذبة في شهرين على الأقل',
        'at_least_five_primary_events':'وجود خمسة أحداث مثبتة البداية على الأقل',
        'at_least_two_eventful_periods':'وجود أحداث في شهرين على الأقل',
    }
    checks = ''.join(f'<li>{"✓" if value else "✕"} {check_names[key]}</li>' for key,value in fresh['acceptance']['checks'].items())
    diagnosis = read(FRESH / 'post_test_diagnosis.json')['summary']
    timestamp = datetime.now(timezone.utc).isoformat()
    page = f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — نتائج V6</title><style>
    body{{font:18px/1.9 system-ui,sans-serif;background:#f2f6f4;color:#173a33;max-width:1100px;margin:40px auto;padding:0 24px}}h1{{font-size:34px;line-height:1.5}}h2{{font-size:25px}}section{{background:white;border:1px solid #dae4df;border-radius:16px;padding:25px;margin:24px 0}}.notice{{background:#fff6e6;border-right:5px solid #b88627;padding:20px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:15px}}.card{{background:#e2eee8;padding:18px;border-radius:12px}}.big{{display:block;font-size:28px;font-weight:700;direction:ltr;unicode-bidi:isolate}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:15px}}th,td{{border-bottom:1px solid #dce6e1;padding:11px;text-align:right}}td:nth-child(n+2){{text-align:center}}a{{color:#126455}}small{{color:#526c63}}details{{margin:20px 0}}summary{{cursor:pointer;font-weight:700}}</style>
    <p>مورد · كشف شذوذ الحساسات · V6</p><h1>تحسن واضح في التطوير؛ {decision}</h1>
    <div class="notice"><b>الحكم مبني على النتائج المحفوظة، لا على أفضل فترة فقط.</b> ثُبّت كود WaterHub وبروتوكوله قبل أول اطلاع على القياسات والوسوم، ثم نُفّذ التقييم الزمني كاملًا. بقيت قواعد الطريقة ثابتة خلال الأشهر الستة، مع إعادة التدريب والمعايرة من الماضي لكل شهر. وصل الاكتشاف على المصدر الجديد إلى <b>{fc['confirmed_events']} من {fb['true_events']} ({percent(fc['confirmed_event_recall'])})</b>، لذلك لا تكفي زيادة العدد وحدها لوصف النموذج بأنه قوي. هذه النتيجة لا تمثل اعتمادًا ميدانيًا لمياه الوضوء، ولم يُربط النموذج بالـ3D أو بالصمام.</div>
    <section><h2>GECCO: نتائج التطوير على 13 فترة</h2><div class="cards"><div class="card">الأحداث المكتشفة<strong class="big">{dev_b_events} → {dev_c_events} / {event_total}</strong>{change(percent(dev_b_events/event_total if event_total else None),percent(dev_c_events/event_total if event_total else None))} من الأحداث؛ عدد هويات أحداث الأساسي المفقودة: {dev['overall']['lost_baseline_events']}</div><div class="card">الإنذارات الكاذبة<strong class="big">{b['false_positive_runs']} → {c['false_positive_runs']}</strong>تغير نسبي: {percent((c['false_positive_runs']-b['false_positive_runs'])/b['false_positive_runs'] if b['false_positive_runs'] else None)}</div><div class="card">دقائق الإنذار الكاذب<strong class="big">{b['normal_alarm_minutes']:g} → {c['normal_alarm_minutes']:g}</strong>تغير نسبي: {percent((c['normal_alarm_minutes']-b['normal_alarm_minutes'])/b['normal_alarm_minutes'] if b['normal_alarm_minutes'] else None)}</div><div class="card">الفترات بلا تراجع<strong class="big">{sum(dev['overall']['noninferior_periods'])} / {len(dev['overall']['noninferior_periods'])}</strong>تحسن الأحداث في {dev_gate['event_gain_periods']} فترات، وانخفضت الإنذارات في {dev_gate['false_run_reduction_periods']}</div></div><p>F1 على مستوى العينات: {change(f'{b["f1"]:.4f}',f'{c["f1"]:.4f}')}. اختيرت المحاولة الرابعة بعد أربع محاولات V6 على بيانات GECCO المكشوفة مسبقًا، مع محاولات أقدم قبل V6. لذلك فهذه أرقام تطوير استُخدمت لاختيار الطريقة، وليست دليلًا مستقلًا على تعميمها. «بلا تراجع» لا يعني تحسنًا في كل فترة، وهذه النسب لالتقاط الأحداث وليست دقة النظام.</p><p>التعرض الطبيعي المرصود: {change(number(dev_days[0]),number(dev_days[1]))} يومًا، الأساسي → V6. معدل مقاطع الإنذار الكاذب لكل يوم طبيعي مرصود: {change(number(dev_rates[0]),number(dev_rates[1]))}. {dev_rate_note} مقارنة الأعداد وحدها لا تصف العبء التشغيلي دون مدة التعرض.</p></section>
    <section><h2>لماذا كان الأداء يتغير بين الفترات؟</h2><p>تتغير مستويات التشغيل وأشكال الأحداث مع الزمن؛ التغير المحلي وحده قد يلتقط خطوة تشغيل طبيعية، كما أن تحرك الوسيط المرجعي قد يبقي أثرًا مرتفعًا بعد انتهاء الحدث. وكان استمرار التصويت بعد زوال الدليل، أو إعادة تقطيع إنذار واحد، يرفع الإنذارات أو مدتها.</p><p>أُضيفت مؤشرات للقفزة والتغير المستمر حول التاريخ السابق للحساس. يشترط مسار التغير المحلي حركة فعلية وتأييدًا من مصنّف شكل الحدث وفق معايرة الماضي. وأصبح كبح الإنذار مشروطًا ببقاء المؤشرات المحلية ضمن المجال المتعلّم. إذا سُمح بإنذار النموذج الأساسي، يبقى متصلًا حتى يزول إنذاره الأساسي؛ ولا يمتد إنذار المسار الإضافي بعد زوال دليله الحالي.</p><p>تختبر المعايرة الخرج المشترك وهويات الأحداث، ومدة الإنذار وعدده في كل فترة. عند ضعف الدليل قد يُعطّل المسار الإضافي، وقد تُبقي المعايرة خرج الأساسي أو مسار الكبح المقبول. اختيار الأساسي كما هو لا يُنسب إلى تحسن النموذج.</p><details><summary>المحاولات الأربع، بما فيها غير الناجحة</summary><table><tr><th>المحاولة</th><th>الأحداث</th><th>إنذارات كاذبة</th><th>دقائقها</th><th>فترات بلا تراجع</th></tr>{''.join(attempts)}</table></details><details><summary>تفصيل فترات GECCO</summary><div class="scroll"><table><tr><th>الفترة</th><th>الأحداث: الأساسي → V6</th><th>إنذارات كاذبة</th><th>دقائقها</th></tr>{''.join(dev_rows)}</table></div></details></section>
    <section><h2>WaterHub: اختبار المصدر الجديد على ستة أشهر</h2><p>هذا اختبار لطريقة التعلم من تاريخ موقع جديد: حساسات ضغط في معالجة مياه رمادية من تركيب واحد. في كل شهر، درّبنا النماذج على التاريخ الأقدم، وعايرناها على الشهرين السابقين، ثم اختبرنا الشهر التالي. هذا تقييم لإعادة تدريب الطريقة ومعايرتها محليًا، وليس نقلًا مباشرًا لأوزان GECCO إلى موقع لم تتعلم منه. لم تُعدّل قواعد الطريقة بعد مشاهدة النتائج، لكن الأشهر السابقة تدخل تاريخ التعلم لاحقًا وفق البروتوكول. الأشهر الستة من تركيب واحد وليست ستة مصادر مستقلة.</p><div class="cards"><div class="card">الأحداث التي التُقطت ببداية إنذار<strong class="big">{fb['confirmed_events']} → {fc['confirmed_events']} / {fb['true_events']}</strong>{change(percent(fb['confirmed_event_recall']),percent(fc['confirmed_event_recall']))}</div><div class="card">الإنذارات الكاذبة<strong class="big">{fb['false_positive_runs']} → {fc['false_positive_runs']}</strong>مقاطع إنذار داخل الوقت الموسوم طبيعيًا</div><div class="card">دقائق الإنذار الكاذب<strong class="big">{minutes(fb):g} → {minutes(fc):g}</strong>مدة مقدرة من العينات الموسومة طبيعيًا</div><div class="card">F1 للنقاط المعروفة والمرصودة<strong class="big">{number(fb['f1_observed_points'])} → {number(fc['f1_observed_points'])}</strong>يستبعد النقاط غير المرصودة؛ تغطيتها معروضة أدناه</div></div><p>التعرض الطبيعي المعلوم المرصود: {change(number(normal_days(fb)),number(normal_days(fc)))} يومًا، الأساسي → V6. مقاطع الإنذار الكاذب لكل يوم طبيعي معلوم مرصود: {change(number(fb["false_runs_per_day"]),number(fc["false_runs_per_day"]))}. {fresh_rate_note} يُعرض المعدل «غير متاح» إذا لم توجد مدة طبيعية معلومة قابلة للرصد؛ ولا يثبت انخفاض العدد وحده تحسنًا في الحساسية.</p><div class="scroll"><table><tr><th>شهر الاختبار</th><th>الأحداث: الأساسي → V6</th><th>إنذارات كاذبة</th><th>دقائقها</th><th>دقائق الطبيعي المعلوم المرصود</th><th>أحداث سابقة مفقودة</th><th>الحكم</th></tr>{''.join(period_rows)}</table></div><p>F1 للعينات المعروفة والقابلة للرصد: {change(f'{fb["f1_observed_points"]:.4f}' if fb['f1_observed_points'] is not None else '—',f'{fc["f1_observed_points"]:.4f}' if fc['f1_observed_points'] is not None else '—')}. هذا لا يساوي دقة النظام أو معدل اكتشاف الأحداث. عند عرض 0/0 لا توجد أحداث ذات بداية معلومة لقياس الاستدعاء؛ ولا يثبت عدم التراجع في هذه الأشهر حساسية الكشف. مدة الإنذار مقدرة من عدد العينات × زمن العينة، وليست قياسًا مستمرًا للحالة المادية. «طبيعي» هنا وسم المصدر، لا شهادة سلامة المياه.</p><h3>{decision}</h3><ul>{checks}</ul></section>
    <section><h2>ما الذي يفسّر القصور المتبقي؟</h2><p>هذه قراءة استكشافية بعد اكتمال الاختبار، وليست تحققًا جديدًا أو نتيجة نموذج معدل. في {diagnosis['baseline_missed_events_below_IF_threshold']} حدثًا فات النموذج الأساسي، بقيت أعلى درجة داخل الحدث دون عتبة التنبيه. لم يكن أي حدث غير قابل للرصد بالكامل، ولم تغب إلا {diagnosis['positive_unavailable_rows']} دقيقة موجبة من {diagnosis['known_positive_rows']:,}؛ لذلك لا يفسّر نقص القراءات هذا الضعف.</p><p>اختلفت طبيعة الوسوم بين المصدرين: وسيط طول المقطع الموجب {diagnosis['waterhub_duration_minutes']['median']:g} دقيقة في WaterHub مقابل {diagnosis['gecco_duration_minutes']['median']:g} في GECCO، ونسبته من الصفوف {percent(diagnosis['waterhub_positive_fraction'])} مقابل {percent(diagnosis['gecco_positive_fraction'])}. هذه مقارنة بين مصدرين وسياسَتي وسم مختلفتين، لا إثبات لأصناف أعطال مادية. غطّى V6 نحو {percent(diagnosis['candidate_positive_point_coverage'])} فقط من الدقائق الموجبة رغم زيادة عدد بدايات الأحداث المكتشفة.</p><p>الكبح المحافظ لم يجد مجالًا كافيًا للتحسين: تعطّل لقلة أحداث المعايرة في نوفمبر ومارس وأبريل، وحافظ على معظم الإنذارات في ديسمبر ويناير عندما لم يسمح شرط التغير المحلي بكبحها. خفّض فبراير وحده أربعة إنذارات. مكاسب الاكتشاف جاءت من ثلاثة أحداث في نوفمبر عبر مسار القفزة، وستة في مارس عبر درجة مصنّف شكل الحدث مباشرةً؛ مسار مارس مستقل عن شرط الحركة المحلية. لذلك يبقى المطلوب تحسين تمثيل الأحداث الممتدة والمعايرة، ثم اختبار مستقل جديد؛ لا يجوز اعتبار إعادة الاختبار على WaterHub بعد هذا التحليل تحققًا محجوبًا جديدًا.</p><p>{link('../gecco-v6-waterhub-first-use/post_test_diagnosis.json','التشخيص اللاحق: توزيعات الدرجات وقرارات المعايرة وهويات الأحداث')}</p></section>
    <section><h2>البيانات الناقصة ومنع التسريب</h2><p>التغطية بالوسوم المعروفة: {percent(fb['known_label_fraction'])}؛ توافر تنبؤ النموذج الأساسي: {percent(fb['sensor_available_fraction'])}؛ تغطية النقاط الموجبة القابلة للرصد: {percent(fb['point_positive_observed_fraction'])}. بقي {fb['unknown_label_rows']:,} صفًا مجهول الوسم في المحور الزمني، ولم يُحوّل إلى مثال طبيعي.</p><p>الحدث الأساسي مقطع من وسوم 1 تسبقه مباشرة عينة ذات وسم 0؛ ولا يثبت ذلك توقيت عطل مادي بعينه. يتطلب اكتشافه انتقال التنبؤ الأصلي من 0 إلى 1 داخل المقطع؛ لا يكفي إنذار قائم عند بدايته أو انتقال من عدم التوافر إلى الإنذار. عُرض أيضًا {fb['left_censored_positive_segments']} مقطعًا موجبًا مجهول البداية لأنه يبدأ عند أول الصفوف أو بعد وسم مجهول؛ يبقى في إحصاءات النقاط والتغطية، ويُستبعد من مقام الأحداث الأساسية. يبقى الحدث ذو البداية المعلومة في المقام إذا لم يتوافر له تنبؤ. قد تنقسم مقاطع الإنذار الكاذب عند الوسوم المجهولة، فلا تساوي بالضرورة بدايات إنذار مادية منفصلة. إجمالي الأحداث المجمّع يُحسب مرة واحدة على نوفمبر–أبريل، وقد يختلف عن جمع أعداد الأشهر عند الحدود.</p><p>كل دقيقة تستخدم قراءة الضغط عند الثانية 50 بعد التأكد من وجود ستة أزمنة خام فريدة ومتطابقة بين المسارين، ويصدر القرار عند نهاية الدقيقة. لا استيفاء ولا تعبئة مستقبلية. تُستبعد الدقائق ذات تكرار الساعة وفق قناع توقيت ثابت مستقل عن القيم. السببية البرمجية مشروطة بهذا القناع وإغلاق الدقيقة؛ المنطقة الزمنية وتاريخ التصدير من الجهاز غير موثقين بالكامل.</p><p>يُستبعد أول 120 صفًا في كل كتلة معايرة أو اختبار قبل حساب المزايا. تتعلم النماذج والمعايير من الماضي فقط، وتُحفظ الحزمة وبصمتها قبل حساب الاختبار. استخدام وسوم الأشهر السابقة يفترض إتاحتها يدويًا في ذلك الوقت. لا تدخل الوسوم أو إتاحتها في مسار التنبؤ.</p></section>
    <section><h2>المراجعة والملفات</h2><p>نجح 120 اختبارًا قبل فتح المصدر. أُعيدت نتائج GECCO من الحزم المحفوظة على 188,791 صفًا، مع تطابق معالجة متتابعة على 720 صفًا واختبارات منفصلة للإنذار الطويل. أعادت مراجعة WaterHub المستقلة استدلال 260,640 صفًا وتطابقت أكثر من 7 ملايين مقارنة رقمية. وتطابقت إعادة بناء 480,960 صفًا من 82 ملف مصدر، والمعالجة المتتابعة على 600 صف إضافي. نجاح هذا التدقيق يؤكد صحة الحسابات، ولا يحوّل فشل شرط القبول إلى نجاح. لا يوجد قياس سرعة على Raspberry Pi ضمن هذه النتائج.</p><p>{link('../gecco-v6-waterhub-first-use/protocol.json','البروتوكول المثبّت')} · {link('../gecco-v6-waterhub-first-use/results.json','نتائج المصدر الجديد')} · {link('../gecco-v6-waterhub-first-use/audit.json','إعادة الحساب والتدقيق')} · {link('../gecco-v6-waterhub-first-use/source_adapter_audit.json','تغطية المصدر ومعالجته')} · {link('../gecco-v6-waterhub-first-use/source_runtime_replay_audit.json','إعادة بناء المصدر وتطابق التشغيل المتتابع')} · {link('../gecco-v6-development/selected_method.json','المحاولات واختيار الطريقة')} · {link('../gecco-v6-development/run_04/runtime_replay_audit.json','تدقيق GECCO والتشغيل المتتابع')}</p><p>هذه البيانات لا تثبت كشف التلوث الكيميائي أو تصنيف الأعطال الخمسة أو أمان فتح الماء. واجهة الاستدلال الحالية تُخرج درجات وقرارات تنبيه برمجية ولا ترسل أوامر صمام. يلزم اختبار موقعي لمورد قبل أي اعتماد ميداني أو ربط تشغيلي بالـ3D أو بالمشغلات.</p></section><small>إنشاء التقرير: <span dir="ltr">{timestamp}</span></small></html>'''
    OUT.mkdir(parents=True, exist_ok=True); (OUT / 'report.html').write_text(page)
    (OUT / 'status.json').write_text(json.dumps({'created_at_utc':timestamp,'development_pass':bool(dev_gate['passes_development_requirements']),
        'fresh_evaluation_complete':True,'fresh_acceptance':fresh['acceptance'],'fresh_source_consumed':True,
        'independent_audit_file':'../gecco-v6-waterhub-first-use/audit.json','three_d_connected':False,
        'field_deployment_approved':False,'goal_achieved':False,'next_required':'Improve sensitivity to longer labeled events and conservative calibration in disclosed development; obtain new untouched validation before approval.'},indent=2)+'\n')
    print(OUT / 'report.html')

if __name__ == '__main__': main()
