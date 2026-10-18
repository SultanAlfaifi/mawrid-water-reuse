"""Independent V12 full sensor replay and frozen original-IF evidence audit.

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
from copy import copy
import hashlib

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from ml.gecco_v8_audits import replay as v8
from ml.gecco_v9_audits import replay as v9
from ml.gecco_v10_audits import replay as v10
from ml.gecco_v7_audits import replay as old
from ml.gecco_v7_audits import replay_delayed as delayed
from ml.gecco_v7_audits import replay_certified as certified
from ml.gecco_v7_audits.replay import (sha, read_json, inside, Checks, ATOL, EXPECTED_NAMES,
                                      expected_geometry, _source_frames, GAP)
fixed_choice, independent_certificate, assessment = certified.fixed_choice, certified.independent_certificate, certified.assessment
scalar_prediction, independent_masks, comparisons = v10.scalar_prediction, delayed.independent_masks, delayed.comparisons
recompute_comparisons = comparisons
independent_summary = delayed.summary
ATTEMPT = 'v12_run01_if_raw_score_feature_hgb'
VERSION = 'v12_if_evidence_hgb_pulse_certified_120s'
V9_AUDITOR_SHA = 'abaf8c04b6daa55d2698ee5e43c8e7b6e4b482e132cddeab70324052706d942c'
V10_AUDITOR_SHA = 'c760ebe7c2c794090ba199461f773f747d1ba70ef58df06b2c76800d0d47b4e2'
V10_CALIBRATION_SHA = 'dd92671cc74d2a623f0f9f9d58e989cdcfd0056ae0080750b290989609c016ad'
IF_NAMES = ['original_if_raw_anomaly_score', 'original_if_score_observed']
REFERENCE_FILES = ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz', 'predictions.csv.gz')
V8_AUDITOR_SHA = 'f1a42156a2cb19061df46b282902ccc6b569021e7e625025e860051645606680'
CERTIFIED_AUDITOR_SHA = '71140ad73a862da069471509a84a4400d7e9d0954a3a6ee9ab27d78fb75dace6'
DELAYED_AUDITOR_SHA = 'e71483016cbd0a5ffc18f25ede169ed9d61cecbde16ca3a322fa73c34ef52d5f'
ORIGINAL_AUDITOR_SHA = 'aef512fb2edd5fbaa168c72ca63808abf0fd3a6677b756a82bd9a5084f90ac85'


reference_oracle, weight_oracle, audit_training = v9.reference_oracle, v9.weight_oracle, v9.audit_training
conditional_oracle, conditional_feature_oracle = v9.conditional_oracle, v9.conditional_feature_oracle
check_added_features, audit_conditional_training = v9.check_added_features, v9.audit_conditional_training
_certified_calibration, _trial_selection = v10._calibration, v10._trial_selection


def baseline_input_oracle(frame, channels):
    """Reconstruct baseline15 independently, retaining full-prefix numerics.

    pandas rolling kernels are deliberately shared numerical infrastructure:
    re-summing each window is not equivalent at IF tree boundaries. No production
    feature helper, annotation, threshold or detector policy is called here.
    """
    x = frame.loc[:, channels].astype(float).replace([np.inf, -np.inf], np.nan)
    groups = [x.to_numpy(), x.diff().abs().to_numpy(),
              (x - x.rolling(15, min_periods=15).mean()).to_numpy(),
              x.rolling(15, min_periods=15).std(ddof=0).to_numpy()]
    matrix = np.concatenate(groups, axis=1)
    valid = x.notna().all(axis=1).to_numpy()
    cumulative = np.r_[0, np.cumsum(valid, dtype=np.int64)]
    eligible = np.zeros(len(x), bool)
    if len(x) >= 15:
        eligible[14:] = cumulative[15:] - cumulative[:-15] == 15
    eligible &= np.isfinite(matrix).all(axis=1)
    suffixes = ('value', 'abs_change_1m', 'residual_mean_15m', 'std_15m')
    names = [f'{channel}__{suffix}' for suffix in suffixes for channel in channels]
    return matrix, eligible, names


def baseline_feature_oracle(frame, channels, estimator):
    matrix, eligible, names = baseline_input_oracle(frame, channels)
    raw = np.full(len(frame), np.nan, float)
    if estimator is not None and eligible.any():
        values = -np.asarray(estimator.score_samples(matrix[eligible]), float)
        if values.shape != (int(eligible.sum()),):
            raise ValueError('Frozen IF must return exactly one score per eligible row')
        raw[eligible] = values
    with np.errstate(over='ignore', invalid='ignore'):
        represented = raw.astype(np.float32)
    observed = np.isfinite(raw) & np.isfinite(represented)
    block = np.zeros((len(frame), 2), np.float32)
    block[observed, 0] = represented[observed]
    block[observed, 1] = 1
    return raw, block, eligible, names


def baseline_fit_mask_oracle(frame, labels, channels):
    """Original IF fits complete windows of exactly15 known-normal rows."""
    y = old.ternary(labels, 'original IF training labels')
    if len(y) != len(frame): raise ValueError('Aligned original IF training labels required')
    _, eligible, _ = baseline_input_oracle(frame, channels)
    mask = np.zeros(len(y), bool)
    # Explicit window labels preserve unknowns and original adjacency.
    for i in range(14, len(y)):
        mask[i] = bool(eligible[i] and np.all(y[i-14:i+1] == 0))
    return mask


def audit_if_frame(checks, name, model, frame):
    before = certified.fitted_state_digest(model.baseline_estimator_)
    raw, block, eligible, names = baseline_feature_oracle(frame, model.channels, model.baseline_estimator_)
    checks.tree(name + ':original_if_input_order', model.expected_baseline_feature_names_, names)
    checks.array(name + ':independent_full_prefix_if_raw', model.baseline_raw_scores(frame), raw, floating=True)
    actual = model.baseline_features(frame)
    checks.require(name + ':if_block_float32_shape', actual.dtype == np.float32 and actual.shape == block.shape)
    checks.array(name + ':independent_if_feature_block', actual, block)
    checks.array(name + ':independent_if_observed_helper', model.baseline_observed(frame), block[:, 1] == 1)
    checks.require(name + ':if_scoring_did_not_mutate_estimator',
                   before == certified.fitted_state_digest(model.baseline_estimator_))
    return {'rows': len(frame), 'finite_15row_windows': int(eligible.sum()),
            'observed_if_rows': int(block[:, 1].sum()), 'fitted_estimator_digest': before}


def audit_conditional_frame(checks, name, model, frame, oracle, *, check_original=True):
    """Check unchanged V9 prefix in bounded chunks; IF separately full-prefix.

    Chunk calls check the actual append wiring under that same local input.
    They do NOT assert a cropped IF score equals full-prefix rolling numerics.
    """
    from ml.gecco_v9.conditional import ConditionalResidualHGBScorer
    view = copy(model)
    view.feature_names_ = list(model.v9_feature_names_)
    # Avoid virtual dispatch back to V12 for the existing V9 prefix checker.
    view.features = lambda x: ConditionalResidualHGBScorer.features(view, x)
    result = v9.audit_conditional_frame(checks, name, view, frame, oracle, check_original=check_original)
    audit_if_frame(checks, name, model, frame)
    if check_original:
        for start in range(0, len(frame), 8192):
            end = min(start + 8192, len(frame)); origin = max(0, start - 1440)
            history = frame.iloc[origin:end].loc[:, model.channels]; offset = start - origin
            original, availability = ConditionalResidualHGBScorer.features(view, history)
            actual, actual_availability = model.features(history)
            _, expected_if, _, _ = baseline_feature_oracle(history, model.channels, model.baseline_estimator_)
            checks.require(name + ':exact_v9_plus_two_width:' + str(start),
                           actual.shape == (len(history), len(model.v9_feature_names_) + 2))
            checks.array(name + ':entire_v9_prefix_unchanged:' + str(start),
                         actual[offset:, :-2], original[offset:])
            checks.array(name + ':v9_availability_unchanged:' + str(start),
                         actual_availability[offset:], availability[offset:])
            checks.array(name + ':appended_if_under_same_input_context:' + str(start),
                         actual[offset:, -2:], expected_if[offset:])
    return result


def audit_if_lineage(checks, name, model, bundle, training, labels, prior_folder, hashes):
    import joblib
    from sklearn.ensemble import IsolationForest
    # The caller already verified freeze, prior artifact hash and source bounds.
    original = joblib.load(prior_folder / 'bundle.joblib')
    original_detector = original['prior_bundle']['model']
    estimator = original_detector.baseline_
    ancestor_digest = certified.fitted_state_digest(estimator)
    attached_digest = certified.fitted_state_digest(model.baseline_estimator_)
    checks.require(name + ':attached_if_is_exact_prior_fitted_estimator', ancestor_digest == attached_digest)
    checks.require(name + ':entire_v6_reference_bundle_unchanged',
                   certified.fitted_state_digest(original) == certified.fitted_state_digest(bundle['reference_bundle']))
    checks.require(name + ':only_direct_original_if_estimator_stored',
                   model.baseline_estimator_ is None or type(model.baseline_estimator_) is IsolationForest)
    checks.require(name + ':if_attachment_hash_unchanged',
                   attached_digest == model.baseline_state_hash_at_attachment_)
    fitmask = baseline_fit_mask_oracle(training, labels, model.channels)
    count = int(fitmask.sum())
    checks.require(name + ':original_if_known_normal_fit_population', original_detector.baseline_fit_rows_ == count)
    checks.require(name + ':original_if_fit_support_threshold', (estimator is not None) == (count >= 256))
    checks.require(name + ':original_if_train_boundary', original['max_fit_index'] == len(training) - 1)
    if estimator is not None:
        expected = {'n_estimators': 200, 'max_samples': 256, 'contamination': 'auto',
                    'random_state': 20261016, 'n_jobs': 1}
        checks.tree(name + ':unchanged_original_if_hyperparameters',
                    {key: estimator.get_params()[key] for key in expected}, expected)
        checks.require(name + ':original_if_width', estimator.n_features_in_ == 4 * len(model.channels))
    training_features = audit_if_frame(checks, name + ':training', model, training)
    hashes[name + '/semantic_original_if'] = ancestor_digest
    return {**training_features, 'original_known_normal_training_windows': count,
            'prior_and_attached_fitted_states_identical': ancestor_digest == attached_digest,
            'representation_is_in_sample_not_cross_fitted': True,
            'original_if_refitted_by_audit': False,
            'fit_population_mask_sha256': hashlib.sha256(fitmask.tobytes()).hexdigest()}


def audit_v8_event_ids(root, checks, hashes, by_source, periods, out, stats):
    """Additional exact-ID diagnostic; it does not replace original gates."""
    base = root / 'output/ml/gecco-v8-development/run_01'
    audit = read_json(base / 'audit.json')
    audit_hash = sha(base / 'audit.json')
    checks.require('v8_comparison_uses_pinned_passed_full_audit',
        audit_hash == '2d6475045b5c9323a2c13e950587793404419b5f1cda211ec4d676dc9f2456c1'
        and audit['passed'] is True and audit['complete_replayed_cases'] == 19)
    hashes['v8/audit.json'] = audit_hash
    result = {}
    for period in periods:
        name = period['case']; path = base / name / 'predictions.csv.gz'
        digest = sha(path)
        checks.require(name + ':v8_predictions_match_passed_audit', digest == audit['hashes'][name + '/predictions.csv.gz'])
        hashes['v8/' + name + '/predictions.csv.gz'] = digest
        prior = pd.read_csv(path, float_precision='round_trip')
        current = pd.read_csv(out / name / 'predictions.csv.gz', float_precision='round_trip')
        checks.array(name + ':v8_comparison_original_axis', current.sample_index, prior.sample_index)
        checks.array(name + ':v8_comparison_same_labels', current.label, prior.label)
        y = current.label.to_numpy(np.int8)
        before = stats(y, prior.candidate.to_numpy(np.int8), 60)
        after = stats(y, current.candidate.to_numpy(np.int8), 60)
        b = dict(zip(before['confirmed_event_ids'], before['confirmed_times']))
        a = dict(zip(after['confirmed_event_ids'], after['confirmed_times']))
        result[name] = {'v8_confirmed_event_ids': sorted(b), 'v12_confirmed_event_ids': sorted(a),
            'lost_v8_event_ids': sorted(set(b) - set(a)), 'gained_over_v8_event_ids': sorted(set(a) - set(b)),
            'paired_extra_delays_seconds': [{'event_id': i, 'seconds': float((a[i]-b[i])*60)} for i in sorted(set(a) & set(b))],
            'all_v8_event_ids_retained': not (set(b) - set(a)),
            'diagnostic_only_no_gate_replacement': True}
    return result


def method_spec(plan):
    if plan.get('attempt') != ATTEMPT: raise ValueError('Exact reviewed V12 attempt required')
    return {'runtime': 'ml.gecco_v12.runtime', 'bundle_version': VERSION,
            'model_class': 'BaselineEvidenceHGBScorer', 'guarded_score': True,
            'extra_code': []}


def verify_reference_manifest(plan, checks):
    """Metadata-only link from the upfront19-case inventory to input hashes.

    Actual bytes are subsequently hashed by the pinned provenance verifier,
    before source rows or executable bundles are opened. No source IO here.
    """
    checks.require('upfront_exact_19_reference_case_order', plan.get('case_order') == EXPECTED_NAMES)
    records = plan.get('reference_sha256', {})
    checks.require('upfront_exact_19_reference_inventory', isinstance(records, dict)
                   and set(records) == set(EXPECTED_NAMES))
    for index, name in enumerate(EXPECTED_NAMES):
        record = records[name]
        parent = ('output/ml/gecco-v6-development/run_04' if index < 13
                  else 'output/ml/gecco-v6-waterhub-first-use')
        folder = parent + '/' + name
        checks.require(name + ':upfront_reference_record_schema', isinstance(record, dict)
                       and set(record) == {'folder', 'files'} and record['folder'] == folder
                       and isinstance(record['files'], dict) and set(record['files']) == set(REFERENCE_FILES))
        for filename in REFERENCE_FILES:
            digest = record['files'][filename]
            checks.require(name + ':upfront_reference_digest:' + filename,
                           isinstance(digest, str) and len(digest) == 64
                           and all(c in '0123456789abcdef' for c in digest))
            checks.require(name + ':upfront_reference_in_input_closure:' + filename,
                           plan.get('input_sha256', {}).get(folder + '/' + filename) == digest)


def _verify_provenance(root, out, plan, checks, hashes):
    for module, pinned in ((v9, V9_AUDITOR_SHA), (v10, V10_AUDITOR_SHA), (v8, V8_AUDITOR_SHA), (old, ORIGINAL_AUDITOR_SHA), (delayed, DELAYED_AUDITOR_SHA), (certified, CERTIFIED_AUDITOR_SHA)):
        checks.require('unchanged_reused_auditor:' + module.__name__, sha(module.__file__) == pinned)
    required = {'ml/gecco_v9/' + name for name in ('conditional.py', 'development.py', 'runtime.py')}
    required |= {'ml/gecco_v12/' + name for name in ('baseline_evidence.py', 'development.py', 'runtime.py')}
    required |= {'ml/gecco_v10/calibration.py'}
    checks.require('unchanged_frozen_v10_policy', sha(root / 'ml/gecco_v10/calibration.py') == V10_CALIBRATION_SHA)
    required |= {'ml/gecco_v8/onset.py'}
    required |= {'ml/gecco_v7/' + name for name in ('calibration_certified.py', 'runtime_delayed.py', 'evidence.py')}
    checks.require('all_v12_method_code_is_frozen', required.issubset(plan['code_sha256']))
    method_spec(plan)
    verify_reference_manifest(plan, checks)
    return old._verify_provenance(root, out, {**plan, 'attempt': 'run02_hgb_guarded'}, checks, hashes)


def _load_runtime(root, plan):
    _, comparison, stats = old._load_runtime(root, {**plan, 'attempt': 'run02_hgb_guarded'})
    module = importlib.import_module('ml.gecco_v12.runtime')
    if Path(module.__file__).resolve() != root / 'ml/gecco_v12/runtime.py':
        raise ValueError('V12 runtime must resolve to verified code')
    return module.predict_frame, comparison, stats


def _audit_case(root, out, spec, source, saved_top, plan_sha, checks, hashes, runtime, comparison, stats, method=None):
    """Reuse immutable full raw replay, then audit new V12 training/IF state and frozen V10 calibration."""
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
    conditional = audit_conditional_training(checks, name, model, source.iloc[:train_end],
                                              source.label.iloc[:train_end].to_numpy(np.int8))
    from ml.gecco_v7.long_context_hgb import HGB_PARAMS
    from ml.gecco_v7.long_context import LongContextEventScorer
    from ml.gecco_v8.onset import OnsetWeightedHGBScorer
    checks.require(name + ':unchanged_onset_fit_and_inference_methods',
                   type(model).fit is OnsetWeightedHGBScorer.fit
                   and type(model).score_components is LongContextEventScorer.score_components)
    if model.model_ is not None:
        checks.tree(name + ':fixed_hgb_parameters', {k: model.model_.get_params()[k] for k in HGB_PARAMS}, HGB_PARAMS)
    prototype = OnsetWeightedHGBScorer(spec['channels'])
    old_contract = prototype.feature_contract_
    new_contract = {k: v for k, v in model.feature_contract_.items() if k not in ('conditional_residuals', 'original_if_evidence')}
    for skip in ('version', 'feature_names', 'feature_count'): old_contract.pop(skip); new_contract.pop(skip)
    checks.tree(name + ':original_features_weights_and_hgb_contract_unchanged', new_contract, old_contract)
    expected_added = [f'{channel}::{key}' for channel in spec['channels'] for key in
                      ('conditional_residual_z', 'absolute_conditional_residual_z', 'conditional_residual_observed')]
    checks.tree(name + ':unchanged_original_feature_order', model.original_feature_names_, prototype.feature_names_)
    checks.tree(name + ':declared_added_feature_order', model.conditional_feature_names_, expected_added)
    checks.tree(name + ':entire_feature_order', model.feature_names_, prototype.feature_names_ + expected_added + IF_NAMES)
    checks.tree(name + ':unchanged_v9_feature_order', model.v9_feature_names_, prototype.feature_names_ + expected_added)
    checks.tree(name + ':exact_two_if_feature_order', model.baseline_feature_names_, IF_NAMES)
    checks.tree(name + ':fixed_ridge_hyperparameters', model.feature_contract_['conditional_residuals']['ridge'],
                {'alpha': 1.0, 'fit_intercept': True, 'solver': 'svd'})
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
    # Check added features on every calibration/test row that the caller exposes
    # after its declared gap. Their missing mask never changes original V8 availability.
    def checked_gap(frame, tag):
        postgap = frame.iloc[GAP:]
        audit_conditional_frame(checks, name + ':' + tag, model, postgap, conditional)
        observed = np.all(conditional_feature_oracle(postgap.loc[:, spec['channels']].to_numpy(float), conditional)[:, 2::3] == 1, axis=1)
        return np.r_[np.zeros(min(GAP, len(frame)), bool), observed]
    if spec['continuous_cal']:
        cal_observed = checked_gap(source.iloc[train_end:test_start], 'continuous_cal_features')
    else:
        cal_observed = np.concatenate([checked_gap(source.iloc[a:b], 'cal_features_' + str(i))
            for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:]))])
    checks.array(name + ':saved_calibration_conditional_coverage', cal.conditional_observed, cal_observed)
    _certified_calibration(checks, name, cal, prior_cal, cal, bounds, bundle['selected'], comparison, stats)
    _trial_selection(checks, name, pd.read_csv(folder / 'calibration_trials.csv.gz', float_precision='round_trip'), bundle['selected'])
    saved = pd.read_csv(folder / 'predictions.csv.gz', float_precision='round_trip'); actual = captured['actual']
    test_observed = checked_gap(source.iloc[spec['test'][0]:spec['test'][1]], 'test_features')
    checks.array(name + ':saved_test_conditional_coverage', saved.conditional_observed, test_observed)
    checks.tree(name + ':test_conditional_coverage_accounting', saved_top['conditional_block_test_coverage'],
                {'current_observed_rows_after_gap': int(test_observed.sum()),
                 'observed_on_reference_available_rows': int((test_observed & (actual.reference_prediction.to_numpy() >= 0)).sum()),
                 'reference_available_rows': int((actual.reference_prediction.to_numpy() >= 0).sum()),
                 'diagnostic_only_not_prediction_availability': True})
    gate, rescue = independent_masks(actual[['level', 'jump', 'sustained']], actual.long_context)
    checks.array(name + ':test_rescue_score_oracle', rescue, saved.rescue_long_context, floating=True)
    checks.array(name + ':runtime_rescue_score_matches_saved', actual.rescue_long_context, saved.rescue_long_context, floating=True)
    predicted, _ = scalar_prediction(actual.reference_prediction.to_numpy(np.int8), actual.long_context, rescue, bundle['selected'])
    checks.array(name + ':independent_full_scalar_alarm_oracle', predicted, actual.prediction)
    period['if_evidence_audit'] = audit_if_lineage(checks, name, model, bundle, source.iloc[:train_end], source.label.iloc[:train_end].to_numpy(np.int8), prior, hashes)
    period['calibration_sensor_rows_replayed'] = len(cal)
    period['onset_weighting_counts'] = {k: weights[k] for k in ('known_onset_events', 'eligible_onset_events', 'eligible_onset_rows')}
    period['conditional_audit'] = {'training_complete_normal_rows': int(conditional['complete_normal_mask'].sum()),
                                 'training_attempted_fit_rows': int(conditional['fit_mask'].sum()),
                                 'supported': conditional['supported'],
                                 'test_observed_rows_after_gap': int(test_observed.sum())}
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
    report = {"audit_version": "v12_frozen_if_evidence_full_raw_sensor_batch_replay_v1", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "audit_script_sha256": sha(__file__), "passed": False, "development_only": True,
              "fresh_validation": False, "v7_streaming_tested": False, "model_refit": False,
              "absolute_float_tolerance": ATOL, "checks": checks.records, "hashes": hashes,
              "independent_conditional_feature_tolerance": "max(1e-12,one float32 ULP); masks exact; all replayed scores/coefficients/scales remain1e-12 absolute",
              "replayed_rows": 0, "complete_replayed_cases": 0,
              "attempt": plan.get("attempt", "run01_extratrees"),
              "limitations": [
                  "PASS verifies the checked artifacts and arithmetic; it is not model success or deployment approval.",
                  "All 19 cases use already-disclosed development sources; no genuinely unused final source is tested.",
                  "WaterHub adaptation evidence is reused and SHA-verified, not regenerated in this audit.",
                  "V12 inference tested here is batch; prefix tests are not a persistent-state streaming implementation.",
                  "Fitted artifacts and declared bounds are checked without retraining; historical absence of hidden access is not provable from artifacts alone.",
                  "Reference statistics use the whole training block. Causal inference is conditional on these frozen training-only references; this is not online re-estimation at each earlier training row.",
                  "V6 unknown-label metrics are reused; V12 onset weights, normal references, conditional ridge coefficients/scales/masks, original and added features, calibration sensor scores, certificate and summary are independently checked.",
                  "Frozen IF scores used by HGB training are in-sample known-normal representations, not cross-fitted independent evidence.",
                  "IF feature values use full supplied-prefix pandas rolling state. Cropped numerical or streaming parity is not claimed.",
                  "The IF input-feature oracle independently reconstructs the four groups using pinned installed pandas numerical kernels, then calls the verified frozen estimator; it does not reimplement isolation trees.",
                  "The ridge-reference oracle independently solves fixed coefficient equations for verification only; no classifier or alarm operating point is refitted.",
                  "Legacy comparison keys ending in v7 denote the current V12 candidate.", "GECCO seconds use nominal acquisition cadence; WaterHub has a verified regular timestamp grid."]}
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
            frozen = read_json(out / spec['name'] / 'freeze.json')
            pinned = plan['reference_sha256'][spec['name']]
            checks.tree(spec['name'] + ':case_reference_folder_matches_upfront_plan',
                        frozen['prior_folder'], pinned['folder'])
            checks.tree(spec['name'] + ':case_reference_hashes_match_upfront_plan',
                        frozen['prior_sha256'], pinned['files'])
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
        report["conditional_audit_by_case"] = {p["case"]: p["conditional_audit"] for p in periods}
        report["if_evidence_audit_by_case"] = {p["case"]: p["if_evidence_audit"] for p in periods}
        report["v8_event_comparison"] = audit_v8_event_ids(root, checks, hashes, by_source, periods, out, stats)
        checks.require("all_expected_test_rows_replayed", report["replayed_rows"] == 449431)
        checks.require("all_expected_calibration_rows_replayed", report["calibration_sensor_rows_replayed"] == 891750)
        report["recomputed_development_gates"] = {key: value["passes_declared_development_gate"] for key, value in summary.items()}
        checks.require("completed_plan_unchanged", sha(out / "plan.json") == hashes["plan.json"])
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
