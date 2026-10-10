// Published evidence informs the candidate material; none of these are MAWRID test results.
// Organization names identify authors' institutions or the publication, never project partners.
export const RESEARCH_SOURCES = [
  {
    id: 'kaust-palm-soil-2024',
    organization: 'King Abdullah University of Science and Technology (KAUST)',
    logoUrl: new URL('../../assets/research/kaust.svg', import.meta.url).href,
    logoPath: 'assets/research/kaust.svg',
    logoKind: 'institution',
    logoAlt: { ar: 'شعار كاوست، جهة انتماء مؤلفين في الدراسة', en: 'KAUST logo, a research-author affiliation' },
    title: {
      ar: 'فحم أوراق النخيل وتحسين التربة الرملية ونمو المورينجا',
      en: 'Date-palm biochar, sandy soil and Moringa growth',
    },
    url: 'https://doi.org/10.3389/fpls.2024.1434462',
    material: {
      ar: 'فحم أوراق نخيل محمّل بالمغذيات، مع تغطية رملية طاردة للماء.',
      en: 'Nutrient-loaded date-palm-leaf biochar and superhydrophobic sand mulch.',
    },
    supports: {
      ar: 'يوثّق تحويل أوراق نخيل إلى فحم واختباره لتحسين نمو النبات واستخدام ماء الري في التربة.',
      en: 'Documents palm-leaf conversion into biochar and tests plant growth and irrigation use in soil.',
    },
    limits: {
      ar: 'دراسة تربة؛ لا تختبر تنقية مياه الوضوء أو طبقة مرشح مورد.',
      en: 'A soil study; it does not test ablution-water purification or MAWRID filtration.',
    },
    category: { ar: 'دراسة تربة', en: 'Soil study' },
    researchType: 'biochar',
  },
  {
    id: 'khalifa-palm-column-2023',
    organization: 'Khalifa University',
    logoUrl: new URL('../../assets/research/khalifa-university.png', import.meta.url).href,
    logoPath: 'assets/research/khalifa-university.png',
    logoKind: 'institution',
    logoAlt: { ar: 'شعار جامعة خليفة، جهة مؤلفي الدراسة', en: 'Khalifa University logo, the authors’ institution' },
    title: {
      ar: 'فحم مخلفات النخيل وامتزاز مكونات غير عضوية في أعمدة معالجة',
      en: 'Date-palm biochar adsorption in packed columns',
    },
    url: 'https://doi.org/10.1007/s13369-022-07472-3',
    material: {
      ar: 'فحم مشتق من مخلفات نخيل، في أعمدة امتزاز ومياه جوفية محضّرة للتجربة.',
      en: 'Date-palm-waste biochar in adsorption columns and synthetic groundwater.',
    },
    supports: {
      ar: 'دليل تجريبي على امتزاز أيونات محددة، وتأثر الأداء بالتدفق وتركيز الداخل وارتفاع طبقة الوسط.',
      en: 'Experimental evidence of selected-ion adsorption and effects of flow, inlet concentration and bed height.',
    },
    limits: {
      ar: 'نوع الماء والملوثات مختلف؛ لا يثبت تعقيمًا أو أداء مورد أو صلاحية مياهه للشرب.',
      en: 'Different water and contaminants; no proof of disinfection, MAWRID performance or drinking-water suitability.',
    },
    category: { ar: 'تجربة امتزاز', en: 'Adsorption experiment' },
    researchType: 'biochar',
  },
  {
    id: 'qatar-palm-review-2026',
    organization: 'Qatar University',
    logoUrl: new URL('../../assets/research/qatar-university.png', import.meta.url).href,
    logoPath: 'assets/research/qatar-university.png',
    logoKind: 'institution',
    logoAlt: { ar: 'شعار جامعة قطر، أحد انتماءات مؤلفي المراجعة', en: 'Qatar University logo, one affiliation in the review' },
    title: {
      ar: 'مراجعة فحم مخلفات النخيل لامتزاز مركبات دوائية',
      en: 'Review of date-palm biochar for pharmaceutical adsorption',
    },
    url: 'https://doi.org/10.1186/s12302-026-01333-8',
    material: {
      ar: 'أنواع مختلفة من فحم مخلفات النخيل، بطرق تحضير وتنشيط متعددة.',
      en: 'Date-palm-waste biochars with different preparation and activation routes.',
    },
    supports: {
      ar: 'توضح أن المادة وطريقة التحضير ونوع الملوث والماء تحدد كفاءة الامتزاز.',
      en: 'Shows that feedstock, preparation, contaminant and water matrix determine adsorption performance.',
    },
    limits: {
      ar: 'مراجعة لأبحاث منشورة بمشاركة جهات أخرى؛ لا تقدم اختبارًا جديدًا لمياه مورد أو سعرًا محليًا.',
      en: 'A multi-institution literature review; no new MAWRID-water test or local price.',
    },
    category: { ar: 'مراجعة علمية', en: 'Literature review' },
    researchType: 'biochar',
  },
  {
    id: 'riyadh-raw-fiber-2024',
    organization: 'Desalination and Water Treatment',
    logoUrl: new URL('../../assets/research/elsevier.svg', import.meta.url).href,
    logoPath: 'assets/research/elsevier.svg',
    logoKind: 'publisher',
    logoAlt: { ar: 'شعار Elsevier، ناشر دراسة المجلة', en: 'Elsevier logo, the article publisher' },
    title: {
      ar: 'مرشح ألياف نخيل خام لمياه وضوء من مساجد الرياض',
      en: 'Raw date-palm-fibre filtration of Riyadh ablution water',
    },
    url: 'https://doi.org/10.1016/j.dwt.2024.100163',
    material: {
      ar: 'ألياف نخيل خام بسماكات مختلفة، وليست فحمًا حيويًا.',
      en: 'Raw date-palm fibres at different thicknesses, not biochar.',
    },
    supports: {
      ar: 'اختبرت الدراسة عينات من 24 مسجدًا، ورصدت انخفاض العكارة وبعض المؤشرات الفيزيائية والكيميائية.',
      en: 'Tested samples from 24 mosques and reported reductions in turbidity and selected physicochemical indicators.',
    },
    limits: {
      ar: 'الدليل يخص الألياف الخام؛ لا ينقل إلى الفحم، ولا يثبت السلامة الميكروبية أو أداء مورد.',
      en: 'Evidence concerns raw fibres; it does not establish biochar behaviour, microbial safety or MAWRID performance.',
    },
    category: { ar: 'دراسة ألياف خام', en: 'Raw-fibre study' },
    researchType: 'raw-fiber',
  },
  {
    id: 'kearns-wood-uva-2021',
    organization: 'Environmental Engineering Science',
    logoUrl: new URL('../../assets/research/sage.png', import.meta.url).href,
    logoPath: 'assets/research/sage.png',
    logoKind: 'publisher',
    logoAlt: { ar: 'شعار Sage، هوية منصة النشر الحالية للمجلة', en: 'Sage logo, the journal’s current publishing identity' },
    title: {
      ar: 'مراقبة عمر امتزاز الفحم بمؤشر UVA254',
      en: 'UVA254 monitoring of biochar adsorption life',
    },
    url: 'https://doi.org/10.1089/ees.2020.0173',
    material: {
      ar: 'فحم خشبي، وماء من مصادر مختلفة، وأعمدة مختبرية مع كربون تجاري للمقارنة.',
      en: 'Wood-derived biochars, different water matrices and laboratory columns with a commercial-carbon comparator.',
    },
    supports: {
      ar: 'تدرس العلاقة بين مؤشر امتصاص الأشعة فوق البنفسجية واختراق مركبات عضوية محددة لطبقة الامتزاز.',
      en: 'Studies relationships between UV absorbance and breakthrough of selected organic micropollutants.',
    },
    limits: {
      ar: 'مادة مختلفة عن فحم النخيل؛ المؤشر لا يكشف مسببات المرض ولا يعتمد جودة مياه مورد.',
      en: 'Different feedstock from palm biochar; the surrogate neither detects pathogens nor certifies MAWRID water.',
    },
    category: { ar: 'دراسة مراقبة امتزاز', en: 'Adsorption-monitoring study' },
    researchType: 'biochar',
  },
  {
    id: 'fang-field-review-2025',
    organization: 'U.S. Environmental Protection Agency · University of Florida',
    logoUrl: new URL('../../assets/research/university-of-florida.png', import.meta.url).href,
    logoPath: 'assets/research/university-of-florida.png',
    logoKind: 'institution',
    logoAlt: { ar: 'شعار جامعة فلوريدا، أحد انتماءات مؤلفي المراجعة', en: 'University of Florida logo, one affiliation in the review' },
    title: {
      ar: 'الفحم الحيوي في تطبيقات معالجة مياه واقعية',
      en: 'Biochar in realistic water-remediation applications',
    },
    url: 'https://doi.org/10.1016/j.jenvman.2025.125524',
    material: {
      ar: 'أنواع فحم حيوي وتقنيات معالجة مختلفة في دراسات تجريبية وميدانية.',
      en: 'Different biochars and treatment technologies in pilot and field studies.',
    },
    supports: {
      ar: 'توضح فرص التطبيق الواقعي وفجوات التوسع والجودة؛ الأداء يعتمد على الملوث والمادة والتقنية.',
      en: 'Reviews practical potential and scale-up and quality gaps; performance depends on contaminant, material and technology.',
    },
    limits: {
      ar: 'لا يتفوق الفحم دائمًا على الكربون المنشط، ولا تثبت المراجعة عمر خدمة أو كلفة لمورد.',
      en: 'Biochar does not always outperform activated carbon; the review establishes no MAWRID service life or cost.',
    },
    category: { ar: 'مراجعة تطبيقات واقعية', en: 'Field-application review' },
    researchType: 'biochar',
  },
  {
    id: 'alsawy-regeneration-review-2022',
    organization: 'npj Clean Water',
    logoUrl: new URL('../../assets/research/springer-nature.svg', import.meta.url).href,
    logoPath: 'assets/research/springer-nature.svg',
    logoKind: 'publisher',
    logoAlt: { ar: 'شعار Springer Nature، هوية ناشر npj Clean Water', en: 'Springer Nature logo, publisher identity for npj Clean Water' },
    title: {
      ar: 'مراجعة التجديد الكيميائي لوسط الفحم الحيوي',
      en: 'Review of chemical biochar regeneration',
    },
    url: 'https://doi.org/10.1038/s41545-022-00172-3',
    material: {
      ar: 'فحم حيوي استُخدم لامتزاز ملوثات عضوية وغير عضوية، وطرق تجديد كيميائي.',
      en: 'Biochars loaded with organic or inorganic pollutants and chemical regeneration methods.',
    },
    supports: {
      ar: 'تربط إمكانية التجديد بطبيعة الامتزاز وتغير الوسط، وتناقش إدارة التلوث الثانوي.',
      en: 'Links regeneration to adsorption mechanisms and media changes, and discusses secondary-pollution management.',
    },
    limits: {
      ar: 'التجديد ليس مضمونًا؛ لا يبرر وضع الوسط المستهلك في التربة أو ادعاء اقتصاد دائري مكتمل.',
      en: 'Regeneration is not guaranteed; no basis for applying spent media to soil or claiming a closed circular system.',
    },
    category: { ar: 'مراجعة تجديد الوسط', en: 'Media-regeneration review' },
    researchType: 'biochar',
  },
  {
    id: 'gastat-palm-base-2024',
    organization: 'General Authority for Statistics (GASTAT)',
    logoUrl: new URL('../../assets/research/gastat.svg', import.meta.url).href,
    logoPath: 'assets/research/gastat.svg',
    logoKind: 'statistics',
    logoAlt: { ar: 'شعار الهيئة العامة للإحصاء، مصدر الإحصاء الرسمي', en: 'GASTAT logo, the official statistical source' },
    title: {
      ar: 'الإحصاءات الزراعية السعودية 2024',
      en: 'Saudi agricultural statistics 2024',
    },
    url: 'https://www.stats.gov.sa/en/w/news/127',
    material: {
      ar: 'إحصاء قطاع النخيل؛ ليس دراسة وسط ترشيح.',
      en: 'Palm-sector statistics, not a filtration-media study.',
    },
    supports: {
      ar: 'أكثر من 37.6 مليون نخلة في المملكة خلال 2024: قاعدة محلية كبيرة لدراسة سلسلة توريد المخلفات.',
      en: 'Over 37.6 million palms in Saudi Arabia in 2024: a substantial base for a residue-supply study.',
    },
    limits: {
      ar: 'عدد النخيل لا يحدد كمية المخلفات القابلة للجمع أو سعر الفحم أو مردود التصنيع.',
      en: 'Palm counts do not establish collectable residue volume, biochar price or manufacturing yield.',
    },
    category: { ar: 'إحصاء رسمي', en: 'Official statistics' },
    researchType: 'general',
  },
];
