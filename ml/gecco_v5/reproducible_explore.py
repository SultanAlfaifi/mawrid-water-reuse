"""Preserved V5 support-gate development on the three already disclosed sources.

This runner saves executable snapshots, fitted bundles and calibration scores.
It never accesses the reserved Eawag source. A changed executable aborts the run.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import joblib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'ml/gecco_v2'))
from alarm_policy import select,predict as baseline_predict
from calibration import calibrate,predict
from evaluation import compare_period,assess_series,gates
from recovery_candidate import CHANNELS18,CHANNELS19

GAP=120
def now():return datetime.now(timezone.utc).isoformat()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
def compact(obj):
    if isinstance(obj,dict):return {k:compact(v) for k,v in obj.items() if k not in ('event_records','false_alarm_records')}
    if isinstance(obj,list):return [compact(v) for v in obj]
    return obj


def method_paths():
    names=['reproducible_explore.py','recovery_candidate.py','supported_candidate.py','normal_support.py',
           'calibration.py','evaluation.py','runtime.py']
    return [HERE/n for n in names]+[ROOT/'ml/gecco_baseline/metrics.py',ROOT/'ml/gecco_v2/alarm_policy.py',ROOT/'ml/gecco_v2/candidates_supervised.py']


def verify_code(plan):
    for name,digest in plan['code_sha256'].items():
        if sha(ROOT/name)!=digest:raise RuntimeError(f'Executable changed during development: {name}')


def score_gap(model,frame):
    tail=model.score_components(frame.iloc[GAP:].reset_index(drop=True))
    return {key:np.r_[np.full(min(GAP,len(frame)),np.nan),values] for key,values in tail.items()}


def source_cases():
    for year,n in [('2017',122334),('2018',139566)]:
        raw=ROOT/f'data/external/gecco{year}/1_gecco{year}_water_quality.csv'
        for k in range(4,10):
            train_end,test_start,test_end=[n*p//10 for p in (k-2,k,k+1)]
            prefix=pd.read_csv(raw,nrows=test_start)
            bounds=np.linspace(train_end,test_start,5,dtype=int)
            yield {'name':f'{year}_fold_{k-3}','source':year,
                'train':prefix.iloc[:train_end].reset_index(drop=True),
                'cal':[prefix.iloc[a:b].reset_index(drop=True) for a,b in zip(bounds[:-1],bounds[1:])],
                'cal_starts':bounds[:-1].tolist(),'test_start':test_start,'test_end':test_end,
                'load_test':lambda path=raw,a=test_start,b=test_end:pd.read_csv(path,nrows=b).iloc[a:].reset_index(drop=True),
                'channels':CHANNELS18,'continuous_cal':False,
                'reference':ROOT/'output/ml/gecco-v4'/('external_2017' if year=='2017' else 'development_2018')/f'fold_{k-3}'}
    raw=ROOT/'data/external/gecco2019'
    train=pd.read_csv(raw/'7_gecco2019_train_water_quality.csv').rename(columns={'Event':'EVENT'})
    valid=pd.read_csv(raw/'8_gecco2019_valid_water_qulity.csv').rename(columns={'Event':'EVENT'})
    bounds=np.linspace(0,len(valid),5,dtype=int)
    yield {'name':'2019_disclosed_test','source':'2019','train':train,
        'cal':[valid.iloc[a:b].reset_index(drop=True) for a,b in zip(bounds[:-1],bounds[1:])],
        'cal_starts':(bounds[:-1]+len(train)).tolist(),'test_start':len(train)+len(valid),'test_end':len(train)+len(valid)+31650,
        'load_test':lambda:pd.read_csv(raw/'6_gecco2019_test_water_quality.csv').rename(columns={'Event':'EVENT'}),
        'channels':CHANNELS19,'continuous_cal':True,'reference':ROOT/'output/ml/gecco-v3/external_2019'}


def run_case(out,case,configs,factory,plan):
    verify_code(plan)
    folder=out/case['name'];folder.mkdir()
    start=time.perf_counter();models={};selected={};all_cal={};base_choice=None
    labels=[part.EVENT.to_numpy(bool) for part in case['cal']]
    cal_output={'sample_index':np.arange(case['cal_starts'][0],case['test_start']),
                'EVENT':np.concatenate(labels)}
    for config in configs:
        model=factory(config,case['channels']).fit(case['train'],case['train'].EVENT.to_numpy(bool))
        models[config]=model
        if case['continuous_cal']:
            whole=score_gap(model,pd.concat(case['cal'],ignore_index=True))
            bounds=np.r_[0,np.cumsum([len(p) for p in case['cal']])]
            scores=[{key:value[a:b] for key,value in whole.items()} for a,b in zip(bounds[:-1],bounds[1:])]
        else:scores=[score_gap(model,part) for part in case['cal']]
        all_cal[config]=scores
        base_scores=np.concatenate([p['baseline'] for p in scores])
        if base_choice is None:
            base_choice,base_trials=select(np.concatenate(labels),base_scores,baseline=True)
            baseline_parts=[baseline_predict(p['baseline'],base_choice['threshold'],'instant') for p in scores]
            cal_output['baseline_score']=base_scores
            cal_output['baseline_prediction']=np.concatenate(baseline_parts)
            pd.DataFrame(base_trials).to_csv(folder/'baseline_calibration_trials.csv.gz',index=False)
        else:np.testing.assert_array_equal(base_scores,cal_output['baseline_score'])
        blocks=[{'labels':y,'scores':s['shape'],'baseline_predictions':b,'source_start':int(a),'block_id':f'cal_{i+1}'}
                for i,(y,s,b,a) in enumerate(zip(labels,scores,baseline_parts,case['cal_starts']))]
        chosen,trials=calibrate(blocks,cadence_seconds=60)
        selected[config]=chosen
        for key in scores[0]:
            if key!='baseline':cal_output[config+'__'+key]=np.concatenate([s[key] for s in scores])
        pd.DataFrame(trials).to_csv(folder/(config+'_calibration_trials.csv.gz'),index=False)
        bundle={'model':model,'selected':chosen,'baseline_threshold':base_choice['threshold'],
                'baseline_policy':'instant','channels':case['channels'],'sample_seconds':60,
                'max_fit_source_index':len(case['train'])-1,'max_selection_source_index':case['test_start']-1}
        joblib.dump(bundle,folder/(config+'_bundle.joblib'),compress=3)
        print(json.dumps({'case':case['name'],'stage':'calibrated','recipe':config,'decision':chosen['decision'],
            'status':chosen['status'],'elapsed_seconds':time.perf_counter()-start}),flush=True)
    reference=case['reference']
    if case['continuous_cal']:
        ref=np.r_[np.full(GAP,np.nan),pd.read_csv(reference/'baseline_calibration_predictions.csv.gz')['score'].to_numpy()]
    else:ref=pd.read_csv(reference/'calibration_predictions.csv.gz')['baseline_score'].to_numpy()
    np.testing.assert_allclose(cal_output['baseline_score'],ref,rtol=0,atol=1e-12,equal_nan=True)
    pd.DataFrame(cal_output).to_csv(folder/'calibration_predictions.csv.gz',index=False)
    verify_code(plan)
    frozen={'frozen_at_utc':now(),'development_only':True,'plan_sha256':sha(out/'plan.json'),
        'train':[0,len(case['train'])],'calibration_starts':case['cal_starts'],'test':[case['test_start'],case['test_end']],
        'baseline':base_choice,'selected':selected,'code_sha256':plan['code_sha256'],
        'bundle_sha256':{config:sha(folder/(config+'_bundle.joblib')) for config in configs}}
    write(folder/'freeze.json',frozen)
    test=case['load_test']();y=test.EVENT.to_numpy(bool)
    ref=pd.read_csv(reference/'test_predictions.csv.gz')
    predictions={'sample_index':np.arange(case['test_start'],case['test_end']),'EVENT':y}
    results={}
    for config,model in models.items():
        scores=score_gap(model,test)
        base=baseline_predict(scores['baseline'],base_choice['threshold'],'instant')
        candidate=predict(scores['shape'],base,selected[config])
        np.testing.assert_allclose(scores['baseline'],ref.baseline_score.to_numpy(),rtol=0,atol=1e-12,equal_nan=True)
        np.testing.assert_array_equal(base,ref.baseline_prediction.to_numpy())
        result=compare_period(y,base,candidate,60)
        result.update({'development_only':True,'selection':selected[config],'baseline_parity':True})
        results[config]=result;predictions['baseline']=base;predictions[config]=candidate
        for key,values in scores.items():predictions[config+'__'+key]=values
        b,c=result['baseline'],result['candidate']
        print(json.dumps({'case':case['name'],'recipe':config,'events':[b['confirmed_new_alarm_inside_events'],c['confirmed_new_alarm_inside_events']],
            'FPday':[b['false_alarm_runs_per_normal_day'],c['false_alarm_runs_per_normal_day']],
            'lost':len(result['lost_baseline_events']),'noninferior':result['noninferior']}),flush=True)
    verify_code(plan)
    pd.DataFrame(predictions).to_csv(folder/'predictions.csv.gz',index=False)
    write(folder/'results.json',results)
    return results,predictions


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit-cases',type=int,default=13)
    args=parser.parse_args()
    from supported_candidate import SupportedRecoveryDetector,CONFIGS
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    paths=method_paths();hashes={str(p.relative_to(ROOT)):sha(p) for p in paths}
    plan={'created_at_utc':now(),'scope':'Disclosed development only; no reserved source access',
        'recipes':CONFIGS,'limit_cases':args.limit_cases,'gap_samples':GAP,'sample_seconds':60,
        'geometry':'Same fixed past train/cal/test geometry and original baseline scores as initial V5 development',
        'code_sha256':hashes,'all_case_outcomes_retained':True}
    for path in paths:
        target=out/'source'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    write(out/'plan.json',plan)
    periods={config:[] for config in CONFIGS};by_source={}
    for index,case in enumerate(source_cases()):
        if index>=args.limit_cases:break
        results,pred=run_case(out,case,CONFIGS,SupportedRecoveryDetector,plan)
        by_source.setdefault(case['source'],[]).append(pred)
        for config in CONFIGS:periods[config].append(results[config])
    pooled={config:[] for config in CONFIGS};source_results={}
    for source,parts in by_source.items():
        combined={key:np.concatenate([p[key] for p in parts]) for key in parts[0]}
        assert np.all(np.diff(combined['sample_index'])==1)
        bounds=np.r_[0,np.cumsum([len(p['EVENT']) for p in parts])].tolist()
        source_results[source]={}
        for config in CONFIGS:
            result=assess_series(combined['EVENT'],combined['baseline'],combined[config],bounds,60)
            source_results[source][config]=compact(result);pooled[config].append(result['pooled'])
    result={'development_only':True,'completed_at_utc':now(),'complete_13_cases':args.limit_cases==13,
            'overall':{config:gates(periods[config],pooled[config]) for config in CONFIGS},'sources':source_results}
    write(out/'results.json',result)
    print(json.dumps({'completed':True,'overall':result['overall']}),flush=True)

if __name__=='__main__':main()
