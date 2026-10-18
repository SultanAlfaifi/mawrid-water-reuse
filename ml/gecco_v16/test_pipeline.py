"""Actual sklearn teacher/generator smoke test on synthetic sensors only."""
import io
import unittest
import joblib
import numpy as np
import pandas as pd
from ml.gecco_v16 import teachers,model


class SyntheticPipeline(unittest.TestCase):
    def test_real_fitted_teacher_survives_freeze_and_sensor_only_forecast(self):
        rng=np.random.default_rng(20261017)
        values=rng.normal(0,.03,(3400,4))+np.arange(4)[None,:]
        y=np.zeros(3400,np.int8)
        for l,r in ((300,370),(1000,1070),(1650,1670),(2010,2040),(2800,2820),(3200,3220)):
            values[l:r]+=2;y[l:r]=1
        frame=pd.DataFrame(values,columns=['a','b','c','d'])
        bounds=[1500,1800,2100,2400,2700]
        teacher=teachers.fit_teacher(frame.iloc[:1500],y[:1500],
            [frame.iloc[l:r] for l,r in zip(bounds[:-1],bounds[1:])],
            [y[l:r] for l,r in zip(bounds[:-1],bounds[1:])],bounds[:-1],channels=list(frame))
        self.assertTrue(teacher['supported'])
        memory=io.BytesIO();joblib.dump(teacher,memory,compress=3);memory.seek(0)
        frozen=joblib.load(memory)
        self.assertIs(frozen['v8_bundle']['reference_bundle'],frozen['v6_bundle'])
        forecast=frame.iloc[2700:].copy();extra=forecast.assign(EVENT=999,label=-1,row_id=-400)
        actual=teachers.predict_teacher(frozen,forecast)
        repeated=teachers.predict_teacher(frozen,extra)
        pd.testing.assert_frame_equal(actual,repeated)
        self.assertTrue((actual[['baseline','v6','v8']].iloc[:120]==-1).all().all())
        generator=model.fit_generator(list(frame),frozen['v6_bundle']['prior_bundle']['model'].baseline_,frame.iloc[:1500],y[:1500])
        X,available,context=model.decision_matrix(generator,forecast,
            actual.v6.to_numpy(np.int8),actual.v8.to_numpy(np.int8))
        self.assertEqual(X.dtype,np.float32);self.assertEqual(X.shape[1],len(generator.feature_names_)+8)
        self.assertTrue(np.isfinite(X).all());self.assertFalse(available[:180].any())
        self.assertEqual(context['matrix'].shape,(700,8))


if __name__=='__main__':unittest.main()
