/** Native-engine regression for nested visual Home/End public keyboard routing. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {harness,inputFixture,inspect,sha} from './nested_line_navigation.harness.mjs';

function geometry(h,line,atEnd){
 const offset=atEnd?line.end:line.start,rows=atEnd?[...line.rows].reverse():line.rows;
 const row=rows.find(row=>row.charStart<=offset&&offset<=row.charStart+Array.from(row.text).length);assert.ok(row,'Independent input has exact endpoint text span');
 const caret=h.caret();assert.ok(caret);const x=h.virtualScroll.getPageLeftResolved(line.page,800)+row.x+row.charX[offset-row.charStart],y=h.virtualScroll.getPageOffset(line.page)+row.y;
 assert.ok(Math.abs(parseFloat(caret.left)-x)<=0.15,'Real public caret must use exact inner visual x');
 assert.ok(Math.abs(parseFloat(caret.top)-y)<=0.15,'Real public caret must stay on the correct inner visual line');
 assert.ok(Math.abs(parseFloat(caret.height)-row.h)<=0.15,'Real public caret height must match endpoint font span');
}

for(const depth of [2,3])test(`depth ${depth} End appends in exact inner owner and preserves undo/redo`,async t=>{
 const input=inputFixture(depth,'INNER-00'),hash=sha(input.bytes),h=await harness(t,input),before=h.export();
 h.clickAtOffset(3);h.key('End');assert.equal(h.position().charOffset,8,'End must read inner paragraph rather than empty outer host');
 h.type('-EDIT');assert.equal(h.inspect()[input.target][0],'INNER-00-EDIT');assert.deepEqual(h.inspect()['s0/body'],['','']);
 assert.equal(h.command('edit:undo').ok,true);assert.deepEqual(h.inspect(),inspect(before));assert.equal(h.command('edit:redo').ok,true);assert.equal(h.inspect()[input.target][0],'INNER-00-EDIT');
 assert.equal(sha(input.bytes),hash);assert.deepEqual(h.position().cellPath,input.path);
});

for(const depth of [2,3])test(`depth ${depth} Home starts exact nested paragraph without mutation/history`,async t=>{
 const input=inputFixture(depth,'INNER-00'),h=await harness(t,input);h.clickAtOffset(5);const before=h.export();h.key('Home');
 assert.equal(h.position().charOffset,0);assert.deepEqual(h.position().cellPath,input.path);assert.equal(h.handler.canUndo(),false);assert.deepEqual(h.export(),before);
});

for(const depth of [2,3])test(`depth ${depth} wrapped Home/End retain visual-line boundary affinity`,async t=>{
 const text='ALPHA BETA GAMMA DELTA EPSILON ZETA ETA THETA IOTA KAPPA LAMBDA MU',input=inputFixture(depth,text),h=await harness(t,input);
 assert.ok(input.lines.length>=3,'Authored native input really wraps');const line=input.lines[1];assert.ok(line.start>0&&line.end<Array.from(text).length);
 h.clickAtOffset(line.start+2);const before=h.export();h.key('Home');assert.equal(h.position().charOffset,line.start,'Home must reach current wrapped line, not paragraph start');geometry(h,line,false);
 h.key('End');assert.equal(h.position().charOffset,line.end,'End must reach visual line boundary, not paragraph end');geometry(h,line,true);
 h.key('End');assert.equal(h.position().charOffset,line.end,'Repeated End must preserve previous visual line affinity');
 h.key('Home');assert.equal(h.position().charOffset,line.start,'Home after End must return to the same visual line');geometry(h,line,false);
 assert.deepEqual(h.position().cellPath,input.path);assert.deepEqual(h.export(),before);assert.equal(h.handler.canUndo(),false);
});

test('nested emoji offsets use Unicode codepoints rather than UTF16 units',async t=>{
 const input=inputFixture(3,'A😀BCDEF'),h=await harness(t,input);assert.equal(input.text.length,8);assert.equal(Array.from(input.text).length,7);
 h.clickAtOffset(2);h.key('End');assert.equal(h.position().charOffset,7);h.type('-X');assert.equal(h.inspect()[input.target][0],'A😀BCDEF-X');
 h.key('Home');assert.equal(h.position().charOffset,0);h.key('End',{shiftKey:true});assert.equal(h.position().charOffset,9);h.key('Backspace');assert.equal(h.inspect()[input.target][0],'');
 assert.equal(h.command('edit:undo').ok,true);assert.equal(h.inspect()[input.target][0],'A😀BCDEF-X');
});

test('mixed font spans on one nested wrapped line form one visual navigation range',async t=>{
 const text='ALPHA BETA GAMMA DELTA EPSILON ZETA ETA THETA IOTA KAPPA LAMBDA MU',input=inputFixture(2,text,{mixedStyle:true}),h=await harness(t,input);
 assert.ok(input.lines.length>=3);const line=input.lines[0];assert.ok(line.rows.length>1,'Mixed native input has multiple font spans on one visual line');h.clickAtOffset(1);h.key('End');assert.equal(h.position().charOffset,line.end);geometry(h,line,true);h.key('Home');assert.equal(h.position().charOffset,line.start);geometry(h,line,false);
 assert.deepEqual(h.position().cellPath,input.path);
});

test('empty nested paragraph keeps visual caret owner and creates no history',async t=>{
 const input=inputFixture(3,''),h=await harness(t,input);h.clickAtOffset(0);const before=h.export();h.key('End');h.key('Home');
 assert.equal(h.position().charOffset,0);assert.deepEqual(h.position().cellPath,input.path);assert.deepEqual(h.export(),before);assert.equal(h.handler.canUndo(),false);
});

test('nested hard line breaks stop End before the newline and preserve Home affinity',async t=>{
 const input=inputFixture(2,'FIRST\nSECOND\nTHIRD'),h=await harness(t,input);h.clickAtOffset(7);h.key('Home');assert.equal(h.position().charOffset,6);h.key('End');assert.equal(h.position().charOffset,12);h.key('Home');assert.equal(h.position().charOffset,6);
});

test('navigation reopens saved output and cannot reuse prior document line spans',async t=>{
 const a=inputFixture(2,'INNER-00'),b=inputFixture(2,'SECOND'),h=await harness(t,a);h.clickAtOffset(3);h.key('End');h.type('-EDIT');const saved=h.export();
 h.reopen(saved);h.clickAtOffset(3);h.key('End');assert.equal(h.position().charOffset,13);assert.equal(h.inspect()[a.target][0],'INNER-00-EDIT');
 h.reopen(b.bytes);h.clickAtOffset(3);h.key('End');assert.equal(h.position().charOffset,Array.from(b.text).length);assert.equal(h.inspect()[b.target][0],b.text);assert.equal(h.handler.canUndo(),false);assert.equal(h.handler.canRedo(),false);
});

test('nested second paragraph uses full owner path and keeps Shift+Home selection',async t=>{
 const input=inputFixture(3,'SECOND-00',{paragraphs:['FIRST-00','SECOND-00'],paragraphIndex:1}),h=await harness(t,input);h.clickAtOffset(3);h.key('End');assert.equal(h.position().charOffset,9);
 h.key('Home',{shiftKey:true});assert.equal(h.position().charOffset,0);h.key('Backspace');assert.deepEqual(h.inspect()[input.target],['FIRST-00','']);
 assert.equal(h.command('edit:undo').ok,true);assert.deepEqual(h.inspect()[input.target],['FIRST-00','SECOND-00']);
});
