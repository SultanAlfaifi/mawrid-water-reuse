"""Synthetic-only adapter tests. No measured source or archived label is opened."""
import copy
import unittest

import numpy as np
import pandas as pd

from waterhub_adapter import (
    CHANNELS, LABEL_STREAMS, RAW_AUDIT_COLUMNS, adapt_waterhub,
)


def synthetic(minutes=5, start="2020-01-01 00:00:00"):
    times = pd.date_range(start, periods=minutes * 6, freq="10s")
    values = np.arange(len(times), dtype=float)
    a = pd.DataFrame({"p1": values + 1, "p2": values + 101}, index=times)
    b = pd.DataFrame({"p3": values + 201, "p4": values + 301}, index=times)
    annotations = {name: pd.DataFrame({"Anomaly": np.zeros(len(times), dtype=int)},
                                       index=times) for name in LABEL_STREAMS}
    return a, b, annotations


class WaterHubAdapterTests(unittest.TestCase):
    def test_minute_end_exact_last_sample_and_known_zero_labels(self):
        a, b, labels = synthetic(3)
        result = adapt_waterhub(a, b, labels)
        expected = pd.concat([a, b], axis=1).iloc[5::6].copy()
        expected.index = pd.date_range("2020-01-01 00:01", periods=3, freq="min",
                                       name="minute_end").as_unit("ns")
        pd.testing.assert_frame_equal(result.features, expected)
        np.testing.assert_array_equal(result.labels, [0, 0, 0])
        self.assertTrue(result.audit.feature_available.all())
        self.assertTrue(result.audit.label_available.all())
        self.assertTrue((result.audit.known_annotation_slots == 36).all())
        self.assertEqual(result.metadata["cadence_seconds"], 60)
        self.assertEqual(len(result.frame), 3)

    def test_each_of_six_streams_can_supply_a_minute_positive(self):
        for stream in LABEL_STREAMS:
            with self.subTest(stream=stream):
                a, b, labels = synthetic(2)
                labels[stream].iloc[0, 0] = 1  # No need to overlap the :50 sample.
                np.testing.assert_array_equal(adapt_waterhub(a, b, labels).labels, [1, 0])

    def test_all_36_labels_required_even_when_another_known_label_is_positive(self):
        a, b, labels = synthetic(2)
        labels["p1"].iloc[0, 0] = 1
        labels["p4"] = labels["p4"].drop(labels["p4"].index[1])
        result = adapt_waterhub(a, b, labels)
        self.assertEqual(result.labels.iloc[0], -1)
        self.assertEqual(result.audit.known_annotation_slots.iloc[0], 35)
        self.assertTrue(result.audit.annotation_missing_timestamp.iloc[0])
        self.assertTrue(result.audit.feature_available.all())

    def test_agreeing_annotation_duplicates_collapse_order_independently(self):
        a, b, labels = synthetic(2)
        labels["p1"].iloc[1, 0] = 1
        expected = adapt_waterhub(a, b, labels)
        labels["p1"] = pd.concat([labels["p1"], labels["p1"].iloc[[1]]])
        result = adapt_waterhub(a, b, labels)
        pd.testing.assert_series_equal(result.labels, expected.labels)
        self.assertTrue(result.audit.annotation_duplicate_timestamp.iloc[0])
        labels["p1"] = labels["p1"].iloc[::-1]
        pd.testing.assert_series_equal(adapt_waterhub(a, b, labels).labels, result.labels)

    def test_conflicting_annotation_duplicate_is_unknown_not_first_or_max(self):
        a, b, labels = synthetic(2)
        extra = labels["p1"].iloc[[0]].copy()
        extra["Anomaly"] = 1
        labels["p1"] = pd.concat([labels["p1"], extra])
        result = adapt_waterhub(a, b, labels)
        np.testing.assert_array_equal(result.labels, [-1, 0])
        self.assertTrue(result.audit.annotation_ambiguous_value.iloc[0])
        self.assertTrue(result.audit.feature_available.all())

    def test_invalid_annotation_values_and_invalid_duplicates_are_unknown(self):
        for invalid in (np.nan, np.inf, -np.inf, 2, -1, "invalid"):
            with self.subTest(invalid=invalid):
                a, b, labels = synthetic(2)
                labels["p1"]["Anomaly"] = labels["p1"]["Anomaly"].astype(object)
                labels["p1"].iloc[0, 0] = invalid
                result = adapt_waterhub(a, b, labels)
                self.assertEqual(result.labels.iloc[0], -1)
                self.assertTrue(result.audit.annotation_ambiguous_value.iloc[0])
                a, b, labels = synthetic(2)
                extra = pd.DataFrame({"Anomaly": [invalid]}, index=labels["p1"].index[:1])
                labels["p1"] = pd.concat([labels["p1"], extra])
                self.assertEqual(adapt_waterhub(a, b, labels).labels.iloc[0], -1)

    def test_missing_raw_slot_preserves_known_positive_and_full_grid(self):
        a, b, labels = synthetic(3)
        labels["p1"].iloc[6, 0] = 1
        a = a.drop(a.index[7])
        result = adapt_waterhub(a, b, labels)
        self.assertEqual(len(result.features), 3)
        self.assertTrue(result.features.iloc[1].isna().all())
        self.assertEqual(result.labels.iloc[1], 1)
        self.assertTrue(result.audit.raw_missing_timestamp.iloc[1])
        self.assertTrue(result.audit.raw_process_mismatch.iloc[1])

    def test_entire_raw_gap_keeps_labelled_event_and_does_not_shift_time(self):
        a, b, labels = synthetic(4)
        labels["p3p4"].iloc[6:12, 0] = 1
        a, b = a.drop(a.index[6:12]), b.drop(b.index[6:12])
        result = adapt_waterhub(a, b, labels)
        np.testing.assert_array_equal(result.labels, [0, 1, 0, 0])
        np.testing.assert_array_equal(result.audit.feature_available, [1, 0, 1, 1])
        self.assertFalse(result.audit.raw_process_mismatch.any())

    def test_raw_duplicate_invalidates_minute_without_averaging(self):
        a, b, labels = synthetic(3)
        extra = a.iloc[[2]].copy()
        extra["p1"] = 1e12
        a = pd.concat([a, extra])
        result = adapt_waterhub(a, b, labels)
        self.assertTrue(result.audit.raw_duplicate_timestamp.iloc[0])
        self.assertFalse(result.audit.feature_available.iloc[0])
        self.assertTrue(result.features.iloc[0].isna().all())
        self.assertEqual(result.labels.iloc[0], 0)

    def test_missing_and_nonfinite_selected_readings_have_distinct_reasons(self):
        a, b, labels = synthetic(3)
        a.iloc[5, 0] = np.inf
        a = a.drop(a.index[11])
        result = adapt_waterhub(a, b, labels)
        np.testing.assert_array_equal(result.audit.feature_available, [0, 0, 1])
        np.testing.assert_array_equal(result.audit.nonfinite_selected_pressure, [1, 0, 0])
        np.testing.assert_array_equal(result.audit.raw_missing_timestamp, [0, 1, 0])

    def test_earlier_pressure_values_are_never_used_for_last_value_features(self):
        a, b, labels = synthetic(4)
        expected = adapt_waterhub(a, b, labels)
        nonselected = np.arange(len(a)) % 6 != 5
        a.loc[nonselected, :] = np.inf
        b.loc[nonselected, :] = np.nan
        result = adapt_waterhub(a, b, labels)
        pd.testing.assert_frame_equal(result.features, expected.features)
        pd.testing.assert_frame_equal(result.audit[list(RAW_AUDIT_COLUMNS)],
                                      expected.audit[list(RAW_AUDIT_COLUMNS)])

    def test_annotation_values_columns_missingness_and_extent_cannot_change_features(self):
        a, b, labels = synthetic(3)
        expected = adapt_waterhub(a, b, labels)
        for stream in LABEL_STREAMS:
            labels[stream]["Anomaly"] = np.nan
            for channel in CHANNELS:
                labels[stream][channel] = "never a feature"
            labels[stream] = pd.concat([labels[stream], labels[stream].iloc[[0]]])
            labels[stream].index = labels[stream].index + pd.Timedelta(days=700)
        result = adapt_waterhub(a, b, labels)
        pd.testing.assert_frame_equal(result.features, expected.features)
        pd.testing.assert_frame_equal(result.audit[list(RAW_AUDIT_COLUMNS)],
                                      expected.audit[list(RAW_AUDIT_COLUMNS)])
        self.assertTrue((result.labels == -1).all())

    def test_unlabelled_time_retained_as_unknown_and_not_normal(self):
        a, b, labels = synthetic(4, "2020-07-31 23:58:00")
        labels = {name: frame.iloc[:12].copy() for name, frame in labels.items()}
        result = adapt_waterhub(a, b, labels)
        np.testing.assert_array_equal(result.labels, [0, 0, -1, -1])
        self.assertTrue(result.audit.feature_available.all())
        self.assertEqual(result.metadata["label_known_minutes"], 2)

    def test_prefix_parity_for_closed_minutes_with_same_frozen_mask(self):
        a, b, labels = synthetic(8)
        frozen = pd.DatetimeIndex([a.index[7]])
        whole = adapt_waterhub(a, b, labels, timestamp_ambiguity_mask=frozen)
        for cut in (1, 5, 6, 7, 13, 24, 47, 48):
            with self.subTest(cut=cut):
                prefix = adapt_waterhub(a.iloc[:cut], b.iloc[:cut],
                                        {k: v.iloc[:cut] for k, v in labels.items()},
                                        timestamp_ambiguity_mask=frozen)
                closed = cut // 6
                pd.testing.assert_frame_equal(prefix.features.iloc[:closed],
                                              whole.features.iloc[:closed])
                pd.testing.assert_series_equal(prefix.labels.iloc[:closed],
                                               whole.labels.iloc[:closed])

    def test_late_repeated_clock_requires_frozen_mask_for_prefix_parity(self):
        a, b, labels = synthetic(4)
        repeated_time = a.index[2]
        frozen = pd.Series([True, False], index=[repeated_time, a.index[14]])
        prefix = adapt_waterhub(a, b, labels, timestamp_ambiguity_mask=frozen)
        a = pd.concat([a, a.iloc[[2]]])
        b = pd.concat([b, b.iloc[[2]]])
        whole = adapt_waterhub(a, b, labels, timestamp_ambiguity_mask=frozen)
        pd.testing.assert_frame_equal(prefix.features, whole.features)
        pd.testing.assert_series_equal(prefix.audit.feature_available,
                                       whole.audit.feature_available)
        self.assertTrue(prefix.audit.fixed_clock_ambiguity.iloc[0])
        self.assertFalse(prefix.audit.raw_duplicate_timestamp.iloc[0])
        self.assertTrue(whole.audit.raw_duplicate_timestamp.iloc[0])

    def test_future_pressure_and_label_mutation_cannot_change_past_features(self):
        a, b, labels = synthetic(8)
        expected = adapt_waterhub(a, b, labels)
        a.iloc[18:, :] = -1e20
        b.iloc[18:, :] = np.nan
        for frame in labels.values():
            frame.iloc[18:, 0] = 1
        result = adapt_waterhub(a, b, labels)
        pd.testing.assert_frame_equal(result.features.iloc[:3], expected.features.iloc[:3])
        pd.testing.assert_series_equal(result.labels.iloc[:3], expected.labels.iloc[:3])

    def test_partial_boundaries_retained_and_marked(self):
        a, b, labels = synthetic(4)
        result = adapt_waterhub(a.iloc[1:-1], b.iloc[1:-1], labels)
        self.assertEqual(len(result.features), 4)
        np.testing.assert_array_equal(result.audit.feature_available, [0, 1, 1, 0])
        np.testing.assert_array_equal(result.audit.partial_boundary_minute, [1, 0, 0, 1])

    def test_empty_input_with_explicit_grid_preserves_known_labels(self):
        a, b, labels = synthetic(3)
        labels["p1"].iloc[0, 0] = 1
        result = adapt_waterhub(a.iloc[:0], b.iloc[:0], labels,
                                grid_start="2020-01-01", grid_end="2020-01-01 00:02")
        self.assertTrue(result.features.isna().all().all())
        np.testing.assert_array_equal(result.labels, [1, 0, 0])

    def test_all_empty_input_is_well_typed(self):
        a, b, labels = synthetic(0)
        result = adapt_waterhub(a, b, labels)
        self.assertEqual(len(result.features), 0)
        self.assertEqual(list(result.features.columns), list(CHANNELS))
        self.assertEqual(result.labels.dtype, np.int8)
        self.assertEqual(result.audit.feature_available.dtype, bool)
        self.assertEqual(result.audit.label_available.dtype, bool)

    def test_source_formats_and_timestamp_column_match_datetime_index(self):
        a, b, labels = synthetic(3)
        expected = adapt_waterhub(a, b, labels)
        for frame in (a, b):
            frame["day"] = frame.index.strftime("%d.%m.%Y")
            frame["hour"] = frame.index.strftime("%H:%M:%S")
            frame.reset_index(drop=True, inplace=True)
        for frame in labels.values():
            frame["day"] = frame.index.strftime("%Y-%m-%d")
            frame["time"] = frame.index.strftime("%H:%M:%S")
            frame.reset_index(drop=True, inplace=True)
        result = adapt_waterhub(a, b, labels)
        pd.testing.assert_frame_equal(result.features, expected.features)
        pd.testing.assert_series_equal(result.labels, expected.labels)
        a, b, labels = synthetic(3)
        a = a.rename_axis("timestamp").reset_index()
        b = b.rename_axis("timestamp").reset_index()
        pd.testing.assert_frame_equal(adapt_waterhub(a, b, labels).features, expected.features)

    def test_off_grid_raw_and_annotation_times_affect_only_relevant_path(self):
        a, b, labels = synthetic(3)
        extra = a.iloc[[0]].copy()
        extra.index += pd.Timedelta(seconds=1)
        a = pd.concat([a, extra])
        extra_label = labels["p1"].iloc[[6]].copy()
        extra_label.index += pd.Timedelta(seconds=1)
        labels["p1"] = pd.concat([labels["p1"], extra_label])
        result = adapt_waterhub(a, b, labels)
        np.testing.assert_array_equal(result.audit.feature_available, [0, 1, 1])
        np.testing.assert_array_equal(result.labels, [0, -1, 0])
        self.assertTrue(result.audit.raw_off_grid_timestamp.iloc[0])
        self.assertTrue(result.audit.annotation_off_grid_timestamp.iloc[1])

    def test_inputs_are_not_mutated(self):
        a, b, labels = synthetic(3)
        prior_a, prior_b, prior_labels = a.copy(), b.copy(), copy.deepcopy(labels)
        adapt_waterhub(a, b, labels)
        pd.testing.assert_frame_equal(a, prior_a)
        pd.testing.assert_frame_equal(b, prior_b)
        for stream in LABEL_STREAMS:
            pd.testing.assert_frame_equal(labels[stream], prior_labels[stream])

    def test_invalid_schema_and_configuration_fail_explicitly(self):
        a, b, labels = synthetic(2)
        with self.assertRaises(ValueError):
            adapt_waterhub(a.drop(columns="p1"), b, labels)
        with self.assertRaises(ValueError):
            adapt_waterhub(a, b, {k: v for k, v in labels.items() if k != "p1"})
        with self.assertRaises(ValueError):
            adapt_waterhub(a, b, labels, grid_start="2020-01-01 00:00:01")
        with self.assertRaises(ValueError):
            adapt_waterhub(a, b, labels, grid_start="2020-01-02", grid_end="2020-01-01")
        with self.assertRaises(ValueError):
            adapt_waterhub(a, b, labels, timestamp_ambiguity_mask=pd.Series([1], index=a.index[:1]))
        with self.assertRaises(TypeError):
            adapt_waterhub("not-a-source-path", b, labels)
        a.index = a.index.tz_localize("UTC")
        with self.assertRaises(ValueError):
            adapt_waterhub(a, b, labels)


if __name__ == "__main__":
    unittest.main()
