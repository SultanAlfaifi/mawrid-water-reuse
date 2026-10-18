"""Synthetic verification of the user-authorized <=120-second test policy."""
import unittest

import numpy as np

from ml.gecco_v7 import calibration_delayed as cal
from ml.gecco_v7.test_calibration import blocks_fixture
from unknown_label_metrics import comparison


def confirmation_fixture():
    blocks = blocks_fixture()
    for b in blocks:
        b["reference"][1000:1220] = 0
        b["reference"][1000] = 1
        b["reference"][1200:1202] = 1
        b["long_scores"][:] = .1
        b["long_scores"][202:205] = .9
        b["rescue_scores"] = np.full(len(b["labels"]), np.nan)
    return blocks


def scalar_seed(reference, confidence, low, deadline):
    result = []
    age = 0; latched = False
    for r, score in zip(reference, confidence):
        if r != 1:
            age = 0; latched = False; result.append(r)
            continue
        if low is None or not np.isfinite(score) or score >= low or age >= deadline:
            latched = True
        result.append(int(latched)); age += 1
    return np.asarray(result, np.int8)


class DelayedCalibrationTests(unittest.TestCase):
    def test_continuous_reference_forces_on_at_deadline_and_then_latches(self):
        reference = np.array([0, 1, 1, 1, 1, 1, 0], np.int8)
        scores = np.zeros(len(reference))
        for deadline, expected in ((1, [0, 0, 1, 1, 1, 1, 0]), (2, [0, 0, 0, 1, 1, 1, 0])):
            selected = cal._choice(.5, None, confirmation_samples=deadline)
            np.testing.assert_array_equal(cal.predict(reference, scores, selected), expected)

    def test_short_episodes_can_be_discarded_and_each_new_episode_resets_age(self):
        r = np.array([0, 1, 0, 1, 1, 0, 1, 1, 1], np.int8)
        p = cal.predict(r, np.zeros(len(r)), cal._choice(.5, confirmation_samples=2))
        np.testing.assert_array_equal(p, [0, 0, 0, 0, 0, 0, 0, 0, 1])

    def test_high_or_unknown_current_confidence_releases_early_and_latches(self):
        r = np.ones(6, np.int8)
        for score in (.5, .8, np.nan, np.inf, -np.inf):
            raw = np.array([.1, score, .1, .1, .1, .1])
            np.testing.assert_array_equal(cal.predict(r, raw, cal._choice(.5, confirmation_samples=2)), [0, 1, 1, 1, 1, 1])
        r = np.array([0, 1, 1, -1, 1, 1, 1], np.int8)
        raw = np.array([0., np.nan, 0., 0., 0., 0., 0.])
        np.testing.assert_array_equal(cal.predict(r, raw, cal._choice(.5, confirmation_samples=2)), [0, 1, 1, -1, 0, 0, 1])

    def test_reference_availability_never_changes(self):
        r = np.array([-1, 0, 1, 1, -1, 0, 1], np.int8)
        raw = np.zeros(len(r)); rescue = np.ones(len(r))
        p = cal.predict(r, raw, cal._choice(.5, .8, confirmation_samples=2), rescue)
        np.testing.assert_array_equal(p >= 0, r >= 0)
        np.testing.assert_array_equal(p, [-1, 1, 1, 1, -1, 1, 1])

    def test_scalar_oracle_prefix_and_future_mutation(self):
        rng = np.random.default_rng(20261016)
        for _ in range(50):
            r = rng.choice([-1, 0, 1], 120).astype(np.int8)
            raw = rng.random(len(r)); raw[::11] = np.nan
            for deadline in (1, 2):
                selected = cal._choice(.5, confirmation_samples=deadline)
                whole = cal.predict(r, raw, selected)
                np.testing.assert_array_equal(whole, scalar_seed(r, raw, .5, deadline))
                for stop in (0, 1, 2, 5, 40, 100):
                    np.testing.assert_array_equal(cal.predict(r[:stop], raw[:stop], selected), whole[:stop])
                    changed = raw.copy(); changed[stop:] = 100
                    np.testing.assert_array_equal(cal.predict(r, changed, selected)[:stop], whole[:stop])

    def test_cadence_caps_deadline_and_five_minute_data_cannot_wait(self):
        self.assertEqual(cal.allowed_confirmation_samples(60), [1, 2])
        self.assertEqual(cal.allowed_confirmation_samples(90), [1])
        self.assertEqual(cal.allowed_confirmation_samples(120), [1])
        self.assertEqual(cal.allowed_confirmation_samples(120.001), [])
        self.assertEqual(cal.allowed_confirmation_samples(300), [])
        for cadence, deadline in ((300, 1), (90, 2), (60, 3)):
            with self.assertRaises(ValueError):
                cal.predict([0, 1, 1], [.1] * 3, cal._choice(.5, confirmation_samples=deadline, cadence_seconds=cadence))
        chosen, trials = cal.calibrate(confirmation_fixture(), cadence_seconds=300)
        self.assertTrue(all(t["confirmation_samples"] == 0 and t["low_threshold"] is None for t in trials))
        self.assertEqual(chosen["decision"], "reference")

    def test_calibration_allows_initial_positive_row_loss_with_retained_ids_and_bounded_delay(self):
        blocks = confirmation_fixture()
        selected, trials = cal.calibrate(blocks)
        self.assertEqual(selected["confirmation_samples"], 2)
        self.assertEqual(selected["events"], 6)
        self.assertEqual(selected["false_runs"], 0)
        self.assertEqual(selected["max_paired_extra_delay_seconds"], 120)
        self.assertGreater(selected["lost_positive_alarm_rows"], 0)
        self.assertEqual(selected["lost_event_ids"], [])
        self.assertEqual(selected["over_budget_delay_event_ids"], [])
        self.assertTrue(all(d["extra_delay_seconds"] <= 120 for d in selected["calibration_paired_delays"]))
        for trial in (t for t in trials if t["feasible"]):
            predictions = [cal.predict(b["reference"], b["long_scores"], trial, b["rescue_scores"]) for b in blocks]
            parts = [(b["labels"], b["reference"], p) for b, p in zip(blocks, predictions)]
            parts += [(np.concatenate([b["labels"] for b in blocks]), np.concatenate([b["reference"] for b in blocks]), np.concatenate(predictions))]
            for y, reference, p in parts:
                result = comparison(y, reference, p)
                self.assertFalse(result["lost_baseline_event_ids"])
                self.assertTrue(all(d["extra_delay_seconds"] <= 120 for d in result["paired_extra_delays"]))
                self.assertTrue(result["sensor_availability_equal"])
                self.assertLessEqual(result["candidate"]["fp"], result["baseline"]["fp"])
                self.assertLessEqual(result["candidate"]["false_positive_runs"], result["baseline"]["false_positive_runs"])

    def test_runtime_episode_bound_does_not_excuse_event_delay_over_budget(self):
        blocks = confirmation_fixture()
        for b in blocks:
            b["labels"][500:530] = 1
            b["reference"][500:530] = 0
            b["reference"][501] = 1
            b["reference"][510:515] = 1
        _, trials = cal.calibrate(blocks)
        bad = [t for t in trials if t["max_paired_extra_delay_seconds"] is not None and t["max_paired_extra_delay_seconds"] > 120]
        self.assertTrue(bad)
        self.assertTrue(all(not t["feasible"] for t in bad))
        self.assertTrue(all("reference_delay_exceeds_120_seconds_global" in t["rejection_reasons"] for t in bad))

    def test_discarded_short_true_event_is_rejected(self):
        blocks = confirmation_fixture()
        for b in blocks:
            b["reference"][802:805] = 0
            b["reference"][802] = 1
        _, trials = cal.calibrate(blocks)
        lost = [t for t in trials if t["lost_event_ids"]]
        self.assertTrue(lost)
        self.assertTrue(all(not t["feasible"] and "lost_reference_event_global" in t["rejection_reasons"] for t in lost))

    def test_rescue_uses_only_separate_current_score_and_its_policy(self):
        r = np.zeros(6, np.int8)
        raw = np.ones(6)
        rescue = np.array([1., 1., 1., .1, np.nan, 1.])
        for policy in ("2of3", "3of5"):
            p = cal.predict(r, raw, cal._choice(None, .8, policy), rescue)
            self.assertEqual(p[3], 0); self.assertEqual(p[4], 0); self.assertEqual(p[5], 0)
        np.testing.assert_array_equal(cal.predict(r, raw, cal._choice(None, .8), np.full(6, np.nan)), r)

    def test_rescue_cannot_spend_saved_false_alarm_budget(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["rescue_scores"] = b["long_scores"].copy()
        _, trials = cal.calibrate(blocks)
        spenders = [t for t in trials if t["rescue_added_normal_rows"] > 0]
        self.assertTrue(spenders)
        self.assertTrue(all(not t["feasible"] for t in spenders))
        self.assertTrue(all("rescue_added_known_normal_rows_global" in t["rejection_reasons"] for t in spenders))

    def test_low_grid_raw_high_grid_corroborated_and_unknown_label_exclusion(self):
        blocks = confirmation_fixture()
        for b in blocks:
            b["rescue_scores"][200:212] = .95
            b["rescue_scores"][500:512] = .95
            b["labels"][2000:2010] = -1
            b["rescue_scores"][2000:2010] = .95
        chosen, trials = cal.calibrate(blocks)
        high = {t["high_threshold"] for t in trials if t["high_threshold"] is not None}
        self.assertEqual(high, {.95, float(np.nextafter(.95, np.inf))})
        self.assertIsNotNone(chosen["high_threshold"])
        self.assertEqual(chosen["rescue_added_normal_rows"], 0)
        self.assertEqual(chosen["evidence"]["reference"]["available_rows"], 6600)
        self.assertEqual(chosen["evidence"]["reference"]["normal_observed_rows"], 6508)

    def test_event_bridge_and_crossblock_coverage_still_use_original_id_semantics(self):
        blocks = blocks_fixture()
        for b in blocks:
            b["reference"][:] = 0; b["long_scores"][:] = .1
            b["rescue_scores"] = np.full(len(b["labels"]), np.nan)
        blocks[0]["labels"][3200:] = 1; blocks[1]["labels"][:100] = 1
        blocks[0]["rescue_scores"][3200:] = .9; blocks[1]["rescue_scores"][:100] = .9
        selected, trials = cal.calibrate(blocks)
        trial = next(t for t in trials if t["high_threshold"] == .9 and t["policy"] == "instant")
        self.assertEqual(len(trial["rescue_coverage_event_ids"]), 1)
        self.assertEqual(trial["rescue_coverage_blocks"], [0])
        self.assertFalse(trial["feasible"])
        self.assertEqual(selected["decision"], "reference")

    def test_missing_evidence_falls_back_and_validation_prevents_invalid_deadline(self):
        blocks = confirmation_fixture()
        for b in blocks: b["labels"][:] = -1
        selected, trials = cal.calibrate(blocks)
        self.assertEqual(selected["decision"], "reference")
        self.assertEqual(selected["confirmation_samples"], 0)
        self.assertEqual(len(trials), 1)
        with self.assertRaises(ValueError): cal.predict([1], [.1], cal._choice(None, confirmation_samples=1))
        with self.assertRaises(ValueError): cal.predict([1], [.1], cal._choice(.5, confirmation_samples=0))
        with self.assertRaises(ValueError): cal.predict([1], [.1], {**cal._choice(.5, confirmation_samples=1), "confirmation_samples": True})
        with self.assertRaises(ValueError): cal.predict([1], [.1], {**cal._choice(.5, confirmation_samples=1), "confirmation_delay_seconds": 120})
        with self.assertRaises(ValueError): cal.predict([1], [.1], cal._choice(), [1, 2])


if __name__ == "__main__":
    unittest.main()
