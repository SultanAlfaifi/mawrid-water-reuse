"""Synthetic-only tests of the single V9 conditional-residual addition."""
import copy
import json
import pickle
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits

from ml.gecco_v7.long_context_hgb import HGB_PARAMS
from ml.gecco_v8.onset import OnsetWeightedHGBScorer
from ml.gecco_v8.test_onset import weighting_fixture
from ml.gecco_v9.conditional import (
    ADDED_KEYS, CONDITIONAL_CLIP, MIN_COMPLETE_NORMAL_ROWS,
    MIN_RESIDUAL_SCALE, REFERENCE_ATTRIBUTES, RIDGE_PARAMS,
    ConditionalResidualHGBScorer,
)


def cheap_fit(frame, labels, cls=ConditionalResidualHGBScorer):
    with patch("ml.gecco_v8.onset.HistGradientBoostingClassifier.fit", return_value=None):
        return cls(list(frame.columns)).fit(frame, labels)


def relation_fixture(n=600):
    t = np.linspace(-3, 3, n)
    frame = pd.DataFrame({"a": t, "b": 2 * t + 4, "c": -3 * t - 2})
    return frame, np.zeros(n, np.int8)


class ConditionalFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = weighting_fixture()
        cls.scorer = cheap_fit(cls.frame, cls.labels)
        cls.original = cheap_fit(cls.frame, cls.labels, OnsetWeightedHGBScorer)

    def test_only_append_features_exact_original_prefix_and_availability(self):
        old, available_old = self.original.features(self.frame)
        current, available_current = self.scorer.features(self.frame)
        self.assertEqual(current.shape, (len(self.frame), old.shape[1] + 3 * len(self.frame.columns)))
        self.assertEqual(current.dtype, np.float32)
        np.testing.assert_array_equal(old, current[:, :old.shape[1]])
        np.testing.assert_array_equal(available_old, available_current)
        self.assertEqual(self.scorer.original_feature_names_, self.original.feature_names_)
        self.assertEqual(self.scorer.feature_names_[:old.shape[1]], self.original.feature_names_)
        expected = [f"{channel}::{key}" for channel in self.frame.columns for key in ADDED_KEYS]
        self.assertEqual(self.scorer.conditional_feature_names_, expected)
        self.assertEqual(self.scorer.feature_names_[old.shape[1]:], expected)
        np.testing.assert_array_equal(current[:, old.shape[1]:], self.scorer.conditional_features(self.frame))

    def test_original_references_weights_onset_audit_and_hgb_are_identical(self):
        self.assertIs(ConditionalResidualHGBScorer.fit, OnsetWeightedHGBScorer.fit)
        self.assertIs(ConditionalResidualHGBScorer.score_components, OnsetWeightedHGBScorer.score_components)
        for attr in REFERENCE_ATTRIBUTES + ("normal_reference_counts_", "normal_delta_counts_", "positive_delta_counts_",
                "training_eligible_mask_", "training_normalized_weight_", "training_sample_weight_"):
            np.testing.assert_array_equal(getattr(self.scorer, attr), getattr(self.original, attr))
        self.assertEqual(self.scorer.onset_weight_audit_, self.original.onset_weight_audit_)
        self.assertEqual(self.scorer.onset_mass_redistributed_, self.original.onset_mass_redistributed_)
        for key, value in HGB_PARAMS.items():
            self.assertEqual(self.scorer.model_.get_params()[key], value)
        excluded = {"version", "feature_count", "feature_names", "conditional_residuals"}
        self.assertEqual({k: v for k, v in self.scorer.feature_contract_.items() if k not in excluded},
                         {k: v for k, v in self.original.feature_contract_.items() if k not in excluded})

    def test_fit_population_known_normal_complete_original_axis_no_history_gate(self):
        expected = (self.labels == 0) & np.isfinite(self.frame.to_numpy()).all(axis=1)
        np.testing.assert_array_equal(self.scorer.conditional_fit_mask_, expected)
        np.testing.assert_array_equal(self.scorer.conditional_complete_normal_mask_, expected)
        # Unlike classifier eligibility, the conditional population can use early normal rows.
        frame, labels = relation_fixture()
        scorer = cheap_fit(frame, labels)
        self.assertTrue(scorer.conditional_fit_mask_[:60].all())
        self.assertFalse(scorer.training_eligible_mask_[:60].any())
        self.assertEqual(RIDGE_PARAMS, {"alpha": 1.0, "fit_intercept": True, "solver": "svd"})
        self.assertEqual(MIN_COMPLETE_NORMAL_ROWS, 128)

    def test_closed_form_ridge_and_scales_match_full_known_normal_population(self):
        scorer = self.scorer
        z = (self.frame.to_numpy() - scorer.normal_median_) / scorer.level_scale_
        z = z[scorer.conditional_fit_mask_]
        for target, predictors in enumerate(scorer.conditional_predictor_indices_):
            self.assertEqual(predictors.tolist(), [j for j in range(z.shape[1]) if j != target])
            x = z[:, predictors]
            x_mean, y_mean = x.mean(axis=0), z[:, target].mean()
            centered = x - x_mean
            coef = np.linalg.solve(centered.T @ centered + np.eye(x.shape[1]), centered.T @ (z[:, target] - y_mean))
            intercept = y_mean - x_mean @ coef
            residual = z[:, target] - (x @ coef + intercept)
            expected_scale = max(np.quantile(np.abs(residual), .75),
                                 scorer.noise_floor_[target] / scorer.level_scale_[target], 1e-6)
            np.testing.assert_allclose(scorer.conditional_coef_[target], coef, rtol=0, atol=1e-14)
            self.assertAlmostEqual(scorer.conditional_intercept_[target], intercept, places=14)
            self.assertAlmostEqual(scorer.conditional_residual_scale_[target], expected_scale, places=14)

    def test_positive_unknown_measurements_never_fit_conditional_parameters(self):
        changed = self.frame.copy()
        changed.loc[self.labels != 0, :] = np.arange(4) + 1e6
        scorer = cheap_fit(changed, self.labels)
        for attr in REFERENCE_ATTRIBUTES + ("conditional_coef_", "conditional_intercept_", "conditional_residual_scale_",
                "conditional_fit_mask_", "conditional_complete_normal_mask_"):
            np.testing.assert_array_equal(getattr(scorer, attr), getattr(self.scorer, attr))
        # Reclassifying unknown as positive leaves the normal population identical.
        labels = self.labels.copy(); labels[labels == -1] = 1
        relabeled = cheap_fit(self.frame, labels)
        np.testing.assert_array_equal(relabeled.conditional_coef_, self.scorer.conditional_coef_)
        np.testing.assert_array_equal(relabeled.conditional_residual_scale_, self.scorer.conditional_residual_scale_)

    def test_current_only_missingness_has_whole_added_block_mask_without_availability_change(self):
        frame = self.frame.iloc[:250].copy()
        frame.iloc[100, 0] = np.nan
        frame.iloc[101, 1] = np.inf
        frame.iloc[102, :2] = np.nan
        added = self.scorer.conditional_features(frame)
        self.assertTrue((added[100:103] == 0).all())
        self.assertTrue((added[[99, 103], 2::3] == 1).all())
        _, original_available = self.original.features(frame)
        _, current_available = self.scorer.features(frame)
        np.testing.assert_array_equal(current_available, original_available)
        self.assertTrue(current_available[100])
        self.assertTrue(current_available[101])
        self.assertFalse(current_available[102])
        np.testing.assert_array_equal(self.scorer.conditional_observed(frame), (added[:, 2::3] == 1).all(axis=1))

    def test_missing_complete_training_rows_does_not_shrink_channel_set(self):
        frame = pd.DataFrame(np.tile(np.arange(4), (400, 1)).astype(float), columns=list("abcd"))
        # Each channel still has 300 finite rows and many adjacent normal pairs,
        # but no row has all four measured sensors.
        for j in range(4): frame.iloc[100 * j:100 * (j + 1), j] = np.nan
        scorer = cheap_fit(frame, np.zeros(400, np.int8))
        self.assertTrue(scorer.reference_supported_.all())
        self.assertFalse(scorer.conditional_supported_)
        self.assertEqual(scorer.conditional_fit_status_, "insufficient_complete_normal_rows")
        self.assertFalse(scorer.conditional_fit_mask_.any())
        self.assertTrue((scorer.conditional_features(frame) == 0).all())

    def test_minimum_complete_population_boundary_is_exact(self):
        frame, labels = relation_fixture(300)
        for count, supported in ((127, False), (128, True)):
            changed = frame.copy()
            changed.iloc[count:220, 0] = np.nan
            changed.iloc[220:, 1] = np.nan
            scorer = cheap_fit(changed, labels)
            self.assertTrue(scorer.reference_supported_.all())
            self.assertEqual(int(scorer.conditional_complete_normal_mask_.sum()), count)
            self.assertEqual(scorer.conditional_supported_, supported)

    def test_single_channel_unsupported_reference_no_normal_and_empty_states(self):
        frame, labels = relation_fixture()
        single = cheap_fit(frame[["a"]], labels)
        self.assertEqual(single.conditional_fit_status_, "insufficient_channels")
        self.assertEqual(single.conditional_features(frame[["a"]]).shape, (len(frame), 3))
        self.assertFalse(single.conditional_observed(frame[["a"]]).any())
        changed = frame.copy(); changed.loc[:, "c"] = np.nan
        unsupported = cheap_fit(changed, labels)
        self.assertEqual(unsupported.conditional_fit_status_, "unsupported_original_reference")
        for value in (-1, 1):
            scorer = cheap_fit(frame, np.full(len(frame), value, np.int8))
            self.assertFalse(scorer.conditional_supported_)
            self.assertTrue((scorer.conditional_features(frame) == 0).all())
            json.dumps(scorer.inspection(), allow_nan=False)
        empty = cheap_fit(frame.iloc[:0], labels[:0])
        self.assertEqual(empty.features(frame.iloc[:0])[0].shape, (0, len(empty.feature_names_)))
        self.assertEqual(empty.conditional_features(frame.iloc[:0]).shape, (0, 9))
        self.assertEqual(empty.conditional_fit_mask_.shape, (0,))

    def test_constant_and_collinear_rows_support_fixed_scale_and_ridge(self):
        constant = pd.DataFrame(np.tile([2., -3., 4.], (400, 1)), columns=list("abc"))
        scorer = cheap_fit(constant, np.zeros(400, np.int8))
        self.assertTrue(scorer.conditional_supported_)
        np.testing.assert_array_equal(scorer.conditional_coef_, np.zeros((3, 2)))
        np.testing.assert_array_equal(scorer.conditional_residual_scale_, np.ones(3))
        added = scorer.conditional_features(constant)
        self.assertTrue((added[:, 0::3] == 0).all())
        self.assertTrue((added[:, 1::3] == 0).all())
        self.assertTrue((added[:, 2::3] == 1).all())
        frame, labels = relation_fixture()
        first, second = cheap_fit(frame, labels), cheap_fit(frame, labels)
        np.testing.assert_array_equal(first.conditional_coef_, second.conditional_coef_)
        self.assertTrue(np.all(first.conditional_residual_scale_ >= MIN_RESIDUAL_SCALE))

    def test_relation_departure_and_correlated_fault_counterexample(self):
        frame, labels = relation_fixture()
        scorer = cheap_fit(frame, labels)
        current = pd.DataFrame([[.5, 5., -3.5], [.5, 9., -3.5], [8., 20., -26.]], columns=list("abc"))
        added = scorer.conditional_features(current)
        strength = np.max(added[:, 1::3], axis=1)
        self.assertGreater(strength[1], strength[0] + 5)
        self.assertLess(strength[2], strength[1])
        # A synchronized fault that lies on the relation has the same low
        # residual as an operational shift; residuals are not a safety proof.
        correlated_fault = current.iloc[[2]].copy()
        np.testing.assert_array_equal(scorer.conditional_features(correlated_fault), added[2:3])

    def test_extreme_current_values_are_clipped_or_marked_unavailable_never_nonfinite(self):
        scorer = self.scorer
        frame = pd.DataFrame([[1e200, -1e200, 1e200, -1e200],
                              [1e308, -1e308, 1e308, -1e308],
                              [np.nan, 2., 3., 4.]], columns=list("abcd"))
        added = scorer.conditional_features(frame)
        self.assertTrue(np.isfinite(added).all())
        self.assertLessEqual(np.abs(added).max(), CONDITIONAL_CLIP)
        self.assertTrue((added[2] == 0).all())
        overflowing = copy.deepcopy(scorer)
        overflowing.conditional_coef_[:] = 1e308
        added = overflowing.conditional_features(pd.DataFrame([[1e200] * 4], columns=list("abcd")))
        self.assertTrue((added == 0).all())

    def test_numerical_fit_failure_disables_entire_block_preserves_attempted_mask(self):
        frame, labels = relation_fixture()
        for error in (FloatingPointError("overflow"), np.linalg.LinAlgError("SVD failed"),
                      ValueError("array must not contain infs or NaNs")):
            with self.subTest(error=type(error).__name__):
                # Target 0 can succeed; failure at target 1 must not leave any
                # partly supported residual block or previously saved target.
                real_fit = Ridge.fit
                calls = []
                def fail_second(estimator, x, y, **kwargs):
                    calls.append(1)
                    if len(calls) == 2: raise error
                    return real_fit(estimator, x, y, **kwargs)
                with patch("ml.gecco_v9.conditional.Ridge.fit", new=fail_second):
                    scorer = cheap_fit(frame, labels)
                self.assertFalse(scorer.conditional_supported_)
                self.assertEqual(scorer.conditional_fit_status_, "numerical_fit_failure")
                self.assertEqual(scorer.conditional_failure_reason_["target"], "b")
                self.assertTrue(scorer.conditional_fit_mask_.all())
                self.assertTrue(np.isnan(scorer.conditional_coef_).all())
                self.assertTrue((scorer.conditional_features(frame) == 0).all())
                json.dumps(scorer.inspection(), allow_nan=False)

    def test_nonfinite_fitted_parameter_is_not_allowed_and_programming_errors_surface(self):
        frame, labels = relation_fixture()
        real_fit = Ridge.fit
        def bad_fit(estimator, x, y, **kwargs):
            real_fit(estimator, x, y, **kwargs)
            estimator.coef_[:] = np.inf
            return estimator
        with patch("ml.gecco_v9.conditional.Ridge.fit", new=bad_fit):
            scorer = cheap_fit(frame, labels)
        self.assertFalse(scorer.conditional_supported_)
        self.assertEqual(scorer.conditional_fit_status_, "numerical_fit_failure")
        for error in (ValueError("invalid parameter shape"), RuntimeError("programming failure")):
            with self.subTest(error=type(error).__name__):
                with patch("ml.gecco_v9.conditional.Ridge.fit", side_effect=error):
                    with self.assertRaises(type(error)):
                        cheap_fit(frame, labels)

    def test_unsupported_block_original_features_are_still_unchanged(self):
        frame = pd.DataFrame(np.ones((400, 4)), columns=list("abcd"))
        for j in range(4): frame.iloc[100 * j:100 * (j + 1), j] = np.nan
        labels = np.zeros(len(frame), np.int8)
        current, original = cheap_fit(frame, labels), cheap_fit(frame, labels, OnsetWeightedHGBScorer)
        a, aa = original.features(frame); b, ba = current.features(frame)
        np.testing.assert_array_equal(a, b[:, :a.shape[1]])
        np.testing.assert_array_equal(aa, ba)
        self.assertTrue((b[:, a.shape[1]:] == 0).all())

    def test_inspection_json_masks_and_refit_reset_are_reviewable(self):
        scorer = copy.deepcopy(self.scorer)
        info = scorer.inspection()
        json.dumps(info, allow_nan=False)
        conditional = info["conditional_residuals"]
        self.assertEqual(conditional["attempted_fit_rows"], int(scorer.conditional_fit_mask_.sum()))
        self.assertEqual(conditional["channel_order"], list(self.frame.columns))
        self.assertEqual(set(conditional["original_reference_hashes"]), set(REFERENCE_ATTRIBUTES))
        self.assertEqual(len(conditional["fit_mask_sha256"]), 64)
        self.assertEqual(info["feature_contract"]["feature_count"], len(scorer.feature_names_))
        self.assertEqual(info["feature_contract"]["feature_names"], scorer.feature_names_)
        scorer.fit(self.frame, np.full(len(self.frame), -1, np.int8))
        self.assertFalse(scorer.conditional_supported_)
        self.assertFalse(scorer.conditional_fit_mask_.any())
        self.assertTrue(np.isnan(scorer.conditional_coef_).all())
        self.assertIsNone(scorer.conditional_failure_reason_)

    def test_pure_added_method_no_mutation_label_inputs_or_history_dependency(self):
        scorer = self.scorer
        before = pickle.dumps(scorer)
        expected = scorer.conditional_features(self.frame)
        for stop in (0, 1, 60, 200, 750, len(self.frame)):
            np.testing.assert_array_equal(scorer.conditional_features(self.frame.iloc[:stop]), expected[:stop])
        changed = self.frame.copy(); changed.iloc[750:] = 1e7
        np.testing.assert_array_equal(scorer.conditional_features(changed)[:750], expected[:750])
        labelled = self.frame.copy(); labelled["EVENT"] = self.labels; labelled["label"] = -1
        np.testing.assert_array_equal(scorer.conditional_features(labelled), expected)
        labelled["EVENT"] = 999; labelled["label"] = 1
        np.testing.assert_array_equal(scorer.conditional_features(labelled), expected)
        np.testing.assert_array_equal(scorer.conditional_features(self.frame.iloc[100:101]), expected[100:101])
        self.assertEqual(pickle.dumps(scorer), before)

    def test_reject_missing_or_duplicate_configured_columns_and_invalid_labels(self):
        with self.assertRaises(ValueError): ConditionalResidualHGBScorer(["a", "a"])
        with self.assertRaises(ValueError): self.scorer.conditional_features(self.frame.drop(columns="a"))
        with self.assertRaises(ValueError): self.scorer.conditional_features(pd.concat([self.frame, self.frame[["a"]]], axis=1))
        with self.assertRaises(ValueError): cheap_fit(self.frame, self.labels.astype(float))
        unfit = ConditionalResidualHGBScorer(list(self.frame.columns))
        self.assertTrue((unfit.conditional_features(self.frame) == 0).all())
        with self.assertRaises(RuntimeError): unfit.features(self.frame)


class ConditionalInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(3245)
        n = 1800
        latent = rng.normal(size=n)
        cls.frame = pd.DataFrame({"a": latent, "b": 2 * latent + rng.normal(0, .05, n),
                                  "c": -latent + rng.normal(0, .03, n)})
        cls.labels = np.zeros(n, np.int8)
        cls.labels[400:450] = 1; cls.labels[1000:1250] = 1; cls.labels[700:720] = -1
        cls.frame.loc[cls.labels == 1, "b"] += 4
        cls.thread_limit = threadpool_limits(limits=1)
        cls.thread_limit.__enter__()
        cls.scorer = ConditionalResidualHGBScorer(list("abc")).fit(cls.frame, cls.labels)
        cls.scores = cls.scorer.score_components(cls.frame)["long_context"]

    @classmethod
    def tearDownClass(cls):
        cls.thread_limit.__exit__(None, None, None)

    def test_synthetic_hgb_fit_is_deterministic_with_preserved_parameters(self):
        repeated = ConditionalResidualHGBScorer(list("abc")).fit(self.frame, self.labels)
        np.testing.assert_array_equal(repeated.conditional_coef_, self.scorer.conditional_coef_)
        np.testing.assert_allclose(repeated.score_components(self.frame)["long_context"], self.scores, rtol=0, atol=0, equal_nan=True)
        self.assertEqual(self.scorer.model_.n_iter_, HGB_PARAMS["max_iter"])
        self.assertFalse(self.scorer.model_.do_early_stopping_)

    def test_frozen_model_scores_prefix_future_mutation_and_bounded_history(self):
        for stop in (0, 60, 61, 500, 1000, 1441, len(self.frame)):
            actual = self.scorer.score_components(self.frame.iloc[:stop])["long_context"]
            np.testing.assert_allclose(actual, self.scores[:stop], rtol=0, atol=1e-12, equal_nan=True)
        changed = self.frame.copy(); changed.iloc[1000:] = 1e5; changed.iloc[1001::3] = np.nan
        np.testing.assert_allclose(self.scorer.score_components(changed)["long_context"][:1000], self.scores[:1000], rtol=0, atol=1e-12, equal_nan=True)
        cropped = self.scorer.score_components(self.frame.iloc[-1441:])["long_context"]
        self.assertAlmostEqual(cropped[-1], self.scores[-1], places=12)

    def test_inference_label_columns_are_ignored_and_unknown_availability_remains(self):
        labelled = self.frame.copy(); labelled["EVENT"] = self.labels; labelled["label"] = 0
        np.testing.assert_allclose(self.scorer.score_components(labelled)["long_context"], self.scores, rtol=0, atol=0, equal_nan=True)
        labelled["EVENT"] = -1; labelled["label"] = 1
        np.testing.assert_allclose(self.scorer.score_components(labelled)["long_context"], self.scores, rtol=0, atol=0, equal_nan=True)
        missing = self.frame.copy(); missing.iloc[800] = np.nan
        actual = self.scorer.score_components(missing)["long_context"]
        self.assertTrue(np.isnan(actual[:60]).all())
        self.assertTrue(np.isnan(actual[800]))
        self.assertTrue(np.isfinite(actual[801]))
        self.assertTrue(np.isfinite(actual[700:720]).all())


if __name__ == "__main__":
    unittest.main()
