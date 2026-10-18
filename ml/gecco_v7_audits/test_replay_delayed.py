"""Synthetic-only tests for the independent delayed replay auditor."""
import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest

from ml.gecco_v6.unknown_label_metrics import comparison, stats
from ml.gecco_v7 import calibration_delayed as cal
from ml.gecco_v7 import recalibrate_delayed as runner
from ml.gecco_v7.test_calibration_delayed import confirmation_fixture
from ml.gecco_v7_audits import replay_delayed as audit


class ScalarTests(unittest.TestCase):
    def test_synthetic_fitted_estimator_roundtrip_and_actual_parameter_tampering(self):
        rng = np.random.default_rng(6622); x = rng.normal(size=(50, 2)); y = (x[:, 0] > 0).astype(int)
        for model in (IsolationForest(n_estimators=2, random_state=1).fit(x),
                      HistGradientBoostingClassifier(max_iter=2, min_samples_leaf=5, early_stopping=False, random_state=1).fit(x, y)):
            stream = BytesIO(); joblib.dump(model, stream); stream.seek(0); restored = joblib.load(stream)
            self.assertEqual(audit.fitted_state_digest(model), audit.fitted_state_digest(restored))
        original = np.random.default_rng(1); changed = np.random.default_rng(1)
        self.assertEqual(audit.fitted_state_digest(original), audit.fitted_state_digest(changed))
        changed.random()
        self.assertNotEqual(audit.fitted_state_digest(original), audit.fitted_state_digest(changed))

    def test_semantic_model_digest_ignores_only_padding_not_named_tree_values(self):
        dtype = np.dtype({'names': ['child', 'threshold'], 'formats': ['i4', 'f8'],
                          'offsets': [0, 8], 'itemsize': 24})
        a = np.zeros(3, dtype=dtype); b = np.zeros(3, dtype=dtype)
        a['child'] = b['child'] = [0, 1, 2]; a['threshold'] = b['threshold'] = [.1, .2, .3]
        b.view(np.uint8).reshape(3, 24)[:, 4:8] = 254
        b.view(np.uint8).reshape(3, 24)[:, 16:] = 123
        self.assertNotEqual(a.tobytes(), b.tobytes())
        self.assertEqual(audit.fitted_state_digest(a), audit.fitted_state_digest(b))
        b['threshold'][1] += .001
        self.assertNotEqual(audit.fitted_state_digest(a), audit.fitted_state_digest(b))

    def test_seed_and_rescue_against_live_predictor_for_all_policies(self):
        rng = np.random.default_rng(6621)
        for n in (0, 1, 2, 11, 201):
            reference = rng.choice([-1, 0, 1], n).astype(np.int8)
            confidence = rng.random(n); confidence[::9] = np.nan
            rescue = rng.random(n); rescue[::7] = np.nan
            for policy in ('instant', '2of3', '3of5'):
                for lo, hi, deadline in ((None, None, 0), (.3, None, 1), (.3, None, 2), (None, .8, 0), (.3, .8, 2)):
                    choice = cal._choice(lo, hi, policy, deadline)
                    actual, seed = audit.scalar_prediction(reference, confidence, rescue, choice)
                    np.testing.assert_array_equal(actual, cal.predict(reference, confidence, choice, rescue))
                    np.testing.assert_array_equal(seed >= 0, reference >= 0)
                    for stop in (0, 1, min(50, n), n):
                        prefix, _ = audit.scalar_prediction(reference[:stop], confidence[:stop], rescue[:stop], choice)
                        np.testing.assert_array_equal(prefix, actual[:stop])

    def test_short_removed_pulse_can_produce_720_second_event_delay(self):
        labels = np.r_[0, np.ones(25), 0].astype(np.int8)
        reference = np.zeros(len(labels), np.int8); reference[1] = 1; reference[11:20] = 1
        choice = cal._choice(.5, confirmation_samples=2)
        candidate, _ = audit.scalar_prediction(reference, np.zeros(len(labels)), np.full(len(labels), np.nan), choice)
        result = audit.comparisons(labels, {'baseline': reference, 'reference': reference, 'candidate': candidate}, comparison)['v6_vs_v7']
        self.assertEqual(candidate[13], 1)
        self.assertEqual(result['maximum_observed_paired_extra_delay_seconds'], 720)
        self.assertFalse(result['noninferior'])
        self.assertEqual(result['lost_baseline_event_ids'], [])

    def test_unknown_score_releases_but_reference_missing_resets(self):
        reference = np.array([0, 1, 1, -1, 1, 1, 1], np.int8)
        score = np.array([0., .1, np.nan, 0., .1, .1, .1])
        actual, _ = audit.scalar_prediction(reference, score, np.full(7, np.nan), cal._choice(.5, confirmation_samples=2))
        np.testing.assert_array_equal(actual, [0, 0, 1, -1, 0, 0, 1])

    def test_invalid_physical_deadlines_rejected(self):
        for cadence, deadline in ((300, 1), (90, 2), (60, 3)):
            with self.assertRaises(ValueError):
                audit.scalar_prediction([0, 1], [0., .1], [0., .1], cal._choice(.5, confirmation_samples=deadline, cadence_seconds=cadence))

    def test_current_evidence_masks_are_exclusive_and_missing_conservative(self):
        local = np.array([[1., .2, .3], [1.1, .2, .3], [np.nan, 2., .2], [.2, .2, .2]])
        gate, rescue = audit.independent_masks(local, [.4, .5, .6, np.nan])
        np.testing.assert_allclose(gate, [.4, np.nan, np.nan, np.nan], equal_nan=True)
        np.testing.assert_allclose(rescue, [np.nan, .5, np.nan, np.nan], equal_nan=True)


class AccountingTests(unittest.TestCase):
    def test_independent_120s_comparisons_and_summary_match_runner(self):
        labels = np.array([0, 1, 1, 1, 0, 0, 1, 1, 1, 0], np.int8)
        baseline = np.array([0, 1, 1, 0, 0, 1, 0, 0, 0, 0], np.int8)
        candidate = np.array([0, 0, 0, 1, 0, 0, 1, 0, 0, 0], np.int8)
        arrays = {'baseline': baseline, 'reference': baseline, 'candidate': candidate}
        measured = audit.comparisons(labels, arrays, comparison)
        expected = runner.assess(labels, baseline, baseline, candidate)
        check = audit.old.Checks(); check.tree('full', measured, expected)
        self.assertTrue(all(c['passed'] for c in check.records))
        periods = [{'case': str(i), 'comparisons': measured} for i in range(19)]
        sources = {'synthetic': measured}
        check.tree('summary', audit.summary(periods, sources), runner.summarize(periods, sources))
        self.assertTrue(all(c['passed'] for c in check.records))

    def test_calibration_scalar_accounting_and_tampered_candidate_detection(self):
        blocks = confirmation_fixture()
        selected, trials = cal.calibrate(blocks)
        frames = []; index = 100
        bounds = [index]
        for block in blocks:
            n = len(block['labels'])
            # This fixture has no rescue; all local scores are quiet.
            frame = pd.DataFrame({'sample_index': np.arange(index, index+n), 'label': block['labels'],
                                  'baseline': block['reference'], 'reference': block['reference'],
                                  'long_context': block['long_scores'], 'guarded_long_context': block['long_scores'],
                                  'rescue_long_context': np.nan,
                                  'candidate': cal.predict(block['reference'], block['long_scores'], selected, block['rescue_scores'])})
            frames.append(frame); index += n; bounds.append(index)
        table = pd.concat(frames, ignore_index=True)
        selected = {**selected, 'evidence': {**selected['evidence'], 'source_range': [bounds[0], bounds[-1]]}}
        prior = table.assign(level=.2, jump=.3, sustained=.4)
        checks = audit.old.Checks()
        audit._calibration(checks, 'synthetic', table, prior, table, bounds, selected, comparison, stats)
        audit._trial_selection(checks, 'synthetic', pd.DataFrame(trials), selected)
        self.assertTrue(all(c['passed'] for c in checks.records), checks.records)
        changed = table.copy(); changed.loc[50, 'candidate'] = 1
        checks = audit.old.Checks()
        audit._calibration(checks, 'tampered', changed, prior, table, bounds, selected, comparison, stats)
        self.assertFalse(all(c['passed'] for c in checks.records))

    def test_incomplete_run_refuses_source_or_bundle_access_and_report_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plan.json').write_text(json.dumps({'attempt': audit.ATTEMPT, 'expected_cases': 19}))
            (root / 'results.json').write_text(json.dumps({'complete_cases': 18, 'expected_cases': 19}))
            with patch.object(audit.old, '_source_frames', side_effect=AssertionError('Must not read sources')):
                with self.assertRaises(ValueError): audit.audit_directory(root, workspace_root=root)
            self.assertFalse((root / 'audit.json').exists())


if __name__ == '__main__':
    unittest.main()
