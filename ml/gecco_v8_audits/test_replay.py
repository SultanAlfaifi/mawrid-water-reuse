"""Independent synthetic-only V8 training accounting fixtures."""
import unittest
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import joblib
import numpy as np
import pandas as pd

from ml.gecco_v8_audits import replay as audit
from ml.gecco_v8_audits.replay import reference_oracle, weight_oracle


class FakeTrainModel:
    def __init__(self, channels): self.channels = channels
    def fit(self, frame, labels):
        self.fit_rows = len(frame); self.fit_labels = labels.copy(); self.fit_status_ = 'synthetic'
        return self
    def inspection(self): return {'fit_rows': self.fit_rows}
    def score_components(self, frame): return {'long_context': frame[self.channels[0]].to_numpy(float)}


class RunnerContractTests(unittest.TestCase):
    def test_runner_fits_only_train_and_freezes_before_loading_test_values(self):
        from ml.gecco_v8 import development as runner
        from ml.gecco_v7.calibration_delayed import _choice
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); out = root / 'output'; out.mkdir(); prior = root / 'prior'; prior.mkdir()
            (out / 'plan.json').write_text('{}')
            starts = [200, 330, 460, 590]; test_start = 720; test_end = 920
            train = pd.DataFrame({'a': np.arange(200) / 200, 'EVENT': 0})
            cals = [pd.DataFrame({'a': np.arange(130) / 130, 'EVENT': 0}) for _ in range(4)]
            reference = {'max_fit_index': 199, 'max_calibration_index': 719, 'selected': {}}
            joblib.dump(reference, prior / 'bundle.joblib')
            frozen = {'train': [0, 200], 'calibration_starts': starts, 'test': [test_start, test_end],
                      'bundle_sha256': runner.sha(prior / 'bundle.joblib')}
            (prior / 'freeze.json').write_text(json.dumps(frozen))
            pd.DataFrame({'sample_index': np.arange(200, 720), 'EVENT': 0, 'baseline': 0,
                          'guarded': 0, 'level': .1, 'jump': .2, 'sustained': .3}).to_csv(prior / 'calibration_scores.csv.gz', index=False)
            pd.DataFrame({'sample_index': np.arange(720, 920), 'EVENT': 0, 'baseline': 0,
                          'candidate': 0, 'level': .1, 'jump': .2, 'sustained': .3}).to_csv(prior / 'predictions.csv.gz', index=False)
            chosen = _choice(); calls = []
            def load_test():
                artifact = json.loads((out / 'synthetic' / 'freeze.json').read_text())
                self.assertEqual(artifact['selected'], chosen)
                self.assertEqual(artifact['bundle_sha256'], runner.sha(out / 'synthetic' / 'bundle.joblib'))
                self.assertEqual(artifact['plan_sha256'], runner.sha(out / 'plan.json'))
                calls.append('test_loaded_after_freeze')
                return pd.DataFrame({'a': np.arange(200) / 200, 'EVENT': 0})
            case = {'name': 'synthetic', 'source': '2018', 'prior': prior, 'train': train,
                    'cal': cals, 'cal_starts': starts, 'test_start': test_start, 'test_end': test_end,
                    'target': 'EVENT', 'channels': ['a'], 'continuous_cal': False, 'load_test': load_test}
            def select(blocks, **kwargs):
                self.assertEqual([b['source_start'] for b in blocks], starts)
                self.assertTrue(all(np.isnan(b['long_scores'][:120]).all() for b in blocks))
                self.assertEqual(calls, [])
                return chosen, [{'feasible': True}]
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'verify'), \
                 patch.object(runner, 'OnsetWeightedHGBScorer', FakeTrainModel), \
                 patch.object(runner.prior, 'v6_predict', side_effect=lambda base, *args: base), \
                 patch.object(runner, 'calibrate', side_effect=select), redirect_stdout(StringIO()):
                result, rows = runner.run_case(case, out, {})
            saved = joblib.load(out / 'synthetic' / 'bundle.joblib')
            self.assertEqual(saved['version'], 'v8_onset_hgb_temporally_certified_120s')
            self.assertEqual(saved['long_model'].fit_rows, 200)
            np.testing.assert_array_equal(saved['long_model'].fit_labels, train.EVENT)
            self.assertEqual(calls, ['test_loaded_after_freeze'])
            self.assertEqual(len(rows), 200)

    def test_runtime_preserves_certified_policy_and_strips_labels(self):
        from ml.gecco_v8 import runtime
        from ml.gecco_v7 import runtime_v2
        from ml.gecco_v7_audits.test_delayed_runner import make_bundle, fake_reference
        state = make_bundle(); state['version'] = 'v8_onset_hgb_temporally_certified_120s'
        frame = pd.DataFrame({'p1': [.1, .1, .1, .9, .9], 'p2': [0, .8, .8, .8, 0], 'label': 0})
        original_choice = state['selected'].copy()
        with patch.object(runtime_v2, 'reference_predict', side_effect=fake_reference):
            result = runtime.predict_frame(state, frame)
            altered = runtime.predict_frame(state, frame.assign(label=1))
            for stop in range(6):
                pd.testing.assert_frame_equal(runtime.predict_frame(state, frame.iloc[:stop]), result.iloc[:stop])
        pd.testing.assert_frame_equal(result, altered)
        self.assertEqual(state['selected'], original_choice)
        np.testing.assert_array_equal(result.prediction >= 0, result.reference_prediction >= 0)


class WeightOracleTests(unittest.TestCase):
    def test_single_known_onset_has_exact_declared_masses(self):
        y = np.r_[np.zeros(200), np.ones(20)].astype(np.int8)
        result = weight_oracle(y, np.ones(len(y), bool))
        for key, mass in [('normal', .5), ('positive_point', .125), ('event', .125), ('onset', .25)]:
            self.assertAlmostEqual(result['components'][key].sum(), mass)
        np.testing.assert_allclose(result['normalized'][200:203], .125 / 20 + .125 / 20 + .25 / 3)
        np.testing.assert_allclose(result['normalized'][203:], .25 / 20)
        self.assertAlmostEqual(result['sample'].sum(), len(y))

    def test_bonus_balanced_across_eligible_onsets_then_original_rows(self):
        y = np.r_[np.zeros(200), np.ones(10), 0, np.ones(5)].astype(np.int8)
        available = np.ones(len(y), bool); available[211:213] = False
        result = weight_oracle(y, available)
        self.assertEqual(result['eligible_onset_events'], 2)
        np.testing.assert_allclose(result['components']['onset'][200:203], .125 / 3)
        self.assertEqual(result['components']['onset'][213], .125)
        self.assertEqual(result['components']['onset'][214], 0)
        self.assertEqual(result['eligible_onset_rows'], 4)

    def test_onset_window_never_moves_to_later_eligible_rows(self):
        y = np.r_[np.zeros(200), np.ones(20)].astype(np.int8)
        available = np.ones(len(y), bool); available[200:203] = False
        result = weight_oracle(y, available)
        self.assertEqual(result['known_onset_events'], 1)
        self.assertEqual(result['eligible_onset_events'], 0)
        self.assertTrue(result['onset_bonus_redistributed'])
        self.assertEqual(result['components']['onset'].sum(), 0)
        self.assertAlmostEqual(result['components']['event'].sum(), .375)
        self.assertAlmostEqual(result['normalized'].sum(), 1)

    def test_left_censored_and_unknown_preceded_segments_receive_no_onset_bonus(self):
        y = np.r_[np.ones(4), np.zeros(200), -1, np.ones(7)].astype(np.int8)
        result = weight_oracle(y, np.ones(len(y), bool))
        self.assertEqual(result['known_onset_events'], 0)
        self.assertEqual(result['eligible_segments'], 2)
        self.assertEqual(result['normalized'][204], 0)
        self.assertAlmostEqual(result['components']['event'][:4].sum(), .375 / 2)
        self.assertAlmostEqual(result['components']['event'][205:].sum(), .375 / 2)

    def test_insufficient_normal_training_retains_axis_with_zero_weights(self):
        y = np.r_[np.zeros(127), np.ones(8)].astype(np.int8)
        result = weight_oracle(y, np.ones(len(y), bool))
        self.assertFalse(result['fit_possible'])
        np.testing.assert_array_equal(result['normalized'], np.zeros(len(y)))
        self.assertEqual(result['segments'][0]['start'], 127)


class ReferenceOracleTests(unittest.TestCase):
    def test_actual_scorer_bookkeeping_matches_independent_training_oracle(self):
        from ml.gecco_v8 import onset
        class EstimatorSpy:
            def __init__(self, **kwargs): self.params = kwargs
            def fit(self, x, y, sample_weight):
                self.target = y.copy(); self.weights = sample_weight.copy(); return self
        rng = np.random.default_rng(281)
        frame = pd.DataFrame(rng.normal(size=(700, 2)), columns=['a', 'b'])
        labels = np.zeros(700, np.int8)
        labels[:4] = 1; labels[200:220] = 1; labels[300] = -1; labels[301:315] = 1; labels[400:420] = 1
        frame.loc[400:401, 'a'] = np.nan
        with patch.object(onset, 'HistGradientBoostingClassifier', EstimatorSpy):
            model = onset.OnsetWeightedHGBScorer(['a', 'b']).fit(frame, labels)
        checks = audit.old.Checks(); result = audit.audit_training(checks, 'synthetic', model, frame, labels)
        self.assertTrue(all(c['passed'] for c in checks.records), checks.records)
        np.testing.assert_array_equal(model.model_.target, labels[result['eligible']])
        np.testing.assert_allclose(model.model_.weights, result['sample'][result['eligible']], atol=1e-12, rtol=0)
        model.training_normalized_weight_[205] += .001
        changed = audit.old.Checks(); audit.audit_training(changed, 'tampered', model, frame, labels)
        self.assertTrue(any(not c['passed'] for c in changed.records))

    def test_only_finite_known_normal_adjacent_pairs_enter_references(self):
        x = np.arange(220, dtype=float)[:, None]; y = np.zeros(220, np.int8)
        y[100] = -1; y[200:] = 1
        expected = reference_oracle(x, y)
        changed = x.copy(); changed[y != 0] = 1e12
        actual = reference_oracle(changed, y)
        for key in expected:
            np.testing.assert_allclose(actual[key], expected[key], equal_nan=True)
        self.assertEqual(actual['normal_reference_counts_'][0], 199)
        self.assertEqual(actual['normal_delta_counts_'][0], 197)
        self.assertEqual(actual['positive_delta_counts_'][0], 197)

    def test_availability_uses_previous_60_samples_and_current_only(self):
        x = np.ones((240, 2)); y = np.zeros(240, np.int8)
        x[60:73, 0] = np.nan
        result = reference_oracle(x, y)
        self.assertFalse(result['available'][:60].any())
        self.assertFalse(result['available'][73])
        self.assertTrue(result['available'][121])
        changed = x.copy(); changed[170:] = np.nan
        future = reference_oracle(changed, y)
        # Both references remain supported on the fixed constant training data.
        np.testing.assert_array_equal(result['available'][:170], future['available'][:170])


class CompletedAuditContractTests(unittest.TestCase):
    def test_incomplete_v8_run_cannot_open_sources_or_write_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'plan.json').write_text(json.dumps({'attempt': audit.ATTEMPT, 'scope': 'all', 'limit_cases': 19}))
            (root / 'results.json').write_text(json.dumps({'complete_cases': 1, 'expected_cases': 19}))
            with patch.object(audit, '_source_frames', side_effect=AssertionError('No source read allowed')):
                with self.assertRaises(ValueError): audit.audit_directory(root, workspace_root=root)
            self.assertFalse((root / 'audit.json').exists())

    def test_new_calibration_hooks_accept_certified_synthetic_evidence(self):
        from copy import deepcopy
        from ml.gecco_v7 import calibration_certified as cal
        from ml.gecco_v7.test_calibration_delayed import confirmation_fixture
        from ml.gecco_v6.unknown_label_metrics import stats, comparison
        first = confirmation_fixture(); blocks = first + deepcopy(first); start = 0; bounds = [0]
        for i, b in enumerate(blocks):
            b['source_start'] = start; b['block_id'] = str(i); start += len(b['labels']); bounds.append(start)
        selected, trials = cal.calibrate(blocks)
        frames = []
        for b in blocks:
            frames.append(pd.DataFrame({'sample_index': np.arange(b['source_start'], b['source_start'] + len(b['labels'])),
                'label': b['labels'], 'baseline': b['reference'], 'reference': b['reference'],
                'long_context': b['long_scores'], 'guarded_long_context': b['long_scores'], 'rescue_long_context': np.nan,
                'candidate': cal.predict(b['reference'], b['long_scores'], selected, b['rescue_scores'])}))
        table = pd.concat(frames, ignore_index=True); checks = audit.old.Checks()
        audit._certified_calibration(checks, 'synthetic', table, table.assign(level=.2, jump=.3, sustained=.4),
                                     table, bounds, selected, comparison, stats)
        audit._trial_selection(checks, 'synthetic', pd.DataFrame(trials), selected)
        self.assertTrue(all(c['passed'] for c in checks.records), checks.records)


if __name__ == '__main__': unittest.main()
