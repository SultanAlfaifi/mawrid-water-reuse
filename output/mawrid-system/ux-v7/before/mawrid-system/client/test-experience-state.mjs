/* Pure synthetic state tests: no HTTP, persistence, simulation or ML calls. */
import assert from 'node:assert/strict';
import { experienceState } from './experience-state.js';

let count = 0;
function check(name, test) { test(); count++; console.log(`PASS ${name}`); }
const base = () => ({
  source: {kind: 'digital_twin', id: 'virtual_plant'},
  session: {id: 'session-a', status: 'ready'},
  overview: {manual_hold: false},
  virtual_plant: {
    session_id: 'session-a', running: true, manual_hold: false,
    fault: 'none', mode: 'auto',
    flow: {reuse_lpm: 8, treatment_lpm: 10},
    equipment: {irrigation_valve: 'open'},
    safety: {state: 'REUSE', reasons: []},
  },
});
const completed = {experienceSession: 'session-a', experienceRestored: true};
const state = (data, ui = {}) => experienceState(data, ui, true);

check('loading offers no command', () => {
  const s = experienceState(null, completed, false);
  assert.equal(s.id, 'loading'); assert.equal(s.action, null);
});
check('disconnect takes priority over all saved plant and completion states', () => {
  const d = base(); d.virtual_plant.manual_hold = true;
  const s = experienceState(d, completed, false);
  assert.equal(s.id, 'disconnected'); assert.equal(s.action, null);
  assert.match(s.text, /آخر حالة/); assert.notEqual(s.tone, 'good');
});
check('inactive virtual plant starts rather than inheriting UI completion', () => {
  const s = state({}, completed); assert.equal(s.id, 'start'); assert.equal(s.action, 'start');
  assert.equal(s.label, 'تشغيل المحطة'); assert.equal(s.step, 0);
});
check('wrong source and mismatched session do not inherit saved virtual success or hold', () => {
  for (const edit of [d => {d.source.kind = 'public_replay';}, d => {d.source.id = 'other';}, d => {d.session.id = 'other';}]) {
    const d = base(); d.virtual_plant.manual_hold = true; edit(d);
    assert.equal(state(d, completed).id, 'start');
  }
});
check('snapshot manual hold precedes fault, pause and completion', () => {
  const d = base(); Object.assign(d.virtual_plant, {manual_hold: true, fault: 'sensor_dropout', running: false});
  d.session.status = 'paused';
  const s = state(d, completed); assert.equal(s.id, 'manual-hold'); assert.equal(s.action, 'release');
  assert.match(s.label, /إلغاء الإيقاف اليدوي/); assert.notEqual(s.tone, 'good');
});
check('global explicit hold can be released before a virtual session exists', () => {
  const s = state({overview: {manual_hold: true}}, completed);
  assert.equal(s.action, 'release'); assert.equal(s.step, 0);
});
check('textual reasons and hidden settings do not invent a manual-hold boolean', () => {
  const d = base(); d.settings = {_manual_hold: true}; d.overview.reasons = ['إيقاف برمجي يدوي مفعّل'];
  assert.equal(state(d).id, 'normal');
});
check('confirmed sensor dropout explains irrigation stopping while treatment can continue', () => {
  const d = base(); d.virtual_plant.fault = 'sensor_dropout'; d.virtual_plant.flow.reuse_lpm = 0;
  d.virtual_plant.equipment.irrigation_valve = 'closed'; d.virtual_plant.safety.state = 'HOLD';
  const s = state(d, completed); assert.equal(s.id, 'fault'); assert.equal(s.action, 'restore');
  assert.equal(s.step, 2); assert.match(s.text, /أُغلق الري/); assert.match(s.text, /قد تستمر المعالجة/);
  assert.equal(s.label, 'إزالة العطل ومتابعة التشغيل');
});
check('dropout with unconfirmed closure cannot claim successful protective closure', () => {
  for (const alter of [d => {}, d => {d.virtual_plant.equipment.irrigation_valve = 'closed';}, d => {delete d.virtual_plant.flow.reuse_lpm;}]) {
    const d = base(); d.virtual_plant.fault = 'sensor_dropout'; alter(d);
    const s = state(d, completed); assert.equal(s.id, 'fault'); assert.match(s.text, /لم تتأكد/);
    assert.doesNotMatch(s.text, /فأُغلق/);
  }
});
check('all faults take priority over completion and paused state', () => {
  for (const fault of ['turbidity', 'clogging', 'power_loss', 'valve_stuck']) {
    const d = base(); Object.assign(d.virtual_plant, {fault, running: false}); d.session.status = 'paused';
    d.virtual_plant.safety.reasons = ['سبب العطل من الخدمة'];
    const s = state(d, completed); assert.equal(s.action, 'restore'); assert.equal(s.step, 2);
    assert.match(s.text, /سبب العطل من الخدمة/); assert.notEqual(s.id, 'done');
  }
});
check('standby and backwash offer return to ordinary operation', () => {
  for (const mode of ['standby', 'backwash']) {
    const d = base(); d.virtual_plant.mode = mode;
    const s = state(d, completed); assert.equal(s.id, 'mode'); assert.equal(s.action, 'restore');
    assert.equal(s.label, 'متابعة التجربة'); assert.notEqual(s.tone, 'good');
  }
});
check('paused state cannot be completed by a saved UI flag', () => {
  for (const edit of [d => {d.virtual_plant.running = false;}, d => {d.session.status = 'paused';}]) {
    const d = base(); edit(d);
    const s = state(d, completed); assert.equal(s.id, 'paused'); assert.equal(s.action, 'resume'); assert.equal(s.step, 0);
  }
});
check('unavailable operating fields cannot look like normal or finished operation', () => {
  for (const key of ['running', 'mode', 'fault']) {
    const d = base(); delete d.virtual_plant[key];
    const s = state(d, completed); assert.equal(s.id, 'unavailable'); assert.equal(s.action, null);
  }
});
check('hold or missing safety state waits and preserves server reasons', () => {
  for (const safety of [{state: 'HOLD', reasons: ['المخزون غير كافٍ']}, {}, undefined]) {
    const d = base(); d.virtual_plant.safety = safety;
    const s = state(d, completed); assert.equal(s.id, 'waiting'); assert.equal(s.action, null);
    assert.notEqual(s.tone, 'good');
    if (safety?.reasons) assert.match(s.text, /المخزون غير كافٍ/);
  }
});
check('closed or missing valve feedback cannot prove success', () => {
  for (const valve of ['closed', 'unavailable', undefined]) {
    const d = base(); d.virtual_plant.equipment.irrigation_valve = valve;
    assert.equal(state(d, completed).id, 'waiting'); assert.equal(state(d, completed).action, null);
  }
});
check('zero negative missing string and nonfinite reuse flow cannot prove success', () => {
  for (const flow of [0, -1, null, undefined, '8', NaN, Infinity]) {
    const d = base(); d.virtual_plant.flow.reuse_lpm = flow;
    assert.equal(state(d, completed).id, 'waiting');
  }
});
check('ordinary operation offers one sensor test', () => {
  const s = state(base()); assert.equal(s.id, 'normal'); assert.equal(s.action, 'test');
  assert.equal(s.label, 'جرّب انقطاع الحساس'); assert.equal(s.step, 1);
});
check('completion needs this exact session and boolean restoration flag', () => {
  for (const ui of [{}, {experienceSession: 'old', experienceRestored: true}, {experienceSession: 'session-a', experienceRestored: false}, {experienceSession: 'session-a', experienceRestored: 'true'}]) {
    assert.equal(state(base(), ui).id, 'normal');
  }
  const s = state(base(), completed); assert.equal(s.id, 'done'); assert.equal(s.step, 3); assert.equal(s.action, 'test');
});
check('failed sessions restart rather than issuing an invalid resume or release', () => {
  const d = base(); d.session.status = 'failed'; d.virtual_plant.manual_hold = true;
  const s = state(d, completed); assert.equal(s.id, 'start'); assert.equal(s.action, 'start'); assert.match(s.text, /جلسة جديدة/);
});
check('function is pure and always returns the documented fields', () => {
  const d = base(), ui = {...completed}, before = JSON.stringify({d, ui});
  const a = state(d, ui), b = state(d, ui); assert.deepEqual(a, b);
  assert.deepEqual(Object.keys(a), ['id', 'title', 'text', 'action', 'label', 'tone', 'step']);
  assert.equal(JSON.stringify({d, ui}), before);
});
console.log(`${count} experience state checks PASS; synthetic only, no mutations.`);
