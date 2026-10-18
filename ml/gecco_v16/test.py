"""One fixed outer pass after independently audited all19 policy freezes."""
from pathlib import Path
import argparse
import json
import gc
import time
import joblib
import numpy as np
import pandas as pd
from ml.gecco_v7 import development_v2 as prior
from ml.gecco_v7.recalibrate_delayed import assess,summarize
from ml.gecco_v15 import development as old
from ml.gecco_v16.development import ROOT,NAMES,VERSION,guard,verify,sha,write,now
from ml.gecco_v16.runtime import predict_frame

HISTORY=['v8','v9','v10','v11','v12','v13','v14','v15']


def pair(y,ref,candidate):return assess(y,ref,ref,candidate)['v6_vs_v7']


def verify_freeze(out,plan,frozen):
    if (frozen.get('all19_calibration_complete') is not True
            or frozen.get('outer_test_numerical_arrays_opened') is not False
            or frozen.get('plan_sha256')!=sha(out/'plan.json')
            or list(frozen.get('policies',{}))!=NAMES):
        raise ValueError('Exact19 policy freezes tied to this plan required')
    for name,entry in frozen['policies'].items():
        folder=out/name
        if sha(folder/'freeze.json')!=entry['freeze_sha256'] or sha(folder/'bundle.joblib')!=entry['bundle_sha256']:
            raise ValueError('Case freeze/bundle changed: '+name)
        case=json.loads((folder/'freeze.json').read_text())
        if case['plan_sha256']!=sha(out/'plan.json') or case['selected']['choice']!=entry['choice']:
            raise ValueError('Case policy/plan does not match global freeze')
        for p,h in case['artifacts_sha256'].items():
            if sha(folder/p)!=h:raise ValueError('Unsealed training/calibration artifact:'+name+'/'+p)


def run(out,resume=False):
    plan=json.loads((out/'plan.json').read_text());verify(plan)
    frozen=json.loads((out/'policies-frozen.json').read_text());verify_freeze(out,plan,frozen)
    audit=json.loads((out/'pretest-audit.json').read_text())
    if (audit.get('passed') is not True or audit.get('complete_replayed_cases')!=19
            or audit.get('plan_sha256')!=sha(out/'plan.json')
            or audit.get('policies_sha256')!=sha(out/'policies-frozen.json')
            or audit.get('audit_version')!='v16_forward_teacher_raw_sensor_batch_replay_v1'
            or audit.get('stage')!='train' or audit.get('failed_checks')!=0
            or audit.get('outer_test_rows_read')!=0
            or audit.get('audit_script_sha256')!=sha(ROOT/'ml/gecco_v16_audits/replay.py')):
        raise ValueError('Independent complete training/calibration audit required')
    if (out/'results.json').exists():raise ValueError('Outer results already complete; never overwrite')
    guard(out)
    binding={'plan_sha256':sha(out/'plan.json'),'policies_sha256':sha(out/'policies-frozen.json'),
        'pretest_audit_sha256':sha(out/'pretest-audit.json'),'one_fixed_outer_pass':True,'no_retuning':True}
    if (out/'test-started.json').exists():
        if not resume:raise ValueError('Test started; resume exact frozen procedure explicitly')
        started=json.loads((out/'test-started.json').read_text())
        for k,v in binding.items():
            if started[k]!=v:raise ValueError('Resume bindings changed')
    else:write(out/'test-started.json',{'at_utc':now(),**binding})
    periods=[];by_source={}
    for case in prior.cases('all'):
        name=case['name'];guard(out)
        receipt=out/name/'test_case_freeze.json'
        if resume and receipt.exists():
            sealed=json.loads(receipt.read_text())
            for k in ('plan_sha256','policies_sha256','pretest_audit_sha256'):
                if sealed[k]!=binding[k]:raise ValueError('Completed outer case binding changed')
            for filename,h in sealed['files'].items():
                if sha(out/name/filename)!=h:raise ValueError('Completed outer case changed')
            result=json.loads((out/name/'results.json').read_text())
            rows=pd.read_csv(out/name/'predictions.csv.gz',float_precision='round_trip')
            if result['case']!=name or result['source']!=case['source']:raise ValueError('Case identity changed')
            periods.append(result);by_source.setdefault(case['source'],[]).append(rows)
            print(json.dumps({'case':name,'phase':'resume_completed_outer_case_without_rescoring'}),flush=True)
            continue
        if any((out/name/f).exists() for f in ('predictions.csv.gz','results.json')):
            if not resume:raise ValueError('Unsealed partial outer output exists')
            preserved=out/name/('test_unsealed_'+str(time.time_ns()));preserved.mkdir()
            for filename in ('predictions.csv.gz','results.json'):
                if (out/name/filename).exists():(out/name/filename).rename(preserved/filename)
        bundle=joblib.load(out/name/'bundle.joblib')
        if bundle['version']!=VERSION:raise ValueError('Bundle version mismatch')
        raw=case['load_test']();y=raw[case['target']].to_numpy(np.int8)
        actual=predict_frame(bundle,raw.loc[:,case['channels']],gap_samples=120)
        caches={v:pd.read_csv(old.parent(v)/name/'predictions.csv.gz',float_precision='round_trip') for v in HISTORY}
        prior_v8=caches['v8']
        np.testing.assert_array_equal(prior_v8.label,y)
        np.testing.assert_array_equal(prior_v8.sample_index,np.arange(case['test_start'],case['test_end']))
        for actual_name,old_name in (('baseline_prediction','baseline'),('reference_prediction','reference'),('v8_prediction','candidate')):
            np.testing.assert_array_equal(actual[actual_name],prior_v8[old_name])
        candidate=actual.prediction.to_numpy(np.int8);v6=actual.reference_prediction.to_numpy(np.int8)
        v8=actual.v8_prediction.to_numpy(np.int8);base=actual.baseline_prediction.to_numpy(np.int8)
        rows=pd.DataFrame({'sample_index':prior_v8.sample_index,'label':y,'baseline':base,
            'reference':v6,'v8':v8,'long_context':actual.long_context.to_numpy(),'candidate':candidate})
        result={'case':name,'source':case['source'],'accepted_calibration':frozen['policies'][name]['accepted'],
            'comparisons':assess(y,base,v6,candidate),'v8_comparison':pair(y,v8,candidate),'history':{}}
        for v,h in caches.items():
            np.testing.assert_array_equal(h.sample_index,rows.sample_index);np.testing.assert_array_equal(h.label,y)
            result['history'][v]=pair(y,h.candidate.to_numpy(np.int8),candidate)
            rows['history__'+v]=h.candidate.to_numpy(np.int8)
        rows.to_csv(out/name/'predictions.csv.gz',index=False);write(out/name/'results.json',result)
        write(receipt,{'at_utc':now(),'case':name,**binding,
            'files':{f:sha(out/name/f) for f in ('predictions.csv.gz','results.json')}})
        periods.append(result);by_source.setdefault(case['source'],[]).append(rows)
        print(json.dumps({'case':name,'phase':'outer_test','events':result['v8_comparison']['candidate']['confirmed_events'],
            'false_runs':result['v8_comparison']['candidate']['false_positive_runs'],
            'lost_v8':result['v8_comparison']['lost_baseline_event_ids']}),flush=True)
        del bundle,raw,actual,caches;gc.collect()
    if [p['case'] for p in periods]!=NAMES:raise ValueError('Incomplete original case identities')
    sources={};v8_sources={};hist_sources={}
    for source,parts in by_source.items():
        a=pd.concat(parts,ignore_index=True)
        np.testing.assert_array_equal(np.diff(a.sample_index),np.ones(len(a)-1,np.int64))
        sources[source]=assess(*(a[c].to_numpy(np.int8) for c in ('label','baseline','reference','candidate')))
        v8_sources[source]=pair(a.label.to_numpy(np.int8),a.v8.to_numpy(np.int8),a.candidate.to_numpy(np.int8))
        hist_sources[source]={v:pair(a.label.to_numpy(np.int8),a['history__'+v].to_numpy(np.int8),a.candidate.to_numpy(np.int8)) for v in HISTORY}
    summary=summarize(periods,sources)
    v8all=[p['v8_comparison'] for p in periods]+list(v8_sources.values())
    v8_checks={'all_periods_and_source_pools_noninferior':all(p['noninferior'] for p in v8all),
        'strictly_fewer_pooled_false_fragments':sum(p['candidate']['false_positive_runs'] for p in v8_sources.values())<sum(p['baseline']['false_positive_runs'] for p in v8_sources.values()),
        'false_fragment_reduction_in_two_periods':sum(p['v8_comparison']['candidate']['false_positive_runs']<p['v8_comparison']['baseline']['false_positive_runs'] for p in periods)>=2}
    retention={v:{'retained':all(not p['history'][v]['lost_baseline_event_ids'] for p in periods)
        and all(not p[v]['lost_baseline_event_ids'] for p in hist_sources.values()),
        'lost':{p['case']:p['history'][v]['lost_baseline_event_ids'] for p in periods if p['history'][v]['lost_baseline_event_ids']},
        'lost_source_pools':{s:p[v]['lost_baseline_event_ids'] for s,p in hist_sources.items() if p[v]['lost_baseline_event_ids']}} for v in HISTORY}
    quality=all(v8_checks.values()) and all(p['retained'] for p in retention.values()) and summary['if_vs_v7']['passes_declared_development_gate'] and summary['v6_vs_v7']['passes_declared_development_gate']
    verify(plan);verify_freeze(out,plan,frozen)
    write(out/'results.json',{'completed_at_utc':now(),'candidate_version':'V16','complete_cases':19,'expected_cases':19,
        'all_prespecified_cases_complete':True,'development_only':True,'fresh_validation':False,
        'all_sources_previously_disclosed':True,'no_promotion':True,'new_head_fit':True,'raw_outer_sensor_replay':True,
        'accepted_calibration_cases':sum(p['accepted'] for p in frozen['policies'].values()),
        'periods':periods,'sources':sources,'summary':summary,'v8_sources':v8_sources,'v8_checks':v8_checks,
        'historical_retention':retention,'historical_source_comparisons':hist_sources,
        'v8_totals':{m:prior.totals([p[m] for p in v8_sources.values()]) for m in ('baseline','candidate')},
        'quality_checks_before_independent_audit_passed':bool(quality),
        'independent_test_audit_pending':True,'current_quality_goal_passed':False})
    print(json.dumps({'complete_cases':19,'quality_checks_before_audit':bool(quality)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--resume',action='store_true');a=p.parse_args();run(a.output.resolve(),a.resume)
