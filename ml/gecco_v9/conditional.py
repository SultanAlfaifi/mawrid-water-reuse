"""Append fixed normal-only cross-sensor residuals to the frozen V8 scorer.

Ridge parameters, channel order and fitting populations are fixed before data
access. All original V8 features, row availability, onset weights and HGB
parameters remain intact. This is an extra representation, not an alarm gate,
missing-value imputation, safety estimate, or demonstrated performance gain.
"""
from __future__ import annotations

from copy import copy
import hashlib

import numpy as np
from sklearn.linear_model import Ridge

from ml.gecco_v8.onset import OnsetWeightedHGBScorer


RIDGE_PARAMS = {"alpha": 1.0, "fit_intercept": True, "solver": "svd"}
MIN_COMPLETE_NORMAL_ROWS = 128
CONDITIONAL_CLIP = 64.0
MIN_RESIDUAL_SCALE = 1e-6
ADDED_KEYS = ("conditional_residual_z", "absolute_conditional_residual_z", "conditional_residual_observed")
REFERENCE_ATTRIBUTES = ("normal_median_", "normal_iqr_", "noise_floor_", "level_scale_", "reference_supported_")


def _array_hash(values):
    values = np.ascontiguousarray(values)
    digest = hashlib.sha256()
    digest.update(str(values.shape).encode())
    digest.update(values.dtype.str.encode())
    digest.update(values.tobytes())
    return digest.hexdigest()


class ConditionalResidualHGBScorer(OnsetWeightedHGBScorer):
    """Inherited fit/scoring API plus conditional_features(frame)->float32[n,3*C].

Each channel contributes signed residual, absolute residual and observed mask,
in configured channel order. Mask columns are 2::3. A complete current row
supports all added residuals together; an unavailable dependency disables the
whole added row block without changing the original V8 score availability.
"""

    def __init__(self, channels):
        super().__init__(channels)
        self.original_feature_names_ = list(self.feature_names_)
        self.conditional_feature_names_ = [f"{channel}::{key}" for channel in self.channels for key in ADDED_KEYS]
        self.feature_names_ = self.original_feature_names_ + self.conditional_feature_names_
        self.feature_contract_["version"] = "long_context_hgb_onset_conditional_ridge_v1"
        self.feature_contract_["feature_count"] = len(self.feature_names_)
        self.feature_contract_["feature_names"] = list(self.feature_names_)
        self.feature_contract_["conditional_residuals"] = {
            "ridge": dict(RIDGE_PARAMS), "objective": "sum squared residuals + alpha * sum squared coefficients; intercept unpenalized",
            "minimum_complete_normal_rows": MIN_COMPLETE_NORMAL_ROWS,
            "minimum_channels": 2, "all_original_references_required": True,
            "fitting_population": "All original training rows with label exactly 0 and every raw and standardized channel finite. No availability-history restriction and no subset search.",
            "standardization": "(raw-current - original V8 normal median) / original V8 level scale, without clipping",
            "predictors": "All other configured channels at the same current row, in their original order",
            "residual_scale": "max(q75(abs(in-sample known-normal residual)), original noise_floor/level_scale, 1e-6)",
            "added_feature_order": list(self.conditional_feature_names_),
            "observed_mask_columns": list(range(2, 3 * len(self.channels), 3)),
            "clip": [-CONDITIONAL_CLIP, CONDITIONAL_CLIP],
            "missingness": "No raw imputation. Any missing, unsupported, nonfinite standardized input or nonfinite added calculation makes the whole added row block zeros with observed masks 0.",
            "numerical_fit_failure": "Any target's numerical fitting failure or nonfinite coefficients/intercept/scale disables the entire added block; no alternate sensors, clipping or tuning.",
            "original_availability": "Unchanged V8 availability; added residual availability is only an input feature",
            "causality": "Current aligned measurements only, conditional on frozen whole-training normal references and ridge fits; no online refit",
        }
        self._reset_conditional(0)

    def _reset_conditional(self, rows):
        channels = len(self.channels)
        self.conditional_predictor_indices_ = np.array([[k for k in range(channels) if k != j]
                                                       for j in range(channels)], dtype=np.int64).reshape(channels, channels - 1)
        self.conditional_fit_mask_ = np.zeros(rows, bool)
        self.conditional_complete_normal_mask_ = np.zeros(rows, bool)
        self.conditional_coef_ = np.full((channels, channels - 1), np.nan)
        self.conditional_intercept_ = np.full(channels, np.nan)
        self.conditional_residual_scale_ = np.full(channels, np.nan)
        self.conditional_supported_ = False
        self.conditional_fit_status_ = "not_fitted"
        self.conditional_failure_reason_ = None
        self.conditional_original_reference_hashes_ = {}

    def _standardized(self, x):
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            values = x.to_numpy(dtype=float)
            standardized = (values - self.normal_median_) / self.level_scale_
        complete = np.isfinite(values).all(axis=1) & np.isfinite(standardized).all(axis=1)
        return standardized, complete

    def _fit_references(self, x, labels):
        # The inherited V8 fit invokes this before feature construction. Keeping
        # its fit method unchanged also preserves the exact onset weights/HGB.
        super()._fit_references(x, labels)
        self._reset_conditional(len(x))
        self.conditional_original_reference_hashes_ = {
            name: _array_hash(getattr(self, name)) for name in REFERENCE_ATTRIBUTES}
        if len(self.channels) < 2:
            self.conditional_fit_status_ = "insufficient_channels"
            return
        if not self.reference_supported_.all():
            self.conditional_fit_status_ = "unsupported_original_reference"
            return
        standardized, complete = self._standardized(x)
        normal_complete = complete & (np.asarray(labels) == 0)
        self.conditional_complete_normal_mask_ = normal_complete
        if normal_complete.sum() < MIN_COMPLETE_NORMAL_ROWS:
            self.conditional_fit_status_ = "insufficient_complete_normal_rows"
            return
        # This is the actual attempted fitting population. It remains inspectable
        # if a numerical failure disables the whole block.
        self.conditional_fit_mask_ = normal_complete.copy()
        z = standardized[normal_complete]
        coefficients = np.empty_like(self.conditional_coef_)
        intercepts = np.empty_like(self.conditional_intercept_)
        scales = np.empty_like(self.conditional_residual_scale_)
        for target, predictors in enumerate(self.conditional_predictor_indices_):
            try:
                with np.errstate(over="raise", invalid="raise", divide="raise"):
                    ridge = Ridge(**RIDGE_PARAMS).fit(z[:, predictors], z[:, target])
                    coefficients[target] = ridge.coef_
                    intercepts[target] = ridge.intercept_
                    residual = z[:, target] - ridge.predict(z[:, predictors])
                    scale = max(float(np.quantile(np.abs(residual), .75)),
                                float(self.noise_floor_[target] / self.level_scale_[target]), MIN_RESIDUAL_SCALE)
                if (not np.isfinite(coefficients[target]).all() or not np.isfinite(intercepts[target])
                        or not np.isfinite(residual).all() or not np.isfinite(scale) or scale <= 0):
                    self.conditional_fit_status_ = "numerical_fit_failure"
                    self.conditional_failure_reason_ = {"target": self.channels[target], "reason": "nonfinite_fitted_parameter_or_residual"}
                    return
                scales[target] = scale
            except (FloatingPointError, np.linalg.LinAlgError) as error:
                self.conditional_fit_status_ = "numerical_fit_failure"
                self.conditional_failure_reason_ = {"target": self.channels[target], "reason": type(error).__name__}
                return
            except ValueError as error:
                # sklearn/scipy can reject overflow-created internal matrices.
                # Shape/parameter/programming ValueErrors must still surface.
                message = str(error).lower()
                if not any(token in message for token in ("infs or nans", "infinity", "too large", "input contains nan", "array must not contain")):
                    raise
                self.conditional_fit_status_ = "numerical_fit_failure"
                self.conditional_failure_reason_ = {"target": self.channels[target], "reason": "nonfinite_internal_matrix"}
                return
        self.conditional_coef_ = coefficients
        self.conditional_intercept_ = intercepts
        self.conditional_residual_scale_ = scales
        self.conditional_supported_ = True
        self.conditional_fit_status_ = "fitted"

    def conditional_features(self, frame):
        """Current-only added block; never refits, mutates state or changes rows."""
        x = self._frame(frame)
        added = np.zeros((len(x), 3 * len(self.channels)), np.float32)
        if not self.conditional_supported_ or not len(x):
            return added
        standardized, complete = self._standardized(x)
        indices = np.flatnonzero(complete)
        if not len(indices):
            return added
        z = standardized[indices]
        residual = np.empty_like(z)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            for target, predictors in enumerate(self.conditional_predictor_indices_):
                residual[:, target] = (z[:, target] - (z[:, predictors] @ self.conditional_coef_[target]
                    + self.conditional_intercept_[target])) / self.conditional_residual_scale_[target]
        finite = np.isfinite(residual).all(axis=1)
        indices = indices[finite]
        clipped = np.clip(residual[finite], -CONDITIONAL_CLIP, CONDITIONAL_CLIP).astype(np.float32)
        added[indices, 0::3] = clipped
        added[indices, 1::3] = np.abs(clipped)
        added[indices, 2::3] = 1
        return added

    def conditional_observed(self, frame):
        return (self.conditional_features(frame)[:, 2::3] == 1).all(axis=1)

    def features(self, frame):
        # The frozen implementation allocates by len(self.feature_names_).
        # A shallow view restores the original width without mutating self or
        # allocating/copying fitted arrays, then appends the independent block.
        original_view = copy(self)
        original_view.feature_names_ = self.original_feature_names_
        matrix, available = super(ConditionalResidualHGBScorer, original_view).features(frame)
        return np.concatenate((matrix, self.conditional_features(frame)), axis=1), available

    def inspection(self):
        result = super().inspection()
        def finite_list(values):
            return [float(value) if np.isfinite(value) else None for value in values]
        result["conditional_residuals"] = {
            "supported": bool(self.conditional_supported_), "fit_status": self.conditional_fit_status_,
            "failure_reason": self.conditional_failure_reason_, "channel_order": list(self.channels),
            "ridge_parameters": dict(RIDGE_PARAMS), "training_rows": len(self.conditional_fit_mask_),
            "complete_normal_rows": int(self.conditional_complete_normal_mask_.sum()),
            "attempted_fit_rows": int(self.conditional_fit_mask_.sum()),
            "fit_mask_sha256": _array_hash(self.conditional_fit_mask_),
            "fit_mask_coordinate_system": "Original positional training row indices; full boolean mask stored in fitted model",
            "original_reference_hashes": dict(self.conditional_original_reference_hashes_),
            "original_feature_count": len(self.original_feature_names_), "added_feature_names": list(self.conditional_feature_names_),
            "targets": [{"target": channel, "predictor_channels": [self.channels[k] for k in predictors],
                         "predictor_indices": predictors.tolist(), "coefficients": finite_list(self.conditional_coef_[j]),
                         "intercept": finite_list([self.conditional_intercept_[j]])[0],
                         "residual_scale": finite_list([self.conditional_residual_scale_[j]])[0],
                         "supported": bool(self.conditional_supported_)}
                        for j, (channel, predictors) in enumerate(zip(self.channels, self.conditional_predictor_indices_))],
        }
        return result
