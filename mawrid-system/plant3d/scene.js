import * as THREE from '../../mawrid-final/node_modules/three/build/three.module.js';
import {isJourneyStage,journeyStage} from './journey.js';

// Visual dimensions only. Inventory, flow and equipment decisions are supplied
// by the server. The water column is drawn from its reported level percentage.
export function createVirtualScene() {
  const root=new THREE.Group(), equipment=new Map(),labels=[],pipes=[],pumps=[],gauges=[],tanks={};
  root.name='MAWRID virtual process';
  const material=(color,options={})=>new THREE.MeshStandardMaterial({color,roughness:.55,metalness:.1,...options});
  const mats={stone:material('#dfdfd3'),white:material('#f1f0e5'),steel:material('#83938a',{metalness:.72,roughness:.3}),
    green:material('#285e49'),dark:material('#243f36'),pipe:material('#79938b',{metalness:.4}),
    clean:material('#845ba0'),drain:material('#ae8152'),wash:material('#7485a1'),carbon:material('#435950'),
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
  // Leave the raw-tank opening out of the ground slab. The cut-away makes a
  // buried vessel and submerged pump visible; it is not an excavation design.
  box(root,[13.5,.15,6.8],[2.35,-.12,0],mats.stone);
  box(root,[9.1,.12,2.4],[-.25,.03,0],mats.white);
  box(root,[2.6,.12,2.65],[-6,-1.83,0],mats.stone);
  box(root,[.12,1.8,2.65],[-7.24,-.9,0],mats.stone);
  box(root,[.12,1.8,2.65],[-4.76,-.9,0],mats.stone);
  box(root,[2.6,1.8,.12],[-6,-.9,-1.27],mats.stone);
  for(const z of [-3.1,3.1])box(root,[16.6,.012,.035],[.7,-.035,z],mats.green);
  for(let x=-4.2;x<=8.8;x+=.85)box(root,[.008,.006,6.2],[x,-.039,0],material('#cbd1c5'));

  const raw=group('raw',[-6,0,0]),rawBase=-1.65,rawArea=2.56,rawHeight=5/rawArea;
  box(raw,[1.72,rawHeight+.1,1.72],[0,rawBase+rawHeight/2,0],mats.glass);
  for(const y of [rawBase,rawBase+.65,rawBase+1.3,rawBase+rawHeight]){
    for(const z of [-.86,.86])box(raw,[1.76,.055,.045],[0,y,z],mats.white);
    for(const x of [-.86,.86])box(raw,[.045,.055,1.76],[x,y,0],mats.white);
  }
  // Transparent cut-away bands expose storage without assigning water quality.
  const rawWater=box(raw,[1.6,1,1.6],[0,rawBase+.5,0],mats.rawWater);rawWater.visible=false;
  cyl(raw,.3,.1,[0,rawBase+rawHeight+.13,0],mats.dark);
  rod(raw,[.62,rawBase+rawHeight,0],[.62,.75,0],.035,mats.steel);
  const rawLamp=beacon(raw,[.78,.55,.1]);
  tanks.raw={water:rawWater,base:rawBase,usableHeight:rawHeight,lamp:rawLamp,geometry:'rectangular-cutaway',capacityM3:5};
  label('raw',[-6,1.1,0],true);

  const treated=group('treated',[5,0,0]),tankRadius=.85,tankLength=5/(Math.PI*tankRadius*tankRadius),tankCenter=1.1;
  for(const x of [-.75,.75])box(treated,[.25,.35,1.55],[x,.18,0],mats.steel);
  cyl(treated,tankRadius+.04,tankLength,[0,tankCenter,0],mats.glass,'x');
  for(const x of [-tankLength/2,-.65,0,.65,tankLength/2]){
    const band=ring(treated,tankRadius+.045,.035,[x,tankCenter,0],mats.white);band.rotation.z=Math.PI/2;
  }
  cyl(treated,.18,.09,[0,tankCenter+tankRadius+.05,0],mats.dark);
  rod(treated,[.65,tankCenter+tankRadius,0],[.65,2.3,0],.035,mats.steel);
  const treatedWater=mesh(treated,new THREE.BufferGeometry(),mats.water,[0,tankCenter,0]);treatedWater.visible=false;
  const treatedLamp=beacon(treated,[1.05,1.8,.3]);
  tanks.treated={water:treatedWater,base:tankCenter-tankRadius,usableHeight:2*tankRadius,
    lamp:treatedLamp,geometry:'horizontal-cylinder',radius:tankRadius,length:tankLength,capacityM3:5,lastPercent:null};
  label('treated',[5,2.65,0],true);
  function horizontalWater(part,percent){
    if(part.lastPercent===percent)return;part.lastPercent=percent;
    const f=Math.max(0,Math.min(1,percent/100)),r=part.radius;
    // Invert circular-segment volume. This converts reported inventory to a
    // drawing only; the viewer never integrates or changes the fluid stock.
    let low=-r,high=r;
    for(let i=0;i<48;i++){const h=(low+high)/2,area=r*r*(Math.asin(h/r)+Math.PI/2)+h*Math.sqrt(Math.max(0,r*r-h*h));if(area/(Math.PI*r*r)<f)low=h;else high=h;}
    const h=(low+high)/2,theta=Math.asin(h/r),half=Math.sqrt(Math.max(0,r*r-h*h)),shape=new THREE.Shape();
    shape.moveTo(-half,h);shape.lineTo(half,h);shape.absarc(0,0,r,theta,Math.PI-theta,true);shape.closePath();
    const geometry=new THREE.ExtrudeGeometry(shape,{depth:part.length,bevelEnabled:false,curveSegments:40});
    geometry.rotateY(Math.PI/2);geometry.translate(-part.length/2,0,0);
    part.water.geometry.dispose();part.water.geometry=geometry;
    part.water.userData.volumeFraction=f;part.water.userData.fillHeight=h+r;
  }
  function makePump(id,x,z,scale=1){
    const g=group(id,[x,.12,z]);g.scale.setScalar(scale);
    box(g,[.83,.08,.47],[0,.04,0],mats.steel);box(g,[.47,.09,.35],[.11,.13,0],mats.dark);
    cyl(g,.19,.48,[.13,.36,0],mats.green,'x');cyl(g,.235,.19,[-.22,.36,0],mats.steel,'x');
    for(let i=0;i<7;i++){const fin=box(g,[.44,.024,.08],[.13,.36+Math.sin(i/7*Math.PI*2)*.2,Math.cos(i/7*Math.PI*2)*.2],mats.green);fin.rotation.x=-i/7*Math.PI*2;}
    const rotor=new THREE.Group();rotor.position.set(.385,.36,0);g.add(rotor);
    for(let i=0;i<5;i++){const fin=box(rotor,[.012,.26,.055],[0,0,0],mats.steel);fin.rotation.x=i/5*Math.PI;}
    const lamp=beacon(g,[.08,.61,.1]);pumps.push({id,rotor,lamp});label(id,[x,.99,z],false);return g;
  }
  const feed=group('feed',[-5.65,-1.4,.2]);
  cyl(feed,.16,.43,[0,.23,0],mats.steel);box(feed,[.36,.06,.36],[0,.02,0],mats.dark);
  const subRotor=new THREE.Group();feed.add(subRotor);subRotor.position.set(0,.12,0);
  for(let i=0;i<4;i++){const fin=box(subRotor,[.25,.025,.05],[0,0,0],mats.green);fin.rotation.y=i*Math.PI/4;}
  pumps.push({id:'feed',rotor:subRotor,lamp:beacon(feed,[.2,.44,0])});
  label('feed',[-5.65,-.5,.55],false);
  makePump('reuse',7,0);makePump('backwash',3.5,-1.75,.85);
  function makeFilter(id,x,carbon=false){
    const g=group(id,[x,.15,0]),mat=carbon?mats.carbon:material('#d4ddc6');
    cyl(g,.46,.15,[0,.1,0],mats.steel);cyl(g,.4,1.52,[0,.93,0],mat);
    const top=mesh(g,new THREE.SphereGeometry(.4,32,18),mat,[0,1.7,0]);top.scale.y=.42;
    for(const y of [.3,.55,.8,1.05,1.3,1.55])ring(g,.405,.016,[0,y,0],mats.steel);
    cyl(g,.16,.17,[0,1.95,0],mats.dark);box(g,[.42,.17,.3],[0,2.04,0],mats.dark);
    rod(g,[-.38,.45,0],[-.38,1.94,0],.05,mats.pipe);rod(g,[.38,.45,0],[.38,1.94,0],.05,mats.pipe);
    label(id,[x,2.55,0],true);
  }
  makeFilter('media',-3.2);makeFilter('carbon',-1.25,true);
  // Four distinct design dosing units: no computed chemical consumption,
  // independent pump feedback or numerical dose is invented by this scene.
  const doseLamps=[];
  for(const [id,x] of [['dose_pre',-4.25],['dose_dechlor',-2.2],['dose_ph',1],['dose_final',1.7]]){
    const g=group(id,[x,.12,1.1]);g.userData.designOnly=true;
    cyl(g,.23,.6,[0,.32,0],mats.white);cyl(g,.07,.05,[0,.65,0],mats.dark);
    box(g,[.26,.21,.2],[0,.78,0],mats.green);
    rod(g,[0,.8,0],[0,1.05,0],.013,mats.green);rod(g,[0,1.05,0],[0,1.05,-1.1],.013,mats.green);
    rod(g,[0,1.05,-1.1],[0,.43,-1.1],.013,mats.green);
    doseLamps.push(beacon(g,[.17,.83,0]));label(id,[x,1.48,1.1],false);
  }
  const dosing=group('dosing',[-.45,.1,1.5]);dosing.userData.designOnly=true;
  box(dosing,[.38,.2,.15],[0,.1,0],mats.white); // compatibility aggregate, no process bypass
  const cartridge=group('cartridge',[.35,.15,0]);cartridge.userData.designOnly=true;
  cyl(cartridge,.22,1.28,[0,.74,0],mats.white);cyl(cartridge,.29,.14,[0,1.43,0],mats.dark);
  for(const x of [-.1,.1])cyl(cartridge,.055,1.03,[x,.73,.16],mats.steel);
  label('cartridge',[.35,2.02,0],false);
  const compliance=group('compliance',[2.25,.55,0]);
  cyl(compliance,.13,.37,[0,0,0],mats.steel,'x');cyl(compliance,.1,.23,[0,0,.13],mats.steel,'z');
  box(compliance,[.25,.23,.22],[0,.28,0],mats.dark);
  const complianceLamp=beacon(compliance,[0,.47,0]);label('compliance',[2.25,1.45,0],false);
  const uv=group('uv',[3.1,.55,0]);uv.userData.designOnly=true;
  cyl(uv,.17,.83,[0,0,0],mats.steel,'x');box(uv,[.3,.25,.18],[0,.35,.1],mats.white);
  label('uv',[3.1,1.65,0],false);
  const strainer=group('strainer',[-7.6,.3,0]);strainer.userData.designOnly=true;
  box(strainer,[.32,.3,.35],[0,0,0],mats.steel);
  for(let i=0;i<5;i++)rod(strainer,[-.12+i*.06,-.12,.18],[-.12+i*.06,.12,.18],.008,mats.dark);
  label('strainer',[-7.6,.9,0],false);
  const pilot=group('pilot',[-1.25,.15,-1.3]);pilot.userData.designOnly=true;
  cyl(pilot,.12,1.1,[0,.63,0],mats.glass);cyl(pilot,.1,.8,[0,.5,0],mats.carbon);
  label('pilot',[-1.25,1.65,-1.3],false);
  const flowMeter=group('flow_meter',[-4.85,.55,.09]);
  cyl(flowMeter,.1,.21,[0,0,0],mats.green,'x');box(flowMeter,[.18,.19,.12],[0,.2,0],mats.dark);
  label('flow_meter',[-4.85,1.07,.09],false);
  const orp=group('orp',[-1.85,.55,0]);orp.userData.designOnly=true;
  rod(orp,[0,0,0],[0,.32,0],.025,mats.steel);box(orp,[.16,.16,.1],[0,.4,0],mats.dark);
  label('orp',[-1.85,1.3,0],false);
  const valve=group('valve',[8,.48,0]);
  cyl(valve,.13,.4,[0,0,0],mats.steel,'x');rod(valve,[0,.08,0],[0,.3,0],.03,mats.steel);
  box(valve,[.28,.18,.22],[0,.34,0],mats.dark);
  const handle=box(valve,[.38,.04,.055],[0,.47,0],mats.green),valveLamp=beacon(valve,[0,.57,0]);
  handle.name='irrigation-feedback-handle';
  label('valve',[8,1.38,0],true);
  const drain=group('drain',[8.2,0,2.4]);
  box(drain,[.8,.06,.63],[0,.02,0],mats.dark);
  for(let i=0;i<7;i++)box(drain,[.055,.025,.59],[-.32+i*.105,.065,0],mats.steel);
  label('drain',[8.2,.82,2.4],false);label('inlet',[-8.35,.9,0],false);
  const inlet=group('inlet',[-8.35,.3,0]);cyl(inlet,.12,.24,[0,0,0],mats.green,'x');
  for(const x of [-.14,.14])cyl(inlet,.15,.035,[x,0,0],mats.steel,'x');
  for(let i=0;i<5;i++){const x=8.5+i*.15;rod(root,[x,.13,-.25],[x,.13,.25],.025,mats.dark);}

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
  pipe('collection','inlet',[[-8.6,.3,0],[-7.77,.3,0]]);
  pipe('screen-to-raw','inlet',[[-7.43,.3,0],[-6.86,.3,0]]);
  pipe('raw-to-feed','treatment',[[-5.65,-1.5,.2],[-5.65,-1.2,.2]]);
  pipe('feed-to-media','treatment',[[-5.65,-.96,.2],[-5.65,.55,.2],[-4.25,.55,0],[-3.6,.55,0]]);
  pipe('media-to-carbon','treatment',[[-2.8,.55,0],[-2.2,.55,0],[-1.65,.55,0]]);
  pipe('carbon-to-cartridge','treatment',[[-.85,.55,0],[.12,.55,0]]);
  pipe('cartridge-to-compliance','treatment',[[.58,.55,0],[1,.55,0],[1.7,.55,0],[2.05,.55,0]]);
  pipe('compliance-to-uv','product',[[2.45,.55,0],[2.67,.55,0]],'clean');
  pipe('product-to-storage','product',[[3.53,.55,0],[3.75,.55,0],[3.75,1.1,0],[3.89,1.1,0]],'clean');
  // Return and pilot are honest design paths, with no fabricated circulation.
  pipe('compliance-return-design',null,[[2.25,.55,.23],[2.25,.55,2.75],[-5.9,.55,2.75],[-5.9,.55,.86]],'process');
  pipe('pilot-in-design',null,[[-1.8,.55,0],[-1.8,.55,-1.3],[-1.37,.55,-1.3]]);
  pipe('pilot-return-design',null,[[-1.25,.25,-1.42],[-1.25,.25,-2.05],[-6,.25,-2.05],[-6,.25,-.86]]);
  pipe('storage-to-reuse','reuse',[[6.11,.48,0],[6.56,.48,0]],'clean');
  pipe('reuse-to-valve','reuse',[[7.4,.48,0],[7.8,.48,0]],'clean');
  pipe('irrigation-out','reuse',[[8.2,.48,0],[9.05,.48,0],[9.05,.13,0]],'clean');
  pipe('wash-from-storage','backwash',[[5,.42,-.75],[5,.42,-1.75],[3.86,.42,-1.75]],'wash');
  pipe('wash-to-media','backwash',[[3.14,.42,-1.75],[-3.2,.42,-1.75],[-3.2,.42,-.4]],'wash');
  pipe('wash-to-drain','backwash',[[-3.2,1.9,-.4],[-3.2,1.9,-2.55],[8.2,1.9,-2.55],[8.2,.42,-2.55],[8.2,.42,2.4]],'wash');
  pipe('carbon-wash-design',null,[[-1.25,1.9,-.4],[-1.25,1.9,-2.55]],'wash');
  // Individual overflow attribution is not supplied by the current contract.
  // Static branches join one animated shared overflow line with the TOTAL rate.
  pipe('overflow-raw-static',null,[[-6,.28,-.86],[-6,.28,-2.95],[5,.28,-2.95]],'drain');
  pipe('overflow-treated-static',null,[[5,1.85,-.5],[5,1.85,-2.95],[5,.28,-2.95]],'drain');
  pipe('overflow-common','overflow',[[5,.28,-2.95],[8.6,.28,-2.95],[8.6,.28,2.4],[8.2,.18,2.4]],'drain');
  function gauge(x,key){const g=new THREE.Group();g.position.set(x,.93,.55);root.add(g);rod(root,[x,.55,0],[x,.55,.55],.018,mats.steel);rod(root,[x,.55,.55],[x,.88,.55],.018,mats.steel);cyl(g,.105,.045,[0,0,0],mats.white,'z');ring(g,.1,.012,[0,0,.025],mats.steel).rotation.x=0;const hand=box(g,[.012,.073,.009],[0,.022,.03],mats.dark);gauges.push({key,hand});}
  gauge(-3.85,'p1_bar');gauge(-2.6,'p2_bar');gauge(-.55,'p3_bar');gauge(.75,'p4_bar');
  // Product sample panel and ORP location are design markers. Sensor numbers
  // remain the server's illustrative channels; no new readings are generated.
  const sample=group('quality',[2,.2,-.8]);sample.userData.designOnly=true;
  box(sample,[.65,.82,.14],[0,.43,0],mats.white);
  for(let i=0;i<4;i++)cyl(sample,.035,.28,[-.23+i*.15,.42,.12],mats.steel);
  label('quality',[2,1.45,-.8],false);
  const panel=group('panel',[-.1,.2,-1.35]);box(panel,[.68,1.15,.22],[0,.7,0],mats.white);
  box(panel,[.4,.25,.025],[0,.88,.13],mats.dark);const statusLamp=beacon(panel,[.28,1.42,0]);
  label('panel',[-.1,2.0,-1.35],false);
  const selection=new THREE.Box3Helper(new THREE.Box3(),0xb89d63);selection.visible=false;root.add(selection);
  root.traverse(o=>{if(o.isMesh){let p=o;while(p&&!p.userData.equipment)p=p.parent;if(p)o.userData.equipment=p.userData.equipment;}});
  const dummy=new THREE.Object3D();let snapshot=null,selected=null;
  // A separate educational layer keeps original shared materials, sensor lamps,
  // selections and geometry untouched. It is not a hydraulic calculation.
  const journeyLayer=new THREE.Group();journeyLayer.name='Educational route highlight';root.add(journeyLayer);
  let activeJourney=null,journeyMarkers=[];
  const journeyGeometries=new Set(),journeyMaterials=new Set();
  const signalMeshes=new Set([rawLamp,treatedLamp,valveLamp,statusLamp,complianceLamp,...doseLamps,...pumps.map(p=>p.lamp),tanks.raw.water,tanks.treated.water,handle]);
  for(const pump of pumps)pump.rotor.traverse(object=>signalMeshes.add(object));
  function clearJourney(){
    journeyLayer.clear();journeyGeometries.forEach(g=>g.dispose());journeyMaterials.forEach(m=>m.dispose());
    journeyGeometries.clear();journeyMaterials.clear();journeyMarkers=[];
  }
  function ownGeometry(geometry){journeyGeometries.add(geometry);return geometry;}
  function ownMaterial(mat){journeyMaterials.add(mat);return mat;}
  function setJourney(id){
    if(id!==null&&!isJourneyStage(id))return false;
    if(id===activeJourney)return true;
    clearJourney();activeJourney=id;
    const stage=journeyStage(id);if(!stage)return true;
    root.updateMatrixWorld(true);
    const inverseRoot=root.matrixWorld.clone().invert();
    const bodyMaterial=ownMaterial(new THREE.MeshBasicMaterial({color:'#e7aa3b',transparent:true,opacity:.19,depthWrite:false,side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1}));
    const edgeMaterial=ownMaterial(new THREE.LineBasicMaterial({color:'#087a71',transparent:true,opacity:.95,depthTest:false}));
    const ringMaterial=ownMaterial(new THREE.MeshBasicMaterial({color:'#d59020',transparent:true,opacity:.94,depthWrite:false}));
    for(const equipmentId of stage.equipment){
      const target=equipment.get(equipmentId);if(!target)continue;
      target.traverse(object=>{
        if(!object.isMesh||!object.visible||signalMeshes.has(object))return;
        // Reuse geometry read-only; only our own materials are disposed on a
        // stage change. A transparent overlay preserves actual lamp feedback.
        const glow=new THREE.Mesh(object.geometry,bodyMaterial);
        glow.matrix.copy(inverseRoot).multiply(object.matrixWorld);glow.matrixAutoUpdate=false;glow.renderOrder=3;journeyLayer.add(glow);
      });
      const bounds=new THREE.Box3().setFromObject(target),size=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3());
      const boxGeometry=new THREE.BoxGeometry(...size.toArray()),edges=ownGeometry(new THREE.EdgesGeometry(boxGeometry));boxGeometry.dispose();
      const outline=new THREE.LineSegments(edges,edgeMaterial);
      outline.position.copy(center);outline.renderOrder=4;journeyLayer.add(outline);
      const radius=Math.max(.18,Math.min(1.32,Math.max(size.x,size.z)*.62));
      const halo=mesh(journeyLayer,ownGeometry(new THREE.TorusGeometry(radius,.025,8,64)),ringMaterial,[center.x,Math.max(.09,bounds.min.y+.025),center.z]);
      halo.rotation.x=Math.PI/2;halo.castShadow=false;halo.receiveShadow=false;halo.renderOrder=3;
    }
    const routeMaterial=ownMaterial(new THREE.MeshBasicMaterial({color:'#d98d20',transparent:true,opacity:.94,depthWrite:false}));
    const markerMaterial=ownMaterial(new THREE.MeshBasicMaterial({color:'#fff3a0',depthWrite:false}));
    for(const name of stage.pipes){
      const path=pipes.find(p=>p.name===name);if(!path)continue;
      const overlay=mesh(journeyLayer,ownGeometry(new THREE.TubeGeometry(path.curve,Math.max(12,path.curve.curves.length*16),.081,10,false)),routeMaterial,[0,0,0]);
      overlay.castShadow=false;overlay.receiveShadow=false;overlay.renderOrder=3;
      const count=Math.max(1,Math.ceil(path.curve.getLength()/1.3));
      const arrows=new THREE.InstancedMesh(ownGeometry(new THREE.ConeGeometry(.13,.28,10)),markerMaterial,count);
      arrows.visible=false;arrows.renderOrder=4;journeyLayer.add(arrows);journeyMarkers.push({path,arrows,count});
    }
    return true;
  }
  function apply(next){
    snapshot=next;
    for(const key of ['raw','treated']){const part=tanks[key],percent=next?.tanks[key].percent;part.water.visible=typeof percent==='number'&&percent>0;
      if(typeof percent==='number'){if(part.geometry==='horizontal-cylinder')horizontalWater(part,percent);else{const h=part.usableHeight*percent/100;part.water.scale.y=Math.max(.0001,h);part.water.position.y=part.base+h/2;}}
      setLight(part.lamp,next?'#6d9683':'#bdc9bf');}
    for(const pump of pumps)setLight(pump.lamp,next?.pumps[pump.id]==='running'?'#6ba384':next?.pumps[pump.id]==='stopped'?'#bac3b9':'#d4d4c8');
    for(const lamp of doseLamps)setLight(lamp,'#bdc9bf'); // design-only, not four independent feedbacks
    setLight(complianceLamp,next?.complianceValve==='product'?'#69a587':next?.complianceValve==='closed'?'#b39162':'#bdc9bf');
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
    for(const marker of journeyMarkers){
      const rate=marker.path.key?snapshot?.flows[marker.path.key]:null;
      marker.arrows.visible=!!motion&&typeof rate==='number'&&rate>0;
      if(marker.arrows.visible){for(let i=0;i<marker.count;i++){
        const t=(i/marker.count+time*.2/marker.path.curve.getLength())%1;
        dummy.position.copy(marker.path.curve.getPointAt(t));dummy.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),marker.path.curve.getTangentAt(t));dummy.updateMatrix();marker.arrows.setMatrixAt(i,dummy.matrix);
      }marker.arrows.instanceMatrix.needsUpdate=true;}
    }
    if(motion)for(const pump of pumps)if(snapshot?.pumps[pump.id]==='running')pump.rotor.rotation.x+=dt*7;
  }
  function select(id){selected=equipment.has(id)?id:null;selection.visible=!!selected;if(selected)selection.box.setFromObject(equipment.get(selected));}
  function dispose(){const geometries=new Set(),materials=new Set();root.traverse(o=>{if(o.geometry)geometries.add(o.geometry);if(o.material)materials.add(o.material);});geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());}
  apply(null);
  return {root,equipment,labels,pipes,tanks,pumps,apply,update,select,setJourney,dispose,get snapshot(){return snapshot;},
    get journeyStage(){return activeJourney;},get highlightedEquipment(){return [...(journeyStage(activeJourney)?.equipment??[])];},
    get highlightedPipes(){return [...(journeyStage(activeJourney)?.pipes??[])];},
    get journeyMotion(){return journeyMarkers.map(m=>({name:m.path.name,key:m.path.key,visible:m.arrows.visible}));}};
}
