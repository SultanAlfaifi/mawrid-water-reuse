"""The same V5 trainer with explicit missing-label exclusion for a new source.

Unknown labels never become positive/negative training examples. Known-normal
15/61-row windows are required for baseline/floor fitting. Measured historical
context remains a feature regardless of its label availability. Inference is
inherited unchanged. With all labels known, this must match the original
trainer numerically; this adapter is not a new hyperparameter recipe.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest,ExtraTreesClassifier
from threadpoolctl import threadpool_limits
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gecco_v5'))
from recovery_candidate import RecoveryEventDetector,CLASSIFIER_PARAMS,event_intervals,build_features

class PartiallyLabeledRecoveryDetector(RecoveryEventDetector):
    def fit(self, frame, labels):
        x = self._frame(frame)
        y = np.asarray(labels)
        if y.shape != (len(x),) or y.dtype.kind not in "biu" or not np.isin(y, [-1, 0, 1]).all():
            raise ValueError("labels must be same-length integer labels: -1 unknown, 0 normal, 1 event")
        known = y >= 0
        normal = y == 0
        y = y == 1
        self.baseline_ = None; self.shape_ = None
        self.fit_rows_ = 0; self.fit_events_ = 0; self.baseline_fit_rows_ = 0
        self.fit_status_ = "insufficient_normal_training"
        baseline_X, baseline_eligible, _ = build_features(x, "baseline15", self.channels)
        normal15 = pd.Series(normal).rolling(15, min_periods=15).sum().eq(15).to_numpy()
        base_fit = baseline_eligible & normal15
        self.baseline_fit_rows_ = int(base_fit.sum())
        if base_fit.sum() >= 256:
            self.baseline_ = IsolationForest(n_estimators=200, max_samples=256,
                contamination="auto", n_jobs=1, random_state=20261016).fit(baseline_X[base_fit])
        clean = pd.Series(normal).rolling(61, min_periods=61).sum().eq(61).to_numpy()
        self.normal_scale_window_mask_ = clean
        if clean.sum() < 100:
            return self
        delta = x.diff().abs().to_numpy()
        floors = []
        for j in range(len(self.channels)):
            values = delta[clean, j]
            positive = values[np.isfinite(values) & (values > 0)]
            observed = x.to_numpy()[clean, j]
            finite = observed[np.isfinite(observed)]
            epsilon = max(np.median(np.abs(finite)) * 1e-12, 1e-12) if finite.size else 1e-12
            floors.append(max(float(np.quantile(positive, .75)) if positive.size else 0., epsilon))
        self.noise_floor_ = np.asarray(floors)
        features, eligible = self.features(x)
        eligible &= known
        self.fit_rows_ = int(eligible.sum())
        events = [np.flatnonzero(eligible[s:e]) + s for s, e in event_intervals(y)]
        events = [event for event in events if len(event)]
        self.fit_events_ = len(events)
        if eligible.sum() < 100 or not events or not (eligible & ~y).any():
            self.fit_status_ = "one_class_training"
            return self
        # Equal positive mass per original event. Within normal data, emphasize
        # high-IF examples so the classifier learns actual alarm-like artifacts.
        weight = np.zeros(len(y))
        for event in events:
            weight[event] = .5 / (len(events) * len(event))
        base_scores = self._baseline_score(x)
        normal_scores = base_scores[normal & np.isfinite(base_scores)]
        alert_level = np.quantile(normal_scores, .95) if len(normal_scores) else np.inf
        negative = eligible & ~y
        weight[negative] = 1. + 4. * (base_scores[negative] >= alert_level)
        weight[negative] *= .5 / weight[negative].sum()
        weight *= eligible.sum()
        self.shape_ = ExtraTreesClassifier(**CLASSIFIER_PARAMS)
        with threadpool_limits(limits=1):
            self.shape_.fit(features[eligible], y[eligible].astype(int), sample_weight=weight[eligible])
        self.fit_status_ = "fitted"
        return self

