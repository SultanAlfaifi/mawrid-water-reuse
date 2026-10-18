import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../../mawrid-final/node_modules/three/build/three.module.js';
import {layoutLabels,overviewDistance} from './labels.js';
import {createVirtualScene} from './scene.js';

function assertVisible(boxes,width,height){
  for(const a of boxes){assert.ok(a.left>=9&&a.top>=9);assert.ok(a.left+a.width<=width-9+1e-9);assert.ok(a.top+a.height<=height-9+1e-9);
    assert.ok([a.leader.x,a.leader.y,a.anchor.x,a.anchor.y].every(Number.isFinite));}
  for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
    const a=boxes[i],b=boxes[j];assert.ok(a.left+a.width+8<=b.left+1e-9||b.left+b.width+8<=a.left+1e-9||a.top+a.height+8<=b.top+1e-9||b.top+b.height+8<=a.top+1e-9,`${a.id} overlaps ${b.id}`);
  }
}
function cameraAt(width,height,angle=0){const camera=new THREE.PerspectiveCamera(36,width/height,.1,180),target=new THREE.Vector3(0,.8,0);
  const direction=new THREE.Vector3(8,10,16).normalize().applyAxisAngle(new THREE.Vector3(0,1,0),angle);camera.position.copy(target).addScaledVector(direction,overviewDistance(width/height));camera.lookAt(target);camera.updateMatrixWorld();return camera;}

test('overlapping filter labels keep full rectangles, anchor leaders and deterministic placement',()=>{
  const items=[{id:'media',x:220,y:180,width:110,height:57},{id:'carbon',x:251,y:184,width:116,height:57},{id:'dosing',x:296,y:225,width:118,height:57}];
  const before=JSON.stringify(items),out=layoutLabels(items,610,440);
  assertVisible(out,610,440);assert.deepEqual(out.map(x=>x.id),items.map(x=>x.id));assert.notEqual(out[0].top,out[1].top);
  assert.deepEqual(out,layoutLabels(items,610,440));assert.equal(JSON.stringify(items),before);
  assert.deepEqual(out[1].anchor,{x:251,y:184});
});

test('all five default scene labels fit without collision across widths and camera orientations',()=>{
  const model=createVirtualScene();
  for(const width of [500,610,720,1000,1280])for(const angle of [-.45,0,.45]){
    const height=440,camera=cameraAt(width,height,angle),items=model.labels.filter(p=>p.primary).map(p=>{const point=p.position.clone().project(camera);return {id:p.id,x:(point.x*.5+.5)*width,y:(-point.y*.5+.5)*height,width:120,height:58};});
    const result=layoutLabels(items,width,height);assert.equal(result.length,5);assertVisible(result,width,height);
  }
  model.dispose();
});

test('compact viewport preserves both tank labels and selected filter without clipping',()=>{
  const model=createVirtualScene(),width=340,height=380,camera=cameraAt(width,height);
  const items=model.labels.filter(p=>['raw','treated','media'].includes(p.id)).map(p=>{const point=p.position.clone().project(camera);return {id:p.id,x:(point.x*.5+.5)*width,y:(-point.y*.5+.5)*height,width:100,height:52};});
  assertVisible(layoutLabels(items,width,height),width,height);model.dispose();
});

test('closer default overview still contains every scene bounding-box corner',()=>{
  const model=createVirtualScene(),box=new THREE.Box3().setFromObject(model.root);
  for(const [width,height] of [[340,380],[610,440],[1000,540],[1280,620]]){
    const camera=cameraAt(width,height);
    for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
      const p=new THREE.Vector3(x,y,z).project(camera);assert.ok(Math.abs(p.x)<1&&Math.abs(p.y)<1&&p.z<1,`${width}x${height}: ${p.toArray()}`);
    }
  }
  model.dispose();
});
