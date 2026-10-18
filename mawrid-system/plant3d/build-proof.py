"""Build only the isolated local viewer and bind its bytes to their source."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARTIFACTS = ROOT / 'mawrid-system/client/plant3d'
PROOF = ROOT / 'output/mawrid-system/plant3d-build-v4.json'
DEPENDENCIES = [ROOT / 'mawrid-final/node_modules' / name for name in
                ('three', 'vite', '@fontsource/ibm-plex-sans-arabic')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(roots):
    return {str(p.relative_to(ROOT)): digest(p)
            for folder in roots for p in ([folder] if folder.is_file() else sorted(folder.rglob('*')))
            if p.is_file() and '__pycache__' not in p.parts}


def run(argv):
    p = subprocess.run(argv, cwd=HERE, capture_output=True, text=True)
    return {'argv': argv, 'cwd': str(HERE), 'exit_code': p.returncode,
            'stdout': p.stdout, 'stderr': p.stderr}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--proof',default=str(PROOF))
    parser.add_argument('--previous-proof')
    args=parser.parse_args()
    proof=Path(args.proof)
    if not proof.is_absolute(): proof=ROOT/proof
    if proof.exists(): raise FileExistsError('Preserve existing build proof; choose a new --proof path')
    previous=Path(args.previous_proof) if args.previous_proof else None
    if previous is not None and not previous.is_absolute(): previous=ROOT/previous
    source_before = snapshot([HERE,ROOT / 'mawrid-system/client/guide-content.js'])
    # Includes complete package files as a conservative superset of the actual
    # local Three/font imports. No old scene geometry/material helper is used.
    dependencies_before = snapshot(DEPENDENCIES)
    tests = run(['node', '--test', *[p.name for p in sorted(HERE.glob('test-*.mjs'))]])
    command = ['node', '../../mawrid-final/node_modules/vite/bin/vite.js',
               'build', '--config', 'vite.config.mjs']
    build = run(command) if tests['exit_code'] == 0 else None
    source_after, dependencies_after = snapshot([HERE,ROOT / 'mawrid-system/client/guide-content.js']), snapshot(DEPENDENCIES)
    stable = source_before == source_after and dependencies_before == dependencies_after
    passed = tests['exit_code'] == 0 and build is not None and build['exit_code'] == 0 and stable
    record = {'schema_version': 1, 'status': 'PASS' if passed else 'FAIL',
              'scope': 'Isolated operational virtual 3D viewer: source, synthetic tests and static build only. Browser and HTTP integration are separate checks.',
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'source_sha256_before': source_before, 'source_sha256_after': source_after,
              'local_vendor_sha256_before': dependencies_before, 'local_vendor_sha256_after': dependencies_after,
              'source_and_vendor_unchanged_during_build': stable,
              'previous_build_proof': {'path':str(previous),'sha256':digest(previous)} if previous else None,
              'old_engineering_geometry_helpers_imported': [],
              'node_version': run(['node', '--version'])['stdout'].strip(),
              'local_dependency_versions': {p.name: json.loads((p/'package.json').read_text())['version'] for p in DEPENDENCIES},
              'tests': tests, 'build': build,
              'artifact_sha256': snapshot([ARTIFACTS]) if build and build['exit_code'] == 0 else {},
              'browser_verified': False, 'physical_hardware_connected': False,
              'model_injected_or_promoted': False, 'external_assets_or_installs': False}
    proof.parent.mkdir(parents=True, exist_ok=True)
    proof.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'status': record['status'], 'proof': str(proof),
                      'proof_sha256': digest(proof), 'source_files': len(source_before),
                      'vendor_files': len(dependencies_before), 'artifacts': len(record['artifact_sha256']),
                      'build': build}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
