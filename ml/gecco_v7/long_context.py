"""Fixed causal long-context supervised ranking; no alarms, thresholds or source IO.

All windows count samples (minutes only when the supplied cadence is one minute).
The feature/weight contract is fixed in this module and inspectable through
``inspection()``. A score is a classifier ranking, not calibrated water safety.
Unknown labels never train references, supervision, or negative weights. Their
measured observations may supply causal history for later known-label rows.
No label is changed, expanded, dropped from evaluation, or used at inference.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier


WINDOWS = (15, 60, 240, 1440)
LAGS = (1, 15, 60, 240, 1440)
MAX_LOOKBACK = 1440
MIN_NORMAL_LEVELS = 128
MIN_NORMAL_DELTAS = 64
MIN_NORMAL_FIT_ROWS = 128
HISTORY_WINDOW = 60
MIN_HISTORY_OBSERVED = 48
LEVEL_CLIP = 32.0
FEATURE_CLIP = 64.0
STALL_NOISE_FRACTION = 0.1
MODEL_PARAMS = dict(n_estimators=200, max_depth=14, min_samples_leaf=8,
                    max_features=0.7, n_jobs=1, random_state=20261016)


def _feature_keys():
    keys = ["reference_level_z", "absolute_reference_level_z", "near_stall_run_fraction",
            "current_observed", "reference_supported"]
    for lag in LAGS:
        keys.extend((f"difference_z_lag{lag}", f"lag_pair_observed_{lag}"))
    for window in WINDOWS:
        keys.extend(f"{name}_{window}" for name in (
            "mean_reference_z", "mean_absolute_reference_z", "std_reference_z",
            "current_minus_mean_z", "range_reference_z", "near_stall_fraction",
            "observed_fraction", "pair_observed_fraction"))
    return tuple(keys)


FEATURE_KEYS = _feature_keys()


class LongContextEventScorer:
    """fit(frame, ternary_integer_labels); score_components(frame)['long_context'].

    At least ceil(0.75*C) channels must each have a supported training reference,
    a finite current observation, and >=48 finite preceding observations in the
    60-row history. The first 60 rows are unavailable. Longer windows can be
    partial; observed fractions use the full nominal window as denominator.
    Calls use only their supplied history, never hidden training-tail context.
    Maximum lookback is 1440, so the current row plus 1440 prior rows suffice.

    Per-channel unavailable feature values become zero ONLY inside the feature
    matrix, with explicit current/lag/context/reference availability features.
    This never fills raw measurements or changes row/score availability.
    """

    def __init__(self, channels):
        self.channels = list(channels)
        if not self.channels or any(not isinstance(c, str) or not c for c in self.channels) or len(set(self.channels)) != len(self.channels):
            raise ValueError("channels must be a nonempty ordered list of unique names")
        self.minimum_channels = math.ceil(0.75 * len(self.channels))
        self.max_lookback_ = MAX_LOOKBACK
        self.max_lookback_samples = MAX_LOOKBACK
        self.history_rows = MAX_LOOKBACK + 1
        self.model_ = None
        self.fit_status_ = "not_fitted"
        self.feature_names_ = [f"{channel}::{key}" for channel in self.channels for key in FEATURE_KEYS]
        self.feature_names_ += [f"pooled_{pool}::{key}" for key in FEATURE_KEYS for pool in ("mean", "min", "max")]
        self.feature_contract_ = {
            "version": "long_context_fixed_v1", "channels": list(self.channels),
            "windows_samples": list(WINDOWS), "difference_lags_samples": list(LAGS),
            "max_lookback_samples": MAX_LOOKBACK, "required_history_rows": MAX_LOOKBACK + 1,
            "normal_reference": "Per channel median and IQR of finite known-normal training readings only.",
            "noise_reference": "q75 absolute differences with both adjacent training labels known-normal and both readings finite; no nonadjacent bridging.",
            "epsilon": "max(abs(normal median)*1e-12,1e-12)",
            "level_scale": "max(normal IQR/1.349, noise floor); noise floor=max(normal-delta q75,epsilon)",
            "reference_minimums": {"normal_readings": MIN_NORMAL_LEVELS, "adjacent_normal_deltas": MIN_NORMAL_DELTAS},
            "minimum_eligible_normal_fit_rows": MIN_NORMAL_FIT_ROWS,
            "availability": {"minimum_jointly_eligible_channels": self.minimum_channels,
                             "prior_window": HISTORY_WINDOW, "minimum_finite_prior_readings": MIN_HISTORY_OBSERVED,
                             "initial_unavailable_rows": HISTORY_WINDOW},
            "level_z_clip": [-LEVEL_CLIP, LEVEL_CLIP], "final_feature_clip": [-FEATURE_CLIP, FEATURE_CLIP],
            "rolling": "Right-aligned including current; means/std(ddof=0)/range use finite readings with min_periods=1. Fractions divide by the full nominal window, including absent prefix history.",
            "differences": "Signed raw current-minus-lag reading divided by fitted level scale, never by a future/local refit.",
            "near_stall": {"test": "finite adjacent pair and abs(delta)<=0.1*normal noise floor",
                           "run_cap_samples": MAX_LOOKBACK, "run_feature": "capped consecutive run/1440",
                           "missing_resets_run": True,
                           "window_fraction": "near-stall pairs / finite adjacent pairs in the window"},
            "pooling": "Each ordered channel is retained; finite-channel mean/min/max are also appended per feature family.",
            "feature_missingness": "Only unavailable feature entries use zero, after pooling; availability indicators remain explicit. Raw readings are never filled.",
            "unknown_labels": "Excluded from references, classifier targets and all weights; measured causal unknown history may enter features.",
            "weighting": "Normalized negative mass=0.5 uniformly over eligible known-normal rows. Positive mass=0.5: 0.25 point-balanced plus 0.25 balanced across original contiguous known-positive segments with eligible rows. No interval expansion or joining across unknown labels.",
            "fit_weight_scale": "Normalized weights multiplied by total eligible known-label rows for classifier.fit.",
            "classifier": dict(MODEL_PARAMS), "feature_count": len(self.feature_names_),
            "feature_names": list(self.feature_names_),
        }

    def _frame(self, frame):
        if not isinstance(frame, pd.DataFrame) or any(list(frame.columns).count(c) != 1 for c in self.channels):
            raise ValueError("frame must contain every configured sensor channel exactly once")
        return frame.loc[:, self.channels].astype(float).replace([np.inf, -np.inf], np.nan).reset_index(drop=True)

    def _fit_references(self, x, labels):
        values = x.to_numpy()
        n, c = values.shape
        self.normal_median_ = np.full(c, np.nan)
        self.normal_iqr_ = np.full(c, np.nan)
        self.noise_floor_ = np.full(c, np.nan)
        self.level_scale_ = np.full(c, np.nan)
        self.reference_supported_ = np.zeros(c, dtype=bool)
        self.normal_reference_counts_ = np.zeros(c, dtype=int)
        self.normal_delta_counts_ = np.zeros(c, dtype=int)
        self.positive_delta_counts_ = np.zeros(c, dtype=int)
        normal = labels == 0
        adjacent_normal = np.r_[False, normal[1:] & normal[:-1]] if n else np.zeros(0, bool)
        with np.errstate(over="ignore", invalid="ignore"):
            deltas = np.abs(x.diff().to_numpy())
        for j in range(c):
            observed = values[normal & np.isfinite(values[:, j]), j]
            change = deltas[adjacent_normal & np.isfinite(deltas[:, j]), j]
            self.normal_reference_counts_[j] = len(observed)
            self.normal_delta_counts_[j] = len(change)
            self.positive_delta_counts_[j] = int((change > 0).sum())
            if len(observed) < MIN_NORMAL_LEVELS or len(change) < MIN_NORMAL_DELTAS:
                continue
            with np.errstate(over="ignore", invalid="ignore"):
                center = float(np.median(observed))
                lower, upper = np.quantile(observed, [.25, .75])
                spread = float(upper - lower)
                epsilon = max(abs(center) * 1e-12, 1e-12)
                noise = max(float(np.quantile(change, .75)), epsilon)
                scale = max(spread / 1.349, noise)
            if not np.all(np.isfinite([center, spread, noise, scale])) or scale <= 0:
                continue
            self.normal_median_[j], self.normal_iqr_[j] = center, spread
            self.noise_floor_[j], self.level_scale_[j] = noise, scale
            self.reference_supported_[j] = True

    def features(self, frame):
        """Inspectable (float32 matrix, original-axis availability mask). No labels."""
        x = self._frame(frame)
        if not hasattr(self, "level_scale_"):
            raise RuntimeError("Call fit before inspecting fitted-reference features")
        values = x.to_numpy()
        n, c = values.shape
        finite = np.isfinite(values)
        supported = self.reference_supported_[None, :]
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            z = np.clip((values - self.normal_median_) / self.level_scale_, -LEVEL_CLIP, LEVEL_CLIP)
            delta = np.abs(x.diff().to_numpy())
        z[~finite | ~np.broadcast_to(supported, finite.shape)] = np.nan
        pair = finite & np.isfinite(x.shift(1).to_numpy()) & supported
        near = pair & np.isfinite(delta) & (delta <= STALL_NOISE_FRACTION * self.noise_floor_)
        run = np.zeros((n, c), dtype=float)
        positions = np.arange(n)
        for j in range(c):
            last_break = np.maximum.accumulate(np.where(~near[:, j], positions, -1))
            run[:, j] = np.minimum(positions - last_break, MAX_LOOKBACK) / MAX_LOOKBACK
        zframe = pd.DataFrame(z)
        matrices = {
            "reference_level_z": z, "absolute_reference_level_z": np.abs(z),
            "near_stall_run_fraction": np.where(supported, run, np.nan),
            "current_observed": finite.astype(float),
            "reference_supported": np.broadcast_to(supported, (n, c)).astype(float),
        }
        for lag in LAGS:
            past = x.shift(lag).to_numpy()
            observed_pair = finite & np.isfinite(past) & supported
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                difference = np.clip((values - past) / self.level_scale_, -FEATURE_CLIP, FEATURE_CLIP)
            matrices[f"difference_z_lag{lag}"] = np.where(observed_pair, difference, np.nan)
            matrices[f"lag_pair_observed_{lag}"] = observed_pair.astype(float)
        pair_frame = pd.DataFrame(pair.astype(float))
        near_frame = pd.DataFrame(near.astype(float))
        for window in WINDOWS:
            roll = zframe.rolling(window, min_periods=1)
            center = roll.mean().to_numpy()
            spread = (roll.max() - roll.min()).to_numpy()
            deviation = roll.std(ddof=0).to_numpy(copy=True)
            # Incremental rolling variance can retain tiny roundoff after an
            # earlier variable region leaves an exactly constant window. The
            # mathematically exact variance of a zero-range window is zero.
            deviation[spread == 0] = 0
            observed_count = pd.DataFrame((finite & supported).astype(float)).rolling(window, min_periods=1).sum().to_numpy()
            pair_count = pair_frame.rolling(window, min_periods=1).sum().to_numpy()
            near_count = near_frame.rolling(window, min_periods=1).sum().to_numpy()
            stall = np.divide(near_count, pair_count, out=np.full_like(pair_count, np.nan), where=pair_count > 0)
            matrices.update({
                f"mean_reference_z_{window}": center,
                f"mean_absolute_reference_z_{window}": zframe.abs().rolling(window, min_periods=1).mean().to_numpy(),
                f"std_reference_z_{window}": deviation,
                f"current_minus_mean_z_{window}": z - center,
                f"range_reference_z_{window}": spread,
                f"near_stall_fraction_{window}": stall,
                f"observed_fraction_{window}": observed_count / window,
                f"pair_observed_fraction_{window}": pair_count / window,
            })
        # Write directly to float32, avoiding a large float64 column_stack
        # intermediate. Pop each family after copying to release its storage.
        matrix = np.empty((n, len(self.feature_names_)), dtype=np.float32)
        families = len(FEATURE_KEYS)
        for k, key in enumerate(FEATURE_KEYS):
            value = np.clip(matrices.pop(key), -FEATURE_CLIP, FEATURE_CLIP).astype(np.float32)
            for j in range(c):
                matrix[:, j * families + k] = value[:, j]
            mask = np.isfinite(value)
            count = mask.sum(axis=1)
            mean = np.divide(np.where(mask, value, 0).sum(axis=1, dtype=np.float64), count,
                             out=np.full(n, np.nan), where=count > 0)
            low = np.min(np.where(mask, value, np.inf), axis=1)
            high = np.max(np.where(mask, value, -np.inf), axis=1)
            low[count == 0], high[count == 0] = np.nan, np.nan
            pooled = c * families + 3 * k
            matrix[:, pooled] = mean
            matrix[:, pooled + 1] = low
            matrix[:, pooled + 2] = high
        matrix[~np.isfinite(matrix)] = 0
        history = pd.DataFrame(finite.astype(float)).shift(1).rolling(
            HISTORY_WINDOW, min_periods=1).sum().to_numpy()
        eligible_channels = finite & supported & (history >= MIN_HISTORY_OBSERVED)
        available = eligible_channels.sum(axis=1) >= self.minimum_channels
        available[:min(HISTORY_WINDOW, n)] = False
        return matrix, available

    def fit(self, frame, labels):
        x = self._frame(frame)
        y = np.asarray(labels)
        if y.shape != (len(x),) or y.dtype.kind not in "biu" or not np.isin(y, [-1, 0, 1]).all():
            raise ValueError("labels must be same-length integer -1/0/1 values")
        y = y.astype(np.int8, copy=False)
        self.model_ = None
        self.fit_status_ = "insufficient_normal_reference"
        self.training_rows_ = len(x)
        self.label_counts_ = {"unknown": int((y == -1).sum()), "normal": int((y == 0).sum()),
                              "positive": int((y == 1).sum())}
        self._fit_references(x, y)
        self.training_eligible_mask_ = np.zeros(len(x), dtype=bool)
        self.training_normalized_weight_ = np.zeros(len(x), dtype=float)
        self.training_sample_weight_ = np.zeros(len(x), dtype=float)
        self.event_weight_audit_ = []
        self.fit_normal_rows_ = self.fit_positive_rows_ = self.fit_events_ = 0
        if self.reference_supported_.sum() < self.minimum_channels:
            return self
        matrix, available = self.features(x)
        eligible = available & (y >= 0)
        self.training_eligible_mask_ = eligible
        positive = eligible & (y == 1)
        negative = eligible & (y == 0)
        self.fit_normal_rows_, self.fit_positive_rows_ = int(negative.sum()), int(positive.sum())
        changes = np.diff(np.r_[False, y == 1, False].astype(np.int8))
        starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
        events = []
        for event_id, (start, end) in enumerate(zip(starts, ends), 1):
            rows = np.flatnonzero(positive[start:end]) + start
            self.event_weight_audit_.append({"event_id": event_id, "start": int(start),
                "end_exclusive": int(end), "labeled_rows": int(end - start),
                "eligible_positive_rows": len(rows), "normalized_weight_mass": 0.0})
            if len(rows):
                events.append((rows, self.event_weight_audit_[-1]))
        self.fit_events_ = len(events)
        if self.fit_normal_rows_ < MIN_NORMAL_FIT_ROWS:
            self.fit_status_ = "insufficient_normal_examples"
            return self
        if not self.fit_positive_rows_:
            self.fit_status_ = "no_event_training"
            return self
        weights = self.training_normalized_weight_
        weights[negative] = .5 / self.fit_normal_rows_
        weights[positive] = .25 / self.fit_positive_rows_
        for rows, record in events:
            weights[rows] += .25 / (self.fit_events_ * len(rows))
            record["normalized_weight_mass"] = float(weights[rows].sum())
        self.training_sample_weight_ = weights * int(eligible.sum())
        self.model_ = ExtraTreesClassifier(**MODEL_PARAMS)
        self.model_.fit(matrix[eligible], y[eligible], sample_weight=self.training_sample_weight_[eligible])
        self.fit_status_ = "fitted"
        return self

    def score_components(self, frame):
        x = self._frame(frame)
        score = np.full(len(x), np.nan, dtype=float)
        if self.model_ is None:
            return {"long_context": score}
        matrix, available = self.features(x)
        if available.any():
            positive_column = int(np.flatnonzero(self.model_.classes_ == 1)[0])
            score[available] = self.model_.predict_proba(matrix[available])[:, positive_column]
        return {"long_context": score}

    def inspection(self):
        """JSON-safe fixed contract, reference counts/values and fitted weights."""
        def finite_or_none(value):
            return float(value) if np.isfinite(value) else None
        references = []
        if hasattr(self, "normal_reference_counts_"):
            for j, channel in enumerate(self.channels):
                references.append({"channel": channel,
                    "normal_readings": int(self.normal_reference_counts_[j]),
                    "adjacent_normal_deltas": int(self.normal_delta_counts_[j]),
                    "positive_normal_deltas": int(self.positive_delta_counts_[j]),
                    "supported": bool(self.reference_supported_[j]),
                    "median": finite_or_none(self.normal_median_[j]), "iqr": finite_or_none(self.normal_iqr_[j]),
                    "noise_floor": finite_or_none(self.noise_floor_[j]), "level_scale": finite_or_none(self.level_scale_[j])})
        return {"feature_contract": self.feature_contract_, "fit_status": self.fit_status_,
                "training_rows": getattr(self, "training_rows_", 0), "references": references,
                "original_label_counts": getattr(self, "label_counts_", {}),
                "eligible_normal_rows": getattr(self, "fit_normal_rows_", 0),
                "eligible_positive_rows": getattr(self, "fit_positive_rows_", 0),
                "eligible_positive_segments": getattr(self, "fit_events_", 0),
                "positive_segment_weights": getattr(self, "event_weight_audit_", []),
                "normalized_weight_sum": float(getattr(self, "training_normalized_weight_", np.array([])).sum())}
