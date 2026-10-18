import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {BrowserPlant, FAULTS, sceneSnapshot} from './src/model.js';
const cwd = fileURLToPath(new URL('..',import.meta.url));
const python = process.env.PYTHON || 'python';
const cases = [
  {name:'normal matched inventory',actions:[{step:0},{step:60},{step:300},{step:12.5}]},
  ...FAULTS.map(fault => ({name:fault,actions:[{step:60},{control:{fault}},{step:300},{control:{fault:'none'}},{step:60}]})),
  {name:'backwash empties treated inventory',actions:[{control:{mode:'backwash'}},{step:300},{step:300},{step:300},{step:300},{step:300},{step:300},{step:300},{control:{mode:'auto'}},{step:60}]},
  {name:'standby and power loss',actions:[{control:{mode:'standby'}},{step:300},{control:{fault:'power_loss'}},{step:300},{control:{mode:'auto',fault:'none'}},{step:20}]},
  {name:'manual hold persists after fault clearing',actions:[{hold:true},{control:{fault:'turbidity'}},{step:300},{control:{fault:'none'}},{step:30},{hold:false},{step:30}]},
  {name:'speed is metadata only',actions:[{control:{speed:30}},{step:1},{control:{speed:1}},{step:1},{control:{speed:10}},{step:1}]},
];
function compare(actual, expected, field = '') {
  if (field === 'source') {assert.equal(actual,'browser_simulation'); assert.equal(expected,'virtual_plant'); return;}
  if (field === 'timestamp') {assert.equal(Date.parse(actual),Date.parse(expected)); return;}
  if (typeof actual === 'number') {assert.ok(Math.abs(actual-expected) <= 1e-8 * Math.max(1,Math.abs(expected)),`${field}: ${actual} != ${expected}`); return;}
  if (actual && typeof actual === 'object') {for (const [key,value] of Object.entries(actual)) compare(value,expected[key],field ? `${field}.${key}` : key); return;}
  assert.deepEqual(actual,expected,field);
}
test('browser inventory and conservative rules match Python at representative snapshots', t => {
  const code = `import sys,json\nsys.path.insert(0,'mawrid-system/server')\nfrom plant import PlantSimulator\ncases=json.load(sys.stdin)\nout=[]\nfor case in cases:\n p=PlantSimulator('2026-10-18T09:00:00Z')\n snaps=[p.snapshot()]\n for action in case['actions']:\n  if 'control' in action:p.set_control(action['control'])\n  if 'hold' in action:p.set_manual_hold(action['hold'])\n  if 'step' in action:p.step(action['step'])\n  snaps.append(p.snapshot())\n out.append(snaps)\nprint(json.dumps(out,ensure_ascii=False))`;
  const result = spawnSync(python,['-c',code],{cwd,input:JSON.stringify(cases),encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'},maxBuffer:4*1024*1024});
  assert.equal(result.status,0,`${python} parity reference failed: ${result.stderr}`);
  const expected = JSON.parse(result.stdout); let count = 0;
  cases.forEach((item,index) => {const plant = new BrowserPlant(); compare(plant.snapshot(),expected[index][0]); count++; item.actions.forEach((action,step) => {if (action.control) plant.control(action.control); if ('hold' in action) plant.control({manualHold:action.hold}); if ('step' in action) plant.step(action.step); compare(plant.snapshot(),expected[index][step+1]); count++;});});
  assert.ok(count >= 69,`Only ${count} snapshots checked`);
  t.diagnostic(`${count} Python/browser snapshots compared; floating-point tolerance 1e-8`);
});
test('faults close virtual feedback and stop reuse; clearing restores only the virtual rule',() => {
  for (const fault of FAULTS.filter(f => f !== 'none')) {const plant = new BrowserPlant(); plant.control({fault}); const s = plant.step(60); assert.equal(s.safety.state,'HOLD',fault); assert.equal(s.equipment.irrigation_feedback,'closed',fault); assert.equal(s.flow.reuse_lpm,0,fault); assert.equal(s.volumes.reuse_liters,0,fault); plant.control({fault:'none'}); assert.equal(plant.snapshot().safety.state,'REUSE');}
});
test('scene preserves missing reading and separate valve command / feedback',() => {
  const plant = new BrowserPlant(); plant.control({fault:'sensor_dropout'}); assert.equal(sceneSnapshot(plant.snapshot()).readings.chlorine,null); plant.control({fault:'valve_stuck'}); const view = sceneSnapshot(plant.snapshot()); assert.equal(view.irrigationCommand,'open'); assert.equal(view.irrigationFeedback,'closed'); assert.equal(view.flows.reuse,0);
});
test('long deterministic sequence conserves water and stock never becomes negative',() => {
  const plant = new BrowserPlant(); for (let i = 0; i < 1500; i++) {plant.control({fault:FAULTS[i % FAULTS.length],mode:i % 4 === 0 ? 'backwash' : 'auto'}); const s = plant.step((i * 17) % 301); assert.ok(s.tanks.raw.liters >= 0 && s.tanks.raw.liters <= 5000); assert.ok(s.tanks.treated.liters >= 0 && s.tanks.treated.liters <= 5000); assert.ok(Math.abs(s.volumes.balance_error_liters) < 1e-7);}
});
test('invalid controls and steps reject atomically and snapshot is detached',() => {
  const plant = new BrowserPlant(), before = plant.snapshot(); assert.throws(() => plant.control({fault:'unknown'})); assert.throws(() => plant.control({speed:100})); for (const dt of [-1,301,NaN,Infinity,true]) assert.throws(() => plant.step(dt)); compare(plant.snapshot(),{...before,source:'virtual_plant'}); const detached = plant.snapshot(); detached.tanks.raw.liters = -1; assert.equal(plant.snapshot().tanks.raw.liters,3000);
});
