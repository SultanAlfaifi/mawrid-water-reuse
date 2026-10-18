"""Post-test WaterHub minute-aggregation diagnosis, never a model or adapter.

Only the already consumed November 2018--April 2019 WaterHub members are read.
No import-time IO, fitting, thresholds, UWO access, label copying into pressure
features, or change to any frozen result. Each month is released before the next.
Run --self-test for synthetic checks; --run explicitly authorizes this diagnosis.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.gecco_v6.waterhub_adapter import CHANNELS, LABEL_STREAMS, adapt_waterhub
from ml.gecco_v6.waterhub_loader import load_waterhub_archive, waterhub_member_plan

MONTHS = ("2018-11", "2018-12", "2019-01", "2019-02", "2019-03", "2019-04")
PRIOR = ROOT / "output/ml/gecco-v6-waterhub-first-use"
OUT = ROOT / "output/ml/gecco-v7-diagnosis/aggregation_audit.json"
TEN_SECONDS_NS = 10_000_000_000


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def slots_and_target(annotations, starts):
    """Independent slot reconstruction; duplicate consensus, no unknown fill."""
    starts = starts.as_unit("ns")
    n = len(starts)
    expected = pd.DatetimeIndex((starts.asi8[:, None] +
                                np.arange(6) * TEN_SECONDS_NS).reshape(-1))
    slots = np.full((n, 6, 6), -1, dtype=np.int8)  # minute, stream, ten-second slot
    off_grid = np.zeros(n, dtype=bool)
    for k, stream in enumerate(LABEL_STREAMS):
        frame = annotations[stream]
        ts = frame.index.as_unit("ns")
        values = pd.to_numeric(frame.Anomaly, errors="coerce").to_numpy(dtype=float)
        valid = np.isfinite(values) & ((values == 0) | (values == 1))
        # Distinct min/max, plus an explicit invalid marker, resolves duplicates.
        group = pd.DataFrame({"v": values, "bad": ~valid}, index=ts).groupby(level=0)
        lo, hi, bad = group.v.min(), group.v.max(), group.bad.any()
        good = ~bad & (lo == hi)
        resolved = pd.Series(-1, index=lo.index, dtype=np.int8)
        resolved.loc[good] = lo.loc[good].astype(np.int8)
        slots[:, k, :] = resolved.reindex(expected, fill_value=-1).to_numpy().reshape(n, 6)
        off_grid |= starts.isin(ts[ts.asi8 % TEN_SECONDS_NS != 0].floor("min"))
    known = (slots >= 0).all(axis=(1, 2)) & ~off_grid
    target = np.where(known, (slots == 1).any(axis=(1, 2)), -1).astype(np.int8)
    return slots, target


def partition(slots, labels):
    positive = labels == 1
    last_positive = positive & (slots[:, :, 5] == 1).any(axis=1)
    earlier_only = positive & (slots[:, :, 5] == 0).all(axis=1)
    assert np.array_equal(positive, last_positive | earlier_only)
    assert not (last_positive & earlier_only).any()
    assert (slots[earlier_only, :, :5] == 1).any(axis=(1, 2)).all()
    return {"known_normal": labels == 0, "known_positive_at_50": last_positive,
            "known_positive_earlier_only": earlier_only, "unknown_label": labels < 0}


def raw_slots(raw_a, raw_b, starts):
    """Raw pressure only; duplicate timestamp values are deliberately unavailable."""
    starts = starts.as_unit("ns")
    expected = pd.DatetimeIndex((starts.asi8[:, None] +
                                np.arange(6) * TEN_SECONDS_NS).reshape(-1))
    result = np.full((len(starts), 6, 4), np.nan)
    for frame, channels in ((raw_a, CHANNELS[:2]), (raw_b, CHANNELS[2:])):
        unique = frame.loc[~frame.index.duplicated(keep=False)]
        for channel in channels:
            result[:, :, CHANNELS.index(channel)] = pd.to_numeric(
                unique[channel], errors="coerce").reindex(expected).to_numpy().reshape(-1, 6)
    return result


def interval_summary(labels, groups):
    """Descriptive original-minute positive intervals, with boundary censoring."""
    positive = labels == 1
    edges = np.flatnonzero(np.diff(np.r_[False, positive, False]))
    counts = {"positive_intervals": 0, "known_normal_preceded_intervals": 0,
              "boundary_or_unknown_preceded_intervals": 0,
              "entirely_earlier_only_intervals": 0,
              "entirely_earlier_only_known_normal_preceded_intervals": 0,
              "intervals_with_any_positive_at_50": 0}
    for start, end in edges.reshape(-1, 2):
        counts["positive_intervals"] += 1
        primary = start > 0 and labels[start - 1] == 0
        counts["known_normal_preceded_intervals" if primary else
               "boundary_or_unknown_preceded_intervals"] += 1
        earlier_only = groups["known_positive_earlier_only"][start:end].all()
        counts["entirely_earlier_only_intervals"] += int(earlier_only)
        counts["entirely_earlier_only_known_normal_preceded_intervals"] += int(earlier_only and primary)
        counts["intervals_with_any_positive_at_50"] += int(not earlier_only)
    return counts


def stats(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    result = {"n": int(len(values))}
    if not len(values):
        return {**result, **dict.fromkeys(("min", "median", "p90", "p95", "p99", "max"))}
    q = np.quantile(values, [0, .5, .9, .95, .99, 1])
    return {**result, **dict(zip(("min", "median", "p90", "p95", "p99", "max"),
                                map(float, q)))}


def pressure_summary(raw, groups, audit):
    """Descriptive distributions; no threshold or proposed feature is selected."""
    structural = ~audit[["raw_missing_timestamp", "raw_duplicate_timestamp",
                         "raw_off_grid_timestamp", "raw_process_mismatch",
                         "fixed_clock_ambiguity"]].any(axis=1).to_numpy()
    output = {}
    for name, mask in groups.items():
        summary = {}
        for c, channel in enumerate(CHANNELS):
            finite = np.isfinite(raw[:, :, c]).all(axis=1)
            eligible = mask & structural & finite
            values = raw[eligible, :, c]
            spread = np.ptp(values, axis=1)
            sd = np.std(values, axis=1, ddof=0)
            max_difference = np.max(np.abs(values[:, :5] - values[:, 5:6]), axis=1)
            end_vs_prior_mean = np.abs(values[:, 5] - values[:, :5].mean(axis=1))
            summary[channel] = {
                "group_minutes": int(mask.sum()), "usable_complete_raw_minutes": int(eligible.sum()),
                "excluded_structural_minutes": int((mask & ~structural).sum()),
                "excluded_nonfinite_among_structurally_valid": int((mask & structural & ~finite).sum()),
                "all_six_values_equal": int((spread == 0).sum()),
                "within_minute_range": stats(spread), "within_minute_std_population": stats(sd),
                "max_abs_earlier_minus_selected_50": stats(max_difference),
                "abs_selected_50_minus_earlier_mean": stats(end_vs_prior_mean),
            }
        output[name] = summary
    return output


def month_diagnosis(inputs, mask, starts, saved, saved_audit):
    adapted = adapt_waterhub(*inputs, timestamp_ambiguity_mask=mask,
                             grid_start=starts[0], grid_end=starts[-1])
    slots, reconstructed = slots_and_target(inputs.annotations, starts)
    labels = adapted.labels.to_numpy()
    np.testing.assert_array_equal(reconstructed, labels)
    # Compare the exact frozen on-disk target and feature/availability path.
    reference = saved.reindex(adapted.features.index)
    reference_audit = saved_audit.reindex(adapted.features.index)
    assert reference.index.equals(adapted.features.index)
    assert not reference.label.isna().any()
    np.testing.assert_array_equal(reference.label.to_numpy(), labels)
    np.testing.assert_array_equal(reference[list(CHANNELS)].to_numpy(), adapted.features.to_numpy())
    pd.testing.assert_frame_equal(reference_audit, adapted.audit, check_dtype=False, check_freq=False)
    groups = partition(slots, labels)
    features_available = adapted.audit.feature_available.to_numpy()
    counts = {"calendar_minutes": len(starts), "known_positive_minutes": int((labels == 1).sum())}
    for name, group in groups.items():
        counts[name] = int(group.sum())
        counts[name + "_feature_available"] = int((group & features_available).sum())
        counts[name + "_feature_unavailable"] = int((group & ~features_available).sum())
    pressure = raw_slots(inputs.raw_t1_t2, inputs.raw_gak, starts)
    flags = {column: int(adapted.audit[column].sum()) for column in adapted.audit
             if column != "known_annotation_slots"}
    by_group_flags = {name: {column: int(adapted.audit.loc[group, column].sum())
                            for column in adapted.audit if column != "known_annotation_slots"}
                      for name, group in groups.items()}
    return {"counts": counts, "positive_interval_counts": interval_summary(labels, groups),
            "audit_flag_counts_overlapping": flags,
            "audit_flags_by_label_partition_overlapping": by_group_flags,
            "exact_parity": {"independent_target_vs_current_adapter": True,
                             "current_adapter_vs_frozen_target": True,
                             "current_adapter_vs_frozen_features": True,
                             "current_adapter_vs_frozen_all_audit_columns": True},
            "pressure_distributions_raw_units": pressure_summary(pressure, groups, adapted.audit)}


def synthetic_self_test():
    """Seven fixtures exercise attribution and the independent target oracle."""
    from ml.gecco_v6.waterhub_loader import WaterHubInputs
    times = pd.date_range("2019-01-01", periods=12, freq="10s")
    starts = pd.date_range(times[0], periods=2, freq="min")
    a = pd.DataFrame({"p1": np.arange(12.), "p2": np.arange(12.)}, index=times)
    b = pd.DataFrame({"p3": np.arange(12.), "p4": np.arange(12.)}, index=times)
    def annotations():
        return {s: pd.DataFrame({"Anomaly": np.zeros(12)}, index=times) for s in LABEL_STREAMS}
    for case in range(7):
        ann = annotations(); raw_a = a.copy()
        ann["p1"].iloc[1, 0] = 1
        ann["p3p4"].iloc[11, 0] = 1
        expected = [1, 1]
        if case == 1:
            ann["p2"] = ann["p2"].drop(times[0]); expected = [-1, 1]
        elif case == 2:
            ann["p1"] = pd.concat([ann["p1"], pd.DataFrame({"Anomaly": [0]}, index=times[1:2])])
            expected = [-1, 1]
        elif case == 3:
            ann["p1"] = pd.concat([ann["p1"], ann["p1"].iloc[1:2]])
        elif case == 4:
            ann["p2"] = pd.concat([ann["p2"], pd.DataFrame({"Anomaly": [0]}, index=[times[0] + pd.Timedelta(seconds=1)])])
            expected = [-1, 1]
        elif case == 5:
            raw_a = raw_a.drop(times[0])
        elif case == 6:
            raw_a.iloc[0, 0] = np.nan
        result = adapt_waterhub(raw_a, b, ann, grid_start=starts[0], grid_end=starts[-1])
        slots, target = slots_and_target(ann, starts)
        np.testing.assert_array_equal(target, expected)
        np.testing.assert_array_equal(target, result.labels)
        groups = partition(slots, target)
        if expected[0] == 1:
            assert groups["known_positive_earlier_only"][0]
        assert groups["known_positive_at_50"][1]
        if case == 5:
            assert not result.audit.feature_available.iloc[0]
        if case == 6:
            assert result.audit.feature_available.iloc[0]
        oracle = month_diagnosis(WaterHubInputs(raw_a, b, ann), [], starts,
                                 pd.concat([result.features, result.labels], axis=1), result.audit)
        assert all(oracle["exact_parity"].values())
    return {"synthetic_fixtures_passed": 7}


def run():
    tests = synthetic_self_test()
    protocol = json.loads((PRIOR / "protocol.json").read_text())
    previous = json.loads((PRIOR / "source_adapter_audit.json").read_text())
    code_pins = {}
    for name in ("ml/gecco_v6/waterhub_loader.py", "ml/gecco_v6/waterhub_adapter.py"):
        code_pins[name] = sha(ROOT / name)
        assert code_pins[name] == protocol["code_sha256"][name], name
    saved = pd.read_csv(PRIOR / "adapted_source.csv.gz", index_col=0, parse_dates=[0], float_precision="round_trip")
    saved_audit = pd.read_csv(PRIOR / "availability_audit.csv.gz", index_col=0, parse_dates=[0])
    all_pins = {item["member"]: item["sha256"] for item in previous["loader"]["members"]}
    monthly = []
    members = []
    archive = ROOT / protocol["archive_path"]
    for month in MONTHS:
        pins = {item["member"]: all_pins[item["member"]] for item in waterhub_member_plan([month])}
        loaded = load_waterhub_archive(archive, months=[month], expected_member_sha256=pins)
        begin = pd.Timestamp(month + "-01")
        end = begin + pd.offsets.MonthBegin(1)
        starts = pd.date_range(begin, end, freq="min", inclusive="left").as_unit("ns")
        result = month_diagnosis(loaded.monthly[month], loaded.timestamp_ambiguity_mask,
                                 starts, saved, saved_audit)
        result["month"] = month
        monthly.append(result)
        members.extend(loaded.member_manifest)
        print(json.dumps({"month": month, "counts": result["counts"], "exact_parity": True}), flush=True)
        del loaded, starts
        gc.collect()
    keys = monthly[0]["counts"]
    totals = {key: sum(row["counts"][key] for row in monthly) for key in keys}
    fraction = totals["known_positive_earlier_only"] / totals["known_positive_minutes"]
    interval_totals = {key: sum(row["positive_interval_counts"][key] for row in monthly)
                       for key in monthly[0]["positive_interval_counts"]}
    output = {
        "status": "exploratory_post_test_diagnosis_on_consumed_source",
        "scope": list(MONTHS), "synthetic_verification": tests,
        "method": "Independently resolve all 36 annotation slots; partition known-positive minutes by :50 annotations; compare raw six-slot pressure distributions without fitting or threshold selection.",
        "totals": totals, "positive_interval_totals": interval_totals,
        "earlier_only_fraction_of_known_positive_minutes": fraction,
        "monthly": monthly, "member_manifest": members,
        "provenance": {"archive_path": str(archive.relative_to(ROOT)),
                       "archive_sha256_recorded_in_original_protocol": protocol["archive_sha256"],
                       "whole_archive_rehashed_in_this_diagnosis": False,
                       "selected_member_hashes_verified": True,
                       "frozen_loader_adapter_sha256": code_pins,
                       "script_sha256": sha(__file__),
                       "frozen_adapted_source_sha256": sha(PRIOR / "adapted_source.csv.gz"),
                       "frozen_availability_audit_sha256": sha(PRIOR / "availability_audit.csv.gz")},
        "limitations": [
            "No model fitting, threshold changes, alternative target evaluation, or source reopening beyond the consumed six WaterHub months.",
            "An earlier-only label identifies a label/representation timing mismatch, not proof that a physical anomaly was discarded or caused a model miss.",
            "Range and standard deviation are descriptive raw-pressure statistics in native units; differences do not establish detectability or chemical faults.",
            "Unknown labels remain unknown. Raw feature availability is independent from label knowledge. Audit flag counts may overlap.",
            "Within-minute distributions require all six finite raw readings per channel and no structural ambiguity. Missing earlier pressure values can coexist with an available selected :50 feature.",
            "Monthly duplicate masks reproduce the frozen complete-source availability exactly; valid member timestamps cannot cross their calendar month.",
            "UWO and all other unused sources remain unopened. These post-test observations are not new validation evidence.",
        ],
        "interpretation": {
            "narrow_timing_hypothesis": "The OR target is positive while every :50 annotation is normal in only the reported earlier-only fraction. This is a real but infrequent minute-label mismatch; it does not support that mismatch as the general explanation for low positive-minute coverage.",
            "interval_scope": "Intervals use the original minute target; a first-row or post-unknown positive interval is censored. Entirely earlier-only intervals distinguish complete short-interval omission from boundary-minute differences, without changing any frozen metric or model prediction.",
            "pressure_evidence": "Raw within-minute variation is present in both annotated and known-normal minutes. Its range and standard deviation are lost from a last-value-only representation, but these descriptive distributions alone neither prove that this information is useful nor show that it caused a missed event.",
            "counterfactual_not_tested": "No alternative aggregation, model, threshold, or annotation target was evaluated. Whether additional causal raw summaries help remains an untested development hypothesis.",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(OUT), "totals": totals, "earlier_only_fraction": fraction}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--self-test", action="store_true")
    action.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(synthetic_self_test()))
    else:
        run()
