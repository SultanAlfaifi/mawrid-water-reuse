"""Actual isolated HTTP snapshots checked by the operational3D source adapter.

Only a temporary database and loopback test server are used. The model sentinel
rejects every fit/inference request. This is simulation presentation evidence,
not a classifier, physical-device, or graphics validation.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from verify_plant import http_application, check_state, digest, ROOT, SYSTEM


class Assets(HTMLParser):
    def __init__(self):
        super().__init__(); self.paths=[]
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if (tag=='script' and key=='src') or (tag=='link' and key=='href'):
                original=urlsplit(value)
                resolved=urlsplit(urljoin('/plant3d/index.html',value))
                if original.scheme or original.netloc or not resolved.path.startswith('/plant3d/') or resolved.query or resolved.fragment:
                    raise AssertionError('Unexpected or external page asset: '+value)
                self.paths.append(resolved.path)


def frozen_sources():
    paths=[SYSTEM/'scripts/verify_plant3d.py',SYSTEM/'scripts/check_plant3d_fixtures.mjs',
           SYSTEM/'scripts/verify_plant.py',SYSTEM/'CONTRACT.json',SYSTEM/'client/plant.js']
    paths += [SYSTEM/'server'/name for name in ['__init__.py','app.py','main.py','store.py','plant.py']]
    paths += [p for p in (SYSTEM/'plant3d').rglob('*') if p.is_file()]
    paths += [p for p in (SYSTEM/'client/plant3d').rglob('*') if p.is_file()]
    return {str(p.relative_to(ROOT)):digest(p) for p in paths}


def run(output):
    output=output.resolve(); output.mkdir(parents=True,exist_ok=False)
    evidence={'created_at_utc':datetime.now(timezone.utc).isoformat(),'passed':False,
              'virtual_only':True,'operator_database_opened':False,'model_loaded':False,
              'browser_rendering_verified_by_this_script':False}
    fixtures=[]
    try:
        before_hashes=frozen_sources()
        assert any(name.startswith('mawrid-system/client/plant3d/') for name in before_hashes),'Build required before verification'
        with tempfile.TemporaryDirectory() as tmp, http_application(Path(tmp)/'isolated.sqlite3',worker=False) as (app,engine,request):
            def capture(name):
                state=request('/api/state')
                if state['virtual_plant'] is not None: check_state(state)
                fixtures.append({'name':name,'state':state})
                return state
            capture('no_virtual_session')
            request('/api/sessions',{'source_id':'virtual_plant','research_ack':True})
            capture('initial_auto')
            request('/api/plant/control',{'speed':30})
            for _ in range(120): app._plant_tick()
            capture('one_virtual_hour')
            for fault in ['turbidity','sensor_dropout','clogging','power_loss','valve_stuck']:
                request('/api/plant/control',{'mode':'auto','fault':fault}); capture(fault)
            request('/api/plant/control',{'fault':'none','mode':'standby'}); capture('standby')
            request('/api/plant/control',{'mode':'backwash'}); app._plant_tick(); capture('backwash')
            request('/api/plant/control',{'running':False}); before=capture('paused')
            for _ in range(3): app._plant_tick()
            assert capture('paused_poll_still_fresh')['virtual_plant']==before['virtual_plant']
            request('/api/plant/control',{'mode':'auto','running':True})
            request('/api/control/stop',{'note':'Isolated operational3D verification'}); capture('manual_hold')
            request('/api/control/reset',{}); capture('reset_still_paused')
            request('/api/plant/control',{'running':True}); capture('resumed')
            old_session=fixtures[-1]['state']['session']['id']
            request('/api/sessions',{'source_id':'virtual_plant','research_ack':True})
            assert capture('new_virtual_session')['session']['id']!=old_session
            request('/api/sessions',{'source_id':'telemetry'}); capture('telemetry_clears_plant')
            before=request('/api/state')
            page=request('/plant3d/index.html',raw=True)
            assets=Assets(); assets.feed(page.decode())
            assert assets.paths,'Built local3D entry and assets are required'
            for path in assets.paths: assert request(path,raw=True),path
            assert request('/api/state')==before,'Static page GET must not start a session or clock'
            assert engine.start_calls==engine.step_calls==0
            evidence['local_http_assets']=assets.paths
            evidence['model_sentinel_calls']={'start':engine.start_calls,'step':engine.step_calls}
        path=output/'http-snapshots.json'; path.write_text(json.dumps(fixtures,ensure_ascii=False,indent=2)+'\n')
        completed=subprocess.run(['/opt/homebrew/bin/node',str(SYSTEM/'scripts/check_plant3d_fixtures.mjs'),str(path)],check=True,capture_output=True,text=True)
        evidence['adapter']=json.loads(completed.stdout)
        evidence['fixtures_sha256']=digest(path)
        assert frozen_sources()==before_hashes,'Source, server, helper or built assets changed during verification'
        evidence['source_sha256']=before_hashes
        evidence['all_recorded_sources_frozen_before_and_after_execution']=True
        preserved=json.loads((ROOT/'output/mawrid-system/engineering-viewer-before-operational3d.json').read_text())
        assert all(digest(ROOT/name)==sha for name,sha in preserved['sha256'].items())
        evidence['original_engineering_viewer_unchanged_files']=len(preserved['sha256'])
        evidence['passed']=True
    except Exception as error:
        evidence['error']=repr(error)
        raise
    finally:
        (output/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'fixtures':len(fixtures),'checks':evidence['adapter']['checks'],'output':str(output)},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
