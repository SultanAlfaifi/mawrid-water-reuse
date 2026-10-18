import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

// All lengths are supplied by unitSpec. Numbers in this file are tessellation,
// angles, normalized proportions, canvas pixels or matrix identities.
export const v3 = (v) => v.isVector3 ? v.clone() : new THREE.Vector3(...v);
export function mesh(parent, geometry, material, position=[0,0,0]) {
  const m=new THREE.Mesh(geometry,material); m.position.copy(v3(position));
  m.castShadow=true; m.receiveShadow=true; parent.add(m); return m;
}
export function box(g,size,pos,mat,radius=0){
  return mesh(g,radius?new RoundedBoxGeometry(...size,3,radius):new THREE.BoxGeometry(...size),mat,pos);
}
export function cyl(g,radius,height,pos,mat,axis='y',segments=48){
  const m=mesh(g,new THREE.CylinderGeometry(radius,radius,height,segments),mat,pos);
  if(axis==='x')m.rotation.z=-Math.PI/2;if(axis==='z')m.rotation.x=Math.PI/2;return m;
}
export function sphere(g,r,pos,mat,scale=[1,1,1]){const m=mesh(g,new THREE.SphereGeometry(r,24,16),mat,pos);m.scale.set(...scale);return m;}
export function torus(g,r,t,pos,mat,axis='y',arc=Math.PI*2){
  const m=mesh(g,new THREE.TorusGeometry(r,t,10,40,arc),mat,pos);if(axis==='y')m.rotation.x=Math.PI/2;if(axis==='x')m.rotation.y=Math.PI/2;return m;
}
export function rod(g,a,b,r,mat,segments=12){a=v3(a);b=v3(b);const m=cyl(g,r,a.distanceTo(b),a.clone().add(b).multiplyScalar(.5),mat,'y',segments);m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.sub(a).normalize());return m;}
export function canvasTexture(draw,w=1024,h=512){const c=document.createElement('canvas');c.width=w;c.height=h;draw(c.getContext('2d'),w,h);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=8;return t;}
export function textPlate(g,text,size,pos,base,options={}){
  const texture=canvasTexture((ctx,w,h)=>{
    ctx.fillStyle=options.bg||'#d9dedb';ctx.fillRect(0,0,w,h);
    if(options.border!==false){ctx.strokeStyle='#84908c';ctx.lineWidth=8;ctx.strokeRect(10,10,w-20,h-20);}
    ctx.fillStyle=options.color||'#243b35';ctx.textAlign='center';ctx.textBaseline='middle';ctx.direction='rtl';
    const lines=Array.isArray(text)?text:[text];ctx.font=`${options.bold?'600':'500'} ${Math.min(h/(lines.length*1.7),w/Math.max(...lines.map(l=>l.length))*1.7)}px Arial`;
    lines.forEach((line,i)=>ctx.fillText(line,w/2,h*(i+.5)/lines.length,w*.92));
  });
  const mat=new THREE.MeshPhysicalMaterial({map:texture,roughness:options.screen?.32:.42,metalness:options.screen?0:.4,emissive:options.screen?'#81b9b3':'#000000',emissiveIntensity:options.screen?.12:0});
  const m=box(g,size,pos,mat);m.userData.texture=texture;return m;
}
export function roundedPath(points,radius){
 const p=points.map(v3),curve=new THREE.CurvePath();let prev=p[0];
 for(let i=1;i<p.length-1;i++){
   const before=p[i-1],c=p[i],after=p[i+1];const r=Math.min(radius,c.distanceTo(before)*.35,c.distanceTo(after)*.35);
   const a=c.clone().add(before.clone().sub(c).normalize().multiplyScalar(r));const b=c.clone().add(after.clone().sub(c).normalize().multiplyScalar(r));
   if(prev.distanceTo(a)>Number.EPSILON)curve.add(new THREE.LineCurve3(prev,a));curve.add(new THREE.QuadraticBezierCurve3(a,c,b));prev=b;
 }
 if(prev.distanceTo(p.at(-1))>Number.EPSILON)curve.add(new THREE.LineCurve3(prev,p.at(-1)));return curve;
}
export function pipeGeometry(points,radius,bend){const curve=roundedPath(points,bend);return {curve,geometry:new THREE.TubeGeometry(curve,Math.max(24,points.length*12),radius,12,false)};}
export function instanced(g,geometry,material,transforms){
 const m=new THREE.InstancedMesh(geometry,material,transforms.length);const dummy=new THREE.Object3D();
 transforms.forEach((t,i)=>{dummy.position.copy(v3(t.position));dummy.scale.set(...(t.scale||[1,1,1]));dummy.rotation.set(...(t.rotation||[0,0,0]));dummy.updateMatrix();m.setMatrixAt(i,dummy.matrix);});
 m.castShadow=true;m.receiveShadow=true;m.instanceMatrix.needsUpdate=true;g.add(m);return m;
}
export function mergeStatic(group){
 // Merge only explicit static structure members, retaining interactive parts.
 const buckets=new Map();group.traverse(o=>{if(o.isMesh&&o.userData.merge){const list=buckets.get(o.material)||[];list.push(o);buckets.set(o.material,list);}});
 for(const [mat,list] of buckets){if(list.length<2)continue;group.updateMatrixWorld(true);const inverse=group.matrixWorld.clone().invert();
   const geometries=list.map(o=>o.geometry.clone().applyMatrix4(inverse.clone().multiply(o.matrixWorld)));
   const merged=mergeGeometries(geometries);if(merged)mesh(group,merged,mat);
   list.forEach(o=>{o.parent.remove(o);o.geometry.dispose();});geometries.forEach(g=>g.dispose());
 }
}
