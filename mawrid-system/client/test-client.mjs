/* Synthetic, dependency-free checks. No server, source files or live DB access. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

// Import the real ES modules, including the guide's relative dependencies.
// The VM below provides only an event/queue harness, not a browser renderer.
const moduleURLs = new Map();
async function moduleURL(name, parent = import.meta.url) {
  const file = new URL(name, parent).href;
  if (moduleURLs.has(file)) return moduleURLs.get(file);
  let source = await fs.readFile(new URL(file), 'utf8');
  for (const match of [...source.matchAll(/from\s+(['"])(\.[^'"]+)\1/g)]) {
    source = source.replace(match[0], `from '${await moduleURL(match[2], file)}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
  moduleURLs.set(file, url); return url;
}
const loadModule = async name => import(await moduleURL(name));
const { sensorChart } = await loadModule('./charts.js');
const { plantView, plantPage, updatePlant, EQUIPMENT, PLANT_MODES, PLANT_FAULTS } = await loadModule('./plant.js');
const { GUIDE_PAGES, renderGuide, updateTour, updateComponent } = await loadModule('./guide.js');
const { experienceState } = await loadModule('./experience-state.js');
const { journeyProgress, WATER_JOURNEY } = await loadModule('./water-journey.js');
const { JourneyPresentation, readingDuration } = await loadModule('./presentation.js');
let tests = 0;
const channel = { key: 'x', name: '<unsafe sensor>', unit: 'FNU' };
const rows = values => values.map((value, i) => ({ id:i, channels:{ x:value }, prediction:i===0 ? 1 : 0, timestamp:'2026-10-17T12:01:00', sample_index:i }));
let chart = sensorChart(rows([2, null, 4, NaN, Infinity, 5]), channel);
assert.equal(chart.finiteCount, 3); assert.equal(chart.missingCount, 3);
assert.equal(chart.min, 2); assert.equal(chart.max, 5);
assert.equal(chart.svg.match(/class="chart-line" d="([^"]+)"/)[1].match(/M/g).length, 3);
assert(!chart.svg.includes('<unsafe sensor>')); assert(chart.svg.includes('&lt;unsafe sensor&gt;'));
assert(!chart.svg.includes('NaN')); assert(!chart.svg.includes('Infinity')); tests++;
chart = sensorChart(rows([null, null]), channel);
assert.equal(chart.svg, ''); assert.equal(chart.finiteCount, 0); assert.equal(chart.latest, null); tests++;
chart = sensorChart(rows([0, 0, 0]), channel);
assert.equal(chart.min, 0); assert.equal(chart.latest, 0); assert(!chart.svg.includes('NaN')); tests++;

const { api, ApiError, safeLink } = await loadModule('./api.js');
globalThis.location = { origin:'http://127.0.0.1:8787' };
assert.equal(safeLink('/viewer/'), 'http://127.0.0.1:8787/viewer/');
assert.equal(safeLink('javascript:alert(1)'), null); assert.equal(safeLink('file:///secret'), null); tests++;
let calls = [];
globalThis.fetch = async (url, options) => { calls.push({url,options}); return {ok:true,json:async()=>({ok:true})}; };
await api.createSession('known-source', false);
assert.deepEqual(JSON.parse(calls.at(-1).options.body),{source_id:'known-source',research_ack:false});
assert.equal(calls.at(-1).options.headers['Content-Type'],'application/json');
assert.equal(calls.at(-1).options.credentials,'same-origin');
await api.step(10); assert.deepEqual(JSON.parse(calls.at(-1).options.body),{count:10});
await api.readings({limit:100,sessionId:'a & b'}); assert(calls.at(-1).url.includes('session_id=a+%26+b')); tests++;
await api.plantControl({fault:'sensor_dropout',mode:'auto',running:true});
assert.equal(calls.at(-1).url,'/api/plant/control'); assert.equal(calls.at(-1).options.method,'POST');
assert.deepEqual(JSON.parse(calls.at(-1).options.body),{fault:'sensor_dropout',mode:'auto',running:true});
await api.state();assert.equal(calls.at(-1).url,'/api/state');assert.equal(calls.at(-1).options.method,'GET');
assert.equal(calls.at(-1).options.body,undefined);tests++;
globalThis.fetch = async () => ({ok:false,status:409,json:async()=>({error:{code:'manual_hold',message:'held'}})});
await assert.rejects(api.step(1),error=>error instanceof ApiError && error.code==='manual_hold' && error.message==='held'); tests++;
globalThis.fetch = async () => { throw new Error('offline'); };
await assert.rejects(api.state(),error=>error.code==='network_error'); tests++;
globalThis.fetch = async () => { const e=new Error();e.name='AbortError';throw e; };
await assert.rejects(api.state(),error=>error.code==='timeout'); tests++;

// Exercise the app's actual queue functions with a minimal DOM, not a second
// reimplementation of the replay logic. Every fixture is synthetic.
const nodes = new Map();
function node(key) {
  if (!nodes.has(key)) nodes.set(key,{disabled:false,hidden:true,checked:false,innerHTML:'',textContent:'',value:'',dataset:{},
    open:false,focusCalls:[],listeners:new Map(),
    classList:{add(){},remove(){},toggle(){},contains(){return false;}},
    setAttribute(){},removeAttribute(){},addEventListener(type,handler){this.listeners.set(type,handler);},
    focus(options){this.focusCalls.push(options);},showModal(){this.open=true;},close(){this.open=false;},querySelector(){return null;},querySelectorAll(){return [];}});
  return nodes.get(key);
}
const base={app:{name:'synthetic'},overview:{readings:0,unacknowledged_alarms:0,reasons:[]},series:[],alarms:[],
  source:{id:'synthetic',kind:'public_replay',channels:[]},session:{id:'fixture',status:'ready',position:0,total:1600,sample_seconds:60},
  model:{version:'synthetic',status:'research_only'},settings:{site_name:'fixture'},links:{},latest:null};
const scheduled = new Map(); let timerId=0, resolveStep, stepCalls=0, pauseCalls=0;
const fakeApi={state:async()=>base,sources:async()=>({sources:[]}),
  step:()=>{stepCalls++;return new Promise(resolve=>{resolveStep=resolve;});},
  pause:async()=>{pauseCalls++;return {...base,session:{...base.session,status:'paused',position:10}};}};
const documentListeners=new Map();
const dom={hidden:false,activeElement:null,body:node('body'),querySelector:node,querySelectorAll:()=>[],addEventListener(type,handler){documentListeners.set(type,handler);}};
// Only the inline command error needs a nested element in this queue harness.
// The rest of the real guide's browser rendering is checked separately.
node('#page-content').querySelector=selector=>selector==='#experience-error'?node('#experience-error'):null;
globalThis.document=dom;
globalThis.matchMedia=()=>({matches:false});
const locationFixture={origin:'http://127.0.0.1:8787',_hash:'',get hash(){return this._hash;},set hash(value){this._hash=value&&!value.startsWith('#')?'#'+value:value;}};
const scrollCalls=[];
const windowListeners=new Map(),sceneMessages=[];
const sceneWindow={postMessage:(payload,origin)=>sceneMessages.push({payload,origin})};
node('#guide-scene').contentWindow=sceneWindow;
let syntheticNow=0;
const context=vm.createContext({console,Intl,Date,Promise,Map,Set,Number,String,Object,Array,Math,JSON,Error,
  api:fakeApi, safeLink:()=>null, sensorChart, plantView, plantPage, updatePlant, EQUIPMENT, PLANT_MODES, PLANT_FAULTS,
  GUIDE_PAGES,renderGuide,updateTour,updateComponent,experienceState,journeyProgress,JourneyPresentation,
  performance:{now:()=>syntheticNow},
  navigator:{clipboard:{writeText:async()=>{}}},
  document:dom,
  location:locationFixture,window:{addEventListener(type,handler){windowListeners.set(type,handler);},scrollTo(options){scrollCalls.push(options);}},
  setTimeout:callback=>{const id=++timerId;scheduled.set(id,callback);return id;},
  clearTimeout:id=>scheduled.delete(id),setInterval:()=>0,
});
let appSource=await fs.readFile(new URL('./app.js',import.meta.url),'utf8');
appSource=appSource.replace(/^import .*;\n/gm,'')+'\nglobalThis.harness={state,play,pause,mutate,canReplay,refresh,loadHistory,loadAlarms,applyState,telemetryView,telemetryCardContent,copyTelemetrySession,settingsPage,render,openSession,startPlant,controlPlant,guideCommand,experienceNext,syncJourneyScene,moveJourney,sessionBanner,route,presenter,startPresentation,resumePresentation,pausePresentation,stopPresentation,tickPresentation,get cameraRequest(){return cameraRequest;}};';
vm.runInContext(appSource,context);
await new Promise(resolve=>setImmediate(resolve));
const h=context.harness; assert(h.state.connected); assert(h.canReplay());
assert.equal(h.state.page,'start');assert(node('#page-content').innerHTML.includes('g-hero'));
assert.equal(node('#advanced-navigation').open,false);
assert(node('#main-content').focusCalls.length>0);assert(scrollCalls.length>0);
context.location.hash='#overview';h.route();assert.equal(node('#advanced-navigation').open,true);
context.location.hash='#unknown';h.route();assert.equal(h.state.page,'start');
assert.equal(stepCalls,0);assert.equal(pauseCalls,0);tests++;
const playing=h.play(); await Promise.resolve();
assert.equal(stepCalls,1); assert(h.state.mutation); assert(h.state.autoplay);
await h.play(); assert.equal(stepCalls,1); // A second play never overlaps.
const paused=h.pause(); assert.equal(h.state.autoplay,false); assert.equal(pauseCalls,0);
resolveStep({...base,overview:{...base.overview,readings:10},session:{...base.session,position:10}});
await Promise.all([playing,paused]);
assert.equal(pauseCalls,1); assert.equal(h.state.mutation,null); assert.equal(h.state.timer,null);
assert.equal(h.state.data.session.status,'paused'); assert.equal(stepCalls,1); tests++;

fakeApi.step=async()=>{stepCalls++;throw new ApiError('synthetic failure','replay_failed',500);};
await h.play(); assert.equal(h.state.autoplay,false); assert.equal(h.state.mutation,null); assert.equal(h.state.timer,null);
assert.equal(h.state.data.session.position,10); tests++;

function deferred() { let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject}; }
const settle=()=>new Promise(resolve=>setImmediate(resolve));

// A GET started before a write cannot restore the old session or settings,
// even if it resolves after the successful mutation response.
h.state.sources=[base.source];
const staleState=deferred();fakeApi.state=()=>staleState.promise;
const refreshing=h.refresh();
const newer={...base,session:{...base.session,id:'new-session',position:25},settings:{site_name:'new settings'}};
await h.mutate(async()=>newer);
staleState.resolve(base);await refreshing;
assert.equal(h.state.data.session.id,'new-session');assert.equal(h.state.data.session.position,25);
assert.equal(h.state.data.settings.site_name,'new settings');assert(h.state.connected);tests++;

// The same invalidation applies before the write settles and to stale errors.
const oldGet=deferred(),pendingWrite=deferred();fakeApi.state=()=>oldGet.promise;
const oldRefresh=h.refresh();const writing=h.mutate(()=>pendingWrite.promise);
oldGet.reject(new ApiError('old network failure','network_error'));await oldRefresh;
assert(h.state.connected);assert.equal(h.state.data.session.id,'new-session');
pendingWrite.resolve({...newer,session:{...newer.session,position:30}});await writing;
assert.equal(h.state.data.session.position,30);tests++;

// Reversed filter responses never show all-session rows under "current".
const allHistory=deferred(),currentHistory=deferred();const historyCalls=[];
fakeApi.readings=options=>{historyCalls.push(options);return options.sessionId?currentHistory.promise:allHistory.promise;};
h.state.page='history';h.state.historyScope='all';h.state.readings=[{id:900}];h.state.historyLoaded=true;
const loadingAll=h.loadHistory();h.state.historyScope='current';const loadingCurrent=h.loadHistory();
assert.equal(h.state.readings.length,0);assert.equal(h.state.historyLoaded,false);
currentHistory.resolve({readings:[{id:2,session_id:'new-session',channels:{}}]});await loadingCurrent;
allHistory.resolve({readings:[{id:1,session_id:'other-session',channels:{}}]});await loadingAll;
assert.equal(h.state.readings[0].id,2);assert.equal(h.state.historyScope,'current');
assert.equal(historyCalls[1].sessionId,'new-session');assert(!node('#page-content').innerHTML.includes('other-session'));tests++;

// A superseded failure must not replace the current result/error, and limit
// changes invalidate the view immediately while the new request is pending.
const oldLimit=deferred(),newLimit=deferred();fakeApi.readings=options=>options.limit===100?oldLimit.promise:newLimit.promise;
h.state.historyLimit=100;const oldLimitLoad=h.loadHistory();h.state.historyLimit=250;const newLimitLoad=h.loadHistory();
assert.equal(h.state.readings.length,0);
newLimit.resolve({readings:[{id:3,session_id:'new-session',channels:{}}]});await newLimitLoad;
oldLimit.reject(new Error('obsolete error'));await oldLimitLoad;
assert.equal(h.state.readings[0].id,3);assert.equal(h.state.historyError,'');tests++;

// Polling updates the visible alert list immediately, then expands it from
// the dedicated endpoint. A prior list request cannot overwrite that snapshot.
h.state.page='alerts';h.state.alarmsLoaded=true;h.state.alarms=[{id:1,title:'OLD_ALARM',kind:'system'}];
const oldAlerts=deferred(),newAlerts=deferred();let alarmRequests=0;
fakeApi.alarms=()=>++alarmRequests===1?oldAlerts.promise:newAlerts.promise;
const oldAlarmLoad=h.loadAlarms();
const newAlarm={id:2,title:'NEW_ALARM',detail:'from polling',kind:'anomaly',severity:'warning'};
fakeApi.state=async()=>({...newer,overview:{...base.overview,unacknowledged_alarms:1},alarms:[newAlarm]});
const alertRefresh=h.refresh();await settle();
assert.equal(node('#nav-alert-count').textContent,'1');
assert(node('#page-content').innerHTML.includes('NEW_ALARM'));assert(!node('#page-content').innerHTML.includes('OLD_ALARM'));
oldAlerts.resolve({alarms:[{id:1,title:'OLD_ALARM',kind:'system'}]});await oldAlarmLoad;
assert(node('#page-content').innerHTML.includes('NEW_ALARM'));
newAlerts.resolve({alarms:[newAlarm,{id:0,title:'OLDER_HISTORY',kind:'system'}]});await alertRefresh;
assert.equal(h.state.alarmsLoaded,true);assert.equal(h.state.alarms.length,2);
assert(node('#page-content').innerHTML.includes('NEW_ALARM'));assert(node('#page-content').innerHTML.includes('OLDER_HISTORY'));tests++;

// Session pinning is explicit. Replay, failed/idle sessions, and mismatched
// telemetry snapshots never supply a usable identifier or previous receipts.
const telemetryId='2750bfbf-90ca-4c07-ae46-bdff5e55758e';
const telemetryBase={...base,source:{id:'telemetry',name:'قراءات جهاز عبر API',kind:'telemetry',channels:[]},
  session:{id:telemetryId,status:'ready'},telemetry:{session_id:telemetryId,last_device_id:null,last_received_at:null,last_receipt:null}};
assert.equal(h.telemetryView(telemetryBase).sessionId,telemetryId);
assert(h.telemetryView({...telemetryBase,session:{...telemetryBase.session,status:'paused'}}).eligible);
for(const status of ['idle','failed','completed']) assert.equal(h.telemetryView({...telemetryBase,session:{...telemetryBase.session,status}}).sessionId,null);
for(const fixture of [base,{...telemetryBase,source:base.source},{...telemetryBase,telemetry:{...telemetryBase.telemetry,session_id:'other'}},
  {...telemetryBase,session:null},{...telemetryBase,telemetry:null}]) {
  const view=h.telemetryView(fixture);assert(!view.eligible);assert.equal(view.sessionId,null);assert.equal(view.receipt,null);
} tests++;

h.state.page='settings';h.state.settingsRendered=false;h.applyState(telemetryBase);
let card=h.telemetryCardContent();
assert(card.includes('بانتظار أول قراءة'));assert(card.includes('لم يصل معرّف جهاز'));assert(card.includes('لم تصل قراءة بعد'));
assert(card.includes(telemetryId));assert(card.includes('copy-telemetry-session'));assert(card.includes('غير مؤهل لهذا المخطط'));
assert(!card.includes('your-device-id'));tests++;

const received={...telemetryBase,telemetry:{session_id:telemetryId,last_device_id:'edge <img src=x>',
  last_received_at:'2026-10-17T10:20:30Z',last_receipt:{session_id:telemetryId,measurement_id:'measurement <script>',reading_id:42,duplicate:false}},
  ingestion:{receipts:[{session_id:'other',measurement_id:'WRONG_EPHEMERAL_RECEIPT',reading_id:99}]}};
h.applyState(received);card=h.telemetryCardContent();
assert(card.includes('وصلت قراءة'));assert(card.includes('2026-10-17 10:20:30 UTC'));assert(card.includes('edge &lt;img src=x&gt;'));
assert(card.includes('measurement &lt;script&gt;'));assert(!card.includes('<img'));assert(!card.includes('<script>'));
assert(!card.includes('WRONG_EPHEMERAL_RECEIPT'));assert.equal(h.telemetryView(received).receipt.readingId,42);tests++;

for(const last_receipt of [null,{session_id:'other',measurement_id:'WRONG_RECEIPT',reading_id:99},
  {session_id:telemetryId,measurement_id:'WRONG_RECEIPT',reading_id:null}]) {
  h.applyState({...received,telemetry:{...received.telemetry,last_receipt}});
  card=h.telemetryCardContent();assert(!card.includes('WRONG_RECEIPT'));assert(!card.includes('WRONG_EPHEMERAL_RECEIPT'));
  assert(card.includes('لا يوجد إيصال مرقّم لهذه القراءة'));
} tests++;

// Polling replaces only the card. It must not recreate a settings form while
// the operator is editing it, even when session/receipt identity changes.
h.applyState(telemetryBase);h.render(true);
const settingsMarkup=node('#page-content').innerHTML;
node('[name="site_name"]').value='UNSAVED OPERATOR EDIT';
fakeApi.state=async()=>received;await h.refresh();
assert.equal(node('#page-content').innerHTML,settingsMarkup);
assert.equal(node('[name="site_name"]').value,'UNSAVED OPERATOR EDIT');
assert(node('#telemetry-card').innerHTML.includes('measurement &lt;script&gt;'));
fakeApi.state=async()=>base;await h.refresh();
assert.equal(node('#page-content').innerHTML,settingsMarkup);
assert.equal(node('[name="site_name"]').value,'UNSAVED OPERATOR EDIT');
assert(!node('#telemetry-card').innerHTML.includes(telemetryId));assert(!node('#telemetry-card').innerHTML.includes('copy-telemetry-session'));
assert(node('#telemetry-card').innerHTML.includes('telemetry-session'));tests++;

// Copy reads the current authoritative state, not the DOM or a cached UUID.
const copied=[];context.navigator.clipboard.writeText=async text=>{copied.push(text);};
h.applyState(received);await h.copyTelemetrySession();assert.deepEqual(copied,[telemetryId]);
h.applyState(base);await assert.rejects(h.copyTelemetrySession(),/لا توجد جلسة API/);assert.equal(copied.length,1);
h.applyState(received);h.state.connected=false;await assert.rejects(h.copyTelemetrySession(),/لا توجد جلسة API/);assert.equal(copied.length,1);h.state.connected=true;
context.navigator.clipboard.writeText=async()=>{throw new Error('clipboard denied');};
await assert.rejects(h.copyTelemetrySession(),/تعذّر النسخ إلى الحافظة/);
context.navigator.clipboard=null;await assert.rejects(h.copyTelemetrySession(),/النسخ التلقائي غير متاح/);tests++;

const clipboardPending=deferred();context.navigator.clipboard={writeText:()=>clipboardPending.promise};
const copying=h.copyTelemetrySession();h.applyState(base);clipboardPending.resolve();
await assert.rejects(copying,/تغيّرت حالة الجلسة/);tests++;

// The CTA only opens the normal source/acknowledgement dialog. It never
// starts a telemetry session or reuses the acknowledgement from an old one.
let createCalls=0;fakeApi.createSession=async()=>{createCalls++;return telemetryBase;};
h.state.sources=[base.source,telemetryBase.source];
await h.openSession('telemetry');
const dialog=node('#session-form-fields').innerHTML;
assert(dialog.includes('<option value="telemetry" selected>'));assert(dialog.includes('id="research-ack" required'));
assert(!dialog.includes(' checked'));assert.equal(createCalls,0);assert.equal(h.state.data.source.kind,'public_replay');tests++;

// Digital twin controls are explicit writes, isolated from historical replay.
const twin={...base,source:{id:'virtual_plant',kind:'digital_twin',channels:[]},session:{id:'twin',status:'ready'},
  virtual_plant:{session_id:'twin',running:true,mode:'auto',fault:'none',speed:1,timestamp:'2026-01-01T00:00:00Z'}};
// Source selection from the overview dialog must keep three distinct
// descriptions and acknowledgements; a twin is never historical inference.
h.state.page='overview';h.state.sources=[base.source,telemetryBase.source,twin.source];
await h.openSession('virtual_plant');
const twinDialog=node('#session-form-fields').innerHTML;
assert(twinDialog.includes('<option value="virtual_plant" selected>'));
assert(twinDialog.includes('الخزانات والتدفقات'));assert(twinDialog.includes('قواعد تشغيل ثابتة'));
assert(twinDialog.includes('كل ثانية'));assert(twinDialog.includes('×30'));assert(twinDialog.includes('أبدأ توأمًا رقميًا'));
assert(!twinDialog.includes('إعادة عرض'));assert(!twinDialog.includes('قراءة تاريخية'));
assert(!twinDialog.includes('الاستدلال فعليًا'));assert(!twinDialog.includes('نموذج بحثي على بيانات تاريخية'));
assert(twinDialog.includes('id="research-ack" required'));assert(!twinDialog.includes(' checked'));
await h.openSession('synthetic');assert(node('#session-form-fields').innerHTML.includes('الاستدلال فعليًا'));
await h.openSession('telemetry');assert(node('#session-form-fields').innerHTML.includes('جلسة استقبال لقياساتك عبر API'));
assert(!node('#session-form-fields').innerHTML.includes('الاستدلال فعليًا'));tests++;
const created=[];fakeApi.createSession=async(sourceId,ack)=>{created.push([sourceId,ack]);return twin;};
h.state.page='overview';h.applyState(base);await h.startPlant();
assert.equal(created.length,1);assert.equal(created[0][0],'virtual_plant');assert.equal(created[0][1],true);
assert.equal(h.state.page,'plant');assert.equal(h.canReplay(),false);assert(node('.research-strip').hidden);
const twinBanner=h.sessionBanner();assert(twinBanner.includes('#plant'));assert(!twinBanner.includes('data-action="step"'));
assert(!twinBanner.includes('data-action="play"'));tests++;

const plantCommands=[];fakeApi.plantControl=async command=>{plantCommands.push(JSON.parse(JSON.stringify(command)));return {...twin,virtual_plant:{...twin.virtual_plant,...command}};};
await h.controlPlant('fault','power_loss');assert.equal(plantCommands.at(-1).fault,'power_loss');
await h.controlPlant('speed',30);assert.equal(plantCommands.at(-1).speed,30);
await h.controlPlant('running',false);assert.equal(plantCommands.at(-1).running,false);
assert.equal(h.state.data.virtual_plant.timestamp,'2026-01-01T00:00:00Z');
for(const [key,value] of [['speed',2],['fault','power'],['valve','open'],['running','true']]) await assert.rejects(h.controlPlant(key,value),/غير صالح/);
assert.equal(plantCommands.length,3);tests++;

const plantWrite=deferred();fakeApi.plantControl=()=>plantWrite.promise;
const firstPlantWrite=h.controlPlant('mode','standby');await assert.rejects(h.controlPlant('mode','backwash'),/انتظر اكتمال/);
plantWrite.resolve({...twin,virtual_plant:{...twin.virtual_plant,mode:'standby'}});await firstPlantWrite;
assert.equal(h.state.data.virtual_plant.mode,'standby');tests++;

fakeApi.state=async()=>twin;const commandCount=plantCommands.length;
await h.refresh();await h.refresh();assert.equal(plantCommands.length,commandCount);assert.equal(created.length,1);
assert.equal(h.state.data.virtual_plant.timestamp,'2026-01-01T00:00:00Z');
h.applyState(base);await assert.rejects(h.controlPlant('mode','auto'),/شغّل جلسة المنشأة/);
assert(!node('#page-content').innerHTML.includes('123.5'));assert(node('#page-content').innerHTML.includes('id="guide-scene"'));tests++;

// Route changes, guide-step navigation and polling are read-only. Only an
// explicit scenario action invokes the command, with session creation first
// if needed. These exercise the actual handlers, with synthetic API promises.
const writes=[];
fakeApi.createSession=async(sourceId,ack)=>{writes.push({kind:'session',sourceId,ack});return twin;};
fakeApi.plantControl=async control=>{writes.push({kind:'control',control:JSON.parse(JSON.stringify(control))});return {...twin,virtual_plant:{...twin.virtual_plant,...control}};};
fakeApi.state=async()=>base;
h.applyState(base);context.location.hash='#plant';h.route();
const click=async(action,extra={})=>node('#page-content').listeners.get('click')({target:{closest:selector=>selector==='[data-action]'?{dataset:{action,...extra}}:null}});
await click('guide-tour',{step:'1'});assert.equal(h.state.guideUi.tourStep,1);
await click('guide-tour-next');assert.equal(h.state.guideUi.tourStep,2);
await h.refresh();assert.equal(writes.length,0);
await click('guide-fault');
assert.deepEqual(writes,[{kind:'session',sourceId:'virtual_plant',ack:true},{kind:'control',control:{fault:'sensor_dropout',mode:'auto',running:true}}]);
await click('guide-clear');assert.equal(writes.length,3);
assert.deepEqual(writes.at(-1),{kind:'control',control:{fault:'none',mode:'auto',running:true}});tests++;

// A second explicit guide action cannot overlap an in-flight mutation.
const pendingGuide=deferred();let guideWrites=0;
fakeApi.plantControl=()=>{guideWrites++;return pendingGuide.promise;};
const guideRequest=h.guideCommand({fault:'sensor_dropout',mode:'auto',running:true});
await assert.rejects(h.guideCommand({fault:'none',mode:'auto',running:true}),/انتظر اكتمال/);
assert.equal(guideWrites,1);pendingGuide.resolve(twin);await guideRequest;tests++;

// The simplified page uses the actual experience-next handler. These fixtures
// are explicit server responses, not a second simulator or state machine.
function experienceFixture({sessionId='experience-a',status='ready',running=true,fault='none',mode='auto',hold=false,
  valve='open',reuse=8,safety='REUSE'}={}) {
  return {...base, source:{id:'virtual_plant',kind:'digital_twin',channels:[]},
    session:{id:sessionId,status}, overview:{...base.overview,manual_hold:hold},
    virtual_plant:{session_id:sessionId,running,manual_hold:hold,mode,fault,speed:1,
      timestamp:'2026-01-01T00:00:00Z',flow:{reuse_lpm:reuse,treatment_lpm:10},
      equipment:{irrigation_valve:valve},safety:{state:safety,reasons:[]}}};
}
const experienceWrites=[];
const captureControl=(response)=>async control=>{
  experienceWrites.push({kind:'control',control:JSON.parse(JSON.stringify(control))});return response;
};
const nextState=()=>experienceState(h.state.data,h.state.guideUi,h.state.connected);
h.state.page='plant';h.state.guideUi.experienceRestored=true;h.state.guideUi.experienceSession='old';
h.applyState(base);
fakeApi.createSession=async(sourceId,ack)=>{
  experienceWrites.push({kind:'session',sourceId,ack});return experienceFixture();
};
await click('experience-next');
assert.deepEqual(experienceWrites,[{kind:'session',sourceId:'virtual_plant',ack:true}]);
assert.equal(h.state.guideUi.experienceSession,'experience-a');assert.equal(h.state.guideUi.experienceRestored,false);
assert.equal(nextState().id,'journey');assert.equal(journeyProgress(h.state.guideUi,'experience-a').index,0);
assert.equal(h.state.guideUi.journeyComplete,false);assert.equal(dom.body.dataset.experience,'true');tests++;

// Next and previous only navigate the educational route. Seven Next actions
// cover all eight stages; only the last stage offers an actual fault command.
experienceWrites.length=0;sceneMessages.length=0;
for(let index=0;index<WATER_JOURNEY.length;index++) {
  const progress=journeyProgress(h.state.guideUi,'experience-a');
  assert.equal(progress.index,index);assert.equal(nextState().id,'journey');
  assert.equal(nextState().title,WATER_JOURNEY[index].title);
  assert.equal(nextState().action,index===7?'test':'journey-next');
  h.syncJourneyScene(true);
  const message=sceneMessages.at(-1);assert.equal(message.origin,locationFixture.origin);
  assert.equal(message.payload.type,'mawrid:journey');assert.equal(message.payload.id,WATER_JOURNEY[index].id);
  assert.equal(message.payload.camera,'overview');assert.equal(typeof message.payload.requestId,'number');
  if(index<7)await click('experience-next');
}
assert.equal(experienceWrites.length,0);assert.equal(h.state.guideUi.journeyComplete,false);
await click('journey-previous');assert.equal(journeyProgress(h.state.guideUi,'experience-a').index,6);
await click('experience-next');assert.equal(journeyProgress(h.state.guideUi,'experience-a').index,7);
assert.equal(experienceWrites.length,0);tests++;

// Resume preserves the session and issues only a clock command. It does not
// silently remove a fault, change speed or create a new session.
experienceWrites.length=0;
h.applyState(experienceFixture({status:'paused',running:false}));
fakeApi.plantControl=captureControl(experienceFixture());
await click('experience-next');
assert.deepEqual(experienceWrites,[{kind:'control',control:{running:true}}]);
assert.equal(nextState().id,'journey');assert.equal(journeyProgress(h.state.guideUi,'experience-a').index,7);
assert.equal(h.state.guideUi.experienceRestored,false);tests++;

// Testing a sensor records the active session only after the write succeeds.
// A previous completion flag is invalidated on the confirmed test response.
experienceWrites.length=0;h.state.guideUi.experienceRestored=true;
const dropout=experienceFixture({fault:'sensor_dropout',valve:'closed',reuse:0,safety:'HOLD'});
fakeApi.plantControl=captureControl(dropout);
await click('experience-next');
assert.deepEqual(experienceWrites,[{kind:'control',control:{fault:'sensor_dropout',mode:'auto',speed:1,running:true}}]);
assert.equal(nextState().id,'fault');assert.equal(h.state.guideUi.experienceRestored,false);
assert.equal(h.state.guideUi.experienceSession,'experience-a');assert.equal(h.state.guideUi.journeyComplete,true);tests++;

experienceWrites.length=0;fakeApi.plantControl=captureControl(experienceFixture());
await click('experience-next');
assert.deepEqual(experienceWrites,[{kind:'control',control:{fault:'none',mode:'auto',speed:1,running:true}}]);
assert.equal(h.state.guideUi.experienceRestored,true);assert.equal(nextState().id,'done');
assert.equal(nextState().action,'test');tests++;

// Polling and route changes preserve completion for the same session. An
// unrelated session or source cannot inherit it, even if the UI flag remains.
h.applyState(experienceFixture());
context.location.hash='#components';h.route();assert.equal(dom.body.dataset.experience,'false');
context.location.hash='#plant';h.route();assert.equal(dom.body.dataset.experience,'true');
assert.equal(nextState().id,'done');
h.applyState(experienceFixture({sessionId:'experience-b'}));assert.equal(nextState().id,'journey');
assert.equal(journeyProgress(h.state.guideUi,'experience-b').index,0);assert.equal(journeyProgress(h.state.guideUi,'experience-b').complete,false);
h.applyState(base);assert.equal(nextState().id,'start');
assert.equal(h.state.guideUi.experienceSession,'experience-a');tests++;

// Replaying the explanation clears its local progress and restoration badge.
// It neither restarts the session nor changes the running plant in any way.
h.applyState(experienceFixture());experienceWrites.length=0;
const beforeReplay=JSON.stringify(h.state.data);
await click('journey-replay');
assert.equal(journeyProgress(h.state.guideUi,'experience-a').index,0);
assert.equal(h.state.guideUi.journeyComplete,false);assert.equal(h.state.guideUi.experienceRestored,false);
assert.equal(nextState().id,'journey');assert.equal(JSON.stringify(h.state.data),beforeReplay);
assert.equal(experienceWrites.length,0);tests++;

// Pausing halfway through the journey preserves its stage; only the explicit
// resume action writes to the clock. Previous and replay are blocked here.
h.state.guideUi.journeyIndex=3;h.applyState(experienceFixture({status:'paused',running:false}));
const beforePauseJourney=JSON.stringify(h.state.guideUi);experienceWrites.length=0;
await click('journey-previous');await click('journey-replay');
assert.equal(JSON.stringify(h.state.guideUi),beforePauseJourney);assert.equal(experienceWrites.length,0);
fakeApi.plantControl=captureControl(experienceFixture());await click('experience-next');
assert.deepEqual(experienceWrites,[{kind:'control',control:{running:true}}]);
assert.equal(journeyProgress(h.state.guideUi,'experience-a').index,3);
assert.equal(nextState().title,WATER_JOURNEY[3].title);tests++;

// Scene synchronization is read-only and deduplicates repeated polling. Only
// a ready message from the current iframe at this origin may force a resend.
experienceWrites.length=0;sceneMessages.length=0;h.syncJourneyScene(true);
const messageCount=sceneMessages.length;h.syncJourneyScene();h.syncJourneyScene();
assert.equal(sceneMessages.length,messageCount);
const onMessage=windowListeners.get('message');assert.equal(typeof onMessage,'function');
for(const event of [
  {origin:'https://other.example',source:sceneWindow,data:{type:'mawrid:scene-ready'}},
  {origin:locationFixture.origin,source:{},data:{type:'mawrid:scene-ready'}},
  {origin:locationFixture.origin,source:sceneWindow,data:{type:'mawrid:control'}},
])onMessage(event);
assert.equal(sceneMessages.length,messageCount);
onMessage({origin:locationFixture.origin,source:sceneWindow,data:{type:'mawrid:scene-ready'}});
assert.equal(sceneMessages.length,messageCount+1);assert.equal(sceneMessages.at(-1).payload.id,'polish');
assert.equal(experienceWrites.length,0);tests++;

// A fault, manual hold or disconnection blocks educational navigation. The
// coach reflects the actual condition without moving the saved route index.
for(const fixture of [experienceFixture({fault:'sensor_dropout',reuse:0,valve:'closed',safety:'HOLD'}),experienceFixture({hold:true})]) {
  h.applyState(fixture);const index=h.state.guideUi.journeyIndex;experienceWrites.length=0;
  assert.notEqual(nextState().id,'journey');await click('journey-previous');await click('journey-replay');
  assert.equal(h.state.guideUi.journeyIndex,index);assert.equal(experienceWrites.length,0);
}
h.applyState(experienceFixture());h.state.connected=false;const offlineIndex=h.state.guideUi.journeyIndex;
await click('journey-previous');await click('journey-replay');await h.experienceNext();
assert.equal(h.state.guideUi.journeyIndex,offlineIndex);assert.equal(experienceWrites.length,0);
h.state.connected=true;tests++;

// Restoring an already active fault midway through the explanation does not
// award a finished journey or skip its remaining stages.
h.applyState(dropout);experienceWrites.length=0;fakeApi.plantControl=captureControl(experienceFixture());
await click('experience-next');
assert.equal(h.state.guideUi.experienceRestored,true);assert.equal(h.state.guideUi.journeyComplete,false);
assert.equal(nextState().id,'journey');assert.equal(journeyProgress(h.state.guideUi,'experience-a').index,3);
assert.equal(experienceWrites.length,1);tests++;

// Fault focus is explanatory only. Changing source removes the old journey
// highlight, and a different virtual session begins at collection.
experienceWrites.length=0;
for(const [fault,id] of [['sensor_dropout','verify'],['clogging','media'],['valve_stuck','irrigation'],['power_loss',null]]){
  h.applyState(experienceFixture({fault,reuse:0,valve:'closed',safety:'HOLD'}));h.syncJourneyScene(true);
  assert.equal(sceneMessages.at(-1).payload.id,id);
}
h.applyState(base);h.syncJourneyScene(true);assert.equal(sceneMessages.at(-1).payload.id,null);
h.applyState(experienceFixture({sessionId:'different'}));h.syncJourneyScene(true);
assert.equal(sceneMessages.at(-1).payload.id,'collection');assert.equal(experienceWrites.length,0);tests++;

// The remaining fault regression checks begin after the full route, as the
// completion badge now requires both this session's route and restoration.
Object.assign(h.state.guideUi,{journeySession:'experience-a',journeyIndex:7,journeyComplete:true});

// Failed restoration keeps the same action and exposes an inline error. The
// real click handler catches it for the user; no completion or session starts.
h.applyState(dropout);h.state.guideUi.experienceRestored=false;
experienceWrites.length=0;
fakeApi.plantControl=async control=>{
  experienceWrites.push({kind:'control',control:JSON.parse(JSON.stringify(control))});
  throw new ApiError('تعذر تأكيد إزالة العطل','control_failed',409);
};
await click('experience-next');
assert.equal(experienceWrites.length,1);assert.equal(h.state.guideUi.experienceRestored,false);
assert.equal(nextState().id,'fault');assert.equal(h.state.guideUi.experienceError,'تعذر تأكيد إزالة العطل');
assert.equal(node('#experience-error').hidden,false);assert.equal(node('#experience-error').textContent,'تعذر تأكيد إزالة العطل');
assert.equal(node('#toast').textContent,'تعذر تأكيد إزالة العطل');assert.equal(h.state.mutation,null);tests++;

// A syntactically successful API response that still reports a fault is not
// enough to record restoration. A blocked valve after a cleared fault also
// cannot display completion, regardless of the UI's restoration marker.
experienceWrites.length=0;fakeApi.plantControl=captureControl(dropout);
await click('experience-next');
assert.equal(h.state.guideUi.experienceRestored,false);assert.equal(nextState().id,'fault');
assert.equal(h.state.guideUi.experienceError,'');assert.equal(node('#experience-error').hidden,true);
fakeApi.plantControl=captureControl(experienceFixture({valve:'closed',reuse:0,safety:'HOLD'}));
await click('experience-next');assert.equal(nextState().id,'waiting');assert.notEqual(nextState().id,'done');tests++;

// Returning from backwash or standby is ordinary operation, not evidence that
// the visitor observed and restored a sensor dropout.
for(const mode of ['backwash','standby']) {
  h.applyState(experienceFixture({mode}));h.state.guideUi.experienceRestored=false;
  experienceWrites.length=0;fakeApi.plantControl=captureControl(experienceFixture());
  await click('experience-next');
  assert.deepEqual(experienceWrites,[{kind:'control',control:{fault:'none',mode:'auto',speed:1,running:true}}]);
  assert.equal(h.state.guideUi.experienceRestored,false);assert.equal(nextState().id,'normal');
}
tests++;

// Removing a manual hold issues reset only. Resuming is a separate explicit
// action, so a visitor cannot accidentally restart equipment by clearing it.
experienceWrites.length=0;
h.applyState(experienceFixture({hold:true,status:'paused',running:false}));
fakeApi.reset=async()=>{
  experienceWrites.push({kind:'reset'});return experienceFixture({status:'paused',running:false});
};
fakeApi.plantControl=captureControl(experienceFixture());
await click('experience-next');assert.deepEqual(experienceWrites,[{kind:'reset'}]);
assert.equal(nextState().id,'paused');assert.equal(nextState().action,'resume');
await click('experience-next');assert.deepEqual(experienceWrites,[{kind:'reset'},{kind:'control',control:{running:true}}]);tests++;

// A pending write cannot be duplicated by a rapid second click. The final
// result, not the click, changes the session-bound completion marker.
h.applyState(dropout);h.state.guideUi.experienceRestored=false;
const pendingExperience=deferred();experienceWrites.length=0;
fakeApi.plantControl=control=>{
  experienceWrites.push({kind:'control',control:JSON.parse(JSON.stringify(control))});return pendingExperience.promise;
};
const experienceRequest=click('experience-next');await settle();
assert(h.state.mutation);assert.equal(h.state.guideUi.experienceRestored,false);
await click('experience-next');assert.equal(experienceWrites.length,1);
assert.match(node('#toast').textContent,/انتظر اكتمال/);
pendingExperience.resolve(experienceFixture());await experienceRequest;
assert.equal(h.state.mutation,null);assert.equal(nextState().id,'done');tests++;

// Offline and incomplete operating states have no primary action and cannot
// issue writes even when a caller invokes the real handler directly.
experienceWrites.length=0;h.state.connected=false;
await h.experienceNext();assert.equal(experienceWrites.length,0);assert.equal(nextState().id,'disconnected');
h.applyState(experienceFixture({reuse:undefined}));delete h.state.data.virtual_plant.flow.reuse_lpm;
await h.experienceNext();assert.equal(experienceWrites.length,0);assert.equal(nextState().id,'waiting');tests++;

// Automatic presentation uses the actual app orchestration and iframe message
// handler, with an explicit clock. It is not historical replay autoplay.
function resetPresentation(fixture=experienceFixture()){
  h.stopPresentation();dom.hidden=false;node('#experience-details').open=false;
  h.state.page='plant';h.state.connected=true;h.applyState(fixture);
  syntheticNow+=1000;experienceWrites.length=0;sceneMessages.length=0;
  fakeApi.state=async()=>experienceFixture();
}
function sceneEvent(type,extra={},event={}){
  onMessage({origin:locationFixture.origin,source:sceneWindow,data:{type,...extra},...event});
}
function settleCamera(){sceneEvent('mawrid:camera-settled',{id:WATER_JOURNEY[h.presenter.index].id,requestId:h.cameraRequest});}
resetPresentation();await h.startPresentation();
assert.equal(h.presenter.status,'playing');assert.equal(h.presenter.index,0);assert(h.presenter.waitingCamera);
assert.equal(experienceWrites.length,0);assert.equal(h.state.autoplay,false);
const startCameraRequest=h.cameraRequest;
assert.equal(sceneMessages.at(-1).payload.camera,'focus');
assert.equal(sceneMessages.at(-1).payload.id,'collection');
assert.equal(sceneMessages.at(-1).payload.requestId,startCameraRequest);
const beforeCameraRead=h.presenter.remainingMs;syntheticNow+=2000;h.tickPresentation();
assert(h.presenter.waitingCamera);assert.equal(h.presenter.remainingMs,beforeCameraRead);tests++;

// An acknowledgement is accepted only from the current same-origin iframe,
// for the current camera request and the stage that is actually displayed.
for(const [extra,event] of [
  [{id:'collection',requestId:startCameraRequest},{origin:'https://other.example'}],
  [{id:'collection',requestId:startCameraRequest},{source:{}}],
  [{id:'collection',requestId:startCameraRequest-1},{}],
  [{id:'media',requestId:startCameraRequest},{}],
]){sceneEvent('mawrid:camera-settled',extra,event);assert(h.presenter.waitingCamera);}
settleCamera();assert(!h.presenter.waitingCamera);assert.equal(h.presenter.remainingMs,beforeCameraRead);
syntheticNow+=5000;h.tickPresentation();assert.equal(h.presenter.remainingMs,beforeCameraRead-5000);
assert.equal(experienceWrites.length,0);tests++;

// Manual pause freezes only the reading clock. Resume retains the same stage
// and remaining time but waits for its newly requested camera focus.
const atPause=h.presenter.remainingMs;h.pausePresentation();assert.equal(h.presenter.status,'paused');
syntheticNow+=50000;h.tickPresentation();assert.equal(h.presenter.remainingMs,atPause);
h.resumePresentation();assert.equal(h.presenter.status,'playing');assert(h.presenter.waitingCamera);
assert(h.cameraRequest>startCameraRequest);assert.equal(h.presenter.remainingMs,atPause);
sceneEvent('mawrid:camera-settled',{id:'collection',requestId:startCameraRequest});assert(h.presenter.waitingCamera);
settleCamera();syntheticNow+=1000;h.tickPresentation();assert.equal(h.presenter.remainingMs,atPause-1000);
assert.equal(experienceWrites.length,0);tests++;

resetPresentation(base);
fakeApi.createSession=async(sourceId,ack)=>{
  experienceWrites.push({kind:'session',sourceId,ack});return experienceFixture();
};
await h.startPresentation();
assert.deepEqual(experienceWrites,[{kind:'session',sourceId:'virtual_plant',ack:true}]);
assert.equal(h.presenter.status,'playing');assert.equal(h.presenter.index,0);
assert.equal(h.presenter.sessionId,'experience-a');tests++;

// Changing the educational stage manually exits automatic mode, avoiding a
// mismatch between the clock's stage and the stage shown by the guide.
for(const pausedMode of [false,true]){
  resetPresentation();await h.startPresentation();settleCamera();
  if(pausedMode)h.pausePresentation();
  await h.experienceNext();
  assert.equal(h.state.guideUi.journeyIndex,1);assert.equal(h.presenter.status,'idle');
  assert.equal(experienceWrites.length,0);h.resumePresentation();assert.equal(h.presenter.status,'idle');
}
resetPresentation();await h.startPresentation();settleCamera();
syntheticNow+=h.presenter.remainingMs;h.tickPresentation();settleCamera();h.pausePresentation();
assert.equal(h.state.guideUi.journeyIndex,1);h.moveJourney('previous');
assert.equal(h.state.guideUi.journeyIndex,0);assert.equal(h.presenter.status,'idle');
assert.equal(experienceWrites.length,0);tests++;

// Reading all eight stages does not trigger the manual sensor-fault button,
// issue any other plant command, or restart the presentation after completion.
resetPresentation();await h.startPresentation();
for(let index=0;index<WATER_JOURNEY.length;index++){
  assert.equal(h.presenter.index,index);assert.equal(h.state.guideUi.journeyIndex,index);
  assert(h.presenter.waitingCamera);settleCamera();
  const duration=h.presenter.remainingMs;assert.equal(duration,readingDuration(WATER_JOURNEY[index]));
  syntheticNow+=duration-1;h.tickPresentation();assert.equal(h.presenter.remainingMs,1);
  syntheticNow+=1;h.tickPresentation();
  if(index<7){assert.equal(h.presenter.index,index+1);assert(h.presenter.waitingCamera);assert(h.presenter.remainingMs>=20000);}
}
assert.equal(h.presenter.status,'complete');assert.equal(h.presenter.index,7);
assert.equal(h.state.data.virtual_plant.fault,'none');assert.equal(experienceWrites.length,0);
assert.equal(sceneMessages.at(-1).payload.camera,'overview');
syntheticNow+=1000000;h.tickPresentation();assert.equal(h.presenter.status,'complete');assert.equal(h.presenter.index,7);
assert.equal(experienceWrites.length,0);tests++;

// Explicit automatic start on a paused, otherwise normal plant may resume
// its clock once; it must not clear faults, change speed or reset a hold.
resetPresentation(experienceFixture({status:'paused',running:false}));
fakeApi.plantControl=captureControl(experienceFixture());await h.startPresentation();
assert.deepEqual(experienceWrites,[{kind:'control',control:{running:true}}]);
assert.equal(h.presenter.status,'playing');assert.equal(h.presenter.index,0);tests++;

for(const blocked of [
  experienceFixture({hold:true,status:'paused',running:false}),
  experienceFixture({fault:'sensor_dropout',valve:'closed',reuse:0,safety:'HOLD'}),
  experienceFixture({mode:'backwash'}),
  experienceFixture({safety:'HOLD',valve:'closed',reuse:0}),
]){
  resetPresentation(blocked);await assert.rejects(h.startPresentation(),/التشغيل الاعتيادي/);
  assert.equal(h.presenter.status,'idle');assert.equal(experienceWrites.length,0);
}
resetPresentation();h.state.connected=false;await assert.rejects(h.startPresentation(),/التشغيل الاعتيادي/);
assert.equal(experienceWrites.length,0);tests++;

// A pending explicit resume cannot be duplicated by a rapid second start.
resetPresentation(experienceFixture({status:'paused',running:false}));
const pendingAuto=deferred();fakeApi.plantControl=control=>{
  experienceWrites.push({kind:'control',control:JSON.parse(JSON.stringify(control))});return pendingAuto.promise;
};
const autoStarting=h.startPresentation();await settle();await assert.rejects(h.startPresentation(),/انتظر اكتمال/);
assert.equal(experienceWrites.length,1);pendingAuto.resolve(experienceFixture());await autoStarting;
assert.equal(h.presenter.status,'playing');assert.equal(experienceWrites.length,1);tests++;

// Missing camera/WebGL acknowledgement falls back to the textual journey
// after eight seconds, without consuming any of that stage's reading time.
resetPresentation();await h.startPresentation();const fallbackDuration=h.presenter.remainingMs;
syntheticNow+=7999;h.tickPresentation();assert(h.presenter.waitingCamera);
syntheticNow+=1;h.tickPresentation();assert(!h.presenter.waitingCamera);
assert.equal(h.presenter.remainingMs,fallbackDuration);assert.equal(h.state.guideUi.presentation.textOnly,true);
syntheticNow+=1000;h.tickPresentation();assert.equal(h.presenter.remainingMs,fallbackDuration-1000);
assert.equal(experienceWrites.length,0);tests++;

// Camera manipulation is an explicit request to inspect. Untrusted events
// cannot pause the presentation; a real interaction preserves reading time.
resetPresentation();await h.startPresentation();settleCamera();syntheticNow+=4000;h.tickPresentation();
const cameraRemaining=h.presenter.remainingMs;
sceneEvent('mawrid:camera-interaction',{}, {origin:'https://other.example'});assert.equal(h.presenter.status,'playing');
sceneEvent('mawrid:camera-interaction');assert.equal(h.presenter.status,'paused');
assert.equal(h.presenter.reason,'camera');assert.equal(h.presenter.remainingMs,cameraRemaining);
syntheticNow+=50000;h.tickPresentation();assert.equal(h.presenter.remainingMs,cameraRemaining);
assert.equal(experienceWrites.length,0);tests++;

// Details and navigation pause without an automatic restart when closed or
// revisited. The explicit Resume control is required to continue.
resetPresentation();await h.startPresentation();settleCamera();await click('experience-details');
assert(node('#experience-details').open);assert.equal(h.presenter.status,'paused');assert.equal(h.presenter.reason,'details');
await click('experience-close');assert(!node('#experience-details').open);assert.equal(h.presenter.status,'paused');
h.resumePresentation();settleCamera();context.location.hash='#components';h.route();
assert.equal(h.presenter.status,'paused');assert.equal(h.presenter.reason,'navigation');
context.location.hash='#plant';h.route();assert.equal(h.presenter.status,'paused');
assert.equal(experienceWrites.length,0);tests++;

resetPresentation();await h.startPresentation();settleCamera();syntheticNow+=3000;
dom.hidden=true;documentListeners.get('visibilitychange')();
assert.equal(h.presenter.status,'paused');assert.equal(h.presenter.reason,'hidden');
const hiddenRemaining=h.presenter.remainingMs;syntheticNow+=100000;
dom.hidden=false;documentListeners.get('visibilitychange')();await settle();h.tickPresentation();
assert.equal(h.presenter.status,'paused');assert.equal(h.presenter.remainingMs,hiddenRemaining);
assert.equal(experienceWrites.length,0);tests++;

for(const interruption of [
  experienceFixture({fault:'sensor_dropout',valve:'closed',reuse:0,safety:'HOLD'}),
  experienceFixture({hold:true,status:'paused',running:false}),
  experienceFixture({status:'paused',running:false}),
]){
  resetPresentation();await h.startPresentation();settleCamera();syntheticNow+=3000;
  h.applyState(interruption);assert.equal(h.presenter.status,'paused');assert.equal(h.presenter.reason,'plant');
  const remaining=h.presenter.remainingMs;h.resumePresentation();assert.equal(h.presenter.status,'paused');
  h.applyState(experienceFixture());syntheticNow+=100000;h.tickPresentation();
  assert.equal(h.presenter.status,'paused');assert.equal(h.presenter.remainingMs,remaining);
  assert.equal(experienceWrites.length,0);
}
resetPresentation();await h.startPresentation();settleCamera();h.state.connected=false;h.render();
assert.equal(h.presenter.status,'paused');assert.equal(h.presenter.reason,'connection');
h.state.connected=true;h.render();assert.equal(h.presenter.status,'paused');assert.equal(experienceWrites.length,0);tests++;

// Explicitly restoring a fault is allowed, but it cannot automatically resume
// the interrupted explanation or discard the remaining reading time.
resetPresentation();await h.startPresentation();settleCamera();syntheticNow+=3000;h.tickPresentation();
const beforeFaultRemaining=h.presenter.remainingMs;h.applyState(dropout);
assert.equal(h.presenter.status,'paused');fakeApi.plantControl=captureControl(experienceFixture());
await h.experienceNext();assert.equal(h.presenter.status,'paused');
assert.equal(h.presenter.remainingMs,beforeFaultRemaining);assert.equal(h.presenter.index,0);
assert.deepEqual(experienceWrites,[{kind:'control',control:{fault:'none',mode:'auto',speed:1,running:true}}]);
h.resumePresentation();assert.equal(h.presenter.status,'playing');assert(h.presenter.waitingCamera);
assert.equal(h.presenter.remainingMs,beforeFaultRemaining);settleCamera();assert(!h.presenter.waitingCamera);tests++;

resetPresentation();await h.startPresentation();settleCamera();h.applyState(experienceFixture({sessionId:'replacement'}));
assert.equal(h.presenter.status,'idle');assert.equal(h.presenter.sessionId,null);
assert.equal(experienceWrites.length,0);
await h.startPresentation();settleCamera();h.stopPresentation();const stoppedRequest=h.cameraRequest;
assert.equal(h.presenter.status,'idle');assert.equal(h.state.guideUi.presentation.status,'idle');
sceneEvent('mawrid:camera-settled',{id:'collection',requestId:stoppedRequest-1});
syntheticNow+=1000000;h.tickPresentation();assert.equal(h.presenter.status,'idle');assert.equal(experienceWrites.length,0);tests++;

const contract=JSON.parse(await fs.readFile(new URL('../CONTRACT.json',import.meta.url),'utf8'));
for (const source of contract.sources) for (const item of source.channels) assert.equal(typeof item.unit,'string');
assert.equal(contract.sources[0].channels.find(c=>c.key==='Turb').unit,'FNU');
assert.equal(contract.sources[0].channels.find(c=>c.key==='Cond').unit,'S/m'); tests++;
assert.equal(contract.version,5);assert.equal(contract.guided_application.default_route,'#start');tests++;
console.log(`${tests} frontend checks PASS; actual guide module and app queue/event handlers with synthetic fixtures only; no browser-rendering/accessibility claim, network or persisted application mutations.`);
