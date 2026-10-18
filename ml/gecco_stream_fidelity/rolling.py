"""Stateful baseline15 statistics matching the frozen pandas3.0.6 kernel.

The numerical recurrences are adapted from pandas' BSD-3-Clause licensed
aggregations.pyx, pinned commit2905718b126579d2cf0fe5bae05bd75facb67d77,
lines175..440. Copyright(c)2008-2011,AQR Capital Management,LLC, Lambda
Foundry,Inc. and PyData Development Team; all rights reserved. See
PANDAS_LICENSE in this directory. Original source and SHA are archived under
output/ml/gecco-stream-fidelity/source/. No sensor data is read by this module.

This reproduces the numerical history of a normal right-aligned15sample
rolling mean/variance from period start. It does not replace near-zero values
by an invented threshold, alter labels, fit a model or change an alarm rule.
Only15observations/channel and scalar accumulators are retained. A variance
instability triggers the SAME upstream recomputation over the current15rows.
The std negative-variance clamp is pandas zsqrt semantics, not a new heuristic.
The feature names retain the frozen1m suffix; the window itself counts samples.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from copy import copy
from dataclasses import dataclass
import ctypes
import hashlib
import math
import platform

import numpy as np
import pandas as pd

PANDAS_VERSION = '3.0.6'
PANDAS_KERNEL_SHA256 = '07cf0f94b1a3b55574aacca4927b52fdcd8821fb5eba10ce2e3f849c276dd3cb'
WINDOW = 15
INV_CONDITION_TOLERANCE = float(np.finfo(np.float64).eps) * 1e3
# The qualified arm64 pandas wheel contracts the variance product and sum.
# Python's separate multiply/add rounds twice and does NOT match that kernel.
# libc fma makes the one-rounding operation explicit. This is numerical
# implementation fidelity, not an epsilon/rounding rule applied to values.
_FMA = ctypes.CDLL(None).fma
_FMA.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
_FMA.restype = ctypes.c_double


def validate_environment():
    """Fail closed for an unqualified numerical kernel; no dataset IO."""
    if (pd.__version__ != PANDAS_VERSION or pd.get_option('compute.use_numba')
            or platform.system() != 'Darwin' or platform.machine() != 'arm64'):
        raise ValueError('Qualified pandas3.0.6 Cython Darwin-arm64 environment required; no portable/Pi claim')
    from pandas._libs.window import aggregations
    digest = hashlib.sha256()
    with open(aggregations.__file__, 'rb') as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b''): digest.update(part)
    if digest.hexdigest() != PANDAS_KERNEL_SHA256:
        raise ValueError('Installed pandas numerical kernel differs from the qualified build')


@dataclass(slots=True)
class MeanState:
    nobs: int = 0
    negative_count: int = 0
    total: float = 0.0
    add_compensation: float = 0.0
    remove_compensation: float = 0.0
    previous_value: float = math.nan
    same_count: int = 0

    def add(self, value):
        if math.isnan(value): return
        self.nobs += 1
        y = value - self.add_compensation
        t = self.total + y
        self.add_compensation = t - self.total - y
        self.total = t
        self.negative_count += int(math.copysign(1.0, value) < 0)
        # Upstream only compares this count with nobs<=15. Capping it at15
        # preserves that predicate and prevents growth during an endless flat.
        self.same_count = min(WINDOW, self.same_count + 1) if value == self.previous_value else 1
        self.previous_value = value

    def remove(self, value):
        if math.isnan(value): return
        self.nobs -= 1
        y = -value - self.remove_compensation
        t = self.total + y
        self.remove_compensation = t - self.total - y
        self.total = t
        self.negative_count -= int(math.copysign(1.0, value) < 0)

    def result(self):
        if self.nobs < WINDOW: return math.nan
        result = self.total / float(self.nobs)
        if self.same_count >= self.nobs: return self.previous_value
        if self.negative_count == 0 and result < 0: return 0.0
        if self.negative_count == self.nobs and result > 0: return 0.0
        return result


@dataclass(slots=True)
class VarianceState:
    nobs: float = 0.0
    mean: float = 0.0
    m2: float = 0.0
    add_compensation: float = 0.0
    remove_compensation: float = 0.0
    unstable: bool = False

    def add(self, value):
        if math.isnan(value): return
        previous_m2 = self.m2
        self.nobs += 1.0
        previous_mean = self.mean - self.add_compensation
        y = value - self.add_compensation
        t = y - self.mean
        self.add_compensation = t + self.mean - y
        self.mean = self.mean + t / self.nobs
        self.m2 = _FMA(value - previous_mean, value - self.mean, self.m2)
        if previous_m2 * INV_CONDITION_TOLERANCE > self.m2: self.unstable = True

    def remove(self, value):
        if math.isnan(value): return
        previous_m2 = self.m2
        self.nobs -= 1.0
        if self.nobs:
            previous_mean = self.mean - self.remove_compensation
            y = value - self.remove_compensation
            t = y - self.mean
            self.remove_compensation = t + self.mean - y
            self.mean = self.mean - t / self.nobs
            self.m2 = _FMA(-(value - previous_mean), value - self.mean, self.m2)
            if previous_m2 * INV_CONDITION_TOLERANCE > self.m2: self.unstable = True
        else:
            self.mean = self.m2 = 0.0
            self.unstable = False

    def std(self):
        if self.nobs < WINDOW: return math.nan
        variance = self.m2 / self.nobs  # frozen baseline ddof=0
        if variance < 0: return 0.0  # pandas.core.window.common.zsqrt
        return float(np.sqrt(variance))


class ChannelState:
    def __init__(self):
        self.values = deque(maxlen=WINDOW)
        self.mean = MeanState()
        self.variance = VarianceState()

    def clone(self):
        other = copy(self)
        other.values = deque(self.values, maxlen=WINDOW)
        other.mean = copy(self.mean); other.variance = copy(self.variance)
        return other

    def update(self, value):
        previous = self.values[-1] if self.values else math.nan
        first = not self.values
        if len(self.values) == WINDOW:
            oldest = self.values[0]
            self.mean.remove(oldest); self.variance.remove(oldest)
        self.values.append(value)
        self.mean.add(value)
        if not first: self.variance.add(value)
        if first or self.variance.unstable:
            self.variance = VarianceState()
            for old in self.values: self.variance.add(old)
            self.variance.unstable = False
        return value, abs(value - previous), value - self.mean.result(), self.variance.std()


class RollingBaselineFeatures:
    """Sensor-only update(row)->(float64[4*C], eligible), with atomic rows.

    update_frame() continues state across chunks and is atomic as a whole.
    A caller owns period resets/gaps and its timestamp policy. Missing/inf
    values remain unavailable; no interpolation or source/label use occurs.
    """
    def __init__(self, channels):
        validate_environment()
        self.channels = tuple(channels)
        if (not self.channels or len(set(self.channels)) != len(self.channels)
                or any(not isinstance(c, str) or c.lower() in
                       {'event','label','labels','target','anomaly','attack','timestamp'} for c in self.channels)):
            raise ValueError('Unique sensor channels without annotation/clock fields are required')
        self.reset()

    @property
    def feature_names(self):
        return [c + suffix for suffix in ('__value','__abs_change_1m','__residual_mean_15m','__std_15m')
                for c in self.channels]

    def reset(self): self.states = [ChannelState() for _ in self.channels]

    def clone(self):
        other = copy(self); other.states = [s.clone() for s in self.states]
        return other

    def update(self, row):
        if not isinstance(row, (Mapping, pd.Series)) or any(c not in row for c in self.channels):
            raise ValueError('One complete sensor mapping is required')
        if isinstance(row, pd.Series) and any(list(row.index).count(c) != 1 for c in self.channels):
            raise ValueError('Sensor names must occur once')
        values = [float(row[c]) for c in self.channels]
        values = [v if math.isfinite(v) else math.nan for v in values]
        staged = [state.clone() for state in self.states]
        columns = [state.update(value) for state, value in zip(staged, values)]
        features = np.asarray(columns, dtype=np.float64).T.ravel()
        eligible = all(len(s.values) == WINDOW and all(math.isfinite(v) for v in s.values)
                       for s in staged) and bool(np.isfinite(features).all())
        self.states = staged
        return features, eligible

    def update_frame(self, frame):
        if not isinstance(frame, pd.DataFrame) or any(list(frame.columns).count(c) != 1 for c in self.channels):
            raise ValueError('A DataFrame with each fitted sensor column once is required')
        staged = self.clone(); records = [staged.update(row) for _, row in frame.loc[:, self.channels].iterrows()]
        X = np.asarray([r[0] for r in records], dtype=np.float64).reshape(len(frame), 4 * len(self.channels))
        eligible = np.asarray([r[1] for r in records], dtype=bool)
        self.states = staged.states
        return X, eligible
