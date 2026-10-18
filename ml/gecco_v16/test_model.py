"""Synthetic V16 head tests. No source files, original bundles or real fits."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ml.gecco_v16 import decisions, model
from ml.gecco_v12.baseline_evidence import baseline_state_digest
from ml.gecco_v7.long_context_hgb import HGB_PARAMS


CHANNELS = ['a', 'b', 'c']


class StubIF(IsolationForest):
    """Fitted-state stub; neither IF.fit nor a source reader is called."""
    def __init__(self, width=12):
        self.width = width
        super().__init__(n_estimators=1, random_state=1)
        self.n_features_in_ = width
        self.estimators_ = []

    def score_samples(self, matrix):
        return -.5 - .01 * np.tanh(matrix[:, 0])


class RecordingHead:
    def __init__(self, **params):
        self.params = params
        self.fit_calls = 0; self.predict_calls = 0

    def fit(self, matrix, labels, sample_weight):
        self.fit_calls += 1
        self.fit_matrix = matrix.copy(); self.fit_labels = labels.copy()
        self.fit_weights = sample_weight.copy()
        self.classes_ = np.array([0, 1], dtype=np.int8)
        return self

    def predict_proba(self, matrix):
        self.predict_calls += 1
        p = np.clip(.3 + .1 * matrix[:, 0].astype(np.float64), .01, .99)
        return np.column_stack((1 - p, p))


def frame(n=720):
    t = np.arange(n, dtype=float)
    return pd.DataFrame({'a': np.sin(t / 11) + .01 * t,
                         'b': 10 + np.cos(t / 17), 'c': np.sin(t / 7) + np.cos(t / 23),
                         'EVENT': np.ones(n, dtype=int), 'timestamp': ['ignored'] * n})


def fixture(*, kinds='both', positives=((160, 168), (480, 488)), stop=720, n=720):
    x = frame(n); y = np.zeros(n, dtype=np.int8)
    for start, end in positives:
        y[start:end] = 1
    y[310:315] = -1
    generator = model.fit_generator(CHANNELS, StubIF(), x, y)
    base, available = model.features_gap(generator, x, 0)
    a = np.zeros(n, np.int8); b = a.copy()
    for i in range(80, stop - 4, 8):
        if kinds == 'both':
            a[i:i + 2] = 1; b[i + 1:i + 4] = 1
        elif kinds == 'anchor':
            b[i:i + 3] = 1
        else:
            a[i:i + 2] = 1
    folds = np.r_[np.zeros(n // 2, np.int64), np.ones(n - n // 2, np.int64)]
    full_context = np.zeros((n, 8), np.float32)
    origins = {key: np.full(n, -1, np.int64) for key in ('anchor_origins', 'recovery_origins')}
    for start, end in ((0, n // 2), (n // 2, n)):
        context = decisions.contexts(a[start:end], b[start:end])
        full_context[start:end] = context['matrix']
        for key in origins:
            origin = context[key].copy(); origin[origin >= 0] += start
            origins[key][start:end] = origin
    w = decisions.weights(y, available, folds, origins['anchor_origins'], origins['recovery_origins'])
    indices = np.flatnonzero(w['eligible'])
    X = np.concatenate((base, full_context), axis=1)
    examples = {'matrix': X[indices], 'indices': indices, 'fold_ids': folds[indices],
                'event_ids': w['event_ids'][indices], 'weights': w['sample'][indices],
                'summary': w['summary']}
    return x, y, examples, base, available, a, b, generator


def fitted(**kwargs):
    values = fixture(**kwargs)
    head = model.DecisionHeadScorer(CHANNELS, values[-1].baseline_estimator_)
    with patch.object(model, 'HistGradientBoostingClassifier', RecordingHead):
        head.fit_final(values[0], values[1], values[2])
    return head, values


class ReferenceTests(unittest.TestCase):
    def test_reference_only_generator_does_not_fit_if_or_any_head(self):
        x = frame(400); y = np.zeros(400, np.int8); y[200:205] = 1; y[260:270] = -1
        baseline = StubIF(); before = baseline_state_digest(baseline)
        with patch.object(IsolationForest, 'fit', side_effect=AssertionError('IF refit')), \
             patch.object(model.BaselineEvidenceHGBScorer, 'fit', side_effect=AssertionError('HGB fit')):
            generator = model.fit_generator(CHANNELS, baseline, x, y)
        self.assertIs(generator.baseline_estimator_, baseline)
        self.assertIsNone(generator.model_)
        self.assertTrue(generator.reference_only_fit_)
        self.assertEqual(baseline_state_digest(baseline), before)
        self.assertEqual(generator.normal_reference_counts_.tolist(), [385] * 3)
        expected = x.loc[y == 0, CHANNELS].median().to_numpy()
        np.testing.assert_array_equal(generator.normal_median_, expected)

    def test_unknown_rows_do_not_become_normal_references(self):
        x = frame(400); y = np.zeros(400, np.int8); y[200:240] = -1
        changed = x.copy(); changed.loc[200:239, CHANNELS] = 1e9
        a = model.fit_generator(CHANNELS, None, x, y)
        b = model.fit_generator(CHANNELS, None, changed, y)
        for key in ('normal_median_', 'normal_iqr_', 'noise_floor_', 'conditional_coef_', 'conditional_residual_scale_'):
            np.testing.assert_array_equal(getattr(a, key), getattr(b, key))

    def test_gap_discards_context_and_excludes_labels_and_metadata(self):
        x, y, _, _, _, a, b, generator = fixture()
        X, valid = model.features_gap(generator, x)
        tailX, tailvalid = generator.features(x.iloc[120:].reset_index(drop=True))
        np.testing.assert_array_equal(X[120:], tailX)
        np.testing.assert_array_equal(valid[120:], tailvalid)
        self.assertFalse(valid[:180].any())
        self.assertTrue(valid[180])
        self.assertFalse(X[:120].any())
        changed = x.copy(); changed.loc[:119, CHANNELS] = 1e20
        changed['EVENT'] = -1; changed['timestamp'] = 'future label metadata'
        other, ov = model.features_gap(generator, changed)
        np.testing.assert_array_equal(X, other); np.testing.assert_array_equal(valid, ov)
        full, observed, context = model.decision_matrix(generator, x, a, b)
        np.testing.assert_array_equal(full[:, :-8], X)
        np.testing.assert_array_equal(full[:, -8:], context['matrix'])
        np.testing.assert_array_equal(observed, valid)

    def test_features_prefix_and_future_mutation_are_causal(self):
        x, y, _, _, _, a, b, generator = fixture()
        whole, available = model.features_gap(generator, x)
        prefix, pv = model.features_gap(generator, x.iloc[:500])
        np.testing.assert_array_equal(whole[:500], prefix)
        np.testing.assert_array_equal(available[:500], pv)
        changed = x.copy(); changed.loc[500:, CHANNELS] = -1e8
        suffix, sv = model.features_gap(generator, changed)
        np.testing.assert_array_equal(whole[:500], suffix[:500])
        np.testing.assert_array_equal(available[:500], sv[:500])

    def test_missing_sensors_not_labels_control_availability(self):
        x, y, _, _, _, a, b, generator = fixture()
        x.loc[300, ['a', 'b']] = np.nan
        X, observed = model.features_gap(generator, x, 0)
        self.assertFalse(observed[300]); self.assertTrue(np.isfinite(X).all())
        self.assertTrue(observed[310])  # unknown training label does not mask sensors

    def test_empty_gap_and_input_validation(self):
        x = frame(400); generator = model.fit_generator(CHANNELS, None, x, np.zeros(400, np.int8))
        for n in (0, 20, 120):
            X, available = model.features_gap(generator, x.iloc[:n])
            self.assertEqual(X.shape, (n, len(generator.feature_names_)))
            self.assertFalse(available.any())
        for gap in (True, -1, 1.5):
            with self.assertRaises(ValueError): model.features_gap(generator, x, gap)
        for bad in (np.zeros(399, np.int8), np.zeros(400, float), np.full(400, 2, np.int8)):
            with self.assertRaises(ValueError): model.fit_generator(CHANNELS, None, x, bad)
        with self.assertRaises(ValueError): model.features_gap(generator, x.drop(columns=['a']))
        with self.assertRaises(ValueError): model.features_gap(generator, pd.concat((x, x[['a']]), axis=1))


class HeadFitTests(unittest.TestCase):
    def test_exact_sample_population_weights_parameters_and_one_head_fit(self):
        head, (x, y, examples, *_) = fitted()
        self.assertEqual(head.fit_status_, 'fitted')
        self.assertEqual(head.model_.fit_calls, 1)
        self.assertEqual(head.model_.params, HGB_PARAMS)
        np.testing.assert_array_equal(head.model_.fit_matrix, examples['matrix'])
        np.testing.assert_array_equal(head.model_.fit_labels, y[examples['indices']])
        np.testing.assert_array_equal(head.model_.fit_weights, examples['weights'])
        np.testing.assert_array_equal(head.example_indices_, examples['indices'])
        self.assertAlmostEqual(head.example_normalized_weight_.sum(), 1)
        self.assertTrue(all(s['supported'] for s in head.request_support_.values()))
        record = head.inspection(); json.dumps(record, allow_nan=False)
        self.assertTrue(record['original_if_unchanged'])
        generator_record = record['final_generator']
        self.assertTrue(generator_record['reference_only_fit'])
        self.assertTrue(generator_record['head_examples_from_forward_teachers'])
        self.assertFalse(generator_record['hgb_fitted_here'])
        self.assertFalse(generator_record['original_if_evidence']['in_sample_training_representation'])
        self.assertFalse(generator_record['original_if_evidence']['cross_fitted'])
        self.assertIn('no HGB is fitted here', generator_record['feature_contract']['original_if_evidence']['training_scope'])
        self.assertEqual(record['example_matrix_sha256'], model._hash_array(examples['matrix']))
        self.assertNotIn('example_matrix_', vars(head))

    def test_final_reference_refit_never_regenerates_inner_examples(self):
        x, y, examples, *other = fixture()
        X = examples['matrix'].copy(); X[:, 0] = np.float32(123.25)
        examples['matrix'] = X
        head = model.DecisionHeadScorer(CHANNELS, other[-1].baseline_estimator_)
        with patch.object(model, 'HistGradientBoostingClassifier', RecordingHead), \
             patch.object(model.BaselineEvidenceHGBScorer, 'features', side_effect=AssertionError('regenerated inner X')):
            head.fit_final(x, y, examples)
        np.testing.assert_array_equal(head.model_.fit_matrix, X)

    def test_minimum_normal_event_and_fold_support_fail_closed(self):
        cases = [({'stop': 200}, 'insufficient_normal_decision_rows'),
                 ({'positives': ((160, 168),)}, 'insufficient_positive_events'),
                 ({'positives': ((160, 168), (240, 248))}, 'insufficient_positive_folds'),
                 ({'positives': ()}, 'insufficient_positive_events')]
        for options, status in cases:
            with self.subTest(options=options):
                x, y, examples, *rest = fixture(**options)
                head = model.DecisionHeadScorer(CHANNELS, rest[-1].baseline_estimator_)
                with patch.object(model, 'HistGradientBoostingClassifier', side_effect=AssertionError('unsupported fit')):
                    head.fit_final(x, y, examples)
                self.assertEqual(head.fit_status_, status)
                self.assertIsNone(head.model_)
                self.assertTrue(np.isnan(head.score_matrix(rest[0], rest[1], rest[2], rest[3])).all())

    def test_original_event_ids_must_not_restart_at_forecast_fold(self):
        x, y, examples, *rest = fixture(positives=((160, 168), (350, 380), (480, 488)))
        head = model.DecisionHeadScorer(CHANNELS, rest[-1].baseline_estimator_)
        bad = deepcopy(examples)
        hit = np.flatnonzero((bad['indices'] >= 360) & (bad['indices'] < 380))
        self.assertGreater(len(hit), 0)
        bad['event_ids'][hit] += 1
        with self.assertRaisesRegex(ValueError, 'Event IDs'): head.fit_final(x, y, bad)

    def test_malformed_examples_rejected_without_classifier_fit(self):
        x, y, examples, *rest = fixture()
        mutations = [lambda e:e.update(matrix=e['matrix'].astype(float)),
            lambda e:e.update(matrix=e['matrix'][:, :-1]),
            lambda e:e['matrix'].__setitem__((0, 0), np.nan),
            lambda e:e['indices'].__setitem__(1, e['indices'][0]),
            lambda e:e['indices'].__setitem__(0, len(x)),
            lambda e:e.update(indices=e['indices'].astype(float)),
            lambda e:e['weights'].__setitem__(0, -1),
            lambda e:e['weights'].__setitem__(0, np.inf),
            lambda e:e.update(weights=e['weights'] / e['weights'].sum()),
            lambda e:e['summary'].__setitem__('positive_events', 99),
            lambda e:e['summary']['request_support']['anchor'].__setitem__('supported', False),
            lambda e:e['matrix'].__setitem__((0, [-4, -2]), 0),
            lambda e:e['matrix'].__setitem__((0, -8 + 5), .75)]
        for mutation in mutations:
            bad = deepcopy(examples); mutation(bad)
            with self.subTest(mutation=mutation), patch.object(model, 'HistGradientBoostingClassifier', side_effect=AssertionError('bad fit')):
                head = model.DecisionHeadScorer(CHANNELS, rest[-1].baseline_estimator_)
                with self.assertRaises(ValueError): head.fit_final(x, y, bad)

    def test_targets_derive_from_indices_and_unknown_never_positive(self):
        x, y, examples, *rest = fixture()
        bad_y = y.copy(); bad_y[examples['indices'][0]] = -1
        head = model.DecisionHeadScorer(CHANNELS, rest[-1].baseline_estimator_)
        with self.assertRaisesRegex(ValueError, 'Unknown labels'): head.fit_final(x, bad_y, examples)


class ScoreTests(unittest.TestCase):
    def test_any_active_unsupported_type_masks_overlap(self):
        head, values = fitted(kinds='anchor')
        self.assertTrue(head.request_support_['anchor']['supported'])
        self.assertFalse(head.request_support_['recovery']['supported'])
        n = 8; base = np.zeros((n, len(head.base_feature_names_)), np.float32); available = np.ones(n, bool)
        a = np.array([0, 1, 1, 0, 0, 0, 0, 0], np.int8)
        b = np.array([0, 0, 1, 1, 1, 0, 0, 0], np.int8)
        scores = head.score_matrix(base, available, a, b)
        self.assertTrue(np.isnan(scores[1:4]).all())
        self.assertTrue(np.isfinite(scores[4]))  # anchor only after recovery expires
        self.assertTrue(np.isnan(scores[[0, 5, 6, 7]]).all())

    def test_unfitted_and_unavailable_scores_are_nan(self):
        head = model.DecisionHeadScorer(CHANNELS, None)
        a = np.array([0, 1, 1], np.int8); b = np.zeros(3, np.int8)
        result = head.score(frame(3), a, b)
        self.assertEqual(result.dtype, np.float64); self.assertTrue(np.isnan(result).all())
        head, values = fitted(); n = len(values[0])
        result = head.score_matrix(values[3], np.zeros(n, bool), values[5], values[6])
        self.assertTrue(np.isnan(result).all()); self.assertEqual(head.model_.predict_calls, 0)

    def test_score_prefix_suffix_and_sensor_label_separation(self):
        head, (x, y, examples, base, available, a, b, generator) = fitted()
        whole = head.score(x, a, b)
        prefix = head.score(x.iloc[:500], a[:500], b[:500])
        np.testing.assert_array_equal(whole[:500], prefix)
        altered = x.copy(); altered.loc[500:, CHANNELS] = -1e8
        altered['EVENT'] = -1
        a2 = a.copy(); b2 = b.copy(); a2[500:] = -1; b2[500:] = 1
        other = head.score(altered, a2, b2)
        np.testing.assert_array_equal(whole[:500], other[:500])
        only_sensors = head.score(x[CHANNELS], a, b)
        np.testing.assert_array_equal(whole, only_sensors)

    def test_continuous_sensor_features_but_request_reset_per_block(self):
        head, (x, y, examples, base, available, a, b, generator) = fitted()
        a = np.zeros(len(x), np.int8); b = a.copy(); b[359:363] = 1
        X, observed = model.features_gap(head.generator_, x)
        whole = model.combine_and_score(head, X, observed, a, b)
        second = model.combine_and_score(head, X[360:], observed[360:], a[360:], b[360:])
        self.assertTrue(np.isfinite(whole[360]))
        self.assertTrue(np.isnan(second[:3]).all())  # first-row pulse is censored after reset
        self.assertTrue(observed[360])  # history was not reset with request state

    def test_empty_and_invalid_score_inputs(self):
        head, values = fitted(); width = len(head.base_feature_names_)
        self.assertEqual(head.score_matrix(np.zeros((0, width), np.float32), np.zeros(0, bool), np.zeros(0, np.int8), np.zeros(0, np.int8)).shape, (0,))
        base = np.zeros((4, width), np.float32); a = np.zeros(4, np.int8)
        with self.assertRaises(ValueError): head.score_matrix(base.astype(float), np.ones(4, bool), a, a)
        with self.assertRaises(ValueError): head.score_matrix(base, np.ones(4, int), a, a)
        with self.assertRaises(ValueError): head.score_matrix(base, np.ones(4, bool), a[:-1], a)
        base[0, 0] = np.inf
        with self.assertRaises(ValueError): head.score_matrix(base, np.ones(4, bool), a, a)

    def test_numerically_unknown_head_output_is_not_zero_confidence(self):
        head, values = fitted(); X, available, a, b = values[3:7]
        with patch.object(head.model_, 'predict_proba', side_effect=lambda mat:np.full((len(mat), 2), np.nan)):
            result = head.score_matrix(X, available, a, b)
        self.assertTrue(np.isnan(result).all())


if __name__ == '__main__':
    unittest.main()
