"""Offline CSV inference for a trusted V4 bundle; no simulator or valve I/O."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(ROOT/'ml/gecco_v2'))
from alarm_policy import predict


def predict_frame(bundle, frame):
    channels = bundle['channels']
    missing = sorted(set(channels)-set(frame.columns))
    if missing:
        raise ValueError('Missing required channels: '+', '.join(missing))
    # Deliberately drop timestamps, row IDs and labels before model scoring.
    raw = frame.loc[:,channels].astype(float)
    if bundle['family']=='baseline':
        from run_evaluation import score_baseline
        scores = score_baseline(bundle['model'],raw)
    else:
        scores = bundle['model'].score(raw)
    predictions = predict(scores,bundle['threshold'],bundle['policy'])
    reason = np.full(len(raw),'available',dtype=object)
    reason[predictions<0]='history_or_policy_unavailable'
    reason[~np.isfinite(raw.to_numpy()).all(axis=1)]='current_measurement_missing'
    fit_status=getattr(bundle['model'],'fit_status_',None)
    if fit_status is not None and fit_status!='fitted':
        reason[:]=fit_status
    return pd.DataFrame({'score':scores,'prediction':predictions,
        'score_available':np.isfinite(scores),'decision_available':predictions>=0,
        'reason':reason})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',required=True,type=Path,help='Trusted local joblib bundle only')
    parser.add_argument('--input',required=True,type=Path,help='Consecutive one-minute sensor rows in acquisition order')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Output exists; choose a new file')
    bundle=joblib.load(args.model)
    result=predict_frame(bundle,pd.read_csv(args.input))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(args.output,index=False)
    print(f'Wrote {len(result)} offline predictions. No valve permission or 3D connection.')
