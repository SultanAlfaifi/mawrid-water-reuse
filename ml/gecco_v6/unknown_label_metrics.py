"""Accounting on an unchanged row axis with {-1 unknown, 0 normal, 1 event} labels.

This module performs no inference, source IO, or prediction masking. Predictions
use {-1 unavailable, 0 quiet, 1 alarm} independently of label knowledge. Point
confusion counts include only known labels with an available prediction. Their
recall is therefore conditional on observation; positive-point coverage and
event denominators are reported separately so missing predictions cannot hide
known events. Durations are sample counts times the supplied cadence.

Every contiguous known-positive segment is retained for descriptive accounting.
A primary event needs an established onset: its first row must immediately
follow a known label 0. A segment at the first row or after label -1 has a
left-censored onset and is not another established event. Thus 0,1,-1,1,0 has
one primary onset and two known-positive segments, never two established
onsets. A primary interval may be right-censored by unknown labels or the end
of the series; its established onset still belongs in the primary denominator.
The number of underlying physical events across unknown intervals is unknown.

Confirmation requires adjacent ORIGINAL sensor predictions 0 -> 1 inside the
original primary positive interval. The initial prediction and -1 -> 1 do not
qualify. Unknown labels split false-positive runs but never alter predictions.
An alarm continuing across unknown labels can therefore produce two observed
false-positive runs; these are normal-alarm fragments, not two proven starts.

IDs are one-based known-positive-segment IDs, fixed solely by the original
labels. Primary IDs may have gaps when censored segments occur. Row indices
and confirmation times are local to the original supplied array, never a
compressed known-label/available-prediction axis. Callers must preserve context
or explicitly accept first-row censoring when evaluating a cropped block.
"""
from __future__ import annotations

from numbers import Real

import numpy as np


def _ternary(values, name):
    result = np.asarray(values)
    if result.ndim != 1 or result.dtype.kind not in "biu":
        raise ValueError(f"{name} must be a one-dimensional integer/bool array")
    if not np.isin(result, (-1, 0, 1)).all():
        raise ValueError(f"{name} must contain only -1, 0, 1")
    return result.astype(np.int8, copy=False)


def _cadence(value, n):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError("cadence must be a finite positive numeric scalar")
    value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise ValueError("cadence must be a finite positive numeric scalar")
    if n and value > np.finfo(float).max / n:
        raise ValueError("cadence times row count exceeds finite duration range")
    return value


def _ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def _spans(mask):
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    return np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)


def stats(labels, predictions, cadence=60):
    """Return V5-compatible keys plus explicit known/unknown/censored coverage.

    ``true_events`` is the primary established-onset count, not all positive
    segments. ``available_rows`` always measures original sensor availability
    over ALL labels. Zero-denominator fractions are None, including no-event
    recall. Empty integer arrays are allowed. Inputs are not mutated.
    """
    y, p = _ternary(labels, "labels"), _ternary(predictions, "predictions")
    if y.shape != p.shape:
        raise ValueError("labels and predictions must have equal shape")
    cadence = _cadence(cadence, len(y))
    n = len(y)
    known = y >= 0
    observed = p >= 0
    positive = y == 1
    normal = y == 0
    alarm = p == 1
    tp = int((positive & alarm).sum())
    fp = int((normal & alarm).sum())
    fn = int((positive & (p == 0)).sum())
    tn = int((normal & (p == 0)).sum())
    false = normal & alarm
    previous_false = np.r_[False, false[:-1]] if n else np.zeros(0, bool)
    runs = int((false & ~previous_false).sum())
    previous_quiet = np.r_[False, p[:-1] == 0] if n else np.zeros(0, bool)
    confirmed_start = alarm & previous_quiet
    starts, ends = _spans(positive)
    segments = []
    primary = []
    confirmed_ids, confirmed_times, latencies = [], [], []
    primary_covered = []
    for segment_id, (start, end) in enumerate(zip(starts, ends), 1):
        a, b = int(start), int(end)
        established = a > 0 and y[a - 1] == 0
        right_censored = b == n or y[b] == -1
        hits = np.flatnonzero(confirmed_start[a:b])
        confirmation = int(a + hits[0]) if len(hits) else None
        segment = {
            "event_id": segment_id,
            "start": a, "end_exclusive": b,
            "primary_uncensored_onset": bool(established),
            "left_censored": bool(not established),
            "left_censor_reason": None if established else (
                "series_start" if a == 0 else "preceding_unknown_label"),
            "right_censored": bool(right_censored),
            "right_censor_reason": (
                "series_end" if b == n else "following_unknown_label"
            ) if right_censored else None,
            "positive_rows": b - a,
            "observed_positive_rows": int(observed[a:b].sum()),
            "alarm_positive_rows": int(alarm[a:b].sum()),
            "any_alarm": bool(alarm[a:b].any()),
            "confirmed_transition_index": confirmation,
        }
        segments.append(segment)
        if established:
            primary.append(segment)
            if segment["any_alarm"]:
                primary_covered.append(segment_id)
            if confirmation is not None:
                confirmed_ids.append(segment_id)
                confirmed_times.append(confirmation)
                latencies.append((confirmation - a) * cadence)
    censored = [segment for segment in segments if segment["left_censored"]]
    known_rows = int(known.sum())
    available_rows = int(observed.sum())
    positive_rows = int(positive.sum())
    normal_rows = int(normal.sum())
    normal_observed = fp + tn
    normal_seconds = normal_observed * cadence
    positive_observed = tp + fn
    censored_rows = sum(segment["positive_rows"] for segment in censored)
    censored_observed = sum(segment["observed_positive_rows"] for segment in censored)
    censored_alarms = sum(segment["alarm_positive_rows"] for segment in censored)
    return {
        # V5 calibration/comparison compatibility. Primary event semantics differ
        # only as documented above; available_rows never depends on label masks.
        "true_events": len(primary),
        "confirmed_event_ids": confirmed_ids,
        "confirmed_times": confirmed_times,
        "confirmed_events": len(confirmed_ids),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "false_positive_runs": runs,
        "normal_observed_seconds": normal_seconds,
        "false_runs_per_day": _ratio(runs * 86400, normal_seconds),
        "normal_alarm_fraction": _ratio(fp, normal_observed),
        "fp_duration_seconds": fp * cadence,
        "available_rows": available_rows,
        # Coverage over the unchanged original timeline.
        "rows": n, "cadence_seconds": cadence, "nominal_seconds": n * cadence,
        "known_label_rows": known_rows, "unknown_label_rows": n - known_rows,
        "known_label_fraction": _ratio(known_rows, n),
        "sensor_available_fraction": _ratio(available_rows, n),
        "known_observed_rows": tp + fp + fn + tn,
        "known_label_observed_fraction": _ratio(tp + fp + fn + tn, known_rows),
        "unknown_label_observed_rows": int((~known & observed).sum()),
        "known_positive_rows": positive_rows,
        "known_normal_rows": normal_rows,
        "positive_observed_rows": positive_observed,
        "positive_unavailable_rows": positive_rows - positive_observed,
        "point_positive_observed_fraction": _ratio(positive_observed, positive_rows),
        "point_positive_alarm_coverage": _ratio(tp, positive_rows),
        "normal_observed_rows": normal_observed,
        "normal_unavailable_rows": normal_rows - normal_observed,
        "known_normal_observed_fraction": _ratio(normal_observed, normal_rows),
        "precision": _ratio(tp, tp + fp),
        "recall_observed_positive": _ratio(tp, tp + fn),
        "f1_observed_points": _ratio(2 * tp, 2 * tp + fp + fn),
        # All known-positive segments remain visible, including censored ones.
        "known_positive_segments": len(segments),
        "known_positive_segment_details": segments,
        "known_positive_segments_with_alarm": sum(s["any_alarm"] for s in segments),
        "known_positive_segments_fully_unobserved": sum(
            s["observed_positive_rows"] == 0 for s in segments),
        "left_censored_positive_segments": len(censored),
        "left_censored_segment_ids": [s["event_id"] for s in censored],
        "right_censored_positive_segments": sum(s["right_censored"] for s in segments),
        "fully_bounded_positive_segments": sum(
            not s["left_censored"] and not s["right_censored"] for s in segments),
        "left_censored_positive_rows": censored_rows,
        "left_censored_observed_positive_rows": censored_observed,
        "left_censored_positive_observed_fraction": _ratio(censored_observed, censored_rows),
        "left_censored_positive_alarm_coverage": _ratio(censored_alarms, censored_rows),
        "primary_event_ids": [s["event_id"] for s in primary],
        "primary_event_intervals": [
            {"event_id": s["event_id"], "start": s["start"],
             "end_exclusive": s["end_exclusive"], "right_censored": s["right_censored"]}
            for s in primary],
        "primary_events_fully_unobserved": sum(
            s["observed_positive_rows"] == 0 for s in primary),
        "primary_events_with_any_alarm": len(primary_covered),
        "primary_event_alarm_coverage": _ratio(len(primary_covered), len(primary)),
        "confirmed_event_recall": _ratio(len(confirmed_ids), len(primary)),
        "confirmed_latency_seconds": latencies,
        "median_confirmed_latency_seconds": float(np.median(latencies)) if latencies else None,
        "sensor_confirmed_alarm_starts": int(confirmed_start.sum()),
    }


def comparison(labels, base, prediction, cadence=60):
    """Compare original sensor availability and matched primary event IDs.

    This never masks either prediction by known labels or common availability.
    Same-time label censoring is identical for both methods. Paired latency
    differences use the first confirmed start in the same original interval.
    """
    y = _ternary(labels, "labels")
    baseline = _ternary(base, "baseline predictions")
    candidate = _ternary(prediction, "candidate predictions")
    if baseline.shape != y.shape or candidate.shape != y.shape:
        raise ValueError("labels, baseline and candidate must have equal shape")
    cadence = _cadence(cadence, len(y))
    b, c = stats(y, baseline, cadence), stats(y, candidate, cadence)
    bt = dict(zip(b["confirmed_event_ids"], b["confirmed_times"]))
    ct = dict(zip(c["confirmed_event_ids"], c["confirmed_times"]))
    onsets = {event["event_id"]: event["start"] for event in b["primary_event_intervals"]}
    paired = [
        {"event_id": event_id,
         "extra_delay_seconds": (ct[event_id] - bt[event_id]) * cadence,
         "baseline_confirmation_index": bt[event_id],
         "candidate_confirmation_index": ct[event_id],
         "baseline_latency_seconds": (bt[event_id] - onsets[event_id]) * cadence,
         "candidate_latency_seconds": (ct[event_id] - onsets[event_id]) * cadence}
        for event_id in bt if event_id in ct
    ]
    return {
        "baseline": b, "candidate": c,
        "lost_baseline_event_ids": sorted(set(bt) - set(ct)),
        "hidden_baseline_rows": int(((baseline >= 0) & (candidate < 0)).sum()),
        "paired_extra_delays": paired,
        "retained_baseline_event_ids": sorted(set(bt) & set(ct)),
        "new_candidate_event_ids": sorted(set(ct) - set(bt)),
        "added_candidate_available_rows": int(((baseline < 0) & (candidate >= 0)).sum()),
        "sensor_availability_equal": bool(np.array_equal(baseline >= 0, candidate >= 0)),
        "common_sensor_available_rows": int(((baseline >= 0) & (candidate >= 0)).sum()),
        "common_known_observed_rows": int(((y >= 0) & (baseline >= 0) & (candidate >= 0)).sum()),
    }


def _stats(labels, predictions, cadence_seconds=60):
    """V5 keyword-compatible wrapper; primary onset semantics are documented above."""
    return stats(labels, predictions, cadence_seconds)


def _comparison(labels, base, prediction, cadence):
    return comparison(labels, base, prediction, cadence)
