"""Causal alarm policies and calibration-only operating-point selection.

``select`` must receive the past calibration partition, never final-test labels.
No files or data sets are read. The evaluation implementation is the reviewed
v1 metrics module; only compact scalar metrics are retained in the sweep.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

_METRICS_PATH = Path(__file__).resolve().parents[1] / "gecco_baseline" / "metrics.py"
_SPEC = importlib.util.spec_from_file_location("mawrid_gecco_v1_metrics", _METRICS_PATH)
_METRICS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_METRICS)
evaluate = _METRICS.evaluate

POLICIES = {"instant": (1, 1), "2of3": (2, 3), "3of5": (3, 5)}
COMPACT_KEYS = (
    "sample_count", "valid_count", "unavailable_count", "prediction_coverage",
    "precision", "recall", "f1", "tp", "fp", "fn", "tn", "true_events",
    "detected_events", "event_recall", "confirmed_new_alarm_inside_events",
    "confirmed_new_alarm_inside_event_recall", "false_positive_runs",
    "eligible_normal_days", "false_alarm_runs_per_normal_day",
    "normal_time_under_alarm",
)


def _scores(values):
    scores = np.asarray(values, dtype=float)
    if scores.ndim != 1:
        raise ValueError("scores must be one-dimensional")
    return scores


def predict(scores, threshold, policy="instant"):
    """Return {-1, 0, 1} predictions using only the current and past scores.

    A policy m-of-n returns a prediction only when all n scores in its trailing
    window are finite. Missing/infinite scores invalidate the window and prevent
    bridging an unavailable interval. The first n-1 rows are unavailable.
    """
    values = _scores(scores)
    if policy not in POLICIES:
        raise ValueError(f"unknown alarm policy: {policy}")
    threshold = float(threshold)
    if not np.isfinite(threshold):
        raise ValueError("threshold must be finite")
    m, n = POLICIES[policy]
    result = np.full(len(values), -1, dtype=np.int8)
    if len(values) < n:
        return result
    finite = np.isfinite(values)
    positive = finite & (values >= threshold)
    kernel = np.ones(n, dtype=np.int64)
    valid_counts = np.convolve(finite.astype(np.int64), kernel, mode="valid")
    votes = np.convolve(positive.astype(np.int64), kernel, mode="valid")
    eligible = valid_counts == n
    current_indices = np.arange(n - 1, len(values))[eligible]
    result[current_indices] = (votes[eligible] >= m).astype(np.int8)
    return result


def _feasible(metrics):
    rate = metrics["false_alarm_runs_per_normal_day"]
    duration = metrics["normal_time_under_alarm"]
    return (rate is not None and duration is not None
            and rate <= 1.0 and duration <= .01)


def select(labels, scores, baseline=False):
    """Return ``(selected_dict, compact_trials)`` from calibration data only.

    Baseline selection reproduces v1's instant-policy quantile sweep and
    (point F1, fewer false-positive minutes, higher threshold) ranking.

    V2 ranks feasible candidates by confirmed-event recall, point F1, fewer
    false-positive minutes, higher threshold, then instant-policy preference.
    If calibration contains no events, v2 uses 2of3 and the lowest feasible
    threshold. ``selected['no_events']`` records this condition. Baseline stays
    instant even without events. Missing scores never enter score quantiles.

    A ValueError is raised if there are no finite scores or no eligible normal
    exposure on which the operating constraints can be established.
    """
    values = _scores(scores)
    truth = np.asarray(labels)
    if truth.ndim != 1 or truth.shape != values.shape:
        raise ValueError("labels and scores must be equal-length 1-D sequences")
    if truth.dtype.kind not in "biu" or not np.all(np.isin(truth, [0, 1])):
        raise ValueError("labels must contain only Boolean or binary integers")
    truth = truth.astype(bool, copy=False)
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise ValueError("calibration has no finite scores")
    no_events = not bool(truth.any())
    if baseline:
        quantiles = np.unique(np.r_[0, .5, .75, np.linspace(.8, .99, 191),
                                    np.linspace(.99, 1, 201)])
        policies = ["instant"]
    else:
        quantiles = np.unique(np.r_[np.linspace(0, .95, 96),
                                    np.linspace(.95, 1, 101)])
        policies = list(POLICIES)
    above_maximum = np.nextafter(finite.max(), np.inf)
    if not np.isfinite(above_maximum):
        raise ValueError("scores are too large for a finite no-alarm threshold")
    thresholds = np.unique(np.r_[np.quantile(finite, quantiles), above_maximum])
    trials = []
    for policy in policies:
        for threshold in thresholds:
            metrics = evaluate(truth, predict(values, threshold, policy))
            trials.append({
                "threshold": float(threshold), "policy": policy,
                "feasible": _feasible(metrics), "no_events": no_events,
                **{key: metrics[key] for key in COMPACT_KEYS},
            })
    feasible = [trial for trial in trials if trial["feasible"]]
    if no_events and not baseline:
        feasible = [trial for trial in feasible if trial["policy"] == "2of3"]
    if not feasible:
        raise ValueError("no policy has sufficient normal exposure to establish constraints")
    if baseline:
        chosen = max(feasible, key=lambda r: (r["f1"] or 0, -r["fp"], r["threshold"]))
    elif no_events:
        chosen = min(feasible, key=lambda r: r["threshold"])
    else:
        chosen = max(feasible, key=lambda r: (
            r["confirmed_new_alarm_inside_event_recall"] or 0,
            r["f1"] or 0, -r["fp"], r["threshold"], r["policy"] == "instant",
        ))
    return dict(chosen), trials
