"""Application binding tests with virtual physics and a synthetic ML stub."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .app import Application, APIError
from .store import ValidationError
from .test_app import FakeEngine


class PlantApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = FakeEngine()
        self.app = Application(Path(self.temp.name)/'plant.sqlite3', engine=self.engine,
                               start_plant_worker=False)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def start(self):
        return self.app.start({'source_id': 'virtual_plant', 'research_ack': True})

    def test_explicit_twin_source_no_model_and_read_only_get(self):
        with patch.object(self.engine, 'start', side_effect=AssertionError('ML must stay separate')):
            state = self.start()
            for _ in range(4):
                self.assertEqual(self.app.state()['virtual_plant'], state['virtual_plant'])
        self.assertTrue(state['virtual_plant']['virtual'])
        self.assertFalse(state['app']['hardware_connected'])
        self.assertEqual(state['overview']['valve_state'], 'closed')
        self.assertIsNone(state['overview']['measured_irrigation_liters'])
        self.assertEqual(state['model']['status'], 'unavailable')
        self.assertEqual(self.engine.calls, 0)
        self.assertEqual(state['session']['position'], 0)
        with self.assertRaises(APIError): self.app.step({'count': 1})

    def test_tick_persists_actual_snapshot_conserved_volumes_and_export_provenance(self):
        self.start()
        self.app.plant_control({'speed': 30})
        for _ in range(120): self.app._plant_tick()
        state = self.app.state(); snapshot = state['virtual_plant']
        self.assertEqual(state['session']['position'], 120)
        self.assertEqual(snapshot['elapsed_seconds'], 3600)
        self.assertAlmostEqual(snapshot['volumes']['input_liters'], 1000)
        self.assertAlmostEqual(snapshot['volumes']['reuse_liters'], 1000)
        self.assertAlmostEqual(snapshot['volumes']['reject_drain_liters'], 0)
        self.assertAlmostEqual(snapshot['tanks']['raw']['liters'], 3000)
        self.assertAlmostEqual(snapshot['tanks']['treated']['liters'], 2000)
        self.assertAlmostEqual(snapshot['volumes']['balance_error_liters'], 0, places=8)
        self.assertEqual(state['latest']['virtual_plant']['volumes'], snapshot['volumes'])
        self.assertIsNone(state['latest']['score'])
        self.assertEqual(state['latest']['prediction'], -1)
        rows = list(csv.DictReader(io.StringIO(b''.join(self.app.export_csv('readings')).decode('utf-8-sig'))))
        self.assertEqual(len(rows), 120)
        self.assertTrue(all(r['provenance_mode']=='digital_twin' for r in rows))
        self.assertEqual(json.loads(rows[-1]['virtual_plant'])['volumes'], snapshot['volumes'])
        self.assertEqual(self.app.report()['virtual_plant']['volumes'], snapshot['volumes'])

    def test_pause_freezes_clock_and_fault_controls_recompute_without_volume_change(self):
        self.start(); self.app._plant_tick()
        self.app.plant_control({'running': False})
        before = self.app.state()['virtual_plant']
        self.app._plant_tick()
        self.assertEqual(self.app.state()['virtual_plant'], before)
        fault = self.app.plant_control({'fault': 'power_loss'})['virtual_plant']
        self.assertEqual(fault['safety']['state'], 'HOLD')
        self.assertEqual(fault['equipment']['irrigation_valve'], 'closed')
        self.assertEqual(fault['equipment']['feed_pump'], 'stopped')
        self.assertEqual(fault['volumes'], before['volumes'])
        self.assertEqual(fault['elapsed_seconds'], before['elapsed_seconds'])
        self.app.plant_control({'fault': 'none', 'running': True})
        self.app._plant_tick()
        self.assertEqual(self.app.state()['virtual_plant']['safety']['state'], 'REUSE')
        self.assertEqual(self.app.state()['virtual_plant']['elapsed_seconds'], before['elapsed_seconds']+1)

    def test_manual_hold_cannot_be_bypassed_by_start_controls_or_fault_clear(self):
        self.start(); self.app._plant_tick()
        self.app.stop({'note': 'synthetic operator stop'})
        self.assertEqual(self.app.state()['virtual_plant']['safety']['state'], 'HOLD')
        with self.assertRaises(APIError): self.app.plant_control({'running': True})
        self.app.plant_control({'fault': 'none', 'mode': 'auto'})
        self.assertEqual(self.app.state()['virtual_plant']['safety']['state'], 'HOLD')
        self.assertEqual(self.start()['session']['status'], 'paused')
        self.assertEqual(self.app.state()['virtual_plant']['safety']['state'], 'HOLD')
        self.app.reset_hold({})
        self.assertEqual(self.app.state()['session']['status'], 'paused')
        self.app.plant_control({'running': True}); self.app._plant_tick()
        self.assertEqual(self.app.state()['virtual_plant']['safety']['state'], 'REUSE')

    def test_failed_database_tick_does_not_publish_unsaved_time_or_volume(self):
        self.start(); self.app._plant_tick()
        before = self.app.state()['virtual_plant']
        with patch.object(self.app.store, 'append_reading', side_effect=OSError('synthetic disk failure')):
            self.app._plant_tick()
        state = self.app.state()
        self.assertEqual(state['session']['status'], 'failed')
        self.assertEqual(state['session']['position'], 1)
        self.assertEqual(state['virtual_plant']['volumes'], before['volumes'])
        self.assertEqual(state['virtual_plant']['elapsed_seconds'], before['elapsed_seconds'])
        self.assertEqual(state['virtual_plant']['safety']['state'], 'HOLD')
        self.assertEqual(state['overview']['readings'], 1)

    def test_control_commit_failure_leaves_snapshot_unchanged(self):
        self.start(); before = self.app.state()['virtual_plant']
        with patch.object(self.app.store, 'add_event', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError): self.app.plant_control({'fault': 'power_loss'})
        self.assertEqual(self.app.state()['virtual_plant'], before)

    def test_source_switch_clears_twin_and_controls_cannot_change_current_source(self):
        self.start(); self.app._plant_tick()
        self.app.start({'source_id': 'telemetry'})
        self.app._plant_tick()
        state = self.app.state()
        self.assertIsNone(state['virtual_plant'])
        self.assertEqual(state['session']['position'], 0)
        with self.assertRaises(APIError): self.app.plant_control({'speed': 10})
        self.assertEqual(self.app.state()['source']['id'], 'telemetry')

    def test_control_validation_and_stuck_valve_feedback(self):
        self.start(); before = self.app.state()['virtual_plant']
        for payload in ({}, {'speed': True}, {'speed': 100}, {'running': 1},
                        {'mode': 'open'}, {'fault': 'unknown'}, {'gpio': 1}):
            with self.assertRaises(ValidationError): self.app.plant_control(payload)
            self.assertEqual(self.app.state()['virtual_plant'], before)
        state = self.app.plant_control({'fault': 'valve_stuck'})['virtual_plant']
        self.assertEqual(state['equipment']['irrigation_command'], 'open')
        self.assertEqual(state['equipment']['irrigation_feedback'], 'closed')
        self.assertEqual(state['safety']['state'], 'HOLD')
        self.assertEqual(state['flow']['reuse_lpm'], 0)


if __name__ == '__main__': unittest.main()
