"""Local development-only V9 sensor CSV replay; never an actuator interface.

Joblib is executable serialization: use ONLY trusted, locally created bundles.
Matching hashes establish artifact consistency, not trust in arbitrary files.
Import does no IO. The CLI never trains, changes an operating point, or reads
label columns into inference. Failed development gates require --research-preview.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'v9_conditional_hgb_temporally_certified_120s'
ATTEMPT = 'v9_run01_conditional_residual_hgb_certified'
CASES = ([f'{year}_fold_{i}' for year in ('2017', '2018') for i in range(1, 7)]
         + ['2019_disclosed_test', '2018-11', '2018-12', '2019-01', '2019-02', '2019-03', '2019-04'])
LABEL_NAMES = {'label', 'labels', 'event', 'anomaly', 'attack', 'target'}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def inside(root, relative):
    root = Path(root).resolve(); result = (root / relative).resolve()
    if not result.is_relative_to(root): raise ValueError('Artifact path escapes its declared root')
    return result


def _equal_hash(path, expected, what):
    actual = sha(path)
    if not isinstance(expected, str) or actual != expected: raise ValueError(what + ' hash mismatch')
    return actual


def verify_run(run, case, *, research_preview=False, workspace_root=None):
    """Metadata/hash gate before any executable bundle or sensor-row load."""
    root = Path(workspace_root).resolve() if workspace_root else ROOT
    run = Path(run).resolve()
    if case not in CASES: raise ValueError('An exact prespecified case is required')
    result = read_json(run / 'results.json'); plan = read_json(run / 'plan.json'); audit = read_json(run / 'audit.json')
    if (plan.get('attempt') != ATTEMPT or plan.get('scope') != 'all' or plan.get('limit_cases') != 19
            or result.get('complete_cases') != 19 or result.get('expected_cases') != 19
            or result.get('all_prespecified_cases_complete') is not True
            or [p.get('case') for p in result.get('periods', [])] != CASES
            or not result.get('completed_at_utc') or (run / 'failed_case.json').exists()):
        raise ValueError('All 19 prespecified development cases must be complete')
    if (audit.get('passed') is not True or audit.get('failed_checks') != 0
            or audit.get('complete_replayed_cases') != 19 or audit.get('replayed_rows') != 449431
            or audit.get('attempt') != ATTEMPT):
        raise ValueError('A matching PASS audit of all 19 cases is required')
    if (plan.get('fresh_validation') is not False or result.get('fresh_validation') is not False
            or audit.get('fresh_validation') is not False):
        raise ValueError('This interface expects the declared development-only scope')
    hashes = audit['hashes']
    verified = {'plan.json': _equal_hash(run / 'plan.json', hashes.get('plan.json'), 'Plan'),
                'results.json': _equal_hash(run / 'results.json', hashes.get('results.json'), 'Results'),
                'audit.json': sha(run / 'audit.json')}
    verified['audit_script'] = _equal_hash(root / 'ml/gecco_v9_audits/replay.py', audit.get('audit_script_sha256'), 'Auditor')
    production = {}
    required = {'ml/gecco_v9/conditional.py', 'ml/gecco_v9/development.py', 'ml/gecco_v9/runtime.py',
                'ml/gecco_v8/onset.py', 'ml/gecco_v7/calibration_certified.py', 'ml/gecco_v7/runtime_delayed.py'}
    if not required.issubset(plan.get('code_sha256', {})): raise ValueError('Incomplete frozen production code inventory')
    for relative, expected in plan['code_sha256'].items():
        production[relative] = _equal_hash(inside(root, relative), expected, 'Current production code')
        _equal_hash(inside(run / 'source', relative), expected, 'Frozen production code')
    folder = inside(run, case); freeze = read_json(folder / 'freeze.json')
    for filename in ('freeze.json', 'bundle.joblib', 'results.json'):
        verified[case + '/' + filename] = _equal_hash(folder / filename, hashes.get(case + '/' + filename), 'Case artifact')
    if freeze.get('plan_sha256') != verified['plan.json']:
        raise ValueError('Case freeze does not belong to the verified plan')
    if freeze.get('bundle_sha256') != verified[case + '/bundle.joblib']:
        raise ValueError('Bundle does not match its freeze')
    local_result = read_json(folder / 'results.json')
    if local_result != next(p for p in result['periods'] if p['case'] == case):
        raise ValueError('Case result differs from the complete-run result')
    if local_result.get('selected') != freeze.get('selected'):
        raise ValueError('Case operating point differs from its freeze')
    acceptance = all(result['summary'][key]['passes_declared_development_gate'] is True
                     for key in ('if_vs_v7', 'v6_vs_v7'))
    audited_acceptance = all(audit['recomputed_development_gates'].get(key) is True
                            for key in ('if_vs_v7', 'v6_vs_v7'))
    if acceptance != audited_acceptance: raise ValueError('Acceptance verdict differs from independent audit')
    if not acceptance and not research_preview:
        raise ValueError('Development acceptance failed; explicit --research-preview is required')
    return {'run': run, 'folder': folder, 'root': root, 'freeze': freeze,
            'verified_hashes': verified, 'production_hashes': production,
            'development_acceptance_passed': acceptance,
            'status': 'research_only' if not acceptance or research_preview else 'development_prototype'}


def _bootstrap_legacy_imports(root):
    """Resolve trusted historical pickle class names after the hash gates.

    Older local bundles contain top-level module names such as
    supported_candidate/local_change. A fresh CLI has not imported runtime_v4
    yet, so it must establish that runtime's own fixed workspace paths first.
    No environment PYTHONPATH or caller working directory is required.
    """
    root = Path(root).resolve()
    for relative in ('.', 'ml/gecco_v6', 'ml/gecco_v5', 'ml/gecco_v2', 'ml/gecco_baseline'):
        directory = str(inside(root, relative))
        if directory not in sys.path: sys.path.insert(0, directory)


def _load_bundle(gate):
    # Trusted local serialization only, and only after all metadata/hash gates.
    _bootstrap_legacy_imports(gate['root'])
    import joblib
    bundle = joblib.load(gate['folder'] / 'bundle.joblib')
    if bundle.get('version') != VERSION: raise ValueError('Wrong bundle version')
    if bundle.get('selected') != gate['freeze']['selected']: raise ValueError('Loaded operating point mismatch')
    channels = list(bundle['long_model'].channels)
    if (not channels or len(channels) != len(set(channels))
            or any(not isinstance(c, str) or c.lower() in LABEL_NAMES or c == 'timestamp' for c in channels)):
        raise ValueError('Fitted sensor schema is invalid or contains an annotation column')
    if channels != list(bundle['reference_bundle']['local_model'].channels): raise ValueError('Reference sensor order differs')
    if (bundle['max_fit_index'] != gate['freeze']['train'][1] - 1
            or bundle['max_calibration_index'] != gate['freeze']['test'][0] - 1
            or bundle['max_fit_index'] >= bundle['max_calibration_index']):
        raise ValueError('Loaded training/calibration bounds mismatch')
    return bundle, channels


def verify_stream_audit(gate, case, path=None):
    """A batch audit or synthetic stream fixture cannot authorize a real bundle."""
    path = Path(path).resolve() if path else gate['run'] / 'streaming_audit.json'
    evidence = read_json(path)
    if evidence.get('schema_version') != 1 or evidence.get('passed') is not True:
        raise ValueError('A separate PASS streaming audit is required')
    if evidence.get('batch_audit_sha256') != gate['verified_hashes']['audit.json']:
        raise ValueError('Streaming evidence does not match the batch audit')
    expected_bundle = gate['verified_hashes'][case + '/bundle.joblib']
    if evidence.get('verified_bundle_sha256', {}).get(case) != expected_bundle:
        raise ValueError('This actual fitted bundle has not passed stream verification')
    _equal_hash(gate['root'] / 'ml/gecco_v9/streaming.py', evidence.get('streaming_sha256'), 'Streaming implementation')
    runtime_hashes = evidence.get('runtime_code_sha256', {})
    required = {'ml/gecco_v9/runtime.py', 'ml/gecco_v7/runtime_delayed.py',
                'ml/gecco_v7/runtime_v2.py', 'ml/gecco_v6/runtime_v4.py'}
    if not required.issubset(runtime_hashes): raise ValueError('Streaming runtime dependency evidence is incomplete')
    for relative, digest in runtime_hashes.items(): _equal_hash(inside(gate['root'], relative), digest, 'Streaming dependency')
    records = [record for record in evidence.get('cases', []) if record.get('case_id') == case]
    if len(records) != 1: raise ValueError('One explicit tested-prefix record is required for this bundle')
    record = records[0]; bounds = record.get('tested_sample_bounds', [])
    if (len(bounds) != 2 or bounds[0] != 0 or not isinstance(bounds[1], int) or bounds[1] < 1600
            or record.get('exact_prediction_masks') is not True
            or not isinstance(record.get('score_tolerance'), (int, float))
            or not 0 <= record['score_tolerance'] <= 1e-12):
        raise ValueError('Streaming prefix evidence must cross the bounded-history boundary with exact prediction masks')
    return {'path': str(path), 'sha256': sha(path), 'case': record,
            'scope': 'Only this fitted bundle and the documented tested prefix; not all-period stream proof',
            'limitations': evidence.get('limitations', [])}


def _import_runtime(name):
    return importlib.import_module(name)


def _sensor_frames(path, channels, *, chunksize):
    """Project only timestamp and fitted channels; other CSV columns are ignored."""
    import pandas as pd
    with Path(path).open(newline='', encoding='utf-8-sig') as handle:
        header = next(csv.reader(handle), [])
    if len(header) != len(set(header)) or any(header.count(c) != 1 for c in ['timestamp'] + channels):
        raise ValueError('CSV requires unique timestamp and each fitted sensor column exactly once')
    reader = pd.read_csv(path, usecols=['timestamp'] + channels, chunksize=chunksize)
    frames = reader if chunksize else [reader]
    try:
        for frame in frames:
            timestamps = pd.DatetimeIndex(pd.to_datetime(frame['timestamp'], errors='raise'))
            if timestamps.hasnans: raise ValueError('Missing timestamps are not allowed')
            sensors = frame.loc[:, channels].apply(pd.to_numeric, errors='raise')
            sensors.index = timestamps
            sensors.index.name = 'timestamp'
            yield sensors
    finally:
        if chunksize: reader.close()


def _output_frame(scored):
    import numpy as np
    import pandas as pd
    required = ['prediction', 'long_context', 'reference_prediction', 'available']
    if not all(c in scored for c in required): raise ValueError('Runtime output schema mismatch')
    if (not np.isin(scored.prediction, [-1, 0, 1]).all()
            or not np.isin(scored.reference_prediction, [-1, 0, 1]).all()):
        raise ValueError('Runtime must preserve ternary predictions')
    return pd.DataFrame({'timestamp': scored.index, 'prediction': scored.prediction.to_numpy(),
                         'model_score': scored.long_context.to_numpy(),
                         'reference_prediction': scored.reference_prediction.to_numpy(),
                         'available': scored.available.to_numpy()})


def run_replay(run, case, input_path, output_path, *, mode='stream', research_preview=False, workspace_root=None, stream_audit=None):
    """Write one new CSV plus .manifest.json; keep partial files after failures."""
    if mode not in ('batch', 'stream'): raise ValueError('Mode must be batch or stream')
    input_path, output_path = Path(input_path).resolve(), Path(output_path).resolve()
    manifest_path = output_path.with_suffix(output_path.suffix + '.manifest.json')
    if input_path in (output_path, manifest_path): raise ValueError('Input cannot be overwritten')
    if output_path.exists() or manifest_path.exists(): raise FileExistsError('Output or manifest already exists')
    if not input_path.is_file(): raise FileNotFoundError('Input CSV does not exist')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'initializing',
                'completed': False, 'development_only': True, 'fresh_validation': False,
                'actuator_integration': False, 'water_safety_probability': False,
                'score_meaning': 'model_score is a learned anomaly/event ranking, not a probability of safe water',
                'case': case, 'mode': mode, 'research_preview_requested': bool(research_preview),
                'input_path': str(input_path), 'output_path': str(output_path), 'rows_written': 0,
                'limitations': ['Development results do not establish field safety or performance at a new site.',
                                'Each invocation resets state and applies the saved gap/warmup.',
                                'Only aligned timestamps and ordered sensor readings enter inference; labels are ignored.']}
    # Exclusively reserve both new paths. These handles belong only to this run.
    with output_path.open('x', newline='') as output, manifest_path.open('x') as manifest_handle:
        def save_manifest():
            manifest_handle.seek(0); manifest_handle.truncate()
            json.dump(manifest, manifest_handle, indent=2, allow_nan=False); manifest_handle.write('\n'); manifest_handle.flush()
        save_manifest()
        try:
            gate = verify_run(run, case, research_preview=research_preview, workspace_root=workspace_root)
            manifest.update({k: gate[k] for k in ('verified_hashes', 'production_hashes', 'development_acceptance_passed', 'status')})
            manifest['run'] = str(gate['run'])
            if mode == 'stream': manifest['stream_verification'] = verify_stream_audit(gate, case, stream_audit)
            if str(gate['root']) not in sys.path: sys.path.insert(0, str(gate['root']))
            bundle, channels = _load_bundle(gate)
            manifest['channels'] = channels; manifest['sample_seconds'] = float(bundle['sample_seconds'])
            manifest['gap_samples'] = int(bundle['gap_samples'])
            manifest['input_sha256'] = sha(input_path)
            module_name = 'ml.gecco_v9.streaming' if mode == 'stream' else 'ml.gecco_v9.runtime'
            runtime_path = gate['root'] / ('ml/gecco_v9/streaming.py' if mode == 'stream' else 'ml/gecco_v9/runtime.py')
            runtime_hash = sha(runtime_path)
            runtime = _import_runtime(module_name)
            if Path(runtime.__file__).resolve() != runtime_path.resolve(): raise ValueError('Unexpected runtime import path')
            manifest['runtime_module'] = module_name; manifest['runtime_sha256'] = runtime_hash
            manifest['prototype_sha256'] = sha(__file__)
            engine = runtime.StreamingPredictor(bundle) if mode == 'stream' else None
            wrote_header = False
            for sensors in _sensor_frames(input_path, channels, chunksize=256 if mode == 'stream' else None):
                scored = engine.update_frame(sensors) if mode == 'stream' else runtime.predict_frame(bundle, sensors)
                if len(scored) != len(sensors) or not scored.index.equals(sensors.index): raise ValueError('Runtime changed the timestamp axis')
                _output_frame(scored).to_csv(output, index=False, header=not wrote_header)
                wrote_header = True; output.flush(); manifest['rows_written'] += len(scored)
            if not wrote_header:
                output.write('timestamp,prediction,model_score,reference_prediction,available\n'); output.flush()
            _equal_hash(input_path, manifest['input_sha256'], 'Input changed during replay')
            _equal_hash(runtime_path, runtime_hash, 'Runtime changed during replay')
            # Detect a concurrent change to any audited model/dependency/output.
            final_gate = verify_run(run, case, research_preview=research_preview, workspace_root=workspace_root)
            if final_gate['verified_hashes'] != gate['verified_hashes']: raise ValueError('Audited artifacts changed during replay')
            if mode == 'stream':
                again = verify_stream_audit(final_gate, case, stream_audit)
                if again['sha256'] != manifest['stream_verification']['sha256']: raise ValueError('Streaming evidence changed during replay')
            manifest['completed'] = True; manifest['output_sha256'] = sha(output_path)
        except Exception as error:
            manifest['failure'] = {'type': type(error).__name__, 'message': str(error)}
            manifest['partial_output_retained'] = True
            manifest['status'] = 'failed_replay'
            raise
        finally:
            manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat(); save_manifest()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('run', 'case', 'input', 'output'): parser.add_argument('--' + flag, required=True)
    parser.add_argument('--mode', choices=('batch', 'stream'), default='stream')
    parser.add_argument('--research-preview', action='store_true')
    parser.add_argument('--stream-audit', help='Defaults to RUN/streaming_audit.json; actual fitted-bundle prefix verification required')
    args = parser.parse_args()
    result = run_replay(args.run, args.case, args.input, args.output, mode=args.mode,
                        research_preview=args.research_preview, stream_audit=args.stream_audit)
    print(json.dumps({k: result[k] for k in ('status', 'completed', 'development_acceptance_passed', 'rows_written')}))


if __name__ == '__main__': main()
