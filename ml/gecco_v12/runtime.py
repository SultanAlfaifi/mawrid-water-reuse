"""Sensor-only batch replay of the V12 pulse-aware confirmation experiment."""
import numpy as np
import pandas as pd

from ml.gecco_v7.runtime_v2 import predict_frame as score_frame
from ml.gecco_v7.evidence import separate_scores
from ml.gecco_v10.calibration import predict

VERSION = 'v12_if_evidence_hgb_pulse_certified_120s'


def predict_frame(bundle, frame, *, gap_samples=None):
    if bundle.get('version') != VERSION:
        raise ValueError('A matching V12 bundle is required')
    cadence = bundle.get('sample_seconds')
    if (isinstance(cadence, (bool, np.bool_)) or not np.isscalar(cadence)
            or not np.isfinite(cadence) or cadence <= 0
            or cadence != bundle['selected'].get('cadence_seconds')):
        raise ValueError('Model and saved confirmation cadence must agree')
    if isinstance(frame.index, pd.DatetimeIndex):
        if frame.index.hasnans or (len(frame) > 1 and not np.all(
                frame.index[1:] - frame.index[:-1] == pd.Timedelta(seconds=cadence))):
            raise ValueError('Actual timestamp cadence must match the saved policy')
    no_op = {'decision': 'reference', 'low_threshold': None,
             'high_threshold': None, 'policy': 'instant'}
    scored = score_frame({**bundle, 'selected': no_op}, frame, gap_samples=gap_samples)
    masks = separate_scores({key: scored[key].to_numpy() for key in
                             ('level', 'jump', 'sustained')}, scored.long_context.to_numpy())
    scored['rescue_long_context'] = masks['rescue_long_context']
    scored['prediction'] = predict(scored.reference_prediction.to_numpy(np.int8),
        scored.long_context.to_numpy(), bundle['selected'],
        rescue_scores=scored.rescue_long_context.to_numpy())
    return scored
