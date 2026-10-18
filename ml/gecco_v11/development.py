"""Prespecified V11 retained-IF protection on unchanged, audited V10 models/scores.

All sources are disclosed development data. Each policy is chosen using only
the first two historical blocks and vetoed using the later two. Test scores
are opened after the new policy/bundle freeze. No model is fitted here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import time

import joblib
import numpy as np
import pandas as pd

from ml.gecco_v10.development import code_paths as parent_code_paths
from ml.gecco_v7.development_v2 import ROOT, now, sha, write, verify
from ml.gecco_v7.recalibrate_delayed import assess, summarize
from ml.gecco_v7.evidence import separate_scores
from ml.gecco_v11.calibration import calibrate, predict
from ml.gecco_v11.runtime import VERSION

ATTEMPT = 'v11_run01_preserve_retained_if_pulses'
EXPECTED_NAMES = ([f'{year}_fold_{k}' for year in ('2017', '2018') for k in range(1, 7)]
    + ['2019_disclosed_test', '2018-11', '2018-12', '2019-01', '2019-02', '2019-03', '2019-04'])
PARENT_FILES = ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz',
                'predictions.csv.gz', 'model_inspection.json', 'results.json')


def read(path):
    return json.loads(Path(path).read_text())


def parent_metadata(parent):
    results, plan, audit = [read(parent / name) for name in
                            ('results.json', 'plan.json', 'audit.json')]
    if (results.get('candidate_version') != 'V10' or results.get('complete_cases') != 19
            or results.get('expected_cases') != 19
            or results.get('all_prespecified_cases_complete') is not True
            or [p['case'] for p in results['periods']] != EXPECTED_NAMES
            or (parent / 'failed_case.json').exists()):
        raise ValueError('Exactly all19 completed V10 cases are required')
    if (audit.get('passed') is not True or audit.get('failed_checks') != 0
            or audit.get('complete_replayed_cases') != 19
            or audit.get('audit_version') != 'v10_pending_pulse_full_raw_sensor_replay_v1'
            or audit.get('attempt') != plan.get('attempt')
            or audit.get('hashes', {}).get('plan.json') != sha(parent / 'plan.json')
            or audit.get('hashes', {}).get('results.json') != sha(parent / 'results.json')):
        raise ValueError('A matching independent all19 V10 replay audit is required')
    if results.get('fresh_validation') is not False or results.get('development_only') is not True:
        raise ValueError('Parent scope must remain disclosed development')
    verify(plan)
    for case in EXPECTED_NAMES:
        for filename in PARENT_FILES:
            if sha(parent / case / filename) != audit['hashes'].get(case + '/' + filename):
                raise ValueError('Parent audited artifact changed: ' + case + '/' + filename)
    return results, plan, audit


def code_paths():
    return sorted(set(parent_code_paths() + [ROOT / 'ml/gecco_v11' / name
                    for name in ('development.py', 'calibration.py', 'runtime.py')]))


def load_outer(source):
    """The only outer-score read; called only after this case's new freeze."""
    return pd.read_csv(source / 'predictions.csv.gz', float_precision='round_trip')


def run_case(item, parent, out, plan):
    started = time.perf_counter(); verify(plan)
    name = item['case']; source = parent / name; dest = out / name; dest.mkdir()
    frozen = read(source / 'freeze.json')
    parent_hashes = {filename: sha(source / filename) for filename in PARENT_FILES}
    assert parent_hashes['bundle.joblib'] == frozen['bundle_sha256']
    bundle = joblib.load(source / 'bundle.joblib')
    assert bundle['version'] == 'v10_pulse_certified_pending_120s'
    assert bundle['max_fit_index'] == frozen['train'][1] - 1
    assert bundle['max_calibration_index'] == frozen['test'][0] - 1
    prior = ROOT / frozen['prior_folder']
    for filename, digest in frozen['prior_sha256'].items():
        assert sha(prior / filename) == digest, 'V6 cached input changed'
    cal = pd.read_csv(source / 'calibration_scores.csv.gz', float_precision='round_trip')
    local = pd.read_csv(prior / 'calibration_scores.csv.gz', float_precision='round_trip')
    starts = frozen['calibration_starts']
    np.testing.assert_array_equal(cal.sample_index, np.arange(starts[0], frozen['test'][0]))
    np.testing.assert_array_equal(cal.sample_index, local.sample_index)
    target = 'label' if item['source'] == 'WaterHub' else 'EVENT'
    np.testing.assert_array_equal(cal.label, local[target])
    masks = separate_scores({key: local[key].to_numpy() for key in
                             ('level', 'jump', 'sustained')}, cal.long_context.to_numpy())
    for key, values in masks.items():
        np.testing.assert_allclose(cal[key], values, rtol=0, atol=0, equal_nan=True)
    bounds = [value - starts[0] for value in starts + [frozen['test'][0]]]
    blocks = [{'labels': cal.label.iloc[a:b].to_numpy(np.int8),
               'reference': cal.reference.iloc[a:b].to_numpy(np.int8),
               'baseline': cal.baseline.iloc[a:b].to_numpy(np.int8),
               'long_scores': cal.long_context.iloc[a:b].to_numpy(),
               'rescue_scores': cal.rescue_long_context.iloc[a:b].to_numpy(),
               'source_start': starts[i]}
              for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:]))]
    print(json.dumps({'case': name, 'phase': 'past_pulse_selection_then_certification'}), flush=True)
    selected, trials = calibrate(blocks, cadence_seconds=60)
    cal['v10_candidate'] = cal.candidate
    cal['candidate'] = np.concatenate([predict(block['reference'], block['long_scores'], selected,
        rescue_scores=block['rescue_scores'], baseline=block['baseline']) for block in blocks])
    cal.to_csv(dest / 'calibration_scores.csv.gz', index=False)
    pd.DataFrame(trials).to_csv(dest / 'calibration_trials.csv.gz', index=False)
    updated = {**bundle, 'version': VERSION, 'selected': selected}
    joblib.dump(updated, dest / 'bundle.joblib', compress=3)
    shutil.copy2(source / 'model_inspection.json', dest / 'model_inspection.json')
    verify(plan)
    write(dest / 'freeze.json', {**frozen, 'frozen_at_utc': now(),
        'plan_sha256': sha(out / 'plan.json'), 'bundle_sha256': sha(dest / 'bundle.joblib'),
        'selected': selected, 'parent_folder': str(source.relative_to(ROOT)),
        'parent_sha256': parent_hashes, 'training_reused_without_refit': True})
    test = load_outer(source)
    np.testing.assert_array_equal(test.sample_index, np.arange(*frozen['test']))
    for filename, digest in parent_hashes.items():
        assert sha(source / filename) == digest, 'Parent artifact changed after selection'
    test['v10_candidate'] = test.candidate
    test['candidate'] = predict(test.reference.to_numpy(np.int8), test.long_context.to_numpy(),
        selected, rescue_scores=test.rescue_long_context.to_numpy(), baseline=test.baseline.to_numpy(np.int8))
    test.to_csv(dest / 'predictions.csv.gz', index=False)
    result = {'case': name, 'source': item['source'], 'development_only': True,
        'selected': selected, 'model_refitted': False, 'fit_status': item['fit_status'],
        'conditional_block_test_coverage': item['conditional_block_test_coverage'],
        'comparisons': assess(*(test[col].to_numpy(np.int8) for col in
                               ('label', 'baseline', 'reference', 'candidate'))),
        'seconds': time.perf_counter() - started}
    write(dest / 'results.json', result)
    brief = result['comparisons']['v6_vs_v7']
    print(json.dumps({'case': name, 'completed': True,
        'events': [brief[k]['confirmed_events'] for k in ('baseline', 'candidate')],
        'false_runs': [brief[k]['false_positive_runs'] for k in ('baseline', 'candidate')],
        'lost_events': len(brief['lost_baseline_event_ids']), 'noninferior': brief['noninferior'],
        'seconds': round(result['seconds'], 2)}), flush=True)
    return result, test


def execute(parent, out):
    parent_results, parent_plan, parent_audit = parent_metadata(parent)
    out.mkdir(parents=True, exist_ok=False)
    paths = code_paths()
    lineage = {name: sha(parent / name) for name in ('plan.json', 'results.json', 'audit.json')}
    inputs = dict(parent_plan['input_sha256'])
    for relative in list(lineage) + [case + '/' + name for case in EXPECTED_NAMES for name in PARENT_FILES]:
        path = parent / relative
        inputs[str(path.relative_to(ROOT))] = sha(path)
    plan = {'created_at_utc': now(), 'attempt': ATTEMPT, 'scope': 'all',
        'expected_cases': 19, 'limit_cases': 19, 'case_order': EXPECTED_NAMES,
        'development_only': True, 'fresh_validation': False, 'all_sources_previously_disclosed': True,
        'parent_run': str(parent.relative_to(ROOT)), 'parent_sha256': lineage,
        'parent_audit_passed': True, 'no_model_refit': True,
        'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in paths}, 'input_sha256': inputs,
        'method': 'Fixed audited V10 models and scores. One new hierarchy rule: baseline IF=1 and V6 reference=1 immediately releases and latches that reference episode. It never restores an IF alert removed by V6. Baseline is an explicit sensor prediction input, not a fabricated confidence value. The protected confirmation seed participates in first2 selection and late2/all4 certification. Pending cannot arise from an already protected or released episode. All V10 pulse, pending, rescue, availability and false-cost rules remain. All releases are actual alarms.',
        'pending_checks': 'Pure confirmation seed includes pending and retains original event-ID/delay/FP/availability checks before independent rescue. Added pending alarms are separately compared with protected unextended confirmation: zero added known-normal rows in first2, late2 and all4, and positive coverage across at least2original events in at least2blocks in both selection and certification. No artificial positive labels or delayed timestamps.',
        'calibration': 'Protection is integrated before candidate scoring, not applied after selection. Unchanged low/high threshold grids, normal exposure and primary event minima. First2 chronological past blocks choose one proposal; last2 certify or return V6 with no alternate search. Four-block original-axis veto remains. Pulse coverage must occur in the same contiguous known-positive segment within120s of the pulse positive intersection; independent rescue cannot hide a missing confirmation response.',
        'disclosure': 'Architecture informed by earlier disclosed failures. Chronological fitting/calibration and before-test policy freezes do not make these reused tests fresh independent validation.',
        'split': 'Exact19 parent expanding historical splits, gaps and causal scores preserved. No fitting on calibration or test. Policy/bundle hashes saved before each outer score read.',
        'acceptance': 'All19periods and eachsourcepool preserve confirmed eventIDs/availability, pairedextra delay<=120s and noFPcount/durationincrease vsbothIFandV6. Morepooledevents andfewerFPfragments, eachgainin>=2periods. Same metrics without point adjustment. TProwlossdescriptive.',
        'comparison_schema': 'Legacy if_vs_v7/v6_vs_v7 mean candidateV11; V10candidate saved separately for paired descriptive comparison only.',
        'certification_scope': 'Conditional certification of new policy; fixedV6 reference was originally calibrated on all4. Disclosed development, not fresh pipeline validation.',
        'cadence_seconds': 60, 'maximum_confirmation_seconds': 120,
        'deployment_approved': False, 'three_d_connected': False}
    for path in paths:
        destination = out / 'source' / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, destination)
    write(out / 'plan.json', plan)
    periods, source_rows = [], {}
    for item in parent_results['periods']:
        try:
            result, rows = run_case(item, parent, out, plan)
        except Exception as error:
            write(out / 'failed_case.json', {'case': item['case'], 'error': repr(error), 'at_utc': now()})
            raise
        periods.append(result); source_rows.setdefault(item['source'], []).append(rows)
    sources = {}
    for source, parts in source_rows.items():
        whole = pd.concat(parts, ignore_index=True)
        assert np.all(np.diff(whole.sample_index) == 1)
        sources[source] = assess(*(whole[col].to_numpy(np.int8) for col in
                                  ('label', 'baseline', 'reference', 'candidate')))
    verify(plan)
    result = {'completed_at_utc': now(), 'candidate_version': 'V11', 'development_only': True,
        'fresh_validation': False, 'model_refitted': False, 'complete_cases': len(periods),
        'expected_cases': 19, 'all_prespecified_cases_complete': len(periods) == 19,
        'maximum_allowed_extra_delay_seconds': 120, 'periods': periods,
        'sources': sources, 'summary': summarize(periods, sources)}
    write(out / 'results.json', result)
    print(json.dumps({'completed': True, 'cases': len(periods), 'summary': result['summary']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); execute(args.parent.resolve(), args.output.resolve())
