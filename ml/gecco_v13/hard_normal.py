"""V13 changes only eligible-normal HGB training weights; no source IO.

The q95 population is ALL finite frozen-IF scores on known-normal training rows,
including rows unavailable to HGB. The fitted IF is never refitted here. This is
an in-sample representation, not independent validation or a safety probability.
Original V12 features, positive/onset weights, availability and scoring remain.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from ml.gecco_v7.long_context import MIN_NORMAL_FIT_ROWS
from ml.gecco_v7.long_context_hgb import HGB_PARAMS
from ml.gecco_v8.onset import (ONSET_WINDOW_SAMPLES, NEGATIVE_MASS,
    POSITIVE_POINT_MASS, POSITIVE_EVENT_MASS, POSITIVE_ONSET_MASS)
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer, baseline_state_digest

HARD_NORMAL_QUANTILE = .95
HARD_NORMAL_RATIO = 5.0


def _mask_sha256(mask):
    """SHA256 of original-axis C-contiguous NumPy bool bytes (one byte/row)."""
    return hashlib.sha256(np.ascontiguousarray(mask, dtype=np.bool_).tobytes()).hexdigest()


class HardNormalTailHGBScorer(BaselineEvidenceHGBScorer):
    """Same constructor/scoring as V12; one HGB fit with a fixed normal-tail mass."""
    def __init__(self, channels, baseline_estimator):
        super().__init__(channels, baseline_estimator)
        self.feature_contract_["version"] = "long_context_hgb_onset_conditional_frozen_if_hard_normal_v1"
        self.feature_contract_["weighting"] = (
            "Same V8 positive point/event/onset masses and eligibility. Eligible known-normal "
            "mass=0.5, proportional to 1+4*(finite raw IF score >= train-normal q95). "
            "q95 uses all finite known-normal training raw IF scores, not only HGB-eligible rows. "
            "Unknown labels have zero supervised weight. Missing IF evidence receives base weight1; "
            "no finite known-normal IF scores gives uniform normal weights. No IF refit.")
        self.feature_contract_["hard_normal_weighting"] = {
            "quantile": HARD_NORMAL_QUANTILE, "quantile_method": "linear",
            "quantile_population": "ALL original training rows where label==0 and raw float64 IF score is finite",
            "weight_population": "Unchanged HGB-eligible training rows where label==0",
            "tail_comparison": ">=", "tail_to_other_relative_weight": HARD_NORMAL_RATIO,
            "normal_mass": NEGATIVE_MASS,
            "formula": "0.5 * (1 + 4*tail) / sum_over_eligible_normals(1 + 4*tail)",
            "missing_row_score": "Base relative weight1; never discard an otherwise eligible row",
            "unavailable_if": "Uniform normal mass0.5 if HGB fit is otherwise possible",
            "positive_weights": "Exactly inherited V8 point/event/known-onset recipe",
            "features_and_availability": "Exactly V12, including current frozen-IF evidence features",
            "if_fit": False, "in_sample_not_cross_fitted": True,
            "mask_encoding": "SHA256 of C-contiguous np.bool_ bytes on original training axis",
        }
        # The inherited IF feature contract referred to V12's weights. Clarify
        # the only V13 difference without changing feature construction.
        self.feature_contract_["original_if_evidence"]["original_availability"] = (
            "V9 availability and fit population unchanged; only V13 eligible-normal training weights change.")

    def _prepare_hard_normal(self, frame, y):
        self.hard_normal_if_state_before_ = baseline_state_digest(self.baseline_estimator_)
        raw = np.asarray(self.baseline_raw_scores(frame), dtype=np.float64)
        if raw.shape != (len(frame),):
            raise ValueError("Frozen IF training score shape mismatch")
        self.hard_normal_raw_scores_ = raw.copy()
        self.hard_normal_quantile_mask_ = (y == 0) & np.isfinite(raw)
        self.hard_normal_q95_ = (float(np.quantile(raw[self.hard_normal_quantile_mask_],
            HARD_NORMAL_QUANTILE, method="linear")) if self.hard_normal_quantile_mask_.any() else None)
        self.hard_normal_quantile_status_ = ("available" if self.hard_normal_q95_ is not None else
            "missing_estimator" if self.baseline_estimator_ is None else "no_finite_known_normal_scores")
        self.hard_normal_eligible_normal_mask_ = np.zeros(len(y), dtype=bool)
        self.hard_normal_tail_mask_ = np.zeros(len(y), dtype=bool)
        self.hard_normal_status_ = "not_applied"

    def _apply_hard_normal_weights(self, negative, weights):
        self.hard_normal_eligible_normal_mask_ = negative.copy()
        if self.hard_normal_q95_ is None:
            weights[negative] = NEGATIVE_MASS / int(negative.sum())
            self.hard_normal_status_ = "uniform_fallback"
            return
        self.hard_normal_tail_mask_ = negative & np.isfinite(self.hard_normal_raw_scores_) & (
            self.hard_normal_raw_scores_ >= self.hard_normal_q95_)
        relative = 1.0 + (HARD_NORMAL_RATIO - 1.0) * self.hard_normal_tail_mask_[negative]
        weights[negative] = NEGATIVE_MASS * relative / relative.sum()
        self.hard_normal_status_ = "tail_weighted"

    def _finalize_hard_normal(self, y):
        normal = self.training_eligible_mask_ & (y == 0)
        self.hard_normal_eligible_normal_mask_ = normal.copy()
        self.hard_normal_tail_mask_ = (normal & np.isfinite(self.hard_normal_raw_scores_) &
            (self.hard_normal_raw_scores_ >= self.hard_normal_q95_)) if self.hard_normal_q95_ is not None else np.zeros(len(y), bool)
        if self.fit_status_ != "fitted":
            self.hard_normal_status_ = "not_applied_" + self.fit_status_
        after = baseline_state_digest(self.baseline_estimator_)
        if after != self.hard_normal_if_state_before_:
            raise AssertionError("Frozen IF state mutated during HGB fitting")
        weights = self.training_normalized_weight_
        self.hard_normal_audit_ = {
            "status": self.hard_normal_status_, "quantile_status": self.hard_normal_quantile_status_,
            "q95": self.hard_normal_q95_, "quantile": HARD_NORMAL_QUANTILE,
            "quantile_method": "linear", "tail_comparison": ">=", "tail_relative_weight": HARD_NORMAL_RATIO,
            "training_rows": len(y), "quantile_population_rows": int(self.hard_normal_quantile_mask_.sum()),
            "quantile_population_hgb_ineligible_rows": int((self.hard_normal_quantile_mask_ & ~self.training_eligible_mask_).sum()),
            "eligible_normal_rows": int(normal.sum()), "eligible_tail_rows": int(self.hard_normal_tail_mask_.sum()),
            "eligible_normal_missing_if_rows": int((normal & ~np.isfinite(self.hard_normal_raw_scores_)).sum()),
            "normal_weight_mass": float(weights[y == 0].sum()),
            "positive_weight_mass": float(weights[y == 1].sum()),
            "unknown_weight_mass": float(weights[y == -1].sum()),
            "eligible_tail_weight_mass": float(weights[self.hard_normal_tail_mask_].sum()),
            "quantile_mask_sha256": _mask_sha256(self.hard_normal_quantile_mask_),
            "eligible_normal_mask_sha256": _mask_sha256(normal),
            "tail_mask_sha256": _mask_sha256(self.hard_normal_tail_mask_),
            "if_state_before": self.hard_normal_if_state_before_, "if_state_after": after,
            "if_state_unchanged": True, "if_refitted": False,
            "in_sample_not_cross_fitted": True,
        }

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
        self._prepare_hard_normal(x, y)
        self.training_eligible_mask_ = np.zeros(len(x), dtype=bool)
        self.training_normalized_weight_ = np.zeros(len(x), dtype=float)
        self.training_sample_weight_ = np.zeros(len(x), dtype=float)
        self.event_weight_audit_ = []
        self.onset_weight_audit_ = []
        self.fit_normal_rows_ = self.fit_positive_rows_ = self.fit_events_ = 0
        self.known_onset_segments_ = self.eligible_onset_segments_ = self.eligible_onset_rows_ = 0
        self.onset_mass_redistributed_ = False
        changes = np.diff(np.r_[False, y == 1, False].astype(np.int8))
        starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
        for event_id, (start, end) in enumerate(zip(starts, ends), 1):
            known = bool(start > 0 and y[start - 1] == 0)
            self.known_onset_segments_ += int(known)
            self.onset_weight_audit_.append({
                "event_id": event_id, "start": int(start), "end_exclusive": int(end),
                "labeled_rows": int(end - start), "eligible_positive_rows": 0,
                "known_onset": known,
                "onset_censor_reason": None if known else ("series_start" if start == 0 else "preceding_unknown_label"),
                "onset_window_start": int(start),
                "onset_window_end_exclusive": int(min(end, start + ONSET_WINDOW_SAMPLES)),
                "eligible_onset_row_indices": [], "eligible_onset_rows": 0,
                "normalized_point_weight_mass": 0.0, "normalized_event_weight_mass": 0.0,
                "normalized_onset_weight_mass": 0.0, "normalized_weight_mass": 0.0,
            })
        if self.reference_supported_.sum() < self.minimum_channels:
            self._finalize_hard_normal(y)
            return self
        matrix, available = self.features(x)
        eligible = available & (y >= 0)
        self.training_eligible_mask_ = eligible
        positive = eligible & (y == 1)
        negative = eligible & (y == 0)
        self.fit_normal_rows_, self.fit_positive_rows_ = int(negative.sum()), int(positive.sum())
        events = []; onsets = []
        self.event_weight_audit_ = self.onset_weight_audit_
        for record in self.event_weight_audit_:
            start, end = record["start"], record["end_exclusive"]
            rows = np.flatnonzero(positive[start:end]) + start
            record["eligible_positive_rows"] = int(len(rows))
            if len(rows):
                events.append((rows, record))
            if record["known_onset"]:
                window_end = record["onset_window_end_exclusive"]
                onset_rows = np.flatnonzero(positive[start:window_end]) + start
                record["eligible_onset_row_indices"] = onset_rows.tolist()
                record["eligible_onset_rows"] = int(len(onset_rows))
                if len(onset_rows):
                    onsets.append((onset_rows, record))
        self.fit_events_ = len(events)
        self.eligible_onset_segments_ = len(onsets)
        self.eligible_onset_rows_ = sum(len(rows) for rows, _ in onsets)
        if self.fit_normal_rows_ < MIN_NORMAL_FIT_ROWS:
            self.fit_status_ = "insufficient_normal_examples"
            self._finalize_hard_normal(y)
            return self
        if not self.fit_positive_rows_:
            self.fit_status_ = "no_event_training"
            self._finalize_hard_normal(y)
            return self
        self.onset_mass_redistributed_ = not bool(onsets)
        event_mass = POSITIVE_EVENT_MASS + (POSITIVE_ONSET_MASS if not onsets else 0)
        weights = self.training_normalized_weight_
        self._apply_hard_normal_weights(negative, weights)
        weights[positive] = POSITIVE_POINT_MASS / self.fit_positive_rows_
        for rows, record in events:
            weights[rows] += event_mass / (self.fit_events_ * len(rows))
            record["normalized_point_weight_mass"] = float(POSITIVE_POINT_MASS * len(rows) / self.fit_positive_rows_)
            record["normalized_event_weight_mass"] = float(event_mass / self.fit_events_)
        for rows, record in onsets:
            weights[rows] += POSITIVE_ONSET_MASS / (len(onsets) * len(rows))
            record["normalized_onset_weight_mass"] = float(POSITIVE_ONSET_MASS / len(onsets))
        for rows, record in events:
            record["normalized_weight_mass"] = float(weights[rows].sum())
        # Preserve mathematically uniform masses; do not adjust an arbitrary row
        # to absorb harmless floating-point summation roundoff.
        if not np.isclose(weights.sum(), 1.0, rtol=0, atol=1e-12):
            raise AssertionError("Normalized training masses must sum to one")
        self.training_sample_weight_ = weights * int(eligible.sum())
        self.model_ = HistGradientBoostingClassifier(**HGB_PARAMS)
        self.model_.fit(matrix[eligible], y[eligible], sample_weight=self.training_sample_weight_[eligible])
        self.fit_status_ = "fitted"
        self._finalize_hard_normal(y)
        return self

    def inspection(self):
        result = super().inspection()
        result["hard_normal_weighting"] = deepcopy(getattr(self, "hard_normal_audit_", {"status": "not_fitted"}))
        return result
