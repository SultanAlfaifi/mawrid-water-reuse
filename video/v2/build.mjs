import path from 'node:path';import {fileURLToPath,pathToFileURL} from 'node:url';
const here=fileURLToPath(new URL('.',import.meta.url)),deps=path.resolve(here,'../../node_modules'),three=path.join(deps,'three');
const {build}=await import(pathToFileURL(path.join(deps,'vite/dist/node/index.js')).href);
await build({configFile:false,root:path.join(here,'src'),base:'./',publicDir:false,resolve:{alias:[{find:'../../mawrid-final/node_modules/three/build/three.module.js',replacement:path.join(three,'build/three.module.js')},{find:/^three\/addons\/(.*)/,replacement:path.join(three,'examples/jsm/')+'$1'},{find:/^three$/,replacement:path.join(three,'build/three.module.js')}]},build:{outDir:path.join(here,'.build'),emptyOutDir:true,assetsDir:'assets',target:'es2022'}});
