import '@fontsource/ibm-plex-sans-arabic/400.css';
import '@fontsource/ibm-plex-sans-arabic/500.css';
import '@fontsource/ibm-plex-sans-arabic/600.css';
import '@fontsource/ibm-plex-sans-arabic/700.css';
import './style.css';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { SMAAPass } from 'three/addons/postprocessing/SMAAPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { unitSpec, resolveSpec } from './unitSpec.js';
import { getComponents, csvFromComponents } from './components.js';
import { createMaterials } from './materials.js';
import { createPlant } from './model.js';
import { createEnvironment } from './environment.js';
import { mountUI } from './ui.js';

const state={preset:'M20',environment:'studio',mode:'normal',cutaway:false,exploded:false,flow:false,labels:false,human:false,step:false,service:false,selected:null,quality:'auto'};
let spec=resolveSpec(state.preset),plant,environment,renderer,scene,camera,controls,composer,gtao,smaa,bloomComposer,bloomPass,blendPass,sun,materials,ui,exporting=false;
let mobile=innerWidth<spec.rendering.mobileBreakpoint,quality='mobile',fps=60,clockTime=0,previous=0,frameCount=0,frameWindow=0,lowWindows=0,presetScale=1,cameraMove=null,dirtyFrames=3,transitionUntil=0,viewVisible=true,dragging=false,needsSharpFrame=false,fittedView='overview';
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const viewport=document.getElementById('viewport');
const overlay=document.getElementById('annotation-layer');
const capturedErrors=[];
window.addEventListener('error',e=>capturedErrors.push(e.message));
function components(){return getComponents(spec);}
function setStatus(t){ui?.setStatus(t);}
function download(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),30000);}
function csv(){download(new Blob([csvFromComponents(spec)],{type:'text/csv;charset=utf-8'}),`MAWRID-${state.preset}-components.csv`);}
ui=mountUI({state,getComponents:components,onChange:change,onCamera:view,onExport:background=>exportPNG(background),onCSV:csv,onSelect:select});

function initialize(){
 if(new URLSearchParams(location.search).has('fallback')){fallback('اختبار الصورة البديلة');return;}
 try{
  renderer=new THREE.WebGLRenderer({alpha:true,antialias:false,preserveDrawingBuffer:false,powerPreference:'high-performance'});
 }catch(error){fallback(error);return;}
 renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.8;
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;renderer.shadowMap.autoUpdate=false;renderer.shadowMap.needsUpdate=true;renderer.localClippingEnabled=true;renderer.setClearColor('#e9eae5',1);
 renderer.domElement.id='scene-canvas';renderer.domElement.setAttribute('aria-label','مجسم مورد الهندسي؛ اسحب للدوران أو استخدم أزرار الزوايا');renderer.domElement.tabIndex=0;
 viewport.prepend(renderer.domElement);
 renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();fallback('تعذر استمرار WebGL. الصورة الهندسية البديلة متاحة.');});
 scene=new THREE.Scene();scene.background=new THREE.Color('#e9eae5');
 const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();const env=pmrem.fromScene(room,.04);scene.environment=env.texture;scene.environmentIntensity=.55;room.dispose();pmrem.dispose();
 const cs=spec.camera;camera=new THREE.PerspectiveCamera(cs.fov,1,cs.near,cs.far);
 controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=!reduced;controls.dampingFactor=.08;controls.minDistance=cs.minDistance;controls.maxDistance=cs.maxDistance;controls.maxPolarAngle=Math.PI*.58;controls.target.set(cs.target.x,cs.target.y,cs.target.z);
 controls.addEventListener('start',()=>{fittedView=null;cameraMove=null;dragging=true;setResolution(1);dirtyFrames=3;});controls.addEventListener('end',()=>{dragging=false;needsSharpFrame=true;dirtyFrames=3;});controls.addEventListener('change',()=>{dirtyFrames=2;});
 new IntersectionObserver(entries=>{viewVisible=entries[0].isIntersecting;if(viewVisible)dirtyFrames=3;},{threshold:.05}).observe(viewport);
 sun=new THREE.DirectionalLight('#fff0dc',2.2);sun.position.set(spec.site.groundLength*.24,spec.site.wallHeight*3,spec.site.groundWidth*.24);sun.castShadow=true;
 sun.shadow.camera.left=-spec.site.groundLength/2;sun.shadow.camera.right=spec.site.groundLength/2;sun.shadow.camera.top=spec.site.groundWidth/2;sun.shadow.camera.bottom=-spec.site.groundWidth/2;sun.shadow.camera.near=cs.near;sun.shadow.camera.far=cs.far;sun.shadow.bias=-.00015;sun.shadow.normalBias=spec.detail.labels.surfaceGap;sun.shadow.radius=3;scene.add(sun);
 const fill=new THREE.HemisphereLight('#e9f0ec','#b3b5a6',.65);scene.add(fill);
 materials=createMaterials(spec);rebuild();
 buildComposers();applyQuality();resize();view('overview',true);
 renderer.domElement.addEventListener('pointerdown',pointerDown);renderer.domElement.addEventListener('pointerup',pick);
 addEventListener('resize',resize);new ResizeObserver(resize).observe(viewport);
 ui.setLoading(false);setStatus('المشهد جاهز · اسحب للدوران وانقر لاستكشاف قطعة');
 requestAnimationFrame(animate);
 window.MAWRID={state,unitSpec,get spec(){return spec;},get plant(){return plant;},get camera(){return camera;},change,view,exportData:async(bg='white')=>(await renderExport(bg)).toDataURL('image/png'),exportPNG,csv:()=>csvFromComponents(spec),diagnostics:()=>({preset:state.preset,headY:plant.dimensions.headY,components:plant.groups.size,ports:plant.ports.size,pipes:plant.pipeRuns.length,invalidCoordinates:invalidCoordinates(),valveClosed:state.mode!=='normal',quality,fps:Math.round(fps),drawCalls:renderer.info.render.calls,triangles:renderer.info.render.triangles,errors:capturedErrors}),ready:true};
}
function invalidCoordinates(){const errors=[];plant.root.traverse(o=>{if(![o.position.x,o.position.y,o.position.z].every(Number.isFinite))errors.push(o.name||o.type);const a=o.geometry?.attributes.position?.array;if(a&&a.some(v=>!Number.isFinite(v)))errors.push(`${o.name||o.type}:vertices`);});return errors;}
function fallback(error){console.info(String(error));if(renderer){renderer.domElement.style.display='none';renderer.dispose();renderer=null;}viewport.classList.add('webgl-failed');const img=document.getElementById('fallback');if(img){img.hidden=false;img.style.display='block';img.alt='منظور استوديو لوحدة مورد M20؛ تعذّر تشغيل WebGL على هذا الجهاز';}ui.setLoading(false);setStatus('عرض الصورة البديلة: WebGL غير متاح. جدول المكونات والتنزيل متاحان.');}
function rebuild(){
 if(plant){scene.remove(plant.root);plant.dispose();environment.dispose();}
 spec=resolveSpec(state.preset);plant=createPlant(spec,materials);scene.add(plant.root);environment=createEnvironment({scene,materials,spec});environment.setMode(state.environment);environment.setCutaway?.(state.cutaway);plant.updateState(state);plant.select(state.selected);
 presetScale=reduced?1:.97;
}
function buildComposers(){
 composer=new EffectComposer(renderer);composer.addPass(new RenderPass(scene,camera));
 gtao=new GTAOPass(scene,camera,1,1);gtao.blendIntensity=.6;gtao.updateGtaoMaterial({radius:spec.detail.fittings.elbowRadius*3,distanceExponent:1,thickness:spec.common.frame.post,scale:1,samples:8});composer.addPass(gtao);
 bloomComposer=new EffectComposer(renderer);bloomComposer.renderToScreen=false;const bp=new RenderPass(scene,camera);bp.clearColor=new THREE.Color('#000000');bp.clearAlpha=0;bloomComposer.addPass(bp);
 bloomPass=new UnrealBloomPass(new THREE.Vector2(1,1),.45,.3,.35);bloomComposer.addPass(bloomPass);
 blendPass=new ShaderPass({uniforms:{tDiffuse:{value:null},bloomTexture:{value:null}},vertexShader:'varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',fragmentShader:'uniform sampler2D tDiffuse; uniform sampler2D bloomTexture; varying vec2 vUv; void main(){vec4 base=texture2D(tDiffuse,vUv);vec3 glow=texture2D(bloomTexture,vUv).rgb;gl_FragColor=vec4(base.rgb+glow,max(base.a,min(1.0,length(glow))));}'});blendPass.uniforms.bloomTexture.value=bloomComposer.renderTarget2.texture;composer.addPass(blendPass);
 smaa=new SMAAPass();composer.addPass(smaa);composer.addPass(new OutputPass());
}
function applyQuality(){
 quality=state.quality==='auto'?'mobile':state.quality;
 const low=quality==='mobile';const r=spec.rendering;
 setResolution(mobile?r.mobilePixelRatio:r.desktopPixelRatio);
 const shadow=low?r.mobileShadow:r.desktopShadow;sun.shadow.mapSize.set(shadow,shadow);sun.shadow.map?.dispose();sun.shadow.map=null;
 gtao.enabled=!low;smaa.enabled=true;blendPass.enabled=!low;renderer.shadowMap.needsUpdate=true;dirtyFrames=3;resize();
}
function setResolution(ratio){renderer.setPixelRatio(ratio);composer?.setPixelRatio(ratio);bloomComposer?.setPixelRatio(1);}
function resize(){if(!renderer||exporting)return;const wasMobile=mobile;mobile=innerWidth<spec.rendering.mobileBreakpoint;if(mobile!==wasMobile&&!dragging)setResolution(mobile?spec.rendering.mobilePixelRatio:spec.rendering.desktopPixelRatio);const w=Math.max(1,viewport.clientWidth),h=Math.max(1,viewport.clientHeight),previousAspect=camera.aspect;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h);composer?.setSize(w,h);if(gtao)gtao.setSize(Math.max(1,Math.round(w*renderer.getPixelRatio()/2)),Math.max(1,Math.round(h*renderer.getPixelRatio()/2)));bloomComposer?.setSize(Math.round(w/2),Math.round(h/2));dirtyFrames=3;mobile=innerWidth<spec.rendering.mobileBreakpoint;if(fittedView==='overview'&&!dragging&&Math.abs(previousAspect-camera.aspect)>0.01)view('overview',true);}
function change(patch){
 const old={...state};Object.assign(state,patch);dirtyFrames=4;transitionUntil=performance.now()+1100;
 if(!renderer){spec=resolveSpec(state.preset);ui.sync(state);return;}
 if(old.preset!==state.preset){rebuild();view('overview');ui.showComponent(state.selected?components().find(c=>c.id===state.selected):null);}
 else plant.updateState(state);environment.setCutaway?.(state.cutaway);
 if(old.environment!==state.environment){environment.setMode(state.environment);scene.background=new THREE.Color(state.environment==='site'?'#e6e9e1':'#e9eae5');sun.intensity=state.environment==='site'?2.8:2.2;}
 if(old.quality!==state.quality)applyQuality();renderer.shadowMap.needsUpdate=true;
 if(old.labels!==state.labels&&state.labels)view('overview');
 ui.sync(state);if(old.labels!==state.labels)requestAnimationFrame(()=>{resize();view('overview');});setStatus(state.mode==='fault'?'احتجاز: عكارة نهائية خارج الحد · صمام الري مغلق':state.mode==='poweroff'?'انقطاع كهرباء · عودة نابض V-601 إلى الإغلاق':state.mode==='backwash'?'غسيل عكسي · تدفق إلى الصرف بفجوة هوائية':'تشغيل طبيعي · قراءات توضيحية للمحاكاة');
}
function select(id){dirtyFrames=3;state.selected=id;plant?.select(id);ui.sync(state);ui.showComponent(id?components().find(c=>c.id===id):null);}
let pointerStart=null;
function pointerDown(e){pointerStart=[e.clientX,e.clientY];}
function pick(e){if(!pointerStart||Math.hypot(e.clientX-pointerStart[0],e.clientY-pointerStart[1])>6)return;const r=renderer.domElement.getBoundingClientRect();const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);const hits=ray.intersectObject(plant.root,true);const hit=hits.find(h=>h.object.visible&&h.object.userData.id);if(hit)select(hit.object.userData.id);}
function view(key,instant=false){if(!camera)return;fittedView=key;dirtyFrames=3;transitionUntil=performance.now()+1100;const cs=spec.camera;let target=new THREE.Vector3(cs.target.x,cs.target.y,cs.target.z),position;
 if(key==='overview'){const p=cs.overview;const spread=(spec.skid.length+spec.balance.diameter+spec.treated.length+spec.common.chamber.length+spec.layout.tankSkidGap*2+spec.layout.chamberTankGap)/10;const ratio=Math.max(1,1.25/camera.aspect);position=new THREE.Vector3(p.x*spread*ratio*1.12,p.y*spread*ratio*1.12,p.z*spread*ratio*1.12);target.x=(plant.positions.chamber-spec.common.chamber.length/2-spec.layout.rawInletReach+plant.positions.treated+spec.treated.length/2+spec.layout.irrigationEndpointOffset)/2+spec.layout.service.ends*.7;}
 else if(key==='train'){position=new THREE.Vector3(cs.train.x,cs.train.y,cs.train.z);target.set(0,spec.layout.processRailY,0);}
 else if(key==='panel'){target=plant.getAnchor(13);position=target.clone().add(new THREE.Vector3(cs.panel.x-spec.positions.panel.x,cs.panel.y-spec.common.panel.centerHeight,cs.panel.z));}
 else if(key==='valves'){target=plant.getAnchor(10);position=target.clone().add(new THREE.Vector3(cs.valves.x-spec.positions.valve.x,cs.valves.y-spec.layout.valveCenterY,cs.valves.z));}
 else {target=plant.getAnchor(1);position=target.clone().add(new THREE.Vector3(spec.common.chamber.length,cs.collection.y,cs.collection.z));}
 if(instant||reduced){camera.position.copy(position);controls.target.copy(target);controls.update();cameraMove=null;}else cameraMove={from:camera.position.clone(),to:position,start:controls.target.clone(),target,elapsed:0};
}
function render(){
 if(blendPass.enabled){const bg=scene.background;scene.background=new THREE.Color('#000000');camera.layers.set(1);bloomComposer.render();camera.layers.set(0);scene.background=bg;}
 composer.render();
}
function animate(now){
 if(!renderer)return;requestAnimationFrame(animate);if(exporting||!viewVisible||document.hidden){previous=now;return;}
 const dt=Math.min((now-previous)/1000||1/60,.1);previous=now;clockTime+=dt;
 const closeMotorAnimation=!reduced&&state.mode!=='poweroff'&&controls.getDistance()<spec.camera.train.z+spec.skid.width;
 const moving=!!cameraMove||now<transitionUntil||state.flow&&!reduced||closeMotorAnimation;
 if(needsSharpFrame&&!dragging){setResolution(mobile?spec.rendering.mobilePixelRatio:spec.rendering.desktopPixelRatio);resize();needsSharpFrame=false;}
 if(!moving&&dirtyFrames<=0){if(!animate.idle){ui.setPerformance(0,quality);animate.idle=true;}return;}animate.idle=false;
 const interval=1000/(quality==='mobile'?30:60);if(now-frameWindow<interval*.9)return;
 const frameDt=Math.min(.05,Math.max(dt,(now-frameWindow)/1000));
 if(cameraMove){cameraMove.elapsed+=frameDt;const t=Math.min(1,cameraMove.elapsed/spec.rendering.transitionSeconds),e=t*t*(3-2*t);camera.position.lerpVectors(cameraMove.from,cameraMove.to,e);controls.target.lerpVectors(cameraMove.start,cameraMove.target,e);if(t===1)cameraMove=null;}
 presetScale+=(1-presetScale)*Math.min(1,dt*9);plant.root.scale.setScalar(presetScale);plant.update(clockTime,frameDt,reduced);controls.update();
 if(now<transitionUntil)renderer.shadowMap.needsUpdate=true;
 render();renderAnnotations();dirtyFrames=Math.max(0,dirtyFrames-1);frameWindow=now;
 frameCount++;if(now-(animate.lastFPS||0)>2500){fps=frameCount*1000/(now-(animate.lastFPS||0));frameCount=0;animate.lastFPS=now;ui.setPerformance(Math.min(60,Math.max(1,Math.round(fps))),quality);}
}
function projected(id,w,h){const p=plant.getAnchor(id).project(camera);return {id,x:(p.x*.5+.5)*w,y:(-p.y*.5+.5)*h};}
function labelLayout(w,h){
 const points=components().map(c=>projected(c.id,w,h));const high=points.filter(p=>[3,5,6,7,9,13].includes(p.id)).sort((a,b)=>a.x-b.x),low=points.filter(p=>!high.includes(p)).sort((a,b)=>a.x-b.x);
 const output=[];for(const [list,isHigh] of [[high,true],[low,false]])list.forEach((p,i)=>{const margin=w*.045;const lx=margin+(w-margin*2)*(i+.5)/list.length;const ly=isHigh?h*.17:h*.82;output.push({...p,lx,ly,high:isHigh});});return output;
}
function renderAnnotations(){
 if(!overlay)return;if(!state.labels){overlay.replaceChildren();return;}
 const w=viewport.clientWidth,h=viewport.clientHeight,ns='http://www.w3.org/2000/svg';let svg=overlay.querySelector('svg');if(!svg){svg=document.createElementNS(ns,'svg');overlay.replaceChildren(svg);}svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.innerHTML='';
 labelLayout(w,h).forEach(p=>{const line=document.createElementNS(ns,'path');line.setAttribute('d',`M${p.x},${p.y} L${p.x},${p.ly+(p.high?22:-22)} L${p.lx},${p.ly}`);line.setAttribute('fill','none');line.setAttribute('stroke','#7e9188');line.setAttribute('stroke-width','1');svg.append(line);const circle=document.createElementNS(ns,'circle');circle.setAttribute('cx',p.lx);circle.setAttribute('cy',p.ly);circle.setAttribute('r','15');circle.setAttribute('fill','#fff');circle.setAttribute('stroke','#244d40');svg.append(circle);const text=document.createElementNS(ns,'text');text.setAttribute('x',p.lx);text.setAttribute('y',p.ly+5);text.setAttribute('text-anchor','middle');text.setAttribute('font-size','13');text.setAttribute('fill','#123e35');text.textContent=p.id;svg.append(text);circle.style.pointerEvents='all';circle.style.cursor='pointer';circle.onclick=()=>select(p.id);});
}
function wrap(ctx,text,x,y,width,lineHeight,maxLines=9){const words=text.split(' ');let line='',n=0;for(const word of words){const next=line?line+' '+word:word;if(ctx.measureText(next).width>width&&line){ctx.fillText(line,x,y+n*lineHeight);line=word;n++;if(n>=maxLines)return y+n*lineHeight;}else line=next;}ctx.fillText(line,x,y+n*lineHeight);return y+(n+1)*lineHeight;}
async function renderExport(background='white'){
 if(!renderer)throw new Error('WebGL غير متاح للتصدير');exporting=true;ui.setLoading(true);await new Promise(r=>requestAnimationFrame(r));
 const W=spec.rendering.exportWidth,H=spec.rendering.exportHeight,ratio=renderer.getPixelRatio(),oldSize=renderer.getSize(new THREE.Vector2()),aspect=camera.aspect,oldPosition=camera.position.clone(),bg=scene.background,gtaoWas=gtao.enabled,blendWas=blendPass.enabled,envVisible=environment.group.visible,selected=state.selected;
 try{
  const output=document.createElement('canvas');output.width=W;output.height=H;const ctx=output.getContext('2d');
  const withTable=state.labels,tableWidth=withTable?W*.29:0,sceneW=W-tableWidth;
  setResolution(1);renderer.setSize(sceneW,H,false);camera.aspect=sceneW/H;if(withTable)camera.position.copy(controls.target).add(oldPosition.clone().sub(controls.target).multiplyScalar(Math.max(1,aspect/camera.aspect)*1.1));camera.updateProjectionMatrix();composer.setSize(sceneW,H);gtao.setSize(Math.round(sceneW/2),Math.round(H/2));bloomComposer.setSize(Math.round(sceneW/2),Math.round(H/2));
  gtao.enabled=background!=='transparent';blendPass.enabled=true;sun.shadow.mapSize.set(spec.rendering.desktopShadow,spec.rendering.desktopShadow);sun.shadow.map?.dispose();sun.shadow.map=null;
  if(background==='transparent'){scene.background=null;environment.group.visible=false;gtao.enabled=false;}else scene.background=new THREE.Color('#f1f2ed');
  renderer.shadowMap.needsUpdate=true;plant.select(null);plant.root.scale.setScalar(1);plant.update(clockTime,1,true);renderer.setClearAlpha(background==='transparent'?0:1);render();
  if(background!=='transparent'){ctx.fillStyle='#f1f2ed';ctx.fillRect(0,0,W,H);}ctx.drawImage(renderer.domElement,0,0,sceneW,H);
  ctx.direction='rtl';ctx.textAlign='right';ctx.fillStyle='#123e35';ctx.font='600 65px Arial';ctx.fillText('مورد | MAWRID',sceneW-90,110);ctx.font='28px Arial';ctx.fillStyle='#65776e';ctx.fillText(`${spec.key}  /  ${spec.capacity} م³ يوميًا  /  ${state.cutaway?'مقطع داخلي':state.environment==='site'?'تصور الموقع':'تصور هندسي'}`,sceneW-90,160);
  if(withTable){
   for(const p of labelLayout(sceneW,H)){ctx.strokeStyle='#66857a';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(p.x,p.ly+(p.high?40:-40));ctx.lineTo(p.lx,p.ly);ctx.stroke();ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(p.lx,p.ly,26,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#214c40';ctx.stroke();ctx.fillStyle='#123e35';ctx.font='26px Arial';ctx.textAlign='center';ctx.fillText(String(p.id),p.lx,p.ly+9);}
   ctx.fillStyle='#ffffff';ctx.fillRect(sceneW,0,tableWidth,H);ctx.fillStyle='#123e35';ctx.textAlign='right';ctx.font='600 40px Arial';ctx.fillText('دليل المكونات',W-65,100);ctx.font='23px Arial';ctx.fillStyle='#64766d';ctx.fillText('الرقم · الرمز · الوظيفة · المقاس',W-65,145);
   let y=210;for(const c of components()){
    ctx.fillStyle=c.id%2?'#f3f5f0':'#fff';ctx.fillRect(sceneW+28,y-40,tableWidth-56,88);ctx.fillStyle='#123e35';ctx.font='600 25px Arial';ctx.fillText(`${c.id.toString().padStart(2,'0')}  ${c.name}`,W-65,y-7);ctx.font='19px Arial';ctx.fillStyle='#65766c';ctx.fillText(c.code+'  ·  '+c.function,W-65,y+23,tableWidth-100);ctx.textAlign='left';ctx.direction='rtl';ctx.font='18px Arial';ctx.fillText(c.size,sceneW+50,y+47,tableWidth-90);ctx.textAlign='right';y+=91;
   }
   y+=25;ctx.font='600 29px Arial';ctx.fillStyle='#123e35';ctx.fillText('القيود الموثقة',W-65,y);y+=42;ctx.font='21px Arial';ctx.fillStyle='#556b5e';for(const note of unitSpec.constraints){y=wrap(ctx,'• '+note,W-65,y,tableWidth-110,31,3)+9;}
  }
  // Mandatory disclosure is burnt into every export, including transparent PNG.
  ctx.direction='rtl';ctx.textAlign='right';ctx.font='28px Arial';const watermark=unitSpec.disclaimer;const ww=ctx.measureText(watermark).width+60;ctx.fillStyle='rgba(255,255,255,.94)';ctx.fillRect(sceneW-ww-55,H-110,ww,63);ctx.fillStyle='#274c3f';ctx.fillText(watermark,sceneW-85,H-69);
  ctx.font='22px Arial';ctx.fillStyle='#687a70';ctx.textAlign='left';ctx.direction='ltr';ctx.fillText(`1 unit = 1 m  •  Engineering concept  •  ${spec.key}`,65,H-65);
  return output;
 }finally{camera.position.copy(oldPosition);camera.aspect=aspect;camera.updateProjectionMatrix();renderer.setSize(oldSize.x,oldSize.y);composer.setSize(oldSize.x,oldSize.y);setResolution(ratio);gtao.setSize(Math.round(oldSize.x*ratio/2),Math.round(oldSize.y*ratio/2));bloomComposer.setSize(Math.round(oldSize.x/2),Math.round(oldSize.y/2));scene.background=bg;environment.group.visible=envVisible;gtao.enabled=gtaoWas;blendPass.enabled=blendWas;plant.select(selected);renderer.setClearAlpha(1);sun.shadow.mapSize.set(quality==='mobile'?spec.rendering.mobileShadow:spec.rendering.desktopShadow,quality==='mobile'?spec.rendering.mobileShadow:spec.rendering.desktopShadow);sun.shadow.map?.dispose();sun.shadow.map=null;renderer.shadowMap.needsUpdate=true;dirtyFrames=3;exporting=false;ui.setLoading(false);}
}
async function exportPNG(background='white'){try{setStatus('جارٍ تصدير لقطة 4K…');const out=await renderExport(background);out.toBlob(blob=>{download(blob,`MAWRID-${state.preset}-${state.environment}${state.cutaway?'-section':''}${state.labels?'-numbered':''}.png`);setStatus('تم تصدير PNG بدقة 3840 × 2160 مع الوسم الهندسي');},'image/png');}catch(e){setStatus('تعذر التصدير: '+e.message);console.error(e);}}
initialize();
