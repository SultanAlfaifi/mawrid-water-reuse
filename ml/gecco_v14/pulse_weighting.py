"""One HGB fit with sensor-tail-pulse bonus weights on the original train axis.

All features, normal references, IF state and inference come from frozen V12.
Only supervised weights change. IF scores are an in-sample representation,
not out-of-fold evidence or a calibrated probability. This module has no I/O.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from ml.gecco_v7.long_context import MIN_NORMAL_FIT_ROWS
from ml.gecco_v7.long_context_hgb import HGB_PARAMS
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer, baseline_state_digest

TAIL_QUANTILE = .95
PULSE_WINDOW_SAMPLES = 3
NEGATIVE_MASS = .5
POSITIVE_POINT_MASS = .125
POSITIVE_EVENT_MASS = .125
POSITIVE_PULSE_MASS = .25


def _mask_sha256(mask):
    return hashlib.sha256(np.ascontiguousarray(mask, dtype=np.bool_).tobytes()).hexdigest()


class SensorTailPulseHGBScorer(BaselineEvidenceHGBScorer):
    """Frozen V12 constructor/scoring API; one changed training-weight recipe."""

    def __init__(self, channels, baseline_estimator):
        super().__init__(channels, baseline_estimator)
        self.feature_contract_["version"] = "long_context_hgb_conditional_frozen_if_sensor_tail_pulse_v1"
        self.feature_contract_["weighting"] = (
            "Eligible known-normal mass0.5 uniform; positive point mass0.125 and "
            "segment-uniform mass0.125. Bonus0.25 uniform across positive segments "
            "with eligible confirmed IF-tail pulse-window rows, then uniform across "
            "their qualifying pulses, then uniform across each intersection's rows. "
            "Original label-onset bonus is removed. With no eligible pulse-window "
            "intersection anywhere, bonus0.25 moves to segment-uniform mass0.375.")
        self.feature_contract_["onset_weighting"] = {
            "enabled": False, "replacement": "sensor_tail_pulse_weighting",
            "label_onset_bonus_mass": 0.0,
        }
        self.feature_contract_["sensor_tail_pulse_weighting"] = {
            "quantile": TAIL_QUANTILE, "quantile_method": "linear", "tail_comparison": ">=",
            "quantile_population": "ALL original train label==0 rows with finite float64 raw original-IF score, including HGB-ineligible rows",
            "tail_definition": "finite(raw_score) and raw_score>=q95 on the FULL original training axis",
            "confirmed_start": "start>0 with immediately preceding raw score finite and strictly below q95",
            "censored_starts": "series start or immediately after any nonfinite raw score; no bonus",
            "label_boundaries": "Do not reset or create a sensor-tail pulse at a label boundary",
            "window_offsets_samples": [0, 1, 2],
            "window_end": "min(pulse_end_exclusive, pulse_start+3), fixed before label or feature-availability filtering",
            "pulse_scope": "ALL confirmed pulses, not only the first pulse in a positive segment",
            "bonus_hierarchy": "equal eligible positive segments, then equal qualifying pulse intersections within each segment, then equal eligible positive rows within each intersection",
            "unknown_labels": "zero supervised weight; never quantile normals; do not reset sensor-tail geometry",
            "unavailable_rows": "excluded without axis compression, extending a window or replacing its original offsets",
            "negative_mass": NEGATIVE_MASS, "positive_point_mass": POSITIVE_POINT_MASS,
            "positive_event_mass": POSITIVE_EVENT_MASS, "positive_pulse_mass": POSITIVE_PULSE_MASS,
            "no_eligible_pulse_event_mass": POSITIVE_EVENT_MASS + POSITIVE_PULSE_MASS,
            "physical_duration": "three original samples, cadence-dependent; no unconditional duration claim",
            "if_refit": False, "in_sample_not_cross_fitted": True,
            "feature_availability": "exactly frozen V12; missing IF evidence never removes another eligible row",
            "mask_encoding": "SHA256 of C-contiguous np.bool_ bytes on original train axis",
        }
        self.feature_contract_["original_if_evidence"]["original_availability"] = (
            "V12 features, availability and eligible fit population unchanged; only V14 supervised weights change.")

    def _prepare_pulses(self, frame, y):
        self.pulse_if_state_before_ = baseline_state_digest(self.baseline_estimator_)
        raw = np.asarray(self.baseline_raw_scores(frame), dtype=np.float64)
        if raw.shape != (len(frame),):
            raise ValueError("Frozen IF training score shape mismatch")
        self.pulse_raw_scores_ = raw.copy()
        finite = np.isfinite(raw)
        self.pulse_quantile_mask_ = (y == 0) & finite
        self.pulse_q95_ = (float(np.quantile(raw[self.pulse_quantile_mask_], TAIL_QUANTILE,
            method="linear")) if self.pulse_quantile_mask_.any() else None)
        self.pulse_quantile_status_ = ("available" if self.pulse_q95_ is not None else
            "missing_estimator" if self.baseline_estimator_ is None else "no_finite_known_normal_scores")
        self.pulse_tail_mask_ = finite & (raw >= self.pulse_q95_) if self.pulse_q95_ is not None else np.zeros(len(y), bool)
        changes = np.diff(np.r_[False, self.pulse_tail_mask_, False].astype(np.int8))
        self.pulse_starts_ = np.flatnonzero(changes == 1)
        self.pulse_ends_exclusive_ = np.flatnonzero(changes == -1)
        self.pulse_known_onset_mask_ = np.zeros(len(self.pulse_starts_), bool)
        self.pulse_window_mask_ = np.zeros(len(y), bool)
        self.pulse_bonus_mask_ = np.zeros(len(y), bool)
        self.training_pulse_bonus_weight_ = np.zeros(len(y), float)
        self.pulse_records_ = []
        self.pulse_bonus_redistributed_ = False
        self.pulse_status_ = "not_applied"
        self.eligible_pulse_segments_ = self.eligible_pulse_count_ = self.eligible_pulse_intersections_ = 0
        for pulse_id, (start, end) in enumerate(zip(self.pulse_starts_, self.pulse_ends_exclusive_), 1):
            start, end = int(start), int(end)
            known = bool(start > 0 and finite[start - 1] and raw[start - 1] < self.pulse_q95_)
            self.pulse_known_onset_mask_[pulse_id - 1] = known
            window_end = min(end, start + PULSE_WINDOW_SAMPLES) if known else start
            self.pulse_window_mask_[start:window_end] = True
            self.pulse_records_.append({
                "pulse_id": pulse_id, "start": start, "end_exclusive": end,
                "known_onset": known,
                "censor_reason": None if known else ("series_start" if start == 0 else "preceding_nonfinite_if_score"),
                "window_start": start, "window_end_exclusive": window_end,
                "window_row_indices": list(range(start, window_end)),
                "eligible_positive_row_indices": [], "segment_intersections": [],
                "normalized_bonus_weight_mass": 0.0,
            })
        self.pulse_known_starts_ = self.pulse_starts_[self.pulse_known_onset_mask_].copy()

    def _link_pulses_to_segments(self, positive):
        # At most three original rows per pulse: no segment-by-pulse cross-product.
        segment_at = np.zeros(len(positive), np.int64)
        for record in self.pulse_segment_audit_:
            segment_at[record["start"]:record["end_exclusive"]] = record["event_id"]
        self.pulse_bonus_mask_ = self.pulse_window_mask_ & positive
        for pulse in self.pulse_records_:
            a, b = pulse["window_start"], pulse["window_end_exclusive"]
            rows = np.flatnonzero(positive[a:b]) + a
            pulse["eligible_positive_row_indices"] = rows.tolist()
            for event_id in np.unique(segment_at[rows]):
                selected = rows[segment_at[rows] == event_id]
                intersection = {
                    "pulse_id": pulse["pulse_id"], "event_id": int(event_id),
                    "pulse_start": pulse["start"], "pulse_end_exclusive": pulse["end_exclusive"],
                    "window_start": a, "window_end_exclusive": b,
                    "eligible_row_indices": selected.tolist(), "eligible_rows": int(len(selected)),
                    "normalized_bonus_weight_mass": 0.0, "normalized_bonus_weight_per_row": 0.0,
                }
                self.pulse_segment_audit_[int(event_id) - 1]["pulse_intersections"].append(intersection)
                pulse["segment_intersections"].append(intersection)
        self.eligible_pulse_segments_ = sum(bool(s["pulse_intersections"]) for s in self.pulse_segment_audit_)
        self.eligible_pulse_count_ = sum(bool(p["eligible_positive_row_indices"]) for p in self.pulse_records_)
        self.eligible_pulse_intersections_ = sum(len(s["pulse_intersections"]) for s in self.pulse_segment_audit_)

    def _finalize_pulses(self, y):
        after = baseline_state_digest(self.baseline_estimator_)
        if after != self.pulse_if_state_before_:
            raise AssertionError("Frozen IF state mutated during HGB fitting")
        if self.fit_status_ != "fitted":
            self.pulse_status_ = "not_applied_" + self.fit_status_
        w = self.training_normalized_weight_
        self.pulse_weighting_audit_ = {
            "status": self.pulse_status_, "quantile_status": self.pulse_quantile_status_,
            "q95": self.pulse_q95_, "quantile": TAIL_QUANTILE, "quantile_method": "linear",
            "tail_comparison": ">=", "window_samples": PULSE_WINDOW_SAMPLES,
            "training_rows": len(y), "quantile_population_rows": int(self.pulse_quantile_mask_.sum()),
            "quantile_population_hgb_ineligible_rows": int((self.pulse_quantile_mask_ & ~self.training_eligible_mask_).sum()),
            "tail_rows": int(self.pulse_tail_mask_.sum()), "tail_episodes": len(self.pulse_records_),
            "confirmed_tail_pulses": int(self.pulse_known_onset_mask_.sum()),
            "censored_tail_episodes": int((~self.pulse_known_onset_mask_).sum()),
            "confirmed_window_rows": int(self.pulse_window_mask_.sum()),
            "eligible_bonus_rows": int(self.pulse_bonus_mask_.sum()),
            "eligible_bonus_segments": self.eligible_pulse_segments_,
            "eligible_bonus_pulses": self.eligible_pulse_count_,
            "eligible_segment_pulse_intersections": self.eligible_pulse_intersections_,
            "bonus_redistributed_to_event_uniform": self.pulse_bonus_redistributed_,
            "normal_weight_mass": float(w[y == 0].sum()),
            "positive_weight_mass": float(w[y == 1].sum()), "unknown_weight_mass": float(w[y == -1].sum()),
            "point_component_mass": float(sum(s["normalized_point_weight_mass"] for s in self.pulse_segment_audit_)),
            "event_component_mass": float(sum(s["normalized_event_weight_mass"] for s in self.pulse_segment_audit_)),
            "pulse_component_mass": float(self.training_pulse_bonus_weight_.sum()),
            "label_onset_bonus_mass": 0.0,
            "quantile_mask_sha256": _mask_sha256(self.pulse_quantile_mask_),
            "tail_mask_sha256": _mask_sha256(self.pulse_tail_mask_),
            "window_mask_sha256": _mask_sha256(self.pulse_window_mask_),
            "bonus_mask_sha256": _mask_sha256(self.pulse_bonus_mask_),
            "if_state_before": self.pulse_if_state_before_, "if_state_after": after,
            "if_state_unchanged": True, "if_refitted": False, "in_sample_not_cross_fitted": True,
            "pulse_records": self.pulse_records_, "segment_records": self.pulse_segment_audit_,
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
        self.label_counts_ = {"unknown": int((y == -1).sum()), "normal": int((y == 0).sum()), "positive": int((y == 1).sum())}
        self._fit_references(x, y)
        self._prepare_pulses(x, y)
        self.training_eligible_mask_ = np.zeros(len(x), bool)
        self.training_normalized_weight_ = np.zeros(len(x), float)
        self.training_sample_weight_ = np.zeros(len(x), float)
        self.pulse_segment_audit_ = []
        self.event_weight_audit_ = self.pulse_segment_audit_
        # Legacy onset attributes stay explicitly empty: no label-onset bonus.
        self.onset_weight_audit_ = []
        self.known_onset_segments_ = self.eligible_onset_segments_ = self.eligible_onset_rows_ = 0
        self.onset_mass_redistributed_ = False
        self.fit_normal_rows_ = self.fit_positive_rows_ = self.fit_events_ = 0
        changes = np.diff(np.r_[False, y == 1, False].astype(np.int8))
        starts, ends = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
        for event_id, (start, end) in enumerate(zip(starts, ends), 1):
            known = bool(start > 0 and y[start - 1] == 0)
            self.pulse_segment_audit_.append({
                "event_id": event_id, "start": int(start), "end_exclusive": int(end),
                "labeled_rows": int(end - start), "label_known_onset": known,
                "eligible_positive_rows": 0, "pulse_intersections": [],
                "normalized_point_weight_mass": 0.0, "normalized_event_weight_mass": 0.0,
                "normalized_pulse_weight_mass": 0.0, "normalized_onset_weight_mass": 0.0,
                "normalized_weight_mass": 0.0,
            })
        if self.reference_supported_.sum() < self.minimum_channels:
            self._finalize_pulses(y)
            return self
        matrix, available = self.features(x)
        eligible = available & (y >= 0)
        self.training_eligible_mask_ = eligible
        positive, negative = eligible & (y == 1), eligible & (y == 0)
        self.fit_normal_rows_, self.fit_positive_rows_ = int(negative.sum()), int(positive.sum())
        events = []
        for record in self.pulse_segment_audit_:
            rows = np.flatnonzero(positive[record["start"]:record["end_exclusive"]]) + record["start"]
            record["eligible_positive_rows"] = int(len(rows))
            if len(rows):
                events.append((rows, record))
        self.fit_events_ = len(events)
        self._link_pulses_to_segments(positive)
        if self.fit_normal_rows_ < MIN_NORMAL_FIT_ROWS:
            self.fit_status_ = "insufficient_normal_examples"
            self._finalize_pulses(y)
            return self
        if not self.fit_positive_rows_:
            self.fit_status_ = "no_event_training"
            self._finalize_pulses(y)
            return self
        self.pulse_bonus_redistributed_ = self.eligible_pulse_segments_ == 0
        self.pulse_status_ = "event_uniform_fallback" if self.pulse_bonus_redistributed_ else "pulse_weighted"
        event_mass = POSITIVE_EVENT_MASS + (POSITIVE_PULSE_MASS if self.pulse_bonus_redistributed_ else 0)
        weights = self.training_normalized_weight_
        weights[negative] = NEGATIVE_MASS / self.fit_normal_rows_
        weights[positive] = POSITIVE_POINT_MASS / self.fit_positive_rows_
        for rows, record in events:
            weights[rows] += event_mass / (self.fit_events_ * len(rows))
            record["normalized_point_weight_mass"] = float(POSITIVE_POINT_MASS * len(rows) / self.fit_positive_rows_)
            record["normalized_event_weight_mass"] = float(event_mass / self.fit_events_)
            intersections = record["pulse_intersections"]
            if intersections:
                segment_mass = POSITIVE_PULSE_MASS / self.eligible_pulse_segments_
                record["normalized_pulse_weight_mass"] = segment_mass
                for item in intersections:
                    mass = segment_mass / len(intersections)
                    per_row = mass / item["eligible_rows"]
                    self.training_pulse_bonus_weight_[item["eligible_row_indices"]] += per_row
                    item["normalized_bonus_weight_mass"] = mass
                    item["normalized_bonus_weight_per_row"] = per_row
                    self.pulse_records_[item["pulse_id"] - 1]["normalized_bonus_weight_mass"] += mass
        weights += self.training_pulse_bonus_weight_
        for rows, record in events:
            record["normalized_weight_mass"] = float(weights[rows].sum())
        if not np.isclose(weights.sum(), 1.0, rtol=0, atol=1e-12):
            raise AssertionError("Normalized training masses must sum to one")
        self.training_sample_weight_ = weights * int(eligible.sum())
        self.model_ = HistGradientBoostingClassifier(**HGB_PARAMS)
        self.model_.fit(matrix[eligible], y[eligible], sample_weight=self.training_sample_weight_[eligible])
        self.fit_status_ = "fitted"
        self._finalize_pulses(y)
        return self

    def inspection(self):
        result = deepcopy(super().inspection())
        for key in ("known_onset_segments", "eligible_known_onset_segments", "eligible_known_onset_rows",
                    "onset_mass_redistributed_to_event_uniform", "onset_weighting_audit"):
            result.pop(key, None)
        result["label_onset_bonus_removed"] = True
        result["sensor_tail_pulse_weighting"] = deepcopy(getattr(self, "pulse_weighting_audit_", {"status": "not_fitted"}))
        return result
