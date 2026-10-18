import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as THREE from '../../mawrid-final/node_modules/three/build/three.module.js';
import {createVirtualScene} from './scene.js';
import {WATER_JOURNEY,isJourneyStage,journeyStage} from './journey.js';
import {journeyBounds,fitPerspectiveBounds,journeyFrame,interpolateFrame} from './camera.js';
import {overviewDistance,layoutLabels} from './labels.js';

function cameraAt(frame,aspect){
  const camera=new THREE.PerspectiveCamera(36,aspect,.1,180);
  camera.position.fromArray(frame.position);camera.lookAt(new THREE.Vector3(...frame.target));camera.updateMatrixWorld();return camera;
}
function corners(box){const out=[];for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z])out.push(new THREE.Vector3(x,y,z));return out;}

test('camera bounds include all equipment, route endpoints and label anchors of each educational stage',()=>{
  const model=createVirtualScene(),sourceGeometry=[];
  for(const equipment of model.equipment.values())equipment.traverse(object=>{if(object.geometry)sourceGeometry.push([object,object.geometry]);});
  for(const [id,stage] of Object.entries(WATER_JOURNEY)){
    const box=journeyBounds(model,id);assert.ok(box&&!box.isEmpty());
    for(const equipmentId of stage.equipment)for(const point of corners(new THREE.Box3().setFromObject(model.equipment.get(equipmentId))))assert.ok(box.containsPoint(point),`${id} includes ${equipmentId}`);
    for(const name of stage.pipes)for(const point of model.pipes.find(path=>path.name===name).curve.getPoints(48))assert.ok(box.containsPoint(point),`${id} includes ${name}`);
    for(const label of model.labels.filter(label=>stage.labels.includes(label.id)))assert.ok(box.containsPoint(label.position));
  }
  assert.equal(journeyBounds(model,'unknown'),null);assert.equal(journeyBounds(model,null),null);
  for(const [object,geometry] of sourceGeometry)assert.equal(object.geometry,geometry);
  assert.equal(model.journeyStage,null);assert.equal(model.snapshot,null);model.dispose();
});

test('all eight focused stages fit portrait, tablet, desktop and ultrawide viewports with near-plane and label margins',()=>{
  const model=createVirtualScene();
  for(const [width,height] of [[280,440],[340,315],[391,600],[610,440],[1000,540],[1600,540]])for(const id of Object.keys(WATER_JOURNEY)){
    const box=journeyBounds(model,id),frame=journeyFrame(model,id,width/height),camera=cameraAt(frame,width/height);
    assert.ok(frame.distance<overviewDistance(width/height),`${id} is closer than overview at ${width}×${height}`);
    assert.ok(frame.distance>=2.4&&frame.position.every(Number.isFinite)&&frame.target.every(Number.isFinite));
    for(const point of corners(box)){
      const p=point.clone().project(camera);
      assert.ok(Math.abs(p.x)<.77&&Math.abs(p.y)<.77&&p.z>-1&&p.z<1,`${id} ${width}×${height}: ${p.toArray()}`);
    }
    const annotations=model.labels.filter(label=>WATER_JOURNEY[id].labels.includes(label.id)).map(label=>{
      const p=label.position.clone().project(camera);return {id:label.id,x:(p.x*.5+.5)*width,y:(-p.y*.5+.5)*height,width:130,height:38};
    });
    for(const label of layoutLabels(annotations,width,height))assert.ok(label.left>=9&&label.top>=9&&label.left+label.width<=width-9+1e-8&&label.top+label.height<=height-9+1e-8,`${id} label stays inside`);
  }
  model.dispose();
});

test('framing handles off-centre and buried bounds without mutating inputs and rejects unavailable geometry',()=>{
  const bounds=new THREE.Box3(new THREE.Vector3(-9,-2,-1),new THREE.Vector3(-4,2,2)),before=bounds.clone(),options={aspect:.45};
  const frame=fitPerspectiveBounds(bounds,options),camera=cameraAt(frame,options.aspect);
  for(const point of corners(bounds)){const p=point.clone().project(camera);assert.ok(Math.abs(p.x)<.77&&Math.abs(p.y)<.77&&p.z>-1&&p.z<1);}
  assert.ok(bounds.equals(before));assert.ok(frame.target[0]<-4&&frame.target[0]>-9);
  for(const invalid of [null,new THREE.Box3()])assert.equal(fitPerspectiveBounds(invalid,options),null);
  for(const aspect of [undefined,0,-1,NaN,Infinity])assert.equal(fitPerspectiveBounds(bounds,{aspect}),null);
  assert.equal(fitPerspectiveBounds(bounds,{aspect:1,direction:[0,0,0]}),null);
  assert.equal(fitPerspectiveBounds(bounds,{aspect:1,direction:[0,1,0]}),null);
  assert.equal(fitPerspectiveBounds(bounds,{aspect:1,fov:180}),null);
});

test('camera transitions ease to an exact endpoint, clamp progress and snap with reduced motion',()=>{
  const from={position:[0,12,24],target:[0,.8,0]},to={position:[-2,4,6],target:[-6,-.2,0]},before=JSON.stringify([from,to]);
  assert.deepEqual(interpolateFrame(from,to,0),from);assert.deepEqual(interpolateFrame(from,to,-1),from);
  assert.deepEqual(interpolateFrame(from,to,1),to);assert.deepEqual(interpolateFrame(from,to,3),to);
  assert.deepEqual(interpolateFrame(from,to,0,{reducedMotion:true}),to);
  const middle=interpolateFrame(from,to,.5);assert.deepEqual(middle.position,[-1,8,15]);assert.ok(Math.abs(middle.target[1]-.3)<1e-12);assert.equal(middle.target[0],-3);assert.equal(middle.target[2],0);
  const early=interpolateFrame(from,to,.1);assert.ok(early.position[0]>-.2,'easing starts more slowly than linear movement');
  assert.equal(JSON.stringify([from,to]),before);
});

// Run the actual main.js camera/message handlers with geometry and a small
// DOM surface, so acknowledgements are checked without substituting WebGL.
function cameraHarness(){
  const source=fs.readFileSync(new URL('./main.js',import.meta.url),'utf8'),model=createVirtualScene(),messages=[],camera=new THREE.PerspectiveCamera(36,1,.1,180),target=new THREE.Vector3(0,.8,0);
  camera.position.set(8,10,16);const controls={target,update(){camera.lookAt(target);camera.updateMatrixWorld();}};
  const classes=new Set(),classList={add(name){classes.add(name);},remove(name){classes.delete(name);},contains(name){return classes.has(name);},toggle(name,on){if(on)classes.add(name);else classes.delete(name);}};
  const parent={postMessage(message){messages.push(message);}},context=vm.createContext({THREE,journeyFrame,interpolateFrame,overviewDistance,isJourneyStage,journeyStage,model,camera,controls,viewport:{clientWidth:1000,clientHeight:540},renderer:{setSize(){}},document:{hidden:false,body:{dataset:{},classList}},window:{parent},location:{origin:'http://127.0.0.1:8787'},performance:{now:()=>context.now},now:10,embedded:true,simple:false,selected:'raw',labelNodes:new Map(),activeJourney:null,webglAvailable:true,reduced:false,cameraMode:'overview',cameraStage:null,cameraTransition:null,cameraRequestId:null,focusInterrupted:false});
  vm.runInContext(source.slice(source.indexOf('function setJourney('),source.indexOf('\nfor(const [id,[tag,title]]'))+'\n'+source.slice(source.indexOf('function postParent('),source.indexOf('\nfunction zoom(')),context);
  return {context,model,messages,run(code){return vm.runInContext(code,context);},dispose(){model.dispose();}};
}

test('actual camera handler acknowledges the latest request only after arrival and repeats do not restart movement',()=>{
  const h=cameraHarness();
  h.run("setJourney('media','focus',41)");assert.equal(h.context.document.body.dataset.cameraTransition,'moving');assert.equal(h.messages.length,0);
  const started=h.run('cameraTransition.started');h.context.now=200;
  h.run("setJourney('media','focus',42)");assert.equal(h.run('cameraTransition.started'),started);assert.equal(h.messages.length,0);
  h.run('settleCamera()');assert.equal(h.messages.at(-1).requestId,42);assert.equal(h.messages.at(-1).id,'media');assert.equal(h.context.document.body.dataset.cameraTransition,'settled');
  h.model.select('valve');h.context.selected='valve';h.context.document.body.classList.add('equipment-selected');
  assert.equal(h.model.root.getObjectByProperty('type','Box3Helper').visible,true);
  const frame=h.run('JSON.stringify(currentFrame())');h.run("setJourney('media','focus','resume-43')");assert.equal(h.run('cameraTransition'),null);assert.equal(h.run('JSON.stringify(currentFrame())'),frame);assert.equal(h.messages.at(-1).requestId,'resume-43');
  assert.equal(h.context.document.body.classList.contains('equipment-selected'),false);assert.equal(h.model.root.getObjectByProperty('type','Box3Helper').visible,false);assert.equal(h.context.selected,'valve');
  h.run("setJourney('unknown','focus',44)");assert.equal(h.run('cameraRequestId'),'resume-43');assert.equal(h.run('cameraStage'),'media');h.dispose();
});

test('actual camera handler cancels on manual interaction, resumes focus, and tolerates hidden or unavailable WebGL',()=>{
  const h=cameraHarness();h.run("setJourney('collection','focus',1)");h.run('manualCamera()');
  assert.equal(h.run('cameraTransition'),null);assert.equal(h.messages.at(-1).type,'mawrid:camera-interaction');
  h.context.now=300;h.run("setJourney('collection','focus',2)");assert.equal(h.run('cameraTransition.started'),300);
  h.context.viewport.clientWidth=340;h.run('resize()');assert.equal(h.run('cameraTransition.started'),300);assert.equal(h.context.document.body.dataset.cameraTransition,'moving');
  h.run('settleCamera()');assert.equal(h.messages.at(-1).requestId,2);
  h.context.webglAvailable=false;h.run("setJourney('uv','focus',3)");assert.equal(h.context.document.body.dataset.cameraTransition,'settled');assert.equal(h.messages.at(-1).requestId,3);assert.equal(h.messages.at(-1).id,'uv');
  h.context.webglAvailable=true;h.context.document.hidden=true;h.run("setJourney('irrigation','focus',4)");assert.equal(h.run('cameraTransition'),null);assert.equal(h.messages.at(-1).requestId,4);
  h.context.document.hidden=false;h.run("setJourney(null,'overview',5)");assert.equal(h.context.document.body.dataset.cameraMode,'overview');assert.equal(h.context.document.body.dataset.cameraStage,'');h.run('settleCamera()');assert.equal(h.messages.at(-1).id,null);assert.equal(h.messages.at(-1).requestId,5);h.dispose();
});
