"""Pure in-memory WaterHub adapter; no source IO, pickle, fitting or prediction.

This evaluates a declared raw-input policy, not the publisher's zero-filled,
every-sixth-row pickle. A minute [M, M+60s) uses raw p1--p4 at M+50s and is
timestamped M+60s. Its label is the OR of six annotation streams at six slots,
only when all 36 labels are known. Annotation pressure columns are never read.

Repeated wall-clock timestamps cannot establish physical acquisition order.
``timestamp_ambiguity_mask`` is an optional *already frozen* collection of
ambiguous raw timestamps, or a boolean Series indexed by those timestamps.
Batch/prefix parity is conditional on the same mask and on comparing closed
minutes. Without a complete mask, later repeated clock times can invalidate
earlier minutes; this adapter does not claim online clock-disambiguation.

Inputs have a naive DatetimeIndex, a parsed ``timestamp`` column, or the
publisher's day/hour (raw) and day/time (annotation) columns. grid_start and
grid_end, when supplied, are inclusive minute-start bounds. Only a caller with
a minute-end watermark may emit the resulting row in a live system. No labels
or annotation-derived availability may enter the inference feature path.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


CHANNELS = ("p1", "p2", "p3", "p4")
LABEL_STREAMS = ("p1", "p2", "p1p2", "p3", "p4", "p3p4")
TEN_SECONDS_NS = 10_000_000_000
RAW_AUDIT_COLUMNS = (
    "feature_available", "raw_missing_timestamp", "raw_duplicate_timestamp",
    "raw_off_grid_timestamp", "raw_process_mismatch", "fixed_clock_ambiguity",
    "nonfinite_selected_pressure", "partial_boundary_minute",
)


@dataclass(frozen=True)
class WaterHubAdapted:
    features: pd.DataFrame
    labels: pd.Series
    audit: pd.DataFrame
    metadata: dict[str, Any]

    @property
    def frame(self) -> pd.DataFrame:
        """Convenience view; inference should explicitly select ``features``."""
        return pd.concat([self.features, self.labels, self.audit], axis=1)


def _checked_index(values: Any, name: str) -> pd.DatetimeIndex:
    try:
        index = pd.DatetimeIndex(values)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name}: invalid datetime values") from exc
    if index.hasnans:
        raise ValueError(f"{name}: missing timestamps are not allowed")
    if index.tz is not None:
        raise ValueError(f"{name}: timezone-aware timestamps require a separate protocol")
    # pandas can store a DatetimeIndex at a resolution other than nanoseconds.
    return index.as_unit("ns")


def _timestamps(frame: pd.DataFrame, *, raw: bool) -> pd.DatetimeIndex:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Inputs must be DataFrames; this adapter does not open paths")
    if "timestamp" in frame.columns:
        return _checked_index(frame["timestamp"], "timestamp")
    if isinstance(frame.index, pd.DatetimeIndex):
        return _checked_index(frame.index, "index")
    clock = "hour" if raw else "time"
    if {"day", clock}.issubset(frame.columns):
        text = frame["day"].astype(str) + " " + frame[clock].astype(str)
        fmt = "%d.%m.%Y %H:%M:%S" if raw else "%Y-%m-%d %H:%M:%S"
        return _checked_index(pd.to_datetime(text, format=fmt, errors="raise"), clock)
    if frame.empty:
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    raise ValueError("Require DatetimeIndex, timestamp, or documented day/clock columns")


def _bound(value: Any, name: str) -> pd.Timestamp | None:
    if value is None:
        return None
    result = _checked_index([value], name)[0]
    if result != result.floor("min"):
        raise ValueError(f"{name} must be an exact minute-start boundary")
    return result


def _grid(a: pd.DatetimeIndex, b: pd.DatetimeIndex,
          start: Any, end: Any) -> pd.DatetimeIndex:
    start, end = _bound(start, "grid_start"), _bound(end, "grid_end")
    nonempty = [index for index in (a, b) if len(index)]
    if not nonempty:
        if start is None and end is None:
            return pd.DatetimeIndex([], dtype="datetime64[ns]")
        if start is None or end is None:
            raise ValueError("Both grid bounds are required when raw inputs are empty")
    else:
        if start is None:
            start = min(index.min() for index in nonempty).floor("min")
        if end is None:
            end = max(index.max() for index in nonempty).floor("min")
    if start > end:
        raise ValueError("grid_start is after grid_end")
    return pd.date_range(start, end, freq="min").as_unit("ns")


def _minute_flags(times: pd.DatetimeIndex, starts: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(starts.isin(times.floor("min")), dtype=bool)


def _ambiguity_times(mask: Iterable | pd.Series | None) -> pd.DatetimeIndex:
    if mask is None:
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    if isinstance(mask, pd.Series):
        if not pd.api.types.is_bool_dtype(mask.dtype) or mask.isna().any():
            raise ValueError("Timestamp ambiguity Series must contain known booleans")
        return _checked_index(mask.index[mask.to_numpy(dtype=bool)], "ambiguity mask")
    if isinstance(mask, (str, bytes)):
        raise TypeError("Timestamp ambiguity mask must be a collection, not a string")
    return _checked_index(list(mask), "ambiguity mask")


def _raw_features(raw_t1_t2: pd.DataFrame, raw_gak: pd.DataFrame,
                  starts: pd.DatetimeIndex, a: pd.DatetimeIndex, b: pd.DatetimeIndex,
                  expected: pd.DatetimeIndex, ambiguity: pd.DatetimeIndex):
    n = len(starts)
    counts = [index.value_counts(sort=False) for index in (a, b)]
    slots = [count.reindex(expected, fill_value=0).to_numpy().reshape(n, 6)
             for count in counts]
    missing = (slots[0] == 0).any(axis=1) | (slots[1] == 0).any(axis=1)
    duplicate_times = a[a.duplicated(keep=False)].append(b[b.duplicated(keep=False)])
    duplicate = _minute_flags(duplicate_times, starts)
    off_grid_times = a[a.asi8 % TEN_SECONDS_NS != 0].append(
        b[b.asi8 % TEN_SECONDS_NS != 0])
    off_grid = _minute_flags(off_grid_times, starts)
    left, right = counts[0].align(counts[1], join="outer", fill_value=0)
    mismatch = _minute_flags(_checked_index(left.index[left != right], "raw mismatch"), starts)
    fixed = _minute_flags(ambiguity, starts)
    chosen = starts + pd.Timedelta(seconds=50)
    output_index = pd.DatetimeIndex(starts + pd.Timedelta(minutes=1), name="minute_end")
    features = pd.DataFrame(index=output_index, columns=CHANNELS, dtype=float)
    nonfinite = np.zeros(n, dtype=bool)
    for frame, times, group, slot_counts in (
        (raw_t1_t2, a, ("p1", "p2"), slots[0]),
        (raw_gak, b, ("p3", "p4"), slots[1]),
    ):
        unique_selected = times.isin(chosen) & ~times.duplicated(keep=False)
        for channel in group:
            if channel not in frame.columns:
                raise ValueError(f"Raw input is missing required channel {channel}")
            values = pd.to_numeric(frame.loc[unique_selected, channel], errors="coerce")
            values = pd.Series(values.to_numpy(dtype=float, na_value=np.nan),
                               index=times[unique_selected]).reindex(chosen)
            array = values.to_numpy(dtype=float)
            features[channel] = array
            nonfinite |= (slot_counts[:, 5] == 1) & ~np.isfinite(array)
    partial = np.zeros(n, dtype=bool)
    for times in (a, b):
        if len(times) and n:
            first, last = times.min(), times.max()
            partial |= (starts == first.floor("min")) & (first > starts)
            partial |= (starts == last.floor("min")) & (last < chosen)
    available = ~(missing | duplicate | off_grid | mismatch | fixed | nonfinite)
    # A missing selected reading is already caught by timestamp completeness.
    available &= np.isfinite(features.to_numpy()).all(axis=1)
    features.loc[~available, :] = np.nan
    audit = pd.DataFrame({
        "feature_available": available,
        "raw_missing_timestamp": missing,
        "raw_duplicate_timestamp": duplicate,
        "raw_off_grid_timestamp": off_grid,
        "raw_process_mismatch": mismatch,
        "fixed_clock_ambiguity": fixed,
        "nonfinite_selected_pressure": nonfinite,
        "partial_boundary_minute": partial,
    }, index=output_index)
    return features, audit


def _labels(annotations: Mapping[str, pd.DataFrame], starts: pd.DatetimeIndex,
            expected: pd.DatetimeIndex, output_index: pd.DatetimeIndex):
    if not isinstance(annotations, Mapping) or set(annotations) != set(LABEL_STREAMS):
        raise ValueError(f"Annotations must contain exactly {LABEL_STREAMS}")
    n = len(starts)
    known_count = np.zeros(n, dtype=np.int16)
    positive = np.zeros(n, dtype=bool)
    missing = np.zeros(n, dtype=bool)
    ambiguous = np.zeros(n, dtype=bool)
    off_grid = np.zeros(n, dtype=bool)
    duplicate = np.zeros(n, dtype=bool)
    stream_metadata = {}
    for stream in LABEL_STREAMS:
        frame = annotations[stream]
        times = _timestamps(frame, raw=False)
        if "Anomaly" not in frame.columns:
            raise ValueError(f"Annotation stream {stream} is missing Anomaly")
        values = pd.to_numeric(frame["Anomaly"], errors="coerce").to_numpy(
            dtype=float, na_value=np.nan)
        valid = np.isfinite(values) & np.isin(values, (0.0, 1.0))
        work = pd.DataFrame({"value": np.where(valid, values, np.nan), "valid": valid},
                            index=times)
        grouped = work.groupby(level=0, sort=False).agg(
            count=("value", "size"), valid=("valid", "all"),
            low=("value", "min"), high=("value", "max"))
        agrees = grouped["valid"] & (grouped["low"] == grouped["high"])
        resolved = pd.Series(-1, index=grouped.index, dtype=np.int8)
        resolved.loc[agrees] = grouped.loc[agrees, "low"].astype(np.int8)
        grid_values = resolved.reindex(expected, fill_value=-1).to_numpy().reshape(n, 6)
        grid_present = expected.isin(grouped.index).reshape(n, 6)
        known_count += (grid_values >= 0).sum(axis=1).astype(np.int16)
        positive |= (grid_values == 1).any(axis=1)
        missing |= (~grid_present).any(axis=1)
        ambiguous |= (grid_present & (grid_values < 0)).any(axis=1)
        off_grid |= _minute_flags(times[times.asi8 % TEN_SECONDS_NS != 0], starts)
        duplicate |= _minute_flags(times[times.duplicated(keep=False)], starts)
        stream_metadata[stream] = {
            "input_rows": len(frame), "unique_timestamps": len(grouped),
            "duplicate_timestamp_groups": int((grouped["count"] > 1).sum()),
            "unknown_timestamp_groups": int((~agrees).sum()),
        }
    available = (known_count == 36) & ~off_grid
    labels = pd.Series(np.where(available, positive.astype(np.int8), -1),
                       index=output_index, dtype=np.int8, name="label")
    audit = pd.DataFrame({
        "label_available": available,
        "annotation_missing_timestamp": missing,
        "annotation_ambiguous_value": ambiguous,
        "annotation_off_grid_timestamp": off_grid,
        "annotation_duplicate_timestamp": duplicate,
        "known_annotation_slots": known_count,
    }, index=output_index)
    return labels, audit, stream_metadata


def adapt_waterhub(raw_t1_t2: pd.DataFrame, raw_gak: pd.DataFrame,
                   annotations: Mapping[str, pd.DataFrame], *,
                   timestamp_ambiguity_mask: Iterable | pd.Series | None = None,
                   grid_start: Any = None, grid_end: Any = None) -> WaterHubAdapted:
    """Adapt already-loaded data without fitting, source IO, or label features.

    Raw process frames contain p1/p2 and p3/p4 respectively. All six annotation
    frames must be supplied (empty frames are allowed), with ``Anomaly`` labels.
    Invalid/contradictory annotations make their minute unknown, rather than
    normal. Unexpected off-grid timestamps conservatively invalidate that
    minute in the relevant feature or label path. Inputs are not mutated.

    Explicit grid bounds let callers retain a predeclared full calendar even
    when an input block is empty. Bounds describe minute starts, inclusively.
    Inferred bounds depend only on raw timestamps, never on annotations.
    """
    a, b = _timestamps(raw_t1_t2, raw=True), _timestamps(raw_gak, raw=True)
    starts = _grid(a, b, grid_start, grid_end)
    ambiguity = _ambiguity_times(timestamp_ambiguity_mask)
    offsets = np.arange(6, dtype=np.int64) * TEN_SECONDS_NS
    expected = pd.DatetimeIndex((starts.asi8[:, None] + offsets).reshape(-1))
    # Complete the raw-only path before parsing annotation values or masks.
    features, raw_audit = _raw_features(raw_t1_t2, raw_gak, starts, a, b,
                                        expected, ambiguity)
    labels, label_audit, stream_metadata = _labels(annotations, starts, expected,
                                                  features.index)
    audit = pd.concat([raw_audit, label_audit], axis=1)
    metadata = {
        "adapter_policy": "minute_end_raw_last_complete_grid_six_stream_or_v1",
        "cadence_seconds": 60, "feature_sample_offset_seconds": 50,
        "output_timestamp": "minute_end", "output_rows": len(starts),
        "raw_rows_t1_t2": len(raw_t1_t2), "raw_rows_gak": len(raw_gak),
        "feature_available_minutes": int(raw_audit.feature_available.sum()),
        "label_known_minutes": int(label_audit.label_available.sum()),
        "timestamp_ambiguity_mask_supplied": timestamp_ambiguity_mask is not None,
        "fixed_ambiguous_timestamp_count": len(ambiguity.unique()),
        "annotation_streams": stream_metadata,
        "limitations": [
            "One hydraulic-pressure installation; no chemical-quality or field-safety claim.",
            "Timezone and instrument-to-raw export provenance remain unspecified.",
            "Prefix parity requires the same frozen clock ambiguity mask and closed minutes.",
            "Known labels are independent of feature availability; unknown labels are not normal.",
            "Minute OR labels may describe a transient absent in the selected :50 reading.",
            "This raw policy is not the publisher's zero-filled/thinned benchmark input.",
        ],
    }
    return WaterHubAdapted(features, labels, audit, metadata)
