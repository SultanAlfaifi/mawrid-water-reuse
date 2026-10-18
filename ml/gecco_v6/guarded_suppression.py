"""Allow classifier suppression only within each local normal-tail envelope.

Training normalized each per-channel recipe by its normal q99.5. A guard value
<=1 is evidence of local ordinary behavior, not a probability or safety proof.
All three local components must be available and <=1; otherwise retain IF.
Raw classifier output is kept independent for additive rescue.
"""
import numpy as np
LOCAL_NORMAL_LIMIT=1.0

def guarded_shape(local_components,shape_raw):
    values=np.column_stack([local_components[k] for k in ('level','jump','sustained')])
    shape=np.asarray(shape_raw,float).copy()
    if values.shape[0]!=len(shape):raise ValueError('Mismatched arrays')
    ordinary=np.isfinite(values).all(axis=1)&(values<=LOCAL_NORMAL_LIMIT).all(axis=1)
    shape[~ordinary]=np.nan
    return shape
