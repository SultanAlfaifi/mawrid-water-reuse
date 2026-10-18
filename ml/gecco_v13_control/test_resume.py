"""Synthetic only: temp artifact trees and fake child, never source/model fit."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v13_control import resume as c
from ml.gecco_v7.recalibrate_delayed import assess, summarize


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.out = self.root/'output/run'; self.out.mkdir(parents=True)
        (self.root/'frozen.py').write_text('# synthetic frozen code, never executed\n')
        (self.root/'sealed.csv').write_bytes(b'synthetic opaque byte stream; do not parse\n')
        (self.out/'source').mkdir(); (self.out/'source/frozen.py').write_bytes((self.root/'frozen.py').read_bytes())
        self.plan = {'attempt': c.ATTEMPT, 'scope': 'all', 'limit_cases': 19, 'expected_cases': 19,
            'case_order': c.EXPECTED_NAMES, 'development_only': True, 'fresh_validation': False,
            'resource_execution': {'minimum_free_disk_bytes': c.MIN_FREE_BYTES},
            'environment': c.environment(), 'code_sha256': {'frozen.py': c.sha(self.root/'frozen.py')},
            'input_sha256': {'sealed.csv': c.sha(self.root/'sealed.csv')}}
        (self.out/'plan.json').write_text(json.dumps(self.plan))
        self.plan_sha = c.sha(self.out/'plan.json')
        self.starts = {}; starts = {}
        for i, name in enumerate(c.EXPECTED_NAMES):
            source = '2017' if i < 6 else '2018' if i < 12 else '2019' if i == 12 else 'WaterHub'
            self.starts[name] = (source, starts.get(source, 0)); starts[source] = starts.get(source, 0)+6
        for name in c.EXPECTED_NAMES[:12]: self.make_case(name)
        self.calls = []

    def tearDown(self): self.temp.cleanup()

    def make_case(self, name):
        folder = self.out/name; folder.mkdir()
        source, start = self.starts[name]
        frame = pd.DataFrame({'sample_index': np.arange(start, start+6),
            'label': [0, 1, 1, 0, 0, 0], 'baseline': [0, 1, 0, 0, 0, 0],
            'reference': [0, 1, 0, 0, 0, 0], 'candidate': [0, 1, 0, 0, 0, 0]})
        frame.to_csv(folder/'predictions.csv.gz', index=False)
        (folder/'bundle.joblib').write_bytes(b'SYNTHETIC ONLY, NEVER UNPICKLED')
        (folder/'freeze.json').write_text(json.dumps({'plan_sha256': self.plan_sha,
            'bundle_sha256': c.sha(folder/'bundle.joblib'), 'train': [0, 1], 'test': [start, start+6]}))
        (folder/'model_inspection.json').write_text('{"synthetic":true}')
        for file in ('calibration_scores.csv.gz', 'calibration_trials.csv.gz'):
            (folder/file).write_bytes(b'SYNTHETIC OPAQUE ARTIFACT, NOT PARSED')
        result = {'case': name, 'source': source, 'development_only': True,
            'comparisons': assess(*(frame[k].to_numpy(np.int8) for k in ('label', 'baseline', 'reference', 'candidate')))}
        (folder/'results.json').write_text(json.dumps(result, allow_nan=False))

    def prepared(self):
        return c.prepare(self.out, root=self.root)

    def child(self, name, out, root, log):
        self.assertEqual(out, self.out); self.assertEqual(root, self.root)
        self.calls.append(name); self.make_case(name); log.write('synthetic child completed '+name+'\n')
        return 0

    @contextmanager
    def execution(self, *, child=None, free=None):
        with patch.object(c, '_run_child', side_effect=child or self.child), \
             patch.object(c, '_load_production', return_value=SimpleNamespace(assess=assess, summarize=summarize)), \
             patch.object(c.shutil, 'disk_usage', return_value=SimpleNamespace(free=2*c.MIN_FREE_BYTES) if free is None else free):
            yield

    def test_prepare_metadata_only_and_immutable_checkpoint(self):
        with patch.object(pd, 'read_csv', side_effect=AssertionError('No source or score parsing in prepare')), \
             patch.object(c, '_run_child', side_effect=AssertionError('No child during prepare')), \
             patch.object(c, '_load_production', side_effect=AssertionError('No production import during prepare')):
            result = self.prepared()
        self.assertEqual(result['completed_cases'], 12)
        self.assertEqual(result['missing_cases'], c.EXPECTED_NAMES[12:])
        checkpoint = c.read(result['checkpoint'])
        self.assertEqual(checkpoint['controller_sha256'], c.controller_hashes())
        self.assertEqual(len(checkpoint['initial_completed_cases']), 12)
        self.assertTrue(all(set(v) == set(c.ARTIFACTS) for v in checkpoint['initial_completed_cases'].values()))
        with self.assertRaisesRegex(c.ResumeError, 'immutable'): self.prepared()

    def test_resumes_only_missing7_preserves12_and_exact_frozen_aggregation_schema(self):
        prepared = self.prepared(); before = c.inventory(self.out, self.plan_sha)
        original_log = self.root/'original.log'; original_log.write_text('original operational failure preserved')
        with self.execution(): result = c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, c.EXPECTED_NAMES[12:])
        self.assertEqual(result['complete_cases'], 19)
        for name, files in before.items():
            self.assertEqual({f: c.sha(self.out/name/f) for f in c.ARTIFACTS}, files)
        data = c.read(self.out/'results.json')
        self.assertEqual([p['case'] for p in data['periods']], c.EXPECTED_NAMES)
        self.assertEqual(set(data['sources']), {'2017', '2018', '2019', 'WaterHub'})
        self.assertEqual(data['summary'], summarize(data['periods'], data['sources']))
        self.assertEqual(data['candidate_version'], 'V13'); self.assertFalse(data['fresh_validation'])
        self.assertTrue(data['acceptance_evaluation_pending_independent_audit_and_historical_comparison'])
        self.assertEqual(len(data['execution_resume']['resumed_case_receipt_sha256']), 7)
        self.assertEqual(original_log.read_text(), 'original operational failure preserved')
        self.assertEqual(set(data), {'completed_at_utc', 'development_only', 'fresh_validation', 'candidate_version',
            'complete_cases', 'expected_cases', 'all_prespecified_cases_complete', 'maximum_allowed_extra_delay_seconds',
            'historical_retention_required', 'v8_user_objective_required', 'acceptance_evaluation_pending_independent_audit_and_historical_comparison',
            'periods', 'sources', 'summary', 'execution_resume'})
        with self.execution():
            with self.assertRaisesRegex(c.ResumeError, 'Top-level results'): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)

    def test_modified_plan_artifact_dependency_or_snapshot_rejected_without_child(self):
        prepared = self.prepared()
        targets = [(self.out/'plan.json', 'plan SHA'),
            (self.out/c.EXPECTED_NAMES[0]/'predictions.csv.gz', 'artifact changed'),
            (self.root/'frozen.py', 'dependency changed'), (self.root/'sealed.csv', 'dependency changed'),
            (self.out/'source/frozen.py', 'snapshot changed')]
        for path, reason in targets:
            with self.subTest(path=path):
                old = path.read_bytes(); path.write_bytes(old+b' ')
                try:
                    with self.execution():
                        with self.assertRaisesRegex(c.ResumeError, reason): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
                finally: path.write_bytes(old)
        self.assertEqual(self.calls, []); self.assertFalse((self.out/'results.json').exists())

    def test_partial_unknown_and_unreceipted_complete_case_are_not_rerun(self):
        prepared = self.prepared()
        (self.out/'unknown_case').mkdir()
        with self.execution():
            with self.assertRaisesRegex(c.ResumeError, 'Unknown run entry'): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        (self.out/'unknown_case').rmdir()
        partial = self.out/c.EXPECTED_NAMES[12]; partial.mkdir(); (partial/'bundle.joblib').write_bytes(b'partial')
        with self.execution():
            with self.assertRaisesRegex(c.ResumeError, 'Partial'): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        (partial/'bundle.joblib').unlink(); partial.rmdir(); self.make_case(c.EXPECTED_NAMES[12])
        with self.execution():
            with self.assertRaisesRegex(c.ResumeError, 'Unreceipted'): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, [])

    def test_child_failure_leaves_no_top_completion_or_forged_receipt(self):
        prepared = self.prepared()
        def failed(name, out, root, log): self.calls.append(name); return 7
        with self.execution(child=failed):
            with self.assertRaisesRegex(c.ResumeError, 'exited7'): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, [c.EXPECTED_NAMES[12]])
        self.assertFalse((self.out/'results.json').exists())
        self.assertEqual(list((self.out/'execution_resume').glob('case_*.json')), [])

    def test_original_low_disk_guard_stops_before_child_and_allows_later_resource_resume(self):
        prepared = self.prepared()
        with self.execution(free=SimpleNamespace(free=c.MIN_FREE_BYTES-1)):
            with self.assertRaises(c.ResourcePause): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, []); self.assertFalse((self.out/'results.json').exists())
        with self.execution(): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, c.EXPECTED_NAMES[12:])
        self.assertEqual(len(list((self.out/'execution_resume').glob('resume_*.log'))), 2)

    def test_receipt_preserves_newly_completed_case_across_another_resource_pause(self):
        prepared = self.prepared()
        with self.execution(), patch.object(c, 'check_space', side_effect=[2*c.MIN_FREE_BYTES, c.ResourcePause('synthetic pause')]):
            with self.assertRaises(c.ResourcePause): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, c.EXPECTED_NAMES[12:13])
        receipt = self.out/'execution_resume'/f'case_13_{c.EXPECTED_NAMES[12]}.json'
        digest = c.sha(receipt)
        self.assertFalse((self.out/'results.json').exists())
        with self.execution(): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, c.EXPECTED_NAMES[12:])
        self.assertEqual(c.sha(receipt), digest)

    def test_wrong_checkpoint_digest_controller_or_environment_rejected(self):
        prepared = self.prepared()
        with self.execution():
            with self.assertRaisesRegex(c.ResumeError, 'externally pinned'): c.resume(self.out, '0'*64, root=self.root)
        with self.execution(), patch.object(c, 'controller_hashes', return_value={'changed': '0'*64}):
            with self.assertRaisesRegex(c.ResumeError, 'controller changed'): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        with self.execution(), patch.object(c, 'environment', return_value={'python': 'wrong'}):
            with self.assertRaisesRegex(c.ResumeError, 'versions changed'): c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, [])

    def test_controller_edit_during_resume_stops_before_child(self):
        prepared = self.prepared(); original = c.controller_hashes()
        with self.execution(), patch.object(c, 'controller_hashes', side_effect=[original, {'changed': '0'*64}]):
            with self.assertRaisesRegex(c.ResumeError, 'Controller changed during execution'):
                c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.out/'results.json').exists())

    def test_child_cannot_modify_old_artifact_or_receive_success_receipt(self):
        prepared = self.prepared()
        def corrupting_child(name, out, root, log):
            self.child(name, out, root, log)
            (out/c.EXPECTED_NAMES[0]/'model_inspection.json').write_text('{"changed":true}')
            return 0
        with self.execution(child=corrupting_child):
            with self.assertRaisesRegex(c.ResumeError, 'modified earlier committed artifacts'):
                c.resume(self.out, prepared['checkpoint_sha256'], root=self.root)
        self.assertEqual(self.calls, c.EXPECTED_NAMES[12:13])
        self.assertEqual(list((self.out/'execution_resume').glob('case_*.json')), [])
        self.assertFalse((self.out/'results.json').exists())

    def test_lock_rejects_second_controller_and_atomic_metadata_never_overwrites(self):
        with c.locked(self.out):
            with self.assertRaisesRegex(c.ResumeError, 'holds the run lock'):
                with c.locked(self.out): pass
        path = self.out/'execution_resume/new.json'; c.atomic_new_json(path, {'original': True})
        digest = c.sha(path)
        with self.assertRaises(c.ResumeError): c.atomic_new_json(path, {'replacement': True})
        self.assertEqual(c.sha(path), digest)

    def test_failed_case_marker_and_missing_case_order_refuse_prepare(self):
        (self.out/'failed_case.json').write_text('{}')
        with self.assertRaisesRegex(c.ResumeError, 'failed-case'): self.prepared()
        (self.out/'failed_case.json').unlink()
        self.plan['case_order'] = list(reversed(self.plan['case_order']))
        (self.out/'plan.json').write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(c.ResumeError, 'exact reviewed'): self.prepared()

    def test_production_child_command_thread_settings_and_fresh_interpreter(self):
        with tempfile.TemporaryFile(mode='w+') as log, \
             patch.dict(c.os.environ, {'OPENBLAS_NUM_THREADS': '8', 'OMP_NUM_THREADS': '7', 'MKL_NUM_THREADS': '3'}), \
             patch.object(c.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(c._run_child(c.EXPECTED_NAMES[12], self.out, self.root, log), 0)
        args, kwargs = run.call_args
        self.assertEqual(args[0], [c.sys.executable, '-B', '-m', 'ml.gecco_v13.development', '--output', str(self.out), '--case', c.EXPECTED_NAMES[12]])
        self.assertEqual(kwargs['env']['OPENBLAS_NUM_THREADS'], '1')
        self.assertEqual(kwargs['env']['OMP_NUM_THREADS'], '1')
        self.assertNotIn('MKL_NUM_THREADS', kwargs['env']); self.assertEqual(kwargs['cwd'], self.root)


if __name__ == '__main__': unittest.main()
