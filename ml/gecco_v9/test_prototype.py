"""Prototype gates and label isolation using synthetic files/stubs only."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v9 import prototype as proto


def fixture(root, *, accepted=False):
    run = root / 'run'; run.mkdir()
    case = proto.CASES[-1]; folder = run / case; folder.mkdir()
    code = {}
    for name in ('ml/gecco_v9/conditional.py', 'ml/gecco_v9/development.py', 'ml/gecco_v9/runtime.py',
                 'ml/gecco_v8/onset.py', 'ml/gecco_v7/calibration_certified.py', 'ml/gecco_v7/runtime_delayed.py'):
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# synthetic fixture\n')
        frozen = run / 'source' / name; frozen.parent.mkdir(parents=True, exist_ok=True); frozen.write_bytes(path.read_bytes())
        code[name] = proto.sha(path)
    auditor = root / 'ml/gecco_v9_audits/replay.py'; auditor.parent.mkdir(parents=True); auditor.write_text('# synthetic auditor\n')
    plan = {'attempt': proto.ATTEMPT, 'scope': 'all', 'limit_cases': 19, 'fresh_validation': False, 'code_sha256': code}
    (run / 'plan.json').write_text(json.dumps(plan))
    choice = {'decision': 'reference'}
    periods = [{'case': name, 'selected': choice} for name in proto.CASES]
    result = {'complete_cases': 19, 'expected_cases': 19, 'all_prespecified_cases_complete': True,
              'completed_at_utc': 'synthetic', 'fresh_validation': False, 'periods': periods,
              'summary': {k: {'passes_declared_development_gate': accepted} for k in ('if_vs_v7', 'v6_vs_v7')}}
    (run / 'results.json').write_text(json.dumps(result))
    (folder / 'results.json').write_text(json.dumps(periods[-1]))
    (folder / 'bundle.joblib').write_bytes(b'Synthetic metadata only; never unpickle this fixture')
    frozen = {'plan_sha256': proto.sha(run / 'plan.json'), 'bundle_sha256': proto.sha(folder / 'bundle.joblib'),
              'selected': choice, 'train': [0, 200], 'test': [720, 920]}
    (folder / 'freeze.json').write_text(json.dumps(frozen))
    hashes = {name: proto.sha(run / name) for name in ('plan.json', 'results.json')}
    hashes.update({case + '/' + name: proto.sha(folder / name) for name in ('bundle.joblib', 'freeze.json', 'results.json')})
    audit = {'passed': True, 'failed_checks': 0, 'complete_replayed_cases': 19, 'replayed_rows': 449431,
             'attempt': proto.ATTEMPT, 'fresh_validation': False, 'audit_script_sha256': proto.sha(auditor),
             'hashes': hashes, 'recomputed_development_gates': {k: accepted for k in ('if_vs_v7', 'v6_vs_v7')}}
    (run / 'audit.json').write_text(json.dumps(audit))
    return run, case


def fake_bundle():
    return {'version': proto.VERSION, 'long_model': SimpleNamespace(channels=['p1', 'p2']),
            'reference_bundle': {'local_model': SimpleNamespace(channels=['p1', 'p2'])},
            'sample_seconds': 60, 'gap_samples': 120, 'max_fit_index': 199, 'max_calibration_index': 719,
            'selected': {'decision': 'reference'}}


class PrototypeTests(unittest.TestCase):
    def test_fresh_isolated_process_resolves_actual_legacy_pickle_class_names(self):
        # Real project class identity, synthetic unfit object, no source or model
        # artifact access. -I ignores PYTHONPATH/current-directory imports.
        with tempfile.TemporaryDirectory() as temp:
            root = str(proto.ROOT); folder = str(Path(temp))
            producer = '''
import sys
from pathlib import Path
from types import SimpleNamespace
root=Path(sys.argv[1]); folder=Path(sys.argv[2])
for relative in ('.','ml/gecco_v6','ml/gecco_v5','ml/gecco_v2','ml/gecco_baseline'):
    sys.path.insert(0,str(root/relative))
import joblib
from supported_candidate import SupportedRecoveryDetector
bundle={'version':'v9_conditional_hgb_temporally_certified_120s',
 'long_model':SimpleNamespace(channels=['p1','p2']),
 'reference_bundle':{'local_model':SimpleNamespace(channels=['p1','p2']),
                     'prior_bundle':{'model':SupportedRecoveryDetector(channels=['p1','p2'])}},
 'sample_seconds':60,'gap_samples':120,'max_fit_index':199,
 'max_calibration_index':719,'selected':{'decision':'reference'}}
joblib.dump(bundle,folder/'bundle.joblib')
'''
            consumer = '''
import sys,importlib.util
from pathlib import Path
root=Path(sys.argv[1]); folder=Path(sys.argv[2]); sys.path.insert(0,str(root))
from ml.gecco_v9 import prototype
assert importlib.util.find_spec('supported_candidate') is None
gate={'root':root,'folder':folder,'freeze':{'selected':{'decision':'reference'},
       'train':[0,200],'test':[720,920]}}
bundle,channels=prototype._load_bundle(gate)
assert channels==['p1','p2']
model=bundle['reference_bundle']['prior_bundle']['model']
assert type(model).__module__=='supported_candidate'
assert type(model).__name__=='SupportedRecoveryDetector'
assert not hasattr(model,'baseline_')
print('fresh isolated legacy unpickle passed')
'''
            for script in (producer, consumer):
                completed = subprocess.run([sys.executable, '-I', '-B', '-c', script, root, folder],
                    cwd=temp, capture_output=True, text=True, timeout=60)
                self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('fresh isolated legacy unpickle passed', completed.stdout)

    def test_stream_failure_retains_committed_chunk_with_labels_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run, case = fixture(root)
            source = root / 'in.csv'
            pd.DataFrame({'timestamp': pd.date_range('2022-01-01', periods=300, freq='min'),
                          'p1': 1., 'EVENT': 'ignored', 'p2': 2.}).to_csv(source, index=False)
            stream_path = root / 'ml/gecco_v9/streaming.py'; stream_path.write_text('# synthetic stream\n')
            owner = self
            class Engine:
                def __init__(self, bundle): self.calls = 0
                def update_frame(self, sensors):
                    owner.assertEqual(list(sensors), ['p1', 'p2'])
                    self.calls += 1
                    if self.calls > 1: raise ValueError('synthetic second-chunk failure')
                    return pd.DataFrame({'prediction': 0, 'long_context': .2,
                                         'reference_prediction': 0, 'available': True}, index=sensors.index)
            module = SimpleNamespace(__file__=str(stream_path), StreamingPredictor=Engine)
            output = root / 'out.csv'
            with patch.object(proto, '_load_bundle', return_value=(fake_bundle(), ['p1', 'p2'])), \
                 patch.object(proto, '_import_runtime', return_value=module), \
                 patch.object(proto, 'verify_stream_audit', return_value={'sha256': 'synthetic_gate_tested_separately'}):
                with self.assertRaisesRegex(ValueError, 'second-chunk'):
                    proto.run_replay(run, case, source, output, research_preview=True, workspace_root=root)
            manifest = proto.read_json(output.with_suffix('.csv.manifest.json'))
            self.assertEqual(manifest['rows_written'], 256); self.assertFalse(manifest['completed'])
            self.assertEqual(len(pd.read_csv(output)), 256)

    def test_streaming_requires_real_bundle_specific_prefix_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run, case = fixture(root)
            gate = proto.verify_run(run, case, research_preview=True, workspace_root=root)
            with self.assertRaises(FileNotFoundError): proto.verify_stream_audit(gate, case)
            paths = ['ml/gecco_v9/runtime.py', 'ml/gecco_v7/runtime_delayed.py', 'ml/gecco_v7/runtime_v2.py', 'ml/gecco_v6/runtime_v4.py']
            for name in paths + ['ml/gecco_v9/streaming.py']:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists(): path.write_text('# synthetic stream evidence fixture\n')
            evidence = {'schema_version': 1, 'passed': True,
                        'streaming_sha256': proto.sha(root / 'ml/gecco_v9/streaming.py'),
                        'batch_audit_sha256': gate['verified_hashes']['audit.json'],
                        'runtime_code_sha256': {name: proto.sha(root / name) for name in paths},
                        'verified_bundle_sha256': {case: gate['verified_hashes'][case + '/bundle.joblib']},
                        'cases': [{'case_id': case, 'tested_sample_bounds': [0, 1600], 'full_period_tested': False,
                                   'exact_prediction_masks': True, 'score_tolerance': 1e-12}], 'limitations': ['Synthetic metadata test only']}
            path = run / 'streaming_audit.json'; path.write_text(json.dumps(evidence))
            verified = proto.verify_stream_audit(gate, case)
            self.assertFalse(verified['case']['full_period_tested'])
            evidence['verified_bundle_sha256'][case] = 'wrong'; path.write_text(json.dumps(evidence))
            with self.assertRaisesRegex(ValueError, 'actual fitted bundle'): proto.verify_stream_audit(gate, case)

    def test_failed_performance_requires_explicit_research_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run, case = fixture(root)
            with self.assertRaisesRegex(ValueError, 'research-preview'): proto.verify_run(run, case, workspace_root=root)
            gate = proto.verify_run(run, case, workspace_root=root, research_preview=True)
            self.assertEqual(gate['status'], 'research_only'); self.assertFalse(gate['development_acceptance_passed'])

    def test_incomplete_or_failed_audit_blocks_before_bundle_or_sensor_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run, case = fixture(root)
            audit = proto.read_json(run / 'audit.json'); audit['passed'] = False
            (run / 'audit.json').write_text(json.dumps(audit))
            source = root / 'in.csv'; source.write_text('timestamp,p1,p2\nDO NOT PARSE SENSOR ROWS')
            out = root / 'out.csv'
            with patch.object(proto, '_load_bundle', side_effect=AssertionError('bundle must remain closed')), \
                 patch.object(proto, '_sensor_frames', side_effect=AssertionError('rows must remain closed')):
                with self.assertRaisesRegex(ValueError, 'PASS audit'):
                    proto.run_replay(run, case, source, out, research_preview=True, workspace_root=root)
            manifest = proto.read_json(out.with_suffix('.csv.manifest.json'))
            self.assertFalse(manifest['completed']); self.assertTrue(manifest['partial_output_retained'])

    def test_production_freeze_bundle_result_and_auditor_hash_mutations_rejected(self):
        targets = ['ml/gecco_v9/runtime.py', 'ml/gecco_v9_audits/replay.py',
                   'run/2019-04/bundle.joblib', 'run/2019-04/freeze.json', 'run/results.json']
        for target in targets:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); run, case = fixture(root); path = root / target
                path.write_bytes(path.read_bytes() + b' ')
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    proto.verify_run(run, case, workspace_root=root, research_preview=True)

    def test_batch_csv_projects_ordered_sensors_only_and_records_honest_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run, case = fixture(root)
            source = root / 'in.csv'; source.write_text('timestamp,p2,EVENT,p1\n2022-01-01T00:00:00,2,SECRET,1\n2022-01-01T00:01:00,4,NOT_NUMERIC,3\n')
            calls = []
            def predict(bundle, sensors):
                calls.append(sensors.copy())
                self.assertEqual(list(sensors.columns), ['p1', 'p2'])
                return pd.DataFrame({'prediction': [-1, 1], 'long_context': [np.nan, .8],
                                     'reference_prediction': [-1, 0], 'available': [False, True]}, index=sensors.index)
            module = SimpleNamespace(__file__=str(root / 'ml/gecco_v9/runtime.py'), predict_frame=predict)
            with patch.object(proto, '_load_bundle', return_value=(fake_bundle(), ['p1', 'p2'])), \
                 patch.object(proto, '_import_runtime', return_value=module):
                manifest = proto.run_replay(run, case, source, root / 'out.csv', mode='batch', research_preview=True, workspace_root=root)
            self.assertEqual(len(calls), 1); self.assertTrue(manifest['completed'])
            self.assertEqual(manifest['status'], 'research_only'); self.assertFalse(manifest['water_safety_probability'])
            result = pd.read_csv(root / 'out.csv')
            self.assertEqual(list(result.columns), ['timestamp', 'prediction', 'model_score', 'reference_prediction', 'available'])
            self.assertEqual(result.prediction.tolist(), [-1, 1]); self.assertNotIn('EVENT', result)
            self.assertEqual(manifest['input_sha256'], proto.sha(source))

    def test_no_input_existing_output_or_manifest_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'in.csv'; source.write_text('preserve')
            with self.assertRaises(ValueError): proto.run_replay('unused', 'unused', source, source)
            output = root / 'out.csv'; output.write_text('preserve-output')
            with self.assertRaises(FileExistsError): proto.run_replay('unused', 'unused', source, output)
            self.assertEqual(source.read_text(), 'preserve'); self.assertEqual(output.read_text(), 'preserve-output')

    def test_runtime_failure_keeps_csv_and_failure_manifest_without_fabricated_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run, case = fixture(root)
            source = root / 'in.csv'; source.write_text('timestamp,p1,p2\n2022-01-01T00:00:00,1,2\n')
            module = SimpleNamespace(__file__=str(root / 'ml/gecco_v9/runtime.py'),
                                     predict_frame=lambda *args: (_ for _ in ()).throw(ValueError('synthetic bad cadence')))
            output = root / 'out.csv'
            with patch.object(proto, '_load_bundle', return_value=(fake_bundle(), ['p1', 'p2'])), \
                 patch.object(proto, '_import_runtime', return_value=module):
                with self.assertRaisesRegex(ValueError, 'synthetic bad cadence'):
                    proto.run_replay(run, case, source, output, mode='batch', research_preview=True, workspace_root=root)
            manifest = proto.read_json(output.with_suffix('.csv.manifest.json'))
            self.assertFalse(manifest['completed']); self.assertEqual(manifest['rows_written'], 0)
            self.assertTrue(output.exists()); self.assertEqual(source.read_text().count('\n'), 2)


if __name__ == '__main__': unittest.main()
