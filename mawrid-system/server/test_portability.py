"""Clean-copy bootstrap and packaged assets; no ML, dependencies or live DB."""
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest.mock import patch

from .app import Application
from .main import LocalServer, SYSTEM
from .test_app import FakeEngine


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        # Deliberately omit ml/, node_modules/ and all local runtime data.
        self.clone = self.root/'clean copy with spaces'/'mawrid-system'
        self.clone.mkdir(parents=True)
        shutil.copy2(SYSTEM/'start.command', self.clone/'start.command')
        shutil.copy2(SYSTEM/'CONTRACT.json', self.clone/'CONTRACT.json')
        shutil.copytree(SYSTEM/'server', self.clone/'server',
                        ignore=shutil.ignore_patterns('__pycache__', 'test_*.py'))

    def tearDown(self):
        self.temp.cleanup()

    def launch_help(self, env):
        return subprocess.run([str(self.clone/'start.command'), '--help'],
                              cwd=self.root, env=env, text=True,
                              capture_output=True, timeout=15)

    def test_clean_copy_bootstraps_with_explicit_python_and_path_fallback(self):
        env = dict(os.environ)
        env['MAWRID_PYTHON'] = sys.executable
        explicit = self.launch_help(env)
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertIn('--database', explicit.stdout)
        env.pop('MAWRID_PYTHON')
        binary = self.root/'bin'; binary.mkdir()
        (binary/'python3').symlink_to(sys.executable)
        env['PATH'] = str(binary) + os.pathsep + os.defpath
        fallback = self.launch_help(env)
        self.assertEqual(fallback.returncode, 0, fallback.stderr)
        self.assertIn('--database', fallback.stdout)
        self.assertFalse((self.clone.parent/'ml').exists())
        self.assertFalse((self.clone/'var').exists())

    def test_invalid_explicit_interpreter_is_reported_without_silent_fallback(self):
        env = dict(os.environ, MAWRID_PYTHON=str(self.root/'missing python'))
        result = self.launch_help(env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MAWRID_PYTHON', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_clean_packaged_copy_serves_virtual_plant_and_reports_missing_ml(self):
        shutil.copytree(SYSTEM/'client', self.clone/'client')
        # -I prevents the checkout, PYTHONPATH and user site packages from
        # satisfying a missing research module in the clean copy.
        probe = textwrap.dedent(r'''
            import http.client
            import json
            from pathlib import Path
            import re
            import sys
            import threading
            sys.path.insert(0, sys.argv[1])
            from server.app import Application
            from server.main import LocalServer, SYSTEM
            app = Application(Path(sys.argv[2]), start_plant_worker=False)
            server = LocalServer(0, app)
            worker = threading.Thread(target=server.serve_forever,
                kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            def request(method, path, value=None):
                connection = http.client.HTTPConnection(
                    '127.0.0.1', server.server_port, timeout=5)
                body = None if value is None else json.dumps(value)
                headers = {} if value is None else {'Content-Type': 'application/json'}
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                result = response.status, response.read()
                connection.close()
                return result
            try:
                assert not (SYSTEM.parent/'ml').exists()
                assert not (SYSTEM.parent/'node_modules').exists()
                assert not (SYSTEM/'.venv').exists()
                status, html = request('GET', '/')
                assert status == 200
                entry = re.search(rb'id="mawrid-entry"[^>]*src="([^"]+)"', html)
                assert entry, 'Packaged classic client entry missing'
                assert request('GET', '/' + entry[1].decode().removeprefix('./'))[0] == 200
                status, css = request('GET', '/styles.css')
                assert status == 200
                fonts = re.findall(rb"url\(['\"]?(\./assets/fonts/[^)'\"]+)", css)
                assert len(set(fonts)) == 4
                for font in fonts:
                    assert request('GET', '/' + font.decode().removeprefix('./'))[0] == 200
                status, scene = request('GET', '/plant3d/index.html')
                assert status == 200
                for asset in re.findall(rb'(?:src|href)="(\./assets/[^"]+)"', scene):
                    assert request('GET', '/plant3d/' + asset.decode().removeprefix('./'))[0] == 200
                for license_path in ['assets/fonts/OFL.txt',
                                     'plant3d/licenses/three-MIT.txt',
                                     'plant3d/licenses/IBM-Plex-Arabic-OFL.txt']:
                    assert (SYSTEM/'client'/license_path).is_file(), license_path
                status, body = request('POST', '/api/sessions',
                    {'source_id': 'virtual_plant', 'research_ack': True})
                assert status == 200
                state = json.loads(body)
                assert state['session']['status'] == 'ready'
                assert state['app']['hardware_connected'] is False
                assert state['virtual_plant']['virtual'] is True
                assert state['model']['status'] == 'unavailable'
                assert state['model']['provenance'] is None
                status, body = request('POST', '/api/sessions',
                    {'source_id': '2019_disclosed_test', 'research_ack': True})
                assert status == 503
                error = json.loads(body)['error']
                assert error['code'] == 'model_initialization_failed'
                assert 'البيئة المحلية' in error['message']
                assert b'Traceback' not in body and str(SYSTEM).encode() not in body
                state = app.state()
                assert state['session']['status'] == 'failed'
                assert state['latest'] is None and state['series'] == []
                assert state['model']['source_id'] is None
                assert state['model']['provenance'] is None
                for module in ['ml', 'numpy', 'pandas', 'sklearn', 'joblib']:
                    assert module not in sys.modules, module
                print('Clean packaged HTTP: assets, four fonts, virtual session and genuine missing-ML JSON 503 PASS')
            finally:
                server.shutdown(); server.server_close(); worker.join()
                app.close()
        ''')
        result = subprocess.run(
            [sys.executable, '-I', '-B', '-c', probe, str(self.clone), str(self.root/'clean.db')],
            cwd=self.root, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Clean packaged HTTP:', result.stdout)
        self.assertFalse((self.clone/'var').exists())


class PackagedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = FakeEngine()
        self.app = Application(Path(self.temp.name)/'test.db', engine=self.engine)
        self.server = LocalServer(0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.app.close(); self.temp.cleanup()

    def request(self, method, path, data=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Content-Type': 'application/json'} if data is not None else {}
        connection.request(method, path, body=None if data is None else json.dumps(data), headers=headers)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_every_declared_main_font_is_served_from_packaged_client_files(self):
        status, css, _ = self.request('GET', '/styles.css')
        self.assertEqual(status, 200)
        fonts = re.findall(r"url\(['\"]?(\./assets/fonts/[^)'\"]+)", css.decode())
        self.assertEqual(len(set(fonts)), 4)
        self.assertTrue(all('node_modules' not in str(root)
                            for root in self.server.asset_roots.values()))
        for relative in fonts:
            status, body, headers = self.request('GET', '/' + relative.removeprefix('./'))
            self.assertEqual(status, 200, relative)
            self.assertEqual(body, (SYSTEM/'client'/relative).read_bytes())
            self.assertIn('font', headers['Content-Type'])

    def test_missing_optional_model_returns_clear_json_without_internal_paths(self):
        with patch.object(self.engine, 'start', side_effect=FileNotFoundError('/private/model/bundle.joblib')):
            status, body, _ = self.request('POST', '/api/sessions',
                                           {'source_id': '2019_disclosed_test', 'research_ack': True})
        self.assertEqual(status, 503)
        error = json.loads(body)['error']
        self.assertEqual(error['code'], 'model_initialization_failed')
        self.assertIn('البيئة المحلية', error['message'])
        self.assertNotIn('/private/', body.decode())
        self.assertNotIn('Traceback', body.decode())
        self.assertEqual(self.app.state()['session']['status'], 'failed')
        self.assertIsNone(self.engine.source)


if __name__ == '__main__':
    unittest.main()
