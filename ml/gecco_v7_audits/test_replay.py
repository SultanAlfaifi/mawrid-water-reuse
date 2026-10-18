"""Synthetic-only independent V7 audit tests; no publisher data is opened."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd

from ml.gecco_v6.unknown_label_metrics import comparison, stats
from ml.gecco_v7_audits import replay


def dump(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False))


class SyntheticModel:
    def __init__(self, frame):
        self.channels = ["a"]
        self.training_rows_ = len(frame)
        self.training_sample_weight_ = np.zeros(len(frame))
        self.training_normalized_weight_ = np.zeros(len(frame))
        self.fit_status_ = "synthetic"
        normal = (frame.label.to_numpy() == 0) & np.isfinite(frame.a.to_numpy())
        self.normal_reference_counts_ = np.array([normal.sum()])
        self.normal_delta_counts_ = np.array([(normal[1:] & normal[:-1]).sum()])

    def inspection(self):
        return {"training_rows": self.training_rows_, "synthetic": True}


def synthetic_runtime(bundle, frame):
    score = frame.a.to_numpy(float).copy()
    score[:min(120, len(score))] = np.nan
    prediction = np.where(np.isfinite(score), (score >= .5).astype(np.int8), -1).astype(np.int8)
    return pd.DataFrame({"baseline_score": score, "baseline_prediction": prediction,
                         "reference_prediction": prediction, "long_context": score,
                         "prediction": prediction, "available": prediction >= 0,
                         "ignored_gap": np.arange(len(frame)) < 120}, index=frame.index)


def guarded_synthetic_runtime(bundle, frame):
    result = synthetic_runtime(bundle, frame)
    result["level"] = np.abs(frame.a.to_numpy()) * 2
    result["jump"] = .2
    result["sustained"] = .7
    guarded = result.long_context.to_numpy().copy()
    guarded[result.level.to_numpy() > 1] = np.nan
    result["guarded_long_context"] = guarded
    return result


def make_case(root):
    out = root / "output"
    folder = out / "synthetic_case"
    prior = root / "prior"
    folder.mkdir(parents=True)
    prior.mkdir()
    n = 1400
    source = pd.DataFrame({"a": np.sin(np.arange(n) / 17), "label": (np.arange(n) % 101 < 12).astype(np.int8)})
    source.loc[np.arange(n) % 47 == 0, "label"] = -1
    spec = {"name": "synthetic_case", "source": "2017", "train": [0, 200],
            "calibration_starts": [200, 400, 600, 800], "test": [1000, 1400],
            "continuous_cal": False, "channels": ["a"]}
    model = SyntheticModel(source.iloc[:200])
    parts = []
    for left, right in zip([200, 400, 600, 800], [400, 600, 800, 1000]):
        frame = source.iloc[left:right]
        raw = synthetic_runtime({}, frame)
        parts.append(pd.DataFrame({"sample_index": np.arange(left, right), "label": frame.label.to_numpy(),
                                   "baseline": raw.prediction.to_numpy(), "reference": raw.prediction.to_numpy(),
                                   "candidate": raw.prediction.to_numpy(), "long_context": raw.long_context.to_numpy()}))
    calibration = pd.concat(parts, ignore_index=True)
    selected = {"decision": "reference", "calibration_metrics": stats(calibration.label.to_numpy(), calibration.candidate.to_numpy(), 60),
                "calibration_block_metrics": [stats(p.label.to_numpy(), p.candidate.to_numpy(), 60) for p in parts]}
    bundle = {"long_model": model, "reference_bundle": {"max_fit_index": 199, "max_calibration_index": 999},
              "selected": selected, "sample_seconds": 60, "gap_samples": 120,
              "max_fit_index": 199, "max_calibration_index": 999}
    joblib.dump(bundle, folder / "bundle.joblib")
    raw = synthetic_runtime(bundle, source.iloc[1000:])
    labels = source.label.iloc[1000:].to_numpy()
    arrays = {"baseline": raw.baseline_prediction.to_numpy(), "reference": raw.reference_prediction.to_numpy(),
              "candidate": raw.prediction.to_numpy()}
    prediction = pd.DataFrame({"sample_index": np.arange(1000, 1400), "label": labels,
                               **arrays, "long_context": raw.long_context.to_numpy()})
    prediction.to_csv(folder / "predictions.csv.gz", index=False)
    cached = pd.DataFrame({"sample_index": np.arange(1000, 1400), "EVENT": labels,
                          "baseline": arrays["baseline"], "candidate": arrays["reference"],
                          "baseline_score": raw.baseline_score.to_numpy()})
    cached.to_csv(prior / "predictions.csv.gz", index=False)
    calibration.to_csv(folder / "calibration_scores.csv.gz", index=False)
    calibration.to_csv(prior / "calibration_scores.csv.gz", index=False)
    pd.DataFrame([{"feasible": True}]).to_csv(folder / "calibration_trials.csv.gz", index=False)
    (prior / "bundle.joblib").write_bytes(b"synthetic prior; never unpickled")
    dump(prior / "freeze.json", {"bundle_sha256": replay.sha(prior / "bundle.joblib")})
    frozen = {"plan_sha256": "synthetic-plan", "development_only": True,
              **{k: spec[k] for k in ("train", "calibration_starts", "test", "continuous_cal")},
              "prior_folder": "prior", "prior_sha256": {name: replay.sha(prior / name) for name in
                  ("bundle.joblib", "freeze.json", "predictions.csv.gz", "calibration_scores.csv.gz")},
              "bundle_sha256": replay.sha(folder / "bundle.joblib"), "selected": selected}
    dump(folder / "freeze.json", frozen)
    dump(folder / "model_inspection.json", model.inspection())
    result = {"case": spec["name"], "source": spec["source"], "development_only": True,
              "selected": selected, "fit_status": "synthetic",
              "comparisons": replay.recompute_comparisons(labels, arrays, comparison)}
    dump(folder / "results.json", result)
    return out, source, spec, result


class ReplayAuditTests(unittest.TestCase):
    def test_explicit_attempt_dispatch_and_unknown_version_refusal(self):
        self.assertEqual(replay.method_spec({})["runtime"], "ml.gecco_v7.runtime")
        method = replay.method_spec({"attempt": "run02_hgb_guarded"})
        self.assertEqual(method["runtime"], "ml.gecco_v7.runtime_v2")
        self.assertEqual(method["model_class"], "LongContextHGBScorer")
        self.assertTrue(method["guarded_score"])
        self.assertIn("long_context_hgb.py", method["extra_code"])
        with self.assertRaises(ValueError):
            replay.method_spec({"attempt": "unreviewed_model"})

    def test_synthetic_saved_case_full_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out, frame, spec, saved = make_case(root)
            checks = replay.Checks()
            measured, rows = replay._audit_case(root, out, spec, frame, saved, "synthetic-plan", checks, {}, synthetic_runtime, comparison, stats)
            self.assertTrue(all(row["passed"] for row in checks.records), [r for r in checks.records if not r["passed"]])
            self.assertEqual(len(rows), 400)
            self.assertEqual(measured["comparisons"], saved["comparisons"])
            self.assertTrue(any("full_test_runtime:long_context" in row["check"] for row in checks.records))

    def test_hgb_guarded_score_path_and_guard_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out, source, spec, saved = make_case(root)
            folder, prior = out / spec["name"], root / "prior"
            bundle = joblib.load(folder / "bundle.joblib")
            bundle["version"] = "synthetic_guarded"
            joblib.dump(bundle, folder / "bundle.joblib")
            calibration = pd.read_csv(folder / "calibration_scores.csv.gz", float_precision="round_trip")
            local = guarded_synthetic_runtime(bundle, source.iloc[200:1000])
            for key in ("level", "jump", "sustained"):
                calibration[key] = local[key].to_numpy()
            calibration.to_csv(prior / "calibration_scores.csv.gz", index=False)
            guard = calibration.long_context.to_numpy().copy()
            guard[calibration.level.to_numpy() > 1] = np.nan
            calibration["guarded_long_context"] = guard
            calibration.to_csv(folder / "calibration_scores.csv.gz", index=False)
            saved_predictions = pd.read_csv(folder / "predictions.csv.gz", float_precision="round_trip")
            actual = guarded_synthetic_runtime(bundle, source.iloc[1000:])
            saved_predictions["guarded_long_context"] = actual.guarded_long_context.to_numpy()
            saved_predictions.to_csv(folder / "predictions.csv.gz", index=False)
            frozen = json.loads((folder / "freeze.json").read_text())
            frozen["bundle_sha256"] = replay.sha(folder / "bundle.joblib")
            frozen["prior_sha256"]["calibration_scores.csv.gz"] = replay.sha(prior / "calibration_scores.csv.gz")
            dump(folder / "freeze.json", frozen)
            method = {"bundle_version": "synthetic_guarded", "model_class": "SyntheticModel", "guarded_score": True}
            checks = replay.Checks()
            replay._audit_case(root, out, spec, source, saved, "synthetic-plan", checks, {}, guarded_synthetic_runtime, comparison, stats, method)
            self.assertTrue(all(row["passed"] for row in checks.records), [row for row in checks.records if not row["passed"]])
            self.assertTrue(any("calibration_guarded_long_score" in row["check"] for row in checks.records))
            saved_predictions.loc[200, "guarded_long_context"] = 42
            saved_predictions.to_csv(folder / "predictions.csv.gz", index=False)
            checks = replay.Checks()
            replay._audit_case(root, out, spec, source, saved, "synthetic-plan", checks, {}, guarded_synthetic_runtime, comparison, stats, method)
            self.assertTrue(any(not row["passed"] and "full_test_runtime:guarded_long_context" in row["check"] for row in checks.records))

    def test_changed_saved_score_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out, frame, spec, saved = make_case(root)
            path = out / spec["name"] / "predictions.csv.gz"
            data = pd.read_csv(path, float_precision="round_trip")
            data.loc[200, "long_context"] += .1
            data.to_csv(path, index=False)
            checks = replay.Checks()
            replay._audit_case(root, out, spec, frame, saved, "synthetic-plan", checks, {}, synthetic_runtime, comparison, stats)
            self.assertTrue(any(not row["passed"] and "full_test_runtime:long_context" in row["check"] for row in checks.records))

    def test_changed_bundle_refused_before_unpickle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out, frame, spec, saved = make_case(root)
            with (out / spec["name"] / "bundle.joblib").open("ab") as file:
                file.write(b"tampered")
            with patch("joblib.load", side_effect=AssertionError("must not unpickle")):
                with self.assertRaisesRegex(ValueError, "bundle_sha_before_unpickle"):
                    replay._audit_case(root, out, spec, frame, saved, "synthetic-plan", replay.Checks(), {}, synthetic_runtime, comparison, stats)

    def test_changed_fit_boundary_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out, frame, spec, saved = make_case(root)
            path = out / spec["name"] / "bundle.joblib"
            bundle = joblib.load(path)
            bundle["max_fit_index"] = 1001
            joblib.dump(bundle, path)
            frozen_path = path.with_name("freeze.json")
            frozen = json.loads(frozen_path.read_text())
            frozen["bundle_sha256"] = replay.sha(path)
            dump(frozen_path, frozen)
            with self.assertRaisesRegex(ValueError, "max_fit_cal_indices"):
                replay._audit_case(root, out, spec, frame, saved, "synthetic-plan", replay.Checks(), {}, synthetic_runtime, comparison, stats)

    def test_incomplete_run_cannot_open_sources_or_write_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump(root / "results.json", {"complete_cases": 1})
            dump(root / "plan.json", {"scope": "all", "limit_cases": 19})
            with patch.object(replay, "_source_frames", side_effect=AssertionError("no source read")), patch("joblib.load", side_effect=AssertionError("no bundle read")):
                with self.assertRaisesRegex(ValueError, "All 19 fixed"):
                    replay.audit_directory(root, workspace_root=root)
            self.assertFalse((root / "audit.json").exists())

    def test_tree_and_array_tolerance_nan_masks(self):
        checks = replay.Checks()
        self.assertTrue(checks.array("good", [np.nan, .1], [np.nan, .1 + 1e-13], floating=True))
        self.assertFalse(checks.array("nan moved", [np.nan, .1], [.1, np.nan], floating=True))
        self.assertFalse(checks.array("large change", [.1], [.1 + 1e-10], floating=True))
        self.assertFalse(checks.array("shape", np.ones((2, 1)), np.ones(2)))
        self.assertTrue(checks.tree("nested", {"a": [1, None, True, .1]}, {"a": [1, None, True, .1]}))
        self.assertFalse(checks.tree("keys", {"a": 1, "extra": 1}, {"a": 1}))
        self.assertFalse(checks.tree("bool type", {"a": 1}, {"a": True}))

    def test_representative_prefix_future_mutation_and_label_independence(self):
        frame = pd.DataFrame({"a": np.sin(np.arange(3000) / 13)})
        checks = replay.Checks()
        full = synthetic_runtime({}, frame)
        replay._causality_checks(checks, "synthetic", {}, frame, full, synthetic_runtime)
        self.assertTrue(all(r["passed"] for r in checks.records))
        self.assertTrue(any("future_mutation" in r["check"] for r in checks.records))
        self.assertTrue(any("labels_ignored" in r["check"] for r in checks.records))

    def test_future_leaking_runtime_is_detected(self):
        frame = pd.DataFrame({"a": np.arange(3000, dtype=float)})
        def leaky(bundle, data):
            output = synthetic_runtime(bundle, data)
            output["long_context"] = data.a.mean()
            return output
        checks = replay.Checks()
        replay._causality_checks(checks, "leaky", {}, frame, leaky({}, frame), leaky)
        self.assertTrue(any(not r["passed"] and "future_mutation" in r["check"] for r in checks.records))

    def test_comparison_preserves_unknown_and_original_event_ids(self):
        labels = np.array([0, 1, 1, -1, 1, 0, 1, 0], dtype=np.int8)
        baseline = np.array([0, 1, 0, 1, 1, 0, 0, 0], dtype=np.int8)
        candidate = np.array([0, 1, 1, 1, 1, 0, 1, 0], dtype=np.int8)
        result = replay.recompute_comparisons(labels, {"baseline": baseline, "reference": baseline, "candidate": candidate}, comparison)["v6_vs_v7"]
        self.assertEqual(result["baseline"]["true_events"], 2)
        self.assertEqual(result["candidate"]["confirmed_event_ids"], [1, 3])
        self.assertEqual(result["candidate"]["left_censored_positive_segments"], 1)
        self.assertEqual(result["new_candidate_event_ids"], [3])
        self.assertEqual(result["lost_positive_alarm_rows"], 0)

    def test_source_pool_does_not_double_count_split_event(self):
        labels = np.array([0, 1, 1, 1, 0], np.int8)
        prediction = np.array([0, 1, 1, 1, 0], np.int8)
        whole = replay.recompute_comparisons(labels, {key: prediction for key in ("baseline", "reference", "candidate")}, comparison)
        a = replay.recompute_comparisons(labels[:3], {key: prediction[:3] for key in ("baseline", "reference", "candidate")}, comparison)
        b = replay.recompute_comparisons(labels[3:], {key: prediction[3:] for key in ("baseline", "reference", "candidate")}, comparison)
        self.assertEqual(whole["v6_vs_v7"]["baseline"]["true_events"], 1)
        self.assertEqual(b["v6_vs_v7"]["baseline"]["left_censored_positive_segments"], 1)
        summary = replay.independent_summary([{"comparisons": a}, {"comparisons": b}], {"one_source": whole})
        self.assertEqual(summary["v6_vs_v7"]["baseline"]["true_events"], 1)
        self.assertFalse(summary["v6_vs_v7"]["passes_declared_development_gate"])

    def test_noninferiority_alone_is_not_improvement_gate(self):
        labels = np.array([0, 1, 0, 0], np.int8)
        p = np.array([0, 1, 0, 0], np.int8)
        measured = replay.recompute_comparisons(labels, {key: p for key in ("baseline", "reference", "candidate")}, comparison)
        summary = replay.independent_summary([{"comparisons": measured}] * 19, {"source": measured})
        result = summary["v6_vs_v7"]
        self.assertEqual(result["noninferior_periods"], 19)
        self.assertFalse(result["passes_declared_development_gate"])
        self.assertFalse(result["checks"]["strictly_more_pooled_events"])
        self.assertFalse(result["checks"]["strictly_fewer_pooled_false_runs"])

    def test_fixed_geometry_has_all19_contiguous_test_periods(self):
        sources = {"2017": range(122334), "2018": range(139566), "2019": range(1000 + 800 + 31650)}
        specs = replay.expected_geometry(sources, 1000, 800)
        self.assertEqual([s["name"] for s in specs], replay.EXPECTED_NAMES)
        for source in ("2017", "2018", "WaterHub"):
            periods = [s for s in specs if s["source"] == source]
            self.assertTrue(all(a["test"][1] == b["test"][0] for a, b in zip(periods[:-1], periods[1:])))
        for spec in specs:
            self.assertEqual(spec["train"][1], spec["calibration_starts"][0])
            self.assertLess(spec["calibration_starts"][-1], spec["test"][0])

    def test_path_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                replay.inside(directory, "../elsewhere")


if __name__ == "__main__":
    unittest.main()
