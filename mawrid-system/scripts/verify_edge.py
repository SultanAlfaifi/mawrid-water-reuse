#!/usr/bin/env python3
"""Synthetic collector integration through real isolated Mawrid HTTP/SQLite.

No live database, sensor file, ML bundle, hardware or non-loopback endpoint is
opened. The only fault injection closes the first successful ingestion reply
after the unmodified application has committed its reading/events/receipt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

SYSTEM = Path(__file__).resolve().parents[1]
WORKSPACE = SYSTEM.parent
sys.path.insert(0, str(SYSTEM))

from edge.core import Outbox, canonical_json, ingest_file
from edge.sender import LocalTransport, flush_once
from server.app import Application
from server.main import Handler, LocalServer
from server.test_app import FakeEngine

OUTPUT = WORKSPACE / 'output/mawrid-system/edge-integration-v3.json'
CODE_PATHS = (
    'mawrid-system/CONTRACT.json', 'mawrid-system/server/app.py',
    'mawrid-system/server/store.py', 'mawrid-system/server/main.py',
    'mawrid-system/server/test_app.py', 'mawrid-system/edge/core.py',
    'mawrid-system/edge/sender.py', 'mawrid-system/edge/main.py',
    'mawrid-system/scripts/verify_edge.py',
)


def code_hashes():
    return {name: hashlib.sha256((WORKSPACE/name).read_bytes()).hexdigest() for name in CODE_PATHS}


class LostReplyHandler(Handler):
    """All routing/validation/commit code stays in the real server Handler."""
    def log_message(self, *args):
        pass

    def _json(self, value, status=200):
        receipt = value.get('ingestion') if isinstance(value, dict) else None
        if self.path == '/api/readings' and status == 200 and receipt is not None:
            self.server.receipts_returned.append(dict(receipt))
            if self.server.drop_next_receipt:
                self.server.drop_next_receipt = False
                self.server.dropped_receipt = dict(receipt)
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
        return super()._json(value, status)


class IsolatedServer:
    def __init__(self, path, *, drop_first=False):
        self.engine = FakeEngine()
        self.app = Application(path, engine=self.engine, start_plant_worker=False)
        self.http = LocalServer(0, self.app, asset_roots={})
        self.http.RequestHandlerClass = LostReplyHandler
        self.http.drop_next_receipt = drop_first
        self.http.dropped_receipt = None
        self.http.receipts_returned = []
        self.thread = threading.Thread(target=self.http.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.http.server_port

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError('Temporary HTTP server did not stop')
        self.app.close()

    def json_request(self, path, payload=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            body = canonical_json(payload).encode() if payload is not None else None
            connection.request('POST' if body is not None else 'GET', path, body=body,
                               headers={'Content-Type': 'application/json', 'Connection': 'close'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def counts(self):
        with self.app.store._lock:
            receipts = self.app.store._connection.execute('SELECT COUNT(*) FROM ingestion_receipts').fetchone()[0]
        return {**self.app.store.counts(), 'receipts': receipts}


class RecordingTransport(LocalTransport):
    def __init__(self, port):
        super().__init__(port)
        self.sent = []

    def send(self, row):
        self.sent.append({key: row[key] for key in ('measurement_id', 'session_id', 'payload_sha256')})
        return super().send(row)


def fixture(clock, offset):
    return {'timestamp': (clock+timedelta(seconds=offset)).isoformat(),
            'device_id': 'fixture-edge-http-integration',
            'channels': {'turbidity': .8, 'ph': 7.2, 'chlorine': .3, 'flow_lpm': 1.5}}


def verify():
    started = time.monotonic()
    report = {
        'schema_version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'passed': False,
        'scope': 'Synthetic transport/persistence integration only; no model or water-quality validation',
        'fixtures': {'kind': 'synthetic', 'device_id': 'fixture-edge-http-integration',
                     'clock': 'Verification wall clock minus30 seconds, then increasing one-second offsets',
                     'values': {'turbidity': .8, 'ph': 7.2, 'chlorine': .3, 'flow_lpm': 1.5}},
        'isolation': {'temporary_sqlite': True, 'loopback_ephemeral_port': True,
                      'engine': 'server.test_app.FakeEngine', 'plant_worker_enabled': False,
                      'live_db_accessed': False, 'real_sensors_accessed': False,
                      'ml_bundles_loaded': False, 'actuation': False},
        'code_sha256_before': code_hashes(),
        'checks': [],
        'limitations': [
            'This verifier exercises synthetic input over the real local HTTP application; it is not a hardware test.',
            'Durability starts at successful SQLite commit; unread/uncommitted stdin bytes are outside this guarantee.',
            'No guarantee against filesystem corruption or storage devices that violate fsync is established.',
        ],
    }

    def check(name, actual, expected=True):
        passed = actual == expected
        report['checks'].append({'name': name, 'passed': passed, 'actual': actual, 'expected': expected})
        if not passed:
            raise AssertionError(name)

    server = box = None
    try:
        with tempfile.TemporaryDirectory(prefix='mawrid-edge-verifier-') as temporary:
            temp = Path(temporary)
            server_path, outbox_path = temp/'server.sqlite3', temp/'outbox.sqlite3'
            server = IsolatedServer(server_path, drop_first=True)
            status, state = server.json_request('/api/sessions', {'source_id': 'telemetry'})
            check('telemetry_session_created_through_real_http', status, 200)
            sid = state['session']['id']
            clock = datetime.now(timezone.utc)-timedelta(seconds=30)
            source = temp/'fixture-readings.jsonl'
            source.write_text(''.join(canonical_json(fixture(clock, n))+'\n' for n in range(2)), encoding='utf-8')
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            box = Outbox(outbox_path)
            imported = ingest_file(box, source, sid, input_kind='fixture')
            check('two_fixture_rows_durably_queued', imported['queued'], 2)
            transport = RecordingTransport(server.port)
            first = flush_once(box, sid, transport)
            check('lost_reply_is_retry', first['state'], 'retry')
            check('only_first_row_sent_before_receipt', len(transport.sent), 1)
            first_id = transport.sent[0]['measurement_id']
            first_row = box.row(first_id)
            check('first_request_retained_without_receipt', first_row['receipt_json'], None)
            saved_receipt = server.http.dropped_receipt
            check('dropped_reply_belongs_to_committed_measurement', saved_receipt['measurement_id'], first_id)
            committed_counts = server.counts()
            check('one_server_reading_after_lost_reply', committed_counts['readings'], 1)
            check('one_atomic_receipt_after_lost_reply', committed_counts['receipts'], 1)
            check('server_receipt_matches_reading', server.app.store.ingestion_receipt(first_id)['reading_id'], saved_receipt['reading_id'])
            second = box.db.execute('SELECT * FROM outbox WHERE measurement_id!=?', (first_id,)).fetchone()
            second_id = second['measurement_id']
            check('fifo_second_row_never_attempted_yet', second['attempts'], 0)
            check('persisted_first_backoff_within_bounds', 0 < first_row['next_attempt_at']-time.time() <= 1.01)

            box.close()
            box = Outbox(outbox_path)
            check('outbox_restart_keeps_exact_request_bytes', box.row(first_id)['payload_json'], first_row['payload_json'])
            waiting = flush_once(box, sid, transport)
            check('restart_honors_backoff', waiting['state'], 'waiting')
            check('no_network_during_backoff', len(transport.sent), 1)
            wait_seconds = max(0, box.row(first_id)['next_attempt_at']-time.time())+.02
            check('verification_wait_bounded', wait_seconds <= 1.1)
            time.sleep(wait_seconds)
            retried = flush_once(box, sid, transport, max_items=1)
            check('one_retry_delivered', retried['delivered'], 1)
            check('retry_reuses_exact_id_session_payload_hash', transport.sent[1], transport.sent[0])
            receipt = json.loads(box.row(first_id)['receipt_json'])
            check('retry_receipt_is_duplicate', receipt['duplicate'])
            check('retry_keeps_original_reading_id', receipt['reading_id'], saved_receipt['reading_id'])
            check('retry_adds_no_reading_receipt_or_event', server.counts(), committed_counts)
            check('second_still_pending_after_first_receipt', box.row(second_id)['attempts'], 0)
            rest = flush_once(box, sid, transport)
            check('second_reading_sent_after_verified_first_receipt', rest['state'], 'empty')
            check('exactly_two_readings', server.counts()['readings'], 2)
            check('exactly_two_receipts', server.counts()['receipts'], 2)
            check('fifo_order_preserved_on_server',
                  [r['data']['measurement_id'] for r in server.app.store.readings(session_id=sid)], [first_id, second_id])
            check('fixture_input_unchanged', hashlib.sha256(source.read_bytes()).hexdigest(), source_sha)
            check('no_inference_during_ingestion', server.engine.calls, 0)

            before_restart = server.counts()
            server.close()
            server = IsolatedServer(server_path)
            transport = RecordingTransport(server.port)
            _, idle = server.json_request('/api/state')
            check('server_restart_does_not_resume_session', idle['session']['id'], None)
            historical = transport.send(first_row)
            check('historical_receipt_after_restart_accepted', historical.action, 'delivered')
            check('historical_receipt_preserves_reading_id', historical.receipt['reading_id'], saved_receipt['reading_id'])
            check('historical_receipt_marked_duplicate', historical.receipt['duplicate'])
            check('historical_retry_no_db_effect', server.counts(), before_restart)
            _, idle_after = server.json_request('/api/state')
            check('historical_retry_does_not_create_current_latest', idle_after['latest'], None)

            status, new_state = server.json_request('/api/sessions', {'source_id': 'telemetry'})
            check('second_session_created', status, 200)
            new_sid = new_state['session']['id']
            check('new_session_distinct', new_sid != sid)
            current_row = box.enqueue(fixture(clock, 3), new_sid, input_kind='fixture')
            check('explicit_new_session_delivered', flush_once(box, new_sid, transport)['state'], 'empty')
            _, current = server.json_request('/api/state')
            check('current_latest_is_new_session_measurement', current['latest']['measurement_id'], current_row['measurement_id'])
            historical_again = transport.send(first_row)
            check('old_receipt_allowed_after_session_switch', historical_again.receipt['duplicate'])
            _, after_duplicate = server.json_request('/api/state')
            check('old_receipt_does_not_replace_current_latest', after_duplicate['latest'], current['latest'])
            check('old_receipt_does_not_replace_current_telemetry_receipt',
                  after_duplicate['telemetry']['last_receipt'], current['telemetry']['last_receipt'])
            stale_row = box.enqueue(fixture(clock, 2), sid, input_kind='fixture')
            before_rejection = server.counts()
            blocked = flush_once(box, sid, transport)
            check('old_session_new_measurement_blocks', blocked['state'], 'blocked')
            check('exact_inactive_session_code', blocked['error_code'], 'session_not_active')
            check('blocked_row_keeps_original_session', json.loads(box.row(stale_row['measurement_id'])['payload_json'])['session_id'], sid)
            check('blocked_row_keeps_no_false_receipt', box.row(stale_row['measurement_id'])['receipt_json'], None)
            check('inactive_request_no_db_effect', server.counts(), before_rejection)
            request_count = len(transport.sent)
            box.close()
            box = Outbox(outbox_path)
            check('blocked_state_survives_collector_restart', flush_once(box, sid, transport)['state'], 'blocked')
            check('blocked_row_not_resent_or_rebound', len(transport.sent), request_count)
            _, final_state = server.json_request('/api/state')
            check('session_switch_remains_explicit', final_state['session']['id'], new_sid)
            check('current_latest_preserved_after_rejection', final_state['latest'], current['latest'])
            check('hardware_not_connected', final_state['app']['hardware_connected'], False)
            check('software_valve_stays_closed', final_state['overview']['valve_state'], 'closed')
            check('telemetry_model_unavailable', final_state['model']['status'], 'unavailable')
            check('no_inference_after_restart', server.engine.calls, 0)
            report['summary'] = {
                'synthetic_rows_delivered': server.counts()['readings'],
                'persisted_receipts': server.counts()['receipts'],
                'old_session_delivered_rows': len(server.app.store.readings(session_id=sid)),
                'new_session_delivered_rows': len(server.app.store.readings(session_id=new_sid)),
                'retained_blocked_rows': box.status(sid)['sessions'][sid]['blocked'],
                'original_reading_id_after_lost_reply_and_server_restart': saved_receipt['reading_id'],
            }
            report['edge_review'] = {
                'scope': 'Read-only review during integration; not a comprehensive security audit',
                'blocking_defects_found': [],
                'observations': [
                    'Confirmed durable FIFO, stable IDs, verified receipts, explicit sessions and fail-stop409 on this HTTP path.',
                    'File checkpoints are keyed by resolved path and session, not a globally unique source file identity; copies or renamed files imported again receive new IDs.',
                    'Restreaming stdin is a new import, not automatic deduplication of identical sensor content.',
                    'Blocked rows have no automatic repair/rebind command and remain available for manual diagnosis.',
                ],
            }
            box.close(); box = None
            server.close(); server = None
        check('temporary_fixture_databases_removed', not temp.exists())
        report['code_sha256_after'] = code_hashes()
        check('relevant_code_unchanged_during_verification', report['code_sha256_after'], report['code_sha256_before'])
        report['passed'] = True
    except Exception as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        if box is not None:
            box.close()
        if server is not None:
            server.close()
        report['elapsed_seconds'] = time.monotonic()-started
        report['checks_passed'] = sum(item['passed'] for item in report['checks'])
        report['checks_total'] = len(report['checks'])
    return report


def main():
    report = verify()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        old = json.loads(OUTPUT.read_text())
        report['previous_attempts'] = [*old.pop('previous_attempts', []), old]
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks_passed': report['checks_passed'],
                      'checks_total': report['checks_total'], 'output': str(OUTPUT),
                      'failure': report.get('failure')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
