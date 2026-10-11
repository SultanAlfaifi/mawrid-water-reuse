import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import { C,root,svgText,textWidth,logoAt,markAt,svgWrap,esc } from './shared.mjs';
const sharp=createRequire(path.join(process.env.MAWRID_NODE_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'),'runtime.cjs'))('sharp');
const W=1600,H=1000,book=[],pictures=new Map();
async function picture(file) {
  if(!pictures.has(file))pictures.set(file,`data:image/jpeg;base64,${(await sharp(path.join(root,file)).resize({width:1600,withoutEnlargement:true}).jpeg({quality:88,mozjpeg:true}).toBuffer()).toString('base64')}`);
  return pictures.get(file);
}
const names=['ablution','concept','testing','irrigation','maintenance'];
const photos=Object.fromEntries(await Promise.all(names.map(async n=>[n,await picture(`assets/images/campus-${n}.webp`)])));
const labels={ablution:'مصدر الوضوء',concept:'وحدة مورد',testing:'فحص العينات',irrigation:'الري بالتنقيط',maintenance:'صيانة الخرطوشة'};
const previews=async(name)=>picture(`assets/brand/png/templates/${name}.png`);
class Page {
  constructor(title,en,bg=C.paper){this.title=title;this.en=en;this.bg=bg;this.parts=[`<rect width="1600" height="1000" fill="${bg}"/>`];book.push(this);}
  r(x,y,w,h,fill,extra=''){this.parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" ${extra}/>`);return this;}
  line(x,y,x2,y2,color=C.line,sw=2){this.parts.push(`<path d="M${x} ${y}L${x2} ${y2}" fill="none" stroke="${color}" stroke-width="${sw}"/>`);return this;}
  p(d,fill='none',stroke=C.green,sw=3,extra=''){this.parts.push(`<path d="${d}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`);return this;}
  t(text,x,y,size=26,color=C.ink,weight=400,lang='ar',align=lang==='ar'?'right':'left'){const left=align==='right'?x-textWidth(text,size,weight,lang):align==='center'?x-textWidth(text,size,weight,lang)/2:x;this.parts.push(svgText(text,left,y,size,color,weight,lang));return this;}
  lines(lines,x,y,size=27,color=C.ink,weight=400,leading=46,lang='ar'){lines.forEach((text,i)=>this.t(text,x,y+i*leading,size,color,weight,lang));return this;}
  logo(x,y,w,color=C.forest,variant='ar'){this.parts.push(logoAt(x,y,w,color,variant));return this;}
  mark(x,y,w,color=C.forest){this.parts.push(markAt(x,y,w,color));return this;}
  image(src,x,y,w,h,fit='slice'){this.parts.push(`<image x="${x}" y="${y}" width="${w}" height="${h}" href="${src}" preserveAspectRatio="xMidYMid ${fit}"/>`);return this;}
  icon(name,x,y,size=64,color=C.forest){const s=icons[name].replaceAll(C.forest,color);this.parts.push(`<g transform="translate(${x} ${y}) scale(${size/24})">${s}</g>`);return this;}
  header(){this.t(this.title,1512,157,64,C.forest,600).t(this.en,88,150,22,C.green,400,'en').line(88,214,1512,214);return this;}
  footer(){const fg=this.bg===C.forest?C.mint:C.green;this.line(88,919,1512,919,this.bg===C.forest?C.green:C.line,1).t('مورد · دليل الهوية',1512,963,18,fg,400).t(String(book.indexOf(this)+1).padStart(2,'0'),88,963,18,fg,400,'en').t('2026 / 1.0',140,963,14,fg,400,'en');return this;}
  finish(){this.footer();return svgWrap(W,H,this.parts.join(''),`${this.title} · MAWRID brand book`);}
}
const icons={};for(const name of ['source','tank','filter','carbon','disinfection','sensor','route','irrigation','lab','maintenance','palm','evidence']){const svg=await fs.readFile(path.join(root,'assets/brand/icons',name+'.svg'),'utf8');icons[name]=svg.match(/<g[\s\S]*<\/g>/)[0];}
const arch=(x,y,w,h)=>`M${x} ${y+h}V${y+w/2}A${w/2} ${w/2} 0 0 1 ${x+w} ${y+w/2}V${y+h}Z`;
function motif(p,x,y,w,h,color=C.green,opacity='.12') {p.p(`M${x} ${y}H${x+w*.62}Q${x+w} ${y} ${x+w} ${y+h*.35}V${y+h*.62}Q${x+w} ${y+h} ${x+w*.6} ${y+h}H${x+w*.25}Q${x} ${y+h} ${x} ${y+h*.7}V${y+h*.5}`,'none',color,5,`opacity="${opacity}"`);}

// The guide deliberately alternates full imagery, large specimen pages and
// quiet explanatory spreads. Every Arabic line is shaped into vector paths.
let p=new Page('هوية مورد','MAWRID identity',C.forest);
p.image(photos.ablution,0,0,965,919).r(965,0,635,919,C.forest).logo(1050,112,455,C.paper).lines(['مياه الوضوء،','موردٌ للري.'],1512,448,78,C.paper,700,116).lines(['هوية بصرية متكاملة','بروح الحرم المشرق.'],1512,712,32,C.mint,400,55).t('Ablution water,',1048,820,23,C.mint,400,'en').t('a resource for irrigation.',1048,855,23,C.mint,400,'en').t('تصور مولّد؛ غير منفذ',910,870,20,C.paper,400);motif(p,40,90,280,730,C.paper,'.20');

p=new Page('فكرة واحدة. حضور واضح.','The brand idea').header();
p.lines(['نجمع مياه الوضوء المفصولة، ونعالجها،','ونختبر استخدامها لري المساحات الخضراء.'],1512,363,47,C.forest,600,84).lines(['علامة سعودية السياق، جامعية الاستخدام،','هادئة في مظهرها، واضحة في تفسيرها.'],1512,553,29,C.ink,400,52);
const processSequence=[['source','مصدر واضح','مياه وضوء مفصولة'],['filter','معالجة مقترحة','مسار يحتاج اختبارًا'],['lab','تحقق مخبري','للاستخدام المقصود'],['irrigation','ري محدد','مساحات الجامعة']];
processSequence.forEach(([icon,title,sub],i)=>{const x=1224-i*360;p.icon(icon,x+52,704,60).t(title,x+86,823,29,C.forest,600,'ar','center').t(sub,x+86,871,23,C.green,400,'ar','center');if(i<3)p.p(`M${x-28} 742H${x-114}m18-12-18 12 18 12`);});

p=new Page('الحرم المشرق.','A bright campus world').header();
p.image(photos.ablution,88,270,875,536).lines(['ضوء طبيعي.','حجر فاتح.','ماء له وظيفة.'],1512,370,54,C.forest,600,92).lines(['تأتي الروح الإسلامية من العمارة:','قوس متزن، مشربية، وظل هندسي.','وتأتي الروح الجامعية من الوضوح','والتعلم والمادة القابلة للاختبار.'],1512,675,27,C.ink,400,48).t('تصور مولّد؛ غير منفذ',960,861,20,C.green);

p=new Page('الشعار الأساسي.','Primary signature').header();
p.logo(590,294,880).t('القطرة والاسم. كتلة واحدة.',1512,712,41,C.forest,600).lines(['نحافظ على رسم القطرة الذي ظهر في الموقع.','مساراتها الداخلية تلخّص انتقال الماء داخل النظام.','الاسم عربي أولًا، ويظل الشعار أحادي اللون.'],1512,792,27,C.ink,400,46).mark(118,460,194,C.green);

p=new Page('عائلة الشعار.','One mark, several lockups').header();
p.r(88,274,690,280,C.mint).logo(190,328,480,C.forest,'en').t('النسخة الإنجليزية',735,517,22,C.green);
p.r(822,274,690,280,C.forest).logo(1060,312,330,C.paper,'bilingual').t('العربي والإنجليزي معًا',1470,517,22,C.paper);
p.logo(320,622,230,C.forest,'stacked').t('القفل العمودي',620,856,24,C.green).mark(950,655,180).t('الرمز منفردًا',1280,856,24,C.green).lines(['تختار النسخة حسب مساحة التصميم ولغته.','يبقى ترتيب الاسم والرمز ونسبهما ثابتًا.'],1512,622,23,C.ink,400,45);

p=new Page('مساحة تحفظ وضوحه.','Clear space and minimum size').header();
p.r(205,330,792,383,C.mint).r(257,382,688,279,'none',`stroke="${C.green}" stroke-width="2" stroke-dasharray="9 8"`).logo(285,412,632);
p.t('x',165,430,28,C.green,700,'en').line(205,382,257,382,C.green).line(205,370,205,394,C.green).line(257,370,257,394,C.green);
p.lines(['x = ربع ارتفاع القطرة.','تظل هذه المسافة فارغة حول الشعار.','الحد الأدنى المقترح لارتفاع الرمز:','24 بكسل للشاشة؛ 8 مم للطباعة.'],1512,365,28,C.ink,400,62);
p.logo(1244,681,185).t('اختبر الوضوح في الحجم الفعلي.',1512,830,27,C.green,600).t('تُصغّر المجموعة كاملة بنسبة واحدة.',997,835,25,C.ink);

p=new Page('لون واحد. خلفية هادئة.','Colorways and correct use').header();
[[88,C.paper,C.forest],[585,C.mint,C.forest],[1082,C.forest,C.paper]].forEach(([x,bg,fg])=>p.r(x,278,430,350,bg).logo(x+58,377,320,fg));
['أساسي على الورق','أساسي على النعناع','معكوس على الأخضر'].forEach((t,i)=>p.t(t,518+i*497,688,26,C.forest,600));
p.lines(['لا تمدّد الشعار، ولا تدوّره، ولا تضف ظلًا أو تدرجًا.','لا تعيد رسم المسارات أو تكتب الاسم بخط بديل.','فوق صورة مزدحمة، ضعه داخل مساحة مستقلة هادئة.'],1512,770,27,C.ink,400,48);

p=new Page('ألوان مورد.','The palette').header();
const swatches=[['الأخضر العميق','FOREST',C.forest],['الأخضر','GREEN',C.green],['الورق','PAPER',C.paper],['النعناع','MINT',C.mint],['المريمية','SAGE',C.sage],['الحبر','INK',C.ink],['الحجر','SAND',C.sand]];
swatches.forEach(([ar,en,hex],i)=>{const x=88+i*204,fg=[0,1,5].includes(i)?C.paper:C.forest;p.r(x,280,192,352,hex,i===2?`stroke="${C.line}" stroke-width="1"`:'').t(ar,x+166,355,23,fg,600).t(en,x+26,580,16,fg,700,'en').t(hex.toUpperCase(),x+26,710,23,C.forest,700,'en');});
p.lines(['المساحات الفاتحة هي الغالبة، والأخضر العميق يحدد نقطة التركيز.','الحجر والمريمية للخلفيات والتفاصيل؛ الحبر والأخضر العميق للقراءة.'],1512,795,27,C.ink,400,50);

p=new Page('الألوان تخدم القراءة.','Contrast and color roles').header();
function rgb(hex){return hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255);}function lum(hex){const a=rgb(hex).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return .2126*a[0]+.7152*a[1]+.0722*a[2];}function contrast(a,b){return ((Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05)).toFixed(2);}
const pairs=[[C.forest,C.paper,'عناوين أساسية'],[C.ink,C.mint,'نصوص وتفاصيل'],[C.paper,C.forest,'نص معكوس'],[C.green,C.paper,'روابط ومسار الماء']];
pairs.forEach(([fg,bg,title],i)=>{const y=280+i*146;p.r(88,y,620,110,bg).t('مياه الوضوء، موردٌ للري.',675,y+72,33,fg,600).t(title,1500,y+45,29,C.forest,600).t(`${contrast(fg,bg)} : 1`,845,y+75,25,C.green,700,'en');});
p.t('الحجر والمريمية لا يستخدمان كنص صغير على خلفية فاتحة.',1512,897,25,C.green);

p=new Page('خط واضح بلغتين.','Typography').header();
p.t('مياه الوضوء،',1512,365,82,C.forest,700).t('موردٌ للري.',1512,490,82,C.green,700).t('IBM Plex Sans Arabic',88,370,27,C.green,700,'en').t('400 / 600 / 700',88,416,24,C.ink,400,'en');
p.t('Ablution water.',88,635,66,C.forest,700,'en').t('A resource for irrigation.',88,728,66,C.green,700,'en').t('Manrope',1512,652,27,C.forest,700,'en','right').t('400 / 700',1512,704,24,C.ink,400,'en','right').t('الخطوط محلية ومرفق معها ترخيص OFL.',1512,856,25,C.green);

p=new Page('عنوان واحد. فكرة واحدة.','Type scale and composition').header();
[['عنوان أساسي',64,600,'01'],['عنوان قسم',40,600,'02'],['شرح قصير قابل للقراءة',28,400,'03'],['تعليق قريب من الصورة أو الدليل',21,400,'04']].forEach(([txt,size,weight,num],i)=>{const y=320+i*147;p.t(txt,1512,y,size,C.forest,weight).t(`${size}px`,88,y,23,C.green,700,'en').line(88,y+51,1512,y+51);});
p.t('هذه أحجام مرجعية للمطبوع البصري؛ الويب يستخدم نصًا أساسيًا 18px.',1512,880,23,C.ink);

p=new Page('مسار الماء. قوس الضوء.','Graphic language').header();
p.p(arch(88,280,375,530),C.sand,'none',0).p(arch(138,345,275,465),C.paper,'none',0).t('قوس الضوء',458,862,25,C.forest,600);
for(let y=308;y<800;y+=88)for(let x=572;x<916;x+=88)p.p(`M${x+44} ${y} ${x+88} ${y+44} ${x+44} ${y+88} ${x} ${y+44}Z`,'none',C.sage,2);
p.t('المشربية الهادئة',975,862,25,C.forest,600);motif(p,1068,360,352,310,C.green,'.7');p.mark(1173,389,134,C.forest).t('المسار المتصل',1502,862,25,C.forest,600);

p=new Page('أيقونات بنفس النَفَس.','A consistent icon family').header();
const iconTitles=['المصدر','الخزان','الترشيح','المادة','التطهير','الحساس','التوجيه','الري','المختبر','الصيانة','النخلة','الدليل'];
Object.keys(icons).forEach((name,i)=>{const x=1245-(i%4)*365,y=285+Math.floor(i/4)*185;p.icon(name,x+59,y,86).t(iconTitles[i],x+102,y+139,27,C.ink,600,'ar','center');});
p.t('شبكة 24×24، سُمك خط 1.6، أطراف مستديرة، ولون واحد.',1512,877,25,C.green);

p=new Page('كيف تبدو صور مورد؟','Photography and concept imagery').header();
p.image(photos.ablution,88,273,915,570).lines(['نهار طبيعي، حجر كريمي،','نخيل ومعدن واقعي.','كاميرا قريبة من مستوى العين.','الماء واضح بوظيفته.'],1512,352,30,C.forest,600,69).lines(['نتجنب الليل الدرامي، النيون،','الزخرفة المزدحمة، والرموز الدينية','المضافة فوق الصورة كديكور.'],1512,687,26,C.ink,400,47).t('تصور مولّد؛ غير منفذ',998,882,21,C.green);

p=new Page('خمس لقطات. رحلة واحدة.','A coherent image sequence').header();
names.forEach((name,i)=>{const x=1237-i*287;p.image(photos[name],x,292,265,391).t(labels[name],x+265,749,26,C.forest,600).t(String(i+1).padStart(2,'0'),x,750,18,C.green,400,'en');if(i<4)p.p(`M${x-6} 499H${x-20}m7-7-7 7 7 7`);});
p.lines(['نكرر الضوء والحجر والخضرة وشكل الوحدة بين اللقطات.','تسبق صورة الفحص صورة الري. كل المشاهد تصورات مولّدة غير منفذة.'],1512,827,27,C.ink,400,47);

p=new Page('حركة تشرح العلاقة.','Motion and digital behavior').header();
const motion=[['دخول هادئ','360–700ms','ظهور محدود، دون إخفاء النص أثناء القراءة.'],['المسار المتصل','SCROLL','خطوة تتبع خطوة، مع عنوان ثابت وواضح.'],['فتح الطبقات','3D','نكتشف موضع المادة وعلاقتها بما قبلها وبعدها.'],['حلقة المشاهد','720ms','صورة كبيرة، سحب مباشر، وزر لإيقاف الدوران.']];
motion.forEach(([title,timing,body],i)=>{const y=301+i*144;p.t(title,1512,y,34,C.forest,600).t(timing,88,y,25,C.green,700,'en').t(body,1512,y+57,25,C.ink).line(88,y+94,1512,y+94);});p.t('تقليل الحركة يلغي الدوران التلقائي والانتقالات غير الضرورية.',1512,891,25,C.green);

p=new Page('صوت مورد.','Brand voice').header();
p.lines(['واضح في شرحه.','دقيق في دليله.','هادئ في ثقته.'],1512,374,69,C.forest,600,112).r(88,286,630,550,C.mint).lines(['نكتب:','«نختبر استخدام الماء للري».','«ماذا يدعم هذا البحث؟».','«مرحلة التصميم والتحقق المخطط».'],670,370,32,C.forest,600,94).lines(['نتجنب وعود الأداء قبل قياسه،','وقائمة الشركاء غير المؤكدة،','والشرح الطويل قبل فهم الفكرة.'],1512,744,27,C.ink,400,48);

p=new Page('هوية تعمل على الورق.','Stationery and reports').header();
p.image(await previews('business-card-front'),88,296,544,302,'meet').image(await previews('business-card-back'),88,635,544,240,'meet').image(await previews('letterhead-a4'),697,279,358,562,'meet').image(await previews('report-cover-a4'),1094,279,418,592,'meet').t('بطاقة الفريق · 90×50 مم',632,904,21,C.green).t('ورق A4',1055,904,21,C.green).t('غلاف تقرير A4',1512,904,21,C.green);

p=new Page('حضور رقمي موحّد.','Social and research templates').header();
p.image(await previews('social-square'),88,302,518,518,'meet').image(await previews('research-card'),654,287,426,548,'meet').image(await previews('social-story'),1140,270,372,607,'meet').t('منشور · 1080×1080',606,892,23,C.green).t('دليل بحث · 1080×1350',1080,892,23,C.green).t('قصة · 1080×1920',1512,892,23,C.green);

p=new Page('في المعرض والمختبر.','Exhibition and working labels').header();
p.image(await previews('exhibition-poster-a3'),88,282,495,600,'meet').image(await previews('unit-label'),689,309,823,469,'meet').image(await previews('sample-label'),910,718,488,172,'meet').t('بوستر A3',582,899,22,C.green).t('ملصق وحدة · 180×110 مم',1512,816,23,C.green).t('ملصق عينة · 90×50 مم',874,818,22,C.green);

p=new Page('العرض يحكي القصة نفسها.','Presentation system').header();
p.image(photos.concept,88,277,775,480).r(906,277,606,480,C.forest).logo(1116,336,320,C.paper).lines(['مياه الوضوء،','موردٌ للري.'],1460,522,47,C.paper,700,81).t('قالب PowerPoint قابل للتعديل · 16:9',1512,828,27,C.forest,600).t('غلاف، مصدر، مسار، طبقات، مقارنة، أدلة، تحقق، وخاتمة.',1512,881,25,C.ink).t('تصور مولّد؛ غير منفذ',855,731,20,C.paper);

p=new Page('الحزمة الجاهزة للاستخدام.','Files and handoff').header();
const rows=[['الشعار','عربي، إنجليزي، ثنائي، عمودي، رمز؛ أخضر ومعكوس وحبر.'],['العناصر','ألوان وخطوط، 12 أيقونة، و3 أنماط هندسية.'],['التطبيقات','مطبوعات، منشورات، أبحاث، ملصقات، وأغلفة رقمية.'],['العروض','8 شرائح قابلة للتعديل مع النص والأشكال.'],['الدليل','PDF، نسخة تصفح HTML، وملفات SVG وPNG.']];
rows.forEach(([head,body],i)=>{const y=302+i*116;p.t(head,1512,y,31,C.forest,600).t(body,1250,y,26,C.ink).line(88,y+51,1512,y+51);});p.lines(['الأصول الهندسية قابلة للتحرير. النص في SVG مسارات تحفظ شكل العربية.','المقاسات الطباعية نهائية دون نزف؛ يضيف المطبّع النزف المناسب قبل الإنتاج.'],1512,843,23,C.green,400,42);

p=new Page('مورد. بروح الحرم المشرق.','MAWRID / bright campus',C.forest);
p.image(photos.irrigation,0,0,795,919).r(795,0,805,919,C.forest).logo(989,184,485,C.paper).lines(['مصدر واحد.','واستخدام واضح.'],1512,593,74,C.paper,600,108).t('مياه الوضوء، موردٌ للري.',1512,809,33,C.mint,600).t('تصور مولّد؛ غير منفذ',744,868,20,C.paper);

const guide=path.join(root,'assets/brand/guide');await fs.mkdir(path.join(guide,'pages'),{recursive:true});
const index=[];
for(let i=0;i<book.length;i++){const page=book[i],name=String(i+1).padStart(2,'0')+'.svg';await fs.writeFile(path.join(guide,'pages',name),page.finish());index.push({id:i+1,title:page.title,en:page.en,file:'pages/'+name});}
await fs.writeFile(path.join(guide,'contents.json'),JSON.stringify(index,null,2));
const sections=index.map(page=>`<section id="page-${page.id}" class="spread"><img src="${page.file}" alt="${esc(page.title)} — ${esc(page.en)}" loading="${page.id===1?'eager':'lazy'}" width="1600" height="1000"><a href="${page.file}" download>تنزيل هذه الصفحة SVG</a></section>`).join('');
const nav=index.map(page=>`<a href="#page-${page.id}">${String(page.id).padStart(2,'0')} <span>${esc(page.title)}</span></a>`).join('');
const html=`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مورد — دليل الهوية المتكامل</title><style>@font-face{font-family:Plex;src:url('../../fonts/plex-arabic-400.ttf')}@font-face{font-family:Plex;src:url('../../fonts/plex-arabic-600.ttf');font-weight:600}:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:${C.mint};color:${C.forest};font:18px/1.7 Plex,sans-serif}a{color:inherit;text-decoration:none}a:focus-visible{outline:2px solid ${C.green};outline-offset:4px}::selection{background:${C.sage}}header{padding:32px 38px;display:flex;justify-content:space-between;gap:24px;align-items:center;background:${C.paper};border-bottom:1px solid ${C.line}}h1{margin:0;font-size:28px;font-weight:600}header p{margin:5px 0 0;color:${C.green};font-size:16px}.actions{display:flex;gap:12px;flex-wrap:wrap}.actions a{background:${C.forest};color:${C.paper};padding:12px 20px;border-radius:8px;min-height:44px}.actions a+ a{background:${C.mint};color:${C.forest}}.layout{display:grid;grid-template-columns:275px minmax(0,1fr);max-width:1800px;margin:auto}nav{position:sticky;top:0;height:100dvh;overflow:auto;padding:24px 20px;font-size:15px}nav a{display:flex;gap:12px;padding:10px 8px;border-radius:6px}nav a:hover{background:${C.paper}}nav span{flex:1}main{min-width:0;padding:24px}.spread{margin:0 0 28px;scroll-margin-top:20px}.spread img{display:block;width:100%;height:auto;background:${C.paper};box-shadow:0 8px 24px -14px rgba(0,0,0,.12)}.spread>a{display:inline-block;font-size:14px;padding:8px 0;color:${C.green}}@media(max-width:800px){header{padding:24px;align-items:start;flex-direction:column}.layout{display:block}nav{position:static;height:auto;display:flex;overflow:auto;padding:12px 20px;gap:10px}nav a{white-space:nowrap;min-height:44px}main{padding:14px}.spread>a{font-size:13px}}@media(prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}</style></head><body><header><div><h1>هوية مورد</h1><p>دليل بصري وتطبيقات جاهزة · ${book.length} صفحة</p></div><div class="actions"><a href="../../../output/pdf/mawrid-brand-book.pdf" download>تحميل دليل PDF</a><a href="https://github.com/SultanAlfaifi/mawrid-water-reuse/releases/download/identity-v1.0/mawrid-identity-kit.zip" download>تحميل حزمة الهوية</a></div></header><div class="layout"><nav aria-label="صفحات دليل الهوية">${nav}</nav><main>${sections}</main></div></body></html>`;
await fs.writeFile(path.join(guide,'index.html'),html);
// Replace the old repository banner with the new identity, using the exact
// artwork already approved by this system rather than a competing logo.
await fs.copyFile(path.join(root,'assets/social/github-social-preview.svg'),path.join(root,'assets/brand/mawrid-hero.svg'));
console.log(`${book.length} vector guide pages and a browsable identity book generated.`);
