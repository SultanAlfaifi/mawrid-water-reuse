"""Observed-row event identities with explicit regular-grid slot geometry.

Inputs contain original observations only. A missing time interval cannot
confirm a0->1 transition or join false-alarm runs. Event labels retain their
original observed-row runs; no false labels are invented inside time gaps.
"""
from __future__ import annotations
import numpy as np
from evaluation import evaluate_at_cadence, gates


def _slots(values, n):
    s = np.asarray(values)
    if s.shape != (n,) or s.dtype.kind not in "iu" or (n > 1 and np.any(np.diff(s) <= 0)):
        raise ValueError("slots must be same-length strictly increasing integer indices")
    return s


def _runs(mask, adjacent):
    start = np.flatnonzero(mask & ~np.r_[False, mask[:-1] & adjacent[1:]])
    end = np.flatnonzero(mask & ~np.r_[mask[1:] & adjacent[1:], False]) + 1
    return list(zip(start, end)) if len(mask) else []


def evaluate_sparse(labels, predictions, slots, sample_seconds=900):
    """Full metric schema compatible with evaluate_at_cadence.

    Exposure and alarm duration count observed eligible samples, not elapsed
    gap time. Detection latency uses actual slot distance. Event duration is
    observed labeled time; sparse event records additionally expose elapsed
    span and missing slots. Boundary-complete recalls retain their original
    boundary-only definition; time-gap censoring is reported separately.
    """
    y = np.asarray(labels); p = np.asarray(predictions); s = _slots(slots, len(y))
    m = evaluate_at_cadence(y, p, sample_seconds)
    if len(s) < 2 or np.all(np.diff(s) == 1):
        return m  # Exact existing schema/value parity on contiguous inputs.
    y = y.astype(bool); factor = float(sample_seconds) / 60
    adjacent = np.r_[False, np.diff(s) == 1]
    alarm = p == 1
    raw_start = alarm & ~np.r_[False, (p[:-1] == 1) & adjacent[1:]]
    confirmed = alarm & np.r_[False, (p[:-1] == 0) & adjacent[1:]]
    false = alarm & ~y
    m["false_alarm_records"] = [{"start":int(a), "end":int(b), "duration_minutes":(b-a)*factor}
                                for a,b in _runs(false, adjacent)]
    m["false_positive_runs"] = len(m["false_alarm_records"])
    m["false_alarm_runs_per_normal_day"] = m["false_positive_runs"] / m["eligible_normal_days"] if m["eligible_normal_days"] else None
    m["alarm_runs"] = len(_runs(alarm, adjacent))
    coverage_delays = []
    for r in m["event_records"]:
        a,b = r["start"],r["end"]
        r["elapsed_span_minutes"] = int(s[b-1]-s[a]+1)*factor
        r["missing_slots_inside_event"] = int(s[b-1]-s[a]+1-(b-a))
        r["time_gap_censored"] = r["missing_slots_inside_event"] > 0
        for mask, present, index_name, delay_name in [
            (alarm,"detected","first_alarm_index","detection_delay_minutes"),
            (raw_start,"new_alarm_inside_event","new_alarm_start_index","new_alarm_delay_minutes"),
            (confirmed,"confirmed_new_alarm_inside_event","confirmed_new_alarm_index","confirmed_new_alarm_delay_minutes"),
        ]:
            hits = np.flatnonzero(mask[a:b]); index = int(a+hits[0]) if len(hits) else None
            r[present] = index is not None; r[index_name] = index
            r[delay_name] = int(s[index]-s[a])*factor if index is not None else None
        index = r["new_alarm_start_index"]
        unavailable = bool(index is not None and index > 0 and (not adjacent[index] or p[index-1] == -1))
        r["new_alarm_previous_unavailable"] = unavailable
        r["new_alarm_previous_unknown"] = index == 0 or unavailable
        r["alarm_started_at_onset"] = bool(raw_start[a])
        if r["detection_delay_minutes"] is not None:coverage_delays.append(r["detection_delay_minutes"])
    records = m["event_records"]; total = len(records)
    new = sum(r["new_alarm_inside_event"] for r in records)
    confirmed_count = sum(r["confirmed_new_alarm_inside_event"] for r in records)
    complete = [r for r in records if not r["boundary_censored"]]
    complete_new = sum(r["new_alarm_inside_event"] for r in complete)
    complete_confirmed = sum(r["confirmed_new_alarm_inside_event"] for r in complete)
    for name in ("new_alarm_inside_events","raw_new_alarm_inside_events"):m[name] = new
    for name in ("new_alarm_inside_event_recall","raw_new_alarm_inside_event_recall"):m[name] = new/total if total else None
    m["confirmed_new_alarm_inside_events"] = confirmed_count
    m["confirmed_new_alarm_inside_event_recall"] = confirmed_count/total if total else None
    m["complete_new_alarm_inside_events"] = complete_new
    m["complete_confirmed_new_alarm_inside_events"] = complete_confirmed
    for name in ("complete_event_new_alarm_start_recall","complete_raw_new_alarm_start_recall"):
        m[name] = complete_new/len(complete) if complete else None
    m["complete_confirmed_new_alarm_start_recall"] = complete_confirmed/len(complete) if complete else None
    m["median_detection_delay_minutes"] = float(np.median(coverage_delays)) if coverage_delays else None
    m["p95_detection_delay_minutes"] = float(np.percentile(coverage_delays,95)) if coverage_delays else None
    return m


def compare_sparse(labels, baseline_prediction, candidate_prediction, slots, sample_seconds=900):
    b = np.asarray(baseline_prediction); c = np.asarray(candidate_prediction)
    bm = evaluate_sparse(labels,b,slots,sample_seconds); cm = evaluate_sparse(labels,c,slots,sample_seconds)
    lost=[]; gained=[]; delays=[]
    for left,right in zip(bm["event_records"],cm["event_records"]):
        assert (left["start"],left["end"]) == (right["start"],right["end"])
        identity={"event_id":left["event_id"],"start":left["start"],"end":left["end"]}
        lb=left["confirmed_new_alarm_inside_event"]; rc=right["confirmed_new_alarm_inside_event"]
        if lb and not rc:lost.append(identity)
        if rc and not lb:gained.append(identity)
        if lb and rc:
            delays.append({**identity,"baseline_delay_minutes":left["confirmed_new_alarm_delay_minutes"],
                "candidate_delay_minutes":right["confirmed_new_alarm_delay_minutes"],
                "extra_delay_minutes":right["confirmed_new_alarm_delay_minutes"]-left["confirmed_new_alarm_delay_minutes"]})
    hidden=int(((b>=0)&(c<0)).sum()); common=(b>=0)&(c>=0)
    measurable=all(m[k] is not None for m in (bm,cm) for k in ("false_alarm_runs_per_normal_day","normal_time_under_alarm"))
    noninferior=bool(measurable and not lost and hidden==0 and cm["false_alarm_runs_per_normal_day"]<=bm["false_alarm_runs_per_normal_day"]
                     and cm["normal_time_under_alarm"]<=bm["normal_time_under_alarm"] and cm["fp"]<=bm["fp"])
    return {"baseline":bm,"candidate":cm,
        "common":{"baseline":evaluate_sparse(labels,np.where(common,b,-1),slots,sample_seconds),
                  "candidate":evaluate_sparse(labels,np.where(common,c,-1),slots,sample_seconds)},
        "lost_baseline_events":lost,"newly_detected_events":gained,"paired_detection_delays":delays,
        "baseline_observed_rows_hidden_by_candidate":hidden,"normal_exposure_measurable":measurable,"noninferior":noninferior}


def assess_sparse_series(labels, baseline_prediction, candidate_prediction, slots, boundaries, sample_seconds=900):
    y=np.asarray(labels);b=np.asarray(baseline_prediction);c=np.asarray(candidate_prediction);s=_slots(slots,len(y));bounds=np.asarray(boundaries)
    if bounds.ndim!=1 or bounds.dtype.kind not in "iu" or len(bounds)<2 or bounds[0]!=0 or bounds[-1]!=len(y) or np.any(np.diff(bounds)<=0):
        raise ValueError("boundaries must cover observed rows exactly once in increasing integer order")
    whole=compare_sparse(y,b,c,s,sample_seconds)
    periods=[compare_sparse(y[a:z],b[a:z],c[a:z],s[a:z],sample_seconds) for a,z in zip(bounds[:-1],bounds[1:])]
    return {"pooled":whole,"periods":periods,"gates":gates(periods,[whole])}
