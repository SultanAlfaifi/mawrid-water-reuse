import fs from 'node:fs/promises';import path from 'node:path';import http from 'node:http';import {fileURLToPath} from 'node:url';import {createRequire} from 'node:module';import {spawn} from 'node:child_process';import {once} from 'node:events';import {createHash} from 'node:crypto';
const here=fileURLToPath(new URL('.',import.meta.url)),root=path.resolve(here,'../..'),require=createRequire(import.meta.url);
const {chromium}=require(process.env.MAWRID_PLAYWRIGHT_MODULE||'playwright');
const ffmpeg=process.env.MAWRID_FFMPEG||'ffmpeg',review=path.join(here,'review');await fs.mkdir(review,{recursive:true});
const mime={'.html':'text/html;charset=utf-8','.js':'text/javascript','.css':'text/css','.ttf':'font/ttf','.svg':'image/svg+xml'};
const server=http.createServer(async(req,res)=>{try{let p=path.resolve(here,'.build','.'+decodeURIComponent(new URL(req.url,'http://local').pathname));const base=path.join(here,'.build');if(p!==base&&!p.startsWith(base+path.sep))throw Error();if((await fs.stat(p)).isDirectory())p=path.join(p,'index.html');res.writeHead(200,{'Content-Type':mime[path.extname(p)]||'application/octet-stream'});res.end(await fs.readFile(p))}catch{res.writeHead(404);res.end()}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({headless:true,args:process.platform==='win32'?['--use-gl=angle','--use-angle=d3d11','--enable-gpu']:[]});
const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1}),errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(`http://127.0.0.1:${server.address().port}/`,{waitUntil:'networkidle'});await page.waitForFunction(()=>window.FILM_READY);
const styleTimes=[2.8,9,19,28,34,40,47,55.5],diagnostics=[];
for(const t of styleTimes){diagnostics.push(await page.evaluate(f=>renderFilmFrame(f),Math.round(t*30)));await page.screenshot({path:path.join(review,`frame-${String(t).replace('.','_')}.jpg`),type:'jpeg',quality:92});}
await fs.writeFile(path.join(review,'style-diagnostics.json'),JSON.stringify({errors,diagnostics},null,2));if(errors.length)throw Error(errors.join('\n'));
if(process.argv.includes('--verify')){
 const checks=[];
 for(const t of [2.8,19,34,40,45,49,55.5]){const f=Math.round(t*30);const d=await page.evaluate(f=>renderFilmFrame(f),f);const firstImage=await page.screenshot({type:'png'});const first=createHash('sha256').update(firstImage).digest('hex');await page.evaluate(f=>renderFilmFrame(f),f+45);await page.evaluate(f=>renderFilmFrame(f),f);const repeatedImage=await page.screenshot({type:'png'});const repeated=createHash('sha256').update(repeatedImage).digest('hex');if(first!==repeated){await fs.writeFile(path.join(review,'failed-first.png'),firstImage);await fs.writeFile(path.join(review,'failed-repeat.png'),repeatedImage);throw Error('Nondeterministic rendered frame at '+t);}if(d.type.active.some(s=>s.lines.some(l=>!l.fitsWidth||!l.withinFrame)))throw Error('Text overflow at '+t);if(t>=30&&t<38&&(d.state!=='HOLD'||d.irrigationFeedback!=='closed'||d.flow.reuse_lpm!==0))throw Error('Virtual fault response mismatch');if(t===19&&d.research?.confirmed_alarm!==13005)throw Error('Research source mismatch');if(t===45&&(d.phone?.screenState!=='dropout'||d.phone?.mlUsed!==false))throw Error('Actual phone screenshot provenance mismatch');checks.push({time:t,sha256:first,repeat_identical:true,state:d.state,irrigation:d.irrigationFeedback,phone:d.phone?.screenState??null,research:d.research??null});}
 await fs.writeFile(path.join(review,'seek-verification.json'),JSON.stringify({status:'PASS',checks,scope:'Deterministic frame seeking, Arabic bounds and virtual fault response only.'},null,2));console.log('Seek and virtual-fault verification PASS');
}
if(!process.argv.includes('--stills')&&!process.argv.includes('--verify')){
 const proof=process.argv.includes('--proof'),frames=proof?180:1800;
 const output=proof?path.join(review,'motion-proof.mp4'):path.join(root,'assets/demo/mawrid-smart-demo.mp4');
 const encoder=spawn(ffmpeg,['-hide_banner','-loglevel','warning','-f','image2pipe','-vcodec','mjpeg','-framerate','30','-i','pipe:0','-vf','scale=in_range=pc:out_range=tv,format=yuv420p','-an','-c:v','libx264','-preset','medium','-crf','20','-pix_fmt','yuv420p','-color_range','tv','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart','-y',output],{windowsHide:true,stdio:['pipe','ignore','pipe']});
 let stderr='';encoder.stderr.on('data',d=>stderr=(stderr+d).slice(-12000));const completed=new Promise((resolve,reject)=>{encoder.on('exit',code=>code===0?resolve():reject(Error(stderr)));encoder.on('error',reject)});
 const started=Date.now();for(let frame=0;frame<frames;frame++){await page.evaluate(f=>renderFilmFrame(f),frame);const jpg=await page.screenshot({type:'jpeg',quality:92});if(!encoder.stdin.write(jpg))await once(encoder.stdin,'drain');if(frame%90===0)console.log(`Rendered ${frame}/${frames}, elapsed ${Math.round((Date.now()-started)/1000)}s`);}
 encoder.stdin.end();await completed;await fs.writeFile(path.join(review,proof?'proof-render.json':'render.json'),JSON.stringify({frames,fps:30,width:1920,height:1080,elapsed_seconds:(Date.now()-started)/1000,errors,output:path.relative(root,output)},null,2));console.log(output);
}
await browser.close();await new Promise(r=>server.close(r));
