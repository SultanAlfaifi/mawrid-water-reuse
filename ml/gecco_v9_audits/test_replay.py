"""Independent V9 synthetic-only coefficient, feature and caller contract checks."""
import unittest
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import joblib
import numpy as np
import pandas as pd
from ml.gecco_v9_audits import replay as audit

class FakeTrainModel:
    def __init__(self, channels): self.channels = channels
    def fit(self, frame, labels):
        self.fit_rows = len(frame); self.fit_labels = labels.copy(); self.fit_status_ = 'synthetic'
        return self
    def inspection(self): return {'fit_rows': self.fit_rows}
    def conditional_observed(self, frame): return np.isfinite(frame[self.channels[0]].to_numpy())
    def score_components(self, frame): return {'long_context': frame[self.channels[0]].to_numpy(float)}


class RunnerContractTests(unittest.TestCase):
    def test_runner_fits_only_train_and_freezes_before_loading_test_values(self):
        from ml.gecco_v9 import development as runner
        from ml.gecco_v7.calibration_delayed import _choice
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); out = root / 'output'; out.mkdir(); prior = root / 'prior'; prior.mkdir()
            (out / 'plan.json').write_text('{}')
            starts = [200, 330, 460, 590]; test_start = 720; test_end = 920
            train = pd.DataFrame({'a': np.arange(200) / 200, 'EVENT': 0})
            cals = [pd.DataFrame({'a': np.arange(130) / 130, 'EVENT': 0}) for _ in range(4)]
            reference = {'max_fit_index': 199, 'max_calibration_index': 719, 'selected': {}}
            joblib.dump(reference, prior / 'bundle.joblib')
            frozen = {'train': [0, 200], 'calibration_starts': starts, 'test': [test_start, test_end],
                      'bundle_sha256': runner.sha(prior / 'bundle.joblib')}
            (prior / 'freeze.json').write_text(json.dumps(frozen))
            pd.DataFrame({'sample_index': np.arange(200, 720), 'EVENT': 0, 'baseline': 0,
                          'guarded': 0, 'level': .1, 'jump': .2, 'sustained': .3}).to_csv(prior / 'calibration_scores.csv.gz', index=False)
            pd.DataFrame({'sample_index': np.arange(720, 920), 'EVENT': 0, 'baseline': 0,
                          'candidate': 0, 'level': .1, 'jump': .2, 'sustained': .3}).to_csv(prior / 'predictions.csv.gz', index=False)
            chosen = _choice(); calls = []
            def load_test():
                artifact = json.loads((out / 'synthetic' / 'freeze.json').read_text())
                self.assertEqual(artifact['selected'], chosen)
                self.assertEqual(artifact['bundle_sha256'], runner.sha(out / 'synthetic' / 'bundle.joblib'))
                self.assertEqual(artifact['plan_sha256'], runner.sha(out / 'plan.json'))
                calls.append('test_loaded_after_freeze')
                return pd.DataFrame({'a': np.arange(200) / 200, 'EVENT': 0})
            case = {'name': 'synthetic', 'source': '2018', 'prior': prior, 'train': train,
                    'cal': cals, 'cal_starts': starts, 'test_start': test_start, 'test_end': test_end,
                    'target': 'EVENT', 'channels': ['a'], 'continuous_cal': False, 'load_test': load_test}
            def select(blocks, **kwargs):
                self.assertEqual([b['source_start'] for b in blocks], starts)
                self.assertTrue(all(np.isnan(b['long_scores'][:120]).all() for b in blocks))
                self.assertEqual(calls, [])
                return chosen, [{'feasible': True}]
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'verify'), \
                 patch.object(runner, 'ConditionalResidualHGBScorer', FakeTrainModel), \
                 patch.object(runner.prior, 'v6_predict', side_effect=lambda base, *args: base), \
                 patch.object(runner, 'calibrate', side_effect=select), redirect_stdout(StringIO()):
                result, rows = runner.run_case(case, out, {})
            saved = joblib.load(out / 'synthetic' / 'bundle.joblib')
            self.assertEqual(saved['version'], 'v9_conditional_hgb_temporally_certified_120s')
            self.assertEqual(saved['long_model'].fit_rows, 200)
            np.testing.assert_array_equal(saved['long_model'].fit_labels, train.EVENT)
            self.assertEqual(calls, ['test_loaded_after_freeze'])
            self.assertEqual(len(rows), 200)

    def test_runtime_preserves_certified_policy_and_strips_labels(self):
        from ml.gecco_v9 import runtime
        from ml.gecco_v7 import runtime_v2
        from ml.gecco_v7_audits.test_delayed_runner import make_bundle, fake_reference
        state = make_bundle(); state['version'] = 'v9_conditional_hgb_temporally_certified_120s'
        frame = pd.DataFrame({'p1': [.1, .1, .1, .9, .9], 'p2': [0, .8, .8, .8, 0], 'label': 0})
        original_choice = state['selected'].copy()
        with patch.object(runtime_v2, 'reference_predict', side_effect=fake_reference):
            result = runtime.predict_frame(state, frame)
            altered = runtime.predict_frame(state, frame.assign(label=1))
            for stop in range(6):
                pd.testing.assert_frame_equal(runtime.predict_frame(state, frame.iloc[:stop]), result.iloc[:stop])
        pd.testing.assert_frame_equal(result, altered)
        self.assertEqual(state['selected'], original_choice)
        np.testing.assert_array_equal(result.prediction >= 0, result.reference_prediction >= 0)


def fixture():
    rng = np.random.default_rng(9821)
    values = rng.normal(size=(600, 4))
    values[:, 1] = .8 * values[:, 0] + .3 * values[:, 2] + .1 * values[:, 1]
    frame = pd.DataFrame(values, columns=['a', 'b', 'c', 'd'])
    labels = np.zeros(600, np.int8)
    labels[170:190] = 1; labels[220:240] = -1; labels[420:430] = 1
    frame.loc[310:312, 'd'] = np.nan
    return frame, labels


def synthetic_fit(frame, labels):
    from ml.gecco_v8 import onset
    from ml.gecco_v9.conditional import ConditionalResidualHGBScorer
    class Spy:
        def __init__(self, **kwargs): self.params = kwargs
        def fit(self, x, y, sample_weight):
            self.target = y.copy(); self.weights = sample_weight.copy(); return self
    with patch.object(onset, 'HistGradientBoostingClassifier', Spy):
        return ConditionalResidualHGBScorer(list(frame.columns)).fit(frame, labels)


class ConditionalOracleTests(unittest.TestCase):
    def test_oracle_rejects_any_nonfinite_normal_residual_even_if_quantile_is_finite(self):
        values = np.ones((130, 2)); values[-1, 0] = 1e308
        labels = np.zeros(130, np.int8)
        references = {'normal_median_': np.zeros(2), 'level_scale_': np.ones(2),
                      'noise_floor_': np.ones(2), 'reference_supported_': np.ones(2, bool)}
        with patch.object(np.linalg, 'lstsq', return_value=(np.array([10.]), None, None, None)), np.errstate(over='ignore', invalid='ignore'):
            result = audit.conditional_oracle(values, labels, references)
        self.assertFalse(result['supported'])
        self.assertEqual(result['status'], 'numerical_fit_failure')

    def test_float32_rounding_allowance_is_bounded_and_masks_are_exact(self):
        expected = np.array([[.2, .2, 1]], dtype=np.float32)
        actual = expected.copy(); actual[0, 0] = np.nextafter(actual[0, 0], np.float32(1))
        checks = audit.Checks()
        self.assertTrue(audit.check_added_features(checks, 'one_ulp', actual, expected))
        actual[0, 0] = np.nextafter(actual[0, 0], np.float32(1))
        self.assertFalse(audit.check_added_features(checks, 'two_ulps', actual, expected))
        actual = expected.copy(); actual[0, 2] = np.nextafter(np.float32(1), np.float32(0))
        self.assertFalse(audit.check_added_features(checks, 'mask', actual, expected))

    def test_constant_and_exactly_collinear_normal_channels_are_ridge_regularized(self):
        a = np.linspace(-1, 1, 300)
        frame = pd.DataFrame({'a': a, 'b': 2*a+1, 'c': np.ones(300)})
        labels = np.zeros(300, np.int8)
        model = synthetic_fit(frame, labels)
        checks = audit.Checks(); oracle = audit.audit_conditional_training(checks, 'collinear', model, frame, labels)
        self.assertTrue(oracle['supported'])
        self.assertTrue(all(r['passed'] for r in checks.records), checks.records)
        self.assertTrue(np.isfinite(model.conditional_features(frame)).all())

    def test_single_predictor_matches_closed_form_scalar_ridge(self):
        a = np.linspace(-2, 2, 200)
        values = np.column_stack([a, 3 * a + .2 * np.sin(np.arange(200))])
        labels = np.zeros(200, np.int8)
        result = audit.conditional_oracle(values, labels)
        self.assertTrue(result['supported'])
        refs = result['references']; z = (values - refs['normal_median_']) / refs['level_scale_']
        for target in (0, 1):
            x, y = z[:, 1-target], z[:, target]
            xx, yy = x-x.mean(), y-y.mean()
            coefficient = sum(float(xi) * float(yi) for xi, yi in zip(xx, yy)) / (sum(float(xi)**2 for xi in xx) + 1)
            self.assertAlmostEqual(result['coef'][target, 0], coefficient, places=12)
            self.assertAlmostEqual(result['intercept'][target], y.mean()-coefficient*x.mean(), places=12)

    def test_actual_synthetic_scorer_matches_independent_references_weights_ridge_and_features(self):
        frame, labels = fixture(); model = synthetic_fit(frame, labels)
        checks = audit.Checks()
        weights = audit.audit_training(checks, 'synthetic', model, frame, labels)
        oracle = audit.audit_conditional_training(checks, 'synthetic', model, frame, labels)
        audit.audit_conditional_frame(checks, 'synthetic', model, frame, oracle)
        self.assertTrue(all(row['passed'] for row in checks.records), [r for r in checks.records if not r['passed']])
        np.testing.assert_array_equal(model.model_.target, labels[weights['eligible']])
        np.testing.assert_array_equal(model.model_.weights, weights['sample'][weights['eligible']])
        self.assertFalse(model.conditional_fit_mask_[labels != 0].any())

    def test_mutating_unknown_positive_training_values_does_not_fit_conditional_reference(self):
        frame, labels = fixture(); first = synthetic_fit(frame, labels)
        changed = frame.copy(); changed.loc[labels != 0] = 1e6
        second = synthetic_fit(changed, labels)
        for name in ('normal_median_', 'level_scale_', 'conditional_coef_', 'conditional_intercept_',
                     'conditional_residual_scale_', 'conditional_fit_mask_'):
            np.testing.assert_allclose(getattr(first, name), getattr(second, name), rtol=0, atol=1e-12)

    def test_missing_predictor_disables_added_row_but_preserves_v8_availability(self):
        from ml.gecco_v7.long_context import LongContextEventScorer
        from copy import copy
        frame, labels = fixture(); model = synthetic_fit(frame, labels)
        query = frame.iloc[:150].copy(); query.iloc[100, 3] = np.nan
        block = model.conditional_features(query)
        self.assertEqual(block[100].sum(), 0)
        full, available = model.features(query)
        view = copy(model); view.feature_names_ = model.original_feature_names_
        old, original_available = LongContextEventScorer.features(view, query)
        self.assertTrue(available[100])
        np.testing.assert_array_equal(available, original_available)
        np.testing.assert_array_equal(full[:, :len(model.original_feature_names_)], old)

    def test_prefix_future_and_label_mutations_leave_features_unchanged(self):
        frame, labels = fixture(); model = synthetic_fit(frame, labels)
        query = frame.iloc[:240].copy(); full, avail = model.features(query)
        for stop in (0, 1, 59, 60, 61, 123, 240):
            prefix, seen = model.features(query.iloc[:stop])
            np.testing.assert_allclose(prefix, full[:stop], rtol=0, atol=1e-12)
            np.testing.assert_array_equal(seen, avail[:stop])
        changed = query.copy(); changed.iloc[123:] = -1e8
        altered, _ = model.features(changed)
        np.testing.assert_allclose(altered[:123], full[:123], rtol=0, atol=1e-12)
        changed = query.assign(label=1, EVENT=-1)
        np.testing.assert_array_equal(model.features(changed)[0], full)

    def test_insufficient_channels_and_normal_complete_populations_are_explicit(self):
        frame, labels = fixture()
        model = synthetic_fit(frame[['a']], labels)
        self.assertEqual(model.conditional_fit_status_, 'insufficient_channels')
        self.assertFalse(model.conditional_fit_mask_.any())
        self.assertFalse(model.conditional_features(frame).any())
        checks = audit.Checks(); audit.audit_conditional_training(checks, 'one', model, frame[['a']], labels)
        self.assertTrue(all(r['passed'] for r in checks.records), checks.records)
        # Every original channel has enough normal values; no complete joint row.
        x = np.ones((600, 4)); y = np.zeros(600, np.int8)
        for i in range(600): x[i, i % 4] = np.nan
        missing = pd.DataFrame(x, columns=list('abcd'))
        model = synthetic_fit(missing, y)
        self.assertEqual(model.conditional_fit_status_, 'insufficient_complete_normal_rows')
        checks = audit.Checks(); audit.audit_conditional_training(checks, 'none', model, missing, y)
        self.assertTrue(all(r['passed'] for r in checks.records), checks.records)

    def test_numeric_failure_and_nonfinite_inference_fail_closed_added_block_only(self):
        from ml.gecco_v9 import conditional
        frame, labels = fixture()
        with patch.object(conditional.Ridge, 'fit', side_effect=np.linalg.LinAlgError('synthetic')):
            model = synthetic_fit(frame, labels)
        self.assertEqual(model.conditional_fit_status_, 'numerical_fit_failure')
        self.assertGreater(model.conditional_fit_mask_.sum(), 128)
        self.assertFalse(model.conditional_features(frame).any())
        model = synthetic_fit(frame, labels)
        query = frame.iloc[:4].copy(); query.iloc[1, 0] = np.finfo(float).max
        block = model.conditional_features(query)
        self.assertTrue(np.isfinite(block).all())
        self.assertFalse(block[1].any())

    def test_corrupt_fitted_coefficient_is_detected_without_refitting_classifier(self):
        frame, labels = fixture(); model = synthetic_fit(frame, labels)
        model.conditional_coef_[0, 0] += .05
        checks = audit.Checks(); audit.audit_conditional_training(checks, 'tampered', model, frame, labels)
        self.assertTrue(any(not r['passed'] for r in checks.records))


class CompletedAuditContractTests(unittest.TestCase):
    def test_incomplete_run_cannot_open_sources_or_write_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plan.json').write_text(json.dumps({'attempt': audit.ATTEMPT, 'scope': 'all', 'limit_cases': 19}))
            (root / 'results.json').write_text(json.dumps({'complete_cases': 1, 'expected_cases': 19}))
            with patch.object(audit, '_source_frames', side_effect=AssertionError('No source access')):
                with self.assertRaises(ValueError): audit.audit_directory(root, workspace_root=root)
            self.assertFalse((root / 'audit.json').exists())


if __name__ == '__main__': unittest.main()

