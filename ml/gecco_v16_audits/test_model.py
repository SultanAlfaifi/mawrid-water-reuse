"""Synthetic-only checks of V16's independent model-audit helpers.

No source readers, artifact bundles, cached examples, actual measurements or
real labels are accessed. One small synthetic IF supplies fitted inference;
the decision classifier is deterministic and never trained in these tests.
"""
from copy import deepcopy
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ml.gecco_v16 import model as production
from ml.gecco_v16_audits import model as audit
from ml.gecco_v16_audits.decisions import context_oracle


CHANNELS = ["a", "b", "c"]


def frame(n=640):
    t = np.arange(n, dtype=float)
    return pd.DataFrame({"a": 3 + np.sin(t / 11) + t / 500,
        "b": 20 + np.cos(t / 17) + .1 * np.sin(t / 3),
        "c": 8 + np.sin(t / 7) + np.cos(t / 23),
        "EVENT": np.full(n, -99), "timestamp": ["ignored metadata"] * n})


class ScoreStub:
    classes_ = np.array([0, 1], np.int8)

    def predict_proba(self, X):
        p = .4 + .1 * np.tanh(X[:, 0].astype(float)) + .02 * X[:, -1]
        return np.column_stack((1 - p, p))


def requests(n):
    a, b = np.zeros(n, np.int8), np.zeros(n, np.int8)
    for start in range(184, n - 5, 16):
        a[start:start + 2] = 1
        b[start + 1:start + 5] = 1
    if n > 380:
        a[380] = -1; b[389] = -1
    return a, b


class AuditModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.x = frame()
        cls.y = np.zeros(len(cls.x), np.int8)
        cls.y[210:222] = 1; cls.y[430:446] = 1; cls.y[300:313] = -1
        cls.x.loc[90, "b"] = np.nan
        matrix, _, _ = audit.if_audit.baseline_input_oracle(cls.x, CHANNELS)
        mask = audit.if_audit.baseline_fit_mask_oracle(cls.x, cls.y, CHANNELS)
        cls.if_model = IsolationForest(**audit.IF_PARAMS).fit(matrix[mask])
        cls.generator = production.fit_generator(CHANNELS, cls.if_model, cls.x, cls.y)

    def checks_pass(self, checks):
        failed = [r for r in checks.records if not r["passed"]]
        self.assertEqual(failed, [], failed[:3])

    def head(self, support=(True, True)):
        head = production.DecisionHeadScorer(CHANNELS, self.if_model)
        head.generator_ = self.generator
        head.model_ = ScoreStub()
        head.request_support_ = {kind: {"supported": flag}
            for kind, flag in zip(("anchor", "recovery"), support)}
        return head

    def test_independent_training_refs_masks_and_if_state_no_fit(self):
        checks = audit.Checks()
        digest = audit.fitted_state_digest(self.if_model)
        with patch.object(IsolationForest, "fit", side_effect=AssertionError("audit must not fit")), \
             patch.object(production, "fit_generator", side_effect=AssertionError("production fit")):
            result = audit.audit_generator(checks, "fit", self.generator, self.x, self.y)
        self.checks_pass(checks)
        self.assertEqual(result["if_fit_rows"], self.if_model._n_samples)
        self.assertEqual(result["if_digest"], digest)
        self.assertEqual(audit.fitted_state_digest(self.if_model), digest)
        self.assertFalse(result["if_fit_mask"][300:327].any())
        self.assertEqual(result["limitations"], audit.LIMITATIONS)

    def test_corrupted_reference_recorded_and_changed_labels_fail(self):
        generator = deepcopy(self.generator)
        generator.normal_median_[0] += .01
        checks = audit.Checks()
        audit.audit_generator(checks, "mutated", generator, self.x, self.y)
        self.assertTrue(any(not r["passed"] for r in checks.records))
        y = self.y.copy(); y[0] = -1
        with self.assertRaisesRegex(ValueError, "fit_label_hash"):
            audit.audit_generator(audit.Checks(), "labels", self.generator, self.x, y)

    def test_if_attachment_and_fit_population_must_match(self):
        generator = deepcopy(self.generator)
        generator.baseline_estimator_.offset_ += .1
        with self.assertRaisesRegex(ValueError, "if_attachment"):
            audit.audit_generator(audit.Checks(), "changed_if", generator, self.x, self.y)
        generator = deepcopy(self.generator)
        generator.baseline_estimator_._n_samples += 1
        generator.baseline_state_hash_at_attachment_ = audit.fitted_state_digest(generator.baseline_estimator_)
        with self.assertRaisesRegex(ValueError, "if_original_fit_count"):
            audit.audit_generator(audit.Checks(), "count", generator, self.x, self.y)

    def test_unsupported_reference_and_original_if_states_are_explicit(self):
        for n in (0, 80, 200):
            x = frame(n); y = np.zeros(n, np.int8)
            generator = production.fit_generator(CHANNELS, None, x, y)
            checks = audit.Checks()
            result = audit.audit_generator(checks, "short", generator, x, y)
            self.checks_pass(checks)
            self.assertLess(result["if_fit_rows"], 256)
            self.assertIsNone(generator.model_)
        generator = production.fit_generator(CHANNELS, None, self.x, self.y)
        with self.assertRaisesRegex(ValueError, "if_support_matches"):
            audit.audit_generator(audit.Checks(), "missing_if", generator, self.x, self.y)

    def test_exact_full_prefix_features_and_gap_ignore_label_metadata(self):
        checks = audit.Checks()
        expected, ev = production.features_gap(self.generator, self.x, 120)
        with patch.object(production, "features_gap", side_effect=AssertionError("new wrapper used")):
            X, available = audit.features_oracle(checks, "features", self.generator, self.x, 120)
        self.checks_pass(checks)
        np.testing.assert_array_equal(X, expected)
        np.testing.assert_array_equal(available, ev)
        self.assertFalse(available[:180].any()); self.assertTrue(available[180])
        changed = self.x.copy(); changed.loc[:119, CHANNELS] = -1e10
        changed["EVENT"] = 1; changed["timestamp"] = "future/label data"
        Y, av = audit.features_oracle(audit.Checks(), "metadata", self.generator, changed, 120)
        np.testing.assert_array_equal(X, Y); np.testing.assert_array_equal(available, av)

    def test_unknown_training_labels_do_not_mask_inference_and_sensor_missing_does(self):
        x = self.x.copy(); x.loc[310, ["a", "b"]] = np.nan
        checks = audit.Checks()
        X, av = audit.features_oracle(checks, "missing", self.generator, x, 0)
        self.checks_pass(checks)
        self.assertTrue(av[305]); self.assertFalse(av[310])
        self.assertTrue(np.isfinite(X).all())
        self.assertEqual(X[310, -1], 0)  # independent IF observed flag

    def test_features_causal_prefix_future_change_and_full_prefix_if(self):
        x = frame(700)
        x.loc[400:, CHANNELS] = [3., 20., 8.]
        allX, allv = audit.features_oracle(audit.Checks(), "all", self.generator, x, 120)
        prefix, pv = audit.features_oracle(audit.Checks(), "prefix", self.generator, x.iloc[:500], 120)
        changed = x.copy(); changed.loc[500:, CHANNELS] = 1e6
        altered, av = audit.features_oracle(audit.Checks(), "future", self.generator, changed, 120)
        np.testing.assert_array_equal(allX[:500], prefix)
        np.testing.assert_array_equal(allX[:500], altered[:500])
        np.testing.assert_array_equal(allv[:500], pv)
        np.testing.assert_array_equal(allv[:500], av[:500])
        _, independent, _, _ = audit.if_audit.baseline_feature_oracle(x.iloc[120:], CHANNELS, self.if_model)
        np.testing.assert_array_equal(allX[120:, -2:], independent)

    def test_exact_provider_returned_even_when_independent_residual_is_one_ulp_away(self):
        original = audit.conditional_audit.conditional_feature_oracle
        def perturbed(values, fitted):
            X = original(values, fitted)
            columns = np.arange(X.shape[1]) % 3 != 2
            X[:, columns] = np.nextafter(X[:, columns], np.float32(np.inf))
            return X
        expected, ev = production.features_gap(self.generator, self.x, 120)
        checks = audit.Checks()
        with patch.object(audit.conditional_audit, "conditional_feature_oracle", side_effect=perturbed):
            actual, av = audit.features_oracle(checks, "one_ulp", self.generator, self.x)
        self.checks_pass(checks)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(av, ev)

    def test_no_ulp_tolerance_for_observed_flags(self):
        original = audit.conditional_audit.conditional_feature_oracle
        def corrupted(values, fitted):
            X = original(values, fitted); X[100, 2] = 0 if X[100, 2] else 1
            return X
        checks = audit.Checks()
        with patch.object(audit.conditional_audit, "conditional_feature_oracle", side_effect=corrupted):
            audit.features_oracle(checks, "bad_mask", self.generator, self.x)
        self.assertTrue(any(not r["passed"] for r in checks.records))

    def test_score_matches_production_without_calling_new_features_or_score(self):
        head = self.head(); a, b = requests(len(self.x))
        expected = head.score(self.x, a, b)
        checks = audit.Checks()
        with patch.object(production, "features_gap", side_effect=AssertionError("new features")), \
             patch.object(production.DecisionHeadScorer, "score", side_effect=AssertionError("new score")), \
             patch.object(production.DecisionHeadScorer, "score_matrix", side_effect=AssertionError("new matrix score")):
            actual = audit.score_oracle(head, self.x, a, b, checks=checks)
        self.checks_pass(checks)
        np.testing.assert_array_equal(actual, expected)
        self.assertTrue(np.isfinite(actual).any())

    def test_all_support_combinations_overlap_and_reset_context(self):
        base, av = production.features_gap(self.generator, self.x)
        a, b = requests(len(self.x)); ctx = context_oracle(a, b)
        self.assertTrue((ctx["anchor_active"] & ctx["recovery_active"] & av).any())
        for support in ((True, True), (True, False), (False, True), (False, False)):
            head = self.head(support)
            actual = audit.score_matrix_oracle(head, base, av, a, b)
            np.testing.assert_array_equal(actual, head.score_matrix(base, av, a, b))
            if not all(support):
                self.assertTrue(np.isnan(actual[ctx["anchor_active"] & ctx["recovery_active"]]).all())
        # Shared sensor history can be sliced while request state resets at a
        # block boundary: a censored alarm does not fabricate an opportunity.
        start = 185
        head = self.head()
        actual = audit.score_matrix_oracle(head, base[start:], av[start:], a[start:], b[start:])
        np.testing.assert_array_equal(actual, head.score_matrix(base[start:], av[start:], a[start:], b[start:]))
        self.assertTrue(np.isnan(actual[:3]).all())

    def test_scores_prefix_future_and_labels_are_causal(self):
        head = self.head(); a, b = requests(len(self.x))
        scores = audit.score_oracle(head, self.x, a, b)
        prefix = audit.score_oracle(head, self.x.iloc[:500], a[:500], b[:500])
        np.testing.assert_array_equal(scores[:500], prefix)
        changed = self.x.copy(); changed.loc[500:, CHANNELS] = -1e8; changed["EVENT"] = 123
        future = audit.score_oracle(head, changed, a, b)
        np.testing.assert_array_equal(scores[:500], future[:500])

    def test_unfitted_head_and_no_active_request_are_unavailable(self):
        head = production.DecisionHeadScorer(CHANNELS, self.if_model)
        a, b = requests(len(self.x))
        self.assertTrue(np.isnan(audit.score_oracle(head, self.x, a, b)).all())
        head = self.head(); head.model_ = None
        self.assertTrue(np.isnan(audit.score_oracle(head, self.x, a, b)).all())
        head = self.head(); a[:] = 0; b[:] = 0
        with patch.object(head.model_, "predict_proba", side_effect=AssertionError("outside request")):
            self.assertTrue(np.isnan(audit.score_oracle(head, self.x, a, b)).all())

    def test_empty_inputs_shape_dtype_and_gap_validation(self):
        for stop in (0, 20, 120):
            checks = audit.Checks()
            X, av = audit.features_oracle(checks, "empty", self.generator, self.x.iloc[:stop])
            self.checks_pass(checks)
            self.assertEqual(X.shape, (stop, len(self.generator.feature_names_)))
            self.assertFalse(av.any())
        for gap in (True, -1, 1.5):
            with self.assertRaises(ValueError): audit.features_oracle(audit.Checks(), "bad", self.generator, self.x, gap)
        for bad in (self.x.drop(columns=["a"]), pd.concat((self.x, self.x[["a"]]), axis=1)):
            with self.assertRaises(ValueError): audit.features_oracle(audit.Checks(), "bad", self.generator, bad)
        head = self.head(); a, b = requests(len(self.x))
        X, av = production.features_gap(self.generator, self.x)
        for badX, badav, aa in ((X.astype(float), av, a), (X, av.astype(int), a), (X, av, a[:-1])):
            with self.assertRaises(ValueError): audit.score_matrix_oracle(head, badX, badav, aa, b)

    def test_audit_imports_no_new_production_and_exposes_numeric_limitations(self):
        source = Path(audit.__file__).read_text()
        imports = [node.module or "" for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name == "ml.gecco_v16" or name.startswith("ml.gecco_v16.") for name in imports))
        self.assertIn("not independently reimplemented", " ".join(audit.LIMITATIONS))
        self.assertIn("exact frozen V12 full-prefix", " ".join(audit.LIMITATIONS))


if __name__ == "__main__":
    unittest.main()
