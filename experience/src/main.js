import './style.css';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {createVirtualScene} from '../../mawrid-system/plant3d/scene.js';
import {journeyFrame, interpolateFrame} from '../../mawrid-system/plant3d/camera.js';
import {overviewDistance} from '../../mawrid-system/plant3d/labels.js';
import {EQUIPMENT, FAULTS} from '../../mawrid-system/plant3d/adapter.js';
import {BrowserPlant, sceneSnapshot} from './model.js';
const $ = id => document.getElementById(id), reduced = matchMedia('(prefers-reduced-motion: reduce)');
const textIfChanged = (id,value) => {const el = $(id); if (el.textContent !== value) el.textContent = value;};
const fmt = (v, digits = 2) => typeof v === 'number' && Number.isFinite(v) ? new Intl.NumberFormat('en-US', {maximumFractionDigits: digits, minimumFractionDigits: digits}).format(v) : 'غير متاح';
const stages = [
  ['collection','التجميع','يجمع خزان الخام مياه الوضوء في التصميم؛ المصفاة والمضخة يوضحان بداية المسار.'],
  ['media','الوسائط','مرشح الوسائط جزء من التصميم. المحاكاة لا تحسب نسبة إزالة عكارة أو ملوثات.'],
  ['carbon','الكربون','مرشح الكربون وموضع ORP تفاصيل تصميمية؛ لا محاكاة لامتزاز أو عمر المادة.'],
  ['polish','الترشيح الدقيق','ترشيح دقيق ومراحل جرعات ممثلة بصريًا؛ لا جرعات كيميائية محسوبة.'],
  ['verify','التحقق','القيم الافتراضية تقارن بقواعد تجريبية ثابتة. فقد القراءة أو تجاوزها يغلق الري الافتراضي.'],
  ['uv','UV اختياري','حاجز إضافي اختياري في التصميم؛ لا شدة أشعة أو فعالية تعقيم محسوبة.'],
  ['storage','التخزين','خزان المنتج بسعة تصميمية 5 م³؛ الحجم المعروض جزء من ميزان ماء افتراضي.'],
  ['irrigation','الري','طلب المتحكم منفصل عن تأكيد موضع الصمام. تعطل الصمام يوقف المضخات افتراضيًا.'],
];
let plant = new BrowserPlant(), running = false, events = [], activeStage = null, tourTimer = null, lastSample = 0;
plant.control({speed:10});
let renderer, scene, camera, controls, model, environmentMap, transition = null, webglAvailable = false, animationTime = 0, frameHandle, previousFrame = 0;
const viewport = $('viewport');
function log(action) {const s = plant.snapshot(); events.push({simulation_seconds: s.elapsed_seconds, page_elapsed_seconds: Math.round(performance.now()) / 1000, simulation_running: running, action, source: s.source, state: s.safety.state, fault: s.fault, irrigation_command: s.equipment.irrigation_command, irrigation_feedback: s.equipment.irrigation_feedback, policy_reuse_lpm: s.flow.reuse_lpm, effective_reuse_lpm: running ? s.flow.reuse_lpm : 0, reasons: s.safety.reason_codes}); if (events.length > 250) events.shift(); renderEvents();}
function renderEvents() {$('event-count').textContent = events.length; $('event-log').replaceChildren(...events.slice(-12).reverse().map(e => {const li = document.createElement('li'); const clock = document.createElement('bdi'); clock.textContent = elapsedLabel(e.simulation_seconds); li.append(clock, document.createTextNode(' · ' + e.action)); return li;}));}
function elapsedLabel(seconds) {const s = Math.floor(seconds); return `${String(Math.floor(s / 60)).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;}
function paint() {
  const s = plant.snapshot(), hold = s.safety.state === 'HOLD'; model?.apply(sceneSnapshot(s));
  document.body.dataset.state = s.safety.state; document.body.dataset.running = String(running);
  $('run').textContent = running ? 'إيقاف مؤقت' : 'تشغيل المحاكاة'; $('run').setAttribute('aria-pressed', String(running));
  $('simulation-status').textContent = running ? `تعمل · سرعة ×${s.speed}` : 'المحاكاة متوقفة';
  $('decision').dataset.state = s.safety.state;
  textIfChanged('decision-title',({REUSE:running?'يسمح بالري الافتراضي':'القواعد تسمح عند التشغيل',HOLD:'الري محجوز افتراضيًا',STANDBY:'وضع الاستعداد',BACKWASH:'غسيل عكسي افتراضي'})[s.safety.state]);
  textIfChanged('valve-state',s.equipment.irrigation_feedback === 'open' ? 'موضع الصمام: مفتوح' : 'موضع الصمام: مغلق');
  textIfChanged('decision-reason',(!running ? 'الساعة متوقفة؛ لا تدفق جارٍ في المحاكاة. ' : '') + (s.safety.reasons.join(' ') || 'القيم ضمن الحدود التجريبية. لا يعني هذا إثبات صلاحية الماء.'));
  for (const k of ['turbidity','ph','chlorine','orp']) $(k).textContent = fmt(s.chans[k], k === 'orp' ? 0 : 2);
  for (const k of ['raw','treated']) {$(`${k}-volume`).textContent = `${fmt(s.tanks[k].liters,0)} / 5,000 L`; $(`${k}-level`).value = s.tanks[k].liters;}
  $('reuse-flow').replaceChildren(document.createTextNode(fmt(running ? s.flow.reuse_lpm : 0) + ' '), Object.assign(document.createElement('small'), {textContent:'L/min'}));
  $('reuse-volume').replaceChildren(document.createTextNode(fmt(s.volumes.reuse_liters,1) + ' '), Object.assign(document.createElement('small'), {textContent:'L'}));
  $('elapsed').textContent = elapsedLabel(s.elapsed_seconds); $('clock-note').textContent = running ? hold ? 'الساعة تعمل والتدفق متوقف' : 'وقت افتراضي مسرّع' : 'الساعة والتدفقات متوقفة';
  for (const button of document.querySelectorAll('[data-fault]')) button.setAttribute('aria-pressed', String(button.dataset.fault === plant.fault));
}
function setRunning(next, action) {running = next; if (!next) stopTour(); log(action || (next ? 'بدء التشغيل الافتراضي' : 'إيقاف ساعة المحاكاة')); paint();}
$('run').onclick = () => setRunning(!running);
$('reset').onclick = () => {running = false; stopTour(); plant = new BrowserPlant(); plant.control({speed:Number($('speed').value)}); events = []; lastSample = 0; setStage(null); log('إعادة بدء محاكاة المتصفح'); paint();};
$('speed').onchange = event => {plant.control({speed:Number(event.target.value)}); log('تغيير السرعة ×' + plant.speed); paint();};
for (const [fault, label] of Object.entries(FAULTS)) {const button = document.createElement('button'); button.type = 'button'; button.dataset.fault = fault; button.textContent = fault === 'none' ? 'تشغيل طبيعي' : label; button.setAttribute('aria-pressed', String(fault === 'none')); button.onclick = () => {plant.control({fault}); log('اختيار السيناريو: ' + button.textContent); paint();}; $('fault-buttons').append(button);}
function overviewFrame() {const target = new THREE.Vector3(.8,.7,0), direction = new THREE.Vector3(8,10,16).normalize(), aspect = viewport.clientWidth / Math.max(1,viewport.clientHeight), distance = overviewDistance(aspect) * (aspect >= 1.25 ? .8 : 1); return {target:target.toArray(), position:target.clone().addScaledVector(direction,distance).toArray()};}
function applyFrame(frame) {camera.position.fromArray(frame.position); controls.target.fromArray(frame.target); controls.update();}
function moveCamera(to) {if (!camera) return; controls.enableDamping = false; controls.update(); transition = {from:{position:camera.position.toArray(),target:controls.target.toArray()},to,start:performance.now()}; if (reduced.matches) {applyFrame(to); transition = null;}}
function setStage(id) {activeStage = id; model?.setJourney(id); model?.select(null); $('equipment-label').hidden = true; const stage = stages.find(s => s[0] === id); $('journey-title').textContent = stage ? stage[1] : 'رحلة الماء'; $('journey-description').textContent = stage ? stage[2] : 'اختر مرحلة لتقترب منها الكاميرا. التظليل شرح للمسار، وليس حسابًا لزمن المعالجة.'; for (const button of document.querySelectorAll('[data-stage]')) button.setAttribute('aria-pressed',String(button.dataset.stage === id)); if (camera) {controls.minDistance = id ? 2.4 : 6; controls.maxDistance = 65; moveCamera(id ? journeyFrame(model,id,camera.aspect) : overviewFrame());}}
function stopTour() {clearInterval(tourTimer); tourTimer = null; $('tour').textContent = 'بدء الجولة'; $('tour').setAttribute('aria-pressed','false');}
for (const [id, label] of stages) {const button = document.createElement('button'); button.type = 'button'; button.dataset.stage = id; button.textContent = label; button.setAttribute('aria-pressed','false'); button.onclick = () => {stopTour(); setStage(id);}; $('journey-buttons').append(button);}
$('tour').onclick = () => {if (tourTimer) {stopTour(); return;} if (!running) setRunning(true); let index = 0; setStage(stages[0][0]); $('tour').textContent = 'إيقاف الجولة'; $('tour').setAttribute('aria-pressed','true'); tourTimer = setInterval(() => {index++; if (index === stages.length) {stopTour(); setStage(null);} else setStage(stages[index][0]);},5200);};
$('overview').onclick = () => {stopTour(); setStage(null);};
function zoom(factor) {if (!camera) return; transition = null; const delta = camera.position.clone().sub(controls.target); delta.setLength(Math.max(controls.minDistance, Math.min(controls.maxDistance,delta.length() * factor))); camera.position.copy(controls.target).add(delta); controls.update();}
$('zoom-in').onclick = () => zoom(.82); $('zoom-out').onclick = () => zoom(1.22);
$('export').onclick = () => {const snapshot = plant.snapshot(); const data = {source:'browser_simulation',hardware_connected:false,ml_used:false,persistent_server:false,simulation_running:running,clock_paused:!running,rate_basis:'snapshot.flow and equipment describe the instantaneous virtual rule, including latent rates when paused. effective_flow_lpm is zero while the clock is paused.',effective_flow_lpm:Object.fromEntries(Object.entries(snapshot.flow).map(([k,v]) => [k,running ? v : 0])),description:'Illustrative browser simulation; no measured water quality or treatment efficacy.',snapshot,events}; const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})), a = document.createElement('a'); a.href = url; a.download = 'mawrid-browser-simulation.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);};
function resize() {if (!renderer) return; const w = Math.max(1,viewport.clientWidth), h = Math.max(1,viewport.clientHeight); renderer.setSize(w,h); camera.aspect = w / h; camera.updateProjectionMatrix(); if (activeStage) moveCamera(journeyFrame(model,activeStage,camera.aspect)); else applyFrame(overviewFrame());}
function initialize() {
  try {
    renderer = new THREE.WebGLRenderer({antialias:true,powerPreference:'low-power'}); renderer.setPixelRatio(Math.min(devicePixelRatio,1.5)); renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.15; renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.setAttribute('aria-label','مجسم المحطة الافتراضية. اسحب للدوران أو استخدم أزرار المراحل والتقريب.'); renderer.domElement.tabIndex = 0; viewport.prepend(renderer.domElement);
    scene = new THREE.Scene(); scene.background = new THREE.Color('#f5f6ee'); const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment(); environmentMap = pmrem.fromScene(room,.08); scene.environment = environmentMap.texture; scene.environmentIntensity = .5; room.dispose(); pmrem.dispose();
    scene.add(new THREE.HemisphereLight('#fbfff3','#b5bea7',2.3)); const key = new THREE.DirectionalLight('#fff6de',3.4); key.position.set(-6,13,7); key.castShadow = true; key.shadow.mapSize.set(1024,1024); Object.assign(key.shadow.camera,{left:-11,right:11,top:9,bottom:-8,near:1,far:35}); key.shadow.bias = -.0003; key.shadow.normalBias = .025; scene.add(key); const fill = new THREE.DirectionalLight('#e5f6f0',1); fill.position.set(8,6,-9); scene.add(fill);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(150,150),new THREE.MeshStandardMaterial({color:'#f5f6ee',roughness:1})); floor.rotation.x = -Math.PI/2; floor.position.y = -.2; floor.receiveShadow = true; scene.add(floor);
    model = createVirtualScene(); scene.add(model.root); camera = new THREE.PerspectiveCamera(36,1,.1,180); controls = new OrbitControls(camera,renderer.domElement); controls.enableDamping = !reduced.matches; controls.dampingFactor = .08; controls.minDistance = 6; controls.maxDistance = 65; controls.minPolarAngle = .12; controls.maxPolarAngle = Math.PI * .49; controls.maxTargetRadius = 8; controls.addEventListener('start', () => {transition = null; stopTour();});
    renderer.domElement.addEventListener('keydown', event => {if (['+','=','-','Home','ArrowLeft','ArrowRight'].includes(event.key)) {event.preventDefault(); transition = null; if (event.key === 'Home') setStage(null); else if (event.key === '-' || event.key === '+' || event.key === '=') zoom(event.key === '-' ? 1.2 : .83); else {const delta = camera.position.clone().sub(controls.target).applyAxisAngle(new THREE.Vector3(0,1,0),event.key === 'ArrowLeft' ? .22 : -.22); camera.position.copy(controls.target).add(delta); controls.update();}}});
    let pointer = null; renderer.domElement.addEventListener('pointerdown', event => {pointer = [event.clientX,event.clientY];}); renderer.domElement.addEventListener('pointerup', event => {if (!pointer || Math.hypot(event.clientX-pointer[0],event.clientY-pointer[1]) > 5) return; const rect = renderer.domElement.getBoundingClientRect(), ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera); const hit = ray.intersectObject(model.root,true).find(h => EQUIPMENT[h.object.userData.equipment]); if (hit) {const id = hit.object.userData.equipment; model.select(id); $('equipment-label').textContent = EQUIPMENT[id].join(' · '); $('equipment-label').hidden = false;}});
    renderer.domElement.addEventListener('webglcontextlost', event => {event.preventDefault(); webglAvailable = false; renderer.domElement.hidden = true; $('scene-fallback').hidden = false;});
    webglAvailable = true; resize(); new ResizeObserver(resize).observe(viewport); frameHandle = requestAnimationFrame(animate);
  } catch (error) {renderer?.dispose(); renderer = null; $('scene-fallback').hidden = false;}
  $('scene-loading').hidden = true;
}
function animate(now) {frameHandle = requestAnimationFrame(animate); if (!webglAvailable || document.hidden) {previousFrame = now; return;} const dt = Math.min(.1,Math.max(0,(now-previousFrame)/1000)); previousFrame = now; if (running && !reduced.matches) animationTime += dt; model.update(animationTime,running && !reduced.matches,running && !reduced.matches ? dt : 0); if (transition) {const progress = (now-transition.start)/1000; applyFrame(interpolateFrame(transition.from,transition.to,progress,{reducedMotion:reduced.matches})); if (progress >= 1 || reduced.matches) {transition = null; controls.enableDamping = !reduced.matches;}} else controls.update(); renderer.render(scene,camera);}
let lastTick = performance.now(); const timer = setInterval(() => {const now = performance.now(), dt = Math.min(.5,Math.max(0,(now-lastTick)/1000)); lastTick = now; if (running && !document.hidden) {plant.step(dt * plant.speed); if (plant.elapsed-lastSample >= 30) {lastSample = plant.elapsed; log('عينة دورية: ' + (plant.snapshot().safety.state === 'REUSE' ? 'ري افتراضي' : 'احتجاز افتراضي'));} paint();}},250);
document.addEventListener('visibilitychange', () => {lastTick = performance.now(); if (document.hidden && running) setRunning(false,'إيقاف تلقائي عند مغادرة الصفحة');});
window.addEventListener('pagehide', event => {if (event.persisted) {if (running) setRunning(false,'إيقاف عند مغادرة الصفحة'); return;} clearInterval(timer); stopTour(); cancelAnimationFrame(frameHandle); controls?.dispose(); model?.dispose(); environmentMap?.dispose(); renderer?.dispose();});
window.addEventListener('pageshow', event => {if (event.persisted) {lastTick = performance.now(); previousFrame = lastTick; paint();}});
initialize(); log('تهيئة محاكاة المتصفح'); paint();
// Read-only inspection surface: no injected readings, backend or actuation.
window.MAWRID_BROWSER_DEMO = {get status() {return {source:'browser_simulation',hardwareConnected:false,mlUsed:false,webglAvailable,running,stage:activeStage,...plant.snapshot()};},diagnostics() {return {drawCalls:renderer?.info.render.calls ?? 0, equipmentCount:model?.equipment.size ?? 0, animatedPipes:model?.pipes.filter(p => p.dots.visible).map(p => p.name) ?? [], events:events.length};}};
