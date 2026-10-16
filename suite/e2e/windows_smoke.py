"""Actual Suite home, six existing/new embedded frames, and three keyboard edits.

Only generated fixtures under --fixtures are opened. Unicode SendInput is not an
IME-composition test; engine/model tests and native keyboard tests stay separate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile

INPUT_CASES = (('writer', 'docx'), ('calc', 'xlsx'), ('impress', 'pptx'))
ATTACH_CASES = (('draw', 'odg'), ('math', 'odf'), ('base', 'odb'))
MODULE_LABELS = tuple('OpenGeul ' + name for name in ('HWP', 'Writer', 'Calc', 'Impress', 'Draw', 'Math', 'Base'))
NEW_MODULES = tuple(module for module, _ in INPUT_CASES + ATTACH_CASES)


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
    _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                ('rcCaret', wintypes.RECT)]


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
        self.user.GetGUIThreadInfo.argtypes = (wintypes.DWORD, ctypes.POINTER(GuiThreadInfo))
        self.user.GetGUIThreadInfo.restype = wintypes.BOOL

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

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
        return found

    def title(self, hwnd):
        text = ctypes.create_unicode_buffer(2048)
        self.user.GetWindowTextW(hwnd, text, len(text))
        return text.value

    def attached(self, process):
        for hwnd in self.windows(process.pid):
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
        info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
        if not self.user.GetGUIThreadInfo(thread, ctypes.byref(info)): raise ctypes.WinError(ctypes.get_last_error())
        assert info.hwndFocus and (info.hwndFocus == child or self.user.IsChild(child, info.hwndFocus)), 'Keyboard focus is outside the embedded Office editor'
        return int(info.hwndFocus)

    def home(self, process):
        homes = [hwnd for hwnd in self.windows(process.pid) if self.title(hwnd) == 'OpenGeul Office']
        assert len(homes) <= 1, 'Expected one Suite home, not a modal error or duplicate home'
        if homes: return homes[0]
        if process.poll() is not None: raise AssertionError('Suite exited before showing its home')
        return None


def package_text(path):
    with zipfile.ZipFile(path) as archive:
        return '\n'.join(''.join(ET.fromstring(archive.read(name)).itertext())
                         for name in archive.namelist()
                         if (name == 'word/document.xml' or name == 'xl/sharedStrings.xml'
                             or name.startswith('xl/worksheets/') or name.startswith('ppt/slides/'))
                         and name.endswith('.xml'))


def write_result(output, name, record):
    (output / (name + '-result.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def capture_failure(output, name, record, exc):
    record.update(success=False, error=type(exc).__name__ + ': ' + str(exc),
                  traceback=''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(output / (name + '-failure.png'))
    except Exception: pass


def stop_owned_test_process(process, record):
    if process.poll() is not None: return
    try:
        # Only this launched generated-fixture test and its descendants are eligible.
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        process.wait(timeout=5)
    except Exception as exc:
        exit_code = process.poll()
        if isinstance(exc, subprocess.CalledProcessError) and exc.returncode == 128 and exit_code == 0:
            # The owned shell completed normal shutdown between poll and taskkill.
            # Preserve any original case failure; this is only secondary cleanup evidence.
            record.update(cleanupExitRaceVerified=True, cleanupProcessExitCode=exit_code)
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


def close_document(api, process, hwnd, child, record):
    # HwndWrapper.close() adds a 2s deadline before our async teardown waits.
    # Post the same owned WM_CLOSE once, then use the explicit lifecycle bounds.
    record['stage'] = 'close-document'
    api.request_close(hwnd, process.pid)
    record['stage'] = 'wait-document-close'
    wait_for(lambda: not api.user.IsWindow(hwnd), seconds=20)
    record['stage'] = 'wait-editor-close'
    wait_for(lambda: not api.user.IsWindow(child), seconds=10)


def verified_attachment(api, process, module):
    hwnd, parent, child = wait_for(lambda: api.attached(process), seconds=150)
    office_pid = api.pid(child)
    assert office_pid and office_pid != process.pid, 'Editor must belong to the separate native Office engine'
    assert 'OpenGeul ' + module.title() in api.title(hwnd), 'Document title is not OpenGeul branded'
    assert not api.windows(office_pid), 'Office created an unowned visible top-level window'
    return hwnd, parent, child, office_pid


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


def save_new_base(api, process, hwnd, fixtures, output, record):
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    target = new_base_target(fixtures)
    caption = 'OpenGeul Base — 다른 이름으로 저장'
    record['newBaseSaveAsVerified'] = False
    record['stage'] = 'focus-save-menu'
    api.require_foreground(hwnd)
    shell = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
    menus = [item for item in shell.descendants(control_type='MenuItem')
             if item.element_info.name == '파일' and item.element_info.process_id == process.pid
             and item.is_visible() and item.is_enabled()]
    assert len(menus) == 1, 'The exact shell-owned File menu is required for the Save shortcut'
    menus[0].click_input()
    api.require_foreground(hwnd)
    send_keys('^s', pause=0.1)

    def own_save_dialog():
        matches = [dialog for dialog in api.windows(process.pid)
                   if api.title(dialog) == caption and api.user.GetWindow(dialog, 4) == hwnd]
        assert len(matches) <= 1, 'Save As dialog is ambiguous'
        if not matches: return None
        dialog = matches[0]
        native = Desktop(backend='win32').window(handle=dialog).wrapper_object()
        require_dialog_identity(api.pid(dialog), process.pid, api.user.GetWindow(dialog, 4), hwnd,
                                api.title(dialog), caption, native.class_name())
        return dialog, native

    record['stage'] = 'wait-save-dialog'
    dialog, native = wait_for(own_save_dialog, seconds=20)
    accessible = Desktop(backend='uia').window(handle=dialog).wrapper_object()
    edits = [item for item in accessible.descendants(control_type='Edit')
             if item.element_info.automation_id == '1001' and item.is_visible() and item.is_enabled()]
    buttons = [item for item in accessible.descendants(control_type='Button')
               if item.element_info.automation_id == '1' and item.is_visible() and item.is_enabled()]
    assert len(edits) == 1 and len(buttons) == 1, 'Exact standard filename Edit 1001 and Save Button 1 are required'
    native.set_focus()
    api.require_foreground(dialog)
    require_dialog_identity(api.pid(dialog), process.pid, api.user.GetWindow(dialog, 4), hwnd,
                            api.title(dialog), caption, native.class_name())
    record['stage'] = 'type-save-path'
    edits[0].click_input()
    api.require_foreground(dialog)
    send_keys('^a', pause=0.1)
    send_keys(literal_keys(str(target)), with_spaces=True, pause=0.01)
    assert edits[0].iface_value.CurrentValue == str(target), 'Save As filename differs from the fresh owned target'
    native.capture_as_image().save(output / 'new-base-save-as.png')
    require_dialog_identity(api.pid(dialog), process.pid, api.user.GetWindow(dialog, 4), hwnd,
                            api.title(dialog), caption, native.class_name())
    api.require_foreground(dialog)
    assert not target.exists(), 'Save As target appeared before the verified Save click'
    record['stage'] = 'click-save'
    buttons[0].click_input()
    record['stage'] = 'wait-save-dialog-close'
    wait_for(lambda: not api.user.IsWindow(dialog), seconds=20)
    record['stage'] = 'validate-saved-base'
    evidence = wait_for(lambda: saved_base_evidence(target), seconds=30)
    wait_for(lambda: not api.title(hwnd).startswith('* '), seconds=10)
    record.update(saveAsDialogVerified=True, saveAsDialogHwnd=int(dialog), saveAsFilenameAutomationId='1001',
                  saveAsButtonAutomationId='1', saveShortcutViaOwnedMenu=True,
                  savedFile=target.name, beforeCleanupSha256=evidence['sha256'])
    return target


def new_module(suite, output, module, *, fixtures=None):
    from pywinauto import Desktop
    name = 'new-' + module
    process = subprocess.Popen(new_document_command(suite, module), cwd=suite, shell=False)
    api = Windows()
    record = {'module': module, 'kind': 'new-document', 'shellPid': process.pid, 'success': False,
              'keyboardInputVerified': False, 'contentMutationVerified': False, 'imeVerified': False,
              'discardPromptHandled': False, 'stage': 'attach'}
    try:
        hwnd, parent, child, office_pid = verified_attachment(api, process, module)
        record['stage'] = 'prepare-window'
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        window.set_focus()
        wait_for(lambda: api.user.GetAncestor(api.user.GetForegroundWindow(), 2) == hwnd, 10)
        screenshot = name + '-attached.png'
        record['stage'] = 'capture-attached'
        window.capture_as_image().save(output / screenshot)
        assert not api.windows(office_pid), 'New document opened an unowned visible Office window'
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
        close_document(api, process, hwnd, child, record)
        close_home(api, process, record)
        if saved_base is not None:
            record['stage'] = 'verify-base-after-cleanup'
            final = saved_base_evidence(saved_base)
            assert not record['discardPromptHandled'], 'Saved Base must close normally without discard'
            record.update(newBaseSaveAsVerified=True, savedFileSurvivedCleanup=True,
                          savedFileSha256=final['sha256'], savedFileBytes=final['bytes'],
                          savedDatabaseUrl=final['connection'])
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
    process = subprocess.Popen([str(suite / 'OpenGeul.Office.exe')], cwd=suite, shell=False)
    api = Windows()
    record = {'kind': 'home', 'shellPid': process.pid, 'success': False, 'keyboardInputVerified': False, 'stage': 'find-home'}
    try:
        hwnd = wait_for(lambda: api.home(process), seconds=30)
        assert api.windows(process.pid) == [hwnd], 'No-argument startup opened an unexpected document or dialog'
        assert not api.user.GetPropW(hwnd, 'OpenGeul.Office.ChildHwnd'), 'Home must not contain an editor frame'
        record['stage'] = 'prepare-home'
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        window.set_focus()
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


def document_case(suite, fixtures, output, module, extension, physical_input):
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    assert (module, extension) in (INPUT_CASES if physical_input else ATTACH_CASES), 'Module is not eligible for this test mode'
    source = require_engine_fixture(fixtures, module, extension)
    if physical_input:
        assert 'Engine-OpenGeul-' + module in package_text(source), 'Generated source marker is missing'
        assert 'UI-OpenGeul-' + module not in package_text(source), 'UI marker must be absent before actual input'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    process = subprocess.Popen([str(suite/'OpenGeul.Office.exe'), '--module', module, '--file', str(source)],
                               cwd=suite, shell=False)
    api = Windows()
    record = {'module': module, 'kind': 'keyboard-edit' if physical_input else 'native-attach',
              'shellPid': process.pid, 'file': source.name, 'success': False,
              'keyboardInputVerified': False, 'contentMutationVerified': False, 'imeVerified': False, 'stage': 'attach'}
    try:
        hwnd, parent, child, office_pid = verified_attachment(api, process, module)
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=office_pid, title=api.title(hwnd))
        record['stage'] = 'prepare-window'
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        window.set_focus()
        wait_for(lambda: api.user.GetAncestor(api.user.GetForegroundWindow(), 2) == hwnd, 10)
        screenshot = module + ('-before.png' if physical_input else '-attached.png')
        record['stage'] = 'capture-attached'
        window.capture_as_image().save(output / screenshot)
        if physical_input:
            record['stage'] = 'focus-editor'
            api.require_foreground(hwnd)
            # A physical click gives the embedded process focus; Ctrl+F6 enters its document.
            Desktop(backend='win32').window(handle=child).wrapper_object().click_input()
            send_keys('^{F6}', pause=0.1)
            api.require_editor_focus(hwnd, child)
            record['stage'] = 'navigate-editor'
            if module == 'writer': send_keys('^{END}', pause=0.1)
            elif module == 'calc': send_keys('^{HOME}{F2}^{END}', pause=0.1)
            else: send_keys('{TAB}{F2}^{END}', pause=0.1)
            marker = 'UI-OpenGeul-' + module
            focus = api.require_editor_focus(hwnd, child)
            record['stage'] = 'type-marker'
            send_keys(marker, pause=0.04, with_spaces=True)
            if module == 'calc': send_keys('{ENTER}', pause=0.1)
            api.require_editor_focus(hwnd, child)
            record['stage'] = 'save-keyboard'
            send_keys('^s', pause=0.1)
            record['stage'] = 'wait-saved-marker'
            wait_for(lambda: marker in package_text(source), seconds=30)
            assert hashlib.sha256(source.read_bytes()).hexdigest() != before, 'Saved file bytes did not change'
            wait_for(lambda: not api.title(hwnd).startswith('* '), seconds=10)
            record['stage'] = 'capture-edited'
            window.capture_as_image().save(output / (module + '-edited.png'))
            record.update(keyboardMarker=marker, keyboardFocusHwnd=focus,
                          keyboardInputVerified=True, contentMutationVerified=True)
        assert not api.windows(office_pid), 'Office created an unowned visible top-level window during the test'
        record.update(nativeParentVerified=True, noExternalOfficeWindow=True, screenshot=screenshot)
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
        capture_failure(output, module, record, exc)
        raise
    finally:
        stop_owned_test_process(process, record)
        write_result(output, module, record)


def edit_module(suite, fixtures, output, module, extension):
    return document_case(suite, fixtures, output, module, extension, physical_input=True)


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
            record.update(success=False, caseException=type(exc).__name__ + ': ' + str(exc),
                          caseTraceback=''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            record.setdefault('error', record['caseException'])
        record['case'] = name
        record.setdefault('stage', 'case-setup')
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
    cases = [('home', lambda: capture_home(suite, output))]
    for module, extension in INPUT_CASES:
        cases.append((module, lambda module=module, extension=extension: edit_module(suite, fixtures, output, module, extension)))
    for module, extension in ATTACH_CASES:
        cases.append((module, lambda module=module, extension=extension: attach_module(suite, fixtures, output, module, extension)))
    for module in NEW_MODULES:
        cases.append(('new-' + module, lambda module=module: new_module(suite, output, module, fixtures=fixtures)))
    return run_cases(cases, output)


if __name__ == '__main__': raise SystemExit(main())
