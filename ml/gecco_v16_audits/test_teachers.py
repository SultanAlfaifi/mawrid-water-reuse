"""Synthetic teacher audits with prebuilt estimator stubs; no sklearn fitting."""
from __future__ import annotations

from copy import deepcopy
from unittest import TestCase, main
from unittest.mock import patch
import ast
from pathlib import Path

import numpy as np
import pandas as pd

from ml.gecco_v16_audits import teachers as a
from ml.gecco_v16 import teachers as production
from ml.gecco_v7_audits.replay import Checks
from ml.gecco_v6.partially_labeled_model import PartiallyLabeledRecoveryDetector
from ml.gecco_v6.local_change import LocalChangeScorer
from ml.gecco_v8.onset import OnsetWeightedHGBScorer
from ml.gecco_v6.source_suppression import predict as guard_prediction
from ml.gecco_v6.source_joint_calibration import predict as joint_prediction


class StubIF:
    """Deterministic stateless scorer, deliberately never trained."""
    def __init__(self, rows, channels):
        self.n_features_in_ = 4 * channels
        self.estimators_ = [{} for _ in range(200)]
        self.estimators_samples_ = [np.arange(256) for _ in range(200)]
        self.max_samples_ = 256
        self.rows = rows
    def get_params(self, deep=False): return dict(a.IF_PARAMETERS)
    def score_samples(self, matrix): return -np.clip(.35 + .02 * matrix[:, 0], .05, .95)
    def fit(self, *args, **kwargs): raise AssertionError("No IF fitting in audit tests")


class StubClassifier:
    def __init__(self, params):
        self.params = dict(params)
        self.classes_ = np.array([0, 1])
    def get_params(self, deep=False): return self.params.copy()
    def predict_proba(self, matrix):
        score = np.clip(.2 + .03 * matrix[:, 0], 0, 1)
        return np.column_stack([1 - score, score])
    def fit(self, *args, **kwargs): raise AssertionError("No classifier fitting in audit tests")


class Prebuilt:
    """Teacher wiring receives a completed synthetic object, no estimator fit."""
    def __init__(self, model): self.model = model
    def fit(self, *args, **kwargs): return self.model


def sensors(n, offset=0):
    index = np.arange(n) + offset
    return pd.DataFrame({'a': 2 + np.sin(index / 7) + index / 200,
                         'b': 3 + .7 * np.cos(index / 11)})


def prebuilt_models(frame, labels):
    channels = list(frame.columns)
    recovery = PartiallyLabeledRecoveryDetector('shape_invariant', channels)
    fitmask = a.baseline_fit_mask_oracle(frame, labels, channels)
    recovery.baseline_fit_rows_ = int(fitmask.sum())
    recovery.baseline_ = StubIF(int(fitmask.sum()), len(channels)) if fitmask.sum() >= 256 else None
    normal61 = a.normal_windows(labels, 61)
    recovery.normal_scale_window_mask_ = normal61
    recovery.fit_rows_ = recovery.fit_events_ = 0
    recovery.shape_ = None
    recovery.fit_status_ = 'insufficient_normal_training'
    if normal61.sum() >= 100:
        recovery.noise_floor_, _ = a._floor(frame, normal61, minimum=0)
        _, available = recovery.features(frame)
        eligible = available & (labels >= 0)
        starts = np.flatnonzero((labels == 1) & np.r_[True, labels[:-1] != 1])
        ends = np.flatnonzero((labels == 1) & np.r_[labels[1:] != 1, True]) + 1
        recovery.fit_rows_ = int(eligible.sum())
        recovery.fit_events_ = sum(bool(eligible[x:z].any()) for x, z in zip(starts, ends))
        fitted = eligible.sum() >= 100 and recovery.fit_events_ > 0 and (eligible & (labels == 0)).any()
        recovery.fit_status_ = 'fitted' if fitted else 'one_class_training'
        recovery.shape_ = StubClassifier(a.SHAPE_PARAMETERS) if fitted else None
    local = LocalChangeScorer(channels)
    local.normal_floor_window_mask_ = normal61
    local.normal_tail_window_masks_ = {k: a.normal_windows(labels, 75 if k == 'sustained' else 61) for k in a.LOCAL_KEYS}
    local.noise_floor_, local.floor_fit_counts_ = a._floor(frame, normal61, minimum=64)
    # Use the inherited production feature formula to populate synthetic state;
    # the audit recomputes it independently from pandas primitives.
    raw = local._raw_channel_components(frame)
    local.channel_tail_scales_ = {}; local.tail_fit_counts_ = {}
    for key in a.LOCAL_KEYS:
        scale = np.full(len(channels), np.nan); counts = np.zeros(len(channels), int)
        for j in range(len(channels)):
            values = raw[key][local.normal_tail_window_masks_[key], j]
            values = values[np.isfinite(values)]; counts[j] = len(values)
            if len(values) >= 64: scale[j] = max(float(np.quantile(values, .995)), 1.)
        local.channel_tail_scales_[key] = scale; local.tail_fit_counts_[key] = counts
    local.fit_rows_ = int(normal61.sum()); local.is_fitted_ = True
    local.fit_status_ = 'fitted' if min(np.isfinite(v).sum() for v in local.channel_tail_scales_.values()) >= local.minimum_channels else 'insufficient_normal_training'
    long = OnsetWeightedHGBScorer(channels)
    refs = a.v8_audit.reference_oracle(frame.to_numpy(), labels)
    for key, value in refs.items():
        if key != 'available': setattr(long, key, value)
    enough = long.reference_supported_.sum() >= long.minimum_channels
    weights = a.v8_audit.weight_oracle(labels, refs['available'] if enough else np.zeros(len(frame), bool))
    long.training_eligible_mask_ = weights['eligible']
    long.training_normalized_weight_ = weights['normalized']
    long.training_sample_weight_ = weights['sample']
    long.training_rows_ = len(frame)
    long.fit_status_ = ('insufficient_normal_reference' if not enough else 'insufficient_normal_examples'
                       if weights['negative'].sum() < 128 else 'no_event_training' if not weights['positive'].any() else 'fitted')
    long.model_ = StubClassifier(a.HGB_PARAMETERS) if long.fit_status_ == 'fitted' else None
    return {'recovery': recovery, 'local': local, 'long': long}


def fixture(*, unsupported=False, calibration_label=None):
    frame = sensors(600)
    y = np.zeros(len(frame), np.int8); y[300:320] = 1; y[430:440] = -1
    if unsupported: y[:] = -1
    models = prebuilt_models(frame, y)
    cal = [sensors(195, 600 + i * 195) for i in range(4)]
    targets = []
    for _ in cal:
        target = np.zeros(195, np.int8); target[160] = -1; target[184:188] = 1
        if calibration_label is not None: target[:] = calibration_label
        targets.append(target)
    starts = [600 + i * 195 for i in range(4)]
    with patch.object(production, 'PartiallyLabeledRecoveryDetector', return_value=Prebuilt(models['recovery'])), \
         patch.object(production, 'LocalChangeScorer', return_value=Prebuilt(models['local'])), \
         patch.object(production, 'OnsetWeightedHGBScorer', return_value=Prebuilt(models['long'])):
        teacher = production.fit_teacher(frame, y, cal, targets, starts, channels=list(frame.columns))
    forecast = sensors(230, 1400)
    saved = production.predict_teacher(teacher, forecast) if teacher['supported'] else None
    return teacher, frame, y, cal, targets, starts, forecast, saved


class TeacherAuditTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixture()

    def audit(self, data=None):
        checks = Checks()
        summary = a.audit_teacher(checks, 'synthetic', *(self.fixture if data is None else data))
        self.assertTrue(all(r['passed'] for r in checks.records))
        return summary, checks

    def test_full_supported_replay_without_production_v16_or_any_refit(self):
        with (patch.object(production, 'fit_teacher', side_effect=AssertionError('No fit')),
              patch.object(production, 'predict_teacher', side_effect=AssertionError('No V16 prediction'))):
            summary, checks = self.audit()
        self.assertTrue(summary['passed']); self.assertTrue(summary['fitted_state_unchanged'])
        self.assertEqual(summary['forecast_rows_replayed'], 230)
        self.assertEqual(summary['calibration_rows_replayed'], 780)
        self.assertGreater(len(checks.records), 250)
        self.assertFalse(summary['training']['if_fit_values_proven_by_refit'])

    def test_unsupported_missing_if_has_no_invented_forecast(self):
        data = fixture(unsupported=True)
        summary, _ = self.audit(data)
        self.assertFalse(summary['supported']); self.assertEqual(summary['forecast_rows_replayed'], 0)
        changed = list(data); changed[-1] = pd.DataFrame({'v6': [-1]})
        with self.assertRaisesRegex(ValueError, 'no_unsupported_forecast'): self.audit(changed)

    def test_unsupported_calibration_replays_raw_rows_but_no_forecast(self):
        for label, status in [(-1, 'unsupported_no_finite_known_calibration'),
                              (1, 'unsupported_no_observed_normal_calibration')]:
            data = fixture(calibration_label=label)
            summary, _ = self.audit(data)
            self.assertFalse(summary['supported']); self.assertEqual(summary['status'], status)
            self.assertEqual(summary['calibration_rows_replayed'], 780)
            self.assertEqual(summary['forecast_rows_replayed'], 0)

    def test_changed_fitted_normal_population_is_rejected(self):
        data = deepcopy(self.fixture)
        data[0]['training_models']['recovery'].baseline_fit_rows_ += 1
        with self.assertRaisesRegex(ValueError, 'baseline_normal15_fit_count'): self.audit(data)

    def test_unknown_training_labels_cannot_be_treated_as_normal(self):
        data = list(deepcopy(self.fixture)); data[2][430:440] = 0
        with self.assertRaisesRegex(ValueError, 'past_geometry'): self.audit(data)

    def test_future_fit_or_calibration_metadata_is_rejected_before_predictions(self):
        for field in ('max_fit_index', 'max_calibration_index'):
            data = deepcopy(self.fixture); data[0]['training_metadata'][field] += 1
            with patch.object(a, 'raw_scores', side_effect=AssertionError('No score before geometry')):
                with self.assertRaisesRegex(ValueError, 'past_geometry'): self.audit(data)

    def test_changed_saved_forecast_and_calibration_values_are_rejected(self):
        data = deepcopy(self.fixture); data[-1].loc[190, 'v8'] ^= 1
        with self.assertRaisesRegex(ValueError, 'forecast:v8'): self.audit(data)
        data = deepcopy(self.fixture); data[0]['calibration_data'][0].loc[140, 'baseline_score'] += .01
        with self.assertRaisesRegex(ValueError, 'raw_calibration'): self.audit(data)

    def test_classifier_parameter_and_weight_corruption_are_rejected(self):
        data = deepcopy(self.fixture); data[0]['training_models']['long'].model_.params['max_iter'] = 101
        with self.assertRaisesRegex(ValueError, 'hgb_parameters'): self.audit(data)
        data = deepcopy(self.fixture); data[0]['training_models']['long'].training_sample_weight_[431] = 1
        with self.assertRaisesRegex(ValueError, 'all_v8_training_oracles'): self.audit(data)

    def test_scoring_cannot_mutate_fitted_state_silently(self):
        data = deepcopy(self.fixture)
        original = StubIF.score_samples
        def mutating(instance, matrix):
            instance.audit_unexpected_mutations = getattr(instance, 'audit_unexpected_mutations', 0) + 1
            return original(instance, matrix)
        with patch.object(StubIF, 'score_samples', mutating):
            with self.assertRaisesRegex(ValueError, 'fitted_state_unchanged'): self.audit(data)

    def test_separate_calibration_gaps_and_sensor_only_forecast(self):
        data = list(deepcopy(self.fixture)); data[-2]['label'] = 999; data[-2]['EVENT'] = -123
        summary, _ = self.audit(data)
        self.assertEqual(summary['forecast_rows_replayed'], 230)
        for table in data[0]['calibration_data']:
            self.assertTrue(table.baseline_score.iloc[:120].isna().all())
            self.assertTrue((table.v6.iloc[:120] == -1).all())

    def test_local_feature_oracle_matches_frozen_formula_with_missing_values(self):
        frame = sensors(220); frame.loc[90, 'a'] = np.nan; frame.loc[151, 'b'] = np.nan
        local = self.fixture[0]['training_models']['local']
        expected = local._raw_channel_components(frame)
        actual = a.local_raw(frame, local.noise_floor_)
        for key in a.LOCAL_KEYS:
            np.testing.assert_allclose(actual[key], expected[key], rtol=0, atol=1e-12, equal_nan=True)

    def test_scalar_guard_and_rescue_match_inherited_policies(self):
        rng = np.random.default_rng(27271)
        for _ in range(20):
            base = rng.choice([-1, 0, 1], 45).astype(np.int8)
            shape = rng.normal(size=45); shape[rng.random(45) < .1] = np.nan
            scores = {k: rng.normal(size=45) for k in ('shape_raw', *a.LOCAL_KEYS)}
            for policy in ('instant', '2of3', '3of5'):
                choice = {'decision': 'candidate', 'threshold': .2, 'policy': policy}
                guard = a.scalar_guard(base, shape, choice)
                np.testing.assert_array_equal(guard, guard_prediction(shape, base, choice))
                for seed in ('guarded', 'baseline'):
                    selected = {'seed': seed, 'rescue': 'jump', 'threshold': .2, 'policy': policy}
                    np.testing.assert_array_equal(a.scalar_joint(base, guard, scores, selected),
                                                  joint_prediction(base, guard, scores, selected))

    def test_normal_windows_do_not_bridge_unknown_or_compress_axis(self):
        y = np.zeros(100, np.int8); y[40] = -1
        mask = a.normal_windows(y, 15)
        self.assertFalse(mask[:14].any()); self.assertTrue(mask[14:40].all())
        self.assertFalse(mask[40:55].any()); self.assertTrue(mask[55:].all())

    def test_auditor_does_not_import_v16_or_call_fit(self):
        source = Path(a.__file__).read_text(); tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom): self.assertFalse((node.module or '').startswith('ml.gecco_v16'))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute): self.assertNotEqual(node.func.attr, 'fit')


if __name__ == '__main__': main()
