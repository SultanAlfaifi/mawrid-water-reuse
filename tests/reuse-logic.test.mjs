import test from 'node:test';
import assert from 'node:assert/strict';
import { DEMO_NORMAL, evaluateReuse, evaluateDemo } from '../web/src/reuse-logic.js';

test('only all known valid conditions permit the illustrative route', () => {
  assert.equal(evaluateReuse(DEMO_NORMAL).permitted, true);
  assert.equal(evaluateReuse({}).permitted, false);
  for (const key of Object.keys(DEMO_NORMAL)) {
    const changed = { ...DEMO_NORMAL };
    delete changed[key];
    assert.equal(evaluateReuse(changed).permitted, false, `missing ${key}`);
    assert.equal(evaluateReuse({ ...DEMO_NORMAL, [key]: !DEMO_NORMAL[key] }).permitted, false, `invalid ${key}`);
  }
});

test('every selectable fault closes the illustrative reuse path', () => {
  for (const mode of ['sensor', 'disinfection', 'power', 'storage', 'unknown']) {
    const state = evaluateDemo(mode);
    assert.equal(state.permitted, false);
    assert.equal(state.valve, 'CLOSED');
    assert.equal(state.route, 'HOLD');
    assert.ok(state.reasons.length);
  }
  assert.equal(evaluateDemo('normal').permitted, true);
});
