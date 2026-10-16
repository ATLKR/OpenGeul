"""Real keyboard editing in Suite-owned native Windows document frames.

Only generated fixtures under --fixtures are opened. Unicode SendInput is not an
IME-composition test; engine/model tests and native keyboard tests stay separate.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile


def wait_for(check, seconds=60):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = check()
        except (FileNotFoundError, zipfile.BadZipFile):
            last = 'File save is in progress'
        if last: return last
        time.sleep(0.1)
    raise AssertionError('Native UI condition did not become true: ' + str(last))


class Windows:
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = (self.callback, wintypes.LPARAM)
        self.user.GetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
        self.user.GetPropW.restype = wintypes.HANDLE
        self.user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.IsChild.argtypes = (wintypes.HWND, wintypes.HWND)
        self.user.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user.IsWindow.argtypes = (wintypes.HWND,)
        self.user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def windows(self, pid):
        found = []
        def visit(hwnd, _):
            if self.pid(hwnd) == pid and self.user.IsWindowVisible(hwnd): found.append(hwnd)
            return True
        callback = self.callback(visit)
        self.user.EnumWindows(callback, 0)
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
                assert self.user.IsChild(hwnd, parent), 'Host panel is not owned by Suite'
                assert self.user.IsChild(parent, child), 'Office editor is not inside host panel'
                return int(hwnd), int(parent), int(child)
        if process.poll() is not None: raise AssertionError('Suite shell exited before native attachment')
        return None

    def require_foreground(self, hwnd):
        foreground = self.user.GetForegroundWindow()
        assert self.user.GetAncestor(foreground, 2) == hwnd, 'Physical input requires the owned Suite foreground'


def package_text(path):
    with zipfile.ZipFile(path) as archive:
        return '\n'.join(''.join(ET.fromstring(archive.read(name)).itertext())
                         for name in archive.namelist()
                         if (name == 'word/document.xml' or name == 'xl/sharedStrings.xml'
                             or name.startswith('xl/worksheets/') or name.startswith('ppt/slides/'))
                         and name.endswith('.xml'))


def edit_module(suite, fixtures, output, module, extension):
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    source = fixtures/('OpenGeul-' + module + '.' + extension)
    if not source.is_file(): raise AssertionError('Generated fixture is missing: ' + source.name)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    process = subprocess.Popen([str(suite/'OpenGeul.Office.exe'), '--module', module, '--file', str(source)],
                               cwd=suite, shell=False)
    api = Windows()
    record = {'module': module, 'shellPid': process.pid, 'file': source.name, 'success': False}
    try:
        hwnd, parent, child = wait_for(lambda: api.attached(process), seconds=75)
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=api.pid(child))
        assert 'OpenGeul ' + module.title() in api.title(hwnd), 'Document title is not OpenGeul branded'
        assert not api.windows(api.pid(child)), 'Office created an unowned visible top-level window'
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.move_window(x=15, y=15, width=1120, height=710)
        window.set_focus()
        wait_for(lambda: api.user.GetAncestor(api.user.GetForegroundWindow(), 2) == hwnd, 10)
        window.capture_as_image().save(output/(module + '-before.png'))
        api.require_foreground(hwnd)
        send_keys('^{F6}', pause=0.1)
        if module == 'writer': send_keys('^{END}', pause=0.1)
        elif module == 'calc': send_keys('^{HOME}{F2}^{END}', pause=0.1)
        else: send_keys('{TAB}{F2}^{END}', pause=0.1)
        marker = 'UI-OpenGeul-' + module
        api.require_foreground(hwnd)
        send_keys(marker, pause=0.04, with_spaces=True)
        if module == 'calc': send_keys('{ENTER}', pause=0.1)
        api.require_foreground(hwnd)
        send_keys('^s', pause=0.1)
        wait_for(lambda: marker in package_text(source), seconds=30)
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        assert after != before, 'Saved file bytes did not change'
        window.capture_as_image().save(output/(module + '-edited.png'))
        record.update(success=True, keyboardMarker=marker, beforeSha256=before, afterSha256=after,
                      nativeParentVerified=True, noExternalOfficeWindow=True)
        window.close()
        wait_for(lambda: not api.user.IsWindow(hwnd), seconds=20)
        # The Suite home remains open after its last document, as in Office.
        for home in api.windows(process.pid):
            if api.title(home) == 'OpenGeul Office':
                Desktop(backend='win32').window(handle=home).wrapper_object().close()
        process.wait(timeout=25)
        assert process.returncode == 0, 'Suite did not close cleanly'
        return record
    except Exception as exc:
        record['error'] = type(exc).__name__ + ': ' + str(exc)
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(output/(module + '-failure.png'))
        except Exception: pass
        (output/(module + '-result.json')).write_text(json.dumps(record, indent=2), encoding='utf-8')
        raise
    finally:
        if process.poll() is None:
            # All descendants belong to this generated-fixture test, never a user session.
            subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


def main():
    if os.name != 'nt': raise RuntimeError('Actual Windows GUI execution is required')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for module, extension in (('writer', 'docx'), ('calc', 'xlsx'), ('impress', 'pptx')):
        result = edit_module(args.suite.resolve(), args.fixtures.resolve(), args.output.resolve(), module, extension)
        results.append(result)
        (args.output/(module+'-result.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    (args.output/'results.json').write_text(json.dumps({'success': True, 'tests': results}, indent=2), encoding='utf-8')
    print('Actual embedded Windows keyboard/save checks passed:', len(results))


if __name__ == '__main__': main()
