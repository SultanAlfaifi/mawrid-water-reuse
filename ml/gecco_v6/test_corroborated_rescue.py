from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from corroborated_rescue import corroborated_scores,fit_shape_reference
class CorroborationTests(unittest.TestCase):
    def test_large_local_step_alone_is_not_enough(self):
        c={'level':np.array([100.,100.,100.]),'jump':np.full(3,3.),'sustained':np.ones(3)*3,'shape_raw':np.array([0,.5,np.nan])}
        r=corroborated_scores(c,.1)
        np.testing.assert_allclose(r['level'],[0,100,np.nan],equal_nan=True)
        self.assertEqual(c['level'][0],100.)
    def test_reference_uses_only_normal_observed_rows(self):
        y=np.r_[np.zeros(6000,dtype=bool),True,False]
        values=np.r_[np.linspace(.01,.1,6000),100,100]
        base=np.r_[np.zeros(6001,dtype=int),-1]
        t=fit_shape_reference([{'labels':y,'baseline':base,'scores':{'shape_raw':values}}])
        self.assertAlmostEqual(t,np.quantile(values[:6000],.99))
    def test_insufficient_reference_is_explicit_unavailability(self):
        b={'labels':np.zeros(3,dtype=bool),'baseline':np.zeros(3,dtype=int),'scores':{'shape_raw':np.ones(3)}}
        self.assertIsNone(fit_shape_reference([b]))
        c={k:np.ones(3) for k in ('level','jump','sustained','shape_raw')}
        self.assertTrue(all(np.isnan(v).all() for v in corroborated_scores(c,None).values()))
if __name__=='__main__':unittest.main()
