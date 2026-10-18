"""Past-training normal support; False means unknown, never proof of normality.

The caller supplies causal, relative shape features (the V5 invariant matrix
has52 columns). This module never reads a source, EVENT during scoring, or an
outer calibration/test label. A fixed fit scores each query independently.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import numpy as np


@dataclass(frozen=True)
class SupportConfig:
    expected_features: int = 52
    prototype_fraction: float = .8
    max_prototypes: int = 1024
    reference_quantile: float = .95
    minimum_prototype_rows: int = 128
    minimum_reference_rows: int = 64
    normal_history_samples: int = 60
    absolute_scale_floor: float = 1e-6
    relative_scale_floor: float = 1e-3
    query_batch_size: int = 256


def _mask(values, n, name):
    a = np.asarray(values)
    if a.shape != (n,) or a.dtype.kind not in "biu" or not np.isin(a, [0, 1]).all():
        raise ValueError(f"{name} must be a same-length Boolean/binary integer mask")
    return a.astype(bool, copy=False)


class NormalSupportGate:
    """Robust nearest-prototype distance on explicitly normal past windows.

    normal_labels=True means normal (~EVENT). The original acquisition-row
    order defines the80/20 split. Median/IQR scaling and deterministic evenly
    spaced prototypes use only the first80%. A distance threshold uses only
    known-normal eligible rows in the last20%. Every fitted row additionally
    requires current and prior60 labels to be normal. Unavailable/unsupported
    query rows return False; the downstream gate must retain its IF baseline.

    A True result means inside the learned normal-support envelope; it is not
    a safety classification, event-type guarantee, or calibrated probability.
    """
    def __init__(self, config=None):
        self.config = SupportConfig() if config is None else config
        if not isinstance(self.config, SupportConfig):
            raise TypeError("config must be SupportConfig")
        c = self.config
        integers = (c.expected_features, c.max_prototypes, c.minimum_prototype_rows,
                    c.minimum_reference_rows, c.query_batch_size)
        if any(not isinstance(v, (int, np.integer)) or isinstance(v, bool) or v < 1 for v in integers):
            raise ValueError("Feature, prototype, exposure and batch counts must be positive integers")
        if not isinstance(c.normal_history_samples, (int, np.integer)) or isinstance(c.normal_history_samples, bool) or c.normal_history_samples < 0:
            raise ValueError("normal_history_samples must be a nonnegative integer")
        if not 0 < c.prototype_fraction < 1 or not 0 < c.reference_quantile < 1:
            raise ValueError("Split fraction and reference quantile must lie strictly between0and1")
        if not np.isfinite(c.absolute_scale_floor) or c.absolute_scale_floor <= 0 or not np.isfinite(c.relative_scale_floor) or c.relative_scale_floor < 0:
            raise ValueError("Scale floors must be finite and nonnegative, with positive absolute floor")

    def _matrix(self, values):
        x = np.asarray(values, dtype=float)
        if x.ndim != 2 or x.shape[1] != self.config.expected_features:
            raise ValueError(f"Expected a2D matrix with {self.config.expected_features} feature columns")
        return x

    def fit(self, feature_matrix, normal_labels, pasteligible):
        x = self._matrix(feature_matrix)
        n = len(x); c = self.config
        normal = _mask(normal_labels, n, "normal_labels")
        eligible = _mask(pasteligible, n, "pasteligible")
        self.split_index_ = int(np.floor(n * c.prototype_fraction))
        self.threshold_ = None
        self.fit_status_ = "unfitted"
        self.center_ = None; self.scale_ = None; self.prototypes_ = None
        self.prototype_source_indices_ = np.empty(0, dtype=int)
        self.scaler_source_indices_ = np.empty(0, dtype=int)
        self.reference_source_indices_ = np.empty(0, dtype=int)
        # The cumulative count excludes an EVENT anywhere in the full causal
        # feature window. No shortening of the original acquisition axis.
        width = c.normal_history_samples + 1
        clean = np.zeros(n, dtype=bool)
        if n >= width:
            counts = np.r_[0, np.cumsum(normal, dtype=np.int64)]
            clean[width - 1:] = (counts[width:] - counts[:-width]) == width
        observed = np.isfinite(x).all(axis=1)
        accepted = clean & eligible & observed
        axis = np.arange(n)
        first = np.flatnonzero(accepted & (axis < self.split_index_))
        last = np.flatnonzero(accepted & (axis >= self.split_index_))
        self.clean_normal_window_mask_ = clean
        self.diagnostics_ = {
            "config": asdict(c), "training_rows": n, "split_index": self.split_index_,
            "normal_label_rows": int(normal.sum()), "clean_normal_window_rows": int(clean.sum()),
            "eligible_complete_normal_rows": int(accepted.sum()),
            "first_prefix_normal_rows": len(first), "last_suffix_reference_rows": len(last),
            "normal_rows_rejected_missing_features": int((normal & ~observed).sum()),
            "geometry": "Original training acquisition-row80/20 split; clean current+60past normal windows; robust scaler/prototypes first prefix only; distance quantile last suffix only",
            "unknown_policy": "False support retains the original baseline prediction",
            "score_meaning": "Known-normal feature-envelope membership, not a normal/safe posterior probability",
        }
        if not normal.any():
            self.fit_status_ = "no_normal_training"
        elif len(first) < c.minimum_prototype_rows:
            self.fit_status_ = "insufficient_prototype_normal_rows"
        elif len(last) < c.minimum_reference_rows:
            self.fit_status_ = "insufficient_reference_normal_rows"
        else:
            fit_values = x[first]
            self.center_ = np.median(fit_values, axis=0)
            q25, q75 = np.quantile(fit_values, [.25, .75], axis=0)
            floor = np.maximum(c.absolute_scale_floor, np.median(np.abs(fit_values), axis=0) * c.relative_scale_floor)
            self.scale_ = np.maximum(q75 - q25, floor)
            positions = np.linspace(0, len(first) - 1, min(c.max_prototypes, len(first)), dtype=int)
            self.scaler_source_indices_ = first.copy()
            self.prototype_source_indices_ = first[positions].copy()
            self.reference_source_indices_ = last.copy()
            self.prototypes_ = (x[self.prototype_source_indices_] - self.center_) / self.scale_
            reference = self._distance(x[last])
            if not np.isfinite(reference).all():
                self.fit_status_ = "nonfinite_reference_distance"
            else:
                self.threshold_ = float(np.quantile(reference, c.reference_quantile))
                self.fit_status_ = "fitted"
                self.diagnostics_.update({
                    "prototype_count": len(self.prototypes_),
                    "reference_distance_min": float(reference.min()),
                    "reference_distance_median": float(np.median(reference)),
                    "reference_distance_max": float(reference.max()),
                    "reference_empirical_support_fraction": float(np.mean(reference <= self.threshold_)),
                })
        self.diagnostics_.update({"status": self.fit_status_, "threshold": self.threshold_})
        return self

    def _distance(self, x):
        """Nearest RMS standardized Euclidean distance, without clipping."""
        out = np.full(len(x), np.inf)
        complete = np.flatnonzero(np.isfinite(x).all(axis=1))
        p = self.prototypes_
        for start in range(0, len(complete), self.config.query_batch_size):
            index = complete[start:start + self.config.query_batch_size]
            with np.errstate(over="ignore", invalid="ignore"):
                z = (x[index] - self.center_) / self.scale_
                # Direct subtraction avoids catastrophic cancellation near a
                # prototype. Batch size bounds memory even for extreme queries.
                squared = np.sum((z[:, None, :] - p[None, :, :]) ** 2, axis=2)
                d = np.sqrt(np.min(squared, axis=1) / self.config.expected_features)
            out[index] = np.where(np.isfinite(d), d, np.inf)
        return out

    def distance(self, feature_matrix):
        x = self._matrix(feature_matrix)
        if not hasattr(self, "fit_status_"):
            raise RuntimeError("fit must precede distance/score_support")
        if self.fit_status_ != "fitted":
            return np.full(len(x), np.inf)
        return self._distance(x)

    def score_support(self, feature_matrix):
        distances = self.distance(feature_matrix)
        if self.fit_status_ != "fitted":
            return np.zeros(len(distances), dtype=bool)
        return np.isfinite(distances) & (distances <= self.threshold_)
