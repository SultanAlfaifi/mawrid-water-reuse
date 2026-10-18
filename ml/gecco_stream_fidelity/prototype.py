"""Strictly scoped, sensor-only research replay using the qualified V9 adapter.

Only the two verified initial 1600-row CSVs are accepted. This is a replay
preview, not a new sensor deployment, model acceptance, or actuator interface.
Bundles are trusted local executable serialization; hashes establish consistency
of that local evidence, not trust in arbitrary joblib files. Import does no I/O.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if not __package__ and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ml.gecco_v9 import prototype as original

CASES = ('2019-04', '2019_disclosed_test')
ROWS = 1600
RUNTIME = 'ml.gecco_stream_fidelity.runtime'
REQUIRED_CODE = {
    'ml/gecco_stream_fidelity/__init__.py',
    'ml/gecco_stream_fidelity/rolling.py', 'ml/gecco_stream_fidelity/runtime.py',
    'ml/gecco_v9/streaming.py', 'ml/gecco_v9/runtime.py',
    'ml/gecco_v7/runtime_delayed.py', 'ml/gecco_v7/runtime_v2.py',
    'ml/gecco_v6/runtime_v4.py', 'ml/gecco_v2/candidates_supervised.py',
}


def _environment(evidence, plan):
    import numpy as np
    import pandas as pd
    from ml.gecco_stream_fidelity.rolling import validate_environment, PANDAS_KERNEL_SHA256
    validate_environment()
    if plan.get('pandas_kernel_sha256') != PANDAS_KERNEL_SHA256:
        raise ValueError('Numerical kernel qualification mismatch')
    expected = evidence.get('environment', {})
    actual = {'platform': platform.platform(), 'python': platform.python_version(),
              'numpy': np.__version__, 'pandas': pd.__version__, 'threadpool_limit': 1}
    if actual != expected:
        raise ValueError('Current environment differs from the qualified replay environment')
    return actual


def verify_qualification(gate, case, evidence_path, input_proof_path, input_path):
    """All metadata/hash checks precede sensor decoding and bundle unpickling."""
    if case not in CASES:
        raise ValueError('Only the two qualified V9 cases are supported')
    evidence_path, input_proof_path = Path(evidence_path).resolve(), Path(input_proof_path).resolve()
    evidence = original.read_json(evidence_path)
    plan_path = evidence_path.parent / 'verification_plan.json'
    plan = original.read_json(plan_path)
    if (evidence.get('passed') is not True or evidence.get('model_acceptance_claim') is not False
            or [c.get('case_id') for c in evidence.get('cases', [])] != list(CASES)
            or plan.get('cases') != list(CASES) or plan.get('first_original_test_rows') != ROWS
            or plan.get('labels_parsed') is not False or plan.get('no_selection_or_refitting') is not True):
        raise ValueError('Matching completed two-prefix numerical evidence is required')
    original._equal_hash(plan_path, evidence.get('verification_plan_sha256'), 'Numerical verification plan')
    if plan.get('batch_audit_sha256') != gate['verified_hashes']['audit.json']:
        raise ValueError('Numerical evidence belongs to another batch audit')
    dependencies = plan.get('current_code_sha256', {})
    if not REQUIRED_CODE.issubset(dependencies) or not set(gate['production_hashes']).issubset(dependencies):
        raise ValueError('Numerical runtime dependency closure is incomplete')
    for relative, digest in dependencies.items():
        original._equal_hash(original.inside(gate['root'], relative), digest, 'Qualified numerical dependency')
    original._equal_hash(gate['run'] / 'streaming_audit.json',
                         plan.get('unchanged_failed_prior_audit_sha256'), 'Preserved prior failed stream evidence')
    records = [c for c in evidence.get('cases', []) if c.get('case_id') == case]
    if len(records) != 1:
        raise ValueError('Exactly one qualified prefix record is required')
    record = records[0]
    if (record.get('tested_sample_bounds') != [0, ROWS]
            or record.get('full_period_tested') is not False
            or record.get('exact_original_baseline_features') is not True
            or record.get('exact_eligibility') is not True
            or record.get('exact_predictions_and_masks') is not True
            or record.get('original_saved_prefix_replay') is not True
            or record.get('score_absolute_tolerance') != 1e-12
            or record.get('score_relative_tolerance') != 0
            or record.get('bundle_sha256') != gate['verified_hashes'][case + '/bundle.joblib']):
        raise ValueError('This exact bundle and initial prefix are not qualified')
    errors = record.get('maximum_absolute_score_errors', {})
    if (set(errors) != {'row_updates', 'chunk_updates'} or
            any(not values or any(not isinstance(v, (int, float)) or not 0 <= v <= 1e-12
                                  for v in values.values()) for values in errors.values())):
        raise ValueError('Score fidelity evidence is incomplete or exceeds the unchanged tolerance')
    environment = _environment(evidence, plan)
    proof = original.read_json(input_proof_path)
    if (proof.get('schema_version') != 1 or proof.get('sensor_only') is not True
            or proof.get('actual_prefix_verification_sha256') != original.sha(evidence_path)
            or proof.get('verification_plan_sha256') != original.sha(plan_path)):
        raise ValueError('Sensor CSV qualification does not match numerical evidence')
    inputs = [c for c in proof.get('cases', []) if c.get('case_id') == case]
    if len(inputs) != 1:
        raise ValueError('This qualified sensor CSV is not documented')
    item = inputs[0]
    channels = record['source']['columns_parsed'][1:]
    if (item.get('rows') != ROWS or item.get('columns') != ['timestamp'] + channels
            or item.get('source') != record['source']
            or item.get('actual_clock') != record['actual_clock']
            or item.get('numeric_roundtrip_exact') is not True
            or item.get('label_columns_parsed') is not False):
        raise ValueError('Sensor CSV scope differs from the tested prefix')
    original._equal_hash(input_path, item.get('csv_sha256'), 'Qualified sensor CSV')
    return {'evidence_path': str(evidence_path), 'evidence_sha256': original.sha(evidence_path),
            'plan_sha256': original.sha(plan_path), 'input_proof_path': str(input_proof_path),
            'input_proof_sha256': original.sha(input_proof_path), 'input_sha256': item['csv_sha256'],
            'case': record, 'channels': channels, 'environment': environment,
            'runtime_code_sha256': dependencies, 'pandas_kernel_sha256': plan['pandas_kernel_sha256'],
            'scope': 'Only this exact previously exposed 1600-row prefix and fitted V9 bundle'}


def _read_sensors(path, qualification):
    import numpy as np
    import pandas as pd
    columns = ['timestamp'] + qualification['channels']
    with Path(path).open(newline='', encoding='utf-8-sig') as handle:
        if next(csv.reader(handle), []) != columns:
            raise ValueError('Exactly timestamp and the ordered qualified sensors are required; no labels')
    frame = pd.read_csv(path, nrows=ROWS + 1, float_precision='round_trip')
    if len(frame) != ROWS:
        raise ValueError('Only the qualified initial 1600 rows are supported')
    index = pd.DatetimeIndex(pd.to_datetime(frame.pop('timestamp'), errors='raise'), name='timestamp')
    clock = qualification['case']['actual_clock']
    if (index.hasnans or index[0].isoformat() != clock['first'] or index[-1].isoformat() != clock['last']
            or not np.all(index[1:] - index[:-1] == pd.Timedelta(seconds=clock['sample_seconds']))):
        raise ValueError('Sensor CSV must retain the exact qualified clock and cadence')
    frame = frame.apply(pd.to_numeric, errors='raise')
    frame.index = index
    return frame


def _runtime():
    return importlib.import_module(RUNTIME)


def run_replay(run, case, input_path, output_path, *, evidence_path, input_proof_path,
               research_preview=False, workspace_root=None):
    if research_preview is not True:
        raise ValueError('This research-only adapter requires explicit --research-preview')
    if case not in CASES:
        raise ValueError('Only the two qualified V9 cases are supported')
    input_path, output_path = Path(input_path).resolve(), Path(output_path).resolve()
    manifest_path = output_path.with_suffix(output_path.suffix + '.manifest.json')
    if input_path in (output_path, manifest_path):
        raise ValueError('Input cannot be overwritten')
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError('Previous output and evidence are preserved')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'completed': False,
                'status': 'initializing', 'mode': 'qualified_numerical_stream_replay', 'research_only': True,
                'case': case, 'development_only': True, 'fresh_validation': False,
                'actuator_integration': False, 'water_safety_probability': False,
                'rows_written': 0, 'input_path': str(input_path), 'output_path': str(output_path),
                'model_version': 'V9', 'model_score_meaning': 'Event ranking, not a probability of safe water.',
                'limitations': ['V9 failed its all19-period statistical acceptance; numerical fidelity does not reverse it.',
                    'Only two already exposed initial1600-row prefixes are qualified. This is not a live deployment.',
                    'Exact pinned Darwinarm64 pandas kernel only; not a RaspberryPi benchmark.',
                    'Original failed streaming evidence and old prototype remain unchanged.',
                    'V12 and other models or periods are not qualified by this interface.',
                    'Each invocation resets state, discards the saved120-row gap and retains original warmup/unknowns.']}
    with output_path.open('x', newline='') as output, manifest_path.open('x') as handle:
        def save():
            handle.seek(0); handle.truncate()
            json.dump(manifest, handle, indent=2, allow_nan=False); handle.write('\n'); handle.flush()
        save()
        try:
            gate = original.verify_run(run, case, research_preview=True, workspace_root=workspace_root)
            qualification = verify_qualification(gate, case, evidence_path, input_proof_path, input_path)
            manifest.update(status='research_only', development_acceptance_passed=gate['development_acceptance_passed'],
                            run=str(gate['run']), verified_hashes=gate['verified_hashes'], qualification=qualification,
                            prototype_sha256=original.sha(__file__))
            sensors = _read_sensors(input_path, qualification)
            # The original trusted legacy bootstrap runs only after all gates.
            bundle, channels = original._load_bundle(gate)
            if channels != qualification['channels'] or bundle['sample_seconds'] != qualification['case']['actual_clock']['sample_seconds']:
                raise ValueError('Loaded model schema/cadence differs from the qualified sensor prefix')
            runtime = _runtime()
            runtime_path = gate['root'] / 'ml/gecco_stream_fidelity/runtime.py'
            if Path(runtime.__file__).resolve() != runtime_path.resolve():
                raise ValueError('Unexpected numerical runtime import path')
            from threadpoolctl import threadpool_limits
            started = time.perf_counter()
            with threadpool_limits(limits=1):
                engine = runtime.StreamingPredictor(bundle)
                for start in range(0, ROWS, 256):
                    frame = sensors.iloc[start:start + 256]
                    scored = engine.update_frame(frame)
                    if len(scored) != len(frame) or not scored.index.equals(frame.index):
                        raise ValueError('Runtime changed the qualified sensor axis')
                    original._output_frame(scored).to_csv(output, index=False, header=start == 0)
                    output.flush(); manifest['rows_written'] += len(scored)
            manifest['elapsed_seconds'] = time.perf_counter() - started
            after = original.verify_run(run, case, research_preview=True, workspace_root=workspace_root)
            again = verify_qualification(after, case, evidence_path, input_proof_path, input_path)
            if gate['verified_hashes'] != after['verified_hashes'] or qualification != again:
                raise ValueError('Qualification changed during replay')
            original._equal_hash(__file__, manifest['prototype_sha256'], 'CLI changed during replay')
            manifest.update(completed=True, output_sha256=original.sha(output_path))
        except Exception as error:
            manifest.update(status='failed_replay', partial_output_retained=True,
                            failure={'type': type(error).__name__, 'message': str(error)})
            raise
        finally:
            manifest['finished_at_utc'] = datetime.now(timezone.utc).isoformat(); save()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('run', 'case', 'input', 'output'):
        parser.add_argument('--' + flag, required=True)
    folder = ROOT / 'output/ml/gecco-stream-fidelity'
    parser.add_argument('--evidence', default=folder / 'actual_prefix_verification.json', type=Path)
    parser.add_argument('--input-proof', default=folder / 'input_qualification.json', type=Path)
    parser.add_argument('--research-preview', action='store_true')
    args = parser.parse_args()
    result = run_replay(args.run, args.case, args.input, args.output, evidence_path=args.evidence,
                        input_proof_path=args.input_proof, research_preview=args.research_preview)
    print(json.dumps({k: result[k] for k in ('status', 'completed', 'development_acceptance_passed', 'rows_written')}))


if __name__ == '__main__':
    main()
