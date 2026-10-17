"""Failure cleanup is separate from the measured pending-input action."""
import copy
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import test_generated_calc_close as boundary_fixture


class CalcFailureCleanupTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'e2e/calc_failure_cleanup.py'
        self.assertTrue(path.is_file(),'RED: pre-input failure needs an explicit owned-close path')
        self.api=importlib.import_module('calc_failure_cleanup')
        self.fixture=boundary_fixture.GeneratedCalcCloseTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.Desktop,_,self.buttons=self.fixture.boundary()
        f=self.fixture
        f.live.add(15)
        f.windows.user.IsChild=lambda h,c:(h,c) in ((10,15),(15,20),(10,20))
        f.process.args=[str(f.suite/'OpenGeul.Office.exe'),'--module','calc','--file',str(f.source)]
        f.process._handle=77;f.process.opengeul_evidence_case='calc-active-cell-save'
        f.record.update(case='calc-active-cell-save',kind='physical-uncommitted-calc-save',success=False,
            stage='observe-clean-before-input',parentHwnd=15,officePid=8,navigationKeys=[],commitKeys=[],
            saveShortcutCount=0,error='Original getter failure',traceback='original traceback')
        f.exit_code=None
        f.process.poll=lambda:f.exit_code
        f.process.wait=lambda timeout:0
        self.generations={7:9007199254741007,8:9007199254741008}
        self.bound=[];test=self
        class Bound:
            def __init__(self,pid,image):
                self.pid,self.image,self.kernel,self.handle=pid,image,None,pid
                self.creation=test.generations[pid];test.bound.append(self)
            def live(self):return self.pid==7 and f.exit_code is None or self.pid==8 and 20 in f.live
            def close(self):self.handle=None
        def identity(kernel,handle):
            pid=7 if handle==77 else handle
            return ((f.suite/('OpenGeul.Office.exe' if pid==7 else 'Office/program/soffice.bin')).resolve(),self.generations[pid])
        import lifecycle_smoke
        for p in (patch.object(lifecycle_smoke,'BoundHwpProcess',Bound),
                  patch.object(lifecycle_smoke,'process_identity',side_effect=identity),
                  patch.dict(sys.modules,{'pywinauto':NS(Desktop=self.Desktop)}),
                  patch.object(lifecycle_smoke,'require_dialog_button_ancestry',return_value=[{'controlType':'Button','nativeHandle':1},{'controlType':'Window'}]),
                  patch.object(lifecycle_smoke,'dialog_uia_identity',return_value={'pid':7}),
                  patch('windows_smoke.wait_for',side_effect=lambda check,seconds=60:check() or (_ for _ in ()).throw(AssertionError('not ready')))):
            p.start();self.addCleanup(p.stop)
        self.observer=dict(physicalCleanupSucceeded=True,contextQualified=False,cleanupSucceeded=False,
            terminated=False,errors=[],finalJobPids=[],readerMembers=[dict(waitResult=0,exitCode=0)])
        self.proof=self.api.bind_pre_input_cleanup(f.windows,f.process,10,15,20,f.record,f.proof())

    def finish(self,**kwargs):
        f=self.fixture
        def home(api,process,record):
            record['stage']='wait-shell-exit';f.exit_code=0;process.returncode=0
        with patch('windows_smoke.close_home',side_effect=home):
            self.api.finish_pre_input_cleanup(f.windows,f.process,f.record,self.proof,self.observer,**kwargs)

    def test_failed_first_observation_gets_one_explicit_discard_and_keeps_original_failure(self):
        f=self.fixture;original=copy.deepcopy(f.record)
        self.finish()
        self.assertEqual([(10,7)],f.closes);self.assertEqual(['discard'],f.clicks)
        self.assertEqual(f.data,f.source.read_bytes())
        for key in ('stage','error','traceback','success'):self.assertEqual(original[key],f.record[key])
        receipt=f.record['failureCleanup']
        self.assertTrue(receipt['success']);self.assertTrue(receipt['baselineBytesUnchanged'])
        self.assertFalse(receipt['productShutdownQualified'])
        self.assertEqual(9007199254741007,receipt['shellCreationTime'])
        self.assertTrue(all(p.handle is None for p in self.bound))

    def test_close_probe_first_read_has_the_same_separate_cleanup_boundary(self):
        f=self.fixture;f.record.update(case='calc-close-save',kind='physical-calc-uncommitted-close',
            stage='observe-before-input',choice='save',closeShortcutCount=0,beforeCloseActions=[])
        f.record.pop('saveShortcutCount');f.process.opengeul_evidence_case='calc-close-save'
        # The proof belongs to its frozen case; rebinding a later record is forbidden.
        self.finish();self.assertEqual([],f.closes)
        self.assertFalse(f.record['failureCleanup']['success'])
        self.proof=self.api.bind_pre_input_cleanup(f.windows,f.process,10,15,20,f.record,f.proof())
        self.finish();self.assertEqual([(10,7)],f.closes)

    def test_partial_input_or_original_shortcut_never_gets_a_second_close(self):
        f=self.fixture
        for change in (dict(stage='physical-edit-without-enter'),dict(navigationKeys=['^{HOME}']),
                       dict(physicalAsciiMarker='partial'),dict(saveShortcutCount=1),dict(commitKeys=['{ENTER}'])):
            old=copy.deepcopy(f.record);f.record.update(change)
            self.finish();self.assertEqual([],f.closes);self.assertEqual([],f.clicks)
            f.record.clear();f.record.update(old)

    def test_changed_file_native_generation_command_or_host_panel_never_discards(self):
        f=self.fixture
        for reason in ('bytes','generation','command','parent'):
            with self.subTest(reason=reason):
                old_args=list(f.process.args);old_child=f.windows.user.IsChild
                if reason=='bytes':f.source.write_bytes(b'changed')
                elif reason=='generation':self.generations[8]+=1
                elif reason=='command':f.process.args[-1]=str(f.owned/'other.xlsx')
                else:f.windows.user.IsChild=lambda h,c:False
                self.finish();self.assertEqual([],f.closes);self.assertEqual([],f.clicks)
                f.source.write_bytes(f.data);f.process.args=old_args;f.windows.user.IsChild=old_child
                self.generations[8]=9007199254741008
                self.proof=self.api.bind_pre_input_cleanup(f.windows,f.process,10,15,20,f.record,f.proof())

    def test_unproved_forced_or_nonzero_observer_cleanup_never_closes_product(self):
        f=self.fixture
        for change in (dict(physicalCleanupSucceeded=False),dict(terminated=True),dict(finalJobPids=[9]),
                       dict(errors=[{'message':'bad'}]),dict(readerMembers=[dict(waitResult=258,exitCode=259)]),
                       dict(readerMembers=[dict(waitResult=0,exitCode=1)])):
            old=copy.deepcopy(self.observer);self.observer.update(change)
            self.finish();self.assertEqual([],f.closes)
            self.observer=old
            self.proof=self.api.bind_pre_input_cleanup(f.windows,f.process,10,15,20,f.record,f.proof())

    def test_foreign_prompt_preserves_original_error_without_discard_or_retry(self):
        f=self.fixture;f.owner=lambda h,k:999
        self.finish()
        self.assertEqual([(10,7)],f.closes);self.assertEqual([],f.clicks)
        self.assertEqual('Original getter failure',f.record['error'])
        self.assertFalse(f.record['failureCleanup']['success'])

    def test_failed_binding_keeps_primary_error_and_attempts_both_handle_closures(self):
        f=self.fixture;f.record['officePid']=999;closed=[]
        def fail_engine_close(bound):
            closed.append(bound.pid)
            if bound.pid==8:raise OSError('secondary CloseHandle failure')
            bound.handle=None
        with patch.object(type(self.bound[0]),'close',fail_engine_close),self.assertRaises(AssertionError):
            self.api.bind_pre_input_cleanup(f.windows,f.process,10,15,20,f.record,f.proof())
        self.assertEqual([8,7],closed)
        self.assertIn('secondary CloseHandle failure',f.record['preInputCleanupBindingHandleErrors'][0])

    def test_both_real_harnesses_release_observer_then_explicitly_close_before_forced_fallback(self):
        import calc_save_smoke as save
        import calc_close_probe as close
        import lifecycle_smoke as lifecycle
        import windows_smoke as native
        import writer_model_reader
        import writer_style_smoke
        f=self.fixture
        for kind in ('save','close'):
            with self.subTest(kind=kind):
                calls=[];f.exit_code=None
                output=f.root/('physical-'+kind);output.mkdir()
                failure=RuntimeError('first pending getter failed')
                test=self
                class Reader:
                    def __init__(self,*a,**kw):calls.append('reader-created')
                    def start(self,deadline):calls.append('first-read');raise failure
                    def close(self,deadline):calls.append('release-observer');return test.observer
                def bind(api,process,hwnd,parent,child,record,saved):
                    self.assertEqual('calc',record.get('module'))
                    self.assertEqual(f.data,saved.path.read_bytes())
                    calls.append('bind-before-observer');return object()
                def finish(api,process,record,proof,observer):
                    self.assertIs(observer,self.observer)
                    self.assertIn('first pending getter failed',record['error'])
                    self.assertFalse(record['success'])
                    calls.append('explicit-close');f.exit_code=0
                    record['failureCleanup']={'success':True,'productShutdownQualified':False}
                noop=lambda *a,**kw:None
                window=NS(maximize=noop,set_focus=noop,capture_as_image=lambda:NS(save=noop))
                desktop=lambda **kw:NS(window=lambda **kw:NS(wrapper_object=lambda:window))
                f.windows.user.GetAncestor=lambda h,k:10
                f.windows.user.GetForegroundWindow=lambda:10
                patches=(patch.dict(sys.modules,{'pywinauto':NS(Desktop=desktop),
                                'pywinauto.keyboard':NS(send_keys=lambda *a,**kw:self.fail('No test input was authorized'))}),
                    patch.object(save,'require_engine_fixture',return_value=f.source),
                    patch.object(native,'require_engine_fixture',return_value=f.source),
                    patch.object(save,'launch_suite',return_value=f.process),
                    patch.object(native,'launch_suite',return_value=f.process),
                    patch.object(save,'Windows',return_value=f.windows),
                    patch.object(lifecycle,'LifecycleWindows',return_value=f.windows),
                    patch.object(save,'verified_attachment',return_value=(10,15,20,8)),
                    patch.object(native,'verified_attachment',return_value=(10,15,20,8)),
                    patch.object(save,'prepare_editor_focus',side_effect=noop),
                    patch.object(native,'prepare_editor_focus',side_effect=noop),
                    patch.object(lifecycle,'retained_writer_shell',return_value=9007199254741007),
                    patch.object(writer_style_smoke,'_packaged_identity_file',return_value=({'sha256':'a'*64},b'{}')),
                    patch.object(writer_model_reader,'OwnedModelReader',Reader),
                    patch.object(close.CalcCloseCase,'screenshot',side_effect=noop),
                    patch.object(self.api,'bind_pre_input_cleanup',side_effect=bind),
                    patch.object(self.api,'finish_pre_input_cleanup',side_effect=finish),
                    patch.object(native.subprocess,'run',side_effect=lambda *a,**kw:self.fail('Forced fallback preceded explicit cleanup')))
                from contextlib import ExitStack
                with ExitStack() as stack:
                    for p in patches:stack.enter_context(p)
                    with self.assertRaisesRegex(RuntimeError,'first pending getter failed'):
                        if kind=='save':save.physical_case(f.suite,f.owned,output)
                        else:close.CalcCloseCase(f.suite,f.owned,output,'save').run()
                self.assertEqual(['bind-before-observer','reader-created','first-read','release-observer','explicit-close'],calls)


if __name__=='__main__':unittest.main()
