"""One-shot fixed-method evaluation; no tuning from fresh outer outcomes.

Only the four declared M/Phase1 series are parsed. Outer metrics are withheld
from stdout until all 24 fits finish. Later folds may learn their own past as
predeclared expanding-window evaluation; no future labels enter fitting.
"""
from __future__ import annotations
import argparse
import json
import importlib.metadata
import platform
from pathlib import Path
import shutil
import time
import joblib
import numpy as np
import pandas as pd
from baseline_cadence import select_baseline, predict as baseline_predict
from calibration import predict
from evaluation import gates
from sparse_calibration import calibrate_sparse
from sparse_evaluation import compare_sparse, assess_sparse_series
from supported_candidate import SupportedRecoveryDetector
from ponds_data import CHANNELS, DEFAULT_COHORTS, read_selected_cohorts
from provenance import declare_protocol, check_protocol, begin_first_access, sha256, now

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
CADENCE=900; GAP=8; RECIPE='support_q50'
ARCHIVE=ROOT/'data/external/new_holdout_candidate/eawag_ponds_active_learning/AL_Repo.zip'

def write(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def compact(obj):
    if isinstance(obj,dict):return {k:compact(v) for k,v in obj.items() if k not in ('event_records','false_alarm_records')}
    if isinstance(obj,list):return [compact(v) for v in obj]
    return obj

def code_paths():
    names=['ponds_frozen_evaluation.py','ponds_data.py','baseline_cadence.py','sparse_calibration.py',
        'sparse_evaluation.py','provenance.py','recovery_candidate.py','supported_candidate.py',
        'normal_support.py','calibration.py','evaluation.py','runtime.py']
    return [HERE/name for name in names]+[ROOT/'ml/gecco_baseline/metrics.py',
        ROOT/'ml/gecco_v2/alarm_policy.py',ROOT/'ml/gecco_v2/candidates_supervised.py']

def configuration():
    return {'method':RECIPE,'selected_using':'13 already disclosed GECCO periods; q50 retains73/104 baseline events, FP236->228. q95 loses10 events and is rejected.',
        'environment':{'python':platform.python_version(),'platform':platform.platform(),
            'packages':{name:importlib.metadata.version(name) for name in ['numpy','pandas','scipy','scikit-learn','joblib','threadpoolctl']}},
        'source_doi':'10.25678/00023Y','cohorts':[list(p) for p in DEFAULT_COHORTS],
        'filter':{'Treatment':'M','Phase':'1'},'expected_grid_rows_per_cohort':22752,
        'sample_seconds':CADENCE,'gap_samples':GAP,'gap_minutes':120,
        'geometry':'For k=4..9: train [0,floor(N*(k-2)/10)), calibration next20% divided into4 adjacent blocks, test next10%. No random split. Reset feature context after8-slot gap in each cal/test block.',
        'local_refit':'Identical fixed method refits only on each local past prefix; this is not zero-shot transfer of GECCO weights.',
        'features':CHANNELS,'lookbacks_samples':[15,60],'lookbacks_minutes':[225,900],
        'labels':'Original observed conductivity finite and expert-cleaned conductivity missing; other anomaly types unlabelled.',
        'missing':'Original missing target becomes all-channel unavailable. Inserted grid slots are unavailable; never interpolated. Original event IDs survive time gaps; a gap cannot confirm0->1.',
        'baseline':'Original200-tree IF with cadence-corrected original threshold grid/F1 ranking and1 false run/day,1% normal-alarm-time calibration constraints.',
        'baseline_trial_event_diagnostics':'Legacy baseline trial event counts use the full grid and may split an event at an inserted gap; only point F1 and false-alarm quantities affect baseline selection. Candidate calibration and all reported event results use original observed identities.',
        'no_calibration_evidence':'If no finite baseline calibration score or no normal exposure, use finite no-alarm threshold1.0000000000000002 (IF score is at most1), report unqualified; such periods cannot support release.',
        'candidate_calibration':'Existing default minimum1 normal day/block,2 observed blocks,4 normal days total,5 reference events across2 blocks; instant/2of3/3of5; preserve every reference event ID and normal exposure. Unknown support retains original IF.',
        'primary_acceptance':'Every one of24 periods must retain every baseline event ID and availability, with no higher false-run rate or normal alarm duration; strict pooled false-run reduction on original source axes.',
        'evidence_minimum':{'baseline_detected_events':5,'eventful_cohorts':2,'eventful_periods':2,'all_baseline_calibrations_qualified':True},
        'outcome_policy':'Run all24 before inspecting outer metrics. No changes based on fresh outcomes; failures retained. Future retuning would make these cohorts development data.',
        'prior_exposure':'Archive metadata, identity/time fields, headers and publisher source code reviewed; no selected sensor values or derived labels inspected. A qualitative published benchmark ranking was incidentally exposed, not used for model choice.',
        'upstream_limitation':'Publisher intermediate3.1 preprocessing provenance is incomplete. This establishes our own temporal isolation conditional on published inputs; end-to-end raw-instrument causality is unverified.',
        'scope':'Four series share one pond experiment,15-minute cadence; conductivity observation anomalies only. No MAWRID field efficacy, water safety probability, five physical fault classes, or3D/Pi performance claim.'}

def score_gap(model,frame):
    scored=model.score_components(frame.iloc[GAP:].reset_index(drop=True))
    return {k:np.r_[np.full(min(GAP,len(frame)),np.nan),v] for k,v in scored.items()}

def run_case(out,cohort,frame,k):
    check_protocol(ROOT,out)
    n=len(frame); train_end,start,end=[n*i//10 for i in (k-2,k,k+1)]
    name=f'{cohort[0]}_{cohort[1]}_fold_{k-3}';folder=out/name;folder.mkdir()
    begin=time.perf_counter(); train=frame.iloc[:train_end].reset_index(drop=True)
    bounds=np.linspace(train_end,start,5,dtype=int)
    parts=[frame.iloc[a:b].reset_index(drop=True) for a,b in zip(bounds[:-1],bounds[1:])]
    model=SupportedRecoveryDetector(RECIPE,CHANNELS).fit(train,train.EVENT.to_numpy(bool))
    scores=[score_gap(model,p) for p in parts]
    labels=np.concatenate([p.EVENT.to_numpy(bool) for p in parts])
    base_scores=np.concatenate([s['baseline'] for s in scores])
    try:
        base_choice,base_trials=select_baseline(labels,base_scores,CADENCE)
        baseline_qualified=True
    except ValueError as exc:
        if str(exc) not in ('calibration has no finite scores','no policy has sufficient normal exposure to establish constraints'):raise
        base_choice={'threshold':float(np.nextafter(1.,np.inf)),'policy':'instant','status':str(exc)}
        base_trials=[];baseline_qualified=False
    baseline_parts=[baseline_predict(s['baseline'],base_choice['threshold'],'instant') for s in scores]
    for part,base in zip(parts,baseline_parts):
        assert np.all(base[~part.label_available.to_numpy(bool)]==-1), 'Unknown targets cannot add normal calibration exposure'
    blocks=[{'labels':p.EVENT.to_numpy(bool),'scores':s['shape'],'baseline_predictions':b,
        'observed':p.row_observed.to_numpy(bool),'slots':p.slot.to_numpy(np.int64),
        'source_start':int(a),'block_id':f'cal_{i+1}'}
        for i,(p,s,b,a) in enumerate(zip(parts,scores,baseline_parts,bounds[:-1]))]
    chosen,trials=calibrate_sparse(blocks,cadence_seconds=CADENCE)
    bundle={'model':model,'selected':chosen,'baseline_threshold':base_choice['threshold'],
        'baseline_policy':'instant','channels':CHANNELS,'sample_seconds':CADENCE,
        'max_fit_source_index':train_end-1,'max_selection_source_index':start-1,
        'source_cohort':list(cohort),'baseline_calibration_qualified':baseline_qualified}
    joblib.dump(bundle,folder/'bundle.joblib',compress=3)
    cal=pd.concat(parts,ignore_index=True)[['slot','source_row','row_observed','label_available','EVENT']].copy()
    for key in scores[0]:cal[key+'_score']=np.concatenate([s[key] for s in scores])
    cal['baseline_prediction']=np.concatenate(baseline_parts)
    cal['prediction']=np.concatenate([predict(s['shape'],b,chosen) for s,b in zip(scores,baseline_parts)])
    cal.to_csv(folder/'calibration_predictions.csv.gz',index=False)
    write(folder/'baseline_trials.json',base_trials);write(folder/'candidate_trials.json',trials)
    check_protocol(ROOT,out)
    freeze={'frozen_at_utc':now(),'protocol_sha256':sha256(out/'protocol.json'),
        'train':[0,train_end],'calibration_boundaries':bounds.tolist(),'test':[start,end],
        'baseline':base_choice,'baseline_calibration_qualified':baseline_qualified,'selected':chosen,
        'model_fit_status':model.fit_status_,'baseline_fit_rows':model.baseline_fit_rows_,
        'bundle_sha256':sha256(folder/'bundle.joblib')}
    write(folder/'freeze.json',freeze)
    # This outer slice never enters model.fit, support.fit or calibrate.
    test=frame.iloc[start:end].reset_index(drop=True);s=score_gap(model,test)
    base=baseline_predict(s['baseline'],base_choice['threshold'],'instant')
    candidate=predict(s['shape'],base,chosen)
    unknown=~test.label_available.to_numpy(bool)
    assert np.all(base[unknown]==-1) and np.all(candidate[unknown]==-1), 'Unknown targets cannot add normal test exposure'
    pred=test[['slot','source_row','row_observed','label_available','EVENT']].copy()
    for key,value in s.items():pred[key+'_score']=value
    pred['baseline']=base;pred['candidate']=candidate
    pred.to_csv(folder/'predictions.csv.gz',index=False)
    observed=pred.loc[pred.row_observed].reset_index(drop=True)
    result=compare_sparse(observed.EVENT.to_numpy(bool),observed.baseline.to_numpy(np.int8),
        observed.candidate.to_numpy(np.int8),observed.slot.to_numpy(np.int64),CADENCE)
    result.update({'case':name,'baseline_calibration_qualified':baseline_qualified,
        'selection_status':chosen['status'],'selection_decision':chosen['decision']})
    write(folder/'results.json',result);check_protocol(ROOT,out)
    print(json.dumps({'completed_case':name,'elapsed_seconds':round(time.perf_counter()-begin,2),
        'outer_metrics':'withheld until all24 complete'}),flush=True)
    return result,observed

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    protocol=declare_protocol(ROOT,out,configuration(),code_paths(),[ARCHIVE])
    for relative in protocol['code']:
        target=out/'source'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,target)
    begin_first_access(ROOT,out)
    cohorts=read_selected_cohorts(ARCHIVE)
    if list(cohorts)!=DEFAULT_COHORTS or any(len(f)!=22752 for f in cohorts.values()):
        raise ValueError('Predeclared cohort/time geometry differs; preserve failed attempt')
    write(out/'adaptation.json',{'parsed_at_utc':now(),'cohorts':[
        {'cohort':list(key),'grid_rows':len(f),'original_rows':int(f.row_observed.sum()),
         'label_available_rows':int(f.label_available.sum())}
        for key,f in cohorts.items()], 'no_other_cohort_measurements_parsed':True})
    periods=[];pooled=[];source_results={};qualified=[]
    for cohort,frame in cohorts.items():
        parts=[]
        for k in range(4,10):
            result,pred=run_case(out,cohort,frame,k)
            periods.append(result);parts.append(pred);qualified.append(result['baseline_calibration_qualified'])
        combined=pd.concat(parts,ignore_index=True)
        bounds=np.r_[0,np.cumsum([len(p) for p in parts])].tolist()
        source=assess_sparse_series(combined.EVENT.to_numpy(bool),combined.baseline.to_numpy(np.int8),
            combined.candidate.to_numpy(np.int8),combined.slot.to_numpy(np.int64),bounds,CADENCE)
        source_results['_'.join(cohort)]=compact(source);pooled.append(source['pooled'])
    overall=gates(periods,pooled)
    evidence={'baseline_detected_events':overall['totals']['baseline']['confirmed_new_alarm_inside_events'],
        'eventful_cohorts':sum(p['baseline']['confirmed_new_alarm_inside_events']>0 for p in pooled),
        'eventful_periods':sum(p['baseline']['confirmed_new_alarm_inside_events']>0 for p in periods),
        'all_baseline_calibrations_qualified':all(qualified)}
    sufficient=(evidence['baseline_detected_events']>=5 and evidence['eventful_cohorts']>=2
        and evidence['eventful_periods']>=2 and all(qualified))
    result={'completed_at_utc':now(),'protocol_sha256':sha256(out/'protocol.json'),'completed_cases':len(periods),
        'overall':overall,'evidence':evidence,'sufficient_evidence':sufficient,
        'primary_acceptance_passed':bool(overall['stable_joint_improvement'] and sufficient),
        'sources':source_results,'periods':compact(periods),'scope':configuration()['scope'],
        'upstream_limitation':configuration()['upstream_limitation']}
    check_protocol(ROOT,out);write(out/'results.json',result)
    print(json.dumps({'all24_completed':True,'overall':overall,'evidence':evidence,
        'primary_acceptance_passed':result['primary_acceptance_passed']}),flush=True)

if __name__=='__main__':main()
