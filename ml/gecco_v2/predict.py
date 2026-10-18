"""Detection-only inference for a frozen Mawrid GECCO bundle.

Only load trusted local joblib files: joblib/pickle deserialization can execute
code. This module does not validate an arbitrary model file as safe.

No input labels are used. A prediction of -1 means unavailable, 0 means no
detected alarm under this model, and 1 means an alarm. In particular, 0 is NOT
permission to open a valve, a statement that water is safe, or a trust score.

The batch API is causal within the supplied frame. For incremental use, retain
the necessary past channel history and policy history; independent chunks
restart their feature/policy warm-up. No threshold or model fitting occurs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from alarm_policy import predict as apply_alarm_policy
from candidates_supervised import build_features, score_model
# Import registers the supported custom detector class for trusted joblib loads.
import candidates_unsupervised  # noqa: F401
sys.path.append(str(HERE.parent / "gecco_v3"))
import candidate  # noqa: F401 -- registers trusted v3 detector classes


FAMILIES = {"baseline", "extra_trees", "hist_gradient_boosting", "logistic",
            "if_normalized_changes_w30", "baseline_persistent",
            "normalized_extra_trees_depth10", "normalized_extra_trees_depth14",
            "normalized_hist_gradient_boosting"}
POLICIES = {"instant", "2of3", "3of5"}
LABEL_NAMES = {"event", "label", "labels", "target", "y"}


def validate_bundle(bundle: dict[str, Any]) -> list[str]:
    if not isinstance(bundle, dict):
        raise TypeError("The trusted model artifact must contain a bundle dictionary")
    required = {"family", "model", "channels", "threshold", "policy", "feature_set",
                "model_id", "limitations"}
    missing = required-set(bundle)
    if missing:
        raise ValueError("Incomplete inference bundle: " + ", ".join(sorted(missing)))
    if bundle["family"] not in FAMILIES:
        raise ValueError("Unsupported model family")
    channels = bundle["channels"]
    if not isinstance(channels, (list, tuple)) or not channels:
        raise ValueError("channels must be a nonempty ordered list")
    if any(not isinstance(c, str) or not c for c in channels):
        raise ValueError("Every channel must have a nonempty string name")
    if len(set(channels)) != len(channels):
        raise ValueError("Duplicate channel names are not allowed")
    if any(c.casefold() in LABEL_NAMES for c in channels):
        raise ValueError("Label columns cannot be inference channels")
    if not np.isfinite(float(bundle["threshold"])):
        raise ValueError("threshold must be finite")
    if bundle["policy"] not in POLICIES:
        raise ValueError("Unsupported causal alarm policy")
    expected = {"baseline": "baseline15",
                "baseline_persistent": "baseline15",
                "if_normalized_changes_w30": "normalized_causal_changes_w30"}.get(
                    bundle["family"], "normalized_supervised_changes_w30" if bundle["family"].startswith("normalized_") else "multiscale")
    if bundle["feature_set"] != expected:
        raise ValueError(f"{bundle['family']} requires feature_set={expected!r}")
    if bundle["family"] == "if_normalized_changes_w30" or bundle["family"].startswith("normalized_"):
        model_channels = getattr(bundle["model"], "channels", channels)
        if list(model_channels) != list(channels):
            raise ValueError("Bundle channels differ from the custom detector's channel order")
    return list(channels)


def predict_frame(bundle: dict[str, Any], raw_frame: pd.DataFrame) -> pd.DataFrame:
    """Return score, prediction, score_available, reason without reading labels.

    The supplied row order and index are preserved. Extra columns are ignored.
    Non-numeric or non-finite channel values become unavailable measurements.
    ``score_available`` means the model score is finite. A finite score may
    still have prediction -1 while a persistence policy lacks complete history.
    """
    channels = validate_bundle(bundle)
    if not isinstance(raw_frame, pd.DataFrame):
        raise TypeError("raw_frame must be a pandas DataFrame")
    absent = set(channels)-set(raw_frame.columns)
    if absent:
        raise ValueError("Missing required channels: " + ", ".join(sorted(absent)))
    if raw_frame.columns.duplicated().any():
        raise ValueError("Duplicate input column names are ambiguous")
    # Select BEFORE numeric conversion: no EVENT or other extra column is read.
    selected = raw_frame.loc[:, channels].copy()
    selected = selected.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    raw_complete = selected.notna().all(axis=1).to_numpy()
    family = bundle["family"]
    model = bundle["model"]
    n = len(selected)
    if family == "if_normalized_changes_w30" or family.startswith("normalized_"):
        scores = np.asarray(model.score(selected), dtype=float)
        lookback = int(getattr(model, "history_rows", 61))
        eligible = pd.Series(raw_complete).rolling(lookback, min_periods=lookback).sum().eq(lookback).to_numpy()
    else:
        X, eligible, _ = build_features(selected, bundle["feature_set"], channels=channels)
        lookback = 15 if family in ("baseline", "baseline_persistent") else 60
        if family in ("baseline", "baseline_persistent"):
            scores = np.full(n, np.nan)
            if eligible.any():
                scores[eligible] = -np.asarray(model.score_samples(X[eligible]), dtype=float)
        else:
            scores = score_model(model, X, eligible)
    if scores.shape != (n,):
        raise ValueError("Model must return exactly one scalar score per input row")
    # Never allow a custom estimator to bypass missing-measurement handling.
    scores = scores.copy()
    scores[~eligible] = np.nan
    scores[~np.isfinite(scores)] = np.nan
    available = np.isfinite(scores)
    prediction = np.asarray(apply_alarm_policy(scores, float(bundle["threshold"]), bundle["policy"]), dtype=int)
    if prediction.shape != (n,) or not np.isin(prediction, [-1, 0, 1]).all():
        raise ValueError("Invalid output from the causal alarm policy")
    if np.any(prediction[~available] != -1):
        raise ValueError("Alarm policy returned a decision for an unavailable score")
    reasons = np.full(n, "available", dtype=object)
    reasons[~eligible] = "missing_value_in_feature_window"
    reasons[:max(lookback-1, 0)] = "feature_warmup"
    reasons[~raw_complete] = "current_measurement_missing"
    reasons[eligible & ~available] = "model_score_nonfinite"
    reasons[available & (prediction == -1)] = "policy_history_unavailable"
    result = pd.DataFrame({"score": scores, "prediction": prediction,
                           "score_available": available,
                           "reason": pd.Series(reasons, index=raw_frame.index, dtype="string")},
                          index=raw_frame.index)
    result.attrs.update({"model_id": bundle["model_id"], "detect_only": True,
                         "limitations": bundle["limitations"],
                         "normal_prediction_is_not_water_safety_or_valve_permission": True})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True, help="Trusted local frozen joblib bundle only")
    parser.add_argument("--input", type=Path, required=True, help="CSV containing required sensor channels")
    parser.add_argument("--output", type=Path, required=True, help="Prediction CSV; labels are never copied")
    args = parser.parse_args()
    if args.output.resolve() in {args.model.resolve(), args.input.resolve()}:
        raise ValueError("Output must not replace the input CSV or trusted model bundle")
    bundle = joblib.load(args.model)
    channels = validate_bundle(bundle)
    frame = pd.read_csv(args.input, usecols=channels)
    result = predict_frame(bundle, frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(json.dumps({"model_id": bundle["model_id"], "rows": len(result),
                      "scores_available": int(result.score_available.sum()),
                      "predictions_unavailable": int((result.prediction == -1).sum()),
                      "alarm_minutes": int((result.prediction == 1).sum()),
                      "detect_only": True, "output": str(args.output.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
