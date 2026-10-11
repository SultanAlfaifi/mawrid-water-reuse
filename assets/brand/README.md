# حزمة هوية مورد

الهوية مبنية على شعار القطرة واسم مورد وثيم الموقع الأخضر، باتجاه تصوير جامعي إسلامي مشرق. [ابدأ بدليل الهوية](guide/index.html) أو [PDF](../../output/pdf/mawrid-brand-book.pdf).

| المجلد / الملف | الاستخدام |
|---|---|
| `logos/` | عربي، إنجليزي، ثنائي، عمودي، رمز؛ بأخضر ومعكوس وحبر |
| `png/logos/` | نسخ شفافة عالية الدقة؛ الاسم والرمز لا يحتاجان تثبيت الخط |
| `patterns/` | المسار المتصل، المشربية الهادئة، قوس الضوء |
| `icons/` | 12 أيقونة على شبكة 24×24 وبخط 1.6 |
| `templates/` | بطاقات ومراسلات وغلاف وبوستر ومنشورات وأبحاث وملصقات |
| `templates/mawrid-presentation.pptx` | 8 شرائح 16:9 بنصوص وأشكال قابلة للتعديل |
| `png/templates/` | معاينات القوالب للاستخدام الرقمي؛ أصل الطباعة المتجهي هو SVG |
| `readme-cover.svg` / `readme-cover.png` | غلاف المستودع باللغة الإنجليزية وبالهوية نفسها |
| `photography/` | خمس صور تصورية متجانسة للاستخدام في التصميم |
| `photography-prompts.md` | توجيه الصورة ونصوص توليد مشاهد جديدة |
| `colors.json` / `palette.csv` | HEX وRGB وCMYK التقريبي وأدوار الألوان |
| `mawrid-tokens.css` | ألوان وخطوط ومسافات وحركة للاستخدام الرقمي |
| `guide/pages/` | صفحات الدليل SVG قابلة للتكبير والتحرير |
| `../../output/brand/mawrid-identity-kit.zip` | الحزمة المجمّعة مع الدليل والخطوط وتراخيصها |

الحزمة المجمّعة ناتج محلي قابل لإعادة التوليد. النسخة المنشورة متاحة عبر [إصدار الهوية 1.0 على GitHub](https://github.com/SultanAlfaifi/mawrid-water-reuse/releases/tag/identity-v1.0)؛ تبقى أصولها المفردة في المستودع.

## الاستخدام والتحرير

نص SVG محوّل إلى مسارات للحفاظ على تشكيل العربية ومظهر الشعار في برامج التصميم. يمكن تغيير نص القالب من مولّداته ثم إعادة التصدير؛ في PowerPoint النصوص والأشكال طبيعية وقابلة للتحرير. ثبت الخطين المرفقين في الجهاز الذي ستعدّل عليه العرض، أو استبدلهما وفق دليل الهوية قبل التصدير.

جميع مقاسات المطبوعات مقاسات نهائية دون نزف. يجهز المطبّع النزف المناسب، عادة 3mm، ويحوّل الألوان حسب ملف الطابعة. قيم CMYK في CSV تقريب حسابي، وليست معايرة لورق وطابعة محددين. تحفظ ملفات الخطوط مع إشعارات OFL عند إعادة توزيعها.

الصور تصورات مولّدة وليست تصويرًا لتنفيذ. تبقى عبارة «تصور مولّد؛ غير منفذ» قربها. ملفات الصورة المرجعية ومعلومات منشئها في [صور المشروع](../images/)؛ لا تعرض جامعة أو جهة على أنها شريك مؤكد.

## إعادة إنتاج الأصول

أصول الهوية الجاهزة تعمل دون أدوات توليد. لإعادة إنتاجها من السكربتات تحتاج Node.js وPython، وfontkit 2.0.4 وbidi-js 1.0.3 وSharp وReportLab، وللعرض runtime يحتوي `@oai/artifact-tool`. لا تستخدم السكربتات خدمة تصميم أو نشر خارجية.

```powershell
npm.cmd install --prefix .qa/brand-tools --no-save --no-package-lock fontkit@2.0.4 bidi-js@1.0.3
node scripts/brand/create-logos.mjs
node scripts/brand/create-applications.mjs
node scripts/brand/create-diagrams.mjs
node scripts/brand/create-readme-cover.mjs
node scripts/brand/check-typography.mjs
node scripts/brand/export-photography.mjs
node scripts/brand/export-assets.mjs
node scripts/brand/create-brandbook.mjs
python scripts/brand/export-brandbook.py
python scripts/brand/package-kit.py
```

يمكن تعريف `MAWRID_NODE_MODULES` بمسار حزم Node المتاحة لمولد الدليل والصادرات، و`MAWRID_BRAND_NODE_MODULES` لمولد التطبيقات. دليل المحتوى: [هوية مورد وصياغته](../../docs/brand-and-content.md).
