"""Independent, read-only audit of the completed, frozen v4 experiment.

Never imports the production metrics, selector, or model modules. It does not
open any 2017 CSV until all six external results and every required output
exist. Only final_audit.json is written; no model decisions are made here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/ml/gecco-v4"
DECLARED_PROTOCOL_SHA256 = "604825a813513073e1669a76db6474f19d1b66c854a4eb30e6066b16834291ff"
V1_SNAPSHOT = {
    "output/ml/gecco-baseline-v1/freeze.json": "608fb0cc477132f4b0b8cbac5c8a787d9e94416df8ef9daa84da67e88cee70a4",
    "output/ml/gecco-baseline-v1/test_results.json": "219db24a77a871d2605c7357c0029339f0f957d05b39362915451132509efadd",
    "output/ml/gecco-baseline-v1/test_predictions.csv.gz": "d1ba275df2142648a2d97598e24106f952a2c38e94fa7f2c66a89b24daf2efae",
    "output/ml/gecco-baseline-v1/model.joblib": "40dc599fd27d583674e3cf81dcef206af14d6a4ca3b3f8b4f1eaa3e4c12f3bef",
    "output/ml/gecco-baseline-v1/data_manifest.json": "a51f0c46f6c56ad26aa03aa08a9d6012e7d0becaf62c3641c93443d1b9f8136d",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def read_csv(path, **kwargs):
    # Preserve threshold-adjacent score bits when checking >= decisions.
    return pd.read_csv(path, float_precision="round_trip", **kwargs)


def spans(flags):
    result, beginning = [], None
    for index, active in enumerate([*map(bool, flags), False]):
        if active and beginning is None:
            beginning = index
        elif not active and beginning is not None:
            result.append((beginning, index))
            beginning = None
    return result


def ratio(top, bottom):
    return float(top / bottom) if bottom else None


def independent_metrics(labels, predictions):
    y, p = list(map(bool, labels)), list(map(int, predictions))
    assert len(y) == len(p) and set(p).issubset({-1, 0, 1})
    valid = [v != -1 for v in p]
    alarm = [v == 1 for v in p]
    raw_starts = [a and (i == 0 or p[i - 1] != 1) for i, a in enumerate(alarm)]
    confirmed = [a and i > 0 and p[i - 1] == 0 for i, a in enumerate(alarm)]
    tp = sum(t and v == 1 for t, v in zip(y, p))
    fp = sum(not t and v == 1 for t, v in zip(y, p))
    fn = sum(t and v == 0 for t, v in zip(y, p))
    tn = sum(not t and v == 0 for t, v in zip(y, p))
    false_runs = spans([not t and a for t, a in zip(y, alarm)])
    events, delays = [], []
    for start, end in spans(y):
        positive = next((i for i in range(start, end) if alarm[i]), None)
        fresh = next((i for i in range(start, end) if raw_starts[i]), None)
        certain = next((i for i in range(start, end) if confirmed[i]), None)
        covered, onset = positive is not None, alarm[start]
        available = sum(valid[start:end])
        unknown_previous = fresh is not None and fresh > 0 and p[fresh - 1] == -1
        if covered:
            delays.append(positive - start)
        events.append({
            "event_id": len(events) + 1, "start": start, "end": end,
            "duration_minutes": end - start,
            "boundary_censored": start == 0 or end == len(y),
            "valid_count": available, "unavailable_count": end - start - available,
            "fully_unscorable": available == 0, "detected": covered,
            "first_alarm_index": positive,
            "detection_delay_minutes": positive - start if covered else None,
            "covered_at_onset": onset, "new_alarm_inside_event": fresh is not None,
            "new_alarm_start_index": fresh,
            "new_alarm_delay_minutes": fresh - start if fresh is not None else None,
            "new_alarm_previous_unavailable": unknown_previous,
            "new_alarm_previous_unknown": fresh == 0 or unknown_previous,
            "confirmed_new_alarm_inside_event": certain is not None,
            "confirmed_new_alarm_index": certain,
            "confirmed_new_alarm_delay_minutes": certain - start if certain is not None else None,
            "alarm_started_at_onset": raw_starts[start],
            "detection_kind": "covered_at_onset" if onset else "first_alarm_after_onset" if covered else "undetected",
        })
    count = len(events)
    detected = sum(e["detected"] for e in events)
    fresh = sum(e["new_alarm_inside_event"] for e in events)
    certain = sum(e["confirmed_new_alarm_inside_event"] for e in events)
    complete = [e for e in events if not e["boundary_censored"]]
    complete_detected = sum(e["detected"] for e in complete)
    complete_fresh = sum(e["new_alarm_inside_event"] for e in complete)
    complete_certain = sum(e["confirmed_new_alarm_inside_event"] for e in complete)
    normal_days = (fp + tn) / 1440
    return {
        "sample_count": len(y), "valid_count": sum(valid), "unavailable_count": len(y) - sum(valid),
        "prediction_coverage": ratio(sum(valid), len(y)), "normal_valid_count": fp + tn,
        "positive_valid_count": tp + fn, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn), "false_positive_rate": ratio(fp, fp + tn),
        "false_negative_rate": ratio(fn, fn + tp), "specificity": ratio(tn, tn + fp),
        "accuracy": ratio(tp + tn, sum(valid)), "false_positive_runs": len(false_runs),
        "eligible_normal_days": normal_days, "false_alarm_runs_per_normal_day": ratio(len(false_runs), normal_days),
        "normal_time_under_alarm": ratio(fp, fp + tn), "alarm_runs": len(spans(alarm)),
        "true_events": count, "detected_events": detected, "undetected_events": count - detected,
        "fully_unscorable_events": sum(e["fully_unscorable"] for e in events),
        "event_recall": ratio(detected, count), "new_alarm_inside_event_recall": ratio(fresh, count),
        "raw_new_alarm_inside_event_recall": ratio(fresh, count),
        "confirmed_new_alarm_inside_event_recall": ratio(certain, count),
        "covered_at_onset_events": sum(e["covered_at_onset"] for e in events),
        "new_alarm_inside_events": fresh, "raw_new_alarm_inside_events": fresh,
        "confirmed_new_alarm_inside_events": certain, "boundary_censored_events": count - len(complete),
        "complete_events": len(complete), "complete_detected_events": complete_detected,
        "complete_new_alarm_inside_events": complete_fresh,
        "complete_confirmed_new_alarm_inside_events": complete_certain,
        "complete_event_coverage": ratio(complete_detected, len(complete)),
        "complete_event_new_alarm_start_recall": ratio(complete_fresh, len(complete)),
        "complete_raw_new_alarm_start_recall": ratio(complete_fresh, len(complete)),
        "complete_confirmed_new_alarm_start_recall": ratio(complete_certain, len(complete)),
        "median_detection_delay_minutes": float(np.median(delays)) if delays else None,
        "p95_detection_delay_minutes": float(np.percentile(delays, 95)) if delays else None,
        "event_records": events,
        "false_alarm_records": [{"start": s, "end": e, "duration_minutes": e - s} for s, e in false_runs],
    }


def independent_policy(scores, threshold, policy):
    required, width = {"instant": (1, 1), "2of3": (2, 3), "3of5": (3, 5)}[policy]
    output = []
    for i in range(len(scores)):
        window = scores[max(0, i - width + 1):i + 1]
        if len(window) != width or not all(math.isfinite(float(v)) for v in window):
            output.append(-1)
        else:
            output.append(int(sum(v >= threshold for v in window) >= required))
    return np.asarray(output, dtype=int)


class Audit:
    def __init__(self):
        self.checked = 0
        self.findings = []
        self.summary = {}

    def check(self, condition, location, detail=None):
        self.checked += 1
        if not bool(condition):
            self.findings.append({"location": location, "detail": str(detail)})

    def compare(self, expected, actual, location):
        if isinstance(expected, dict):
            for key, value in expected.items():
                self.check(key in actual, location + "." + key, "missing key")
                if key in actual:
                    self.compare(value, actual[key], location + "." + key)
        elif isinstance(expected, list):
            self.check(len(expected) == len(actual), location, "record count differs")
            for i, (a, b) in enumerate(zip(expected, actual)):
                self.compare(a, b, f"{location}[{i}]")
        elif isinstance(expected, float):
            self.check(actual is not None and math.isclose(expected, float(actual), rel_tol=1e-12, abs_tol=1e-12),
                       location, {"expected": expected, "actual": actual})
        else:
            self.check(expected == actual, location, {"expected": expected, "actual": actual})

    def metric_pair(self, frame, saved, location):
        y = frame.EVENT.to_numpy(dtype=bool)
        base, newer = [frame[f"{role}_prediction"].to_numpy(dtype=int) for role in ["baseline", "v4"]]
        common = (base >= 0) & (newer >= 0)
        for scope in ["native", "common"]:
            for role, p in [("baseline", base), ("v4", newer)]:
                values = p if scope == "native" else np.where(common, p, -1)
                independent = independent_metrics(y, values)
                self.compare(independent, saved[scope][role], f"{location}.{scope}.{role}")
        self.summary[location] = {role: {key: saved["common"][role][key] for key in
            ["tp", "fp", "fn", "tn", "f1", "true_events", "confirmed_new_alarm_inside_events",
             "false_alarm_runs_per_normal_day", "normal_time_under_alarm"]} for role in ["baseline", "v4"]}


PRECHOICE_SHA = "09a999ed2d4dd9908d45aea13b5ef1af4ab4eaa9dd5fbda1f8b022d099b18cfb"
OLD_MANIFEST_SHA = "79f6a3bce08318aeea640668094fc99d485530cbd5f570a1f1fdb537ce38b5dd"
CHANNELS = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
GAP = 120


def policy_fast(scores, threshold, policy):
    needed, width = {"instant": (1, 1), "2of3": (2, 3), "3of5": (3, 5)}[policy]
    out = np.full(len(scores), -1, dtype=np.int8)
    available = np.isfinite(scores)
    if len(scores) >= width:
        good = np.convolve(available.astype(int), np.ones(width, int), mode="valid") == width
        votes = np.convolve((available & (scores >= threshold)).astype(int), np.ones(width, int), mode="valid")
        out[np.arange(width-1, len(scores))[good]] = (votes[good] >= needed).astype(np.int8)
    return out


def compact_fast(y, p):
    """Independent vectorized counts for every trial, without event records."""
    y = np.asarray(y, bool); p = np.asarray(p, int)
    valid, alarm = p >= 0, p == 1
    fresh = alarm & np.r_[True, p[:-1] != 1]
    confirmed = alarm & np.r_[False, p[:-1] == 0]
    changes = np.diff(np.r_[False, y, False].astype(int))
    starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    complete = (starts > 0) & (ends < len(y))
    def hit(mask):
        totals = np.r_[0, np.cumsum(mask)]
        return (totals[ends] - totals[starts]) > 0
    tp, fp = int((y & alarm).sum()), int((~y & alarm).sum())
    fn, tn = int((y & (p == 0)).sum()), int((~y & (p == 0)).sum())
    false = ~y & alarm
    runs = int((false & np.r_[True, ~false[:-1]]).sum())
    event_hits, known = hit(alarm), hit(confirmed)
    days = (fp+tn)/1440
    return {"sample_count": len(y), "valid_count": int(valid.sum()), "unavailable_count": int((~valid).sum()),
            "prediction_coverage": ratio(int(valid.sum()), len(y)), "precision": ratio(tp,tp+fp),
            "recall": ratio(tp,tp+fn), "f1": ratio(2*tp,2*tp+fp+fn), "tp":tp,"fp":fp,"fn":fn,"tn":tn,
            "true_events":len(starts),"detected_events":int(event_hits.sum()),"event_recall":ratio(int(event_hits.sum()),len(starts)),
            "confirmed_new_alarm_inside_events":int(known.sum()),"confirmed_new_alarm_inside_event_recall":ratio(int(known.sum()),len(starts)),
            "false_positive_runs":runs,"eligible_normal_days":days,"false_alarm_runs_per_normal_day":ratio(runs,days),
            "normal_time_under_alarm":ratio(fp,fp+tn),"complete_events":int(complete.sum()),
            "complete_confirmed_new_alarm_inside_events":int((known & complete).sum()),
            "complete_confirmed_new_alarm_start_recall":ratio(int((known & complete).sum()),int(complete.sum()))}


def aggregate_blocks(metrics):
    tp=sum(m["tp"] for m in metrics); fp=sum(m["fp"] for m in metrics); fn=sum(m["fn"] for m in metrics)
    events=sum(m["complete_events"] for m in metrics)
    caught=sum(m["complete_confirmed_new_alarm_inside_events"] for m in metrics)
    event_rates=[m["complete_confirmed_new_alarm_start_recall"] for m in metrics if m["complete_events"]]
    return {"pooled_point_f1":ratio(2*tp,2*tp+fp+fn) or 0,"complete_events":events,"complete_confirmed":caught,
            "pooled_confirmed_recall":ratio(caught,events) or 0,"worst_event_block_recall":min(event_rates) if event_rates else 0,
            "worst_false_runs_per_day":max(m["false_alarm_runs_per_normal_day"] or 0 for m in metrics),
            "worst_false_duration_fraction":max(m["normal_time_under_alarm"] or 0 for m in metrics),"fp_minutes":fp,
            "feasible_all_blocks":all(m["false_alarm_runs_per_normal_day"] is not None and m["normal_time_under_alarm"] is not None
                 and m["false_alarm_runs_per_normal_day"]<=1 and m["normal_time_under_alarm"]<=.01 for m in metrics)}


def safe_csv(path):
    try:return read_csv(path)
    except pd.errors.EmptyDataError:return pd.DataFrame()


def number(value):
    return None if isinstance(value, float) and np.isnan(value) else value


def expected_score_mask(part, role):
    raw=part.iloc[GAP:][CHANNELS].astype(float).replace([np.inf,-np.inf],np.nan).reset_index(drop=True)
    current=raw.notna().all(axis=1)
    if role=="baseline":
        eligible=current.rolling(15,min_periods=15).sum().eq(15).to_numpy()
    else:
        # Frozen return_gated_channel_median5: actual observations only.
        noise=raw.diff().abs().shift(1).rolling(30,min_periods=15).count()
        prior=raw.shift(1)
        short=prior.rolling(30,min_periods=15).count()
        anchor=prior.rolling(180,min_periods=90).count()
        eligible=current.to_numpy() & (noise.to_numpy()>=15).all(axis=1) & (short.to_numpy()>=15).all(axis=1) & (anchor.to_numpy()>=90).all(axis=1)
        eligible=pd.Series(eligible).rolling(5,min_periods=5).sum().eq(5).to_numpy()
    return np.r_[np.zeros(min(GAP,len(part)),bool),eligible]


def audit_calibration(audit, folder, freeze, source, bounds):
    frame=read_csv(folder/"calibration_predictions.csv.gz")
    start,end=int(bounds[0]),int(bounds[-1])
    audit.check(np.array_equal(frame.sample_index,np.arange(start,end)),str(folder)+".cal_axis")
    y=source.EVENT.iloc[start:end].to_numpy(bool)
    audit.check(np.array_equal(frame.EVENT.to_numpy(bool),y),str(folder)+".cal_original_labels")
    slices=[slice(int(a-start),int(b-start)) for a,b in zip(bounds[:-1],bounds[1:])]
    block_labels=[y[s] for s in slices]
    selection_summary={}
    for role in ["baseline","v4"]:
        scores=frame[role+"_score"].to_numpy(float)
        for j,(a,b) in enumerate(zip(bounds[:-1],bounds[1:])):
            part=source.iloc[int(a):int(b)].reset_index(drop=True)
            mask=expected_score_mask(part,role)
            audit.check(np.array_equal(np.isfinite(scores[slices[j]]),mask),f"{folder.name}.{role}.cal{j}.availability")
        trials=safe_csv(folder/f"{role}_calibration_trials.csv.gz")
        chosen=freeze["selected"][role]
        vals=scores[np.isfinite(scores)]
        if not len(vals):
            audit.check(role=="v4" and len(trials)==0 and chosen.get("unavailable_reason")=="one_class_or_no_valid_calibration",str(folder)+".empty_calibration")
            continue
        qs=(np.unique(np.r_[0,.5,.75,np.linspace(.8,.99,191),np.linspace(.99,1,201)]) if role=="baseline"
            else np.unique(np.r_[np.linspace(0,.9,37),np.linspace(.9,1,65)]))
        thresholds=np.unique(np.r_[np.quantile(vals,qs),np.nextafter(vals.max(),np.inf)] if role=="baseline"
                             else np.r_[0,np.quantile(vals,qs),np.nextafter(vals.max(),np.inf)])
        policies=["instant"] if role=="baseline" else ["instant","2of3","3of5"]
        expected_grid=[(policy,float(t)) for policy in policies for t in thresholds]
        audit.check(len(trials)==len(expected_grid),f"{folder.name}.{role}.trial_grid_count")
        independent_rows=[]
        for i,(row,(policy,threshold)) in enumerate(zip(trials.to_dict("records"),expected_grid)):
            audit.check(row["policy"]==policy and row["threshold"]==threshold,f"{folder.name}.{role}.trial{i}.grid")
            if role=="baseline":
                metrics=compact_fast(y,policy_fast(scores,threshold,policy))
                feasible=metrics["false_alarm_runs_per_normal_day"] is not None and metrics["normal_time_under_alarm"] is not None and metrics["false_alarm_runs_per_normal_day"]<=1 and metrics["normal_time_under_alarm"]<=.01
                r={"threshold":threshold,"policy":policy,"feasible":feasible,"no_events":not bool(y.any()),
                   **{k:metrics[k] for k in row if k in metrics}}
            else:
                blocks=[compact_fast(y[s],policy_fast(scores[s],threshold,policy)) for s in slices]
                r={"threshold":threshold,"policy":policy,**aggregate_blocks(blocks)}
            audit.compare(r,{k:number(v) for k,v in row.items()},f"{folder.name}.{role}.trial{i}")
            independent_rows.append(r)
        if role=="baseline":
            options=[r for r in independent_rows if r["feasible"]]
            winner=max(options,key=lambda r:(r["f1"] or 0,-r["fp"],r["threshold"]))
        else:
            options=[r for r in independent_rows if r["feasible_all_blocks"]]
            if options:
                winner=max(options,key=lambda r:(r["worst_event_block_recall"],r["pooled_confirmed_recall"],r["pooled_point_f1"],-r["fp_minutes"],r["threshold"]))
                winner={**winner,"calibration_status":"feasible_all_blocks"}
            else:
                winner=next(r for r in independent_rows if r["policy"]=="instant" and r["threshold"]==thresholds[-1])
                winner={**winner,"calibration_status":"no_feasible_operating_point_all_silent"}
        audit.compare(winner,chosen,f"{folder.name}.{role}.selected_winner")
        if role=="baseline":
            measured=independent_metrics(y,independent_policy(scores,chosen["threshold"],chosen["policy"]))
            audit.compare({k:measured[k] for k in chosen if k in measured},chosen,f"{folder.name}.baseline.selected_metrics")
        else:
            measured=[independent_metrics(y[s],independent_policy(scores[s],chosen["threshold"],chosen["policy"])) for s in slices]
            for j,m in enumerate(measured):
                audit.compare({k:v for k,v in m.items() if not k.endswith("records")},chosen["block_metrics"][j],f"{folder.name}.v4.selected_block{j}")
        selection_summary[role]={"threshold":chosen["threshold"],"policy":chosen["policy"],"trial_count":len(trials),
            "calibration_events_per_block":[len(spans(labels)) for labels in block_labels],
            "selected_block_metrics":chosen.get("block_metrics"),"selected_metrics":{k:v for k,v in chosen.items() if k!="block_metrics"}}
    return selection_summary


def independent_assess(frame):
    y=frame.EVENT.to_numpy(bool)
    pred={r:frame[r+"_prediction"].to_numpy(int) for r in ["baseline","v4"]}
    common=(pred["baseline"]>=0)&(pred["v4"]>=0)
    return {scope:{r:independent_metrics(y,p if scope=="native" else np.where(common,p,-1)) for r,p in pred.items()} for scope in ["native","common"]}


def independent_gates(result, folds):
    def known(a,b):return all(m[k] is not None for m in [a,b] for k in ["false_alarm_runs_per_normal_day","normal_time_under_alarm"])
    def noninferior(f):
        a,b=f["common"]["baseline"],f["common"]["v4"]
        return known(a,b) and b["confirmed_new_alarm_inside_events"]>=a["confirmed_new_alarm_inside_events"] and b["false_alarm_runs_per_normal_day"]<=a["false_alarm_runs_per_normal_day"] and b["normal_time_under_alarm"]<=a["normal_time_under_alarm"]
    a,b=result["common"]["baseline"],result["common"]["v4"]
    pooled=known(a,b) and b["confirmed_new_alarm_inside_events"]>a["confirmed_new_alarm_inside_events"] and b["false_alarm_runs_per_normal_day"]<a["false_alarm_runs_per_normal_day"] and b["normal_time_under_alarm"]<=a["normal_time_under_alarm"]
    comparable=[noninferior(f) for f in folds]
    budgets=[]
    for f in folds:
        m=f["native"]["v4"]
        budgets.append(known(m,m) and m["false_alarm_runs_per_normal_day"]<=1 and m["normal_time_under_alarm"]<=.01)
    return {"pooled_joint_improvement":pooled,"noninferior_periods":comparable,"noninferior_period_count":sum(comparable),
            "stable_joint_improvement":pooled and all(comparable),"operating_budget_pass_per_period":budgets,
            "all_period_operating_budget_pass":all(budgets),"3d_connected":False}


def audit_run(audit, name, source, protocol, prechoice):
    run=OUT/name
    n=len(source)
    access=read_json(run/"label_access_started.json")
    audit.check(access["protocol_sha256"]==DECLARED_PROTOCOL_SHA256,name+".access_protocol")
    audit.check(datetime.fromisoformat(prechoice["chosen_at_utc"])<datetime.fromisoformat(protocol["frozen_at_utc"])<=datetime.fromisoformat(access["at_utc"]),name+".choice_before_protocol_before_label_access")
    source_path=ROOT/protocol["source_file"] if name=="external_2017" else ROOT/"data/external/gecco2018/1_gecco2018_water_quality.csv"
    audit.check(access["source_sha256"]==sha(source_path),name+".access_source")
    parts=[]; independent_folds=[]
    for k in range(4,10):
        folder=run/f"fold_{k-3}"; location=f"{name}.fold_{k-3}"
        frozen=read_json(folder/"freeze.json"); saved=read_json(folder/"test_results.json")
        train_end,start,end=[n*j//10 for j in [k-2,k,k+1]]
        bounds=np.linspace(train_end,start,5,dtype=int)
        audit.compare([0,train_end],frozen["train"],location+".train_bounds")
        audit.compare([[int(a),int(b)] for a,b in zip(bounds[:-1],bounds[1:])],frozen["calibration_blocks"],location+".cal_bounds")
        audit.compare([start,end],frozen["test"],location+".test_bounds")
        audit.compare([start,end],saved["test"],location+".saved_test_bounds")
        audit.check(frozen["protocol_sha256"]==DECLARED_PROTOCOL_SHA256,location+".protocol_lock")
        audit.check(datetime.fromisoformat(access["at_utc"])<=datetime.fromisoformat(frozen["frozen_at_utc"])<datetime.fromisoformat(saved["scored_at_utc"]),location+".freeze_before_test")
        audit.check(set(frozen["model_sha256"])=={"baseline","v4"},location+".model_count_roles")
        for role,digest in frozen["model_sha256"].items():audit.check(sha(folder/f"{role}_model.joblib")==digest,location+"."+role+".model_hash")
        selections=audit_calibration(audit,folder,frozen,source,bounds)
        frame=read_csv(folder/"test_predictions.csv.gz"); original=source.iloc[start:end].reset_index(drop=True)
        audit.check(np.array_equal(frame.sample_index,np.arange(start,end)),location+".source_axis")
        audit.check(np.array_equal(frame.EVENT.to_numpy(bool),original.EVENT.to_numpy(bool)),location+".original_labels")
        audit.check(np.array_equal(frame.timestamp_original,original.Time),location+".original_timestamps")
        audit.check(saved["excluded_gap_event_minutes"]==int(original.EVENT.iloc[:GAP].sum()),location+".gap_event_minutes")
        audit.check(saved["raw_incomplete_event_minutes"]==int((original[CHANNELS].isna().any(axis=1).to_numpy()&original.EVENT.to_numpy(bool)).sum()),location+".raw_missing_event_minutes")
        for role in ["baseline","v4"]:
            sc=frame[role+"_score"].to_numpy(float); pred=frame[role+"_prediction"].to_numpy(int); chosen=frozen["selected"][role]
            audit.check(np.array_equal(np.isfinite(sc),expected_score_mask(original,role)),location+"."+role+".availability")
            audit.check(np.isnan(sc[:GAP]).all() and (pred[:GAP]==-1).all(),location+"."+role+".gap")
            audit.check(np.array_equal(pred,independent_policy(sc,chosen["threshold"],chosen["policy"])),location+"."+role+".policy")
        audit.metric_pair(frame,saved,location)
        audit.summary[location]["selection"]=selections
        independent_folds.append(independent_assess(frame));parts.append(frame)
    expected=pd.concat(parts,ignore_index=True); combined=read_csv(run/"predictions.csv.gz")
    audit.check(np.array_equal(combined.sample_index,np.arange(n*4//10,n)),name+".global_axis")
    audit.check(np.array_equal(combined.EVENT.to_numpy(bool),source.EVENT.iloc[n*4//10:].to_numpy(bool)),name+".global_original_labels")
    for column in expected.columns:
        if column.endswith("_score"):
            a,b=expected[column].to_numpy(float),combined[column].to_numpy(float)
            good=np.isfinite(a)&np.isfinite(b)
            delta=np.abs(a[good]-b[good])
            audit.summary.setdefault("csv_score_roundtrip",{})[name+"."+column]={"maximum_absolute_difference":float(delta.max()) if len(delta) else 0.,"maximum_relative_difference_over_max_1_abs":float((delta/np.maximum(1,np.abs(a[good]))).max()) if len(delta) else 0.}
            audit.check(np.array_equal(np.isnan(a),np.isnan(b)) and np.allclose(a,b,rtol=5e-16,atol=1e-15,equal_nan=True),name+".combined."+column)
        else:audit.check(np.array_equal(expected[column],combined[column]),name+".combined."+column)
    saved=read_json(run/"results.json")
    audit.metric_pair(combined,saved,name+".global")
    result=independent_assess(combined)
    gates=independent_gates(result,independent_folds)
    audit.compare(gates,saved["gates"],name+".gates")
    for i,(independent,recorded) in enumerate(zip(independent_folds,saved["folds"])):
        audit.compare(independent,recorded,f"{name}.embedded_fold{i+1}")
    audit.check(len(saved["folds"])==6,name+".six_folds")
    audit.check(saved["protocol_sha256"]==DECLARED_PROTOCOL_SHA256,name+".global_protocol")
    audit.summary[name+".gates"]=gates


def require_complete():
    required=[OUT/"protocol.json",OUT/"pre_external_choice.json"]
    for name in ["external_2017","development_2018"]:
        run=OUT/name
        required.extend(run/f for f in ["results.json","predictions.csv.gz","label_access_started.json"])
        for i in range(1,7):
            required.extend(run/f"fold_{i}"/f for f in ["freeze.json","test_results.json","test_predictions.csv.gz","calibration_predictions.csv.gz","baseline_calibration_trials.csv.gz","v4_calibration_trials.csv.gz","baseline_model.joblib","v4_model.joblib"])
    absent=[str(p) for p in required if not p.exists()]
    if absent:raise SystemExit("Audit blocked before any new-source CSV access: incomplete outputs: "+str(absent))


def main():
    require_complete()  # Must precede all raw source reads and raw source hashes.
    audit=Audit(); protocol=read_json(OUT/"protocol.json"); prechoice=read_json(OUT/"pre_external_choice.json")
    audit.check(sha(OUT/"protocol.json")==DECLARED_PROTOCOL_SHA256,"protocol_sha256")
    audit.check(sha(OUT/"pre_external_choice.json")==PRECHOICE_SHA,"prechoice_sha256")
    audit.check(protocol["family"]==prechoice["family"]=="adaptive" and protocol["recipe"]==prechoice["recipe"]=="return_gated_channel_median5","locked_choice")
    audit.check(prechoice["new_source_labels_read"] is False and protocol["new_source_event_values_read_before_freeze"] is False,"prefreeze_label_flags")
    for path,digest in protocol["code_sha256"].items():audit.check(sha(ROOT/path)==digest,"method_hash."+path)
    audit.check(sha(ROOT/"ml/gecco_v4/adaptive_candidate.py")==prechoice["candidate_sha256"],"prechoice_candidate_hash")
    audit.check(sha(ROOT/protocol["source_file"])==protocol["source_sha256"],"external_source_hash")
    for path,digest in protocol["development_source_sha256"].items():audit.check(sha(ROOT/path)==digest,"development_source_hash")
    manifest_path=ROOT/"output/ml/gecco-comparison/package_manifest.json"
    audit.check(sha(manifest_path)==OLD_MANIFEST_SHA,"historical_manifest_hash")
    historical=read_json(manifest_path)
    prefixes=("ml/gecco_baseline/","ml/gecco_v2/","ml/gecco_v3/","output/ml/gecco-baseline-v1/","output/ml/gecco-v2/","output/ml/gecco-v3/")
    historical_count=0
    for path,meta in historical["files"].items():
        if path.startswith(prefixes):
            historical_count+=1
            audit.check((ROOT/path).exists() and sha(ROOT/path)==meta["sha256"],"unchanged_previous."+path)
    for path,digest in V1_SNAPSHOT.items():audit.check(sha(ROOT/path)==digest,"original_v1_snapshot."+path)
    audit.summary["unchanged_historical_artifacts_checked"]=historical_count
    for name,path in [("development_2018",ROOT/"data/external/gecco2018/1_gecco2018_water_quality.csv"),("external_2017",ROOT/protocol["source_file"])]:
        source=read_csv(path)
        if name=="external_2017":audit.check(len(source)==protocol["source_rows"],"external_source_row_count")
        audit_run(audit,name,source,protocol,prechoice)
    report={"status":"pass" if not audit.findings else "findings","audited_at_utc":datetime.now(timezone.utc).isoformat(),
            "audit_code_sha256":sha(__file__),"declared_protocol_sha256":DECLARED_PROTOCOL_SHA256,
            "checks_performed":audit.checked,"findings":audit.findings,"summary":audit.summary,
            "independent_implementation":"No production evaluation, policy, selector, runner or model imports. Every saved calibration trial recalculated from saved scores; no models refitted.",
            "access_guard":"No raw2017 source access until all six final periods and combined results for both2018/2017 exist. Human completion authorization was also required.",
            "chronology_limit":"Checks recorded freezes and access logs plus previously audited prefix-only workflow; filesystem records cannot independently reconstruct every possible read outside that workflow.",
            "csv_score_tolerance":"Combined score CSV reserialization allowed absolute1e-15 plus relative5e-16 (scores can exceed100); labels, axes, decisions and missing masks must match exactly. Per-fold original scores used for policy replay.",
            "audit_pass_is_not_performance_success":True}
    (OUT/"final_audit.json").write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print(json.dumps({"status":report["status"],"checks_performed":audit.checked,"findings":audit.findings,"output":str(OUT/"final_audit.json")},ensure_ascii=False))
    if audit.findings:raise SystemExit(1)


if __name__=="__main__":main()

