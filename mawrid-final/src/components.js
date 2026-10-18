import { resolveSpec } from './unitSpec.js';

/** مصدر موحد للترقيم في المجسم والبطاقات والجدول وملف CSV. */
export const componentData = [
  { id: 1, code: 'C-101', name: 'حجرة التجميع والمصيدة', function: 'تجمع مياه الوضوء ومغاسل اليدين وتحتجز الشوائب الخشنة.', sensor: 'عوامة تشغيل P-101' },
  { id: 2, code: 'P-101', name: 'مضخة الرفع الغاطسة', function: 'ترفع الماء من الحجرة إلى خزان الموازنة عبر عدم رجوع وعزل.', sensor: 'عوامة المستوى' },
  { id: 3, code: 'T-201', name: 'خزان الموازنة', function: 'يوازن التدفق ويتيح قياس جودة الماء الخام قبل التغذية.', sensor: 'مستوى عالٍ/منخفض، pH، موصلية، حرارة، عكارة خام' },
  { id: 4, code: 'P-102', name: 'مضخة التغذية', function: 'تؤمن تدفق وضغط التغذية عبر مراحل الترشيح.', sensor: 'FM-1، P1 ومانومتر' },
  { id: 5, code: 'F-301', name: 'الفلتر الرملي متعدد الوسائط', function: 'يخفض المواد العالقة عبر الأنثراسايت والرمل والحصى.', sensor: 'P2 بعد الفلتر' },
  { id: 6, code: 'F-302', name: 'فلتر الكربون / Biochar النخيل', function: 'مرحلة امتزاز مقترحة بوسط كربوني يُختار ويُثبت بالاختبار.', sensor: 'P3 ونقطتا عينة قبل/بعد' },
  { id: 7, code: 'F-303', name: 'فلتر PP خمسة ميكرون', function: 'يحجز الجسيمات الدقيقة قبل التعقيم بالأشعة فوق البنفسجية.', sensor: 'P4 بعد الفلتر' },
  { id: 8, code: 'UV-401', name: 'مفاعل التعقيم UV', function: 'يعرض الماء للأشعة فوق البنفسجية بجرعة تصميمية يلزم التحقق منها.', sensor: 'شدة UV وحالة ballast' },
  { id: 9, code: 'AT-501', name: 'خلية التحقق', function: 'تراقب جودة الماء النهائي وتصدر إشارة السماح أو الاحتجاز.', sensor: 'عكارة نهائية، pH، موصلية، حرارة' },
  { id: 10, code: 'V-601 / V-602 / FM-2', name: 'صمامات القرار', function: 'تسمح بالري أو تحول الماء إلى إعادة المعالجة/الصرف؛ الري مغلق افتراضيًا.', sensor: 'موضع V-601، موضع V-602، FM-2' },
  { id: 11, code: 'P-103', name: 'مضخة الغسيل وإعادة المعالجة', function: 'تغذي مشعب الغسيل؛ يخرج ماء الغسيل إلى الصرف بفجوة هوائية.', sensor: 'ضغط المشعب وحالة المضخة' },
  { id: 12, code: 'T-701 / P-104', name: 'خزان المياه المعالجة ومضخة الري', function: 'يخزن ماء الري غير الصالح للشرب ويغذي شبكة التنقيط.', sensor: 'مستوى الخزان وحالة P-104' },
  { id: 13, code: 'CP-801', name: 'لوحة التحكم', function: 'تعرض القياسات وتنفذ الإيقاف الآمن وإشارات الإنذار والاتصال.', sensor: 'تجميع إشارات جميع الحساسات' },
  { id: 14, code: 'SK-001', name: 'الهيكل وصينية التسرب', function: 'يحمل المعدات والتوصيلات ويجمع التسربات مع وسائل رفع وتسوية.', sensor: 'فحص تسرب بصري' },
  { id: 15, code: 'DR-901', name: 'خطوط الصرف', function: 'تنقل الفائض والغسيل والتحويل بميل إلى نقطة الصرف الصحي.', sensor: 'فجوة هوائية وفحص بصري' },
];

const m = (v) => Number(v).toLocaleString('en-US', { maximumFractionDigits: 3 });
const cylinder = (d, h) => `قطر ${m(d)} × ارتفاع ${m(h)} م`;

export function getComponents(spec = resolveSpec()) {
  const s = typeof spec === 'string' ? resolveSpec(spec) : spec;
  const c = s.common;
  const sizes = {
    1: `${m(c.chamber.length)} × ${m(c.chamber.width)} × عمق ${m(c.chamber.depth)} م؛ منهل قطر ${m(c.chamber.coverDiameter)} م`,
    2: cylinder(c.submersible.diameter, c.submersible.height),
    3: `${s.balance.capacity} م³ اسمية؛ ${cylinder(s.balance.diameter, s.balance.height)}`,
    4: `طول ${m(c.pump.length)} م؛ قطر محرك ${m(c.pump.motorDiameter)} م`,
    5: `${s.sand.model}: ${cylinder(s.sand.diameter, s.sand.height)}؛ رأس ${m(s.valveHead.height)} م`,
    6: `${s.carbon.model}: ${cylinder(s.carbon.diameter, s.carbon.height)}؛ رأس ${m(s.valveHead.height)} م`,
    7: `20 بوصة؛ ${cylinder(c.pp.diameter, c.pp.height)}؛ 5 ميكرون`,
    8: `قطر ${m(s.uv.diameter)} × طول ${m(s.uv.length)} م`,
    9: `${m(s.detail.analyzer.width)} × ${m(s.detail.analyzer.height)} × ${m(s.detail.analyzer.depth)} م؛ 4 مجسات`,
    10: `${s.pipe.nominal}؛ قطر خارجي ${m(s.pipe.outerDiameter)} م؛ V-601 يعود بنابض`,
    11: `طول ${m(c.pump.length)} م؛ قطر محرك ${m(c.pump.motorDiameter)} م؛ فجوة هوائية ${m(s.detail.fittings.drainAirGap)} م`,
    12: `${s.treated.capacity} م³ اسمية؛ ${m(s.treated.length)} × ${m(s.treated.width)} × ${m(s.treated.height)} م؛ مضخة ${m(c.irrigationPump.length)} × ${m(c.irrigationPump.diameter)} م`,
    13: `${m(c.panel.width)} × ${m(c.panel.height)} × ${m(c.panel.depth)} م؛ مركز عند ${m(c.panel.centerHeight)} م`,
    14: `${m(s.skid.length)} × ${m(s.skid.width)} م؛ أعمدة ${m(c.frame.post)} م؛ ارتفاع ${m(c.frame.height)} م؛ قناة ${m(c.frame.baseChannel)} م`,
    15: `${c.drain.nominal}؛ قطر خارجي ${m(c.drain.outerDiameter)} م؛ ميل تصوري ${m(s.layout.drainSlope * 100)}%`,
  };
  return componentData.map(component => ({ ...component, size: sizes[component.id] }));
}

export function csvFromComponents(spec = resolveSpec()) {
  const quote = value => `"${String(value).replaceAll('"', '""')}"`;
  const rows = [['الرقم', 'الرمز', 'الاسم', 'الوظيفة', 'المقاس'], ...getComponents(spec).map(c => [c.id, c.code, c.name, c.function, c.size])];
  return '\uFEFF' + rows.map(row => row.map(quote).join(',')).join('\r\n');
}
