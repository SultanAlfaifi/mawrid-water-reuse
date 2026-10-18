"""Synthetic onset weighting and unchanged causal-feature/inference checks."""
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.gecco_v7.long_context_hgb import HGB_PARAMS, LongContextHGBScorer
from ml.gecco_v7.test_long_context_hgb import synthetic
from ml.gecco_v8.onset import OnsetWeightedHGBScorer, ONSET_WINDOW_SAMPLES


def weighting_fixture():
    rng = np.random.default_rng(44)
    frame = pd.DataFrame(rng.normal(size=(1200, 4)), columns=list("abcd"))
    labels = np.zeros(1200, np.int8)
    for a, b in ((0, 90), (300, 310), (400, 420), (500, 520), (600, 601), (700, 705), (800, 810)):
        labels[a:b] = 1
    labels[[299, 699]] = -1
    labels[1000:1020] = -1
    frame.iloc[[400, 402], :] = np.nan
    frame.iloc[500:503, :] = np.nan
    return frame, labels


def cheap_fit(frame, labels):
    with patch("ml.gecco_v8.onset.HistGradientBoostingClassifier.fit", return_value=None):
        return OnsetWeightedHGBScorer(list("abcd")).fit(frame, labels)


class OnsetWeightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = weighting_fixture()
        cls.scorer = cheap_fit(cls.frame, cls.labels)

    def test_fixed_masses_with_equal_onset_event_shares_and_uniform_within_each_window(self):
        scorer = self.scorer
        weights = scorer.training_normalized_weight_
        eligible = scorer.training_eligible_mask_
        positive = eligible & (self.labels == 1)
        negative = eligible & (self.labels == 0)
        self.assertAlmostEqual(weights.sum(), 1, places=14)
        np.testing.assert_array_equal(weights[negative], np.full(negative.sum(), .5 / negative.sum()))
        self.assertAlmostEqual(weights[positive].sum(), .5, places=14)
        self.assertEqual(scorer.known_onset_segments_, 4)
        self.assertEqual(scorer.eligible_onset_segments_, 3)
        self.assertEqual(scorer.eligible_onset_rows_, 5)
        expected = np.zeros(len(weights))
        expected[negative] = .5 / negative.sum()
        expected[positive] = .125 / positive.sum()
        for record in scorer.event_weight_audit_:
            a, b = record["start"], record["end_exclusive"]
            rows = np.flatnonzero(positive[a:b]) + a
            if len(rows):
                expected[rows] += .125 / (scorer.fit_events_ * len(rows))
            onset = record["eligible_onset_row_indices"]
            if onset:
                expected[onset] += .25 / (3 * len(onset))
                self.assertAlmostEqual(record["normalized_onset_weight_mass"], .25 / 3)
        np.testing.assert_allclose(weights, expected, rtol=0, atol=1e-16)
        np.testing.assert_array_equal(scorer.training_sample_weight_, weights * int(eligible.sum()))
        self.assertAlmostEqual(sum(r["normalized_point_weight_mass"] for r in scorer.event_weight_audit_), .125)
        self.assertAlmostEqual(sum(r["normalized_event_weight_mass"] for r in scorer.event_weight_audit_), .125)
        self.assertAlmostEqual(sum(r["normalized_onset_weight_mass"] for r in scorer.event_weight_audit_), .25)

    def test_partial_onset_window_never_moves_to_first_three_eligible_rows(self):
        records = {r["start"]: r for r in self.scorer.event_weight_audit_}
        self.assertEqual(records[400]["eligible_onset_row_indices"], [401])
        self.assertEqual(records[400]["onset_window_end_exclusive"], 403)
        self.assertEqual(records[500]["eligible_onset_row_indices"], [])
        self.assertGreater(records[500]["eligible_positive_rows"], 0)
        self.assertEqual(records[500]["normalized_onset_weight_mass"], 0)
        self.assertEqual(records[600]["eligible_onset_row_indices"], [600])
        self.assertEqual(records[600]["onset_window_end_exclusive"], 601)
        self.assertEqual(records[800]["eligible_onset_row_indices"], [800, 801, 802])

    def test_censored_start_and_post_unknown_segments_receive_no_onset_bonus(self):
        records = {r["start"]: r for r in self.scorer.event_weight_audit_}
        for start, reason in ((0, "series_start"), (300, "preceding_unknown_label"), (700, "preceding_unknown_label")):
            self.assertFalse(records[start]["known_onset"])
            self.assertEqual(records[start]["onset_censor_reason"], reason)
            self.assertEqual(records[start]["eligible_onset_row_indices"], [])
            self.assertEqual(records[start]["normalized_onset_weight_mass"], 0)
            self.assertGreater(records[start]["normalized_weight_mass"], 0)
        self.assertTrue((self.scorer.training_normalized_weight_[self.labels == -1] == 0).all())

    def test_no_eligible_onset_redistributes_to_event_uniform_without_shifting(self):
        frame = self.frame.copy()
        labels = np.zeros(len(frame), np.int8)
        labels[:90] = 1
        labels[299] = -1; labels[300:310] = 1
        labels[500:520] = 1  # Known onset, but its original first three rows are unavailable.
        scorer = cheap_fit(frame, labels)
        self.assertEqual(scorer.known_onset_segments_, 1)
        self.assertEqual(scorer.eligible_onset_segments_, 0)
        self.assertTrue(scorer.onset_mass_redistributed_)
        self.assertAlmostEqual(sum(r["normalized_event_weight_mass"] for r in scorer.event_weight_audit_), .375)
        self.assertEqual(sum(r["normalized_onset_weight_mass"] for r in scorer.event_weight_audit_), 0)
        positive = scorer.training_eligible_mask_ & (labels == 1)
        expected = np.zeros(len(labels)); expected[positive] = .125 / positive.sum()
        negative = scorer.training_eligible_mask_ & (labels == 0)
        expected[negative] = .5 / negative.sum()
        for record in scorer.event_weight_audit_:
            a, b = record["start"], record["end_exclusive"]
            rows = np.flatnonzero(positive[a:b]) + a
            if len(rows): expected[rows] += .375 / (scorer.fit_events_ * len(rows))
        np.testing.assert_allclose(scorer.training_normalized_weight_, expected, rtol=0, atol=1e-16)

    def test_references_features_availability_and_hgb_parameters_are_frozen(self):
        with patch("ml.gecco_v7.long_context_hgb.HistGradientBoostingClassifier.fit", return_value=None):
            old = LongContextHGBScorer(list("abcd")).fit(self.frame, self.labels)
        for attribute in ("normal_median_", "normal_iqr_", "noise_floor_", "level_scale_", "reference_supported_",
                          "normal_reference_counts_", "normal_delta_counts_", "positive_delta_counts_", "training_eligible_mask_"):
            np.testing.assert_array_equal(getattr(old, attribute), getattr(self.scorer, attribute))
        for method in ("features", "score_components", "_fit_references", "_frame"):
            self.assertIs(getattr(OnsetWeightedHGBScorer, method), getattr(LongContextHGBScorer, method))
        original, original_available = old.features(self.frame)
        current, current_available = self.scorer.features(self.frame)
        np.testing.assert_array_equal(original, current)
        np.testing.assert_array_equal(original_available, current_available)
        self.assertEqual(old.feature_names_, self.scorer.feature_names_)
        ignored = {"version", "weighting", "onset_weighting"}
        self.assertEqual({k:v for k,v in old.feature_contract_.items() if k not in ignored},
                         {k:v for k,v in self.scorer.feature_contract_.items() if k not in ignored})
        for key, value in HGB_PARAMS.items(): self.assertEqual(self.scorer.model_.get_params()[key], value)

    def test_estimator_sees_only_known_eligible_targets_and_prespecified_weights(self):
        captured = {}
        def fit(estimator, matrix, target, sample_weight):
            captured.update(matrix=matrix, target=target, sample_weight=sample_weight)
            return estimator
        with patch("ml.gecco_v8.onset.HistGradientBoostingClassifier.fit", new=fit):
            scorer = OnsetWeightedHGBScorer(list("abcd")).fit(self.frame, self.labels)
        mask = scorer.training_eligible_mask_
        np.testing.assert_array_equal(captured["target"], self.labels[mask])
        np.testing.assert_array_equal(captured["sample_weight"], scorer.training_sample_weight_[mask])
        self.assertTrue(np.isin(captured["target"], [0, 1]).all())
        np.testing.assert_array_equal(captured["matrix"], scorer.features(self.frame)[0][mask])

    def test_metadata_is_complete_json_safe_and_explicit_about_sample_units(self):
        info = self.scorer.inspection()
        json.dumps(info, allow_nan=False)
        self.assertEqual(info["known_onset_segments"], 4)
        self.assertEqual(info["eligible_known_onset_segments"], 3)
        self.assertEqual(info["eligible_known_onset_rows"], 5)
        self.assertEqual(info["onset_weighting_audit"], info["positive_segment_weights"])
        self.assertEqual(info["original_label_counts"]["unknown"], int((self.labels == -1).sum()))
        self.assertEqual(info["feature_contract"]["onset_weighting"]["window_samples"], ONSET_WINDOW_SAMPLES)
        self.assertEqual(ONSET_WINDOW_SAMPLES, 3)

    def test_unsupported_no_event_empty_and_refit_reset_metadata(self):
        scorer = OnsetWeightedHGBScorer(list("abcd"))
        frame = pd.DataFrame(np.ones((400, 4)), columns=list("abcd"))
        for value, status in ((0, "no_event_training"), (1, "insufficient_normal_reference"), (-1, "insufficient_normal_reference")):
            scorer.fit(frame, np.full(400, value, np.int8))
            self.assertEqual(scorer.fit_status_, status)
            self.assertTrue(np.isnan(scorer.score_components(frame)["long_context"]).all())
            self.assertEqual(scorer.training_normalized_weight_.sum(), 0)
            json.dumps(scorer.inspection(), allow_nan=False)
        scorer.fit(frame.iloc[:0], np.array([], np.int8))
        self.assertEqual(scorer.inspection()["onset_weighting_audit"], [])
        self.assertEqual(scorer.inspection()["known_onset_segments"], 0)
        self.assertEqual(scorer.score_components(frame.iloc[:0])["long_context"].shape, (0,))
        with self.assertRaises(ValueError): scorer.fit(self.frame, self.labels.astype(float))


class OnsetInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = synthetic()
        cls.thread_limit = threadpool_limits(limits=1)
        cls.thread_limit.__enter__()
        cls.scorer = OnsetWeightedHGBScorer(list("abcd")).fit(cls.frame, cls.labels)
        cls.scores = cls.scorer.score_components(cls.frame)["long_context"]

    @classmethod
    def tearDownClass(cls):
        cls.thread_limit.__exit__(None, None, None)

    def test_fit_is_deterministic_with_fixed_estimator_parameters(self):
        repeated = OnsetWeightedHGBScorer(list("abcd")).fit(self.frame, self.labels)
        np.testing.assert_array_equal(repeated.training_normalized_weight_, self.scorer.training_normalized_weight_)
        np.testing.assert_allclose(repeated.score_components(self.frame)["long_context"], self.scores,
                                   rtol=0, atol=0, equal_nan=True)
        self.assertEqual(self.scorer.model_.n_iter_, HGB_PARAMS["max_iter"])
        self.assertFalse(self.scorer.model_.do_early_stopping_)

    def test_score_prefix_and_future_observation_mutation(self):
        for stop in (0, 60, 61, 700, 1441, 2100, 4000):
            values = self.scorer.score_components(self.frame.iloc[:stop])["long_context"]
            np.testing.assert_allclose(values, self.scores[:stop], rtol=0, atol=1e-12, equal_nan=True)
        changed = self.frame.copy(); changed.iloc[2100:] = 1e8; changed.iloc[2101::3] = np.nan
        values = self.scorer.score_components(changed)["long_context"]
        np.testing.assert_allclose(values[:2100], self.scores[:2100], rtol=0, atol=1e-12, equal_nan=True)

    def test_future_labels_are_not_inference_inputs_and_history_is_bounded(self):
        labelled = self.frame.copy()
        labelled["label"] = self.labels
        labelled["EVENT"] = np.arange(len(labelled)) % 2
        first = self.scorer.score_components(labelled)["long_context"]
        labelled.loc[2000:, "label"] = -1; labelled.loc[2000:, "EVENT"] = 999
        second = self.scorer.score_components(labelled)["long_context"]
        np.testing.assert_allclose(first, self.scores, rtol=0, atol=0, equal_nan=True)
        np.testing.assert_allclose(second, self.scores, rtol=0, atol=0, equal_nan=True)
        cropped = self.scorer.score_components(self.frame.iloc[-1441:])["long_context"]
        self.assertAlmostEqual(cropped[-1], self.scores[-1], places=12)

    def test_original_axis_availability_and_unknown_current_observations(self):
        frame = self.frame.iloc[:250].copy()
        frame.iloc[100, 0] = np.nan
        frame.iloc[101, :2] = np.nan
        score = self.scorer.score_components(frame)["long_context"]
        self.assertEqual(score.shape, (250,))
        self.assertTrue(np.isnan(score[:60]).all())
        self.assertTrue(np.isfinite(score[100]))
        self.assertTrue(np.isnan(score[101]))


if __name__ == "__main__":
    unittest.main()
