// Educational browser model only. These are process conditions, not water-quality limits.
// It is deliberately independent of presentation and does not control any physical actuator.
export const DEMO_NORMAL = Object.freeze({
  power: true, sensorValid: true, calibrationValid: true, freshData: true,
  flowValid: true, treatmentValid: true, disinfectionValid: true,
  storageValid: true, maintenance: false, criticalFault: false
});

export const DEMO_MODES = Object.freeze({
  normal: {},
  sensor: { sensorValid: false },
  disinfection: { disinfectionValid: false },
  power: { power: false },
  storage: { storageValid: false }
});

export function evaluateReuse(input) {
  const checks = [
    ['power', 'POWER_LOSS'], ['sensorValid', 'SENSOR_INVALID'],
    ['calibrationValid', 'CALIBRATION_INVALID'], ['freshData', 'STALE_DATA'],
    ['flowValid', 'FLOW_INVALID'], ['treatmentValid', 'TREATMENT_INVALID'],
    ['disinfectionValid', 'DISINFECTION_INVALID'], ['storageValid', 'STORAGE_INVALID']
  ];
  const reasons = checks.filter(([key]) => input[key] !== true).map(([, code]) => code);
  if (input.maintenance !== false) reasons.push('MAINTENANCE_OR_UNKNOWN');
  if (input.criticalFault !== false) reasons.push('CRITICAL_FAULT_OR_UNKNOWN');
  return { permitted: reasons.length === 0, valve: reasons.length ? 'CLOSED' : 'OPEN',
    route: reasons.length ? 'HOLD' : 'REUSE', reasons };
}

export function evaluateDemo(mode) {
  if (!(mode in DEMO_MODES)) return evaluateReuse({});
  return evaluateReuse({ ...DEMO_NORMAL, ...DEMO_MODES[mode] });
}
