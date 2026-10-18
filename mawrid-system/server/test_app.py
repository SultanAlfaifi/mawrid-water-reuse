"""Application tests with deterministic synthetic engine; no ML/data loading."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import csv
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from .app import Application, APIError
from .store import ValidationError


class FakeEngine:
    def __init__(self): self.calls = 0; self.reset_calls = 0; self.reset()
    def reset(self): self.position = 0; self.source = None; self.reset_calls += 1
    def status(self):
        return {'version': 'V9', 'status': 'research_only' if self.source else 'not_loaded',
                'acceptance_passed': False, 'limitations': ['Synthetic engine, no model evidence'],
                'metrics': {}, 'position': self.position, 'total': 1600, 'sample_seconds': 60}
    def start(self, source): self.reset(); self.source = source; return self.status()
    def step(self, count):
        self.calls += 1; records = []
        for _ in range(count):
            index = self.position
            records.append({'source_id': self.source, 'sample_index': index,
              'timestamp': (datetime(2020, 1, 1) + timedelta(minutes=index)).isoformat(),
              'channels': {'pH': 7.2, 'Turb': 200.}, 'prediction': 1 if 2 <= index <= 3 else -1 if index < 2 else 0,
              'reference_prediction': 0, 'baseline_prediction': 0, 'score': None if index < 2 else .75,
              'available': index >= 2, 'ignored_gap': index < 2, 'model_version': 'V9'})
            self.position += 1
        return records


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name)/'test.sqlite3'
        self.engine = FakeEngine(); self.app = Application(self.path, engine=self.engine)
    def tearDown(self): self.app.close(); self.temp.cleanup()
    def start(self): return self.app.start({'source_id': '2019_disclosed_test', 'research_ack': True})

    def test_get_state_does_not_advance_and_replay_is_real_engine_output(self):
        with self.assertRaises(APIError): self.app.start({'source_id': '2019_disclosed_test'})
        state = self.start(); sid = state['session']['id']
        for _ in range(3): self.assertEqual(self.app.state()['session']['position'], 0)
        self.assertEqual(self.engine.calls, 0)
        state = self.app.step({'count': 5})
        self.assertEqual(self.engine.calls, 1); self.assertEqual(state['session']['position'], 5)
        self.assertEqual([r['prediction'] for r in state['series']], [-1, -1, 1, 1, 0])
        self.assertEqual(state['overview']['valve_state'], 'closed'); self.assertIsNone(state['overview']['measured_irrigation_liters'])
        self.assertEqual(state['overview']['anomaly_readings'], 2)
        self.assertEqual(len([a for a in state['alarms'] if a['kind']=='anomaly']), 1)
        # Raw public FNU readings are never compared to the telemetry NTU rule.
        self.assertFalse(any(a['kind']=='safety' for a in state['alarms']))
        self.assertEqual(state['latest']['session_id'], sid)

    def test_restart_retains_history_but_forces_new_session_and_no_model_replay(self):
        sid = self.start()['session']['id']; self.app.step({'count': 4})
        self.app.close(); self.engine = FakeEngine(); self.app = Application(self.path, engine=self.engine)
        self.assertIsNone(self.app.state()['session']['id']); self.assertEqual(self.app.state()['session']['status'], 'idle')
        self.assertEqual(len(self.app.store.readings(session_id=sid)), 4)
        with self.assertRaises(APIError): self.app.step({'count': 1})
        self.assertEqual(self.engine.calls, 0)
        self.assertNotEqual(self.start()['session']['id'], sid)

    def test_db_failure_after_engine_step_marks_failed_and_resets_engine(self):
        self.start(); self.app.step({'count': 1})
        with patch.object(self.app.store, 'append_readings', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(APIError): self.app.step({'count': 2})
        self.assertEqual(self.app.state()['session']['status'], 'failed'); self.assertIsNone(self.engine.source)
        self.assertEqual(self.app.store.counts()['readings'], 1)
        with self.assertRaises(APIError): self.app.step({'count': 1})

    def test_manual_hold_and_acknowledgement_never_open_or_clear_anomaly(self):
        self.start(); self.app.step({'count': 3})
        alarm = next(a for a in self.app.state()['alarms'] if a['kind']=='anomaly')
        self.app.acknowledge(alarm['id'], {'note': '=not a formula after export'})
        self.assertEqual(self.app.state()['latest']['prediction'], 1)
        stopped = self.app.stop({'note': 'صيانة'}); self.assertEqual(stopped['session']['status'], 'paused')
        with self.assertRaises(APIError): self.app.step({'count': 1})
        self.assertEqual(self.app.reset_hold({})['overview']['valve_state'], 'closed')
        self.app.step({'count': 1})
        self.assertIn("'=not a formula", b''.join(self.app.export_csv('events')).decode('utf-8-sig'))

    def test_settings_whitelist_finite_order_and_persistence(self):
        before = self.app.settings()
        for change in ({'arbitrary_model_path': 'x'}, {'ph_min': 9}, {'chlorine_max': -1}, {'stale_seconds': True}, {'turbidity_max': float('nan')}, {'ph_min': 10**999}):
            with self.assertRaises(ValidationError): self.app.update_settings(change)
        self.assertEqual(self.app.settings(), before)
        self.app.update_settings({'site_name': 'موقع تجريبي', 'ph_max': 8.8})
        self.app.close(); self.app = Application(self.path, engine=FakeEngine())
        self.assertEqual(self.app.settings()['site_name'], 'موقع تجريبي')

    def test_telemetry_missing_unknown_ml_timezone_staleness_and_monotonicity(self):
        self.app.start({'source_id': 'telemetry'})
        observed = datetime.now(timezone.utc) - timedelta(minutes=4)
        payload = {'timestamp': observed.isoformat(), 'channels': {'ph': 9, 'flow_lpm': -2}, 'device_id': '@device'}
        state = self.app.ingest(payload)
        self.assertEqual(state['latest']['prediction'], -1); self.assertIsNone(state['latest']['score'])
        self.assertEqual(state['model']['status'], 'unavailable'); self.assertEqual(self.engine.calls, 0)
        self.assertIsNone(state['latest']['channels']['chlorine'])
        self.assertTrue(any('سالبة' in reason for reason in state['latest']['reasons']))
        self.assertTrue(any('متأخرة' in reason for reason in state['latest']['reasons']))
        self.assertEqual(state['overview']['valve_state'], 'closed')
        with self.assertRaises(APIError): self.app.ingest(payload)
        for timestamp in ('2026-01-01T00:00:00', (datetime.now(timezone.utc)+timedelta(seconds=20)).isoformat()):
            with self.assertRaises(ValidationError): self.app.ingest(dict(payload, timestamp=timestamp))
        with self.assertRaises(ValidationError): self.app.ingest(dict(payload, channels={'ph': float('inf')}))
        exported = b''.join(self.app.export_csv('readings')).decode('utf-8-sig')
        self.assertIn('telemetry_ml_unavailable', exported); self.assertIn("'@device", exported)
        self.assertFalse(any(cell.lower()=='nan' for row in csv.reader(io.StringIO(exported)) for cell in row))

    def test_simultaneous_steps_are_serial_and_keep_unique_source_axis(self):
        self.start(); original = self.engine.step
        active, maximum, errors = [0], [0], []
        barrier = threading.Barrier(4)
        def delayed(count):
            active[0] += 1; maximum[0] = max(maximum[0], active[0]); time.sleep(.01)
            try: return original(count)
            finally: active[0] -= 1
        def request():
            try: barrier.wait(); self.app.step({'count': 5})
            except Exception as error: errors.append(error)
        with patch.object(self.engine, 'step', side_effect=delayed):
            threads = [threading.Thread(target=request) for _ in range(4)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=5)
        self.assertEqual(errors, []); self.assertEqual(maximum[0], 1)
        self.assertEqual([r['data']['sample_index'] for r in self.app.store.readings()], list(range(20)))

    def test_export_report_keep_source_session_and_no_unmeasured_volume(self):
        self.start(); self.app.step({'count': 3})
        export = b''.join(self.app.export_csv('readings'))
        self.assertTrue(export.startswith(b'\xef\xbb\xbf'))
        self.assertIn('qualified_public_replay', export.decode('utf-8-sig'))
        self.assertIn('session_id', export.decode('utf-8-sig'))
        report = self.app.report(); self.assertIsNone(report['measured_irrigation_liters'])
        self.assertFalse(report['hardware_connected']); self.assertEqual(report['totals']['readings'], 3)


if __name__ == '__main__': unittest.main()
