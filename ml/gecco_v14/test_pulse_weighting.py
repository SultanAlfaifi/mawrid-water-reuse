"""Synthetic-only tests for V14 pulse geometry, weights and frozen inference."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from threadpoolctl import threadpool_limits

from ml.gecco_v7.long_context_hgb import HGB_PARAMS
from ml.gecco_v8.test_onset import weighting_fixture
from ml.gecco_v9.conditional import REFERENCE_ATTRIBUTES
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer, baseline_state_digest
from ml.gecco_v12.test_baseline_evidence import fitted_if
from ml.gecco_v14.pulse_weighting import SensorTailPulseHGBScorer


def fixture(n=600):
    frame = pd.DataFrame(np.random.default_rng(918).normal(size=(n, 4)), columns=list('abcd'))
    labels = np.zeros(n, np.int8)
    labels[200:230] = 1; labels[300:320] = 1
    raw = np.zeros(n); raw[10:60] = 1  # q95=1, independent of positive pulse scores.
    return frame, labels, raw


def cheap_fit(frame, labels, raw, available=None, scorer=None):
    model = scorer or SensorTailPulseHGBScorer(list(frame.columns), None)
    with patch.object(HistGradientBoostingClassifier, 'fit', return_value=None), \
         patch.object(model, 'baseline_raw_scores', lambda data: np.asarray(raw, float)[:len(data)]):
        if available is None:
            return model.fit(frame, labels)
        with patch.object(model, 'features', lambda data: (
            np.zeros((len(data), len(model.feature_names_)), np.float32), np.asarray(available, bool)[:len(data)])):
            return model.fit(frame, labels)


def weight_oracle(labels, raw, eligible):
    """Independent small scalar oracle: full-axis episodes before label filtering."""
    n = len(labels)
    population = [raw[t] for t in range(n) if labels[t] == 0 and np.isfinite(raw[t])]
    q = float(np.quantile(population, .95, method='linear')) if population else None
    tail = [q is not None and np.isfinite(v) and v >= q for v in raw]
    pulse_windows = []
    t = 0
    while t < n:
        if not tail[t]: t += 1; continue
        a = t
        while t < n and tail[t]: t += 1
        if a > 0 and np.isfinite(raw[a-1]) and raw[a-1] < q:
            pulse_windows.append(list(range(a, min(t, a + 3))))
    segments = []; t = 0
    while t < n:
        if labels[t] != 1: t += 1; continue
        a = t
        while t < n and labels[t] == 1: t += 1
        rows = [j for j in range(a, t) if eligible[j]]
        if rows:
            windows = [[j for j in window if a <= j < t and eligible[j]] for window in pulse_windows]
            segments.append((rows, [w for w in windows if w]))
    positive = [j for j in range(n) if labels[j] == 1 and eligible[j]]
    negative = [j for j in range(n) if labels[j] == 0 and eligible[j]]
    qualifying = sum(bool(w) for _, w in segments)
    w = np.zeros(n); bonus = np.zeros(n)
    w[negative] = .5 / len(negative); w[positive] = .125 / len(positive)
    for rows, windows in segments:
        w[rows] += (.125 if qualifying else .375) / (len(segments) * len(rows))
        for window in windows:
            bonus[window] += .25 / (qualifying * len(windows) * len(window))
    return w + bonus, bonus, q


class PulseWeightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = weighting_fixture()
        cls.channels = list(cls.frame.columns)
        cls.estimator = fitted_if(cls.frame, cls.labels)
        cls.if_hash = baseline_state_digest(cls.estimator)
        with threadpool_limits(limits=1), patch.object(IsolationForest, 'fit', side_effect=AssertionError('IF refit forbidden')):
            cls.model = SensorTailPulseHGBScorer(cls.channels, cls.estimator).fit(cls.frame, cls.labels)
            cls.prior = BaselineEvidenceHGBScorer(cls.channels, cls.estimator).fit(cls.frame, cls.labels)

    def test_independent_hierarchy_all_pulses_equal_segment_then_pulse_then_rows(self):
        frame, y, raw = fixture()
        raw[200:204] = 2; raw[210:211] = 2; raw[305:307] = 2
        model = cheap_fit(frame, y, raw)
        expected, bonus, q = weight_oracle(y, raw, model.training_eligible_mask_)
        np.testing.assert_allclose(model.training_normalized_weight_, expected, atol=1e-16, rtol=0)
        np.testing.assert_allclose(model.training_pulse_bonus_weight_, bonus, atol=1e-16, rtol=0)
        self.assertEqual(model.pulse_q95_, q)
        self.assertEqual(model.eligible_pulse_segments_, 2); self.assertEqual(model.eligible_pulse_count_, 3)
        self.assertAlmostEqual(bonus[200:203].sum(), .0625)
        self.assertAlmostEqual(bonus[210], .0625)
        self.assertAlmostEqual(bonus[305:307].sum(), .125)
        for segment in model.pulse_segment_audit_:
            self.assertAlmostEqual(segment['normalized_pulse_weight_mass'], .125)
            self.assertEqual(segment['normalized_onset_weight_mass'], 0)

    def test_quantile_all_normal_includes_feature_ineligible_rows(self):
        frame, y, raw = fixture(); raw[:] = 0; raw[:61] = 10
        available = np.ones(len(y), bool); available[:61] = False
        model = cheap_fit(frame, y, raw, available)
        self.assertEqual(model.pulse_q95_, 10)
        self.assertEqual(np.quantile(raw[(y == 0) & available], .95), 0)
        self.assertTrue(model.pulse_quantile_mask_[:61].all())
        self.assertEqual(model.inspection()['sensor_tail_pulse_weighting']['quantile_population_hgb_ineligible_rows'], 61)

    def test_positive_unknown_and_nonfinite_excluded_from_quantile(self):
        frame, y, raw = fixture(); y[400:420] = -1
        raw[[100, 101, 102]] = [np.nan, np.inf, -np.inf]
        first = cheap_fit(frame, y, raw)
        changed = raw.copy(); changed[y != 0] = 1e9
        second = cheap_fit(frame, y, changed)
        self.assertEqual(first.pulse_q95_, second.pulse_q95_)
        np.testing.assert_array_equal(second.pulse_quantile_mask_, (y == 0) & np.isfinite(changed))
        self.assertTrue((second.training_normalized_weight_[y == -1] == 0).all())
        self.assertFalse(second.pulse_tail_mask_[[100, 101, 102]].any())

    def test_ties_count_as_tail_and_constant_tail_has_no_fabricated_onset(self):
        frame, y, raw = fixture(); raw[200:205] = 1
        model = cheap_fit(frame, y, raw)
        self.assertEqual(model.pulse_q95_, 1)
        self.assertTrue(model.pulse_tail_mask_[200:205].all())
        self.assertEqual(model.pulse_records_[1]['window_row_indices'], [200, 201, 202])
        constant = cheap_fit(frame, y, np.full(len(y), .5))
        self.assertTrue(constant.pulse_tail_mask_.all())
        self.assertEqual(len(constant.pulse_records_), 1)
        self.assertFalse(constant.pulse_records_[0]['known_onset'])
        self.assertTrue(constant.pulse_bonus_redistributed_)

    def test_series_start_and_after_nonfinite_are_censored(self):
        frame, y, raw = fixture(); y[:] = 0; y[180:240] = 1
        raw[:3] = 1; raw[200] = np.nan; raw[201:205] = 2
        raw[210:214] = 2; raw[220] = np.inf; raw[221:225] = 2
        model = cheap_fit(frame, y, raw)
        by_start = {p['start']: p for p in model.pulse_records_}
        for start in (0, 201, 221):
            self.assertFalse(by_start[start]['known_onset'])
            self.assertEqual(by_start[start]['window_row_indices'], [])
        self.assertEqual(by_start[210]['window_row_indices'], [210, 211, 212])
        self.assertEqual(np.flatnonzero(model.pulse_bonus_mask_).tolist(), [210, 211, 212])

    def test_pulse_clear_truncates_window_even_if_next_rows_positive(self):
        frame, y, raw = fixture(); raw[205] = 2; raw[215:217] = 2
        model = cheap_fit(frame, y, raw)
        self.assertEqual(np.flatnonzero(model.pulse_bonus_mask_).tolist(), [205, 215, 216])
        self.assertEqual(model.training_pulse_bonus_weight_[206], 0)
        self.assertEqual(model.training_pulse_bonus_weight_[217], 0)

    def test_label_boundary_never_restarts_sensor_pulse(self):
        frame, y, raw = fixture(); y[:] = 0; y[201:208] = 1
        raw[198:210] = 2
        model = cheap_fit(frame, y, raw)
        self.assertTrue(model.pulse_tail_mask_[201])
        self.assertFalse(model.pulse_window_mask_[201])
        self.assertFalse(model.pulse_bonus_mask_.any())
        self.assertTrue(model.pulse_bonus_redistributed_)
        self.assertFalse(any(p['start'] == 201 for p in model.pulse_records_))

    def test_one_pulse_can_intersect_two_segments_without_unknown_bridge(self):
        frame, y, raw = fixture(); y[:] = 0
        y[300] = 1; y[301] = -1; y[302:310] = 1; raw[300:310] = 2
        model = cheap_fit(frame, y, raw)
        pulse = next(p for p in model.pulse_records_ if p['start'] == 300)
        self.assertEqual(pulse['eligible_positive_row_indices'], [300, 302])
        self.assertEqual(len(pulse['segment_intersections']), 2)
        self.assertEqual(model.eligible_pulse_count_, 1); self.assertEqual(model.eligible_pulse_intersections_, 2)
        self.assertEqual(model.training_pulse_bonus_weight_[301], 0)
        self.assertEqual(model.training_pulse_bonus_weight_[300], .125)
        self.assertEqual(model.training_pulse_bonus_weight_[302], .125)

    def test_unavailable_window_not_shifted_and_all_later_real_pulses_kept(self):
        frame, y, raw = fixture(); raw[200:205] = 2; raw[210:215] = 2; raw[220] = 2
        available = np.ones(len(y), bool); available[200:202] = False; available[210:213] = False
        model = cheap_fit(frame, y, raw, available)
        self.assertEqual(np.flatnonzero(model.pulse_bonus_mask_).tolist(), [202, 220])
        for row in (203, 204, 213, 214): self.assertEqual(model.training_pulse_bonus_weight_[row], 0)
        self.assertEqual(model.training_pulse_bonus_weight_[202], .125)
        self.assertEqual(model.training_pulse_bonus_weight_[220], .125)
        pulse = next(p for p in model.pulse_records_ if p['start'] == 210)
        self.assertEqual(pulse['window_row_indices'], [210, 211, 212])
        self.assertEqual(pulse['eligible_positive_row_indices'], [])

    def test_global_fallback_event_mass_and_uniform_normals(self):
        frame, y, raw = fixture()
        for supplied in (raw, np.full(len(y), np.nan)):
            model = cheap_fit(frame, y, supplied)
            expected, bonus, _ = weight_oracle(y, supplied, model.training_eligible_mask_)
            np.testing.assert_allclose(model.training_normalized_weight_, expected, atol=1e-16, rtol=0)
            self.assertTrue(model.pulse_bonus_redistributed_)
            self.assertFalse(model.pulse_bonus_mask_.any()); self.assertFalse(bonus.any())
            info = model.inspection()['sensor_tail_pulse_weighting']
            self.assertAlmostEqual(info['event_component_mass'], .375)
            self.assertAlmostEqual(info['point_component_mass'], .125)
            self.assertAlmostEqual(info['normal_weight_mass'], .5)
            self.assertEqual(info['pulse_component_mass'], 0)
            self.assertEqual(info['label_onset_bonus_mass'], 0)
        with patch.object(HistGradientBoostingClassifier, 'fit', return_value=None):
            none = SensorTailPulseHGBScorer(list(frame.columns), None).fit(frame, y)
        self.assertEqual(none.pulse_quantile_status_, 'missing_estimator')
        self.assertTrue(np.isnan(none.pulse_raw_scores_).all())

    def test_independent_oracle_matches_actual_synthetic_if_weights(self):
        model = self.model
        expected, bonus, q = weight_oracle(self.labels, model.pulse_raw_scores_, model.training_eligible_mask_)
        np.testing.assert_allclose(model.training_normalized_weight_, expected, atol=1e-16, rtol=0)
        np.testing.assert_allclose(model.training_pulse_bonus_weight_, bonus, atol=1e-16, rtol=0)
        self.assertEqual(model.pulse_q95_, q)
        np.testing.assert_array_equal(model.training_sample_weight_, model.training_normalized_weight_ * model.training_eligible_mask_.sum())
        normal = model.training_eligible_mask_ & (self.labels == 0)
        np.testing.assert_array_equal(model.training_normalized_weight_[normal], np.full(normal.sum(), .5 / normal.sum()))

    def test_exact_v12_features_references_eligibility_and_model_parameters(self):
        current, prior = self.model, self.prior
        for attr in REFERENCE_ATTRIBUTES + ('normal_reference_counts_', 'normal_delta_counts_', 'positive_delta_counts_',
            'training_eligible_mask_', 'conditional_fit_mask_', 'conditional_complete_normal_mask_',
            'conditional_coef_', 'conditional_intercept_', 'conditional_residual_scale_'):
            np.testing.assert_array_equal(getattr(current, attr), getattr(prior, attr))
        np.testing.assert_array_equal(current.features(self.frame)[0], prior.features(self.frame)[0])
        np.testing.assert_array_equal(current.features(self.frame)[1], prior.features(self.frame)[1])
        self.assertEqual(current.feature_names_, prior.feature_names_)
        for name in ('features', 'score_components', 'baseline_raw_scores', '_fit_references'):
            self.assertIs(getattr(SensorTailPulseHGBScorer, name), getattr(BaselineEvidenceHGBScorer, name))
        for key, value in HGB_PARAMS.items(): self.assertEqual(current.model_.get_params()[key], value)

    def test_single_hgb_fit_known_targets_only_and_if_state_unchanged(self):
        with patch.object(HistGradientBoostingClassifier, 'fit', return_value=None) as fit, \
             patch.object(IsolationForest, 'fit', side_effect=AssertionError('IF refit forbidden')):
            model = SensorTailPulseHGBScorer(self.channels, self.estimator).fit(self.frame, self.labels)
        self.assertEqual(fit.call_count, 1)
        matrix, target = fit.call_args.args
        np.testing.assert_array_equal(target, self.labels[model.training_eligible_mask_])
        np.testing.assert_array_equal(fit.call_args.kwargs['sample_weight'], model.training_sample_weight_[model.training_eligible_mask_])
        self.assertTrue(np.isin(target, [0, 1]).all())
        self.assertEqual(matrix.shape[0], int(model.training_eligible_mask_.sum()))
        self.assertEqual(baseline_state_digest(self.estimator), self.if_hash)
        self.assertTrue(model.inspection()['sensor_tail_pulse_weighting']['if_state_unchanged'])

    def test_original_axis_inference_prefix_future_mutation_and_labels_ignored(self):
        matrix, available = self.model.features(self.frame)
        scores = self.model.score_components(self.frame)['long_context']
        for stop in (0, 1, 14, 15, 61, 132, 450, len(self.frame)-1):
            part = self.frame.iloc[:stop]
            m, a = self.model.features(part)
            np.testing.assert_array_equal(m, matrix[:stop]); np.testing.assert_array_equal(a, available[:stop])
            np.testing.assert_allclose(self.model.score_components(part)['long_context'], scores[:stop], atol=1e-12, rtol=0, equal_nan=True)
        changed = self.frame.copy(); changed.iloc[200:] = 1e4
        changed['EVENT'] = 'ignored'; changed['target'] = -1
        np.testing.assert_array_equal(self.model.features(changed)[0][:200], matrix[:200])
        np.testing.assert_allclose(self.model.score_components(changed)['long_context'][:200], scores[:200], atol=1e-12, rtol=0, equal_nan=True)

    def test_unsupported_states_and_refit_reset_are_explicit(self):
        frame, y, raw = fixture(); raw[205:210] = 2
        model = cheap_fit(frame, y, raw)
        model = cheap_fit(frame, np.zeros(len(y), np.int8), raw, scorer=model)
        self.assertEqual(model.fit_status_, 'no_event_training')
        self.assertEqual(model.pulse_status_, 'not_applied_no_event_training')
        self.assertFalse(model.training_normalized_weight_.any())
        self.assertEqual(model.pulse_segment_audit_, [])
        self.assertFalse(model.pulse_bonus_redistributed_)
        for n in (0, 1, 70):
            small = cheap_fit(frame.iloc[:n], y[:n], raw[:n])
            self.assertNotEqual(small.fit_status_, 'fitted')
            self.assertEqual(len(small.pulse_raw_scores_), n)
            self.assertTrue(np.isnan(small.score_components(frame.iloc[:n])['long_context']).all())
            json.dumps(small.inspection(), allow_nan=False)
        unknown = cheap_fit(frame, np.full(len(y), -1, np.int8), raw)
        self.assertIsNone(unknown.pulse_q95_); self.assertFalse(unknown.pulse_tail_mask_.any())
        self.assertFalse(unknown.training_normalized_weight_.any())

    def test_inspection_json_deepcopy_masks_roundtrip_and_if_fingerprint(self):
        model = self.model; info = model.inspection()['sensor_tail_pulse_weighting']
        for key, attr in (('quantile_mask_sha256', 'pulse_quantile_mask_'), ('tail_mask_sha256', 'pulse_tail_mask_'),
                          ('window_mask_sha256', 'pulse_window_mask_'), ('bonus_mask_sha256', 'pulse_bonus_mask_')):
            self.assertEqual(info[key], hashlib.sha256(np.ascontiguousarray(getattr(model, attr), dtype=np.bool_).tobytes()).hexdigest())
        json.dumps(model.inspection(), allow_nan=False)
        info['pulse_records'][0]['start'] = -100
        self.assertNotEqual(model.pulse_records_[0]['start'], -100)
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'synthetic.joblib'; joblib.dump(model, p, compress=3); restored = joblib.load(p)
        self.assertEqual(restored.inspection(), model.inspection())
        self.assertEqual(baseline_state_digest(restored.baseline_estimator_), self.if_hash)
        np.testing.assert_array_equal(restored.training_normalized_weight_, model.training_normalized_weight_)
        restored.baseline_estimator_.offset_ -= .1
        self.assertFalse(restored.inspection()['original_if_evidence']['state_unchanged'])

    def test_invalid_label_dtype_shape_values_and_raw_shape_fail(self):
        for labels in (self.labels.astype(float), self.labels[:-1], np.full(len(self.labels), 2)):
            with self.assertRaises(ValueError):
                SensorTailPulseHGBScorer(self.channels, self.estimator).fit(self.frame, labels)
        with patch.object(SensorTailPulseHGBScorer, 'baseline_raw_scores', return_value=np.ones(2)):
            with self.assertRaises(ValueError):
                SensorTailPulseHGBScorer(self.channels, self.estimator).fit(self.frame, self.labels)


if __name__ == '__main__':
    unittest.main()
