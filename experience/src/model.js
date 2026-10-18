// Browser port of the deterministic virtual rules in server/plant.py.
// Illustrative inventory and signals only; no chemistry, ML, I/O or hardware.
export const FAULTS = ['none', 'turbidity', 'sensor_dropout', 'clogging', 'power_loss', 'valve_stuck'];
export const MODES = ['auto', 'standby', 'backwash'];
const FEED = 1000 / 60, CAPACITY = 5000;
export class BrowserPlant {
  constructor(start = '2026-10-18T09:00:00Z') {
    this.start = Date.parse(start); this.elapsed = 0; this.raw = 3000; this.treated = 2000;
    this.fault = 'none'; this.mode = 'auto'; this.speed = 1; this.manualHold = false;
    this.volumes = Object.fromEntries(['input_liters', 'reuse_liters', 'reject_drain_liters', 'overflow_liters', 'backwash_liters', 'treatment_feed_liters', 'treated_product_liters', 'raw_overflow_liters', 'treated_overflow_liters'].map(k => [k, 0]));
  }
  control({fault = this.fault, mode = this.mode, speed = this.speed, manualHold = this.manualHold} = {}) {
    if (!FAULTS.includes(fault) || !MODES.includes(mode) || ![1,10,30].includes(speed) || typeof manualHold !== 'boolean') throw new RangeError('Invalid browser simulation control');
    Object.assign(this, {fault, mode, speed, manualHold}); return this.snapshot();
  }
  operation() {
    const t = this.elapsed, wave = Math.sin(t / 600), chans = {turbidity: .65 + .08 * wave, ph: 7.2 + .05 * Math.sin(t / 900), chlorine: .35 + .02 * Math.sin(t / 720), orp: 680 + 8 * Math.sin(t / 800), p1_bar: 2.8 + .03 * wave, p2_bar: 2.55 + .03 * wave, p3_bar: 2.3 + .03 * wave, p4_bar: 1.85 + .03 * wave};
    if (this.fault === 'turbidity') chans.turbidity = 8 + .2 * wave;
    if (this.fault === 'sensor_dropout') chans.chlorine = null;
    if (this.fault === 'clogging') Object.assign(chans, {p1_bar: 2.9, p2_bar: 1.5, p3_bar: .9, p4_bar: .35});
    const power = this.fault !== 'power_loss';
    if (!power || this.manualHold || this.mode === 'standby') for (const k of ['p1_bar', 'p2_bar', 'p3_bar', 'p4_bar']) chans[k] = 0;
    const validity = Object.fromEntries(Object.entries(chans).map(([k,v]) => [k, typeof v === 'number' && Number.isFinite(v)]));
    const flow = {inlet_lpm: 0, treatment_lpm: 0, reuse_lpm: 0, drain_lpm: 0, backwash_lpm: 0, product_lpm: 0, overflow_lpm: 0, recirculation_lpm: 0};
    const reasons = [], codes = []; const reason = (code, text) => {codes.push(code); reasons.push(text);};
    let state = 'HOLD', command = 'closed', feedback = 'closed';
    if (!power) reason('POWER_LOSS', 'انقطاع التغذية الافتراضية؛ المضخات متوقفة والصمامان مغلقان.');
    if (this.manualHold) reason('MANUAL_HOLD', 'إيقاف يدوي افتراضي مفعّل.');
    if (!power || this.manualHold) state = 'HOLD';
    else if (this.mode === 'standby') {state = 'STANDBY'; reason('STANDBY_MODE', 'وضع الاستعداد؛ لا معالجة أو ري افتراضي.');}
    else if (this.mode === 'backwash') {
      if (this.treated > 0) {flow.backwash_lpm = 65; state = 'BACKWASH'; reason('BACKWASH_MODE', 'غسيل عكسي افتراضي من الخزان المعالج إلى مصرف الغسيل؛ الري مغلق.');}
      else reason('TREATED_TANK_EMPTY', 'الخزان المعالج فارغ؛ مضخة الغسيل متوقفة.');
    } else {
      if (!['turbidity','ph','chlorine'].every(k => validity[k])) reason('QUALITY_SENSOR_INVALID', 'قراءة جودة مفقودة أو غير صالحة؛ لا سماح بالري الافتراضي.');
      else {
        if (chans.turbidity > 2) reason('TURBIDITY_HIGH', 'العكارة تتجاوز الحد التجريبي الثابت 2 NTU.');
        if (chans.ph < 6.5 || chans.ph > 8.5) reason('PH_OUT_OF_RANGE', 'الأس الهيدروجيني خارج النطاق التجريبي 6.5–8.5.');
        if (chans.chlorine < .2 || chans.chlorine > .5) reason('CHLORINE_OUT_OF_RANGE', 'الكلور المتبقي خارج النطاق التجريبي 0.2–0.5 mg/L.');
      }
      const keys = ['p1_bar','p2_bar','p3_bar','p4_bar'];
      if (!keys.every(k => validity[k])) reason('PRESSURE_SENSOR_INVALID', 'قراءة ضغط غير صالحة.');
      else {
        if (chans.p4_bar < .8 || chans.p4_bar > 3.5) reason('OUTLET_PRESSURE_OUT_OF_RANGE', 'ضغط المخرج خارج النطاق التجريبي 0.8–3.5 bar.');
        if (keys.some(k => chans[k] < 0 || chans[k] > 5)) reason('LINE_PRESSURE_OUT_OF_RANGE', 'ضغط خط خارج نطاق 0–5 bar التجريبي.');
        if (chans.p1_bar - chans.p2_bar > .9) reason('FILTER_DIFFERENTIAL_HIGH', 'فرق الضغط عبر المرشح يتجاوز 0.9 bar؛ حجز افتراضي.');
      }
      if (!codes.length) {command = 'open'; feedback = this.fault === 'valve_stuck' ? 'closed' : 'open'; if (feedback !== command) reason('VALVE_COMMAND_FEEDBACK_MISMATCH', 'طلب فتح افتراضي مع تأكيد بقاء صمام الري مغلقًا؛ إيقاف المضخات وحجز التدفق.');}
      if (!codes.length) {state = 'REUSE'; Object.assign(flow, {inlet_lpm: FEED, treatment_lpm: FEED, product_lpm: FEED, reuse_lpm: FEED});}
    }
    return {chans, validity, flow, power, state, command, feedback, reasons, codes};
  }
  step(seconds) {
    if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0 || seconds > 300) throw new RangeError('Step must be within 0–300 seconds');
    if (!seconds) return this.snapshot();
    const f = this.operation().flow, minutes = seconds / 60, incoming = f.inlet_lpm * minutes;
    const feed = Math.min(f.treatment_lpm * minutes, this.raw + incoming), product = feed;
    const backwash = Math.min(f.backwash_lpm * minutes, this.treated), reuse = Math.min(f.reuse_lpm * minutes, this.treated + product - backwash);
    const raw = this.raw + incoming - feed, treated = this.treated + product - reuse - backwash;
    const rawOverflow = Math.max(0, raw - CAPACITY), treatedOverflow = Math.max(0, treated - CAPACITY);
    this.raw = raw - rawOverflow; this.treated = treated - treatedOverflow; this.elapsed += seconds;
    const increments = {input_liters: incoming, reuse_liters: reuse, reject_drain_liters: 0, backwash_liters: backwash, overflow_liters: rawOverflow + treatedOverflow, raw_overflow_liters: rawOverflow, treated_overflow_liters: treatedOverflow, treatment_feed_liters: feed, treated_product_liters: product};
    for (const [k,v] of Object.entries(increments)) this.volumes[k] += v;
    const snapshot = this.snapshot();
    if (this.raw < 0 || this.treated < 0 || this.raw > CAPACITY || this.treated > CAPACITY || Math.abs(snapshot.volumes.balance_error_liters) > 1e-7) throw new Error('Browser inventory invariant failed');
    return snapshot;
  }
  snapshot() {
    const o = this.operation(), v = this.volumes, stored = this.raw + this.treated;
    return {source: 'browser_simulation', virtual: true, hardware: false, timestamp: new Date(this.start + this.elapsed * 1000).toISOString(), elapsed_seconds: this.elapsed, mode: this.mode, fault: this.fault, speed: this.speed, manual_hold: this.manualHold,
      chans: {...o.chans, flow_lpm: o.flow.reuse_lpm}, validity: {...o.validity, flow_lpm: true}, flow: o.flow,
      tanks: Object.fromEntries([['raw', this.raw], ['treated', this.treated]].map(([k, liters]) => [k, {liters, capacity_liters: CAPACITY, level_percent: liters / CAPACITY * 100}])),
      volumes: {...v, initial_stored_liters: 5000, stored_liters: stored, balance_error_liters: 5000 + v.input_liters - stored - v.reuse_liters - v.reject_drain_liters - v.overflow_liters - v.backwash_liters},
      equipment: {feed_pump: o.flow.treatment_lpm > 0 ? 'running' : 'stopped', dosing_pumps: o.flow.treatment_lpm > 0 ? 'running' : 'stopped', inlet_pump: o.flow.inlet_lpm > 0 ? 'running' : 'stopped', reuse_pump: o.flow.reuse_lpm > 0 ? 'running' : 'stopped', backwash_pump: o.flow.backwash_lpm > 0 ? 'running' : 'stopped', irrigation_valve: o.feedback, drain_valve: o.flow.backwash_lpm > 0 ? 'open' : 'closed', power: o.power, irrigation_command: o.command, irrigation_feedback: o.feedback, compliance_valve: o.flow.product_lpm > 0 ? 'product' : 'closed'},
      safety: {state: o.state, reuse_permitted: o.state === 'REUSE' && o.flow.reuse_lpm > 0, reasons: o.reasons, reason_codes: o.codes}};
  }
}
export function sceneSnapshot(s) {
  return {tanks: Object.fromEntries(Object.entries(s.tanks).map(([k,t]) => [k, {liters: t.liters, capacity: t.capacity_liters, percent: t.level_percent}])), readings: s.chans,
    flows: Object.fromEntries(Object.entries(s.flow).map(([k,v]) => [k.replace('_lpm',''), v])),
    pumps: {feed: s.equipment.feed_pump, inlet: s.equipment.inlet_pump, dosing: s.equipment.dosing_pumps, reuse: s.equipment.reuse_pump, backwash: s.equipment.backwash_pump}, state: s.safety.state, irrigationFeedback: s.equipment.irrigation_feedback, irrigationCommand: s.equipment.irrigation_command, complianceValve: s.equipment.compliance_valve};
}
