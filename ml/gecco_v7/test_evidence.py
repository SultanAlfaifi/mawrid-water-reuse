import unittest

import numpy as np

from ml.gecco_v7.evidence import separate_scores


class EvidenceTests(unittest.TestCase):
    def test_fixed_boundary_is_complementary_on_finite_current_local_scores(self):
        raw = np.array([.1, .2, .3, .4, .5])
        local = {"level": np.array([0, 1, 1.000001, 0, 0]),
                 "jump": np.array([0, 1, 0, 2, 0]),
                 "sustained": np.array([0, 1, 0, 0, 3])}
        result = separate_scores(local, raw)
        np.testing.assert_array_equal(result["guarded_long_context"], [.1, .2, np.nan, np.nan, np.nan])
        np.testing.assert_array_equal(result["rescue_long_context"], [np.nan, np.nan, .3, .4, .5])

    def test_any_unknown_local_or_nonfinite_long_score_disables_both(self):
        raw = np.array([.1, .2, .3, np.nan, np.inf, -np.inf])
        local = {"level": np.array([np.nan, 2, 2, 2, 2, 2]),
                 "jump": np.array([2, np.inf, 2, 2, 2, 2]),
                 "sustained": np.array([2, 2, -np.inf, 2, 2, 2])}
        self.assertTrue(all(np.isnan(v).all() for v in separate_scores(local, raw).values()))

    def test_prefix_future_and_previous_rows_have_no_effect(self):
        raw = np.arange(12, dtype=float)
        local = {key: np.arange(12, dtype=float) / 4 for key in ("level", "jump", "sustained")}
        whole = separate_scores(local, raw)
        for stop in (0, 1, 4, 7, 12):
            prefix = separate_scores({k: v[:stop] for k, v in local.items()}, raw[:stop])
            for key in whole:
                np.testing.assert_array_equal(prefix[key], whole[key][:stop])
        isolated = separate_scores({k: v[7:8] for k, v in local.items()}, raw[7:8])
        for key in whole:
            np.testing.assert_array_equal(isolated[key], whole[key][7:8])

    def test_shape_validation_empty_inputs_and_no_mutation(self):
        local = {key: np.ones(3) for key in ("level", "jump", "sustained")}
        raw = np.arange(3, dtype=float)
        saved = {key: value.copy() for key, value in local.items()}
        separate_scores(local, raw)
        for key in local:
            np.testing.assert_array_equal(local[key], saved[key])
        np.testing.assert_array_equal(raw, np.arange(3))
        self.assertTrue(all(len(v) == 0 for v in separate_scores({k: [] for k in local}, []).values()))
        with self.assertRaises(ValueError): separate_scores({}, raw)
        with self.assertRaises(ValueError): separate_scores(local, np.zeros((3, 1)))
        with self.assertRaises(ValueError): separate_scores({**local, "jump": [1]}, raw)


if __name__ == "__main__":
    unittest.main()
