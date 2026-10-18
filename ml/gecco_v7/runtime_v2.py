"""Standalone batch V7 inference using sensor readings and fitted bundles only.

This is an evaluation/replay interface, with no 3D or actuator integration.
An invocation is one independent period. It resets V6 and long-context state
and discards the configured gap before either computes sensor features.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ml.gecco_v6.runtime_v4 import predict_frame as reference_predict
from ml.gecco_v7.calibration_v2 import predict
from ml.gecco_v6.guarded_suppression import guarded_shape


def predict_frame(bundle, frame, *, gap_samples=None):
    if not isinstance(bundle, dict) or not {'long_model', 'reference_bundle', 'selected'}.issubset(bundle):
        raise ValueError('A complete V7 inference bundle is required')
    gap = bundle.get('gap_samples', 120) if gap_samples is None else gap_samples
    if isinstance(gap, (bool, np.bool_)) or not isinstance(gap, (int, np.integer)) or gap < 0:
        raise ValueError('gap_samples must be a nonnegative integer')
    model = bundle['long_model']
    channels = list(model.channels)
    if channels != list(bundle['reference_bundle']['local_model'].channels):
        raise ValueError('Reference and long-context channels must match in order')
    if not isinstance(frame, pd.DataFrame) or any(c not in frame for c in channels):
        raise ValueError('All fitted sensor columns are required')
    sensors = frame.loc[:, channels]
    reference = reference_predict(bundle['reference_bundle'], sensors, gap_samples=gap)
    scores = model.score_components(sensors.iloc[gap:].reset_index(drop=True))['long_context']
    scores = np.r_[np.full(min(gap, len(sensors)), np.nan), scores]
    if scores.shape != (len(frame),):
        raise ValueError('Invalid long-context score shape')
    result = reference.rename(columns={'prediction': 'reference_prediction'}).copy()
    result['long_context'] = scores
    gate_scores = guarded_shape({key: reference[key].to_numpy() for key in ('level', 'jump', 'sustained')}, scores)
    result['guarded_long_context'] = gate_scores
    result['prediction'] = predict(result.reference_prediction.to_numpy(np.int8), scores, bundle['selected'], gate_scores=gate_scores)
    return result
