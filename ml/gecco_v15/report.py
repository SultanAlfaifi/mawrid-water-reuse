"""Build a small, evidence-linked Arabic report after the independent audit."""
from __future__ import annotations
import argparse
import html
import json
from pathlib import Path
from ml.gecco_v15.development import ROOT, parent, sha, write, now


def build(run, out):
    r=json.loads((run/'results.json').read_text()); audit=json.loads((run/'audit.json').read_text())
    if r['complete_cases'] != 19 or audit.get('passed') is not True:
        raise ValueError('Completed19 cases and independent audit PASS required')
    out.mkdir(parents=True,exist_ok=False)
    versions={}
    for v in ('v8','v9','v10','v11','v12','v13','v14'):
        old=json.loads((parent(v)/'results.json').read_text())
        versions[v.upper()]=old['summary']['v6_vs_v7']['candidate']
    versions={'V6':r['summary']['v6_vs_v7']['baseline'],**versions,'V15':r['summary']['v6_vs_v7']['candidate']}
    rows=''.join('<tr><th>'+v+'</th><td>'+str(m['confirmed_events'])+'/'+str(m['true_events'])+'</td><td>'+str(m['false_positive_runs'])+'</td><td>'+str(round(m['fp_duration_seconds']/60))+'</td><td>'+f"{100*m['f1_observed_points']:.2f}%"+'</td></tr>' for v,m in versions.items())
    periods=[]; total_union=kept_union=0
    for p in r['periods']:
        a=p['comparisons']['v6_vs_v7']; b=p['v8_comparison']
        union=set(a['baseline']['confirmed_event_ids'])|set(b['baseline']['confirmed_event_ids'])
        kept=set(a['candidate']['confirmed_event_ids']); total_union+=len(union); kept_union+=len(union&kept)
        lost6=a['lost_baseline_event_ids']; lost8=b['lost_baseline_event_ids']
        badge='اجتازت المعايرة المشروطة' if p['accepted_calibration'] else 'غير مدعومة · عودة V8'
        periods.append('<tr><th dir="ltr">'+html.escape(p['case'])+'</th><td>'+str(a['baseline']['confirmed_events'])+'/'+str(b['baseline']['confirmed_events'])+'/'+str(a['candidate']['confirmed_events'])+'</td><td>'+str(a['baseline']['false_positive_runs'])+'/'+str(b['baseline']['false_positive_runs'])+'/'+str(a['candidate']['false_positive_runs'])+'</td><td>'+html.escape(str(lost6))+' / '+html.escape(str(lost8))+'</td><td>'+badge+'</td></tr>')
    goal=bool(r['quality_checks_before_independent_audit_passed'] and audit['passed'])
    status={'created_at_utc':now(),'phase':'quality_goal_passed_development_only' if goal else 'current_retention_goal_failed',
        'candidate':'V15','complete_cases':19,'audit_passed':True,'quality_goal_passed':goal,
        'accepted_calibration_cases':r['accepted_calibration_cases'],'retained_v6_v8_union':kept_union,'v6_v8_union':total_union,
        'no_model_fit':True,'fresh_validation':False,'new_sensor_replay':False,'model_promoted':False,
        'results_sha256':sha(run/'results.json'),'audit_sha256':sha(run/'audit.json'),
        'protocol_sha256':sha(ROOT/'output/ml/gecco-v15-design/protocol.json')}
    write(out/'status.json',status)
    m=versions['V15']; state='اجتاز شرط التطوير؛ لم يُرقَّ للتشغيل' if goal else 'لم يحقق شرط الاحتفاظ بالأحداث وخفض الإنذارات'
    content=f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد · نتيجة V15</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#eef3f4;color:#102c35;font:17px/1.9 system-ui,sans-serif}}main{{max-width:1280px;margin:auto;padding:40px 24px}}header{{background:#103b45;color:white;padding:32px;border-radius:24px}}h1{{font-size:38px;margin:6px 0}}h2{{font-size:25px;margin-top:32px}}p{{max-width:1050px}}.tag{{color:#bfece3}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:22px 0}}.card{{background:white;padding:20px;border-radius:16px;border:1px solid #cfdee1}}strong.big{{display:block;font-size:32px;color:#0a706a}}.notice{{background:#fff0da;border-right:5px solid #ae6812;padding:18px;border-radius:10px}}.table{{overflow:auto;background:white;border-radius:16px}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{text-align:right;padding:12px 16px;border-bottom:1px solid #e4ecee}}thead{{background:#dceaea}}tbody tr:last-child{{font-weight:700}}a{{color:#08675f}}code{{direction:ltr;display:inline-block}}footer{{font-size:14px;color:#49636b;margin-top:32px}}li{{margin:8px 0}}</style>
<main><header><span class="tag">مورد · تجربة تطوير على درجات محفوظة ومُدقَّقة</span><h1>V15: إصلاح هدف سياسة الإنذار</h1><p>{state}. اكتملت الفترات الـ19؛ نجاح التدقيق الحسابي لا يعني نجاح جودة النموذج.</p></header>
<div class="cards"><div class="card">الأحداث المؤكدة<strong class="big">{m['confirmed_events']} / {m['true_events']}</strong></div><div class="card">الإنذارات الكاذبة<strong class="big">{m['false_positive_runs']}</strong></div><div class="card">دقائق الإنذار الكاذب<strong class="big">{m['fp_duration_seconds']/60:g}</strong></div><div class="card">الاحتفاظ باتحاد V6 وV8<strong class="big">{kept_union} / {total_union}</strong></div></div>
<p class="notice">اتحاد {total_union} هو مجموعة أحداث سبق كشفها للمقارنة، والمقام الأصلي للاستدعاء هو {m['true_events']}. كل المصادر والفترات مكشوفة من التجارب السابقة؛ هذا تحقق زمني أثناء التطوير، وليس تحققًا خارجيًا جديدًا أو إثباتًا لسلامة ماء مورد.</p>
<h2>ما الذي تغير؟</h2><p>ثُبّت نموذج V14 ودرجاته دون إعادة تدريب. تستخدم السياسة V8 مرجعًا، مع تأكيد محدود واستعادة بعض نبضات V6 خلال 120 ثانية. أصبح القرار النهائي ملزمًا بحفظ معرّفات أحداث المرجعين وتوقيتاتهما وتكاليف الإنذار الكاذب في المعايرة. دعم الاستعادة يُحسب من بدايات أحداث مؤكدة فعلًا مقارنة بالقرار الأولي، لا من دقائق إضافية داخل حدث مكتشف.</p>
<p>اختيرت سياسة واحدة من أول كتلتين ماضيتين ضمن شبكة ثابتة لا تتجاوز 64 خيارًا. الكتلتان اللاحقتان والفحص المجمع يقبلانها أو يرفضانها فقط. جُمّدت سياسات الفترات الـ19 قبل فتح أي مصفوفة اختبار لهذه التجربة. اجتازت المعايرة المشروطة {r['accepted_calibration_cases']} من 19؛ تعني «عودة V8» عدم دعم تعديل السياسة، ولا تضمن حفظ اتحاد الأحداث.</p>
<p>استعمل V6 وV8 الكتل الأربع في معايرتهما الأصلية؛ لذلك التصديق الجديد مشروط بهذين المرجعين، وليس اختبارًا مستقلًا للمنظومة كلها. التدقيق الحالي يعيد سياسة الإنذار والقياسات على الدرجات المحفوظة؛ تدقيق الحساسات والنماذج موروث من V8 وV14، ولم يُعد هنا.</p>
<h2>المقارنة على المحاور نفسها</h2><div class="table"><table><thead><tr><th>الإصدار</th><th>الأحداث المؤكدة</th><th>الإنذارات الكاذبة</th><th>دقائق الإنذار الكاذب</th><th>F1 للنقاط المتاحة</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>كل الفترات؛ بما فيها الإخفاقات</h2><p>ترتيب الأرقام: V6 / V8 / V15. الأعداد وحدها لا تثبت الاحتفاظ بهوية الحدث أو احترام مهلة التأكيد.</p><div class="table"><table><thead><tr><th>الفترة</th><th>كشف الأحداث</th><th>الإنذارات الكاذبة</th><th>الأحداث المفقودة أمام V6 / V8</th><th>دعم المعايرة</th></tr></thead><tbody>{''.join(periods)}</tbody></table></div>
<h2>أدلة قابلة للمراجعة</h2><ul><li><a href="../gecco-v15-design/protocol.json">المواصفات المثبتة قبل التجربة</a></li><li><a href="../gecco-v15-design/preflight.json">الاختبارات الاصطناعية قبل التشغيل</a></li><li><a href="../gecco-v15-development/run_01/plan.json">تثبيت المدخلات والكود</a></li><li><a href="../gecco-v15-development/run_01/policies-frozen.json">تجميد جميع السياسات قبل الاختبار</a></li><li><a href="../gecco-v15-development/run_01/calibration-audit.json">التدقيق المستقل للمعايرة</a></li><li><a href="../gecco-v15-development/run_01/results.json">النتائج الكاملة</a></li><li><a href="../gecco-v15-development/run_01/audit.json">تدقيق الاختبار المستقل</a></li><li><a href="status.json">الحالة القابلة للقراءة آليًا</a></li><li><a href="../gecco-v14/report.html">تقرير V14 المحفوظ</a></li></ul>
<footer>لا ترقية إلى العرض التشغيلي أو الصمام. العرض الافتراضي الحالي مستقل عن V15. لم تُقَس سلامة الماء أو دقة تشخيص الأعطال الخمسة أو أداء Raspberry Pi بهذه التجربة. أُنشئ التقرير من النتائج الفعلية بتاريخ {html.escape(now())}.</footer></main></html>'''
    (out/'report.html').write_text(content,encoding='utf-8')
    return status


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.run.resolve(),a.output.resolve()),ensure_ascii=False))
