"""Independent V11 protected-pulse certificate and full sensor replay audit.

Import performs no IO. Run only after all nineteen authorized development cases
finish. Reuse pinned V9 training/reference/feature oracles and its raw sensor
replay, without modifying that auditor. A separate scalar state machine below
checks the new policy. Models are never fitted; trusted local joblib objects are
opened only after their artifact hashes. PASS is accounting, not performance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import importlib
import json
from pathlib import Path
import sys
from types import FunctionType

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ml.gecco_v9_audits import replay as v9
from ml.gecco_v10_audits import replay as v10
from ml.gecco_v7_audits import replay_certified as cert

old = v9.old
sha, read_json, inside, Checks = old.sha, old.read_json, old.inside, old.Checks
EXPECTED_NAMES = old.EXPECTED_NAMES
ATTEMPT = 'v11_run01_preserve_retained_if_pulses'
VERSION = 'v11_protected_reference_pulse_120s'
V10_AUDITOR_SHA = 'c760ebe7c2c794090ba199461f773f747d1ba70ef58df06b2c76800d0d47b4e2'
V9_AUDITOR_SHA = 'abaf8c04b6daa55d2698ee5e43c8e7b6e4b482e132cddeab70324052706d942c'
CHOICE_KEYS = ('decision', 'low_threshold', 'high_threshold', 'policy', 'confirmation_samples',
               'cadence_seconds', 'max_confirmation_seconds', 'confirmation_delay_seconds', 'pending_after_clear', 'retained_if_protection')
comparisons, summary = v9.comparisons, v9.independent_summary


def fixed_choice(selected):
    return {key: selected[key] for key in CHOICE_KEYS}


def reference_choice():
    return dict(decision='reference', low_threshold=None, high_threshold=None, policy='instant',
                confirmation_samples=0, cadence_seconds=60.0, max_confirmation_seconds=120.0,
                confirmation_delay_seconds=0.0, pending_after_clear=False, retained_if_protection=True)


def scalar_paths(reference, confidence, rescue, choice, *, baseline):
    """One row at a time: final output, pure seed, unextended seed and owners.

    Each pending owner is inserted when its reference pulse clears, with the
    original fixed deadline. No future pulse end or future score is examined.
    An old owner's release cannot latch or reset a newly active reference pulse.
    A simultaneous current IF/reference alarm releases the active episode and
    latches it; because it is delivered, it cannot become pending after clear.
    """
    ref = old.ternary(reference, 'reference')
    baseline = old.ternary(baseline, 'baseline')
    if baseline.shape != ref.shape:
        raise ValueError('Baseline and reference axes must align')
    if choice.get('retained_if_protection') is not True:
        raise ValueError('The frozen retained-IF protection must be enabled')
    confidence, rescue = np.asarray(confidence, float), np.asarray(rescue, float)
    if confidence.shape != ref.shape or rescue.shape != ref.shape:
        raise ValueError('Aligned one-dimensional score axes required')
    cadence, deadline = choice['cadence_seconds'], choice['confirmation_samples']
    low, high, pending = choice['low_threshold'], choice['high_threshold'], choice['pending_after_clear']
    if isinstance(cadence, (bool, np.bool_)) or not np.isscalar(cadence) or not np.isfinite(cadence) or cadence <= 0:
        raise ValueError('Finite positive cadence required')
    if isinstance(deadline, (bool, np.bool_)) or not isinstance(deadline, (int, np.integer)):
        raise ValueError('Integer deadline required')
    if not isinstance(pending, (bool, np.bool_)) or (pending and (low is None or not deadline)):
        raise ValueError('Pending requires an active bounded confirmation path')
    if choice['max_confirmation_seconds'] != 120 or choice['confirmation_delay_seconds'] != deadline * cadence:
        raise ValueError('Deadline physical contract mismatch')
    if (low is None and deadline != 0) or (low is not None and (deadline not in (1, 2) or deadline * cadence > 120)):
        raise ValueError('Unsupported deadline')
    for threshold in (low, high):
        if threshold is not None and (isinstance(threshold, (bool, np.bool_)) or not np.isfinite(threshold)):
            raise ValueError('Finite scalar threshold required')
    if low is not None and high is not None and low > high:
        raise ValueError('Low exceeds high')
    windows = {'instant': (1, 1), '2of3': (3, 2), '3of5': (5, 3)}
    if choice['policy'] not in windows:
        raise ValueError('Unknown rescue policy')
    width, count = windows[choice['policy']]
    a0, seed, result = ref.copy(), ref.copy(), ref.copy()
    origins = np.full(len(ref), -1, np.int64)
    active = None
    released = False
    waiting = []
    for i, r in enumerate(ref):
        if r < 0:
            active, released, waiting = None, False, []
        else:
            if r == 0 and active is not None:
                if pending and not released and i <= active + deadline:
                    waiting.append((active, active + deadline))
                active, released = None, False
            if r == 1:
                if active is None:
                    active, released = i, False
                if baseline[i] == 1 or low is None or not np.isfinite(confidence[i]) or confidence[i] >= low or i - active >= deadline:
                    released = True
                a0[i] = int(released)
        seed[i] = a0[i]
        retained = []
        for owner, until in waiting:
            if i > until:
                continue
            if r >= 0 and np.isfinite(confidence[i]) and confidence[i] >= low:
                seed[i], origins[i] = 1, owner
            else:
                retained.append((owner, until))
        waiting = retained
        result[i] = seed[i]
        if high is not None and r >= 0 and i >= width - 1:
            recent = rescue[i - width + 1:i + 1]
            if np.isfinite(recent).all() and rescue[i] >= high and sum(v >= high for v in recent) >= count:
                result[i] = 1
    return result, seed, a0, origins


def scalar_prediction(reference, confidence, rescue, choice, *, baseline):
    result, seed, _, _ = scalar_paths(reference, confidence, rescue, choice, baseline=baseline)
    return result, seed


def protection_accounting(reference, baseline, paths):
    """Attribute the rule only to A0; pending and rescue may alarm after clear."""
    ref, base = np.asarray(reference), np.asarray(baseline)
    final, seed, unextended, _ = paths
    protected = (ref == 1) & (base == 1)
    return {'retained_if_protected_rows': int(protected.sum()),
        'protected_rows_withheld_by_unextended_seed': int((protected & (unextended != 1)).sum()),
        'unextended_seed_alarm_rows_outside_reference_alarm': int(((ref != 1) & (unextended == 1)).sum()),
        'pending_seed_alarm_rows_on_reference_zero': int(((ref == 0) & (seed == 1)).sum()),
        'final_alarm_rows_on_if_one_reference_zero': int(((base == 1) & (ref == 0) & (final == 1)).sum()),
        'interpretation': 'Zero resurrection applies to protected unextended A0. Pending and independent rescue can create reference-zero alarms; final rows are not attributed to IF protection merely because IF also alarms.'}


def spans(values, wanted):
    answer = []
    i = 0
    while i < len(values):
        if values[i] != wanted:
            i += 1
            continue
        start = i
        while i < len(values) and values[i] == wanted:
            i += 1
        answer.append((start, i))
    return answer


def pulse_scope(labels, reference, seed, origins, choice, source_start):
    """Every positive segment/reference-pulse intersection is an obligation."""
    positive, episodes = spans(labels, 1), spans(reference, 1)
    retained = censored = obligations = 0
    failures = []
    within = int(np.floor(120 / choice['cadence_seconds']))
    first = 0
    for episode_id, (a, b) in enumerate(episodes, 1):
        while first < len(positive) and positive[first][1] <= a:
            first += 1
        j = first
        while j < len(positive) and positive[j][0] < b:
            c, d = positive[j]
            anchor = max(a, c)
            last = min(d, anchor + within + 1)
            kept = any(seed[t] == 1 for t in range(anchor, min(b, last)))
            if not kept:
                kept = any(seed[t] == 1 and origins[t] == a
                           for t in range(max(anchor, b), min(last, a + choice['confirmation_samples'] + 1)))
            left_censored = a == 0 or reference[a - 1] < 0
            obligations += 1
            retained += int(kept)
            censored += int(left_censored)
            if not kept:
                failures.append({'episode_id': episode_id, 'positive_segment_id': j + 1,
                    'episode_start': a, 'episode_end_exclusive': b,
                    'positive_segment_start': c, 'positive_segment_end_exclusive': d,
                    'first_positive_reference_row': anchor, 'left_censored_reference_episode': bool(left_censored),
                    'source_episode_start': source_start + a, 'source_positive_reference_row': source_start + anchor})
            j += 1
    return {'passed': not failures, 'obligations': obligations, 'retained_obligations': retained,
        'censored_fragment_obligations': censored, 'lost_positive_reference_pulses': failures,
        'rejection_reasons': [] if not failures else ['positive_reference_pulse_not_retained_within120s_in_same_segment']}


def pulse_assessment(blocks, seeds, traces, choice):
    y = np.concatenate([b['labels'] for b in blocks])
    r = np.concatenate([b['reference'] for b in blocks])
    p = np.concatenate(seeds)
    bounds = np.r_[0, np.cumsum([len(b['labels']) for b in blocks])]
    trace = np.full(len(y), -1, np.int64)
    # Construct global episode identities without compressing missing rows.
    episode_owner = np.full(len(y), -1, np.int64)
    for a, b in spans(r, 1):
        episode_owner[a:b] = a
    for offset, local in zip(bounds[:-1], traces):
        for at in np.flatnonzero(local >= 0):
            trace[offset + at] = episode_owner[offset + local[at]]
    scopes = [{'scope': 'pool', **pulse_scope(y, r, p, trace, choice, blocks[0]['source_start'])}]
    for i, (b, output, origin) in enumerate(zip(blocks, seeds, traces)):
        scopes.append({'scope': f'block_{i}', **pulse_scope(b['labels'], b['reference'], output, origin, choice, b['source_start'])})
    reasons = [s['scope'] + ':' + reason for s in scopes for reason in s['rejection_reasons']]
    return {'passed': not reasons, 'rejection_reasons': reasons, 'scopes': scopes,
        'interpretation': 'Observed-positive episode/segment obligations; censored fragments retained but do not add primary-event evidence. Pure confirmation path before rescue; original event-ID metrics remain independent.'}


def added_evidence(blocks, outputs, base, active, path, stats):
    y = np.concatenate([b['labels'] for b in blocks])
    p, seed = np.concatenate(outputs), np.concatenate(base)
    bounds = np.r_[0, np.cumsum([len(b['labels']) for b in blocks])]
    normal = (y == 0) & (p == 1) & (seed != 1)
    by_block = [int(normal[a:b].sum()) for a, b in zip(bounds[:-1], bounds[1:])]
    additions = (y == 1) & (p == 1) & (seed != 1)
    ids, owners = [], []
    for e in stats(y, seed, 60)['primary_event_intervals']:
        added = np.flatnonzero(additions[e['start']:e['end_exclusive']])
        if len(added):
            ids.append(e['event_id'])
            owners.append(int(np.searchsorted(bounds, e['start'] + added[0], side='right') - 1))
    checks = {'no_added_known_normal_rows_global': not normal.any(),
        'no_added_known_normal_rows_in_any_block': not any(by_block),
        f'at_least_two_original_{path}_coverage_events': not active or len(ids) >= 2,
        f'{path}_first_additions_in_at_least_two_blocks': not active or len(set(owners)) >= 2}
    return {'active': bool(active), 'path': path, 'passed': all(checks.values()), 'checks': checks,
        'rejection_reasons': [k for k, v in checks.items() if not v],
        'added_known_normal_rows': int(normal.sum()), 'added_known_normal_rows_by_block': by_block,
        'coverage_event_ids': ids, 'first_addition_blocks': sorted(set(owners)),
        'event_ownership': 'original primary onset; each event belongs to its first added positive row',
        'comparison_baseline': 'unextended confirmation A0' if path == 'pending' else 'pure confirmation plus pending P'}


def fixed_checks(blocks, choice, stats):
    paths = [scalar_paths(b['reference'], b['long_scores'], b['rescue_scores'], choice, baseline=b['baseline']) for b in blocks]
    outputs, seeds, unextended, traces = map(list, zip(*paths))
    return {'candidate': cert.assessment(blocks, outputs, stats),
        'pure_confirmation_seed': cert.assessment(blocks, seeds, stats),
        'positive_reference_pulses': pulse_assessment(blocks, seeds, traces, choice),
        'pending': added_evidence(blocks, seeds, unextended, choice['pending_after_clear'], 'pending', stats),
        'rescue': added_evidence(blocks, outputs, seeds, choice['high_threshold'] is not None, 'rescue', stats)}


def independent_certificate(blocks, proposed, stats):
    later = blocks[2:]
    evidence = cert.evidence(later, stats)
    assessed = fixed_checks(later, proposed, stats)
    checks = {'adequate_observed_normal_exposure': evidence['enough_observed_normal_exposure'],
        'adequate_primary_event_representation': evidence['enough_primary_event_representation'],
        **{name + '_passed': value['passed'] for name, value in assessed.items()}}
    reasons = [key for key, passed in checks.items() if not passed]
    reasons += [name + ':' + reason for name, value in assessed.items() for reason in value['rejection_reasons']]
    certificate = {'passed': not reasons, 'checks': checks, 'rejection_reasons': reasons,
        'fixed_choice': proposed, 'evidence': evidence, **assessed,
        'interpretation': 'Temporal veto of incremental policy conditional on V6 calibrated on all4; not independent validation of whole pipeline.'}
    all_four, early = fixed_checks(blocks, proposed, stats), fixed_checks(blocks[:2], proposed, stats)
    veto = {'earlier_pure_confirmation_seed': early['pure_confirmation_seed'],
        'earlier_positive_reference_pulses': early['positive_reference_pulses'], 'earlier_pending': early['pending'],
        **{'all_four_' + name: value for name, value in all_four.items()}}
    veto_reasons = [name + ':' + reason for name, value in veto.items() for reason in value['rejection_reasons']]
    return certificate, veto, bool(certificate['passed'] and not veto_reasons), reasons + veto_reasons


def _calibration(checks, name, cal, prior_cal, parent_cal, bounds, selected, comparison, stats):
    origin = bounds[0]
    blocks = []
    for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        part = cal.iloc[a - origin:b - origin]
        blocks.append({'labels': part.label.to_numpy(np.int8), 'reference': part.reference.to_numpy(np.int8),
            'baseline': part.baseline.to_numpy(np.int8),
            'long_scores': part.long_context.to_numpy(), 'rescue_scores': part.rescue_long_context.to_numpy(),
            'source_start': a, 'block_id': str(i)})
    proposed = fixed_choice(selected['earlier_selected'])
    early = fixed_checks(blocks[:2], proposed, stats)
    for key, value in early.items():
        checks.require(name + ':early_selected_feasible:' + key, value['passed'])
    ev = cert.evidence(blocks[:2], stats)
    stored_ev = selected['earlier_selected']['evidence']
    for key, value in ev.items():
        checks.tree(name + ':early_evidence:' + key, stored_ev[key], value)
    if proposed['decision'] != 'reference':
        checks.require(name + ':early_evidence_minima', ev['enough_observed_normal_exposure'] and ev['enough_primary_event_representation'])
    early_paths = [scalar_paths(b['reference'], b['long_scores'], b['rescue_scores'], proposed, baseline=b['baseline'])[0] for b in blocks[:2]]
    for i, (y, p) in enumerate([(np.concatenate([b['labels'] for b in blocks[:2]]), np.concatenate(early_paths))]
                              + [(b['labels'], p) for b, p in zip(blocks[:2], early_paths)]):
        measured = stats(y, p, 60)
        expected = (selected['earlier_selected']['calibration_metrics'] if i == 0
                    else selected['earlier_selected']['calibration_block_metrics'][i - 1])
        checks.tree(name + ':early_selected_metrics:' + str(i), measured, expected)
    certificate, veto, accepted, reasons = independent_certificate(blocks, proposed, stats)
    checks.tree(name + ':independent_later_certificate', certificate, selected['certification'])
    checks.tree(name + ':independent_all_four_veto', veto, selected['global_veto'])
    checks.tree(name + ':certificate_acceptance', accepted, selected['certification_passed'])
    checks.tree(name + ':certificate_rejection_reasons', reasons, selected['certification_rejection_reasons'])
    final = proposed if accepted else reference_choice()
    checks.tree(name + ':fixed_choice_or_complete_fallback', fixed_choice(selected), final)
    checks.tree(name + ':final_choice_snapshot', selected['final_selected'], final)
    checks.tree(name + ':only_early_selection_blocks', selected['selection_blocks'], ['0', '1'])
    checks.tree(name + ':only_later_veto_blocks', selected['certification_blocks'], ['2', '3'])
    checks.require(name + ':single_certificate_attempt', selected['certification_attempts'] == 1)
    checks.array(name + ':prior_calibration_original_axis', prior_cal.sample_index, cal.sample_index)
    gate, rescue = v9.independent_masks(prior_cal[['level', 'jump', 'sustained']], cal.long_context)
    checks.array(name + ':unchanged_guarded_score', gate, cal.guarded_long_context, floating=True)
    checks.array(name + ':unchanged_rescue_score', rescue, cal.rescue_long_context, floating=True)
    outputs = [scalar_prediction(b['reference'], b['long_scores'], b['rescue_scores'], final, baseline=b['baseline'])[0] for b in blocks]
    checks.array(name + ':final_calibration_scalar_policy', np.concatenate(outputs), cal.candidate)
    assessed = cert.assessment(blocks, outputs, stats)
    checks.require(name + ':final_calibration_constraints', assessed['passed'])
    checks.tree(name + ':final_calibration_stats', stats(cal.label.to_numpy(np.int8), cal.candidate.to_numpy(np.int8), 60), selected['calibration_metrics'])
    for i, (b, p) in enumerate(zip(blocks, outputs)):
        checks.tree(name + ':final_calibration_block:' + str(i), stats(b['labels'], p, 60), selected['calibration_block_metrics'][i])
    checks.tree(name + ':paired_calibration_delays', assessed['scopes'][0]['paired_extra_delays'], selected['calibration_paired_delays'])


def trial_rank(row):
    def number(value):
        return None if value is None or pd.isna(value) else float(value)
    low, high = number(row['low_threshold']), number(row['high_threshold'])
    pending = bool(row['pending_after_clear'])
    return (-int(row['events']), int(row['false_runs']), int(row['fp']), -int(row['tp']),
        int(low is not None) + int(high is not None) + int(pending), int(row['confirmation_samples']),
        low if low is not None else -np.inf, -high if high is not None else -np.inf,
        ('instant', '2of3', '3of5').index(row['policy']), int(pending))


def _trial_selection(checks, name, trials, selected):
    earlier = trials[trials.stage == 'earlier_selection']
    later = trials[trials.stage == 'later_certification_and_global_veto']
    checks.require(name + ':one_later_veto_not_search', len(later) == 1 and len(trials) == len(earlier) + 1
        and len(earlier) == selected['selection_trial_count'] and len(trials) == selected['trial_count'])
    records = earlier.to_dict('records')
    feasible = [r for r in records if r['feasible'] is True]
    checks.require(name + ':early_feasible_candidate_exists', bool(feasible))
    best = min(feasible, key=trial_rank)
    checks.tree(name + ':early_fixed_rank', trial_rank(best), trial_rank(selected['earlier_selected']))
    for label, row in (('best', best), ('later', later.iloc[0])):
        for key in CHOICE_KEYS:
            actual = row[key]
            if key in ('low_threshold', 'high_threshold') and pd.isna(actual):
                actual = None
            if key in ('pending_after_clear', 'retained_if_protection'):
                if not isinstance(actual, (bool, np.bool_)):
                    raise ValueError('Stored pending choice must remain boolean')
                actual = bool(actual)
            checks.tree(name + ':' + label + '_same_early_choice:' + key, actual, selected['earlier_selected'][key])
    checks.tree(name + ':later_trial_acceptance', bool(later.iloc[0]['feasible']), selected['certification_passed'])


def method_spec(plan):
    if plan.get('attempt') != ATTEMPT:
        raise ValueError('Exact reviewed V11 attempt required')
    return {'runtime': 'ml.gecco_v11.runtime', 'bundle_version': VERSION,
            'model_class': 'ConditionalResidualHGBScorer', 'guarded_score': True, 'extra_code': []}


def _audit_case(root, out, parent, parent_audit, spec, source, saved_top, plan_sha,
                checks, hashes, runtime, comparison, stats):
    import joblib
    name = spec['name']
    folder, before_folder = out / name, parent / name
    frozen, before = read_json(folder / 'freeze.json'), read_json(before_folder / 'freeze.json')
    checks.require(name + ':parent_case_location', inside(root, frozen['parent_folder']) == before_folder)
    checks.require(name + ':declared_no_refit', frozen['training_reused_without_refit'] is True and saved_top['model_refitted'] is False)
    for filename, digest in frozen['parent_sha256'].items():
        actual = sha(before_folder / filename)
        hashes[name + '/parent/' + filename] = actual
        checks.require(name + ':parent_artifact_from_passing_audit:' + filename,
            actual == digest == parent_audit['hashes'][name + '/' + filename])
    checks.require(name + ':both_bundle_sha_before_unpickle', sha(folder / 'bundle.joblib') == frozen['bundle_sha256']
        and sha(before_folder / 'bundle.joblib') == before['bundle_sha256'] == frozen['parent_sha256']['bundle.joblib'])
    # Keep reusable frozen functions unchanged; bindings exist only in this call.
    captured = {}
    def replay_runtime(bundle, sensors):
        actual = runtime(bundle, sensors)
        if not captured:
            captured['baseline'] = actual.baseline_prediction.to_numpy(np.int8).copy()
            captured['reference'] = actual.reference_prediction.to_numpy(np.int8).copy()
        return actual
    def test_scalar(reference, confidence, rescue, choice):
        if not np.array_equal(reference, captured['reference']):
            raise ValueError('Full-test scalar oracle must use its explicit replayed baseline axis')
        paths = scalar_paths(reference, confidence, rescue, choice, baseline=captured['baseline'])
        captured['protection_accounting'] = protection_accounting(reference, captured['baseline'], paths)
        return paths[0], paths[1]
    namespace = {**v9._audit_case.__globals__, '_certified_calibration': _calibration,
                 '_trial_selection': _trial_selection, 'scalar_prediction': test_scalar}
    replay = FunctionType(v9._audit_case.__code__, namespace, v9._audit_case.__name__)
    period, rows = replay(root, out, spec, source, saved_top, plan_sha, checks, hashes,
                         replay_runtime, comparison, stats, method_spec({'attempt': ATTEMPT}))
    protected = (rows.reference.to_numpy() == 1) & (rows.baseline.to_numpy() == 1)
    checks.array(name + ':retained_if_rows_never_withheld', rows.candidate.to_numpy()[protected], np.ones(int(protected.sum()), np.int8))
    accounting = captured['protection_accounting']
    checks.require(name + ':unextended_protection_never_restores_reference_quiet_or_unknown',
        accounting['unextended_seed_alarm_rows_outside_reference_alarm'] == 0
        and accounting['protected_rows_withheld_by_unextended_seed'] == 0)
    period['retained_if_protection_audit'] = accounting
    bundle, original = joblib.load(folder / 'bundle.joblib'), joblib.load(before_folder / 'bundle.joblib')
    checks.require(name + ':exact_parent_version', original['version'] == v10.VERSION and bundle['version'] == VERSION)
    for key in ('long_model', 'reference_bundle'):
        first, second = cert.fitted_state_digest(original[key]), cert.fitted_state_digest(bundle[key])
        hashes[name + '/fitted_state/' + key] = second
        checks.require(name + ':identical_fitted_state_without_refit:' + key, first == second)
    original_meta = {key: value for key, value in original.items() if key not in ('version', 'selected', 'long_model', 'reference_bundle')}
    current_meta = {key: value for key, value in bundle.items() if key not in ('version', 'selected', 'long_model', 'reference_bundle')}
    checks.tree(name + ':unchanged_remaining_bundle_metadata', current_meta, original_meta)
    checks.tree(name + ':copied_model_inspection', read_json(folder / 'model_inspection.json'), read_json(before_folder / 'model_inspection.json'))
    checks.tree(name + ':copied_conditional_coverage', saved_top['conditional_block_test_coverage'], read_json(before_folder / 'results.json')['conditional_block_test_coverage'])
    if name in old.REPRESENTATIVE_NAMES:
        short = source.iloc[spec['test'][0]:min(spec['test'][1], spec['test'][0] + 200)].loc[:, spec['channels']].copy()
        short.index = pd.date_range('2020-01-01', periods=len(short), freq='2min')
        rejected = False
        try:
            runtime(bundle, short)
        except ValueError:
            rejected = True
        checks.require(name + ':physical_timestamp_cadence_mismatch_rejected', rejected)
    for filename in ('calibration_scores.csv.gz', 'predictions.csv.gz'):
        new, prior = [pd.read_csv(p / filename, float_precision='round_trip') for p in (folder, before_folder)]
        checks.tree(name + ':parent_column_projection:' + filename, list(new.columns), list(prior.columns) + ['v10_candidate'])
        for column in prior:
            actual = 'v10_candidate' if column == 'candidate' else column
            checks.array(name + ':unchanged_parent_rows:' + filename + ':' + column, new[actual], prior[column], floating=prior[column].dtype.kind == 'f')
    return period, rows


def audit_directory(output, *, workspace_root=None):
    out = Path(output).resolve()
    root = Path(workspace_root).resolve() if workspace_root else ROOT
    plan, completed = read_json(out / 'plan.json'), read_json(out / 'results.json')
    if (plan.get('attempt') != ATTEMPT or plan.get('scope') != 'all' or plan.get('limit_cases') != 19
            or completed.get('complete_cases') != 19 or completed.get('expected_cases') != 19
            or completed.get('all_prespecified_cases_complete') is not True
            or [p.get('case') for p in completed.get('periods', [])] != EXPECTED_NAMES
            or not completed.get('completed_at_utc') or (out / 'failed_case.json').exists()):
        raise ValueError('All nineteen completed V11 cases required before source access or audit write')
    checks, hashes = Checks(), {}
    report = {'audit_version': 'v11_retained_if_full_raw_sensor_replay_v1',
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'audit_script_sha256': sha(__file__),
        'passed': False, 'attempt': ATTEMPT, 'development_only': True, 'fresh_validation': False,
        'model_refit': False, 'streaming_tested': False, 'absolute_float_tolerance': old.ATOL,
        'checks': checks.records, 'hashes': hashes, 'replayed_rows': 0, 'complete_replayed_cases': 0,
        'limitations': ['PASS verifies artifacts, numerical replay and accounting, not performance or deployment approval.',
            'All nineteen cases are disclosed development; no new source is accessed.',
            'V9 independent fitted-reference/weight/conditional-feature checks are reused unchanged and re-executed; model state is also compared to the passing V10 parent.',
            'WaterHub raw adaptation evidence is reused and hash-verified, not re-derived again.',
            'V6 ternary-label metrics are reused; scalar retained-IF release/latch, pending, pulse ownership, later certificate and all-period gates are independently recomputed.',
            'Prefix/future/label checks are batch causality checks; this does not validate a V11 streaming implementation.',
            'GECCO delay seconds use nominal acquisition minutes; WaterHub uses its actual regular minute grid.',
            'Stored early trial ranking is verified, and the chosen early operating point is independently checked; the complete threshold grid is not searched again.',
            'Artifacts cannot prove the absence of every historical out-of-band observation.']}
    try:
        checks.require('complete_development_scope_no_refit', plan['development_only'] is True and plan['fresh_validation'] is False
            and plan['all_sources_previously_disclosed'] is True and plan['no_model_refit'] is True
            and completed['candidate_version'] == 'V11' and completed['model_refitted'] is False)
        hashes['plan.json'], hashes['results.json'] = sha(out / 'plan.json'), sha(out / 'results.json')
        checks.require('frozen_v9_auditor_unchanged', sha(v9.__file__) == V9_AUDITOR_SHA)
        checks.require('frozen_v10_auditor_unchanged', sha(v10.__file__) == V10_AUDITOR_SHA)
        parent = inside(root, plan['parent_run'])
        for filename in ('plan.json', 'results.json', 'audit.json'):
            hashes['parent/' + filename] = sha(parent / filename)
            checks.require('parent_lineage:' + filename, hashes['parent/' + filename] == plan['parent_sha256'][filename])
        parent_plan, parent_results, parent_audit = [read_json(parent / filename) for filename in ('plan.json', 'results.json', 'audit.json')]
        checks.require('matching_full_passing_v10_audit', parent_audit['passed'] is True and parent_audit['failed_checks'] == 0
            and parent_audit['complete_replayed_cases'] == 19 and parent_audit['replayed_rows'] == 449431
            and parent_audit['audit_script_sha256'] == V10_AUDITOR_SHA
            and parent_audit['audit_version'] == 'v10_pending_pulse_full_raw_sensor_replay_v1'
            and parent_plan['attempt'] == v10.ATTEMPT
            and parent_audit['hashes']['plan.json'] == hashes['parent/plan.json']
            and parent_audit['hashes']['results.json'] == hashes['parent/results.json']
            and parent_results['candidate_version'] == 'V10'
            and [p['case'] for p in parent_results['periods']] == EXPECTED_NAMES)
        checks.require('v11_production_code_frozen', {'ml/gecco_v11/' + f for f in ('development.py', 'runtime.py', 'calibration.py')}.issubset(plan['code_sha256']))
        for relative, digest in parent_plan['code_sha256'].items():
            checks.require('inherited_production_code_unchanged:' + relative, plan['code_sha256'].get(relative) == digest)
        for relative, digest in parent_plan['input_sha256'].items():
            checks.require('inherited_raw_source_unchanged:' + relative, plan['input_sha256'].get(relative) == digest)
        report['reused_source_adaptation_audit'] = v9._verify_provenance(root, out, {**plan, 'attempt': v9.ATTEMPT}, checks, hashes)
        _, comparison, stats = old._load_runtime(root, {**plan, 'attempt': 'run02_hgb_guarded'})
        module = importlib.import_module('ml.gecco_v11.runtime')
        checks.require('runtime_from_verified_source', Path(module.__file__).resolve() == root / 'ml/gecco_v11/runtime.py')
        sources, train19, valid19 = old._source_frames(root)
        specs = old.expected_geometry(sources, train19, valid19)
        checks.tree('independent_case_geometry_order', [s['name'] for s in specs], EXPECTED_NAMES)
        checks.require('waterhub_source_length', len(sources['WaterHub']) == 480960)
        checks.array('waterhub_regular_physical_grid', np.diff(sources['WaterHub'].index.as_unit('ns').asi8), np.full(480959, 60 * 10**9))
        periods, pools = [], {}
        for spec, saved in zip(specs, completed['periods']):
            period, rows = _audit_case(root, out, parent, parent_audit, spec, sources[spec['source']], saved,
                hashes['plan.json'], checks, hashes, module.predict_frame, comparison, stats)
            periods.append(period)
            pools.setdefault(spec['source'], []).append(rows)
            report['replayed_rows'] += len(rows)
            report['complete_replayed_cases'] += 1
            print(json.dumps({'audited_case': spec['name'], 'rows': len(rows), 'cumulative_replayed_rows': report['replayed_rows']}), flush=True)
            gc.collect()
        measured_sources = {}
        for name, parts in pools.items():
            whole = pd.concat(parts, ignore_index=True)
            checks.array(name + ':contiguous_pooled_original_axis', np.diff(whole.sample_index), np.ones(len(whole) - 1, int))
            measured_sources[name] = comparisons(whole.label.to_numpy(np.int8),
                {key: whole[key].to_numpy(np.int8) for key in ('baseline', 'reference', 'candidate')}, comparison)
            checks.tree(name + ':pooled_source_metrics', measured_sources[name], completed['sources'][name])
        measured_summary = summary(periods, measured_sources)
        checks.tree('independent_summary_and_all_original_gates', measured_summary, completed['summary'])
        report['recomputed_development_gates'] = {k: v['passes_declared_development_gate'] for k, v in measured_summary.items()}
        report['calibration_sensor_rows_replayed'] = sum(p['calibration_sensor_rows_replayed'] for p in periods)
        report['conditional_audit_by_case'] = {p['case']: p['conditional_audit'] for p in periods}
        report['onset_weighting_counts_by_case'] = {p['case']: p['onset_weighting_counts'] for p in periods}
        report['retained_if_protection_by_case'] = {p['case']: p['retained_if_protection_audit'] for p in periods}
        checks.require('all_expected_test_rows_replayed', report['replayed_rows'] == 449431)
        for filename in ('plan.json', 'results.json'):
            checks.require('unchanged_output:' + filename, sha(out / filename) == hashes[filename])
        for filename in ('plan.json', 'results.json', 'audit.json'):
            checks.require('unchanged_parent:' + filename, sha(parent / filename) == hashes['parent/' + filename])
        for relative, digest in plan['code_sha256'].items():
            checks.require('unchanged_current_code_after_replay:' + relative, sha(inside(root, relative)) == digest)
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    report = audit_directory(parser.parse_args().output)
    print(json.dumps({k: report[k] for k in ('passed', 'failed_checks', 'replayed_rows', 'complete_replayed_cases', 'total_numeric_checks')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
