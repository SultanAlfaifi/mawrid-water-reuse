"""Three fixed, causal local-change rankings; no data-source access or alarms.

All durations below are SAMPLE COUNTS. On GECCO one sample is 60 seconds;
these constants do not imply the same physical duration at another cadence.
Any resampling/adapter must be declared separately before its evaluation.

Declared recipe (no search or data-dependent window choice):
* level: absolute current residual from the preceding 60-sample median,
  divided by max(preceding IQR / 1.349, learned noise floor).
* jump: max of absolute lag-1 and lag-5 changes, divided by the preceding
  15-delta q75 scale and sqrt(lag), with the same learned floor.
* sustained: max absolute signed residual sum over current + past 4/14,
  divided by sqrt(5/15). Each residual is clipped to [-8, 8] before summing.
  Opposing changes therefore cancel rather than accumulating alarm evidence.

Each recipe/channel is divided by max(its normal-training q99.5, 1), then
max-pooled only if at least ceil(channel_count / 2) channels are available.
These outputs are rankings, never confidence or water-safety probabilities.
No threshold, persistence, baseline fusion, label expansion or cooldown lives
here. Evaluation starts from the supplied frame; no state crosses calls.
The local median adapts during a long change: its eventual return can score
high too. These recipes do not claim to eliminate return tails; calibration
must assess added false-alarm duration as well as event detections.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


RECIPES = ("level", "jump", "sustained")
PAST_WINDOW = 60
MIN_PAST_OBSERVED = 30
DELTA_WINDOW = 15
MIN_DELTAS_OBSERVED = 8
JUMP_LAGS = (1, 5)
ACCUMULATION_WINDOWS = (5, 15)
RESIDUAL_CLIP = 8.0
RAW_SCORE_CLIP = 1e6
FLOOR_QUANTILE = 0.75
TAIL_QUANTILE = 0.995
MIN_NORMAL_SAMPLES = 64
MAX_LOOKBACK_SAMPLES = PAST_WINDOW + max(ACCUMULATION_WINDOWS) - 1


def _normal_windows(labels, length):
    """Mask rows whose current and preceding length-1 labels are all normal."""
    return (pd.Series(~labels).rolling(length, min_periods=length)
            .sum().eq(length).to_numpy())


class LocalChangeScorer:
    """Fit only normal training scales, then score independent causal frames.

    ``LocalChangeScorer(channels).fit(frame, labels)`` returns self.
    ``score_components(frame)`` returns three float arrays of length N.
    Non-finite sensor values are unobserved. No sensor is back/forward-filled.
    History medians need 30/60 finite observations; delta scales need 8/15.
    Accumulations need all 5 or all 15 constituent residuals observed. The
    short accumulation remains usable when only the long one is unavailable.

    Floors use only wholly EVENT-free 61-row windows. Tail fitting for level
    and jump uses that same mask; sustained uses wholly EVENT-free 75-row
    windows, covering its entire 74-sample lookback. A channel/recipe without
    64 finite normal examples is unavailable, never implicitly normal.
    """

    def __init__(self, channels):
        self.channels = list(channels)
        if not self.channels or len(set(self.channels)) != len(self.channels):
            raise ValueError("channels must be unique and nonempty")
        self.minimum_channels = (len(self.channels) + 1) // 2
        self.max_lookback = MAX_LOOKBACK_SAMPLES
        self.max_lookback_ = MAX_LOOKBACK_SAMPLES
        self.max_lookback_samples = MAX_LOOKBACK_SAMPLES
        self.minimum_history_ = MIN_PAST_OBSERVED
        self.cadence_unit_ = "samples"
        self.is_fitted_ = False

    def _frame(self, frame):
        return (frame.loc[:, self.channels].astype(float)
                .replace([np.inf, -np.inf], np.nan).reset_index(drop=True))

    def _raw_channel_components(self, x):
        a = x.to_numpy()
        prior = x.shift(1).rolling(PAST_WINDOW, min_periods=MIN_PAST_OBSERVED)
        center = prior.median().to_numpy()
        spread = (prior.quantile(.75) - prior.quantile(.25)).to_numpy() / 1.349
        residual_scale = np.maximum(spread, self.noise_floor_[None, :])
        delta_scale = (x.diff().abs().shift(1)
                       .rolling(DELTA_WINDOW, min_periods=MIN_DELTAS_OBSERVED)
                       .quantile(.75).to_numpy())
        delta_scale = np.maximum(delta_scale, self.noise_floor_[None, :])
        observed = np.isfinite(a) & np.isfinite(center) & np.isfinite(residual_scale)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            signed = np.clip((a - center) / residual_scale,
                             -RAW_SCORE_CLIP, RAW_SCORE_CLIP)
            signed[~observed] = np.nan
            level = np.abs(signed)
            jumps = [np.abs(a - x.shift(lag).to_numpy())
                     / (delta_scale * np.sqrt(lag)) for lag in JUMP_LAGS]
            # Both lag values must be observed; a missing value is not a zero.
            jump = np.clip(np.maximum.reduce(jumps), 0., RAW_SCORE_CLIP)
            jump[~observed] = np.nan

        clipped = pd.DataFrame(np.clip(signed, -RESIDUAL_CLIP, RESIDUAL_CLIP))
        accumulations = [np.abs(clipped.rolling(w, min_periods=w).sum().to_numpy())
                         / np.sqrt(w) for w in ACCUMULATION_WINDOWS]
        # A complete short window is valid evidence even if the long one is not.
        sustained = np.fmax.reduce(accumulations)
        return dict(level=level, jump=jump, sustained=sustained)

    def fit(self, frame, labels):
        self.is_fitted_ = False
        x = self._frame(frame)
        y = np.asarray(labels)
        if (y.shape != (len(x),) or y.dtype.kind not in "biu"
                or not np.isin(y, [0, 1]).all()):
            raise ValueError("labels must be same-length Boolean/binary EVENT values")
        y = y.astype(bool)
        clean61 = _normal_windows(y, PAST_WINDOW + 1)
        clean75 = _normal_windows(y, MAX_LOOKBACK_SAMPLES + 1)
        self.normal_floor_window_mask_ = clean61
        self.normal_tail_window_masks_ = dict(level=clean61.copy(), jump=clean61.copy(),
                                             sustained=clean75)
        a = x.to_numpy()
        delta = x.diff().abs().to_numpy()
        self.noise_floor_ = np.full(len(self.channels), np.nan)
        self.floor_fit_counts_ = np.zeros(len(self.channels), dtype=int)
        for j in range(len(self.channels)):
            values = delta[clean61, j]
            values = values[np.isfinite(values)]
            self.floor_fit_counts_[j] = len(values)
            if len(values) < MIN_NORMAL_SAMPLES:
                continue
            positive = values[values > 0]
            finite = a[clean61, j]
            finite = finite[np.isfinite(finite)]
            # Floating-point floor for a perfectly constant/quantized channel.
            # For varying channels the empirical positive-delta floor dominates.
            epsilon = max(float(np.median(np.abs(finite))) * 1e-12, 1e-12)
            empirical = float(np.quantile(positive, FLOOR_QUANTILE)) if len(positive) else 0.
            self.noise_floor_[j] = max(empirical, epsilon)

        raw = self._raw_channel_components(x)
        self.channel_tail_scales_ = {}
        self.tail_fit_counts_ = {}
        for recipe in RECIPES:
            scales = np.full(len(self.channels), np.nan)
            counts = np.zeros(len(self.channels), dtype=int)
            for j in range(len(self.channels)):
                values = raw[recipe][self.normal_tail_window_masks_[recipe], j]
                values = values[np.isfinite(values)]
                counts[j] = len(values)
                if len(values) >= MIN_NORMAL_SAMPLES:
                    scales[j] = max(float(np.quantile(values, TAIL_QUANTILE)), 1.)
            self.channel_tail_scales_[recipe] = scales
            self.tail_fit_counts_[recipe] = counts
        self.fit_rows_ = int(clean61.sum())
        trained_counts = [int(np.isfinite(self.channel_tail_scales_[r]).sum()) for r in RECIPES]
        self.fit_status_ = ("fitted" if min(trained_counts) >= self.minimum_channels
                            else "insufficient_normal_training")
        self.is_fitted_ = True
        return self

    def score_components(self, frame):
        if not self.is_fitted_:
            raise RuntimeError("fit must be called before score_components")
        raw = self._raw_channel_components(self._frame(frame))
        result = {}
        for recipe in RECIPES:
            normalized = raw[recipe] / self.channel_tail_scales_[recipe][None, :]
            observed = np.isfinite(normalized)
            enough = observed.sum(axis=1) >= self.minimum_channels
            scores = np.max(np.where(observed, normalized, -np.inf), axis=1)
            scores[~enough] = np.nan
            result[recipe] = scores
        return result
