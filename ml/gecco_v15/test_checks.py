"""Synthetic-only independent checks for the fixed V15 calibration contract."""
import copy
import json
import unittest
from unittest.mock import patch

import numpy as np

from ml.gecco_v15 import checks as c
from ml.gecco_v6.unknown_label_metrics import stats


def block(labels, v6=None, v8=None, *, start=0, identifier='0'):
    y = np.asarray(labels, np.int8)
    r = np.zeros(len(y), np.int8) if v6 is None else np.asarray(v6, np.int8)
    return {'labels': y, 'v6': r, 'v8': r.copy() if v8 is None else np.asarray(v8, np.int8),
            'scores': np.full(len(y), .5), 'source_start': start, 'block_id': identifier}


class ValidationTests(unittest.TestCase):
    def test_validation_preserves_unknowns_and_is_idempotent_without_mutation(self):
        b = block([0, -1, 1], [0, 1, -1]); b['scores'] = np.array([np.nan, np.inf, -np.inf])
        before = copy.deepcopy(b); clean = c.validate_blocks([b]); again = c.validate_blocks(clean)
        for key in ('labels', 'v6', 'v8', 'scores'):
            np.testing.assert_array_equal(clean[0][key], before[key])
            np.testing.assert_array_equal(again[0][key], before[key])
            np.testing.assert_array_equal(b[key], before[key])

    def test_rejects_malformed_ternary_axes_scores_coordinates_and_ids(self):
        mutations = [lambda b: b.update(labels=np.array([0., 1., 0.])),
            lambda b: b.update(v6=np.array([0, 2, 0])), lambda b: b.update(v8=np.zeros((3, 1), int)),
            lambda b: b.update(scores=['.1', '.2', '.3']), lambda b: b.update(scores=np.zeros(3, complex)),
            lambda b: b.update(scores=np.zeros(3, bool)), lambda b: b.update(scores=np.zeros(2)),
            lambda b: b.update(source_start=True), lambda b: b.update(source_start=0.),
            lambda b: b.update(source_start=-1), lambda b: b.update(source_start=2**63),
            lambda b: b.update(block_id=''), lambda b: b.update(block_id=False)]
        for mutate in mutations:
            b = block([0, 1, 0]); mutate(b)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): c.validate_blocks([b])
        for blocks in ([], [block([])], [{}], [block([0]), block([0], start=2, identifier='1')],
                       [block([0]), block([0], start=1, identifier='0')]):
            with self.assertRaises(ValueError): c.validate_blocks(blocks)
        for cadence in (True, 0, 10, 120, 300, np.nan, np.inf, '60'):
            with self.assertRaises(ValueError): c.validate_blocks([block([0])], cadence_seconds=cadence)

    def test_predictions_and_reference_arguments_are_strict(self):
        b = [block([0, 1, 0])]
        for predictions in ([], [[0, 1]], [[0., 1., 0.]], [[0, 2, 0]], np.array([[0, 1, 0]])):
            with self.assertRaises(ValueError): c.assess(b, predictions)
        for refs in ((), ('v9',), ('v6', 'v6'), 'v6'):
            with self.assertRaises(ValueError): c.assess(b, [[0, 1, 0]], refs=refs)
        with self.assertRaises(ValueError): c.assess(b, [[0, 1, 0]], pulses=1)


class JointAssessmentTests(unittest.TestCase):
    def test_same_event_count_does_not_substitute_for_both_reference_ids(self):
        b = block([0, 1, 0, 1, 0], [0, 1, 0, 0, 0], [0, 0, 0, 1, 0])
        r = c.assess([b], [b['v8']])
        self.assertFalse(r['passed']); self.assertEqual(r['lost_union_event_ids'], [1])
        self.assertEqual(r['metrics'][0]['confirmed_events'], 1)
        self.assertTrue(c.assess([b], [[0, 1, 0, 1, 0]])['passed'])

    def test_or_can_bridge_away_a_real_reference_confirmation(self):
        b = block([0, 0, 1, 1, 0], [0, 0, 0, 1, 0], [0, 1, 1, 0, 0])
        union = np.maximum(b['v6'], b['v8'])
        r = c.assess([b], [union])
        self.assertFalse(r['passed']); self.assertEqual(r['lost_union_event_ids'], [1])
        self.assertEqual(r['metrics'][0]['confirmed_events'], 0)

    def test_exact120_seconds_passes_but180_and_short_event_postclear_fail(self):
        b = block([0, 1, 1, 1, 1, 1, 0], [0, 1, 0, 0, 0, 0, 0])
        self.assertTrue(c.assess([b], [[0, 0, 0, 1, 0, 0, 0]])['passed'])
        late = c.assess([b], [[0, 0, 0, 0, 1, 0, 0]])
        self.assertFalse(late['passed'])
        self.assertIn('pool:v6:paired_delay_at_most120s', late['reasons'])
        short = block([0, 1, 0, 0], [0, 1, 0, 0])
        self.assertFalse(c.assess([short], [[0, 0, 0, 1]])['passed'])

    def test_earliest_of_two_reference_confirmations_governs_delay(self):
        b = block([0, 1, 1, 1, 1, 1, 0], [0, 1, 0, 0, 0, 0, 0], [0, 0, 0, 1, 0, 0, 0])
        r = c.assess([b], [[0, 0, 0, 0, 1, 0, 0]])
        self.assertFalse(r['passed'])
        self.assertIn('pool:v6:paired_delay_at_most120s', r['reasons'])
        self.assertNotIn('pool:v8:paired_delay_at_most120s', r['reasons'])

    def test_censored_positive_fragments_still_create_pulse_obligations(self):
        b = block([1, 1, -1, 1, 1, 0], [1, 0, -1, 1, 0, 0])
        missing = np.where(b['v6'] < 0, -1, 0).astype(np.int8)
        r = c.assess([b], [missing])
        self.assertEqual(r['metrics'][0]['true_events'], 0)
        pulse = r['scopes'][0]['references']['v6']['positive_pulses']
        self.assertEqual(pulse['obligations'], 2); self.assertEqual(pulse['censored_fragment_obligations'], 2)
        self.assertFalse(r['passed']); json.dumps(r, allow_nan=False)
        self.assertTrue(c.assess([b], [b['v6']])['passed'])

    def test_one_continuing_alarm_has_separate_positive_intersection_obligations(self):
        b = block([1, 1, -1, 1, 1, 0], [1, 1, 1, 1, 1, 0])
        r = c.assess([b], [[1, 1, 0, 0, 0, 0]])
        pulse = r['scopes'][0]['references']['v6']['positive_pulses']
        self.assertEqual(pulse['obligations'], 2)
        self.assertEqual(pulse['retained_obligations'], 1)
        self.assertEqual(pulse['lost_positive_reference_pulses'][0]['positive_segment_id'], 2)

    def test_per_block_cost_veto_cannot_be_offset_by_another_block(self):
        blocks = [block([0, 0], [1, 0]), block([0, 0], [0, 0], start=2, identifier='1')]
        r = c.assess(blocks, [[0, 0], [1, 0]])
        self.assertEqual(r['metrics'][0]['fp'], 1)
        self.assertIn('block_1:v6:false_duration_nonincreasing', r['reasons'])
        self.assertNotIn('pool:v6:false_duration_nonincreasing', r['reasons'])

    def test_pool_detects_boundary_event_hidden_by_local_censoring(self):
        blocks = [block([0], [0]), block([1, 1, 0], [1, 0, 0], start=1, identifier='1')]
        r = c.assess(blocks, [[0], [0, 0, 0]])
        self.assertEqual(r['metrics'][0]['true_events'], 1)
        self.assertEqual(r['metrics'][2]['true_events'], 0)
        self.assertEqual(r['lost_union_event_ids'], [1])

    def test_seed_may_lose_events_but_never_availability_or_false_cost(self):
        b = block([0, 1, 0, -1], [0, 1, 0, 0])
        self.assertTrue(c.seed_assess([b], [[0, 0, 0, 0]])['passed'])
        self.assertFalse(c.assess([b], [[0, 0, 0, 0]])['passed'])
        self.assertFalse(c.seed_assess([b], [[0, 0, 0, -1]])['passed'])
        self.assertFalse(c.seed_assess([b], [[1, 0, 0, 0]])['passed'])
        b['v6'][3] = -1
        self.assertFalse(c.assess([b], [b['v8']])['passed'])


class RecoveryTests(unittest.TestCase):
    def fixtures(self):
        blocks = [block([0, 1, 1, 0], [0, 1, 0, 0]),
                  block([0, 1, 1, 0], [0, 1, 0, 0], start=4, identifier='1')]
        seeds = [np.zeros(4, np.int8), np.zeros(4, np.int8)]
        finals = [b['v6'].copy() for b in blocks]
        return blocks, seeds, finals

    def test_actual_new_ids_in_two_blocks_and_restoration_not_novelty(self):
        blocks, seeds, finals = self.fixtures(); r = c.recovery_evidence(blocks, seeds, finals, True)
        self.assertTrue(r['passed']); self.assertEqual(r['new_confirmed_event_ids'], [1, 2])
        self.assertEqual(r['first_confirmation_blocks'], [0, 1])
        self.assertEqual(r['restored_reference_event_ids'], [1, 2])
        self.assertEqual(r['novel_beyond_reference_union_event_ids'], [])
        for b in blocks: b['v6'][:] = 0; b['v8'][:] = 0
        r = c.recovery_evidence(blocks, seeds, finals, True)
        self.assertEqual(r['novel_beyond_reference_union_event_ids'], [1, 2])

    def test_added_positive_coverage_is_not_new_confirmed_event_evidence(self):
        blocks, _, seeds = self.fixtures(); finals = [p.copy() for p in seeds]
        for p in finals: p[2] = 1
        r = c.recovery_evidence(blocks, seeds, finals, True)
        self.assertEqual(r['added_positive_rows'], 2)
        self.assertEqual(r['new_confirmed_event_ids'], []); self.assertFalse(r['passed'])

    def test_first_actual_confirmation_not_first_added_row_owns_evidence(self):
        blocks = [block([0, 1, 1, 1], [-1, 0, 0, 0]),
                  block([1, 1, 0, 1, 1, 0], [0]*6, start=4, identifier='1')]
        seeds = [b['v6'].copy() for b in blocks]
        finals = [np.array([-1, 1, 0, 0], np.int8), np.array([1, 0, 0, 1, 0, 0], np.int8)]
        r = c.recovery_evidence(blocks, seeds, finals, True)
        self.assertEqual(r['new_confirmed_event_ids'], [1, 2])
        self.assertEqual(r['first_confirmation_blocks'], [1])
        self.assertEqual(r['new_confirmed_event_records'][0]['first_final_confirmation_index'], 4)
        self.assertFalse(r['passed'])

    def test_even_one_added_normal_row_vetoes_otherwise_supported_recovery(self):
        blocks, seeds, finals = self.fixtures(); finals[0][3] = 1
        r = c.recovery_evidence(blocks, seeds, finals, True)
        self.assertFalse(r['passed']); self.assertEqual(r['added_known_normal_rows'], 1)
        self.assertEqual(r['added_known_normal_rows_by_block'], [1, 0])

    def test_inactive_identity_and_sensor_availability_are_enforced(self):
        blocks, seeds, finals = self.fixtures()
        self.assertTrue(c.recovery_evidence(blocks, seeds, seeds, False)['passed'])
        self.assertFalse(c.recovery_evidence(blocks, seeds, finals, False)['passed'])
        finals[0][0] = -1
        self.assertFalse(c.recovery_evidence(blocks, seeds, finals, True)['passed'])
        with self.assertRaises(ValueError): c.recovery_evidence(blocks, seeds, finals, 1)

    def test_unknown_label_rows_are_not_negative_and_do_not_add_primary_ids(self):
        blocks, seeds, finals = self.fixtures()
        for b in blocks: b['labels'][3] = -1
        for p in finals: p[3] = 1
        r = c.recovery_evidence(blocks, seeds, finals, True)
        self.assertTrue(r['passed']); self.assertEqual(r['added_known_normal_rows'], 0)
        self.assertEqual(r['added_unknown_label_rows'], 2)
        self.assertEqual(r['new_confirmed_event_ids'], [1, 2])


class ExposureAndParityTests(unittest.TestCase):
    def test_original_exposure_minima_require_known_normals_and_onsets_in_two_blocks(self):
        a, b = np.zeros(3000, np.int8), np.zeros(3000, np.int8)
        a[[1, 3, 5]] = 1; b[[1, 3]] = 1
        blocks = [block(a), block(b, start=3000, identifier='1')]
        e = c.exposure(blocks)
        self.assertTrue(e['passed']); self.assertEqual(e['qualified_normal_minutes'], 5995)
        self.assertEqual(e['primary_events'], 5); self.assertEqual(e['eventful_blocks'], [0, 1])
        blocks[1]['labels'][10:500] = -1
        self.assertFalse(c.exposure(blocks)['passed'])
        blocks[1]['labels'][10:500] = 0; blocks[1]['v6'][10:500] = -1
        self.assertFalse(c.exposure(blocks)['passed'])

    def test_cross_boundary_one_event_cannot_count_as_two_eventful_blocks(self):
        a = np.zeros(3000, np.int8); a[[1, 3, 5, 7, 2999]] = 1
        b = np.zeros(3000, np.int8); b[0:20] = 1
        e = c.exposure([block(a), block(b, start=3000, identifier='1')])
        self.assertEqual(e['primary_events'], 5); self.assertEqual(e['eventful_blocks'], [0])
        self.assertFalse(e['passed'])

    def test_fixed_random_compact_metric_parity_with_trusted_full_accounting(self):
        rng = np.random.default_rng(202615)
        for _ in range(50):
            y, a, b, p = [rng.integers(-1, 2, 110, dtype=np.int8) for _ in range(4)]
            blocks = [block(y[:55], a[:55], b[:55]), block(y[55:], a[55:], b[55:], start=55, identifier='1')]
            result = c.assess(blocks, [p[:55], p[55:]])
            for m, yy, pp in zip(result['metrics'], [y, y[:55], y[55:]], [p, p[:55], p[55:]]):
                oracle = stats(yy, pp, 60)
                for key, value in m.items(): self.assertEqual(value, oracle[key], key)
            json.dumps(result, allow_nan=False)

    def test_no_source_or_model_io(self):
        b = [block([0, 1, 0], [0, 1, 0])]
        with patch('builtins.open', side_effect=AssertionError('No file IO')):
            self.assertTrue(c.assess(b, [b[0]['v6']])['passed'])
            c.seed_assess(b, [b[0]['v8']]); c.exposure(b)
            c.recovery_evidence(b, [b[0]['v8']], [b[0]['v8']], False)


if __name__ == '__main__': unittest.main()
