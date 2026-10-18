"""Frozen six-month forward evaluation; no source access on import or freeze.

Run --freeze first, review protocol.json, then --run. The actual data loader is
called only after the immutable access marker exists. Every fit/calibration is
restricted to the past; source outcomes are revealed only after all six cases.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, platform, shutil, sys, time
import numpy as np
import pandas as pd
import joblib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for directory in ('gecco_v2', 'gecco_v5', 'gecco_v6'):
    sys.path.insert(0, str(ROOT / 'ml' / directory))
from alarm_policy import select as select_baseline, predict as baseline_predict
from partially_labeled_model import PartiallyLabeledRecoveryDetector
from local_change import LocalChangeScorer
from guarded_suppression import guarded_shape
from corroborated_rescue import fit_shape_reference, corroborated_scores
from source_suppression import calibrate as calibrate_guard, predict as predict_guard
from source_joint_calibration import calibrate as calibrate_joint
from runtime_v4 import predict_frame
from unknown_label_metrics import comparison

ARCHIVE = ROOT / 'data/external/new_holdout_candidate/eawag_adasen/ADASen_paper.zip'
ARCHIVE_SHA = 'f91e930d1e194f401f4570c8ddbfdd90606475233e2f6cd36114ff9da11fc8b0'
CHANNELS = ['p1', 'p2', 'p3', 'p4']
GAP = 120
MIN_TEST_NORMAL_MINUTES = 1440
START = pd.Timestamp('2018-06-01')
END = pd.Timestamp('2019-05-01')

def now(): return datetime.now(timezone.utc).isoformat()
def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()
def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')

def geometry():
    """Minute-start index boundaries; output rows are stamped at minute end."""
    cases = []
    for test_start in pd.date_range('2018-11-01', '2019-04-01', freq='MS'):
        cal_start = test_start - pd.DateOffset(months=2)
        test_end = test_start + pd.DateOffset(months=1)
        index = lambda t: int((t - START).total_seconds() // 60)
        a, b, c = index(cal_start), index(test_start), index(test_end)
        boundaries = np.linspace(a, b, 5, dtype=np.int64).tolist()
        cases.append({'name': test_start.strftime('%Y-%m'), 'train': [0, a],
                      'calibration_boundaries': boundaries, 'test': [b, c]})
    return cases

def code_paths():
    return sorted(list(HERE.glob('*.py')) +
        [ROOT / 'ml/gecco_v5' / n for n in ['recovery_candidate.py', 'calibration.py']] +
        [ROOT / 'ml/gecco_v2' / n for n in ['alarm_policy.py', 'candidates_supervised.py']] +
        [ROOT / 'ml/gecco_baseline/metrics.py'])

def freeze(out):
    out.mkdir(parents=True, exist_ok=False)
    assert sha(ARCHIVE) == ARCHIVE_SHA, 'Archive bytes changed'
    paths = code_paths()
    assert (HERE / 'waterhub_loader.py') in paths
    plan = {
        'frozen_at_utc': now(), 'version': 'v6_run04_waterhub_forward_6_v1',
        'measurement_values_and_row_labels_previously_opened': False,
        'prior_exposure': 'File inventory, headers, timestamp-only geometry, publisher source code only.',
        'development_selection': 'GECCO run04 selected after four disclosed development attempts; none is fresh validation.',
        'archive_sha256': ARCHIVE_SHA, 'archive_path': str(ARCHIVE.relative_to(ROOT)),
        'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in paths},
        'source_scope': 'Raw and annotation CSVs June2018-April2019 inclusive; May2019 is unlabelled and unused. August stays on calendar with unknown labels.',
        'adapter': 'Closed minute [M,M+60s), selected raw pressure at M+50s; require six unique aligned slots per process, four finite chosen readings. Score timestamp M+60s. No interpolation or label-derived features.',
        'ambiguity': 'Fixed raw-timestamp duplicate calendar computed before value adaptation. Conditional pipeline causality only; no proof of physical instrument clock chronology.',
        'annotations': 'Six streams x six slots: valid binary agreement among duplicates, then OR only when all36 are known. Otherwise -1, never normal. Complete immutable annotation exports are required; label prefix parity is not claimed for late duplicate annotations.',
        'cases': geometry(), 'cadence_seconds': 60, 'gap_samples_per_independent_block': GAP,
        'training': 'Expanding history from June1 to two months before each test. Unknown targets excluded from supervision, normal scale fitting and negative weighting; raw past observations may provide label-independent context. Fixed run04 model and hyperparameters.',
        'calibration': 'Previous two calendar months, four contiguous near-equal minute blocks, each reset with120 discarded observations before feature calculation. Fit no model here. Baseline grid selected on known labels only; inference remains available on unknown labels. Guard and rescue retain fixed run04 grids/gates; unknown-label onset accounting declared before exposure.',
        'forward_update': 'Previous test months become eligible historical training/calibration for later periods under a simulated available-manual-annotations assumption. No human method adjustment between periods.',
        'primary_events': 'Known-positive segment immediately preceded by known0; first row or preceding-unknown onset is left-censored and reported separately. Confirmed event requires actual adjacent sensor predictions0->1 inside original interval. Unknown labels do not alter predictions.',
        'aggregation': 'Report monthly comparisons and one pooled contiguous November-April timeline. Pooled primary event identities are calculated once; do not sum monthly event counts.',
        'false_runs': 'Runs of known-normal alarm minutes; unknown labels split observed fragments and are not proven distinct physical starts.',
        'failure_policy': 'No finite baseline calibration/normal exposure yields an explicitly failed case, preserved error, no invented zero-alarm success; incomplete evaluation cannot pass.',
        'acceptance': {'complete_periods': 6, 'every_period_and_pool': ['no lost baseline event IDs', 'identical sensor availability', 'no added paired detection delay', 'no increased false runs', 'no increased false alarm minutes'],
                       'pooled_more_events': True, 'pooled_fewer_false_runs': True,
                       'minimum_event_gain_periods': 2, 'minimum_false_run_reduction_periods': 2,
                       'minimum_primary_events': 5, 'minimum_eventful_periods': 2,
                       'minimum_observed_known_normal_minutes_each_test_period': MIN_TEST_NORMAL_MINUTES},
        'limits': ['One new hydraulic-pressure installation, not chemical-quality efficacy or sensor fault taxonomy.',
                   'Resampling differs intentionally from publisher processed benchmark; no benchmark reproduction claim.',
                   'Not Raspberry Pi speed validation, no3D or actuator integration.'],
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__},
    }
    for p in paths:
        dest = out / 'source' / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dest)
    write(out / 'protocol.json', plan)
    print(json.dumps({'protocol_frozen': str(out / 'protocol.json'), 'sha256': sha(out / 'protocol.json')}), flush=True)

def verify(plan):
    for path, digest in plan['code_sha256'].items():
        if sha(ROOT / path) != digest: raise RuntimeError('Frozen code changed: ' + path)

def gap_components(model, local, frame):
    tail = frame.iloc[GAP:].reset_index(drop=True)
    a = model.score_components(tail); b = local.score_components(tail)
    values = {'baseline_score': a['baseline'], 'shape_raw': a['shape'], **b}
    return {k: np.r_[np.full(min(GAP, len(frame)), np.nan), v] for k, v in values.items()}

def fit_case(frame, labels, case, folder):
    """Only past slices are passed to fitting or selection functions."""
    a = case['train'][1]; bounds = case['calibration_boundaries']
    print(json.dumps({'period': case['name'], 'phase': 'training_past_only'}), flush=True)
    model = PartiallyLabeledRecoveryDetector('shape_invariant', CHANNELS).fit(frame.iloc[:a], labels[:a])
    local = LocalChangeScorer(CHANNELS).fit(frame.iloc[:a], labels[:a] != 0)
    blocks = []
    for left, right in zip(bounds[:-1], bounds[1:]):
        scores = gap_components(model, local, frame.iloc[left:right])
        blocks.append({'labels': labels[left:right], 'scores': scores, 'source_start': left})
    cal_y = np.concatenate([b['labels'] for b in blocks])
    cal_s = np.concatenate([b['scores']['baseline_score'] for b in blocks])
    print(json.dumps({'period': case['name'], 'phase': 'baseline_calibration'}), flush=True)
    # Score masking is confined to baseline threshold selection, never inference.
    selected_base, trials = select_baseline(cal_y == 1, np.where(cal_y >= 0, cal_s, np.nan), baseline=True)
    pd.DataFrame(trials).to_csv(folder / 'baseline_calibration_trials.csv.gz', index=False)
    for b in blocks:
        b['baseline'] = baseline_predict(b['scores'].pop('baseline_score'), selected_base['threshold'], 'instant')
        b['guarded'] = b['baseline'].copy()
    guard_blocks = [{'labels': b['labels'], 'scores': guarded_shape(b['scores'], b['scores']['shape_raw']),
                     'baseline_predictions': b['baseline'], 'source_start': b['source_start']} for b in blocks]
    print(json.dumps({'period': case['name'], 'phase': 'suppression_calibration'}), flush=True)
    guard, trials = calibrate_guard(guard_blocks)
    pd.DataFrame(trials).to_csv(folder / 'suppression_calibration_trials.csv.gz', index=False)
    cal_rows = []
    for b, g in zip(blocks, guard_blocks):
        b['guarded'] = predict_guard(g['scores'], b['baseline'], guard)
        cal_rows.append(pd.DataFrame({'sample_index': np.arange(b['source_start'], b['source_start'] + len(b['labels'])),
                                     'label': b['labels'], 'baseline': b['baseline'], 'guarded': b['guarded'], **b['scores']}))
    shape_threshold = fit_shape_reference(blocks)
    for b, rows in zip(blocks, cal_rows):
        b['scores'] = corroborated_scores(b['scores'], shape_threshold)
        for key, value in b['scores'].items(): rows['rescue__' + key] = value
    print(json.dumps({'period': case['name'], 'phase': 'joint_calibration'}), flush=True)
    selected, trials = calibrate_joint(blocks)
    pd.DataFrame(trials).to_csv(folder / 'joint_calibration_trials.csv.gz', index=False)
    pd.concat(cal_rows, ignore_index=True).to_csv(folder / 'calibration_scores.csv.gz', index=False)
    return {'local_model': local, 'prior_bundle': {'model': model, 'baseline_threshold': selected_base['threshold'], 'baseline_policy': 'instant'},
            'guard_selected': guard, 'selected': selected, 'shape_support_threshold': shape_threshold,
            'sample_seconds': 60, 'max_fit_index': a - 1, 'max_calibration_index': bounds[-1] - 1,
            'training_status': {'shape': model.fit_status_, 'local': local.fit_status_}}

def noninferior(result):
    b, c = result['baseline'], result['candidate']
    return bool(not result['lost_baseline_event_ids'] and result['sensor_availability_equal']
                and all(d['extra_delay_seconds'] <= 0 for d in result['paired_extra_delays'])
                and c['false_positive_runs'] <= b['false_positive_runs'] and c['fp'] <= b['fp'])

def acceptance(periods, pooled):
    b, c = pooled['baseline'], pooled['candidate']
    checks = {'six_complete_periods': len(periods) == 6,
              'each_period_has_one_day_observed_known_normal': all(
                  r[model]['normal_observed_seconds'] >= MIN_TEST_NORMAL_MINUTES * 60
                  for r in periods for model in ('baseline', 'candidate')),
              'all_periods_and_pool_noninferior': all(noninferior(r) for r in periods + [pooled]),
              'strictly_more_pooled_events': c['confirmed_events'] > b['confirmed_events'],
              'strictly_fewer_pooled_false_runs': c['false_positive_runs'] < b['false_positive_runs'],
              'event_gain_in_at_least_two_periods': sum(bool(r['new_candidate_event_ids']) for r in periods) >= 2,
              'false_run_reduction_in_at_least_two_periods': sum(r['candidate']['false_positive_runs'] < r['baseline']['false_positive_runs'] for r in periods) >= 2,
              'at_least_five_primary_events': b['true_events'] >= 5,
              'at_least_two_eventful_periods': sum(r['baseline']['true_events'] > 0 for r in periods) >= 2}
    return {'checks': checks, 'passes_fresh_validation_requirements': all(checks.values()),
            'deployment_approved': False}

def run(out):
    from waterhub_loader import load_waterhub_archive  # Actual I/O happens below, not on import.
    from waterhub_adapter import adapt_waterhub
    plan = json.loads((out / 'protocol.json').read_text()); verify(plan)
    assert sha(ARCHIVE) == plan['archive_sha256']
    with (out / 'source_access_started.json').open('x') as f:
        json.dump({'first_measurement_access_started_at_utc': now(), 'protocol_sha256': sha(out / 'protocol.json')}, f, indent=2)
    print('Frozen source access started; outer outcomes withheld until all periods complete.', flush=True)
    loaded = load_waterhub_archive(ARCHIVE)
    raw_t1_t2, raw_gak, annotations = loaded.combined()
    adapted = adapt_waterhub(raw_t1_t2, raw_gak, annotations,
                             timestamp_ambiguity_mask=loaded.timestamp_ambiguity_mask,
                             grid_start=START, grid_end=END - pd.Timedelta(minutes=1))
    loader_audit = {'metadata': loaded.metadata, 'members': loaded.member_manifest}
    del loaded, raw_t1_t2, raw_gak, annotations
    frame = adapted.features; labels = adapted.labels.to_numpy(np.int8)
    expected = pd.date_range(START + pd.Timedelta(minutes=1), END, freq='min')
    assert frame.index.equals(expected), 'Adapter calendar changed'
    write(out / 'source_adapter_audit.json', {'loader': loader_audit, 'adapter': adapted.metadata})
    adapted.audit.to_csv(out / 'availability_audit.csv.gz')
    frame.assign(label=labels).to_csv(out / 'adapted_source.csv.gz')
    predictions = []; periods = []
    for case in plan['cases']:
        verify(plan); folder = out / case['name']; folder.mkdir(); started = time.perf_counter()
        try:
            bundle = fit_case(frame, labels, case, folder)
        except ValueError as error:
            write(folder / 'failed_case.json', {'error': str(error), 'case': case, 'at_utc': now()})
            write(out / 'incomplete.json', {'case': case['name'], 'reason': str(error), 'passes_fresh_validation_requirements': False})
            raise
        joblib.dump(bundle, folder / 'bundle.joblib', compress=3)
        verify(plan)
        write(folder / 'freeze.json', {'frozen_at_utc': now(), 'case': case, 'bundle_sha256': sha(folder / 'bundle.joblib'),
                                     'protocol_sha256': sha(out / 'protocol.json'), 'selected': bundle['selected'],
                                     'guard_selected': bundle['guard_selected'], 'shape_support_threshold': bundle['shape_support_threshold']})
        left, right = case['test']
        scored = predict_frame(bundle, frame.iloc[left:right])
        scored.insert(0, 'sample_index', np.arange(left, right)); scored.insert(1, 'label', labels[left:right])
        scored.to_csv(folder / 'predictions.csv.gz')
        result = comparison(labels[left:right], scored.baseline_prediction.to_numpy(), scored.prediction.to_numpy())
        result['case'] = case['name']; result['noninferior'] = noninferior(result)
        write(folder / 'results.json', result); periods.append(result); predictions.append(scored)
        print(json.dumps({'period_completed': case['name'], 'seconds': round(time.perf_counter() - started, 1), 'outcomes': 'withheld'}), flush=True)
    verify(plan)
    whole = pd.concat(predictions)
    assert (np.diff(whole.sample_index) == 1).all()
    pooled = comparison(whole.label.to_numpy(), whole.baseline_prediction.to_numpy(), whole.prediction.to_numpy())
    result = {'completed_at_utc': now(), 'first_use_frozen_forward_evaluation': True, 'protocol_sha256': sha(out / 'protocol.json'),
              'periods': periods, 'pooled': pooled, 'acceptance': acceptance(periods, pooled)}
    write(out / 'results.json', result)
    print(json.dumps({'completed': True, 'acceptance': result['acceptance'],
                      'events': [pooled[n]['confirmed_events'] for n in ('baseline', 'candidate')],
                      'primary_events': pooled['baseline']['true_events'],
                      'false_runs': [pooled[n]['false_positive_runs'] for n in ('baseline', 'candidate')]}), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument('--freeze', action='store_true'); mode.add_argument('--run', action='store_true')
    args = parser.parse_args(); (freeze if args.freeze else run)(args.output.resolve())
