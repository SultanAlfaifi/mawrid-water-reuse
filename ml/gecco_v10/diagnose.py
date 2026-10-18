"""Read-only post-test V10 diagnosis on all19 completed disclosed periods.

No fit, threshold choice, policy replay, or new source access. Inspect saved
choices/trials and compare original axes with both audited historical versions.
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

ROOT = Path(__file__).resolve().parents[2]
CHOICE_KEYS = ('decision', 'low_threshold', 'high_threshold', 'policy', 'confirmation_samples', 'cadence_seconds', 'pending_after_clear')


def choice(s):
    return {k: s.get(k, False if k == 'pending_after_clear' else None) for k in CHOICE_KEYS}


def trial_match(frame, selected, pending=None):
    mask = frame.stage.eq('earlier_selection')
    for key in ('low_threshold', 'high_threshold'):
        mask &= frame[key].isna() if selected[key] is None else frame[key].eq(selected[key])
    mask &= frame.confirmation_samples.eq(selected['confirmation_samples'])
    mask &= frame.policy.eq(selected['policy'])
    mask &= frame.pending_after_clear.eq(selected.get('pending_after_clear', False) if pending is None else pending)
    return frame.loc[mask]


def trial_records(frame):
    keys = ['feasible', 'rejection_reasons', 'events', 'tp', 'fp', 'false_runs',
            'lost_positive_pulse_obligations', 'pending_added_normal_rows',
            'pending_added_normal_rows_by_block', 'pending_coverage_event_ids', 'pending_coverage_blocks']
    result = frame[keys].to_dict('records')
    for row in result:
        for key in keys:
            if isinstance(row[key], str) and row[key].startswith('['): row[key] = ast.literal_eval(row[key])
    return result


def suppression_support(run):
    """Describe saved positive pulse responses; never execute another policy."""
    run = Path(run).resolve(); result = complete_result(run, 'V10')
    hashes = {str(run/'results.json'): sha(run/'results.json')}; cases=[]; lost=[]
    for period in result['periods']:
        s=period['selected']
        if s['low_threshold'] is None: continue
        if s['high_threshold'] is not None or s['pending_after_clear']:
            raise ValueError('Saved candidate can describe pure unextended confirmation only when other paths are disabled')
        paths={key:run/period['case']/name for key,name in [('freeze','freeze.json'),('cal','calibration_scores.csv.gz'),('test','predictions.csv.gz')]}
        for path in paths.values(): hashes[str(path)]=sha(path)
        frozen=read(paths['freeze']); cal=pd.read_csv(paths['cal'],float_precision='round_trip')
        test=pd.read_csv(paths['test'],float_precision='round_trip'); blocks=[]
        starts=frozen['calibration_starts']; ends=starts[1:]+[frozen['test'][0]]
        for i,(a,b) in enumerate(zip(starts,ends)):
            rows=cal[(cal.sample_index>=a)&(cal.sample_index<b)]
            y,r,p=[rows[k].to_numpy(np.int8) for k in ('label','reference','candidate')]
            raw=rows.long_context.to_numpy(float); pulses=[]
            for start,end in _episodes(r):
                positive=np.flatnonzero(y[start:end]==1)+start
                if not len(positive): continue
                alarms=positive[p[positive]==1]; finite=np.isfinite(raw[positive])
                pulses.append({'source_pulse_start':int(rows.sample_index.iloc[start]),'length_samples':int(end-start),
                    'left_censored':bool(start==0),'right_censored':bool(end==len(rows)),
                    'positive_rows':len(positive),'finite_positive_confidence_below_low_rows':int((finite&(raw[positive]<s['low_threshold'])).sum()),
                    'all_positive_confidence_finite_below_low':bool(finite.all() and (raw[positive]<s['low_threshold']).all()),
                    'positive_alarm_rows_removed':int((p[positive]!=1).sum()),
                    'positive_response_absent_inside_pulse':not bool(len(alarms)),
                    'first_positive_response_delay_seconds':int((alarms[0]-positive[0])*s['cadence_seconds']) if len(alarms) else None})
            blocks.append({'block':i,'phase':'earlier_selection' if i<2 else 'later_certification','sample_range':[a,b],
                'positive_reference_pulses':len(pulses),
                'pulses_with_any_positive_confidence_below_low':sum(p['finite_positive_confidence_below_low_rows']>0 for p in pulses),
                'pulses_with_all_positive_confidence_finite_below_low':sum(p['all_positive_confidence_finite_below_low'] for p in pulses),
                'positive_response_delayed_pulses':sum(p['first_positive_response_delay_seconds'] is not None and p['first_positive_response_delay_seconds']>0 for p in pulses),
                'positive_response_absent_inside_pulse':sum(p['positive_response_absent_inside_pulse'] for p in pulses),
                'positive_alarm_rows_removed':sum(p['positive_alarm_rows_removed'] for p in pulses),'pulses':pulses})
        cases.append({'case':period['case'],'selected':choice(s),'blocks':blocks})
        comp=period['comparisons']['v6_vs_v7']
        for event in comp['baseline']['primary_event_intervals']:
            if event['event_id'] not in comp['lost_baseline_event_ids']: continue
            part=test.iloc[event['start']:event['end_exclusive']]; pulse=part[part.reference==1]
            lost.append({'case':period['case'],'event_id':event['event_id'],'reference_pulse_rows':len(pulse),
                'raw_confidence':pulse.long_context.tolist(),'guarded_confidence':pulse.guarded_long_context.tolist(),
                'guarded_equals_raw_on_pulse':bool(np.array_equal(pulse.long_context,pulse.guarded_long_context,equal_nan=True)),
                'conditional_observed_on_every_pulse_row':bool(pulse.conditional_observed.all())})
    for path,digest in hashes.items():
        if sha(path)!=digest: raise ValueError('Support artifact changed')
    return {'candidate_version':'V10','status':'post_test_saved_confirmation_support_only','new_source_accessed':False,
        'model_refitted':False,'thresholds_changed':False,'policy_reexecuted':False,'input_sha256':hashes,
        'cases':cases,'lost_event_score_evidence':lost,
        'interpretation':'Block-local positive-intersecting reference episodes, not unique events. Boundary fragments are marked. Delays describe saved within-pulse positive response; full original event and pulse certification remain authoritative.'}


def describe(run, parent, earlier):
    run, parent, earlier = [Path(p).resolve() for p in (run, parent, earlier)]
    versions = {'v10': complete_result(run, 'V10'), 'v9': complete_result(parent, 'V9'), 'v8': complete_result(earlier, 'V8')}
    folders = {'v10': run, 'v9': parent, 'v8': earlier}
    periods = {v: {p['case']: p for p in result['periods']} for v, result in versions.items()}
    hashes = {str(folder/name): sha(folder/name) for folder in folders.values() for name in ('results.json', 'plan.json')}
    diagnostic = diagnose_run(run)
    diagnostic['notes'][0] = f"All {len(diagnostic['active_periods'])} active policies and {len(diagnostic['fallbacks'])} reference fallbacks are retained."
    diagnostic['notes'].append('Saved candidate predictions include any selected pending path; removed in-pulse rows alone do not prove a missed event.')
    for active in diagnostic['active_periods']:
        active['fixed_selected']['pending_after_clear'] = periods['v10'][active['case']]['selected']['pending_after_clear']
        for event in active['lost_events']:
            event['explanation'] = 'The saved candidate missed this original event. Pulse scores, the frozen choice and the absence or presence of pending/rescue are descriptive evidence, not a newly tested alternative.'
            for pulse in event['reference_episodes']:
                pulse['short_low_confidence_episode_pattern'] = pulse.pop('short_low_confidence_episode_discard_explains_loss')
    comparisons, timings, coverages, policy_details, pool_parts = [], [], [], [], {}
    for period in versions['v10']['periods']:
        name = period['case']; rows = {}
        for version, folder in folders.items():
            path = folder/name/'predictions.csv.gz'; hashes[str(path)] = sha(path)
            rows[version] = pd.read_csv(path, float_precision='round_trip')
            if periods[version][name]['source'] != period['source']: raise ValueError('Source identity changed')
            if periods[version][name]['selected']['cadence_seconds'] != period['selected']['cadence_seconds']: raise ValueError('Cadence changed')
        current = rows['v10']
        for version in ('v8', 'v9'):
            for key in ('sample_index', 'label', 'baseline', 'reference'):
                np.testing.assert_array_equal(current[key], rows[version][key])
        for key in ('long_context', 'guarded_long_context', 'rescue_long_context', 'conditional_observed'):
            np.testing.assert_array_equal(current[key], rows['v9'][key])
        np.testing.assert_array_equal(current.v9_candidate, rows['v9'].candidate)
        paired = {}
        for version in ('v8', 'v9'):
            pair = compare_rows(current.label, rows[version].candidate, current.candidate, period['selected']['cadence_seconds'])
            pair['interpretation'] = f'Descriptive {version.upper()}/V10 same-axis comparison; original IF/V6 gates unchanged.'
            if pair['baseline'] != periods[version][name]['comparisons']['v6_vs_v7']['candidate'] or pair['candidate'] != period['comparisons']['v6_vs_v7']['candidate']:
                raise ValueError('Metrics disagree with saved same-axis results')
            paired[version+'_vs_v10'] = pair
        comparisons.append({'case': name, 'source': period['source'], **paired})
        cov = coverage(current)
        for key, value in period['conditional_block_test_coverage'].items():
            if cov[key] != value: raise ValueError('Conditional coverage changed')
        coverages.append({'case': name, **cov})
        ids = set()
        for version in versions: ids.update(periods[version][name]['comparisons']['v6_vs_v7']['lost_baseline_event_ids'])
        for pair in paired.values(): ids.update(pair['lost_baseline_event_ids']); ids.update(pair['new_candidate_event_ids'])
        for event in paired['v9_vs_v10']['baseline']['primary_event_intervals']:
            if event['event_id'] not in ids: continue
            info = {'case': name, 'event_id': event['event_id'], 'source_sample_start': int(current.sample_index.iloc[event['start']]),
                    'source_sample_end_exclusive': int(current.sample_index.iloc[event['end_exclusive']-1])+1}
            for version in versions:
                saved = periods[version][name]
                info[version] = timing(rows[version], event, saved['selected'], saved['comparisons']['v6_vs_v7']['candidate'])
                info[version]['pending_after_clear'] = saved['selected'].get('pending_after_clear', False)
                info['lost_from_v6_by_'+version] = event['event_id'] in saved['comparisons']['v6_vs_v7']['lost_baseline_event_ids']
            timings.append(info)
        selected = period['selected']; prior = periods['v9'][name]['selected']
        path = run/name/'calibration_trials.csv.gz'; hashes[str(path)] = sha(path)
        trials = pd.read_csv(path, float_precision='round_trip')
        pending = trials[(trials.stage == 'earlier_selection') & trials.pending_after_clear.eq(True)]
        counts = Counter(reason for value in pending.rejection_reasons for reason in set(ast.literal_eval(value)))
        detail = {'case': name, 'v9_final': choice(prior), 'v9_status': prior['status'], 'v9_earlier': choice(prior['earlier_selected']),
            'v9_certification_rejection_reasons': prior['certification_rejection_reasons'],
            'v10_final': choice(selected), 'v10_status': selected['status'], 'v10_earlier': choice(selected['earlier_selected']),
            'v10_certification_rejection_reasons': selected['certification_rejection_reasons'],
            'earlier_selected_trial': trial_records(trial_match(trials, selected['earlier_selected'])),
            'v9_earlier_choice_in_v10_saved_grid': trial_records(trial_match(trials, prior['earlier_selected'], False)),
            'pending_grid_trials': len(pending), 'pending_grid_feasible_trials': int(pending.feasible.sum()),
            'pending_grid_rejection_counts': dict(counts),
            'pending_at_earlier_chosen_other_settings': trial_records(trial_match(trials, selected['earlier_selected'], True)),
            'earlier_pulse_certificate': selected['global_veto']['earlier_positive_reference_pulses'],
            'later_pulse_certificate': selected['certification']['positive_reference_pulses'],
            'all_four_pulse_certificate': selected['global_veto']['all_four_positive_reference_pulses'],
            'later_pending_evidence': selected['certification']['pending'],
            'interpretation': 'First-two saved grid rows only. No candidate rerun or test-based threshold selection; duplicate inactive-rescue policy recipes are counted as saved.'}
        policy_details.append(detail)
        combined = current[['sample_index','label','candidate']].copy()
        for version in ('v8','v9'): combined[version] = rows[version].candidate.to_numpy(np.int8)
        pool_parts.setdefault(period['source'], []).append(combined)
    source_comparisons = {}
    for source, parts in pool_parts.items():
        rows = pd.concat(parts, ignore_index=True)
        np.testing.assert_array_equal(np.diff(rows.sample_index), np.ones(len(rows)-1, int))
        source_comparisons[source] = {}
        for version in ('v8','v9'):
            pair = compare_rows(rows.label, rows[version], rows.candidate)
            pair['interpretation'] = f'Descriptive {version.upper()}/V10 original contiguous source axis; no new acceptance gate.'
            if pair['baseline'] != versions[version]['sources'][source]['v6_vs_v7']['candidate'] or pair['candidate'] != versions['v10']['sources'][source]['v6_vs_v7']['candidate']:
                raise ValueError('Pooled source metric mismatch')
            source_comparisons[source][version+'_vs_v10'] = pair
    for path, digest in hashes.items():
        if sha(path) != digest: raise ValueError('Input changed during diagnosis: '+path)
    diagnostic.update({'candidate_version': 'V10', 'previous_run': str(parent), 'earlier_run': str(earlier),
        'cross_run_input_sha256': hashes, 'cross_run_axis_verified': True, 'v9_scores_exactly_unchanged': True,
        'cross_run_period_comparison': comparisons, 'cross_run_source_comparison': source_comparisons,
        'timing_comparison': timings, 'conditional_coverage_by_period': coverages, 'policy_evidence_by_period': policy_details,
        'fresh_validation': False, 'policies_reexecuted_for_diagnosis': False,
        'statistical_change': 'No model or score change. Earlier feasibility/later certification/all-four veto add positive reference-pulse retention before rescue; pending-after-clear is selectable only with separate zero-normal and two-event/two-block evidence.',
        'pending_selected_periods': [p['case'] for p in versions['v10']['periods'] if p['selected']['pending_after_clear']],
        'timing_interpretation': 'Every timing uses its own saved selected threshold; none is a newly executed alternative. Identical V9/V10 raw scores isolate changes to the calibrated policy and fallback decisions.'})
    return diagnostic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--earlier', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); result = describe(args.run, args.parent, args.earlier)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream: json.dump(result, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'output': str(args.output), 'status_counts': result['status_counts'], 'pending_selected_periods': result['pending_selected_periods']}))


if __name__ == '__main__': main()
