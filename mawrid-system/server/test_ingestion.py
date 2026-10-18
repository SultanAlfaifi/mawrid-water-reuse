"""Reliable local telemetry delivery, independent of models and field data."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid

from .app import Application, APIError
from .store import ValidationError
from .test_app import FakeEngine


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'isolated.sqlite3'
        self.app = Application(self.path, engine=FakeEngine())
        self.sid = self.app.start({'source_id': 'telemetry'})['session']['id']
        self.clock = datetime.now(timezone.utc) - timedelta(seconds=10)

    def tearDown(self):
        self.app.close(); self.temp.cleanup()

    def payload(self, offset=0):
        return {'session_id': self.sid, 'measurement_id': str(uuid.uuid4()),
                'timestamp': (self.clock + timedelta(seconds=offset)).isoformat(),
                'device_id': 'local-collector-test',
                'channels': {'turbidity': .8, 'ph': 7.2, 'chlorine': .3, 'flow_lpm': 1.5}}

    def test_lost_reply_retry_keeps_one_reading_one_original_receipt(self):
        body = self.payload()
        first = self.app.ingest(body)
        counts = self.app.store.counts()
        duplicate = self.app.ingest(deepcopy(body))
        self.assertFalse(first['ingestion']['duplicate'])
        self.assertTrue(duplicate['ingestion']['duplicate'])
        self.assertEqual(first['ingestion']['reading_id'], duplicate['ingestion']['reading_id'])
        self.assertEqual(self.app.store.counts(), counts)
        self.assertEqual(duplicate['session']['position'], 1)
        self.assertEqual(duplicate['telemetry']['last_receipt']['measurement_id'], body['measurement_id'])
        self.assertFalse(duplicate['app']['hardware_connected'])
        self.assertEqual(duplicate['model']['status'], 'unavailable')

    def test_conflicting_content_or_session_never_reuses_id(self):
        body = self.payload(); self.app.ingest(body)
        changed = deepcopy(body); changed['channels']['ph'] = 9
        for bad in (changed, {**body, 'session_id': str(uuid.uuid4())}):
            with self.assertRaises(APIError) as result: self.app.ingest(bad)
            self.assertEqual(result.exception.code, 'idempotency_conflict')
        self.assertEqual(self.app.store.counts()['readings'], 1)

    def test_old_clock_with_new_id_is_not_a_retry(self):
        body = self.payload(); self.app.ingest(body)
        with self.assertRaises(APIError) as result:
            self.app.ingest({**body, 'measurement_id': str(uuid.uuid4())})
        self.assertEqual(result.exception.code, 'nonincreasing_timestamp')

    def test_receipt_survives_restart_without_resuming_old_session(self):
        body = self.payload(); first = self.app.ingest(body)['ingestion']
        self.app.close(); self.app = Application(self.path, engine=FakeEngine())
        retried = self.app.ingest(body)
        self.assertIsNone(retried['session']['id'])
        self.assertIsNone(retried['latest'])
        self.assertEqual(retried['ingestion']['reading_id'], first['reading_id'])
        self.assertTrue(retried['ingestion']['duplicate'])
        with self.assertRaises(APIError) as result: self.app.ingest(self.payload(1))
        self.assertEqual(result.exception.code, 'session_not_active')
        self.assertEqual(self.app.store.counts()['readings'], 1)

    def test_retry_of_old_session_does_not_replace_current_measurement(self):
        old = self.payload(); self.app.ingest(old)
        self.sid = self.app.start({'source_id': 'telemetry'})['session']['id']
        new = self.payload(1); current = self.app.ingest(new)
        retried = self.app.ingest(old)
        self.assertEqual(retried['ingestion']['session_id'], old['session_id'])
        self.assertEqual(retried['session']['id'], self.sid)
        self.assertEqual(retried['latest'], current['latest'])
        self.assertEqual(retried['telemetry']['last_receipt'], current['telemetry']['last_receipt'])
        with self.assertRaises(APIError) as result:
            self.app.ingest({**old, 'measurement_id': str(uuid.uuid4())})
        self.assertEqual(result.exception.code, 'session_not_active')

    def test_receipt_insert_failure_rolls_back_reading_and_alarm_together(self):
        body = self.payload(); body['channels']['ph'] = 10
        before = self.app.store.counts()
        self.app.store._connection.execute("""CREATE TRIGGER fail_receipt BEFORE INSERT ON ingestion_receipts
          BEGIN SELECT RAISE(ABORT,'synthetic receipt commit failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError): self.app.ingest(body)
        self.assertEqual(self.app.store.counts(), before)
        self.assertEqual(self.app.position, 0)
        self.assertIsNone(self.app.store.ingestion_receipt(body['measurement_id']))
        self.assertIsNone(self.app._last_telemetry_clock)
        self.app.store._connection.execute('DROP TRIGGER fail_receipt')
        self.app.ingest(body)
        self.assertEqual(self.app.position, 1)
        self.assertEqual(self.app.store.counts()['readings'], 1)
        self.assertEqual(len([e for e in self.app.store.events() if e['kind'] == 'safety']), 1)

    def test_concurrent_same_measurement_commits_once(self):
        body = self.payload(); barrier = threading.Barrier(5); responses, errors = [], []
        def send():
            try:
                barrier.wait(); responses.append(self.app.ingest(deepcopy(body))['ingestion'])
            except Exception as error: errors.append(error)
        threads = [threading.Thread(target=send) for _ in range(5)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertFalse(errors)
        self.assertEqual(len(responses), 5)
        self.assertEqual(sum(not r['duplicate'] for r in responses), 1)
        self.assertEqual(len({r['reading_id'] for r in responses}), 1)
        self.assertEqual(self.app.position, 1)

    def test_paired_uuid_and_explicit_four_channel_schema(self):
        body = self.payload()
        cases = []
        for missing in ('session_id', 'measurement_id'):
            bad = deepcopy(body); bad.pop(missing); cases.append(bad)
        for bad_id in (None, True, 1, 'not-uuid', str(uuid.uuid4()).upper()):
            cases.append({**body, 'measurement_id': bad_id})
        bad = deepcopy(body); bad['channels'].pop('chlorine'); cases.append(bad)
        for bad in cases:
            with self.assertRaises(ValidationError): self.app.ingest(bad)
        self.assertEqual(self.app.store.counts()['readings'], 0)

    def test_additive_receipt_schema_migration_preserves_existing_data(self):
        self.app.ingest({'timestamp': self.clock.isoformat(), 'device_id': 'legacy', 'channels': {'ph': 7.2}})
        self.app.store._connection.execute('DROP TABLE ingestion_receipts')
        self.app.store._connection.execute('PRAGMA user_version=1')
        before = self.app.store.counts()
        self.app.close(); self.app = Application(self.path, engine=FakeEngine())
        self.assertEqual(self.app.store.counts(), before)
        self.assertIsNone(self.app.store.ingestion_receipt(str(uuid.uuid4())))
        self.assertIsNone(self.app.state()['telemetry']['session_id'])


if __name__ == '__main__':
    unittest.main()
