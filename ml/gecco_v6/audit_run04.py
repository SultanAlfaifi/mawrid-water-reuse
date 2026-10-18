"""Recompute all run04 predictions from saved models and raw disclosed inputs."""
from pathlib import Path
import sys,json,hashlib,time
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import joblib
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT/'ml/gecco_v5'))
from reproducible_explore import source_cases
from runtime_v4 import predict_frame,StreamingPredictor

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
 out=ROOT/'output/ml/gecco-v6-development/run_04';plan=json.loads((out/'plan.json').read_text());checks=0;rows=0;records=[]
 for name,digest in {**plan['code_sha256'],**plan['raw_sha256']}.items():assert sha(ROOT/name)==digest,name;checks+=1
 for case in source_cases():
  folder=out/case['name'];freeze=json.loads((folder/'freeze.json').read_text())
  assert sha(folder/'bundle.joblib')==freeze['bundle_sha256'];checks+=1
  bundle=joblib.load(folder/'bundle.joblib');frame=case['load_test']()
  before=time.perf_counter();pred=predict_frame(bundle,frame);saved=pd.read_csv(folder/'predictions.csv.gz',float_precision='round_trip')
  assert len(frame)==len(saved)==len(pred);checks+=1;rows+=len(pred)
  pairs={'prediction':'candidate','baseline_prediction':'baseline','guarded_prediction':'guarded',
         **{k:k for k in ['level','jump','sustained','shape_raw','rescue__level','rescue__jump','rescue__sustained','rescue__shape_raw']}}
  for actual,reference in pairs.items():
   np.testing.assert_allclose(pred[actual],saved[reference],rtol=0,atol=1e-12,equal_nan=True);checks+=1
  r=json.loads((folder/'results.json').read_text());y=frame.EVENT.to_numpy(bool);b=pred.baseline_prediction.to_numpy();p=pred.prediction.to_numpy()
  starts=np.flatnonzero(np.diff(np.r_[False,y,False].astype(int))==1);ends=np.flatnonzero(np.diff(np.r_[False,y,False].astype(int))==-1)
  stats={}
  for name,a in [('baseline',b),('candidate',p)]:
   confirmed=(a==1)&np.r_[False,a[:-1]==0];found={i:int(lo+np.flatnonzero(confirmed[lo:hi])[0]) for i,(lo,hi) in enumerate(zip(starts,ends)) if confirmed[lo:hi].any()}
   false=(~y)&(a==1);fr=int((false&np.r_[True,~false[:-1]]).sum());fp=int(false.sum())
   assert r[name]['confirmed_new_alarm_inside_events']==len(found);assert r[name]['false_positive_runs']==fr;assert r[name]['fp']==fp;checks+=3
   stats[name]=found
  assert set(stats['baseline']).issubset(stats['candidate']);checks+=1
  assert all(stats['candidate'][i]<=a for i,a in stats['baseline'].items());checks+=1
  # Three real-model prefixes cover selected sources; full long-latch behavior
  # is checked separately by deterministic synthetic streaming contracts.
  stream_rows=0
  if case['name'] in ('2017_fold_3','2018_fold_2','2019_disclosed_test'):
   n=240;stream=StreamingPredictor(bundle);actual=stream.update_frame(frame.iloc[:n]);stream_rows=n
   for col in pred:
    if col in ('available','ignored_gap'):np.testing.assert_array_equal(actual[col],pred[col].iloc[:n])
    else:np.testing.assert_allclose(actual[col],pred[col].iloc[:n],rtol=0,atol=1e-10,equal_nan=True)
    checks+=1
   assert len(stream.sensor_rows)<=75 and len(stream.score_history)<=5;checks+=1
  records.append({'case':case['name'],'raw_test_rows':len(pred),'streamed_prefix_rows':stream_rows,'all_saved_components_matched':True,'seconds':time.perf_counter()-before})
  print(json.dumps(records[-1]),flush=True)
 report={'completed_at_utc':datetime.now(timezone.utc).isoformat(),'status':'PASS','checks':checks,'recomputed_test_rows':rows,'cases':records,
         'runtime_sha256':sha(HERE/'runtime_v4.py'),'audit_sha256':sha(__file__),'scope':'Same disclosed data; executable and component parity plus manual event/FP counts. This is not a new independent data test or Raspberry Pi benchmark.'}
 (out/'runtime_replay_audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='cases'}),flush=True)
if __name__=='__main__':main()
