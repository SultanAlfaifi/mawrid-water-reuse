"""V5 acceptance accounting; original event identities and availability retained.

This module does not select a model, a threshold, or an evaluation source.
Common-availability summaries are diagnostic. Release gates use native outputs
and explicitly prohibit hiding baseline-observed rows by abstaining.
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml/gecco_baseline"))
from metrics import evaluate


def evaluate_at_cadence(labels, prediction, sample_seconds=60):
    """Convert the original minute-based accounting for a fixed regular cadence.

    Irregular observations must first be represented on an explicit regular
    axis, with absent observations unavailable. Index boundaries stay in rows.
    """
    if not np.isfinite(sample_seconds) or sample_seconds <= 0:
        raise ValueError("sample_seconds must be finite and positive")
    m = evaluate(labels, prediction)
    factor = float(sample_seconds) / 60
    m['sample_seconds'] = float(sample_seconds)
    m['eligible_normal_days'] *= factor
    m['normal_alarm_minutes'] = m['fp'] * factor
    if m['false_alarm_runs_per_normal_day'] is not None:
        m['false_alarm_runs_per_normal_day'] /= factor
    for key in ('median_detection_delay_minutes', 'p95_detection_delay_minutes'):
        if m[key] is not None:m[key] *= factor
    for record in m['event_records']:
        for key in ('duration_minutes', 'detection_delay_minutes', 'new_alarm_delay_minutes', 'confirmed_new_alarm_delay_minutes'):
            if record[key] is not None:record[key] *= factor
    for record in m['false_alarm_records']:record['duration_minutes'] *= factor
    return m


def compare_period(labels, baseline_prediction, candidate_prediction, sample_seconds=60):
    baseline = np.asarray(baseline_prediction)
    candidate = np.asarray(candidate_prediction)
    # evaluate validates length, integer semantics and labels before comparisons.
    b = evaluate_at_cadence(labels, baseline, sample_seconds)
    c = evaluate_at_cadence(labels, candidate, sample_seconds)
    lost, gained, delays = [], [], []
    for left, right in zip(b["event_records"], c["event_records"]):
        assert (left["start"], left["end"]) == (right["start"], right["end"])
        lb = left["confirmed_new_alarm_inside_event"]
        rc = right["confirmed_new_alarm_inside_event"]
        identity = {"event_id": left["event_id"], "start": left["start"], "end": left["end"]}
        if lb and not rc:
            lost.append(identity)
        if rc and not lb:
            gained.append(identity)
        if lb and rc:
            delays.append({**identity,
                "baseline_delay_minutes": left["confirmed_new_alarm_delay_minutes"],
                "candidate_delay_minutes": right["confirmed_new_alarm_delay_minutes"],
                "extra_delay_minutes": right["confirmed_new_alarm_delay_minutes"] - left["confirmed_new_alarm_delay_minutes"]})
    hidden = int(np.count_nonzero((baseline >= 0) & (candidate < 0)))
    common = (baseline >= 0) & (candidate >= 0)
    measurable = all(m[k] is not None for m in (b, c) for k in
                     ("false_alarm_runs_per_normal_day", "normal_time_under_alarm"))
    noninferior = bool(measurable and not lost and hidden == 0 and
        c["false_alarm_runs_per_normal_day"] <= b["false_alarm_runs_per_normal_day"] and
        c["normal_time_under_alarm"] <= b["normal_time_under_alarm"] and
        c["fp"] <= b["fp"])
    return {"baseline": b, "candidate": c,
        "common": {"baseline": evaluate_at_cadence(labels, np.where(common, baseline, -1), sample_seconds),
                   "candidate": evaluate_at_cadence(labels, np.where(common, candidate, -1), sample_seconds)},
        "lost_baseline_events": lost, "newly_detected_events": gained,
        "paired_detection_delays": delays,
        "baseline_observed_rows_hidden_by_candidate": hidden,
        "normal_exposure_measurable": measurable,
        "noninferior": noninferior}


def gates(periods, pooled_sources=None):
    """Gate periods and aggregate independently evaluated continuous sources.

    Adjacent periods from the same stream must be supplied through
    assess_series (or pooled_sources) so an event crossing a period boundary is
    counted once in totals. Without pooled_sources, periods must be independent
    sources, not adjacent slices of one source.
    """
    if not periods:
        raise ValueError("At least one test period is required")
    pooled_sources = periods if pooled_sources is None else pooled_sources
    if not pooled_sources:raise ValueError('At least one pooled source is required')
    totals = {}
    for name in ("baseline", "candidate"):
        counts = {key: sum(p[name][key] for p in pooled_sources) for key in
            ("sample_count", "valid_count", "true_events", "confirmed_new_alarm_inside_events",
             "false_positive_runs", "normal_valid_count", "tp", "fp", "fn", "tn",
             "eligible_normal_days", "normal_alarm_minutes")}
        normal = counts["normal_valid_count"]
        denom = 2 * counts["tp"] + counts["fp"] + counts["fn"]
        days = counts['eligible_normal_days']
        counts["false_alarm_runs_per_normal_day"] = counts["false_positive_runs"] / days if days else None
        counts["normal_time_under_alarm"] = counts["normal_alarm_minutes"] / (days * 1440) if days else None
        counts["f1"] = 2 * counts["tp"] / denom if denom else None
        totals[name] = counts
    b, c = totals["baseline"], totals["candidate"]
    lost = sum(len(p["lost_baseline_events"]) for p in pooled_sources)
    hidden = sum(p["baseline_observed_rows_hidden_by_candidate"] for p in pooled_sources)
    measurable = all(p["normal_exposure_measurable"] for p in periods)
    joint = bool(measurable and lost == 0 and hidden == 0 and
        c["false_alarm_runs_per_normal_day"] < b["false_alarm_runs_per_normal_day"] and
        c["normal_time_under_alarm"] <= b["normal_time_under_alarm"] and c["fp"] <= b["fp"])
    return {"totals": totals, "lost_baseline_events": lost,
        "hidden_baseline_observed_rows": hidden,
        "noninferior_periods": [p["noninferior"] for p in periods],
        "pooled_joint_improvement": joint,
        "stable_joint_improvement": joint and all(p["noninferior"] for p in periods),
        "period_event_occurrences": sum(p['baseline']['true_events'] for p in periods),
        "scope": "Observed test periods only; totals count events on each original continuous source axis. No guarantee for future sites or event types"}


def assess_series(labels, baseline_prediction, candidate_prediction, boundaries, sample_seconds=60):
    """Evaluate one contiguous source and fixed period boundaries on its axis."""
    y = np.asarray(labels);b = np.asarray(baseline_prediction);c = np.asarray(candidate_prediction)
    bounds = np.asarray(boundaries)
    if bounds.ndim != 1 or bounds.dtype.kind not in 'iu' or len(bounds) < 2:
        raise ValueError('boundaries must be a 1D sequence of at least two integer row indices')
    if bounds[0] != 0 or bounds[-1] != len(y) or np.any(np.diff(bounds) <= 0):
        raise ValueError('boundaries must cover the entire source exactly once in increasing order')
    whole = compare_period(y,b,c,sample_seconds)
    periods = [compare_period(y[left:right],b[left:right],c[left:right],sample_seconds)
               for left,right in zip(bounds[:-1],bounds[1:])]
    return {'pooled':whole,'periods':periods,'gates':gates(periods,[whole])}
