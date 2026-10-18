"""Independent completed-run V7 batch replay, with no model fit or selection.

Import performs no file IO. Invoke only for an authorized, fully completed
19-case development run. GECCO sensor rows come from the publisher CSV inputs;
WaterHub sensor rows come from the unchanged, independently rederived adapted
cache. Its pinned source-replay evidence and full raw archive SHA are verified
here; this audit does NOT itself regenerate the WaterHub adaptation.

Only trusted local joblib bundles are loaded, after matching freeze SHA256.
Established V6 ternary-label metrics are reused intentionally; comparisons,
source pooling and the top-level gate are recomputed outside the V7 runner.
This is batch replay and representative prefix/future-mutation checking, NOT
a V7 streaming implementation, independent fresh validation, or field proof.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import importlib
import json
import math
from numbers import Real
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ATOL = 1e-12
GAP = 120
CHANNELS_18 = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
CHANNELS_19 = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
WATERHUB = "output/ml/gecco-v6-waterhub-first-use"
SOURCE_EVIDENCE_SHA = "2c3fbd8716c8474b51a47e81cf0552e1f5c51b0b35ba1d7f6c2bf376f3bea729"
WATERHUB_CACHE_SHA = "2ebd0997afb7571390c7df6b5b64616dec81441b304f6a02ff323b6218984ff7"
ARCHIVE_SHA = "f91e930d1e194f401f4570c8ddbfdd90606475233e2f6cd36114ff9da11fc8b0"
EXPECTED_NAMES = ([f"{year}_fold_{fold}" for year in (2017, 2018) for fold in range(1, 7)]
                  + ["2019_disclosed_test", "2018-11", "2018-12", "2019-01", "2019-02", "2019-03", "2019-04"])
REPRESENTATIVE_NAMES = {"2017_fold_1", "2018_fold_1", "2019_disclosed_test", "2018-11", "2019-04"}
PAIRS = {"if_vs_v6": ("baseline", "reference"), "if_vs_v7": ("baseline", "candidate"),
         "v6_vs_v7": ("reference", "candidate")}


def method_spec(plan):
    """Explicit version dispatch; never infer a model from observed performance."""
    attempt = plan.get("attempt")
    if attempt is None:
        return {"runtime": "ml.gecco_v7.runtime", "bundle_version": None,
                "model_class": "LongContextEventScorer", "guarded_score": False,
                "extra_code": []}
    if attempt == "run02_hgb_guarded":
        return {"runtime": "ml.gecco_v7.runtime_v2", "bundle_version": "v7_hgb_guarded_v2",
                "model_class": "LongContextHGBScorer", "guarded_score": True,
                "extra_code": ["development_v2.py", "runtime_v2.py", "calibration_v2.py", "long_context_hgb.py"]}
    raise ValueError("Unknown V7 attempt; an explicit reviewed audit dispatch is required")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path escapes declared artifact/workspace root")
    return path


class Checks:
    def __init__(self):
        self.records = []

    def add(self, name, passed, count=1, numeric=0, detail=None):
        row = {"check": name, "passed": bool(passed), "compared_values": int(count),
               "numeric_comparisons": int(numeric)}
        if detail is not None:
            row["detail"] = detail
        self.records.append(row)
        return bool(passed)

    def require(self, name, passed, detail=None):
        if not self.add(name, passed, detail=detail):
            raise ValueError(name)

    def array(self, name, actual, expected, *, floating=False):
        a, b = np.asarray(actual), np.asarray(expected)
        count = max(a.size, b.size)
        if a.shape != b.shape:
            return self.add(name, False, count, count, "Shape mismatch")
        equal = np.isclose(a.astype(float), b.astype(float), atol=ATOL, rtol=0, equal_nan=True) if floating else a == b
        detail = {"mismatches": int((~equal).sum())}
        if floating:
            finite = np.isfinite(a) & np.isfinite(b)
            detail["maximum_finite_absolute_difference"] = float(np.max(np.abs(a[finite] - b[finite]))) if finite.any() else 0.0
            detail["nan_mask_equal"] = bool(np.array_equal(np.isnan(a), np.isnan(b)))
        return self.add(name, equal.all(), count, count, detail)

    def tree(self, name, actual, expected):
        count = numeric = 0
        mismatches = []

        def walk(a, b, path):
            nonlocal count, numeric
            count += 1
            if isinstance(b, dict):
                if not isinstance(a, dict) or set(a) != set(b):
                    mismatches.append(path + ":keys")
                if isinstance(a, dict):
                    for key in b.keys() & a.keys():
                        walk(a[key], b[key], path + "." + str(key))
            elif isinstance(b, list):
                if not isinstance(a, list) or len(a) != len(b):
                    mismatches.append(path + ":length")
                if isinstance(a, list):
                    for index, (av, bv) in enumerate(zip(a, b)):
                        walk(av, bv, path + f"[{index}]")
            else:
                numeric += isinstance(b, Real)
                if isinstance(b, float):
                    equal = isinstance(a, Real) and not isinstance(a, bool) and math.isfinite(a) and abs(a - b) <= ATOL
                else:
                    equal = a == b and (not isinstance(b, bool) or isinstance(a, bool))
                if not equal:
                    mismatches.append(path)

        walk(actual, expected, name)
        return self.add(name, not mismatches, count, numeric,
                        {"mismatches": len(mismatches), "first_mismatch_paths": mismatches[:10]})


def ternary(values, name):
    values = np.asarray(values)
    if values.ndim != 1 or values.dtype.kind not in "biu" or not np.isin(values, [-1, 0, 1]).all():
        raise ValueError(name + " must be original-axis integer -1/0/1")
    return values.astype(np.int8, copy=False)


def recompute_comparisons(labels, arrays, comparison):
    """Established point/event semantics, independently enriched V7 decisions."""
    results = {}
    for key, (left, right) in PAIRS.items():
        b, c = arrays[left], arrays[right]
        result = comparison(labels, b, c, 60)
        base, candidate = result["baseline"], result["candidate"]
        result["noninferior"] = bool(
            not result["lost_baseline_event_ids"] and result["sensor_availability_equal"]
            and all(item["extra_delay_seconds"] <= 0 for item in result["paired_extra_delays"])
            and candidate["false_positive_runs"] <= base["false_positive_runs"]
            and candidate["fp"] <= base["fp"])
        result["lost_positive_alarm_rows"] = int(np.count_nonzero((labels == 1) & (b == 1) & (c != 1)))
        results[key] = result
    return results


def independent_summary(periods, sources):
    """Source intervals are accounted first; independent sources then summed."""
    sum_keys = ("true_events", "confirmed_events", "tp", "fp", "fn", "tn", "false_positive_runs",
                "normal_observed_seconds", "fp_duration_seconds", "known_positive_rows",
                "positive_unavailable_rows", "rows", "available_rows")
    ratio = lambda a, b: a / b if b else None
    answer = {}
    for key in PAIRS:
        per = [part["comparisons"][key] for part in periods]
        pooled = [part[key] for part in sources.values()]
        summed = {}
        for side in ("baseline", "candidate"):
            totals = {name: sum(part[side][name] for part in pooled) for name in sum_keys}
            totals.update(
                confirmed_event_recall=ratio(totals["confirmed_events"], totals["true_events"]),
                precision=ratio(totals["tp"], totals["tp"] + totals["fp"]),
                recall_observed_positive=ratio(totals["tp"], totals["tp"] + totals["fn"]),
                f1_observed_points=ratio(2 * totals["tp"], 2 * totals["tp"] + totals["fp"] + totals["fn"]),
                false_runs_per_day=ratio(totals["false_positive_runs"] * 86400, totals["normal_observed_seconds"]))
            summed[side] = totals
        b, c = summed["baseline"], summed["candidate"]
        event_gain = sum(len(part["new_candidate_event_ids"]) > 0 for part in per)
        fp_gain = sum(part["candidate"]["false_positive_runs"] < part["baseline"]["false_positive_runs"] for part in per)
        rules = {
            "all_prespecified_cases_complete": len(periods) == 19,
            "all_periods_and_source_pools_noninferior": all(part["noninferior"] for part in per + pooled),
            "strictly_more_pooled_events": c["confirmed_events"] > b["confirmed_events"],
            "strictly_fewer_pooled_false_runs": c["false_positive_runs"] < b["false_positive_runs"],
            "event_gain_in_at_least_two_periods": event_gain >= 2,
            "false_run_reduction_in_at_least_two_periods": fp_gain >= 2,
        }
        if key == "v6_vs_v7":
            rules["no_additional_positive_alarm_row_loss_relative_v6"] = all(part["lost_positive_alarm_rows"] == 0 for part in per + pooled)
        answer[key] = {**summed, "checks": rules, "noninferior_periods": sum(part["noninferior"] for part in per),
                       "periods": len(per), "event_gain_periods": event_gain, "false_run_reduction_periods": fp_gain,
                       "passes_declared_development_gate": all(rules.values())}
    return answer


def expected_geometry(sources, train19_rows, valid19_rows):
    """Independent reconstruction of the declared fixed acquisition-row splits."""
    specifications = []
    for year, n in (("2017", 122334), ("2018", 139566)):
        if len(sources[year]) != n:
            raise ValueError("Unexpected fixed GECCO source row count")
        for fold in range(1, 7):
            tenth = fold + 3
            a, b, c = [n * value // 10 for value in (tenth - 2, tenth, tenth + 1)]
            specifications.append({"name": f"{year}_fold_{fold}", "source": year, "train": [0, a],
                "calibration_starts": np.linspace(a, b, 5, dtype=int)[:-1].tolist(), "test": [b, c],
                "continuous_cal": False, "channels": CHANNELS_18})
    n19 = train19_rows + valid19_rows
    if len(sources["2019"]) != n19 + 31650:
        raise ValueError("Unexpected fixed GECCO 2019 test row count")
    specifications.append({"name": "2019_disclosed_test", "source": "2019", "train": [0, train19_rows],
        "calibration_starts": (np.linspace(0, valid19_rows, 5, dtype=int)[:-1] + train19_rows).tolist(),
        "test": [n19, n19 + 31650], "continuous_cal": True, "channels": CHANNELS_19})
    origin = pd.Timestamp("2018-06-01")
    for start in pd.date_range("2018-11-01", "2019-04-01", freq="MS"):
        a, b, c = [int((date - origin).total_seconds() // 60) for date in
                   (start - pd.DateOffset(months=2), start, start + pd.DateOffset(months=1))]
        specifications.append({"name": start.strftime("%Y-%m"), "source": "WaterHub", "train": [0, a],
            "calibration_starts": np.linspace(a, b, 5, dtype=int)[:-1].tolist(), "test": [b, c],
            "continuous_cal": False, "channels": ["p1", "p2", "p3", "p4"]})
    return specifications


def _source_frames(root):
    # Exact parsing mode of the frozen runner is intentional: GECCO uses the
    # ordinary CSV parser; the previously serialized WaterHub uses round_trip.
    sources = {year: pd.read_csv(root / f"data/external/gecco{year}/1_gecco{year}_water_quality.csv")
               .rename(columns={"EVENT": "label"}) for year in ("2017", "2018")}
    parts = [pd.read_csv(root / "data/external/gecco2019" / filename)
             .rename(columns={"Event": "label", "EVENT": "label"}) for filename in
             ("7_gecco2019_train_water_quality.csv", "8_gecco2019_valid_water_qulity.csv", "6_gecco2019_test_water_quality.csv")]
    ntrain, nvalid = len(parts[0]), len(parts[1])
    sources["2019"] = pd.concat(parts, ignore_index=True)
    sources["WaterHub"] = pd.read_csv(root / WATERHUB / "adapted_source.csv.gz", index_col=0,
                                       parse_dates=True, float_precision="round_trip")
    for source, frame in sources.items():
        frame["label"] = ternary(frame["label"].to_numpy(), source + " labels")
    return sources, ntrain, nvalid


def _verify_provenance(root, out, plan, checks, hashes):
    required_code = {"ml/gecco_v7/" + name for name in
                     ("development.py", "runtime.py", "calibration.py", "long_context.py")}
    required_code |= {"ml/gecco_v6/runtime_v4.py", "ml/gecco_v6/unknown_label_metrics.py"}
    required_code |= {"ml/gecco_v7/" + filename for filename in method_spec(plan)["extra_code"]}
    required_inputs = {f"data/external/gecco{year}/1_gecco{year}_water_quality.csv" for year in (2017, 2018)}
    required_inputs |= {"data/external/gecco2019/" + filename for filename in
                        ("7_gecco2019_train_water_quality.csv", "8_gecco2019_valid_water_qulity.csv", "6_gecco2019_test_water_quality.csv")}
    required_inputs.add(WATERHUB + "/adapted_source.csv.gz")
    checks.require("frozen_hashes_cover_all_replayed_core_and_sources", required_code.issubset(plan["code_sha256"])
                   and required_inputs.issubset(plan["input_sha256"]))
    for relative, expected in plan["code_sha256"].items():
        for label, parent in (("current_code", root), ("frozen_code", out / "source")):
            digest = sha(inside(parent, relative))
            hashes[label + "/" + relative] = digest
            checks.require(label + ":" + relative, digest == expected)
    for relative, expected in plan["input_sha256"].items():
        digest = sha(inside(root, relative))
        hashes["input/" + relative] = digest
        checks.require("input_sha:" + relative, digest == expected)
    evidence_path = root / WATERHUB / "source_runtime_replay_audit.json"
    evidence_sha = sha(evidence_path)
    hashes["reused_waterhub_source_audit"] = evidence_sha
    checks.require("pinned_prior_waterhub_source_replay_evidence", evidence_sha == SOURCE_EVIDENCE_SHA)
    evidence = read_json(evidence_path)
    checks.require("prior_waterhub_source_audit_passed", evidence["passed"] is True
                   and evidence["source_rows_rederived"] == 480960 and evidence["source_members_verified"] == 82)
    checks.require("prior_source_auditor_code_hash", sha(root / "ml/gecco_v6_audits/source_runtime_replay.py") == evidence["audit_script_sha256"])
    protocol = read_json(root / WATERHUB / "protocol.json")
    archive = inside(root, protocol["archive_path"])
    hashes["raw_waterhub_archive"] = sha(archive)
    checks.require("unchanged_whole_raw_waterhub_archive", hashes["raw_waterhub_archive"] == protocol["archive_sha256"] == evidence["archive_sha256"] == ARCHIVE_SHA)
    cache_relative = WATERHUB + "/adapted_source.csv.gz"
    checks.require("unchanged_independently_rederived_waterhub_cache", plan["input_sha256"][cache_relative] == evidence["adapted_source_sha256"] == WATERHUB_CACHE_SHA)
    return {"evidence": str(evidence_path.relative_to(root)), "evidence_sha256": evidence_sha,
            "source_rows_previously_rederived": evidence["source_rows_rederived"],
            "adapted_source_sha256": WATERHUB_CACHE_SHA, "raw_archive_sha256": ARCHIVE_SHA,
            "adaptation_reexecuted_by_this_audit": False}


def _load_runtime(root, plan):
    sys.path.insert(0, str(root))
    for name in ("gecco_v2", "gecco_v5", "gecco_v6"):
        sys.path.insert(0, str(root / "ml" / name))
    runtime_name = method_spec(plan)["runtime"]
    runtime = importlib.import_module(runtime_name)
    metrics = importlib.import_module("unknown_label_metrics")
    if Path(runtime.__file__).resolve() != root / (runtime_name.replace(".", "/") + ".py"):
        raise ValueError("Runtime did not resolve to verified code")
    if Path(metrics.__file__).resolve() != root / "ml/gecco_v6/unknown_label_metrics.py":
        raise ValueError("Metrics did not resolve to verified code")
    return runtime.predict_frame, metrics.comparison, metrics.stats


def _runtime_table(checks, prefix, actual, expected):
    checks.tree(prefix + ":schema", list(actual.columns), list(expected.columns))
    for column in expected.columns:
        if column in actual:
            checks.array(prefix + ":" + column, actual[column].to_numpy(), expected[column].to_numpy(),
                         floating=expected[column].dtype.kind == "f")


def _causality_checks(checks, name, bundle, sensors, full, runtime):
    stops = sorted(set(min(len(sensors), n) for n in (0, 120, 121, 180, 181, 512, 2500)))
    for stop in stops:
        prefix = runtime(bundle, sensors.iloc[:stop])
        _runtime_table(checks, f"{name}:prefix_{stop}", prefix, full.iloc[:stop])
    stop = min(2500, max(1, len(sensors) // 2))
    changed = sensors.copy()
    # Change only the future; no statistics from it determine the mutation.
    changed.iloc[stop:, :] = 1e9
    if len(changed) > stop + 1:
        changed.iloc[stop + 1::7, :] = np.nan
    actual = runtime(bundle, changed)
    _runtime_table(checks, name + ":future_mutation_prefix", actual.iloc[:stop], full.iloc[:stop])
    augmented = sensors.iloc[:stop].copy()
    augmented["label"] = (np.arange(stop) % 3 - 1).astype(np.int8)
    augmented["EVENT"] = np.arange(stop) % 2
    _runtime_table(checks, name + ":labels_ignored", runtime(bundle, augmented), full.iloc[:stop])


def _audit_case(root, out, spec, source, saved_top, plan_sha, checks, hashes, runtime, comparison, stats, method=None):
    import joblib  # Executable trusted local bundle only, after matching hashes.
    name = spec["name"]
    folder = inside(out, name)
    frozen = read_json(folder / "freeze.json")
    result = read_json(folder / "results.json")
    checks.tree(name + ":result_matches_top_level_period", result, saved_top)
    checks.require(name + ":result_case_and_source_identity", result["case"] == name and result["source"] == spec["source"])
    checks.require(name + ":plan_hash", frozen["plan_sha256"] == plan_sha)
    checks.require(name + ":development_only", frozen["development_only"] is True and result["development_only"] is True)
    for key in ("train", "calibration_starts", "test", "continuous_cal"):
        checks.tree(name + ":independent_geometry:" + key, frozen[key], spec[key])
    a, (left, right) = spec["train"][1], spec["test"]
    bounds = spec["calibration_starts"] + [left]
    checks.require(name + ":strict_past_split", spec["train"][0] == 0 < a == bounds[0]
                   and all(x < y for x, y in zip(bounds[:-1], bounds[1:])) and left < right <= len(source))
    prior = inside(root, frozen["prior_folder"])
    prior_freeze = read_json(prior / "freeze.json")
    for filename, expected in frozen["prior_sha256"].items():
        digest = sha(prior / filename)
        hashes[name + "/prior/" + filename] = digest
        checks.require(name + ":prior_sha:" + filename, digest == expected)
    checks.require(name + ":prior_bundle_freeze_hash", frozen["prior_sha256"]["bundle.joblib"] == prior_freeze["bundle_sha256"])
    digest = sha(folder / "bundle.joblib")
    hashes[name + "/bundle.joblib"] = digest
    checks.require(name + ":bundle_sha_before_unpickle", digest == frozen["bundle_sha256"])
    bundle = joblib.load(folder / "bundle.joblib")
    if method is not None:
        checks.require(name + ":bundle_version_matches_plan", bundle.get("version") == method["bundle_version"])
        checks.require(name + ":model_class_matches_plan", type(bundle["long_model"]).__name__ == method["model_class"])
    checks.require(name + ":max_fit_cal_indices_before_test", bundle["max_fit_index"] == a - 1 < left
                   and bundle["max_calibration_index"] == left - 1 and bundle["max_fit_index"] < bundle["max_calibration_index"])
    checks.require(name + ":cadence_gap", bundle["sample_seconds"] == 60 and bundle["gap_samples"] == GAP)
    checks.tree(name + ":frozen_operating_point", bundle["selected"], frozen["selected"])
    checks.tree(name + ":result_operating_point", result["selected"], frozen["selected"])
    model = bundle["long_model"]
    checks.tree(name + ":configured_sensor_order", model.channels, spec["channels"])
    checks.require(name + ":stored_training_axis", model.training_rows_ == a
                   and len(model.training_sample_weight_) == a and len(model.training_normalized_weight_) == a)
    train_y = source.label.iloc[:a].to_numpy(np.int8)
    checks.array(name + ":unknown_training_weight_zero", model.training_sample_weight_[train_y == -1], np.zeros(np.count_nonzero(train_y == -1)), floating=True)
    checks.tree(name + ":model_inspection_matches_saved", model.inspection(), read_json(folder / "model_inspection.json"))
    checks.require(name + ":fit_status_matches_result", model.fit_status_ == result["fit_status"])
    checks.require(name + ":reference_bundle_past_bounds", bundle["reference_bundle"]["max_fit_index"] == a - 1
                   and bundle["reference_bundle"]["max_calibration_index"] == left - 1)
    # Verify the actual fitted reference population counts, without fitting or
    # estimating any new model/reference parameters.
    for channel_index, channel in enumerate(spec["channels"]):
        values = source[channel].iloc[:a].to_numpy(float)
        normal = (train_y == 0) & np.isfinite(values)
        with np.errstate(over="ignore", invalid="ignore"):
            finite_delta = np.isfinite(np.diff(values))
        count = int(normal.sum())
        pairs = int(np.count_nonzero(normal[1:] & normal[:-1] & finite_delta))
        checks.require(name + ":training_reference_counts:" + channel,
                       model.normal_reference_counts_[channel_index] == count and model.normal_delta_counts_[channel_index] == pairs)
    for filename in ("freeze.json", "results.json", "predictions.csv.gz", "calibration_scores.csv.gz", "calibration_trials.csv.gz", "model_inspection.json"):
        hashes[name + "/" + filename] = sha(folder / filename)
    calibration = pd.read_csv(folder / "calibration_scores.csv.gz", float_precision="round_trip")
    checks.array(name + ":calibration_original_indices", calibration.sample_index.to_numpy(), np.arange(a, left))
    checks.array(name + ":calibration_labels_from_source", calibration.label.to_numpy(), source.label.iloc[a:left].to_numpy())
    if method is not None and method["guarded_score"]:
        prior_calibration = pd.read_csv(prior / "calibration_scores.csv.gz", float_precision="round_trip")
        checks.array(name + ":prior_calibration_axis", prior_calibration.sample_index.to_numpy(), np.arange(a, left))
        local = prior_calibration.loc[:, ["level", "jump", "sustained"]].to_numpy(float)
        ordinary = np.isfinite(local).all(axis=1) & (local <= 1).all(axis=1)
        expected_gate = calibration.long_context.to_numpy(float).copy()
        expected_gate[~ordinary] = np.nan
        checks.array(name + ":calibration_guarded_long_score", calibration.guarded_long_context.to_numpy(), expected_gate, floating=True)
    checks.tree(name + ":selected_calibration_metrics", stats(calibration.label.to_numpy(np.int8), calibration.candidate.to_numpy(np.int8), 60), bundle["selected"]["calibration_metrics"])
    for index, (begin, end) in enumerate(zip(bounds[:-1], bounds[1:])):
        part = calibration.iloc[begin - a:end - a]
        checks.tree(name + f":selected_calibration_block_{index}", stats(part.label.to_numpy(np.int8), part.candidate.to_numpy(np.int8), 60), bundle["selected"]["calibration_block_metrics"][index])
    test = source.iloc[left:right]
    saved = pd.read_csv(folder / "predictions.csv.gz", float_precision="round_trip")
    checks.array(name + ":test_original_indices", saved.sample_index.to_numpy(), np.arange(left, right))
    labels = test.label.to_numpy(np.int8)
    checks.array(name + ":test_labels_from_source", saved.label.to_numpy(), labels)
    sensors = test.loc[:, spec["channels"]]
    replay = runtime(bundle, sensors)
    checks.require(name + ":runtime_original_axis", len(replay) == right - left and replay.index.equals(sensors.index))
    for saved_key, runtime_key in (("baseline", "baseline_prediction"), ("reference", "reference_prediction"),
                                   ("candidate", "prediction"), ("long_context", "long_context")):
        checks.array(name + ":full_test_runtime:" + saved_key, replay[runtime_key].to_numpy(), saved[saved_key].to_numpy(), floating=saved_key == "long_context")
    if method is not None and method["guarded_score"]:
        checks.array(name + ":full_test_runtime:guarded_long_context", replay.guarded_long_context.to_numpy(), saved.guarded_long_context.to_numpy(), floating=True)
    checks.array(name + ":prediction_availability_equal_reference", replay.prediction.to_numpy() >= 0, replay.reference_prediction.to_numpy() >= 0)
    checks.require(name + ":gap_excluded_before_scoring", (replay.prediction.iloc[:GAP] == -1).all()
                   and replay.long_context.iloc[:GAP].isna().all())
    cached = pd.read_csv(prior / "predictions.csv.gz", float_precision="round_trip")
    checks.array(name + ":prior_cache_original_indices", cached.sample_index.to_numpy(), np.arange(left, right))
    cache_label = "label" if spec["source"] == "WaterHub" else "EVENT"
    checks.array(name + ":prior_cache_labels_from_source", cached[cache_label].to_numpy(), labels)
    for current, old in (("baseline_prediction", "baseline_prediction" if spec["source"] == "WaterHub" else "baseline"),
                         ("reference_prediction", "prediction" if spec["source"] == "WaterHub" else "candidate")):
        checks.array(name + ":actual_reference_replay_vs_cache:" + current, replay[current].to_numpy(), cached[old].to_numpy())
    # Cached score columns exist for V6 as well. Validate every directly
    # corresponding score, beyond the required saved final/reference outputs.
    for column in replay.columns:
        if column in cached.columns and column not in ("prediction", "available", "ignored_gap"):
            checks.array(name + ":prior_cache_score:" + column, replay[column].to_numpy(), cached[column].to_numpy(), floating=replay[column].dtype.kind == "f")
    arrays = {"baseline": ternary(replay.baseline_prediction.to_numpy(), "IF"),
              "reference": ternary(replay.reference_prediction.to_numpy(), "V6"),
              "candidate": ternary(replay.prediction.to_numpy(), "V7")}
    measured = recompute_comparisons(labels, arrays, comparison)
    checks.tree(name + ":recomputed_full_period_metrics", measured, result["comparisons"])
    if name in REPRESENTATIVE_NAMES:
        _causality_checks(checks, name, bundle, sensors, replay, runtime)
    # Reading a stored artifact must not mutate it during replay.
    checks.require(name + ":bundle_unchanged_after_replay", sha(folder / "bundle.joblib") == digest)
    rows = pd.DataFrame({"sample_index": np.arange(left, right), "label": labels, **arrays})
    return {"case": name, "source": spec["source"], "comparisons": measured}, rows


def audit_directory(output, *, workspace_root=None):
    """Only output/audit.json is written, after complete-run metadata exists."""
    out = Path(output).resolve()
    root = Path(workspace_root).resolve() if workspace_root else Path(__file__).resolve().parents[2]
    # Gate actual source/bundle access and any report write on completed scope.
    completed = read_json(out / "results.json")
    plan = read_json(out / "plan.json")
    if (plan.get("scope") != "all" or plan.get("limit_cases") != 19
            or completed.get("complete_cases") != 19 or completed.get("expected_cases") != 19
            or completed.get("all_prespecified_cases_complete") is not True
            or [p.get("case") for p in completed.get("periods", [])] != EXPECTED_NAMES
            or not completed.get("completed_at_utc") or (out / "failed_case.json").exists()):
        raise ValueError("All 19 fixed cases must be complete before audit source access or report write")
    checks, hashes = Checks(), {}
    report = {"audit_version": "v7_full_raw_sensor_batch_replay_v1", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "audit_script_sha256": sha(__file__), "passed": False, "development_only": True,
              "fresh_validation": False, "v7_streaming_tested": False, "model_refit": False,
              "absolute_float_tolerance": ATOL, "checks": checks.records, "hashes": hashes,
              "replayed_rows": 0, "complete_replayed_cases": 0,
              "attempt": plan.get("attempt", "run01_extratrees"),
              "limitations": [
                  "PASS verifies the checked artifacts and arithmetic; it is not model success or deployment approval.",
                  "All 19 cases use already-disclosed development sources; no genuinely unused final source is tested.",
                  "WaterHub adaptation evidence is reused and SHA-verified, not regenerated in this audit.",
                  "V7 inference tested here is batch; prefix tests are not a persistent-state streaming implementation.",
                  "Fitted artifacts and declared bounds are checked without retraining; historical absence of hidden access is not provable from artifacts alone.",
                  "V6 unknown-label metrics are intentionally reused; V7 pooling/summary are independently reconstructed."]}
    try:
        checks.require("all_19_complete_before_source_access", True)
        checks.require("declared_development_scope", plan.get("all_sources_previously_disclosed") is True
                       and plan.get("fresh_validation") is False and completed.get("fresh_validation") is False)
        hashes["plan.json"], hashes["results.json"] = sha(out / "plan.json"), sha(out / "results.json")
        report["reused_source_adaptation_audit"] = _verify_provenance(root, out, plan, checks, hashes)
        method = method_spec(plan)
        report["inference_module"] = method["runtime"]
        runtime, comparison, stats = _load_runtime(root, plan)
        sources, train19, valid19 = _source_frames(root)
        specs = expected_geometry(sources, train19, valid19)
        checks.tree("independent_prespecified_case_order", [spec["name"] for spec in specs], EXPECTED_NAMES)
        checks.require("waterhub_adapted_geometry", len(sources["WaterHub"]) == 480960)
        checks.array("waterhub_regular_minute_grid", np.diff(sources["WaterHub"].index.as_unit("ns").asi8), np.full(480959, 60 * 10**9))
        periods, by_source = [], {}
        for spec, saved in zip(specs, completed["periods"]):
            period, rows = _audit_case(root, out, spec, sources[spec["source"]], saved, hashes["plan.json"],
                                       checks, hashes, runtime, comparison, stats, method)
            periods.append(period)
            by_source.setdefault(spec["source"], []).append(rows)
            report["replayed_rows"] += len(rows)
            report["complete_replayed_cases"] += 1
            print(json.dumps({"audited_case": spec["name"], "rows": len(rows),
                              "cumulative_replayed_rows": report["replayed_rows"]}), flush=True)
            gc.collect()
        measured_sources = {}
        for source, parts in by_source.items():
            whole = pd.concat(parts, ignore_index=True)
            checks.array(source + ":pooled_contiguous_original_axis", np.diff(whole.sample_index), np.ones(len(whole) - 1, dtype=int))
            measured_sources[source] = recompute_comparisons(whole.label.to_numpy(np.int8),
                {column: whole[column].to_numpy(np.int8) for column in ("baseline", "reference", "candidate")}, comparison)
            checks.tree(source + ":source_pool_metrics", measured_sources[source], completed["sources"][source])
        summary = independent_summary(periods, measured_sources)
        checks.tree("independent_top_level_summary_and_all_gates", summary, completed["summary"])
        report["recomputed_development_gates"] = {key: value["passes_declared_development_gate"] for key, value in summary.items()}
        checks.require("completed_results_unchanged", sha(out / "results.json") == hashes["results.json"])
        for relative, expected in plan["code_sha256"].items():
            checks.require("current_code_unchanged_after_replay:" + relative, sha(inside(root, relative)) == expected)
    except Exception as error:
        report["exception"] = {"type": type(error).__name__, "message": str(error)}
        checks.add("audit_completed_without_exception", False, detail=str(error))
    report["failed_checks"] = sum(not row["passed"] for row in checks.records)
    report["total_check_groups"] = len(checks.records)
    report["total_numeric_checks"] = sum(row["numeric_comparisons"] for row in checks.records)
    report["total_compared_values"] = sum(row["compared_values"] for row in checks.records)
    report["passed"] = report["failed_checks"] == 0 and report["complete_replayed_cases"] == 19
    (out / "audit.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_directory(args.output)
    print(json.dumps({key: report[key] for key in ("passed", "failed_checks", "total_numeric_checks", "replayed_rows", "complete_replayed_cases")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
