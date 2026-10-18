/* Deterministic presentation-clock checks. No DOM, server or plant writes. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const modules=new Map();
async function moduleURL(name,parent=import.meta.url){
  const file=new URL(name,parent).href;if(modules.has(file))return modules.get(file);
  let source=await fs.readFile(new URL(file),'utf8');
  for(const match of [...source.matchAll(/from\s+(['"])(\.[^'"]+)\1/g)])source=source.replace(match[0],`from '${await moduleURL(match[2],file)}'`);
  const url=`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;modules.set(file,url);return url;
}
const {JourneyPresentation,readingDuration,PRESENTATION_DURATION}=await import(await moduleURL('./presentation.js'));
const {WATER_JOURNEY}=await import(await moduleURL('./water-journey.js'));
let tests=0;
assert.equal(readingDuration({}),20000);
assert.equal(readingDuration({role:'word '.repeat(300)}),30000);
for(const stage of WATER_JOURNEY){assert(readingDuration(stage)>=20000);assert(readingDuration(stage)<=30000);}
assert.equal(PRESENTATION_DURATION,WATER_JOURNEY.reduce((sum,stage)=>sum+readingDuration(stage),0));tests++;

const p=new JourneyPresentation();assert.equal(p.status,'idle');
for(const id of [null,undefined,'',2])assert.throws(()=>p.start(id,0));
p.start('synthetic-session',100);assert.equal(p.index,0);assert.equal(p.status,'playing');assert(p.waitingCamera);
const firstDuration=p.durationMs;assert.equal(p.remainingMs,firstDuration);
assert.equal(p.tick(500000),false);assert.equal(p.index,0);assert.equal(p.remainingMs,firstDuration);
assert.equal(p.settle('media',500000),false);assert(p.waitingCamera);
assert.equal(p.settle('collection',500000),true);assert(!p.waitingCamera);tests++;

assert.equal(p.tick(501000),false);assert.equal(p.remainingMs,firstDuration-1000);
assert.equal(p.tick(500500),false);assert.equal(p.remainingMs,firstDuration-1000);
assert.equal(p.tick(502000),false);assert.equal(p.remainingMs,firstDuration-2000);tests++;

// A stalled tab may advance only once. The next stage gets its full reading
// time after a separate camera acknowledgement, not the old elapsed delay.
assert.equal(p.tick(1000000),true);assert.equal(p.index,1);assert(p.waitingCamera);
assert.equal(p.remainingMs,readingDuration(WATER_JOURNEY[1]));assert(p.remainingMs>0);
assert.equal(p.tick(2000000),false);assert.equal(p.index,1);assert(p.waitingCamera);
assert(p.settle('media',2000000));assert.equal(p.remainingMs,p.durationMs);tests++;

p.tick(2003000);const remaining=p.remainingMs;
assert(p.pause('reading',2004000));assert.equal(p.status,'paused');assert.equal(p.remainingMs,remaining-1000);
const pausedRemaining=p.remainingMs;assert.equal(p.tick(3000000),false);assert.equal(p.remainingMs,pausedRemaining);
assert.equal(p.pause('hidden',3000000),false);assert.equal(p.reason,'reading');
assert(p.resume(3000000));assert(p.waitingCamera);assert.equal(p.remainingMs,pausedRemaining);
assert.equal(p.tick(4000000),false);assert.equal(p.remainingMs,pausedRemaining);
assert.equal(p.settle('collection',4000000),false);assert(p.settle('media',4000000));
p.tick(4001000);assert.equal(p.remainingMs,pausedRemaining-1000);tests++;

p.start('other-session',0);assert(p.pause('hidden',100));const waitingRemaining=p.remainingMs;
assert(p.waitingCamera);assert(p.resume(1000));assert.equal(p.waitingSince,1000);
assert.equal(p.remainingMs,waitingRemaining);assert(p.settle('collection',5000));tests++;

// Read all eight stages. Completion is terminal and cannot loop or advance to
// a ninth stage, regardless of later ticks or camera acknowledgements.
p.start('complete-session',0);let now=0;
for(let index=0;index<WATER_JOURNEY.length;index++){
  assert.equal(p.index,index);assert(p.waitingCamera);assert(p.remainingMs>=20000);
  now+=2000;assert(p.settle(WATER_JOURNEY[index].id,now));
  assert.equal(p.tick(now+p.durationMs-1),false);assert.equal(p.remainingMs,1);
  now+=p.durationMs;assert.equal(p.tick(now),true);
}
assert.equal(p.status,'complete');assert.equal(p.index,7);assert.equal(p.remainingMs,0);
assert.equal(p.tick(now+10000000),false);assert.equal(p.resume(now+10000000),false);
assert.equal(p.settle('irrigation',now+10000000),false);assert.equal(p.index,7);tests++;

const view=p.view();view.index=0;assert.equal(p.index,7);
p.stop();assert.deepEqual(p.view(),{status:'idle',sessionId:null,index:0,remainingMs:0,durationMs:0,waitingCamera:false,reason:''});
assert.equal(p.tick(now+20000000),false);assert.equal(p.pause('manual',now),false);tests++;
console.log(`${tests} presentation-clock checks PASS; real presentation module, explicit synthetic clock; no server, browser or plant commands.`);
