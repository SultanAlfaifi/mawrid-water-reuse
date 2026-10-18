import { plantView } from './plant.js';

const finite = value => typeof value === 'number' && Number.isFinite(value);
const result = (id, title, text, action, label, tone, step) => ({id, title, text, action, label, tone, step});
const reason = v => Array.isArray(v.reasons) ? v.reasons.filter(x => typeof x === 'string' && x.trim()).join(' · ') : '';

// Server state determines the next useful action. UI memory only records that
// this visitor restored the sensor in this exact session; it cannot prove that
// the plant is running, that the valve closed, or that the service is online.
export function experienceState(data, ui = {}, connected = false) {
  if (!data) return result('loading', 'جارٍ الاتصال بالمحطة', 'ننتظر حالة المحطة من الخدمة المحلية.', null, '', 'idle', 0);
  if (!connected) return result('disconnected', 'انقطع الاتصال', 'المشهد يعرض آخر حالة مستلمة. انتظر عودة الاتصال قبل متابعة التجربة.', null, '', 'warning', 0);

  const v = plantView(data), p = data.virtual_plant;
  const controllable = v.active && ['ready', 'paused'].includes(data.session?.status);
  // Current API: the virtual snapshot exposes manual_hold. The overview field
  // also supports a global hold before a virtual session is created.
  const held = data.overview?.manual_hold === true || (controllable && p?.manual_hold === true);
  if (held) return result('manual-hold', 'الإيقاف اليدوي مفعّل', 'ألغِ الطلب اليدوي أولًا. تبقى المحطة متوقفة حتى تضغط متابعة التجربة.', 'release', 'إلغاء الإيقاف اليدوي', 'warning', 0);

  if (!controllable) return result('start', data.session?.status === 'failed' && v.active ? 'توقفت الجلسة بعد خطأ' : 'شغّل محطة مورد', data.session?.status === 'failed' && v.active ? 'تحتاج المحاكاة إلى جلسة جديدة. يبقى سجل الجلسة السابقة محفوظًا.' : 'شاهد الماء يمر بالمعالجة ثم يتجه إلى الري داخل المحاكاة.', 'start', 'تشغيل المحطة', 'idle', 0);

  if (typeof v.fault !== 'string' || !v.fault || typeof v.mode !== 'string' || !v.mode || typeof p.running !== 'boolean') {
    return result('unavailable', 'حالة المحطة غير مكتملة', 'ننتظر حالة تشغيل واضحة من الخدمة قبل متابعة التجربة.', null, '', 'warning', 0);
  }
  if (v.fault !== 'none') {
    const stopped = v.equipment?.irrigation?.status === 'closed' && finite(v.irrigation_flow_lpm) && v.irrigation_flow_lpm === 0;
    const sensorText = stopped
      ? 'انقطعت قراءة الكلور فأُغلق الري افتراضيًا. قد تستمر المعالجة؛ أزل العطل لاستعادة القراءة.'
      : 'انقطعت قراءة الحساس. راقب حالة صمام الري؛ لم تتأكد حالة إغلاقه وتوقف تدفقه بعد.';
    return result('fault', v.fault === 'sensor_dropout' ? 'قراءة الحساس منقطعة' : 'سيناريو عطل قيد التجربة', v.fault === 'sensor_dropout' ? sensorText : (reason(v) || 'هناك عطل افتراضي مفعّل. أزله للعودة إلى التشغيل الاعتيادي.'), 'restore', 'إزالة العطل ومتابعة التشغيل', 'warning', 2);
  }
  if (v.mode !== 'auto') return result('mode', 'المحطة في وضع تشغيل آخر', `${reason(v) || (v.mode === 'backwash' ? 'الغسيل العكسي مفعّل.' : 'المحطة في وضع الاستعداد.')} عُد إلى التشغيل الاعتيادي لمتابعة التجربة.`, 'restore', 'متابعة التجربة', 'idle', 0);
  if (!v.running || data.session?.status === 'paused') return result('paused', 'التجربة متوقفة مؤقتًا', 'الزمن والعدادات ثابتة. تابع التجربة لتتحرك المياه من جديد.', 'resume', 'متابعة التجربة', 'idle', 0);

  if (v.safety_state !== 'REUSE' || v.equipment?.irrigation?.status !== 'open' || !finite(v.irrigation_flow_lpm) || v.irrigation_flow_lpm <= 0) {
    return result('waiting', v.safety_state === 'HOLD' ? 'الري محجوز حاليًا' : 'ننتظر جاهزية الري', reason(v) || 'لم تتأكد حالة الري وتدفقه من الخدمة بعد. انتظر تحديث الحالة.', null, '', 'warning', 1);
  }

  if (ui?.experienceSession === v.sessionId && ui?.experienceRestored === true) {
    return result('done', 'عاد الري بعد استعادة القراءة', 'أزلت العطل وعاد تدفق الري في المحاكاة. يمكنك مراجعة النتيجة أو تكرار اختبار الحساس.', 'test', 'جرّب انقطاع الحساس', 'good', 3);
  }
  return result('normal', 'المحطة تعمل والري متاح', 'جرّب انقطاع قراءة الحساس وشاهد كيف يستجيب النظام.', 'test', 'جرّب انقطاع الحساس', 'good', 1);
}
