"""Explicit, prefix-only engineering verification of trusted completed V9 runs.

Import performs no IO. The CLI is intended only after the operator authorizes
the named, already disclosed test prefixes. It does not fit or select policies.
All19-case metadata/hash/audit gates precede bundle or sensor-row loading.
Only timestamp and fitted sensor columns are parsed; labels are never loaded.
This verifier cannot certify model acceptance, field safety or Pi performance.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.gecco_v9 import prototype
from ml.gecco_v9.runtime import predict_frame
from ml.gecco_v9.streaming import (StreamingPredictor, OUTPUT_COLUMNS,
                                  INTEGER_COLUMNS, BOOLEAN_COLUMNS)

ALLOWED_CASES = ('2019_disclosed_test', '2019-04')
ABSOLUTE_SCORE_TOLERANCE = 1e-12
PREFIX_ROWS = 1600
GECCO_SOURCE = 'data/external/gecco2019/6_gecco2019_test_water_quality.csv'
WATERHUB_SOURCE = 'output/ml/gecco-v6-waterhub-first-use/adapted_source.csv.gz'


def compare_outputs(expected, actual):
    """Exact axes/dtypes/ternary masks; finite scores use absolute1e-12 only."""
    if not actual.index.equals(expected.index) or list(actual.columns) != list(expected.columns):
        raise AssertionError('Streaming changed the original axis or output columns')
    differences = {}
    for column in expected:
        a, b = expected[column].to_numpy(), actual[column].to_numpy()
        if a.dtype != b.dtype:
            raise AssertionError('Streaming changed output dtype: ' + column)
        if column in INTEGER_COLUMNS + BOOLEAN_COLUMNS:
            if not np.array_equal(a, b):
                raise AssertionError('Exact prediction/mask mismatch: ' + column)
            continue
        if (not np.array_equal(np.isnan(a), np.isnan(b))
                or not np.array_equal(np.isposinf(a), np.isposinf(b))
                or not np.array_equal(np.isneginf(a), np.isneginf(b))):
            raise AssertionError('Nonfinite score mask mismatch: ' + column)
        finite = np.isfinite(a)
        difference = np.abs(a[finite] - b[finite])
        maximum = float(difference.max()) if len(difference) else 0.0
        differences[column] = maximum
        if maximum > ABSOLUTE_SCORE_TOLERANCE:
            raise AssertionError('Absolute score tolerance exceeded: ' + column)
    return differences


def _state_bytes(engine):
    """Approximate retained mutable Python state, excluding fitted estimators."""
    seen = set()
    def size(value):
        identity = id(value)
        if identity in seen: return 0
        seen.add(identity)
        result = sys.getsizeof(value)
        if isinstance(value, dict): return result + sum(size(k) + size(v) for k, v in value.items())
        if isinstance(value, (tuple, list, deque)): return result + sum(map(size, value))
        return result
    return size((engine.sensor_rows, engine.rescue_scores, engine.samples_seen,
                 engine.last_timestamp, engine.previous_reference, engine.episode_age,
                 engine.released, engine.reference.sensor_rows, engine.reference.score_history,
                 engine.reference.samples_seen, engine.reference.baseline_alarm_latched))


def _peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


def _typed_output(records, index):
    frame = pd.DataFrame(records, index=index, columns=OUTPUT_COLUMNS)
    for column in frame:
        frame[column] = frame[column].astype(np.int8 if column in INTEGER_COLUMNS
                      else bool if column in BOOLEAN_COLUMNS else float)
    return frame


def verify_prefix(bundle, frame):
    """Compare batch, per-row updates and varied continuous chunks in memory.

    This utility does not issue artifact authorization; verify_run_prefixes
    independently checks real bundle/source/audit provenance and minimum size.
    """
    channels = list(bundle['long_model'].channels)
    sensors = frame.loc[:, channels]
    # The stream constructor enforces actual timestamp cadence before inference.
    engine = StreamingPredictor(bundle)
    if not isinstance(sensors.index, pd.DatetimeIndex) or sensors.index.hasnans:
        raise ValueError('An actual, complete DatetimeIndex is required')
    if len(sensors) > 1 and not np.all(sensors.index[1:] - sensors.index[:-1] == engine.interval):
        raise ValueError('Actual source clock is not regular at the saved cadence')
    rss_start = _peak_rss_bytes()
    before = time.perf_counter(); batch = predict_frame(bundle, sensors)
    batch_seconds = time.perf_counter() - before
    rows, latency = [], []
    maxima = {'sensor_rows': 0, 'reference_sensor_rows': 0,
              'reference_score_rows': 0, 'rescue_score_rows': 0, 'mutable_state_bytes': 0}
    for timestamp, sensor in sensors.iterrows():
        before = time.perf_counter(); rows.append(engine.update(timestamp, sensor))
        latency.append(time.perf_counter() - before)
        maxima['sensor_rows'] = max(maxima['sensor_rows'], len(engine.sensor_rows))
        maxima['reference_sensor_rows'] = max(maxima['reference_sensor_rows'], len(engine.reference.sensor_rows))
        maxima['reference_score_rows'] = max(maxima['reference_score_rows'], len(engine.reference.score_history))
        maxima['rescue_score_rows'] = max(maxima['rescue_score_rows'], len(engine.rescue_scores))
        maxima['mutable_state_bytes'] = max(maxima['mutable_state_bytes'], _state_bytes(engine))
    individual = _typed_output(rows, sensors.index)
    row_errors = compare_outputs(batch, individual)
    # Boundaries include initial gap, partial warmup and first history rollover.
    gap = int(bundle.get('gap_samples', 120))
    edges = sorted({0, len(sensors), *[min(len(sensors), x) for x in
                   (1, 17, gap - 1, gap, gap + 1, gap + 60, 801,
                    gap + 1440, gap + 1441)]})
    edges = [x for x in edges if 0 <= x <= len(sensors)]
    chunked_engine = StreamingPredictor(bundle)
    before = time.perf_counter()
    parts = [chunked_engine.update_frame(sensors.iloc[a:b]) for a, b in zip(edges[:-1], edges[1:])]
    chunked_seconds = time.perf_counter() - before
    chunked = pd.concat(parts) if parts else chunked_engine.update_frame(sensors)
    chunk_errors = compare_outputs(batch, chunked)
    latency = np.asarray(latency)
    active = latency[gap:] if len(latency) > gap else np.array([])
    def timing(values):
        return {'rows': len(values), 'total_seconds': float(values.sum()),
                'mean_seconds': float(values.mean()) if len(values) else None,
                'p50_seconds': float(np.quantile(values, .5)) if len(values) else None,
                'p95_seconds': float(np.quantile(values, .95)) if len(values) else None,
                'maximum_seconds': float(values.max()) if len(values) else None}
    record = {'tested_sample_bounds': [0, len(sensors)], 'full_period_tested': False,
              'exact_prediction_masks': True, 'score_tolerance': ABSOLUTE_SCORE_TOLERANCE,
              'score_relative_tolerance': 0.0,
              'maximum_absolute_score_error': {'individual': row_errors, 'chunked': chunk_errors},
              'chunk_boundaries': edges, 'batch_seconds': batch_seconds,
              'latency_seconds': {'individual_all_rows': timing(latency), 'individual_after_gap': timing(active),
                                  'chunked_total': chunked_seconds},
              'memory_metrics': {'maximum_runtime_history': maxima,
                                'process_peak_rss_before_bytes': rss_start,
                                'process_peak_rss_after_bytes': _peak_rss_bytes(),
                                'rss_scope': 'Process lifetime peak includes imported libraries, fitted models, batch/scratch/output; not incremental stream memory.',
                                'mutable_state_scope': 'Approximate recursive Python object sizes; excludes fitted models, scratch features and caller-owned input/output.'},
              'clock': {'first': sensors.index[0].isoformat() if len(sensors) else None,
                        'last': sensors.index[-1].isoformat() if len(sensors) else None,
                        'actual_timestamps_validated': True, 'sample_seconds': float(bundle['sample_seconds'])},
              'prefix_prediction_counts': {key: {str(value): int((batch[key] == value).sum()) for value in (-1, 0, 1)}
                                           for key in ('reference_prediction', 'prediction')}}
    return record, batch


def _source_prefix(gate, case, channels, samples):
    plan = prototype.read_json(gate['run'] / 'plan.json')
    relative = GECCO_SOURCE if case == '2019_disclosed_test' else WATERHUB_SOURCE
    path = prototype.inside(gate['root'], relative)
    expected_sha = plan.get('input_sha256', {}).get(relative)
    source_sha = prototype._equal_hash(path, expected_sha, 'Original test source')
    start, end = gate['freeze']['test']
    if samples > end - start: raise ValueError('Requested prefix exceeds the original test period')
    if case == '2019_disclosed_test':
        raw = pd.read_csv(path, usecols=['Time'] + channels, nrows=samples)
        index = pd.DatetimeIndex(pd.to_datetime(raw.pop('Time'), errors='raise'))
        source_slice = [0, samples]
        clock_origin = 'Published GECCO2019 test Time field; actual serialized year is retained, not rewritten to the dataset title year.'
    else:
        # The adapted source retains its original complete minute calendar.
        # Read header only first; then skip prior rows without parsing their values.
        header = pd.read_csv(path, nrows=0).columns.tolist()
        clock = header[0]
        raw = pd.read_csv(path, usecols=[clock] + channels, skiprows=range(1, start + 1),
                          nrows=samples, float_precision='round_trip')
        index = pd.DatetimeIndex(pd.to_datetime(raw.pop(clock), errors='raise'))
        source_slice = [start, start + samples]
        clock_origin = 'Frozen WaterHub adapted minute-end calendar; preserved gaps remain explicit sensor NaNs.'
    sensors = raw.loc[:, channels]; sensors.index = index
    if len(sensors) != samples: raise ValueError('Original test prefix was shorter than declared')
    metadata = {'path': relative, 'sha256': source_sha, 'original_source_row_bounds': source_slice,
                'original_test_axis_bounds': [start, start + samples],
                'columns_parsed': ['Time' if case == '2019_disclosed_test' else clock] + channels,
                'label_columns_parsed': False, 'clock_origin': clock_origin}
    return sensors, metadata


def verify_run_prefixes(run, *, cases=ALLOWED_CASES, samples=PREFIX_ROWS, output=None):
    """Explicitly verify the two preselected original prefixes; write one new JSON."""
    run = Path(run).resolve()
    if len(cases) != len(set(cases)) or not cases or any(c not in ALLOWED_CASES for c in cases):
        raise ValueError('Only the explicitly authorized cases are supported')
    if samples != PREFIX_ROWS: raise ValueError('This verification plan is fixed at1600original test rows')
    output = Path(output).resolve() if output else run / 'streaming_audit.json'
    if output.exists(): raise FileExistsError('An existing stream audit will not be overwritten')
    # Verify every requested case first, before any fitted model/sensor access.
    gates = {case: prototype.verify_run(run, case, research_preview=True) for case in cases}
    first = next(iter(gates.values()))
    runtime_hashes = dict(first['production_hashes'])
    for relative in ('ml/gecco_v9/streaming.py', 'ml/gecco_v9/verify_stream.py', 'ml/gecco_v9/prototype.py'):
        runtime_hashes[relative] = prototype.sha(first['root'] / relative)
    evidence = {'schema_version': 1, 'passed': False, 'development_only': True,
                'model_acceptance_claim': False, 'research_preview_only': True,
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'streaming_sha256': runtime_hashes['ml/gecco_v9/streaming.py'],
                'runtime_code_sha256': runtime_hashes,
                'batch_audit_sha256': first['verified_hashes']['audit.json'],
                'verified_bundle_sha256': {}, 'cases': [],
                'environment': {'platform': platform.platform(), 'python': platform.python_version(),
                                'numpy': np.__version__, 'pandas': pd.__version__, 'threadpool_limit': 1},
                'limitations': ['Only the named fitted bundles and first1600original test rows were stream-verified; this is not full-period or all-period stream proof.',
                    'All19periods passed the separate batch artifact/replay audit; model development acceptance remains separate and may fail.',
                    'Timing and memory were measured on the current computer, not a RaspberryPi.',
                    'Synthetic tests cover active confirmation/rescue/unknown/continuous alarms; an actual prefix may not exercise every policy state.',
                    'Core history is bounded, but fitted training-audit arrays and caller-owned chunk/input/output storage are not removed.',
                    'No actuator,3D,field-safety or chemical-fault validation is provided.']}
    try:
        with threadpool_limits(limits=1):
            for case, gate in gates.items():
                print(json.dumps({'case': case, 'phase': 'stream_prefix_verification', 'rows': samples}), flush=True)
                bundle, channels = prototype._load_bundle(gate)
                sensors, source = _source_prefix(gate, case, channels, samples)
                record, batch = verify_prefix(bundle, sensors)
                # Replay the exact previously audited frozen result, without labels.
                columns = ['baseline', 'reference', 'candidate', 'long_context', 'rescue_long_context']
                saved_path = gate['folder'] / 'predictions.csv.gz'
                audit = prototype.read_json(run / 'audit.json')
                saved_sha = prototype._equal_hash(saved_path, audit['hashes'].get(case + '/predictions.csv.gz'), 'Frozen test predictions')
                saved = pd.read_csv(saved_path, usecols=columns, nrows=samples, float_precision='round_trip')
                for old, new in (('baseline', 'baseline_prediction'), ('reference', 'reference_prediction'), ('candidate', 'prediction')):
                    if not np.array_equal(saved[old].to_numpy(), batch[new].to_numpy()):
                        raise AssertionError('Original saved prediction prefix mismatch: ' + new)
                for key in ('long_context', 'rescue_long_context'):
                    if not np.allclose(saved[key], batch[key], atol=ABSOLUTE_SCORE_TOLERANCE, rtol=0, equal_nan=True):
                        raise AssertionError('Original saved score prefix mismatch: ' + key)
                record.update(case_id=case, source=source, original_saved_prediction_sha256=saved_sha,
                              saved_prefix_replay_passed=True,
                              selected_policy={key: bundle['selected'].get(key) for key in
                                 ('decision', 'low_threshold', 'high_threshold', 'policy', 'confirmation_samples', 'cadence_seconds')})
                evidence['cases'].append(record)
                evidence['verified_bundle_sha256'][case] = gate['verified_hashes'][case + '/bundle.joblib']
                del bundle, sensors, batch, saved; gc.collect()
        for case, gate in gates.items():
            again = prototype.verify_run(run, case, research_preview=True)
            if again['verified_hashes'] != gate['verified_hashes']: raise ValueError('Audited artifacts changed during stream verification')
        for relative, digest in runtime_hashes.items(): prototype._equal_hash(first['root'] / relative, digest, 'Runtime dependency')
        for record in evidence['cases']:
            prototype._equal_hash(first['root'] / record['source']['path'], record['source']['sha256'], 'Source after verification')
        evidence['passed'] = True
    except Exception as error:
        evidence['failure'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        evidence['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        with output.open('x') as handle: json.dump(evidence, handle, indent=2, allow_nan=False); handle.write('\n')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify_run_prefixes(args.run, output=args.output)
    print(json.dumps({'passed': result['passed'], 'cases': list(result['verified_bundle_sha256'])}))
