/* Synthetic digital-twin UI contract tests; no server or simulator mutation. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const source=await fs.readFile(new URL('./plant.js',import.meta.url),'utf8');
const {plantView,plantPage,plantRegions,updatePlant,PLANT_FAULTS}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
let tests=0;
const snapshot={session_id:'plant-session',running:true,timestamp:'2026-01-01T10:00:00Z',mode:'auto',fault:'none',speed:10,
  chans:{turbidity:.65,ph:7.2,chlorine:.35,p1_bar:2.8,p2_bar:2.55,p3_bar:2.3},validity:{turbidity:true,ph:true,chlorine:true},
  tanks:{raw:{liters:1800,capacity_liters:3000,level_percent:60},treated:{liters:1200,capacity_liters:3000,level_percent:40}},
  flow:{inlet_lpm:12,treatment_lpm:10.4167,reuse_lpm:8,drain_lpm:2.0833,backwash_lpm:0},volumes:{reuse_liters:123.5},
  equipment:{feed_pump:'running',dosing_pumps:'running',irrigation_valve:'open',drain_valve:'open',power:true},
  safety:{state:'REUSE',reuse_permitted:true,reasons:[]}};
const data={source:{id:'virtual_plant',kind:'digital_twin'},session:{id:'plant-session',status:'ready'},virtual_plant:snapshot,alarms:[]};
const ui={equipment:'collection',previousLevels:{collection:59,treated:39}};
const original=JSON.stringify(data);
const v=plantView(data);
assert(v.active);assert.equal(v.tanks.collection.level_pct,60);assert.equal(v.irrigation_liters,123.5);
assert(Math.abs(v.filter_delta_pressure_bar-.25)<1e-10);assert.equal(v.drain_flow_lpm,2.0833);tests++;
for(const d of [null,{}, {...data,source:{kind:'public_replay',id:'2019'}},{...data,session:{id:'different'}},{...data,virtual_plant:null}]) {
  assert(!plantView(d).active);const html=plantPage(d,ui);assert(html.includes('plant-start'));assert(!html.includes('123.5'));
}tests++;
let html=plantPage(data,ui);
assert(!html.includes('data-action="plant-start"'));assert(html.includes('123.5'));assert(html.includes('60%'));assert(html.includes('from="70.8" to="72"'));
assert.equal((html.match(/data-equipment=/g)||[]).length,16);assert.equal((html.match(/role="button"/g)||[]).length,8);
assert(!html.includes('plant-zoomed'));assert(html.includes('تكبير المخطط'));assert(plantPage(data,{...ui,zoom:true}).includes('plant-zoomed'));assert(html.includes('aria-pressed="true"'));assert(!html.includes('NaN'));assert(!html.includes('Infinity'));assert(!html.includes('score'));tests++;
const missing={...data,virtual_plant:{...snapshot,chans:{...snapshot.chans,chlorine:0,turbidity:NaN,p2_bar:null},validity:{...snapshot.validity,chlorine:false}}};
const mv=plantView(missing);assert.equal(mv.readings.chlorine,null);assert.equal(mv.filter_delta_pressure_bar,null);
html=plantPage(missing,ui);assert(html.includes('— mg/L'));assert(html.includes('— bar'));assert(!html.includes('NaN'));tests++;
const zero={...data,virtual_plant:{...snapshot,running:false,chans:{...snapshot.chans,p1_bar:0,p2_bar:0,p3_bar:0},
  flow:{inlet_lpm:0,treatment_lpm:0,reuse_lpm:0,drain_lpm:0,backwash_lpm:0},equipment:{feed_pump:'stopped',dosing_pumps:'stopped',irrigation_valve:'closed',drain_valve:'closed'},safety:{state:'HOLD',reasons:['انقطاع الكهرباء']}}};
html=plantPage(zero,ui);assert(!html.includes('plant-pipe flowing'));assert(!html.includes('pump-rotor running'));
assert.equal(plantView(zero).filter_delta_pressure_bar,0);assert(html.includes('plant-chip danger'));assert(html.includes('انقطاع الكهرباء'));tests++;
const bw={...data,virtual_plant:{...snapshot,mode:'backwash',flow:{...snapshot.flow,treatment_lpm:0,drain_lpm:0,backwash_lpm:20},safety:{state:'BACKWASH',reasons:[]}}};
assert.equal(plantView(bw).drain_flow_lpm,20);html=plantPage(bw,{equipment:'drain'});assert(html.includes('الغسيل العكسي'));assert(html.includes('plant-chip warning'));tests++;
const malicious={...data,alarms:[{session_id:'plant-session',title:'<img src=x>',detail:'<script>x</script>',severity:'critical',timestamp:'<bad>'},
 {session_id:'old-session',title:'OLD_OTHER_SESSION'}]};
html=plantPage(malicious,ui);assert(html.includes('&lt;img src=x&gt;'));assert(!html.includes('<script>'));assert(!html.includes('OLD_OTHER_SESSION'));tests++;
assert.deepEqual(Object.keys(PLANT_FAULTS),['none','turbidity','sensor_dropout','clogging','power_loss','valve_stuck']);
assert.equal(JSON.stringify(data),original);tests++;

// Update only data regions. Native controls and the enclosing page stay in
// place, and a focused select keeps its current in-progress choice.
const nodes=new Map();let containerWrites=0,regionWrites=0;
const selectMode={value:'standby',disabled:false},selectFault={value:'none',disabled:false};
const active={dataset:{session:'plant-session'}};
for(const key of ['kpis','diagram','detail','events','process','reasons']) {
 const n={};Object.defineProperty(n,'innerHTML',{set(value){this.markup=value;regionWrites++;}});nodes.set(`[data-plant-region="${key}"]`,n);
}
nodes.set('#plant-screen',active);nodes.set('#plant-mode',selectMode);nodes.set('#plant-fault',selectFault);
const speeds=[1,10,30].map(speed=>({dataset:{speed:String(speed)},disabled:false,setAttribute(name,value){this[name]=value;}}));
const container={set innerHTML(value){containerWrites++;this.markup=value;},querySelector:selector=>nodes.get(selector)||null,querySelectorAll:()=>speeds};
globalThis.document={activeElement:selectMode};
updatePlant(container,data,ui,false);assert.equal(containerWrites,0);assert.equal(selectMode.value,'standby');assert.equal(selectFault.value,'none');
assert.equal(speeds[1]['aria-pressed'],'true');const writes=regionWrites;updatePlant(container,data,ui,false);assert.equal(regionWrites,writes);
assert.equal(containerWrites,0);tests++;
updatePlant(container,data,ui,true);assert(selectMode.disabled);assert(speeds.every(s=>s.disabled));
updatePlant(container,{...data,session:{id:'new-session'}},ui,false);assert.equal(containerWrites,1);assert(container.markup.includes('plant-start'));tests++;
console.log(`${tests} plant UI checks PASS; no network, random values, clock advancement or persisted mutation.`);
