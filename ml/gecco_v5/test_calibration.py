"""Synthetic calibration contracts, including independent V5 metric parity."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parent))
import calibration as cal
from evaluation import compare_period


def blocks():
    result=[]
    for i in range(2):
        n=1000;y=np.zeros(n,dtype=bool);p=np.zeros(n,dtype=np.int8);s=np.full(n,.05)
        for start in [100,300,500]:
            y[start:start+10]=True;p[start:start+10]=1;s[start:start+10]=.9
        for start in [50,200,400,700]:p[start:start+2]=1;s[start:start+2]=.1
        result.append({"labels":y,"scores":s,"baseline_predictions":p,"source_start":i*n,"block_id":str(i)})
    return result


def select(data, **kwargs):
    return cal.calibrate(data,min_normal_minutes_per_block=10,min_observed_blocks=2,
                         min_total_normal_minutes=20,**kwargs)


class CalibrationTests(unittest.TestCase):
    def test_sensitivity_preserved_before_false_alarm_reduction(self):
        b=blocks();chosen,trials=select(b)
        self.assertEqual(chosen["decision"],"candidate")
        self.assertTrue(chosen["retains_all_baseline_events"])
        self.assertEqual(chosen["candidate_fp"],0)
        self.assertEqual(chosen["candidate_confirmed_events"],6)
        self.assertTrue(any(t["lost_baseline_event_ids"] for t in trials))

    def test_selected_metrics_match_independent_evaluation(self):
        b=blocks();chosen,_=select(b,cadence_seconds=10)
        # Short cadence needs relaxed exposure for this small synthetic fixture.
        if chosen["decision"]=="baseline":
            chosen,_=cal.calibrate(b,cadence_seconds=10,min_normal_minutes_per_block=1,
                min_observed_blocks=2,min_total_normal_minutes=2)
        y=np.concatenate([x["labels"] for x in b]);baseline=np.concatenate([x["baseline_predictions"] for x in b])
        p=np.concatenate([cal.predict(x["scores"],x["baseline_predictions"],chosen) for x in b])
        independent=compare_period(y,baseline,p,sample_seconds=10)
        m=independent["candidate"]
        self.assertEqual(chosen["candidate_confirmed_events"],m["confirmed_new_alarm_inside_events"])
        self.assertEqual(chosen["candidate_fp"],m["fp"])
        self.assertEqual(chosen["candidate_false_runs_per_day"],m["false_alarm_runs_per_normal_day"])
        self.assertEqual(chosen["hidden_baseline_rows"],independent["baseline_observed_rows_hidden_by_candidate"])
        self.assertEqual(chosen["lost_baseline_event_ids"],[x["event_id"] for x in independent["lost_baseline_events"]])

    def test_all_missing_block_is_unavailable_evidence_not_silent_threshold(self):
        b=blocks();empty={"labels":np.zeros(1000,dtype=bool),"scores":np.full(1000,np.nan),
            "baseline_predictions":np.full(1000,-1,dtype=np.int8),"source_start":1000,"block_id":"unobserved"}
        b[1]["source_start"]=2000
        chosen,_=select([b[0],empty,b[1]])
        self.assertEqual(chosen["decision"],"candidate")
        self.assertEqual(chosen["evidence"]["unobserved_block_ids"],["unobserved"])
        self.assertEqual(chosen["candidate_confirmed_events"],6)

    def test_missing_and_infinite_shape_retain_baseline_per_row(self):
        base=np.array([1,1,0,-1,1,0],dtype=np.int8)
        for policy in cal.POLICIES:
            selected={"decision":"candidate","threshold":.5,"policy":policy}
            for bad in [np.nan,np.inf,-np.inf]:
                result=cal.predict(np.full(6,bad),base,selected)
                np.testing.assert_array_equal(result,base)

    def test_unsupported_training_or_no_shape_does_not_hide_normal_rows(self):
        b=blocks()
        for x in b:x["scores"][:]=np.nan
        chosen,_=select(b)
        self.assertEqual(chosen["decision"],"baseline")
        for x in b:np.testing.assert_array_equal(cal.predict(x["scores"],x["baseline_predictions"],chosen),x["baseline_predictions"])

    def test_sparse_events_are_explicit_baseline_fallback(self):
        b=blocks()
        for x in b:x["labels"][200:]=False;x["baseline_predictions"][200:]=0
        chosen,_=select(b)
        self.assertEqual(chosen["decision"],"baseline")
        self.assertEqual(chosen["status"],"insufficient_event_representation")
        self.assertIn("few_reference_detected_events",chosen["evidence"]["representation_flags"])

    def test_no_event_calibration_never_selects_all_quiet_gate(self):
        b=blocks()
        for x in b:x["labels"][:]=False
        chosen,_=select(b)
        self.assertEqual(chosen["decision"],"baseline")

    def test_insufficient_normal_exposure_is_reported(self):
        chosen,trials=cal.calibrate(blocks())
        self.assertEqual(chosen["decision"],"baseline")
        self.assertEqual(chosen["status"],"insufficient_observed_normal_exposure")
        self.assertEqual(trials,[])

    def test_preserves_event_identity_not_equal_total(self):
        y=np.array([0,1,1,0,1,1,0],dtype=bool)
        b=np.array([0,1,0,1,1,1,0]);p=np.array([0,0,0,0,1,1,0])
        result=cal._comparison(y,b,p,60)
        self.assertEqual(result["baseline"]["confirmed_events"],1)
        self.assertEqual(result["candidate"]["confirmed_events"],1)
        self.assertEqual(result["lost_baseline_event_ids"],[1])

    def test_contiguous_event_crossing_blocks_counted_once(self):
        y=np.array([0,0,1,1,1,1,0,0],dtype=bool)
        b=np.array([0,0,1,1,0,1,0,0],dtype=np.int8)
        data=[{"labels":y[:4],"scores":np.ones(4),"baseline_predictions":b[:4],"source_start":0},
              {"labels":y[4:],"scores":np.ones(4),"baseline_predictions":b[4:],"source_start":4}]
        chosen,_=cal.calibrate(data)
        self.assertEqual(chosen["evidence"]["reference"]["true_events"],1)
        self.assertEqual(chosen["evidence"]["reference"]["confirmed_events"],1)

    def test_noncontiguous_axis_rejected(self):
        b=blocks();b[1]["source_start"]+=1
        with self.assertRaises(ValueError):select(b)

    def test_invalid_float_labels_and_baseline_rejected(self):
        for field in ["labels","baseline_predictions"]:
            b=blocks();b[0][field]=b[0][field].astype(float)
            with self.assertRaises(ValueError):select(b)
        with self.assertRaises(ValueError):cal.predict(np.zeros(2),np.array([0.,1.]),{"decision":"baseline"})

    def test_cadence_changes_exposure_rates_and_delays(self):
        y=np.array([0,0,1,1,1,0],dtype=bool);b=np.array([0,1,1,0,1,0]);p=np.array([0,0,0,0,1,0])
        sixty=cal._stats(y,b,60);ten=cal._stats(y,b,10)
        self.assertEqual(sixty["normal_observed_seconds"],ten["normal_observed_seconds"]*6)
        self.assertEqual(ten["false_runs_per_day"],sixty["false_runs_per_day"]*6)
        with self.assertRaises(ValueError):select(blocks(),cadence_seconds=0)

    def test_prediction_causality_and_missing_reset(self):
        rng=np.random.default_rng(3);score=rng.uniform(size=100);base=(rng.uniform(size=100)>.5).astype(np.int8)
        for policy in cal.POLICIES:
            chosen={"decision":"candidate","threshold":.5,"policy":policy}
            before=cal.predict(score,base,chosen);altered=score.copy();altered[60:]=np.nan
            np.testing.assert_array_equal(before[:60],cal.predict(altered,base,chosen)[:60])
            np.testing.assert_array_equal(before[:60],cal.predict(score[:60],base[:60],chosen))
            self.assertTrue(np.all(cal.predict(altered,base,chosen)[60:]==base[60:]))


if __name__=="__main__":unittest.main(verbosity=2)
