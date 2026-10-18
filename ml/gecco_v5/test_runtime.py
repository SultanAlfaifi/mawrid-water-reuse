import unittest
import numpy as np
import pandas as pd
from recovery_candidate import RecoveryEventDetector
from runtime import predict_frame,predict_last,required_history_rows


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(900)
        cls.frame = pd.DataFrame(np.cumsum(rng.normal(size=(900,3)),axis=0),columns=['x','y','z'])
        y = np.zeros(900,bool);y[200:220] = True;y[500:520] = True
        cls.frame.loc[y,'y'] += 30
        cls.model = RecoveryEventDetector('shape_invariant',['x','y','z']).fit(cls.frame,y)

    def bundle(self,policy='instant'):
        return {'model':self.model,'baseline_threshold':.55,'baseline_policy':'instant',
            'selected':{'decision':'candidate','threshold':.1,'policy':policy,'status':'synthetic_test_selection'}}

    def test_bounded_memory_matches_batch_all_policies(self):
        for policy in ['instant','2of3','3of5']:
            bundle = self.bundle(policy)
            batch = predict_frame(bundle,self.frame)
            for row in [20,40,100,205,530,899]:
                got = predict_last(bundle,self.frame.iloc[:row+1])
                self.assertEqual(got['prediction'],batch.prediction.iloc[row])
                self.assertEqual(got['baseline_prediction'],batch.baseline_prediction.iloc[row])
                if np.isfinite(got['shape_score']):self.assertAlmostEqual(got['shape_score'],batch.shape_score.iloc[row],places=14)
        self.assertEqual(required_history_rows(self.bundle('3of5')),64)

    def test_fallback_is_explicit_and_baseline_unchanged(self):
        bundle = self.bundle();bundle['selected'] = {'decision':'baseline','status':'insufficient_event_representation','threshold':None,'policy':None}
        got = predict_frame(bundle,self.frame)
        np.testing.assert_array_equal(got.prediction,got.baseline_prediction)
        self.assertTrue((got.calibration_status == 'insufficient_event_representation').all())

    def test_missing_current_is_unavailable(self):
        frame = self.frame.copy();frame.iloc[-1,0] = np.nan
        result = predict_last(self.bundle(),frame)
        self.assertEqual(result['prediction'],-1)
        self.assertFalse(result['available'])
        self.assertEqual(result['reason'],'baseline_unavailable')

    def test_metadata_and_labels_are_not_model_inputs(self):
        plain = predict_frame(self.bundle(),self.frame)
        enriched = predict_frame(self.bundle(),self.frame.assign(EVENT=True,Time='arbitrary'))
        pd.testing.assert_frame_equal(plain,enriched)

if __name__ == '__main__':unittest.main()
