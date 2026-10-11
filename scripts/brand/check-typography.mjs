import assert from 'node:assert/strict';
import {getFont,textLayout} from './shared.mjs';

// Mixed-direction labels must keep the Arabic joining of the same isolated
// phrase, and preserve the natural order of Latin identifiers and numbers.
const paths=(text)=>textLayout(text).glyphs.map(g=>g.path);
function containsSequence(haystack,needle){return haystack.some((_,i)=>needle.every((value,j)=>haystack[i+j]===value));}
for(const phrase of ['ربع ارتفاع القطرة.','بكسل للشاشة','قابل للتعديل']){
  assert(containsSequence(paths(`A4 · 24 ${phrase}`),paths(phrase)),`Arabic joining changed: ${phrase}`);
}
for(const [mixed,ltr] of [['ورق A4','A4'],['24 بكسل للشاشة','24'],['بوستر A3','A3'],['قالب PowerPoint قابل للتعديل · 16:9','PowerPoint'],['نصًا أساسيًا 18px.','18px'],['بطاقة الفريق · 90×50 مم','90×50'],['منشور · 1080×1350','1080×1350']]){
  assert(containsSequence(paths(mixed),paths(ltr)),`Latin or numeral order changed: ${mixed}`);
}
assert.deepEqual(textLayout('90×50').glyphs.filter(g=>g.commands.length).map(g=>g.commands),getFont().layout('90×50',[],'latn',undefined,'ltr').glyphs.map(g=>g.path.commands),'Dimensions must read left to right');
const isolatedQaf=getFont().glyphForCodePoint('ق'.codePointAt(0));
assert.notDeepEqual(textLayout('قابل').glyphs.at(-1).commands,isolatedQaf.path.commands,'Qaf must use its connected initial form');
console.log('Arabic joining and mixed Arabic / Latin / numeral labels verified.');
