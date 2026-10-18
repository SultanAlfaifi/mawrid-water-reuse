"""Bounded, sensor-only streaming of the frozen V9 batch inference contract.

This is an engineering adapter, not model acceptance or a hardware benchmark.
There is no fitting, label use, source/file I/O, clock resampling, or actuation.
One instance is one continuous session. Both update() and update_frame() commit
atomically: validation/scoring exceptions leave all stream state unchanged.

Core state holds 1441 sensor rows, the existing V6 stream, five rescue scores,
and the final confirmation episode state. Input/output frames are caller-sized.
Fitted estimators remain shared, trusted, and immutable; policy dictionaries are
copied. Recomputing features on the bounded ring prioritizes fidelity over speed.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from copy import copy, deepcopy
from datetime import datetime

import numpy as np
import pandas as pd

from ml.gecco_v6.runtime_v4 import StreamingPredictor as ReferenceStream
from ml.gecco_v6.runtime_v4 import OUTPUT_COLUMNS as REFERENCE_COLUMNS
from ml.gecco_v6.guarded_suppression import guarded_shape
from ml.gecco_v7.calibration import _rescue_mask
from ml.gecco_v7.calibration_delayed import _validate_choice
from ml.gecco_v7.evidence import separate_scores


VERSION = "v9_conditional_hgb_temporally_certified_120s"
SENSOR_HISTORY_ROWS = 1441
RESCUE_HISTORY_ROWS = 5
OUTPUT_COLUMNS = tuple("reference_prediction" if k == "prediction" else k
                       for k in REFERENCE_COLUMNS) + (
    "long_context", "guarded_long_context", "prediction", "rescue_long_context")
INTEGER_COLUMNS = ("baseline_prediction", "guarded_prediction",
                   "reference_prediction", "prediction")
BOOLEAN_COLUMNS = ("available", "ignored_gap")


def _reference_copy(stream):
    result = copy(stream)
    result.sensor_rows = deque(stream.sensor_rows, maxlen=stream.sensor_rows.maxlen)
    result.score_history = deque(stream.score_history, maxlen=stream.score_history.maxlen)
    return result


def _output(records, index):
    result = pd.DataFrame(records, index=index, columns=OUTPUT_COLUMNS)
    for key in OUTPUT_COLUMNS:
        dtype = np.int8 if key in INTEGER_COLUMNS else bool if key in BOOLEAN_COLUMNS else float
        result[key] = result[key].astype(dtype)
    return result


class StreamingPredictor:
    """update(timestamp, sensor_mapping), update_frame(frame), and reset().

    Frames must have a regular DatetimeIndex at the bundle's declared cadence.
    The clock is also checked between calls. Gaps/duplicates/reversal fail;
    reset() explicitly begins a new session and restarts the saved initial gap.
    First gap_samples rows are discarded before all sensor feature computation.
    Extra fields such as EVENT/label are ignored, never forwarded to a model.

    Fitted bundle objects must not be mutated by callers during this session.
    The adapter is single-consumer; simultaneous calls are not supported.
    """

    def __init__(self, bundle, *, gap_samples=None):
        required = {"version", "long_model", "reference_bundle", "selected", "sample_seconds"}
        if not isinstance(bundle, dict) or not required.issubset(bundle) or bundle["version"] != VERSION:
            raise ValueError("A complete matching V9 bundle is required")
        if not isinstance(bundle["selected"], dict):
            raise ValueError("A saved confirmation policy is required")
        self.selected = deepcopy(bundle["selected"])
        self.low, self.high, self.policy, self.deadline = _validate_choice(self.selected)
        cadence = bundle["sample_seconds"]
        if (isinstance(cadence, (bool, np.bool_)) or not isinstance(cadence, (int, float, np.integer, np.floating))
                or not np.isfinite(cadence) or cadence <= 0
                or cadence != self.selected.get("cadence_seconds")):
            raise ValueError("Model and saved policy need the same positive cadence")
        self.sample_seconds = float(cadence)
        self.interval = pd.Timedelta(seconds=self.sample_seconds)
        if self.interval <= pd.Timedelta(0):
            raise ValueError("Cadence must be representable by pandas timestamps")
        self.gap_samples = bundle.get("gap_samples", 120) if gap_samples is None else gap_samples
        self.long_model = bundle["long_model"]
        channels = getattr(self.long_model, 'channels', None)
        if not isinstance(channels, (tuple, list)) or not channels:
            raise ValueError('A nonempty fitted sensor schema is required')
        if (any(not isinstance(c, str) or not c or c.lower() in
                {'label', 'labels', 'event', 'anomaly', 'attack', 'target', 'timestamp'} for c in channels)
                or len(channels) != len(set(channels))):
            raise ValueError('Sensor channels must be unique and exclude label/clock fields')
        self.channels = tuple(channels)
        bound = getattr(self.long_model, "max_lookback_", None)
        if (isinstance(bound, (bool, np.bool_)) or not isinstance(bound, (int, np.integer))
                or not 0 <= bound < SENSOR_HISTORY_ROWS):
            raise ValueError("Long model exceeds the supported1440sample lookback")
        # Copy mutable policy/config dictionaries, never large fitted estimators.
        if not isinstance(bundle['reference_bundle'], dict):
            raise ValueError('A complete saved reference bundle is required')
        reference = dict(bundle["reference_bundle"])
        for key in ("prior_bundle", "guard_selected", "selected"):
            if not isinstance(reference.get(key), dict):
                raise ValueError('A complete saved reference policy is required')
            reference[key] = dict(reference[key])
        self._reference_config = reference
        probe = ReferenceStream(reference, gap_samples=self.gap_samples)
        if self.channels != tuple(probe.channels):
            raise ValueError("Long and reference channel order must match")
        self.gap_samples = int(self.gap_samples)
        self.reset()

    def reset(self):
        """Begin a new session; no previous sensor, clock, or alarm state survives."""
        self.reference = ReferenceStream(self._reference_config, gap_samples=self.gap_samples)
        self.sensor_rows = deque(maxlen=SENSOR_HISTORY_ROWS)
        self.rescue_scores = deque(maxlen=RESCUE_HISTORY_ROWS)
        self.samples_seen = 0
        self.last_timestamp = None
        self.previous_reference = -1
        self.episode_age = 0
        self.released = False

    def _fork(self):
        staged = copy(self)
        staged.reference = _reference_copy(self.reference)
        staged.sensor_rows = deque(self.sensor_rows, maxlen=SENSOR_HISTORY_ROWS)
        staged.rescue_scores = deque(self.rescue_scores, maxlen=RESCUE_HISTORY_ROWS)
        return staged

    def _commit(self, staged):
        for name in ("reference", "sensor_rows", "rescue_scores", "samples_seen",
                     "last_timestamp", "previous_reference", "episode_age", "released"):
            setattr(self, name, getattr(staged, name))

    def _timestamp(self, timestamp):
        if not isinstance(timestamp, (pd.Timestamp, datetime, np.datetime64)):
            raise ValueError("An explicit timestamp is required; numeric/sample indices are unsupported")
        current = pd.Timestamp(timestamp)
        if pd.isna(current):
            raise ValueError("Timestamp cannot be missing")
        if self.last_timestamp is not None:
            if str(current.tz) != str(self.last_timestamp.tz):
                raise ValueError("Timezone must stay unchanged within a session")
            if current - self.last_timestamp != self.interval:
                raise ValueError("Timestamp must advance by exactly the saved cadence")
        return current

    def _sensor_row(self, row):
        if not isinstance(row, (Mapping, pd.Series)):
            raise ValueError("A sensor mapping or Series is required")
        if any(c not in row for c in self.channels):
            raise ValueError("Every fitted sensor channel is required")
        if isinstance(row, pd.Series) and any(list(row.index).count(c) != 1 for c in self.channels):
            raise ValueError("Sensor names must occur exactly once")
        # Match frozen batch behavior: discarded gap values are never converted.
        if self.samples_seen < self.gap_samples:
            return {c: row[c] for c in self.channels}
        return {c: float(row[c]) for c in self.channels}

    def _advance(self, timestamp, row):
        timestamp = self._timestamp(timestamp)
        sensors = self._sensor_row(row)
        record = self.reference.update(sensors)
        reference = int(record.pop("prediction"))
        record["reference_prediction"] = reference
        if self.samples_seen < self.gap_samples:
            confidence = np.nan
        else:
            self.sensor_rows.append(tuple(sensors[c] for c in self.channels))
            history = pd.DataFrame(self.sensor_rows, columns=self.channels)
            scores = np.asarray(self.long_model.score_components(history)["long_context"], float)
            if scores.shape != (len(history),):
                raise ValueError("Long scores must match the bounded sensor axis")
            confidence = float(scores[-1])
        local = {key: np.array([record[key]], float) for key in ("level", "jump", "sustained")}
        raw = np.array([confidence], float)
        record["long_context"] = confidence
        record["guarded_long_context"] = float(guarded_shape(local, raw)[0])
        rescue = float(separate_scores(local, raw)["rescue_long_context"][0])
        self.rescue_scores.append(rescue)
        # Preserve final policy state independently from the V6 baseline latch.
        if reference != 1:
            self.episode_age = 0
            self.released = False
            prediction = reference
        else:
            self.episode_age = (min(self.episode_age + 1, self.deadline)
                                if self.previous_reference == 1 else 0)
            self.released = bool(self.released or self.low is None
                                 or not np.isfinite(confidence) or confidence >= self.low
                                 or self.episode_age >= self.deadline)
            prediction = int(self.released)
        # Rescue does not change the reference episode's age/released state.
        if self.high is not None and reference >= 0 and _rescue_mask(
                np.asarray(self.rescue_scores), self.high, self.policy)[-1]:
            prediction = 1
        record["prediction"] = prediction
        record["rescue_long_context"] = rescue
        if bool(record["available"]) != (prediction >= 0):
            raise AssertionError("Final inference changed reference availability")
        self.previous_reference = reference
        self.samples_seen += 1
        self.last_timestamp = timestamp
        return record

    def update(self, timestamp, row):
        """Commit one reading atomically; unknown sensor values are allowed."""
        staged = self._fork()
        result = staged._advance(timestamp, row)
        self._commit(staged)
        return result

    def update_frame(self, frame):
        """Continue a session with an entire chunk, committed atomically.

        An empty, correctly shaped DatetimeIndex frame returns an empty output
        of stable dtypes and leaves state untouched. Return storage scales with
        this caller-provided chunk; internal retained state stays bounded.
        """
        if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.DatetimeIndex):
            raise ValueError("A sensor DataFrame with DatetimeIndex is required")
        if any(list(frame.columns).count(c) != 1 for c in self.channels):
            raise ValueError("Every fitted sensor column must occur exactly once")
        if frame.index.hasnans or (len(frame) > 1 and not np.all(
                frame.index[1:] - frame.index[:-1] == self.interval)):
            raise ValueError("Frame timestamp cadence must match the saved policy")
        if len(frame):
            self._timestamp(frame.index[0])
        sensors = frame.loc[:, list(self.channels)]
        staged = self._fork()
        records = [staged._advance(timestamp, row) for timestamp, row in sensors.iterrows()]
        result = _output(records, frame.index)
        self._commit(staged)
        return result
