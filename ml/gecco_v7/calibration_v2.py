"""V7 run02 joint calibration: guarded suppression and zero-normal-addition rescue.

Separate gate_scores affect only lower-threshold suppression. Missing guarded
scores preserve reference alarms; raw long_scores still drive rescue. Rescue
may add no known-normal alarm row versus its pure gated seed in any calibration
block or pooled timeline, so suppression cannot finance a new false rescue.

All original V7 event identity, paired-latency, positive-row and availability
constraints remain. This module is a new disclosed-development recipe; the
frozen run01 calibration.py is unchanged. No file or source data is read here.
"""
from __future__ import annotations

import numpy as np

from ml.gecco_v7.calibration import (
    MIN_EVENTS, MIN_EVENTFUL_BLOCKS, MIN_NORMAL_MINUTES_PER_BLOCK,
    MIN_TOTAL_NORMAL_MINUTES, MIN_OBSERVED_BLOCKS, MIN_RESCUE_EVENTS,
    MIN_RESCUE_EVENTFUL_BLOCKS, POLICIES, _MetricContext, _choice, _grid,
    _latched_seed, _rank, _rescue_mask, _ternary, _validated, _validate_choice,
    full_stats,
)


def _validated_gate_blocks(blocks, cadence_seconds):
    validated = _validated(blocks, cadence_seconds)
    for original, block in zip(blocks, validated):
        gate = np.asarray(original.get("gate_scores", block["long_scores"]), float)
        if gate.shape != block["long_scores"].shape:
            raise ValueError("gate_scores must have the same shape as long_scores")
        block["gate_scores"] = gate
    return validated


def predict(reference, long_scores, selected, gate_scores=None):
    """Use fixed selection and original availability; labels are never supplied."""
    reference = _ternary(reference, "reference")
    scores = np.asarray(long_scores, float)
    gate = scores if gate_scores is None else np.asarray(gate_scores, float)
    if scores.shape != reference.shape or gate.shape != reference.shape:
        raise ValueError("Long scores, gate scores and reference must have the same shape")
    low, high, policy = _validate_choice(selected)
    result = _latched_seed(reference, gate, low, policy)
    if high is not None:
        result[(reference >= 0) & _rescue_mask(scores, high, policy)] = 1
    return result


def calibrate(blocks, *, cadence_seconds=60):
    """Select only from supplied past blocks, returning (selected, all_trials).

    Every candidate must preserve all known-positive reference alarm rows,
    confirmed event identities and paired latency globally and in every block.
    Neither false-normal fragments nor false-normal duration may increase in
    any block, including short-exposure blocks. Evidence minima govern both
    optional paths; insufficient evidence always returns unchanged reference.
    """
    blocks = _validated_gate_blocks(blocks, cadence_seconds)
    labels = np.concatenate([b["labels"] for b in blocks])
    reference = np.concatenate([b["reference"] for b in blocks])
    scores = np.concatenate([b["long_scores"] for b in blocks])
    gate_scores = np.concatenate([b["gate_scores"] for b in blocks])
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
                "event_ownership": "original global primary onset; rescue uses first added positive row",
                "suppression_scores": "separate gate_scores; unknown preserves reference",
                "rescue_scores": "raw long_scores only",
                "rescue_known_normal_addition_limit": 0,
                "rescue_normal_reference": "pure gated seed in every block and globally"}
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
        rescue_added_normal_rows, rescue_added_normal_blocks = 0, []
        if choice["high_threshold"] is not None:
            seed = np.concatenate(seeds)
            added_normal = (labels == 0) & (prediction == 1) & (seed != 1)
            rescue_added_normal_rows = int(added_normal.sum())
            rescue_added_normal_blocks = [i for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])) if added_normal[a:b].any()]
            if rescue_added_normal_rows:
                reasons.append("rescue_added_known_normal_rows_global")
            if rescue_added_normal_blocks:
                reasons.append("rescue_added_known_normal_rows_in_block")
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
                  "rescue_coverage_event_ids": added_ids, "rescue_coverage_blocks": added_blocks,
                  "rescue_added_normal_rows": rescue_added_normal_rows,
                  "rescue_added_normal_blocks": rescue_added_normal_blocks}
        trials.append(result)

    assess(_choice(), [b["reference"] for b in blocks])
    if enough_events and enough_exposure:
        lows = [None] + _grid(gate_scores[reference == 1], np.linspace(0, 1, 21))
        highs = [None] + _grid(scores, np.linspace(.90, 1, 41), above_max=True)
        for policy in POLICIES:
            rescue_cache = {high: [_rescue_mask(b["long_scores"], high, policy) for b in blocks]
                            for high in highs if high is not None}
            for low in lows:
                seeds = [_latched_seed(b["reference"], b["gate_scores"], low, policy) for b in blocks]
                for high in highs:
                    if low is None and high is None:
                        continue
                    if low is not None and high is not None and low > high:
                        continue
                    assess(_choice(low, high, policy), seeds, rescue_cache.get(high))
    selected = min((t for t in trials if t["feasible"]), key=_rank)
    predictions = [predict(b["reference"], b["long_scores"], selected, gate_scores=b["gate_scores"]) for b in blocks]
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
