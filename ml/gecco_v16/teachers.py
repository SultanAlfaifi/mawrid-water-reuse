"""Past-only V6/V8 teachers for the frozen V16 experiment; no source I/O.

The caller owns chronological slicing, persistence and the freeze BEFORE any
forecast call. All four inner calibration blocks reset independently, including
GECCO2019. Only explicitly supplied sensors and separate ternary labels enter
fit. A teacher with no fitted IF or no usable baseline calibration is unsupported;
``predict_teacher`` then raises rather than inventing normal predictions.

These are batch learning artifacts, not a streaming or deployment interface.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# The frozen runtime supplies the legacy-module bootstrap its dependencies need.
from ml.gecco_v6 import runtime_v4 as v6_runtime
from ml.gecco_v2.alarm_policy import select as select_baseline, predict as baseline_predict
from ml.gecco_v6.partially_labeled_model import PartiallyLabeledRecoveryDetector
from ml.gecco_v6.local_change import LocalChangeScorer
from ml.gecco_v6.guarded_suppression import guarded_shape
from ml.gecco_v6.corroborated_rescue import fit_shape_reference, corroborated_scores
from ml.gecco_v6.source_suppression import calibrate as calibrate_guard, predict as predict_guard
from ml.gecco_v6.source_joint_calibration import calibrate as calibrate_joint, predict as predict_joint
from ml.gecco_v7.calibration_certified import calibrate as calibrate_v8, predict as predict_v8
from ml.gecco_v7.evidence import separate_scores
from ml.gecco_v8.onset import OnsetWeightedHGBScorer
from ml.gecco_v8.runtime import predict_frame as predict_v8_frame


GAP_SAMPLES = 120
CADENCE_SECONDS = 60
V8_VERSION = "v8_onset_hgb_temporally_certified_120s"
TEACHER_VERSION = "v16_inner_v6_run04_v8_teacher_v1"
LOCAL_KEYS = ("level", "jump", "sustained")


def _channels(channels):
    if isinstance(channels, (str, bytes)):
        raise ValueError("channels must be an ordered sequence of unique names")
    result = list(channels)
    if not result or any(not isinstance(c, str) or not c for c in result) or len(set(result)) != len(result):
        raise ValueError("channels must be nonempty, unique strings")
    return result


def _sensors(frame, channels):
    if not isinstance(frame, pd.DataFrame) or any(list(frame.columns).count(c) != 1 for c in channels):
        raise ValueError("Every configured sensor must occur exactly once")
    return frame.loc[:, channels].astype(float).copy()


def _labels(labels, length):
    values = np.asarray(labels)
    if values.shape != (length,) or values.dtype.kind not in "iu" or not np.isin(values, [-1, 0, 1]).all():
        raise ValueError("Labels must be same-length integer -1/0/1, not Boolean")
    return values.astype(np.int8, copy=True)


def _validate_fit(fit_frame, fit_labels, cal_frames, cal_labels, cal_starts, channels):
    names = _channels(channels)
    fit = _sensors(fit_frame, names)
    if not len(fit):
        raise ValueError("Inner fit must be nonempty")
    y = _labels(fit_labels, len(fit))
    if len(cal_frames) != 4 or len(cal_labels) != 4 or len(cal_starts) != 4:
        raise ValueError("Exactly four inner calibration blocks are required")
    frames, labels, starts = [], [], []
    expected = len(fit)
    for frame, target, start in zip(cal_frames, cal_labels, cal_starts):
        if isinstance(start, (bool, np.bool_)) or not isinstance(start, (int, np.integer)) or start != expected:
            raise ValueError("Calibration starts must be adjacent integers following the inner fit")
        sensors = _sensors(frame, names)
        if not len(sensors):
            raise ValueError("Calibration blocks must remain nonempty")
        frames.append(sensors)
        labels.append(_labels(target, len(sensors)))
        starts.append(int(start))
        expected += len(sensors)
    return names, fit, y, frames, labels, starts


def _pad(values, skipped, length):
    result = np.asarray(values, dtype=float)
    if result.shape != (length - skipped,):
        raise ValueError("Teacher components must match their original sensor axis")
    return np.r_[np.full(skipped, np.nan), result]


def _components_gap(model, local, frame):
    skipped = min(GAP_SAMPLES, len(frame))
    tail = frame.iloc[skipped:].reset_index(drop=True)
    if not len(tail):
        return {k: np.full(len(frame), np.nan) for k in ("baseline_score", "shape_raw", *LOCAL_KEYS)}
    parent = model.score_components(tail)
    components = local.score_components(tail)
    raw = {"baseline_score": parent["baseline"], "shape_raw": parent["shape"],
           **{k: components[k] for k in LOCAL_KEYS}}
    return {k: _pad(v, skipped, len(frame)) for k, v in raw.items()}


def _long_gap(model, frame):
    skipped = min(GAP_SAMPLES, len(frame))
    if skipped == len(frame):
        return np.full(len(frame), np.nan)
    return _pad(model.score_components(frame.iloc[skipped:].reset_index(drop=True))["long_context"],
                skipped, len(frame))


def fit_teacher(fit_frame, fit_labels, cal_frames, cal_labels, cal_starts, *, channels):
    """Fit on inner fit, select on four later inner blocks; never score forecast.

    Returns ``status``, ``supported``, ``v6_bundle``, ``v8_bundle``,
    ``training_models``, ``training_metadata``, four ``calibration_data`` frames,
    and ``trials`` grouped by baseline/suppression/joint/v8. Fitted objects are
    shared between these dictionary entries, not separately copied. Temporary
    feature matrices are not returned. All labels remain on the original axis.
    """
    names, fit, y, frames, labels, starts = _validate_fit(
        fit_frame, fit_labels, cal_frames, cal_labels, cal_starts, channels)
    metadata = {"version": TEACHER_VERSION, "channels": names, "fit_rows": len(fit),
        "fit_range": [0, len(fit)], "max_fit_index": len(fit) - 1,
        "calibration_starts": starts, "calibration_rows": [len(f) for f in frames],
        "calibration_end_exclusive": starts[-1] + len(frames[-1]),
        "max_calibration_index": starts[-1] + len(frames[-1]) - 1,
        "calibration_gap_samples_each": GAP_SAMPLES, "calibration_context": "four_separate_resets",
        "sample_seconds": CADENCE_SECONDS,
        "fit_label_counts": {"unknown": int((y < 0).sum()), "normal": int((y == 0).sum()),
                             "positive": int((y == 1).sum())},
        "calibration_label_counts": [{"unknown": int((t < 0).sum()), "normal": int((t == 0).sum()),
                                      "positive": int((t == 1).sum())} for t in labels],
        "outer_artifacts_used": False, "forecast_scored_during_fit": False}
    result = {"version": TEACHER_VERSION, "status": "fitting", "supported": False,
              "v6_bundle": None, "v8_bundle": None, "training_models": {},
              "training_metadata": metadata, "calibration_data": [],
              "trials": {k: [] for k in ("baseline", "suppression", "joint", "v8")}}
    model = PartiallyLabeledRecoveryDetector("shape_invariant", names).fit(fit, y)
    local = LocalChangeScorer(names).fit(fit, y != 0)
    result["training_models"].update(recovery=model, local=local)
    metadata["fit_status"] = {"recovery": model.fit_status_, "local": local.fit_status_}
    if model.baseline_ is None:
        result["status"] = "unsupported_missing_baseline_if"
        return result

    raw_blocks = [_components_gap(model, local, frame) for frame in frames]
    cal_y = np.concatenate(labels)
    cal_score = np.concatenate([b["baseline_score"] for b in raw_blocks])
    known_finite = (cal_y >= 0) & np.isfinite(cal_score)
    metadata["finite_known_baseline_calibration_rows"] = int(known_finite.sum())
    metadata["finite_normal_baseline_calibration_rows"] = int(((cal_y == 0) & np.isfinite(cal_score)).sum())
    # Preserve scores even for unsupported folds; never erase sensor availability
    # because a label is unknown. Only the selection argument below is masked.
    result["calibration_data"] = [pd.DataFrame({
        "sample_index": np.arange(start, start + len(t)), "label": t, **raw})
        for start, t, raw in zip(starts, labels, raw_blocks)]
    if not known_finite.any():
        result["status"] = "unsupported_no_finite_known_calibration"
        return result
    if not metadata["finite_normal_baseline_calibration_rows"]:
        result["status"] = "unsupported_no_observed_normal_calibration"
        return result
    # Missing support was handled explicitly above. Unexpected selector/schema
    # errors must abort the attempt, not masquerade as an unsupported teacher.
    base_selected, result["trials"]["baseline"] = select_baseline(
        cal_y == 1, np.where(cal_y >= 0, cal_score, np.nan), baseline=True)
    threshold = float(base_selected["threshold"])
    if not np.isfinite(threshold):
        raise ValueError("Frozen baseline calibration must return a finite threshold")
    metadata["baseline_selected"] = base_selected

    blocks, guard_blocks = [], []
    for raw, t, start, rows in zip(raw_blocks, labels, starts, result["calibration_data"]):
        base = baseline_predict(raw["baseline_score"], threshold, "instant")
        components = {k: raw[k] for k in ("shape_raw", *LOCAL_KEYS)}
        gate = guarded_shape(components, components["shape_raw"])
        blocks.append({"labels": t, "baseline": base, "guarded": base.copy(),
                       "scores": components, "source_start": start})
        guard_blocks.append({"labels": t, "scores": gate, "baseline_predictions": base,
                             "source_start": start})
        rows["baseline"] = base
        rows["guarded_shape"] = gate
    guard, result["trials"]["suppression"] = calibrate_guard(guard_blocks)
    for block, gate, rows in zip(blocks, guard_blocks, result["calibration_data"]):
        block["guarded"] = predict_guard(gate["scores"], block["baseline"], guard)
        rows["guarded"] = block["guarded"]
    shape_threshold = fit_shape_reference(blocks)
    for block, rows in zip(blocks, result["calibration_data"]):
        block["scores"] = corroborated_scores(block["scores"], shape_threshold)
        for key, value in block["scores"].items():
            rows["rescue__" + key] = value
    selected, result["trials"]["joint"] = calibrate_joint(blocks)
    v6 = {"local_model": local, "prior_bundle": {"model": model, "baseline_threshold": threshold,
            "baseline_policy": "instant"}, "guard_selected": guard, "selected": selected,
          "shape_support_threshold": shape_threshold, "sample_seconds": CADENCE_SECONDS,
          "max_fit_index": len(fit) - 1, "max_calibration_index": metadata["max_calibration_index"],
          "training_status": {"shape": model.fit_status_, "local": local.fit_status_}}

    # One V8 HGB fit on exactly the same INNER FIT sensors and separate labels.
    long_model = OnsetWeightedHGBScorer(names).fit(fit, y)
    result["training_models"]["long"] = long_model
    metadata["fit_status"]["long"] = long_model.fit_status_
    v8_blocks = []
    for block, frame, rows in zip(blocks, frames, result["calibration_data"]):
        reference = predict_joint(block["baseline"], block["guarded"], block["scores"], selected)
        long_score = _long_gap(long_model, frame)
        masks = separate_scores({k: rows[k].to_numpy() for k in LOCAL_KEYS}, long_score)
        v8_blocks.append({"labels": block["labels"], "reference": reference,
            "long_scores": long_score, "rescue_scores": masks["rescue_long_context"],
            "source_start": block["source_start"]})
        rows["v6"] = reference
        rows["long_context"] = long_score
        for key, value in masks.items():
            rows[key] = value
    long_selected, result["trials"]["v8"] = calibrate_v8(v8_blocks, cadence_seconds=CADENCE_SECONDS)
    for block, rows in zip(v8_blocks, result["calibration_data"]):
        rows["v8"] = predict_v8(block["reference"], block["long_scores"], long_selected,
                                rescue_scores=block["rescue_scores"])
    v8 = {"version": V8_VERSION, "long_model": long_model, "reference_bundle": v6,
          "selected": long_selected, "sample_seconds": CADENCE_SECONDS,
          "max_fit_index": len(fit) - 1, "max_calibration_index": metadata["max_calibration_index"],
          "gap_samples": GAP_SAMPLES}
    result.update(status="ready", supported=True, v6_bundle=v6, v8_bundle=v8)
    return result


def predict_teacher(bundle, forecast_frame, gap_samples=GAP_SAMPLES):
    """Score one independent sensor forecast after the caller freezes teachers.

    The output retains the input index and frozen V8 runtime columns, plus
    ``baseline``, ``v6`` and ``v8`` int8 aliases. Extra columns, including labels,
    never reach the runtime. No supplied observations or fitted object mutate.
    """
    if not isinstance(bundle, dict) or bundle.get("version") != TEACHER_VERSION:
        raise ValueError("A V16 inner-teacher result is required")
    if bundle.get("supported") is not True or bundle.get("status") != "ready":
        raise ValueError("Unsupported teacher has no forecast predictions")
    if isinstance(gap_samples, (bool, np.bool_)) or not isinstance(gap_samples, (int, np.integer)) or gap_samples < 0:
        raise ValueError("gap_samples must be a nonnegative integer")
    names = _channels(bundle["training_metadata"]["channels"])
    sensors = _sensors(forecast_frame, names)
    v8 = bundle["v8_bundle"]
    if v8["reference_bundle"] is not bundle["v6_bundle"]:
        raise ValueError("V8 must reference the very same rebuilt V6 bundle")
    if list(v8["long_model"].channels) != names or list(bundle["v6_bundle"]["local_model"].channels) != names:
        raise ValueError("Teacher channel order must agree")
    scored = predict_v8_frame(v8, sensors, gap_samples=int(gap_samples)).copy()
    scored.insert(0, "baseline", scored["baseline_prediction"].to_numpy(np.int8))
    scored.insert(1, "v6", scored["reference_prediction"].to_numpy(np.int8))
    scored.insert(2, "v8", scored["prediction"].to_numpy(np.int8))
    return scored
