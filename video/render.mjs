/**
 * MAWRID silent judge film. No package installation or hosted renderer.
 * Set MAWRID_PLAYWRIGHT_MODULE / MAWRID_FFMPEG to installed tools when needed.
 * node video/render.mjs [--cards-only]
 * Native source: composition.html. Timeline: mashhad.json.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import http from 'node:http';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'..');
const cache=path.join(here,'.render');
const review=path.join(here,'review');
const target=path.join(root,'assets','demo');
const require=createRequire(import.meta.url);
const playwrightModule=process.env.MAWRID_PLAYWRIGHT_MODULE || 'playwright';
const {chromium}=require(playwrightModule);
const ffmpeg=process.env.MAWRID_FFMPEG || 'ffmpeg';
const run=(args)=>new Promise((resolve,reject)=>{const child=spawn(ffmpeg,args,{stdio:['ignore','ignore','pipe'],windowsHide:true});let log='';child.stderr.on('data',data=>{log=(log+data).slice(-16000)});child.on('exit',code=>code===0?resolve(log):reject(new Error(log)));child.on('error',reject)});
const mime={'.html':'text/html;charset=utf-8','.jpg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml','.ttf':'font/ttf','.js':'text/javascript'};
const server=http.createServer(async(req,res)=>{try{const requested=path.resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://local').pathname));if(!requested.startsWith(root+path.sep))throw new Error('Path outside project');const body=await fs.readFile(requested);res.writeHead(200,{'content-type':mime[path.extname(requested)]||'application/octet-stream'});res.end(body)}catch{res.writeHead(404);res.end('Not found')}});
await fs.mkdir(cache,{recursive:true});await fs.mkdir(review,{recursive:true});await fs.mkdir(target,{recursive:true});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const address=`http://127.0.0.1:${server.address().port}`;
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto(`${address}/video/composition.html`);await page.evaluate(()=>document.fonts.ready);
const shots=await page.evaluate(()=>window.timeline);
for(const shot of shots){
  const overlay=['journey','fault'].includes(shot.id);
  await page.evaluate(({shot,overlay})=>window.renderFrame(shot.id,{overlay,progress:shot.end/60}),{shot,overlay});
  await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(im=>im.complete?Promise.resolve():new Promise(r=>{im.onload=r;im.onerror=r})))});
  await page.screenshot({path:path.join(cache,`${shot.id}${overlay?'-overlay':''}.png`),omitBackground:overlay});
  // A complete frame is retained as a composition/Arabic inspection artifact.
  if(overlay){await page.evaluate(id=>window.renderFrame(id,{progress:1}),shot.id);await page.screenshot({path:path.join(review,`${shot.id}-styleframe.png`)})}
  else await fs.copyFile(path.join(cache,`${shot.id}.png`),path.join(review,`${shot.id}-styleframe.png`));
}
await browser.close();await new Promise(resolve=>server.close(resolve));
if(process.argv.includes('--cards-only')){console.log('Cards rendered; video encode skipped.');process.exit(0)}
let recording={};try{recording=JSON.parse(await fs.readFile(path.join(here,'recordings','sources.json'),'utf8'))}catch{}
for(const shot of shots){
  const duration=shot.end-shot.start;
  const output=path.join(cache,`${shot.id}.mp4`);
  const common=['-r','24','-an','-c:v','libx264','-preset','fast','-crf','24','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart','-y',output];
  if(['journey','fault'].includes(shot.id)&&recording[shot.id]){
    const source=path.resolve(here,recording[shot.id].path);
    const start=recording[shot.id].start||0;
    const fault=shot.id==='fault';
    const sceneLabel=fault?'[insetbase]':'[withscreen]';
    const inset=fault?`;[2:v]scale=390:-1[decision];[insetbase][decision]overlay=x=68:y=468:enable='gte(t,2.2)'[withscreen]`:'';
    const graph=`[0:v]fps=24,scale=848:476:force_original_aspect_ratio=increase,crop=848:476,setsar=1,tpad=stop_mode=clone:stop_duration=2[screen];color=c=0xf7faf6:s=1280x720:r=24:d=${duration}[base];[base][screen]overlay=x=48:y=154:shortest=1${sceneLabel}${inset};[withscreen][1:v]overlay=0:0:shortest=1,format=yuv420p,fade=t=in:st=0:d=0.25,fade=t=out:st=${duration-.25}:d=0.25[v]`;
    await run(['-hide_banner','-loglevel','warning','-ss',String(start),'-i',source,'-loop','1','-i',path.join(cache,`${shot.id}-overlay.png`),...(fault?['-loop','1','-i',path.join(review,'decision-hold.png')]:[]),'-filter_complex',graph,'-map','[v]','-t',String(duration),...common]);
  }else{
    const imageFile=path.join(review,`${shot.id}-styleframe.png`);
    await run(['-hide_banner','-loglevel','warning','-loop','1','-framerate','24','-i',imageFile,'-t',String(duration),'-vf',`format=yuv420p,fade=t=in:st=0:d=0.25,fade=t=out:st=${duration-.25}:d=0.25`,...common]);
  }
  console.log(`Encoded ${shot.id}: ${duration}s`);
}
await fs.writeFile(path.join(cache,'concat.txt'),shots.map(s=>`file '${path.join(cache,`${s.id}.mp4`).replaceAll('\\','/')}'`).join('\n'));
const final=path.join(target,'mawrid-software-demo.mp4');
await run(['-hide_banner','-loglevel','warning','-f','concat','-safe','0','-i',path.join(cache,'concat.txt'),'-c','copy','-movflags','+faststart','-an','-y',final]);
await run(['-hide_banner','-loglevel','warning','-ss','1.5','-i',final,'-frames:v','1','-q:v','2','-y',path.join(target,'mawrid-software-demo-poster.jpg')]);
console.log(final);
