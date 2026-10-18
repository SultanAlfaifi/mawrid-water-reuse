"""One prespecified raw-IF evidence feature experiment under frozen V10 policy.

Original V9 features, reference models, onset weights and HGB parameters remain
fixed. Only HGB is refitted; the original IF estimator is reused unchanged.
All sources are previously disclosed development data. No 3D or actuation.
Legacy comparison keys ending in v7 mean candidate V12.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import shutil
import sys
import time

import joblib
import numpy as np
import pandas as pd
import sklearn

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ml.gecco_v7 import development_v2 as prior
from ml.gecco_v9.development import code_paths as prior_code_paths
from ml.gecco_v7.recalibrate_delayed import assess, summarize
from ml.gecco_v10.calibration import calibrate, predict
from ml.gecco_v7.evidence import separate_scores
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer

GAP = prior.GAP
now, sha, write, verify = prior.now, prior.sha, prior.write, prior.verify
cases = prior.cases
EXPECTED_NAMES = ([f'{year}_fold_{k}' for year in ('2017', '2018') for k in range(1, 7)]
    + ['2019_disclosed_test', '2018-11', '2018-12', '2019-01', '2019-02', '2019-03', '2019-04'])
REFERENCE_FILES = ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz', 'predictions.csv.gz')


def reference_inventory():
    """Hash exact original reference artifacts before source-value access."""
    result = {}
    for i, name in enumerate(EXPECTED_NAMES):
        folder = (prior.GECCO_PRIOR if i < 13 else prior.WATERHUB_PRIOR) / name
        result[name] = {'folder': str(folder.relative_to(ROOT)),
                        'files': {filename: sha(folder / filename) for filename in REFERENCE_FILES}}
    return result


def score_gap(model, frame):
    """Enforce the sensor-only API even though the frozen scorer also filters."""
    return prior.score_gap(model, frame.loc[:, model.channels])


def conditional_coverage_gap(model, frame):
    """Diagnostic only; current evidence never changes original availability."""
    values = model.conditional_observed(frame.iloc[GAP:].loc[:, model.channels])
    values = np.asarray(values, dtype=bool)
    if values.shape != (max(0, len(frame) - GAP),):
        raise ValueError('Conditional coverage must retain the original row axis')
    return np.r_[np.zeros(min(GAP, len(frame)), dtype=bool), values]


def code_paths():
    return sorted(set(prior_code_paths() + [ROOT / 'ml/gecco_v10/calibration.py'] + [ROOT / 'ml/gecco_v12' / filename
                       for filename in ('development.py', 'baseline_evidence.py', 'runtime.py')]))


def run_case(case, out, plan):
    verify(plan)
    folder = out / case['name']; folder.mkdir()
    started = time.perf_counter()
    old = case['prior']; old_freeze = json.loads((old / 'freeze.json').read_text())
    geometry = old_freeze['case'] if case['source'] == 'WaterHub' else old_freeze
    assert geometry['train'] == [0, len(case['train'])]
    cal_starts = geometry['calibration_boundaries'][:-1] if case['source'] == 'WaterHub' else geometry['calibration_starts']
    assert cal_starts == case['cal_starts']
    assert geometry['test'] == [case['test_start'], case['test_end']]
    prior_hashes = {filename: sha(old / filename) for filename in
                    ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz', 'predictions.csv.gz')}
    pinned_reference = plan['reference_sha256'][case['name']]
    assert pinned_reference['folder'] == str(old.relative_to(ROOT)), 'Reference folder changed since plan'
    assert pinned_reference['files'] == prior_hashes, 'Reference changed since upfront plan freeze'
    assert prior_hashes['bundle.joblib'] == old_freeze['bundle_sha256']
    reference_bundle = joblib.load(old / 'bundle.joblib')
    assert reference_bundle['max_fit_index'] == len(case['train']) - 1
    assert reference_bundle['max_calibration_index'] == case['test_start'] - 1
    print(json.dumps({'case': case['name'], 'phase': 'fit_if_evidence_conditional_hgb', 'train_rows': len(case['train'])}), flush=True)
    baseline_estimator = reference_bundle['prior_bundle']['model'].baseline_
    baseline_digest_before = joblib.hash(baseline_estimator, hash_name='sha1')
    model = BaselineEvidenceHGBScorer(case['channels'], baseline_estimator).fit(
        case['train'].loc[:, case['channels']], case['train'][case['target']].to_numpy(np.int8))
    assert joblib.hash(baseline_estimator, hash_name='sha1') == baseline_digest_before, 'Frozen IF changed during HGB fit'
    assert joblib.hash(model.baseline_estimator_, hash_name='sha1') == baseline_digest_before, 'Confidence model did not retain identical IF'
    write(folder / 'model_inspection.json', model.inspection())
    saved = pd.read_csv(old / 'calibration_scores.csv.gz', float_precision='round_trip')
    np.testing.assert_array_equal(saved.sample_index, np.arange(case['cal_starts'][0], case['test_start']))
    labels = np.concatenate([part[case['target']].to_numpy(np.int8) for part in case['cal']])
    np.testing.assert_array_equal(labels, saved[case['target']].to_numpy(np.int8))
    bounds = np.r_[0, np.cumsum([len(part) for part in case['cal']])]
    if case['continuous_cal']:
        whole = score_gap(model, pd.concat(case['cal'], ignore_index=True))
        long_parts = [whole[a:b] for a, b in zip(bounds[:-1], bounds[1:])]
        coverage = conditional_coverage_gap(model, pd.concat(case['cal'], ignore_index=True))
        coverage_parts = [coverage[a:b] for a, b in zip(bounds[:-1], bounds[1:])]
    else:
        long_parts = [score_gap(model, part) for part in case['cal']]
        coverage_parts = [conditional_coverage_gap(model, part) for part in case['cal']]
    blocks, cal_rows = [], []
    for index, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        rows = saved.iloc[a:b]
        components = {key.removeprefix('rescue__'): rows[key].to_numpy() for key in rows.columns if key.startswith('rescue__')}
        reference = prior.v6_predict(rows.baseline.to_numpy(np.int8), rows.guarded.to_numpy(np.int8), components, reference_bundle['selected'])
        masks = separate_scores({key: rows[key].to_numpy() for key in ('level', 'jump', 'sustained')}, long_parts[index])
        blocks.append({'labels': labels[a:b], 'reference': reference, 'long_scores': long_parts[index],
                       'rescue_scores': masks['rescue_long_context'], 'source_start': int(case['cal_starts'][index])})
        cal_rows.append(pd.DataFrame({'sample_index': rows.sample_index.to_numpy(), 'label': labels[a:b],
            'baseline': rows.baseline.to_numpy(np.int8), 'reference': reference,
            'long_context': long_parts[index], 'conditional_observed': coverage_parts[index], **masks}))
    print(json.dumps({'case': case['name'], 'phase': 'early_selection_then_late_certification', 'fit_status': model.fit_status_}), flush=True)
    selected, trials = calibrate(blocks, cadence_seconds=60)
    for rows, block in zip(cal_rows, blocks):
        rows['candidate'] = predict(block['reference'], block['long_scores'], selected, block['rescue_scores'])
    pd.concat(cal_rows, ignore_index=True).to_csv(folder / 'calibration_scores.csv.gz', index=False)
    pd.DataFrame(trials).to_csv(folder / 'calibration_trials.csv.gz', index=False)
    bundle = {'version': 'v12_if_evidence_hgb_pulse_certified_120s', 'long_model': model,
              'reference_bundle': reference_bundle, 'selected': selected, 'sample_seconds': 60,
              'max_fit_index': len(case['train']) - 1, 'max_calibration_index': case['test_start'] - 1,
              'gap_samples': GAP}
    joblib.dump(bundle, folder / 'bundle.joblib', compress=3)
    verify(plan)
    write(folder / 'freeze.json', {'frozen_at_utc': now(), 'development_only': True,
          'plan_sha256': sha(out / 'plan.json'), 'prior_folder': str(old.relative_to(ROOT)),
          'prior_sha256': prior_hashes, 'train': [0, len(case['train'])],
          'calibration_starts': case['cal_starts'], 'continuous_cal': case['continuous_cal'],
          'test': [case['test_start'], case['test_end']], 'bundle_sha256': sha(folder / 'bundle.joblib'),
          'selected': selected})
    # Outer measurement values/labels for this case are loaded only after freeze.
    test = case['load_test'](); labels = test[case['target']].to_numpy(np.int8)
    long_scores = score_gap(model, test)
    conditional_observed = conditional_coverage_gap(model, test)
    cached = pd.read_csv(old / 'predictions.csv.gz', float_precision='round_trip')
    for filename, digest in prior_hashes.items():
        assert sha(old / filename) == digest, 'V6 artifact changed'
    np.testing.assert_array_equal(cached.sample_index, np.arange(case['test_start'], case['test_end']))
    np.testing.assert_array_equal(labels, cached[case['target']].to_numpy(np.int8))
    base_column, ref_column = ('baseline_prediction', 'prediction') if case['source'] == 'WaterHub' else ('baseline', 'candidate')
    baseline, reference = cached[base_column].to_numpy(np.int8), cached[ref_column].to_numpy(np.int8)
    masks = separate_scores({key: cached[key].to_numpy() for key in ('level', 'jump', 'sustained')}, long_scores)
    candidate = predict(reference, long_scores, selected, masks['rescue_long_context'])
    rows = pd.DataFrame({'sample_index': cached.sample_index, 'label': labels, 'baseline': baseline,
                        'reference': reference, 'candidate': candidate, 'long_context': long_scores,
                        'conditional_observed': conditional_observed, **masks})
    rows.to_csv(folder / 'predictions.csv.gz', index=False)
    result = {'case': case['name'], 'source': case['source'], 'development_only': True,
              'comparisons': assess(labels, baseline, reference, candidate), 'selected': selected,
              'conditional_block_test_coverage': {
                  'current_observed_rows_after_gap': int(conditional_observed.sum()),
                  'observed_on_reference_available_rows': int((conditional_observed & (reference >= 0)).sum()),
                  'reference_available_rows': int((reference >= 0).sum()),
                  'diagnostic_only_not_prediction_availability': True},
              'fit_status': model.fit_status_, 'seconds': time.perf_counter() - started}
    write(folder / 'results.json', result)
    brief = result['comparisons']['v6_vs_v7']
    print(json.dumps({'case': case['name'], 'completed': True,
        'events': [brief[m]['confirmed_events'] for m in ('baseline', 'candidate')],
        'false_runs': [brief[m]['false_positive_runs'] for m in ('baseline', 'candidate')],
        'lost_events': len(brief['lost_baseline_event_ids']), 'noninferior': brief['noninferior'],
        'seconds': round(result['seconds'], 2)}), flush=True)
    return result, rows


def execute(out):
    out.mkdir(parents=True, exist_ok=False)
    paths = code_paths()
    inputs = [prior.WATERHUB_ADAPTED]
    for year in ('2017', '2018', '2019'):
        inputs.extend((ROOT / f'data/external/gecco{year}').glob('*.csv'))
    references = reference_inventory()
    for record in references.values():
        inputs.extend(ROOT / record['folder'] / filename for filename in REFERENCE_FILES)
    plan = {'created_at_utc': now(), 'scope': 'all', 'limit_cases': 19, 'expected_cases': 19,
        'attempt': 'v12_run01_if_raw_score_feature_hgb', 'development_only': True,
        'all_sources_previously_disclosed': True, 'fresh_validation': False,
        'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in paths},
        'input_sha256': {str(p.relative_to(ROOT)): sha(p) for p in inputs},
        'reference_sha256': references,
        'case_order': EXPECTED_NAMES,
        'single_statistical_change': 'Append two features to unchanged V9 representation: original fitted IF raw anomaly score and finite observed mask. Build baseline15 sensor features using frozen implementation and score only with the unchanged training-fitted IF. No calibrated IF threshold, alarm policy, future labels or other RecoveryDetector state enters the confidence scorer. Original conditional residuals, references, HGB hyperparameters, onset weights and row availability unchanged. IF missing or unavailable => feature0 and mask0; this is not raw-sensor imputation.',
        'calibration_contract': 'Use the already frozen V10 positive-pulse/pending certification, not the V11 hard protection. This is one new feature experiment under that fixed policy. No extra threshold grid, model family search or revised acceptance gate.',
        'fitting_disclosure': 'Original IF is reused without refitting. Its training scores are in-sample representation features, not cross-fitted estimates. The HGB is fitted only on the original training subset. These are reused disclosed development periods; correct temporal splits do not create fresh independent evidence.',
        'streaming_limitation': 'Raw baseline15 rolling statistics depend on finite-precision history. Mathematical lookback bounds alone do not qualify a cropped streaming implementation; separate numerical parity evidence is required.',
        'weights': 'Normal0.5 uniformly; positive0.125 uniformly by point +0.125 uniformly across eligible contiguous segments +0.25 uniformly across known-onset events and eligible rows at actual offsets0,1,2. Known onset requires previouslabel0. No moving unavailable onset rows later. If no eligible known onset exists, redistribute0.25 to segment-uniform mass (0.375). Unknown labels always zero weight.',
        'onset_window': 'Three samples; at current60s cadence offsets0,60,120s. This training emphasis is not an inference latency guarantee.',
        'reference': 'Immutable V6run04 GECCO and frozen six-month WaterHub; original IF also compared.',
        'split': 'Exact13GECCO+6WaterHub expanding historical training geometry. Four contiguous past calibration blocks. No model fitting on calibration/test.',
        'selection': 'First2 past blocks choose one fixed V10 pulse-retaining pending policy; last2 certify without retuning and all4 veto. Identical low/high grids, normal/event evidence, zero-added-normal pending/rescue checks, positive-pulse ownership and 120s cap. Unsupported or failed certificate returns V6. Fixed V6 itself previously used all4 calibration blocks.',
        'reset': 'Discard first120rows before feature generation perindependentcal/test segment. Partial causal longcontext1440; first60remainingrows unavailable. GECCO2019calfeaturescontinuousafteronegap, policiesreset4blocks.',
        'acceptance': 'All19periods and eachsourcepool preserve confirmed reference eventIDs, availability, paired extraeventdelay<=120s, noFPcount/duration increase vsbothIFandV6. Pooledmoreevents/fewerFPfragments; eachgainin>=2periods. TProwlossdescriptive underuserauthorized<=120s experiment.',
        'comparison_schema': 'Legacy keys if_vs_v7 and v6_vs_v7 denote currentcandidate V12; all metrics and output columns retain the independently audited schema.',
        'cadence_seconds': 60, 'maximum_confirmation_seconds': 120,
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__, 'sklearn': sklearn.__version__},
        'no_3d_or_actuator_integration': True}
    for path in paths:
        dest = out / 'source' / path.relative_to(ROOT); dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, dest)
    write(out / 'plan.json', plan)
    periods, source_rows = [], {}
    for case in cases('all'):
        try:
            result, rows = run_case(case, out, plan)
        except Exception as error:
            write(out / 'failed_case.json', {'case': case['name'], 'error': repr(error), 'at_utc': now()})
            raise
        periods.append(result); source_rows.setdefault(case['source'], []).append(rows)
    sources = {}
    for name, parts in source_rows.items():
        whole = pd.concat(parts, ignore_index=True)
        assert np.all(np.diff(whole.sample_index) == 1)
        sources[name] = assess(*(whole[c].to_numpy(np.int8) for c in ('label', 'baseline', 'reference', 'candidate')))
    verify(plan)
    result = {'completed_at_utc': now(), 'development_only': True, 'fresh_validation': False,
              'candidate_version': 'V12', 'complete_cases': len(periods), 'expected_cases': 19,
              'all_prespecified_cases_complete': len(periods) == 19, 'maximum_allowed_extra_delay_seconds': 120,
              'periods': periods, 'sources': sources, 'summary': summarize(periods, sources)}
    write(out / 'results.json', result)
    print(json.dumps({'completed': True, 'cases': len(periods), 'summary': result['summary']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    execute(parser.parse_args().output.resolve())
