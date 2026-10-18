"""V5 development: preserve original IF evidence, learn causal event shapes.

No data files are read here. All GECCO2017/2018/2019 sources are disclosed
development. Outputs are anomaly/event rankings, never safety probabilities.
"""
from __future__ import annotations

from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, IsolationForest
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml/gecco_v2"))
from candidates_supervised import build_features

CHANNELS18 = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
CHANNELS19 = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
CONFIGS = {
    "shape_invariant": {"channel_features": False},
    "shape_channel_relative": {"channel_features": True},
}
CLASSIFIER_PARAMS = dict(n_estimators=160, max_depth=12, min_samples_leaf=8,
                         max_features=.7, n_jobs=1, random_state=20261016)


def event_intervals(labels):
    edges = np.diff(np.r_[False, np.asarray(labels, dtype=bool), False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


class RecoveryEventDetector:
    """Exact original baseline plus a separately available shape classifier.

    The calibration/prediction layer decides whether there is past evidence
    supporting suppression or rescue. This class never suppresses IF alerts.
    ``score_components`` keys are ``baseline`` and ``shape``. The baseline
    retains its original15-row complete-window availability; shape can score
    when at least half the selected current channels and their causal history
    are observed. Unobserved channel features have explicit masks, not claims
    that the missing sensor is normal.
    """
    def __init__(self, config_id="shape_invariant", channels=None):
        if config_id not in CONFIGS:
            raise ValueError(f"Unknown config_id: {config_id}")
        self.config_id = config_id
        self.channels = list(CHANNELS18 if channels is None else channels)
        if not self.channels or len(self.channels) != len(set(self.channels)):
            raise ValueError("channels must be unique and nonempty")
        self.max_lookback = 60
        self.max_lookback_ = 60
        self.minimum_history_ = 30
        self.minimum_channels = int(np.ceil(len(self.channels) / 2))

    def _frame(self, frame):
        return frame.loc[:, self.channels].astype(float).replace([np.inf, -np.inf], np.nan).reset_index(drop=True)

    def _baseline_score(self, frame):
        scores = np.full(len(frame), np.nan)
        if self.baseline_ is None:
            return scores
        X, eligible, _ = build_features(frame[self.channels], "baseline15", self.channels)
        if eligible.any():
            scores[eligible] = -self.baseline_.score_samples(X[eligible])
        return scores

    def features(self, frame):
        x = self._frame(frame)
        a = x.to_numpy()
        past = x.shift(1)
        noise = x.diff().abs().shift(1).rolling(15, min_periods=7).quantile(.75).to_numpy()
        noise = np.maximum(noise, self.noise_floor_[None, :])
        centers = {}; fractions = {}; spreads = {}
        for window in (15, 60):
            rolling = past.rolling(window, min_periods=int(np.ceil(window / 2)))
            centers[window] = rolling.median().to_numpy()
            spreads[window] = (rolling.quantile(.75) - rolling.quantile(.25)).to_numpy() / 1.349
            fractions[window] = past.notna().rolling(window, min_periods=1).sum().to_numpy() / window
        current_observed = np.isfinite(a)
        channel_valid = current_observed & np.isfinite(centers[15]) & np.isfinite(centers[60]) & np.isfinite(noise)
        channel_valid &= (fractions[15] >= .5) & (fractions[60] >= .5)
        eligible = channel_valid.sum(axis=1) >= self.minimum_channels
        distance = np.abs(a - centers[60])
        parts = []
        for lag in (1, 5, 15):
            parts.append(np.abs(a - x.shift(lag).to_numpy()) / (noise * np.sqrt(lag)))
        for window in (15, 60):
            parts.append(np.abs(a - centers[window]) / np.maximum(spreads[window], self.noise_floor_[None, :]))
        for lag in (1, 5):
            parts.append(np.maximum(0., distance - np.abs(x.shift(lag).to_numpy() - centers[60])) / noise)
        parts.append(np.maximum(0., np.abs(x.shift(1).to_numpy() - centers[60]) - distance) / noise)
        parts.extend([distance / noise, np.abs(a - centers[15]) / noise,
                      spreads[15] / noise, spreads[60] / noise])
        magnitude = np.stack(parts, axis=2)
        magnitude = np.log1p(np.clip(magnitude, 0, 1e6))
        magnitude[~channel_valid] = np.nan
        # Each statistic is channel-anonymous. Explicit density features allow
        # the learner to distinguish partial evidence from observed zero change.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ordered = np.sort(np.where(np.isfinite(magnitude), magnitude, -np.inf), axis=1)
            top = ordered[:, -1, :]
            top2 = np.where(np.isfinite(ordered[:, -2:, :]), ordered[:, -2:, :], np.nan)
            pooled = [top, np.nanmean(top2, axis=1), np.nanmean(magnitude, axis=1),
                      np.nanmedian(magnitude, axis=1)]
        pooled.extend([channel_valid.mean(axis=1)[:, None], current_observed.mean(axis=1)[:, None],
                       fractions[15].mean(axis=1)[:, None], fractions[60].mean(axis=1)[:, None]])
        if CONFIGS[self.config_id]["channel_features"]:
            pooled.extend([magnitude.reshape(len(frame), -1), channel_valid.astype(float),
                           current_observed.astype(float), fractions[15], fractions[60]])
        X = np.concatenate(pooled, axis=1)
        # Fixed placeholder + explicit masks; never backfill sensor measurements.
        X = np.where(np.isfinite(X), X, 0.)
        return X, eligible

    def fit(self, frame, labels):
        x = self._frame(frame)
        y = np.asarray(labels)
        if y.shape != (len(x),) or y.dtype.kind not in "biu" or not np.isin(y, [0, 1]).all():
            raise ValueError("labels must be same-length Boolean/binary EVENT values")
        y = y.astype(bool)
        self.baseline_ = None; self.shape_ = None
        self.fit_rows_ = 0; self.fit_events_ = 0; self.baseline_fit_rows_ = 0
        self.fit_status_ = "insufficient_normal_training"
        baseline_X, baseline_eligible, _ = build_features(x, "baseline15", self.channels)
        normal15 = pd.Series(~y).rolling(15, min_periods=15).sum().eq(15).to_numpy()
        base_fit = baseline_eligible & normal15
        self.baseline_fit_rows_ = int(base_fit.sum())
        if base_fit.sum() >= 256:
            self.baseline_ = IsolationForest(n_estimators=200, max_samples=256,
                contamination="auto", n_jobs=1, random_state=20261016).fit(baseline_X[base_fit])
        clean = pd.Series(~y).rolling(61, min_periods=61).sum().eq(61).to_numpy()
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
        normal_scores = base_scores[(~y) & np.isfinite(base_scores)]
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

    def score_components(self, frame):
        result = {"baseline": self._baseline_score(frame), "shape": np.full(len(frame), np.nan)}
        if self.shape_ is None:
            return result
        features, eligible = self.features(frame)
        if eligible.any():
            with threadpool_limits(limits=1):
                result["shape"][eligible] = self.shape_.predict_proba(features[eligible])[:, 1]
        return result

    def score(self, frame):
        return self.score_components(frame)["shape"]
