"""Independent run04 replay: frozen models, earlier selection, later veto.

Reuses the unchanged run03 per-case sensor replay with explicit local bindings
for bundle version, certification accounting, and a length-delimited fitted
state digest. No file in the earlier attempt is edited. Only completed disclosed
development runs can be audited; import performs no source IO. The optional
lineage supplement checks trusted local model objects, never source rows.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gc
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import FunctionType

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from ml.gecco_v7_audits import replay_delayed as delayed
old = delayed.old
ATTEMPT = 'run04_hgb_temporal_certification_120s'
VERSION = 'v7_hgb_temporally_certified_120s'
EXTRA_CODE = delayed.EXTRA_CODE + ('recalibrate_certified.py', 'runtime_certified.py', 'calibration_certified.py')
DELAYED_HELPER_SHA = 'e71483016cbd0a5ffc18f25ede169ed9d61cecbde16ca3a322fa73c34ef52d5f'
CERTIFIED_CAL_SHA = '1f6809a73ebead4746f771a526d6ee7c5ac4987bd4d16aa4e21b3f3775f86fce'
comparisons, summary = delayed.comparisons, delayed.summary


def fixed_choice(selected):
    return {key: selected[key] for key in ('decision', 'low_threshold', 'high_threshold', 'policy',
            'confirmation_samples', 'cadence_seconds', 'max_confirmation_seconds', 'confirmation_delay_seconds')}


def assessment(blocks, outputs, stats):
    parts = [(b['labels'], b['reference'], p) for b, p in zip(blocks, outputs)]
    pool = tuple(np.concatenate([p[i] for p in parts]) for i in range(3))
    scopes = []; reasons = []
    for i, (y, r, p) in enumerate([pool] + parts):
        before, after = stats(y, r, 60), stats(y, p, 60)
        bt, ct = dict(zip(before['confirmed_event_ids'], before['confirmed_times'])), dict(zip(after['confirmed_event_ids'], after['confirmed_times']))
        lost = sorted(set(bt) - set(ct))
        paired = [{'event_id': k, 'extra_delay_seconds': float((ct[k] - t) * 60)} for k, t in bt.items() if k in ct]
        late = [d['event_id'] for d in paired if d['extra_delay_seconds'] > 120]
        checks = {'reference_event_ids_retained': not lost, 'paired_event_delay_at_most_120_seconds': not late,
                  'reference_availability_unchanged': bool(np.array_equal(r >= 0, p >= 0)),
                  'false_duration_not_increased': after['fp_duration_seconds'] <= before['fp_duration_seconds'],
                  'false_fragments_not_increased': after['false_positive_runs'] <= before['false_positive_runs']}
        scope = 'pool' if i == 0 else f'block_{i-1}'
        reasons.extend(scope + ':' + k for k, v in checks.items() if not v)
        scopes.append({'scope': scope, 'checks': checks, 'lost_reference_event_ids': lost,
                       'over_budget_event_ids': late, 'paired_extra_delays': paired,
                       'max_paired_extra_delay_seconds': max((d['extra_delay_seconds'] for d in paired), default=None),
                       'lost_positive_alarm_rows': int(((y == 1) & (r == 1) & (p != 1)).sum()),
                       'reference_events': before['confirmed_events'], 'candidate_events': after['confirmed_events'],
                       'reference_false_fragments': before['false_positive_runs'], 'candidate_false_fragments': after['false_positive_runs'],
                       'reference_false_seconds': before['fp_duration_seconds'], 'candidate_false_seconds': after['fp_duration_seconds']})
    return {'passed': not reasons, 'rejection_reasons': reasons, 'scopes': scopes}


def evidence(blocks, stats):
    y, r = [np.concatenate([b[k] for b in blocks]) for k in ('labels', 'reference')]
    global_stats = stats(y, r, 60); parts = [stats(b['labels'], b['reference'], 60) for b in blocks]
    bounds = np.r_[0, np.cumsum([len(b['labels']) for b in blocks])]
    qualified = [i for i, s in enumerate(parts) if s['normal_observed_seconds'] >= 1440 * 60]
    seconds = sum(parts[i]['normal_observed_seconds'] for i in qualified)
    eventful = sorted({int(np.searchsorted(bounds, e['start'], side='right') - 1) for e in global_stats['primary_event_intervals']})
    return {'enough_observed_normal_exposure': len(qualified) >= 2 and seconds >= 5760 * 60,
            'enough_primary_event_representation': global_stats['true_events'] >= 5 and len(eventful) >= 2,
            'primary_events': global_stats['true_events'], 'eventful_blocks': eventful, 'qualified_blocks': qualified,
            'qualified_normal_minutes': seconds / 60,
            'observed_normal_minutes_by_block': [s['normal_observed_seconds'] / 60 for s in parts],
            'min_events': 5, 'min_eventful_blocks': 2, 'min_observed_blocks': 2,
            'min_normal_minutes_per_block': 1440, 'min_total_normal_minutes': 5760,
            'source_range': [blocks[0]['source_start'], blocks[-1]['source_start'] + len(blocks[-1]['labels'])],
            'block_ids': [b['block_id'] for b in blocks]}


def rescue_evidence(blocks, outputs, seeds, choice, stats):
    y = np.concatenate([b['labels'] for b in blocks]); p, seed = np.concatenate(outputs), np.concatenate(seeds)
    bounds = np.r_[0, np.cumsum([len(b['labels']) for b in blocks])]
    normal = (y == 0) & (p == 1) & (seed != 1)
    normal_by_block = [int(normal[a:b].sum()) for a, b in zip(bounds[:-1], bounds[1:])]
    added = (y == 1) & (p == 1) & (seed != 1); ids = []; owners = []
    for e in stats(y, seed, 60)['primary_event_intervals']:
        positions = np.flatnonzero(added[e['start']:e['end_exclusive']])
        if len(positions):
            ids.append(e['event_id']); owners.append(int(np.searchsorted(bounds, e['start'] + positions[0], side='right') - 1))
    active = choice['high_threshold'] is not None
    checks = {'no_added_known_normal_rows_global': not normal.any(),
              'no_added_known_normal_rows_in_any_block': not any(normal_by_block),
              'at_least_two_original_rescue_coverage_events': not active or len(ids) >= 2,
              'rescue_first_additions_in_at_least_two_blocks': not active or len(set(owners)) >= 2}
    return {'active': active, 'passed': all(checks.values()), 'checks': checks,
            'rejection_reasons': [k for k, v in checks.items() if not v],
            'added_known_normal_rows': int(normal.sum()), 'added_known_normal_rows_by_block': normal_by_block,
            'coverage_event_ids': ids, 'first_addition_blocks': sorted(set(owners)),
            'event_ownership': 'original primary onset; each event belongs to its first added positive row'}


def independent_certificate(blocks, proposed, stats):
    predicted, seeds = [], []
    for b in blocks:
        p, seed = delayed.scalar_prediction(b['reference'], b['long_scores'], b['rescue_scores'], proposed)
        predicted.append(p); seeds.append(seed)
    late = blocks[2:]; ev = evidence(late, stats)
    candidate = assessment(late, predicted[2:], stats); seed = assessment(late, seeds[2:], stats)
    rescue = rescue_evidence(late, predicted[2:], seeds[2:], proposed, stats)
    checks = {'adequate_observed_normal_exposure': ev['enough_observed_normal_exposure'],
              'adequate_primary_event_representation': ev['enough_primary_event_representation'],
              'candidate_preserves_reference_constraints': candidate['passed'],
              'pure_confirmation_seed_preserves_reference_constraints': seed['passed'],
              'rescue_has_independent_coverage_without_normal_additions': rescue['passed']}
    reasons = [k for k, v in checks.items() if not v]
    reasons += ['candidate:' + r for r in candidate['rejection_reasons']]
    reasons += ['pure_seed:' + r for r in seed['rejection_reasons']]
    reasons += ['rescue:' + r for r in rescue['rejection_reasons']]
    certificate = {'passed': all(checks.values()), 'checks': checks, 'rejection_reasons': reasons,
                   'fixed_choice': proposed, 'evidence': ev, 'candidate': candidate,
                   'pure_confirmation_seed': seed, 'rescue': rescue,
                   'interpretation': 'temporal veto of incremental policy conditional on V6 calibrated using all four blocks; not an independent pipeline holdout'}
    veto = {'earlier_pure_confirmation_seed': assessment(blocks[:2], seeds[:2], stats),
            'all_four_pure_confirmation_seed': assessment(blocks, seeds, stats),
            'all_four_candidate': assessment(blocks, predicted, stats)}
    veto_reasons = [name + ':' + reason for name, value in veto.items() for reason in value['rejection_reasons']]
    return certificate, veto, bool(certificate['passed'] and not veto_reasons), reasons + veto_reasons


def _calibration(checks, name, cal, prior_cal, parent_cal, bounds, selected, comparison, stats):
    origin = bounds[0]; blocks = []
    for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        part = cal.iloc[a-origin:b-origin]
        blocks.append({'labels': part.label.to_numpy(np.int8), 'reference': part.reference.to_numpy(np.int8),
                       'long_scores': part.long_context.to_numpy(), 'rescue_scores': part.rescue_long_context.to_numpy(),
                       'source_start': a, 'block_id': str(i)})
    proposed = fixed_choice(selected['earlier_selected']); earlier_rows = bounds[2] - origin
    earlier_cal = cal.iloc[:earlier_rows].copy()
    earlier_cal['candidate'] = np.concatenate([delayed.scalar_prediction(b['reference'], b['long_scores'], b['rescue_scores'], proposed)[0] for b in blocks[:2]])
    delayed._calibration(checks, name + ':earlier_only', earlier_cal, prior_cal.iloc[:earlier_rows],
                         parent_cal.iloc[:earlier_rows], bounds[:3], selected['earlier_selected'], comparison, stats)
    certificate, veto, accepted, reasons = independent_certificate(blocks, proposed, stats)
    checks.tree(name + ':independent_later_certificate', certificate, selected['certification'])
    checks.tree(name + ':all_four_boundary_veto', veto, selected['global_veto'])
    checks.tree(name + ':certificate_acceptance', accepted, selected['certification_passed'])
    checks.tree(name + ':certificate_rejection_reasons', reasons, selected['certification_rejection_reasons'])
    reference_choice = {'decision': 'reference', 'low_threshold': None, 'high_threshold': None, 'policy': 'instant',
                        'confirmation_samples': 0, 'cadence_seconds': 60.0, 'max_confirmation_seconds': 120.0,
                        'confirmation_delay_seconds': 0.0}
    final = proposed if accepted else reference_choice
    checks.tree(name + ':single_choice_or_full_reference_fallback', fixed_choice(selected), final)
    checks.tree(name + ':final_choice_snapshot', selected['final_selected'], final)
    checks.tree(name + ':earlier_block_ids', selected['selection_blocks'], ['0', '1'])
    checks.tree(name + ':later_block_ids', selected['certification_blocks'], ['2', '3'])
    checks.require(name + ':one_certification_attempt', selected['certification_attempts'] == 1)
    for column in ('sample_index', 'label', 'baseline', 'reference', 'long_context', 'guarded_long_context'):
        checks.array(name + ':same_parent_calibration:' + column, cal[column], parent_cal[column], floating=column.endswith('context'))
    gate, rescue = delayed.independent_masks(prior_cal[['level', 'jump', 'sustained']], cal.long_context)
    checks.array(name + ':calibration_gate', gate, cal.guarded_long_context, floating=True)
    checks.array(name + ':calibration_rescue', rescue, cal.rescue_long_context, floating=True)
    outputs = [delayed.scalar_prediction(b['reference'], b['long_scores'], b['rescue_scores'], final)[0] for b in blocks]
    checks.array(name + ':all_four_final_scalar_outputs', np.concatenate(outputs), cal.candidate)
    assessed = assessment(blocks, outputs, stats)
    checks.require(name + ':final_calibration_constraints', assessed['passed'])
    checks.tree(name + ':final_calibration_stats', stats(cal.label.to_numpy(np.int8), cal.candidate.to_numpy(np.int8), 60), selected['calibration_metrics'])
    for i, (b, p) in enumerate(zip(blocks, outputs)):
        checks.tree(name + f':final_calibration_block:{i}', stats(b['labels'], p, 60), selected['calibration_block_metrics'][i])
    checks.tree(name + ':paired_calibration_delays', assessed['scopes'][0]['paired_extra_delays'], selected['calibration_paired_delays'])


def _trial_selection(checks, name, trials, selected):
    earlier = trials[trials.stage == 'earlier_selection']
    later = trials[trials.stage == 'later_certification_and_global_veto']
    checks.require(name + ':exactly_one_later_veto_not_search', len(later) == 1 and len(trials) == len(earlier) + 1
                   and len(earlier) == selected['selection_trial_count'] and len(trials) == selected['trial_count'])
    delayed._trial_selection(checks, name + ':earlier_only', earlier, selected['earlier_selected'])
    checks.tree(name + ':later_trial_is_fixed_proposal',
                {k: (None if pd.isna(later.iloc[0][k]) else later.iloc[0][k]) for k in ('low_threshold', 'high_threshold', 'policy')},
                {k: selected['earlier_selected'][k] for k in ('low_threshold', 'high_threshold', 'policy')})


def _audit_case(*args, **kwargs):
    # New function globals are local to this call; frozen module globals and
    # files remain untouched. Only attempt-specific hooks differ.
    namespace = {**delayed._audit_case.__globals__, 'VERSION': VERSION,
                 '_calibration': _calibration, '_trial_selection': _trial_selection,
                 'fitted_state_digest': fitted_state_digest}
    function = FunctionType(delayed._audit_case.__code__, namespace, delayed._audit_case.__name__)
    return function(*args, **kwargs)


def lineage_supplement(output):
    """Supplement run03 state identity without altering its completed audit."""
    import joblib
    for name in ('gecco_v2', 'gecco_v5', 'gecco_v6'):
        sys.path.insert(0, str(ROOT / 'ml' / name))
    out = Path(output).resolve(); plan = old.read_json(out / 'plan.json')
    previous = old.read_json(out / 'audit.json')
    if previous.get('passed') is not True or previous.get('complete_replayed_cases') != 19:
        raise ValueError('Completed passing replay required')
    checks = old.Checks(); values = {}
    for name in old.EXPECTED_NAMES:
        folder = out / name; frozen = old.read_json(folder / 'freeze.json')
        parent = old.inside(ROOT, frozen['parent_folder']); parent_freeze = old.read_json(parent / 'freeze.json')
        checks.require(name + ':bundle_sha', old.sha(folder / 'bundle.joblib') == frozen['bundle_sha256'])
        checks.require(name + ':parent_sha', old.sha(parent / 'bundle.joblib') == frozen['parent_sha256']['bundle.joblib'] == parent_freeze['bundle_sha256'])
        a, b = joblib.load(folder / 'bundle.joblib'), joblib.load(parent / 'bundle.joblib')
        for key in ('long_model', 'reference_bundle'):
            before, after = fitted_state_digest(b[key]), fitted_state_digest(a[key])
            checks.require(name + ':' + key, before == after); values[name + '/' + key] = after
    report = {'passed': all(c['passed'] for c in checks.records), 'cases': 19,
              'original_audit_sha256': old.sha(out / 'audit.json'), 'supplement_auditor_sha256': old.sha(__file__),
              'original_replay_preserved': True, 'source_rows_read': 0, 'checks': checks.records, 'fitted_state_sha256': values,
              'correction': 'Earlier state fingerprint lacked explicit nested-dictionary boundaries. This length-delimited supplement verifies all19 actual model pairs, retaining every named tree field and excluding only alignment padding. Earlier full-row runtime replay and all performance failures remain unchanged.'}
    (out / 'model_lineage_supplement.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def fitted_state_digest(value):
    """Length-delimited semantic fitted state; excludes only undefined record padding.

    sklearn Tree node records contain alignment padding that can change on
    unpickle/re-pickle although every named model field remains identical.
    Each named field is hashed separately; no fitted feature, threshold, child,
    value, missing-direction field, or estimator attribute is omitted.
    Executed only on already SHA-verified trusted local fitted objects.
    """
    digest = hashlib.sha256()
    def write(payload):
        digest.update(len(payload).to_bytes(8, 'big')); digest.update(payload)
    def add(item):
        if isinstance(item, np.generic):
            add(item.item()); return
        if item is None or isinstance(item, (str, bool, int, float)):
            write((type(item).__name__ + ':' + repr(item)).encode()); return
        if isinstance(item, bytes):
            write(b'bytes:'); write(item); return
        if isinstance(item, np.ndarray):
            write(('array:' + str(item.shape) + ':' + str(item.dtype)).encode())
            if item.dtype.names:
                for name in item.dtype.names:
                    add(name); add(item[name])
            elif item.dtype.hasobject:
                for part in item.flat: add(part)
            else:
                write(np.ascontiguousarray(item).tobytes())
            return
        if isinstance(item, dict):
            write(('dict:' + str(len(item))).encode())
            for key in sorted(item, key=lambda key: (type(key).__name__, repr(key))): add(key); add(item[key])
            return
        if isinstance(item, (tuple, list)):
            write((type(item).__name__ + ':' + str(len(item))).encode())
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


def audit_directory(output, *, workspace_root=None):
    out = Path(output).resolve(); root = Path(workspace_root).resolve() if workspace_root else ROOT
    plan, completed = old.read_json(out / 'plan.json'), old.read_json(out / 'results.json')
    if (plan.get('attempt') != ATTEMPT or plan.get('expected_cases') != 19
            or completed.get('complete_cases') != 19 or completed.get('expected_cases') != 19
            or completed.get('all_prespecified_cases_complete') is not True
            or [p.get('case') for p in completed.get('periods', [])] != old.EXPECTED_NAMES
            or not completed.get('completed_at_utc') or (out / 'failed_case.json').exists()):
        raise ValueError('All 19 run04 cases must be complete before any source/bundle access or audit write')
    checks, hashes = old.Checks(), {}
    report = {'audit_version': 'v7_certified_full_sensor_replay_v1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'audit_script_sha256': old.sha(__file__), 'reused_audit_helper_sha256': old.sha(old.__file__),
              'passed': False, 'development_only': True, 'fresh_validation': False, 'model_refit': False,
              'v7_streaming_tested': False, 'absolute_float_tolerance': old.ATOL,
              'checks': checks.records, 'hashes': hashes, 'replayed_rows': 0, 'complete_replayed_cases': 0,
              'attempt': ATTEMPT, 'inference_module': 'ml.gecco_v7.runtime_certified',
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
        checks.require('frozen_delayed_replay_helper', old.sha(delayed.__file__) == DELAYED_HELPER_SHA)
        checks.require('pinned_certification_algorithm', old.sha(root / 'ml/gecco_v7/calibration_certified.py') == CERTIFIED_CAL_SHA)
        report['reused_delayed_helper_sha256'] = DELAYED_HELPER_SHA
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
        runtime_module = importlib.import_module('ml.gecco_v7.runtime_certified')
        checks.require('runtime_resolved_to_verified_code', Path(runtime_module.__file__).resolve() == root / 'ml/gecco_v7/runtime_certified.py')
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


def self_test():
    """Synthetic fixtures only; no publisher/source or real bundle IO."""
    import unittest
    from unittest.mock import patch
    from ml.gecco_v6.unknown_label_metrics import comparison, stats
    from ml.gecco_v7 import calibration_certified as certified
    from ml.gecco_v7.test_calibration_delayed import confirmation_fixture as two_block_fixture

    def confirmation_fixture():
        first = two_block_fixture(); blocks = first + deepcopy(first)
        start = 0
        for i, block in enumerate(blocks):
            block['source_start'] = start; block['block_id'] = str(i)
            start += len(block['labels'])
        return blocks

    class Tests(unittest.TestCase):
        def test_dictionary_boundaries_are_unambiguous(self):
            self.assertNotEqual(fitted_state_digest({'a': {'b': 1}, 'c': 2}),
                                fitted_state_digest({'a': {'b': 1, 'c': 2}}))
            self.assertNotEqual(fitted_state_digest(['a', 'bc']), fitted_state_digest(['ab', 'c']))

        def test_padding_is_ignored_but_named_fields_are_preserved(self):
            dtype = np.dtype({'names': ['child', 'threshold'], 'formats': ['i4', 'f8'], 'offsets': [0, 8], 'itemsize': 24})
            a = np.zeros(2, dtype); b = a.copy()
            b.view(np.uint8).reshape(2, 24)[:, 4:8] = 123
            self.assertEqual(fitted_state_digest(a), fitted_state_digest(b))
            b['threshold'][0] = .5
            self.assertNotEqual(fitted_state_digest(a), fitted_state_digest(b))

        def test_certification_and_boundary_veto_are_recomputed(self):
            blocks = confirmation_fixture(); selected, trials = certified.calibrate(blocks)
            normalized = certified.delayed._validated_rescue_blocks(blocks, 60)
            certificate, veto, accepted, reasons = independent_certificate(normalized, fixed_choice(selected['earlier_selected']), stats)
            checks = old.Checks()
            checks.tree('certificate', certificate, selected['certification'])
            checks.tree('veto', veto, selected['global_veto'])
            checks.tree('reasons', reasons, selected['certification_rejection_reasons'])
            self.assertEqual(accepted, selected['certification_passed'])
            self.assertTrue(all(c['passed'] for c in checks.records), checks.records)

        def test_later_label_mutation_cannot_change_earlier_choice(self):
            blocks = confirmation_fixture(); first = certified.calibrate(blocks)[0]
            changed = deepcopy(blocks)
            for b in changed[2:]: b['labels'][:] = -1
            original_calibrate = certified.delayed.calibrate
            seen = []
            def spy(supplied, **kwargs):
                seen.append(supplied)
                self.assertEqual(len(supplied), 2)
                for actual, expected in zip(supplied, blocks[:2]):
                    np.testing.assert_array_equal(actual['labels'], expected['labels'])
                return original_calibrate(supplied, **kwargs)
            with patch.object(certified.delayed, 'calibrate', side_effect=spy):
                second = certified.calibrate(changed)[0]
            self.assertEqual(len(seen), 1)
            self.assertEqual(first['earlier_selected'], second['earlier_selected'])
            self.assertEqual(second['decision'], 'reference')

        def test_full_calibration_hook_with_synthetic_staged_trials(self):
            blocks = confirmation_fixture(); selected, trials = certified.calibrate(blocks)
            normalized = certified.delayed._validated_rescue_blocks(blocks, 60)
            frames = []; bounds = [normalized[0]['source_start']]
            for b in normalized:
                start = b['source_start']; n = len(b['labels'])
                frames.append(pd.DataFrame({'sample_index': np.arange(start, start+n), 'label': b['labels'],
                    'baseline': b['reference'], 'reference': b['reference'], 'long_context': b['long_scores'],
                    'guarded_long_context': b['long_scores'], 'rescue_long_context': np.nan,
                    'candidate': certified.predict(b['reference'], b['long_scores'], selected, b['rescue_scores'])}))
                bounds.append(start+n)
            table = pd.concat(frames, ignore_index=True); checks = old.Checks()
            _calibration(checks, 'synthetic', table, table.assign(level=.2, jump=.3, sustained=.4), table,
                         bounds, selected, comparison, stats)
            _trial_selection(checks, 'synthetic', pd.DataFrame(trials), selected)
            self.assertTrue(all(c['passed'] for c in checks.records), checks.records)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    return result.wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--lineage-supplement', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        return 0 if self_test() else 1
    if args.lineage_supplement:
        report = lineage_supplement(args.lineage_supplement)
        print(json.dumps({'passed': report['passed'], 'cases': report['cases'], 'source_rows_read': 0}))
        return 0 if report['passed'] else 1
    if not args.output: parser.error('--output, --lineage-supplement, or --self-test required')
    report = audit_directory(args.output)
    print(json.dumps({key: report[key] for key in ('passed', 'failed_checks', 'total_numeric_checks', 'replayed_rows', 'complete_replayed_cases')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

