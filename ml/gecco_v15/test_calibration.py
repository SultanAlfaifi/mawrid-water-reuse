"""Synthetic tests of time separation, veto-only semantics and fixed grid."""
import unittest
from unittest.mock import patch
import numpy as np
from ml.gecco_v15 import calibration as c


class CalibrationTests(unittest.TestCase):
    def test_finite_grid_is_unique_fixed_quantiles(self):
        self.assertEqual(c._grid([np.nan,np.inf,-np.inf]),[])
        np.testing.assert_allclose(c._grid([0.,1.,np.nan]),[0,.25,.5,.75,.9,.95,1])
        self.assertEqual(c._grid([.2,.2]),[.2])

    def test_selection_only_receives_two_earlier_blocks(self):
        with self.assertRaises(ValueError): c.select_earlier([{}, {}, {}])
        with self.assertRaises(ValueError): c.calibrate([{}, {}, {}])

    def test_later_veto_cannot_choose_different_early_policy(self):
        blocks=[{'id':i} for i in range(4)]
        proposed=c.choice(.2,.8)
        calls=[]
        def evaluate(b,selected,**kwargs):
            calls.append(([x['id'] for x in b],dict(selected)))
            return {'passed':False}
        with patch.object(c.checks,'validate_blocks',side_effect=lambda b:b), \
             patch.object(c,'select_earlier',return_value=(proposed,[{'feasible':True}])), \
             patch.object(c,'evaluate',side_effect=evaluate):
            result,trials=c.calibrate(blocks)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['choice'],c.choice())
        self.assertEqual(calls[0],([2,3],proposed))
        self.assertEqual(calls[1],([0,1,2,3],proposed))
        self.assertEqual(calls[2],([0,1,2,3],c.choice()))
        self.assertEqual(proposed,c.choice(.2,.8))

    def test_no_feasible_earlier_choice_does_not_search_later(self):
        blocks=[{'id':i} for i in range(4)]
        with patch.object(c.checks,'validate_blocks',side_effect=lambda b:b), \
             patch.object(c,'select_earlier',return_value=(None,[{'feasible':False}])), \
             patch.object(c,'evaluate',return_value={'passed':False}) as evaluate:
            result,_=c.calibrate(blocks)
        self.assertEqual(evaluate.call_count,1)
        self.assertIsNone(result['later_certificate'])
        self.assertFalse(result['accepted'])
        self.assertEqual(result['status'],'unsupported_v8_identity_fallback')

    def test_rank_costs_and_actual_events_precede_true_positive_duration(self):
        def trial(events,fp,runs,tp):
            return {'choice':c.choice(.3,None),'metrics':{'confirmed_events':events,
                'false_positive_runs':runs,'fp':fp,'tp':tp}}
        self.assertLess(c._rank(trial(2,10,2,3)),c._rank(trial(1,0,0,100)))
        self.assertLess(c._rank(trial(2,3,1,3)),c._rank(trial(2,2,2,100)))
        self.assertLess(c._rank(trial(2,2,1,3)),c._rank(trial(2,3,1,100)))


if __name__=='__main__': unittest.main()
