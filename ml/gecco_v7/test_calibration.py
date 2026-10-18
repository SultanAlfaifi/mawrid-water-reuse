"""Synthetic tests only: no source measurements or labels are opened."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

_SPEC = importlib.util.spec_from_file_location("v7_calibration_under_test", Path(__file__).with_name("calibration.py"))
cal = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cal)
from unknown_label_metrics import stats, comparison
from latched_suppression import predict as old_latched_predict


def blocks_fixture():
    blocks = []
    for i in range(2):
        y = np.zeros(3300, np.int8)
        reference = np.zeros(len(y), np.int8)
        scores = np.full(len(y), .1)
        for start in (200, 500, 800):
            y[start:start + 12] = 1
            reference[start + 2:start + 5] = 1
            scores[start:start + 12] = .9
        # The upper rescue alone spends additional FP budget; a joint decision
        # can fund it by removing two distinct low-score reference false alarms.
        reference[1000:1020] = 1
        reference[1200:1220] = 1
        scores[1000:1020] = .2
        scores[1200:1220] = .2
        scores[2000:2010] = .9
        blocks.append({"labels": y, "reference": reference, "long_scores": scores,
                       "source_start": i * len(y), "block_id": str(i)})
    return blocks


class CalibrationTests(unittest.TestCase):
    def test_joint_budget_credit_requires_final_combined_assessment(self):
        blocks = blocks_fixture()
        selected, trials = cal.calibrate(blocks)
        self.assertEqual(selected["decision"], "candidate")
        self.assertIsNotNone(selected["low_threshold"])
        self.assertIsNotNone(selected["high_threshold"])
        self.assertEqual(selected["events"], 6)
        self.assertEqual(selected["tp"], 72)
        self.assertEqual(selected["false_runs"], 2)
        self.assertEqual(selected["fp"], 20)
        self.assertEqual(selected["policy"], "instant")
        pure_rescues = [t for t in trials if t["low_threshold"] is None and t["high_threshold"] is not None
                        and t["tp"] > selected["evidence"]["reference"]["tp"]]
        self.assertTrue(pure_rescues)
        self.assertTrue(all(not t["feasible"] for t in pure_rescues))
        self.assertTrue(any("added_false_duration_in_block" in t["rejection_reasons"] for t in pure_rescues))

    def test_every_feasible_candidate_preserves_all_constraints(self):
        blocks = blocks_fixture()
        selected, trials = cal.calibrate(blocks)
        labels = np.concatenate([b["labels"] for b in blocks])
        reference = np.concatenate([b["reference"] for b in blocks])
        for trial in (t for t in trials if t["feasible"]):
            predictions = [cal.predict(b["reference"], b["long_scores"], trial) for b in blocks]
            pairs = [(labels, reference, np.concatenate(predictions))] + [
                (b["labels"], b["reference"], p) for b, p in zip(blocks, predictions)]
            for y, r, p in pairs:
                c = comparison(y, r, p)
                self.assertTrue(c["sensor_availability_equal"])
                self.assertFalse(c["lost_baseline_event_ids"])
                self.assertTrue(all(d["extra_delay_seconds"] <= 0 for d in c["paired_extra_delays"]))
                self.assertLessEqual(c["candidate"]["false_positive_runs"], c["baseline"]["false_positive_runs"])
                self.assertLessEqual(c["candidate"]["fp"], c["baseline"]["fp"])
                self.assertTrue(np.all(p[(y == 1) & (r == 1)] == 1))

    def test_unknown_labels_are_neither_normal_nor_prediction_masks(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["labels"][:1800] = -1
        chosen, trials = cal.calibrate(blocks)
        self.assertEqual(chosen["decision"], "reference")
        self.assertEqual(chosen["status"], "insufficient_observed_normal_exposure")
        self.assertEqual(chosen["evidence"]["reference"]["normal_observed_rows"], 3000)
        self.assertEqual(chosen["evidence"]["reference"]["available_rows"], 6600)
        for b in blocks:
            np.testing.assert_array_equal(cal.predict(b["reference"], b["long_scores"], chosen), b["reference"])
        self.assertEqual(len(trials), 1)

    def test_labeled_events_can_calibrate_when_reference_detects_none(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["reference"][:] = 0
            b["long_scores"][2000:2010] = .1
        selected, _ = cal.calibrate(blocks)
        self.assertTrue(selected["evidence"]["enough_labeled_events"])
        self.assertEqual(selected["evidence"]["reference"]["confirmed_events"], 0)
        self.assertEqual(selected["events"], 6)
        self.assertEqual(selected["false_runs"], 0)

    def test_reference_positive_point_loss_rejected_even_when_id_retained(self):
        blocks = blocks_fixture()
        for b in blocks:
            for start in (200, 500, 800):
                # Earlier low-score reference alarm would be suppressed; later
                # retained alarm still confirms the same event but adds latency.
                b["long_scores"][start + 2:start + 4] = .2
        _, trials = cal.calibrate(blocks)
        rejected = [t for t in trials if t["high_threshold"] is None and t["lost_positive_alarm_rows"] > 0]
        self.assertTrue(rejected)
        self.assertTrue(all(not t["feasible"] for t in rejected))
        self.assertTrue(any("added_reference_delay_global" in t["rejection_reasons"] for t in rejected))

    def test_one_crossblock_event_cannot_supply_two_rescue_events_or_owners(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["reference"][:] = 0
            b["long_scores"][:] = .1
        blocks[0]["labels"][3200:] = 1
        blocks[1]["labels"][:100] = 1
        blocks[0]["long_scores"][3200:] = .9
        blocks[1]["long_scores"][:100] = .9
        selected, trials = cal.calibrate(blocks)
        candidate = [t for t in trials if t["high_threshold"] == .9 and t["policy"] == "instant"]
        self.assertEqual(len(candidate), 1)
        self.assertEqual(len(candidate[0]["rescue_coverage_event_ids"]), 1)
        self.assertEqual(candidate[0]["rescue_coverage_blocks"], [0])
        self.assertFalse(candidate[0]["feasible"])
        self.assertEqual(selected["decision"], "reference")

    def test_early_alarm_bridge_cannot_fake_reference_event_retention(self):
        blocks = blocks_fixture()
        for b in blocks:
            for start in (200, 500, 800):
                b["reference"][start:start + 12] = 1
                b["long_scores"][start - 1:start + 12] = .9
        _, trials = cal.calibrate(blocks)
        bridges = [t for t in trials if t["policy"] == "instant" and t["high_threshold"] == .9]
        self.assertTrue(bridges)
        self.assertTrue(all("lost_reference_event_global" in t["rejection_reasons"] for t in bridges))
        self.assertTrue(all(not t["feasible"] for t in bridges))

    def test_short_block_is_still_subject_to_fp_constraints(self):
        blocks = blocks_fixture()
        short = {"labels": np.zeros(20, np.int8), "reference": np.zeros(20, np.int8),
                 "long_scores": np.r_[np.full(10, .1), np.full(10, .9)], "source_start": 6600}
        blocks.append(short)
        selected, trials = cal.calibrate(blocks)
        self.assertEqual(selected["high_threshold"], None)
        high_candidates = [t for t in trials if t["high_threshold"] == .9]
        self.assertTrue(high_candidates)
        self.assertTrue(all(2 in t["added_false_duration_blocks"] for t in high_candidates))
        self.assertTrue(all(not t["feasible"] for t in high_candidates))

    def test_unknown_scores_preserve_reference_and_availability(self):
        r = np.array([-1, 1, 1, 0, 0, 1, -1], np.int8)
        s = np.array([9, np.nan, .1, np.nan, 9, .1, 9])
        chosen = cal._choice(.5, .9, "instant")
        result = cal.predict(r, s, chosen)
        np.testing.assert_array_equal(result, [-1, 1, 1, 0, 1, 0, -1])
        np.testing.assert_array_equal(result >= 0, r >= 0)

    def test_suppression_exactly_matches_frozen_v6_latch(self):
        rng = np.random.default_rng(742)
        for policy in cal.POLICIES:
            for _ in range(20):
                r = rng.choice([-1, 0, 1], 100).astype(np.int8)
                s = rng.random(100)
                s[rng.random(100) < .15] = np.nan
                expected = old_latched_predict(s, r, {"decision": "candidate", "threshold": .5, "policy": policy})
                np.testing.assert_array_equal(cal.predict(r, s, cal._choice(.5, None, policy)), expected)

    def test_rescue_requires_current_evidence_after_persistence(self):
        r = np.zeros(7, np.int8)
        s = np.array([1., 1., 1., .1, .1, np.nan, 1.])
        for policy in ("2of3", "3of5"):
            p = cal.predict(r, s, cal._choice(None, .5, policy))
            self.assertEqual(p[3], 0)
            self.assertEqual(p[4], 0)
            self.assertEqual(p[5], 0)
            self.assertEqual(p[6], 0)

    def test_prefix_causality_and_long_latch(self):
        r = np.zeros(300, np.int8)
        r[10:290] = 1
        r[290] = -1
        s = np.zeros(300)
        s[10] = 1
        s[299] = 1
        for policy in cal.POLICIES:
            chosen = cal._choice(.5, .9, policy)
            whole = cal.predict(r, s, chosen)
            for stop in (1, 10, 11, 12, 75, 200, 290, 291, 299):
                np.testing.assert_array_equal(cal.predict(r[:stop], s[:stop], chosen), whole[:stop])
        np.testing.assert_array_equal(cal.predict(r, s, cal._choice(.5))[10:290], np.ones(280))

    def test_metric_optimization_matches_frozen_oracle_random_unknowns(self):
        rng = np.random.default_rng(20261016)
        for n in (1, 2, 7, 150):
            for _ in range(40):
                y = rng.choice([-1, 0, 1], n).astype(np.int8)
                p = rng.choice([-1, 0, 1], n).astype(np.int8)
                expected = stats(y, p)
                for key, value in cal._MetricContext(y).measure(p).items():
                    self.assertEqual(value, expected[key], (key, y, p))

    def test_fixed_grid_and_noop_reference_preference(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["long_scores"][:] = np.nan
        selected, trials = cal.calibrate(blocks)
        self.assertEqual(selected["decision"], "reference")
        self.assertEqual(len(trials), 1)
        self.assertEqual(cal._grid(np.array([0., 1., np.nan]), np.linspace(0, 1, 21)), np.linspace(0, 1, 21).tolist())
        values = cal._grid(np.linspace(0, 1, 101), np.linspace(.9, 1, 41), above_max=True)
        self.assertEqual(len(values), 42)
        self.assertGreater(values[-1], 1.)

    def test_insufficient_events_retains_reference(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["labels"][:] = 0
            b["labels"][200:212] = 1
        selected, _ = cal.calibrate(blocks)
        self.assertEqual(selected["status"], "insufficient_primary_event_representation")
        self.assertEqual(selected["decision"], "reference")

    def test_input_validation_and_no_mutation(self):
        blocks = blocks_fixture()
        snapshots = [{k: v.copy() for k, v in b.items() if isinstance(v, np.ndarray)} for b in blocks]
        cal.calibrate(blocks)
        for b, snapshot in zip(blocks, snapshots):
            for key in snapshot:
                np.testing.assert_array_equal(b[key], snapshot[key])
        with self.assertRaises(ValueError): cal.calibrate([])
        with self.assertRaises(ValueError): cal.calibrate(blocks, cadence_seconds=True)
        with self.assertRaises(ValueError): cal.calibrate(blocks, cadence_seconds=np.nan)
        with self.assertRaises(ValueError): cal.predict([0, 1], [0., 1.], cal._choice(.9, .5))
        with self.assertRaises(ValueError): cal.predict([0, 1], [0., 1.], cal._choice(policy="invalid"))
        blocks[1]["source_start"] += 1
        with self.assertRaises(ValueError): cal.calibrate(blocks)


if __name__ == "__main__":
    unittest.main()
