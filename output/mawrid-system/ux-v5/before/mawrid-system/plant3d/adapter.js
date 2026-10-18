/* Pure presentation of the server snapshot. No thresholds, physics, ML or I/O. */
const finite = value => typeof value==='number' && Number.isFinite(value);
const value = input => finite(input) ? input : null;
const nonnegative = input => finite(input) && input>=0 ? input : null;
const text = input => typeof input==='string' ? input : null;
const oneOf = (input, options) => options.includes(input) ? input : 'unavailable';
const uuid = input => typeof input==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(input);
export const STATES={REUSE:'معالجة وري',HOLD:'احتجاز',STANDBY:'استعداد',BACKWASH:'غسيل عكسي'};
export const FAULTS={none:'لا عطل مختار',turbidity:'ارتفاع العكارة',sensor_dropout:'انقطاع قراءة حساس',clogging:'انسداد المرشح',power_loss:'انقطاع الكهرباء',valve_stuck:'تعطل صمام الري'};
export const SENSOR_LABELS={turbidity:['العكارة','NTU'],ph:['الأس الهيدروجيني','pH'],chlorine:['الكلور المتبقي','mg/L'],orp:['جهد الأكسدة','mV'],p1_bar:['ضغط الدخول','bar'],p2_bar:['بعد الوسائط','bar'],p3_bar:['بعد الكربون','bar'],p4_bar:['ضغط المخرج','bar']};
export const EQUIPMENT={raw:['TK-101','خزان التجميع'],feed:['P-101','مضخة التغذية'],media:['F-101','مرشح الوسائط'],carbon:['F-102','مرشح الكربون'],dosing:['D-101','مضخات الجرعات'],treated:['TK-102','الخزان المعالج'],reuse:['P-102','مضخة الري'],valve:['XV-201','صمام الري'],backwash:['P-103','مضخة الغسيل'],drain:['DR-101','المصرف'],inlet:['IN-101','مدخل التجميع']};

function tank(input) {
  if(!input || typeof input!=='object') return {liters:null,capacity:null,percent:null};
  const capacity=nonnegative(input.capacity_liters),liters=nonnegative(input.liters);
  // Invalid/missing inventory is unavailable, never silently clamped to empty.
  const valid=capacity>0 && liters!==null && liters<=capacity;
  const percent=finite(input.level_percent) && input.level_percent>=0 && input.level_percent<=100 ? input.level_percent : null;
  return {liters:valid?liters:null,capacity:capacity>0?capacity:null,percent:valid?percent:null};
}
export function adaptState(data) {
  const p=data?.virtual_plant,s=data?.session;
  if(data?.source?.kind!=='digital_twin' || data?.source?.id!=='virtual_plant'
    || data?.app?.hardware_connected!==false || !uuid(s?.id)
    || !p || p.source!=='virtual_plant' || p.virtual!==true || p.hardware!==false
    || p.session_id!==s.id || !['ready','paused','failed'].includes(s.status)) return null;
  const readings={};
  for(const key of Object.keys(SENSOR_LABELS)) readings[key]=p.validity?.[key]===true ? value(p.chans?.[key]) : null;
  const e=p.equipment||{},flow=p.flow||{},volumes=p.volumes||{};
  const flows={};for(const key of ['inlet','treatment','product','reuse','drain','backwash','overflow'])flows[key]=nonnegative(flow[key+'_lpm']);
  const pumps={};for(const [key,field] of Object.entries({feed:'feed_pump',inlet:'inlet_pump',dosing:'dosing_pumps',reuse:'reuse_pump',backwash:'backwash_pump'}))pumps[key]=oneOf(e[field],['running','stopped']);
  const v={};for(const key of ['input_liters','reuse_liters','reject_drain_liters','backwash_liters','overflow_liters','stored_liters','treated_product_liters'])v[key]=nonnegative(volumes[key]);
  return {sessionId:s.id,sessionStatus:s.status,running:p.running===true&&s.status==='ready',
    timestamp:text(p.timestamp),elapsedSeconds:nonnegative(p.elapsed_seconds),
    speed:[1,10,30].includes(p.speed)?p.speed:null,mode:oneOf(p.mode,['auto','standby','backwash']),
    fault:oneOf(p.fault,Object.keys(FAULTS)),manualHold:p.manual_hold===true,
    state:oneOf(p.safety?.state,Object.keys(STATES)),
    reasons:Array.isArray(p.safety?.reasons)?p.safety.reasons.filter(x=>typeof x==='string'):[],
    reasonCodes:Array.isArray(p.safety?.reason_codes)?p.safety.reason_codes.filter(x=>typeof x==='string'):[],
    power:typeof e.power==='boolean'?e.power:null,
    irrigationFeedback:oneOf(e.irrigation_feedback,['open','closed']),irrigationCommand:oneOf(e.irrigation_command,['open','closed']),
    drainValve:oneOf(e.drain_valve,['open','closed']),pumps,flows,readings,
    deltaMedia:readings.p1_bar!==null&&readings.p2_bar!==null?readings.p1_bar-readings.p2_bar:null,
    deltaCarbon:readings.p2_bar!==null&&readings.p3_bar!==null?readings.p2_bar-readings.p3_bar:null,
    tanks:{raw:tank(p.tanks?.raw),treated:tank(p.tanks?.treated)},volumes:v,
    ratedFeed:nonnegative(p.design_assumptions?.rated_m3_per_day),recovery:value(p.design_assumptions?.volumetric_recovery),
    alarms:(Array.isArray(data.alarms)?data.alarms:[]).filter(a=>a.session_id===s.id).map(a=>({title:text(a.title),timestamp:text(a.timestamp),severity:text(a.severity)})),
  };
}

// Wall-time freshness is about successful transport, never the virtual clock.
export function presentation(state,now,staleMs=6500) {
  const snapshot=state?.snapshot||null;
  const fresh=state?.connection==='connected' && finite(state.lastSuccessAt) && finite(now) && now-state.lastSuccessAt<=staleMs && now>=state.lastSuccessAt;
  const phase=!fresh?(state?.connection==='connecting'?'connecting':'disconnected'):
    !snapshot?'empty':snapshot.sessionStatus==='failed'?'failed':snapshot.running?'live':'paused';
  return {snapshot,fresh,phase,motion:fresh&&!!snapshot?.running&&snapshot.sessionStatus==='ready'};
}
