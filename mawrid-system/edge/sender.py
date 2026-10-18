"""Bounded loopback HTTP delivery. No session creation, rebinding or hardware."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import http.client
import json
import socket
import threading
import time

from .core import InputError, canonical_uuid, strict_json, MAX_BACKOFF

MAX_RESPONSE_BYTES = 1048576
HTTP_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Delivery:
    action: str  # delivered, retry, blocked
    code: str
    message: str
    receipt: dict | None = None
    retry_after: str | None = None


class LocalTransport:
    def __init__(self, port=8787, *, timeout=HTTP_TIMEOUT_SECONDS):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('port must be an integer between1 and65535')
        if isinstance(timeout,bool) or not isinstance(timeout, (int,float)) or not 0 < timeout <= HTTP_TIMEOUT_SECONDS:
            raise ValueError('HTTP timeout must be positive and at most5 seconds')
        self.port, self.timeout = port, float(timeout)

    def send(self, row):
        body = row['payload_json'].encode('utf-8')
        if hashlib.sha256(body).hexdigest() != row['payload_sha256']:
            return Delivery('blocked','outbox_integrity_error','Stored payload hash differs; no HTTP request was sent')
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.timeout)
        started = time.monotonic(); timer = None
        try:
            connection.connect()
            remaining = self.timeout - (time.monotonic()-started)
            if remaining <= 0: raise TimeoutError('Request deadline exceeded')
            sock = connection.sock
            sock.settimeout(remaining)
            # A total wall-clock deadline also interrupts a slowly trickling
            # response; per-socket-read timeouts alone would not bound it.
            def expire():
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            timer = threading.Timer(remaining, expire); timer.daemon = True; timer.start()
            connection.request('POST','/api/readings',body=body,headers={
                'Content-Type':'application/json','Accept':'application/json',
                'Connection':'close','User-Agent':'Mawrid-Local-Collector/1'})
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES+1)
            if time.monotonic()-started >= self.timeout: raise TimeoutError('Request deadline exceeded')
            if len(raw)>MAX_RESPONSE_BYTES:
                return Delivery('retry','response_too_large','Server response exceeded local limit')
            try: result = strict_json(raw)
            except InputError:
                return Delivery('retry','invalid_response','Response was not finite JSON; commit status is unknown')
            if not isinstance(result,dict):
                return Delivery('retry','invalid_response','Response was not a JSON object; commit status is unknown')
            if response.status == 200:
                receipt = result.get('ingestion')
                if (not isinstance(receipt,dict) or receipt.get('measurement_id')!=row['measurement_id']
                        or receipt.get('session_id')!=row['session_id']
                        or isinstance(receipt.get('reading_id'),bool)
                        or not isinstance(receipt.get('reading_id'),int) or receipt['reading_id']<1
                        or not isinstance(receipt.get('duplicate'),bool)):
                    return Delivery('retry','receipt_mismatch','Matching session/measurement/reading receipt is required before acknowledging delivery')
                return Delivery('delivered','receipt_verified','Server receipt verified',receipt=receipt)
            error = result.get('error',{})
            code = error.get('code') if isinstance(error,dict) else None
            message = error.get('message') if isinstance(error,dict) else None
            code = code if isinstance(code,str) else f'http_{response.status}'
            message = message if isinstance(message,str) else f'HTTP{response.status}'
            if response.status >= 500 or response.status in (408,425,429):
                return Delivery('retry',code,message,retry_after=response.getheader('Retry-After'))
            # Redirects are not followed. A wrong session, payload conflict or
            # invalid input remains durable and stops this session's FIFO.
            return Delivery('blocked',code,message)
        except (OSError, http.client.HTTPException, TimeoutError) as error:
            return Delivery('retry','network_error',f'{type(error).__name__}; server commit status may be unknown')
        finally:
            if timer is not None: timer.cancel()
            connection.close()


def flush_once(outbox, session_id, transport, *, clock=time.time, max_items=1000, on_progress=None):
    """Drain the ready FIFO prefix; stop on waiting, retry or any blocked row."""
    canonical_uuid(session_id,'session_id')
    if isinstance(max_items,bool) or not isinstance(max_items,int) or not 1<=max_items<=1000:
        raise ValueError('max_items must be between1 and1000')
    delivered = 0
    for _ in range(max_items):
        claim = outbox.claim(session_id,now=clock())
        if claim['state'] != 'claimed':
            result = {'state':claim['state'],'session_id':session_id,'delivered':delivered}
            if 'wait_seconds' in claim: result['wait_seconds']=claim['wait_seconds']
            if 'row' in claim:
                result.update(measurement_id=claim['row']['measurement_id'],error_code=claim['row']['last_error_code'])
            return result
        row = claim['row']
        response = transport.send(row)
        if response.action == 'delivered':
            outbox.delivered(row,response.receipt); delivered+=1
            if on_progress: on_progress({'state':'delivered','measurement_id':row['measurement_id'],
                'session_id':session_id,'receipt':response.receipt})
        else:
            blocked=response.action=='blocked'
            delay=outbox.failed(row,response.code,response.message,blocked=blocked,
                                retry_after=response.retry_after,now=clock())
            result={'state':'blocked' if blocked else 'retry','session_id':session_id,'delivered':delivered,
                    'measurement_id':row['measurement_id'],'error_code':response.code,'message':response.message[:500]}
            if not blocked: result['wait_seconds']=delay
            return result
    return {'state':'batch_limit','session_id':session_id,'delivered':delivered}


def watch(outbox, session_id, transport, *, emit, stop=None):
    """Explicit continuous sender; idle polling never creates measurements."""
    stop = stop or threading.Event()
    while not stop.is_set():
        result=flush_once(outbox,session_id,transport,on_progress=emit)
        if result['state'] in ('retry','blocked') or result['delivered']:
            emit(result)
        if result['state']=='blocked': return result
        # Short interruptible waits make shutdown prompt and bound each wait;
        # persisted next_attempt_at enforces the actual1..60 second backoff.
        stop.wait(min(1.0,result.get('wait_seconds',1.0)))
    return {'state':'stopped','session_id':session_id}
