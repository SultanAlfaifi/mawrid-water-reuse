import * as THREE from '../../mawrid-final/node_modules/three/build/three.module.js';

// Visual dimensions only. Inventory, flow and equipment decisions are supplied
// by the server. The water column is drawn from its reported level percentage.
export function createVirtualScene() {
  const root=new THREE.Group(), equipment=new Map(),labels=[],pipes=[],pumps=[],gauges=[],tanks={};
  root.name='MAWRID virtual process';
  const material=(color,options={})=>new THREE.MeshStandardMaterial({color,roughness:.55,metalness:.1,...options});
  const mats={stone:material('#dfdfd3'),white:material('#f1f0e5'),steel:material('#83938a',{metalness:.72,roughness:.3}),
    green:material('#285e49'),dark:material('#243f36'),pipe:material('#79938b',{metalness:.4}),
    clean:material('#397e77'),drain:material('#ae8152'),wash:material('#7485a1'),carbon:material('#435950'),
    water:new THREE.MeshPhysicalMaterial({color:'#589c92',roughness:.17,metalness:.12,transparent:true,opacity:.78,depthWrite:false}),
    rawWater:new THREE.MeshPhysicalMaterial({color:'#9dba98',roughness:.2,transparent:true,opacity:.83,depthWrite:false}),
    glass:new THREE.MeshPhysicalMaterial({color:'#d7e3d9',metalness:.02,roughness:.22,transparent:true,opacity:.17,depthWrite:false,side:THREE.DoubleSide})};
  function mesh(parent,geometry,mat,position){const o=new THREE.Mesh(geometry,mat);o.position.set(...position);o.castShadow=true;o.receiveShadow=true;parent.add(o);return o;}
  const box=(g,size,position,mat)=>mesh(g,new THREE.BoxGeometry(...size),mat,position);
  function cyl(g,r,h,position,mat,axis='y'){const o=mesh(g,new THREE.CylinderGeometry(r,r,h,36),mat,position);if(axis==='x')o.rotation.z=-Math.PI/2;if(axis==='z')o.rotation.x=Math.PI/2;return o;}
  function rod(g,a,b,r,mat){const start=new THREE.Vector3(...a),end=new THREE.Vector3(...b),o=cyl(g,r,start.distanceTo(end),start.clone().add(end).multiplyScalar(.5).toArray(),mat);o.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),end.sub(start).normalize());return o;}
  function ring(g,r,t,position,mat){const o=mesh(g,new THREE.TorusGeometry(r,t,8,48),mat,position);o.rotation.x=Math.PI/2;return o;}
  function group(id,position){const g=new THREE.Group();g.position.set(...position);g.userData.equipment=id;root.add(g);equipment.set(id,g);return g;}
  function label(id,position,primary=false){labels.push({id,position:new THREE.Vector3(...position),primary});}
  function beacon(g,position){const mat=material('#bcc6ba',{emissive:'#000000',emissiveIntensity:.25});return cyl(g,.055,.11,position,mat);}
  function setLight(o,color){o.material.color.set(color);o.material.emissive.set(color);}

  // A low service deck, floor strips, and pipe supports make the topology legible.
  box(root,[14.7,.15,6.1],[0,-.12,0],mats.stone);
  box(root,[8.1,.12,2.35],[-.6,.03,0],mats.white);
  for(const z of [-2.8,2.8])box(root,[14,.012,.035],[0,-.035,z],mats.green);
  for(let x=-6.8;x<=6.8;x+=.85)box(root,[.008,.006,5.7],[x,-.039,0],material('#cbd1c5'));
  for(const z of [-1.8,1.8])box(root,[14,.006,.008],[0,-.037,z],mats.steel);

  function makeTank(id,x,waterMat){
    const g=group(id,[x,0,0]),r=.75,usableHeight=3/(Math.PI*r*r),base=.25;
    cyl(g,.86,.16,[0,.08,0],mats.steel);cyl(g,.81,.11,[0,.21,0],mats.white);
    cyl(g,.79,1.87,[0,1.17,0],mats.glass);
    for(const y of [.27,.72,1.23,1.74,2.1])ring(g,.795,.028,[0,y,0],mats.white);
    const dome=mesh(g,new THREE.SphereGeometry(.79,40,20,0,Math.PI*2,0,Math.PI/2),mats.white,[0,2.1,0]);dome.scale.y=.22;
    cyl(g,.2,.075,[0,2.3,0],mats.dark);rod(g,[.46,2.17,0],[.46,2.47,0],.035,mats.steel);
    const water=cyl(g,.743,1,[0,base+.5,0],waterMat);water.visible=false;water.castShadow=false;
    // Sight strip and fixed ladder. Neither computes stock or process behavior.
    box(g,[.05,1.76,.04],[.51,1.17,.61],mats.steel);
    for(let i=0;i<=8;i++)box(g,[.11,.008,.02],[.51,.3+i*.21,.64],mats.dark);
    for(const xx of [-.16,.16])rod(g,[xx,.18,-.83],[xx,2.24,-.83],.018,mats.steel);
    for(let i=0;i<7;i++)rod(g,[-.16,.4+i*.26,-.83],[.16,.4+i*.26,-.83],.016,mats.steel);
    const lamp=beacon(g,[.76,1.9,.1]);tanks[id]={water,base,usableHeight,lamp};
    label(id,[x,2.65,0],true);
  }
  makeTank('raw',-5.25,mats.rawWater);makeTank('treated',3.25,mats.water);
  function makePump(id,x,z,scale=1){
    const g=group(id,[x,.12,z]);g.scale.setScalar(scale);
    box(g,[.83,.08,.47],[0,.04,0],mats.steel);box(g,[.47,.09,.35],[.11,.13,0],mats.dark);
    cyl(g,.19,.48,[.13,.36,0],mats.green,'x');cyl(g,.235,.19,[-.22,.36,0],mats.steel,'x');
    for(let i=0;i<7;i++){const fin=box(g,[.44,.024,.08],[.13,.36+Math.sin(i/7*Math.PI*2)*.2,Math.cos(i/7*Math.PI*2)*.2],mats.green);fin.rotation.x=-i/7*Math.PI*2;}
    const rotor=new THREE.Group();rotor.position.set(.385,.36,0);g.add(rotor);
    for(let i=0;i<5;i++){const fin=box(rotor,[.012,.26,.055],[0,0,0],mats.steel);fin.rotation.x=i/5*Math.PI;}
    const lamp=beacon(g,[.08,.61,.1]);pumps.push({id,rotor,lamp});label(id,[x,.99,z],false);return g;
  }
  makePump('feed',-3.8,0);makePump('reuse',4.6,0);makePump('backwash',1.25,-1.65,.9);
  function makeFilter(id,x,carbon=false){
    const g=group(id,[x,.15,0]),mat=carbon?mats.carbon:material('#d4ddc6');
    cyl(g,.46,.15,[0,.1,0],mats.steel);cyl(g,.4,1.52,[0,.93,0],mat);
    const top=mesh(g,new THREE.SphereGeometry(.4,32,18),mat,[0,1.7,0]);top.scale.y=.42;
    for(const y of [.3,.55,.8,1.05,1.3,1.55])ring(g,.405,.016,[0,y,0],mats.steel);
    cyl(g,.16,.17,[0,1.95,0],mats.dark);box(g,[.42,.17,.3],[0,2.04,0],mats.dark);
    rod(g,[-.38,.45,0],[-.38,1.94,0],.05,mats.pipe);rod(g,[.38,.45,0],[.38,1.94,0],.05,mats.pipe);
    label(id,[x,2.55,0],true);
  }
  makeFilter('media',-2.45);makeFilter('carbon',-1.05,true);
  // These are metering pumps, not an invented UV intensity or reactor.
  const dosing=group('dosing',[.45,.13,.05]);
  box(dosing,[1,.08,.76],[0,.07,0],mats.steel);
  for(const x of [-.27,.27]){box(dosing,[.35,.55,.35],[x,.38,0],mats.white);cyl(dosing,.11,.16,[x,.39,.24],mats.green,'z');rod(dosing,[x,.4,.33],[x,.4,.51],.017,mats.dark);rod(dosing,[x,.4,.51],[x,.62,.51],.017,mats.dark);}
  const doseLamp=beacon(dosing,[0,.7,0]);label('dosing',[.45,1.3,.05],true);
  const valve=group('valve',[5.45,.48,0]);
  cyl(valve,.13,.4,[0,0,0],mats.steel,'x');rod(valve,[0,.08,0],[0,.3,0],.03,mats.steel);
  box(valve,[.28,.18,.22],[0,.34,0],mats.dark);
  const handle=box(valve,[.38,.04,.055],[0,.47,0],mats.green),valveLamp=beacon(valve,[0,.57,0]);
  handle.name='irrigation-feedback-handle';
  label('valve',[5.45,1.38,0],true);
  const drain=group('drain',[5.95,0,1.9]);
  box(drain,[.8,.06,.63],[0,.02,0],mats.dark);
  for(let i=0;i<7;i++)box(drain,[.055,.025,.59],[-.32+i*.105,.065,0],mats.steel);
  label('drain',[6.1,.82,1.9],false);label('inlet',[-6.85,.92,0],false);
  const inlet=group('inlet',[-6.7,.48,0]);cyl(inlet,.12,.24,[0,0,0],mats.green,'x');
  for(const x of [-.14,.14])cyl(inlet,.15,.035,[x,0,0],mats.steel,'x');
  for(let i=0;i<5;i++){const x=6.05+i*.2;rod(root,[x,.13,-.25],[x,.13,.25],.025,mats.dark);}

  // Every drawn moving line has one explicit server flow key. Motion is a
  // decorative direction marker, never a flow/stock integration or estimate.
  function pipe(name,key,points,kind='process'){
    const curve=new THREE.CurvePath();const vectors=points.map(p=>new THREE.Vector3(...p));
    for(let i=1;i<vectors.length;i++)curve.add(new THREE.LineCurve3(vectors[i-1],vectors[i]));
    const mat=(kind==='drain'?mats.drain:kind==='wash'?mats.wash:kind==='clean'?mats.clean:mats.pipe).clone();
    const geometry=new THREE.TubeGeometry(curve,Math.max(12,points.length*8),.052,10,false);
    mesh(root,geometry,mat,[0,0,0]);
    for(const p of vectors.slice(1,-1))mesh(root,new THREE.SphereGeometry(.066,14,10),mat,p.toArray());
    const count=Math.max(3,Math.ceil(curve.getLength()/1.0)),dots=new THREE.InstancedMesh(new THREE.SphereGeometry(.07,8,6),material(kind==='drain'?'#e2b66b':'#b0e2d3',{emissive:kind==='drain'?'#b88d44':'#76b8a1',emissiveIntensity:.3}),count);
    dots.visible=false;root.add(dots);pipes.push({name,key,curve,dots,count});
    for(const p of vectors.slice(0,-1))if(p.y>.22)rod(root,[p.x,.12,p.z],[p.x,p.y-.06,p.z],.018,mats.steel);
  }
  pipe('collection','inlet',[[-7,.48,0],[-6.01,.48,0]]);
  pipe('raw-to-feed','treatment',[[-4.5,.48,0],[-4.24,.48,0],[-4.18,.48,0]]);
  pipe('feed-to-media','treatment',[[-3.38,.48,0],[-2.84,.48,0]]);
  pipe('media-to-carbon','treatment',[[-2.06,.48,0],[-1.44,.48,0]]);
  pipe('carbon-to-dosing','treatment',[[-.66,.48,0],[-.12,.48,.56],[.98,.48,.56],[1.3,.48,0]]);
  pipe('product-to-storage','product',[[1.3,.48,0],[1.9,.48,0],[1.9,1.84,0],[2.5,1.84,0]],'clean');
  pipe('normal-reject','drain',[[1.3,.48,0],[1.3,.48,1.75],[5.95,.48,1.75],[5.95,.18,1.9]],'drain');
  pipe('storage-to-reuse','reuse',[[4,.48,0],[4.2,.48,0]],'clean');
  pipe('reuse-to-valve','reuse',[[5,.48,0],[5.25,.48,0]],'clean');
  pipe('irrigation-out','reuse',[[5.65,.48,0],[6.75,.48,0],[6.75,.13,0]],'clean');
  pipe('wash-from-storage','backwash',[[3.25,.42,-.75],[3.25,.42,-1.65],[1.65,.42,-1.65]],'wash');
  pipe('wash-to-media','backwash',[[.87,.42,-1.65],[-2.45,.42,-1.65],[-2.45,.42,-.4]],'wash');
  pipe('wash-to-drain','backwash',[[-2.45,1.9,-.4],[-2.45,1.9,-2.38],[5.95,1.9,-2.38],[5.95,.42,-2.38],[5.95,.42,1.9]],'wash');
  // Individual overflow attribution is not supplied by the current contract.
  // Static branches join one animated shared overflow line with the TOTAL rate.
  pipe('overflow-raw-static',null,[[-5.25,2,-.78],[-5.25,2,-2.7],[-5.25,.38,-2.7],[3.25,.38,-2.7]],'drain');
  pipe('overflow-treated-static',null,[[3.25,2,-.78],[3.25,2,-2.7],[3.25,.38,-2.7]],'drain');
  pipe('overflow-common','overflow',[[3.25,.38,-2.7],[6.45,.38,-2.7],[6.45,.38,1.9],[6,.18,1.9]],'drain');
  function gauge(x,key){const g=new THREE.Group();g.position.set(x,.93,.55);root.add(g);rod(root,[x,.48,.55],[x,.88,.55],.018,mats.steel);cyl(g,.105,.045,[0,0,0],mats.white,'z');ring(g,.1,.012,[0,0,.025],mats.steel).rotation.x=0;const hand=box(g,[.012,.073,.009],[0,.022,.03],mats.dark);gauges.push({key,hand});}
  gauge(-3.05,'p1_bar');gauge(-1.7,'p2_bar');gauge(-.26,'p3_bar');gauge(1.7,'p4_bar');
  const panel=group('panel',[.45,.2,-.85]);box(panel,[.68,1.15,.22],[0,.7,0],mats.white);
  box(panel,[.4,.25,.025],[0,.88,.13],mats.dark);const statusLamp=beacon(panel,[.28,1.42,0]);
  const selection=new THREE.Box3Helper(new THREE.Box3(),0xb89d63);selection.visible=false;root.add(selection);
  root.traverse(o=>{if(o.isMesh){let p=o;while(p&&!p.userData.equipment)p=p.parent;if(p)o.userData.equipment=p.userData.equipment;}});
  const dummy=new THREE.Object3D();let snapshot=null,selected=null;
  function apply(next){
    snapshot=next;
    for(const key of ['raw','treated']){const part=tanks[key],percent=next?.tanks[key].percent;part.water.visible=typeof percent==='number'&&percent>0;
      if(typeof percent==='number'){const h=part.usableHeight*percent/100;part.water.scale.y=Math.max(.0001,h);part.water.position.y=part.base+h/2;}
      setLight(part.lamp,next?'#6d9683':'#bdc9bf');}
    for(const pump of pumps)setLight(pump.lamp,next?.pumps[pump.id]==='running'?'#6ba384':next?.pumps[pump.id]==='stopped'?'#bac3b9':'#d4d4c8');
    setLight(doseLamp,next?.pumps.dosing==='running'?'#6ba384':'#bdc9bf');
    const feedback=next?.irrigationFeedback;
    handle.rotation.y=feedback==='open'?0:feedback==='closed'?Math.PI/2:Math.PI/4;
    setLight(valveLamp,feedback==='open'?'#69a587':feedback==='closed'?'#b39162':'#bdc9bf');
    setLight(statusLamp,({REUSE:'#6ba384',HOLD:'#bb765f',BACKWASH:'#c1a36a',STANDBY:'#a4b0a6'})[next?.state]||'#bdc9bf');
    for(const gauge of gauges){const v=next?.readings[gauge.key];gauge.hand.visible=typeof v==='number';if(typeof v==='number')gauge.hand.rotation.z=Math.PI*.75-Math.max(0,Math.min(5,v))/5*Math.PI*1.5;}
    root.updateMatrixWorld(true);if(selected)select(selected);
  }
  function update(time,motion,dt=0){
    for(const pipe of pipes){const rate=pipe.key?snapshot?.flows[pipe.key]:null;pipe.dots.visible=motion&&typeof rate==='number'&&rate>0;
      if(pipe.dots.visible){for(let i=0;i<pipe.count;i++){const t=(i/pipe.count+time*.2/pipe.curve.getLength())%1;dummy.position.copy(pipe.curve.getPointAt(t));dummy.updateMatrix();pipe.dots.setMatrixAt(i,dummy.matrix);}pipe.dots.instanceMatrix.needsUpdate=true;}}
    if(motion)for(const pump of pumps)if(snapshot?.pumps[pump.id]==='running')pump.rotor.rotation.x+=dt*7;
  }
  function select(id){selected=equipment.has(id)?id:null;selection.visible=!!selected;if(selected)selection.box.setFromObject(equipment.get(selected));}
  function dispose(){const geometries=new Set(),materials=new Set();root.traverse(o=>{if(o.geometry)geometries.add(o.geometry);if(o.material)materials.add(o.material);});geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());}
  apply(null);
  return {root,equipment,labels,pipes,tanks,pumps,apply,update,select,dispose,get snapshot(){return snapshot;}};
}
