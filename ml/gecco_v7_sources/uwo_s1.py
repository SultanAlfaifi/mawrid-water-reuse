"""Pinned UWO S1 reader, prepared using metadata and synthetic data only.

There is no source I/O at import and no command-line entry point. The caller
must explicitly acknowledge protocol freeze before any archive is opened.
This acknowledgement is an execution guard, not independent proof of freeze.

The complete supplied 2018 clock is retained. The paper instead describes
26 March--25 April 2017, while the file starts on 6 March 2018. The generic
publisher code uses a different, smaller example CSV and does not prove that
the first twenty supplied days were reviewed. Consequently, the conservative
annotation calendar starts on 26 March on the supplied 2018 axis. The publisher
tool also excludes days with fewer than 192 raw observations. Thus the first
twenty days and the final partial day have unknown labels, not normal labels.
The actual historical year and expert review coverage remain uncertain.

Publisher ``comp_labs_case1`` joins sparse selected timestamps to the raw clock,
maps ``left_only`` to 0 and ``both`` to 1, and unions bf_03, bf_04 and the
collective bf_03bf_04bl_ce193 stream. We implement that membership operation
inside the explicit annotation calendar; we never execute publisher notebooks
or unpickle data. Copied annotation measurements are not numeric inputs.

The member hashes and schema came from metadata qualification. No sensor value
or numeric row-label field was inspected while implementing this module.
Sparse annotation timestamps were inspected previously only for structural
alignment, so this is not a claim of zero annotation-coordinate exposure.
S1 lacks the specifically documented S2 point-anomaly filter, but its native
instrument provenance and all upstream processing are not established.

Cadence is five minutes per sample. No resampling, interpolation, smoothing,
feature construction, fitting, thresholding or event adjustment occurs here.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import re
from types import MappingProxyType
from typing import Any, NamedTuple
import zipfile

import numpy as np
import pandas as pd


CHANNELS = ("bf_03", "bf_04", "bl_ce193")
LABEL_STREAMS = ("bf_03", "bf_04", "bf_03bf_04bl_ce193")
CADENCE_SECONDS = 300
MIN_ANNOTATABLE_DAY_ROWS = 192
SOURCE_START = "2018-03-06 00:00:00"
SOURCE_END = "2018-04-25 12:00:00"
ANNOTATION_START_DATE = "2018-03-26"
ANNOTATION_END_DATE = "2018-04-25"
COVERAGE_CONTRACT = MappingProxyType({
    "id": "uwo-s1-paper-month-days-on-serialized-year-v1",
    "source_axis_year": 2018,
    "paper_axis_year": 2017,
    "annotation_start_date": ANNOTATION_START_DATE,
    "annotation_end_date_inclusive": ANNOTATION_END_DATE,
    "minimum_raw_rows_per_day": MIN_ANNOTATABLE_DAY_ROWS,
    "provenance": "conservative_documented_inference_not_byte_proven_annotation_universe",
    "retain_outside_calendar_as_unknown": True,
})
ARCHIVE_SHA256 = "f91e930d1e194f401f4570c8ddbfdd90606475233e2f6cd36114ff9da11fc8b0"
PUBLISHER_MAPPING_NOTEBOOK_SHA256 = "dd0cb7a13df126e814e476b2d2a8693a3c4a4a3f3c7d4a40a0b7151eb94952d9"
BASE = "ADASen_paper/data/02_UWO/Case 1/data_raw/"
RAW_MEMBER = BASE + "181128_trialData_UWOforADASen_case1.csv"
ANNOTATION_MEMBERS = MappingProxyType({
    stream: BASE + "Labels_1_181128/Labels_Case1_time_" + stream + ".csv"
    for stream in LABEL_STREAMS
})
EXPECTED_MEMBER_SHA256 = MappingProxyType({
    RAW_MEMBER: "ac310984f8525112b33440e7c677da663a3fdadac8095c980b61f687a56f5fd8",
    ANNOTATION_MEMBERS["bf_03"]: "aed637ccaab837d175a53c0f913dd0dd18268b4bede4d96c3102e5aad30f6b9a",
    ANNOTATION_MEMBERS["bf_04"]: "c0454d51eee7ea12f591cde8061bc5934ea80ff852b8b5c4f8f5e8a73ce1b483",
    ANNOTATION_MEMBERS["bf_03bf_04bl_ce193"]: "1b8fc3947c0d3c04d7e9ec5fdef05cf3db70179fe89078dcda15639dafa94b29",
})
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\Z", re.ASCII)
_MISSING = frozenset(("", "na", "nan", "null", "none", "n/a"))


class UwoS1QualificationError(ValueError):
    """Failure with structured audit context; no partially labelled result."""

    def __init__(self, code: str, message: str, **context):
        self.audit = {"status": "failed", "error_code": code, **context}
        super().__init__(message)


class UwoS1Data(NamedTuple):
    features: pd.DataFrame
    labels: np.ndarray
    audit: dict[str, Any]
    member_manifest: list[dict[str, Any]]


@dataclass(frozen=True)
class _Member:
    name: str
    kind: str
    stream: str
    header: tuple[str, ...]
    projected: tuple[str, ...]


def _plan():
    return (
        _Member(RAW_MEMBER, "measurement", "raw", ("time", *CHANNELS), ("time", *CHANNELS)),
        *(_Member(ANNOTATION_MEMBERS[stream], "annotation", stream,
                  ("", "date", "time", *(CHANNELS if stream == LABEL_STREAMS[-1] else ("value",))),
                  ("date", "time")) for stream in LABEL_STREAMS),
    )


def uwo_s1_member_plan() -> list[dict[str, Any]]:
    """Return a fresh metadata plan without accessing any file."""
    return [{"member": item.name, "kind": item.kind, "stream": item.stream,
             "header": list(item.header), "projected_columns": list(item.projected),
             "expected_sha256": EXPECTED_MEMBER_SHA256[item.name]} for item in _plan()]


@contextmanager
def _open_archive(source):
    if isinstance(source, zipfile.ZipFile):
        yield source
    else:
        with zipfile.ZipFile(source, "r") as archive:
            yield archive


def _rows(data: bytes, member: _Member):
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader)
        if tuple(header) != member.header:
            raise UwoS1QualificationError("header_mismatch", "Unexpected CSV header", member=member.name)
        positions = [header.index(column) for column in member.projected]
        for line, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise UwoS1QualificationError("row_width", "Unexpected CSV field count",
                                             member=member.name, line=line)
            # Annotation copied sensor/index fields are never numerically parsed.
            yield line, tuple(row[position] for position in positions)
    except (UnicodeError, csv.Error, StopIteration) as exc:
        raise UwoS1QualificationError("csv_invalid", "Invalid or empty CSV",
                                     member=member.name) from exc


def _timestamp(value, member, line):
    if not _STAMP.fullmatch(value):
        raise UwoS1QualificationError("timestamp_invalid", "Expected naive ISO timestamp to seconds",
                                     member=member, line=line)
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise UwoS1QualificationError("timestamp_invalid", "Invalid calendar timestamp",
                                     member=member, line=line) from exc


def _number(value, member, line, channel):
    stripped = value.strip()
    if stripped.casefold() in _MISSING:
        return np.nan
    try:
        number = float(stripped)
    except ValueError as exc:
        raise UwoS1QualificationError("measurement_invalid", "Unsupported numeric measurement",
                                     member=member, line=line, channel=channel) from exc
    return number if np.isfinite(number) else np.nan


def load_uwo_s1(archive, *, protocol_frozen: bool = False,
                coverage_contract: Mapping | None = None) -> UwoS1Data:
    """Explicitly load the four pinned CSVs only after caller protocol freeze.

    ``archive`` may be a ZIP path, binary file object or open ``ZipFile``.
    The caller must explicitly pass ``coverage_contract=dict(COVERAGE_CONTRACT)``
    to acknowledge the documented inference separately from protocol freeze.
    A caller-owned ZIP remains open. There is deliberately no production hash,
    calendar, channel or stream override. Synthetic tests patch module constants;
    they never use the real archive. All four hashes are verified before any
    CSV is parsed. Unselected archive members are never opened.

    Unexpected clocks, schema, hashes or unmapped sparse timestamps raise
    ``UwoS1QualificationError`` with an ``audit`` dictionary. Missing annotation
    files cannot become all-normal labels. Exact pinned members are verified;
    this function does not re-hash the entire 1.3GB archive.
    """
    if protocol_frozen is not True:
        raise UwoS1QualificationError("protocol_not_frozen", "Explicit protocol_frozen=True is required")
    if not isinstance(coverage_contract, Mapping) or dict(coverage_contract) != dict(COVERAGE_CONTRACT):
        raise UwoS1QualificationError("coverage_contract", "Explicit pinned coverage contract is required")
    plan = _plan()
    payloads = {}
    manifest = []
    with _open_archive(archive) as source:
        counts = Counter(info.filename for info in source.infolist())
        if any(counts[item.name] != 1 for item in plan):
            raise UwoS1QualificationError("member_set", "Required ZIP member missing or repeated",
                                         invalid_members=[item.name for item in plan if counts[item.name] != 1])
        for item in plan:
            info = source.getinfo(item.name)
            payload = source.read(info)
            digest = hashlib.sha256(payload).hexdigest()
            if digest != EXPECTED_MEMBER_SHA256[item.name]:
                raise UwoS1QualificationError("member_hash", "Pinned member SHA256 mismatch", member=item.name)
            payloads[item.name] = payload
            manifest.append({"member": item.name, "kind": item.kind, "stream": item.stream,
                             "sha256": digest, "sha256_verified": True,
                             "uncompressed_bytes": len(payload), "zip_crc32": f"{info.CRC:08x}",
                             "projected_columns": list(item.projected)})

    timestamps, values = [], []
    for line, row in _rows(payloads[RAW_MEMBER], plan[0]):
        timestamps.append(_timestamp(row[0], RAW_MEMBER, line))
        values.append([_number(value, RAW_MEMBER, line, channel)
                       for channel, value in zip(CHANNELS, row[1:])])
    index = pd.DatetimeIndex(timestamps, name="timestamp")
    if index.has_duplicates:
        raise UwoS1QualificationError("raw_duplicate_timestamp", "Raw timestamp repetition is not allowed")
    expected = pd.date_range(SOURCE_START, SOURCE_END, freq=pd.Timedelta(seconds=CADENCE_SECONDS),
                             name="timestamp")
    if not index.equals(expected):
        raise UwoS1QualificationError("raw_axis", "Raw clock differs from the complete pinned 2018 axis",
                                     expected_rows=len(expected), observed_rows=len(index))
    features = pd.DataFrame(values, index=index, columns=CHANNELS, dtype=float)
    # Clock-only calendar, never based on sensor missingness or annotation content.
    day_strings = index.strftime("%Y-%m-%d")
    day_counts = Counter(day_strings)
    declared = ((day_strings >= ANNOTATION_START_DATE) & (day_strings <= ANNOTATION_END_DATE))
    adequate_day = np.array([day_counts[day] >= MIN_ANNOTATABLE_DAY_ROWS for day in day_strings])
    annotatable = np.asarray(declared & adequate_day, dtype=bool)
    grid = set(timestamps)
    selected_union = set()
    stream_audit = {}
    for item in plan[1:]:
        selected = set()
        rows = 0
        for line, row in _rows(payloads[item.name], item):
            stamp = _timestamp(row[0] + " " + row[1], item.name, line)
            if stamp not in grid:
                raise UwoS1QualificationError("annotation_unmapped", "Annotation timestamp is outside the raw grid",
                                             member=item.name, line=line)
            selected.add(stamp)
            rows += 1
        selected_union.update(selected)
        outside_calendar = sum(not (ANNOTATION_START_DATE <= stamp.strftime("%Y-%m-%d") <= ANNOTATION_END_DATE)
                               or day_counts[stamp.strftime("%Y-%m-%d")] < MIN_ANNOTATABLE_DAY_ROWS
                               for stamp in selected)
        stream_audit[item.stream] = {"rows": rows, "unique_selected_timestamps": len(selected),
                                    "duplicate_selected_rows": rows - len(selected),
                                    "selected_timestamps_outside_annotatable_calendar": outside_calendar}
        next(m for m in manifest if m["member"] == item.name)["rows"] = rows
    manifest[0]["rows"] = len(index)
    labels = np.full(len(index), -1, dtype=np.int8)
    selected_mask = np.fromiter((stamp in selected_union for stamp in timestamps), dtype=bool, count=len(index))
    labels[annotatable] = selected_mask[annotatable].astype(np.int8)
    features.attrs = {"cadence_seconds": CADENCE_SECONDS, "source_member": RAW_MEMBER,
                      "label_independent_features": True, "source_axis_preserved": True}
    audit = {
        "status": "passed", "protocol_freeze_acknowledged_by_caller": True,
        "source_qualification": "conditional_on_documented_label_coverage_inference",
        "coverage_contract": dict(COVERAGE_CONTRACT),
        "rows": len(index), "cadence_seconds": CADENCE_SECONDS,
        "source_start": index[0].isoformat(), "source_end_inclusive": index[-1].isoformat(),
        "annotation_calendar_start": ANNOTATION_START_DATE, "annotation_calendar_end": ANNOTATION_END_DATE,
        "minimum_annotatable_day_rows": MIN_ANNOTATABLE_DAY_ROWS,
        "day_raw_row_counts": dict(sorted(day_counts.items())),
        "rows_outside_documented_calendar": int(np.count_nonzero(~declared)),
        "rows_on_inadequate_days": int(np.count_nonzero(~adequate_day)),
        "annotatable_rows": int(annotatable.sum()),
        "labels": {str(value): int(np.count_nonzero(labels == value)) for value in (-1, 0, 1)},
        "streams": stream_audit,
        "sensor_nonfinite_count_by_channel": {channel: int(features[channel].isna().sum()) for channel in CHANNELS},
        "rows_with_any_finite_measurement": int(np.isfinite(features.to_numpy()).any(axis=1).sum()),
        "expected_whole_archive_sha256": ARCHIVE_SHA256, "whole_archive_hash_verified_here": False,
        "verified_member_count": len(manifest), "label_feature_separation": True,
        "provenance_limits": [
            "Paper says 26 March--25 April 2017; supplied axis says 6 March--25 April 2018.",
            "The first twenty supplied days have unproven annotation coverage and are unknown.",
            "Partial days below 192 raw rows are unknown; features remain present.",
            "Calendar limits are a conservative documentation-based convention, not an expert completion log.",
            "S1 was exempted from the specified S2 filter; other upstream processing remains unverified.",
            "Implementation used metadata, pinned code and synthetic fixtures only; sparse timestamp alignment was exposed.",
        ],
    }
    return UwoS1Data(features, labels, audit, manifest)
