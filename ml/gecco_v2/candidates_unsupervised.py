"""Causal, normal-window-trained change detectors for GECCO development.

The executable development experiment reads only the first 55,826 CSV rows.
Scores express anomaly evidence, never trust probabilities. No labels are used
as scoring features. Model/floor fitting excludes windows overlapping events.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

CHANNELS = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
CONFIGS = [
    {"name": "robust_change_w10", "window": 10, "method": "robust", "aggregate": "max"},
    {"name": "robust_change_w15", "window": 15, "method": "robust", "aggregate": "max"},
    {"name": "robust_change_w30", "window": 30, "method": "robust", "aggregate": "max"},
    {"name": "robust_change_w30_top2", "window": 30, "method": "robust", "aggregate": "top2"},
    {"name": "if_normalized_changes_w30", "window": 30, "method": "iforest", "aggregate": "max"},
]


class CausalChangeDetector:
    """Fit channel noise floors on normal training windows; score causally.

    ``fit(frame, normal_mask)`` accepts a DataFrame with the configured channels and a Boolean
    mask with True only for original normal labels. It excludes the current and
    preceding ``2*window`` rows after every abnormal or missing observation.

    ``score(frame)`` returns one score per input row, higher = more unusual.
    Supply earlier history in the same frame when scoring a later segment and
    slice its scores afterward. ``score_channels`` returns inspectable per-
    channel residual/change evidence, not additive IF feature attributions.
    Pass ``channels=[...]`` to the constructor or put a ``channels`` list in
    config to select another schema. The constructor argument takes precedence.
    Omitting both preserves the nine-channel GECCO 2018 schema and settings.
    """

    def __init__(self, config: dict[str, Any] | None = None, channels: list[str] | None = None):
        self.config = dict(CONFIGS[1] if config is None else config)
        self.channels = list(channels if channels is not None else self.config.get("channels", CHANNELS))
        if not self.channels or any(not isinstance(channel, str) for channel in self.channels):
            raise ValueError("channels must be a nonempty sequence of column names")
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("channels must not contain duplicates")
        self.window = int(self.config.get("window", 30))
        if self.window < 5 or self.window > 30:
            raise ValueError("window must be between 5 and 30 (maximum lookback 60 minutes)")
        self.max_lookback = 2 * self.window
        self.history_rows = 2 * self.window + 1
        self.model = None

    def _frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        return raw[self.channels].astype(float).replace([np.inf, -np.inf], np.nan).reset_index(drop=True)

    def _components(self, x: pd.DataFrame):
        past = x.shift(1)
        center = past.rolling(self.window, min_periods=self.window).median()
        residual = x - center
        # This causal MAD proxy is itself built only from earlier residuals.
        mad_proxy = residual.abs().shift(1).rolling(self.window, min_periods=self.window).median() * 1.4826
        delta = x.diff()
        short_mean = past.rolling(5, min_periods=5).mean()
        mean_change = short_mean - center
        eligible = x.notna().all(axis=1).rolling(self.history_rows, min_periods=self.history_rows).sum().eq(self.history_rows).to_numpy()
        return residual, mad_proxy, delta, mean_change, eligible

    def fit(self, raw_channels: pd.DataFrame, normal_mask: Any):
        x = self._frame(raw_channels)
        normal = np.asarray(normal_mask)
        if normal.ndim != 1 or len(normal) != len(x) or not np.isin(normal, [0, 1]).all():
            raise ValueError("normal_mask must be a binary one-dimensional mask matching the frame")
        residual, mad_proxy, delta, mean_change, eligible = self._components(x)
        clean = pd.Series(normal.astype(bool)).rolling(self.history_rows, min_periods=self.history_rows).sum().eq(self.history_rows).to_numpy()
        fit_mask = eligible & clean
        if fit_mask.sum() < 100:
            raise ValueError("need at least 100 eligible normal training windows")
        self.fit_rows_ = int(fit_mask.sum())
        floor = []
        delta_floor = []
        for channel in self.channels:
            values = x.loc[fit_mask, channel].to_numpy()
            steps = delta.loc[fit_mask, channel].abs().to_numpy()
            positive_steps = steps[steps > 0]
            quantum_noise = float(np.quantile(positive_steps, 0.75)) if positive_steps.size else 0.0
            robust_span = float(np.quantile(values, 0.75) - np.quantile(values, 0.25))
            eps = max(float(np.median(np.abs(values))) * 1e-9, 1e-9)
            # Positive-step quantiles protect quantized channels whose MAD is zero.
            delta_floor.append(max(quantum_noise, robust_span * 0.005, eps))
            residual_scale = float(np.median(residual.loc[fit_mask, channel].abs())) * 1.4826
            floor.append(max(quantum_noise, robust_span * 0.01, residual_scale * 0.05, eps))
        self.floor_ = np.array(floor)
        self.delta_floor_ = np.array(delta_floor)
        features, _ = self._normalized(residual, mad_proxy, delta, mean_change)
        if self.config.get("method", "robust") == "iforest":
            self.model = IsolationForest(n_estimators=160, max_samples=512, n_jobs=1,
                                         random_state=20261016, contamination="auto")
            self.model.fit(features[fit_mask])
        elif self.config.get("method", "robust") != "robust":
            raise ValueError("unknown method")
        return self

    def _normalized(self, residual, mad_proxy, delta, mean_change):
        scale = np.maximum(mad_proxy.to_numpy(), self.floor_)
        z_residual = residual.to_numpy() / scale
        z_delta = delta.to_numpy() / self.delta_floor_
        z_change = mean_change.to_numpy() / scale
        # Clipping prevents extreme quantized shifts overflowing downstream code.
        features = np.clip(np.concatenate([z_residual, z_delta, z_change], axis=1), -1e6, 1e6)
        channel_scores = np.maximum.reduce([np.abs(z_residual), 0.5 * np.abs(z_delta), 0.5 * np.abs(z_change)])
        return features, np.clip(channel_scores, 0, 1e6)

    def score_channels(self, raw_channels: pd.DataFrame) -> pd.DataFrame:
        if not hasattr(self, "floor_"):
            raise RuntimeError("fit must be called first")
        residual, mad_proxy, delta, mean_change, eligible = self._components(self._frame(raw_channels))
        _, channels = self._normalized(residual, mad_proxy, delta, mean_change)
        channels[~eligible] = np.nan
        return pd.DataFrame(channels, columns=self.channels, index=raw_channels.index)

    def score(self, raw_channels: pd.DataFrame) -> np.ndarray:
        if not hasattr(self, "floor_"):
            raise RuntimeError("fit must be called first")
        residual, mad_proxy, delta, mean_change, eligible = self._components(self._frame(raw_channels))
        features, channels = self._normalized(residual, mad_proxy, delta, mean_change)
        result = np.full(len(raw_channels), np.nan)
        if not eligible.any():
            return result
        if self.model is not None:
            result[eligible] = -self.model.score_samples(features[eligible])
        elif self.config.get("aggregate", "max") == "top2":
            result[eligible] = np.sort(channels[eligible], axis=1)[:, -2:].mean(axis=1)
        else:
            result[eligible] = channels[eligible].max(axis=1)
        return result


def causal_predict(scores, threshold: float, persistence: int | str = 1) -> np.ndarray:
    """Causal consecutive or m-of-n evidence; missing data resets alarm history.

    Supported named rules are instant, 2of3, 3of5. Integer rules require that
    many consecutive positives. A finite low row may remain alarmed under an
    m-of-n rule; that causal release delay is included in false-alarm metrics.
    """
    scores = np.asarray(scores, dtype=float)
    predictions = np.full(len(scores), -1, dtype=int)
    if isinstance(persistence, str):
        required, width = {"instant": (1, 1), "2of3": (2, 3), "3of5": (3, 5)}[persistence]
    else:
        required = width = int(persistence)
        if required < 1:
            raise ValueError("persistence must be positive")
    recent = []
    for index, score in enumerate(scores):
        if not np.isfinite(score):
            recent = []
            continue
        recent.append(bool(score >= threshold))
        recent = recent[-width:]
        predictions[index] = int(sum(recent) >= required)
    return predictions


def _compact(result):
    return {k: v for k, v in result.items() if not k.endswith("records")}


def development_experiment():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "ml/gecco_baseline"))
    from metrics import evaluate
    out = root / "output/ml/gecco-v2-development/unsupervised"
    out.mkdir(parents=True, exist_ok=True)
    train_end, calibration_end, development_end = 34891, 41869, 55826
    plan = {"scope": "development only; all selections use data index < 55826", "train_end": train_end,
            "calibration_end": calibration_end, "development_end": development_end,
            "configs": CONFIGS, "persistence_candidates": ["instant", "2of3", "3of5"],
            "maximum_model_lookback_minutes": 60,
            "threshold_quantiles": "121 fixed quantiles from 0.90 through 1.0, plus above-max",
            "calibration_objective": "feasible confirmed new event recall, then point F1, then fewer false positive minutes",
            "limits": {"false_alarm_runs_per_normal_day": 1, "normal_time_under_alarm": 0.01}}
    (out / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    # nrows is the hard read boundary: later source values and labels are never read.
    data = pd.read_csv(root / "data/external/gecco2018/1_gecco2018_water_quality.csv", nrows=development_end)
    assert len(data) == development_end
    labels = data.EVENT.to_numpy(dtype=bool)
    results, all_trials = [], []
    for config in CONFIGS:
        detector = CausalChangeDetector(config).fit(data.iloc[:train_end], ~labels[:train_end])
        scores = detector.score(data)
        cal_scores = scores[train_end:calibration_end]
        finite = cal_scores[np.isfinite(cal_scores)]
        thresholds = np.unique(np.r_[np.quantile(finite, np.linspace(.90, 1, 121)), np.nextafter(finite.max(), np.inf)])
        trials = []
        for persistence in ["instant", "2of3", "3of5"]:
            for threshold in thresholds:
                predictions = causal_predict(cal_scores, threshold, persistence)
                metrics = evaluate(labels[train_end:calibration_end], predictions)
                feasible = metrics["false_alarm_runs_per_normal_day"] <= 1 and metrics["normal_time_under_alarm"] <= .01
                trial = {"name": config["name"], "threshold": float(threshold), "persistence": persistence,
                         "feasible": bool(feasible), **_compact(metrics)}
                trials.append(trial)
        feasible = [trial for trial in trials if trial["feasible"]]
        selected = max(feasible, key=lambda t: (t["confirmed_new_alarm_inside_event_recall"] or 0,
                                               t["f1"] or 0, -t["fp"], t["threshold"],
                                               {"instant": 2, "2of3": 1, "3of5": 0}[t["persistence"]]))
        # Threshold/persistence already selected: development is for comparing declared configurations.
        pred = causal_predict(scores, selected["threshold"], selected["persistence"])
        dev_metrics = evaluate(labels[calibration_end:development_end], pred[calibration_end:development_end])
        dev_feasible = dev_metrics["false_alarm_runs_per_normal_day"] <= 1 and dev_metrics["normal_time_under_alarm"] <= .01
        result = {"config": config, "fit_rows": detector.fit_rows_, "floor": detector.floor_.tolist(),
                  "calibration_selection": selected, "development": _compact(dev_metrics),
                  "development_feasible": bool(dev_feasible)}
        results.append(result)
        all_trials.extend(trials)
        pd.DataFrame({"sample_index": np.arange(development_end), "EVENT": labels,
                      "score": scores, "prediction": pred}).to_csv(out / f"{config['name']}_development_scores.csv.gz", index=False)
        (out / f"{config['name']}_events.json").write_text(json.dumps(dev_metrics["event_records"], indent=2) + "\n")
        print(json.dumps(result), flush=True)
    pd.DataFrame(all_trials).to_csv(out / "calibration_trials.csv", index=False)
    (out / "results.json").write_text(json.dumps(results, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", action="store_true")
    arguments = parser.parse_args()
    if arguments.development:
        development_experiment()
    else:
        parser.error("use --development to run the bounded development experiment")
