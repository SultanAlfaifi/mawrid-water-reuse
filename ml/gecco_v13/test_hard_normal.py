"""Synthetic-only V13 weight, availability, frozen IF and causal tests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from threadpoolctl import threadpool_limits
from ml.gecco_v7.long_context_hgb import HGB_PARAMS
from ml.gecco_v8.test_onset import weighting_fixture
from ml.gecco_v9.conditional import REFERENCE_ATTRIBUTES
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer, baseline_state_digest
from ml.gecco_v12.test_baseline_evidence import fitted_if
from ml.gecco_v13.hard_normal import HardNormalTailHGBScorer


def cheap_fit(frame, labels, estimator, raw=None, scorer=None):
    scorer = scorer or HardNormalTailHGBScorer(list(frame.columns), estimator)
    with patch.object(HistGradientBoostingClassifier, 'fit', return_value=None):
        if raw is None:
            return scorer.fit(frame, labels)
        with patch.object(HardNormalTailHGBScorer, 'baseline_raw_scores', lambda self, data: np.asarray(raw[:len(data)], float)):
            return scorer.fit(frame, labels)


class HardNormalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = weighting_fixture()
        cls.channels = list(cls.frame.columns)
        cls.estimator = fitted_if(cls.frame, cls.labels)
        cls.if_hash = baseline_state_digest(cls.estimator)
        with threadpool_limits(limits=1), patch.object(IsolationForest, 'fit', side_effect=AssertionError('IF refit forbidden')):
            cls.current = HardNormalTailHGBScorer(cls.channels, cls.estimator).fit(cls.frame, cls.labels)
            cls.prior = BaselineEvidenceHGBScorer(cls.channels, cls.estimator).fit(cls.frame, cls.labels)

    def test_normal_mass_and_exact_independent_recipe(self):
        model = self.current; raw = model.baseline_raw_scores(self.frame)
        population = (self.labels == 0) & np.isfinite(raw)
        q95 = np.quantile(raw[population], .95, method='linear')
        negative = model.training_eligible_mask_ & (self.labels == 0)
        tail = negative & np.isfinite(raw) & (raw >= q95)
        relative = 1.0 + 4.0 * tail[negative]
        np.testing.assert_array_equal(model.hard_normal_quantile_mask_, population)
        np.testing.assert_array_equal(model.hard_normal_tail_mask_, tail)
        self.assertEqual(model.hard_normal_q95_, q95)
        np.testing.assert_array_equal(model.training_normalized_weight_[negative], .5 * relative / relative.sum())
        self.assertAlmostEqual(model.training_normalized_weight_[negative].sum(), .5, places=14)
        self.assertAlmostEqual(model.training_normalized_weight_.sum(), 1., places=14)
        np.testing.assert_array_equal(model.training_sample_weight_, model.training_normalized_weight_ * model.training_eligible_mask_.sum())

    def test_positive_onset_mass_eligibility_and_all_features_unchanged(self):
        current, prior = self.current, self.prior
        np.testing.assert_array_equal(current.training_normalized_weight_[self.labels != 0], prior.training_normalized_weight_[self.labels != 0])
        np.testing.assert_array_equal(current.training_sample_weight_[self.labels != 0], prior.training_sample_weight_[self.labels != 0])
        self.assertEqual(current.onset_weight_audit_, prior.onset_weight_audit_)
        self.assertEqual(current.event_weight_audit_, prior.event_weight_audit_)
        for attr in REFERENCE_ATTRIBUTES + ('training_eligible_mask_', 'conditional_fit_mask_', 'conditional_complete_normal_mask_',
            'conditional_coef_', 'conditional_intercept_', 'conditional_residual_scale_'):
            np.testing.assert_array_equal(getattr(current, attr), getattr(prior, attr))
        np.testing.assert_array_equal(current.features(self.frame)[0], prior.features(self.frame)[0])
        np.testing.assert_array_equal(current.features(self.frame)[1], prior.features(self.frame)[1])
        self.assertEqual(current.feature_names_, prior.feature_names_)
        for key, value in HGB_PARAMS.items(): self.assertEqual(current.model_.get_params()[key], value)
        self.assertIs(HardNormalTailHGBScorer.score_components, BaselineEvidenceHGBScorer.score_components)

    def test_unknown_positive_scores_excluded_from_q95_and_unknown_weight_zero(self):
        raw = np.linspace(.1, .9, len(self.frame))
        first = cheap_fit(self.frame, self.labels, self.estimator, raw)
        changed = raw.copy(); changed[self.labels != 0] = 10000
        second = cheap_fit(self.frame, self.labels, self.estimator, changed)
        self.assertEqual(first.hard_normal_q95_, second.hard_normal_q95_)
        np.testing.assert_array_equal(first.training_normalized_weight_, second.training_normalized_weight_)
        self.assertFalse(second.hard_normal_quantile_mask_[self.labels != 0].any())
        self.assertTrue((second.training_sample_weight_[self.labels == -1] == 0).all())

    def test_quantile_population_includes_hgb_ineligible_rows(self):
        labels = np.zeros(len(self.frame), np.int8); labels[300:310] = 1
        raw = np.full(len(self.frame), .1); raw[:61] = .99
        model = cheap_fit(self.frame, labels, self.estimator, raw)
        normal = model.training_eligible_mask_ & (labels == 0)
        self.assertGreater(model.hard_normal_q95_, np.quantile(raw[normal], .95))
        self.assertEqual(model.hard_normal_q95_, float(np.quantile(raw[labels == 0], .95)))
        self.assertGreater(model.inspection()['hard_normal_weighting']['quantile_population_hgb_ineligible_rows'], 0)

    def test_ties_are_tail_and_all_ties_remain_uniform(self):
        model = cheap_fit(self.frame, self.labels, self.estimator, np.full(len(self.frame), .4))
        normal = model.training_eligible_mask_ & (self.labels == 0)
        np.testing.assert_array_equal(model.hard_normal_tail_mask_, normal)
        self.assertEqual(model.hard_normal_q95_, .4)
        np.testing.assert_allclose(model.training_normalized_weight_[normal], .5 / normal.sum(), rtol=0, atol=1e-18)

    def test_nonfinite_scores_are_base_weight_without_row_removal(self):
        raw = np.linspace(.1, .9, len(self.frame)); raw[[150, 151, 152]] = [np.nan, np.inf, -np.inf]
        model = cheap_fit(self.frame, self.labels, self.estimator, raw)
        self.assertTrue(model.training_eligible_mask_[[150, 151, 152]].all())
        self.assertFalse(model.hard_normal_quantile_mask_[[150, 151, 152]].any())
        self.assertFalse(model.hard_normal_tail_mask_[[150, 151, 152]].any())
        weights = model.training_normalized_weight_
        np.testing.assert_array_equal(weights[[150, 151, 152]], np.full(3, weights[153]))
        tail = np.flatnonzero(model.hard_normal_tail_mask_)[0]
        self.assertAlmostEqual(weights[tail] / weights[150], 5.)

    def test_no_finite_normal_if_and_none_estimator_uniform_fallback(self):
        raw = np.full(len(self.frame), np.nan); raw[self.labels == 1] = .99
        model = cheap_fit(self.frame, self.labels, self.estimator, raw)
        self.assertIsNone(model.hard_normal_q95_)
        self.assertEqual(model.hard_normal_quantile_status_, 'no_finite_known_normal_scores')
        self.assertEqual(model.hard_normal_status_, 'uniform_fallback')
        np.testing.assert_array_equal(model.training_normalized_weight_, self.prior.training_normalized_weight_)
        none = cheap_fit(self.frame, self.labels, None)
        self.assertEqual(none.hard_normal_quantile_status_, 'missing_estimator')
        np.testing.assert_array_equal(none.training_normalized_weight_, self.prior.training_normalized_weight_)
        self.assertTrue(np.isnan(none.hard_normal_raw_scores_).all())

    def test_no_eligible_onset_redistribution_preserved(self):
        labels = np.zeros(len(self.frame), np.int8)
        labels[:90] = 1; labels[299] = -1; labels[300:310] = 1; labels[500:520] = 1
        model = cheap_fit(self.frame, labels, self.estimator)
        with patch.object(HistGradientBoostingClassifier, 'fit', return_value=None):
            prior = BaselineEvidenceHGBScorer(self.channels, self.estimator).fit(self.frame, labels)
        self.assertTrue(model.onset_mass_redistributed_)
        self.assertEqual(model.onset_weight_audit_, prior.onset_weight_audit_)
        np.testing.assert_array_equal(model.training_normalized_weight_[labels != 0], prior.training_normalized_weight_[labels != 0])

    def test_single_hgb_fit_and_never_if_refit(self):
        with patch.object(HistGradientBoostingClassifier, 'fit', return_value=None) as fit, patch.object(IsolationForest, 'fit', side_effect=AssertionError('no IF fit')):
            model = HardNormalTailHGBScorer(self.channels, self.estimator).fit(self.frame, self.labels)
        self.assertEqual(fit.call_count, 1)
        self.assertEqual(baseline_state_digest(self.estimator), self.if_hash)
        self.assertEqual(model.hard_normal_if_state_before_, self.if_hash)
        self.assertTrue(model.inspection()['original_if_evidence']['state_unchanged'])

    def test_original_axis_causal_prefix_future_and_label_column_isolation(self):
        matrix, available = self.current.features(self.frame); scores = self.current.score_components(self.frame)
        for stop in (0, 1, 14, 15, 61, 132, 450, len(self.frame)-1):
            part = self.frame.iloc[:stop]; m, a = self.current.features(part)
            np.testing.assert_array_equal(m, matrix[:stop]); np.testing.assert_array_equal(a, available[:stop])
            for key, values in self.current.score_components(part).items():
                np.testing.assert_allclose(values, scores[key][:stop], rtol=0, atol=1e-12, equal_nan=True)
        changed = self.frame.copy(); changed.iloc[200:] = 1e4; changed['EVENT'] = 'ignored'; changed['label'] = -1
        np.testing.assert_array_equal(self.current.features(changed)[0][:200], matrix[:200])
        for key, values in self.current.score_components(changed).items():
            np.testing.assert_allclose(values[:200], scores[key][:200], rtol=0, atol=1e-12, equal_nan=True)

    def test_unavailable_fit_status_and_second_fit_reset_audit(self):
        model = cheap_fit(self.frame, self.labels, self.estimator)
        labels = np.zeros(len(self.frame), np.int8)
        cheap_fit(self.frame, labels, self.estimator, scorer=model)
        self.assertEqual(model.fit_status_, 'no_event_training')
        self.assertEqual(model.hard_normal_status_, 'not_applied_no_event_training')
        self.assertTrue((model.training_normalized_weight_ == 0).all())
        self.assertEqual(model.inspection()['hard_normal_weighting']['normal_weight_mass'], 0)
        for n in (0, 1, 70):
            empty = cheap_fit(self.frame.iloc[:n], labels[:n], self.estimator)
            self.assertNotEqual(empty.fit_status_, 'fitted')
            self.assertEqual(len(empty.hard_normal_raw_scores_), n)
            self.assertTrue(np.isnan(empty.score_components(self.frame.iloc[:n])['long_context']).all())
            json.dumps(empty.inspection(), allow_nan=False)
        unknown = cheap_fit(self.frame, np.full(len(self.frame), -1, np.int8), self.estimator)
        self.assertIsNone(unknown.hard_normal_q95_); self.assertFalse(unknown.hard_normal_quantile_mask_.any())

    def test_auditable_masks_masses_json_and_inspection_readonly(self):
        info = self.current.inspection()['hard_normal_weighting']
        for key, attr in [('quantile_mask_sha256','hard_normal_quantile_mask_'), ('eligible_normal_mask_sha256','hard_normal_eligible_normal_mask_'), ('tail_mask_sha256','hard_normal_tail_mask_')]:
            self.assertEqual(info[key], hashlib.sha256(np.ascontiguousarray(getattr(self.current, attr), dtype=np.bool_).tobytes()).hexdigest())
        self.assertAlmostEqual(info['normal_weight_mass'], .5)
        self.assertAlmostEqual(info['positive_weight_mass'], .5)
        self.assertEqual(info['unknown_weight_mass'], 0)
        self.assertTrue(info['if_state_unchanged']); self.assertFalse(info['if_refitted'])
        json.dumps(self.current.inspection(), allow_nan=False)
        info['q95'] = -123
        self.assertNotEqual(self.current.inspection()['hard_normal_weighting']['q95'], -123)

    def test_roundtrip_preserves_if_fingerprint_and_mask_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'synthetic.joblib'; joblib.dump(self.current, path, compress=3); model = joblib.load(path)
        self.assertEqual(model.inspection(), self.current.inspection())
        self.assertEqual(baseline_state_digest(model.baseline_estimator_), self.if_hash)
        np.testing.assert_array_equal(model.hard_normal_raw_scores_, self.current.hard_normal_raw_scores_)
        np.testing.assert_array_equal(model.training_normalized_weight_, self.current.training_normalized_weight_)
        model.baseline_estimator_.offset_ -= .1
        self.assertFalse(model.inspection()['original_if_evidence']['state_unchanged'])

    def test_invalid_labels_and_raw_score_shape_rejected(self):
        for labels in (self.labels.astype(float), self.labels[:-1], np.full(len(self.labels), 2)):
            with self.assertRaises(ValueError): cheap_fit(self.frame, labels, self.estimator)
        with patch.object(HardNormalTailHGBScorer, 'baseline_raw_scores', return_value=np.ones(2)):
            with self.assertRaises(ValueError): cheap_fit(self.frame, self.labels, self.estimator)


if __name__ == '__main__':
    unittest.main()
