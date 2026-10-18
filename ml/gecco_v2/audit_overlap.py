"""Audit GECCO source overlap without loading EVENT or feature distributions.

Only row counts, schema, source hashes, temporal metadata and row-hash
intersections are retained. Acquisition order is never changed.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import struct
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output/ml/gecco-v2-development/external_overlap_audit.json"
CHANNELS_2018 = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
CHANNELS_2019 = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
FILES = {
    "gecco2018": ROOT / "data/external/gecco2018/1_gecco2018_water_quality.csv",
    "gecco2019_train": ROOT / "data/external/gecco2019/7_gecco2019_train_water_quality.csv",
    "gecco2019_test": ROOT / "data/external/gecco2019/6_gecco2019_test_water_quality.csv",
    "gecco2019_valid": ROOT / "data/external/gecco2019/8_gecco2019_valid_water_qulity.csv",
}


def row_digest(row):
    timestamp, *values = row
    digest = hashlib.sha256(str(timestamp).encode("utf-8") + b"\0")
    for value in values:
        value = float(value)
        if math.isnan(value):
            digest.update(b"N")
        else:
            # Numeric equality treats negative zero and positive zero equally.
            digest.update(b"V" + struct.pack(">d", 0.0 if value == 0.0 else value))
    return digest.digest()


def inspect(name, path):
    # EVENT is explicitly excluded at parsing; no label array is materialized.
    channels = CHANNELS_2018 if name == "gecco2018" else CHANNELS_2019
    usecols = ["Time", *channels]
    frame = pd.read_csv(path, usecols=usecols)[usecols]
    assert not any(c.lower() == "event" for c in frame.columns)
    timestamps = pd.to_datetime(frame["Time"], errors="raise")
    canonical_time = timestamps.dt.strftime("%Y-%m-%d %H:%M:%S")
    canonical = frame.copy()
    canonical["Time"] = canonical_time
    digests = [row_digest(row) for row in canonical.itertuples(index=False, name=None)]
    differences = timestamps.diff().dt.total_seconds()
    reversals = []
    for position in differences.index[differences.lt(0)]:
        reversals.append({
            "row_position_one_based": int(position + 1),
            "previous_timestamp_original": str(frame.Time.iloc[position - 1]),
            "timestamp_original": str(frame.Time.iloc[position]),
            "delta_seconds": float(differences.iloc[position]),
        })
    content = path.read_bytes()  # File checksum only; labels are not parsed.
    metadata = {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "md5": hashlib.md5(content).hexdigest(),
        "row_count": int(len(frame)),
        "loaded_columns": frame.columns.tolist(),
        "sensor_columns": channels,
        "event_loaded": False,
        "first_timestamp_original": str(frame.Time.iloc[0]),
        "last_timestamp_original": str(frame.Time.iloc[-1]),
        "unique_timestamp_count": int(canonical_time.nunique()),
        "duplicate_timestamp_count": int(canonical_time.duplicated().sum()),
        "time_difference_counts_seconds": {
            str(float(delta)): int(count)
            for delta, count in differences.dropna().value_counts().items()
        },
        "clock_reversals": reversals,
        "unique_timestamp_sensor_vectors": len(set(digests)),
        "duplicate_timestamp_sensor_vectors": len(digests) - len(set(digests)),
    }
    return canonical, digests, set(canonical_time), metadata


def main():
    loaded = {name: inspect(name, path) for name, path in FILES.items()}
    pairs = []
    for left, right in itertools.combinations(FILES, 2):
        a, ah, at, _ = loaded[left]
        b, bh, bt, _ = loaded[right]
        identical_schema = list(a.columns) == list(b.columns)
        common_channels = [c for c in a.columns if c != "Time" and c in b.columns]
        shared_a = [row_digest(row) for row in a[["Time", *common_channels]].itertuples(index=False, name=None)]
        shared_b = [row_digest(row) for row in b[["Time", *common_channels]].itertuples(index=False, name=None)]
        shared_keys = set(shared_a) & set(shared_b)
        common = (set(ah) & set(bh)) if identical_schema else None
        pairs.append({
            "left": left,
            "right": right,
            "native_sensor_schema_identical": identical_schema,
            "overlapping_unique_timestamps": len(at & bt),
            "overlapping_unique_timestamp_full_native_sensor_vectors": len(common) if common is not None else None,
            "left_rows_with_full_native_match_in_right": sum(h in common for h in ah) if common is not None else None,
            "right_rows_with_full_native_match_in_left": sum(h in common for h in bh) if common is not None else None,
            "identical_selected_rows_in_acquisition_order": a.equals(b) if identical_schema else None,
            "identical_sensor_vectors_in_acquisition_order": a.drop(columns="Time").equals(b.drop(columns="Time")) if identical_schema else None,
            "shared_exact_name_channels_without_alias_inference": common_channels,
            "overlapping_unique_timestamp_shared_channel_vectors": len(shared_keys),
            "left_rows_with_shared_channel_match_in_right": sum(h in shared_keys for h in shared_a),
            "right_rows_with_shared_channel_match_in_left": sum(h in shared_keys for h in shared_b),
            "full_nine_channel_comparison_available": identical_schema and len(common_channels) == 9,
        })
    report = {
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Nonlabel schema, source hashes, temporal metadata and exact row overlap only",
        "event_loaded_anywhere": False,
        "feature_distributions_inspected": False,
        "acquisition_order_preserved": True,
        "overlap_key": "Timestamp to seconds plus the native sensor vector where schemas match; separate shared-exact-name-channel comparison where schemas differ; missing values canonicalized; SHA256",
        "schema_limit": "GECCO2018 has nine named sensor channels; GECCO2019 has six and only Tp/pH share exact names. No nine-channel equality assertion across years is possible. No alias mapping is inferred.",
        "actual_gecco2019_chronological_file_order": sorted(
            [name for name in FILES if name.startswith("gecco2019")],
            key=lambda name: loaded[name][3]["first_timestamp_original"],
        ),
        "chronology_warning": "Actual file timestamps place 2019 train before valid before test. Calibrating on test and then evaluating valid would use future data. This differs from the record description's stated train/test/validation order.",
        "independence_limit": "No exact overlap does not establish independence from the same measuring station or prove no temporal dependence.",
        "files": {name: entry[3] for name, entry in loaded.items()},
        "comparisons": pairs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(OUT), "comparisons": pairs,
                      "temporal_metadata": {name: {key: entry[3][key] for key in
                          ["row_count", "first_timestamp_original", "last_timestamp_original", "clock_reversals"]}
                          for name, entry in loaded.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
