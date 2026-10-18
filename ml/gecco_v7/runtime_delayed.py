"""Batch replay of the <=120-second confirmation experiment; no actuators."""
import numpy as np
import pandas as pd

from ml.gecco_v7.runtime_v2 import predict_frame as score_frame
from ml.gecco_v7.calibration_delayed import predict
from ml.gecco_v7.evidence import separate_scores


def predict_frame(bundle, frame, *, gap_samples=None):
    if bundle.get('version') != 'v7_hgb_corroborated_confirmation_120s':
        raise ValueError('A matching delayed-confirmation experiment bundle is required')
    if bundle.get('sample_seconds') != bundle['selected'].get('cadence_seconds'):
        raise ValueError('Model and confirmation-policy cadence must agree')
    cadence = bundle['sample_seconds']
    if not np.isfinite(cadence) or cadence <= 0:
        raise ValueError('A finite positive sample cadence is required')
    if isinstance(frame.index, pd.DatetimeIndex):
        if frame.index.hasnans or (len(frame) > 1 and not np.all(
                (frame.index[1:] - frame.index[:-1]) == pd.Timedelta(seconds=cadence))):
            raise ValueError('Actual timestamp cadence must match the confirmation policy')
    # RangeIndex replay inputs rely on the source adapter's qualified cadence.
    # The v2 scorer needs a syntactically valid no-op policy; it never fits.
    no_op = {'decision': 'reference', 'low_threshold': None, 'high_threshold': None, 'policy': 'instant'}
    scored = score_frame({**bundle, 'selected': no_op}, frame, gap_samples=gap_samples)
    masks = separate_scores({key: scored[key].to_numpy() for key in ('level', 'jump', 'sustained')}, scored.long_context.to_numpy())
    scored['rescue_long_context'] = masks['rescue_long_context']
    scored['prediction'] = predict(scored.reference_prediction.to_numpy(np.int8), scored.long_context.to_numpy(),
                                   bundle['selected'], rescue_scores=scored.rescue_long_context.to_numpy())
    return scored
