"""Descriptive V8/V7 comparison after all prespecified development cases finish.

This reads disclosed saved predictions only. It neither fits a model nor
searches a threshold, and never accesses a fresh source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.gecco_v7_audits.diagnose_certified import diagnose_run


ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(run, previous):
    run, previous = Path(run).resolve(), Path(previous).resolve()
    diagnostic = diagnose_run(run)
    diagnostic['notes'][0] = (
        f"All {len(diagnostic['active_periods'])} active policies are analyzed; "
        f"all {len(diagnostic['fallbacks'])} reference-retention decisions are retained.")
    old_path = previous / 'results.json'
    old_hash = sha(old_path)
    old = json.loads(old_path.read_text())
    new = json.loads((run / 'results.json').read_text())
    if new.get('candidate_version') != 'V8' or old.get('complete_cases') != 19:
        raise ValueError('Expected completed V8 and V7 development runs')
    old_periods = {p['case']: p for p in old['periods']}
    comparisons = []
    input_hashes = {str(old_path.relative_to(ROOT)): old_hash}
    for period in new['periods']:
        name = period['case']
        prior = old_periods[name]
        paths = [previous / name / 'predictions.csv.gz', run / name / 'predictions.csv.gz']
        hashes = [sha(p) for p in paths]
        old_rows, new_rows = [pd.read_csv(p, float_precision='round_trip') for p in paths]
        for key in ('sample_index', 'label', 'baseline', 'reference'):
            np.testing.assert_array_equal(old_rows[key], new_rows[key])
        before = prior['comparisons']['v6_vs_v7']['candidate']
        after = period['comparisons']['v6_vs_v7']['candidate']
        before_ids, after_ids = map(set, (before['confirmed_event_ids'], after['confirmed_event_ids']))
        metrics = ('confirmed_events', 'false_positive_runs', 'fp_duration_seconds', 'tp', 'fp', 'f1_observed_points')
        comparisons.append({
            'case': name,
            'source': period['source'],
            'v7': {key: before[key] for key in metrics},
            'v8': {key: after[key] for key in metrics},
            'lost_v7_event_ids': sorted(before_ids - after_ids),
            'additional_vs_v7_event_ids': sorted(after_ids - before_ids),
            'reference_event_ids_lost_by_v8': period['comparisons']['v6_vs_v7']['lost_baseline_event_ids'],
            'v7_policy': prior['selected']['decision'],
            'v8_policy': period['selected']['decision'],
            'interpretation': 'Descriptive comparison; method was proposed after prior development results were disclosed.',
        })
        for path, digest in zip(paths, hashes):
            if sha(path) != digest:
                raise AssertionError('Saved scores changed during comparison')
            input_hashes[str(path.relative_to(ROOT))] = digest
    if sha(old_path) != old_hash:
        raise AssertionError('Prior result changed during comparison')
    diagnostic.update({
        'candidate_version': 'V8',
        'previous_run': str(previous.relative_to(ROOT)),
        'cross_run_input_sha256': input_hashes,
        'cross_run_period_comparison': comparisons,
        'fresh_validation': False,
        'statistical_change': 'Only training weights emphasize known event onset offsets 0,1,2. Calibration, reference and policy remain frozen.',
    })
    return diagnostic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = describe(args.run, args.previous)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'output': str(args.output), 'status_counts': result['status_counts'],
        'lost_reference_events': {p['case']: [e['event_id'] for e in p['lost_events']]
                                  for p in result['active_periods']}}))


if __name__ == '__main__':
    main()
