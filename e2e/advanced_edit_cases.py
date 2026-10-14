"""Seven common advanced UI cases driven through actual public input.

Mixin after SupportedTests and before EditorTests/NativeTests. Fixture generation
is separate from product input. Never use private editor/bridge/WASM APIs here.
"""
from __future__ import annotations
import json
import copy
from pathlib import Path
import re
import shutil
import hashlib
from playwright.sync_api import expect
from driver import digest, edit, menu, primary_modifier
from advanced_edit_oracle import (inspect_advanced_hwpx, assert_grid, assert_field,
    assert_equation, assert_equation_ink, assert_notes, assert_page, assert_textbox, require_body, assert_population, assert_checkpoint, checkpoint_diagnostic)
from test_editor import FIXTURES

ADVANCED_CHECKS = {
 'test_advanced_table_merge_split_history_reopen': ('grid','merged','merge-undo','merge-redo','split','split-undo','split-redo','reopen','next-edit','source-sha'),
 'test_advanced_existing_nested_cell_edit_history_reopen': ('nested','edited','undo','redo','selection-delete','delete-undo','delete-redo','reopen','next-edit','source-sha'),
 'test_advanced_field_insert_fill_history_reopen': ('inserted','insert-undo','insert-redo','filled','fill-undo','fill-redo','reopen','next-edit','source-sha'),
 'test_advanced_equation_chord_doubleclick_history_reopen': ('inserted','property-undo','create-undo','create-redo','property-redo','doubleclick-edit','edit-undo','edit-redo','ink','reopen','next-edit','source-sha'),
 'test_advanced_footnote_endnote_history_reopen': ('footnote','foot-text-undo','foot-create-undo','foot-create-redo','foot-text-redo','endnote','end-text-undo','end-create-undo','end-create-redo','end-text-redo','reopen','next-edit','source-sha'),
 'test_advanced_header_footer_landscape_page_history_reopen': ('header','header-undo','header-redo','footer','footer-undo','footer-redo','page','page-undo','page-redo','page-break','break-undo','break-redo','reopen','next-edit','source-sha'),
 'test_advanced_textbox_create_edit_history_reopen': ('created','create-undo','create-redo','text','text-undo','text-redo','properties','property-undo','property-redo','reopen','next-edit','source-sha'),
}
GRID={(r,c):((1,1),f'ADV-CELL-{r}{c}',(f'ADV-CELL-{r}{c}',)) for r in range(2) for c in range(2)}
MERGED={(0,0):((1,2),'ADV-CELL-00ADV-CELL-01',('ADV-CELL-00','ADV-CELL-01')),(1,0):GRID[(1,0)],(1,1):GRID[(1,1)]}
SPLIT={**GRID,(0,0):((1,1),'ADV-CELL-00ADV-CELL-01',('ADV-CELL-00','ADV-CELL-01')),(0,1):((1,1),'',('',))}


class AdvancedEditCases:
    def advanced_owned(self,name='owned-blank.hwpx'):
        source=FIXTURES/'advanced-owned'/name
        self._advanced_sources={source:digest(source)}
        editable=self.folder/name; shutil.copy2(source,editable)
        self._advanced_sources[editable]=digest(editable)
        self._advanced_input=inspect_advanced_hwpx(editable)
        self._advanced_state={
            'body_paragraphs':list(self._advanced_input['paragraphs']['s0/body']),
            'pages':copy.deepcopy(self._advanced_input['pages']),
            'breaks':list(self._advanced_input['breaks']),
            'population':{key:len(self._advanced_input[key]) for key in
                          ('tables','fields','equations','notes','headers','footers','shapes')},
            'headers':[row['text'] for row in self._advanced_input['headers']],
            'footers':[row['text'] for row in self._advanced_input['footers']]}
        self.open(editable)
        self._advanced_serial=0
        return editable

    def advanced_sources_preserved(self):
        for source,sha in self._advanced_sources.items(): self.assertEqual(digest(source),sha)

    def advanced_save(self,phase):
        self.advanced_sources_preserved()
        self._advanced_serial+=1
        target=self.folder/f'advanced-{self._advanced_serial:02}.hwpx'
        native=self.session.mode=='native'
        saved=self.session.save(self.document,target,save_as=native)
        self.assertEqual(saved,target)
        if native: self.document=target
        actual=inspect_advanced_hwpx(target)
        helpers={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                 for name in ('advanced_edit_cases.py','advanced_edit_oracle.py')}
        diagnostic=checkpoint_diagnostic(actual,phase=phase,saved_sha256=digest(target),
            input_sha256={source.name:sha for source,sha in self._advanced_sources.items()},
            helper_sha256=helpers,expected=copy.deepcopy(self._advanced_state))
        target.with_suffix('.checkpoint.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
        assert_checkpoint(actual,**self._advanced_state)
        self.advanced_sources_preserved()
        return target

    def advanced_check(self,label,oracle,**declared):
        # Only authored constants/known input metadata set the expected state;
        # saved GUI output never teaches this policy what an Undo should preserve.
        if set(declared)-set(self._advanced_state):raise AssertionError('Unknown checkpoint state component')
        self._advanced_state.update(copy.deepcopy(declared))
        saved=self.advanced_save(label); oracle(inspect_advanced_hwpx(saved)); self.checked(label)
        return saved

    def advanced_immutable(self):
        self.advanced_sources_preserved()
        self.checked('source-sha')

    def advanced_palette(self,command):
        self.area().focus(); self.page.keyboard.press(primary_modifier(self.page)+'+/')
        search=self.page.locator('.cp-input'); expect(search).to_be_visible(); search.fill(command)
        item=self.page.locator('.cp-item'); self.assertEqual(item.count(),1)
        item.click(); expect(search).not_to_be_visible()

    def advanced_canvas_point(self,x_mm,y_mm,*,width_mm=210,height_mm=297):
        canvas=self.page.locator('canvas.document-page-canvas').first
        canvas.scroll_into_view_if_needed(); b=canvas.bounding_box()
        if not b or min(b['width'],b['height'])<=0: raise AssertionError('No public page bounds')
        point={'x':b['x']+b['width']*x_mm/width_mm,'y':b['y']+b['height']*y_mm/height_mm}
        hit=canvas.evaluate('(node,p)=>document.elementFromPoint(p.x,p.y)===node',point)
        if not hit: raise AssertionError('Input point misses/covered actual page canvas')
        return point

    def advanced_click_mm(self,x,y):
        p=self.advanced_canvas_point(x,y); self.page.mouse.click(p['x'],p['y'])
        self.area().focus()

    def advanced_body_tail(self,text):
        self.area().focus(); self.page.keyboard.press('Escape'); self.page.keyboard.press('Escape')
        edit(self.page,text)
        self._advanced_state['body_paragraphs'][-1]+=text

    def advanced_end(self):
        self.area().focus()
        self.page.keyboard.press('Meta+ArrowDown' if primary_modifier(self.page)=='Meta' else 'Control+End')

    def test_advanced_table_merge_split_history_reopen(self):
        self.advanced_owned()
        self.page.locator('#icon-toolbar button[data-cmd="table:create"]').click()
        cell=self.page.locator('[data-row="1"][data-col="1"]'); expect(cell).to_be_visible(); cell.click()
        self.area().focus()
        for i in range(4):
            self.page.keyboard.insert_text(f'ADV-CELL-{i//2}{i%2}')
            if i<3:self.page.keyboard.press('Tab')
        verify=lambda r,wanted:(assert_population(r,tables=1),assert_grid(r,'s0/body/t0',wanted))
        self.advanced_check('grid',lambda r:verify(r,GRID),body_paragraphs=['',''],population={'tables':1})
        self.area().focus()
        for _ in range(3):self.page.keyboard.press('Shift+Tab')
        # First F5 selects one cell; second F5 makes arrows extend a range.
        self.page.keyboard.press('F5'); self.page.keyboard.press('F5'); self.page.keyboard.press('ArrowRight')
        menu(self.page,'table:cell-merge',category='table')
        self.advanced_check('merged',lambda r:verify(r,MERGED))
        self.undo(); self.advanced_check('merge-undo',lambda r:verify(r,GRID))
        self.redo(); self.advanced_check('merge-redo',lambda r:verify(r,MERGED))
        self.area().focus(); menu(self.page,'table:cell-split',category='table')
        d=self.page.locator('.dialog-wrap').filter(has=self.page.locator('#csd-col-check'))
        expect(d).to_be_visible(); d.locator('#csd-row-check').uncheck(); d.locator('#csd-col-check').check()
        d.locator('input[type=number]').nth(1).fill('2'); d.locator('.dialog-btn-primary').click()
        self.advanced_check('split',lambda r:verify(r,SPLIT))
        self.undo(); self.advanced_check('split-undo',lambda r:verify(r,MERGED))
        self.redo(); saved=self.advanced_check('split-redo',lambda r:verify(r,SPLIT))
        self.open(saved); self.advanced_check('reopen',lambda r:verify(r,SPLIT))
        self.advanced_body_tail(' TABLE-NEXT'); self.advanced_check('next-edit',lambda r:(verify(r,SPLIT),require_body(r,'TABLE-NEXT')))
        self.advanced_immutable()

    def test_advanced_existing_nested_cell_edit_history_reopen(self):
        self.advanced_owned('owned-nested.hwpx')
        def verify(result,suffix):
            assert_population(result,tables=2)
            self.assertEqual(set(result['tables']),{'s0/body/t0','s0/body/t0/r0c0/t0'})
            outer={(r,c):((1,1),f'OUTER-{r}{c}',(f'OUTER-{r}{c}',)) for r in range(2) for c in range(2)}
            outer[(0,0)]=((1,1),'OUTER-00',('OUTER-00',''))  # second paragraph owns the inner table
            assert_grid(result,'s0/body/t0',outer)
            expected={(r,c):((1,1),f'INNER-{r}{c}',(f'INNER-{r}{c}',)) for r in range(2) for c in range(2)}
            expected[(0,0)]=((1,1),'INNER-00'+suffix,('INNER-00'+suffix,)); assert_grid(result,'s0/body/t0/r0c0/t0',expected)
        self.advanced_check('nested',lambda r:verify(r,''))
        # Owned fixture's first nested row covers approximately 56.5–72mm.
        # This authored interior point is verified against the real native layout.
        # Saved direct ancestry is the decisive check; a missed click fails it.
        self.advanced_click_mm(42,63); self.page.keyboard.press('End'); self.page.keyboard.insert_text('-EDIT')
        self.advanced_check('edited',lambda r:verify(r,'-EDIT'))
        self.undo(); self.advanced_check('undo',lambda r:verify(r,''))
        self.redo(); self.advanced_check('redo',lambda r:verify(r,'-EDIT'))
        self.area().focus(); self.page.keyboard.press('End')
        for _ in '-EDIT':self.page.keyboard.press('Shift+ArrowLeft')
        self.page.keyboard.press('Backspace'); self.advanced_check('selection-delete',lambda r:verify(r,''))
        self.undo(); self.advanced_check('delete-undo',lambda r:verify(r,'-EDIT'))
        self.redo(); saved=self.advanced_check('delete-redo',lambda r:verify(r,''))
        self.open(saved); self.advanced_check('reopen',lambda r:verify(r,''))
        self.advanced_click_mm(42,63); self.page.keyboard.press('End'); self.page.keyboard.insert_text('-NEXT')
        self.advanced_check('next-edit',lambda r:verify(r,'-NEXT')); self.advanced_immutable()

    def test_advanced_field_insert_fill_history_reopen(self):
        self.advanced_owned(); edit(self.page,'FIELD-BODY-HEAD')
        menu(self.page,'insert:field',category='insert')
        d=self.page.locator('.dialog-wrap').filter(has=self.page.locator('.field-edit-body'))
        expect(d).to_be_visible(); d.locator('.field-edit-input').nth(0).fill('ADV-GUIDE')
        d.locator('.field-edit-input').nth(1).fill('ADV-NAME'); d.locator('.field-edit-textarea').fill('ADV-MEMO')
        d.locator('.field-edit-checkbox-row input').check(); d.locator('.dialog-footer .dialog-btn-primary').click()
        verify=lambda r,value:assert_field(r,name='ADV-NAME',guide='ADV-GUIDE',memo='ADV-MEMO',value=value,body=('FIELD-BODY-HEAD',),anchor=(0,15))
        self.advanced_check('inserted',lambda r:verify(r,''),body_paragraphs=['FIELD-BODY-HEAD'],population={'fields':1})
        self.undo(); self.advanced_check('insert-undo',lambda r:self.assertEqual(r['fields'],[]),population={})
        self.redo(); self.advanced_check('insert-redo',lambda r:verify(r,''),population={'fields':1})
        self.advanced_palette('view:form-mode'); self.area().focus(); self.page.keyboard.press('Tab')
        self.page.keyboard.insert_text('ADV-VALUE'); self.advanced_palette('view:form-mode')
        self.advanced_check('filled',lambda r:verify(r,'ADV-VALUE'))
        self.undo(); self.advanced_check('fill-undo',lambda r:verify(r,''))
        self.redo(); saved=self.advanced_check('fill-redo',lambda r:verify(r,'ADV-VALUE'))
        self.open(saved); self.advanced_check('reopen',lambda r:verify(r,'ADV-VALUE'))
        # Document End is also this field's end boundary. ArrowRight exits the
        # field without moving its anchor; input then belongs to the body.
        self.advanced_end(); self.page.keyboard.press('ArrowRight')
        self.page.keyboard.insert_text(' FIELD-BODY-NEXT')
        self._advanced_state['body_paragraphs'][-1]+=' FIELD-BODY-NEXT'
        self.advanced_check('next-edit',lambda r:(verify(r,'ADV-VALUE'),require_body(r,'FIELD-BODY-NEXT'))); self.advanced_immutable()

    def advanced_eq_dialog(self,script):
        d=self.page.locator('.eq-dialog'); expect(d).to_be_visible(); d.locator('.eq-script').fill(script)
        d.locator('.eq-props-row input[type=number]').fill('10')
        d.locator('.dialog-footer .dialog-btn-primary').click(); self.area().focus()

    def advanced_selected_bbox(self):
        borders=self.page.locator('.table-object-layer > div').evaluate_all('''nodes => nodes
          .filter(n=>getComputedStyle(n).borderColor==='rgb(0, 0, 0)' && getComputedStyle(n).backgroundColor==='rgba(0, 0, 0, 0)')
          .map(n=>{const b=n.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height}})
          .filter(b=>b.width>4 && b.height>4)''')
        self.assertEqual(len(borders),1,'Exactly one public selected object border required')
        return borders[0]

    def advanced_select_equation(self):
        # An equation-only paragraph has text length zero, so backward F11
        # from document End finds no earlier control. Select forward from Home.
        self.area().focus(); self.page.keyboard.press('Escape'); self.page.keyboard.press('Escape')
        self.page.keyboard.press('Meta+ArrowUp' if primary_modifier(self.page)=='Meta' else 'Control+Home')
        self.page.keyboard.press('Shift+F11')

    def test_advanced_equation_chord_doubleclick_history_reopen(self):
        self.advanced_owned(); edit(self.page,'EQUATION-BODY'); self.page.keyboard.press('Enter')
        self.page.keyboard.press('Control+m'); self.page.keyboard.press('m')
        self.advanced_eq_dialog('x^2 + {1} over {2}')
        verify=lambda r,script:assert_equation(r,script,body=('EQUATION-BODY',),anchor=(1,0))
        self.advanced_check('inserted',lambda r:verify(r,'x^2 + {1} over {2}'),body_paragraphs=['EQUATION-BODY',''],population={'equations':1})
        self.undo(); self.advanced_check('property-undo',lambda r:assert_equation(r,'',body=('EQUATION-BODY',),anchor=(1,0),dimensions_hu=(1,1)))
        self.undo(); self.advanced_check('create-undo',lambda r:self.assertEqual(r['equations'],[]),population={})
        self.redo(); self.advanced_check('create-redo',lambda r:assert_equation(r,'',body=('EQUATION-BODY',),anchor=(1,0),dimensions_hu=(1,1)),population={'equations':1})
        self.redo(); self.advanced_check('property-redo',lambda r:verify(r,'x^2 + {1} over {2}'))
        self.advanced_select_equation()
        box=self.advanced_selected_bbox(); self.page.mouse.dblclick(box['x']+box['width']/2,box['y']+box['height']/2)
        self.advanced_eq_dialog('x^3 + {1} over {2}'); self.advanced_check('doubleclick-edit',lambda r:verify(r,'x^3 + {1} over {2}'))
        self.undo(); self.advanced_check('edit-undo',lambda r:verify(r,'x^2 + {1} over {2}'))
        self.redo(); saved=self.advanced_check('edit-redo',lambda r:verify(r,'x^3 + {1} over {2}'))
        self.advanced_select_equation()
        box=self.advanced_selected_bbox(); canvas=self.page.locator('canvas.document-page-canvas').first; pagebox=canvas.bounding_box()
        normalized=((box['x']-pagebox['x'])/pagebox['width'],(box['y']-pagebox['y'])/pagebox['height'],
            (box['x']+box['width']-pagebox['x'])/pagebox['width'],(box['y']+box['height']-pagebox['y'])/pagebox['height'])
        self.area().focus(); self.page.keyboard.press('Escape')
        expect(self.page.locator('.table-object-layer > div')).to_have_count(0)
        png=self.folder/'equation-ink.png'; canvas.screenshot(path=str(png))
        ink=assert_equation_ink(png,normalized); (self.folder/'equation-ink.json').write_text(json.dumps(ink)); self.checked('ink')
        self.open(saved); self.advanced_check('reopen',lambda r:verify(r,'x^3 + {1} over {2}'))
        # Edit the declared first body paragraph, leaving the equation-only
        # second paragraph and its (1,0) reference unchanged.
        self.area().focus()
        self.page.keyboard.press('Meta+ArrowUp' if primary_modifier(self.page)=='Meta' else 'Control+Home')
        self.page.keyboard.press('End'); self.page.keyboard.insert_text(' EQUATION-NEXT')
        self._advanced_state['body_paragraphs'][0]+=' EQUATION-NEXT'
        self.advanced_check('next-edit',lambda r:(verify(r,'x^3 + {1} over {2}'),require_body(r,'EQUATION-NEXT'))); self.advanced_immutable()

    def test_advanced_footnote_endnote_history_reopen(self):
        self.advanced_owned(); edit(self.page,'NOTE-BODY')
        def verify(result,entries,anchor=(0,9)):
            assert_notes(result,entries,body=('NOTE-BODY',),anchors=[anchor]*len(entries))
        entries=[]
        for kind,command,marker,prefix in [('footNote','insert:footnote','ADV-FOOTNOTE','foot'),('endNote','insert:endnote','ADV-ENDNOTE','end')]:
            self.area().focus(); self.page.keyboard.press('Escape'); self.advanced_end()
            menu(self.page,command,category='insert')
            # Native note edit info begins at IR charOffset=2, after autoNum+space.
            # Serialization emits one actual space; the other IR position is autoNum.
            placeholder=' '
            self.area().focus(); self.page.keyboard.insert_text(marker); self.page.keyboard.press('Escape')
            entries.append((kind,placeholder+marker)); self.advanced_check('footnote' if prefix=='foot' else 'endnote',lambda r:verify(r,entries),body_paragraphs=['NOTE-BODY'],population={'notes':len(entries)})
            self.undo(); self.advanced_check(prefix+'-text-undo',lambda r:verify(r,entries[:-1]+[(kind,placeholder)]))
            self.undo(); self.advanced_check(prefix+'-create-undo',lambda r:verify(r,entries[:-1]),population={'notes':len(entries)-1})
            self.redo(); self.advanced_check(prefix+'-create-redo',lambda r:verify(r,entries[:-1]+[(kind,placeholder)]),population={'notes':len(entries)})
            self.redo(); saved=self.advanced_check(prefix+'-text-redo',lambda r:verify(r,entries))
        self.open(saved); self.advanced_check('reopen',lambda r:verify(r,entries))
        # These zero-text note controls sit at body End. Inserting ten body
        # characters there precedes both controls and moves their references.
        self.advanced_body_tail(' NOTE-NEXT'); self.advanced_check('next-edit',lambda r:(verify(r,entries,anchor=(0,19)),require_body(r,'NOTE-NEXT'))); self.advanced_immutable()

    def advanced_hf_close(self):
        self.page.locator('.tb-headerfooter-group button[data-cmd="page:headerfooter-close"]').click()
        expect(self.page.locator('#scroll-container')).not_to_have_class(re.compile(r'\bhf-editing\b'))

    def test_advanced_header_footer_landscape_page_history_reopen(self):
        self.advanced_owned(); edit(self.page,'PAGE-BODY-ONE')
        for key,command,marker in [('headers','page:header-create','ADV-HEADER'),('footers','page:footer-create','ADV-FOOTER')]:
            self.page.locator('#icon-toolbar button[data-cmd="'+command+'"]').click()
            expect(self.page.locator('.tb-headerfooter-group')).to_be_visible()
            self.area().focus(); self.page.keyboard.insert_text(marker); self.advanced_hf_close()
            verify=lambda r:self.assertEqual([(n['text'],n['attrs'].get('applyPageType')) for n in r[key]],[(marker,'BOTH')])
            self.advanced_check('header' if key=='headers' else 'footer',verify,body_paragraphs=['PAGE-BODY-ONE'],population={'headers':1,'footers':int(key=='footers')},**{key:[marker]})
            self.undo(); self.advanced_check(('header' if key=='headers' else 'footer')+'-undo',lambda r:self.assertEqual(r[key][0]['text'],''),**{key:['']})
            self.redo(); self.advanced_check(('header' if key=='headers' else 'footer')+'-redo',verify,**{key:[marker]})
            self.advanced_hf_close()
        baseline=self._advanced_input['pages'][0]  # Authored source metadata, never GUI output
        menu(self.page,'file:page-setup')
        d=self.page.locator('.dialog-wrap').filter(has=self.page.locator('.margin-grid')); expect(d).to_be_visible()
        d.locator('select.dialog-select').first.select_option('A4')
        d.locator('input[name=orient][value=true]').locator('..').click()
        for i,value in enumerate(('13','23','17','19','8','9','0')):d.locator('.margin-grid input').nth(i).fill(value)
        d.locator('.dialog-footer .dialog-btn-primary').click()
        wanted={'width':59528,'height':84189,'landscape':'NARROWLY','margin':{'left':4819,'right':5386,'top':3685,'bottom':6520,'header':2268,'footer':2551,'gutter':0}}
        self.advanced_check('page',lambda r:self.assertEqual(r['pages'],[wanted]),pages=[wanted])
        self.undo(); self.advanced_check('page-undo',lambda r:self.assertEqual(r['pages'],[baseline]),pages=[baseline])
        self.redo(); self.advanced_check('page-redo',lambda r:self.assertEqual(r['pages'],[wanted]),pages=[wanted])
        self.advanced_end(); menu(self.page,'page:break',category='page')
        self.advanced_check('page-break',lambda r:self.assertEqual(r['breaks'],[(0,1)]),body_paragraphs=['PAGE-BODY-ONE',''],breaks=[(0,1)])
        self.undo(); self.advanced_check('break-undo',lambda r:self.assertEqual(r['breaks'],[]),body_paragraphs=['PAGE-BODY-ONE'],breaks=[])
        self.redo(); self.advanced_check('break-redo',lambda r:self.assertEqual(r['breaks'],[(0,1)]),body_paragraphs=['PAGE-BODY-ONE',''],breaks=[(0,1)])
        self.area().focus(); self.page.keyboard.insert_text('PAGE-BODY-TWO')
        self._advanced_state['body_paragraphs']=['PAGE-BODY-ONE','PAGE-BODY-TWO']
        verify=lambda r:assert_page(r,header='ADV-HEADER',footer='ADV-FOOTER',body=('PAGE-BODY-ONE','PAGE-BODY-TWO'))
        saved=self.advanced_save('page-body-two'); verify(inspect_advanced_hwpx(saved)); self.open(saved); self.advanced_check('reopen',verify)
        self.advanced_body_tail(' PAGE-NEXT'); self.advanced_check('next-edit',lambda r:(verify(r),require_body(r,'PAGE-NEXT'))); self.advanced_immutable()

    def test_advanced_textbox_create_edit_history_reopen(self):
        self.advanced_owned(); edit(self.page,'SHAPE-BODY')
        menu(self.page,'insert:textbox',category='insert')
        self.page.wait_for_function('getComputedStyle(document.querySelector("#scroll-container")).cursor === "crosshair"')
        start=self.advanced_canvas_point(75,70); end=self.advanced_canvas_point(115,90)
        self.page.mouse.move(start['x'],start['y']); self.page.mouse.down()
        try:self.page.mouse.move(end['x'],end['y'],steps=12)
        finally:self.page.mouse.up()
        verify=lambda r,count,text='',size=(40,20):assert_textbox(r,count=count,text=text,body=('SHAPE-BODY',),dimensions_mm=size)
        self.advanced_check('created',lambda r:verify(r,1),body_paragraphs=['SHAPE-BODY'],population={'shapes':1})
        self.undo(); self.advanced_check('create-undo',lambda r:verify(r,0),population={})
        self.redo(); self.advanced_check('create-redo',lambda r:verify(r,1),population={'shapes':1})
        self.advanced_click_mm(85,80); self.page.keyboard.insert_text('ADV-TEXTBOX')
        self.advanced_check('text',lambda r:verify(r,1,'ADV-TEXTBOX'))
        self.undo(); self.advanced_check('text-undo',lambda r:verify(r,1))
        self.redo(); self.advanced_check('text-redo',lambda r:verify(r,1,'ADV-TEXTBOX'))
        self.area().focus(); self.page.keyboard.press('Escape')
        self.page.locator('#icon-toolbar button[data-cmd="format:object-properties"]').click()
        d=self.page.locator('.pp-dialog'); expect(d).to_be_visible(); panel=d.locator('.dialog-tab-panel[data-tab=basic]')
        ratio=panel.get_by_label('비율 유지',exact=True); ratio.uncheck()
        panel.locator('input[type=number]').nth(0).fill('45'); panel.locator('input[type=number]').nth(1).fill('25')
        d.locator('.cs-right-col .dialog-btn-primary').click()
        self.advanced_check('properties',lambda r:verify(r,1,'ADV-TEXTBOX',(45,25)))
        self.undo(); self.advanced_check('property-undo',lambda r:verify(r,1,'ADV-TEXTBOX'))
        self.redo(); saved=self.advanced_check('property-redo',lambda r:verify(r,1,'ADV-TEXTBOX',(45,25)))
        self.open(saved); self.advanced_check('reopen',lambda r:verify(r,1,'ADV-TEXTBOX',(45,25)))
        self.advanced_click_mm(85,80); self.page.keyboard.press('End'); self.page.keyboard.insert_text('-NEXT')
        self.advanced_check('next-edit',lambda r:verify(r,1,'ADV-TEXTBOX-NEXT',(45,25))); self.advanced_immutable()
