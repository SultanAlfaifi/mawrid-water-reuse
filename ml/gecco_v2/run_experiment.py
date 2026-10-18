"""Predeclared, nested chronological comparison; final 2019 test opened once.

Use the baseline virtual environment. No model decisions may use outer scores.
2018 is retrospective because its old test was already inspected in v1.
2019 uses actual dates: train -> valid (calibration) -> test (final).
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
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "ml/gecco_baseline"))
from metrics import evaluate, run_intervals
from candidates_supervised import CHANNELS, CANDIDATES, build_features, make_model, score_model
from candidates_unsupervised import CausalChangeDetector
from alarm_policy import predict, select

OUT = ROOT / "output/ml/gecco-v2"
RAW18 = ROOT / "data/external/gecco2018/1_gecco2018_water_quality.csv"
RAW19 = ROOT / "data/external/gecco2019"
N18 = 139566
GAP = 120
FAMILIES = ["extra_trees", "hist_gradient_boosting", "logistic", "if_normalized_changes_w30"]
CHANNELS19 = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
UNSUP = {"name": "if_normalized_changes_w30", "window": 30, "method": "iforest", "aggregate": "max"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n")


def now():
    return datetime.now(timezone.utc).isoformat()


def compact(result):
    return {k: v for k, v in result.items() if not k.endswith("records")}


def hashes():
    paths = [HERE / f for f in ["run_experiment.py", "candidates_supervised.py", "candidates_unsupervised.py", "alarm_policy.py"]]
    paths += [ROOT / "ml/gecco_baseline/metrics.py"]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def declare():
    assert not (OUT / "protocol.json").exists(), "Do not replace a declared experiment"
    protocol = {
        "experiment": "mawrid-gecco-v2", "declared_at_utc": now(),
        "code_sha256": hashes(), "seed": 20261016,
        "data_sha256": {str(RAW18.relative_to(ROOT)): sha(RAW18), **{
            str(p.relative_to(ROOT)): sha(p) for p in sorted(RAW19.glob("*.csv"))}},
        "development": "First 40% of 2018 only; 3 supervised and 5 unsupervised variants explored. Development diagnostics are not final test results.",
        "retrospective_2018": "Six expanding walk-forward periods 40-50%,50-60%,60-70%,70-80%,80-90%,90-100%. Earlier v1 results have already been seen; do not call this a fresh independent benchmark.",
        "fold_definition": "For outer decile k=4..9: training [0,floor(N*(k-1)/10)); calibration [training_end+120,floor(N*k/10)); test conceptual [floor(N*k/10),floor(N*(k+1)/10)). First 120 test rows excluded; all feature/persistence history resets after gap. Excluded rows remain -1 in evaluation.",
        "gap_rows": GAP, "maximum_feature_history_predecessors": 60,
        "candidate_families": FAMILIES, "supervised_parameters": CANDIDATES,
        "unsupervised_parameters": UNSUP,
        "model_selection": "Within each fold only: feasible calibration confirmed 0-to-1 event recall, then raw point F1, then fewer FP minutes, then fixed family order. No-event calibration uses fixed family order, with lowest feasible threshold and 2of3 persistence. Never choose based on outer outcomes.",
        "threshold_selection": "alarm_policy.py hash fixes grids, tie breaks and causal instant/2of3/3of5 policies. Baseline keeps original v1 F1 objective and instant policy.",
        "constraints": {"max_false_runs_per_normal_day": 1.0, "max_normal_alarm_fraction": 0.01},
        "baseline": "Refit original v1 algorithm on each identical train/calibration split. Never use its future-trained checkpoint on an earlier fold. Same 15-row features, 200 trees, max_samples=256, seed, normal-window filtering and original threshold grid.",
        "labels": "Original current-minute binary EVENT; no expansion, point adjustment, fault-type relabeling or event-tail forgiveness. No labels as model features.",
        "missing": "No imputation; score only complete causal windows. -1 means unavailable, never normal. Report native and common-available comparisons and all event denominators.",
        "aggregation": "Reassemble predictions on the original 40%-100% axis with gaps and unavailable rows; identify each original contiguous EVENT once, not the sum of fold event totals.",
        "chronology": "Preserve acquisition row order including 2018 backward wall-clock hour; elapsed minutes are nominal.",
        "external_2019": {"training": "7_gecco2019_train_water_quality.csv", "calibration": "8_gecco2019_valid_water_qulity.csv", "final_test": "6_gecco2019_test_water_quality.csv", "order_basis": "Actual timestamps from label-blind overlap audit, not filename semantics", "gap": "Exclude first 120 rows of calibration and final test, reset history", "channels": CHANNELS19, "procedure": "Same fixed candidate-selection procedure retrained on six channels. Freeze model/threshold/persistence before loading final test labels. This is a method evaluation after retraining, not 2018 checkpoint transfer or proof of a new site."},
        "limits": ["No 3D integration", "No five-fault classification", "No water-safety certification", "No Raspberry Pi speed claim", "Model outputs cannot open valves", "Dataset events include maintenance and simulated challenge events"]
    }
    write(OUT / "protocol.json", protocol)
    print("DECLARED", sha(OUT / "protocol.json"), flush=True)


def check():
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert hashes() == protocol["code_sha256"], "Frozen method code changed"
    for p, digest in protocol["data_sha256"].items():
        assert sha(ROOT / p) == digest, f"Source changed: {p}"
    return protocol


def fit_candidate(family, train, channels):
    y = train.EVENT.to_numpy(dtype=bool)
    started = time.perf_counter()
    if family == "if_normalized_changes_w30":
        model = CausalChangeDetector({**UNSUP, "channels": channels}).fit(train[channels], ~y)
        count = model.fit_rows_
    else:
        X, eligible, _ = build_features(train, "baseline15" if family == "baseline" else "multiscale", channels)
        if family == "baseline":
            clean = pd.Series(y).rolling(15, min_periods=15).sum().eq(0).to_numpy()
            eligible &= clean
            model = IsolationForest(n_estimators=200, max_samples=256, contamination="auto", n_jobs=1, random_state=20261016)
            model.fit(X[eligible])
        else:
            model = make_model(family)
            assert np.unique(y[eligible]).size == 2, "Supervised fitting needs both classes"
            with threadpool_limits(limits=1):
                model.fit(X[eligible], y[eligible].astype(int))
        count = int(eligible.sum())
    return model, {"fit_rows": count, "fit_seconds": time.perf_counter()-started}


def scores_for(family, model, part, channels):
    # The predictor receives only channel columns, never EVENT or row identifiers.
    x = part.loc[:, channels]
    if family == "if_normalized_changes_w30":
        return model.score(x)
    X, eligible, _ = build_features(x, "baseline15" if family == "baseline" else "multiscale", channels)
    if family != "baseline":
        return score_model(model, X, eligible)
    scores = np.full(len(x), np.nan)
    if eligible.any():
        scores[eligible] = -model.score_samples(X[eligible])
    return scores


def select_models(train, calibration, channels, folder, metadata):
    folder.mkdir(parents=True, exist_ok=True)
    assert not (folder / "freeze.json").exists()
    selections, models, cal_scores = [], {}, {}
    y = calibration.EVENT.to_numpy(dtype=bool)
    for family in ["baseline"] + FAMILIES:
        model, timing = fit_candidate(family, train, channels)
        scores = scores_for(family, model, calibration, channels)
        chosen, trials = select(y, scores, baseline=(family == "baseline"))
        chosen = {**chosen, "family": family, **timing}
        selections.append(chosen)
        models[family], cal_scores[family] = model, scores
        pd.DataFrame(trials).to_csv(folder / f"{family}_calibration_trials.csv.gz", index=False)
        print(json.dumps({"stage": "calibrated", "partition": folder.name, "family": family,
                          "f1": chosen["f1"], "event_recall": chosen["confirmed_new_alarm_inside_event_recall"],
                          "false_per_day": chosen["false_alarm_runs_per_normal_day"]}), flush=True)
    candidates = [s for s in selections if s["family"] != "baseline"]
    if not y.any():
        winner = min(candidates, key=lambda s: FAMILIES.index(s["family"]))
    else:
        winner = max(candidates, key=lambda s: (s["confirmed_new_alarm_inside_event_recall"] or 0,
                    s["f1"] or 0, -s["fp"], -FAMILIES.index(s["family"])))
    baseline = selections[0]
    bundles = {}
    for role, chosen in [("baseline", baseline), ("v2", winner)]:
        family = chosen["family"]
        bundle = {"model_id": f"mawrid-{folder.name}-{role}", "family": family, "model": models[family],
                  "channels": channels, "threshold": chosen["threshold"], "policy": chosen["policy"],
                  "feature_set": ("baseline15" if role == "baseline" else
                                  "normalized_causal_changes_w30" if family == "if_normalized_changes_w30" else "multiscale"),
                  "limitations": check()["limits"], "calibration": chosen, "metadata": metadata}
        joblib.dump(bundle, folder / f"{role}_model.joblib", compress=3)
        bundles[role] = bundle
        pred = predict(cal_scores[family], chosen["threshold"], chosen["policy"])
        pd.DataFrame({"EVENT": y, "score": cal_scores[family], "prediction": pred}).to_csv(
            folder / f"{role}_calibration_predictions.csv.gz", index=False)
    freeze = {"frozen_at_utc": now(), "protocol_sha256": sha(OUT / "protocol.json"),
              "code_sha256": hashes(), "metadata": metadata,
              "training_rows": len(train), "calibration_rows": len(calibration),
              "training_event_minutes": int(train.EVENT.sum()), "calibration_event_minutes": int(y.sum()),
              "selection_candidates": selections, "selected": winner, "baseline": baseline,
              "model_sha256": {role: sha(folder / f"{role}_model.joblib") for role in bundles},
              "test_used_for_selection": False}
    write(folder / "freeze.json", freeze)
    print("FROZEN " + str(folder), flush=True)
    return bundles


def load_models(folder):
    freeze = json.loads((folder / "freeze.json").read_text())
    assert freeze["protocol_sha256"] == sha(OUT / "protocol.json")
    assert freeze["code_sha256"] == hashes()
    models = {}
    for role, digest in freeze["model_sha256"].items():
        path = folder / f"{role}_model.joblib"
        assert sha(path) == digest
        models[role] = joblib.load(path)
    return models


def assess(y, baseline, v2):
    common = (baseline >= 0) & (v2 >= 0)
    return {"native": {"baseline": evaluate(y, baseline), "v2": evaluate(y, v2)},
            "common": {"baseline": evaluate(y, np.where(common, baseline, -1)),
                       "v2": evaluate(y, np.where(common, v2, -1))}}


def evaluate_partition(part, bundles, folder, source_start_index, gap=GAP):
    assert not (folder / "test_results.json").exists(), "Test already evaluated"
    predictions, scores = {}, {}
    for role, bundle in bundles.items():
        score = scores_for(bundle["family"], bundle["model"], part.iloc[gap:].reset_index(drop=True), bundle["channels"])
        fullscore = np.r_[np.full(gap, np.nan), score]
        predictions[role] = predict(fullscore, bundle["threshold"], bundle["policy"])
        scores[role] = fullscore
    y = part.EVENT.to_numpy(dtype=bool)
    result = assess(y, predictions["baseline"], predictions["v2"])
    result.update({"scored_at_utc": now(), "source_start_index": source_start_index,
                   "source_end_index": source_start_index+len(part), "timestamp_start": str(part.Time.iloc[0]),
                   "timestamp_end": str(part.Time.iloc[-1]), "selected_family": bundles["v2"]["family"]})
    write(folder / "test_results.json", result)
    pd.DataFrame({"sample_index": np.arange(source_start_index, source_start_index+len(part)),
                  "timestamp_original": part.Time.to_numpy(), "EVENT": y,
                  "baseline_score": scores["baseline"], "baseline_prediction": predictions["baseline"],
                  "v2_score": scores["v2"], "v2_prediction": predictions["v2"]}).to_csv(folder / "test_predictions.csv.gz", index=False)
    print(json.dumps({"stage": "test", "partition": folder.name, "family": bundles["v2"]["family"],
                      "baseline": compact(result["common"]["baseline"]),
                      "v2": compact(result["common"]["v2"])}), flush=True)
    return result


def outer():
    check()
    for k in range(4, 10):
        train_end, test_start, test_end = [N18 * j // 10 for j in [k-1, k, k+1]]
        folder = OUT / f"fold_{k-3}"
        if (folder / "test_results.json").exists():
            load_models(folder)  # Safe resumption verifies locks, never retunes.
            continue
        if not (folder / "freeze.json").exists():
            prefix = pd.read_csv(RAW18, nrows=test_start)
            assert len(prefix) == test_start
            metadata = {"train": [0, train_end], "calibration": [train_end+GAP, test_start],
                        "test": [test_start, test_end], "actual_scoring_starts": test_start+GAP,
                        "source": str(RAW18.relative_to(ROOT)), "selection_max_source_index": test_start-1}
            select_models(prefix.iloc[:train_end].reset_index(drop=True),
                          prefix.iloc[train_end+GAP:].reset_index(drop=True), CHANNELS, folder, metadata)
        bundles = load_models(folder)
        part = pd.read_csv(RAW18, nrows=test_end).iloc[test_start:].reset_index(drop=True)
        evaluate_partition(part, bundles, folder, test_start)
    frames = [pd.read_csv(OUT / f"fold_{k}/test_predictions.csv.gz") for k in range(1, 7)]
    combined = pd.concat(frames, ignore_index=True)
    assert np.array_equal(combined.sample_index, np.arange(N18*4//10, N18))
    result = assess(combined.EVENT.to_numpy(dtype=bool), combined.baseline_prediction.to_numpy(dtype=int), combined.v2_prediction.to_numpy(dtype=int))
    result.update({"scope": "2018 retrospective 40%-100%, global contiguous event IDs", "source_start": N18*4//10,
                   "source_end": N18, "folds": 6, "protocol_sha256": sha(OUT / "protocol.json")})
    # Every event, including unavailable events, remains on the same full axis.
    combined.to_csv(OUT / "walk_forward_predictions.csv.gz", index=False)
    write(OUT / "walk_forward_results.json", result)
    print("WALK_FORWARD_COMPLETE", flush=True)


def external_calibrate():
    check()
    folder = OUT / "external_2019"
    assert not (folder / "freeze.json").exists()
    train = pd.read_csv(RAW19 / "7_gecco2019_train_water_quality.csv").rename(columns={"Event": "EVENT"})
    cal = pd.read_csv(RAW19 / "8_gecco2019_valid_water_qulity.csv").rename(columns={"Event": "EVENT"})
    assert pd.to_datetime(train.Time).max() < pd.to_datetime(cal.Time).min()
    metadata = {"training_file": "7_gecco2019_train_water_quality.csv", "calibration_file": "8_gecco2019_valid_water_qulity.csv",
                "final_file": "6_gecco2019_test_water_quality.csv", "train_end_time": str(train.Time.iloc[-1]),
                "calibration_start_time": str(cal.Time.iloc[GAP]), "calibration_end_time": str(cal.Time.iloc[-1]),
                "final_file_labels_not_loaded": True, "chronological_order_audited": True,
                "method_retrained_on_new_six_channel_schema": True}
    select_models(train, cal.iloc[GAP:].reset_index(drop=True), CHANNELS19, folder, metadata)


def external_test():
    check()
    folder = OUT / "external_2019"
    assert not (folder / "test_results.json").exists(), "Final holdout already evaluated"
    bundles = load_models(folder)
    # First label access to the newest 2019 period occurs only after model locks.
    part = pd.read_csv(RAW19 / "6_gecco2019_test_water_quality.csv").rename(columns={"Event": "EVENT"})
    freeze = json.loads((folder / "freeze.json").read_text())
    assert pd.to_datetime(freeze["metadata"]["calibration_end_time"]) < pd.to_datetime(part.Time).min()
    evaluate_partition(part, bundles, folder, source_start_index=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["declare", "outer", "external-calibrate", "external-test"])
    parser.add_argument("--output-dir", type=Path, default=OUT,
                        help="Use a new directory to reproduce without replacing frozen results")
    args = parser.parse_args()
    OUT = args.output_dir.resolve()
    {"declare": declare, "outer": outer, "external-calibrate": external_calibrate,
     "external-test": external_test}[args.stage]()
