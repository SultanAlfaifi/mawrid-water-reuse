"""Fixed onset-weighted HGB; frozen V7 features, references and inference.

Only training weights change. The onset window is THREE SAMPLES at original
offsets 0, 1 and 2, not an unconditional duration in seconds. A segment starts
at a known onset only when its immediately preceding label is known normal.
Unknown labels never become negatives, targets or onset evidence. No source IO.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from ml.gecco_v7.long_context import MIN_NORMAL_FIT_ROWS
from ml.gecco_v7.long_context_hgb import HGB_PARAMS, LongContextHGBScorer


ONSET_WINDOW_SAMPLES = 3
NEGATIVE_MASS = .5
POSITIVE_POINT_MASS = .125
POSITIVE_EVENT_MASS = .125
POSITIVE_ONSET_MASS = .25


class OnsetWeightedHGBScorer(LongContextHGBScorer):
    """Same channels constructor and scoring API; no calibration/policy change."""

    def __init__(self, channels):
        super().__init__(channels)
        self.feature_contract_["version"] = "long_context_fixed_hgb_onset_weighted_v1"
        self.feature_contract_["weighting"] = (
            "Normalized negative mass=0.5 uniformly over eligible known-normal rows. "
            "Positive mass=0.5: 0.125 point-uniform, 0.125 uniform across original "
            "known-positive segments with eligible rows, and 0.25 uniform across "
            "known-onset segments having eligible rows at original offsets 0,1,2, "
            "then uniform across those eligible onset rows. A known onset must be "
            "immediately preceded by label 0. No onset shifting, expansion or "
            "bridging across unknown labels. If no eligible known onset exists, "
            "its 0.25 mass moves to event-uniform mass, making that mass 0.375.")
        self.feature_contract_["onset_weighting"] = {
            "window_samples": ONSET_WINDOW_SAMPLES, "offsets_samples": [0, 1, 2],
            "physical_duration": "sampling-cadence dependent; no unconditional 120-second claim",
            "negative_mass": NEGATIVE_MASS, "positive_point_mass": POSITIVE_POINT_MASS,
            "positive_event_mass": POSITIVE_EVENT_MASS, "positive_onset_mass": POSITIVE_ONSET_MASS,
            "no_eligible_onset_event_mass": POSITIVE_EVENT_MASS + POSITIVE_ONSET_MASS,
            "onset_definition": "original positive-segment start immediately preceded by known label 0",
            "unavailable_onset_rows": "Excluded without moving the original window; no bonus to later rows",
            "censored_onsets": "series-start and post-unknown segments receive no onset bonus",
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
            return self
        if not self.fit_positive_rows_:
            self.fit_status_ = "no_event_training"
            return self
        self.onset_mass_redistributed_ = not bool(onsets)
        event_mass = POSITIVE_EVENT_MASS + (POSITIVE_ONSET_MASS if not onsets else 0)
        weights = self.training_normalized_weight_
        weights[negative] = NEGATIVE_MASS / self.fit_normal_rows_
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
        return self

    def inspection(self):
        result = super().inspection()
        result.update({
            "known_onset_segments": getattr(self, "known_onset_segments_", 0),
            "eligible_known_onset_segments": getattr(self, "eligible_onset_segments_", 0),
            "eligible_known_onset_rows": getattr(self, "eligible_onset_rows_", 0),
            "onset_mass_redistributed_to_event_uniform": getattr(self, "onset_mass_redistributed_", False),
            "onset_weighting_audit": getattr(self, "onset_weight_audit_", []),
        })
        return result
