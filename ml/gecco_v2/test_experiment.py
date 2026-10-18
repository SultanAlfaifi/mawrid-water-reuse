"""Runner checks using synthetic frames only; no benchmark labels are opened."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import run_experiment as runner
from candidates_supervised import CHANNELS, build_features
from run_baseline import feature_frame as original_feature_frame


def synthetic_frame(length):
    rng = np.random.default_rng(781)
    frame = pd.DataFrame(rng.normal(size=(length, len(CHANNELS))), columns=CHANNELS)
    frame["EVENT"] = False
    frame["source_index"] = np.arange(length)
    frame["Time"] = pd.date_range("2020-01-01", periods=length, freq="min").astype(str)
    return frame


class BaselineParityTests(unittest.TestCase):
    def test_original_v1_feature_order_values_and_missing_eligibility(self):
        frame = synthetic_frame(180)
        frame.loc[40, "Tp"] = np.nan
        frame.loc[99, "Cl"] = np.inf
        expected, expected_eligible, _ = original_feature_frame(frame)
        actual, eligible, names = build_features(frame, "baseline15", CHANNELS)
        self.assertEqual(names, expected.columns.tolist())
        np.testing.assert_allclose(actual, expected.to_numpy(), equal_nan=True, rtol=0, atol=0)
        np.testing.assert_array_equal(eligible, expected_eligible)

    def test_refitted_baseline_excludes_all_windows_overlapping_event(self):
        frame = synthetic_frame(180)
        frame.loc[65:69, "EVENT"] = True
        # First feature directly identifies each fitted observation's source row.
        frame["Tp"] = np.arange(len(frame), dtype=float)
        captured = {}

        class FakeForest:
            def __init__(self, **kwargs):
                captured["parameters"] = kwargs

            def fit(self, values):
                captured["rows"] = values[:, 0].astype(int)
                return self

        with patch.object(runner, "IsolationForest", FakeForest):
            _, metadata = runner.fit_candidate("baseline", frame, CHANNELS)
        fitted_rows = captured["rows"]
        self.assertTrue(np.all(fitted_rows >= 14))
        self.assertFalse(np.isin(fitted_rows, np.arange(65, 84)).any())
        self.assertIn(64, fitted_rows)
        self.assertIn(84, fitted_rows)
        self.assertEqual(metadata["fit_rows"], len(fitted_rows))
        self.assertEqual(captured["parameters"]["n_estimators"], 200)
        self.assertEqual(captured["parameters"]["max_samples"], 256)


class PredictorIsolationTests(unittest.TestCase):
    def test_unsupervised_score_never_receives_event_or_identifiers(self):
        frame = synthetic_frame(150)
        seen = []

        class Spy:
            def score(self, channels):
                seen.append(channels.columns.tolist())
                return np.arange(len(channels), dtype=float)

        original = runner.scores_for("if_normalized_changes_w30", Spy(), frame, CHANNELS)
        frame["EVENT"] = True
        frame["source_index"] = -1000
        changed = runner.scores_for("if_normalized_changes_w30", Spy(), frame, CHANNELS)
        self.assertEqual(seen, [CHANNELS, CHANNELS])
        np.testing.assert_array_equal(original, changed)

    def test_supervised_score_is_invariant_to_event_labels(self):
        frame = synthetic_frame(150)

        class Spy:
            classes_ = np.array([0, 1])

            def predict_proba(self, features):
                self.feature_count = features.shape[1]
                positive = 1 / (1 + np.exp(-features[:, 0]))
                return np.column_stack([1 - positive, positive])

        model = Spy()
        original = runner.scores_for("extra_trees", model, frame, CHANNELS)
        frame["EVENT"] = True
        changed = runner.scores_for("extra_trees", model, frame, CHANNELS)
        self.assertEqual(model.feature_count, 54)
        np.testing.assert_allclose(original, changed, equal_nan=True, rtol=0, atol=0)


class TemporalRunnerTests(unittest.TestCase):
    def test_outer_reads_only_past_for_selection_and_reassembles_full_axis(self):
        source = synthetic_frame(1000)
        stored = {}
        selected_bounds = []
        evaluated_bounds = []
        output_metrics = {}
        real_read_csv = pd.read_csv

        def fake_read_csv(path, *args, **kwargs):
            path = Path(path)
            if path == runner.RAW18:
                self.assertIn("nrows", kwargs)
                return source.iloc[:kwargs["nrows"]].copy()
            if path.name == "test_predictions.csv.gz":
                return stored[path.parent.name].copy()
            raise AssertionError(f"Unexpected read attempted: {path}")

        def fake_select(train, calibration, channels, folder, metadata):
            selected_bounds.append(metadata)
            train_start, train_end = metadata["train"]
            cal_start, cal_end = metadata["calibration"]
            test_start, test_end = metadata["test"]
            np.testing.assert_array_equal(train.source_index, np.arange(train_start, train_end))
            np.testing.assert_array_equal(calibration.source_index, np.arange(cal_start, cal_end))
            self.assertEqual(cal_start - train_end, 3)
            self.assertEqual(cal_end, test_start)
            self.assertLess(train.source_index.max(), calibration.source_index.min())
            self.assertLess(calibration.source_index.max(), test_start)
            self.assertEqual(metadata["selection_max_source_index"], test_start - 1)
            self.assertEqual(test_end - test_start, 100)

        def fake_evaluate(part, bundles, folder, source_start_index):
            evaluated_bounds.append((source_start_index, source_start_index + len(part)))
            np.testing.assert_array_equal(part.source_index, np.arange(source_start_index, source_start_index + len(part)))
            predicted = np.zeros(len(part), dtype=int)
            predicted[:3] = -1
            stored[folder.name] = pd.DataFrame({
                "sample_index": part.source_index.to_numpy(),
                "EVENT": part.EVENT.to_numpy(),
                "baseline_prediction": predicted,
                "v2_prediction": predicted,
            })

        def fake_write(path, value):
            output_metrics[Path(path).name] = value

        with TemporaryDirectory() as temporary, \
             patch.object(runner, "OUT", Path(temporary)), \
             patch.object(runner, "N18", 1000), \
             patch.object(runner, "GAP", 3), \
             patch.object(runner, "check", return_value={}), \
             patch.object(runner, "sha", return_value="synthetic-protocol-hash"), \
             patch.object(runner, "select_models", side_effect=fake_select), \
             patch.object(runner, "load_models", return_value={}), \
             patch.object(runner, "evaluate_partition", side_effect=fake_evaluate), \
             patch.object(runner, "write", side_effect=fake_write), \
             patch.object(runner.pd, "read_csv", side_effect=fake_read_csv), \
             patch("builtins.print"):
            runner.outer()
            # Reading only a synthetic artifact generated above; never a benchmark.
            combined = real_read_csv(Path(temporary) / "walk_forward_predictions.csv.gz")
        np.testing.assert_array_equal(combined.sample_index, np.arange(400, 1000))
        self.assertEqual(evaluated_bounds, [(i, i + 100) for i in range(400, 1000, 100)])
        self.assertEqual(len(selected_bounds), 6)
        self.assertEqual(output_metrics["walk_forward_results.json"]["native"]["v2"]["unavailable_count"], 18)

    def test_common_evaluation_keeps_unscorable_events_in_recall_denominator(self):
        labels = np.array([False, True, True, False, True, False])
        baseline = np.array([0, 1, 1, 0, 1, 0])
        candidate = np.array([0, -1, -1, 0, 1, 0])
        result = runner.assess(labels, baseline, candidate)
        self.assertEqual(result["native"]["baseline"]["event_recall"], 1)
        self.assertEqual(result["common"]["baseline"]["event_recall"], .5)
        self.assertEqual(result["common"]["v2"]["event_recall"], .5)
        self.assertEqual(result["common"]["v2"]["true_events"], 2)
        self.assertEqual(result["common"]["v2"]["fully_unscorable_events"], 1)

    def test_test_partition_gap_remains_unavailable_on_original_axis(self):
        part = synthetic_frame(180)
        captured = []
        bundles = {
            role: {"family": "if_normalized_changes_w30", "model": object(),
                   "channels": CHANNELS, "threshold": 1, "policy": "instant"}
            for role in ["baseline", "v2"]
        }

        def fake_score(family, model, score_part, channels):
            captured.append(score_part.source_index.to_numpy())
            return np.zeros(len(score_part))

        with TemporaryDirectory() as temporary, \
             patch.object(runner, "scores_for", side_effect=fake_score), \
             patch("builtins.print"):
            result = runner.evaluate_partition(part, bundles, Path(temporary), 1000, gap=120)
        for scored_indices in captured:
            np.testing.assert_array_equal(scored_indices, np.arange(120, 180))
        self.assertEqual(result["source_end_index"], 1180)
        self.assertEqual(result["native"]["v2"]["sample_count"], 180)
        self.assertEqual(result["native"]["v2"]["unavailable_count"], 120)

    def test_2019_calibration_never_reads_final_file(self):
        train = synthetic_frame(180).rename(columns={"EVENT": "Event"})
        calibration = synthetic_frame(180).rename(columns={"EVENT": "Event"})
        calibration["Time"] = pd.date_range("2020-02-01", periods=180, freq="min").astype(str)
        reads = []
        selected = {}

        def fake_read(path):
            name = Path(path).name
            reads.append(name)
            if name == "7_gecco2019_train_water_quality.csv":
                return train.copy()
            if name == "8_gecco2019_valid_water_qulity.csv":
                return calibration.copy()
            raise AssertionError("Final file must not be opened during calibration")

        def fake_select(fit, cal, channels, folder, metadata):
            selected.update({"train": fit, "calibration": cal, "channels": channels, "metadata": metadata})

        with TemporaryDirectory() as temporary, \
             patch.object(runner, "OUT", Path(temporary)), \
             patch.object(runner, "check", return_value={}), \
             patch.object(runner.pd, "read_csv", side_effect=fake_read), \
             patch.object(runner, "select_models", side_effect=fake_select):
            runner.external_calibrate()
        self.assertEqual(reads, ["7_gecco2019_train_water_quality.csv", "8_gecco2019_valid_water_qulity.csv"])
        self.assertEqual(selected["channels"], ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"])
        np.testing.assert_array_equal(selected["calibration"].source_index, np.arange(120, 180))
        self.assertTrue(selected["metadata"]["final_file_labels_not_loaded"])

    def test_2019_final_labels_open_only_after_loading_frozen_models(self):
        final = synthetic_frame(180).rename(columns={"EVENT": "Event"})
        final["Time"] = pd.date_range("2020-03-01", periods=180, freq="min").astype(str)
        order = []

        def load_models(folder):
            order.append("frozen_models_loaded")
            return {"sentinel": "frozen"}

        def read_final(path):
            self.assertEqual(order, ["frozen_models_loaded"])
            self.assertEqual(Path(path).name, "6_gecco2019_test_water_quality.csv")
            order.append("final_labels_loaded")
            return final.copy()

        with TemporaryDirectory() as temporary, \
             patch.object(runner, "OUT", Path(temporary)), \
             patch.object(runner, "check", return_value={}), \
             patch.object(runner, "load_models", side_effect=load_models), \
             patch.object(runner.pd, "read_csv", side_effect=read_final), \
             patch.object(runner, "evaluate_partition") as evaluate:
            folder = Path(temporary) / "external_2019"
            folder.mkdir()
            (folder / "freeze.json").write_text(json.dumps({"metadata": {"calibration_end_time": "2020-02-01"}}))
            runner.external_test()
            evaluate.assert_called_once()
        self.assertEqual(order, ["frozen_models_loaded", "final_labels_loaded"])


if __name__ == "__main__":
    unittest.main()
