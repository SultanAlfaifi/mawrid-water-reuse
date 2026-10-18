import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../../mawrid-final/node_modules/three/build/three.module.js';
import {createVirtualScene} from './scene.js';
import {adaptState,presentation} from './adapter.js';
import {WATER_JOURNEY,isJourneyStage,journeyStage} from './journey.js';
import {overviewDistance} from './labels.js';

function fixture(){
  const id='12345678-1234-4234-8234-123456789abc';
  return adaptState({app:{hardware_connected:false},source:{id:'virtual_plant',kind:'digital_twin'},session:{id,status:'ready'},
    virtual_plant:{source:'virtual_plant',virtual:true,hardware:false,session_id:id,running:true,
      timestamp:'2042-01-01T01:00:00Z',speed:1,mode:'auto',fault:'none',safety:{state:'REUSE'},
      tanks:{raw:{liters:2500,capacity_liters:5000,level_percent:50},treated:{liters:1250,capacity_liters:5000,level_percent:25}},
      equipment:{power:true,feed_pump:'running',reuse_pump:'running',backwash_pump:'stopped',dosing_pumps:'running',inlet_pump:'running',irrigation_feedback:'open',irrigation_command:'open'},
      flow:{inlet_lpm:1000/60,treatment_lpm:1000/60,product_lpm:1000/60,reuse_lpm:1000/60,drain_lpm:0,backwash_lpm:0,overflow_lpm:0,recirculation_lpm:0},
      volumes:{reuse_liters:12,stored_liters:2250},validity:{},chans:{}}});
}
const freeze=value=>{if(value&&typeof value==='object'){Object.freeze(value);for(const child of Object.values(value))freeze(child);}return value;};

test('eight immutable educational stages refer only to existing equipment and measured-flow routes',()=>{
  const model=createVirtualScene(),paths=new Map(model.pipes.map(p=>[p.name,p]));
  assert.deepEqual(Object.keys(WATER_JOURNEY),['collection','media','carbon','polish','verify','uv','storage','irrigation']);
  assert.ok(Object.isFrozen(WATER_JOURNEY));
  for(const [id,stage] of Object.entries(WATER_JOURNEY)){
    assert.equal(isJourneyStage(id),true);assert.equal(journeyStage(id),stage);
    assert.ok(Object.isFrozen(stage));for(const list of Object.values(stage))assert.ok(Object.isFrozen(list));
    for(const equipment of stage.equipment)assert.ok(model.equipment.has(equipment),equipment);
    for(const label of stage.labels)assert.ok(stage.equipment.includes(label),label);
    for(const pipe of stage.pipes){assert.ok(paths.has(pipe),pipe);assert.ok(paths.get(pipe).key,pipe);}
  }
  assert.deepEqual(WATER_JOURNEY.uv.pipes,['compliance-to-uv']);
  assert.deepEqual(WATER_JOURNEY.storage.pipes,['product-to-storage']);
  assert.ok(!WATER_JOURNEY.verify.pipes.includes('compliance-to-uv'));
  for(const value of [null,undefined,1,{},'__proto__','constructor','drain','COLLECTION'])assert.equal(isJourneyStage(value),false);
  model.dispose();
});

test('stage changes do not mutate shared materials, water quantities, feedback, or the manual selection',()=>{
  const model=createVirtualScene(),s=freeze(fixture()),before=JSON.stringify(s),originals=[];
  model.apply(s);model.select('valve');
  const selection=model.root.getObjectByProperty('type','Box3Helper'),selectedBounds=selection.box.clone();
  for(const equipment of model.equipment.values())equipment.traverse(o=>{if(o.isMesh)originals.push({object:o,material:o.material,color:o.material.color.getHex(),geometry:o.geometry});});
  for(const id of Object.keys(WATER_JOURNEY)){
    assert.equal(model.setJourney(id),true);model.update(2,true,0);
    assert.equal(model.journeyStage,id);assert.deepEqual(model.highlightedEquipment,WATER_JOURNEY[id].equipment);assert.deepEqual(model.highlightedPipes,WATER_JOURNEY[id].pipes);
    for(const original of originals){assert.equal(original.object.material,original.material);assert.equal(original.material.color.getHex(),original.color);assert.equal(original.object.geometry,original.geometry);}
    assert.equal(selection.visible,true);assert.ok(selection.box.equals(selectedBounds));assert.equal(JSON.stringify(s),before);
    assert.equal(model.tanks.treated.water.userData.volumeFraction,.25);
    assert.equal(model.equipment.get('valve').getObjectByName('irrigation-feedback-handle').rotation.y,0);
  }
  model.highlightedEquipment.push('invented');assert.ok(!model.highlightedEquipment.includes('invented'));
  assert.equal(model.setJourney('unknown'),false);assert.equal(model.setJourney(undefined),false);assert.equal(model.journeyStage,'irrigation');
  assert.equal(model.setJourney(null),true);assert.equal(model.journeyStage,null);assert.deepEqual(model.highlightedEquipment,[]);assert.deepEqual(model.highlightedPipes,[]);assert.deepEqual(model.journeyMotion,[]);
  assert.equal(model.root.getObjectByName('Educational route highlight').children.length,0);model.dispose();
});

test('educational arrows require each exact flow and live presentation, while static focus survives pause and disconnect',()=>{
  const model=createVirtualScene(),s=fixture();model.apply(s);
  s.flows.inlet=0;s.flows.treatment=12;s.flows.product=null;s.flows.reuse=0;
  for(const id of Object.keys(WATER_JOURNEY)){
    model.setJourney(id);model.update(2,true,0);
    for(const marker of model.journeyMotion)assert.equal(marker.visible,typeof s.flows[marker.key]==='number'&&s.flows[marker.key]>0,marker.name);
  }
  model.setJourney('media');
  for(const transport of [{connection:'connected',snapshot:{...s,running:false},lastSuccessAt:100},{connection:'disconnected',snapshot:s,lastSuccessAt:100}]){
    const view=presentation(transport,101);model.apply(view.snapshot);model.update(3,view.motion,0);
    assert.ok(model.journeyMotion.every(m=>!m.visible));assert.equal(model.journeyStage,'media');assert.ok(model.root.getObjectByName('Educational route highlight').children.length>0);
  }
  for(const value of [0,null,NaN]){s.flows.treatment=value;model.apply(s);model.update(9,true,0);assert.ok(model.journeyMotion.every(m=>!m.visible));}
  model.apply(null);model.update(9,true,0);assert.ok(model.journeyMotion.every(m=>!m.visible));model.dispose();
});

test('educational stage highlights remain within the existing overview framing',()=>{
  const model=createVirtualScene();model.apply(fixture());
  for(const stage of Object.keys(WATER_JOURNEY)){
    model.setJourney(stage);model.update(2,true,0);
    const box=new THREE.Box3().setFromObject(model.root);
    for(const [width,height] of [[340,380],[610,440],[1000,540],[1280,620]]){
      const camera=new THREE.PerspectiveCamera(36,width/height,.1,180),target=new THREE.Vector3(0,.8,0);
      camera.position.copy(target).addScaledVector(new THREE.Vector3(8,10,16).normalize(),overviewDistance(width/height));camera.lookAt(target);camera.updateMatrixWorld();
      for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
        const p=new THREE.Vector3(x,y,z).project(camera);assert.ok(Math.abs(p.x)<1&&Math.abs(p.y)<1&&p.z<1,`${stage} ${width}x${height}: ${p.toArray()}`);
      }
    }
  }
  model.dispose();
});
