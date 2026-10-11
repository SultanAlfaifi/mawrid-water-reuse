"""Package approved identity outputs only, preserving guide-relative paths."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/brand'
OUT.mkdir(parents=True, exist_ok=True)
files = set()
for folder in ['assets/brand', 'assets/fonts', 'assets/social', 'assets/diagrams', 'scripts/brand', 'docs', 'references']:
    files.update(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
for scene in ['ablution', 'concept', 'testing', 'irrigation', 'maintenance']:
    files.update(p for p in (ROOT / 'assets/images').glob(f'campus-{scene}.*') if p.is_file())
files.update([ROOT/'DESIGN.md', ROOT/'output/pdf/mawrid-brand-book.pdf'])
entries = [{'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size,
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
           for p in sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())]
manifest = {'name': 'MAWRID identity kit', 'version': '1.0', 'entry': 'assets/brand/guide/index.html',
            'files_count': len(entries), 'files': entries}
manifest_bytes=(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
(OUT/'manifest.json').write_bytes(manifest_bytes)
readme='''# مورد — حزمة الهوية 1.0

ابدأ بفتح assets/brand/guide/index.html، أو output/pdf/mawrid-brand-book.pdf.
القوالب والشعار في assets/brand/؛ العرض القابل للتحرير في assets/brand/templates/mawrid-presentation.pptx.
الخطوط وتراخيصها في assets/fonts/. ثبت الخطين على جهاز التحرير للحفاظ على مظهر العرض.
تفاصيل الطباعة والتحرير وإعادة التوليد في assets/brand/README.md.
الصور تصورات مولدة؛ غير منفذة. المعالجة والري يحتاجان اختبارًا وقياسات مستقلة.
هذه حزمة أصول الهوية؛ وثائق السياق المرفقة ليست نسخة كاملة من موقع المشروع أو مستودعه.
'''
archive=OUT/'mawrid-identity-kit.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    z.writestr('START-HERE.md', readme.encode('utf-8'))
    z.writestr('manifest.json', manifest_bytes)
    for p in sorted(files, key=lambda p: p.relative_to(ROOT).as_posix()):
        z.write(p, p.relative_to(ROOT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None, 'Archive CRC verification failed'
    for entry in entries:
        assert hashlib.sha256(z.read(entry['path'])).hexdigest() == entry['sha256'], entry['path']
print(json.dumps({'archive':str(archive),'files':len(entries)+2,'bytes':archive.stat().st_size,'verified':True},ensure_ascii=False))
