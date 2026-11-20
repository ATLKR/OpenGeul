import './renderer_font_candidates.loader.mjs';
import {test,beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {state} from './renderer_font_candidates.fixture.mjs';
const fonts=await import('@/core/local-fonts');
const normal={weight:400,slant:'normal'};
const entry=(postScriptName,style='normal',weight=400,family='Split')=>({family,postScriptName,style,weight,sourceKind:'system-installed',path:`/synthetic/${postScriptName}.ttf`});
beforeEach(()=>{fonts.resetLocalFontsForTests();delete globalThis.window;});
async function desktop(entries){globalThis.window={__TAURI_INTERNALS__:{}};state.entries=entries;await fonts.detectLocalFonts();}
test('renderer candidates are an actual named export with required style',()=>{assert.equal(typeof fonts.resolveRendererLocalFontCandidates,'function');});
test('browser delegates to upstream without reducing the result or changing style',()=>{const result=[{family:'Browser',postscriptName:'Browser'}];state.results=result;assert.equal(fonts.resolveRendererLocalFontCandidates('Browser',normal),result);assert.equal(state.calls.length,1);assert.equal(state.calls[0].style,normal);assert.equal(state.singleCalls,0);assert.equal(state.nativeCalls.length,0);});
test('desktop host provider delegates all ordered split programs',()=>{globalThis.window={__TAURI_INTERNALS__:{}};state.host=true;const result=[{family:'Split',postscriptName:'Z'},{family:'Split',postscriptName:'A'}];state.results=result;assert.equal(fonts.resolveRendererLocalFontCandidates('Split',normal),result);assert.equal(state.nativeCalls.length,0);assert.equal(state.singleCalls,0);});
test('desktop resolver never opens a catalog or bytes when not already loaded',()=>{globalThis.window={__TAURI_INTERNALS__:{}};assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Unknown',normal),[]);assert.equal(state.nativeCalls.length,0);});
test('desktop split programs retain the existing normalized catalog order',async()=>{await desktop([entry('Z'),entry('A'),entry('Bold','normal',700)]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Split',normal).map(x=>x.postscriptName),['A','Z']);assert.deepEqual(state.nativeCalls,['list_local_fonts']);});
test('desktop exact PostScript identity does not substitute a styled family face',async()=>{await desktop([entry('A'),entry('Bold','normal',700)]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('A',{weight:700,slant:'italic'}).map(x=>x.postscriptName),['A']);});
test('desktop weight selection excludes other faces',async()=>{await desktop([entry('Regular'),entry('Bold','normal',700)]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Split',{weight:700,slant:'normal'}).map(x=>x.postscriptName),['Bold']);});
test('desktop exact slant wins over the inclined alternate',async()=>{await desktop([entry('Italic','italic'),entry('Oblique','oblique')]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Split',{weight:400,slant:'italic'}).map(x=>x.postscriptName),['Italic']);});
test('desktop alternate slant preserves every matching split program',async()=>{await desktop([entry('OZ','oblique'),entry('OA','oblique'),entry('Normal')]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Split',{weight:400,slant:'italic'}).map(x=>x.postscriptName),['OA','OZ']);});
test('desktop normal slant does not borrow inclined or unknown-weight faces',async()=>{await desktop([entry('Italic','italic'),{...entry('MissingWeight'),weight:undefined}]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Split',normal),[]);});
test('desktop duplicate PostScript identities remain ambiguous',async()=>{await desktop([entry('Duplicate','normal',400,'One'),{...entry('Duplicate','normal',400,'Two'),path:'/synthetic/different.ttf'}]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Duplicate',normal),[]);});
test('desktop duplicate split identifiers grant no coverage choice',async()=>{const a=entry('Duplicate');await desktop([a,{...a,path:'/synthetic/other.ttf'}]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Split',normal),[]);});
test('document rendering keeps existing blocked-authoring font access and never reads bytes',async()=>{await desktop([entry('HYHeadLineM','normal',400,'HY헤드라인M')]);assert.equal(fonts.getLocalFonts().length,0);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('HYHeadLineM',normal).map(x=>x.postscriptName),['HYHeadLineM']);assert.deepEqual(state.nativeCalls,['list_local_fonts']);});
test('desktop selected identities cannot alias a different family during byte lookup',async()=>{await desktop([entry('Shared','normal',400,'One'),{...entry('Shared','normal',400,'Two'),path:'/synthetic/different.ttf'}]);assert.deepEqual(fonts.resolveRendererLocalFontCandidates('One',normal),[]);});
test('localized family aliases preserve the same existing desktop byte-read identity',async()=>{
 const base=entry('MalgunGothic','normal',400,'맑은 고딕');base.path='/synthetic/malgun.ttf';
 await desktop([base,{...base,family:'Malgun Gothic'}]);
 const legacy=fonts.resolveRendererLocalFont('MalgunGothic');
 const ps=fonts.resolveRendererLocalFontCandidates('MalgunGothic',normal);
 assert.equal(ps.length,1);assert.equal(ps[0].family,legacy.family);
 const ko=fonts.resolveRendererLocalFontCandidates('맑은 고딕',normal);
 const en=fonts.resolveRendererLocalFontCandidates('Malgun Gothic',normal);
 assert.equal(ko.length,1);assert.equal(ko[0].family,'맑은 고딕');assert.equal(en.length,1);assert.equal(en[0].family,'Malgun Gothic');
 for(const record of [ps[0],ko[0],en[0]]){assert.deepEqual(Object.keys(record).sort(),Object.keys(legacy).sort());for(const key of ['path','sourceKind','weight'])assert.equal(Object.hasOwn(record,key),false);assert.equal(JSON.stringify(record).includes('/synthetic/'),false);}
 assert.equal(state.readPaths.length,0);
 for(const record of [legacy,ps[0],ko[0],en[0]]){const data=await fonts.loadRendererLocalFont(record);assert.equal(data.faceIndex,0);assert.deepEqual([...new Uint8Array(data.bytes)],[1,2,3,4]);}
 assert.equal(state.readPaths.length,4);assert.equal(new Set(state.readPaths).size,1);assert.equal(state.readPaths[0],'/synthetic/malgun.ttf');
});
test('same path alone cannot merge different desktop read metadata',async()=>{
 for(const delta of [{weight:700},{style:'italic'},{sourceKind:'file-backed'},{path:'/synthetic/other.ttf'}]){
  fonts.resetLocalFontsForTests();const base={...entry('Shared','normal',400,'One'),path:'/synthetic/shared.ttf'};
  await desktop([base,{...base,family:'Two',...delta}]);
  assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Shared',normal),[]);
  assert.deepEqual(fonts.resolveRendererLocalFontCandidates('One',normal),[]);assert.equal(state.readPaths.length,0);
 }
});
test('multiple aliases with no verifiable path remain unresolved',async()=>{
 const base={...entry('Shared','normal',400,'One'),path:null};await desktop([base,{...base,family:'Two'}]);
 assert.deepEqual(fonts.resolveRendererLocalFontCandidates('Shared',normal),[]);assert.equal(state.readPaths.length,0);
});
