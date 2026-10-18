"""Synthetic contract tests; this suite never opens any measured data source."""
import unittest

import numpy as np
import pandas as pd

from local_change import LocalChangeScorer, RECIPES, MAX_LOOKBACK_SAMPLES


def synthetic(n=640, channels=6, seed=7):
    rng = np.random.default_rng(seed)
    names = [f"sensor_{j}" for j in range(channels)]
    # Different operating levels and noise scales exercise channel normalization.
    values = rng.normal(size=(n, channels)) * np.arange(1, channels + 1)
    values += 100 * np.arange(channels)
    return pd.DataFrame(values, columns=names)


class LocalChangeTests(unittest.TestCase):
    def setUp(self):
        self.train = synthetic()
        self.channels = list(self.train.columns)
        self.model = LocalChangeScorer(self.channels).fit(self.train, np.zeros(len(self.train), bool))

    def assert_scores_equal(self, left, right):
        self.assertEqual(set(left), set(RECIPES))
        for recipe in RECIPES:
            np.testing.assert_allclose(left[recipe], right[recipe], rtol=1e-12, atol=1e-12,
                                       equal_nan=True, err_msg=recipe)

    def test_prefix_invariance_for_independent_score_calls(self):
        frame = synthetic(400, seed=13)
        whole = self.model.score_components(frame)
        for cut in (1, 29, 30, 35, 90, 200, 399):
            prefix = self.model.score_components(frame.iloc[:cut])
            self.assert_scores_equal(prefix, {k: v[:cut] for k, v in whole.items()})

    def test_future_mutation_cannot_change_past_scores(self):
        frame = synthetic(300, seed=19)
        original = self.model.score_components(frame)
        changed = frame.copy()
        changed.iloc[180:] = 1e9
        changed.iloc[205:215] = np.nan
        actual = self.model.score_components(changed)
        self.assert_scores_equal({k: v[:180] for k, v in original.items()},
                                 {k: v[:180] for k, v in actual.items()})

    def test_bound_is_exact_and_old_history_cannot_change_score(self):
        self.assertEqual(MAX_LOOKBACK_SAMPLES, 74)
        self.assertLessEqual(self.model.max_lookback, 90)
        frame = synthetic(300, seed=21)
        full = self.model.score_components(frame)
        t = 240
        cropped = self.model.score_components(frame.iloc[t - 74:t + 1])
        self.assert_scores_equal({k: v[t:t + 1] for k, v in full.items()},
                                 {k: v[-1:] for k, v in cropped.items()})
        mutated = frame.copy()
        mutated.iloc[:t - 74] = np.nan
        actual = self.model.score_components(mutated)
        self.assert_scores_equal({k: v[t:] for k, v in full.items()},
                                 {k: v[t:] for k, v in actual.items()})

    def test_training_masks_cover_all_feature_history(self):
        y = np.zeros(len(self.train), bool)
        y[155:175] = True
        y[430:434] = True
        model = LocalChangeScorer(self.channels).fit(self.train, y)
        for index in np.flatnonzero(model.normal_floor_window_mask_):
            self.assertGreaterEqual(index, 60)
            self.assertFalse(y[index - 60:index + 1].any())
        for recipe, mask in model.normal_tail_window_masks_.items():
            history = 74 if recipe == "sustained" else 60
            for index in np.flatnonzero(mask):
                self.assertGreaterEqual(index, history)
                self.assertFalse(y[index - history:index + 1].any())
        # Mutate only labeled anomalies: none of the fitted normal scales may move.
        changed = self.train.copy()
        changed.loc[y] = 1e12
        other = LocalChangeScorer(self.channels).fit(changed, y)
        np.testing.assert_array_equal(model.noise_floor_, other.noise_floor_)
        for recipe in RECIPES:
            np.testing.assert_allclose(model.channel_tail_scales_[recipe],
                                       other.channel_tail_scales_[recipe], rtol=1e-12, atol=1e-12)

    def test_positive_rescaling_preserves_scores(self):
        scales = np.array([.1, 10., .001, 3., 100., .5])
        scaled = LocalChangeScorer(self.channels).fit(self.train * scales,
                                                      np.zeros(len(self.train), bool))
        frame = synthetic(200, seed=51)
        self.assert_scores_equal(self.model.score_components(frame),
                                 scaled.score_components(frame * scales))
        np.testing.assert_allclose(scaled.noise_floor_, self.model.noise_floor_ * scales,
                                   rtol=1e-11)

    def test_quantized_and_constant_training_have_positive_finite_floors(self):
        t = np.arange(320)
        frame = pd.DataFrame({"constant": np.full(320, 7.), "quantized": (t % 4) * .25})
        model = LocalChangeScorer(frame.columns).fit(frame, np.zeros(320, bool))
        self.assertTrue(np.all(np.isfinite(model.noise_floor_)))
        self.assertTrue(np.all(model.noise_floor_ > 0))
        actual = model.score_components(frame)
        for score in actual.values():
            self.assertTrue(np.isfinite(score[74:]).all())
            self.assertFalse(np.isinf(score).any())
        event = frame.copy()
        event.iloc[200:220, 0] += 1
        changed = model.score_components(event)
        self.assertGreater(changed["level"][200], actual["level"][200])
        self.assertTrue(np.isfinite(changed["sustained"][210]))

    def test_warmup_and_majority_missing_are_unavailable(self):
        frame = synthetic(200, seed=33)
        scores = self.model.score_components(frame)
        self.assertTrue(np.isnan(scores["level"][:30]).all())
        self.assertTrue(np.isnan(scores["jump"][:30]).all())
        self.assertTrue(np.isnan(scores["sustained"][:34]).all())
        self.assertTrue(np.isfinite(scores["level"][30:]).all())
        self.assertTrue(np.isfinite(scores["jump"][30:]).all())
        self.assertTrue(np.isfinite(scores["sustained"][34:]).all())
        frame.iloc[100:120, :3] = np.nan  # Exactly half remains observable.
        frame.iloc[140:150, :4] = np.inf  # Less than half remains observable.
        masked = self.model.score_components(frame)
        for score in masked.values():
            self.assertTrue(np.isfinite(score[110:120]).all())
            self.assertTrue(np.isnan(score[140:150]).all())
            self.assertTrue(np.isfinite(score[180:]).all())

    def test_current_missing_is_never_filled_and_recovers(self):
        frame = synthetic(180, seed=44)
        frame.iloc[100] = np.nan
        scores = self.model.score_components(frame)
        for score in scores.values():
            self.assertTrue(np.isnan(score[100]))
            self.assertTrue(np.isfinite(score[120:]).all())
        self.assertTrue(np.isfinite(scores["level"][101]))
        self.assertTrue(np.isnan(scores["jump"][101]))
        self.assertTrue(np.isnan(scores["jump"][105]))
        self.assertTrue(np.isnan(scores["sustained"][100:105]).all())
        self.assertTrue(np.isfinite(scores["sustained"][105]))

    def test_signed_accumulation_rewards_persistent_over_alternating_change(self):
        # A constant training channel makes the sign comparison unambiguous.
        train = pd.DataFrame({"x": np.zeros(300)})
        model = LocalChangeScorer(["x"]).fit(train, np.zeros(300, bool))
        persistent = pd.DataFrame({"x": np.r_[np.zeros(100), np.full(20, 1.), np.zeros(20)]})
        alternating = persistent.copy()
        alternating.iloc[100:120, 0] = np.tile([1., -1.], 10)
        sustained = model.score_components(persistent)["sustained"]
        alternating_score = model.score_components(alternating)["sustained"]
        self.assertGreater(sustained[114], 8 * alternating_score[114])
        self.assertLessEqual(np.nanmax(sustained), 8 * np.sqrt(15) + 1e-12)

    def test_long_step_return_is_exposed_rather_than_hidden(self):
        train = pd.DataFrame({"x": np.zeros(300)})
        model = LocalChangeScorer(["x"]).fit(train, np.zeros(300, bool))
        frame = pd.DataFrame({"x": np.r_[np.zeros(100), np.ones(100), np.zeros(100)]})
        scores = model.score_components(frame)
        self.assertGreater(scores["level"][100], 0)
        self.assertEqual(scores["level"][180], 0)  # Reference has adapted.
        self.assertGreater(scores["level"][200], 0)  # Return can look anomalous.
        self.assertGreater(scores["jump"][200], 0)

    def test_score_ignores_event_and_metadata_columns(self):
        frame = synthetic(200, seed=67)
        expected = self.model.score_components(frame)
        frame["EVENT"] = np.arange(len(frame)) % 2
        frame["future_metadata"] = "must not be used"
        self.assert_scores_equal(expected, self.model.score_components(frame))

    def test_no_normal_training_returns_unavailable(self):
        model = LocalChangeScorer(self.channels).fit(self.train, np.ones(len(self.train), bool))
        self.assertEqual(model.fit_status_, "insufficient_normal_training")
        for score in model.score_components(self.train).values():
            self.assertTrue(np.isnan(score).all())

    def test_input_contract_and_empty_frame(self):
        with self.assertRaises(ValueError):
            LocalChangeScorer([])
        with self.assertRaises(ValueError):
            LocalChangeScorer(["x", "x"])
        with self.assertRaises(RuntimeError):
            LocalChangeScorer(self.channels).score_components(self.train)
        for bad in (np.zeros(3, bool), np.full(len(self.train), 2),
                    np.zeros(len(self.train), float)):
            with self.assertRaises(ValueError):
                LocalChangeScorer(self.channels).fit(self.train, bad)
        empty = self.model.score_components(self.train.iloc[:0])
        self.assertTrue(all(v.shape == (0,) for v in empty.values()))


if __name__ == "__main__":
    unittest.main()
