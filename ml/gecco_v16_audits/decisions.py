"""Independent scalar V16 context and weight oracles; no production imports/IO.

Only NumPy is imported. Events, request ownership and class masses are derived
by walking original rows and explicit request records. This audit module never
fits a model, reads a dataset, tunes a policy or imports a V16 production module.
"""
from __future__ import annotations

import numpy as np


CONTEXT_NAMES = (
    "v6_alarm", "v8_alarm", "v6_known", "v8_known",
    "anchor_opportunity", "anchor_age_fraction",
    "recovery_opportunity", "recovery_age_fraction",
)
KINDS = ("anchor", "recovery")


def _ints(values, name, n=None, ternary=False, allow_bool=False):
    a = np.asarray(values)
    if a.ndim != 1 or a.dtype.kind not in ("biu" if allow_bool else "iu"):
        raise ValueError(name + " must be a one-dimensional integer array")
    if n is not None and len(a) != n:
        raise ValueError(name + " length mismatch")
    if a.dtype.kind == "u" and any(int(x) > np.iinfo(np.int64).max for x in a):
        raise ValueError(name + " exceeds int64")
    if ternary and any(int(x) not in (-1, 0, 1) for x in a):
        raise ValueError(name + " must contain -1/0/1")
    return a.astype(np.int64, copy=False)


def _request_rows(origins, kind):
    groups = {}
    for row, value in enumerate(origins):
        origin = int(value)
        if origin >= 0:
            groups.setdefault(origin, []).append(row)
    return [{"type": kind, "origin": origin, "rows": rows}
            for origin, rows in sorted(groups.items())]


def context_oracle(v6, v8):
    """Independent current/past scalar state machine on the supplied axis."""
    first = _ints(v6, "v6", ternary=True)
    second = _ints(v8, "v8", len(first), ternary=True)
    n = len(first)
    matrix = np.zeros((n, 8), np.float32)
    anchor_origins = np.full(n, -1, np.int64)
    recovery_origins = np.full(n, -1, np.int64)
    anchor_origin = recovery_origin = None
    previous6 = previous8 = None
    for i in range(n):
        a, b = int(first[i]), int(second[i])
        # A censored V8=1 cannot create a request; its known start is required.
        if b != 1:
            anchor_origin = None
        elif previous8 == 0:
            anchor_origin = i
        anchor_active = anchor_origin is not None and i - anchor_origin <= 2
        if anchor_active:
            anchor_origins[i] = anchor_origin

        # Cancellation precedes a current hit/request: no transfer from the old
        # pulse when a new V6 pulse starts, even if the new pulse is ineligible.
        if a < 0 or b < 0:
            recovery_origin = None
        known_start6 = a == 1 and previous6 == 0
        if known_start6:
            recovery_origin = i if b == 0 else None
        if recovery_origin is not None and i - recovery_origin > 2:
            recovery_origin = None
        recovery_active = recovery_origin is not None
        if recovery_active:
            recovery_origins[i] = recovery_origin

        matrix[i] = (a == 1, b == 1, a >= 0, b >= 0,
                     anchor_active, (i - anchor_origin) / 2 if anchor_active else 0,
                     recovery_active, (i - recovery_origin) / 2 if recovery_active else 0)
        previous6, previous8 = a, b
    anchor_active, recovery_active = anchor_origins >= 0, recovery_origins >= 0
    active = anchor_active | recovery_active
    opportunities = _request_rows(anchor_origins, "anchor") + _request_rows(recovery_origins, "recovery")
    opportunities.sort(key=lambda item: (item["origin"], item["type"]))
    return {"matrix": matrix, "active": active, "eligible": active.copy(),
            "anchor_active": anchor_active, "recovery_active": recovery_active,
            "anchor_origins": anchor_origins, "recovery_origins": recovery_origins,
            "opportunities": opportunities, "feature_names": list(CONTEXT_NAMES)}


def _validated_origins(values, name, n, folds):
    a = _ints(values, name, n)
    for i, value in enumerate(a):
        start = int(value)
        if start < -1 or start > i:
            raise ValueError(name + " has an invalid/future origin")
        if start >= 0:
            if i - start > 2 or int(folds[i]) < 0 or int(folds[i]) != int(folds[start]):
                raise ValueError(name + " crosses a deadline or forecast fold")
    for group in _request_rows(a, name):
        expected = list(range(group["origin"], group["rows"][-1] + 1))
        if group["rows"] != expected:
            raise ValueError(name + " shifts/restarts an original request")
    return a


def weight_oracle(y, available, fold_ids, anchor_origins, recovery_origins):
    """Reconstruct original segments and hierarchical masses with scalar loops.

    Overlap contributes additive mass to one original row, not duplicate fitting
    examples. Unknown labels retain their row but never enter supervised mass.
    All positive segments, including censored and unsupported ones, retain IDs.
    """
    labels = _ints(y, "labels", ternary=True, allow_bool=True)
    n = len(labels)
    observed = np.asarray(available)
    if observed.shape != (n,) or observed.dtype.kind != "b":
        raise ValueError("available must be a same-length Boolean array")
    folds = _ints(fold_ids, "fold_ids", n)
    if any(int(f) < -1 for f in folds):
        raise ValueError("fold ids must be -1 or nonnegative")
    origins = {
        "anchor": _validated_origins(anchor_origins, "anchor_origins", n, folds),
        "recovery": _validated_origins(recovery_origins, "recovery_origins", n, folds),
    }
    active = np.zeros(n, bool)
    eligible = np.zeros(n, bool)
    normal = np.zeros(n, bool)
    positive = np.zeros(n, bool)
    for i in range(n):
        active[i] = origins["anchor"][i] >= 0 or origins["recovery"][i] >= 0
        eligible[i] = bool(observed[i] and active[i] and folds[i] >= 0 and labels[i] >= 0)
        normal[i] = bool(eligible[i] and labels[i] == 0)
        positive[i] = bool(eligible[i] and labels[i] == 1)

    event_ids = np.zeros(n, np.int64)
    event_records = []
    i = 0
    while i < n:
        if labels[i] != 1:
            i += 1
            continue
        start = i
        while i < n and labels[i] == 1:
            i += 1
        end = i
        event_id = len(event_records) + 1
        rows = []
        for row in range(start, end):
            event_ids[row] = event_id
            if positive[row]:
                rows.append(row)
        event_records.append({"event_id": event_id, "start": start, "end_exclusive": end,
            "known_onset": bool(start > 0 and labels[start - 1] == 0),
            "eligible_rows": rows, "fold_ids": sorted({int(folds[r]) for r in rows}),
            "opportunity_intersections": 0, "normalized_weight_mass": 0.0})

    records = []
    for kind in KINDS:
        records.extend(_request_rows(origins[kind], kind))
    records.sort(key=lambda record: (record["origin"], record["type"]))
    intersections = {}
    for record in records:
        kept, negatives, positives, grouped_positive = [], [], [], {}
        for row in record["rows"]:
            if eligible[row]:
                kept.append(row)
            if normal[row]:
                negatives.append(row)
            if positive[row]:
                positives.append(row)
                grouped_positive.setdefault(int(event_ids[row]), []).append(row)
        record.update(fold_id=int(folds[record["origin"]]), eligible_rows=kept,
            normal_rows=negatives, positive_rows=positives, positive_intersections=[],
            normal_weight_mass=0.0, normal_weight_per_row=0.0, normalized_weight_mass=0.0)
        for event_id in sorted(grouped_positive):
            part = {"event_id": event_id, "rows": grouped_positive[event_id],
                    "normalized_weight_mass": 0.0, "normalized_weight_per_row": 0.0}
            record["positive_intersections"].append(part)
            intersections.setdefault(event_id, []).append((record, part))

    normalized = np.zeros(n, np.float64)
    normal_records = [record for record in records if record["normal_rows"]]
    for record in normal_records:
        mass = .5 / len(normal_records)
        per_row = mass / len(record["normal_rows"])
        for row in record["normal_rows"]:
            normalized[row] += per_row
        record["normal_weight_mass"] = mass
        record["normal_weight_per_row"] = per_row
        record["normalized_weight_mass"] += mass
    for event_id, parts in intersections.items():
        event_mass = .5 / len(intersections)
        event_records[event_id - 1]["opportunity_intersections"] = len(parts)
        event_records[event_id - 1]["normalized_weight_mass"] = event_mass
        for record, part in parts:
            mass = event_mass / len(parts)
            per_row = mass / len(part["rows"])
            for row in part["rows"]:
                normalized[row] += per_row
            part["normalized_weight_mass"] = mass
            part["normalized_weight_per_row"] = per_row
            record["normalized_weight_mass"] += mass

    positive_folds = sorted({int(folds[i]) for i in range(n) if positive[i]})
    normal_count = sum(bool(v) for v in normal)
    fit_checks = {"at_least_128_normal_rows": normal_count >= 128,
        "at_least_two_positive_segments": len(intersections) >= 2,
        "positive_examples_in_two_forecast_folds": len(positive_folds) >= 2}
    request_support, per_offset = {}, {}
    for kind in KINDS:
        subset = [r for r in records if r["type"] == kind]
        event_set = sorted({p["event_id"] for r in subset for p in r["positive_intersections"]})
        normal_opportunities = sum(bool(r["normal_rows"]) for r in subset)
        normal_rows = [i for i in range(n) if normal[i] and origins[kind][i] >= 0]
        positive_rows = [i for i in range(n) if positive[i] and origins[kind][i] >= 0]
        request_support[kind] = {"supported": bool(normal_opportunities and event_set),
            "opportunities": len(subset), "normal_opportunities": normal_opportunities,
            "positive_opportunities": sum(bool(r["positive_rows"]) for r in subset),
            "positive_events": len(event_set), "positive_event_ids": event_set,
            "normal_rows": len(normal_rows), "positive_rows": len(positive_rows),
            "positive_folds": sorted({int(folds[i]) for i in positive_rows})}
        per_offset[kind] = []
        for offset in range(3):
            rows = [i for i in range(n) if origins[kind][i] >= 0 and i - int(origins[kind][i]) == offset]
            per_offset[kind].append({"offset": offset, "opportunity_rows": len(rows),
                "eligible_rows": sum(bool(eligible[i]) for i in rows),
                "normal_rows": sum(bool(normal[i]) for i in rows),
                "positive_rows": sum(bool(positive[i]) for i in rows),
                "unknown_label_rows": int(sum(labels[i] < 0 for i in rows)),
                "base_unavailable_rows": sum(not observed[i] for i in rows),
                "positive_event_ids": sorted({int(event_ids[i]) for i in rows if positive[i]})})
    per_fold = []
    for fold in sorted({int(f) for f in folds if f >= 0}):
        rows = [i for i in range(n) if folds[i] == fold]
        per_fold.append({"fold_id": fold, "rows": len(rows),
            "opportunity_rows": sum(bool(active[i]) for i in rows),
            "eligible_rows": sum(bool(eligible[i]) for i in rows),
            "normal_rows": sum(bool(normal[i]) for i in rows),
            "positive_rows": sum(bool(positive[i]) for i in rows),
            "positive_event_ids": sorted({int(event_ids[i]) for i in rows if positive[i]}),
            "normal_weight_mass": float(sum(normalized[i] for i in rows if labels[i] == 0)),
            "positive_weight_mass": float(sum(normalized[i] for i in rows if labels[i] == 1)),
            "opportunities_by_type": {kind: sum(r["type"] == kind and r["fold_id"] == fold for r in records)
                                      for kind in KINDS}})
    summary = {"training_rows": n, "opportunity_rows": int(active.sum()), "opportunities": len(records),
        "eligible_rows": int(eligible.sum()), "normal_rows": normal_count, "positive_rows": int(positive.sum()),
        "original_positive_segments": len(event_records), "positive_events": len(intersections),
        "positive_event_ids": sorted(intersections), "positive_folds": positive_folds,
        "positive_fold_count": len(positive_folds), "request_support": request_support,
        "per_fold": per_fold, "per_offset": per_offset, "fit_checks": fit_checks,
        "fit_supported": all(fit_checks.values()),
        "normal_weight_mass": float(sum(normalized[i] for i in range(n) if labels[i] == 0)),
        "positive_weight_mass": float(sum(normalized[i] for i in range(n) if labels[i] == 1)),
        "unknown_weight_mass": float(sum(normalized[i] for i in range(n) if labels[i] < 0)),
        "normalized_weight_sum": float(sum(normalized)), "sample_weight_scale": int(eligible.sum()),
        "weight_contract": "normal0.5 opportunity->row; positive0.5 originalsegment->opportunityintersection->row; overlap contributions summed on unique rows; absent class mass not redistributed"}
    return {"normalized": normalized, "sample": normalized * int(eligible.sum()),
            "eligible": eligible, "event_ids": event_ids, "summary": summary,
            "records": records, "event_records": event_records}
