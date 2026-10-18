"""Independent causal/data-use tests of the recovery detector, not accuracy claims."""
import unittest
import numpy as np
import pandas as pd
from recovery_candidate import RecoveryEventDetector


class RecoveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(127)
        cls.channels = ['a','b','c','d']
        values = np.cumsum(rng.normal(0,.1,(1300,4)),axis=0)
        labels = np.zeros(1300,bool)
        for start in (180,420,700,980):
            labels[start:start+15] = True
            values[start:start+15,1] += 5
        cls.frame = pd.DataFrame(values,columns=cls.channels)
        cls.labels = labels
        cls.models = [RecoveryEventDetector(name,cls.channels).fit(cls.frame,labels)
                      for name in ('shape_invariant','shape_channel_relative')]

    def test_mutating_future_cannot_change_earlier_outputs(self):
        changed = self.frame.copy()
        changed.iloc[800:] = 1e8
        for model in self.models:
            before = model.score_components(self.frame)
            after = model.score_components(changed)
            for component in before:
                np.testing.assert_array_equal(before[component][:800],after[component][:800])

    def test_score_ignores_all_target_and_metadata_columns(self):
        enriched = self.frame.assign(EVENT=self.labels,Time=np.arange(len(self.frame)),future=np.roll(self.labels,-20))
        for model in self.models:
            expected = model.score_components(self.frame)
            actual = model.score_components(enriched)
            for key in expected:np.testing.assert_array_equal(expected[key],actual[key])

    def test_bounded_history_matches_batch(self):
        for model in self.models:
            batch = model.score_components(self.frame)
            for endpoint in (100,200,430,750,1299):
                recent = self.frame.iloc[endpoint-model.max_lookback_:endpoint+1]
                last = model.score_components(recent)
                for key in batch:
                    self.assertAlmostEqual(batch[key][endpoint],last[key][-1],places=14)

    def test_unavailable_shape_does_not_disable_original_baseline(self):
        model = RecoveryEventDetector('shape_invariant',self.channels).fit(self.frame,np.zeros(len(self.frame),bool))
        result = model.score_components(self.frame)
        self.assertIsNone(model.shape_)
        self.assertTrue(np.isfinite(result['baseline'][30:]).all())
        self.assertTrue(np.isnan(result['shape']).all())

    def test_missing_majority_is_unavailable_not_normal_evidence(self):
        missing = self.frame.copy()
        missing.iloc[800:,0:3] = np.nan
        for model in self.models:
            score = model.score_components(missing)
            self.assertTrue(np.isnan(score['shape'][800:]).all())
            self.assertTrue(np.isnan(score['baseline'][800:]).all())

    def test_normal_noise_fit_windows_exclude_event_history(self):
        for model in self.models:
            for row in np.flatnonzero(model.normal_scale_window_mask_):
                self.assertGreaterEqual(row,60)
                self.assertFalse(self.labels[row-60:row+1].any())


if __name__ == '__main__':unittest.main()
