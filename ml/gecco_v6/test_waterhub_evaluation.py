"""Synthetic-only runner contracts. Never open an archive or measured source."""
import contextlib
import copy
import inspect
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

import waterhub_evaluation as runner
import waterhub_adapter
from unknown_label_metrics import comparison


def acceptable_results():
    periods = []
    all_y, all_b, all_c = [], [], []
    for i in range(6):
        y = np.zeros(2000, np.int8)
        baseline = np.zeros(2000, np.int8)
        candidate = np.zeros(2000, np.int8)
        for a in (100, 400, 800):
            y[a:a + 6] = 1
            candidate[a:a + 3] = 1
        for a in (100, 400):
            baseline[a:a + 3] = 1
        baseline[50:53] = 1
        candidate[50:53] = 1
        baseline[1500:1502] = 1
        periods.append(comparison(y, baseline, candidate))
        all_y.append(y); all_b.append(baseline); all_c.append(candidate)
    pooled = comparison(np.concatenate(all_y), np.concatenate(all_b), np.concatenate(all_c))
    return periods, pooled


class WaterHubEvaluationTests(unittest.TestCase):
    def test_geometry_is_expanding_past_only_and_covers_exact_calendar(self):
        cases = runner.geometry()
        self.assertEqual([c['name'] for c in cases],
                         ['2018-11', '2018-12', '2019-01', '2019-02', '2019-03', '2019-04'])
        previous_end = None
        for case in cases:
            train_start, train_end = case['train']
            bounds = case['calibration_boundaries']
            start, end = case['test']
            self.assertEqual(train_start, 0)
            self.assertEqual(train_end, bounds[0])
            self.assertEqual(bounds[-1], start)
            self.assertTrue(all(a < b for a, b in zip(bounds[:-1], bounds[1:])))
            self.assertLess(train_end, start)
            self.assertLess(start, end)
            self.assertLessEqual(max(np.diff(bounds)) - min(np.diff(bounds)), 1)
            date = runner.START + pd.Timedelta(minutes=start)
            self.assertEqual(date.strftime('%Y-%m'), case['name'])
            self.assertEqual(runner.START + pd.Timedelta(minutes=train_end),
                             date - pd.DateOffset(months=2))
            self.assertEqual(runner.START + pd.Timedelta(minutes=end), date + pd.DateOffset(months=1))
            if previous_end is not None:
                self.assertEqual(start, previous_end)
            previous_end = end
        self.assertEqual(runner.START + pd.Timedelta(minutes=previous_end), runner.END)

    def test_actual_constructor_signatures_accept_runner_arguments(self):
        prior = runner.PartiallyLabeledRecoveryDetector('shape_invariant', runner.CHANNELS)
        local = runner.LocalChangeScorer(runner.CHANNELS)
        self.assertEqual(prior.channels, runner.CHANNELS)
        self.assertEqual(local.channels, runner.CHANNELS)
        inspect.signature(runner.predict_frame).bind({}, pd.DataFrame(), gap_samples=runner.GAP)

    def test_fit_selection_never_get_test_rows_and_unknown_masks_are_local(self):
        # Index encoded as sensor values survives each block's reset_index.
        n = 2100
        x = pd.DataFrame({c: np.arange(n, dtype=float) for c in runner.CHANNELS})
        labels = np.zeros(n, np.int8)
        labels[100:110] = -1
        labels[150:155] = 1
        labels[760:765] = -1
        labels[1800:] = -1
        case = {'name': 'synthetic', 'train': [0, 600], 'calibration_boundaries': [600, 900, 1200, 1500, 1800], 'test': [1800, 2100]}
        fits, scored = [], []
        class Prior:
            def __init__(self, config_id, channels):
                self.channels = list(channels)
                if config_id != 'shape_invariant': raise AssertionError('Recipe changed')
                self.fit_status_ = 'synthetic'
            def fit(self, frame, y):
                fits.append(('prior', frame.p1.to_numpy().copy(), y.copy())); return self
            def score_components(self, frame):
                scored.append(('prior', frame.p1.to_numpy().copy()))
                return {'baseline': np.full(len(frame), .1), 'shape': np.full(len(frame), .2)}
        class Local:
            def __init__(self, channels):
                self.channels = list(channels); self.fit_status_ = 'synthetic'
            def fit(self, frame, y):
                fits.append(('local', frame.p1.to_numpy().copy(), y.copy())); return self
            def score_components(self, frame):
                scored.append(('local', frame.p1.to_numpy().copy()))
                return {key: np.full(len(frame), .2) for key in ('level', 'jump', 'sustained')}
        selected_inputs = {}
        def baseline_select(y, values, baseline):
            selected_inputs['baseline_y'] = y.copy()
            selected_inputs['baseline_scores'] = values.copy()
            self.assertTrue(baseline)
            return {'threshold': .5}, []
        def guard_select(blocks):
            selected_inputs['guard'] = copy.deepcopy(blocks)
            return {'decision': 'baseline'}, []
        def shape_reference(blocks):
            selected_inputs['shape'] = copy.deepcopy(blocks)
            return .5
        def joint_select(blocks):
            selected_inputs['joint'] = copy.deepcopy(blocks)
            return {'seed': 'baseline', 'rescue': None, 'threshold': None, 'policy': 'instant'}, []
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(runner, 'PartiallyLabeledRecoveryDetector', Prior), \
             patch.object(runner, 'LocalChangeScorer', Local), \
             patch.object(runner, 'select_baseline', baseline_select), \
             patch.object(runner, 'calibrate_guard', guard_select), \
             patch.object(runner, 'fit_shape_reference', shape_reference), \
             patch.object(runner, 'calibrate_joint', joint_select), \
             contextlib.redirect_stdout(io.StringIO()):
            bundle = runner.fit_case(x, labels, case, Path(folder))
        for name, values, used_labels in fits:
            np.testing.assert_array_equal(values, np.arange(600))
            np.testing.assert_array_equal(used_labels, labels[:600] if name == 'prior' else labels[:600] != 0)
        expected_blocks = [np.arange(a + 120, b) for a, b in zip(case['calibration_boundaries'][:-1], case['calibration_boundaries'][1:])]
        for name in ('prior', 'local'):
            actual = [rows for kind, rows in scored if kind == name]
            self.assertEqual(len(actual), 4)
            for values, expected in zip(actual, expected_blocks):
                np.testing.assert_array_equal(values, expected)
                self.assertTrue((values < case['test'][0]).all())
        cal_y = labels[600:1800]
        np.testing.assert_array_equal(selected_inputs['baseline_y'], cal_y == 1)
        self.assertTrue(np.isnan(selected_inputs['baseline_scores'][cal_y < 0]).all())
        for blocks in (selected_inputs['guard'], selected_inputs['shape'], selected_inputs['joint']):
            for i, block in enumerate(blocks):
                np.testing.assert_array_equal(block['labels'], cal_y[i * 300:(i + 1) * 300])
        # Unknown label rows remain sensor-observable in guard/joint calibration.
        self.assertTrue((selected_inputs['guard'][0]['baseline_predictions'][160:165] == 0).all())
        self.assertTrue((selected_inputs['joint'][0]['baseline'][160:165] == 0).all())
        self.assertEqual(bundle['max_fit_index'], 599)
        self.assertEqual(bundle['max_calibration_index'], 1799)

    def test_baseline_known_only_mask_has_correct_point_and_false_run_accounting(self):
        # Compare every original baseline threshold trial against the ternary
        # metrics on UNMASKED inference. Only unknown-label score ranks differ.
        from unknown_label_metrics import stats
        n = 7000
        labels = np.zeros(n, np.int8)
        labels[200:230] = 1
        labels[500:540] = -1
        scores = np.full(n, .1)
        scores[200:220] = .8
        scores[500:540] = 10.
        scores[900] = .9
        chosen, trials = runner.select_baseline(labels == 1, np.where(labels >= 0, scores, np.nan), baseline=True)
        for trial in trials:
            prediction = runner.baseline_predict(scores, trial['threshold'], 'instant')
            expected = stats(labels, prediction)
            for key in ('tp', 'fp', 'fn', 'tn', 'false_positive_runs'):
                self.assertEqual(trial[key], expected[key])
            self.assertEqual(trial['false_alarm_runs_per_normal_day'], expected['false_runs_per_day'])
            self.assertEqual(trial['normal_time_under_alarm'], expected['normal_alarm_fraction'])
        self.assertLess(chosen['threshold'], 10.)
        self.assertTrue((runner.baseline_predict(scores, chosen['threshold'])[500:540] >= 0).all())

    def test_positive_acceptance_and_exact_exposure_boundary(self):
        periods, pooled = acceptable_results()
        self.assertTrue(runner.acceptance(periods, pooled)['passes_fresh_validation_requirements'])
        for result in periods:
            for name in ('baseline', 'candidate'):
                result[name]['normal_observed_seconds'] = 1440 * 60
        self.assertTrue(runner.acceptance(periods, pooled)['passes_fresh_validation_requirements'])

    def test_acceptance_rejects_each_regression_and_insufficient_evidence(self):
        mutations = {
            'lost_id': lambda ps, pool: ps[0].update(lost_baseline_event_ids=[1]),
            'availability': lambda ps, pool: ps[0].update(sensor_availability_equal=False),
            'delay': lambda ps, pool: ps[0]['paired_extra_delays'].append({'extra_delay_seconds': 60}),
            'fp_runs': lambda ps, pool: ps[0]['candidate'].update(false_positive_runs=ps[0]['baseline']['false_positive_runs'] + 1),
            'fp_time': lambda ps, pool: ps[0]['candidate'].update(fp=ps[0]['baseline']['fp'] + 1),
            'pool_loss': lambda ps, pool: pool.update(lost_baseline_event_ids=[2]),
            'pool_delay': lambda ps, pool: pool['paired_extra_delays'].append({'extra_delay_seconds': 60}),
            'no_pooled_gain': lambda ps, pool: pool['candidate'].update(confirmed_events=pool['baseline']['confirmed_events']),
            'no_pooled_fp_reduction': lambda ps, pool: pool['candidate'].update(false_positive_runs=pool['baseline']['false_positive_runs']),
            'too_few_events': lambda ps, pool: pool['baseline'].update(true_events=4),
            'one_gain_period': lambda ps, pool: [r.update(new_candidate_event_ids=[]) for r in ps[1:]],
            'one_fp_gain_period': lambda ps, pool: [r['candidate'].update(false_positive_runs=r['baseline']['false_positive_runs']) for r in ps[1:]],
            'one_eventful_period': lambda ps, pool: [r['baseline'].update(true_events=0) for r in ps[1:]],
            'short_known_normal': lambda ps, pool: ps[0]['baseline'].update(normal_observed_seconds=1439 * 60),
            'short_candidate_normal': lambda ps, pool: ps[0]['candidate'].update(normal_observed_seconds=1439 * 60),
            'unmeasurable_period': lambda ps, pool: [ps[0][name].update(normal_observed_seconds=0) for name in ('baseline', 'candidate')],
            'incomplete': lambda ps, pool: ps.pop(),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                periods, pooled = acceptable_results()
                mutate(periods, pooled)
                self.assertFalse(runner.acceptance(periods, pooled)['passes_fresh_validation_requirements'])

    def test_freeze_declares_normal_exposure_without_source_access(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); here = root / 'ml/gecco_v6'; here.mkdir(parents=True)
            loader = here / 'waterhub_loader.py'; loader.write_text('# synthetic loader only\n')
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'HERE', here), \
                 patch.object(runner, 'ARCHIVE', root / 'synthetic-unopened.zip'), \
                 patch.object(runner, 'code_paths', return_value=[loader]), \
                 patch.object(runner, 'sha', return_value=runner.ARCHIVE_SHA), \
                 contextlib.redirect_stdout(io.StringIO()):
                runner.freeze(root / 'frozen')
            plan = json.loads((root / 'frozen/protocol.json').read_text())
            self.assertEqual(plan['acceptance']['minimum_observed_known_normal_minutes_each_test_period'], 1440)
            self.assertIn('ml/gecco_v6/waterhub_loader.py', plan['code_sha256'])
            self.assertFalse((root / 'frozen/source_access_started.json').exists())

    def test_code_freeze_covers_runtime_and_direct_model_dependencies(self):
        actual = {str(p.relative_to(runner.ROOT)) for p in runner.code_paths()}
        required = {'ml/gecco_v6/runtime_v4.py', 'ml/gecco_v6/local_change.py',
                    'ml/gecco_v6/partially_labeled_model.py', 'ml/gecco_v6/unknown_label_metrics.py',
                    'ml/gecco_v6/source_suppression.py', 'ml/gecco_v6/source_joint_calibration.py',
                    'ml/gecco_v6/corroborated_rescue.py', 'ml/gecco_v6/latched_suppression.py',
                    'ml/gecco_v6/departure_scores.py', 'ml/gecco_v6/guarded_suppression.py',
                    'ml/gecco_v6/joint_calibration_v2.py', 'ml/gecco_v6/waterhub_adapter.py',
                    'ml/gecco_v5/recovery_candidate.py', 'ml/gecco_v5/calibration.py',
                    'ml/gecco_v2/alarm_policy.py', 'ml/gecco_v2/candidates_supervised.py',
                    'ml/gecco_baseline/metrics.py'}
        self.assertTrue(required <= actual, required - actual)

    def test_run_uses_archive_loader_contract_and_marks_access_before_call(self):
        # The only loader in this test is this synthetic module; no real archive
        # path is dereferenced. The runner still exercises its full interface.
        start = pd.Timestamp('2020-01-01'); end = start + pd.Timedelta(minutes=100)
        index = pd.date_range(start + pd.Timedelta(minutes=1), end, freq='min')
        x = pd.DataFrame(0., index=index, columns=runner.CHANNELS)
        adapted = types.SimpleNamespace(features=x, labels=pd.Series(np.zeros(100, np.int8), index=index),
                                        audit=pd.DataFrame({'synthetic': True}, index=index), metadata={'synthetic': True})
        raw_a, raw_b, annotations = object(), object(), object()
        mask = pd.DatetimeIndex([])
        loaded = types.SimpleNamespace(combined=lambda: (raw_a, raw_b, annotations),
                                       timestamp_ambiguity_mask=mask, member_manifest={}, metadata={'synthetic': True})
        module = types.ModuleType('waterhub_loader')
        cases = [{'name': f'case{i}', 'test': [40 + 10 * i, 50 + 10 * i]} for i in range(6)]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'protocol.json').write_text(json.dumps({'code_sha256': {}, 'archive_sha256': runner.ARCHIVE_SHA, 'cases': cases}))
            def load_archive(archive, months=None):
                self.assertTrue((out / 'source_access_started.json').exists())
                self.assertEqual(archive, runner.ARCHIVE)
                return loaded
            module.load_waterhub_archive = Mock(side_effect=load_archive)
            fitted = {'selected': {}, 'guard_selected': {}, 'shape_support_threshold': None}
            def score(bundle, frame):
                return pd.DataFrame({'baseline_prediction': np.zeros(len(frame), np.int8),
                                     'prediction': np.zeros(len(frame), np.int8)}, index=frame.index)
            with patch.dict(sys.modules, {'waterhub_loader': module}), \
                 patch.object(runner, 'START', start), patch.object(runner, 'END', end), \
                 patch.object(runner, 'sha', return_value=runner.ARCHIVE_SHA), \
                 patch.object(runner, 'fit_case', return_value=fitted) as fitting, \
                 patch.object(runner, 'predict_frame', side_effect=score) as scoring, \
                 patch.object(runner.joblib, 'dump'), \
                 patch.object(waterhub_adapter, 'adapt_waterhub', return_value=adapted) as adapter, \
                 contextlib.redirect_stdout(io.StringIO()):
                runner.run(out)
            module.load_waterhub_archive.assert_called_once()
            args, kwargs = adapter.call_args
            self.assertEqual(args, (raw_a, raw_b, annotations))
            self.assertIs(kwargs['timestamp_ambiguity_mask'], mask)
            self.assertEqual(kwargs['grid_start'], start)
            self.assertEqual(kwargs['grid_end'], end - pd.Timedelta(minutes=1))
            self.assertEqual(fitting.call_count, 6)
            self.assertEqual(scoring.call_count, 6)
            for call, case in zip(scoring.call_args_list, cases):
                pd.testing.assert_index_equal(call.args[1].index, x.iloc[slice(*case['test'])].index)
            result = json.loads((out / 'results.json').read_text())
            self.assertFalse(result['acceptance']['passes_fresh_validation_requirements'])
            self.assertEqual(result['pooled']['baseline']['rows'], 60)


if __name__ == '__main__':
    unittest.main()
