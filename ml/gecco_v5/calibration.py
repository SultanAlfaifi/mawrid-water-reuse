"""Past-only calibration of a causal gate, with explicit baseline fallback.

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
    return base


def _stats(labels, predictions, cadence_seconds=60):
    y=np.asarray(labels,bool);p=np.asarray(predictions,int)
    starts,ends=_spans(y)
    confirmed=(p==1)&np.r_[False,p[:-1]==0]
    found=[];times=[]
    for event_id,(a,b) in enumerate(zip(starts,ends),1):
        hit=np.flatnonzero(confirmed[a:b])
        if len(hit):found.append(event_id);times.append(int(a+hit[0]))
    alarm=p==1;false=(~y)&alarm
    fp=int(false.sum());tn=int(((~y)&(p==0)).sum())
    runs=int((false&np.r_[True,~false[:-1]]).sum())
    normal_seconds=(fp+tn)*cadence_seconds
    tp=int((y&alarm).sum());fn=int((y&(p==0)).sum())
    return {"true_events":len(starts),"confirmed_event_ids":found,"confirmed_times":times,
            "confirmed_events":len(found),"tp":tp,"fp":fp,"fn":fn,"tn":tn,
            "false_positive_runs":runs,"normal_observed_seconds":normal_seconds,
            "false_runs_per_day":runs*86400/normal_seconds if normal_seconds else None,
            "normal_alarm_fraction":fp/(fp+tn) if fp+tn else None,
            "fp_duration_seconds":fp*cadence_seconds,"available_rows":int((p>=0).sum())}


def _comparison(labels, base, prediction, cadence):
    b=_stats(labels,base,cadence);c=_stats(labels,prediction,cadence)
    lost=sorted(set(b["confirmed_event_ids"])-set(c["confirmed_event_ids"]))
    bt=dict(zip(b["confirmed_event_ids"],b["confirmed_times"]));ct=dict(zip(c["confirmed_event_ids"],c["confirmed_times"]))
    delays=[{"event_id":i,"extra_delay_seconds":(ct[i]-bt[i])*cadence} for i in bt if i in ct]
    return {"baseline":b,"candidate":c,"lost_baseline_event_ids":lost,
            "hidden_baseline_rows":int(((np.asarray(base)>=0)&(np.asarray(prediction)<0)).sum()),
            "paired_extra_delays":delays}


def _validated(blocks):
    if not blocks:raise ValueError("At least one calibration block is required")
    result=[];next_start=None
    for i,block in enumerate(blocks):
        y=np.asarray(block["labels"]);s=np.asarray(block["scores"],float);b=np.asarray(block["baseline_predictions"])
        if y.ndim!=1 or len(y)==0 or s.shape!=y.shape or b.shape!=y.shape:
            raise ValueError("Calibration block arrays must have equal nonempty one-dimensional shape")
        if y.dtype.kind not in "biu" or b.dtype.kind not in "biu" or not np.isin(y,[0,1]).all() or not np.isin(b,[-1,0,1]).all():
            raise ValueError("Use original binary labels and {-1,0,1} baseline predictions")
        if not isinstance(block["source_start"],(int,np.integer)) or block["source_start"]<0:
            raise ValueError("source_start must be a nonnegative integer acquisition index")
        start=int(block["source_start"])
        if next_start is not None and start!=next_start:raise ValueError("Calibration blocks must be adjacent on the original source axis")
        next_start=start+len(y)
        result.append({"labels":y.astype(bool),"scores":s,"baseline_predictions":b.astype(np.int8),
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


def explore_stored_scores():
    """Development oracle feasibility, not a causal or independent evaluation."""
    import pandas as pd
    root=Path(__file__).resolve().parents[2];out=root/"output/ml/gecco-v5-calibration-development";out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for source in ["external_2017","development_2018"]:
        for fold in range(1,7):
            frame=pd.read_csv(root/"output/ml/gecco-v4"/source/f"fold_{fold}"/"test_predictions.csv.gz",float_precision="round_trip")
            y=frame.EVENT.to_numpy(bool);base=frame.baseline_prediction.to_numpy(np.int8);ref=_stats(y,base)
            for score_name in ["v4_score","baseline_score"]:
                scores=frame[score_name].to_numpy(float);finite=scores[np.isfinite(scores)]
                grid=np.unique(np.r_[np.quantile(finite,np.linspace(0,1,501)),np.nextafter(finite.max(),np.inf)])
                candidates=[]
                for policy in POLICIES:
                    for threshold in grid:
                        pred=predict(scores,base,{"decision":"candidate","threshold":threshold,"policy":policy})
                        cmp=_comparison(y,base,pred,60);m=cmp["candidate"]
                        if not cmp["lost_baseline_event_ids"] and m["false_runs_per_day"]<=ref["false_runs_per_day"] and m["fp"]<=ref["fp"]:
                            candidates.append({"threshold":float(threshold),"policy":policy,"false_runs_per_day":m["false_runs_per_day"],"fp":m["fp"],"events":m["confirmed_events"],"max_extra_delay_seconds":max([d["extra_delay_seconds"] for d in cmp["paired_extra_delays"]],default=None)})
                best=min(candidates,key=lambda r:(r["false_runs_per_day"],r["fp"],r["max_extra_delay_seconds"] or 0)) if candidates else None
                row={"source":source,"fold":fold,"gate_score":score_name,"baseline_events":ref["confirmed_events"],"true_events":ref["true_events"],
                     "baseline_false_runs_per_day":ref["false_runs_per_day"],"baseline_fp":ref["fp"],"checked_points":len(grid)*3,
                     "strict_improvement_possible_on_exposed_period":bool(best and best["false_runs_per_day"]<ref["false_runs_per_day"]),"oracle_best":best}
                rows.append(row);print(json.dumps(row),flush=True)
    (out/"oracle_feasibility.json").write_text(json.dumps({"scope":"ORACLE posthoc feasibility on fully exposed2017/2018 only; thresholds selected using these periods' labels and must never be reported as generalization","results":rows},indent=2,allow_nan=False)+"\n")


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--explore-stored",action="store_true")
    args=parser.parse_args()
    if args.explore_stored:explore_stored_scores()
    else:parser.error("Use --explore-stored for already-exposed development predictions")
