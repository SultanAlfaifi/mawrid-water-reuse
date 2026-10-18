"""Post-audit calibration guard; does NOT change the frozen V4 evaluation.

This is a wrapper for future offline use, not a retuned detector or a new
benchmark result. A failed calibration must be unavailable, not a quiet alarm.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import joblib
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parent))
from predict import predict_frame

def readiness_reason(selection):
    if selection.get('calibration_status') != 'feasible_all_blocks' or not selection.get('feasible_all_blocks'):
        return 'calibration_constraints_not_established'
    if selection.get('complete_events',0)>0 and selection.get('worst_event_block_recall',0)<=0:
        return 'calibration_missed_all_events_in_a_block'
    return None

def checked_predict_frame(bundle, selection, frame):
    reason=readiness_reason(selection)
    if reason:
        return pd.DataFrame({'score':np.full(len(frame),np.nan),
            'prediction':np.full(len(frame),-1,dtype=np.int8),
            'score_available':False,'decision_available':False,'reason':reason,
            'calibration_ready':False})
    result=predict_frame(bundle,frame)
    result['calibration_ready']=True
    return result

def load_checked(model_path):
    model_path=Path(model_path)
    if model_path.name!='v4_model.joblib':raise ValueError('Expected a V4 model artifact')
    freeze=json.loads(model_path.with_name('freeze.json').read_text())
    digest=hashlib.sha256(model_path.read_bytes()).hexdigest()
    if digest!=freeze['model_sha256']['v4']:raise ValueError('Model hash mismatch')
    return joblib.load(model_path),freeze['selected']['v4']

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',required=True,type=Path,help='Trusted local V4 artifact with its freeze.json')
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Output exists; choose a new path')
    bundle,selection=load_checked(args.model)
    result=checked_predict_frame(bundle,selection,pd.read_csv(args.input))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(args.output,index=False)
    print('Offline guarded output only. Passing calibration is not field readiness or valve permission.')
