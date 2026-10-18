"""Real fitted synthetic estimators only; no measured source or bundle access."""
from copy import deepcopy
import pickle
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from ml.gecco_stream_fidelity.runtime import StreamingPredictor
from ml.gecco_v9.test_streaming import fitted_bundle, synthetic, snapshot
from ml.gecco_v9.runtime import predict_frame
from ml.gecco_v9.verify_stream import compare_outputs


def numerical_snapshot(engine):
    return snapshot(engine), pickle.dumps(engine.reference.baseline_features.states)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with threadpool_limits(limits=1):
            cls.bundle = fitted_bundle(6, always_alarm=True)

    def test_fitted_batch_stream_parity_across_long_history_rollover_and_constant_tail(self):
        with threadpool_limits(limits=1):
            frame, _ = synthetic(1700, 6, 203)
            frame.iloc[600:1600, :2] = [.3, -.2]
            frame.iloc[350:355, 2] = np.nan; frame.iloc[1000, 3] = np.inf
            frame.index = pd.date_range('2026-01-01', periods=len(frame), freq='min')
            expected = predict_frame(self.bundle, frame)
            stream = StreamingPredictor(self.bundle)
            edges = [0,119,120,121,134,180,600,601,1001,1560,1561,1700]
            actual = pd.concat([stream.update_frame(frame.iloc[a:b]) for a,b in zip(edges[:-1],edges[1:])])
            compare_outputs(expected, actual)
            self.assertEqual(len(stream.sensor_rows), 1441)
            self.assertEqual(len(stream.reference.sensor_rows), 75)
            self.assertTrue(all(len(s.values) == 15 for s in stream.reference.baseline_features.states))
            self.assertTrue(stream.released)

    def test_gap_exclusion_labels_reset_and_empty_preserve_numerical_history(self):
        with threadpool_limits(limits=1):
            frame, _ = synthetic(190, 6, 204)
            frame.index = pd.date_range('2026-02-01', periods=len(frame), freq='min')
            frame = frame.astype(object); frame.iloc[:120] = 'discard before conversion'
            frame['EVENT'] = 'never a sensor'
            engine = StreamingPredictor(self.bundle)
            prefix = engine.update_frame(frame.iloc[:120])
            self.assertTrue(all(len(s.values) == 0 for s in engine.reference.baseline_features.states))
            before = numerical_snapshot(engine); empty = engine.update_frame(frame.iloc[:0])
            self.assertEqual(numerical_snapshot(engine), before); self.assertEqual(len(empty), 0)
            result = pd.concat([prefix, engine.update_frame(frame.iloc[120:])])
            compare_outputs(predict_frame(self.bundle, frame), result)
            engine.reset(); self.assertTrue(all(not s.values for s in engine.reference.baseline_features.states))
            compare_outputs(result, engine.update_frame(frame))

    def test_bad_clock_and_scoring_exception_rollback_accumulators_then_retry(self):
        with threadpool_limits(limits=1):
            frame, _ = synthetic(210, 6, 205)
            frame.index = pd.date_range('2026-03-01', periods=len(frame), freq='min')
            engine = StreamingPredictor(self.bundle); engine.update_frame(frame.iloc[:170])
            before = numerical_snapshot(engine)
            with self.assertRaises(ValueError): engine.update(frame.index[169], frame.iloc[170])
            self.assertEqual(numerical_snapshot(engine), before)
            original = self.bundle['long_model'].score_components
            calls = [0]
            def fail_later(part):
                calls[0] += 1
                if calls[0] == 4: raise FloatingPointError('synthetic scorer exception')
                return original(part)
            with patch.object(self.bundle['long_model'], 'score_components', side_effect=fail_later):
                with self.assertRaises(FloatingPointError): engine.update_frame(frame.iloc[170:])
            self.assertEqual(numerical_snapshot(engine), before)
            actual = engine.update_frame(frame.iloc[170:])
            compare_outputs(predict_frame(self.bundle, frame).iloc[170:], actual)


if __name__ == '__main__': unittest.main()
