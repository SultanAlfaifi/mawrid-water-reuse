"""End-to-end HTTP/SQLite/inference verification on the qualified public inputs.

Uses a fresh temporary database and ephemeral loopback port. Does not train,
change models, read annotation columns, or alter the operator's database.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
from html.parser import HTMLParser
from pathlib import Path
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

SYSTEM = Path(__file__).resolve().parents[1]
ROOT = SYSTEM.parent
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT))
from server.app import Application
from server.main import LocalServer


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(output):
    if output.exists():
        raise FileExistsError('Preserve previous evidence; choose a new output path')
    import numpy as np
    import pandas as pd
    started = time.perf_counter()
    evidence = {'created_at': datetime.now(timezone.utc).isoformat(), 'passed': False,
                'scope': 'Local application HTTP, SQLite and genuine qualified V9 inference; not field readiness or improved model acceptance.',
                'cases': [], 'hardware_connected': False, 'fresh_validation': False}
    with tempfile.TemporaryDirectory(prefix='mawrid-system-verification-') as temporary:
        database = Path(temporary) / 'isolated.sqlite3'
        app = Application(database)
        server = LocalServer(0, app)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'

        def request(path, body=None, method=None, expected=200, headers=None, raw=False):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data,
                headers={'Content-Type': 'application/json', **(headers or {})}, method=method)
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    status, payload = response.status, response.read()
            except urllib.error.HTTPError as error:
                status, payload = error.code, error.read()
            assert status == expected, (path, status, payload[:200])
            return payload if raw else json.loads(payload)

        try:
            class Links(HTMLParser):
                def __init__(self):
                    super().__init__(); self.paths = []
                def handle_starttag(self, tag, attrs):
                    if tag == 'a':
                        self.paths.extend(value for key, value in attrs if key == 'href')
            state = request('/api/state')
            report_path = state['links']['model_report']
            links = Links(); links.feed(request(report_path, raw=True).decode())
            local_evidence = [urlsplit(urljoin(base + report_path, path)).path for path in links.paths
                              if urljoin(base + report_path, path).startswith(base + '/evidence/')]
            assert len(local_evidence) == 9
            for path in local_evidence:
                assert request(path, raw=True)
            assert request(state['links']['viewer'], raw=True)
            evidence['all_nine_relative_report_links_and_viewer'] = True
            request('/api/sessions', {'source_id': '2019_disclosed_test'}, expected=400)
            request('/api/sessions', {'source_id': '2019_disclosed_test', 'research_ack': True},
                    expected=403, headers={'Origin': 'https://untrusted.example'})
            request('/api/control/open', {}, expected=404)
            request('/api/settings', {'ph_min': 10, 'ph_max': 5}, method='PATCH', expected=400)
            for case in ('2019_disclosed_test', '2019-04'):
                case_started = time.perf_counter()
                state = request('/api/sessions', {'source_id': case, 'research_ack': True})
                session = state['session']['id']
                assert state['model']['acceptance_passed'] is False
                assert state['model']['provenance']['labels_used'] is False
                for _ in range(64):
                    state = request('/api/replay/step', {'count': 25})
                assert state['session']['position'] == 1600
                assert request('/api/state')['session']['position'] == 1600
                assert request('/api/state')['session']['position'] == 1600
                assert state['session']['status'] == 'completed'
                assert state['overview']['measured_irrigation_liters'] is None
                assert state['overview']['valve_state'] == 'closed'
                rows = list(csv.DictReader(io.StringIO(request('/api/export/readings.csv', raw=True).decode('utf-8-sig'))))
                rows = [row for row in rows if row['session_id'] == session]
                assert len(rows) == 1600
                assert [int(row['sample_index']) for row in rows] == list(range(1600))
                proof = json.loads((ROOT/'output/ml/gecco-stream-fidelity/input_qualification.json').read_text())
                original_input = next(item for item in proof['cases'] if item['case_id'] == case)
                sensor_rows = pd.read_csv(ROOT/original_input['csv_path'], float_precision='round_trip')
                np.testing.assert_array_equal(pd.to_datetime([row['timestamp'] for row in rows]).asi8,
                                              pd.to_datetime(sensor_rows.timestamp).array.asi8)
                for channel in original_input['columns'][1:]:
                    exported = np.array([float(row['sensor_' + channel]) if row['sensor_' + channel] else np.nan for row in rows])
                    np.testing.assert_allclose(exported, sensor_rows[channel], rtol=0, atol=0, equal_nan=True)
                reference_path = ROOT / 'output/ml/gecco-v9-development/run_01' / case / 'predictions.csv.gz'
                reference = pd.read_csv(reference_path, nrows=1600, usecols=['baseline', 'reference', 'candidate', 'long_context'], float_precision='round_trip')
                for saved, actual in (('baseline','baseline_prediction'), ('reference','reference_prediction'), ('candidate','prediction')):
                    np.testing.assert_array_equal([int(row[actual]) for row in rows], reference[saved])
                scores = np.array([float(row['score']) if row['score'] else np.nan for row in rows])
                np.testing.assert_allclose(scores, reference.long_context, rtol=0, atol=1e-12, equal_nan=True)
                normal = reference.long_context.to_numpy()
                error = float(np.max(np.abs(scores[np.isfinite(scores)] - normal[np.isfinite(scores)])))
                evidence['cases'].append({'source': case, 'rows': len(rows), 'exact_predictions': True,
                    'score_max_absolute_error': error, 'saved_prediction_sha256': digest(reference_path),
                    'exact_input_clock_and_sensors': True,
                    'elapsed_seconds': time.perf_counter() - case_started})
                print(json.dumps({'verified_case': case, 'rows': 1600}), flush=True)
            alarms = request('/api/alarms')['alarms']
            if alarms:
                state = request(f"/api/alarms/{alarms[0]['id']}/ack", {'note': 'Integration verification'})
                assert next(row for row in state['alarms'] if row['id'] == alarms[0]['id'])['acknowledged_at']
            request('/api/control/stop', {})
            state = request('/api/sessions', {'source_id': 'telemetry'})
            assert state['overview']['valve_state'] == 'closed'
            request('/api/control/reset', {})
            now = datetime.now(timezone.utc)
            record = {'device_id': 'synthetic-integration-fixture', 'timestamp': now.isoformat(),
                      'channels': {'turbidity': 0.8, 'ph': 7.2, 'chlorine': 0.3, 'flow_lpm': 1.5}}
            state = request('/api/readings', record)
            assert state['model']['status'] == 'unavailable'
            assert state['latest']['available'] is False
            assert state['overview']['valve_state'] == 'closed'
            request('/api/readings', record, expected=409)
            future = {**record, 'timestamp': (now + timedelta(days=1)).isoformat()}
            request('/api/readings', future, expected=400)
            report = request('/api/report')
            assert report['measured_irrigation_liters'] is None
            evidence['http_validation'] = ['explicit research scope', 'cross-origin rejection', 'no open actuator route',
                'settings validation', 'acknowledgement', 'duplicate/future device clocks', 'telemetry ML unavailable']
            evidence['records_before_restart'] = app.store.counts()
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=5); app.close()
        reopened = Application(database)
        try:
            assert reopened.store.counts() == evidence['records_before_restart']
            assert reopened.state()['session']['status'] == 'idle'
            assert reopened.state()['latest'] is None
            evidence['restart_preserves_records_requires_new_session'] = True
        finally:
            reopened.close()
    evidence['code_sha256'] = {str(path.relative_to(ROOT)): digest(path)
        for directory in ('server', 'client') for path in (SYSTEM/directory).rglob('*')
        if path.is_file() and path.suffix in ('.py', '.js', '.css', '.html')}
    evidence['contract_sha256'] = digest(SYSTEM/'CONTRACT.json')
    evidence.update(passed=True, elapsed_seconds=time.perf_counter() - started)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'passed': True, 'cases': len(evidence['cases']), 'evidence': str(output)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    verify(parser.parse_args().output.resolve())
