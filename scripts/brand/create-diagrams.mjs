import { C, markAt, svgText, svgWrap, textWidth, write } from './shared.mjs';

// Reproducible brand diagrams. All type is shaped and outlined by shared.mjs.
// Solid lines describe water; dashed lines describe control, evidence, or inputs.
const W = 1400;
const center = (text, x, y, size = 22, color = C.ink, weight = 400, lang = 'ar') =>
  svgText(text, x - textWidth(text, size, weight, lang) / 2, y, size, color, weight, lang);
const right = (text, x, y, size = 22, color = C.ink, weight = 400, lang = 'ar') =>
  svgText(text, x - textWidth(text, size, weight, lang), y, size, color, weight, lang);
const rect = (x, y, w, h, fill = C.paper, stroke = C.line, dash = '') =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="16" fill="${fill}" stroke="${stroke}" stroke-width="1.5"${dash ? ` stroke-dasharray="${dash}"` : ''}/>`;
const line = (d, { dashed = false, arrow = true, color = C.green, width = 2.5 } = {}) =>
  `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"${dashed ? ' stroke-dasharray="7 7"' : ''}${arrow ? ' marker-end="url(#arrow)"' : ''}/>`;
const base = (h, title, sub, en) =>
  `<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 0 9 4.5 0 9Z" fill="${C.green}"/></marker></defs>` +
  `<rect width="${W}" height="${h}" fill="${C.paper}"/>` + markAt(54, 40, 46) +
  right(title, 1340, 75, 32, C.forest, 700) + right(sub, 1340, 113, 19, C.muted) +
  svgText(en, 60, 143, 13, C.green, 700, 'en') +
  `<path d="M60 157H1340" fill="none" stroke="${C.line}"/>`;
function icon(kind, x, y, size = 48) {
  const paths = {
    collect: '<rect x="9" y="8" width="30" height="33" rx="4"/><path d="M10 28c7-5 12 4 19 0s7-1 10 0M24 3v7"/>',
    filter: '<rect x="10" y="5" width="28" height="38" rx="5"/><path d="M14 16h20M14 24h20M14 32h20"/>',
    medium: '<rect x="10" y="5" width="28" height="38" rx="5"/><circle cx="19" cy="17" r="3"/><circle cx="30" cy="18" r="3"/><circle cx="24" cy="28" r="3"/><circle cx="17" cy="35" r="2"/><circle cx="31" cy="35" r="2"/>',
    disinfect: '<rect x="12" y="5" width="24" height="38" rx="9"/><path d="M24 11v26M18 15l-3-3M30 15l3-3M18 33l-3 3M30 33l3 3M18 24h-6M30 24h6"/>',
    monitor: '<rect x="5" y="8" width="38" height="26" rx="4"/><path d="M18 42h12M24 34v8M10 25l8-8 7 5 11-10"/>',
    route: '<path d="M40 24H24M24 24V10H8M24 24v14H8M8 10l5-5M8 10l5 5M8 38l5-5M8 38l5 5"/>',
    pressure: '<circle cx="24" cy="23" r="17"/><path d="M24 23l10-9M17 40v4h14v-4M13 17l3 2M24 9v4M35 17l-3 2"/>',
    lab: '<path d="M19 4h10M21 4v15L8 39c-2 3 0 5 3 5h26c3 0 5-2 3-5L27 19V4M15 29h18"/><circle cx="21" cy="35" r="2"/><circle cx="28" cy="39" r="1.5"/>',
    plant: '<path d="M24 44V22M24 32C10 33 6 24 6 13c12 0 18 5 18 19M24 26C38 27 42 18 42 7c-12 0-18 5-18 19M16 44h16"/>',
    palm: '<path d="M24 44V15M24 15C18 6 9 5 4 9M24 15C13 12 6 16 3 23M24 15C18 16 13 24 13 31M24 15C30 6 39 5 44 9M24 15C35 12 42 16 45 23M24 15C30 16 35 24 35 31M20 30h8M20 36h8"/>',
    meter: '<rect x="7" y="8" width="34" height="33" rx="4"/><path d="M12 16h24v12H12ZM16 34h2M23 34h2M30 34h2"/>',
  };
  return `<g transform="translate(${x} ${y}) scale(${size / 48})" fill="none" stroke="${C.green}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths[kind] ?? paths.collect}</g>`;
}
const ruleNote = (text, h) => right(text, 1340, h - 26, 17, C.muted);
function renderTreatment() {
  const h = 680;
  let body = base(h, 'مسار المعالجة والقرار', 'مصدر واحد، واستخدام ري محدد؛ مخطط وظيفي للتصميم المقترح.', 'TREATMENT / OUTLET CONTROL');
  const stages = [
    { x: 1160, title: 'التجميع', detail: 'مياه وضوء مفصولة', kind: 'collect' },
    { x: 950, title: 'الترشيح', detail: 'مواد عالقة', kind: 'filter' },
    { x: 740, title: 'خرطوشة اختبار', detail: 'امتزاز عند الحاجة', kind: 'medium', optional: true },
    { x: 530, title: 'التطهير', detail: 'عملية تحتاج تحققًا', kind: 'disinfect' },
    { x: 320, title: 'المراقبة', detail: 'قراءة شروط التشغيل', kind: 'monitor' },
    { x: 110, title: 'التوجيه', detail: 'متحكم مخرج مستقل', kind: 'route' },
  ];
  stages.forEach((s, i) => {
    const cx = s.x + 90;
    body += rect(s.x, 182, 180, 206, s.optional || i === 4 ? C.mint : C.paper, C.line, s.optional ? '5 5' : '');
    body += svgText(String(i + 1).padStart(2, '0'), s.x + 15, 211, 15, C.green, 700, 'en');
    body += icon(s.kind, cx - 26, 224, 52);
    body += center(s.title, cx, 315, 23, C.forest, 700);
    body += center(s.detail, cx, 352, 17, C.ink);
  });
  // Water flows around the monitoring panel; the panel supplies a control signal.
  body += line('M1157 271H1133') + line('M947 271H923') + line('M737 271H713');
  body += line('M620 392V424H80V310H106');
  body += center('مسار الماء', 613, 450, 16, C.green);
  body += line('M317 267H293', { dashed: true });
  body += center('إشارة', 305, 248, 13, C.green);
  body += line('M200 392V472H990V494');
  body += line('M200 472V494');
  body += rect(620, 498, 720, 98, C.mint);
  body += right('ري المساحات الخضراء بعد التحقق', 1314, 537, 25, C.forest, 700);
  body += right('الاستخدام مقترح؛ يحتاج فحوصًا ومراجعة الموقع والمتطلبات.', 1314, 573, 19, C.ink);
  body += rect(60, 498, 500, 98, C.paper);
  body += right('تحويل عند فشل الشروط', 534, 537, 25, C.forest, 700);
  body += right('إغلاق مسار الاستخدام والتوجيه إلى المسار المحدد.', 534, 573, 18, C.ink);
  body += ruleNote('تصميم مفاهيمي؛ المراقبة ليست مرحلة يمر الماء داخلها، ولا توجد نتائج معالجة فعلية موثقة.', h);
  write('assets/diagrams/treatment-train.svg', svgWrap(W, h, body, 'مورد · مسار المعالجة المقترح وحماية المخرج'));
}
function renderFilterHealth() {
  const h = 720;
  let body = base(h, 'الانسداد وأداء الامتزاز: دليلان مختلفان', 'كل قرار صيانة يحتاج دليلًا مناسبًا؛ الزمن وحده لا يثبت حالة الوسط.', 'FILTER CONDITION / EVIDENCE');
  const panels = [
    { x: 955, w: 385, title: 'حالة التدفق', kind: 'pressure', label: 'قرائن على الانسداد', rows: ['فرق الضغط عبر المرشح', 'ومعدل التدفق'], action: 'الفحص والتنظيف حسب البروتوكول' },
    { x: 515, w: 385, title: 'حالة الامتزاز', kind: 'lab', label: 'أداء المكوّن المستهدف', rows: ['تحليل الماء قبل الوسط وبعده', 'ومقارنة عند شروط متكافئة'], action: 'قرار الاستبدال مبني على النتائج' },
  ];
  panels.forEach(p => {
    const cx = p.x + p.w / 2;
    body += rect(p.x, 186, p.w, 326);
    body += right(p.title, p.x + p.w - 25, 230, 28, C.forest, 700);
    body += icon(p.kind, cx - 27, 255, 54);
    body += center(p.label, cx, 346, 23, C.forest, 600);
    body += center(p.rows[0], cx, 383, 20, C.ink) + center(p.rows[1], cx, 414, 20, C.ink);
    body += rect(p.x + 18, 454, p.w - 36, 40, C.mint, C.mint);
    body += center(p.action, cx, 481, 18, C.forest, 600);
  });
  body += rect(60, 186, 400, 326, C.mint);
  body += right('قرار المخرج', 435, 230, 28, C.forest, 700);
  body += icon('route', 233, 255, 54);
  body += center('حماية مستقلة', 260, 346, 23, C.forest, 600);
  body += center('فشل شرط أو قياس حرج', 260, 383, 20, C.ink);
  body += center('يغلق مسار إعادة الاستخدام', 260, 414, 20, C.ink);
  body += center('ويحوّل الماء إلى المسار المحدد.', 260, 446, 20, C.ink);
  body += center('≠', 927, 355, 34, C.forest, 400, 'en');
  body += rect(60, 552, 1280, 92, C.paper);
  body += right('فرق الضغط والتدفق لا يثبتان قدرة الامتزاز.', 1314, 587, 25, C.forest, 700);
  body += right('الحساسات تراقب التشغيل؛ الفحص المخبري يتحقق من جودة الماء للري.', 1314, 623, 21, C.ink);
  body += ruleNote('تصميم وخطة تحقق؛ التحليلات تدعم الصيانة، ولا تمنح تصريحًا لفتح مسار الري.', h);
  write('assets/diagrams/filter-health.svg', svgWrap(W, h, body, 'مورد · تمييز الانسداد عن أداء الامتزاز ودليل قرار المخرج'));
}
function renderCircularValue() {
  const h = 750;
  let body = base(h, 'القيمة المقترحة وكيف نقيسها', 'مياه وضوء مفصولة، ومعالجة لغرض محدد، ثم قياس الاستخدام والأثر.', 'PROPOSED VALUE / MEASUREMENT');
  const primary = [
    { x: 1040, w: 300, title: 'المصدر', kind: 'collect', rows: ['مياه وضوء مفصولة', 'في منشأة جامعية واحدة'] },
    { x: 555, w: 400, title: 'الوحدة المقترحة', kind: 'filter', rows: ['معالجة وحماية للمخرج', 'وتحقق قبل تطبيق الري'] },
    { x: 60, w: 405, title: 'الاستخدام المستهدف', kind: 'plant', rows: ['ري المساحات الخضراء', 'ضمن نطاق ومتطلبات محددة'] },
  ];
  primary.forEach(p => {
    const cx = p.x + p.w / 2;
    body += rect(p.x, 192, p.w, 252, p.kind === 'filter' ? C.mint : C.paper);
    body += icon(p.kind, cx - 29, 220, 58);
    body += center(p.title, cx, 326, 27, C.forest, 700);
    body += center(p.rows[0], cx, 369, 22, C.ink) + center(p.rows[1], cx, 401, 20, C.ink);
  });
  body += line('M1037 310H960') + line('M552 310H470');
  body += rect(1040, 508, 300, 144, C.paper, C.line, '6 6');
  body += icon('palm', 1263, 526, 44);
  body += right('وسط من مخلفات النخيل', 1245, 558, 19, C.forest, 700);
  body += center('فرضية اختبار عند الحاجة.', 1190, 599, 19, C.ink);
  body += center('يُحذف إن لم يضف قيمة.', 1190, 627, 19, C.ink);
  body += line('M1036 580H902V448', { dashed: true });
  body += center('اختبار المادة', 970, 606, 16, C.green);
  body += rect(60, 508, 405, 144, C.mint);
  body += icon('meter', 380, 529, 44);
  body += right('قياس الاستخدام الفعلي', 360, 559, 24, C.forest, 700);
  body += right('الماء المستخدم والتكلفة والصيانة.', 440, 599, 20, C.ink);
  body += right('الأثر يحتاج بيانات تشغيل وفحوصًا.', 440, 627, 19, C.ink);
  body += line('M263 448V504', { dashed: true });
  body += line('M468 580H655V448', { dashed: true });
  body += center('قياس لتحسين التصميم', 704, 613, 19, C.green);
  body += ruleNote('تصور للترابط؛ الأثر لم يُثبت بعد، ويحتاج قياس الماء والطاقة والمادة والمخلفات.', h);
  write('assets/diagrams/circular-value.svg', svgWrap(W, h, body, 'مورد · المصدر والاستخدام المقترح وفرضية الوسط وقياس القيمة'));
}

renderTreatment();
renderFilterHealth();
renderCircularValue();
console.log('Created three outlined MAWRID brand diagrams.');
