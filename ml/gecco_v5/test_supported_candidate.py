import unittest
import numpy as np
import pandas as pd
from supported_candidate import SupportedRecoveryDetector
from calibration import predict


class SupportWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng=np.random.default_rng(872)
        cls.frame=pd.DataFrame(np.cumsum(rng.normal(0,.1,(1800,3)),axis=0),columns=['x','y','z'])
        y=np.zeros(1800,bool);y[300:320]=True;y[800:820]=True
        cls.frame.loc[y,'y']+=3
        cls.model=SupportedRecoveryDetector('support_q50',['x','y','z']).fit(cls.frame,y)

    def test_unknown_shapes_preserve_baseline_alarms(self):
        altered=self.frame.copy();altered.iloc[1700:,0]+=1e8
        components=self.model.score_components(altered)
        self.assertTrue(np.isnan(components['shape'][1700]))
        base=np.ones(len(altered),dtype=np.int8)
        got=predict(components['shape'],base,{'decision':'candidate','threshold':.9,'policy':'instant'})
        self.assertEqual(got[1700],1)

    def test_base_scores_unchanged_and_future_does_not_affect_prefix(self):
        normal=self.model.score_components(self.frame)
        other=self.frame.copy();other.iloc[1600:]=np.nan
        changed=self.model.score_components(other)
        for key in normal:np.testing.assert_array_equal(normal[key][:1600],changed[key][:1600])

    def test_bounded_history_matches_supported_shape(self):
        batch=self.model.score_components(self.frame)
        for end in [200,700,1300,1799]:
            last=self.model.score_components(self.frame.iloc[end-60:end+1])
            for key in batch:np.testing.assert_allclose(batch[key][end],last[key][-1],rtol=0,atol=1e-12,equal_nan=True)

if __name__=='__main__':unittest.main()
