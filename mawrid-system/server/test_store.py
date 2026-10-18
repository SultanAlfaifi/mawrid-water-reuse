"""Synthetic-only durable store tests; no source/model reads."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from .store import Store, ValidationError, NotFoundError


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / 'mawrid.sqlite3'
        self.store = Store(self.path)
        self.session = self.store.create_session('synthetic', {'cadenceSeconds': 60})

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def event(self):
        return {'kind': 'ml_alarm', 'severity': 'warning', 'title': 'إنذار تجريبي', 'details': {'prediction': 1}}

    def test_reopen_preserves_readings_events_settings_and_acknowledgement(self):
        reading, added = self.store.append_reading(self.session, 0, '2026-10-17T10:00:00',
          {'sensors': {'pH': 7.2, 'Turb': None}, 'prediction': -1}, events=[self.event()])
        self.assertTrue(added); event = self.store.events()[0]
        ack = self.store.acknowledge(event['id']); self.store.update_settings({'siteName': 'مورد', 'display': {'language': 'ar'}})
        self.store.close(); self.store = Store(self.path)
        self.assertEqual(self.store.readings()[0], reading)
        self.assertEqual(self.store.event(event['id']), ack)
        self.assertEqual(self.store.settings()['siteName'], 'مورد')
        self.assertEqual(self.store.session(self.session)['metadata']['cadenceSeconds'], 60)
        self.assertEqual(self.store.counts()['unacknowledgedEvents'], 0)

    def test_retry_is_idempotent_and_conflicting_payload_rejected(self):
        args = (self.session, 2, '2026-10-17T10:00:00Z', {'value': 0.})
        first, _ = self.store.append_reading(*args, events=[self.event()])
        second, added = self.store.append_reading(*args, events=[self.event()])
        self.assertFalse(added); self.assertEqual(first, second)
        self.assertEqual(self.store.counts()['events'], 1)
        with self.assertRaises(ValidationError):
            self.store.append_reading(self.session, 2, args[2], {'value': 1.})
        self.assertEqual(self.store.counts()['readings'], 1)

    def test_invalid_values_event_or_foreign_key_commit_nothing(self):
        for data in ({'bad': float('nan')}, {'bad': float('inf')}, {2: 'nonstring'}, {'bad': {1}}):
            with self.assertRaises(ValidationError): self.store.append_reading(self.session, 0, '2026-10-17T10:00:00', data)
        with self.assertRaises(ValidationError):
            self.store.append_reading(self.session, 0, '2026-10-17T10:00:00', {}, events=[{'kind': 'x'}])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_reading('no_session', 0, '2026-10-17T10:00:00', {}, events=[self.event()])
        self.assertEqual(self.store.counts()['readings'], 0); self.assertEqual(self.store.counts()['events'], 0)

    def test_settings_write_validates_all_before_commit(self):
        self.store.update_settings({'siteName': 'old'})
        with self.assertRaises(ValidationError): self.store.update_settings({'siteName': 'new', 'bad': float('nan')})
        self.assertEqual(self.store.settings(), {'siteName': 'old'})

    def test_mid_batch_conflict_rolls_back_earlier_insert_and_events(self):
        records = [{'sequence': 0, 'timestamp': '2026-10-17T10:00:00', 'data': {'v': 1}, 'events': [self.event()]},
                   {'sequence': 0, 'timestamp': '2026-10-17T10:00:00', 'data': {'v': 2}}]
        with self.assertRaises(ValidationError): self.store.append_readings(self.session, records)
        self.assertEqual(self.store.counts()['readings'], 0); self.assertEqual(self.store.counts()['events'], 0)

    def test_acknowledge_idempotent_without_changing_safety_data(self):
        event = self.store.add_event(self.event(), session_id=self.session)
        first = self.store.acknowledge(event['id']); second = self.store.acknowledge(event['id'])
        self.assertEqual(first, second); self.assertEqual(first['details'], {'prediction': 1})
        with self.assertRaises(NotFoundError): self.store.acknowledge(999)

    def test_new_session_never_deletes_history_and_queries_are_bounded(self):
        for sequence in range(4): self.store.append_reading(self.session, sequence, '2026-10-17T10:00:00', {'sequence': sequence})
        other = self.store.create_session('reset')
        self.store.append_reading(other, 0, '2026-10-17T10:01:00', {'new': True})
        self.assertEqual(len(self.store.readings(session_id=self.session)), 4)
        self.assertEqual([r['sequence'] for r in self.store.readings(limit=2, session_id=self.session)], [2, 3])
        for value in (True, 0, -1, 1001):
            with self.assertRaises(ValidationError): self.store.readings(limit=value)
        with self.assertRaises(ValidationError): self.store.append_reading(other, True, '2026-10-17T10:01:00', {})
        with self.assertRaises(ValidationError): self.store.append_reading(other, 1, '2026-10-17', {})


if __name__ == '__main__': unittest.main()
