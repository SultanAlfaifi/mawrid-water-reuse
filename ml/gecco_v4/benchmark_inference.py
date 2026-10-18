"""Verify saved predictions and bounded-history inference, then time local CPU."""
from pathlib import Path
import argparse
import hashlib
import json
import platform
import sys
import time

import joblib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
from predict import predict_frame
from run_evaluation import check, SOURCES, GAP

def main(out, source_id):
    check(out)
    parent=out/('external_2017' if source_id=='2017' else 'development_2018')
    assert (parent/'results.json').exists(), 'Do not expose incomplete external evaluation'
    folder=parent/'fold_6'
    frozen=json.loads((folder/'freeze.json').read_text())
    model_path=folder/'v4_model.joblib'
    digest=hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert digest==frozen['model_sha256']['v4']
    bundle=joblib.load(model_path)
    start,end=frozen['test']
    raw=pd.read_csv(SOURCES[source_id],nrows=end).iloc[start+GAP:end].reset_index(drop=True)
    saved=pd.read_csv(folder/'test_predictions.csv.gz').iloc[GAP:].reset_index(drop=True)
    actual=predict_frame(bundle,raw)
    np.testing.assert_allclose(actual.score,saved.v4_score,rtol=0,atol=1e-10,equal_nan=True)
    np.testing.assert_array_equal(actual.prediction,saved.v4_prediction)
    model=bundle['model']
    lookback=int(getattr(model,'max_lookback_',getattr(model,'max_lookback',60)))
    length=lookback+5
    candidates=np.flatnonzero((actual.decision_available.to_numpy()) & (np.arange(len(raw))>=length-1))
    indices=candidates[np.linspace(0,len(candidates)-1,min(100,len(candidates)),dtype=int)]
    milliseconds=[]
    for index in indices:
        begin=time.perf_counter()
        current=predict_frame(bundle,raw.iloc[index-length+1:index+1]).iloc[-1]
        milliseconds.append((time.perf_counter()-begin)*1000)
        assert int(current.prediction)==int(actual.iloc[index].prediction)
        np.testing.assert_allclose(current.score,actual.iloc[index].score,rtol=0,atol=1e-10,equal_nan=True)
    result={'platform':platform.platform(),'machine':platform.machine(),'source_id':source_id,
        'model_bytes':model_path.stat().st_size,'model_sha256':digest,
        'maximum_feature_predecessors':lookback,'bounded_input_rows':length,'samples':len(indices),
        'full_saved_scores_and_predictions_match':True,'bounded_history_matches_batch':True,
        'median_ms':float(np.median(milliseconds)),'p95_ms':float(np.percentile(milliseconds,95)),
        'scope':'Local Mac CPU offline inference including feature construction and policy, excluding sensor I/O, model loading, network and 3D. No Raspberry Pi measurement.',
        'no_3d_or_valve_connection':True}
    path=out/'runtime.json'
    assert not path.exists(), 'Preserve benchmark results'
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=ROOT/'output/ml/gecco-v4')
    parser.add_argument('--source',choices=['2017','2018'],default='2017')
    args=parser.parse_args()
    main(args.output_dir,args.source)
