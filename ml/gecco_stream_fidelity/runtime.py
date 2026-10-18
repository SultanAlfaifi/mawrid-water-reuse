"""Experimental V9 stream with numerically persistent frozen IF features.

Only the IF baseline feature computation changes implementation, to reproduce
the original full-prefix pandas kernel. Fitted estimators, feature definition,
thresholds and policies are unchanged. No frozen file is patched or monkey-
patched. This module is not wired into the existing prototype/production path.
The inherited V9 stream supplies clock validation,1441row long-feature history,
confirmation/rescue states and atomic row/chunk commits. The reference retains
75sensor rows plus15observations/channel and scalar numerical accumulators.
The initial gap never enters any numerical accumulator.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.gecco_v6 import runtime_v4 as frozen
from ml.gecco_v9.streaming import StreamingPredictor as PreviousV9Stream
from ml.gecco_stream_fidelity.rolling import RollingBaselineFeatures


class _NumericalReferenceStream(frozen.StreamingPredictor):
    def reset(self):
        super().reset()
        self.baseline_features = RollingBaselineFeatures(self.channels)

    def update(self, row):
        if self.samples_seen < self.gap_samples:
            return super().update(row)
        if any(c not in row for c in self.channels):
            raise ValueError('Every fitted sensor channel is required')
        values = {c: float(row[c]) for c in self.channels}
        features, eligible = self.baseline_features.update(values)
        self.sensor_rows.append(values)
        frame = pd.DataFrame(self.sensor_rows, columns=self.channels)
        components = frozen._components(self.bundle, frame)
        record = {key: float(value[-1]) for key, value in components.items()}
        model = self.bundle['prior_bundle']['model']
        if not hasattr(model, 'baseline_'):
            raise ValueError('A fitted original RecoveryEventDetector baseline is required')
        record['baseline_score'] = (float(-model.baseline_.score_samples(features[None, :])[0])
                                    if eligible and model.baseline_ is not None else np.nan)
        # Below is the frozen V6 update policy sequence, using its unchanged
        # functions and the corrected score BEFORE any latch/persistence update.
        history = (list(self.score_history) + [record])[-frozen.SCORE_HISTORY_ROWS:]
        prior = self.bundle['prior_bundle']
        base = int(frozen.baseline_predict([r['baseline_score'] for r in history],
                   prior['baseline_threshold'], prior.get('baseline_policy', 'instant'))[-1])
        guard = self.bundle['guard_selected']
        if base != 1:
            self.baseline_alarm_latched = False
            seed = base
        else:
            if guard['decision'] == 'baseline':
                keep = True
            else:
                gate = frozen.suppression_gate([r['guarded_shape'] for r in history],
                            guard['threshold'], guard['policy'])[-1]
                keep = gate != 0
            self.baseline_alarm_latched = self.baseline_alarm_latched or bool(keep)
            seed = int(self.baseline_alarm_latched)
        record['baseline_prediction'] = base
        record['guarded_prediction'] = seed
        rescue = {key: np.asarray([r['rescue__' + key] for r in history]) for key in frozen.COMPONENT_KEYS}
        bases = np.asarray([r['baseline_prediction'] for r in history], dtype=np.int8)
        seeds = np.asarray([r['guarded_prediction'] for r in history], dtype=np.int8)
        prediction = int(frozen.joint_predict(bases, seeds, rescue, self.bundle['selected'])[-1])
        record.update(prediction=prediction, available=prediction >= 0, ignored_gap=False)
        self.score_history.append(record)
        self.samples_seen += 1
        return dict(record)


class StreamingPredictor(PreviousV9Stream):
    """Same V9 update(timestamp,row)/update_frame(frame)/reset API.

    Qualified only for the exact pandas kernel checked by RollingBaselineFeatures.
    A batch/stream score check is still required for every claimed bundle/scope.
    No fit, label-based decisions, file/source loading or actuator commands.
    """
    def reset(self):
        super().reset()
        self.reference = _NumericalReferenceStream(self._reference_config, gap_samples=self.gap_samples)

    def _fork(self):
        staged = super()._fork()
        staged.reference.baseline_features = self.reference.baseline_features.clone()
        return staged
