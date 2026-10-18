import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
const require=createRequire('/Users/sultan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/');
const {chromium}=require('playwright');
const sharp=require('sharp');
const {PDFDocument}=require('pdf-lib');
const out=path.resolve(import.meta.dirname,'..');
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,args:['--allow-file-access-from-files']});
const names=process.argv.slice(2).length?process.argv.slice(2):['sheet-3-slide','sheet-3-slide-transparent','sheet-1-pid','sheet-2-ga'];
for (const name of names){
 let slide=name.includes('slide');
 let width=slide?1920:4961,height=slide?1080:3508;
 const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
 const svg=await fs.readFile(path.join(out,name+'.svg'),'utf8');
 await page.setContent(`<html><head><style>@page{size:420mm 297mm;margin:0}html,body{margin:0;padding:0;background:transparent}svg{display:block;width:100vw;height:100vh}@media print{svg{width:420mm;height:297mm}}</style></head><body>${svg}</body></html>`);
 await page.evaluate(()=>document.fonts.ready);
 let shot=await page.screenshot({omitBackground:name.endsWith('transparent')});
 await sharp(shot).withMetadata({density:300}).png().toFile(path.join(out,name+'.png'));
 await sharp(shot).resize(slide?1440:1680).png().toFile(path.join(out,'review',name+'-preview.png'));
 let bounds=await page.evaluate(()=>{let s=document.querySelector('svg'),v=s.viewBox.baseVal;return [...s.querySelectorAll('text')].map(e=>{let b=e.getBBox();return {id:e.id,text:e.textContent,x:b.x,y:b.y,w:b.width,h:b.height,out:b.x<0||b.y<0||b.x+b.width>v.width||b.y+b.height>v.height}})});
 await fs.writeFile(path.join(out,'review',name+'-bounds.json'),JSON.stringify(bounds,null,2));
 if(!slide){
   await page.emulateMedia({media:'print'});
   await page.pdf({path:path.join(out,'review',name+'.pdf'),width:'420mm',height:'297mm',margin:{top:0,bottom:0,left:0,right:0},printBackground:true,preferCSSPageSize:true});
 }
 console.log(JSON.stringify({name,width,height,textCount:bounds.length,outOfBounds:bounds.filter(x=>x.out)}));
 await page.close();
}
await browser.close();
if(names.includes('sheet-1-pid')&&names.includes('sheet-2-ga')){
 const merged=await PDFDocument.create();
 for(const name of ['sheet-1-pid','sheet-2-ga']){
  const src=await PDFDocument.load(await fs.readFile(path.join(out,'review',name+'.pdf')));
  for(const page of await merged.copyPages(src,src.getPageIndices())){
   const originalHeight=page.getHeight(); const a3Width=420*72/25.4,a3Height=297*72/25.4;
   page.setSize(a3Width,a3Height);page.translateContent(0,a3Height-originalHeight);merged.addPage(page);
  }
 }
 merged.setTitle('MAWRID | M20 engineering concept');merged.setAuthor('MAWRID');merged.setSubject('Competition concept. Not approved for construction.');merged.setCreationDate(new Date('2026-10-15T00:00:00Z'));
 await fs.writeFile(path.join(out,'mawrid-engineering.pdf'),await merged.save());
 console.log('Merged PDF complete');
}
