"""Synthetic-only HGB substitution tests. No source dataset is opened."""
import ast
import inspect
import json
import textwrap
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.gecco_v7.long_context import LongContextEventScorer
from ml.gecco_v7.long_context_hgb import HGB_PARAMS, LongContextHGBScorer


def synthetic(n=4000):
    rng = np.random.default_rng(427)
    values = rng.normal(0, .05, (n, 4)) + np.arange(4)
    labels = np.zeros(n, dtype=np.int8)
    labels[700:2600] = 1
    labels[3000:3030] = 1
    labels[350:380] = -1
    values[labels == 1] += 1.25
    return pd.DataFrame(values, columns=list("abcd")), labels


class HGBSubstitutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = synthetic()
        # Execution resource control only; no estimator hyperparameter changes.
        cls.thread_limit = threadpool_limits(limits=1)
        cls.thread_limit.__enter__()
        cls.scorer = LongContextHGBScorer(list("abcd")).fit(cls.frame, cls.labels)
        cls.scores = cls.scorer.score_components(cls.frame)["long_context"]

    @classmethod
    def tearDownClass(cls):
        cls.thread_limit.__exit__(None, None, None)

    def test_fit_code_matches_parent_except_estimator_names(self):
        def normalized(method):
            source = textwrap.dedent(inspect.getsource(method))
            source = source.replace("HistGradientBoostingClassifier", "ExtraTreesClassifier").replace("HGB_PARAMS", "MODEL_PARAMS")
            return ast.dump(ast.parse(source), include_attributes=False)
        self.assertEqual(normalized(LongContextHGBScorer.fit), normalized(LongContextEventScorer.fit))

    def test_fixed_hgb_parameters_and_no_random_early_stopping(self):
        expected = dict(max_iter=100, max_leaf_nodes=15, max_depth=None, min_samples_leaf=20,
                        learning_rate=.08, l2_regularization=1, max_bins=63, early_stopping=False,
                        random_state=20261016)
        self.assertEqual(HGB_PARAMS, expected)
        for key, value in expected.items():
            self.assertEqual(self.scorer.model_.get_params()[key], value)
        self.assertEqual(self.scorer.model_.n_iter_, 100)
        self.assertFalse(self.scorer.model_.do_early_stopping_)

    def test_feature_weight_reference_contract_identical_to_frozen_parent(self):
        with patch("ml.gecco_v7.long_context.ExtraTreesClassifier.fit", return_value=None):
            original = LongContextEventScorer(list("abcd")).fit(self.frame, self.labels)
        base_contract = {k: v for k, v in original.feature_contract_.items() if k not in ("version", "classifier")}
        new_contract = {k: v for k, v in self.scorer.feature_contract_.items() if k not in ("version", "classifier")}
        self.assertEqual(new_contract, base_contract)
        for attribute in ("normal_median_", "normal_iqr_", "noise_floor_", "level_scale_", "reference_supported_",
                          "normal_reference_counts_", "normal_delta_counts_", "training_eligible_mask_",
                          "training_sample_weight_", "training_normalized_weight_"):
            np.testing.assert_array_equal(getattr(self.scorer, attribute), getattr(original, attribute))
        self.assertEqual(original.event_weight_audit_, self.scorer.event_weight_audit_)
        a, aa = original.features(self.frame)
        b, ba = self.scorer.features(self.frame)
        np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(aa, ba)

    def test_unknown_labels_are_absent_from_supervision_and_all_weights(self):
        self.assertTrue((self.scorer.training_sample_weight_[self.labels == -1] == 0).all())
        captured = {}
        def capture(_estimator, matrix, target, sample_weight):
            captured.update(target=target, weights=sample_weight, rows=len(matrix))
            return _estimator
        with patch("ml.gecco_v7.long_context_hgb.HistGradientBoostingClassifier.fit", new=capture):
            scorer = LongContextHGBScorer(list("abcd")).fit(self.frame, self.labels)
        self.assertTrue(np.isin(captured["target"], [0, 1]).all())
        self.assertEqual(captured["rows"], scorer.training_eligible_mask_.sum())
        self.assertAlmostEqual(scorer.training_normalized_weight_[self.labels == 1].sum(), .5)
        self.assertAlmostEqual(scorer.training_normalized_weight_[self.labels == 0].sum(), .5)

    def test_actual_hgb_scores_prefix_and_future_mutation(self):
        for stop in (0, 60, 61, 700, 1441, 2300, 4000):
            score = self.scorer.score_components(self.frame.iloc[:stop])["long_context"]
            np.testing.assert_allclose(score, self.scores[:stop], atol=1e-12, rtol=0, equal_nan=True)
        changed = self.frame.copy()
        changed.iloc[2100:] = 1e7
        changed.iloc[2101::4] = np.nan
        score = self.scorer.score_components(changed)["long_context"]
        np.testing.assert_allclose(score[:2100], self.scores[:2100], atol=1e-12, rtol=0, equal_nan=True)

    def test_bounded_history_and_extra_labels_ignored(self):
        score = self.scorer.score_components(self.frame.iloc[-1441:])["long_context"]
        self.assertAlmostEqual(score[-1], self.scores[-1], places=12)
        labelled = self.frame.copy()
        labelled["EVENT"] = -1
        labelled["label"] = np.arange(len(labelled)) % 2
        np.testing.assert_allclose(self.scorer.score_components(labelled)["long_context"], self.scores,
                                   atol=0, rtol=0, equal_nan=True)

    def test_current_missing_quorum_preserves_original_axis(self):
        frame = self.frame.iloc[:250].copy()
        frame.iloc[100, 0] = np.nan
        frame.iloc[101, :2] = np.nan
        result = self.scorer.score_components(frame)["long_context"]
        self.assertEqual(result.shape, (250,))
        self.assertTrue(np.isnan(result[:60]).all())
        self.assertTrue(np.isfinite(result[100]))
        self.assertTrue(np.isnan(result[101]))

    def test_constant_and_no_event_training_unavailable(self):
        frame = pd.DataFrame(np.ones((400, 4)), columns=list("abcd"))
        for value, status in ((0, "no_event_training"), (1, "insufficient_normal_reference"),
                              (-1, "insufficient_normal_reference")):
            scorer = LongContextHGBScorer(list("abcd")).fit(frame, np.full(400, value, np.int8))
            self.assertEqual(scorer.fit_status_, status)
            self.assertTrue(np.isnan(scorer.score_components(frame)["long_context"]).all())
            json.dumps(scorer.inspection(), allow_nan=False)

    def test_synthetic_long_event_is_ranked_through_late_stage(self):
        self.assertGreater(np.median(self.scores[2200:2500]), np.median(self.scores[3200:3700]) + .4)

    def test_invalid_labels_and_empty_source(self):
        scorer = LongContextHGBScorer(list("abcd"))
        with self.assertRaises(ValueError):
            scorer.fit(self.frame, self.labels.astype(float))
        scorer.fit(self.frame.iloc[:0], np.array([], np.int8))
        self.assertEqual(scorer.score_components(self.frame.iloc[:0])["long_context"].shape, (0,))


if __name__ == "__main__":
    unittest.main()
