"""Synthetic-only V14 IF evidence and caller isolation audit checks."""
from copy import copy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from ml.gecco_v14_audits import replay as audit
from ml.gecco_v14.pulse_weighting import SensorTailPulseHGBScorer
from ml.gecco_v9.conditional import ConditionalResidualHGBScorer
from ml.gecco_v2.candidates_supervised import build_features


class SpyClassifier:
    def __init__(self, **kwargs): self.parameters = kwargs
    def fit(self, x, y, sample_weight):
        self.fitted_shape = x.shape; self.weights = sample_weight.copy(); self.labels = y.copy()
        return self


def fixture(n=600):
    rng = np.random.default_rng(84591)
    x = rng.normal(size=(n, 4))
    x[:, 1] = x[:, 0] * .4 + x[:, 1] * .2
    frame = pd.DataFrame(x, columns=list('abcd'))
    labels = np.zeros(n, np.int8)
    labels[180:196] = 1; labels[230:240] = -1; labels[430:440] = 1
    frame.loc[300:302, 'd'] = np.nan
    return frame, labels


def make_estimator(frame, labels):
    x, eligible, _ = build_features(frame, 'baseline15', list(frame.columns))
    mask = audit.baseline_fit_mask_oracle(frame, labels, list(frame.columns))
    return IsolationForest(n_estimators=200, max_samples=256, contamination='auto',
        n_jobs=1, random_state=20261016).fit(x[mask])


def make_model(frame, labels, estimator):
    from ml.gecco_v14 import pulse_weighting
    with patch.object(pulse_weighting, 'HistGradientBoostingClassifier', SpyClassifier):
        return SensorTailPulseHGBScorer(list(frame.columns), estimator).fit(frame, labels)


class EvidenceOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.labels = fixture()
        cls.estimator = make_estimator(cls.frame, cls.labels)
        cls.model = make_model(cls.frame, cls.labels, cls.estimator)

    def assert_checks(self, checks):
        self.assertTrue(all(row['passed'] for row in checks.records),
                        [row for row in checks.records if not row['passed']])

    def test_independent_baseline_input_matrix_names_and_missing_mask(self):
        frame = self.frame.copy(); frame.loc[330, 'a'] = np.inf
        actual = audit.baseline_input_oracle(frame, list(frame.columns))
        expected = build_features(frame, 'baseline15', list(frame.columns))
        np.testing.assert_array_equal(actual[0], expected[0])
        np.testing.assert_array_equal(actual[1], expected[1])
        self.assertEqual(actual[2], expected[2])
        self.assertFalse(actual[1][330:345].any())
        self.assertTrue(actual[1][345])
        for n in (0, 1, 14, 15):
            a = audit.baseline_input_oracle(frame.iloc[:n], list(frame.columns))
            self.assertEqual(a[0].shape, (n, 16))
            self.assertEqual(a[1].sum(), int(n == 15))

    def test_normal_windows_exclude_unknown_positive_and_nonadjacent_rows(self):
        frame = pd.DataFrame({'a': np.arange(80, dtype=float)})
        labels = np.zeros(80, np.int8); labels[20] = -1; labels[45] = 1
        frame.loc[65, 'a'] = np.nan
        mask = audit.baseline_fit_mask_oracle(frame, labels, ['a'])
        expected = np.array([i >= 14 and np.all(labels[i-14:i+1] == 0)
            and np.isfinite(frame.a.iloc[max(0, i-14):i+1]).all() for i in range(80)])
        np.testing.assert_array_equal(mask, expected)
        self.assertFalse(mask[20:35].any()); self.assertTrue(mask[35])
        self.assertFalse(mask[45:60].any()); self.assertTrue(mask[60])

    def test_actual_synthetic_added_features_and_if_state_are_independently_verified(self):
        checks = audit.Checks()
        audit.audit_if_frame(checks, 'synthetic', self.model, self.frame)
        self.assert_checks(checks)
        self.assertEqual(self.model.baseline_features(self.frame).dtype, np.float32)
        with patch.object(IsolationForest, 'fit', side_effect=AssertionError('IF must never fit')):
            make_model(self.frame, self.labels, self.estimator)
            self.model.baseline_raw_scores(self.frame)

    def test_original_weights_references_ridge_prefix_and_availability_remain_unchanged(self):
        checks = audit.Checks()
        weights = audit.audit_training(checks, 'synthetic', self.model, self.frame, self.labels)
        conditional = audit.audit_conditional_training(checks, 'synthetic', self.model, self.frame, self.labels)
        audit.audit_conditional_frame(checks, 'synthetic', self.model, self.frame, conditional)
        self.assert_checks(checks)
        self.assertEqual(self.model.model_.fitted_shape[1], len(self.model.v9_feature_names_) + 2)
        np.testing.assert_array_equal(self.model.model_.weights, weights['sample'][weights['eligible']])
        np.testing.assert_array_equal(self.model.model_.labels, self.labels[weights['eligible']])

    def test_none_estimator_does_not_remove_original_available_rows(self):
        model = make_model(self.frame, self.labels, None)
        full, available = model.features(self.frame)
        view = copy(model); view.feature_names_ = model.v9_feature_names_
        original, old_available = ConditionalResidualHGBScorer.features(view, self.frame)
        np.testing.assert_array_equal(full[:, :-2], original)
        np.testing.assert_array_equal(full[:, -2:], np.zeros((len(full), 2), np.float32))
        np.testing.assert_array_equal(available, old_available)
        self.assertTrue(available.any())
        checks = audit.Checks(); audit.audit_if_frame(checks, 'none', model, self.frame)
        self.assert_checks(checks)

    def test_prefix_future_and_label_mutations_do_not_change_if_features(self):
        frame = self.frame.iloc[:260].copy(); original = self.model.baseline_features(frame)
        for stop in (0, 1, 14, 15, 60, 121, 260):
            np.testing.assert_array_equal(self.model.baseline_features(frame.iloc[:stop]), original[:stop])
        altered = frame.copy(); altered.iloc[121:] = -1e9
        np.testing.assert_array_equal(self.model.baseline_features(altered)[:121], original[:121])
        np.testing.assert_array_equal(self.model.baseline_features(frame.assign(EVENT=1, label=-1)), original)

    def test_serialized_if_semantic_identity_and_attachment_hash_remain_unchanged(self):
        before = audit.certified.fitted_state_digest(self.estimator)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bundle.joblib'; joblib.dump(self.model, path, compress=3)
            restored = joblib.load(path)
            self.assertEqual(before, audit.certified.fitted_state_digest(restored.baseline_estimator_))
            self.assertEqual(restored.baseline_state_hash_at_attachment_, audit.certified.fitted_state_digest(restored.baseline_estimator_))
            np.testing.assert_array_equal(restored.baseline_raw_scores(self.frame), self.model.baseline_raw_scores(self.frame))

    def test_corrupt_or_wrong_origin_estimator_is_detected(self):
        original = audit.certified.fitted_state_digest(self.estimator)
        restored = copy(self.model); restored.baseline_estimator_ = copy(self.estimator)
        restored.baseline_estimator_.offset_ = -.7
        self.assertNotEqual(original, audit.certified.fitted_state_digest(restored.baseline_estimator_))
        self.assertNotEqual(restored.baseline_state_hash_at_attachment_, audit.certified.fitted_state_digest(restored.baseline_estimator_))
        # Offset does not affect score_samples: semantic lineage catches what
        # score replay alone would miss.
        np.testing.assert_array_equal(restored.baseline_raw_scores(self.frame), self.model.baseline_raw_scores(self.frame))

    def test_saved_prior_if_lineage_and_known_normal_population_are_both_checked(self):
        count = int(audit.baseline_fit_mask_oracle(self.frame, self.labels, self.model.channels).sum())
        prior = {'prior_bundle': {'model': SimpleNamespace(baseline_=self.estimator, baseline_fit_rows_=count)},
                 'max_fit_index': len(self.frame)-1}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); joblib.dump(prior, folder / 'bundle.joblib')
            checks = audit.Checks()
            result = audit.audit_if_lineage(checks, 'synthetic', self.model, {'reference_bundle': prior},
                self.frame, self.labels, folder, {})
            self.assert_checks(checks)
            self.assertEqual(result['original_known_normal_training_windows'], count)
            # Same model scores cannot hide a falsely declared normal fit count.
            prior['prior_bundle']['model'].baseline_fit_rows_ -= 1
            joblib.dump(prior, folder / 'bundle.joblib')
            checks = audit.Checks()
            with self.assertRaisesRegex(ValueError, 'known_normal_fit_population'):
                audit.audit_if_lineage(checks, 'wrong_count', self.model, {'reference_bundle': prior},
                    self.frame, self.labels, folder, {})
            self.assertTrue(any(not r['passed'] for r in checks.records))

    def test_nonfinite_and_unrepresentable_scores_disable_only_added_evidence(self):
        for value in (np.nan, np.inf, 1e100):
            with patch.object(self.estimator, 'score_samples', side_effect=lambda x, v=value: np.full(len(x), v)):
                raw, block, _, _ = audit.baseline_feature_oracle(self.frame, self.model.channels, self.estimator)
                np.testing.assert_array_equal(block, self.model.baseline_features(self.frame))
                self.assertFalse(block.any())

    def test_v10_scalar_policy_is_exact_frozen_policy_not_v11_protection(self):
        from ml.gecco_v10.calibration import predict
        choice = audit.v10.reference_choice()
        choice.update(decision='candidate', low_threshold=.5, confirmation_samples=2,
                      confirmation_delay_seconds=120., pending_after_clear=True)
        ref = np.array([0, 1, 0, 0, 1, 1, 0, -1], np.int8)
        scores = np.array([.1, .1, .1, .8, .1, .8, .1, .1])
        rescue = np.full(len(ref), np.nan)
        actual, _ = audit.scalar_prediction(ref, scores, rescue, choice)
        np.testing.assert_array_equal(actual, predict(ref, scores, choice, rescue))
        self.assertEqual(actual[1], 0)  # No automatic retained-IF hard protection.


class CompleteGateTests(unittest.TestCase):
    def manifest(self):
        plan = {'case_order': list(audit.EXPECTED_NAMES), 'reference_sha256': {}, 'input_sha256': {}}
        for i, name in enumerate(audit.EXPECTED_NAMES):
            folder = ('output/ml/gecco-v6-development/run_04' if i < 13 else
                      'output/ml/gecco-v6-waterhub-first-use') + '/' + name
            files = {filename: 'a' * 64 for filename in audit.REFERENCE_FILES}
            plan['reference_sha256'][name] = {'folder': folder, 'files': files}
            plan['input_sha256'].update({folder + '/' + key: value for key, value in files.items()})
        return plan

    def test_upfront_reference_manifest_checks_all19_without_opening_values(self):
        checks = audit.Checks()
        with patch.object(Path, 'open', side_effect=AssertionError('Metadata check must not open source')):
            audit.verify_reference_manifest(self.manifest(), checks)
        self.assertTrue(all(r['passed'] for r in checks.records))
        self.assertEqual(len([r for r in checks.records if ':upfront_reference_in_input_closure:' in r['check']]), 76)

    def test_upfront_reference_manifest_rejects_changed_case_folder_hash_or_missing_input(self):
        for failure in ('order', 'missing_case', 'folder', 'hash', 'missing_input', 'extra_file'):
            with self.subTest(failure=failure):
                plan = self.manifest(); first = audit.EXPECTED_NAMES[0]
                record = plan['reference_sha256'][first]
                if failure == 'order': plan['case_order'].reverse()
                elif failure == 'missing_case': plan['reference_sha256'].pop(first)
                elif failure == 'folder': record['folder'] = 'output/other'
                elif failure == 'hash': record['files']['bundle.joblib'] = 'b' * 64
                elif failure == 'missing_input': plan['input_sha256'].pop(record['folder'] + '/bundle.joblib')
                elif failure == 'extra_file': record['files']['unplanned.joblib'] = 'a' * 64
                with self.assertRaises(ValueError):
                    audit.verify_reference_manifest(plan, audit.Checks())

    def test_incomplete_run_cannot_open_sources_or_write_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plan.json').write_text(json.dumps({'attempt': audit.ATTEMPT, 'scope': 'all', 'limit_cases': 19}))
            (root / 'results.json').write_text(json.dumps({'complete_cases': 1, 'expected_cases': 19}))
            with patch.object(audit, '_source_frames', side_effect=AssertionError('No source access')):
                with self.assertRaises(ValueError): audit.audit_directory(root, workspace_root=root)
            self.assertFalse((root / 'audit.json').exists())

    def test_only_exact_v14_attempt_and_class_are_accepted(self):
        result = audit.method_spec({'attempt': audit.ATTEMPT})
        self.assertEqual(result['runtime'], 'ml.gecco_v14.runtime')
        self.assertEqual(result['model_class'], 'SensorTailPulseHGBScorer')
        with self.assertRaises(ValueError): audit.method_spec({'attempt': 'v11'})


class TrainingTamperTests(unittest.TestCase):
    def test_independent_training_audit_detects_wrong_q95_mask_raw_weights_and_metadata(self):
        from copy import deepcopy
        frame, labels = fixture(); model = make_model(frame, labels, make_estimator(frame, labels))
        for field in ('q95', 'population', 'tail', 'weight', 'raw', 'metadata'):
            with self.subTest(field=field):
                altered = deepcopy(model)
                if field == 'q95': altered.pulse_q95_ += .01
                elif field == 'population': altered.pulse_quantile_mask_[0] = True
                elif field == 'tail': altered.pulse_tail_mask_[100] = not altered.pulse_tail_mask_[100]
                elif field == 'weight': altered.training_normalized_weight_[100] += .1
                elif field == 'raw': altered.pulse_raw_scores_[100] += .01
                else: altered.pulse_weighting_audit_['eligible_bonus_rows'] += 1
                checks = audit.Checks()
                audit.audit_training(checks, field, altered, frame, labels)
                self.assertTrue(any(not row['passed'] for row in checks.records), field)

    def test_auditor_never_calls_production_weight_helper(self):
        frame, labels = fixture(); model = make_model(frame, labels, make_estimator(frame, labels))
        with patch.object(SensorTailPulseHGBScorer, '_prepare_pulses', side_effect=AssertionError('No production weight helper')):
            checks = audit.Checks(); audit.audit_training(checks, 'independent', model, frame, labels)
            self.assertTrue(all(r['passed'] for r in checks.records))


class HistoricalArtifactTests(unittest.TestCase):
    """Tiny19-case artifacts entirely generated here; no real output access."""
    def setUp(self):
        from ml.gecco_v6.unknown_label_metrics import stats, comparison
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.out = self.root/'candidate'; self.out.mkdir()
        self.stats, self.comparison = stats, comparison
        self.plan = {'historical_comparison_sha256': {}, 'input_sha256': {}}
        self.hashes, self.periods = {}, []
        self.current = {}
        counts = {}
        for i, name in enumerate(audit.EXPECTED_NAMES):
            source = '2017' if i < 6 else '2018' if i < 12 else '2019' if i == 12 else 'WaterHub'
            start = counts.get(source, 0); counts[source] = start+6
            frame = pd.DataFrame({'sample_index': np.arange(start, start+6),
                'label': [0, 1, 1, 0, 0, 0], 'baseline': [0, 1, 0, 0, 0, 0],
                'reference': [0, 1, 0, 0, 0, 0], 'candidate': [0, 1, 0, 0, 0, 0]})
            folder = self.out/name; folder.mkdir(); path = folder/'predictions.csv.gz'
            frame.to_csv(path, index=False); self.hashes[name+'/predictions.csv.gz'] = audit.sha(path)
            self.periods.append({'case': name, 'source': source}); self.current[name] = frame
        for version, auditor_sha in audit.HISTORICAL_AUDITOR_SHA.items():
            base = self.root/f'output/ml/gecco-{version}-development/run_01'; base.mkdir(parents=True)
            proof = {'passed': True, 'complete_replayed_cases': 19, 'audit_script_sha256': auditor_sha, 'hashes': {}}
            saved = []
            for period in self.periods:
                name = period['case']; frame = self.current[name].copy(); frame.loc[5, 'candidate'] = 1
                folder = base/name; folder.mkdir(); path = folder/'predictions.csv.gz'
                frame.to_csv(path, index=False); proof['hashes'][name+'/predictions.csv.gz'] = audit.sha(path)
                saved.append({**period, 'comparisons': {'v6_vs_v7': {'candidate': stats(frame.label.to_numpy(), frame.candidate.to_numpy(), 60)}}})
            (base/'plan.json').write_text('{}')
            (base/'results.json').write_text(json.dumps({'periods': saved}))
            proof['hashes'].update({name: audit.sha(base/name) for name in ('plan.json', 'results.json')})
            (base/'audit.json').write_text(json.dumps(proof))
            for name in ('plan.json', 'results.json', 'audit.json'):
                relative = str((base/name).relative_to(self.root))
                self.plan['historical_comparison_sha256'][relative] = audit.sha(base/name)
                self.plan['input_sha256'][relative] = audit.sha(base/name)

    def tearDown(self): self.temp.cleanup()

    def run_audit(self):
        checks = audit.Checks()
        result = audit.audit_historical_comparisons(self.root, self.out, self.plan, checks,
            self.hashes, self.periods, self.comparison, self.stats)
        return result, checks

    def test_all19_historical_artifacts_bind_hashes_axes_metrics_and_source_pools(self):
        result, checks = self.run_audit()
        self.assertTrue(all(row['passed'] for row in checks.records))
        self.assertEqual(set(result['source_pools']), {'2017', '2018', '2019', 'WaterHub'})
        self.assertEqual(len(result['periods']), 19)
        self.assertTrue(result['summary']['all_historical_event_ids_retained'])
        self.assertTrue(result['summary']['passes_v8_user_objective'])
        self.assertEqual(result['source_pools']['WaterHub']['v8']['before_false_positive_runs'], 6)
        self.assertEqual(result['source_pools']['WaterHub']['v8']['after_false_positive_runs'], 0)

    def test_tampered_historical_prediction_or_upfront_core_hash_fails_closed(self):
        path = self.root/'output/ml/gecco-v8-development/run_01/2017_fold_1/predictions.csv.gz'
        with path.open('ab') as handle: handle.write(b'tamper')
        with self.assertRaisesRegex(ValueError, 'historical_prediction_bound_to_audit'):
            self.run_audit()
        relative = 'output/ml/gecco-v9-development/run_01/audit.json'
        self.plan['historical_comparison_sha256'][relative] = '0'*64
        with self.assertRaisesRegex(ValueError, 'historical_upfront_hash'):
            self.run_audit()

    def test_missing_upfront_historical_manifest_refuses_before_csv_values(self):
        self.plan['historical_comparison_sha256'].pop(next(iter(self.plan['historical_comparison_sha256'])))
        with patch.object(pd, 'read_csv', side_effect=AssertionError('No historical rows before complete manifest')):
            with self.assertRaisesRegex(ValueError, 'exact_historical_upfront_inventory'):
                self.run_audit()


class PulseOracleTests(unittest.TestCase):
    def arrays(self):
        y = np.zeros(400, np.int8); y[210:220] = 1; y[240:246] = 1; y[280:283] = 1
        raw = np.zeros(400, np.float64); raw[:200] = np.linspace(0, 1, 200)
        return y, np.ones(400, bool), raw

    def test_all_pulses_segment_then_pulse_then_row_mass(self):
        y, available, raw = self.arrays()
        raw[210:212] = 2; raw[215:219] = 2; raw[240:244] = 2
        w = audit.weight_oracle(y, available, raw)
        self.assertEqual(w['bonus_segments'], 2); self.assertEqual(w['bonus_pulses'], 3)
        bonus = w['components']['pulse']
        np.testing.assert_allclose(bonus[210:212], .125/2/2, atol=0, rtol=0)
        np.testing.assert_allclose(bonus[215:218], .125/2/3, atol=0, rtol=0)
        np.testing.assert_allclose(bonus[240:243], .125/3, atol=0, rtol=0)
        self.assertFalse(bonus[280:283].any()); self.assertAlmostEqual(bonus.sum(), .25)
        self.assertAlmostEqual(w['components']['normal'].sum(), .5)
        self.assertAlmostEqual(w['components']['positive_point'].sum(), .125)
        self.assertAlmostEqual(w['components']['event'].sum(), .125)
        self.assertAlmostEqual(w['normalized'].sum(), 1.)
        self.assertEqual(len(np.unique(w['normalized'][y == 0])), 1)

    def test_single_pulse_can_cross_two_positive_segments_without_label_reset(self):
        y, available, raw = self.arrays(); y[210:220] = 0
        y[210] = 1; y[211] = -1; y[212] = 1; raw[210:215] = 2
        w = audit.weight_oracle(y, available, raw)
        pulse = next(p for p in w['pulses'] if p['start'] == 210)
        self.assertEqual(pulse['end_exclusive'], 215)
        self.assertEqual(pulse['window_row_indices'], [210, 211, 212])
        self.assertEqual(pulse['eligible_positive_row_indices'], [210, 212])
        self.assertEqual(len(pulse['segment_intersections']), 2)
        self.assertEqual(w['bonus_pulses'], 1); self.assertEqual(w['bonus_intersections'], 2)
        self.assertEqual(w['components']['pulse'][210], .125)
        self.assertEqual(w['components']['pulse'][212], .125)
        self.assertEqual(w['normalized'][211], 0)

    def test_series_start_after_missing_and_tie_threshold_geometry(self):
        y, available, raw = self.arrays(); raw[:3] = 2; raw[209] = np.nan; raw[210:215] = 2
        w = audit.weight_oracle(y, available, raw)
        for start in (0, 210):
            p = next(p for p in w['pulses'] if p['start'] == start)
            self.assertFalse(p['known_onset']); self.assertEqual(p['window_row_indices'], [])
        self.assertFalse(w['bonus'].any()); self.assertTrue(w['redistributed'])
        # An inclusive tie at q95 remains a tail continuation, not a new onset.
        raw[:] = 0; raw[:200] = 1; raw[209] = 0; raw[210:213] = 1
        w = audit.weight_oracle(y, available, raw)
        self.assertEqual(w['q95'], 1)
        p = next(p for p in w['pulses'] if p['start'] == 210)
        self.assertTrue(p['known_onset']); self.assertEqual(p['window_row_indices'], [210, 211, 212])

    def test_truncated_window_and_unavailable_offsets_never_shift_or_expand(self):
        y, available, raw = self.arrays(); raw[210:212] = 2
        available[210] = False
        w = audit.weight_oracle(y, available, raw)
        p = next(p for p in w['pulses'] if p['start'] == 210)
        self.assertEqual(p['window_row_indices'], [210, 211])
        self.assertEqual(p['eligible_positive_row_indices'], [211]); self.assertFalse(w['bonus'][212])
        raw[210:220] = 2; available[210:213] = False
        w = audit.weight_oracle(y, available, raw)
        self.assertFalse(w['bonus'][210:220].any()); self.assertTrue(w['redistributed'])
        self.assertAlmostEqual(w['components']['event'].sum(), .375)

    def test_label_start_inside_old_tail_does_not_create_a_new_window(self):
        y, available, raw = self.arrays(); raw[205:220] = 2
        w = audit.weight_oracle(y, available, raw)
        self.assertFalse(w['bonus'].any()); self.assertTrue(w['redistributed'])
        self.assertFalse(any(p['start'] == 210 for p in w['pulses']))
        self.assertEqual(next(p for p in w['pulses'] if p['start'] == 205)['window_row_indices'], [205, 206, 207])

    def test_q95_all_training_normals_float64_not_hgb_subset_or_positive_unknown(self):
        y, available, raw = self.arrays(); available[:100] = False
        raw[:100] = 100; raw[y != 0] = 1e6; y[300:310] = -1; raw[300:310] = 1e9
        w = audit.weight_oracle(y, available, raw)
        self.assertEqual(w['q95'], 100)
        self.assertGreater(w['q95'], np.quantile(raw[(y == 0) & available], .95))
        self.assertFalse(w['quantile_population'][y == -1].any())
        raw = .5+np.arange(len(y))*1e-10
        w = audit.weight_oracle(y, available, raw)
        self.assertEqual(w['q95'], np.quantile(raw[y == 0], .95, method='linear'))
        self.assertNotEqual(w['q95'], float(np.quantile(raw[y == 0].astype(np.float32), .95)))

    def test_unknown_scores_or_no_eligible_bonus_redistribute_only_when_fit_possible(self):
        y, available, raw = self.arrays(); raw[:] = np.nan
        w = audit.weight_oracle(y, available, raw)
        self.assertIsNone(w['q95']); self.assertTrue(w['redistributed'])
        self.assertAlmostEqual(w['components']['event'].sum(), .375)
        self.assertFalse(w['components']['pulse'].any())
        available[:300] = False
        w = audit.weight_oracle(y, available, raw)
        self.assertFalse(w['fit_possible']); self.assertFalse(w['redistributed'])
        self.assertFalse(w['normalized'].any())
        for bad in (np.zeros(399), np.zeros((400, 1))):
            with self.assertRaises(ValueError): audit.weight_oracle(y, available, bad)

    def test_actual_model_unsupported_states_match_independent_oracle(self):
        for n, events in ((20, False), (180, True), (400, False)):
            with self.subTest(n=n, events=events):
                frame, labels = fixture(n)
                if not events: labels[:] = 0
                elif n == 180: labels[150:160] = 1
                model = make_model(frame, labels, None)
                checks = audit.Checks(); w = audit.audit_training(checks, 'unsupported', model, frame, labels)
                self.assertTrue(all(row['passed'] for row in checks.records), [r for r in checks.records if not r['passed']])
                self.assertFalse(w['fit_possible']); self.assertFalse(model.training_normalized_weight_.any())


class DesignProtocolTests(unittest.TestCase):
    def test_pinned_metadata_only_protocol_and_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); relative = 'output/ml/gecco-v14-design/protocol.json'
            path = root/relative; path.parent.mkdir(parents=True)
            path.write_bytes((audit.ROOT/relative).read_bytes())
            plan = {'design_protocol_sha256': audit.DESIGN_PROTOCOL_SHA,
                    'input_sha256': {relative: audit.DESIGN_PROTOCOL_SHA}}
            checks = audit.Checks(); hashes = {}
            with patch.object(pd, 'read_csv', side_effect=AssertionError('No rows')):
                audit.verify_design_protocol(root, plan, checks, hashes)
            self.assertTrue(all(r['passed'] for r in checks.records))
            path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'exact_bytes'):
                audit.verify_design_protocol(root, plan, audit.Checks(), {})
            plan['design_protocol_sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'upfront_pin'):
                audit.verify_design_protocol(root, plan, audit.Checks(), {})


if __name__ == '__main__': unittest.main()
