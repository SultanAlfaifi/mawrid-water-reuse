"""Independent synthetic checks. Never opens any GECCO CSV or model artifact."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# Parallel tree-probability summation can differ by a few ULPs. This tolerance
# is far below input resolution; equal_nan still requires identical coverage.
SCORE_ATOL = 1e-12


def synthetic(n=900):
    rng = np.random.default_rng(701)
    values = np.cumsum(rng.normal(0, .08, (n, 3)), axis=0) + rng.normal(0, .01, (n, 3))
    labels = np.zeros(n, dtype=np.int8)
    for a, b, ch, amp in [(160, 175, 0, 3), (330, 350, 1, -2), (640, 675, 2, 4)]:
        labels[a:b] = 1
        values[a:b, ch] += amp
    return pd.DataFrame(values, columns=["a", "b", "c"]), labels


class CausalContractMixin:
    """All observed-frame checks run against one already-fitted synthetic model."""

    def test_future_values_and_missingness_cannot_change_prefix(self):
        original = self.detector.score(self.frame)
        for cut in [281, 503, len(self.frame)-139]:
            altered = self.frame.copy()
            altered.iloc[cut:, :] = np.nan
            altered.iloc[cut::2, :] = 1e10
            np.testing.assert_allclose(original[:cut], self.detector.score(altered)[:cut],
                                       rtol=0, atol=SCORE_ATOL, equal_nan=True)

    def test_prefix_only_equals_full_frame(self):
        full = self.detector.score(self.frame)
        for cut in [281, 503, len(self.frame)-139]:
            np.testing.assert_allclose(full[:cut], self.detector.score(self.frame.iloc[:cut]),
                                       rtol=0, atol=SCORE_ATOL, equal_nan=True)

    def test_labels_and_row_identity_never_enter_scoring(self):
        altered = self.frame.copy()
        altered["EVENT"] = self.labels
        altered["Time"] = np.arange(len(altered))[::-1]
        altered["sample_index"] = "ignore me"
        expected = self.detector.score(self.frame)
        np.testing.assert_allclose(expected, self.detector.score(altered), rtol=0, atol=SCORE_ATOL, equal_nan=True)
        altered["EVENT"] = 1 - self.labels
        np.testing.assert_allclose(expected, self.detector.score(altered), rtol=0, atol=SCORE_ATOL, equal_nan=True)

    def test_single_missing_current_channel_never_scores(self):
        for channel in self.frame.columns:
            for bad in [np.nan, np.inf, -np.inf]:
                altered = self.frame.copy()
                altered.loc[450, channel] = bad
                score = self.detector.score(altered)
                self.assertTrue(np.isnan(score[450]), (channel, bad))
                np.testing.assert_allclose(self.detector.score(self.frame)[:450], score[:450],
                                           rtol=0, atol=SCORE_ATOL, equal_nan=True)

    def test_long_missing_interval_cannot_be_filled_from_future(self):
        altered = self.frame.copy()
        altered.iloc[250:500] = np.nan
        score = self.detector.score(altered)
        self.assertTrue(np.isnan(score[250:500]).all())
        self.assertTrue(np.isnan(score[500]))
        self.assertTrue(np.isfinite(score[-1]))

    def test_bounded_history_reproduces_suffix(self):
        # Boundary comparisons include gaps near the farthest history access.
        altered = self.frame.copy()
        altered.iloc[538:540, 0] = np.nan
        max_lookback = int(getattr(self.detector, "max_lookback", getattr(self.detector, "max_lookback_", 0)))
        self.assertGreater(max_lookback, 0)
        cut = max(600, max_lookback+180)
        full = self.detector.score(altered)
        chunk = self.detector.score(altered.iloc[cut-max_lookback:].reset_index(drop=True))
        np.testing.assert_allclose(full[cut:], chunk[max_lookback:], rtol=0, atol=SCORE_ATOL, equal_nan=True)

    def test_fitting_scoring_does_not_modify_inputs(self):
        untouched = self.frame.copy(deep=True)
        labels = self.labels.copy()
        self.detector.score(self.frame)
        pd.testing.assert_frame_equal(self.frame, untouched)
        np.testing.assert_array_equal(self.labels, labels)


class SupervisedContract(CausalContractMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from supervised_candidate import FixedRelativeContextDetector
        cls.frame, cls.labels = synthetic()
        cls.detector = FixedRelativeContextDetector(list(cls.frame.columns)).fit(cls.frame, cls.labels)

    def test_training_weight_totals_are_event_balanced_and_original(self):
        from supervised_candidate import training_weights
        y = np.array([0, 1, 1, 0, 0, 1, 1, 1, 1, 0], dtype=np.int8)
        eligible = np.ones(len(y), dtype=bool)
        eligible[6] = False
        compressed = training_weights(y, eligible)
        weights = np.zeros(len(y)); weights[eligible] = compressed
        self.assertEqual(weights[6], 0.)
        self.assertAlmostEqual(weights[1:3].sum(), weights[5:9].sum())
        self.assertAlmostEqual(weights[y==0].sum(), weights[y==1].sum())

    def test_all_score_components_are_causal(self):
        expected = self.detector.score_components(self.frame)
        altered = self.frame.copy(); altered.iloc[500:] = 1e7
        actual = self.detector.score_components(altered)
        for key in ["relative", "context", "ensemble"]:
            np.testing.assert_allclose(expected[key][:500], actual[key][:500], rtol=0, atol=SCORE_ATOL, equal_nan=True)

    def test_feature_arrays_and_availability_are_causal(self):
        expected = self.detector.features(self.frame)
        altered = self.frame.copy(); altered.iloc[500:] = np.nan
        actual = self.detector.features(altered)
        for before, after in zip(expected, actual):
            np.testing.assert_allclose(before[:500], after[:500], rtol=0, atol=1e-12, equal_nan=True)

    def test_untrainable_status_has_no_silent_normal_predictions(self):
        from supervised_candidate import FixedRelativeContextDetector
        model = FixedRelativeContextDetector(list(self.frame.columns)).fit(self.frame, np.zeros(len(self.frame), dtype=int))
        self.assertEqual(model.fit_status_, "one_class_training")
        self.assertTrue(np.isnan(model.score(self.frame)).all())
        self.assertTrue((model.score_reasons(self.frame) == "one_class_training").all())
        model = FixedRelativeContextDetector(list(self.frame.columns)).fit(self.frame.iloc[:50], self.labels[:50])
        self.assertEqual(model.fit_status_, "insufficient_normal_training")
        self.assertTrue(np.isnan(model.score(self.frame)).all())

    def test_unavailability_reasons_match_score_mask(self):
        altered = self.frame.copy(); altered.iloc[350:440] = np.nan
        score, reason = self.detector.score(altered), self.detector.score_reasons(altered)
        np.testing.assert_array_equal(np.isfinite(score), reason == "available")
        self.assertTrue((reason[350:440] == "current_missing").all())


def adaptive_case(config_id):
    class AdaptiveContract(CausalContractMixin, unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            from adaptive_candidate import AdaptiveChangeDetector
            cls.frame, cls.labels = synthetic(2600 if config_id == "anchored_long720" else 900)
            cls.detector = AdaptiveChangeDetector(config_id, list(cls.frame.columns)).fit(cls.frame, cls.labels)

        def test_training_fit_windows_never_touch_event(self):
            for i in np.flatnonzero(self.detector.fit_normal_window_mask_):
                self.assertGreaterEqual(i, self.detector.max_lookback_)
                self.assertFalse(self.labels[i-self.detector.max_lookback_:i+1].any())

        def test_channel_evidence_is_causal(self):
            expected = self.detector.score_channels(self.frame)
            altered = self.frame.copy(); altered.iloc[500:] = 1e10
            actual = self.detector.score_channels(altered)
            np.testing.assert_allclose(expected[:500], actual[:500], rtol=0, atol=SCORE_ATOL, equal_nan=True)
    AdaptiveContract.__name__ = "AdaptiveContract_" + config_id
    AdaptiveContract.__qualname__ = AdaptiveContract.__name__
    return AdaptiveContract


class AdaptiveReturnProperties(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from adaptive_candidate import AdaptiveChangeDetector
        rng=np.random.default_rng(222)
        train=pd.DataFrame(rng.normal(0,.1,(2200,2)),columns=["a","b"])
        labels=np.zeros(len(train),dtype=bool)
        cls.models={name:AdaptiveChangeDetector(name,["a","b"]).fit(train,labels)
                    for name in ["symmetric_return_gated180","return_gated_channel_median5","anchored_long720"]}

    def test_return_to_unchanged_reference_adds_no_outward_jump(self):
        for direction in [-1,1]:
            x=pd.DataFrame(np.zeros((1300,2)),columns=["a","b"])
            x.loc[900:904,"a"]=direction*10
            for name,model in self.models.items():
                scores=model.score(x)
                delay=2 if name=="return_gated_channel_median5" else 0
                self.assertGreater(np.nanmax(scores[900:905]),0)
                np.testing.assert_allclose(scores[905+delay:1000],0,rtol=0,atol=0)
                # Any median tail is real causal persistence, never forgiven.
                if delay:self.assertGreater(scores[905],0)

    def test_monotonic_ramp_is_finite_causal_evidence_not_a_performance_claim(self):
        x=pd.DataFrame(np.zeros((1500,2)),columns=["a","b"])
        x.loc[900:1199,"a"]=np.linspace(0,10,300)
        for name,model in self.models.items():
            score=model.score(x)
            self.assertTrue(np.isfinite(score[910:1200]).all(),name)
            self.assertTrue((score[910:1200]>0).all(),name)
            altered=x.copy();altered.iloc[1200:]=1e9
            np.testing.assert_allclose(score[:1200],model.score(altered)[:1200],rtol=0,atol=1e-12,equal_nan=True)

    def test_long_anchor_holds_through_253_minute_step_and_returns_to_zero(self):
        x=pd.DataFrame(np.zeros((1500,2)),columns=["a","b"])
        x.loc[900:1152,"a"]=10
        score=self.models["anchored_long720"].score(x)
        self.assertTrue((score[900:1153]>0).all())
        np.testing.assert_allclose(score[1153:1300],0,rtol=0,atol=0)

    def test_median_five_resets_availability_after_missing_current(self):
        x=pd.DataFrame(np.zeros((1300,2)),columns=["a","b"]);x.loc[950,"a"]=np.nan
        score=self.models["return_gated_channel_median5"].score(x)
        self.assertTrue(np.isnan(score[950:955]).all())
        self.assertTrue(np.isfinite(score[955]))


if (HERE / "adaptive_candidate.py").exists():
    for _config in ["symmetric_local30", "symmetric_multiscale180", "symmetric_top2_180",
                    "symmetric_return_gated180", "return_gated_channel_median5", "anchored_long720"]:
        globals()["AdaptiveContract_" + _config] = adaptive_case(_config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
