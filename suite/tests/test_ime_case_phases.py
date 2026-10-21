"""Real IME case orchestration against finite native/reader boundary doubles."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import korean_ime_smoke as ime
import windows_smoke as native
import test_korean_ime_smoke as fixtures


class IMECasePhaseTests(unittest.TestCase):
    def run_case(self, module, *, fail_context=False, fail_mode=False):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);calls=[];offset=[0.];clock=time.monotonic
        original=root/('OpenGeul-'+module+'.'+dict(ime.INPUT_CASES)[module]);original.write_bytes(b'unchanged fixture')
        process=NS(pid=77);records=[];observer_installed=[False];layout=[0x04090409]
        policy=fixtures.KoreanImePolicyTests();record_template=policy.record()
        observed=dict(text='Engine-OpenGeul-'+module+' 한글 '+ime.marker(module),formula='=SUM(B1:C1)',value=42,pageCount=1)
        user=NS(GetKeyboardLayout=lambda tid:layout[0],GetAsyncKeyState=lambda key:0,GetKeyState=lambda key:0,
            GetWindowThreadProcessId=lambda hwnd,pointer:41,GetForegroundWindow=lambda:11,GetAncestor=lambda hwnd,kind:11,
            IsWindow=lambda hwnd:True,SendInput=lambda count,payload,size:count)
        api=NS(user=user,require_foreground=lambda hwnd:None,require_editor_focus=lambda hwnd,child:51,
            pid=lambda hwnd:31,title=lambda hwnd:'Saved owned document',windows=lambda pid:[])
        image=NS(save=lambda path:None);window=NS(maximize=lambda:None,capture_as_image=lambda:image)
        desktop=NS(window=lambda **kw:NS(wrapper_object=lambda:window))
        class Keyboard:
            def __init__(inner,api,p,hwnd,parent,child,pid,kind,record,deadline):
                inner.api=api;inner.tid=41;inner.focus=51;inner.record=record;inner.binding={'actualFirstAdmission':True};records.append(record)
            def start(inner):calls.append('admission')
            def focus_editor(inner,deadline):calls.append('CTRL_F6')
            def editor_ready(inner,receipt):calls.append('ready')
            def navigate(inner):calls.append(('navigate',module))
            def require_target(inner):return None
            def setup_complete(inner):calls.append('setup-complete')
            def begin_save(inner,restoration,deadline):
                self.assertEqual(restoration,policy.restoration());self.assertTrue(inner.record['layoutRestored'])
                self.assertEqual(deadline,inner.record['imeSaveBudget']['deadline'])
                self.assertAlmostEqual(deadline-inner.record['imeSaveBudget']['startedAt'],30.)
                calls.append('save-budget-started')
            def save(inner):
                self.assertEqual(calls[-1],'save-budget-started')
                if module=='calc':calls.append('ENTER')
                calls.append('CTRL_S');offset[0]+=3.
            def close(inner,primary=None):
                if not getattr(inner,'closed',False):calls.append('keyboard-close');inner.closed=True
        class Observer:
            def __init__(inner,*args,**kw):
                self.assertFalse(observer_installed[0]);observer_installed[0]=True
                ime.require_ascii_prefix(records[0])
                if module=='calc':self.assertIn('reader-natural-cleanup',calls)
                inner.api=api;inner.tid=41;inner.focus=51;inner.commands=[];inner.activation_attempted=False;inner.restored=False
                inner.native_architecture=dict(processMachine=0,nativeMachine=0x8664,processArchitecture='x64',nativeArchitecture='x64')
                inner.target_architecture=dict(inner.native_architecture);calls.append('observer-installed')
            def require_target(inner):return None
            def command(inner,command,**kw):
                calls.append(('command',command))
                if command==4:
                    layout[0]=0x04090409;inner.restored=True;value=policy.restoration()
                else:
                    self.assertEqual(kw['setup_deadline'],records[0]['imeSetupBudget']['deadline'])
                    value=dict(command=command,status=-3 if fail_mode and command==2 else 0,
                        activeLanguage=0x0412,activeClsid=policy.readiness()['profile']['providerClsid'],
                        activeProfile=policy.readiness()['profile']['profileGuid'])
                    if command==1:inner.activation_attempted=True;layout[0]=0x04120412
                inner.commands.append(value)
                if value['status']!=0:raise AssertionError('native command status -3')
                return value
            def events(inner):return record_template['events']
            def pending(inner,expected,after):return True
            def close(inner):calls.append('observer-close')
        def prepare(api,hwnd,child,shell,pid,record,click,enter,**kw):
            record['editorFocusReadiness']={'deadline':record['imeSetupBudget']['deadline']};click();enter();return 51
        def context(suite,source,original_bytes,record,deadline,**kw):
            self.assertFalse(observer_installed[0]);ime.require_ascii_prefix(record)
            calls.append('reader-observation')
            if fail_context:raise RuntimeError('calc context rejected')
            calls.append('reader-natural-cleanup')
        def physical(observer,token,record):record['keyTokens'].append(token);calls.append(('physical',token))
        def wait(predicate,seconds):
            value=predicate()
            self.assertTrue(value,'Unexpected false boundary predicate')
            return value
        def package(source):
            if 'CTRL_S' in calls:
                calls.append('saved-marker-read')
                # Three seconds of simulated original save work are charged.
                self.assertLess(records[0]['imeSaveBudget']['deadline']-(clock()+offset[0]),28.)
            return observed['text']
        def reopen(command,**kw):
            Path(command[-1]).write_text(json.dumps(observed));return NS(returncode=0,stdout=b'',stderr=b'')
        with ExitStack() as stack:
            patchers = [patch.dict('sys.modules',{'pywinauto':NS(Desktop=lambda **kw:desktop)}),
            patch.object(ime,'require_engine_fixture',return_value=original),patch.object(ime,'launch_suite',return_value=process),
            patch.object(ime,'Windows',return_value=api),patch.object(ime,'verified_attachment',return_value=(11,12,22,31)),
            patch.object(ime,'activate_owned_suite'),patch.object(ime,'IMEKeyboardSession',Keyboard),
            patch.object(native,'prepare_editor_focus',side_effect=prepare),patch.object(native,'click_owned_editor'),
            patch.object(ime,'retained_setup_shell',return_value={'originalPopen':True}),patch.object(ime,'observe_calc_setup',side_effect=context),
            patch.object(ime,'CompositionObserver',Observer),patch.object(ime,'physical_key',side_effect=physical),
            patch.object(ime,'wait_for',side_effect=wait),patch.object(ime,'package_text',side_effect=package),
            patch.object(ime,'close_document'),patch.object(ime,'close_home'),patch.object(native,'_verified_saved_calc_close_proof',return_value={'proof':True}),
            patch('calc_model_barrier.baseline_from_ooxml',return_value={'baseline':True}),
            patch.object(ime.subprocess,'run',side_effect=reopen),patch.object(ime,'capture_failure'),
            patch.object(ime,'stop_owned_test_process'),patch.object(ime,'write_result'),
            patch.object(ime.time,'monotonic',side_effect=lambda:clock()+offset[0]),patch.object(ime.ascii_input.time,'sleep')]
            for patcher in patchers:stack.enter_context(patcher)
            error=None;result=None
            try:result=ime.case(root,root,root,policy.readiness(),module,dict(ime.INPUT_CASES)[module])
            except Exception as exc:error=exc
        return calls,records[0],result,error
    def test_all_modules_restore_before_one_existing_save_sequence_and_charge_original_budget(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module):
                calls,record,result,error=self.run_case(module)
                self.assertIsNone(error,repr(error));self.assertTrue(result['imeVerified'])
                self.assertLess(calls.index(('command',4)),calls.index('save-budget-started'))
                expected=['save-budget-started']+(['ENTER'] if module=='calc' else [])+['CTRL_S','keyboard-close','saved-marker-read']
                start=calls.index('save-budget-started');self.assertEqual(calls[start:start+len(expected)],expected)
                self.assertEqual(calls.count('CTRL_S'),1);self.assertEqual(calls.count('ENTER'),int(module=='calc'))
    def test_calc_context_failure_prevents_observer_install_profile_switch_and_save(self):
        calls,record,result,error=self.run_case('calc',fail_context=True)
        self.assertIsInstance(error,RuntimeError);self.assertIn('calc context rejected',str(error))
        self.assertNotIn('observer-installed',calls);self.assertNotIn(('command',1),calls);self.assertNotIn('CTRL_S',calls)
        self.assertIn('keyboard-close',calls)
    def test_impress_minus_three_remains_fatal_and_restores_without_hangul_or_save(self):
        calls,record,result,error=self.run_case('impress',fail_mode=True)
        self.assertIsInstance(error,AssertionError);self.assertIn('-3',str(error))
        self.assertEqual(calls.count(('command',2)),1);self.assertEqual(calls.count(('command',4)),1)
        self.assertFalse(any(isinstance(value,tuple) and value[0]=='physical' for value in calls))
        self.assertNotIn('CTRL_S',calls);self.assertIn('keyboard-close',calls)
