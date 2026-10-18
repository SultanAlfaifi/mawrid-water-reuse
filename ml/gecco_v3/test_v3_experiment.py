"""Runner checks using synthetic frames only; no benchmark labels are opened."""

from pathlib import Path
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import importlib.util
_RUNNER_PATH = Path(__file__).resolve().parent / "run_experiment.py"
_SPEC = importlib.util.spec_from_file_location("mawrid_v3_runner_test", _RUNNER_PATH)
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)
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
    def test_exact_four_candidates_and_original_baseline_not_in_candidate_pool(self):
        self.assertEqual(runner.FAMILIES, [
            "baseline_persistent", "normalized_extra_trees_depth10",
            "normalized_extra_trees_depth14", "normalized_hist_gradient_boosting",
        ])
        self.assertEqual(len(runner.CONFIGS), 3)

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

    def test_persistent_baseline_keeps_exact_original_fitted_scores(self):
        frame = synthetic_frame(600)
        frame.loc[300:319, "EVENT"] = True
        original, _ = runner.fit_candidate("baseline", frame, CHANNELS)
        persistent, _ = runner.fit_candidate("baseline_persistent", frame, CHANNELS)
        np.testing.assert_array_equal(
            runner.scores_for("baseline", original, frame, CHANNELS),
            runner.scores_for("baseline_persistent", persistent, frame, CHANNELS),
        )


class PredictorIsolationTests(unittest.TestCase):
    def test_normalized_score_never_receives_event_or_identifiers(self):
        frame = synthetic_frame(150)
        seen = []

        class Spy:
            def score(self, channels):
                seen.append(channels.columns.tolist())
                return np.arange(len(channels), dtype=float)

        original = runner.scores_for("normalized_extra_trees_depth10", Spy(), frame, CHANNELS)
        frame["EVENT"] = True
        frame["source_index"] = -1000
        changed = runner.scores_for("normalized_extra_trees_depth10", Spy(), frame, CHANNELS)
        self.assertEqual(seen, [CHANNELS, CHANNELS])
        np.testing.assert_array_equal(original, changed)

    def test_normalized_fit_receives_labels_separately_from_channel_features(self):
        frame = synthetic_frame(150)
        frame.loc[70:74, "EVENT"] = True
        seen = {}

        class Spy:
            def __init__(self, family, channels):
                seen["family"] = family
                seen["channels"] = channels

            def fit(self, features, labels):
                seen["fit_columns"] = features.columns.tolist()
                seen["labels"] = labels.copy()
                self.fit_rows_ = len(features)
                return self

        with patch.object(runner, "NormalizedEventDetector", Spy):
            _, metadata = runner.fit_candidate("normalized_extra_trees_depth10", frame, CHANNELS)
        self.assertEqual(seen["fit_columns"], CHANNELS)
        np.testing.assert_array_equal(seen["labels"], frame.EVENT.to_numpy(dtype=bool))
        self.assertEqual(metadata["fit_rows"], 150)

    def test_normalized_runner_scores_are_causal_and_label_invariant(self):
        frame = synthetic_frame(900)
        frame.loc[300:329, "EVENT"] = True
        frame.loc[300:329, "Tp"] += 5
        model, _ = runner.fit_candidate("normalized_extra_trees_depth10", frame.iloc[:650], CHANNELS)
        original = runner.scores_for("normalized_extra_trees_depth10", model, frame.iloc[:750], CHANNELS)
        frame.loc[750:, CHANNELS] = 1e6
        frame["EVENT"] = ~frame.EVENT
        changed = runner.scores_for("normalized_extra_trees_depth10", model, frame, CHANNELS)
        np.testing.assert_array_equal(original, changed[:750])


class TemporalRunnerTests(unittest.TestCase):
    def test_outer_reads_only_past_for_selection_and_reassembles_full_axis(self):
        source = synthetic_frame(1000)
        stored = {}
        selected_bounds = []
        evaluated_bounds = []
        output_metrics = {}
        saved = {}

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
                "v3_prediction": predicted,
            })

        def fake_write(path, value):
            output_metrics[Path(path).name] = value

        def fake_save(frame, path, **kwargs):
            saved[Path(path).name] = frame.copy()

        with patch.object(runner, "OUT", Path("/synthetic/gecco-v3")), \
             patch.object(Path, "exists", return_value=False), \
             patch.object(runner, "N18", 1000), \
             patch.object(runner, "GAP", 3), \
             patch.object(runner, "check", return_value={}), \
             patch.object(runner, "sha", return_value="synthetic-protocol-hash"), \
             patch.object(runner, "select_models", side_effect=fake_select), \
             patch.object(runner, "load_models", return_value={}), \
             patch.object(runner, "evaluate_partition", side_effect=fake_evaluate), \
             patch.object(runner, "write", side_effect=fake_write), \
             patch.object(pd.DataFrame, "to_csv", autospec=True, side_effect=fake_save), \
             patch.object(runner.pd, "read_csv", side_effect=fake_read_csv), \
             patch("builtins.print"):
            runner.outer()
            combined = saved["walk_forward_predictions.csv.gz"]
        np.testing.assert_array_equal(combined.sample_index, np.arange(400, 1000))
        self.assertEqual(evaluated_bounds, [(i, i + 100) for i in range(400, 1000, 100)])
        self.assertEqual(len(selected_bounds), 6)
        self.assertEqual(output_metrics["walk_forward_results.json"]["native"]["v3"]["unavailable_count"], 18)

    def test_common_evaluation_keeps_unscorable_events_in_recall_denominator(self):
        labels = np.array([False, True, True, False, True, False])
        baseline = np.array([0, 1, 1, 0, 1, 0])
        candidate = np.array([0, -1, -1, 0, 1, 0])
        result = runner.assess(labels, baseline, candidate)
        self.assertEqual(result["native"]["baseline"]["event_recall"], 1)
        self.assertEqual(result["common"]["baseline"]["event_recall"], .5)
        self.assertEqual(result["common"]["v3"]["event_recall"], .5)
        self.assertEqual(result["common"]["v3"]["true_events"], 2)
        self.assertEqual(result["common"]["v3"]["fully_unscorable_events"], 1)

    def test_test_partition_gap_remains_unavailable_on_original_axis(self):
        part = synthetic_frame(180)
        captured = []
        bundles = {
            role: {"family": "normalized_extra_trees_depth10", "model": object(),
                   "channels": CHANNELS, "threshold": 1, "policy": "instant"}
            for role in ["baseline", "v3"]
        }

        def fake_score(family, model, score_part, channels):
            captured.append(score_part.source_index.to_numpy())
            return np.zeros(len(score_part))

        with patch.object(Path, "exists", return_value=False), \
             patch.object(runner, "scores_for", side_effect=fake_score), \
             patch.object(runner, "write"), \
             patch.object(pd.DataFrame, "to_csv"), \
             patch("builtins.print"):
            result = runner.evaluate_partition(part, bundles, Path("/synthetic/gecco-v3"), 1000, gap=120)
        for scored_indices in captured:
            np.testing.assert_array_equal(scored_indices, np.arange(120, 180))
        self.assertEqual(result["source_end_index"], 1180)
        self.assertEqual(result["native"]["v3"]["sample_count"], 180)
        self.assertEqual(result["native"]["v3"]["unavailable_count"], 120)

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

        with patch.object(runner, "OUT", Path("/synthetic/gecco-v3")), \
             patch.object(Path, "exists", return_value=False), \
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

        with patch.object(runner, "OUT", Path("/synthetic/gecco-v3")), \
             patch.object(Path, "exists", return_value=False), \
             patch.object(runner, "check", return_value={}), \
             patch.object(runner, "load_models", side_effect=load_models), \
             patch.object(Path, "read_text", return_value=json.dumps({"metadata": {"calibration_end_time": "2020-02-01"}})), \
             patch.object(runner.pd, "read_csv", side_effect=read_final), \
             patch.object(runner, "evaluate_partition") as evaluate:
            runner.external_test()
            evaluate.assert_called_once()
        self.assertEqual(order, ["frozen_models_loaded", "final_labels_loaded"])


if __name__ == "__main__":
    unittest.main()
