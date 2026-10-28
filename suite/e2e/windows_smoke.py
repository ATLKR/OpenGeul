"""Actual Suite home, six existing/new embedded frames, and three keyboard edits.

Only generated fixtures under --fixtures are opened. ASCII editor markers use
physical US scans; separate Korean IME cases prove actual composition.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile

_evidence_spec = importlib.util.spec_from_file_location(
    'suite_native_window_evidence', Path(__file__).with_name('native_window_evidence.py'))
_evidence = importlib.util.module_from_spec(_evidence_spec)
_evidence_spec.loader.exec_module(_evidence)
NativeWindowProbe, prepare_launch_pointer = _evidence.NativeWindowProbe, _evidence.prepare_launch_pointer
_ascii_spec = importlib.util.spec_from_file_location(
    'suite_ascii_editor_input', Path(__file__).with_name('ascii_editor_input.py'))
ascii_input = importlib.util.module_from_spec(_ascii_spec)
_ascii_spec.loader.exec_module(ascii_input)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numeric_notice
import calc_model_barrier
from scenario_editor_shortcuts import FirstAdmissionEditorSession
from owned_control_actions import click_owned_control, send_host_menu_shortcut, send_owned_dialog_escape
from owned_save_menu import require_save_menu_action, detached_save_menu_action

INPUT_CASES = (('writer', 'docx'), ('calc', 'xlsx'), ('impress', 'pptx'))
EDITOR_MARKERS = {module: 'UI-OpenGeul-' + module for module, _ in INPUT_CASES}
ATTACH_CASES = (('draw', 'odg'), ('math', 'odf'), ('base', 'odb'))
MODULE_LABELS = tuple('OpenGeul ' + name for name in ('HWP', 'Writer', 'Calc', 'Impress', 'Draw', 'Math', 'Base'))
NEW_MODULES = tuple(module for module, _ in INPUT_CASES + ATTACH_CASES)


def launch_working_directory(suite, working_directory=None):
    if working_directory is None:
        return suite
    directory = Path(working_directory)
    if not directory.is_absolute() or str(directory).startswith(('\\\\', '//')) or '..' in directory.parts:
        raise ValueError('Launch directory must be a local absolute path without traversal')
    for part in (directory, *directory.parents):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Launch directory ancestors must be ordinary directories without links or reparse points')
    if directory.resolve() != directory:
        raise ValueError('Launch directory aliases are not accepted')
    root = Path(suite).resolve()
    if directory == root or root in directory.parents or directory in root.parents:
        raise ValueError('Explicit launch directory must be outside and separate from the Suite payload')
    return directory


def launch_suite(command, suite, output, name, *, environment=None, working_directory=None):
    cwd = launch_working_directory(suite, working_directory)
    if working_directory is not None and (not command or not Path(command[0]).is_absolute()):
        raise ValueError('Explicit launch directory requires an absolute executable command')
    prepare_launch_pointer(output, name)
    # Popen duplicates the file handle for the child; the parent's stream closes here.
    with (output / (name + '-stderr.log')).open('xb') as stderr:
        process = subprocess.Popen(command, cwd=cwd, shell=False, stderr=stderr, env=environment)
    process.opengeul_evidence_output, process.opengeul_evidence_case = output, name
    process.opengeul_suite_root = Path(suite).resolve()
    return process


def activate_owned_suite(api, process, hwnd, record):
    from suite_window_activation import activate_suite_window
    return activate_suite_window(api.require_foreground, process, hwnd, record)


def click_owned_editor(api, process, hwnd, parent, child, office_pid, record):
    from editor_click_readiness import click_editor_once
    return click_editor_once(api.require_foreground, process, hwnd, parent, child, office_pid, record)


def is_owned_startup_error(dialog_pid, shell_pid, owner_pid, caption, class_name):
    return shell_pid > 0 and dialog_pid == shell_pid and owner_pid == shell_pid \
        and caption == 'OpenGeul Office' and class_name == '#32770'


def new_document_command(suite, module):
    assert module in NEW_MODULES, 'Only the six owned Office modules may create blank test documents'
    return [str(suite / 'OpenGeul.Office.exe'), '--module', module]


def new_base_target(fixtures):
    assert fixtures.is_dir() and not fixtures.is_symlink() and not getattr(fixtures, 'is_junction', lambda: False)(), 'New Base save requires the owned fixture directory'
    target = fixtures / 'New-OpenGeul-base.odb'
    assert not target.exists() and not target.is_symlink(), 'New Base Save As must never overwrite a document'
    target = target.resolve()
    assert target.parent == fixtures.resolve(), 'New Base target escaped generated fixtures'
    return target


def saved_base_evidence(path):
    assert not path.is_symlink(), 'Saved Base evidence must not link to another document'
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None, 'Saved ODB has corrupt ZIP members'
        # Pinned LibreOffice documentconstants.hxx: MIMETYPE_OASIS_OPENDOCUMENT_DATABASE.
        assert archive.read('mimetype') == b'application/vnd.oasis.opendocument.base', 'Saved file is not an ODF database'
        content = ET.fromstring(archive.read('content.xml'))
        connections = [value for item in content.iter() for key, value in item.attrib.items()
                       if key == '{http://www.w3.org/1999/xlink}href']
        assert 'sdbc:embedded:firebird' in connections, 'Saved ODB lost its embedded Firebird connection'
    payload = path.read_bytes()
    assert payload, 'Saved ODB is empty'
    return {'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload), 'connection': 'sdbc:embedded:firebird'}


def attach_only_content_status(module, before, after):
    assert module in ('draw', 'math', 'base'), 'Byte policy applies only to attach-only fixtures'
    unchanged = before == after
    assert module == 'base' or unchanged, 'Attach-only test changed the generated document'
    return {'fixtureUnchanged': unchanged, 'contentVerificationRequired': module == 'base'}


def literal_keys(text):
    return ''.join('{' + char + '}' if char in '+^%~(){}' else char for char in text)


def require_dialog_identity(pid, shell_pid, owner, document, title, expected_title, class_name):
    assert pid == shell_pid and pid > 0, 'Dialog belongs to a different process'
    assert owner == document and document > 0, 'Dialog is not owned by the tested document'
    assert title == expected_title and class_name == '#32770', 'Dialog is not the exact expected native prompt'


def wait_for(check, seconds=60):
    deadline = time.monotonic() + seconds
    last = None
    transient_error = None
    while time.monotonic() < deadline:
        try:
            last = check()
        except (FileNotFoundError, zipfile.BadZipFile) as exc:
            last = None
            transient_error = type(exc).__name__ + ': ' + str(exc)
        if last: return last
        time.sleep(0.1)
    raise AssertionError('Native UI condition did not become true: ' + str(last)
                         + ('; last transient error: ' + transient_error if transient_error else ''))


def require_home_labels(labels):
    observed = [label for label in labels if label.startswith('OpenGeul ')]
    assert sorted(observed) == sorted(MODULE_LABELS), 'Home must expose each exact OpenGeul module label once: ' + str(observed)
    return observed


def require_engine_fixture(fixtures, module, extension):
    assert (module, extension) in INPUT_CASES + ATTACH_CASES, 'Only fixed generated module fixtures may be opened'
    source = fixtures / ('OpenGeul-' + module + '.' + extension)
    for path in (fixtures, source):
        assert not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'Fixture links are not accepted'
    assert source.is_file(), 'Generated fixture is missing: ' + source.name
    source = source.resolve()
    assert source.parent == fixtures.resolve(), 'Fixture escaped its owned directory'
    baseline = json.loads((fixtures.parent / 'engine-smoke.json').read_text(encoding='utf-8'))
    assert baseline.get('schemaVersion') == 1 and baseline.get('kind') == 'engine' and baseline.get('passed') is True, 'A passing generated engine baseline is required'
    cases = [case for case in baseline['cases'] if case.get('module') == module]
    assert len(cases) == 1 and cases[0].get('status') == 'passed', 'The module engine baseline must pass exactly once'
    case = cases[0]
    assert Path(case['fixture']).resolve() == source, 'Engine baseline names a different fixture'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == case.get('sha256'), 'Generated fixture differs from engine baseline'
    return source


class GuiThreadInfo(ctypes.Structure):
    # Fixed Win32 widths also let non-Windows receipt replay check the x64 ABI.
    _fields_ = [('cbSize', ctypes.c_uint32), ('flags', ctypes.c_uint32),
                ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                ('rcCaret', _evidence.Rect)]


class Windows:
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = (self.callback, wintypes.LPARAM)
        self.user.EnumWindows.restype = wintypes.BOOL
        self.user.GetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
        self.user.GetPropW.restype = wintypes.HANDLE
        self.user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user.GetWindow.restype = wintypes.HWND
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetForegroundWindow.argtypes = ()
        self.user.IsChild.argtypes = (wintypes.HWND, wintypes.HWND)
        self.user.IsChild.restype = wintypes.BOOL
        self.user.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user.IsWindowVisible.restype = wintypes.BOOL
        self.user.IsWindow.argtypes = (wintypes.HWND,)
        self.user.IsWindow.restype = wintypes.BOOL
        self.user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.user.PostMessageW.restype = wintypes.BOOL
        self.user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        self.user.GetWindowTextW.restype = ctypes.c_int
        self.user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        self.user.GetClassNameW.restype = ctypes.c_int
        self.user.GetGUIThreadInfo.argtypes = (wintypes.DWORD, ctypes.POINTER(GuiThreadInfo))
        self.user.GetGUIThreadInfo.restype = wintypes.BOOL

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def query_gui_thread_info(self, thread):
        """Use the structure type belonging to this API instance's prototype."""
        assert type(thread) is int and 0 < thread < 2**32, 'Owned native input thread must be a positive DWORD'
        info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
        if not self.user.GetGUIThreadInfo(thread, ctypes.byref(info)):
            raise OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), 'GetGUIThreadInfo for owned filename field failed')
        return info

    def request_close(self, hwnd, shell_pid):
        assert self.user.IsWindow(hwnd), 'Close target is not a live window'
        assert self.pid(hwnd) == shell_pid, 'Close target belongs to a different process'
        assert self.user.GetAncestor(hwnd, 2) == hwnd, 'Only the owned top-level Suite form may close'
        if not self.user.PostMessageW(hwnd, 0x0010, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def windows(self, pid):
        found = []
        def visit(hwnd, _):
            if self.pid(hwnd) == pid and self.user.IsWindowVisible(hwnd): found.append(hwnd)
            return True
        callback = self.callback(visit)
        if not self.user.EnumWindows(callback, 0): raise ctypes.WinError(ctypes.get_last_error())
        if not hasattr(self, '_last_window_enumerations'):
            self._last_window_enumerations = {}
        self._last_window_enumerations[pid] = list(found)
        return found

    def external_window_message(self, pid, message):
        handles = self._last_window_enumerations[pid]
        try:
            census = NativeWindowProbe().window_census(handles, pid)
        except Exception as exc:
            census = {'officePid': pid, 'enumeratedHwnds': handles,
                      'censusError': type(exc).__name__ + ': ' + str(exc)}
        output, case = getattr(self, 'evidence_output', None), getattr(self, 'evidence_case', None)
        if output is not None and case is not None:
            try:
                with (Path(output) / (case + '-offending-windows.json')).open('x', encoding='utf-8') as stream:
                    json.dump(census, stream, ensure_ascii=False, indent=2)
                    stream.write('\n')
            except Exception as exc:
                census['censusWriteError'] = type(exc).__name__ + ': ' + str(exc)
        return message + '\nOffending Office HWND census: ' + json.dumps(census, ensure_ascii=False)

    def title(self, hwnd):
        text = ctypes.create_unicode_buffer(2048)
        self.user.GetWindowTextW(hwnd, text, len(text))
        return text.value

    def class_name(self, hwnd):
        name = ctypes.create_unicode_buffer(256)
        self.user.GetClassNameW(hwnd, name, len(name))
        return name.value

    def attached(self, process):
        windows = self.windows(process.pid)
        for hwnd in windows:
            caption = self.title(hwnd)
            if caption != 'OpenGeul Office' or self.class_name(hwnd) != '#32770': continue
            owner = self.user.GetWindow(hwnd, 4)
            if not owner or not self.user.IsWindow(owner) or self.user.GetAncestor(owner, 2) != owner: continue
            if is_owned_startup_error(self.pid(hwnd), process.pid, self.pid(owner), caption, self.class_name(hwnd)):
                failure=AssertionError(f'Owned Suite startup-error dialog HWND {int(hwnd)} owner {int(owner)}; inspect case stderr log')
                try:
                    if numeric_notice.notices_enabled():
                        import startup_diagnostics
                        startup_diagnostics.attach(failure,startup_diagnostics.receive(self,process,hwnd,owner))
                except Exception:
                    pass
                raise failure
        for hwnd in windows:
            parent = self.user.GetPropW(hwnd, 'OpenGeul.Office.ParentHwnd')
            child = self.user.GetPropW(hwnd, 'OpenGeul.Office.ChildHwnd')
            if parent and child:
                assert self.user.IsWindow(parent) and self.user.IsWindow(child), 'Editor HWNDs are not live windows'
                assert self.user.IsChild(hwnd, parent), 'Host panel is not owned by Suite'
                assert self.user.IsChild(parent, child), 'Office editor is not inside host panel'
                if not self.user.IsWindowVisible(child): continue
                return int(hwnd), int(parent), int(child)
        if process.poll() is not None: raise AssertionError('Suite shell exited before native attachment')
        return None

    def require_foreground(self, hwnd):
        foreground = self.user.GetForegroundWindow()
        assert self.user.GetAncestor(foreground, 2) == hwnd, 'Physical input requires the owned Suite foreground'

    def require_editor_focus(self, hwnd, child):
        self.require_foreground(hwnd)
        thread = self.user.GetWindowThreadProcessId(child, None)
        assert thread > 0, 'Owned editor thread is not live; foreground-thread fallback is forbidden'
        info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
        if not self.user.GetGUIThreadInfo(thread, ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
        assert info.hwndFocus and (info.hwndFocus == child or self.user.IsChild(child, info.hwndFocus)), 'Keyboard focus is outside the embedded Office editor'
        try:
            assert not info.hwndCapture, 'Owned editor mouse capture is still active before physical input'
        except AssertionError as primary:
            try:
                from focus_rejection_diagnostics import retain_capture_rejection
                retain_capture_rejection(self, hwnd, child, thread, info, primary)
            except BaseException as diagnostic_error:
                try: primary.opengeul_focus_rejection_error = type(diagnostic_error).__name__
                except BaseException: pass
            raise
        return int(info.hwndFocus)

    def _focus_window(self, hwnd):
        hwnd = int(hwnd or 0)
        live = bool(hwnd and self.user.IsWindow(hwnd))
        pid = wintypes.DWORD()
        thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) if live else 0
        return {'hwnd': hwnd, 'isWindow': live, 'pid': int(pid.value), 'threadId': int(thread),
                'rootHwnd': int(self.user.GetAncestor(hwnd, 2) or 0) if live else 0,
                'className': self.class_name(hwnd) if live else ''}

    def editor_focus_snapshot(self, hwnd, child, shell_pid, office_pid):
        """Observe the explicit editor thread; never substitute foreground TID 0.

        GetGUIThreadInfo is a snapshot, not an input-completion acknowledgement.
        Retain both surrounding ownership/foreground observations for diagnosis.
        """
        def binding():
            return {'suite': self._focus_window(hwnd), 'editor': self._focus_window(child),
                    'foreground': self._focus_window(self.user.GetForegroundWindow()),
                    'editorWithinSuite': bool(self.user.IsChild(hwnd, child))}
        before = binding()
        thread = before['editor']['threadId']
        info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
        suite, editor = before['suite'], before['editor']
        allowed = bool(suite['isWindow'] and suite['pid'] == shell_pid and suite['rootHwnd'] == hwnd
            and editor['isWindow'] and editor['pid'] == office_pid and editor['rootHwnd'] == hwnd
            and before['editorWithinSuite'] and thread > 0)
        if allowed: getattr(ctypes, 'set_last_error', lambda value: None)(0)
        queried = bool(allowed and self.user.GetGUIThreadInfo(thread, ctypes.byref(info)))
        error = getattr(ctypes, 'get_last_error', lambda: 0)() if not queried else 0
        return {'before': before, 'after': binding(), 'queriedThreadId': thread,
                'cbSize': int(info.cbSize), 'queryAttempted': allowed, 'querySucceeded': queried,
                'lastError': int(error),
                'flags': int(info.flags), 'active': self._focus_window(info.hwndActive),
                'focus': self._focus_window(info.hwndFocus), 'capture': self._focus_window(info.hwndCapture),
                'menuOwner': self._focus_window(info.hwndMenuOwner),
                'moveSize': self._focus_window(info.hwndMoveSize), 'caret': self._focus_window(info.hwndCaret),
                'caretRect': [info.rcCaret.left, info.rcCaret.top, info.rcCaret.right, info.rcCaret.bottom],
                'focusWithinEditor': bool(info.hwndFocus and
                    (info.hwndFocus == child or self.user.IsChild(child, info.hwndFocus)))}

    def home(self, process):
        homes = [hwnd for hwnd in self.windows(process.pid) if self.title(hwnd) == 'OpenGeul Office']
        assert len(homes) <= 1, 'Expected one Suite home, not a modal error or duplicate home'
        if homes: return homes[0]
        if process.poll() is not None: raise AssertionError('Suite exited before showing its home')
        return None


def _editor_focus_snapshot_ready(snapshot, hwnd, child, shell_pid, office_pid, thread):
    for edge in ('before', 'after'):
        suite, editor, foreground = (snapshot[edge][key] for key in ('suite', 'editor', 'foreground'))
        assert (suite['isWindow'] and suite['hwnd'] == hwnd and suite['pid'] == shell_pid
                and suite['rootHwnd'] == hwnd), 'Owned Suite window identity changed during focus preparation'
        assert (editor['isWindow'] and editor['hwnd'] == child and editor['pid'] == office_pid
                and editor['threadId'] > 0 and editor['rootHwnd'] == hwnd
                and snapshot[edge]['editorWithinSuite']), 'Owned editor window identity changed during focus preparation'
        assert editor['threadId'] == thread, 'Owned editor thread identity changed during focus preparation'
        assert (foreground['isWindow'] and foreground['rootHwnd'] == hwnd
                and foreground['pid'] in (shell_pid, office_pid)), 'Physical input requires the owned Suite foreground during focus preparation'
    assert snapshot['queriedThreadId'] == thread and snapshot['cbSize'] == 72, 'Owned editor query thread or Win64 structure size changed'
    assert snapshot['queryAttempted'] is True, 'Owned editor native query was not attempted'
    if snapshot['querySucceeded'] is not True:
        raise OSError(snapshot['lastError'], 'GetGUIThreadInfo for owned editor failed')
    assert snapshot['lastError'] == 0, 'Successful editor focus query has a nonzero native error'
    focus = snapshot['focus']
    if focus['hwnd']:
        assert (focus['isWindow'] and focus['rootHwnd'] == hwnd
                and focus['pid'] in (shell_pid, office_pid)), 'Observed foreign or dead keyboard focus during editor preparation'
    ready = bool(snapshot['focusWithinEditor'] and focus['isWindow'] and focus['pid'] == office_pid)
    if snapshot['focusWithinEditor']:
        assert ready, 'Observed foreign keyboard focus inside the editor hierarchy'
        assert focus['threadId'] == thread, 'Observed keyboard focus belongs to another editor thread'
    capture = snapshot['capture']['hwnd']
    assert type(capture) is int and capture >= 0, 'Invalid native mouse capture observation'
    # Zero capture excludes current Win32 capture; it is not input completion.
    return focus['hwnd'] if ready and capture == 0 else None


def require_editor_focus_readiness(evidence, hwnd, child, shell_pid, office_pid):
    """Replay successful raw readiness evidence without Windows APIs or input."""
    assert evidence['schemaVersion'] == 1 and evidence['kind'] == 'owned-editor-focus-readiness', 'Invalid editor readiness receipt'
    assert evidence['ready'] is True, 'Editor focus was not ready'
    assert (evidence['suiteHwnd'], evidence['childHwnd'], evidence['shellPid'], evidence['officePid']) == (hwnd, child, shell_pid, office_pid), 'Readiness receipt belongs to another editor generation'
    assert 0 < evidence['deadlineSeconds'] <= 10, 'Editor readiness deadline is not bounded'
    assert evidence['deadlineScope'] == 'editor-setup-and-focus', 'Editor readiness has no shared entry deadline'
    assert all(type(evidence[key]) in (int, float) and math.isfinite(evidence[key])
               for key in ('startedAt', 'deadline', 'deadlineSeconds')), 'Invalid editor readiness clock'
    assert evidence['deadline'] == evidence['startedAt'] + evidence['deadlineSeconds'], 'Editor readiness entry deadline differs'
    assert all(type(evidence[key]) is int and evidence[key] == 1 for key in ('clickAttempts', 'controlF6Attempts')), 'Editor setup input was repeated or omitted'
    assert evidence['clickCompleted'] is True and evidence['controlF6Completed'] is True, 'Original editor setup input did not complete'
    rows = evidence['snapshots']
    assert len(rows) >= 3 and [row['phase'] for row in rows[:3]] == ['before-click', 'after-click', 'after-control-f6'], 'Editor setup snapshots are incomplete or reordered'
    assert all(row['phase'] == 'wait' for row in rows[3:]), 'Unexpected readiness input or snapshot phase'
    assert evidence['pollStartedSeconds'] == rows[2]['elapsedSeconds'], 'Focus poll deadline is not bound to the original setup observation'
    previous, focus = -1, None
    for index, row in enumerate(rows):
        assert row['elapsedSeconds'] >= 0 and row['elapsedSeconds'] >= previous, 'Editor focus observation time moved backwards'
        assert row['elapsedSeconds'] <= evidence['deadlineSeconds'], 'Editor setup exceeded the shared entry deadline'
        previous = row['elapsedSeconds']
        observed = _editor_focus_snapshot_ready(row, hwnd, child, shell_pid, office_pid, evidence['editorThreadId'])
        if index >= 2:
            if index < len(rows) - 1: assert not observed, 'Focus polling continued after readiness'
            focus = observed
    assert focus and focus == evidence['focusHwnd'], 'Final strict focus differs from the ready owned editor'
    return evidence


def prepare_editor_focus(api, hwnd, child, shell_pid, office_pid, record,
                         click_editor, enter_document, seconds=5):
    """Share one entry deadline across single click/Ctrl+F6 and focus observations.

    A missing focus, live Suite setup control, or mouse capture may be pending.
    Foreign foreground/focus, changed ownership, and native query errors fail
    immediately. Zero capture does not establish edit mode or input completion,
    nor does this establish the cause of a previous focus failure.
    """
    assert type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 10, 'Editor focus readiness must have a bounded deadline'
    started = time.monotonic()
    deadline = started + seconds
    evidence = {'schemaVersion': 1, 'kind': 'owned-editor-focus-readiness', 'ready': False,
                'suiteHwnd': hwnd, 'childHwnd': child, 'shellPid': shell_pid,
                'officePid': office_pid, 'deadlineSeconds': seconds, 'startedAt': started,
                'deadline': deadline, 'deadlineScope': 'editor-setup-and-focus', 'snapshots': [],
                'clickAttempts': 0, 'clickCompleted': False,
                'controlF6Attempts': 0, 'controlF6Completed': False}
    record['editorFocusReadiness'] = evidence
    record.setdefault('editorFocusReadinessRecords', []).append(evidence)

    def observe(phase):
        assert time.monotonic() < deadline, 'Editor focus shared entry deadline expired'
        snapshot = api.editor_focus_snapshot(hwnd, child, shell_pid, office_pid)
        snapshot.update(phase=phase, elapsedSeconds=round(time.monotonic() - started, 6))
        evidence['snapshots'].append(snapshot)
        assert time.monotonic() <= deadline, 'Editor focus query exceeded the shared entry deadline'
        evidence.setdefault('editorThreadId', snapshot['before']['editor']['threadId'])
        return _editor_focus_snapshot_ready(snapshot, hwnd, child, shell_pid, office_pid, evidence['editorThreadId'])

    try:
        observe('before-click')
        assert time.monotonic() < deadline, 'Editor click cannot start after the shared entry deadline'
        evidence['clickAttempts'] += 1
        click_editor()
        evidence['clickCompleted'] = True
        assert time.monotonic() < deadline, 'Editor click exceeded the shared entry deadline'
        observe('after-click')
        assert time.monotonic() < deadline, 'Editor Ctrl+F6 cannot start after the shared entry deadline'
        evidence['controlF6Attempts'] += 1
        enter_document()
        evidence['controlF6Completed'] = True
        assert time.monotonic() < deadline, 'Editor Ctrl+F6 exceeded the shared entry deadline'
        focus = observe('after-control-f6')
        evidence['pollStartedSeconds'] = evidence['snapshots'][-1]['elapsedSeconds']
        while not focus and time.monotonic() < deadline:
            time.sleep(min(.05, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline: break
            focus = observe('wait')
            if time.monotonic() > deadline: focus = None
        assert focus, 'Owned editor keyboard focus did not become ready before the deadline'
        # Focus, ownership and zero capture belong to the same final full row.
        final_row=evidence['snapshots'][-1]
        strict_focus = _editor_focus_snapshot_ready(final_row,hwnd,child,shell_pid,office_pid,evidence['editorThreadId'])
        assert time.monotonic() <= deadline, 'Final strict editor focus validation exceeded the shared entry deadline'
        assert strict_focus == focus, 'Owned editor focus changed before physical input'
        assert final_row['focus']['pid'] == office_pid, 'Observed foreign keyboard focus before editor input'
        evidence.update(ready=True, focusHwnd=focus)
        require_editor_focus_readiness(evidence, hwnd, child, shell_pid, office_pid)
        return focus
    except Exception:
        evidence['ready'] = False
        raise
    finally:
        finished = time.monotonic()
        evidence['elapsedSeconds'] = round(finished - started, 6)
        if evidence['ready'] and finished > deadline:
            evidence['ready'] = False
            raise AssertionError('Editor readiness finalization exceeded the shared entry deadline')


def package_text(path):
    with zipfile.ZipFile(path) as archive:
        return '\n'.join(''.join(ET.fromstring(archive.read(name)).itertext())
                         for name in archive.namelist()
                         if (name == 'word/document.xml' or name == 'xl/sharedStrings.xml'
                             or name.startswith('xl/worksheets/') or name.startswith('ppt/slides/'))
                         and name.endswith('.xml'))


def _record_save_read_transient(receipt, exc):
    row=dict(kind=type(exc).__name__,errno=getattr(exc,'errno',None),
             winerror=getattr(exc,'winerror',None),observedAt=time.monotonic())
    receipt['transientCount']+=1
    receipt.setdefault('firstTransient',row);receipt['lastTransient']=row


def read_saving_document(source, deadline, receipt):
    """Read one save-readiness snapshot; None requests another bounded poll.

    Only read errors are retryable here. Parsing, input and independent final
    reads retain their own fatal checks. Empty bytes are not a retry sentinel.
    """
    def budget():
        assert time.monotonic()<deadline,'Original document save deadline expired during byte observation'
    budget()
    receipt.setdefault('deadline',deadline)
    assert receipt['deadline']==deadline,'Original document save deadline changed'
    receipt.setdefault('attempts',0);receipt.setdefault('transientCount',0)
    receipt['attempts']+=1
    try:
        raw=source.read_bytes()
    except (PermissionError,FileNotFoundError) as exc:
        _record_save_read_transient(receipt,exc);budget();return None
    budget()
    return raw


def wait_saved_marker(source, marker, before_sha256, deadline, record):
    """Observe this generated document's save under its original deadline.

    An unreadable file is only a retry candidate, not proof of a sharing
    violation. Persistent denial still fails. XML and hash use the same bytes.
    """
    receipt=record['savedMarkerRead']=dict(deadline=deadline,attempts=0,transientCount=0)
    def budget():
        assert time.monotonic()<deadline,'Original GUI save deadline expired during persisted-marker observation'
    def check():
        payload=read_saving_document(source,deadline,receipt)
        if payload is None:return False
        try:
            text=package_text(io.BytesIO(payload))
        except zipfile.BadZipFile as exc:
            _record_save_read_transient(receipt,exc);budget();return False
        budget()
        if marker not in text:return False
        digest=hashlib.sha256(payload).hexdigest()
        budget()
        assert digest!=before_sha256,'Saved file bytes did not change'
        return digest
    budget()
    digest=wait_for(check,seconds=deadline-time.monotonic())
    budget()
    receipt.update(sha256=digest,observedAt=time.monotonic())
    return digest


def write_result(output, name, record):
    try:
        (output / (name + '-result.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    except Exception as exc:
        try:
            if numeric_notice.notices_enabled():
                record.setdefault('numericFailure', numeric_notice.capture_failure_code(exc))
        except Exception: pass
        raise
    finally:
        try: numeric_notice.emit_case_notice(name, record)
        except Exception: pass


def capture_failure(output, name, record, exc):
    try:
        if numeric_notice.notices_enabled():
            record.setdefault('numericFailure', numeric_notice.capture_failure_code(exc))
            record.setdefault('numericFailureFrames', numeric_notice.capture_failure_frames(exc))
            startup=numeric_notice.captured_startup(record)
            if startup[0]>0:record.setdefault('numericStartupDiagnostic',startup)
    except Exception: pass
    record.update(success=False, error=type(exc).__name__ + ': ' + str(exc),
                  traceback=''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(output / (name + '-failure.png'))
    except Exception: pass


def stop_owned_test_process(process, record, diagnostic_lease=None):
    if diagnostic_lease is not None:
        from editor_capture_diagnostic import CohortEngineLease
        assert isinstance(diagnostic_lease,CohortEngineLease), 'Owned focus cleanup requires its retained lease'
        return diagnostic_lease.stop_owned_process(process,record)
    exit_code = process.poll()
    receipt = dict(shellPid=process.pid, forceRequested=False, shellExitCode=exit_code,
                   gracefulShutdownVerified=False, disposition='already-exited')
    record['testProcessCleanup'] = receipt
    if exit_code is not None: return
    try:
        # Only this launched generated-fixture test and its descendants are eligible.
        # Retain intent before taskkill: a killed worker cannot finish its own
        # archive. This controller receipt never qualifies a graceful shutdown.
        receipt.update(forceRequested=True, disposition='stop-unconfirmed')
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        # Retained diagnostic descendants may share only this existing exit phase.
        exit_started=time.monotonic()
        receipt.update(exitWaitStartedAt=exit_started,exitWaitDeadline=exit_started+5,
                       exitWaitBudgetSeconds=5)
        receipt.update(shellExitCode=process.wait(timeout=5), disposition='forced-stop-returned')
    except Exception as exc:
        exit_code = process.poll()
        receipt.update(shellExitCode=exit_code, errorType=type(exc).__name__)
        if isinstance(exc, subprocess.CalledProcessError) and exc.returncode == 128 and exit_code == 0:
            # The owned shell completed normal shutdown between poll and taskkill.
            # Preserve any original case failure; this is only secondary cleanup evidence.
            record.update(cleanupExitRaceVerified=True, cleanupProcessExitCode=exit_code)
            receipt['disposition'] = 'exit-zero-after-taskkill-not-found'
            return
        record.update(success=False, cleanupError=type(exc).__name__ + ': ' + str(exc),
                      cleanupProcessExitCode=exit_code,
                      cleanupTraceback=''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def close_home(api, process, record):
    record['stage'] = 'find-home'
    home = wait_for(lambda: api.home(process), seconds=10)
    record['stage'] = 'close-home'
    api.request_close(home, process.pid)
    record['stage'] = 'wait-shell-exit'
    process.wait(timeout=25)
    assert process.returncode == 0, 'Suite did not close cleanly'


def _verified_saved_calc_close_proof(suite, owned_root, source, baseline, **options):
    from generated_calc_close import freeze_saved_calc_from_baseline
    return freeze_saved_calc_from_baseline(suite, owned_root, source, baseline, **options)


def close_document(api, process, hwnd, child, record, *, calc_close_proof=None):
    if record.get('module') == 'calc':
        from generated_calc_close import (GeneratedBlankCalc, SavedCalcCopy,
                                          close_generated_blank_calc, close_saved_calc_copy)
        assert isinstance(calc_close_proof, (SavedCalcCopy, GeneratedBlankCalc)), 'Calc cleanup requires an explicit verified generated-copy or fresh-blank token'
        closer = close_generated_blank_calc if isinstance(calc_close_proof, GeneratedBlankCalc) else close_saved_calc_copy
        closer(api, process, hwnd, child, record, calc_close_proof)
        return
    assert calc_close_proof is None, 'Calc discard authorization cannot close another module'
    # HwndWrapper.close() adds a 2s deadline before our async teardown waits.
    # Post the same owned WM_CLOSE once, then use the explicit lifecycle bounds.
    record['stage'] = 'close-document'
    api.request_close(hwnd, process.pid)
    record['stage'] = 'wait-document-close'
    wait_for(lambda: not api.user.IsWindow(hwnd), seconds=20)
    record['stage'] = 'wait-editor-close'
    wait_for(lambda: not api.user.IsWindow(child), seconds=10)


def verified_attachment(api, process, module):
    api.evidence_output = getattr(process, 'opengeul_evidence_output', None)
    api.evidence_case = getattr(process, 'opengeul_evidence_case', None)
    hwnd, parent, child = wait_for(lambda: api.attached(process), seconds=150)
    office_pid = api.pid(child)
    assert office_pid and office_pid != process.pid, 'Editor must belong to the separate native Office engine'
    assert 'OpenGeul ' + module.title() in api.title(hwnd), 'Document title is not OpenGeul branded'
    assert not api.windows(office_pid), api.external_window_message(office_pid, 'Office created an unowned visible top-level window')
    return hwnd, parent, child, office_pid


def capture_native_archive_generation(api, process, attachment, *, probe=None):
    """One metadata-only admission before input/close; synchronous calls cannot be interrupted."""
    from counted_editor_shortcuts import NativeShortcutProbe, _same_image
    assert set(attachment) == {'hwnd','parent','child','officePid'}, 'Exact original attachment is required'
    assert all(type(value) is int and 0 < value < 2**64 for value in attachment.values())
    hwnd, parent, child, office_pid = (attachment[key] for key in ('hwnd','parent','child','officePid'))
    suite = Path(process.opengeul_suite_root)
    assert suite.is_absolute() and type(process.pid) is int and 0 < process.pid < 2**32
    assert office_pid < 2**32 and office_pid != process.pid and int(process._handle) > 0
    assert isinstance(process.args,(list,tuple)) and _same_image(process.args[0],suite/'OpenGeul.Office.exe')
    deadline = time.monotonic() + 5  # Metadata only; no input or save deadline is changed.
    probe = probe if probe is not None else NativeShortcutProbe(deadline,time.monotonic)
    def owned():
        assert all(api.user.IsWindow(value) for value in (hwnd,parent,child)), 'Original attachment window closed'
        assert (api.pid(hwnd),api.pid(parent),api.pid(child)) == (process.pid,process.pid,office_pid), 'Original attachment process changed'
        assert api.user.GetAncestor(hwnd,2) == hwnd and api.user.IsChild(hwnd,parent) and api.user.IsChild(parent,child), 'Original attachment ownership changed'
        assert (int(api.user.GetPropW(hwnd,'OpenGeul.Office.ParentHwnd') or 0),
                int(api.user.GetPropW(hwnd,'OpenGeul.Office.ChildHwnd') or 0)) == (parent,child), 'Original attachment export changed'
    owned()
    shell = probe.process_snapshot(process)
    assert (shell['pid'],shell['handleValue'],shell['waitResult']) == (process.pid,int(process._handle),258), 'Original shell HANDLE changed'
    assert type(shell['creationTime']) is int and 0 < shell['creationTime'] < 2**64
    assert _same_image(shell['image'],suite/'OpenGeul.Office.exe'), 'Original shell image changed'
    handle = probe.open_engine(office_pid)
    primary = None
    try:
        assert type(handle) is int and handle > 0, 'Archive metadata engine HANDLE is invalid'
        engine = probe.engine_snapshot(handle)
        assert (engine['pid'],engine['handleValue'],engine['waitResult']) == (office_pid,handle,258), 'Original archive engine HANDLE changed'
        assert type(engine['creationTime']) is int and shell['creationTime'] <= engine['creationTime'] < 2**64, 'Original archive engine generation changed'
        assert _same_image(engine['image'],suite/'Office/program/soffice.bin'), 'Original archive engine image changed'
        assert probe.engine_snapshot(handle) == engine and probe.process_snapshot(process) == shell, 'Original archive process generation changed'
        owned()
        return {key:engine[key] for key in ('pid','creationTime','image')}
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if type(handle) is int and handle > 0:
            try:
                assert probe.close_engine(handle) is True, 'Native archive generation HANDLE close failed'
            except BaseException:
                if primary is None: raise
                primary.add_note('Native archive generation HANDLE close failed')
        if primary is None:
            assert time.monotonic() <= deadline, 'Archive metadata elapsed bound exceeded'


def base_new_closed(api, process, hwnd, record):
    if not api.user.IsWindow(hwnd): return True
    if record.get('discardPromptHandled'): return False
    from pywinauto import Desktop
    dialogs = [dialog for dialog in api.windows(process.pid)
               if api.title(dialog) == 'OpenGeul Base' and api.user.GetWindow(dialog, 4) == hwnd]
    if not dialogs: return False
    assert len(dialogs) == 1, 'Expected exactly one owned Base close prompt'
    dialog = dialogs[0]
    native = Desktop(backend='win32').window(handle=dialog).wrapper_object()
    require_dialog_identity(api.pid(dialog), process.pid, api.user.GetWindow(dialog, 4), hwnd,
                            api.title(dialog), 'OpenGeul Base', native.class_name())
    accessible = Desktop(backend='uia').window(handle=dialog).wrapper_object()
    assert '변경 내용을 저장하시겠습니까?' in [item.element_info.name for item in accessible.descendants()], 'Base dialog is not the exact save/discard/cancel prompt'
    buttons = [button for button in accessible.descendants(control_type='Button')
               if button.element_info.name == '저장하지 않음' and button.is_visible() and button.is_enabled()]
    assert len(buttons) == 1, 'The exact Base discard button is missing or ambiguous'
    native.set_focus()
    assert api.user.GetAncestor(api.user.GetForegroundWindow(), 2) == dialog, 'Discard requires the owned prompt foreground'
    assert api.pid(dialog) == process.pid and api.title(dialog) == 'OpenGeul Base' and api.user.GetWindow(dialog, 4) == hwnd, 'Discard prompt ownership changed before physical input'
    buttons[0].click_input()  # Explicit physical user action, only for this blank Base document.
    record.update(discardPromptHandled=True, discardDialogHwnd=int(dialog), discardButton='저장하지 않음')
    return not api.user.IsWindow(hwnd)


BASE_SAVE_DIALOG_SECONDS = 20
BASE_SAVE_MAX_OBSERVATIONS = 201
BASE_SAVE_UIA_TYPES = (50004, 50000)  # UIA Edit and Button control types.


def _base_int(value, *, positive=False):
    assert type(value) is int and value >= (1 if positive else 0), 'Invalid native Base integer'
    return value


def _base_time(value):
    assert type(value) in (int, float) and math.isfinite(value) and value >= 0, 'Invalid Base observation time'
    return value


def _base_native_identity(snapshot, shell_pid, document, dialog, caption):
    owner = snapshot['document']
    assert (owner['hwnd'] == document and owner['pid'] == shell_pid and owner['isWindow'] is True
            and owner['rootHwnd'] == document and _base_int(owner['threadId'], positive=True)), 'Foreign or dead Base document'
    if not dialog: return
    native = snapshot['dialog']
    assert (native['hwnd'] == dialog and native['isWindow'] is True and native['pid'] == shell_pid
            and native['rootHwnd'] == dialog and _base_int(native['threadId'], positive=True)), 'Foreign or dead Base save dialog'
    require_dialog_identity(native['pid'], shell_pid, snapshot['ownerHwnd'], document,
                            snapshot['title'], caption, native['className'])
    assert snapshot['visible'] is True, 'Owned Base save dialog disappeared'
    foreground = snapshot['foreground']
    assert (foreground['isWindow'] is True and foreground['pid'] == shell_pid
            and foreground['rootHwnd'] == dialog), 'Foreign Base save foreground'


def _base_native_key(window):
    for key in ('hwnd', 'pid', 'threadId', 'rootHwnd'): _base_int(window[key], positive=True)
    assert type(window['className']) is str and window['className']
    assert window['isWindow'] is True
    return tuple(window[key] for key in ('hwnd','pid','threadId','rootHwnd','className'))


def _base_native_continuity(anchor, observation):
    for edge in ('before','after'):
        assert _base_native_key(observation[edge]['document']) == _base_native_key(anchor['document']), 'Base document native generation changed'
        if observation['dialogMatches']:
            assert _base_native_key(observation[edge]['dialog']) == _base_native_key(anchor['dialog']), 'Base save dialog native thread or window identity changed'


def _base_uia_hwnd(row):
    raw = row['nativeHwndRaw']
    assert raw is None or type(raw) is int, 'Invalid raw UIA pointer value'
    expected = 0 if raw is None else _base_int(raw)
    assert _base_int(row['nativeHwnd']) == expected, 'Raw UIA null/handle normalization changed'
    return expected


def _base_runtime_id(value):
    assert isinstance(value, list) and 1 <= len(value) <= 64 and all(type(n) is int for n in value), 'Missing actual UIA runtime identity'
    return tuple(value)


def _base_save_observation_state(observation, shell_pid, document, caption, frozen_dialog, frozen_root, *, filename_id='1001'):
    assert filename_id in ('1001','1148')
    if filename_id=='1148':assert caption=='OpenGeul Office에서 문서 열기'
    if observation['apiError'] is not None:
        error = observation['apiError']
        raise AssertionError('Base native/UIA API failed: ' + str(error))
    matches = observation['dialogMatches']
    assert isinstance(matches, list) and len(matches) <= 1, 'Owned Base save dialog is ambiguous'
    for edge in ('before', 'after'):
        _base_native_identity(observation[edge], shell_pid, document, frozen_dialog if matches else 0, caption)
    if not matches:
        assert not frozen_dialog, 'Bound Base save dialog disappeared'
        assert observation['queryAttempted'] is False and observation['controls'] == [], 'Unexpected query without an owned dialog'
        return 'pending'
    assert matches == [frozen_dialog] and _base_int(frozen_dialog, positive=True), 'Owned Base save dialog was replaced'
    assert observation['queryAttempted'] is True and observation['querySucceeded'] is True, 'Missing raw Base UIA query'
    assert observation['queryApi'] == 'IUIAutomationElement.FindAll' and observation['treeScope'] == 4, 'Wrong Base UIA query scope'
    root = observation['uiaRoot']
    assert (_base_runtime_id(root['runtimeId']) == tuple(frozen_root) and root['nativeHwnd'] == frozen_dialog
            and root['pid'] == shell_pid and root['controlType'] == 50032), 'Foreign or replaced Base UIA root'
    _base_int(root['pid'],positive=True); _base_int(_base_uia_hwnd(root),positive=True); _base_int(root['controlType'],positive=True)
    assert type(root['enabled']) is bool and type(root['offscreen']) is bool
    controls = observation['controls']
    assert isinstance(controls, list) and _base_int(observation['rawCount']) == len(controls) <= 512, 'Incomplete bounded raw UIA enumeration'
    candidates = {(filename_id, 50004): [], ('1', 50000): []}
    seen = set()
    for index, row in enumerate(controls):
        assert _base_int(row['index']) == index and type(row['controlType']) is int and row['controlType'] in BASE_SAVE_UIA_TYPES, 'Unexpected Base UIA control type or index'
        _base_int(row['pid'], positive=True); _base_uia_hwnd(row)
        identity = _base_runtime_id(row['runtimeId'])
        assert type(row['automationId']) is str and type(row['offscreen']) is bool and type(row['enabled']) is bool, 'Invalid raw Base UIA properties'
        key = (row['automationId'], row['controlType'])
        if key not in candidates: continue
        assert identity not in seen, 'Base controls have duplicate live UIA identities'
        seen.add(identity)
        candidates[key].append(row)
        assert row['pid'] == shell_pid, 'Foreign Base save control process'
        chain = row['ancestry']
        assert isinstance(chain, list) and 2 <= len(chain) <= 32, 'Missing bounded live UIA ancestry'
        chain_ids = []
        for position, node in enumerate(chain):
            chain_ids.append(_base_runtime_id(node['runtimeId']))
            assert node['pid'] == shell_pid and _base_int(node['controlType'], positive=True), 'Foreign UIA control ancestry'
            _base_uia_hwnd(node)
            assert node['equalsDialogRoot'] is (position == len(chain)-1), 'UIA ancestry did not terminate at the owned root'
            if node['controlType'] == 50032:
                assert position == len(chain)-1, 'Foreign nested UIA Window before the owned Base dialog'
            if node['nativeHwnd']:
                native = node['native']
                assert (native['hwnd'] == node['nativeHwnd'] and native['isWindow'] is True
                        and native['pid'] == shell_pid and native['rootHwnd'] == frozen_dialog
                        and node['nativeWithinDialog'] is True), 'Foreign native UIA ancestor'
            else:
                assert node['native'] is None and node['nativeWithinDialog'] is False, 'Invented UIA ancestor HWND'
        assert len(set(chain_ids)) == len(chain_ids) and chain_ids[0] == identity and chain_ids[-1] == tuple(frozen_root), 'Replaced or cyclic UIA ancestry'
        assert chain[-1]['nativeHwnd'] == frozen_dialog and chain[-1]['controlType'] == 50032, 'UIA ancestry ends at a foreign native window'
        if row['nativeHwnd']:
            native = row['native']
            assert (native['hwnd'] == row['nativeHwnd'] and native['isWindow'] is True
                    and native['pid'] == shell_pid and native['rootHwnd'] == frozen_dialog
                    and row['nativeWithinDialog'] is True), 'Foreign native Base control'
        else:
            assert row['native'] is None and row['nativeWithinDialog'] is False, 'Invented HWND for a DirectUI control'
    actual_counts = {'filename':len(candidates[(filename_id,50004)]),'save':len(candidates[('1',50000)])}
    assert observation['candidateCounts'] == actual_counts and all(type(n) is int for n in observation['candidateCounts'].values()) and observation['countsComplete'] is True, 'Invalid raw Base candidate counts'
    assert all(len(rows) <= 1 for rows in candidates.values()), 'Exact Base filename or Save control is ambiguous'
    ready = root['enabled'] and not root['offscreen'] and all(len(rows) == 1 and rows[0]['enabled'] and not rows[0]['offscreen'] for rows in candidates.values())
    return 'ready' if ready else 'pending'


def require_base_save_dialog_readiness(evidence, shell_pid, document_hwnd, caption, *, before_input=False, expected_trigger='owned-save-menu-pointer'):
    """Replay actual native/UIA receipts without loading Windows libraries."""
    _base_int(shell_pid, positive=True); _base_int(document_hwnd, positive=True)
    assert type(before_input) is bool
    assert type(evidence['schemaVersion']) is int and evidence['schemaVersion'] == 1
    assert evidence['kind'] == 'owned-base-save-dialog-readiness'
    assert (evidence['shellPid'], evidence['documentHwnd'], evidence['caption']) == (shell_pid, document_hwnd, caption)
    assert _base_int(evidence['budgetSeconds']) == BASE_SAVE_DIALOG_SECONDS and _base_int(evidence['maxObservations']) == BASE_SAVE_MAX_OBSERVATIONS
    start, deadline, finished = (_base_time(evidence[key]) for key in ('startedAt', 'deadline', 'finishedAt'))
    assert deadline == start + BASE_SAVE_DIALOG_SECONDS and start <= finished <= deadline, 'Base readiness exceeded its original deadline'
    assert expected_trigger in ('legacy-shortcut','owned-save-menu-pointer')
    assert _base_int(evidence['fileMenuClicks']) == 1 and evidence['ready'] is True, 'Original Base inputs or readiness changed'
    if expected_trigger=='owned-save-menu-pointer':
        assert evidence['trigger']==expected_trigger and _base_int(evidence['saveShortcuts'])==0 and _base_int(evidence['saveMenuClicks'])==1, 'Base pointer trigger/counts differ'
    else:
        assert evidence.get('trigger','legacy-shortcut')==expected_trigger and _base_int(evidence['saveShortcuts'])==1 and _base_int(evidence.get('saveMenuClicks',0))==0, 'Legacy Base shortcut trigger/counts differ'
        assert 'saveMenuAction' not in evidence, 'Legacy shortcut proof contains a pointer action'
    focus = evidence['focusAction']
    dialog = _base_int(evidence['dialogHwnd'], positive=True)
    root = _base_runtime_id(evidence['uiaRootRuntimeId'])
    assert focus['dialogHwnd'] == dialog and _base_int(focus['count']) == 1 and start <= _base_time(focus['at']) <= finished, 'Base dialog focus was retried or reordered'
    observations = evidence['observations']
    assert isinstance(observations, list) and 1 <= len(observations) <= BASE_SAVE_MAX_OBSERVATIONS
    previous, bound = start, False
    for index, observation in enumerate(observations):
        began, ended = (_base_time(observation[key]) for key in ('startedAt', 'finishedAt'))
        assert previous <= began <= ended <= finished and _base_int(observation['sequence']) == index, 'Invalid Base observation order'
        previous = ended
        assert observation['shellProcessPoll'] == {'pid':shell_pid,'exitCode':None}, 'Original retained Suite process exited'
        _base_native_continuity(evidence['nativeAnchor'],observation)
        matches = observation['dialogMatches']
        if matches:
            bound = True
            assert focus['at'] <= began, 'Base controls queried before the single native focus action'
        state = _base_save_observation_state(observation, shell_pid, document_hwnd, caption, dialog if bound else 0, root)
        assert observation['state'] == state and (state == 'ready') is (index == len(observations)-1), 'Base readiness did not stop at the first strict ready snapshot'
    rows = observations[-1]['controls']
    bindings = evidence['wrapperBindings']
    assert len(bindings) == 2
    for binding, key in zip(bindings, (('1001', 50004), ('1', 50000))):
        row = rows[_base_int(binding['sourceIndex'])]
        assert (row['automationId'], row['controlType']) == key and binding['rawElementEquals'] is True, 'Wrapper did not retain the actual queried Base control'
        assert binding['properties'] == {name: row[name] for name in binding['properties']} and set(binding['properties']) == {'runtimeId','automationId','controlType','pid','nativeHwnd','nativeHwndRaw','enabled','offscreen'}, 'Wrapper identity changed before input'
    assert evidence['bindingError'] is None, 'Raw Base wrapper binding failed'
    if not before_input or 'filenameInputStartedAt' in evidence:
        assert _base_time(evidence['filenameInputStartedAt']) >= finished, 'Filename input preceded exact Base readiness'
    if expected_trigger=='owned-save-menu-pointer':
        require_save_menu_action(evidence['saveMenuAction'],shell_pid,document_hwnd,caption,evidence)
    return evidence


def _base_native_snapshot(api, document, dialog):
    return {'document': api._focus_window(document), 'dialog': api._focus_window(dialog) if dialog else None,
            'ownerHwnd': int(api.user.GetWindow(dialog, 4) or 0) if dialog else 0,
            'title': api.title(dialog) if dialog else '', 'visible': bool(api.user.IsWindowVisible(dialog)) if dialog else False,
            'foreground': api._focus_window(api.user.GetForegroundWindow())}


def _base_api_error(operation, exc):
    raw = getattr(exc, 'hresult', None)
    arguments = list(exc.args)
    try: json.dumps(arguments,allow_nan=False)
    except (TypeError,ValueError): arguments = [repr(argument) for argument in exc.args]
    return {'operation': operation, 'type': type(exc).__name__, 'message': str(exc),
            'hresult': int(raw) if raw is not None else None, 'arguments':arguments}


def _base_raw_properties(element, call, result=None):
    if result is None: result = {}
    for target, source, convert in (('automationId','CurrentAutomationId',str), ('controlType','CurrentControlType',int),
            ('pid','CurrentProcessId',int), ('nativeHwnd','CurrentNativeWindowHandle',int),
            ('enabled','CurrentIsEnabled',bool), ('offscreen','CurrentIsOffscreen',bool)):
        value = call(source, lambda source=source: getattr(element, source))
        if target == 'nativeHwnd':
            # UIA_HWND is void*: successful ctypes NULL out parameters are None.
            result['nativeHwndRaw'] = value
            if value is not None and type(value) is not int:
                raise TypeError('UIA_HWND must be an actual integer or successful null pointer')
            result[target] = 0 if value is None else _base_int(value)
        else:
            result[target] = convert(value)
    result['runtimeId'] = list(call('GetRuntimeId', element.GetRuntimeId))
    return result


def _base_raw_controls(api, accessible, uia, dialog, observation, *, filename_id='1001'):
    """Do not use descendants/elements_from_uia_array: both swallow COM errors."""
    assert filename_id in ('1001','1148')
    last = 'UIA root'
    def call(operation, function):
        nonlocal last
        last = operation
        return function()
    elements = []
    try:
        root = accessible.element_info._element
        observation['uiaRoot'] = {}
        _base_raw_properties(root, call, observation['uiaRoot'])
        condition = call('CreateOrCondition', lambda: uia.iuia.CreateOrCondition(
            uia.build_condition(control_type='Edit'), uia.build_condition(control_type='Button')))
        observation.update(queryAttempted=True, queryApi='IUIAutomationElement.FindAll', treeScope=4)
        found = call('IUIAutomationElement.FindAll', lambda: root.FindAll(uia.tree_scope['descendants'], condition))
        count = int(call('IUIAutomationElementArray.Length', lambda: found.Length))
        observation['rawCount'] = count
        assert 0 <= count <= 512, 'Base UIA enumeration exceeded its finite element limit'
        for index in range(count):
            element = call('IUIAutomationElementArray.GetElement', lambda: found.GetElement(index))
            row = {'index': index}
            observation['controls'].append(row)
            _base_raw_properties(element, call, row)
            elements.append(element)
            if (row['automationId'], row['controlType']) in ((filename_id,50004),('1',50000)):
                row['ancestry'], cursor = [], element
                for _ in range(32):
                    node = _base_raw_properties(cursor, call)
                    node = {name: node[name] for name in ('runtimeId','pid','nativeHwnd','nativeHwndRaw','controlType')}
                    node['equalsDialogRoot'] = bool(call('IUIAutomation.CompareElements', lambda: uia.iuia.CompareElements(cursor,root)))
                    node['native'] = api._focus_window(node['nativeHwnd']) if node['nativeHwnd'] else None
                    node['nativeWithinDialog'] = bool(node['nativeHwnd'] and
                        (node['nativeHwnd'] == dialog or api.user.IsChild(dialog,node['nativeHwnd'])))
                    row['ancestry'].append(node)
                    if node['equalsDialogRoot']: break
                    cursor = call('ControlViewWalker.GetParentElement', lambda: uia.iuia.ControlViewWalker.GetParentElement(cursor))
                    assert cursor, 'Base UIA ancestry ended before the owned dialog'
                else: raise AssertionError('Base UIA ancestry exceeded its finite depth')
                row['native'] = api._focus_window(row['nativeHwnd']) if row['nativeHwnd'] else None
                row['nativeWithinDialog'] = bool(row['nativeHwnd'] and api.user.IsChild(dialog, row['nativeHwnd']))
        observation['querySucceeded'] = True
    except Exception as exc:
        observation['apiError'] = _base_api_error(last, exc)
    finally:
        if 'rawCount' in observation:
            observation['candidateCounts'] = {name:sum((row.get('automationId'),row.get('controlType')) == key for row in observation['controls'])
                for name,key in (('filename',(filename_id,50004)),('save',('1',50000)))}
            observation['countsComplete'] = observation['querySucceeded']
    return elements


def _wait_base_save_controls(api, process, document, caption, record, *, open_dialog=False, expected_trigger='owned-save-menu-pointer', save_menu_action=None):
    start = time.monotonic()
    assert expected_trigger in ('legacy-shortcut','owned-save-menu-pointer')
    filename_id='1148' if open_dialog else '1001'
    from pywinauto import Desktop
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo
    from pywinauto.controls.uiawrapper import UIAWrapper
    proof = {'schemaVersion':1, 'kind':'owned-base-save-dialog-readiness', 'shellPid':process.pid,
             'documentHwnd':document, 'caption':caption, 'budgetSeconds':BASE_SAVE_DIALOG_SECONDS,
             'maxObservations':BASE_SAVE_MAX_OBSERVATIONS, 'startedAt':start, 'deadline':start+BASE_SAVE_DIALOG_SECONDS,
             'finishedAt':start, 'fileMenuClicks':1, 'saveShortcuts':1, 'focusAction':None,
             'dialogHwnd':0, 'uiaRootRuntimeId':[], 'nativeAnchor':{}, 'observations':[], 'wrapperBindings':[], 'bindingError':None, 'ready':False}
    if open_dialog:
        assert caption == 'OpenGeul Office에서 문서 열기'
        proof.pop('fileMenuClicks');proof.pop('saveShortcuts')
        proof.update(kind='owned-open-dialog-readiness',trigger=dict(record['openTrigger']),filenameAutomationId=filename_id)
        record['openDialogReadiness'] = proof
    else:
        if expected_trigger=='owned-save-menu-pointer':
            proof.update(trigger=expected_trigger,saveShortcuts=0,saveMenuClicks=1,
                         saveMenuAction=detached_save_menu_action(save_menu_action))
        record['baseSaveDialogReadiness'] = proof
    dialog, native, accessible, uia = 0, None, None, None
    try:
        for sequence in range(BASE_SAVE_MAX_OBSERVATIONS):
            assert time.monotonic() < proof['deadline'], 'Base save dialog readiness deadline expired'
            observation = {'sequence':sequence, 'startedAt':time.monotonic(), 'dialogMatches':[],
                           'queryAttempted':False, 'querySucceeded':False, 'controls':[], 'apiError':None, 'state':'observing'}
            proof['observations'].append(observation)
            operation = 'EnumWindows/owned Base dialog identity'
            try:
                observation['shellProcessPoll'] = {'pid':process.pid,'exitCode':process.poll()}
                assert observation['shellProcessPoll']['exitCode'] is None, 'Original retained Suite process exited'
                matches = [handle for handle in api.windows(process.pid) if api.title(handle) == caption]
                observation['dialogMatches'] = matches
                assert len(matches) <= 1, 'Owned Base save dialog is ambiguous'
                observed = matches[0] if matches else 0
                if dialog: assert observed == dialog, 'Bound Base save dialog disappeared or was replaced'
                if observed and not dialog:
                    dialog = observed
                    # Verify native owner/class BEFORE the one existing focus action.
                    require_dialog_identity(api.pid(dialog), process.pid, api.user.GetWindow(dialog,4), document,
                                            api.title(dialog), caption, api.class_name(dialog))
                    operation = 'native dialog wrapper/focus'
                    native = Desktop(backend='win32').window(handle=dialog).wrapper_object()
                    native.set_focus()
                    api.require_foreground(dialog)
                    proof['dialogHwnd'] = dialog
                    proof['focusAction'] = {'dialogHwnd':dialog, 'count':1, 'at':time.monotonic()}
                    # Observation timing starts after that single setup action.
                    observation['startedAt'] = time.monotonic()
                    operation = 'UIA ElementFromHandle/wrapper'
                    accessible = Desktop(backend='uia').window(handle=dialog).wrapper_object()
                    uia = IUIA()
                observation['before'] = _base_native_snapshot(api, document, observed)
                _base_native_identity(observation['before'], process.pid, document, observed, caption)
                if 'document' not in proof['nativeAnchor']: proof['nativeAnchor']['document'] = observation['before']['document']
                if observed and 'dialog' not in proof['nativeAnchor']: proof['nativeAnchor']['dialog'] = observation['before']['dialog']
                if observed:
                    elements = _base_raw_controls(api, accessible, uia, dialog, observation, filename_id=filename_id)
                    if not proof['uiaRootRuntimeId'] and observation.get('uiaRoot'):
                        proof['uiaRootRuntimeId'] = observation['uiaRoot']['runtimeId']
            except Exception as exc:
                if observation['apiError'] is None: observation['apiError'] = _base_api_error(operation, exc)
            finally:
                try: observation['after'] = _base_native_snapshot(api, document, dialog)
                except Exception as exc:
                    observation.setdefault('secondaryErrors',[]).append(_base_api_error('native after snapshot',exc))
                    if observation['apiError'] is None: observation['apiError'] = _base_api_error('native after snapshot',exc)
                observation['finishedAt'] = time.monotonic()
            if observation['apiError'] is None: _base_native_continuity(proof['nativeAnchor'],observation)
            state = _base_save_observation_state(observation, process.pid, document, caption, dialog, proof['uiaRootRuntimeId'], filename_id=filename_id)
            observation['state'] = state
            assert observation['finishedAt'] <= proof['deadline'], 'Base save dialog readiness deadline expired during observation'
            if state == 'ready':
                wrappers=[]
                binding_operation = 'UIA wrapper construction'
                def binding_call(operation, function):
                    nonlocal binding_operation
                    binding_operation = operation
                    return function()
                try:
                    for key in ((filename_id,50004), ('1',50000)):
                        row = next(row for row in observation['controls'] if (row['automationId'],row['controlType']) == key)
                        element = elements[row['index']]
                        wrapper = binding_call('UIAWrapper(UIAElementInfo)', lambda:UIAWrapper(UIAElementInfo(element)))
                        binding = {'sourceIndex':row['index'], 'properties':{}}
                        proof['wrapperBindings'].append(binding)
                        _base_raw_properties(wrapper.element_info._element, binding_call, binding['properties'])
                        binding['rawElementEquals'] = bool(binding_call('IUIAutomation.CompareElements wrapper',
                            lambda:uia.iuia.CompareElements(wrapper.element_info._element,element)))
                        wrappers.append(wrapper)
                except Exception as exc:
                    proof['bindingError'] = _base_api_error(binding_operation,exc)
                    raise
                proof.update(ready=True, finishedAt=time.monotonic())
                if open_dialog:
                    from home_routing_smoke import require_open_dialog_readiness
                    require_open_dialog_readiness(proof, process.pid, document, before_input=True)
                else:require_base_save_dialog_readiness(proof, process.pid, document, caption, before_input=True, expected_trigger=expected_trigger)
                return dialog, native, wrappers[0], wrappers[1]
            time.sleep(min(0.1, max(0,proof['deadline']-time.monotonic())))
        raise AssertionError('Base save readiness deadline or finite observation limit expired')
    except Exception as exc:
        if proof['observations'] and proof['observations'][-1]['state'] == 'observing':
            proof['observations'][-1]['state'] = 'failed'
        proof.update(ready=False, failure=type(exc).__name__+': '+str(exc))
        raise
    finally:
        if not proof['ready']: proof['finishedAt'] = time.monotonic()


def save_new_base(api, process, hwnd, fixtures, output, record):
    from pywinauto import Desktop
    import lifecycle_smoke as lifecycle
    target = new_base_target(fixtures)
    caption = 'OpenGeul Base — 다른 이름으로 저장'
    record['newBaseSaveAsVerified'] = False
    record.update(newBaseSaveMenuActionVerified=False, saveShortcutViaOwnedMenu=False)
    record['stage'] = 'focus-save-menu'
    api.require_foreground(hwnd)
    shell = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
    menus = [item for item in shell.descendants(control_type='MenuItem')
             if item.element_info.name == '파일' and item.element_info.process_id == process.pid
             and item.is_visible() and item.is_enabled()]
    assert len(menus) == 1, 'The exact shell-owned File menu is required for the Save shortcut'
    click_owned_control(api, process, hwnd, menus[0], record, purpose='FILE_MENU')
    record['stage'] = 'click-owned-base-save-menu'
    trigger = click_owned_control(api, process, hwnd, menus[0], record, purpose='SAVE_MENU', caption=caption)
    record['baseSaveMenuAction'] = trigger

    record['stage'] = 'wait-save-dialog'
    dialog, native, filename, save_button = _wait_base_save_controls(api, process, hwnd, caption, record, expected_trigger='owned-save-menu-pointer', save_menu_action=trigger)
    api.require_foreground(dialog)
    require_dialog_identity(api.pid(dialog), process.pid, api.user.GetWindow(dialog, 4), hwnd,
                            api.title(dialog), caption, native.class_name())
    require_base_save_dialog_readiness(record['baseSaveDialogReadiness'], process.pid, hwnd, caption, before_input=True, expected_trigger='owned-save-menu-pointer')
    require_save_menu_action(trigger, process.pid, hwnd, caption, record['baseSaveDialogReadiness'])
    record['newBaseSaveMenuActionVerified'] = True
    require_base_save_menu_record(record,process.pid,hwnd,before_input=True)
    record['stage'] = 'type-save-path'
    record['baseSaveDialogReadiness']['filenameInputStartedAt'] = time.monotonic()
    accessible = Desktop(backend='uia').window(handle=dialog).wrapper_object()
    lifecycle.set_owned_picker_filename(api, process.pid, hwnd, dialog, accessible, filename, str(target),
                                       record, expected_title=caption)
    assert filename.iface_value.CurrentValue == str(target), 'Save As filename differs from the fresh owned target'
    native.capture_as_image().save(output / 'new-base-save-as.png')
    require_dialog_identity(api.pid(dialog), process.pid, api.user.GetWindow(dialog, 4), hwnd,
                            api.title(dialog), caption, native.class_name())
    api.require_foreground(dialog)
    assert not target.exists(), 'Save As target appeared before the verified Save click'
    record['stage'] = 'click-save'
    click_owned_control(api, process, hwnd, save_button, record, purpose='SAVE_BUTTON', dialog=dialog,
                        caption=caption, readiness=record['baseSaveDialogReadiness'])
    record['stage'] = 'wait-save-dialog-close'
    wait_for(lambda: not api.user.IsWindow(dialog), seconds=20)
    record['stage'] = 'validate-saved-base'
    evidence = wait_for(lambda: saved_base_evidence(target), seconds=30)
    wait_for(lambda: not api.title(hwnd).startswith('* '), seconds=10)
    record.update(saveAsDialogVerified=True, saveAsDialogHwnd=int(dialog), saveAsFilenameAutomationId='1001',
                  saveAsButtonAutomationId='1', saveShortcutViaOwnedMenu=False,
                  savedFile=target.name, beforeCleanupSha256=evidence['sha256'])
    return target


def require_base_save_menu_record(record, shell_pid, hwnd, *, before_input=False):
    """Join bounded readiness embedding to the original separately retained action."""
    caption='OpenGeul Base — 다른 이름으로 저장'
    proof=record['baseSaveDialogReadiness'];action=record['baseSaveMenuAction']
    assert record['newBaseSaveMenuActionVerified'] is True and record.get('saveShortcutViaOwnedMenu') is False
    assert proof['saveMenuAction']==action
    assert [row for row in record['ownedControlActions'] if row['purpose']=='SAVE_MENU']==[action]
    from owned_save_menu import file_click_anchor
    assert action['saveMenuFileAnchor']==file_click_anchor(record,hwnd,action['originalProcess'],action['startedAt'])
    require_base_save_dialog_readiness(proof,shell_pid,hwnd,caption,before_input=before_input,expected_trigger='owned-save-menu-pointer')
    require_save_menu_action(action,shell_pid,hwnd,caption,proof)
    return action


def new_module(suite, output, module, *, fixtures=None):
    from pywinauto import Desktop
    name = 'new-' + module
    process = launch_suite(new_document_command(suite, module), suite, output, name)
    api = Windows()
    record = {'module': module, 'kind': 'new-document', 'shellPid': process.pid, 'success': False,
              'keyboardInputVerified': False, 'contentMutationVerified': False, 'imeVerified': False,
              'discardPromptHandled': False, 'stage': 'attach', 'stderrLog': name + '-stderr.log'}
    try:
        hwnd, parent, child, office_pid = verified_attachment(api, process, module)
        record['nativeArchiveGeneration'] = capture_native_archive_generation(api,process,
            dict(hwnd=hwnd,parent=parent,child=child,officePid=office_pid))
        record['stage'] = 'prepare-window'
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        activate_owned_suite(api, process, hwnd, record)
        wait_for(lambda: api.user.GetAncestor(api.user.GetForegroundWindow(), 2) == hwnd, 10)
        screenshot = name + '-attached.png'
        record['stage'] = 'capture-attached'
        window.capture_as_image().save(output / screenshot)
        assert not api.windows(office_pid), api.external_window_message(office_pid, 'New document opened an unowned visible Office window')
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=office_pid,
                      title=api.title(hwnd), screenshot=screenshot, nativeParentVerified=True,
                      noExternalOfficeWindow=True)
        saved_base = None
        if module == 'base':
            assert fixtures is not None, 'New Base Save As requires owned generated fixtures'
            saved_base = save_new_base(api, process, hwnd, fixtures, output, record)
            record['stage'] = 'capture-saved-base'
            window.capture_as_image().save(output / 'new-base-saved.png')
        # A Save As failure never falls back to discarding the unsaved Base document.
        calc_proof = None
        if module == 'calc':
            from generated_calc_close import freeze_generated_blank_calc
            calc_proof = freeze_generated_blank_calc(suite, api, process, hwnd, child, record)
            close_document(api, process, hwnd, child, record, calc_close_proof=calc_proof)
        else:
            close_document(api, process, hwnd, child, record)
        close_home(api, process, record)
        if saved_base is not None:
            record['stage'] = 'verify-base-after-cleanup'
            final = saved_base_evidence(saved_base)
            assert not record['discardPromptHandled'], 'Saved Base must close normally without discard'
            record.update(newBaseSaveAsVerified=True, savedFileSurvivedCleanup=True,
                          savedFileSha256=final['sha256'], savedFileBytes=final['bytes'],
                          savedDatabaseUrl=final['connection'])
            require_base_save_menu_record(record,process.pid,hwnd)
        record.update(success=True, cleanClose=True, newDocumentVerified=True, stage='complete')
        return record
    except Exception as exc:
        capture_failure(output, name, record, exc)
        raise
    finally:
        stop_owned_test_process(process, record)
        write_result(output, name, record)


def capture_home(suite, output):
    from pywinauto import Desktop
    process = launch_suite([str(suite / 'OpenGeul.Office.exe')], suite, output, 'home')
    api = Windows()
    record = {'kind': 'home', 'shellPid': process.pid, 'success': False, 'keyboardInputVerified': False,
              'stage': 'find-home', 'stderrLog': 'home-stderr.log'}
    try:
        hwnd = wait_for(lambda: api.home(process), seconds=30)
        assert api.windows(process.pid) == [hwnd], 'No-argument startup opened an unexpected document or dialog'
        assert not api.user.GetPropW(hwnd, 'OpenGeul.Office.ChildHwnd'), 'Home must not contain an editor frame'
        record['stage'] = 'prepare-home'
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        activate_owned_suite(api, process, hwnd, record)
        record['stage'] = 'verify-home-labels'
        home_uia = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
        labels = require_home_labels([button.element_info.name for button in home_uia.descendants(control_type='Button')])
        record['stage'] = 'capture-home'
        window.capture_as_image().save(output / 'home.png')
        record.update(windowHwnd=int(hwnd), title=api.title(hwnd), moduleLabels=labels, screenshot='home.png')
        close_home(api, process, record)
        record.update(success=True, cleanClose=True, stage='complete')
        return record
    except Exception as exc:
        capture_failure(output, 'home', record, exc)
        raise
    finally:
        stop_owned_test_process(process, record)
        write_result(output, 'home', record)


class CalcModelContext:
    """One original Calc edit; no observer survives into the original Ctrl+S."""
    def __init__(self, suite, source, output, process, attachment, record, baseline):
        self.suite,self.source,self.output,self.process=suite,source,output,process
        self.attachment,self.record,self.baseline=dict(attachment),record,dict(baseline)
        self.expected_url=source.resolve().as_uri()
        self.reader=self.plan=self.receipt=None
        self.failed=False

    def begin(self, marker):
        from lifecycle_smoke import retained_writer_shell
        from writer_model_reader import OwnedModelReader
        from writer_style_smoke import _packaged_identity_file
        assert self.reader is None and self.receipt is None and not self.failed,'Calc edit cannot restart'
        started=time.monotonic();self.deadline=started+calc_model_barrier.MAX_SECONDS
        self.receipt=dict(schemaVersion=1,kind='calc-model-completion',success=False,startedAt=started,
            deadline=self.deadline,originalPhysicalAsciiLossCauseEstablished=False,productFixEstablished=False)
        self.record['calcModelCompletion']=self.receipt
        try:
            self.receipt['originalShell']={}
            creation=retained_writer_shell(self.process,self.suite,self.receipt['originalShell'])
            identity_file,data=_packaged_identity_file(self.suite,'suite-inventory.json')
            self.inventory,self.inventory_sha256=json.loads(data),identity_file['sha256']
            self.destination=self.output/'calc-model-reader'
            self.receipt['readerOutput']=str(self.destination)
            a=self.attachment
            self.reader=OwnedModelReader(self.suite,self.destination,expected_service=calc_model_barrier.SERVICE,
                getter_contract=calc_model_barrier.GETTERS,shell_pid=self.process.pid,expected_shell_creation=creation,
                suite_hwnd=a['hwnd'],parent_hwnd=a['parent'],child_hwnd=a['child'],office_pid=a['officePid'],expected_url=self.expected_url)
            before=self.reader.start(self.deadline);self.receipt['beforeInput']=before
            self.plan=calc_model_barrier.freeze_expectation(before['bindingBefore'],self.baseline,marker,before,
                suite_root=self.suite,original_shell=self.receipt['originalShell'],inventory=self.inventory,
                inventory_sha256=self.inventory_sha256,expected_url=self.expected_url,started_at=started)
            self.receipt['expectation']=self.plan.receipt()
            return self.plan
        except BaseException as exc:
            self.abort(exc);raise

    def complete(self, plan):
        assert plan is self.plan and not self.failed and self.reader is not None
        try:
            calc_model_barrier.await_completion(plan,self.reader.read,clock=time.monotonic,pause=time.sleep,record=self.receipt)
            try:cleanup=self.reader.close(self.deadline)
            finally:self.reader=None
            calc_model_barrier.finalize_completion(plan,self.receipt,cleanup,time.monotonic())
            self.record['calcModelCompletionReplay']=calc_model_barrier.replay_completion(self.receipt,
                suite_root=self.suite,inventory=self.inventory,inventory_sha256=self.inventory_sha256,
                binding=plan.binding,baseline=self.baseline,expected_url=self.expected_url,marker=plan.marker)
            self.record['calcModelCompletionVerified']=True
            self.persist()
        except BaseException as exc:
            self.abort(exc);raise

    def persist(self):
        if self.receipt is not None and getattr(self,'destination',None) is not None and self.destination.is_dir():
            (self.destination/'completion.json').write_text(json.dumps(self.receipt,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

    def abort(self, exc):
        if self.reader is None and self.receipt is not None and self.receipt.get('state')=='complete':
            return  # A later original save/close failure cannot erase sealed model evidence.
        self.failed=True
        if self.receipt is not None:
            self.receipt.update(success=False,state='failed')
            self.receipt.setdefault('error',type(exc).__name__+': '+str(exc))
            self.receipt.setdefault('traceback',traceback.format_exc())
        if self.reader is not None:
            try:self.receipt['cleanup']=self.reader.close(self.deadline)
            except BaseException as later:self.receipt.setdefault('cleanupErrors',[]).append(type(later).__name__+': '+str(later))
            finally:self.reader=None
        try:self.persist()
        except BaseException as later:
            if self.receipt is not None:self.receipt.setdefault('evidenceWriteErrors',[]).append(type(later).__name__+': '+str(later))


def prepare_ascii_cohort(suite, output):
    """Validate inventory and prepare once, before any physical-input case."""
    from writer_style_smoke import _packaged_identity_file
    from native_suite_architecture import require_architecture
    identity, raw = _packaged_identity_file(suite, 'suite-inventory.json')
    inventory = json.loads(raw)
    assert type(inventory.get('schemaVersion')) is int and inventory['schemaVersion'] == 1, 'Invalid Suite inventory'
    architecture = require_architecture(inventory.get('architecture'))
    return ascii_input.prepare_observer(output / 'ascii-message-observer', architecture=architecture)


def document_case(suite, fixtures, output, module, extension, physical_input, *, prepared_library=None):
    from pywinauto import Desktop
    assert (module, extension) in (INPUT_CASES if physical_input else ATTACH_CASES), 'Module is not eligible for this test mode'
    assert not physical_input or prepared_library is not None, 'Physical ASCII cohort must be prepared before launch'
    source = require_engine_fixture(fixtures, module, extension)
    if physical_input:
        assert 'Engine-OpenGeul-' + module in package_text(source), 'Generated source marker is missing'
        assert 'UI-OpenGeul-' + module not in package_text(source), 'UI marker must be absent before actual input'
    source_bytes=source.read_bytes()
    before = hashlib.sha256(source_bytes).hexdigest()
    calc_baseline=None
    if physical_input and module=='calc':
        calc_baseline=calc_model_barrier.baseline_from_ooxml(source_bytes)
        with (output/'calc-model-baseline.xlsx').open('xb') as captured:captured.write(source_bytes)
    process = launch_suite([str(suite/'OpenGeul.Office.exe'), '--module', module, '--file', str(source)],
                           suite, output, module)
    api = Windows()
    record = {'module': module, 'kind': 'keyboard-edit' if physical_input else 'native-attach',
              'shellPid': process.pid, 'file': source.name, 'success': False,
              'keyboardInputVerified': False, 'contentMutationVerified': False, 'imeVerified': False,
              'stage': 'attach', 'stderrLog': module + '-stderr.log', 'beforeSha256':before}
    if calc_baseline is not None:record['calcModelBaseline']=dict(calc_baseline)
    calc_context=None
    calc_context_completed=False
    try:
        hwnd, parent, child, office_pid = verified_attachment(api, process, module)
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=office_pid, title=api.title(hwnd))
        if not physical_input:
            record['nativeArchiveGeneration'] = capture_native_archive_generation(api,process,
                dict(hwnd=hwnd,parent=parent,child=child,officePid=office_pid))
        record['stage'] = 'prepare-window'
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        activate_owned_suite(api, process, hwnd, record)
        wait_for(lambda: api.user.GetAncestor(api.user.GetForegroundWindow(), 2) == hwnd, 10)
        screenshot = module + ('-before.png' if physical_input else '-attached.png')
        record['stage'] = 'capture-attached'
        window.capture_as_image().save(output / screenshot)
        if physical_input:
            marker = EDITOR_MARKERS[module]
            entry_deadline=time.monotonic()+5
            with FirstAdmissionEditorSession(api,process,
                    dict(hwnd=hwnd,parent=parent,child=child,officePid=office_pid),
                    'GUI_'+module.upper(),record,entry_deadline,marker=marker) as shortcuts:
                record['stage'] = 'focus-editor'
                api.require_foreground(hwnd)
                prepare_editor_focus(api, hwnd, child, process.pid, office_pid, record,
                    lambda: click_owned_editor(api,process,hwnd,parent,child,office_pid,record),
                    lambda: shortcuts.press('CTRL_F6'), seconds=entry_deadline-time.monotonic())
                shortcuts.editor_ready(record['editorFocusReadiness'])
                calc_plan=None
                if module=='calc':
                    record['stage']='begin-calc-model-observation'
                    calc_context=CalcModelContext(suite,source,output,process,
                        dict(hwnd=hwnd,parent=parent,child=child,officePid=office_pid),record,calc_baseline)
                    calc_plan=calc_context.begin(marker)
                    shortcuts.join_model(calc_context,calc_plan)
                record['stage'] = 'navigate-editor'
                navigation={'writer':('CTRL_END',),'calc':('CTRL_HOME','F2','CTRL_END'),
                            'impress':('TAB','F2','CTRL_END')}[module]
                for shortcut in navigation: shortcuts.press(shortcut)
                focus = shortcuts.pre_ascii_focus()
                record['stage'] = 'type-marker'
                typed=ascii_input.type_ascii(api, hwnd, child, marker, record, pause=0.04,deadline=shortcuts.deadline,
                    original_popen=process,native_binding=shortcuts.binding,prepared_library=prepared_library)
                shortcuts.typed(typed)
                if module == 'calc': shortcuts.press('ENTER')
                api.require_editor_focus(hwnd, child)
                if module=='calc':
                    record['stage']='complete-calc-model-observation'
                    shortcuts.complete_model(calc_context,calc_plan)
                    calc_context_completed=True
                record['stage'] = 'save-keyboard'
                save_deadline=time.monotonic()+30
                shortcuts.save_phase(save_deadline);shortcuts.press('CTRL_S')
            record['stage'] = 'wait-saved-marker'
            wait_saved_marker(source,marker,before,save_deadline,record)
            wait_for(lambda: not api.title(hwnd).startswith('* '), seconds=10)
            record['stage'] = 'capture-edited'
            window.capture_as_image().save(output / (module + '-edited.png'))
            record.update(keyboardMarker=marker, keyboardFocusHwnd=focus,
                          keyboardInputVerified=True, contentMutationVerified=True)
        assert not api.windows(office_pid), api.external_window_message(office_pid, 'Office created an unowned visible top-level window during the test')
        record.update(nativeParentVerified=True, noExternalOfficeWindow=True, screenshot=screenshot)
        calc_proof = None
        if module == 'calc':
            calc_proof = _verified_saved_calc_close_proof(suite, fixtures, source, calc_baseline,
                                                         suffix=EDITOR_MARKERS[module])
            close_document(api, process, hwnd, child, record, calc_close_proof=calc_proof)
        else:
            close_document(api, process, hwnd, child, record)
        close_home(api, process, record)
        record['stage'] = 'verify-final-content'
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        if physical_input:
            assert marker in package_text(source), 'Physical input marker disappeared after close'
            content_status = {'fixtureUnchanged': after == before}
        else:
            content_status = attach_only_content_status(module, before, after)
        record.update(success=True, cleanClose=True, beforeSha256=before, afterSha256=after, stage='complete',
                      **content_status)
        return record
    except Exception as exc:
        if calc_context is not None and not calc_context_completed:
            try:calc_context.abort(exc)
            except BaseException as later:record.setdefault('calcModelAbortErrors',[]).append(type(later).__name__+': '+str(later))
        capture_failure(output, module, record, exc)
        raise
    finally:
        stop_owned_test_process(process, record)
        write_result(output, module, record)


def edit_module(suite, fixtures, output, module, extension, *, prepared_library):
    return document_case(suite, fixtures, output, module, extension, physical_input=True,prepared_library=prepared_library)


def attach_module(suite, fixtures, output, module, extension):
    return document_case(suite, fixtures, output, module, extension, physical_input=False)


def collect_cases(cases, output):
    results = []
    for name, run in cases:
        try:
            record = dict(run())
        except Exception as exc:
            record = {}
            saved = output / (name + '-result.json')
            if saved.is_file() and not saved.is_symlink():
                try:
                    record = json.loads(saved.read_text(encoding='utf-8'))
                    if not isinstance(record, dict): raise ValueError('Case record must be an object')
                except Exception as read_error:
                    record = {'recordReadError': type(read_error).__name__ + ': ' + str(read_error)}
            try:
                if numeric_notice.notices_enabled():
                    record.setdefault('numericFailure', numeric_notice.capture_failure_code(exc))
            except Exception: pass
            record.update(success=False, caseException=type(exc).__name__ + ': ' + str(exc),
                          caseTraceback=''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            record.setdefault('error', record['caseException'])
        record['case'] = name
        record.setdefault('stage', 'case-setup')
        if (output / (name + '-stderr.log')).is_file(): record.setdefault('stderrLog', name + '-stderr.log')
        if record.get('success') is not True:
            record['success'] = False
            record.setdefault('error', 'Case did not report success')
        try:
            write_result(output, name, record)
        except Exception as exc:
            record.update(success=False, recordWriteError=type(exc).__name__ + ': ' + str(exc))
        results.append(record)
        print(name + ': ' + ('passed' if record['success'] else 'FAILED: ' + record.get('error', 'Evidence write failed')), flush=True)
    return results


def suite_report(results):
    expected = ('home',) + NEW_MODULES + tuple('new-' + module for module in NEW_MODULES)
    counts = Counter(record['case'] for record in results)
    missing = [name for name in expected if name not in counts]
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    unexpected = sorted(set(counts) - set(expected))
    passed = {record['case']: record for record in results if record.get('success') is True}
    failed = [record['case'] for record in results if record.get('success') is not True]
    success = not missing and not duplicates and not unexpected and not failed
    report = {'success': success, 'imeVerified': False, 'tests': results,
              'expectedCaseCount': len(expected), 'completedCaseCount': len(results),
              'passedCaseCount': sum(record.get('success') is True for record in results),
              'failedCases': failed, 'missingCases': missing, 'duplicateCases': duplicates,
              'unexpectedCases': unexpected, 'homeVerified': 'home' in passed,
              'nativeAttachmentModules': [module for module in NEW_MODULES if module in passed and passed[module].get('nativeParentVerified') is True],
              'physicalInputModules': [module for module, _ in INPUT_CASES if module in passed and passed[module].get('keyboardInputVerified') is True and passed[module].get('contentMutationVerified') is True],
              'attachOnlyModules': [module for module, _ in ATTACH_CASES if module in passed],
              'newDocumentModules': [module for module in NEW_MODULES if 'new-' + module in passed and passed['new-' + module].get('newDocumentVerified') is True]}
    if not success: report['error'] = 'One or more GUI cases failed or required case coverage is incomplete'
    return report


def run_cases(cases, output):
    report = suite_report(collect_cases(cases, output))
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f"GUI cases: {report['passedCaseCount']}/{report['expectedCaseCount']} passed", flush=True)
    return 0 if report['success'] else 1


def main():
    if os.name != 'nt': raise RuntimeError('Actual Windows GUI execution is required')
    if not __debug__: raise RuntimeError('Do not disable native GUI assertions with Python -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for path in (args.suite, args.fixtures, args.output):
        assert not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'Linked Suite/fixture/evidence directories are not accepted'
    suite, fixtures, output = args.suite.resolve(), args.fixtures.resolve(), args.output.resolve()
    assert suite != output and suite not in output.parents, 'Evidence must be outside the payload'
    assert fixtures != output and fixtures not in output.parents, 'Evidence must be outside generated fixtures'
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output)), 'Only local test paths are accepted'
    output.mkdir(parents=True, exist_ok=False)
    prepared_library = prepare_ascii_cohort(suite, output)
    cases = [('home', lambda: capture_home(suite, output))]
    for module, extension in INPUT_CASES:
        cases.append((module, lambda module=module, extension=extension: edit_module(suite, fixtures, output, module, extension,prepared_library=prepared_library)))
    for module, extension in ATTACH_CASES:
        cases.append((module, lambda module=module, extension=extension: attach_module(suite, fixtures, output, module, extension)))
    for module in NEW_MODULES:
        cases.append(('new-' + module, lambda module=module: new_module(suite, output, module, fixtures=fixtures)))
    return run_cases(cases, output)


if __name__ == '__main__': raise SystemExit(main())
