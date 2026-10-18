/** Capture actual deployed mobile operation panel; no readings/state are injected. */
import path from 'node:path';
import fs from 'node:fs/promises';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.MAWRID_PLAYWRIGHT_MODULE||'playwright');
const here=path.dirname(fileURLToPath(import.meta.url)),out=path.join(here,'assets');
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,args:process.platform==='win32'?['--use-gl=angle','--use-angle=d3d11','--enable-gpu']:[]});
const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:3,isMobile:true,hasTouch:true});
const url=process.env.MAWRID_PHONE_URL||'https://sultalfaifi.com/mawrid-water-reuse/experience/';
await page.goto(url,{waitUntil:'networkidle'});
await page.evaluate(()=>document.fonts.ready);
await page.waitForFunction(()=>window.MAWRID_BROWSER_DEMO?.status.webglAvailable);
await page.locator('#run').click();
await page.waitForTimeout(600);
await page.locator('#controls').scrollIntoViewIfNeeded();
await page.evaluate(()=>window.scrollTo(0,document.querySelector('#controls').getBoundingClientRect().top+window.scrollY-16));
const evidence={url,viewport:{width:390,height:844},deviceScaleFactor:3,note:'Actual browser screenshots of the deployed responsive simulation; no invented readings, remote station connection or ML inference.',shots:[]};
for(const [name,selector] of [['normal','[data-fault="none"]'],['dropout','[data-fault="sensor_dropout"]']]){
 await page.locator(selector).click();
 await page.waitForTimeout(300);
 evidence.shots.push({file:`phone-${name}.png`,scrollY:await page.evaluate(()=>window.scrollY),status:await page.evaluate(()=>window.MAWRID_BROWSER_DEMO.status),decision:await page.locator('#decision').innerText()});
 await page.screenshot({path:path.join(out,`phone-${name}.png`)});
}
await fs.writeFile(path.join(out,'phone-capture-evidence.json'),JSON.stringify(evidence,null,2));
if(process.env.MAWRID_PHONE_PROOF==='1'){
 const root=path.resolve(here,'../..');
 const html=`<!doctype html><html><head><script type="importmap">{"imports":{"three":"/node_modules/three/build/three.module.js"}}</script><style>html,body{margin:0;background:#0a211d}canvas{display:block}</style></head><body><script type="module">
 import * as THREE from 'three';import {createPhoneShot} from '/video/v3/src/phone.js';
 const r=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});r.setSize(1920,1080);r.outputColorSpace=THREE.SRGBColorSpace;r.toneMapping=THREE.ACESFilmicToneMapping;document.body.append(r.domElement);
 const s=new THREE.Scene();s.background=new THREE.Color('#0a211d');s.add(new THREE.HemisphereLight('#e8fff6','#052015',2));
 const l=new THREE.DirectionalLight('#e4f9e8',5);l.position.set(-3,6,8);s.add(l);const rim=new THREE.DirectionalLight('#b5b9c9',4);rim.position.set(4,2,-5);s.add(rim);
 const p=createPhoneShot();s.add(p.root);await p.ready;p.update(45);
 const c=new THREE.PerspectiveCamera(37,1920/1080,.1,100);c.position.set(0,0,10.9);c.lookAt(0,0,0);r.render(s,c);window.PROOF_READY=true;window.PROOF_DIAGNOSTICS=p.diagnostics();
 </script></body></html>`;
 const server=http.createServer(async(req,res)=>{try{if(req.url==='/proof'){res.setHeader('Content-Type','text/html');res.end(html);return}const name=decodeURIComponent(req.url.split('?')[0]);const file=path.resolve(root,'.'+name);if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return}res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.png')?'image/png':'application/octet-stream');res.end(await fs.readFile(file))}catch{res.writeHead(404);res.end()}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const proof=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});await proof.goto(`http://127.0.0.1:${server.address().port}/proof`);await proof.waitForFunction(()=>window.PROOF_READY);await proof.screenshot({path:path.join(out,'phone-proof.png')});evidence.proof=await proof.evaluate(()=>window.PROOF_DIAGNOSTICS);await proof.close();await new Promise(resolve=>server.close(resolve));
}
await fs.writeFile(path.join(out,'phone-capture-evidence.json'),JSON.stringify(evidence,null,2));
await browser.close();
console.log(JSON.stringify(evidence,null,2));
