"""Synthetic no-refit and freeze-before-outer boundary tests for V10."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from ml.gecco_v10 import development as d, runtime
from ml.gecco_v7 import development_v2, runtime_v2
from ml.gecco_v7.calibration_delayed import _choice
from ml.gecco_v7.evidence import separate_scores
from ml.gecco_v9.test_development import SensorOnlySpy, reference_fake


class NoFit:
    def fit(self, *args, **kwargs):
        raise AssertionError('V10 must never refit its frozen models')


class RunnerBoundaryTests(unittest.TestCase):
    def exercise(self, *, waterhub=False, change=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); parent = root/'parent'; source = parent/'synthetic'
            source.mkdir(parents=True); prior = root/'prior'; prior.mkdir()
            out = root/'out'; out.mkdir(); target = 'label' if waterhub else 'EVENT'
            starts = [200, 400, 600, 800]; end = 1000; test_end = 1190
            selected = {**_choice(.4, .7, '2of3', 2), 'pending_after_clear': False,
                        'status': 'synthetic_selection'}
            bundle = {'version': 'v9_conditional_hgb_temporally_certified_120s',
                      'long_model': NoFit(), 'reference_bundle': {'model': NoFit()},
                      'max_fit_index': 199, 'max_calibration_index': end-1,
                      'sample_seconds': 60, 'gap_samples': 120,
                      'selected': {**_choice(), 'status': 'reference'}}
            joblib.dump(bundle, source/'bundle.joblib')
            def frame(a, b):
                n = b-a; ix = np.arange(a, b)
                labels = np.where(ix % 29 < 7, 1, 0).astype(np.int8)
                ref = np.where(ix % 11 < 4, 1, 0).astype(np.int8)
                score = ix % 13/12
                components = {'level': np.full(n, .5), 'jump': np.where(ix % 7 < 3, 2., .5),
                              'sustained': np.full(n, .5)}
                masks = separate_scores(components, score)
                return pd.DataFrame({'sample_index': ix, 'label': labels,
                    'baseline': ref, 'reference': ref, 'candidate': ref,
                    'long_context': score, 'conditional_observed': True, **masks}), components
            cal, local = frame(starts[0], end); outer, _ = frame(end, test_end)
            cal.to_csv(source/'calibration_scores.csv.gz', index=False)
            outer.to_csv(source/'predictions.csv.gz', index=False)
            pd.DataFrame({'sample_index': cal.sample_index, target: cal.label, **local}).to_csv(
                prior/'calibration_scores.csv.gz', index=False)
            (prior/'bundle.joblib').write_bytes(b'not_loaded_frozen_prior')
            frozen = {'train': [0, 200], 'test': [end, test_end],
                'calibration_starts': starts, 'prior_folder': 'prior',
                'prior_sha256': {name: d.sha(prior/name) for name in
                                 ('bundle.joblib', 'calibration_scores.csv.gz')},
                'bundle_sha256': d.sha(source/'bundle.joblib'), 'continuous_cal': False}
            (source/'freeze.json').write_text(json.dumps(frozen))
            (source/'model_inspection.json').write_text('{"unchanged": true}')
            (source/'results.json').write_text('{"parent_only": true}')
            (root/'code.py').write_text('frozen code')
            plan = {'code_sha256': {'code.py': d.sha(root/'code.py')}, 'input_sha256': {}}
            (out/'plan.json').write_text(json.dumps(plan))
            item = {'case': 'synthetic', 'source': 'WaterHub' if waterhub else 'GECCO2017',
                'fit_status': 'fitted', 'conditional_block_test_coverage': {'diagnostic_only': True}}
            opened = []; calls = []
            parent_hashes = {p.name: d.sha(p) for p in source.iterdir()}
            def calibrate(blocks, *, cadence_seconds):
                self.assertEqual(cadence_seconds, 60); self.assertEqual(len(blocks), 4)
                self.assertFalse((out/'synthetic'/'freeze.json').exists())
                self.assertFalse(opened)
                for i, block in enumerate(blocks):
                    self.assertEqual(block['source_start'], starts[i])
                    np.testing.assert_array_equal(block['labels'], cal.label.iloc[i*200:(i+1)*200])
                calls.append(True)
                if change == 'code': (root/'code.py').write_text('changed after selection')
                return selected, [{**selected, 'feasible': True}]
            def load_outer(folder):
                self.assertEqual(folder, source); self.assertEqual(len(calls), 1)
                new = d.read(out/'synthetic'/'freeze.json')
                self.assertEqual(new['selected'], selected)
                self.assertEqual(new['plan_sha256'], d.sha(out/'plan.json'))
                self.assertEqual(new['bundle_sha256'], d.sha(out/'synthetic'/'bundle.joblib'))
                self.assertTrue(new['training_reused_without_refit'])
                saved = joblib.load(out/'synthetic'/'bundle.joblib')
                self.assertEqual(saved['version'], runtime.VERSION)
                self.assertEqual(saved['max_fit_index'], 199)
                self.assertEqual(saved['max_calibration_index'], end-1)
                self.assertEqual(saved['selected'], selected)
                opened.append(True)
                if change == 'parent': (source/'model_inspection.json').write_text('changed after freeze')
                return outer.copy()
            with patch.object(d, 'ROOT', root), patch.object(development_v2, 'ROOT', root), \
                 patch.object(d, 'calibrate', side_effect=calibrate), \
                 patch.object(d, 'load_outer', side_effect=load_outer):
                if change:
                    with self.assertRaises(RuntimeError if change == 'code' else AssertionError):
                        d.run_case(item, parent, out, plan)
                    self.assertEqual(bool(opened), change == 'parent')
                    return
                result, rows = d.run_case(item, parent, out, plan)
            self.assertTrue(opened); self.assertFalse(result['model_refitted'])
            self.assertEqual(parent_hashes, {p.name: d.sha(p) for p in source.iterdir()})
            np.testing.assert_array_equal(rows.v9_candidate, outer.candidate)
            np.testing.assert_array_equal(rows.candidate, d.predict(outer.reference.to_numpy(),
                outer.long_context.to_numpy(), selected, outer.rescue_long_context.to_numpy()))
            self.assertEqual(d.sha(source/'model_inspection.json'), d.sha(out/'synthetic'/'model_inspection.json'))
            saved_cal = pd.read_csv(out/'synthetic'/'calibration_scores.csv.gz')
            self.assertEqual(saved_cal.sample_index.tolist(), cal.sample_index.tolist())
            np.testing.assert_array_equal(saved_cal.v9_candidate, cal.candidate)

    def test_freeze_before_outer_and_no_refit_or_parent_mutation(self): self.exercise()
    def test_waterhub_label_schema(self): self.exercise(waterhub=True)
    def test_changed_code_stops_before_outer(self): self.exercise(change='code')
    def test_changed_parent_after_freeze_rejected(self): self.exercise(change='parent')

    def test_parent_requires_complete_exact_case_inventory_and_matching_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            for name in ('results.json', 'plan.json', 'audit.json'):
                (parent/name).write_text('{}')
            with self.assertRaises(ValueError): d.parent_metadata(parent)
            result = {'candidate_version': 'V9', 'complete_cases': 19, 'expected_cases': 19,
                      'all_prespecified_cases_complete': True,
                      'periods': [{'case': n} for n in d.EXPECTED_NAMES]}
            (parent/'results.json').write_text(json.dumps(result))
            with self.assertRaises(ValueError): d.parent_metadata(parent)


class RuntimeBoundaryTests(unittest.TestCase):
    def bundle(self):
        return {'version': runtime.VERSION, 'sample_seconds': 60, 'gap_samples': 120,
            'long_model': SensorOnlySpy(),
            'reference_bundle': {'local_model': SimpleNamespace(channels=['p1', 'p2'])},
            'selected': {**_choice(.4, .7, '2of3', 2), 'pending_after_clear': True}}

    def test_sensor_only_batch_matches_policy_and_ignores_labels(self):
        frame = pd.DataFrame({'p1': np.arange(300.), 'p2': 1., 'EVENT': 999, 'label': -1},
                             index=pd.date_range('2020-01-01', periods=300, freq='min'))
        bundle = self.bundle()
        with patch.object(runtime_v2, 'reference_predict', side_effect=reference_fake):
            a = runtime.predict_frame(bundle, frame)
            b = runtime.predict_frame(bundle, frame.assign(EVENT=-999, label=1))
        pd.testing.assert_frame_equal(a, b)
        expected = d.predict(a.reference_prediction.to_numpy(np.int8), a.long_context.to_numpy(),
                             bundle['selected'], a.rescue_long_context.to_numpy())
        np.testing.assert_array_equal(a.prediction, expected)
        np.testing.assert_array_equal(a.prediction >= 0, a.reference_prediction >= 0)

    def test_wrong_version_cadence_and_timestamp_axis_are_rejected(self):
        frame = pd.DataFrame({'p1': [1., 2., 3.], 'p2': 1.},
                             index=pd.date_range('2020-01-01', periods=3, freq='5min'))
        with self.assertRaises(ValueError): runtime.predict_frame({'version': 'wrong'}, frame)
        with self.assertRaises(ValueError): runtime.predict_frame(self.bundle(), frame)
        bundle = self.bundle(); bundle['sample_seconds'] = 300
        with self.assertRaises(ValueError): runtime.predict_frame(bundle, frame)


if __name__ == '__main__': unittest.main()
