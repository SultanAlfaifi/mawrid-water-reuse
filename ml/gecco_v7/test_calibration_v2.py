"""Synthetic tests for run02; do not access disclosed or reserved source data."""
import unittest

import numpy as np

from ml.gecco_v7 import calibration as original
from ml.gecco_v7 import calibration_v2 as cal
from ml.gecco_v7.test_calibration import blocks_fixture
from unknown_label_metrics import comparison


class CalibrationV2Tests(unittest.TestCase):
    def test_suppression_cannot_finance_new_false_rescue_minutes(self):
        blocks = blocks_fixture()
        first, _ = original.calibrate(blocks)
        self.assertIsNotNone(first["low_threshold"])
        self.assertIsNotNone(first["high_threshold"])
        selected, trials = cal.calibrate(blocks)
        self.assertIsNotNone(selected["low_threshold"])
        self.assertIsNone(selected["high_threshold"])
        self.assertEqual(selected["events"], 6)
        self.assertEqual(selected["fp"], 0)
        formerly_funded = [t for t in trials if t["low_threshold"] == first["low_threshold"]
                            and t["high_threshold"] == first["high_threshold"] and t["policy"] == first["policy"]]
        self.assertEqual(len(formerly_funded), 1)
        trial = formerly_funded[0]
        self.assertFalse(trial["feasible"])
        self.assertEqual(trial["rescue_added_normal_rows"], 20)
        self.assertEqual(trial["rescue_added_normal_blocks"], [0, 1])
        self.assertIn("rescue_added_known_normal_rows_global", trial["rejection_reasons"])
        self.assertIn("rescue_added_known_normal_rows_in_block", trial["rejection_reasons"])
        # Its final false duration and fragments still beat the reference;
        # rejecting this trial specifically removes cross-path FP credit.
        self.assertLess(trial["fp"], selected["evidence"]["reference"]["fp"])
        self.assertLess(trial["false_runs"], selected["evidence"]["reference"]["false_positive_runs"])

    def test_rescue_without_any_new_known_normal_row_can_be_selected(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["long_scores"][2000:2010] = .1
            b["gate_scores"] = b["long_scores"].copy()
        chosen, trials = cal.calibrate(blocks)
        self.assertIsNotNone(chosen["high_threshold"])
        self.assertEqual(chosen["tp"], 72)
        self.assertEqual(chosen["rescue_added_normal_rows"], 0)
        self.assertEqual(chosen["rescue_added_normal_blocks"], [])
        self.assertTrue(all(t["rescue_added_normal_rows"] == 0 for t in trials if t["feasible"]))

    def test_unknown_guard_preserves_reference_but_does_not_block_raw_rescue(self):
        r = np.array([0, 1, 1, 0, 0, -1], np.int8)
        raw = np.array([.9, .1, .1, .9, .9, .9])
        guarded = np.array([np.nan, np.nan, .1, np.nan, np.nan, .9])
        selected = cal._choice(.5, .8)
        np.testing.assert_array_equal(cal.predict(r, raw, selected, gate_scores=guarded), [1, 1, 1, 1, 1, -1])
        np.testing.assert_array_equal(cal.predict(r, raw, cal._choice(.5), gate_scores=guarded), [0, 1, 1, 0, 0, -1])

    def test_guard_values_cannot_rescue_when_raw_long_score_is_low(self):
        r = np.zeros(10, np.int8)
        raw = np.zeros(10)
        guarded = np.ones(10)
        for policy in cal.POLICIES:
            np.testing.assert_array_equal(cal.predict(r, raw, cal._choice(None, .8, policy), guarded), r)

    def test_lower_grid_uses_guard_scores_upper_grid_uses_raw_scores(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["gate_scores"] = np.where(b["reference"] == 1, .7, np.nan)
        _, trials = cal.calibrate(blocks)
        lower = {t["low_threshold"] for t in trials if t["low_threshold"] is not None}
        upper = {t["high_threshold"] for t in trials if t["high_threshold"] is not None}
        raw = np.concatenate([b["long_scores"] for b in blocks])
        self.assertEqual(lower, {.7})
        self.assertEqual(upper, set(cal._grid(raw, np.linspace(.90, 1, 41), above_max=True)))

    def test_all_unknown_guard_disables_suppression_grid_not_rescue(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["gate_scores"] = np.full(len(b["labels"]), np.nan)
            b["long_scores"][2000:2010] = .1
        chosen, trials = cal.calibrate(blocks)
        self.assertTrue(all(t["low_threshold"] is None for t in trials))
        self.assertIsNotNone(chosen["high_threshold"])
        self.assertGreater(chosen["tp"], chosen["evidence"]["reference"]["tp"])

    def test_unknown_labels_do_not_count_as_false_rescue_rows_or_mask_predictions(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["labels"][2000:2010] = -1
        chosen, _ = cal.calibrate(blocks)
        self.assertIsNotNone(chosen["high_threshold"])
        self.assertEqual(chosen["rescue_added_normal_rows"], 0)
        for b in blocks:
            p = cal.predict(b["reference"], b["long_scores"], chosen)
            self.assertTrue((p[2000:2010] == 1).all())
            np.testing.assert_array_equal(p >= 0, b["reference"] >= 0)

    def test_every_feasible_candidate_preserves_original_constraints(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["long_scores"][2000:2010] = .1
            b["gate_scores"] = b["long_scores"].copy()
            b["gate_scores"][1005] = np.nan
        _, trials = cal.calibrate(blocks)
        labels = np.concatenate([b["labels"] for b in blocks])
        reference = np.concatenate([b["reference"] for b in blocks])
        for trial in (t for t in trials if t["feasible"]):
            parts = [cal.predict(b["reference"], b["long_scores"], trial, b["gate_scores"]) for b in blocks]
            comparisons = [(labels, reference, np.concatenate(parts))] + [(b["labels"], b["reference"], p) for b, p in zip(blocks, parts)]
            for y, r, p in comparisons:
                c = comparison(y, r, p)
                self.assertFalse(c["lost_baseline_event_ids"])
                self.assertTrue(all(d["extra_delay_seconds"] <= 0 for d in c["paired_extra_delays"]))
                self.assertTrue(c["sensor_availability_equal"])
                self.assertLessEqual(c["candidate"]["false_positive_runs"], c["baseline"]["false_positive_runs"])
                self.assertLessEqual(c["candidate"]["fp"], c["baseline"]["fp"])
                self.assertTrue((p[(y == 1) & (r == 1)] == 1).all())
            for b, p in zip(blocks, parts):
                seed = cal._latched_seed(b["reference"], b["gate_scores"], trial["low_threshold"], trial["policy"])
                self.assertFalse(((b["labels"] == 0) & (p == 1) & (seed != 1)).any())

    def test_single_crossblock_event_cannot_supply_two_rescue_owners(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["reference"][:] = 0
            b["long_scores"][:] = .1
        blocks[0]["labels"][3200:] = 1; blocks[1]["labels"][:100] = 1
        blocks[0]["long_scores"][3200:] = .9; blocks[1]["long_scores"][:100] = .9
        selected, trials = cal.calibrate(blocks)
        trials = [t for t in trials if t["high_threshold"] == .9 and t["policy"] == "instant"]
        self.assertEqual(len(trials[0]["rescue_coverage_event_ids"]), 1)
        self.assertEqual(trials[0]["rescue_coverage_blocks"], [0])
        self.assertFalse(trials[0]["feasible"])
        self.assertEqual(selected["decision"], "reference")

    def test_default_guard_exactly_preserves_v1_predictor_and_prefix_causality(self):
        rng = np.random.default_rng(66)
        r = rng.choice([-1, 0, 1], 250).astype(np.int8)
        raw = rng.random(250); raw[::13] = np.nan
        guarded = raw.copy(); guarded[::7] = np.nan
        for policy in cal.POLICIES:
            choice = cal._choice(.3, .8, policy)
            np.testing.assert_array_equal(cal.predict(r, raw, choice), original.predict(r, raw, choice))
            full = cal.predict(r, raw, choice, guarded)
            for stop in (0, 1, 3, 5, 25, 70, 150):
                np.testing.assert_array_equal(cal.predict(r[:stop], raw[:stop], choice, guarded[:stop]), full[:stop])
                raw2, guard2 = raw.copy(), guarded.copy(); raw2[stop:] = 20; guard2[stop:] = -20
                np.testing.assert_array_equal(cal.predict(r, raw2, choice, guard2)[:stop], full[:stop])

    def test_rescue_does_not_extend_after_current_evidence_clears(self):
        r = np.zeros(6, np.int8)
        raw = np.array([1., 1., 1., .1, np.nan, 1.])
        guarded = np.full(6, np.nan)
        for policy in ("2of3", "3of5"):
            p = cal.predict(r, raw, cal._choice(None, .8, policy), guarded)
            self.assertEqual(p[3], 0)
            self.assertEqual(p[4], 0)
            self.assertEqual(p[5], 0)

    def test_invalid_guard_shape_rejected_and_inputs_not_mutated(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["gate_scores"] = b["long_scores"].copy()
        saved = [{k: v.copy() for k, v in b.items() if isinstance(v, np.ndarray)} for b in blocks]
        cal.calibrate(blocks)
        for b, original_block in zip(blocks, saved):
            for k, v in original_block.items():
                np.testing.assert_array_equal(b[k], v)
        with self.assertRaises(ValueError): cal.predict([0, 1], [0., 1.], cal._choice(.3, .8), [1.])
        blocks[0]["gate_scores"] = np.zeros(3)
        with self.assertRaises(ValueError): cal.calibrate(blocks)


if __name__ == "__main__":
    unittest.main()
