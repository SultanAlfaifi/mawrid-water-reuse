"""Synthetic only: real fitted estimator parity and independent policy/clock checks.

No dataset, saved model, trial output, or network is read. Real-estimator tests
retain the frozen estimator parameters; fixtures and operating points are fixed.
"""
from __future__ import annotations

from copy import deepcopy
import pickle
import time
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.gecco_v9.streaming import StreamingPredictor, VERSION, OUTPUT_COLUMNS
from ml.gecco_v9.runtime import predict_frame
from ml.gecco_v9.conditional import ConditionalResidualHGBScorer
from ml.gecco_v6.local_change import LocalChangeScorer
from ml.gecco_v6.runtime_v4 import RecoveryEventDetector
from ml.gecco_v7.calibration_delayed import _choice


def snapshot(engine):
    return pickle.dumps((engine.samples_seen, engine.last_timestamp,
        list(engine.sensor_rows), list(engine.rescue_scores), engine.previous_reference,
        engine.episode_age, engine.released, engine.reference.samples_seen,
        list(engine.reference.sensor_rows), list(engine.reference.score_history),
        engine.reference.baseline_alarm_latched))


def assert_parity(test, actual, expected):
    test.assertEqual(actual.columns.tolist(), expected.columns.tolist())
    pd.testing.assert_index_equal(actual.index, expected.index)
    for name in actual:
        test.assertEqual(actual[name].dtype, expected[name].dtype)
        if name.endswith("prediction") or actual[name].dtype == bool:
            np.testing.assert_array_equal(actual[name], expected[name], err_msg=name)
        else:
            np.testing.assert_array_equal(np.isnan(actual[name]), np.isnan(expected[name]), err_msg=name)
            np.testing.assert_allclose(actual[name], expected[name], atol=1e-12, rtol=1e-12,
                                       equal_nan=True, err_msg=name)


CHANNELS = ["base", "shape", "level", "jump", "sustained", "confidence"]


class Classifier:
    def predict_proba(self, x):
        return np.column_stack([1 - x[:, 0], x[:, 0]])


class Prior(RecoveryEventDetector):
    def __init__(self):
        self.channels = list(CHANNELS)
        self.max_lookback_ = 60
        self.shape_ = Classifier()

    def _baseline_score(self, frame):
        return frame.base.to_numpy(float)

    def features(self, frame):
        return frame[["shape"]].to_numpy(float), np.isfinite(frame["shape"].to_numpy(float))


class Local:
    channels = list(CHANNELS)
    max_lookback_ = 74

    def score_components(self, frame):
        if frame.columns.tolist() != CHANNELS:
            raise AssertionError("Non-sensor fields reached a model")
        return {key: frame[key].to_numpy(float) for key in ("level", "jump", "sustained")}


class Long:
    channels = list(CHANNELS)
    max_lookback_ = 1440

    def score_components(self, frame):
        if frame.columns.tolist() != CHANNELS:
            raise AssertionError("Non-sensor fields reached a model")
        return {"long_context": frame.confidence.to_numpy(float)}


def micro_bundle(*, gap=0, low=.7, high=.9, policy="3of5", deadline=2, cadence=60):
    return {"version": VERSION, "sample_seconds": cadence, "gap_samples": gap,
        "long_model": Long(), "reference_bundle": {
            "local_model": Local(), "prior_bundle": {"model": Prior(),
                "baseline_threshold": .5, "baseline_policy": "instant"},
            "guard_selected": {"decision": "baseline"}, "shape_support_threshold": .5,
            "selected": {"seed": "baseline", "rescue": None}},
        "selected": _choice(low, high, policy, deadline if low is not None else 0, cadence)}


def micro_frame(n=80, cadence=60):
    return pd.DataFrame({"base": np.zeros(n), "shape": np.full(n, .8),
        "level": np.full(n, 2.), "jump": np.full(n, 2.),
        "sustained": np.full(n, 2.), "confidence": np.full(n, .1)},
        index=pd.date_range("2026-01-01", periods=n, freq=pd.Timedelta(seconds=cadence)))


class PolicyAndInputTests(unittest.TestCase):
    def test_confirmation_deadline_unknown_clear_and_rescue_have_separate_states(self):
        frame = micro_frame()
        frame.loc[frame.index[8:30], "base"] = 1
        frame.loc[frame.index[35:36], "base"] = 1  # Clears before deadline.
        frame.loc[frame.index[40:50], "base"] = 1
        frame.loc[frame.index[60:70], "base"] = 1
        frame.loc[frame.index[41], "confidence"] = np.nan
        frame.loc[frame.index[64], "base"] = np.nan
        frame.loc[frame.index[31:34], "confidence"] = .95
        bundle = micro_bundle()
        actual = StreamingPredictor(bundle).update_frame(frame)
        assert_parity(self, actual, predict_frame(bundle, frame))
        np.testing.assert_array_equal(actual.prediction.iloc[8:12], [0, 0, 1, 1])
        self.assertEqual(actual.prediction.iloc[35], 0)
        self.assertEqual(actual.prediction.iloc[36], 0)
        self.assertEqual(actual.prediction.iloc[41], 1)  # Unknown releases now.
        self.assertEqual(actual.prediction.iloc[64], -1)
        np.testing.assert_array_equal(actual.prediction.iloc[65:68], [0, 0, 1])
        self.assertEqual(actual.prediction.iloc[33], 1)  # Current3of5rescue.

    def test_rescue_does_not_release_confirmation_latch(self):
        frame = micro_frame(9)
        frame.loc[frame.index[1:5], "base"] = 1
        bundle = micro_bundle(low=.7, high=.9, policy="instant")
        engine = StreamingPredictor(bundle)
        # Fixed scalar confidence cannot simultaneously be below low and above
        # high; test independence directly by replacing only rescue evidence.
        with patch("ml.gecco_v9.streaming.separate_scores", return_value={"rescue_long_context": np.array([.99])}):
            engine.update(frame.index[0], frame.iloc[0])
            first = engine.update(frame.index[1], frame.iloc[1])
        self.assertEqual(first["prediction"], 1)
        self.assertFalse(engine.released)
        second = engine.update(frame.index[2], frame.iloc[2])
        self.assertEqual(second["prediction"], 0)
        self.assertEqual(engine.episode_age, 1)

    def test_policies_chunking_threshold_equality_and_long_latch(self):
        frame = micro_frame(1520)
        frame.loc[frame.index[6:1510], "base"] = 1
        frame.loc[frame.index[6], "confidence"] = .7  # Inclusive boundary.
        frame.loc[frame.index[1510:1513], "confidence"] = .9
        for policy in ("instant", "2of3", "3of5"):
            bundle = micro_bundle(policy=policy)
            engine = StreamingPredictor(bundle)
            result = pd.concat([engine.update_frame(frame.iloc[a:b]) for a, b in
                                [(0, 1), (1, 6), (6, 9), (9, 1441), (1441, 1512), (1512, 1520)]])
            assert_parity(self, result, predict_frame(bundle, frame))
            self.assertEqual(len(engine.sensor_rows), 1441)
            self.assertLessEqual(len(engine.reference.score_history), 5)
            self.assertLessEqual(len(engine.rescue_scores), 5)
            self.assertTrue((result.prediction.iloc[6:1510] == 1).all())

    def test_gap_empty_reset_and_labels_are_independent(self):
        frame = micro_frame(35).astype(object)
        frame["EVENT"] = object()
        frame["label"] = "never convert"
        frame.loc[frame.index[:7], CHANNELS] = "discarded gap"
        bundle = micro_bundle(gap=7)
        engine = StreamingPredictor(bundle)
        first = engine.update_frame(frame.iloc[:7])
        self.assertEqual(len(engine.sensor_rows), 0)
        self.assertEqual(len(engine.reference.sensor_rows), 0)
        before = snapshot(engine)
        empty = engine.update_frame(frame.iloc[:0])
        self.assertEqual(snapshot(engine), before)
        self.assertEqual(empty.columns.tolist(), list(OUTPUT_COLUMNS))
        rest = engine.update_frame(frame.iloc[7:])
        result = pd.concat([first, empty, rest])
        assert_parity(self, result, predict_frame(bundle, frame))
        engine.reset()
        assert_parity(self, engine.update_frame(frame), result)

    def test_bad_clock_or_schema_never_changes_state(self):
        frame = micro_frame(10)
        engine = StreamingPredictor(micro_bundle())
        engine.update_frame(frame.iloc[:3])
        before = snapshot(engine)
        invalid = [frame.iloc[2:4], frame.iloc[4:6], frame.iloc[3:6].iloc[::-1],
                   frame.iloc[3:6].set_axis(pd.RangeIndex(3))]
        duplicate = frame.iloc[3:6].copy(); duplicate.index = [frame.index[3]] * 3
        missing = frame.iloc[3:6].copy(); missing.index = pd.DatetimeIndex([frame.index[3], pd.NaT, frame.index[5]])
        wrong = frame.iloc[3:6].copy(); wrong.index = pd.date_range(frame.index[3], periods=3, freq="5min")
        invalid += [duplicate, missing, wrong, frame.iloc[3:6].drop(columns="base")]
        for chunk in invalid:
            with self.assertRaises(ValueError): engine.update_frame(chunk)
            self.assertEqual(snapshot(engine), before)
        for timestamp in (3, "2026-01-01", pd.NaT, frame.index[3].tz_localize("UTC")):
            with self.assertRaises(ValueError): engine.update(timestamp, frame.iloc[3])
            self.assertEqual(snapshot(engine), before)

    def test_numerical_exception_rolls_back_whole_chunk_and_row(self):
        frame = micro_frame(12)
        bundle = micro_bundle()
        engine = StreamingPredictor(bundle)
        engine.update_frame(frame.iloc[:3])
        before = snapshot(engine)
        original = bundle["long_model"].score_components
        calls = 0
        def fail_later(part):
            nonlocal calls
            calls += 1
            if calls == 2: raise FloatingPointError("synthetic numerical failure")
            return original(part)
        with patch.object(bundle["long_model"], "score_components", side_effect=fail_later):
            with self.assertRaises(FloatingPointError): engine.update_frame(frame.iloc[3:8])
        self.assertEqual(snapshot(engine), before)
        with patch.object(bundle["long_model"], "score_components", side_effect=FloatingPointError):
            with self.assertRaises(FloatingPointError): engine.update(frame.index[3], frame.iloc[3])
        self.assertEqual(snapshot(engine), before)
        assert_parity(self, engine.update_frame(frame.iloc[3:]), predict_frame(bundle, frame).iloc[3:])

    def test_future_suffix_and_mutable_policy_input_cannot_change_emitted_prefix(self):
        frame = micro_frame(70); frame.loc[frame.index[4:40], "base"] = 1
        bundle = micro_bundle(); frozen = deepcopy(bundle)
        engine = StreamingPredictor(bundle)
        first = engine.update_frame(frame.iloc[:30])
        bundle["selected"]["low_threshold"] = .05
        bundle["reference_bundle"]["selected"]["seed"] = "guarded"
        changed = frame.copy(); changed.iloc[30:] = np.nan
        engine.update_frame(changed.iloc[30:])
        assert_parity(self, first, predict_frame(frozen, frame).iloc[:30])
        self.assertEqual(engine.low, frozen["selected"]["low_threshold"])

    def test_actual_timestamp_resolution_and_deadline_units(self):
        frame = micro_frame(8); frame.loc[frame.index[1:6], "base"] = 1
        for unit in ("ns", "us"):
            current = frame.copy(); current.index = current.index.as_unit(unit)
            engine = StreamingPredictor(micro_bundle(high=None))
            result = pd.DataFrame([engine.update(t, r) for t, r in current.iterrows()], index=current.index)
            np.testing.assert_array_equal(result.prediction, predict_frame(micro_bundle(high=None), current).prediction)
        with self.assertRaises(ValueError): StreamingPredictor(micro_bundle(cadence=300))
        short = micro_frame(8, cadence=30); short.loc[short.index[1:6], "base"] = 1
        result = StreamingPredictor(micro_bundle(high=None, cadence=30)).update_frame(short)
        np.testing.assert_array_equal(result.prediction.iloc[1:4], [0, 0, 1])

    def test_inference_never_fits_calibrates_or_reads_source(self):
        frame = micro_frame(15)
        frame["EVENT"] = object()
        with patch.object(RecoveryEventDetector, "fit", side_effect=AssertionError("fit")), \
             patch.object(LocalChangeScorer, "fit", side_effect=AssertionError("fit")), \
             patch.object(ConditionalResidualHGBScorer, "fit", side_effect=AssertionError("fit")), \
             patch("ml.gecco_v7.calibration_delayed.calibrate", side_effect=AssertionError("calibrate")), \
             patch("pandas.read_csv", side_effect=AssertionError("source read")):
            result = StreamingPredictor(micro_bundle()).update_frame(frame)
        self.assertEqual(len(result), len(frame))


def synthetic(n, channels, seed):
    rng = np.random.default_rng(seed); t = np.arange(n)
    shared = .5 * np.sin(t / 43) + .2 * np.cos(t / 17)
    values = np.column_stack([4 + j + shared * (1 + j / 10) + .02 * rng.normal(size=n)
                              for j in range(channels)])
    labels = np.zeros(n, np.int8)
    for start, end in ((280, 310), (500, 550), (680, 710)):
        if start < n:
            labels[start:min(end, n)] = 1
            values[start:min(end, n), :2] += 2.5
    frame = pd.DataFrame(np.round(values, 4), columns=[f"s{i}" for i in range(channels)])
    return frame, labels


def fitted_bundle(channels, *, always_alarm=False):
    train, labels = synthetic(800, channels, 81 + channels)
    names = list(train.columns)
    prior = RecoveryEventDetector(channels=names).fit(train, labels)
    local = LocalChangeScorer(names).fit(train, labels)
    long = ConditionalResidualHGBScorer(names).fit(train, labels)
    assert prior.baseline_ is not None and prior.shape_ is not None
    assert local.is_fitted_ and long.model_ is not None and long.conditional_supported_
    return {"version": VERSION, "sample_seconds": 60, "gap_samples": 120,
        "long_model": long, "reference_bundle": {"local_model": local,
            "prior_bundle": {"model": prior, "baseline_threshold": -1. if always_alarm else .52,
                             "baseline_policy": "instant"},
            "guard_selected": ({"decision": "baseline"} if always_alarm else
                               {"decision": "candidate", "threshold": .5, "policy": "2of3"}),
            "shape_support_threshold": .5,
            "selected": ({"seed": "baseline", "rescue": None} if always_alarm else
                         {"seed": "guarded", "rescue": "jump", "threshold": 2., "policy": "2of3"})},
        "selected": _choice(1.1 if always_alarm else .7, None if always_alarm else .9,
                            "instant" if always_alarm else "3of5", 2, 60)}


class FittedEstimatorParityTests(unittest.TestCase):
    def test_real_six_channel_estimators_across1441rollover_and_long_alarm(self):
        with threadpool_limits(limits=1):
            bundle = fitted_bundle(6, always_alarm=True)
            frame, _ = synthetic(1690, 6, 44)
            frame.index = pd.date_range("2026-02-01", periods=len(frame), freq="min")
            expected = predict_frame(bundle, frame)
            engine = StreamingPredictor(bundle)
            started = time.perf_counter()
            chunks = [(0, 119), (119, 120), (120, 134), (134, 181), (181, 801),
                      (801, 1560), (1560, 1561), (1561, 1690)]
            result = pd.concat([engine.update_frame(frame.iloc[a:b]) for a, b in chunks])
            elapsed = time.perf_counter() - started
        assert_parity(self, result, expected)
        self.assertEqual(len(engine.sensor_rows), 1441)
        self.assertEqual(len(engine.reference.sensor_rows), 75)
        self.assertTrue(engine.reference.baseline_alarm_latched)
        self.assertTrue(engine.released)
        self.assertGreater(int((result.reference_prediction == 1).sum()), 1441)
        print(f"\nSynthetic fitted6-channel stream:1690rows in{elapsed:.3f}s; not a hardware or acceptance benchmark.")

    def test_real_nine_channel_partial_missing_and_fallback_scores(self):
        with threadpool_limits(limits=1):
            bundle = fitted_bundle(9)
            frame, _ = synthetic(340, 9, 99)
            frame.index = pd.date_range("2026-03-01", periods=len(frame), freq="min")
            frame.iloc[185:190, 0] = np.nan
            frame.iloc[211, 2] = np.inf
            frame.iloc[250:252, :5] = np.nan
            frame["EVENT"] = "do not read"; frame["future_label"] = object()
            expected = predict_frame(bundle, frame)
            engine = StreamingPredictor(bundle)
            result = pd.concat([engine.update_frame(frame.iloc[a:b]) for a, b in
                                [(0, 120), (120, 185), (185, 212), (212, 250), (250, 340)]])
        assert_parity(self, result, expected)
        self.assertTrue((result.loc[result.reference_prediction < 0, "prediction"] == -1).all())


class VerificationHelperTests(unittest.TestCase):
    def test_prefix_verifier_matches_both_interfaces_and_retains_explicit_scope(self):
        from ml.gecco_v9.verify_stream import verify_prefix
        frame = micro_frame(75)
        frame.iloc[12:40, frame.columns.get_loc('base')] = 1
        frame.iloc[17, frame.columns.get_loc('confidence')] = np.nan
        frame['EVENT'] = 'never parsed by inference'
        result, batch = verify_prefix(micro_bundle(gap=5), frame)
        self.assertTrue(result['exact_prediction_masks'])
        self.assertFalse(result['full_period_tested'])
        self.assertEqual(result['tested_sample_bounds'], [0, 75])
        self.assertEqual(result['score_relative_tolerance'], 0)
        self.assertEqual(result['memory_metrics']['maximum_runtime_history']['sensor_rows'], 70)
        self.assertEqual(result['latency_seconds']['individual_all_rows']['rows'], 75)
        self.assertEqual(len(batch), 75)

    def test_comparator_rejects_prediction_mask_dtype_and_absolute_score_errors(self):
        from ml.gecco_v9.verify_stream import compare_outputs
        expected = predict_frame(micro_bundle(), micro_frame(10))
        for column, value in [('prediction', 1), ('available', False), ('long_context', .10000000001)]:
            changed = expected.copy(); changed.loc[changed.index[4], column] = value
            with self.subTest(column=column), self.assertRaises(AssertionError):
                compare_outputs(expected, changed)
        changed = expected.copy(); changed['prediction'] = changed.prediction.astype('int64')
        with self.assertRaises(AssertionError): compare_outputs(expected, changed)
        changed = expected.copy(); changed.loc[changed.index[2], 'long_context'] = np.nan
        with self.assertRaises(AssertionError): compare_outputs(expected, changed)

    def test_completion_gate_precedes_bundle_and_source_access(self):
        from ml.gecco_v9 import verify_stream as module
        with patch.object(module.prototype, 'verify_run', side_effect=ValueError('incomplete')) as gate, \
             patch.object(module.prototype, '_load_bundle', side_effect=AssertionError('closed')), \
             patch.object(module, '_source_prefix', side_effect=AssertionError('closed')):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                module.verify_run_prefixes('/nonexistent/synthetic/incomplete-run')
            self.assertEqual(gate.call_count, 1)

    def test_no_clock_invention_and_invalid_nested_model_schema(self):
        from ml.gecco_v9.verify_stream import verify_prefix
        frame = micro_frame(10); frame.index = pd.RangeIndex(10)
        with self.assertRaises(ValueError): verify_prefix(micro_bundle(), frame)
        for value in (None, {}, {'prior_bundle': None}):
            bundle = micro_bundle(); bundle['reference_bundle'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): StreamingPredictor(bundle)
        for channels in (['EVENT'], ['p1', 'p1'], [], None):
            bundle = micro_bundle(); bundle['long_model'] = deepcopy(bundle['long_model'])
            bundle['long_model'].channels = channels
            with self.subTest(channels=channels), self.assertRaises(ValueError): StreamingPredictor(bundle)


if __name__ == "__main__":
    unittest.main()
