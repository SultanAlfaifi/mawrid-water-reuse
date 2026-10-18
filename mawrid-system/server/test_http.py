"""Loopback synthetic API integration; no real engine or external calls."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urljoin

from .app import Application
from .main import LocalServer
from .test_app import FakeEngine


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        self.engine = FakeEngine(); self.app = Application(root/'test.db', engine=self.engine)
        client = root/'client'; client.mkdir(); (client/'index.html').write_text('<h1>Mawrid fixture</h1>')
        (root/'secret.txt').write_text('must not serve')
        self.server = LocalServer(0, self.app, client_root=client, asset_roots={})
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.app.close(); self.temp.cleanup()
    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        body = None if data is None else json.dumps(data)
        options = {'Content-Type': 'application/json'} if data is not None else {}
        options.update(headers or {})
        connection.request(method, path, body=body, headers=options)
        response = connection.getresponse(); raw = response.read(); status = response.status; response_headers = dict(response.getheaders()); connection.close()
        return status, raw, response_headers
    def test_api_state_does_not_score_and_sessions_step_persistence_exports(self):
        status, body, _ = self.request('GET', '/api/state')
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)['session']['status'], 'idle')
        self.assertEqual(self.engine.calls, 0)
        self.assertEqual(self.request('POST', '/api/sessions', {'source_id':'2019_disclosed_test','research_ack':True})[0], 200)
        self.assertEqual(self.request('POST', '/api/replay/step', {'count':3})[0], 200)
        status, body, _ = self.request('GET','/api/readings?limit=100')
        self.assertEqual(len(json.loads(body)['readings']), 3)
        status, body, headers = self.request('GET','/api/export/readings.csv')
        self.assertEqual(status,200); self.assertTrue(body.startswith(b'\xef\xbb\xbf'))
        self.assertIn('attachment',headers['Content-Disposition'])
        for _ in range(2): self.request('GET','/api/state')
        self.assertEqual(self.engine.calls,1)
    def test_cross_origin_content_type_bad_json_limit_and_actuation_rejected(self):
        for headers, expected in (({'Origin':'https://attacker.invalid'},403), ({'Origin':'null'},403),
                                  ({'Content-Type':'text/plain'},415), ({'Host':'attacker.invalid'},403)):
            self.assertEqual(self.request('POST','/api/control/stop',{},headers)[0],expected)
        for count in (True,0,26,'4'):
            self.assertEqual(self.request('POST','/api/replay/step',{'count':count})[0],400)
        self.assertEqual(self.request('POST','/api/control/open',{})[0],404)
        self.assertEqual(self.request('GET','/api/readings?limit=1001')[0],400)
        connection = http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('POST','/api/control/stop',body='{"note":NaN}',headers={'Content-Type':'application/json'})
        response=connection.getresponse();self.assertEqual(response.status,400);response.read();connection.close()
    def test_static_paths_confined_and_errors_are_json_without_traceback(self):
        self.assertEqual(self.request('GET','/')[0],200)
        for path in ('/%2e%2e/secret.txt','/api/does-not-exist','/viewer/not-built.js'):
            status,body,_=self.request('GET',path);self.assertEqual(status,404)
            self.assertIn('error',json.loads(body));self.assertNotIn('Traceback',body.decode())
        self.assertEqual(self.request('GET','/',headers={'Host':'attacker.invalid'})[0],403)

    def test_evidence_report_relative_links_reach_sibling_audits_and_prior_report(self):
        root = Path(self.temp.name)/'output/ml'
        documents = {'gecco-v9/report.html': '<a href="../gecco-v9-development/run_01/audit.json">Audit</a><a href="../gecco-v8/report.html">Prior</a>',
                     'gecco-v9-development/run_01/audit.json': '{"passed":true,"synthetic":true}',
                     'gecco-v8/report.html': '<h1>Prior synthetic report</h1>'}
        for relative, content in documents.items():
            path = root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content)
        self.server.asset_roots['/evidence/'] = root
        report_url = self.app.state()['links']['model_report']
        self.assertEqual(report_url, '/evidence/gecco-v9/report.html')
        self.assertEqual(self.app.contract['state']['links']['model_report'], report_url)
        self.assertEqual(self.request('GET',report_url)[0],200)
        for relative in ('../gecco-v9-development/run_01/audit.json','../gecco-v8/report.html'):
            resolved = urljoin(report_url,relative)
            status,body,_ = self.request('GET',resolved)
            self.assertEqual(status,200); self.assertIn(b'synthetic',body.lower())
        self.assertEqual(self.request('GET',urljoin(report_url,'../missing/audit.json'))[0],404)
        self.assertEqual(self.request('GET','/evidence/%2e%2e/secret.txt')[0],404)


if __name__ == '__main__': unittest.main()
