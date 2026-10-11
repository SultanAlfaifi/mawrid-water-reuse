import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(root, '.qa/brand-tools/runtime.cjs'));
const fontkit = require('fontkit');
const bidi = require('bidi-js')();
export const C = { forest:'#123e35', green:'#39786a', paper:'#f7faf6', mint:'#e9f3ef', sage:'#b4cfba', ink:'#243d38', sand:'#d9ccba', muted:'#4d6156', line:'#d1e0d5', white:'#ffffff' };
const fonts = new Map();
export const getFont = (weight=400, lang='ar') => {
  const name = lang === 'ar' ? `plex-arabic-${weight === 700 ? 700 : weight >= 600 ? 600 : 400}.ttf` : `manrope-${weight >= 600 ? 700 : 400}.ttf`;
  if (!fonts.has(name)) fonts.set(name,fontkit.openSync(path.join(root,'assets/fonts',name)));
  return fonts.get(name);
};
export const esc = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const n = value => Number(value.toFixed(3));
function glyphPath(glyph) {
  return glyph.path.commands.map(({ command,args }) => {
    const xy = args.map((v,i)=>n(i%2 ? -v : v));
    return ({moveTo:'M',lineTo:'L',quadraticCurveTo:'Q',bezierCurveTo:'C',closePath:'Z'}[command]??'')+xy.join(' ');
  }).join('');
}
export function textLayout(text,size=20,weight=400,lang='ar') {
  text=String(text);
  // Technical identifiers and dimensions are LTR units, including separators
  // such as × that would otherwise split a number sequence inside Arabic.
  if(lang==='ar')text=text.replace(/[#A-Za-z0-9]+(?:[A-Za-z0-9×.:/−–-]*[A-Za-z0-9])?/g,token=>`\u2066${token}\u2069`);
  const font = getFont(weight,lang);
  const scale = size/font.unitsPerEm;
  const {levels}=bidi.getEmbeddingLevels(text,lang==='ar'?'rtl':'ltr');
  const runs=[];
  for(let start=0;start<text.length;){
    const level=levels[start]; let end=start+1;
    while(end<text.length&&levels[end]===level)end++;
    runs.push({text:text.slice(start,end),level}); start=end;
  }
  // Unicode bidi L2 reorders directional runs without reversing Latin letters,
  // digits or the logical input used by the Arabic joining engine.
  const maxLevel=Math.max(0,...runs.map(run=>run.level));
  const minOdd=Math.min(...runs.filter(run=>run.level%2).map(run=>run.level));
  for(let level=maxLevel;level>=minOdd;level--){
    for(let i=0;i<runs.length;){
      if(runs[i].level<level){i++;continue;}
      let end=i+1;while(end<runs.length&&runs[end].level>=level)end++;
      runs.splice(i,end-i,...runs.slice(i,end).reverse());i=end;
    }
  }
  let cursor=0;
  const glyphs=[];
  for(const fragment of runs){
    const run=font.layout(fragment.text,undefined,undefined,undefined,fragment.level%2?'rtl':'ltr');
    run.glyphs.forEach((glyph,i)=>{
      const position=run.positions[i];
      glyphs.push({path:glyphPath(glyph),commands:glyph.path.commands,x:(cursor+position.xOffset)*scale,y:-position.yOffset*scale,scale});
      cursor+=position.xAdvance;
    });
  }
  return {width:cursor*scale,glyphs};
}
export const textWidth=(text,size=20,weight=400,lang='ar')=>textLayout(text,size,weight,lang).width;
// x is always the LEFT edge of the shaped run; y is its baseline. RTL shaping
// is resolved before paths are emitted, so these files need no installed font.
export function svgText(text,x,y,size,color=C.forest,weight=400,lang='ar') {
  const run=textLayout(text,size,weight,lang);
  // One compound fill per text line avoids raster seams at joined Arabic glyph
  // edges when an SVG page is displayed at fractional browser scales.
  const d=run.glyphs.map(g=>g.commands.map(({command,args})=>({moveTo:'M',lineTo:'L',quadraticCurveTo:'Q',bezierCurveTo:'C',closePath:'Z'}[command]??'')+args.map((v,i)=>n(i%2?y+g.y-v*g.scale:x+g.x+v*g.scale)).join(' ')).join('')).join('');
  return `<path fill="${color}" fill-rule="nonzero" d="${d}" role="img" aria-label="${esc(text)}"/>`;
}
export const markPaths=[ 'M24 5C19 13 10 21 10 30a14 14 0 0 0 28 0C38 21 29 13 24 5Z', 'M11 29h12a7 7 0 0 1 7 7v6M38 27H27a7 7 0 0 1-7-7V11' ];
export function markAt(x,y,size,color=C.forest) {
  return `<g transform="translate(${x} ${y}) scale(${size/48})" fill="none" stroke="${color}" stroke-width="2.5">${markPaths.map(d=>`<path d="${d}"/>`).join('')}</g>`;
}
export const LOGOS={ar:{width:266,height:96},en:{width:408,height:96},bilingual:{width:266,height:126},stacked:{width:240,height:216},mark:{width:48,height:48}};
export function logoBody(color=C.forest,variant='ar') {
  if(variant==='mark')return markAt(0,0,48,color);
  if(variant==='en')return svgText('MAWRID',0,63,58,color,700,'en')+markAt(310,0,96,color);
  if(variant==='stacked')return markAt(72,0,96,color)+svgText('مورد',(240-textWidth('مورد',76,700))/2,158,76,color,700)+svgText('MAWRID',(240-textWidth('MAWRID',22,700,'en'))/2,202,22,color,700,'en');
  const primary=svgText('مورد',0,64,80,color,700)+markAt(170,0,96,color);
  return primary+(variant==='bilingual'?svgText('MAWRID',0,110,25,color,700,'en'):'');
}
export function logoAt(x,y,width,color=C.forest,variant='ar') {
  const geometry=LOGOS[variant]??LOGOS.ar;
  return `<g transform="translate(${x} ${y}) scale(${width/geometry.width})">${logoBody(color,variant)}</g>`;
}
export const svgWrap=(w,h,body,title='مورد · MAWRID')=>`<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img"><title>${esc(title)}</title>${body}</svg>`;
export function imageData(file) {
  const ext=path.extname(file).toLowerCase();
  const mime=ext==='.png'?'image/png':ext==='.svg'?'image/svg+xml':ext==='.webp'?'image/webp':'image/jpeg';
  return `data:${mime};base64,${fs.readFileSync(path.resolve(root,file)).toString('base64')}`;
}
export const write=(file,content)=>{const dest=path.resolve(root,file);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,content);};
