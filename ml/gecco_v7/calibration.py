"""Joint, past-only calibration of V7 long-context suppression and rescue.

The fixed candidate grid evaluates the final combined output. Suppression never
hides reference availability and latches a retained alarm until that reference
alarm clears. Rescue requires current evidence, so persistence cannot invent a
tail after the score clears. Neither predictor receives labels.

Calibration labels are {-1 unknown, 0 normal, 1 event}; prediction availability
is independent. Metrics retain the original row axis and V6 established-onset
event identities. Each block starts with fresh predictor state, while pooled
metrics use the adjacent, uncompressed acquisition axis. No source IO occurs.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

_V6 = str(Path(__file__).resolve().parents[1] / "gecco_v6")
if _V6 not in sys.path:
    sys.path.append(_V6)
from latched_suppression import _gate, POLICIES
from unknown_label_metrics import stats as full_stats


MIN_EVENTS = 5
MIN_EVENTFUL_BLOCKS = 2
MIN_NORMAL_MINUTES_PER_BLOCK = 1440
MIN_TOTAL_NORMAL_MINUTES = 5760
MIN_OBSERVED_BLOCKS = 2
MIN_RESCUE_EVENTS = 2
MIN_RESCUE_EVENTFUL_BLOCKS = 2


def _ternary(values, name):
    array = np.asarray(values)
    if array.ndim != 1 or array.dtype.kind not in "biu" or not np.isin(array, [-1, 0, 1]).all():
        raise ValueError(f"{name} must be a one-dimensional ternary integer array")
    return array.astype(np.int8, copy=False)


def _choice(low=None, high=None, policy="instant"):
    return {"decision": "reference" if low is None and high is None else "candidate",
            "low_threshold": low, "high_threshold": high, "policy": policy}


def _validate_choice(selected):
    low, high = selected.get("low_threshold"), selected.get("high_threshold")
    policy = selected.get("policy", "instant")
    if policy not in POLICIES:
        raise ValueError("Unknown persistence policy")
    for threshold in (low, high):
        if threshold is not None and (isinstance(threshold, (bool, np.bool_)) or
                                      not np.isscalar(threshold) or not np.isfinite(threshold)):
            raise ValueError("Thresholds must be finite numeric scalars or None")
    if low is not None and high is not None and low > high:
        raise ValueError("Suppression threshold must not exceed rescue threshold")
    expected = "reference" if low is None and high is None else "candidate"
    if selected.get("decision", expected) != expected:
        raise ValueError("Decision and active thresholds disagree")
    return low, high, policy


def _latched_seed(reference, scores, low, policy):
    result = reference.copy()
    if low is None or not len(result):
        return result
    gate = _gate(scores, low, policy)
    result[(reference == 1) & (gate == 0)] = 0
    index = np.arange(len(result))
    last_reset = np.maximum.accumulate(np.where(reference != 1, index, -1))
    last_keep = np.maximum.accumulate(np.where((reference == 1) & (result == 1), index, -1))
    result[(reference == 1) & (last_keep > last_reset)] = 1
    return result


def _rescue_mask(scores, high, policy):
    return (_gate(scores, high, policy) == 1) & np.isfinite(scores) & (scores >= high)


def predict(reference, long_scores, selected):
    """Causal batch predictor; prefix-invariant when selected is fixed.

    Each invocation starts fresh. Unknown scores preserve the reference under
    suppression; rescue can only add alarms on reference-observed rows.
    """
    reference = _ternary(reference, "reference")
    scores = np.asarray(long_scores, float)
    if scores.shape != reference.shape:
        raise ValueError("Scores and reference must have the same shape")
    low, high, policy = _validate_choice(selected)
    result = _latched_seed(reference, scores, low, policy)
    if high is not None:
        result[(reference >= 0) & _rescue_mask(scores, high, policy)] = 1
    return result


class _MetricContext:
    """Vectorized repeated accounting, cross-checked against V6 for selection."""

    def __init__(self, labels):
        self.labels = _ternary(labels, "labels")
        self.positive = self.labels == 1
        self.normal = self.labels == 0
        change = np.diff(np.r_[False, self.positive, False].astype(np.int8))
        starts, ends = np.flatnonzero(change == 1), np.flatnonzero(change == -1)
        self.primary_intervals = [(i, int(a), int(b)) for i, (a, b) in
                                  enumerate(zip(starts, ends), 1)
                                  if a > 0 and self.labels[a - 1] == 0]
        self.event_ids = np.zeros(len(self.labels), np.int32)
        for event_id, a, b in self.primary_intervals:
            self.event_ids[a:b] = event_id
        self.segment_count = len(starts)

    def measure(self, prediction):
        p = np.asarray(prediction)
        alarm = p == 1
        false = self.normal & alarm
        runs = int(np.count_nonzero(false & ~np.r_[False, false[:-1]]))
        confirmed = alarm & np.r_[False, p[:-1] == 0]
        hit = np.flatnonzero(confirmed & (self.event_ids > 0))
        first = np.full(self.segment_count + 1, len(p), dtype=np.int64)
        np.minimum.at(first, self.event_ids[hit], hit)
        found = np.flatnonzero(first < len(p))
        return {"true_events": len(self.primary_intervals),
                "confirmed_event_ids": found.tolist(), "confirmed_times": first[found].tolist(),
                "confirmed_events": len(found), "tp": int(np.count_nonzero(self.positive & alarm)),
                "fp": int(false.sum()), "false_positive_runs": runs,
                "normal_observed_rows": int(np.count_nonzero(self.normal & (p >= 0))),
                "available_rows": int(np.count_nonzero(p >= 0))}


def _validated(blocks, cadence_seconds):
    if not blocks:
        raise ValueError("At least one calibration block is required")
    if isinstance(cadence_seconds, (bool, np.bool_)) or not np.isscalar(cadence_seconds) or not np.isfinite(cadence_seconds) or cadence_seconds <= 0:
        raise ValueError("Finite positive cadence_seconds required")
    clean = []
    next_start = None
    for i, block in enumerate(blocks):
        y = _ternary(block["labels"], "labels")
        reference = _ternary(block["reference"], "reference")
        scores = np.asarray(block["long_scores"], float)
        if not len(y) or y.shape != reference.shape or y.shape != scores.shape:
            raise ValueError("Block arrays must have equal nonempty one-dimensional shape")
        start = block["source_start"]
        if isinstance(start, (bool, np.bool_)) or not isinstance(start, (int, np.integer)) or start < 0:
            raise ValueError("source_start must be a nonnegative integer")
        if next_start is not None and start != next_start:
            raise ValueError("Calibration blocks must be adjacent on the original source axis")
        next_start = int(start) + len(y)
        clean.append({"labels": y, "reference": reference, "long_scores": scores,
                      "source_start": int(start), "block_id": str(block.get("block_id", i))})
    if sum(len(b["labels"]) for b in clean) * float(cadence_seconds) > np.finfo(float).max:
        raise ValueError("Cadence times row count exceeds finite duration range")
    return clean


def _grid(values, quantiles, *, above_max=False):
    finite = values[np.isfinite(values)]
    if not len(finite):
        return []
    thresholds = np.quantile(finite, quantiles)
    if above_max:
        with np.errstate(over="ignore"):
            thresholds = np.r_[thresholds, np.nextafter(finite.max(), np.inf)]
    return np.unique(thresholds[np.isfinite(thresholds)]).tolist()


def _rank(trial):
    low, high = trial["low_threshold"], trial["high_threshold"]
    return (-trial["events"], -trial["tp"], trial["false_runs"], trial["fp"],
            int(low is not None) + int(high is not None),
            low if low is not None else -np.inf,
            -high if high is not None else -np.inf,
            list(POLICIES).index(trial["policy"]))


def calibrate(blocks, *, cadence_seconds=60):
    """Select only from supplied past blocks, returning (selected, all_trials).

    Every candidate must preserve all known-positive reference alarm rows,
    confirmed event identities and paired latency globally and in every block.
    Neither false-normal fragments nor false-normal duration may increase in
    any block, including short-exposure blocks. Evidence minima govern both
    optional paths; insufficient evidence always returns unchanged reference.
    """
    blocks = _validated(blocks, cadence_seconds)
    labels = np.concatenate([b["labels"] for b in blocks])
    reference = np.concatenate([b["reference"] for b in blocks])
    scores = np.concatenate([b["long_scores"] for b in blocks])
    bounds = np.r_[0, np.cumsum([len(b["labels"]) for b in blocks])]
    contexts = [_MetricContext(labels)] + [_MetricContext(b["labels"]) for b in blocks]
    references = [reference] + [b["reference"] for b in blocks]
    metrics = [c.measure(p) for c, p in zip(contexts, references)]
    reference_times = [dict(zip(m["confirmed_event_ids"], m["confirmed_times"])) for m in metrics]
    qualified = [i for i, m in enumerate(metrics[1:]) if
                 m["normal_observed_rows"] * cadence_seconds >= MIN_NORMAL_MINUTES_PER_BLOCK * 60]
    normal_seconds = sum(metrics[i + 1]["normal_observed_rows"] * cadence_seconds for i in qualified)
    enough_exposure = len(qualified) >= MIN_OBSERVED_BLOCKS and normal_seconds >= MIN_TOTAL_NORMAL_MINUTES * 60
    # Original global onsets have one owner, including onsets exactly at a block
    # boundary. Censored continuation fragments cannot multiply this evidence.
    eventful = sorted({int(np.searchsorted(bounds, a, side="right") - 1)
                       for _, a, _ in contexts[0].primary_intervals})
    enough_events = metrics[0]["true_events"] >= MIN_EVENTS and len(eventful) >= MIN_EVENTFUL_BLOCKS
    evidence = {"cadence_seconds": float(cadence_seconds), "reference": metrics[0],
                "block_reference": metrics[1:], "qualified_blocks": qualified,
                "qualified_block_ids": [blocks[i]["block_id"] for i in qualified],
                "eventful_blocks": eventful, "enough_exposure": bool(enough_exposure),
                "enough_labeled_events": bool(enough_events), "min_events": MIN_EVENTS,
                "min_eventful_blocks": MIN_EVENTFUL_BLOCKS,
                "min_normal_minutes_per_block": MIN_NORMAL_MINUTES_PER_BLOCK,
                "min_total_normal_minutes": MIN_TOTAL_NORMAL_MINUTES,
                "min_observed_blocks": MIN_OBSERVED_BLOCKS,
                "min_rescue_events": MIN_RESCUE_EVENTS,
                "min_rescue_eventful_blocks": MIN_RESCUE_EVENTFUL_BLOCKS,
                "source_range": [blocks[0]["source_start"], blocks[-1]["source_start"] + len(blocks[-1]["labels"])],
                "event_ownership": "original global primary onset; rescue uses first added positive row"}
    trials = []

    def assess(choice, seeds, rescue_masks=None):
        predictions = [s.copy() for s in seeds]
        if rescue_masks is not None:
            for block, p, rescue in zip(blocks, predictions, rescue_masks):
                p[(block["reference"] >= 0) & rescue] = 1
        prediction = np.concatenate(predictions)
        candidate_metrics = [c.measure(p) for c, p in zip(contexts, [prediction] + predictions)]
        reasons = []
        lost_ids, delayed_ids = [], []
        for old_times, m in zip(reference_times, candidate_metrics):
            times = dict(zip(m["confirmed_event_ids"], m["confirmed_times"]))
            lost_ids.append(sorted(set(old_times) - set(times)))
            delayed_ids.append(sorted(i for i, t in old_times.items() if i in times and times[i] > t))
        lost_blocks = [i for i, lost in enumerate(lost_ids[1:]) if lost]
        delayed_blocks = [i for i, delayed in enumerate(delayed_ids[1:]) if delayed]
        if lost_ids[0]: reasons.append("lost_reference_event_global")
        if lost_blocks: reasons.append("lost_reference_event_in_block")
        if delayed_ids[0]: reasons.append("added_reference_delay_global")
        if delayed_blocks: reasons.append("added_reference_delay_in_block")
        positive_loss = int(np.count_nonzero((labels == 1) & (reference == 1) & (prediction != 1)))
        if positive_loss: reasons.append("lost_reference_positive_alarm_rows")
        availability_equal = bool(np.array_equal(reference >= 0, prediction >= 0))
        if not availability_equal: reasons.append("changed_reference_availability")
        fp_more = [i for i, (r, c) in enumerate(zip(metrics, candidate_metrics)) if c["fp"] > r["fp"]]
        runs_more = [i for i, (r, c) in enumerate(zip(metrics, candidate_metrics)) if c["false_positive_runs"] > r["false_positive_runs"]]
        if 0 in fp_more: reasons.append("added_false_duration_global")
        if any(i > 0 for i in fp_more): reasons.append("added_false_duration_in_block")
        if 0 in runs_more: reasons.append("added_false_fragments_global")
        if any(i > 0 for i in runs_more): reasons.append("added_false_fragments_in_block")
        added_ids, added_blocks = [], []
        if choice["high_threshold"] is not None:
            seed = np.concatenate(seeds)
            added = (labels == 1) & (prediction == 1) & (seed != 1)
            primary_added = np.flatnonzero(added & (contexts[0].event_ids > 0))
            if len(primary_added):
                ids, first_positions = np.unique(contexts[0].event_ids[primary_added], return_index=True)
                first_additions = primary_added[first_positions]
                added_ids = ids.tolist()
                added_blocks = np.unique(np.searchsorted(bounds, first_additions, side="right") - 1).tolist()
            if len(added_ids) < MIN_RESCUE_EVENTS: reasons.append("too_few_rescue_coverage_events")
            if len(added_blocks) < MIN_RESCUE_EVENTFUL_BLOCKS: reasons.append("rescue_coverage_concentrated_in_too_few_blocks")
        if choice["decision"] != "reference":
            if not enough_exposure: reasons.append("insufficient_observed_normal_exposure")
            if not enough_events: reasons.append("insufficient_primary_event_representation")
        c = candidate_metrics[0]
        result = {**choice, "feasible": not reasons, "rejection_reasons": reasons,
                  "events": c["confirmed_events"], "tp": c["tp"], "fp": c["fp"],
                  "false_runs": c["false_positive_runs"],
                  "new_event_ids": sorted(set(c["confirmed_event_ids"]) - set(metrics[0]["confirmed_event_ids"])),
                  "lost_event_ids": lost_ids[0], "lost_event_blocks": lost_blocks,
                  "delayed_event_ids": delayed_ids[0], "delayed_event_blocks": delayed_blocks,
                  "lost_positive_alarm_rows": positive_loss, "availability_equal": availability_equal,
                  "added_false_duration_blocks": [i - 1 for i in fp_more if i > 0],
                  "added_false_fragment_blocks": [i - 1 for i in runs_more if i > 0],
                  "rescue_coverage_event_ids": added_ids, "rescue_coverage_blocks": added_blocks}
        trials.append(result)

    assess(_choice(), [b["reference"] for b in blocks])
    if enough_events and enough_exposure:
        lows = [None] + _grid(scores[reference == 1], np.linspace(0, 1, 21))
        highs = [None] + _grid(scores, np.linspace(.90, 1, 41), above_max=True)
        for policy in POLICIES:
            rescue_cache = {high: [_rescue_mask(b["long_scores"], high, policy) for b in blocks]
                            for high in highs if high is not None}
            for low in lows:
                seeds = [_latched_seed(b["reference"], b["long_scores"], low, policy) for b in blocks]
                for high in highs:
                    if low is None and high is None:
                        continue
                    if low is not None and high is not None and low > high:
                        continue
                    assess(_choice(low, high, policy), seeds, rescue_cache.get(high))
    selected = min((t for t in trials if t["feasible"]), key=_rank)
    predictions = [predict(b["reference"], b["long_scores"], selected) for b in blocks]
    # Independent, frozen V6 metrics verify the optimized selection accounting.
    verification = [full_stats(y, p, cadence_seconds) for y, p in
                    zip([labels] + [b["labels"] for b in blocks], [np.concatenate(predictions)] + predictions)]
    fast_verification = [c.measure(p) for c, p in zip(contexts, [np.concatenate(predictions)] + predictions)]
    for fast, full in zip(fast_verification, verification):
        for key, value in fast.items():
            if value != full[key]:
                raise AssertionError(f"Optimized calibration accounting differs from frozen V6: {key}")
    if not enough_exposure:
        status = "insufficient_observed_normal_exposure"
    elif not enough_events:
        status = "insufficient_primary_event_representation"
    elif selected["decision"] == "reference":
        status = "reference_retained"
    else:
        status = "joint_operating_point_selected"
    return {**selected, "status": status, "evidence": evidence,
            "calibration_metrics": verification[0], "calibration_block_metrics": verification[1:],
            "trial_count": len(trials)}, trials
