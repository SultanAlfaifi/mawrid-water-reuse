"""Post-test diagnosis of completed run04, using disclosed saved scores only.

Reads no model training input, unopened source, or alternative operating point.
Writes one new diagnostic artifact; never changes models, scores, or thresholds.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ml.gecco_v7_audits.diagnose import diagnose_scores, quantiles


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _episodes(reference):
    alarm = np.asarray(reference) == 1
    change = np.diff(np.r_[False, alarm, False].astype(np.int8))
    return list(zip(np.flatnonzero(change == 1), np.flatnonzero(change == -1)))


def _phase(rows, choice):
    diagnostic = diagnose_scores(rows, choice)
    # Keep event details only for actual lost IDs, below; ranking and all score
    # distributions remain descriptive and do not select a test threshold.
    diagnostic.pop("primary_events")
    y, r, p = [rows[key].to_numpy(np.int8) for key in ("label", "reference", "candidate")]
    raw = rows.long_context.to_numpy(float)
    rescue = rows.rescue_long_context.to_numpy(float)
    low, high = choice["low_threshold"], choice["high_threshold"]
    true_episodes = [(a, b) for a, b in _episodes(r) if (y[a:b] == 1).any()]
    removed = [(a, b) for a, b in true_episodes if not (p[a:b] == 1).any()]
    diagnostic["reference_episodes_intersecting_known_positive"] = {
        "count": len(true_episodes),
        "length_samples": quantiles([b - a for a, b in true_episodes]),
        "at_most_confirmation_deadline_samples": int(sum(b - a <= choice["confirmation_samples"] for a, b in true_episodes)),
        "entirely_removed_episode_count": len(removed),
        "entirely_removed_episode_lengths": quantiles([b - a for a, b in removed]),
        "interpretation": "reference episodes intersecting positive labels, not unique primary events; an episode can cross phase boundaries"}
    known_positive_reference = (y == 1) & (r == 1) & np.isfinite(raw)
    diagnostic["finite_positive_reference_rows_below_confirmation_threshold"] = (
        int((known_positive_reference & (raw < low)).sum()) if low is not None else None)
    diagnostic["finite_positive_reference_rows"] = int(known_positive_reference.sum())
    diagnostic["rescue_normal_scores"] = quantiles(rescue[(y == 0) & (r >= 0)])
    diagnostic["rescue_positive_scores"] = quantiles(rescue[(y == 1) & (r >= 0)])
    diagnostic["rescue_known_normal_rows_above_fixed_threshold"] = (
        int(((y == 0) & (r >= 0) & np.isfinite(rescue) & (rescue >= high)).sum()) if high is not None else None)
    diagnostic["sample_range"] = [int(rows.sample_index.iloc[0]), int(rows.sample_index.iloc[-1]) + 1]
    return diagnostic


def _lost_event(rows, event, choice, comparison):
    y, reference, candidate = [rows[key].to_numpy(np.int8) for key in ("label", "reference", "candidate")]
    score = rows.long_context.to_numpy(float)
    a, b = event["start"], event["end_exclusive"]
    origin = int(rows.sample_index.iloc[0])
    pulses = []
    for start, end in _episodes(reference):
        if end <= a or start >= b:
            continue
        values = score[start:end]
        low = choice["low_threshold"]
        finite_below = bool(low is not None and np.isfinite(values).all() and (values < low).all())
        fully_removed = not (candidate[start:end] == 1).any()
        pulses.append({
            "start_test_index": int(start), "end_test_index_exclusive": int(end),
            "source_sample_start": origin + int(start), "source_sample_end_exclusive": origin + int(end),
            "length_samples": int(end - start), "duration_seconds": int((end - start) * choice["cadence_seconds"]),
            "left_censored_by_test_boundary": bool(start == 0),
            "right_censored_by_test_boundary": bool(end == len(rows)),
            "positive_rows_inside_event": int((y[max(start, a):min(end, b)] == 1).sum()),
            "confidence_first_values": [float(v) if np.isfinite(v) else None for v in values[:8]],
            "confidence_distribution": quantiles(values),
            "all_confidence_finite_below_fixed_low_threshold": finite_below,
            "length_at_most_confirmation_deadline_samples": bool(end - start <= choice["confirmation_samples"]),
            "fully_removed": bool(fully_removed),
            "candidate_alarm_rows_inside_episode": int((candidate[start:end] == 1).sum()),
            "short_low_confidence_episode_discard_explains_loss": bool(fully_removed and finite_below and end - start <= choice["confirmation_samples"]),
        })
    before_times = dict(zip(comparison["baseline"]["confirmed_event_ids"], comparison["baseline"]["confirmed_times"]))
    return {"event_id": event["event_id"], "start_test_index": int(a), "end_test_index_exclusive": int(b),
            "source_sample_start": origin + int(a), "source_sample_end_exclusive": origin + int(b),
            "positive_event_rows": int(b - a), "reference_confirmed_test_index": before_times.get(event["event_id"]),
            "reference_alarm_rows_inside_event": int((reference[a:b] == 1).sum()),
            "candidate_alarm_rows_inside_event": int((candidate[a:b] == 1).sum()),
            "raw_event_confidence_distribution": quantiles(score[a:b]), "reference_episodes": pulses,
            "rescue_enabled": choice["high_threshold"] is not None,
            "explanation": "A finite low-confidence reference episode no longer than the confirmation deadline can end before forced release. The two-minute continuous-episode limit cannot preserve such an event by itself; past certification cannot guarantee future event pulse shape."}


def diagnose_run(folder):
    folder = Path(folder).resolve()
    result_path = folder / "results.json"
    result = json.loads(result_path.read_text())
    if (result.get("complete_cases") != 19 or result.get("expected_cases") != 19
            or not result.get("all_prespecified_cases_complete") or len(result["periods"]) != 19):
        raise ValueError("A completed predeclared 19-case run is required before reading scores")
    if len({p["case"] for p in result["periods"]}) != 19:
        raise ValueError("Expected 19 distinct case identities")
    digest = _sha(result_path)
    statuses = Counter(); earlier_reasons = Counter(); failed_reasons = Counter(); failed_checks = Counter()
    fallbacks = []; active = []; input_hashes = {"results.json": digest}
    for period in result["periods"]:
        choice = period["selected"]
        statuses[choice["status"]] += 1
        if choice["decision"] == "reference":
            entry = {"case": period["case"], "status": choice["status"],
                     "earlier_selection_status": choice["earlier_selected"]["status"],
                     "certification_rejection_reasons": choice["certification_rejection_reasons"],
                     "certification_checks": choice["certification"]["checks"],
                     "earlier_evidence": {key: choice["earlier_selected"]["evidence"][key]
                         for key in ("enough_exposure", "enough_labeled_events", "eventful_blocks", "qualified_blocks")},
                     "later_evidence": choice["certification"]["evidence"]}
            fallbacks.append(entry)
            if choice["status"] == "earlier_reference_retained":
                earlier_reasons[entry["earlier_selection_status"]] += 1
            else:
                failed_reasons.update(set(choice["certification_rejection_reasons"]))
                failed_checks.update(key for key, passed in choice["certification"]["checks"].items() if not passed)
            continue
        path = folder / period["case"]
        frozen = json.loads((path / "freeze.json").read_text())
        for name in ("freeze.json", "calibration_scores.csv.gz", "predictions.csv.gz"):
            input_hashes[f"{period['case']}/{name}"] = _sha(path / name)
        calibration = pd.read_csv(path / "calibration_scores.csv.gz", float_precision="round_trip")
        test = pd.read_csv(path / "predictions.csv.gz", float_precision="round_trip")
        starts = frozen["calibration_starts"]
        np.testing.assert_array_equal(calibration.sample_index, np.arange(starts[0], frozen["test"][0]))
        np.testing.assert_array_equal(test.sample_index, np.arange(*frozen["test"]))
        split = starts[2]
        earlier = calibration[calibration.sample_index < split]
        later = calibration[calibration.sample_index >= split]
        comparison = period["comparisons"]["v6_vs_v7"]
        lost_ids = set(comparison["lost_baseline_event_ids"])
        events = comparison["baseline"]["primary_event_intervals"]
        active.append({"case": period["case"], "source": period["source"],
                       "fixed_selected": {key: choice[key] for key in ("decision", "low_threshold", "high_threshold", "policy", "confirmation_samples", "cadence_seconds", "confirmation_delay_seconds")},
                       "certification_passed": choice["certification_passed"],
                       "earlier_selection": _phase(earlier, choice),
                       "later_certification": _phase(later, choice), "test": _phase(test, choice),
                       "lost_events": [_lost_event(test, event, choice, comparison) for event in events if event["event_id"] in lost_ids],
                       "comparison": comparison})
    if _sha(result_path) != digest:
        raise AssertionError("Completed results changed during diagnosis")
    for name, sha in input_hashes.items():
        if _sha(folder / name) != sha:
            raise AssertionError("Saved diagnosis input changed: " + name)
    return {"created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "post_test_diagnosis_on_disclosed_development_results",
            "run": str(folder.relative_to(ROOT)), "development_only": True,
            "new_source_accessed": False, "model_refitted": False, "thresholds_changed": False,
            "input_sha256": input_hashes,
            "notes": ["Four active policies only are analyzed numerically; all 15 fallback reasons are retained.",
                      "First-two and last-two diagnostics use the fixed final policy and original saved block-reset predictions; no operating point is selected by this script.",
                      "Certification was conditional on V6 calibrated using all four blocks, not an independent holdout for the complete pipeline.",
                      "Known labels only are used for score ranking; unknown labels never count as normal and score availability is shown separately.",
                      "Episode statistics describe reference episodes, not independent events. Lost event IDs retain the original known-onset metric.",
                      "Passing past calibration and certification constraints does not guarantee future event-ID retention; short true reference pulses may differ in duration or confidence."],
            "status_counts": dict(statuses), "earlier_reference_reason_counts": dict(earlier_reasons),
            "failed_certification_check_case_counts": dict(failed_checks),
            "failed_certification_reason_case_counts": dict(failed_reasons),
            "fallbacks": fallbacks, "active_periods": active, "summary": result["summary"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    diagnostic = diagnose_run(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(diagnostic, indent=2, allow_nan=False) + "\n"
    with args.output.open("x") as stream:
        stream.write(encoded)
    print(json.dumps({"output": str(args.output), "status_counts": diagnostic["status_counts"],
                      "active_periods": len(diagnostic["active_periods"]),
                      "lost_events": {p["case"]: [e["event_id"] for e in p["lost_events"]] for p in diagnostic["active_periods"]}}))


if __name__ == "__main__":
    main()
