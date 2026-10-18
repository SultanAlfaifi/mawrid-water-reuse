import test from 'node:test';
import assert from 'node:assert/strict';
import {createVirtualScene} from './scene.js';
import {adaptState,presentation,EQUIPMENT} from './adapter.js';

function snapshot(){
  const id='12345678-1234-4234-8234-123456789abc';
  return adaptState({app:{hardware_connected:false},source:{id:'virtual_plant',kind:'digital_twin'},session:{id,status:'ready'},
    virtual_plant:{source:'virtual_plant',virtual:true,hardware:false,session_id:id,running:true,
      timestamp:'2042-01-01T01:00:00Z',speed:10,mode:'auto',fault:'none',safety:{state:'REUSE'},
      tanks:{raw:{liters:1500,capacity_liters:3000,level_percent:50},treated:{liters:750,capacity_liters:3000,level_percent:25}},
      equipment:{power:true,feed_pump:'running',reuse_pump:'running',backwash_pump:'stopped',dosing_pumps:'running',inlet_pump:'running',irrigation_feedback:'open',irrigation_command:'open'},
      flow:{inlet_lpm:12,treatment_lpm:625/60,product_lpm:500/60,reuse_lpm:8,drain_lpm:125/60,backwash_lpm:0,overflow_lpm:0},
      volumes:{reuse_liters:123.5,stored_liters:2250},validity:{p1_bar:true,p2_bar:true,p3_bar:true,p4_bar:true},chans:{p1_bar:2,p2_bar:1.7,p3_bar:1.4,p4_bar:1.2}}});
}
const freeze=value=>{if(value&&typeof value==='object'){Object.freeze(value);for(const child of Object.values(value))freeze(child);}return value;};

test('all equipment is selectable, with finite geometry and nonzero pipe segments',()=>{
  const model=createVirtualScene();
  for(const id of Object.keys(EQUIPMENT))assert.ok(model.equipment.has(id),id);
  model.root.traverse(object=>{
    if(object.geometry)for(const attr of Object.values(object.geometry.attributes))for(const v of attr.array)assert.ok(Number.isFinite(v));
    for(const v of [...object.position,...object.scale,...object.quaternion])assert.ok(Number.isFinite(v));
  });
  assert.equal(new Set(model.pipes.map(p=>p.name)).size,model.pipes.length);
  for(const p of model.pipes){assert.ok(p.curve.getLength()>0);for(const segment of p.curve.curves)assert.ok(segment.getLength()>0);}
  model.dispose();
});

test('each moving line uses its exact server flow, with reuse after storage and separate backwash',()=>{
  const model=createVirtualScene(),s=snapshot();model.apply(s);model.update(3,true,.1);
  const paths=Object.fromEntries(model.pipes.map(p=>[p.name,p]));
  assert.equal(paths['product-to-storage'].key,'product');
  for(const name of ['storage-to-reuse','reuse-to-valve','irrigation-out'])assert.equal(paths[name].key,'reuse');
  for(const name of ['wash-from-storage','wash-to-media','wash-to-drain'])assert.equal(paths[name].key,'backwash');
  assert.equal(paths['normal-reject'].key,'drain');assert.equal(paths['overflow-common'].key,'overflow');
  for(const p of model.pipes)assert.equal(p.dots.visible,p.key!==null&&s.flows[p.key]>0,p.name);
  assert.ok(paths['storage-to-reuse'].curve.curves[0].v1.x>model.equipment.get('treated').position.x);
  assert.ok(paths['wash-from-storage'].curve.curves[0].v1.x===model.equipment.get('treated').position.x);
  for(const p of model.pipes.filter(p=>p.dots.visible))for(const value of p.dots.instanceMatrix.array)assert.ok(Number.isFinite(value));
  model.dispose();
});

test('water level follows reported percentage exactly, including empty and unavailable',()=>{
  const model=createVirtualScene(),s=snapshot();model.apply(s);
  assert.equal(model.tanks.raw.water.scale.y,model.tanks.raw.usableHeight*.5);
  assert.equal(model.tanks.treated.water.scale.y,model.tanks.treated.usableHeight*.25);
  assert.ok(Math.abs(model.tanks.raw.usableHeight*Math.PI*.75**2-3)<1e-12);
  s.tanks.raw.percent=100;model.apply(s);assert.equal(model.tanks.raw.water.scale.y,model.tanks.raw.usableHeight);
  s.tanks.raw.percent=0;model.apply(s);assert.equal(model.tanks.raw.water.visible,false);
  s.tanks.raw.percent=null;model.apply(s);assert.equal(model.tanks.raw.water.visible,false);
  model.apply(null);assert.equal(model.tanks.treated.water.visible,false);model.dispose();
});

test('HOLD with zero flows is still even with live transport, with no invented valve movement',()=>{
  const model=createVirtualScene(),s=snapshot();s.state='HOLD';
  for(const key of Object.keys(s.flows))s.flows[key]=0;
  for(const key of Object.keys(s.pumps))s.pumps[key]='stopped';
  s.irrigationCommand='open';s.irrigationFeedback='closed';model.apply(s);
  const handle=model.equipment.get('valve').getObjectByName('irrigation-feedback-handle');
  assert.equal(handle.rotation.y,Math.PI/2);model.update(7,true,10);
  assert.ok(model.pipes.every(p=>!p.dots.visible));assert.ok(model.pumps.every(p=>p.rotor.rotation.x===0));
  assert.equal(handle.rotation.y,Math.PI/2);model.dispose();
});

test('pause or disconnected transport stops motion but preserves actual open feedback',()=>{
  const model=createVirtualScene(),s=snapshot();model.apply(s);model.update(1,true,.1);
  const rotations=model.pumps.map(p=>p.rotor.rotation.x),handle=model.equipment.get('valve').getObjectByName('irrigation-feedback-handle');
  assert.equal(handle.rotation.y,0);
  for(const state of [{connection:'disconnected',snapshot:s,lastSuccessAt:0},{connection:'connected',snapshot:{...s,running:false},lastSuccessAt:100}]){
    const v=presentation(state,100);model.apply(v.snapshot);model.update(2,v.motion,20);
    assert.ok(model.pipes.every(p=>!p.dots.visible));assert.deepEqual(model.pumps.map(p=>p.rotor.rotation.x),rotations);assert.equal(handle.rotation.y,0);
  }
  model.dispose();
});

test('backwash and unknown flows do not borrow treatment rate or inferred inventory',()=>{
  const model=createVirtualScene(),s=snapshot();for(const key of Object.keys(s.flows))s.flows[key]=null;
  s.flows.backwash=20;s.flows.overflow=3;s.pumps.backwash='running';s.pumps.feed='stopped';s.pumps.reuse='stopped';
  model.apply(s);model.update(3,true,.1);
  for(const p of model.pipes)assert.equal(p.dots.visible,['backwash','overflow'].includes(p.key),p.name);
  assert.equal(model.pumps.find(p=>p.id==='feed').rotor.rotation.x,0);assert.ok(model.pumps.find(p=>p.id==='backwash').rotor.rotation.x>0);
  model.dispose();
});

test('render updates cannot accumulate liters, alter equipment decisions or mutate snapshot',()=>{
  const model=createVirtualScene(),s=freeze(snapshot()),before=JSON.stringify(s);model.apply(s);
  for(let i=0;i<80;i++)model.update(i/30,true,1/30);
  assert.equal(JSON.stringify(s),before);assert.equal(model.snapshot.volumes.reuse_liters,123.5);
  assert.equal(model.tanks.raw.water.scale.y,model.tanks.raw.usableHeight*.5);
  model.apply(null);model.update(5,false,.1);assert.equal(model.snapshot,null);assert.ok(model.pipes.every(p=>!p.dots.visible));
  model.dispose();
});
