/**
 * مورد | MAWRID — المصدر الوحيد لجميع الأبعاد الهندسية.
 * جميع المسافات بالمتر. 1 وحدة Three.js = 1 متر. الزوايا بالراديان.
 * المصدر الأساسي: جدول صاحب المشروع؛ القياسات الثانوية مقترحات رسم وليست رسومات تصنيع.
 */
export const unitSpec = {
  defaultPreset: 'M20',
  units: 'm',
  inch: 0.0254, // تحويل دولي دقيق: البوصة = 25.4 مم.
  disclaimer: 'تصور هندسي مقترح — الأبعاد تقريبية حسب مقاسات تجارية شائعة وتُثبت بالتصميم',
  presets: {
    M10: {
      capacity: 10, // م³/يوم — السعة الاسمية المطلوبة، وليست ضمان أداء.
      sand: { model: '1354', diameter: 0.330, height: 1.372 }, // جدول المستخدم؛ فئة 13×54 بوصة الاسمية.
      carbon: { model: '1465', diameter: 0.356, height: 1.651 }, // جدول المستخدم؛ فئة 14×65 بوصة الاسمية.
      valveHead: { height: 0.22 }, // رأس تجاري مقترح، من جدول المستخدم.
      balance: { capacity: 3, diameter: 1.55, height: 1.85 }, // جدول المستخدم؛ سعة خزان اسمية بالمتر المكعب.
      treated: { capacity: 1, length: 1.2, width: 1.0, height: 1.0 }, // جدول المستخدم؛ أبعاد خارجية تقريبية.
      uv: { diameter: 0.089, length: 0.95 }, // جدول المستخدم؛ فئة غلاف ستانلس 3.5 بوصة.
      skid: { length: 2.6, width: 1.3 }, // أبعاد قاعدة الهيكل حسب جدول المستخدم.
      pipe: { nominal: 'DN32', outerDiameter: 0.040 }, // جدول المستخدم؛ DN هو قطر اسمي وOD هو قطر الرسم.
    },
    M20: {
      capacity: 20, // م³/يوم — السعة الاسمية المطلوبة.
      sand: { model: '1665', diameter: 0.406, height: 1.651 }, // جدول المستخدم؛ فئة 16×65 بوصة الاسمية.
      carbon: { model: '1865', diameter: 0.457, height: 1.651 }, // جدول المستخدم؛ فئة 18×65 بوصة الاسمية.
      valveHead: { height: 0.22 }, // جدول المستخدم؛ رأس متعدد المنافذ مقترح.
      balance: { capacity: 5, diameter: 1.90, height: 2.00 }, // جدول المستخدم؛ الاسمية لا تساوي الحجم الهندسي الفارغ.
      treated: { capacity: 2, length: 1.6, width: 1.2, height: 1.15 }, // جدول المستخدم؛ أبعاد خارجية تقريبية.
      uv: { diameter: 0.089, length: 0.95 }, // جدول المستخدم.
      skid: { length: 3.0, width: 1.4 }, // جدول المستخدم.
      pipe: { nominal: 'DN32', outerDiameter: 0.040 }, // جدول المستخدم؛ UPVC بقطر خارجي 40 مم.
    },
    M30: {
      capacity: 30, // م³/يوم — السعة الاسمية المطلوبة.
      sand: { model: '2162', diameter: 0.533, height: 1.575 }, // جدول المستخدم؛ فئة 21×62 بوصة الاسمية.
      carbon: { model: '2162', diameter: 0.533, height: 1.575 }, // جدول المستخدم؛ فئة 21×62 بوصة الاسمية.
      valveHead: { height: 0.25 }, // جدول المستخدم.
      balance: { capacity: 8, diameter: 2.20, height: 2.35 }, // جدول المستخدم؛ سعة اسمية 8 م³.
      treated: { capacity: 3, length: 2.0, width: 1.3, height: 1.25 }, // جدول المستخدم.
      uv: { diameter: 0.114, length: 1.00 }, // جدول المستخدم؛ فئة غلاف 4.5 بوصة.
      skid: { length: 3.4, width: 1.6 }, // جدول المستخدم.
      pipe: { nominal: 'DN40', outerDiameter: 0.050 }, // جدول المستخدم؛ UPVC بقطر خارجي 50 مم.
    },
  },
  common: {
    pp: { diameter: 0.18, height: 0.62 }, // Jumbo 20 بوصة: الغلاف الخارجي المطلوب من المستخدم.
    pump: { length: 0.45, motorDiameter: 0.16 }, // مضختا التغذية والغسيل الأفقيتان: من المستخدم.
    submersible: { diameter: 0.18, height: 0.40 }, // المضخة الغاطسة: من المستخدم.
    irrigationPump: { length: 0.35, diameter: 0.15 }, // مضخة الري: من المستخدم.
    panel: { width: 0.60, height: 0.80, depth: 0.25, centerHeight: 1.50 }, // من المستخدم؛ ارتفاع المركز من منسوب الأرض.
    frame: { post: 0.060, height: 2.20, baseChannel: 0.100 }, // قطاعات الهيكل 60×60 مم وقناة 100 مم: من المستخدم.
    drain: { nominal: 'DN50', outerDiameter: 0.063 }, // من المستخدم؛ OD 63 مم، فلا يُستبدل بالقطر الاسمي 50 مم.
    chamber: { length: 1.20, width: 0.80, depth: 1.00, coverDiameter: 0.60 }, // حجرة التجميع ومنهلها: من المستخدم.
    opticalThickness: { peWhite: 0.12, peTreated: 0.10, pp: 0.025, acrylic: 0.05, quartz: 0.008 }, // سماكات بصرية تقريبية بالمتر للتصيير، وليست سماكات جدران التصنيع.
  },
  layout: {
    // تنسيق تصوري يتيح الوصول من خارج الهيكل؛ لا يمثل دراسة صيانة معتمدة.
    groundY: 0,
    equipmentBaseY: 0.09, // قاعدة المعدات منخفضة بين قناتي المحيط؛ يحافظ على رؤوس FRP تحت 2 م.
    serviceAisle: 0.70, // قيمة العرض الأولي؛ حدود الصيانة الملزمة التالية تحل محلها.
    service: { front: 0.90, ends: 0.60, rear: 0.30, headClearance: 0.50 }, // توجيه المستخدم اللاحق: أمام 0.9 م، نهايتان 0.6 م، خلف 0.3 م، فراغ علوي ≥0.5 م.
    tankGap: 0.75, tankSkidGap: 0.75, treatedSkidGap: 0.75, // ممر خدمة خارجي مقترح بين الخزانات والهيكل.
    chamberGap: 0.65, chamberTankGap: 0.65, // فصل تصوري يسمح بخط الرفع وصيانته.
    irrigationPumpOffset: 0.45, irrigationEndpointOffset: 1.3, irrigationEndZ: 1.2, dripHeight: 0.04, // مواضع مقترحة للمضخة وخط الري قرب الحوض.
    sandXFactor: -0.24, carbonXFactor: 0, frpZFactor: -0.13, // نسب بلا وحدة من طول/عرض الهيكل.
    ppXFactor: 0.23, ppBottomY: 0.75, ppZ: -0.16, // PP مرفوع على حامل تابع للهيكل.
    uvXFactor: 0.22, uvCenterY: 0.66, uvZFactor: 0.30, // مفاعل أفقي على سرجين؛ النسب بلا وحدة.
    analyzerXFactor: 0.38, analyzerCenterY: 0.97, analyzerZ: 0, // خلية تحقق على حامل.
    valveXFactor: 0.39, valveCenterY: 0.40, valveZFactor: 0.30, // صمامات القرار في الواجهة الأمامية.
    panelEdgeOffset: 0.03, // مركز اللوحة بمحاذاة عمود الحافة؛ مركز الارتفاع من common.panel.
    feedPumpXFactor: -0.35, backwashPumpXFactor: -0.17, pumpCenterY: 0.22, pumpZFactor: 0.30, // مواقع على أساسات عزل اهتزاز.
    drainZ: 1.15, rawInletReach: 0.60, feedMeterY: 0.52, // مناسيب ومواقع خطوط تصورية؛ تُثبت بمخطط التنفيذ.
    pipeLowY: 0.34, // مستوى خط سفلي مقترح أعلى الأرجل والصينية.
    processRailY: 1.02, // مستوى أفقي مقترح للأجهزة النهائية.
    cableTrayY: 2.20, // مجرى خلفي/جانبي فقط؛ لا يمر فوق أسطوانات FRP أو ضمن حيز رفع رؤوسها.
    pipeSupportInterval: 1.0, // دعم كل متر تقريبًا، كما طلب المستخدم.
    maximumHeadY: 2.0, // شرط ارتفاع أعلى الرأس من المستخدم.
    drainSlope: 0.02, // ميل تصوري 2% باتجاه نقطة الاستقبال؛ يُثبت هيدروليكيًا في التصميم.
  },
  detail: {
    // جميع القيم التالية تفاصيل تصور هندسي مقترحة قابلة للتعديل، وليست مقاسات شركة مصنّعة.
    shell: { frpWall: 0.008, peWall: 0.012, stainlessWall: 0.002, chamberWall: 0.070, acrylicWall: 0.008 },
    frame: { footDiameter: 0.10, footHeight: 0.025, footStem: 0.035, trayThickness: 0.004, trayLip: 0.025, liftingEyeDiameter: 0.075, liftingEyeTube: 0.012, forkOpeningWidth: 0.19, forkOpeningHeight: 0.07, forkSpacing: 0.70, crossmember: 0.05, gusset: 0.09 },
    serviceStep: { width: 0.65, depth: 0.28, height: 0.20, treadThickness: 0.025, legWidth: 0.025, hingeDiameter: 0.025, frontOffset: 0.05 }, // درجة خدمة قابلة للطي أمام المرشحات؛ أبعاد مقترحة من الصفر لتسهيل الوصول للرؤوس المرتفعة.
    frp: { baseHeight: 0.10, baseLip: 0.012, neckDiameter: 0.105, neckHeight: 0.06, shoulderHeight: 0.12, mediaClearance: 0.018, mediaBottomY: 0.16, standpipeDiameter: 0.032 },
    head: { bodyDiameter: 0.16, bodyHeight: 0.11, handleLength: 0.13, handleThickness: 0.018, nozzleLength: 0.085, portSpacing: 0.075 },
    balance: { capDiameter: 0.38, capHeight: 0.055, capTeethHeight: 0.012, ventDiameter: 0.05, ventHeight: 0.14, sampleHeight: 0.30, outletHeight: 0.18, overflowOffset: 0.15, ribWidth: 0.032, waterSurfaceMargin: 0.018 },
    treated: { cornerRadius: 0.06, capDiameter: 0.25, capHeight: 0.035, ribDepth: 0.025, inletOffset: 0.12, outletHeight: 0.15, warningWidth: 0.65, warningHeight: 0.20 },
    chamber: { baffleThickness: 0.035, baffleHeight: 0.68, baffleUnderflow: 0.12, basketWidth: 0.30, basketDepth: 0.28, basketHeight: 0.35, basketWire: 0.006, basketGrid: 0.035, coverThickness: 0.028, curb: 0.05, inletHeight: -0.25, overflowHeight: -0.16, waterHeight: -0.50, floatDiameter: 0.075, floatCable: 0.004 },
    pump: { footLength: 0.34, footWidth: 0.18, footHeight: 0.028, isolatorHeight: 0.02, isolatorDiameter: 0.045, centerHeight: 0.13, shaftDiameter: 0.02, finWidth: 0.008, finDepth: 0.018, fanDepth: 0.026, fanGuardDepth: 0.014, terminalWidth: 0.07, terminalHeight: 0.055 },
    pp: { capHeight: 0.08, capDiameter: 0.20, cartridgeDiameter: 0.115, cartridgeHeight: 0.508, pleatDepth: 0.007, bracketWidth: 0.24, bracketHeight: 0.18, bracketThickness: 0.004 },
    uv: { nozzleLength: 0.09, nozzleInset: 0.12, endCapDepth: 0.035, quartzDiameter: 0.035, lampDiameter: 0.018, lampEndClearance: 0.07, sensorDiameter: 0.028, sensorHeight: 0.055, ballastWidth: 0.25, ballastHeight: 0.12, ballastDepth: 0.08, supportHeight: 0.12 },
    analyzer: { width: 0.28, height: 0.13, depth: 0.10, probeDiameter: 0.018, probeLength: 0.16, probeSpacing: 0.055, supportWidth: 0.32, supportThickness: 0.004 },
    valve: { bodyLength: 0.10, bodyDiameter: 0.075, handleLength: 0.11, handleWidth: 0.02, handleHeight: 0.012, actuatorWidth: 0.14, actuatorHeight: 0.12, actuatorDepth: 0.10, springHousingDiameter: 0.065, indicatorDiameter: 0.035, returnTravel: 0.07 },
    instrument: { gaugeDiameter: 0.085, gaugeDepth: 0.022, gaugeStem: 0.045, pressureDiameter: 0.026, pressureLength: 0.065, flowLength: 0.14, flowBodyDiameter: 0.075, displayWidth: 0.075, displayHeight: 0.045, probeDiameter: 0.018, probeHeight: 0.10 },
    fittings: { unionLength: 0.04, unionExtraDiameter: 0.020, elbowRadius: 0.075, flangeThickness: 0.012, flangeExtraDiameter: 0.040, hoseDiameter: 0.012, sampleSpout: 0.08, drainAirGap: 0.14, drainReceptorDiameter: 0.14, drainReceptorHeight: 0.15, clampWidth: 0.018, clampWall: 0.004, bracketThickness: 0.006, supportBase: 0.07 },
    fasteners: { boltDiameter: 0.012, boltHeadHeight: 0.008, washerDiameter: 0.022, washerHeight: 0.002 },
    labels: { plateWidth: 0.16, plateHeight: 0.050, plateThickness: 0.002, dataWidth: 0.45, dataHeight: 0.13, pipeBandWidth: 0.08, pipeArrowLength: 0.06, surfaceGap: 0.003 },
    panel: { doorGap: 0.012, doorThickness: 0.018, hingeHeight: 0.07, screenWidth: 0.155, screenHeight: 0.087, screenDepth: 0.012, emergencyDiameter: 0.045, keyDiameter: 0.025, glandDiameter: 0.022, glandLength: 0.027, antennaHeight: 0.22, antennaDiameter: 0.014, beaconDiameter: 0.055, beaconSegmentHeight: 0.045, beaconStemHeight: 0.07, mountWidth: 0.08, mountDepth: 0.06 },
    cable: { diameter: 0.006, conduitDiameter: 0.025, trayWidth: 0.12, trayHeight: 0.06, trayThickness: 0.003, trayRungInterval: 0.20 },
    explode: { xOffset: 0.24, yOffset: 0.28, zOffset: 0.32, lineDash: 0.065, lineGap: 0.04 },
    particles: { radius: 0.012, spacing: 0.16 },
  },
  human: {
    // Hauteur de référence demandée : adulte stylisé de 1,75 m ; proportions artistiques anonymes.
    height: 1.75, headRadius: 0.115, torsoHeight: 0.52, torsoWidth: 0.40, torsoDepth: 0.19,
    neckHeight: 0.07, armLength: 0.54, armDiameter: 0.085, legLength: 0.82, legDiameter: 0.12,
    footLength: 0.23, footHeight: 0.06, footWidth: 0.105, stanceWidth: 0.21,
  },
  site: {
    // أبعاد بيئة معمارية تخيلية وليست مخطط موقع حقيقي.
    wallX: -3.5, screenX: 4.4, planterX: 5.0, planterZ: -2.7, studioBackZ: -16,
    palmLeafWidth: 0.19, palmTrunkRing: 0.065,
    groundLength: 26, groundWidth: 18, slabThickness: 0.12, paverSize: 0.60, paverJoint: 0.008,
    wallLength: 12, wallHeight: 2.7, wallThickness: 0.20, wallZ: -3.8,
    washBenchHeight: 0.43, washBenchDepth: 0.45, washTroughWidth: 0.50, washTroughHeight: 0.28,
    tapHeight: 0.85, tapSpacing: 0.85, tapDiameter: 0.023, tapProjection: 0.18,
    screenWidth: 3.0, screenHeight: 2.3, screenDepth: 0.07, screenOpening: 0.30, screenBar: 0.025,
    planterLength: 7.8, planterWidth: 1.25, planterHeight: 0.40, planterWall: 0.08,
    palmHeight: 3.7, palmTrunkDiameter: 0.20, palmCrownRadius: 1.5, palmLeafLength: 1.7,
    shrubHeight: 0.45, shrubRadius: 0.30, dripDiameter: 0.016, dripSpacing: 0.35,
    studioLength: 160, studioWidth: 24, cycloramaRadius: 4.0, cycloramaHeight: 50, // عرض/ارتفاع استوديو تصوري ممتد لمنع ظهور حد الخلفية في زوايا الكاميرا؛ بداية الانحناء عند z=-12 تطابق حافة الأرضية.
    cutawayMargin: 0.12, drainTerminalWidth: 0.35, drainTerminalDepth: 0.35, drainTerminalHeight: 0.18,
  },
  camera: {
    // Distances de caméra proposées en mètres ; focales et pixels ci-dessous ne sont pas des dimensions physiques.
    near: 0.05, far: 120, minDistance: 1.2, maxDistance: 24,
    overview: { x: 3.5, y: 3.7, z: 11.4 }, target: { x: 0, y: 0.90, z: 0 },
    train: { x: 2.8, y: 2.2, z: 5.1 }, panel: { x: 2.3, y: 1.8, z: 2.0 },
    valves: { x: 3.7, y: 1.8, z: 2.7 }, collection: { x: -6.2, y: 1.5, z: 3.3 },
    fov: 38,
  },
  rendering: {
    // Paramètres sans unité, pixels, secondes ou angles ; jamais des distances physiques.
    desktopShadow: 4096, mobileShadow: 2048, desktopPixelRatio: 2, mobilePixelRatio: 1.25,
    exportWidth: 3840, exportHeight: 2160, mobileBreakpoint: 760,
    transitionSeconds: 0.75, presetTransitionSeconds: 0.9, targetDesktopFPS: 60, targetMobileFPS: 30,
  },
  constraints: [
    'قاعدة أسطوانات FRP على منسوب 0.09 م، محمولة داخل قنوات المحيط؛ أعلى رأس M20 عند 1.961 م.',
    'صينية التسرب غائرة داخل الإطار؛ يجب تثبيت تفاصيل الأحمال والعزل ومنع التصادم في التصميم الإنشائي.',
    'خلوص الخدمة: 0.90 م أمامًا، 0.60 م عند كل نهاية، 0.30 م خلفًا؛ الوصول التشغيلي من الواجهة الأمامية.',
    'خلوص صيانة لا يقل عن 0.50 م فوق رؤوس المرشحات؛ مجرى الكابلات خلفي أو جانبي ولا يمر فوق الأسطوانات.',
    'الصمامات والمانومترات ونقاط العينات ولوحة التحكم تواجه الأمام؛ درجة خدمة قابلة للطي أمام المرشحات.',
    'السعات اسمية والأبعاد الخارجية تقريبية؛ أداء المعالجة والجرعات والحدود التشغيلية تُثبت بالحساب والاختبار.',
  ],
};

export function resolveSpec(preset = unitSpec.defaultPreset) {
  const key = Object.hasOwn(unitSpec.presets, preset) ? preset : unitSpec.defaultPreset;
  const p = unitSpec.presets[key];
  const l = unitSpec.layout;
  const balanceX = -p.skid.length / 2 - l.tankGap - p.balance.diameter / 2;
  const chamberX = balanceX - p.balance.diameter / 2 - l.chamberGap - unitSpec.common.chamber.length / 2;
  const treatedX = p.skid.length / 2 + l.tankGap + p.treated.length / 2;
  return {
    key,
    ...p,
    common: unitSpec.common,
    layout: unitSpec.layout,
    detail: unitSpec.detail,
    site: unitSpec.site,
    human: unitSpec.human,
    camera: unitSpec.camera,
    rendering: unitSpec.rendering,
    disclaimer: unitSpec.disclaimer,
    constraints: unitSpec.constraints,
    positions: {
      balance: { x: balanceX, y: l.groundY, z: 0 },
      chamber: { x: chamberX, y: l.groundY, z: 0 },
      treated: { x: treatedX, y: l.groundY, z: 0 },
      sand: { x: p.skid.length * l.sandXFactor, y: l.equipmentBaseY, z: p.skid.width * l.frpZFactor },
      carbon: { x: p.skid.length * l.carbonXFactor, y: l.equipmentBaseY, z: p.skid.width * l.frpZFactor },
      pp: { x: p.skid.length * l.ppXFactor, y: l.ppBottomY, z: l.ppZ },
      uv: { x: p.skid.length * l.uvXFactor, y: l.uvCenterY, z: p.skid.width * l.uvZFactor },
      analyzer: { x: p.skid.length * l.analyzerXFactor, y: l.analyzerCenterY, z: l.analyzerZ },
      valve: { x: p.skid.length * l.valveXFactor, y: l.valveCenterY, z: p.skid.width * l.valveZFactor },
      panel: { x: p.skid.length / 2 - l.panelEdgeOffset, y: unitSpec.common.panel.centerHeight, z: -p.skid.width / 2 },
      feedPump: { x: p.skid.length * l.feedPumpXFactor, y: l.pumpCenterY, z: p.skid.width * l.pumpZFactor },
      backwashPump: { x: p.skid.length * l.feedPumpXFactor + unitSpec.common.pump.length + unitSpec.detail.fittings.elbowRadius * 2, y: l.pumpCenterY, z: p.skid.width * l.pumpZFactor },
    },
  };
}
