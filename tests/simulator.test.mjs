import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createSimulation, stepSimulation, injectFault, clearFaults, getMetrics,
  getEconomics, buildReportData, buildControllerInput, DEFAULT_CONFIG, FAULTS
} from '../web/src/simulator-engine.js';
import { evaluateReuse } from '../web/src/reuse-logic.js';

const WEEK_STEPS = 7 * 24 * 60 / 5;
const finish = sim => stepSimulation(sim, WEEK_STEPS);

function assertBalance(sim, context = '') {
  const metrics = getMetrics(sim);
  assert.ok(metrics.balanceErrorPct < 0.1, `${context}: balance ${metrics.balanceErrorPct}%`);
  assert.ok(Math.abs(metrics.collected - metrics.irrigated - metrics.diverted - metrics.backwash - metrics.overflow - metrics.stored) < 1e-6);
}

test('seven days at five-minute intervals are deterministic and finish', () => {
  const a = finish(createSimulation());
  const b = finish(createSimulation());
  assert.equal(a.history.length, WEEK_STEPS);
  assert.equal(a.minute, 7 * 24 * 60);
  assert.equal(a.done, true);
  assert.deepEqual(a.history, b.history);
  assert.deepEqual(getMetrics(a), getMetrics(b));
  stepSimulation(a, 100);
  assert.equal(a.history.length, WEEK_STEPS);
  assert.ok(getMetrics(a).irrigated > 0, 'normal operation must actually irrigate');
  assertBalance(a);
});

test('power loss immediately commands CLOSED for every operating route and prevents release', () => {
  for (const preset of ['mosque', 'university', 'haram']) {
    for (const start of [0, 62, 75, 180, 400]) {
      const sim = createSimulation({ preset });
      stepSimulation(sim, start);
      if (start === 180) { injectFault(sim, 'contamination'); stepSimulation(sim, 40); }
      injectFault(sim, 'power');
      assert.equal(sim.decision.valve, 'CLOSED');
      assert.equal(sim.valveCommand, 'CLOSED');
      assert.equal(sim.pumpsRunning, false);
      const before = sim.totals.irrigated;
      finish(sim);
      assert.equal(sim.totals.irrigated, before);
      assert.equal(getMetrics(sim).unsafeIrrigationCount, 0);
      assertBalance(sim, `${preset}/${start}`);
    }
  }
});

test('final sensor drift is discovered from residuals and ends in quarantine before unsafe release', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 90);
  assert.equal(sim.decision.permitted, true);
  injectFault(sim, 'drift');
  let discovered = false;
  for (let i = 0; i < 72; i++) {
    stepSimulation(sim);
    assert.equal(getMetrics(sim).unsafeIrrigationCount, 0);
    if (sim.sensors.turbidity.confidence < sim.config.limits.confidence) {
      discovered = true;
      assert.equal(sim.decision.permitted, false);
      assert.equal(sim.route, 'HOLD');
      break;
    }
  }
  assert.equal(discovered, true, 'drift must be detected in this scenario');
  assert.ok(sim.maintenance.some(item => item.key.includes('calibration')));
  const detectedStep = sim.step;
  finish(sim);
  assert.ok(sim.history.slice(detectedStep).every(row => row.route !== 'IRRIGATE'), 'a calibration ticket must latch HOLD even if confidence briefly recovers');
  assertBalance(sim);
});

test('all eight fault buttons and simultaneous faults keep independently audited unsafe irrigation at zero', () => {
  for (const preset of ['mosque', 'university', 'haram']) {
    for (const fault of FAULTS) {
      const sim = createSimulation({ preset });
      stepSimulation(sim, 150);
      const inputBefore = sim.totals.collected;
      injectFault(sim, fault.id);
      finish(sim);
      assert.equal(getMetrics(sim).unsafeIrrigationCount, 0, `${preset}/${fault.id}`);
      assert.equal(getMetrics(sim).unsafeIrrigationLitres, 0, `${preset}/${fault.id}`);
      assert.ok(sim.totals.collected > inputBefore, 'test must expose the fault to actual incoming water');
      assertBalance(sim, `${preset}/${fault.id}`);
    }
  }
  const combined = createSimulation({ preset: 'haram' });
  stepSimulation(combined, 80);
  for (const fault of FAULTS) injectFault(combined, fault.id);
  finish(combined);
  assert.equal(getMetrics(combined).unsafeIrrigationCount, 0);
  assertBalance(combined, 'combined');
});

test('AI can only restrict the existing fixed controller; it cannot turn HOLD into REUSE', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 80);
  for (const fault of [null, 'power', 'valve', 'sensor', 'uvFailure']) {
    if (fault) injectFault(sim, fault);
    for (const confidence of [0, 38, 69, 70, 100]) {
      sim.ai.confidence = confidence;
      sim.sensors.ph.confidence = confidence;
      sim.sensors.turbidity.confidence = confidence;
      const base = evaluateReuse(buildControllerInput(sim, false));
      const augmented = evaluateReuse(buildControllerInput(sim, true));
      if (!base.permitted) assert.equal(augmented.permitted, false);
      if (confidence < sim.config.limits.confidence) assert.equal(augmented.permitted, false);
    }
  }
});

test('outlet adapter does not consult final hidden ground truth', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 80);
  const before = buildControllerInput(sim);
  Object.assign(sim.quality.final, { turbidity: 1e6, ph: 14, ecoli: 1e9, dose: 0, intensity: 0 });
  Object.assign(sim.treated.quality, { turbidity: 1e6, ph: 14, ecoli: 1e9, ec: 1e9, dose: 0, intensity: 0 });
  assert.deepEqual(buildControllerInput(sim), before, 'changing audit truth without new instrument readings cannot change controller input');
});

test('the unsafe counter really detects bad water if every measured and model condition is spoofed', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 80);
  // Deliberately break the model's instrument assumptions. This is not one of
  // the claimed faults: it proves the counter is an independent audit, not a
  // literal zero, and the controller is not secretly gated by true E. coli.
  sim.treated.litres = 500;
  sim.treated.observerIntensity = 100;
  sim.treated.observerDose = 60;
  sim.treated.quality.ecoli = 1e9;
  sim.treated.quality.observerEcoliUpper = 0;
  stepSimulation(sim);
  assert.ok(sim.totals.unsafeCount > 0);
});

test('pollution injected between prayers waits for water and causes recycling and diversion', () => {
  const sim = createSimulation();
  stepSimulation(sim, 150); // 12:30, no incoming prayer peak.
  injectFault(sim, 'contamination');
  assert.equal(sim.faults.contamination.pending, true);
  finish(sim);
  assert.equal(sim.faults.contamination.pending, false);
  assert.ok(sim.events.some(item => item.type === 'contamination'));
  assert.ok(sim.history.some(row => row.route === 'REPROCESS'));
  assert.ok(sim.events.some(item => item.type === 'diversion' && item.title.includes('محاولات')));
  assert.equal(getMetrics(sim).unsafeIrrigationCount, 0);
  assertBalance(sim);
});

test('restoring a weak lamp cannot retroactively qualify the old untreated batch', () => {
  const sim = createSimulation();
  stepSimulation(sim, 180);
  injectFault(sim, 'uv');
  stepSimulation(sim, 50);
  const oldIntensity = sim.treated.observerIntensity;
  clearFaults(sim);
  if (sim.treated.litres > 0 && oldIntensity < sim.config.limits.uvIntensity) {
    assert.equal(sim.decision.permitted, false);
  }
  stepSimulation(sim, 20);
  assert.equal(getMetrics(sim).unsafeIrrigationCount, 0);
  assertBalance(sim);
});

test('long power loss and recovery preserves mass and does not release microbially aged stored water', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 100);
  injectFault(sim, 'power');
  stepSimulation(sim, 450);
  assert.ok(sim.totals.diverted > 0, 'stale raw/treated batches must leave via recorded drain');
  clearFaults(sim);
  finish(sim);
  assert.equal(getMetrics(sim).unsafeIrrigationCount, 0);
  assertBalance(sim);
});

test('valve failure isolates flow by stopping pumps and reports a critical alarm', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 80);
  const before = sim.totals.irrigated;
  injectFault(sim, 'valve');
  assert.equal(sim.valveCommand, 'CLOSED');
  assert.equal(sim.valveFeedback, 'STUCK_OPEN');
  assert.equal(sim.pumpsRunning, false);
  assert.ok(sim.events.some(item => item.severity === 'critical'));
  stepSimulation(sim, 100);
  assert.equal(sim.totals.irrigated, before);
  assertBalance(sim);
});

test('demand backwash draws only recovered water and does not hide it in overflow', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 80);
  injectFault(sim, 'clog');
  stepSimulation(sim, 40);
  assert.ok(sim.totals.backwash > 0);
  assert.ok(sim.events.some(item => item.type === 'backwash'));
  assert.ok(sim.maintenance.some(item => item.key === 'sand'));
  assertBalance(sim);
});

test('comparison shares source volumes; commercial system is sized without inventing its treatment performance', () => {
  const sim = finish(createSimulation());
  const metrics = getMetrics(sim);
  assert.ok(metrics.comparison.simple.unsafeIrrigationCount > 0);
  assert.ok(metrics.comparison.simple.irrigated > metrics.irrigated);
  assert.ok(Math.abs(metrics.comparison.simple.irrigated - metrics.collected) < 1e-6);
  assert.equal(metrics.comparison.hydraloop.units, Math.ceil(metrics.comparison.hydraloop.dailyLitres / 720));
  assert.equal(metrics.comparison.hydraloop.footprintM2, metrics.comparison.hydraloop.units * 0.82 * 0.68);
  assert.equal(metrics.comparison.hydraloop.watts, metrics.comparison.hydraloop.units * 50);
  assert.equal(metrics.comparison.hydraloop.simulatedQuality, false);
});

test('Sunday week gives Friday multiplier on day six and university no inflow Friday/Saturday', () => {
  const mosque = finish(createSimulation());
  const daily = Array.from({ length: 7 }, (_, day) => mosque.history.slice(day * 288, (day + 1) * 288).reduce((sum, row) => sum + row.inflow, 0));
  assert.ok(Math.abs(daily[5] / daily[0] - DEFAULT_CONFIG.fridayMultiplier) < 1e-8);
  const university = finish(createSimulation({ preset: 'university' }));
  assert.equal(university.history.slice(5 * 288).reduce((sum, row) => sum + row.inflow, 0), 0);
  assert.equal(university.history.slice(5 * 288).reduce((sum, row) => sum + row.forecast, 0), 0, 'forecast must obey the same known university workweek before observing the flow');
  assert.ok(university.history.slice(0, 288).some(row => row.inflow > 0));
});

test('no source and sustained outage do not fabricate backwash savings or water', () => {
  const dry = finish(createSimulation({ peoplePerDay: 0 }));
  assert.equal(getMetrics(dry).backwashFixed, 0);
  assert.equal(getMetrics(dry).backwash, 0);
  assert.equal(getMetrics(dry).collected, 0);
  assertBalance(dry);
  const outage = createSimulation();
  injectFault(outage, 'power');
  finish(outage);
  assert.equal(getMetrics(outage).backwashFixed, 0);
  assert.equal(getMetrics(outage).irrigated, 0);
  assertBalance(outage);
});

test('economics uses actual simulated irrigation, capacity ceiling and recurring cost', () => {
  const sim = finish(createSimulation({ preset: 'haram', peoplePerDay: 100000, treatmentM3PerDay: 200 }));
  const economics = getEconomics(sim, 9, 10);
  assert.equal(economics.capital, 90000);
  assert.equal(economics.annualMaintenance, 10000);
  assert.ok(economics.annualIrrigationM3 <= 10 * 365);
  assert.equal(economics.annualNetSavings, economics.annualGrossSavings - economics.annualMaintenance);
  const empty = getEconomics(createSimulation(), 6, 20);
  assert.equal(empty.paybackYears, null);
  assert.equal(empty.annualGrossSavings, 0);
});

test('report is visibly simulated, includes real ledger, fault response and future lab plan', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 80); injectFault(sim, 'ph'); stepSimulation(sim, 80); clearFaults(sim);
  const report = buildReportData(sim);
  assert.equal(report.status, 'SIMULATED');
  assert.ok(report.title.includes('محاكاة'));
  assert.ok(report.period.includes('ليست قياسات ربع سنوية'));
  assert.ok(report.faults.some(item => item.fault === 'ph'));
  assert.ok(report.plannedLabs.length > 0);
  assert.equal(report.calibrations.length, 1);
  assertBalance(sim);
});


test('restoration records service and repeated sensor faults open fresh latched calibration tickets', () => {
  const sim = createSimulation({ preset: 'haram' });
  stepSimulation(sim, 80);
  for (let incident = 0; incident < 2; incident++) {
    injectFault(sim, 'drift');
    stepSimulation(sim, 20);
    const unresolved = sim.maintenance.filter(item => item.key.includes('calibration') && !item.resolved);
    assert.equal(unresolved.length, 1);
    assert.equal(sim.decision.permitted, false);
    clearFaults(sim);
    assert.equal(sim.maintenance.filter(item => !item.resolved).length, 0);
  }
  assert.equal(sim.maintenance.filter(item => item.key.includes('calibration')).length, 2);
  assert.equal(sim.calibrations.length, 2);
  clearFaults(sim);
  assert.equal(sim.calibrations.length, 3, 'an explicit service action is logged even without an injected fault');
  assert.equal(getMetrics(sim).unsafeIrrigationCount, 0);
  assertBalance(sim);
});
