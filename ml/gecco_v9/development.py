"""One prespecified conditional-residual feature attempt on already disclosed development data.

Only current normal-conditional residual features differ from V8 run01.
Original features, references, onset weights, parameters, calibration, alarm policy,
source geometry, reference models and acceptance criteria remain fixed.
Legacy comparison keys ending in v7 mean the current candidate (V9 here).
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
from ml.gecco_v8.development import code_paths as prior_code_paths
from ml.gecco_v7.recalibrate_delayed import assess, summarize
from ml.gecco_v7.calibration_certified import calibrate, predict
from ml.gecco_v7.evidence import separate_scores
from ml.gecco_v9.conditional import ConditionalResidualHGBScorer

GAP = prior.GAP
now, sha, write, verify = prior.now, prior.sha, prior.write, prior.verify
cases = prior.cases


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
    return sorted(set(prior_code_paths() + [ROOT / 'ml/gecco_v9' / filename
                       for filename in ('development.py', 'conditional.py', 'runtime.py')]))


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
    assert prior_hashes['bundle.joblib'] == old_freeze['bundle_sha256']
    reference_bundle = joblib.load(old / 'bundle.joblib')
    assert reference_bundle['max_fit_index'] == len(case['train']) - 1
    assert reference_bundle['max_calibration_index'] == case['test_start'] - 1
    print(json.dumps({'case': case['name'], 'phase': 'fit_conditional_residual_hgb', 'train_rows': len(case['train'])}), flush=True)
    model = ConditionalResidualHGBScorer(case['channels']).fit(
        case['train'].loc[:, case['channels']], case['train'][case['target']].to_numpy(np.int8))
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
    bundle = {'version': 'v9_conditional_hgb_temporally_certified_120s', 'long_model': model,
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
    plan = {'created_at_utc': now(), 'scope': 'all', 'limit_cases': 19, 'expected_cases': 19,
        'attempt': 'v9_run01_conditional_residual_hgb_certified', 'development_only': True,
        'all_sources_previously_disclosed': True, 'fresh_validation': False,
        'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in paths},
        'input_sha256': {str(p.relative_to(ROOT)): sha(p) for p in inputs},
        'single_statistical_change': 'Only3*Ccurrent cross-sensor normal-conditional residual features are appended to V8run01. Same original features, original normal references, onset weights, HGB parameters, temporal certification, inference policy and acceptance gates. Ridge alpha1/intercept/SVD trained only complete known-normal training rows; minimum128, allreference support,C>=2. Residualscale=max(q75absnormalresidual,noise_floor/levelscale,1e-6); clip64; unsupported/missing getszero+mask0; original availability unchanged. Numerical fit failure/nonfinite parameters disables wholeaddedblock; nonfinite inference disables addedblock for thatrow, without raw clipping/subset selection. Conditional coverage columns are descriptive only and never enter alarm policy.',
        'weights': 'Normal0.5 uniformly; positive0.125 uniformly by point +0.125 uniformly across eligible contiguous segments +0.25 uniformly across known-onset events and eligible rows at actual offsets0,1,2. Known onset requires previouslabel0. No moving unavailable onset rows later. If no eligible known onset exists, redistribute0.25 to segment-uniform mass (0.375). Unknown labels always zero weight.',
        'onset_window': 'Three samples; at current60s cadence offsets0,60,120s. This training emphasis is not an inference latency guarantee.',
        'reference': 'Immutable V6run04 GECCO and frozen six-month WaterHub; original IF also compared.',
        'split': 'Exact13GECCO+6WaterHub expanding historical training geometry. Four contiguous past calibration blocks. No model fitting on calibration/test.',
        'selection': 'First2calibrationblocks choose one candidate with unchanged V7delayed grid; last2certify withoutretuning, with all4boundaryveto on pureseed andcandidate. Unsupported/failed certificate returnsV6. Conditional policy certification: fixedV6itself previously usedall4calblocks.',
        'reset': 'Discard first120rows before feature generation perindependentcal/test segment. Partial causal longcontext1440; first60remainingrows unavailable. GECCO2019calfeaturescontinuousafteronegap, policiesreset4blocks.',
        'acceptance': 'All19periods and eachsourcepool preserve confirmed reference eventIDs, availability, paired extraeventdelay<=120s, noFPcount/duration increase vsbothIFandV6. Pooledmoreevents/fewerFPfragments; eachgainin>=2periods. TProwlossdescriptive underuserauthorized<=120s experiment.',
        'comparison_schema': 'Legacy keys if_vs_v7 and v6_vs_v7 denote currentcandidate V9; all metrics and output columns retain the independently audited schema.',
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
              'candidate_version': 'V9', 'complete_cases': len(periods), 'expected_cases': 19,
              'all_prespecified_cases_complete': len(periods) == 19, 'maximum_allowed_extra_delay_seconds': 120,
              'periods': periods, 'sources': sources, 'summary': summarize(periods, sources)}
    write(out / 'results.json', result)
    print(json.dumps({'completed': True, 'cases': len(periods), 'summary': result['summary']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    execute(parser.parse_args().output.resolve())
