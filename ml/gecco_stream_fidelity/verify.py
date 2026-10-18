"""Explicit fixed-prefix engineering verification, never model selection.

Run only after synthetic tests pass and the two already disclosed prefixes are
authorized. No labels are parsed, no model is fitted and no old artifact is
overwritten. A PASS here does not enable the existing prototype automatically.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import pickle
import platform
import resource
import sys
import time

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.gecco_v9 import prototype
from ml.gecco_v9.runtime import predict_frame
from ml.gecco_v9.verify_stream import _source_prefix, _typed_output, compare_outputs
from ml.gecco_v2.candidates_supervised import build_features
from ml.gecco_stream_fidelity.rolling import RollingBaselineFeatures, validate_environment, PANDAS_KERNEL_SHA256
from ml.gecco_stream_fidelity.runtime import StreamingPredictor

ROOT = Path(__file__).resolve().parents[2]
CASES = ('2019-04', '2019_disclosed_test')
ROWS = 1600


def verify_prefix(bundle, frame):
    sensors = frame.loc[:, bundle['long_model'].channels]
    gap = int(bundle['gap_samples'])
    tail = sensors.iloc[gap:]
    expected_features, expected_available, _ = build_features(tail, 'baseline15', list(sensors))
    features, available = RollingBaselineFeatures(list(sensors)).update_frame(tail)
    np.testing.assert_array_equal(features, expected_features)
    np.testing.assert_array_equal(available, expected_available)
    # The clock is the actual source clock. No nominal timestamp is invented.
    engine = StreamingPredictor(bundle)
    if (not isinstance(sensors.index, pd.DatetimeIndex) or sensors.index.hasnans
            or not np.all(sensors.index[1:] - sensors.index[:-1] == engine.interval)):
        raise ValueError('An actual regular source clock is required')
    baseline = predict_frame(bundle, sensors)
    records, timing = [], []
    maximum = {'long_sensor_rows': 0, 'reference_sensor_rows': 0,
               'reference_score_rows': 0, 'rescue_score_rows': 0,
               'rolling_rows_per_channel': 0, 'rolling_state_pickle_bytes': 0}
    for timestamp, row in sensors.iterrows():
        started = time.perf_counter(); records.append(engine.update(timestamp, row))
        timing.append(time.perf_counter() - started)
        stats = {'long_sensor_rows': len(engine.sensor_rows),
                 'reference_sensor_rows': len(engine.reference.sensor_rows),
                 'reference_score_rows': len(engine.reference.score_history),
                 'rescue_score_rows': len(engine.rescue_scores),
                 'rolling_rows_per_channel': max(len(s.values) for s in engine.reference.baseline_features.states),
                 'rolling_state_pickle_bytes': len(pickle.dumps(engine.reference.baseline_features.states))}
        maximum = {key: max(value, stats[key]) for key, value in maximum.items()}
    single = _typed_output(records, sensors.index)
    single_difference = compare_outputs(baseline, single)
    edges = [0, 1, 119, 120, 121, 134, 180, 801, 1560, 1561, ROWS]
    chunked_engine = StreamingPredictor(bundle)
    started = time.perf_counter()
    chunks = pd.concat([chunked_engine.update_frame(sensors.iloc[a:b]) for a,b in zip(edges[:-1],edges[1:])])
    chunk_seconds = time.perf_counter() - started
    chunk_difference = compare_outputs(baseline, chunks)
    np.testing.assert_array_equal(single.prediction, chunks.prediction)
    timing = np.asarray(timing)[gap:]
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss = int(peak_rss if sys.platform == 'darwin' else peak_rss * 1024)
    return {'tested_sample_bounds': [0, len(sensors)], 'full_period_tested': False,
            'exact_original_baseline_features': True, 'feature_values_compared': int(features.size),
            'exact_eligibility': True, 'exact_predictions_and_masks': True,
            'score_absolute_tolerance': 1e-12, 'score_relative_tolerance': 0.0,
            'maximum_absolute_score_errors': {'row_updates': single_difference, 'chunk_updates': chunk_difference},
            'chunk_boundaries': edges, 'maximum_retained_state': maximum,
            'latency_after_initial_gap_seconds': {'rows': len(timing), 'mean': float(timing.mean()),
                'p50': float(np.quantile(timing,.5)), 'p95': float(np.quantile(timing,.95)), 'maximum': float(timing.max()),
                'sum': float(timing.sum())},
            'chunked_total_seconds': chunk_seconds, 'process_lifetime_peak_rss_bytes': peak_rss,
            'memory_scope': 'PeakRSS includes loaded fitted models/imports/batch verification/input/output. Serialized rolling state size is not a full RAM measurement.',
            'actual_clock': {'first': sensors.index[0].isoformat(), 'last': sensors.index[-1].isoformat(),
                             'sample_seconds': float(bundle['sample_seconds'])}}, baseline


def run(run_dir, output):
    run_dir, output = Path(run_dir).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / 'actual_prefix_verification.json'
    plan_path = output / 'verification_plan.json'
    if result_path.exists() or plan_path.exists(): raise FileExistsError('Previous numerical verification artifacts are retained')
    validate_environment()
    gates = {case: prototype.verify_run(run_dir, case, research_preview=True) for case in CASES}
    dependencies = dict(next(iter(gates.values()))['production_hashes'])
    for path in [*sorted((ROOT/'ml/gecco_stream_fidelity').glob('*.py')),
                 ROOT/'ml/gecco_v9/streaming.py', ROOT/'ml/gecco_v9/verify_stream.py', ROOT/'ml/gecco_v9/prototype.py']:
        dependencies[str(path.relative_to(ROOT))] = prototype.sha(path)
    failure = run_dir / 'streaming_audit.json'
    plan = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'cases': list(CASES), 'first_original_test_rows': ROWS,
            'no_selection_or_refitting': True, 'labels_parsed': False,
            'current_code_sha256': dependencies, 'pandas_kernel_sha256': PANDAS_KERNEL_SHA256,
            'unchanged_failed_prior_audit_sha256': prototype.sha(failure),
            'batch_audit_sha256': prototype.sha(run_dir/'audit.json'),
            'design_sha256': prototype.sha(output/'design.json')}
    plan_path.write_text(json.dumps(plan,indent=2,allow_nan=False)+'\n')
    result = {'passed': False, 'scope': 'Experimental numerical implementation fidelity on two fixed previously exposed prefixes; not all-period or new-data validation.',
              'model_acceptance_claim': False, 'prototype_enabled': False,
              'verification_plan_sha256': prototype.sha(plan_path), 'cases': [],
              'environment': {'platform': platform.platform(), 'python': platform.python_version(),
                              'pandas': pd.__version__, 'numpy': np.__version__, 'threadpool_limit': 1},
              'limitations': ['Qualified only on the pinned Darwinarm64 pandas kernel; not a Pi benchmark.',
                  'No existing model, threshold, frozen runtime, prototype, label or previous failure evidence changed.',
                  'Other bundles/periods/new data need their own evidence; two prefixes cannot certify long-running deployment.',
                  'The original all19period statistical evaluation and failed acceptance remain unchanged.']}
    try:
        with threadpool_limits(limits=1):
            for case, gate in gates.items():
                print(json.dumps({'case':case,'phase':'fixed_prefix_numerical_verification','rows':ROWS}),flush=True)
                bundle, channels = prototype._load_bundle(gate)
                frame, source = _source_prefix(gate,case,channels,ROWS)
                record, batch = verify_prefix(bundle,frame)
                saved_path = gate['folder']/'predictions.csv.gz'
                audit = prototype.read_json(run_dir/'audit.json')
                prototype._equal_hash(saved_path,audit['hashes'][case+'/predictions.csv.gz'],'Saved prefix')
                saved = pd.read_csv(saved_path,nrows=ROWS,usecols=['baseline','reference','candidate','long_context','rescue_long_context'],float_precision='round_trip')
                for old,new in [('baseline','baseline_prediction'),('reference','reference_prediction'),('candidate','prediction')]:
                    np.testing.assert_array_equal(saved[old],batch[new])
                for column in ('long_context','rescue_long_context'):
                    np.testing.assert_allclose(saved[column],batch[column],atol=1e-12,rtol=0,equal_nan=True)
                record.update(case_id=case,source=source,original_saved_prefix_replay=True,
                              bundle_sha256=gate['verified_hashes'][case+'/bundle.joblib'])
                result['cases'].append(record)
                print(json.dumps({'case':case,'passed':True,'maximum_score_error':max(max(errors.values()) for errors in record['maximum_absolute_score_errors'].values())}),flush=True)
                del bundle,frame,batch,saved;gc.collect()
        for relative,digest in dependencies.items(): prototype._equal_hash(ROOT/relative,digest,'Unchanged dependency')
        prototype._equal_hash(failure,plan['unchanged_failed_prior_audit_sha256'],'Preserved previous failure')
        for case,gate in gates.items():
            after = prototype.verify_run(run_dir,case,research_preview=True)
            if after['verified_hashes'] != gate['verified_hashes']: raise ValueError('Audited bundle/source closure changed')
        for record in result['cases']:
            prototype._equal_hash(ROOT/record['source']['path'],record['source']['sha256'],'Unchanged source')
        result['passed'] = True
    except Exception as error:
        result['failure'] = {'type':type(error).__name__,'message':str(error)}
        raise
    finally:
        result['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        with result_path.open('x') as handle: json.dump(result,handle,indent=2,allow_nan=False);handle.write('\n')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'output/ml/gecco-stream-fidelity')
    args=parser.parse_args();proof=run(args.run,args.output)
    print(json.dumps({'passed':proof['passed'],'cases':len(proof['cases'])}))
