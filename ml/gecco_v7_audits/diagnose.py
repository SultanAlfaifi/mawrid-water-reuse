"""Read-only diagnosis of completed V7 development; never fit or select anew.

Uses only disclosed GECCO/WaterHub saved predictions and calibration trials.
The complete expected 19-case result must exist before any score file is read.
Ranking statistics are diagnostic, never a replacement held-out acceptance gate.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml/gecco_v6"))
from unknown_label_metrics import stats


def quantiles(values):
    finite = np.asarray(values, float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return {"rows": 0, "q01": None, "q10": None, "q50": None, "q90": None, "q99": None, "max": None}
    qs = np.quantile(finite, [.01, .1, .5, .9, .99])
    return {"rows": len(finite), **dict(zip(("q01", "q10", "q50", "q90", "q99"), map(float, qs))), "max": float(finite.max())}


def diagnose_scores(rows, choice):
    y = rows.label.to_numpy(np.int8)
    r = rows.reference.to_numpy(np.int8)
    p = rows.candidate.to_numpy(np.int8)
    s = rows.long_context.to_numpy(float)
    known_available = (y >= 0) & (r >= 0)
    finite = known_available & np.isfinite(s)
    target, score = y[finite], s[finite]
    both_classes = len(np.unique(target)) == 2
    prevalence = float(np.mean(target)) if len(target) else None
    ap = float(average_precision_score(target, score)) if both_classes else None
    auc = float(roc_auc_score(target, score)) if both_classes else None
    score_at_start = (r == 1) & np.r_[True, r[:-1] != 1]
    reference_stats = stats(y, r)
    candidate_stats = stats(y, p)
    reference_ids = set(reference_stats["confirmed_event_ids"])
    candidate_ids = set(candidate_stats["confirmed_event_ids"])
    high = choice.get("high_threshold")
    events = []
    for event in reference_stats["primary_event_intervals"]:
        a, b = event["start"], event["end_exclusive"]
        observed = r[a:b] >= 0
        values = s[a:b]
        events.append({"event_id": event["event_id"], "start": a, "end_exclusive": b,
                       "positive_minutes": b - a, "reference_confirmed": event["event_id"] in reference_ids,
                       "candidate_confirmed": event["event_id"] in candidate_ids,
                       "reference_positive_minutes": int((r[a:b] == 1).sum()),
                       "candidate_positive_minutes": int((p[a:b] == 1).sum()),
                       "reference_available_minutes": int(observed.sum()),
                       "long_score_available_minutes": int((observed & np.isfinite(values)).sum()),
                       "long_score_quantiles": quantiles(values[observed]),
                       "minutes_above_selected_rescue_threshold": int((observed & np.isfinite(values) & (values >= high)).sum()) if high is not None else None})
    return {"known_reference_available_rows": int(known_available.sum()),
            "known_reference_rows_with_long_score": int(finite.sum()),
            "long_score_fraction_on_reference_observed_known_rows": float(finite.sum() / known_available.sum()) if known_available.any() else None,
            "positive_prevalence_on_scored_known_rows": prevalence, "average_precision": ap,
            "average_precision_over_prevalence": ap / prevalence if ap is not None and prevalence else None,
            "roc_auc": auc, "normal_scores": quantiles(s[finite & (y == 0)]),
            "positive_scores": quantiles(s[finite & (y == 1)]),
            "reference_false_alarm_scores": quantiles(s[(y == 0) & (r == 1)]),
            "reference_true_alarm_scores": quantiles(s[(y == 1) & (r == 1)]),
            "reference_alarm_starts": int(score_at_start.sum()),
            "reference_alarm_starts_with_unknown_long_score": int((score_at_start & ~np.isfinite(s)).sum()),
            "reference_known_normal_alarm_start_scores": quantiles(s[score_at_start & (y == 0)]),
            "reference_known_positive_alarm_start_scores": quantiles(s[score_at_start & (y == 1)]),
            "added_positive_alarm_minutes": int(((y == 1) & (r != 1) & (p == 1)).sum()),
            "removed_positive_alarm_minutes": int(((y == 1) & (r == 1) & (p != 1)).sum()),
            "added_false_alarm_minutes": int(((y == 0) & (r != 1) & (p == 1)).sum()),
            "removed_false_alarm_minutes": int(((y == 0) & (r == 1) & (p != 1)).sum()),
            "primary_event_duration_minutes": quantiles([e["positive_minutes"] for e in events]),
            "primary_events": events}


def list_value(value):
    if isinstance(value, list):
        return value
    parsed = ast.literal_eval(value)
    if not isinstance(parsed, list):
        raise ValueError("Expected retained rejection-reason list")
    return parsed


def diagnose_run(folder):
    folder = Path(folder)
    completed = json.loads((folder / "results.json").read_text())
    if completed.get("complete_cases") != 19 or completed.get("expected_cases") != 19 or not completed.get("all_prespecified_cases_complete"):
        raise ValueError("Diagnosis requires the completed predeclared 19-case development run")
    periods = []
    for period in completed["periods"]:
        path = folder / period["case"]
        chosen = period["selected"]
        calibration = pd.read_csv(path / "calibration_scores.csv.gz", float_precision="round_trip")
        test = pd.read_csv(path / "predictions.csv.gz", float_precision="round_trip")
        trials = pd.read_csv(path / "calibration_trials.csv.gz")
        reasons = Counter(reason for value in trials.rejection_reasons for reason in list_value(value))
        feasible = trials[trials.feasible]
        inspection = json.loads((path / "model_inspection.json").read_text())
        item = {"case": period["case"], "source": period["source"], "selected": {
                    key: chosen.get(key) for key in ("decision", "low_threshold", "high_threshold", "policy", "status")},
                "fit_status": period["fit_status"], "training": {
                    key: inspection.get(key) for key in ("training_rows", "original_label_counts", "eligible_normal_rows", "eligible_positive_rows", "eligible_positive_segments")},
                "evidence": {key: chosen["evidence"].get(key) for key in
                             ("enough_exposure", "enough_labeled_events", "qualified_blocks", "eventful_blocks")},
                "trials": {"total": len(trials), "feasible": len(feasible),
                           "feasible_rescue": int(feasible.high_threshold.notna().sum()),
                           "feasible_suppression": int(feasible.low_threshold.notna().sum()),
                           "rejection_reason_counts": dict(reasons.most_common())},
                "calibration": diagnose_scores(calibration, chosen), "test": diagnose_scores(test, chosen),
                "comparison": period["comparisons"]["v6_vs_v7"]}
        cal_auc, test_auc = item["calibration"]["roc_auc"], item["test"]["roc_auc"]
        item["calibration_minus_test_auc"] = cal_auc - test_auc if cal_auc is not None and test_auc is not None else None
        periods.append(item)
    return {"development_only": True, "new_source_accessed": False,
            "diagnosis_does_not_change_model_or_thresholds": True,
            "notes": ["Ranking metrics use only known-label reference-observed rows with finite long scores; availability is reported separately.",
                      "AUC/AP describe point ranking, not confirmed event recall; no threshold is fitted to test scores.",
                      "Calibration series concatenates original adjacent blocks for descriptive metrics; selection itself retains every block's reset and constraints.",
                      "Unknown labels remain unknown, never normal. Source-level acceptance is copied from the original completed run."],
            "summary": completed["summary"], "periods": periods}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    diagnostic = diagnose_run(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(diagnostic, stream, indent=2, allow_nan=False)
        stream.write("\n")
    for period in diagnostic["periods"]:
        before, after = period["comparison"]["baseline"], period["comparison"]["candidate"]
        print(json.dumps({"case": period["case"], "decision": period["selected"],
                          "cal_auc": period["calibration"]["roc_auc"], "test_auc": period["test"]["roc_auc"],
                          "events": [before["confirmed_events"], after["confirmed_events"]],
                          "fp_runs": [before["false_positive_runs"], after["false_positive_runs"]],
                          "fp_minutes": [before["fp"], after["fp"]],
                          "lost_events": period["comparison"]["lost_baseline_event_ids"],
                          "rejections": period["trials"]["rejection_reason_counts"]}))


if __name__ == "__main__":
    main()
