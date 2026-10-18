"""Package completed V5 evidence without altering any frozen artifacts."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[2]

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):digest.update(part)
    return digest.hexdigest()

def main():
    result=ROOT/'output/ml/gecco-v5-ponds-frozen/results.json'
    if json.loads(result.read_text())['completed_cases']!=24:raise ValueError('Fresh evaluation incomplete')
    extension=ROOT/'output/ml/gecco-v5-ponds-reserved-repaired/results.json'
    if json.loads(extension.read_text())['completed_cases']!=312:raise ValueError('Reserved extension incomplete')
    if not (ROOT/'output/ml/gecco-v5/report.html').is_file():raise ValueError('Report missing')
    paths=[]
    directories=['ml/gecco_v5','output/ml/gecco-v5','output/ml/gecco-v5-supported-development',
        'output/ml/gecco-v5-recovery-development','output/ml/gecco-v5-calibration-development',
        'output/ml/gecco-v5-source-search','output/ml/gecco-v5-ponds-frozen',
        'output/ml/gecco-v5-ponds-reserved-frozen',
        'output/ml/gecco-v5-ponds-reserved-repaired',
        'data/external/gecco2017','data/external/gecco2018','data/external/gecco2019']
    for relative in directories:
        paths.extend(p for p in (ROOT/relative).rglob('*') if p.is_file()
            and '__pycache__' not in p.parts and not p.name.startswith('.')
            and p.name not in ('package_manifest.json','package_verification.json'))
    paths.extend(ROOT/p for p in ['ml/gecco_baseline/metrics.py','ml/gecco_v2/alarm_policy.py',
        'ml/gecco_v2/candidates_supervised.py',
        'output/ml/gecco-v4/external_failure_diagnosis.json',
        'data/external/new_holdout_candidate/eawag_ponds_active_learning/AL_Repo.zip'])
    paths=sorted(set(paths));aliases={};kept=[]
    failed=ROOT/'output/ml/gecco-v5-ponds-reserved-frozen'
    repaired=ROOT/'output/ml/gecco-v5-ponds-reserved-repaired'
    for p in paths:
        if p.name=='bundle.joblib' and p.is_relative_to(failed):
            replacement=repaired/p.relative_to(failed)
            if replacement.is_file() and sha(p)==sha(replacement):
                aliases[str(p.relative_to(ROOT))]={'identical_to':str(replacement.relative_to(ROOT)),'sha256':sha(p)}
                continue
        kept.append(p)
    paths=kept
    manifest={str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in paths}
    manifest_path=ROOT/'output/ml/gecco-v5/package_manifest.json'
    manifest_path.write_text(json.dumps({'files':manifest,'byte_identical_failed_attempt_bundle_aliases':aliases,'scope':'V5 development attempts and frozen Ponds evaluation; retain failures and all source limitations. Byte-identical failed-attempt bundles are stored once under the repaired path; their aliases/hashes are explicit. No deployment model approval implied.'},indent=2)+'\n')
    target=ROOT/'output/ml/mawrid-ai-v5-evaluation.zip'
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in paths+[manifest_path]:archive.write(p,str(p.relative_to(ROOT)))
    verified=0
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:raise ValueError('Archive CRC failed')
        for name,expected in manifest.items():
            digest=hashlib.sha256(archive.read(name)).hexdigest()
            if digest!=expected['sha256']:raise ValueError(f'Archive mismatch: {name}')
            verified+=1
    record={'archive':str(target.relative_to(ROOT)),'bytes':target.stat().st_size,'sha256':sha(target),
        'verified_files':verified,'deduplicated_byte_identical_bundles':len(aliases),'crc_passed':True,'all_content_hashes_passed':True}
    (ROOT/'output/ml/gecco-v5/package_verification.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record))

if __name__=='__main__':main()
