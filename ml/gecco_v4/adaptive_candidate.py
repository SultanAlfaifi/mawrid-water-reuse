"""Symmetric causal changes, fitted on normal training windows only.

Scores are dimensionless anomaly rankings, not probabilities or water-safety
decisions. All GECCO2018/2019 development data have already been disclosed.
This module never loads data and never reads EVENT from a scoring frame.
"""
from __future__ import annotations

import warnings
import numpy as np
import pandas as pd

CHANNELS18 = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
CHANNELS19 = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
CONFIGS = {
    "symmetric_local30": {"windows": (30,), "aggregate": "max"},
    "symmetric_multiscale180": {"windows": (30, 180), "aggregate": "max"},
    "symmetric_top2_180": {"windows": (30, 180), "aggregate": "top2"},
    "symmetric_return_gated180": {"windows": (30, 180), "aggregate": "max", "return_gate": True},
    "return_gated_channel_median5": {"windows": (30, 180), "aggregate": "max", "return_gate": True, "smooth_channels": 5},
    "anchored_long720": {"windows": (720,), "aggregate": "max", "return_gate": True,
                         "anchor_window": 720, "long_residual_only": True},
}


class AdaptiveChangeDetector:
    """Magnitude changes around the channel's own trailing operating point.

    fit(frame, labels) receives the original Boolean EVENT labels. Any training
    window touching an EVENT is excluded from noise and tail-scale fitting.
    score(frame) receives values only; unrelated columns including EVENT are
    ignored. The caller resets state by passing a fresh partition. No future
    smoothing, imputation, cooldown, event expansion, or label-aware scoring.

    A current observation in every selected channel is required. Trailing
    windows need at least 50% actual observations. A missing past measurement
    therefore does not force 180 minutes of unavailability. Long windows remain
    unavailable until their initial minimum history has accumulated.
    """
    def __init__(self, config_id="symmetric_multiscale180", channels=None):
        if config_id not in CONFIGS:
            raise ValueError(f"Unknown configuration: {config_id}")
        self.config_id = config_id
        self.channels = list(CHANNELS18 if channels is None else channels)
        if not self.channels or len(set(self.channels)) != len(self.channels):
            raise ValueError("channels must be unique and nonempty")
        self.config = dict(CONFIGS[config_id])
        self.max_lookback_ = max(31, max(self.config["windows"])) + self.config.get("smooth_channels", 1) - 1
        self.minimum_history_ = max(16, max(self.config["windows"]) // 2) + self.config.get("smooth_channels", 1) - 1

    def _frame(self, frame):
        return frame.loc[:, self.channels].astype(float).replace(
            [np.inf, -np.inf], np.nan).reset_index(drop=True)

    def _features(self, x):
        # delta(t-1) reads t-2; 30 trailing deltas thus use 31 predecessors.
        noise = x.diff().abs().shift(1).rolling(30, min_periods=15).quantile(.75)
        denominator = np.maximum(noise.to_numpy(), self.noise_floor_[None, :])
        if self.config.get("return_gate"):
            short = x.shift(1).rolling(30, min_periods=15).median()
            anchor_window = self.config.get("anchor_window", 180)
            anchor = x.shift(1).rolling(anchor_window, min_periods=anchor_window // 2).median()
            distance = (x - anchor).abs()
            # Compare current and previous values to the SAME past anchor.
            # A move closer to the reference contributes no outward-change
            # evidence. This is a measurement feature, never a cooldown.
            parts = [np.maximum(0., distance.to_numpy() -
                        (x.shift(lag) - anchor).abs().to_numpy()) / denominator
                     for lag in (1, 5, 15)]
            residual = distance.to_numpy() if self.config.get("long_residual_only") else np.minimum(
                (x - short).abs().to_numpy(), distance.to_numpy())
            parts.append(residual / denominator)
            required = np.isfinite(x.to_numpy()).all(axis=1)
            required &= np.isfinite(anchor.to_numpy()).all(axis=1)
            required &= np.isfinite(short.to_numpy()).all(axis=1)
            required &= np.isfinite(denominator).all(axis=1)
            return np.stack(parts, axis=2), required
        parts = [x.diff().abs().to_numpy() / denominator]
        required = np.isfinite(x.to_numpy()).all(axis=1)
        for window in self.config["windows"]:
            center = x.shift(1).rolling(window, min_periods=window // 2).median()
            residual = (x - center).abs().to_numpy() / denominator
            parts.append(residual)
            required &= np.isfinite(residual).all(axis=1)
        values = np.stack(parts, axis=2)
        # Missing immediately preceding measurement invalidates the delta only;
        # observed current values can still be compared with a valid past center.
        return values, required

    def fit(self, frame, labels):
        x = self._frame(frame)
        y = np.asarray(labels)
        if y.shape != (len(x),) or y.dtype.kind not in "biu" or not np.isin(y, [0, 1]).all():
            raise ValueError("labels must be a same-length Boolean/binary EVENT vector")
        clean = pd.Series(~y.astype(bool)).rolling(
            self.max_lookback_ + 1, min_periods=self.max_lookback_ + 1
        ).sum().eq(self.max_lookback_ + 1).to_numpy()
        if clean.sum() < 100:
            raise ValueError("At least 100 uncontaminated normal training windows required")
        delta = x.diff().abs().to_numpy()
        floors = []
        for channel in range(len(self.channels)):
            good = delta[clean, channel]
            positive = good[np.isfinite(good) & (good > 0)]
            # Positive quantum floor prevents division by zero on quantized
            # channels. Median level only supplies floating-point epsilon.
            observed = x.to_numpy()[clean, channel]
            epsilon = max(float(np.nanmedian(np.abs(observed))) * 1e-12, 1e-12)
            floors.append(max(float(np.quantile(positive, .75)) if positive.size else 0., epsilon))
        self.noise_floor_ = np.asarray(floors)
        features, eligible = self._features(x)
        eligible &= clean
        if eligible.sum() < 100:
            raise ValueError("Fewer than 100 eligible normal training windows")
        # Each channel/component contributes on its own normal-tail scale.
        # This prevents a naturally noisy channel dominating the channel max.
        tail = np.nanquantile(features[eligible], .995, axis=0)
        self.tail_scale_ = np.maximum(np.where(np.isfinite(tail), tail, 0.), 1.)
        self.fit_rows_ = int(eligible.sum())
        self.fit_normal_window_mask_ = eligible
        return self

    def score_channels(self, frame):
        if not hasattr(self, "tail_scale_"):
            raise RuntimeError("fit must precede score")
        values, eligible = self._features(self._frame(frame))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = np.nanmax(values / self.tail_scale_[None, :, :], axis=2)
        result[~eligible] = np.nan
        if self.config.get("smooth_channels"):
            window = self.config["smooth_channels"]
            result = pd.DataFrame(result).rolling(window, min_periods=window).median().to_numpy()
        return result

    def score(self, frame):
        contributions = self.score_channels(frame)
        eligible = np.isfinite(contributions).all(axis=1)
        output = np.full(len(frame), np.nan)
        if self.config["aggregate"] == "max":
            output[eligible] = contributions[eligible].max(axis=1)
        else:
            largest = np.sort(contributions[eligible], axis=1)[:, -min(2, len(self.channels)):]
            output[eligible] = largest.mean(axis=1)
        return output
