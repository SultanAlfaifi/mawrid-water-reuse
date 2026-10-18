"""Causal V5 inference interface; no valve command or safety probability.

The caller supplies a trusted, locally fitted model bundle. This module reads
no files, fits no parameters and accepts no labels. A baseline fallback is
reported explicitly; it is not a claim of improved detection.
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gecco_v2'))
from alarm_policy import predict as predict_baseline
from calibration import predict as predict_recovery, POLICIES


def required_history_rows(bundle):
    selected = bundle['selected']
    policy = selected['policy'] if selected['decision'] == 'candidate' else 'instant'
    return int(bundle['model'].max_lookback_) + POLICIES[policy][1] - 1


def predict_frame(bundle, frame):
    model = bundle['model']
    values = frame.loc[:,list(model.channels)]
    components = model.score_components(values)
    baseline = predict_baseline(components['baseline'],bundle['baseline_threshold'],bundle.get('baseline_policy','instant'))
    selected = bundle['selected']
    prediction = predict_recovery(components['shape'],baseline,selected)
    reasons = np.full(len(frame),'baseline_retained_by_calibration',dtype=object)
    if selected['decision'] == 'candidate':
        reasons[:] = 'calibrated_shape_confirmation'
        reasons[~np.isfinite(components['shape'])] = 'shape_unavailable_baseline_retained'
        # A causal voting window may be unavailable after a missing score even
        # when the current shape score is observed; report that fallback too.
        n = POLICIES[selected['policy']][1]
        valid_window = pd.Series(np.isfinite(components['shape'])).rolling(n,min_periods=n).sum().eq(n).to_numpy()
        reasons[~valid_window] = 'shape_window_unavailable_baseline_retained'
    reasons[baseline < 0] = 'baseline_unavailable'
    assert np.array_equal(prediction >= 0,baseline >= 0), 'Inference may not hide baseline-observed rows'
    return pd.DataFrame({'baseline_score':components['baseline'],'shape_score':components['shape'],
        'baseline_prediction':baseline,'prediction':prediction,'available':prediction >= 0,
        'reason':reasons,'calibration_status':selected['status']})


def predict_last(bundle, past_and_current):
    """Bounded memory prediction; include current row and required past rows."""
    if len(past_and_current) == 0:raise ValueError('A current observation is required')
    recent = past_and_current.iloc[-required_history_rows(bundle)-1:]
    return predict_frame(bundle,recent).iloc[-1].to_dict()
