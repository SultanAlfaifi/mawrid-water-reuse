# سجل التغييرات · Changelog

## v0.3.0 — 18 أكتوبر 2026 / 18 October 2026

هذه نسخة من النموذج البرمجي والبحث، وليست إصدار تشغيل ميداني أو نتيجة أداء معالجة مياه. تبقى الأدلة التاريخية مقيدة بإصداراتها وبصماتها ونطاق الاختبار.

### العربية

- **تشغيل واضح من نسخة المستودع:** أصبح مسار المحطة الافتراضية يعمل بـPython 3.10+ ومكتبته القياسية، مع مشغل يختار المفسر ويتحقق من إصداره. الواجهة والخطوط والمشهد التشغيلي والعرض الهندسي `/viewer/` مرفقة بأصول مجمعة؛ لا يلزم Node.js أو تنزيل نموذج ML لتجربة المحطة.
- **رحلة ماء تشرح نفسها:** يضيف UX V8 عرضًا تلقائيًا لثماني مراحل، في نحو 3 دقائق و20 ثانية. تضيء معدات المرحلة ومسارها وتقترب الكاميرا، ثم تبدأ مهلة قراءة 21–27 ثانية للنص الحالي. الإيقاف والمتابعة يحفظان المرحلة والوقت المتبقي؛ التفاصيل والتحكم اليدوي والانقطاع توقف العرض حتى متابعة صريحة. النهاية لا تحقن عطلًا تلقائيًا.
- **تتبع التشغيل ومصدر البيانات:** خدمة HTTP محلية، وسجل SQLite، وتصدير القراءات والأحداث، وجامع API/edge بطابور دائم وإيصالات وهوية قياس ثابتة لإعادة المحاولة. اختبارات النقل والمحاكاة تستخدم بيانات موسومة؛ لا تثبت اتصال حساس أو صمام مادي.
- **نتائج ML كما هي:** V9 لإعادة عرض بحثية مؤهلة فقط: 113/399 حدثًا، و237 مقطع إنذار كاذب و478 دقيقة كاذبة في التقييم التطويري ذي الفترات الـ19. انتهت سياسة V15 إلى V8 دون تعديل: 117/399، و235 مقطعًا كاذبًا و475 دقيقة. لم تُرقَّ V15، ولم يبدأ تدريب V16؛ هدف خفض الإنذارات مع الاحتفاظ بكل الأحداث لم يتحقق. لا يعمل ML على ماء التوأم أو مخطط قراءات الجهاز، ولا يفتح المخرج.
- **تسليم البحث منفصل:** تبقى الشيفرة والتقارير المنتقاة في Git، وتُرفق حزمة البحث الاختيارية لـV9 في GitHub Release بدل إدخال النماذج والبيانات الكبيرة في تاريخ Git. مصادر البيانات وتراخيصها وخطوات التثبيت والتحقق موضحة في [أصول البحث](docs/research-assets.md).
- **عرض وتوثيق قابلان للمراجعة:** فصل الموقع الثابت على GitHub Pages عن خدمة `127.0.0.1:8787` المحلية، وتحديث [خريطة المخرجات التسعة](docs/judging-map.md)، وأدلة التحقق، وتعليمات البناء والمساهمة، و[الفحوص الآلية](.github/workflows/verify.yml). Pages لا يستضيف Python أو قاعدة جهاز المشغل.

### English

- **Runnable local clone:** the virtual plant uses Python 3.10+ and its standard library. The launcher selects and checks the interpreter. Bundled UI, fonts, operational 3D and `/viewer/` assets remove the need for Node.js or an ML download when using the virtual plant.
- **Guided UX V8:** an explicit eight-stage automatic water journey takes about 3 minutes 20 seconds. Equipment and pipes are highlighted, the camera moves closer, then the current text receives 21–27 seconds of reading time. Pause/resume preserves progress and remaining time; interruptions require explicit continuation. Completion does not inject a fault.
- **Traceable local operation:** HTTP API, SQLite history, exports and an API/edge collector with a persistent queue, receipts and stable measurement identities. Software transport checks and simulated records do not establish physical sensor or actuator operation.
- **Unchanged research outcomes:** research-only V9 detected 113/399 events with 237 false-alarm fragments and 478 false-alarm minutes across 19 development periods. V15 retained V8 unchanged: 117/399, 235 fragments and 475 minutes; it was not promoted. V16 training has not started. The retain-all-events/reduce-false-alarms objective remains unmet. ML is unavailable for virtual-plant water and the device schema, and cannot authorize outlet opening.
- **Optional research release asset:** selected code and reports live in Git; the optional V9 research bundle is distributed through GitHub Releases rather than storing large models/data in Git history. Follow the [research-assets guide](docs/research-assets.md) for sources, licenses, installation and verification.
- **Reviewable delivery:** documentation separates the static public Pages site from the loopback Python service, maps the nine submission outputs and records scoped verification. [CI](.github/workflows/verify.yml) checks software; it does not establish treatment efficacy, field readiness or production readiness.

[Project scope](docs/project-brief.md) · [Model card](docs/data-and-model-card.md) · [Evidence](docs/evidence-register.md) · [Development](docs/development.md)
