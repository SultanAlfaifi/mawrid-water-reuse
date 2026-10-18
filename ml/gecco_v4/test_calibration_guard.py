"""No real dataset access: guard an unavailable calibration explicitly."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from checked_predict import checked_predict_frame,readiness_reason

class CalibrationGuardTests(unittest.TestCase):
    def test_empty_or_infeasible_calibration_never_emits_normal(self):
        frame=pd.DataFrame({'sensor':[1.,2.,3.]})
        for selection in [{},{'calibration_status':'no_feasible_operating_point_all_silent','feasible_all_blocks':False}]:
            with patch('checked_predict.predict_frame',side_effect=AssertionError('Must not score')):
                result=checked_predict_frame({},selection,frame)
            np.testing.assert_array_equal(result.prediction,[-1,-1,-1])
            self.assertTrue(result.score.isna().all())
            self.assertFalse(result.calibration_ready.any())

    def test_known_zero_event_block_is_not_ready(self):
        s={'calibration_status':'feasible_all_blocks','feasible_all_blocks':True,
           'complete_events':6,'worst_event_block_recall':0}
        self.assertEqual(readiness_reason(s),'calibration_missed_all_events_in_a_block')

    def test_guard_does_not_change_predictions_when_past_calibration_passes(self):
        s={'calibration_status':'feasible_all_blocks','feasible_all_blocks':True,
           'complete_events':6,'worst_event_block_recall':.5}
        expected=pd.DataFrame({'prediction':[-1,0,1]})
        with patch('checked_predict.predict_frame',return_value=expected.copy()) as score:
            result=checked_predict_frame({},s,pd.DataFrame({'sensor':[1,2,3]}))
        score.assert_called_once()
        np.testing.assert_array_equal(result.prediction,expected.prediction)
        self.assertTrue(result.calibration_ready.all())

if __name__=='__main__':unittest.main()
