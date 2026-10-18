"""Synthetic numerical regression only; no dataset or saved fitted artifact IO."""
import pickle
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_stream_fidelity import rolling
from ml.gecco_v2.candidates_supervised import build_features


def fixture(n=2500):
    rng = np.random.default_rng(91)
    x = np.round(rng.normal(size=(n, 4)), 2) + [10, 100, 1e6, -5]
    x[500:900, 1] = 99.1; x[1200:1800, 2] = 1000000.3
    x[40:43, 0] = np.nan; x[910:940, 3] = np.nan
    return pd.DataFrame(x, columns=['a','b','c','d'])


class RollingTests(unittest.TestCase):
    def assert_frozen(self, frame):
        channels = ['a','b','c','d']
        expected, eligible, names = build_features(frame, 'baseline15', channels)
        engine = rolling.RollingBaselineFeatures(channels)
        actual, observed = engine.update_frame(frame)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(observed, eligible)
        self.assertEqual(names, engine.feature_names)
        return engine, actual

    def test_full_frozen_features_exact_with_quantization_historical_changes_and_constant_tails(self):
        engine, _ = self.assert_frozen(fixture())
        self.assertTrue(all(len(state.values) == 15 for state in engine.states))

    def test_long_constant_tail_after_large_history_then_return_is_not_relabelled(self):
        rng = np.random.default_rng(204)
        data = np.r_[rng.normal(10, 80, (131, 4)), np.full((2500, 4), 1.3),
                     rng.normal(10, 80, (200, 4)), np.zeros((700, 4))]
        frame = pd.DataFrame(data, columns=['a','b','c','d'])
        _, actual = self.assert_frozen(frame)
        np.testing.assert_array_equal(actual[200:2600, -4:], 0)

    def test_signed_zero_subnormal_large_offset_and_alternating_sign(self):
        n = 2000; i = np.arange(n)
        frame = pd.DataFrame({'a': np.where(i % 2, -0.0, 0.0),
                              'b': np.where(i % 2, -1e-160, 1e-160),
                              'c': 1e12 + np.sin(i) * .01,
                              'd': np.where(i % 3, -1e8, 1e8)})
        self.assert_frozen(frame)

    def test_missing_infinities_and_first_difference_keep_original_eligibility(self):
        frame = fixture(250)
        frame.iloc[60, 1] = np.inf; frame.iloc[80, 2] = -np.inf
        frame.iloc[100:130] = np.nan; frame.iloc[:2, 3] = np.nan
        engine, _ = self.assert_frozen(frame)
        self.assertTrue(all(len(s.values) <= 15 for s in engine.states))

    def test_chunk_invariance_empty_chunk_and_explicit_reset(self):
        frame = fixture(1500); whole = rolling.RollingBaselineFeatures(frame.columns)
        expected, mask = whole.update_frame(frame)
        engine = rolling.RollingBaselineFeatures(frame.columns)
        chunks = [(0,1),(1,14),(14,15),(15,75),(75,76),(76,500),(500,500),(500,1000),(1000,1500)]
        values, observed = zip(*(engine.update_frame(frame.iloc[a:b]) for a,b in chunks))
        np.testing.assert_array_equal(np.concatenate(values), expected)
        np.testing.assert_array_equal(np.concatenate(observed), mask)
        self.assertEqual(pickle.dumps(engine.states), pickle.dumps(whole.states))
        engine.reset(); again, _ = engine.update_frame(frame)
        np.testing.assert_array_equal(again, expected)

    def test_clone_future_independence_and_annotation_isolation(self):
        frame = fixture(300); engine = rolling.RollingBaselineFeatures(frame.columns)
        prefix, _ = engine.update_frame(frame.iloc[:175]); twin = engine.clone()
        mutated = frame.copy(); mutated.iloc[175:] *= 100
        expected, _, _ = build_features(mutated, 'baseline15', list(frame.columns))
        np.testing.assert_array_equal(prefix, expected[:175])
        frame['EVENT'] = 'no targets'; frame['future_label'] = object()
        a, _ = engine.update_frame(frame.iloc[175:]); b, _ = twin.update_frame(frame.iloc[175:])
        np.testing.assert_array_equal(a, b)

    def test_bad_row_and_mid_chunk_exception_roll_back_all_compensators(self):
        frame = fixture(100); engine = rolling.RollingBaselineFeatures(frame.columns)
        engine.update_frame(frame.iloc[:60]); before = pickle.dumps(engine.states)
        row = frame.iloc[60].astype(object); row['d'] = 'bad'
        with self.assertRaises(ValueError): engine.update(row)
        self.assertEqual(pickle.dumps(engine.states), before)
        chunk = frame.iloc[60:80].astype(object); chunk.iloc[11, 3] = 'bad'
        with self.assertRaises(ValueError): engine.update_frame(chunk)
        self.assertEqual(pickle.dumps(engine.states), before)
        actual, _ = engine.update_frame(frame.iloc[60:80])
        expected, _, _ = build_features(frame.iloc[:80], 'baseline15', list(frame.columns))
        np.testing.assert_array_equal(actual, expected[60:])

    def test_state_is_bounded_after_thousands_of_identical_observations(self):
        frame = pd.DataFrame(np.full((5000, 4), 1.3), columns=['a','b','c','d'])
        engine = rolling.RollingBaselineFeatures(frame.columns)
        engine.update_frame(frame.iloc[:100]); size = len(pickle.dumps(engine.states))
        engine.update_frame(frame.iloc[100:])
        self.assertEqual(len(pickle.dumps(engine.states)), size)
        self.assertTrue(all(s.mean.same_count <= 15 and len(s.values) == 15 for s in engine.states))

    def test_fused_operation_is_necessary_for_this_frozen_kernel(self):
        frame = fixture(500)
        expected, _, _ = build_features(frame, 'baseline15', list(frame.columns))
        with patch.object(rolling, '_FMA', side_effect=lambda a,b,c: a*b+c):
            wrong, _ = rolling.RollingBaselineFeatures(frame.columns).update_frame(frame)
        self.assertTrue(np.any(np.isfinite(wrong) & (wrong != expected)))

    def test_unqualified_environment_and_annotation_schema_fail_closed(self):
        with patch.object(rolling.pd, '__version__', 'different'):
            with self.assertRaises(ValueError): rolling.RollingBaselineFeatures(['a'])
        with patch.object(rolling, 'PANDAS_KERNEL_SHA256', 'wrong'):
            with self.assertRaises(ValueError): rolling.RollingBaselineFeatures(['a'])
        for channels in (['EVENT'], ['a','a'], []):
            with self.subTest(channels=channels), self.assertRaises(ValueError):
                rolling.RollingBaselineFeatures(channels)


if __name__ == '__main__': unittest.main()
