"""Synthetic temporal-veto tests. No source values or labels are opened."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np

from ml.gecco_v7 import calibration_certified as cal
from ml.gecco_v7 import calibration_delayed as delayed
from ml.gecco_v7.test_calibration_delayed import confirmation_fixture


def four_blocks():
    blocks = confirmation_fixture() + confirmation_fixture()
    for i, block in enumerate(blocks):
        block["source_start"] = i * len(block["labels"])
        block["block_id"] = str(i)
    return blocks


def forced_selection(choice):
    return {**choice, "evidence": {"synthetic_fixed_choice": True}}, [
        {**choice, "feasible": True, "rejection_reasons": []},
        {**delayed._choice(), "feasible": True, "rejection_reasons": []}]


class CertifiedCalibrationTests(unittest.TestCase):
    def test_real_selection_is_frozen_then_certified_without_changing_predictor(self):
        blocks = four_blocks()
        before = deepcopy(blocks)
        earlier, original_trials = delayed.calibrate(blocks[:2])
        selected, trials = cal.calibrate(blocks)
        self.assertEqual(selected["earlier_selected"], earlier)
        self.assertTrue(selected["certification_passed"])
        self.assertEqual(selected["decision"], "candidate")
        self.assertEqual(selected["confirmation_samples"], 2)
        self.assertEqual(selected["events"], 12)
        self.assertEqual(selected["false_runs"], 0)
        self.assertGreater(selected["lost_positive_alarm_rows"], 0)
        self.assertEqual(selected["max_paired_extra_delay_seconds"], 120)
        self.assertEqual(selected["selection_trial_count"], len(original_trials))
        self.assertEqual(len(trials), len(original_trials) + 1)
        self.assertEqual(selected["selection_blocks"], ["0", "1"])
        self.assertEqual(selected["certification_blocks"], ["2", "3"])
        self.assertIs(cal.predict, delayed.predict)
        for a, b in zip(blocks, before):
            for key in ("labels", "reference", "long_scores", "rescue_scores"):
                np.testing.assert_array_equal(a[key], b[key])

    def test_later_mutation_cannot_change_earlier_choice_and_never_selects_an_alternative(self):
        blocks = four_blocks()
        expected, _ = delayed.calibrate(blocks[:2])
        for block in blocks[2:]:
            block["labels"][:] = -1
            block["long_scores"][:] = 100
        with patch.object(delayed, "calibrate", wraps=delayed.calibrate) as selector:
            selected, _ = cal.calibrate(blocks)
        self.assertEqual(selector.call_count, 1)
        self.assertEqual(len(selector.call_args.args[0]), 2)
        self.assertEqual(selected["earlier_selected"], expected)
        self.assertEqual(selected["final_selected"], delayed._choice())
        self.assertEqual(selected["status"], "certification_failed_reference_retained")
        self.assertEqual(selected["certification_attempts"], 1)
        self.assertFalse(selected["certification"]["evidence"]["enough_observed_normal_exposure"])
        self.assertFalse(selected["certification"]["evidence"]["enough_primary_event_representation"])
        self.assertTrue(selected["certification"]["candidate"]["scopes"][0]["checks"]["reference_availability_unchanged"])

    def test_normal_evidence_uses_only_later_pair_and_unknowns_never_become_normal(self):
        blocks = four_blocks()
        for block in blocks[2:]:
            block["labels"][1500:] = -1
        selected, _ = cal.calibrate(blocks)
        evidence = selected["certification"]["evidence"]
        self.assertEqual(evidence["qualified_normal_minutes"], 2928)
        self.assertEqual(evidence["qualified_blocks"], [0, 1])
        self.assertFalse(evidence["enough_observed_normal_exposure"])
        self.assertEqual(selected["decision"], "reference")
        for block in blocks[2:]:
            np.testing.assert_array_equal(cal.predict(block["reference"], block["long_scores"], selected), block["reference"])

    def test_rescue_cannot_hide_short_true_pulse_removed_by_confirmation(self):
        blocks = four_blocks()[2:]
        for block in blocks:
            block["reference"][802:805] = 0
            block["reference"][802] = 1
            block["rescue_scores"][802] = .9
        fixed = delayed._choice(.5, .8, confirmation_samples=2)
        certificate = cal.certify(fixed, blocks)
        self.assertTrue(certificate["candidate"]["passed"])
        self.assertTrue(certificate["rescue"]["passed"])
        self.assertFalse(certificate["pure_confirmation_seed"]["passed"])
        self.assertFalse(certificate["passed"])
        self.assertIn("pure_seed:pool:reference_event_ids_retained", certificate["rejection_reasons"])

    def test_rescue_cannot_hide_event_delay_over_120_despite_episode_timer(self):
        blocks = four_blocks()[2:]
        for block in blocks:
            block["labels"][500:530] = 1
            block["reference"][500:530] = 0
            block["reference"][501] = 1
            block["reference"][510:515] = 1
            block["rescue_scores"][501] = .9
        certificate = cal.certify(delayed._choice(.5, .8, confirmation_samples=2), blocks)
        self.assertTrue(certificate["candidate"]["passed"])
        seed = certificate["pure_confirmation_seed"]
        self.assertEqual(seed["scopes"][0]["max_paired_extra_delay_seconds"], 660)
        self.assertFalse(seed["passed"])
        self.assertFalse(certificate["passed"])

    def test_rescue_cannot_spend_confirmation_false_alarm_credit(self):
        blocks = four_blocks()[2:]
        for block in blocks:
            block["rescue_scores"][200:212] = .9
            block["rescue_scores"][1001] = .9
        certificate = cal.certify(delayed._choice(.5, .8, confirmation_samples=2), blocks)
        self.assertTrue(certificate["candidate"]["passed"])
        self.assertEqual(certificate["rescue"]["added_known_normal_rows"], 2)
        self.assertEqual(certificate["rescue"]["added_known_normal_rows_by_block"], [1, 1])
        self.assertFalse(certificate["passed"])

    def test_rescue_coverage_requires_original_events_and_two_first_addition_blocks(self):
        blocks = four_blocks()[2:]
        blocks[0]["rescue_scores"][200:212] = .9
        blocks[0]["rescue_scores"][500:512] = .9
        certificate = cal.certify(delayed._choice(None, .8), blocks)
        self.assertEqual(len(certificate["rescue"]["coverage_event_ids"]), 2)
        self.assertEqual(certificate["rescue"]["first_addition_blocks"], [0])
        self.assertFalse(certificate["passed"])
        for block in blocks:
            block["rescue_scores"][:] = np.nan
        blocks[0]["labels"][3200:] = 1
        blocks[1]["labels"][:100] = 1
        blocks[0]["rescue_scores"][3200:] = .9
        blocks[1]["rescue_scores"][:100] = .9
        certificate = cal.certify(delayed._choice(None, .8), blocks)
        self.assertEqual(len(certificate["rescue"]["coverage_event_ids"]), 1)
        self.assertEqual(certificate["rescue"]["first_addition_blocks"], [0])
        self.assertFalse(certificate["passed"])

    def test_cross_selection_certification_event_censoring_cannot_bypass_all_four_veto(self):
        blocks = four_blocks()
        blocks[1]["labels"][-10:] = 1
        blocks[2]["labels"][:10] = 1
        blocks[2]["reference"][1] = 1
        fixed = delayed._choice(.5, confirmation_samples=2)
        with patch.object(delayed, "calibrate", return_value=forced_selection(fixed)):
            selected, _ = cal.calibrate(blocks)
        self.assertTrue(selected["certification"]["passed"])
        self.assertTrue(selected["global_veto"]["earlier_pure_confirmation_seed"]["passed"])
        self.assertFalse(selected["global_veto"]["all_four_pure_confirmation_seed"]["passed"])
        self.assertFalse(selected["global_veto"]["all_four_candidate"]["passed"])
        self.assertEqual(selected["decision"], "reference")

    def test_pure_seed_is_checked_on_earlier_pair_even_if_final_policy_masks_its_loss(self):
        blocks = four_blocks()
        for block in blocks:
            block["rescue_scores"][200:212] = .9
        for block in blocks[:2]:
            block["reference"][802:805] = 0
            block["reference"][802] = 1
            block["rescue_scores"][802] = .9
        fixed = delayed._choice(.5, .8, confirmation_samples=2)
        with patch.object(delayed, "calibrate", return_value=forced_selection(fixed)):
            selected, _ = cal.calibrate(blocks)
        self.assertTrue(selected["certification"]["passed"])
        self.assertTrue(selected["global_veto"]["all_four_candidate"]["passed"])
        self.assertFalse(selected["global_veto"]["earlier_pure_confirmation_seed"]["passed"])
        self.assertEqual(selected["decision"], "reference")

    def test_each_block_false_alarm_constraint_applies_even_if_pool_improves(self):
        blocks = four_blocks()[2:]
        blocks[0]["reference"][1000:1202] = 0
        for block in blocks:
            block["rescue_scores"][200:212] = .9
        blocks[0]["rescue_scores"][1500] = .9
        certificate = cal.certify(delayed._choice(.5, .8, confirmation_samples=2), blocks)
        scopes = certificate["candidate"]["scopes"]
        self.assertTrue(all(scopes[0]["checks"].values()))
        self.assertFalse(scopes[1]["checks"]["false_duration_not_increased"])
        self.assertFalse(scopes[1]["checks"]["false_fragments_not_increased"])
        self.assertFalse(certificate["passed"])

    def test_rescue_early_bridge_is_event_loss_despite_more_positive_coverage(self):
        blocks = four_blocks()[2:]
        for block in blocks:
            block["rescue_scores"][199:212] = .9
        certificate = cal.certify(delayed._choice(None, .8), blocks)
        self.assertFalse(certificate["candidate"]["scopes"][0]["checks"]["reference_event_ids_retained"])
        self.assertFalse(certificate["passed"])

    def test_geometry_cadence_and_absent_evidence_are_not_silently_relaxed(self):
        blocks = four_blocks()
        with self.assertRaises(ValueError): cal.calibrate(blocks[:3])
        with self.assertRaises(ValueError): cal.certify(delayed._choice(), blocks)
        blocks[2]["source_start"] += 1
        with self.assertRaises(ValueError): cal.calibrate(blocks)
        with self.assertRaises(ValueError): cal.certify(delayed._choice(cadence_seconds=300), four_blocks()[2:])
        selected, trials = cal.calibrate(four_blocks(), cadence_seconds=300)
        self.assertEqual(selected["decision"], "reference")
        self.assertTrue(all(t["confirmation_samples"] == 0 for t in trials))
        blocks = four_blocks()
        for block in blocks: block["labels"][:] = -1
        selected, _ = cal.calibrate(blocks)
        self.assertEqual(selected["status"], "earlier_reference_retained")
        self.assertFalse(selected["certification_passed"])


if __name__ == "__main__":
    unittest.main()
