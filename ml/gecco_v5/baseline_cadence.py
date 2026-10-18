"""Original instant IF calibration with explicit, regular acquisition cadence.

Only the supplied past calibration labels/scores are used. No data files are
read. This preserves the old baseline's score grid and ranking; only elapsed
time quantities are converted from the legacy one-minute metric convention.
Absent observations must occupy unavailable rows on the regular source axis.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

_PATH = Path(__file__).resolve().parents[1] / "gecco_v2" / "alarm_policy.py"
_SPEC = importlib.util.spec_from_file_location("mawrid_legacy_alarm_policy", _PATH)
_LEGACY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LEGACY)

# Prediction needs no labels, cadence or fitting. Its instant decisions are
# exactly the original baseline's, including nonfinite-score unavailability.
predict = _LEGACY.predict
COMPACT_KEYS = _LEGACY.COMPACT_KEYS


def select_baseline(labels, scores, cadence_seconds):
    """Return ``(chosen, compact_trials)`` using past calibration data only.

    Use the original baseline quantiles, instant policy and maximum
    ``(point F1, -false-positive samples, threshold)`` ranking. A trial is
    feasible only at <=1 false-positive run per observed normal day AND
    <=1% observed normal time under alarm, at the declared cadence.

    At 60 seconds all original selection fields and decisions match
    ``alarm_policy.select(..., baseline=True)``. Additional time fields have
    explicit minute units; counts remain samples, not minutes. No event labels
    are expanded, and unknown rows do not contribute normal exposure.

    Cadence is a fixed positive number of seconds per acquisition row. This
    does not infer timestamps, resample, change model windows or access any
    future evaluation labels. The caller freezes the returned choice before
    calling ``predict`` on a later score sequence.
    """
    if isinstance(cadence_seconds, (bool, np.bool_)) or np.ndim(cadence_seconds) != 0:
        raise ValueError("cadence_seconds must be a finite positive scalar")
    try:
        cadence = float(cadence_seconds)
    except (TypeError, ValueError):
        raise ValueError("cadence_seconds must be a finite positive scalar") from None
    if not np.isfinite(cadence) or cadence <= 0:
        raise ValueError("cadence_seconds must be a finite positive scalar")

    values = np.asarray(scores, dtype=float)
    truth = np.asarray(labels)
    if values.ndim != 1 or truth.ndim != 1 or truth.shape != values.shape:
        raise ValueError("labels and scores must be equal-length 1-D sequences")
    if truth.dtype.kind not in "biu" or not np.all(np.isin(truth, [0, 1])):
        raise ValueError("labels must contain only Boolean or binary integers")
    truth = truth.astype(bool, copy=False)
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise ValueError("calibration has no finite scores")
    no_events = not bool(truth.any())

    # These are the original baseline's quantile locations, including the
    # finite above-maximum no-alarm candidate and NumPy's default interpolation.
    quantiles = np.unique(np.r_[0, .5, .75, np.linspace(.8, .99, 191),
                                np.linspace(.99, 1, 201)])
    with np.errstate(over="ignore"):
        above_maximum = np.nextafter(finite.max(), np.inf)
    if not np.isfinite(above_maximum):
        raise ValueError("scores are too large for a finite no-alarm threshold")
    thresholds = np.unique(np.r_[np.quantile(finite, quantiles), above_maximum])
    minute_factor = cadence / 60.0
    trials = []
    for threshold in thresholds:
        metrics = _LEGACY.evaluate(truth, predict(values, threshold, "instant"))
        days = metrics["eligible_normal_days"] * minute_factor
        rate = metrics["false_alarm_runs_per_normal_day"]
        rate = rate / minute_factor if rate is not None else None
        duration = metrics["normal_time_under_alarm"]
        trial = {
            "threshold": float(threshold), "policy": "instant",
            "feasible": (rate is not None and duration is not None
                         and rate <= 1.0 and duration <= .01),
            "no_events": no_events,
            **{key: metrics[key] for key in COMPACT_KEYS},
            "cadence_seconds": cadence,
            "normal_valid_count": metrics["normal_valid_count"],
            "eligible_normal_days": days,
            "false_alarm_runs_per_normal_day": rate,
            "normal_observed_minutes": metrics["normal_valid_count"] * minute_factor,
            "normal_alarm_minutes": metrics["fp"] * minute_factor,
        }
        for key in ("median_detection_delay_minutes", "p95_detection_delay_minutes"):
            value = metrics[key]
            trial[key] = value * minute_factor if value is not None else None
        trials.append(trial)
    feasible = [trial for trial in trials if trial["feasible"]]
    if not feasible:
        raise ValueError("no policy has sufficient normal exposure to establish constraints")
    chosen = max(feasible, key=lambda r: (r["f1"] or 0, -r["fp"], r["threshold"]))
    return dict(chosen), trials
