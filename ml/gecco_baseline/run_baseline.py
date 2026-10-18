"""Reproducible, causally prepared GECCO baseline. Run prepare, train, then test.

The training stage never loads the prepared test set. The test stage refuses to
overwrite results and checks the frozen model/protocol/training-code hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest

from metrics import evaluate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = ROOT / "data/external/gecco2018/1_gecco2018_water_quality.csv"
OUT = ROOT / "output/ml/gecco-baseline-v1"
PROTOCOL_PATH = HERE / "protocol.json"
PROTOCOL = json.loads(PROTOCOL_PATH.read_text())
CHANNELS = PROTOCOL["features"]["channels"]
WINDOW = PROTOCOL["features"]["window_minutes"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def feature_frame(raw_channels):
    """Each row uses only itself and its 14 predecessors within its partition."""
    x = raw_channels[CHANNELS].astype(float).replace([np.inf, -np.inf], np.nan)
    rolling = x.rolling(WINDOW, min_periods=WINDOW)
    parts = [x, x.diff().abs(), x - rolling.mean(), rolling.std(ddof=0)]
    suffixes = ["value", "abs_change_1m", "residual_mean_15m", "std_15m"]
    features = pd.concat(
        [part.rename(columns={c: f"{c}__{suffix}" for c in CHANNELS})
         for part, suffix in zip(parts, suffixes)], axis=1)
    complete = x.notna().all(axis=1)
    eligible = complete.rolling(WINDOW, min_periods=WINDOW).sum().eq(WINDOW)
    eligible &= np.isfinite(features.to_numpy()).all(axis=1)
    return features, eligible.to_numpy(), complete.to_numpy()


def prepare():
    assert sha(RAW) == PROTOCOL["source_sha256"], "Source checksum changed"
    assert not (OUT / "freeze.json").exists(), "Already frozen; do not replace splits"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "prepared").mkdir(exist_ok=True)
    df = pd.read_csv(RAW)
    rowids = df.iloc[:, 0].to_numpy()
    assert np.array_equal(rowids, np.arange(1, len(df) + 1))
    labels = df.EVENT.to_numpy(dtype=bool)
    original_time = pd.to_datetime(df.Time)
    dt = original_time.diff().dt.total_seconds().to_numpy()[1:]
    assert ((dt == 60) | (dt == -3540)).all()
    assert (dt == -3540).sum() == 1
    clock_back = np.flatnonzero(dt < 0) + 1
    n = len(df)
    b1 = int(n * PROTOCOL["split"]["train_fraction"])
    b2 = int(n * PROTOCOL["split"]["validation_end_fraction"])
    gap = PROTOCOL["split"]["gap_rows_after_each_boundary"]
    bounds = {"train": (0, b1), "validation": (b1 + gap, b2),
              "test": (b2 + gap, n)}
    splits = {}
    for name, (start, end) in bounds.items():
        part = df.iloc[start:end].reset_index(drop=True)
        y = labels[start:end]
        features, eligible, raw_complete = feature_frame(part)
        clean_label_window = (pd.Series(y.astype(int)).rolling(WINDOW,
                              min_periods=WINDOW).sum().eq(0).to_numpy())
        fit_mask = eligible & clean_label_window
        reasons = np.full(len(part), "available", dtype="U40")
        reasons[~eligible] = "missing_value_in_feature_window"
        reasons[:WINDOW - 1] = "split_warmup"
        reasons[~raw_complete] = "current_measurement_missing"
        X = features.to_numpy(dtype=np.float64)
        np.savez_compressed(OUT / "prepared" / f"{name}.npz", X=X, y=y,
                            eligible=eligible, fit_mask=fit_mask,
                            raw_complete=raw_complete, reason=reasons,
                            row_id=part.iloc[:, 0].to_numpy(dtype=int),
                            sample_index=np.arange(start, end),
                            timestamp_original=part.Time.to_numpy(dtype=str))
        audit = part.copy().rename(columns={part.columns[0]: "row_id",
                                            "Time": "timestamp_original"})
        audit["sample_index"] = np.arange(start, end)
        audit["score_available"] = eligible
        audit["unavailable_reason"] = reasons
        audit["normal_training_window"] = fit_mask if name == "train" else False
        audit.to_csv(OUT / "prepared" / f"{name}.csv.gz", index=False)
        splits[name] = {
            "source_start_index_inclusive": start, "source_end_index_exclusive": end,
            "first_row_id": start + 1, "last_row_id": end, "rows": end - start,
            "first_timestamp_original": part.Time.iloc[0],
            "last_timestamp_original": part.Time.iloc[-1],
            "nominal_days": (end - start) / 1440,
            "eligible_rows": int(eligible.sum()), "unavailable_rows": int((~eligible).sum()),
            "raw_incomplete_rows": int((~raw_complete).sum()),
            "original_event_minutes": int(y.sum()),
            "fit_rows": int(fit_mask.sum()) if name == "train" else 0,
            "starts_inside_source_event": bool(y[0] and start > 0 and labels[start-1]),
            "ends_inside_source_event": bool(y[-1] and end < n and labels[end]),
            "prepared_sha256": sha(OUT / "prepared" / f"{name}.npz")}
    assert bounds["train"][1] + gap == bounds["validation"][0]
    assert bounds["validation"][1] + gap == bounds["test"][0]
    manifest = {"experiment": PROTOCOL["experiment"], "source_sha256": sha(RAW),
                "protocol_sha256": sha(PROTOCOL_PATH), "source_rows": n,
                "excluded_gap_rows": gap * 2, "splits": splits,
                "features": features.columns.tolist(),
                "clock_reversal_row_ids": (clock_back + 1).tolist(),
                "time_policy": "Retain acquisition order; elapsed minutes are nominal, not reconstructed UTC",
                "quality": {"missing_by_channel": df[CHANNELS].isna().sum().to_dict(),
                            "duplicate_wall_clock_values": int(original_time.duplicated().sum())},
                "versions": {"python": platform.python_version(), "numpy": np.__version__,
                             "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
                             "joblib": joblib.__version__}}
    write_json(OUT / "data_manifest.json", manifest)
    print(json.dumps(splits, indent=2), flush=True)


def load_split(name):
    manifest = json.loads((OUT / "data_manifest.json").read_text())
    path = OUT / "prepared" / f"{name}.npz"
    assert sha(PROTOCOL_PATH) == manifest["protocol_sha256"]
    assert sha(path) == manifest["splits"][name]["prepared_sha256"]
    with np.load(path, allow_pickle=False) as data:
        return {k: data[k] for k in data.files}


def score_split(model, split):
    scores = np.full(len(split["y"]), np.nan)
    # sklearn score_samples is lower for more abnormal observations.
    scores[split["eligible"]] = -model.score_samples(split["X"][split["eligible"]])
    return scores


def predict(scores, threshold):
    result = np.full(len(scores), -1, dtype=int)
    valid = np.isfinite(scores)
    result[valid] = (scores[valid] >= threshold).astype(int)
    return result


def save_predictions(name, split, scores, predictions):
    pd.DataFrame({"row_id": split["row_id"], "sample_index": split["sample_index"],
                  "timestamp_original": split["timestamp_original"], "EVENT": split["y"],
                  "score_available": split["eligible"], "unavailable_reason": split["reason"],
                  "anomaly_score": scores, "prediction": predictions
                  }).to_csv(OUT / f"{name}_predictions.csv.gz", index=False)


def train():
    assert not (OUT / "freeze.json").exists(), "A model is already frozen"
    assert not (OUT / "test_results.json").exists(), "Held-out test already opened"
    train_data = load_split("train")
    validation = load_split("validation")
    manifest = json.loads((OUT / "data_manifest.json").read_text())
    settings = {k: v for k, v in PROTOCOL["model"].items() if k != "name"}
    model = IsolationForest(**settings, random_state=PROTOCOL["seed"])
    started = time.perf_counter()
    model.fit(train_data["X"][train_data["fit_mask"]])
    fit_seconds = time.perf_counter() - started
    scores = score_split(model, validation)
    quantiles = np.unique(np.r_[0, .5, .75, np.linspace(.8, .99, 191),
                                np.linspace(.99, 1, 201)])
    finite = scores[np.isfinite(scores)]
    thresholds = np.unique(np.r_[np.quantile(finite, quantiles),
                                  np.nextafter(finite.max(), np.inf)])
    sweep = []
    for threshold in thresholds:
        result = evaluate(validation["y"], predict(scores, threshold))
        limits = PROTOCOL["threshold_selection"]
        feasible = (result["false_alarm_runs_per_normal_day"] <=
                    limits["max_false_positive_runs_per_eligible_normal_day"] and
                    result["normal_time_under_alarm"] <= limits["max_normal_time_under_alarm"])
        sweep.append({"threshold": float(threshold), "feasible": feasible,
                      **{key: result[key] for key in ["precision", "recall", "f1", "fp",
                         "false_alarm_runs_per_normal_day", "normal_time_under_alarm",
                         "true_events", "detected_events", "event_recall"]}})
    feasible_candidates = [r for r in sweep if r["feasible"]]
    selected = max(feasible_candidates, key=lambda r: (r["f1"] or 0,
                                                       -r["fp"], r["threshold"]))
    threshold = selected["threshold"]
    predictions = predict(scores, threshold)
    validation_result = evaluate(validation["y"], predictions)
    write_json(OUT / "validation_results.json", validation_result)
    pd.DataFrame(sweep).to_csv(OUT / "validation_threshold_sweep.csv", index=False)
    save_predictions("validation", validation, scores, predictions)
    bundle = {"model": model, "threshold": threshold, "features": manifest["features"],
              "protocol": PROTOCOL, "data_manifest": manifest}
    joblib.dump(bundle, OUT / "model.joblib", compress=3)
    # Confirm serialization preserves validation predictions before freezing.
    reloaded = joblib.load(OUT / "model.joblib")
    assert np.array_equal(predict(score_split(reloaded["model"], validation),
                                 reloaded["threshold"]), predictions)
    frozen = {"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
              "experiment": PROTOCOL["experiment"], "source_sha256": sha(RAW),
              "protocol_sha256": sha(PROTOCOL_PATH),
              "data_manifest_sha256": sha(OUT / "data_manifest.json"),
              "training_code_sha256": sha(__file__), "metrics_code_sha256": sha(HERE / "metrics.py"),
              "model_sha256": sha(OUT / "model.joblib"),
              "model_size_bytes": (OUT / "model.joblib").stat().st_size,
              "threshold": threshold, "threshold_selection": selected,
              "fit_rows": int(train_data["fit_mask"].sum()), "fit_seconds": fit_seconds,
              "features": manifest["features"], "test_used_for_selection": False,
              "validation_targets_have_nonzero_recall": bool((selected["recall"] or 0) > 0)}
    write_json(OUT / "freeze.json", frozen)
    print(json.dumps({"freeze": frozen, "validation":
          {k:v for k,v in validation_result.items() if not k.endswith("records")}}, indent=2), flush=True)


def test():
    assert not (OUT / "test_results.json").exists(), "Test already scored; do not tune/reopen"
    frozen = json.loads((OUT / "freeze.json").read_text())
    assert sha(RAW) == frozen["source_sha256"]
    assert sha(PROTOCOL_PATH) == frozen["protocol_sha256"]
    assert sha(OUT / "data_manifest.json") == frozen["data_manifest_sha256"]
    assert sha(__file__) == frozen["training_code_sha256"]
    assert sha(HERE / "metrics.py") == frozen["metrics_code_sha256"]
    assert sha(OUT / "model.joblib") == frozen["model_sha256"]
    bundle = joblib.load(OUT / "model.joblib")
    test_data = load_split("test")
    started = time.perf_counter()
    scores = score_split(bundle["model"], test_data)
    elapsed = time.perf_counter() - started
    predictions = predict(scores, bundle["threshold"])
    result = evaluate(test_data["y"], predictions)
    result["experiment"] = PROTOCOL["experiment"]
    result["threshold"] = bundle["threshold"]
    result["scored_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["test_used_for_selection"] = False
    limits = PROTOCOL["threshold_selection"]
    result["heldout_operating_targets_met"] = (
        result["false_alarm_runs_per_normal_day"] <=
        limits["max_false_positive_runs_per_eligible_normal_day"] and
        result["normal_time_under_alarm"] <= limits["max_normal_time_under_alarm"])
    result["coverage_fraction"] = result["valid_count"] / len(test_data["y"])
    result["all_normal_reference"] = evaluate(test_data["y"],
                                 np.where(test_data["eligible"], 0, -1))
    # This is a local-machine benchmark only. No Raspberry Pi claim.
    examples = test_data["X"][test_data["eligible"]][:100]
    durations = []
    for example in examples:
        start = time.perf_counter()
        bundle["model"].score_samples(example.reshape(1, -1))
        durations.append((time.perf_counter() - start) * 1000)
    result["runtime"] = {"machine": platform.machine(), "system": platform.platform(),
                         "processor": platform.processor(), "raspberry_pi_measured": False,
                         "batch_scoring_seconds": elapsed,
                         "batch_ms_per_eligible_row": elapsed * 1000 / result["valid_count"],
                         "single_row_median_ms": float(np.median(durations)),
                         "single_row_p95_ms": float(np.quantile(durations, .95)),
                         "single_row_benchmark_count": len(durations),
                         "feature_preparation_included": False}
    save_predictions("test", test_data, scores, predictions)
    write_json(OUT / "test_results.json", result)
    pd.DataFrame(result["event_records"]).to_csv(OUT / "test_events.csv", index=False)
    pd.DataFrame(result["false_alarm_records"]).to_csv(OUT / "test_false_alarm_intervals.csv", index=False)
    print(json.dumps({k:v for k,v in result.items()
                      if not k.endswith("records") and k != "all_normal_reference"}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "train", "test"])
    stage = parser.parse_args().stage
    {"prepare": prepare, "train": train, "test": test}[stage]()
