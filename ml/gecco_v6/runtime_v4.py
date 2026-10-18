"""Inference for the frozen V6 run04 recipe, without fitting or source I/O.

The caller supplies an already fitted development_v4 bundle. This module uses
the raw parent shape score (before V5 normal-support masking), the local guard,
onset-latched suppression, corroborated rescue, and the saved joint selection.
It accepts sensor observations only; extra columns, including EVENT, are ignored.
There are no valve commands, safety probabilities, or deployment/latency claims.

By default the first 120 supplied samples are unavailable and are discarded
BEFORE feature calculation. This resets context exactly like the runner. All
window/gap sizes are SAMPLE COUNTS; no cadence conversion occurs here.

Streaming retains 75 sensor rows, 5 score records, and one retained-alarm bit.
That bit can remain true for arbitrarily long baseline alarms: recomputing a
latched decision from bounded sensor/score history alone would be incorrect.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "gecco_v5"))
sys.path.insert(0, str(HERE.parents[0] / "gecco_v2"))
from recovery_candidate import RecoveryEventDetector
from alarm_policy import predict as baseline_predict, POLICIES
from latched_suppression import predict as suppression_predict, _gate as suppression_gate
from guarded_suppression import guarded_shape
from corroborated_rescue import corroborated_scores
from joint_calibration_v2 import predict as joint_predict


SENSOR_HISTORY_ROWS = 75
SCORE_HISTORY_ROWS = 5
LOCAL_KEYS = ("level", "jump", "sustained")
COMPONENT_KEYS = LOCAL_KEYS + ("shape_raw",)
SCORE_COLUMNS = ("baseline_score", "shape_raw", *LOCAL_KEYS, "guarded_shape",
                 *("rescue__" + key for key in COMPONENT_KEYS))
OUTPUT_COLUMNS = (*SCORE_COLUMNS, "baseline_prediction", "guarded_prediction",
                  "prediction", "available", "ignored_gap")


def _validate(bundle, gap_samples):
    if isinstance(gap_samples, (bool, np.bool_)) or not isinstance(gap_samples, (int, np.integer)) or gap_samples < 0:
        raise ValueError("gap_samples must be a nonnegative integer sample count")
    required = {"local_model", "prior_bundle", "guard_selected", "shape_support_threshold", "selected"}
    if not isinstance(bundle, dict) or not required.issubset(bundle):
        raise ValueError("A complete development_v4 inference bundle is required")
    prior = bundle["prior_bundle"]
    if not isinstance(prior, dict) or not {"model", "baseline_threshold"}.issubset(prior):
        raise ValueError("prior_bundle requires model and baseline_threshold")
    local, model = bundle["local_model"], prior["model"]
    channels = list(local.channels)
    if not channels or len(set(channels)) != len(channels) or channels != list(model.channels):
        raise ValueError("Local and prior models must use the same nonempty ordered channels")
    for fitted in (local, model):
        bound = getattr(fitted, "max_lookback_", None)
        if not isinstance(bound, (int, np.integer)) or not 0 <= bound < SENSOR_HISTORY_ROWS:
            raise ValueError("Model lookback exceeds the supported 74-sample history")
    if not np.isfinite(float(prior["baseline_threshold"])):
        raise ValueError("A finite baseline threshold is required")
    if prior.get("baseline_policy", "instant") not in POLICIES:
        raise ValueError("Unknown baseline policy")
    guard = bundle["guard_selected"]
    if guard.get("decision") not in ("baseline", "candidate"):
        raise ValueError("Unknown guard decision")
    if guard["decision"] == "candidate":
        if guard.get("policy") not in POLICIES or not np.isfinite(float(guard["threshold"])):
            raise ValueError("Guard needs a known policy and finite threshold")
    shape_threshold = bundle["shape_support_threshold"]
    if shape_threshold is not None and (not np.isfinite(shape_threshold) or shape_threshold <= 0):
        raise ValueError("Shape support threshold must be None or positive finite")
    selected = bundle["selected"]
    if selected.get("seed") not in ("baseline", "guarded"):
        raise ValueError("Unknown joint seed")
    if selected.get("rescue") is not None:
        if selected["rescue"] not in COMPONENT_KEYS or selected.get("policy") not in POLICIES:
            raise ValueError("Unknown rescue component or policy")
        if not np.isfinite(float(selected["threshold"])):
            raise ValueError("Rescue threshold must be finite")
    return channels


def _values(frame, channels):
    if not isinstance(frame, pd.DataFrame) or any(c not in frame.columns for c in channels):
        raise ValueError("A DataFrame with all fitted sensor channels is required")
    return frame.loc[:, channels].astype(float).reset_index(drop=True)


def _components(bundle, frame):
    """Deliberately bypass SupportedRecoveryDetector.score_components masking."""
    local = bundle["local_model"].score_components(frame)
    parent = RecoveryEventDetector.score_components(bundle["prior_bundle"]["model"], frame)
    raw = {key: np.asarray(local[key], float) for key in LOCAL_KEYS}
    raw["shape_raw"] = np.asarray(parent["shape"], float)
    baseline = np.asarray(parent["baseline"], float)
    if baseline.shape != (len(frame),) or any(v.shape != baseline.shape for v in raw.values()):
        raise ValueError("Model components must be one-dimensional and match input length")
    guard = guarded_shape(raw, raw["shape_raw"])
    rescue = corroborated_scores(raw, bundle["shape_support_threshold"])
    return {"baseline_score": baseline, **raw, "guarded_shape": guard,
            **{"rescue__" + key: rescue[key] for key in COMPONENT_KEYS}}


def _ignored_record():
    return {**{key: np.nan for key in SCORE_COLUMNS}, "baseline_prediction": -1,
            "guarded_prediction": -1, "prediction": -1, "available": False,
            "ignored_gap": True}


def _output(records, index):
    out = pd.DataFrame(records, index=index, columns=OUTPUT_COLUMNS)
    for key in ("baseline_prediction", "guarded_prediction", "prediction"):
        out[key] = out[key].astype(np.int8)
    for key in ("available", "ignored_gap"):
        out[key] = out[key].astype(bool)
    for key in SCORE_COLUMNS:
        out[key] = out[key].astype(float)
    return out


def predict_frame(bundle, frame, *, gap_samples=120):
    """Batch inference on one independent period, returning original row alignment.

    Calling this separately for adjacent chunks intentionally resets the gap and
    latch. Use one StreamingPredictor for continuous chunks instead.
    """
    channels = _validate(bundle, gap_samples)
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("frame must be a DataFrame")
    skipped = min(gap_samples, len(frame))
    tail = _values(frame.iloc[skipped:], channels)
    if len(tail) == 0:
        return _output([_ignored_record() for _ in range(skipped)], frame.index)
    scored = _components(bundle, tail)
    # Preserve the runner's score axis: unavailable gap precedes all policies.
    scored = {key: np.r_[np.full(skipped, np.nan), value] for key, value in scored.items()}
    prior = bundle["prior_bundle"]
    base = baseline_predict(scored["baseline_score"], prior["baseline_threshold"],
                            prior.get("baseline_policy", "instant"))
    seed = suppression_predict(scored["guarded_shape"], base, bundle["guard_selected"])
    rescue = {key: scored["rescue__" + key] for key in COMPONENT_KEYS}
    prediction = joint_predict(base, seed, rescue, bundle["selected"])
    return _output({**scored, "baseline_prediction": base, "guarded_prediction": seed,
                    "prediction": prediction, "available": prediction >= 0,
                    "ignored_gap": np.arange(len(frame)) < skipped}, frame.index)


class StreamingPredictor:
    """Sample-at-a-time equivalent of predict_frame, with a persistent alarm latch.

    update(row) returns one output dictionary. update_frame(frame) continues the
    same state and returns a DataFrame; reset() starts a new independent period.
    Model bundle/parameters must remain unchanged during the stream. This simple
    interface recomputes features on the bounded sensor buffer; it is not a
    hardware throughput benchmark or a production sensor transport.
    """

    def __init__(self, bundle, *, gap_samples=120):
        self.channels = _validate(bundle, gap_samples)
        self.bundle = bundle
        self.gap_samples = int(gap_samples)
        self.reset()

    def reset(self):
        self.samples_seen = 0
        self.sensor_rows = deque(maxlen=SENSOR_HISTORY_ROWS)
        self.score_history = deque(maxlen=SCORE_HISTORY_ROWS)
        self.baseline_alarm_latched = False

    def update(self, row):
        if any(c not in row for c in self.channels):
            raise ValueError("row must contain all fitted sensor channels")
        if self.samples_seen < self.gap_samples:
            self.samples_seen += 1
            return _ignored_record()
        # Never let discarded gap observations enter model or policy context.
        values = {c: float(row[c]) for c in self.channels}
        self.sensor_rows.append(values)
        frame = pd.DataFrame(self.sensor_rows, columns=self.channels)
        components = _components(self.bundle, frame)
        record = {key: float(value[-1]) for key, value in components.items()}
        history = list(self.score_history) + [record]
        history = history[-SCORE_HISTORY_ROWS:]
        prior = self.bundle["prior_bundle"]
        base = int(baseline_predict([r["baseline_score"] for r in history],
                                   prior["baseline_threshold"],
                                   prior.get("baseline_policy", "instant"))[-1])
        guard = self.bundle["guard_selected"]
        if base != 1:
            self.baseline_alarm_latched = False
            seed = base
        else:
            if guard["decision"] == "baseline":
                keep = True
            else:
                gate = suppression_gate([r["guarded_shape"] for r in history],
                                        guard["threshold"], guard["policy"])[-1]
                keep = gate != 0  # Unknown gate preserves the baseline alarm.
            self.baseline_alarm_latched = self.baseline_alarm_latched or bool(keep)
            seed = int(self.baseline_alarm_latched)
        record["baseline_prediction"] = base
        record["guarded_prediction"] = seed
        rescue = {key: np.asarray([r["rescue__" + key] for r in history]) for key in COMPONENT_KEYS}
        bases = np.asarray([r["baseline_prediction"] for r in history], dtype=np.int8)
        seeds = np.asarray([r["guarded_prediction"] for r in history], dtype=np.int8)
        prediction = int(joint_predict(bases, seeds, rescue, self.bundle["selected"])[-1])
        record.update(prediction=prediction, available=prediction >= 0, ignored_gap=False)
        self.score_history.append(record)
        self.samples_seen += 1
        return dict(record)

    def update_frame(self, frame):
        if not isinstance(frame, pd.DataFrame) or any(c not in frame.columns for c in self.channels):
            raise ValueError("A DataFrame with all fitted sensor channels is required")
        return _output([self.update(row) for _, row in frame.iterrows()], frame.index)
