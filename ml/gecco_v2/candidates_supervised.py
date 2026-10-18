"""Supervised binary EVENT candidates, developed strictly on GECCO's first 40%.

Library API:
    X, eligible, names = build_features(frame, feature_set="multiscale", channels=None)
    model = make_model(candidate_id)
    model.fit(X[eligible], y[eligible])
    scores = score_model(model, X, eligible)

The CLI selects on development validation and freezes before opening its
development-test partition. These are development results, not outer results.
No function imports or reads the v1 experiment's result artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler
from threadpoolctl import threadpool_limits


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = ROOT / "data/external/gecco2018/1_gecco2018_water_quality.csv"
OUT = ROOT / "output/ml/gecco-v2-development/supervised"
sys.path.insert(0, str(ROOT / "ml/gecco_baseline"))
from metrics import evaluate

CHANNELS = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
SEED = 20261016
MAX_DEVELOPMENT_ROWS = 55826
TRAIN_END = 34891
VALIDATION_END = 41869
GAP = 60
CANDIDATE_IDS = ("extra_trees", "hist_gradient_boosting", "logistic")
CANDIDATES = {
    "extra_trees": dict(n_estimators=300, max_depth=14, min_samples_leaf=4,
                        max_features=.8, class_weight="balanced", n_jobs=2,
                        random_state=SEED),
    "hist_gradient_boosting": dict(max_iter=200, max_leaf_nodes=15,
                                    min_samples_leaf=20, learning_rate=.05,
                                    l2_regularization=1., class_weight="balanced",
                                    early_stopping=False, random_state=SEED),
    "logistic": dict(C=.1, max_iter=1000, class_weight="balanced", solver="lbfgs",
                     random_state=SEED),
}


def build_features(frame, feature_set="multiscale", channels=None):
    """Causal features; a full clean lookback is required, without imputation.

    Window statistics include the current sample. Input row order is retained.
    Reset this function at split boundaries, or explicitly supply past context
    and discard it, according to the caller's predeclared evaluation protocol.
    No labels are read. Never uses centered windows or future samples.
    ``channels`` optionally supplies an ordered channel list; None retains the
    original nine-channel development behavior and its feature ordering.
    """
    if feature_set not in ("levels", "baseline15", "multiscale"):
        raise ValueError(f"Unknown feature set: {feature_set}")
    selected_channels = list(CHANNELS if channels is None else channels)
    if not selected_channels or len(set(selected_channels)) != len(selected_channels):
        raise ValueError("channels must be a nonempty ordered list without duplicates")
    x = frame.loc[:, selected_channels].astype(float).replace([np.inf, -np.inf], np.nan)
    parts = [x.add_suffix("__value")]
    clean = x.notna().all(axis=1)
    if feature_set == "levels":
        lookback = 1
    else:
        parts.append(x.diff().abs().add_suffix("__abs_change_1m"))
        windows = (15,) if feature_set == "baseline15" else (15, 60)
        lookback = max(windows)
        for window in windows:
            rolling = x.rolling(window, min_periods=window)
            parts.append((x-rolling.mean()).add_suffix(f"__residual_mean_{window}m"))
            parts.append(rolling.std(ddof=0).add_suffix(f"__std_{window}m"))
    features = pd.concat(parts, axis=1)
    X = features.to_numpy(dtype=np.float64)
    eligible = clean.rolling(lookback, min_periods=lookback).sum().eq(lookback).to_numpy(copy=True)
    eligible &= np.isfinite(X).all(axis=1)
    return X, eligible, features.columns.tolist()


def make_model(candidate_id):
    params = dict(CANDIDATES[candidate_id])
    if candidate_id == "extra_trees":
        return ExtraTreesClassifier(**params)
    if candidate_id == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(**params)
    if candidate_id == "logistic":
        return make_pipeline(RobustScaler(quantile_range=(25, 75)), LogisticRegression(**params))
    raise ValueError(candidate_id)


def score_model(model, X, eligible):
    scores = np.full(len(X), np.nan)
    if np.any(eligible):
        classes = np.asarray(model.classes_)
        positive = np.flatnonzero(classes == 1)
        if positive.size != 1:
            raise ValueError("Supervised training requires both normal and EVENT classes")
        with threadpool_limits(limits=1):
            scores[eligible] = model.predict_proba(X[eligible])[:, positive[0]]
    return scores


def predictions(scores, threshold):
    output = np.full(len(scores), -1, dtype=int)
    valid = np.isfinite(scores)
    output[valid] = (scores[valid] >= threshold).astype(int)
    return output


def read_prefix(stop):
    if not 0 < stop <= MAX_DEVELOPMENT_ROWS:
        raise ValueError("Reading beyond first 40% development is prohibited")
    frame = pd.read_csv(RAW, nrows=stop)
    assert len(frame) == stop
    assert np.array_equal(frame.iloc[:, 0].to_numpy(), np.arange(1, stop+1))
    return frame


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def brief(result):
    return {key: value for key, value in result.items() if not key.endswith("records")}


def finite_or_zero(value):
    return 0. if value is None else float(value)


def select_threshold(labels, scores):
    """Only development-validation scores may be passed by the CLI."""
    finite = scores[np.isfinite(scores)]
    if not finite.size:
        raise ValueError("No eligible validation measurements")
    quantiles = np.unique(np.r_[np.linspace(0, .95, 96), np.linspace(.95, 1, 101)])
    thresholds = np.unique(np.r_[0., np.quantile(finite, quantiles),
                                  np.nextafter(finite.max(), np.inf)])
    sweep = []
    for threshold in thresholds:
        result = evaluate(labels, predictions(scores, threshold))
        rate = result["false_alarm_runs_per_normal_day"]
        duration = result["normal_time_under_alarm"]
        feasible = rate is not None and duration is not None and rate <= 1. and duration <= .01
        utility = .5*finite_or_zero(result["f1"]) + .5*finite_or_zero(result["confirmed_new_alarm_inside_event_recall"])
        sweep.append({"threshold": float(threshold), "feasible": feasible,
                      "utility": utility, **brief(result)})
    feasible = [row for row in sweep if row["feasible"]]
    if not feasible:
        raise ValueError("No feasible threshold; no-alarm reference should be feasible")
    selected = max(feasible, key=lambda row: (row["utility"], finite_or_zero(row["f1"]),
                                              -row["fp"], row["threshold"]))
    return selected, sweep


def protocol():
    return {
        "experiment": "supervised-development-40pct-v1",
        "label_target": "Original binary EVENT; not five-fault type classification",
        "development_only": True, "maximum_source_rows_read": MAX_DEVELOPMENT_ROWS,
        "boundaries_zero_based_end_exclusive": {
            "train": [0, TRAIN_END], "validation": [TRAIN_END+GAP, VALIDATION_END],
            "development_test": [VALIDATION_END+GAP, MAX_DEVELOPMENT_ROWS]},
        "feature_set": "multiscale", "feature_count": 54, "channels": CHANNELS,
        "lookback_rows": 60, "missing_policy": "Exclude incomplete causal windows; prediction=-1; no imputation",
        "candidate_parameters": CANDIDATES, "seed": SEED,
        "threshold_search": "196 quantile grid locations before deduplication plus zero and above-max",
        "operating_constraints": {"false_alarm_runs_per_normal_day_max": 1., "normal_time_under_alarm_max": .01},
        "selection": ".5*unadjusted_point_F1 + .5*confirmed_0_to_1_event_start_recall among feasible validation thresholds; ties F1, fewer FP, higher threshold",
        "alarm_policy": "Independent current probability threshold, no persistence, retrospective merging, or point adjustment",
        "test_policy": "Freeze chosen candidate and threshold before development-test; no tuning on development-test",
        "supervision": "Eligible training rows of both classes; no relabeling or expansion of EVENT",
    }


def select():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT/"selection_freeze.json").exists():
        raise SystemExit("Selection already frozen; do not overwrite")
    spec = protocol()
    spec["declared_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(OUT/"protocol.json", spec)
    frame = read_prefix(VALIDATION_END)
    training = frame.iloc[:TRAIN_END].reset_index(drop=True)
    validation = frame.iloc[TRAIN_END+GAP:VALIDATION_END].reset_index(drop=True)
    Xtrain, train_ok, names = build_features(training)
    Xval, val_ok, _ = build_features(validation)
    ytrain = training.EVENT.to_numpy(dtype=bool)
    yval = validation.EVENT.to_numpy(dtype=bool)
    if np.unique(ytrain[train_ok]).size != 2:
        raise ValueError("Training partition does not contain both classes")
    info = {"development_only": True, "training_rows": len(training),
            "eligible_training_rows": int(train_ok.sum()),
            "eligible_training_positive_minutes": int(ytrain[train_ok].sum()),
            "validation_rows": len(validation), "eligible_validation_rows": int(val_ok.sum()),
            "validation_positive_minutes": int(yval.sum()), "feature_names": names,
            "max_source_index_inspected": VALIDATION_END-1}
    write_json(OUT/"selection_data_manifest.json", info)
    summaries = []
    for candidate_id in CANDIDATE_IDS:
        model = make_model(candidate_id)
        started = time.perf_counter()
        with threadpool_limits(limits=1):
            model.fit(Xtrain[train_ok], ytrain[train_ok].astype(int))
        fit_seconds = time.perf_counter()-started
        scores = score_model(model, Xval, val_ok)
        chosen, sweep = select_threshold(yval, scores)
        joblib.dump(model, OUT/f"{candidate_id}.joblib", compress=3)
        pd.DataFrame(sweep).to_csv(OUT/f"{candidate_id}_validation_sweep.csv", index=False)
        pd.DataFrame({"row_id": validation.iloc[:, 0], "EVENT": yval,
                      "score": scores, "prediction": predictions(scores, chosen["threshold"])}).to_csv(
                          OUT/f"{candidate_id}_validation_predictions.csv.gz", index=False)
        result = {"candidate_id": candidate_id, "fit_seconds": fit_seconds,
                  "chosen_validation": chosen,
                  "best_validation_f1_without_constraints": max(sweep, key=lambda r: finite_or_zero(r["f1"]))}
        summaries.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    winner = max(summaries, key=lambda s: (s["chosen_validation"]["utility"],
                 finite_or_zero(s["chosen_validation"]["f1"]), -s["chosen_validation"]["fp"],
                 -CANDIDATE_IDS.index(s["candidate_id"])))
    freeze = {"frozen_at_utc": datetime.now(timezone.utc).isoformat(), "development_only": True,
              "candidate_id": winner["candidate_id"], "threshold": winner["chosen_validation"]["threshold"],
              "selection": winner, "all_candidates_tried": list(CANDIDATE_IDS),
              "candidate_results": summaries, "development_test_used_for_selection": False,
              "max_source_index_inspected_before_freeze": VALIDATION_END-1,
              "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "model_sha256": hashlib.sha256((OUT/f'{winner["candidate_id"]}.joblib').read_bytes()).hexdigest()}
    write_json(OUT/"selection_freeze.json", freeze)
    print("FROZEN " + winner["candidate_id"], flush=True)


def development_test():
    if (OUT/"development_test_results.json").exists():
        raise SystemExit("Development test already evaluated; do not tune/reopen")
    frozen = json.loads((OUT/"selection_freeze.json").read_text())
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != frozen["code_sha256"]:
        raise ValueError("Code changed after selection freeze")
    modelpath = OUT/f'{frozen["candidate_id"]}.joblib'
    if hashlib.sha256(modelpath.read_bytes()).hexdigest() != frozen["model_sha256"]:
        raise ValueError("Frozen model changed")
    frame = read_prefix(MAX_DEVELOPMENT_ROWS).iloc[VALIDATION_END+GAP:].reset_index(drop=True)
    X, eligible, names = build_features(frame)
    model = joblib.load(modelpath)
    scores = score_model(model, X, eligible)
    y = frame.EVENT.to_numpy(dtype=bool)
    predicted = predictions(scores, frozen["threshold"])
    result = evaluate(y, predicted)
    result.update({"development_only": True, "candidate_id": frozen["candidate_id"],
                   "threshold": frozen["threshold"], "development_test_used_for_selection": False,
                   "max_source_index_inspected": MAX_DEVELOPMENT_ROWS-1,
                   "source_row_ids": [int(frame.iloc[0, 0]), int(frame.iloc[-1, 0])],
                   "feature_count": len(names), "evaluated_at_utc": datetime.now(timezone.utc).isoformat()})
    write_json(OUT/"development_test_results.json", result)
    pd.DataFrame({"row_id": frame.iloc[:, 0], "EVENT": y, "score": scores,
                  "prediction": predicted}).to_csv(OUT/"development_test_predictions.csv.gz", index=False)
    print(json.dumps(brief(result), indent=2), flush=True)


def self_test():
    """Focused tests: causality, missing-window handling, registry configuration."""
    rng = np.random.default_rng(123)
    frame = pd.DataFrame(rng.normal(size=(180, len(CHANNELS))), columns=CHANNELS)
    X, ok, names = build_features(frame)
    prefix, prefix_ok, _ = build_features(frame.iloc[:120])
    assert len(names) == 54 and X.shape == (180, 54)
    np.testing.assert_allclose(X[:120], prefix, equal_nan=True)
    assert np.array_equal(ok[:120], prefix_ok)
    assert not ok[:59].any() and ok[59:].all()
    missing = frame.copy(); missing.loc[90, "Cl"] = np.nan
    _, missing_ok, _ = build_features(missing)
    assert missing_ok[89] and not missing_ok[90:150].any() and missing_ok[150]
    mutated = frame.copy(); mutated.iloc[120:] = 999999
    altered, _, _ = build_features(mutated)
    np.testing.assert_allclose(X[:120], altered[:120], equal_nan=True)
    explicit, explicit_ok, explicit_names = build_features(frame, channels=CHANNELS)
    np.testing.assert_allclose(X, explicit, equal_nan=True)
    assert np.array_equal(ok, explicit_ok) and names == explicit_names
    six_channels = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
    six = pd.DataFrame(rng.normal(size=(180, 6)), columns=six_channels)
    Xsix, six_ok, six_names = build_features(six, channels=six_channels)
    six_prefix, prefix_ok, _ = build_features(six.iloc[:120], channels=six_channels)
    assert Xsix.shape == (180, 36)
    assert six_names[:6] == [f"{channel}__value" for channel in six_channels]
    np.testing.assert_allclose(Xsix[:120], six_prefix, equal_nan=True)
    assert np.array_equal(six_ok[:120], prefix_ok)
    six_mutated = six.copy(); six_mutated.iloc[120:] = -999999
    six_altered, _, _ = build_features(six_mutated, channels=six_channels)
    np.testing.assert_allclose(Xsix[:120], six_altered[:120], equal_nan=True)
    assert make_model("hist_gradient_boosting").early_stopping is False
    for name in CANDIDATE_IDS:
        model = make_model(name)
        with threadpool_limits(limits=1):
            model.fit(X[ok], (X[ok, 0] > 0).astype(int))
        scores = score_model(model, X, ok)
        assert np.isnan(scores[~ok]).all()
        assert np.isfinite(scores[ok]).all()
    try:
        read_prefix(MAX_DEVELOPMENT_ROWS+1)
        raise AssertionError("Access guard missing")
    except ValueError:
        pass
    print("PASS: nine-channel compatibility, six-channel synthetic causality, future mutation, missing windows, three estimators, source-access bound")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["self-test", "select", "development-test"])
    args = parser.parse_args()
    {"self-test": self_test, "select": select, "development-test": development_test}[args.stage]()
