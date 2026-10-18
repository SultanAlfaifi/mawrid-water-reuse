/** Real scene capture: uses the application's own controls and canvas frames.
 * It changes viewport framing only. It never supplies readings, state or ML.
 * Start a static server at the repository root; MAWRID_CAPTURE_URL overrides URL.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),here=path.dirname(fileURLToPath(import.meta.url));
const {chromium}=require(process.env.MAWRID_PLAYWRIGHT_MODULE || 'playwright');
const out=path.join(here,'recordings');await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:process.platform==='win32'?['--use-gl=angle','--use-angle=d3d11','--enable-gpu']:[]});
const p=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await p.goto(process.env.MAWRID_CAPTURE_URL || 'http://127.0.0.1:8894/experience/');
await p.evaluate(()=>document.fonts.ready);await p.waitForFunction(()=>window.MAWRID_BROWSER_DEMO?.status.webglAvailable);
await p.addStyleTag({content:'#viewport{position:fixed!important;inset:0!important;width:1280px!important;height:720px!important;z-index:999;background:#f5f6ee}'});
await p.waitForTimeout(500);
const click=selector=>p.locator(selector).evaluate(el=>el.click());
const state=()=>p.evaluate(()=>window.MAWRID_BROWSER_DEMO.status);
const evidence={capture:'Actual browser canvas; no readings injected. Canvas enlarged to 1280x720 for framing.',url:process.env.MAWRID_CAPTURE_URL || 'http://127.0.0.1:8894/experience/',gpu:await p.evaluate(()=>{const gl=document.querySelector('canvas').getContext('webgl2'),e=gl.getExtension('WEBGL_debug_renderer_info');return e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}),events:[]};
async function begin(){await p.evaluate(()=>{const canvas=document.querySelector('#viewport canvas');const stream=canvas.captureStream(24);const chunks=[];const r=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp9',videoBitsPerSecond:3500000});window.__filmRecorder={r,chunks,stream};r.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};r.start(500);});}
async function end(name){const b64=await p.evaluate(()=>new Promise(resolve=>{const {r,chunks,stream}=window.__filmRecorder;r.onstop=()=>{for(const t of stream.getTracks())t.stop();const f=new FileReader();f.onload=()=>resolve(f.result.split(',')[1]);f.readAsDataURL(new Blob(chunks,{type:'video/webm'}))};r.stop()}));await fs.writeFile(path.join(out,name),Buffer.from(b64,'base64'));}
await click('#run');await click('#overview');await p.waitForTimeout(1100);
await p.locator('#viewport canvas').screenshot({path:path.join(here,'review','browser-overview.png')});
await begin();
for(const stage of ['collection','media','storage','irrigation']){await click(`[data-stage="${stage}"]`);evidence.events.push({clip:'journey',at_seconds:evidence.events.length*4,state:await state()});await p.waitForTimeout(4000)}
await end('browser-journey.webm');
await click('#overview');await p.waitForTimeout(1200);await begin();await p.waitForTimeout(2200);
await click('[data-fault="sensor_dropout"]');evidence.events.push({clip:'fault',at_seconds:2.2,state:await state()});await p.waitForTimeout(9500);await end('browser-fault.webm');
// Capture the real decision element, with its own live text, for a readable inset.
await p.addStyleTag({content:'#viewport{position:relative!important;inset:auto!important;width:auto!important;height:480px!important;z-index:auto!important}'});
await p.waitForTimeout(300);await p.locator('#decision').screenshot({path:path.join(here,'review','decision-hold.png')});
await fs.writeFile(path.join(out,'sources.json'),JSON.stringify({journey:{path:'recordings/browser-journey.webm',start:0},fault:{path:'recordings/browser-fault.webm',start:0}},null,2));
await fs.writeFile(path.join(here,'review','capture-evidence.json'),JSON.stringify(evidence,null,2));
await browser.close();console.log('Captured actual canvas journey and sensor-dropout response.');
