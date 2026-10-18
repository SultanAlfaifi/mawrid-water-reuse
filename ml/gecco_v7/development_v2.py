"""V7 second attempt: HGB and guarded zero-normal-addition calibration.

Disclosed data only. Prior ExtraTrees attempt rejected; snapshots retained.

V6 predictions are a fixed stronger reference. Compare both the original IF
and V6 with V7 on identical rows. Model/code/selection are saved before each
outer segment is loaded, but these are DEVELOPMENT tests, not fresh evidence:
all GECCO and WaterHub outcomes have already informed this project.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
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
for directory in (ROOT, ROOT / 'ml/gecco_v2', ROOT / 'ml/gecco_v5', ROOT / 'ml/gecco_v6'):
    sys.path.insert(0, str(directory))
# V7 imports are package-qualified: V5 also has a calibration.py module.
from ml.gecco_v7.long_context_hgb import LongContextHGBScorer as LongContextEventScorer
from ml.gecco_v7.calibration_v2 import calibrate, predict
from guarded_suppression import guarded_shape
from reproducible_explore import source_cases
from joint_calibration_v2 import predict as v6_predict
from unknown_label_metrics import comparison
from waterhub_evaluation import geometry as waterhub_geometry

GAP = 120
GECCO_PRIOR = ROOT / 'output/ml/gecco-v6-development/run_04'
WATERHUB_PRIOR = ROOT / 'output/ml/gecco-v6-waterhub-first-use'
WATERHUB_ADAPTED = WATERHUB_PRIOR / 'adapted_source.csv.gz'
WATERHUB_SHA = '2ebd0997afb7571390c7df6b5b64616dec81441b304f6a02ff323b6218984ff7'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def score_gap(model, frame):
    values = model.score_components(frame.iloc[GAP:].reset_index(drop=True))['long_context']
    return np.r_[np.full(min(GAP, len(frame)), np.nan), values]


def code_paths():
    paths = [ROOT / 'ml/gecco_v7' / name for name in ('development.py', 'development_v2.py', 'calibration.py', 'calibration_v2.py', 'long_context.py', 'long_context_hgb.py', 'runtime.py', 'runtime_v2.py')]
    paths += list((ROOT / 'ml/gecco_v6').glob('*.py'))
    paths += [ROOT / 'ml/gecco_v5' / name for name in
              ('reproducible_explore.py', 'calibration.py', 'evaluation.py', 'recovery_candidate.py',
               'supported_candidate.py', 'normal_support.py')]
    paths += [ROOT / 'ml/gecco_v2' / name for name in ('alarm_policy.py', 'candidates_supervised.py')]
    paths += [ROOT / 'ml/gecco_baseline/metrics.py']
    return sorted(set(paths))


def verify(plan):
    for key in ('code_sha256', 'input_sha256'):
        for path, digest in plan[key].items():
            if sha(ROOT / path) != digest:
                raise RuntimeError('Frozen input or code changed: ' + path)


def cases(scope):
    if scope in ('all', 'gecco'):
        for case in source_cases():
            yield {**case, 'target': 'EVENT', 'prior': GECCO_PRIOR / case['name']}
    if scope in ('all', 'waterhub'):
        if sha(WATERHUB_ADAPTED) != WATERHUB_SHA:
            raise RuntimeError('Previously verified WaterHub adaptation changed')
        for item in waterhub_geometry():
            a, b, c = item['train'][1], *item['test']
            bounds = item['calibration_boundaries']
            frame = pd.read_csv(WATERHUB_ADAPTED, nrows=b, index_col=0, parse_dates=True, float_precision='round_trip')
            yield {'name': item['name'], 'source': 'WaterHub', 'train': frame.iloc[:a],
                   'cal': [frame.iloc[left:right] for left, right in zip(bounds[:-1], bounds[1:])],
                   'cal_starts': bounds[:-1], 'test_start': b, 'test_end': c,
                   'load_test': lambda left=b, right=c: pd.read_csv(
                       WATERHUB_ADAPTED, nrows=right, index_col=0, parse_dates=True,
                       float_precision='round_trip').iloc[left:right],
                   'channels': ['p1', 'p2', 'p3', 'p4'], 'continuous_cal': False,
                   'target': 'label', 'prior': WATERHUB_PRIOR / item['name']}


def noninferior(result):
    b, c = result['baseline'], result['candidate']
    return bool(not result['lost_baseline_event_ids'] and result['sensor_availability_equal']
                and all(d['extra_delay_seconds'] <= 0 for d in result['paired_extra_delays'])
                and c['false_positive_runs'] <= b['false_positive_runs'] and c['fp'] <= b['fp'])


def comparisons(labels, baseline, reference, candidate):
    results = {}
    for key, left, right in [('if_vs_v6', baseline, reference), ('if_vs_v7', baseline, candidate),
                             ('v6_vs_v7', reference, candidate)]:
        result = comparison(labels, left, right, 60)
        result['noninferior'] = noninferior(result)
        result['lost_positive_alarm_rows'] = int(((labels == 1) & (left == 1) & (right != 1)).sum())
        results[key] = result
    return results


def totals(stats):
    keys = ('true_events', 'confirmed_events', 'tp', 'fp', 'fn', 'tn', 'false_positive_runs',
            'normal_observed_seconds', 'fp_duration_seconds', 'known_positive_rows',
            'positive_unavailable_rows', 'rows', 'available_rows')
    out = {key: sum(item[key] for item in stats) for key in keys}
    ratio = lambda a, b: a / b if b else None
    out.update(confirmed_event_recall=ratio(out['confirmed_events'], out['true_events']),
               precision=ratio(out['tp'], out['tp'] + out['fp']),
               recall_observed_positive=ratio(out['tp'], out['tp'] + out['fn']),
               f1_observed_points=ratio(2 * out['tp'], 2 * out['tp'] + out['fp'] + out['fn']),
               false_runs_per_day=ratio(out['false_positive_runs'] * 86400, out['normal_observed_seconds']))
    return out


def summarize(periods, sources, expected_cases=19):
    result = {}
    for comparison_key in ('if_vs_v6', 'if_vs_v7', 'v6_vs_v7'):
        pool = [source[comparison_key] for source in sources.values()]
        parts = [period['comparisons'][comparison_key] for period in periods]
        b, c = [totals([p[model] for p in pool]) for model in ('baseline', 'candidate')]
        checks = {
            'all_prespecified_cases_complete': len(periods) == expected_cases,
            'all_periods_and_source_pools_noninferior': all(p['noninferior'] for p in pool + parts),
            'strictly_more_pooled_events': c['confirmed_events'] > b['confirmed_events'],
            'strictly_fewer_pooled_false_runs': c['false_positive_runs'] < b['false_positive_runs'],
            'event_gain_in_at_least_two_periods': sum(bool(p['new_candidate_event_ids']) for p in parts) >= 2,
            'false_run_reduction_in_at_least_two_periods': sum(p['candidate']['false_positive_runs'] < p['baseline']['false_positive_runs'] for p in parts) >= 2,
        }
        if comparison_key == 'v6_vs_v7':
            checks['no_additional_positive_alarm_row_loss_relative_v6'] = all(
                p['lost_positive_alarm_rows'] == 0 for p in pool + parts)
        result[comparison_key] = {'baseline': b, 'candidate': c, 'checks': checks,
                                 'noninferior_periods': sum(p['noninferior'] for p in parts),
                                 'periods': len(parts), 'event_gain_periods': sum(bool(p['new_candidate_event_ids']) for p in parts),
                                 'false_run_reduction_periods': sum(p['candidate']['false_positive_runs'] < p['baseline']['false_positive_runs'] for p in parts),
                                 'passes_declared_development_gate': all(checks.values())}
    return result


def run_case(case, out, plan):
    verify(plan)
    folder = out / case['name']; folder.mkdir()
    start = time.perf_counter()
    old = case['prior']; old_freeze = json.loads((old / 'freeze.json').read_text())
    if case['source'] == 'WaterHub':
        geom = old_freeze['case']
        assert geom['train'] == [0, len(case['train'])]
        assert geom['calibration_boundaries'][:-1] == case['cal_starts']
        assert geom['test'] == [case['test_start'], case['test_end']]
    else:
        assert old_freeze['train'] == [0, len(case['train'])]
        assert old_freeze['calibration_starts'] == case['cal_starts']
        assert old_freeze['test'] == [case['test_start'], case['test_end']]
    prior_hashes = {name: sha(old / name) for name in ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz', 'predictions.csv.gz')}
    assert prior_hashes['bundle.joblib'] == old_freeze['bundle_sha256']
    prior = joblib.load(old / 'bundle.joblib')
    assert prior['max_fit_index'] == len(case['train']) - 1
    assert prior['max_calibration_index'] == case['test_start'] - 1
    print(json.dumps({'case': case['name'], 'phase': 'fit_long_context', 'train_rows': len(case['train'])}), flush=True)
    model = LongContextEventScorer(case['channels']).fit(
        case['train'], case['train'][case['target']].to_numpy(np.int8))
    write(folder / 'model_inspection.json', model.inspection())
    saved = pd.read_csv(old / 'calibration_scores.csv.gz', float_precision='round_trip')
    np.testing.assert_array_equal(saved.sample_index, np.arange(case['cal_starts'][0], case['test_start']))
    labels = np.concatenate([part[case['target']].to_numpy(np.int8) for part in case['cal']])
    np.testing.assert_array_equal(labels, saved[case['target']].to_numpy(np.int8))
    bounds = np.r_[0, np.cumsum([len(part) for part in case['cal']])]
    if case['continuous_cal']:
        whole = score_gap(model, pd.concat(case['cal'], ignore_index=True))
        long_parts = [whole[a:b] for a, b in zip(bounds[:-1], bounds[1:])]
    else:
        long_parts = [score_gap(model, part) for part in case['cal']]
    blocks = []; cal_rows = []
    for j, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        part = saved.iloc[a:b]
        components = {key.removeprefix('rescue__'): part[key].to_numpy() for key in part.columns if key.startswith('rescue__')}
        ref = v6_predict(part.baseline.to_numpy(np.int8), part.guarded.to_numpy(np.int8), components, prior['selected'])
        gate = guarded_shape({key: part[key].to_numpy() for key in ('level', 'jump', 'sustained')}, long_parts[j])
        blocks.append({'labels': labels[a:b], 'reference': ref, 'long_scores': long_parts[j], 'gate_scores': gate, 'source_start': int(case['cal_starts'][j])})
        cal_rows.append(pd.DataFrame({'sample_index': part.sample_index.to_numpy(), 'label': labels[a:b],
                                     'baseline': part.baseline.to_numpy(np.int8), 'reference': ref, 'long_context': long_parts[j], 'guarded_long_context': gate}))
    print(json.dumps({'case': case['name'], 'phase': 'joint_calibration', 'fit_status': model.fit_status_}), flush=True)
    selected, trials = calibrate(blocks, cadence_seconds=60)
    for rows, block in zip(cal_rows, blocks):
        rows['candidate'] = predict(block['reference'], block['long_scores'], selected, gate_scores=block['gate_scores'])
    pd.concat(cal_rows, ignore_index=True).to_csv(folder / 'calibration_scores.csv.gz', index=False)
    pd.DataFrame(trials).to_csv(folder / 'calibration_trials.csv.gz', index=False)
    bundle = {'version': 'v7_hgb_guarded_v2', 'long_model': model, 'reference_bundle': prior, 'selected': selected,
              'sample_seconds': 60, 'max_fit_index': len(case['train']) - 1,
              'max_calibration_index': case['test_start'] - 1, 'gap_samples': GAP}
    joblib.dump(bundle, folder / 'bundle.joblib', compress=3)
    verify(plan)
    write(folder / 'freeze.json', {'frozen_at_utc': now(), 'development_only': True,
          'plan_sha256': sha(out / 'plan.json'), 'prior_folder': str(old.relative_to(ROOT)),
          'prior_sha256': prior_hashes, 'train': [0, len(case['train'])],
          'calibration_starts': case['cal_starts'], 'continuous_cal': case['continuous_cal'],
          'test': [case['test_start'], case['test_end']], 'bundle_sha256': sha(folder / 'bundle.joblib'),
          'selected': selected})
    # All fitting/calibration above precede access to this case's disclosed outer rows.
    test = case['load_test'](); target = test[case['target']].to_numpy(np.int8)
    long_scores = score_gap(model, test)
    cached = pd.read_csv(old / 'predictions.csv.gz', float_precision='round_trip')
    for name, digest in prior_hashes.items():
        assert sha(old / name) == digest, 'V6 artifact changed'
    np.testing.assert_array_equal(cached.sample_index, np.arange(case['test_start'], case['test_end']))
    np.testing.assert_array_equal(target, cached[case['target']].to_numpy(np.int8))
    bcol, rcol = ('baseline_prediction', 'prediction') if case['source'] == 'WaterHub' else ('baseline', 'candidate')
    base, ref = cached[bcol].to_numpy(np.int8), cached[rcol].to_numpy(np.int8)
    gate_scores = guarded_shape({key: cached[key].to_numpy() for key in ('level', 'jump', 'sustained')}, long_scores)
    pred = predict(ref, long_scores, selected, gate_scores=gate_scores)
    rows = pd.DataFrame({'sample_index': cached.sample_index, 'label': target,
                         'baseline': base, 'reference': ref, 'candidate': pred, 'long_context': long_scores, 'guarded_long_context': gate_scores})
    rows.to_csv(folder / 'predictions.csv.gz', index=False)
    result = {'case': case['name'], 'source': case['source'], 'development_only': True,
              'comparisons': comparisons(target, base, ref, pred), 'selected': selected,
              'fit_status': model.fit_status_, 'seconds': time.perf_counter() - start}
    write(folder / 'results.json', result)
    brief = result['comparisons']['v6_vs_v7']
    print(json.dumps({'case': case['name'], 'completed': True, 'events': [brief[m]['confirmed_events'] for m in ('baseline', 'candidate')],
                      'false_runs': [brief[m]['false_positive_runs'] for m in ('baseline', 'candidate')],
                      'positive_alarm_rows': [brief[m]['tp'] for m in ('baseline', 'candidate')],
                      'lost_events': len(brief['lost_baseline_event_ids']), 'noninferior': brief['noninferior'],
                      'seconds': round(result['seconds'], 2)}), flush=True)
    return result, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--scope', choices=['all', 'gecco', 'waterhub'], default='all')
    ap.add_argument('--limit-cases', type=int, default=19)
    args = ap.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    paths = code_paths()
    inputs = [WATERHUB_ADAPTED] if args.scope in ('all', 'waterhub') else []
    if args.scope in ('all', 'gecco'):
        for year in ('2017', '2018', '2019'):
            inputs += list((ROOT / f'data/external/gecco{year}').glob('*.csv'))
    plan = {'created_at_utc': now(), 'scope': args.scope, 'limit_cases': args.limit_cases,
            'development_only': True, 'all_sources_previously_disclosed': True, 'attempt': 'run02_hgb_guarded', 'previous_attempt': 'run01 rejected/incomplete after9cases; results preserved separately',
            'fresh_validation': False, 'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in paths},
            'input_sha256': {str(p.relative_to(ROOT)): sha(p) for p in inputs},
            'reference': 'Immutable V6 run04 GECCO and frozen six-month WaterHub predictions; original IF retained as separate comparison.',
            'method': 'Fixed long-context HistGradientBoosting100trees/15leaves/.08learning/1L2/63bins/noearlystop, identical causal features and mixed event/point weights. Suppression only if allV6localcomponents finite<=1; otherwise preserve reference. Rescue cannot add any known-normal alarm row over its pure gated seed in any calibration block. Final joint constraints retain reference events/points/latency/availability/FP.',
            'split': 'Exact prior13GECCO+6WaterHub geometry. Expanding historical training; four adjacent past calibration blocks; no model fit on calibration or test.',
            'reset': 'Independent cal/test blocks discard first120sensor rows before feature calculation. Long lookback1440cannot cross reset; partial long windows carry observed fractions. GECCO2019cal features have original continuous context, alarm policies reset each block.',
            'selection': 'Only calibration targets select thresholds; code is frozen for this development attempt. Test outcomes cannot change an in-progress case or later selection algorithm.',
            'metrics': 'V6 unknown-label original-axis confirmed0->1onsets; unknown labels never imply normal. Per-period metrics and contiguous source pools. Independent sources summed only after own event accounting.',
            'acceptance': 'All periods and source pools preserve events/availability/paired latency and FPcount/time against IF and V6; positive alarm rows are additionally preserved relativeV6 (not retroactively required ofV6vsIF). Pooled strictly more events/fewerFPruns; each improvement in>=2periods. Report independently against IF and V6.',
            'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__, 'sklearn': sklearn.__version__},
            'no_3d_or_actuator_integration': True}
    for path in paths:
        target = out / 'source' / path.relative_to(ROOT); target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)
    write(out / 'plan.json', plan)
    periods = []; source_rows = {}
    for index, case in enumerate(cases(args.scope)):
        if index >= args.limit_cases:
            break
        try:
            result, rows = run_case(case, out, plan)
        except Exception as error:
            write(out / 'failed_case.json', {'case': case['name'], 'error': repr(error), 'at_utc': now()})
            raise
        periods.append(result); source_rows.setdefault(case['source'], []).append(rows)
    sources = {}
    for source, rows in source_rows.items():
        whole = pd.concat(rows, ignore_index=True)
        assert np.all(np.diff(whole.sample_index) == 1), 'Source pool must retain contiguous original rows'
        sources[source] = comparisons(*(whole[c].to_numpy(np.int8) for c in ('label', 'baseline', 'reference', 'candidate')))
    verify(plan)
    expected_cases = {'all': 19, 'gecco': 13, 'waterhub': 6}[args.scope]
    result = {'completed_at_utc': now(), 'development_only': True, 'fresh_validation': False,
              'complete_cases': len(periods), 'expected_cases': expected_cases,
              'all_prespecified_cases_complete': len(periods) == expected_cases,
              'periods': periods, 'sources': sources,
              'summary': summarize(periods, sources, expected_cases=expected_cases)}
    write(out / 'results.json', result)
    print(json.dumps({'completed': True, 'cases': len(periods), 'summary': result['summary']}), flush=True)


if __name__ == '__main__':
    main()
