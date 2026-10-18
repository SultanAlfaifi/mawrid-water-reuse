"""Temporary virtual-only loopback service for browser QA; no operator DB/ML.

Print the URL, then type stop or close stdin to tear down all test resources.
"""
import json
from pathlib import Path
import tempfile
import sys
import threading
from urllib.request import urlopen, Request
from verify_plant import FakeEngine, Application, LocalServer


with tempfile.TemporaryDirectory() as temporary:
    engine=FakeEngine()
    app=Application(Path(temporary)/'browser-qa.sqlite3',engine=engine,start_plant_worker=True)
    server=LocalServer(0,app)
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
    thread.start()
    try:
        base=f'http://127.0.0.1:{server.server_port}'
        payload=json.dumps({'source_id':'virtual_plant','research_ack':True}).encode()
        with urlopen(Request(base+'/api/sessions',data=payload,headers={'Content-Type':'application/json'})) as response:
            state=json.load(response)
        print(json.dumps({'url':base+'/plant3d/index.html','base':base,'session_id':state['session']['id'],'temporary_database':True,'model_loaded':False}),flush=True)
        sys.stdin.readline()
        assert engine.start_calls==engine.step_calls==0
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3);app.close()
