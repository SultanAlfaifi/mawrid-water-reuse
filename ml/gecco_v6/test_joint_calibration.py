from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from joint_calibration import combine,predict,calibrate

class JointTests(unittest.TestCase):
    def data(self):
        out=[]
        for k in range(2):
            y=np.zeros(1000,dtype=bool);b=np.zeros(1000,dtype=np.int8);s=np.zeros(1000)
            for a in [100,300,500]:y[a:a+10]=True;s[a:a+10]=1
            b[100:110]=1;b[300:310]=1;b[700]=1
            seed=b.copy();seed[700]=0
            out.append(dict(labels=y,baseline=b,q50=seed,scores={'local':s},source_start=k*1000))
        return out
    def select(self,data):
        return calibrate(data,min_normal_minutes_per_block=10,min_total_normal_minutes=20)
    def test_recovers_missed_ids_without_false_alarm_cost(self):
        chosen,_=self.select(self.data())
        self.assertEqual(chosen['events'],6);self.assertEqual(chosen['false_runs'],0)
        self.assertEqual(chosen['rescue'],'local');self.assertEqual(chosen['seed'],'q50')
    def test_unknown_does_not_create_or_hide_observations(self):
        b=np.array([-1,0,1,0],dtype=np.int8)
        np.testing.assert_array_equal(combine(b,b,np.full(4,np.nan),.5),b)
        p=combine(b,b,np.ones(4),.5);self.assertEqual(p[0],-1)
        with self.assertRaises(ValueError):combine(b,np.array([0,0,1,0]))
    def test_early_rescue_can_erase_onset_and_is_rejected(self):
        data=self.data()
        for block in data:block['scores']['local'][95:100]=1
        chosen,trials=self.select(data)
        self.assertIsNone(chosen['rescue'])
        self.assertTrue(any(t['lost_event_ids'] for t in trials))
    def test_more_false_time_is_rejected(self):
        data=self.data()
        for block in data:block['scores']['local'][600:620]=1
        chosen,_=self.select(data);self.assertIsNone(chosen['rescue'])
    def test_prefix_invariance(self):
        b=np.zeros(100,dtype=np.int8);s=np.arange(100,dtype=float)
        for policy in ['instant','2of3','3of5']:
            p=combine(b,b,s,50,policy)
            np.testing.assert_array_equal(p[:60],combine(b[:60],b[:60],s[:60],50,policy))
    def test_insufficient_event_evidence_disables_rescue(self):
        data=self.data();chosen,_=calibrate(data,min_events=100)
        self.assertIsNone(chosen['rescue'])
    def test_invalid_configuration_rejected(self):
        for value in [float('nan'),float('inf'),0,-1]:
            with self.assertRaises(ValueError):calibrate(self.data(),cadence_seconds=value)
            with self.assertRaises(ValueError):calibrate(self.data(),min_events=value)
    def test_noncontiguous_axis_rejected(self):
        data=self.data();data[1]['source_start']+=1
        with self.assertRaises(ValueError):self.select(data)
if __name__=='__main__':unittest.main()
