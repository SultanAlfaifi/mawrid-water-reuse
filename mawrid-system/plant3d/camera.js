import * as THREE from '../../mawrid-final/node_modules/three/build/three.module.js';
import {journeyStage} from './journey.js';

// Presentation geometry only. No plant state, flow, controls, or timing of a
// water parcel is inferred by the camera framing.
export function journeyBounds(model,id) {
  const stage=journeyStage(id);
  if(!stage)return null;
  model.root.updateMatrixWorld(true);
  const bounds=new THREE.Box3();
  for(const equipmentId of stage.equipment){
    const equipment=model.equipment.get(equipmentId);
    if(equipment)bounds.union(new THREE.Box3().setFromObject(equipment));
  }
  for(const name of stage.pipes){
    const path=model.pipes.find(pipe=>pipe.name===name);
    if(path)for(const point of path.curve.getPoints(48))bounds.expandByPoint(point);
  }
  for(const label of model.labels)if(stage.labels.includes(label.id))bounds.expandByPoint(label.position);
  return bounds.isEmpty()?null:bounds;
}

export function fitPerspectiveBounds(bounds,{aspect,fov=36,near=.1,padding=.24,minDistance=2.4,direction=[8,10,16],safeExtent=.76}={}) {
  if(!bounds||bounds.isEmpty()||!Number.isFinite(aspect)||aspect<=0||!Number.isFinite(fov)||fov<=0||fov>=175||!Number.isFinite(near)||near<=0) return null;
  const padded=bounds.clone().expandByScalar(Math.max(.05,padding)),target=padded.getCenter(new THREE.Vector3());
  const forward=new THREE.Vector3(...direction);
  if(!forward.lengthSq())return null;
  forward.normalize();
  const right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),forward).normalize();
  if(!right.lengthSq())return null;
  const up=new THREE.Vector3().crossVectors(forward,right),tanV=Math.tan(THREE.MathUtils.degToRad(fov/2)),tanH=tanV*aspect;
  const extent=THREE.MathUtils.clamp(safeExtent,.35,.9);
  let distance=Math.max(near+.5,minDistance);
  for(const x of [padded.min.x,padded.max.x])for(const y of [padded.min.y,padded.max.y])for(const z of [padded.min.z,padded.max.z]){
    const offset=new THREE.Vector3(x,y,z).sub(target),depth=offset.dot(forward);
    distance=Math.max(distance,depth+Math.abs(offset.dot(right))/(tanH*extent),depth+Math.abs(offset.dot(up))/(tanV*extent),depth+near+.3);
  }
  if(!Number.isFinite(distance))return null;
  return {target:target.toArray(),position:target.clone().addScaledVector(forward,distance).toArray(),distance};
}

export function journeyFrame(model,id,aspect) {
  return fitPerspectiveBounds(journeyBounds(model,id),{aspect});
}

export function interpolateFrame(from,to,progress,{reducedMotion=false}={}) {
  const t=reducedMotion?1:THREE.MathUtils.clamp(progress,0,1),ease=t*t*(3-2*t);
  if(t===0||t===1){const frame=t===1?to:from;return {position:[...frame.position],target:[...frame.target]};}
  const mix=(a,b)=>a.map((v,i)=>v+(b[i]-v)*ease);
  return {position:mix(from.position,to.position),target:mix(from.target,to.target)};
}
