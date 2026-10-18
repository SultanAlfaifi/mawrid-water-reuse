"""Synthetic artifact trees and local synthetic joblib bundles only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gecco_v6"))
from unknown_label_metrics import stats, comparison
from waterhub_audit import audit_directory, scalar_stats, scalar_comparison, scalar_acceptance


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_runtime(bundle, frame, *, gap_samples):
    scores = frame.p1.to_numpy() * .01
    prediction = (frame.p1.to_numpy().astype(int) % 8 >= 2).astype(np.int8)
    scores[:gap_samples] = np.nan
    prediction[:gap_samples] = -1
    return pd.DataFrame({"baseline_score": scores, "baseline_prediction": prediction,
                         "guarded_prediction": prediction.copy(), "prediction": prediction.copy(),
                         "available": prediction >= 0,
                         "ignored_gap": np.arange(len(frame)) < gap_samples}, index=frame.index)


def make_fixture(root):
    out = root / "output"
    out.mkdir()
    code = root / "ml/gecco_v6/synthetic_source.py"
    code.parent.mkdir(parents=True)
    code.write_text("# Synthetic code fingerprint. No model or source data.\n")
    frozen = out / "source/ml/gecco_v6/synthetic_source.py"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(code.read_bytes())
    archive = root / "data/synthetic.zip"
    archive.parent.mkdir()
    archive.write_bytes(b"Synthetic archive fingerprint; never unpickled.")
    cases = []
    for i in range(6):
        left = 20 + i * 8
        cases.append({"name": f"period_{i + 1}", "train": [0, left - 8],
                      "calibration_boundaries": list(range(left - 8, left + 1, 2)),
                      "test": [left, left + 8]})
    rules = {"complete_periods": 6, "minimum_observed_known_normal_minutes_each_test_period": 1,
             "minimum_event_gain_periods": 2, "minimum_false_run_reduction_periods": 2,
             "minimum_primary_events": 5, "minimum_eventful_periods": 2}
    plan = {"cases": cases, "frozen_at_utc": "2020-01-01T00:00:00+00:00",
            "code_sha256": {"ml/gecco_v6/synthetic_source.py": sha(code)},
            "archive_path": "data/synthetic.zip", "archive_sha256": sha(archive),
            "cadence_seconds": 60, "gap_samples_per_independent_block": 2, "acceptance": rules}
    write(out / "protocol.json", plan)
    protocol_hash = sha(out / "protocol.json")
    write(out / "source_access_started.json", {
        "protocol_sha256": protocol_hash, "first_measurement_access_started_at_utc": "2020-01-01T00:01:00+00:00"})
    index = pd.date_range("2018-06-01 00:01", periods=68, freq="min", name="minute_end").as_unit("ns")
    source = pd.DataFrame({f"p{c}": np.arange(68, dtype=float) + c - 1 for c in range(1, 5)}, index=index)
    labels = np.zeros(68, dtype=np.int8)
    labels[6:8] = -1
    for case in cases:
        start = case["test"][0]
        labels[start + 2:start + 4] = 1
        labels[start + 6] = -1
    source.assign(label=labels).to_csv(out / "adapted_source.csv.gz")
    period_results, all_predictions = [], []
    for case in cases:
        folder = out / case["name"]
        folder.mkdir()
        left, right = case["test"]
        bundle = {"max_fit_index": case["train"][1] - 1,
                  "max_calibration_index": case["calibration_boundaries"][-1] - 1,
                  "sample_seconds": 60, "selected": {"seed": "baseline", "rescue": None},
                  "guard_selected": {"decision": "baseline"}, "shape_support_threshold": None}
        joblib.dump(bundle, folder / "bundle.joblib")
        write(folder / "freeze.json", {"case": case, "protocol_sha256": protocol_hash,
            "bundle_sha256": sha(folder / "bundle.joblib"),
            **{key: bundle[key] for key in ("selected", "guard_selected", "shape_support_threshold")}})
        a, b = case["calibration_boundaries"][0], case["calibration_boundaries"][-1]
        pd.DataFrame({"sample_index": np.arange(a, b), "label": labels[a:b]}).to_csv(
            folder / "calibration_scores.csv.gz", index=False)
        pred = synthetic_runtime(bundle, source.iloc[left:right], gap_samples=2)
        pred.insert(0, "sample_index", np.arange(left, right))
        pred.insert(1, "label", labels[left:right])
        pred.to_csv(folder / "predictions.csv.gz")
        result = comparison(labels[left:right], pred.baseline_prediction.to_numpy(), pred.prediction.to_numpy())
        result.update(case=case["name"], noninferior=True)
        write(folder / "results.json", result)
        period_results.append(result)
        all_predictions.append(pred)
    whole = pd.concat(all_predictions)
    pooled = comparison(whole.label.to_numpy(), whole.baseline_prediction.to_numpy(), whole.prediction.to_numpy())
    acceptance = scalar_acceptance(period_results, pooled, rules)
    write(out / "results.json", {"completed_at_utc": "2020-01-01T01:00:00+00:00", "protocol_sha256": protocol_hash,
                                  "periods": period_results, "pooled": pooled, "acceptance": acceptance})
    return out


class WaterHubAuditTests(unittest.TestCase):
    def test_independent_scalar_full_metric_tree_matches_synthetic_oracle_contract(self):
        rng = np.random.default_rng(420)
        for n in (0, 1, 3, 10, 80):
            for _ in range(20):
                y = rng.integers(-1, 2, n, dtype=np.int8)
                b = rng.integers(-1, 2, n, dtype=np.int8)
                c = rng.integers(-1, 2, n, dtype=np.int8)
                self.assertEqual(scalar_stats(y, b, 10), stats(y, b, 10))
                self.assertEqual(scalar_comparison(y, b, c, 10), comparison(y, b, c, 10))

    def test_complete_synthetic_six_period_audit_passes_but_validation_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = make_fixture(root)
            report = audit_directory(out, workspace_root=root, runtime_predict=synthetic_runtime)
            failures = [r for r in report["checks"] if not r["passed"]]
            self.assertTrue(report["passed"], failures)
            self.assertTrue(report["audit_passed"])
            self.assertFalse(report["fresh_validation_requirements_passed"])
            self.assertEqual(report["replayed_rows"], 48)
            self.assertGreater(report["total_numeric_checks"], 1000)
            self.assertEqual(len(report["periods_replayed"]), 6)
            self.assertTrue((out / "audit.json").is_file())

    def test_incomplete_run_refuses_saved_observation_and_bundle_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = make_fixture(root)
            result = json.loads((out / "results.json").read_text())
            result["periods"] = result["periods"][:5]
            write(out / "results.json", result)
            with patch("waterhub_audit._read_frame", side_effect=AssertionError("data opened")), \
                 patch("joblib.load", side_effect=AssertionError("bundle opened")):
                report = audit_directory(out, workspace_root=root, runtime_predict=synthetic_runtime)
            self.assertFalse(report["passed"])
            self.assertEqual(report["replayed_rows"], 0)
            self.assertFalse(any(r["detail"].get("type") == "AssertionError" for r in report["checks"]
                                 if isinstance(r.get("detail"), dict)))

    def test_code_hash_change_stops_before_unpickle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = make_fixture(root)
            (root / "ml/gecco_v6/synthetic_source.py").write_text("# changed")
            with patch("joblib.load", side_effect=AssertionError("bundle opened")):
                report = audit_directory(out, workspace_root=root, runtime_predict=synthetic_runtime)
            self.assertFalse(report["passed"])
            self.assertEqual(report["replayed_rows"], 0)
            self.assertTrue(any(r["check"].startswith("current hash:") and not r["passed"] for r in report["checks"]))

    def test_bundle_hash_change_stops_before_unpickle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = make_fixture(root)
            with (out / "period_1/bundle.joblib").open("ab") as f:
                f.write(b"changed")
            with patch("joblib.load", side_effect=AssertionError("bundle opened")):
                report = audit_directory(out, workspace_root=root, runtime_predict=synthetic_runtime)
            self.assertFalse(report["passed"])
            self.assertEqual(report["replayed_rows"], 0)
            self.assertTrue(any("bundle_hash_before_unpickle" in r["check"] and not r["passed"] for r in report["checks"]))

    def test_replay_detects_changed_score_even_when_metrics_still_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = make_fixture(root)
            path = out / "period_2/predictions.csv.gz"
            saved = pd.read_csv(path, index_col=0)
            saved.iloc[3, saved.columns.get_loc("baseline_score")] += 1e-5
            saved.to_csv(path)
            report = audit_directory(out, workspace_root=root, runtime_predict=synthetic_runtime)
            self.assertFalse(report["passed"])
            self.assertTrue(any(r["check"] == "period_2:runtime:baseline_score" and not r["passed"] for r in report["checks"]))

    def test_scalar_audit_detects_changed_event_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = make_fixture(root)
            path = out / "period_3/results.json"
            result = json.loads(path.read_text())
            result["baseline"]["true_events"] += 1
            write(path, result)
            report = audit_directory(out, workspace_root=root, runtime_predict=synthetic_runtime)
            self.assertFalse(report["passed"])
            self.assertTrue(any(r["check"] == "period_3:scalar_metrics_vs_period_file" and not r["passed"] for r in report["checks"]))

    def test_future_fit_bound_is_detected_even_with_updated_bundle_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = make_fixture(root)
            path = out / "period_1/bundle.joblib"
            bundle = joblib.load(path)
            bundle["max_fit_index"] = 25
            joblib.dump(bundle, path)
            frozen = json.loads((path.parent / "freeze.json").read_text())
            frozen["bundle_sha256"] = sha(path)
            write(path.parent / "freeze.json", frozen)
            report = audit_directory(out, workspace_root=root, runtime_predict=synthetic_runtime)
            self.assertFalse(report["passed"])
            self.assertTrue(any(r["check"] == "period_1:fit_and_calibration_indices_before_test" and not r["passed"] for r in report["checks"]))


if __name__ == "__main__":
    unittest.main()
