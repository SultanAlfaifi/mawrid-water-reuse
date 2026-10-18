"""One frozen policy replay on audited scores; no sensor/model fitting.

All19 calibration choices freeze before any test numeric array is opened.
The inherited model audit is explicit: this is not a new raw-sensor audit.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import numpy as np
import pandas as pd
from ml.gecco_v7 import development_v2 as prior
from ml.gecco_v7.recalibrate_delayed import assess, summarize
from ml.gecco_v15.calibration import calibrate
from ml.gecco_v15.runtime import predict

ROOT = Path(__file__).resolve().parents[2]
NAMES = ([f'{y}_fold_{i}' for y in ('2017', '2018') for i in range(1, 7)]
    + ['2019_disclosed_test', '2018-11', '2018-12', '2019-01', '2019-02', '2019-03', '2019-04'])
PROTOCOL = ROOT/'output/ml/gecco-v15-design/protocol.json'
PROTOCOL_SHA = '5bc11ea7154a29c9f2301d2d9d652c8d38887e908c5d6aeb9983a2e3a5ca0c66'
HISTORY = ['v8','v9','v10','v11','v12','v13','v14']
RESERVE = 1024**3
V14_AUDIT_SHA = '09ba31b89ccf58b66b9790fd822243d18d923e2364cd73da98dcd08a3a4b0f3b'
write, sha, now = prior.write, prior.sha, prior.now


def parent(version):
    return ROOT/f'output/ml/gecco-{version}-development/run_01'


def guard(out):
    if shutil.disk_usage(out).free < RESERVE:
        raise RuntimeError('Incomplete: preserve1GiB disk reserve; no evidence is deleted')


def verify(plan):
    for key in ('code_sha256','input_sha256'):
        for p,h in plan[key].items():
            if sha(ROOT/p) != h:
                raise ValueError('Frozen bytes changed: '+p)


def prepare(out):
    if sha(PROTOCOL) != PROTOCOL_SHA:
        raise ValueError('Design protocol changed')
    out.mkdir(parents=True, exist_ok=False); guard(out)
    # Freeze hashes without decoding the numeric calibration or test contents.
    preflight_path=ROOT/'output/ml/gecco-v15-design/preflight.json'
    preflight=json.loads(preflight_path.read_text())
    if preflight.get('passed') is not True or preflight.get('tests')!=68:
        raise ValueError('Passing complete synthetic preflight required before source access')
    for path,digest in preflight['code_sha256'].items():
        if sha(ROOT/path)!=digest:
            raise ValueError('Source changed after preflight: '+path)
    inputs = [PROTOCOL,preflight_path,ROOT/'output/ml/gecco-v15-design/preflight.log']
    lineage = {}
    if sha(parent('v14')/'audit.json') != V14_AUDIT_SHA:
        raise ValueError('Pinned V14 audit changed')
    anchor_audit=json.loads((parent('v14')/'audit.json').read_text())
    if sha(parent('v14')/'plan.json') != anchor_audit['hashes']['plan.json']:
        raise ValueError('Audited V14 plan changed')
    anchor_plan=json.loads((parent('v14')/'plan.json').read_text())
    for version in HISTORY:
        p = parent(version)
        if version!='v14':
            for filename in ('plan.json','results.json','audit.json'):
                path=str((p/filename).relative_to(ROOT))
                if sha(p/filename)!=anchor_plan['input_sha256'][path]:
                    raise ValueError('Historical audited lineage changed: '+path)
        r = json.loads((p/'results.json').read_text())
        a = json.loads((p/'audit.json').read_text())
        if r.get('complete_cases') != 19 or a.get('passed') is not True:
            raise ValueError('Complete audited history required: '+version)
        if [x['case'] for x in r['periods']]!=NAMES:
            raise ValueError('Original case identities/order changed: '+version)
        for filename in ('plan.json','results.json'):
            if sha(p/filename)!=a['hashes'][filename]:
                raise ValueError('Parent no longer matches independent audit: '+version+'/'+filename)
        inputs += [p/n for n in ('plan.json','results.json','audit.json')]
        if version in ('v8','v14'):
            lineage[version] = {'results_sha256':sha(p/'results.json'),'audit_sha256':sha(p/'audit.json')}
        for name in NAMES:
            artifacts=['predictions.csv.gz']
            if version in ('v8','v14'): artifacts+=['calibration_scores.csv.gz','freeze.json','bundle.joblib']
            for filename in artifacts:
                if sha(p/name/filename)!=a['hashes'][name+'/'+filename]:
                    raise ValueError('Parent artifact changed after audit: '+version+'/'+name+'/'+filename)
            inputs.append(p/name/'predictions.csv.gz')
            if version in ('v8','v14'):
                inputs += [p/name/n for n in ('calibration_scores.csv.gz','freeze.json','bundle.joblib')]
    inherited = json.loads((parent('v14')/'plan.json').read_text())['code_sha256']
    for path,digest in inherited.items():
        if sha(ROOT/path) != digest:
            raise ValueError('Inherited audited source changed: '+path)
    code = {str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'ml/gecco_v15').glob('*.py')}
    code = {**inherited, **code}
    plan = {'created_at_utc':now(),'version':'v15_joint_reference_bounded_recovery',
        'attempt':'v15_run01_frozen_score_policy_only','case_order':NAMES,'expected_cases':19,
        'development_only':True,'fresh_validation':False,'all_sources_previously_disclosed':True,
        'no_model_fit':True,'new_raw_sensor_replay':False,'inherited_model_audit':lineage,
        'protocol_sha256':PROTOCOL_SHA,'code_sha256':code,
        'input_sha256':{str(p.relative_to(ROOT)):sha(p) for p in inputs},
        'test_access':'All19 calibration policies freeze before any outer test numeric arrays are read',
        'no_3d_or_actuation_promotion':True}
    write(out/'plan.json',plan)
    print(json.dumps({'prepared':True,'plan_sha256':sha(out/'plan.json'),'files':len(inputs),'code':len(code)}),flush=True)


def verify_policies(out,frozen):
    if (frozen.get('all19_calibration_complete') is not True
            or frozen.get('outer_test_numeric_values_opened') is not False
            or frozen.get('plan_sha256')!=sha(out/'plan.json')
            or list(frozen.get('policies',{}))!=NAMES):
        raise ValueError('Frozen policies must bind exactly all19 cases to this plan before test')
    for name,item in frozen['policies'].items():
        for filename,key in (('selection.json','selection_sha256'),('trials.json','trials_sha256'),
                ('calibration_predictions.csv.gz','calibration_predictions_sha256')):
            if sha(out/name/filename)!=item[key]:
                raise ValueError('Calibration artifact changed after freeze: '+name+'/'+filename)
        selection=json.loads((out/name/'selection.json').read_text())
        if selection['choice']!=item['choice'] or selection['accepted'] is not item['accepted']:
            raise ValueError('Frozen policy choice/status does not match original selection')


def calibration_blocks(name):
    f = json.loads((parent('v14')/name/'freeze.json').read_text())
    a = pd.read_csv(parent('v14')/name/'calibration_scores.csv.gz',float_precision='round_trip')
    b = pd.read_csv(parent('v8')/name/'calibration_scores.csv.gz',float_precision='round_trip')
    for c in ('sample_index','label','reference'):
        np.testing.assert_array_equal(a[c],b[c])
    starts = f['calibration_starts']; stop = f['test'][0]
    np.testing.assert_array_equal(a.sample_index,np.arange(starts[0],stop))
    bounds = [s-starts[0] for s in starts+[stop]]
    blocks = []
    for i,(l,r) in enumerate(zip(bounds[:-1],bounds[1:])):
        blocks.append({'labels':a.label.iloc[l:r].to_numpy(np.int8),
            'v6':a.reference.iloc[l:r].to_numpy(np.int8),
            'v8':b.candidate.iloc[l:r].to_numpy(np.int8),
            'scores':a.long_context.iloc[l:r].to_numpy(float),
            'source_start':int(starts[i]),'block_id':str(i)})
    return blocks,a,b


def run_calibration(out):
    plan=json.loads((out/'plan.json').read_text()); verify(plan)
    if (out/'policies-frozen.json').exists():
        raise ValueError('Policies already frozen; no overwrite/reselection')
    policies={}
    for name in NAMES:
        guard(out)
        folder=out/name; folder.mkdir()
        blocks,a,b=calibration_blocks(name)
        selected,trials=calibrate(blocks)
        write(folder/'selection.json',selected); write(folder/'trials.json',trials)
        values=np.concatenate([predict(x['v6'],x['v8'],x['scores'],selected['choice']) for x in blocks])
        pd.DataFrame({'sample_index':a.sample_index,'candidate':values}).to_csv(folder/'calibration_predictions.csv.gz',index=False)
        policies[name]={'selection_sha256':sha(folder/'selection.json'),'trials_sha256':sha(folder/'trials.json'),
            'calibration_predictions_sha256':sha(folder/'calibration_predictions.csv.gz'),
            'choice':selected['choice'],'accepted':selected['accepted']}
        print(json.dumps({'phase':'calibration','case':name,'accepted':selected['accepted'],
            'feasible':selected['feasible_earlier_trials'],'trials':selected['earlier_trial_count']}),flush=True)
    verify(plan)
    write(out/'policies-frozen.json',{'frozen_at_utc':now(),'all19_calibration_complete':True,
        'outer_test_numeric_values_opened':False,'plan_sha256':sha(out/'plan.json'),'policies':policies})


def _pair(y,ref,candidate):
    return assess(y,ref,ref,candidate)['v6_vs_v7']


def test_once(out):
    plan=json.loads((out/'plan.json').read_text()); verify(plan)
    frozen=json.loads((out/'policies-frozen.json').read_text())
    cal_audit=json.loads((out/'calibration-audit.json').read_text())
    if cal_audit.get('passed') is not True or cal_audit.get('policies_sha256') != sha(out/'policies-frozen.json'):
        raise ValueError('Independent frozen calibration audit required before test access')
    if (out/'test-started.json').exists():
        raise ValueError('Outer test access already started; no rerun/retuning')
    verify_policies(out,frozen)
    write(out/'test-started.json',{'at_utc':now(),'policies_sha256':sha(out/'policies-frozen.json'),
        'calibration_audit_sha256':sha(out/'calibration-audit.json'),'one_fixed_outer_pass':True})
    periods=[]; by_source={}
    historical_results={}
    metadata={p['case']:p for p in json.loads((parent('v14')/'results.json').read_text())['periods']}
    for name in NAMES:
        guard(out); t=time.perf_counter()
        a=pd.read_csv(parent('v14')/name/'predictions.csv.gz',float_precision='round_trip')
        histories={v:pd.read_csv(parent(v)/name/'predictions.csv.gz',float_precision='round_trip') for v in HISTORY if v!='v14'}
        b=histories['v8']
        for c in ('sample_index','label','reference'):
            np.testing.assert_array_equal(a[c],b[c])
        y=a.label.to_numpy(np.int8); v6=a.reference.to_numpy(np.int8); v8=b.candidate.to_numpy(np.int8)
        selected=frozen['policies'][name]['choice']
        candidate=predict(v6,v8,a.long_context.to_numpy(),selected)
        rows=pd.DataFrame({'sample_index':a.sample_index,'label':y,'baseline':a.baseline,
            'reference':v6,'v8':v8,'long_context':a.long_context,'candidate':candidate})
        result={'case':name,'source':metadata[name]['source'],'accepted_calibration':frozen['policies'][name]['accepted'],
            'comparisons':assess(y,a.baseline.to_numpy(np.int8),v6,candidate),
            'v8_comparison':_pair(y,v8,candidate),'history':{}}
        for v in HISTORY:
            h=a if v=='v14' else histories[v]
            for c in ('sample_index','label'): np.testing.assert_array_equal(a[c],h[c])
            result['history'][v]=_pair(y,h.candidate.to_numpy(np.int8),candidate)
            rows['history__'+v]=h.candidate.to_numpy(np.int8)
        rows.to_csv(out/name/'predictions.csv.gz',index=False)
        write(out/name/'results.json',result)
        periods.append(result); by_source.setdefault(result['source'],[]).append(rows)
        print(json.dumps({'phase':'test','case':name,'events':result['v8_comparison']['candidate']['confirmed_events'],
            'false_runs':result['v8_comparison']['candidate']['false_positive_runs'],
            'lost_v8':result['v8_comparison']['lost_baseline_event_ids'],'seconds':round(time.perf_counter()-t,2)}),flush=True)
    sources={}; v8_sources={}; historical_sources={}
    for source,parts in by_source.items():
        a=pd.concat(parts,ignore_index=True)
        np.testing.assert_array_equal(np.diff(a.sample_index),np.ones(len(a)-1,dtype=int))
        sources[source]=assess(*(a[c].to_numpy(np.int8) for c in ('label','baseline','reference','candidate')))
        v8_sources[source]=_pair(a.label.to_numpy(np.int8),a.v8.to_numpy(np.int8),a.candidate.to_numpy(np.int8))
        historical_sources[source]={v:_pair(a.label.to_numpy(np.int8),a['history__'+v].to_numpy(np.int8),a.candidate.to_numpy(np.int8)) for v in HISTORY}
    summary=summarize(periods,sources)
    comparisons=[p['v8_comparison'] for p in periods]+list(v8_sources.values())
    v8_checks={'all_periods_and_source_pools_noninferior':all(p['noninferior'] for p in comparisons),
        'strictly_fewer_pooled_false_fragments':sum(p['candidate']['false_positive_runs'] for p in v8_sources.values())<sum(p['baseline']['false_positive_runs'] for p in v8_sources.values()),
        'false_fragment_reduction_in_two_periods':sum(p['v8_comparison']['candidate']['false_positive_runs']<p['v8_comparison']['baseline']['false_positive_runs'] for p in periods)>=2}
    retention={v:{'retained':all(not p['history'][v]['lost_baseline_event_ids'] for p in periods)
        and all(not p[v]['lost_baseline_event_ids'] for p in historical_sources.values()),
        'lost':{p['case']:p['history'][v]['lost_baseline_event_ids'] for p in periods if p['history'][v]['lost_baseline_event_ids']},
        'lost_source_pools':{s:p[v]['lost_baseline_event_ids'] for s,p in historical_sources.items() if p[v]['lost_baseline_event_ids']}} for v in HISTORY}
    verify(plan); verify_policies(out,frozen)
    result={'completed_at_utc':now(),'candidate_version':'V15','complete_cases':19,'expected_cases':19,
        'all_prespecified_cases_complete':True,'development_only':True,'fresh_validation':False,
        'no_model_fit':True,'inherited_sensor_audit_not_new_raw_replay':True,
        'accepted_calibration_cases':sum(p['accepted'] for p in frozen['policies'].values()),
        'periods':periods,'sources':sources,'summary':summary,'v8_sources':v8_sources,'v8_checks':v8_checks,
        'historical_retention':retention,'historical_source_comparisons':historical_sources,
        'v8_totals':{model:prior.totals([p[model] for p in v8_sources.values()]) for model in ('baseline','candidate')},
        'current_quality_goal_passed':False,
        'independent_test_audit_pending':True,'no_promotion':True}
    result['quality_checks_before_independent_audit_passed']=bool(all(v8_checks.values()) and all(x['retained'] for x in retention.values())
        and summary['if_vs_v7']['passes_declared_development_gate'] and summary['v6_vs_v7']['passes_declared_development_gate'])
    write(out/'results.json',result)
    print(json.dumps({'complete_cases':19,'accepted':result['accepted_calibration_cases'],'summary':summary,'v8_checks':v8_checks}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('stage',choices=['prepare','calibrate','test']); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); out=args.output.resolve()
    {'prepare':prepare,'calibrate':run_calibration,'test':test_once}[args.stage](out)
