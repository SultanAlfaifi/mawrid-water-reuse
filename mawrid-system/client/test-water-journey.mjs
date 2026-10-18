/* Pure explanation data/progress checks: no server, simulation or ML calls. */
import assert from 'node:assert/strict';
import { WATER_JOURNEY, journeyProgress } from './water-journey.js';

let count=0;
function check(name,test){test();count++;console.log(`PASS ${name}`);}

check('eight unique stages explain the water path in process order',()=>{
  assert.deepEqual(WATER_JOURNEY.map(stage=>stage.id),['collection','media','carbon','polish','verify','uv','storage','irrigation']);
  for(const stage of WATER_JOURNEY)for(const field of ['id','short','title','role','benefit']){
    assert.equal(typeof stage[field],'string');assert(stage[field].trim());
  }
  assert.match(WATER_JOURNEY[4].benefit,/لا تحسب إعادة الماء/);
  assert.match(WATER_JOURNEY[5].title,/اختياري/);
  assert.match(WATER_JOURNEY[5].benefit,/اختبارًا فعليًا/);
});
check('fresh or different sessions begin at collection without completion',()=>{
  for(const [ui,id] of [[{},'a'],[{journeySession:'old',journeyIndex:7,journeyComplete:true},'a'],[{journeySession:undefined,journeyIndex:7,journeyComplete:true},undefined]]){
    const result=journeyProgress(ui,id);assert.equal(result.index,0);assert.equal(result.complete,false);
    assert.equal(result.total,8);assert.equal(result.stage.id,'collection');
  }
});
check('only integer local indices are accepted and valid values are bounded',()=>{
  for(const [index,expected] of [[0,0],[3,3],[7,7],[-2,0],[90,7],[1.5,0],['5',0],[NaN,0],[Infinity,0],[undefined,0]]){
    const result=journeyProgress({journeySession:'a',journeyIndex:index},'a');
    assert.equal(result.index,expected);assert.equal(result.stage,WATER_JOURNEY[expected]);
  }
});
check('completion is a boolean tied to the exact session',()=>{
  for(const [complete,expected] of [[true,true],[false,false],['true',false],[1,false],[undefined,false]]){
    assert.equal(journeyProgress({journeySession:'a',journeyIndex:7,journeyComplete:complete},'a').complete,expected);
  }
  assert.equal(journeyProgress({journeySession:'a',journeyIndex:7,journeyComplete:true},'b').complete,false);
});
check('reading progress never edits local UI state or the stage data',()=>{
  const ui={journeySession:'a',journeyIndex:3,journeyComplete:false};
  const before=JSON.stringify({ui,stages:WATER_JOURNEY});
  assert.deepEqual(journeyProgress(ui,'a'),journeyProgress(ui,'a'));
  assert.equal(JSON.stringify({ui,stages:WATER_JOURNEY}),before);
});
console.log(`${count} water journey checks PASS; pure explanation/progress only.`);
