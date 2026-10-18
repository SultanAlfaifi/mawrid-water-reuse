"""Label-blind source integrity and overlap check before a new evaluation.

Does not load EVENT/Event values. Duplicate sensor rows can occur naturally;
the window comparison additionally checks consecutive 60-row sensor sequences.
"""
from pathlib import Path
import hashlib
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
NEW = ROOT / 'data/external/gecco2017/1_gecco2017_water_quality.csv'
OLD = ROOT / 'data/external/gecco2018/1_gecco2018_water_quality.csv'

def read_blind(path):
    return pd.read_csv(path, usecols=lambda name: name.lower() not in {'event', 'label', 'anomaly'})

def windows(frame, channels, length=60):
    hashes = pd.util.hash_pandas_object(frame[channels], index=False).to_numpy(dtype=np.uint64)
    # Exact binary window digest, every start, no labels or timestamps.
    clean = np.isfinite(frame[channels].to_numpy()).all(axis=1)
    complete = np.convolve(clean.astype(int), np.ones(length, dtype=int), mode='valid') == length
    return {hashlib.blake2b(hashes[i:i+length].tobytes(), digest_size=16).digest()
            for i in range(len(hashes)-length+1) if complete[i]}

def main():
    a, b = read_blind(NEW), read_blind(OLD)
    channels = [c for c in a if c not in {'Time', 'Unnamed: 0'}]
    time_a, time_b = pd.to_datetime(a.Time), pd.to_datetime(b.Time)
    original = NEW.read_bytes()
    official = 'e5d0b266b586ac6f602fd6bd789ec8ed'
    assert hashlib.md5(original).hexdigest() == official
    result = {
        'audited_at_utc': datetime.now(timezone.utc).isoformat(),
        'source': 'https://zenodo.org/records/3884465',
        'file': str(NEW.relative_to(ROOT)),
        'bytes': len(original), 'rows': len(a), 'channels': channels,
        'sha256': hashlib.sha256(original).hexdigest(),
        'md5_verified_against_publisher': official,
        'labels_loaded': False, 'first_timestamp': str(time_a.iloc[0]),
        'last_timestamp': str(time_a.iloc[-1]),
        'negative_clock_steps': int((time_a.diff().dt.total_seconds() < 0).sum()),
        'non_60_second_steps': int((time_a.diff().dt.total_seconds().dropna() != 60).sum()),
        'timestamps_overlapping_2018': int(time_a.isin(time_b).sum()),
        'exact_sensor_60_row_windows_overlapping_2018': len(windows(a, channels) & windows(b, channels)),
        'window_overlap_definition': 'Only fully observed windows; all-missing sequences are not evidence of copied measurements.',
        'timestamps_overlapping_2019': {},
        'interpretation': 'Previously unused historical dataset. Earlier in calendar time than development datasets. Not a future field deployment or a new-site claim. Method design used later historical datasets; fitted parameters for this evaluation must use only local chronological past.'
    }
    for p in sorted((ROOT / 'data/external/gecco2019').glob('*.csv')):
        old_times = pd.to_datetime(pd.read_csv(p, usecols=['Time']).Time)
        result['timestamps_overlapping_2019'][p.name] = int(time_a.isin(old_times).sum())
    assert result['timestamps_overlapping_2018'] == 0
    assert result['exact_sensor_60_row_windows_overlapping_2018'] == 0
    assert not any(result['timestamps_overlapping_2019'].values())
    destination = ROOT / 'output/ml/gecco-v4-diagnostics/new_source_audit.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert not destination.exists(), 'Preserve original blind audit'
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
