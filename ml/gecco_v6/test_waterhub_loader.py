"""Synthetic in-memory ZIP tests only; the actual ADASen archive is never opened."""
import csv
import hashlib
import io
import unittest
from unittest.mock import patch
import warnings
import zipfile

import numpy as np
import pandas as pd

import waterhub_loader as loader
from waterhub_adapter import adapt_waterhub, LABEL_STREAMS


def synthetic_members(months=("2018-06",), *, duplicate_raw=False,
                      conflicting_label=False, row_count=12):
    """Every value here is invented. Copied annotation pressures are poison text."""
    members = {}
    for spec in loader.waterhub_member_plan(months):
        times = list(pd.date_range(spec["month"] + "-03", periods=row_count, freq="10s"))
        rows = []
        for i, time in enumerate(times):
            if spec["kind"] == "raw":
                row = {"day": time.strftime("%d.%m.%Y"), "hour": time.strftime("%H:%M:%S")}
                for channel in spec["output_columns"]:
                    row[channel] = 100 * int(channel[-1]) + i
            else:
                row = {"": "ignored source export index", "day": time.strftime("%Y-%m-%d"),
                       "time": time.strftime("%H:%M:%S"), "Anomaly": int(i == 6)}
                for column in spec["header"]:
                    if column.startswith("p"):
                        row[column] = "DO NOT USE COPIED PRESSURE"
            rows.append(row)
        if duplicate_raw and spec["kind"] == "raw" and rows:
            rows.append(dict(rows[2]))
        if conflicting_label and spec["kind"] == "annotation" and spec["stream"] == "p1" and rows:
            extra = dict(rows[1])
            extra["Anomaly"] = 1
            rows.append(extra)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=spec["header"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        members[spec["member"]] = buffer.getvalue().encode("utf-8")
    return members


def synthetic_zip(members, *, duplicates=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        for name in duplicates:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(name, members[name])
    buffer.seek(0)
    return buffer


def rewrite_csv(data, mutate):
    source = io.StringIO(data.decode())
    reader = csv.DictReader(source)
    fieldnames = reader.fieldnames
    rows = list(reader)
    mutate(rows)
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return target.getvalue().encode()


class WaterHubLoaderTests(unittest.TestCase):
    def test_default_metadata_plan_has_82_members_including_raw_august_not_may(self):
        plan = loader.waterhub_member_plan()
        self.assertEqual(len(plan), 82)
        self.assertEqual(sum(s["kind"] == "raw" for s in plan), 22)
        self.assertEqual(sum(s["kind"] == "annotation" for s in plan), 60)
        self.assertEqual(sorted({s["month"] for s in plan}), list(loader.DEFAULT_MONTHS))
        august = [s for s in plan if s["month"] == "2018-08"]
        self.assertEqual(len(august), 2)
        self.assertTrue(all(s["kind"] == "raw" for s in august))
        self.assertFalse(any("May" in s["member"] for s in plan))

    def test_loader_returns_compact_tuple_inputs_with_exact_timestamp_formats(self):
        loaded = loader.load_waterhub_archive(synthetic_zip(synthetic_members()), ["2018-06"])
        a, b, annotations = loaded.combined()
        self.assertEqual(list(a.columns), ["p1", "p2"])
        self.assertEqual(list(b.columns), ["p3", "p4"])
        self.assertEqual(a.index[0], pd.Timestamp("2018-06-03"))
        self.assertEqual(a.index.name, "timestamp")
        self.assertEqual(a.index.dtype, np.dtype("datetime64[ns]"))
        self.assertEqual(a.iloc[0].tolist(), [100, 200])
        for stream in LABEL_STREAMS:
            self.assertEqual(list(annotations[stream].columns), ["Anomaly"])
            self.assertEqual(annotations[stream].index[0], a.index[0])
        self.assertEqual(len(loaded.timestamp_ambiguity_mask), 0)
        self.assertFalse(loaded.metadata["whole_archive_sha256_verified_by_loader"])

    def test_member_hashes_cover_original_bytes_and_selected_columns(self):
        members = synthetic_members()
        loaded = loader.load_waterhub_archive(synthetic_zip(members), ["2018-06"])
        self.assertEqual(len(loaded.member_manifest), 8)
        for record in loaded.member_manifest:
            data = members[record["member"]]
            self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(record["uncompressed_bytes"], len(data))
            self.assertEqual(record["rows"], 12)
            self.assertEqual(record["combined_row_start"], 0)
            self.assertEqual(record["combined_row_end_exclusive"], 12)
            if record["kind"] == "annotation":
                self.assertEqual(record["parsed_columns"], ["day", "time", "Anomaly"])
                self.assertEqual(record["output_columns"], ["Anomaly"])

    def test_reader_uses_explicit_column_projection(self):
        original = pd.read_csv
        requests = []
        def spy(*args, **kwargs):
            requests.append(tuple(kwargs["usecols"]))
            return original(*args, **kwargs)
        with patch.object(loader.pd, "read_csv", side_effect=spy):
            loader.load_waterhub_archive(synthetic_zip(synthetic_members()), ["2018-06"])
        self.assertEqual(requests.count(("day", "time", "Anomaly")), 6)
        self.assertEqual(requests.count(("day", "hour", "p1", "p2")), 1)
        self.assertEqual(requests.count(("day", "hour", "p3", "p4")), 1)

    def test_rows_and_raw_duplicates_preserved_with_global_selected_mask(self):
        months = ["2018-07", "2018-06"]
        loaded = loader.load_waterhub_archive(
            synthetic_zip(synthetic_members(months, duplicate_raw=True)), months)
        self.assertEqual(list(loaded.monthly), ["2018-06", "2018-07"])
        a, b, _ = loaded.combined()
        self.assertEqual(len(a), 26)
        self.assertEqual(len(b), 26)
        self.assertEqual(a.index[12], a.index[2])
        self.assertEqual(a.index[25], a.index[15])
        self.assertEqual(list(loaded.timestamp_ambiguity_mask),
                         [pd.Timestamp("2018-06-03 00:00:20"), pd.Timestamp("2018-07-03 00:00:20")])
        self.assertEqual(loaded.metadata["raw_duplicate_timestamp_counts_by_process"],
                         {"T1_T2": 2, "GAK": 2})
        july = [r for r in loaded.member_manifest if r["month"] == "2018-07" and r["kind"] == "raw"]
        self.assertTrue(all(r["combined_row_start"] == 13 for r in july))

    def test_duplicate_labels_preserved_and_cannot_change_raw_ambiguity(self):
        first = loader.load_waterhub_archive(synthetic_zip(synthetic_members()), ["2018-06"])
        loaded = loader.load_waterhub_archive(
            synthetic_zip(synthetic_members(conflicting_label=True)), ["2018-06"])
        self.assertEqual(len(loaded.monthly["2018-06"].annotations["p1"]), 13)
        pd.testing.assert_index_equal(loaded.timestamp_ambiguity_mask, first.timestamp_ambiguity_mask)
        pd.testing.assert_frame_equal(loaded.combined().raw_t1_t2, first.combined().raw_t1_t2)
        a, b, labels = loaded.combined()
        adapted = adapt_waterhub(a, b, labels, timestamp_ambiguity_mask=loaded.timestamp_ambiguity_mask)
        np.testing.assert_array_equal(adapted.labels, [-1, 1])
        self.assertTrue(adapted.audit.feature_available.all())

    def test_august_is_raw_data_with_unknown_labels_and_no_fabricated_negatives(self):
        loaded = loader.load_waterhub_archive(
            synthetic_zip(synthetic_members(["2018-08"])), ["2018-08"])
        a, b, labels = loaded.combined()
        self.assertEqual(len(a), 12)
        self.assertTrue(all(frame.empty for frame in labels.values()))
        adapted = adapt_waterhub(a, b, labels)
        np.testing.assert_array_equal(adapted.labels, [-1, -1])
        self.assertTrue(adapted.audit.feature_available.all())
        self.assertEqual(loaded.metadata["unlabelled_months_retained"], ["2018-08"])

    def test_default_entire_calendar_loads_synthetic_inputs_only(self):
        members = synthetic_members(loader.DEFAULT_MONTHS, row_count=1)
        loaded = loader.load_waterhub_archive(synthetic_zip(members))
        a, b, labels = loaded.combined()
        self.assertEqual(len(a), 11)
        self.assertEqual(len(b), 11)
        self.assertTrue(all(len(frame) == 10 for frame in labels.values()))
        self.assertEqual(len(loaded.member_manifest), 82)

    def test_unselected_payloads_may_not_be_opened(self):
        members = synthetic_members()
        forbidden = [
            "ADASen_paper/data/04_WaterHub/data_processed/NEST_Anomaly_collective",
            f"{loader.PROCESS_DIRECTORIES['T1_T2']}/17_May 2019.csv",
            "ADASen_paper/data/03_Ponds/not_selected.csv",
        ]
        for name in forbidden:
            members[name] = b"This payload must never be read or unpickled."
        with zipfile.ZipFile(synthetic_zip(members)) as archive:
            original = archive.open
            opened = []
            def guarded(name, *args, **kwargs):
                member = name.filename if isinstance(name, zipfile.ZipInfo) else name
                self.assertNotIn(member, forbidden)
                opened.append(member)
                return original(name, *args, **kwargs)
            with patch.object(archive, "open", side_effect=guarded):
                loaded = loader.load_waterhub_archive(archive, ["2018-06"])
            self.assertIsNotNone(archive.fp)  # Caller-owned ZipFile remains open.
        self.assertEqual(len(opened), len(loaded.member_manifest))
        self.assertEqual(set(opened), set(members) - set(forbidden))

    def test_missing_required_or_duplicate_member_name_fails_before_body_read(self):
        members = synthetic_members()
        selected = next(iter(members))
        missing = dict(members)
        del missing[selected]
        for source in (synthetic_zip(missing), synthetic_zip(members, duplicates=[selected])):
            with self.subTest(source=source):
                with zipfile.ZipFile(source) as archive:
                    with patch.object(archive, "read", side_effect=AssertionError("body opened")):
                        with self.assertRaises(ValueError):
                            loader.load_waterhub_archive(archive, ["2018-06"])

    def test_expected_sha_verification_and_failure_before_csv_parsing(self):
        members = synthetic_members()
        expected = {name: hashlib.sha256(data).hexdigest() for name, data in members.items()}
        loaded = loader.load_waterhub_archive(synthetic_zip(members), ["2018-06"],
                                              expected_member_sha256=expected)
        self.assertTrue(loaded.metadata["member_sha256_verified_against_expected"])
        expected[next(iter(expected))] = "0" * 64
        with patch.object(loader, "_parse_member", side_effect=AssertionError("parsed before SHA check")):
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                loader.load_waterhub_archive(synthetic_zip(members), ["2018-06"],
                                              expected_member_sha256=expected)
        with self.assertRaises(ValueError):
            loader.load_waterhub_archive(synthetic_zip(members), ["2018-06"],
                                          expected_member_sha256={})

    def test_raw_numeric_missing_invalid_and_infinite_values_are_not_filled(self):
        members = synthetic_members()
        name = next(s["member"] for s in loader.waterhub_member_plan(["2018-06"])
                    if s["kind"] == "raw" and s["stream"] == "T1_T2")
        def mutate(rows):
            rows[0]["p1"] = ""
            rows[1]["p1"] = "invalid"
            rows[2]["p1"] = "inf"
        members[name] = rewrite_csv(members[name], mutate)
        loaded = loader.load_waterhub_archive(synthetic_zip(members), ["2018-06"])
        a = loaded.combined().raw_t1_t2
        self.assertTrue(np.isnan(a.p1.iloc[0]))
        self.assertTrue(np.isnan(a.p1.iloc[1]))
        self.assertTrue(np.isinf(a.p1.iloc[2]))
        self.assertEqual(len(a), 12)

    def test_invalid_annotation_value_is_preserved_as_unknown_for_adapter(self):
        members = synthetic_members()
        name = next(s["member"] for s in loader.waterhub_member_plan(["2018-06"])
                    if s["kind"] == "annotation" and s["stream"] == "p1")
        members[name] = rewrite_csv(members[name], lambda rows: rows[0].update(Anomaly="invalid"))
        loaded = loader.load_waterhub_archive(synthetic_zip(members), ["2018-06"])
        a, b, labels = loaded.combined()
        self.assertTrue(np.isnan(labels["p1"].Anomaly.iloc[0]))
        self.assertEqual(adapt_waterhub(a, b, labels).labels.iloc[0], -1)

    def test_bad_header_wrong_month_and_ambiguous_date_format_fail(self):
        original = synthetic_members()
        name = next(iter(original))
        mutations = [
            lambda value: value.replace(b"day,hour", b"date,hour", 1),
            lambda value: rewrite_csv(value, lambda rows: rows[0].update(day="03.07.2018")),
            lambda value: rewrite_csv(value, lambda rows: rows[0].update(day="2018-06-03")),
        ]
        for mutate in mutations:
            members = dict(original)
            members[name] = mutate(members[name])
            with self.subTest(mutate=mutate):
                with self.assertRaises(ValueError):
                    loader.load_waterhub_archive(synthetic_zip(members), ["2018-06"])

    def test_header_only_members_remain_empty_not_fabricated(self):
        loaded = loader.load_waterhub_archive(
            synthetic_zip(synthetic_members(row_count=0)), ["2018-06"])
        a, b, labels = loaded.combined()
        self.assertTrue(a.empty and b.empty)
        self.assertTrue(all(frame.empty for frame in labels.values()))
        self.assertEqual(len(loaded.timestamp_ambiguity_mask), 0)

    def test_scope_validation_is_before_opening_any_archive(self):
        for months in ([], ["2019-05"], ["2018-06", "2018-06"], "2018-06", [201806]):
            with self.subTest(months=months):
                with patch.object(loader.zipfile, "ZipFile", side_effect=AssertionError("archive opened")):
                    with self.assertRaises(ValueError):
                        loader.load_waterhub_archive("not a real archive", months)


if __name__ == "__main__":
    unittest.main()
