"""Independent synthetic-only V11 protected-reference policy audit tests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v11_audits import replay as audit
from ml.gecco_v11 import calibration as production
from ml.gecco_v10_audits.test_replay import blocks_fixture, assert_checks
from ml.gecco_v6.unknown_label_metrics import stats


def fixture():
    blocks = blocks_fixture()
    for b in blocks:
        b['baseline'] = np.zeros(len(b['reference']), np.int8)
        b['baseline'][202] = 1
    return blocks


class ProtectedScalarTests(unittest.TestCase):
    def choice(self, **kwargs):
        return production._choice(.5, confirmation_samples=2, pending_after_clear=True, **kwargs)

    def paths(self, reference, baseline, score, choice=None, rescue=None):
        r, b, s = np.asarray(reference, np.int8), np.asarray(baseline, np.int8), np.asarray(score, float)
        return audit.scalar_paths(r, s, s if rescue is None else rescue, choice or self.choice(), baseline=b)

    def test_protected_pulse_latches_then_cannot_create_pending(self):
        result, seed, base, owners = self.paths([1, 1, 0, 0], [1, 0, 0, 0], [.1, .1, .9, .9])
        for path in (result, seed, base):
            np.testing.assert_array_equal(path, [1, 1, 0, 0])
        np.testing.assert_array_equal(owners, [-1] * 4)

    def test_later_protection_releases_same_episode_without_resetting_deadline(self):
        result, _, _, owners = self.paths([1, 1, 0, 1, 1, 1], [0, 1, 0, 0, 0, 0], [.1] * 6)
        np.testing.assert_array_equal(result, [0, 1, 0, 0, 0, 1])
        np.testing.assert_array_equal(owners, [-1] * 6)

    def test_baseline_alerts_removed_by_reference_never_resurrect(self):
        result, _, _, _ = self.paths([0, -1, 0, 1, 0], [1, 1, 1, 0, 1], [.1] * 5)
        np.testing.assert_array_equal(result, [0, -1, 0, 0, 0])

    def test_reference_unknown_cancels_protected_and_waiting_owners(self):
        result, _, _, owners = self.paths([1, -1, 1, 0, -1, 0], [1, 1, 0, 0, 1, 1], [.1, .1, .1, .1, .9, .9])
        np.testing.assert_array_equal(result, [1, -1, 0, 0, -1, 0])
        np.testing.assert_array_equal(owners, [-1] * 6)

    def test_old_pending_can_overlap_new_protected_pulse_without_extending_owner(self):
        result, seed, base, owners = self.paths([1, 0, 1, 1, 0], [0, 0, 1, 0, 0], [.1, .1, .9, .1, .9])
        np.testing.assert_array_equal(result, [0, 0, 1, 1, 0])
        np.testing.assert_array_equal(seed, base)
        self.assertEqual(owners[2], 0)
        self.assertEqual(int((owners >= 0).sum()), 1)

    def test_scalar_matches_production_and_explicit_protected_floor_all_policies(self):
        rng = np.random.default_rng(413)
        for n in (0, 1, 2, 7, 99, 410):
            r, b = [rng.choice([-1, 0, 1], n).astype(np.int8) for _ in range(2)]
            s, rescue = rng.random(n), rng.random(n)
            s[::17] = np.nan; s[::29] = np.inf; rescue[::11] = np.nan
            for deadline in (1, 2):
                for pending in (False, True):
                    for high in (None, .8):
                        for policy in ('instant', '2of3', '3of5'):
                            choice = production._choice(.5, high, policy, deadline, 60, pending)
                            final, seed, base, owners = audit.scalar_paths(r, s, rescue, choice, baseline=b)
                            np.testing.assert_array_equal(final, production.predict(r, s, choice, rescue, baseline=b))
                            for x, y in zip((seed, base, owners), production._confirmation(r, s, .5, deadline, pending, b)):
                                np.testing.assert_array_equal(x, y)
                            np.testing.assert_array_equal(seed[(r == 1) & (b == 1)], np.ones(int(((r == 1) & (b == 1)).sum()), np.int8))
                            np.testing.assert_array_equal(final >= 0, r >= 0)

    def test_prefix_future_baseline_and_cumulative_chunk_causality(self):
        rng = np.random.default_rng(71); n = 128
        r, b = [rng.choice([-1, 0, 1], n).astype(np.int8) for _ in range(2)]
        s, rescue = rng.random(n), rng.random(n)
        choice = production._choice(.5, .8, '2of3', 2, 60, True)
        full = audit.scalar_paths(r, s, rescue, choice, baseline=b)
        edges = (0, 1, 2, 3, 17, 63, 64, 127, 128)
        chunks = []
        for a, stop in zip(edges[:-1], edges[1:]):
            prefix = audit.scalar_paths(r[:stop], s[:stop], rescue[:stop], choice, baseline=b[:stop])
            for current, total in zip(prefix, full):
                np.testing.assert_array_equal(current, total[:stop])
            chunks.append(prefix[0][a:stop])
            rr, bb, ss = r.copy(), b.copy(), s.copy()
            rr[stop:] = 1; bb[stop:] = 1; ss[stop:] = 1
            altered = audit.scalar_paths(rr, ss, rescue, choice, baseline=bb)
            np.testing.assert_array_equal(altered[0][:stop], full[0][:stop])
        # Cumulative-prefix replay across arbitrary chunk boundaries, not a
        # claim that this batch API implements persistent streaming state.
        np.testing.assert_array_equal(np.concatenate(chunks), full[0])

    def test_rescue_does_not_fake_protection_or_release_long_latch(self):
        r = np.ones(5, np.int8); baseline = np.zeros(5, np.int8)
        result, seed, _, _ = audit.scalar_paths(r, np.zeros(5), [.9, .1, .1, .1, .1], self.choice(high=.8), baseline=baseline)
        np.testing.assert_array_equal(result, [1, 0, 1, 1, 1])
        np.testing.assert_array_equal(seed, [0, 0, 1, 1, 1])

    def test_resurrection_accounting_does_not_misattribute_rescue_to_protection(self):
        r, b, score = np.array([0, 1, 0, -1]), np.array([1, 1, 1, 1]), np.ones(4)
        paths = audit.scalar_paths(r, score, score, self.choice(high=.8), baseline=b)
        count = audit.protection_accounting(r, b, paths)
        self.assertEqual(count['retained_if_protected_rows'], 1)
        self.assertEqual(count['unextended_seed_alarm_rows_outside_reference_alarm'], 0)
        self.assertEqual(count['pending_seed_alarm_rows_on_reference_zero'], 0)
        self.assertEqual(count['final_alarm_rows_on_if_one_reference_zero'], 2)

    def test_baseline_shape_values_metadata_and_missing_argument_rejected(self):
        r, s = np.ones(3, np.int8), np.ones(3)
        for baseline in (np.ones(2), np.array([0, 2, 1]), np.array([0, np.nan, 1]), np.ones((3, 1))):
            with self.assertRaises(ValueError):
                audit.scalar_paths(r, s, s, self.choice(), baseline=baseline)
        with self.assertRaises(TypeError):
            audit.scalar_paths(r, s, s, self.choice())
        for flag in (False, 1, None):
            with self.assertRaises(ValueError):
                audit.scalar_paths(r, s, s, {**self.choice(), 'retained_if_protection': flag}, baseline=r)


class CertificateAndCallerTests(unittest.TestCase):
    def test_protected_baseline_certificate_and_csv_choice_audit(self):
        blocks = fixture(); selected, trials = production.calibrate(blocks)
        self.assertTrue(selected['retained_if_protection'])
        self.assertTrue(selected['certification_passed'])
        frames = []
        for b in blocks:
            frames.append(pd.DataFrame({'sample_index': np.arange(b['source_start'], b['source_start'] + len(b['labels'])),
                'label': b['labels'], 'reference': b['reference'], 'baseline': b['baseline'],
                'long_context': b['long_scores'], 'guarded_long_context': b['long_scores'], 'rescue_long_context': b['rescue_scores'],
                'candidate': production.predict(b['reference'], b['long_scores'], selected, b['rescue_scores'], baseline=b['baseline'])}))
        frame = pd.concat(frames, ignore_index=True)
        local = pd.DataFrame({'sample_index': frame.sample_index, 'level': .1, 'jump': .1, 'sustained': .1})
        checks = audit.Checks()
        audit._calibration(checks, 'protected', frame, local, frame, [0, 4000, 8000, 12000, 16000], selected, None, stats)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trials.csv.gz'
            pd.DataFrame(trials).to_csv(path, index=False)
            audit._trial_selection(checks, 'protected', pd.read_csv(path, float_precision='round_trip'), selected)
        assert_checks(self, checks)

    def test_later_baseline_changes_cannot_reselect_early_threshold(self):
        blocks = fixture()
        first, _ = production.calibrate(blocks)
        changed = deepcopy(blocks)
        for b in changed[2:]:
            b['baseline'][802] = 1
        final, _ = production.calibrate(changed)
        self.assertEqual(first['earlier_selected'], final['earlier_selected'])
        certificate, veto, accepted, reasons = audit.independent_certificate(changed, audit.fixed_choice(final['earlier_selected']), stats)
        self.assertEqual(certificate, final['certification'])
        self.assertEqual(veto, final['global_veto'])
        self.assertEqual(accepted, final['certification_passed'])
        self.assertEqual(reasons, final['certification_rejection_reasons'])
        # Protection already delivers these episodes. It cannot manufacture
        # added-positive support for the now unnecessary pending extension.
        self.assertEqual(certificate['pending']['coverage_event_ids'], [])
        self.assertFalse(certificate['pending']['passed'])
        self.assertEqual(final['final_selected'], audit.reference_choice())

    def test_no_complete_run_means_no_actual_source_access_or_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plan.json').write_text(json.dumps({'attempt': audit.ATTEMPT, 'scope': 'all', 'limit_cases': 19}))
            (root / 'results.json').write_text(json.dumps({'complete_cases': 18, 'periods': []}))
            with patch.object(audit.old, '_source_frames', side_effect=AssertionError('No source read')) as source:
                with self.assertRaises(ValueError):
                    audit.audit_directory(root, workspace_root=root)
                source.assert_not_called()
            self.assertFalse((root / 'audit.json').exists())

    def test_parent_auditor_source_is_pinned_without_touching_frozen_code(self):
        self.assertEqual(audit.sha(audit.v10.__file__), audit.V10_AUDITOR_SHA)
        self.assertEqual(audit.sha(audit.v9.__file__), audit.V9_AUDITOR_SHA)
        self.assertEqual(audit.method_spec({'attempt': audit.ATTEMPT})['bundle_version'], audit.VERSION)
        with self.assertRaises(ValueError):
            audit.method_spec({'attempt': 'unreviewed'})


if __name__ == '__main__':
    unittest.main()
