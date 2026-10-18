import test from 'node:test';
import assert from 'node:assert/strict';
import {adaptState, presentation} from './adapter.js';
import {StatePoller} from './poller.js';

// Independent synthetic contract review; no server, browser, model or sensors.
const id='12345678-1234-4234-8234-123456789abc';
const nextId='22345678-1234-4234-8234-123456789abc';
function fixture() {
  return {app:{hardware_connected:false}, source:{id:'virtual_plant',kind:'digital_twin'},
    session:{id,status:'ready'}, alarms:[{session_id:id,title:'current'}, {session_id:nextId,title:'old'}],
    virtual_plant:{source:'virtual_plant',virtual:true,hardware:false,session_id:id,running:true,
      timestamp:'2020-01-01T00:00:00Z',elapsed_seconds:0,mode:'auto',fault:'none',speed:1,
      validity:{turbidity:true,ph:true,p1_bar:true,p2_bar:true},
      chans:{turbidity:0,ph:7.2,p1_bar:2,p2_bar:1},
      tanks:{raw:{liters:0,capacity_liters:100,level_percent:0}},
      equipment:{power:true,irrigation_command:'closed',irrigation_feedback:'open'},
      flow:{reuse_lpm:0},safety:{state:'HOLD',reasons:['feedback mismatch'],reason_codes:['MISMATCH']}}};
}
const response = data => ({ok:true,json:async()=>data});
const settle = () => new Promise(resolve=>setImmediate(resolve));
function harness() {
  const calls=[],emissions=[],timers=new Map();let sequence=0,clock=100;
  const fetchState=options=>new Promise((resolve,reject)=>calls.push({options,resolve,reject}));
  const poller=new StatePoller({fetchState,onState:s=>emissions.push(s),now:()=>clock,
    schedule:(fn,delay)=>{const token=++sequence;timers.set(token,{fn,delay});return token;},
    cancel:token=>timers.delete(token)});
  return {poller,calls,emissions,timers,setClock:v=>{clock=v;}};
}

test('only explicit virtual, matching-session state is accepted',()=>{
  assert.ok(adaptState(fixture()));
  const mutations=[d=>d.source.id='telemetry',d=>d.source.kind='public_replay',
    d=>d.app.hardware_connected=true,d=>delete d.app.hardware_connected,
    d=>d.virtual_plant.hardware=true,d=>d.virtual_plant.virtual=false,
    d=>d.virtual_plant.session_id=nextId,d=>d.session.status='idle',
    d=>d.virtual_plant=null,d=>d.session.id='not-a-uuid'];
  for(const mutate of mutations){const d=fixture();mutate(d);assert.equal(adaptState(d),null);}
});

test('zero is observed, missing or invalid evidence is unavailable; old alarms are excluded',()=>{
  const d=fixture();d.virtual_plant.chans.ph=Infinity;
  d.virtual_plant.chans.chlorine=.3; // no validity assertion is not a valid sample
  d.virtual_plant.flow.treatment_lpm=-1;
  const s=adaptState(d);
  assert.equal(s.readings.turbidity,0);assert.equal(s.readings.ph,null);
  assert.equal(s.readings.chlorine,null);assert.equal(s.flows.treatment,null);
  assert.equal(s.tanks.raw.liters,0);assert.equal(s.tanks.treated.liters,null);
  assert.equal(s.deltaMedia,1);assert.equal(s.deltaCarbon,null);
  assert.equal(s.irrigationCommand,'closed');assert.equal(s.irrigationFeedback,'open');
  assert.deepEqual(s.alarms.map(a=>a.title),['current']);
});

test('wall transport freshness never uses virtual timestamp; pause and failure cannot animate',()=>{
  const d=fixture();d.session.status='paused';
  let snapshot=adaptState(d);
  let p=presentation({connection:'connected',snapshot,lastSuccessAt:100},101);
  assert.equal(p.phase,'paused');assert.equal(p.fresh,true);assert.equal(p.motion,false);
  d.session.status='failed';snapshot=adaptState(d);
  assert.equal(presentation({connection:'connected',snapshot,lastSuccessAt:100},101).phase,'failed');
  d.session.status='ready';snapshot=adaptState(d);
  assert.equal(presentation({connection:'connected',snapshot,lastSuccessAt:100},6601).motion,false);
  assert.equal(presentation({connection:'connected',snapshot,lastSuccessAt:100},99).fresh,false);
  assert.equal(presentation({connection:'disconnected',snapshot,lastSuccessAt:100},101).motion,false);
});

test('one read-only GET in flight and no auto-start/control request',async()=>{
  const h=harness();h.poller.start();h.poller.start();await h.poller.poll();
  assert.equal(h.calls.length,1);
  const options=h.calls[0].options;
  assert.equal(options.method,'GET');assert.equal(options.body,undefined);
  assert.equal(options.cache,'no-store');assert.equal(options.credentials,'same-origin');
  h.calls[0].resolve(response(fixture()));await settle();
  assert.equal(h.poller.state.snapshot.sessionId,id);h.poller.stop();
});

test('source switch clears snapshot and subsequent session replaces rather than merges it',async()=>{
  const h=harness();h.poller.start();h.calls[0].resolve(response(fixture()));await settle();
  const switched=fixture();switched.source.id='telemetry';switched.virtual_plant=null;
  const second=h.poller.poll();h.calls[1].resolve(response(switched));await second;
  assert.equal(h.poller.state.snapshot,null);assert.equal(h.poller.state.reset,true);
  const fresh=fixture();fresh.session.id=nextId;fresh.virtual_plant.session_id=nextId;
  fresh.virtual_plant.chans={};fresh.virtual_plant.validity={};
  const third=h.poller.poll();h.calls[2].resolve(response(fresh));await third;
  assert.equal(h.poller.state.snapshot.sessionId,nextId);
  assert.equal(h.poller.state.snapshot.readings.turbidity,null);h.poller.stop();
});

test('stop/restart rejects late old generation even if transport ignores abort',async()=>{
  const h=harness();h.poller.start();h.poller.stop();h.poller.start();
  h.calls[0].resolve(response(fixture()));await settle();
  assert.equal(h.poller.state.snapshot,null);assert.equal(h.calls.length,1);
  const pending=h.poller.poll();const fresh=fixture();fresh.session.id=nextId;fresh.virtual_plant.session_id=nextId;
  h.calls[1].resolve(response(fresh));await pending;
  assert.equal(h.poller.state.snapshot.sessionId,nextId);h.poller.stop();
});

test('deadline rejects late successful payload and holds a non-live last snapshot',async()=>{
  const h=harness();h.poller.start();h.calls[0].resolve(response(fixture()));await settle();
  const pending=h.poller.poll();
  const deadline=[...h.timers.values()].find(t=>t.delay===4500);assert.ok(deadline);deadline.fn();
  assert.equal(h.poller.state.connection,'disconnected');
  assert.equal(presentation(h.poller.state,100).motion,false);
  const late=fixture();late.virtual_plant.elapsed_seconds=999;
  h.calls[1].resolve(response(late));await pending;
  assert.equal(h.poller.state.snapshot.elapsedSeconds,0);h.poller.stop();
});

test('HTTP and JSON failure cannot publish fresh state',async()=>{
  const h=harness();h.poller.start();h.calls[0].resolve({ok:false});await settle();
  assert.equal(h.poller.state.connection,'disconnected');assert.equal(h.poller.state.lastSuccessAt,null);
  const pending=h.poller.poll();h.calls[1].resolve({ok:true,json:async()=>{throw Error('malformed');}});await pending;
  assert.equal(h.poller.state.snapshot,null);assert.equal(h.poller.state.lastSuccessAt,null);h.poller.stop();
});
