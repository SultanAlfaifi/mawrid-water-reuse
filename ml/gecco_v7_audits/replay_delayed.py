"""Independent full replay of completed run03; no fitting or new selection.

Only already-disclosed GECCO and the SHA-verified WaterHub cache are opened.
The prior raw WaterHub adaptation audit is reused explicitly. Trusted local
joblib objects are loaded only after matching their frozen and audited hashes.
The scalar confirmation/persistence oracle and 120-second acceptance accounting
below do not invoke the new runner's selection or summary functions. Established
V6 ternary-label metrics are reused for event identities and point accounting.
Import has no source IO. Run only after all 19 cases are complete and authorized.
GECCO delays use nominal acquisition minutes, including its known clock rollback;
WaterHub uses a verified regular timestamp grid. This is batch, not streaming.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import importlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ml.gecco_v7_audits import replay as old

ATTEMPT = 'run03_hgb_corroborated_confirmation_120s'
VERSION = 'v7_hgb_corroborated_confirmation_120s'
EXTRA_CODE = ('recalibrate_delayed.py', 'runtime_delayed.py', 'calibration_delayed.py', 'evidence.py')
SUM_KEYS = ('true_events', 'confirmed_events', 'tp', 'fp', 'fn', 'tn', 'false_positive_runs',
            'normal_observed_seconds', 'fp_duration_seconds', 'known_positive_rows',
            'positive_unavailable_rows', 'rows', 'available_rows')


def fitted_state_digest(value):
    """Hash semantic fitted state, excluding undefined structured-array padding.

    sklearn Tree node records contain alignment padding that can change on
    unpickle/re-pickle although every named model field remains identical.
    Each named field is hashed separately; no fitted feature, threshold, child,
    value, missing-direction field, or estimator attribute is omitted.
    Executed only on already SHA-verified trusted local fitted objects.
    """
    digest = hashlib.sha256()
    def add(item):
        if isinstance(item, np.generic):
            add(item.item()); return
        if item is None or isinstance(item, (str, bool, int, float)):
            digest.update((type(item).__name__ + ':' + repr(item)).encode()); return
        if isinstance(item, bytes):
            digest.update(b'bytes:'); digest.update(item); return
        if isinstance(item, np.ndarray):
            digest.update(('array:' + str(item.shape) + ':' + str(item.dtype)).encode())
            if item.dtype.names:
                for name in item.dtype.names:
                    add(name); add(item[name])
            elif item.dtype.hasobject:
                for part in item.flat: add(part)
            else:
                digest.update(np.ascontiguousarray(item).tobytes())
            return
        if isinstance(item, dict):
            digest.update(b'dict:')
            for key in sorted(item, key=lambda key: (type(key).__name__, repr(key))): add(key); add(item[key])
            return
        if isinstance(item, (tuple, list)):
            digest.update((type(item).__name__ + ':' + str(len(item))).encode())
            for part in item: add(part)
            return
        if isinstance(item, type):
            add('class:' + item.__module__ + '.' + item.__qualname__); return
        if isinstance(item, np.random.Generator):
            add('numpy_generator'); add(item.bit_generator.state); return
        if isinstance(item, np.random.RandomState):
            add('numpy_random_state'); add(item.get_state()); return
        add('object:' + type(item).__module__ + '.' + type(item).__qualname__)
        if hasattr(item, '__dict__'):
            add(vars(item))
        elif hasattr(item, '__getstate__'):
            state = item.__getstate__()
            if state is None:
                # This fixed Cython loss has no instance parameters; reduction
                # still captures its constructor and arguments explicitly.
                if type(item).__module__ == 'sklearn._loss._loss' and type(item).__name__ == 'CyHalfBinomialLoss':
                    reduction = item.__reduce__()
                    add((getattr(reduction[0], '__module__', ''), getattr(reduction[0], '__qualname__', ''), reduction[1:]))
                else:
                    raise TypeError('Unsupported stateless model object: ' + str(type(item)))
            else:
                add(state)
        else:
            raise TypeError('Unsupported fitted state: ' + str(type(item)))
    add(value)
    return digest.hexdigest()


def scalar_prediction(reference, confidence, rescue, choice):
    """Independent literal row-by-row bounded latch plus current-gated rescue."""
    ref = old.ternary(reference, 'reference')
    confidence, rescue = np.asarray(confidence, float), np.asarray(rescue, float)
    if confidence.shape != ref.shape or rescue.shape != ref.shape:
        raise ValueError('Equal one-dimensional score axes required')
    cadence = choice['cadence_seconds']; deadline = choice['confirmation_samples']
    low, high = choice['low_threshold'], choice['high_threshold']
    if isinstance(cadence, bool) or not np.isfinite(cadence) or cadence <= 0:
        raise ValueError('Finite positive cadence required')
    if isinstance(deadline, bool) or not isinstance(deadline, (int, np.integer)):
        raise ValueError('Integer deadline required')
    if choice['max_confirmation_seconds'] != 120 or choice['confirmation_delay_seconds'] != deadline * cadence:
        raise ValueError('The declared deadline must match the fixed physical contract')
    if (low is None and deadline != 0) or (low is not None and (deadline not in (1, 2) or deadline * cadence > 120)):
        raise ValueError('Invalid confirmation deadline')
    for threshold in (low, high):
        if threshold is not None and (isinstance(threshold, bool) or not np.isfinite(threshold)):
            raise ValueError('Finite threshold required')
    if low is not None and high is not None and low > high:
        raise ValueError('Low threshold exceeds high threshold')
    windows = {'instant': (1, 1), '2of3': (3, 2), '3of5': (5, 3)}
    if choice['policy'] not in windows:
        raise ValueError('Unknown policy')
    n, k = windows[choice['policy']]
    out, seed = ref.copy(), ref.copy()
    age = 0; released = False
    for i, r in enumerate(ref):
        if r != 1:
            age = 0; released = False
        else:
            if low is None or not np.isfinite(confidence[i]) or confidence[i] >= low or age >= deadline:
                released = True
            seed[i] = int(released); age += 1
        out[i] = seed[i]
        if high is not None and r >= 0 and i >= n - 1:
            window = rescue[i - n + 1:i + 1]
            if np.isfinite(window).all() and rescue[i] >= high and np.count_nonzero(window >= high) >= k:
                out[i] = 1
    return out, seed


def independent_masks(local, raw):
    local = np.asarray(local, float); raw = np.asarray(raw, float)
    if local.shape != (len(raw), 3):
        raise ValueError('Three aligned local components required')
    known = np.isfinite(local).all(axis=1) & np.isfinite(raw)
    return (np.where(known & (local <= 1).all(axis=1), raw, np.nan),
            np.where(known & (local > 1).any(axis=1), raw, np.nan))


def comparisons(labels, arrays, comparison):
    answer = old.recompute_comparisons(labels, arrays, comparison)
    for result in answer.values():
        b, c = result['baseline'], result['candidate']
        result['noninferior_zero_extra_delay'] = result['noninferior']
        delays = [d['extra_delay_seconds'] for d in result['paired_extra_delays']]
        result['noninferior'] = bool(not result['lost_baseline_event_ids'] and result['sensor_availability_equal']
                                    and all(d <= 120 for d in delays)
                                    and c['false_positive_runs'] <= b['false_positive_runs'] and c['fp'] <= b['fp'])
        result['maximum_allowed_extra_delay_seconds'] = 120
        result['maximum_observed_paired_extra_delay_seconds'] = max(delays, default=None)
    return answer


def summary(periods, sources):
    answer = {}; ratio = lambda a, b: a / b if b else None
    for key in old.PAIRS:
        parts = [p['comparisons'][key] for p in periods]
        pools = [p[key] for p in sources.values()]
        summed = {}
        for side in ('baseline', 'candidate'):
            s = {name: sum(p[side][name] for p in pools) for name in SUM_KEYS}
            s.update(confirmed_event_recall=ratio(s['confirmed_events'], s['true_events']),
                     precision=ratio(s['tp'], s['tp'] + s['fp']),
                     recall_observed_positive=ratio(s['tp'], s['tp'] + s['fn']),
                     f1_observed_points=ratio(2 * s['tp'], 2 * s['tp'] + s['fp'] + s['fn']),
                     false_runs_per_day=ratio(s['false_positive_runs'] * 86400, s['normal_observed_seconds']))
            summed[side] = s
        b, c = summed['baseline'], summed['candidate']
        events = sum(bool(p['new_candidate_event_ids']) for p in parts)
        fp = sum(p['candidate']['false_positive_runs'] < p['baseline']['false_positive_runs'] for p in parts)
        gates = {'all_prespecified_cases_complete': len(periods) == 19,
                 'all_periods_and_source_pools_noninferior_with_120s_limit': all(p['noninferior'] for p in parts + pools),
                 'strictly_more_pooled_events': c['confirmed_events'] > b['confirmed_events'],
                 'strictly_fewer_pooled_false_runs': c['false_positive_runs'] < b['false_positive_runs'],
                 'event_gain_in_at_least_two_periods': events >= 2,
                 'false_run_reduction_in_at_least_two_periods': fp >= 2}
        answer[key] = {**summed, 'checks': gates, 'noninferior_periods': sum(p['noninferior'] for p in parts),
                       'periods': len(parts), 'event_gain_periods': events, 'false_run_reduction_periods': fp,
                       'maximum_observed_paired_extra_delay_seconds': max(
                           (d['extra_delay_seconds'] for p in pools + parts for d in p['paired_extra_delays']), default=None),
                       'lost_positive_alarm_rows_descriptive': sum(p['lost_positive_alarm_rows'] for p in pools),
                       'passes_declared_development_gate': all(gates.values())}
    return answer


def _calibration(checks, name, cal, prior_cal, parent_cal, bounds, selected, comparison, stats):
    for column in ('sample_index', 'label', 'baseline', 'reference', 'long_context', 'guarded_long_context'):
        checks.array(name + ':unchanged_parent_calibration:' + column, cal[column], parent_cal[column],
                     floating=column.endswith('context'))
    checks.array(name + ':prior_local_calibration_indices', prior_cal.sample_index, cal.sample_index)
    gate, rescue = independent_masks(prior_cal[['level', 'jump', 'sustained']], cal.long_context)
    checks.array(name + ':calibration_quiet_score', cal.guarded_long_context, gate, floating=True)
    checks.array(name + ':calibration_current_rescue', cal.rescue_long_context, rescue, floating=True)
    origin = bounds[0]; parts = []; seeds = []
    for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        part = cal.iloc[a - origin:b - origin]
        candidate, seed = scalar_prediction(part.reference.to_numpy(np.int8), part.long_context,
                                            rescue[a - origin:b - origin], selected)
        checks.array(name + f':calibration_scalar_prediction:{i}', part.candidate, candidate)
        parts.append((part.label.to_numpy(np.int8), part.reference.to_numpy(np.int8), candidate))
        seeds.append(seed)
    whole = tuple(np.concatenate([part[i] for part in parts]) for i in range(3))
    constraints = []
    for index, (labels, ref, candidate) in enumerate([whole] + parts):
        comp = comparisons(labels, {'baseline': ref, 'reference': ref, 'candidate': candidate}, comparison)['v6_vs_v7']
        checks.require(name + f':selected_past_calibration_constraints:{index}', comp['noninferior'])
        measured = stats(labels, candidate, 60)
        expected = selected['calibration_metrics'] if index == 0 else selected['calibration_block_metrics'][index - 1]
        checks.tree(name + f':selected_calibration_metrics:{index}', measured, expected)
        constraints.append(comp)
    checks.tree(name + ':selected_paired_calibration_delays',
                [{key: d[key] for key in ('event_id', 'extra_delay_seconds')} for d in constraints[0]['paired_extra_delays']],
                selected['calibration_paired_delays'])
    labels, ref, candidate = whole; seed = np.concatenate(seeds)
    added_normal = (labels == 0) & (candidate == 1) & (seed != 1)
    checks.require(name + ':rescue_adds_no_known_normal_calibration_rows', not added_normal.any())
    reference_stats = stats(labels, ref, 60)
    blocks_stats = [stats(y, r, 60) for y, r, _ in parts]
    qualified = [i for i, s in enumerate(blocks_stats) if s['normal_observed_seconds'] >= 1440 * 60]
    qualified_seconds = sum(blocks_stats[i]['normal_observed_seconds'] for i in qualified)
    relative_bounds = np.array(bounds) - origin
    events = reference_stats['primary_event_intervals']
    eventful = {int(np.searchsorted(relative_bounds, e['start'], side='right') - 1) for e in events}
    checks.tree(name + ':calibration_source_range_is_past', selected['evidence']['source_range'], [bounds[0], bounds[-1]])
    checks.tree(name + ':calibration_qualified_blocks', selected['evidence']['qualified_blocks'], qualified)
    checks.tree(name + ':calibration_eventful_blocks', selected['evidence']['eventful_blocks'], sorted(eventful))
    if selected['decision'] != 'reference':
        checks.require(name + ':active_path_past_evidence_minima', len(qualified) >= 2 and qualified_seconds >= 5760 * 60
                       and len(events) >= 5 and len(eventful) >= 2)
    if selected['high_threshold'] is not None:
        additions = (labels == 1) & (candidate == 1) & (seed != 1)
        owners = set(); ids = []
        for event in events:
            inside = np.flatnonzero(additions[event['start']:event['end_exclusive']])
            if len(inside):
                ids.append(event['event_id'])
                owners.add(int(np.searchsorted(relative_bounds, event['start'] + inside[0], side='right') - 1))
        checks.require(name + ':rescue_coverage_evidence_minima', len(ids) >= 2 and len(owners) >= 2)
        checks.tree(name + ':rescue_coverage_event_ids', selected['rescue_coverage_event_ids'], ids)
        checks.tree(name + ':rescue_coverage_blocks', selected['rescue_coverage_blocks'], sorted(owners))


def _trial_selection(checks, name, trials, selected):
    def maybe(value): return None if pd.isna(value) else float(value)
    def rank(row):
        lo, hi = maybe(row['low_threshold']), maybe(row['high_threshold'])
        return (-int(row['events']), int(row['false_runs']), int(row['fp']), -int(row['tp']),
                int(lo is not None) + int(hi is not None), int(row['confirmation_samples']),
                lo if lo is not None else -np.inf, -hi if hi is not None else -np.inf,
                ('instant', '2of3', '3of5').index(row['policy']))
    rows = [row for row in trials.to_dict('records') if row['feasible'] is True]
    checks.require(name + ':feasible_calibration_trial_exists', bool(rows))
    best = min(rows, key=rank)
    checks.require(name + ':stored_selection_is_best_declared_feasible_trial', rank(best) == rank(selected))
    checks.require(name + ':trial_count', len(trials) == selected['trial_count'])
    for key in ('low_threshold', 'high_threshold'):
        checks.tree(name + ':selected_trial:' + key, maybe(best[key]), selected[key])
    for key in ('policy', 'confirmation_samples', 'cadence_seconds'):
        checks.tree(name + ':selected_trial:' + key, best[key], selected[key])


def _audit_case(root, out, parent, parent_audit, spec, source, saved_top, plan_sha,
                checks, hashes, runtime, comparison, stats):
    import joblib
    name = spec['name']; folder = old.inside(out, name)
    frozen = old.read_json(folder / 'freeze.json'); result = old.read_json(folder / 'results.json')
    checks.tree(name + ':top_level_result', result, saved_top)
    checks.require(name + ':source_identity', result['source'] == spec['source'] and result['case'] == name)
    checks.require(name + ':plan_and_no_refit_contract', frozen['plan_sha256'] == plan_sha
                   and frozen['training_reused_without_refit'] is True and frozen['development_only'] is True)
    for key in ('train', 'calibration_starts', 'test', 'continuous_cal'):
        checks.tree(name + ':fixed_geometry:' + key, frozen[key], spec[key])
    a, (left, right) = spec['train'][1], spec['test']; bounds = spec['calibration_starts'] + [left]
    checks.require(name + ':strict_past_geometry', spec['train'][0] == 0 < a == bounds[0]
                   and all(x < y for x, y in zip(bounds[:-1], bounds[1:])) and left < right <= len(source))
    parent_folder = old.inside(root, frozen['parent_folder'])
    checks.require(name + ':parent_case_location', parent_folder == parent / name)
    parent_freeze = old.read_json(parent_folder / 'freeze.json')
    for filename, digest in frozen['parent_sha256'].items():
        actual = old.sha(parent_folder / filename); hashes[name + '/parent/' + filename] = actual
        checks.require(name + ':parent_artifact_and_previous_audit:' + filename,
                       actual == digest == parent_audit['hashes'][name + '/' + filename])
    checks.require(name + ':parent_bundle_freeze', parent_freeze['bundle_sha256'] == frozen['parent_sha256']['bundle.joblib'])
    prior = old.inside(root, frozen['prior_folder'])
    for filename, digest in frozen['prior_sha256'].items():
        checks.require(name + ':immutable_v6_artifact:' + filename, old.sha(prior / filename) == digest)
    for filename in ('bundle.joblib', 'freeze.json', 'predictions.csv.gz', 'calibration_scores.csv.gz',
                     'calibration_trials.csv.gz', 'model_inspection.json', 'results.json'):
        hashes[name + '/' + filename] = old.sha(folder / filename)
    checks.require(name + ':bundle_sha_before_loading', hashes[name + '/bundle.joblib'] == frozen['bundle_sha256'])
    bundle = joblib.load(folder / 'bundle.joblib'); original = joblib.load(parent_folder / 'bundle.joblib')
    checks.require(name + ':versions', bundle['version'] == VERSION and original['version'] == 'v7_hgb_guarded_v2')
    for key in ('long_model', 'reference_bundle'):
        before, after = fitted_state_digest(original[key]), fitted_state_digest(bundle[key])
        hashes[name + '/fitted_state/' + key] = after
        checks.require(name + ':identical_fitted_state_without_refit:' + key, before == after)
    checks.tree(name + ':unchanged_model_inspection', old.read_json(folder / 'model_inspection.json'),
                old.read_json(parent_folder / 'model_inspection.json'))
    checks.require(name + ':model_and_reference_fit_cal_bounds', bundle['max_fit_index'] == a - 1
                   and bundle['max_calibration_index'] == left - 1 and a - 1 < left - 1 < left
                   and bundle['reference_bundle']['max_fit_index'] == a - 1
                   and bundle['reference_bundle']['max_calibration_index'] == left - 1)
    checks.tree(name + ':channel_order', bundle['long_model'].channels, spec['channels'])
    checks.require(name + ':nominal_minute_and_gap', bundle['sample_seconds'] == 60 and bundle['gap_samples'] == 120)
    selected = bundle['selected']
    checks.tree(name + ':frozen_selection', selected, frozen['selected'])
    checks.tree(name + ':reported_selection', selected, result['selected'])
    checks.require(name + ':declared_confirmation_seconds', selected['cadence_seconds'] == 60
                   and selected['max_confirmation_seconds'] == 120
                   and selected['confirmation_delay_seconds'] == selected['confirmation_samples'] * 60 <= 120)
    cal = pd.read_csv(folder / 'calibration_scores.csv.gz', float_precision='round_trip')
    checks.array(name + ':calibration_original_axis', cal.sample_index, np.arange(a, left))
    checks.array(name + ':calibration_labels_from_source', cal.label, source.label.iloc[a:left])
    _calibration(checks, name, cal,
                 pd.read_csv(prior / 'calibration_scores.csv.gz', float_precision='round_trip'),
                 pd.read_csv(parent_folder / 'calibration_scores.csv.gz', float_precision='round_trip'),
                 bounds, selected, comparison, stats)
    _trial_selection(checks, name, pd.read_csv(folder / 'calibration_trials.csv.gz', float_precision='round_trip'), selected)
    saved = pd.read_csv(folder / 'predictions.csv.gz', float_precision='round_trip')
    old_saved = pd.read_csv(parent_folder / 'predictions.csv.gz', float_precision='round_trip')
    for column in ('sample_index', 'label', 'baseline', 'reference', 'long_context', 'guarded_long_context'):
        checks.array(name + ':unchanged_parent_test:' + column, saved[column], old_saved[column],
                     floating=column.endswith('context'))
    checks.array(name + ':test_original_axis', saved.sample_index, np.arange(left, right))
    labels = source.label.iloc[left:right].to_numpy(np.int8)
    checks.array(name + ':test_labels_from_source', saved.label, labels)
    sensors = source.iloc[left:right].loc[:, spec['channels']]
    actual = runtime(bundle, sensors)
    checks.require(name + ':runtime_axis_preserved', actual.index.equals(sensors.index) and len(actual) == right - left)
    for stored, live in (('baseline', 'baseline_prediction'), ('reference', 'reference_prediction'),
                         ('candidate', 'prediction'), ('long_context', 'long_context'),
                         ('guarded_long_context', 'guarded_long_context'), ('rescue_long_context', 'rescue_long_context')):
        checks.array(name + ':full_sensor_runtime:' + stored, actual[live], saved[stored], floating=stored.endswith('context'))
    guard, rescue = independent_masks(actual[['level', 'jump', 'sustained']], actual.long_context)
    checks.array(name + ':test_quiet_score_oracle', actual.guarded_long_context, guard, floating=True)
    checks.array(name + ':test_rescue_score_oracle', actual.rescue_long_context, rescue, floating=True)
    oracle, _ = scalar_prediction(actual.reference_prediction.to_numpy(np.int8), actual.long_context, rescue, selected)
    checks.array(name + ':full_scalar_alarm_oracle', actual.prediction, oracle)
    checks.array(name + ':sensor_availability_preserved', actual.prediction >= 0, actual.reference_prediction >= 0)
    checks.require(name + ':gap_not_scored', (actual.prediction.iloc[:120] == -1).all() and actual.long_context.iloc[:120].isna().all())
    arrays = {key: old.ternary(actual[col].to_numpy(), key) for key, col in
              (('baseline', 'baseline_prediction'), ('reference', 'reference_prediction'), ('candidate', 'prediction'))}
    measured = comparisons(labels, arrays, comparison)
    checks.tree(name + ':recomputed_period_metrics_and_120s_gate', measured, result['comparisons'])
    if name in old.REPRESENTATIVE_NAMES:
        old._causality_checks(checks, name, bundle, sensors, actual, runtime)
        short = sensors.iloc[:min(200, len(sensors))].copy()
        short.index = pd.date_range('2020-01-01', periods=len(short), freq='2min')
        rejected = False
        try: runtime(bundle, short)
        except ValueError: rejected = True
        checks.require(name + ':physical_datetime_cadence_mismatch_rejected', rejected)
    checks.require(name + ':bundle_unchanged_after_replay', old.sha(folder / 'bundle.joblib') == frozen['bundle_sha256'])
    over_budget = []
    for delay in measured['v6_vs_v7']['paired_extra_delays']:
        if delay['extra_delay_seconds'] > 120:
            first = delay['baseline_confirmation_index']; end = first
            while end < len(arrays['reference']) and arrays['reference'][end] == 1:
                end += 1
            over_budget.append({**delay, 'first_reference_episode_rows': int(end - first),
                                'first_reference_alarm_removed': bool(arrays['candidate'][first] != 1),
                                'episode_deadline_samples': selected['confirmation_samples'],
                                'interpretation': 'A bound on each continuous reference episode is not a bound on event-to-event matched latency.'})
    return {'case': name, 'source': spec['source'], 'comparisons': measured,
            'over_budget_paired_event_delays': over_budget}, pd.DataFrame(
        {'sample_index': np.arange(left, right), 'label': labels, **arrays})


def audit_directory(output, *, workspace_root=None):
    out = Path(output).resolve(); root = Path(workspace_root).resolve() if workspace_root else ROOT
    plan, completed = old.read_json(out / 'plan.json'), old.read_json(out / 'results.json')
    if (plan.get('attempt') != ATTEMPT or plan.get('expected_cases') != 19
            or completed.get('complete_cases') != 19 or completed.get('expected_cases') != 19
            or completed.get('all_prespecified_cases_complete') is not True
            or [p.get('case') for p in completed.get('periods', [])] != old.EXPECTED_NAMES
            or not completed.get('completed_at_utc') or (out / 'failed_case.json').exists()):
        raise ValueError('All 19 run03 cases must be complete before any source/bundle access or audit write')
    checks, hashes = old.Checks(), {}
    report = {'audit_version': 'v7_delayed_full_sensor_replay_v1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'audit_script_sha256': old.sha(__file__), 'reused_audit_helper_sha256': old.sha(old.__file__),
              'passed': False, 'development_only': True, 'fresh_validation': False, 'model_refit': False,
              'v7_streaming_tested': False, 'absolute_float_tolerance': old.ATOL,
              'checks': checks.records, 'hashes': hashes, 'replayed_rows': 0, 'complete_replayed_cases': 0,
              'attempt': ATTEMPT, 'inference_module': 'ml.gecco_v7.runtime_delayed',
              'cadence_contract': {'WaterHub': 'verified regular datetime grid, 60 seconds',
                                   'GECCO': 'nominal 60-second acquisition rows; 2018 wall-clock rollback retained',
                                   'maximum_confirmation_samples': 2, 'maximum_nominal_confirmation_seconds': 120},
              'limitations': ['PASS checks execution/accounting, not performance success or deployment readiness.',
                              'All sources are disclosed development; there is no fresh validation here.',
                              'Reuses the SHA-verified prior WaterHub raw adaptation audit; does not regenerate adaptation.',
                              'Uses frozen V6 ternary-label metrics; 120-second decisions and scalar alarm logic independently recomputed.',
                              'Prefix tests establish batch causality for the tested prefixes, not a persistent streaming implementation.',
                              'GECCO delay seconds are nominal acquisition cadence, not proof at its ambiguous wall-clock hour.',
                              'Artifact lineage cannot prove absence of every historical out-of-band data access.']}
    try:
        checks.require('development_scope_and_no_refit', plan['development_only'] is True and plan['fresh_validation'] is False
                       and completed['fresh_validation'] is False and plan['no_model_refit'] is True)
        hashes['plan.json'], hashes['results.json'] = old.sha(out / 'plan.json'), old.sha(out / 'results.json')
        parent = old.inside(root, plan['parent_run'])
        for filename, key in (('plan.json', 'parent_plan_sha256'), ('results.json', 'parent_results_sha256'), ('audit.json', 'parent_audit_sha256')):
            digest = old.sha(parent / filename); hashes['parent/' + filename] = digest
            checks.require('parent_lineage:' + filename, digest == plan[key])
        parent_audit, parent_plan = old.read_json(parent / 'audit.json'), old.read_json(parent / 'plan.json')
        checks.require('parent_full_audit_passed', parent_audit['passed'] is True and parent_audit['complete_replayed_cases'] == 19
                       and parent_audit['replayed_rows'] == 449431 and parent_plan['attempt'] == 'run02_hgb_guarded')
        checks.require('unchanged_parent_auditor', old.sha(old.__file__) == parent_audit['audit_script_sha256'])
        checks.tree('same_raw_inputs_as_audited_parent', plan['input_sha256'], parent_plan['input_sha256'])
        checks.require('new_frozen_core_included', {'ml/gecco_v7/' + name for name in EXTRA_CODE}.issubset(plan['code_sha256']))
        report['reused_source_adaptation_audit'] = old._verify_provenance(root, out,
            {**plan, 'attempt': 'run02_hgb_guarded'}, checks, hashes)
        _, comparison, stats = old._load_runtime(root, parent_plan)
        runtime_module = importlib.import_module('ml.gecco_v7.runtime_delayed')
        checks.require('runtime_resolved_to_verified_code', Path(runtime_module.__file__).resolve() == root / 'ml/gecco_v7/runtime_delayed.py')
        runtime = runtime_module.predict_frame
        sources, train19, valid19 = old._source_frames(root)
        specs = old.expected_geometry(sources, train19, valid19)
        checks.require('waterhub_source_length', len(sources['WaterHub']) == 480960)
        checks.array('waterhub_physical_regular_minute_grid',
                     np.diff(sources['WaterHub'].index.as_unit('ns').asi8), np.full(480959, 60 * 10**9))
        periods, by_source = [], {}
        for spec, saved in zip(specs, completed['periods']):
            period, rows = _audit_case(root, out, parent, parent_audit, spec, sources[spec['source']], saved,
                                      hashes['plan.json'], checks, hashes, runtime, comparison, stats)
            periods.append(period); by_source.setdefault(spec['source'], []).append(rows)
            report['replayed_rows'] += len(rows); report['complete_replayed_cases'] += 1
            print(json.dumps({'audited_case': spec['name'], 'rows': len(rows), 'cumulative_replayed_rows': report['replayed_rows']}), flush=True)
            gc.collect()
        measured_sources = {}
        for name, parts in by_source.items():
            whole = pd.concat(parts, ignore_index=True)
            checks.array(name + ':contiguous_original_axis_pool', np.diff(whole.sample_index), np.ones(len(whole) - 1, int))
            measured_sources[name] = comparisons(whole.label.to_numpy(np.int8),
                {key: whole[key].to_numpy(np.int8) for key in ('baseline', 'reference', 'candidate')}, comparison)
            checks.tree(name + ':source_pool_metrics', measured_sources[name], completed['sources'][name])
        measured_summary = summary(periods, measured_sources)
        checks.tree('independent_summary_and_relaxed_120s_gates', measured_summary, completed['summary'])
        report['recomputed_development_gates'] = {key: s['passes_declared_development_gate'] for key, s in measured_summary.items()}
        report['over_budget_paired_event_delays'] = [{'case': p['case'], **d} for p in periods for d in p['over_budget_paired_event_delays']]
        report['event_latency_contract_met_every_period'] = not report['over_budget_paired_event_delays']
        checks.require('full_expected_replayed_rows', report['replayed_rows'] == 449431)
        for filename in ('plan.json', 'results.json'):
            checks.require('unchanged_result:' + filename, old.sha(out / filename) == hashes[filename])
        for filename in ('plan.json', 'results.json', 'audit.json'):
            checks.require('unchanged_parent:' + filename, old.sha(parent / filename) == hashes['parent/' + filename])
        for relative, digest in plan['code_sha256'].items():
            checks.require('unchanged_current_code:' + relative, old.sha(old.inside(root, relative)) == digest)
    except Exception as error:
        report['exception'] = {'type': type(error).__name__, 'message': str(error)}
        checks.add('audit_completed_without_exception', False, detail=str(error))
    report['failed_checks'] = sum(not c['passed'] for c in checks.records)
    report['total_check_groups'] = len(checks.records)
    report['total_numeric_checks'] = sum(c['numeric_comparisons'] for c in checks.records)
    report['total_compared_values'] = sum(c['compared_values'] for c in checks.records)
    report['passed'] = report['failed_checks'] == 0 and report['complete_replayed_cases'] == 19
    (out / 'audit.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    report = audit_directory(parser.parse_args().output)
    print(json.dumps({key: report[key] for key in ('passed', 'failed_checks', 'total_numeric_checks', 'replayed_rows', 'complete_replayed_cases')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
