import '../../mawrid-final/node_modules/@fontsource/ibm-plex-sans-arabic/400.css';
import '../../mawrid-final/node_modules/@fontsource/ibm-plex-sans-arabic/500.css';
import '../../mawrid-final/node_modules/@fontsource/ibm-plex-sans-arabic/600.css';
import './style.css';
import * as THREE from '../../mawrid-final/node_modules/three/build/three.module.js';
import { OrbitControls } from '../../mawrid-final/node_modules/three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from '../../mawrid-final/node_modules/three/examples/jsm/environments/RoomEnvironment.js';
import { createVirtualScene } from './scene.js';
import { StatePoller } from './poller.js';
import { presentation,STATES,FAULTS,EQUIPMENT,SENSOR_LABELS } from './adapter.js';
import { layoutLabels,overviewDistance } from './labels.js';
import { guideContent } from '../client/guide-content.js';
import {isJourneyStage,journeyStage} from './journey.js';
import {journeyFrame,interpolateFrame} from './camera.js';

const $=id=>document.getElementById(id);
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=(value,digits=1)=>typeof value==='number'&&Number.isFinite(value)?new Intl.NumberFormat('en-US',{maximumFractionDigits:digits}).format(value):'—';
const field=(title,value,unit='')=>`<div><dt>${escape(title)}</dt><dd><bdi>${escape(value)}</bdi>${unit?' <small>'+escape(unit)+'</small>':''}</dd></div>`;
const stateName=value=>({running:'يعمل',stopped:'متوقف',open:'مفتوح',closed:'مغلق',unavailable:'غير متاح'})[value]||'غير متاح';
const clock=value=>typeof value==='string'?value.replace('T',' ').replace(/\.\d+(?=Z|[+-]|$)/,'').replace('Z',' UTC'):'—';
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
let reduced=motionPreference.matches;
const embedded=new URLSearchParams(location.search).get('embed')==='1';
document.body.classList.toggle('embedded',embedded);
const simple=embedded&&new URLSearchParams(location.search).get('simple')==='1';
document.body.classList.toggle('simple',simple);
let selected='raw',activeJourney=null,transport={connection:'connecting',snapshot:null,lastSuccessAt:null},lastPhase=null;
let renderer,scene,camera,controls,model,environmentMap,disposed=false,frameHandle,previousTime=0,animationTime=0,lastRender=0,webglAvailable=false;
let cameraMode='overview',cameraStage=null,cameraTransition=null,cameraRequestId=null,focusInterrupted=false;
const viewport=$('viewport'),labels=$('labels'),labelNodes=new Map(),leaderNodes=new Map();
document.body.dataset.cameraMode=cameraMode;document.body.dataset.cameraStage='';document.body.dataset.cameraTransition='settled';
function setText(id,value){const el=$(id);if(el.textContent!==String(value))el.textContent=value;}

function details(s) {
  const [tag,title]=EQUIPMENT[selected];setText('equipment-tag',tag);setText('equipment-title',title);
  let rows='',note='الحالة من لقطة الخادم؛ لا أوامر تشغيل من هذا العرض.';
  if(selected==='raw'||selected==='treated') {
    const t=s?.tanks[selected];rows=field('المستوى',number(t?.percent,1),'%')+field('الحجم الحالي',number(t?.liters,1),'L')+field('سعة الخزان',number(t?.capacity,0),'L');
    if(selected==='treated') rows+=field('الناتج الداخل',number(s?.flows.product,2),'L/min')+field('الخارج إلى الري',number(s?.flows.reuse,2),'L/min');
  } else if(['media','carbon','cartridge'].includes(selected)) {
    rows=field('تدفق المعالجة',number(s?.flows.treatment,2),'L/min')+field('فرق الضغط',number(selected==='media'?s?.deltaMedia:selected==='carbon'?s?.deltaCarbon:s?.deltaCartridge,2),'bar');
    if(selected==='media')rows+=field('الغسيل العكسي',number(s?.flows.backwash,2),'L/min');
  } else if(selected==='valve') {
    rows=field('موضع الصمام الفعلي الافتراضي',stateName(s?.irrigationFeedback))+field('طلب المتحكم الافتراضي',stateName(s?.irrigationCommand))+field('تدفق الري',number(s?.flows.reuse,2),'L/min');
    note='الطلب منفصل عن تأكيد الموضع؛ الطلب بالفتح لا يغيّر رسم صمام مؤكد الإغلاق.';
  } else if(selected==='drain') {
    rows=field('رفض المعالجة',number(s?.flows.drain,2),'L/min')+field('صرف الغسيل',number(s?.flows.backwash,2),'L/min')+field('الفائض المجمّع',number(s?.flows.overflow,2),'L/min')+field('صمام الصرف',stateName(s?.drainValve));
    note='الفائض مجمّع من الخزانين؛ لا تُنسب نسبته إلى خزان بعينه في العرض.';
  } else if(selected==='flow_meter'){
    rows=field('تدفق خط المعالجة',number(s?.flows.treatment,2),'L/min');note='عداد التغذية مستقل عن تدفق الري؛ لا تُعرض قراءة حساس ميداني.';
  } else if(selected==='quality'){
    rows=['turbidity','chlorine','ph'].map(k=>field(SENSOR_LABELS[k][0],number(s?.readings[k],2),SENSOR_LABELS[k][1])).join('');note='لوحة قراءات افتراضية؛ EC والحرارة ليستا قناتين منفذتين هنا.';
  } else if(selected==='compliance'){
    rows=field('المسار الافتراضي',s?.complianceValve==='product'?'إلى المنتج':s?.complianceValve==='closed'?'مغلق':'غير متاح')+field('إعادة إلى الخام',number(s?.flows.recirculation,2),'L/min');note='خط العودة تمثيل تصميمي ثابت؛ الاحتجاز الحالي يوقف التدفقات ولا يحاكي إعادة معالجة.';
  } else if(['dose_pre','dose_dechlor','dose_ph','dose_final','dosing'].includes(selected)){
    rows=field('حالة خط الجرعات',stateName(s?.pumps.dosing));note='تمثيل تصميمي لأربع مراحل جرعات. لا تُحسب كمية مادة أو فعالية معالجة كيميائية.';
  } else if(['uv','pilot','strainer','panel','orp'].includes(selected)){
    const descriptions={uv:'حاجز تعقيم إضافي في التصميم. لا توجد قراءة شدة أشعة أو حساب فعالية UV.',pilot:'عمود بحثي للمقارنة المستقبلية؛ لا تدفق أو نتائج إزالة محاكاة.',strainer:'حجز أولي للشعر والوبر. لا يُحسب تراكم الشوائب.',panel:'تمثيل للوحة التحكم. القواعد تعمل برمجيًا على هذا الجهاز ولا يوجد PLC متصل.',orp:'موضع حساس ORP في التصميم بعد إزالة الكلور. لا توجد قراءة مستقلة لهذا الموضع في المحرك؛ قراءة ORP العامة لا تُنسب إليه.'};
    rows=field('مستوى التمثيل','تفصيل تصميمي');note=descriptions[selected];
  } else {
    const flowKey={feed:'treatment',reuse:'reuse',dosing:'treatment',backwash:'backwash',inlet:'inlet'}[selected];
    rows=field('حالة المضخة',stateName(s?.pumps[selected]))+field(selected==='dosing'?'تدفق الخط':'التدفق',number(s?.flows[flowKey],2),'L/min');
    if(selected==='dosing')note='حالة مضخات الجرعات الافتراضية؛ لا تمثل شدة UV أو جرعة كيميائية محسوبة.';
  }
  const copy=guideContent.components.find(x=>x.id===selected);
  if(simple){$('equipment-details').innerHTML=copy?'<p class="equipment-role">'+escape(copy.role)+'</p><p class="equipment-benefit"><b>الفائدة: </b>'+escape(copy.benefit)+'</p>':'';return;}
  $('equipment-details').innerHTML=(copy?'<p class="equipment-role">'+escape(copy.role)+'</p><p class="equipment-benefit"><b>الفائدة: </b>'+escape(copy.benefit)+'</p>':'')+'<dl class="detail-values">'+rows+'</dl><p class="detail-note">'+escape(note)+'</p>';
}
function choose(id){if(!Object.hasOwn(EQUIPMENT,id))return;selected=id;model?.select(id);details(transport.snapshot);document.body.classList.add('equipment-selected');
  if(embedded&&window.parent!==window)window.parent.postMessage({type:'mawrid:equipment',id},location.origin);
  for(const button of document.querySelectorAll('[data-equipment]'))button.setAttribute('aria-pressed',String(button.dataset.equipment===id));
}
function setJourney(id,cameraRequest,requestId=null){
  if(id!==null&&!isJourneyStage(id))return;
  cameraRequestId=typeof requestId==='string'||typeof requestId==='number'&&Number.isFinite(requestId)?requestId:null;
  if(cameraRequest==='focus'&&id!==null){
    // Resuming the same stage also clears an inspector opened while paused.
    // The equipment identity remains available; only its popup/outline closes.
    document.body.classList.remove('equipment-selected');model?.select(null);
    focusJourneyCamera(id);
  }
  else if(cameraRequest==='overview')returnToOverview();
  if(id===activeJourney)return;
  activeJourney=id;model?.setJourney(id);
  document.body.classList.toggle('journey-active',id!==null);document.body.dataset.journey=id??'';
  const stage=journeyStage(id);
  for(const [equipmentId,node] of labelNodes)node.classList.toggle('journey-label',stage?.labels.includes(equipmentId)??false);
  // Stepping through the explanation never opens an equipment popup or
  // changes the user's selected equipment identity.
  if(simple){document.body.classList.remove('equipment-selected');model?.select(null);}
}
for(const [id,[tag,title]] of Object.entries(EQUIPMENT)){
  const button=document.createElement('button');button.type='button';button.dataset.equipment=id;button.setAttribute('aria-pressed',String(id===selected));
  const code=document.createElement('small');code.textContent=tag;button.append(code,document.createTextNode(title));button.addEventListener('click',()=>choose(id));$('equipment-strip').append(button);
}
function paint() {
  const view=presentation(transport,performance.now()),s=view.snapshot,phase=view.phase;
  document.body.dataset.phase=phase;
  const connection=$('connection');connection.dataset.phase=phase;
  const messages={connecting:'جارٍ الاتصال بالخادم المحلي',live:'متصل · تحديث من الخادم كل ثانيتين',paused:'متصل · ساعة المحاكاة متوقفة',empty:'لا توجد جلسة منشأة افتراضية نشطة',failed:'الجلسة متوقفة بعد خطأ',disconnected:'انقطع التحديث · آخر حالة مستلمة'};
  setText('connection',messages[phase]);setText('metric-feed',number(s?.flows.treatment,2));setText('metric-product',number(s?.flows.product,2));setText('metric-reuse',number(s?.flows.reuse,2));setText('metric-volume',number(s?.volumes.reuse_liters,1));
  setText('process-state',s?(STATES[s.state]||'غير متاح'):'بانتظار الجلسة');$('process-state').dataset.state=s?.state||'';
  setText('simulation-clock',clock(s?.timestamp));setText('clock-speed',s?.speed?'×'+s.speed:'×—');setText('fault-label',s?(FAULTS[s.fault]||'غير متاح'):'—');
  setText('freshness-label',view.fresh?'لقطة مستلمة الآن':transport.lastSuccessAt===null?'لم تصل لقطة':'آخر لقطة؛ دون حركة');
  setText('operation-reason',s?(s.reasons.length?s.reasons.join(' · '):'شروط التشغيل الافتراضية متحققة. تدفقات الخزانات والمعدات من محرك المحاكاة.'):'ابدأ جلسة المنشأة الافتراضية من غرفة التشغيل. فتح هذه الصفحة لا يبدأ جلسة أو يعيد بيانات عامة.');
  $('operation-reason').dataset.state=s?.state||'';
  setText('reading-status',view.fresh&&s?'لقطة المحاكاة':s?'آخر لقطة':'غير متاح');
  $('quality-readings').innerHTML=['turbidity','ph','chlorine','orp'].map(key=>{const [title,unit]=SENSOR_LABELS[key];return `<div class="quality-row"><span>${title}</span><b>${number(s?.readings[key],key==='orp'?0:2)}<small>${unit}</small></b></div>`;}).join('');
  setText('assumptions',s?`تصميم التغذية ${number(s.ratedFeed,0)} م³/يوم عند 15 ساعة تشغيل · دون رفض مستمر مفترض · الغسيل والفائض يحسبان منفصلين`:'تُعرض افتراضات التشغيل عند اتصال المنشأة الافتراضية.');
  setText('session-label',s?'SESSION '+s.sessionId.slice(0,8):'');$('session-label').title=s?.sessionId||'';
  details(s);
  const notice=$('scene-notice');
  if(!webglAvailable){notice.classList.remove('hidden');notice.innerHTML='<span class="notice-icon">◇</span><strong>العرض الثلاثي غير متاح على هذا الجهاز</strong><p>يمكن متابعة الحالة والقراءات، أو فتح غرفة التشغيل.</p>';}
  else if(phase==='connecting'||phase==='empty') {notice.classList.remove('hidden');notice.innerHTML='<span class="notice-icon">◌</span><strong>'+escape(phase==='connecting'?'جارٍ انتظار لقطة الخادم':'ابدأ المنشأة من غرفة التشغيل')+'</strong><p>المشهد جاهز؛ لا توجد قيم أو حركة تشغيل دون جلسة افتراضية.</p>';}
  else if(phase==='disconnected'||phase==='failed'){notice.classList.remove('hidden');notice.innerHTML='<span class="notice-icon">◇</span><strong>'+escape(phase==='failed'?'توقفت الجلسة الافتراضية':'توقف التحديث')+'</strong><p>آخر لقطة معروضة دون حركة. موضع الصمام هو آخر تأكيد مستلم.</p>';}
  else notice.classList.add('hidden');
  for(const [id,node] of labelNodes){const t=s?.tanks[id],flowKey=({reuse:'reuse',backwash:'backwash',drain:'drain',inlet:'inlet'})[id]||'treatment';node.querySelector('em').textContent=t?`${number(t.percent,0)}% · ${number(t.liters,0)} L`:id==='valve'?stateName(s?.irrigationFeedback):['uv','pilot','strainer','panel','orp'].includes(id)?'تفصيل تصميمي':id==='compliance'?'خط الإعادة غير محاكى':id.startsWith('dose_')||id==='dosing'?'حالة جرعات مجمّعة':s?`${number(s.flows[flowKey],1)} L/min`:'—';}
  lastPhase=phase;
}
function postParent(message){if(embedded&&window.parent!==window)window.parent.postMessage(message,location.origin);}
function reportCameraSettled(){document.body.dataset.cameraTransition='settled';postParent({type:'mawrid:camera-settled',id:cameraStage,requestId:cameraRequestId});}
function currentFrame(){return {position:camera.position.toArray(),target:controls.target.toArray()};}
function overviewFrame(){const aspect=viewport.clientWidth/Math.max(1,viewport.clientHeight),target=new THREE.Vector3(0,.8,0),position=target.clone().addScaledVector(new THREE.Vector3(8,10,16).normalize(),overviewDistance(aspect));return {position:position.toArray(),target:target.toArray()};}
function applyFrame(frame){if(!camera||!controls)return;camera.position.fromArray(frame.position);controls.target.fromArray(frame.target);controls.update();}
function settleCamera(){
  const transition=cameraTransition;cameraTransition=null;
  if(transition)applyFrame(transition.to);
  if(controls)controls.enableDamping=!reduced;
  reportCameraSettled();
}
function moveCamera(frame,{snap=false}={}){
  if(!camera||!controls||!webglAvailable){reportCameraSettled();return;}
  // Flush residual orbit damping before a scripted movement. During the
  // transition the exact interpolated frame is the only camera authority.
  controls.enableDamping=false;controls.update();
  controls.minDistance=cameraMode==='focus'?2.4:6;controls.maxDistance=Math.max(55,(frame.distance??0)*1.3);controls.maxTargetRadius=50;
  cameraTransition={from:currentFrame(),to:frame,started:performance.now(),duration:1100};
  document.body.dataset.cameraTransition='moving';
  if(snap||reduced||document.hidden)settleCamera();
}
function focusJourneyCamera(id,{resize=false}={}){
  const repeated=cameraMode==='focus'&&cameraStage===id&&!focusInterrupted;
  focusInterrupted=false;
  cameraMode='focus';cameraStage=id;document.body.dataset.cameraMode=cameraMode;document.body.dataset.cameraStage=id;
  if(repeated&&!resize){if(!cameraTransition)reportCameraSettled();return;}
  const frame=model?journeyFrame(model,id,viewport.clientWidth/Math.max(1,viewport.clientHeight)):null;
  if(frame)moveCamera(frame,{snap:resize});else reportCameraSettled();
}
function returnToOverview({snap=false}={}){
  const repeated=cameraMode==='overview';cameraMode='overview';cameraStage=null;document.body.dataset.cameraMode=cameraMode;document.body.dataset.cameraStage='';
  focusInterrupted=false;
  if(repeated&&!snap){if(!cameraTransition)reportCameraSettled();return;}
  if(camera)moveCamera(overviewFrame(),{snap});else reportCameraSettled();
}
function manualCamera(){
  cameraTransition=null;focusInterrupted=true;document.body.dataset.cameraTransition='settled';
  if(controls)controls.enableDamping=!reduced;
  postParent({type:'mawrid:camera-interaction'});
}
function resetCamera(){
  manualCamera();
  // Keep the last requested stage identity so a repeated paused-parent
  // message cannot undo the user's deliberate overview reset.
  if(camera)applyFrame(overviewFrame());
}
function resize(){if(!renderer)return;const w=Math.max(1,viewport.clientWidth),h=Math.max(1,viewport.clientHeight);renderer.setSize(w,h);const aspect=w/h,previous=camera.aspect;
  camera.aspect=aspect;camera.updateProjectionMatrix();
  if(cameraMode==='focus'&&cameraStage){
    const frame=journeyFrame(model,cameraStage,aspect);
    // Text/layout changes can resize the iframe immediately after a stage
    // request. Retarget the same smooth movement instead of snapping it early.
    if(cameraTransition&&frame){cameraTransition.to=frame;controls.maxDistance=Math.max(55,frame.distance*1.3);}
    else focusJourneyCamera(cameraStage,{resize:true});
  }
  else if(controls&&previous>0&&aspect!==previous){
    if(cameraTransition){cameraTransition.to=overviewFrame();settleCamera();}
    else{const delta=camera.position.clone().sub(controls.target);delta.multiplyScalar(overviewDistance(aspect)/overviewDistance(previous));camera.position.copy(controls.target).add(delta);}
  }
}
function zoom(factor){if(!camera)return;manualCamera();const delta=camera.position.clone().sub(controls.target);delta.setLength(Math.max(controls.minDistance,Math.min(controls.maxDistance,delta.length()*factor)));camera.position.copy(controls.target).add(delta);controls.update();}
function rotate(angle){if(!camera)return;manualCamera();const delta=camera.position.clone().sub(controls.target).applyAxisAngle(new THREE.Vector3(0,1,0),angle);camera.position.copy(controls.target).add(delta);controls.update();}
$('zoom-in').onclick=()=>zoom(.83);$('zoom-out').onclick=()=>zoom(1.2);$('rotate-right').onclick=()=>rotate(-Math.PI/10);$('rotate-left').onclick=()=>rotate(Math.PI/10);$('reset-camera').onclick=resetCamera;
$('show-parts').onclick=()=>{const shown=document.body.classList.toggle('show-parts');$('show-parts').setAttribute('aria-pressed',String(shown));};
$('close-equipment').onclick=()=>document.body.classList.remove('equipment-selected');
window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==window.parent)return;
  if(event.data?.type==='mawrid:focus')choose(event.data.id);
  if(event.data?.type==='mawrid:journey')setJourney(event.data.id,event.data.camera,event.data.requestId);
  // A completed parent command asks for a fresh read, never sends equipment
  // commands or unverified sensor values into the scene.
  if(event.data?.type==='mawrid:refresh'){transport={...transport,connection:'connecting',lastSuccessAt:null};paint();poller.poll();}
});
function initialize(){
  try {
    renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});
    renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.15;
    renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    renderer.domElement.setAttribute('aria-label','مجسم المنشأة الافتراضية؛ اسحب للدوران، أو استخدم أزرار الكاميرا');renderer.domElement.tabIndex=0;
    viewport.prepend(renderer.domElement);
    scene=new THREE.Scene();scene.background=new THREE.Color('#f5f6ee');
    const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();environmentMap=pmrem.fromScene(room,.08);scene.environment=environmentMap.texture;scene.environmentIntensity=.5;room.dispose();pmrem.dispose();
    scene.add(new THREE.HemisphereLight('#fbfff3','#b5bea7',2.3));
    const key=new THREE.DirectionalLight('#fff6de',3.4);key.position.set(-6,13,7);key.castShadow=true;key.shadow.mapSize.set(2048,2048);Object.assign(key.shadow.camera,{left:-11,right:11,top:9,bottom:-8,near:1,far:35});key.shadow.bias=-.0003;key.shadow.normalBias=.025;key.shadow.radius=3;scene.add(key);
    const fill=new THREE.DirectionalLight('#e5f6f0',1);fill.position.set(8,6,-9);scene.add(fill);
    const floor=new THREE.Mesh(new THREE.PlaneGeometry(150,150),new THREE.MeshStandardMaterial({color:'#f5f6ee',roughness:1}));floor.rotation.x=-Math.PI/2;floor.position.y=-.2;floor.receiveShadow=true;scene.add(floor);
    model=createVirtualScene();scene.add(model.root);model.select(selected);
    camera=new THREE.PerspectiveCamera(36,1,.1,180);controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=!reduced;controls.dampingFactor=.08;controls.minDistance=6;controls.maxDistance=55;controls.minPolarAngle=.12;controls.maxPolarAngle=Math.PI*.49;controls.maxTargetRadius=6;
    webglAvailable=true;resize();returnToOverview({snap:true});new ResizeObserver(()=>{resize();}).observe(viewport);
    controls.addEventListener('start',manualCamera);
    for(const item of model.labels){if(!Object.hasOwn(EQUIPMENT,item.id))continue;const [tag,title]=EQUIPMENT[item.id],node=document.createElement('button');node.type='button';node.className='scene-label'+(item.primary?'':' secondary');node.dataset.equipment=item.id;node.setAttribute('aria-pressed',String(item.id===selected));node.innerHTML=`<small>${tag}</small><b>${title}</b><em>—</em>`;node.onclick=()=>choose(item.id);labels.append(node);labelNodes.set(item.id,node);const leader=document.createElement('span');leader.className='label-leader';leader.setAttribute('aria-hidden','true');labels.prepend(leader);leaderNodes.set(item.id,leader);}
    let down=null;renderer.domElement.addEventListener('pointerdown',event=>{down=[event.clientX,event.clientY];});renderer.domElement.addEventListener('pointerup',event=>{if(!down||Math.hypot(event.clientX-down[0],event.clientY-down[1])>5)return;const rect=renderer.domElement.getBoundingClientRect(),ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);const hit=ray.intersectObject(model.root,true).find(h=>Object.hasOwn(EQUIPMENT,h.object.userData.equipment));if(hit)choose(hit.object.userData.equipment);});
    renderer.domElement.addEventListener('keydown',event=>{const actions={ArrowLeft:()=>rotate(Math.PI/10),ArrowRight:()=>rotate(-Math.PI/10),'+':()=>zoom(.85),'=':()=>zoom(.85),'-':()=>zoom(1.18),Home:resetCamera};if(actions[event.key]){event.preventDefault();actions[event.key]();}});
    renderer.domElement.addEventListener('webglcontextlost',event=>{event.preventDefault();webglAvailable=false;cameraTransition=null;reportCameraSettled();renderer.domElement.hidden=true;labels.hidden=true;paint();});
    webglAvailable=true;frameHandle=requestAnimationFrame(animate);
  } catch(error){webglAvailable=false;renderer?.dispose();renderer=null;labels.hidden=true;}
}
function animate(now){
  if(disposed)return;frameHandle=requestAnimationFrame(animate);
  if(!renderer||!webglAvailable||document.hidden){previousTime=now;return;}
  if(now-lastRender<32)return;lastRender=now;
  const view=presentation(transport,now);if(view.phase!==lastPhase)paint();
  const dt=Math.min(.1,Math.max(0,(now-previousTime)/1000));previousTime=now;
  // Cosmetic arrow phase only. No measured or cumulative quantity is computed.
  if(view.motion&&!reduced)animationTime+=dt;
  model.update(animationTime,view.motion,view.motion&&!reduced?dt:0);
  if(cameraTransition){const progress=(now-cameraTransition.started)/cameraTransition.duration;applyFrame(interpolateFrame(cameraTransition.from,cameraTransition.to,progress,{reducedMotion:reduced}));if(progress>=1||reduced)settleCamera();}
  else controls.update();
  renderer.render(scene,camera);
  const annotations=[];
  for(const item of model.labels){const node=labelNodes.get(item.id);if(!node)continue;const point=item.position.clone().project(camera);node.hidden=point.z>1||point.z< -1||Math.abs(point.x)>1.1||Math.abs(point.y)>1.1;leaderNodes.get(item.id).hidden=true;
    if(!node.hidden&&node.offsetWidth>0&&node.offsetHeight>0)annotations.push({id:item.id,x:(point.x*.5+.5)*viewport.clientWidth,y:(-point.y*.5+.5)*viewport.clientHeight,width:node.offsetWidth,height:node.offsetHeight});}
  for(const box of layoutLabels(annotations,viewport.clientWidth,viewport.clientHeight)){const node=labelNodes.get(box.id),leader=leaderNodes.get(box.id);node.style.left=box.left+'px';node.style.top=box.top+'px';const dx=box.anchor.x-box.leader.x,dy=box.anchor.y-box.leader.y,length=Math.hypot(dx,dy);leader.hidden=length<3;leader.style.left=box.leader.x+'px';leader.style.top=box.leader.y+'px';leader.style.width=length+'px';leader.style.transform=`rotate(${Math.atan2(dy,dx)}rad)`;}
}
initialize();paint();
document.addEventListener('visibilitychange',()=>{if(document.hidden&&cameraTransition)settleCamera();});
motionPreference.addEventListener('change',event=>{reduced=event.matches;if(controls)controls.enableDamping=!reduced&&!cameraTransition;if(reduced&&cameraTransition)settleCamera();});
const poller=new StatePoller({onState(state){transport=state;if(state.reset){model?.apply(null);animationTime=0;}model?.apply(state.snapshot);paint();}});
poller.start();
if(embedded&&window.parent!==window)window.parent.postMessage({type:'mawrid:scene-ready'},location.origin);
window.addEventListener('pagehide',()=>{disposed=true;poller.stop();cancelAnimationFrame(frameHandle);controls?.dispose();model?.dispose();environmentMap?.dispose();renderer?.dispose();},{once:true});
// A bounded, read-only QA surface; no mutation, source selection or ML hooks.
window.MAWRID_PLANT3D={get status(){const v=presentation(transport,performance.now());return {phase:v.phase,motion:v.motion,sessionId:v.snapshot?.sessionId??null,webglAvailable,selected,journeyStage:activeJourney};},diagnostics(){return {sceneEquipment:model?.equipment.size??0,flowPaths:model?.pipes.map(p=>({name:p.name,key:p.key,visible:p.dots.visible}))??[],journeyStage:activeJourney,highlightedEquipment:model?.highlightedEquipment??[],highlightedPipes:model?.highlightedPipes??[],journeyMotion:model?.journeyMotion??[],drawCalls:renderer?.info.render.calls??null,hardwareConnected:false,mlControlsPlant:false};}};
