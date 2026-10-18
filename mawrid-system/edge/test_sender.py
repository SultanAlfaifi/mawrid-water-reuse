"""Fake loopback HTTP only, including a response lost after durable server commit."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from .core import Outbox
from .sender import LocalTransport, flush_once
from .test_core import SESSION, OTHER, measurement


class FakeServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self):
        self.active=SESSION;self.mode='normal';self.records={};self.requests=[]
        super().__init__(('127.0.0.1',0),FakeHandler)


class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        raw=self.rfile.read(int(self.headers['Content-Length']));payload=json.loads(raw)
        self.server.requests.append(raw)
        assert self.path=='/api/readings'
        mid=payload['measurement_id'];session=payload['session_id']
        if self.server.mode=='slow':
            self.send_response(200);self.send_header('Content-Length','100');self.end_headers()
            try:self.wfile.write(b'{');self.wfile.flush();time.sleep(.8)
            except OSError:pass
            return
        if self.server.mode=='redirect':
            return self.reply(302,{'error':{'code':'redirect_not_followed','message':'test'}},location='http://external.invalid/no')
        if self.server.mode=='busy':
            return self.reply(429,{'error':{'code':'rate_limit','message':'retry later'}},retry='99999')
        duplicate=mid in self.server.records
        if duplicate:
            if self.server.records[mid]['raw']!=raw:
                return self.reply(409,{'error':{'code':'idempotency_conflict','message':'different payload'}})
            receipt=dict(self.server.records[mid]['receipt'],duplicate=True)
        else:
            if session!=self.server.active:
                return self.reply(409,{'error':{'code':'session_not_active','message':'pinned session is not active'}})
            receipt={'measurement_id':mid,'session_id':session,'reading_id':len(self.server.records)+1,'duplicate':False}
            self.server.records[mid]={'raw':raw,'receipt':receipt}
            if self.server.mode=='drop_after_commit':
                self.server.mode='normal'
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
        if self.server.mode=='wrong_receipt':receipt=dict(receipt,session_id=OTHER)
        self.reply(200,{'app':{'mode':'synthetic'},'ingestion':receipt})
    def reply(self,status,value,*,retry=None,location=None):
        raw=json.dumps(value).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        if retry:self.send_header('Retry-After',retry)
        if location:self.send_header('Location',location)
        self.end_headers();self.wfile.write(raw)


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'outbox.sqlite3';self.box=Outbox(self.path)
        self.server=FakeServer();self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.transport=LocalTransport(self.server.server_port);self.now=100.
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.box.close();self.temp.cleanup()
    def enqueue(self,index=0,session=SESSION):return self.box.enqueue(measurement(index),session,input_kind='fixture')
    def flush(self,session=SESSION):return flush_once(self.box,session,self.transport,clock=lambda:self.now)

    def test_lost_response_after_commit_retries_same_id_payload_and_receipt_after_restart(self):
        first=self.enqueue();second=self.enqueue(1)
        self.server.mode='drop_after_commit'
        result=self.flush();self.assertEqual(result['state'],'retry');self.assertEqual(len(self.server.records),1)
        self.assertEqual(len(self.server.requests),1) # Second measurement cannot leapfrog.
        self.box.close();self.box=Outbox(self.path)
        self.assertEqual(self.flush()['state'],'waiting')
        self.now+=1;result=self.flush();self.assertEqual(result['state'],'empty');self.assertEqual(result['delivered'],2)
        self.assertEqual(len(self.server.records),2)
        self.assertEqual(self.server.requests[0],self.server.requests[1])
        stored=self.box.row(first['measurement_id']);receipt=json.loads(stored['receipt_json'])
        self.assertTrue(receipt['duplicate']);self.assertEqual(receipt['reading_id'],1)
        self.assertEqual(stored['status'],'delivered');self.assertEqual(self.box.row(second['measurement_id'])['status'],'delivered')

    def test_historical_duplicate_receipt_can_succeed_after_active_session_changes(self):
        first=self.enqueue();self.server.mode='drop_after_commit';self.flush()
        self.server.active=OTHER;self.now+=1
        self.assertEqual(self.flush()['state'],'empty')
        self.assertEqual(self.box.row(first['measurement_id'])['status'],'delivered')
        self.assertEqual(len(self.server.records),1)

    def test_inactive_session_blocks_without_rebinding_or_deleting(self):
        first=self.enqueue();self.server.active=OTHER
        result=self.flush();self.assertEqual(result['state'],'blocked');self.assertEqual(result['error_code'],'session_not_active')
        self.assertEqual(len(self.server.records),0);self.assertEqual(len(self.server.requests),1)
        self.box.close();self.box=Outbox(self.path)
        self.assertEqual(self.flush()['state'],'blocked');self.assertEqual(len(self.server.requests),1)
        self.assertEqual(json.loads(self.box.row(first['measurement_id'])['payload_json'])['session_id'],SESSION)

    def test_wrong_receipt_does_not_discard_measurement(self):
        row=self.enqueue();self.server.mode='wrong_receipt'
        result=self.flush();self.assertEqual(result['state'],'retry');self.assertEqual(result['error_code'],'receipt_mismatch')
        self.assertIsNone(self.box.row(row['measurement_id'])['receipt_json'])
        self.server.mode='normal';self.now+=1;self.assertEqual(self.flush()['state'],'empty')
        self.assertEqual(len(self.server.records),1)

    def test_payload_conflict_blocks_fifo_without_overwriting_original_receipt(self):
        first=self.enqueue();self.enqueue(1)
        original={'measurement_id':first['measurement_id'],'session_id':SESSION,'reading_id':99,'duplicate':False}
        self.server.records[first['measurement_id']]={'raw':b'other existing payload','receipt':original}
        result=self.flush()
        self.assertEqual(result['state'],'blocked');self.assertEqual(result['error_code'],'idempotency_conflict')
        self.assertEqual(len(self.server.requests),1)
        self.assertEqual(self.server.records[first['measurement_id']]['receipt'],original)
        self.assertIsNone(self.box.row(first['measurement_id'])['receipt_json'])
        self.assertEqual(self.box.row(first['measurement_id'])['status'],'blocked')

    def test_429_retry_after_is_capped_and_no_future_item_is_sent(self):
        self.enqueue();self.enqueue(1);self.server.mode='busy'
        result=self.flush();self.assertEqual(result['wait_seconds'],60)
        self.assertEqual(len(self.server.requests),1)
        self.now+=59;self.assertEqual(self.flush()['state'],'waiting')
        self.server.mode='normal';self.now+=1;self.assertEqual(self.flush()['delivered'],2)

    def test_deadline_and_redirect_are_bounded_and_never_follow_remote_url(self):
        row=self.enqueue();claimed=self.box.claim(SESSION,now=self.now)['row']
        self.server.mode='slow';transport=LocalTransport(self.server.server_port,timeout=.15)
        started=time.monotonic();result=transport.send(claimed);elapsed=time.monotonic()-started
        self.assertEqual(result.action,'retry');self.assertLess(elapsed,.7)
        self.server.mode='redirect';result=self.transport.send(claimed)
        self.assertEqual(result.action,'blocked');self.assertEqual(result.code,'redirect_not_followed')
        self.assertEqual(len(self.server.requests),2)
        self.assertEqual(self.box.row(row['measurement_id'])['status'],'pending')

    def test_corrupted_outbox_payload_hash_prevents_network(self):
        row=self.enqueue();row['payload_json']+=' '
        result=self.transport.send(row)
        self.assertEqual(result.action,'blocked');self.assertEqual(result.code,'outbox_integrity_error')
        self.assertEqual(len(self.server.requests),0)


if __name__=='__main__':unittest.main()
