"""Independent synthetic checks for the explicitly relaxed 120-second attempt.

No publisher sources, models, or saved development measurements are opened.
The actual frozen model replay is a separate audit, not this fixture suite.
"""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from ml.gecco_v7 import runtime_v2, runtime_delayed, recalibrate_delayed as runner
from ml.gecco_v7.calibration_delayed import _choice, predict


class SyntheticLongModel:
    channels = ['p1', 'p2']

    def __init__(self):
        self.seen = []

    def fit(self, *args, **kwargs):
        raise AssertionError('Inference must never fit')

    def score_components(self, frame):
        self.seen.append(frame.copy())
        return {'long_context': frame.p1.to_numpy(float).copy()}


def fake_reference(bundle, frame, *, gap_samples):
    # The second input is a synthetic raw sensor, never a label column.
    values = frame.p2.to_numpy(float)
    available = np.isfinite(values) & (np.arange(len(frame)) >= gap_samples)
    ref = np.where(available, (values > .5).astype(np.int8), -1).astype(np.int8)
    return pd.DataFrame({'baseline_prediction': ref.copy(), 'prediction': ref,
                         'level': np.where(available, np.abs(values), np.nan),
                         'jump': np.where(available, .2, np.nan),
                         'sustained': np.where(available, .4, np.nan),
                         'available': available,
                         'ignored_gap': np.arange(len(frame)) < gap_samples}, index=frame.index)


def make_bundle(low=.5, high=.8, policy='instant', deadline=2, gap=0):
    return {'version': 'v7_hgb_corroborated_confirmation_120s',
            'long_model': SyntheticLongModel(),
            'reference_bundle': {'local_model': SimpleNamespace(channels=['p1', 'p2'])},
            'sample_seconds': 60, 'gap_samples': gap,
            'selected': _choice(low, high, policy, deadline if low is not None else 0, 60)}


class DelayedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({'p1': [.1, .1, .1, .1, .1, .9, .9, np.nan, .1, .9, .9, .9],
                                   'p2': [0, .8, .8, .8, 0, .2, 1.2, .8, np.nan, 1.2, 1.2, 0]},
                                  index=pd.date_range('2020-01-01', periods=12, freq='min'))

    def run_frame(self, state, frame, **kwargs):
        with patch.object(runtime_v2, 'reference_predict', side_effect=fake_reference):
            return runtime_delayed.predict_frame(state, frame, **kwargs)

    def test_confirmation_can_delay_exactly_120_seconds_and_then_latches(self):
        result = self.run_frame(make_bundle(high=None), self.frame)
        np.testing.assert_array_equal(result.prediction.iloc[:5], [0, 0, 0, 1, 0])
        self.assertEqual(result.prediction.iloc[7], 1)  # Unknown confidence releases immediately.
        self.assertEqual(result.prediction.iloc[8], -1)

    def test_rescue_uses_current_corroboration_not_just_long_confidence(self):
        result = self.run_frame(make_bundle(low=None), self.frame)
        self.assertTrue(np.isnan(result.rescue_long_context.iloc[5]))
        self.assertEqual(result.prediction.iloc[5], 0)
        self.assertEqual(result.rescue_long_context.iloc[6], .9)
        self.assertEqual(result.prediction.iloc[6], 1)

    def test_all_policies_match_the_selected_predictor_and_keep_availability(self):
        for policy in ('instant', '2of3', '3of5'):
            for low, high in ((None, None), (.5, None), (None, .8), (.5, .8)):
                state = make_bundle(low, high, policy)
                result = self.run_frame(state, self.frame)
                expected = predict(result.reference_prediction.to_numpy(np.int8),
                                   result.long_context.to_numpy(), state['selected'],
                                   rescue_scores=result.rescue_long_context.to_numpy())
                np.testing.assert_array_equal(result.prediction, expected)
                np.testing.assert_array_equal(result.prediction >= 0, result.reference_prediction >= 0)
                np.testing.assert_array_equal(result.available, result.prediction >= 0)

    def test_prefix_future_mutation_and_empty_frames(self):
        for policy in ('instant', '2of3', '3of5'):
            state = make_bundle(policy=policy)
            whole = self.run_frame(state, self.frame)
            for stop in (0, 1, 2, 3, 5, 8, 11):
                pd.testing.assert_frame_equal(self.run_frame(state, self.frame.iloc[:stop]), whole.iloc[:stop])
                changed = self.frame.copy(); changed.iloc[stop:] = 99999
                pd.testing.assert_frame_equal(self.run_frame(state, changed).iloc[:stop], whole.iloc[:stop])

    def test_labels_are_stripped_by_the_underlying_runtime(self):
        state = make_bundle()
        frame = self.frame.assign(label=-1, EVENT=0)
        old = self.run_frame(state, frame)
        new = self.run_frame(state, frame.assign(label=1, EVENT=999))
        pd.testing.assert_frame_equal(old, new)
        self.assertTrue(all(list(f) == ['p1', 'p2'] for f in state['long_model'].seen))

    def test_gap_reset_and_bundle_selection_not_mutated(self):
        state = make_bundle(gap=4)
        selected = state['selected'].copy()
        result = self.run_frame(state, self.frame)
        changed = self.frame.copy(); changed.iloc[:4] = 999
        pd.testing.assert_frame_equal(result, self.run_frame(state, changed))
        self.assertEqual(state['selected'], selected)
        self.assertTrue((result.prediction.iloc[:4] == -1).all())
        self.assertTrue(np.isnan(result.long_context.iloc[:4]).all())
        overridden = self.run_frame(state, self.frame, gap_samples=2)
        self.assertEqual(int(overridden.ignored_gap.sum()), 2)

    def test_wrong_version_cadence_or_deadline_rejected(self):
        state = make_bundle(); state['version'] = 'v7_hgb_guarded_v2'
        with self.assertRaises(ValueError): self.run_frame(state, self.frame)
        state = make_bundle(); state['sample_seconds'] = 300
        with self.assertRaises(ValueError): self.run_frame(state, self.frame)
        state = make_bundle(); state['selected']['confirmation_samples'] = 3
        with self.assertRaises(ValueError): self.run_frame(state, self.frame)

    def test_datetime_resolution_does_not_change_cadence_validation(self):
        expected = self.run_frame(make_bundle(), self.frame)
        for unit in ('s', 'ms', 'us', 'ns'):
            frame = self.frame.copy(); frame.index = frame.index.as_unit(unit)
            result = self.run_frame(make_bundle(), frame)
            np.testing.assert_array_equal(result.prediction, expected.prediction)
        for freq in ('30s', '2min'):
            frame = self.frame.copy(); frame.index = pd.date_range('2020-01-01', periods=len(frame), freq=freq)
            with self.assertRaises(ValueError): self.run_frame(make_bundle(), frame)
        frame = self.frame.copy(); index = list(frame.index); index[3] = pd.NaT
        frame.index = pd.DatetimeIndex(index)
        with self.assertRaises(ValueError): self.run_frame(make_bundle(), frame)


class DelayedAccountingTests(unittest.TestCase):
    def test_zero_delay_and_120_second_rules_are_distinct_and_explicit(self):
        labels = np.array([0] + [1] * 7 + [0], np.int8)
        reference = labels.copy()
        for delay in (0, 1, 2, 3):
            after = reference.copy(); after[1:1 + delay] = 0
            result = runner.assess(labels, reference, reference, after)['v6_vs_v7']
            self.assertEqual(result['noninferior'], delay <= 2)
            self.assertEqual(result['noninferior_zero_extra_delay'], delay == 0)
            self.assertEqual(result['maximum_allowed_extra_delay_seconds'], 120)
            self.assertEqual(result['maximum_observed_paired_extra_delay_seconds'], delay * 60)
            self.assertEqual(result['lost_positive_alarm_rows'], delay)

    def test_relaxed_rule_does_not_allow_event_or_availability_or_false_alarm_loss(self):
        labels = np.array([0, 1, 1, 1, 0, 0], np.int8)
        for candidate in ([0, 0, 0, 0, 0, 0], [0, 1, -1, 1, 0, 0], [0, 1, 1, 1, 1, 0]):
            result = runner.assess(labels, labels, labels, np.array(candidate, np.int8))['v6_vs_v7']
            self.assertFalse(result['noninferior'])


def synthetic_parent(root):
    parent = root / 'parent'; parent.mkdir()
    names = ([f'{year}_fold_{i}' for year in (2017, 2018) for i in range(1, 7)]
             + ['2019_disclosed_test', '2018-11', '2018-12', '2019-01', '2019-02', '2019-03', '2019-04'])
    periods = []
    for name in names:
        source = parent / name; source.mkdir()
        prior = root / 'prior' / name; prior.mkdir(parents=True)
        cal = pd.DataFrame({'sample_index': np.arange(10, 30), 'label': 0, 'baseline': 0,
                            'reference': 0, 'candidate': 0, 'long_context': .1,
                            'guarded_long_context': .1})
        test = pd.DataFrame({'sample_index': np.arange(30, 40), 'label': 0, 'baseline': 0,
                             'reference': 0, 'candidate': 0, 'long_context': .1,
                             'guarded_long_context': .1})
        for filename, frame in [('calibration_scores.csv.gz', cal), ('predictions.csv.gz', test)]:
            frame.to_csv(source / filename, index=False)
            frame.assign(level=.2, jump=.3, sustained=.4).to_csv(prior / filename, index=False)
        state = {'version': 'v7_hgb_guarded_v2', 'max_fit_index': 9,
                 'max_calibration_index': 29, 'long_model': 'synthetic-no-fit-model', 'sample_seconds': 60}
        joblib.dump(state, source / 'bundle.joblib')
        frozen = {'train': [0, 10], 'calibration_starts': [10, 15, 20, 25], 'test': [30, 40],
                  'bundle_sha256': runner.sha(source / 'bundle.joblib'),
                  'prior_folder': str(prior.relative_to(root)),
                  'prior_sha256': {name: runner.sha(prior / name) for name in
                                   ('calibration_scores.csv.gz', 'predictions.csv.gz')}}
        (source / 'freeze.json').write_text(json.dumps(frozen))
        (source / 'model_inspection.json').write_text('{}')
        periods.append({'case': name, 'source': name})
    (parent / 'plan.json').write_text(json.dumps({'attempt': 'run02_hgb_guarded', 'input_sha256': {}, 'code_sha256': {}}))
    (parent / 'results.json').write_text(json.dumps({'complete_cases': 19, 'all_prespecified_cases_complete': True, 'periods': periods}))
    (parent / 'audit.json').write_text(json.dumps({'passed': True, 'complete_replayed_cases': 19,
                                                 'replayed_rows': 190, 'failed_checks': 0}))
    return parent, names


class DelayedFreezeOrderingTests(unittest.TestCase):
    def test_failed_parent_audit_is_rejected_before_output_created(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); parent, _ = synthetic_parent(root); out = root / 'output'
            (parent / 'audit.json').write_text(json.dumps({'passed': False}))
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'verify'):
                with self.assertRaises(ValueError): runner.execute(parent, out)
            self.assertFalse(out.exists())

    def test_duplicate_parent_case_is_rejected_before_output_created(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); parent, _ = synthetic_parent(root); out = root / 'output'
            result = json.loads((parent / 'results.json').read_text())
            result['periods'][-1] = result['periods'][0]
            (parent / 'results.json').write_text(json.dumps(result))
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'verify'):
                with self.assertRaises(ValueError): runner.execute(parent, out)
            self.assertFalse(out.exists())

    def test_all_19_test_caches_are_parsed_only_after_new_selection_freeze(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); parent, names = synthetic_parent(root); out = root / 'output'
            real_read = pd.read_csv
            read_tests = []
            selected = _choice()
            def read_spy(path, *args, **kwargs):
                path = Path(path)
                if path.name == 'predictions.csv.gz':
                    name = path.parent.name
                    frozen = json.loads((out / name / 'freeze.json').read_text())
                    self.assertEqual(frozen['selected'], selected)
                    self.assertTrue(frozen['training_reused_without_refit'])
                    self.assertEqual(frozen['bundle_sha256'], runner.sha(out / name / 'bundle.joblib'))
                    read_tests.append(name)
                return real_read(path, *args, **kwargs)
            def calibrate_spy(blocks, **kwargs):
                self.assertEqual(len(blocks), 4)
                self.assertEqual([b['source_start'] for b in blocks], [10, 15, 20, 25])
                self.assertTrue(all(len(b['labels']) == 5 for b in blocks))
                return selected.copy(), [{'feasible': True}]
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'verify'), \
                    patch.object(runner, 'code_paths', return_value=[]), \
                    patch.object(runner, 'calibrate', side_effect=calibrate_spy) as calibration, \
                    patch.object(runner.pd, 'read_csv', side_effect=read_spy), redirect_stdout(StringIO()):
                runner.execute(parent, out)
            self.assertEqual(calibration.call_count, 19)
            self.assertEqual(sorted(read_tests), sorted(names * 2))
            result = json.loads((out / 'results.json').read_text())
            self.assertEqual(result['complete_cases'], 19)
            for name in names:
                after = joblib.load(out / name / 'bundle.joblib')
                self.assertEqual(after['long_model'], 'synthetic-no-fit-model')


if __name__ == '__main__':
    unittest.main()
