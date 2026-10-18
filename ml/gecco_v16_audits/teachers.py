"""Audit supplied inner teachers without source I/O or any estimator refit.

Independent pieces: geometry, normal populations, baseline15 features, local
features/scales, masks, scalar alarm paths, V8 references/weights/certification.
Inherited pieces are stated explicitly: frozen V5 shape/V8 feature formulas,
fitted sklearn predictions, and frozen legacy calibration search. This module
does not import V16 production teacher/model/decision code. Parent audit owns
artifact hashes and the receipts establishing which inputs the fits consumed.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

# Initialize the frozen legacy import environment, without calling its runtime.
from ml.gecco_v6 import runtime_v4 as _legacy_bootstrap
from ml.gecco_v2.alarm_policy import select as inherited_baseline_select
from ml.gecco_v6.source_suppression import calibrate as inherited_suppression_select
from ml.gecco_v6.source_joint_calibration import calibrate as inherited_joint_select
from ml.gecco_v7.calibration_certified import calibrate as inherited_v8_select
from ml.gecco_v6.unknown_label_metrics import comparison, stats
from ml.gecco_v7_audits import replay_certified as certified
from ml.gecco_v7_audits import replay_delayed as delayed
from ml.gecco_v8_audits import replay as v8_audit
from ml.gecco_v12_audits.replay import baseline_input_oracle, baseline_fit_mask_oracle


VERSION = "v16_inner_v6_run04_v8_teacher_v1"
GAP = 120
LOCAL_KEYS = ("level", "jump", "sustained")
HGB_PARAMETERS = dict(max_iter=100, max_leaf_nodes=15, max_depth=None,
    min_samples_leaf=20, learning_rate=.08, l2_regularization=1, max_bins=63,
    early_stopping=False, random_state=20261016)
IF_PARAMETERS = dict(n_estimators=200, max_samples=256, contamination="auto",
                     n_jobs=1, random_state=20261016)
SHAPE_PARAMETERS = dict(n_estimators=160, max_depth=12, min_samples_leaf=8,
                       max_features=.7, n_jobs=1, random_state=20261016)


def _array(checks, name, actual, expected, floating=False):
    checks.require(name + ":verified", checks.array(name, actual, expected, floating=floating))


def _tree(checks, name, actual, expected):
    checks.require(name + ":verified", checks.tree(name, actual, expected))


def _clean(frame, channels):
    if not isinstance(frame, pd.DataFrame) or any(list(frame.columns).count(c) != 1 for c in channels):
        raise ValueError("Each configured sensor must occur exactly once")
    return frame.loc[:, channels].astype(float).replace([np.inf, -np.inf], np.nan).reset_index(drop=True)


def _labels(y, n):
    y = np.asarray(y)
    if y.shape != (n,) or y.dtype.kind not in "iu" or not np.isin(y, [-1, 0, 1]).all():
        raise ValueError("Original aligned integer ternary labels required")
    return y.astype(np.int8, copy=False)


def normal_windows(labels, width):
    """Independent prefix-count oracle, without compressing unknown labels."""
    good = np.asarray(labels) == 0
    count = np.r_[0, np.cumsum(good, dtype=np.int64)]
    mask = np.zeros(len(good), bool)
    if len(good) >= width:
        mask[width - 1:] = count[width:] - count[:-width] == width
    return mask


def local_raw(frame, floors):
    """Independent pandas implementation of fixed V6 channel components."""
    current = frame.to_numpy(float)
    prior = frame.shift(1).rolling(60, min_periods=30)
    center = prior.median().to_numpy()
    spread = (prior.quantile(.75) - prior.quantile(.25)).to_numpy() / 1.349
    scale = np.maximum(spread, np.asarray(floors)[None, :])
    noise = frame.diff().abs().shift(1).rolling(15, min_periods=8).quantile(.75).to_numpy()
    noise = np.maximum(noise, np.asarray(floors)[None, :])
    observed = np.isfinite(current) & np.isfinite(center) & np.isfinite(scale)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        residual = np.clip((current - center) / scale, -1e6, 1e6)
        residual[~observed] = np.nan
        level = np.abs(residual)
        lag1 = np.abs(current - frame.shift(1).to_numpy()) / noise
        lag5 = np.abs(current - frame.shift(5).to_numpy()) / (noise * np.sqrt(5))
        jump = np.clip(np.maximum(lag1, lag5), 0, 1e6)
        jump[~observed] = np.nan
    bounded = pd.DataFrame(np.clip(residual, -8, 8))
    short = np.abs(bounded.rolling(5, min_periods=5).sum().to_numpy()) / np.sqrt(5)
    long = np.abs(bounded.rolling(15, min_periods=15).sum().to_numpy()) / np.sqrt(15)
    return {"level": level, "jump": jump, "sustained": np.fmax(short, long)}


def _floor(frame, mask, *, minimum):
    a, delta = frame.to_numpy(), frame.diff().abs().to_numpy()
    floors = np.full(frame.shape[1], np.nan)
    counts = np.zeros(frame.shape[1], int)
    for j in range(frame.shape[1]):
        values = delta[mask, j]
        values = values[np.isfinite(values)]
        counts[j] = len(values)
        if len(values) < minimum:
            continue
        positive = values[values > 0]
        observed = a[mask, j]; observed = observed[np.isfinite(observed)]
        epsilon = max(float(np.median(np.abs(observed))) * 1e-12, 1e-12) if len(observed) else 1e-12
        floors[j] = max(float(np.quantile(positive, .75)) if len(positive) else 0., epsilon)
    return floors, counts


def audit_local_training(checks, name, model, frame, labels):
    mask61, mask75 = normal_windows(labels, 61), normal_windows(labels, 75)
    _array(checks, name + ":normal61", model.normal_floor_window_mask_, mask61)
    expected_floor, counts = _floor(frame, mask61, minimum=64)
    _array(checks, name + ":normal_floor", model.noise_floor_, expected_floor, True)
    _array(checks, name + ":floor_counts", model.floor_fit_counts_, counts)
    raw = local_raw(frame, expected_floor)
    trained = []
    for key in LOCAL_KEYS:
        mask = mask75 if key == "sustained" else mask61
        _array(checks, name + ":tail_mask:" + key, model.normal_tail_window_masks_[key], mask)
        scale = np.full(frame.shape[1], np.nan); count = np.zeros(frame.shape[1], int)
        for j in range(frame.shape[1]):
            values = raw[key][mask, j]; values = values[np.isfinite(values)]
            count[j] = len(values)
            if len(values) >= 64:
                scale[j] = max(float(np.quantile(values, .995)), 1.)
        _array(checks, name + ":tail_scale:" + key, model.channel_tail_scales_[key], scale, True)
        _array(checks, name + ":tail_count:" + key, model.tail_fit_counts_[key], count)
        trained.append(int(np.isfinite(scale).sum()))
    expected = "fitted" if min(trained) >= math.ceil(frame.shape[1] / 2) else "insufficient_normal_training"
    checks.require(name + ":fit_status", model.fit_status_ == expected)
    checks.require(name + ":fit_rows", model.fit_rows_ == int(mask61.sum()))
    checks.require(name + ":fitted_flag", model.is_fitted_ is True)
    return {"normal61_rows": int(mask61.sum()), "normal75_rows": int(mask75.sum()),
            "unknown_excluded_from_normal_windows": True, "independent_local_scales": True}


def _params(checks, name, model, expected):
    actual = model.get_params(deep=False)
    _tree(checks, name, {k: actual[k] for k in expected}, expected)


def audit_training_models(checks, name, models, frame, labels, channels):
    """No refit: independent normal populations and V8 weight accounting."""
    recovery, local = models["recovery"], models["local"]
    for key, model in (("recovery", recovery), ("local", local)):
        _tree(checks, name + ":channels:" + key, list(model.channels), channels)
    checks.require(name + ":shape_invariant", recovery.config_id == "shape_invariant")
    fit_mask = baseline_fit_mask_oracle(frame, labels, channels)
    count = int(fit_mask.sum())
    checks.require(name + ":baseline_normal15_fit_count", recovery.baseline_fit_rows_ == count)
    checks.require(name + ":baseline_presence", (recovery.baseline_ is not None) == (count >= 256))
    estimator = recovery.baseline_
    if estimator is not None:
        _params(checks, name + ":if_parameters", estimator, IF_PARAMETERS)
        checks.require(name + ":if_feature_width", estimator.n_features_in_ == 4 * len(channels))
        checks.require(name + ":if_estimator_count", len(estimator.estimators_) == 200)
        checks.require(name + ":if_subsample_size", estimator.max_samples_ == 256)
        for i, sample in enumerate(estimator.estimators_samples_):
            checks.require(name + f":if_sample_indices:{i}", len(sample) == 256 and
                           np.all((np.asarray(sample) >= 0) & (np.asarray(sample) < count)))
    normal61 = normal_windows(labels, 61)
    _array(checks, name + ":shape_normal61", recovery.normal_scale_window_mask_, normal61)
    if normal61.sum() >= 100:
        floor, _ = _floor(frame, normal61, minimum=0)
        _array(checks, name + ":shape_normal_floor", recovery.noise_floor_, floor, True)
        # Frozen V5 feature formula is inherited, not a new independent oracle.
        _, available = recovery.features(frame)
        eligible = np.asarray(available, bool) & (labels >= 0)
        starts = np.flatnonzero((labels == 1) & np.r_[True, labels[:-1] != 1])
        ends = np.flatnonzero((labels == 1) & np.r_[labels[1:] != 1, True]) + 1
        events = sum(bool(eligible[a:b].any()) for a, b in zip(starts, ends))
        checks.require(name + ":shape_fit_rows", recovery.fit_rows_ == int(eligible.sum()))
        checks.require(name + ":shape_fit_events", recovery.fit_events_ == events)
        fitted = eligible.sum() >= 100 and events > 0 and bool((eligible & (labels == 0)).any())
        checks.require(name + ":shape_classifier_presence", (recovery.shape_ is not None) == fitted)
        checks.require(name + ":shape_fit_status", recovery.fit_status_ == ("fitted" if fitted else "one_class_training"))
    else:
        checks.require(name + ":shape_unsupported", recovery.shape_ is None and
                       recovery.fit_status_ == "insufficient_normal_training")
    if recovery.shape_ is not None:
        _params(checks, name + ":shape_parameters", recovery.shape_, SHAPE_PARAMETERS)
    local_summary = audit_local_training(checks, name + ":local", local, frame, labels)
    if "long" in models:
        model = models["long"]
        _tree(checks, name + ":long_channels", list(model.channels), channels)
        start = len(checks.records)
        accounting = v8_audit.audit_training(checks, name + ":v8", model, frame, labels)
        checks.require(name + ":all_v8_training_oracles", all(r["passed"] for r in checks.records[start:]))
        if model.model_ is not None:
            _params(checks, name + ":hgb_parameters", model.model_, HGB_PARAMETERS)
            _array(checks, name + ":hgb_classes", model.model_.classes_, [0, 1])
        checks.require(name + ":hgb_presence", (model.model_ is not None) == (model.fit_status_ == "fitted"))
        long_summary = {"eligible_rows": int(accounting["eligible"].sum()),
                        "positive_segments": accounting["eligible_segments"],
                        "reference_and_weight_oracle": True}
    else:
        long_summary = None
    return {"if_known_normal_15row_windows": count, "if_model_present": estimator is not None,
            "if_fit_values_proven_by_refit": False, "shape_feature_formula": "inherited_frozen_V5",
            "local": local_summary, "v8": long_summary}


def _long_available(frame, supported):
    finite = np.isfinite(frame.to_numpy(float))
    counts = np.vstack([np.zeros((1, frame.shape[1]), int), np.cumsum(finite, axis=0)])
    index = np.arange(len(frame))
    prior = counts[index] - counts[np.maximum(index - 60, 0)]
    available = (finite & np.asarray(supported)[None, :] & (prior >= 48)).sum(axis=1) >= math.ceil(.75 * frame.shape[1])
    available[:min(60, len(frame))] = False
    return available


def raw_scores(checks, name, models, sensors):
    """Score saved estimators after the gap, with independent IF/local inputs."""
    skipped = min(GAP, len(sensors)); tail = sensors.iloc[skipped:].reset_index(drop=True)
    result = {k: np.full(len(sensors), np.nan) for k in ("baseline_score", "shape_raw", *LOCAL_KEYS, "long_context")}
    if not len(tail):
        return result
    recovery, local = models["recovery"], models["local"]
    matrix, available, _ = baseline_input_oracle(tail, recovery.channels)
    if recovery.baseline_ is not None and available.any():
        values = -np.asarray(recovery.baseline_.score_samples(matrix[available]), float)
        result["baseline_score"][skipped + np.flatnonzero(available)] = values
    if recovery.shape_ is not None:
        matrix, available = recovery.features(tail)
        if available.any():
            result["shape_raw"][skipped + np.flatnonzero(available)] = recovery.shape_.predict_proba(matrix[available])[:, 1]
    raw = local_raw(tail, local.noise_floor_)
    for key in LOCAL_KEYS:
        normalized = raw[key] / local.channel_tail_scales_[key][None, :]
        finite = np.isfinite(normalized)
        enough = finite.sum(axis=1) >= math.ceil(tail.shape[1] / 2)
        score = np.max(np.where(finite, normalized, -np.inf), axis=1)
        score[~enough] = np.nan
        result[key][skipped:] = score
    if "long" in models:
        model = models["long"]
        if model.model_ is not None:
            # Reference/availability oracle is independent; the frozen V8
            # feature formulas and sklearn classifier execution are inherited.
            matrix, available = model.features(tail)
            expected = _long_available(tail, model.reference_supported_)
            _array(checks, name + ":long_availability", available, expected)
            if available.any():
                column = int(np.flatnonzero(model.model_.classes_ == 1)[0])
                result["long_context"][skipped + np.flatnonzero(available)] = model.model_.predict_proba(matrix[available])[:, column]
    return result


def scalar_guard(base, shape, selected):
    out = np.asarray(base, np.int8).copy()
    if selected["decision"] == "baseline":
        return out
    width, votes = {"instant": (1, 1), "2of3": (3, 2), "3of5": (5, 3)}[selected["policy"]]
    threshold = selected["threshold"]; kept = False
    for i, value in enumerate(base):
        if value != 1:
            kept = False
            continue
        window = np.asarray(shape[max(0, i - width + 1):i + 1])
        known = len(window) == width and np.isfinite(window).all()
        if not known or (window >= threshold).sum() >= votes:
            kept = True
        out[i] = int(kept)
    return out


def corroborated(raw, threshold):
    result = {k: np.asarray(raw[k], float).copy() for k in ("shape_raw", *LOCAL_KEYS)}
    if threshold is None:
        return {k: np.full_like(v, np.nan) for k, v in result.items()}
    jump = raw["jump"]
    for key in ("level", "sustained"):
        result[key][np.isfinite(jump) & (jump <= 1)] = 0
        result[key][~np.isfinite(jump)] = np.nan
    shape = raw["shape_raw"]
    for key in LOCAL_KEYS:
        result[key][np.isfinite(shape) & (shape < threshold)] = 0
        result[key][~np.isfinite(shape)] = np.nan
    return result


def scalar_joint(base, guarded, scores, selected):
    out = np.asarray(guarded if selected["seed"] == "guarded" else base, np.int8).copy()
    if selected["rescue"] is None:
        return out
    source = scores[selected["rescue"]]; threshold = selected["threshold"]
    width, votes = {"instant": (1, 1), "2of3": (3, 2), "3of5": (5, 3)}[selected["policy"]]
    for i in range(width - 1, len(out)):
        window = source[i - width + 1:i + 1]
        if base[i] >= 0 and np.isfinite(window).all() and source[i] >= threshold and (window >= threshold).sum() >= votes:
            out[i] = 1
    return out


def prediction_table(raw, v6, v8, index):
    baseline = np.full(len(index), -1, np.int8)
    finite = np.isfinite(raw["baseline_score"])
    baseline[finite] = (raw["baseline_score"][finite] >= v6["prior_bundle"]["baseline_threshold"]).astype(np.int8)
    local = np.column_stack([raw[k] for k in LOCAL_KEYS])
    guarded_shape = np.where(np.isfinite(local).all(axis=1) & (local <= 1).all(axis=1), raw["shape_raw"], np.nan)
    guarded = scalar_guard(baseline, guarded_shape, v6["guard_selected"])
    rescue = corroborated(raw, v6["shape_support_threshold"])
    reference = scalar_joint(baseline, guarded, rescue, v6["selected"])
    gate, rescue_long = delayed.independent_masks(local, raw["long_context"])
    prediction, _ = delayed.scalar_prediction(reference, raw["long_context"], rescue_long, v8["selected"])
    return pd.DataFrame({**raw, "guarded_shape": guarded_shape,
        **{"rescue__" + k: value for k, value in rescue.items()},
        "baseline_prediction": baseline, "guarded_prediction": guarded,
        "reference_prediction": reference, "prediction": prediction,
        "available": reference >= 0, "ignored_gap": np.arange(len(index)) < min(GAP, len(index)),
        "guarded_long_context": gate, "rescue_long_context": rescue_long,
        "baseline": baseline, "v6": reference, "v8": prediction}, index=index)


def _compare_table(checks, name, actual, expected):
    checks.require(name + ":row_count", isinstance(actual, pd.DataFrame) and len(actual) == len(expected))
    for column in expected:
        checks.require(name + ":column:" + column, column in actual)
        _array(checks, name + ":" + column, actual[column], expected[column], expected[column].dtype.kind == "f")


def audit_teacher(checks, name, saved_teacher, inner_fit_frame, inner_y,
                  cal_frames, cal_y, cal_starts, forecast_frame, saved_forecast):
    """Audit one supplied teacher; parent owns all filesystem and lineage checks."""
    teacher = saved_teacher
    checks.require(name + ":version", teacher.get("version") == VERSION)
    metadata = teacher["training_metadata"]; channels = list(metadata["channels"])
    checks.require(name + ":unique_channels", bool(channels) and len(channels) == len(set(channels)))
    fit = _clean(inner_fit_frame, channels); y = _labels(inner_y, len(fit))
    checks.require(name + ":four_past_blocks", len(cal_frames) == len(cal_y) == len(cal_starts) == 4)
    frames = [_clean(f, channels) for f in cal_frames]
    targets = [_labels(t, len(f)) for t, f in zip(cal_y, frames)]
    expected_starts = (np.r_[len(fit), len(fit) + np.cumsum([len(f) for f in frames])[:-1]]).tolist()
    _tree(checks, name + ":adjacent_supplied_calibration", list(cal_starts), expected_starts)
    expected_metadata = {"version": VERSION, "channels": channels, "fit_rows": len(fit),
        "fit_range": [0, len(fit)], "max_fit_index": len(fit) - 1,
        "calibration_starts": expected_starts, "calibration_rows": [len(f) for f in frames],
        "calibration_end_exclusive": len(fit) + sum(len(f) for f in frames),
        "max_calibration_index": len(fit) + sum(len(f) for f in frames) - 1,
        "calibration_gap_samples_each": GAP, "calibration_context": "four_separate_resets",
        "sample_seconds": 60, "outer_artifacts_used": False, "forecast_scored_during_fit": False,
        "fit_label_counts": {"unknown": int((y < 0).sum()), "normal": int((y == 0).sum()), "positive": int((y == 1).sum())},
        "calibration_label_counts": [{"unknown": int((t < 0).sum()), "normal": int((t == 0).sum()), "positive": int((t == 1).sum())} for t in targets]}
    _tree(checks, name + ":past_geometry", {k: metadata.get(k) for k in expected_metadata}, expected_metadata)
    models = teacher["training_models"]
    before = certified.fitted_state_digest(models)
    training = audit_training_models(checks, name + ":fit", models, fit, y, channels)
    _tree(checks, name + ":fit_status_metadata", metadata["fit_status"], {k: m.fit_status_ for k, m in models.items()})
    summary = {"name": name, "status": teacher["status"], "supported": teacher["supported"],
        "training": training, "fit_rows": len(fit), "calibration_rows_replayed": 0, "forecast_rows_replayed": 0,
        "no_model_refit": True, "no_v16_production_forecaster_called": True,
        "independent_baseline_inputs_local_features_and_scalar_policies": True,
        "inherited_frozen_shape_and_long_feature_formulas": True,
        "calibration_search_scope": "recomputed using frozen V2/V6/V7 selectors; V8 certificate and scalar paths independently audited",
        "fit_ownership_scope": "normal masks/counts/parameters and supplied past geometry checked; actual fitted-input ownership additionally requires parent lineage receipts; no IF refit proof"}
    if models["recovery"].baseline_ is None:
        checks.require(name + ":missing_if_status", teacher["supported"] is False and teacher["status"] == "unsupported_missing_baseline_if")
        checks.require(name + ":no_calibration_without_if", not teacher["calibration_data"])
    else:
        raw_blocks = [raw_scores(checks, name + f":cal:{i}", models, f) for i, f in enumerate(frames)]
        all_y = np.concatenate(targets); raw_baseline = np.concatenate([r["baseline_score"] for r in raw_blocks])
        known_finite = (all_y >= 0) & np.isfinite(raw_baseline)
        normal_finite = (all_y == 0) & np.isfinite(raw_baseline)
        checks.require(name + ":finite_known_count", metadata["finite_known_baseline_calibration_rows"] == int(known_finite.sum()))
        checks.require(name + ":finite_normal_count", metadata["finite_normal_baseline_calibration_rows"] == int(normal_finite.sum()))
        checks.require(name + ":four_saved_calibration_blocks", len(teacher["calibration_data"]) == 4)
        for i, (raw, target, start, actual) in enumerate(zip(raw_blocks, targets, expected_starts, teacher["calibration_data"])):
            expected = {"sample_index": np.arange(start, start + len(target)), "label": target,
                        **{k: raw[k] for k in ("baseline_score", "shape_raw", *LOCAL_KEYS)}}
            _compare_table(checks, name + f":raw_calibration:{i}", actual, pd.DataFrame(expected))
        summary["calibration_rows_replayed"] = sum(len(f) for f in frames)
        if not known_finite.any():
            expected_status = "unsupported_no_finite_known_calibration"
        elif not normal_finite.any():
            expected_status = "unsupported_no_observed_normal_calibration"
        else:
            expected_status = None
        baseline_choice = None
        if expected_status is None:
            try:
                baseline_choice, baseline_trials = inherited_baseline_select(all_y == 1, np.where(all_y >= 0, raw_baseline, np.nan), baseline=True)
            except ValueError as error:
                expected_status = "unsupported_baseline_calibration"
                checks.require(name + ":selection_failure_reason", metadata.get("baseline_calibration_error") == str(error))
        if expected_status is not None:
            checks.require(name + ":unsupported_calibration_status", teacher["supported"] is False and teacher["status"] == expected_status)
        else:
            checks.require(name + ":supported_status", teacher["supported"] is True and teacher["status"] == "ready")
            v6, v8 = teacher["v6_bundle"], teacher["v8_bundle"]
            checks.require(name + ":same_v6_teacher_object", v8["reference_bundle"] is v6)
            checks.require(name + ":same_fitted_models", v6["prior_bundle"]["model"] is models["recovery"] and
                           v6["local_model"] is models["local"] and v8["long_model"] is models["long"])
            for kind, bundle in (("v6", v6), ("v8", v8)):
                for field in ("max_fit_index", "max_calibration_index", "sample_seconds"):
                    checks.require(name + f":{kind}:{field}", bundle[field] == metadata[field])
            checks.require(name + ":v8_version_gap", v8["version"] == "v8_onset_hgb_temporally_certified_120s" and v8["gap_samples"] == GAP)
            _tree(checks, name + ":baseline_selected", metadata["baseline_selected"], baseline_choice)
            _tree(checks, name + ":baseline_trials", teacher["trials"]["baseline"], baseline_trials)
            checks.require(name + ":baseline_threshold", v6["prior_bundle"]["baseline_threshold"] == baseline_choice["threshold"] and
                           v6["prior_bundle"]["baseline_policy"] == "instant")
            guard_blocks, blocks = [], []
            for raw, target, start in zip(raw_blocks, targets, expected_starts):
                base = np.full(len(target), -1, np.int8); finite = np.isfinite(raw["baseline_score"])
                base[finite] = (raw["baseline_score"][finite] >= baseline_choice["threshold"]).astype(np.int8)
                local = np.column_stack([raw[k] for k in LOCAL_KEYS])
                gate = np.where(np.isfinite(local).all(axis=1) & (local <= 1).all(axis=1), raw["shape_raw"], np.nan)
                guard_blocks.append({"labels": target, "scores": gate, "baseline_predictions": base, "source_start": start})
                blocks.append({"labels": target, "baseline": base, "guarded": base.copy(),
                               "scores": {k: raw[k] for k in ("shape_raw", *LOCAL_KEYS)}, "source_start": start})
            guard, guard_trials = inherited_suppression_select(guard_blocks)
            _tree(checks, name + ":suppression_selected", v6["guard_selected"], guard)
            _tree(checks, name + ":suppression_trials", teacher["trials"]["suppression"], guard_trials)
            normal_shape = np.concatenate([b["scores"]["shape_raw"][(b["labels"] == 0) & (b["baseline"] >= 0) & np.isfinite(b["scores"]["shape_raw"])] for b in blocks])
            shape_threshold = max(float(np.quantile(normal_shape, .99)), 1e-6) if len(normal_shape) >= 5760 else None
            _tree(checks, name + ":shape_q99", v6["shape_support_threshold"], shape_threshold)
            for block, gate in zip(blocks, guard_blocks):
                block["guarded"] = scalar_guard(block["baseline"], gate["scores"], guard)
                block["scores"] = corroborated(block["scores"], shape_threshold)
            joint, joint_trials = inherited_joint_select(blocks)
            _tree(checks, name + ":joint_selected", v6["selected"], joint)
            _tree(checks, name + ":joint_trials", teacher["trials"]["joint"], joint_trials)
            v8_blocks = []
            for block, raw in zip(blocks, raw_blocks):
                reference = scalar_joint(block["baseline"], block["guarded"], block["scores"], joint)
                _, rescue = delayed.independent_masks(np.column_stack([raw[k] for k in LOCAL_KEYS]), raw["long_context"])
                v8_blocks.append({"labels": block["labels"], "reference": reference, "long_scores": raw["long_context"],
                                  "rescue_scores": rescue, "source_start": block["source_start"]})
            selected, trials = inherited_v8_select(v8_blocks, cadence_seconds=60)
            _tree(checks, name + ":v8_recomputed_selection", v8["selected"], selected)
            _tree(checks, name + ":v8_recomputed_trials", teacher["trials"]["v8"], trials)
            cal_tables = []
            for i, (raw, target, start, actual) in enumerate(zip(raw_blocks, targets, expected_starts, teacher["calibration_data"])):
                table = prediction_table(raw, v6, v8, pd.RangeIndex(len(target)))
                selected_columns = ["baseline", "guarded_shape", "v6", "long_context", "guarded_long_context", "rescue_long_context", "v8"] + ["rescue__" + k for k in ("shape_raw", *LOCAL_KEYS)]
                expected = table[selected_columns].copy(); expected["guarded"] = table.guarded_prediction
                _compare_table(checks, name + f":full_calibration:{i}", actual, expected)
                cal_tables.append(pd.DataFrame({"sample_index": np.arange(start, start + len(target)), "label": target,
                    "reference": table.v6, "candidate": table.v8, **{k: table[k] for k in ("long_context", "guarded_long_context", "rescue_long_context", *LOCAL_KEYS)}}))
            cal = pd.concat(cal_tables, ignore_index=True)
            bounds = [*expected_starts, expected_metadata["calibration_end_exclusive"]]
            record_start = len(checks.records)
            v8_audit._certified_calibration(checks, name + ":independent_v8_certificate", cal, cal, cal, bounds, selected, comparison, stats)
            v8_audit._trial_selection(checks, name + ":independent_v8_trial_rank", pd.DataFrame(trials), selected)
            checks.require(name + ":all_independent_v8_calibration_checks", all(r["passed"] for r in checks.records[record_start:]))
            forecast = _clean(forecast_frame, channels)
            raw = raw_scores(checks, name + ":forecast", models, forecast)
            expected = prediction_table(raw, v6, v8, forecast_frame.index)
            _compare_table(checks, name + ":forecast", saved_forecast, expected)
            summary["forecast_rows_replayed"] = len(forecast)
    if teacher["supported"] is not True:
        checks.require(name + ":no_unsupported_forecast", saved_forecast is None or
                       (isinstance(saved_forecast, pd.DataFrame) and len(saved_forecast) == 0))
        checks.require(name + ":no_unsupported_bundles", teacher["v6_bundle"] is None and teacher["v8_bundle"] is None)
        checks.require(name + ":no_long_fit_without_calibration", "long" not in models)
    after = certified.fitted_state_digest(models)
    checks.require(name + ":fitted_state_unchanged", before == after)
    summary.update(fitted_state_sha256=before, fitted_state_unchanged=True, passed=True)
    return summary
