"""Mechanical adapter for the preregistered, unused Ponds phase cohorts.

Importing this module does not read data. Call only after the reserve extension
protocol has frozen. Exact five-field identities select observations before any
sensor suffix is decoded. The four consumed M/Phase1 cohorts are prohibited.
Phases remain separate histories; multiple phases are not independent sites.
Publisher preprocessing before intermediate3.1 remains unverified.
"""
from __future__ import annotations

import math
import zipfile

import numpy as np
import pandas as pd

from ponds_data import (
    ANNOTATION_MEMBER, CHANNELS, FEATURES_MEMBER, IDENTITY,
    _identity_prefix, _sensor_fields, number,
)


def _cohort_keys(cohorts):
    keys = [tuple(value) for value in cohorts]
    if not keys or any(len(key) != 5 or any(not isinstance(v, str) or not v for v in key) for key in keys):
        raise ValueError('Nonempty five-string cohort identities required')
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate reserved cohort identity')
    if any(key[2] == 'M' and key[4] == '1' for key in keys):
        raise ValueError('Consumed M/Phase1 cohorts cannot enter reserved evaluation')
    return keys


def read_reserved_cohorts(archive, cohorts):
    """Return tuple5 -> regular15-minute DataFrame in declared cohort order.

    Identity order is Pond,Sonde,Treatment,Replicate,Phase. Absolute relative-time
    slots are retained, including nonzero phase starts. Missing original target
    and inserted time slots remain unavailable; no interpolation or zero fill.
    The caller must freeze the exact identities and expected geometry before use.
    """
    keys = _cohort_keys(cohorts)
    encoded = {tuple(v.encode('utf-8') for v in key): key for key in keys}
    rows = {key: [] for key in keys}
    with zipfile.ZipFile(archive) as z:
        with z.open(FEATURES_MEMBER) as first, z.open(ANNOTATION_MEMBER) as second:
            expected = IDENTITY + CHANNELS
            headers = [s.readline().decode('utf-8-sig').rstrip('\r\n').split('\t') for s in (first, second)]
            if any(header != expected for header in headers):
                raise ValueError('Unexpected publisher schema; stop before adapting it')
            for source_row, left_line in enumerate(first):
                right_line = next(second, None)
                if right_line is None:
                    raise ValueError(f'Annotation identity/order mismatch at source row {source_row}')
                left_identity, left_suffix = _identity_prefix(left_line)
                right_identity, right_suffix = _identity_prefix(right_line)
                if left_identity != right_identity:
                    raise ValueError(f'Annotation identity/order mismatch at source row {source_row}')
                key = encoded.get(tuple(left_identity[:5]))
                if key is None:
                    continue
                left = _sensor_fields(left_suffix)
                right = _sensor_fields(right_suffix)
                values = {channel: number(left[channel]) for channel in CHANNELS}
                cleaned_conductivity = number(right['SpCond_uScm'])
                annotated = math.isfinite(values['SpCond_uScm'])
                event = annotated and math.isnan(cleaned_conductivity)
                elapsed_days = number(left_identity[6].decode('utf-8'))
                if not math.isfinite(elapsed_days):
                    raise ValueError('Nonfinite relative time')
                slot = int(round(elapsed_days * 96))
                if abs(elapsed_days * 96 - slot) > 1e-4:
                    raise ValueError('Time not on declared15-minute grid')
                if not annotated:
                    values = {channel: float('nan') for channel in CHANNELS}
                rows[key].append({
                    'slot': slot, 'Time_seq': elapsed_days, 'source_row': source_row,
                    'row_observed': True, 'label_available': annotated,
                    'EVENT': bool(event), **values,
                })
            if next(second, None) is not None:
                raise ValueError('Annotation contains extra rows')

    result = {}
    for key, observed in rows.items():
        if not observed:
            raise ValueError(f'Predeclared cohort absent: {key}')
        frame = pd.DataFrame(observed)
        slots = frame.slot.to_numpy()
        if np.any(np.diff(slots) <= 0):
            raise ValueError(f'Nonmonotonic/duplicate source time: {key}')
        axis = np.arange(slots[0], slots[-1] + 1)
        regular = frame.set_index('slot').reindex(axis)
        regular.index.name = 'slot'
        regular['row_observed'] = regular.row_observed.eq(True)
        regular['label_available'] = regular.label_available.eq(True)
        regular['EVENT'] = regular.EVENT.eq(True)
        regular['source_row'] = regular.source_row.fillna(-1).astype(np.int64)
        regular['Time_seq'] = axis / 96
        result[key] = regular.reset_index()
    return result
