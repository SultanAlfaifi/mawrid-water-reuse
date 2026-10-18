"""Post-test V9/V8 diagnosis from saved disclosed-development outputs only.

All 19 results must be complete before row files are opened. This script does
not fit models, select policies, try thresholds, or access source datasets.
Comparisons use identical original row axes and the frozen primary event rule.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.gecco_v6.unknown_label_metrics import comparison
from ml.gecco_v7_audits.diagnose_certified import diagnose_run, _episodes
from ml.gecco_v7_audits.diagnose import quantiles
from ml.gecco_v8.report import EXPECTED_NAMES


ROOT = Path(__file__).resolve().parents[2]


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())


def complete_result(run, version):
    result = read(run / 'results.json')
    if (result.get('candidate_version') != version or result.get('complete_cases') != 19
            or result.get('expected_cases') != 19 or result.get('all_prespecified_cases_complete') is not True
            or [p.get('case') for p in result.get('periods', [])] != EXPECTED_NAMES
            or not result.get('completed_at_utc') or (run / 'failed_case.json').exists()
            or result.get('development_only') is not True or result.get('fresh_validation') is not False):
        raise ValueError(f'All 19 fixed {version} disclosed-development results must be complete before reading scores')
    return result


def compare_rows(labels, before, after, cadence=60):
    result = comparison(np.asarray(labels, np.int8), np.asarray(before, np.int8), np.asarray(after, np.int8), cadence)
    result['lost_positive_alarm_rows'] = int(((np.asarray(labels) == 1) & (np.asarray(before) == 1) & (np.asarray(after) != 1)).sum())
    result['maximum_observed_paired_extra_delay_seconds'] = max((x['extra_delay_seconds'] for x in result['paired_extra_delays']), default=None)
    result['noninferior_with_120s_limit'] = bool(not result['lost_baseline_event_ids'] and result['sensor_availability_equal']
        and all(x['extra_delay_seconds'] <= 120 for x in result['paired_extra_delays'])
        and result['candidate']['false_positive_runs'] <= result['baseline']['false_positive_runs']
        and result['candidate']['fp_duration_seconds'] <= result['baseline']['fp_duration_seconds'])
    result['interpretation'] = 'Descriptive comparison with V8 on the same original axis; does not add or alter the declared IF/V6 acceptance gates.'
    return result


def timing(rows, event, selected, metric):
    """Inspect the already selected confidence threshold; never scan a new one."""
    start, end = event['start'], event['end_exclusive']
    score = rows.long_context.to_numpy(float)
    reference = rows.reference.to_numpy(np.int8)
    candidate = rows.candidate.to_numpy(np.int8)
    low, cadence = selected['low_threshold'], selected['cadence_seconds']
    first = dict(zip(metric['confirmed_event_ids'], metric['confirmed_times'])).get(event['event_id'])
    pulses = []
    for a, b in _episodes(reference):
        if b <= start or a >= end: continue
        a, b = int(a), int(b)
        # Reference pulse may begin before the event. Keep that original pulse
        # start; do not invent a new deadline by cropping to the event onset.
        window = score[a:end]
        hits = np.flatnonzero(np.isfinite(window) & (window >= low)) if low is not None else np.array([], int)
        unknown = np.flatnonzero(~np.isfinite(score[a:b]))
        crossing = float(hits[0] * cadence) if len(hits) else None
        pulses.append({'source_sample_start': int(rows.sample_index.iloc[a]), 'start_index': a, 'end_exclusive': b,
            'length_samples': b-a, 'duration_seconds': float((b-a)*cadence),
            'confidence_first_values_including_after_pulse': [float(x) if np.isfinite(x) else None for x in window[:5]],
            'pulse_confidence': quantiles(score[a:b]),
            'first_raw_confidence_crossing_seconds_before_event_end': crossing,
            'finite_confidence_reaches_fixed_threshold_within120s': bool(crossing is not None and crossing <= 120),
            'first_unknown_confidence_seconds_within_pulse': float(unknown[0]*cadence) if len(unknown) else None,
            'candidate_alarm_rows_within_reference_pulse': int((candidate[a:b] == 1).sum()),
            'whole_reference_pulse_removed': bool(not (candidate[a:b] == 1).any()),
            'pulse_no_longer_than_selected_deadline': bool(b-a <= selected['confirmation_samples']),
            'left_censored_by_test_boundary': bool(a == 0), 'right_censored_by_test_boundary': bool(b == len(rows))})
    candidate_rows = int((candidate[start:end] == 1).sum())
    return {'fixed_low_threshold': low, 'fixed_high_threshold': selected['high_threshold'],
        'confirmation_enabled': low is not None, 'confirmation_samples': selected['confirmation_samples'],
        'cadence_seconds': cadence, 'confirmed_index': first, 'candidate_alarm_rows_inside_event': candidate_rows,
        'reference_alarm_rows_inside_event': int((reference[start:end] == 1).sum()),
        'raw_event_confidence_distribution': quantiles(score[start:end]), 'reference_pulses': pulses,
        'descriptive_cause_flags': {
            'no_candidate_alarm_inside_event': candidate_rows == 0,
            'alarm_inside_event_but_no_qualified_quiet_to_alarm_transition': candidate_rows > 0 and first is None,
            'all_intersecting_reference_pulses_removed': bool(pulses) and all(p['whole_reference_pulse_removed'] for p in pulses),
            'some_short_reference_pulse_removed': any(p['whole_reference_pulse_removed'] and p['pulse_no_longer_than_selected_deadline'] for p in pulses)},
        'interpretation': 'Post-test timing at this version\'s own frozen threshold. A later crossing is not an implemented alarm, and crossing within120s after a cleared pulse does not prove retention under the existing policy.'}


def coverage(rows):
    observed = rows.conditional_observed.to_numpy(bool)
    reference_available = rows.reference.to_numpy(np.int8) >= 0
    result = {'total_rows': len(rows), 'current_observed_rows_after_gap': int(observed.sum()),
        'observed_on_reference_available_rows': int((observed & reference_available).sum()),
        'reference_available_rows': int(reference_available.sum()), 'diagnostic_only_not_prediction_availability': True}
    for value, key in ((-1, 'unknown'), (0, 'normal'), (1, 'positive')):
        mask = reference_available & (rows.label.to_numpy(np.int8) == value)
        result[key] = {'reference_available_rows': int(mask.sum()), 'conditional_observed_rows': int((observed & mask).sum())}
    return result


def describe(run, previous):
    run, previous = Path(run).resolve(), Path(previous).resolve()
    new, old = complete_result(run, 'V9'), complete_result(previous, 'V8')
    input_hashes = {str(path): sha(path) for path in (run/'results.json', previous/'results.json', run/'plan.json', previous/'plan.json')}
    diagnostic = diagnose_run(run)
    diagnostic['notes'][0] = (f"All {len(diagnostic['active_periods'])} active policies are analyzed; "
                             f"all {len(diagnostic['fallbacks'])} reference-retention decisions are retained.")
    old_periods = {p['case']: p for p in old['periods']}
    comparisons, timing_events, coverage_periods, source_parts = [], [], [], {}
    for period in new['periods']:
        name = period['case']; prior = old_periods[name]
        if period['source'] != prior['source']: raise ValueError('Source identity changed')
        paths = [previous/name/'predictions.csv.gz', run/name/'predictions.csv.gz']
        for path in paths: input_hashes[str(path)] = sha(path)
        before, after = [pd.read_csv(p, float_precision='round_trip') for p in paths]
        for key in ('sample_index', 'label', 'baseline', 'reference'):
            np.testing.assert_array_equal(before[key], after[key])
        if period['selected']['cadence_seconds'] != prior['selected']['cadence_seconds']:
            raise ValueError('Paired run cadence must agree')
        cadence = period['selected']['cadence_seconds']
        paired = compare_rows(after.label, before.candidate, after.candidate, cadence)
        if (paired['baseline'] != prior['comparisons']['v6_vs_v7']['candidate']
                or paired['candidate'] != period['comparisons']['v6_vs_v7']['candidate']):
            raise ValueError('Same-axis recomputation disagrees with saved candidate metrics')
        comparisons.append({'case': name, 'source': period['source'], 'v8_vs_v9': paired,
            'v8_policy': prior['selected']['decision'], 'v9_policy': period['selected']['decision'],
            'v8_reference_lost_ids': prior['comparisons']['v6_vs_v7']['lost_baseline_event_ids'],
            'v9_reference_lost_ids': period['comparisons']['v6_vs_v7']['lost_baseline_event_ids']})
        detail = coverage(after)
        for key, value in period['conditional_block_test_coverage'].items():
            if detail[key] != value: raise ValueError('Coverage diagnostic disagrees with saved result')
        coverage_periods.append({'case': name, **detail})
        interesting_ids = set(prior['comparisons']['v6_vs_v7']['lost_baseline_event_ids'])
        interesting_ids.update(period['comparisons']['v6_vs_v7']['lost_baseline_event_ids'])
        interesting_ids.update(paired['lost_baseline_event_ids'])
        interesting_ids.update(paired['new_candidate_event_ids'])
        for event in paired['baseline']['primary_event_intervals']:
            if event['event_id'] not in interesting_ids: continue
            timing_events.append({'case': name, 'event_id': event['event_id'],
                'source_sample_start': int(after.sample_index.iloc[event['start']]),
                'source_sample_end_exclusive': int(after.sample_index.iloc[event['end_exclusive']-1])+1,
                'lost_from_v6_by_v8': event['event_id'] in prior['comparisons']['v6_vs_v7']['lost_baseline_event_ids'],
                'lost_from_v6_by_v9': event['event_id'] in period['comparisons']['v6_vs_v7']['lost_baseline_event_ids'],
                'lost_from_v8_by_v9': event['event_id'] in paired['lost_baseline_event_ids'],
                'v8': timing(before, event, prior['selected'], paired['baseline']),
                'v9': timing(after, event, period['selected'], paired['candidate'])})
        joined = after[['sample_index', 'label', 'candidate']].copy()
        joined['v8'] = before.candidate.to_numpy(np.int8)
        source_parts.setdefault(period['source'], []).append(joined)
    source_comparisons = {}
    for source, parts in source_parts.items():
        rows = pd.concat(parts, ignore_index=True)
        np.testing.assert_array_equal(np.diff(rows.sample_index), np.ones(len(rows)-1, dtype=int))
        paired = compare_rows(rows.label, rows.v8, rows.candidate)
        if (paired['baseline'] != old['sources'][source]['v6_vs_v7']['candidate']
                or paired['candidate'] != new['sources'][source]['v6_vs_v7']['candidate']):
            raise ValueError('Contiguous source-axis comparison disagrees with saved pools')
        source_comparisons[source] = paired
    for path, digest in input_hashes.items():
        if sha(path) != digest: raise AssertionError('Saved artifact changed during diagnosis: '+path)
    diagnostic.update({'candidate_version': 'V9', 'previous_run': str(previous),
        'cross_run_input_sha256': input_hashes, 'cross_run_axis_verified': True,
        'cross_run_period_comparison': comparisons, 'cross_run_source_comparison': source_comparisons,
        'timing_comparison': timing_events, 'conditional_coverage_by_period': coverage_periods,
        'fresh_validation': False, 'statistical_change': 'Only3*C current normal-only conditional ridge residual/mask features added to V8; original features, references, weights, HGB, calibration, policies and acceptance unchanged.',
        'timing_interpretation': 'Confidence is compared at each previously selected version-specific threshold; no test threshold is selected, no timing rule is changed, and observed gains are not fresh validation.'})
    return diagnostic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = describe(args.run, args.previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'output': str(args.output), 'status_counts': result['status_counts'],
        'lost_reference_events': {p['case']: [e['event_id'] for e in p['lost_events']] for p in result['active_periods']}}))


if __name__ == '__main__': main()
