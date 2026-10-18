import assert from 'node:assert/strict';
import fs from 'node:fs';
import {adaptState,presentation} from '../plant3d/adapter.js';

const fixtures=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let checks=0;
function equal(actual,expected,label){assert.deepEqual(actual,expected,label);checks++;}
let accepted=0;
for(const {name,state} of fixtures){
  const original=JSON.stringify(state);
  const v=adaptState(state), p=state.virtual_plant;
  if(!p){equal(v,null,name+': other source cleared');continue;}
  accepted++;
  equal(v.sessionId,state.session.id,name+': session');
  equal(v.state,p.safety.state,name+': controller state');
  equal(v.timestamp,p.timestamp,name+': virtual clock');
  equal(v.irrigationFeedback,p.equipment.irrigation_feedback,name+': feedback');
  equal(v.irrigationCommand,p.equipment.irrigation_command,name+': command');
  equal(v.complianceValve,p.equipment.compliance_valve,name+': compliance selector');
  equal(v.complianceValve,p.flow.product_lpm>0?'product':'closed',name+': selector is consistent with calculated product flow');
  equal(Object.keys(v.flows).sort(),['inlet','treatment','product','reuse','drain','backwash','overflow','recirculation'].sort(),name+': complete flow schema');
  for(const key of ['inlet','treatment','product','reuse','drain','backwash','overflow','recirculation'])
    equal(v.flows[key],p.flow[key+'_lpm'],name+': '+key);
  equal(v.flows.recirculation,0,name+': design-only return branch has no computed flow');
  equal(v.flows.drain,0,name+': no continuous rejection stage');
  for(const [key,field] of Object.entries({feed:'feed_pump',inlet:'inlet_pump',dosing:'dosing_pumps',reuse:'reuse_pump',backwash:'backwash_pump'}))
    equal(v.pumps[key],p.equipment[field],name+': '+field);
  for(const key of ['raw','treated']){
    equal(v.tanks[key].liters,p.tanks[key].liters,name+': tank liters');
    equal(v.tanks[key].capacity,p.tanks[key].capacity_liters,name+': capacity');
    equal(v.tanks[key].capacity,5000,name+': specified 5m3 tank');
    equal(v.tanks[key].percent,p.tanks[key].level_percent,name+': level');
  }
  const sensors=['turbidity','ph','chlorine','orp','p1_bar','p2_bar','p3_bar','p4_bar'];
  const volumes=['input_liters','reuse_liters','reject_drain_liters','backwash_liters','overflow_liters','stored_liters','treated_product_liters'];
  equal(Object.keys(v.readings).sort(),[...sensors].sort(),name+': complete sensor schema');
  equal(Object.keys(v.volumes).sort(),[...volumes].sort(),name+': complete volume schema');
  for(const key of sensors)equal(v.readings[key],p.validity[key]===true?p.chans[key]:null,name+': '+key);
  for(const key of volumes)equal(v.volumes[key],p.volumes[key],name+': volume '+key);
  equal(v.recovery,1,name+': volume transfer only; not chemical removal');
  equal(p.design_assumptions.rated_feed_lph,1000,name+': specified hourly feed');
  equal(p.design_assumptions.rated_operating_hours_per_day,15,name+': daily capacity basis');
  equal(p.design_assumptions.daily_duty_cycle_enforced,false,name+': no implicit schedule');
  if(p.safety.state==='HOLD'||p.safety.state==='STANDBY')equal(Object.values(v.flows).every(x=>x===0),true,name+': held/standby zero-flow');
  if(p.safety.state==='REUSE')for(const key of ['inlet','treatment','product','reuse'])equal(v.flows[key],1000/60,name+': nominal '+key);
  if(p.safety.state==='BACKWASH')equal(v.flows.backwash,65,name+': specified wash flow');
  const clock={connection:'connected',lastSuccessAt:1000,snapshot:v};
  equal(presentation(clock,1000).motion,p.running===true&&state.session.status==='ready',name+': motion');
  const stale=presentation(clock,10000);
  equal(stale.motion,false,name+': stale stops motion');
  equal(stale.snapshot.irrigationFeedback,p.equipment.irrigation_feedback,name+': stale never invents closed');
  equal(presentation({...clock,connection:'disconnected'},1000).motion,false,name+': disconnected');
  equal(JSON.stringify(state),original,name+': input unchanged');
}
console.log(JSON.stringify({passed:true,checks,fixtures:fixtures.length,acceptedVirtualSnapshots:accepted,scope:'Actual temporary HTTP/SQLite snapshots through source adapter; no browser rendering or ML qualification.'}));
