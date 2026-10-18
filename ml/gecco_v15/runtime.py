"""V15's frozen two-reference, 120-second policy; no fitting or source IO.

Inputs are original-axis V6/V8 predictions and frozen V14 scores, never labels.
The V8 anchor uses the unchanged delayed confirmation implementation. Recovery
belongs to an original known V6 onset with V8 quiet at that onset. A later V6
onset cancels an unfulfilled older request before considering the current score.

``components`` returns independent int8 seed/recovery/final arrays. Recovery is
an emission indicator (not a separately scored model): -1 exactly where V8 is
unavailable, otherwise 0/1. Final availability always equals V8 availability.
This batch policy is prefix-causal; it does not implement a persistent stream.
"""
from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np

from ml.gecco_v7.calibration_delayed import _confirmed_seed


CADENCE_SECONDS = 60
DEADLINE_SAMPLES = 2


def _reference(values, name):
    array = np.asarray(values)
    if array.ndim != 1 or array.dtype.kind not in "iu" or not np.isin(array, (-1, 0, 1)).all():
        raise ValueError(f"{name} must be a one-dimensional ternary integer array")
    return array.astype(np.int8, copy=False)


def _threshold(value, name):
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real scalar or None")
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite float64 scalar or None") from error
    if not np.isfinite(converted):
        raise ValueError(f"{name} must be a finite float64 scalar or None")
    return converted


def _validated(v6, v8, scores, choice):
    first, anchor = _reference(v6, "v6"), _reference(v8, "v8")
    confidence = np.asarray(scores)
    if confidence.ndim != 1 or confidence.dtype.kind not in "iuf":
        raise ValueError("scores must be a one-dimensional real numeric array")
    if first.shape != anchor.shape or confidence.shape != anchor.shape:
        raise ValueError("v6, v8 and scores must have equal shapes")
    if not isinstance(choice, Mapping):
        raise ValueError("choice must be a mapping")
    required = {"anchor_threshold", "recovery_threshold", "cadence_seconds"}
    if not required.issubset(choice):
        raise ValueError("choice requires anchor_threshold, recovery_threshold and cadence_seconds")
    cadence = choice["cadence_seconds"]
    if isinstance(cadence, (bool, np.bool_)) or not isinstance(cadence, Real) or cadence != CADENCE_SECONDS:
        raise ValueError("V15 requires cadence_seconds exactly 60")
    # Thresholds are independent. The frozen protocol does not impose low<=high.
    low = _threshold(choice["anchor_threshold"], "anchor_threshold")
    high = _threshold(choice["recovery_threshold"], "recovery_threshold")
    return first, anchor, confidence.astype(np.float64, copy=False), low, high


def _recovery(v6, v8, scores, threshold):
    result = np.where(v8 < 0, -1, 0).astype(np.int8)
    if threshold is None or not len(v6):
        return result
    n = len(v6)
    index = np.arange(n)
    known_start = (v6 == 1) & np.r_[False, v6[:-1] == 0]
    origins = np.flatnonzero(known_start & (v8 == 0))
    if not len(origins):
        return result

    # Inclusive cancellation prefixes ensure a reference unknown or ANY new V6
    # known onset cancels an old request, even if the new onset is ineligible.
    unknown_prefix = np.r_[0, np.cumsum((v6 < 0) | (v8 < 0))]
    latest_start = np.maximum.accumulate(np.where(known_start, index, -1))
    first_hit = np.full(len(origins), -1, dtype=np.int64)
    for offset in range(DEADLINE_SAMPLES + 1):
        positions = origins + offset
        inside = positions < n
        candidates = np.flatnonzero(inside & (first_hit < 0))
        at = positions[candidates]
        start = origins[candidates]
        valid = (unknown_prefix[at + 1] == unknown_prefix[start]) & (latest_start[at] == start)
        hit = valid & np.isfinite(scores[at]) & (scores[at] >= threshold)
        first_hit[candidates[hit]] = at[hit]

    hits = first_hit[first_hit >= 0]
    if not len(hits):
        return result
    # A hit in the original continuous pulse latches only that pulse. A later
    # unknown V8 row cancels the latch permanently, even if V6 remains high.
    releases = np.zeros(n, dtype=bool)
    releases[hits[v6[hits] == 1]] = True
    last_release = np.maximum.accumulate(np.where(releases, index, -1))
    last_reset = np.maximum.accumulate(np.where((v6 != 1) | (v8 < 0), index, -1))
    result[(v6 == 1) & (v8 == 0) & (last_release > last_reset)] = 1
    # Literal protocol: post-clear release occurs once when both references are
    # known, including V8=1. It can therefore restore a suppressed anchor row.
    result[hits[v6[hits] == 0]] = 1
    return result


def components(v6, v8, scores, choice):
    """Return causal seed/recovery/final arrays without mutating any input."""
    first, anchor, confidence, low, high = _validated(v6, v8, scores, choice)
    seed = _confirmed_seed(anchor, confidence, low, DEADLINE_SAMPLES)
    recovery = _recovery(first, anchor, confidence, high)
    final = seed.copy()
    final[recovery == 1] = 1
    return {"seed": seed, "recovery": recovery, "final": final}


def predict(v6, v8, scores, choice):
    """Return final np.int8 {-1,0,1}; scores are not safety probabilities."""
    return components(v6, v8, scores, choice)["final"]
