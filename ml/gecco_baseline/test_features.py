"""Tests for causal feature preparation, including missing-data recovery."""
import unittest
import numpy as np
import pandas as pd
from run_baseline import CHANNELS, WINDOW, feature_frame


class FeatureTests(unittest.TestCase):
    def sample(self, n=90):
        rng = np.random.default_rng(42)
        return pd.DataFrame(rng.normal(size=(n, len(CHANNELS))), columns=CHANNELS)

    def test_changing_the_future_cannot_change_past_features(self):
        raw = self.sample()
        original, valid, _ = feature_frame(raw)
        changed = raw.copy()
        changed.iloc[50:] = 10000
        alternate, alternate_valid, _ = feature_frame(changed)
        np.testing.assert_allclose(original.iloc[:50], alternate.iloc[:50], equal_nan=True)
        np.testing.assert_array_equal(valid[:50], alternate_valid[:50])

    def test_prefix_and_full_stream_agree(self):
        raw = self.sample()
        full, valid, _ = feature_frame(raw)
        prefix, prefix_valid, _ = feature_frame(raw.iloc[:40])
        np.testing.assert_allclose(full.iloc[:40], prefix, equal_nan=True)
        np.testing.assert_array_equal(valid[:40], prefix_valid)

    def test_missing_measurement_requires_full_clean_window_before_recovery(self):
        raw = self.sample()
        raw.loc[30, "Cl"] = np.nan
        _, valid, complete = feature_frame(raw)
        self.assertFalse(complete[30])
        self.assertFalse(valid[:WINDOW - 1].any())
        self.assertTrue(valid[WINDOW - 1:30].all())
        self.assertFalse(valid[30:30 + WINDOW].any())
        self.assertTrue(valid[30 + WINDOW:].all())

    def test_labels_time_and_row_id_are_not_features(self):
        raw = self.sample()
        baseline, _, _ = feature_frame(raw)
        raw["EVENT"] = True
        raw["Time"] = "future"
        raw["row_id"] = -123
        actual, _, _ = feature_frame(raw)
        pd.testing.assert_frame_equal(baseline, actual)
        self.assertEqual(actual.shape[1], 4 * len(CHANNELS))


if __name__ == "__main__":
    unittest.main()
