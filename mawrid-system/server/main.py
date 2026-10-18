"""Loopback-only HTTP + SQLite Mawrid prototype. No hardware/actuator interface.

Run: python server/main.py [--port 8787] [--database var/mawrid.sqlite3]
The Python environment needs the already installed ML dependencies only when a
qualified replay starts. The HTTP server, persistence and telemetry use stdlib.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

SYSTEM = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(SYSTEM))
from server.app import Application, APIError, reading_record, alarm_record
from server.store import ValidationError, NotFoundError, integer

MAX_BODY = 65536


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, app, *, client_root=None, asset_roots=None):
        self.app = app
        self.client_root = Path(client_root or SYSTEM/'client').resolve()
        self.asset_roots = asset_roots if asset_roots is not None else {
            '/viewer/': SYSTEM.parent/'mawrid-final/dist',
            '/evidence/': SYSTEM.parent/'output/ml',
        }
        super().__init__(('127.0.0.1', port), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'MawridLocal/1'

    def log_message(self, fmt, *args):
        # Do not log sensor payloads, model paths or request bodies.
        sys.stderr.write('mawrid %s %s\n' % (self.command, self.path.split('?', 1)[0]))

    def _host(self):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            raise APIError(403, 'invalid_host', 'هذا الخادم محلي فقط.')

    def _mutation_body(self):
        self._host()
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        origin = self.headers.get('Origin')
        if origin is not None and origin not in allowed:
            raise APIError(403, 'origin_rejected', 'الطلبات المعدّلة يجب أن تأتي من التطبيق المحلي نفسه.')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise APIError(403, 'origin_rejected', 'طلب عابر للمواقع غير مسموح.')
        if self.headers.get_content_type() != 'application/json':
            raise APIError(415, 'json_required', 'استخدم Content-Type: application/json.')
        if self.headers.get('Transfer-Encoding'):
            raise APIError(400, 'invalid_body', 'ترميز الطلب غير مدعوم.')
        try: length = int(self.headers.get('Content-Length', '0'))
        except ValueError: raise APIError(400, 'invalid_length', 'طول الطلب غير صحيح.')
        if length < 0 or length > MAX_BODY:
            raise APIError(413, 'body_too_large', 'حجم الطلب يتجاوز الحد المحلي.')
        raw = self.rfile.read(length)
        if len(raw) != length: raise APIError(400, 'incomplete_body', 'لم يصل الطلب كاملًا.')
        def pairs(items):
            data = {}
            for key, value in items:
                if key in data: raise ValueError('duplicate key')
                data[key] = value
            return data
        try:
            data = json.loads(raw, object_pairs_hook=pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise APIError(400, 'invalid_json', 'JSON غير صالح؛ استخدم null للقياسات المفقودة.')
        if not isinstance(data, dict): raise APIError(400, 'object_required', 'يجب أن يكون الطلب كائن JSON.')
        return data

    def _json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error):
        if isinstance(error, APIError): status, code, message = error.status, error.code, error.message
        elif isinstance(error, ValidationError): status, code, message = 400, 'validation_error', str(error)
        elif isinstance(error, NotFoundError): status, code, message = 404, 'not_found', 'السجل المطلوب غير موجود.'
        else: status, code, message = 500, 'internal_error', 'تعذر إكمال العملية المحلية. بقي الصمام البرمجي مغلقًا.'
        self._json({'error': {'code': code, 'message': message}}, status)

    @staticmethod
    def _query_value(query, name, default):
        values = query.get(name, [default])
        if len(values) != 1: raise ValidationError('لا تكرر معاملات الطلب')
        return values[0]

    def _limit(self, query, default=100):
        raw = self._query_value(query, 'limit', str(default))
        if not re.fullmatch(r'[0-9]{1,4}', raw): raise ValidationError('حد عدد السجلات غير صحيح')
        return integer(int(raw), 'limit', 1, 1000)

    def _csv(self, kind):
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition', f'attachment; filename="mawrid-{kind}.csv"')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close'); self.end_headers(); self.close_connection = True
        for chunk in self.server.app.export_csv(kind): self.wfile.write(chunk)

    def _static(self, path):
        decoded = unquote(path)
        if '\x00' in decoded or '\\' in decoded or '..' in Path(decoded).parts:
            raise APIError(404, 'not_found', 'الملف غير موجود.')
        base, relative = self.server.client_root, decoded.lstrip('/')
        for prefix, root in self.server.asset_roots.items():
            if decoded.startswith(prefix): base, relative = Path(root).resolve(), decoded[len(prefix):]; break
        target = (base/relative).resolve()
        if not target.is_relative_to(base): raise APIError(404, 'not_found', 'الملف غير موجود.')
        if target.is_dir(): target = (target/'index.html').resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise APIError(404, 'not_found', 'الملف المحلي غير موجود.')
        if target.suffix.lower() not in {'.html','.css','.js','.json','.woff','.woff2','.ttf','.png','.jpg','.jpeg','.svg','.ico','.webp','.map'}:
            raise APIError(404, 'not_found', 'نوع الملف غير متاح في الواجهة.')
        self.send_response(200)
        content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        self.send_header('Content-Type', content_type + ('; charset=utf-8' if content_type.startswith('text/') or target.suffix in ('.js','.json') else ''))
        self.send_header('Content-Length', str(target.stat().st_size))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        with target.open('rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''): self.wfile.write(chunk)

    def do_GET(self):
        try:
            self._host()
            url = urlsplit(self.path); path, query = url.path, parse_qs(url.query, keep_blank_values=True)
            app = self.server.app
            if path == '/api/state': self._json(app.state())
            elif path == '/api/sources': self._json({'sources': list(app.sources.values())})
            elif path == '/api/settings': self._json({'settings': app.settings()})
            elif path == '/api/report': self._json(app.report())
            elif path == '/api/readings':
                if set(query) - {'limit', 'session_id'}: raise ValidationError('معامل غير معروف')
                session = self._query_value(query, 'session_id', None)
                if session is not None and (not session or len(session) > 100): raise ValidationError('معرف جلسة غير صحيح')
                self._json({'readings': [reading_record(r) for r in app.store.readings(limit=self._limit(query), session_id=session)]})
            elif path == '/api/alarms': self._json({'alarms': [alarm_record(r) for r in app.store.events(limit=self._limit(query))]})
            elif path == '/api/export/readings.csv': self._csv('readings')
            elif path == '/api/export/events.csv': self._csv('events')
            elif path.startswith('/api/'): raise APIError(404, 'not_found', 'مسار API غير موجود.')
            else: self._static(path)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception as error: self._error(error)

    def do_POST(self):
        try:
            data = self._mutation_body(); path = urlsplit(self.path).path; app = self.server.app
            routes = {'/api/sessions': app.start, '/api/replay/step': app.step,
                      '/api/replay/pause': app.pause, '/api/control/stop': app.stop,
                      '/api/control/reset': app.reset_hold, '/api/readings': app.ingest,
                      '/api/plant/control': app.plant_control}
            if path in routes: result = routes[path](data)
            elif match := re.fullmatch(r'/api/alarms/([1-9][0-9]{0,15})/ack', path):
                result = app.acknowledge(int(match.group(1)), data)
            else: raise APIError(404, 'not_found', 'لا يوجد هذا الأمر؛ لا تحكم بعتاد من التطبيق.')
            self._json(result)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception as error: self._error(error)

    def do_PATCH(self):
        try:
            data = self._mutation_body()
            if urlsplit(self.path).path != '/api/settings': raise APIError(404, 'not_found', 'المسار غير موجود.')
            self._json(self.server.app.update_settings(data))
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception as error: self._error(error)

    def do_OPTIONS(self): self._json({'error': {'code': 'method_not_allowed', 'message': 'لا وصول عابر للمواقع.'}}, 405)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--database', type=Path, default=SYSTEM/'var/mawrid.sqlite3')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('--port must be between1and65535')
    app = Application(args.database)
    server = LocalServer(args.port, app)
    print(f'Mawrid local prototype: http://127.0.0.1:{server.server_port} (hardware disconnected)', flush=True)
    try: server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt: pass
    finally:
        server.server_close(); app.close()


if __name__ == '__main__': main()
