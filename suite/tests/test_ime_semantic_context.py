"""Portable editing-object contracts; these fakes are not Windows/UNO evidence."""
import importlib
import copy
import io
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import zipfile

E2E=Path(__file__).resolve().parents[1]/'e2e'
sys.path.insert(0,str(E2E));sys.path.insert(0,str(Path(__file__).parent))
import writer_model_reader as model_reader
from test_calc_pending_input import Accessible,ROLES,STATES
from test_calc_model_barrier import workbook
from test_calc_model_barrier import observation
from test_writer_model_barrier import synthetic_frame,original_shell_fixture,retime_native_cleanup_fixture
from test_writer_model_reader import cleanup_fixture
import test_calc_pending_input as pending_fixtures


def package(parts):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        for name,text in parts.items():archive.writestr(name,text)
    return data.getvalue()


def writer_fixture(text='Baseline'):
    return package({'word/document.xml':'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>'})


def impress_fixture(extra=''):
    return package({'ppt/slides/slide1.xml':'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="9" name=""/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:txBody><a:bodyPr/><a:p><a:pPr>'+extra+'</a:pPr><a:r><a:t>Baseline</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'})


class FixedSemanticContractTests(unittest.TestCase):
    def test_three_new_explicit_service_getter_pairs_are_registered_without_legacy_fallback(self):
        pairs=[('com.sun.star.text.TextDocument','writer-active-edit-context-v1'),
            ('com.sun.star.sheet.SpreadsheetDocument','calc-a1-active-edit-context-v1'),
            ('com.sun.star.presentation.PresentationDocument','impress-active-edit-context-v1')]
        for service,getter in pairs:
            with self.subTest(getter=getter):
                error=None
                try:contract=model_reader._model_contract(service,getter)
                except BaseException as exc:error=exc
                self.assertIsNone(error,'New fixed editing-context contract is unavailable')
                self.assertEqual(contract.service,service);self.assertEqual(contract.getters,getter)
                with self.assertRaises(AssertionError):model_reader._model_contract(service,getter+'-optional')
    def test_legacy_reader_operations_stay_exact(self):
        self.assertEqual(model_reader.OPERATIONS,['resolve-existing-owned-frame','Text.getString','isModified','verify-retained-generation'])
        self.assertEqual(model_reader.CALC_PENDING_OPERATIONS,[model_reader.CALC_OPERATIONS[0],
            'XSelectionSupplier.getSelection.rangeAddress','owned-test-accessible.A1-editor.XAccessibleText.getText']+model_reader.CALC_OPERATIONS[1:])


class SemanticGetterTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((E2E/'ime_semantic_context.py').is_file(),'Missing source-backed semantic context')
        self.api=importlib.import_module('ime_semantic_context');self.now=1.
    def writer(self,text='Baseline',position=8,collapsed=True):
        body=NS(getString=lambda:text,getEnd=lambda:NS(position=len(text)),
            compareRegionEnds=lambda left,right:0 if left.position==right.position else -1)
        cursor=NS(isCollapsed=lambda:collapsed,getText=lambda:body,getEnd=lambda:NS(position=position),
            isVisible=lambda:self.fail('Stub visibility cannot certify caret readiness'),
            gotoEnd=lambda *a:self.fail('Getter must not move GUI cursor'))
        model=NS(getText=lambda:body,isModified=lambda:False)
        return self.api.EditingContextReader('writer',object(),NS(getViewCursor=lambda:cursor),model,456,
            deadline=10.,clock=lambda:self.now),cursor,body
    def test_writer_reads_actual_gui_cursor_and_body_end_without_mutating_it(self):
        reader,cursor,body=self.writer();value=reader.read()
        self.assertTrue(self.api.edit_context_ready(value,'writer','Baseline',456))
        self.assertTrue(value['cursorCollapsed']);self.assertEqual(value['bodyEndComparison'],0)
    def test_writer_selected_or_wrong_parent_or_nonend_cursor_never_becomes_ready(self):
        for mode in ('selected','foreign-parent','not-end'):
            with self.subTest(mode=mode):
                reader,cursor,body=self.writer(collapsed=mode!='selected',position=7 if mode=='not-end' else 8)
                if mode=='foreign-parent':cursor.getText=lambda:object()
                self.assertFalse(self.api.edit_context_ready(reader.read(),'writer','Baseline',456))
    def test_writer_body_text_has_to_match_the_untrimmed_expected_baseline(self):
        reader,_,_=self.writer('Baseline ',9)
        self.assertFalse(self.api.edit_context_ready(reader.read(),'writer','Baseline',456))
    def test_writer_caret_getter_exception_is_fatal_not_a_pending_default(self):
        reader,cursor,_=self.writer()
        cursor.isCollapsed=lambda:(_ for _ in ()).throw(RuntimeError('no text selection'))
        with self.assertRaisesRegex(RuntimeError,'no text selection'):reader.read()
    def test_fixture_parser_preserves_writer_breaks_and_rejects_impress_bullets_and_fields(self):
        original=writer_fixture('A</w:t><w:br/><w:t>B')
        self.assertEqual(self.api.fixture_baseline('writer',original)['text'],'A\nB')
        self.assertEqual(self.api.fixture_baseline('impress',impress_fixture())['text'],'Baseline')
        for extra in ('<a:buChar char="x"/>','<a:buAutoNum type="arabicPeriod"/>','<a:fld id="1"/>'):
            with self.subTest(extra=extra),self.assertRaises(AssertionError):self.api.fixture_baseline('impress',impress_fixture(extra))
    def test_calc_baseline_uses_fixed_cells_and_a_plain_single_line_a1(self):
        value=self.api.fixture_baseline('calc',workbook())
        self.assertEqual(value['text'],value['cells']['a1Text'])
        self.assertEqual(value['sourceSha256'],value['cells']['sourceSha256'])
    def impress(self,text='Baseline',caret=8,selection=(8,8),extra_paragraph=False):
        paragraph=Accessible(41,rectangle=(20,20,70,35),text=text)
        paragraph.getCaretPosition=lambda:caret
        paragraph.getCharacterCount=lambda:len(text.encode('utf-16-le'))//2
        paragraph.getSelectionStart=lambda:selection[0];paragraph.getSelectionEnd=lambda:selection[1]
        shape=Accessible(52,children=[paragraph],rectangle=(15,15,80,45))
        if extra_paragraph:shape.set_children([paragraph,Accessible(41,text='')])
        document=Accessible(83,children=[shape],rectangle=(10,10,95,95))
        root=Accessible(40,children=[document],rectangle=(0,0,100,100))
        container_root=Accessible(49,children=[root],rectangle=(0,0,100,100))
        component=NS(getProperty=lambda name:root)
        peer=NS(getWindowHandle=lambda *a:456,getProperty=lambda name:container_root,
            isChild=lambda child:child is component)
        frame=NS(getContainerWindow=lambda:peer,getComponentWindow=lambda:component)
        controller=NS(getFrame=lambda:frame);model=NS(getCurrentController=lambda:controller)
        frame.getController=lambda:controller;controller.getModel=lambda:model
        roles=dict(ROLES,DOCUMENT_PRESENTATION=83,SHAPE=52)
        uno=NS(getConstantByName=lambda name:(STATES if '.AccessibleStateType.' in name else roles)[name.rsplit('.',1)[-1]])
        return frame,paragraph,shape,document,uno
    def test_impress_caret_is_from_the_active_accessible_outliner_paragraph(self):
        frame,paragraph,shape,doc,uno=self.impress()
        with patch.dict(sys.modules,uno=uno):
            reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
            self.assertTrue(self.api.edit_context_ready(reader.read(),'impress','Baseline',456))
    def test_impress_undefined_caret_or_selection_or_multiple_paragraphs_never_qualifies(self):
        for args in [dict(caret=-1),dict(selection=(-1,-1)),dict(selection=(0,8)),dict(extra_paragraph=True)]:
            with self.subTest(args=args):
                frame,paragraph,shape,doc,uno=self.impress(**args)
                with patch.dict(sys.modules,uno=uno):
                    reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
                    self.assertFalse(self.api.edit_context_ready(reader.read(),'impress','Baseline',456))
    def test_impress_changed_native_peer_or_retained_paragraph_identity_fails(self):
        frame,paragraph,shape,doc,uno=self.impress()
        with patch.dict(sys.modules,uno=uno):
            reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
            reader.read();replacement=Accessible(41,text='Baseline');shape.set_children([replacement])
            with self.assertRaises(AssertionError):reader.read()
    def test_known_null_or_bool_or_float_caret_is_not_coerced_to_zero(self):
        for bad in (None,True,0.,'8'):
            with self.subTest(bad=bad):
                frame,paragraph,shape,doc,uno=self.impress(caret=bad)
                with patch.dict(sys.modules,uno=uno):
                    reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
                    with self.assertRaises(AssertionError):reader.read()
    def test_getter_deadline_does_not_reset_or_admit_late_readiness(self):
        reader,_,_=self.writer();self.now=10.
        with self.assertRaises((AssertionError,TimeoutError)):reader.read()
    def test_impress_document_replacement_during_metric_read_rejects_old_exact_text(self):
        frame,paragraph,shape,doc,uno=self.impress()
        root=frame.getComponentWindow().getProperty('XAccessible')
        def replaced_count():
            root.set_children([Accessible(83,children=[Accessible(52)])])
            return 8
        paragraph.getCharacterCount=replaced_count
        with patch.dict(sys.modules,uno=uno):
            reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
            with self.assertRaises(AssertionError):reader.read()
    def test_impress_retained_shape_replacement_rejects_before_foreign_metric_getter(self):
        frame,paragraph,shape,doc,uno=self.impress()
        with patch.dict(sys.modules,uno=uno):
            reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
            reader.read()
            foreign=Accessible(41,text='Baseline')
            foreign.getCaretPosition=lambda:(_ for _ in ()).throw(RuntimeError('Foreign metric getter queried'))
            doc.set_children([Accessible(52,children=[foreign])])
            with self.assertRaises(AssertionError):reader.read()
    def test_impress_nonready_keeps_the_owned_raw_unsupported_caret_and_paragraph_count(self):
        for options in (dict(caret=-1),dict(extra_paragraph=True)):
            with self.subTest(options=options):
                frame,paragraph,shape,doc,uno=self.impress(**options)
                with patch.dict(sys.modules,uno=uno):
                    reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
                    value=reader.read()
                rows=value.get('candidateObservations',[])
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['paragraphCount'],2 if options.get('extra_paragraph') else 1)
                if 'caret' in options:self.assertEqual(rows[0]['caretPosition'],-1)
    def calc(self):
        fixture=pending_fixtures.PendingInputTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.document.set_children([fixture.table,fixture.editor])
        n=len(fixture.paragraph.text)
        for name in ('getCharacterCount','getCaretPosition','getSelectionStart','getSelectionEnd'):
            setattr(fixture.paragraph,name,lambda:n)
        reader=self.api.EditingContextReader('calc',fixture.frame,object(),object(),456,deadline=10.,clock=lambda:self.now)
        return reader,fixture
    def test_calc_reads_original_a1_actual_caret_and_selection(self):
        reader,fixture=self.calc()
        self.assertTrue(self.api.edit_context_ready(reader.read(),'calc',fixture.paragraph.text,456))
    def test_calc_document_or_editor_replaced_during_caret_read_is_rejected(self):
        for target in ('document','editor'):
            with self.subTest(target=target):
                reader,fixture=self.calc()
                def replace():
                    if target=='document':fixture.root.set_children([Accessible(84,children=[fixture.table])])
                    else:fixture.document.set_children([fixture.table,Accessible(61,'Cell A1')])
                    return len(fixture.paragraph.text)
                fixture.paragraph.getCaretPosition=replace
                with self.assertRaises(AssertionError):reader.read()
    def test_writer_receipt_preserves_retained_body_and_gui_cursor_identities(self):
        reader,_,_=self.writer();first=reader.read();second=reader.read()
        self.assertIn('writerBinding',first)
        self.assertEqual(first['writerBinding'],second['writerBinding'])
        altered=copy.deepcopy(first);altered['writerBinding']['cursorIdentity']=True
        with self.assertRaises(AssertionError):self.api.require_edit_context(altered,'writer',456)
    def test_accessible_raw_binding_and_geometry_are_replayed_not_just_verified_flag(self):
        frame,paragraph,shape,doc,uno=self.impress()
        with patch.dict(sys.modules,uno=uno):
            reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
            raw=reader.read()
        for mutate in (lambda v:v['accessibleBinding']['document'].update(role=84),
                       lambda v:v['accessibleBinding'].update(shapeIndex=True),
                       lambda v:v['accessibleBinding']['paragraph'].update(stateBits=0),
                       lambda v:v['accessibleBinding']['shape'].update(rectangle=[0,0,1000,1000])):
            altered=copy.deepcopy(raw);mutate(altered)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):
                self.api.require_edit_context(altered,'impress',456)
        calc,fixture=self.calc();raw=calc.read()
        raw['accessibleBinding']['editorIdentity']='f'*32
        with self.assertRaises(AssertionError):self.api.require_edit_context(raw,'calc',456)
    def test_added_paragraph_during_metric_read_cannot_reuse_local_collapsed_end(self):
        calc,fixture=self.calc()
        def add_calc():
            fixture.editor.set_children([fixture.paragraph,Accessible(41,text='')])
            return len(fixture.paragraph.text)
        fixture.paragraph.getCaretPosition=add_calc
        with self.assertRaises(AssertionError):calc.read()
        frame,paragraph,shape,doc,uno=self.impress()
        calls=[0]
        def add_impress():
            calls[0]+=1
            if calls[0]>1:shape.set_children([paragraph,Accessible(41,text='')])
            return 8
        paragraph.getCaretPosition=add_impress
        with patch.dict(sys.modules,uno=uno):
            reader=self.api.EditingContextReader('impress',frame,frame.getController(),frame.getController().getModel(),456,deadline=10.,clock=lambda:self.now)
            with self.assertRaises(AssertionError):reader.read()
    def test_explicit_helper_dispatch_collects_actual_getters_and_releases_only_its_proxies(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module):
                reader=model_reader._UnoReader.__new__(model_reader._UnoReader)
                reader.contract=model_reader._model_contract(self.api.SERVICES[module],self.api.GETTERS[module])
                reader.config=dict(child_hwnd=456,readerDeadline=time.monotonic()+10.)
                reader.edit_context=reader.pending_input=None
                snapshots=[]
                reader.snapshot=lambda:snapshots.append(len(snapshots)) or dict(measured=len(snapshots))
                if module=='writer':
                    body=NS(getString=lambda:'Baseline',getEnd=lambda:8,compareRegionEnds=lambda a,b:0)
                    cursor=NS(isCollapsed=lambda:True,getText=lambda:body,getEnd=lambda:8)
                    reader.frame=object();reader.controller=NS(getViewCursor=lambda:cursor)
                    reader.model=NS(getText=lambda:body,isModified=lambda:False)
                elif module=='calc':
                    original,fixture=self.calc();reader.frame=fixture.frame
                    reader.proxy_type=NS  # Explicit synthetic counterpart of the retained local PyUNO type.
                    reader.controller=NS(getSelection=lambda:NS(getRangeAddress=lambda:NS(Sheet=0,StartColumn=0,StartRow=0,EndColumn=0,EndRow=0)))
                    cells={'A1':NS(getString=lambda:'Existing A1'),'B1':NS(getValue=lambda:17.),
                        'C1':NS(getValue=lambda:25.),'D1':NS(getValue=lambda:42.,getFormula=lambda:'=SUM(B1:C1)')}
                    reader.model=NS(getSheets=lambda:NS(getByIndex=lambda index:NS(getCellRangeByName=lambda name:cells[name])),isModified=lambda:False)
                else:
                    frame,paragraph,shape,doc,uno=self.impress()
                    reader.frame=frame;reader.controller=frame.getController()
                    reader.controller.getSelection=lambda:self.fail('Generic Impress selection is not the GUI caret')
                    reader.model=reader.controller.getModel();reader.model.isModified=lambda:False
                    patcher=patch.dict(sys.modules,uno=uno);patcher.start();self.addCleanup(patcher.stop)
                value=reader.read();retained=reader.edit_context;second=reader.read()
                self.assertIs(retained,reader.edit_context)
                self.assertEqual(value['editContext']['module'],module)
                self.assertEqual(len(snapshots),4)
                reader.release();self.assertIsNone(reader.edit_context);self.assertIsNone(retained.frame)
                if module=='calc':self.assertEqual(value['a1Text'],'Existing A1')


class SemanticSetupTests(unittest.TestCase):
    def setUp(self):
        self.api=importlib.import_module('ime_semantic_context')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.frame=synthetic_frame((Path(self.temp.name)/'Suite').resolve(),'unused')
        self.native={k:self.frame.binding[k] for k in ('shellPid','shellCreationTime','officePid',
            'officeCreationTime','expectedImage','suiteHwnd','parentHwnd','childHwnd','rootHwnd')}
        self.shell=original_shell_fixture(self.frame.binding,self.frame.suite)
        self.now=.5;self.calls=[];self.fixtures={}
    def fixture(self,module):
        if module in self.fixtures:
            source,data=self.fixtures[module];self.frame.binding['documentUrl']=source.as_uri()
            return source,data
        data={'writer':writer_fixture(),'impress':impress_fixture(),'calc':workbook()}[module]
        source=self.frame.suite/('OpenGeul-'+module+{'writer':'.docx','calc':'.xlsx','impress':'.pptx'}[module])
        source.write_bytes(data);self.frame.binding['documentUrl']=source.as_uri()
        self.fixtures[module]=(source,data);return source,data
    def row(self,module,text,at=1.,modified=False,ready=True):
        row=observation(self.frame,text,at,at+.1,modified)
        contract=model_reader._model_contract(self.api.SERVICES[module],self.api.GETTERS[module])
        row.update(kind=contract.kind,operations=list(contract.operations))
        for uno in row['unoSnapshots'].values():uno['modelService']=self.api.SERVICES[module]
        editing=dict(kind='actual-gui-editing-context',sourceTag=self.api.SOURCE,module=module,
            readOnly=True,targetStable=True,childHwnd=self.native['childHwnd'])
        if module=='writer':
            editing.update(textBefore=text,textAfter=text,cursorCollapsed=True,
                cursorTextIsBody=True,bodyEndComparison=0 if ready else -1,
                writerBinding=dict(verified=True,bodyIdentity='1'*32,cursorIdentity='2'*32))
            row['bodyText']=text
        else:
            end=len(text.encode('utf-16-le'))//2
            editing.update(targetFound=True,paragraphCount=1,paragraph=dict(textBefore=text,textAfter=text,
                characterCount=end,caretPosition=end if ready else -1,selectionStart=end,selectionEnd=end),
                accessibleBinding=dict(verified=True))
        if module=='impress':
            state=STATES['SHOWING']|STATES['VISIBLE']
            root=dict(role=40,stateBits=state,rectangle=[0,0,100,100])
            doc=dict(role=83,stateBits=state,rectangle=[10,10,95,95])
            shape=dict(role=52,stateBits=state,rectangle=[15,15,80,45])
            para=dict(role=41,stateBits=state,rectangle=[20,20,70,35])
            checks=dict(frameController=True,controllerFrame=True,modelController=True,controllerModel=True,
                containerPeer=True,containerAccessible=True,componentPeer=True,componentDistinct=True,
                properContainerChild=True,componentAccessible=True,containerHwnd=self.native['childHwnd'])
            editing['accessibleBinding']=dict(verified=True,rootIdentity='1'*32,documentIdentity='2'*32,
                shapeIdentity='3'*32,paragraphIdentity='4'*32,root=root,document=doc,shape=shape,paragraph=para,
                documentPath=[0],shapeIndex=0,paragraphIndex=0,visitedCount=2,
                rootBasis='original-frame-current-component-window',componentBinding=dict(
                    containerRoot=dict(role=49,stateBits=state,rectangle=[0,0,100,100]),
                    before=copy.deepcopy(checks),after=copy.deepcopy(checks)))
            editing['candidateObservations']=[dict(shapeIndex=0,paragraphCount=1,shape=shape,
                paragraphIndex=0,paragraph=para,caretPosition=end if ready else -1)]
            if not ready:
                editing.update(targetFound=False,paragraphCount=0,paragraph=None)
                for key in ('shapeIdentity','paragraphIdentity','shapeIndex','paragraphIndex','shape','paragraph'):
                    del editing['accessibleBinding'][key]
        if module=='calc':
            fixture=pending_fixtures.PendingInputTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
            fixture.paragraph.text=text;pending=fixture.present();pending['childHwnd']=self.native['childHwnd']
            editing['pendingInput']=pending
            editing['accessibleBinding']=dict(verified=True,rootIdentity=pending['root']['identity'],
                documentIdentity=pending['document']['identity'],editorIdentity=pending['editor']['identity'],paragraphIndex=0)
            row['a1Text']=self.api.fixture_baseline('calc',workbook())['text']
            row['calcSelection']=dict(readOnly=True,source='retained-controller.getSelection',
                range=dict(sheet=0,startColumn=0,startRow=0,endColumn=0,endRow=0))
        row['editContext']=editing
        return row
    def clean(self,module,deadline=10.,at=2.):
        value=cleanup_fixture(self.frame.binding,str(self.frame.suite))
        contract=model_reader._model_contract(self.api.SERVICES[module],self.api.GETTERS[module])
        value.update(kind=contract.cleanup_kind,startedAt=at,finishedAt=at+.1,deadline=deadline)
        retime_native_cleanup_fixture(value);return value
    def run_phase(self,module='writer',phase='pre',record=None,rows=None,cleanup=None,
                  failure=None,close_failure=None,deadline=10.,current_failure=None):
        source,data=self.fixture(module);prefix=self.api.PREFIXES[module]
        record={} if record is None else record
        record.setdefault('module',module)
        if rows is None:
            text=self.api.fixture_baseline(module,data)['text']+(prefix if phase=='post' else '')
            rows=[self.row(module,text,at=self.now+.5,modified=phase=='post' and module=='writer')]
        rows=iter(rows);cleanup=self.clean(module,deadline=deadline,at=self.now+1.5) if cleanup is None else cleanup
        def read(end):
            self.calls.append(('read',end));self.now+=.2
            if failure is not None:raise failure
            row=next(rows);self.now=max(self.now,row['readFinishedAt']+.01);return row
        def start(end):self.calls.append(('start',end));return read(end)
        def close(end):
            self.calls.append(('close',end));self.now=max(self.now,cleanup['finishedAt'])
            if close_failure is not None:raise close_failure
            return cleanup
        def factory(*args,**kwargs):
            self.calls.append(('construct',kwargs));return NS(start=start,read=read,close=close)
        def require_current():
            self.calls.append(('current',))
            if current_failure is not None:raise current_failure
        result=self.api.observe_ime_semantic_setup(self.frame.suite,source,data,record,deadline,
            original_shell=self.shell,expected_native=self.native,require_current=require_current,
            phase=phase,expected_prefix=prefix if phase=='post' else None,
            reader_factory=factory,clock=lambda:self.now,pause=lambda seconds:setattr(self,'now',self.now+seconds))
        return result,record
    def test_pre_context_requires_actual_end_caret_then_natural_cleanup_before_return(self):
        value,record=self.run_phase()
        self.assertTrue(value['success']);self.assertIs(record['imeSemanticContext'],value)
        self.assertIs(record['imeSemanticContexts'][0],value)
        self.assertEqual(len(value['observations']),1)
        self.assertIs(value['observation'],value['observations'][0])
        self.assertEqual([c[0] for c in self.calls].count('close'),1)
        self.api.require_ime_semantic_context(value,module='writer',expected_native=self.native,
            setup_deadline=10.,now=3.,phase='pre')
    def test_read_only_poll_can_observe_readiness_without_repeating_any_input(self):
        self.fixture('writer')
        rows=[self.row('writer','Baseline',ready=False),self.row('writer','Baseline',at=1.2)]
        value,_=self.run_phase(rows=rows)
        self.assertEqual(len(value['observations']),2)
        self.assertEqual([c[0] for c in self.calls].count('construct'),1)
        self.assertEqual([c[0] for c in self.calls].count('close'),1)
        self.assertNotIn('asciiEditorInputs',value)
    def test_arbitrary_getter_error_is_not_converted_to_notready_and_cleanup_is_once(self):
        primary=RuntimeError('actual UNO getter failed');record={}
        with self.assertRaises(RuntimeError) as raised:self.run_phase(record=record,failure=primary)
        self.assertIs(raised.exception,primary)
        self.assertEqual([c[0] for c in self.calls].count('close'),1)
        self.assertFalse(record['imeSemanticContext']['success'])
    def test_secondary_cleanup_error_does_not_replace_the_original_getter_error(self):
        primary=RuntimeError('getter primary');record={}
        with self.assertRaises(RuntimeError) as raised:
            self.run_phase(record=record,failure=primary,close_failure=OSError('close secondary'))
        self.assertIs(raised.exception,primary)
        self.assertIn('close secondary',record['imeSemanticContext']['cleanupErrors'][0])
    def test_native_guard_rejection_prevents_reader_construction(self):
        primary=RuntimeError('native generation changed')
        with self.assertRaises(RuntimeError):self.run_phase(current_failure=primary)
        self.assertNotIn('construct',[c[0] for c in self.calls])
    def test_sample_binding_drift_is_fatal_even_when_text_and_caret_match(self):
        self.fixture('writer')
        rows=[self.row('writer','Baseline',ready=False),self.row('writer','Baseline',at=1.2)]
        rows[1]['bindingBefore']['officeCreationTime']+=1
        with self.assertRaises(AssertionError):self.run_phase(rows=rows)
    def test_unsafe_native_cleanup_never_produces_an_accepted_context(self):
        for key,value in [('terminated',True),('finalJobPids',[100]),('errors',[dict(error='not released')])]:
            with self.subTest(key=key):
                self.fixture('writer');cleanup=self.clean('writer');cleanup[key]=value
                with self.assertRaises(AssertionError):self.run_phase(cleanup=cleanup)
    def test_phase_deadline_is_original_capped_twelve_and_cleanup_cannot_finish_late(self):
        self.fixture('writer');cleanup=self.clean('writer',deadline=12.5);cleanup['finishedAt']=12.5
        retime_native_cleanup_fixture(cleanup)
        with self.assertRaises(AssertionError):self.run_phase(cleanup=cleanup,deadline=60.)
        self.assertEqual([c[1] for c in self.calls if c[0]=='start'],[12.5])
    def test_pure_replay_rejects_forged_success_native_generation_and_clock(self):
        value,_=self.run_phase()
        for change in (lambda v:v['observation'].update(bodyText='lost'),
                       lambda v:v['cleanup'].update(terminated=True),
                       lambda v:v['expectedNative'].update(childHwnd=999),
                       lambda v:v.update(finishedAt=10.)):
            altered=copy.deepcopy(value);change(altered)
            with self.subTest(change=change),self.assertRaises(AssertionError):
                self.api.require_ime_semantic_context(altered,module='writer',expected_native=self.native,
                    setup_deadline=10.,now=3.,phase='pre')
    def test_post_requires_a_real_pre_context_and_exact_once_physical_prefix(self):
        with self.assertRaises(AssertionError):self.run_phase(phase='post')
    def test_pre_context_does_not_accept_dirty_document_or_an_already_inserted_prefix(self):
        self.fixture('writer')
        with self.assertRaises(AssertionError):self.run_phase(rows=[self.row('writer','Baseline',modified=True)])
        with self.assertRaises(AssertionError):self.run_phase(record=dict(asciiPrefix=self.api.PREFIXES['writer']))
    def prefix(self,record,module):
        import ascii_editor_input as keyboard
        import test_ascii_editor_input as ascii_fixtures
        from ascii_observer_boundary import AsciiObserverBoundary
        self.now+=.1
        process=NS(pid=self.native['shellPid'],_handle=self.shell['handleValue'])
        with patch.object(keyboard,'_observer',side_effect=AsciiObserverBoundary), \
             patch.object(keyboard.time,'sleep',side_effect=lambda seconds:setattr(self,'now',self.now+seconds)):
            keyboard.type_ascii(ascii_fixtures.FakeWindows(),11,22,self.api.PREFIXES[module],record,
                pause=.04,deadline=10.,clock=lambda:self.now,original_popen=process,
                native_binding=self.native,prepared_library={'testOnlyObserverBoundary':True})
        record.update(asciiPrefix=self.api.PREFIXES[module],prefixInputLayout=keyboard.US_LAYOUT,
            windowHwnd=11,childHwnd=22,keyboardFocusHwnd=33,editorTid=44)
        self.now+=.1
    def test_three_modules_pre_and_post_use_exact_live_text_with_distinct_modified_contracts(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module):
                self.now=.5
                pre,record=self.run_phase(module)
                self.prefix(record,module)
                post,record=self.run_phase(module,'post',record)
                self.assertTrue(post['success']);self.assertEqual(len(record['imeSemanticContexts']),2)
                self.assertEqual(post['observation']['isModified'],module=='writer')
                self.api.require_ime_semantic_context(post,module=module,expected_native=self.native,
                    setup_deadline=10.,now=self.now,phase='post',expected_prefix=self.api.PREFIXES[module])
                if module=='calc':self.assertEqual(post['observation']['a1Text'],pre['baseline']['text'])
    def test_counted_full_prefix_is_not_semantic_proof_for_a_missing_first_or_mid_character(self):
        for module,omitted in [('writer',5),('calc',0),('impress',2)]:
            with self.subTest(module=module):
                self.now=.5;pre,record=self.run_phase(module);self.prefix(record,module)
                prefix=self.api.PREFIXES[module];lost=prefix[:omitted]+prefix[omitted+1:]
                bad=self.row(module,pre['baseline']['text']+lost,at=self.now+.1,modified=module=='writer')
                with self.assertRaises((AssertionError,StopIteration)):
                    self.run_phase(module,'post',record,rows=[bad])
                self.assertFalse(record['imeSemanticContext']['success'])
                self.assertEqual(len(record['imeSemanticContext']['observations']),1)
                self.assertIn('cleanup',record['imeSemanticContext'])
    def test_post_calc_committed_change_is_rejected_even_with_exact_pending_text(self):
        pre,record=self.run_phase('calc');self.prefix(record,'calc')
        row=self.row('calc',pre['baseline']['text']+self.api.PREFIXES['calc'],at=self.now+.1)
        row.update(a1Text=pre['baseline']['text']+self.api.PREFIXES['calc'],isModified=True)
        with self.assertRaises(AssertionError):self.run_phase('calc','post',record,rows=[row])
    def test_prefix_original_deadline_and_pre_to_post_times_are_joined_in_pure_replay(self):
        pre,record=self.run_phase();self.prefix(record,'writer')
        post,_=self.run_phase(phase='post',record=record)
        for key,value in [('absoluteDeadline',11.),('startedAt',pre['finishedAt']-.01),
                          ('finishedAt',post['startedAt']+.01),('finishedAt',True)]:
            altered=copy.deepcopy(post);altered['asciiEvidence']['asciiEditorInputs'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(AssertionError):
                self.api.require_ime_semantic_context(altered,module='writer',expected_native=self.native,
                    setup_deadline=10.,now=self.now,phase='post',expected_prefix=self.api.PREFIXES['writer'])
    def test_replay_rejects_a_read_finished_after_its_actual_receive_time(self):
        value,_=self.run_phase();altered=copy.deepcopy(value)
        altered['observations'][0]['readFinishedAt']=1.9
        with self.assertRaises(AssertionError):
            self.api.require_ime_semantic_context(altered,module='writer',expected_native=self.native,
                setup_deadline=10.,now=3.,phase='pre')
    def test_pure_windows_source_uri_replay_does_not_use_the_reviewers_host_os(self):
        self.assertEqual(self.api._source_uri('D:\\a b\\owned.docx'),'file:///D:/a%20b/owned.docx')
        self.assertEqual(self.api._source_uri('/a b/owned.docx'),'file:///a%20b/owned.docx')


class SemanticFixturePathTests(unittest.TestCase):
    def test_aliased_temporary_root_reaches_all_three_actual_pre_and_post_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory);(parent/'alias-parent').mkdir()
            alias=parent/'alias-parent'/'..'
            temporary=NS(name=str(alias),cleanup=lambda:None)
            case=SemanticSetupTests('test_three_modules_pre_and_post_use_exact_live_text_with_distinct_modified_contracts')
            with patch.object(tempfile,'TemporaryDirectory',return_value=temporary):
                case.debug()

    def test_native_admission_replays_drive_and_unc_paths_without_host_path_conversion(self):
        api=importlib.import_module('ime_semantic_context')
        for suite in (PureWindowsPath(r'C:\Users\RUNNER~1\Suite'),PureWindowsPath(r'\\server\share\Suite')):
            with self.subTest(suite=str(suite)):
                native=dict(shellPid=11,shellCreationTime=101,officePid=22,officeCreationTime=202,
                    expectedImage=str(suite/'Office/program/soffice.bin'),suiteHwnd=33,
                    rootHwnd=33,parentHwnd=44,childHwnd=55)
                self.assertIs(api._native(native,suite),native)
                native['expectedImage']=str(suite.parent/'Foreign/Office/program/soffice.bin')
                with self.assertRaises(AssertionError):api._native(native,suite)
        suite=PureWindowsPath(r'C:\Users\runneradmin\Suite')
        native['expectedImage']=r'C:\Users\RUNNER~1\Suite\Office\program\soffice.bin'
        with self.assertRaises(AssertionError):api._native(native,suite)
        native['expectedImage']=str(suite/'Office/program/soffice.bin')
        self.assertIs(api._native(native,suite),native)


if __name__=='__main__':unittest.main()
