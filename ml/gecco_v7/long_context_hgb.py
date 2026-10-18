"""Fixed HGB development attempt; unchanged V7 causal features and weights.

The original ExtraTrees implementation remains frozen. This subclass inherits
all feature/reference/inference code and repeats its fit bookkeeping solely to
instantiate a different, prespecified estimator. No source IO or model/threshold
search occurs. Inputs remain integer -1/0/1 labels; unknown labels have no
reference, target or sample-weight role. Scores are not water-safety estimates.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from ml.gecco_v7.long_context import LongContextEventScorer, MIN_NORMAL_FIT_ROWS


HGB_PARAMS = dict(max_iter=100, max_leaf_nodes=15, max_depth=None,
                  min_samples_leaf=20, learning_rate=0.08, l2_regularization=1,
                  max_bins=63, early_stopping=False, random_state=20261016)


class LongContextHGBScorer(LongContextEventScorer):
    """Same fit / score_components / features / inspection API as frozen V7.

The only statistical method change is ExtraTrees -> fixed HGB. References,
availability, history, feature ordering, event segmentation and weighting are
inherited or copied exactly. Automatic/random early-stopping splits are off.
"""

    def __init__(self, channels):
        super().__init__(channels)
        self.feature_contract_["version"] = "long_context_fixed_hgb_v1"
        self.feature_contract_["classifier"] = dict(HGB_PARAMS)

    def fit(self, frame, labels):
        # This bookkeeping is deliberately identical to frozen parent.fit;
        # estimator construction below is the sole functional substitution.
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
        self.model_ = HistGradientBoostingClassifier(**HGB_PARAMS)
        self.model_.fit(matrix[eligible], y[eligible], sample_weight=self.training_sample_weight_[eligible])
        self.fit_status_ = "fitted"
        return self
