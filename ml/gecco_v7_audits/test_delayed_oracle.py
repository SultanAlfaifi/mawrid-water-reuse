"""Independent synthetic audit of the user-approved <=120-second experiment.

No real data, labels, saved models, results, or file IO. The scalar oracle uses
an explicit clock and latch, not the implementation's cumulative array logic.
This authorizes no revision to the original zero-extra-delay V7 results.
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v7 import calibration_delayed as cal
from ml.gecco_v7 import runtime_delayed, runtime_v2
from ml.gecco_v7 import recalibrate_delayed


def selected(low=.5, high=None, policy="instant", delay=2, seconds=60):
    return {"decision": "reference" if low is None and high is None else "candidate",
            "low_threshold": low, "high_threshold": high, "policy": policy,
            "confirmation_samples": delay if low is not None else 0,
            "cadence_seconds": seconds, "max_confirmation_seconds": 120,
            "confirmation_delay_seconds": delay * seconds if low is not None else 0}


def scalar_predict(reference, confidence, rescue, choice):
    result = []
    started_at = None
    retained = False
    width, required = {"instant": (1, 1), "2of3": (3, 2), "3of5": (5, 3)}[choice["policy"]]
    low, high = choice["low_threshold"], choice["high_threshold"]
    for t, ref in enumerate(reference):
        if ref != 1:
            started_at = None
            retained = False
            value = int(ref)
        else:
            if started_at is None:
                started_at = t * choice["cadence_seconds"]
            elapsed = t * choice["cadence_seconds"] - started_at
            if (low is None or not np.isfinite(confidence[t]) or confidence[t] >= low
                    or elapsed >= choice["confirmation_delay_seconds"]):
                retained = True
            value = int(retained)
        if high is not None and ref >= 0 and t + 1 >= width:
            observations = rescue[t + 1 - width:t + 1]
            if (all(np.isfinite(v) for v in observations) and rescue[t] >= high
                    and sum(v >= high for v in observations) >= required):
                value = 1
        result.append(value)
    return np.asarray(result, dtype=np.int8)


class LongModel:
    channels = ["p1", "p2"]

    def __init__(self):
        self.inputs = []

    def score_components(self, frame):
        self.inputs.append(frame.copy())
        return {"long_context": frame.p1.rolling(2, min_periods=2).mean().to_numpy()}


def fake_reference(bundle, frame, *, gap_samples):
    assert frame.columns.tolist() == ["p1", "p2"]
    observed = np.isfinite(frame.to_numpy()).all(axis=1)
    observed[:gap_samples] = False
    p = np.where(observed, (frame.p1 >= .2).astype(int), -1).astype(np.int8)
    return pd.DataFrame({"baseline_prediction": p, "prediction": p,
                         "level": frame.p2, "jump": frame.p2, "sustained": frame.p2,
                         "available": observed, "ignored_gap": np.arange(len(frame)) < gap_samples}, index=frame.index)


def bundle(choice=None):
    return {"version": "v7_hgb_corroborated_confirmation_120s", "sample_seconds": 60,
            "long_model": LongModel(), "reference_bundle": {"local_model": SimpleNamespace(channels=["p1", "p2"])},
            "selected": selected() if choice is None else choice, "gap_samples": 2}


class DelayedIndependentOracleTests(unittest.TestCase):
    def test_full_scalar_oracle_random_ternary_and_separate_rescue(self):
        rng = np.random.default_rng(7120016)
        for _ in range(80):
            ref = rng.choice([-1, 0, 1], size=91).astype(np.int8)
            confidence = rng.choice([-.2, .1, .5, .8, 1., np.nan, np.inf, -np.inf], size=len(ref))
            rescue = rng.choice([.1, .4, .8, 1., np.nan, np.inf, -np.inf], size=len(ref))
            for policy in ("instant", "2of3", "3of5"):
                for low, high, deadline in ((None, None, 0), (.5, None, 1), (.5, None, 2),
                                             (None, .8, 0), (.5, .8, 1), (.5, .8, 2)):
                    choice = selected(low, high, policy, deadline)
                    expected = scalar_predict(ref, confidence, rescue, choice)
                    actual = cal.predict(ref, confidence, choice, rescue)
                    np.testing.assert_array_equal(actual, expected)
                    np.testing.assert_array_equal(actual >= 0, ref >= 0)

    def test_episode_deadline_is_elapsed_seconds_and_long_latch_survives(self):
        for seconds, deadline in ((30, 2), (60, 2), (90, 1), (120, 1)):
            ref = np.r_[0, np.ones(2000), 0, np.ones(4), -1, np.ones(4)].astype(np.int8)
            score = np.zeros(len(ref)); choice = selected(delay=deadline, seconds=seconds)
            p = cal.predict(ref, score, choice)
            first = np.flatnonzero(p == 1)[0]
            self.assertEqual((first - 1) * seconds, deadline * seconds)
            self.assertLessEqual((first - 1) * seconds, 120)
            self.assertTrue((p[first:2001] == 1).all())
            np.testing.assert_array_equal(p, scalar_predict(ref, score, score, choice))

    def test_unknown_releases_immediately_then_latches_until_reference_reset(self):
        for unknown in (np.nan, np.inf, -np.inf):
            r = np.array([0, 1, 1, 1, 1, -1, 1, 1, 1], np.int8)
            s = np.array([0, 0, unknown, 0, 0, 0, 0, 0, 0])
            p = cal.predict(r, s, selected())
            np.testing.assert_array_equal(p, [0, 0, 1, 1, 1, -1, 0, 0, 1])

    def test_prefix_and_future_mutation_of_all_inference_inputs(self):
        rng = np.random.default_rng(9031)
        r = rng.choice([-1, 0, 1], 120).astype(np.int8)
        s = rng.random(120); q = rng.random(120); s[::9] = np.nan; q[::13] = np.nan
        for policy in ("instant", "2of3", "3of5"):
            choice = selected(.5, .8, policy)
            whole = cal.predict(r, s, choice, q)
            for stop in (0, 1, 2, 4, 6, 61, 119):
                np.testing.assert_array_equal(cal.predict(r[:stop], s[:stop], choice, q[:stop]), whole[:stop])
                rr, ss, qq = r.copy(), s.copy(), q.copy()
                rr[stop:] = 1; ss[stop:] = 99; qq[stop:] = -99
                np.testing.assert_array_equal(cal.predict(rr, ss, choice, qq)[:stop], whole[:stop])

    def test_five_minute_or_misreported_deadline_cannot_activate_confirmation(self):
        r, s = np.array([0, 1, 1], np.int8), np.zeros(3)
        for choice in (selected(seconds=300), selected(seconds=90, delay=2),
                       {**selected(), "confirmation_delay_seconds": 60}):
            with self.assertRaises(ValueError):
                cal.predict(r, s, choice)
        no_delay = selected(None, .8, seconds=300)
        np.testing.assert_array_equal(cal.predict(r, s, no_delay), r)

    def test_runtime_rejects_actual_five_minute_timestamps_for_minute_policy(self):
        frame = pd.DataFrame({"p1": [.2] * 8, "p2": [.5] * 8},
                             index=pd.date_range("2020-01-01", periods=8, freq="5min"))
        with patch.object(runtime_v2, "reference_predict", side_effect=fake_reference):
            with self.assertRaises(ValueError):
                runtime_delayed.predict_frame(bundle(), frame)

    def test_runtime_rejects_irregular_duplicate_reversed_and_missing_timestamps(self):
        regular = pd.date_range("2020-01-01", periods=8, freq="min")
        irregular = regular.to_list(); irregular[4] += pd.Timedelta(seconds=10)
        duplicate = regular.to_list(); duplicate[4] = duplicate[3]
        missing = regular.to_list(); missing[4] = pd.NaT
        for name, index in (("irregular", pd.DatetimeIndex(irregular)),
                            ("duplicate", pd.DatetimeIndex(duplicate)),
                            ("reversed", regular[::-1]), ("missing", pd.DatetimeIndex(missing))):
            with self.subTest(name=name):
                frame = pd.DataFrame({"p1": [.2] * 8, "p2": [.5] * 8}, index=index)
                with patch.object(runtime_delayed, "score_frame") as scorer:
                    with self.assertRaises(ValueError):
                        runtime_delayed.predict_frame(bundle(), frame)
                    scorer.assert_not_called()

    def test_runtime_rejects_wrong_cadence_and_accepts_equal_timestamp_resolutions(self):
        for frequency in ("30s", "90s", "2min", "5min"):
            frame = pd.DataFrame({"p1": [.2] * 8, "p2": [.5] * 8},
                                 index=pd.date_range("2020-01-01", periods=8, freq=frequency))
            with patch.object(runtime_delayed, "score_frame") as scorer:
                with self.assertRaises(ValueError):
                    runtime_delayed.predict_frame(bundle(), frame)
                scorer.assert_not_called()
        outputs = []
        for unit in ("s", "ms", "us", "ns"):
            frame = pd.DataFrame({"p1": [.2] * 8, "p2": [.5] * 8},
                                 index=pd.date_range("2020-01-01", periods=8, freq="min").as_unit(unit))
            with patch.object(runtime_v2, "reference_predict", side_effect=fake_reference):
                outputs.append(runtime_delayed.predict_frame(bundle(), frame).prediction.to_numpy())
        for output in outputs[1:]:
            np.testing.assert_array_equal(output, outputs[0])

    def test_runtime_labels_cannot_enter_models_and_score_routing_is_exact(self):
        frame = pd.DataFrame({"p1": [.3, .3, .3, .3, .7, .2, .2, .8],
                              "p2": [.5, .5, 2., 2., 2., .5, .5, 2.],
                              "EVENT": [1] * 8, "label": [-1] * 8},
                             index=pd.date_range("2020-01-01", periods=8, freq="min"))
        choice = selected(.5, .8, "2of3")
        state = bundle(choice)
        with patch.object(runtime_v2, "reference_predict", side_effect=fake_reference):
            first = runtime_delayed.predict_frame(state, frame)
            changed = runtime_delayed.predict_frame(state, frame.assign(EVENT=99, label=3))
        pd.testing.assert_frame_equal(first, changed)
        self.assertTrue(all(x.columns.tolist() == ["p1", "p2"] for x in state["long_model"].inputs))
        np.testing.assert_array_equal(first.prediction, scalar_predict(
            first.reference_prediction.to_numpy(), first.long_context.to_numpy(),
            first.rescue_long_context.to_numpy(), choice))
        self.assertTrue((first.prediction.iloc[:2] == -1).all())

    def test_calibration_retains_ids_with_bounded_delay_and_reports_initial_tp_loss(self):
        blocks = []
        for k in range(2):
            y = np.zeros(3300, np.int8); r = np.zeros(3300, np.int8); s = np.full(3300, .1)
            for start in (200, 500, 800):
                y[start:start + 10] = 1; r[start:start + 10] = 1; s[start + 2:start + 10] = .9
            r[1200] = 1; r[1300:1302] = 1; r[1500:1510] = 1
            y[2000:2010] = -1
            blocks.append({"labels": y, "reference": r, "long_scores": s,
                           "rescue_scores": np.full(3300, np.nan), "source_start": 3300 * k})
        choice, trials = cal.calibrate(blocks, cadence_seconds=60)
        self.assertTrue(choice["feasible"])
        self.assertEqual(choice["confirmation_samples"], 2)
        self.assertEqual(choice["lost_positive_alarm_rows"], 12)
        self.assertEqual(choice["max_paired_extra_delay_seconds"], 120)
        for trial in (trial for trial in trials if trial["feasible"]):
            self.assertFalse(trial["lost_event_ids"])
            self.assertFalse(trial["lost_event_blocks"])
            self.assertFalse(trial["over_budget_delay_event_ids"])
            self.assertFalse(trial["over_budget_delay_event_blocks"])
            self.assertFalse(trial["added_false_duration_blocks"])
            self.assertFalse(trial["added_false_fragment_blocks"])
            self.assertTrue(trial["availability_equal"])
        actual_loss = 0
        for b in blocks:
            p = scalar_predict(b["reference"], b["long_scores"], b["rescue_scores"], choice)
            actual_loss += ((b["labels"] == 1) & (b["reference"] == 1) & (p != 1)).sum()
        self.assertEqual(actual_loss, choice["lost_positive_alarm_rows"])

    def test_run03_accepts_exactly_120_but_rejects_180_seconds_of_event_delay(self):
        labels = np.zeros(30, np.int8); labels[2:20] = 1
        reference = np.zeros(30, np.int8); reference[3:20] = 1
        for rows, acceptable in ((0, True), (1, True), (2, True), (3, False)):
            prediction = np.zeros(30, np.int8); prediction[3 + rows:20] = 1
            assessed = recalibrate_delayed.assess(labels, reference, reference, prediction)
            for key in ("if_vs_v7", "v6_vs_v7"):
                result = assessed[key]
                self.assertEqual(result["maximum_observed_paired_extra_delay_seconds"], rows * 60)
                self.assertEqual(result["noninferior"], acceptable)
                self.assertEqual(result["noninferior_zero_extra_delay"], rows == 0)
                self.assertEqual(result["lost_positive_alarm_rows"], rows)

    def test_run03_episode_bound_does_not_allow_unbounded_event_delay(self):
        labels = np.zeros(30, np.int8); labels[2:22] = 1
        reference = np.zeros(30, np.int8); reference[3] = 1; reference[12:22] = 1
        # Each continuous episode is obeying the 120s deadline, but losing the
        # early short episode postpones this event's first detection by 660s.
        candidate = cal.predict(reference, np.zeros(30), selected())
        self.assertEqual(candidate[14], 1)
        result = recalibrate_delayed.assess(labels, reference, reference, candidate)["v6_vs_v7"]
        self.assertFalse(result["lost_baseline_event_ids"])
        self.assertEqual(result["maximum_observed_paired_extra_delay_seconds"], 660)
        self.assertFalse(result["noninferior"])

    def test_run03_retains_event_identity_availability_and_false_alarm_constraints(self):
        labels = np.zeros(40, np.int8); labels[2:10] = 1; labels[20:30] = 1
        reference = np.zeros(40, np.int8); reference[3:10] = 1; reference[35] = -1
        changed_event = np.zeros(40, np.int8); changed_event[21:30] = 1; changed_event[35] = -1
        changed_availability = reference.copy(); changed_availability[35] = 0
        added_false = reference.copy(); added_false[15] = 1
        for name, candidate in (("different event same count", changed_event),
                                ("availability", changed_availability), ("false alarm", added_false)):
            with self.subTest(name=name):
                result = recalibrate_delayed.assess(labels, reference, reference, candidate)["v6_vs_v7"]
                self.assertFalse(result["noninferior"])
        result = recalibrate_delayed.assess(labels, reference, reference, changed_event)["v6_vs_v7"]
        self.assertEqual(result["baseline"]["confirmed_events"], result["candidate"]["confirmed_events"])
        self.assertTrue(result["lost_baseline_event_ids"])


if __name__ == "__main__":
    unittest.main()
