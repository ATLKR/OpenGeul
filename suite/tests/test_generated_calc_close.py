"""Opt-in generated Calc cleanup; no general prompt-discard fallback."""
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from suite.tests import test_calc_model_barrier as workbook_fixture

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))


class GeneratedCalcCloseTests(unittest.TestCase):
    def setUp(self):
        self.api=importlib.import_module('generated_calc_close')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.suite=self.root/'suite';self.suite.mkdir()
        self.owned=self.root/'generated';self.owned.mkdir()
        self.source=self.owned/'OpenGeul-calc.xlsx'
        self.data=workbook_fixture.workbook()
        self.source.write_bytes(self.data)
        self.digest=hashlib.sha256(self.data).hexdigest()
        import calc_save_smoke
        self.cells=calc_save_smoke.read_cells(self.data)

    def proof(self):
        return self.api.freeze_saved_calc_copy(self.suite,self.owned,self.source,self.digest,self.cells)

    def test_only_explicit_fixed_owned_copy_with_exact_already_verified_bytes_and_cells_can_authorize(self):
        proof=self.proof();self.api.verify_saved_calc_copy(proof)
        for reason in ('hash','cells','name','payload'):
            path=self.source;root=self.owned;digest=self.digest;cells=dict(self.cells)
            if reason=='hash':digest='0'*64
            elif reason=='cells':cells['a1Text']='wrong'
            elif reason=='name':path=self.owned/'user.xlsx';path.write_bytes(self.data)
            else:root=self.suite;path=root/'OpenGeul-calc.xlsx';path.write_bytes(self.data)
            with self.subTest(reason=reason),self.assertRaises(AssertionError):
                self.api.freeze_saved_calc_copy(self.suite,root,path,digest,cells)

    def boundary(self):
        self.live={10,20,30};self.clicks=[];self.closes=[];self.prompt=False
        buttons=[NS(element_info=NS(name=name),is_visible=lambda:True,is_enabled=lambda:True)
                 for name in ('저장','저장하지 않음','취소')]
        def click():self.clicks.append('discard');self.live.clear()
        buttons[1].click_input=click
        accessible=NS(descendants=lambda **kw:buttons if kw else
                      [NS(element_info=NS(name='변경 내용을 저장하시겠습니까?'))]+buttons)
        native=NS(set_focus=lambda:None)
        class Desktop:
            def __init__(self,backend):self.backend=backend
            def window(self,handle):return NS(wrapper_object=lambda:accessible if self.backend=='uia' else native)
        self.pid=lambda h:7 if h in (10,30) else 8
        self.owner=lambda h,k:10 if h==30 else 0
        self.title=lambda h:'OpenGeul Calc'
        def request(h,p):self.closes.append((h,p));self.prompt=True
        self.windows=NS(user=NS(IsWindow=lambda h:h in self.live,IsChild=lambda h,c:h==10 and c==20,
                       GetAncestor=lambda h,k:h,GetWindow=lambda h,k:self.owner(h,k)),
                       pid=lambda h:self.pid(h),title=lambda h:self.title(h),class_name=lambda h:'#32770',
                       windows=lambda pid:[30] if self.prompt else [],request_close=request,
                       require_foreground=lambda h:None)
        self.process=NS(pid=7,poll=lambda:None)
        self.record=dict(module='calc',shellPid=7,windowHwnd=10,childHwnd=20)
        return Desktop,accessible,buttons

    def invoke(self,proof,Desktop,*,blank=False,waiter=None,real_ancestry=False):
        from contextlib import nullcontext
        import lifecycle_smoke as lifecycle
        with patch.dict(sys.modules,{'pywinauto':NS(Desktop=Desktop)}), \
             (nullcontext() if real_ancestry else patch.object(lifecycle,'require_dialog_button_ancestry',return_value=[{'controlType':'Button','nativeHandle':1},{'controlType':'Window'}])), \
             (nullcontext() if real_ancestry else patch.object(lifecycle,'dialog_uia_identity',return_value={'pid':7})), \
             patch('windows_smoke.wait_for',side_effect=waiter or (lambda check,seconds=60:check() or (_ for _ in ()).throw(AssertionError('not ready')))):
            function=self.api.close_generated_blank_calc if blank else self.api.close_saved_calc_copy
            function(self.windows,self.process,10,20,self.record,proof)

    def blank_proof(self):
        import lifecycle_smoke as lifecycle
        self.process.args=[str(self.suite/'OpenGeul.Office.exe'),'--module','calc']
        self.process._handle=77;self.process.opengeul_evidence_case='new-calc'
        self.record.update(kind='new-document',keyboardInputVerified=False,contentMutationVerified=False)
        test=self
        class Bound:
            def __init__(self,pid,image):self.pid=pid;self.handle=pid;self.creation=9007199254741000+pid;self.kernel=None
            def live(self):return self.pid==7 or 20 in test.live
            def close(self):self.handle=None
        self.bound_creation=9007199254741007
        def identity(kernel,handle):
            return ((self.suite/'OpenGeul.Office.exe').resolve(),self.bound_creation) if handle in (7,77) else ((self.suite/'Office/program/soffice.bin').resolve(),9007199254741008)
        for patcher in (patch.object(lifecycle,'BoundHwpProcess',Bound),patch.object(lifecycle,'process_identity',side_effect=identity)):
            patcher.start();self.addCleanup(patcher.stop)
        return self.api.freeze_generated_blank_calc(self.suite,self.windows,self.process,10,20,self.record)

    def test_generated_blank_requires_exact_factory_launch_and_native_process_generations(self):
        Desktop,_,_=self.boundary();proof=self.blank_proof();self.invoke(proof,Desktop,blank=True)
        self.assertEqual([(10,7)],self.closes);self.assertEqual(['discard'],self.clicks)
        evidence=self.record['verifiedGeneratedBlankCalcDiscard']
        self.assertEqual(9007199254741007,evidence['shellCreationTime'])
        self.assertEqual(9007199254741008,evidence['engineCreationTime'])
        self.assertIsNone(proof.shell.handle);self.assertIsNone(proof.engine.handle)

    def test_blank_wrong_file_launch_new_case_or_native_generation_never_discards(self):
        for reason in ('file','case','generation'):
            Desktop,_,_=self.boundary();proof=self.blank_proof()
            if reason=='file':self.process.args+=['--file',str(self.source)]
            elif reason=='case':self.record['kind']='keyboard-edit'
            else:self.bound_creation+=1
            with self.subTest(reason=reason),self.assertRaises(AssertionError):self.invoke(proof,Desktop,blank=True)
            self.assertEqual([],self.closes);self.assertEqual([],self.clicks)

    def test_one_owned_close_and_one_exact_discard_leave_verified_saved_bytes_unchanged(self):
        proof=self.proof();Desktop,_,_=self.boundary();self.invoke(proof,Desktop)
        self.assertEqual([(10,7)],self.closes);self.assertEqual(['discard'],self.clicks)
        self.assertEqual(self.data,self.source.read_bytes())
        self.assertTrue(self.record['verifiedSavedCalcDiscard']['diskBytesUnchanged'])

    def test_foreign_or_ambiguous_prompt_never_receives_discard(self):
        for reason in ('owner','pid','title','button','class'):
            proof=self.proof();Desktop,accessible,buttons=self.boundary()
            if reason=='owner':self.owner=lambda h,k:99
            elif reason=='pid':self.pid=lambda h:999 if h==30 else 7 if h==10 else 8
            elif reason=='title':self.title=lambda h:'foreign'
            elif reason=='button':buttons.append(buttons[1])
            else:self.windows.class_name=lambda h:'foreign'
            with self.subTest(reason=reason),self.assertRaises(AssertionError):self.invoke(proof,Desktop)
            self.assertEqual([],self.clicks)

    def test_changed_saved_bytes_after_authorization_stop_before_any_close_or_choice(self):
        proof=self.proof();Desktop,_,_=self.boundary();self.source.write_bytes(b'changed')
        with self.assertRaises(AssertionError):self.invoke(proof,Desktop)
        self.assertEqual([],self.closes);self.assertEqual([],self.clicks)

    def test_saved_copy_change_between_close_and_choice_never_clicks_discard(self):
        proof=self.proof();Desktop,_,_=self.boundary()
        request=self.windows.request_close
        def changed(h,p):request(h,p);self.source.write_bytes(b'changed while closing')
        self.windows.request_close=changed
        with self.assertRaises(AssertionError):self.invoke(proof,Desktop)
        self.assertEqual([(10,7)],self.closes);self.assertEqual([],self.clicks)

    def test_wrong_module_or_native_binding_stops_before_close(self):
        for key,value in [('module','writer'),('shellPid',99),('windowHwnd',99),('childHwnd',99)]:
            proof=self.proof();Desktop,_,_=self.boundary();self.record[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.invoke(proof,Desktop)
            self.assertEqual([],self.closes);self.assertEqual([],self.clicks)

    def test_unexpected_fourth_button_is_recorded_and_never_dismissed(self):
        proof=self.proof();Desktop,_,buttons=self.boundary()
        buttons.append(NS(element_info=NS(name='Close',control_type='Button',automation_id='Close',
            control_id=0,process_id=7,runtime_id=[42,30,99]),is_visible=lambda:True,is_enabled=lambda:True))
        with self.assertRaisesRegex(AssertionError,'Expected exact three-choice Calc prompt'):
            self.invoke(proof,Desktop)
        self.assertEqual([(10,7)],self.closes);self.assertEqual([],self.clicks)
        evidence=self.record['verifiedSavedCalcDiscard']
        self.assertIn('promptObservations',evidence,'Rejected buttons must remain inspectable')
        row=evidence['promptObservations'][-1]
        self.assertEqual(['저장','저장하지 않음','취소','Close'],[b['name'] for b in row['buttons']])
        self.assertEqual([42,30,99],row['buttons'][-1]['runtimeId'])
        self.assertFalse(row['ready']);self.assertEqual('unexpected-or-duplicate-button',row['readiness'])

    def test_readonly_wait_allows_three_owned_choices_to_finish_appearing_once(self):
        import itertools
        self.assertTrue(hasattr(self.api,'time'),'Readiness must keep the original prompt deadline')
        proof=self.proof();Desktop,accessible,buttons=self.boundary();scans=[0];budgets=[]
        buttons[0].is_enabled=lambda:scans[0]>=2
        def descendants(**kw):
            if kw:scans[0]+=1;return buttons
            return [NS(element_info=NS(name='변경 내용을 저장하시겠습니까?'))]+buttons
        accessible.descendants=descendants
        def wait(check,seconds=60):
            budgets.append(seconds)
            for _ in range(3):
                result=check()
                if result:return result
            raise AssertionError('not ready')
        with patch.object(self.api.time,'monotonic',side_effect=itertools.count(100,2)):
            self.invoke(proof,Desktop,waiter=wait)
        self.assertEqual([(10,7)],self.closes);self.assertEqual(['discard'],self.clicks)
        evidence=self.record['verifiedSavedCalcDiscard']
        self.assertEqual(['choices-not-ready','ready','ready'],[o['readiness'] for o in evidence['promptObservations']])
        self.assertEqual([18,16,14],budgets[:3],'The same original prompt deadline must bound every read-only wait')

    def test_never_ready_prompt_keeps_bounded_raw_observations_without_discard(self):
        proof=self.proof();Desktop,_,buttons=self.boundary();buttons[0].is_enabled=lambda:False
        def wait(check,seconds=60):
            for _ in range(35):
                result=check()
                if result:return result
            raise AssertionError('prompt readiness timeout')
        with self.assertRaisesRegex(AssertionError,'prompt readiness timeout'):
            self.invoke(proof,Desktop,waiter=wait)
        evidence=self.record['verifiedSavedCalcDiscard']
        self.assertEqual([(10,7)],self.closes);self.assertEqual([],self.clicks)
        self.assertEqual(35,evidence['promptObservationCount'])
        self.assertEqual(24,len(evidence['promptObservations']))
        self.assertFalse(evidence['lastPromptObservation']['buttons'][0]['enabled'])

    def test_prompt_verification_finishing_after_original_deadline_never_clicks(self):
        proof=self.proof();Desktop,_,_=self.boundary();clock=[100.];calls=[0]
        def wait(check,seconds=60):
            calls[0]+=1;result=check()
            if calls[0]==3:clock[0]=121.
            return result or (_ for _ in ()).throw(AssertionError('not ready'))
        with patch.object(self.api.time,'monotonic',side_effect=lambda:clock[0]), \
             self.assertRaisesRegex(AssertionError,'Original Calc close-prompt deadline expired'):
            self.invoke(proof,Desktop,waiter=wait)
        self.assertEqual([(10,7)],self.closes);self.assertEqual([],self.clicks)

    def titlebar_boundary(self):
        Desktop,accessible,buttons=self.boundary()
        root=NS(handle=30,process_id=7,runtime_id=[42,30],name='OpenGeul Calc',control_type='Window',parent=None)
        pane=NS(handle=50,process_id=7,runtime_id=[42,50],name='OpenGeul Calc',control_type='Pane',parent=root)
        titlebar=NS(handle=0,process_id=7,runtime_id=[42,30,3,-2147483647,30,-2,0],
            name='None',control_type='TitleBar',parent=root)
        for i,button in enumerate(buttons):
            button.element_info=NS(handle=40+i,process_id=7,runtime_id=[42,40+i],
                name=button.element_info.name,control_type='Button',parent=pane)
        close=NS(element_info=NS(handle=0,process_id=7,runtime_id=[42,30,3,-2147483647,30,-2,5],
            name='Close',control_type='Button',automation_id='',class_name='',parent=titlebar),
            is_visible=lambda:True,is_enabled=lambda:True,
            click_input=lambda:self.fail('Nonclient Close must never be clicked'))
        buttons.append(close);accessible.element_info=root
        self.live.update((40,41,42,50))
        self.pid=lambda h:7 if h in (10,30,40,41,42,50) else 8
        self.windows.user.GetAncestor=lambda h,k:30 if h in (30,40,41,42,50) else h
        return Desktop,accessible,buttons,close,titlebar,pane,root

    def test_actual_native_titlebar_close_is_separate_from_three_client_choices(self):
        proof=self.proof();Desktop,_,_,_,_,_,_=self.titlebar_boundary()
        self.invoke(proof,Desktop,real_ancestry=True)
        self.assertEqual([(10,7)],self.closes);self.assertEqual(['discard'],self.clicks)
        evidence=self.record['verifiedSavedCalcDiscard']
        self.assertEqual(1,evidence['nonclientCloseCount'])
        row=evidence['promptObservations'][0]['buttons'][-1]
        self.assertEqual('native-titlebar-close',row['role'])
        self.assertEqual(['Button','TitleBar','Window'],[x['controlType'] for x in row['ancestry']])
        self.assertTrue(evidence['diskBytesUnchanged'])

    def test_close_label_or_fake_titlebar_never_exempts_an_unexpected_client_action(self):
        for reason in ('client','foreign','wrong-root','wrong-runtime','native-hwnd','automation-id','extra-pane','renamed','duplicate'):
            proof=self.proof();Desktop,_,buttons,close,titlebar,pane,root=self.titlebar_boundary()
            info=close.element_info
            if reason=='client':info.parent=pane
            elif reason=='foreign':titlebar.process_id=999
            elif reason=='wrong-root':titlebar.parent=NS(**dict(vars(root),handle=99,runtime_id=[42,99]))
            elif reason=='wrong-runtime':info.runtime_id=[42,30,123]
            elif reason=='native-hwnd':info.handle=40
            elif reason=='automation-id':info.automation_id='CommandButton_103'
            elif reason=='extra-pane':titlebar.parent=pane
            elif reason=='renamed':info.name='Other action'
            else:buttons.append(close)
            with self.subTest(reason=reason),self.assertRaises(AssertionError):
                self.invoke(proof,Desktop,real_ancestry=True)
            self.assertEqual([(10,7)],self.closes);self.assertEqual([],self.clicks)

    def test_choice_labels_in_nonclient_titlebar_do_not_become_document_actions(self):
        proof=self.proof();Desktop,_,buttons,close,titlebar,_,_=self.titlebar_boundary()
        buttons.remove(close);buttons[0].element_info.parent=titlebar
        with self.assertRaises(AssertionError):self.invoke(proof,Desktop,real_ancestry=True)
        self.assertEqual([(10,7)],self.closes);self.assertEqual([],self.clicks)

    def test_shared_selector_is_readonly_and_retains_exact_client_roles(self):
        self.assertTrue(hasattr(self.api,'require_calc_prompt_buttons'),'The measured close and cleanup must use one read-only selector')
        _,accessible,_,_,_,_,_=self.titlebar_boundary();evidence={}
        buttons=self.api.require_calc_prompt_buttons(self.windows,accessible,7,30,evidence)
        self.assertEqual(['저장','저장하지 않음','취소'],[b.element_info.name for b in buttons])
        self.assertEqual([],self.closes);self.assertEqual([],self.clicks)
        self.assertEqual(1,evidence['nonclientCloseCount']);self.assertTrue(evidence['ready'])

    def raw_titlebar(self,accessible,close,titlebar,root):
        def raw(info,parent,type_):
            return NS(CurrentName=info.name,CurrentProcessId=info.process_id,
                CurrentNativeWindowHandle=info.handle,CurrentControlType=type_,parent=parent,
                GetRuntimeId=lambda:list(info.runtime_id))
        raw_root=raw(root,None,50032);raw_titlebar=raw(titlebar,raw_root,50037)
        raw_close=raw(close.element_info,raw_titlebar,50000)
        accessible.element_info.element=raw_root;close.element_info.element=raw_close
        automation=NS(RawViewWalker=NS(GetParentElement=lambda node:node.parent),CompareElements=lambda a,b:a is b)
        return raw_root,raw_titlebar,raw_close,automation

    def test_skipped_controlview_titlebar_needs_independent_live_rawview_root_proof(self):
        proof=self.proof();Desktop,accessible,_,close,titlebar,_,root=self.titlebar_boundary()
        _,_,_,automation=self.raw_titlebar(accessible,close,titlebar,root)
        close.element_info.parent=root
        with patch.dict(sys.modules,{'pywinauto.uia_defines':NS(IUIA=lambda:NS(iuia=automation))}):
            self.invoke(proof,Desktop,real_ancestry=True)
        self.assertEqual(['discard'],self.clicks)
        row=self.record['verifiedSavedCalcDiscard']['promptObservations'][0]['buttons'][-1]
        self.assertEqual(['Button','Window'],[p['controlType'] for p in row['ancestry']])
        self.assertEqual(['Button','TitleBar','Window'],[p['controlType'] for p in row['rawAncestry']])

    def test_rawview_fallback_never_infers_titlebar_or_accepts_a_lookalike_root(self):
        for reason in ('missing-titlebar','foreign-root','foreign-pid'):
            proof=self.proof();Desktop,accessible,_,close,titlebar,_,root=self.titlebar_boundary()
            raw_root,raw_titlebar,raw_close,automation=self.raw_titlebar(accessible,close,titlebar,root)
            close.element_info.parent=root
            if reason=='missing-titlebar':raw_close.parent=raw_root
            elif reason=='foreign-root':raw_titlebar.parent=NS(**vars(raw_root))
            else:raw_titlebar.CurrentProcessId=999
            with self.subTest(reason=reason),patch.dict(sys.modules,{'pywinauto.uia_defines':NS(IUIA=lambda:NS(iuia=automation))}),self.assertRaises(AssertionError):
                self.invoke(proof,Desktop,real_ancestry=True)
            self.assertEqual([],self.clicks)


if __name__=='__main__':unittest.main()
