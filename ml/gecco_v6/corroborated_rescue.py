"""Two independent pieces of past-trained evidence for additive rescue.

Local departures alone also flag ordinary operating steps. Permit their rescue
only if the trained event-shape classifier exceeds its past calibration normal
q99. This only restricts additive rescue; unknown evidence never suppresses IF.
The reference percentile is fitted on calibration normal labels, not test data.
"""
import numpy as np
from departure_scores import departure_scores
NORMAL_SHAPE_QUANTILE=.99
MIN_NORMAL_SHAPE_ROWS=5760

def fit_shape_reference(blocks):
    normal=[]
    for b in blocks:
        values=np.asarray(b['scores']['shape_raw'],float)
        normal.extend(values[(~np.asarray(b['labels'],bool))&(np.asarray(b['baseline'])>=0)&np.isfinite(values)])
    if len(normal)<MIN_NORMAL_SHAPE_ROWS:return None
    return max(float(np.quantile(normal,NORMAL_SHAPE_QUANTILE)),1e-6)

def corroborated_scores(components,shape_threshold):
    out=departure_scores(components)
    if shape_threshold is None:return {k:np.full_like(v,np.nan) for k,v in out.items()}
    if not np.isfinite(shape_threshold) or shape_threshold<=0:raise ValueError('Positive finite shape reference required')
    raw=out['shape_raw']
    for key in ('level','jump','sustained'):
        out[key][np.isfinite(raw)&(raw<shape_threshold)]=0.
        out[key][~np.isfinite(raw)]=np.nan
    return out
