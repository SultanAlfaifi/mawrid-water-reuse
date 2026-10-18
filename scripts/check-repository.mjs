import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const tracked = execFileSync('git', ['ls-files', '-z'], { cwd: root, encoding: 'utf8' }).split('\0').filter(Boolean);
const trackedSet = new Set(tracked);
const sha256 = p => createHash('sha256').update(readFileSync(path.join(root, p))).digest('hex');
const json = p => JSON.parse(readFileSync(path.join(root, p), 'utf8'));
const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

for (const p of tracked) {
  check(!/(^|\/)(node_modules|\.venv|__pycache__|var)(\/|$)/.test(p), `Runtime directory is versioned: ${p}`);
  check(!/\.(sqlite3|db|joblib|npz|pyc)(?:-|$)/.test(p), `Runtime/data artifact is versioned: ${p}`);
  check(!p.startsWith('data/external/'), `External raw data is versioned: ${p}`);
  check(statSync(path.join(root, p)).size <= 50 * 1024 ** 2, `File exceeds the repository's 50 MiB review limit: ${p}`);
}

for (const p of json('scripts/ml-publication-files.json').files) {
  check(p.startsWith('output/ml/') && trackedSet.has(p), `Curated research evidence missing from Git: ${p}`);
}

const clientProof = json('output/mawrid-system/ux-v8/client-build-r1.json');
const sceneProof = json('output/mawrid-system/ux-v8/plant3d-build-r1.json');
for (const [label, hashes] of [
  ['client source', clientProof.source_sha256_final],
  ['3D source', sceneProof.source_sha256_after],
  ['3D asset', sceneProof.artifact_sha256],
]) {
  for (const [p, expected] of Object.entries(hashes)) {
    check(trackedSet.has(p) && sha256(p) === expected, `Delivered ${label} differs from its build proof: ${p}`);
  }
}
check(sha256(clientProof.compiled_file.path) === clientProof.compiled_file.sha256, 'Client bundle differs from its proof');
check(sha256('mawrid-system/client/index.html') === clientProof.index_html_sha256_after, 'Client entry differs from its proof');

// Check the maintained entry-point documents. Frozen research snapshots and
// historical HTML reports retain deliberate links to separately archived data.
const docs = tracked.filter(p => p.endsWith('.md') && (
  !p.includes('/') || p.startsWith('docs/') || p === 'data/README.md' ||
  p === 'ml/README.md' || p === 'mawrid-system/README.md' ||
  p === 'mawrid-system/edge/README.md' || p === 'mawrid-final/README.md'
));
let links = 0;
for (const p of docs) {
  const source = readFileSync(path.join(root, p), 'utf8');
  for (const match of source.matchAll(/!?\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\)/g)) {
    const url = match[1] ?? match[2];
    if (/^(?:[a-z][a-z\d+.-]*:|#|\/)/i.test(url)) continue;
    const target = decodeURIComponent(url.split(/[?#]/, 1)[0]);
    const relative = path.posix.normalize(path.posix.join(path.posix.dirname(p), target));
    links++;
    check(trackedSet.has(relative) || tracked.some(item => item.startsWith(relative.replace(/\/$/, '') + '/')),
      `Local documentation link is not included in Git: ${p} -> ${target}`);
  }
}

assert.equal(failures.length, 0, failures.join('\n'));
console.log(`Repository checks PASS: ${tracked.length} tracked files, ${links} local documentation links, curated ML evidence and delivered client/3D hashes. No model loading or field-validation claim.`);
