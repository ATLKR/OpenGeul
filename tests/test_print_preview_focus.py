"""Actual print focus policy with only external Windows/UIA operations substituted."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
import json
import tempfile
import ctypes
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Element:
    def __init__(self, control):
        self.control = control
    def GetRuntimeId(self): return self.control.rid
    def SetFocus(self):
        if self.control.focus_error: raise self.control.focus_error
        self.control.probe.focused_control = self.control


class Control:
    def __init__(self, rid, pid=20, handle=None, parent=None, name='', cls='', kind='Window'):
        self.rid, self.pid, self.handle, self.parent_control = rid, pid, handle, parent
        self.name, self.cls, self.visible, self.enabled = name, cls, True, True
        self.focus_error = None
        self.element_info = types.SimpleNamespace(control_type=kind, automation_id='', element=Element(self))
        self.children = []
    def window_text(self): return self.name
    def class_name(self): return self.cls
    def process_id(self): return self.pid
    def is_visible(self): return self.visible
    def is_enabled(self): return self.enabled
    def parent(self): return self.parent_control
    def descendants(self, **filters): return self.children
    def rectangle(self): return types.SimpleNamespace(left=10, top=10, right=40, bottom=40)


class NativeApi:
    """External query/focus API, not a second implementation of the policy."""
    def __init__(self):
        self.windows = {100: dict(hwnd=100, pid=10, tid=11, cls='Tauri Window', visible=True, enabled=True, root=100, owners=[]),
                        200: dict(hwnd=200, pid=20, tid=21, cls='RootView', visible=True, enabled=True, root=200, owners=[100]),
                        999: dict(hwnd=999, pid=99, tid=91, cls='Foreign', visible=True, enabled=True, root=999, owners=[])}
        self.processes = {10: dict(pid=10, creation=110, session=2),
                          20: dict(pid=20, creation=120, session=2,parentProcessId=10)}
        self.foreground_hwnd = 999
        self.foreground_result = True
        self.foreground_calls = []
        self.activation_barriers=[]
        self.focused_control = None
        self.hit_hwnd = 200
        self.closed = False
    def bind_process(self, pid, expected, handle=None): return dict(self.processes[pid])
    def verify_process(self, pid, expected):
        if self.processes.get(pid) != expected: raise AssertionError('process identity changed')
    def window(self, hwnd):
        if hwnd not in self.windows: raise AssertionError('window disappeared')
        return dict(self.windows[hwnd])
    def foreground(self): return self.foreground_hwnd
    def set_foreground(self, hwnd):
        self.foreground_calls.append(hwnd)
        if self.foreground_result:self.foreground_hwnd = hwnd
        return self.foreground_result
    def focused(self): return self.focused_control
    def sync_activation(self,hwnd,expected,report):
        self.activation_barriers.append(hwnd)
        report.update({'returned':True,'timeoutMs':1000,'foregroundAfter':self.foreground_hwnd})
        return True
    def hit(self, point): return self.hit_hwnd
    def close(self): self.closed = True


class PrintPreviewFocusTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('print_focus', ROOT/'e2e/print_focus.py')
        self.module = importlib.util.module_from_spec(spec)
        self.desktop = types.ModuleType('pywinauto');self.desktop.Desktop = None
        self.modules = patch.dict(sys.modules, {'pywinauto': self.desktop, 'print_focus': self.module})
        self.modules.start();self.addCleanup(self.modules.stop)
        spec.loader.exec_module(self.module)
        self.probe = NativeApi()
        self.app = Control((1,), 10, 100, name='OpenGeul', cls='Tauri Window')
        self.native = Control((2,), 20, 200, parent=self.app, cls='RootView')
        self.preview = Control((3,), 20, parent=self.native, name='Print', cls='RootView')
        self.target = Control((4,), parent=self.preview, kind='ComboBox')
        self.target.probe = self.probe
        self.runtime = {'nativeArchitecture': {'processId':10},
                        'webview2Native': {'rootProcessId':10, 'processes':[{'processId':20, 'parentProcessId':10}]}}

    def guard(self):
        cls = getattr(self.module, 'OwnedPreviewFocus', None)
        self.assertIsNotNone(cls, 'Missing owned print-preview focus boundary')
        return cls(self.preview, 100, 10, self.runtime, probe=self.probe, app_handle=77)

    def test_owned_foreground_and_real_focus_are_observed_before_action(self):
        guard = self.guard()
        guard.prepare(self.target, 'margins-expand')
        self.assertEqual(self.probe.foreground_hwnd, 200)
        self.assertIsNone(self.probe.focused_control)
        self.assertEqual(self.probe.foreground_calls, [200])
        guard.check(self.target, 'margins-after-expand')
        self.assertEqual(self.probe.foreground_calls, [200])

    def test_initial_ctrl_p_boundary_prepares_exact_app_foreground(self):
        fn=getattr(self.module,'prepare_app_for_print',None)
        self.assertIsNotNone(fn,'Missing initial owned Ctrl+P focus boundary')
        fn(100,10,self.runtime,app_handle=77,probe=self.probe)
        self.assertEqual(self.probe.foreground_calls,[100])
        self.assertEqual(self.probe.foreground_hwnd,100)

    def test_semantic_prepare_does_not_require_or_change_keyboard_focus(self):
        guard=self.guard();self.target.focus_error=OSError('Semantic target is not keyboard focusable')
        self.probe.focused_control=self.app
        self.probe.focused=lambda:(_ for _ in ()).throw(AssertionError('Global focus must not approve semantic input'))
        guard.prepare(self.target,'margins-expand')
        self.assertEqual(self.probe.foreground_calls,[200])
        self.assertIs(self.probe.focused_control,self.app)

    def test_one_activation_orders_async_zero_before_semantic_dispatch(self):
        guard=self.guard()
        def activated(hwnd):
            self.probe.foreground_calls.append(hwnd);self.probe.foreground_hwnd=0;return True
        def processed(hwnd,expected,report):
            self.probe.activation_barriers.append(hwnd);self.probe.foreground_hwnd=hwnd
            report.update({'returned':True,'timeoutMs':1000});return True
        self.probe.set_foreground=activated;self.probe.sync_activation=processed
        guard.prepare(self.target,'margins-expand')
        self.assertEqual(self.probe.foreground_calls,[200]);self.assertEqual(self.probe.activation_barriers,[200])

    def test_foreign_foreground_after_barrier_still_rejects_one_activation(self):
        guard=self.guard()
        def processed(hwnd,expected,report):
            self.probe.activation_barriers.append(hwnd);self.probe.foreground_hwnd=999;return True
        self.probe.sync_activation=processed
        with self.assertRaises(AssertionError):guard.prepare(self.target,'margins-expand')
        self.assertEqual(self.probe.foreground_calls,[200]);self.assertEqual(self.probe.activation_barriers,[200])

    def test_hung_barrier_never_approves_semantic_input(self):
        guard=self.guard()
        self.probe.sync_activation=lambda hwnd,expected,report:False
        with self.assertRaises(AssertionError):guard.prepare(self.target,'margins-expand')
        self.assertEqual(self.probe.foreground_calls,[200])

    def test_real_windows_adapter_orders_owned_wm_null_once_and_rechecks_identity(self):
        probe=self.module.WindowsFocusProbe.__new__(self.module.WindowsFocusProbe)
        probe.ctypes=ctypes;probe.user=types.SimpleNamespace();window=dict(self.probe.windows[100]);messages=[]
        record={'pid':10,'creation':110,'session':2}
        image={'imagePath':'OpenGeul.exe','nativeMachine':0xAA64}
        probe.handles={10:(77,False,record,image)}
        probe.process=types.SimpleNamespace(inspect=lambda pid,handle:{**image,'exitCode':259,'processMachine':0})
        probe._times_session=lambda pid,handle:dict(record)
        probe.window=lambda hwnd:dict(window)
        probe.foreground=lambda:self.probe.foreground_hwnd
        def message(hwnd,kind,wparam,lparam,flags,timeout,result):
            messages.append((hwnd,kind,wparam,lparam,flags,timeout));self.probe.foreground_hwnd=hwnd;return 1
        probe.user.SendMessageTimeoutW=message
        report={};fn=getattr(probe,'sync_activation',None);self.assertIsNotNone(fn)
        self.assertTrue(fn(100,dict(window),report))
        self.assertEqual(messages,[(100,0,0,0,0x23,1000)])
        self.assertTrue(report['returned']);self.assertEqual(report['foregroundAfter'],100)
        messages.clear()
        def retarget(*args):
            messages.append(args[:6]);window['pid']=99;return 1
        probe.user.SendMessageTimeoutW=retarget
        with self.assertRaises(AssertionError):fn(100,self.probe.windows[100],{})
        self.assertEqual(len(messages),1)

    def test_foreign_semantic_provider_is_rejected_before_foreground_or_pattern(self):
        guard=self.guard();self.target.pid=99
        with self.assertRaises(AssertionError):guard.prepare(self.target,'margins-expand')
        self.assertEqual(self.probe.foreground_calls,[])

    def test_semantic_prepare_rejects_foreground_changed_at_final_observation(self):
        guard=self.guard();original=self.probe.foreground;reads=[]
        def observed():
            reads.append(None)
            return 999 if len(reads)==6 else original()
        self.probe.foreground=observed
        with self.assertRaises(AssertionError):guard.prepare(self.target,'margins-expand')
        self.assertEqual(self.probe.foreground_calls,[200])

    def test_initial_ctrl_p_boundary_refuses_failed_focus_or_foreign_hwnd(self):
        fn=getattr(self.module,'prepare_app_for_print',None)
        self.assertIsNotNone(fn,'Missing initial owned Ctrl+P focus boundary')
        self.probe.foreground_result=False
        with self.assertRaises(AssertionError):fn(100,10,self.runtime,app_handle=77,probe=self.probe)
        self.assertEqual(self.probe.foreground_hwnd,999)

    def test_initial_ctrl_p_boundary_rejects_foreground_change_during_identity_check(self):
        original=self.probe.verify_process
        def changed(pid,expected):
            original(pid,expected);self.probe.foreground_hwnd=999
        self.probe.verify_process=changed
        with self.assertRaises(AssertionError):
            self.module.prepare_app_for_print(100,10,self.runtime,app_handle=77,probe=self.probe)
        self.assertEqual(self.probe.foreground_calls,[100])
        self.assertTrue(self.probe.closed)

    def test_real_adapter_queries_fresh_parent_after_holding_child_handle(self):
        probe=self.module.WindowsFocusProbe.__new__(self.module.WindowsFocusProbe);probe.architecture='arm64'
        probe.handles={10:(100,False,{'pid':10,'creation':110,'session':2},{})}
        world={'parent':10};events=[]
        def snapshot():
            events.append('snapshot');return [{'processId':20,'parentProcessId':world['parent']}]
        def opened(*args):events.append('held-child');world['parent']=99;return 200
        probe.process=types.SimpleNamespace(processes=snapshot,
            api=types.SimpleNamespace(OpenProcess=opened,CloseHandle=lambda h:events.append('closed-query')))
        probe._times_session=lambda pid,handle:{'pid':pid,'creation':120,'session':2}
        probe.verify_process=lambda *args:None
        native={'runningAtInspection':True,'sha256':'same-image-sha','bytes':123,'processMachine':0}
        with patch.dict(sys.modules,{'native_architecture':types.SimpleNamespace(verify_process=lambda *a,**kw:native)}):
            with self.assertRaises(AssertionError):
                probe.bind_process(20,{'imagePath':'msedgewebview2.exe','sha256':'same-image-sha','bytes':123,'parentProcessId':10})
        self.assertEqual(events,['held-child','snapshot','closed-query'])

    def test_two_virtual_previews_same_pid_remain_ambiguous(self):
        other = Control((5,), 20, parent=self.native, name='Print', cls='RootView')
        self.app.children = [self.preview, other]
        desktop = types.SimpleNamespace(windows=lambda: [])
        found = self.module._preview_windows(desktop, self.app, 100, {10,20})
        self.assertEqual(len(found), 2, 'Distinct UIA roots were collapsed by their null HWND')

    def test_foreground_request_failure_never_focuses_or_retries(self):
        guard = self.guard();self.probe.foreground_result = False
        with self.assertRaises(AssertionError):guard.prepare(self.target, 'margins-expand')
        self.assertIsNone(self.probe.focused_control)
        self.assertEqual(self.probe.foreground_calls, [200])

    def test_still_foreign_foreground_never_focuses(self):
        guard = self.guard()
        self.probe.set_foreground = lambda hwnd: True
        with self.assertRaises(AssertionError):guard.prepare(self.target, 'margins-expand')
        self.assertIsNone(self.probe.focused_control)

    def test_non_keyboard_focusable_semantic_target_preserves_owned_foreground(self):
        guard = self.guard();self.target.focus_error = OSError('Focus rejected')
        self.target.element_info.element.CurrentIsKeyboardFocusable=False
        guard.prepare(self.target, 'margins-expand')
        self.assertEqual(self.probe.foreground_calls, [200])
        self.assertIsNone(self.probe.focused_control)

    def test_global_keyboard_focus_cannot_authorize_target_outside_exact_preview(self):
        guard = self.guard()
        self.target.parent_control=self.app
        self.probe.focused_control = self.target
        with self.assertRaises(AssertionError):guard.prepare(self.target, 'margins-expand')
        self.assertEqual(self.probe.foreground_calls,[])

    def test_no_native_ancestor_has_no_app_hwnd_fallback(self):
        self.preview.parent_control = None
        with self.assertRaises(AssertionError):self.guard()
        self.assertEqual(self.probe.foreground_calls, [])

    def test_same_image_reused_webview_with_changed_actual_parent_never_binds(self):
        self.probe.processes[20]['parentProcessId']=99
        with self.assertRaises(AssertionError):self.guard()
        self.assertEqual(self.probe.foreground_calls,[])

    def test_binding_failure_preserves_bounded_partial_diagnostic_without_error_text(self):
        cls=getattr(self.module,'OwnedPreviewFocus');self.preview.parent_control=None
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError):
                cls(self.preview,100,10,self.runtime,probe=self.probe,app_handle=77,evidence_dir=Path(tmp))
            raw=(Path(tmp)/'print-focus-diagnostic.json').read_bytes();data=json.loads(raw)
            self.assertLessEqual(len(raw),32*1024)
            self.assertEqual(data['kind'],'diagnostic-metadata')
            self.assertEqual(data['lastPartialAncestorChain'],[{'runtimeId':[3],'pid':20,'hwnd':0}])
            self.assertEqual(data['observations'][-1],{'phase':'binding-failed','stage':'preview-uia-ancestor','errorType':'AssertionError'})
            self.assertFalse(data['productTelemetry']);self.assertFalse(data['sourceQualified'])
            self.assertTrue(self.probe.closed)

    def test_native_query_error_message_never_enters_diagnostic(self):
        cls=getattr(self.module,'OwnedPreviewFocus')
        def refused(*args,**kwargs):raise OSError('private-document-name password value')
        self.probe.bind_process=refused
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):
                cls(self.preview,100,10,self.runtime,probe=self.probe,app_handle=77,evidence_dir=Path(tmp))
            raw=(Path(tmp)/'print-focus-diagnostic.json').read_bytes()
            self.assertNotIn(b'private-document',raw);self.assertNotIn(b'password',raw)
            self.assertEqual(json.loads(raw)['observations'][-1]['errorType'],'OSError')

    def test_child_hwnd_is_normalized_to_its_owned_top_level(self):
        self.native.handle = 201
        self.probe.windows[201] = dict(hwnd=201, pid=20, tid=21, cls='Child', visible=True, enabled=True, root=200, owners=[])
        guard = self.guard();guard.prepare(self.target, 'margins-expand')
        self.assertEqual(self.probe.foreground_calls, [200])

    def test_root_retarget_or_process_reuse_fails_before_input(self):
        for mutate in [lambda:setattr(self.preview, 'rid', (99,)),
                       lambda:self.probe.processes[20].update(creation=999),
                       lambda:self.probe.windows[200].update(pid=99),
                       lambda:self.probe.windows[200].update(tid=99),
                       lambda:self.probe.windows[200].update(cls='foreign'),
                       lambda:self.probe.windows[200].update(visible=False)]:
            with self.subTest(mutate=mutate):
                guard = self.guard();mutate()
                with self.assertRaises(AssertionError):guard.prepare(self.target, 'margins-expand')
                self.assertEqual(self.probe.foreground_calls, [])
                self.preview.rid=(3,);self.probe.processes[20]['creation']=120
                self.probe.windows[200]=dict(hwnd=200,pid=20,tid=21,cls='RootView',visible=True,enabled=True,root=200,owners=[100])

    def test_foreign_hit_target_fails_without_refocusing_popup(self):
        guard = self.guard();guard.prepare(self.target, 'margins-expand')
        self.probe.hit_hwnd = 999
        with self.assertRaises(AssertionError):guard.check(self.target, 'margins-click', physical=True)
        self.assertEqual(self.probe.foreground_calls, [200])

    def test_owned_popup_requires_explicit_uia_and_native_owner_chains(self):
        guard = self.guard();guard.prepare(self.target, 'margins-expand')
        popup = Control((6,), 20, 300, parent=self.preview, cls='Popup')
        choice = Control((7,), 20, parent=popup, kind='ListItem')
        self.probe.windows[300]=dict(hwnd=300,pid=20,tid=21,cls='Popup',visible=True,enabled=True,root=300,owners=[200])
        self.probe.foreground_hwnd=300;self.probe.hit_hwnd=300
        guard.check(choice, 'margins-click', physical=True)
        self.probe.windows[300]['owners']=[]
        with self.assertRaises(AssertionError):guard.check(choice, 'margins-click', physical=True)
        self.assertEqual(self.probe.foreground_calls,[200])

    def settings(self):
        spec=importlib.util.spec_from_file_location('preview_settings',ROOT/'e2e/preview_settings.py')
        module=importlib.util.module_from_spec(spec)
        with patch.object(sys,'path',[str(ROOT/'e2e'),*sys.path]):spec.loader.exec_module(module)
        paper_group=Control((8,),parent=self.preview,name='Paper size',kind='Group')
        margin_group=Control((9,),parent=self.preview,name='Margins',kind='Group')
        paper=Control((10,),parent=paper_group,kind='ComboBox')
        margins=Control((11,),parent=margin_group,kind='ComboBox')
        choice=Control((12,),parent=margin_group,name='None',kind='ListItem')
        actual=Control((13,),parent=self.preview,name='Actual size',kind='RadioButton')
        paper.iface_value=types.SimpleNamespace(CurrentValue='A4')
        margins.iface_value=types.SimpleNamespace(CurrentValue='Default')
        actual.iface_selection_item=types.SimpleNamespace(CurrentIsSelected=True)
        self.actions=[]
        for control in [paper,margins,choice,actual]:control.probe=self.probe
        def expand():
            self.actions.append('expand');self.preview.children.append(choice)
        margins.iface_expand_collapse=types.SimpleNamespace(Expand=expand)
        def click():
            self.actions.append('click');margins.iface_value.CurrentValue='None'
            choice.parent_control=None  # Chromium may remove the option after committing.
        choice.click_input=click
        self.preview.children=[paper,margins,actual]
        # Match UIA FindAll filters instead of substituting the production selector.
        self.preview.descendants=lambda **kw:[c for c in self.preview.children if not kw or c.element_info.control_type==kw['control_type']]
        return module,margins

    def test_actual_configure_preview_prepares_before_expand_and_clicks_once(self):
        module,margins=self.settings();guard=self.guard()
        margins.element_info.element.CurrentIsKeyboardFocusable=False
        margins.focus_error=OSError('Semantic target is not keyboard focusable')
        result=module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand','click'])
        self.assertEqual(result['margins'],'None')
        self.assertEqual(self.probe.foreground_calls,[200])
        self.assertIsNone(self.probe.focused_control)

    def test_actual_configure_preview_foreign_focus_failure_dispatches_nothing(self):
        module,_=self.settings();guard=self.guard();self.probe.foreground_result=False
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,[])

    def test_actual_expand_failure_is_not_retried(self):
        module,margins=self.settings();guard=self.guard()
        def fail():
            self.actions.append('expand');raise OSError('dispatched expansion failed')
        margins.iface_expand_collapse.Expand=fail
        with self.assertRaisesRegex(OSError,'expansion failed'):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand'])

    def test_popup_open_foreign_occlusion_stops_before_physical_click(self):
        module,margins=self.settings();guard=self.guard()
        expand=margins.iface_expand_collapse.Expand
        def obscured():
            expand();self.probe.foreground_hwnd=999
        margins.iface_expand_collapse.Expand=obscured
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand'])
        self.assertEqual(self.probe.foreground_calls,[200])

    def lost_dropdown(self, *, collapse=True, foreign=True, lose_again=False):
        """UIA reports a committed A4 and a margin menu closed by focus loss."""
        module,margins=self.settings();self.probe.foreground_hwnd=200
        clock=types.SimpleNamespace(now=0.0)
        clock.monotonic=lambda:clock.now
        clock.sleep=lambda seconds:setattr(clock,'now',clock.now+seconds)
        module.time=clock
        pattern=margins.iface_expand_collapse
        pattern.CurrentExpandCollapseState=0
        original=pattern.Expand
        self.after_loss=lambda:None
        def expand():
            original();pattern.CurrentExpandCollapseState=1
            if self.actions.count('expand')==1 or lose_again:
                self.preview.children=[c for c in self.preview.children if c.window_text()!='None']
                if collapse:pattern.CurrentExpandCollapseState=0
                if foreign:self.probe.foreground_hwnd=999
                self.after_loss()
        pattern.Expand=expand
        return module,margins,clock

    def test_configure_recovers_one_foreign_focus_collapsed_menu_with_one_click(self):
        module,margins,clock=self.lost_dropdown();guard=self.guard()
        result=module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand','expand','click'])
        self.assertEqual(self.probe.foreground_calls,[200])
        self.assertEqual((result['paper'],result['margins'],result['actualSize']),('A4','None',True))
        self.assertEqual((result['paperRecoveryCount'],result['marginsRecoveryCount']),(0,1))
        self.assertEqual(result['marginsLatestExpandState'],0)
        self.assertLess(clock.now,30)

    def test_collapsed_owned_foreground_never_reopens_or_clicks(self):
        module,margins,clock=self.lost_dropdown(foreign=False);guard=self.guard()
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])
        self.assertGreaterEqual(clock.now,30);self.assertLess(clock.now,30.2)

    def test_expanded_foreign_foreground_never_reopens_or_clicks(self):
        module,margins,clock=self.lost_dropdown(collapse=False);guard=self.guard()
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])
        self.assertGreaterEqual(clock.now,30);self.assertLess(clock.now,30.2)

    def test_second_focus_loss_does_not_repeat_recovery_or_extend_deadline(self):
        module,margins,clock=self.lost_dropdown(lose_again=True);guard=self.guard()
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand','expand']);self.assertEqual(self.probe.foreground_calls,[200])
        self.assertGreaterEqual(clock.now,30);self.assertLess(clock.now,30.2)

    def test_recovery_failed_foreground_activation_never_expands_again(self):
        module,margins,_=self.lost_dropdown();guard=self.guard();self.probe.foreground_result=False
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[200])

    def test_recovery_retained_control_identity_changes_never_dispatch_input(self):
        mutations=[lambda m:setattr(m,'rid',(99,)),lambda m:setattr(m,'pid',10),
                   lambda m:setattr(m,'parent_control',self.app),
                   lambda m:self.probe.processes[20].update(creation=999),
                   lambda m:self.probe.windows[200].update(tid=99)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.setUp();module,margins,_=self.lost_dropdown();guard=self.guard()
                self.after_loss=lambda:mutate(margins)
                with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
                self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])

    def test_recovery_observed_source_identity_rejection_never_dispatches_input(self):
        module,margins,_=self.lost_dropdown();guard=self.guard()
        def rejected():
            self.probe.verify_process=lambda *args:(_ for _ in ()).throw(AssertionError('held image changed'))
        self.after_loss=rejected
        with self.assertRaisesRegex(AssertionError,'held image changed'):
            module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])

    def test_recovery_option_presence_cannot_approve_a_retargeted_dropdown(self):
        module,margins,_=self.lost_dropdown();guard=self.guard();original=margins.iface_expand_collapse.Expand
        def expanded():
            original()
            if self.actions.count('expand')==2:margins.rid=(99,)
        margins.iface_expand_collapse.Expand=expanded
        with self.assertRaisesRegex(AssertionError,'dropdown identity changed'):
            module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand','expand']);self.assertEqual(self.probe.foreground_calls,[200])

    def test_recovery_target_retargeted_during_activation_never_expands(self):
        module,margins,_=self.lost_dropdown();guard=self.guard()
        def processed(hwnd,expected,report):
            self.probe.activation_barriers.append(hwnd);margins.rid=(99,);return True
        self.probe.sync_activation=processed
        with self.assertRaisesRegex(AssertionError,'dropdown identity changed'):
            module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[200])

    def test_boolean_or_unknown_expand_state_cannot_authorize_recovery(self):
        for state in [False,-1,4,None,'0']:
            with self.subTest(state=state):
                module,margins,clock=self.lost_dropdown();guard=self.guard()
                self.after_loss=lambda:setattr(margins.iface_expand_collapse,'CurrentExpandCollapseState',state)
                with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
                self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])
                self.assertGreaterEqual(clock.now,30);self.assertLess(clock.now,30.2)

    def test_unknown_zero_foreground_cannot_authorize_menu_recovery(self):
        module,margins,clock=self.lost_dropdown();guard=self.guard()
        self.after_loss=lambda:setattr(self.probe,'foreground_hwnd',0)
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])
        self.assertGreaterEqual(clock.now,30);self.assertLess(clock.now,30.2)

    def test_collapsed_menu_with_missing_option_and_owned_popup_never_reactivates(self):
        module,margins,clock=self.lost_dropdown();guard=self.guard()
        self.probe.windows[300]=dict(hwnd=300,pid=20,tid=21,cls='Popup',visible=True,enabled=True,root=300,owners=[200])
        self.after_loss=lambda:setattr(self.probe,'foreground_hwnd',300)
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])
        self.assertGreaterEqual(clock.now,30);self.assertLess(clock.now,30.2)

    def test_foreground_window_query_failure_never_approves_recovery(self):
        module,margins,_=self.lost_dropdown();guard=self.guard();window=self.probe.window
        def queried(hwnd):
            if hwnd==999:raise OSError('foreground query unavailable')
            return window(hwnd)
        self.probe.window=queried
        with self.assertRaises(OSError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])

    def test_same_pid_without_bound_popup_thread_or_owner_never_approves_recovery(self):
        for change in [{'owners':[]},{'tid':99},{'root':100}]:
            with self.subTest(change=change):
                module,margins,_=self.lost_dropdown();guard=self.guard()
                self.probe.windows[300]=dict(hwnd=300,pid=20,tid=21,cls='Popup',visible=True,enabled=True,root=300,owners=[200])
                self.probe.windows[300].update(change)
                self.after_loss=lambda:setattr(self.probe,'foreground_hwnd',300)
                with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
                self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])

    def test_foreground_change_during_query_never_approves_recovery(self):
        module,margins,_=self.lost_dropdown();guard=self.guard();window=self.probe.window
        def queried(hwnd):
            result=window(hwnd)
            if hwnd==999:self.probe.foreground_hwnd=200
            return result
        self.probe.window=queried
        with self.assertRaises(AssertionError):module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(self.actions,['expand']);self.assertEqual(self.probe.foreground_calls,[])

    def test_same_owned_popup_focus_keeps_open_menu_and_clicks_once(self):
        module,margins=self.settings();self.probe.foreground_hwnd=200;guard=self.guard()
        original=margins.iface_expand_collapse.Expand
        popup=Control((30,),20,300,parent=self.preview,cls='Popup')
        self.probe.windows[300]=dict(hwnd=300,pid=20,tid=21,cls='Popup',visible=True,enabled=True,root=300,owners=[200])
        def expanded():
            original();choice=self.preview.children[-1];choice.parent_control=popup
            self.probe.foreground_hwnd=300;self.probe.hit_hwnd=300
        margins.iface_expand_collapse.Expand=expanded
        result=module.configure_preview(self.preview,{10,20},focus=guard)
        self.assertEqual(result['margins'],'None');self.assertEqual(self.actions,['expand','click'])
        self.assertEqual(self.probe.foreground_calls,[])


if __name__ == '__main__':unittest.main()
