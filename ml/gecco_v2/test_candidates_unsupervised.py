import unittest

import numpy as np
import pandas as pd

from candidates_unsupervised import CHANNELS, CausalChangeDetector, causal_predict


class CausalChangeTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(12)
        self.data = pd.DataFrame(rng.normal(size=(800, len(CHANNELS))), columns=CHANNELS)
        self.config = {"window": 15, "method": "robust", "aggregate": "max"}

    def test_future_values_cannot_change_past_scores(self):
        model = CausalChangeDetector(self.config).fit(self.data.iloc[:400], np.ones(400, dtype=bool))
        early = model.score(self.data.iloc[:650])
        perturbed = self.data.copy()
        perturbed.iloc[650:] = 1e8
        np.testing.assert_allclose(early, model.score(perturbed)[:650], equal_nan=True)

    def test_event_windows_excluded_from_floor_fit(self):
        mask = np.ones(len(self.data), dtype=bool)
        mask[400:430] = False
        perturbed = self.data.copy()
        perturbed.iloc[400:430] = 1e8
        first = CausalChangeDetector(self.config).fit(self.data, mask)
        second = CausalChangeDetector(self.config).fit(perturbed, mask)
        np.testing.assert_allclose(first.floor_, second.floor_)
        np.testing.assert_allclose(first.delta_floor_, second.delta_floor_)

    def test_quantized_constant_channels_remain_finite_and_detect_change(self):
        data = pd.DataFrame(np.ones((500, 9)), columns=CHANNELS)
        model = CausalChangeDetector(self.config).fit(data, np.ones(500, dtype=bool))
        changed = data.copy()
        changed.loc[400, "Cl"] = 2
        score = model.score(changed)
        self.assertEqual(score[399], 0)
        self.assertTrue(np.isfinite(score[400]))
        self.assertGreater(score[400], 1)

    def test_missing_resets_full_history_eligibility(self):
        model = CausalChangeDetector(self.config).fit(self.data, np.ones(800, dtype=bool))
        changed = self.data.copy()
        changed.loc[500, "Cl"] = np.nan
        scores = model.score(changed)
        self.assertTrue(np.isnan(scores[500:531]).all())
        self.assertTrue(np.isfinite(scores[531]))

    def test_persistence_is_causal_and_unavailability_breaks_the_run(self):
        scores = [0, 2, 2, np.nan, 2, 2, 0, 2]
        self.assertEqual(causal_predict(scores, 1, 2).tolist(), [0, 0, 1, -1, 0, 1, 0, 0])

    def test_m_of_n_includes_causal_alarm_tails_and_resets_on_missing(self):
        scores = [2, 0, 2, 0, 0, np.nan, 2, 0]
        self.assertEqual(causal_predict(scores, 1, "2of3").tolist(), [0, 0, 1, 0, 0, -1, 0, 0])
        self.assertEqual(causal_predict([2, 2, 0, 0], 1, "2of3").tolist(), [0, 1, 1, 0])

    def test_iforest_all_missing_returns_unavailable_without_predicting(self):
        config = {"window": 15, "method": "iforest", "aggregate": "max"}
        model = CausalChangeDetector(config).fit(self.data, np.ones(800, dtype=bool))
        missing = self.data.iloc[:100].copy()
        missing.loc[:, :] = np.nan
        self.assertTrue(np.isnan(model.score(missing)).all())

    def test_explicit_default_schema_preserves_scores_and_floors(self):
        normal = np.ones(len(self.data), dtype=bool)
        default = CausalChangeDetector(self.config).fit(self.data, normal)
        explicit = CausalChangeDetector(self.config, channels=CHANNELS).fit(self.data, normal)
        np.testing.assert_array_equal(default.floor_, explicit.floor_)
        np.testing.assert_array_equal(default.delta_floor_, explicit.delta_floor_)
        np.testing.assert_allclose(default.score(self.data), explicit.score(self.data), equal_nan=True)
        self.assertEqual(default.channels, CHANNELS)

    def test_six_channel_synthetic_iforest_schema_and_causality(self):
        channels = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
        rng = np.random.default_rng(91)
        data = pd.DataFrame(rng.normal(size=(800, 6)), columns=channels)
        config = {"window": 30, "method": "iforest", "aggregate": "max", "channels": channels}
        model = CausalChangeDetector(config).fit(data.iloc[:650], np.ones(650, dtype=bool))
        prefix = model.score(data.iloc[:700])
        perturbed = data.copy()
        perturbed.iloc[700:] = 1e8
        np.testing.assert_allclose(prefix, model.score(perturbed)[:700], equal_nan=True)
        self.assertEqual(model.floor_.shape, (6,))
        self.assertEqual(model.model.n_features_in_, 18)
        self.assertEqual(model.score_channels(data).columns.tolist(), channels)
        self.assertEqual(model.max_lookback, 60)

    def test_constructor_schema_overrides_config_without_mutating_it(self):
        channels = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
        config = {**self.config, "channels": CHANNELS}
        model = CausalChangeDetector(config, channels=channels)
        self.assertEqual(model.channels, channels)
        self.assertEqual(config["channels"], CHANNELS)


if __name__ == "__main__":
    unittest.main()
