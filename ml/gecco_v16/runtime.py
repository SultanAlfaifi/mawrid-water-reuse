"""Sensor-only batch inference; unchanged V15 policy with V16 head scores."""
import numpy as np
import pandas as pd
from ml.gecco_v8.runtime import predict_frame as reference_frame
from ml.gecco_v15.runtime import predict

VERSION='v16_forward_teacher_decision_head'


def predict_frame(bundle,frame,*,gap_samples=120):
    if bundle.get('version')!=VERSION or bundle.get('sample_seconds')!=60:
        raise ValueError('Matching V16 one-minute bundle required')
    channels=bundle['model'].channels
    if not isinstance(frame,pd.DataFrame) or any(list(frame.columns).count(c)!=1 for c in channels):
        raise ValueError('Each model sensor must occur exactly once')
    sensors=frame.loc[:,channels]
    scored=reference_frame(bundle['reference_bundle'],sensors,gap_samples=gap_samples).copy()
    v6=scored.reference_prediction.to_numpy(np.int8)
    v8=scored.prediction.to_numpy(np.int8)
    scores=bundle['model'].score(sensors,v6,v8,gap_samples=gap_samples)
    scored['v8_prediction']=v8
    scored['original_v8_long_context']=scored.long_context.to_numpy()
    scored['long_context']=scores
    scored['prediction']=predict(v6,v8,scores,bundle['selected']['choice'])
    scored['available']=scored.prediction.to_numpy()>=0
    return scored
