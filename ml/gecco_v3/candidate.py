"""Development-only supervised classifiers of causal normalized changes.

No absolute operating levels enter the classifier. Noise floors are fitted on
normal training windows, and scores are anomaly rankings, not safety/trust
probabilities. The CLI reads only the explicitly allowed 2019 TRAIN file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "ml/gecco_v2"))
sys.path.insert(0, str(ROOT / "ml/gecco_baseline"))
from candidates_unsupervised import CHANNELS as CHANNELS18, CausalChangeDetector
from alarm_policy import select, predict
from metrics import evaluate

CHANNELS19 = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
CONFIGS = [
    {"name": "normalized_extra_trees_depth10", "method": "extra_trees", "window": 30,
     "n_estimators": 160, "max_depth": 10, "min_samples_leaf": 6},
    {"name": "normalized_extra_trees_depth14", "method": "extra_trees", "window": 30,
     "n_estimators": 160, "max_depth": 14, "min_samples_leaf": 4},
    {"name": "normalized_hist_gradient_boosting", "method": "hist_gradient_boosting", "window": 30,
     "max_iter": 120, "max_leaf_nodes": 15, "min_samples_leaf": 20,
     "learning_rate": .05, "l2_regularization": 2.0},
]


class NormalizedChangeClassifier:
    """fit(frame, labels), score(frame); optional ordered six/nine-channel schema.

    Features per channel are signed residual from the previous-window median,
    one-minute difference, and previous-five-minute mean minus previous-window
    median. All are divided by causally estimated noise scales with a floor
    learned from normal training windows. The maximum lookback is 60 minutes.
    Missing observations invalidate the entire lookback; no imputation occurs.
    """

    def __init__(self, config=None, channels=None):
        self.config = dict(CONFIGS[0] if config is None else config)
        self.channels = list(channels) if channels is not None else self.config.get("channels")
        self.max_lookback = 2 * int(self.config.get("window", 30))

    def fit(self, frame, labels):
        labels = np.asarray(labels)
        if labels.ndim != 1 or len(labels) != len(frame) or labels.dtype.kind not in "biu" or not np.isin(labels, [0, 1]).all():
            raise ValueError("labels must be a binary one-dimensional sequence matching frame")
        labels = labels.astype(bool, copy=False)
        if self.channels is None:
            if set(CHANNELS18).issubset(frame.columns):
                self.channels = list(CHANNELS18)
            elif set(CHANNELS19).issubset(frame.columns):
                self.channels = list(CHANNELS19)
            else:
                raise ValueError("supply channels or a recognized GECCO schema")
        self.normalizer_ = CausalChangeDetector(
            {"window": self.config.get("window", 30), "method": "robust", "aggregate": "max"},
            channels=self.channels,
        ).fit(frame[self.channels], ~labels)
        features, eligible = self.features(frame)
        if np.unique(labels[eligible]).size != 2:
            raise ValueError("eligible supervised training rows must contain both classes")
        self.fit_rows_ = int(eligible.sum())
        self.floor_fit_rows_ = self.normalizer_.fit_rows_
        params = {key: value for key, value in self.config.items()
                  if key not in {"name", "method", "window", "channels"}}
        if self.config["method"] == "extra_trees":
            self.model_ = ExtraTreesClassifier(**params, max_features=.8, class_weight="balanced",
                                               n_jobs=1, random_state=20261016)
        elif self.config["method"] == "hist_gradient_boosting":
            self.model_ = HistGradientBoostingClassifier(**params, class_weight="balanced",
                                                         early_stopping=False, random_state=20261016)
        else:
            raise ValueError("unknown classifier")
        with threadpool_limits(limits=1):
            self.model_.fit(features[eligible], labels[eligible].astype(int))
        return self

    def features(self, frame):
        if not hasattr(self, "normalizer_"):
            raise RuntimeError("fit must establish normal training floors first")
        values = self.normalizer_._frame(frame[self.channels])
        residual, mad, delta, change, eligible = self.normalizer_._components(values)
        features, _ = self.normalizer_._normalized(residual, mad, delta, change)
        eligible = eligible & np.isfinite(features).all(axis=1)
        return features, eligible

    def score(self, frame):
        if not hasattr(self, "model_"):
            raise RuntimeError("fit must precede scoring")
        features, eligible = self.features(frame)
        scores = np.full(len(frame), np.nan)
        if eligible.any():
            positive = int(np.flatnonzero(self.model_.classes_ == 1)[0])
            with threadpool_limits(limits=1):
                scores[eligible] = self.model_.predict_proba(features[eligible])[:, positive]
        return scores


class NormalizedEventDetector(NormalizedChangeClassifier):
    """Stable runner interface selecting one of the three predeclared IDs."""

    def __init__(self, config_id="normalized_extra_trees_depth10", channels=None):
        matching = [config for config in CONFIGS if config["name"] == config_id]
        if not matching:
            raise ValueError(f"unknown config_id: {config_id}")
        super().__init__(matching[0], channels=channels)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def _compact(value):
    return {key: item for key, item in value.items() if not key.endswith("records")}


def run_development():
    source = ROOT / "data/external/gecco2019/7_gecco2019_train_water_quality.csv"
    output = ROOT / "output/ml/gecco-v3-development"
    if (output / "development_results.json").exists() or (output / "freeze.json").exists():
        raise RuntimeError("Development already frozen; do not overwrite or retune")
    training_end, calibration_end, permitted_end, gap = 79488, 105984, 132480, 120
    code_hashes = {str(path.relative_to(ROOT)): _hash(path) for path in [
        Path(__file__), ROOT / "ml/gecco_v2/candidates_unsupervised.py",
        ROOT / "ml/gecco_v2/alarm_policy.py", ROOT / "ml/gecco_baseline/metrics.py"]}
    protocol = {"scope": "2019 TRAIN internal development only, never final holdout",
                "configs": CONFIGS, "code_hashes": code_hashes,
                "source": str(source.relative_to(ROOT)), "max_rows_permitted": permitted_end,
                "splits": {"training": [0, training_end], "calibration": [training_end + gap, calibration_end],
                           "development_test": [calibration_end + gap, permitted_end]},
                "features": "signed normalized residual, delta, short-mean minus long-median; no raw levels",
                "floor_fit": "normal training windows only, including all 60 predecessors",
                "classification_fit": "all eligible training rows with their original labels",
                "maximum_lookback": 60, "selection": "frozen v2 alarm_policy.select, calibration only",
                "missing": "no imputation; complete 61-row history required; reset at each split",
                "final_2019_test_accessed": False, "v2_outer_results_accessed": False}
    _write(output / "protocol.json", protocol)
    prefix = pd.read_csv(source, nrows=calibration_end).rename(columns={"Event": "EVENT"})
    assert len(prefix) == calibration_end
    training = prefix.iloc[:training_end].reset_index(drop=True)
    calibration = prefix.iloc[training_end + gap:calibration_end].reset_index(drop=True)
    training_labels = training.EVENT.to_numpy(dtype=bool)
    calibration_labels = calibration.EVENT.to_numpy(dtype=bool)
    selections = []
    for config in CONFIGS:
        model = NormalizedChangeClassifier(config, CHANNELS19).fit(training, training_labels)
        scores = model.score(calibration)
        chosen, trials = select(calibration_labels, scores)
        name = config["name"]
        joblib.dump(model, output / f"{name}.joblib", compress=3)
        pd.DataFrame(trials).to_csv(output / f"{name}_calibration_trials.csv.gz", index=False)
        pd.DataFrame({"EVENT": calibration_labels, "score": scores,
                      "prediction": predict(scores, chosen["threshold"], chosen["policy"])}).to_csv(
            output / f"{name}_calibration_scores.csv.gz", index=False)
        selection = {"config": config, "fit_rows": model.fit_rows_, "floor_fit_rows": model.floor_fit_rows_,
                     "selected_calibration": chosen, "model_sha256": _hash(output / f"{name}.joblib")}
        selections.append(selection)
        print(json.dumps({"stage": "calibrated", **selection}), flush=True)
    # Every model, config and operating point is locked before the dev-test rows are opened.
    winner = max(selections, key=lambda row: (
        row["selected_calibration"]["confirmed_new_alarm_inside_event_recall"] or 0,
        row["selected_calibration"]["f1"] or 0,
        -row["selected_calibration"]["fp"],
        -[config["name"] for config in CONFIGS].index(row["config"]["name"])))
    _write(output / "freeze.json", {"protocol_sha256": _hash(output / "protocol.json"),
                                     "code_hashes": code_hashes, "selections": selections,
                                     "selected_by_calibration": winner["config"]["name"],
                                     "development_test_labels_opened": False,
                                     "final_2019_test_accessed": False})
    del prefix, training, calibration
    assert _hash(__file__) == code_hashes[str(Path(__file__).relative_to(ROOT))]
    development = pd.read_csv(source, nrows=permitted_end).rename(columns={"Event": "EVENT"})
    assert len(development) == permitted_end
    development = development.iloc[calibration_end + gap:permitted_end].reset_index(drop=True)
    labels = development.EVENT.to_numpy(dtype=bool)
    results = []
    for selection in selections:
        name = selection["config"]["name"]
        path = output / f"{name}.joblib"
        assert _hash(path) == selection["model_sha256"]
        model = joblib.load(path)
        scores = model.score(development)
        chosen = selection["selected_calibration"]
        predictions = predict(scores, chosen["threshold"], chosen["policy"])
        metrics = evaluate(labels, predictions)
        result = {"name": name, "selected_by_calibration": name == winner["config"]["name"],
                  "development_only": True, "metrics": _compact(metrics)}
        results.append(result)
        pd.DataFrame({"source_index": np.arange(calibration_end + gap, permitted_end),
                      "EVENT": labels, "score": scores, "prediction": predictions}).to_csv(
            output / f"{name}_development_scores.csv.gz", index=False)
        _write(output / f"{name}_development_events.json", metrics["event_records"])
        print(json.dumps({"stage": "development_evaluation", **result}), flush=True)
    _write(output / "development_results.json", {"scope": protocol["scope"],
                                                 "selected_by_calibration": winner["config"]["name"],
                                                 "results": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if args.development:
        run_development()
    else:
        parser.error("use --development for the permitted TRAIN-only experiment")
