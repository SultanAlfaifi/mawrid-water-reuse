# Source adapter: only label validation/accounting differs from latched_suppression.
# Unknown labels stay on the original timeline; no sensor prediction is masked.
# Primary onset censoring is declared in unknown_label_metrics, before data use.
"""Past-only calibration of an onset-latched gate, with explicit baseline fallback.

blocks are dicts containing labels, scores (shape or another predeclared score),
baseline_predictions, source_start, and optional block_id. They must be adjacent
on one acquisition axis. No source is read by calibrate/predict. Binary labels
cannot establish physical fault-type coverage; representation flags say so.
"""
from __future__ import annotations

from pathlib import Path
import json
import numpy as np

POLICIES = {"instant": (1, 1), "2of3": (2, 3), "3of5": (3, 5)}


def _spans(labels):
    changes=np.diff(np.r_[False,labels,False].astype(np.int8))
    return np.flatnonzero(changes==1),np.flatnonzero(changes==-1)


def _gate(scores, threshold, policy):
    scores=np.asarray(scores,float)
    m,n=POLICIES[policy];result=np.full(len(scores),-1,dtype=np.int8)
    if len(scores)<n:return result
    finite=np.isfinite(scores)
    available=np.convolve(finite.astype(int),np.ones(n,int),mode="valid")==n
    votes=np.convolve((finite & (scores>=threshold)).astype(int),np.ones(n,int),mode="valid")
    result[np.arange(n-1,len(scores))[available]]=(votes[available]>=m).astype(np.int8)
    return result


def predict(scores, baseline_predictions, selected):
    """Never hide a baseline-observed row; unknown gate retains its baseline.

    selected.decision='baseline' returns the reference unchanged. Candidate
    threshold/policy are fixed by past calibration. No current/future labels.
    """
    scores=np.asarray(scores,float);base=np.asarray(baseline_predictions)
    if scores.ndim!=1 or base.shape!=scores.shape or base.dtype.kind not in "biu" or not np.isin(base,[-1,0,1]).all():
        raise ValueError("Scores and {-1,0,1} baseline must have equal one-dimensional shape")
    base=base.astype(np.int8,copy=True)
    if selected["decision"]=="baseline":return base
    if selected["decision"]!="candidate":raise ValueError("Unknown calibration decision")
    threshold=float(selected["threshold"])
    if not np.isfinite(threshold):raise ValueError("Threshold must be finite")
    gate=_gate(scores,threshold,selected["policy"])
    base[(base==1)&(gate==0)]=0
    # Once retained, an existing baseline alarm remains on until baseline clears.
    # This prevents pointwise suppression from splitting a false-alarm run.
    # Suppressed starts may reopen when contemporaneous evidence warrants it.
    index=np.arange(len(base))
    original=np.asarray(baseline_predictions)
    last_reset=np.maximum.accumulate(np.where(original!=1,index,-1))
    last_keep=np.maximum.accumulate(np.where((original==1)&(base==1),index,-1))
    base[(original==1)&(last_keep>last_reset)]=1
    return base


from unknown_label_metrics import _stats,_comparison


def _validated(blocks):
    if not blocks:raise ValueError("At least one calibration block is required")
    result=[];next_start=None
    for i,block in enumerate(blocks):
        y=np.asarray(block["labels"]);s=np.asarray(block["scores"],float);b=np.asarray(block["baseline_predictions"])
        if y.ndim!=1 or len(y)==0 or s.shape!=y.shape or b.shape!=y.shape:
            raise ValueError("Calibration block arrays must have equal nonempty one-dimensional shape")
        if y.dtype.kind not in "biu" or b.dtype.kind not in "biu" or not np.isin(y,[-1,0,1]).all() or not np.isin(b,[-1,0,1]).all():
            raise ValueError("Use original ternary labels and {-1,0,1} baseline predictions")
        if not isinstance(block["source_start"],(int,np.integer)) or block["source_start"]<0:
            raise ValueError("source_start must be a nonnegative integer acquisition index")
        start=int(block["source_start"])
        if next_start is not None and start!=next_start:raise ValueError("Calibration blocks must be adjacent on the original source axis")
        next_start=start+len(y)
        result.append({"labels":y.astype(np.int8),"scores":s,"baseline_predictions":b.astype(np.int8),
                       "source_start":start,"block_id":str(block.get("block_id",i))})
    return result


def calibrate(blocks, *, cadence_seconds=60, min_normal_minutes_per_block=1440,
              min_observed_blocks=2, min_total_normal_minutes=5760,
              min_reference_events=5, min_eventful_blocks=2,
              policies=("instant","2of3","3of5")):
    """Return selected, trials, using only supplied past calibration blocks.

    Adequate exposure is measured from actually observed BASELINE normal time.
    Completely unobserved blocks stay in event denominators but do not pretend
    to establish a false-alarm constraint. Missing shape always retains baseline.
    Every baseline-detected original event must survive globally and per block.
    A gate must lower pooled false runs, without increasing them or alarm time in
    any exposure-qualified block. Otherwise the declared reference is retained.
    """
    if not np.isfinite(cadence_seconds) or cadence_seconds<=0:raise ValueError("Positive cadence_seconds required")
    if any(p not in POLICIES for p in policies):raise ValueError("Unknown alarm policy")
    if min_normal_minutes_per_block<=0 or min_observed_blocks<1 or min_total_normal_minutes<=0:
        raise ValueError("Positive observed-normal exposure requirements are mandatory")
    if min_reference_events<1 or min_eventful_blocks<1:raise ValueError("Positive event representation requirements are mandatory")
    blocks=_validated(blocks)
    labels=np.concatenate([b["labels"] for b in blocks]);base=np.concatenate([b["baseline_predictions"] for b in blocks])
    reference=_stats(labels,base,cadence_seconds)
    block_reference=[_stats(b["labels"],b["baseline_predictions"],cadence_seconds) for b in blocks]
    qualified=[i for i,r in enumerate(block_reference) if r["normal_observed_seconds"]>=min_normal_minutes_per_block*60]
    eventful=sum(r["confirmed_events"]>0 for r in block_reference)
    representation=[]
    if reference["confirmed_events"]<min_reference_events:representation.append("few_reference_detected_events")
    if eventful<min_eventful_blocks:representation.append("events_concentrated_in_too_few_blocks")
    evidence={"cadence_seconds":cadence_seconds,"normal_exposure_required_seconds_per_block":min_normal_minutes_per_block*60,
              "min_observed_blocks":min_observed_blocks,"minimum_total_normal_seconds":min_total_normal_minutes*60,
              "qualified_block_ids":[blocks[i]["block_id"] for i in qualified],
              "unobserved_block_ids":[blocks[i]["block_id"] for i,r in enumerate(block_reference) if not r["normal_observed_seconds"]],
              "short_exposure_block_ids":[blocks[i]["block_id"] for i,r in enumerate(block_reference) if 0<r["normal_observed_seconds"]<min_normal_minutes_per_block*60],
              "reference":reference,"block_reference":block_reference,"representation_flags":representation,
              "min_reference_events":min_reference_events,"min_eventful_blocks":min_eventful_blocks,
              "fault_type_support":"Unknown: binary EVENT labels provide no physical fault-type taxonomy",
              "source_range":[blocks[0]["source_start"],blocks[-1]["source_start"]+len(blocks[-1]["labels"])]}
    fallback={"decision":"baseline","threshold":None,"policy":None,"mode":"gated_baseline","evidence":evidence}
    exposure=sum(block_reference[i]["normal_observed_seconds"] for i in qualified)
    if len(qualified)<min_observed_blocks or exposure<min_total_normal_minutes*60:
        return {**fallback,"status":"insufficient_observed_normal_exposure"},[]
    if representation:return {**fallback,"status":"insufficient_event_representation"},[]
    all_scores=np.concatenate([b["scores"] for b in blocks]);finite=all_scores[np.isfinite(all_scores)]
    if not len(finite):return {**fallback,"status":"shape_unavailable_baseline_retained"},[]
    thresholds=np.unique(np.r_[np.quantile(finite,np.linspace(0,1,201)),np.nextafter(finite.max(),np.inf)])
    trials=[]
    for policy in policies:
        for threshold in thresholds:
            choice={"decision":"candidate","threshold":float(threshold),"policy":policy}
            preds=[predict(b["scores"],b["baseline_predictions"],choice) for b in blocks]
            pooled=_comparison(labels,base,np.concatenate(preds),cadence_seconds)
            per_block=[_comparison(b["labels"],b["baseline_predictions"],p,cadence_seconds) for b,p in zip(blocks,preds)]
            retained=not pooled["lost_baseline_event_ids"] and all(not p["lost_baseline_event_ids"] for p in per_block)
            no_hide=pooled["hidden_baseline_rows"]==0
            noninferior=all(per_block[i]["candidate"]["false_runs_per_day"]<=per_block[i]["baseline"]["false_runs_per_day"]
                and per_block[i]["candidate"]["normal_alarm_fraction"]<=per_block[i]["baseline"]["normal_alarm_fraction"]
                and per_block[i]["candidate"]["fp"]<=per_block[i]["baseline"]["fp"] for i in qualified)
            bm,cm=pooled["baseline"],pooled["candidate"]
            improved=cm["false_runs_per_day"]<bm["false_runs_per_day"] and cm["fp"]<=bm["fp"]
            extra=[x["extra_delay_seconds"] for x in pooled["paired_extra_delays"]]
            trials.append({"threshold":float(threshold),"policy":policy,"feasible":bool(retained and no_hide and noninferior and improved),
                           "retains_all_baseline_events":retained,"lost_baseline_event_ids":pooled["lost_baseline_event_ids"],
                           "hidden_baseline_rows":pooled["hidden_baseline_rows"],"qualified_blocks_noninferior":bool(noninferior),
                           "strict_pooled_false_runs_reduction":bool(improved),"candidate_confirmed_events":cm["confirmed_events"],
                           "candidate_false_runs_per_day":cm["false_runs_per_day"],"candidate_fp":cm["fp"],
                           "candidate_fp_duration_seconds":cm["fp_duration_seconds"],"candidate_normal_alarm_fraction":cm["normal_alarm_fraction"],
                           "max_extra_delay_seconds":max(extra) if extra else None,"mean_extra_delay_seconds":float(np.mean(extra)) if extra else None,
                           "per_block_lost_counts":[len(p["lost_baseline_event_ids"]) for p in per_block]})
    choices=[r for r in trials if r["feasible"]]
    if not choices:return {**fallback,"status":"no_sensitivity_preserving_false_alarm_improvement"},trials
    selected=min(choices,key=lambda r:(r["candidate_false_runs_per_day"],r["candidate_fp"],r["max_extra_delay_seconds"] or 0,
                                      -r["candidate_confirmed_events"],-r["threshold"],r["policy"]!="instant"))
    selected={**selected,"decision":"candidate","status":"sensitivity_preserving_gate_selected","mode":"gated_baseline","evidence":evidence}
    predictions=np.concatenate([predict(b["scores"],b["baseline_predictions"],selected) for b in blocks])
    selected["calibration_comparison"]=_comparison(labels,base,predictions,cadence_seconds)
    return selected,trials

