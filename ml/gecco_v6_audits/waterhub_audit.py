"""Post-completion WaterHub artifact audit, independent of the model freeze.

Import has no IO. Run ``--output EVALUATION_DIR`` ONLY after authorization and
completion of all six periods. This audits saved adapted observations; it does
not regenerate them from raw sensor CSVs. Runtime replay uses current code only
after verifying it against the frozen source hashes. Joblib is executable:
only trusted, locally generated bundles with matching freeze hashes are loaded.

Scalar accounting below deliberately does not import unknown_label_metrics.
An audit PASS verifies the checked artifacts/calculations, not model efficacy,
physical water safety, historical absence of undisclosed access, or deployment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from numbers import Real
from pathlib import Path
import statistics
import sys

import numpy as np
import pandas as pd


TOLERANCE = 1e-12


def _ratio(a, b):
    return a / b if b else None


def _integers(values, name):
    array = np.asarray(values)
    if array.ndim == 1 and not array.size:
        return []
    if array.ndim != 1 or array.dtype.kind not in "biu" or not np.isin(array, [-1, 0, 1]).all():
        raise ValueError(f"{name} must be a one-dimensional ternary integer array")
    return [int(value) for value in array]


def scalar_stats(labels, predictions, cadence=60):
    """Independent row-by-row accounting on the original, uncompressed axis."""
    y, p = _integers(labels, "labels"), _integers(predictions, "predictions")
    if len(y) != len(p):
        raise ValueError("Shape mismatch")
    if isinstance(cadence, (bool, np.bool_)) or not isinstance(cadence, Real) or not math.isfinite(cadence) or cadence <= 0:
        raise ValueError("Finite positive numeric cadence required")
    cadence = float(cadence)
    n = len(y)
    counts = {key: 0 for key in ("tp", "fp", "fn", "tn", "known", "available", "unknown_observed",
                                  "positive", "normal", "sensor_starts", "false_runs")}
    previous_false = False
    for i, (label, pred) in enumerate(zip(y, p)):
        counts["known"] += label != -1
        counts["available"] += pred != -1
        counts["unknown_observed"] += label == -1 and pred != -1
        counts["positive"] += label == 1
        counts["normal"] += label == 0
        counts["sensor_starts"] += i > 0 and pred == 1 and p[i - 1] == 0
        false = label == 0 and pred == 1
        counts["false_runs"] += false and not previous_false
        previous_false = false
        if label != -1 and pred != -1:
            key = {(1, 1): "tp", (0, 1): "fp", (1, 0): "fn", (0, 0): "tn"}[(label, pred)]
            counts[key] += 1
    segments = []
    i = 0
    while i < n:
        if y[i] != 1:
            i += 1
            continue
        start = i
        while i < n and y[i] == 1:
            i += 1
        end = i
        primary = start > 0 and y[start - 1] == 0
        right_censored = end == n or y[end] == -1
        confirmed = None
        observed = alarms = 0
        for row in range(start, end):
            observed += p[row] != -1
            alarms += p[row] == 1
            if confirmed is None and row > 0 and p[row] == 1 and p[row - 1] == 0:
                confirmed = row
        segments.append({
            "event_id": len(segments) + 1, "start": start, "end_exclusive": end,
            "primary_uncensored_onset": primary, "left_censored": not primary,
            "left_censor_reason": None if primary else ("series_start" if start == 0 else "preceding_unknown_label"),
            "right_censored": right_censored,
            "right_censor_reason": ("series_end" if end == n else "following_unknown_label") if right_censored else None,
            "positive_rows": end - start, "observed_positive_rows": observed,
            "alarm_positive_rows": alarms, "any_alarm": alarms > 0,
            "confirmed_transition_index": confirmed,
        })
    primary = [s for s in segments if s["primary_uncensored_onset"]]
    censored = [s for s in segments if s["left_censored"]]
    detected = [s for s in primary if s["confirmed_transition_index"] is not None]
    latencies = [(s["confirmed_transition_index"] - s["start"]) * cadence for s in detected]
    tp, fp, fn, tn = [counts[key] for key in ("tp", "fp", "fn", "tn")]
    normal_observed, positive_observed = fp + tn, tp + fn
    normal_seconds = normal_observed * cadence
    censored_rows = sum(s["positive_rows"] for s in censored)
    censored_observed = sum(s["observed_positive_rows"] for s in censored)
    censored_alarms = sum(s["alarm_positive_rows"] for s in censored)
    covered = sum(s["any_alarm"] for s in primary)
    return {
        "true_events": len(primary), "confirmed_event_ids": [s["event_id"] for s in detected],
        "confirmed_times": [s["confirmed_transition_index"] for s in detected],
        "confirmed_events": len(detected), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "false_positive_runs": counts["false_runs"], "normal_observed_seconds": normal_seconds,
        "false_runs_per_day": _ratio(counts["false_runs"] * 86400, normal_seconds),
        "normal_alarm_fraction": _ratio(fp, normal_observed), "fp_duration_seconds": fp * cadence,
        "available_rows": counts["available"], "rows": n, "cadence_seconds": cadence,
        "nominal_seconds": n * cadence, "known_label_rows": counts["known"],
        "unknown_label_rows": n - counts["known"], "known_label_fraction": _ratio(counts["known"], n),
        "sensor_available_fraction": _ratio(counts["available"], n), "known_observed_rows": tp + fp + fn + tn,
        "known_label_observed_fraction": _ratio(tp + fp + fn + tn, counts["known"]),
        "unknown_label_observed_rows": counts["unknown_observed"], "known_positive_rows": counts["positive"],
        "known_normal_rows": counts["normal"], "positive_observed_rows": positive_observed,
        "positive_unavailable_rows": counts["positive"] - positive_observed,
        "point_positive_observed_fraction": _ratio(positive_observed, counts["positive"]),
        "point_positive_alarm_coverage": _ratio(tp, counts["positive"]),
        "normal_observed_rows": normal_observed, "normal_unavailable_rows": counts["normal"] - normal_observed,
        "known_normal_observed_fraction": _ratio(normal_observed, counts["normal"]),
        "precision": _ratio(tp, tp + fp), "recall_observed_positive": _ratio(tp, tp + fn),
        "f1_observed_points": _ratio(2 * tp, 2 * tp + fp + fn),
        "known_positive_segments": len(segments), "known_positive_segment_details": segments,
        "known_positive_segments_with_alarm": sum(s["any_alarm"] for s in segments),
        "known_positive_segments_fully_unobserved": sum(s["observed_positive_rows"] == 0 for s in segments),
        "left_censored_positive_segments": len(censored), "left_censored_segment_ids": [s["event_id"] for s in censored],
        "right_censored_positive_segments": sum(s["right_censored"] for s in segments),
        "fully_bounded_positive_segments": sum(not s["left_censored"] and not s["right_censored"] for s in segments),
        "left_censored_positive_rows": censored_rows, "left_censored_observed_positive_rows": censored_observed,
        "left_censored_positive_observed_fraction": _ratio(censored_observed, censored_rows),
        "left_censored_positive_alarm_coverage": _ratio(censored_alarms, censored_rows),
        "primary_event_ids": [s["event_id"] for s in primary],
        "primary_event_intervals": [{k: s[k] for k in ("event_id", "start", "end_exclusive", "right_censored")} for s in primary],
        "primary_events_fully_unobserved": sum(s["observed_positive_rows"] == 0 for s in primary),
        "primary_events_with_any_alarm": covered, "primary_event_alarm_coverage": _ratio(covered, len(primary)),
        "confirmed_event_recall": _ratio(len(detected), len(primary)), "confirmed_latency_seconds": latencies,
        "median_confirmed_latency_seconds": float(statistics.median(latencies)) if latencies else None,
        "sensor_confirmed_alarm_starts": counts["sensor_starts"],
    }


def scalar_comparison(labels, baseline, candidate, cadence=60):
    y, bpred, cpred = _integers(labels, "labels"), _integers(baseline, "baseline"), _integers(candidate, "candidate")
    if not len(y) == len(bpred) == len(cpred):
        raise ValueError("Comparison shape mismatch")
    b, c = scalar_stats(y, bpred, cadence), scalar_stats(y, cpred, cadence)
    bt, ct = dict(zip(b["confirmed_event_ids"], b["confirmed_times"])), dict(zip(c["confirmed_event_ids"], c["confirmed_times"]))
    onsets = {s["event_id"]: s["start"] for s in b["primary_event_intervals"]}
    return {
        "baseline": b, "candidate": c, "lost_baseline_event_ids": sorted(set(bt) - set(ct)),
        "hidden_baseline_rows": sum(bp >= 0 and cp < 0 for bp, cp in zip(bpred, cpred)),
        "paired_extra_delays": [{"event_id": i, "extra_delay_seconds": (ct[i] - bt[i]) * cadence,
            "baseline_confirmation_index": bt[i], "candidate_confirmation_index": ct[i],
            "baseline_latency_seconds": (bt[i] - onsets[i]) * cadence,
            "candidate_latency_seconds": (ct[i] - onsets[i]) * cadence} for i in bt if i in ct],
        "retained_baseline_event_ids": sorted(set(bt) & set(ct)), "new_candidate_event_ids": sorted(set(ct) - set(bt)),
        "added_candidate_available_rows": sum(bp < 0 and cp >= 0 for bp, cp in zip(bpred, cpred)),
        "sensor_availability_equal": all((bp >= 0) == (cp >= 0) for bp, cp in zip(bpred, cpred)),
        "common_sensor_available_rows": sum(bp >= 0 and cp >= 0 for bp, cp in zip(bpred, cpred)),
        "common_known_observed_rows": sum(yy >= 0 and bp >= 0 and cp >= 0 for yy, bp, cp in zip(y, bpred, cpred)),
    }


def _noninferior(result):
    b, c = result["baseline"], result["candidate"]
    return bool(not result["lost_baseline_event_ids"] and result["sensor_availability_equal"]
                and all(d["extra_delay_seconds"] <= 0 for d in result["paired_extra_delays"])
                and c["false_positive_runs"] <= b["false_positive_runs"] and c["fp"] <= b["fp"])


def scalar_acceptance(periods, pooled, rules):
    b, c = pooled["baseline"], pooled["candidate"]
    checks = {
        "six_complete_periods": len(periods) == rules["complete_periods"],
        "each_period_has_one_day_observed_known_normal": all(
            r[model]["normal_observed_seconds"] >= rules["minimum_observed_known_normal_minutes_each_test_period"] * 60
            for r in periods for model in ("baseline", "candidate")),
        "all_periods_and_pool_noninferior": all(_noninferior(r) for r in periods + [pooled]),
        "strictly_more_pooled_events": c["confirmed_events"] > b["confirmed_events"],
        "strictly_fewer_pooled_false_runs": c["false_positive_runs"] < b["false_positive_runs"],
        "event_gain_in_at_least_two_periods": sum(bool(r["new_candidate_event_ids"]) for r in periods) >= rules["minimum_event_gain_periods"],
        "false_run_reduction_in_at_least_two_periods": sum(r["candidate"]["false_positive_runs"] < r["baseline"]["false_positive_runs"] for r in periods) >= rules["minimum_false_run_reduction_periods"],
        "at_least_five_primary_events": b["true_events"] >= rules["minimum_primary_events"],
        "at_least_two_eventful_periods": sum(r["baseline"]["true_events"] > 0 for r in periods) >= rules["minimum_eventful_periods"],
    }
    return {"checks": checks, "passes_fresh_validation_requirements": all(checks.values()), "deployment_approved": False}


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path):
    return json.loads(Path(path).read_text())


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Artifact path escapes its declared root")
    return path


class Checks:
    def __init__(self):
        self.records = []

    def add(self, name, passed, count=1, detail=None, numeric_count=0):
        record = {"check": name, "passed": bool(passed), "compared_values": int(count),
                  "numeric_comparisons": int(numeric_count)}
        if detail is not None:
            record["detail"] = detail
        self.records.append(record)
        return bool(passed)

    def tree(self, name, actual, expected):
        count, numeric_count, failures = 0, 0, []
        def walk(a, b, path):
            nonlocal count, numeric_count
            if isinstance(b, dict):
                count += 1
                if not isinstance(a, dict) or set(a) != set(b):
                    failures.append(path + ":keys")
                if isinstance(a, dict):
                    for key in b:
                        if key in a:
                            walk(a[key], b[key], path + "." + key)
            elif isinstance(b, list):
                count += 1
                if not isinstance(a, list) or len(a) != len(b):
                    failures.append(path + ":length")
                if isinstance(a, list):
                    for i, (av, bv) in enumerate(zip(a, b)):
                        walk(av, bv, path + f"[{i}]")
            else:
                count += 1
                numeric_count += isinstance(b, Real)
                if isinstance(b, float):
                    ok = isinstance(a, Real) and not isinstance(a, bool) and math.isfinite(a) and abs(a - b) <= TOLERANCE
                else:
                    ok = a == b and (not isinstance(b, bool) or isinstance(a, bool))
                if not ok:
                    failures.append(path)
        walk(actual, expected, name)
        return self.add(name, not failures, count, {"mismatch_paths": failures[:8], "mismatches": len(failures)}, numeric_count)

    def array(self, name, actual, expected, numeric=False):
        a, b = np.asarray(actual), np.asarray(expected)
        if a.shape != b.shape:
            return self.add(name, False, max(a.size, b.size), "Shape mismatch", max(a.size, b.size))
        matches = np.isclose(a.astype(float), b.astype(float), atol=TOLERANCE, rtol=0, equal_nan=True) if numeric else a == b
        return self.add(name, bool(matches.all()), a.size, {"mismatches": int((~matches).sum())}, a.size)


def _read_frame(path):
    frame = pd.read_csv(path, index_col=0, parse_dates=[0], float_precision="round_trip")
    frame.index = pd.DatetimeIndex(frame.index).as_unit("ns")
    return frame


def audit_directory(output, *, workspace_root=None, runtime_predict=None):
    """Write only audit.json. runtime_predict injection is for synthetic tests.

    Completion is checked before any saved observations, predictions or bundle
    is opened. A missing/incomplete results.json produces a failed audit only.
    """
    out = Path(output).resolve()
    root = Path(workspace_root).resolve() if workspace_root else Path(__file__).resolve().parents[2]
    checks, hashes, period_summaries = Checks(), {}, []
    report = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
              "audit_version": "waterhub_saved_artifacts_scalar_v1", "absolute_runtime_tolerance": TOLERANCE,
              "audit_code_sha256": _sha(__file__), "checks": checks.records, "hashes": hashes,
              "scope": "Completed six-period saved-artifact audit; no raw CSV adaptation or refitting",
              "limitations": [
                  "Audit PASS is calculation/integrity evidence, not validation success or deployment approval.",
                  "Adapted-source bytes are fingerprinted, not regenerated from raw CSVs in this audit.",
                  "Declared fit/calibration bounds and frozen code are checked; models are not retrained.",
                  "Artifact timestamps cannot independently prove historical absence of undisclosed access.",
                  "Latency is on the sampled minute grid; zero is not proof of instantaneous physical detection."]}
    try:
        completed = _json(out / "results.json")
        plan = _json(out / "protocol.json")
        names = [case["name"] for case in plan["cases"]]
        ready = (len(names) == 6 and len(set(names)) == 6 and bool(completed.get("completed_at_utc"))
                 and [r.get("case") for r in completed.get("periods", [])] == names
                 and not (out / "incomplete.json").exists())
        if not checks.add("all_six_periods_complete_before_data_access", ready):
            raise ValueError("All six completed periods are required before artifact-data access")
        for name in names:
            folder = _inside(out, name)
            for filename in ("results.json", "freeze.json", "bundle.joblib", "predictions.csv.gz", "calibration_scores.csv.gz"):
                if not (folder / filename).is_file():
                    raise ValueError("Required complete-period artifact missing: " + name + "/" + filename)
        hashes["protocol.json"] = _sha(out / "protocol.json")
        checks.add("final_results_protocol_hash", completed["protocol_sha256"] == hashes["protocol.json"])
        access = _json(out / "source_access_started.json")
        checks.add("access_marker_protocol_hash", access["protocol_sha256"] == hashes["protocol.json"])
        checks.add("freeze_precedes_recorded_access", datetime.fromisoformat(plan["frozen_at_utc"]) <= datetime.fromisoformat(access["first_measurement_access_started_at_utc"]))
        all_code_valid = True
        for relative, expected in plan["code_sha256"].items():
            for label, base in (("current", root), ("frozen_source", out / "source")):
                digest = _sha(_inside(base, relative))
                hashes[label + "/" + relative] = digest
                all_code_valid &= checks.add(label + " hash:" + relative, digest == expected)
        if not all_code_valid:
            raise ValueError("Code hash mismatch; runtime replay and unpickling refused")
        hashes["source_archive"] = _sha(_inside(root, plan["archive_path"]))
        checks.add("source_archive_matches_protocol", hashes["source_archive"] == plan["archive_sha256"])
        if runtime_predict is None:
            for directory in ("gecco_v2", "gecco_v5", "gecco_v6"):
                sys.path.insert(0, str(root / "ml" / directory))
            runtime = importlib.import_module("runtime_v4")
            if Path(runtime.__file__).resolve() != (root / "ml/gecco_v6/runtime_v4.py").resolve():
                raise ValueError("Runtime module is not from the verified workspace")
            runtime_predict = runtime.predict_frame
        import joblib  # Trusted, locally generated, hash-verified bundles only.
        hashes["adapted_source.csv.gz"] = _sha(out / "adapted_source.csv.gz")
        source = _read_frame(out / "adapted_source.csv.gz")
        checks.add("source_schema", list(source.columns) == ["p1", "p2", "p3", "p4", "label"])
        y = np.asarray(_integers(source["label"].to_numpy(), "source labels"), dtype=np.int8)
        cadence = plan["cadence_seconds"]
        checks.array("source_regular_minute_end_grid", np.diff(source.index.asi8),
                     np.full(max(0, len(source) - 1), int(cadence * 1e9)))
        predictions, independently_counted = [], []
        for case, saved_period in zip(plan["cases"], completed["periods"]):
            name, (left, right) = case["name"], case["test"]
            folder = _inside(out, name)
            frozen = _json(folder / "freeze.json")
            checks.tree(name + ":frozen_case_geometry", frozen["case"], case)
            checks.add(name + ":protocol_hash", frozen["protocol_sha256"] == hashes["protocol.json"])
            bundle_hash = _sha(folder / "bundle.joblib")
            hashes[name + "/bundle.joblib"] = bundle_hash
            if not checks.add(name + ":bundle_hash_before_unpickle", bundle_hash == frozen["bundle_sha256"]):
                raise ValueError("Bundle hash mismatch; unpickling refused")
            bundle = joblib.load(folder / "bundle.joblib")
            a = case["train"][1]
            bounds = case["calibration_boundaries"]
            checks.add(name + ":past_only_geometry", 0 <= case["train"][0] < a == bounds[0]
                       and all(u < v for u, v in zip(bounds[:-1], bounds[1:]))
                       and bounds[-1] == left < right <= len(source))
            checks.add(name + ":fit_and_calibration_indices_before_test",
                       bundle["max_fit_index"] == a - 1 < left
                       and bundle["max_calibration_index"] == bounds[-1] - 1 < left)
            checks.add(name + ":bundle_cadence", bundle["sample_seconds"] == cadence)
            for key in ("selected", "guard_selected", "shape_support_threshold"):
                checks.tree(name + ":frozen_selection:" + key, bundle[key], frozen[key])
            hashes[name + "/calibration_scores.csv.gz"] = _sha(folder / "calibration_scores.csv.gz")
            cal = pd.read_csv(folder / "calibration_scores.csv.gz", usecols=["sample_index", "label"])
            checks.array(name + ":calibration_original_indices", cal.sample_index, np.arange(bounds[0], bounds[-1]))
            checks.array(name + ":calibration_labels_match_source", cal.label, y[bounds[0]:bounds[-1]])
            hashes[name + "/predictions.csv.gz"] = _sha(folder / "predictions.csv.gz")
            saved = _read_frame(folder / "predictions.csv.gz")
            checks.array(name + ":test_original_indices", saved.sample_index, np.arange(left, right))
            checks.array(name + ":test_timestamps", saved.index.asi8, source.index[left:right].asi8)
            checks.array(name + ":test_labels_match_source", saved.label, y[left:right])
            replay = runtime_predict(bundle, source.iloc[left:right].loc[:, ["p1", "p2", "p3", "p4"]],
                                     gap_samples=plan["gap_samples_per_independent_block"])
            checks.add(name + ":prediction_schema", list(saved.columns) == ["sample_index", "label", *replay.columns])
            checks.array(name + ":runtime_timestamps", replay.index.asi8, saved.index.asi8)
            for column in replay.columns:
                exact = column.endswith("prediction") or column in ("available", "ignored_gap")
                checks.array(name + ":runtime:" + column, saved[column], replay[column], numeric=not exact)
            checks.array(name + ":unmasked_sensor_availability", saved.available, saved.prediction.to_numpy() >= 0)
            counted = scalar_comparison(saved.label.to_numpy(), saved.baseline_prediction.to_numpy(),
                                        saved.prediction.to_numpy(), cadence)
            counted["case"], counted["noninferior"] = name, _noninferior(counted)
            checks.tree(name + ":scalar_metrics_vs_period_file", _json(folder / "results.json"), counted)
            checks.tree(name + ":scalar_metrics_vs_final_period", saved_period, counted)
            independently_counted.append(counted)
            predictions.append(saved)
            period_summaries.append({"case": name, "rows": len(saved), "runtime_replayed": True})
        whole = pd.concat(predictions)
        checks.array("pooled_original_axis_contiguous", np.diff(whole.sample_index), np.ones(max(0, len(whole) - 1), dtype=int))
        pooled = scalar_comparison(whole.label.to_numpy(), whole.baseline_prediction.to_numpy(), whole.prediction.to_numpy(), cadence)
        checks.tree("pooled_scalar_metrics", completed["pooled"], pooled)
        accepted = scalar_acceptance(independently_counted, pooled, plan["acceptance"])
        checks.tree("independent_acceptance_accounting", completed["acceptance"], accepted)
        report["fresh_validation_requirements_passed"] = accepted["passes_fresh_validation_requirements"]
    except Exception as error:
        checks.add("audit_completed_without_exception", False, detail={"type": type(error).__name__, "message": str(error)})
    report["periods_replayed"] = period_summaries
    report["audit_passed"] = bool(checks.records) and all(record["passed"] for record in checks.records) and len(period_summaries) == 6
    report["passed"] = report["audit_passed"]
    report["total_numeric_checks"] = sum(record["numeric_comparisons"] for record in checks.records)
    report["replayed_rows"] = sum(period["rows"] for period in period_summaries)
    report["check_groups"] = len(checks.records)
    report["compared_values"] = sum(record["compared_values"] for record in checks.records)
    report["failed_check_groups"] = sum(not record["passed"] for record in checks.records)
    (out / "audit.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_directory(args.output)
    print(json.dumps({key: result[key] for key in ("audit_passed", "check_groups", "compared_values", "failed_check_groups")}))
    return 0 if result["audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
