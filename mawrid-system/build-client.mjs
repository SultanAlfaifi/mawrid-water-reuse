#!/usr/bin/env node
// Build a single classic deferred entry while retaining the original ES-module
// source files for development and tests. No installs, serving, or publication.
import {build} from '../mawrid-final/node_modules/vite/dist/node/index.js';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const here=path.dirname(fileURLToPath(import.meta.url)),root=path.dirname(here),client=path.join(here,'client');
const entry=path.join(client,'app.js'),htmlPath=path.join(client,'index.html');
const relative=file=>path.relative(root,file).split(path.sep).join('/');
const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const fileHash=async file=>digest(await fs.readFile(file));
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);

async function sourceClosure(file,found=new Map()){
  const resolved=await fs.realpath(file);
  if(!resolved.startsWith(client+path.sep)||!resolved.endsWith('.js'))throw Error('Only local client JavaScript imports are supported: '+relative(resolved));
  if(found.has(resolved))return found;
  const bytes=await fs.readFile(resolved),source=bytes.toString('utf8');found.set(resolved,digest(bytes));
  if(/\bimport\s*\(/.test(source))throw Error('Dynamic imports need a new closure audit: '+relative(resolved));
  const imports=/^\s*(?:import\s+(?:[^'";\n]+?\s+from\s*)?|export\s+[^'";\n]*?\s+from\s*)['"]([^'"]+)['"]/gm;
  for(const match of source.matchAll(imports)){
    if(!match[1].startsWith('./')&&!match[1].startsWith('../'))throw Error('Non-local import is outside this client build: '+match[1]);
    await sourceClosure(path.resolve(path.dirname(resolved),match[1]),found);
  }
  return found;
}
function snapshotMap(closure){return Object.fromEntries([...closure].sort(([a],[b])=>a.localeCompare(b)).map(([file,hash])=>[relative(file),hash]));}
async function atomicWrite(file,bytes){
  const temporary=file+'.tmp-'+process.pid+'-'+crypto.randomBytes(5).toString('hex');
  try{await fs.writeFile(temporary,bytes,{flag:'wx'});await fs.rename(temporary,file);}
  finally{await fs.rm(temporary,{force:true});}
}

const args=process.argv.slice(2);
if(args.length!==2||args[0]!=='--proof'||!args[1]){
  console.error('Usage: node mawrid-system/build-client.mjs --proof output/mawrid-system/ux-v8/client-build-r1.json');process.exit(2);
}
const proofPath=path.resolve(root,args[1]);
await fs.mkdir(path.dirname(proofPath),{recursive:true});
// Exclusive reservation prevents accidental replacement of a prior receipt.
const reservation=await fs.open(proofPath,'wx');
await reservation.writeFile(JSON.stringify({status:'RUNNING',created_at_utc:new Date().toISOString()})+'\n');await reservation.close();
const record={schema_version:1,status:'FAIL',created_at_utc:new Date().toISOString(),
  scope:'Single classic IIFE client entry, exact local source closure and static HTML integration. Browser behavior and application tests are verified separately.',
  node_version:process.version,external_assets_or_installs:false,browser_verified:false,
  source_js_changed:false,other_assets_removed:false,physical_hardware_connected:false,model_injected_or_promoted:false};
let exitCode=1;
try{
  const before=await sourceClosure(entry),scriptPath=fileURLToPath(import.meta.url);
  record.source_sha256_before=snapshotMap(before);record.build_script_sha256_before=await fileHash(scriptPath);
  const htmlBefore=await fs.readFile(htmlPath,'utf8');record.index_html_sha256_before=digest(htmlBefore);
  const backupPath=proofPath+'.index-before.html';await fs.writeFile(backupPath,htmlBefore,{flag:'wx'});
  record.index_html_before_backup={path:relative(backupPath),sha256:digest(htmlBefore)};
  const vitePackage=JSON.parse(await fs.readFile(path.join(root,'mawrid-final/node_modules/vite/package.json'),'utf8'));
  const rolldownPackage=JSON.parse(await fs.readFile(path.join(root,'mawrid-final/node_modules/rolldown/package.json'),'utf8'));
  record.local_dependency_versions={vite:vitePackage.version,rolldown:rolldownPackage.version};
  const result=await build({configFile:false,envDir:false,envFile:false,root:client,publicDir:false,logLevel:'warn',
    build:{write:false,emptyOutDir:false,target:'es2022',minify:false,sourcemap:false,reportCompressedSize:false,
      lib:{entry,name:'MawridUI',formats:['iife'],fileName:()=> 'mawrid-ui.js'}}});
  const outputs=(Array.isArray(result)?result:[result]).flatMap(item=>item.output??[]);
  if(outputs.length!==1||outputs[0].type!=='chunk'||!outputs[0].isEntry)throw Error('Expected exactly one entry chunk and no extra assets');
  const chunk=outputs[0];
  if(chunk.imports.length||chunk.dynamicImports.length)throw Error('The classic entry must not load JavaScript modules');
  const actualModules=Object.keys(chunk.modules).filter(id=>!id.startsWith('\0')).map(id=>path.resolve(id)).sort();
  const expectedModules=[...before.keys()].sort();
  record.bundled_module_ids=actualModules.map(relative);
  if(!same(actualModules,expectedModules))throw Error('Bundler module graph differs from the audited source closure');
  // A Script parse rejects import/export/top-level-await module syntax.
  new vm.Script(chunk.code,{filename:'mawrid-ui.classic.js'});
  const after=await sourceClosure(entry);record.source_sha256_after=snapshotMap(after);record.build_script_sha256_after=await fileHash(scriptPath);
  record.source_and_build_script_unchanged_during_build=same(record.source_sha256_before,record.source_sha256_after)&&record.build_script_sha256_before===record.build_script_sha256_after;
  if(!record.source_and_build_script_unchanged_during_build)throw Error('Sources changed during the build; no entry was installed');
  const bytes=Buffer.from(chunk.code,'utf8'),hash=digest(bytes),fileName='mawrid-ui-'+hash.slice(0,12)+'.js',assetPath=path.join(client,'assets',fileName);
  const entryScript=/<script\b(?=[^>]*(?:\bid\s*=\s*["']mawrid-entry["']|\bsrc\s*=\s*["']\.\/app\.js(?:\?[^"']*)?["']))[^>]*>\s*<\/script>/g;
  const matches=[...htmlBefore.matchAll(entryScript)];
  if(matches.length!==1)throw Error('Expected exactly one app.js or mawrid-entry script in index.html');
  const htmlAfter=htmlBefore.replace(entryScript,'<script id="mawrid-entry" defer src="./assets/'+fileName+'"></script>');
  if(await fs.readFile(htmlPath,'utf8')!==htmlBefore)throw Error('index.html changed during build; no entry was installed');
  await fs.mkdir(path.dirname(assetPath),{recursive:true});
  try{if(await fileHash(assetPath)!==hash)throw Error('Content-hash filename collision; refusing to replace an existing asset');}
  catch(error){if(error.code==='ENOENT')await atomicWrite(assetPath,bytes);else throw error;}
  record.compiled_file={path:relative(assetPath),sha256:hash,bytes:bytes.length,format:'iife',classic_script_parse:'PASS',external_imports:[],dynamic_imports:[]};
  await atomicWrite(htmlPath,htmlAfter);
  record.index_html_sha256_after=await fileHash(htmlPath);record.entry_script='<script id="mawrid-entry" defer src="./assets/'+fileName+'"></script>';
  record.source_sha256_final=snapshotMap(await sourceClosure(entry));
  if(!same(record.source_sha256_before,record.source_sha256_final)||record.index_html_sha256_after!==digest(htmlAfter)||await fileHash(assetPath)!==hash)throw Error('Final installed bytes do not match the audited build');
  record.status='PASS';exitCode=0;
}catch(error){record.error={name:error.name,message:error.message};}
record.finished_at_utc=new Date().toISOString();
await atomicWrite(proofPath,JSON.stringify(record,null,2)+'\n');
console.log(JSON.stringify({status:record.status,proof:relative(proofPath),proof_sha256:await fileHash(proofPath),source_files:Object.keys(record.source_sha256_before??{}).length,compiled_file:record.compiled_file??null,error:record.error??null}));
process.exitCode=exitCode;
