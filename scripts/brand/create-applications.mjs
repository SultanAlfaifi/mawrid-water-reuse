import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { svgText, logoAt, textWidth } from './shared.mjs';

// All print sizes are trim sizes. Artwork stays inside generous safe margins.
// Paths keep Arabic shaping portable when opened outside a browser.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const bundledModules = process.env.MAWRID_BRAND_NODE_MODULES ?? path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const sharp = createRequire(path.join(bundledModules, 'mawrid-brand-runtime.cjs'))('sharp');
const colors = {
  forest: '#123e35', green: '#39786a', paper: '#f7faf6', mint: '#e9f3ef',
  sage: '#b4cfba', ink: '#243d38', sand: '#d9ccba',
};
const icons = {
  source: '<path d="M4 9h12V6H9V3M16 9v4h4V9h-4M6 16v5h12v-5"/><path d="M18 14c-1 1.4-1.8 2.2-1.8 3.2a1.8 1.8 0 0 0 3.6 0c0-1-.8-1.8-1.8-3.2Z"/>',
  tank: '<path d="M5 5c0-1.2 3.1-2 7-2s7 .8 7 2v14c0 1.2-3.1 2-7 2s-7-.8-7-2V5Z"/><path d="M5 5c0 1.2 3.1 2 7 2s7-.8 7-2M5 13h14M19 17h3"/>',
  filter: '<path d="M8 3h8v3H8V3ZM7 6h10v15H7V6ZM7 10h10M7 16h10M3 8h4M17 19h4"/><path d="M10 12h4M10 14h4"/>',
  carbon: '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><circle cx="9" cy="9" r="1.2"/><circle cx="15" cy="9" r="1.2"/><circle cx="12" cy="13" r="1.2"/><circle cx="8" cy="16" r=".7"/><circle cx="16" cy="16" r=".7"/>',
  disinfection: '<rect x="9" y="3" width="6" height="18" rx="3"/><path d="M4 6l2 2M2 12h4M4 18l2-2M20 6l-2 2M22 12h-4M20 18l-2-2M12 7v10"/>',
  sensor: '<path d="M5 15a8 8 0 1 1 14 0M4 15h16M12 15l4-7M12 18v3M9 21h6"/><path d="M5 8l1.5.8M12 4v2M19 8l-1.5.8"/>',
  route: '<path d="M5 5h10a5 5 0 0 1 0 10H9a4 4 0 0 0 0 8M5 2 2 5l3 3M9 20h10M16 17l3 3-3 3"/><circle cx="10" cy="5" r="1"/><circle cx="12" cy="15" r="1"/>',
  irrigation: '<path d="M3 19h18M5 19v-4h4M12 19V9M12 13c-5 0-6-2-6-5 4 0 6 1 6 5ZM12 10c0-4 3-6 7-6 0 4-2 6-7 6Z"/><path d="M5 11c-.7 1-1.3 1.7-1.3 2.4a1.3 1.3 0 0 0 2.6 0c0-.7-.6-1.4-1.3-2.4Z"/>',
  lab: '<path d="M9 3h6M10 3v7L4.5 19a1.3 1.3 0 0 0 1.1 2h12.8a1.3 1.3 0 0 0 1.1-2L14 10V3M7.5 15h9"/><circle cx="10" cy="18" r=".65"/><circle cx="14" cy="17" r=".65"/>',
  maintenance: '<path d="M14 4a5 5 0 0 0-6.6 6.6L3.5 17a2.5 2.5 0 0 0 3.5 3.5l6.4-3.9A5 5 0 0 0 20 10l-3 3-4-4 3-3-2-2Z"/><circle cx="5.6" cy="18.4" r=".6"/>',
  palm: '<path d="M12 8 10 21h5L12 8ZM12 8C10 3 6 3 3 7M12 8C8 5 5 6 3 10M12 8c2-5 6-5 9-1M12 8c4-3 7-2 9 2M12 8c0-4 2-6 4-6"/><path d="M10.8 15h2.3M10.4 18h3.3"/>',
  evidence: '<path d="M5 3h10l4 4v14H5V3ZM15 3v4h4M8 10h8M8 13h5M8 17l2 2 5-5"/>',
};

const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const rect = (x, y, w, h, fill, extra = '') => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" ${extra}/>`;
const line = (x1, y1, x2, y2, color = colors.sage, sw = 2, extra = '') => `<path d="M${x1} ${y1}L${x2} ${y2}" fill="none" stroke="${color}" stroke-width="${sw}" ${extra}/>`;
const iconAt = (name, x, y, size, color = colors.forest) => `<g transform="translate(${x} ${y}) scale(${size/24})" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${icons[name]}</g>`;

const patternDefs = `<pattern id="screen" x="0" y="0" width="100" height="100" patternUnits="userSpaceOnUse"><g fill="none" stroke="${colors.forest}" stroke-width="1.5"><path d="M50 0 100 50 50 100 0 50ZM0 0H100V100H0ZM25 25H75V75H25ZM50 15 85 50 50 85 15 50Z"/></g></pattern>`;
const screen = (x, y, w, h, opacity = .08) => rect(x, y, w, h, 'url(#screen)', `opacity="${opacity}"`);
const arch = (x, y, w, h) => `M${x} ${y+h}V${y+w/2}A${w/2} ${w/2} 0 0 1 ${x+w} ${y+w/2}V${y+h}Z`;
const route = (x, y, w, h, color = colors.green, sw = 4, opacity = 1) => `<path d="M${x} ${y}H${x+w*.6}Q${x+w} ${y} ${x+w} ${y+h*.45}V${y+h*.6}Q${x+w} ${y+h} ${x+w*.55} ${y+h}H${x+w*.23}Q${x} ${y+h} ${x} ${y+h*.7}V${y+h*.52}" fill="none" stroke="${color}" stroke-width="${sw}" opacity="${opacity}" stroke-linecap="round"/>`;

async function write(relative, markup) {
  const destination = path.join(root, relative);
  await fs.mkdir(path.dirname(destination), { recursive: true });
  await fs.writeFile(destination, markup, 'utf8');
  console.log(relative);
}

function svg(w, h, title, body, physical, definitions = '') {
  const dimensions = physical ? `width="${physical[0]}mm" height="${physical[1]}mm"` : `width="${w}" height="${h}"`;
  return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ${dimensions} viewBox="0 0 ${w} ${h}" role="img" aria-labelledby="title desc"><title id="title">${escape(title)}</title><desc id="desc">مورد — هوية الحرم المشرق. قالب قابل للتحرير. النصوص مسارات لضمان تشكيل العربية؛ الصور تصورات توضيحية. المقاس النهائي دون نزف طباعي.</desc><defs>${patternDefs}${definitions}</defs>${body}</svg>`;
}

// Patterns have transparent backgrounds so they can sit quietly on Paper or Sand.
await write('assets/brand/patterns/architectural-screen.svg', svg(480, 480, 'مشربية هندسية — مورد', screen(0, 0, 480, 480, .12)));
await write('assets/brand/patterns/symbol-route.svg', svg(720, 420, 'مسار المورد المتصل', route(50, 80, 610, 260, colors.forest, 7, .15) + '<circle cx="50" cy="80" r="10" fill="#39786a"/><circle cx="50" cy="215" r="10" fill="#39786a"/>'));
await write('assets/brand/patterns/arc-light.svg', svg(720, 720, 'قوس الضوء — مورد', `<path d="${arch(115, 50, 490, 670).slice(0,-1)}" fill="none" stroke="${colors.sand}" stroke-width="50" opacity=".18"/><path d="${arch(215, 160, 290, 560).slice(0,-1)}" fill="none" stroke="${colors.sage}" stroke-width="30" opacity=".13"/>`));
for (const [name, paths] of Object.entries(icons)) {
  await write(`assets/brand/icons/${name}.svg`, `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" role="img"><title>مورد — ${name}</title><g fill="none" stroke="${colors.forest}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${paths}</g></svg>`);
}

const photoNames = ['campus-ablution', 'campus-concept', 'campus-irrigation'];
// JPEG keeps the original scene portable across desktop SVG / print renderers,
// with bounded file sizes. This is an export conversion, not a new visual.
const photos = Object.fromEntries(await Promise.all(photoNames.map(async name => {
  const bitmap = await sharp(path.join(root, 'assets/images', `${name}.png`))
    .resize({ width: 1400, withoutEnlargement: true }).jpeg({ quality: 88, mozjpeg: true }).toBuffer();
  return [name, `data:image/jpeg;base64,${bitmap.toString('base64')}`];
})));
const photo = (name, x, y, w, h, clip) => `<image x="${x}" y="${y}" width="${w}" height="${h}" href="${photos[name]}" preserveAspectRatio="${name === 'campus-concept' ? 'xMinYMid' : 'xMidYMid'} slice"${clip ? ` clip-path="url(#${clip})"` : ''}/>`;

// Text alignment helpers are completed against the shared brand renderer below.
const T = (text, x, y, size, color = colors.forest, weight = 400, lang = 'ar') => svgText(text, lang === 'ar' ? x-textWidth(text, size, weight, lang) : x, y, size, color, weight, lang);
const EN = (text, x, y, size, color = colors.green, weight = 400) => T(text, x, y, size, color, weight, 'en');
const centered = (text, cx, y, size, color = colors.forest, weight = 400, lang = 'ar') => svgText(text, cx-textWidth(text, size, weight, lang)/2, y, size, color, weight, lang);
const L = (x, y, width, color = colors.forest, variant = 'ar') => logoAt(x, y, width, color, variant);
const labelRule = (label, x, y, w, size = 25) => T(label, x+w, y, size, colors.green) + line(x, y+30, x+w, y+30);
const caption = (x, y, size = 18, color = colors.green) => T('تصور مولّد؛ غير منفذ', x, y, size, color);

// Business card: protected symbol, purposeful whitespace, fillable contact lines.
await write('assets/brand/templates/business-card-front.svg', svg(900, 500, 'بطاقة مورد — الوجه',
  rect(0, 0, 900, 500, colors.paper) + screen(0, 0, 110, 500) +
  route(65, 110, 105, 285, colors.green, 2.8, .32) + L(342.5, 125, 335) +
  centered('مياه الوضوء، موردٌ للري.', 510, 345, 32, colors.forest, 600) +
  centered('Ablution water, a resource for irrigation.', 510, 402, 26, colors.green, 400, 'en'), [90, 50]));
await write('assets/brand/templates/business-card-back.svg', svg(900, 500, 'بطاقة مورد — الظهر',
  rect(0, 0, 900, 500, colors.paper) + rect(0, 0, 14, 500, colors.forest) + L(68, 64, 145) +
  T('الاسم', 820, 126, 40, colors.forest, 600) + T('الدور', 820, 172, 28, colors.green) +
  labelRule('البريد الإلكتروني', 320, 275, 500, 28) + labelRule('رابط المشروع', 320, 380, 500, 28), [90, 50]));

// A4 stationery keeps the usable writing area free of photographs and ornament.
await write('assets/brand/templates/letterhead-a4.svg', svg(2100, 2970, 'ورق مراسلات مورد — A4',
  rect(0, 0, 2100, 2970, colors.paper) + L(1560, 165, 360) + EN('MAWRID', 180, 235, 28, colors.green, 700) +
  line(180, 395, 1920, 395, colors.sage, 2) + labelRule('التاريخ', 180, 470, 335, 28) +
  labelRule('الموضوع', 1230, 470, 690, 28) + screen(0, 2680, 130, 290, .06) +
  line(180, 2740, 1920, 2740, colors.sage, 2) + T('مياه الوضوء، موردٌ للري.', 1920, 2820, 31, colors.forest, 600) +
  EN('Ablution water, a resource for irrigation.', 180, 2870, 28), [210, 297]));

// Report cover: a bright campus framed by the same architectural arch as the mark.
const coverClip = `<clipPath id="cover-arch"><path d="${arch(420, 1230, 1510, 1355)}"/></clipPath>`;
await write('assets/brand/templates/report-cover-a4.svg', svg(2100, 2970, 'غلاف تقرير مورد — A4',
  rect(0, 0, 2100, 2970, colors.paper) + screen(0, 0, 160, 2970, .065) + L(1490, 170, 435) +
  T('مياه الوضوء،', 1920, 635, 112, colors.forest, 700) + T('موردٌ للري.', 1920, 810, 112, colors.forest, 700) +
  T('تقرير المشروع', 1920, 970, 42, colors.green, 600) +
  photo('campus-ablution', 420, 1230, 1510, 1355, 'cover-arch') + caption(1920, 2640, 24) +
  route(190, 1770, 315, 875, colors.green, 4, .42) +
  EN('Ablution water, a resource for irrigation.', 420, 2780, 29), [210, 297], coverClip));

// A3 exhibition poster follows one source and one reuse; no unsupported numbers.
const posterClip = `<clipPath id="poster-arch"><path d="${arch(345, 1120, 2280, 1585)}"/></clipPath>`;
const processCell = (name, title, subtitle, x, y, w) => iconAt(name, x+w/2-62, y, 124) +
  centered(title, x+w/2, y+202, 54, colors.forest, 600) + centered(subtitle, x+w/2, y+282, 34, colors.green);
await write('assets/brand/templates/exhibition-poster-a3.svg', svg(2970, 4200, 'بوستر مورد — A3',
  rect(0, 0, 2970, 4200, colors.paper) + L(2060, 190, 650) + EN('A CAMPUS WATER REUSE CONCEPT', 255, 290, 33) +
  T('مياه الوضوء،', 2710, 670, 160, colors.forest, 700) + T('موردٌ للري.', 2710, 900, 160, colors.forest, 700) +
  photo('campus-concept', 345, 1120, 2280, 1585, 'poster-arch') + caption(2630, 2780, 32) +
  processCell('source', 'مصدر واضح', 'مياه وضوء مفصولة', 2050, 2940, 660) +
  processCell('filter', 'معالجة مقترحة', 'اختبار الجودة أولاً', 1145, 2940, 660) +
  processCell('irrigation', 'استخدام محدد', 'ري المساحات الخضراء', 250, 2940, 660) +
  '<path d="M1960 3012H1850m30-20-30 20 30 20M1060 3012H950m30-20-30 20 30 20" stroke="#39786a" fill="none" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>' +
  line(255, 3440, 2710, 3440, colors.sage, 3) + T('من التصور إلى اختبارٍ يمكن قياسه.', 2710, 3620, 66, colors.forest, 600) +
  T('مواد محلية. مسار مفهوم. قرار ري قائم على التحقق.', 2710, 3730, 41, colors.green) +
  EN('Ablution water, a resource for irrigation.', 255, 3990, 38) + screen(0, 3470, 150, 730, .06), [297, 420], posterClip));

// Social templates keep important words away from crop and avatar zones.
const squareClip = `<clipPath id="social-arch"><path d="${arch(88, 465, 904, 490)}"/></clipPath>`;
await write('assets/brand/templates/social-square.svg', svg(1080, 1080, 'منشور مربع — مورد',
  rect(0, 0, 1080, 1080, colors.paper) + L(736, 64, 260) +
  T('مياه الوضوء،', 994, 242, 71, colors.forest, 700) + T('موردٌ للري.', 994, 345, 71, colors.forest, 700) +
  photo('campus-ablution', 88, 465, 904, 490, 'social-arch') +
  EN('Ablution water, a resource for irrigation.', 88, 1017, 22) + caption(992, 1017, 20), undefined, squareClip));

const storyClip = `<clipPath id="story-arch"><path d="${arch(64, 714, 952, 745)}"/></clipPath>`;
await write('assets/brand/templates/social-story.svg', svg(1080, 1920, 'قصة عمودية — مورد',
  rect(0, 0, 1080, 1920, colors.paper) + L(700, 205, 315) +
  T('مياه الوضوء،', 1014, 470, 83, colors.forest, 700) + T('موردٌ للري.', 1014, 590, 83, colors.forest, 700) +
  photo('campus-irrigation', 64, 714, 952, 745, 'story-arch') + caption(1014, 1512, 22) +
  T('مصدر واضح. استخدام محدد.', 1014, 1640, 43, colors.forest, 600) +
  EN('Ablution water, a resource for irrigation.', 64, 1710, 22) +
  route(72, 190, 170, 420, colors.green, 2.5, .23), undefined, storyClip));

// Research evidence is a reading surface. Institutional marks belong to their owners.
await write('assets/brand/templates/research-card.svg', svg(1080, 1350, 'بطاقة دليل علمي — مورد',
  rect(0, 0, 1080, 1350, colors.paper) + L(720, 72, 285) + iconAt('evidence', 80, 75, 65) +
  T('ماذا يدعم البحث؟', 1000, 297, 68, colors.forest, 600) +
  line(80, 360, 1000, 360, colors.sage, 2) + labelRule('عنوان الدراسة', 80, 425, 920, 28) +
  line(80, 530, 1000, 530) + labelRule('الجهة والسنة', 80, 610, 920, 28) +
  T('النتيجة ذات الصلة بمورد', 1000, 800, 34, colors.forest, 600) +
  line(80, 867, 1000, 867) + line(80, 935, 1000, 935) +
  T('ما الذي لا تثبته الدراسة؟', 1000, 1070, 31, colors.green, 600) + line(80, 1135, 1000, 1135) +
  EN('DOI / URL', 80, 1240, 23) + line(275, 1251, 1000, 1251) + rect(0, 1318, 1080, 32, colors.forest)));

await write('assets/brand/templates/unit-label.svg', svg(1800, 1100, 'ملصق وحدة مورد',
  rect(0, 0, 1800, 1100, colors.paper) + rect(0, 0, 1800, 16, colors.forest) + L(1260, 92, 425) +
  T('نموذج تصوري', 1675, 330, 52, colors.forest, 600) +
  T('إعادة استخدام مياه الوضوء للري', 1675, 422, 44, colors.green) +
  line(115, 500, 1680, 500) + labelRule('رقم الوحدة', 115, 598, 695, 33) + labelRule('الموقع', 985, 598, 695, 33) +
  labelRule('تاريخ الفحص', 115, 738, 695, 33) + labelRule('الحالة', 985, 738, 695, 33) +
  iconAt('irrigation', 115, 900, 80) + T('الري بعد التحقق من الجودة.', 1680, 958, 45, colors.forest, 600), [180, 110]));

await write('assets/brand/templates/sample-label.svg', svg(900, 500, 'ملصق عينة مياه — مورد',
  rect(0, 0, 900, 500, colors.paper) + L(641, 36, 212) + iconAt('lab', 45, 38, 40) +
  T('عينة مياه', 852, 190, 35, colors.forest, 600) +
  labelRule('رقم العينة', 48, 245, 336, 27) + labelRule('المصدر', 480, 245, 372, 27) +
  labelRule('التاريخ', 48, 343, 336, 27) + labelRule('وقت الجمع', 480, 343, 372, 27) +
  T('قبل المعالجة', 817, 445, 25, colors.green) + rect(832, 426, 20, 20, 'none', `stroke="${colors.green}" stroke-width="1.3"`) +
  T('بعد المعالجة', 445, 445, 25, colors.green) + rect(460, 426, 20, 20, 'none', `stroke="${colors.green}" stroke-width="1.3"`), [90, 50]));

const xClip = `<clipPath id="x-arch"><path d="${arch(895, 24, 570, 476)}"/></clipPath>`;
await write('assets/social/x-header.svg', svg(1500, 500, 'غلاف مورد — X',
  rect(0, 0, 1500, 500, colors.paper) + L(567, 68, 262) +
  T('مياه الوضوء،', 830, 233, 56, colors.forest, 700) + T('موردٌ للري.', 830, 312, 56, colors.forest, 700) +
  EN('Ablution water, a resource for irrigation.', 245, 387, 19) +
  photo('campus-ablution', 895, 24, 570, 476, 'x-arch') +
  rect(1210, 454, 234, 34, colors.paper, 'opacity=".92"') + caption(1428, 477, 16) +
  route(40, 40, 130, 235, colors.green, 2.5, .17), undefined, xClip));

const githubClip = `<clipPath id="github-arch"><path d="${arch(658, 44, 565, 552)}"/></clipPath>`;
await write('assets/social/github-social-preview.svg', svg(1280, 640, 'معاينة مستودع مورد',
  rect(0, 0, 1280, 640, colors.paper) + L(293, 73, 300) +
  T('مياه الوضوء،', 594, 286, 59, colors.forest, 700) + T('موردٌ للري.', 594, 372, 59, colors.forest, 700) +
  EN('Ablution water,', 74, 470, 24) + EN('a resource for irrigation.', 74, 508, 24) +
  EN('MAWRID / CAMPUS WATER REUSE', 74, 578, 14, colors.green, 700) +
  photo('campus-concept', 658, 44, 565, 552, 'github-arch') +
  rect(966, 547, 233, 33, colors.paper, 'opacity=".92"') + caption(1186, 570, 16) +
  screen(0, 0, 30, 640, .09), undefined, githubClip));
