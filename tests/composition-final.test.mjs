import test from 'node:test';
import assert from 'node:assert/strict';
import {settleFinalComposition as finalize} from '../overlay/composition-final.ts';
const state=(extra={})=>({active:true,isComposing:true,compositionAnchor:{},compositionLength:0,_lastCompositionText:'',textarea:{value:'확정 😀'},...extra});
for(const [name,extra,expected] of [
 ['commit arrives before any composing input',{},1],
 ['final differs from live composition',{compositionLength:1,_lastCompositionText:'확'},1],
 ['same intermediate text must not double insert',{compositionLength:4,_lastCompositionText:'확정 😀'},0],
 ['same text in a new composition must commit',{compositionLength:0,_lastCompositionText:'확정 😀'},1],
 ['inactive input cannot mutate',{active:false},0],
 ['composition already ended',{isComposing:false},0],
 ['cancelled or blocked composition',{compositionAnchor:null},0],
 ['empty pending text does not replay a previous composition',{textarea:{value:''},compositionLength:2,_lastCompositionText:'이전'},0],
]) {
 test(name,()=>{
  const value=state(extra);let calls=0;
  finalize(value,()=>{calls++;assert.equal(value.textarea.value,'확정 😀');});
  assert.equal(calls,expected);
 });
}
