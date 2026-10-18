"""Select on two past blocks, then veto a frozen policy on two later blocks.

This is a temporal check of the incremental policy conditional on frozen V6.
V6 itself was calibrated on all four blocks, so the later pair is not an
independent holdout for the whole pipeline. Certification never chooses a
different candidate: any failure returns the unchanged reference. No source IO.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np

from ml.gecco_v7 import calibration_delayed as delayed
from ml.gecco_v7.calibration import (
    MIN_EVENTS, MIN_EVENTFUL_BLOCKS, MIN_NORMAL_MINUTES_PER_BLOCK,
    MIN_TOTAL_NORMAL_MINUTES, MIN_OBSERVED_BLOCKS, MIN_RESCUE_EVENTS,
    MIN_RESCUE_EVENTFUL_BLOCKS, full_stats,
)

# Inference is unchanged. Labels are accepted only by the calibration wrapper.
predict = delayed.predict


def _fixed_choice(selected):
    low, high, policy, samples = delayed._validate_choice(selected)
    return delayed._choice(low, high, policy, samples, selected.get("cadence_seconds", 60))


def _predict_blocks(blocks, selected):
    return [predict(b["reference"], b["long_scores"], selected, b["rescue_scores"]) for b in blocks]


def _assessment(blocks, predictions, cadence_seconds):
    """Original-axis event identities and latency, on the pool and every block."""
    parts = [(b["labels"], b["reference"], p) for b, p in zip(blocks, predictions)]
    pooled = tuple(np.concatenate([part[i] for part in parts]) for i in range(3))
    scopes = []
    reasons = []
    for index, (labels, reference, candidate) in enumerate([pooled] + parts):
        before = full_stats(labels, reference, cadence_seconds)
        after = full_stats(labels, candidate, cadence_seconds)
        bt = dict(zip(before["confirmed_event_ids"], before["confirmed_times"]))
        ct = dict(zip(after["confirmed_event_ids"], after["confirmed_times"]))
        lost = sorted(set(bt) - set(ct))
        paired = [{"event_id": i, "extra_delay_seconds": float((ct[i] - t) * cadence_seconds)}
                  for i, t in bt.items() if i in ct]
        late = [d["event_id"] for d in paired if d["extra_delay_seconds"] > 120]
        checks = {
            "reference_event_ids_retained": not lost,
            "paired_event_delay_at_most_120_seconds": not late,
            "reference_availability_unchanged": bool(np.array_equal(reference >= 0, candidate >= 0)),
            "false_duration_not_increased": after["fp_duration_seconds"] <= before["fp_duration_seconds"],
            "false_fragments_not_increased": after["false_positive_runs"] <= before["false_positive_runs"],
        }
        scope = "pool" if index == 0 else f"block_{index - 1}"
        reasons.extend(f"{scope}:{key}" for key, passed in checks.items() if not passed)
        scopes.append({"scope": scope, "checks": checks,
                       "lost_reference_event_ids": lost, "over_budget_event_ids": late,
                       "paired_extra_delays": paired,
                       "max_paired_extra_delay_seconds": max((d["extra_delay_seconds"] for d in paired), default=None),
                       "lost_positive_alarm_rows": int(np.count_nonzero((labels == 1) & (reference == 1) & (candidate != 1))),
                       "reference_events": before["confirmed_events"], "candidate_events": after["confirmed_events"],
                       "reference_false_fragments": before["false_positive_runs"], "candidate_false_fragments": after["false_positive_runs"],
                       "reference_false_seconds": before["fp_duration_seconds"], "candidate_false_seconds": after["fp_duration_seconds"]})
    return {"passed": not reasons, "rejection_reasons": reasons, "scopes": scopes}


def _evidence(blocks, cadence_seconds):
    labels = np.concatenate([b["labels"] for b in blocks])
    reference = np.concatenate([b["reference"] for b in blocks])
    metrics = full_stats(labels, reference, cadence_seconds)
    parts = [full_stats(b["labels"], b["reference"], cadence_seconds) for b in blocks]
    bounds = np.r_[0, np.cumsum([len(b["labels"]) for b in blocks])]
    qualified = [i for i, m in enumerate(parts)
                 if m["normal_observed_seconds"] >= MIN_NORMAL_MINUTES_PER_BLOCK * 60]
    qualified_seconds = sum(parts[i]["normal_observed_seconds"] for i in qualified)
    eventful = sorted({int(np.searchsorted(bounds, event["start"], side="right") - 1)
                       for event in metrics["primary_event_intervals"]})
    return {"enough_observed_normal_exposure": len(qualified) >= MIN_OBSERVED_BLOCKS
                and qualified_seconds >= MIN_TOTAL_NORMAL_MINUTES * 60,
            "enough_primary_event_representation": metrics["true_events"] >= MIN_EVENTS
                and len(eventful) >= MIN_EVENTFUL_BLOCKS,
            "primary_events": metrics["true_events"], "eventful_blocks": eventful,
            "qualified_blocks": qualified, "qualified_normal_minutes": qualified_seconds / 60,
            "observed_normal_minutes_by_block": [m["normal_observed_seconds"] / 60 for m in parts],
            "min_events": MIN_EVENTS, "min_eventful_blocks": MIN_EVENTFUL_BLOCKS,
            "min_observed_blocks": MIN_OBSERVED_BLOCKS,
            "min_normal_minutes_per_block": MIN_NORMAL_MINUTES_PER_BLOCK,
            "min_total_normal_minutes": MIN_TOTAL_NORMAL_MINUTES,
            "source_range": [blocks[0]["source_start"], blocks[-1]["source_start"] + len(blocks[-1]["labels"])],
            "block_ids": [b["block_id"] for b in blocks]}


def _rescue_evidence(blocks, predictions, seeds, selected, cadence_seconds):
    labels = np.concatenate([b["labels"] for b in blocks])
    prediction = np.concatenate(predictions)
    seed = np.concatenate(seeds)
    bounds = np.r_[0, np.cumsum([len(b["labels"]) for b in blocks])]
    normal_additions = (labels == 0) & (prediction == 1) & (seed != 1)
    normal_by_block = [int(normal_additions[a:b].sum()) for a, b in zip(bounds[:-1], bounds[1:])]
    added = (labels == 1) & (prediction == 1) & (seed != 1)
    event_ids = []; first_blocks = []
    for event in full_stats(labels, seed, cadence_seconds)["primary_event_intervals"]:
        a, b = event["start"], event["end_exclusive"]
        positions = np.flatnonzero(added[a:b])
        if len(positions):
            event_ids.append(event["event_id"])
            first_blocks.append(int(np.searchsorted(bounds, a + positions[0], side="right") - 1))
    active = selected["high_threshold"] is not None
    checks = {
        "no_added_known_normal_rows_global": not normal_additions.any(),
        "no_added_known_normal_rows_in_any_block": not any(normal_by_block),
        "at_least_two_original_rescue_coverage_events": not active or len(event_ids) >= MIN_RESCUE_EVENTS,
        "rescue_first_additions_in_at_least_two_blocks": not active or len(set(first_blocks)) >= MIN_RESCUE_EVENTFUL_BLOCKS,
    }
    return {"active": active, "passed": all(checks.values()), "checks": checks,
            "rejection_reasons": [name for name, passed in checks.items() if not passed],
            "added_known_normal_rows": int(normal_additions.sum()), "added_known_normal_rows_by_block": normal_by_block,
            "coverage_event_ids": event_ids, "first_addition_blocks": sorted(set(first_blocks)),
            "event_ownership": "original primary onset; each event belongs to its first added positive row"}


def certify(selected, blocks, *, cadence_seconds=60):
    """Evaluate exactly two later blocks without choosing or altering a policy."""
    if len(blocks) != 2:
        raise ValueError("Certification requires exactly two later blocks")
    blocks = delayed._validated_rescue_blocks(blocks, cadence_seconds)
    selected = _fixed_choice(selected)
    if selected["cadence_seconds"] != cadence_seconds:
        raise ValueError("Policy cadence and certification cadence disagree")
    seed_choice = delayed._choice(selected["low_threshold"], None, "instant",
                                  selected["confirmation_samples"], cadence_seconds)
    predictions = _predict_blocks(blocks, selected)
    seeds = _predict_blocks(blocks, seed_choice)
    evidence = _evidence(blocks, cadence_seconds)
    candidate = _assessment(blocks, predictions, cadence_seconds)
    seed = _assessment(blocks, seeds, cadence_seconds)
    rescue = _rescue_evidence(blocks, predictions, seeds, selected, cadence_seconds)
    checks = {
        "adequate_observed_normal_exposure": evidence["enough_observed_normal_exposure"],
        "adequate_primary_event_representation": evidence["enough_primary_event_representation"],
        "candidate_preserves_reference_constraints": candidate["passed"],
        "pure_confirmation_seed_preserves_reference_constraints": seed["passed"],
        "rescue_has_independent_coverage_without_normal_additions": rescue["passed"],
    }
    reasons = [key for key, passed in checks.items() if not passed]
    reasons += ["candidate:" + r for r in candidate["rejection_reasons"]]
    reasons += ["pure_seed:" + r for r in seed["rejection_reasons"]]
    reasons += ["rescue:" + r for r in rescue["rejection_reasons"]]
    return {"passed": all(checks.values()), "checks": checks, "rejection_reasons": reasons,
            "fixed_choice": selected, "evidence": evidence, "candidate": candidate,
            "pure_confirmation_seed": seed, "rescue": rescue,
            "interpretation": "temporal veto of incremental policy conditional on V6 calibrated using all four blocks; not an independent pipeline holdout"}


def calibrate(blocks, *, cadence_seconds=60):
    """Choose once on first two blocks; later two and global veto can only reject."""
    if len(blocks) != 4:
        raise ValueError("Exactly four adjacent past blocks are required")
    blocks = delayed._validated_rescue_blocks(blocks, cadence_seconds)
    earlier_selected, earlier_trials = delayed.calibrate(blocks[:2], cadence_seconds=cadence_seconds)
    # A detached snapshot prevents certification or final metadata from changing
    # the chosen operating point or the earlier selection evidence.
    earlier_selected = deepcopy(earlier_selected)
    proposed = _fixed_choice(earlier_selected)
    certificate = certify(proposed, blocks[2:], cadence_seconds=cadence_seconds)
    proposed_predictions = _predict_blocks(blocks, proposed)
    seed_choice = delayed._choice(proposed["low_threshold"], None, "instant",
                                  proposed["confirmation_samples"], cadence_seconds)
    seeds = _predict_blocks(blocks, seed_choice)
    veto = {
        "earlier_pure_confirmation_seed": _assessment(blocks[:2], seeds[:2], cadence_seconds),
        "all_four_pure_confirmation_seed": _assessment(blocks, seeds, cadence_seconds),
        "all_four_candidate": _assessment(blocks, proposed_predictions, cadence_seconds),
    }
    veto_reasons = [name + ":" + reason for name, assessed in veto.items()
                    for reason in assessed["rejection_reasons"]]
    accepted = certificate["passed"] and not veto_reasons
    final = proposed if accepted else delayed._choice(cadence_seconds=cadence_seconds)
    if proposed["decision"] == "reference":
        status = "earlier_reference_retained"
    elif accepted:
        status = "temporally_certified_confirmation_policy_selected"
    else:
        status = "certification_failed_reference_retained"
    predictions = _predict_blocks(blocks, final)
    labels = np.concatenate([b["labels"] for b in blocks])
    prediction = np.concatenate(predictions)
    final_metrics = full_stats(labels, prediction, cadence_seconds)
    final_assessment = _assessment(blocks, predictions, cadence_seconds)
    all_reasons = certificate["rejection_reasons"] + veto_reasons
    trials = [{**deepcopy(t), "stage": "earlier_selection"} for t in earlier_trials]
    trials.append({**proposed, "stage": "later_certification_and_global_veto",
                   "feasible": bool(accepted), "rejection_reasons": all_reasons})
    return {**final, "status": status, "earlier_selected": earlier_selected,
            "certification": certificate, "global_veto": veto,
            "certification_passed": bool(accepted), "certification_rejection_reasons": all_reasons,
            "final_selected": deepcopy(final), "selection_blocks": [b["block_id"] for b in blocks[:2]],
            "certification_blocks": [b["block_id"] for b in blocks[2:]],
            "evidence": {"earlier_selection": earlier_selected["evidence"], "later_certification": certificate["evidence"]},
            "calibration_metrics": final_metrics,
            "calibration_block_metrics": [full_stats(b["labels"], p, cadence_seconds) for b, p in zip(blocks, predictions)],
            "calibration_paired_delays": final_assessment["scopes"][0]["paired_extra_delays"],
            "lost_positive_alarm_rows": final_assessment["scopes"][0]["lost_positive_alarm_rows"],
            "max_paired_extra_delay_seconds": max((s["max_paired_extra_delay_seconds"] for s in final_assessment["scopes"]
                if s["max_paired_extra_delay_seconds"] is not None), default=None),
            "trial_count": len(trials), "selection_trial_count": len(earlier_trials), "certification_attempts": 1,
            "events": final_metrics["confirmed_events"], "tp": final_metrics["tp"],
            "fp": final_metrics["fp"], "false_runs": final_metrics["false_positive_runs"]}, trials
