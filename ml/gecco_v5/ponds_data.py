"""Mechanical fresh-source adapter. Importing it does not read any data.

Call only after a method protocol and first-access record exist. Never use the
expert-cleaned file as model features. Nonselected cohorts stay unparsed as
measurements/labels; identity fields alone are checked for exact row alignment.
Upstream processing of publisher intermediate3.1 is a separate provenance issue.
"""
from __future__ import annotations
import csv
import math
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd

FEATURES_MEMBER='AL_Repo/data/ponds_sonde_data_intermediate_3.1.txt'
ANNOTATION_MEMBER='AL_Repo/data/ponds_sonde_data_intermediate_3.2.txt'
IDENTITY=['Pond','Sonde','Treatment','Replicate','Phase','Subphase','Time_seq']
CHANNELS=['Chlorophyll_RFU','BGAPC_RFU','ODO_sat','ODO_mgL','pH','fDOM_RFU','SpCond_uScm','Temp_C']
DEFAULT_COHORTS=[('2D','Sonde07'),('3D','Sonde10'),('5A','Sonde04'),('5B','Sonde15')]
MISSING={'','NA','N/A','NaN','nan','NULL','null','None'}


def number(value):
    return float('nan') if value.strip() in MISSING else float(value)


def _identity_prefix(line):
    """Split only seven identity fields; leave the sensor suffix opaque."""
    fields=line.split(b'\t',7)
    if len(fields)!=8:
        raise ValueError('Unexpected TSV row: seven identity fields required')
    identity=fields[:7]
    if any(not field or any(mark in field for mark in (b'"',b'\r',b'\n',b'\x00')) for field in identity):
        raise ValueError('Unexpected empty, quoted or multiline identity field')
    return identity,fields[7]


def _sensor_fields(suffix):
    """Decode sensor fields only after the predeclared cohort has matched."""
    values=next(csv.reader([suffix.decode('utf-8').rstrip('\r\n')],delimiter='\t',strict=True))
    if len(values)!=len(CHANNELS):
        raise ValueError('Unexpected sensor-field count in selected cohort')
    return dict(zip(CHANNELS,values))


def read_selected_cohorts(archive,cohorts=DEFAULT_COHORTS):
    """Return regular15-minute axes, retaining original source-row identities.

    The caller's protocol must declare Treatment=M,Phase=1 and the cohort list.
    The cleaned conductivity field supplies only annotation. Original missing
    conductivity is an unknown target, so both methods receive unavailable
    feature rows there. No zero filling, interpolation or backward filling.
    """
    selected=set(tuple(pair) for pair in cohorts)
    if not selected or len(selected)!=len(cohorts):raise ValueError('Unique nonempty cohort list required')
    encoded_pairs={(pair[0].encode('utf-8'),pair[1].encode('utf-8')):pair for pair in selected}
    rows={pair:[] for pair in cohorts}
    with zipfile.ZipFile(archive) as z:
        with z.open(FEATURES_MEMBER) as first,z.open(ANNOTATION_MEMBER) as second:
            expected=IDENTITY+CHANNELS
            headers=[stream.readline().decode('utf-8-sig').rstrip('\r\n').split('\t') for stream in (first,second)]
            if any(header!=expected for header in headers):
                raise ValueError('Unexpected publisher schema; stop before adapting it')
            count=0
            for count,left_line in enumerate(first,1):
                right_line=next(second,None)
                if right_line is None:
                    raise ValueError(f'Annotation identity/order mismatch at source row {count-1}')
                left_identity,left_suffix=_identity_prefix(left_line)
                right_identity,right_suffix=_identity_prefix(right_line)
                if left_identity!=right_identity:
                    raise ValueError(f'Annotation identity/order mismatch at source row {count-1}')
                pair=encoded_pairs.get((left_identity[0],left_identity[1]))
                if pair is None or left_identity[2]!=b'M' or left_identity[4]!=b'1':continue
                left=_sensor_fields(left_suffix)
                right=_sensor_fields(right_suffix)
                values={key:number(left[key]) for key in CHANNELS}
                cleaned_conductivity=number(right['SpCond_uScm'])
                original=values['SpCond_uScm']
                annotated=math.isfinite(original)
                event=annotated and math.isnan(cleaned_conductivity)
                elapsed_days=number(left_identity[6].decode('utf-8'))
                if not math.isfinite(elapsed_days):raise ValueError('Nonfinite relative time')
                slot=int(round(elapsed_days*96))
                if abs(elapsed_days*96-slot)>1e-4:raise ValueError('Time not on declared15-minute grid')
                # Unknown target values cannot train a negative example or add
                # normal exposure through the other seven observed channels.
                if not annotated:values={key:float('nan') for key in CHANNELS}
                rows[pair].append({'slot':slot,'Time_seq':elapsed_days,'source_row':count-1,
                    'row_observed':True,'label_available':annotated,'EVENT':bool(event),**values})
            if next(second,None) is not None:raise ValueError('Annotation contains extra rows')
    result={}
    for pair,observed in rows.items():
        if not observed:raise ValueError(f'Predeclared cohort absent: {pair}')
        frame=pd.DataFrame(observed)
        slots=frame.slot.to_numpy()
        if np.any(np.diff(slots)<=0):raise ValueError(f'Nonmonotonic/duplicate source time: {pair}')
        axis=np.arange(slots[0],slots[-1]+1)
        regular=frame.set_index('slot').reindex(axis)
        regular.index.name='slot'
        regular['row_observed']=regular.row_observed.eq(True)
        regular['label_available']=regular.label_available.eq(True)
        regular['EVENT']=regular.EVENT.eq(True)
        regular['source_row']=regular.source_row.fillna(-1).astype(np.int64)
        regular['Time_seq']=axis/96
        result[pair]=regular.reset_index()
    return result


def observed_evaluation_view(regular,predictions):
    """Drop only inserted grid slots; preserve every publisher observation.

    Features still run on the full grid, so a time gap cannot be bridged by a
    rolling feature. Event identities follow original observed label intervals.
    Return slot indices as well for actual elapsed-time latency reporting.
    """
    p=np.asarray(predictions)
    if p.shape!=(len(regular),):raise ValueError('Prediction axis mismatch')
    original=regular.row_observed.to_numpy(bool)
    return regular.EVENT.to_numpy(bool)[original],p[original],regular.slot.to_numpy()[original]
