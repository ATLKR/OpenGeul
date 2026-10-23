"""Four fixed Korean UI entry routes; native boundary doubles are not UI proof."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import test_initial_focus_admission as admission
import test_scenario_editor_shortcuts as scenario_tests
import korean_ui_smoke as smoke


class KoreanUiEntryTests(unittest.TestCase):
    def feature(self):
        self.assertTrue(callable(getattr(smoke,'prepare_korean_ui_focus',None)),
            'Korean UI requires its fixed measured entry program')

    def prepare(self,module,*,mode=None):
        self.feature();temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        helper,f=admission.InitialFocusAdmissionTests().fixture(temporary.name)
        p,b,api,clock,probe,record,attachment=f
        record.update(module=module,case='korean-ui-'+module,stage='prepare-owned-native-focus',
            koreanUiVerified=False,tabbedUiVerified=False)
        clicks=[];sessions=[]
        def factory(api,process,attached,program,owner,deadline,**kwargs):
            self.assertEqual(attached,attachment);self.assertIs(owner,record)
            self.assertEqual(program,'KOREAN_UI_ENTRY');self.assertEqual(deadline,6.)
            value=scenario_tests.scenario.FirstAdmissionEditorSession(api,process,attached,
                program,owner,deadline,probe=probe,clock=clock,**kwargs)
            sessions.append(value);return value
        def click(*args):
            clicks.append(args);clock.now+=.1
            probe.focus=0 if mode=='missing-after-click' else 22
            if mode=='late-click':clock.now=6.
        if mode=='partial':probe.counts=[2]
        if mode=='cleanup':probe.close_result=False
        caught=None
        with patch.object(smoke.time,'monotonic',side_effect=clock),\
             patch.object(smoke.native,'FirstAdmissionEditorSession',side_effect=factory),\
             patch.object(smoke.native,'click_owned_editor',side_effect=click):
            try:focus=smoke.prepare_korean_ui_focus(api,p,11,12,22,88,module,record)
            except BaseException as exc:caught=exc;focus=None
        return f,clicks,sessions,focus,caught

    def test_all_four_modules_use_one_measured_click_one_ctrl_f6_and_same_entry_budget(self):
        for module in ('writer','calc','impress','draw'):
            with self.subTest(module=module):
                f,clicks,sessions,focus,error=self.prepare(module)
                self.assertIsNone(error,repr(error));self.assertEqual(focus,22)
                self.assertEqual(len(clicks),1);self.assertEqual(len(sessions),1)
                receipt=sessions[0].receipt
                self.assertEqual(receipt['expectedProgram'],['CTRL_F6','EDITOR_READY'])
                self.assertEqual([a['shortcut'] for a in receipt['actions']],['CTRL_F6'])
                self.assertEqual(receipt['actions'][0]['requestedInputs'],4)
                self.assertEqual(receipt['actions'][0]['insertedInputs'],4)
                self.assertEqual(receipt['entryDeadline'],receipt['deadline'])
                self.assertEqual(receipt['deadline'],6.)
                self.assertTrue(receipt['success']);self.assertTrue(receipt['engineHandleReleased'])
                self.assertFalse(receipt['deliveryVerified'])
                self.assertTrue(f[5]['nativeInputFocusPrepared']);self.assertEqual(f[5]['keyboardFocusHwnd'],22)
                self.assertFalse(f[5]['koreanUiVerified']);self.assertFalse(f[5]['tabbedUiVerified'])

    def test_missing_focus_after_single_click_does_not_authorize_ctrl_f6_or_retry(self):
        f,clicks,sessions,_,error=self.prepare('calc',mode='missing-after-click')
        self.assertIsInstance(error,AssertionError);self.assertEqual(len(clicks),1)
        self.assertEqual(f[4].sent,[]);self.assertFalse(sessions[0].receipt['success'])
        self.assertNotIn('nativeInputFocusPrepared',f[5]);self.assertTrue(sessions[0].receipt['engineHandleReleased'])

    def test_late_click_cannot_renew_budget_or_begin_ctrl_f6(self):
        f,clicks,sessions,_,error=self.prepare('draw',mode='late-click')
        self.assertIsInstance(error,AssertionError);self.assertEqual(len(clicks),1)
        self.assertEqual(f[4].sent,[]);self.assertEqual(sessions[0].receipt['deadline'],6.)
        self.assertNotIn('nativeInputFocusPrepared',f[5])

    def test_partial_ctrl_f6_stops_without_another_chord_or_ui_qualification(self):
        f,clicks,sessions,_,error=self.prepare('impress',mode='partial')
        self.assertIsInstance(error,AssertionError);self.assertEqual(len(clicks),1)
        self.assertEqual([a['shortcut'] for a in sessions[0].receipt['actions']],['CTRL_F6'])
        self.assertEqual(sessions[0].receipt['actions'][0]['insertedInputs'],2)
        self.assertFalse(sessions[0].receipt['success']);self.assertNotIn('nativeInputFocusPrepared',f[5])
        self.assertEqual(sum(isinstance(c,tuple) and c[0]=='release' for c in f[4].calls),1)

    def test_failed_handle_release_cannot_mark_preparation_ready(self):
        f,_,sessions,_,error=self.prepare('writer',mode='cleanup')
        self.assertIsNotNone(error);self.assertFalse(sessions[0].receipt['success'])
        self.assertNotIn('nativeInputFocusPrepared',f[5])

    def test_unknown_module_cannot_construct_the_fixed_entry_program(self):
        f,clicks,sessions,_,error=self.prepare('base')
        self.assertIsInstance(error,AssertionError)
        self.assertEqual(clicks,[]);self.assertEqual(sessions,[]);self.assertEqual(f[4].sent,[])

    def test_fixed_ui_program_rejects_ascii_save_and_arbitrary_shortcuts(self):
        self.feature()
        for shortcut in ('CTRL_S','CTRL_HOME','ASCII','ESCAPE'):
            with self.subTest(shortcut=shortcut),tempfile.TemporaryDirectory() as directory:
                helper,f=admission.InitialFocusAdmissionTests().fixture(directory);f[4].focus=22
                with self.assertRaises(AssertionError):
                    with helper.session(f,'KOREAN_UI_ENTRY') as session:session.press(shortcut)
                self.assertEqual(f[4].sent,[])

    def test_run_case_routes_all_four_modules_and_probe_mode_through_preparation_before_capture(self):
        self.feature()
        for module,probe_only in ((name,probe) for name in smoke.MODULES for probe in (False,True)):
            with self.subTest(module=module,probe_only=probe_only),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source=root/'source';source.write_bytes(b'unchanged-fixture')
                output=root/'output';output.mkdir();process=NS(pid=77,poll=lambda:0)
                calls=[];engine=NS(creation_time=123,exited=lambda seconds:True,close=lambda:calls.append('engine-close'))
                api=NS(require_foreground=lambda hwnd:None)
                wrapper=NS(maximize=lambda:None,click_input=lambda:self.fail('Legacy unmeasured click reached'),
                    capture_as_image=lambda:self.fail('Capture preceded measured entry'))
                desktop=NS(window=lambda **kwargs:NS(wrapper_object=lambda:wrapper))
                def entry(*args):
                    calls.append(('entry',args[6]));raise RuntimeError('stop-after-measured-entry-route')
                def failure(output,case,record,exc):record['error']=str(exc)
                with ExitStack() as stack:
                    for owner,name,value in ((smoke.native,'require_engine_fixture',lambda *a:source),
                        (smoke.native,'launch_suite',lambda *a:process),(smoke.native,'Windows',lambda:api),
                        (smoke.native,'verified_attachment',lambda *a:(11,12,22,88)),
                        (smoke.startup,'EngineProcessWitness',lambda *a:engine),
                        (smoke.native,'activate_owned_suite',lambda *a:None),
                        (smoke,'prepare_korean_ui_focus',entry),(smoke.native,'capture_failure',failure),
                        (smoke.native,'stop_owned_test_process',lambda *a:None),
                        (smoke.native,'write_result',lambda *a:None)):
                        stack.enter_context(patch.object(owner,name,side_effect=value))
                    stack.enter_context(patch.dict(sys.modules,pywinauto=NS(Desktop=lambda **kwargs:desktop)))
                    record=smoke.run_case(root,root,output,module,probe_only=probe_only)
                self.assertEqual(calls,[('entry',module),'engine-close'])
                self.assertEqual(record['error'],'stop-after-measured-entry-route')
                self.assertFalse(record['koreanUiVerified']);self.assertFalse(record['tabbedUiVerified'])


if __name__=='__main__':unittest.main()
