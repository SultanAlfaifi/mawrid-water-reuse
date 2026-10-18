"""Synthetic scalar-oracle tests; no sources, estimators, or actual fitting."""
from __future__ import annotations

import inspect
import json
import unittest

import numpy as np

from ml.gecco_v16 import decisions as d


def scalar_context(v6, v8):
    """Chronological oracle independent of production prefix-accumulation."""
    anchor, recovery = [], []
    active_a = active_r = None
    for row, (first, second) in enumerate(zip(v6, v8)):
        new_a = row > 0 and v8[row - 1] == 0 and second == 1
        new_r = row > 0 and v6[row - 1] == 0 and first == 1
        if second != 1:
            active_a = None
        if new_a:
            active_a = row
        if active_a is not None and row - active_a > 2:
            active_a = None
        if first == -1 or second == -1 or new_r:
            active_r = None
        if new_r and second == 0:
            active_r = row
        if active_r is not None and row - active_r > 2:
            active_r = None
        anchor.append(-1 if active_a is None else active_a)
        recovery.append(-1 if active_r is None else active_r)
    matrix = []
    for row, (first, second, a, r) in enumerate(zip(v6, v8, anchor, recovery)):
        matrix.append([first == 1, second == 1, first >= 0, second >= 0,
                       a >= 0, (row - a) / 2 if a >= 0 else 0,
                       r >= 0, (row - r) / 2 if r >= 0 else 0])
    return np.asarray(matrix, np.float32).reshape(-1, 8), np.asarray(anchor), np.asarray(recovery)


def scalar_weights(y, available, folds, anchor, recovery):
    """Dictionary/row oracle for segment->opportunity->row balancing."""
    events = []
    event_id = 0
    for row, label in enumerate(y):
        if label == 1 and (row == 0 or y[row - 1] != 1):
            event_id += 1
        events.append(event_id if label == 1 else 0)
    opportunities = {}
    eligible = []
    for row, label in enumerate(y):
        keep = bool(available[row] and folds[row] >= 0 and label >= 0
                    and (anchor[row] >= 0 or recovery[row] >= 0))
        eligible.append(keep)
        if keep:
            for kind, origins in (("anchor", anchor), ("recovery", recovery)):
                if origins[row] >= 0:
                    opportunities.setdefault((kind, int(origins[row])), []).append(row)
    negatives, positives = {}, {}
    for key, rows in opportunities.items():
        for row in rows:
            if y[row] == 0:
                negatives.setdefault(key, []).append(row)
            else:
                positives.setdefault(events[row], {}).setdefault(key, []).append(row)
    weights = [0.] * len(y)
    for rows in negatives.values():
        for row in rows:
            weights[row] += .5 / len(negatives) / len(rows)
    for by_opportunity in positives.values():
        for rows in by_opportunity.values():
            for row in rows:
                weights[row] += .5 / len(positives) / len(by_opportunity) / len(rows)
    return np.asarray(weights), np.asarray(eligible), np.asarray(events)


def fixture():
    v6 = np.array([0, 1, 0, 0, 0, 0, 0, 0, 0, 0], np.int8)
    v8 = np.array([0, 0, 1, 1, 1, 0, 0, 1, 1, 1], np.int8)
    y = np.array([0, 0, 1, 1, 0, 0, 0, 1, 0, -1], np.int8)
    available = np.ones(10, bool)
    folds = np.array([0] * 5 + [1] * 5)
    context = d.contexts(v6, v8)
    return y, available, folds, context['anchor_origins'], context['recovery_origins']


class ContextTests(unittest.TestCase):
    def test_independent_scalar_random_prefix_and_future_mutation(self):
        rng = np.random.default_rng(50461)
        for _ in range(80):
            v6 = rng.choice([-1, 0, 1], 53).astype(np.int8)
            v8 = rng.choice([-1, 0, 1], 53).astype(np.int8)
            whole = d.contexts(v6, v8)
            expected, a, r = scalar_context(v6, v8)
            np.testing.assert_array_equal(whole['matrix'], expected)
            np.testing.assert_array_equal(whole['anchor_origins'], a)
            np.testing.assert_array_equal(whole['recovery_origins'], r)
            for cut in (0, 1, 2, 17, 52, 53):
                prefix = d.contexts(v6[:cut], v8[:cut])
                changed6, changed8 = v6.copy(), v8.copy()
                changed6[cut:] = 1
                changed8[cut:] = -1
                mutated = d.contexts(changed6, changed8)
                for key in ('matrix', 'active', 'anchor_origins', 'recovery_origins'):
                    np.testing.assert_array_equal(prefix[key], whole[key][:cut])
                    np.testing.assert_array_equal(mutated[key][:cut], whole[key][:cut])
                cropped = [{**p, 'rows': [i for i in p['rows'] if i < cut]}
                           for p in whole['opportunities'] if p['origin'] < cut]
                self.assertEqual(prefix['opportunities'], cropped)

    def test_unknown_series_start_and_midpulse_do_not_invent_requests(self):
        v6 = np.array([1, 1, -1, 1, 1, 0, 1, 1, 1, 1], np.int8)
        v8 = np.array([1, 1, -1, 1, 1, 0, 0, 0, 0, 0], np.int8)
        c = d.contexts(v6, v8)
        np.testing.assert_array_equal(c['anchor_origins'], np.full(10, -1))
        np.testing.assert_array_equal(c['recovery_origins'], [-1] * 6 + [6, 6, 6, -1])

    def test_postclear_recovery_overlaps_anchor_without_extending_deadline(self):
        c = d.contexts(np.array([0, 1, 0, 0, 0]), np.array([0, 0, 1, 1, 1]))
        np.testing.assert_array_equal(c['recovery_origins'], [-1, 1, 1, 1, -1])
        np.testing.assert_array_equal(c['anchor_origins'], [-1, -1, 2, 2, 2])
        np.testing.assert_array_equal(c['matrix'][3, 4:], [1, .5, 1, 1])
        self.assertEqual(c['opportunities'], [
            {'type': 'recovery', 'origin': 1, 'rows': [1, 2, 3]},
            {'type': 'anchor', 'origin': 2, 'rows': [2, 3, 4]}])

    def test_new_ineligible_start_cancels_older_request_before_current_row(self):
        v6 = np.array([0, 1, 0, 1, 0, 0])
        c = d.contexts(v6, np.array([0, 0, 0, 1, 0, 0]))
        np.testing.assert_array_equal(c['recovery_origins'], [-1, 1, 1, -1, -1, -1])
        c = d.contexts(v6, np.zeros(6, dtype=int))
        np.testing.assert_array_equal(c['recovery_origins'], [-1, 1, 1, 3, 3, 3])

    def test_unknown_either_reference_cancels_recovery_permanently(self):
        for a, b in [([0, 1, -1, 1, 1], [0, 0, 0, 0, 0]),
                     ([0, 1, 1, 1, 1], [0, 0, -1, 0, 0])]:
            c = d.contexts(np.array(a), np.array(b))
            np.testing.assert_array_equal(c['recovery_origins'], [-1, 1, -1, -1, -1])

    def test_v6_unknown_does_not_cancel_known_v8_anchor(self):
        c = d.contexts(np.array([0, -1, -1, -1, 0]), np.array([0, 1, 1, 1, 1]))
        np.testing.assert_array_equal(c['anchor_origins'], [-1, 1, 1, 1, -1])
        self.assertEqual(c['matrix'][1, 2], 0)
        self.assertEqual(c['matrix'][1, 4], 1)

    def test_context_shape_order_no_labels_input_or_mutation(self):
        v6 = np.array([0, 1, 0], np.int8); v8 = np.zeros(3, np.int8)
        originals = v6.copy(), v8.copy()
        c = d.contexts(v6, v8)
        self.assertEqual(list(inspect.signature(d.contexts).parameters), ['v6', 'v8'])
        self.assertEqual(c['feature_names'], list(d.CONTEXT_NAMES))
        self.assertEqual(c['matrix'].shape, (3, 8)); self.assertEqual(c['matrix'].dtype, np.float32)
        self.assertEqual(c['active'].dtype, np.bool_)
        self.assertEqual(c['anchor_origins'].dtype, np.int64)
        np.testing.assert_array_equal(c['active'], c['eligible'])
        self.assertFalse(np.shares_memory(c['active'], c['eligible']))
        np.testing.assert_array_equal(v6, originals[0]); np.testing.assert_array_equal(v8, originals[1])
        empty = d.contexts(np.array([], dtype=int), np.array([], dtype=int))
        self.assertEqual(empty['matrix'].shape, (0, 8)); self.assertEqual(empty['opportunities'], [])

    def test_invalid_reference_inputs_rejected(self):
        for a, b in [([0.0, 1.0], [0, 0]), ([False, True], [0, 0]),
                     ([0, 2], [0, 0]), ([0, 1], [0]), ([[0]], [0])]:
            with self.assertRaises(ValueError): d.contexts(a, b)


class WeightTests(unittest.TestCase):
    def test_mixed_overlapping_opportunities_exact_hierarchical_masses(self):
        args = fixture(); out = d.weights(*args)
        expected = [0, 1/6, .125, .125, 1/6, 0, 0, .25, 1/6, 0]
        np.testing.assert_allclose(out['normalized'], expected, rtol=0, atol=1e-16)
        np.testing.assert_allclose(out['sample'], np.array(expected) * 6, rtol=0, atol=1e-15)
        self.assertEqual(out['summary']['eligible_rows'], 6)
        self.assertEqual(out['summary']['positive_events'], 2)
        self.assertEqual(out['summary']['positive_folds'], [0, 1])
        self.assertAlmostEqual(out['summary']['normal_weight_mass'], .5)
        self.assertAlmostEqual(out['summary']['positive_weight_mass'], .5)
        self.assertEqual(out['summary']['unknown_weight_mass'], 0)
        self.assertFalse(out['summary']['fit_supported'])
        self.assertTrue(out['summary']['request_support']['anchor']['supported'])
        self.assertTrue(out['summary']['request_support']['recovery']['supported'])
        self.assertEqual(len(out['records']), 3)

    def test_original_event_crosses_forecast_folds_without_extra_event_credit(self):
        y, available, folds, a, r = fixture()
        y[2:8] = 1
        out = d.weights(y, available, folds, a, r)
        np.testing.assert_array_equal(out['event_ids'], [0, 0, 1, 1, 1, 1, 1, 1, 0, 0])
        self.assertEqual(out['summary']['positive_events'], 1)
        self.assertEqual(out['summary']['positive_folds'], [0, 1])
        self.assertFalse(out['summary']['fit_checks']['at_least_two_positive_segments'])
        self.assertEqual(out['event_records'][0]['opportunity_intersections'], 3)
        self.assertAlmostEqual(out['event_records'][0]['normalized_weight_mass'], .5)

    def test_offset_and_fold_summary_counts_do_not_double_count_unique_rows(self):
        out = d.weights(*fixture())
        anchor = out['summary']['per_offset']['anchor']
        recovery = out['summary']['per_offset']['recovery']
        self.assertEqual([(v['normal_rows'], v['positive_rows'], v['unknown_label_rows'])
                          for v in anchor], [(0, 2, 0), (1, 1, 0), (1, 0, 1)])
        self.assertEqual([(v['normal_rows'], v['positive_rows']) for v in recovery],
                         [(1, 0), (0, 1), (0, 1)])
        self.assertEqual([v['eligible_rows'] for v in out['summary']['per_fold']], [4, 2])
        self.assertEqual([v['positive_event_ids'] for v in out['summary']['per_fold']], [[1], [2]])
        # Two overlapping rows contribute to two opportunity records but once
        # to the fit population and its sample-weight scale.
        self.assertEqual(sum(len(r['eligible_rows']) for r in out['records']), 8)
        self.assertEqual(out['summary']['sample_weight_scale'], 6)
        # Persisted metadata must remain native JSON, including per-fold counts.
        json.dumps({key: out[key] for key in ('summary', 'records', 'event_records')}, allow_nan=False)

    def test_unknown_splits_segments_but_does_not_shift_opportunity_or_become_normal(self):
        y, available, folds, a, r = fixture()
        y[2:5] = [1, -1, 1]
        out = d.weights(y, available, folds, a, r)
        self.assertEqual(out['summary']['positive_events'], 3)
        self.assertEqual(out['event_ids'][2], 1); self.assertEqual(out['event_ids'][4], 2)
        self.assertFalse(out['event_records'][1]['known_onset'])
        self.assertEqual(out['normalized'][3], 0)
        self.assertEqual(out['records'][0]['rows'], [1, 2, 3])
        self.assertEqual(out['summary']['request_support']['anchor']['normal_opportunities'], 1)

    def test_unavailable_offsets_are_excluded_without_replacement(self):
        y, available, folds, a, r = fixture()
        available[2] = False
        out = d.weights(y, available, folds, a, r)
        self.assertEqual(out['normalized'][2], 0)
        self.assertAlmostEqual(out['normalized'][3], .25)
        self.assertEqual(out['normalized'][5], 0)
        self.assertEqual(out['records'][1]['rows'], [2, 3, 4])
        self.assertEqual(out['records'][1]['eligible_rows'], [3, 4])

    def test_global_segments_before_forecast_keep_original_numbering(self):
        y, available, folds, a, r = fixture()
        y[0] = 1; available[0] = False; folds[0] = -1
        out = d.weights(y, available, folds, a, r)
        self.assertEqual(out['summary']['positive_event_ids'], [2, 3])
        self.assertEqual(out['summary']['original_positive_segments'], 3)
        self.assertEqual(out['event_records'][0]['eligible_rows'], [])

    def test_independent_scalar_weights_random_three_fold_original_axis(self):
        rng = np.random.default_rng(91072)
        for _ in range(60):
            n = 80
            y = rng.choice([-1, 0, 1], n).astype(np.int8)
            available = rng.random(n) > .2
            folds = np.full(n, -1, dtype=int)
            a = np.full(n, -1, dtype=int); r = a.copy()
            for fold, (start, end) in enumerate(((20, 40), (40, 60), (60, 80))):
                c = d.contexts(rng.choice([-1, 0, 1], end - start), rng.choice([-1, 0, 1], end - start))
                folds[start:end] = fold
                for key, destination in [('anchor_origins', a), ('recovery_origins', r)]:
                    values = c[key]
                    destination[start:end] = np.where(values >= 0, values + start, -1)
            out = d.weights(y, available, folds, a, r)
            expected, eligible, events = scalar_weights(y, available, folds, a, r)
            np.testing.assert_allclose(out['normalized'], expected, rtol=0, atol=2e-16)
            np.testing.assert_array_equal(out['eligible'], eligible)
            np.testing.assert_array_equal(out['event_ids'], events)
            np.testing.assert_array_equal(out['normalized'][~eligible], 0)
            np.testing.assert_allclose(out['sample'], expected * eligible.sum(), rtol=0, atol=1e-14)

    def test_class_minima_and_request_type_support_are_separate(self):
        n = 420
        v6 = np.zeros(n, dtype=int); v8 = np.tile([0, 1, 0], n // 3)
        c = d.contexts(v6, v8)
        y = np.zeros(n, dtype=int); y[1] = 1; y[211] = 1
        folds = np.r_[np.zeros(210, dtype=int), np.ones(210, dtype=int)]
        out = d.weights(y, np.ones(n, bool), folds, c['anchor_origins'], c['recovery_origins'])
        self.assertTrue(out['summary']['fit_supported'])
        self.assertEqual(out['summary']['normal_rows'], 138)
        self.assertTrue(out['summary']['request_support']['anchor']['supported'])
        self.assertFalse(out['summary']['request_support']['recovery']['supported'])
        self.assertTrue(all(out['summary']['fit_checks'].values()))

    def test_exact_normal_minimum_does_not_count_duplicate_opportunity_memberships(self):
        n = 390
        v8 = np.tile([0, 1, 0], n // 3)
        context = d.contexts(np.zeros(n, dtype=int), v8)
        y = np.zeros(n, dtype=int); y[1] = 1; y[196] = 1
        folds = np.r_[np.zeros(195, dtype=int), np.ones(195, dtype=int)]
        available = np.ones(n, bool)
        out = d.weights(y, available, folds, context['anchor_origins'], context['recovery_origins'])
        self.assertEqual(out['summary']['normal_rows'], 128)
        self.assertTrue(out['summary']['fit_supported'])
        available[4] = False
        out = d.weights(y, available, folds, context['anchor_origins'], context['recovery_origins'])
        self.assertEqual(out['summary']['normal_rows'], 127)
        self.assertFalse(out['summary']['fit_checks']['at_least_128_normal_rows'])
        self.assertFalse(out['summary']['fit_supported'])

    def test_missing_class_mass_is_not_invented_or_redistributed(self):
        args = list(fixture())
        for label, normal_mass, positive_mass in [(0, .5, 0), (1, 0, .5), (-1, 0, 0)]:
            args[0] = np.full(10, label, dtype=int)
            out = d.weights(*args)
            self.assertFalse(out['summary']['fit_supported'])
            self.assertAlmostEqual(out['summary']['normal_weight_mass'], normal_mass)
            self.assertAlmostEqual(out['summary']['positive_weight_mass'], positive_mass)
            self.assertFalse(out['summary']['request_support']['anchor']['supported'])

    def test_normal_opportunities_equal_mass_despite_different_lengths(self):
        args = list(fixture()); args[0][:] = 0
        out = d.weights(*args)
        for record in out['records']:
            self.assertAlmostEqual(record['normal_weight_mass'], .5 / 3)
        self.assertAlmostEqual(out['normalized'].sum(), .5)

    def test_inputs_unchanged_and_label_changes_cannot_modify_context(self):
        args = fixture(); copies = [value.copy() for value in args]
        before = d.contexts(np.array([0, 1, 0]), np.array([0, 0, 1]))
        d.weights(*args)
        for value, original in zip(args, copies): np.testing.assert_array_equal(value, original)
        args[0][:] = -1; d.weights(*args)
        after = d.contexts(np.array([0, 1, 0]), np.array([0, 0, 1]))
        np.testing.assert_array_equal(before['matrix'], after['matrix'])

    def test_invalid_weight_axes_reject_shifted_future_cancelled_and_crossfold_origins(self):
        args = list(fixture())
        invalid = []
        changed = [x.copy() for x in args]; changed[3][3] = 4; invalid.append(changed)
        changed = [x.copy() for x in args]; changed[3][2] = -1; invalid.append(changed)
        changed = [x.copy() for x in args]; changed[3][3] = -1; invalid.append(changed)
        changed = [x.copy() for x in args]; changed[3][5] = 2; invalid.append(changed)
        changed = [x.copy() for x in args]; changed[2][3] = 1; invalid.append(changed)
        changed = [x.copy() for x in args]; changed[2][2] = -1; invalid.append(changed)
        changed = [x.copy() for x in args]; changed[2][0] = -2; invalid.append(changed)
        changed = [x.copy() for x in args]; changed[1] = changed[1].astype(int); invalid.append(changed)
        changed = [x.copy() for x in args]; changed[0][0] = 2; invalid.append(changed)
        for changed in invalid:
            with self.assertRaises(ValueError): d.weights(*changed)

    def test_empty_weights_have_explicit_no_support(self):
        empty = np.array([], dtype=int)
        out = d.weights(empty, np.array([], bool), empty, empty, empty)
        self.assertEqual(out['summary']['eligible_rows'], 0)
        self.assertFalse(out['summary']['fit_supported'])
        self.assertEqual(out['records'], []); self.assertEqual(out['event_records'], [])
        self.assertEqual(out['normalized'].dtype, np.float64)


if __name__ == '__main__':
    unittest.main()
