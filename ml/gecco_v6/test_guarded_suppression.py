from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from guarded_suppression import guarded_shape
from joint_calibration_v2 import combine
class GuardTests(unittest.TestCase):
    def test_unknown_and_unfamiliar_never_allow_suppression(self):
        parts={'level':np.array([.2,2,.2,.2]),'jump':np.array([.1,.1,np.nan,.1]),'sustained':np.array([.3,.3,.3,np.inf])}
        out=guarded_shape(parts,np.full(4,.01))
        self.assertEqual(out[0],.01);self.assertTrue(np.isnan(out[1:]).all())
    def test_current_evidence_must_still_be_high(self):
        b=np.zeros(5,dtype=np.int8);s=np.array([0,1,1,0,0.])
        out=combine(b,b,s,.5,'2of3')
        self.assertEqual(out[2],1);self.assertEqual(out[3],0)
    def test_prefix_invariance(self):
        s=np.arange(100)/100;b=np.zeros(100,dtype=np.int8)
        np.testing.assert_array_equal(combine(b,b,s,.5,'2of3')[:60],combine(b[:60],b[:60],s[:60],.5,'2of3'))
if __name__=='__main__':unittest.main()
