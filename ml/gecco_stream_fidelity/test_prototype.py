"""Synthetic artifact gates only; no actual source or fitted artifact reads."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_stream_fidelity import prototype as p
from ml.gecco_v9.test_prototype import fixture as old_fixture, fake_bundle


def dump(path, value):
    path.write_text(json.dumps(value))


def fixture(root):
    run, case = old_fixture(root)
    gate = p.original.verify_run(run, case, research_preview=True, workspace_root=root)
    for relative in p.REQUIRED_CODE:
        path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_text('# synthetic numerical fixture\n')
    failure = run / 'streaming_audit.json'; dump(failure, {'passed': False, 'synthetic': True})
    code = dict(gate['production_hashes'])
    code.update({name: p.original.sha(root / name) for name in p.REQUIRED_CODE})
    folder = root / 'evidence'; folder.mkdir()
    plan = {'cases': list(p.CASES), 'first_original_test_rows': 1600, 'labels_parsed': False,
            'no_selection_or_refitting': True, 'batch_audit_sha256': gate['verified_hashes']['audit.json'],
            'current_code_sha256': code, 'unchanged_failed_prior_audit_sha256': p.original.sha(failure),
            'pandas_kernel_sha256': 'synthetic-environment-is-mocked'}
    dump(folder / 'verification_plan.json', plan)
    timestamps = pd.date_range('2022-01-01', periods=1600, freq='min')
    source = {'columns_parsed': ['minute_end', 'p1', 'p2'], 'label_columns_parsed': False,
              'path': 'synthetic-only', 'sha256': 'synthetic'}
    clock = {'first': timestamps[0].isoformat(), 'last': timestamps[-1].isoformat(), 'sample_seconds': 60}
    record = {'case_id': case, 'tested_sample_bounds': [0, 1600], 'full_period_tested': False,
              'exact_original_baseline_features': True, 'exact_eligibility': True,
              'exact_predictions_and_masks': True, 'original_saved_prefix_replay': True,
              'score_absolute_tolerance': 1e-12, 'score_relative_tolerance': 0,
              'bundle_sha256': gate['verified_hashes'][case + '/bundle.joblib'],
              'maximum_absolute_score_errors': {'row_updates': {'baseline_score': 0.},
                                               'chunk_updates': {'baseline_score': 0.}},
              'source': source, 'actual_clock': clock}
    other = deepcopy(record); other['case_id'] = p.CASES[1]
    evidence = {'passed': True, 'model_acceptance_claim': False, 'cases': [record, other],
                'verification_plan_sha256': p.original.sha(folder / 'verification_plan.json')}
    evidence_path = folder / 'actual_prefix_verification.json'; dump(evidence_path, evidence)
    input_path = root / 'sensors.csv'
    pd.DataFrame({'timestamp': timestamps, 'p1': 1., 'p2': np.arange(1600)/7}).to_csv(input_path, index=False)
    input_record = {'case_id': case, 'rows': 1600, 'columns': ['timestamp', 'p1', 'p2'],
                    'source': source, 'actual_clock': clock, 'numeric_roundtrip_exact': True,
                    'label_columns_parsed': False, 'csv_sha256': p.original.sha(input_path)}
    proof = {'schema_version': 1, 'sensor_only': True,
             'actual_prefix_verification_sha256': p.original.sha(evidence_path),
             'verification_plan_sha256': evidence['verification_plan_sha256'], 'cases': [input_record]}
    proof_path = folder / 'input_qualification.json'; dump(proof_path, proof)
    return run, case, input_path, evidence_path, proof_path


class PrototypeTests(unittest.TestCase):
    def call(self, root, args, **kwargs):
        run, case, source, evidence, proof = args
        return p.run_replay(run, case, source, root / 'output.csv', evidence_path=evidence,
                            input_proof_path=proof, research_preview=True, workspace_root=root, **kwargs)

    def test_explicit_flag_and_supported_case_before_any_file_or_model_read(self):
        with patch.object(p.original, 'verify_run', side_effect=AssertionError('must remain closed')):
            with self.assertRaisesRegex(ValueError, 'research-preview'):
                p.run_replay('x', '2019-04', 'x', 'y', evidence_path='x', input_proof_path='x')
            with self.assertRaisesRegex(ValueError, 'two qualified'):
                p.run_replay('x', '2018_fold_1', 'x', 'y', evidence_path='x', input_proof_path='x', research_preview=True)

    def test_incomplete_numerical_proof_and_bundle_mismatch_block_before_rows_or_unpickle(self):
        changes = [lambda e: e.update(passed=False),
                   lambda e: e['cases'][0].update(bundle_sha256='wrong'),
                   lambda e: e['cases'][0].update(tested_sample_bounds=[0, 1599]),
                   lambda e: e['cases'][0].update(score_absolute_tolerance=1e-8),
                   lambda e: e['cases'][0]['maximum_absolute_score_errors']['row_updates'].update(baseline_score=float('nan'))]
        for mutate in changes:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); args = fixture(root)
                evidence = p.original.read_json(args[3]); mutate(evidence); dump(args[3], evidence)
                with patch.object(p, '_read_sensors', side_effect=AssertionError('sensor rows closed')), \
                     patch.object(p.original, '_load_bundle', side_effect=AssertionError('bundle closed')):
                    with self.assertRaises(ValueError): self.call(root, args)

    def test_batch_audit_or_dependency_mutation_blocks(self):
        for target in ('run/audit.json', 'ml/gecco_stream_fidelity/rolling.py', 'run/streaming_audit.json'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); args = fixture(root); path = root / target
                if target.endswith('audit.json') and target == 'run/audit.json':
                    item = p.original.read_json(path); item['passed'] = False; dump(path, item)
                else: path.write_bytes(path.read_bytes() + b' ')
                with patch.object(p.original, '_load_bundle', side_effect=AssertionError('bundle closed')):
                    with self.assertRaises(ValueError): self.call(root, args)

    def test_environment_mismatch_and_input_hash_before_decode(self):
        for environment_error in (True, False):
            with self.subTest(environment=environment_error), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); args = fixture(root)
                if not environment_error: args[2].write_text('malformed forbidden CSV contents')
                with patch.object(p, '_environment', side_effect=ValueError('environment') if environment_error else None,
                                  return_value={'synthetic': True}), \
                     patch.object(p, '_read_sensors', side_effect=AssertionError('must not decode')), \
                     patch.object(p.original, '_load_bundle', side_effect=AssertionError('must not unpickle')):
                    with self.assertRaises(ValueError): self.call(root, args)

    def test_sensor_reader_rejects_overlength_label_column_and_wrong_clock(self):
        for kind in ('overlength', 'label', 'duplicate_clock', 'wrong_clock', 'short'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); args = fixture(root); frame = pd.read_csv(args[2])
                if kind == 'overlength': frame = pd.concat([frame, frame.iloc[[-1]]], ignore_index=True)
                if kind == 'short': frame = frame.iloc[:-1]
                if kind == 'label': frame['EVENT'] = 'must never enter model'
                if kind == 'duplicate_clock': frame.loc[5, 'timestamp'] = frame.loc[4, 'timestamp']
                if kind == 'wrong_clock': frame['timestamp'] = pd.date_range('2023-01-01', periods=1600, freq='min')
                frame.to_csv(args[2], index=False)
                proof = p.original.read_json(args[4]); proof['cases'][0]['csv_sha256'] = p.original.sha(args[2]); dump(args[4], proof)
                with patch.object(p, '_environment', return_value={'synthetic': True}), \
                     patch.object(p.original, '_load_bundle', side_effect=AssertionError('must not unpickle')):
                    with self.assertRaises(ValueError): self.call(root, args)

    def test_success_preserves_exact_scope_and_research_failed_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); args = fixture(root); calls = []
            class Engine:
                def __init__(self, bundle): pass
                def update_frame(self, frame):
                    calls.append(frame.copy())
                    return pd.DataFrame({'prediction': 0, 'long_context': .2,
                        'reference_prediction': 0, 'available': True}, index=frame.index)
            runtime = SimpleNamespace(__file__=str(root / 'ml/gecco_stream_fidelity/runtime.py'), StreamingPredictor=Engine)
            with patch.object(p, '_environment', return_value={'synthetic': True}), \
                 patch.object(p.original, '_load_bundle', return_value=(fake_bundle(), ['p1', 'p2'])), \
                 patch.object(p, '_runtime', return_value=runtime):
                result = self.call(root, args)
            self.assertTrue(result['completed']); self.assertEqual(result['rows_written'], 1600)
            self.assertEqual(result['status'], 'research_only'); self.assertFalse(result['development_acceptance_passed'])
            self.assertFalse(result['fresh_validation']); self.assertFalse(result['actuator_integration'])
            self.assertEqual([len(c) for c in calls], [256]*6 + [64])
            self.assertTrue(all(list(c) == ['p1', 'p2'] for c in calls))
            self.assertEqual(len(pd.read_csv(root / 'output.csv')), 1600)
            self.assertEqual(result['qualification']['case']['tested_sample_bounds'], [0, 1600])

    def test_failure_keeps_only_completed_chunks_and_failure_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); args = fixture(root)
            class Engine:
                def __init__(self, bundle): self.calls = 0
                def update_frame(self, frame):
                    self.calls += 1
                    if self.calls == 2: raise ValueError('synthetic numerical failure')
                    return pd.DataFrame({'prediction': 0, 'long_context': .2,
                        'reference_prediction': 0, 'available': True}, index=frame.index)
            runtime = SimpleNamespace(__file__=str(root / 'ml/gecco_stream_fidelity/runtime.py'), StreamingPredictor=Engine)
            with patch.object(p, '_environment', return_value={'synthetic': True}), \
                 patch.object(p.original, '_load_bundle', return_value=(fake_bundle(), ['p1', 'p2'])), \
                 patch.object(p, '_runtime', return_value=runtime):
                with self.assertRaisesRegex(ValueError, 'numerical failure'): self.call(root, args)
            manifest = p.original.read_json(root / 'output.csv.manifest.json')
            self.assertFalse(manifest['completed']); self.assertEqual(manifest['rows_written'], 256)
            self.assertEqual(manifest['status'], 'failed_replay')
            self.assertEqual(len(pd.read_csv(root / 'output.csv')), 256)
            with self.assertRaises(FileExistsError): self.call(root, args)

    def test_fresh_isolated_cli_import_works_without_pythonpath_or_working_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, '-I', '-B', str(Path(p.__file__).resolve()), '--help'],
                                    cwd=temp, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--research-preview', result.stdout)


if __name__ == '__main__': unittest.main()
