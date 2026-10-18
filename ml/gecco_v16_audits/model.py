"""V16 reference/feature/score audit helpers, with explicit inherited numerics.

No V16 production model, teacher, runner or feature wrapper is imported. Normal
references, Ridge fitting populations/algebra, availability and request context
have independent oracles. Rich V7 rolling-feature arithmetic and fitted sklearn
predictors are inherited providers, NOT a second independent implementation.

IMPORTANT: feature validation permits the frozen V9 one-float32-ULP tolerance
only in conditional residual columns. The RETURNED feature matrix is the exact
frozen V12 full-prefix numeric provider, never the algebraically approximate
matrix: even one ULP can change a fitted HGB bin. IF is evaluated on the entire
supplied segment AFTER its gap, never cropped and asserted numerically equal.
Import and all functions have no source I/O, model fitting or threshold search.
"""
from __future__ import annotations

from copy import copy
import hashlib
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ml.gecco_v7.long_context import LongContextEventScorer
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer
from ml.gecco_v7_audits.replay import Checks
from ml.gecco_v7_audits.replay_certified import fitted_state_digest
from ml.gecco_v8_audits.replay import reference_oracle
from ml.gecco_v9_audits import replay as conditional_audit
from ml.gecco_v12_audits import replay as if_audit
from ml.gecco_v16_audits.decisions import context_oracle


LIMITATIONS = [
    "Rich V7 long-context feature arithmetic is the frozen inherited provider, not independently reimplemented here.",
    "Normal references, original-axis availability, Ridge populations/algebra, V12 append wiring and decision contexts are checked independently.",
    "Conditional feature validation permits max(1e-12, one float32 ULP) only for residual values; observed masks stay exact.",
    "Returned/scored matrices use exact frozen V12 full-prefix numerics after validation, not approximate Ridge-oracle features at HGB bin boundaries.",
    "Baseline15 input construction is independent but shares pandas rolling kernels; fitted IF.score_samples and HGB.predict_proba are inherited estimator inference.",
    "The supplied full segment is reset once after its gap. Cropped IF parity, streaming parity, fresh validation and model quality are not established by these helpers.",
]
IF_PARAMS = {"n_estimators": 200, "max_samples": 256, "contamination": "auto",
             "random_state": 20261016, "n_jobs": 1}
REF_NAMES = ("normal_median_", "normal_iqr_", "noise_floor_", "level_scale_",
             "normal_reference_counts_", "normal_delta_counts_", "positive_delta_counts_", "reference_supported_")


def _array_hash(a):
    a = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str(a.shape).encode()); h.update(a.dtype.str.encode()); h.update(a.tobytes())
    return h.hexdigest()


def _sensors(frame, channels):
    if not isinstance(frame, pd.DataFrame) or any(list(frame.columns).count(c) != 1 for c in channels):
        raise ValueError("Each fitted sensor column must occur exactly once")
    return frame.loc[:, channels].astype(float).replace([np.inf, -np.inf], np.nan)


def _gap(gap):
    if isinstance(gap, (bool, np.bool_)) or not isinstance(gap, (int, np.integer)) or gap < 0:
        raise ValueError("gap must be a nonnegative integer")
    return int(gap)


def _available(values, supported):
    """Independent exclusive prefix counts, including the original60-row cold start."""
    x = np.asarray(values, float)
    finite = np.isfinite(x)
    n, c = x.shape
    counts = np.vstack((np.zeros((1, c), np.int64), np.cumsum(finite, axis=0)))
    prior = counts[np.arange(n)] - counts[np.maximum(0, np.arange(n) - 60)]
    eligible = (finite & np.asarray(supported, bool)[None, :] & (prior >= 48)).sum(axis=1) >= math.ceil(.75 * c)
    eligible[:min(n, 60)] = False
    return eligible


def _conditional_state(generator):
    # The fitting algebra/normal population is independently validated by
    # audit_generator. Prediction uses those audited fitted parameters.
    return {"references": {key: getattr(generator, key) for key in REF_NAMES},
        "predictors": generator.conditional_predictor_indices_, "coef": generator.conditional_coef_,
        "intercept": generator.conditional_intercept_, "scale": generator.conditional_residual_scale_,
        "supported": bool(generator.conditional_supported_)}


def audit_generator(checks, name, generator, fit_frame, fit_labels):
    """Audit refs-only V12 generator on its exact allowed fit population.

    Return reference/conditional oracle state, original15-normal IF fit mask and
    count, IF semantic digest and limitations. The main auditor must separately
    bind this generator's IF to its saved teacher/original V6 artifact and prove
    that these supplied rows are precisely that artifact's earlier fit interval.
    """
    x = _sensors(fit_frame, generator.channels)
    y = np.asarray(fit_labels)
    if y.shape != (len(x),) or y.dtype.kind not in "biu" or not np.isin(y, [-1, 0, 1]).all():
        raise ValueError("Generator fit labels must be aligned integer -1/0/1")
    y = y.astype(np.int8, copy=False)
    refs = reference_oracle(x.to_numpy(float), y)
    for key in REF_NAMES:
        expected = refs[key]
        checks.array(name + ":independent_normal_reference:" + key, getattr(generator, key), expected,
                     floating=expected.dtype.kind == "f")
    conditional = conditional_audit.audit_conditional_training(checks, name, generator, x, y)
    checks.require(name + ":references_only_no_hgb", generator.model_ is None)
    checks.require(name + ":reference_only_marker", generator.reference_only_fit_ is True)
    checks.require(name + ":original_fit_length", generator.training_rows_ == len(x))
    checks.require(name + ":fit_label_hash", generator.reference_training_label_sha256_ == _array_hash(y))
    checks.tree(name + ":original_label_counts", generator.label_counts_,
        {"unknown": int((y < 0).sum()), "normal": int((y == 0).sum()), "positive": int((y == 1).sum())})
    expected_status = ("references_fitted" if refs["reference_supported_"].sum() >= math.ceil(.75 * len(generator.channels))
                       else "insufficient_normal_reference")
    checks.require(name + ":reference_support_status", generator.fit_status_ == expected_status)

    mask = if_audit.baseline_fit_mask_oracle(x, y, generator.channels)
    count = int(mask.sum())
    estimator = generator.baseline_estimator_
    digest = fitted_state_digest(estimator)
    checks.require(name + ":if_attachment_unchanged", digest == generator.baseline_state_hash_at_attachment_)
    checks.require(name + ":if_support_matches_original_known_normal_population", (estimator is not None) == (count >= 256))
    if estimator is not None:
        checks.require(name + ":direct_isolation_forest", type(estimator) is IsolationForest)
        checks.tree(name + ":fixed_if_hyperparameters", {k: estimator.get_params()[k] for k in IF_PARAMS}, IF_PARAMS)
        checks.require(name + ":if_original_fit_count", estimator._n_samples == count)
        checks.require(name + ":if_width", estimator.n_features_in_ == 4 * len(generator.channels))
        checks.require(name + ":if_max_samples", estimator.max_samples_ == min(256, count))
    if_audit.audit_if_frame(checks, name + ":training", generator, x)
    checks.require(name + ":if_unmutated_by_audit", fitted_state_digest(estimator) == digest)
    return {"references": refs, "conditional": conditional, "if_fit_mask": mask,
            "if_fit_rows": count, "if_digest": digest, "limitations": list(LIMITATIONS)}


def features_oracle(checks, name, generator, frame, gap=120):
    """Validate legacy wiring, then return EXACT inherited V12 numeric features.

    No production V16 features_gap/decision_matrix/score method is called.
    Full-prefix raw IF state is kept; bounded chunk checks in the inherited
    helper compare BOTH implementations under the same local input only.
    """
    gap = _gap(gap)
    x = _sensors(frame, generator.channels)
    n = len(x)
    width = len(generator.feature_names_)
    result = np.zeros((n, width), np.float32)
    available = np.zeros(n, bool)
    checks.require(name + ":v12_generator_type", type(generator) is BaselineEvidenceHGBScorer)
    checks.require(name + ":reference_only_has_no_hgb", generator.model_ is None)
    if n <= gap:
        return result, available
    tail = x.iloc[gap:].reset_index(drop=True)
    # Full V7 formula provider is inherited; all additional blocks are assembled
    # and validated independently before the full exact V12 provider is used.
    original = LongContextEventScorer(generator.channels)
    view = copy(generator)
    view.feature_names_ = list(original.feature_names_)
    inherited, inherited_available = LongContextEventScorer.features(view, tail)
    independent_available = _available(tail.to_numpy(float), generator.reference_supported_)
    checks.array(name + ":independent_original_axis_availability", inherited_available, independent_available)
    fitted = _conditional_state(generator)
    independent_conditional = conditional_audit.conditional_feature_oracle(tail.to_numpy(float), fitted)
    raw_if, independent_if, _, if_names = if_audit.baseline_feature_oracle(tail, generator.channels, generator.baseline_estimator_)
    checks.tree(name + ":baseline15_input_order", generator.expected_baseline_feature_names_, if_names)
    checks.tree(name + ":v12_feature_order", generator.feature_names_,
        original.feature_names_ + generator.conditional_feature_names_ + if_audit.IF_NAMES)
    checks.array(name + ":full_prefix_raw_if", generator.baseline_raw_scores(tail), raw_if, floating=True)

    # This static frozen-class call is the numeric provider. It is intentionally
    # distinct from any new V16 wrapper or an independently approximated matrix.
    exact, exact_available = BaselineEvidenceHGBScorer.features(generator, tail)
    checks.require(name + ":full_v12_matrix_dtype_shape", exact.dtype == np.float32 and exact.shape == (len(tail), width))
    base_end = len(original.feature_names_)
    conditional_end = base_end + 3 * len(generator.channels)
    checks.array(name + ":exact_inherited_long_feature_prefix", exact[:, :base_end], inherited)
    conditional_audit.check_added_features(checks, name + ":independent_conditional_values_and_masks",
        exact[:, base_end:conditional_end], independent_conditional)
    checks.array(name + ":exact_full_prefix_if_block", exact[:, conditional_end:], independent_if)
    checks.array(name + ":unchanged_v12_availability", exact_available, independent_available)
    # Reuse the prior independent append-wiring checks, explicitly under each
    # identical local input. This does not assert cropped/full-prefix IF parity.
    if_audit.audit_conditional_frame(checks, name + ":inherited_wiring", generator, tail, fitted)
    result[gap:] = exact
    available[gap:] = independent_available
    return result, available


def score_oracle(head, frame, v6, v8, gap=120, *, checks=None, name="score"):
    """Independent V16 request/support routing plus inherited fitted HGB call."""
    checks = Checks() if checks is None else checks
    gap = _gap(gap)
    sensors = _sensors(frame, head.channels)
    context = context_oracle(v6, v8)
    checks.require(name + ":context_axis", len(context["matrix"]) == len(sensors))
    scores = np.full(len(sensors), np.nan, float)
    if head.generator_ is None:
        checks.require(name + ":unfitted_head_has_no_classifier", head.model_ is None)
        return scores
    base, available = features_oracle(checks, name + ":features", head.generator_, sensors, gap)
    return score_matrix_oracle(head, base, available, v6, v8, checks=checks, name=name)


def score_matrix_oracle(head, baseX, available, v6, v8, *, checks=None, name="score"):
    """Score validated shared sensor features with independent fresh contexts.

    This supports the frozen continuous-sensor/per-block-context calibration
    case. The caller must obtain baseX from features_oracle once, then slice it
    and available without regenerating sensor history at a context boundary.
    """
    checks = Checks() if checks is None else checks
    base = np.asarray(baseX)
    available = np.asarray(available)
    width = len(head.base_feature_names_)
    checks.require(name + ":base_matrix", base.ndim == 2 and base.shape[1] == width
                   and base.dtype == np.float32 and np.isfinite(base).all())
    checks.require(name + ":available_mask", available.shape == (len(base),) and available.dtype.kind == "b")
    context = context_oracle(v6, v8)
    checks.require(name + ":context_axis", len(context["matrix"]) == len(base))
    scores = np.full(len(base), np.nan, float)
    eligible = available & context["active"]
    for kind in ("anchor", "recovery"):
        supported = head.request_support_[kind]["supported"]
        checks.require(name + ":support_boolean:" + kind, isinstance(supported, (bool, np.bool_)))
        if not supported:
            eligible &= ~context[kind + "_active"]
    if head.model_ is None or not eligible.any():
        return scores
    matrix = np.concatenate((base[eligible], context["matrix"][eligible]), axis=1)
    checks.tree(name + ":head_feature_order", head.feature_names_,
                head.base_feature_names_ + list(context["feature_names"]))
    classes = np.asarray(head.model_.classes_)
    positive = np.flatnonzero(classes == 1)
    checks.require(name + ":one_positive_class", classes.ndim == 1 and len(positive) == 1)
    probability = np.asarray(head.model_.predict_proba(matrix), float)
    checks.require(name + ":predict_proba_shape", probability.shape == (int(eligible.sum()), len(classes)))
    values = probability[:, positive[0]]
    finite = np.isfinite(values)
    checks.require(name + ":probability_range", np.all((values[finite] >= 0) & (values[finite] <= 1)))
    scores[np.flatnonzero(eligible)[finite]] = values[finite]
    return scores
