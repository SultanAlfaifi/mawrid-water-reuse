"""Calibration on original observed event IDs, with full-grid causal decisions.

blocks contain full-grid labels/scores/baseline_predictions, observed, slots,
source_start, and optional block_id. Every grid slot must remain represented.
Inserted slots have observedFalse, scoresNaN and baseline-1. Their labels are
placeholders and never enter evaluation. No dataset is read by this module.
"""
from __future__ import annotations
import numpy as np
from calibration import POLICIES, predict, _validated, _spans


def _validated_sparse(blocks):
    normalized=_validated(blocks)
    previous_slot=None
    for raw,b in zip(blocks,normalized):
        observed=np.asarray(raw["observed"]);slots=np.asarray(raw["slots"])
        if observed.shape!=b["labels"].shape or observed.dtype.kind not in "biu" or not np.isin(observed,[0,1]).all():
            raise ValueError("observed must be a same-length Boolean/binary integer mask")
        if slots.shape!=observed.shape or slots.dtype.kind not in "iu" or np.any(np.diff(slots)!=1):
            raise ValueError("slots must contain the full consecutive integer regular grid")
        if previous_slot is not None and slots[0]!=previous_slot+1:
            raise ValueError("Calibration slots must be contiguous across blocks")
        observed=observed.astype(bool)
        if np.any(np.isfinite(b["scores"][~observed])) or np.any(b["baseline_predictions"][~observed]!=-1):
            raise ValueError("Inserted slots require unavailable scores and baseline predictions")
        b.update({"observed":observed,"slots":slots});previous_slot=int(slots[-1])
    return normalized


def _stats(labels,predictions,slots,cadence_seconds=900):
    y=np.asarray(labels,bool);p=np.asarray(predictions,int);s=np.asarray(slots)
    adjacent=np.r_[False,np.diff(s)==1] if len(s) else np.zeros(0,bool)
    confirmed=(p==1)&np.r_[False,p[:-1]==0]&adjacent if len(p) else np.zeros(0,bool)
    starts,ends=_spans(y);found=[];times=[]
    for event_id,(a,b) in enumerate(zip(starts,ends),1):
        hit=np.flatnonzero(confirmed[a:b])
        if len(hit):found.append(event_id);times.append(int(s[a+hit[0]]-s[0]))
    alarm=p==1;false=(~y)&alarm
    fp=int(false.sum());tn=int(((~y)&(p==0)).sum())
    runs=int((false&~np.r_[False,false[:-1]&adjacent[1:]]).sum()) if len(false) else 0
    seconds=(fp+tn)*cadence_seconds
    return {"true_events":len(starts),"confirmed_event_ids":found,"confirmed_times":times,
            "confirmed_events":len(found),"tp":int((y&alarm).sum()),"fp":fp,"fn":int((y&(p==0)).sum()),"tn":tn,
            "false_positive_runs":runs,"normal_observed_seconds":seconds,
            "false_runs_per_day":runs*86400/seconds if seconds else None,
            "normal_alarm_fraction":fp/(fp+tn) if fp+tn else None,"fp_duration_seconds":fp*cadence_seconds,
            "available_rows":int((p>=0).sum())}


def _comparison(labels,base,prediction,slots,cadence):
    b=_stats(labels,base,slots,cadence);c=_stats(labels,prediction,slots,cadence)
    lost=sorted(set(b["confirmed_event_ids"])-set(c["confirmed_event_ids"]))
    bt=dict(zip(b["confirmed_event_ids"],b["confirmed_times"]));ct=dict(zip(c["confirmed_event_ids"],c["confirmed_times"]))
    delays=[{"event_id":i,"extra_delay_seconds":(ct[i]-bt[i])*cadence} for i in bt if i in ct]
    return {"baseline":b,"candidate":c,"lost_baseline_event_ids":lost,
            "hidden_baseline_rows":int(((np.asarray(base)>=0)&(np.asarray(prediction)<0)).sum()),"paired_extra_delays":delays}


def calibrate_sparse(blocks, *, cadence_seconds=900, min_normal_minutes_per_block=1440,
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
    blocks=_validated_sparse(blocks)
    views=[{"labels":b["labels"][b["observed"]],"baseline_predictions":b["baseline_predictions"][b["observed"]],"slots":b["slots"][b["observed"]]} for b in blocks]
    labels=np.concatenate([b["labels"] for b in views]);base=np.concatenate([b["baseline_predictions"] for b in views]);slots=np.concatenate([b["slots"] for b in views])
    reference=_stats(labels,base,slots,cadence_seconds)
    block_reference=[_stats(b["labels"],b["baseline_predictions"],b["slots"],cadence_seconds) for b in views]
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
            preds=[predict(b["scores"],b["baseline_predictions"],choice)[b["observed"]] for b in blocks]
            pooled=_comparison(labels,base,np.concatenate(preds),slots,cadence_seconds)
            per_block=[_comparison(b["labels"],b["baseline_predictions"],p,b["slots"],cadence_seconds) for b,p in zip(views,preds)]
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
    predictions=np.concatenate([predict(b["scores"],b["baseline_predictions"],selected)[b["observed"]] for b in blocks])
    selected["calibration_comparison"]=_comparison(labels,base,predictions,slots,cadence_seconds)
    return selected,trials


