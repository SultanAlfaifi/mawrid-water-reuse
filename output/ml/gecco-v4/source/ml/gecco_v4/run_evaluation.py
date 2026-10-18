"""Locked historical external evaluation, with prefix-only model selection.

Development is disclosed. This runner cannot freeze a recipe implicitly and
prints progress without outer metrics until every declared fold is complete.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'ml/gecco_baseline'))
sys.path.insert(0, str(ROOT / 'ml/gecco_v2'))
from metrics import evaluate
from alarm_policy import predict, select
from candidates_supervised import build_features

CHANNELS = ['Tp', 'Cl', 'pH', 'Redox', 'Leit', 'Trueb', 'Cl_2', 'Fm', 'Fm_2']
GAP = 120
SOURCES = {
    '2017': ROOT / 'data/external/gecco2017/1_gecco2017_water_quality.csv',
    '2018': ROOT / 'data/external/gecco2018/1_gecco2018_water_quality.csv',
}

def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
def compact(result): return {k:v for k,v in result.items() if not k.endswith('records')}

def method_files(family):
    paths = [HERE / f for f in ['run_evaluation.py', 'predict.py', 'supervised_explore.py',
                               'supervised_candidate.py', 'evaluation_contract.json']]
    if family == 'adaptive': paths += [HERE / 'adaptive_candidate.py']
    paths += [ROOT / 'ml/gecco_baseline/metrics.py',
              ROOT / 'ml/gecco_v2/alarm_policy.py',
              ROOT / 'ml/gecco_v2/candidates_supervised.py']
    return paths

def declare(out, family, recipe):
    assert not (out / 'protocol.json').exists(), 'Never replace a frozen protocol'
    contract = json.loads((HERE / 'evaluation_contract.json').read_text())
    assert sha(SOURCES['2017']) == contract['new_source_sha256']
    # Read timestamps only to count rows. No EVENT access before declaration.
    count = len(pd.read_csv(SOURCES['2017'], usecols=['Time']))
    assert count == contract['new_source_rows']
    protocol = {
        'frozen_at_utc': now(), 'family': family, 'recipe': recipe,
        'source_file': str(SOURCES['2017'].relative_to(ROOT)), 'source_rows': count,
        'source_sha256': sha(SOURCES['2017']), 'contract': contract,
        'development_source_sha256': {str(SOURCES['2018'].relative_to(ROOT)):sha(SOURCES['2018'])},
        'code_sha256': {str(p.relative_to(ROOT)):sha(p) for p in method_files(family)},
        'fold_geometry': 'k=4..9; train[0,floor(N*(k-2)/10)); calibration previous20% in four contiguous5% blocks; test next10%. Each cal/test block first120 unavailable, then reset features.',
        'calibration': 'supervised_explore.calibrate: <=1 FP run/day and <=1% normal alarm duration in EVERY past block. Rank worst complete-event block recall, pooled confirmed complete-event recall, point F1, fewer FP minutes, higher threshold. No-event blocks still constrain false alarms; no-event overall chooses high no-alarm threshold through same conservative ranking.',
        'baseline_calibration': 'Original v1 instant F1 selector on all four past calibration blocks reassembled on original axis, with unavailable gaps retained.',
        'new_source_event_values_read_before_freeze': False,
        'selected_from': 'Previously disclosed GECCO2018 and GECCO2019 development only',
        'new_source_review': 'All six folds must complete before any outer metrics are reviewed. No model-family changes after new-source labels are accessed.',
        'one_class': 'Adaptive uses normal-only fitting. Supervised fit must return explicitly unavailable if eligible labels contain one class; no unplanned family switching.',
        'output_semantics': '-1 unavailable;0 no model alarm;1 alarm. Never authorizes a valve opening.'
    }
    write(out / 'protocol.json', protocol)
    print('METHOD_FROZEN '+sha(out / 'protocol.json'), flush=True)

def check(out):
    protocol = json.loads((out / 'protocol.json').read_text())
    assert sha(SOURCES['2017']) == protocol['source_sha256']
    for name, digest in protocol['code_sha256'].items():
        assert sha(ROOT / name) == digest, f'Frozen executable changed: {name}'
    return protocol

def candidate(protocol):
    if protocol['family'] == 'adaptive':
        from adaptive_candidate import AdaptiveChangeDetector
        return AdaptiveChangeDetector(protocol['recipe'], CHANNELS)
    from supervised_candidate import FixedRelativeContextDetector
    return FixedRelativeContextDetector(CHANNELS, protocol['recipe'])

def fit_baseline(train):
    features, valid, _ = build_features(train[CHANNELS], 'baseline15', CHANNELS)
    normal = pd.Series(train.EVENT.to_numpy(dtype=bool)).rolling(15, min_periods=15).sum().eq(0).to_numpy()
    model = IsolationForest(n_estimators=200, max_samples=256, contamination='auto', n_jobs=1, random_state=20261016)
    assert (valid & normal).sum() >= 256
    model.fit(features[valid & normal])
    return model

def score_baseline(model, frame):
    features, valid, _ = build_features(frame[CHANNELS], 'baseline15', CHANNELS)
    scores = np.full(len(frame), np.nan)
    if valid.any(): scores[valid] = -model.score_samples(features[valid])
    return scores

def score_with_gap(model, frame, baseline=False):
    raw = frame.iloc[GAP:].loc[:, CHANNELS].reset_index(drop=True)
    after = score_baseline(model, raw) if baseline else model.score(raw)
    assert len(after) == len(raw)
    return np.r_[np.full(min(GAP,len(frame)),np.nan),after]

def assess(labels, predictions):
    common = np.logical_and.reduce([p >= 0 for p in predictions.values()])
    return {'native': {r:evaluate(labels,p) for r,p in predictions.items()},
            'common': {r:evaluate(labels,np.where(common,p,-1)) for r,p in predictions.items()}}

def gates(result, folds):
    b, v = result['common']['baseline'], result['common']['v4']
    def ratios_available(*parts):
        return all(p[key] is not None for p in parts for key in
                   ['false_alarm_runs_per_normal_day','normal_time_under_alarm'])
    def noninferior(part):
        a,c = part['common']['baseline'],part['common']['v4']
        return (ratios_available(a,c) and c['confirmed_new_alarm_inside_events'] >= a['confirmed_new_alarm_inside_events']
            and c['false_alarm_runs_per_normal_day'] <= a['false_alarm_runs_per_normal_day']
            and c['normal_time_under_alarm'] <= a['normal_time_under_alarm'])
    pooled = (ratios_available(b,v) and v['confirmed_new_alarm_inside_events'] > b['confirmed_new_alarm_inside_events']
        and v['false_alarm_runs_per_normal_day'] < b['false_alarm_runs_per_normal_day']
        and v['normal_time_under_alarm'] <= b['normal_time_under_alarm'])
    per_fold = [noninferior(f) for f in folds]
    budgets = [ratios_available(f['native']['v4']) and f['native']['v4']['false_alarm_runs_per_normal_day'] <= 1
               and f['native']['v4']['normal_time_under_alarm'] <= .01 for f in folds]
    return {'pooled_joint_improvement': pooled, 'noninferior_periods':per_fold,
            'noninferior_period_count':sum(per_fold),
            'stable_joint_improvement': pooled and all(per_fold),
            'operating_budget_pass_per_period':budgets,
            'all_period_operating_budget_pass':all(budgets), '3d_connected':False}

def run(out, source_id):
    protocol = check(out)
    from supervised_explore import calibrate
    source = SOURCES[source_id]
    count = len(pd.read_csv(source, usecols=['Time']))
    run_dir = out / ('external_2017' if source_id == '2017' else 'development_2018')
    run_dir.mkdir(parents=True, exist_ok=True)
    assert not (run_dir / 'results.json').exists(), 'Preserve completed evaluation'
    access_log = run_dir / 'label_access_started.json'
    if not access_log.exists():
        write(access_log, {'at_utc':now(), 'protocol_sha256':sha(out/'protocol.json'),
                          'source_sha256':sha(source), 'source_id':source_id,
                          'first_read': 'prefix through first calibration end only'})
    for k in range(4,10):
        folder = run_dir / f'fold_{k-3}'
        folder.mkdir(exist_ok=True)
        if (folder/'test_results.json').exists():
            frozen=json.loads((folder/'freeze.json').read_text())
            assert frozen['protocol_sha256']==sha(out/'protocol.json')
            for r,d in frozen['model_sha256'].items(): assert sha(folder/f'{r}_model.joblib')==d
            continue
        train_end, test_start, test_end = [count*j//10 for j in [k-2,k,k+1]]
        bounds = np.linspace(train_end,test_start,5,dtype=int)
        if not (folder/'freeze.json').exists():
            # Only past prefix labels are loaded while choosing models/thresholds.
            prefix=pd.read_csv(source,nrows=test_start)
            assert len(prefix)==test_start
            train=prefix.iloc[:train_end].reset_index(drop=True)
            blocks=[prefix.iloc[a:b].reset_index(drop=True) for a,b in zip(bounds[:-1],bounds[1:])]
            started=time.perf_counter()
            models={'baseline':fit_baseline(train),
                    'v4':candidate(protocol).fit(train[CHANNELS],train.EVENT.to_numpy(dtype=bool))}
            cal={r:[score_with_gap(m,block,baseline=(r=='baseline')) for block in blocks] for r,m in models.items()}
            labels=[block.EVENT.to_numpy(dtype=bool) for block in blocks]
            selected={}
            selected['baseline'],base_trials=select(np.concatenate(labels),np.concatenate(cal['baseline']),baseline=True)
            if not any(np.isfinite(s).any() for s in cal['v4']):
                selected['v4']={'threshold':1.,'policy':'instant','unavailable_reason':'one_class_or_no_valid_calibration'}
                v4_trials=[]
            else:
                selected['v4'],v4_trials=calibrate(list(zip(labels,cal['v4'])))
            for r,trials in [('baseline',base_trials),('v4',v4_trials)]:
                pd.DataFrame(trials).to_csv(folder/f'{r}_calibration_trials.csv.gz',index=False)
                bundle={'model':models[r],'family':r if r=='baseline' else protocol['family'],
                        'recipe':protocol['recipe'],'channels':CHANNELS,
                        'threshold':selected[r]['threshold'],'policy':selected[r]['policy'],
                        'max_training_source_index':train_end-1,'max_selection_source_index':test_start-1}
                joblib.dump(bundle,folder/f'{r}_model.joblib',compress=3)
            cal_frame=pd.DataFrame({'sample_index':np.arange(train_end,test_start),'EVENT':np.concatenate(labels),
                                   'baseline_score':np.concatenate(cal['baseline']),'v4_score':np.concatenate(cal['v4'])})
            cal_frame.to_csv(folder/'calibration_predictions.csv.gz',index=False)
            write(folder/'freeze.json',{'frozen_at_utc':now(),'protocol_sha256':sha(out/'protocol.json'),
                'source_id':source_id,'train':[0,train_end], 'calibration_blocks':[[int(a),int(b)] for a,b in zip(bounds[:-1],bounds[1:])],
                'test':[test_start,test_end],'selected':selected,'fit_seconds':time.perf_counter()-started,
                'model_sha256':{r:sha(folder/f'{r}_model.joblib') for r in models}})
        frozen=json.loads((folder/'freeze.json').read_text())
        assert frozen['protocol_sha256']==sha(out/'protocol.json')
        bundles={}
        for r,d in frozen['model_sha256'].items():
            assert sha(folder/f'{r}_model.joblib')==d
            bundles[r]=joblib.load(folder/f'{r}_model.joblib')
        # First outer label access for this period follows its immutable freeze.
        part=pd.read_csv(source,nrows=test_end).iloc[test_start:].reset_index(drop=True)
        scores={r:score_with_gap(b['model'],part,baseline=(r=='baseline')) for r,b in bundles.items()}
        predictions={r:predict(scores[r],b['threshold'],b['policy']) for r,b in bundles.items()}
        labels=part.EVENT.to_numpy(dtype=bool)
        result=assess(labels,predictions)
        result.update({'scored_at_utc':now(),'test':[test_start,test_end],
                       'excluded_gap_event_minutes':int(labels[:GAP].sum()),
                       'raw_incomplete_event_minutes':int((part[CHANNELS].isna().any(axis=1).to_numpy()&labels).sum())})
        frame=pd.DataFrame({'sample_index':np.arange(test_start,test_end),'timestamp_original':part.Time,
                            'EVENT':labels,**{r+'_score':s for r,s in scores.items()},
                            **{r+'_prediction':p for r,p in predictions.items()}})
        frame.to_csv(folder/'test_predictions.csv.gz',index=False)
        write(folder/'test_results.json',result)
        print(f'PERIOD_{k-3}_FROZEN_AND_SCORED_NO_METRICS_DISCLOSED',flush=True)
    parts=[pd.read_csv(run_dir/f'fold_{j}/test_predictions.csv.gz') for j in range(1,7)]
    combined=pd.concat(parts,ignore_index=True)
    assert np.array_equal(combined.sample_index,np.arange(count*4//10,count))
    result=assess(combined.EVENT.to_numpy(dtype=bool),{r:combined[r+'_prediction'].to_numpy(dtype=np.int8) for r in ['baseline','v4']})
    folds=[json.loads((run_dir/f'fold_{j}/test_results.json').read_text()) for j in range(1,7)]
    result.update({'completed_at_utc':now(),'scope':'new external historical check' if source_id=='2017' else 'disclosed development',
                   'protocol_sha256':sha(out/'protocol.json'),'folds':folds,'gates':gates(result,folds)})
    combined.to_csv(run_dir/'predictions.csv.gz',index=False)
    write(run_dir/'results.json',result)
    print('ALL_SIX_PERIODS_COMPLETE_RESULTS_MAY_NOW_BE_REVIEWED',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['declare','2017','2018'])
    parser.add_argument('--output-dir',type=Path,default=ROOT/'output/ml/gecco-v4')
    parser.add_argument('--family',choices=['adaptive','supervised'])
    parser.add_argument('--recipe')
    args=parser.parse_args()
    if args.stage=='declare':
        assert args.family and args.recipe
        declare(args.output_dir,args.family,args.recipe)
    else: run(args.output_dir,args.stage)
