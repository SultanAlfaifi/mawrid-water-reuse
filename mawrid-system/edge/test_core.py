"""Synthetic JSONL and SQLite tests; no sensor files or live service access."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from .core import (Outbox, InputError, ClaimLost, ingest_file, ingest_stream,
                   strict_json, validate_measurement, backoff_seconds, canonical_uuid)

SESSION = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'


def measurement(index=0):
    return {'timestamp': f'2026-01-01T10:00:{index:02d}+03:00', 'device_id':'fixture-edge-test',
            'channels':{'turbidity':1.2,'ph':7.1,'chlorine':.3,'flow_lpm':None}}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'outbox.sqlite3';self.box=Outbox(self.path)
    def tearDown(self): self.box.close();self.temp.cleanup()

    def test_validation_rejects_missing_unknown_boolean_nonfinite_and_unaware_clock(self):
        bad=[]
        for key,value in [('ph',float('nan')),('ph',float('inf')),('ph',True),('ph',10**999),('ph','7.1'),('flow_lpm',-1)]:
            payload=measurement();payload['channels'][key]=value;bad.append(payload)
        payload=measurement();del payload['channels']['ph'];bad.append(payload)
        payload=measurement();payload['channels']['ORP']=400;bad.append(payload)
        payload=measurement();payload['timestamp']='2026-01-01T10:00:00';bad.append(payload)
        payload=measurement();payload['measurement_id']=str(uuid.uuid4());bad.append(payload)
        payload=measurement();payload['device_id']='unmarked-fixture';bad.append(payload)
        for payload in bad:
            with self.subTest(payload_type=str(type(payload))):
                with self.assertRaises(InputError): self.box.enqueue(payload,SESSION,input_kind='fixture')
        for raw in ('{"value":NaN}','{"x":1,"x":2}','{"x":Infinity}'):
            with self.assertRaises(InputError): strict_json(raw)
        self.assertEqual(self.box.status()['sessions'],{})

    def test_empty_input_still_requires_explicit_valid_contract(self):
        empty=self.root/'empty.jsonl';empty.write_bytes(b'')
        for source,call in ((empty,ingest_file),(io.BytesIO(b''),ingest_stream)):
            with self.assertRaises(InputError):call(self.box,source,'not-a-uuid',input_kind='fixture')
            with self.assertRaises(InputError):call(self.box,source,SESSION,input_kind='implicit')
        self.assertEqual(self.box.status()['sessions'],{})

    def test_original_clock_values_null_and_uuid_survive_reopen(self):
        original=measurement();before=deepcopy(original)
        row=self.box.enqueue(original,SESSION,input_kind='fixture')
        canonical_uuid(row['measurement_id'],'measurement_id')
        self.assertEqual(original,before)
        self.box.close();self.box=Outbox(self.path);restored=self.box.row(row['measurement_id'])
        self.assertEqual(restored['payload_json'],row['payload_json'])
        payload=json.loads(restored['payload_json'])
        self.assertEqual(payload['timestamp'],before['timestamp'])
        self.assertEqual(payload['channels'],before['channels'])
        self.assertEqual(payload['session_id'],SESSION)
        self.assertEqual(restored['payload_sha256'],hashlib.sha256(restored['payload_json'].encode()).hexdigest())

    def test_file_checkpoint_append_resume_and_changed_prefix_guard(self):
        source=self.root/'readings.jsonl'
        source.write_text(json.dumps(measurement(0))+'\n'+json.dumps(measurement(1))+'\n')
        original=source.read_bytes()
        first=ingest_file(self.box,source,SESSION,input_kind='fixture');self.assertEqual(first['queued'],2)
        self.box.close();self.box=Outbox(self.path)
        self.assertEqual(ingest_file(self.box,source,SESSION,input_kind='fixture')['queued'],0)
        with source.open('a') as handle:handle.write(json.dumps(measurement(2))+'\n')
        self.assertEqual(ingest_file(self.box,source,SESSION,input_kind='fixture')['queued'],1)
        self.assertTrue(source.read_bytes().startswith(original))
        source.write_bytes(source.read_bytes().replace(b'1.2',b'1.3',1))
        with self.assertRaisesRegex(InputError,'prefix changed'):ingest_file(self.box,source,SESSION,input_kind='fixture')
        self.assertEqual(self.box.status(SESSION)['sessions'][SESSION]['pending'],3)

    def test_partial_invalid_line_keeps_prior_commit_and_repair_resumes(self):
        source=self.root/'readings.jsonl';line=json.dumps(measurement(0))+'\n'
        source.write_text(line+'{"broken":\n')
        with self.assertRaises(InputError) as error:ingest_file(self.box,source,SESSION,input_kind='fixture')
        self.assertEqual(error.exception.queued,1)
        source.write_text(line+json.dumps(measurement(1))+'\n')
        self.assertEqual(ingest_file(self.box,source,SESSION,input_kind='fixture')['queued'],1)
        self.assertEqual(self.box.status(SESSION)['sessions'][SESSION]['pending'],2)

    def test_stdin_and_file_never_rewrite_input_or_generate_missing_values(self):
        raw=(json.dumps(measurement())+'\n').encode()
        stream=io.BytesIO(raw)
        result=ingest_stream(self.box,stream,SESSION,input_kind='fixture')
        self.assertEqual(result['queued'],1);self.assertEqual(stream.getvalue(),raw)
        self.assertIn('cannot be recovered',result['limitation'])
        # Distinct explicit sessions never rebind an existing queued record.
        row=self.box.enqueue(measurement(1),OTHER,input_kind='fixture')
        self.assertEqual(json.loads(row['payload_json'])['session_id'],OTHER)
        self.assertEqual(self.box.claim(SESSION,now=100)['row']['session_id'],SESSION)

    def test_lease_restart_and_strict_fifo_prevent_leapfrogging(self):
        first=self.box.enqueue(measurement(0),SESSION,input_kind='fixture')
        self.box.enqueue(measurement(1),SESSION,input_kind='fixture')
        claim=self.box.claim(SESSION,now=100);self.assertEqual(claim['row']['measurement_id'],first['measurement_id'])
        other=Outbox(self.path)
        try:
            self.assertEqual(other.claim(SESSION,now=101)['state'],'waiting')
            reclaimed=other.claim(SESSION,now=116)['row']
            self.assertEqual(reclaimed['measurement_id'],first['measurement_id'])
            self.assertEqual(reclaimed['attempts'],2)
            with self.assertRaises(ClaimLost):self.box.delivered(claim['row'],{'unexpected':'stale claim'})
            delay=other.failed(reclaimed,'network_error','unknown commit',now=116)
            self.assertEqual(delay,2)
            self.assertEqual(other.claim(SESSION,now=117)['state'],'waiting')
            self.assertEqual(other.claim(SESSION,now=118)['row']['measurement_id'],first['measurement_id'])
        finally:other.close()

    def test_backoff_is_persistent_and_bounded(self):
        self.assertEqual([backoff_seconds(n) for n in range(1,9)],[1,2,4,8,16,32,60,60])
        for hint in ('999999','-2','NaN','Infinity','junk',None):
            delay=backoff_seconds(999999,hint);self.assertGreaterEqual(delay,1);self.assertLessEqual(delay,60)
        self.assertEqual(backoff_seconds(1,'12'),12)
        with self.assertRaises(ValueError):backoff_seconds(True)

    def test_fresh_cli_ingests_and_reports_without_network_or_ml_imports(self):
        script=Path(__file__).with_name('main.py');db=self.root/'cli.sqlite3'
        command=[sys.executable,'-I','-B',str(script),'--database',str(db)]
        result=subprocess.run(command+['ingest','--session-id',SESSION,'--input','-','--input-kind','fixture'],
            input=json.dumps(measurement())+'\n',text=True,capture_output=True,cwd=self.temp.name,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['queued'],1)
        self.assertNotIn('7.1',result.stdout)
        status=subprocess.run(command+['status','--session-id',SESSION],capture_output=True,text=True,cwd=self.temp.name,timeout=10)
        self.assertEqual(status.returncode,0,status.stderr)
        self.assertEqual(json.loads(status.stdout)['sessions'][SESSION]['pending'],1)


if __name__=='__main__':unittest.main()
