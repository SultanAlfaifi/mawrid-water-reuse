from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
import source_suppression as ss,latched_suppression as old_s
import source_joint_calibration as sj,joint_calibration_v2 as old_j
class SourceCalibrationTests(unittest.TestCase):
    @staticmethod
    def blocks():
        rows=[]
        for i in range(2):
            y=np.zeros(1000,dtype=np.int8);b=np.zeros(1000,dtype=np.int8);s=np.full(1000,.05)
            for a in [100,300,500]:y[a:a+10]=1;b[a:a+10]=1;s[a:a+10]=.9
            for a in [50,200,400,700]:b[a:a+2]=1
            rows.append(dict(labels=y,scores=s,baseline_predictions=b,source_start=i*1000))
        return rows
    def test_all_known_suppression_matches_original(self):
        b=self.blocks();kw=dict(min_normal_minutes_per_block=10,min_total_normal_minutes=20)
        a,_=old_s.calibrate(b,**kw);c,_=ss.calibrate(b,**kw)
        for key in ['decision','threshold','policy','candidate_fp','candidate_confirmed_events']:self.assertEqual(a[key],c[key])
        for block in b:np.testing.assert_array_equal(old_s.predict(block['scores'],block['baseline_predictions'],a),ss.predict(block['scores'],block['baseline_predictions'],c))
    def test_unknown_labels_cannot_supply_normal_exposure(self):
        b=self.blocks()
        for block in b:block['labels'][:]=-1
        choice,_=ss.calibrate(b);self.assertEqual(choice['status'],'insufficient_observed_normal_exposure')
        self.assertEqual(choice['evidence']['reference']['true_events'],0)
        self.assertEqual(choice['evidence']['reference']['normal_observed_seconds'],0)
    def test_unknown_break_does_not_invent_an_onset(self):
        b=self.blocks();b[0]['labels'][90:100]=-1
        choice,_=ss.calibrate(b)
        self.assertEqual(choice['evidence']['reference']['true_events'],5)
        self.assertEqual(choice['evidence']['reference']['left_censored_positive_segments'],1)
    def test_all_known_joint_matches_original(self):
        blocks=[]
        for b in self.blocks():
            base=b['baseline_predictions'].copy();base[500:510]=0
            guard=base.copy();guard[50:52]=0
            blocks.append(dict(labels=b['labels'],baseline=base,guarded=guard,scores={'local':b['scores']},source_start=b['source_start']))
        kw=dict(min_normal_minutes_per_block=10,min_total_normal_minutes=20)
        a,_=old_j.calibrate(blocks,**kw);c,_=sj.calibrate(blocks,**kw)
        for key in ['seed','rescue','threshold','policy','events','false_runs','fp']:self.assertEqual(a[key],c[key])
    def test_prediction_independent_of_label_accounting(self):
        rng=np.random.default_rng(9);b=rng.integers(-1,2,500,dtype=np.int8);s=rng.uniform(size=500)
        for policy in ['instant','2of3','3of5']:
            decision=dict(decision='candidate',threshold=.5,policy=policy)
            np.testing.assert_array_equal(ss.predict(s,b,decision),old_s.predict(s,b,decision))
            np.testing.assert_array_equal(sj.combine(b,b,s,.5,policy),old_j.combine(b,b,s,.5,policy))
if __name__=='__main__':unittest.main()
