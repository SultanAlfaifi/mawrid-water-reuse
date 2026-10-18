"""Read-only V13 post-test diagnosis; no source access or alternative fitting.

V13 refits HGB with one training-normal reweighting change on the original training populations.
Only original axes, labels and IF/V6 predictions are asserted unchanged; V13
confidence scores and fitted HGB are deliberately not assumed equal to V8-12.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import numpy as np
import pandas as pd
from ml.gecco_v9.diagnose import complete_result,compare_rows,timing,coverage,sha,read
from ml.gecco_v7_audits.diagnose_certified import diagnose_run
from ml.gecco_v7_audits.diagnose import quantiles

ROOT=Path(__file__).resolve().parents[2]
HISTORICAL=('v8','v9','v10','v11','v12')


def score_description(current,previous):
    result={}
    for label,name in ((0,'normal'),(1,'positive'),(-1,'unknown')):
        scope=(current.label.to_numpy()==label)&(current.reference.to_numpy()>=0)
        first=previous.long_context.to_numpy(float);second=current.long_context.to_numpy(float)
        paired=scope&np.isfinite(first)&np.isfinite(second)
        result[name]={'rows':int(scope.sum()),'paired_finite_rows':int(paired.sum()),
            'v12_raw_confidence':quantiles(first[scope]),'v13_raw_confidence':quantiles(second[scope]),
            'paired_raw_change':quantiles(second[paired]-first[paired])}
    return result


def describe(run,historical_runs):
    folders={'v13':Path(run).resolve(),**{v:Path(historical_runs[v]).resolve() for v in HISTORICAL}}
    versions={v:complete_result(folder,v.upper()) for v,folder in folders.items()}
    period_maps={v:{p['case']:p for p in value['periods']} for v,value in versions.items()}
    hashes={str(folder/name):sha(folder/name) for folder in folders.values() for name in ('results.json','plan.json')}
    current_run=folders['v13'];diagnostic=diagnose_run(current_run)
    diagnostic['model_refitted_by_diagnosis']=diagnostic.pop('model_refitted')
    diagnostic['notes'][0]=f"All {len(diagnostic['active_periods'])} active decisions and {len(diagnostic['fallbacks'])} reference fallbacks are retained."
    diagnostic['notes'].append('This experiment refitted HGB on original training rows, reusing a fixed original IF; the diagnostic itself does not fit or execute alternative policies.')
    for active in diagnostic['active_periods']:
        active['fixed_selected']['pending_after_clear']=period_maps['v13'][active['case']]['selected']['pending_after_clear']
        for event in active['lost_events']:
            event['explanation']='Saved candidate missed this original event. Timing and scores use only its frozen selected policy; no counterfactual threshold or altered model was evaluated.'
            for pulse in event['reference_episodes']:
                pulse['short_low_confidence_episode_pattern']=pulse.pop('short_low_confidence_episode_discard_explains_loss')
    comparisons=[];timings=[];coverage_rows=[];policies=[];score_rows=[];pool_parts={};row_identity=[]
    for p in versions['v13']['periods']:
        name=p['case'];rows={}
        for version,folder in folders.items():
            path=folder/name/'predictions.csv.gz';hashes[str(path)]=sha(path)
            rows[version]=pd.read_csv(path,float_precision='round_trip')
            if period_maps[version][name]['source']!=p['source'] or period_maps[version][name]['selected']['cadence_seconds']!=p['selected']['cadence_seconds']:raise ValueError('Historical source/cadence mismatch')
        current=rows['v13'];paired={}
        for version in HISTORICAL:
            for key in ('sample_index','label','baseline','reference'):np.testing.assert_array_equal(current[key],rows[version][key])
            pair=compare_rows(current.label,rows[version].candidate,current.candidate,p['selected']['cadence_seconds'])
            pair['interpretation']=f'Descriptive {version.upper()}/V13 same original axis. Original IF/V6 strong gate unchanged; any historical event-ID loss remains material to retention.'
            if pair['baseline']!=period_maps[version][name]['comparisons']['v6_vs_v7']['candidate'] or pair['candidate']!=p['comparisons']['v6_vs_v7']['candidate']:raise ValueError('Saved cross-run metrics mismatch')
            paired[version+'_vs_v13']=pair
        comparisons.append({'case':name,'source':p['source'],**paired})
        row_identity.append({'case':name,'rows':len(current),'candidate_reference_row_mismatches':int((current.candidate!=current.reference).sum()),
            **{version+'_candidate_row_mismatches':int((current.candidate.to_numpy()!=rows[version].candidate.to_numpy()).sum()) for version in HISTORICAL}})
        detail=coverage(current)
        for key,value in p['conditional_block_test_coverage'].items():
            if detail[key]!=value:raise ValueError('Conditional coverage metadata mismatch')
        coverage_rows.append({'case':name,**detail})
        score_rows.append({'case':name,'comparison':'V12 versus newly fitted V13, descriptive raw scores only','distributions':score_description(current,rows['v12'])})
        interesting=set()
        for version in versions:interesting.update(period_maps[version][name]['comparisons']['v6_vs_v7']['lost_baseline_event_ids'])
        for pair in paired.values():interesting.update(pair['lost_baseline_event_ids']);interesting.update(pair['new_candidate_event_ids'])
        for event in paired['v11_vs_v13']['baseline']['primary_event_intervals']:
            if event['event_id'] not in interesting:continue
            entry={'case':name,'event_id':event['event_id'],'source_sample_start':int(current.sample_index.iloc[event['start']]),'source_sample_end_exclusive':int(current.sample_index.iloc[event['end_exclusive']-1])+1}
            for version in versions:
                saved=period_maps[version][name];entry[version]=timing(rows[version],event,saved['selected'],saved['comparisons']['v6_vs_v7']['candidate'])
                entry[version]['pending_after_clear']=saved['selected'].get('pending_after_clear',False)
                entry[version]['retained_if_protection']=saved['selected'].get('retained_if_protection',False)
                entry['lost_from_v6_by_'+version]=event['event_id'] in saved['comparisons']['v6_vs_v7']['lost_baseline_event_ids']
            timings.append(entry)
        trial_path=current_run/name/'calibration_trials.csv.gz';hashes[str(trial_path)]=sha(trial_path)
        trials=pd.read_csv(trial_path,float_precision='round_trip');early=trials[trials.stage=='earlier_selection'];pending=early[early.pending_after_clear.eq(True)]
        pending_reasons=Counter(reason for text in pending.rejection_reasons for reason in set(ast.literal_eval(text)))
        s=p['selected'];policies.append({'case':name,'status':s['status'],'earlier_status':s['earlier_selected']['status'],
            'final_choice':{k:s[k] for k in ('decision','low_threshold','high_threshold','policy','confirmation_samples','pending_after_clear')},
            'early_trials':len(early),'early_feasible_trials':int(early.feasible.sum()),'pending_grid_trials':len(pending),'pending_grid_feasible_trials':int(pending.feasible.sum()),
            'pending_rejection_counts':dict(pending_reasons),'certification_rejection_reasons':s['certification_rejection_reasons'],
            'later_pending_evidence':s['certification']['pending'],'later_rescue_evidence':s['certification']['rescue'],
            'later_pulse_certificate':s['certification']['positive_reference_pulses']})
        joined=current[['sample_index','label','candidate']].copy()
        for version in HISTORICAL:joined[version]=rows[version].candidate.to_numpy(np.int8)
        pool_parts.setdefault(p['source'],[]).append(joined)
    source_comparisons={}
    for source,parts in pool_parts.items():
        rows=pd.concat(parts,ignore_index=True);np.testing.assert_array_equal(np.diff(rows.sample_index),np.ones(len(rows)-1,int));source_comparisons[source]={}
        for version in HISTORICAL:
            pair=compare_rows(rows.label,rows[version],rows.candidate)
            pair['interpretation']=f'Descriptive {version.upper()}/V13 contiguous source axis; no independent duplicate boundary events.'
            if pair['baseline']!=versions[version]['sources'][source]['v6_vs_v7']['candidate'] or pair['candidate']!=versions['v13']['sources'][source]['v6_vs_v7']['candidate']:raise ValueError('Source metrics mismatch')
            source_comparisons[source][version+'_vs_v13']=pair
    for path,digest in hashes.items():
        if sha(path)!=digest:raise ValueError('Saved input changed during diagnosis')
    diagnostic.update({'candidate_version':'V13','comparison_runs':{v:str(p) for v,p in folders.items()},
        'cross_run_input_sha256':hashes,'cross_run_axis_verified':True,'original_if_v6_predictions_unchanged':True,
        'experiment_refitted_hgb':True,'experiment_refitted_original_if':False,'policies_reexecuted_for_diagnosis':False,'fresh_validation':False,
        'cross_run_period_comparison':comparisons,'cross_run_source_comparison':source_comparisons,'timing_comparison':timings,
        'conditional_coverage_by_period':coverage_rows,'policy_evidence_by_period':policies,'score_comparison_by_period':score_rows,'row_identity_by_period':row_identity,
        'pending_selected_periods':[p['case'] for p in versions['v13']['periods'] if p['selected']['pending_after_clear']],
        'statistical_change':'Single change from V12: q95 uses all finite known-normal training IF scores; eligible known-normal HGB rows at or above it receive relative weight5, other eligible known-normal rows weight1; renormalize only normal mass0.5. Positive weights remain exactly unchanged. Original IF, features, references, conditional fit, HGB parameters, availability and frozen V10 policy unchanged; HGB fitted anew on original training rows.',
        'timing_interpretation':'Version-specific selected thresholds and newly fitted HGB scores can both differ. Training-normal reweighting is a hypothesis, not a proven cause or cure of late confidence. Raw scores are not calibrated safety probabilities. No test threshold was selected.'})
    return diagnostic


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    for v in HISTORICAL:p.add_argument('--'+v,type=Path,default=ROOT/f'output/ml/gecco-{v}-development/run_01')
    a=p.parse_args();d=describe(a.run,{v:getattr(a,v) for v in HISTORICAL});a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:json.dump(d,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'output':str(a.output),'status_counts':d['status_counts'],'pending_selected_periods':d['pending_selected_periods']}))


if __name__=='__main__':main()
