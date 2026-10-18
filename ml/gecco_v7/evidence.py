"""Current-sample V6 local corroboration; no labels, fit, state or source IO.

The fixed boundary 1 is inherited from V6's fitted normal-reference scales.
All three local components must be finite. Quiet local context (all <=1)
supports optional suppression; any component >1 supports optional rescue.
Missing local or long evidence makes both outputs unavailable.
"""
from __future__ import annotations

import numpy as np


LOCAL_KEYS = ("level", "jump", "sustained")


def separate_scores(local_dict, long_scores):
    scores = np.asarray(long_scores, float)
    if scores.ndim != 1:
        raise ValueError("long_scores must be one-dimensional")
    try:
        components = [np.asarray(local_dict[key], float) for key in LOCAL_KEYS]
    except (KeyError, TypeError) as error:
        raise ValueError("level, jump and sustained local components are required") from error
    if any(component.shape != scores.shape for component in components):
        raise ValueError("Local components and long scores must have equal shape")
    local = np.stack(components)
    known = np.isfinite(scores) & np.isfinite(local).all(axis=0)
    quiet = known & (local <= 1).all(axis=0)
    changing = known & (local > 1).any(axis=0)
    return {"guarded_long_context": np.where(quiet, scores, np.nan),
            "rescue_long_context": np.where(changing, scores, np.nan)}
