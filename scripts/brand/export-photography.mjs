import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';

const root=path.resolve(import.meta.dirname,'../..');
const runtime=process.env.MAWRID_NODE_MODULES || path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const sharp=createRequire(path.join(runtime,'runtime.cjs'))('sharp');
const scenes=['ablution','concept','testing','irrigation','maintenance'];
const folder=path.join(root,'assets/brand/photography');
await fs.mkdir(folder,{recursive:true});
for(const scene of scenes) await sharp(path.join(root,`assets/images/campus-${scene}.png`)).resize({width:1600}).jpeg({quality:90,mozjpeg:true}).toFile(path.join(folder,`campus-${scene}.jpg`));
await fs.writeFile(path.join(folder,'README.md'),`# صور مورد

خمس صور مولّدة معتمدة بصريًا ضمن المشروع، بطابع جامعي إسلامي مشرق. هذه نسخ JPEG بعرض 1600px للاستخدام في القوالب؛ تحويل صيغة وحجم فقط، دون تغيير إبداعي للصورة.

الترتيب: الوضوء → وحدة المعالجة → فحص العينة → الري → الصيانة.

يوضع عند العرض: **«تصور مولّد؛ غير منفذ»**. لا تثبت الصور وجود جهاز أو موقع شريك أو عينات مختبرة. تحفظ أصول PNG وWebP وملفات prompts وبيانات المنشأ في [صور المشروع](../../images/). توجيه اللقطات الجديدة في [مرجع التصوير](../photography-prompts.md).
`);
console.log('5 coordinated campus JPEGs exported.');
