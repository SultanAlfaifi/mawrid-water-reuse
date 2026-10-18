"""Synthetic-only tests for the independent V10 oracle and caller contract."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from ml.gecco_v10_audits import replay as audit
from ml.gecco_v10 import calibration as production
from ml.gecco_v6.unknown_label_metrics import stats


def blocks_fixture():
    blocks = []
    for i in range(4):
        n = 4000
        y, r = np.zeros(n, np.int8), np.zeros(n, np.int8)
        score = np.full(n, .1)
        rescue = np.full(n, np.nan)
        for start in (200, 500, 800):
            y[start:start + 12] = 1
            r[start + 2:start + 5] = 1
            score[start + 3:start + 5] = .9
        r[802:805] = 0
        r[802] = 1
        score[803] = .9
        r[1000] = 1  # Suppressible normal pulse; no later confidence crossing.
        blocks.append(dict(labels=y, reference=r, long_scores=score, rescue_scores=rescue,
                           source_start=i * n, block_id=str(i)))
    return blocks


def assert_checks(test, checks):
    failures = [r for r in checks.records if not r['passed']]
    test.assertEqual(failures, [], str(failures[:5]))


class ScalarAndPulseTests(unittest.TestCase):
    def test_scalar_matches_all_paths_and_original_prefixes(self):
        rng = np.random.default_rng(20261017)
        for n in (0, 1, 2, 5, 80, 411):
            r = rng.choice([-1, 0, 1], n).astype(np.int8)
            s, rescue = rng.random(n), rng.random(n)
            s[::11] = np.nan
            s[::17] = np.inf
            rescue[::13] = np.nan
            for pending in (False, True):
                for deadline in (1, 2):
                    for high in (None, .8):
                        for policy in ('instant', '2of3', '3of5'):
                            choice = production._choice(.5, high, policy, deadline, 60, pending)
                            final, seed, a0, trace = audit.scalar_paths(r, s, rescue, choice)
                            np.testing.assert_array_equal(final, production.predict(r, s, choice, rescue))
                            for actual, expected in zip((seed, a0, trace), production._confirmation(r, s, .5, deadline, pending)):
                                np.testing.assert_array_equal(actual, expected)
                            for stop in sorted({0, min(2, n), n // 2, n}):
                                for before, after in zip(audit.scalar_paths(r[:stop], s[:stop], rescue[:stop], choice), (final, seed, a0, trace)):
                                    np.testing.assert_array_equal(before, after[:stop])
                            np.testing.assert_array_equal(final >= 0, r >= 0)

    def test_deadline_owner_new_pulse_unknown_and_no_force_after_clear(self):
        choice = production._choice(.5, confirmation_samples=2, pending_after_clear=True)
        fixtures = [([1, 0, 0], [.1, .1, .8], [0, 0, 1], [-1, -1, 0]),
            ([1, 0, 0, 0], [.1, .1, .1, .8], [0, 0, 0, 0], [-1] * 4),
            ([1, -1, 0], [.1, .8, .8], [0, -1, 0], [-1] * 3),
            ([1, 0, 0], [.1, np.nan, np.inf], [0, 0, 0], [-1] * 3),
            ([1, 0, 1, 1, 1], [.1, .1, .1, .1, .1], [0, 0, 0, 0, 1], [-1] * 5),
            ([1, 0, 1, 1], [.1, .1, .8, .1], [0, 0, 1, 1], [-1, -1, 0, -1])]
        for r, s, p, origins in fixtures:
            result, _, _, trace = audit.scalar_paths(np.array(r), s, s, choice)
            np.testing.assert_array_equal(result, p)
            np.testing.assert_array_equal(trace, origins)

    def test_pulse_obligation_cannot_use_rescue_unrelated_or_postunknown_alarm(self):
        choice = production._choice(.5, confirmation_samples=2, pending_after_clear=True)
        y, r = np.array([0, 1, 1, 1, 0]), np.array([0, 1, 0, 0, 0])
        p, t = np.array([0, 0, 0, 1, 0]), np.array([-1, -1, -1, 1, -1])
        good = audit.pulse_scope(y, r, p, t, choice, 100)
        self.assertTrue(good['passed'])
        self.assertFalse(audit.pulse_scope(y, r, p, np.full(5, -1), choice, 100)['passed'])
        y[2] = -1
        self.assertFalse(audit.pulse_scope(y, r, p, t, choice, 100)['passed'])
        # An independent rescue row cannot hide a failed pure seed.
        y = np.array([0, 1, 1, 1, 0])
        final, seed, _, trace = audit.scalar_paths(r, np.zeros(5), np.ones(5), {**choice, 'high_threshold': .8})
        self.assertEqual(final[1], 1)
        self.assertFalse(audit.pulse_scope(y, r, seed, trace, choice, 100)['passed'])

    def test_pulse_scalar_parity_with_unknown_segments_and_block_crossing(self):
        rng = np.random.default_rng(121)
        choice = production._choice(.5, confirmation_samples=2, pending_after_clear=True)
        for _ in range(40):
            blocks = []
            for i in range(4):
                n = 21
                blocks.append(dict(labels=rng.choice([-1, 0, 1], n).astype(np.int8),
                    reference=rng.choice([-1, 0, 1], n).astype(np.int8), long_scores=rng.random(n),
                    rescue_scores=np.full(n, np.nan), source_start=i * n, block_id=str(i)))
            paths = [audit.scalar_paths(b['reference'], b['long_scores'], b['rescue_scores'], choice) for b in blocks]
            seeds, traces = [p[1] for p in paths], [p[3] for p in paths]
            self.assertEqual(audit.pulse_assessment(blocks, seeds, traces, choice), production._pulse_assessment(blocks, seeds, traces, choice))
        blocks = [dict(labels=np.array([0, 1, 1]), reference=np.array([0, 1, 1]), source_start=0),
                  dict(labels=np.array([1, 1, 0]), reference=np.array([1, 0, 0]), source_start=3)]
        seeds = [np.array([0, 0, 0]), np.array([0, 1, 0])]
        traces = [np.full(3, -1), np.array([-1, 0, -1])]
        self.assertEqual(audit.pulse_assessment(blocks, seeds, traces, choice), production._pulse_assessment(blocks, seeds, traces, choice))
        self.assertFalse(audit.pulse_assessment(blocks, seeds, traces, choice)['passed'])

    def test_invalid_physical_contract_and_shapes_rejected(self):
        good = production._choice(.5, confirmation_samples=2, pending_after_clear=True)
        for bad in ({**good, 'cadence_seconds': 90}, {**good, 'pending_after_clear': 1},
                    {**good, 'confirmation_samples': True}, {**good, 'low_threshold': np.nan},
                    {**good, 'low_threshold': None}, {**good, 'max_confirmation_seconds': 180}):
            with self.assertRaises(ValueError):
                audit.scalar_paths(np.array([1, 0]), [.1, .8], [.1, .8], bad)
        with self.assertRaises(ValueError):
            audit.scalar_paths(np.array([1, 0]), [.1], [.1], good)


class CalibrationAuditTests(unittest.TestCase):
    def test_certificate_veto_and_saved_calibration_recomputed_on_synthetic_rows(self):
        blocks = blocks_fixture()
        selected, trials = production.calibrate(blocks)
        self.assertTrue(selected['pending_after_clear'])
        self.assertTrue(selected['certification_passed'])
        cal = pd.concat([pd.DataFrame({'sample_index': np.arange(b['source_start'], b['source_start'] + len(b['labels'])),
            'label': b['labels'], 'baseline': b['reference'], 'reference': b['reference'],
            'long_context': b['long_scores'], 'guarded_long_context': b['long_scores'],
            'rescue_long_context': b['rescue_scores'],
            'candidate': production.predict(b['reference'], b['long_scores'], selected, b['rescue_scores'])}) for b in blocks], ignore_index=True)
        prior = pd.DataFrame({'sample_index': cal.sample_index, 'level': .1, 'jump': .1, 'sustained': .1})
        checks = audit.Checks()
        audit._calibration(checks, 'synthetic', cal, prior, cal, [0, 4000, 8000, 12000, 16000], selected, None, stats)
        # Exercise the actual gzip/CSV dtype round-trip used by the runner.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'trials.csv.gz'
            pd.DataFrame(trials).to_csv(path, index=False)
            audit._trial_selection(checks, 'synthetic', pd.read_csv(path, float_precision='round_trip'), selected)
        assert_checks(self, checks)
        broken = deepcopy(selected)
        broken['certification']['pending']['added_known_normal_rows'] += 1
        checks = audit.Checks()
        audit._calibration(checks, 'tampered', cal, prior, cal, [0, 4000, 8000, 12000, 16000], broken, None, stats)
        self.assertTrue(any(not c['passed'] for c in checks.records))

    def test_late_labels_only_veto_early_choice_and_pending_normal_additions(self):
        blocks = blocks_fixture()
        first, _ = production.calibrate(blocks)
        changed = deepcopy(blocks)
        for b in changed[2:]:
            b['labels'][803] = 0  # Same sensor confidence; now a charged normal addition.
        second, _ = production.calibrate(changed)
        self.assertEqual(first['earlier_selected'], second['earlier_selected'])
        self.assertEqual(second['final_selected'], audit.reference_choice())
        certificate, veto, accepted, reasons = audit.independent_certificate(changed, audit.fixed_choice(second['earlier_selected']), stats)
        self.assertFalse(accepted)
        self.assertEqual(certificate, second['certification'])
        self.assertEqual(veto, second['global_veto'])
        self.assertEqual(reasons, second['certification_rejection_reasons'])
        self.assertEqual(certificate['pending']['added_known_normal_rows'], 2)

    def test_unknown_additions_supply_neither_normal_cost_nor_primary_evidence(self):
        blocks = blocks_fixture()[2:]
        choice = production._choice(.5, confirmation_samples=2, pending_after_clear=True)
        for b in blocks:
            b['labels'][800:812] = -1
        expected = audit.fixed_checks(blocks, choice, stats)
        actual = production._fixed_checks(blocks, choice, 60)
        self.assertEqual(expected, actual)
        self.assertEqual(expected['pending']['added_known_normal_rows'], 0)
        self.assertEqual(expected['pending']['coverage_event_ids'], [])
        self.assertFalse(expected['pending']['passed'])

    def test_incomplete_run_blocks_source_access_and_no_audit_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plan.json').write_text(json.dumps({'attempt': audit.ATTEMPT, 'scope': 'all', 'limit_cases': 19}))
            (root / 'results.json').write_text(json.dumps({'complete_cases': 18, 'periods': []}))
            with patch.object(audit.old, '_source_frames', side_effect=AssertionError('Must not read source')) as source:
                with self.assertRaises(ValueError):
                    audit.audit_directory(root, workspace_root=root)
                source.assert_not_called()
            self.assertFalse((root / 'audit.json').exists())


class RunnerContractTests(unittest.TestCase):
    def test_reuses_models_and_freezes_before_outer_scores(self):
        from ml.gecco_v10 import development as runner
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            parent, out, prior = root / 'parent', root / 'out', root / 'prior'
            parent.mkdir(); out.mkdir(); prior.mkdir()
            source = parent / 'synthetic'; source.mkdir()
            (out / 'plan.json').write_text('{}')
            starts = [200, 220, 240, 260]
            cal = pd.DataFrame({'sample_index': np.arange(200, 280), 'label': 0, 'baseline': 0,
                'reference': 0, 'candidate': 0, 'long_context': .2,
                'guarded_long_context': .2, 'rescue_long_context': np.nan, 'conditional_observed': True})
            outer = pd.DataFrame({'sample_index': np.arange(280, 290), 'label': 0, 'baseline': 0,
                'reference': 0, 'candidate': 0, 'long_context': .2,
                'guarded_long_context': .2, 'rescue_long_context': np.nan, 'conditional_observed': True})
            cal.to_csv(source / 'calibration_scores.csv.gz', index=False)
            outer.to_csv(source / 'predictions.csv.gz', index=False)
            pd.DataFrame({'sample_index': cal.sample_index, 'EVENT': 0, 'level': .1, 'jump': .1, 'sustained': .1}).to_csv(prior / 'calibration_scores.csv.gz', index=False)
            bundle = dict(version=audit.v9.VERSION, max_fit_index=199, max_calibration_index=279,
                long_model={'fitted_coefficients': np.array([2.0, 3.0])}, reference_bundle={'fitted_threshold': .9}, selected={'old': True})
            joblib.dump(bundle, source / 'bundle.joblib')
            (source / 'model_inspection.json').write_text('{}')
            (source / 'results.json').write_text('{}')
            frozen = dict(train=[0, 200], test=[280, 290], calibration_starts=starts,
                prior_folder='prior', prior_sha256={'calibration_scores.csv.gz': runner.sha(prior / 'calibration_scores.csv.gz')},
                bundle_sha256=runner.sha(source / 'bundle.joblib'))
            (source / 'freeze.json').write_text(json.dumps(frozen))
            selected = audit.reference_choice()
            calls = []
            def calibrate(blocks, **kwargs):
                self.assertEqual([b['source_start'] for b in blocks], starts)
                self.assertEqual(sum(len(b['labels']) for b in blocks), 80)
                self.assertFalse((out / 'synthetic' / 'freeze.json').exists())
                calls.append('past_calibration')
                return selected, [dict(selected, feasible=True)]
            def load_outer(path):
                self.assertEqual(calls, ['past_calibration'])
                frozen_now = json.loads((out / 'synthetic' / 'freeze.json').read_text())
                self.assertEqual(frozen_now['selected'], selected)
                self.assertTrue(frozen_now['training_reused_without_refit'])
                self.assertEqual(frozen_now['bundle_sha256'], runner.sha(out / 'synthetic' / 'bundle.joblib'))
                new = joblib.load(out / 'synthetic' / 'bundle.joblib')
                for key in ('long_model', 'reference_bundle'):
                    self.assertEqual(audit.cert.fitted_state_digest(new[key]), audit.cert.fitted_state_digest(bundle[key]))
                calls.append('outer_after_freeze')
                return outer.copy()
            fake = {'v6_vs_v7': dict(baseline={'confirmed_events': 0, 'false_positive_runs': 0},
                candidate={'confirmed_events': 0, 'false_positive_runs': 0}, lost_baseline_event_ids=[], noninferior=True)}
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'verify'), patch.object(runner, 'calibrate', side_effect=calibrate), \
                    patch.object(runner, 'load_outer', side_effect=load_outer), patch.object(runner, 'assess', return_value=fake), redirect_stdout(StringIO()):
                result, rows = runner.run_case(dict(case='synthetic', source='2018', fit_status='fitted', conditional_block_test_coverage={}), parent, out, {})
            self.assertEqual(calls, ['past_calibration', 'outer_after_freeze'])
            self.assertFalse(result['model_refitted'])
            np.testing.assert_array_equal(rows.v9_candidate, outer.candidate)


if __name__ == '__main__':
    unittest.main()
