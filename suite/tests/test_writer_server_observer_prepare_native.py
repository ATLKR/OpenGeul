"""Portable typed syscall seams; no real Windows calls or input."""
import ctypes as C
import importlib.util
import itertools
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).parents[1] / 'e2e' / 'writer_server_observer_prepare_native.py'
if SOURCE.exists():
    spec = importlib.util.spec_from_file_location('writer_server_observer_prepare_native', SOURCE)
    M = importlib.util.module_from_spec(spec);sys.modules[spec.name] = M;spec.loader.exec_module(M)
else:
    M = SimpleNamespace()


def number(value): return int(getattr(value, 'value', value) or 0)


def utf16(pointer):
    result = []
    for i in range(128):
        value = C.cast(pointer, C.POINTER(C.c_uint16))[i]
        if value == 0:break
        result.append(value)
    return b''.join(v.to_bytes(2, 'little') for v in result).decode('utf-16-le')


class Function:
    def __init__(self, call):self.call = call;self.argtypes = self.restype = None
    def __call__(self, *args):return self.call(*args)


class System:
    def __init__(self):
        count = itertools.count(1)
        (self.host, self.thread, self.host_pid, self.birth, self.host_tid,
         self.engine_pid, self.engine_tid, self.home, self.document,
         self.panel, self.child, self.descendant) = [next(count) for _ in range(12)]
        self.launch = SimpleNamespace(host=self.host, thread=self.thread,
            identity=(self.host_pid, self.birth), failed=False, resumed=True,
            uncertain=False, creation_job_membership=True, pre_resume_verified=True)
        self.windows = [self.home, self.document]
        self.facts = {
            self.home:(self.host_pid,self.host_tid,0,self.home),
            self.document:(self.host_pid,self.host_tid,0,self.document),
            self.panel:(self.host_pid,self.host_tid,self.document,self.document),
            self.child:(self.engine_pid,self.engine_tid,self.panel,self.document),
            self.descendant:(self.engine_pid,self.engine_tid,self.child,self.document),
        }
        self.props = {(self.document,'OpenGeul.Office.ParentHwnd'):self.panel,
                      (self.document,'OpenGeul.Office.ChildHwnd'):self.child}
        self.focus, self.foreground = self.child, self.document
        self.foreground_sequence = []
        self.capture = self.menu = self.flags = 0
        self.thread_alive = True
        self.child_queries_to_death = None
        self.enumerated = []
        self.events = []
        self.qpc = 1
        self.expired = False
        self.expire_after = None
        self.last_check = 0
        self.fail_gui = self.fail_image = False
        self.image = r'C:\synthetic-payload\Office\program\soffice.bin'
        self.changed_exports = False
        self.prop_reads = 0
        self.user = SimpleNamespace()
        self.kernel = SimpleNamespace()
        for name, function in {
            'EnumThreadWindows':self.enumerate, 'GetPropW':self.prop,
            'IsWindow':self.is_window, 'GetParent':self.parent,
            'GetAncestor':self.root, 'GetWindowThreadProcessId':self.window_identity,
            'IsChild':self.is_child, 'GetGUIThreadInfo':self.gui,
            'GetForegroundWindow':self.foreground_window,
        }.items():setattr(self.user,name,Function(function))
        for name, function in {'GetThreadId':self.thread_id, 'WaitForSingleObject':self.wait,
            'QueryFullProcessImageNameW':self.process_image}.items():setattr(self.kernel,name,Function(function))

    def check(self):
        if self.expired:raise RuntimeError('synthetic deadline')
        self.qpc += 1;self.last_check = self.qpc;return self.qpc

    def event(self, name):
        self.events.append(name)
        if name == self.expire_after:self.expired = True

    def thread_id(self, handle):
        self.event('thread-id');assert number(handle) == self.thread;return self.host_tid

    def wait(self, handle, milliseconds):
        self.event('thread-wait');assert number(handle) == self.thread and number(milliseconds) == 0
        return 258 if self.thread_alive else 0

    def enumerate(self, thread, callback, parameter):
        self.event('enumerate');self.enumerated.append(number(thread));assert number(thread) == self.host_tid
        for hwnd in self.windows:
            if not callback(hwnd,0):return False
        return True

    def is_window(self, hwnd):self.event('is-window');return number(hwnd) in self.facts
    def parent(self, hwnd):self.event('parent');return self.facts[number(hwnd)][2]
    def root(self, hwnd, mode):
        self.event('root');assert number(mode) == 2;return self.facts[number(hwnd)][3]

    def window_identity(self, hwnd, pid):
        self.event('window-identity');p,t,_,_ = self.facts[number(hwnd)]
        C.cast(pid,C.POINTER(C.c_uint32))[0] = p;return t

    def prop(self, hwnd, name):
        self.event('property');key = utf16(name)
        assert key in ('OpenGeul.Office.ParentHwnd','OpenGeul.Office.ChildHwnd')
        if number(hwnd) == self.document:
            self.prop_reads += 1
            if self.changed_exports and self.prop_reads > 2 and key.endswith('ChildHwnd'):return self.panel
        return self.props.get((number(hwnd),key),0)

    def is_child(self, parent, child):
        self.event('is-child');parent,child = number(parent),number(child)
        if self.child_queries_to_death is not None:
            self.child_queries_to_death -= 1
            if self.child_queries_to_death == 0:self.thread_alive = False
        seen = set()
        while child in self.facts and child not in seen:
            seen.add(child);child = self.facts[child][2]
            if child == parent:return True
        return False

    def gui(self, thread, output):
        self.event('gui');assert number(thread) == self.engine_tid and number(thread) != 0
        result = C.cast(output,C.POINTER(M.GuiThreadInfo)).contents
        assert result.size == 72
        if self.fail_gui:return False
        result.flags,self_focus = self.flags,self.focus
        result.focus,result.capture,result.menu = self_focus,self.capture,self.menu
        return True

    def foreground_window(self):
        self.event('foreground')
        return self.foreground_sequence.pop(0) if self.foreground_sequence else self.foreground

    def process_image(self, handle, flags, buffer, length):
        self.event('image');assert number(handle) > 0 and number(flags) == 0
        if self.fail_image:return False
        raw = self.image.encode('utf-16-le')
        target = C.cast(buffer,C.POINTER(C.c_uint16))
        for i in range(len(raw)//2):target[i] = int.from_bytes(raw[2*i:2*i+2],'little')
        C.cast(length,C.POINTER(C.c_uint32))[0] = len(raw)//2
        return True


class PreparationContracts(unittest.TestCase):
    def fixture(self):
        self.assertTrue(callable(getattr(M,'PreparationNativeApi',None)),'Preparation adapter missing')
        system = System()
        return M.PreparationNativeApi(object(),kernel=system.kernel,user=system.user),system

    def attachment(self, api, system):
        return api.find_attachment_once(system.launch,system.engine_pid,check=system.check)

    def test_only_original_thread_is_enumerated_and_fixed_exports_are_pinned(self):
        api,s = self.fixture();result = self.attachment(api,s)
        self.assertIsNotNone(result)
        self.assertEqual(s.enumerated,[s.host_tid])
        self.assertEqual(result.private_tuple(),(s.host,s.thread,s.host_pid,s.birth,s.host_tid,
            s.document,s.panel,s.child,s.engine_pid,s.engine_tid))

    def test_no_exports_yet_is_pending_without_another_window_search(self):
        api,s = self.fixture();s.props.clear()
        self.assertIsNone(self.attachment(api,s));self.assertEqual(s.enumerated,[s.host_tid])

    def test_more_than_one_exported_root_is_ambiguous(self):
        api,s = self.fixture();s.windows.append(s.document)
        with self.assertRaises(M.PreparationError):self.attachment(api,s)

    def test_dead_original_thread_is_not_replaced_by_reused_tid(self):
        api,s = self.fixture();s.thread_alive = False
        with self.assertRaises(M.PreparationError):self.attachment(api,s)
        self.assertFalse(s.enumerated)

    def test_foreign_engine_or_broken_parent_hierarchy_is_rejected(self):
        for change in ('engine','parent'):
            with self.subTest(change=change):
                api,s = self.fixture()
                p,t,parent,root = s.facts[s.child]
                s.facts[s.child] = (s.host_pid if change=='engine' else p,t,
                    s.document if change=='parent' else parent,root)
                with self.assertRaises(M.PreparationError):self.attachment(api,s)

    def test_exports_must_match_two_complete_reads(self):
        api,s = self.fixture();s.changed_exports = True
        with self.assertRaises(M.PreparationError):self.attachment(api,s)

    def test_recheck_uses_only_the_pinned_original_windows(self):
        api,s = self.fixture();result = self.attachment(api,s);s.enumerated.clear()
        self.assertIs(api.recheck_attachment(s.launch,result,check=s.check),True)
        self.assertFalse(s.enumerated)
        s.props[(s.document,'OpenGeul.Office.ChildHwnd')] = s.panel
        with self.assertRaises(M.PreparationError):api.recheck_attachment(s.launch,result,check=s.check)

    def test_original_thread_remains_live_after_the_last_attachment_read(self):
        api,s = self.fixture();attachment = self.attachment(api,s)
        # Keep stale/reused window facts after the original kernel thread dies.
        s.child_queries_to_death = 4
        with self.assertRaises(M.PreparationError):api.recheck_attachment(s.launch,attachment,check=s.check)

    def test_late_native_return_stops_before_the_next_native_query(self):
        api,s = self.fixture();s.expire_after = 'thread-id'
        with self.assertRaises(M.PreparationError):self.attachment(api,s)
        self.assertEqual(s.events[-1],'thread-id');self.assertFalse(s.enumerated)

    def test_callback_errors_are_closed_without_a_ctypes_exception_escape(self):
        api,s = self.fixture();s.expire_after = 'property'
        with self.assertRaises(M.PreparationError):self.attachment(api,s)
        self.assertEqual(s.events[-1],'property')

    def test_owned_focus_is_numeric_only_and_does_not_activate_or_input(self):
        api,s = self.fixture();attachment = self.attachment(api,s)
        result = api.focus_snapshot(s.launch,attachment,check=s.check)
        self.assertTrue(result.ready and result.query_succeeded and result.foreground_owned)
        self.assertTrue(result.focus_within_child and result.capture_clear and result.menu_clear and result.flags_clear)
        self.assertTrue(all(type(v) in (bool,int) for v in result.numeric_projection().values()))
        self.assertEqual(repr(result),'<FocusSnapshot private>')

    def test_focus_outside_original_child_is_unknown_without_fallback(self):
        api,s = self.fixture();attachment = self.attachment(api,s);s.focus = s.panel
        result = api.focus_snapshot(s.launch,attachment,check=s.check)
        self.assertFalse(result.ready or result.focus_within_child)
        self.assertEqual(s.events.count('gui'),1)

    def test_foreground_change_across_gui_observation_remains_unknown(self):
        api,s = self.fixture();attachment = self.attachment(api,s)
        s.foreground_sequence = [s.document,s.home]
        result = api.focus_snapshot(s.launch,attachment,check=s.check)
        self.assertFalse(result.ready or result.foreground_owned)
        self.assertEqual(s.events.count('foreground'),2)

    def test_foreign_foreground_or_capture_or_flags_never_qualifies(self):
        for change in ('foreground','capture','menu','flags'):
            with self.subTest(change=change):
                api,s = self.fixture();attachment = self.attachment(api,s)
                setattr(s,change,s.home if change!='flags' else 1)
                self.assertFalse(api.focus_snapshot(s.launch,attachment,check=s.check).ready)

    def test_failed_editor_gui_query_is_not_a_positive_snapshot(self):
        api,s = self.fixture();attachment = self.attachment(api,s);s.fail_gui = True
        with self.assertRaises(M.PreparationError):api.focus_snapshot(s.launch,attachment,check=s.check)

    def test_image_is_queried_from_original_handle_without_pid_open(self):
        api,s = self.fixture()
        self.assertEqual(api.process_image(s.host,check=s.check),s.image)
        self.assertEqual(s.events,['image'])
        s.fail_image = True
        with self.assertRaises(M.PreparationError):api.process_image(s.host,check=s.check)

    def test_attachment_and_errors_have_no_private_identity_repr(self):
        api,s = self.fixture();attachment = self.attachment(api,s)
        self.assertEqual(repr(attachment),'<OriginalAttachment private>')
        with self.assertRaises((AttributeError,TypeError)):attachment.document = s.home
        s.thread_alive = False
        with self.assertRaises(M.PreparationError) as caught:api.recheck_attachment(s.launch,attachment,check=s.check)
        self.assertTrue(str(caught.exception).startswith('writer_observer_preparation_'))


if __name__ == '__main__':unittest.main()
