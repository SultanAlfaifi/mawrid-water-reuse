from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
import latched_suppression as ls
from departure_scores import departure_scores
class LatchTests(unittest.TestCase):
    def test_alarm_not_fragmented_after_first_retention(self):
        b=np.array([0,1,1,1,1,0,1,1,0],dtype=np.int8)
        s=np.array([1,1,0,0,1,1,0,0,1.])
        p=ls.predict(s,b,{'decision':'candidate','threshold':.5,'policy':'instant'})
        np.testing.assert_array_equal(p,[0,1,1,1,1,0,0,0,0])
    def test_suppressed_start_can_reopen_on_current_evidence(self):
        b=np.array([0,1,1,1,1,0],dtype=np.int8);s=np.array([0,0,0,1,0,0.])
        np.testing.assert_array_equal(ls.predict(s,b,{'decision':'candidate','threshold':.5,'policy':'instant'}),[0,0,0,1,1,0])
    def test_unavailability_resets_and_prefix_invariant(self):
        b=np.array([0,1,1,-1,1,1,0],dtype=np.int8);s=np.array([0,1,0,0,0,0,0.]);c={'decision':'candidate','threshold':.5,'policy':'instant'}
        p=ls.predict(s,b,c);np.testing.assert_array_equal(p,[0,1,1,-1,0,0,0])
        np.testing.assert_array_equal(p[:5],ls.predict(s[:5],b[:5],c))
    def test_departure_requires_observed_unusual_movement(self):
        c={'level':np.ones(4)*100,'sustained':np.ones(4)*100,'jump':np.array([.2,2,np.nan,1.])}
        p=departure_scores(c)
        np.testing.assert_allclose(p['level'],[0,100,np.nan,0],equal_nan=True)
        self.assertTrue(np.all(c['level']==100))
if __name__=='__main__':unittest.main()
