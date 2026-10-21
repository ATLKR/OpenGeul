"""Owned physical editor click policy/native boundary; no Windows qualification."""
import copy
import ctypes
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
sys.path.insert(0, str(Path(__file__).resolve().parent))
SOURCE = E2E / 'editor_click_readiness.py'


class Clock:
    def __init__(self): self.now = 1.
    def __call__(self): return self.now
    def sleep(self, value): self.now += value


class Probe:
    def __init__(self, process, clock):
        self.process, self.clock = process, clock
        self.shell = dict(pid=77, handleValue=2**40, creationTime=134370146280641471,
            image=str(process.opengeul_suite_root / 'OpenGeul.Office.exe'), waitResult=258)
        self.engine = dict(pid=88, handleValue=2**41, creationTime=134370146301659971,
            image=str(process.opengeul_suite_root / 'Office/program/soffice.bin'), waitResult=258)
        self.frame = dict(suite=dict(hwnd=11, pid=77, threadId=10, rootHwnd=11,
                visible=True, enabled=True, iconic=False, cloaked=0, rectangle=[0, 0, 1024, 720]),
            parent=dict(hwnd=22, pid=77, threadId=10, rootHwnd=11, visible=True, enabled=True,
                rectangle=[8, 55, 1016, 690], clientScreenRect=[8, 55, 1016, 690]),
            editor=dict(hwnd=33, pid=88, threadId=20, rootHwnd=11, visible=True, enabled=True,
                rectangle=[8, 55, 1016, 690], clientScreenRect=[8, 55, 1016, 690]),
            parentWithinSuite=True, editorWithinParent=True)
        self.calls = []; self.foreground_root = 11; self.occluded = 0
        self.fail = None; self.after_move = None; self.after_click = None
    def enter_dpi(self, receipt):
        self.calls.append('dpi-enter'); receipt.update(previousContext=123, verified=True, restored=False)
        if self.fail == 'dpi-enter': raise OSError('DPI entry failed')
    def restore_dpi(self, receipt):
        self.calls.append('dpi-restore'); receipt['restored'] = self.fail != 'dpi-restore'
        if self.fail == 'dpi-restore': raise OSError('DPI restore failed')
    def process_snapshot(self, process):
        self.calls.append('shell')
        if self.fail == 'shell': raise OSError('shell query failed')
        return copy.deepcopy(self.shell)
    def open_engine(self, pid):
        self.calls.append('engine-open')
        if self.fail == 'engine-open': raise OSError('engine open failed')
        assert pid == 88
        return self.engine['handleValue']
    def engine_snapshot(self, handle):
        self.calls.append('engine')
        if self.fail == 'engine': raise OSError('engine query failed')
        return copy.deepcopy(self.engine)
    def close_engine(self, handle, receipt):
        self.calls.append('engine-close'); receipt['engineHandleReleased'] = self.fail != 'engine-close'
        if self.fail == 'engine-close': raise OSError('engine close failed')
    def editor_snapshot(self, hwnd, parent, child):
        self.calls.append('frame')
        if self.fail == 'frame': raise OSError('frame query failed')
        return copy.deepcopy(self.frame)
    def foreground(self):
        self.calls.append('foreground'); return self.foreground_root
    def editor_hit(self, child, point):
        self.calls.append('hit')
        if self.fail == 'hit': raise OSError('hit query failed')
        foreign = self.occluded > 0
        if foreign: self.occluded -= 1
        return dict(point=list(point), hitHwnd=99 if foreign else 34,
            rootHwnd=99 if foreign else 11, pid=999 if foreign else 88,
            threadId=90 if foreign else 20, withinEditor=not foreign,
            visible=True, enabled=True)
    def move(self, point, receipt):
        self.calls.append('move'); receipt.update(pointerMoveAttempts=1,
            pointerSetReturned=True, pointerReadback=list(point))
        if self.after_move: self.after_move()
    def click(self, receipt):
        self.calls.append('click')
        intent, = self.process.opengeul_evidence_output.glob('*-click-intent.json')
        assert json.loads(intent.read_bytes())['clickAttempts'] == 1
        receipt.update(requestedInputs=2, insertedInputs=2, inputCallAttempts=1,
            inputCountBasis='SendInput return value', clickCompleted=True)
        if self.after_click: self.after_click()


class EditorClickPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'Measured owned editor click readiness is missing')
        spec = importlib.util.spec_from_file_location('editor_click_readiness_tested', SOURCE)
        self.mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.mod)
    def fixture(self, directory):
        output = Path(directory).resolve(); suite = output / 'Suite'; suite.mkdir()
        p = NS(pid=77, _handle=2**40, args=[str(suite/'OpenGeul.Office.exe')],
            opengeul_suite_root=suite, opengeul_evidence_output=output, opengeul_evidence_case='owned-case')
        c = Clock(); probe = Probe(p, c)
        p.opengeul_activation_binding = tuple(probe.shell[k] for k in ('pid','handleValue','image','creationTime','waitResult'))
        focus = dict(schemaVersion=1, kind='owned-editor-focus-readiness', ready=False,
            suiteHwnd=11, childHwnd=33, shellPid=77, officePid=88, clickAttempts=1,
            clickCompleted=False, startedAt=1., deadline=2., deadlineSeconds=1.,
            deadlineScope='editor-setup-and-focus')
        return p, c, probe, dict(editorFocusReadiness=focus)
    def run_click(self, p, c, probe, record):
        def strict(hwnd): self.assertEqual(probe.foreground_root, hwnd)
        return self.mod.click_editor_once(strict, p, 11, 22, 33, 88, record,
            probe=probe, clock=c, pause=c.sleep)
    def test_occlusion_is_observed_before_one_measured_click(self):
        with tempfile.TemporaryDirectory() as folder:
            p,c,probe,r = self.fixture(folder); probe.occluded = 3
            result = self.run_click(p,c,probe,r)
            self.assertTrue(result['ready']); self.assertEqual(result['clickAttempts'],1)
            self.assertEqual(probe.calls.count('move'),1); self.assertEqual(probe.calls.count('click'),1)
            self.assertGreaterEqual(len(result['preflight']),4)
            self.assertTrue(all(row['hit']['pid']==999 for row in result['preflight'][:3]))
            self.assertLess(probe.calls.index('engine-open'),probe.calls.index('move'))
            self.assertTrue(result['engineHandleReleased']); self.assertTrue(result['dpiScope']['restored'])
            final, = Path(folder).glob('*-result.json'); self.assertEqual(json.loads(final.read_bytes()),result)
    def test_occlusion_timeout_has_zero_pointer_and_button_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            p,c,probe,r=self.fixture(folder); probe.occluded=1000
            with self.assertRaisesRegex(AssertionError,'deadline|preflight'): self.run_click(p,c,probe,r)
            self.assertNotIn('move',probe.calls); self.assertNotIn('click',probe.calls)
            self.assertTrue(r['editorClicks'][0]['engineHandleReleased'])
            self.assertLessEqual(len(r['editorClicks'][0]['preflight']),102)
    def test_foreign_foreground_fails_immediately_instead_of_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            p,c,probe,r=self.fixture(folder); probe.foreground_root=99
            with self.assertRaisesRegex(AssertionError,'foreground'): self.run_click(p,c,probe,r)
            self.assertNotIn('move',probe.calls); self.assertNotIn('click',probe.calls)
    def test_dead_or_wrong_original_shell_never_inputs(self):
        for key,bad in [('pid',99),('handleValue',4),('creationTime',1),('image','/foreign.exe'),('waitResult',0)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                p,c,probe,r=self.fixture(folder);probe.shell[key]=bad
                with self.assertRaises(AssertionError):self.run_click(p,c,probe,r)
                self.assertNotIn('move',probe.calls);self.assertNotIn('click',probe.calls)
    def test_engine_pid_image_generation_and_liveness_are_retained(self):
        for key,bad in [('pid',99),('image','/foreign.exe'),('waitResult',0),('creationTime',0)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                p,c,probe,r=self.fixture(folder);probe.engine[key]=bad
                with self.assertRaises(AssertionError):self.run_click(p,c,probe,r)
                self.assertNotIn('move',probe.calls);self.assertNotIn('click',probe.calls)
                self.assertEqual(probe.calls.count('engine-close'),1)
    def test_engine_generation_must_not_predate_original_suite(self):
        with tempfile.TemporaryDirectory() as folder:
            p,c,probe,r=self.fixture(folder)
            probe.engine['creationTime']=probe.shell['creationTime']-1
            with self.assertRaisesRegex(AssertionError,'predates|generation'):
                self.run_click(p,c,probe,r)
            self.assertNotIn('move',probe.calls);self.assertNotIn('click',probe.calls)
            self.assertTrue(r['editorClicks'][0]['engineHandleReleased'])
    def test_live_hidden_disabled_foreign_or_changed_hierarchy_never_inputs(self):
        for part,key,bad in [('parent','pid',99),('editor','pid',99),('editor','rootHwnd',99),
                ('editor','visible',False),('editor','enabled',False),('suite','cloaked',1),
                ('suite','iconic',True),('parent','threadId',99)]:
            with self.subTest(part=part,key=key),tempfile.TemporaryDirectory() as folder:
                p,c,probe,r=self.fixture(folder);probe.frame[part][key]=bad
                with self.assertRaises(AssertionError):self.run_click(p,c,probe,r)
                self.assertNotIn('move',probe.calls);self.assertNotIn('click',probe.calls)
        for key in ['parentWithinSuite','editorWithinParent']:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as folder:
                p,c,probe,r=self.fixture(folder);probe.frame[key]=False
                with self.assertRaises(AssertionError):self.run_click(p,c,probe,r)
                self.assertNotIn('click',probe.calls)
    def test_change_after_pointer_never_reselects_or_sends_button(self):
        for change in ['engine','shell','rectangle','hit','foreground','pointer']:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                p,c,probe,r=self.fixture(folder)
                def race():
                    if change=='engine':probe.engine['creationTime']+=1
                    elif change=='shell':probe.shell['creationTime']+=1
                    elif change=='rectangle':probe.frame['editor']['clientScreenRect'][0]+=1
                    elif change=='hit':probe.occluded=1
                    elif change=='foreground':probe.foreground_root=99
                    else:r['editorClicks'][0]['pointerReadback']=[1,2]
                probe.after_move=race
                with self.assertRaises(AssertionError):self.run_click(p,c,probe,r)
                self.assertEqual(probe.calls.count('move'),1);self.assertNotIn('click',probe.calls)
    def test_query_failures_restore_dpi_and_close_any_admitted_handle(self):
        for failure in ['shell','frame','engine-open','engine','hit']:
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                p,c,probe,r=self.fixture(folder);probe.fail=failure
                with self.assertRaises(OSError):self.run_click(p,c,probe,r)
                self.assertNotIn('click',probe.calls);self.assertIn('dpi-restore',probe.calls)
                if 'engine-open' in probe.calls and failure!='engine-open':self.assertIn('engine-close',probe.calls)
    def test_dpi_or_handle_restoration_failure_cannot_qualify_input(self):
        for failure in ['dpi-restore','engine-close']:
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                p,c,probe,r=self.fixture(folder);probe.fail=failure
                with self.assertRaises(OSError):self.run_click(p,c,probe,r)
                self.assertFalse(r['editorClicks'][0]['ready'])
    def test_late_finalization_cannot_qualify_an_expired_shared_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            p,c,probe,r=self.fixture(folder);probe.after_click=lambda:setattr(c,'now',3.)
            with self.assertRaisesRegex(AssertionError,'deadline'):self.run_click(p,c,probe,r)
            self.assertFalse(r['editorClicks'][0]['ready']);self.assertIn('dpi-restore',probe.calls)
    def test_existing_engine_binding_cannot_admit_a_new_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            p,c,probe,r=self.fixture(folder);self.run_click(p,c,probe,r)
            probe.engine['creationTime']+=1
            with self.assertRaisesRegex(AssertionError,'generation'):self.run_click(p,c,probe,r)
            self.assertEqual(probe.calls.count('click'),1)
    def test_active_parent_deadline_and_single_click_intent_are_mandatory(self):
        for key,bad in [('ready',True),('deadlineScope','other'),('clickAttempts',2),('clickCompleted',True),
                ('deadline',4.),('startedAt',float('nan')),('childHwnd',99)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as folder:
                p,c,probe,r=self.fixture(folder);r['editorFocusReadiness'][key]=bad
                with self.assertRaises(AssertionError):self.run_click(p,c,probe,r)
                self.assertNotIn('move',probe.calls);self.assertNotIn('click',probe.calls)


class NativeEditorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'Measured owned editor click native boundary is missing')
        import editor_click_readiness as mod
        from test_suite_window_activation import Library
        self.mod=mod;self.user,self.kernel,self.dwm=Library(),Library(),Library()
        self.clock=Clock();self.probe=mod.NativeEditorClickProbe(9.,self.clock,
            user=self.user,kernel=self.kernel,dwm=self.dwm)
    def test_retained_engine_handle_requires_query_sync_without_inheritance(self):
        self.kernel.OpenProcess.action=lambda rights,inherit,pid:2**42
        handle=self.probe.open_engine(88)
        self.assertEqual(handle,2**42)
        self.assertEqual(self.kernel.OpenProcess.calls,[(0x00101000,False,88)])
        self.assertIs(self.kernel.OpenProcess.restype,ctypes.c_void_p)
        self.assertEqual(self.kernel.CloseHandle.argtypes,(ctypes.c_void_p,))
    def test_zero_engine_handle_fails_without_a_generation_claim(self):
        self.kernel.OpenProcess.action=lambda *args:0
        with self.assertRaises(OSError):self.probe.open_engine(88)
    def test_close_handle_is_mandatory_and_receipt_is_typed(self):
        r={};self.probe.close_engine(2**42,r)
        self.assertIs(r['engineHandleReleased'],True)
        self.kernel.CloseHandle.action=lambda handle:0
        with self.assertRaises(OSError):self.probe.close_engine(2**42,{})
    def test_native_signatures_and_input_structure_keep_win64_abi(self):
        self.assertEqual(ctypes.sizeof(self.mod.Input),40)
        self.assertEqual(self.user.IsChild.argtypes,(ctypes.c_void_p,ctypes.c_void_p))
        self.assertEqual(self.user.ClientToScreen.argtypes,(ctypes.c_void_p,ctypes.POINTER(self.mod.Point)))
        self.assertEqual(self.user.GetClientRect.argtypes,(ctypes.c_void_p,ctypes.POINTER(self.mod.Rect)))
    def test_native_client_corners_and_owned_descendant_hit_are_measured(self):
        def rect(hwnd, pointer):
            value=pointer._obj;value.left,value.top,value.right,value.bottom=10,20,110,220;return 1
        def client(hwnd, pointer):
            value=pointer._obj;value.left,value.top,value.right,value.bottom=0,0,100,200;return 1
        def screen(hwnd, pointer):pointer._obj.x+=10;pointer._obj.y+=20;return 1
        def owner(hwnd, pointer):pointer._obj.value=88;return 20
        self.user.GetWindowRect.action=rect;self.user.GetClientRect.action=client
        self.user.ClientToScreen.action=screen;self.user.GetWindowThreadProcessId.action=owner
        self.user.GetAncestor.action=lambda hwnd,flag:11
        value=self.probe._child_window(33)
        self.assertEqual(value['clientScreenRect'],[10,20,110,220])
        self.assertEqual((value['pid'],value['threadId'],value['rootHwnd']),(88,20,11))
        self.user.WindowFromPhysicalPoint.action=lambda point:34
        self.user.IsChild.action=lambda parent,child:(parent,child)==(33,34)
        hit=self.probe.editor_hit(33,(60,120))
        self.assertEqual(hit,dict(point=[60,120],hitHwnd=34,pid=88,threadId=20,
            rootHwnd=11,withinEditor=True,visible=True,enabled=True))
    def test_mouse_partial_or_unknown_insertion_has_no_second_down(self):
        for answer in [0,1,2,'raise']:
            with self.subTest(answer=answer):
                self.user.GetAsyncKeyState.action=lambda key:0
                self.user.GetPhysicalCursorPos.action=lambda pointer:(setattr(pointer._obj,'x',30),setattr(pointer._obj,'y',40),1)[2]
                self.user.GetSystemMetrics.action=lambda key:0
                sends=[]
                def send(count,payload,size):
                    sends.append((count,[payload[i].data.mouse.flags for i in range(count)],size))
                    if answer=='raise':raise OSError('native return unavailable')
                    return answer if len(sends)==1 else 1
                self.user.SendInput.action=send;r={'chosenPhysicalPoint':[30,40]}
                if answer==2:self.probe.click(r)
                else:
                    with self.assertRaises((AssertionError,OSError)):self.probe.click(r)
                self.assertEqual(sends[0],(2,[2,4],40))
                self.assertEqual(len(sends),2 if answer==1 else 1)
                if answer==1:self.assertEqual(sends[1],(1,[4],40))
                if answer=='raise':self.assertIsNone(r['insertedInputs'])
                else:self.assertEqual(r['insertedInputs'],answer)


if __name__=='__main__': unittest.main()
