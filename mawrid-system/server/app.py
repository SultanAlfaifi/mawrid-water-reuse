"""Application operations for Mawrid's local, non-actuating prototype."""
from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import threading
import uuid

from .store import Store, ValidationError, NotFoundError, integer, text, timestamp, utc_now

SYSTEM = Path(__file__).resolve().parents[1]
WORKSPACE = SYSTEM.parent
SETTINGS = {'site_name': 'وحدة مورد التجريبية', 'turbidity_max': 2.0, 'ph_min': 6.5,
            'ph_max': 8.5, 'chlorine_min': 0.2, 'chlorine_max': 0.5, 'stale_seconds': 120}
NO_CONTROLLER = 'صمام البرنامج مغلق؛ لا يوجد متحكم أمان مستقل أو عتاد متصل.'


class APIError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message); self.status, self.code, self.message = status, code, message


def object_fields(data, allowed, required=()):
    if not isinstance(data, dict) or set(data) - set(allowed) or not set(required).issubset(data):
        raise ValidationError('حقول الطلب غير صحيحة أو غير مكتملة')
    return data


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try: return math.isfinite(value)
    except OverflowError: return False


def reading_record(row):
    result = dict(row['data'])
    result.update(id=row['id'], session_id=row['sessionId'], timestamp=row['timestamp'], received_at=row['recordedAt'])
    return result


def alarm_record(row):
    return {'id': row['id'], 'session_id': row['sessionId'], 'timestamp': row['timestamp'],
            'kind': row['kind'], 'severity': row['severity'], 'title': row['title'], 'detail': row['message'],
            'acknowledged_at': row['acknowledgedAt'], 'note': row['note'], 'reading_id': row['readingId'],
            'received_at': row['recordedAt'], 'details': row['details']}


class Application:
    def __init__(self, database, *, engine=None, contract_path=None, start_plant_worker=True):
        self.store = Store(database)
        self.contract = json.loads(Path(contract_path or SYSTEM/'CONTRACT.json').read_text())
        self.sources = {source['id']: source for source in self.contract['sources']}
        if engine is None:
            from .ai import ResearchEngine
            engine = ResearchEngine()
        self.engine = engine
        self.lock = threading.RLock()
        # A restarted process never reconstitutes a mutable model context from
        # persisted predictions. A new explicit session is required.
        self.engine.reset()
        self.source_id = '2019_disclosed_test'
        self.session_id = None
        self.session_status = 'idle'
        self.position = 0
        self._last_signature = (False, False, ())
        self._last_telemetry_clock = None
        missing = {key: value for key, value in SETTINGS.items() if key not in self.store.settings()}
        if missing: self.store.update_settings(missing)
        self.manual_hold = self.store.settings().get('_manual_hold', False) is True
        self._plant = None
        self._plant_signature = None
        self._plant_stop = threading.Event()
        self._plant_thread = None
        if start_plant_worker:
            self._plant_thread = threading.Thread(target=self._plant_loop, name='mawrid-virtual-plant', daemon=True)
            self._plant_thread.start()

    def close(self):
        self._plant_stop.set()
        if self._plant_thread is not None:
            self._plant_thread.join(timeout=5)
        with self.lock:
            self.engine.reset(); self.store.close()

    def settings(self):
        stored = self.store.settings()
        return {key: stored.get(key, value) for key, value in SETTINGS.items()}

    def _model(self):
        model = deepcopy(self.engine.status())
        if self.source_id == 'telemetry':
            model['status'] = 'unavailable'
            model['message'] = 'الذكاء الحالي غير مؤهل لمخطط قراءات الجهاز؛ تطبق قواعد تجريبية فقط.'
        elif self.source_id == 'virtual_plant':
            model['status'] = 'unavailable'
            model['message'] = 'حماية التوأم بقواعد تشغيل افتراضية؛ النموذج البحثي متاح منفصلًا على بياناته العامة.'
        return model

    def state(self):
        with self.lock:
            model = self._model()
            series = [reading_record(r) for r in self.store.readings(limit=60, session_id=self.session_id)] if self.session_id else []
            latest = series[-1] if series else None
            overview = self.store.stats(self.session_id) if self.session_id else {
                'readings': 0, 'anomaly_readings': 0, 'unavailable_readings': 0}
            reasons = list(latest['reasons']) if latest else ['لم تبدأ قراءة في جلسة حالية.', NO_CONTROLLER]
            if self.source_id == 'telemetry' and latest:
                age = self._age(latest['timestamp'])
                if age > self.settings()['stale_seconds']:
                    reasons.append('القراءة الأخيرة متأخرة عن المهلة التجريبية.')
            if self.manual_hold: reasons.insert(0, 'إيقاف برمجي يدوي مفعّل؛ يلزم إعادة التهيئة لاستئناف الجلسة.')
            overview.update(unacknowledged_alarms=self.store.counts()['unacknowledgedEvents'],
                            measured_irrigation_liters=None, valve_state='closed', decision='محجوز', reasons=reasons)
            source = deepcopy(self.sources[self.source_id])
            telemetry = {'session_id': None, 'last_device_id': None,
                         'last_received_at': None, 'last_receipt': None}
            if self.source_id == 'telemetry' and self.session_id:
                telemetry['session_id'] = self.session_id
                if latest:
                    telemetry.update(last_device_id=latest.get('device_id'), last_received_at=latest['received_at'])
                    if latest.get('measurement_id'):
                        telemetry['last_receipt'] = {'measurement_id': latest['measurement_id'],
                            'session_id': self.session_id, 'reading_id': latest['id'], 'duplicate': False}
            plant = self._plant.snapshot() if self.source_id == 'virtual_plant' and self._plant is not None else None
            if plant is not None:
                plant.update(session_id=self.session_id, running=self.session_status == 'ready')
            return {'app': {'name': 'مورد', 'mode': 'local_prototype', 'hardware_connected': False},
                    'source': source, 'session': {'id': self.session_id, 'status': self.session_status,
                        'position': self.position, 'total': source['rows'], 'sample_seconds': source['sample_seconds']},
                    'model': model, 'overview': overview, 'latest': latest, 'series': series,
                    'alarms': [alarm_record(r) for r in self.store.events(limit=50)], 'settings': self.settings(),
                    'settings_notice': 'حدود تجريبية محلية؛ لا تمثل اعتمادًا نظاميًا أو إثباتًا لسلامة المياه.',
                    'telemetry': telemetry,
                    'virtual_plant': plant,
                    'links': {'model_report': '/evidence/gecco-v9/report.html', 'viewer': '/viewer/'}}

    def _event(self, kind, title, detail='', severity='info', **extra):
        result = {'kind': kind, 'severity': severity, 'title': title, 'message': detail,
                  'details': {'source_id': self.source_id, **extra}}
        return result

    def start(self, data):
        object_fields(data, {'source_id', 'research_ack'}, {'source_id'})
        source = data['source_id']
        if not isinstance(source, str) or source not in self.sources: raise ValidationError('مصدر غير معروف')
        if source != 'telemetry' and data.get('research_ack') is not True:
            raise APIError(400, 'research_ack_required', 'أقرّ بأن النموذج بحثي وأنه لا يثبت سلامة الماء.')
        if 'research_ack' in data and not isinstance(data['research_ack'], bool): raise ValidationError('الإقرار يجب أن يكون منطقيًا')
        with self.lock:
            self.engine.reset()
            self.source_id = source; self.position = 0
            self._plant = None; self._plant_signature = None
            self.session_id = None
            self.session_status = 'idle'; self._last_signature = (False, False, ())
            self._last_telemetry_clock = None
            self.session_id = self.store.create_session(source, {'source': self.sources[source],
                'research_ack': data.get('research_ack', False), 'hardware_connected': False})
            try:
                if source == 'virtual_plant':
                    from .plant import PlantSimulator
                    self._plant = PlantSimulator(start_timestamp=utc_now())
                    self._plant.set_manual_hold(self.manual_hold)
                elif source != 'telemetry': self.engine.start(source)
                self.session_status = 'paused' if self.manual_hold else 'ready'
                self.store.add_event(self._event('system', 'بدأت جلسة محلية',
                    'توأم رقمي معلن؛ العدادات والتدفقات محاكاة وليست قياسات ميدانية.' if source == 'virtual_plant' else
                    'إعادة تشغيل بيانات عامة بنموذج بحثي.' if source != 'telemetry' else 'قراءات جهاز؛ الذكاء غير مؤهل لهذا المخطط.'), session_id=self.session_id)
            except Exception as error:
                self.engine.reset(); self._plant = None; self.session_status = 'failed'
                self.store.add_event(self._event('system', 'تعذر بدء الجلسة',
                    'لم يُحمّل المحرك أو لم ينجح التحقق؛ لا توجد بيانات بديلة.', 'critical'), session_id=self.session_id)
                raise APIError(503, 'model_initialization_failed', 'تعذر تهيئة المصدر المؤهل. تحقق من دليل النموذج والبيئة المحلية.') from error
            return self.state()

    @staticmethod
    def _age(observed):
        parsed = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()

    def _annotate(self, record, signature):
        values = record['channels']; settings = self.settings()
        reasons, violations = [NO_CONTROLLER], []
        prediction = record['prediction']
        if prediction == 1: reasons.append('رصد النموذج شذوذًا؛ يلزم فحص بشري، دون تحديد نوع العطل.')
        elif prediction == 0: reasons.append('لم يرصد النموذج شذوذًا؛ هذه ليست شهادة سلامة للماء.')
        elif self.source_id == 'telemetry': reasons.append('الذكاء غير متاح لمخطط قراءات الجهاز.')
        elif record['ignored_gap']: reasons.append('فترة الاستبعاد الأولية: القراءة لا تدخل سياق النموذج.')
        else: reasons.append('درجة النموذج غير متاحة أثناء التهيئة أو نقص القياسات.')
        missing = any(value is None for value in values.values())
        if missing: reasons.append('توجد قياسات مفقودة؛ يبقى الحجز البرمجي.')
        if self.source_id == 'telemetry':
            turb = values.get('turbidity')
            ph = values.get('ph')
            if turb is not None and (turb < 0 or turb > settings['turbidity_max']): violations.append('العكارة خارج الحد التجريبي.')
            if ph is not None and not settings['ph_min'] <= ph <= settings['ph_max']: violations.append('الأس الهيدروجيني خارج المجال التجريبي.')
        if self.source_id == 'telemetry':
            chlorine = values.get('chlorine'); flow = values.get('flow_lpm')
            if chlorine is not None and not settings['chlorine_min'] <= chlorine <= settings['chlorine_max']:
                violations.append('الكلور المقاس خارج المجال التجريبي؛ لا يُستبدل بقياس ORP.')
            if flow is not None and flow < 0: violations.append('قراءة التدفق سالبة وتحتاج مراجعة.')
            age = self._age(record['timestamp'])
            if age > settings['stale_seconds']: violations.append('القراءة متأخرة عن المهلة التجريبية.')
            elif age < -60: violations.append('طابع القراءة في المستقبل؛ تحقق من ساعة الجهاز.')
        elif self.source_id == '2019-04': reasons.append('مصدر ضغط فقط؛ لا يثبت جودة المياه الكيميائية أو الميكروبية.')
        elif self.source_id == '2019_disclosed_test': reasons.append('إعادة تشغيل مصدر عام؛ لا تُطبق عليه حدود جهاز مورد أو تحويلات وحدات مفترضة.')
        reasons.extend(violations)
        if self.manual_hold: reasons.append('إيقاف برمجي يدوي مفعّل.')
        record = dict(record, reasons=reasons, decision='محجوز')
        alarm = prediction == 1
        events = []
        if alarm and not signature[0]:
            events.append(self._event('anomaly', 'شذوذ رصده النموذج', reasons[1], 'warning'))
        if missing and not signature[1]:
            events.append(self._event('missing', 'قياسات مفقودة', 'لم تُملأ القيم المفقودة أو تُستبدل بقراءات اصطناعية.', 'warning'))
        if violations and tuple(violations) != signature[2]:
            events.append(self._event('safety', 'خروج عن القواعد التجريبية', ' '.join(violations), 'critical'))
        for event in events: event['timestamp'] = record['timestamp']
        return record, events, (alarm, missing, tuple(violations))

    def _fail_after_inference(self):
        self.engine.reset(); self.session_status = 'failed'
        try:
            self.store.add_event(self._event('system', 'أوقفت الجلسة بعد خطأ',
                'لم يعد الاستمرار مسموحًا بعد تعذر الحساب أو الحفظ. ابدأ جلسة جديدة.', 'critical'), session_id=self.session_id)
        except Exception:
            pass  # Database may itself be unavailable; the in-memory fail latch remains.

    def step(self, data):
        object_fields(data, {'count'}, {'count'}); count = integer(data['count'], 'count', 1, 25)
        with self.lock:
            if self.sources[self.source_id]['kind'] != 'public_replay' or not self.session_id or self.session_status not in ('ready', 'paused'):
                raise APIError(409, 'replay_not_ready', 'ابدأ جلسة إعادة تشغيل جديدة أولًا.')
            if self.manual_hold: raise APIError(409, 'manual_hold', 'الجلسة موقوفة يدويًا؛ استخدم إعادة التهيئة أولًا.')
            try:
                records = self.engine.step(count)
                prepared, signature = [], self._last_signature
                for record in records:
                    expected = self.position + len(prepared)
                    if record['sample_index'] != expected or record['source_id'] != self.source_id:
                        raise RuntimeError('Model source axis changed')
                    annotated, events, signature = self._annotate(record, signature)
                    prepared.append({'sequence': expected, 'timestamp': record['timestamp'], 'data': annotated, 'events': events})
                self.store.append_readings(self.session_id, prepared)
                self.position += len(prepared); self._last_signature = signature
                self.session_status = 'completed' if self.position >= self.sources[self.source_id]['rows'] else 'ready'
            except Exception as error:
                self._fail_after_inference()
                raise APIError(500, 'replay_failed', 'توقفت الجلسة بعد تعذر الحساب أو الحفظ؛ ابدأ جلسة جديدة.') from error
            return self.state()

    def pause(self, data):
        object_fields(data, set())
        with self.lock:
            if self.session_status == 'ready': self.session_status = 'paused'
            return self.state()

    def stop(self, data):
        object_fields(data, {'note'}); note = data.get('note', '')
        text(note, 'note', 1000, empty=True)
        with self.lock:
            staged = deepcopy(self._plant)
            if staged is not None: staged.set_manual_hold(True)
            self.store.update_settings({'_manual_hold': True}, event=self._event('system', 'إيقاف برمجي يدوي', note, 'warning'))
            self.manual_hold = True
            self._plant = staged
            if self.session_status == 'ready': self.session_status = 'paused'
            return self.state()

    def reset_hold(self, data):
        object_fields(data, set())
        with self.lock:
            staged = deepcopy(self._plant)
            if staged is not None: staged.set_manual_hold(False)
            self.store.update_settings({'_manual_hold': False}, event=self._event('system', 'أعيدت تهيئة الإيقاف البرمجي',
                'أزيل الإيقاف اليدوي فقط. الصمام البرمجي مغلق ولم يصدر أمر لعتاد.'))
            self.manual_hold = False
            self._plant = staged
            return self.state()

    def _plant_loop(self):
        # A software clock, explicitly separate from field acquisition time.
        # Each tick advances one second times the selected speed; long host
        # suspensions pause the virtual clock rather than invent missing data.
        while not self._plant_stop.wait(1):
            self._plant_tick()

    def _plant_tick(self):
        with self.lock:
            if (self._plant_stop.is_set() or self.source_id != 'virtual_plant'
                    or self._plant is None or self.session_status != 'ready'):
                return
            try:
                staged = deepcopy(self._plant)
                staged.set_manual_hold(self.manual_hold)
                snapshot = staged.step(staged.snapshot()['speed'])
                signature = (snapshot['safety']['state'], tuple(snapshot['safety']['reason_codes']))
                events = []
                if signature != self._plant_signature:
                    severity = 'critical' if signature[0] == 'HOLD' else 'info'
                    events.append(self._event('simulation', 'توأم رقمي: ' + snapshot['safety']['state'],
                        ' '.join(snapshot['safety']['reasons']) or 'شروط التشغيل الافتراضية متحققة.', severity,
                        virtual=True, simulation_timestamp=snapshot['timestamp'], reason_codes=list(signature[1])))
                    events[-1]['timestamp'] = snapshot['timestamp']
                record = {'source_id': 'virtual_plant', 'timestamp': snapshot['timestamp'],
                    'sample_index': self.position, 'channels': snapshot['chans'],
                    'prediction': -1, 'reference_prediction': -1, 'baseline_prediction': -1,
                    'score': None, 'available': False, 'ignored_gap': False, 'model_version': 'unavailable',
                    'decision': 'ري افتراضي' if snapshot['safety']['reuse_permitted'] else 'احتجاز افتراضي',
                    'reasons': list(snapshot['safety']['reasons']), 'virtual_plant': snapshot,
                    'provenance_mode': 'digital_twin'}
                self.store.append_reading(self.session_id, self.position, snapshot['timestamp'], record, events=events)
                self._plant, self._plant_signature = staged, signature
                self.position += 1
            except Exception:
                # No physical actuator exists. Stop this virtual session; do
                # not expose advanced, uncommitted simulation state as saved.
                self.session_status = 'failed'
                if self._plant is not None: self._plant.set_manual_hold(True)
                try:
                    self.store.add_event(self._event('system', 'توقف التوأم الرقمي بعد خطأ حفظ أو حساب',
                        'لم تُنشر خطوة جزئية؛ ابدأ جلسة افتراضية جديدة.', 'critical'), session_id=self.session_id)
                except Exception:
                    pass

    def plant_control(self, data):
        object_fields(data, {'mode', 'fault', 'speed', 'running'})
        if not data: raise ValidationError('اختر أمر تشغيل افتراضي')
        if 'running' in data and not isinstance(data['running'], bool):
            raise ValidationError('running يجب أن يكون منطقيًا')
        with self.lock:
            if self.source_id != 'virtual_plant' or self._plant is None or self.session_status not in ('ready', 'paused'):
                raise APIError(409, 'virtual_plant_not_active', 'ابدأ جلسة المنشأة الافتراضية أولًا.')
            if data.get('running') is True and self.manual_hold:
                raise APIError(409, 'manual_hold', 'أزل الاحتجاز اليدوي قبل تشغيل الساعة الافتراضية.')
            staged = deepcopy(self._plant)
            controls = {key: value for key, value in data.items() if key != 'running'}
            try:
                if controls: staged.set_control(controls)
            except (ValueError, TypeError) as error:
                raise ValidationError(str(error)) from error
            self.store.add_event(self._event('simulation', 'تغير أمر في التوأم الرقمي',
                'أمر برمجي لمعدات افتراضية؛ لا اتصال بعتاد.', changes=data, virtual=True,
                simulation_timestamp=staged.snapshot()['timestamp']), session_id=self.session_id)
            self._plant = staged
            if 'running' in data: self.session_status = 'ready' if data['running'] else 'paused'
            return self.state()

    def acknowledge(self, alarm_id, data):
        object_fields(data, {'note'})
        with self.lock:
            self.store.acknowledge(alarm_id, data.get('note'))
            return self.state()

    def update_settings(self, data):
        object_fields(data, SETTINGS)
        with self.lock:
            candidate = {**self.settings(), **data}
            text(candidate['site_name'], 'site_name', 120)
            bounds = {'turbidity_max': (0, 1000), 'ph_min': (0, 14), 'ph_max': (0, 14),
                      'chlorine_min': (0, 20), 'chlorine_max': (0, 20), 'stale_seconds': (1, 86400)}
            for key, (low, high) in bounds.items():
                value = candidate[key]
                if not finite_number(value) or not low <= value <= high:
                    raise ValidationError(f'قيمة الإعداد {key} خارج المجال التجريبي')
            integer(candidate['stale_seconds'], 'stale_seconds', 1, 86400)
            if candidate['ph_min'] >= candidate['ph_max'] or candidate['chlorine_min'] >= candidate['chlorine_max']:
                raise ValidationError('يجب أن يكون الحد الأدنى أقل من الحد الأعلى')
            self.store.update_settings(data, event=self._event('system', 'حُدّثت الحدود التجريبية',
                'إعدادات محلية غير معتمدة كحدود نظامية.', changes=data))
            return self.state()

    def ingest(self, data):
        object_fields(data, {'timestamp', 'channels', 'device_id', 'session_id', 'measurement_id'},
                      {'timestamp', 'channels', 'device_id'})
        paired = {'session_id', 'measurement_id'} & set(data)
        if paired and paired != {'session_id', 'measurement_id'}:
            raise ValidationError('أرسل session_id وmeasurement_id معًا')
        for key in paired:
            try: canonical = str(uuid.UUID(data[key]))
            except (ValueError, AttributeError, TypeError):
                raise ValidationError(f'{key} يجب أن يكون UUID بصيغته القياسية')
            if canonical != data[key]: raise ValidationError(f'{key} يجب أن يكون UUID بصيغته القياسية')
        observed = timestamp(data['timestamp'])
        parsed = datetime.fromisoformat(observed)
        if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValidationError('طابع الجهاز يجب أن يتضمن المنطقة الزمنية')
        observed = parsed.astimezone(timezone.utc).isoformat()
        device = text(data['device_id'], 'device_id', 100)
        supplied = object_fields(data['channels'], {'turbidity', 'ph', 'chlorine', 'flow_lpm'})
        if paired and set(supplied) != {'turbidity', 'ph', 'chlorine', 'flow_lpm'}:
            raise ValidationError('مع الإيصال أرسل القنوات الأربع صراحة؛ استخدم null للمفقود')
        channels = {key: supplied.get(key) for key in ('turbidity', 'ph', 'chlorine', 'flow_lpm')}
        for value in channels.values():
            if value is not None and not finite_number(value):
                raise ValidationError('قيمة الحساس يجب أن تكون عددًا محدودًا أو null')
        channels = {key: float(value) if value is not None else None for key, value in channels.items()}
        digest = None
        if paired:
            normalized = {'session_id': data['session_id'], 'timestamp': observed, 'device_id': device, 'channels': channels}
            digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False,
                                   allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        with self.lock:
            # A lost HTTP reply can be retried even after a session switch or
            # server restart. Return its original receipt without touching the
            # current source, model, latest measurement, clock or alarm state.
            if paired:
                previous = self.store.ingestion_receipt(data['measurement_id'])
                if previous is not None:
                    if previous['session_id'] != data['session_id'] or previous['request_sha256'] != digest:
                        raise APIError(409, 'idempotency_conflict', 'معرّف القياس مسجّل بمحتوى أو جلسة مختلفة.')
                    result = self.state()
                    result['ingestion'] = {key: previous[key] for key in ('measurement_id', 'session_id', 'reading_id')}
                    result['ingestion']['duplicate'] = True
                    return result
                if self.source_id != 'telemetry' or data['session_id'] != self.session_id or self.session_status not in ('ready', 'paused'):
                    raise APIError(409, 'session_not_active', 'جلسة الجامع غير نشطة؛ لم تُنقل القراءة إلى جلسة أخرى.')
            if self._age(observed) < -5:
                raise ValidationError('طابع الجهاز يتجاوز الساعة الحالية بأكثر من خمس ثوانٍ؛ صحّح ساعة الجهاز أولًا')
            if self.source_id != 'telemetry' or not self.session_id or self.session_status not in ('ready', 'paused'):
                raise APIError(409, 'telemetry_session_required', 'ابدأ جلسة قراءات جهاز أولًا.')
            if self._last_telemetry_clock is not None and parsed <= self._last_telemetry_clock:
                raise APIError(409, 'nonincreasing_timestamp', 'يجب أن يتقدم طابع القراءة داخل الجلسة دون تكرار.')
            record = {'source_id': 'telemetry', 'timestamp': observed, 'sample_index': self.position,
                      'channels': channels, 'prediction': -1, 'reference_prediction': -1, 'baseline_prediction': -1,
                      'score': None, 'available': False, 'ignored_gap': False, 'model_version': 'unavailable', 'device_id': device}
            receipt = None
            if paired:
                record['measurement_id'] = data['measurement_id']
                receipt = {'measurement_id': data['measurement_id'], 'request_sha256': digest}
            annotated, events, signature = self._annotate(record, self._last_signature)
            reading, added = self.store.append_reading(self.session_id, self.position, observed, annotated,
                                                       events=events, receipt=receipt)
            if added:
                self.position += 1; self._last_signature = signature; self._last_telemetry_clock = parsed
            result = self.state()
            if paired:
                result['ingestion'] = {'measurement_id': data['measurement_id'], 'session_id': data['session_id'],
                                       'reading_id': reading['id'], 'duplicate': not added}
            return result

    def report(self):
        with self.lock:
            plant = self._plant.snapshot() if self.source_id == 'virtual_plant' and self._plant is not None else None
            return {'generated_at': utc_now(), 'app_mode': 'local_prototype', 'hardware_connected': False,
                'totals': {**self.store.stats(), **self.store.counts()},
                'sources': deepcopy(list(self.sources.values())), 'model': self._model(),
                'measured_irrigation_liters': None, 'valve_state': 'closed',
                'virtual_plant': plant,
                'limitations': ['سجل تشغيلي محلي؛ ليس تقرير امتثال معتمدًا.',
                    'لا كمية ري مقاسة أو وفر مياه مثبت؛ لا عداد عتاد متصل.',
                    'حجوم التوأم الرقمي محاكاة محفوظة منفصلة عن أي كمية مقاسة.',
                    'القراءات العامة إعادة تشغيل، وقراءات الجهاز لا تدخل النموذج الحالي.',
                    'لا تصنيف مثبت لأعطال الحساس الخمسة ولا ضمان لجودة المياه أو تعقيمها.']}

    def export_csv(self, kind):
        """Snapshot-bounded export, including source/session and research context."""
        if kind not in ('readings', 'events'): raise ValidationError('تصدير غير معروف')
        channels = list(dict.fromkeys(c['key'] for s in self.sources.values() for c in s['channels']))
        fields = (['id', 'session_id', 'source_id', 'timestamp', 'received_at', 'sample_index', 'device_id', 'measurement_id',
                   *['sensor_' + key for key in channels], 'prediction', 'reference_prediction', 'baseline_prediction',
                   'score', 'available', 'ignored_gap', 'model_version', 'decision', 'reasons',
                   'provenance_mode', 'hardware_connected', 'model_acceptance_passed', 'virtual_plant'] if kind == 'readings' else
                  ['id', 'session_id', 'timestamp', 'received_at', 'kind', 'severity', 'title', 'detail',
                   'acknowledged_at', 'note', 'reading_id', 'details'])
        buffer = io.StringIO(); writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader(); yield b'\xef\xbb\xbf' + buffer.getvalue().encode('utf-8')
        buffer.seek(0); buffer.truncate()
        for row in self.store.iter_records(kind):
            if kind == 'readings':
                record = reading_record(row)
                values = {key: record.get(key) for key in fields}
                values.update({'sensor_' + key: record['channels'].get(key) for key in channels})
                values.update(provenance_mode='digital_twin' if record['source_id']=='virtual_plant' else
                              'telemetry_ml_unavailable' if record['source_id']=='telemetry' else 'qualified_public_replay',
                              hardware_connected=False, model_acceptance_passed=False)
            else: values = alarm_record(row)
            clean = {}
            for key in fields:
                value = values.get(key)
                if isinstance(value, (dict, list)): value = json.dumps(value, ensure_ascii=False, allow_nan=False)
                if isinstance(value, str) and value[:1] in ('=', '+', '-', '@'): value = "'" + value
                clean[key] = value
            writer.writerow(clean); yield buffer.getvalue().encode('utf-8')
            buffer.seek(0); buffer.truncate()
