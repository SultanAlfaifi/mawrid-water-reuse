"""V16 pre-test training audit and hash-bound outer raw-sensor replay.

No V16 production inference, feature wrapper, weights or selection is called.
Joblib necessarily imports the fitted object's class. Rich historical feature
formulas and fitted sklearn predictions are inherited explicitly; the separate
audit helpers reconstruct request ownership, weights, IF inputs and local paths.
This does not refit estimators or claim that bookkeeping proves every fit input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import re

import joblib
import numpy as np
import pandas as pd

from ml.gecco_v7_audits import replay as original
from ml.gecco_v7_audits.replay_certified import fitted_state_digest
from ml.gecco_v12.baseline_evidence import baseline_state_digest
from ml.gecco_v15 import audit as policy
from ml.gecco_v16_audits.decisions import context_oracle, weight_oracle
from ml.gecco_v16_audits import teachers as teacher_audit

ROOT = Path(__file__).resolve().parents[2]
NAMES = list(policy.NAMES)
HISTORY = [f'v{i}' for i in range(8, 16)]
VERSION = 'v16_forward_teacher_decision_head'
AUDIT_VERSION = 'v16_forward_teacher_raw_sensor_batch_replay_v1'
PROTOCOL = 'output/ml/gecco-v16-design/protocol.json'
PROTOCOL_SHA = 'f4aa6376ad9586196ce8fdb2484cae9fb92b56bfba601e866da009013ff61b9a'
V15_AUDIT_SHA = '0a297adf68575da23d6cea7d54b34500b36bd7b3e370a141b09e5a15c2eb8045'
HGB_PARAMS = dict(max_iter=100, max_leaf_nodes=15, max_depth=None,
    min_samples_leaf=20, learning_rate=.08, l2_regularization=1, max_bins=63,
    early_stopping=False, random_state=20261016)
CONTEXT_NAMES = ('v6_alarm', 'v8_alarm', 'v6_known', 'v8_known',
    'anchor_opportunity', 'anchor_age_fraction', 'recovery_opportunity', 'recovery_age_fraction')
sha, read = policy.sha, policy.read


class Checks(original.Checks):
    """Legacy-compatible, fail-fast checks with exact bit/mask comparisons."""
    def add(self, name, passed, count=1, numeric=0, detail=None):
        result = super().add(name, passed, count, numeric, detail)
        if not result: raise ValueError(name)
        return result

    def array(self, name, actual, expected, *, floating=False):
        a, b = np.asarray(actual), np.asarray(expected)
        if floating and a.shape == b.shape:
            self.require(name + ':nonfinite masks', bool(np.array_equal(np.isnan(a), np.isnan(b)) and
                np.array_equal(np.isposinf(a), np.isposinf(b)) and np.array_equal(np.isneginf(a), np.isneginf(b))))
        result = super().array(name, a, b, floating=floating)
        self.require(name + ':passed', result)
        return result

    def tree(self, name, actual, expected):
        result = super().tree(name, actual, expected)
        self.require(name + ':passed', result)
        return result

    def fields(self, name, actual, expected):
        self.require(name + ':mapping', isinstance(actual, dict) and set(expected) <= set(actual))
        return self.tree(name, {key: actual[key] for key in expected}, expected)

    def bits(self, name, actual, expected):
        a = np.asarray(actual)
        self.require(name + ':boolean dtype', a.dtype.kind == 'b')
        return self.array(name, a, np.asarray(expected, bool))

    def exact(self, name, actual, expected):
        a, b = np.asarray(actual), np.asarray(expected)
        self.require(name + ':dtype', a.dtype == b.dtype)
        self.require(name + ':shape', a.shape == b.shape)
        self.require(name + ':bitwise values', bool(np.array_equal(a, b, equal_nan=True)))
        self.add(name + ':count', True, b.size, b.size)
        return True


def bounded(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError('Expected a relative artifact path')
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Artifact path escapes its declared root')
    return path


def parent(version):
    return ROOT / f'output/ml/gecco-{version}-development/run_01'


def geometry(n):
    """Independent integer implementation of the frozen inner boundaries."""
    if isinstance(n, (bool, np.bool_)) or not isinstance(n, (int, np.integer)) or n < 16:
        raise ValueError('Original training length must be an integer >=16')
    edges = [int(n) * k // 4 for k in range(1, 5)]
    result = []
    for fold, (start, end) in enumerate(zip(edges[:-1], edges[1:]), 1):
        fit = 3 * start // 5
        bounds = [fit + (start - fit) * k // 4 for k in range(5)]
        result.append({'fold': fold, 'fit': [0, fit], 'calibration_bounds': bounds,
                       'forecast': [start, end]})
    return result


def array_digest(value):
    a = np.ascontiguousarray(value)
    h = hashlib.sha256(); h.update(str(a.shape).encode()); h.update(a.dtype.str.encode()); h.update(a.tobytes())
    return h.hexdigest()


def compact(value):
    """Retain array provenance/counts without duplicating large training axes."""
    if isinstance(value, np.ndarray):
        result = {'shape': list(value.shape), 'dtype': value.dtype.str, 'sha256': array_digest(value)}
        if value.dtype.kind == 'b': result['true_rows'] = int(value.sum())
        return result
    if isinstance(value, np.generic): return value.item()
    if isinstance(value, dict): return {key: compact(item) for key,item in value.items()}
    if isinstance(value, (list,tuple)): return [compact(item) for item in value]
    return value


def csv(path, numeric_files):
    numeric_files.append(str(Path(path).relative_to(ROOT)))
    return pd.read_csv(path, float_precision='round_trip')


def npz(path, numeric_files):
    numeric_files.append(str(Path(path).relative_to(ROOT)))
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def verify_plan(run, checks):
    plan = read(run / 'plan.json')
    checks.fields('V16 plan scope', plan, {'version': VERSION, 'attempt': 'v16_run01_forward_teacher_head',
        'development_only': True, 'fresh_validation': False, 'expected_cases': 19, 'case_order': NAMES,
        'protocol_sha256': PROTOCOL_SHA, 'all_sources_previously_disclosed': True,
        'original_v15_audit_sha256': V15_AUDIT_SHA, 'all19_before_outer_test': True, 'no_promotion': True,
        'source_axes': ['2017', '2018', '2019', 'WaterHub'], 'policy_family': 'Exact frozen V15'})
    for group in ('code_sha256', 'input_sha256'):
        checks.require(group + ':nonempty', bool(plan.get(group)))
        for path, digest in plan[group].items():
            checks.require(group + ':' + path, sha(bounded(ROOT, path)) == digest)
            if group == 'code_sha256':
                checks.require('source snapshot:' + path, sha(bounded(run / 'source', path)) == digest)
    checks.require('pinned V16 protocol', plan['input_sha256'].get(PROTOCOL) == PROTOCOL_SHA)
    required = ['ml/gecco_v16/' + f for f in ('model.py', 'decisions.py', 'teachers.py', 'development.py', 'runtime.py', 'test.py')]
    required += ['ml/gecco_v16_audits/' + f for f in ('replay.py', 'model.py', 'decisions.py', 'teachers.py')]
    required += ['ml/gecco_v15/' + f for f in ('audit.py', 'runtime.py', 'checks.py', 'calibration.py')]
    checks.require('entire method/audit closure declared', all(p in plan['code_sha256'] for p in required))
    checks.require('pinned completed V15 audit', sha(parent('v15') / 'audit.json') == V15_AUDIT_SHA)
    previous = read(parent('v15') / 'audit.json')
    checks.fields('completed V15 audit', previous, {'passed': True, 'failed_checks': 0,
        'complete_replayed_cases': 19, 'audit_version': policy.AUDIT_VERSION})
    for filename in ('plan.json', 'results.json'):
        checks.require('V15 audit binding:' + filename, previous['hashes'][filename] == sha(parent('v15') / filename))
    for version in HISTORY:
        folder = parent(version); audited = read(folder / 'audit.json')
        checks.fields('historical audit complete:' + version, audited,
            {'passed': True, 'failed_checks': 0, 'complete_replayed_cases': 19})
        for filename in ('plan.json', 'results.json', 'audit.json'):
            key = str((folder / filename).relative_to(ROOT))
            checks.require('historical metadata pinned:' + key, plan['input_sha256'].get(key) == sha(folder / filename))
            if filename != 'audit.json':
                checks.require('historical metadata audited:' + key, audited['hashes'][filename] == sha(folder / filename))
        for name in NAMES:
            for filename in (('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz', 'predictions.csv.gz')
                             if version == 'v8' else ('predictions.csv.gz',)):
                key = str((folder / name / filename).relative_to(ROOT))
                checks.require('historical artifact pinned:' + key,
                    plan['input_sha256'].get(key) == audited['hashes'][name + '/' + filename])
    return plan


def validate_frozen(run, checks, *, stage):
    frozen = read(run / 'policies-frozen.json')
    checks.fields('all19 frozen before test', frozen, {'plan_sha256': sha(run / 'plan.json'),
        'all19_calibration_complete': True, 'outer_test_numerical_arrays_opened': False})
    checks.require('exact frozen case order', list(frozen.get('policies', {})) == NAMES)
    expected_dirs = {p.name for p in run.iterdir() if p.is_dir() and p.name != 'source'}
    checks.require('exact case directories', expected_dirs == set(NAMES))
    for name in NAMES:
        folder = run / name; item = frozen['policies'][name]
        checks.require(name + ':case freeze hash', sha(folder / 'freeze.json') == item['freeze_sha256'])
        f = read(folder / 'freeze.json')
        checks.fields(name + ':freeze scope', f, {'case': name, 'plan_sha256': sha(run / 'plan.json'),
            'bundle_sha256': item['bundle_sha256'], 'outer_test_numerical_arrays_opened': False})
        checks.fields(name + ':chosen policy', f['selected'], {'choice': item['choice'], 'accepted': item['accepted']})
        checks.tree(name + ':selection copy', read(folder / 'selection.json'), f['selected'])
        artifacts = f['artifacts_sha256']
        essential = {'bundle.joblib', 'selection.json', 'trials.json', 'calibration_scores.csv.gz',
            'head_examples.npz', 'training_axis.csv.gz', 'training_weights.json', 'inner_lineage.json', 'model_inspection.json'}
        checks.require(name + ':training artifacts present', essential <= set(artifacts))
        for file, digest in artifacts.items():
            checks.require(name + ':frozen:' + file, sha(bounded(folder, file)) == digest)
        checks.require(name + ':bundle artifact cross-binding', artifacts['bundle.joblib'] == item['bundle_sha256'])
        extras = {'freeze.json'}
        if stage == 'test':
            extras |= {'predictions.csv.gz', 'results.json', 'test_case_freeze.json'}
            verify_test_receipt(run, name, checks)
            extras |= set(preserved_test_files(folder, checks))
        actual = {str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()}
        checks.require(name + ':no undeclared case files', actual == set(artifacts) | extras)
    return frozen


def preserved_test_files(folder, checks):
    """Preserved interrupted outputs are hash-bound evidence, never metrics."""
    result = {}
    for directory in folder.iterdir():
        if not directory.name.startswith('test_unsealed_'): continue
        checks.require('preserved test directory name', directory.is_dir() and bool(re.fullmatch(r'test_unsealed_\d+', directory.name)))
        for path in directory.iterdir():
            checks.require('preserved output scope', path.is_file() and path.name in {'predictions.csv.gz','results.json'})
            result[str(path.relative_to(folder))] = sha(path)
    return result


def verify_test_receipt(run, name, checks):
    folder = run/name; receipt = read(folder/'test_case_freeze.json')
    checks.fields(name + ':completed test receipt', receipt, {'case':name,
        'plan_sha256':sha(run/'plan.json'),'policies_sha256':sha(run/'policies-frozen.json'),
        'pretest_audit_sha256':sha(run/'pretest-audit.json'), 'one_fixed_outer_pass':True,'no_retuning':True})
    checks.require(name + ':exact test receipt files', set(receipt['files']) == {'predictions.csv.gz','results.json'})
    for file,digest in receipt['files'].items():
        checks.require(name + ':completed test hash:' + file, sha(folder/file) == digest)
    return receipt


def verify_inner_seal(inner, checks):
    sealed = read(inner/'complete.json')
    checks.require('exact completed inner file inventory', set(sealed['files']) ==
        {p.name for p in inner.iterdir() if p.is_file() and p.name != 'complete.json'})
    for file,digest in sealed['files'].items():
        checks.require('inner completed artifact:' + file, sha(bounded(inner,file)) == digest)
    return sealed['record']


def stage_gate(stage, run, checks, frozen):
    if stage == 'train':
        checks.require('pretest precedes all outer artifacts', not any((run / n).exists()
            for n in ('test-started.json', 'results.json', 'audit.json')))
        return None
    proof = read(run / 'pretest-audit.json'); started = read(run / 'test-started.json')
    checks.fields('complete matching pretest audit', proof, {'audit_version': AUDIT_VERSION,
        'stage': 'train', 'passed': True, 'failed_checks': 0, 'complete_replayed_cases': 19,
        'audit_script_sha256': sha(__file__), 'plan_sha256': sha(run / 'plan.json'),
        'policies_sha256': sha(run / 'policies-frozen.json'), 'outer_test_rows_read': 0})
    checks.fields('test opened only after matching proof', started, {'plan_sha256': sha(run / 'plan.json'),
        'policies_sha256': sha(run / 'policies-frozen.json'),
        'pretest_audit_sha256': sha(run / 'pretest-audit.json'), 'one_fixed_outer_pass': True})
    for key, digest in proof['hashes'].items():
        checks.require('pretest frozen binding:' + key, sha(bounded(run, key)) == digest)
    checks.require('pretest exact case records', list(proof.get('cases',{})) == NAMES)
    required = {'plan.json','policies-frozen.json'}
    for name in NAMES:
        f = read(run/name/'freeze.json')
        required.add(name+'/freeze.json')
        required.update(name+'/'+file for file in f['artifacts_sha256'])
    checks.require('pretest covers all training artifacts', required <= set(proof['hashes']))
    return proof


def compare_table(checks, name, actual, expected, *, exact_columns=True):
    checks.require(name + ':schema', list(actual.columns) == list(expected.columns) if exact_columns
                   else set(expected.columns) <= set(actual.columns))
    for column in expected:
        a, b = actual[column].to_numpy(), expected[column].to_numpy()
        if b.dtype.kind == 'b': checks.bits(name + ':' + column, a, b)
        else: checks.array(name + ':' + column, a, b, floating=b.dtype.kind == 'f')


def score_matrix(head, base, available, v6, v8, *, checks=None, name='score'):
    """Call the separate auditor's scorer, never a V16 production method."""
    from ml.gecco_v16_audits.model import score_matrix_oracle
    checks = Checks() if checks is None else checks
    return score_matrix_oracle(head, base, available, v6, v8, checks=checks, name=name)


def audit_head(checks, name, head, y, matrix, indices, folds, accounting):
    selected = np.asarray(indices, np.int64)
    checks.exact(name + ':unique full original example indices', selected, np.flatnonzero(accounting['eligible']))
    target = np.asarray(y, np.int8)[selected]
    expected = {'example_indices_': selected, 'example_fold_ids_': np.asarray(folds, np.int64)[selected],
        'example_event_ids_': accounting['event_ids'][selected], 'example_targets_': target,
        'example_sample_weight_': accounting['sample'][selected],
        'example_normalized_weight_': accounting['normalized'][selected],
        'example_eligible_mask_': np.ones(len(selected), bool)}
    for field, value in expected.items():
        actual = getattr(head, field)
        if value.dtype.kind == 'b': checks.bits(name + ':' + field, actual, value)
        else: checks.array(name + ':' + field, actual, value, floating=value.dtype.kind == 'f')
    checks.require(name + ':matrix hash', head.example_matrix_sha256_ == array_digest(matrix))
    checks.require(name + ':matrix float32 finite', matrix.dtype == np.float32 and np.isfinite(matrix).all())
    checks.require(name + ':no retained training matrix', not hasattr(head, 'example_matrix_'))
    checks.tree(name + ':global training summary', head.training_summary_, accounting['summary'])
    checks.tree(name + ':per-type request support', head.request_support_, accounting['summary']['request_support'])
    normal, positive = int((target == 0).sum()), int((target == 1).sum())
    events = len(np.unique(accounting['event_ids'][selected][target == 1]))
    positive_folds = np.unique(np.asarray(folds)[selected][target == 1]).tolist()
    fit_checks = {'normal_rows': normal >= 128, 'positive_events': events >= 2, 'positive_folds': len(positive_folds) >= 2}
    status = ('insufficient_normal_decision_rows' if normal < 128 else 'insufficient_positive_events' if events < 2
              else 'insufficient_positive_folds' if len(positive_folds) < 2 else 'fitted')
    checks.tree(name + ':fit checks', head.fit_checks_, fit_checks)
    checks.require(name + ':fit status', head.fit_status_ == status)
    checks.require(name + ':classifier presence', (head.model_ is not None) == (status == 'fitted'))
    checks.require(name + ':training rows', head.training_rows_ == len(y))
    checks.require(name + ':fit populations', (head.fit_normal_rows_, head.fit_positive_rows_, head.fit_events_) == (normal, positive, events))
    checks.tree(name + ':fit positive folds', head.fit_positive_folds_, positive_folds)
    checks.require(name + ':feature width', len(head.feature_names_) == matrix.shape[1] == len(head.base_feature_names_) + 8)
    checks.tree(name + ':context names', head.feature_names_[-8:], list(CONTEXT_NAMES))
    if head.model_ is not None:
        params = head.model_.get_params(deep=False)
        checks.tree(name + ':fixed HGB parameters', {k: params[k] for k in HGB_PARAMS}, HGB_PARAMS)
        checks.array(name + ':HGB classes', head.model_.classes_, [0, 1])
        checks.require(name + ':HGB feature width', head.model_.n_features_in_ == matrix.shape[1])
        checks.require(name + ':HGB exact iterations', head.model_.n_iter_ == 100)
    return {'fit_status': status, 'examples': len(selected), 'normal_rows': normal, 'positive_rows': positive,
        'positive_events': events, 'positive_folds': positive_folds, 'request_support': accounting['summary']['request_support'],
        'independent_current_targets_and_weights': True, 'one_fixed_head_fit_declared_no_audit_refit': True,
        'fitted_input_ownership_limit': 'Saved arrays, receipt hashes, temporal dataflow and parameters checked; no classifier refit proof.'}


def training_case(run, case, checks, numeric_files):
    from ml.gecco_v16_audits import model as model_audit
    name = case['name']; folder = run / name; frozen = read(folder / 'freeze.json')
    x = case['train'].loc[:, case['channels']]; y = case['train'][case['target']].to_numpy(np.int8)
    checks.fields(name + ':original geometry', frozen, {'train': [0, len(x)], 'source': case['source'],
        'calibration_starts': case['cal_starts'], 'continuous_cal': case['continuous_cal'],
        'test': [case['test_start'], case['test_end']]})
    bundle = joblib.load(folder / 'bundle.joblib'); before = fitted_state_digest(bundle)
    checks.fields(name + ':bundle scope', bundle, {'version': VERSION, 'sample_seconds': 60, 'gap_samples': 120,
        'max_fit_index': len(x)-1, 'max_calibration_index': case['test_start']-1, 'selected': frozen['selected']})
    reference = joblib.load(parent('v8') / name / 'bundle.joblib')
    checks.require(name + ':exact historical V8 bundle semantic state', fitted_state_digest(bundle['reference_bundle']) == fitted_state_digest(reference))
    original_if = reference['reference_bundle']['prior_bundle']['model'].baseline_
    head = bundle['model']
    checks.require(name + ':unchanged original IF', baseline_state_digest(head.original_IF_) == baseline_state_digest(original_if))
    checks.require(name + ':unchanged IF attachment receipt', head.original_if_state_sha256_ == baseline_state_digest(original_if))
    del reference  # Keep only the original IF; avoid a second full expert tree bundle.
    checks.tree(name + ':channel order', head.channels, case['channels'])
    checks.tree(name + ':base feature order', head.base_feature_names_, head.generator_.feature_names_)
    n = len(x); available = np.zeros(n, bool); folds = np.full(n, -1, np.int64)
    anchors = np.full(n, -1, np.int64); recoveries = np.full(n, -1, np.int64)
    matrices = []; all_indices = []; inner_summaries = []
    lineage = read(folder / 'inner_lineage.json'); expected_lineage = []
    for geom in geometry(n):
        inner = folder / ('inner_' + str(geom['fold'])); f = read(inner / 'freeze.json')
        completed_inner = verify_inner_seal(inner, checks)
        fit_end = geom['fit'][1]; start, end = geom['forecast']; bounds = geom['calibration_bounds']
        checks.fields(name + ':inner freeze geometry', f, {'geometry': geom, 'max_fit_index': fit_end-1,
            'max_selection_index': start-1, 'teacher_sha256': sha(inner / 'teacher.joblib')})
        checks.require(name + ':inner past only', fit_end <= bounds[0] < bounds[-1] == start < end)
        teacher = joblib.load(inner / 'teacher.joblib')
        checks.tree(name + ':teacher metadata file', read(inner / 'teacher_metadata.json'), teacher['training_metadata'])
        teacher['calibration_data'] = [csv(inner / f'calibration_{i}.csv.gz', numeric_files) for i in range(4)
                                       if (inner / f'calibration_{i}.csv.gz').exists()]
        teacher['trials'] = read(inner / 'calibration_trials.json')
        checks.require(name + ':supported receipt', f['supported'] is teacher['supported'])
        forecast = csv(inner / 'forecast.csv.gz', numeric_files) if f['supported'] else None
        if not f['supported']:
            checks.fields(name + ':unsupported receipt', f, {'status': teacher['status'], 'no_forecast_prediction_invented': True})
            checks.require(name + ':unsupported cannot invent artifacts', not any((inner / file).exists()
                for file in ('generator.joblib', 'forecast.csv.gz', 'examples.npz')))
        audit = teacher_audit.audit_teacher(checks, name + f':teacher{geom["fold"]}', teacher,
            x.iloc[:fit_end], y[:fit_end], [x.iloc[a:b] for a,b in zip(bounds[:-1],bounds[1:])],
            [y[a:b] for a,b in zip(bounds[:-1],bounds[1:])], bounds[:-1],
            x.iloc[start:end] if f['supported'] else None, forecast)
        inner_summaries.append(audit)
        if not f['supported']:
            record = {'geometry': geom, 'supported': False, 'status': teacher['status']}
            checks.tree(name + ':unsupported completion record', completed_inner, record)
            expected_lineage.append(record)
            del teacher; gc.collect(); continue
        checks.fields(name + ':supported receipt', f, {'generator_sha256': sha(inner / 'generator.joblib'),
            'first_forecast_index': start, 'no_outer_calibration_or_test_used': True})
        generator = joblib.load(inner / 'generator.joblib')
        checks.require(name + ':inner IF is rebuilt teacher IF', baseline_state_digest(generator.baseline_estimator_) ==
                       baseline_state_digest(teacher['v6_bundle']['prior_bundle']['model'].baseline_))
        audit['generator'] = compact(model_audit.audit_generator(checks, name + ':inner generator', generator, x.iloc[:fit_end], y[:fit_end]))
        base, observed = model_audit.features_oracle(checks, name + ':inner forecast features', generator, x.iloc[start:end], gap=120)
        v6, v8 = forecast.v6.to_numpy(np.int8), forecast.v8.to_numpy(np.int8)
        context = context_oracle(v6, v8); X = np.concatenate((base, context['matrix']), axis=1)
        checks.array(name + ':forecast original axis', forecast.sample_index, np.arange(start, end))
        checks.array(name + ':forecast original labels', forecast.label, y[start:end])
        checks.bits(name + ':base availability', forecast.base_available, observed)
        folds[start:end] = geom['fold']; available[start:end] = observed
        for destination, key in ((anchors, 'anchor_origins'), (recoveries, 'recovery_origins')):
            expected = np.where(context[key] >= 0, context[key] + start, -1)
            destination[start:end] = expected; checks.array(name + ':' + key, forecast[key], expected)
        for j, column in enumerate(CONTEXT_NAMES): checks.array(name + ':' + column, forecast[column], context['matrix'][:,j])
        keep = observed & context['active'] & (y[start:end] >= 0)
        indices = np.flatnonzero(keep) + start; selected = npz(inner / 'examples.npz', numeric_files)
        checks.require(name + ':inner NPZ schema', set(selected) == {'matrix', 'indices'})
        checks.exact(name + ':inner X', selected['matrix'], X[keep]); checks.exact(name + ':inner indices', selected['indices'], indices)
        matrices.append(X[keep]); all_indices.append(indices)
        record = {'geometry': geom, 'supported': True, 'example_rows': int(keep.sum()),
            **{key + '_sha256': sha(inner / file) for key, file in (
                ('teacher','teacher.joblib'),('generator','generator.joblib'),('forecast','forecast.csv.gz'),('examples','examples.npz'))}}
        checks.tree(name + ':supported completion record', completed_inner, record)
        expected_lineage.append(record)
        del teacher, generator, forecast, base, X; gc.collect()
    checks.tree(name + ':complete inner lineage', lineage, {'folds': expected_lineage, 'original_train': [0,n],
        'no_original_expert_thresholds_in_training': True})
    accounting = weight_oracle(y, available, folds, anchors, recoveries)
    indices = np.concatenate(all_indices) if all_indices else np.empty(0, np.int64)
    X = np.concatenate(matrices) if matrices else np.empty((0, len(head.feature_names_)), np.float32)
    expected_axis = pd.DataFrame({'sample_index': np.arange(n), 'label': y, 'fold_id': folds,
        'base_available': available, 'anchor_origins': anchors, 'recovery_origins': recoveries,
        'eligible': accounting['eligible'], 'event_id': accounting['event_ids'],
        'normalized_weight': accounting['normalized'], 'sample_weight': accounting['sample']})
    compare_table(checks, name + ':full training axis', csv(folder / 'training_axis.csv.gz', numeric_files), expected_axis)
    checks.tree(name + ':training weights', read(folder / 'training_weights.json'),
        {'summary': accounting['summary'], 'records': accounting['records']})
    examples = npz(folder / 'head_examples.npz', numeric_files)
    expected_examples = {'matrix': X, 'indices': indices, 'fold_ids': folds[indices].astype(np.int8),
        'event_ids': accounting['event_ids'][indices], 'weights': accounting['sample'][indices]}
    checks.require(name + ':head NPZ schema', set(examples) == set(expected_examples))
    for key, expected in expected_examples.items(): checks.exact(name + ':head examples:' + key, examples[key], expected)
    head_summary = audit_head(checks, name + ':head', head, y, X, indices, folds, accounting)
    checks.require(name + ':final generator same original IF', baseline_state_digest(head.generator_.baseline_estimator_) == baseline_state_digest(original_if))
    final_generator = compact(model_audit.audit_generator(checks, name + ':final generator', head.generator_, x, y))
    inspection = read(folder / 'model_inspection.json')
    checks.fields(name + ':saved head inspection', inspection, {'fit_status': head.fit_status_, 'training_rows': n,
        'example_rows': len(indices), 'example_matrix_sha256': array_digest(X),
        'training_summary': accounting['summary'], 'request_support': accounting['summary']['request_support'],
        'original_if_unchanged': True, 'representation_shift_disclosed': True, 'example_matrix_retained': False})
    checks.fields(name + ':reference-only metadata', inspection['final_generator'],
        {'reference_only_fit': True, 'head_examples_from_forward_teachers': True, 'hgb_fitted_here': False})
    checks.fields(name + ':no inherited in-sample claim', inspection['final_generator']['original_if_evidence'],
        {'in_sample_training_representation': False, 'cross_fitted': False})
    calibration = calibration_case(run, case, head, checks, numeric_files, full_grid=True)
    checks.require(name + ':entire bundle unchanged by audit', before == fitted_state_digest(bundle))
    return {'case': name, 'source': case['source'], 'training_rows': n, 'inner_teachers': inner_summaries,
        'head': head_summary, 'final_generator': final_generator, 'calibration': calibration,
        'outer_test_rows_read': 0, 'no_estimator_refit': True, 'fitted_state_unchanged': True}


def calibration_case(run, case, head, checks, numeric_files, *, full_grid):
    from ml.gecco_v16_audits import model as model_audit
    name = case['name']; folder = run / name
    old = csv(parent('v8') / name / 'calibration_scores.csv.gz', numeric_files)
    labels = np.concatenate([part[case['target']].to_numpy(np.int8) for part in case['cal']])
    checks.array(name + ':past cal labels', old.label, labels)
    checks.array(name + ':past cal original axis', old.sample_index, np.arange(case['cal_starts'][0], case['test_start']))
    edges = np.r_[0, np.cumsum([len(part) for part in case['cal']])]
    if case['continuous_cal']:
        base, observed = model_audit.features_oracle(checks, name + ':continuous cal features', head.generator_,
            pd.concat(case['cal'], ignore_index=True).loc[:,case['channels']], gap=120)
    blocks = []; output = []
    for i, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
        rows = old.iloc[left:right]; a, b = rows.reference.to_numpy(np.int8), rows.candidate.to_numpy(np.int8)
        if case['continuous_cal']: scores = model_audit.score_matrix_oracle(head, base[left:right], observed[left:right], a, b, checks=checks, name=name+':cal'+str(i))
        else: scores = model_audit.score_oracle(head, case['cal'][i].loc[:,case['channels']], a, b, gap=120, checks=checks, name=name+':cal'+str(i))
        blocks.append({'labels': labels[left:right], 'v6': a, 'v8': b, 'scores': scores,
            'source_start': int(case['cal_starts'][i]), 'block_id': str(i)})
        output.append(pd.DataFrame({'sample_index': rows.sample_index.to_numpy(), 'label': labels[left:right],
            'baseline': rows.baseline.to_numpy(np.int8), 'reference': a, 'v8': b, 'long_context': scores}))
    selected = read(folder / 'selection.json')
    if full_grid:
        expected, trials = policy.oracle_calibrate(blocks)
        checks.tree(name + ':independent V15 selection', selected, expected)
        checks.tree(name + ':all early grid trials', read(folder / 'trials.json'), trials)
    for rows, block in zip(output, blocks):
        rows['candidate'] = policy.scalar_components(block['v6'], block['v8'], block['scores'], selected['choice'])['final']
    expected = pd.concat(output, ignore_index=True)
    compare_table(checks, name + ':outer calibration', csv(folder / 'calibration_scores.csv.gz', numeric_files), expected)
    return {'rows_replayed': len(expected), 'full_early_grid_replayed': full_grid,
        'accepted': selected['accepted'], 'choice': selected['choice'], 'original_v8_cached_reference_hash_verified': True}


def aggregate(periods, by_source, checks):
    sources = {}; v8_sources = {}; historical = {}
    for source, parts in by_source.items():
        rows = pd.concat(parts, ignore_index=True)
        checks.array(source + ':continuous source axis', np.diff(rows.sample_index), np.ones(len(rows)-1, np.int64))
        y, prediction = rows.label.to_numpy(np.int8), rows.candidate.to_numpy(np.int8)
        sources[source] = policy.comparisons(y, rows.baseline.to_numpy(np.int8), rows.reference.to_numpy(np.int8), prediction)
        v8_sources[source] = policy.pair(y, rows.v8.to_numpy(np.int8), prediction)
        historical[source] = {v: policy.pair(y, rows['history__'+v].to_numpy(np.int8), prediction) for v in HISTORY}
    checks.require('exact four acquisition axes', list(sources) == ['2017', '2018', '2019', 'WaterHub'])
    summ = policy.summary(periods, sources)
    all_v8 = [p['v8_comparison'] for p in periods] + list(v8_sources.values())
    objectives = {'all_periods_and_source_pools_noninferior': all(p['noninferior'] for p in all_v8),
        'strictly_fewer_pooled_false_fragments': sum(p['candidate']['false_positive_runs'] for p in v8_sources.values()) < sum(p['baseline']['false_positive_runs'] for p in v8_sources.values()),
        'false_fragment_reduction_in_two_periods': sum(p['v8_comparison']['candidate']['false_positive_runs'] < p['v8_comparison']['baseline']['false_positive_runs'] for p in periods) >= 2}
    retention = {v: {'retained': all(not p['history'][v]['lost_baseline_event_ids'] for p in periods) and all(not p[v]['lost_baseline_event_ids'] for p in historical.values()),
        'lost': {p['case']: p['history'][v]['lost_baseline_event_ids'] for p in periods if p['history'][v]['lost_baseline_event_ids']},
        'lost_source_pools': {s: p[v]['lost_baseline_event_ids'] for s,p in historical.items() if p[v]['lost_baseline_event_ids']}} for v in HISTORY}
    quality = all(objectives.values()) and all(p['retained'] for p in retention.values()) and summ['if_vs_v7']['passes_declared_development_gate'] and summ['v6_vs_v7']['passes_declared_development_gate']
    return {'periods': periods, 'sources': sources, 'summary': summ, 'v8_sources': v8_sources, 'v8_checks': objectives,
        'historical_retention': retention, 'historical_source_comparisons': historical,
        'v8_totals': {m: policy.totals([p[m] for p in v8_sources.values()]) for m in ('baseline','candidate')},
        'quality_checks_before_independent_audit_passed': bool(quality)}


def test_case(run, case, checks, numeric_files):
    from ml.gecco_v16_audits import model as model_audit
    name = case['name']; folder = run / name
    bundle = joblib.load(folder / 'bundle.joblib'); before = fitted_state_digest(bundle)
    frame = case['load_test'](); sensors = frame.loc[:,case['channels']]
    y = frame[case['target']].to_numpy(np.int8)
    old = csv(parent('v8') / name / 'predictions.csv.gz', numeric_files)
    checks.array(name + ':raw original test labels', old.label, y)
    checks.array(name + ':raw test geometry', old.sample_index, np.arange(case['test_start'],case['test_end']))
    a, b = old.reference.to_numpy(np.int8), old.candidate.to_numpy(np.int8)
    scores = model_audit.score_oracle(bundle['model'], sensors, a, b, gap=120, checks=checks, name=name+':test')
    candidate = policy.scalar_components(a, b, scores, bundle['selected']['choice'])['final']
    expected = pd.DataFrame({'sample_index': old.sample_index, 'label': y,
        'baseline': old.baseline.to_numpy(np.int8), 'reference': a, 'v8': b, 'long_context': scores, 'candidate': candidate})
    result = {'case': name, 'source': case['source'], 'accepted_calibration': bundle['selected']['accepted'],
        'comparisons': policy.comparisons(y, expected.baseline.to_numpy(np.int8), a, candidate),
        'v8_comparison': policy.pair(y,b,candidate), 'history': {}}
    for version in HISTORY:
        rows = old if version == 'v8' else csv(parent(version) / name / 'predictions.csv.gz', numeric_files)
        for key in ('sample_index','label','baseline','reference'):
            checks.array(name + ':historical original axis:' + version + ':' + key, rows[key], old[key])
        previous = rows.candidate.to_numpy(np.int8)
        expected['history__'+version] = previous
        result['history'][version] = policy.pair(y,previous,candidate)
    compare_table(checks, name + ':outer prediction replay', csv(folder / 'predictions.csv.gz', numeric_files), expected)
    checks.fields(name + ':per-period metrics', read(folder / 'results.json'), result)
    checks.require(name + ':bundle unchanged', before == fitted_state_digest(bundle))
    return result, expected


def execute(stage, run):
    run = Path(run).resolve(); checks = Checks(); numeric_files = []; hashes = {}; records = {}
    report = {'audit_version': AUDIT_VERSION, 'stage': stage, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'passed': False, 'audit_script_sha256': sha(__file__), 'development_only': True, 'fresh_validation': False,
        'all_sources_previously_disclosed': True, 'no_estimator_refit': True, 'outer_test_rows_read': 0,
        'scope': 'Training/teacher ownership, independent decision contexts and weights, fixed policy and raw-sensor batch replay. Fitted estimators and frozen rich feature formulas are inherited; no streaming, hardware or quality validation claim.',
        'production_v16_scoring_or_weights_called': False, 'no_new_source_opened': True}
    destination = run / ('pretest-audit.json' if stage == 'train' else 'audit.json')
    try:
        if stage not in ('train','test'): raise ValueError('Stage must be train or test')
        verify_plan(run, checks); frozen = validate_frozen(run, checks, stage=stage)
        hashes.update({'plan.json': sha(run/'plan.json'), 'policies-frozen.json': sha(run/'policies-frozen.json')})
        proof = stage_gate(stage, run, checks, frozen)
        report.update(plan_sha256=hashes['plan.json'], policies_sha256=hashes['policies-frozen.json'])
        if stage == 'test':
            hashes.update({'pretest-audit.json': sha(run/'pretest-audit.json'), 'test-started.json': sha(run/'test-started.json')})
            completed = read(run/'results.json')
            checks.fields('all19 outer results complete', completed, {'candidate_version': 'V16', 'complete_cases': 19,
                'expected_cases': 19, 'all_prespecified_cases_complete': True, 'development_only': True,
                'fresh_validation': False, 'no_promotion': True})
            checks.tree('outer case order', [p['case'] for p in completed['periods']], NAMES)
        # Lazy loader: absolutely no source numerical arrays before every gate.
        from ml.gecco_v7 import development_v2 as source
        periods = []; by_source = {}; actual_names = []
        for case in source.cases('all'):
            name = case['name']; actual_names.append(name)
            checks.require('next exact original case', name == NAMES[len(actual_names)-1])
            if stage == 'train':
                records[name] = training_case(run, case, checks, numeric_files)
            else:
                period, rows = test_case(run, case, checks, numeric_files)
                periods.append(period); by_source.setdefault(case['source'], []).append(rows)
                report['outer_test_rows_read'] += len(rows)
                records[name] = {'rows_replayed': len(rows), 'head_fit_status': proof['cases'][name]['head']['fit_status']}
            folder = run/name; f = read(folder/'freeze.json')
            hashes[name+'/freeze.json'] = sha(folder/'freeze.json')
            for file, digest in f['artifacts_sha256'].items(): hashes[name+'/'+file] = digest
            if stage == 'test':
                for file in ('predictions.csv.gz','results.json','test_case_freeze.json'): hashes[name+'/'+file] = sha(folder/file)
                for file,digest in preserved_test_files(folder, checks).items(): hashes[name+'/'+file] = digest
            print(json.dumps({'audit': stage, 'case': name, 'passed': True}), flush=True)
            del case; gc.collect()
        checks.tree('all19 exact source cases', actual_names, NAMES)
        if stage == 'test':
            result = aggregate(periods, by_source, checks); checks.fields('independent all19 objectives', completed, result)
            hashes['results.json'] = sha(run/'results.json')
            report.update(replayed_rows=report['outer_test_rows_read'], summary=result['summary'],
                v8_checks=result['v8_checks'], historical_retention=result['historical_retention'],
                independent_quality_checks_passed=result['quality_checks_before_independent_audit_passed'])
        else:
            report['calibration_rows_replayed'] = sum(r['calibration']['rows_replayed'] for r in records.values())
            report['training_rows_audited'] = sum(r['training_rows'] for r in records.values())
            report['inner_forecast_rows_replayed'] = sum(i['forecast_rows_replayed'] for r in records.values() for i in r['inner_teachers'])
        verify_plan(run, checks); validate_frozen(run, checks, stage=stage)
        for path,digest in hashes.items(): checks.require('ending artifact binding:'+path, sha(bounded(run,path)) == digest)
        report.update(passed=True, failed_checks=0)
    except Exception as error:
        report.update(failed_checks=1, error=type(error).__name__+': '+str(error))
    report.update(complete_replayed_cases=len(records), cases=records, hashes=hashes,
        total_checks=len(checks.records), total_numeric_checks=sum(r['numeric_comparisons'] for r in checks.records),
        numeric_files_read=numeric_files)
    destination.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: report.get(k) for k in ('stage','passed','complete_replayed_cases','failed_checks','total_numeric_checks','error')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['train','test'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); raise SystemExit(execute(args.stage,args.output))
