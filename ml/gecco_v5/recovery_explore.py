"""Two predeclared V5 recipes on disclosed GECCO2017/2018/2019 development.

Fit and calibration use a past prefix only. The next test slice is read and
scored only after both candidates' calibration decisions have been recorded.
Never accesses another source. Sample cadence is60seconds for these streams.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "ml/gecco_v2"))
from alarm_policy import select, predict as baseline_predict
from recovery_candidate import RecoveryEventDetector, CONFIGS, CHANNELS18, CHANNELS19, CLASSIFIER_PARAMS
from evaluation import compare_period, assess_series, gates
from calibration import calibrate, predict

OUT = ROOT / "output/ml/gecco-v5-recovery-development"
GAP = 120
SAMPLE_SECONDS = 60


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def source_hashes():
    paths = [HERE / name for name in ["recovery_candidate.py", "recovery_explore.py", "calibration.py", "evaluation.py"]]
    paths += [ROOT / "ml/gecco_baseline/metrics.py", ROOT / "ml/gecco_v2/alarm_policy.py", ROOT / "ml/gecco_v2/candidates_supervised.py"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def compact(value):
    if isinstance(value, dict):
        return {key: compact(v) for key, v in value.items() if key not in ("event_records", "false_alarm_records")}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def score_gap(model, frame):
    part = frame.iloc[GAP:].reset_index(drop=True)
    values = model.score_components(part)
    return {key: np.r_[np.full(min(GAP, len(frame)), np.nan), value] for key, value in values.items()}


def parity(actual, reference, name, prefix_gap=False):
    if prefix_gap:
        reference = np.r_[np.full(GAP, np.nan), reference]
    np.testing.assert_allclose(actual, reference, rtol=0, atol=1e-12, equal_nan=True, err_msg=name)
    valid = np.isfinite(actual) & np.isfinite(reference)
    return {"comparison": name, "passed": True, "max_absolute_difference": float(np.max(np.abs(actual[valid] - reference[valid]))) if valid.any() else 0.}


def run_case(name, train, cal_frames, cal_starts, load_test, test_start, channels,
             reference_folder, cal_single_frame=False):
    folder = OUT / name
    folder.mkdir()
    models = {}; selections = {}; scores = {}; base_choice = None; bp_cal = None
    started = time.perf_counter()
    labels = [block.EVENT.to_numpy(dtype=bool) for block in cal_frames]
    # For2019, preserve the original continuousVALID scoring context and gap.
    whole_cal = pd.concat(cal_frames, ignore_index=True) if cal_single_frame else None
    for config_id in CONFIGS:
        model = RecoveryEventDetector(config_id, channels).fit(train, train.EVENT.to_numpy(dtype=bool))
        models[config_id] = model
        if cal_single_frame:
            whole = score_gap(model, whole_cal)
            boundaries = np.r_[0, np.cumsum([len(block) for block in cal_frames])]
            parts = [{key: value[a:b] for key, value in whole.items()} for a, b in zip(boundaries[:-1], boundaries[1:])]
        else:
            parts = [score_gap(model, block) for block in cal_frames]
        scores[config_id] = parts
        bs = np.concatenate([p["baseline"] for p in parts])
        if base_choice is None:
            base_choice, base_trials = select(np.concatenate(labels), bs, baseline=True)
            bp_cal = [baseline_predict(p["baseline"], base_choice["threshold"], "instant") for p in parts]
            pd.DataFrame(base_trials).to_csv(folder / "baseline_calibration_trials.csv.gz", index=False)
        else:
            np.testing.assert_array_equal(bs, np.concatenate([p["baseline"] for p in scores[next(iter(CONFIGS))]]))
        blocks = [{"labels": y, "scores": part["shape"], "baseline_predictions": bp,
                   "source_start": int(start), "block_id": f"{name}_cal_{j + 1}"}
                  for j, (y, part, bp, start) in enumerate(zip(labels, parts, bp_cal, cal_starts))]
        selected, trials = calibrate(blocks)
        selections[config_id] = selected
        pd.DataFrame(trials).to_csv(folder / f"{config_id}_calibration_trials.csv.gz", index=False)
        print(json.dumps({"stage": "calibrated", "case": name, "config": config_id,
                          "fit_rows": model.fit_rows_, "fit_events": model.fit_events_,
                          "decision": selected.get("decision"), "mode": selected.get("mode"),
                          "elapsed": time.perf_counter() - started}), flush=True)
    if cal_single_frame:
        reference_cal = pd.read_csv(reference_folder / "baseline_calibration_predictions.csv.gz", usecols=["score"])["score"].to_numpy()
        cal_parity = parity(bs, reference_cal, "original_V3_2019_baseline_calibration", prefix_gap=True)
    else:
        reference_cal = pd.read_csv(reference_folder / "calibration_predictions.csv.gz", usecols=["baseline_score"])["baseline_score"].to_numpy()
        cal_parity = parity(bs, reference_cal, "original_V4_baseline_calibration")
    # This record precedes opening/scoring the next development slice.
    write(folder / "freeze.json", {"development_only": True, "code_sha256": source_hashes(),
           "training_rows": len(train), "calibration_starts": cal_starts, "test_start": test_start,
           "baseline": base_choice, "selected": selections, "calibration_parity": cal_parity,
           "test_labels_or_features_used_for_selection": False})
    test = load_test()
    y = test.EVENT.to_numpy(dtype=bool)
    outputs = {"EVENT": y, "sample_index": np.arange(test_start, test_start + len(test))}
    result = {}; reference = pd.read_csv(reference_folder / "test_predictions.csv.gz", usecols=["baseline_score", "baseline_prediction"])
    for config_id, model in models.items():
        parts = score_gap(model, test)
        bp = baseline_predict(parts["baseline"], base_choice["threshold"], "instant")
        cp = predict(parts["shape"], bp, selections[config_id])
        score_parity = parity(parts["baseline"], reference.baseline_score.to_numpy(), "original_baseline_test_score")
        np.testing.assert_array_equal(bp, reference.baseline_prediction.to_numpy())
        measured = compare_period(y, bp, cp, SAMPLE_SECONDS)
        measured.update({"development_only": True, "case": name, "source_start": test_start,
                         "baseline_parity": score_parity, "selection": selections[config_id]})
        result[config_id] = measured
        outputs["baseline"] = bp
        outputs[config_id] = cp
        outputs[config_id + "__shape_score"] = parts["shape"]
        b, c = measured["baseline"], measured["candidate"]
        print(json.dumps({"stage": "development_result", "case": name, "config": config_id,
              "baseline_confirmed": b["confirmed_new_alarm_inside_events"], "candidate_confirmed": c["confirmed_new_alarm_inside_events"],
              "events": c["true_events"], "lost_ids": len(measured["lost_baseline_events"]),
              "baseline_FPday": b["false_alarm_runs_per_normal_day"], "candidate_FPday": c["false_alarm_runs_per_normal_day"],
              "baseline_FPtime": b["normal_time_under_alarm"], "candidate_FPtime": c["normal_time_under_alarm"],
              "noninferior": measured["noninferior"], "elapsed": time.perf_counter() - started}), flush=True)
    pd.DataFrame(outputs).to_csv(folder / "development_predictions.csv.gz", index=False)
    write(folder / "results.json", result)
    return result, outputs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "plan.json").exists():
        raise SystemExit("Existing attempt retained; do not replace development history")
    plan = {"development_only": True, "source_scope": "Previously disclosed GECCO2017/2018/2019 only",
            "configs": CONFIGS, "classifier": CLASSIFIER_PARAMS, "maximum_lookback_samples": 60,
            "sample_seconds": SAMPLE_SECONDS, "gap_samples": GAP,
            "geometry_2017_2018": "Six expanding deciles40..100%; train throughprevious20%; four5%cal blocks; reset after120gap eachcal/testblock",
            "geometry_2019": "FullTRAIN, fullVALID scored continuously afterone120gap then partitioned into4 calibration blocks; TEST afterfreeze with120gap. Matches originalV3baselinecontext.",
            "comparison": "Exact original IF fitting/scoring/recalibration; assert score and prediction parity against oldV4/V3 artifacts. Native event identities, lost/gained and latency retained; common-availability secondary.",
            "selection": "calibration.py preserves individual baseline-detected event identities; fallback retains baseline when evidence unsupported",
            "code_sha256": source_hashes(), "new_source_accessed": False}
    write(OUT / "plan.json", plan)
    series = {}; all_periods = {key: [] for key in CONFIGS}
    for year, n in [("2017", 122334), ("2018", 139566)]:
        raw = ROOT / f"data/external/gecco{year}/1_gecco{year}_water_quality.csv"
        pieces = []; bounds = [0]
        for k in range(4, 10):
            end_train, start_test, end_test = [n * part // 10 for part in (k - 2, k, k + 1)]
            prefix = pd.read_csv(raw, nrows=start_test)
            boundaries = np.linspace(end_train, start_test, 5, dtype=int)
            cal = [prefix.iloc[a:b].reset_index(drop=True) for a, b in zip(boundaries[:-1], boundaries[1:])]
            folder = ROOT / "output/ml/gecco-v4" / ("external_2017" if year == "2017" else "development_2018") / f"fold_{k - 3}"
            result, values = run_case(f"{year}_fold_{k - 3}", prefix.iloc[:end_train].reset_index(drop=True), cal,
                       boundaries[:-1].tolist(), lambda p=raw, a=start_test, b=end_test: pd.read_csv(p, nrows=b).iloc[a:].reset_index(drop=True),
                       start_test, CHANNELS18, folder)
            pieces.append(values); bounds.append(bounds[-1] + len(values["EVENT"]))
            for key in CONFIGS:
                all_periods[key].append(result[key])
        combined = {key: np.concatenate([part[key] for part in pieces]) for key in pieces[0]}
        series[year] = {key: assess_series(combined["EVENT"], combined["baseline"], combined[key], bounds, SAMPLE_SECONDS) for key in CONFIGS}
        write(OUT / f"{year}_pooled.json", compact(series[year]))
    folder = ROOT / "data/external/gecco2019"
    train = pd.read_csv(folder / "7_gecco2019_train_water_quality.csv").rename(columns={"Event": "EVENT"})
    valid = pd.read_csv(folder / "8_gecco2019_valid_water_qulity.csv").rename(columns={"Event": "EVENT"})
    limits = np.linspace(0, len(valid), 5, dtype=int)
    cal = [valid.iloc[a:b].reset_index(drop=True) for a, b in zip(limits[:-1], limits[1:])]
    result, values = run_case("2019_disclosed_test", train, cal, (limits[:-1] + len(train)).tolist(),
                  lambda: pd.read_csv(folder / "6_gecco2019_test_water_quality.csv").rename(columns={"Event": "EVENT"}),
                  len(train) + len(valid), CHANNELS19, ROOT / "output/ml/gecco-v3/external_2019", cal_single_frame=True)
    for key in CONFIGS:
        all_periods[key].append(result[key])
    overall = {key: gates(all_periods[key], [series[year][key]["pooled"] for year in ("2017", "2018")] + [result[key]]) for key in CONFIGS}
    write(OUT / "results.json", {"development_only": True, "overall": overall,
          "2017": compact(series["2017"]), "2018": compact(series["2018"]), "2019": compact(result)})


if __name__ == "__main__":
    main()
