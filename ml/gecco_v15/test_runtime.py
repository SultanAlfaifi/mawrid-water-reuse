"""Synthetic V15 policy tests. No source rows, bundles or cached outputs."""
from __future__ import annotations

import itertools
import unittest

import numpy as np

from ml.gecco_v7.calibration_delayed import _confirmed_seed
from ml.gecco_v15.runtime import components, predict


def choice(low=None, high=None):
    return {"anchor_threshold": low, "recovery_threshold": high, "cadence_seconds": 60}


def scalar(v6, v8, scores, selected):
    """Independent explicit state oracle, including cancellation before hits."""
    seed = np.asarray(v8, dtype=np.int8).copy()
    recover = np.where(np.asarray(v8) < 0, -1, 0).astype(np.int8)
    low, high = selected["anchor_threshold"], selected["recovery_threshold"]
    anchor_start = None
    anchor_open = False
    request = None
    for i, (a, b, score) in enumerate(zip(v6, v8, scores)):
        if b != 1:
            anchor_start = None
            anchor_open = False
        else:
            if anchor_start is None:
                anchor_start = i
            if low is None or not np.isfinite(score) or score >= low or i - anchor_start >= 2:
                anchor_open = True
            seed[i] = int(anchor_open)
        if high is None:
            continue
        if a < 0 or b < 0:
            request = None
            continue
        known_start = i > 0 and a == 1 and v6[i - 1] == 0
        if known_start:
            request = {"start": i, "cleared": False, "latched": False} if b == 0 else None
        if request is None:
            continue
        if request["latched"]:
            if a == 1:
                recover[i] = int(b == 0)
            else:
                request = None
            continue
        if a == 0:
            request["cleared"] = True
        if i - request["start"] > 2:
            request = None
            continue
        if np.isfinite(score) and score >= high:
            if request["cleared"]:
                recover[i] = 1
                request = None
            else:
                request["latched"] = True
                recover[i] = int(b == 0)
    final = seed.copy()
    final[recover == 1] = 1
    return {"seed": seed, "recovery": recover, "final": final}


class RuntimeTests(unittest.TestCase):
    def run_policy(self, v6, v8, scores, low=None, high=None):
        return components(np.asarray(v6, np.int8), np.asarray(v8, np.int8), np.asarray(scores, float), choice(low, high))

    def test_identity_empty_dtype_and_read_only_inputs(self):
        for values in [[], [-1, 0, 1, 1, 0, -1]]:
            a = np.array(values, np.int8); s = np.full(len(a), np.nan); before = a.copy()
            got = components(a, a, s, choice())
            for x in got.values(): self.assertEqual(x.dtype, np.int8)
            np.testing.assert_array_equal(got['final'], before)
            np.testing.assert_array_equal(a, before)
            self.assertFalse(np.shares_memory(got['seed'], got['final']))
            self.assertFalse(np.shares_memory(got['recovery'], got['final']))

    def test_anchor_exact_frozen_confirmation_and_no_postclear(self):
        ref = np.array([0,1,0,0,1,1,1,1,-1,1,0], np.int8)
        score = np.array([0,0,0,1,0,0,0,0,0,np.nan,0.])
        got = components(ref, ref, score, choice(.5))
        np.testing.assert_array_equal(got['seed'], _confirmed_seed(ref, score, .5, 2))
        np.testing.assert_array_equal(got['final'], [0,0,0,0,0,0,1,1,-1,1,0])

    def test_recovery_offset_zero_and_latches_despite_low_later_scores(self):
        got = self.run_policy([0,1,1,1,0], [0,0,0,0,0], [0,.5,0,0,1], high=.5)
        np.testing.assert_array_equal(got['recovery'], [0,1,1,1,0])

    def test_hit_offset_two_after_clear_once_and_no_backdating(self):
        got = self.run_policy([0,1,0,0,0], [0,0,0,0,0], [0,0,0,.5,1], high=.5)
        np.testing.assert_array_equal(got['recovery'], [0,0,0,1,0])

    def test_postclear_release_can_restore_suppressed_v8_alarm(self):
        got = self.run_policy([0,1,0,0], [0,0,1,1], [0,0,.6,0], low=.9, high=.5)
        np.testing.assert_array_equal(got['seed'], [0,0,0,0])
        np.testing.assert_array_equal(got['recovery'], [0,0,1,0])
        np.testing.assert_array_equal(got['final'], [0,0,1,0])

    def test_new_ineligible_v6_pulse_cancels_old_pending_before_hit(self):
        got = self.run_policy([0,1,0,1,0], [0,0,0,1,0], [0,0,0,1,1], high=.5)
        np.testing.assert_array_equal(got['recovery'], [0,0,0,0,0])

    def test_new_eligible_pulse_owns_new_deadline(self):
        got = self.run_policy([0,1,0,1,1,1,1], [0]*7, [0,0,0,0,0,1,0], high=.5)
        np.testing.assert_array_equal(got['recovery'], [0,0,0,0,0,1,1])

    def test_no_force_after_timeout_or_censored_onsets(self):
        for v6 in [[1,1,1,1,1], [-1,1,1,1,1], [0,1,1,1,1]]:
            got = self.run_policy(v6, [0]*5, [0,0,0,0,1], high=.5)
            np.testing.assert_array_equal(got['recovery'], [0]*5)

    def test_v8_clear_does_not_create_mid_v6_trigger(self):
        got = self.run_policy([0,1,1,1,0], [0,1,0,0,0], [1]*5, high=.5)
        np.testing.assert_array_equal(got['recovery'], [0]*5)

    def test_each_reference_unknown_cancels_seeking_and_latched(self):
        cases = [([0,1,-1,0,0], [0]*5), ([0,1,0,0,0], [0,0,-1,0,0])]
        for a,b in cases:
            got = self.run_policy(a,b,[0,0,0,1,1], high=.5)
            self.assertFalse((got['recovery'] == 1).any())
            np.testing.assert_array_equal(got['final'] >= 0, np.array(b) >= 0)
        got = self.run_policy([0,1,1,1,1], [0,0,-1,0,0], [1]*5, high=.5)
        np.testing.assert_array_equal(got['recovery'], [0,1,-1,0,0])

    def test_nan_inf_scores_release_anchor_but_never_trigger_recovery(self):
        for value in [np.nan,np.inf,-np.inf]:
            got = self.run_policy([0,1,1,1], [0,0,1,1], [0,value,value,value], low=.5, high=.5)
            np.testing.assert_array_equal(got['recovery'], [0]*4)
            np.testing.assert_array_equal(got['seed'], [0,0,1,1])

    def test_hit_when_v8_high_latches_but_emits_only_on_v8_quiet(self):
        got = self.run_policy([0,1,1,1,1,0], [0,0,1,0,0,0], [0,0,1,0,0,0], high=.5)
        np.testing.assert_array_equal(got['recovery'], [0,0,0,1,1,0])

    def test_merged_alarm_can_remove_known_event_transition(self):
        # Synthetic label onset at row2: seed confirms0->1 there; recovery fills
        # row1, so final has no new0->1 at row2. Never equate branch OR with
        # retention of confirmed event onsets.
        got = self.run_policy([0,1,1,0], [0,0,1,0], [1]*4, high=.5)
        self.assertEqual((got['seed'][1],got['seed'][2]),(0,1))
        self.assertEqual((got['final'][1],got['final'][2]),(1,1))

    def test_scalar_oracle_exhaustive_short_original_axes(self):
        for n in range(4):
            for left in itertools.product([-1,0,1],repeat=n):
                for right in itertools.product([-1,0,1],repeat=n):
                    scores = np.array(([0,.6,np.nan]*2)[:n],float)
                    a,b = np.array(left,np.int8),np.array(right,np.int8)
                    for selected in [choice(),choice(.5),choice(None,.5),choice(.8,.5)]:
                        actual,expected = components(a,b,scores,selected),scalar(a,b,scores,selected)
                        for key in actual:np.testing.assert_array_equal(actual[key],expected[key])

    def test_prefix_future_mutation_and_deterministic_random_scalar_parity(self):
        rng=np.random.default_rng(20261017)
        a=rng.choice([-1,0,1],220,p=[.04,.45,.51]).astype(np.int8)
        b=rng.choice([-1,0,1],220,p=[.03,.5,.47]).astype(np.int8)
        s=rng.random(220);s[::17]=np.nan;s[::29]=np.inf
        for selected in [choice(),choice(.4),choice(None,.7),choice(.8,.3)]:
            full=components(a,b,s,selected);oracle=scalar(a,b,s,selected)
            for k in full:np.testing.assert_array_equal(full[k],oracle[k])
            for stop in [0,1,2,3,17,64,150,220]:
                prefix=components(a[:stop],b[:stop],s[:stop],selected)
                for k in full:np.testing.assert_array_equal(prefix[k],full[k][:stop])
                aa,bb,ss=a.copy(),b.copy(),s.copy();aa[stop:]=1;bb[stop:]=0;ss[stop:]=100
                changed=components(aa,bb,ss,selected)
                for k in full:np.testing.assert_array_equal(changed[k][:stop],full[k][:stop])
            np.testing.assert_array_equal(predict(a,b,s,selected),full['final'])

    def test_invalid_shapes_values_types_thresholds_and_cadence(self):
        good=np.array([0,1],np.int8)
        for bad in [np.array([0.,1.]),np.array([False,True]),np.array([0,2]),np.array([[0,1]]),np.array([0])]:
            with self.assertRaises(ValueError):components(bad,good,[.1,.2],choice())
            with self.assertRaises(ValueError):components(good,bad,[.1,.2],choice())
        for bad in [[.1],[[.1,.2]],['0','1'],[True,False],[1j,0]]:
            with self.assertRaises(ValueError):components(good,good,bad,choice())
        for key in ['anchor_threshold','recovery_threshold']:
            for value in [True,np.bool_(False),np.nan,np.inf,[.2],'0.2',1j,10**1000]:
                invalid=choice();invalid[key]=value
                with self.assertRaises(ValueError):components(good,good,[.1,.2],invalid)
        for value in [None,True,0,1,59,61,np.nan,np.inf,'60',[60],10**1000]:
            invalid=choice();invalid['cadence_seconds']=value
            with self.assertRaises(ValueError):components(good,good,[.1,.2],invalid)
        for bad in [{},None,[]]:
            with self.assertRaises(ValueError):components(good,good,[.1,.2],bad)


if __name__ == '__main__':
    unittest.main()
