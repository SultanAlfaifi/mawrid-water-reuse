"""V6 development on disclosed GECCO only; never access a new source.

Reuse verified V5 past-trained baseline/q50 bundles to isolate the local-change
addition. Preserve the exact V5 train/cal/test geometry and120-row reset gap.
Save local scores, original components, every candidate and frozen selection.
"""
from pathlib import Path
import argparse,hashlib,json,shutil,sys,time
from datetime import datetime,timezone
import numpy as np
import pandas as pd
import joblib

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'ml/gecco_v5'))
from reproducible_explore import source_cases,compact
from calibration import predict as suppression_predict, calibrate as suppression_calibrate
from evaluation import compare_period,assess_series,gates
from local_change import LocalChangeScorer
from joint_calibration_v2 import calibrate,predict
from guarded_suppression import guarded_shape

OLD=ROOT/'output/ml/gecco-v5-supported-development'
GAP=120

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):Path(p).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
def now():return datetime.now(timezone.utc).isoformat()
def gap_score(model,frame):
    s=model.score_components(frame.iloc[GAP:].reset_index(drop=True))
    return {k:np.r_[np.full(min(GAP,len(frame)),np.nan),v] for k,v in s.items()}
def verify(plan):
    for path,digest in {**plan['code_sha256'],**plan['raw_sha256']}.items():
        if sha(ROOT/path)!=digest:raise RuntimeError('Code changed during run: '+path)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--limit-cases',type=int,default=13)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    paths=list(HERE.glob('*.py'))+[ROOT/'ml/gecco_v5'/n for n in ['calibration.py','evaluation.py','reproducible_explore.py','recovery_candidate.py','supported_candidate.py','normal_support.py']]+[ROOT/'ml/gecco_baseline/metrics.py',ROOT/'ml/gecco_v2/alarm_policy.py',ROOT/'ml/gecco_v2/candidates_supervised.py']
    raw=list((ROOT/'data/external/gecco2017').glob('*.csv'))+list((ROOT/'data/external/gecco2018').glob('*.csv'))+list((ROOT/'data/external/gecco2019').glob('*.csv'))
    plan={'created_at_utc':now(),'scope':'Already disclosed GECCO development. No fresh test claim.',
          'code_sha256':{str(p.relative_to(ROOT)):sha(p) for p in paths},
          'raw_sha256':{str(p.relative_to(ROOT)):sha(p) for p in raw},
          'selection':'Joint past-only rescue on baseline or locally guarded classifier suppression. All3 local normalized scores <=1 to permit suppression; persistence needs current evidence. All trials retained.',
          'gap_samples':GAP,'cadence_seconds':60,'limit_cases':args.limit_cases,
          'objective':'More original events with no loss of baseline IDs and fewer false alarms, stable across periods.'}
    for p in paths:
        dst=out/'source'/p.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
    write(out/'plan.json',plan)
    periods=[];source_parts={};decisions=[]
    for i,case in enumerate(source_cases()):
        if i>=args.limit_cases:break
        verify(plan);started=time.perf_counter();folder=out/case['name'];folder.mkdir()
        old=OLD/case['name'];oldfreeze=json.loads((old/'freeze.json').read_text())
        assert oldfreeze['train']==[0,len(case['train'])]
        assert oldfreeze['calibration_starts']==case['cal_starts']
        assert oldfreeze['test']==[case['test_start'],case['test_end']]
        cache_hashes={name:sha(old/name) for name in ['calibration_predictions.csv.gz','predictions.csv.gz']}
        bundlepath=old/'support_q50_bundle.joblib'
        if sha(bundlepath)!=oldfreeze['bundle_sha256']['support_q50']:raise RuntimeError('Old bundle hash mismatch')
        prior=joblib.load(bundlepath)
        assert prior['max_fit_source_index']==len(case['train'])-1
        assert prior['max_selection_source_index']==case['test_start']-1
        model=LocalChangeScorer(channels=case['channels']).fit(case['train'],case['train'].EVENT.to_numpy(bool))
        cal_saved=pd.read_csv(old/'calibration_predictions.csv.gz',float_precision='round_trip')
        np.testing.assert_array_equal(cal_saved.sample_index,np.arange(case['cal_starts'][0],case['test_start']))
        np.testing.assert_array_equal(cal_saved.EVENT,np.concatenate([p.EVENT for p in case['cal']]))
        lens=[len(p) for p in case['cal']];bounds=np.r_[0,np.cumsum(lens)]
        if case['continuous_cal']:
            whole=gap_score(model,pd.concat(case['cal'],ignore_index=True))
            cal_scores=[{k:v[a:b] for k,v in whole.items()} for a,b in zip(bounds[:-1],bounds[1:])]
        else:cal_scores=[gap_score(model,p) for p in case['cal']]
        blocks=[];cal_rows=[]
        for j,(a,b) in enumerate(zip(bounds[:-1],bounds[1:])):
            saved=cal_saved.iloc[a:b];base=saved.baseline_prediction.to_numpy(np.int8)
            seed=base.copy()
            scores={**cal_scores[j],'shape_raw':saved.support_q50__shape_raw.to_numpy()}
            blocks.append(dict(labels=case['cal'][j].EVENT.to_numpy(bool),baseline=base,guarded=seed,
                scores=scores,source_start=int(case['cal_starts'][j])))
            cal_rows.append(pd.DataFrame({'sample_index':saved.sample_index,'EVENT':saved.EVENT,'baseline':base,'guarded':seed,**scores}))
        guard_blocks=[{'labels':b['labels'],'scores':guarded_shape(b['scores'],b['scores']['shape_raw']),
                       'baseline_predictions':b['baseline'],'source_start':b['source_start']} for b in blocks]
        guard_selected,guard_trials=suppression_calibrate(guard_blocks)
        pd.DataFrame(guard_trials).to_csv(folder/'suppression_calibration_trials.csv.gz',index=False)
        for j,b in enumerate(blocks):
            b['guarded']=suppression_predict(guard_blocks[j]['scores'],b['baseline'],guard_selected)
            cal_rows[j]['guarded']=b['guarded']
            cal_rows[j]['guarded_shape']=guard_blocks[j]['scores']
        selected,trials=calibrate(blocks)
        pd.concat(cal_rows,ignore_index=True).to_csv(folder/'calibration_scores.csv.gz',index=False)
        pd.DataFrame(trials).to_csv(folder/'calibration_trials.csv.gz',index=False)
        joblib.dump({'local_model':model,'prior_bundle':prior,'selected':selected,'guard_selected':guard_selected,'sample_seconds':60,
                     'max_fit_index':len(case['train'])-1,'max_calibration_index':case['test_start']-1},folder/'bundle.joblib',compress=3)
        verify(plan)
        frozen={'frozen_at_utc':now(),'development_only':True,'plan_sha256':sha(out/'plan.json'),
                'prior_bundle_sha256':sha(bundlepath),'cached_score_sha256':cache_hashes,'prior_freeze_sha256':sha(old/'freeze.json'),
                'train':[0,len(case['train'])],'calibration_starts':case['cal_starts'],
                'test':[case['test_start'],case['test_end']],'selected':selected,'guard_selected':guard_selected,'bundle_sha256':sha(folder/'bundle.joblib')}
        write(folder/'freeze.json',frozen)
        test=case['load_test']();scores=gap_score(model,test)
        saved=pd.read_csv(old/'predictions.csv.gz',float_precision='round_trip')
        np.testing.assert_array_equal(saved.sample_index,np.arange(case['test_start'],case['test_end']))
        np.testing.assert_array_equal(test.EVENT,saved.EVENT)
        for name,digest in cache_hashes.items():
            if sha(old/name)!=digest:raise RuntimeError('Cached baseline scores changed')
        scores['shape_raw']=saved.support_q50__shape_raw.to_numpy()
        base=saved.baseline.to_numpy(np.int8)
        seed=suppression_predict(guarded_shape(scores,scores['shape_raw']),base,guard_selected)
        prediction=predict(base,seed,scores,selected)
        result=compare_period(test.EVENT.to_numpy(bool),base,prediction,60)
        result['selection']=selected;result['development_only']=True
        data={'sample_index':saved.sample_index.to_numpy(),'EVENT':test.EVENT.to_numpy(bool),'baseline':base,'guarded':seed,'candidate':prediction,**scores}
        pd.DataFrame(data).to_csv(folder/'predictions.csv.gz',index=False);write(folder/'results.json',result)
        periods.append(result);source_parts.setdefault(case['source'],[]).append(data);decisions.append({'case':case['name'],'selection':selected})
        print(json.dumps({'case':case['name'],'rescue':selected['rescue'],'seed':selected['seed'],
             'events':[result[n]['confirmed_new_alarm_inside_events'] for n in ['baseline','candidate']],
             'false_runs':[result[n]['false_positive_runs'] for n in ['baseline','candidate']],
             'lost':len(result['lost_baseline_events']),'noninferior':result['noninferior'],
             'seconds':round(time.perf_counter()-started,2)}),flush=True)
    pooled=[];sources={}
    for source,parts in source_parts.items():
        data={k:np.concatenate([p[k] for p in parts]) for k in parts[0]}
        if not np.all(np.diff(data['sample_index'])==1):raise ValueError('Nonadjacent source periods')
        bounds=np.r_[0,np.cumsum([len(p['EVENT']) for p in parts])].tolist()
        result=assess_series(data['EVENT'],data['baseline'],data['candidate'],bounds,60)
        sources[source]=compact(result);pooled.append(result['pooled'])
    verify(plan)
    overall=gates(periods,pooled)
    new_events=overall['totals']['candidate']['confirmed_new_alarm_inside_events']>overall['totals']['baseline']['confirmed_new_alarm_inside_events']
    gain_periods=sum(bool(p['newly_detected_events']) for p in periods)
    reduction_periods=sum(p['candidate']['false_positive_runs']<p['baseline']['false_positive_runs'] for p in periods)
    no_delay=all(d['extra_delay_minutes']<=0 for p in periods+pooled for d in p['paired_detection_delays'])
    v6_acceptance={'strictly_more_global_events':new_events,'event_gain_periods':gain_periods,
                   'false_run_reduction_periods':reduction_periods,'no_added_detection_delay':no_delay,
                   'minimum_gain_periods':2,'minimum_false_run_reduction_periods':2,
                   'passes_development_requirements':bool(overall['stable_joint_improvement'] and new_events and gain_periods>=2 and reduction_periods>=2 and no_delay),
                   'fresh_validation_complete':False,'deployment_approved':False}
    write(out/'results.json',{'created_at_utc':now(),'development_only':True,'completed_cases':len(periods),
                            'overall':overall,'v6_acceptance':v6_acceptance,'sources':sources,'decisions':decisions})
    print(json.dumps({'completed':True,'overall':overall,'v6_acceptance':v6_acceptance}),flush=True)
if __name__=='__main__':main()
