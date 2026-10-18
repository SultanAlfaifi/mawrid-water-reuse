"""Synthetic-only independent-oracle checks; production imports live here only."""
from itertools import product
from pathlib import Path
import ast
from unittest import TestCase, main

import numpy as np

from ml.gecco_v16_audits import decisions as oracle
from ml.gecco_v16 import decisions as production


class DecisionOracleTests(TestCase):
    def assert_equivalent(self, left, right):
        if isinstance(left, np.ndarray):
            self.assertEqual(left.dtype, right.dtype)
            if left.dtype.kind == "f":
                np.testing.assert_allclose(left, right, rtol=0, atol=1e-12)
            else:
                np.testing.assert_array_equal(left, right)
        elif isinstance(left, dict):
            self.assertEqual(set(left), set(right))
            for key in left:
                self.assert_equivalent(left[key], right[key])
        elif isinstance(left, list):
            self.assertEqual(len(left), len(right))
            for a, b in zip(left, right):
                self.assert_equivalent(a, b)
        elif isinstance(left, (float, np.floating)):
            self.assertAlmostEqual(left, right, delta=1e-12)
        else:
            self.assertEqual(left, right)

    def weights(self, y, available, folds, anchor, recovery):
        args = (np.asarray(y, np.int8), np.asarray(available, bool), np.asarray(folds, np.int64),
                np.asarray(anchor, np.int64), np.asarray(recovery, np.int64))
        actual = oracle.weight_oracle(*args)
        self.assert_equivalent(actual, production.weights(*args))
        return actual

    def test_auditor_has_no_production_imports_or_io(self):
        tree = ast.parse(Path(oracle.__file__).read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ("open", "eval", "exec", "__import__"))
        self.assertEqual(imports, ["__future__", "numpy"])

    def test_exhaustive_short_context_axes(self):
        # All9 paired ternary states, lengths0..4:7,381 complete synthetic axes.
        states = tuple(product((-1, 0, 1), repeat=2))
        for n in range(5):
            for pairs in product(states, repeat=n):
                a = np.array([p[0] for p in pairs], np.int8)
                b = np.array([p[1] for p in pairs], np.int8)
                self.assert_equivalent(oracle.context_oracle(a, b), production.contexts(a, b))

    def test_literal_ownership_overlap_and_ineligible_new_start(self):
        result = oracle.context_oracle(np.array([0, 1, 0, 1, 1]), np.array([0, 0, 1, 1, 0]))
        np.testing.assert_array_equal(result["anchor_origins"], [-1, -1, 2, 2, -1])
        np.testing.assert_array_equal(result["recovery_origins"], [-1, 1, 1, -1, -1])
        np.testing.assert_array_equal(result["matrix"][2, 4:], [1, 0, 1, .5])

    def test_censored_unknown_and_postclear_context(self):
        result = oracle.context_oracle(np.array([1, 0, 1, 0, 0, -1, 1, 0, 1]),
                                       np.array([0, 0, 0, 0, 0, 0, 0, -1, 0]))
        np.testing.assert_array_equal(result["recovery_origins"], [-1, -1, 2, 2, 2, -1, -1, -1, 8])
        self.assertFalse(result["anchor_active"].any())
        censored = oracle.context_oracle(np.zeros(5, int), np.array([1, 1, -1, 1, 1]))
        self.assertFalse(censored["active"].any())

    def test_context_prefix_and_future_mutation(self):
        rng = np.random.default_rng(1601)
        a = rng.choice([-1, 0, 1], 120).astype(np.int8)
        b = rng.choice([-1, 0, 1], 120).astype(np.int8)
        full = oracle.context_oracle(a, b)
        for stop in (0, 1, 2, 3, 27, 80, 120):
            part = oracle.context_oracle(a[:stop], b[:stop])
            for key in ("matrix", "active", "anchor_origins", "recovery_origins"):
                np.testing.assert_array_equal(part[key], full[key][:stop])
        aa, bb = a.copy(), b.copy(); aa[80:] = 1; bb[80:] = 0
        mutated = oracle.context_oracle(aa, bb)
        np.testing.assert_array_equal(full["matrix"][:80], mutated["matrix"][:80])

    def test_overlap_sums_contributions_on_unique_rows(self):
        result = self.weights([0, 0, 1, 1, 1], [1] * 5, [0] * 5,
                              [0, 0, 0, -1, -1], [-1, 1, 1, 1, -1])
        np.testing.assert_allclose(result["normalized"], [.125, .375, .375, .125, 0], rtol=0, atol=0)
        self.assertEqual(result["summary"]["eligible_rows"], 4)
        self.assertEqual(result["summary"]["opportunities"], 2)
        self.assertEqual(result["summary"]["normal_weight_mass"], .5)
        self.assertEqual(result["summary"]["positive_weight_mass"], .5)
        np.testing.assert_array_equal(result["sample"], result["normalized"] * 4)

    def test_original_event_id_spans_teacher_boundary(self):
        result = self.weights([0, 1, 1, 1, 1, 0], [1] * 6, [0, 0, 0, 1, 1, 1],
                              [-1, 1, 1, 3, 3, -1], [-1] * 6)
        np.testing.assert_array_equal(result["event_ids"], [0, 1, 1, 1, 1, 0])
        self.assertEqual(result["summary"]["positive_events"], 1)
        self.assertEqual(result["event_records"][0]["fold_ids"], [0, 1])
        self.assertTrue(result["summary"]["fit_checks"]["positive_examples_in_two_forecast_folds"])
        self.assertFalse(result["summary"]["fit_checks"]["at_least_two_positive_segments"])
        self.assertEqual(result["summary"]["normalized_weight_sum"], .5)

    def test_unknown_splits_label_segments_without_removing_rows(self):
        result = self.weights([0, 1, -1, 1, 0], [1] * 5, [0] * 5,
                              [0, 0, 0, -1, -1], [-1, -1, -1, 3, 3])
        np.testing.assert_array_equal(result["event_ids"], [0, 1, 0, 2, 0])
        self.assertEqual(result["normalized"][2], 0)
        self.assertTrue(result["event_records"][0]["known_onset"])
        self.assertFalse(result["event_records"][1]["known_onset"])
        self.assertEqual(result["summary"]["unknown_weight_mass"], 0)

    def test_unavailable_rows_not_shifted_or_replaced(self):
        result = self.weights([0, 1, 1, 1, 0, 0], [1, 0, 0, 1, 1, 1], [0] * 6,
                              [0, 0, 0, -1, 4, 4], [-1] * 6)
        self.assertEqual(result["summary"]["positive_events"], 0)
        self.assertEqual(result["normalized"][3], 0)
        self.assertEqual(result["summary"]["positive_weight_mass"], 0)
        self.assertEqual(result["summary"]["normal_weight_mass"], .5)
        self.assertFalse(result["summary"]["fit_supported"])

    def test_minimum_unique_normal_rows_and_two_positive_folds(self):
        n = 280
        y = np.zeros(n, np.int8); y[4:7] = 1; y[144:147] = 1
        folds = np.r_[np.zeros(140, int), np.ones(140, int)]
        anchor = np.full(n, -1)
        for left in (0, 140):
            for start in range(left, left + 138, 3):
                anchor[start:start + 3] = start
        result = self.weights(y, np.ones(n, bool), folds, anchor, np.full(n, -1))
        self.assertTrue(result["summary"]["fit_supported"])
        self.assertTrue(result["summary"]["request_support"]["anchor"]["supported"])
        self.assertFalse(result["summary"]["request_support"]["recovery"]["supported"])
        observed = np.zeros(n, bool)
        normal = np.flatnonzero((y == 0) & (anchor >= 0))
        observed[normal[:127]] = True; observed[y == 1] = True
        insufficient = self.weights(y, observed, folds, anchor, np.full(n, -1))
        self.assertFalse(insufficient["summary"]["fit_checks"]["at_least_128_normal_rows"])
        self.assertEqual(insufficient["summary"]["normal_rows"], 127)

    def test_per_type_support_does_not_borrow_opposite_type_examples(self):
        result = self.weights([0, 0, 0, 1, 1, 1], [1] * 6, [0] * 6,
                              [0, 0, 0, -1, -1, -1], [-1, -1, -1, 3, 3, 3])
        support = result["summary"]["request_support"]
        self.assertFalse(support["anchor"]["supported"])
        self.assertFalse(support["recovery"]["supported"])
        self.assertEqual(support["anchor"]["normal_opportunities"], 1)
        self.assertEqual(support["recovery"]["positive_events"], 1)

    def test_randomized_original_axis_weight_records(self):
        rng = np.random.default_rng(1626)
        for iteration in range(100):
            n = 60
            y = rng.choice([-1, 0, 1], n, p=[.12, .55, .33]).astype(np.int8)
            available = rng.random(n) > .2
            folds = np.repeat(np.arange(3), 20)
            anchor, recovery = np.full(n, -1), np.full(n, -1)
            for start in (0, 20, 40):
                a = rng.choice([-1, 0, 1], 20).astype(np.int8)
                b = rng.choice([-1, 0, 1], 20).astype(np.int8)
                c = oracle.context_oracle(a, b)
                for target, key in ((anchor, "anchor_origins"), (recovery, "recovery_origins")):
                    values = c[key]
                    target[start:start + 20] = np.where(values >= 0, values + start, -1)
            with self.subTest(iteration=iteration):
                self.weights(y, available, folds, anchor, recovery)

    def test_empty_and_unforecast_rows(self):
        result = self.weights([], [], [], [], [])
        self.assertEqual(result["summary"]["normalized_weight_sum"], 0)
        self.assertFalse(result["summary"]["fit_supported"])
        result = self.weights([0, 1, 1, 0], [1] * 4, [-1] * 4, [-1] * 4, [-1] * 4)
        np.testing.assert_array_equal(result["event_ids"], [0, 1, 1, 0])
        self.assertFalse(result["eligible"].any())

    def test_validation_no_future_crossfold_or_resurrected_opportunities(self):
        valid = (np.array([0, 1, 0, 1]), np.ones(4, bool), np.zeros(4, int), np.full(4, -1), np.full(4, -1))
        bad = []
        a = list(valid); a[3] = np.array([-1, 2, -1, -1]); bad.append(a)
        a = list(valid); a[3] = np.array([0, -1, 0, -1]); bad.append(a)
        a = list(valid); a[3] = np.array([0, 0, 0, 0]); bad.append(a)
        a = list(valid); a[2] = np.array([0, 1, 1, 1]); a[3] = np.array([0, 0, -1, -1]); bad.append(a)
        a = list(valid); a[2] = np.full(4, -1); a[3] = np.array([0, 0, -1, -1]); bad.append(a)
        a = list(valid); a[1] = np.ones(4, int); bad.append(a)
        for args in bad:
            with self.assertRaises(ValueError):
                oracle.weight_oracle(*args)
        for a, b in (([0., 1.], [0, 1]), ([False, True], [0, 1]), ([0, 2], [0, 1]), ([0], [0, 1])):
            with self.assertRaises(ValueError):
                oracle.context_oracle(np.asarray(a), np.asarray(b))


if __name__ == "__main__":
    main()
