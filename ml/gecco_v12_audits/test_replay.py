"""Synthetic-only V12 IF evidence and caller isolation audit checks."""
from copy import copy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from ml.gecco_v12_audits import replay as audit
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer
from ml.gecco_v9.conditional import ConditionalResidualHGBScorer
from ml.gecco_v2.candidates_supervised import build_features


class SpyClassifier:
    def __init__(self, **kwargs): self.parameters = kwargs
    def fit(self, x, y, sample_weight):
        self.fitted_shape = x.shape; self.weights = sample_weight.copy(); self.labels = y.copy()
        return self


def fixture(n=600):
    rng = np.random.default_rng(84591)
    x = rng.normal(size=(n, 4))
    x[:, 1] = x[:, 0] * .4 + x[:, 1] * .2
    frame = pd.DataFrame(x, columns=list('abcd'))
    labels = np.zeros(n, np.int8)
    labels[180:196] = 1; labels[230:240] = -1; labels[430:440] = 1
    frame.loc[300:302, 'd'] = np.nan
    return frame, labels


def make_estimator(frame, labels):
    x, eligible, _ = build_features(frame, 'baseline15', list(frame.columns))
    mask = audit.baseline_fit_mask_oracle(frame, labels, list(frame.columns))
    return IsolationForest(n_estimators=200, max_samples=256, contamination='auto',
        n_jobs=1, random_state=20261016).fit(x[mask])


def make_model(frame, labels, estimator):
    from ml.gecco_v8 import onset
    with patch.object(onset, 'HistGradientBoostingClassifier', SpyClassifier):
        return BaselineEvidenceHGBScorer(list(frame.columns), estimator).fit(frame, labels)


class EvidenceOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = fixture()
        cls.estimator = make_estimator(cls.frame, cls.labels)
        cls.model = make_model(cls.frame, cls.labels, cls.estimator)

    def assert_checks(self, checks):
        self.assertTrue(all(row['passed'] for row in checks.records),
                        [row for row in checks.records if not row['passed']])

    def test_independent_baseline_input_matrix_names_and_missing_mask(self):
        frame = self.frame.copy(); frame.loc[330, 'a'] = np.inf
        actual = audit.baseline_input_oracle(frame, list(frame.columns))
        expected = build_features(frame, 'baseline15', list(frame.columns))
        np.testing.assert_array_equal(actual[0], expected[0])
        np.testing.assert_array_equal(actual[1], expected[1])
        self.assertEqual(actual[2], expected[2])
        self.assertFalse(actual[1][330:345].any())
        self.assertTrue(actual[1][345])
        for n in (0, 1, 14, 15):
            a = audit.baseline_input_oracle(frame.iloc[:n], list(frame.columns))
            self.assertEqual(a[0].shape, (n, 16))
            self.assertEqual(a[1].sum(), int(n == 15))

    def test_normal_windows_exclude_unknown_positive_and_nonadjacent_rows(self):
        frame = pd.DataFrame({'a': np.arange(80, dtype=float)})
        labels = np.zeros(80, np.int8); labels[20] = -1; labels[45] = 1
        frame.loc[65, 'a'] = np.nan
        mask = audit.baseline_fit_mask_oracle(frame, labels, ['a'])
        expected = np.array([i >= 14 and np.all(labels[i-14:i+1] == 0)
            and np.isfinite(frame.a.iloc[max(0, i-14):i+1]).all() for i in range(80)])
        np.testing.assert_array_equal(mask, expected)
        self.assertFalse(mask[20:35].any()); self.assertTrue(mask[35])
        self.assertFalse(mask[45:60].any()); self.assertTrue(mask[60])

    def test_actual_synthetic_added_features_and_if_state_are_independently_verified(self):
        checks = audit.Checks()
        audit.audit_if_frame(checks, 'synthetic', self.model, self.frame)
        self.assert_checks(checks)
        self.assertEqual(self.model.baseline_features(self.frame).dtype, np.float32)
        with patch.object(IsolationForest, 'fit', side_effect=AssertionError('IF must never fit')):
            make_model(self.frame, self.labels, self.estimator)
            self.model.baseline_raw_scores(self.frame)

    def test_original_weights_references_ridge_prefix_and_availability_remain_unchanged(self):
        checks = audit.Checks()
        weights = audit.audit_training(checks, 'synthetic', self.model, self.frame, self.labels)
        conditional = audit.audit_conditional_training(checks, 'synthetic', self.model, self.frame, self.labels)
        audit.audit_conditional_frame(checks, 'synthetic', self.model, self.frame, conditional)
        self.assert_checks(checks)
        self.assertEqual(self.model.model_.fitted_shape[1], len(self.model.v9_feature_names_) + 2)
        np.testing.assert_array_equal(self.model.model_.weights, weights['sample'][weights['eligible']])
        np.testing.assert_array_equal(self.model.model_.labels, self.labels[weights['eligible']])

    def test_none_estimator_does_not_remove_original_available_rows(self):
        model = make_model(self.frame, self.labels, None)
        full, available = model.features(self.frame)
        view = copy(model); view.feature_names_ = model.v9_feature_names_
        original, old_available = ConditionalResidualHGBScorer.features(view, self.frame)
        np.testing.assert_array_equal(full[:, :-2], original)
        np.testing.assert_array_equal(full[:, -2:], np.zeros((len(full), 2), np.float32))
        np.testing.assert_array_equal(available, old_available)
        self.assertTrue(available.any())
        checks = audit.Checks(); audit.audit_if_frame(checks, 'none', model, self.frame)
        self.assert_checks(checks)

    def test_prefix_future_and_label_mutations_do_not_change_if_features(self):
        frame = self.frame.iloc[:260].copy(); original = self.model.baseline_features(frame)
        for stop in (0, 1, 14, 15, 60, 121, 260):
            np.testing.assert_array_equal(self.model.baseline_features(frame.iloc[:stop]), original[:stop])
        altered = frame.copy(); altered.iloc[121:] = -1e9
        np.testing.assert_array_equal(self.model.baseline_features(altered)[:121], original[:121])
        np.testing.assert_array_equal(self.model.baseline_features(frame.assign(EVENT=1, label=-1)), original)

    def test_serialized_if_semantic_identity_and_attachment_hash_remain_unchanged(self):
        before = audit.certified.fitted_state_digest(self.estimator)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bundle.joblib'; joblib.dump(self.model, path, compress=3)
            restored = joblib.load(path)
            self.assertEqual(before, audit.certified.fitted_state_digest(restored.baseline_estimator_))
            self.assertEqual(restored.baseline_state_hash_at_attachment_, audit.certified.fitted_state_digest(restored.baseline_estimator_))
            np.testing.assert_array_equal(restored.baseline_raw_scores(self.frame), self.model.baseline_raw_scores(self.frame))

    def test_corrupt_or_wrong_origin_estimator_is_detected(self):
        original = audit.certified.fitted_state_digest(self.estimator)
        restored = copy(self.model); restored.baseline_estimator_ = copy(self.estimator)
        restored.baseline_estimator_.offset_ = -.7
        self.assertNotEqual(original, audit.certified.fitted_state_digest(restored.baseline_estimator_))
        self.assertNotEqual(restored.baseline_state_hash_at_attachment_, audit.certified.fitted_state_digest(restored.baseline_estimator_))
        # Offset does not affect score_samples: semantic lineage catches what
        # score replay alone would miss.
        np.testing.assert_array_equal(restored.baseline_raw_scores(self.frame), self.model.baseline_raw_scores(self.frame))

    def test_saved_prior_if_lineage_and_known_normal_population_are_both_checked(self):
        count = int(audit.baseline_fit_mask_oracle(self.frame, self.labels, self.model.channels).sum())
        prior = {'prior_bundle': {'model': SimpleNamespace(baseline_=self.estimator, baseline_fit_rows_=count)},
                 'max_fit_index': len(self.frame)-1}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); joblib.dump(prior, folder / 'bundle.joblib')
            checks = audit.Checks()
            result = audit.audit_if_lineage(checks, 'synthetic', self.model, {'reference_bundle': prior},
                self.frame, self.labels, folder, {})
            self.assert_checks(checks)
            self.assertEqual(result['original_known_normal_training_windows'], count)
            # Same model scores cannot hide a falsely declared normal fit count.
            prior['prior_bundle']['model'].baseline_fit_rows_ -= 1
            joblib.dump(prior, folder / 'bundle.joblib')
            checks = audit.Checks()
            with self.assertRaisesRegex(ValueError, 'known_normal_fit_population'):
                audit.audit_if_lineage(checks, 'wrong_count', self.model, {'reference_bundle': prior},
                    self.frame, self.labels, folder, {})
            self.assertTrue(any(not r['passed'] for r in checks.records))

    def test_nonfinite_and_unrepresentable_scores_disable_only_added_evidence(self):
        for value in (np.nan, np.inf, 1e100):
            with patch.object(self.estimator, 'score_samples', side_effect=lambda x, v=value: np.full(len(x), v)):
                raw, block, _, _ = audit.baseline_feature_oracle(self.frame, self.model.channels, self.estimator)
                np.testing.assert_array_equal(block, self.model.baseline_features(self.frame))
                self.assertFalse(block.any())

    def test_v10_scalar_policy_is_exact_frozen_policy_not_v11_protection(self):
        from ml.gecco_v10.calibration import predict
        choice = audit.v10.reference_choice()
        choice.update(decision='candidate', low_threshold=.5, confirmation_samples=2,
                      confirmation_delay_seconds=120., pending_after_clear=True)
        ref = np.array([0, 1, 0, 0, 1, 1, 0, -1], np.int8)
        scores = np.array([.1, .1, .1, .8, .1, .8, .1, .1])
        rescue = np.full(len(ref), np.nan)
        actual, _ = audit.scalar_prediction(ref, scores, rescue, choice)
        np.testing.assert_array_equal(actual, predict(ref, scores, choice, rescue))
        self.assertEqual(actual[1], 0)  # No automatic retained-IF hard protection.


class CompleteGateTests(unittest.TestCase):
    def manifest(self):
        plan = {'case_order': list(audit.EXPECTED_NAMES), 'reference_sha256': {}, 'input_sha256': {}}
        for i, name in enumerate(audit.EXPECTED_NAMES):
            folder = ('output/ml/gecco-v6-development/run_04' if i < 13 else
                      'output/ml/gecco-v6-waterhub-first-use') + '/' + name
            files = {filename: 'a' * 64 for filename in audit.REFERENCE_FILES}
            plan['reference_sha256'][name] = {'folder': folder, 'files': files}
            plan['input_sha256'].update({folder + '/' + key: value for key, value in files.items()})
        return plan

    def test_upfront_reference_manifest_checks_all19_without_opening_values(self):
        checks = audit.Checks()
        with patch.object(Path, 'open', side_effect=AssertionError('Metadata check must not open source')):
            audit.verify_reference_manifest(self.manifest(), checks)
        self.assertTrue(all(r['passed'] for r in checks.records))
        self.assertEqual(len([r for r in checks.records if ':upfront_reference_in_input_closure:' in r['check']]), 76)

    def test_upfront_reference_manifest_rejects_changed_case_folder_hash_or_missing_input(self):
        for failure in ('order', 'missing_case', 'folder', 'hash', 'missing_input', 'extra_file'):
            with self.subTest(failure=failure):
                plan = self.manifest(); first = audit.EXPECTED_NAMES[0]
                record = plan['reference_sha256'][first]
                if failure == 'order': plan['case_order'].reverse()
                elif failure == 'missing_case': plan['reference_sha256'].pop(first)
                elif failure == 'folder': record['folder'] = 'output/other'
                elif failure == 'hash': record['files']['bundle.joblib'] = 'b' * 64
                elif failure == 'missing_input': plan['input_sha256'].pop(record['folder'] + '/bundle.joblib')
                elif failure == 'extra_file': record['files']['unplanned.joblib'] = 'a' * 64
                with self.assertRaises(ValueError):
                    audit.verify_reference_manifest(plan, audit.Checks())

    def test_incomplete_run_cannot_open_sources_or_write_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plan.json').write_text(json.dumps({'attempt': audit.ATTEMPT, 'scope': 'all', 'limit_cases': 19}))
            (root / 'results.json').write_text(json.dumps({'complete_cases': 1, 'expected_cases': 19}))
            with patch.object(audit, '_source_frames', side_effect=AssertionError('No source access')):
                with self.assertRaises(ValueError): audit.audit_directory(root, workspace_root=root)
            self.assertFalse((root / 'audit.json').exists())

    def test_only_exact_v12_attempt_and_class_are_accepted(self):
        result = audit.method_spec({'attempt': audit.ATTEMPT})
        self.assertEqual(result['runtime'], 'ml.gecco_v12.runtime')
        self.assertEqual(result['model_class'], 'BaselineEvidenceHGBScorer')
        with self.assertRaises(ValueError): audit.method_spec({'attempt': 'v11'})


if __name__ == '__main__': unittest.main()
