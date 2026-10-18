"""Post-evaluation reproducibility audit, not another selection/training run."""
from pathlib import Path
import hashlib, json, sys, time
import numpy as np
import pandas as pd
import joblib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ml/gecco_v6'))
from waterhub_evaluation import verify, ARCHIVE, START, END, sha
from waterhub_loader import load_waterhub_archive
from waterhub_adapter import adapt_waterhub
from runtime_v4 import predict_frame, StreamingPredictor, SCORE_COLUMNS

def main():
    out=ROOT/'output/ml/gecco-v6-waterhub-first-use'
    result=json.loads((out/'results.json').read_text())
    assert len(result['periods'])==6
    protocol=json.loads((out/'protocol.json').read_text());verify(protocol)
    assert sha(ARCHIVE)==protocol['archive_sha256']
    audit=json.loads((out/'source_adapter_audit.json').read_text())
    expected={r['member']:r['sha256'] for r in audit['loader']['members']}
    loaded=load_waterhub_archive(ARCHIVE,expected_member_sha256=expected)
    raw1,raw2,labels=loaded.combined()
    adapted=adapt_waterhub(raw1,raw2,labels,timestamp_ambiguity_mask=loaded.timestamp_ambiguity_mask,
                          grid_start=START,grid_end=END-pd.Timedelta(minutes=1))
    saved=pd.read_csv(out/'adapted_source.csv.gz',index_col=0,parse_dates=True,float_precision='round_trip')
    pd.testing.assert_index_equal(saved.index,adapted.features.index,exact=False)
    np.testing.assert_array_equal(saved[['p1','p2','p3','p4']].to_numpy(),adapted.features.to_numpy())
    np.testing.assert_array_equal(saved.label.to_numpy(),adapted.labels.to_numpy())
    saved_audit=pd.read_csv(out/'availability_audit.csv.gz',index_col=0,parse_dates=True)
    pd.testing.assert_frame_equal(saved_audit,adapted.audit,check_dtype=False,check_freq=False,check_index_type=False)
    source_rows=len(saved);del loaded,raw1,raw2,labels,adapted,saved_audit
    streaming_rows=0;case_records=[]
    for case in (protocol['cases'][0],protocol['cases'][-1]):
        folder=out/case['name'];frozen=json.loads((folder/'freeze.json').read_text())
        assert sha(folder/'bundle.joblib')==frozen['bundle_sha256']
        bundle=joblib.load(folder/'bundle.joblib')
        a=case['test'][0];frame=saved.iloc[a:a+300]
        batch=predict_frame(bundle,frame)
        stream=StreamingPredictor(bundle).update_frame(frame)
        for key in SCORE_COLUMNS:
            np.testing.assert_allclose(batch[key],stream[key],atol=1e-12,rtol=0,equal_nan=True)
        for key in ('baseline_prediction','guarded_prediction','prediction','available','ignored_gap'):
            np.testing.assert_array_equal(batch[key],stream[key])
        # A later extreme value cannot alter the first1000 outputs.
        prefix=saved.iloc[a:a+1200].copy();changed=prefix.copy()
        changed.iloc[1000:,changed.columns.get_indexer(['p1','p2','p3','p4'])]=1e6
        original=predict_frame(bundle,prefix);perturbed=predict_frame(bundle,changed)
        for key in original.columns:
            np.testing.assert_allclose(original[key].iloc[:1000],perturbed[key].iloc[:1000],atol=1e-12,rtol=0,equal_nan=True)
        streaming_rows+=len(frame);case_records.append({'case':case['name'],'streaming_rows':len(frame),'future_perturbation_prefix_rows':1000})
    verify(protocol)
    value={'passed':True,'source_rows_rederived':source_rows,'source_sensor_values_rederived':source_rows*4,
           'source_members_verified':len(expected),'streaming_rows':streaming_rows,'cases':case_records,
           'archive_sha256':protocol['archive_sha256'],'adapted_source_sha256':sha(out/'adapted_source.csv.gz'),
           'audit_script_sha256':sha(__file__),'scope':'Post-test exact source adaptation replay and saved-model streaming/prefix parity. No selection, retraining, hardware-speed claim or actuator.'}
    (out/'source_runtime_replay_audit.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value))

if __name__=='__main__':main()
