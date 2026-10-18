"""Strict measurement validation and a durable, session-pinned SQLite outbox."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
import uuid

CHANNELS = ('turbidity', 'ph', 'chlorine', 'flow_lpm')
MAX_LINE_BYTES = 65536
MIN_BACKOFF = 1.0
MAX_BACKOFF = 60.0
CLAIM_SECONDS = 15.0
EMPTY_HASH = hashlib.sha256(b'').hexdigest()


class InputError(ValueError):
    def __init__(self, message, *, queued=0, line=None):
        super().__init__(message); self.queued, self.line = queued, line


class ClaimLost(RuntimeError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def canonical_uuid(value, name):
    if not isinstance(value, str): raise InputError(f'{name} must be a canonical lowercase UUID')
    try: parsed = uuid.UUID(value)
    except (ValueError, AttributeError): raise InputError(f'{name} must be a canonical lowercase UUID')
    if str(parsed) != value: raise InputError(f'{name} must be a canonical lowercase UUID')
    return value


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def validate_input_kind(input_kind):
    if input_kind not in ('measured', 'fixture'):
        raise InputError('input_kind must explicitly be measured or fixture')


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Duplicate JSON object key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise InputError('Invalid JSON; duplicate keys and nonfinite values are not allowed')


def validate_measurement(value, *, input_kind):
    validate_input_kind(input_kind)
    if not isinstance(value, dict) or set(value) != {'timestamp', 'device_id', 'channels'}:
        raise InputError('Each measurement must contain exactly timestamp, device_id and channels')
    stamp = value['timestamp']
    if not isinstance(stamp, str) or len(stamp) > 64 or 'T' not in stamp:
        raise InputError('timestamp must be an original ISO8601 datetime including timezone')
    try: parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    except ValueError: raise InputError('timestamp must be an original ISO8601 datetime including timezone')
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError('timestamp must include timezone; the collector never invents a clock')
    device = value['device_id']
    if not isinstance(device, str) or not device.strip() or len(device) > 100:
        raise InputError('device_id must be a nonempty string of at most100 characters')
    if input_kind == 'fixture' and not device.startswith(('fixture-', 'fixture:')):
        raise InputError('A fixture device_id must explicitly begin with fixture- or fixture:')
    channels = value['channels']
    if not isinstance(channels, dict) or set(channels) != set(CHANNELS):
        raise InputError('All four telemetry channels must be explicit; use null for a missing measurement')
    for name, number in channels.items():
        if number is None: continue
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise InputError(f'{name} must be finite numeric or null')
        try: finite = math.isfinite(number)
        except OverflowError: finite = False
        if not finite: raise InputError(f'{name} must be finite numeric or null')
        if name == 'flow_lpm' and number < 0: raise InputError('flow_lpm cannot be negative')
    # Copy through JSON to prevent subsequent caller mutation, without changing
    # clock text, measured numeric values, device identity or missingness.
    return json.loads(canonical_json(value))


def backoff_seconds(attempt, retry_after=None):
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError('attempt must be a positive integer')
    delay = min(MAX_BACKOFF, MIN_BACKOFF * 2 ** min(attempt - 1, 6))
    if retry_after is not None:
        try:
            proposed = float(retry_after)
            if math.isfinite(proposed): delay = max(delay, proposed)
        except (ValueError, TypeError, OverflowError): pass
    return min(MAX_BACKOFF, max(MIN_BACKOFF, delay))


class Outbox:
    def __init__(self, database):
        self.path = Path(database).resolve(); self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON'); self.db.execute('PRAGMA busy_timeout=10000')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL, session_id TEXT NOT NULL,
            input_kind TEXT NOT NULL, byte_offset INTEGER NOT NULL DEFAULT 0,
            line_number INTEGER NOT NULL DEFAULT 0, prefix_sha256 TEXT NOT NULL,
            UNIQUE(path,session_id)
          );
          CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT, measurement_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
            input_kind TEXT NOT NULL, import_id INTEGER REFERENCES imports(id), source_line INTEGER,
            status TEXT NOT NULL CHECK(status IN ('pending','retry','delivered','blocked')),
            created_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL DEFAULT 0, claim_token TEXT, claim_until REAL,
            last_attempt_at TEXT, last_error_code TEXT, last_error TEXT,
            delivered_at TEXT, receipt_json TEXT,
            UNIQUE(import_id,source_line)
          );
          CREATE INDEX IF NOT EXISTS outbox_session_order ON outbox(session_id,id);
        ''')

    @contextmanager
    def transaction(self):
        with self._lock:
            self.db.execute('BEGIN IMMEDIATE')
            try: yield self.db; self.db.execute('COMMIT')
            except BaseException: self.db.execute('ROLLBACK'); raise

    def close(self):
        with self._lock: self.db.close()

    def checkpoint(self, path, session_id, input_kind):
        path = str(Path(path).resolve()); canonical_uuid(session_id, 'session_id')
        validate_input_kind(input_kind)
        with self.transaction() as db:
            db.execute('''INSERT INTO imports(path,session_id,input_kind,prefix_sha256)
              VALUES(?,?,?,?) ON CONFLICT(path,session_id) DO NOTHING''', (path, session_id, input_kind, EMPTY_HASH))
            result = dict(db.execute('SELECT * FROM imports WHERE path=? AND session_id=?', (path,session_id)).fetchone())
            if result['input_kind'] != input_kind:
                raise InputError('This file/session already has a different input_kind; no automatic relabeling')
        return result

    def enqueue(self, value, session_id, *, input_kind, checkpoint=None, end_offset=None, prefix_hash=None):
        canonical_uuid(session_id, 'session_id')
        measurement = validate_measurement(value, input_kind=input_kind)
        measurement_id = str(uuid.uuid4())
        payload = canonical_json(dict(measurement, session_id=session_id, measurement_id=measurement_id))
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        with self.transaction() as db:
            if checkpoint is not None:
                # This conditional update also rejects concurrent ingestion of
                # the same file/session without duplicating already read lines.
                changed = db.execute('''UPDATE imports SET byte_offset=?,line_number=?,prefix_sha256=?
                    WHERE id=? AND byte_offset=? AND line_number=? AND prefix_sha256=?''',
                    (end_offset,checkpoint['line_number']+1,prefix_hash,checkpoint['id'],
                     checkpoint['byte_offset'],checkpoint['line_number'],checkpoint['prefix_sha256']))
                if changed.rowcount != 1: raise InputError('File checkpoint changed concurrently; rerun ingestion')
            cursor = db.execute('''INSERT INTO outbox(measurement_id,session_id,payload_json,payload_sha256,
                input_kind,import_id,source_line,status,created_at) VALUES(?,?,?,?,?,?,?,'pending',?)''',
                (measurement_id,session_id,payload,digest,input_kind,
                 checkpoint['id'] if checkpoint else None,checkpoint['line_number']+1 if checkpoint else None,now_iso()))
            row = dict(db.execute('SELECT * FROM outbox WHERE id=?',(cursor.lastrowid,)).fetchone())
        return row

    def claim(self, session_id, *, now=None):
        """FIFO: an unresolved earlier measurement always blocks later ones."""
        canonical_uuid(session_id, 'session_id'); now = time.time() if now is None else now
        with self.transaction() as db:
            raw = db.execute("SELECT * FROM outbox WHERE session_id=? AND status!='delivered' ORDER BY id LIMIT 1", (session_id,)).fetchone()
            if raw is None: return {'state': 'empty'}
            row = dict(raw)
            if row['status'] == 'blocked': return {'state': 'blocked', 'row': row}
            due = max(row['next_attempt_at'], row['claim_until'] or 0)
            if due > now: return {'state': 'waiting', 'wait_seconds': min(MAX_BACKOFF,due-now), 'row': row}
            token = str(uuid.uuid4())
            db.execute('''UPDATE outbox SET attempts=attempts+1,claim_token=?,claim_until=?,last_attempt_at=? WHERE id=?''',
                       (token,now+CLAIM_SECONDS,now_iso(),row['id']))
            row = dict(db.execute('SELECT * FROM outbox WHERE id=?',(row['id'],)).fetchone())
            return {'state': 'claimed', 'row': row}

    def delivered(self, row, receipt):
        with self.transaction() as db:
            changed = db.execute("""UPDATE outbox SET status='delivered',delivered_at=?,receipt_json=?,
                claim_token=NULL,claim_until=NULL,last_error_code=NULL,last_error=NULL WHERE id=? AND claim_token=?""",
                (now_iso(),canonical_json(receipt),row['id'],row['claim_token']))
            if changed.rowcount != 1: raise ClaimLost('Delivery claim changed; receipt was not assigned to another record')

    def failed(self, row, code, message, *, blocked=False, retry_after=None, now=None):
        now = time.time() if now is None else now
        delay = backoff_seconds(row['attempts'], retry_after)
        with self.transaction() as db:
            changed = db.execute('''UPDATE outbox SET status=?,next_attempt_at=?,claim_token=NULL,
                claim_until=NULL,last_error_code=?,last_error=? WHERE id=? AND claim_token=?''',
                ('blocked' if blocked else 'retry',now+delay,str(code)[:100],str(message)[:500],row['id'],row['claim_token']))
            if changed.rowcount != 1: raise ClaimLost('Delivery claim changed; no row was overwritten')
        return delay

    def status(self, session_id=None):
        if session_id is not None: canonical_uuid(session_id, 'session_id')
        where,args=('WHERE session_id=?',[session_id]) if session_id else ('',[])
        with self._lock:
            rows=self.db.execute(f'SELECT session_id,status,COUNT(*) n FROM outbox {where} GROUP BY session_id,status',args).fetchall()
            oldest=self.db.execute(f"SELECT measurement_id,session_id,status,attempts,next_attempt_at,last_error_code,last_error FROM outbox {where+' AND' if where else 'WHERE'} status!='delivered' ORDER BY id LIMIT 1",args).fetchone()
        sessions={}
        for row in rows: sessions.setdefault(row['session_id'],{'pending':0,'retry':0,'delivered':0,'blocked':0})[row['status']]=row['n']
        return {'database':str(self.path),'sessions':sessions,'oldest_unresolved':dict(oldest) if oldest else None}

    def row(self, measurement_id):
        with self._lock:
            raw=self.db.execute('SELECT * FROM outbox WHERE measurement_id=?',(measurement_id,)).fetchone()
        return dict(raw) if raw else None


def _prefix(handle, length):
    handle.seek(0); digest=hashlib.sha256(); remaining=length
    while remaining:
        block=handle.read(min(1048576,remaining))
        if not block: raise InputError('Input file was truncated before the saved checkpoint')
        digest.update(block); remaining-=len(block)
    return digest


def ingest_file(outbox, input_path, session_id, *, input_kind):
    canonical_uuid(session_id, 'session_id'); validate_input_kind(input_kind)
    path=Path(input_path).resolve()
    if not path.is_file() or path==outbox.path: raise InputError('Input must be a separate existing JSONL file')
    check=outbox.checkpoint(path,session_id,input_kind); queued=0
    with path.open('rb') as handle:
        digest=_prefix(handle,check['byte_offset'])
        if digest.hexdigest()!=check['prefix_sha256']:
            raise InputError('Previously ingested file prefix changed; no automatic checkpoint reset')
        while raw:=handle.readline(MAX_LINE_BYTES+1):
            line=check['line_number']+1
            try:
                if len(raw)>MAX_LINE_BYTES: raise InputError('JSONL line exceeds65536 bytes')
                value=strict_json(raw.decode('utf-8-sig' if line==1 else 'utf-8'))
                updated=digest.copy(); updated.update(raw); end=check['byte_offset']+len(raw)
                outbox.enqueue(value,session_id,input_kind=input_kind,checkpoint=check,end_offset=end,prefix_hash=updated.hexdigest())
            except (InputError,UnicodeDecodeError) as error:
                raise InputError(f'Line{line}: {error}. Earlier committed lines remain queued.',queued=queued,line=line) from error
            queued+=1; digest=updated
            check.update(byte_offset=end,line_number=line,prefix_sha256=digest.hexdigest())
        if _prefix(handle,check['byte_offset']).hexdigest()!=check['prefix_sha256']:
            raise InputError('Input changed during ingestion; queued values are retained, source needs review',queued=queued)
    return {'queued':queued,'session_id':session_id,'input_kind':input_kind,'source':str(path),
            'checkpoint_line':check['line_number'],'checkpoint_bytes':check['byte_offset'],
            'prefix_sha256':check['prefix_sha256']}


def ingest_stream(outbox, stream, session_id, *, input_kind):
    """stdin has no seekable checkpoint; only committed rows are recoverable."""
    canonical_uuid(session_id, 'session_id'); validate_input_kind(input_kind)
    queued=0
    while raw:=stream.readline(MAX_LINE_BYTES+1):
        line=queued+1
        try:
            if len(raw)>MAX_LINE_BYTES: raise InputError('JSONL line exceeds65536 bytes')
            value=strict_json(raw.decode('utf-8-sig' if line==1 else 'utf-8'))
            outbox.enqueue(value,session_id,input_kind=input_kind)
        except (InputError,UnicodeDecodeError) as error:
            raise InputError(f'stdin line{line}: {error}. Earlier committed lines remain queued.',queued=queued,line=line) from error
        queued+=1
    return {'queued':queued,'session_id':session_id,'input_kind':input_kind,'source':'stdin',
            'limitation':'Only successfully committed stdin lines survive; stdin bytes not yet committed cannot be recovered. Use a file for resumable ingestion.'}
