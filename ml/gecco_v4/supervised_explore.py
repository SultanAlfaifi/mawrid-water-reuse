"""Fully disclosed development only: fixed recipes and multiblock calibration.

Every GECCO 2018/2019 partition used here has already been disclosed. No result
is described as an independent test. No new independent dataset is accessed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"ml/gecco_baseline"))
sys.path.insert(0,str(ROOT/"ml/gecco_v2"))
from metrics import evaluate
from alarm_policy import predict
from supervised_candidate import FixedRelativeContextDetector,InvariantRelativeDetector,CHANNELS18,CHANNELS19,CONFIG

OUT=ROOT/"output/ml/gecco-v4-supervised-development"
GAP=120
RECIPES=("relative","ensemble")


def write(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+"\n")


def brief(result):return {k:v for k,v in result.items() if not k.endswith("records")}


def summarize_blocks(metrics):
    tp=sum(m["tp"] for m in metrics);fp=sum(m["fp"] for m in metrics);fn=sum(m["fn"] for m in metrics)
    events=sum(m["complete_events"] for m in metrics)
    confirmed=sum(m["complete_confirmed_new_alarm_inside_events"] for m in metrics)
    fractions=[m["complete_confirmed_new_alarm_start_recall"] for m in metrics if m["complete_events"]]
    return {"pooled_point_f1":2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,
            "complete_events":events,"complete_confirmed":confirmed,
            "pooled_confirmed_recall":confirmed/events if events else 0,
            "worst_event_block_recall":min(fractions) if fractions else 0,
            "worst_false_runs_per_day":max(m["false_alarm_runs_per_normal_day"] or 0 for m in metrics),
            "worst_false_duration_fraction":max(m["normal_time_under_alarm"] or 0 for m in metrics),
            "fp_minutes":fp,
            "feasible_all_blocks":all(m["false_alarm_runs_per_normal_day"] is not None and
                    m["normal_time_under_alarm"] is not None and m["false_alarm_runs_per_normal_day"]<=1
                    and m["normal_time_under_alarm"]<=.01 for m in metrics)}


def calibrate(blocks):
    finite=np.concatenate([scores[np.isfinite(scores)] for _,scores in blocks])
    if not len(finite):
        ms=[evaluate(y,predict(scores,1.,"instant")) for y,scores in blocks]
        chosen={"threshold":1.,"policy":"instant","calibration_status":"no_available_scores",**summarize_blocks(ms)}
        chosen["block_metrics"]=[brief(m) for m in ms]
        return chosen,[{k:v for k,v in chosen.items() if k!="block_metrics"}]
    quantiles=np.unique(np.r_[np.linspace(0,.9,37),np.linspace(.9,1,65)])
    thresholds=np.unique(np.r_[0,np.quantile(finite,quantiles),np.nextafter(finite.max(),np.inf)])
    trials=[]
    for policy in ("instant","2of3","3of5"):
        for threshold in thresholds:
            ms=[evaluate(y,predict(scores,float(threshold),policy)) for y,scores in blocks]
            trial={"threshold":float(threshold),"policy":policy,**summarize_blocks(ms)}
            trials.append(trial)
    feasible=[r for r in trials if r["feasible_all_blocks"]]
    if feasible:
        chosen=max(feasible,key=lambda r:(r["worst_event_block_recall"],r["pooled_confirmed_recall"],
                   r["pooled_point_f1"],-r["fp_minutes"],r["threshold"]))
        chosen["calibration_status"]="feasible_all_blocks"
    else:
        # No calibration evidence for a block: abstain conservatively instead of
        # silently relaxing the declared constraints or choosing on future data.
        chosen=next(r for r in trials if r["threshold"]==thresholds[-1] and r["policy"]=="instant")
        chosen["calibration_status"]="no_feasible_operating_point_all_silent"
    chosen["block_metrics"]=[brief(evaluate(y,predict(scores,chosen["threshold"],chosen["policy"]))) for y,scores in blocks]
    return chosen,trials


def run_case(name,train,calibration_blocks,test,channels,detector_class=FixedRelativeContextDetector):
    started=time.perf_counter()
    detector=detector_class(channels).fit(train,train.EVENT.to_numpy(dtype=bool))
    cal_components=[detector.score_components(block) for block in calibration_blocks]
    # Keep the original full evaluation axis, including every event in the gap.
    scored_test=test.iloc[GAP:].reset_index(drop=True)
    test_components={key:np.r_[np.full(min(GAP,len(test)),np.nan),values]
                     for key,values in detector.score_components(scored_test).items()}
    score_reason=np.r_[np.full(min(GAP,len(test)),"protocol_gap",dtype=object),detector.score_reasons(scored_test)]
    results=[]
    for recipe in RECIPES:
        blocks=[(block.EVENT.to_numpy(dtype=bool),score[recipe]) for block,score in zip(calibration_blocks,cal_components)]
        chosen,trials=calibrate(blocks)
        prediction=predict(test_components[recipe],chosen["threshold"],chosen["policy"])
        measured=evaluate(test.EVENT.to_numpy(dtype=bool),prediction)
        reason=score_reason.copy()
        reason[(prediction==-1)&np.isfinite(test_components[recipe])]="policy_warmup_after_unavailable"
        record={"case":name,"recipe":recipe,"development_only":True,"training_rows":len(train),
                "fit_rows":detector.fit_rows_,"fit_events":detector.fit_event_count_,
                "fit_status":detector.fit_status_,
                "unavailable_reasons":pd.Series(reason[prediction==-1]).value_counts().to_dict(),
                "calibration_blocks":len(blocks),"selected_calibration":chosen,"metrics":brief(measured)}
        results.append(record)
        pd.DataFrame(trials).to_csv(OUT/f"{name}_{recipe}_calibration_trials.csv.gz",index=False)
        pd.DataFrame({"source_index":test.index.to_numpy(),"EVENT":test.EVENT.to_numpy(dtype=bool),"score":test_components[recipe],
                      "prediction":prediction,"score_reason":score_reason,"prediction_reason":reason}).to_csv(OUT/f"{name}_{recipe}_development_predictions.csv.gz",index=False)
        write(OUT/f"{name}_{recipe}_events.json",measured["event_records"])
        print(json.dumps({"case":name,"recipe":recipe,"threshold":chosen["threshold"],"policy":chosen["policy"],
                          "cal_confirmed":[chosen["complete_confirmed"],chosen["complete_events"]],
                          "P":measured["precision"],"R":measured["recall"],"F1":measured["f1"],
                          "events":measured["true_events"],"confirmed":measured["confirmed_new_alarm_inside_events"],
                          "FPday":measured["false_alarm_runs_per_normal_day"],"FPtime":measured["normal_time_under_alarm"],
                          "coverage":measured["prediction_coverage"],"elapsed":time.perf_counter()-started}),flush=True)
    write(OUT/f"{name}_results.json",results)
    return results


def main():
    global OUT,RECIPES
    parser=argparse.ArgumentParser()
    parser.add_argument("--attempt",choices=["initial","invariant"],default="initial")
    parser.add_argument("--limit-cases",type=int,default=7)
    args=parser.parse_args()
    detector_class=FixedRelativeContextDetector
    if args.attempt=="invariant":
        OUT=OUT/f"attempt2_invariant_first{args.limit_cases}"
        RECIPES=("invariant",)
        detector_class=InvariantRelativeDetector
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/"results.json").exists():raise SystemExit("Results already exist; preserve attempt history")
    plan={"scope":"All GECCO2018/2019 disclosed; development only, not independent evaluation",
          "config":CONFIG,"recipes":RECIPES,"attempt":args.attempt,"limit_cases":args.limit_cases,
          "selection":"Fixed family per recipe. Select operating point across multiple past blocks: constrain EACH block to <=1 false run/normal-day and <=1% normal duration; maximize worst complete-event recall, then pooled confirmed recall, then raw point F1",
          "2018":"Six periods40-100%; train all history before previous20%; four5%-length calibration blocks with120-row leading gaps; evaluation retains full source axis with first120 predictions=-1 and all original events in denominator",
          "2019":"Train first80% ofTRAIN; calibrate on last20%TRAIN and two halves ofVALID; evaluate previously disclosedTEST",
          "missing":"Current all channels must be observed. Past-only ffill up to2 rows, original availability features, at least50% original past observations per15/60 window. Never fill current measurement.",
          "one_class_training":"Return all NaN scores with one_class_training/insufficient_normal_training reason; no family switch",
          "no_new_independent_data":True,"no_3d":True}
    write(OUT/"plan.json",plan)
    data=pd.read_csv(ROOT/"data/external/gecco2018/1_gecco2018_water_quality.csv")
    n=len(data);results=[]
    for k in range(4,10):
        if k-3>args.limit_cases:break
        train_end=n*(k-2)//10;test_start=n*k//10;test_end=n*(k+1)//10
        boundaries=np.linspace(train_end,test_start,5,dtype=int)
        blocks=[data.iloc[a+GAP:b].reset_index(drop=True) for a,b in zip(boundaries[:-1],boundaries[1:])]
        results+=run_case(f"2018_fold_{k-3}",data.iloc[:train_end].reset_index(drop=True),blocks,
                          data.iloc[test_start:test_end],CHANNELS18,detector_class)
    if args.limit_cases<=6:
        write(OUT/"results.json",{"development_only":True,"all_candidates_tried":list(RECIPES),"results":results})
        return
    folder=ROOT/"data/external/gecco2019"
    train=pd.read_csv(folder/"7_gecco2019_train_water_quality.csv").rename(columns={"Event":"EVENT"})
    valid=pd.read_csv(folder/"8_gecco2019_valid_water_qulity.csv").rename(columns={"Event":"EVENT"})
    test=pd.read_csv(folder/"6_gecco2019_test_water_quality.csv").rename(columns={"Event":"EVENT"})
    end=int(len(train)*.8);mid=len(valid)//2
    blocks=[train.iloc[end+GAP:].reset_index(drop=True),valid.iloc[GAP:mid].reset_index(drop=True),valid.iloc[mid+GAP:].reset_index(drop=True)]
    results+=run_case("2019_disclosed_final",train.iloc[:end].reset_index(drop=True),blocks,test,CHANNELS19,detector_class)
    write(OUT/"results.json",{"development_only":True,"all_candidates_tried":list(RECIPES),"results":results})


if __name__=="__main__":main()
