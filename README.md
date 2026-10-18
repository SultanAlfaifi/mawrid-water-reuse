![مورد — مياه الوضوء، مورد للري](assets/brand/readme-cover.png)

# مورد · MAWRID

**مياه الوضوء، مورد للري. لا لتر بلا تحقق.**

[![Verify](https://github.com/SultanAlfaifi/mawrid-water-reuse/actions/workflows/verify.yml/badge.svg)](https://github.com/SultanAlfaifi/mawrid-water-reuse/actions/workflows/verify.yml)

**v0.3.0 · 18 أكتوبر 2026:** نموذج برمجي محلي قابل للتشغيل، وموقع توضيحي عام، وبحث على بيانات عامة. ليست هذه نسخة تشغيل ميداني أو إثبات أداء معالجة مياه. **Status:** local software prototype and public-data research. [سجل التغييرات · Changelog](CHANGELOG.md) · [التحقق الآلي · CI](.github/workflows/verify.yml).

مورد مشروع لاسترجاع مياه الوضوء والمغاسل المفصولة للاستخدام في ري مساحات خضراء محددة. يجمع تصور محطة معالجة، وطبقة حساسات وتحكم، وتجربة رقمية تشرح مسار الماء وتوثق مصدر كل قراءة. له مساران مقترحان: **وحدة كاملة** و**صندوق لتحديث محطة قائمة**.

MAWRID explores source-separated ablution and washbasin water reuse for landscape irrigation. This repository contains the project story, a working local software prototype, public-data anomaly-detection research and evidence of the checks actually performed. It does not establish physical treatment performance or field readiness.

[الموقع العام · Website](https://sultalfaifi.com/mawrid-water-reuse/) · [تعريف المشروع · Project brief](docs/project-brief.md) · [دليل التطوير · Development](docs/development.md) · [الأدلة · Evidence](docs/evidence-register.md) · [المساهمة · Contributing](CONTRIBUTING.md)

## ابدأ من هنا · Choose an experience

| المطلوب | الوجهة | ما الذي يعمل فيها؟ |
|---|---|---|
| فهم الفكرة ومراجعة الوثائق | [الموقع العام](https://sultalfaifi.com/mawrid-water-reuse/) | موقع ثابت بالعربية والإنجليزية، مع محاكي تعليمي مستقل |
| تجربة تشغيل المحطة ورحلة الماء | [النظام المحلي](mawrid-system/README.md) | خدمة Python/SQLite وتوأم افتراضي ومجسم مرتبط بحالة المحاكاة؛ يعمل على جهازك |
| مراجعة الذكاء والنتائج | [بطاقة البيانات والنموذج](docs/data-and-model-card.md) | بروتوكولات ومقارنات وحدود بحث البيانات العامة |
| مراجعة متطلبات العرض | [خريطة المخرجات التسعة](docs/judging-map.md) | الدليل الموجود والنقص والخطوة التالية لكل مخرج |

الموقع العام لا يشغّل خادم Python أو مختبر ML. العناوين `127.0.0.1` تخص الجهاز الذي يشغل الخدمة؛ رفع المستودع لا يحول النظام المحلي إلى خدمة عامة.

## تشغيل النظام المحلي · Local application

يلزم **Python 3.10 أو أحدث**. من جذر المستودع:

```sh
./mawrid-system/start.command
```

افتح [http://127.0.0.1:8787/#start](http://127.0.0.1:8787/#start)، ثم **«جرّب المحطة» → «تشغيل وعرض تلقائي»**. إذا كانت المحاكاة تعمل بالفعل يظهر الزر باسم «ابدأ العرض التلقائي». أوقف الخدمة بـ`Ctrl+C`. على الأنظمة التي لا تشغّل ملف `.command` استخدم `python3 -B mawrid-system/server/main.py`. تُحفظ السجلات محليًا في `mawrid-system/var/` ولا تُنشر إلى Git.

تأتي الواجهة ومشهد 3D والعرض الهندسي `/viewer/` بأصولها المجمعة؛ التجربة الافتراضية لا تحتاج Node.js أو تثبيت حزم Python أو تشغيل تدريب أو اتصالًا بعتاد. يختار المشغل `MAWRID_PYTHON` إن حددته، ثم بيئة البحث الموجودة إن توفرت، ثم `python3`، ويتحقق من الإصدار. مختبر الذكاء اختياري منفصل، ويتطلب بيانات وحزمة نموذج موثوقة وتبعيات مؤهلة؛ غيابها يظهر كحالة عدم إتاحة ولا يتحول إلى تنبؤ مصطنع. راجع [دليل النظام](mawrid-system/README.md) و[دليل التطوير](docs/development.md) للتفاصيل.

**Local use:** run the command above, open the loopback address and choose the virtual plant. Python's standard library is sufficient for that mode. The optional research replay has additional data/model requirements and is not enabled by installing the website dependencies.

## رحلة الماء التلقائية · Automatic water journey

تشرح UX V8 ثماني مراحل، من التجميع إلى الري، في نحو **3 دقائق و20 ثانية**. تضيء معدات المرحلة وخطها، وتقرّب الكاميرا، ثم تمنح القارئ **21–27 ثانية** لكل شرح في النص الحالي. زر الإيقاف والمتابعة يحفظ المرحلة ووقت القراءة المتبقي.

فتح التفاصيل، أو تحريك الكاميرا يدويًا، أو مغادرة التبويب، أو انقطاع الخدمة يوقف العرض حتى متابعة صريحة. **إيقاف العرض** منفصل عن **إيقاف المحاكاة**. تنتهي الجولة دون حقن عطل أو إعادة تلقائية؛ تجربة العطل إجراء اختياري واضح.

[دليل تحقق UX V8](output/mawrid-system/ux-v8/verification.json) يسجل 68 مجموعة واجهة، و8 مجموعات توقيت، و22 حالة تشغيل، و5 حالات تقدم رحلة، و31 اختبار مجسم وكاميرا، وفحص متصفح للرحلة كاملة ولعرض جوال ومكتبي. هذا تحقق وظيفي محدد، وليس دراسة استخدام مع جميع فئات المحكمين أو شهادة إتاحة.

## الحالة والحدود · What exists today

| الجزء | الحالة التي يدعمها الدليل |
|---|---|
| الموقع والنظام المحلي | برمجيات وتجربة رقمية عاملة؛ ليست محطة مائية منفذة |
| التوأم الرقمي | أحجام وتدفقات ومعدات وقواعد تجريبية وحالات عطل، مع سجل SQLite وتصدير موسوم بالمصدر |
| مرجع المحطة | تصميم 1,000 لتر/ساعة، و15 م³/يوم عند 15 ساعة، وخزانان 5 م³؛ ليست سعة معالجة مثبتة |
| المعالجة | كربون تجاري في الأساس، أربع نقاط جرعات، وUV اختياري؛ لا حساب كفاءة كيميائية أو ميكروبية في التوأم |
| مواد النخيل | دراسة إحلال مستقبلية تحتاج مقارنة الأداء والنضّ والعمر والتكلفة؛ ليست وسطًا مثبتًا |
| الذكاء | V9 لإعادة عرض بحثية محدودة على بيانات عامة مؤهلة؛ ML غير متاح لماء التوأم ومخطط قراءات الجهاز |
| العتاد والموقع | لا مشغل مادي متصل، أو نتائج مياه ميدانية، أو شراكة جامعة، أو اعتماد موثق |

يحدد [مرجع المشروع](docs/project-brief.md) مواصفات النسخة الحالية ويحل تعارضها مع افتراضات الدراسة السابقة. تميّز [خطة التحقق](docs/validation.md) بين نجاح البرمجيات، وتقييم النموذج، واختبار المتحكم والصمام، والتحقق من الماء.

**AI evidence:** the connected model is research-only V9. Preserving every previously detected event while reducing false alarms has not been achieved. The completed V15 policy experiment retained V8 unchanged in all 19 periods: **117/399 events, 235 false alarm fragments and 475 false alarm minutes**. It was not promoted. V16 preparation tests are not training results. See the [model card](docs/data-and-model-card.md) for exact protocols and limitations; no five-fault classifier, calibrated sensor-trust probability or Raspberry Pi timing has been established. AI cannot authorize opening the reuse outlet.

تُنشر شيفرة البحث والتقارير المنتقاة مع حدودها. البيانات وحزم الاستدلال لا تدخل تثبيت الموقع؛ يوضح [دليل أصول البحث](docs/research-assets.md) الحصول على المصادر العامة وتثبيت حزمة V9 الاختيارية المخصصة لإصدار **v0.3.0** والتحقق منها.

## تطوير الموقع العام · Public-site development

يلزم **Node.js 22.12 أو أحدث** وnpm. من الجذر:

```sh
npm ci
npm run dev
```

افتح [http://127.0.0.1:4173](http://127.0.0.1:4173) أو [المحاكي التعليمي](http://127.0.0.1:4173/simulator/). على PowerShell يمكن استخدام `npm.cmd`.

```sh
npm run check
npm run build
```

`check` يفحص قواعد المحاكي الثابت. `build` يولد الموقع في `index.html` و`simulator/index.html` و`assets/app/` من مصدر `web/`؛ لا يبني واجهة النظام المحلي ولا ينشر إلى GitHub. أوامر اختبارات النظام المحلي وبناء حزمته منفصلة في [دليل التطوير](docs/development.md).

| المسار | الدور |
|---|---|
| `web/` | مصدر الموقع العام والمحاكي التعليمي |
| `mawrid-system/` | الخدمة المحلية، التوأم، الواجهة، جامع القراءات ومصدر المشهد التشغيلي |
| `mawrid-final/` | مصدر العرض الهندسي وأدوات بناء مشتركة؛ يظل منفصلًا عن التحكم |
| `ml/` | شيفرة البحث والبروتوكولات؛ البيانات والحزم غير المصرح بتوزيعها ليست جزءًا من تثبيت الموقع |
| `docs/`, `references/`, `data/` | تعريف المشروع والأدلة والمصادر ومخططات البيانات والأمثلة الموسومة |
| `assets/` | هوية وخطوط محلية وصور مفاهيمية ورسوم |
| `output/` | أدلة ومخرجات منتقاة وفق نطاق كل تقرير؛ ليست بيانات تشغيل ميدانية |

## مواءمة التسليم · Submission evidence

تطابق [خريطة المخرجات](docs/judging-map.md) التسعة مخرجات الموثقة: الفريق، المشكلة، الحل والابتكار، العميل والقيمة، خطة النموذج ومؤشراته، المخطط والمكونات، التنفيذ والاحتياجات، الجدوى والتوسع والأثر، والملخص في صفحة.

العرض الرقمي يدعم شرح المشروع؛ لا يعوض بيانات الفريق أو قياس المصدر والطلب أو مقابلات العميل أو عروض الأسعار أو نتائج المعالجة. تحفظ جهات الاتصال والموافقات والمرفقات الخاصة في حزمة تسليم خاصة. لا يفترض المستودع موعدًا أو أوزانًا أو درجات تحكيم غير موثقة.

[تصميم النظام](docs/system-design.md) · [التحقق](docs/validation.md) · [الأثر والتكلفة](docs/impact-and-economics.md) · [المراجع](references/README.md) · [الهوية](assets/brand/README.md)

## الترخيص والإسناد · Licensing and attribution

[MIT](LICENSE) applies to project software and documentation subject to existing third-party rights. Fonts retain their SIL Open Font License notices: [IBM Plex Sans Arabic](assets/fonts/LICENSE-plex-arabic.txt) and [Manrope](assets/fonts/LICENSE-manrope.txt). Dataset, library, publication and logo rights remain with their owners; citation does not imply a redistribution license, endorsement or partnership.

Generated scenes are unbuilt concepts. Their provenance is recorded in [design references](docs/design-references.md). Do not publish private reference attachments, supplier offers, device databases or credentials. Use [CITATION.cff](CITATION.cff) when citing the project.
