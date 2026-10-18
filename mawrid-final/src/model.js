import * as THREE from 'three';
import { box,cyl,sphere,torus,rod,textPlate,canvasTexture,pipeGeometry,instanced,mergeStatic,v3 } from './geometry.js';
import { componentData } from './components.js';

// Coordinates and physical lengths are derived only from the selected unitSpec.
// Literal numbers below are ratios, indices, angles, counts and animation values.
export function createPlant(spec, M) {
 const root=new THREE.Group();root.name='MAWRID '+spec.key;
 const s=spec,c=s.common,d=s.detail,L=s.layout; const base=L.equipmentBaseY;
 const groups=new Map(),anchors=new Map(),ports=new Map(),pipeRuns=[],cutMaterials=[],inside=[],fans=[],glows=[],bolts=[],clamps=[],supports=[];
 const parts=new Map(), state={cutaway:false,flow:false,exploded:false,mode:'normal',step:false,service:false};
 const xBalance=-s.skid.length/2-L.tankSkidGap-s.balance.diameter/2;
 const xChamber=xBalance-s.balance.diameter/2-L.chamberTankGap-c.chamber.length/2;
 const xTreated=s.skid.length/2+L.treatedSkidGap+s.treated.length/2;
 const zTrain=s.skid.width*L.frpZFactor, zFront=s.skid.width*L.pumpZFactor;
 const px={sand:s.skid.length*L.sandXFactor,carbon:s.skid.length*L.carbonXFactor,pp:s.skid.length*L.ppXFactor,uv:s.skid.length*L.uvXFactor,at:s.skid.length*L.analyzerXFactor,valve:s.skid.length*L.valveXFactor,feed:s.skid.length*L.feedPumpXFactor,wash:s.skid.length*L.backwashPumpXFactor};
 const pumpY=base+d.pump.footHeight+d.pump.isolatorHeight+c.pump.motorDiameter/2;
 const uvY=L.uvCenterY,ppY=L.ppBottomY,atY=L.analyzerCenterY,valveY=L.valveCenterY;
 const panelX=s.skid.length/2-c.frame.post/2,panelZ=-s.skid.width/2;
 function group(id,pos=[0,0,0]){const g=new THREE.Group();g.name=componentData.find(r=>r.id===id)?.code||String(id);g.position.set(...pos);g.userData.id=id;g.userData.home=g.position.clone();g.userData.explode=new THREE.Vector3((pos[0]>=0?1:-1)*d.explode.xOffset*(id%3+1),d.explode.yOffset*(id%2+1),(id%2?1:-1)*d.explode.zOffset);if(id===14||id===15)g.userData.explode.set(0,0,0);root.add(g);groups.set(id,g);return g;}
 function anchor(id,p){anchors.set(id,v3(p));}
 function port(name,id,p){ports.set(name,{id,local:v3(p)});return world(name);}
 function world(name){const p=ports.get(name);return p.local.clone().add(groups.get(p.id).userData.home);}
 function tagged(id,g,pos){const item=componentData.find(r=>r.id===id);textPlate(g,`${String(id).padStart(2,'0')} · ${item.code}`,[d.labels.plateWidth,d.labels.plateHeight,d.labels.plateThickness],pos,M.steel);}
 function shell(m,z=0){m.material=m.material.clone();m.material.clippingPlanes=[];cutMaterials.push({mat:m.material,z});return m;}
 function internal(o,visibleThroughShell=false){inside.push(o);o.userData.visibleThroughShell=visibleThroughShell;o.visible=visibleThroughShell;return o;}
 function support(g,x,z,top,width=c.frame.post){const h=top-base; if(h>0){const m=box(g,[width,h,width],[x,base+h/2,z],M.steel);m.userData.merge=true;}box(g,[d.fittings.supportBase,d.fittings.bracketThickness,d.fittings.supportBase],[x,base,z],M.steel);}
 function union(g,p,axis='x',mat=M.pipe,outerDiameter=s.pipe.outerDiameter){return cyl(g,(outerDiameter+d.fittings.unionExtraDiameter)/2,d.fittings.unionLength,p,mat,axis,8);}
 function valve(g,p,axis='x',electric=false){
  const dia=d.valve.bodyDiameter; cyl(g,dia/2,d.valve.bodyLength,p,M.brass,axis,16);union(g,v3(p).add(new THREE.Vector3(axis==='x'?d.valve.bodyLength/2:0,axis==='y'?d.valve.bodyLength/2:0,axis==='z'?d.valve.bodyLength/2:0)),axis);
  const y=p[1]+dia/2;rod(g,[p[0],y,p[2]],[p[0],y+d.valve.handleHeight*2,p[2]],d.valve.handleWidth/3,M.steel);
  const h=box(g,[d.valve.handleLength,d.valve.handleHeight,d.valve.handleWidth],[p[0],y+d.valve.handleHeight*2,p[2]],M.red,d.valve.handleHeight/3);return h;
 }
 function pressure(g,p,label,direction=1){
  const stem=d.instrument.gaugeStem,r=d.instrument.gaugeDiameter/2;
  rod(g,p,[p[0],p[1]+stem,p[2]],s.pipe.outerDiameter/5,M.steel);
  cyl(g,r,d.instrument.gaugeDepth,[p[0],p[1]+stem+r,p[2]],M.steel,'z');
  const tex=canvasTexture((ctx,w,h)=>{ctx.fillStyle='#f9faf5';ctx.fillRect(0,0,w,h);ctx.strokeStyle='#243a35';ctx.lineWidth=5;ctx.beginPath();ctx.arc(w/2,h/2,w*.42,0,Math.PI*2);ctx.stroke();for(let i=0;i<25;i++){const a=Math.PI*.75+i/24*Math.PI*1.5;ctx.beginPath();ctx.moveTo(w/2+Math.cos(a)*w*.32,h/2+Math.sin(a)*h*.32);ctx.lineTo(w/2+Math.cos(a)*w*.39,h/2+Math.sin(a)*h*.39);ctx.stroke();}ctx.strokeStyle='#a04132';ctx.lineWidth=10;ctx.beginPath();ctx.moveTo(w/2,h/2);ctx.lineTo(w*.66,h*.27);ctx.stroke();ctx.fillStyle='#183c33';ctx.textAlign='center';ctx.font='55px Arial';ctx.fillText(label,w/2,h*.77);ctx.font='35px Arial';ctx.fillText('bar',w/2,h*.88);},512,512);
  const face=new THREE.MeshPhysicalMaterial({map:tex,roughness:.25});cyl(g,r*.9,d.labels.surfaceGap,[p[0],p[1]+stem+r,p[2]+d.instrument.gaugeDepth/2],face,'z');
  const sensorP=[p[0]+direction*r*2,p[1]+d.instrument.pressureLength/2,p[2]];cyl(g,d.instrument.pressureDiameter/2,d.instrument.pressureLength,sensorP,M.steel);return [sensorP[0],sensorP[1]+d.instrument.pressureLength/2,sensorP[2]];
 }
 function flowMeter(g,p,label){cyl(g,d.instrument.flowBodyDiameter/2,d.instrument.flowLength,p,M.steel,'x');box(g,[d.instrument.displayWidth,d.instrument.displayHeight,d.instrument.gaugeDepth],[p[0],p[1]+d.instrument.flowBodyDiameter/2,p[2]],M.frame);textPlate(g,label,[d.instrument.displayWidth,d.instrument.displayHeight,d.labels.plateThickness],[p[0],p[1]+d.instrument.flowBodyDiameter/2,p[2]+d.instrument.gaugeDepth/2],M.steel,{bg:'#d7e9de'});}
 function sample(g,p){valve(g,p,'z');const a=[p[0],p[1],p[2]+d.fittings.sampleSpout],b=[p[0],p[1]-d.fittings.sampleSpout/2,a[2]];rod(g,p,a,s.pipe.outerDiameter/4,M.brass);rod(g,a,b,s.pipe.outerDiameter/4,M.brass);cyl(g,s.pipe.outerDiameter/3,d.labels.plateThickness,b,M.rubber);}
 function cable(g,points){const {geometry}=pipeGeometry(points,d.cable.diameter/2,d.cable.conduitDiameter);const m=new THREE.Mesh(geometry,M.black);g.add(m);return m;}
 function motorPump(id,x,z,length,diameter){
  const g=group(id,[x,0,z]), r=diameter/2, y=pumpY;
  box(g,[length+d.pump.footHeight,d.pump.footHeight,d.pump.footWidth],[0,base+d.pump.isolatorHeight+d.pump.footHeight/2,0],M.steel);
  for(const xx of [-1,1])for(const zz of [-1,1]){cyl(g,d.pump.isolatorDiameter/2,d.pump.isolatorHeight,[xx*length*.35,base+d.pump.isolatorHeight/2,zz*d.pump.footWidth*.34],M.rubber);bolts.push({position:[x+xx*length*.35,base+d.pump.isolatorHeight+d.pump.footHeight,z+zz*d.pump.footWidth*.34]});}
  cyl(g,r,length*.48,[length*.13,y,0],M.frame,'x');cyl(g,r*.83,length*.36,[-length*.29,y,0],M.steel,'x');
  for(let i=0;i<5;i++)torus(g,r*.83,d.shell.stainlessWall,[length*(-.45+i*.065),y,0],M.steel,'x');
  for(let i=0;i<14;i++){const a=i/14*Math.PI*2;const fin=box(g,[length*.42,d.pump.finWidth,d.pump.finDepth],[length*.13,y+Math.cos(a)*(r+d.pump.finDepth/3),Math.sin(a)*(r+d.pump.finDepth/3)],M.frame);fin.rotation.x=a;}
  box(g,[d.pump.terminalWidth,d.pump.terminalHeight,d.pump.terminalWidth],[length*.13,y+r+d.pump.terminalHeight/2,0],M.frame);
  const fan=new THREE.Group();fan.position.set(length*.42,y,0);g.add(fan);for(let i=0;i<6;i++){const blade=box(fan,[d.pump.fanDepth/3,r*.7,r*.19],[0,r*.33,0],M.black);const pivot=new THREE.Group();fan.remove(blade);pivot.rotation.x=i*Math.PI/3;pivot.add(blade);fan.add(pivot);}fans.push(fan);
  torus(g,r,d.shell.stainlessWall,[length*.48,y,0],M.black,'x');for(let i=1;i<4;i++)torus(g,r*i/4,d.shell.stainlessWall/2,[length*.5,y,0],M.steel,'x');
  rod(g,[-length*.25,base+d.pump.footHeight,0],[-length*.25,y-r*.4,0],d.pump.footHeight,M.steel);rod(g,[length*.23,base+d.pump.footHeight,0],[length*.23,y-r*.4,0],d.pump.footHeight,M.frame);
  const suction=[-length/2,y,0],discharge=[-length*.29,y+r*.83+d.fittings.unionLength,0];
  rod(g,[-length*.47,y,0],suction,s.pipe.outerDiameter/2,M.steel);union(g,suction,'x',M.steel);
  rod(g,[-length*.29,y+r*.65,0],discharge,s.pipe.outerDiameter/2,M.steel);union(g,discharge,'y',M.steel);
  tagged(id,g,[0,y+r*.35,r+d.labels.surfaceGap]);anchor(id,[x,y,z]);port(`${id}.in`,id,suction);port(`${id}.out`,id,discharge);return g;
 }
 // 14 — Recessed skid: edge channels and low inset tray, no deck undercut.
 const frame=group(14);const railY=d.frame.footHeight+c.frame.baseChannel/2;
 for(const z of [-1,1]){box(frame,[s.skid.length,c.frame.baseChannel,c.frame.post],[0,railY,z*(s.skid.width-c.frame.post)/2],M.frame).userData.merge=true;}
 for(const x of [-1,1])box(frame,[c.frame.post,c.frame.baseChannel,s.skid.width],[x*(s.skid.length-c.frame.post)/2,railY,0],M.frame).userData.merge=true;
 box(frame,[s.skid.length-c.frame.post*2,d.frame.trayThickness,s.skid.width-c.frame.post*2],[0,base-d.frame.trayThickness/2,0],M.steel).userData.merge=true;
 for(const z of [-1,1])box(frame,[s.skid.length-c.frame.post*2,d.frame.trayLip,d.frame.trayThickness],[0,base-d.frame.trayLip/2,z*(s.skid.width/2-c.frame.post)],M.steel).userData.merge=true;
 for(const x of [-1,1])for(const z of [-1,1]){
  const xx=x*(s.skid.length/2-c.frame.post),zz=z*(s.skid.width/2-c.frame.post);
  cyl(frame,d.frame.footDiameter/2,d.frame.footHeight,[xx,d.frame.footHeight/2,zz],M.steel);cyl(frame,d.fasteners.boltDiameter/2,d.frame.footStem,[xx,d.frame.footHeight+d.frame.footStem/2,zz],M.steel);
  // Rear columns only: unobstructed front servicing and valve-head lifting envelope.
  if(z<0){box(frame,[c.frame.post,c.frame.height,c.frame.post],[xx,c.frame.height/2,zz],M.frame).userData.merge=true;}
  torus(frame,d.frame.liftingEyeDiameter/2,d.frame.liftingEyeTube/2,[xx,base+d.frame.liftingEyeDiameter/2,zz],M.steel,'z');
  bolts.push({position:[xx,base,zz]});
 }
 box(frame,[s.skid.length,c.frame.post,c.frame.post],[0,c.frame.height-c.frame.post/2,-s.skid.width/2+c.frame.post],M.frame).userData.merge=true;
 for(const x of [-1,1]){const p=[x*d.frame.forkSpacing/2,railY,s.skid.width/2+d.labels.surfaceGap];box(frame,[d.frame.forkOpeningWidth,d.frame.forkOpeningHeight,d.labels.plateThickness],p,M.black);}
 const trayZ=-s.skid.width/2-d.cable.trayWidth/2; const trayY=L.cableTrayY;
 box(frame,[s.skid.length,d.cable.trayThickness,d.cable.trayWidth],[0,trayY,trayZ],M.steel).userData.merge=true;
 for(const z of [-1,1])box(frame,[s.skid.length,d.cable.trayHeight,d.cable.trayThickness],[0,trayY+d.cable.trayHeight/2,trayZ+z*d.cable.trayWidth/2],M.steel).userData.merge=true;
 for(let x=-s.skid.length/2;x<s.skid.length/2;x+=d.cable.trayRungInterval)box(frame,[d.cable.trayThickness,d.cable.trayThickness,d.cable.trayWidth],[x,trayY, trayZ],M.steel).userData.merge=true;
 textPlate(frame,['مورد | MAWRID',`${s.key} · ${s.capacity} م³/يوم · تصور`],[d.labels.dataWidth,d.labels.dataHeight,d.labels.plateThickness],[0,base+d.labels.dataHeight/2,s.skid.width/2],M.steel);anchor(14,[0,base,s.skid.width/2]);
 // 1 — Chamber, removable basket and baffles. The front earth wall is sectioned.
 const chamber=group(1,[xChamber,0,0]),ch=c.chamber,cd=d.chamber,cw=d.shell.chamberWall;
 box(chamber,[ch.length,cw,ch.width],[0,-ch.depth+cw/2,0],M.concrete);
 box(chamber,[ch.length,ch.depth,cw],[0,-ch.depth/2,-ch.width/2],M.concrete);
 for(const sign of [-1,1])box(chamber,[cw,ch.depth,ch.width],[sign*ch.length/2,-ch.depth/2,0],M.concrete);
 for(const sign of [-1,1])box(chamber,[cd.baffleThickness,cd.baffleHeight,ch.width-cw],[sign*ch.length/6,-ch.depth+cd.baffleUnderflow+cd.baffleHeight/2,0],M.concrete);
 box(chamber,[ch.length-cw,cd.waterHeight+ch.depth-cw,ch.width-cw],[0,(-ch.depth+cw+cd.waterHeight)/2,0],M.rawWater);
 const basketX=-ch.length*.32,basketY=-cd.basketHeight/2;
 for(let yy=-cd.basketHeight;yy<=0;yy+=cd.basketGrid){for(const zz of [-1,1])rod(chamber,[basketX-cd.basketWidth/2,yy,zz*cd.basketDepth/2],[basketX+cd.basketWidth/2,yy,zz*cd.basketDepth/2],cd.basketWire/2,M.steel);}
 for(let xx=-cd.basketWidth/2;xx<=cd.basketWidth/2;xx+=cd.basketGrid){for(const zz of [-1,1])rod(chamber,[basketX+xx,-cd.basketHeight,zz*cd.basketDepth/2],[basketX+xx,0,zz*cd.basketDepth/2],cd.basketWire/2,M.steel);rod(chamber,[basketX+xx,-cd.basketHeight,-cd.basketDepth/2],[basketX+xx,-cd.basketHeight,cd.basketDepth/2],cd.basketWire/2,M.steel);}
 torus(chamber,cd.basketWidth/3,cd.basketWire,[basketX,0,0],M.steel,'z',Math.PI);
 for(const sign of [-1,1])rod(chamber,[basketX,0,sign*cd.basketDepth/2],[basketX,0,sign*(ch.width/2-cw/2)],cd.basketWire,M.steel);
 const cover=cyl(chamber,ch.coverDiameter/2,cd.coverThickness,[ch.length*.19,cd.coverThickness/2,-ch.width*.6-ch.coverDiameter/2],M.black);cover.userData.home=cover.position.clone();
 for(let i=-3;i<=3;i++)box(chamber,[ch.coverDiameter*.72,cd.coverThickness/8,cd.basketWire],[cover.position.x,cd.coverThickness,cover.position.z+i*ch.coverDiameter/10],M.steel);
 tagged(1,chamber,[0,-cd.baffleHeight/2,ch.width/2]);anchor(1,[xChamber,-ch.depth*.4,ch.width/2]);
 port('ch.in',1,[-ch.length/2,cd.inletHeight,0]);port('ch.over',1,[ch.length/2,cd.overflowHeight,-ch.width*.25]);
 // 2 — Submersible lift pump with cabled level float.
 const sub=group(2,[xChamber+ch.length*.32,-ch.depth+cw,0]);cyl(sub,c.submersible.diameter/2,c.submersible.height,[0,c.submersible.height/2,0],M.steel);
 cyl(sub,c.submersible.diameter*.53,c.submersible.height*.16,[0,c.submersible.height*.08,0],M.black);torus(sub,c.submersible.diameter*.28,cd.basketWire,[0,c.submersible.height,0],M.steel,'z',Math.PI);
 sphere(sub,cd.floatDiameter/2,[c.submersible.diameter, c.submersible.height*.6,c.submersible.diameter*.5],M.red);
 cable(sub,[[0,c.submersible.height,0],[c.submersible.diameter,c.submersible.height*.9,c.submersible.diameter*.5],[c.submersible.diameter,c.submersible.height*.6,c.submersible.diameter*.5]]);
 tagged(2,sub,[0,c.submersible.height/2,c.submersible.diameter/2]);port('lift.out',2,[0,c.submersible.height,0]);anchor(2,sub.position.clone().add(new THREE.Vector3(0,c.submersible.height/2,0)));
 // 3 — PE equalization tank, water shadow, lid, vent, front sample and floats.
 const balance=group(3,[xBalance,0,0]),br=s.balance.diameter/2,bh=s.balance.height;
 shell(cyl(balance,br,bh*.88,[0,bh*.44,0],M.peWhite));shell(sphere(balance,br,[0,bh*.88,0],M.peWhite,[1,bh*.12/br,1]));
 cyl(balance,br*.94,bh*.61,[0,bh*.305,0],M.rawWater);
 for(let i=1;i<6;i++)shell(torus(balance,br,d.balance.ribWidth/3,[0,bh*i/6,0],M.peWhite));
 cyl(balance,d.balance.capDiameter/2,d.balance.capHeight,[0,bh+d.balance.capHeight/2,0],M.peWhite);
 for(let i=0;i<24;i++){const a=i/24*Math.PI*2;box(balance,[d.balance.capTeethHeight,d.balance.capHeight,d.balance.capTeethHeight],[Math.cos(a)*d.balance.capDiameter/2,bh+d.balance.capHeight/2,Math.sin(a)*d.balance.capDiameter/2],M.peWhite);}
 rod(balance,[br*.55,bh*.96,0],[br*.55,bh+d.balance.ventHeight,0],d.balance.ventDiameter/2,M.pipe);cyl(balance,d.balance.ventDiameter*.8,d.labels.plateThickness,[br*.55,bh+d.balance.ventHeight,0],M.black);
 for(const ratio of [.2,.8]){const f=internal(sphere(balance,cd.floatDiameter/2,[br*.55,bh*ratio,0],M.red));internal(cable(balance,[[br*.55,bh,0],[br*.55,bh*ratio,0]]));}
 const rawSensors=[];for(let i=0;i<4;i++){const sp=[br+d.instrument.probeDiameter*(2+i*3),d.balance.outletHeight+d.instrument.probeHeight/2,0];cyl(balance,d.instrument.probeDiameter/2,d.instrument.probeHeight,sp,M.steel);rawSensors.push([sp[0],sp[1]+d.instrument.probeHeight/2,sp[2]]);}
 sample(balance,[br*.55,d.balance.sampleHeight,Math.sqrt(br*br-br*br*.55*.55)]);
 const drainTap=[0,d.balance.outletHeight,br];valve(balance,drainTap,'z');
 tagged(3,balance,[0,bh*.55,br+d.labels.surfaceGap]);anchor(3,[xBalance,bh*.7,br]);
 function tankNozzle(name,axis,y){const direction=new THREE.Vector3(axis[0],0,axis[1]).normalize();const start=direction.clone().multiplyScalar(br-d.shell.peWall/2);start.y=y;const end=direction.clone().multiplyScalar(br+d.head.nozzleLength);end.y=y;rod(balance,start,end,s.pipe.outerDiameter/2,M.pipe);const fitting=union(balance,end,'y');fitting.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),direction);port(name,3,end.toArray());}
 tankNozzle('balance.in',[-.5,-Math.sqrt(1-.5*.5)],bh*.82);
 tankNozzle('balance.return',[.55,-Math.sqrt(1-.55*.55)],bh*.82);
 tankNozzle('balance.out',[1,0],d.balance.outletHeight);
 tankNozzle('balance.over',[.65,Math.sqrt(1-.65*.65)],bh*.88-d.balance.overflowOffset/2);
 port('balance.drain',3,drainTap);
 // 4 and 11 — Horizontal multistage pumps with isolated bases and cooling fans.
 const feed=motorPump(4,px.feed,zFront,c.pump.length,c.pump.motorDiameter);
 const wash=motorPump(11,px.wash,zFront,c.pump.length,c.pump.motorDiameter);
 // 5 / 6 — FRP pressure vessels with commercial outer envelope.
 function vessel(id,x,dim,mat,carbon=false){
  const g=group(id,[x,base,zTrain]),r=dim.diameter/2,h=dim.height,fh=d.frp;
  cyl(g,r*1.04,fh.baseHeight,[0,fh.baseHeight/2,0],M.black);
  const shoulder=Math.min(fh.shoulderHeight,h*.12), bodyH=h-shoulder*2;
  shell(cyl(g,r,bodyH,[0,shoulder+bodyH/2,0],mat),zTrain);
  shell(sphere(g,r,[0,shoulder,0],mat,[1,shoulder/r,1]),zTrain);shell(sphere(g,r,[0,h-shoulder,0],mat,[1,shoulder/r,1]),zTrain);
  cyl(g,fh.neckDiameter/2,fh.neckHeight,[0,h-fh.neckHeight/2,0],mat);
  const hd=s.valveHead.height; cyl(g,d.head.bodyDiameter/2,hd*.57,[0,h+hd*.285,0],M.black);
  const handle=box(g,[d.head.handleLength,d.head.handleThickness,d.head.handleThickness*2],[0,h+hd-d.head.handleThickness/2,0],M.black);rod(g,[0,h+hd*.57,0],[0,h+hd,0],d.head.handleThickness/2,M.steel);
  const hp=h+hd*.42,portX=d.head.bodyDiameter/2+d.head.nozzleLength;
  for(const sign of [-1,1]){rod(g,[0,hp,0],[sign*portX,hp,0],s.pipe.outerDiameter/2,M.black);union(g,[sign*portX,hp,0]);}
  rod(g,[0,hp,0],[0,hp,-d.head.nozzleLength-d.head.bodyDiameter/2],s.pipe.outerDiameter/2,M.black);
  port(`${id}.in`,id,[-portX,hp,0]);port(`${id}.out`,id,[portX,hp,0]);port(`${id}.bw`,id,[0,hp,-d.head.nozzleLength-d.head.bodyDiameter/2]);
  const mediaH=h*.65,mediaY=fh.mediaBottomY;
  const layers=carbon?[{ratio:1,color:'#2f3730'}]:[{ratio:.16,color:'#8b8979'},{ratio:.18,color:'#b2a385'},{ratio:.38,color:'#d4c19b'},{ratio:.28,color:'#394039'}];
  let y=mediaY;for(const layer of layers){const hh=mediaH*layer.ratio;const medium=new THREE.MeshPhysicalMaterial({color:layer.color,roughness:.98,normalMap:M.soil.normalMap,normalScale:new THREE.Vector2(.4,.4)});internal(cyl(g,r-fh.mediaClearance,hh,[0,y+hh/2,0],medium));y+=hh;}
  internal(cyl(g,fh.standpipeDiameter/2,h-fh.mediaBottomY,[0,(h+fh.mediaBottomY)/2,0],M.pipe));
  for(let i=0;i<8;i++){const a=i/8*Math.PI*2;internal(rod(g,[0,fh.mediaBottomY,0],[Math.cos(a)*r*.8,fh.mediaBottomY,Math.sin(a)*r*.8],fh.standpipeDiameter/4,M.pipe));}
  tagged(id,g,[0,h*.54,r+d.labels.surfaceGap]);anchor(id,[x,base+h*.7,zTrain+r]);return g;
 }
 const sand=vessel(5,px.sand,s.sand,M.frpSand),carbon=vessel(6,px.carbon,s.carbon,M.frpCarbon,true);
 // Section-face flow markers show bed flow down in filtration and up in backwash.
 // These are schematic water markers inside the commercial vessel envelope.
 const sandFlow=new THREE.Group();sand.add(sandFlow);
 const sandFlowZ=s.sand.diameter/2-d.frp.mediaClearance/4;
 const sandFlowBottom=d.frp.mediaBottomY,sandFlowHeight=s.sand.height*.65;
 const sandArrowMaterial=new THREE.MeshPhysicalMaterial({color:'#578bb5',roughness:.3});
 const sandArrows=[];for(const ratio of [.25,.5,.75]){
  const arrow=new THREE.Mesh(new THREE.ConeGeometry(d.particles.radius*.9,d.particles.radius*3,12),sandArrowMaterial);
  arrow.position.set(0,sandFlowBottom+sandFlowHeight*ratio,sandFlowZ);sandFlow.add(arrow);sandArrows.push(arrow);
 }
 const sandFlowCount=16;
 const sandParticles=new THREE.InstancedMesh(new THREE.SphereGeometry(d.particles.radius*.5,8,6),sandArrowMaterial,sandFlowCount);sandFlow.add(sandParticles);

 // 7 — 20-inch pleated cartridge and service bracket attached to rear frame.
 const pp=group(7,[px.pp,ppY,zTrain]),pr=c.pp.diameter/2,ph=c.pp.height;
 shell(cyl(pp,pr,ph-d.pp.capHeight,[0,(ph-d.pp.capHeight)/2,0],M.pp),zTrain);shell(sphere(pp,pr,[0,pr*.4,0],M.pp,[1,.4,1]),zTrain);
 cyl(pp,d.pp.capDiameter/2,d.pp.capHeight,[0,ph-d.pp.capHeight/2,0],M.black);
 const cartridge=internal(cyl(pp,d.pp.cartridgeDiameter/2,d.pp.cartridgeHeight,[0,ph*.46,0],M.white),true);
 for(let i=0;i<40;i++){const a=i/40*Math.PI*2;internal(rod(pp,[Math.cos(a)*d.pp.cartridgeDiameter/2,ph*.46-d.pp.cartridgeHeight/2,Math.sin(a)*d.pp.cartridgeDiameter/2],[Math.cos(a)*d.pp.cartridgeDiameter/2,ph*.46+d.pp.cartridgeHeight/2,Math.sin(a)*d.pp.cartridgeDiameter/2],d.pp.pleatDepth/2,M.white),true);}
 box(pp,[d.pp.bracketWidth,d.pp.bracketThickness,s.skid.width/2+zTrain],[0,ph,(-s.skid.width/2-zTrain)/2],M.steel);
 support(frame,px.pp,-s.skid.width/2+c.frame.post,ppY+ph);
 port('pp.in',7,[-d.pp.capDiameter/2,ph-d.pp.capHeight/2,0]);port('pp.out',7,[d.pp.capDiameter/2,ph-d.pp.capHeight/2,0]);
 tagged(7,pp,[0,ph*.6,pr+d.labels.surfaceGap]);anchor(7,[px.pp,ppY+ph*.65,zTrain+pr]);
 // 8 — Stainless UV reactor with removable lamp end, quartz sleeve, ballast and sensor.
 const uv=group(8,[px.uv,uvY,zFront]),ur=s.uv.diameter/2,ul=s.uv.length;
 shell(cyl(uv,ur,ul,[0,0,0],M.steel,'x'),zFront);
 for(const sign of [-1,1]){shell(cyl(uv,ur*1.12,d.uv.endCapDepth,[sign*(ul/2-d.uv.endCapDepth/2),0,0],M.steel,'x'),zFront);torus(uv,ur*1.12,d.shell.stainlessWall,[sign*ul/2,0,0],M.steel,'x');}
 const quartz=internal(cyl(uv,d.uv.quartzDiameter/2,ul-d.uv.lampEndClearance,[0,0,0],M.quartz,'x'));
 const lamp=internal(cyl(uv,d.uv.lampDiameter/2,ul-d.uv.lampEndClearance*2,[0,0,0],M.uvGlow,'x'));lamp.layers.enable(1);glows.push(lamp);
 const nozzleX=ul/2-d.uv.nozzleInset;for(const sign of [-1,1]){rod(uv,[sign*nozzleX,0,0],[sign*nozzleX,ur+d.uv.nozzleLength,0],s.pipe.outerDiameter/2,M.steel);union(uv,[sign*nozzleX,ur+d.uv.nozzleLength,0],'y',M.steel);}
 port('uv.in',8,[-nozzleX,ur+d.uv.nozzleLength,0]);port('uv.out',8,[nozzleX,ur+d.uv.nozzleLength,0]);
 cyl(uv,d.uv.sensorDiameter/2,d.uv.sensorHeight,[0,ur+d.uv.sensorHeight/2,0],M.steel);
 for(const sign of [-1,1]){support(frame,px.uv+sign*ul*.31,zFront,uvY-ur);torus(uv,ur+d.shell.stainlessWall,d.shell.stainlessWall,[sign*ul*.31,0,0],M.steel,'x');}
 const ballastY=-(uvY-base)/2;box(uv,[d.uv.ballastWidth,d.uv.ballastHeight,d.uv.ballastDepth],[0,ballastY,-s.skid.width*.2],M.steel);support(frame,px.uv,zFront-s.skid.width*.2,uvY+ballastY-d.uv.ballastHeight/2);
 const led=sphere(uv,d.uv.sensorDiameter/6,[d.uv.ballastWidth*.35,ballastY,-s.skid.width*.2+d.uv.ballastDepth/2],M.greenGlow);led.layers.enable(1);glows.push(led);
 cable(uv,[[0,ur+d.uv.sensorHeight,0],[0,ur+d.uv.sensorHeight,-s.skid.width*.2],[0,ballastY,-s.skid.width*.2]]);
 tagged(8,uv,[0,-ur*.25,ur+d.labels.surfaceGap]);anchor(8,[px.uv,uvY,zFront+ur]);
 // 9 — Transparent final verification flow-cell with four immersion probes.
 const at=group(9,[px.at,atY,0]),ad=d.analyzer;
 shell(box(at,[ad.width,ad.height,ad.depth],[0,0,0],M.acrylic,d.shell.acrylicWall));
 internal(cyl(at,s.pipe.outerDiameter/2,ad.width,[0,0,0],M.water,'x'),true);
 for(let i=0;i<4;i++){const x=(i-1.5)*ad.probeSpacing;cyl(at,ad.probeDiameter/2,ad.probeLength,[x,ad.height/2+ad.probeLength*.15,0],M.steel);cyl(at,ad.probeDiameter*.75,ad.probeDiameter,[x,ad.height/2+ad.probeLength*.65,0],M.black);cable(at,[[x,ad.height/2+ad.probeLength*.7,0],[x,ad.height/2+ad.probeLength,s.skid.width*-.15],[x,trayY-atY,trayZ]]);}
 box(at,[ad.supportWidth,ad.supportThickness,ad.depth],[0,-ad.height/2,0],M.steel);support(frame,px.at,0,atY-ad.height/2);
 port('at.in',9,[-ad.width/2,0,0]);port('at.out',9,[ad.width/2,0,0]);tagged(9,at,[0,0,ad.depth/2+d.labels.surfaceGap]);anchor(9,[px.at,atY,ad.depth/2]);
 // 10 — Fail-closed spring-return irrigation isolation and diversion valve.
 const decision=group(10,[px.valve,valveY,zFront]);
 const mainX=d.valve.bodyLength*1.6;valve(decision,[mainX,0,0]);
 const actuator=box(decision,[d.valve.actuatorWidth,d.valve.actuatorHeight,d.valve.actuatorDepth],[mainX,d.valve.bodyDiameter/2+d.valve.actuatorHeight/2,0],M.frame,d.labels.surfaceGap);
 cyl(decision,d.valve.springHousingDiameter/2,d.valve.actuatorWidth,[mainX,d.valve.bodyDiameter/2+d.valve.actuatorHeight/2,-d.valve.actuatorDepth*.65],M.black,'x');
 const indicator=cyl(decision,d.valve.indicatorDiameter/2,d.labels.plateThickness,[mainX,d.valve.bodyDiameter/2+d.valve.actuatorHeight,d.valve.actuatorDepth/2],M.greenGlow,'z');parts.indicator=indicator;
 const handle=box(decision,[d.valve.handleLength,d.valve.handleHeight,d.valve.handleWidth],[mainX,d.valve.bodyDiameter/2+d.valve.actuatorHeight+d.valve.handleHeight,0],M.greenGlow);parts.returnHandle=handle;
 textPlate(decision,'V-601 · NC',[d.labels.plateWidth,d.labels.plateHeight,d.labels.plateThickness],[mainX,d.valve.bodyDiameter/2+d.valve.actuatorHeight/2,d.valve.actuatorDepth/2+d.labels.surfaceGap],M.steel);
 const divZ=-d.valve.bodyLength*2;parts.diverterHandle=valve(decision,[0,0,divZ],'z');cyl(decision,d.valve.bodyDiameter/2,d.valve.bodyLength,[0,0,divZ],M.brass,'z');
 textPlate(decision,'V-602',[d.labels.plateWidth,d.labels.plateHeight,d.labels.plateThickness],[0,d.valve.bodyDiameter,divZ+d.valve.bodyDiameter/2],M.steel);
 support(frame,px.valve+mainX,zFront,valveY-d.valve.bodyDiameter/2);
 port('decision.in',10,[0,0,0]);port('decision.irrigate',10,[mainX+d.valve.bodyLength/2,0,0]);port('decision.return',10,[0,0,divZ-d.valve.bodyLength/2]);port('decision.drain',10,[d.valve.bodyLength/2,0,divZ]);
 rod(decision,[0,0,0],[mainX,0,0],s.pipe.outerDiameter/2,M.purple);rod(decision,[0,0,0],[0,0,divZ],s.pipe.outerDiameter/2,M.pipe);
 anchor(10,[px.valve+mainX,valveY+d.valve.actuatorHeight,zFront]);tagged(10,decision,[mainX,-d.valve.bodyDiameter/2,d.valve.actuatorDepth/2]);
 // 12 — Reclaimed-water tank, warning symbol, irrigation pump.
 const treated=group(12,[xTreated,0,0]),tt=s.treated;
 shell(box(treated,[tt.length,tt.height,tt.width],[0,tt.height/2,0],M.peTreated,d.treated.cornerRadius));
 internal(box(treated,[tt.length-d.shell.peWall*2,tt.height*.67,tt.width-d.shell.peWall*2],[0,tt.height*.335+d.shell.peWall,0],M.water,d.treated.cornerRadius));
 for(let i=1;i<4;i++){for(const sign of [-1,1])shell(box(treated,[tt.length*.95,d.treated.ribDepth,d.treated.ribDepth],[0,tt.height*i/4,sign*tt.width/2],M.peTreated));}
 cyl(treated,d.treated.capDiameter/2,d.treated.capHeight,[0,tt.height+d.treated.capHeight/2,0],M.black);
 const warning=textPlate(treated,['مياه غير صالحة للشرب','NON-POTABLE WATER'],[d.treated.warningWidth,d.treated.warningHeight,d.labels.plateThickness],[0,tt.height*.55,tt.width/2+d.labels.surfaceGap],M.steel,{bg:'#f4e9bc',color:'#3e3522',bold:true});
 const symbol=canvasTexture((ctx,w,h)=>{ctx.fillStyle='#f4e9bc';ctx.fillRect(0,0,w,h);ctx.strokeStyle='#202d2a';ctx.lineWidth=22;ctx.beginPath();ctx.moveTo(w*.3,h*.32);ctx.lineTo(w*.38,h*.72);ctx.lineTo(w*.65,h*.72);ctx.lineTo(w*.72,h*.32);ctx.stroke();ctx.beginPath();ctx.moveTo(w*.34,h*.48);ctx.lineTo(w*.69,h*.48);ctx.stroke();ctx.strokeStyle='#bc3d32';ctx.lineWidth=35;ctx.beginPath();ctx.arc(w/2,h/2,w*.4,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(w*.2,h*.2);ctx.lineTo(w*.8,h*.8);ctx.stroke();},256,256);
 box(treated,[d.treated.warningHeight,d.treated.warningHeight,d.labels.plateThickness],[-d.treated.warningWidth/2-d.treated.warningHeight*.6,tt.height*.55,tt.width/2+d.labels.surfaceGap],new THREE.MeshPhysicalMaterial({map:symbol,roughness:.6}));
 const ipX=tt.length/2+L.irrigationPumpOffset,ipY=c.irrigationPump.diameter/2+d.pump.footHeight;
 box(treated,[c.irrigationPump.length,d.pump.footHeight,c.irrigationPump.diameter],[ipX,d.pump.footHeight/2,0],M.steel);
 cyl(treated,c.irrigationPump.diameter/2,c.irrigationPump.length,[ipX,ipY,0],M.frame,'x');
 port('treated.in',12,[-tt.length/2,tt.height-d.treated.inletOffset,0]);port('treated.out',12,[tt.length/2,d.treated.outletHeight,0]);port('irrigation.in',12,[ipX-c.irrigationPump.length/2,ipY,0]);port('irrigation.out',12,[ipX+c.irrigationPump.length/2,ipY,0]);port('treated.wash',12,[-tt.length/2,d.treated.outletHeight,-tt.width*.25]);
 tagged(12,treated,[0,tt.height*.82,tt.width/2+d.labels.surfaceGap]);anchor(12,[xTreated,tt.height*.7,tt.width/2]);
 // 13 — Panel supported directly by rear right column; front-service operator face.
 const panel=group(13,[panelX,c.panel.centerHeight,panelZ+c.panel.depth/2]),pd=c.panel;
 box(panel,[pd.width,pd.height,pd.depth],[0,0,0],M.white,d.panel.doorGap);
 box(panel,[pd.width-d.panel.doorGap,pd.height-d.panel.doorGap,d.panel.doorThickness],[0,0,pd.depth/2],M.white,d.panel.doorGap/2);
 for(const sign of [-1,1])box(panel,[d.panel.mountWidth,d.panel.mountWidth,d.panel.mountDepth],[0,sign*pd.height*.35,-pd.depth/2-d.panel.mountDepth/2],M.steel);
 const screen=textPlate(panel,['تشغيل طبيعي','عكارة 0.6 NTU','pH 7.2 · UV 100%'],[d.panel.screenWidth,d.panel.screenHeight,d.panel.screenDepth],[-pd.width*.13,pd.height*.14,pd.depth/2+d.panel.screenDepth],M.black,{screen:true,bg:'#102d2c',color:'#d0eadf'});parts.screen=screen;
 const emergency=[pd.width*.22,-pd.height*.16,pd.depth/2+d.panel.emergencyDiameter/2];cyl(panel,d.panel.emergencyDiameter/2,d.panel.emergencyDiameter/2,emergency,M.red,'z');cyl(panel,d.panel.emergencyDiameter*.7,d.labels.plateThickness,[emergency[0],emergency[1],pd.depth/2+d.panel.doorThickness],M.brass,'z');
 cyl(panel,d.panel.keyDiameter/2,d.panel.keyDiameter,[0,-pd.height*.16,pd.depth/2+d.panel.keyDiameter],M.black,'z');
 textPlate(panel,'مورد | MAWRID',[pd.width*.74,d.labels.plateHeight,d.labels.plateThickness],[0,pd.height*.36,pd.depth/2+d.panel.doorThickness],M.steel);
 tagged(13,panel,[0,-pd.height*.37,pd.depth/2+d.panel.doorThickness]);
 for(let i=0;i<6;i++)cyl(panel,d.panel.glandDiameter/2,d.panel.glandLength,[(i-2.5)*pd.width/8,-pd.height/2-d.panel.glandLength/2,0],M.black);
 const antX=-pd.width*.3;cyl(panel,d.panel.antennaDiameter/2,d.panel.antennaHeight,[antX,pd.height/2+d.panel.antennaHeight/2,0],M.black);
 const bx=pd.width*.25,by=pd.height/2;rod(panel,[bx,by,0],[bx,by+d.panel.beaconStemHeight,0],d.panel.antennaDiameter/2,M.steel);
 parts.beacons=[];for(let i=0;i<3;i++){const beacon=cyl(panel,d.panel.beaconDiameter/2,d.panel.beaconSegmentHeight,[bx,by+d.panel.beaconStemHeight+d.panel.beaconSegmentHeight*(i+.5),0],M.offGlow);beacon.layers.enable(1);parts.beacons.push(beacon);glows.push(beacon);}
 cable(panel,[[0,-pd.height/2,0],[pd.width*.4,-pd.height/2-d.cable.conduitDiameter,-pd.depth],[pd.width*.4,trayY-c.panel.centerHeight,trayZ-panel.position.z]]);
 anchor(13,[panelX,c.panel.centerHeight,panelZ+c.panel.depth]);
 // 15 — Drainage terminal; connected piping is built below.
 const drainage=group(15);const sewerX=xTreated+tt.length/2+L.irrigationEndpointOffset,sewerZ=-s.skid.width/2-L.service.rear/2;
 const sewerY=cd.overflowHeight-L.drainSlope*(sewerX-(xChamber+ch.length/2))-d.fittings.elbowRadius;
 const terminal=[sewerX,sewerY-d.fittings.drainReceptorHeight/2,sewerZ];cyl(drainage,d.fittings.drainReceptorDiameter/2,d.fittings.drainReceptorHeight,terminal,M.drain);
 port('sewer',15,[sewerX,sewerY,sewerZ]);
 const sewerSurfaceY=d.fittings.drainReceptorHeight;port('sewer.surface',15,[sewerX,sewerSurfaceY,sewerZ]);
 // Grade-level sump cover surrounds the vertical pipe penetration.
 torus(drainage,d.fittings.drainReceptorDiameter/2,d.fittings.bracketThickness,[sewerX,d.labels.surfaceGap,sewerZ],M.steel);
 for(const sign of [-1,1]){
  box(drainage,[s.site.drainTerminalWidth,d.fittings.bracketThickness,d.fittings.bracketThickness],[sewerX,d.labels.surfaceGap,sewerZ+sign*s.site.drainTerminalDepth/2],M.steel);
  box(drainage,[d.fittings.bracketThickness,d.fittings.bracketThickness,s.site.drainTerminalDepth],[sewerX+sign*s.site.drainTerminalWidth/2,d.labels.surfaceGap,sewerZ],M.steel);
  for(const ratio of [.25,.4])box(drainage,[d.fittings.bracketThickness,d.fittings.bracketThickness,s.site.drainTerminalDepth],[sewerX+sign*s.site.drainTerminalWidth*ratio,d.labels.surfaceGap,sewerZ],M.steel);
 }
 tagged(15,drainage,[sewerX,d.labels.plateHeight, sewerZ+d.fittings.drainReceptorDiameter/2]);anchor(15,[sewerX,0,sewerZ]);
 // Physical plumbing graph: every line has two registered, component-attached ports.
 const plumbing=new THREE.Group();plumbing.name='Connected pipe network';root.add(plumbing);
 const annotations=new THREE.Group();root.add(annotations);
 function run(name,from,to,bends=[],kind='raw',active='process',reverse=false){
  const start=world(from),end=world(to),points=[start,...bends.map(v3),end],od=kind==='drain'?c.drain.outerDiameter:s.pipe.outerDiameter;
  const material=(kind==='drain'?M.drain:kind==='treated'?M.purple:M.pipe).clone();const {curve,geometry}=pipeGeometry(points,od/2,d.fittings.elbowRadius);
  const m=new THREE.Mesh(geometry,material);m.castShadow=true;m.receiveShadow=true;m.userData.id=kind==='drain'?15:ports.get(to).id;plumbing.add(m);
  for(const [p,dir] of [[start,curve.getTangent(0)],[end,curve.getTangent(1)]]){const u=union(plumbing,p,'y',kind==='drain'?M.drain:M.pipe,od);u.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),dir);}
  const geo=new THREE.BufferGeometry().setFromPoints([start,end]);const dashed=new THREE.Line(geo,new THREE.LineDashedMaterial({color:'#708d83',dashSize:d.explode.lineDash,gapSize:d.explode.lineGap,transparent:true,opacity:.65}));dashed.computeLineDistances();dashed.visible=false;annotations.add(dashed);
  const count=Math.max(4,Math.min(80,Math.ceil(curve.getLength()/d.particles.spacing)));const particleMat=new THREE.MeshPhysicalMaterial({color:kind==='drain'?'#7c6852':kind==='treated'?'#8869c7':name.includes('raw')?'#b39463':'#58a9c1',roughness:.28,emissive:'#125065',emissiveIntensity:.18});
  const particles=new THREE.InstancedMesh(new THREE.SphereGeometry(d.particles.radius,6,4),particleMat,count);particles.visible=false;plumbing.add(particles);
  const r={name,from,to,points,curve,mesh:m,particles,count,kind,active,reverse,dashed};pipeRuns.push(r);
  // Actual pipe clamps are instanced, with rods to grade or the skid deck.
  const spacing=L.pipeSupportInterval,length=curve.getLength();for(let u=spacing/2;u<length;u+=spacing){const t=u/length,p=curve.getPointAt(t),dir=curve.getTangentAt(t);if(Math.abs(dir.y)>.5||p.y<base||p.y>trayY)continue;const q=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,0,1),dir);clamps.push({position:p,rotation:new THREE.Euler().setFromQuaternion(q).toArray().slice(0,3),scale:[od/s.pipe.outerDiameter,od/s.pipe.outerDiameter,1]});
   const footY=Math.abs(p.x)<s.skid.length/2&&Math.abs(p.z)<s.skid.width/2?base:0;supports.push({position:[p.x,(p.y+footY)/2,p.z],scale:[1,(p.y-footY)/d.fittings.supportBase,1]});}
  return r;
 }
 // Incoming ablution and lift rising main.
 port('site.source',1,[-ch.length/2-L.rawInletReach,cd.inletHeight,0]);
 run('raw-inlet','site.source','ch.in',[],'raw','raw');
 const liftOut=world('lift.out'),bin=world('balance.in');
 run('lift-to-balance','lift.out','balance.in',[[liftOut.x,L.pipeLowY,liftOut.z],[bin.x,L.pipeLowY,liftOut.z],[bin.x,L.pipeLowY,bin.z],[bin.x,bin.y,bin.z]],'raw','raw');
 valve(chamber,[ch.length*.32,L.pipeLowY,0],'y');cyl(chamber,s.pipe.outerDiameter*.75,d.valve.bodyLength,[ch.length*.32,L.pipeLowY-d.valve.bodyLength*1.3,0],M.brass);
 const bo=world('balance.out'),fi=world('4.in');run('raw-feed','balance.out','4.in',[[bo.x+d.instrument.probeHeight,bo.y,bo.z],[fi.x-d.fittings.elbowRadius*2,bo.y,bo.z],[fi.x-d.fittings.elbowRadius*2,fi.y,fi.z]],'raw','process');
 const fo=world('4.out'),si=world('5.in');
 const feedRise=si.x-d.instrument.flowLength-d.instrument.gaugeDiameter*2-d.fittings.elbowRadius*2;
 const meterZ=zFront+d.fittings.elbowRadius*2;
 const feedTee=[feedRise,si.y,meterZ];
 port('sand.feedtee',5,[feedTee[0]-px.sand,feedTee[1]-base,feedTee[2]-zTrain]);
 sphere(frame,s.pipe.outerDiameter*.72,feedTee,M.pipe);
 const meterEntryX=px.feed+c.pump.length/2,dischargeLift=fo.y+d.fittings.elbowRadius;
 run('feed-sand','4.out','sand.feedtee',[[fo.x,dischargeLift,fo.z],[meterEntryX,dischargeLift,fo.z],[meterEntryX,dischargeLift,meterZ],[meterEntryX,L.feedMeterY,meterZ],[feedRise,L.feedMeterY,meterZ]],'raw','process');
 run('sand-inlet-manifold','sand.feedtee','5.in',[[feedRise,si.y,zTrain]],'raw','sandInlet');
 const fm1X=meterEntryX-d.fittings.elbowRadius-d.instrument.flowLength/2;
 flowMeter(frame,[fm1X,L.feedMeterY,meterZ],'FM-1');
 pressure(frame,[fm1X-d.instrument.flowLength/2-d.instrument.gaugeDiameter/2,L.feedMeterY,meterZ],'P1',-1);
 const so=world('5.out'),ci=world('6.in');run('sand-carbon','5.out','6.in',[[so.x,so.y,zFront],[ci.x,ci.y,zFront]],'raw','process');pressure(frame,[(so.x+ci.x)/2,so.y,zFront],'P2');
 const co=world('6.out'),pi=world('pp.in');
 run('carbon-pp','6.out','pp.in',[[co.x,co.y,zFront],[co.x,pi.y,zFront],[pi.x,pi.y,zFront]],'raw','process');
 pressure(frame,[co.x+(pi.x-co.x)*.35,pi.y,zFront],'P3');
 sample(frame,[so.x+(ci.x-so.x)*.18,so.y,zFront]);sample(frame,[co.x+(pi.x-co.x)*.72,pi.y,zFront]);
 const po=world('pp.out'),ui=world('uv.in');const frontRun=zFront+d.fittings.elbowRadius*2;
 run('pp-uv','pp.out','uv.in',[[po.x,po.y,frontRun],[ui.x,po.y,frontRun],[ui.x,ui.y,frontRun]],'raw','process');pressure(frame,[po.x-(po.x-ui.x)*.4,po.y,frontRun],'P4',-1);
 const uo=world('uv.out'),ai=world('at.in');run('uv-cell','uv.out','at.in',[[uo.x,atY,zFront],[ai.x,atY,zFront]],'treated','process');
 const ao=world('at.out'),di=world('decision.in');run('cell-decision','at.out','decision.in',[[ao.x,ao.y,zFront],[ao.x,di.y,zFront]],'treated','process');
 const dout=world('decision.irrigate'),tin=world('treated.in');run('irrigation-isolation','decision.irrigate','treated.in',[[tin.x-d.fittings.elbowRadius*2,dout.y,zFront],[tin.x-d.fittings.elbowRadius*2,tin.y,zFront],[tin.x-d.fittings.elbowRadius*2,tin.y,tin.z]],'treated','normal');flowMeter(frame,[dout.x+d.instrument.flowLength/2,dout.y,dout.z],'FM-2');
 const tout=world('treated.out'),iin=world('irrigation.in');run('tank-pump','treated.out','irrigation.in',[[iin.x,tout.y,tout.z]],'treated','normal');
 const irrigationEnd=[xTreated+tt.length/2+L.irrigationEndpointOffset, L.dripHeight,L.irrigationEndZ];port('irrigation.terminal',12,[irrigationEnd[0]-xTreated,irrigationEnd[1],irrigationEnd[2]]);
 const iout=world('irrigation.out');run('irrigation-distribution','irrigation.out','irrigation.terminal',[[irrigationEnd[0],iout.y,iout.z],[irrigationEnd[0],irrigationEnd[1],iout.z]],'treated','normal');
 cyl(treated,s.pipe.outerDiameter/2,s.pipe.outerDiameter,[irrigationEnd[0]-xTreated,irrigationEnd[1],irrigationEnd[2]],M.black,'z');
 const dr=world('decision.return'),ret=world('balance.return');const rear=-s.skid.width/2-L.service.rear/2;
 run('fault-reprocess','decision.return','balance.return',[[dr.x,dr.y,rear],[ret.x,L.pipeLowY,rear],[ret.x,ret.y,rear]],'raw','fault');
 const tw=world('treated.wash'),wi=world('11.in');
 const washAroundX=feedRise-d.fittings.elbowRadius*2, washFrontZ=zFront+d.fittings.elbowRadius*4;
 const washSuctionX=wi.x-d.fittings.elbowRadius;
 run('backwash-supply','treated.wash','11.in',[[tw.x,d.treated.outletHeight,rear],[washAroundX,d.treated.outletHeight,rear],[washAroundX,wi.y,rear],[washAroundX,wi.y,washFrontZ],[washSuctionX,wi.y,washFrontZ],[washSuctionX,wi.y,zFront]],'treated','backwash');
 const wo=world('11.out'),bw=world('5.bw'),washDischargeZ=washFrontZ+d.fittings.elbowRadius*2;
 const washDischargeY=wo.y+d.fittings.elbowRadius;
 run('backwash-pump','11.out','sand.feedtee',[[wo.x,washDischargeY,wo.z],[wo.x,washDischargeY,washDischargeZ],[feedRise,washDischargeY,washDischargeZ],[feedRise,si.y,washDischargeZ]],'raw','backwash');
 valve(frame,[(wo.x+feedRise)/2,washDischargeY,washDischargeZ],'x');valve(frame,[(washAroundX+washSuctionX)/2,wi.y,washFrontZ],'x');
 // Isolation bodies at the actual tee branches make the shared feed manifold explicit.
 valve(frame,[feedRise,si.y-d.fittings.elbowRadius*2,meterZ],'y');
 valve(frame,[feedRise,si.y,washDischargeZ-d.fittings.elbowRadius],'z');
 // Air gap: discharge ends over a receptor, never connected across the open gap.
 const gapX=s.skid.length/2-d.fittings.elbowRadius,gapZ=L.drainZ;
 const receptorBase=d.fittings.drainReceptorHeight*2,receptorTop=receptorBase+d.fittings.drainReceptorHeight;
 const receptorY=receptorBase+d.fittings.drainReceptorHeight/2;
 cyl(drainage,d.fittings.drainReceptorDiameter/2,d.fittings.drainReceptorHeight,[gapX,receptorY,gapZ],M.drain);
 for(const sign of [-1,1])rod(drainage,[gapX+sign*d.fittings.drainReceptorDiameter/2,0,gapZ],[gapX+sign*d.fittings.drainReceptorDiameter/2,receptorBase,gapZ],d.fittings.bracketThickness,M.steel);
 port('airgap.spout',15,[gapX,receptorTop+d.fittings.drainAirGap,gapZ]);port('airgap.receptor',15,[gapX,receptorTop,gapZ]);
 const spoutY=receptorTop+d.fittings.drainAirGap;
 const cbw=world('6.bw'),wasteJoin=[gapX,spoutY+d.fittings.elbowRadius*2,rear-d.fittings.elbowRadius];
 port('waste.join',15,wasteJoin);sphere(drainage,c.drain.outerDiameter*.65,wasteJoin,M.drain);
 // Carbon waste remains connected and isolated during the sand-only backwash demonstration.
 run('carbon-backwash-drain','6.bw','waste.join',[[cbw.x,cbw.y,rear-d.fittings.elbowRadius],[gapX,cbw.y,rear-d.fittings.elbowRadius]],'drain','carbonWash');
 run('sand-backwash-drain','5.bw','waste.join',[[bw.x,bw.y,rear-d.fittings.elbowRadius*3],[gapX,bw.y,rear-d.fittings.elbowRadius*3],[gapX,wasteJoin[1],rear-d.fittings.elbowRadius*3]],'drain','backwash');
 run('airgap-discharge','waste.join','airgap.spout',[[gapX,wasteJoin[1],gapZ]],'drain','backwash');
 valve(frame,[cbw.x,cbw.y,rear-d.fittings.elbowRadius/2],'z');
 const ov=world('balance.over'),dd=world('decision.drain'),bp=world('balance.drain'),se=world('sewer');
 const overflowX=xBalance+s.balance.diameter/2+d.fittings.elbowRadius*2;
 const trunkY=x=>sewerSurfaceY+L.drainSlope*(sewerX-x);
 const junctions=[['drain.overflow',overflowX],['drain.diversion',dd.x],['drain.wash',gapX]].sort((a,b)=>a[1]-b[1]);
 for(const [name,x] of junctions){port(name,15,[x,trunkY(x),sewerZ]);sphere(drainage,c.drain.outerDiameter*.6,[x,trunkY(x),sewerZ],M.drain);}
 for(let i=0;i<junctions.length;i++)run(`gravity-main-${i}`,junctions[i][0],i<junctions.length-1?junctions[i+1][0]:'sewer.surface',[],'drain',i===junctions.length-1?'backwash':'drain');
 run('overflow','balance.over','drain.overflow',[[overflowX,ov.y,ov.z],[overflowX,ov.y,sewerZ]],'drain','overflow');
 run('divert-drain','decision.drain','drain.diversion',[[dd.x,dd.y,sewerZ]],'drain','drain');
 // Receptor drains around the right skirt; no pipe crosses the front service step.
 run('backwash-to-sewer','airgap.receptor','drain.wash',[[gapX,receptorTop-d.fittings.elbowRadius,gapZ],[gapX,receptorTop-d.fittings.elbowRadius,sewerZ]],'drain','backwash');
 run('sewer-downpipe','sewer.surface','sewer',[],'drain','backwash');
 // The low tank drain cannot flow uphill to the raised collector. It drops locally
 // into a buried branch, then descends continuously to the underground sewer.
 const buriedZ=bp.z+d.fittings.elbowRadius*2;
 const tankEntryY=sewerY+L.drainSlope*(sewerX-bp.x+Math.abs(buriedZ-sewerZ));
 port('tank.buried',15,[bp.x,tankEntryY,buriedZ]);
 run('tank-drain','balance.drain','tank.buried',[[bp.x,bp.y,buriedZ]],'drain','drain');
 const buriedTank=run('tank-drain-underground','tank.buried','sewer',[[bp.x,tankEntryY-L.drainSlope*Math.abs(buriedZ-sewerZ),sewerZ]],'drain','drain');buriedTank.underground=true;
 const cho=world('ch.over');const chamberDrain=run('chamber-overflow','ch.over','sewer',[[cho.x,cho.y-L.drainSlope*Math.abs(cho.z-sewerZ),sewerZ],[se.x,cho.y-L.drainSlope*(Math.abs(cho.z-sewerZ)+se.x-cho.x),sewerZ]],'drain','overflow');chamberDrain.underground=true;
 // Instrument wiring is led backwards first and then along the rear tray.
 for(const [id,local] of [[4,[0,pumpY+c.pump.motorDiameter,0]],[5,[0,s.sand.height+s.valveHead.height*.5,0]],[6,[0,s.carbon.height+s.valveHead.height*.5,0]],[7,[0,ph,0]],[10,[mainX,d.valve.bodyDiameter/2+d.valve.actuatorHeight,0]]]){
  const g=groups.get(id),p=g.position; cable(g,[local,[local[0],local[1],trayZ-p.z],[local[0],trayY-p.y,trayZ-p.z],[panelX-p.x,trayY-p.y,trayZ-p.z]]);
 }
 // Small pipe direction bands, each attached to an actual straight section.
 const bandRuns=pipeRuns.filter(r=>['raw-feed','irrigation-isolation','overflow','fault-reprocess','backwash-pump'].includes(r.name));
 const pipeBands=[];for(const r of bandRuns){const p=r.curve.getPointAt(.55);const label=r.kind==='drain'?'صرف':r.kind==='treated'?'معالج':'خام';const plate=textPlate(plumbing,label,[d.labels.pipeBandWidth*1.5,d.labels.plateHeight*.6,d.labels.plateThickness],[p.x,p.y,p.z+s.pipe.outerDiameter/2+d.labels.surfaceGap],M.steel,{bg:r.kind==='treated'?'#6f568f':r.kind==='drain'?'#2e3634':'#e7e9e5',color:r.kind==='raw'?'#233e35':'#ffffff'});const tangent=r.curve.getTangentAt(.55).normalize();let outward=new THREE.Vector3(0,0,1).addScaledVector(tangent,-tangent.z);if(outward.lengthSq()<.01)outward=new THREE.Vector3(0,1,0).addScaledVector(tangent,-tangent.y);outward.normalize();
 const arrowCenter=p.clone().addScaledVector(outward,(r.kind==='drain'?c.drain.outerDiameter:s.pipe.outerDiameter)/2+d.labels.surfaceGap);
 const arrowMaterial=r.kind==='raw'?M.black:M.white;
 rod(plumbing,arrowCenter.clone().addScaledVector(tangent,-d.labels.pipeArrowLength/2),arrowCenter.clone().addScaledVector(tangent,d.labels.pipeArrowLength/4),d.labels.surfaceGap/2,arrowMaterial);
 const arrowTip=new THREE.Mesh(new THREE.ConeGeometry(d.labels.surfaceGap*2,d.labels.pipeArrowLength/3,10),arrowMaterial);arrowTip.position.copy(arrowCenter).addScaledVector(tangent,d.labels.pipeArrowLength/3);arrowTip.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),tangent);plumbing.add(arrowTip);
 pipeBands.push({r,plate});}
 // Repeated fastening and supports are instanced; rigid structure is merged.
 instanced(frame,new THREE.CylinderGeometry(d.fasteners.boltDiameter/2,d.fasteners.boltDiameter/2,d.fasteners.boltHeadHeight,6),M.steel,bolts);
 instanced(plumbing,new THREE.TorusGeometry(s.pipe.outerDiameter/2+d.fittings.clampWall,d.fittings.clampWall/2,6,16),M.steel,clamps);
 instanced(plumbing,new THREE.CylinderGeometry(d.fittings.clampWall/2,d.fittings.clampWall/2,d.fittings.supportBase,8),M.steel,supports);
 mergeStatic(frame);
 // Fold-down front service step; stowed and deployed positions remain hinged.
 const step=new THREE.Group(),sd=d.serviceStep;step.position.set((px.sand+px.carbon)/2,sd.height,s.skid.width/2);root.add(step);
 box(step,[sd.width,sd.treadThickness,sd.depth],[0,0,sd.depth/2],M.steel);
 const stepLegs=[];
 for(const sign of [-1,1]){
  const leg=new THREE.Group();leg.position.set(sign*sd.width*.4,-sd.treadThickness/2,sd.depth*.8);step.add(leg);
  rod(leg,[0,0,0],[0,-(sd.height-sd.treadThickness/2),0],sd.legWidth/2,M.steel);stepLegs.push(leg);
  torus(step,sd.hingeDiameter/2,sd.legWidth/4,[sign*sd.width*.4,0,0],M.steel,'x');
  box(frame,[sd.legWidth,sd.height-base,sd.legWidth],[step.position.x+sign*sd.width*.4,(sd.height+base)/2,step.position.z],M.steel);
 }
 step.rotation.x=-Math.PI/2;parts.step=step;
 // Service envelopes shown as transparent ground areas, rear boundary 0.30 m.
 const service=new THREE.Group();root.add(service);const sm=new THREE.MeshPhysicalMaterial({color:'#a6c8b9',transparent:true,opacity:.16,roughness:1,depthWrite:false});
 box(service,[s.skid.length+L.service.ends*2,d.labels.surfaceGap,L.service.front],[0,d.labels.surfaceGap,s.skid.width/2+L.service.front/2],sm);
 for(const sign of [-1,1])box(service,[L.service.ends,d.labels.surfaceGap,s.skid.width],[sign*(s.skid.length/2+L.service.ends/2),d.labels.surfaceGap,0],sm);
 box(service,[s.skid.length,d.labels.surfaceGap,L.service.rear],[0,d.labels.surfaceGap,-s.skid.width/2-L.service.rear/2],sm);
 const clearMat=new THREE.MeshPhysicalMaterial({color:'#cbbd82',transparent:true,opacity:.07,wireframe:true,depthWrite:false});
 for(const [x,f] of [[px.sand,s.sand],[px.carbon,s.carbon]])box(service,[f.diameter,L.service.headClearance,f.diameter],[x,base+f.height+s.valveHead.height+L.service.headClearance/2,zTrain],clearMat);
 // Human reference: exact overall height 1.75 m, anonymous, grounded feet.
 const human=new THREE.Group();const H=s.human;human.position.set(xTreated+tt.length/2+L.irrigationEndpointOffset,0,-s.skid.width/2-L.service.rear);root.add(human);
 const humanMat=new THREE.MeshPhysicalMaterial({color:'#9caaa4',roughness:.75});const headY=H.height-H.headRadius;
 sphere(human,H.headRadius,[0,headY,0],humanMat,[.82,1,.85]);const torsoTop=headY-H.headRadius-H.neckHeight;
 box(human,[H.torsoWidth,H.torsoHeight,H.torsoDepth],[0,torsoTop-H.torsoHeight/2,0],humanMat,H.torsoDepth/3);
 cyl(human,H.armDiameter/3,H.neckHeight,[0,torsoTop+H.neckHeight/2,0],humanMat);
 for(const sign of [-1,1]){const lx=sign*H.stanceWidth/2;rod(human,[lx,H.footHeight,0],[lx,torsoTop-H.torsoHeight*.7,0],H.legDiameter/2,humanMat);box(human,[H.footWidth,H.footHeight,H.footLength],[lx,H.footHeight/2,H.footLength*.18],humanMat,H.footHeight/3);rod(human,[sign*H.torsoWidth*.48,torsoTop-H.armDiameter,0],[sign*H.torsoWidth*.7,torsoTop-H.armLength,0],H.armDiameter/2,humanMat);}
 human.visible=false;
 // Selection highlight follows the picked component, never changes optical material.
 const selection=new THREE.Box3Helper(new THREE.Box3(),new THREE.Color('#a59461'));selection.visible=false;root.add(selection);
 root.traverse(o=>{if(o.isMesh&&!o.userData.id){let p=o.parent;while(p&&p!==root){if(p.userData.id){o.userData.id=p.userData.id;break;}p=p.parent;}}});
 const dummy=new THREE.Object3D();let explodeAmount=0,returnAmount=0,stepAmount=0;
 function updateState(next){Object.assign(state,next);human.visible=!!next.human;service.visible=!!next.service||!!next.labels;
  cutMaterials.forEach(({mat,z})=>{mat.clippingPlanes=state.cutaway?[new THREE.Plane(new THREE.Vector3(0,0,-1),z)]:[];mat.needsUpdate=true;});inside.forEach(o=>o.visible=!!state.cutaway||!!o.userData.visibleThroughShell);
  const mode=state.mode;parts.indicator.material=mode==='normal'?M.greenGlow:M.redGlow;parts.returnHandle.material=mode==='normal'?M.greenGlow:M.redGlow;
  parts.beacons.forEach((b,i)=>b.material=mode==='poweroff'?M.offGlow:mode==='normal'&&i===0?M.greenGlow:mode==='backwash'&&i===1?M.yellowGlow:mode==='fault'&&i===2?M.redGlow:M.offGlow);
  lamp.material=mode==='poweroff'?M.quartz:M.uvGlow;led.material=mode==='poweroff'?M.offGlow:M.greenGlow;
  const text=mode==='fault'?['احتجاز: عكارة نهائية خارج الحد','V-601 مغلق · إعادة معالجة']:mode==='poweroff'?['انقطاع الكهرباء','V-601 مغلق بالنابض']:mode==='backwash'?['غسيل عكسي','الري مغلق · الصرف فعال']:['تشغيل طبيعي','عكارة 0.6 NTU · pH 7.2','قيم محاكاة'];
  const tex=canvasTexture((ctx,w,h)=>{ctx.fillStyle=mode==='poweroff'?'#0e1515':'#103831';ctx.fillRect(0,0,w,h);ctx.fillStyle=mode==='fault'?'#ffc8ba':'#d6ede1';ctx.textAlign='center';ctx.direction='rtl';ctx.font=`${h/(text.length*1.6)}px Arial`;text.forEach((l,i)=>ctx.fillText(l,w/2,h*(i+.75)/text.length,w*.96));});parts.screen.material.map.dispose();parts.screen.material.map=tex;parts.screen.material.needsUpdate=true;
  pipeRuns.forEach(r=>{r.mesh.visible=!r.underground||state.cutaway;r.mesh.material.transparent=!!state.flow;r.mesh.material.opacity=state.flow?.18:1;r.mesh.material.depthWrite=!state.flow;r.mesh.material.needsUpdate=true;});
 }
 function active(r){return state.mode!=='poweroff'&&(r.active===state.mode||(r.active==='process'&&(state.mode==='normal'||state.mode==='fault'))||(r.active==='raw'&&state.mode==='normal')||(r.active==='sandInlet'&&['normal','fault','backwash'].includes(state.mode)));}
 function update(time,dt,reduced=false){
  const ease=reduced?1:1-Math.exp(-dt*6);explodeAmount+=(Number(state.exploded)-explodeAmount)*ease;returnAmount+=((state.mode==='normal'?0:1)-returnAmount)*ease;stepAmount+=(Number(state.step)-stepAmount)*ease;
  groups.forEach(g=>g.position.copy(g.userData.home).addScaledVector(g.userData.explode,explodeAmount));
  plumbing.visible=explodeAmount<.02;annotations.visible=explodeAmount>.01;
  for(const r of pipeRuns){r.dashed.visible=explodeAmount>.01;if(explodeAmount>.01){const f=ports.get(r.from),t=ports.get(r.to),a=f.local.clone().add(groups.get(f.id).position),b=t.local.clone().add(groups.get(t.id).position);r.dashed.geometry.setFromPoints([a,b]);r.dashed.computeLineDistances();}r.particles.visible=!!state.flow&&active(r)&&explodeAmount<.02&&(!r.underground||state.cutaway);
   if(r.particles.visible){for(let i=0;i<r.count;i++){let t=(i/r.count+(reduced?0:time*.24/r.curve.getLength()))%1;if(r.reverse)t=1-t;dummy.position.copy(r.curve.getPointAt(t));dummy.updateMatrix();r.particles.setMatrixAt(i,dummy.matrix);}r.particles.instanceMatrix.needsUpdate=true;}
  }
  parts.returnHandle.rotation.y=returnAmount*Math.PI/2;parts.diverterHandle.rotation.y=(state.mode==='fault'?returnAmount:0)*Math.PI/2;parts.step.rotation.x=-(1-stepAmount)*Math.PI/2;
  stepLegs.forEach(leg=>leg.rotation.x=(1-stepAmount)*Math.PI/2);
  sandFlow.visible=state.cutaway&&state.mode!=='poweroff';sandParticles.visible=state.flow;
  const upward=state.mode==='backwash';sandArrowMaterial.color.set(upward?'#a28b58':'#578bb5');
  sandArrows.forEach(arrow=>arrow.rotation.z=upward?0:Math.PI);
  if(sandFlow.visible&&sandParticles.visible){for(let i=0;i<sandFlowCount;i++){
   const t=(i/sandFlowCount+(reduced?0:time*.25))%1;
   dummy.position.set(0,sandFlowBottom+sandFlowHeight*(upward?t:1-t),sandFlowZ);dummy.updateMatrix();sandParticles.setMatrixAt(i,dummy.matrix);
  }sandParticles.instanceMatrix.needsUpdate=true;}

  if(!reduced&&state.mode!=='poweroff')fans.forEach((fan,i)=>{if((state.mode==='backwash'&&i===1)||(state.mode!=='backwash'&&i===0))fan.rotation.x+=dt*12;});
  if(selection.visible&&state.selected){selection.box.setFromObject(groups.get(state.selected));}
 }
 function select(id){state.selected=id;selection.visible=!!id;if(id)selection.box.setFromObject(groups.get(id));}
 function getAnchor(id){const p=anchors.get(id)?.clone()||new THREE.Vector3();const g=groups.get(id);if(g)p.addScaledVector(g.userData.explode,explodeAmount);return p;}
 function dispose(){root.traverse(o=>{o.geometry?.dispose();if(o.isMesh){const ms=Array.isArray(o.material)?o.material:[o.material];ms.forEach(m=>{if(!Object.values(M).includes(m)){m.map?.dispose();m.dispose();}});}});}
 updateState(state);
 return {root,groups,ports,pipeRuns,anchors,getAnchor,select,updateState,update,dispose,glows,positions:{balance:xBalance,chamber:xChamber,treated:xTreated,train:0,panel:panelX,valve:px.valve},dimensions:{headY:base+Math.max(s.sand.height,s.carbon.height)+s.valveHead.height},service,plumbing};
}
