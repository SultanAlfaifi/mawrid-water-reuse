import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { C, root, svgText, textWidth, logoAt, svgWrap } from './shared.mjs';

const runtime = process.env.MAWRID_NODE_MODULES || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const sharp = createRequire(path.join(runtime, 'runtime.cjs'))('sharp');
const W = 1280, H = 680;
const rect = (x, y, w, h, fill, extra = '') => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" ${extra}/>`;
const text = (value, x, y, size, color = C.forest, weight = 400) => svgText(value, x, y, size, color, weight, 'en');
const center = (value, cx, y, size, color = C.forest, weight = 400) => text(value, cx - textWidth(value, size, weight, 'en') / 2, y, size, color, weight);
const photo = await sharp(path.join(root, 'assets/images/campus-concept.png'))
  .resize({ width: 1500, withoutEnlargement: true }).jpeg({ quality: 90, mozjpeg: true }).toBuffer();
const bitmap = `data:image/jpeg;base64,${photo.toString('base64')}`;
const icons = {};
for (const name of ['source', 'filter', 'irrigation']) {
  const source = await fs.readFile(path.join(root, 'assets/brand/icons', `${name}.svg`), 'utf8');
  icons[name] = source.match(/<g[\s\S]*<\/g>/)[0];
}
const icon = (name, x, y, size) => `<g transform="translate(${x} ${y}) scale(${size/24})">${icons[name]}</g>`;

const body = [
  '<desc>A proposed campus water reuse concept, shown in the approved bright limestone setting. The photograph is a generated concept, not an installed unit. All typography is outlined Manrope.</desc>',
  '<defs><clipPath id="campus-arch"><path d="M598 636V351A315 315 0 0 1 1228 351V636Z"/></clipPath></defs>',
  rect(0, 0, W, H, C.paper),
  logoAt(64, 73, 348, C.forest, 'en'),
  text('Campus water reuse concept', 64, 236, 17, C.green),
  text('Ablution water,', 64, 306, 40, C.forest, 700),
  text('a resource for irrigation.', 64, 367, 40, C.forest, 700),
  '<path d="M64 410H530" fill="none" stroke="#d1e0d5" stroke-width="1.5"/>',
  icon('source', 68, 479, 52),
  icon('filter', 261, 479, 52),
  icon('irrigation', 455, 479, 52),
  '<path d="M139 505H229m-8-7 8 7-8 7M333 505H423m-8-7 8 7-8 7" fill="none" stroke="#39786a" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
  center('Collect', 94, 578, 18, C.forest, 600),
  center('Treat & verify', 287, 578, 18, C.forest, 600),
  center('Irrigate', 481, 578, 18, C.forest, 600),
  `<image x="598" y="36" width="630" height="600" href="${bitmap}" preserveAspectRatio="xMinYMid slice" clip-path="url(#campus-arch)"/>`,
  rect(974, 595, 238, 29, C.paper, 'opacity=".94"'),
  text('Generated concept; unbuilt', 986, 616, 16, C.green),
].join('');

const svg = svgWrap(W, H, body, 'MAWRID — Ablution water, a resource for irrigation.');
const svgFile = path.join(root, 'assets/brand/readme-cover.svg');
const pngFile = path.join(root, 'assets/brand/readme-cover.png');
await fs.writeFile(svgFile, svg, 'utf8');
await sharp(Buffer.from(svg)).resize({ width: W }).png({ compressionLevel: 9 }).toFile(pngFile);
console.log(JSON.stringify({ svg: 'assets/brand/readme-cover.svg', png: 'assets/brand/readme-cover.png', width: W, height: H, englishOnly: !/[\u0600-\u06ff]/u.test(svg) }, null, 2));
