"""Logged, past-only experiments on already disclosed GECCO2018/2019.

No GECCO2017 path is read. All experiments, including failures, are retained.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "ml/gecco_baseline"))
sys.path.insert(0, str(ROOT / "ml/gecco_v2"))
from metrics import evaluate
from alarm_policy import predict, select
from candidates_supervised import build_features
from adaptive_candidate import AdaptiveChangeDetector, CONFIGS, CHANNELS18, CHANNELS19

OUT = ROOT / "output/ml/gecco-v4-adaptive-development"
GAP = 120


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")


def brief(metrics):
    return {k: v for k, v in metrics.items() if not k.endswith("records")}


def calibrate(blocks):
    """Past (labels, score) blocks only; constrain EACH block separately.

    Rank by worst complete-event recall, pooled complete-event recall, point F1,
    fewer false-positive minutes, higher threshold. With no calibration events,
    select the threshold above all past scores (zero known false positives),
    using the instant policy. No event labels are fabricated for normal blocks.
    """
    finite = np.concatenate([s[np.isfinite(s)] for _, s in blocks])
    if not len(finite):
        raise ValueError("No finite calibration scores")
    quantiles = np.unique(np.r_[np.linspace(0, .9, 37), np.linspace(.9, 1, 65)])
    thresholds = np.unique(np.r_[0., np.quantile(finite, quantiles), np.nextafter(finite.max(), np.inf)])
    no_events = not any(np.any(y) for y, _ in blocks)
    trials = []
    for policy in ("instant", "2of3", "3of5"):
        for threshold in thresholds:
            ms = [evaluate(y, predict(s, threshold, policy)) for y, s in blocks]
            tp = sum(m["tp"] for m in ms); fp = sum(m["fp"] for m in ms); fn = sum(m["fn"] for m in ms)
            events = sum(m["complete_events"] for m in ms)
            confirmed = sum(m["complete_confirmed_new_alarm_inside_events"] for m in ms)
            recalls = [m["complete_confirmed_new_alarm_start_recall"] for m in ms if m["complete_events"]]
            feasible = all(m["false_alarm_runs_per_normal_day"] is not None and
                           m["normal_time_under_alarm"] is not None and
                           m["false_alarm_runs_per_normal_day"] <= 1 and
                           m["normal_time_under_alarm"] <= .01 for m in ms)
            trials.append({"threshold": float(threshold), "policy": policy,
                "feasible_all_blocks": feasible, "no_events": no_events,
                "worst_event_block_recall": min(recalls) if recalls else 0.,
                "pooled_confirmed_recall": confirmed / events if events else 0.,
                "complete_events": events, "complete_confirmed": confirmed,
                "pooled_point_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.,
                "fp_minutes": fp,
                "worst_false_runs_per_day": max(m["false_alarm_runs_per_normal_day"] or 0. for m in ms),
                "worst_normal_alarm_fraction": max(m["normal_time_under_alarm"] or 0. for m in ms)})
    feasible = [r for r in trials if r["feasible_all_blocks"]]
    if not feasible:
        raise ValueError("Insufficient normal exposure in calibration blocks")
    if no_events:
        chosen = max([r for r in feasible if r["policy"] == "instant"], key=lambda r: r["threshold"])
    else:
        chosen = max(feasible, key=lambda r: (r["worst_event_block_recall"], r["pooled_confirmed_recall"],
                     r["pooled_point_f1"], -r["fp_minutes"], r["threshold"], r["policy"] == "instant"))
    return dict(chosen), trials


def fit_baseline(train, channels):
    X, eligible, _ = build_features(train, "baseline15", channels)
    clean = (~train.EVENT.astype(bool)).rolling(15, min_periods=15).sum().eq(15).to_numpy()
    model = IsolationForest(n_estimators=200, max_samples=256, contamination="auto",
                            random_state=20261016, n_jobs=1)
    model.fit(X[eligible & clean])
    return model


def score_baseline(model, frame, channels):
    X, eligible, _ = build_features(frame, "baseline15", channels)
    score = np.full(len(frame), np.nan)
    score[eligible] = -model.score_samples(X[eligible])
    return score


def score_with_gap(model, frame, channels, baseline=False):
    score = np.full(len(frame), np.nan)
    work = frame.iloc[GAP:].reset_index(drop=True)
    score[GAP:] = score_baseline(model, work, channels) if baseline else model.score(work)
    return score


def compare(y, pred, baseline):
    common = (pred >= 0) & (baseline >= 0)
    p = np.where(common, pred, -1); b = np.where(common, baseline, -1)
    return {"native": brief(evaluate(y, pred)), "baseline_native": brief(evaluate(y, baseline)),
            "common": brief(evaluate(y, p)), "baseline_common": brief(evaluate(y, b))}


def run_case(name, train, calibration, test, channels, bounds, config_ids=None):
    started = time.perf_counter()
    y = test.EVENT.to_numpy(dtype=bool)
    base = fit_baseline(train, channels)
    base_cal = [score_with_gap(base, block, channels, True) for block in calibration]
    base_choice, base_trials = select(np.concatenate([b.EVENT.to_numpy(dtype=bool) for b in calibration]),
                                      np.concatenate(base_cal), baseline=True)
    bs = score_with_gap(base, test, channels, True)
    bp = predict(bs, base_choice["threshold"], base_choice["policy"])
    results, predictions = [], {"EVENT": y, "baseline": bp}
    pd.DataFrame(base_trials).to_csv(OUT / f"{name}_baseline_calibration.csv.gz", index=False)
    for config_id in (list(CONFIGS) if config_ids is None else config_ids):
        detector = AdaptiveChangeDetector(config_id, channels).fit(train, train.EVENT.to_numpy(dtype=bool))
        cal = [(block.EVENT.to_numpy(dtype=bool), score_with_gap(detector, block, channels)) for block in calibration]
        chosen, trials = calibrate(cal)
        score = score_with_gap(detector, test, channels)
        pred = predict(score, chosen["threshold"], chosen["policy"])
        measured = compare(y, pred, bp)
        record = {"case": name, "config_id": config_id, "development_only": True,
                  "source_bounds": bounds, "training_rows": len(train), "fit_rows": detector.fit_rows_,
                  "max_lookback": detector.max_lookback_, "calibration": chosen,
                  "baseline_calibration": base_choice, "gap_rows": GAP,
                  "current_missing_rows_after_gap": int(test.iloc[GAP:][channels].isna().any(axis=1).sum()),
                  "minimum_feature_history": detector.minimum_history_, **measured}
        results.append(record)
        predictions[config_id] = pred
        predictions[config_id + "__score"] = score
        pd.DataFrame(trials).to_csv(OUT / f"{name}_{config_id}_calibration.csv.gz", index=False)
        write(OUT / f"{name}_{config_id}_events.json", evaluate(y, pred)["event_records"])
        m = measured["common"]; b = measured["baseline_common"]
        print(json.dumps({"case": name, "config": config_id, "confirmed": [m["confirmed_new_alarm_inside_events"], m["true_events"]],
              "baseline_confirmed": b["confirmed_new_alarm_inside_events"], "FPday": m["false_alarm_runs_per_normal_day"],
              "baseline_FPday": b["false_alarm_runs_per_normal_day"], "FPtime": m["normal_time_under_alarm"],
              "F1": m["f1"], "coverage": measured["native"]["prediction_coverage"],
              "threshold": chosen["threshold"], "policy": chosen["policy"], "elapsed": time.perf_counter() - started}), flush=True)
    pd.DataFrame(predictions).to_csv(OUT / f"{name}_predictions.csv.gz", index=False)
    write(OUT / f"{name}_results.json", results)
    return results, predictions


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", default="")
    parser.add_argument("--config-ids", nargs="+", choices=list(CONFIGS), default=list(CONFIGS))
    args = parser.parse_args()
    if args.attempt:
        if Path(args.attempt).name != args.attempt:
            raise ValueError("attempt must be a directory name")
        OUT = OUT / args.attempt
    config_ids = args.config_ids
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "plan.json").exists():
        raise SystemExit("Existing experiment retained; do not silently replace results")
    plan = {"development_only": True, "all_tried_recipes": {key: CONFIGS[key] for key in config_ids},
            "data_access": "Previously disclosed GECCO2018/2019 only; no independent new source",
            "geometry": "2018: train [0,k-2 decile), four calibration blocks of5% until k decile, test k..k+1 decile. k4..9. Every cal/test block retains120 excluded rows then resets features. Original labels and source axis retained.",
            "2019": "Train first80%TRAIN; calibrate last20%TRAIN and two halvesVALID; disclosedTESTevaluation.120leading gap each block retained in event denominator.",
            "selection": "Each calibration block constraints<=1 false run per eligible normal day and<=1% normal alarmtime; worst complete-event recall then pooled recall then F1 then fewerFP then higherthreshold. No-event: above past maximum,instant.",
            "baseline": "Original v1 IF features/normalfit/thresholdobjective, sametrain andcalibration blocks, instant predictions. Original raw labels throughout.",
            "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), HERE / "adaptive_candidate.py"]}}
    write(OUT / "plan.json", plan)
    data = pd.read_csv(ROOT / "data/external/gecco2018/1_gecco2018_water_quality.csv")
    results = []; pieces = []
    n = len(data)
    for k in range(4, 10):
        te, ts, end = n * (k - 2) // 10, n * k // 10, n * (k + 1) // 10
        boundaries = np.linspace(te, ts, 5, dtype=int)
        blocks = [data.iloc[a:b].reset_index(drop=True) for a, b in zip(boundaries[:-1], boundaries[1:])]
        records, predictions = run_case(f"2018_fold_{k - 3}", data.iloc[:te].reset_index(drop=True), blocks,
                  data.iloc[ts:end].reset_index(drop=True), CHANNELS18,
                  {"train": [0, te], "calibration_blocks": [[int(a), int(b)] for a, b in zip(boundaries[:-1], boundaries[1:])], "test": [ts, end]}, config_ids)
        results += records; pieces.append(predictions)
    combined = {key: np.concatenate([p[key] for p in pieces]) for key in pieces[0]}
    pooled = {c: compare(combined["EVENT"], combined[c], combined["baseline"]) for c in config_ids}
    write(OUT / "2018_pooled.json", pooled)
    folder = ROOT / "data/external/gecco2019"
    train = pd.read_csv(folder / "7_gecco2019_train_water_quality.csv").rename(columns={"Event": "EVENT"})
    valid = pd.read_csv(folder / "8_gecco2019_valid_water_qulity.csv").rename(columns={"Event": "EVENT"})
    test = pd.read_csv(folder / "6_gecco2019_test_water_quality.csv").rename(columns={"Event": "EVENT"})
    end, mid = int(len(train) * .8), len(valid) // 2
    records, _ = run_case("2019_disclosed_final", train.iloc[:end].reset_index(drop=True),
                         [train.iloc[end:].reset_index(drop=True), valid.iloc[:mid].reset_index(drop=True), valid.iloc[mid:].reset_index(drop=True)],
                         test, CHANNELS19, {"train": [0, end], "calibration": "last20%TRAIN,halfVALID,halfVALID", "test": "all disclosedTEST"}, config_ids)
    results += records
    write(OUT / "results.json", {"development_only": True, "all_tried_recipes": config_ids, "results": results, "2018_pooled": pooled})


if __name__ == "__main__":
    main()
