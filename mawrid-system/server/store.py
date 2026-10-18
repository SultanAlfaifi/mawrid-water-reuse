"""Durable local records; no model inference, hardware commands or network I/O.

SQLite transactions retain a reading and its associated events together.
Resetting a runtime never removes historical records. All public writes reject
nonfinite JSON, so missing readings must be represented explicitly as None.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import threading
import uuid


class ValidationError(ValueError):
    pass


class NotFoundError(LookupError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def timestamp(value):
    # Source clocks may be timezone-naive historical replay clocks. Preserve
    # that fact instead of assigning a location or making them wall-clock data.
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValidationError('timestamp must be an ISO8601 string')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValidationError('timestamp must be an ISO8601 datetime') from error
    if 'T' not in value and ' ' not in value:
        raise ValidationError('timestamp must include a time')
    return parsed.isoformat()


def text(value, name, maximum=200, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValidationError(f'{name} must be a nonempty string of at most {maximum} characters')
    return value


def integer(value, name, low=0, high=2**53-1):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValidationError(f'{name} must be an integer between {low} and {high}')
    return value


def json_value(value, *, mapping=False, maximum_bytes=131072):
    if mapping and not isinstance(value, dict):
        raise ValidationError('A JSON object is required')
    def validate(item, depth=0):
        if depth > 12:
            raise ValidationError('JSON nesting is too deep')
        if item is None or isinstance(item, (str, bool)):
            return
        if isinstance(item, (int, float)):
            try: finite = math.isfinite(item)
            except OverflowError: finite = False
            if not finite: raise ValidationError('Nonfinite values are not allowed; use null for missing data')
            return
        if isinstance(item, list):
            for child in item: validate(child, depth + 1)
            return
        if isinstance(item, dict) and all(isinstance(k, str) for k in item):
            for child in item.values(): validate(child, depth + 1)
            return
        raise ValidationError('Only JSON values and string object keys are allowed')
    validate(value)
    try: encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (TypeError, ValueError, RecursionError) as error:
        raise ValidationError('Invalid JSON value') from error
    if len(encoded.encode('utf-8')) > maximum_bytes:
        raise ValidationError('JSON record exceeds size limit')
    return encoded


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute('PRAGMA foreign_keys=ON')
        self._connection.execute('PRAGMA journal_mode=WAL')
        self._connection.execute('PRAGMA synchronous=FULL')
        self._connection.execute('PRAGMA busy_timeout=10000')
        self._connection.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, created_at TEXT NOT NULL,
          metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS readings (
          id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
          sequence INTEGER NOT NULL CHECK(sequence>=0), timestamp TEXT NOT NULL,
          created_at TEXT NOT NULL, data_json TEXT NOT NULL,
          UNIQUE(session_id,sequence)
        );
        CREATE INDEX IF NOT EXISTS readings_session_id ON readings(session_id,id);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
          severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
          title TEXT NOT NULL, message TEXT NOT NULL, timestamp TEXT NOT NULL,
          created_at TEXT NOT NULL, session_id TEXT REFERENCES sessions(id),
          reading_id INTEGER REFERENCES readings(id), details_json TEXT NOT NULL,
          acknowledged_at TEXT, note TEXT
        );
        CREATE INDEX IF NOT EXISTS events_open_id ON events(acknowledged_at,id);
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ingestion_receipts (
          measurement_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL REFERENCES sessions(id),
          request_sha256 TEXT NOT NULL,
          reading_id INTEGER NOT NULL UNIQUE REFERENCES readings(id),
          accepted_at TEXT NOT NULL
        );
        PRAGMA user_version=2;
        ''')
        if 'note' not in {row[1] for row in self._connection.execute('PRAGMA table_info(events)')}:
            self._connection.execute('ALTER TABLE events ADD COLUMN note TEXT')

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._connection.execute('BEGIN IMMEDIATE')
            try:
                yield self._connection
                self._connection.execute('COMMIT')
            except BaseException:
                self._connection.execute('ROLLBACK')
                raise

    def close(self):
        with self._lock: self._connection.close()

    def create_session(self, source, metadata=None, *, session_id=None):
        source = text(source, 'source', 100)
        session_id = text(session_id or str(uuid.uuid4()), 'session_id', 100)
        encoded = json_value(metadata or {}, mapping=True)
        with self._transaction() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (session_id, source, utc_now(), encoded))
        return session_id

    def session(self, session_id):
        with self._lock:
            row = self._connection.execute('SELECT * FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None: raise NotFoundError('Session not found')
        return {'id': row['id'], 'source': row['source'], 'createdAt': row['created_at'],
                'metadata': json.loads(row['metadata_json'])}

    @staticmethod
    def _event_input(event):
        if not isinstance(event, dict): raise ValidationError('Event must be an object')
        allowed = {'kind', 'severity', 'title', 'message', 'timestamp', 'details'}
        if set(event) - allowed: raise ValidationError('Unsupported event fields')
        kind = text(event.get('kind'), 'event.kind', 80)
        severity = event.get('severity', 'info')
        if severity not in ('info', 'warning', 'critical'): raise ValidationError('Invalid event severity')
        title = text(event.get('title'), 'event.title', 200)
        message = text(event.get('message', ''), 'event.message', 2000, empty=True)
        observed = timestamp(event.get('timestamp', utc_now()))
        details = json_value(event.get('details', {}), mapping=True)
        return kind, severity, title, message, observed, details

    @staticmethod
    def _insert_event(db, values, session_id, reading_id):
        kind, severity, title, message, observed, details = values
        cursor = db.execute('''INSERT INTO events(kind,severity,title,message,timestamp,created_at,
          session_id,reading_id,details_json) VALUES(?,?,?,?,?,?,?,?,?)''',
          (kind, severity, title, message, observed, utc_now(), session_id, reading_id, details))
        return cursor.lastrowid

    def add_event(self, event, *, session_id=None, reading_id=None):
        values = self._event_input(event)
        if reading_id is not None: integer(reading_id, 'reading_id', 1)
        with self._transaction() as db:
            event_id = self._insert_event(db, values, session_id, reading_id)
        return self.event(event_id)

    def append_reading(self, session_id, sequence, observed_at, data, *, events=(), receipt=None):
        """Idempotent by session+sequence; different retries are rejected.

        The application owns sensor/model/safety schema validation. This layer
        additionally enforces finite JSON, source timestamps and atomic writes.
        """
        return self.append_readings(session_id, [{'sequence': sequence, 'timestamp': observed_at,
                                                  'data': data, 'events': events}], receipt=receipt)[0]

    def append_readings(self, session_id, records, *, receipt=None):
        """Commit a whole model step or none of it; never partial batches."""
        text(session_id, 'session_id', 100)
        if not isinstance(records, list) or len(records) > 25:
            raise ValidationError('At most 25 readings may be committed together')
        if receipt is not None:
            if (not isinstance(receipt, dict) or set(receipt) != {'measurement_id', 'request_sha256'}
                    or len(records) != 1):
                raise ValidationError('One receipt must belong to exactly one reading')
            text(receipt['measurement_id'], 'measurement_id', 64)
            digest = receipt['request_sha256']
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValidationError('Invalid receipt request digest')
        prepared = []
        for record in records:
            sequence = integer(record['sequence'], 'sequence')
            observed_at = timestamp(record['timestamp']); data = record['data']
            encoded = json_value(data, mapping=True)
            events = record.get('events', [])
            if not isinstance(events, (list, tuple)) or len(events) > 20:
                raise ValidationError('A reading may contain at most 20 events')
            prepared.append((sequence, observed_at, data, encoded, [self._event_input(e) for e in events]))
        result = []
        with self._transaction() as db:
            if receipt is not None:
                previous = db.execute('SELECT * FROM ingestion_receipts WHERE measurement_id=?',
                                      (receipt['measurement_id'],)).fetchone()
                if previous is not None:
                    if previous['session_id'] != session_id or previous['request_sha256'] != receipt['request_sha256']:
                        raise ValidationError('Measurement ID already has a different request')
                    row = db.execute('SELECT * FROM readings WHERE id=?', (previous['reading_id'],)).fetchone()
                    return [(self._reading(row), False)]
            for sequence, observed_at, data, encoded, event_values in prepared:
                previous = db.execute('SELECT * FROM readings WHERE session_id=? AND sequence=?',
                                      (session_id, sequence)).fetchone()
                if previous is not None:
                    if previous['timestamp'] != observed_at or json.loads(previous['data_json']) != data:
                        raise ValidationError('Sequence already exists with different reading content')
                    result.append((self._reading(previous), False)); continue
                cursor = db.execute('''INSERT INTO readings(session_id,sequence,timestamp,created_at,data_json)
                                     VALUES(?,?,?,?,?)''', (session_id, sequence, observed_at, utc_now(), encoded))
                reading_id = cursor.lastrowid
                for values in event_values: self._insert_event(db, values, session_id, reading_id)
                row = db.execute('SELECT * FROM readings WHERE id=?', (reading_id,)).fetchone()
                result.append((self._reading(row), True))
            if receipt is not None:
                db.execute('INSERT INTO ingestion_receipts VALUES(?,?,?,?,?)',
                           (receipt['measurement_id'], session_id, receipt['request_sha256'],
                            result[0][0]['id'], utc_now()))
        return result

    def ingestion_receipt(self, measurement_id):
        text(measurement_id, 'measurement_id', 64)
        with self._lock:
            row = self._connection.execute('SELECT * FROM ingestion_receipts WHERE measurement_id=?',
                                           (measurement_id,)).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _reading(row):
        return {'id': row['id'], 'sessionId': row['session_id'], 'sequence': row['sequence'],
                'timestamp': row['timestamp'], 'recordedAt': row['created_at'], 'data': json.loads(row['data_json'])}

    def readings(self, *, limit=200, after_id=0, session_id=None):
        integer(limit, 'limit', 1, 1000); integer(after_id, 'after_id')
        where, args = 'id>?', [after_id]
        if session_id is not None: where += ' AND session_id=?'; args.append(session_id)
        with self._lock:
            rows = self._connection.execute(f'SELECT * FROM readings WHERE {where} ORDER BY id DESC LIMIT ?', args+[limit]).fetchall()
        return [self._reading(row) for row in reversed(rows)]

    @staticmethod
    def _event(row):
        return {'id': row['id'], 'kind': row['kind'], 'severity': row['severity'], 'title': row['title'],
                'message': row['message'], 'timestamp': row['timestamp'], 'recordedAt': row['created_at'],
                'sessionId': row['session_id'], 'readingId': row['reading_id'],
                'details': json.loads(row['details_json']), 'acknowledged': row['acknowledged_at'] is not None,
                'acknowledgedAt': row['acknowledged_at'], 'note': row['note']}

    def event(self, event_id):
        integer(event_id, 'event_id', 1)
        with self._lock:
            row = self._connection.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        if row is None: raise NotFoundError('Event not found')
        return self._event(row)

    def events(self, *, limit=100, unacknowledged_only=False):
        integer(limit, 'limit', 1, 1000)
        if not isinstance(unacknowledged_only, bool): raise ValidationError('Filter must be boolean')
        where = 'WHERE acknowledged_at IS NULL' if unacknowledged_only else ''
        with self._lock:
            rows = self._connection.execute(f'SELECT * FROM events {where} ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [self._event(row) for row in rows]

    def acknowledge(self, event_id, note=None):
        integer(event_id, 'event_id', 1)
        if note is not None: text(note, 'note', 1000, empty=True)
        with self._transaction() as db:
            cursor = db.execute('''UPDATE events SET
              note=CASE WHEN acknowledged_at IS NULL THEN ? ELSE note END,
              acknowledged_at=COALESCE(acknowledged_at,?) WHERE id=?''', (note, utc_now(), event_id))
            if cursor.rowcount != 1: raise NotFoundError('Event not found')
        return self.event(event_id)

    def settings(self):
        with self._lock: rows = self._connection.execute('SELECT key,value_json FROM settings ORDER BY key').fetchall()
        return {row['key']: json.loads(row['value_json']) for row in rows}

    def update_settings(self, changes, *, event=None):
        if not isinstance(changes, dict) or len(changes) > 50: raise ValidationError('Invalid settings object')
        encoded = [(text(key, 'setting key', 80), json_value(value)) for key, value in changes.items()]
        event_values = self._event_input(event) if event is not None else None
        with self._transaction() as db:
            for key, value in encoded:
                db.execute('''INSERT INTO settings VALUES(?,?,?) ON CONFLICT(key)
                  DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''', (key, value, utc_now()))
            if event_values is not None: self._insert_event(db, event_values, None, None)
        return self.settings()

    def stats(self, session_id=None):
        where, args = ('WHERE session_id=?', [session_id]) if session_id is not None else ('', [])
        # Scalar JSON extraction does not load a growing history into memory.
        with self._lock:
            row = self._connection.execute(f'''SELECT COUNT(*) AS readings,
              COALESCE(SUM(json_extract(data_json,'$.prediction')=1),0) AS anomaly_readings,
              COALESCE(SUM(json_extract(data_json,'$.prediction')=-1),0) AS unavailable_readings
              FROM readings {where}''', args).fetchone()
        return dict(row)

    def iter_records(self, kind):
        if kind not in ('readings', 'events'): raise ValidationError('Unsupported export')
        with self._lock:
            last = self._connection.execute(f'SELECT COALESCE(MAX(id),0) FROM {kind}').fetchone()[0]
        cursor = 0
        while cursor < last:
            with self._lock:
                rows = self._connection.execute(f'SELECT * FROM {kind} WHERE id>? AND id<=? ORDER BY id LIMIT 500', (cursor, last)).fetchall()
            if not rows: break
            for row in rows: yield self._reading(row) if kind == 'readings' else self._event(row)
            cursor = rows[-1]['id']

    def counts(self):
        with self._lock:
            values = {name: self._connection.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
                      for name in ('sessions', 'readings', 'events')}
            values['unacknowledgedEvents'] = self._connection.execute("SELECT COUNT(*) FROM events WHERE acknowledged_at IS NULL AND severity IN ('warning','critical')").fetchone()[0]
        return values
