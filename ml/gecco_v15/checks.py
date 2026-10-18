"""V15 calibration accounting on the unchanged original ternary row axis.

No inference, fitting or source IO. These checks certify a fixed incremental
policy conditional on already calibrated V6/V8 experts; they are not an
independent whole-pipeline holdout or a prospective guarantee. Final retention
is deliberately separate from the pure seed's availability/false-cost checks.
The frozen experiment has 60-second samples and a 120-second extra-delay cap.
"""
from __future__ import annotations

from collections.abc import Mapping
import numpy as np

from ml.gecco_v7.calibration import _MetricContext, full_stats

CADENCE_SECONDS = 60.0
MAX_DELAY_SECONDS = 120.0
MIN_EVENTS = 5
MIN_EVENTFUL_BLOCKS = 2
MIN_NORMAL_MINUTES_PER_BLOCK = 1440
MIN_TOTAL_NORMAL_MINUTES = 5760
MIN_OBSERVED_BLOCKS = 2
MIN_RECOVERY_EVENTS = 2
MIN_RECOVERY_BLOCKS = 2


def _cadence(value):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating))
            or not np.isfinite(value) or float(value) != CADENCE_SECONDS):
        raise ValueError('V15 frozen accounting requires cadence_seconds=60')
    return CADENCE_SECONDS


def _ternary(values, name):
    a = np.asarray(values)
    if a.ndim != 1 or a.dtype.kind not in 'biu' or not np.isin(a, [-1, 0, 1]).all():
        raise ValueError(name + ' must be a one-dimensional ternary integer/bool array')
    return a.astype(np.int8, copy=False)


def validate_blocks(blocks, *, cadence_seconds=60):
    _cadence(cadence_seconds)
    if not isinstance(blocks, (list, tuple)) or not blocks:
        raise ValueError('A nonempty list/tuple of original-axis blocks is required')
    clean, ids, next_start = [], set(), None
    required = {'labels', 'v6', 'v8', 'scores', 'source_start', 'block_id'}
    for block in blocks:
        if not isinstance(block, Mapping) or not required.issubset(block):
            raise ValueError('Missing required calibration block fields')
        y, a, b = (_ternary(block[k], k) for k in ('labels', 'v6', 'v8'))
        raw = np.asarray(block['scores'])
        if raw.dtype.kind not in 'iuf' or raw.ndim != 1:
            raise ValueError('Scores must be a one-dimensional real numeric array')
        scores = raw.astype(np.float64, copy=False)
        if not len(y) or any(x.shape != y.shape for x in (a, b, scores)):
            raise ValueError('All block arrays must have the same nonempty shape')
        start = block['source_start']
        if isinstance(start, (bool, np.bool_)) or not isinstance(start, (int, np.integer)) or start < 0:
            raise ValueError('source_start must be a nonnegative integer')
        start = int(start)
        if start > np.iinfo(np.int64).max - len(y):
            raise ValueError('Source coordinates exceed the int64 axis')
        if next_start is not None and start != next_start:
            raise ValueError('Calibration blocks must be adjacent and ordered')
        identifier = block['block_id']
        if isinstance(identifier, (bool, np.bool_)) or not isinstance(identifier, (str, int, np.integer)):
            raise ValueError('block_id must be a string or integer')
        identifier = str(identifier)
        if not identifier or identifier in ids:
            raise ValueError('Block IDs must be nonempty and unique')
        ids.add(identifier); next_start = start + len(y)
        clean.append({'labels': y, 'v6': a, 'v8': b, 'scores': scores,
                      'source_start': start, 'block_id': identifier})
    return clean


def _predictions(blocks, values, name='predictions'):
    if not isinstance(values, (list, tuple)) or len(values) != len(blocks):
        raise ValueError(name + ' must contain one array per block')
    result = [_ternary(v, name) for v in values]
    if any(p.shape != b['labels'].shape for b, p in zip(blocks, result)):
        raise ValueError(name + ' must preserve each original block shape')
    return result


def _metrics(labels, predictions):
    m = _MetricContext(labels).measure(predictions)
    m.update(fp_duration_seconds=float(m['fp'] * CADENCE_SECONDS),
             normal_observed_seconds=float(m['normal_observed_rows'] * CADENCE_SECONDS),
             rows=len(labels), cadence_seconds=CADENCE_SECONDS)
    return m


def _scope_arrays(blocks, predictions):
    y = np.concatenate([b['labels'] for b in blocks])
    first = {'scope': 'pool', 'source_start': blocks[0]['source_start'],
             'labels': y, 'prediction': np.concatenate(predictions),
             'v6': np.concatenate([b['v6'] for b in blocks]),
             'v8': np.concatenate([b['v8'] for b in blocks])}
    return [first] + [{'scope': 'block_' + str(i), 'block_id': b['block_id'],
                      'source_start': b['source_start'], 'labels': b['labels'],
                      'prediction': p, 'v6': b['v6'], 'v8': b['v8']}
                     for i, (b, p) in enumerate(zip(blocks, predictions))]


def _spans(mask):
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(np.flatnonzero(changes == 1).tolist(), np.flatnonzero(changes == -1).tolist()))


def _pulse_obligations(labels, reference, prediction, source_start):
    """Each original alarm/positive-segment intersection keeps actual coverage.

    No branch-origin metadata can substitute for a final alarm. The deadline
    begins at the first positive reference row, is inclusive at 120 seconds,
    and never extends beyond that same positive segment. Left-censored pulse
    or label fragments remain obligations but cannot become primary events.
    """
    segments, episodes = _spans(labels == 1), _spans(reference == 1)
    prefix = np.r_[0, np.cumsum(prediction == 1)]
    obligations, losses, censored = 0, [], 0
    first = 0
    for episode_id, (a, b) in enumerate(episodes, 1):
        while first < len(segments) and segments[first][1] <= a:
            first += 1
        j = first
        while j < len(segments) and segments[j][0] < b:
            c, d = segments[j]; anchor = max(a, c)
            stop = min(d, anchor + int(MAX_DELAY_SECONDS / CADENCE_SECONDS) + 1)
            kept = bool(prefix[stop] - prefix[anchor])
            pulse_censored = bool(a == 0 or reference[a - 1] < 0)
            label_censored = bool(c == 0 or labels[c - 1] != 0)
            obligations += 1; censored += int(pulse_censored or label_censored)
            if not kept:
                losses.append({'episode_id': episode_id, 'positive_segment_id': j + 1,
                    'episode_start': a, 'episode_end_exclusive': b,
                    'positive_segment_start': c, 'positive_segment_end_exclusive': d,
                    'first_positive_reference_row': anchor,
                    'source_first_positive_reference_row': source_start + anchor,
                    'last_allowed_row': stop - 1, 'left_censored_reference_episode': pulse_censored,
                    'left_censored_positive_segment': label_censored})
            j += 1
    return {'passed': not losses, 'obligations': obligations,
            'retained_obligations': obligations - len(losses),
            'censored_fragment_obligations': censored, 'lost_positive_reference_pulses': losses}


def _assess(blocks, predictions, refs, pulses, retain):
    if not isinstance(refs, (tuple, list)) or not refs or any(r not in ('v6', 'v8') for r in refs) or len(set(refs)) != len(refs):
        raise ValueError('refs must be distinct v6/v8 names')
    if not isinstance(pulses, (bool, np.bool_)):
        raise ValueError('pulses must be boolean')
    scopes, metrics, reasons = [], [], []
    for scope in _scope_arrays(blocks, predictions):
        y, p = scope['labels'], scope['prediction']; cm = _metrics(y, p); metrics.append(cm)
        ct = dict(zip(cm['confirmed_event_ids'], cm['confirmed_times']))
        checks, by_ref, union = {}, {}, set()
        for ref in refs:
            r = scope[ref]; rm = _metrics(y, r)
            rt = dict(zip(rm['confirmed_event_ids'], rm['confirmed_times'])); union.update(rt)
            lost = sorted(set(rt) - set(ct))
            paired = [{'event_id': k, 'extra_delay_seconds': float((ct[k] - t) * CADENCE_SECONDS),
                       'reference_confirmation_index': t, 'candidate_confirmation_index': ct[k]}
                      for k, t in rt.items() if k in ct]
            check = {'availability_equal': bool(np.array_equal(p >= 0, r >= 0)),
                     'false_fragments_nonincreasing': cm['false_positive_runs'] <= rm['false_positive_runs'],
                     'false_duration_nonincreasing': cm['fp'] <= rm['fp']}
            if retain:
                check.update(event_ids_retained=not lost,
                    paired_delay_at_most120s=all(d['extra_delay_seconds'] <= MAX_DELAY_SECONDS for d in paired))
            pulse = _pulse_obligations(y, r, p, scope['source_start']) if pulses else None
            if pulse is not None:
                check['positive_pulse_intersections_retained'] = pulse['passed']
            checks[ref] = check
            by_ref[ref] = {'checks': check, 'metrics': rm, 'lost_reference_event_ids': lost,
                'paired_extra_delays': paired,
                'max_paired_extra_delay_seconds': max((d['extra_delay_seconds'] for d in paired), default=None),
                'lost_positive_alarm_rows': int(((y == 1) & (r == 1) & (p != 1)).sum()),
                'positive_pulses': pulse}
            reasons.extend(scope['scope'] + ':' + ref + ':' + k for k, passed in check.items() if not passed)
        scopes.append({'scope': scope['scope'], 'block_id': scope.get('block_id'),
            'source_start': scope['source_start'], 'metrics': cm, 'references': by_ref,
            'reference_union_event_ids': sorted(union), 'lost_union_event_ids': sorted(union - set(ct)),
            'checks': checks})
    return {'passed': not reasons, 'reasons': reasons, 'rejection_reasons': list(reasons),
            'metrics': metrics, 'scopes': scopes,
            'retention_required': retain, 'pulse_retention_required': bool(pulses),
            'lost_union_event_ids': scopes[0]['lost_union_event_ids'],
            'interpretation': 'Original-axis final transition accounting; no OR event-retention assumption.'}


def assess(blocks, predictions, refs=('v6', 'v8'), pulses=True, *, cadence_seconds=60):
    blocks = validate_blocks(blocks, cadence_seconds=cadence_seconds)
    return _assess(blocks, _predictions(blocks, predictions), refs, pulses, True)


def seed_assess(blocks, predictions, *, cadence_seconds=60):
    """Experimental pure-seed gate: V8 availability and FP cost, not retention."""
    blocks = validate_blocks(blocks, cadence_seconds=cadence_seconds)
    return _assess(blocks, _predictions(blocks, predictions), ('v8',), False, False)


def exposure(blocks, *, cadence_seconds=60):
    blocks = validate_blocks(blocks, cadence_seconds=cadence_seconds)
    y = np.concatenate([b['labels'] for b in blocks]); context = _MetricContext(y)
    bounds = np.r_[0, np.cumsum([len(b['labels']) for b in blocks])]
    # Support requires actual known-normal observation by both experts. Never
    # use unknown labels as negatives or compress the onset/source axis.
    minutes = [int(((b['labels'] == 0) & (b['v6'] >= 0) & (b['v8'] >= 0)).sum()) for b in blocks]
    qualified = [i for i, n in enumerate(minutes) if n >= MIN_NORMAL_MINUTES_PER_BLOCK]
    qualified_minutes = sum(minutes[i] for i in qualified)
    owners = sorted({int(np.searchsorted(bounds, a, side='right') - 1) for _, a, _ in context.primary_intervals})
    checks = {'enough_observed_normal_exposure': len(qualified) >= MIN_OBSERVED_BLOCKS and qualified_minutes >= MIN_TOTAL_NORMAL_MINUTES,
              'enough_primary_event_representation': len(context.primary_intervals) >= MIN_EVENTS and len(owners) >= MIN_EVENTFUL_BLOCKS}
    reasons = [k for k, passed in checks.items() if not passed]
    return {'passed': not reasons, 'reasons': reasons, 'rejection_reasons': list(reasons), 'checks': checks,
            'primary_events': len(context.primary_intervals), 'eventful_blocks': owners,
            'qualified_blocks': qualified, 'qualified_block_ids': [blocks[i]['block_id'] for i in qualified],
            'observed_normal_minutes_by_block': minutes, 'qualified_normal_minutes': qualified_minutes,
            'min_events': MIN_EVENTS, 'min_eventful_blocks': MIN_EVENTFUL_BLOCKS,
            'min_observed_blocks': MIN_OBSERVED_BLOCKS, 'min_normal_minutes_per_block': MIN_NORMAL_MINUTES_PER_BLOCK,
            'min_total_normal_minutes': MIN_TOTAL_NORMAL_MINUTES,
            'source_range': [blocks[0]['source_start'], blocks[-1]['source_start'] + len(blocks[-1]['labels'])],
            'event_ownership': 'Original global known onset; one owner at the actual onset block.'}


def recovery_evidence(blocks, seeds, finals, active, *, cadence_seconds=60):
    blocks = validate_blocks(blocks, cadence_seconds=cadence_seconds)
    if not isinstance(active, (bool, np.bool_)):
        raise ValueError('active must be boolean')
    seeds, finals = _predictions(blocks, seeds, 'seeds'), _predictions(blocks, finals, 'finals')
    y = np.concatenate([b['labels'] for b in blocks]); seed = np.concatenate(seeds); final = np.concatenate(finals)
    context = _MetricContext(y); before, after = context.measure(seed), context.measure(final)
    st = dict(zip(before['confirmed_event_ids'], before['confirmed_times']))
    ft = dict(zip(after['confirmed_event_ids'], after['confirmed_times']))
    gained = sorted(set(ft) - set(st))
    bounds = np.r_[0, np.cumsum([len(b['labels']) for b in blocks])]
    records = [{'event_id': i, 'first_final_confirmation_index': ft[i],
                'source_first_final_confirmation_index': blocks[0]['source_start'] + ft[i],
                'owner_block': int(np.searchsorted(bounds, ft[i], side='right') - 1)} for i in gained]
    owners = sorted({r['owner_block'] for r in records})
    addition = (final == 1) & (seed != 1)
    normal = addition & (y == 0)
    normal_blocks = [int(normal[a:b].sum()) for a, b in zip(bounds[:-1], bounds[1:])]
    reference_ids = set()
    for ref in ('v6', 'v8'):
        reference_ids.update(context.measure(np.concatenate([b[ref] for b in blocks]))['confirmed_event_ids'])
    checks = {'availability_unchanged_from_seed': bool(np.array_equal(final >= 0, seed >= 0)),
              'seed_alarm_rows_not_removed': not bool(((seed == 1) & (final != 1)).any()),
              'inactive_recovery_is_identity': bool(active) or bool(np.array_equal(seed, final)),
              'zero_added_known_normal_rows_global': not bool(normal.any()),
              'zero_added_known_normal_rows_each_block': not any(normal_blocks),
              'at_least_two_new_confirmed_ids_vs_seed': not active or len(gained) >= MIN_RECOVERY_EVENTS,
              'actual_first_confirmation_in_at_least_two_blocks': not active or len(owners) >= MIN_RECOVERY_BLOCKS}
    reasons = [k for k, passed in checks.items() if not passed]
    return {'active': bool(active), 'passed': not reasons, 'reasons': reasons, 'rejection_reasons': list(reasons),
            'checks': checks, 'new_confirmed_event_ids': gained, 'new_confirmed_event_records': records,
            'first_confirmation_blocks': owners, 'first_confirmation_block_ids': [blocks[i]['block_id'] for i in owners],
            'restored_reference_event_ids': sorted(set(gained) & reference_ids),
            'novel_beyond_reference_union_event_ids': sorted(set(gained) - reference_ids),
            'added_known_normal_rows': int(normal.sum()), 'added_known_normal_rows_by_block': normal_blocks,
            'added_unknown_label_rows': int((addition & (y < 0)).sum()),
            'added_positive_rows': int((addition & (y == 1)).sum()),
            'min_new_confirmed_events': MIN_RECOVERY_EVENTS, 'min_owning_blocks': MIN_RECOVERY_BLOCKS,
            'event_ownership': 'First actual final 0-to-1 confirmation on the original pool axis, not first added positive coverage.',
            'interpretation': 'New versus suppressed seed; restored reference IDs are distinct from novelty beyond V6/V8.'}
