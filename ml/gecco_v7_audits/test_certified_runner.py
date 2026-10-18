"""Independent synthetic preflight for conditional temporal certification.

No real source, saved score, result, or model is opened. A controlled selection
stub isolates the chronology/veto contract; actual certification and predictors
remain live. Earlier public experiment results are not retrospectively changed.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v7 import calibration_certified as certified
from ml.gecco_v7 import recalibrate_certified as runner
from ml.gecco_v7 import runtime_certified, runtime_delayed, runtime_v2
from ml.gecco_v7_audits.test_delayed_oracle import bundle, fake_reference, selected


def four_blocks():
    blocks = []
    for k in range(4):
        labels = np.zeros(3300, np.int8)
        reference = np.zeros(3300, np.int8)
        confidence = np.full(3300, .1)
        for start in (200, 500, 800):
            labels[start:start + 10] = 1
            reference[start:start + 10] = 1
            confidence[start:start + 10] = .9
        reference[1200] = 1
        reference[1300:1302] = 1
        blocks.append({"labels": labels, "reference": reference,
                       "long_scores": confidence, "rescue_scores": np.full(3300, np.nan),
                       "source_start": 3300 * k, "block_id": f"past_{k}"})
    return blocks


def fixed_proposal(choice=None):
    choice = selected() if choice is None else choice
    return {**choice, "evidence": {"source_range": [0, 6600], "sentinel": "earlier-only"}}, [
        {**choice, "feasible": True, "rejection_reasons": []}]


class CertificationIsolationTests(unittest.TestCase):
    def test_only_first_two_blocks_choose_and_late_mutation_can_only_veto(self):
        blocks = four_blocks()
        proposal, trials = fixed_proposal()
        with patch.object(certified.delayed, "calibrate", return_value=(proposal, trials)) as choose:
            first, _ = certified.calibrate(blocks)
        choose.assert_called_once()
        supplied = choose.call_args.args[0]
        self.assertEqual([b["block_id"] for b in supplied], ["past_0", "past_1"])
        for index, b in enumerate(supplied):
            np.testing.assert_array_equal(b["labels"], blocks[index]["labels"])
        self.assertTrue(first["certification_passed"])
        self.assertEqual(first["decision"], "candidate")
        changed = deepcopy(blocks)
        for b in changed[2:]:
            b["labels"][:] = 0  # no qualified event evidence in later blocks
        with patch.object(certified.delayed, "calibrate", return_value=(proposal, trials)) as choose:
            vetoed, _ = certified.calibrate(changed)
        choose.assert_called_once()
        self.assertEqual(vetoed["earlier_selected"], first["earlier_selected"])
        self.assertEqual(vetoed["earlier_selected"], proposal)
        self.assertEqual(vetoed["decision"], "reference")
        self.assertFalse(vetoed["certification_passed"])
        self.assertEqual(vetoed["certification_attempts"], 1)
        self.assertIsNone(vetoed["low_threshold"])
        self.assertIsNone(vetoed["high_threshold"])
        for b in changed:
            np.testing.assert_array_equal(certified.predict(b["reference"], b["long_scores"],
                                          vetoed, b["rescue_scores"]), b["reference"])

    def test_global_four_block_veto_catches_event_crossing_phase_boundary(self):
        blocks = four_blocks()
        # Its known onset lies in the final selection block; the reference's
        # only confirmation lies in the initial certification continuation.
        blocks[1]["labels"][-2:] = 1
        blocks[2]["labels"][:4] = 1
        blocks[2]["reference"][1] = 1
        blocks[2]["long_scores"][1] = .1
        proposal, trials = fixed_proposal()
        with patch.object(certified.delayed, "calibrate", return_value=(proposal, trials)):
            result, _ = certified.calibrate(blocks)
        self.assertTrue(result["certification"]["passed"])
        self.assertTrue(result["global_veto"]["earlier_pure_confirmation_seed"]["passed"])
        self.assertFalse(result["global_veto"]["all_four_pure_confirmation_seed"]["passed"])
        self.assertFalse(result["global_veto"]["all_four_candidate"]["passed"])
        scope = result["global_veto"]["all_four_pure_confirmation_seed"]["scopes"][0]
        self.assertEqual(len(scope["lost_reference_event_ids"]), 1)
        self.assertEqual(result["decision"], "reference")

    def test_rescue_cannot_conceal_pure_seed_event_loss(self):
        blocks = four_blocks()
        for b in blocks[2:]:
            b["reference"][200:210] = 0
            b["reference"][201] = 1
            b["long_scores"][200:210] = .1
            b["rescue_scores"][201] = .9
        proposal, trials = fixed_proposal(selected(.5, .8))
        with patch.object(certified.delayed, "calibrate", return_value=(proposal, trials)):
            result, _ = certified.calibrate(blocks)
        cert = result["certification"]
        self.assertTrue(cert["candidate"]["passed"])
        self.assertTrue(cert["rescue"]["passed"])
        self.assertFalse(cert["pure_confirmation_seed"]["passed"])
        self.assertFalse(result["certification_passed"])
        self.assertEqual(result["decision"], "reference")

    def test_certification_never_calls_selection_or_modifies_policy(self):
        choice = selected()
        original = deepcopy(choice)
        with patch.object(certified.delayed, "calibrate", side_effect=AssertionError("No selection in certification")):
            result = certified.certify(choice, four_blocks()[2:])
        self.assertTrue(result["passed"])
        self.assertEqual(choice, original)
        self.assertEqual(result["fixed_choice"], original)

    def test_real_selection_and_unsupported_late_evidence_return_exact_reference(self):
        blocks = four_blocks()
        for b in blocks[2:]:
            b["labels"][:] = -1
        result, trials = certified.calibrate(blocks)
        self.assertEqual(result["earlier_selected"]["decision"], "candidate")
        self.assertEqual(result["decision"], "reference")
        self.assertEqual(result["certification_attempts"], 1)
        self.assertFalse(result["certification_passed"])
        self.assertEqual(sum(t["stage"] == "later_certification_and_global_veto" for t in trials), 1)
        for b in blocks:
            np.testing.assert_array_equal(certified.predict(b["reference"], b["long_scores"], result,
                                                           b["rescue_scores"]), b["reference"])


class CertifiedWrapperAndGateTests(unittest.TestCase):
    def test_wrapper_delegates_same_selected_policy_gap_and_inputs_without_mutation(self):
        state = bundle(); state["version"] = "v7_hgb_temporally_certified_120s"
        version = state["version"]; choice = deepcopy(state["selected"])
        frame = pd.DataFrame({"p1": [.2], "p2": [.3]})
        expected = object()
        with patch.object(runtime_certified, "delayed_frame", return_value=expected) as delegate:
            actual = runtime_certified.predict_frame(state, frame, gap_samples=7)
        self.assertIs(actual, expected)
        passed = delegate.call_args.args[0]
        self.assertEqual(passed["version"], "v7_hgb_corroborated_confirmation_120s")
        self.assertEqual(passed["selected"], choice)
        self.assertIs(delegate.call_args.args[1], frame)
        self.assertEqual(delegate.call_args.kwargs, {"gap_samples": 7})
        self.assertEqual(state["version"], version)
        self.assertEqual(state["selected"], choice)
        with self.assertRaises(ValueError):
            runtime_certified.predict_frame(bundle(), frame)

    def test_actual_wrapper_preserves_labels_gap_fallback_and_cadence_checks(self):
        choice = selected(None, None)
        state = bundle(choice); state["version"] = "v7_hgb_temporally_certified_120s"
        state["selected"]["certification_passed"] = False
        frame = pd.DataFrame({"p1": [.3] * 8, "p2": [.5] * 8, "label": [-1] * 8},
                             index=pd.date_range("2020-01-01", periods=8, freq="min"))
        with patch.object(runtime_v2, "reference_predict", side_effect=fake_reference):
            original = runtime_certified.predict_frame(state, frame)
            changed = runtime_certified.predict_frame(state, frame.assign(label=99))
        pd.testing.assert_frame_equal(original, changed)
        np.testing.assert_array_equal(original.prediction, original.reference_prediction)
        self.assertTrue((original.prediction.iloc[:2] == -1).all())
        wrong_clock = frame.copy(); wrong_clock.index = pd.date_range("2020-01-01", periods=8, freq="5min")
        with patch.object(runtime_delayed, "score_frame") as scorer:
            with self.assertRaises(ValueError): runtime_certified.predict_frame(state, wrong_clock)
            scorer.assert_not_called()

    def test_outer_acceptance_is_still_event_level_120_seconds_not_episode_level(self):
        labels = np.zeros(30, np.int8); labels[2:22] = 1
        reference = np.zeros(30, np.int8); reference[3] = 1; reference[12:22] = 1
        candidate = certified.predict(reference, np.zeros(30), selected())
        result = runner.assess(labels, reference, reference, candidate)["v6_vs_v7"]
        self.assertFalse(result["lost_baseline_event_ids"])
        self.assertEqual(result["maximum_observed_paired_extra_delay_seconds"], 660)
        self.assertFalse(result["noninferior"])


if __name__ == "__main__":
    unittest.main()
