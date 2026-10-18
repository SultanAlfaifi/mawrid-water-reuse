"""Bundle reproducible experiments without environments, caches or nested ZIPs."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/ml/gecco-v4'

def main():
    audit=json.loads((OUT/'final_audit.json').read_text())
    assert not audit.get('findings'), 'Resolve audit findings before packaging'
    sources=[ROOT/'ml'/name for name in ['gecco_baseline','gecco_v2','gecco_v3','gecco_v4']]
    sources += [p for p in (ROOT/'output/ml').glob('gecco*') if p.is_dir()]
    sources += [ROOT/'data/external'/f'gecco{year}' for year in ['2017','2018','2019']]
    paths=set()
    manifest=OUT/'package_manifest.json'
    for parent in sources:
        for path in parent.rglob('*'):
            if not path.is_file() or path==manifest:continue
            if any(part in {'.venv','__pycache__','.git'} for part in path.parts):continue
            if path.suffix in {'.pyc','.zip'} or path.name=='.DS_Store':continue
            paths.add(path)
    paths.update([ROOT/'docs/data-and-model-card.md',ROOT/'data/README.md'])
    records={str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths)}
    content={'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'scope':'V4 plus original frozen baseline/v2/v3 evidence and public sources; preserves negative outcomes',
        'model_status':'NOT_PROMOTED','files':records,
        'excluded':['virtual environments','bytecode caches','nested ZIP archives'],
        'note':'Earlier manifests describe their original prior packages. This manifest describes this new package.'}
    manifest.write_text(json.dumps(content,indent=2,ensure_ascii=False)+'\n')
    paths.add(manifest)
    destination=ROOT/'output/ml/mawrid-ai-v4-evaluation.zip'
    assert not destination.exists(), 'Preserve existing package'
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in sorted(paths):archive.write(p,p.relative_to(ROOT))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for name,entry in records.items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==entry['sha256']
    summary={'archive':str(destination.relative_to(ROOT)),'files':len(paths),'bytes':destination.stat().st_size,
             'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'integrity_check':'PASS',
             'every_manifest_entry_verified_from_zip':True}
    (OUT/'package_verification.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
