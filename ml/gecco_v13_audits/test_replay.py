"""Synthetic-only V13 IF evidence and caller isolation audit checks."""
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
from ml.gecco_v13_audits import replay as audit
from ml.gecco_v13.hard_normal import HardNormalTailHGBScorer
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
    from ml.gecco_v13 import hard_normal
    with patch.object(hard_normal, 'HistGradientBoostingClassifier', SpyClassifier):
        return HardNormalTailHGBScorer(list(frame.columns), estimator).fit(frame, labels)


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

    def test_only_exact_v13_attempt_and_class_are_accepted(self):
        result = audit.method_spec({'attempt': audit.ATTEMPT})
        self.assertEqual(result['runtime'], 'ml.gecco_v13.runtime')
        self.assertEqual(result['model_class'], 'HardNormalTailHGBScorer')
        with self.assertRaises(ValueError): audit.method_spec({'attempt': 'v11'})


class HardNormalOracleTests(unittest.TestCase):
    def fixture(self):
        labels = np.zeros(220, np.int8)
        labels[180:190] = 1
        labels[210:215] = -1
        available = np.ones(220, bool); available[:40] = False
        raw = np.linspace(0, 1, 220, dtype=np.float64)
        return labels, available, raw

    def test_q95_uses_all_finite_training_normal_even_outside_hgb_eligibility(self):
        labels, available, raw = self.fixture(); raw[:40] = 100
        result = audit.weight_oracle(labels, available, raw)
        self.assertEqual(result['q95'], 100.)
        self.assertTrue(result['quantile_population'][:40].all())
        self.assertFalse(result['tail'].any())
        wrong = np.quantile(raw[(labels == 0) & available], .95)
        self.assertLess(wrong, result['q95'])
        self.assertAlmostEqual(result['components']['normal'].sum(), .5)

    def test_inclusive_tail_ties_factor_five_and_positive_weights_exact(self):
        labels, available, raw = self.fixture()
        raw[:] = .1; raw[100:130] = .8
        result = audit.weight_oracle(labels, available, raw)
        self.assertEqual(result['q95'], .8)
        self.assertTrue(result['tail'][100:130].all())
        w = result['normalized']
        self.assertAlmostEqual(w[100]/w[60], 5.)
        original = audit.v9.weight_oracle(labels, available)
        np.testing.assert_array_equal(w[labels == 1], original['normalized'][labels == 1])
        np.testing.assert_array_equal(result['sample'][labels == 1], original['sample'][labels == 1])
        self.assertAlmostEqual(w[labels == 0].sum(), .5)
        self.assertFalse(w[labels == -1].any())

    def test_raw_float64_population_not_rounded_feature_values(self):
        labels, available, raw = self.fixture()
        raw = .5 + np.arange(len(raw), dtype=np.float64)*1e-10
        self.assertEqual(np.unique(raw.astype(np.float32)).size, 1)
        result = audit.weight_oracle(labels, available, raw)
        self.assertEqual(result['q95'], np.quantile(raw[labels == 0], .95, method='linear'))
        self.assertGreater(result['tail'].sum(), 0)
        self.assertLess(result['tail'].sum(), result['negative'].sum())

    def test_unknown_positive_and_nonfinite_do_not_define_normal_quantile(self):
        labels, available, raw = self.fixture()
        raw[labels != 0] = 1e100; raw[50] = np.inf; raw[51] = np.nan
        result = audit.weight_oracle(labels, available, raw)
        expected = np.quantile(raw[(labels == 0) & np.isfinite(raw)], .95)
        self.assertEqual(result['q95'], expected)
        self.assertFalse(result['quantile_population'][labels != 0].any())
        self.assertFalse(result['tail'][50:52].any())
        # Eligible normals missing an IF score retain factor1, not zero weight.
        self.assertGreater(result['normalized'][50], 0)

    def test_no_if_fallback_and_no_event_training_preserve_original_behavior(self):
        labels, available, raw = self.fixture(); raw[:] = np.nan
        result = audit.weight_oracle(labels, available, raw)
        original = audit.v9.weight_oracle(labels, available)
        self.assertIsNone(result['q95']); self.assertFalse(result['tail'].any())
        np.testing.assert_array_equal(result['normalized'], original['normalized'])
        labels[:] = 0
        result = audit.weight_oracle(labels, available, np.ones(len(raw)))
        self.assertFalse(result['fit_possible']); self.assertFalse(result['normalized'].any())
        self.assertFalse(result['sample'].any())

    def test_bad_axis_ternary_and_nontraining_extension_are_explicit(self):
        labels, available, raw = self.fixture()
        with self.assertRaises(ValueError): audit.weight_oracle(labels, available, raw[:-1])
        with self.assertRaises(ValueError): audit.weight_oracle(labels, available[:-1], raw)
        changed = labels.copy(); changed[0] = 2
        with self.assertRaises(ValueError): audit.weight_oracle(changed, available, raw)
        # This function consumes the provided TRAIN axis; the actual runner
        # audit enforces model.training_rows_ == strict original train_end.
        result = audit.weight_oracle(labels, available, raw)
        extended = audit.weight_oracle(np.r_[labels, np.zeros(100, np.int8)],
            np.r_[available, np.ones(100, bool)], np.r_[raw, np.full(100, 1e9)])
        self.assertNotEqual(result['q95'], extended['q95'])

    def test_v8_comparison_records_regression_despite_same_event_count(self):
        from ml.gecco_v6.unknown_label_metrics import stats
        labels = np.array([0, 1, 1, 0, 0, 1, 1, 0, -1, 0], np.int8)
        before = stats(labels, np.array([0, 1, 0, 0, 0, 0, 0, 0, -1, 0], np.int8), 60)
        after = stats(labels, np.array([0, 0, 0, 1, 0, 1, 0, 0, -1, 1], np.int8), 60)
        result = audit.v8_comparison_record(before, after)
        self.assertEqual(len(result['v8_confirmed_event_ids']), len(result['v13_confirmed_event_ids']))
        self.assertFalse(result['all_v8_event_ids_retained'])
        self.assertEqual(len(result['lost_v8_event_ids']), 1)
        self.assertEqual(result['false_alarm_comparison']['v13_false_positive_runs'], 2)
        self.assertEqual(result['false_alarm_comparison']['v13_fp_duration_seconds'], 120)
        self.assertFalse(result['false_alarm_comparison']['false_duration_nonincreasing'])

    def test_historical_gate_independently_rejects_ids_delay_availability_and_false_duration(self):
        from copy import deepcopy
        good = {'all_event_ids_retained': True, 'sensor_availability_equal': True,
            'paired_delay_within120': True, 'false_runs_nonincreasing': True,
            'false_duration_nonincreasing': True, 'before_false_positive_runs': 2,
            'after_false_positive_runs': 1}
        periods = {str(i): {v: dict(good) for v in audit.HISTORICAL_AUDITOR_SHA} for i in range(19)}
        pools = {'source': {v: dict(good) for v in audit.HISTORICAL_AUDITOR_SHA}}
        result = audit.historical_objectives(periods, pools)
        self.assertTrue(result['passes_v8_user_objective']); self.assertTrue(result['all_historical_event_ids_retained'])
        for field in ('all_event_ids_retained', 'sensor_availability_equal', 'paired_delay_within120',
                      'false_runs_nonincreasing', 'false_duration_nonincreasing'):
            broken = deepcopy(periods); broken['3']['v8'][field] = False
            self.assertFalse(audit.historical_objectives(broken, pools)['passes_v8_user_objective'], field)
        broken = deepcopy(pools); broken['source']['v12']['all_event_ids_retained'] = False
        result = audit.historical_objectives(periods, broken)
        self.assertFalse(result['all_historical_event_ids_retained'])
        self.assertTrue(result['passes_v8_user_objective'])  # Independent requirements remain distinct.
        self.assertFalse(audit.historical_objectives(dict(list(periods.items())[:-1]), pools)['passes_v8_user_objective'])

    def test_pooled_boundary_event_ids_are_recomputed_and120_second_cap_exact(self):
        from ml.gecco_v6.unknown_label_metrics import comparison
        labels = np.array([0, 1, 1, 1, 1, 1, 0], np.int8)
        base = np.array([0, 1, 0, 0, 0, 0, 0], np.int8)
        delayed120 = np.array([0, 0, 0, 1, 0, 0, 0], np.int8)
        delayed180 = np.array([0, 0, 0, 0, 1, 0, 0], np.int8)
        self.assertTrue(audit.historical_pair(labels, base, delayed120, comparison)['paired_delay_within120'])
        self.assertFalse(audit.historical_pair(labels, base, delayed180, comparison)['paired_delay_within120'])
        self.assertTrue(audit.historical_pair(labels, base, delayed120, comparison)['all_event_ids_retained'])
        # The second fragment starts positive, so its period-local target is
        # censored; it must not replace the concatenated source event axis.
        self.assertEqual(audit.historical_pair(labels[3:], base[3:], delayed120[3:], comparison)['gained_event_ids'], [])


class TrainingTamperTests(unittest.TestCase):
    def test_independent_training_audit_detects_wrong_q95_mask_raw_weights_and_metadata(self):
        from copy import deepcopy
        frame, labels = fixture(); model = make_model(frame, labels, make_estimator(frame, labels))
        for field in ('q95', 'population', 'tail', 'weight', 'raw', 'metadata'):
            with self.subTest(field=field):
                altered = deepcopy(model)
                if field == 'q95': altered.hard_normal_q95_ += .01
                elif field == 'population': altered.hard_normal_quantile_mask_[0] = True
                elif field == 'tail': altered.hard_normal_tail_mask_[180] = True
                elif field == 'weight': altered.training_normalized_weight_[100] += .1
                elif field == 'raw': altered.hard_normal_raw_scores_[100] += .01
                else: altered.hard_normal_audit_['eligible_tail_rows'] += 1
                checks = audit.Checks()
                audit.audit_training(checks, field, altered, frame, labels)
                self.assertTrue(any(not row['passed'] for row in checks.records), field)

    def test_auditor_never_calls_production_weight_helper(self):
        frame, labels = fixture(); model = make_model(frame, labels, make_estimator(frame, labels))
        with patch.object(HardNormalTailHGBScorer, '_apply_hard_normal_weights', side_effect=AssertionError('No production weight helper')):
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


class ExecutionResumeTests(unittest.TestCase):
    """Opaque tiny artifacts, no controller execution, source CSV or bundle IO."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.out = self.root/'output/run'; self.out.mkdir(parents=True)
        self.control = self.out/'execution_resume'; self.control.mkdir()
        self.plan = {'attempt': audit.ATTEMPT, 'case_order': audit.EXPECTED_NAMES,
            'scope': 'all', 'limit_cases': 19, 'expected_cases': 19,
            'resource_execution': {'minimum_free_disk_bytes': 1024**3},
            'environment': {'python': 'synthetic', 'numpy': 'synthetic', 'pandas': 'synthetic', 'sklearn': 'synthetic'}}
        self.write(self.out/'plan.json', self.plan); self.plan_sha = audit.sha(self.out/'plan.json')
        for filename in audit.RESUME_CONTROLLER_SHA:
            target = self.root/'ml/gecco_v13_control'/filename; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((audit.ROOT/'ml/gecco_v13_control'/filename).read_bytes())
        self.artifacts = {}
        for name in audit.EXPECTED_NAMES:
            folder = self.out/name; folder.mkdir()
            for filename in audit.RESUME_ARTIFACTS:
                (folder/filename).write_bytes(b'SYNTHETIC OPAQUE BYTES; NEVER DECODE OR UNPICKLE')
            self.write(folder/'freeze.json', {'plan_sha256': self.plan_sha,
                'bundle_sha256': audit.sha(folder/'bundle.joblib')})
            self.write(folder/'results.json', {'case': name, 'development_only': True})
            self.artifacts[name] = {filename: audit.sha(folder/filename) for filename in audit.RESUME_ARTIFACTS}
        self.threads = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
        self.checkpoint = {'schema_version': 1, 'operation': 'resource_only_resume',
            'root': str(self.root), 'output': str(self.out), 'plan_sha256': self.plan_sha,
            'controller_sha256': audit.RESUME_CONTROLLER_SHA, 'environment': self.plan['environment'],
            'child_thread_environment': self.threads, 'mkl_thread_environment': 'unset, matching original command',
            'initial_completed_cases': {key: self.artifacts[key] for key in audit.EXPECTED_NAMES[:12]},
            'initial_complete_count': 12, 'missing_cases': audit.EXPECTED_NAMES[12:], 'expected_cases': 19,
            'original_minimum_free_disk_bytes': 1024**3, 'statistical_method_changed': False,
            'existing_artifacts_will_not_be_overwritten': True}
        self.write(self.control/'checkpoint.json', self.checkpoint)
        self.checkpoint_sha = audit.sha(self.control/'checkpoint.json')
        self.write(self.out.parent/'resume-checkpoint-pin.json', {
            'sha256': self.checkpoint_sha, 'checkpoint': str((self.control/'checkpoint.json').relative_to(self.root)),
            'initial_preserved_complete_cases': 12, 'remaining_cases': 7,
            'statistical_parameters_changed': False, 'minimum_free_disk_bytes_changed': False,
            'original_process_terminal_exit': 1})
        self.write(self.control/'resume_synthetic.log', {'checkpoint_sha256': self.checkpoint_sha,
            'minimum_free_disk_bytes': 1024**3, 'thread_environment': self.threads})
        receipts = {}
        for index, name in enumerate(audit.EXPECTED_NAMES[12:], 12):
            receipt = {'case': name, 'checkpoint_sha256': self.checkpoint_sha,
                'plan_sha256': self.plan_sha, 'controller_sha256': audit.RESUME_CONTROLLER_SHA,
                'child_returncode': 0, 'thread_environment': self.threads,
                'resume_log': 'execution_resume/resume_synthetic.log', 'artifact_sha256': self.artifacts[name]}
            path = self.control/f'case_{index+1:02d}_{name}.json'; self.write(path, receipt)
            receipts[name] = audit.sha(path)
        self.completed = {'maximum_allowed_extra_delay_seconds': 120,
            'historical_retention_required': True, 'v8_user_objective_required': True,
            'acceptance_evaluation_pending_independent_audit_and_historical_comparison': True,
            'execution_resume': {'operation': 'resource_only_resume', 'checkpoint': 'execution_resume/checkpoint.json',
                'checkpoint_sha256': self.checkpoint_sha, 'original_plan_sha256': self.plan_sha,
                'controller_sha256': audit.RESUME_CONTROLLER_SHA, 'initial_preserved_cases': audit.EXPECTED_NAMES[:12],
                'resumed_case_receipt_sha256': receipts, 'new_resume_logs': ['resume_synthetic.log'],
                'original_method_and_acceptance_unchanged': True, 'existing_case_artifacts_unchanged': True,
                'thread_environment': self.threads, 'environment': self.plan['environment']}}

    def tearDown(self): self.temp.cleanup()

    def write(self, path, value): path.write_text(json.dumps(value)+'\n')

    def run_audit(self):
        checks, hashes = audit.Checks(), {}
        with patch.object(pd, 'read_csv', side_effect=AssertionError('Metadata audit never decodes CSV')), \
             patch.object(joblib, 'load', side_effect=AssertionError('Metadata audit never loads models')), \
             patch.object(audit, 'RESUME_CHECKPOINT_SHA', self.checkpoint_sha):
            result = audit.audit_execution_resume(self.root, self.out, self.plan, self.completed, checks, hashes)
        return result, checks, hashes

    def test_exact12_plus7_bindings_pass_without_decoding_any_measurement_or_bundle(self):
        result, checks, hashes = self.run_audit()
        self.assertTrue(result['operational_resume_checked'])
        self.assertEqual(result['all_case_artifact_hashes_checked'], 133)
        self.assertEqual(result['initial_completed_cases_preserved'], 12)
        self.assertEqual(result['resumed_cases_verified'], 7)
        self.assertTrue(all(row['passed'] for row in checks.records))
        self.assertEqual(len(hashes), 133+7+3+1+1+1)

    def test_missing_checkpoint_receipt_or_initial_artifact_refuses(self):
        for path in (self.control/'checkpoint.json', self.control/'case_13_2019_disclosed_test.json',
                     self.out/audit.EXPECTED_NAMES[0]/'model_inspection.json'):
            original = path.read_bytes(); path.unlink()
            try:
                with self.assertRaises(ValueError): self.run_audit()
            finally: path.write_bytes(original)

    def test_tampered_checkpoint_receipt_initial_resumed_and_controller_files_refuse(self):
        paths = [self.control/'checkpoint.json', self.control/'case_13_2019_disclosed_test.json',
            self.out/audit.EXPECTED_NAMES[0]/'predictions.csv.gz',
            self.out/audit.EXPECTED_NAMES[-1]/'calibration_scores.csv.gz',
            self.root/'ml/gecco_v13_control/resume.py']
        for path in paths:
            with self.subTest(path=path):
                original = path.read_bytes(); path.write_bytes(original+b' ')
                try:
                    with self.assertRaisesRegex(ValueError, 'bound_sha'): self.run_audit()
                finally: path.write_bytes(original)

    def test_rebinding_receipt_hash_does_not_allow_wrong_checkpoint_or_failed_child(self):
        path = self.control/'case_13_2019_disclosed_test.json'; original = audit.read_json(path)
        for field, value in (('checkpoint_sha256', '0'*64), ('child_returncode', 1),
                             ('controller_sha256', {}), ('thread_environment', {})):
            with self.subTest(field=field):
                changed = dict(original); changed[field] = value; self.write(path, changed)
                self.completed['execution_resume']['resumed_case_receipt_sha256']['2019_disclosed_test'] = audit.sha(path)
                with self.assertRaisesRegex(ValueError, 'receipt_provenance'): self.run_audit()

    def test_guard_acceptance_environment_and_missing_resume_metadata_refuse(self):
        from copy import deepcopy
        original = deepcopy(self.completed)
        for field, value in (('maximum_allowed_extra_delay_seconds', 180), ('historical_retention_required', False),
                             ('v8_user_objective_required', False)):
            self.completed = deepcopy(original); self.completed[field] = value
            with self.assertRaisesRegex(ValueError, 'original_acceptance'): self.run_audit()
        self.completed = deepcopy(original); self.completed['execution_resume']['environment'] = {'wrong': 'version'}
        with self.assertRaisesRegex(ValueError, 'original_library_versions'): self.run_audit()
        self.completed = deepcopy(original); self.plan['resource_execution']['minimum_free_disk_bytes'] = 1
        with self.assertRaisesRegex(ValueError, 'one_gib_guard'): self.run_audit()
        self.plan['resource_execution']['minimum_free_disk_bytes'] = 1024**3
        self.completed = {}; self.assertTrue((self.control/'checkpoint.json').exists())
        with self.assertRaisesRegex(ValueError, 'metadata_not_omitted'): self.run_audit()
        (self.control/'checkpoint.json').unlink()
        with self.assertRaisesRegex(ValueError, 'metadata_not_omitted'): self.run_audit()
        for path in self.control.glob('case_*.json'): path.unlink()
        with self.assertRaisesRegex(ValueError, 'metadata_not_omitted'): self.run_audit()
        (self.control/'resume_synthetic.log').unlink()
        with self.assertRaisesRegex(ValueError, 'metadata_not_omitted'): self.run_audit()
        (self.out.parent/'resume-checkpoint-pin.json').unlink()
        result, _, _ = self.run_audit(); self.assertFalse(result['present'])

    def test_separate_operator_pin_must_match_and_cannot_assert_changed_parameters(self):
        path = self.out.parent/'resume-checkpoint-pin.json'; original = audit.read_json(path)
        for field, value in (('sha256', '0'*64), ('remaining_cases', 6),
                             ('statistical_parameters_changed', True), ('minimum_free_disk_bytes_changed', True)):
            changed = dict(original); changed[field] = value; self.write(path, changed)
            with self.assertRaisesRegex(ValueError, 'external_pin_metadata'): self.run_audit()


if __name__ == '__main__': unittest.main()
