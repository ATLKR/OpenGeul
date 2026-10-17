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

    def invoke(self,proof,Desktop,*,blank=False):
        import lifecycle_smoke as lifecycle
        with patch.dict(sys.modules,{'pywinauto':NS(Desktop=Desktop)}), \
             patch.object(lifecycle,'require_dialog_button_ancestry',return_value=None), \
             patch.object(lifecycle,'dialog_uia_identity',return_value={'pid':7}), \
             patch('windows_smoke.wait_for',side_effect=lambda check,seconds=60:check() or (_ for _ in ()).throw(AssertionError('not ready'))):
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


if __name__=='__main__':unittest.main()
