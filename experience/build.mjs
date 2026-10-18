// Uses already installed locked dependencies; never installs or downloads.
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {cp, mkdir, readFile, writeFile, rm} from 'node:fs/promises';
const here = fileURLToPath(new URL('.',import.meta.url));
const dependencies = path.resolve(process.argv[2] || path.join(here,'../node_modules'));
const three = path.join(dependencies,'three');
const temporary = path.resolve(here,'.build');
const outputAssets = path.resolve(here,'assets');
if (path.relative(here,temporary) !== '.build' || path.relative(here,outputAssets) !== 'assets') throw new Error('Unexpected generated output path');
const {build} = await import(pathToFileURL(path.join(dependencies,'vite/dist/node/index.js')).href);
await build({configFile:false,root:path.join(here,'src'),base:'./',publicDir:false,resolve:{alias:[
  {find:'../../mawrid-final/node_modules/three/build/three.module.js',replacement:path.join(three,'build/three.module.js')},
  {find:/^three\/addons\/(.*)/,replacement:path.join(three,'examples/jsm/')+'$1'},
  {find:/^three$/,replacement:path.join(three,'build/three.module.js')},
]},build:{modulePreload:{polyfill:false},outDir:temporary,emptyOutDir:true,assetsDir:'assets',assetsInlineLimit:0,rolldownOptions:{output:{codeSplitting:{groups:[{name:'three',test:/node_modules\/three/}]}}}}});
// Only these checked generated destinations are replaced. Sources and original
// scene/backend/evidence never enter a recursive mutation.
await rm(outputAssets,{recursive:true,force:true});
await mkdir(outputAssets,{recursive:true});
await cp(path.join(temporary,'assets'),outputAssets,{recursive:true});
await writeFile(path.join(here,'index.html'),await readFile(path.join(temporary,'index.html')));
await rm(temporary,{recursive:true,force:true});
