/* Editable MAWRID presentation. Uses the bundled Artifact Tool runtime. */
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const ROOT = path.resolve(__dirname, '../..');
const RUNTIME = process.env.MAWRID_RUNTIME || 'C:/Users/SULTAN1/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const SKILL = process.env.MAWRID_PRESENTATION_SKILL || 'C:/Users/SULTAN1/.codex/plugins/cache/openai-primary-runtime/presentations/26.1007.11041/skills/presentations';
const BUILD = path.join(ROOT, '.qa/brand-presentation');
const OUTPUT = path.join(ROOT, 'assets/brand/templates/mawrid-presentation.pptx');
const COLORS = {
  forest: '#123e35', green: '#39786a', paper: '#f7faf6',
  mint: '#e9f3ef', sage: '#b4cfba', ink: '#243d38', sand: '#d9ccba',
};
const AR = 'IBM Plex Sans Arabic';
const EN = 'Manrope';

async function main() {
  process.env.RUNTIME_NODE_MODULES = path.join(RUNTIME, 'node/node_modules');
  await fs.mkdir(BUILD, { recursive: true });
  await fs.mkdir(path.dirname(OUTPUT), { recursive: true });
  const { Presentation, PresentationFile } = await import(pathToFileURL(path.join(RUNTIME, 'node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs')).href);
  const { FontLibrary } = await import(pathToFileURL(path.join(RUNTIME, 'node/node_modules/@oai/artifact-tool/node_modules/skia-canvas/lib/index.mjs')).href);
  FontLibrary.use(AR, ['plex-arabic-400.ttf', 'plex-arabic-600.ttf', 'plex-arabic-700.ttf'].map(f => path.join(ROOT, 'assets/fonts', f)));
  FontLibrary.use(EN, ['manrope-400.ttf', 'manrope-700.ttf'].map(f => path.join(ROOT, 'assets/fonts', f)));

  const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
  presentation.theme.defaultFont = EN;
  presentation.theme.colorScheme = {
    name: 'MAWRID · Campus Light',
    themeColors: {
      accent1: COLORS.forest, accent2: COLORS.green, accent3: COLORS.sage,
      accent4: COLORS.sand, accent5: COLORS.mint, accent6: COLORS.ink,
      bg1: COLORS.paper, bg2: COLORS.mint, tx1: COLORS.forest, tx2: COLORS.ink,
      dk1: COLORS.ink, dk2: COLORS.forest, lt1: COLORS.paper, lt2: COLORS.mint,
      hlink: COLORS.green, folHlink: COLORS.forest,
    },
  };

  const logo = await fs.readFile(path.join(ROOT, 'assets/brand/logos/mawrid-primary.svg'), 'utf8');
  const mark = await fs.readFile(path.join(ROOT, 'assets/brand/logos/mawrid-mark.svg'), 'utf8');

  function text(slide, value, x, y, w, h, size = 28, options = {}) {
    const shape = slide.shapes.add({
      geometry: 'textbox', name: options.name || value.slice(0, 48),
      position: { left: x, top: y, width: w, height: h },
      fill: 'none', line: { fill: 'none', width: 0 },
    });
    shape.text = value;
    shape.text.style = {
      typeface: options.english ? EN : AR, fontSize: size,
      bold: options.bold || false, color: options.color || COLORS.ink,
      alignment: options.align || 'right', verticalAlignment: 'top',
      autoFit: 'none', wrap: 'square', insets: 0,
    };
    return shape;
  }
  function line(slide, x, y, w, color = COLORS.sage, weight = 1) {
    return slide.shapes.add({ geometry: 'line', position: { left: x, top: y, width: w, height: 0 }, fill: 'none', line: { fill: color, width: weight } });
  }
  function title(slide, value) {
    text(slide, value, 64, 60, 1152, 70, 44, { bold: true, color: COLORS.forest });
  }
  function brand(slide, page) {
    slide.images.add({ svg: mark, alt: 'رمز مورد', fit: 'contain', position: { left: 1178, top: 645, width: 30, height: 42 } });
    text(slide, String(page).padStart(2, '0'), 64, 650, 60, 30, 19, { english: true, align: 'left', color: COLORS.green });
  }
  function makeSlide(page, titleValue) {
    const slide = presentation.slides.add();
    slide.background.fill = COLORS.paper;
    if (titleValue) title(slide, titleValue);
    brand(slide, page);
    return slide;
  }
  async function image(slide, name, x, y, w, h, fit = 'cover') {
    const blob = await fs.readFile(path.join(ROOT, 'assets/images', `${name}.png`));
    slide.images.add({ blob, contentType: 'image/png', alt: `تصور مولّد لمورد في بيئة جامعية: ${name}`, fit, position: { left: x, top: y, width: w, height: h } });
    text(slide, 'صورة مولّدة · تصور تطبيقي غير منفّذ', x, y + h + 10, w, 30, 18, { color: COLORS.green });
  }
  function notes(slide, sources, extra = '') {
    slide.speakerNotes.text = `المصدر: ${sources.join(', ')}\n${extra}\nمورد في مرحلة التصميم المفاهيمي. صور الحرم الجامعي مولّدة ولا توثق موقعًا منفذًا أو شراكة. النصوص والأشكال والجداول قابلة للتعديل.`;
  }

  // 1. Cover: architecture and daylight provide the visual direction.
  {
    const slide = makeSlide(1);
    await image(slide, 'campus-concept', 64, 120, 700, 440, 'contain');
    slide.images.add({ svg: logo, alt: 'شعار مورد', fit: 'contain', position: { left: 878, top: 126, width: 330, height: 100 } });
    text(slide, 'مياه الوضوء،\nمورد للري', 807, 285, 401, 176, 55, { bold: true, color: COLORS.forest });
    text(slide, 'تصميم وحدة محلية لمنشأة جامعية', 807, 491, 401, 86, 26);
    notes(slide, ['docs/project-brief.md', 'assets/images/campus-concept.prompt.md']);
  }

  // 2. One source and a defined customer/use.
  {
    const slide = makeSlide(2, 'المصدر والاحتياج');
    await image(slide, 'campus-ablution', 64, 170, 650, 392);
    text(slide, 'مياه وضوء مفصولة', 780, 176, 428, 56, 33, { bold: true, color: COLORS.forest });
    text(slide, 'نبدأ بموقع جامعي واحد، ونقيس تدفق المصدر وطلب الري القريب.', 780, 249, 428, 145, 29);
    line(slide, 780, 417, 428);
    text(slide, 'العميل الأول', 780, 447, 428, 42, 25, { bold: true, color: COLORS.green });
    text(slide, 'إدارة المرافق الجامعية', 780, 498, 428, 64, 31);
    notes(slide, ['docs/project-brief.md', 'assets/images/campus-ablution.prompt.md'], 'وجود مصدر قابل للفصل وطلب ري مناسب فرضية موقع تحتاج قياسًا. لا كمية هدر أو وفر مثبتة للجامعة.');
  }

  // 3. An editable process sequence, read from right to left.
  {
    const slide = makeSlide(3, 'مسار الماء والقرار');
    text(slide, 'كل مرحلة لها وظيفة محددة ودليل يحتاج التحقق', 64, 145, 1152, 65, 28, { color: COLORS.green });
    const steps = [
      ['الفصل\nوالتجميع', 'مصدر وضوء مستقل'],
      ['الموازنة\nوالترشيح', 'تدفق ومواد عالقة'],
      ['الامتزاز\nعند الحاجة', 'مادة تختبر أمام البدائل'],
      ['التعقيم\nوالتخزين', 'شروط عملية معلنة'],
      ['حماية\nالمخرج', 'تحويل الماء عند الفشل'],
      ['الري\nوالقياس', 'قياس الاستخدام الفعلي'],
    ];
    line(slide, 140, 279, 1000, COLORS.sage, 3);
    steps.forEach(([head, body], i) => {
      const x = 1042 - i * 196;
      text(slide, String(i + 1).padStart(2, '0'), x, 226, 160, 43, 31, { english: true, align: 'center', color: COLORS.green, bold: true });
      text(slide, head, x, 315, 160, 105, 29, { bold: true, color: COLORS.forest, align: 'center' });
      text(slide, body, x - 9, 445, 178, 84, 23, { align: 'center' });
    });
    text(slide, 'الطرق المخبرية تتحقق من جودة الماء للغرض المختار', 64, 563, 1152, 64, 27, { bold: true, color: COLORS.forest });
    notes(slide, ['docs/project-brief.md', 'docs/system-design.md'], 'المخطط يشرح المسار المقترح. الحساسات تراقب شروط التشغيل ولا تثبت وحدها ملاءمة الماء للاستخدام.');
  }

  // 4. Explain the proposed barriers beside the concept image.
  {
    const slide = makeSlide(4, 'طبقات الوحدة المقترحة');
    await image(slide, 'campus-maintenance', 64, 177, 620, 406);
    const layers = [
      ['ترشيح أولي', 'تهيئة التدفق وإزالة المواد العالقة'],
      ['خرطوشة مادة النخيل', 'امتزاز لمكوّن محدد إذا أثبتت الحاجة'],
      ['تعقيم وتخزين', 'إثبات العملية ومراجعة أثر زمن التخزين'],
      ['حماية وقياس', 'مخرج مستقل وسجل ماء استخدم للري'],
    ];
    layers.forEach(([head, body], i) => {
      const y = 166 + i * 113;
      text(slide, head, 735, y, 473, 45, 29, { bold: true, color: COLORS.forest });
      text(slide, body, 735, y + 51, 473, 52, 24);
      if (i < 3) line(slide, 735, y + 103, 473);
    });
    notes(slide, ['docs/project-brief.md', 'docs/system-design.md', 'assets/images/campus-maintenance.prompt.md'], 'رسم الوحدة تصوري. الصورة لا تثبت أبعادًا أو مواصفات هندسية نهائية. خرطوشة النخيل جزء مشروط بنجاح المقارنة.');
  }

  // 5. Native editable table, without fabricated performance figures.
  {
    const slide = makeSlide(5, 'مقارنة مادة النخيل');
    text(slide, 'السؤال: هل تضيف قيمة أمام الحل الأبسط والكربون التجاري؟', 64, 142, 1152, 80, 29, { color: COLORS.green });
    const values = [
      ['ما نقيسه', 'البدائل في المقارنة', 'عنصر القرار'],
      ['إزالة مكوّن محدد بطرق مخبرية', 'بدون امتزاز، نخيل، كربون تجاري', 'الأداء'],
      ['المركبات والدقائق التي قد تطلقها المادة', 'عينات وضوابط بشروط متكافئة', 'أثر المادة في الماء'],
      ['فقد الضغط ومدة الخدمة', 'تدفق وحجم سرير معلنان', 'التشغيل'],
      ['كلفة التحضير والاستبدال والفحص', 'عروض أسعار وقياسات فعلية', 'التكلفة'],
    ];
    const table = slide.tables.add({ rows: values.length, columns: 3, left: 64, top: 239, width: 1152, height: 329, columnWidths: [470, 440, 242], values });
    table.styleOptions = { headerRow: false, bandedRows: false };
    table.borders.assign({ style: 'solid', fill: COLORS.sage, width: 1 });
    table.cells.block({ row: 0, column: 0, rowCount: 5, columnCount: 3 }).assign({
      fill: COLORS.paper, textStyle: { typeface: AR, fontSize: 23, alignment: 'right', color: COLORS.ink },
      margins: { left: 14, right: 16, top: 12, bottom: 12 }, anchor: 'center',
    });
    table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 3 }).assign({ fill: COLORS.mint, textStyle: { typeface: AR, fontSize: 24, alignment: 'right', color: COLORS.forest, bold: true } });
    text(slide, 'قرار الإضافة يتبع نتيجة الاختبار', 64, 593, 1152, 50, 26, { bold: true, color: COLORS.forest });
    notes(slide, ['docs/project-brief.md', 'docs/innovation.md', 'docs/validation.md'], 'لا نتائج أداء أو سعر مثبتة لمادة مورد. المحلية والاستدامة والتكلفة المنخفضة فرضيات تنتظر الدليل.');
  }

  // 6. State current evidence and the missing evidence on one flat canvas.
  {
    const slide = makeSlide(6, 'الأدلة الحالية وما يلزم');
    text(slide, 'موجود في المشروع', 731, 161, 477, 51, 31, { bold: true, color: COLORS.green });
    text(slide, 'مطلوب للتحقق', 64, 161, 526, 51, 31, { bold: true, color: COLORS.green });
    const current = ['نطاق موثّق ومصدر واستخدام محددان', 'تصميم مفاهيمي ومستكشف تعليمي', 'قواعد تشغيل وسيناريوهات محاكاة', 'مراجع علمية وخطة اختبار'];
    const needed = ['قياسات المصدر وطلب الري في الموقع', 'نتائج مخبرية وبيانات خام قابلة للفحص', 'اختبارات صمام وطاقة على منصة مادية', 'مراجعة موقع وتكلفة واهتمام عميل'];
    current.forEach((v, i) => { text(slide, v, 731, 259 + i * 76, 477, 57, 27); if (i < 3) line(slide, 731, 318 + i * 76, 477); });
    needed.forEach((v, i) => { text(slide, v, 64, 259 + i * 76, 526, 57, 27); if (i < 3) line(slide, 64, 318 + i * 76, 526); });
    text(slide, 'الحالة الحالية: تصميم مفاهيمي وخطة تحقق', 64, 583, 1152, 53, 26, { bold: true, color: COLORS.forest });
    notes(slide, ['docs/evidence-register.md', 'docs/project-brief.md'], 'لا سجل نتائج معالجة فعلية لمورد أو شراكة وموافقة موقع مؤكدة في المستودع. الدراسات الخارجية ليست نتائج لمورد.');
  }

  // 7. A staged test plan with explicit transition evidence.
  {
    const slide = makeSlide(7, 'خارطة الاختبار المقترح');
    const phases = [
      ['توصيف الموقع', 'قياس المصدر والطلب، ورسم فصل التصريف'],
      ['اختبار مخبري', 'مقارنة المعالجة وتوثيق جودة الماء والمادة'],
      ['منصة تحكم مادية', 'اختبارات الأعطال وتسجيل استجابة المخرج'],
      ['قرار تجربة محدودة', 'مراجعات وموافقات وجدوى تشغيل وتكلفة'],
    ];
    phases.forEach(([head, body], i) => {
      const y = 165 + i * 112;
      text(slide, String(i + 1).padStart(2, '0'), 1128, y, 80, 56, 37, { english: true, bold: true, color: COLORS.green });
      text(slide, head, 732, y + 1, 349, 53, 31, { bold: true, color: COLORS.forest });
      text(slide, body, 64, y + 5, 594, 64, 27);
      if (i < 3) line(slide, 64, y + 89, 1144);
    });
    text(slide, 'لكل انتقال دليل معلن قبل بدء التجربة', 64, 620, 1152, 40, 25, { color: COLORS.green });
    notes(slide, ['docs/validation.md', 'docs/project-brief.md', 'docs/roadmap.md'], 'الخطوات مقترحة ولم تكتمل. لا ري ميداني في الدراسة المخبرية الأولى. تحدد المراجعة المتطلبات والمؤشرات المنطبقة قبل التطبيق.');
  }

  // 8. Close with the defined use and next concrete evidence.
  {
    const slide = makeSlide(8);
    await image(slide, 'campus-irrigation', 64, 130, 688, 423);
    slide.images.add({ svg: logo, alt: 'شعار مورد', fit: 'contain', position: { left: 870, top: 121, width: 338, height: 104 } });
    text(slide, 'استخدام واضح\nوأثر قابل للقياس', 801, 292, 407, 162, 46, { bold: true, color: COLORS.forest });
    text(slide, 'الخطوة التالية: توصيف موقع جامعي صالح للاختبار', 801, 494, 407, 103, 27);
    notes(slide, ['docs/project-brief.md', 'assets/images/campus-irrigation.prompt.md'], 'إضافة اسم الفريق ووسيلة التواصل تكون في نسخة العرض الخاصة بالفريق. لا ادعاء وفر ميداني قبل القياس.');
  }

  for (const [i, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(i + 1).padStart(2, '0')}`;
    const png = await presentation.export({ slide, format: 'png', scale: 1 });
    await fs.writeFile(path.join(BUILD, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
    const layout = await slide.export({ format: 'layout' });
    await fs.writeFile(path.join(BUILD, `${stem}.layout.json`), await layout.text());
  }
  const candidatePath = path.join(BUILD, 'candidate.pptx');
  await (await PresentationFile.exportPptx(presentation)).save(candidatePath);
  // Artifact Tool exports alignment but omits DrawingML paragraph direction.
  // Preserve logical Arabic text and make the direction explicit in the native
  // presentation, rather than reversing words to work around its PNG renderer.
  const JSZip = require(path.join(RUNTIME, 'node/node_modules/jszip'));
  const nativePackage = await JSZip.loadAsync(await fs.readFile(candidatePath));
  let rtlParagraphCount = 0;
  for (const name of Object.keys(nativePackage.files)) {
    if (!/^ppt\/(slides|notesSlides)\/[^/]+\.xml$/.test(name)) continue;
    const xml = await nativePackage.file(name).async('string');
    const updated = xml.replace(/<a:p\b[^>]*>.*?<\/a:p>/gs, paragraph => {
      const decoded = paragraph.replace(/&#(?:x([\da-f]+)|(\d+));/gi, (entity, hex, decimal) => String.fromCodePoint(parseInt(hex || decimal, hex ? 16 : 10)));
      if (!/\p{Script=Arabic}/u.test(decoded)) return paragraph;
      rtlParagraphCount++;
      let output = paragraph.replace(/<a:pPr\b([^>]*?)(\/?)>/, (tag, attrs, slash) => `<a:pPr${attrs.replace(/\srtl="[^"]*"/g, '')} rtl="1"${slash}>`);
      if (output === paragraph && !/<a:pPr\b/.test(paragraph)) output = paragraph.replace(/(<a:p\b[^>]*>)/, '$1<a:pPr rtl="1"/>');
      return output.replace(/<a:(rPr|defRPr|endParaRPr)\b([^>]*?)(\/?)>/g, (tag, kind, attrs, slash) => `<a:${kind}${attrs.replace(/\slang="[^"]*"/g, '')} lang="ar-SA"${slash}>`);
    });
    nativePackage.file(name, updated);
  }
  await fs.writeFile(candidatePath, await nativePackage.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }));
  await fs.writeFile(path.join(BUILD, 'native-rtl.json'), JSON.stringify({ rtlParagraphCount, renderingNote: 'Artifact Tool PNG previews do not implement Arabic word direction faithfully. Native PPTX paragraphs retain logical text and have DrawingML rtl=1 and ar-SA language.' }, null, 2));
  const { finalizePresentation } = await import(pathToFileURL(path.join(SKILL, 'container_tools/artifact_tool_utils.mjs')).href);
  await fs.mkdir(path.join(BUILD, 'validated'), { recursive: true });
  const runId = Date.now();
  const validatedPath = path.join(BUILD, 'validated', `validated-${runId}.pptx`);
  const validation = await finalizePresentation({
    explicitTotalSlideCount: 8, requiredNativeTableOwnerSlides: [5], requiredNativeChartOwnerSlides: [],
    workspaceDir: ROOT, candidatePath, finalPath: validatedPath,
    pythonExecutable: path.join(RUNTIME, 'python/python.exe'),
    integrityValidatorPath: path.join(SKILL, 'container_tools/inspect_presentation_package_integrity.py'),
    layoutValidatorPath: path.join(SKILL, 'container_tools/inspect_presentation_layout_geometry.py'),
    layoutArgs: ['--expected-slide-size-emu', '12192000,6858000', '--validate-heading-fit', '--require-native-table-slide', '5'],
    fontPolicy: { basis: 'design', families: [AR, EN], scriptFonts: { cs: AR } },
    verifyArtifactToolImport: true,
    receiptPath: path.join(BUILD, `validation-${runId}.json`),
  });
  await fs.copyFile(validatedPath, OUTPUT);
  console.log(JSON.stringify({ output: OUTPUT, slides: 8, previews: BUILD, validation }, null, 2));
}

main().catch(error => { console.error(error); process.exitCode = 1; });
