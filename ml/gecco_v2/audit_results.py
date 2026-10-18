"""Independent, read-only audit of the completed, frozen v2 experiment.

Never imports the production metrics, selector, or model modules. It does not
open any 2019 CSV until the final external result and every required output
exist. Only final_audit.json is written; no model decisions are made here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/ml/gecco-v2"
DECLARED_PROTOCOL_SHA256 = "3e29a4d1bd62a444c5121525a50b35b04e68366c44e455d2deff4e7d980b3b2e"
V1_SNAPSHOT = {
    "output/ml/gecco-baseline-v1/freeze.json": "608fb0cc477132f4b0b8cbac5c8a787d9e94416df8ef9daa84da67e88cee70a4",
    "output/ml/gecco-baseline-v1/test_results.json": "219db24a77a871d2605c7357c0029339f0f957d05b39362915451132509efadd",
    "output/ml/gecco-baseline-v1/test_predictions.csv.gz": "d1ba275df2142648a2d97598e24106f952a2c38e94fa7f2c66a89b24daf2efae",
    "output/ml/gecco-baseline-v1/model.joblib": "40dc599fd27d583674e3cf81dcef206af14d6a4ca3b3f8b4f1eaa3e4c12f3bef",
    "output/ml/gecco-baseline-v1/data_manifest.json": "a51f0c46f6c56ad26aa03aa08a9d6012e7d0becaf62c3641c93443d1b9f8136d",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def read_csv(path, **kwargs):
    # Preserve threshold-adjacent score bits when checking >= decisions.
    return pd.read_csv(path, float_precision="round_trip", **kwargs)


def spans(flags):
    result, beginning = [], None
    for index, active in enumerate([*map(bool, flags), False]):
        if active and beginning is None:
            beginning = index
        elif not active and beginning is not None:
            result.append((beginning, index))
            beginning = None
    return result


def ratio(top, bottom):
    return float(top / bottom) if bottom else None


def independent_metrics(labels, predictions):
    y, p = list(map(bool, labels)), list(map(int, predictions))
    assert len(y) == len(p) and set(p).issubset({-1, 0, 1})
    valid = [v != -1 for v in p]
    alarm = [v == 1 for v in p]
    raw_starts = [a and (i == 0 or p[i - 1] != 1) for i, a in enumerate(alarm)]
    confirmed = [a and i > 0 and p[i - 1] == 0 for i, a in enumerate(alarm)]
    tp = sum(t and v == 1 for t, v in zip(y, p))
    fp = sum(not t and v == 1 for t, v in zip(y, p))
    fn = sum(t and v == 0 for t, v in zip(y, p))
    tn = sum(not t and v == 0 for t, v in zip(y, p))
    false_runs = spans([not t and a for t, a in zip(y, alarm)])
    events, delays = [], []
    for start, end in spans(y):
        positive = next((i for i in range(start, end) if alarm[i]), None)
        fresh = next((i for i in range(start, end) if raw_starts[i]), None)
        certain = next((i for i in range(start, end) if confirmed[i]), None)
        covered, onset = positive is not None, alarm[start]
        available = sum(valid[start:end])
        unknown_previous = fresh is not None and fresh > 0 and p[fresh - 1] == -1
        if covered:
            delays.append(positive - start)
        events.append({
            "event_id": len(events) + 1, "start": start, "end": end,
            "duration_minutes": end - start,
            "boundary_censored": start == 0 or end == len(y),
            "valid_count": available, "unavailable_count": end - start - available,
            "fully_unscorable": available == 0, "detected": covered,
            "first_alarm_index": positive,
            "detection_delay_minutes": positive - start if covered else None,
            "covered_at_onset": onset, "new_alarm_inside_event": fresh is not None,
            "new_alarm_start_index": fresh,
            "new_alarm_delay_minutes": fresh - start if fresh is not None else None,
            "new_alarm_previous_unavailable": unknown_previous,
            "new_alarm_previous_unknown": fresh == 0 or unknown_previous,
            "confirmed_new_alarm_inside_event": certain is not None,
            "confirmed_new_alarm_index": certain,
            "confirmed_new_alarm_delay_minutes": certain - start if certain is not None else None,
            "alarm_started_at_onset": raw_starts[start],
            "detection_kind": "covered_at_onset" if onset else "first_alarm_after_onset" if covered else "undetected",
        })
    count = len(events)
    detected = sum(e["detected"] for e in events)
    fresh = sum(e["new_alarm_inside_event"] for e in events)
    certain = sum(e["confirmed_new_alarm_inside_event"] for e in events)
    complete = [e for e in events if not e["boundary_censored"]]
    complete_detected = sum(e["detected"] for e in complete)
    complete_fresh = sum(e["new_alarm_inside_event"] for e in complete)
    complete_certain = sum(e["confirmed_new_alarm_inside_event"] for e in complete)
    normal_days = (fp + tn) / 1440
    return {
        "sample_count": len(y), "valid_count": sum(valid), "unavailable_count": len(y) - sum(valid),
        "prediction_coverage": ratio(sum(valid), len(y)), "normal_valid_count": fp + tn,
        "positive_valid_count": tp + fn, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn), "false_positive_rate": ratio(fp, fp + tn),
        "false_negative_rate": ratio(fn, fn + tp), "specificity": ratio(tn, tn + fp),
        "accuracy": ratio(tp + tn, sum(valid)), "false_positive_runs": len(false_runs),
        "eligible_normal_days": normal_days, "false_alarm_runs_per_normal_day": ratio(len(false_runs), normal_days),
        "normal_time_under_alarm": ratio(fp, fp + tn), "alarm_runs": len(spans(alarm)),
        "true_events": count, "detected_events": detected, "undetected_events": count - detected,
        "fully_unscorable_events": sum(e["fully_unscorable"] for e in events),
        "event_recall": ratio(detected, count), "new_alarm_inside_event_recall": ratio(fresh, count),
        "raw_new_alarm_inside_event_recall": ratio(fresh, count),
        "confirmed_new_alarm_inside_event_recall": ratio(certain, count),
        "covered_at_onset_events": sum(e["covered_at_onset"] for e in events),
        "new_alarm_inside_events": fresh, "raw_new_alarm_inside_events": fresh,
        "confirmed_new_alarm_inside_events": certain, "boundary_censored_events": count - len(complete),
        "complete_events": len(complete), "complete_detected_events": complete_detected,
        "complete_new_alarm_inside_events": complete_fresh,
        "complete_confirmed_new_alarm_inside_events": complete_certain,
        "complete_event_coverage": ratio(complete_detected, len(complete)),
        "complete_event_new_alarm_start_recall": ratio(complete_fresh, len(complete)),
        "complete_raw_new_alarm_start_recall": ratio(complete_fresh, len(complete)),
        "complete_confirmed_new_alarm_start_recall": ratio(complete_certain, len(complete)),
        "median_detection_delay_minutes": float(np.median(delays)) if delays else None,
        "p95_detection_delay_minutes": float(np.percentile(delays, 95)) if delays else None,
        "event_records": events,
        "false_alarm_records": [{"start": s, "end": e, "duration_minutes": e - s} for s, e in false_runs],
    }


def independent_policy(scores, threshold, policy):
    required, width = {"instant": (1, 1), "2of3": (2, 3), "3of5": (3, 5)}[policy]
    output = []
    for i in range(len(scores)):
        window = scores[max(0, i - width + 1):i + 1]
        if len(window) != width or not all(math.isfinite(float(v)) for v in window):
            output.append(-1)
        else:
            output.append(int(sum(v >= threshold for v in window) >= required))
    return np.asarray(output, dtype=int)


class Audit:
    def __init__(self):
        self.checked = 0
        self.findings = []
        self.summary = {}

    def check(self, condition, location, detail=None):
        self.checked += 1
        if not bool(condition):
            self.findings.append({"location": location, "detail": str(detail)})

    def compare(self, expected, actual, location):
        if isinstance(expected, dict):
            for key, value in expected.items():
                self.check(key in actual, location + "." + key, "missing key")
                if key in actual:
                    self.compare(value, actual[key], location + "." + key)
        elif isinstance(expected, list):
            self.check(len(expected) == len(actual), location, "record count differs")
            for i, (a, b) in enumerate(zip(expected, actual)):
                self.compare(a, b, f"{location}[{i}]")
        elif isinstance(expected, float):
            self.check(actual is not None and math.isclose(expected, float(actual), rel_tol=1e-12, abs_tol=1e-12),
                       location, {"expected": expected, "actual": actual})
        else:
            self.check(expected == actual, location, {"expected": expected, "actual": actual})

    def metric_pair(self, frame, saved, location):
        y = frame.EVENT.to_numpy(dtype=bool)
        base, newer = [frame[f"{role}_prediction"].to_numpy(dtype=int) for role in ["baseline", "v2"]]
        common = (base >= 0) & (newer >= 0)
        for scope in ["native", "common"]:
            for role, p in [("baseline", base), ("v2", newer)]:
                values = p if scope == "native" else np.where(common, p, -1)
                independent = independent_metrics(y, values)
                self.compare(independent, saved[scope][role], f"{location}.{scope}.{role}")
        self.summary[location] = {role: {key: saved["common"][role][key] for key in
            ["tp", "fp", "fn", "tn", "f1", "true_events", "confirmed_new_alarm_inside_events",
             "false_alarm_runs_per_normal_day", "normal_time_under_alarm"]} for role in ["baseline", "v2"]}


def clean(value):
    return None if isinstance(value, float) and math.isnan(value) else value


def scalar(value):
    return 0 if value is None or (isinstance(value, float) and math.isnan(value)) else value


def audit_selection(audit, folder, freeze, calibration_labels, family_order):
    no_events = not bool(np.any(calibration_labels))
    selected_candidates = []
    for family in ["baseline", *family_order]:
        trials = read_csv(folder / f"{family}_calibration_trials.csv.gz").to_dict("records")
        for row in trials:
            rate, duration = row["false_alarm_runs_per_normal_day"], row["normal_time_under_alarm"]
            feasible = math.isfinite(rate) and math.isfinite(duration) and rate <= 1 and duration <= .01
            audit.check(feasible == row["feasible"], f"{folder.name}.{family}.feasibility")
            audit.check(no_events == row["no_events"], f"{folder.name}.{family}.no_events")
        options = [r for r in trials if r["feasible"]]
        if family == "baseline":
            expected = max(options, key=lambda r: (scalar(r["f1"]), -r["fp"], r["threshold"]))
        elif no_events:
            expected = min((r for r in options if r["policy"] == "2of3"), key=lambda r: r["threshold"])
        else:
            expected = max(options, key=lambda r: (scalar(r["confirmed_new_alarm_inside_event_recall"]),
                scalar(r["f1"]), -r["fp"], r["threshold"], r["policy"] == "instant"))
        recorded = next(r for r in freeze["selection_candidates"] if r["family"] == family)
        audit.compare({k: clean(v) for k, v in expected.items()}, recorded, f"{folder.name}.{family}.selected")
        selected_candidates.append(recorded)
    options = selected_candidates[1:]
    if no_events:
        winner = min(options, key=lambda r: family_order.index(r["family"]))
    else:
        winner = max(options, key=lambda r: (scalar(r["confirmed_new_alarm_inside_event_recall"]),
            scalar(r["f1"]), -r["fp"], -family_order.index(r["family"])))
    audit.compare(winner, freeze["selected"], folder.name + ".winning_family")
    for role, selection in [("baseline", freeze["baseline"]), ("v2", freeze["selected"])]:
        frame = read_csv(folder / f"{role}_calibration_predictions.csv.gz")
        audit.check(np.array_equal(frame.EVENT.to_numpy(dtype=bool), calibration_labels), folder.name + ".calibration_original_labels")
        independent = independent_policy(frame.score.to_numpy(), selection["threshold"], selection["policy"])
        audit.check(np.array_equal(independent, frame.prediction.to_numpy()), f"{folder.name}.{role}.calibration_policy")
        metrics = independent_metrics(calibration_labels, independent)
        audit.compare({key: metrics[key] for key in selection if key in metrics}, selection, f"{folder.name}.{role}.calibration_metrics")


def audit_partition(audit, folder, source_part, start, calibration, protocol):
    freeze, result = read_json(folder / "freeze.json"), read_json(folder / "test_results.json")
    audit.check(freeze["protocol_sha256"] == DECLARED_PROTOCOL_SHA256, folder.name + ".protocol_lock")
    audit.compare(protocol["code_sha256"], freeze["code_sha256"], folder.name + ".code_lock")
    for role, digest in freeze["model_sha256"].items():
        audit.check(sha(folder / f"{role}_model.joblib") == digest, folder.name + "." + role + ".model_hash")
    audit.check(datetime.fromisoformat(protocol["declared_at_utc"]) <= datetime.fromisoformat(freeze["frozen_at_utc"])
                < datetime.fromisoformat(result["scored_at_utc"]), folder.name + ".freeze_precedes_test")
    audit.check(freeze["test_used_for_selection"] is False, folder.name + ".test_selection_flag")
    audit_selection(audit, folder, freeze, calibration.EVENT.to_numpy(dtype=bool), protocol["candidate_families"])
    frame = read_csv(folder / "test_predictions.csv.gz")
    audit.check(np.array_equal(frame.sample_index.to_numpy(), np.arange(start, start + len(source_part))), folder.name + ".source_axis")
    audit.check(np.array_equal(frame.EVENT.to_numpy(dtype=bool), source_part.EVENT.to_numpy(dtype=bool)), folder.name + ".original_labels")
    audit.check(np.array_equal(frame.timestamp_original.to_numpy(), source_part.Time.to_numpy()), folder.name + ".original_timestamps")
    for role, selection in [("baseline", freeze["baseline"]), ("v2", freeze["selected"])]:
        scores = frame[f"{role}_score"].to_numpy()
        predictions = frame[f"{role}_prediction"].to_numpy(dtype=int)
        audit.check(np.all(np.isnan(scores[:protocol["gap_rows"]])) and np.all(predictions[:protocol["gap_rows"]] == -1),
                    f"{folder.name}.{role}.gap_preserved")
        audit.check(np.array_equal(predictions, independent_policy(scores, selection["threshold"], selection["policy"])),
                    f"{folder.name}.{role}.saved_policy")
    audit.metric_pair(frame, result, folder.name)
    return frame


def main():
    # The guard runs before any source CSV, including labels, is opened.
    folders = [OUT / f"fold_{i}" for i in range(1, 7)] + [OUT / "external_2019"]
    required = [p / name for p in folders for name in ["freeze.json", "test_results.json", "test_predictions.csv.gz"]]
    required += [OUT / "walk_forward_results.json", OUT / "walk_forward_predictions.csv.gz"]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print(json.dumps({"status": "waiting_for_complete_results", "missing": missing,
                          "external_labels_read": False}))
        return 2
    audit = Audit()
    protocol = read_json(OUT / "protocol.json")
    audit.check(sha(OUT / "protocol.json") == DECLARED_PROTOCOL_SHA256, "declared_protocol_hash")
    for group in ["code_sha256", "data_sha256"]:
        for path, digest in protocol[group].items():
            audit.check(sha(ROOT / path) == digest, group + "." + path)
    for path, digest in V1_SNAPSHOT.items():
        audit.check(sha(ROOT / path) == digest, "v1_unchanged." + path)
    try:
        raw18 = read_csv(ROOT / "data/external/gecco2018/1_gecco2018_water_quality.csv", usecols=["Time", "EVENT"])
        fold_frames = []
        n, gap = len(raw18), protocol["gap_rows"]
        for index, k in enumerate(range(4, 10), start=1):
            train_end, start, end = [n * j // 10 for j in [k - 1, k, k + 1]]
            folder = OUT / f"fold_{index}"
            metadata = read_json(folder / "freeze.json")["metadata"]
            audit.compare({"train": [0, train_end], "calibration": [train_end + gap, start],
                "test": [start, end], "actual_scoring_starts": start + gap,
                "selection_max_source_index": start - 1}, metadata, folder.name + ".past_only_bounds")
            fold_frames.append(audit_partition(audit, folder, raw18.iloc[start:end].reset_index(drop=True),
                start, raw18.iloc[train_end + gap:start].reset_index(drop=True), protocol))
        combined = read_csv(OUT / "walk_forward_predictions.csv.gz")
        joined = pd.concat(fold_frames, ignore_index=True)
        score_columns = ["baseline_score", "v2_score"]
        exact_columns = [column for column in combined.columns if column not in score_columns]
        audit.check(combined[exact_columns].equals(joined[exact_columns]), "global.axes_labels_predictions_reassembled_exactly")
        audit.summary["csv_score_roundtrip"] = {}
        for column in score_columns:
            a, b = combined[column].to_numpy(), joined[column].to_numpy()
            audit.check(np.array_equal(np.isnan(a), np.isnan(b)), "global." + column + ".missing_mask")
            audit.check(np.allclose(a, b, rtol=0, atol=1e-15, equal_nan=True), "global." + column + ".csv_numeric_roundtrip")
            both = np.isfinite(a) & np.isfinite(b)
            audit.summary["csv_score_roundtrip"][column] = {
                "maximum_absolute_difference": float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.0,
                "changed_float_values": int(np.sum(a[both] != b[both])),
                "absolute_tolerance": 1e-15,
                "note": "Combined CSV scores were parsed and reserialized by the runner; all decisions, labels and row identities must remain exact. Frozen per-partition scores are used for policy replay.",
            }
        audit.check(np.array_equal(combined.sample_index.to_numpy(), np.arange(n * 4 // 10, n)), "global.full_contiguous_axis")
        audit.metric_pair(combined, read_json(OUT / "walk_forward_results.json"), "walk_forward_2018")
        original_events = spans(raw18.EVENT.to_numpy(dtype=bool))
        audit.summary["global_original_event_ids"] = [i + 1 for i, (s, e) in enumerate(original_events) if e > n * 4 // 10]
        audit.check(len(audit.summary["global_original_event_ids"]) == read_json(OUT / "walk_forward_results.json")["native"]["v2"]["true_events"],
                    "global.original_events_counted_once")
        base19 = ROOT / "data/external/gecco2019"
        def labeled19(name):
            return read_csv(base19 / name, usecols=["Time", "Event"]).rename(columns={"Event": "EVENT"})
        train = labeled19("7_gecco2019_train_water_quality.csv")
        calibration = labeled19("8_gecco2019_valid_water_qulity.csv")
        final = labeled19("6_gecco2019_test_water_quality.csv")
        audit.check(pd.to_datetime(train.Time).max() < pd.to_datetime(calibration.Time).min()
                    and pd.to_datetime(calibration.Time).max() < pd.to_datetime(final.Time).min(),
                    "external.train_calibration_final_chronology")
        external_freeze = read_json(OUT / "external_2019/freeze.json")
        audit.check(external_freeze["training_rows"] == len(train)
                    and external_freeze["calibration_rows"] == len(calibration) - gap,
                    "external.row_counts")
        audit_partition(audit, OUT / "external_2019", final, 0,
                        calibration.iloc[gap:].reset_index(drop=True), protocol)
    except Exception as exc:
        audit.findings.append({"location": "audit_execution", "detail": f"{type(exc).__name__}: {exc}"})
    result = {
        "status": "pass" if not audit.findings else "findings",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_code_sha256": sha(__file__), "declared_protocol_sha256": DECLARED_PROTOCOL_SHA256,
        "checks_performed": audit.checked, "findings": audit.findings, "summary": audit.summary,
        "independent_implementation": "No production metrics, selection, policy or model module imported",
        "external_source_access": "Only after existence of final external results and every required output was checked",
        "scope": "Saved scores/predictions, metric recomputation, selection ranking, calibration constraints, source axes, hashes and chronology; models not retrained",
        "audit_pass_does_not_imply_model_improvement": True,
    }
    (OUT / "final_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "checks_performed": audit.checked,
                      "findings": audit.findings, "output": str(OUT / "final_audit.json")}, ensure_ascii=False))
    return int(bool(audit.findings))


def self_test():
    result = independent_metrics([0, 0, 1, 1, 0], [1, -1, 1, 0, 0])
    assert (result["tp"], result["fp"], result["fn"], result["tn"]) == (1, 1, 1, 1)
    assert result["detected_events"] == 1 and result["confirmed_new_alarm_inside_events"] == 0
    assert independent_policy([1, 1, 1, np.nan, 1, 1, 1], .5, "2of3").tolist() == [-1, -1, 1, -1, -1, -1, 1]
    assert independent_metrics([], [])["event_recall"] is None
    print("Independent audit self-tests passed; no experiment data read")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        raise SystemExit(main())
