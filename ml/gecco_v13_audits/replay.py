"""Independent V13 full sensor replay and known-normal IF-tail weight audit.

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
from ml.gecco_v12_audits import replay as v12
from ml.gecco_v7_audits import replay as old
from ml.gecco_v7_audits import replay_delayed as delayed
from ml.gecco_v7_audits import replay_certified as certified
from ml.gecco_v7_audits.replay import (sha, read_json, inside, Checks, ATOL, EXPECTED_NAMES,
                                      expected_geometry, _source_frames, GAP)
fixed_choice, independent_certificate, assessment = certified.fixed_choice, certified.independent_certificate, certified.assessment
scalar_prediction, independent_masks, comparisons = v10.scalar_prediction, delayed.independent_masks, delayed.comparisons
recompute_comparisons = comparisons
independent_summary = delayed.summary
ATTEMPT = 'v13_run01_train_normal_if_tail_weights'
VERSION = 'v13_if_tail_weighted_hgb_pulse_certified_120s'
V9_AUDITOR_SHA = 'abaf8c04b6daa55d2698ee5e43c8e7b6e4b482e132cddeab70324052706d942c'
V10_AUDITOR_SHA = 'c760ebe7c2c794090ba199461f773f747d1ba70ef58df06b2c76800d0d47b4e2'
V10_CALIBRATION_SHA = 'dd92671cc74d2a623f0f9f9d58e989cdcfd0056ae0080750b290989609c016ad'
V12_AUDITOR_SHA = '5a5e4306d12324313bbde6e927139fd03fe5cfcd4b741961a1a5a5d15dae8de3'
V12_FEATURE_SHA = 'd8dec0bd816905a9b6a8ad05e6cec35fc533d12e3eb211f4f153f06f6c10b856'
IF_NAMES = ['original_if_raw_anomaly_score', 'original_if_score_observed']
REFERENCE_FILES = ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz', 'predictions.csv.gz')
V8_AUDITOR_SHA = 'f1a42156a2cb19061df46b282902ccc6b569021e7e625025e860051645606680'
CERTIFIED_AUDITOR_SHA = '71140ad73a862da069471509a84a4400d7e9d0954a3a6ee9ab27d78fb75dace6'
DELAYED_AUDITOR_SHA = 'e71483016cbd0a5ffc18f25ede169ed9d61cecbde16ca3a322fa73c34ef52d5f'
ORIGINAL_AUDITOR_SHA = 'aef512fb2edd5fbaa168c72ca63808abf0fd3a6677b756a82bd9a5084f90ac85'
HISTORICAL_AUDITOR_SHA = {'v8': V8_AUDITOR_SHA, 'v9': V9_AUDITOR_SHA,
    'v10': V10_AUDITOR_SHA, 'v11': 'f59e1c836a40701b7f89687e1c8f174fd44401bc95dbe86f4f3ac880bba9645e',
    'v12': V12_AUDITOR_SHA}
RESUME_CONTROLLER_SHA = {
    '__init__.py': '8c9517d9ca560fea942ccccf4c1ba1c5811c1fce260ea5598f2b1c24d93630da',
    'resume.py': '22151b984d1eab5c55d458c2fb1e1ab38840a3e6ca16600adeb80b2e0ace8ba0',
    'test_resume.py': '9531d847111f49397b40b0f34f4a06dc9e353364529736dc75db7dc55dcad4d2'}
RESUME_ARTIFACTS = ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz',
    'calibration_trials.csv.gz', 'predictions.csv.gz', 'model_inspection.json', 'results.json')
RESUME_CHECKPOINT_SHA = 'a8cd0fe6915a1a285120c180ff23ead4f12997f02dca5ec00d3a962fc7055c75'


def audit_execution_resume(root, out, plan, completed, checks, hashes):
    """Independent byte/metadata proof of the resource-only12+7 continuation.

    This never imports or executes the controller, decodes source/score CSVs,
    or loads a bundle. The result pins the checkpoint SHA supplied to the
    controller by its operator; this is artifact binding, not a signed log.
    """
    root, out = Path(root).resolve(), Path(out).resolve()
    metadata = completed.get('execution_resume')
    control = out/'execution_resume'
    if metadata is None:
        evidence = ((control/'checkpoint.json').exists()
                    or bool(list(control.glob('case_*.json')))
                    or bool(list(control.glob('resume_*.log')))
                    or (out.parent/'resume-checkpoint-pin.json').exists())
        checks.require('resume:metadata_not_omitted_for_existing_resume_evidence', not evidence)
        return {'present': False, 'operational_resume_checked': False}
    checks.require('resume:metadata_and_directory', isinstance(metadata, dict)
                   and control.is_dir() and not control.is_symlink())

    def bound_file(path, expected, key):
        checks.require('resume:ordinary_file:'+key, path.is_file() and not path.is_symlink())
        actual = sha(path)
        checks.require('resume:bound_sha:'+key, isinstance(expected, str) and actual == expected)
        hashes[key] = actual
        return actual

    checks.require('resume:fixed_checkpoint_location', metadata.get('checkpoint') == 'execution_resume/checkpoint.json')
    checkpoint_path = control/'checkpoint.json'
    checkpoint_sha = bound_file(checkpoint_path, metadata.get('checkpoint_sha256'), 'execution_resume/checkpoint.json')
    checks.require('resume:externally_pinned_checkpoint', checkpoint_sha == RESUME_CHECKPOINT_SHA)
    external_pin_path = out.parent/'resume-checkpoint-pin.json'
    checks.require('resume:ordinary_external_pin', external_pin_path.is_file() and not external_pin_path.is_symlink())
    external_pin = read_json(external_pin_path)
    checks.require('resume:external_pin_metadata', external_pin.get('sha256') == checkpoint_sha
                   and external_pin.get('checkpoint') == str(checkpoint_path.relative_to(root))
                   and external_pin.get('initial_preserved_complete_cases') == 12
                   and external_pin.get('remaining_cases') == 7
                   and external_pin.get('statistical_parameters_changed') is False
                   and external_pin.get('minimum_free_disk_bytes_changed') is False
                   and external_pin.get('original_process_terminal_exit') == 1)
    external_pin_relative = str(external_pin_path.relative_to(root))
    hashes['workspace:'+external_pin_relative] = sha(external_pin_path)
    checkpoint = read_json(checkpoint_path)
    plan_sha = sha(out/'plan.json')
    checks.require('resume:original_plan_binding', checkpoint.get('plan_sha256') == plan_sha
                   and metadata.get('original_plan_sha256') == plan_sha)
    checks.require('resume:fixed_resource_only_scope', metadata.get('operation') == 'resource_only_resume'
                   and checkpoint.get('operation') == 'resource_only_resume' and checkpoint.get('schema_version') == 1
                   and checkpoint.get('root') == str(root) and checkpoint.get('output') == str(out))
    checks.require('resume:unchanged_one_gib_guard', checkpoint.get('original_minimum_free_disk_bytes') == 1024**3
                   and plan.get('resource_execution', {}).get('minimum_free_disk_bytes') == 1024**3)
    checks.require('resume:all19_scope_and_original_acceptance',
        plan.get('attempt') == ATTEMPT and plan.get('case_order') == EXPECTED_NAMES
        and plan.get('scope') == 'all' and plan.get('limit_cases') == 19 and plan.get('expected_cases') == 19
        and checkpoint.get('expected_cases') == 19
        and metadata.get('original_method_and_acceptance_unchanged') is True
        and metadata.get('existing_case_artifacts_unchanged') is True
        and checkpoint.get('statistical_method_changed') is False
        and checkpoint.get('existing_artifacts_will_not_be_overwritten') is True
        and completed.get('maximum_allowed_extra_delay_seconds') == 120
        and completed.get('historical_retention_required') is True
        and completed.get('v8_user_objective_required') is True
        and completed.get('acceptance_evaluation_pending_independent_audit_and_historical_comparison') is True)
    checks.require('resume:qualified_controller_exact', checkpoint.get('controller_sha256') == RESUME_CONTROLLER_SHA
                   and metadata.get('controller_sha256') == RESUME_CONTROLLER_SHA)
    for filename, expected in RESUME_CONTROLLER_SHA.items():
        relative = 'ml/gecco_v13_control/'+filename
        bound_file(root/relative, expected, relative)
    threads = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
    checks.require('resume:original_thread_environment', metadata.get('thread_environment') == threads
                   and checkpoint.get('child_thread_environment') == threads
                   and checkpoint.get('mkl_thread_environment') == 'unset, matching original command')
    checks.require('resume:original_library_versions', checkpoint.get('environment') == plan.get('environment')
                   and metadata.get('environment') == plan.get('environment') and bool(plan.get('environment')))
    checks.require('resume:initial12_and_missing7_exact', checkpoint.get('initial_complete_count') == 12
                   and list(checkpoint.get('initial_completed_cases', {})) == EXPECTED_NAMES[:12]
                   and checkpoint.get('missing_cases') == EXPECTED_NAMES[12:]
                   and metadata.get('initial_preserved_cases') == EXPECTED_NAMES[:12])
    receipt_pins = metadata.get('resumed_case_receipt_sha256', {})
    checks.require('resume:exact_seven_receipt_pins', isinstance(receipt_pins, dict)
                   and list(receipt_pins) == EXPECTED_NAMES[12:])
    expected_receipts = {f'case_{index+1:02d}_{name}.json' for index, name in enumerate(EXPECTED_NAMES) if index >= 12}
    checks.require('resume:no_unexpected_case_receipts',
                   {path.name for path in control.glob('case_*.json')} == expected_receipts)
    log_names = metadata.get('new_resume_logs')
    checks.require('resume:logs_declared', isinstance(log_names, list) and bool(log_names)
                   and len(log_names) == len(set(log_names))
                   and all(isinstance(name, str) and Path(name).name == name
                           and name.startswith('resume_') and name.endswith('.log') for name in log_names))
    for name in log_names:
        path = control/name
        checks.require('resume:ordinary_log:'+name, path.is_file() and not path.is_symlink())
        hashes['execution_resume/'+name] = sha(path)
        with path.open(encoding='utf-8') as stream:
            header = json.loads(stream.readline())
        checks.require('resume:log_header:'+name, header.get('checkpoint_sha256') == checkpoint_sha
                       and header.get('minimum_free_disk_bytes') == 1024**3
                       and header.get('thread_environment') == threads)
    all_hashes, receipt_hashes = {}, {}
    for index, name in enumerate(EXPECTED_NAMES):
        if index < 12:
            expected_files = checkpoint['initial_completed_cases'][name]
        else:
            relative = f'execution_resume/case_{index+1:02d}_{name}.json'
            path = out/relative
            receipt_hashes[name] = bound_file(path, receipt_pins[name], relative)
            receipt = read_json(path)
            checks.require('resume:receipt_provenance:'+name, receipt.get('case') == name
                           and receipt.get('checkpoint_sha256') == checkpoint_sha
                           and receipt.get('plan_sha256') == plan_sha
                           and receipt.get('controller_sha256') == RESUME_CONTROLLER_SHA
                           and receipt.get('child_returncode') == 0
                           and receipt.get('thread_environment') == threads
                           and receipt.get('resume_log') in ['execution_resume/'+item for item in log_names])
            expected_files = receipt.get('artifact_sha256', {})
        folder = out/name
        checks.require('resume:seven_artifacts_exact:'+name, isinstance(expected_files, dict)
                       and set(expected_files) == set(RESUME_ARTIFACTS)
                       and folder.is_dir() and not folder.is_symlink()
                       and {path.name for path in folder.iterdir()} == set(RESUME_ARTIFACTS))
        all_hashes[name] = {filename: bound_file(folder/filename, expected_files[filename], name+'/'+filename)
                           for filename in RESUME_ARTIFACTS}
        freeze, result = read_json(folder/'freeze.json'), read_json(folder/'results.json')
        checks.require('resume:case_identity_and_freeze:'+name,
                       freeze.get('plan_sha256') == plan_sha
                       and freeze.get('bundle_sha256') == all_hashes[name]['bundle.joblib']
                       and result.get('case') == name and result.get('development_only') is True)
    return {'present': True, 'operational_resume_checked': True, 'checkpoint_sha256': checkpoint_sha,
            'external_checkpoint_pin': external_pin_relative,
            'external_checkpoint_pin_sha256': hashes['workspace:'+external_pin_relative],
            'original_plan_sha256': plan_sha, 'controller_sha256': dict(RESUME_CONTROLLER_SHA),
            'initial_completed_cases_preserved': 12, 'resumed_cases_verified': 7,
            'all_case_artifact_hashes_checked': 19*7, 'minimum_free_disk_bytes': 1024**3,
            'original_acceptance_unchanged': True, 'receipt_sha256': receipt_hashes,
            'limitations': ['Artifact proof binds the separately recorded and auditor-pinned checkpoint digest; it is not an externally signed execution log.',
                            'Original external terminal-log preservation is an operator record, not proven by these new resume-log hashes.',
                            'Operational continuity does not imply statistical model acceptance.']}


reference_oracle = v9.reference_oracle
conditional_oracle, conditional_feature_oracle = v9.conditional_oracle, v9.conditional_feature_oracle
check_added_features, audit_conditional_training = v9.check_added_features, v9.audit_conditional_training
_certified_calibration, _trial_selection = v10._calibration, v10._trial_selection


def weight_oracle(labels, available, raw_scores):
    """Reuse pinned positive/onset oracle; independently replace only negatives.

    The q95 population is ALL original training rows with label exactly0 and a
    finite float64 frozen-IF score, including HGB-unavailable warmup rows. The
    factor5 tail affects only eligible known-normal classifier rows. No model
    weight helper, calibration value, test label or float32 IF feature is used.
    """
    y = old.ternary(labels, 'hard-normal training labels')
    raw = np.asarray(raw_scores, dtype=np.float64)
    if raw.shape != y.shape: raise ValueError('Original-axis IF scores required')
    result = v9.weight_oracle(y, available)
    population = (y == 0) & np.isfinite(raw)
    threshold = float(np.quantile(raw[population], .95, method='linear')) if population.any() else None
    tail = (result['negative'] & np.isfinite(raw) & (raw >= threshold)
            if threshold is not None else np.zeros(len(y), bool))
    if result['fit_possible']:
        n = int(result['negative'].sum()); h = int(tail.sum())
        multipliers = 1.0 + 4.0 * tail[result['negative']]
        result['components']['normal'][result['negative']] = .5 * multipliers / (n + 4*h)
        result['normalized'] = sum(result['components'].values())
        result['sample'] = result['normalized'] * int(result['eligible'].sum())
    result.update(raw=raw, quantile_population=population, q95=threshold, tail=tail)
    return result


def audit_training(checks, name, model, frame, labels):
    """Check the new weights and unchanged references without fitting a model."""
    values = frame.loc[:, model.channels].to_numpy(float)
    refs = reference_oracle(values, labels)
    for key, expected in refs.items():
        if key != 'available':
            checks.array(name + ':training_reference:' + key, getattr(model, key), expected,
                         floating=expected.dtype.kind == 'f')
    sufficient = refs['reference_supported_'].sum() >= math.ceil(.75 * len(model.channels))
    available = refs['available'] if sufficient else np.zeros(len(frame), bool)
    raw, _, _, _ = baseline_feature_oracle(frame, model.channels, model.baseline_estimator_)
    weights = weight_oracle(labels, available, raw)
    checks.require(name + ':stored_hard_normal_scores_float64',
                   isinstance(model.hard_normal_raw_scores_, np.ndarray)
                   and model.hard_normal_raw_scores_.dtype == np.dtype('float64'))
    checks.array(name + ':independent_training_raw_if_scores', model.hard_normal_raw_scores_, raw, floating=True)
    checks.array(name + ':all_training_normal_finite_q95_population',
                 model.hard_normal_quantile_mask_, weights['quantile_population'])
    checks.tree(name + ':independent_float64_linear_q95', model.hard_normal_q95_, weights['q95'])
    checks.array(name + ':eligible_known_normal_weight_population',
                 model.hard_normal_eligible_normal_mask_, weights['negative'])
    checks.array(name + ':independent_inclusive_q95_tail', model.hard_normal_tail_mask_, weights['tail'])
    checks.array(name + ':original_training_eligible_mask', model.training_eligible_mask_, weights['eligible'])
    checks.array(name + ':normalized_training_weights', model.training_normalized_weight_, weights['normalized'], floating=True)
    checks.array(name + ':scaled_training_sample_weights', model.training_sample_weight_, weights['sample'], floating=True)
    y = np.asarray(labels)
    old_weights = v9.weight_oracle(y, available)
    checks.array(name + ':all_positive_weights_unchanged',
                 model.training_normalized_weight_[y == 1], old_weights['normalized'][y == 1], floating=True)
    checks.array(name + ':unknown_rows_have_zero_weight', model.training_sample_weight_[y == -1],
                 np.zeros(np.count_nonzero(y == -1)), floating=True)
    expected_status = ('insufficient_normal_reference' if not sufficient else
                       'insufficient_normal_examples' if weights['negative'].sum() < 128 else
                       'no_event_training' if not weights['positive'].any() else 'fitted')
    checks.require(name + ':fit_status_from_training_support', model.fit_status_ == expected_status)
    checks.require(name + ':training_axis_preserved', model.training_rows_ == len(frame))
    quantile_status = ('available' if weights['q95'] is not None else
                       'missing_estimator' if model.baseline_estimator_ is None else 'no_finite_known_normal_scores')
    hard_status = ('not_applied_' + expected_status if expected_status != 'fitted' else
                   'uniform_fallback' if weights['q95'] is None else 'tail_weighted')
    checks.tree(name + ':hard_normal_status', model.hard_normal_status_, hard_status)
    checks.tree(name + ':hard_normal_quantile_status', model.hard_normal_quantile_status_, quantile_status)
    semantic_if = certified.fitted_state_digest(model.baseline_estimator_)
    expected_audit = {
        'status': hard_status, 'quantile_status': quantile_status, 'q95': weights['q95'],
        'quantile': .95, 'quantile_method': 'linear', 'tail_comparison': '>=', 'tail_relative_weight': 5.,
        'training_rows': len(y), 'quantile_population_rows': int(weights['quantile_population'].sum()),
        'quantile_population_hgb_ineligible_rows': int((weights['quantile_population'] & ~weights['eligible']).sum()),
        'eligible_normal_rows': int(weights['negative'].sum()), 'eligible_tail_rows': int(weights['tail'].sum()),
        'eligible_normal_missing_if_rows': int((weights['negative'] & ~np.isfinite(raw)).sum()),
        'normal_weight_mass': float(weights['normalized'][y == 0].sum()),
        'positive_weight_mass': float(weights['normalized'][y == 1].sum()),
        'unknown_weight_mass': 0., 'eligible_tail_weight_mass': float(weights['normalized'][weights['tail']].sum()),
        'quantile_mask_sha256': hashlib.sha256(weights['quantile_population'].tobytes()).hexdigest(),
        'eligible_normal_mask_sha256': hashlib.sha256(weights['negative'].tobytes()).hexdigest(),
        'tail_mask_sha256': hashlib.sha256(weights['tail'].tobytes()).hexdigest(),
        'if_state_before': semantic_if, 'if_state_after': semantic_if, 'if_state_unchanged': True,
        'if_refitted': False, 'in_sample_not_cross_fitted': True,
    }
    checks.tree(name + ':independent_hard_normal_inspection', model.hard_normal_audit_, expected_audit)
    contract = model.feature_contract_.get('hard_normal_weighting', {})
    checks.tree(name + ':fixed_hard_normal_contract', {k: contract.get(k) for k in
        ('quantile', 'quantile_method', 'tail_comparison', 'tail_to_other_relative_weight', 'normal_mass', 'if_fit', 'in_sample_not_cross_fitted')},
        {'quantile': .95, 'quantile_method': 'linear', 'tail_comparison': '>=',
         'tail_to_other_relative_weight': 5., 'normal_mass': .5, 'if_fit': False, 'in_sample_not_cross_fitted': True})
    if weights['fit_possible']:
        checks.tree(name + ':normal_mass_remains_half', float(model.training_normalized_weight_[weights['negative']].sum()), .5)
    weights['hard_normal_summary'] = {
        'quantile': .95, 'quantile_method': 'linear', 'tail_inclusive': True,
        'tail_relative_factor': 5.0, 'q95': weights['q95'],
        'all_training_finite_known_normal_scores': int(weights['quantile_population'].sum()),
        'q95_population_outside_hgb_eligible': int((weights['quantile_population'] & ~weights['eligible']).sum()),
        'eligible_normal_rows': int(weights['negative'].sum()),
        'eligible_tail_rows': int(weights['tail'].sum()),
        'normalized_normal_mass': float(weights['components']['normal'].sum()),
        'all_positive_weights_unchanged': True, 'unknown_weights_zero': True, 'normal_only': True,
        'q95_uses_training_only': True, 'no_classifier_or_if_refit_by_auditor': True,
    }
    return weights


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
    # Avoid virtual dispatch back to V13 for the existing V9 prefix checker.
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


def v8_comparison_record(before, after):
    """Original-period event identity AND false-alarm exposure; no new gate."""
    b = dict(zip(before['confirmed_event_ids'], before['confirmed_times']))
    a = dict(zip(after['confirmed_event_ids'], after['confirmed_times']))
    return {'v8_confirmed_event_ids': sorted(b), 'v13_confirmed_event_ids': sorted(a),
        'lost_v8_event_ids': sorted(set(b) - set(a)), 'gained_over_v8_event_ids': sorted(set(a) - set(b)),
        'paired_extra_delays_seconds': [{'event_id': i, 'seconds': float((a[i]-b[i])*60)} for i in sorted(set(a) & set(b))],
        'all_v8_event_ids_retained': not (set(b) - set(a)),
        'false_alarm_comparison': {
            'v8_false_positive_runs': before['false_positive_runs'],
            'v13_false_positive_runs': after['false_positive_runs'],
            'v8_fp_duration_seconds': before['fp_duration_seconds'],
            'v13_fp_duration_seconds': after['fp_duration_seconds'],
            'v8_normal_observed_seconds': before['normal_observed_seconds'],
            'v13_normal_observed_seconds': after['normal_observed_seconds'],
            'false_runs_nonincreasing': after['false_positive_runs'] <= before['false_positive_runs'],
            'false_duration_nonincreasing': after['fp_duration_seconds'] <= before['fp_duration_seconds'],
        },
        'scope': 'One original test period; event IDs are local to its untouched label axis. Do not sum these intervals as contiguous-source unique events.',
        'diagnostic_only_no_gate_replacement': True}


def audit_v8_event_ids(root, checks, hashes, by_source, periods, out, stats):
    """Additional exact-ID and FP diagnostic; original IF/V6 gates unchanged."""
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
        result[name] = v8_comparison_record(before, after)
    return result


def historical_pair(labels, older, current, comparison):
    """Original-axis pairing; a historical objective does not alter selection."""
    result = comparison(labels, older, current, 60)
    before, after = result['baseline'], result['candidate']
    return {
        'lost_event_ids': list(result['lost_baseline_event_ids']),
        'gained_event_ids': list(result['new_candidate_event_ids']),
        'all_event_ids_retained': not result['lost_baseline_event_ids'],
        'sensor_availability_equal': result['sensor_availability_equal'],
        'paired_extra_delays_seconds': result['paired_extra_delays'],
        'paired_delay_within120': all(d['extra_delay_seconds'] <= 120 for d in result['paired_extra_delays']),
        'before_false_positive_runs': before['false_positive_runs'],
        'after_false_positive_runs': after['false_positive_runs'],
        'before_fp_duration_seconds': before['fp_duration_seconds'],
        'after_fp_duration_seconds': after['fp_duration_seconds'],
        'before_normal_observed_seconds': before['normal_observed_seconds'],
        'after_normal_observed_seconds': after['normal_observed_seconds'],
        'false_runs_nonincreasing': after['false_positive_runs'] <= before['false_positive_runs'],
        'false_duration_nonincreasing': after['fp_duration_seconds'] <= before['fp_duration_seconds'],
    }


def historical_objectives(periods, pools, *, expected_periods=19):
    """Separate predeclared retention and V8 objective; no IF/V6 gate rewrite."""
    retained = {}
    for version in HISTORICAL_AUDITOR_SHA:
        parts = [entry[version] for entry in periods.values()] + [entry[version] for entry in pools.values()]
        retained[version] = bool(parts) and all(part['all_event_ids_retained'] for part in parts)
    v8parts = [entry['v8'] for entry in periods.values()]
    v8pools = [entry['v8'] for entry in pools.values()]
    conditions = {
        'all19_periods_and_source_pools_evaluated': len(periods) == expected_periods and bool(pools),
        'every_period_and_pool_preserves_v8_event_ids': all(p['all_event_ids_retained'] for p in v8parts+v8pools),
        'every_period_and_pool_availability_equal': all(p['sensor_availability_equal'] for p in v8parts+v8pools),
        'every_period_and_pool_extra_delay_within120': all(p['paired_delay_within120'] for p in v8parts+v8pools),
        'every_period_and_pool_fp_runs_nonincreasing': all(p['false_runs_nonincreasing'] for p in v8parts+v8pools),
        'every_period_and_pool_fp_duration_nonincreasing': all(p['false_duration_nonincreasing'] for p in v8parts+v8pools),
        'strictly_fewer_pooled_false_runs': sum(p['after_false_positive_runs'] for p in v8pools) < sum(p['before_false_positive_runs'] for p in v8pools),
        'false_run_reduction_in_at_least_two_periods': sum(p['after_false_positive_runs'] < p['before_false_positive_runs'] for p in v8parts) >= 2,
    }
    return {'historical_event_retention_by_version': retained,
            'all_historical_event_ids_retained': len(periods) == expected_periods and bool(pools) and all(retained.values()),
            'v8_user_objective_checks': conditions, 'passes_v8_user_objective': all(conditions.values()),
            'scope': 'Evaluation comparators only, after all19 cases; no historical test row or label enters fitting or threshold selection. IF/V6 original strong gates remain separate.'}


def audit_historical_comparisons(root, out, plan, checks, hashes, periods, comparison, stats):
    """Recompute all five historical event-ID comparisons and the V8 FP gate."""
    manifest = plan.get('historical_comparison_sha256', {})
    expected_paths = {f'output/ml/gecco-{version}-development/run_01/{filename}'
        for version in HISTORICAL_AUDITOR_SHA for filename in ('plan.json', 'results.json', 'audit.json')}
    checks.require('exact_historical_upfront_inventory', set(manifest) == expected_paths)
    prior_info = {}
    for version, auditor_sha in HISTORICAL_AUDITOR_SHA.items():
        base = root / f'output/ml/gecco-{version}-development/run_01'
        for filename in ('plan.json', 'results.json', 'audit.json'):
            path = base/filename; relative = str(path.relative_to(root)); digest = sha(path)
            checks.require('historical_upfront_hash:' + relative,
                digest == manifest[relative] == plan['input_sha256'][relative])
            hashes['historical/' + version + '/' + filename] = digest
        proof = read_json(base/'audit.json'); result = read_json(base/'results.json')
        checks.require('historical_passed_full_audit:' + version,
            proof.get('passed') is True and proof.get('complete_replayed_cases') == 19
            and proof.get('audit_script_sha256') == auditor_sha)
        for filename in ('plan.json', 'results.json'):
            checks.require('historical_audit_binds:' + version + '/' + filename,
                proof['hashes'].get(filename) == sha(base/filename))
        checks.tree('historical_exact_case_order:' + version, [p['case'] for p in result['periods']], EXPECTED_NAMES)
        prior_info[version] = (base, proof, {p['case']: p for p in result['periods']})
    report, pooled = {}, {}
    for period in periods:
        name, source = period['case'], period['source']
        path = out/name/'predictions.csv.gz'
        checks.require('historical_current_is_replayed_output:' + name,
                       sha(path) == hashes[name+'/predictions.csv.gz'])
        current = pd.read_csv(path, float_precision='round_trip')
        pool = pooled.setdefault(source, {'current': [], **{v: [] for v in prior_info}})
        pool['current'].append(current)
        report[name] = {}
        for version, (base, proof, saved_periods) in prior_info.items():
            old_path = base/name/'predictions.csv.gz'; digest = sha(old_path)
            checks.require('historical_prediction_bound_to_audit:' + version + '/' + name,
                           digest == proof['hashes'].get(name+'/predictions.csv.gz'))
            hashes['historical/' + version + '/' + name + '/predictions.csv.gz'] = digest
            prior = pd.read_csv(old_path, float_precision='round_trip')
            checks.require('historical_same_source:' + version + '/' + name, saved_periods[name]['source'] == source)
            for key in ('sample_index', 'label', 'baseline', 'reference'):
                checks.array('historical_same_original_axis:' + version + '/' + name + '/' + key, prior[key], current[key])
            checks.tree('historical_saved_candidate_metrics:' + version + '/' + name,
                stats(current.label.to_numpy(np.int8), prior.candidate.to_numpy(np.int8), 60),
                saved_periods[name]['comparisons']['v6_vs_v7']['candidate'])
            report[name][version] = historical_pair(current.label.to_numpy(np.int8), prior.candidate.to_numpy(np.int8),
                                                    current.candidate.to_numpy(np.int8), comparison)
            pool[version].append(prior)
    source_results = {}
    for source, parts in pooled.items():
        current = pd.concat(parts['current'], ignore_index=True)
        checks.require('historical_pool_contiguous:' + source, bool(np.all(np.diff(current.sample_index) == 1)))
        source_results[source] = {}
        for version in prior_info:
            prior = pd.concat(parts[version], ignore_index=True)
            checks.array('historical_pool_original_axis:' + source + '/' + version, current.sample_index, prior.sample_index)
            source_results[source][version] = historical_pair(current.label.to_numpy(np.int8), prior.candidate.to_numpy(np.int8),
                                                               current.candidate.to_numpy(np.int8), comparison)
    return {'periods': report, 'source_pools': source_results,
            'summary': historical_objectives(report, source_results),
            'no_historical_model_fit_or_alternative_selection': True,
            'event_id_scope': 'Period event IDs are local original labels; source-pool IDs recomputed after contiguous-axis concatenation, not added across periods.'}


def method_spec(plan):
    if plan.get('attempt') != ATTEMPT: raise ValueError('Exact reviewed V13 attempt required')
    return {'runtime': 'ml.gecco_v13.runtime', 'bundle_version': VERSION,
            'model_class': 'HardNormalTailHGBScorer', 'guarded_score': True,
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
    for module, pinned in ((v12, V12_AUDITOR_SHA), (v9, V9_AUDITOR_SHA), (v10, V10_AUDITOR_SHA), (v8, V8_AUDITOR_SHA), (old, ORIGINAL_AUDITOR_SHA), (delayed, DELAYED_AUDITOR_SHA), (certified, CERTIFIED_AUDITOR_SHA)):
        checks.require('unchanged_reused_auditor:' + module.__name__, sha(module.__file__) == pinned)
    required = {'ml/gecco_v9/' + name for name in ('conditional.py', 'development.py', 'runtime.py')}
    required |= {'ml/gecco_v13/' + name for name in ('hard_normal.py', 'development.py', 'runtime.py')}
    required |= {'ml/gecco_v12/baseline_evidence.py'}
    checks.require('unchanged_frozen_v12_features', sha(root / 'ml/gecco_v12/baseline_evidence.py') == V12_FEATURE_SHA)
    required |= {'ml/gecco_v10/calibration.py'}
    checks.require('unchanged_frozen_v10_policy', sha(root / 'ml/gecco_v10/calibration.py') == V10_CALIBRATION_SHA)
    required |= {'ml/gecco_v8/onset.py'}
    required |= {'ml/gecco_v7/' + name for name in ('calibration_certified.py', 'runtime_delayed.py', 'evidence.py')}
    checks.require('all_v13_method_code_is_frozen', required.issubset(plan['code_sha256']))
    recipe = plan.get('normal_weight_recipe', {})
    checks.tree('fixed_normal_weight_recipe', {key: recipe.get(key) for key in
        ('quantile', 'quantile_method', 'tail_comparison', 'tail_relative_weight', 'other_relative_weight', 'total_negative_mass')},
        {'quantile': .95, 'quantile_method': 'linear', 'tail_comparison': '>=',
         'tail_relative_weight': 5, 'other_relative_weight': 1, 'total_negative_mass': .5})
    method_spec(plan)
    verify_reference_manifest(plan, checks)
    return old._verify_provenance(root, out, {**plan, 'attempt': 'run02_hgb_guarded'}, checks, hashes)


def _load_runtime(root, plan):
    _, comparison, stats = old._load_runtime(root, {**plan, 'attempt': 'run02_hgb_guarded'})
    module = importlib.import_module('ml.gecco_v13.runtime')
    if Path(module.__file__).resolve() != root / 'ml/gecco_v13/runtime.py':
        raise ValueError('V13 runtime must resolve to verified code')
    return module.predict_frame, comparison, stats


def _audit_case(root, out, spec, source, saved_top, plan_sha, checks, hashes, runtime, comparison, stats, method=None):
    """Reuse immutable full raw replay, then audit new V13 training/IF state and frozen V10 calibration."""
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
    from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer
    from ml.gecco_v13.hard_normal import HardNormalTailHGBScorer
    checks.require(name + ':reviewed_normal_weight_fit_unchanged_inference',
                   type(model) is HardNormalTailHGBScorer
                   and type(model).fit is HardNormalTailHGBScorer.fit
                   and type(model).features is BaselineEvidenceHGBScorer.features
                   and type(model).score_components is LongContextEventScorer.score_components)
    if model.model_ is not None:
        checks.tree(name + ':fixed_hgb_parameters', {k: model.model_.get_params()[k] for k in HGB_PARAMS}, HGB_PARAMS)
    prototype = OnsetWeightedHGBScorer(spec['channels'])
    old_contract = prototype.feature_contract_
    new_contract = {k: v for k, v in model.feature_contract_.items() if k not in ('conditional_residuals', 'original_if_evidence', 'hard_normal_weighting')}
    for skip in ('version', 'feature_names', 'feature_count'): old_contract.pop(skip); new_contract.pop(skip)
    # The negative-weighting prose is allowed to change, with its numerical
    # delta independently checked above. All positive-onset metadata stays.
    old_contract.pop('weighting'); new_contract.pop('weighting')
    checks.tree(name + ':original_features_positive_onset_and_hgb_contract_unchanged', new_contract, old_contract)
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
    period['hard_normal_weighting_audit'] = weights['hard_normal_summary']
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
    report = {"audit_version": "v13_train_normal_if_tail_full_raw_sensor_batch_replay_v1", "created_at_utc": datetime.now(timezone.utc).isoformat(),
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
                  "V13 inference tested here is batch; prefix tests are not a persistent-state streaming implementation.",
                  "Fitted artifacts and declared bounds are checked without retraining; historical absence of hidden access is not provable from artifacts alone.",
                  "Reference statistics use the whole training block. Causal inference is conditional on these frozen training-only references; this is not online re-estimation at each earlier training row.",
                  "V6 unknown-label metrics are reused; V13 normal-tail weights and unchanged positive-onset weights, normal references, conditional ridge coefficients/scales/masks, original and added features, calibration sensor scores, certificate and summary are independently checked.",
                  "The only approved weighting delta uses q95 over all training known-normal finite float64 IF scores; inclusive tail rows receive5:1 relative normal weight inside the unchanged total normal mass0.5. Calibration/test scores do not define this population.",
                  "Frozen IF scores used by HGB training are in-sample known-normal representations, not cross-fitted independent evidence.",
                  "IF feature values use full supplied-prefix pandas rolling state. Cropped numerical or streaming parity is not claimed.",
                  "The IF input-feature oracle independently reconstructs the four groups using pinned installed pandas numerical kernels, then calls the verified frozen estimator; it does not reimplement isolation trees.",
                  "The ridge-reference oracle independently solves fixed coefficient equations for verification only; no classifier or alarm operating point is refitted.",
                  "Legacy comparison keys ending in v7 denote the current V13 candidate.", "GECCO seconds use nominal acquisition cadence; WaterHub has a verified regular timestamp grid."]}
    try:
        checks.require("all_19_complete_before_source_access", True)
        checks.require("declared_development_scope", plan.get("all_sources_previously_disclosed") is True
                       and plan.get("fresh_validation") is False and completed.get("fresh_validation") is False)
        hashes["plan.json"], hashes["results.json"] = sha(out / "plan.json"), sha(out / "results.json")
        report['execution_resume_audit'] = audit_execution_resume(root, out, plan, completed, checks, hashes)
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
        report["hard_normal_weighting_audit_by_case"] = {p["case"]: p["hard_normal_weighting_audit"] for p in periods}
        report["v8_event_comparison"] = audit_v8_event_ids(root, checks, hashes, by_source, periods, out, stats)
        report["v8_comparison_scope"] = {"granularity": "each_of_19_original_test_periods",
            "includes": ["exact_confirmed_event_ids", "paired_extra_delay_seconds", "false_positive_runs", "fp_duration_seconds", "normal_observed_seconds"],
            "diagnostic_only_no_gate_replacement": True, "period_event_counts_are_not_contiguous_source_unique_totals": True}
        report['historical_comparisons'] = audit_historical_comparisons(root, out, plan, checks, hashes, periods, comparison, stats)
        report['historical_acceptance_separate_from_numeric_audit'] = report['historical_comparisons']['summary']
        checks.require("all_expected_test_rows_replayed", report["replayed_rows"] == 449431)
        checks.require("all_expected_calibration_rows_replayed", report["calibration_sensor_rows_replayed"] == 891750)
        report["recomputed_development_gates"] = {key: value["passes_declared_development_gate"] for key, value in summary.items()}
        checks.require("completed_plan_unchanged", sha(out / "plan.json") == hashes["plan.json"])
        checks.require("completed_results_unchanged", sha(out / "results.json") == hashes["results.json"])
        for relative, expected in plan["code_sha256"].items():
            checks.require("current_code_unchanged_after_replay:" + relative, sha(inside(root, relative)) == expected)
        if report['execution_resume_audit']['present']:
            for relative, expected in hashes.items():
                if relative.startswith('execution_resume/'):
                    checks.require('resume:metadata_unchanged_after_replay:'+relative, sha(out/relative) == expected)
                elif relative.startswith('ml/gecco_v13_control/'):
                    checks.require('resume:controller_unchanged_after_replay:'+relative, sha(root/relative) == expected)
                elif relative.startswith('workspace:'):
                    checks.require('resume:external_pin_unchanged_after_replay:'+relative,
                                   sha(root/relative.removeprefix('workspace:')) == expected)
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
