"""Post-test V11 diagnosis on saved completed development outputs only.

No fitting, threshold selection, alternative-policy execution or source access.
All19 V8/V9/V10/V11 results must be complete before any row file is opened.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import numpy as np
import pandas as pd
from ml.gecco_v9.diagnose import complete_result, compare_rows, timing, coverage, sha, read
from ml.gecco_v7_audits.diagnose_certified import diagnose_run, _episodes
from ml.gecco_v10.diagnose import trial_match, trial_records

ROOT=Path(__file__).resolve().parents[2]


def fixed_choice(selected):
    keys=('decision','low_threshold','high_threshold','policy','confirmation_samples','cadence_seconds','pending_after_clear','retained_if_protection')
    return {key:selected.get(key,False) for key in keys}


def protection_rows(rows):
    """Descriptive masks and latching invariants; no alternative predictions."""
    baseline,reference,candidate=[rows[k].to_numpy(np.int8) for k in ('baseline','reference','candidate')]
    trigger=(baseline==1)&(reference==1);removed=(baseline==1)&(reference==0)
    tail=np.zeros(len(rows),bool);episodes=0
    for start,end in _episodes(reference):
        locations=np.flatnonzero(trigger[start:end])
        if len(locations):tail[start+locations[0]:end]=True;episodes+=1
    if (candidate[trigger]!=1).any() or (candidate[tail]!=1).any():raise ValueError('Saved candidate did not retain protected trigger/tail')
    if not np.array_equal(reference>=0,candidate>=0):raise ValueError('Reference availability changed')
    return {'rows':len(rows),'retained_if_trigger_rows':int(trigger.sum()),'protected_reference_episodes':episodes,
        'protected_latched_tail_rows':int(tail.sum()),'protected_trigger_or_tail_lost_rows':int((tail&(candidate!=1)).sum()),
        'protection_trigger_on_v6_removed_if_rows':int((trigger&removed).sum()),
        'if_alarm_rows_removed_by_v6':int(removed.sum()),
        'final_alarm_on_v6_removed_if_rows':int((removed&(candidate==1)).sum()),
        'availability_equal':True,
        'interpretation':'Protection only triggers on IF=1 AND reference=1. The zero trigger-on-removed count is the rule invariant. Any final alarm on reference=0 may arise from separately selected pending/rescue, not the protection trigger. These counts are not an alternative-policy experiment.'}


def outcome_followup(run):
    """Summarize existing early-grid feasibility and actual row-level outcome."""
    run=Path(run).resolve();result=complete_result(run,'V11')
    hashes={str(run/'results.json'):sha(run/'results.json')};cases=[]
    for p in result['periods']:
        folder=run/p['case'];paths={key:folder/name for key,name in [('test','predictions.csv.gz'),('cal','calibration_scores.csv.gz'),('trials','calibration_trials.csv.gz'),('freeze','freeze.json')]}
        for path in paths.values():hashes[str(path)]=sha(path)
        test=pd.read_csv(paths['test'],float_precision='round_trip');cal=pd.read_csv(paths['cal'],float_precision='round_trip')
        trials=pd.read_csv(paths['trials'],float_precision='round_trip');early=trials[trials.stage=='earlier_selection']
        reference=early.iloc[0];confirm=early[early.low_threshold.notna()];feasible=confirm[confirm.feasible.eq(True)]
        cut=read(paths['freeze'])['calibration_starts'][2];past=cal[cal.sample_index<cut]
        normal=(past.label==0)&(past.reference==1);protected=normal&(past.baseline==1)
        differences=test.candidate.to_numpy()!=test.reference.to_numpy()
        cases.append({'case':p['case'],'status':p['selected']['status'],'final_selected':fixed_choice(p['selected']),
            'test_rows':len(test),'candidate_reference_row_mismatches':int(differences.sum()),
            'candidate_reference_mismatch_sample_indices':test.sample_index[differences].astype(int).tolist(),
            'early_reference':{k:int(reference[k]) for k in ('events','tp','fp','false_runs')},
            'early_confirmation_trials':len(confirm),'early_feasible_confirmation_trials':len(feasible),
            'minimum_feasible_confirmation_false_rows':int(feasible.fp.min()) if len(feasible) else None,
            'minimum_feasible_confirmation_false_fragments':int(feasible.false_runs.min()) if len(feasible) else None,
            'maximum_feasible_confirmation_events':int(feasible.events.max()) if len(feasible) else None,
            'any_feasible_confirmation_reduces_false_rows':bool((feasible.fp<reference.fp).any()),
            'any_feasible_confirmation_reduces_false_fragments':bool((feasible.false_runs<reference.false_runs).any()),
            'early_known_normal_reference_alarm_rows':int(normal.sum()),
            'early_known_normal_reference_alarm_rows_protected_by_if':int(protected.sum()),
            'certification_rejection_reasons':p['selected']['certification_rejection_reasons']})
    for path,digest in hashes.items():
        if sha(path)!=digest:raise ValueError('Follow-up input changed')
    return {'candidate_version':'V11','status':'post_test_saved_grid_and_row_equality_only','new_source_accessed':False,'model_refitted':False,
        'thresholds_changed':False,'policy_reexecuted':False,'input_sha256':hashes,'cases':cases,
        'total_candidate_reference_row_mismatches':sum(p['candidate_reference_row_mismatches'] for p in cases),
        'active_confirmation_periods':[p['case'] for p in result['periods'] if p['selected']['low_threshold'] is not None],
        'interpretation':'Minima describe the already saved first-two candidate grid, not a new optimization or selected alternative. If protected feasible confirmation cannot improve the fixed ranking, reference may win by simpler-path tie-breaking. Later certification failures are reported separately. Row equality includes unavailable, quiet and alarm samples.'}


def describe(run,parent,previous,earlier):
    folders={version:Path(path).resolve() for version,path in [('v11',run),('v10',parent),('v9',previous),('v8',earlier)]}
    versions={version:complete_result(path,version.upper()) for version,path in folders.items()}
    run=folders['v11'];periods={v:{p['case']:p for p in result['periods']} for v,result in versions.items()}
    hashes={str(folder/name):sha(folder/name) for folder in folders.values() for name in ('results.json','plan.json')}
    diagnostic=diagnose_run(run)
    diagnostic['notes'][0]=f"All {len(diagnostic['active_periods'])} active policies and {len(diagnostic['fallbacks'])} fallback decisions are retained."
    diagnostic['notes'].append('V11 protection is an explicit IF/reference rule. Timing alone cannot attribute a saved alarm to confidence; the retained IF trigger may release first.')
    for active in diagnostic['active_periods']:
        active['fixed_selected']=fixed_choice(periods['v11'][active['case']]['selected'])
        for event in active['lost_events']:
            event['explanation']='Saved original event loss; inspect explicit baseline/reference agreement and the selected confirmation/pending/rescue paths. No counterfactual policy was executed.'
            for pulse in event['reference_episodes']:
                pulse['short_low_confidence_episode_pattern']=pulse.pop('short_low_confidence_episode_discard_explains_loss')
    comparisons=[];timings=[];coverages=[];details=[];pools={};protection=[]
    for period in versions['v11']['periods']:
        name=period['case'];rows={}
        for version,folder in folders.items():
            path=folder/name/'predictions.csv.gz';hashes[str(path)]=sha(path);rows[version]=pd.read_csv(path,float_precision='round_trip')
            if periods[version][name]['source']!=period['source'] or periods[version][name]['selected']['cadence_seconds']!=period['selected']['cadence_seconds']:raise ValueError('Cross-run source/cadence mismatch')
        current=rows['v11']
        for version in ('v8','v9','v10'):
            for key in ('sample_index','label','baseline','reference'):np.testing.assert_array_equal(current[key],rows[version][key])
        for version in ('v9','v10'):
            for key in ('long_context','guarded_long_context','rescue_long_context','conditional_observed'):np.testing.assert_array_equal(current[key],rows[version][key])
        for version in ('v9','v10'):np.testing.assert_array_equal(current[version+'_candidate'],rows[version].candidate)
        paired={}
        for version in ('v8','v9','v10'):
            pair=compare_rows(current.label,rows[version].candidate,current.candidate,period['selected']['cadence_seconds'])
            pair['interpretation']=f'Descriptive {version.upper()}/V11 exact-axis comparison; original IF/V6 strong gate unchanged. Historical event loss remains material to the user retention goal.'
            if pair['baseline']!=periods[version][name]['comparisons']['v6_vs_v7']['candidate'] or pair['candidate']!=period['comparisons']['v6_vs_v7']['candidate']:raise ValueError('Cross-run metrics mismatch')
            paired[version+'_vs_v11']=pair
        comparisons.append({'case':name,'source':period['source'],**paired})
        cov=coverage(current)
        for key,value in period['conditional_block_test_coverage'].items():
            if cov[key]!=value:raise ValueError('Coverage changed')
        coverages.append({'case':name,**cov})
        ids=set()
        for version in versions:ids.update(periods[version][name]['comparisons']['v6_vs_v7']['lost_baseline_event_ids'])
        for pair in paired.values():ids.update(pair['lost_baseline_event_ids']);ids.update(pair['new_candidate_event_ids'])
        for event in paired['v10_vs_v11']['baseline']['primary_event_intervals']:
            if event['event_id'] not in ids:continue
            info={'case':name,'event_id':event['event_id'],'source_sample_start':int(current.sample_index.iloc[event['start']]),'source_sample_end_exclusive':int(current.sample_index.iloc[event['end_exclusive']-1])+1}
            for version in versions:
                saved=periods[version][name];info[version]=timing(rows[version],event,saved['selected'],saved['comparisons']['v6_vs_v7']['candidate'])
                info[version]['pending_after_clear']=saved['selected'].get('pending_after_clear',False)
                info[version]['retained_if_protection']=saved['selected'].get('retained_if_protection',False)
                info['lost_from_v6_by_'+version]=event['event_id'] in saved['comparisons']['v6_vs_v7']['lost_baseline_event_ids']
                for pulse in info[version]['reference_pulses']:
                    fragment=rows[version].iloc[pulse['start_index']:pulse['end_exclusive']]
                    pulse['baseline_alarm_rows_inside_reference_pulse']=int((fragment.baseline==1).sum())
                    pulse['baseline_alarm_at_first_pulse_row']=bool(fragment.baseline.iloc[0]==1)
            timings.append(info)
        s=period['selected'];prior=periods['v10'][name]['selected'];paths={k:run/name/f for k,f in [('trials','calibration_trials.csv.gz'),('freeze','freeze.json'),('cal','calibration_scores.csv.gz')]}
        for path in paths.values():hashes[str(path)]=sha(path)
        trials=pd.read_csv(paths['trials'],float_precision='round_trip');pending=trials[(trials.stage=='earlier_selection')&trials.pending_after_clear.eq(True)]
        pending_reasons=Counter(reason for value in pending.rejection_reasons for reason in set(ast.literal_eval(value)))
        details.append({'case':name,'v10_final':fixed_choice(prior),'v10_status':prior['status'],'v10_earlier':fixed_choice(prior['earlier_selected']),
            'v11_final':fixed_choice(s),'v11_status':s['status'],'v11_earlier':fixed_choice(s['earlier_selected']),
            'v10_certification_rejection_reasons':prior['certification_rejection_reasons'],'v11_certification_rejection_reasons':s['certification_rejection_reasons'],
            'earlier_selected_trial':trial_records(trial_match(trials,s['earlier_selected'])),
            'previous_operating_point_under_new_protection_rule':trial_records(trial_match(trials,prior['earlier_selected'])),
            'pending_grid_trials':len(pending),'pending_grid_feasible_trials':int(pending.feasible.sum()),'pending_grid_rejection_counts':dict(pending_reasons),
            'pending_at_earlier_chosen_other_settings':trial_records(trial_match(trials,s['earlier_selected'],True)),
            'later_pending_evidence':s['certification']['pending'],'later_pulse_certificate':s['certification']['positive_reference_pulses'],
            'all_four_pulse_certificate':s['global_veto']['all_four_positive_reference_pulses'],
            'interpretation':'Saved first-two trial records only. Matching the former numerical operating point under V11 includes the new protection rule; it is not a rerun of the old V10 policy.'})
        frozen=read(paths['freeze']);cal=pd.read_csv(paths['cal'],float_precision='round_trip');starts=frozen['calibration_starts'];ends=starts[1:]+[frozen['test'][0]]
        cal_support=[]
        for i,(a,b) in enumerate(zip(starts,ends)):
            part=cal[(cal.sample_index>=a)&(cal.sample_index<b)]
            cal_support.append({'block':i,'phase':'earlier_selection' if i<2 else 'later_certification',**protection_rows(part)})
        protection.append({'case':name,'selected':fixed_choice(s),'test':protection_rows(current),'calibration_blocks':cal_support})
        joined=current[['sample_index','label','candidate']].copy()
        for version in ('v8','v9','v10'):joined[version]=rows[version].candidate.to_numpy(np.int8)
        pools.setdefault(period['source'],[]).append(joined)
    source_comparisons={}
    for source,parts in pools.items():
        rows=pd.concat(parts,ignore_index=True);np.testing.assert_array_equal(np.diff(rows.sample_index),np.ones(len(rows)-1,int));source_comparisons[source]={}
        for version in ('v8','v9','v10'):
            pair=compare_rows(rows.label,rows[version],rows.candidate)
            pair['interpretation']=f'Descriptive {version.upper()}/V11 contiguous source-axis comparison; primary IDs preserved without period duplication.'
            if pair['baseline']!=versions[version]['sources'][source]['v6_vs_v7']['candidate'] or pair['candidate']!=versions['v11']['sources'][source]['v6_vs_v7']['candidate']:raise ValueError('Source pool comparison mismatch')
            source_comparisons[source][version+'_vs_v11']=pair
    for path,digest in hashes.items():
        if sha(path)!=digest:raise ValueError('Artifact changed during read-only diagnosis')
    diagnostic.update({'candidate_version':'V11','comparison_runs':{v:str(p) for v,p in folders.items()},
        'cross_run_input_sha256':hashes,'cross_run_axis_verified':True,'v9_v10_scores_exactly_unchanged':True,
        'cross_run_period_comparison':comparisons,'cross_run_source_comparison':source_comparisons,'timing_comparison':timings,
        'conditional_coverage_by_period':coverages,'policy_evidence_by_period':details,'protection_by_period':protection,
        'pending_selected_periods':[p['case'] for p in versions['v11']['periods'] if p['selected']['pending_after_clear']],
        'fresh_validation':False,'policies_reexecuted_for_diagnosis':False,
        'statistical_change':'Fixed V9 model/scores reused via V10. Only retained-IF immediate protected release/latching is added before V10 calibration and certificate accounting.',
        'timing_interpretation':'No threshold or alternate policy tested. Release may be caused by retained IF protection, not improved confidence. Historical V8-only event losses are reported independently of original IF/V6 gate.'})
    return diagnostic


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('run','parent','previous','earlier','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=describe(a.run,a.parent,a.previous,a.earlier);a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'output':str(a.output),'status_counts':result['status_counts'],'pending_selected_periods':result['pending_selected_periods']}))


if __name__=='__main__':main()
