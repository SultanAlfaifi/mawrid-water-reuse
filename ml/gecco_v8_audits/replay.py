"""Independent V8 development replay and training-weight/reference accounting.

Import has no source IO. Only fully completed, explicitly authorized development
runs may open the already-disclosed sources. No fresh water data or model refit
is part of this audit. The training oracles below use original acquisition rows;
unknown labels never contribute reference values or classifier weights.
"""
from __future__ import annotations

import math
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
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from ml.gecco_v7_audits import replay as old
from ml.gecco_v7_audits import replay_delayed as delayed
from ml.gecco_v7_audits import replay_certified as certified
from ml.gecco_v7_audits.replay import (sha, read_json, inside, Checks, ATOL, EXPECTED_NAMES,
                                      expected_geometry, _source_frames, GAP)
fixed_choice, independent_certificate, assessment = certified.fixed_choice, certified.independent_certificate, certified.assessment
scalar_prediction, independent_masks, comparisons = delayed.scalar_prediction, delayed.independent_masks, delayed.comparisons
recompute_comparisons = comparisons
independent_summary = delayed.summary
ATTEMPT = 'v8_run01_onset_weighted_hgb_certified'
VERSION = 'v8_onset_hgb_temporally_certified_120s'
CERTIFIED_AUDITOR_SHA = '71140ad73a862da069471509a84a4400d7e9d0954a3a6ee9ab27d78fb75dace6'
DELAYED_AUDITOR_SHA = 'e71483016cbd0a5ffc18f25ede169ed9d61cecbde16ca3a322fa73c34ef52d5f'
ORIGINAL_AUDITOR_SHA = 'aef512fb2edd5fbaa168c72ca63808abf0fd3a6677b756a82bd9a5084f90ac85'


def reference_oracle(values, labels):
    """Independent direct normal populations; no fitted class or feature call."""
    x = np.asarray(values, float); y = old.ternary(labels, 'training labels')
    if x.ndim != 2 or len(x) != len(y): raise ValueError('Aligned training matrix required')
    n, channels = x.shape
    result = {key: np.full(channels, np.nan) for key in
              ('normal_median_', 'normal_iqr_', 'noise_floor_', 'level_scale_')}
    result.update({key: np.zeros(channels, int) for key in
                   ('normal_reference_counts_', 'normal_delta_counts_', 'positive_delta_counts_')})
    result['reference_supported_'] = np.zeros(channels, bool)
    for j in range(channels):
        finite = np.isfinite(x[:, j]); normal = finite & (y == 0)
        level = x[normal, j]
        with np.errstate(over='ignore', invalid='ignore'):
            delta = np.abs(np.diff(x[:, j]))
        adjacent = normal[1:] & normal[:-1] & np.isfinite(delta)
        changes = delta[adjacent]
        result['normal_reference_counts_'][j] = len(level)
        result['normal_delta_counts_'][j] = len(changes)
        result['positive_delta_counts_'][j] = int((changes > 0).sum())
        if len(level) < 128 or len(changes) < 64: continue
        with np.errstate(over='ignore', invalid='ignore'):
            center = float(np.median(level)); q = np.quantile(level, [.25, .75])
            spread = float(q[1] - q[0]); epsilon = max(abs(center) * 1e-12, 1e-12)
            noise = max(float(np.quantile(changes, .75)), epsilon)
            scale = max(spread / 1.349, noise)
        if not np.isfinite([center, spread, noise, scale]).all() or scale <= 0: continue
        for key, value in zip(('normal_median_', 'normal_iqr_', 'noise_floor_', 'level_scale_'), (center, spread, noise, scale)):
            result[key][j] = value
        result['reference_supported_'][j] = True
    # Count finite prior samples with an exclusive prefix sum: no future row,
    # current sample, or annotation participates in the history population.
    finite = np.isfinite(x)
    counts = np.vstack([np.zeros((1, channels), int), np.cumsum(finite, axis=0)])
    prior = counts[np.arange(n)] - counts[np.maximum(np.arange(n) - 60, 0)]
    supported = result['reference_supported_']
    available = (finite & supported[None, :] & (prior >= 48)).sum(axis=1) >= math.ceil(.75 * channels)
    available[:min(n, 60)] = False
    result['available'] = available
    return result


def weight_oracle(labels, available):
    """Fixed .5/.125/.125/.25 mass, onset offsets0..2 on the original axis."""
    y = old.ternary(labels, 'training labels'); available = np.asarray(available, bool)
    if available.shape != y.shape: raise ValueError('Availability axis mismatch')
    eligible = available & (y >= 0); negative = eligible & (y == 0); positive = eligible & (y == 1)
    records = []; event_rows = []; onset_rows = []
    i = 0
    while i < len(y):
        if y[i] != 1: i += 1; continue
        start = i
        while i < len(y) and y[i] == 1: i += 1
        end = i; rows = np.flatnonzero(positive[start:end]) + start
        established = start > 0 and y[start - 1] == 0
        bonus = np.flatnonzero(positive[start:min(start + 3, end)]) + start if established else np.array([], int)
        record = {'event_id': len(records) + 1, 'start': start, 'end_exclusive': end,
                  'known_onset': bool(established), 'eligible_rows': rows, 'eligible_onset_rows': bonus}
        records.append(record)
        if len(rows): event_rows.append(rows)
        if len(bonus): onset_rows.append(bonus)
    components = {key: np.zeros(len(y), float) for key in ('normal', 'positive_point', 'event', 'onset')}
    fit_possible = int(negative.sum()) >= 128 and bool(positive.any())
    if fit_possible:
        components['normal'][negative] = .5 / negative.sum()
        components['positive_point'][positive] = .125 / positive.sum()
        event_mass = .125 if onset_rows else .375
        for rows in event_rows: components['event'][rows] = event_mass / (len(event_rows) * len(rows))
        for rows in onset_rows: components['onset'][rows] = .25 / (len(onset_rows) * len(rows))
    weight = sum(components.values())
    return {'eligible': eligible, 'positive': positive, 'negative': negative,
            'components': components, 'normalized': weight, 'sample': weight * eligible.sum(),
            'segments': records, 'eligible_segments': len(event_rows),
            'known_onset_events': sum(r['known_onset'] for r in records),
            'eligible_onset_events': len(onset_rows), 'eligible_onset_rows': sum(len(r) for r in onset_rows),
            'fit_possible': fit_possible, 'onset_bonus_redistributed': not bool(onset_rows)}


def audit_training(checks, name, model, frame, labels):
    """Check actual fitted references and row weights without fitting anything."""
    values = frame.loc[:, model.channels].to_numpy(float)
    refs = reference_oracle(values, labels)
    for key, expected in refs.items():
        if key != 'available':
            checks.array(name + ':training_reference:' + key, getattr(model, key), expected,
                         floating=expected.dtype.kind == 'f')
    sufficient_references = refs['reference_supported_'].sum() >= math.ceil(.75 * len(model.channels))
    eligible = refs['available'] if sufficient_references else np.zeros(len(frame), bool)
    weights = weight_oracle(labels, eligible)
    checks.array(name + ':original_training_eligible_mask', model.training_eligible_mask_, weights['eligible'])
    checks.array(name + ':normalized_training_weights', model.training_normalized_weight_, weights['normalized'], floating=True)
    checks.array(name + ':scaled_training_sample_weights', model.training_sample_weight_, weights['sample'], floating=True)
    checks.array(name + ':unknown_rows_have_zero_weight', model.training_sample_weight_[np.asarray(labels) == -1],
                 np.zeros(np.count_nonzero(np.asarray(labels) == -1)), floating=True)
    expected_status = ('insufficient_normal_reference' if not sufficient_references else
                       'insufficient_normal_examples' if weights['negative'].sum() < 128 else
                       'no_event_training' if not weights['positive'].any() else 'fitted')
    checks.require(name + ':fit_status_from_training_support', model.fit_status_ == expected_status)
    checks.require(name + ':training_axis_preserved', model.training_rows_ == len(frame))
    return weights


def _early_calibration(checks, name, cal, prior_cal, parent_cal, bounds, selected, comparison, stats):
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

def _certified_calibration(checks, name, cal, prior_cal, parent_cal, bounds, selected, comparison, stats):
    origin = bounds[0]; blocks = []
    for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        part = cal.iloc[a-origin:b-origin]
        blocks.append({'labels': part.label.to_numpy(np.int8), 'reference': part.reference.to_numpy(np.int8),
                       'long_scores': part.long_context.to_numpy(), 'rescue_scores': part.rescue_long_context.to_numpy(),
                       'source_start': a, 'block_id': str(i)})
    proposed = fixed_choice(selected['earlier_selected']); earlier_rows = bounds[2] - origin
    earlier_cal = cal.iloc[:earlier_rows].copy()
    earlier_cal['candidate'] = np.concatenate([delayed.scalar_prediction(b['reference'], b['long_scores'], b['rescue_scores'], proposed)[0] for b in blocks[:2]])
    _early_calibration(checks, name + ':earlier_only', earlier_cal, prior_cal.iloc[:earlier_rows],
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


def method_spec(plan):
    if plan.get('attempt') != ATTEMPT: raise ValueError('Exact reviewed V8 attempt required')
    return {'runtime': 'ml.gecco_v8.runtime', 'bundle_version': VERSION,
            'model_class': 'OnsetWeightedHGBScorer', 'guarded_score': True,
            'extra_code': []}


def _verify_provenance(root, out, plan, checks, hashes):
    for module, pinned in ((old, ORIGINAL_AUDITOR_SHA), (delayed, DELAYED_AUDITOR_SHA), (certified, CERTIFIED_AUDITOR_SHA)):
        checks.require('unchanged_reused_auditor:' + module.__name__, sha(module.__file__) == pinned)
    required = {'ml/gecco_v8/' + name for name in ('onset.py', 'development.py', 'runtime.py')}
    required |= {'ml/gecco_v7/' + name for name in ('calibration_certified.py', 'runtime_delayed.py', 'evidence.py')}
    checks.require('all_v8_method_code_is_frozen', required.issubset(plan['code_sha256']))
    method_spec(plan)
    return old._verify_provenance(root, out, {**plan, 'attempt': 'run02_hgb_guarded'}, checks, hashes)


def _load_runtime(root, plan):
    _, comparison, stats = old._load_runtime(root, {**plan, 'attempt': 'run02_hgb_guarded'})
    module = importlib.import_module('ml.gecco_v8.runtime')
    if Path(module.__file__).resolve() != root / 'ml/gecco_v8/runtime.py':
        raise ValueError('V8 runtime must resolve to verified code')
    return module.predict_frame, comparison, stats


def _audit_case(root, out, spec, source, saved_top, plan_sha, checks, hashes, runtime, comparison, stats, method=None):
    """Reuse immutable full raw replay, then audit newly fitted V8 state/calibration."""
    captured = {}
    def capture(bundle, sensors):
        actual = runtime(bundle, sensors)
        if not captured: captured.update(bundle=bundle, actual=actual)
        return actual
    namespace = {**old._audit_case.__globals__, 'recompute_comparisons': comparisons}
    function = FunctionType(old._audit_case.__code__, namespace, old._audit_case.__name__)
    period, rows = function(root, out, spec, source, saved_top, plan_sha, checks, hashes,
                            capture, comparison, stats, method)
    name = spec['name']; folder = out / name; bundle = captured['bundle']; model = bundle['long_model']
    train_end, test_start = spec['train'][1], spec['test'][0]
    weights = audit_training(checks, name, model, source.iloc[:train_end], source.label.iloc[:train_end].to_numpy(np.int8))
    from ml.gecco_v7.long_context_hgb import LongContextHGBScorer, HGB_PARAMS
    from ml.gecco_v7.long_context import LongContextEventScorer
    checks.require(name + ':unchanged_feature_reference_and_inference_methods',
                   type(model).features is LongContextEventScorer.features
                   and type(model)._fit_references is LongContextEventScorer._fit_references
                   and type(model).score_components is LongContextEventScorer.score_components)
    if model.model_ is not None:
        checks.tree(name + ':fixed_hgb_parameters', {k: model.model_.get_params()[k] for k in HGB_PARAMS}, HGB_PARAMS)
    prototype = LongContextHGBScorer(spec['channels'])
    old_contract = prototype.feature_contract_
    new_contract = {k: v for k, v in model.feature_contract_.items() if k != 'onset_weighting'}
    for skip in ('version', 'weighting'): old_contract.pop(skip); new_contract.pop(skip)
    checks.tree(name + ':all_nonweight_feature_contracts_unchanged', new_contract, old_contract)
    expected_known = weights['known_onset_events']
    checks.require(name + ':onset_event_counts', model.known_onset_segments_ == expected_known
                   and model.eligible_onset_segments_ == weights['eligible_onset_events']
                   and model.eligible_onset_rows_ == weights['eligible_onset_rows'])
    checks.require(name + ':eligible_training_population_counts',
                   model.fit_normal_rows_ == int(weights['negative'].sum())
                   and model.fit_positive_rows_ == int(weights['positive'].sum())
                   and model.fit_events_ == weights['eligible_segments'])
    checks.require(name + ':explicit_onset_mass_redistribution',
                   model.onset_mass_redistributed_ == (weights['onset_bonus_redistributed'] if weights['fit_possible'] else False))
    checks.require(name + ':all_original_positive_segments_retained', len(model.onset_weight_audit_) == len(weights['segments']))
    for record, expected in zip(model.onset_weight_audit_, weights['segments']):
        checks.tree(name + ':segment_onset:' + str(expected['event_id']),
                    {k: record[k] for k in ('event_id', 'start', 'end_exclusive', 'known_onset')},
                    {k: expected[k] for k in ('event_id', 'start', 'end_exclusive', 'known_onset')})
        checks.array(name + ':original_onset_offsets:' + str(expected['event_id']),
                     record['eligible_onset_row_indices'], expected['eligible_onset_rows'])
        for key, component in (('normalized_point_weight_mass', 'positive_point'), ('normalized_event_weight_mass', 'event'),
                               ('normalized_onset_weight_mass', 'onset')):
            checks.tree(name + ':segment_mass:' + str(expected['event_id']) + ':' + component,
                        record[key], float(weights['components'][component][expected['eligible_rows']].sum()))
        checks.tree(name + ':total_segment_mass:' + str(expected['event_id']),
                    record['normalized_weight_mass'], float(weights['normalized'][expected['eligible_rows']].sum()))
    cal = pd.read_csv(folder / 'calibration_scores.csv.gz', float_precision='round_trip')
    bounds = spec['calibration_starts'] + [test_start]
    frozen = read_json(folder / 'freeze.json'); prior = inside(root, frozen['prior_folder'])
    prior_cal = pd.read_csv(prior / 'calibration_scores.csv.gz', float_precision='round_trip')
    # Recompute every new long score from actual calibration sensor rows too.
    def score_gap(frame):
        score = model.score_components(frame.iloc[GAP:])['long_context']
        return np.r_[np.full(min(GAP, len(frame)), np.nan), score]
    if spec['continuous_cal']:
        scores = score_gap(source.iloc[train_end:test_start].loc[:, spec['channels']])
    else:
        scores = np.concatenate([score_gap(source.iloc[a:b].loc[:, spec['channels']]) for a, b in zip(bounds[:-1], bounds[1:])])
    checks.array(name + ':actual_calibration_sensor_score_replay', scores, cal.long_context, floating=True)
    _certified_calibration(checks, name, cal, prior_cal, cal, bounds, bundle['selected'], comparison, stats)
    _trial_selection(checks, name, pd.read_csv(folder / 'calibration_trials.csv.gz', float_precision='round_trip'), bundle['selected'])
    saved = pd.read_csv(folder / 'predictions.csv.gz', float_precision='round_trip'); actual = captured['actual']
    gate, rescue = independent_masks(actual[['level', 'jump', 'sustained']], actual.long_context)
    checks.array(name + ':test_rescue_score_oracle', rescue, saved.rescue_long_context, floating=True)
    checks.array(name + ':runtime_rescue_score_matches_saved', actual.rescue_long_context, saved.rescue_long_context, floating=True)
    predicted, _ = scalar_prediction(actual.reference_prediction.to_numpy(np.int8), actual.long_context, rescue, bundle['selected'])
    checks.array(name + ':independent_full_scalar_alarm_oracle', predicted, actual.prediction)
    period['calibration_sensor_rows_replayed'] = len(cal)
    period['onset_weighting_counts'] = {k: weights[k] for k in ('known_onset_events', 'eligible_onset_events', 'eligible_onset_rows')}
    return period, rows


def audit_directory(output, *, workspace_root=None):
    """Only output/audit.json is written, after complete-run metadata exists."""
    out = Path(output).resolve()
    root = Path(workspace_root).resolve() if workspace_root else Path(__file__).resolve().parents[2]
    # Gate actual source/bundle access and any report write on completed scope.
    completed = read_json(out / "results.json")
    plan = read_json(out / "plan.json")
    if (plan.get("scope") != "all" or plan.get("limit_cases") != 19
            or completed.get("complete_cases") != 19 or completed.get("expected_cases") != 19
            or completed.get("all_prespecified_cases_complete") is not True
            or [p.get("case") for p in completed.get("periods", [])] != EXPECTED_NAMES
            or not completed.get("completed_at_utc") or (out / "failed_case.json").exists()):
        raise ValueError("All 19 fixed cases must be complete before audit source access or report write")
    checks, hashes = Checks(), {}
    report = {"audit_version": "v8_onset_full_raw_sensor_batch_replay_v1", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "audit_script_sha256": sha(__file__), "passed": False, "development_only": True,
              "fresh_validation": False, "v7_streaming_tested": False, "model_refit": False,
              "absolute_float_tolerance": ATOL, "checks": checks.records, "hashes": hashes,
              "replayed_rows": 0, "complete_replayed_cases": 0,
              "attempt": plan.get("attempt", "run01_extratrees"),
              "limitations": [
                  "PASS verifies the checked artifacts and arithmetic; it is not model success or deployment approval.",
                  "All 19 cases use already-disclosed development sources; no genuinely unused final source is tested.",
                  "WaterHub adaptation evidence is reused and SHA-verified, not regenerated in this audit.",
                  "V8 inference tested here is batch; prefix tests are not a persistent-state streaming implementation.",
                  "Fitted artifacts and declared bounds are checked without retraining; historical absence of hidden access is not provable from artifacts alone.",
                  "Reference statistics use the whole training block. Causal inference is conditional on these frozen training-only references; this is not online re-estimation at each earlier training row.",
                  "V6 unknown-label metrics are reused; V8 onset weights, normal references, calibration sensor scores, certificate and summary are independently checked.", "Legacy comparison keys ending in v7 denote the current V8 candidate.", "GECCO seconds use nominal acquisition cadence; WaterHub has a verified regular timestamp grid."]}
    try:
        checks.require("all_19_complete_before_source_access", True)
        checks.require("declared_development_scope", plan.get("all_sources_previously_disclosed") is True
                       and plan.get("fresh_validation") is False and completed.get("fresh_validation") is False)
        hashes["plan.json"], hashes["results.json"] = sha(out / "plan.json"), sha(out / "results.json")
        report["reused_source_adaptation_audit"] = _verify_provenance(root, out, plan, checks, hashes)
        method = method_spec(plan)
        report["inference_module"] = method["runtime"]
        runtime, comparison, stats = _load_runtime(root, plan)
        sources, train19, valid19 = _source_frames(root)
        specs = expected_geometry(sources, train19, valid19)
        checks.tree("independent_prespecified_case_order", [spec["name"] for spec in specs], EXPECTED_NAMES)
        checks.require("waterhub_adapted_geometry", len(sources["WaterHub"]) == 480960)
        checks.array("waterhub_regular_minute_grid", np.diff(sources["WaterHub"].index.as_unit("ns").asi8), np.full(480959, 60 * 10**9))
        periods, by_source = [], {}
        for spec, saved in zip(specs, completed["periods"]):
            period, rows = _audit_case(root, out, spec, sources[spec["source"]], saved, hashes["plan.json"],
                                       checks, hashes, runtime, comparison, stats, method)
            periods.append(period)
            by_source.setdefault(spec["source"], []).append(rows)
            report["replayed_rows"] += len(rows)
            report["complete_replayed_cases"] += 1
            print(json.dumps({"audited_case": spec["name"], "rows": len(rows),
                              "cumulative_replayed_rows": report["replayed_rows"]}), flush=True)
            gc.collect()
        measured_sources = {}
        for source, parts in by_source.items():
            whole = pd.concat(parts, ignore_index=True)
            checks.array(source + ":pooled_contiguous_original_axis", np.diff(whole.sample_index), np.ones(len(whole) - 1, dtype=int))
            measured_sources[source] = recompute_comparisons(whole.label.to_numpy(np.int8),
                {column: whole[column].to_numpy(np.int8) for column in ("baseline", "reference", "candidate")}, comparison)
            checks.tree(source + ":source_pool_metrics", measured_sources[source], completed["sources"][source])
        summary = independent_summary(periods, measured_sources)
        checks.tree("independent_top_level_summary_and_all_gates", summary, completed["summary"])
        report["calibration_sensor_rows_replayed"] = sum(p["calibration_sensor_rows_replayed"] for p in periods)
        report["onset_weighting_counts_by_case"] = {p["case"]: p["onset_weighting_counts"] for p in periods}
        report["recomputed_development_gates"] = {key: value["passes_declared_development_gate"] for key, value in summary.items()}
        checks.require("completed_results_unchanged", sha(out / "results.json") == hashes["results.json"])
        for relative, expected in plan["code_sha256"].items():
            checks.require("current_code_unchanged_after_replay:" + relative, sha(inside(root, relative)) == expected)
    except Exception as error:
        report["exception"] = {"type": type(error).__name__, "message": str(error)}
        checks.add("audit_completed_without_exception", False, detail=str(error))
    report["failed_checks"] = sum(not row["passed"] for row in checks.records)
    report["total_check_groups"] = len(checks.records)
    report["total_numeric_checks"] = sum(row["numeric_comparisons"] for row in checks.records)
    report["total_compared_values"] = sum(row["compared_values"] for row in checks.records)
    report["passed"] = report["failed_checks"] == 0 and report["complete_replayed_cases"] == 19
    (out / "audit.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    report = audit_directory(parser.parse_args().output)
    print(json.dumps({key: report[key] for key in ('passed', 'failed_checks', 'total_numeric_checks', 'replayed_rows', 'complete_replayed_cases')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
