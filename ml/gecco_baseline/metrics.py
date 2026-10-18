"""Honest point and event metrics for a one-minute anomaly-detection series.

Prediction -1 means unavailable, 0 means normal, and 1 means alarm. Point
metrics exclude unavailable predictions. Event recall retains *every* labeled
event in its denominator, including events with no available predictions.
There is no point adjustment, label expansion, or retroactive detection.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def run_intervals(mask: Any) -> list[tuple[int, int]]:
    """Return maximal true runs as zero-based, end-exclusive index pairs.

    The input must be a one-dimensional Boolean or binary integer sequence.
    An empty input returns an empty list.
    """
    values = _binary_mask(mask, "mask")
    if not values.size:
        return []
    padded = np.concatenate(([False], values, [False])).astype(np.int8)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return [(int(start), int(end)) for start, end in zip(starts, ends)]


def _binary_mask(values: Any, name: str) -> np.ndarray:
    result = np.asarray(values)
    if result.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if not result.size:
        return result.astype(bool)
    if result.dtype.kind not in "biu" or not np.all(np.isin(result, [0, 1])):
        raise ValueError(f"{name} must contain only Boolean or binary integer values")
    return result.astype(bool, copy=False)


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator / denominator) if denominator else None


def evaluate(labels: Any, predictions: Any) -> dict[str, Any]:
    """Evaluate equal-length, one-dimensional sequences at one-minute cadence.

    ``labels`` is Boolean (binary integers are also accepted). ``predictions``
    must contain integers in {-1, 0, 1}. Undefined ratios and delay summaries
    are ``None`` so the result is JSON serializable without NaN/Infinity.

    ``false_positive_runs`` counts contiguous predicted alarms outside true
    events. True event boundaries and unavailable predictions split these
    runs, including the normal tails of a long alarm. The daily rate uses
    eligible normal observation time: ``normal_valid_count / 1440`` days.
    ``alarm_runs`` counts raw contiguous prediction==1 runs across all labels.

    An event is detected if any prediction in its original labeled interval
    is 1. Delay is the first such index minus the event's start, in minutes.
    ``covered_at_onset_events`` counts events with an alarm at their first
    sample, even when that alarm began earlier. Independently,
    ``raw_new_alarm_inside_events`` counts events containing at least one raw alarm
    start (including at their onset). A start requires the previous prediction
    not to be 1. An unavailable previous prediction counts as inactive but is
    explicitly flagged in the event record. At index zero the prior state is
    unknown and is also flagged. Thus a long pre-existing alarm can cover
    multiple events without being credited as a new start in each event.
    ``confirmed_new_alarm_inside_events`` is stricter: it requires an observed
    normal-to-alarm transition (previous prediction == 0). A -1-to-1 transition
    and an alarm at index zero cannot provide a confirmed new start. If an
    event has an unconfirmed start followed by a confirmed start, its confirmed
    delay is measured to the latter, independently of the first coverage alarm.
    Unprefixed ``new_alarm_inside_events`` and ``new_alarm_inside_event_recall``
    remain compatibility aliases for the raw-start metrics, not confirmed starts.
    Delay summaries use coverage-detected events only (linear percentile).
    Events touching either series boundary are marked boundary-censored;
    complete-event recalls exclude these, while overall recalls retain them.

    This function does not tune thresholds or read data from disk.
    """
    truth = _binary_mask(labels, "labels")
    predicted = np.asarray(predictions)
    if predicted.ndim != 1:
        raise ValueError("predictions must be one-dimensional")
    if predicted.shape != truth.shape:
        raise ValueError("labels and predictions must have the same length")
    if predicted.size and (
        predicted.dtype.kind not in "iu"
        or not np.all(np.isin(predicted, [-1, 0, 1]))
    ):
        raise ValueError("predictions must contain only integers -1, 0, or 1")

    valid = predicted != -1
    alarm = predicted == 1
    alarm_start = alarm & ~np.concatenate(([False], alarm[:-1])) if alarm.size else alarm
    confirmed_alarm_start = (
        alarm & np.concatenate(([False], predicted[:-1] == 0)) if alarm.size else alarm
    )
    normal_valid = valid & ~truth
    positive_valid = valid & truth
    false_alarm = alarm & ~truth
    tp = int(np.count_nonzero(alarm & truth))
    fp = int(np.count_nonzero(false_alarm))
    fn = int(np.count_nonzero((predicted == 0) & truth))
    tn = int(np.count_nonzero((predicted == 0) & ~truth))
    valid_count = int(np.count_nonzero(valid))
    normal_valid_count = int(np.count_nonzero(normal_valid))
    positive_valid_count = int(np.count_nonzero(positive_valid))
    normal_days = normal_valid_count / 1440.0

    false_alarm_records = [
        {"start": start, "end": end, "duration_minutes": end - start}
        for start, end in run_intervals(false_alarm)
    ]
    event_records: list[dict[str, Any]] = []
    delays: list[int] = []
    for start, end in run_intervals(truth):
        event_valid_count = int(np.count_nonzero(valid[start:end]))
        positive_offsets = np.flatnonzero(alarm[start:end])
        detected = bool(positive_offsets.size)
        delay = int(positive_offsets[0]) if detected else None
        first_alarm = start + delay if delay is not None else None
        onset_covered = bool(alarm[start])
        new_alarm_offsets = np.flatnonzero(alarm_start[start:end])
        new_alarm_detected = bool(new_alarm_offsets.size)
        new_alarm_delay = int(new_alarm_offsets[0]) if new_alarm_detected else None
        new_alarm_index = start + new_alarm_delay if new_alarm_delay is not None else None
        confirmed_offsets = np.flatnonzero(confirmed_alarm_start[start:end])
        confirmed_detected = bool(confirmed_offsets.size)
        confirmed_delay = int(confirmed_offsets[0]) if confirmed_detected else None
        confirmed_index = start + confirmed_delay if confirmed_delay is not None else None
        previous_unavailable = bool(
            new_alarm_index is not None
            and new_alarm_index > 0
            and predicted[new_alarm_index - 1] == -1
        )
        if delay is not None:
            delays.append(delay)
        event_records.append(
            {
                "event_id": len(event_records) + 1,
                "start": start,
                "end": end,
                "duration_minutes": end - start,
                "boundary_censored": start == 0 or end == truth.size,
                "valid_count": event_valid_count,
                "unavailable_count": end - start - event_valid_count,
                "fully_unscorable": event_valid_count == 0,
                "detected": detected,
                "first_alarm_index": first_alarm,
                "detection_delay_minutes": delay,
                "covered_at_onset": onset_covered,
                "new_alarm_inside_event": new_alarm_detected,
                "new_alarm_start_index": new_alarm_index,
                "new_alarm_delay_minutes": new_alarm_delay,
                "new_alarm_previous_unavailable": previous_unavailable,
                "new_alarm_previous_unknown": new_alarm_index == 0 or previous_unavailable,
                "confirmed_new_alarm_inside_event": confirmed_detected,
                "confirmed_new_alarm_index": confirmed_index,
                "confirmed_new_alarm_delay_minutes": confirmed_delay,
                "alarm_started_at_onset": bool(alarm_start[start]),
                "detection_kind": (
                    "covered_at_onset"
                    if onset_covered
                    else "first_alarm_after_onset" if detected else "undetected"
                ),
            }
        )

    true_events = len(event_records)
    detected_events = len(delays)
    new_alarm_events = sum(record["new_alarm_inside_event"] for record in event_records)
    confirmed_new_alarm_events = sum(
        record["confirmed_new_alarm_inside_event"] for record in event_records
    )
    complete_records = [record for record in event_records if not record["boundary_censored"]]
    complete_detected = sum(record["detected"] for record in complete_records)
    complete_new_alarm = sum(record["new_alarm_inside_event"] for record in complete_records)
    complete_confirmed_new_alarm = sum(
        record["confirmed_new_alarm_inside_event"] for record in complete_records
    )
    return {
        "sample_count": int(truth.size),
        "valid_count": valid_count,
        "unavailable_count": int(truth.size) - valid_count,
        "prediction_coverage": _ratio(valid_count, int(truth.size)),
        "normal_valid_count": normal_valid_count,
        "positive_valid_count": positive_valid_count,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "f1": _ratio(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": _ratio(fp, fp + tn),
        "false_negative_rate": _ratio(fn, fn + tp),
        "specificity": _ratio(tn, tn + fp),
        "accuracy": _ratio(tp + tn, valid_count),
        "false_positive_runs": len(false_alarm_records),
        "eligible_normal_days": normal_days,
        "false_alarm_runs_per_normal_day": _ratio(len(false_alarm_records), normal_days),
        "normal_time_under_alarm": _ratio(fp, normal_valid_count),
        "alarm_runs": len(run_intervals(alarm)),
        "true_events": true_events,
        "detected_events": detected_events,
        "undetected_events": true_events - detected_events,
        "fully_unscorable_events": sum(
            record["fully_unscorable"] for record in event_records
        ),
        "event_recall": _ratio(detected_events, true_events),
        "new_alarm_inside_event_recall": _ratio(new_alarm_events, true_events),
        "raw_new_alarm_inside_event_recall": _ratio(new_alarm_events, true_events),
        "confirmed_new_alarm_inside_event_recall": _ratio(confirmed_new_alarm_events, true_events),
        "covered_at_onset_events": sum(
            record["covered_at_onset"] for record in event_records
        ),
        "new_alarm_inside_events": new_alarm_events,
        "raw_new_alarm_inside_events": new_alarm_events,
        "confirmed_new_alarm_inside_events": confirmed_new_alarm_events,
        "boundary_censored_events": true_events - len(complete_records),
        "complete_events": len(complete_records),
        "complete_detected_events": complete_detected,
        "complete_new_alarm_inside_events": complete_new_alarm,
        "complete_confirmed_new_alarm_inside_events": complete_confirmed_new_alarm,
        "complete_event_coverage": _ratio(complete_detected, len(complete_records)),
        "complete_event_new_alarm_start_recall": _ratio(complete_new_alarm, len(complete_records)),
        "complete_raw_new_alarm_start_recall": _ratio(complete_new_alarm, len(complete_records)),
        "complete_confirmed_new_alarm_start_recall": _ratio(complete_confirmed_new_alarm, len(complete_records)),
        "median_detection_delay_minutes": float(np.median(delays)) if delays else None,
        "p95_detection_delay_minutes": float(np.percentile(delays, 95)) if delays else None,
        "event_records": event_records,
        "false_alarm_records": false_alarm_records,
    }
