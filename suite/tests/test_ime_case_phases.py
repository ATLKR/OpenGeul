"""Real IME case orchestration against finite native/reader boundary doubles."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import korean_ime_smoke as ime
import windows_smoke as native
import activation_failure_diagnostics as failure_native
import test_korean_ime_smoke as fixtures
from ascii_observer_boundary import AsciiObserverBoundary


class IMECasePhaseTests(unittest.TestCase):
    def run_case(self, module, *, fail_context=False, fail_mode=False, fail_semantic=None, empty_retirement_failure=False,
                 focus_failure=None, diagnostic_error=None, fail_navigation=False, diagnose_navigation=False,
                 save_cleanup_reserve=0):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);calls=[];offset=[0.];clock=time.monotonic
        original=root/('OpenGeul-'+module+'.'+dict(ime.INPUT_CASES)[module]);original.write_bytes(b'unchanged fixture')
        process=NS(pid=77);records=[];observer_installed=[False];layout=[0x04090409];prepared=object()
        binding=dict(shellPid=77,officePid=31,suiteHwnd=11,parentHwnd=12,childHwnd=22,rootHwnd=11,
            shellCreationTime=2**55,officeCreationTime=2**55+100,expectedImage=str(root/'Office/program/soffice.bin'))
        policy=fixtures.KoreanImePolicyTests();record_template=policy.record()
        if empty_retirement_failure:
            from ime_typed_policy_fixtures import complete_record
            complete_record(record_template,empty=True)
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
                inner.api=api;inner.process=p;inner.tid=41;inner.focus=51;inner.record=record;inner.binding=binding;records.append(record)
                record['imeKeyboardSession']={'expectedNative':dict(binding)}
            def start(inner):calls.append('admission')
            def focus_editor(inner,deadline):calls.append('CTRL_F6')
            def editor_ready(inner,receipt):calls.append('ready')
            def navigate(inner):
                calls.append(('navigate',module))
                if focus_failure is not None:raise focus_failure
            def navigate_calc(inner,suite,source,original_bytes,**kw):
                self.assertEqual(module,'calc')
                self.assertEqual(suite,root);self.assertEqual(original_bytes,b'unchanged fixture')
                self.assertEqual(kw['original_shell'],{'originalPopen':True})
                calls.extend(['calc-navigation-start0','CTRL_HOME','calc-navigation-read1','calc-navigation-release2'])
                if fail_navigation:raise RuntimeError('Calc source A1 navigation rejected')
                inner.record['calcNavigationContext']={'success':True}
                inner.navigate()
            def require_target(inner):return None
            def require_context_target(inner,key):
                self.assertIn(key,inner.record);calls.append(('reader-guard',key))
            def require_prefix_ready(inner):calls.append('prefix-ready')
            def semantic_ready(inner,context,*,phase):
                self.assertIs(context,inner.record['imeSemanticContext'])
                calls.append(('semantic-ready',phase))
            def setup_complete(inner):
                inner.record['imeKeyboardSession']['setupFinishedAt']=clock()+offset[0]
                calls.append('setup-complete')
            def begin_save(inner,restoration,deadline):
                ime.validate_restoration(restoration);ime.require_ime_save_disposition(inner.record,restoration)
                self.assertEqual(restoration,inner.record['restoration']);self.assertTrue(inner.record['layoutRestored'])
                self.assertEqual(deadline,inner.record['imeSaveBudget']['deadline']-save_cleanup_reserve)
                self.assertAlmostEqual(deadline-inner.record['imeSaveBudget']['startedAt'],30.-save_cleanup_reserve)
                calls.append('save-budget-started')
            def save(inner):
                self.assertEqual(calls[-1],'save-budget-started')
                if module=='calc':calls.append('ENTER')
                calls.append('CTRL_S');offset[0]+=3.
            def close(inner,primary=None):
                if not getattr(inner,'closed',False):calls.append('keyboard-close');inner.closed=True
        class NavigationTrace:
            def __init__(inner,api_arg,process_arg,binding_arg,prepared_arg,record,deadline):
                self.assertIs(process_arg,process);self.assertEqual(binding_arg,binding)
                self.assertIs(prepared_arg,prepared)
                self.assertEqual(deadline,record['imeSetupBudget']['deadline'])
                inner.record=record;inner.closed=False
                record['navigationDiagnostic']={'acceptanceEligible':False}
            def start(inner):calls.append('navigation-trace-start')
            def close(inner,primary=None):
                if inner.closed:return
                inner.closed=True
                calls.append('navigation-trace-snapshot')
                inner.record['navigationDiagnostic']['snapshot']={'status':'complete','events':[]}
                calls.append('navigation-trace-close')
        class Observer:
            def __init__(inner,*args,**kw):
                self.assertFalse(observer_installed[0]);observer_installed[0]=True
                ime.require_ascii_prefix(records[0])
                if module=='calc':self.assertIn('reader-natural-cleanup',calls)
                inner.api=api;inner.tid=41;inner.focus=51;inner.commands=[];inner.activation_attempted=False;inner.restored=False
                inner.native_architecture=dict(processMachine=0,nativeMachine=0x8664,processArchitecture='x64',nativeArchitecture='x64')
                inner.target_architecture=dict(inner.native_architecture);calls.append('observer-installed')
            @property
            def restoration_required(inner):return inner.activation_attempted
            def require_target(inner):return None
            def command(inner,command,**kw):
                calls.append(('command',command))
                if command==4:
                    layout[0]=0x04090409;inner.restored=True;value=copy.deepcopy(record_template['imeCommands'][3])
                else:
                    self.assertEqual(kw['setup_deadline'],records[0]['imeSetupBudget']['deadline'])
                    value=copy.deepcopy(record_template['imeCommands'][command-1])
                    value['status']=-3 if fail_mode and command==2 else 0
                    if command==1:inner.activation_attempted=True;layout[0]=0x04120412
                value['startedAt']=clock()+offset[0]
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
            record['calcSetupContext']={'actualReaderContext':True};kw['require_current']()
            calls.append('reader-observation')
            if fail_context:raise RuntimeError('calc context rejected')
            calls.append('reader-natural-cleanup')
        def semantic(suite,source,original_bytes,record,deadline,**kw):
            self.assertFalse(observer_installed[0]);phase=kw['phase']
            self.assertEqual(deadline,record['imeSetupBudget']['deadline'])
            self.assertEqual(kw['expected_native'],binding)
            self.assertEqual(kw['original_shell'],{'originalPopen':True})
            from ime_typed_policy_fixtures import profile_context
            context=profile_context(binding,deadline);context.update(success=False,phase=phase)
            record['imeSemanticContext']=context;kw['require_current']()
            if phase=='pre':self.assertFalse(record.get('asciiEditorInputs'));self.assertIsNone(kw.get('expected_prefix'))
            else:
                ime.require_ascii_prefix(record);self.assertEqual(kw['expected_prefix'],record['asciiPrefix'])
            calls.append(('semantic-read',phase))
            if fail_semantic==phase:raise RuntimeError('semantic '+phase+' rejected')
            calls.append(('semantic-natural-cleanup',phase))
            context['success']=True
            record.setdefault('imeSemanticContexts',[]).append(context);record['imeSemanticContext']=context
            return context
        original_ascii=ime.ascii_input.type_ascii
        def type_ascii(*args,**kw):
            self.assertIs(kw['original_popen'],process);self.assertIs(kw['native_binding'],binding)
            self.assertIs(kw['prepared_library'],prepared)
            self.assertEqual(kw['deadline'],records[0]['imeSetupBudget']['deadline']);self.assertEqual(kw['pause'],.04)
            calls.append('ascii-forward');return original_ascii(*args,**kw)
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
            calls.append('independent-reopen')
            Path(command[-1]).write_text(json.dumps(observed));return NS(returncode=0,stdout=b'',stderr=b'')
        class Retirement:
            closed=False
            close_attempted=False
            def close(inner,primary=None):
                if not inner.closed:calls.append('retirement-close');inner.closed=True;inner.close_attempted=True
            def cleanup_failed(inner,primary):
                self.assertFalse(inner.closed)
                calls.append(('failure-teardown',primary));calls.append('final-stop');inner.close(primary)
            def verify_after_close_home(inner,**kw):
                self.assertTrue(empty_retirement_failure);self.assertEqual(calls[-1],'home-close')
                calls.append('first-retirement-wait');inner.close();raise RuntimeError('original engine not signaled at first observation')
        def admit_retirement(**kw):
            self.assertIs(kw['original_shell'],process)
            self.assertEqual(kw['setup_deadline'],records[0]['imeSetupBudget']['deadline'])
            self.assertIn('setup-complete',calls);self.assertNotIn(('command',1),calls)
            if empty_retirement_failure:
                records[0]['imeEngineRetirement']={'admission':dict(startedAt=clock()+offset[0],finishedAt=clock()+offset[0],editorTid=41,focusHwnd=51)}
            calls.append('retirement-admitted');return Retirement()
        def capture_failure(output,name,record,exc):
            calls.append('capture-failure')
            record.update(success=False,error=type(exc).__name__+': '+str(exc),
                traceback=''.join(traceback.format_exception(type(exc),exc,exc.__traceback__)))
        def collect_failure(*args,**kw):
            calls.append('failure-observation')
            self.assertEqual(args,(11,77,41,0));self.assertEqual(kw,{})
            self.assertEqual(records[0]['stage'],'focus-editor')
            self.assertIn('error',records[0]);self.assertIn('traceback',records[0])
            self.assertLess(calls.index('capture-failure'),calls.index('failure-observation'))
            if diagnostic_error is not None:raise diagnostic_error
            return dict(kind='activation-failure-native-diagnostics',actionOutcomeUnaffected=True)
        with ExitStack() as stack:
            # This suite checks case orchestration. The separate real-provider
            # fixture tests replay the actual admission/final proof validators.
            # The semantic observer/qualifier is a boundary double here; public
            # typed tests independently run the complete real PRE/POST replay.
            patchers = [patch.dict('sys.modules',{'pywinauto':NS(Desktop=lambda **kw:desktop),'ime_engine_retirement':NS(admit_ime_retirement=admit_retirement,require_ime_retirement_admission=lambda proof,**kw:proof)}),
            patch.dict('sys.modules',{'navigation_diagnostic':NS(NavigationTrace=NavigationTrace,stop_navigation_keyboard=lambda keyboard: keyboard.close(RuntimeError('intentional diagnostic stop')))}),
            patch.object(ime,'original_ime_profile',return_value={'testOnlySemanticBoundary':True}),
            patch.dict(ime.os.environ,{'OPENGEUL_SUITE_DIAGNOSTICS':str(root/'diagnostics')}),
            patch.object(ime,'require_engine_fixture',return_value=original),patch.object(ime,'launch_suite',return_value=process),
            patch.object(ime,'Windows',return_value=api),patch.object(ime,'verified_attachment',return_value=(11,12,22,31)),
            patch.object(ime,'activate_owned_suite'),patch.object(ime,'IMEKeyboardSession',Keyboard),
            patch.object(native,'prepare_editor_focus',side_effect=prepare),patch.object(native,'click_owned_editor'),
            patch.object(ime,'retained_setup_shell',return_value={'originalPopen':True}),patch.object(ime,'observe_calc_setup',side_effect=context),
            patch.object(ime.ascii_input,'type_ascii',side_effect=type_ascii),patch.object(ime.ascii_input,'_observer',side_effect=AsciiObserverBoundary),
            patch.object(ime,'observe_ime_semantic_setup',side_effect=semantic,create=True),
            patch.object(ime,'CompositionObserver',Observer),patch.object(ime,'physical_key',side_effect=physical),
            patch.object(ime,'wait_for',side_effect=wait),patch.object(ime,'package_text',side_effect=package),
            patch.object(ime,'close_document'),patch.object(ime,'close_home',side_effect=lambda *a:calls.append('home-close')),patch.object(native,'_verified_saved_calc_close_proof',return_value={'proof':True}),
            patch('calc_model_barrier.baseline_from_ooxml',return_value={'baseline':True}),
            patch.object(ime.subprocess,'run',side_effect=reopen),patch.object(ime,'capture_failure',side_effect=capture_failure),
            patch.object(failure_native,'collect_failure_diagnostics',side_effect=collect_failure),
            patch.object(ime,'stop_owned_test_process',side_effect=lambda *a:calls.append('final-stop')),patch.object(ime,'write_result'),
            patch.object(ime.time,'monotonic',side_effect=lambda:clock()+offset[0]),patch.object(ime.ascii_input.time,'sleep')]
            for patcher in patchers:stack.enter_context(patcher)
            error=None;result=None
            try:result=ime.case(root,root,root,policy.readiness(),module,dict(ime.INPUT_CASES)[module],prepared_library=prepared,diagnose_navigation=diagnose_navigation)
            except Exception as exc:error=exc
        return calls,records[0],result,error
    def test_pre_and_post_semantic_cleanup_bracket_one_prefix_before_observer(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module):
                calls,record,result,error=self.run_case(module)
                self.assertIsNone(error,repr(error))
                before=calls.index(('semantic-natural-cleanup','pre'))
                prefix=calls.index('prefix-ready');after=calls.index(('semantic-natural-cleanup','post'))
                self.assertLess(before,prefix);self.assertLess(prefix,after);self.assertLess(after,calls.index('observer-installed'))
                self.assertLess(calls.index(('semantic-ready','post')),calls.index(('command',1)))
                self.assertEqual(len(record['asciiEditorInputs']),1)
    def test_calc_source_navigation_and_cleanup_precede_semantic_prefix_and_observer(self):
        calls,record,result,error=self.run_case('calc')
        self.assertIsNone(error,repr(error))
        self.assertIn('calc-navigation-start0',calls,'Calc production path skipped its source barrier')
        self.assertLess(calls.index('calc-navigation-start0'),calls.index('CTRL_HOME'))
        self.assertLess(calls.index('CTRL_HOME'),calls.index('calc-navigation-read1'))
        self.assertLess(calls.index('calc-navigation-read1'),calls.index('calc-navigation-release2'))
        self.assertLess(calls.index('calc-navigation-release2'),calls.index(('semantic-read','pre')))
        self.assertTrue(record['calcNavigationContext']['success'])
    def test_calc_failed_source_navigation_stops_before_semantic_prefix_or_observer(self):
        calls,record,result,error=self.run_case('calc',fail_navigation=True)
        self.assertIsInstance(error,RuntimeError)
        self.assertIn('Calc source A1 navigation rejected',str(error))
        self.assertNotIn(('semantic-read','pre'),calls)
        self.assertNotIn('prefix-ready',calls);self.assertNotIn('observer-installed',calls)
        self.assertNotIn('CTRL_S',calls);self.assertIn('keyboard-close',calls)
    def test_pre_or_post_semantic_failure_blocks_observer_korean_and_save_without_prefix_retry(self):
        for phase in ('pre','post'):
            with self.subTest(phase=phase):
                calls,record,result,error=self.run_case('writer',fail_semantic=phase)
                self.assertIsInstance(error,RuntimeError);self.assertIn('semantic '+phase+' rejected',str(error))
                self.assertNotIn('observer-installed',calls);self.assertNotIn(('command',1),calls);self.assertNotIn('CTRL_S',calls)
                self.assertEqual(calls.count('prefix-ready'),int(phase=='post'))
                self.assertEqual(len(record.get('asciiEditorInputs',[])),int(phase=='post'))
    def test_all_reader_callbacks_use_their_existing_context_cap(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module):
                calls,record,result,error=self.run_case(module);self.assertIsNone(error,repr(error))
                guarded=[row[1] for row in calls if isinstance(row,tuple) and row[0]=='reader-guard']
                self.assertEqual(guarded,['imeSemanticContext','imeSemanticContext']+(['calcSetupContext'] if module=='calc' else []))
    def test_ascii_prefix_forwards_original_process_binding_descriptor_and_setup_deadline(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module):
                calls,record,result,error=self.run_case(module);self.assertIsNone(error,repr(error))
                self.assertEqual(calls.count('ascii-forward'),1)
                self.assertEqual(len(record['asciiMessageObservers']),1)
                self.assertTrue(record['asciiMessageObservers'][0]['success'])
                self.assertIs(record['asciiMessageObservers'][0]['semanticInsertionProved'],False)
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
    def test_failed_composition_teardown_retains_handle_and_primary(self):
        calls,record,result,error=self.run_case('impress',fail_mode=True)
        failures=[v for v in calls if isinstance(v,tuple) and v[0]=='failure-teardown']
        self.assertEqual(len(failures),1);self.assertIs(failures[0][1],error)
        self.assertLess(calls.index('keyboard-close'),calls.index(failures[0]))
        self.assertLess(calls.index('final-stop'),calls.index('retirement-close'))
        self.assertEqual(calls.count('final-stop'),1);self.assertIsNone(result)
        self.assertNotIn('independent-reopen',calls)
    def test_empty_origin_first_observation_failure_blocks_reopen_and_closes_before_force(self):
        calls,record,result,error=self.run_case('writer',empty_retirement_failure=True)
        self.assertIsInstance(error,RuntimeError);self.assertIn('first observation',str(error))
        self.assertLess(calls.index('retirement-admitted'),calls.index(('command',1)))
        self.assertLess(calls.index('home-close'),calls.index('first-retirement-wait'))
        self.assertLess(calls.index('first-retirement-wait'),calls.index('retirement-close'))
        self.assertLess(calls.index('retirement-close'),calls.index('final-stop'))
        self.assertNotIn('independent-reopen',calls);self.assertIsNone(result)
    def test_focus_failure_collects_once_after_primary_capture_before_cleanup_in_each_module(self):
        for module in ('writer','calc','impress'):
            with self.subTest(module=module):
                primary=RuntimeError('original focus guard rejected')
                calls,record,result,error=self.run_case(module,focus_failure=primary)
                self.assertIs(error,primary);self.assertIsNone(result)
                self.assertEqual(record['stage'],'focus-editor');self.assertFalse(record['success'])
                self.assertIn('original focus guard rejected',record['error'])
                self.assertIn('raise focus_failure',record['traceback'])
                self.assertEqual(calls.count('failure-observation'),1)
                self.assertLess(calls.index('failure-observation'),calls.index('keyboard-close'))
                self.assertLess(calls.index('keyboard-close'),calls.index('final-stop'))
                self.assertEqual(record['keyTokens'],[]);self.assertNotIn('observer-installed',calls)
                self.assertNotIn(('command',1),calls);self.assertNotIn('CTRL_S',calls)
                receipt=record['imeFocusFailureDiagnostics']
                self.assertTrue(receipt['actionOutcomeUnaffected']);self.assertFalse(receipt['historicalScopeJoined'])
                self.assertEqual(receipt['status'],'retained')
    def test_secondary_base_exceptions_cannot_replace_the_actual_focus_failure_or_cleanup(self):
        class Unprintable(BaseException):
            def __str__(self):raise SystemExit('formatting must remain secondary')
        for secondary in (KeyboardInterrupt('observer interrupted'),SystemExit(8),Unprintable()):
            with self.subTest(secondary=type(secondary).__name__):
                primary=RuntimeError('original focus guard rejected')
                calls,record,result,error=self.run_case('writer',focus_failure=primary,diagnostic_error=secondary)
                self.assertIs(error,primary);self.assertIsNone(result)
                self.assertEqual(record['error'],'RuntimeError: original focus guard rejected')
                self.assertIn('raise focus_failure',record['traceback'])
                self.assertEqual(calls.count('failure-observation'),1)
                self.assertIn('keyboard-close',calls);self.assertIn('final-stop',calls)
                self.assertEqual(record['imeFocusFailureDiagnostics']['status'],'unavailable')
    def test_success_and_later_reader_failure_do_not_collect_focus_diagnostics(self):
        for options in ({},{'fail_semantic':'pre'},{'fail_semantic':'post'}):
            with self.subTest(options=options):
                calls,record,result,error=self.run_case('writer',**options)
                self.assertEqual(error is None,not options)
                self.assertNotIn('failure-observation',calls)
                self.assertNotIn('imeFocusFailureDiagnostics',record)


    def test_navigation_diagnostic_brackets_original_navigation_pre_only(self):
        calls,record,result,error=self.run_case('impress',diagnose_navigation=True)
        self.assertIsNone(error,repr(error));self.assertTrue(result['success'])
        self.assertFalse(result['acceptanceEligible']);self.assertFalse(result['imeVerified'])
        self.assertLess(calls.index('ready'),calls.index('navigation-trace-start'))
        self.assertLess(calls.index('navigation-trace-start'),calls.index(('navigate','impress')))
        self.assertLess(calls.index(('semantic-natural-cleanup','pre')),calls.index('navigation-trace-snapshot'))
        self.assertLess(calls.index('navigation-trace-close'),calls.index('home-close'))
        self.assertEqual(calls.count('navigation-trace-snapshot'),1)
        for value in ('ascii-forward','observer-installed','CTRL_S',('semantic-read','post')):self.assertNotIn(value,calls)

    def test_navigation_diagnostic_failure_snapshots_before_capture_and_no_retry(self):
        calls,record,result,error=self.run_case('impress',diagnose_navigation=True,fail_semantic='pre')
        self.assertIsInstance(error,RuntimeError);self.assertIn('semantic pre rejected',str(error))
        self.assertLess(calls.index('navigation-trace-snapshot'),calls.index('capture-failure'))
        self.assertEqual(calls.count(('navigate','impress')),1)
        self.assertEqual(calls.count('navigation-trace-snapshot'),1)
        self.assertFalse(record['acceptanceEligible']);self.assertFalse(record['success'])
        self.assertNotIn('ascii-forward',calls);self.assertNotIn('observer-installed',calls)

    def test_writer_navigation_reuses_trace_and_stops_before_extra_input(self):
        for fail in (None,'pre'):
            calls,record,result,error=self.run_case('writer',diagnose_navigation=True,fail_semantic=fail)
            self.assertEqual(error is None,fail is None,repr(error))
            self.assertEqual(calls.count(('navigate','writer')),1)
            self.assertLess(calls.index('ready'),calls.index('navigation-trace-start'))
            self.assertLess(calls.index('navigation-trace-start'),calls.index(('navigate','writer')))
            self.assertEqual(calls.count('navigation-trace-snapshot'),1)
            self.assertFalse(record['acceptanceEligible'])
            for value in ('ascii-forward','observer-installed','CTRL_S',('semantic-read','post')):self.assertNotIn(value,calls)
            if fail:self.assertLess(calls.index('navigation-trace-snapshot'),calls.index('capture-failure'))

    def test_default_case_never_installs_navigation_trace(self):
        calls,record,result,error=self.run_case('impress')
        self.assertIsNone(error,repr(error));self.assertTrue(result['imeVerified'])
        self.assertNotIn('navigation-trace-start',calls);self.assertNotIn('navigationDiagnostic',record)



class IMEFocusFailureDiagnosticTests(unittest.TestCase):
    def context(self):
        binding=dict(shellPid=77,officePid=31,suiteHwnd=11,parentHwnd=12,childHwnd=22,
            rootHwnd=11,shellCreationTime=2**55,officeCreationTime=2**55+100)
        record=dict(stage='focus-editor',success=False,error='original error',traceback='original traceback',
            shellPid=77,officePid=31,windowHwnd=11,parentHwnd=12,childHwnd=22,
            imeKeyboardSession={'expectedNative':dict(binding),'lastGuardObservation':{'scope':{
                'before':{'foreground':{'rootHwnd':28}},'after':{'foreground':{'rootHwnd':29}}}}})
        return record,NS(pid=77),NS(binding=binding,tid=41)
    def test_raw_collector_receipt_and_original_failure_are_preserved_with_explicit_provenance(self):
        record,process,keyboard=self.context();before=copy.deepcopy(record)
        raw=dict(kind='activation-failure-native-diagnostics',actionOutcomeUnaffected=True,foreignWindows=[{'pid':99}])
        with patch.object(failure_native,'collect_failure_diagnostics',return_value=raw) as collect:
            ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
            first=record['imeFocusFailureDiagnostics']
            ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
            self.assertIs(record['imeFocusFailureDiagnostics'],first)
        collect.assert_called_once_with(11,77,41,29)
        receipt=record.pop('imeFocusFailureDiagnostics')
        self.assertEqual(record,before);self.assertIs(receipt['observation'],raw)
        self.assertFalse(receipt['historicalScopeJoined']);self.assertTrue(receipt['actionOutcomeUnaffected'])
        self.assertIn('failure-time separate observation',receipt['observationScope'])
        self.assertEqual(receipt['foreignRootHintSource'],'lastGuardObservation.scope.after.foreground.rootHwnd')
        self.assertEqual(receipt['originalBinding'],keyboard.binding)
    def test_missing_guard_has_no_invented_hint_and_unknown_thread_remains_zero(self):
        record,process,keyboard=self.context();record['imeKeyboardSession'].pop('lastGuardObservation');keyboard.tid=None
        with patch.object(failure_native,'collect_failure_diagnostics',return_value={}) as collect:
            ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
        collect.assert_called_once_with(11,77,0,0)
        self.assertEqual(record['imeFocusFailureDiagnostics']['foreignRootHintSource'],'unavailable')
    def test_once_only_includes_unavailable_attempt_and_never_retries_after_context_repair(self):
        record,process,keyboard=self.context();keyboard.binding['shellPid']=78
        with patch.object(failure_native,'collect_failure_diagnostics') as collect:
            ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
            first=copy.deepcopy(record['imeFocusFailureDiagnostics']);keyboard.binding['shellPid']=77
            ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
        collect.assert_not_called();self.assertEqual(record['imeFocusFailureDiagnostics'],first)
        self.assertEqual(first['status'],'unavailable')
    def test_foreign_hint_rejects_boolean_or_owned_root_and_falls_back_without_inventing_identity(self):
        for candidate in (True,0,-1,2**64,11):
            with self.subTest(candidate=candidate):
                record,process,keyboard=self.context()
                record['imeKeyboardSession']['lastGuardObservation']['scope']['after']['foreground']['rootHwnd']=candidate
                with patch.object(failure_native,'collect_failure_diagnostics',return_value={}) as collect:
                    ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
                collect.assert_called_once_with(11,77,41,28)
                self.assertEqual(record['imeFocusFailureDiagnostics']['foreignRootHintSource'],
                    'lastGuardObservation.scope.before.foreground.rootHwnd')
    def test_invalid_original_context_never_issues_a_native_query(self):
        for field,value in [('suiteHwnd',True),('childHwnd',0),('officePid',2**32),('shellCreationTime',0)]:
            with self.subTest(field=field):
                record,process,keyboard=self.context();keyboard.binding[field]=value
                with patch.object(failure_native,'collect_failure_diagnostics') as collect:
                    ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
                collect.assert_not_called();self.assertEqual(record['imeFocusFailureDiagnostics']['status'],'unavailable')
    def test_other_stage_success_or_unretained_primary_never_queries(self):
        for change in ({'stage':'actual-uno-reopen'},{'success':True},{'traceback':None}):
            with self.subTest(change=change):
                record,process,keyboard=self.context();record.update(change)
                with patch.object(failure_native,'collect_failure_diagnostics') as collect:
                    ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
                collect.assert_not_called()
    def test_oversize_or_nonserializable_result_cannot_break_final_failure_retention(self):
        for raw in ({'large':'x'*failure_native.MAX_BYTES},{'bad':object()}):
            with self.subTest(rawType=next(iter(raw))):
                record,process,keyboard=self.context()
                with patch.object(failure_native,'collect_failure_diagnostics',return_value=raw) as collect:
                    ime.retain_ime_focus_failure_diagnostics(record,process,keyboard)
                collect.assert_called_once()
                receipt=record['imeFocusFailureDiagnostics']
                self.assertEqual(receipt['status'],'unavailable');self.assertNotIn('observation',receipt)
                self.assertLessEqual(len(json.dumps(receipt,ensure_ascii=False).encode()),failure_native.MAX_BYTES)
                self.assertEqual(record['error'],'original error');self.assertEqual(record['traceback'],'original traceback')


class IMECohortPreparationTests(unittest.TestCase):
    def run_main(self, architecture='x64', *, preparation_failure=False):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name).resolve();suite=root/'Suite';suite.mkdir();fixture=root/'fixtures';fixture.mkdir()
        output=root/'evidence';readiness=root/'readiness.json'
        (suite/'suite-inventory.json').write_text(json.dumps(dict(schemaVersion=1,architecture=architecture)))
        value=fixtures.KoreanImePolicyTests().readiness();machine={'x64':0x8664,'arm64':0xaa64}[architecture]
        value['nativeMachine']=machine;value['controllerMachine']=0;value.setdefault('source',{})['architecture']=architecture
        value['profile']['component']['machine']=machine;readiness.write_text(json.dumps(value))
        descriptor=object();calls=[]
        def prepare(folder,*,architecture):
            self.assertEqual(folder,output/'ascii-observer-preparation');self.assertTrue(output.is_dir())
            calls.append(('prepare',architecture))
            if preparation_failure:raise RuntimeError('bounded native preparation failed')
            return descriptor
        def case(*args,prepared_library):
            self.assertIs(prepared_library,descriptor);self.assertEqual(calls[0],('prepare',architecture))
            calls.append(('case',args[4]));return dict(success=True,imeVerified=True)
        native_arch=dict(processMachine=0,nativeMachine=machine,processArchitecture=architecture,nativeArchitecture=architecture)
        with patch.object(ime,'os',NS(name='nt')),patch.object(ime.native_arch,'observe_native_architecture',return_value=native_arch),patch.object(ime.ascii_input,'prepare_observer',side_effect=prepare,create=True),patch.object(ime,'case',side_effect=case):
            error=None;result=None
            try:result=ime.main(['--suite',str(suite),'--fixtures',str(fixture),'--readiness',str(readiness),'--output',str(output)])
            except Exception as exc:error=exc
        return calls,result,error
    def test_temp_alias_is_canonicalized_before_preparation_expectations(self):
        # Real lexical aliases replay the resolve-before-expectation boundary
        # exposed by Windows long/8.3 temporary names, without symlink privileges.
        for architecture,failed in (('x64',False),('arm64',False),('x64',True)):
            with self.subTest(architecture=architecture,preparation_failure=failed):
                with tempfile.TemporaryDirectory() as directory:
                    parent=Path(directory).resolve();(parent/'bridge').mkdir();(parent/'case').mkdir()
                    alias=parent/'bridge'/'..'/'case'
                    self.assertNotEqual(alias,alias.resolve())
                    temporary=NS(name=str(alias),cleanup=lambda:None)
                    with patch.object(tempfile,'TemporaryDirectory',return_value=temporary):
                        calls,result,error=self.run_main(architecture,preparation_failure=failed)
                    if failed:
                        self.assertIsInstance(error,RuntimeError)
                        self.assertIn('bounded native preparation failed',str(error))
                        self.assertEqual(calls,[('prepare',architecture)])
                    else:
                        self.assertIsNone(error,repr(error));self.assertEqual(result,0)
                        self.assertEqual(calls,[('prepare',architecture),('case','writer'),('case','calc'),('case','impress')])
    def test_prepare_once_before_all_original_case_setup_phases_for_both_architectures(self):
        for architecture in ('x64','arm64'):
            with self.subTest(architecture=architecture):
                calls,result,error=self.run_main(architecture)
                self.assertIsNone(error,repr(error));self.assertEqual(result,0)
                self.assertEqual(calls,[('prepare',architecture),('case','writer'),('case','calc'),('case','impress')])
    def test_preparation_failure_starts_no_case_or_editor_setup_budget(self):
        calls,result,error=self.run_main(preparation_failure=True)
        self.assertIsInstance(error,RuntimeError);self.assertIn('bounded native preparation failed',str(error))
        self.assertEqual(calls,[('prepare','x64')])
