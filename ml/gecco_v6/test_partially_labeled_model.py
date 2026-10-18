from pathlib import Path
import sys,unittest
from unittest.mock import patch
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
from partially_labeled_model import PartiallyLabeledRecoveryDetector,RecoveryEventDetector
class PartialLabelTests(unittest.TestCase):
    @staticmethod
    def fixture():
        rng=np.random.default_rng(413);x=pd.DataFrame(rng.normal(size=(1200,3)),columns=['a','b','c']);y=np.zeros(1200,dtype=np.int8)
        y[400:420]=1;y[800:825]=1;x.iloc[400:420,0]+=5;x.iloc[800:825,1]-=5
        return x,y
    def test_all_known_exactly_matches_original_trainer(self):
        x,y=self.fixture();a=RecoveryEventDetector(channels=list(x)).fit(x,y);b=PartiallyLabeledRecoveryDetector(channels=list(x)).fit(x,y)
        for key,value in a.score_components(x).items():np.testing.assert_allclose(value,b.score_components(x)[key],rtol=0,atol=0,equal_nan=True)
        np.testing.assert_array_equal(a.noise_floor_,b.noise_floor_)
    def test_unknown_rows_are_not_supervised_and_exclude_normal_windows(self):
        x,y=self.fixture();y[100:300]=-1;m=PartiallyLabeledRecoveryDetector(channels=list(x)).fit(x,y)
        self.assertFalse(m.normal_scale_window_mask_[100:360].any())
        _,eligible=m.features(x);self.assertEqual(m.fit_rows_,int((eligible&(y>=0)).sum()))
    def test_all_unknown_is_not_normal_training(self):
        x,y=self.fixture();m=PartiallyLabeledRecoveryDetector(channels=list(x)).fit(x,np.full(len(x),-1,dtype=np.int8))
        self.assertIsNone(m.baseline_);self.assertIsNone(m.shape_)
        self.assertEqual(m.baseline_fit_rows_,0)
        self.assertTrue(all(np.isnan(v).all() for v in m.score_components(x).values()))
    def test_unknown_scores_do_not_change_normal_tail_or_negative_weights(self):
        # Change only IF scores at unknown-label rows, not any measured feature.
        # Neither the known-normal q95 nor the resulting training weights may move.
        x,y=self.fixture();y[100:300]=-1
        known_scores=np.linspace(.1,.9,len(x));weights=[];targets=[]
        class CaptureClassifier:
            def __init__(self,**kwargs):pass
            def fit(self,X,target,sample_weight):
                targets.append(target.copy());weights.append(sample_weight.copy());return self
        for unknown_score in (-1e6,1e6):
            scores=known_scores.copy();scores[y<0]=unknown_score
            with patch('partially_labeled_model.ExtraTreesClassifier',CaptureClassifier), \
                 patch.object(PartiallyLabeledRecoveryDetector,'_baseline_score',return_value=scores):
                m=PartiallyLabeledRecoveryDetector(channels=list(x)).fit(x,y)
        np.testing.assert_array_equal(targets[0],targets[1])
        np.testing.assert_array_equal(weights[0],weights[1])
        # Unknown-label sensor history remains measured context for known rows.
        features,_=m.features(x);changed=x.copy();changed.iloc[100:300]+=100
        changed_features,_=m.features(changed)
        self.assertTrue(np.any(features[300]!=changed_features[300]))
if __name__=='__main__':unittest.main()
