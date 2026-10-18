"""V16 decision head and sensor-only V12 reference/feature adapters.

No source IO, teacher construction, policy selection or actuator commands.
Inner callers must fit each generator on its teacher INNER FIT, then supply
only later forecast examples. ``fit_final`` fits final references on original
training T; it never regenerates or replaces the prequential example matrix.
That reference refit is a disclosed representation shift. Scores are rankings,
not calibrated sensor trust or water-safety probabilities.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer, baseline_state_digest
from ml.gecco_v7.long_context_hgb import HGB_PARAMS
from ml.gecco_v16 import decisions

CONTEXT_NAMES = (
    'v6_alarm', 'v8_alarm', 'v6_known', 'v8_known',
    'anchor_opportunity', 'anchor_age_fraction',
    'recovery_opportunity', 'recovery_age_fraction',
)
MIN_NORMAL_ROWS = 128
MIN_POSITIVE_EVENTS = 2
MIN_POSITIVE_FOLDS = 2


def _hash_array(values):
    a = np.ascontiguousarray(values)
    h = hashlib.sha256()
    h.update(str(a.shape).encode()); h.update(a.dtype.str.encode()); h.update(a.tobytes())
    return h.hexdigest()


def _plain(value):
    """Return JSON-safe inspection metadata without mutating audit state."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _labels(labels, rows):
    y = np.asarray(labels)
    if y.shape != (rows,) or y.dtype.kind not in 'biu' or not np.isin(y, [-1, 0, 1]).all():
        raise ValueError('labels must be same-length integer/bool -1/0/1 values')
    return y.astype(np.int8, copy=False)


def _integer_vector(value, rows, name):
    a = np.asarray(value)
    if a.shape != (rows,) or a.dtype.kind not in 'iu':
        raise ValueError(name + ' must be a same-length integer vector')
    if (a < 0).any() or (a > np.iinfo(np.int64).max).any():
        raise ValueError(name + ' must contain representable nonnegative integers')
    return a.astype(np.int64, copy=False)


def _matrix(value, width, name):
    a = np.asarray(value)
    if a.ndim != 2 or a.shape[1] != width or a.dtype != np.dtype('float32') or not np.isfinite(a).all():
        raise ValueError(name + ' must be a finite float32 matrix of width ' + str(width))
    return a


def _available(value, rows):
    a = np.asarray(value)
    if a.shape != (rows,) or a.dtype.kind != 'b':
        raise ValueError('available must be a same-length Boolean vector')
    return a


def _gap(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 0:
        raise ValueError('gap_samples must be a nonnegative integer')
    return int(value)


def _context(v6, v8, rows):
    result = decisions.contexts(v6, v8)
    matrix = _matrix(result['matrix'], 8, 'decision context')
    if len(matrix) != rows or tuple(result['feature_names']) != CONTEXT_NAMES:
        raise ValueError('Decision context axis/order differs from the frozen protocol')
    for key in ('active', 'anchor_active', 'recovery_active'):
        _available(result[key], rows)
    return result


def fit_generator(channels, baseline_estimator, frame, labels):
    """Fit ONLY V12 normal/Ridge references on the supplied past inner fit.

    The supplied IF must already be fitted on that same allowed past. This
    helper never fits IF or HGB; ownership/indices are audited by the caller.
    """
    generator = BaselineEvidenceHGBScorer(channels, baseline_estimator)
    x = generator._frame(frame); y = _labels(labels, len(x))
    before = baseline_state_digest(baseline_estimator)
    generator._fit_references(x, y)
    generator.training_rows_ = len(x)
    generator.label_counts_ = {'unknown': int((y < 0).sum()), 'normal': int((y == 0).sum()),
                               'positive': int((y == 1).sum())}
    generator.fit_status_ = ('references_fitted' if generator.reference_supported_.sum() >= generator.minimum_channels
                             else 'insufficient_normal_reference')
    generator.reference_training_label_sha256_ = _hash_array(y)
    generator.reference_only_fit_ = True
    generator.feature_contract_['original_if_evidence']['training_scope'] = (
        'Reference-only V16 feature generator: no HGB is fitted here and no '
        'in-sample generator scores train the decision head. Inner generators '
        'provide only later forecast examples; final references provide outer '
        'calibration/test features. The caller audits temporal ownership.')
    if generator.model_ is not None or baseline_state_digest(baseline_estimator) != before:
        raise AssertionError('Reference-only generation changed or fitted a classifier')
    return generator


def generator_inspection(generator):
    """Describe the reference-only role without changing inherited estimators.

    V12's ordinary inspection describes its own in-sample HGB training. V16
    uses only its reference/feature provider, so those inherited training tags
    do not describe this object's role. Forward teachers apply to head-example
    construction; they do not make this individual generator cross-fitted.
    """
    result = generator.inspection()
    result['reference_only_fit'] = bool(getattr(generator, 'reference_only_fit_', False))
    result['head_examples_from_forward_teachers'] = True
    result['hgb_fitted_here'] = False
    result['original_if_evidence']['in_sample_training_representation'] = False
    result['original_if_evidence']['cross_fitted'] = False
    result['original_if_evidence']['reference_only_fit'] = True
    result['original_if_evidence']['head_examples_from_forward_teachers'] = True
    return _plain(result)


def features_gap(generator, frame, gap_samples=120):
    """Discard gap sensors BEFORE feature generation; retain original row axis.

    Features use the supplied segment's history only. For GECCO2019 outer
    calibration the caller passes the concatenated calibration interval once,
    then slices these features while resetting decision requests per block.
    """
    gap = _gap(gap_samples)
    x = generator._frame(frame)
    n, width = len(x), len(generator.feature_names_)
    matrix = np.zeros((n, width), dtype=np.float32)
    available = np.zeros(n, dtype=bool)
    if n > gap:
        values, observed = generator.features(x.iloc[gap:].reset_index(drop=True))
        matrix[gap:] = _matrix(values, width, 'base features')
        available[gap:] = _available(observed, n - gap)
    return matrix, available


def decision_matrix(generator, frame, v6, v8, gap_samples=120):
    base, available = features_gap(generator, frame, gap_samples)
    context = _context(v6, v8, len(base))
    return np.concatenate((base, context['matrix']), axis=1), available, context


def combine_and_score(scorer, baseX, available, v6, v8):
    """Score shared sensor features with fresh per-call decision request state."""
    return scorer.score_matrix(baseX, available, v6, v8)


class DecisionHeadScorer:
    """One HGB fit on supplied forward-teacher decision examples, no replay.

    ``examples`` contains matrix float32[M,D+8], sorted unique original-T
    indices, fold_ids, original positive-segment event_ids, FINAL SCALED sample
    weights, and the unchanged global ``decisions.weights`` summary. Targets
    are derived from labels[indices], never accepted as an extra target input.
    No example matrices are retained in the fitted object; their exact hash is.
    """
    def __init__(self, channels, original_IF):
        template = BaselineEvidenceHGBScorer(channels, original_IF)
        self.channels = list(template.channels)
        self.original_IF_ = original_IF
        self.original_if_state_sha256_ = baseline_state_digest(original_IF)
        self.base_feature_names_ = list(template.feature_names_)
        self.feature_names_ = self.base_feature_names_ + list(CONTEXT_NAMES)
        self.max_lookback_samples = template.max_lookback_samples
        self.history_rows = template.history_rows
        self.generator_ = None
        self.model_ = None
        self.fit_status_ = 'not_fitted'
        self.request_support_ = {key: {'supported': False} for key in ('anchor', 'recovery')}
        self.training_summary_ = {}
        self.feature_contract_ = {
            'version': 'v16_forward_teacher_decision_head_v1',
            'base_feature_contract': deepcopy(template.feature_contract_),
            'context_features': list(CONTEXT_NAMES), 'feature_names': list(self.feature_names_),
            'feature_count': len(self.feature_names_), 'classifier': dict(HGB_PARAMS),
            'target': 'Current original label at supplied original-T indices; unknown has zero weight.',
            'training_examples': 'Forward teacher examples; inner references must belong to inner FIT only. Caller owns lineage and independent replay.',
            'reference_shift': 'Final references are refitted on original T, unlike inner-example references; no identical-distribution guarantee.',
            'request_support': 'NaN if ANY active request type lacks >=1 eligible normal opportunity and >=1 eligible positive segment.',
            'score_scope': 'Decision opportunity ranking, not a calibrated safety/trust probability.',
            'initial_gap_samples_default': 120, 'minimum_history_after_gap_samples': 60,
            'cadence': 'Context offsets0/1/2 assume the frozen60-second experiment; feature windows count samples.',
            'no_file_io': True, 'no_if_fit': True, 'no_policy_selection': True,
        }

    def fit_final(self, frame, labels, examples):
        # Fit final references, but never use them to regenerate training X.
        # A failed refit must not leave a prior classifier paired with new refs.
        self.model_ = None
        self.fit_status_ = 'fit_in_progress'
        self.generator_ = None
        self.generator_ = fit_generator(self.channels, self.original_IF_, frame, labels)
        y = _labels(labels, len(frame)); self.training_rows_ = len(y)
        if not isinstance(examples, dict) or not {'matrix', 'indices', 'fold_ids', 'weights', 'event_ids', 'summary'} <= set(examples):
            raise ValueError('Examples require matrix/indices/fold_ids/weights/event_ids/summary')
        X = _matrix(examples['matrix'], len(self.feature_names_), 'example matrix')
        m = len(X)
        indices = _integer_vector(examples['indices'], m, 'indices')
        folds = _integer_vector(examples['fold_ids'], m, 'fold_ids')
        events = _integer_vector(examples['event_ids'], m, 'event_ids')
        if (indices >= len(y)).any() or (m > 1 and (np.diff(indices) <= 0).any()):
            raise ValueError('Example indices must be sorted unique original-training rows')
        weights = np.asarray(examples['weights'])
        if weights.shape != (m,) or weights.dtype.kind not in 'iuf' or not np.isfinite(weights).all() or (weights < 0).any():
            raise ValueError('Sample weights must be finite, nonnegative real values')
        weights = weights.astype(np.float64, copy=False)
        target = y[indices]
        full_events = np.cumsum((y == 1) & ~np.r_[False, y[:-1] == 1]).astype(np.int64)
        full_events[y != 1] = 0
        if not np.array_equal(events, full_events[indices]):
            raise ValueError('Event IDs must retain original full-training positive segments')
        eligible = weights > 0
        if ((target < 0) & eligible).any():
            raise ValueError('Unknown labels cannot receive supervised weight')
        context = X[:, -8:]
        if not np.isin(context[:, (0, 1, 2, 3, 4, 6)], [0, 1]).all() or not np.isin(context[:, (5, 7)], [0, .5, 1]).all():
            raise ValueError('Example context must use frozen binary flags and age/2')
        if ((context[:, 4] == 0) & (context[:, 5] != 0)).any() or ((context[:, 6] == 0) & (context[:, 7] != 0)).any():
            raise ValueError('Inactive request ages must be zero')
        if (eligible & ~((context[:, 4] == 1) | (context[:, 6] == 1))).any():
            raise ValueError('Weighted rows must belong to a decision opportunity')
        normal, positive = eligible & (target == 0), eligible & (target == 1)
        n = int(eligible.sum()); normalized = weights / n if n else weights.copy()
        normal_rows, positive_rows = int(normal.sum()), int(positive.sum())
        positive_events = np.unique(events[positive]).tolist()
        positive_folds = np.unique(folds[positive]).tolist()
        fit_checks = {'normal_rows': normal_rows >= MIN_NORMAL_ROWS,
                      'positive_events': len(positive_events) >= MIN_POSITIVE_EVENTS,
                      'positive_folds': len(positive_folds) >= MIN_POSITIVE_FOLDS}
        summary = examples['summary']
        if not isinstance(summary, dict):
            raise ValueError('Global decision-weight summary must be a dictionary')
        expected = {'normal_rows': normal_rows, 'positive_rows': positive_rows,
            'positive_events': len(positive_events), 'positive_folds': positive_folds,
            'positive_fold_count': len(positive_folds), 'eligible_rows': n,
            'fit_supported': all(fit_checks.values())}
        for key, value in expected.items():
            if key not in summary or summary[key] != value:
                raise ValueError('Global weight summary mismatch: ' + key)
        masses = {'normal_weight_mass': float(normalized[normal].sum()),
                  'positive_weight_mass': float(normalized[positive].sum()),
                  'unknown_weight_mass': float(normalized[target < 0].sum()),
                  'normalized_weight_sum': float(normalized.sum())}
        for key, value in masses.items():
            supplied = summary.get(key)
            if isinstance(supplied, (bool, np.bool_)) or not isinstance(supplied, (int, float, np.number)) or not np.isclose(supplied, value, rtol=0, atol=1e-12):
                raise ValueError('Global weight mass mismatch: ' + key)
        if not np.isclose(masses['normal_weight_mass'], .5 if normal_rows else 0, rtol=0, atol=1e-12) or not np.isclose(masses['positive_weight_mass'], .5 if positive_rows else 0, rtol=0, atol=1e-12):
            raise ValueError('Each present class must keep its prescribed normalized mass0.5')
        support = summary.get('request_support')
        if not isinstance(support, dict) or set(support) != {'anchor', 'recovery'}:
            raise ValueError('Both request-type support records are required')
        for key, column in (('anchor', 4), ('recovery', 6)):
            record = support[key]
            if not isinstance(record, dict):
                raise ValueError('Request support records must be dictionaries')
            active = context[:, column] == 1
            ids = np.unique(events[positive & active]).tolist()
            for field, value in (('positive_events', len(ids)), ('positive_event_ids', ids),
                                 ('normal_rows', int((normal & active).sum())), ('positive_rows', int((positive & active).sum()))):
                if record.get(field) != value:
                    raise ValueError('Request support mismatch: ' + key + '/' + field)
            count = record.get('normal_opportunities')
            if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)) or not 0 <= count <= int((normal & active).sum()):
                raise ValueError('Invalid eligible normal opportunity count')
            expected_support = count >= 1 and len(ids) >= 1
            if not isinstance(record.get('supported'), (bool, np.bool_)) or bool(record['supported']) != expected_support:
                raise ValueError('Request support Boolean disagrees with minimum evidence')

        self.model_ = None
        self.example_indices_ = indices.copy(); self.example_fold_ids_ = folds.copy()
        self.example_event_ids_ = events.copy(); self.example_targets_ = target.copy()
        self.example_sample_weight_ = weights.copy(); self.example_normalized_weight_ = normalized.copy()
        self.example_eligible_mask_ = eligible.copy()
        self.example_matrix_sha256_ = _hash_array(X)
        self.training_summary_ = deepcopy(summary); self.request_support_ = deepcopy(support)
        self.fit_normal_rows_ = normal_rows; self.fit_positive_rows_ = positive_rows
        self.fit_events_ = len(positive_events); self.fit_positive_folds_ = positive_folds
        self.fit_checks_ = fit_checks
        if not fit_checks['normal_rows']:
            self.fit_status_ = 'insufficient_normal_decision_rows'
        elif not fit_checks['positive_events']:
            self.fit_status_ = 'insufficient_positive_events'
        elif not fit_checks['positive_folds']:
            self.fit_status_ = 'insufficient_positive_folds'
        else:
            self.model_ = HistGradientBoostingClassifier(**HGB_PARAMS)
            self.model_.fit(X[eligible], target[eligible], sample_weight=weights[eligible])
            self.fit_status_ = 'fitted'
        if baseline_state_digest(self.original_IF_) != self.original_if_state_sha256_:
            raise AssertionError('Original IF changed during final reference/head fit')
        return self

    def score_matrix(self, baseX, available, v6, v8):
        base = _matrix(baseX, len(self.base_feature_names_), 'base features')
        observed = _available(available, len(base)); context = _context(v6, v8, len(base))
        score = np.full(len(base), np.nan, dtype=np.float64)
        eligible = observed & context['active']
        for key in ('anchor', 'recovery'):
            if not self.request_support_[key]['supported']:
                eligible &= ~context[key + '_active']
        if self.model_ is None or not eligible.any():
            return score
        X = np.concatenate((base[eligible], context['matrix'][eligible]), axis=1)
        classes = np.asarray(self.model_.classes_)
        positive_column = np.flatnonzero(classes == 1)
        if classes.ndim != 1 or len(positive_column) != 1:
            raise ValueError('Fitted head has no unique positive class')
        probabilities = np.asarray(self.model_.predict_proba(X), dtype=np.float64)
        if probabilities.shape != (int(eligible.sum()), len(classes)):
            raise ValueError('Head probabilities do not preserve the score axis')
        values = probabilities[:, positive_column[0]]
        rows = np.flatnonzero(eligible); finite = np.isfinite(values)
        if ((values[finite] < 0) | (values[finite] > 1)).any():
            raise ValueError('Invalid classifier probability range')
        score[rows[finite]] = values[finite]
        return score

    def score(self, frame, v6, v8, gap_samples=120):
        if self.generator_ is None:
            _gap(gap_samples)
            if not isinstance(frame, pd.DataFrame) or any(list(frame.columns).count(c) != 1 for c in self.channels):
                raise ValueError('frame must contain each configured sensor exactly once')
            _context(v6, v8, len(frame))
            return np.full(len(frame), np.nan, dtype=np.float64)
        base, available = features_gap(self.generator_, frame, gap_samples)
        return self.score_matrix(base, available, v6, v8)

    def inspection(self):
        current = baseline_state_digest(self.original_IF_)
        result = {'feature_contract': deepcopy(self.feature_contract_), 'fit_status': self.fit_status_,
            'training_rows': getattr(self, 'training_rows_', 0),
            'example_rows': len(getattr(self, 'example_indices_', [])),
            'example_matrix_sha256': getattr(self, 'example_matrix_sha256_', None),
            'training_summary': deepcopy(self.training_summary_), 'request_support': deepcopy(self.request_support_),
            'fit_checks': getattr(self, 'fit_checks_', {}),
            'original_if_state_at_attachment': self.original_if_state_sha256_,
            'original_if_state_current': current, 'original_if_unchanged': current == self.original_if_state_sha256_,
            'final_generator': None if self.generator_ is None else generator_inspection(self.generator_),
            'example_arrays_retained_for_audit': True, 'example_matrix_retained': False,
            'representation_shift_disclosed': True}
        result['example_array_sha256'] = {name: _hash_array(getattr(self, name)) for name in (
            'example_indices_', 'example_fold_ids_', 'example_event_ids_', 'example_targets_',
            'example_sample_weight_', 'example_normalized_weight_', 'example_eligible_mask_') if hasattr(self, name)}
        return _plain(result)
