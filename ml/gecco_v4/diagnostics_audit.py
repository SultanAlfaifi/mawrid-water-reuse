"""Post-hoc development diagnostics; never a fresh holdout/model evaluation.

Read frozen V2/V3 predictions and all now-exposed GECCO periods. Fit no model,
change no frozen artifact. Event signatures are descriptive sensor patterns,
not identified fault types. Distribution shifts are associations, not causes.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/ml/gecco-v4-diagnostics"
C18 = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
C19 = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def intervals(mask):
    changes = np.diff(np.r_[False, np.asarray(mask, bool), False].astype(int))
    return list(zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)))


def complete(mask, window):
    return pd.Series(mask).rolling(window, min_periods=window).sum().eq(window).to_numpy()


def finite(value):
    if isinstance(value, dict):
        return {str(k): finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def quantiles(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return dict(zip(["p01", "p25", "p50", "p75", "p95", "p99"],
                    np.quantile(x, [.01, .25, .5, .75, .95, .99]))) if len(x) else {}


def component_parts(frame, channels):
    x = frame[channels].astype(float).replace([np.inf, -np.inf], np.nan)
    prior = x.shift(1)
    center = prior.rolling(30, min_periods=30).median()
    residual = x - center
    mad = residual.abs().shift(1).rolling(30, min_periods=30).median() * 1.4826
    return x, residual, mad, x.diff(), prior.rolling(5, min_periods=5).mean() - center


def normal_training_floors(train, channels):
    x, residual, _, delta, _ = component_parts(train, channels)
    clean = complete(x.notna().all(axis=1).to_numpy() & ~train.EVENT.to_numpy(bool), 61)
    floors, dfloors = [], []
    for ch in channels:
        vals, steps = x.loc[clean, ch].to_numpy(), delta.loc[clean, ch].abs().to_numpy()
        positive = steps[steps > 0]
        quantum = np.quantile(positive, .75) if len(positive) else 0.
        span = np.quantile(vals, .75) - np.quantile(vals, .25)
        eps = max(np.median(np.abs(vals)) * 1e-9, 1e-9)
        floors.append(max(quantum, span * .01, np.median(residual.loc[clean, ch].abs()) * 1.4826 * .05, eps))
        dfloors.append(max(quantum, span * .005, eps))
    return np.asarray(floors), np.asarray(dfloors)


def normalized_features(part, channels, floors, dfloors):
    x, residual, mad, delta, change = component_parts(part, channels)
    scale = np.maximum(mad.to_numpy(), floors)
    f = np.clip(np.concatenate([residual.to_numpy()/scale, delta.to_numpy()/dfloors,
                               change.to_numpy()/scale], axis=1), -1e6, 1e6)
    eligible = complete(x.notna().all(axis=1).to_numpy(), 61) & np.isfinite(f).all(axis=1)
    f[~eligible] = np.nan
    names = [ch + "." + kind for kind in ["residual", "delta", "mean_change"] for ch in channels]
    return pd.DataFrame(f, columns=names), eligible


def read_frame(path):
    return pd.read_csv(path).rename(columns={"Event": "EVENT"}).reset_index(drop=True)


def distribution_rows(name, kind, train, cal, test, ty, cy, ey):
    rows = []
    for ch in train.columns:
        a = train.loc[~ty, ch].to_numpy(float)
        b = cal.loc[~cy, ch].to_numpy(float)
        c = test.loc[~ey, ch].to_numpy(float)
        qa, qb, qc = quantiles(a), quantiles(b), quantiles(c)
        if not qa or not qb or not qc:
            continue
        iqr = qa["p75"] - qa["p25"]
        bc, cc = b[np.isfinite(b)], c[np.isfinite(c)]
        rows.append({"partition": name, "kind": kind, "feature": ch,
                     "training_normal_iqr": iqr,
                     "train_median": qa["p50"], "calibration_median": qb["p50"], "test_median": qc["p50"],
                     "cal_to_test_median_shift_training_iqr": (qc["p50"] - qb["p50"])/iqr if iqr > 0 else None,
                     "calibration_outside_train_p01_p99": np.mean((bc < qa["p01"]) | (bc > qa["p99"])),
                     "test_outside_train_p01_p99": np.mean((cc < qa["p01"]) | (cc > qa["p99"])),
                     "test_outside_calibration_p01_p99": np.mean((cc < qb["p01"]) | (cc > qb["p99"])),
                     "calibration_p95_abs": np.quantile(np.abs(bc), .95),
                     "test_p95_abs": np.quantile(np.abs(cc), .95)})
    return rows


def availability(name, split, part, channels, gap):
    y = part.EVENT.to_numpy(bool)
    present = np.isfinite(part[channels].to_numpy(float))
    current = present.all(axis=1)
    records = []
    for ch_index, ch in enumerate(channels):
        records.append({"partition": name, "split": split, "channel": ch,
                        "missing_rows": (~present[:, ch_index]).sum(),
                        "missing_event_rows": ((~present[:, ch_index]) & y).sum(),
                        "rows": len(part)})
    summary = {"rows": len(part), "raw_incomplete_rows": (~current).sum(),
               "raw_incomplete_event_rows": ((~current) & y).sum(),
               "total_event_minutes": y.sum(), "missing_runs": len(intervals(~current))}
    for width in [1, 15, 61]:
        mask = np.r_[np.zeros(gap, bool), complete(current[gap:], width)]
        gap_mask = np.arange(len(part)) < gap
        warmup_mask = (np.arange(len(part)) >= gap) & (np.arange(len(part)) < gap+width-1)
        raw_missing_mask = ~current & ~gap_mask & ~warmup_mask
        history_missing_mask = ~mask & ~gap_mask & ~warmup_mask & ~raw_missing_mask
        assert np.array_equal(~mask, gap_mask | warmup_mask | raw_missing_mask | history_missing_mask)
        summary[f"complete_{width}_coverage"] = mask.mean()
        summary[f"complete_{width}_unavailable_rows"] = (~mask).sum()
        summary[f"complete_{width}_unavailable_event_minutes"] = ((~mask) & y).sum()
        summary[f"complete_{width}_fully_unscorable_events"] = sum(not mask[a:b].any() for a, b in intervals(y))
        summary[f"complete_{width}_unavailable_reasons"] = {
            reason: {"rows": m.sum(), "event_minutes": (m & y).sum()}
            for reason, m in [("protocol_gap", gap_mask), ("initial_history_warmup", warmup_mask),
                              ("raw_missing_after_warmup", raw_missing_mask), ("propagated_history_missing", history_missing_mask)]}
    return summary, records


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    watched = []
    for version in ["gecco-baseline-v1", "gecco-v2", "gecco-v3"]:
        watched.extend(p for p in (ROOT / "output/ml" / version).rglob("*") if p.is_file())
    for version in ["gecco_baseline", "gecco_v2", "gecco_v3"]:
        watched.extend((ROOT / "ml" / version).glob("*.py"))
    hashes_before = {str(p.relative_to(ROOT)): sha(p) for p in watched}
    d18 = read_frame(ROOT / "data/external/gecco2018/1_gecco2018_water_quality.csv")
    base19 = ROOT / "data/external/gecco2019"
    d19 = {"train": read_frame(base19 / "7_gecco2019_train_water_quality.csv"),
           "cal": read_frame(base19 / "8_gecco2019_valid_water_qulity.csv"),
           "test": read_frame(base19 / "6_gecco2019_test_water_quality.csv")}
    summaries, shifts, events, candidates, missing = [], [], [], [], []
    overview = {}
    for name in [f"fold_{i}" for i in range(1, 7)] + ["external_2019"]:
        folder = ROOT / "output/ml/gecco-v3" / name
        freeze = json.loads((folder / "freeze.json").read_text())
        if name.startswith("fold"):
            m = freeze["metadata"]
            tr, ca, te = [d18.iloc[slice(*m[k])].reset_index(drop=True) for k in ["train", "calibration", "test"]]
            channels = C18
            start = m["test"][0]
        else:
            tr, ca, te = d19["train"], d19["cal"].iloc[120:].reset_index(drop=True), d19["test"]
            channels, start = C19, 0
        ytr, yca, yte = [d.EVENT.to_numpy(bool) for d in [tr, ca, te]]
        floors, dfloors = normal_training_floors(tr, channels)
        ftr, _ = normalized_features(tr, channels, floors, dfloors)
        fca, _ = normalized_features(ca, channels, floors, dfloors)
        fte, _ = normalized_features(te.iloc[120:].reset_index(drop=True), channels, floors, dfloors)
        fte = pd.concat([pd.DataFrame(np.nan, index=range(120), columns=fte.columns), fte], ignore_index=True)
        shifts += distribution_rows(name, "raw", tr[channels], ca[channels], te[channels], ytr, yca, yte)
        shifts += distribution_rows(name, "normalized", ftr, fca, fte, ytr, yca, yte)
        ava = {}
        for split, frame, gap in [("train", tr, 0), ("calibration", ca, 0), ("test", te, 120)]:
            ava[split], rows = availability(name, split, frame, channels, gap)
            missing.extend(rows)
        pred = pd.read_csv(folder / "test_predictions.csv.gz", float_precision="round_trip")
        assert len(pred) == len(te) and np.array_equal(pred.EVENT.to_numpy(bool), yte)
        result = json.loads((folder / "test_results.json").read_text())
        calpred = pd.read_csv(folder / "v3_calibration_predictions.csv.gz", float_precision="round_trip")
        selected = freeze["selected"]
        v3metrics = result["native"]["v3"]
        trials_total = 0
        for c in freeze["selection_candidates"]:
            trials = pd.read_csv(folder / f"{c['family']}_calibration_trials.csv.gz")
            trials_total += len(trials) if c["family"] != "baseline" else 0
            feasible = trials[trials.feasible]
            same_recall = feasible[feasible.confirmed_new_alarm_inside_events.eq(c["confirmed_new_alarm_inside_events"])]
            candidates.append({"partition": name, "family": c["family"], "selected": c["family"] == selected["family"],
                               "calibration_events": c["true_events"], "detected_calibration_events": c["confirmed_new_alarm_inside_events"],
                               "calibration_f1": c["f1"], "calibration_false_runs_per_day": c["false_alarm_runs_per_normal_day"],
                               "calibration_alarm_fraction": c["normal_time_under_alarm"], "policy": c["policy"],
                               "threshold": c["threshold"], "trial_count": len(trials), "feasible_count": len(feasible),
                               "feasible_same_event_count": len(same_recall)})
        row = {"partition": name, "selected_family": selected["family"], "policy": selected["policy"],
               "threshold": selected["threshold"], "calibration_events": selected["true_events"],
               "calibration_event_minutes": freeze["calibration_event_minutes"],
               "calibration_confirmed_events": selected["confirmed_new_alarm_inside_events"],
               "calibration_false_runs_per_normal_day": selected["false_alarm_runs_per_normal_day"],
               "candidate_operating_points_checked": trials_total,
               "test_events": v3metrics["true_events"], "test_confirmed_events": v3metrics["confirmed_new_alarm_inside_events"],
               "test_false_runs_per_normal_day": v3metrics["false_alarm_runs_per_normal_day"],
               "test_normal_alarm_fraction": v3metrics["normal_time_under_alarm"], "test_f1": v3metrics["f1"],
               "test_native_coverage": v3metrics["prediction_coverage"],
               "test_fully_unscorable_events": v3metrics["fully_unscorable_events"],
               "test_positive_coverage": v3metrics["positive_valid_count"] / yte.sum() if yte.any() else None}
        for version in ["v2", "v3"]:
            r = json.loads((ROOT / f"output/ml/gecco-{version}" / name / "test_results.json").read_text())
            for role in (["baseline", version] if version == "v3" else [version]):
                rr = r["native"][role]
                for key in ["confirmed_new_alarm_inside_events", "false_alarm_runs_per_normal_day", "normal_time_under_alarm", "f1", "prediction_coverage"]:
                    row[f"{role}_{key}"] = rr[key]
        for split, frame, yy, scorecol in [("calibration", calpred, yca, "score"), ("test", pred, yte, "v3_score")]:
            sc = frame.loc[~yy, scorecol].to_numpy(float)
            sc = sc[np.isfinite(sc)]
            for key, val in quantiles(sc).items():
                row[f"normal_score_{split}_{key}"] = val
            row[f"normal_score_{split}_fraction_above_threshold"] = (sc >= selected["threshold"]).mean()
        summaries.append(row)
        shape_summary = {}
        records = v3metrics["event_records"]
        for (a, b), rec in zip(intervals(yte), records):
            assert a == rec["start"] and b == rec["end"]
            raw_before = te[channels].iloc[max(0, a-30):a].median().to_numpy()
            # Shape only: local pre-event center and training normal noise floor.
            deviation = np.abs(te[channels].iloc[a:b].to_numpy(float)-raw_before) / floors
            strength = np.array([np.nanmax(deviation[:,j]) if np.isfinite(deviation[:,j]).any() else np.nan for j in range(len(channels))])
            order = np.argsort(np.nan_to_num(strength, nan=-np.inf))[::-1]
            dominant = channels[order[0]] if np.isfinite(strength).any() else None
            # Training-relative absolute-level novelty, descriptive and not used to select a model.
            normaltrain = tr.loc[~ytr, channels]
            lo, hi = normaltrain.quantile(.01).to_numpy(), normaltrain.quantile(.99).to_numpy()
            rawvalues = te[channels].iloc[a:b].to_numpy(float)
            excursions = ((rawvalues < lo) | (rawvalues > hi)) & np.isfinite(rawvalues)
            events.append({"partition": name, "source_start_index": start+a, "source_end_index": start+b,
                           "duration_minutes": b-a, "confirmed_detected": rec["confirmed_new_alarm_inside_event"],
                           "any_alarm": rec["detected"], "available_minutes": rec["valid_count"],
                           "fully_unscorable": rec["fully_unscorable"], "delay_minutes": rec["confirmed_new_alarm_delay_minutes"],
                           "dominant_local_deviation_channel": dominant,
                           "dominant_local_deviation_training_floor_units": np.nanmax(strength) if np.isfinite(strength).any() else None,
                           "second_local_deviation_channel": channels[order[1]] if len(channels)>1 and np.isfinite(strength[order[1]]) else None,
                           "fraction_minutes_any_channel_outside_training_p01_p99": excursions.any(axis=1).mean(),
                           "pre_event_30_rows_include_event": bool(yte[max(0,a-30):a].any()),
                           "boundary_censored": rec["boundary_censored"]})
        part_events = [r for r in events if r["partition"] == name]
        for flag in [True, False]:
            er = [r for r in part_events if r["confirmed_detected"] == flag]
            shape_summary["confirmed" if flag else "not_confirmed"] = {
                "count": len(er), "durations": [r["duration_minutes"] for r in er],
                "dominant_channels": dict(Counter(r["dominant_local_deviation_channel"] for r in er)),
                "fully_unscorable": sum(r["fully_unscorable"] for r in er)}
        overview[name] = {"availability": ava, "event_signatures": shape_summary}
    for filename, rows in [("partition_summary.csv", summaries), ("distribution_shift.csv", shifts),
                           ("event_signatures.csv", events), ("calibration_candidates.csv", candidates),
                           ("channel_missingness.csv", missing)]:
        pd.DataFrame(rows).to_csv(OUT / filename, index=False)
    changed = [p for p, digest in hashes_before.items() if sha(ROOT / p) != digest]
    assert not changed, changed
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "scope": "POST-HOC DEVELOPMENT DIAGNOSTICS ONLY; 2018 and all 2019 labels already exposed",
              "no_models_fitted_or_tuned": True, "frozen_files_unchanged": len(hashes_before),
              "script_sha256": sha(__file__), "partitions": overview,
              "interpretation_limits": ["Binary labels do not identify physical fault types; dominant channels describe observable event shape only.",
                 "Feature shifts use normal labels retrospectively for diagnosis, never as a deployable feature or test selection criterion.",
                 "Different schemas and retraining mean 2019 is not zero-shot checkpoint transfer or independent site proof.",
                 "Each fold's metrics are not summed event counts; event spanning a boundary can appear in two per-fold shape records. Existing global audit provides the deduplicated 37-event denominator.",
                 "Association between drift and errors does not prove causation; low calibration counts also constrain estimation."]}
    (OUT / "diagnosis.json").write_text(json.dumps(finite(report), ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"output": str(OUT), "frozen_files_unchanged": len(hashes_before), "partitions": summaries}, default=finite))


if __name__ == "__main__":
    main()
