"""Actual fixed fullscreen policy with bounded synthetic native boundaries."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
SOURCE=Path(__file__).resolve().parents[1]/'e2e/owned_fullscreen.py'


class Probe:
    def __init__(self,origin,clock):
        self.clock=clock;self.bad=None;self.calls=[];self.observations=0;self.sent=0
        self.shell=copy.deepcopy(origin['originalProcess']);self.engine=copy.deepcopy(origin['originalEngine'])
    def process_snapshot(self,process):
        value=copy.deepcopy(self.shell)
        if self.bad=='shell':value['creationTime']+=1
        return value
    def snapshot(self,binding,target):
        # NativeMenuProbe's source binder retains this actual API even when a
        # fullscreen toggle never asks for a menu snapshot. A new call must not
        # receive fabricated menu/identity evidence from this fullscreen fake.
        raise AssertionError('Fullscreen fixture cannot synthesize native menu snapshots')
    def open_engine(self,pid):
        self.calls.append(('open',pid))
        if self.bad=='late-open':self.clock.now+=5
        return 10
    def engine_snapshot(self,handle):
        value=copy.deepcopy(self.engine);value['handleValue']=handle
        if self.bad=='engine':value['creationTime']+=1
        return value
    def close_engine(self,handle):self.calls.append(('close',handle));return self.bad!='close'
    def close_provider(self):self.calls.append('provider-close');return self.bad!='provider-close'
    def enter_dpi(self,value):
        self.calls.append('dpi-enter');value.update(verified=True)
        if self.bad!='dpi-missing':value['previousContext']=1
    def restore_dpi(self,value):self.calls.append('dpi-restore');value['restored']=self.bad!='dpi-restore'
    def window_snapshot(self,hwnd):
        assert hwnd in (11,55,56,57,58)
        pid,thread=(77,7) if hwnd in (11,55) else (88,9)
        root=999 if self.bad=='child-root' and hwnd==56 else 11
        return dict(hwnd=hwnd,pid=pid,threadId=thread,rootHwnd=root,visible=True,enabled=True,
            iconic=False,cloaked=0,rectangle=[0,0,600,400])
    def attachment_snapshot(self,binding):
        return dict(binding=dict(binding),valid=self.bad!='attachment',focusUnderOriginalChild=True,
            windows={k:self.window_snapshot(binding[k]) for k in ('document','parent','child')},exported=[55,56])
    def editor_snapshot(self,binding):
        self.observations+=1
        bad=self.bad=='foreground' or self.bad=='after-foreground' and self.sent
        return dict(binding=dict(binding),attachmentValid=True,focusPid=88,focusRootHwnd=11,
            focusUnderOriginalChild=self.bad!='focus-outside',menuClosed=True,captureHwnd=0,
            menuOwnerHwnd=0,foreground=dict(hwnd=99 if bad else 11,rootHwnd=99 if bad else 11,pid=999 if bad else 77))
    def native_focus(self,thread):
        return dict(threadId=thread,activeHwnd=11,focusHwnd=58 if self.bad=='focus-steal' and self.observations>1 else 57,
            focusPid=88,focusRootHwnd=11,captureHwnd=1 if self.bad=='capture' else 0,
            menuOwnerHwnd=1 if self.bad=='menu' else 0,flags=4 if self.bad=='flags' else 0)
    def keyboard_snapshot(self,thread):
        if self.bad=='late-keyboard':self.clock.now+=5
        return dict(targetLayout=0x04090409,currentThreadLayout=0 if self.bad=='layout' else 0x04090409,
            keysDown=[0x11] if self.bad=='modifier' else [],capsLockOn=self.bad=='caps',scrollLockOn=False,
            numLockOn=not(self.bad=='lock-change' and self.observations>1))
    @property
    def user(self):
        return NS(GetAsyncKeyState=lambda key:0x8000 if self.bad=='j-held' and key==0x4a or self.bad=='mouse' and key==1 else 0,
            GetPropW=lambda hwnd,name:0 if self.bad=='hint' or self.bad=='late-hint' and self.observations>1 else 1)
    def _call(self,function,*args):return function(*args)
    def send(self,payload):
        self.sent+=1;self.calls.append(('send',bytes(payload)));self.clock.now+=.01
        if self.bad=='late-send':self.clock.now+=5
        if self.bad=='send-error':raise OSError('native send unavailable')
        return getattr(self,'count',6)
    def release(self,events):self.calls.append(('release',copy.deepcopy(events)));return len(events)


class FullscreenTests(unittest.TestCase):
    def feature(self):
        self.assertTrue(SOURCE.is_file(),'Fullscreen requires a separate measured native policy')
        spec=importlib.util.spec_from_file_location('tested_owned_fullscreen',SOURCE)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    def fixture(self,*,suite_root=None):
        module=self.feature()
        from test_owned_native_menu import Clock,Probe as MenuProbe
        from owned_native_menu import inspect_native_menu
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);temporary=Path(tmp.name)
        root=temporary if suite_root is None else suite_root;out=temporary/'evidence';out.mkdir()
        clock=Clock();clock.now=1.
        process=NS(pid=77,_handle=8,args=[str(root/'OpenGeul.Office.exe')],poll=lambda:None,
            opengeul_suite_root=root,opengeul_evidence_output=out,opengeul_evidence_case='blank-writer')
        api=NS(attachment=lambda hwnd:(55,56,88),user=NS(GetPropW=lambda hwnd,name:1))
        record=dict(module='writer',windowHwnd=11,parentHwnd=55,childHwnd=56,officePid=88)
        origin=inspect_native_menu(api,process,11,record,'open-escape',probe=MenuProbe(root,clock),clock=clock)
        record['nativeArchiveGeneration']={k:origin['originalEngine'][k] for k in ('pid','creationTime','image')}
        clock.now+=.1
        return module,api,process,record,clock,Probe(origin,clock)
    def run_toggle(self,f,**options):
        m,a,p,r,c,probe=f
        return m.toggle_native_fullscreen(a,p,11,r,module='writer',probe=probe,clock=c,**options)
    def test_one_fixed_six_event_call_joins_original_native_menu_and_archive(self):
        f=self.fixture();value=self.run_toggle(f);probe=f[-1]
        self.assertTrue(value['success']);self.assertFalse(value['deliveryProved'])
        self.assertEqual(value['kind'],'owned-native-fullscreen-toggle')
        self.assertEqual(value['deadline'],value['startedAt']+5)
        self.assertEqual(value['inputCallAttempts'],1);self.assertEqual(value['requestedInputs'],6)
        self.assertEqual(value['insertedInputs'],6);self.assertEqual(probe.sent,1)
        self.assertEqual([(e['scan'],e['flags']) for e in value['events']],
            [(0x1d,8),(0x2a,8),(0x24,8),(0x24,10),(0x2a,10),(0x1d,10)])
        self.assertTrue(value['engineHandleReleased']);self.assertTrue(value['dpiScope']['restored'])
        self.assertTrue(value['providerClientReleased']);self.assertIn(('close',10),probe.calls)
        self.assertGreater(probe.calls.index('provider-close'),probe.calls.index('dpi-restore'))
    def test_same_original_menu_can_authorize_two_distinct_fixed_toggles(self):
        f=self.fixture();self.run_toggle(f);self.run_toggle(f)
        self.assertEqual(f[-1].sent,2);self.assertEqual(len(f[3]['nativeFullscreenActions']),2)
    def test_scope_or_neutral_state_failure_never_inserts_input(self):
        for bad in ('attachment','child-root','foreground','focus-outside','capture','menu','flags','layout','modifier','j-held','mouse','caps','focus-steal','late-keyboard','lock-change','hint','late-hint'):
            with self.subTest(bad=bad):
                f=self.fixture();f[-1].bad=bad
                with self.assertRaises(AssertionError):self.run_toggle(f)
                self.assertEqual(f[-1].sent,0);self.assertIn(('close',10),f[-1].calls)
    def test_archive_and_original_generations_must_match(self):
        for bad in ('shell','engine','archive','missing-origin','failed-origin'):
            with self.subTest(bad=bad):
                f=self.fixture()
                if bad=='archive':f[3]['nativeArchiveGeneration']['creationTime']+=1
                elif bad=='missing-origin':f[3]['nativeMenuActions']=[]
                elif bad=='failed-origin':f[3]['nativeMenuActions'][-1]['success']=False
                else:f[-1].bad=bad
                with self.assertRaises(AssertionError):self.run_toggle(f)
                self.assertEqual(f[-1].sent,0)
    def test_partial_known_prefix_releases_only_owned_keyups_without_retry(self):
        for count,scans in ((0,[]),(1,[0x1d]),(2,[0x2a,0x1d]),(3,[0x24,0x2a,0x1d]),(4,[0x2a,0x1d]),(5,[0x1d])):
            with self.subTest(count=count):
                f=self.fixture();f[-1].count=count
                with self.assertRaisesRegex(AssertionError,'partial'):self.run_toggle(f)
                self.assertEqual(f[-1].sent,1)
                releases=[v[1] for v in f[-1].calls if isinstance(v,tuple) and v[0]=='release']
                self.assertEqual([e['scan'] for e in releases[0]] if releases else [],scans)
                self.assertTrue(all(e['flags']==10 for row in releases for e in row))
                self.assertTrue(f[3]['nativeFullscreenActions'][-1]['engineHandleReleased'])
    def test_unknown_return_never_guesses_a_prefix_or_retries(self):
        for count in (None,True,-1,7):
            with self.subTest(count=count):
                f=self.fixture();f[-1].count=count
                with self.assertRaises(AssertionError):self.run_toggle(f)
                self.assertEqual(f[-1].sent,1);self.assertFalse(any(isinstance(v,tuple) and v[0]=='release' for v in f[-1].calls))
    def test_late_successful_open_is_closed_and_late_input_never_retries(self):
        for bad in ('late-open','late-send','after-foreground'):
            with self.subTest(bad=bad):
                f=self.fixture();f[-1].bad=bad
                with self.assertRaises(AssertionError):self.run_toggle(f)
                self.assertEqual(f[-1].sent,0 if bad=='late-open' else 1);self.assertIn(('close',10),f[-1].calls)
    def test_cleanup_failure_cannot_qualify_input(self):
        for bad in ('close','dpi-restore','provider-close'):
            with self.subTest(bad=bad):
                f=self.fixture();f[-1].bad=bad
                with self.assertRaises(AssertionError):self.run_toggle(f)
                self.assertFalse(f[3]['nativeFullscreenActions'][-1]['success'])
    def test_failed_action_cannot_be_retried_under_same_record(self):
        f=self.fixture();f[-1].count=1
        with self.assertRaises(AssertionError):self.run_toggle(f)
        f[-1].count=6
        with self.assertRaises(AssertionError):self.run_toggle(f)
        self.assertEqual(f[-1].sent,1)
    def test_original_send_error_is_preserved_through_cleanup(self):
        f=self.fixture();f[-1].bad='send-error';f[-1].close_engine=lambda handle:False
        with self.assertRaisesRegex(OSError,'native send unavailable'):self.run_toggle(f)
        self.assertEqual(f[-1].sent,1)
    def test_calc_is_supported_and_module_mismatch_has_no_input(self):
        f=self.fixture();f[3]['module']='calc';m,a,p,r,c,probe=f
        value=m.toggle_native_fullscreen(a,p,11,r,module='calc',probe=probe,clock=c)
        self.assertTrue(value['success']);self.assertEqual(value['module'],'calc')
        f=self.fixture();f[3]['module']='calc'
        with self.assertRaises(AssertionError):self.run_toggle(f)
        self.assertEqual(f[-1].sent,0)
    def test_provider_release_and_dpi_restore_scope_are_mandatory_before_input(self):
        for bad in ('dpi-missing','provider-missing'):
            with self.subTest(bad=bad):
                f=self.fixture()
                if bad=='provider-missing':f[-1].close_provider=None
                else:f[-1].bad=bad
                with self.assertRaises(AssertionError):self.run_toggle(f)
                self.assertEqual(f[-1].sent,0)
    def test_shared_shortcut_programs_and_presets_are_unchanged(self):
        import counted_editor_shortcuts as shortcuts
        from scenario_editor_shortcuts import PROGRAMS
        before=copy.deepcopy((shortcuts.PRESETS,shortcuts.ORDER,PROGRAMS))
        self.run_toggle(self.fixture())
        self.assertEqual((shortcuts.PRESETS,shortcuts.ORDER,PROGRAMS),before)

    def test_entry_selects_probe_once_before_origin_replay_with_the_original_action_deadline(self):
        import native_menu_source_selection as source
        f=self.fixture();module,api,process,record,clock,probe=f;calls=[]
        replay=module.require_native_menu_action
        def select(actual,deadline,actual_clock,*,build,supplied=None):
            calls.append(('select',actual,deadline,actual_clock,supplied))
            return source.selected_native_menu_probe(actual,deadline,actual_clock,build=build,supplied=supplied)
        def origin(*args,**kwargs):calls.append(('origin',));return replay(*args,**kwargs)
        with patch.object(module,'selected_native_menu_probe',select,create=True),patch.object(module,'require_native_menu_action',origin):
            value=self.run_toggle(f)
        self.assertEqual([row[0] for row in calls],['select','origin'])
        self.assertIs(calls[0][1],process);self.assertIs(calls[0][3],clock);self.assertIs(calls[0][4],probe)
        self.assertEqual(calls[0][2],value['startedAt']+5)

    @classmethod
    def source_context(cls):
        if not hasattr(cls,'_source_context'):
            from suite.tests.test_native_menu_source_selection import SourceMenuSelectionTests
            case=SourceMenuSelectionTests(methodName='test_prepares_actual_bare_gate_context_and_freezes_contexts')
            case.setUp();cls.addClassCleanup(case.doCleanups)
            cls._source_context=(case,case.selected(case.prepared()))
        return cls._source_context

    def selected_fixture(self):
        case,selection=self.source_context()
        f=self.fixture(suite_root=case.suite);module,api,process,record,clock,probe=f
        process.opengeul_source_menu_selection=selection;probe.source_selection=selection
        clock.now=selection.launch_deadline+200
        return f,selection

    def test_selected_entry_rechecks_once_and_joins_current_generation_before_dpi(self):
        import owned_native_menu as core
        import time
        self.assertTrue(callable(getattr(core,'_bind_source_generation',None)))
        f,selection=self.selected_fixture();module,api,process,record,clock,probe=f
        admission=selection.prepared.admission;calls=[];rechecks=[]
        verify=type(admission).verify_provider_files;bind=core._bind_source_generation
        def checked(actual,deadline):rechecks.append((actual,deadline));return verify(actual,deadline)
        def replay(*args,**kwargs):calls.append('origin');self.assertTrue(kwargs.get('source_admission') is admission)
        def binding(*args):
            calls.append('bind');self.assertNotIn('dpi-enter',probe.calls)
            self.assertEqual(args[5]['handleValue'],10);return bind(*args)
        with patch.object(time,'monotonic',clock),patch.object(type(admission),'verify_provider_files',checked), \
                patch.object(module,'require_native_menu_action',replay),patch.object(core,'_bind_source_generation',binding):
            value=self.run_toggle(f)
        self.assertEqual(calls,['origin','bind']);self.assertEqual(len(rechecks),1)
        self.assertIs(rechecks[0][0],admission);self.assertEqual(rechecks[0][1],value['deadline'])
        self.assertEqual(value['sourceMenu']['admission']['admissionSha256'],admission.admission_sha256)
        self.assertEqual(value['sourceMenu']['generation']['engineHandleValue'],10)
        self.assertEqual(value['sourceMenu']['generation']['shellHandleValue'],8)
        self.assertEqual(value['sourceMenu']['focusProtocolVersion'],2)
        self.assertTrue(callable(probe._source_snapshot_original))
        self.assertTrue(value['success'])

    def test_selected_factory_rejection_never_replays_origin_opens_or_inputs(self):
        import time
        for reason in ('probe','fake','pending','provider','late'):
            with self.subTest(reason=reason):
                f,selection=self.selected_fixture();module,api,process,record,clock,probe=f
                if reason=='probe':probe.source_selection=self.source_context()[0].selected(selection.prepared)
                elif reason=='fake':process.opengeul_source_menu_selection=True
                import native_menu_msaa_hit as hit
                admission=selection.prepared.admission;verify=type(admission).verify_provider_files
                def checked(actual,deadline):
                    if reason=='provider':raise ValueError('Synthetic provider recheck rejection')
                    result=verify(actual,deadline)
                    if reason=='late':clock.now=deadline
                    return result
                with patch.object(time,'monotonic',clock), \
                        patch.object(type(admission),'verify_provider_files',checked), \
                        patch.object(hit,'pending_msaa_hit',return_value=object() if reason=='pending' else None), \
                        patch.object(module,'require_native_menu_action',side_effect=AssertionError('Rejected selection reached origin')):
                    with self.assertRaises(ValueError):self.run_toggle(f)
                self.assertEqual(probe.calls,[]);self.assertEqual(probe.sent,0)

    def test_attachment_must_be_current_before_generation_binding_or_dpi(self):
        f=self.fixture();f[1].attachment=lambda hwnd:(55,999,88)
        with self.assertRaises(AssertionError):self.run_toggle(f)
        self.assertNotIn('dpi-enter',f[-1].calls);self.assertEqual(f[-1].sent,0)
