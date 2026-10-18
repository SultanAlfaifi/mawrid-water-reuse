"""Independent synthetic contracts for past-only normal support."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normal_support import NormalSupportGate, SupportConfig


def fixture():
    x = np.random.default_rng(21).normal(size=(1000, 52))
    normal = np.ones(1000, dtype=bool)
    eligible = np.ones(1000, dtype=bool)
    return x, normal, eligible


class NormalSupportTests(unittest.TestCase):
    def test_geometry_and_deterministic_prototypes(self):
        x, y, e = fixture()
        config = SupportConfig(max_prototypes=101)
        a = NormalSupportGate(config).fit(x, y, e)
        b = NormalSupportGate(config).fit(x, y, e)
        self.assertEqual(a.fit_status_, "fitted")
        self.assertEqual(a.split_index_, 800)
        self.assertEqual(len(a.prototype_source_indices_), 101)
        self.assertTrue(np.all(a.scaler_source_indices_ < 800))
        self.assertTrue(np.all(a.reference_source_indices_ >= 800))
        np.testing.assert_array_equal(a.prototype_source_indices_, b.prototype_source_indices_)
        self.assertEqual(a.threshold_, b.threshold_)

    def test_last_twenty_percent_cannot_change_scaler_or_prototypes(self):
        x, y, e = fixture(); a = NormalSupportGate().fit(x, y, e)
        changed = x.copy(); changed[800:] *= 10
        b = NormalSupportGate().fit(changed, y, e)
        np.testing.assert_array_equal(a.center_, b.center_)
        np.testing.assert_array_equal(a.scale_, b.scale_)
        np.testing.assert_array_equal(a.prototypes_, b.prototypes_)
        self.assertNotEqual(a.threshold_, b.threshold_)

    def test_threshold_uses_suffix_reference_distance_only(self):
        x, y, e = fixture(); a = NormalSupportGate().fit(x, y, e)
        reference = a.distance(x[a.reference_source_indices_])
        self.assertEqual(a.threshold_, float(np.quantile(reference, .95)))
        self.assertAlmostEqual(a.diagnostics_["reference_empirical_support_fraction"], .95)

    def test_clean_normal_history_excludes_events_and_tails(self):
        x, y, e = fixture(); y[180:200] = False; y[850:860] = False
        a = NormalSupportGate().fit(x, y, e)
        self.assertFalse(a.clean_normal_window_mask_[:60].any())
        self.assertFalse(a.clean_normal_window_mask_[180:260].any())
        self.assertFalse(a.clean_normal_window_mask_[850:920].any())
        used = np.r_[a.scaler_source_indices_, a.reference_source_indices_]
        for row in used:
            self.assertTrue(y[row - 60:row + 1].all())

    def test_ineligible_or_missing_fit_rows_never_become_prototypes(self):
        x, y, e = fixture(); e[100:200] = False; x[300:310] = np.nan
        a = NormalSupportGate().fit(x, y, e)
        self.assertFalse(np.isin(a.scaler_source_indices_, np.r_[100:200, 300:310]).any())

    def test_query_future_mutation_and_batching_do_not_change_prefix(self):
        x, y, e = fixture(); a = NormalSupportGate().fit(x, y, e)
        q = x[100:300].copy(); before = a.distance(q)
        altered = q.copy(); altered[100:] = 1e9
        np.testing.assert_array_equal(before[:100], a.distance(altered)[:100])
        np.testing.assert_array_equal(before[:100], a.distance(q[:100]))
        np.testing.assert_array_equal(a.score_support(q), np.array([a.score_support(row[None, :])[0] for row in q]))

    def test_missing_infinite_and_far_queries_are_unknown(self):
        x, y, e = fixture(); a = NormalSupportGate().fit(x, y, e)
        q = np.repeat(x[[100]], 5, axis=0)
        q[1, 0] = np.nan; q[2, 0] = np.inf; q[3] = 1e8; q[4] = 1e308
        np.testing.assert_array_equal(a.score_support(q), [True, False, False, False, False])
        self.assertEqual(a.distance(q)[0], 0)

    def test_constant_training_is_explicit_finite_geometry(self):
        x, y, e = fixture(); x[:] = 3
        a = NormalSupportGate().fit(x, y, e)
        self.assertEqual(a.threshold_, 0)
        np.testing.assert_array_equal(a.score_support(np.array([np.full(52, 3.), np.full(52, 3.001)])), [True, False])

    def test_all_normal_training_is_valid_for_normal_support(self):
        x, y, e = fixture()
        self.assertEqual(NormalSupportGate().fit(x, y, e).fit_status_, "fitted")

    def test_no_normal_or_insufficient_exposure_falls_back_unknown(self):
        x, y, e = fixture()
        for labels, availability, status in [
            (np.zeros(1000, bool), e, "no_normal_training"),
            (y, np.zeros(1000, bool), "insufficient_prototype_normal_rows"),
            (y, np.r_[np.ones(800, bool), np.zeros(200, bool)], "insufficient_reference_normal_rows"),
        ]:
            a = NormalSupportGate().fit(x, labels, availability)
            self.assertEqual(a.fit_status_, status)
            self.assertFalse(a.score_support(x[:3]).any())
            self.assertTrue(np.isinf(a.distance(x[:3])).all())

    def test_invalid_dimensions_masks_and_prefit_use_rejected(self):
        x, y, e = fixture()
        with self.assertRaises(RuntimeError): NormalSupportGate().score_support(x)
        with self.assertRaises(ValueError): NormalSupportGate().fit(x[:, :2], y, e)
        with self.assertRaises(ValueError): NormalSupportGate().fit(x, y.astype(float), e)
        with self.assertRaises(ValueError): NormalSupportGate().fit(x, y, e[:-1])
        with self.assertRaises(ValueError): NormalSupportGate(SupportConfig(reference_quantile=1))
        a = NormalSupportGate().fit(x, y, e)
        with self.assertRaises(ValueError): a.score_support(x[:, :2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
