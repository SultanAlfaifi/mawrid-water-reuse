import unittest

import numpy as np
import pandas as pd

from candidate import CHANNELS18, CHANNELS19, CONFIGS, NormalizedChangeClassifier


class NormalizedClassifierTests(unittest.TestCase):
    def data(self, channels):
        rng = np.random.default_rng(7)
        frame = pd.DataFrame(rng.normal(size=(1000, len(channels))), columns=channels)
        labels = np.zeros(len(frame), dtype=bool)
        labels[320:350] = True
        labels[600:630] = True
        frame.loc[labels, channels[0]] += 5
        return frame, labels

    def test_six_and_nine_channel_schemas_without_label_features(self):
        for channels in (CHANNELS18, CHANNELS19):
            frame, labels = self.data(channels)
            frame["EVENT"] = labels
            model = NormalizedChangeClassifier(CONFIGS[0]).fit(frame, labels)
            original = model.score(frame)
            frame["EVENT"] = ~labels
            np.testing.assert_array_equal(original, model.score(frame))
            self.assertEqual(model.model_.n_features_in_, len(channels) * 3)

    def test_future_changes_do_not_modify_scores(self):
        frame, labels = self.data(CHANNELS19)
        model = NormalizedChangeClassifier(CONFIGS[0]).fit(frame.iloc[:700], labels[:700])
        expected = model.score(frame.iloc[:800])
        frame.iloc[800:] = 1e6
        np.testing.assert_array_equal(expected, model.score(frame)[:800])

    def test_absolute_level_shift_leaves_normalized_features_unchanged(self):
        frame, labels = self.data(CHANNELS19)
        model = NormalizedChangeClassifier(CONFIGS[0]).fit(frame, labels)
        features, eligible = model.features(frame)
        shifted, shifted_eligible = model.features(frame + 1000)
        np.testing.assert_array_equal(eligible, shifted_eligible)
        np.testing.assert_allclose(features[eligible], shifted[eligible], atol=1e-10, rtol=1e-10)

    def test_missing_observation_invalidates_its_full_history(self):
        frame, labels = self.data(CHANNELS19)
        model = NormalizedChangeClassifier(CONFIGS[0]).fit(frame, labels)
        frame.loc[800, "Tp"] = np.nan
        scores = model.score(frame)
        self.assertTrue(np.isnan(scores[800:861]).all())
        self.assertTrue(np.isfinite(scores[861]))


if __name__ == "__main__":
    unittest.main()
