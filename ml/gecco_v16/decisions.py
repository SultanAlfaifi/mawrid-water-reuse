"""V16's causal decision contexts and original-axis supervised weights.

No estimator, source I/O, threshold, or label is used by ``contexts``. The
contexts describe potential requests before a confidence threshold is chosen;
they do not depend on whether a fitted policy has already released a request.
``weights`` alone reads labels, on the full original training axis. It never
moves an opportunity, joins positive segments across unknown labels, or
duplicates a feature row. The protocol is fixed at a 60-second sample cadence.
"""
from __future__ import annotations

import numpy as np


CONTEXT_NAMES = (
    "v6_alarm", "v8_alarm", "v6_known", "v8_known",
    "anchor_opportunity", "anchor_age_fraction",
    "recovery_opportunity", "recovery_age_fraction",
)
DEADLINE_SAMPLES = 2
MIN_NORMAL_ROWS = 128
MIN_POSITIVE_EVENTS = 2
MIN_POSITIVE_FOLDS = 2
REQUEST_TYPES = ("anchor", "recovery")


def _integers(values, name, length=None, *, ternary=False, boolean=False):
    array = np.asarray(values)
    kinds = "biu" if boolean else "iu"
    if array.ndim != 1 or array.dtype.kind not in kinds:
        raise ValueError(f"{name} must be a one-dimensional integer array")
    if length is not None and len(array) != length:
        raise ValueError(f"{name} must have the same length as labels/references")
    if ternary and not np.isin(array, (-1, 0, 1)).all():
        raise ValueError(f"{name} must contain only -1, 0 and 1")
    if array.dtype.kind == "u" and np.any(array > np.iinfo(np.int64).max):
        raise ValueError(f"{name} cannot exceed int64")
    return array.astype(np.int64, copy=False)


def _opportunities(origins, kind):
    """Rows for each request, in original origin order; no availability filter."""
    positions = np.flatnonzero(origins >= 0)
    if not len(positions):
        return []
    # Each request's rows are contiguous and have at most three entries.
    splits = np.r_[0, np.flatnonzero(np.diff(origins[positions]) != 0) + 1, len(positions)]
    return [{"type": kind, "origin": int(origins[positions[a]]),
             "rows": positions[a:b].tolist()} for a, b in zip(splits[:-1], splits[1:])]


def contexts(v6, v8):
    """Return fixed float32[n,8] contexts plus causal request ownership.

    Anchor: known V8 0->1 only, and ages 0/1/2 while the same pulse remains 1.
    Recovery: known V6 0->1 with V8==0, ages 0/1/2 even after V6 clears.
    Either reference becoming unknown or ANY new known V6 start cancels the
    old recovery request before the current row can belong to it. A new
    eligible start owns a fresh request. Starts at series/unknown boundaries
    are censored and do not create opportunities. Ages never restart midway.

    ``eligible`` is an alias in meaning, not storage, for ``active``. Both
    describe opportunity membership only; feature availability is separate.
    Returned opportunity rows describe only the supplied prefix, not a future
    pulse end. Appending future rows cannot alter any earlier context or owner.
    """
    first = _integers(v6, "v6", ternary=True)
    anchor = _integers(v8, "v8", len(first), ternary=True)
    n = len(first)
    index = np.arange(n, dtype=np.int64)
    anchor_origins = np.full(n, -1, dtype=np.int64)
    recovery_origins = np.full(n, -1, dtype=np.int64)
    if n:
        v8_start = (anchor == 1) & np.r_[False, anchor[:-1] == 0]
        last_v8_start = np.maximum.accumulate(np.where(v8_start, index, -1))
        last_v8_clear = np.maximum.accumulate(np.where(anchor != 1, index, -1))
        age = index - last_v8_start
        active_anchor = ((last_v8_start >= 0) & (last_v8_start > last_v8_clear)
                         & (age <= DEADLINE_SAMPLES))
        anchor_origins[active_anchor] = last_v8_start[active_anchor]

        v6_start = (first == 1) & np.r_[False, first[:-1] == 0]
        eligible_start = v6_start & (anchor == 0)
        last_v6_start = np.maximum.accumulate(np.where(v6_start, index, -1))
        last_request = np.maximum.accumulate(np.where(eligible_start, index, -1))
        last_unknown = np.maximum.accumulate(np.where((first < 0) | (anchor < 0), index, -1))
        active_recovery = ((last_request >= 0) & (last_request == last_v6_start)
                           & (last_request > last_unknown)
                           & (index - last_request <= DEADLINE_SAMPLES))
        recovery_origins[active_recovery] = last_request[active_recovery]

    anchor_active = anchor_origins >= 0
    recovery_active = recovery_origins >= 0
    active = anchor_active | recovery_active
    matrix = np.zeros((n, len(CONTEXT_NAMES)), dtype=np.float32)
    matrix[:, 0] = first == 1
    matrix[:, 1] = anchor == 1
    matrix[:, 2] = first >= 0
    matrix[:, 3] = anchor >= 0
    matrix[:, 4] = anchor_active
    matrix[anchor_active, 5] = (index[anchor_active] - anchor_origins[anchor_active]) / DEADLINE_SAMPLES
    matrix[:, 6] = recovery_active
    matrix[recovery_active, 7] = (index[recovery_active] - recovery_origins[recovery_active]) / DEADLINE_SAMPLES
    opportunities = _opportunities(anchor_origins, "anchor") + _opportunities(recovery_origins, "recovery")
    opportunities.sort(key=lambda item: (item["origin"], item["type"]))
    return {"matrix": matrix, "active": active, "eligible": active.copy(),
            "anchor_active": anchor_active, "recovery_active": recovery_active,
            "anchor_origins": anchor_origins, "recovery_origins": recovery_origins,
            "opportunities": opportunities, "feature_names": list(CONTEXT_NAMES)}


def _validate_origins(values, name, n, folds):
    origins = _integers(values, name, n)
    index = np.arange(n, dtype=np.int64)
    if np.any(origins < -1) or np.any(origins > index):
        raise ValueError(f"{name} contains an invalid/future origin")
    active = origins >= 0
    if np.any(index[active] - origins[active] > DEADLINE_SAMPLES):
        raise ValueError(f"{name} exceeds the original two-sample deadline")
    if np.any(folds[active] < 0):
        raise ValueError(f"{name} cannot create opportunities outside forecast folds")
    if np.any(folds[active] != folds[origins[active]]):
        raise ValueError(f"{name} cannot cross teacher forecast folds")
    for item in _opportunities(origins, name):
        rows, origin = item["rows"], item["origin"]
        if rows != list(range(origin, rows[-1] + 1)):
            raise ValueError(f"{name} must start at its origin and cannot restart after cancellation")
    return origins


def weights(labels, available, fold_ids, anchor_origins, recovery_origins):
    """Build weights on the full ORIGINAL training axis, never a compressed set.

    Parameters are equally sized arrays. ``fold_ids==-1`` identifies rows not
    forecast by an inner teacher. Other fold IDs are caller-owned nonnegative
    integers. Origin arrays are already offset onto this full axis. ``available``
    must be the Boolean availability of the base feature generator.

    Each present class receives its prescribed mass 0.5. If a class is absent,
    its mass is not redistributed; the head is explicitly unsupported. Even
    when training minima fail, descriptive weights/records remain inspectable.
    ``sample`` is normalized weight times unique eligible known-label rows.
    Positive event IDs identify all original contiguous y==1 segments, including
    censored segments and those without eligible examples. Zero means nonpositive.
    """
    y = _integers(labels, "labels", ternary=True, boolean=True)
    n = len(y)
    observed = np.asarray(available)
    if observed.shape != (n,) or observed.dtype.kind != "b":
        raise ValueError("available must be a same-length Boolean array")
    folds = _integers(fold_ids, "fold_ids", n)
    if np.any(folds < -1):
        raise ValueError("fold_ids must be -1 or a nonnegative forecast fold")
    origins = {
        "anchor": _validate_origins(anchor_origins, "anchor_origins", n, folds),
        "recovery": _validate_origins(recovery_origins, "recovery_origins", n, folds),
    }
    active = (origins["anchor"] >= 0) | (origins["recovery"] >= 0)
    eligible = observed & active & (folds >= 0) & (y >= 0)
    normal, positive = eligible & (y == 0), eligible & (y == 1)
    edge = np.diff(np.r_[False, y == 1, False].astype(np.int8))
    starts, ends = np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)
    event_ids = np.zeros(n, dtype=np.int64)
    event_records = []
    for event_id, (start, end) in enumerate(zip(starts, ends), 1):
        event_ids[start:end] = event_id
        rows = (np.flatnonzero(positive[start:end]) + start).tolist()
        event_records.append({"event_id": event_id, "start": int(start), "end_exclusive": int(end),
            "known_onset": bool(start > 0 and y[start - 1] == 0), "eligible_rows": rows,
            "fold_ids": np.unique(folds[rows]).tolist(), "opportunity_intersections": 0,
            "normalized_weight_mass": 0.0})

    records = sum((_opportunities(origins[kind], kind) for kind in REQUEST_TYPES), [])
    records.sort(key=lambda item: (item["origin"], item["type"]))
    intersections = {}
    for record in records:
        rows = np.asarray(record["rows"], dtype=np.int64)
        kept = rows[eligible[rows]]
        negatives = rows[normal[rows]]
        positives = rows[positive[rows]]
        record.update(fold_id=int(folds[record["origin"]]), eligible_rows=kept.tolist(),
            normal_rows=negatives.tolist(), positive_rows=positives.tolist(),
            positive_intersections=[], normal_weight_mass=0.0,
            normal_weight_per_row=0.0, normalized_weight_mass=0.0)
        for event_id in np.unique(event_ids[positives]):
            selected = positives[event_ids[positives] == event_id]
            part = {"event_id": int(event_id), "rows": selected.tolist(),
                    "normalized_weight_mass": 0.0, "normalized_weight_per_row": 0.0}
            record["positive_intersections"].append(part)
            intersections.setdefault(int(event_id), []).append((record, part))

    normalized = np.zeros(n, dtype=np.float64)
    normal_records = [r for r in records if r["normal_rows"]]
    for record in normal_records:
        mass = .5 / len(normal_records)
        per_row = mass / len(record["normal_rows"])
        normalized[record["normal_rows"]] += per_row
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
            normalized[part["rows"]] += per_row
            part["normalized_weight_mass"] = mass
            part["normalized_weight_per_row"] = per_row
            record["normalized_weight_mass"] += mass

    positive_folds = np.unique(folds[positive]).tolist()
    fit_checks = {
        "at_least_128_normal_rows": int(normal.sum()) >= MIN_NORMAL_ROWS,
        "at_least_two_positive_segments": len(intersections) >= MIN_POSITIVE_EVENTS,
        "positive_examples_in_two_forecast_folds": len(positive_folds) >= MIN_POSITIVE_FOLDS,
    }
    request_support, per_offset = {}, {}
    for kind in REQUEST_TYPES:
        selected = [r for r in records if r["type"] == kind]
        normal_opportunities = sum(bool(r["normal_rows"]) for r in selected)
        event_set = sorted({p["event_id"] for r in selected for p in r["positive_intersections"]})
        type_active = origins[kind] >= 0
        request_support[kind] = {
            "supported": bool(normal_opportunities and event_set),
            "opportunities": len(selected), "normal_opportunities": normal_opportunities,
            "positive_opportunities": sum(bool(r["positive_rows"]) for r in selected),
            "positive_events": len(event_set), "positive_event_ids": event_set,
            "normal_rows": int((normal & type_active).sum()),
            "positive_rows": int((positive & type_active).sum()),
            "positive_folds": np.unique(folds[positive & type_active]).tolist(),
        }
        per_offset[kind] = []
        for offset in range(DEADLINE_SAMPLES + 1):
            mask = type_active & (np.arange(n) - origins[kind] == offset)
            per_offset[kind].append({"offset": offset, "opportunity_rows": int(mask.sum()),
                "eligible_rows": int((mask & eligible).sum()),
                "normal_rows": int((mask & normal).sum()), "positive_rows": int((mask & positive).sum()),
                "unknown_label_rows": int((mask & (y < 0)).sum()),
                "base_unavailable_rows": int((mask & ~observed).sum()),
                "positive_event_ids": np.unique(event_ids[mask & positive]).tolist()})
    per_fold = []
    for fold in np.unique(folds[folds >= 0]):
        mask = folds == fold
        per_fold.append({"fold_id": int(fold), "rows": int(mask.sum()),
            "opportunity_rows": int((mask & active).sum()), "eligible_rows": int((mask & eligible).sum()),
            "normal_rows": int((mask & normal).sum()), "positive_rows": int((mask & positive).sum()),
            "positive_event_ids": np.unique(event_ids[mask & positive]).tolist(),
            "normal_weight_mass": float(normalized[mask & (y == 0)].sum()),
            "positive_weight_mass": float(normalized[mask & (y == 1)].sum()),
            "opportunities_by_type": {kind: int(sum(r["type"] == kind and r["fold_id"] == fold for r in records))
                                      for kind in REQUEST_TYPES}})
    summary = {
        "training_rows": n, "opportunity_rows": int(active.sum()), "opportunities": len(records),
        "eligible_rows": int(eligible.sum()), "normal_rows": int(normal.sum()),
        "positive_rows": int(positive.sum()), "original_positive_segments": len(event_records),
        "positive_events": len(intersections), "positive_event_ids": sorted(intersections),
        "positive_folds": positive_folds, "positive_fold_count": len(positive_folds),
        "request_support": request_support, "per_fold": per_fold, "per_offset": per_offset,
        "fit_checks": fit_checks, "fit_supported": all(fit_checks.values()),
        "normal_weight_mass": float(normalized[y == 0].sum()),
        "positive_weight_mass": float(normalized[y == 1].sum()),
        "unknown_weight_mass": float(normalized[y < 0].sum()),
        "normalized_weight_sum": float(normalized.sum()),
        "sample_weight_scale": int(eligible.sum()),
        "weight_contract": "normal0.5 opportunity->row; positive0.5 originalsegment->opportunityintersection->row; overlap contributions summed on unique rows; absent class mass not redistributed",
    }
    return {"normalized": normalized, "sample": normalized * int(eligible.sum()),
            "eligible": eligible, "event_ids": event_ids, "summary": summary,
            "records": records, "event_records": event_records}
