"""Synthetic-only ZIP fixtures; this suite never opens the real source archive."""
import csv
from contextlib import ExitStack
import hashlib
import importlib
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import pandas as pd

from ml.gecco_v7_sources import uwo_s1 as m


class UwoS1Test(unittest.TestCase):
    def fixture(self, start="2018-03-25 00:00:00", end="2018-03-27 12:00:00", *, selected=None,
                raw_times=None, raw_values=None, copied="not-a-numeric-feature"):
        index = pd.date_range(start, end, freq="5min")
        times = list(index if raw_times is None else raw_times)
        values = [[str(i), "2.0", "3.0"] for i in range(len(times))] if raw_values is None else raw_values

        def encode(header, rows):
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
            return buffer.getvalue().encode()

        data = {m.RAW_MEMBER: encode(["time", *m.CHANNELS],
                                   [[str(t), *v] for t, v in zip(times, values)])}
        selected = selected or {}
        for stream in m.LABEL_STREAMS:
            rows = []
            for i, t in enumerate(selected.get(stream, [])):
                stamp = pd.Timestamp(t)
                copies = [copied] * (3 if stream == m.LABEL_STREAMS[-1] else 1)
                rows.append([i, stamp.strftime("%Y-%m-%d"), stamp.strftime("%H:%M:%S"), *copies])
            header = ["", "date", "time", *(m.CHANNELS if stream == m.LABEL_STREAMS[-1] else ("value",))]
            data[m.ANNOTATION_MEMBERS[stream]] = encode(header, rows)
        return data, start, end

    def run_fixture(self, fixture, *, omitted=(), added=(), hashes=None):
        data, start, end = fixture
        expected_hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in data.items()}
        if hashes is not None:
            expected_hashes = hashes
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            for name, payload in data.items():
                if name not in omitted:
                    z.writestr(name, payload)
            for name, payload in added:
                z.writestr(name, payload)
        archive.seek(0)
        with ExitStack() as stack:
            stack.enter_context(patch.object(m, "EXPECTED_MEMBER_SHA256", expected_hashes))
            stack.enter_context(patch.object(m, "SOURCE_START", start))
            stack.enter_context(patch.object(m, "SOURCE_END", end))
            return m.load_uwo_s1(archive, protocol_frozen=True, coverage_contract=dict(m.COVERAGE_CONTRACT))

    def assert_failure(self, fixture, code, **kwargs):
        with self.assertRaises(m.UwoS1QualificationError) as caught:
            self.run_fixture(fixture, **kwargs)
        self.assertEqual(caught.exception.audit["error_code"], code)

    def test_freeze_guard_precedes_any_archive_access(self):
        with patch.object(m, "_open_archive", side_effect=AssertionError("must not open")):
            for value in (False, None, 1, "yes"):
                with self.subTest(value=value), self.assertRaises(m.UwoS1QualificationError) as caught:
                    m.load_uwo_s1("never-open.zip", protocol_frozen=value)
                self.assertEqual(caught.exception.audit["error_code"], "protocol_not_frozen")

    def test_import_and_plan_have_no_archive_io(self):
        with patch.object(zipfile, "ZipFile", side_effect=AssertionError("archive opened")):
            importlib.reload(m)
            self.assertEqual(len(m.uwo_s1_member_plan()), 4)

    def test_explicit_exact_coverage_contract_precedes_archive_access(self):
        changed = dict(m.COVERAGE_CONTRACT, annotation_start_date="2018-03-06")
        with patch.object(m, "_open_archive", side_effect=AssertionError("must not open")):
            for value in (None, {}, changed, {**m.COVERAGE_CONTRACT, "extra": True}):
                with self.subTest(value=value), self.assertRaises(m.UwoS1QualificationError) as caught:
                    m.load_uwo_s1("never-open.zip", protocol_frozen=True, coverage_contract=value)
                self.assertEqual(caught.exception.audit["error_code"], "coverage_contract")

    def test_sparse_union_exact_three_streams(self):
        points = [pd.Timestamp("2018-03-26 01:00:00") + pd.Timedelta(minutes=5*i) for i in range(3)]
        result = self.run_fixture(self.fixture(selected=dict(zip(m.LABEL_STREAMS, [[t] for t in points]))))
        for point in points:
            self.assertEqual(result.labels[result.features.index.get_loc(point)], 1)
        self.assertEqual(np.count_nonzero(result.labels == 1), 3)
        self.assertEqual(result.labels[result.features.index.get_loc("2018-03-26 00:00:00")], 0)
        self.assertEqual(result.features.columns.tolist(), list(m.CHANNELS))
        self.assertEqual(result.labels.dtype, np.int8)

    def test_unproven_early_days_and_partial_days_are_unknown(self):
        selected = {m.LABEL_STREAMS[0]: ["2018-03-25 01:00:00", "2018-03-27 01:00:00"]}
        result = self.run_fixture(self.fixture(selected=selected))
        dates = result.features.index.strftime("%Y-%m-%d")
        self.assertTrue(np.all(result.labels[dates == "2018-03-25"] == -1))
        self.assertTrue(np.all(result.labels[dates == "2018-03-27"] == -1))
        self.assertTrue(np.all(result.labels[dates == "2018-03-26"] == 0))
        self.assertEqual(result.audit["streams"][m.LABEL_STREAMS[0]]["selected_timestamps_outside_annotatable_calendar"], 2)
        self.assertTrue(np.isfinite(result.features.to_numpy()).all())

    def test_exact_192_row_day_is_included(self):
        result = self.run_fixture(self.fixture("2018-03-26 00:00:00", "2018-03-26 15:55:00"))
        self.assertEqual(len(result.labels), 192)
        self.assertTrue(np.all(result.labels == 0))
        smaller = self.run_fixture(self.fixture("2018-03-26 00:00:00", "2018-03-26 15:50:00"))
        self.assertTrue(np.all(smaller.labels == -1))

    def test_pinned_full_axis_synthetic_rows_year_and_day_accounting(self):
        result = self.run_fixture(self.fixture(m.SOURCE_START, m.SOURCE_END))
        self.assertEqual(len(result.labels), 14545)
        self.assertEqual(np.count_nonzero(result.labels == 0), 30 * 288)
        self.assertEqual(np.count_nonzero(result.labels == -1), 20 * 288 + 145)
        self.assertEqual(result.features.index.year.unique().tolist(), [2018])
        self.assertTrue(np.isfinite(result.features.iloc[-145:].to_numpy()).all())
        self.assertEqual(result.audit["cadence_seconds"], 300)

    def test_annotations_and_copied_values_cannot_change_features(self):
        a = self.run_fixture(self.fixture())
        b = self.run_fixture(self.fixture(selected={m.LABEL_STREAMS[-1]: ["2018-03-26 05:00:00"]},
                                          copied="NaN,garbage,999999"))
        pd.testing.assert_frame_equal(a.features, b.features)
        self.assertNotEqual(a.labels.tolist(), b.labels.tolist())

    def test_duplicate_sparse_selections_are_idempotent(self):
        selected = {m.LABEL_STREAMS[0]: ["2018-03-26 02:00:00"] * 3}
        result = self.run_fixture(self.fixture(selected=selected))
        self.assertEqual(np.count_nonzero(result.labels == 1), 1)
        self.assertEqual(result.audit["streams"][m.LABEL_STREAMS[0]]["duplicate_selected_rows"], 2)

    def test_missing_measurements_do_not_erase_positive_or_normal_labels(self):
        fixture = self.fixture(selected={m.LABEL_STREAMS[0]: ["2018-03-26 01:00:00"]})
        data, start, end = fixture
        lines = data[m.RAW_MEMBER].decode().splitlines()
        lines[301] = "2018-03-26 01:00:00,NaN,inf,-inf"
        lines[302] = "2018-03-26 01:05:00,,NA,null"
        data[m.RAW_MEMBER] = ("\n".join(lines) + "\n").encode()
        result = self.run_fixture((data, start, end))
        self.assertTrue(result.features.iloc[300:302].isna().all().all())
        np.testing.assert_array_equal(result.labels[300:302], [1, 0])
        self.assertTrue(np.isfinite(result.features.iloc[302:].to_numpy()).all())

    def test_missing_required_annotation_member_fails(self):
        self.assert_failure(self.fixture(), "member_set", omitted=[m.ANNOTATION_MEMBERS[m.LABEL_STREAMS[0]]])

    def test_duplicate_zip_member_fails(self):
        fixture = self.fixture()
        with self.assertWarns(UserWarning):
            self.assert_failure(fixture, "member_set", added=[(m.RAW_MEMBER, fixture[0][m.RAW_MEMBER])])

    def test_hash_mismatch_precedes_csv_parsing(self):
        fixture = self.fixture()
        with patch.object(m, "_rows", side_effect=AssertionError("must not parse")):
            self.assert_failure(fixture, "member_hash", hashes={name: "0" * 64 for name in fixture[0]})

    def test_extra_unselected_payload_is_not_read(self):
        fixture = self.fixture()
        original = zipfile.ZipFile.read
        opened = []
        def read(z, name, *args, **kwargs):
            opened.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
            return original(z, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "read", read):
            result = self.run_fixture(fixture, added=[("unselected.pkl", b"do not unpickle or read")])
        self.assertEqual(set(opened), set(fixture[0]))
        self.assertEqual(len(result.member_manifest), 4)

    def test_raw_duplicates_gaps_reordering_and_wrong_year_fail(self):
        base = pd.date_range("2018-03-26", periods=288, freq="5min")
        for times, code in [(list(base[:10]) + [base[9]] + list(base[10:]), "raw_duplicate_timestamp"),
                            (list(base[:10]) + list(base[11:]), "raw_axis"),
                            (list(base[::-1]), "raw_axis"),
                            ([t.replace(year=2017) for t in base], "raw_axis")]:
            with self.subTest(code=code):
                self.assert_failure(self.fixture(str(base[0]), str(base[-1]), raw_times=times), code)

    def test_annotation_offgrid_outside_and_wrong_year_fail(self):
        for timestamp in ["2018-03-26 01:01:00", "2018-03-28 00:00:00", "2017-03-26 01:00:00"]:
            with self.subTest(timestamp=timestamp):
                self.assert_failure(self.fixture(selected={m.LABEL_STREAMS[0]: [timestamp]}), "annotation_unmapped")

    def test_malformed_timestamp_invalid_numeric_header_and_row_width(self):
        edits = [
            (lambda s: s.replace("2018-03-25 00:00:00", "2018-03-25T00:00:00"), "timestamp_invalid"),
            (lambda s: s.replace(",0,2.0,3.0", ",invalid,2.0,3.0"), "measurement_invalid"),
            (lambda s: s.replace("time,bf_03", "timestamp,bf_03"), "header_mismatch"),
            (lambda s: s.replace(",0,2.0,3.0", ",0,2.0,3.0,extra"), "row_width"),
        ]
        for change, code in edits:
            data, start, end = self.fixture()
            data[m.RAW_MEMBER] = change(data[m.RAW_MEMBER].decode()).encode()
            with self.subTest(code=code):
                self.assert_failure((data, start, end), code)

    def test_future_measurement_mutation_does_not_change_prefix(self):
        fixture = self.fixture()
        before = self.run_fixture(fixture)
        data, start, end = fixture
        lines = data[m.RAW_MEMBER].decode().splitlines()
        for i in range(501, len(lines)):
            stamp = lines[i].split(",", 1)[0]
            lines[i] = stamp + ",999,-999,0"
        data[m.RAW_MEMBER] = ("\n".join(lines) + "\n").encode()
        after = self.run_fixture((data, start, end))
        pd.testing.assert_frame_equal(before.features.iloc[:500], after.features.iloc[:500])
        np.testing.assert_array_equal(before.labels, after.labels)

    def test_default_member_pins_match_saved_metadata_without_source_access(self):
        metadata = Path(__file__).resolve().parents[2] / "output/ml/gecco-v7-source-search/uwo_s1_adapter_spec.json"
        # Static metadata only; no source archive or source row is read.
        import json
        spec = json.loads(metadata.read_text())["source"]
        expected = {entry["member"]: entry["sha256"]
                    for entry in [spec["provided_measurement_member"], *spec["annotation_members"]]}
        self.assertEqual(dict(m.EXPECTED_MEMBER_SHA256), expected)


if __name__ == "__main__":
    unittest.main()
