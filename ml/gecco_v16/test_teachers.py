"""Synthetic wiring/causality tests only; no sources or numerical CSVs."""
from __future__ import annotations

from contextlib import ExitStack
from unittest import TestCase, main
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v16 import teachers as t
from ml.gecco_v7.calibration_delayed import _choice


class FakeShape:
    def predict_proba(self, x):
        score = np.clip(x[:, 0] / 100, 0, 1)
        return np.column_stack((1 - score, score))


class FakeRecovery:
    calls = []
    has_if = True
    nan_scores = False
    def __init__(self, config, channels):
        self.config_id = config
        self.channels = list(channels)
        self.max_lookback_ = 60
    def fit(self, frame, labels):
        self.calls.append((frame.copy(), labels.copy()))
        self.baseline_ = object() if self.has_if else None
        self.shape_ = FakeShape()
        self.fit_status_ = "synthetic_fitted"
        return self
    def _baseline_score(self, frame):
        if self.nan_scores:
            return np.full(len(frame), np.nan)
        return frame[self.channels[0]].to_numpy(float) / 100
    def features(self, frame):
        x = frame[self.channels].to_numpy(float)
        return x, np.isfinite(x).all(axis=1)
    def score_components(self, frame):
        # The real runtime explicitly calls this same frozen base implementation.
        return t.v6_runtime.RecoveryEventDetector.score_components(self, frame)


class FakeLocal:
    calls = []
    scored = []
    def __init__(self, channels):
        self.channels = list(channels)
        self.max_lookback_ = 74
    def fit(self, frame, labels):
        self.calls.append((frame.copy(), labels.copy()))
        self.fit_status_ = "synthetic_fitted"
        return self
    def score_components(self, frame):
        self.scored.append(frame.copy())
        a = frame[self.channels[0]].to_numpy(float)
        return {key: np.abs(a) / (200 + i) for i, key in enumerate(t.LOCAL_KEYS)}


class FakeLong:
    calls = []
    scored = []
    def __init__(self, channels):
        self.channels = list(channels)
    def fit(self, frame, labels):
        self.calls.append((frame.copy(), labels.copy()))
        self.fit_status_ = "synthetic_fitted"
        return self
    def score_components(self, frame):
        self.scored.append(frame.copy())
        a = frame[self.channels[0]].to_numpy(float)
        return {"long_context": np.clip(a / 300, 0, 1)}


def inputs():
    fit = pd.DataFrame({"a": np.arange(320, dtype=float), "b": 1., "label": 999})
    y = np.zeros(len(fit), np.int8)
    y[20:25] = -1
    y[60:70] = 1
    frames, labels, starts = [], [], []
    start = len(fit)
    for k in range(4):
        frame = pd.DataFrame({"a": np.arange(130, dtype=float) + 100 * k,
                              "b": 2., "EVENT": -999})
        target = np.zeros(len(frame), np.int8)
        target[120] = -1
        target[123:125] = 1
        frames.append(frame)
        labels.append(target)
        starts.append(start)
        start += len(frame)
    return fit, y, frames, labels, starts


class TeachersTests(TestCase):
    def setUp(self):
        for cls in (FakeRecovery, FakeLocal, FakeLong):
            cls.calls = []
        FakeLocal.scored = []; FakeLong.scored = []
        FakeRecovery.has_if = True; FakeRecovery.nan_scores = False
        self.stack = ExitStack()
        for name, cls in (("PartiallyLabeledRecoveryDetector", FakeRecovery),
                          ("LocalChangeScorer", FakeLocal), ("OnsetWeightedHGBScorer", FakeLong)):
            self.stack.enter_context(patch.object(t, name, cls))
        self.addCleanup(self.stack.close)

    def mock_calibration(self):
        funcs = {
            "select_baseline": ({"threshold": .5, "policy": "instant"}, [{"synthetic": True}]),
            "calibrate_guard": ({"decision": "baseline", "threshold": None, "policy": None}, []),
            "calibrate_joint": ({"seed": "baseline", "rescue": None, "threshold": None, "policy": "instant"}, []),
            "calibrate_v8": (_choice(cadence_seconds=60), []),
        }
        return {name: self.stack.enter_context(patch.object(t, name, return_value=result))
                for name, result in funcs.items()}

    def fit(self, args=None):
        return t.fit_teacher(*(inputs() if args is None else args), channels=["a", "b"])

    def test_fit_scope_unknown_exclusion_and_no_forecast(self):
        self.mock_calibration()
        args = inputs(); before = [x.copy(deep=True) for x in [args[0], *args[2]]]
        teacher = self.fit(args)
        self.assertTrue(teacher["supported"])
        self.assertEqual(teacher["status"], "ready")
        for cls in (FakeRecovery, FakeLocal, FakeLong):
            self.assertEqual(len(cls.calls), 1)
            self.assertEqual(list(cls.calls[0][0]), ["a", "b"])
            self.assertEqual(len(cls.calls[0][0]), 320)
        np.testing.assert_array_equal(FakeRecovery.calls[0][1], args[1])
        np.testing.assert_array_equal(FakeLong.calls[0][1], args[1])
        np.testing.assert_array_equal(FakeLocal.calls[0][1], args[1] != 0)
        self.assertEqual(FakeLocal.calls[0][1].dtype, bool)
        for old, new in zip(before, [args[0], *args[2]]):
            pd.testing.assert_frame_equal(old, new)
        self.assertFalse(teacher["training_metadata"]["forecast_scored_during_fit"])

    def test_four_separate_gaps_before_all_features(self):
        self.mock_calibration(); teacher = self.fit()
        for scored in (FakeLocal.scored, FakeLong.scored):
            self.assertEqual([len(f) for f in scored], [10] * 4)
            self.assertEqual([float(f.a.iloc[0]) for f in scored], [120., 220., 320., 420.])
            self.assertTrue(all(list(f.columns) == ["a", "b"] for f in scored))
        for rows, start in zip(teacher["calibration_data"], inputs()[-1]):
            np.testing.assert_array_equal(rows.sample_index, np.arange(start, start + 130))
            self.assertTrue(rows.iloc[:120].baseline_score.isna().all())
            for key in ("baseline", "v6", "v8"):
                self.assertTrue((rows[key].iloc[:120] == -1).all())
                self.assertEqual(rows[key].dtype, np.int8)

    def test_unknown_mask_only_baseline_selection(self):
        mocks = self.mock_calibration(); teacher = self.fit()
        args, kwargs = mocks["select_baseline"].call_args
        y = np.concatenate(inputs()[3])
        self.assertTrue(kwargs["baseline"])
        np.testing.assert_array_equal(args[0], y == 1)
        self.assertTrue(np.isnan(args[1][y < 0]).all())
        for rows in teacher["calibration_data"]:
            self.assertTrue(np.isfinite(rows.baseline_score.iloc[120]))
            self.assertNotEqual(int(rows.baseline.iloc[120]), -1)
        guard_blocks = mocks["calibrate_guard"].call_args.args[0]
        for block, target in zip(guard_blocks, inputs()[3]):
            np.testing.assert_array_equal(block["labels"], target)

    def test_q99_and_joint_receive_original_normal_semantics(self):
        self.mock_calibration()
        original = t.fit_shape_reference
        with patch.object(t, "fit_shape_reference", wraps=original) as shape:
            teacher = self.fit()
        blocks = shape.call_args.args[0]
        for block, target in zip(blocks, inputs()[3]):
            np.testing.assert_array_equal(block["labels"], target)
        self.assertIsNone(teacher["v6_bundle"]["shape_support_threshold"])
        for rows in teacher["calibration_data"]:
            self.assertTrue(rows["rescue__level"].isna().all())

    def test_v8_calibration_uses_rebuilt_v6_and_same_source_axis(self):
        mocks = self.mock_calibration(); teacher = self.fit()
        v8_blocks = mocks["calibrate_v8"].call_args.args[0]
        self.assertEqual(mocks["calibrate_v8"].call_args.kwargs, {"cadence_seconds": 60})
        for block, rows in zip(v8_blocks, teacher["calibration_data"]):
            np.testing.assert_array_equal(block["reference"], rows.v6)
            np.testing.assert_array_equal(block["labels"], rows.label)
            np.testing.assert_array_equal(block["long_scores"], rows.long_context)
            self.assertEqual(block["source_start"], rows.sample_index.iloc[0])
        self.assertIs(teacher["v8_bundle"]["reference_bundle"], teacher["v6_bundle"])
        self.assertIs(teacher["v6_bundle"]["prior_bundle"]["model"], teacher["training_models"]["recovery"])
        self.assertEqual(teacher["v8_bundle"]["max_fit_index"], 319)
        self.assertEqual(teacher["v8_bundle"]["max_calibration_index"], 839)

    def test_missing_if_is_unsupported_without_calibration_or_hgb_fit(self):
        mocks = self.mock_calibration(); FakeRecovery.has_if = False
        teacher = self.fit()
        self.assertEqual(teacher["status"], "unsupported_missing_baseline_if")
        self.assertFalse(teacher["supported"])
        self.assertIsNone(teacher["v6_bundle"])
        self.assertEqual(len(FakeLong.calls), 0)
        self.assertFalse(any(mock.called for mock in mocks.values()))
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            t.predict_teacher(teacher, inputs()[0])

    def test_no_known_calibration_and_no_finite_calibration(self):
        mocks = self.mock_calibration()
        args = list(inputs()); args[3] = [np.full(130, -1, np.int8) for _ in range(4)]
        teacher = self.fit(args)
        self.assertEqual(teacher["status"], "unsupported_no_finite_known_calibration")
        self.assertEqual(len(teacher["calibration_data"]), 4)
        self.assertTrue(all("baseline" not in f for f in teacher["calibration_data"]))
        FakeRecovery.nan_scores = True
        self.assertEqual(self.fit()["status"], "unsupported_no_finite_known_calibration")
        self.assertFalse(mocks["select_baseline"].called)

    def test_no_normal_calibration_and_selector_failure(self):
        mocks = self.mock_calibration()
        args = list(inputs()); args[3] = [np.ones(130, np.int8) for _ in range(4)]
        self.assertEqual(self.fit(args)["status"], "unsupported_no_observed_normal_calibration")
        self.assertFalse(mocks["select_baseline"].called)
        mocks["select_baseline"].side_effect = ValueError("no feasible finite operating point")
        with self.assertRaisesRegex(ValueError, "no feasible finite"):
            self.fit()
        self.assertEqual(len(FakeLong.calls), 0)

    def test_short_cal_blocks_keep_whole_axis_without_feature_calls(self):
        self.mock_calibration()
        fit, y, frames, labels, _ = inputs()
        frames = [f.iloc[:100].copy() for f in frames]
        labels = [v[:100] for v in labels]
        teacher = self.fit((fit, y, frames, labels, [320, 420, 520, 620]))
        self.assertEqual(teacher["status"], "unsupported_no_finite_known_calibration")
        self.assertEqual([len(f) for f in teacher["calibration_data"]], [100] * 4)
        self.assertEqual(FakeLocal.scored, [])

    def test_real_frozen_calibrators_and_runtime_compatibility(self):
        # Only model fitting/scoring are fake; all original calibrators execute.
        teacher = self.fit()
        self.assertEqual(teacher["status"], "ready")
        for raw, cached in zip(inputs()[2], teacher["calibration_data"]):
            actual = t.predict_teacher(teacher, raw)
            for key in ("baseline", "v6", "v8", "long_context", "level", "jump", "sustained"):
                np.testing.assert_array_equal(actual[key], cached[key])

    def test_forecast_label_isolation_index_and_exact_frozen_parity(self):
        self.mock_calibration(); teacher = self.fit()
        frame = inputs()[2][0].copy()
        frame.index = pd.date_range("2020-01-01", periods=len(frame), freq="min")
        frame["label"] = np.arange(len(frame))
        actual = t.predict_teacher(teacher, frame)
        direct = t.predict_v8_frame(teacher["v8_bundle"], frame[["a", "b"]], gap_samples=120)
        self.assertTrue(actual.index.equals(frame.index))
        for key in direct:
            np.testing.assert_array_equal(actual[key], direct[key])
        changed = frame.copy(); changed["EVENT"] = "ignored"; changed["label"] = -777
        pd.testing.assert_frame_equal(actual, t.predict_teacher(teacher, changed))

    def test_prefix_future_mutation_and_gap_independence(self):
        self.mock_calibration(); teacher = self.fit()
        frame = pd.DataFrame({"a": np.sin(np.arange(190) / 3) * 100, "b": 1.})
        actual = t.predict_teacher(teacher, frame)
        for stop in (0, 1, 119, 120, 121, 150, 190):
            pd.testing.assert_frame_equal(actual.iloc[:stop], t.predict_teacher(teacher, frame.iloc[:stop]))
        mutated = frame.copy(); mutated.iloc[150:, 0] = 1e9
        pd.testing.assert_frame_equal(actual.iloc[:150], t.predict_teacher(teacher, mutated).iloc[:150])
        mutated = frame.copy(); mutated.iloc[:120, :] = -1e9
        pd.testing.assert_frame_equal(actual, t.predict_teacher(teacher, mutated))

    def test_calibration_changes_do_not_enter_any_fit_call(self):
        self.mock_calibration(); args = list(inputs())
        self.fit(args)
        first = [(cls.calls[-1][0].copy(), cls.calls[-1][1].copy()) for cls in (FakeRecovery, FakeLocal, FakeLong)]
        args[2] = [f.assign(a=f.a + 10000) for f in args[2]]
        args[3] = [np.zeros(130, np.int8) for _ in args[3]]
        self.fit(args)
        for (frame, y), cls in zip(first, (FakeRecovery, FakeLocal, FakeLong)):
            pd.testing.assert_frame_equal(frame, cls.calls[-1][0])
            np.testing.assert_array_equal(y, cls.calls[-1][1])

    def test_validation_before_fit_rejects_bad_axis_labels_and_channels(self):
        bad = []
        args = list(inputs()); args[1] = args[1].astype(float); bad.append(args)
        args = list(inputs()); args[1] = args[1] >= 0; bad.append(args)
        args = list(inputs()); args[1] = args[1][:-1]; bad.append(args)
        args = list(inputs()); args[1][0] = 2; bad.append(args)
        args = list(inputs()); args[4] = [321, 450, 580, 710]; bad.append(args)
        args = list(inputs()); args[4] = [320, 450, 581, 710]; bad.append(args)
        args = list(inputs()); args[4] = [320., 450, 580, 710]; bad.append(args)
        args = list(inputs()); args[2] = args[2][:3]; bad.append(args)
        args = list(inputs()); args[2][0] = args[2][0].rename(columns={"b": "absent"}); bad.append(args)
        for args in bad:
            with self.subTest(args_type=type(args[1]).__name__), self.assertRaises(ValueError):
                self.fit(args)
        self.assertEqual(FakeRecovery.calls, [])
        for channels in ([], ["a", "a"], "ab", ["a", 2]):
            with self.assertRaises(ValueError):
                t.fit_teacher(*inputs(), channels=channels)

    def test_prediction_validates_bundle_gap_and_channel_order(self):
        self.mock_calibration(); teacher = self.fit(); frame = inputs()[0]
        for gap in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                t.predict_teacher(teacher, frame, gap_samples=gap)
        with self.assertRaises(ValueError):
            t.predict_teacher({}, frame)
        original = teacher["v8_bundle"]["reference_bundle"]
        teacher["v8_bundle"]["reference_bundle"] = dict(original)
        with self.assertRaisesRegex(ValueError, "very same"):
            t.predict_teacher(teacher, frame)
        teacher["v8_bundle"]["reference_bundle"] = original
        teacher["v8_bundle"]["long_model"].channels.reverse()
        with self.assertRaisesRegex(ValueError, "channel order"):
            t.predict_teacher(teacher, frame)


if __name__ == "__main__":
    main()
