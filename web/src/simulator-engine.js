import { evaluateReuse } from './reuse-logic.js';

// SIMULATED: the complete list below is also rendered in the simulator's source
// register. None of these coefficients is a measured MAWRID treatment result.
export const MODEL_ASSUMPTIONS = [
  { id: 'time', title: 'الزمن والمولد', values: '7 أيام؛ خطوة 5 دقائق؛ 288 خطوة/يوم؛ بذرة 350؛ مولّد Mulberry32 ومعاملاته البرمجية القياسية؛ أسبوع افتراضي يبدأ الأحد.', note: 'افتراض توضيحي. الفترات والمحاولات الرقمية اختيارات للعرض وليست أداءً مقاسًا.' },
  { id: 'inflow', title: 'الدخول وجدول الصلاة', values: '2500 شخص/يوم؛ 4 لتر/وضوء؛ 0.5 غسلة يد × 1 لتر؛ استعادة 80%؛ الجمعة ×1.8؛ الصلاة 05:10، 12:15، 15:35، 18:00، 19:30؛ ذروة غاوسية قبل الصلاة بـ10 دقائق بعرض 8 دقائق، مقصوصة ضمن 20 دقيقة قبلها؛ ضوضاء تدفق ±5%. الجامعة: الظهر والعصر من الأحد إلى الخميس. الحرم: خلفية مستمرة بوزن 0.012 مع ذروة بوزن 0.08.', note: 'افتراضات توزيع وأوقات مكة تقريبية قابلة للتعديل؛ مقدار الوضوء في نطاق Zaied. يُطبَّع توزيع كل يوم ليطابق الحجم اليومي تمامًا.' },
  { id: 'raw', title: 'جودة الخام', values: 'عكارة 10–40 NTU؛ TSS ‏15–60 mg/L؛ COD ‏40–150 mg/L؛ pH ‏7–8.5؛ EC ‏400–1200 µS/cm؛ E. coli بتوزيع لوغاريتمي 10¹–10³ لكل 100 mL؛ باقي المتغيرات بتوزيع منتظم.', note: 'افتراض توضيحي يحتاج تحققًا مخبريًا؛ ليست عينات من موقع مورد.' },
  { id: 'hydraulics', title: 'الخزانات والهيدروليكا', values: 'موازنة 5000 لتر؛ معالج 3000 لتر؛ معالجة 20 م³/يوم؛ سحب ري نهاري (06–22) ×1.4، وليلي ×0.35 من سعة المعالجة؛ لا تغذية بماء شرب؛ مسار ري مضخوخ بلا جريان بالجاذبية؛ حد التخزين 360 دقيقة في الخزانين، مع صرف الماء عند تجاوزه؛ عمر الخليط يساوي أكبر عمر لدفعاته؛ نمو ميكروبي exp(0.001 × الدقائق)؛ خلط حجمي كامل؛ حتى 3 محاولات إعادة معالجة.', note: 'افتراض توضيحي. خلط pH متوسط حجمي حسابي وليس نموذج كيمياء أو قلوية. توقف المضخة يمنع التدفق حتى مع صمام عالق؛ يجب اختبار غياب الجاذبية والسيفون والضغط المتبقي واستقلال الحواجز ماديًا. لا يمثل صفر المؤشر ضمانًا ماديًا.' },
  { id: 'removals', title: 'كفاءات الإزالة الافتراضية', values: 'ترتيب النسب: العكارة / TSS / COD. رملي: 70% / 75% / 15%؛ كربون: 25% / 25% / 55%؛ PP: ‏80% / 90% / 5%. نطاقات الضبط بالترتيب نفسه: رملي 40–85% / 50–90% / 5–30%؛ كربون 10–40% / 10–50% / 20–80%؛ PP: ‏60–95% / 70–98% / 0–10%. زيادة فرق الضغط فوق الأساس تخفض كفاءة الرمل بمعامل 0.12/بار، بحد زيادة 0.8 بار؛ إزالة COD بالكربون = الكفاءة × (1 − التشبع).', note: 'افتراضات توضيحية؛ نسب الإزالة لا تخص فحم نخيل مختبرًا. لا تعدل المراحل pH ولا تزيل الأملاح، ولا يُفترض تعقيم بالترشيح.' },
  { id: 'media', title: 'التحميل والغسيل والاختراق', values: 'فرق ضغط ابتدائي: رملي 0.15، كربون 0.1، PP ‏0.08 بار؛ التحميل لكل غرام TSS محجوز: الرمل 0.0002، والكربون 0.0003، وPP ‏0.00012 بار. الغسيل الآلي للرمل وحده عند 0.75 بار، ويستهلك 120 لترًا كاملة؛ يحتجز الماء وينتظر إن لم تتوفر كمية الغسيل. بلاغ بعد 3 غسلات خلال 72 خطوة دون تحسن؛ سعة امتزاز 10000 غ COD؛ تشبع ابتدائي 0؛ إنذار عند Cout/Cin ≥ 0.85 مع Cin > 1 mg/L.', note: 'افتراضات توضيحية. ضغط الكربون وPP يزيد بالتحميل ولا يُغسلان آليًا؛ الاستعادة الافتراضية تعيدهما إلى 0.1 و0.08 بار. فرق الضغط لا يقيس التشبع؛ إنذار الكربون يعتمد مؤشري COD افتراضيين بدقة ±2%. الغسيل الثابت المقارن يستحق كل 24 ساعة وينتظر تشغيل المضخات ووجود ماء، ثم يعد الأصغر من 120 لترًا والمخزون الحالي؛ عداد افتراضي لا محاكاة خزان مستقلة أو وفر مقاس.' },
  { id: 'uv', title: 'نموذج UV والميكروبات', values: 'الجرعة = 60 mJ/cm² × (الشدة/100) × exp(−0.025 × العكارة) × (تدفق التصميم/الفعلي)، بحد علوي 120؛ الخفض اللوغاريتمي = min(6، الجرعة/10)؛ ضعف طبيعي 0.003 نقطة مئوية/ساعة؛ حد جرعة 40، وخفض مرجعي 4؛ E. coli ≤ 1 لكل 100 mL؛ الشدة الافتراضية 100% وحدها 70%. الحد الميكروبي النموذجي يبدأ من 100000 لكل 100 mL لجميع الوارد، وينمو بمعامل 0.001/دقيقة ثم يتناقص بالجرعة المقاسة المحافظة.', note: 'علاقة جرعة وخفض غير معايرة، ولا تثبت التعقيم. الحد الميكروبي مستقل عن الحقيقة النهائية ويجب أن يكون ≤1 للسماح. يحتفظ سجل الدفعات بأدنى شدة مقاسة ناقص 0.4 نقطة وبأقل جرعة؛ لا يعاد تأهيل الماء القديم بمجرد استعادة المصباح. لا يُصفَّر السجل إلا بصرف الدفعة أو إعادة معالجتها كاملة. جميع الحدود افتراضات تشغيل وليست قياسات أو ادعاء امتثال.' },
  { id: 'sensors', title: 'الحساسات وهوامش القرار', values: 'ضوضاء محدودة: مؤشرا COD الداخل والخارج ±2%؛ EC الدخول ±2%؛ العكارة ±0.1 NTU، وpH ‏±0.02، وEC والتدفق ±2%، والشدة ±0.2 نقطة؛ حساس الخام ±0.1 NTU و±0.02 pH؛ هامش القرار 0.3 NTU و0.2 pH و0.2 نقطة UV؛ حد الثقة 70/100؛ حساس رخيص بمدى 0–1000 NTU ودقة ±5% FS = ±50 NTU للعرض فقط.', note: 'جميع دقات نقطة القرار المنخفضة المدى افتراضات توضيحية تتطلب اختيار حساس ومعايرة. حساسات SEN0710 ذات الخطأ الكبير لا تدخل قرار الصمام.' },
  { id: 'ai', title: 'الثقة والتوقع والصيانة', values: 'باقٍ متحرك EWMA بمعامل 0.35؛ الثقة: 100 − 140 × باقي العكارة، و100 − 220 × باقي pH؛ ثقة EC: ‏100 − 700 × الفرق النسبي؛ ثقة التدفق: 100 − 400 × الفرق النسبي؛ حد أدنى 0؛ تجمد 6 قراءات مع تغير متوقع >0.08؛ توقع اليوم الأول 90% من الحجم الاسمي، ثم EWMA يومي 0.35؛ WAPE = مجموع الخطأ المطلق/مجموع الدخول؛ اتجاه الضغط من آخر 72 قراءة؛ ضعف UV من معدل التقادم المفترض. عمر الكربون المتبقي = (كتلة الاختراق − كتلة COD الممتزة المرصودة)/معدل الامتزاز المرصود غ/يوم؛ كتلة الاختراق = 10000 × max(0، 1 − 0.15/كفاءة إزالة COD بالكربون).', note: 'خوارزميات توضيحية قابلة للتفسير؛ لا تقدير محدود للغسيل عند ميل ضغط ≤0 أو للكربون عند معدل امتزاز ≤0؛ عمر الكربون صفر عند الاختراق المرصود، ولا يُقدَّر من الضغط. الملاحظ يستخدم قياس الدخول وخريطة معالجة مفترضة دون الحقيقة النهائية؛ مرجع EC قياس مستقل ±2% ومرجع التدفق حجم المضخة المفترض. لا تعلم آلي مدرب أو نموذج لغوي خارجي أو حق في فتح الصمام.' },
  { id: 'faults', title: 'شدة الأعطال المحقونة', values: 'انحراف عكارة −0.012 NTU/دقيقة؛ اتساخ pH بانحراف −0.003/دقيقة بحد −2؛ ضعف UV ‏−0.12 نقطة/دقيقة؛ انسداد +0.7 بار عند الحقن ثم +0.11 بار/خطوة؛ دفعة تلوث 120 دقيقة: عكارة 250–450 NTU، وTSS ‏300–500 وCOD ‏500–900 mg/L، وpH ‏9.7–10.1، وE. coli ‏10⁴–10⁵ لكل 100 mL؛ تشبع كربون 98%؛ فقد الحساس وتجمّده وعطل UV اختبارات إضافية؛ فشل الصمام يعطي تغذية راجعة مخالفة ويوقف المضخات فورًا.', note: 'كل شدات الأعطال افتراض توضيحي. التلوث والشدة ليست بيانات حادثة حقيقية. العينات العشوائية ثابتة البذرة ومشتركة مع الترشيح البسيط.' },
  { id: 'safety', title: 'تعريف مؤشر الماء غير المطابق', values: 'تفحص الحقيقة المستقلة بعد القرار: العكارة ≤ الحد، وpH بين الحدين، وE. coli ≤ 1 لكل 100 mL، والجرعة ≥40 والشدة ≥ الحد. عدد المرات = خطوات 5 دقائق حدث فيها تصريف غير مطابق، مع حجم مستقل. الترشيح البسيط = رمل فقط بالكفاءات نفسها؛ بلا UV أو حساسات أو احتجاز؛ يتوقف عند انقطاع الكهرباء.', note: 'فاحص التدقيق لا يدخل evaluateReuse ولا يغيّر المسار. الإتاحة: تصريح القواعد/خطوات وجود وارد أو ماء بأي خزان؛ الزمن ضمن الحدود: خطوات فاحص الحقيقة الناجحة/خطوات وجود ماء بالمعالج. غياب الماء لا يعد جودة مطابقة. بلاغ معايرة غير محسوم يبقي المعايرة غير صالحة حتى الاستعادة الافتراضية. صفر المحاكاة محدود بالنموذج والأعطال المعلنة؛ لا تُحاكى كفاءة Hydraloop.' },
  { id: 'economics', title: 'اقتصاد السيناريو', values: 'شريط تعرفة 6–9 ريال/م³ يحتاج تحققًا؛ السنة 365 يومًا؛ الإسقاط = الري الفعلي/الأيام المنقضية ×365، مقيد بالسعة المختارة ×365. سعة 10 م³/يوم: بيع 78000 + تركيب 12000 وصيانة سنوية 10000 ريال؛ سعة 20: ‏95000 + 15000 وصيانة 13000؛ سعة 30: ‏112000 + 18000 وصيانة 16000. الاسترداد = الرأسمالي/(قيمة الماء − التشغيل والصيانة)، ولا يتحقق إن كان الصافي ≤0.', note: 'أسعار مورد افتراضات توضيحية مقدمة في المهمة، وليست عروض أسعار. لا تُحتسب غرامة كإيراد، ولا تُفترض وفورات قياس حقيقية.' },
  { id: 'hydraloop', title: 'تحجيم المقارنة التجارية', values: 'الوحدات = سقف(متوسط الدخول المستعاد اليومي المخطط للأسبوع/720 لترًا)؛ البصمة = 0.82 × 0.68 م²/وحدة؛ قدرة المعالجة 50 واط/وحدة؛ السعر غير منشور.', note: 'قيم المورد المنشورة تحتاج مطابقة إصدار المنتج. ليست مساحة منشأة كاملة ولا طاقة سنوية، ولا نفترض استجابة أو ماء مطابقًا تحت أعطال مورد.' }
];

export const DEFAULT_CONFIG = Object.freeze({
  preset: 'mosque', seed: 350, days: 7, stepMinutes: 5,
  peoplePerDay: 2500, litresPerAblution: 4, handwashesPerPerson: 0.5,
  litresPerHandwash: 1, recovery: 0.8, fridayMultiplier: 1.8,
  prayerTimes: ['05:10', '12:15', '15:35', '18:00', '19:30'],
  equalizationLitres: 5000, treatedLitres: 3000, treatmentM3PerDay: 20,
  maxRetries: 3,
  limits: { turbidity: 5, phMin: 6, phMax: 9, uvIntensity: 70, confidence: 70 },
  efficiency: {
    sand: { turbidity: 0.7, tss: 0.75, cod: 0.15 },
    carbon: { turbidity: 0.25, tss: 0.25, cod: 0.55 },
    pp: { turbidity: 0.8, tss: 0.9, cod: 0.05 }
  }
});

export const FAULTS = Object.freeze([
  { id: 'drift', label: 'انحراف حساس العكارة النهائي', expected: 'باقٍ متزايد ← ثقة أقل ← احتجاز وبلاغ معايرة' },
  { id: 'ph', label: 'اتساخ حساس pH', expected: 'اختلاف عن حساس الدخول ← احتجاز وبلاغ معايرة' },
  { id: 'uv', label: 'ضعف مصباح UV', expected: 'جرعة أقل ← احتجاز وبلاغ تغيير مصباح' },
  { id: 'power', label: 'انقطاع الكهرباء', expected: 'إغلاق الصمام وإيقاف المضخات فورًا' },
  { id: 'clog', label: 'انسداد الفلتر الرملي', expected: 'ارتفاع فرق الضغط ← غسيل ← بلاغ إن تكرر' },
  { id: 'contamination', label: 'دفعة صابون أو طين', expected: 'ارتفاع الجودة المقاسة عن الحدود ← إعادة معالجة ← صرف عند نفاد المحاولات' },
  { id: 'carbon', label: 'تشبع الكربون', expected: 'إنذار اختراق من نسبة COD ← بلاغ تغيير الوسط' },
  { id: 'valve', label: 'فشل الصمام عن الإغلاق', expected: 'إنذار حرج وإيقاف المضخات؛ يفترض المسار المضخوخ انعدام الجريان عند توقفها' }
]);

const clamp = (x, min, max) => Math.max(min, Math.min(max, Number(x)));
const bounded = (value, fallback, min, max) => Number.isFinite(Number(value)) ? clamp(value, min, max) : fallback;
const BASE_DP = 0.15;
const DP_LIMIT = 0.75;
const DOSE_LIMIT = 40;
const MICROBIAL_LIMIT = 1;
const MAX_AGE_MINUTES = 360;
const MINUTES_PER_DAY = 1440;
const M3_TO_LITRES = 1000;
const BACKWASH_LITRES = 120;
const EPSILON = 1e-8;
const qualityKeys = ['turbidity', 'tss', 'cod', 'ph', 'ec', 'ecoli', 'observerTurbidity', 'observerPh', 'observerEc', 'observerEcoliUpper', 'age'];

function random(seed) {
  let value = seed >>> 0;
  return () => {
    value += 0x6D2B79F5;
    let t = value;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
const atRandom = (sim, salt = 0) => random((sim.config.seed + Math.imul(sim.step + 1, 2654435761) + salt) >>> 0);
const signed = (rng, width) => (rng() * 2 - 1) * width;
const emptyQuality = () => ({ turbidity: 0, tss: 0, cod: 0, ph: 7.5, ec: 0, ecoli: 0, observerTurbidity: 0, observerPh: 7.5, observerEc: 0, observerEcoliUpper: 0, dose: 0, intensity: 0, age: 0 });

function normalizeConfig(config) {
  const merged = { ...DEFAULT_CONFIG, ...config, limits: { ...DEFAULT_CONFIG.limits, ...config?.limits } };
  merged.days = 7;
  merged.stepMinutes = 5;
  merged.seed = bounded(merged.seed, 350, 0, 4294967295) >>> 0;
  merged.peoplePerDay = bounded(merged.peoplePerDay, 2500, 0, 1000000);
  merged.litresPerAblution = bounded(merged.litresPerAblution, 4, 2.5, 5);
  merged.handwashesPerPerson = bounded(merged.handwashesPerPerson, 0.5, 0, 20);
  merged.litresPerHandwash = bounded(merged.litresPerHandwash, 1, 0, 20);
  merged.recovery = bounded(merged.recovery, 0.8, 0, 1);
  merged.fridayMultiplier = bounded(merged.fridayMultiplier, 1.8, 1, 10);
  for (const [name, fallback, min, max] of [['equalizationLitres', 5000, 1, 1000000], ['treatedLitres', 3000, 1, 1000000], ['treatmentM3PerDay', 20, 0.1, 10000], ['maxRetries', 3, 0, 20]]) {
    merged[name] = bounded(merged[name], fallback, min, max);
  }
  merged.maxRetries = Math.floor(merged.maxRetries);
  merged.preset = ['mosque', 'university', 'haram'].includes(merged.preset) ? merged.preset : 'mosque';
  merged.prayerTimes = Array.from({ length: 5 }, (_, i) => /^([01]\d|2[0-3]):[0-5]\d$/.test(merged.prayerTimes?.[i]) ? merged.prayerTimes[i] : DEFAULT_CONFIG.prayerTimes[i]);
  const ranges = { sand: [[0.4, 0.85], [0.5, 0.9], [0.05, 0.3]], carbon: [[0.1, 0.4], [0.1, 0.5], [0.2, 0.8]], pp: [[0.6, 0.95], [0.7, 0.98], [0, 0.1]] };
  merged.efficiency = {};
  for (const stage of ['sand', 'carbon', 'pp']) {
    merged.efficiency[stage] = Object.fromEntries(['turbidity', 'tss', 'cod'].map((key, i) => [key, bounded(config?.efficiency?.[stage]?.[key], DEFAULT_CONFIG.efficiency[stage][key], ...ranges[stage][i])]));
  }
  for (const [key, fallback, min, max] of [['turbidity', 5, 0.5, 50], ['phMin', 6, 0, 13], ['phMax', 9, 1, 14], ['uvIntensity', 70, 10, 100], ['confidence', 70, 1, 100]]) {
    merged.limits[key] = bounded(merged.limits[key], fallback, min, max);
  }
  if (merged.limits.phMax <= merged.limits.phMin) merged.limits.phMax = Math.min(14, merged.limits.phMin + 1);
  return merged;
}

function makeInflowPlan(config) {
  const rng = random(config.seed);
  const prayerMinutes = config.prayerTimes.map(time => Number(time.slice(0, 2)) * 60 + Number(time.slice(3)));
  const stepsPerDay = MINUTES_PER_DAY / config.stepMinutes;
  const inflow = [], nominal = [], totals = [];
  const ordinaryLitres = config.peoplePerDay * (config.litresPerAblution + config.handwashesPerPerson * config.litresPerHandwash) * config.recovery;
  for (let day = 0; day < config.days; day++) {
    const active = config.preset !== 'university' || day % 7 < 5;
    const total = active ? ordinaryLitres * (day % 7 === 5 ? config.fridayMultiplier : 1) : 0;
    const weights = Array.from({ length: stepsPerDay }, (_, index) => {
      const minute = index * config.stepMinutes;
      const prayers = config.preset === 'university' ? prayerMinutes.slice(1, 3) : prayerMinutes;
      const pulse = prayers.reduce((sum, prayer) => {
        const delta = minute - (prayer - 10);
        return sum + (minute >= prayer - 20 && minute <= prayer ? Math.exp(-(delta * delta) / (2 * 8 * 8)) : 0);
      }, 0);
      return config.preset === 'haram' ? 0.012 + pulse * 0.08 : pulse;
    });
    const noisy = weights.map(weight => weight * (1 + signed(rng, 0.05)));
    const sum = noisy.reduce((a, b) => a + b, 0) || 1;
    const nominalSum = weights.reduce((a, b) => a + b, 0) || 1;
    weights.forEach((weight, i) => { inflow.push(noisy[i] / sum * total); nominal.push(active ? weight / nominalSum : 0); });
    totals.push(total);
  }
  return { inflow, nominal, totals, ordinaryLitres };
}

export function createSimulation(config = {}) {
  const normalized = normalizeConfig(config);
  const sim = {
    config: normalized, step: 0, minute: 0, day: 1, timeLabel: 'اليوم 1 · 00:00', done: false,
    route: 'HOLD', decision: evaluateReuse({}), controllerInput: {},
    equalization: { litres: 0, quality: emptyQuality() }, treated: { litres: 0, quality: emptyQuality(), retries: 0 },
    quality: { raw: emptyQuality(), sand: emptyQuality(), carbon: emptyQuality(), pp: emptyQuality(), final: emptyQuality(), measured: emptyQuality() },
    sensors: {},
    stages: { sand: { dp: BASE_DP, efficiency: normalized.efficiency.sand.turbidity }, carbon: { dp: 0.1, saturation: 0, breakthrough: false, ratio: 0.45 }, pp: { dp: 0.08 }, uv: { intensity: 100, measuredIntensity: 100, dose: 0, measuredDose: 0, logReduction: 0, hours: 0, transmittance: 1 } },
    ai: { confidence: 100, predictions: { backwashDays: null, lampDays: null, carbonDays: null }, forecast: 0, forecastError: 0, explanations: [] },
    faults: {}, events: [], history: [], calibrations: [], maintenance: [],
    totals: { collected: 0, irrigated: 0, diverted: 0, overflow: 0, backwash: 0, backwashFixed: 0, simpleIrrigated: 0, simpleUnsafeCount: 0, simpleUnsafeLitres: 0, unsafeCount: 0, unsafeLitres: 0, availableSteps: 0, activeSteps: 0, qualitySteps: 0, qualityWithinSteps: 0, forecastAbsolute: 0, forecastActual: 0, processed: 0 },
    _plan: makeInflowPlan(normalized), _ewma: { turbidity: 0, ph: 0 }, _lastReadings: [], _pressureHistory: [],
    _lastRoute: 'HOLD', _announced: new Set(), _washSteps: [], _currentDayCollected: 0,
    _forecastDaily: null, _pumpLitres: 0, _washThisStep: 0, _recirculation: false, _maintenanceActive: false
  };
  sim._forecastDaily = sim._plan.ordinaryLitres * 0.9;
  refreshReadings(sim, false);
  updateDecision(sim);
  return sim;
}

function timeLabel(minute) {
  const day = Math.floor(minute / MINUTES_PER_DAY) + 1;
  const within = Math.floor(minute % MINUTES_PER_DAY);
  return `اليوم ${day} · ${String(Math.floor(within / 60)).padStart(2, '0')}:${String(within % 60).padStart(2, '0')}`;
}

function event(sim, type, title, explanation, severity = 'info', fault = null) {
  const item = { minute: sim.minute, time: sim.timeLabel, type, title, explanation, severity, fault };
  sim.events.unshift(item);
  sim.ai.explanations.unshift(explanation);
  sim.ai.explanations = sim.ai.explanations.slice(0, 8);
  return item;
}

function once(sim, key, callback) {
  if (sim._announced.has(key)) return;
  sim._announced.add(key);
  callback();
}

function maintenance(sim, key, title, explanation, fault = null) {
  once(sim, `maintenance:${key}`, () => {
    sim.maintenance.push({ key, minute: sim.minute, title, explanation, resolved: false });
    event(sim, 'maintenance', title, explanation, 'warning', fault);
  });
}

function mixQuality(a, aLitres, b, bLitres) {
  if (aLitres <= EPSILON) return { ...b };
  if (bLitres <= EPSILON) return { ...a };
  const total = aLitres + bLitres;
  const mixed = Object.fromEntries(qualityKeys.map(key => [key, ((a[key] || 0) * aLitres + (b[key] || 0) * bLitres) / total]));
  // A conservative minimum, rather than a dose average, tracks the least
  // disinfected parcel in a completely mixed tank.
  mixed.age = Math.max(a.age || 0, b.age || 0);
  mixed.dose = Math.min(a.dose || 0, b.dose || 0);
  mixed.intensity = Math.min(a.intensity || 0, b.intensity || 0);
  return mixed;
}

function take(tank, litres) {
  const removed = Math.min(tank.litres, Math.max(0, litres));
  tank.litres -= removed;
  if (tank.litres < EPSILON) tank.litres = 0;
  return removed;
}

function add(tank, litres, quality) {
  if (litres <= 0) return;
  tank.quality = mixQuality(tank.quality, tank.litres, quality, litres);
  tank.litres += litres;
}

function sourceQuality(sim) {
  const rng = atRandom(sim, 129);
  const contaminated = Boolean(sim.faults.contamination && !sim.faults.contamination.pending && sim.step < sim.faults.contamination.endStep);
  const quality = contaminated ? {
    turbidity: 250 + rng() * 200, tss: 300 + rng() * 200, cod: 500 + rng() * 400,
    ph: 9.7 + rng() * 0.4, ec: 400 + rng() * 800, ecoli: 10 ** (4 + rng())
  } : {
    turbidity: 10 + rng() * 30, tss: 15 + rng() * 45, cod: 40 + rng() * 110,
    ph: 7 + rng() * 1.5, ec: 400 + rng() * 800, ecoli: 10 ** (1 + rng() * 2)
  };
  return { ...quality, observerTurbidity: Math.max(0, quality.turbidity + signed(rng, 0.1)), observerPh: quality.ph + signed(rng, 0.02), observerEc: quality.ec * (1 + signed(rng, 0.02)), observerEcoliUpper: 100000, dose: 0, intensity: 0, age: 0 };
}

function filterQuality(input, efficiency) {
  return { ...input,
    turbidity: input.turbidity * (1 - efficiency.turbidity),
    tss: input.tss * (1 - efficiency.tss), cod: input.cod * (1 - efficiency.cod),
    observerTurbidity: input.observerTurbidity * (1 - efficiency.turbidity)
  };
}

function processQuality(sim, input, litres) {
  const efficiency = sim.config.efficiency;
  const penalty = Math.max(0, Math.min(0.8, sim.stages.sand.dp - BASE_DP)) * 0.12;
  const sandEfficiency = { ...efficiency.sand, turbidity: Math.max(0, efficiency.sand.turbidity - penalty), tss: Math.max(0, efficiency.sand.tss - penalty) };
  const sand = filterQuality(input, sandEfficiency);
  const carbon = filterQuality(sand, { ...efficiency.carbon, cod: efficiency.carbon.cod * (1 - sim.stages.carbon.saturation) });
  const pp = filterQuality(carbon, efficiency.pp);
  const designFlow = sim.config.treatmentM3PerDay * M3_TO_LITRES / (MINUTES_PER_DAY / sim.config.stepMinutes);
  const transmittance = Math.exp(-0.025 * pp.turbidity);
  const dose = Math.min(120, 60 * sim.stages.uv.intensity / 100 * transmittance * designFlow / Math.max(litres, EPSILON));
  const logReduction = Math.min(6, dose / 10);
  const estimatedDose = observedDose(sim, pp.observerTurbidity, litres);
  const final = { ...pp, ecoli: pp.ecoli * 10 ** -logReduction, observerEcoliUpper: pp.observerEcoliUpper * 10 ** -Math.min(6, estimatedDose / 10), dose, intensity: sim.stages.uv.intensity, age: 0 };
  sim.stages.sand.efficiency = sandEfficiency.turbidity;
  sim.stages.sand.dp += Math.max(0, input.tss - sand.tss) * litres / M3_TO_LITRES * 0.0002;
  sim.stages.carbon.dp += Math.max(0, sand.tss - carbon.tss) * litres / M3_TO_LITRES * 0.0003;
  sim.stages.pp.dp += Math.max(0, carbon.tss - pp.tss) * litres / M3_TO_LITRES * 0.00012;
  sim.stages.carbon.saturation = Math.min(1, sim.stages.carbon.saturation + Math.max(0, sand.cod - carbon.cod) * litres / M3_TO_LITRES / 10000);
  const codRng = atRandom(sim, 731);
  sim.stages.carbon.inletCodMeasured = sand.cod * (1 + signed(codRng, 0.02));
  sim.stages.carbon.outletCodMeasured = carbon.cod * (1 + signed(codRng, 0.02));
  sim.stages.carbon.adsorbedMeasuredGrams = (sim.stages.carbon.adsorbedMeasuredGrams || 0) + Math.max(0, sim.stages.carbon.inletCodMeasured - sim.stages.carbon.outletCodMeasured) * litres / M3_TO_LITRES;
  sim.stages.carbon.ratio = sim.stages.carbon.inletCodMeasured > 1 ? sim.stages.carbon.outletCodMeasured / sim.stages.carbon.inletCodMeasured : 0;
  sim.stages.carbon.breakthrough = sim.stages.carbon.ratio >= 0.85;
  Object.assign(sim.stages.uv, { transmittance, dose, logReduction });
  sim.quality.sand = sand; sim.quality.carbon = carbon; sim.quality.pp = pp;
  sim.totals.processed += litres;
  return final;
}

function refreshReadings(sim, advanceResiduals = true) {
  const rng = atRandom(sim, 213);
  const quality = sim.treated.quality;
  const elapsedDrift = sim.faults.drift ? Math.max(0, sim.minute - sim.faults.drift.minute) : 0;
  const elapsedPh = sim.faults.ph ? Math.max(0, sim.minute - sim.faults.ph.minute) : 0;
  let turbidity = Math.max(0, quality.turbidity + signed(rng, 0.1) - elapsedDrift * 0.012);
  let ph = quality.ph + signed(rng, 0.02) - Math.min(2, elapsedPh * 0.003);
  if (sim.faults.freeze && sim.faults.freeze.value != null) turbidity = sim.faults.freeze.value;
  const ec = quality.ec * (1 + signed(rng, 0.02));
  const trueFlow = sim._pumpLitres;
  const flow = trueFlow * (1 + signed(rng, 0.02));
  const residualTurbidity = Math.abs(turbidity - quality.observerTurbidity);
  const residualPh = Math.abs(ph - quality.observerPh);
  if (advanceResiduals) {
    sim._ewma.turbidity = 0.35 * residualTurbidity + 0.65 * sim._ewma.turbidity;
    sim._ewma.ph = 0.35 * residualPh + 0.65 * sim._ewma.ph;
    sim._lastReadings.push({ turbidity, expected: quality.observerTurbidity });
    sim._lastReadings = sim._lastReadings.slice(-6);
  }
  const stuck = sim._lastReadings.length === 6 && sim._lastReadings.every(reading => reading.turbidity === sim._lastReadings[0].turbidity) && Math.abs(sim._lastReadings.at(-1).expected - sim._lastReadings[0].expected) > 0.08;
  // The observer reads upstream measured water and the declared process model.
  // It never compares a sensor against hidden final ground truth.
  const confidenceTurbidity = sim.faults.sensor || stuck ? 0 : clamp(100 - Math.max(residualTurbidity, sim._ewma.turbidity) * 140, 0, 100);
  const confidencePh = clamp(100 - Math.max(residualPh, sim._ewma.ph) * 220, 0, 100);
  const ecResidual = quality.observerEc > 0 ? Math.abs(ec - quality.observerEc) / quality.observerEc : 0;
  // EC conservation is an assumed no-salt-removal model; observerEc is an independent noisy inlet EC reference,
  // carried through unchanged by the no-salt-removal model.
  const confidenceEc = clamp(100 - ecResidual * 700, 0, 100);
  const flowResidual = trueFlow > 0 ? Math.abs(flow - trueFlow) / trueFlow : Math.abs(flow);
  const confidenceFlow = clamp(100 - flowResidual * 400, 0, 100);
  const intensity = Math.max(0, sim.stages.uv.intensity + signed(rng, 0.2));
  const measuredDose = sim.treated.litres > 0 ? Math.min(120, 60 * intensity / 100 * Math.exp(-0.025 * turbidity) * (sim._pumpLitres > EPSILON ? sim.config.treatmentM3PerDay * M3_TO_LITRES / (MINUTES_PER_DAY / sim.config.stepMinutes) / sim._pumpLitres : 1)) : 0;
  // Stored water keeps its conservative minimum dose; estimated tank dose is
  // propagated separately from the actual microbiological audit value.
  const doseReference = sim.treated.litres > 0 ? Math.min(measuredDose, sim.treated.observerDose ?? measuredDose) : 0;
  sim.sensors = {
    turbidity: { true: quality.turbidity, measured: turbidity, confidence: confidenceTurbidity, valid: !sim.faults.sensor, residual: residualTurbidity },
    ph: { true: quality.ph, measured: ph, confidence: confidencePh, valid: true, residual: residualPh },
    ec: { true: quality.ec, measured: ec, confidence: confidenceEc, valid: true },
    flow: { true: trueFlow, measured: flow, confidence: confidenceFlow, valid: true },
    cheapTurbidity: { true: quality.turbidity, measured: Math.max(0, quality.turbidity + signed(rng, 50)), errorFullScale: 50, usedForDecision: false }
  };
  sim.stages.uv.measuredIntensity = intensity;
  sim.stages.uv.measuredDose = doseReference;
  sim.ai.confidence = Math.min(confidenceTurbidity, confidencePh, confidenceEc, confidenceFlow);
  sim.ai.modelMicrobialUpper = quality.observerEcoliUpper;
  sim.ai.modelBatchIntensity = sim.treated.observerIntensity ?? 0;
  sim.quality.final = { ...quality };
  sim.quality.measured = { turbidity, ph, ec, flow, dose: doseReference, intensity };
  sim._stuck = stuck;
}

// Only measured instruments, actuator feedback and explicit operational state
// enter this adapter. The post-decision audit below cannot change permission.
export function buildControllerInput(sim, useAI = true) {
  const measured = sim.sensors;
  const limits = sim.config.limits;
  const qualityMeasured = measured.turbidity.measured <= Math.max(0, limits.turbidity - 0.3)
    && measured.ph.measured >= limits.phMin + 0.2 && measured.ph.measured <= limits.phMax - 0.2;
  const base = {
    power: !sim.faults.power,
    sensorValid: measured.turbidity.valid === true && measured.ph.valid === true,
    calibrationValid: !sim.maintenance.some(item => item.key.startsWith('calibration:') && !item.resolved), freshData: !sim._stuck,
    flowValid: measured.flow.valid && (!sim.faults.valve || measured.flow.measured === 0),
    treatmentValid: qualityMeasured,
    disinfectionValid: sim.stages.uv.measuredIntensity >= limits.uvIntensity + 0.2 && sim.stages.uv.measuredDose >= DOSE_LIMIT && sim.ai.modelMicrobialUpper <= MICROBIAL_LIMIT && sim.ai.modelBatchIntensity >= limits.uvIntensity,
    storageValid: sim.treated.litres > 0 && sim.treated.quality.age <= MAX_AGE_MINUTES,
    maintenance: sim._maintenanceActive || sim.stages.carbon.breakthrough,
    criticalFault: Boolean(sim.faults.valve)
  };
  if (!useAI) return base;
  // The AI adapter can only turn a required true into false; it cannot repair
  // any failed base condition or write OPEN/REUSE.
  return { ...base,
    sensorValid: base.sensorValid && sim.ai.confidence >= limits.confidence,
    calibrationValid: base.calibrationValid && measured.ph.confidence >= limits.confidence,
    freshData: base.freshData && measured.turbidity.confidence > 0
  };
}

function updateDecision(sim) {
  sim.controllerInput = buildControllerInput(sim);
  sim.decision = evaluateReuse(sim.controllerInput);
  const recoverable = sim.controllerInput.power && sim.controllerInput.sensorValid && sim.controllerInput.calibrationValid
    && sim.controllerInput.freshData && !sim.controllerInput.criticalFault && !sim.controllerInput.maintenance
    && sim.stages.uv.measuredIntensity >= sim.config.limits.uvIntensity + 0.2
    && sim.treated.litres > EPSILON && (!sim.controllerInput.treatmentValid || !sim.controllerInput.disinfectionValid);
  sim.route = sim.decision.permitted ? 'IRRIGATE' : recoverable ? 'REPROCESS' : 'HOLD';
  sim.pumpsRunning = !sim.faults.power && !sim.faults.valve;
  sim.valveCommand = sim.decision.valve;
  sim.valveFeedback = sim.faults.valve ? 'STUCK_OPEN' : sim.decision.valve;
}

function auditQuality(sim, quality) {
  const limits = sim.config.limits;
  return quality.turbidity <= limits.turbidity && quality.ph >= limits.phMin && quality.ph <= limits.phMax
    && quality.ecoli <= MICROBIAL_LIMIT && quality.dose >= DOSE_LIMIT && quality.intensity >= limits.uvIntensity;
}

function backwash(sim) {
  if (sim.treated.litres + sim.equalization.litres < BACKWASH_LITRES) { sim._maintenanceActive = true; return; }
  let required = BACKWASH_LITRES;
  const treatedDraw = take(sim.treated, required);
  required -= treatedDraw;
  const rawDraw = take(sim.equalization, required);
  const used = treatedDraw + rawDraw;
  if (used <= EPSILON) return;
  sim.stages.sand.dp = BASE_DP;
  sim._washThisStep = used;
  sim.totals.backwash += used;
  sim._maintenanceActive = true;
  sim._washSteps = sim._washSteps.filter(step => sim.step - step < 72);
  sim._washSteps.push(sim.step);
  event(sim, 'backwash', 'غسيل عكسي حسب فرق الضغط', `أوقف الري مؤقتًا عند فرق ضغط مرتفع؛ استُهلك ${used.toFixed(1)} لتر من الماء المستعاد، وأعيد فرق الضغط إلى ${BASE_DP} بار.`, 'info', sim.faults.clog ? 'clog' : null);
  if (sim._washSteps.length >= 3) {
    maintenance(sim, 'sand', 'فحص الفلتر الرملي', 'تكرر ارتفاع فرق الضغط بعد ثلاث غسلات متقاربة؛ يلزم فحص سبب الانسداد قبل استئناف التشغيل.', 'clog');
  }
}

function updatePredictions(sim) {
  sim._pressureHistory.push({ minute: sim.minute, dp: sim.stages.sand.dp });
  sim._pressureHistory = sim._pressureHistory.slice(-72);
  const values = sim._pressureHistory;
  const meanTime = values.reduce((sum, v) => sum + v.minute, 0) / values.length;
  const meanDp = values.reduce((sum, v) => sum + v.dp, 0) / values.length;
  const denominator = values.reduce((sum, v) => sum + (v.minute - meanTime) ** 2, 0);
  const slope = denominator ? values.reduce((sum, v) => sum + (v.minute - meanTime) * (v.dp - meanDp), 0) / denominator : 0;
  sim.ai.predictions.backwashDays = slope > 0 ? Math.max(0, (DP_LIMIT - sim.stages.sand.dp) / slope / MINUTES_PER_DAY) : null;
  const decline = 0.003 / 60 + (sim.faults.uv ? 0.12 : 0);
  sim.ai.predictions.lampDays = Math.max(0, (sim.stages.uv.measuredIntensity - sim.config.limits.uvIntensity) / decline / MINUTES_PER_DAY);
  const adsorbed = sim.stages.carbon.adsorbedMeasuredGrams || 0;
  const elapsedDays = sim.minute / MINUTES_PER_DAY;
  const adsorptionRate = elapsedDays > 0 ? adsorbed / elapsedDays : 0;
  const breakthroughMass = 10000 * Math.max(0, 1 - (1 - 0.85) / sim.config.efficiency.carbon.cod);
  sim.ai.predictions.carbonDays = sim.stages.carbon.breakthrough ? 0 : adsorptionRate > 0 ? Math.max(0, (breakthroughMass - adsorbed) / adsorptionRate) : null;
}

function explainRoute(sim) {
  if (sim.ai.confidence < sim.config.limits.confidence) {
    const weak = sim.sensors.turbidity.confidence <= sim.sensors.ph.confidence ? 'العكارة النهائي' : 'pH';
    const elapsed = sim.minute - (sim.faults[weak === 'pH' ? 'ph' : 'drift']?.minute ?? sim.minute);
    maintenance(sim, `calibration:${weak}`, `معايرة حساس ${weak}`, `احتجز النظام الماء ${sim.timeLabel} لأن ثقة حساس ${weak} انخفضت إلى ${Math.round(sim.ai.confidence)}% بعد باقي قياس متزايد خلال ${(elapsed / 60).toFixed(1)} ساعة؛ لا تسمح طبقة الذكاء بفتح الصمام.`, weak === 'pH' ? 'ph' : 'drift');
  }
  if (sim.stages.uv.measuredIntensity < sim.config.limits.uvIntensity + 0.2 || (sim.treated.litres > 0 && sim.stages.uv.measuredDose < DOSE_LIMIT)) {
    if (sim.stages.uv.hours > 0) maintenance(sim, 'uv', 'فحص جرعة ومصباح UV', 'انخفضت الشدة أو الجرعة المقدرة عن حد التشغيل؛ حُجز الماء ويُطلب فحص المصباح والمفاعل قبل استئناف الري.', 'uv');
  }
  if (sim.stages.carbon.breakthrough) maintenance(sim, 'carbon', 'تغيير وسط الامتزاز', 'ظهر اختراق افتراضي لأن نسبة COD الخارج إلى الداخل بلغت حد التنبيه؛ فرق الضغط وحده لا يثبت التشبع.', 'carbon');
  if (sim.route !== sim._lastRoute) {
    const titles = { IRRIGATE: 'فتح مسار الري بالقواعد الثابتة', REPROCESS: 'إعادة معالجة الماء', HOLD: 'احتجاز وإغلاق صمام الري', DIVERT: 'تحويل الماء إلى الصرف' };
    const reasonLabels = { POWER_LOSS: 'فقد الكهرباء', SENSOR_INVALID: 'حساس غير موثوق', CALIBRATION_INVALID: 'حاجة إلى المعايرة', STALE_DATA: 'قراءة متجمدة', FLOW_INVALID: 'تدفق غير موثوق', TREATMENT_INVALID: 'جودة خارج حدود التشغيل', DISINFECTION_INVALID: 'شرط تعقيم غير مستوفى', STORAGE_INVALID: 'لا ماء مؤهل في التخزين', MAINTENANCE_OR_UNKNOWN: 'صيانة أو اختراق وسط', CRITICAL_FAULT_OR_UNKNOWN: 'عطل حرج في الصمام' };
    const reasons = sim.decision.reasons.map(code => reasonLabels[code] || code).join('، ');
    event(sim, 'route', titles[sim.route], sim.route === 'IRRIGATE' ? `استوفت القراءات المقاسة والهوامش جميع شروط evaluateReuse عند ${sim.timeLabel}.` : `غيّر المتحكم المسار عند ${sim.timeLabel}؛ أسباب القواعد: ${reasons || 'نفاد محاولات إعادة المعالجة'}.`, sim.route === 'HOLD' ? 'warning' : 'info');
    sim._lastRoute = sim.route;
  }
}

function simpleComparator(sim, inflow, raw) {
  if (sim.faults.power || inflow <= EPSILON) return;
  const clogPenalty = Math.max(0, Math.min(0.8, sim.stages.sand.dp - BASE_DP)) * 0.12;
  const simple = filterQuality(raw, { ...sim.config.efficiency.sand, turbidity: Math.max(0, sim.config.efficiency.sand.turbidity - clogPenalty) });
  sim.totals.simpleIrrigated += inflow;
  const limits = sim.config.limits;
  if (simple.turbidity > limits.turbidity || simple.ph < limits.phMin || simple.ph > limits.phMax || simple.ecoli > MICROBIAL_LIMIT) {
    sim.totals.simpleUnsafeCount++;
    sim.totals.simpleUnsafeLitres += inflow;
  }
}

function singleStep(sim) {
  if (sim.done) return;
  sim._washThisStep = 0;
  sim._maintenanceActive = sim.maintenance.some(item => item.key === 'sand' && !item.resolved);
  const stepMinutes = sim.config.stepMinutes;
  const withinDay = sim.minute % MINUTES_PER_DAY;
  const dayIndex = Math.floor(sim.minute / MINUTES_PER_DAY);
  const inflow = sim._plan.inflow[sim.step] || 0;
  const nominalWeight = sim._plan.nominal[sim.step] || 0;
  const friday = dayIndex % 7 === 5 ? sim.config.fridayMultiplier : 1;
  const forecast = nominalWeight * sim._forecastDaily * friday;
  sim.ai.forecast = forecast;
  sim.totals.forecastAbsolute += Math.abs(inflow - forecast);
  sim.totals.forecastActual += inflow;
  sim.ai.forecastError = sim.totals.forecastActual > 0 ? sim.totals.forecastAbsolute / sim.totals.forecastActual * 100 : 0;
  sim._currentDayCollected += inflow;
  sim.totals.collected += inflow;
  if (sim.faults.contamination?.pending && inflow > EPSILON) {
    sim.faults.contamination.pending = false;
    sim.faults.contamination.endStep = sim.step + 120 / stepMinutes;
    event(sim, 'contamination', 'بدء دخول دفعة التلوث الافتراضية', 'بدأت نافذة الدفعة عند أول تدفق موجب بعد الحقن، وتُطبّق الجودة نفسها على مقارنة الترشيح البسيط.', 'warning', 'contamination');
  }
  const raw = sourceQuality(sim);
  sim.quality.raw = { ...raw };
  add(sim.equalization, inflow, raw);
  const overflow = take(sim.equalization, Math.max(0, sim.equalization.litres - sim.config.equalizationLitres));
  sim.totals.overflow += overflow;
  for (const tank of [sim.equalization, sim.treated]) {
    if (tank.litres > 0) {
      tank.quality.age += stepMinutes;
      tank.quality.ecoli *= Math.exp(0.001 * stepMinutes);
      tank.quality.observerEcoliUpper *= Math.exp(0.001 * stepMinutes);
    }
  }
  if (sim.equalization.litres > 0 && sim.equalization.quality.age > MAX_AGE_MINUTES) {
    const staleRaw = take(sim.equalization, sim.equalization.litres);
    sim.totals.diverted += staleRaw;
    event(sim, 'diversion', 'صرف ماء الموازنة بعد مهلة التخزين', `حُوّل ${staleRaw.toFixed(1)} لتر إلى الصرف بسبب عمر دفعة يتجاوز الحد الافتراضي؛ القرار مبني على سجل الزمن لا على معرفة الجودة الحقيقية.`, 'warning');
  }
  if (sim.faults.clog) sim.stages.sand.dp += 0.11;
  if (!sim.faults.power) {
    sim.stages.uv.hours += stepMinutes / 60;
    sim.stages.uv.intensity = Math.max(0, sim.stages.uv.intensity - 0.003 * stepMinutes / 60 - (sim.faults.uv ? 0.12 * stepMinutes : 0));
  }
  if (sim.faults.uvFailure) sim.stages.uv.intensity = 0;
  const lampRng = atRandom(sim, 977);
  sim.stages.uv.measuredIntensity = Math.max(0, sim.stages.uv.intensity + signed(lampRng, 0.2));
  if ((sim.step + 1) % (MINUTES_PER_DAY / stepMinutes) === 0) sim._fixedWashDue = true;
  if (sim._fixedWashDue && !sim.faults.power && !sim.faults.valve && sim.equalization.litres + sim.treated.litres > 0) {
    sim.totals.backwashFixed += Math.min(BACKWASH_LITRES, sim.equalization.litres + sim.treated.litres);
    sim._fixedWashDue = false;
  }
  sim.pumpsRunning = !sim.faults.power && !sim.faults.valve;
  if (sim.pumpsRunning && sim.stages.sand.dp >= DP_LIMIT && !sim._maintenanceActive) backwash(sim);
  const plantCapacity = sim.config.treatmentM3PerDay * M3_TO_LITRES / (MINUTES_PER_DAY / stepMinutes);
  sim._pumpLitres = 0;
  sim._recirculation = sim.route === 'REPROCESS' && sim.treated.litres > EPSILON;
  if (sim.pumpsRunning && !sim._maintenanceActive) {
    if (sim._recirculation) {
      if (sim.treated.retries >= sim.config.maxRetries) {
        const diverted = take(sim.treated, sim.treated.litres);
        sim.totals.diverted += diverted;
        sim.treated.retries = 0;
        sim.treated.observerDose = undefined; sim.treated.observerIntensity = undefined;
        sim.route = 'DIVERT';
        event(sim, 'diversion', 'نفاد محاولات إعادة المعالجة', `حُوّل ${diverted.toFixed(1)} لتر إلى الصرف بعد ${sim.config.maxRetries} محاولات دون تحسن كافٍ.`, 'warning', sim.faults.contamination ? 'contamination' : null);
      } else {
        const volume = Math.min(plantCapacity, sim.treated.litres);
        const input = { ...sim.treated.quality };
        take(sim.treated, volume);
        const final = processQuality(sim, input, volume);
        const unprocessedVolume = sim.treated.litres;
        add(sim.treated, volume, final);
        sim._pumpLitres = volume;
        sim.treated.retries++;
        // Unprocessed water remains at its previous observer dose.
        sim.treated.observerDose = unprocessedVolume > EPSILON ? Math.min(sim.treated.observerDose ?? Infinity, observedDose(sim, final.observerTurbidity, volume)) : observedDose(sim, final.observerTurbidity, volume);
        const batchIntensity = Math.max(0, sim.stages.uv.measuredIntensity - 0.4);
        sim.treated.observerIntensity = unprocessedVolume > EPSILON ? Math.min(sim.treated.observerIntensity ?? batchIntensity, batchIntensity) : batchIntensity;
      }
    } else {
      const volume = Math.min(plantCapacity, sim.equalization.litres, Math.max(0, sim.config.treatedLitres - sim.treated.litres));
      if (volume > EPSILON) {
        const input = { ...sim.equalization.quality };
        take(sim.equalization, volume);
        const final = processQuality(sim, input, volume);
        const previousVolume = sim.treated.litres;
        add(sim.treated, volume, final);
        sim._pumpLitres = volume;
        const newDose = observedDose(sim, final.observerTurbidity, volume);
        sim.treated.observerDose = previousVolume > EPSILON ? Math.min(sim.treated.observerDose ?? newDose, newDose) : newDose;
        const batchIntensity = Math.max(0, sim.stages.uv.measuredIntensity - 0.4);
        sim.treated.observerIntensity = previousVolume > EPSILON ? Math.min(sim.treated.observerIntensity ?? batchIntensity, batchIntensity) : batchIntensity;
      }
    }
  }
  refreshReadings(sim);
  updateDecision(sim);
  const outputAudit = sim.treated.litres > EPSILON ? auditQuality(sim, sim.treated.quality) : false;
  if (sim.treated.litres > EPSILON || sim.equalization.litres > EPSILON || inflow > EPSILON) {
    sim.totals.activeSteps++;
    if (sim.decision.permitted) sim.totals.availableSteps++;
    if (sim.treated.litres > EPSILON) { sim.totals.qualitySteps++; if (outputAudit) sim.totals.qualityWithinSteps++; }
  }
  // Release uses the existing controller's result alone. Hidden ground truth is
  // inspected only AFTER the amount has been selected, for the visible audit.
  if (sim.decision.permitted) {
    const hour = withinDay / 60;
    const irrigationDemand = plantCapacity * (hour >= 6 && hour < 22 ? 1.4 : 0.35);
    const delivered = take(sim.treated, irrigationDemand);
    sim.totals.irrigated += delivered;
    if (delivered > EPSILON && !outputAudit) {
      sim.totals.unsafeCount++;
      sim.totals.unsafeLitres += delivered;
      event(sim, 'unsafe', 'ماء غير مطابق في فاحص المحاكاة', 'رصد التدقيق المستقل خروج ماء خارج حدود النموذج؛ يجب إظهار الإخفاق وعدم إخفائه.', 'critical');
    }
    if (sim.treated.litres === 0) { sim.treated.retries = 0; sim.treated.observerDose = undefined; sim.treated.observerIntensity = undefined; }
  }
  if (sim.treated.litres > 0 && sim.treated.quality.age > MAX_AGE_MINUTES) {
    const disposed = take(sim.treated, sim.treated.litres);
    sim.totals.diverted += disposed;
    sim.treated.retries = 0;
    sim.treated.observerDose = undefined; sim.treated.observerIntensity = undefined;
    sim.route = 'DIVERT';
    event(sim, 'diversion', 'صرف بعد انتهاء عمر التخزين الافتراضي', `حُوّل ${disposed.toFixed(1)} لتر من الماء المحتجز بعد تجاوز ${MAX_AGE_MINUTES / 60} ساعات تخزين؛ هذا حد محاكاة افتراضي.`, 'warning');
  }
  simpleComparator(sim, inflow, raw);
  updatePredictions(sim);
  explainRoute(sim);
  sim.history.push({ minute: sim.minute, inflow, forecast, trueTurbidity: sim.quality.final.turbidity, measuredTurbidity: sim.sensors.turbidity.measured, route: sim.route, equalization: sim.equalization.litres, treated: sim.treated.litres, dp: sim.stages.sand.dp, backwash: sim._washThisStep, uvIntensity: sim.stages.uv.intensity, dose: sim.stages.uv.dose, confidence: sim.ai.confidence });
  sim.step++;
  sim.minute = sim.step * stepMinutes;
  sim.day = Math.min(7, Math.floor(sim.minute / MINUTES_PER_DAY) + 1);
  sim.timeLabel = timeLabel(Math.min(sim.minute, sim.config.days * MINUTES_PER_DAY - stepMinutes));
  sim.done = sim.step >= sim._plan.inflow.length;
  if (sim.step % (MINUTES_PER_DAY / stepMinutes) === 0 && (sim.config.preset !== 'university' || dayIndex % 7 < 5)) {
    const deFriday = sim._currentDayCollected / friday;
    sim._forecastDaily = 0.35 * deFriday + 0.65 * sim._forecastDaily;
    sim._currentDayCollected = 0;
  }
}

function observedDose(sim, turbidity, litres) {
  const designFlow = sim.config.treatmentM3PerDay * M3_TO_LITRES / (MINUTES_PER_DAY / sim.config.stepMinutes);
  // Independent observer: measured lamp intensity plus conservative instrument
  // guard bands, fed by the upstream measured turbidity model.
  const measuredLamp = Math.max(0, sim.stages.uv.measuredIntensity - 0.4);
  return Math.min(120, 60 * measuredLamp / 100 * Math.exp(-0.025 * Math.max(0, turbidity + 0.3)) * designFlow / Math.max(litres, EPSILON));
}

export function stepSimulation(sim, count = 1) {
  for (let i = 0; i < Math.max(0, Math.floor(count)) && !sim.done; i++) singleStep(sim);
  return sim;
}

export function injectFault(sim, id) {
  if (![...FAULTS.map(fault => fault.id), 'freeze', 'sensor', 'uvFailure'].includes(id)) return sim;
  if (sim.faults[id]) return sim;
  sim.faults[id] = { minute: sim.minute, step: sim.step };
  if (id === 'contamination') { sim.faults[id].pending = true; sim.faults[id].endStep = null; }
  if (id === 'clog') sim.stages.sand.dp += 0.7;
  if (id === 'carbon') sim.stages.carbon.saturation = 0.98;
  if (id === 'freeze') sim.faults[id].value = sim.sensors.turbidity.measured;
  if (id === 'uvFailure') sim.stages.uv.intensity = 0;
  const fault = FAULTS.find(item => item.id === id);
  event(sim, 'fault', fault?.label || `عطل ${id}`, (id === 'contamination' ? `${fault.expected}؛ تنتظر الدفعة أول تدفق وارد.` : fault?.expected) || 'يجب أن يكتشف المتحكم فقد القراءة أو شرط التعقيم ويحتجز الماء.', id === 'power' || id === 'valve' ? 'critical' : 'warning', id);
  if (id === 'valve') maintenance(sim, 'valve', 'إنذار حرج: فشل الصمام', 'التغذية الراجعة للصمام تخالف أمر الإغلاق؛ أوقفت المضخات فورًا. يفترض النموذج عدم وجود مسار ري بالجاذبية.', 'valve');
  if (id === 'power' || id === 'valve') sim._pumpLitres = 0;
  refreshReadings(sim, false);
  updateDecision(sim);
  explainRoute(sim);
  return sim;
}

export function clearFaults(sim) {
  sim.faults = {};
  sim.stages.uv.intensity = 100;
  sim.stages.sand.dp = BASE_DP;
  sim.stages.carbon.dp = 0.1;
  sim.stages.pp.dp = 0.08;
  sim.stages.carbon.saturation = 0;
  sim.stages.carbon.adsorbedMeasuredGrams = 0;
  sim.stages.carbon.breakthrough = false;
  sim.stages.carbon.ratio = 0.45;
  sim._ewma = { turbidity: 0, ph: 0 };
  sim._lastReadings = [];
  sim._washSteps = [];
  sim._maintenanceActive = false;
  sim.maintenance.forEach(item => { item.resolved = true; });
  sim._announced.clear();
  sim.calibrations.push({ minute: sim.minute, time: sim.timeLabel, status: 'محاكاة صيانة ومعايرة؛ ليست شهادة ميدانية' });
  event(sim, 'calibration', 'إزالة الأعطال ومحاكاة المعايرة', 'أُعيدت الحساسات والمصباح والوسط إلى حالتها الافتراضية. يبقى الإذن رهين جميع شروط القواعد الثابتة.');
  refreshReadings(sim, false);
  updateDecision(sim);
  return sim;
}

export function getMetrics(sim) {
  const t = sim.totals;
  const stored = sim.equalization.litres + sim.treated.litres;
  const residual = t.collected - t.irrigated - t.diverted - t.backwash - t.overflow - stored;
  const averageDailyLitres = sim._plan.totals.reduce((a, b) => a + b, 0) / sim.config.days;
  const units = Math.ceil(averageDailyLitres / 720);
  const result = {
    collected: t.collected, irrigated: t.irrigated, diverted: t.diverted, backwash: t.backwash, overflow: t.overflow, stored,
    collectedM3: t.collected / M3_TO_LITRES, irrigatedM3: t.irrigated / M3_TO_LITRES, divertedM3: t.diverted / M3_TO_LITRES,
    backwashM3: t.backwash / M3_TO_LITRES, overflowM3: t.overflow / M3_TO_LITRES, storedM3: stored / M3_TO_LITRES,
    balanceResidualLitres: residual, balanceErrorPct: t.collected > 0 ? Math.abs(residual) / t.collected * 100 : 0,
    availability: t.activeSteps ? t.availableSteps / t.activeSteps * 100 : 0,
    withinLimitsPercent: t.qualitySteps ? t.qualityWithinSteps / t.qualitySteps * 100 : 0,
    withinLimitsPct: t.qualitySteps ? t.qualityWithinSteps / t.qualitySteps * 100 : 0,
    maintenanceCount: sim.maintenance.length, unsafeIrrigationCount: t.unsafeCount, unsafeIrrigationLitres: t.unsafeLitres,
    desalinatedSavedM3: t.irrigated / M3_TO_LITRES, forecastError: sim.ai.forecastError,
    backwashFixed: t.backwashFixed, backwashSaved: t.backwashFixed - t.backwash,
    elapsedDays: sim.minute / MINUTES_PER_DAY,
    comparison: {
      mawrid: { irrigated: t.irrigated, unsafeIrrigationCount: t.unsafeCount, unsafeLitres: t.unsafeLitres },
      simple: { irrigated: t.simpleIrrigated, unsafeIrrigationCount: t.simpleUnsafeCount, unsafeLitres: t.simpleUnsafeLitres },
      hydraloop: { dailyLitres: averageDailyLitres, units, footprintM2: units * 0.82 * 0.68, watts: units * 50, price: null, simulatedQuality: false }
    }
  };
  return result;
}

export function getEconomics(sim, tariff = 6, capacity = 20) {
  const tariffs = bounded(tariff, 6, 6, 9);
  const tier = [10, 20, 30].includes(Number(capacity)) ? Number(capacity) : 20;
  const prices = { 10: [78000, 12000, 10000], 20: [95000, 15000, 13000], 30: [112000, 18000, 16000] };
  const [sale, installation, annualMaintenance] = prices[tier];
  const elapsedDays = sim.minute / MINUTES_PER_DAY;
  const annualIrrigationM3 = elapsedDays > 0 ? Math.min(tier * 365, sim.totals.irrigated / M3_TO_LITRES / elapsedDays * 365) : 0;
  const annualGrossSavings = annualIrrigationM3 * tariffs;
  const annualNetSavings = annualGrossSavings - annualMaintenance;
  return { tariff: tariffs, capacity: tier, sale, installation, annualMaintenance, capital: sale + installation,
    annualIrrigationM3, annualGrossSavings, annualNetSavings, paybackYears: annualNetSavings > 0 ? (sale + installation) / annualNetSavings : null,
    simulated: true, elapsedDays };
}

export function buildReportData(sim) {
  return {
    title: 'مسودة توضيحية من بيانات محاكاة', status: 'SIMULATED',
    period: `نافذة محاكاة ${sim.config.days} أيام؛ المنقضي ${(sim.minute / MINUTES_PER_DAY).toFixed(2)} يوم. ليست قياسات ربع سنوية.`,
    metrics: getMetrics(sim), config: sim.config, economics: getEconomics(sim),
    faults: sim.events.filter(item => item.type === 'fault' || item.type === 'route' || item.type === 'diversion' || item.type === 'backwash').slice().reverse(),
    maintenance: sim.maintenance.slice(), calibrations: sim.calibrations.slice(),
    plannedLabs: ['العكارة وTSS وCOD في الخام وبعد المراحل وبأدوات معايرة.', 'pH والموصلية وفحوص الأملاح ومكونات مصدر المياه.', 'E. coli ومؤشرات ميكروبية مناسبة قبل UV وبعده ومع التخزين.', 'تحدي جرعة UV ونفاذية الماء والخلط والربط العكسي وفشل الصمام وفقد الطاقة.', 'رشح الوسط ومقارنة الفحم المرشح بالكربون التجاري واختبارات عمر الامتزاز.'],
    disclaimer: 'حدود تشغيل للمحاكاة قابلة للتعديل؛ لا شهادة مطابقة سعودية أو NSF لمورد. جميع تقديرات الكفاءة والاقتصاد تحتاج تحققًا ميدانيًا.'
  };
}
