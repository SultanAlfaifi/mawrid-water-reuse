import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { root } from './shared.mjs';
const runtime = process.env.MAWRID_NODE_MODULES || path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const sharp = createRequire(path.join(runtime,'runtime.cjs'))('sharp');
const jobs=[];
for(const folder of ['logos','patterns','icons','templates']) {
  for(const name of await fs.readdir(path.join(root,'assets/brand',folder))) {
    if(!name.endsWith('.svg'))continue;
    const source=path.join(root,'assets/brand',folder,name);
    const out=path.join(root,'assets/brand/png',folder,name.replace('.svg','.png'));
    await fs.mkdir(path.dirname(out),{recursive:true});
    const width=folder==='logos'?Math.max(256,Number((await fs.readFile(source,'utf8')).match(/viewBox="0 0 ([\d.]+)/)?.[1]??266)*4):folder==='icons'?192:folder==='patterns'?960:1440;
    jobs.push({source,out,width});
  }
}
for(const name of ['x-header','github-social-preview'])jobs.push({source:path.join(root,'assets/social',name+'.svg'),out:path.join(root,'assets/social',name+'.png'),width:name==='x-header'?1500:1280});
for(const name of ['treatment-train','filter-health','circular-value'])jobs.push({source:path.join(root,'assets/diagrams',name+'.svg'),out:path.join(root,'assets/diagrams',name+'.png'),width:1600});
// Bound concurrent raster work; A4 originals remain editable vector SVG.
for(let i=0;i<jobs.length;i+=3)await Promise.all(jobs.slice(i,i+3).map(async job=>{await sharp(job.source,{density:180}).resize({width:job.width}).png().toFile(job.out);}));
for(const size of [32,192,512])await sharp(path.join(root,'assets/brand/mawrid-logo.svg')).resize(size,size).png().toFile(path.join(root,'assets/brand',`mawrid-icon-${size}.png`));
console.log(`${jobs.length} artwork previews + 3 app icons exported.`);
