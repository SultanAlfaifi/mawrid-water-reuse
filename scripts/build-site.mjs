import { spawnSync } from 'node:child_process';
import { cp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const built = path.join(root, '.site-build');
if (path.relative(root, built) !== '.site-build') throw new Error('Unexpected temporary build destination');
// Clean this generated folder explicitly so earlier hashed bundles never enter
// the published copy, regardless of the bundler's cleanup behavior.
await rm(built, { recursive: true, force: true });
const result = spawnSync(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'), 'build'], {
  cwd: root, stdio: 'inherit'
});
if (result.status !== 0) process.exit(result.status ?? 1);
// assets/app is exclusively generated output. Validate the absolute target before
// replacing old hashes, then write the new index after its dependencies exist.
const appOutput = path.resolve(root, 'assets/app');
if (path.relative(root, appOutput).replaceAll('\\', '/') !== 'assets/app') throw new Error('Unexpected build destination');
console.log('Replacing generated assets only: ' + appOutput);
await rm(appOutput, { recursive: true, force: true });
await mkdir(appOutput, { recursive: true });
await cp(path.join(built, 'assets/app'), appOutput, { recursive: true });
await writeFile(path.join(root, 'index.html'), await readFile(path.join(built, 'index.html')));
await mkdir(path.join(root, 'simulator'), { recursive: true });
await writeFile(path.join(root, 'simulator/index.html'), await readFile(path.join(built, 'simulator/index.html')));
console.log('Static site ready at index.html and simulator/index.html; sources are in web/.');
