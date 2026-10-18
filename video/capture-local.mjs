/** Optional supporting still from the full local Python/SQLite application.
 * Use a disposable capture database; this script creates a new simulation session.
 * Run the normal Python server first; MAWRID_LOCAL_URL overrides its origin.
 */
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),here=path.dirname(fileURLToPath(import.meta.url));
const {chromium}=require(process.env.MAWRID_PLAYWRIGHT_MODULE || 'playwright');
const origin=process.env.MAWRID_LOCAL_URL || 'http://127.0.0.1:8892';
const browser=await chromium.launch({headless:true});
const p=await browser.newPage({viewport:{width:1280,height:860},deviceScaleFactor:1});
await p.request.post(origin+'/api/sessions',{data:{source_id:'virtual_plant',research_ack:true}});
await p.request.post(origin+'/api/plant/control',{data:{running:true,speed:30}});
await p.goto(origin+'/#follow');await p.evaluate(()=>document.fonts.ready);await p.waitForTimeout(2400);
await p.request.post(origin+'/api/plant/control',{data:{fault:'sensor_dropout'}});await p.waitForTimeout(2300);
await p.screenshot({path:path.join(here,'review','readings.jpg'),type:'jpeg',quality:90,clip:{x:20,y:186,width:990,height:558}});
await browser.close();console.log('Captured real local follow view; all readings remain simulated.');
