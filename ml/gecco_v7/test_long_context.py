"""Synthetic-only contract tests; this module never opens any source dataset."""
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v7.long_context import (
    FEATURE_KEYS, LAGS, MAX_LOOKBACK, MODEL_PARAMS, WINDOWS,
    LongContextEventScorer,
)


def synthetic(n=3800, channels=("p1", "p2", "p3", "p4"), seed=23):
    rng = np.random.default_rng(seed)
    values = rng.normal(0, .035, (n, len(channels))) + np.arange(len(channels))
    labels = np.zeros(n, dtype=np.int8)
    labels[600:min(2500, n)] = 1
    labels[2900:min(2970, n)] = 1
    values[labels == 1] += 1.4
    return pd.DataFrame(values, columns=channels), labels


class LongContextContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = synthetic()
        cls.scorer = LongContextEventScorer(list(cls.frame.columns)).fit(cls.frame, cls.labels)
        cls.matrix, cls.available = cls.scorer.features(cls.frame)
        cls.scores = cls.scorer.score_components(cls.frame)["long_context"]

    def index(self, name):
        return self.scorer.feature_names_.index(name)

    def test_fixed_estimator_and_feature_contract(self):
        self.assertEqual(self.scorer.fit_status_, "fitted")
        for name, value in MODEL_PARAMS.items():
            self.assertEqual(self.scorer.model_.get_params()[name], value)
        self.assertEqual(WINDOWS, (15, 60, 240, 1440))
        self.assertEqual(LAGS, (1, 15, 60, 240, 1440))
        self.assertEqual(len(FEATURE_KEYS), 47)
        self.assertEqual(self.matrix.shape, (len(self.frame), 47 * 7))
        self.assertEqual(self.matrix.dtype, np.float32)
        self.assertEqual(len(set(self.scorer.feature_names_)), self.matrix.shape[1])
        self.assertEqual(self.scorer.history_rows, 1441)
        self.assertEqual(self.scorer.max_lookback_, MAX_LOOKBACK)
        self.assertEqual(self.scorer.feature_contract_["classifier"], MODEL_PARAMS)

    def test_features_are_finite_bounded_with_original_axis(self):
        self.assertTrue(np.isfinite(self.matrix).all())
        self.assertLessEqual(float(np.abs(self.matrix).max()), 64)
        self.assertEqual(self.available.shape, (len(self.frame),))
        self.assertFalse(self.available[:60].any())
        self.assertTrue(self.available[60:].all())
        self.assertTrue(np.isnan(self.scores[:60]).all())
        self.assertTrue(np.isfinite(self.scores[60:]).all())
        self.assertTrue(((self.scores[60:] >= 0) & (self.scores[60:] <= 1)).all())

    def test_normal_references_and_adjacent_delta_counts(self):
        values = self.frame.to_numpy()
        normal = self.labels == 0
        pair = np.r_[False, normal[1:] & normal[:-1]]
        delta = np.abs(np.diff(values, axis=0, prepend=values[:1] * np.nan))
        for j in range(values.shape[1]):
            data = values[normal, j]
            changes = delta[pair, j]
            self.assertEqual(self.scorer.normal_reference_counts_[j], normal.sum())
            self.assertEqual(self.scorer.normal_delta_counts_[j], pair.sum())
            self.assertAlmostEqual(self.scorer.normal_median_[j], np.median(data))
            self.assertAlmostEqual(self.scorer.normal_iqr_[j], np.diff(np.quantile(data, [.25, .75]))[0])
            epsilon = max(abs(np.median(data)) * 1e-12, 1e-12)
            self.assertAlmostEqual(self.scorer.noise_floor_[j], max(np.quantile(changes, .75), epsilon))

    def test_prefix_scores_and_features_match_full_series(self):
        # Includes partial context, both event boundaries, and full-day context.
        for stop in (0, 1, 60, 61, 177, 600, 601, 1439, 1441, 2003, 2501, 3800):
            with self.subTest(stop=stop):
                prefix = self.frame.iloc[:stop]
                matrix, available = self.scorer.features(prefix)
                score = self.scorer.score_components(prefix)["long_context"]
                np.testing.assert_allclose(matrix, self.matrix[:stop], atol=0, rtol=0)
                np.testing.assert_array_equal(available, self.available[:stop])
                np.testing.assert_allclose(score, self.scores[:stop], atol=1e-12, rtol=0, equal_nan=True)

    def test_future_mutation_has_no_effect_on_earlier_features_or_scores(self):
        stop = 1643
        changed = self.frame.copy()
        changed.iloc[stop:, :] = np.random.default_rng(17).normal(100, 100, changed.iloc[stop:].shape)
        changed.iloc[stop + 2:stop + 50, 2] = np.nan
        matrix, available = self.scorer.features(changed)
        score = self.scorer.score_components(changed)["long_context"]
        np.testing.assert_array_equal(matrix[:stop], self.matrix[:stop])
        np.testing.assert_array_equal(available[:stop], self.available[:stop])
        np.testing.assert_allclose(score[:stop], self.scores[:stop], atol=1e-12, rtol=0, equal_nan=True)

    def test_exact_bounded_history_at_multiple_rows(self):
        for end in (1440, 1700, 2499, 3200, 3799):
            with self.subTest(end=end):
                window = self.frame.iloc[end - MAX_LOOKBACK:end + 1]
                matrix, available = self.scorer.features(window)
                scores = self.scorer.score_components(window)["long_context"]
                np.testing.assert_allclose(matrix[-1], self.matrix[end], atol=2e-7, rtol=2e-7)
                self.assertEqual(available[-1], self.available[end])
                np.testing.assert_allclose(scores[-1], self.scores[end], atol=1e-12, rtol=0)

    def test_older_than_declared_history_cannot_change_current_output(self):
        changed = self.frame.copy()
        changed.iloc[:-1441] = -700
        matrix, available = self.scorer.features(changed)
        score = self.scorer.score_components(changed)["long_context"]
        np.testing.assert_allclose(matrix[-1], self.matrix[-1], atol=2e-7, rtol=2e-7)
        self.assertEqual(available[-1], self.available[-1])
        self.assertAlmostEqual(score[-1], self.scores[-1], places=12)

    def test_extra_labels_and_column_order_are_ignored_at_inference(self):
        changed = self.frame.iloc[:, ::-1].copy()
        changed["EVENT"] = np.arange(len(changed)) % 3 - 1
        changed["label"] = "never a feature"
        changed.index = pd.date_range("2020-01-01", periods=len(changed), freq="min")
        score = self.scorer.score_components(changed)["long_context"]
        np.testing.assert_allclose(score, self.scores, atol=0, rtol=0, equal_nan=True)
        matrix, available = self.scorer.features(changed)
        np.testing.assert_array_equal(matrix, self.matrix)
        np.testing.assert_array_equal(available, self.available)

    def test_long_event_level_survives_after_local_means_adapt(self):
        # The feature retains the known-normal reference after >1 day elevated.
        row = 2300
        level = self.matrix[row, self.index("p1::reference_level_z")]
        local = self.matrix[row, self.index("p1::current_minus_mean_z_1440")]
        self.assertGreater(level, 10)
        self.assertLess(abs(local), 2)
        self.assertGreater(np.median(self.scores[2100:2450]), np.median(self.scores[3200:3700]) + .4)

    def test_partial_long_context_has_explicit_full_window_fraction(self):
        at = 60
        self.assertAlmostEqual(float(self.matrix[at, self.index("p1::observed_fraction_1440")]), 61 / 1440, places=7)
        self.assertAlmostEqual(float(self.matrix[at, self.index("p1::pair_observed_fraction_1440")]), 60 / 1440, places=7)
        self.assertTrue(self.available[at])

    def test_missing_channel_quorum_and_missing_history(self):
        frame = self.frame.iloc[:250].copy()
        frame.iloc[100, 0] = np.nan  # 3/4 channels still adequate.
        frame.iloc[101, :2] = np.nan  # 2/4 inadequate.
        frame.iloc[110:130, :2] = np.nan
        _, available = self.scorer.features(frame)
        self.assertTrue(available[100])
        self.assertFalse(available[101])
        self.assertFalse(available[130])  # Current is back, prior context is not.
        self.assertTrue(available[190])
        score = self.scorer.score_components(frame)["long_context"]
        self.assertTrue(np.isnan(score[101]))
        self.assertTrue(np.isnan(score[130]))
        self.assertEqual(len(score), len(frame))

    def test_missing_and_infinite_inputs_are_not_filled(self):
        frame = self.frame.iloc[:200].copy()
        frame.iloc[100, :3] = [np.inf, -np.inf, np.nan]
        matrix, available = self.scorer.features(frame)
        self.assertFalse(available[100])
        self.assertTrue(np.isfinite(matrix).all())
        for channel in ("p1", "p2", "p3"):
            self.assertEqual(matrix[100, self.index(f"{channel}::current_observed")], 0)
            self.assertEqual(matrix[100, self.index(f"{channel}::lag_pair_observed_1")], 0)
        self.assertTrue(np.isnan(self.scorer.score_components(frame)["long_context"][100]))

    def test_pooled_features_follow_configured_channels(self):
        for key in ("reference_level_z", "current_observed", "observed_fraction_1440"):
            indices = [self.index(f"{c}::{key}") for c in self.scorer.channels]
            channels = self.matrix[:, indices]
            np.testing.assert_allclose(self.matrix[:, self.index(f"pooled_mean::{key}")], channels.mean(axis=1), atol=2e-6)
            np.testing.assert_array_equal(self.matrix[:, self.index(f"pooled_min::{key}")], channels.min(axis=1))
            np.testing.assert_array_equal(self.matrix[:, self.index(f"pooled_max::{key}")], channels.max(axis=1))

    def test_json_inspection_includes_actual_reference_and_weight_counts(self):
        result = self.scorer.inspection()
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["training_rows"], len(self.frame))
        self.assertEqual(len(result["references"]), 4)
        self.assertEqual(result["eligible_positive_rows"], int((self.labels == 1).sum()))
        self.assertAlmostEqual(result["normalized_weight_sum"], 1)
        self.assertEqual(result["references"][0]["normal_readings"], int((self.labels == 0).sum()))


class LongContextTrainingAndEdgesTests(unittest.TestCase):
    @staticmethod
    def reference_only(n=1800, channels=("a",)):
        frame = pd.DataFrame(np.zeros((n, len(channels))), columns=channels)
        return LongContextEventScorer(channels).fit(frame, np.zeros(n, dtype=np.int8)), frame

    def test_constant_reference_has_positive_noise_floor_and_bounded_stall(self):
        scorer, frame = self.reference_only(1800)
        matrix, available = scorer.features(frame)
        self.assertEqual(scorer.fit_status_, "no_event_training")
        self.assertEqual(scorer.noise_floor_[0], 1e-12)
        self.assertEqual(scorer.level_scale_[0], 1e-12)
        stall_index = scorer.feature_names_.index("a::near_stall_run_fraction")
        self.assertEqual(matrix[0, stall_index], 0)
        self.assertAlmostEqual(float(matrix[100, stall_index]), 100 / 1440, places=7)
        self.assertEqual(matrix[1440, stall_index], 1)
        self.assertEqual(matrix[-1, stall_index], 1)
        cropped, _ = scorer.features(frame.iloc[-1441:])
        np.testing.assert_array_equal(cropped[-1], matrix[-1])
        frame.iloc[1500] = np.nan
        changed, _ = scorer.features(frame)
        self.assertEqual(changed[1500, stall_index], 0)
        self.assertEqual(changed[1501, stall_index], 0)
        self.assertAlmostEqual(float(changed[1502, stall_index]), 1 / 1440, places=9)
        self.assertTrue(np.isnan(scorer.score_components(frame)["long_context"]).all())

    def test_unknown_and_event_values_do_not_enter_fitted_references(self):
        x = pd.DataFrame({"a": np.sin(np.arange(600) / 7)})
        y = np.zeros(600, np.int8)
        y[200:260] = -1
        y[350:370] = 1
        altered = x.copy()
        altered.loc[y != 0, "a"] = 1e8
        first = LongContextEventScorer(["a"])
        second = LongContextEventScorer(["a"])
        # Inspect reference fitting directly to avoid treating this as a model
        # comparison; unknown observations legitimately alter causal features.
        first._fit_references(first._frame(x), y)
        second._fit_references(second._frame(altered), y)
        for name in ("normal_median_", "normal_iqr_", "noise_floor_", "level_scale_",
                     "normal_reference_counts_", "normal_delta_counts_"):
            np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
        self.assertEqual(first.normal_reference_counts_[0], 520)
        # Three known-normal stretches: lengths 200,90,230 -> 517 adjacent pairs.
        self.assertEqual(first.normal_delta_counts_[0], 199 + 89 + 229)
        features_a, _ = first.features(x)
        features_b, _ = second.features(altered)
        col = first.feature_names_.index("a::mean_reference_z_60")
        self.assertNotEqual(features_a[265, col], features_b[265, col])

    def test_unknown_nonfinite_and_nonadjacent_pairs_never_become_normal_deltas(self):
        frame = pd.DataFrame({"a": np.arange(500, dtype=float)})
        labels = np.zeros(500, np.int8)
        labels[[99, 100, 250]] = -1
        frame.iloc[[120, 121, 300]] = np.nan
        scorer = LongContextEventScorer(["a"]).fit(frame, labels)
        normal = labels == 0
        finite = frame.a.notna().to_numpy()
        expected = int((normal[1:] & normal[:-1] & finite[1:] & finite[:-1]).sum())
        self.assertEqual(scorer.normal_delta_counts_[0], expected)
        self.assertEqual(scorer.normal_reference_counts_[0], int((normal & finite).sum()))
        self.assertEqual(scorer.noise_floor_[0], 1)

    def test_weighting_preserves_event_and_point_components_and_unknown_zero(self):
        rng = np.random.default_rng(121)
        frame = pd.DataFrame({"a": rng.normal(size=1000)})
        labels = np.zeros(1000, np.int8)
        labels[0:20] = 1  # Unavailable initial event retained in inspection.
        labels[300:500] = 1
        labels[600] = 1
        labels[700:730] = -1
        captured = {}

        def capture(_model, matrix, target, sample_weight):
            captured.update(matrix=matrix, target=target, weights=sample_weight)
            return _model

        with patch("ml.gecco_v7.long_context.ExtraTreesClassifier.fit", new=capture):
            scorer = LongContextEventScorer(["a"]).fit(frame, labels)
        w = scorer.training_normalized_weight_
        self.assertAlmostEqual(w[labels == 0].sum(), .5)
        self.assertAlmostEqual(w[labels == 1].sum(), .5)
        self.assertTrue((w[labels == -1] == 0).all())
        self.assertTrue((w[:60] == 0).all())
        self.assertTrue((captured["target"] >= 0).all())
        self.assertEqual(len(captured["target"]), scorer.training_eligible_mask_.sum())
        self.assertEqual(scorer.fit_events_, 2)
        self.assertEqual(len(scorer.event_weight_audit_), 3)
        self.assertEqual(scorer.event_weight_audit_[0]["eligible_positive_rows"], 0)
        self.assertEqual(scorer.event_weight_audit_[0]["normalized_weight_mass"], 0)
        self.assertAlmostEqual(w[300:500].sum(), .25 * 200 / 201 + .125)
        self.assertAlmostEqual(w[600], .25 / 201 + .125)
        self.assertLess(w[600], w[300:500].sum())
        np.testing.assert_array_equal(captured["weights"], (w * scorer.training_eligible_mask_.sum())[scorer.training_eligible_mask_])

    def test_unknown_splits_weight_segments_without_expansion(self):
        frame = pd.DataFrame({"a": np.sin(np.arange(700))})
        labels = np.zeros(700, np.int8)
        labels[300:400] = 1
        labels[350] = -1
        with patch("ml.gecco_v7.long_context.ExtraTreesClassifier.fit", return_value=None):
            scorer = LongContextEventScorer(["a"]).fit(frame, labels)
        self.assertEqual([(r["start"], r["end_exclusive"]) for r in scorer.event_weight_audit_], [(300, 350), (351, 400)])
        self.assertEqual(scorer.training_normalized_weight_[350], 0)
        self.assertEqual(scorer.fit_positive_rows_, 99)

    def test_no_event_and_insufficient_normal_training_are_unavailable(self):
        frame = pd.DataFrame({"a": np.ones(400)})
        cases = [
            (np.zeros(400, np.int8), "no_event_training"),
            (np.ones(400, np.int8), "insufficient_normal_reference"),
            (np.full(400, -1, np.int8), "insufficient_normal_reference"),
            (np.r_[np.zeros(128, np.int8), np.ones(272, np.int8)], "insufficient_normal_examples"),
        ]
        for labels, reason in cases:
            with self.subTest(reason=reason):
                scorer = LongContextEventScorer(["a"]).fit(frame, labels)
                self.assertEqual(scorer.fit_status_, reason)
                self.assertIsNone(scorer.model_)
                self.assertTrue(np.isnan(scorer.score_components(frame)["long_context"]).all())
                json.dumps(scorer.inspection(), allow_nan=False)

    def test_supported_reference_channel_quorum_is_fixed(self):
        n = 400
        frame = pd.DataFrame(np.ones((n, 4)), columns=list("abcd"))
        labels = np.zeros(n, np.int8)
        frame["a"] = np.nan
        scorer = LongContextEventScorer(list("abcd")).fit(frame, labels)
        self.assertEqual(scorer.minimum_channels, 3)
        self.assertEqual(scorer.reference_supported_.sum(), 3)
        _, available = scorer.features(frame)
        self.assertTrue(available[60:].all())
        frame["b"] = np.nan
        scorer.fit(frame, labels)
        self.assertEqual(scorer.fit_status_, "insufficient_normal_reference")
        _, available = scorer.features(frame)
        self.assertFalse(available.any())

    def test_refit_clears_an_existing_model(self):
        frame, labels = synthetic(800, channels=("a",))
        scorer = LongContextEventScorer(["a"]).fit(frame, labels)
        self.assertIsNotNone(scorer.model_)
        scorer.fit(frame, np.zeros(len(frame), np.int8))
        self.assertIsNone(scorer.model_)
        self.assertEqual(scorer.fit_status_, "no_event_training")
        self.assertTrue(np.isnan(scorer.score_components(frame)["long_context"]).all())

    def test_empty_frame_and_unfitted_score_are_shape_safe(self):
        frame = pd.DataFrame({"a": np.array([], dtype=float)})
        scorer = LongContextEventScorer(["a"])
        self.assertEqual(scorer.score_components(frame)["long_context"].shape, (0,))
        with self.assertRaises(RuntimeError):
            scorer.features(frame)
        scorer.fit(frame, np.array([], dtype=np.int8))
        matrix, available = scorer.features(frame)
        self.assertEqual(matrix.shape, (0, 47 * 4))
        self.assertEqual(available.shape, (0,))
        json.dumps(scorer.inspection(), allow_nan=False)

    def test_constant_window_forgets_older_variance_roundoff(self):
        scorer, _ = self.reference_only(4000)
        frame = pd.DataFrame({"a": np.r_[np.sin(np.arange(2200)) * 10, np.full(1800, .137)]})
        full, _ = scorer.features(frame)
        bounded, _ = scorer.features(frame.iloc[-1441:])
        np.testing.assert_array_equal(full[-1], bounded[-1])
        for window in WINDOWS:
            self.assertEqual(full[-1, scorer.feature_names_.index(f"a::std_reference_z_{window}")], 0)

    def test_invalid_channels_labels_and_shapes_rejected(self):
        for channels in ([], ["a", "a"], [""], [1]):
            with self.assertRaises(ValueError):
                LongContextEventScorer(channels)
        scorer = LongContextEventScorer(["a"])
        frame = pd.DataFrame({"a": np.zeros(100)})
        for labels in (np.zeros(99, np.int8), np.zeros((100, 1), np.int8),
                       np.zeros(100, float), np.full(100, 2, np.int8),
                       np.full(100, np.nan), np.array(["0"] * 100)):
            with self.assertRaises(ValueError):
                scorer.fit(frame, labels)
        for bad in (pd.DataFrame({"b": [1]}), np.array([[1.0]]),
                    pd.DataFrame([[1, 2]], columns=["a", "a"])):
            with self.assertRaises(ValueError):
                scorer.score_components(bad)


if __name__ == "__main__":
    unittest.main()
