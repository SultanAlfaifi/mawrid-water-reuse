"""Fail-closed operational resume of the unchanged, resource-paused V13 run.

Prepare hashes bytes and metadata only. Resume calls the frozen production
--case command, never modifies its algorithm or existing artifacts, and uses
its exact assess/summarize functions only after all19 cases are committed.
There is no source CSV parsing, bundle loading or model fitting in prepare.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_NAMES = ([f'{year}_fold_{k}' for year in ('2017', '2018') for k in range(1, 7)]
    + ['2019_disclosed_test', '2018-11', '2018-12', '2019-01', '2019-02', '2019-03', '2019-04'])
ARTIFACTS = ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz',
             'calibration_trials.csv.gz', 'predictions.csv.gz', 'model_inspection.json', 'results.json')
ATTEMPT = 'v13_run01_train_normal_if_tail_weights'
MIN_FREE_BYTES = 1024**3
THREAD_ENV = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
CONTROL_FILES = ('__init__.py', 'resume.py', 'test_resume.py')


class ResumeError(RuntimeError):
    pass


class ResourcePause(ResumeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(ok, message):
    if not ok: raise ResumeError(message)


def controller_hashes():
    base = Path(__file__).resolve().parent
    return {name: sha(base/name) for name in CONTROL_FILES}


def environment():
    return {'python': platform.python_version(), **{
        name: importlib.metadata.version('scikit-learn' if name == 'sklearn' else name)
        for name in ('numpy', 'pandas', 'sklearn')}}


def atomic_new_json(path, value):
    """Publish a flushed new file atomically; never replace any existing path."""
    path = Path(path)
    require(not path.exists(), 'Refusing to replace existing metadata: '+str(path))
    descriptor, temporary = tempfile.mkstemp(prefix='.publishing-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        os.link(temporary, path)  # Atomic exclusive link; FileExistsError never overwrites.
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        os.unlink(temporary)  # Only this newly created temporary metadata file.


@contextmanager
def locked(out):
    control = out/'execution_resume'
    require(not control.is_symlink(), 'Resume metadata directory cannot be a symlink')
    control.mkdir(exist_ok=True)
    path = control/'controller.lock'
    require(not path.is_symlink(), 'Controller lock cannot be a symlink')
    with path.open('a+') as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ResumeError('Another resume controller holds the run lock')
        try:
            yield control
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def checked_path(root, relative):
    require(isinstance(relative, str) and not Path(relative).is_absolute(), 'Closure paths must be relative')
    path = (root/relative).resolve()
    require(path.is_relative_to(root), 'Closure path escapes workspace')
    require(path.is_file(), 'Missing frozen dependency: '+relative)
    return path


def verify_plan(out, root, expected_sha=None):
    require(out.is_dir() and not out.is_symlink(), 'Existing run directory required')
    require(not (out/'results.json').exists(), 'Top-level results already exist; no resume or overwrite')
    require(not (out/'failed_case.json').exists(), 'A failed-case record requires separate operator review')
    path = out/'plan.json'
    digest = sha(path)
    if expected_sha is not None: require(digest == expected_sha, 'Frozen plan SHA changed')
    plan = read(path)
    require(plan.get('attempt') == ATTEMPT and plan.get('case_order') == EXPECTED_NAMES,
            'Only the exact reviewed V13 attempt and case order can resume')
    require(plan.get('scope') == 'all' and plan.get('limit_cases') == 19 and plan.get('expected_cases') == 19,
            'The original all19 scope must remain unchanged')
    require(plan.get('development_only') is True and plan.get('fresh_validation') is False,
            'Only disclosed development scope supported')
    require(plan.get('resource_execution', {}).get('minimum_free_disk_bytes') == MIN_FREE_BYTES,
            'The original1GiB resource guard cannot change')
    for group in ('code_sha256', 'input_sha256'):
        records = plan.get(group)
        require(isinstance(records, dict) and bool(records), 'Nonempty original closure required: '+group)
        for relative, expected in records.items():
            require(isinstance(expected, str) and len(expected) == 64 and all(c in '0123456789abcdef' for c in expected),
                    'Invalid frozen dependency SHA')
            require(sha(checked_path(root, relative)) == expected, 'Frozen dependency changed: '+relative)
            if group == 'code_sha256':
                snapshot = (out/'source'/relative).resolve()
                require(snapshot.is_relative_to(out/'source') and snapshot.is_file(), 'Missing frozen source snapshot: '+relative)
                require(sha(snapshot) == expected, 'Source snapshot changed: '+relative)
    require(environment() == plan.get('environment'), 'Python/library versions differ from original training environment')
    return plan, digest


def inventory(out, plan_sha):
    """Only JSON metadata and SHA byte streams; no CSV decode or unpickle."""
    allowed = set(EXPECTED_NAMES) | {'plan.json', 'source', 'execution_resume'}
    require(not (set(p.name for p in out.iterdir())-allowed), 'Unknown run entry; refusing automatic adoption')
    complete, gap_seen = {}, False
    for name in EXPECTED_NAMES:
        folder = out/name
        if not folder.exists():
            gap_seen = True
            continue
        require(not gap_seen, 'Existing cases are not a completed chronological prefix')
        require(folder.is_dir() and not folder.is_symlink(), 'Case must be an ordinary directory: '+name)
        require(set(p.name for p in folder.iterdir()) == set(ARTIFACTS), 'Partial or unexpected case files: '+name)
        require(all((folder/f).is_file() and not (folder/f).is_symlink() for f in ARTIFACTS), 'Case artifact symlinks are not supported')
        hashes = {filename: sha(folder/filename) for filename in ARTIFACTS}
        freeze, result = read(folder/'freeze.json'), read(folder/'results.json')
        require(freeze.get('plan_sha256') == plan_sha, 'Case links to a different frozen plan: '+name)
        require(freeze.get('bundle_sha256') == hashes['bundle.joblib'], 'Case bundle differs from its freeze: '+name)
        require(result.get('case') == name and result.get('development_only') is True,
                'Case result identity/development scope differs: '+name)
        complete[name] = hashes
    return complete


def check_space(out):
    free = shutil.disk_usage(out).free
    if free < MIN_FREE_BYTES:
        raise ResourcePause(f'Original1GiB reserve reached: {free} bytes free; no case started')
    return free


def prepare(out, *, root=ROOT):
    """Seal the original12-case prefix only. Does not call production code."""
    out, root = Path(out).resolve(), Path(root).resolve()
    with locked(out) as control:
        require(not (control/'checkpoint.json').exists(), 'Checkpoint already exists; it is immutable')
        require(not list(control.glob('case_*.json')), 'Receipts cannot precede the checkpoint')
        plan, digest = verify_plan(out, root)
        completed = inventory(out, digest)
        require(list(completed) == EXPECTED_NAMES[:12], 'Preparation requires exactly the original12 complete cases')
        checkpoint = {'schema_version': 1, 'prepared_at_utc': now(), 'operation': 'resource_only_resume',
            'root': str(root), 'output': str(out), 'plan_sha256': digest,
            'controller_sha256': controller_hashes(), 'python_executable': os.path.abspath(sys.executable),
            'environment': environment(), 'child_thread_environment': THREAD_ENV,
            'mkl_thread_environment': 'unset, matching original command',
            'initial_completed_cases': completed, 'initial_complete_count': 12,
            'missing_cases': EXPECTED_NAMES[12:], 'expected_cases': 19,
            'original_minimum_free_disk_bytes': MIN_FREE_BYTES,
            'statistical_method_changed': False, 'existing_artifacts_will_not_be_overwritten': True,
            'prepare_source_access': 'SHA256 byte streams and JSON metadata only; no sensor/label CSV parsing or model unpickling'}
        path = control/'checkpoint.json'; atomic_new_json(path, checkpoint)
        return {'prepared': True, 'checkpoint': str(path), 'checkpoint_sha256': sha(path),
                'completed_cases': 12, 'missing_cases': EXPECTED_NAMES[12:]}


def receipt_path(control, index, name):
    return control/f'case_{index+1:02d}_{name}.json'


def verified_prefix(out, control, checkpoint, checkpoint_sha):
    initial = checkpoint['initial_completed_cases']
    require(list(initial) == EXPECTED_NAMES[:12], 'Checkpoint initial prefix changed')
    recorded = dict(initial); receipts = {}
    stopped = False
    expected_receipts = {receipt_path(control, i, name).name for i, name in enumerate(EXPECTED_NAMES) if i >= 12}
    require(not (set(p.name for p in control.glob('case_*.json'))-expected_receipts), 'Unknown case receipt')
    for index, name in enumerate(EXPECTED_NAMES[12:], 12):
        path = receipt_path(control, index, name)
        if not path.exists(): stopped = True; continue
        require(not stopped and not path.is_symlink(), 'Resume receipts are not a chronological ordinary-file prefix')
        receipt = read(path)
        require(receipt.get('case') == name and receipt.get('checkpoint_sha256') == checkpoint_sha
                and receipt.get('plan_sha256') == checkpoint['plan_sha256']
                and receipt.get('controller_sha256') == checkpoint['controller_sha256']
                and receipt.get('child_returncode') == 0, 'Resume receipt provenance changed: '+name)
        require(set(receipt.get('artifact_sha256', {})) == set(ARTIFACTS), 'Incomplete receipt hashes: '+name)
        recorded[name] = receipt['artifact_sha256']; receipts[name] = sha(path)
    current = inventory(out, checkpoint['plan_sha256'])
    require(list(current) == list(recorded), 'Unreceipted/partial/unexpected case exists; no rerun or automatic adoption')
    require(current == recorded, 'A previously committed case artifact changed')
    return current, receipts


def _run_child(name, out, root, log):
    env = os.environ.copy(); env.update(THREAD_ENV); env.pop('MKL_NUM_THREADS', None)
    command = [sys.executable, '-B', '-m', 'ml.gecco_v13.development', '--output', str(out), '--case', name]
    result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    log.flush(); os.fsync(log.fileno())
    return result.returncode


def _load_production(root):
    if str(root) not in sys.path: sys.path.insert(0, str(root))
    from ml.gecco_v13 import development
    require(Path(development.__file__).resolve() == root/'ml/gecco_v13/development.py', 'Unexpected production module location')
    require(development.EXPECTED_NAMES == EXPECTED_NAMES and development.MIN_FREE_BYTES == MIN_FREE_BYTES,
            'Unexpected production order/resource contract')
    return development


def aggregate(out, root, execution_resume):
    """Exact frozen final schema + execution provenance; only after all19."""
    import numpy as np
    import pandas as pd
    production = _load_production(root)
    periods, source_rows = [], {}
    for name in EXPECTED_NAMES:
        result = read(out/name/'results.json')
        require(result['case'] == name, 'Case identity changed before aggregation')
        rows = pd.read_csv(out/name/'predictions.csv.gz', float_precision='round_trip')
        periods.append(result); source_rows.setdefault(result['source'], []).append(rows)
    sources = {}
    for name, parts in source_rows.items():
        whole = pd.concat(parts, ignore_index=True)
        require(bool(np.all(np.diff(whole.sample_index) == 1)), 'Original pooled source axis is not contiguous')
        sources[name] = production.assess(*(whole[c].to_numpy(np.int8) for c in ('label', 'baseline', 'reference', 'candidate')))
    return {'completed_at_utc': now(), 'development_only': True, 'fresh_validation': False,
        'candidate_version': 'V13', 'complete_cases': len(periods), 'expected_cases': 19,
        'all_prespecified_cases_complete': len(periods) == 19, 'maximum_allowed_extra_delay_seconds': 120,
        'historical_retention_required': True, 'v8_user_objective_required': True,
        'acceptance_evaluation_pending_independent_audit_and_historical_comparison': True,
        'periods': periods, 'sources': sources, 'summary': production.summarize(periods, sources),
        'execution_resume': execution_resume}


def resume(out, checkpoint_sha256, *, root=ROOT):
    out, root = Path(out).resolve(), Path(root).resolve()
    with locked(out) as control:
        path = control/'checkpoint.json'
        require(sha(path) == checkpoint_sha256, 'Checkpoint SHA differs from the externally pinned preparation digest')
        checkpoint = read(path)
        require(checkpoint.get('output') == str(out) and checkpoint.get('root') == str(root), 'Checkpoint run/workspace differs')
        require(checkpoint.get('controller_sha256') == controller_hashes(), 'Resume controller changed after checkpoint')
        require(checkpoint.get('python_executable') == os.path.abspath(sys.executable), 'Use the same qualified Python executable')
        require(checkpoint.get('environment') == environment(), 'Resume library versions changed')
        require(checkpoint.get('child_thread_environment') == THREAD_ENV, 'Original child thread settings changed')
        verify_plan(out, root, checkpoint['plan_sha256'])
        completed, receipts = verified_prefix(out, control, checkpoint, checkpoint_sha256)
        log_path = control/('resume_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex+'.log')
        with log_path.open('x', encoding='utf-8', buffering=1) as log:
            log.write(json.dumps({'started_at_utc': now(), 'checkpoint_sha256': checkpoint_sha256,
                'already_complete': list(completed), 'remaining': EXPECTED_NAMES[len(completed):],
                'minimum_free_disk_bytes': MIN_FREE_BYTES, 'thread_environment': THREAD_ENV})+'\n')
            for index, name in enumerate(EXPECTED_NAMES[len(completed):], len(completed)):
                check_space(out)
                require(controller_hashes() == checkpoint['controller_sha256'], 'Controller changed during execution')
                verify_plan(out, root, checkpoint['plan_sha256'])
                verified_prefix(out, control, checkpoint, checkpoint_sha256)
                require(not (out/name).exists(), 'Never overwrite an existing case: '+name)
                log.write(json.dumps({'case': name, 'phase': 'invoke_unchanged_production', 'at_utc': now()})+'\n')
                code = _run_child(name, out, root, log)
                require(code == 0, f'Child {name} exited{code}; no top-level completion, no automatic rerun')
                require(controller_hashes() == checkpoint['controller_sha256'], 'Controller changed during execution')
                verify_plan(out, root, checkpoint['plan_sha256'])
                current = inventory(out, checkpoint['plan_sha256'])
                require(list(current) == EXPECTED_NAMES[:index+1], 'Child completed an unexpected scope')
                require(all(current[key] == value for key, value in completed.items()), 'Child modified earlier committed artifacts')
                receipt = {'case': name, 'completed_at_utc': now(), 'child_returncode': 0,
                    'checkpoint_sha256': checkpoint_sha256, 'plan_sha256': checkpoint['plan_sha256'],
                    'controller_sha256': checkpoint['controller_sha256'], 'artifact_sha256': current[name],
                    'resume_log': str(log_path.relative_to(out)), 'thread_environment': THREAD_ENV}
                atomic_new_json(receipt_path(control, index, name), receipt)
                completed, receipts = verified_prefix(out, control, checkpoint, checkpoint_sha256)
            require(list(completed) == EXPECTED_NAMES, 'All19 cases required before aggregation')
            check_space(out)
            execution = {'operation': 'resource_only_resume', 'checkpoint_sha256': checkpoint_sha256,
                'checkpoint': str(path.relative_to(out)), 'original_plan_sha256': checkpoint['plan_sha256'],
                'controller_sha256': checkpoint['controller_sha256'], 'initial_preserved_cases': EXPECTED_NAMES[:12],
                'resumed_case_receipt_sha256': receipts, 'new_resume_logs': sorted(p.name for p in control.glob('resume_*.log')),
                'original_method_and_acceptance_unchanged': True, 'existing_case_artifacts_unchanged': True,
                'original_log_preserved': True, 'thread_environment': THREAD_ENV, 'environment': environment()}
            result = aggregate(out, root, execution)
            verify_plan(out, root, checkpoint['plan_sha256'])
            verified_prefix(out, control, checkpoint, checkpoint_sha256)
            require(controller_hashes() == checkpoint['controller_sha256'], 'Controller changed during execution')
            atomic_new_json(out/'results.json', result)
            log.write(json.dumps({'completed_at_utc': now(), 'all19_complete': True, 'results_sha256': sha(out/'results.json')})+'\n')
            log.flush(); os.fsync(log.fileno())
        return {'complete_cases': 19, 'results_sha256': sha(out/'results.json'), 'results': str(out/'results.json'),
                'model_acceptance': 'Not asserted; unchanged independent audit and all statistical gates still required'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare', action='store_true'); modes.add_argument('--resume', action='store_true')
    parser.add_argument('--checkpoint-sha256')
    args = parser.parse_args(argv)
    if args.resume and not args.checkpoint_sha256: parser.error('--resume requires the digest returned by --prepare')
    if args.prepare and args.checkpoint_sha256: parser.error('--checkpoint-sha256 is only for --resume')
    try:
        result = prepare(args.output) if args.prepare else resume(args.output, args.checkpoint_sha256)
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (ResumeError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'complete': False, 'error': type(error).__name__, 'message': str(error),
                          'evidence_preserved': True}, ensure_ascii=False), file=sys.stderr)
        return 75 if isinstance(error, ResourcePause) else 1


if __name__ == '__main__': raise SystemExit(main())
