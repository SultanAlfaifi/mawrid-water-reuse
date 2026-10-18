"""One prespecified sensor-tail positive pulse-weighting experiment under V10 policy.

Original V12 features, references, uniform-normal/point/event weights and HGB parameters remain
fixed. Only HGB is refitted; the original IF estimator is reused unchanged.
All sources are previously disclosed development data. No 3D or actuation.
Legacy comparison keys ending in v7 mean candidate V14.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess
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
from ml.gecco_v14.pulse_weighting import SensorTailPulseHGBScorer

GAP = prior.GAP
now, sha, write, verify = prior.now, prior.sha, prior.write, prior.verify
cases = prior.cases
EXPECTED_NAMES = ([f'{year}_fold_{k}' for year in ('2017', '2018') for k in range(1, 7)]
    + ['2019_disclosed_test', '2018-11', '2018-12', '2019-01', '2019-02', '2019-03', '2019-04'])
REFERENCE_FILES = ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz', 'predictions.csv.gz')
HISTORICAL = ('v8', 'v9', 'v10', 'v11', 'v12', 'v13')
MIN_FREE_BYTES = 1024 ** 3
DESIGN_PROTOCOL = ROOT / 'output/ml/gecco-v14-design/protocol.json'


def resource_guard(out):
    """Reserve disk without deleting evidence or changing statistical scope."""
    free = shutil.disk_usage(out).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(f'Insufficient free disk: {free} bytes; reserve1GiB. Run remains incomplete.')


def historical_inventory():
    """Hash bytes only; historical test values never enter fitting/selection."""
    return {str(path.relative_to(ROOT)): sha(path) for version in HISTORICAL
            for path in [ROOT / f'output/ml/gecco-{version}-development/run_01' / name
                         for name in ('plan.json', 'results.json', 'audit.json')]}


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
    return sorted(set(prior_code_paths() + [ROOT / 'ml/gecco_v10/calibration.py', ROOT / 'ml/gecco_v12/baseline_evidence.py'] + [ROOT / 'ml/gecco_v14' / filename
                       for filename in ('development.py', 'pulse_weighting.py', 'runtime.py')]))


def run_case(case, out, plan):
    resource_guard(out)
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
    print(json.dumps({'case': case['name'], 'phase': 'fit_training_sensor_tail_pulse_hgb', 'train_rows': len(case['train'])}), flush=True)
    baseline_estimator = reference_bundle['prior_bundle']['model'].baseline_
    baseline_digest_before = joblib.hash(baseline_estimator, hash_name='sha1')
    model = SensorTailPulseHGBScorer(case['channels'], baseline_estimator).fit(
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
    bundle = {'version': 'v14_sensor_tail_pulse_weighted_hgb_120s', 'long_model': model,
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
    resource_guard(out)
    paths = code_paths()
    inputs = [prior.WATERHUB_ADAPTED, DESIGN_PROTOCOL]
    for year in ('2017', '2018', '2019'):
        inputs.extend((ROOT / f'data/external/gecco{year}').glob('*.csv'))
    references = reference_inventory()
    historical = historical_inventory()
    for record in references.values():
        inputs.extend(ROOT / record['folder'] / filename for filename in REFERENCE_FILES)
    plan = {'created_at_utc': now(), 'scope': 'all', 'limit_cases': 19, 'expected_cases': 19,
        'attempt': 'v14_run01_sensor_tail_pulse_weights', 'development_only': True,
        'all_sources_previously_disclosed': True, 'fresh_validation': False,
        'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in paths},
        'input_sha256': {**{str(p.relative_to(ROOT)): sha(p) for p in inputs}, **historical},
        'reference_sha256': references,
        'historical_comparison_sha256': historical,
        'case_order': EXPECTED_NAMES,
        'design_protocol_sha256': sha(DESIGN_PROTOCOL),
        'single_statistical_change': 'Relative to V12, replace only positive label-onset mass0.25 with sensor-tail-pulse-aligned mass0.25. Normalmass0.5uniform, positivepoint0.125/event0.125 unchanged. q95linear of ALL finite known-normal original IF raw training scores. Full-axis finite>=q95 tail episodes, only knownstarts preceded by finitebelowq95. All confirmedpulse windows offsets0,1,2 truncated atpulseend. Eligiblepositive intersections balanced bysegment, thenpulse, thenrow. No labelboundary reset, no axiscompression or windowshift. If no eligiblebonus globally redistribute0.25 toeventuniform. OriginalIF/V12features/HGBparams/availability/V10policy fixed. One candidate, no family/coefficient search.',
        'calibration_contract': 'Exact frozen V10 positive-pulse/pending certification. First2blocksselect, later2certify, all4veto. No new grid. OriginalIF/V6gates unchanged; historicalretention and separateV8goal evaluationonly. This conditionalV6fallback does not guarantee V8retention.',
        'fitting_disclosure': 'Original IF reused without refit. Its full-training scores are in-sample representation, not prequential/cross-fitted. HGB fits only original train. Reused disclosed development periods; temporal correctness is not fresh independent validation.',
        'streaming_limitation': 'Raw baseline15 rolling statistics depend on finite-precision history. Mathematical lookback does not qualify cropped or persistent streaming parity.',
        'weights': 'Normal0.5uniform; point0.125uniform; event0.125uniform across eligible original positive segments. Sensor-tail-pulse0.25uniform across segments with eligible bonus, then eligible pulses persegment, then intersecting eligible positive rows. Unknown0. No labelonsetbonus. Globalnobonus: eventmass0.375.',
        'pulse_weight_recipe': {'quantile':0.95,'quantile_method':'linear','quantile_scope':'ALL original trainlabel0finitefloat64IF inclHGB-ineligible','tail_comparison':'>=','pulse_start':'previousrawfinitebelowq95 thenfinite>=q95 onfullaxis','censored_starts_excluded':True,'all_confirmed_pulses':True,'offset_samples':[0,1,2],'truncate_at_tail_end':True,'no_label_boundary_reset':True,'positive_pulse_mass':0.25,'normal_mass':0.5,'normal_uniform':True,'global_no_eligible_bonus_event_mass':0.375},
        'onset_window': 'No label-onset bonus. Sensor-tailpulse first3originalsamples at current60s cadence correspond to offsets0,60,120s; trainingemphasis is not inference latency guarantee.',
        'reference': 'Immutable V6run04 GECCO and frozen six-month WaterHub; original IF also compared.',
        'split': 'Exact13GECCO+6WaterHub expanding historical training geometry. Four contiguous past calibration blocks. No model fitting on calibration/test.',
        'selection': 'First2 past blocks choose one fixed V10 pulse-retaining pending policy; last2 certify without retuning and all4 veto. Identical low/high grids, normal/event evidence, zero-added-normal pending/rescue checks, positive-pulse ownership and 120s cap. Unsupported or failed certificate returns V6. Fixed V6 itself previously used all4 calibration blocks.',
        'reset': 'Discard first120rows before feature generation perindependentcal/test segment. Partial causal longcontext1440; first60remainingrows unavailable. GECCO2019calfeaturescontinuousafteronegap, policiesreset4blocks.',
        'acceptance': 'All19periods and eachsourcepool preserve confirmed reference eventIDs, availability, paired extraeventdelay<=120s, noFPcount/duration increase vsbothIFandV6. Pooledmoreevents/fewerFPfragments; eachgainin>=2periods. TProwlossdescriptive underuserauthorized<=120s experiment.',
        'historical_retention_requirement': 'Zero lost exact confirmed event IDs vs V8,V9,V10,V11,V12,V13 in every original period and each contiguous source pool. V6 and V8 event-union must be retained; counts alone do not satisfy this. Historical test artifacts are evaluation comparators only, never fit/calibration inputs.',
        'v8_user_objective': 'Separate predeclared stricter comparison: preserve exact V8 event IDs, identical per-row availability, paired extraeventdelay<=120s and no false-fragment count or false-duration increase in any period or contiguous source pool; strictly fewer pooled false fragments and reduction in at least two periods. This gate is reported separately from unchanged original IF/V6 strong gates and does not alter model selection.',
        'resource_execution': {'training_parallelism': 1, 'case_isolation': 'fresh subprocess per case; no concurrent training', 'minimum_free_disk_bytes': MIN_FREE_BYTES, 'raw_or_feature_caches_copied': False, 'incomplete_run_cannot_pass': True},
        'comparison_schema': 'Legacy keys if_vs_v7 and v6_vs_v7 denote currentcandidate V14; all metrics and output columns retain the independently audited schema.',
        'cadence_seconds': 60, 'maximum_confirmation_seconds': 120,
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__, 'sklearn': sklearn.__version__},
        'no_3d_or_actuator_integration': True}
    for path in paths:
        dest = out / 'source' / path.relative_to(ROOT); dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, dest)
    write(out / 'plan.json', plan)
    periods, source_rows = [], {}
    for name in EXPECTED_NAMES:
        resource_guard(out)
        try:
            subprocess.run([sys.executable, '-B', '-m', 'ml.gecco_v14.development',
                            '--output', str(out), '--case', name], cwd=ROOT, check=True)
            result = json.loads((out / name / 'results.json').read_text())
            rows = pd.read_csv(out / name / 'predictions.csv.gz', float_precision='round_trip')
        except Exception as error:
            write(out / 'failed_case.json', {'case': name, 'error': repr(error), 'at_utc': now()})
            raise
        if result['case'] != name:
            raise RuntimeError('Subprocess returned a different original case axis')
        periods.append(result); source_rows.setdefault(result['source'], []).append(rows)
    sources = {}
    for name, parts in source_rows.items():
        whole = pd.concat(parts, ignore_index=True)
        assert np.all(np.diff(whole.sample_index) == 1)
        sources[name] = assess(*(whole[c].to_numpy(np.int8) for c in ('label', 'baseline', 'reference', 'candidate')))
    verify(plan)
    result = {'completed_at_utc': now(), 'development_only': True, 'fresh_validation': False,
              'candidate_version': 'V14', 'complete_cases': len(periods), 'expected_cases': 19,
              'all_prespecified_cases_complete': len(periods) == 19, 'maximum_allowed_extra_delay_seconds': 120,
              'historical_retention_required': True, 'v8_user_objective_required': True,
              'acceptance_evaluation_pending_independent_audit_and_historical_comparison': True,
              'periods': periods, 'sources': sources, 'summary': summarize(periods, sources)}
    write(out / 'results.json', result)
    print(json.dumps({'completed': True, 'cases': len(periods), 'summary': result['summary']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=EXPECTED_NAMES)
    args = parser.parse_args(); out = args.output.resolve()
    if args.case:
        plan = json.loads((out / 'plan.json').read_text()); verify(plan)
        if args.case not in plan['case_order']:
            raise ValueError('Unplanned case')
        for case in cases('all'):
            if case['name'] == args.case:
                run_case(case, out, plan)
                break
        else:
            raise ValueError('Prespecified case missing')
    else:
        execute(out)
