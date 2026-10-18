"""Synthetic integration tests for the bounded-confirmation replay wrapper."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v7 import runtime_delayed as runtime
from ml.gecco_v7.calibration_delayed import _choice, predict
from ml.gecco_v7.evidence import separate_scores


def bundle(selected=None):
    return {"version": "v7_hgb_corroborated_confirmation_120s", "sample_seconds": 60,
            "selected": selected if selected is not None else _choice(.5, None, confirmation_samples=2)}


def scored_fixture(n=12):
    reference = np.array([0, 1, 1, 1, 1, 0, 0, 0, -1, 0, 1, 1], np.int8)[:n]
    return pd.DataFrame({"reference_prediction": reference, "baseline_prediction": reference.copy(),
                         "prediction": reference.copy(), "available": reference >= 0,
                         "ignored_gap": False, "level": np.zeros(n), "jump": np.zeros(n),
                         "sustained": np.zeros(n), "long_context": np.full(n, .1)})


class DelayedRuntimeTests(unittest.TestCase):
    def test_wrapper_uses_noop_inner_policy_and_raw_confidence_confirmation(self):
        state = bundle(); original = state["selected"].copy()
        scored = scored_fixture(); scored.loc[:, ["level", "jump", "sustained"]] = 3
        with patch.object(runtime, "score_frame", return_value=scored.copy()) as scorer:
            result = runtime.predict_frame(state, pd.DataFrame({"sensor": np.arange(12)}), gap_samples=7)
        np.testing.assert_array_equal(result.prediction[:6], [0, 0, 0, 1, 1, 0])
        self.assertEqual(scorer.call_args.kwargs["gap_samples"], 7)
        inner = scorer.call_args.args[0]["selected"]
        self.assertEqual(inner["decision"], "reference")
        self.assertIsNone(inner["low_threshold"]); self.assertIsNone(inner["high_threshold"])
        self.assertEqual(state["selected"], original)

    def test_rescue_requires_current_finite_local_change(self):
        scored = scored_fixture(); scored["long_context"] = .9
        scored.loc[6, "jump"] = 2
        scored.loc[7, "jump"] = 2; scored.loc[7, "level"] = np.nan
        state = bundle(_choice(None, .8))
        with patch.object(runtime, "score_frame", return_value=scored.copy()):
            result = runtime.predict_frame(state, pd.DataFrame(index=np.arange(12)))
        self.assertEqual(result.prediction[5], 0)
        self.assertEqual(result.prediction[6], 1)
        self.assertEqual(result.prediction[7], 0)
        self.assertEqual(result.prediction[8], -1)
        self.assertTrue(np.isnan(result.rescue_long_context[5]))

    def test_matches_direct_mask_and_calibrated_predictor(self):
        scored = scored_fixture(); scored.loc[::2, "jump"] = 2
        scored.loc[5:7, "long_context"] = .9
        for policy in ("instant", "2of3", "3of5"):
            state = bundle(_choice(.5, .8, policy, 2))
            with patch.object(runtime, "score_frame", return_value=scored.copy()):
                result = runtime.predict_frame(state, pd.DataFrame(index=np.arange(12)))
            masks = separate_scores({k: scored[k].to_numpy() for k in ("level", "jump", "sustained")}, scored.long_context.to_numpy())
            expected = predict(scored.reference_prediction.to_numpy(), scored.long_context.to_numpy(), state["selected"], masks["rescue_long_context"])
            np.testing.assert_array_equal(result.prediction, expected)
            np.testing.assert_array_equal(result.available, result.prediction >= 0)

    def test_prefix_preserved_through_wrapper(self):
        scored = scored_fixture(); state = bundle(_choice(.5, .8, "2of3", 2))
        with patch.object(runtime, "score_frame", return_value=scored.copy()):
            whole = runtime.predict_frame(state, pd.DataFrame(index=np.arange(12)))
        for n in (0, 1, 2, 4, 6, 10):
            with patch.object(runtime, "score_frame", return_value=scored.iloc[:n].copy()):
                prefix = runtime.predict_frame(state, pd.DataFrame(index=np.arange(n)))
            pd.testing.assert_frame_equal(prefix, whole.iloc[:n])

    def test_version_and_cadence_must_match(self):
        with self.assertRaises(ValueError): runtime.predict_frame({"version": "wrong"}, pd.DataFrame())
        state = bundle(); state["sample_seconds"] = 300
        with self.assertRaises(ValueError): runtime.predict_frame(state, pd.DataFrame())


if __name__ == "__main__":
    unittest.main()
