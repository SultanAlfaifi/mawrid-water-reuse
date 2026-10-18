"""Explicit WaterHub CSV loader for use only after the caller freezes its protocol.

Importing this module performs no IO; there is no CLI or automatic data load.
The member names and headers below come from the already disclosed directory
inventory and header-only metadata in
output/ml/gecco-v5-source-search/waterhub-metadata. No measurement or annotation
row was consulted to implement this loader.

The default calendar is June 2018 through April 2019, including raw August with
no annotations. May is outside this declared scope. Raw inputs use day/hour
and p1/p2 or p3/p4. Annotation inputs use only day/time/Anomaly; their copied
pressure values and exported row-index columns are never parsed into outputs.
The SHA256 manifest covers each complete uncompressed member's original bytes.

No rows are sorted, deduplicated, resampled, interpolated, filled or filtered by
values. Duplicate timestamps and contradictory labels reach the adapter intact.
A fixed duplicate-clock mask is computed solely from ALL selected raw calendar
timestamps, separately by process and then unioned. This is offline temporal
qualification, not an online ability to foresee a future clock repetition.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
import csv
from dataclasses import dataclass
import hashlib
import io
import re
from typing import Any, NamedTuple
import zipfile

import numpy as np
import pandas as pd

try:
    from .waterhub_adapter import LABEL_STREAMS
except ImportError:
    from waterhub_adapter import LABEL_STREAMS


BASE = "ADASen_paper/data/04_WaterHub/data_raw"
MONTH_STEMS = {
    "2018-06": "06_June 2018", "2018-07": "07_July 2018",
    "2018-08": "08_August 2018", "2018-09": "09_September 2018",
    "2018-10": "10_October 2018", "2018-11": "11_November 2018",
    "2018-12": "12_December 2018", "2019-01": "13_January 2019",
    "2019-02": "14_February 2019", "2019-03": "15_March 2019",
    "2019-04": "16_April 2019",
}
DEFAULT_MONTHS = tuple(MONTH_STEMS)
UNLABELLED_MONTHS = ("2018-08",)
PROCESS_DIRECTORIES = {
    "T1_T2": f"{BASE}/data_pressure_sensors_T1_T2",
    "GAK": f"{BASE}/data_pressure_sensor_GAK",
}
RAW_FORMAT = "%d.%m.%Y %H:%M:%S"
ANNOTATION_FORMAT = "%Y-%m-%d %H:%M:%S"


class WaterHubInputs(NamedTuple):
    raw_t1_t2: pd.DataFrame
    raw_gak: pd.DataFrame
    annotations: dict[str, pd.DataFrame]


@dataclass(frozen=True)
class WaterHubArchive:
    monthly: dict[str, WaterHubInputs]
    timestamp_ambiguity_mask: pd.DatetimeIndex
    member_manifest: list[dict[str, Any]]
    metadata: dict[str, Any]

    def combined(self) -> WaterHubInputs:
        """Concatenate the selected months in calendar order without dropping rows.

        A fresh combined view is allocated only when requested; monthly inputs
        remain usable for bounded-memory adaptation with the full fixed mask.
        """
        parts = list(self.monthly.values())
        return WaterHubInputs(
            pd.concat([part.raw_t1_t2 for part in parts], axis=0),
            pd.concat([part.raw_gak for part in parts], axis=0),
            {stream: pd.concat([part.annotations[stream] for part in parts], axis=0)
             for stream in LABEL_STREAMS},
        )


def _months(months):
    if months is None:
        return DEFAULT_MONTHS
    if isinstance(months, (str, bytes)):
        raise ValueError("months must be a collection of YYYY-MM strings")
    selected = tuple(months)
    if not selected or any(not isinstance(value, str) for value in selected):
        raise ValueError("At least one supported YYYY-MM month is required")
    if len(set(selected)) != len(selected) or not set(selected).issubset(MONTH_STEMS):
        raise ValueError("Duplicate months or months outside June 2018--April 2019")
    return tuple(month for month in DEFAULT_MONTHS if month in selected)


def waterhub_member_plan(months=None) -> list[dict[str, Any]]:
    """Return the exact predeclared member/schema plan without opening an archive."""
    plan = []
    for month in _months(months):
        stem = MONTH_STEMS[month]
        for process, channels in (("T1_T2", ("p1", "p2")), ("GAK", ("p3", "p4"))):
            directory = PROCESS_DIRECTORIES[process]
            plan.append({
                "month": month, "kind": "raw", "stream": process,
                "member": f"{directory}/{stem}.csv",
                "header": ["day", "hour", *channels],
                "usecols": ["day", "hour", *channels],
                "output_columns": list(channels), "timestamp_format": RAW_FORMAT,
            })
            if month in UNLABELLED_MONTHS:
                continue
            for stream, copied in ((channels[0], [channels[0]]),
                                   (channels[1], [channels[1]]),
                                   ("".join(channels), list(channels))):
                plan.append({
                    "month": month, "kind": "annotation", "stream": stream,
                    "member": f"{directory}/labels/{stem}_labels_time{stream}.csv",
                    "header": ["", "day", "time", *copied, "Anomaly"],
                    "usecols": ["day", "time", "Anomaly"],
                    "output_columns": ["Anomaly"],
                    "timestamp_format": ANNOTATION_FORMAT,
                })
    return plan


@contextmanager
def _open_archive(source):
    if isinstance(source, zipfile.ZipFile):
        yield source
    else:
        with zipfile.ZipFile(source, "r") as archive:
            yield archive


def _empty_annotations():
    index = pd.DatetimeIndex([], dtype="datetime64[ns]", name="timestamp")
    return {stream: pd.DataFrame({"Anomaly": pd.Series([], dtype=float)}, index=index)
            for stream in LABEL_STREAMS}


def _parse_member(data: bytes, spec):
    header_bytes = data.split(b"\n", 1)[0]
    header_text = header_bytes.decode("utf-8-sig").rstrip("\r")
    header = next(csv.reader([header_text], strict=True))
    if header != spec["header"]:
        raise ValueError(f"Unexpected header for {spec['member']}: {header!r}")
    clock = "hour" if spec["kind"] == "raw" else "time"
    # usecols explicitly excludes annotation pressure columns and exported index.
    parsed = pd.read_csv(io.BytesIO(data), usecols=spec["usecols"],
                         dtype={"day": "string", clock: "string"},
                         encoding="utf-8-sig", low_memory=False)
    text = parsed["day"] + " " + parsed[clock]
    timestamps = pd.DatetimeIndex(pd.to_datetime(
        text, format=spec["timestamp_format"], exact=True, errors="raise"),
        name="timestamp").as_unit("ns")
    if timestamps.hasnans or timestamps.tz is not None:
        raise ValueError(f"Missing or timezone-aware timestamps in {spec['member']}")
    start = pd.Timestamp(spec["month"] + "-01")
    end = start + pd.offsets.MonthBegin(1)
    if len(timestamps) and ((timestamps < start) | (timestamps >= end)).any():
        raise ValueError(f"Timestamp outside declared filename month in {spec['member']}")
    # Numeric parsing matches the adapter's errors=coerce policy. NaN, infinity,
    # nonbinary labels and duplicates are retained for its declared accounting.
    output = pd.DataFrame(index=timestamps)
    for column in spec["output_columns"]:
        output[column] = pd.to_numeric(parsed[column], errors="coerce").to_numpy(
            dtype=float, na_value=np.nan)
    output.attrs = {"source_member": spec["member"], "source_rows_preserved": True}
    return output, hashlib.sha256(header_bytes).hexdigest()


def load_waterhub_archive(archive, months=None, *, expected_member_sha256=None) -> WaterHubArchive:
    """Load the explicitly selected scope after protocol freeze, never at import.

    ``archive`` accepts a path, binary file-like object, or an open ZipFile.
    The default selects all 11 calendar months, including unlabelled August.
    Optional months select only declared month IDs in deterministic calendar
    order. Freeze that scope before measurements/labels are opened.

    An optional expected_member_sha256 mapping must cover the exact selected
    members. Each checksum is verified before that member's CSV is parsed.
    The returned manifest records SHA256 of exact uncompressed bytes, zip CRC,
    selected columns, row counts, and per-stream concatenation offsets. It is
    not a whole-archive publisher-checksum verification.

    No byte from an unselected member is opened. There is no extraction or
    pickle execution. Unknown/invalid parsed numeric values are not filled.
    A missing required annotated file is an error; only metadata-declared
    August is represented by empty annotation frames.
    """
    selected = _months(months)
    plan = waterhub_member_plan(selected)
    required = {spec["member"] for spec in plan}
    if expected_member_sha256 is not None:
        if not isinstance(expected_member_sha256, Mapping) or set(expected_member_sha256) != required:
            raise ValueError("Expected SHA256 mapping must cover the exact selected member set")
        if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None
               for value in expected_member_sha256.values()):
            raise ValueError("Expected SHA256 values must be 64 hexadecimal characters")
    frames = {month: {"raw": {}, "annotations": _empty_annotations()} for month in selected}
    manifest = []
    offsets = {}
    with _open_archive(archive) as source:
        counts = Counter(info.filename for info in source.infolist())
        invalid = sorted(name for name in required if counts[name] != 1)
        if invalid:
            raise ValueError(f"Missing or duplicate selected ZIP member names: {invalid}")
        for spec in plan:
            info = source.getinfo(spec["member"])
            data = source.read(info)
            digest = hashlib.sha256(data).hexdigest()
            if expected_member_sha256 is not None and digest != expected_member_sha256[spec["member"]].lower():
                raise ValueError(f"SHA256 mismatch for {spec['member']}")
            frame, header_hash = _parse_member(data, spec)
            group = "raw" if spec["kind"] == "raw" else "annotations"
            frames[spec["month"]][group][spec["stream"]] = frame
            key = (spec["kind"], spec["stream"])
            offset = offsets.get(key, 0)
            manifest.append({
                "member": spec["member"], "month": spec["month"],
                "kind": spec["kind"], "stream": spec["stream"],
                "sha256": digest, "uncompressed_bytes": len(data),
                "zip_crc32": f"{info.CRC:08x}",
                "header_sha256_excluding_lf": header_hash,
                "parsed_columns": list(spec["usecols"]),
                "output_columns": list(spec["output_columns"]),
                "rows": len(frame), "combined_row_start": offset,
                "combined_row_end_exclusive": offset + len(frame),
            })
            offsets[key] = offset + len(frame)
    monthly = {
        month: WaterHubInputs(part["raw"]["T1_T2"], part["raw"]["GAK"], part["annotations"])
        for month, part in frames.items()
    }
    duplicated = []
    duplicate_counts = {}
    for process, attr in (("T1_T2", "raw_t1_t2"), ("GAK", "raw_gak")):
        # Counts are within each process, not the expected two-process overlap.
        times = pd.DatetimeIndex(np.concatenate([
            getattr(part, attr).index.asi8 for part in monthly.values()]))
        repeats = times[times.duplicated(keep=False)].unique()
        duplicated.append(repeats.asi8)
        duplicate_counts[process] = len(repeats)
    ambiguity = pd.DatetimeIndex(np.unique(np.concatenate(duplicated)), name="timestamp")
    mask_bytes = "\n".join(ambiguity.strftime("%Y-%m-%dT%H:%M:%S.%f")).encode("ascii")
    metadata = {
        "selected_months": list(selected),
        "unlabelled_months_retained": [month for month in selected if month in UNLABELLED_MONTHS],
        "excluded_scope": "May 2019 and all non-WaterHub/nonselected members",
        "source_member_count": len(manifest),
        "member_sha256_verified_against_expected": expected_member_sha256 is not None,
        "whole_archive_sha256_verified_by_loader": False,
        "raw_timestamp_format": RAW_FORMAT, "annotation_timestamp_format": ANNOTATION_FORMAT,
        "raw_duplicate_timestamp_counts_by_process": duplicate_counts,
        "fixed_raw_ambiguous_timestamp_count": len(ambiguity),
        "fixed_raw_ambiguity_mask_sha256": hashlib.sha256(mask_bytes).hexdigest(),
        "ambiguity_mask_basis": "All raw timestamps in the selected calendar; no annotation input",
        "source_rows_preserved": True, "copied_annotation_pressure_columns_loaded": False,
        "limitations": [
            "Read this scope only after caller protocol freeze; no automatic CLI is provided.",
            "A fixed duplicate-clock mask is offline timestamp qualification, not live clock foresight.",
            "Annotation conflicts are preserved for the adapter; no label-driven scope selection occurs.",
            "Instrument-to-raw provenance and wall-clock timezone remain unspecified.",
        ],
    }
    return WaterHubArchive(monthly, ambiguity, manifest, metadata)
