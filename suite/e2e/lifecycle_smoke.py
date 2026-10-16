"""Seven finite native Suite lifecycle cases, using only generated test documents.

Run with system Python after engine_smoke.py. Baseline fixtures are read only;
case-owned copies, screenshots, failures and direct OOXML evidence stay in output.
No unexpected or foreign dialog is accepted, dismissed, or sent keyboard input.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile


def _sibling(name):
    spec = importlib.util.spec_from_file_location('suite_lifecycle_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = _sibling('windows_smoke')
CASE_REQUIREMENTS = {
    'dirty-writer-cancel-save': ('cancelPreservedDirtyEditor', 'closeSavePersisted', 'packagedUnoVerified', 'cleanClose'),
    'dirty-writer-discard': ('discardOriginalShaUnchanged', 'discardMarkerAbsent', 'packagedUnoVerified', 'cleanClose'),
    'new-writer-saveas-cancel': ('pickerCancelRetainedDirtyEditor', 'unicodeSaveAsPersisted', 'packagedUnoVerified', 'cleanClose'),
    'failed-saveas-retains-editor': ('actualSaveAsFailureVerified', 'originalShaPreservedOnFailure', 'subsequentEditSavePersisted', 'packagedUnoVerified', 'cleanClose'),
    'home-two-documents-cancel': ('homeCancelPreservedRemainder', 'remainingEditorSavePersisted', 'packagedUnoVerified', 'cleanClose'),
    'resize-minimize-restore': ('childBoundsFollowedHost', 'minimizeRestoreVerified', 'restoredEditorSavePersisted', 'packagedUnoVerified', 'cleanClose'),
    'hwp-tile-hwpx-route': ('hwpTileBundledProcessVerified', 'hwpxRouteBundledProcessVerified', 'webview2Verified', 'generatedHwpxUnchanged', 'cleanClose'),
}
WRITER_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
HWPX_MARKER = 'Suite-HWPX-route-한글 & 123'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unlinked(path):
    assert not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'Linked test paths are not accepted'


def owned_target(folder, name):
    unlinked(folder)
    assert folder.is_dir(), 'Owned fixture directory is missing'
    assert name and Path(name).name == name and not Path(name).is_absolute(), 'Target must be a direct child of the owned fixture directory'
    target = folder / name
    unlinked(target)
    assert not target.exists(), 'Test target must never overwrite an existing document'
    assert target.resolve().parent == folder.resolve(), 'Target escaped the owned fixture directory'
    return target.resolve()


def writer_evidence(path, required=(), forbidden=()):
    unlinked(path)
    with zipfile.ZipFile(path) as package:
        assert package.testzip() is None, 'Saved Writer package has a corrupt ZIP member'
        document = ET.fromstring(package.read('word/document.xml'))
        body = document.find(WRITER_NS + 'body')
        assert body is not None, 'Saved Writer document has no body'
        paragraphs = [''.join(node.text or '' for node in paragraph.iter(WRITER_NS + 't'))
                      for paragraph in body.iter(WRITER_NS + 'p')]
        text = '\n'.join(paragraphs)
    for marker in required:
        assert text.count(marker) == 1, 'Writer body must contain the exact marker once: ' + marker
    for marker in forbidden:
        assert marker not in text, 'Writer body contains a forbidden marker: ' + marker
    return {'sha256': digest(path), 'bytes': path.stat().st_size, 'bodyText': text,
            'bodyParagraphs': paragraphs, 'requiredMarkers': list(required), 'forbiddenMarkers': list(forbidden)}


def copy_writer_fixture(fixtures, folder, name):
    # The existing thirteen-case GUI job may already have added its known marker.
    # Baseline provenance and original bytes are retained, never rewritten here.
    source = fixtures / 'OpenGeul-writer.docx'
    for item in (fixtures, source): unlinked(item)
    baseline = json.loads((fixtures.parent / 'engine-smoke.json').read_text(encoding='utf-8'))
    assert baseline.get('schemaVersion') == 1 and baseline.get('kind') == 'engine' and baseline.get('passed') is True, 'Passing generated engine baseline is required'
    records = [row for row in baseline['cases'] if row.get('module') == 'writer']
    assert len(records) == 1 and records[0].get('status') == 'passed', 'One passing generated Writer baseline is required'
    assert Path(records[0]['fixture']).resolve() == source.resolve(), 'Writer baseline names another source'
    writer_evidence(source, ('Engine-OpenGeul-writer',))
    original = digest(source)
    target = owned_target(folder, name)
    shutil.copyfile(source, target)
    assert digest(target) == original and digest(source) == original, 'Owned Writer copy differs from generated source'
    return target


def require_dialog_action(*, pid, shell_pid, owner, document, title, expected_title,
                          class_name, text, expected_text, button, allowed):
    native.require_dialog_identity(pid, shell_pid, owner, document, title, expected_title, class_name)
    assert expected_text in text, 'Dialog does not contain the exact expected prompt text'
    assert button in allowed, 'Dialog action is outside the explicit expected choices'


def require_child_bounds(host, child):
    assert host[0:2] == (0, 0) and host[2] > 0 and host[3] > 0, 'Host client bounds must be nonempty'
    assert tuple(child) == tuple(host), 'Embedded child must fill the actual host client bounds: ' + str((host, child))
    return [host[2], host[3]]


def generate_hwpx(target):
    assert owned_target(target.parent, target.name) == target.resolve()
    template = Path(__file__).resolve().parents[2] / 'tests/fixtures/advanced-owned/owned-blank.hwpx'
    unlinked(template)
    with zipfile.ZipFile(template) as source, zipfile.ZipFile(target, 'x') as output:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == 'Contents/section0.xml':
                assert payload.count(b'<hp:t></hp:t>') == 1, 'Owned blank HWPX template changed'
                payload = payload.replace(b'<hp:t></hp:t>', ('<hp:t>' + escape(HWPX_MARKER) + '</hp:t>').encode('utf-8'))
            elif member.filename == 'Preview/PrvText.txt': payload = HWPX_MARKER.encode('utf-8')
            output.writestr(member, payload)
    return target


def lifecycle_report(records):
    counts = Counter(row.get('case') for row in records)
    missing = [name for name in CASE_REQUIREMENTS if counts[name] == 0]
    duplicates = [name for name, count in counts.items() if count > 1]
    unexpected = [name for name in counts if name not in CASE_REQUIREMENTS]
    incomplete = [row.get('case') for row in records if row.get('success') is not True
                  or any(row.get(flag) is not True for flag in CASE_REQUIREMENTS.get(row.get('case'), ()))]
    success = not (missing or duplicates or unexpected or incomplete)
    return {'schemaVersion': 1, 'kind': 'native-lifecycle', 'success': success,
            'expectedCaseCount': len(CASE_REQUIREMENTS), 'completedCaseCount': len(records),
            'passedCaseCount': len(records) - len(incomplete), 'failedCases': incomplete,
            'missingCases': missing, 'duplicateCases': duplicates, 'unexpectedCases': unexpected,
            'imeVerified': False, 'tests': records}


def require_uno_observation(expected, observed, before, after):
    text = observed.replace('\r\n', '\n').replace('\r', '\n')
    assert before == expected['sha256'], 'Saved file changed between direct OOXML evidence and independent UNO reopen'
    assert after == before, 'Independent UNO reopen changed the saved file bytes'
    assert text == expected['bodyText'], 'Independent packaged UNO body differs from direct OOXML body'
    return {'bodyText': text, 'beforeSha256': before, 'afterSha256': after}


def verify_saved_with_uno(suite, output):
    """Runs only in packaged Python, after GUI processes have closed their documents."""
    engine_module = _sibling('engine_smoke')
    engine = engine_module.Engine(suite)
    records = json.loads((output / 'results.json').read_text(encoding='utf-8'))['tests']
    result = {'kind': 'packaged-uno-lifecycle-reopen', 'success': False, 'cases': []}
    try:
        engine.start()
        for record in records:
            if record.get('success') is not True or 'packagedUnoVerified' not in CASE_REQUIREMENTS.get(record.get('case'), ()): continue
            saved = record.get('savedDocuments', [])
            assert saved, 'Successful Writer lifecycle case has no saved document evidence'
            case_result = {'case': record['case'], 'success': False, 'documents': []}
            result['cases'].append(case_result)
            for expected in saved:
                path = Path(expected['path'])
                unlinked(path)
                assert path.resolve().is_relative_to((output / 'fixtures').resolve()), 'UNO verification escaped case-owned fixtures'
                before = digest(path)
                document = None
                try:
                    document = engine.load(path.resolve().as_uri())
                    assert document.supportsService('com.sun.star.text.TextDocument'), 'UNO did not reopen a Writer document'
                    observed = document.getText().getString()
                finally: engine.close_document(document)
                proof = require_uno_observation(expected, observed, before, digest(path))
                case_result['documents'].append({'path': str(path), **proof})
            case_result['success'] = True
        result['success'] = all(row['success'] is True for row in result['cases'])
    except Exception as exc:
        native.capture_failure(output, 'packaged-uno', result, exc)
    finally:
        engine.cleanup()
        if engine.cleanup_errors: result.update(success=False, cleanupErrors=engine.cleanup_errors)
        (output / 'packaged-uno-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return 0 if result['success'] else 1


class LifecycleWindows(native.Windows):
    def __init__(self):
        super().__init__()
        self.user.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.user.GetClientRect.restype = wintypes.BOOL
        self.user.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.user.GetWindowRect.restype = wintypes.BOOL
        self.user.MapWindowPoints.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.POINTER(wintypes.POINT), wintypes.UINT)
        self.user.MapWindowPoints.restype = ctypes.c_int
        self.user.IsIconic.argtypes = (wintypes.HWND,)
        self.user.IsIconic.restype = wintypes.BOOL

    def document_windows(self, process):
        return [hwnd for hwnd in self.windows(process.pid) if self.user.GetPropW(hwnd, 'OpenGeul.Office.ChildHwnd')]

    def bounds(self, parent, child):
        assert self.user.IsChild(parent, child), 'Child ownership changed before resize verification'
        host, screen = wintypes.RECT(), wintypes.RECT()
        if not self.user.GetClientRect(parent, ctypes.byref(host)): raise ctypes.WinError(ctypes.get_last_error())
        if not self.user.GetWindowRect(child, ctypes.byref(screen)): raise ctypes.WinError(ctypes.get_last_error())
        points = (wintypes.POINT * 2)(wintypes.POINT(screen.left, screen.top), wintypes.POINT(screen.right, screen.bottom))
        self.user.MapWindowPoints(None, parent, points, 2)
        return (host.left, host.top, host.right, host.bottom), (points[0].x, points[0].y, points[1].x, points[1].y)


class Case:
    def __init__(self, suite, fixtures, output, name, *, blank=False, home=False):
        self.suite, self.fixtures, self.output, self.name = suite, fixtures, output, name
        self.folder = output / 'fixtures' / name
        self.folder.mkdir()
        self.source = None if blank or home else copy_writer_fixture(fixtures, self.folder, '원본 문서 & ' + name + '.docx')
        command = [str(suite / 'OpenGeul.Office.exe')]
        if not home: command += ['--module', 'writer'] + (['--file', str(self.source)] if self.source else [])
        self.process = native.launch_suite(command, suite, output, name)
        self.api = LifecycleWindows()
        self.record = {'case': name, 'kind': 'native-lifecycle', 'success': False, 'shellPid': self.process.pid,
                       'stage': 'startup', 'stderrLog': name + '-stderr.log', 'imeVerified': False}

    def run(self, action):
        try:
            action(self)
            self.record.update(success=True, stage='complete')
            return self.record
        except Exception as exc:
            native.capture_failure(self.output, self.name, self.record, exc)
            raise
        finally:
            native.stop_owned_test_process(self.process, self.record)
            native.write_result(self.output, self.name, self.record)

    def attach(self, *, previous=()):
        from pywinauto import Desktop
        self.record['stage'] = 'attach'
        def next_document():
            candidate = self.api.attached(self.process)
            if candidate and candidate[0] not in previous: return candidate
            for hwnd in self.api.document_windows(self.process):
                if hwnd not in previous:
                    parent = self.api.user.GetPropW(hwnd, 'OpenGeul.Office.ParentHwnd')
                    child = self.api.user.GetPropW(hwnd, 'OpenGeul.Office.ChildHwnd')
                    assert self.api.user.IsChild(hwnd, parent) and self.api.user.IsChild(parent, child), 'Native editor parent changed'
                    return int(hwnd), int(parent), int(child)
            return None
        hwnd, parent, child = native.wait_for(next_document, 150)
        office_pid = self.api.pid(child)
        assert office_pid and office_pid != self.process.pid and not self.api.windows(office_pid), 'Native editor must be embedded with no external Office window'
        assert 'OpenGeul Writer' in self.api.title(hwnd), 'Wrong native document module'
        self.record.setdefault('attachments', []).append({'hwnd': hwnd, 'parent': parent, 'child': child, 'officePid': office_pid})
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        window.set_focus()
        native.wait_for(lambda: self.api.user.GetAncestor(self.api.user.GetForegroundWindow(), 2) == hwnd, 10)
        return hwnd, parent, child

    def screenshot(self, hwnd, suffix):
        from pywinauto import Desktop
        filename = self.name + '-' + suffix + '.png'
        Desktop(backend='win32').window(handle=hwnd).wrapper_object().capture_as_image().save(self.output / filename)
        self.record.setdefault('screenshots', []).append(filename)

    def edit(self, hwnd, child, marker):
        from pywinauto import Desktop
        from pywinauto.keyboard import send_keys
        self.record['stage'] = 'physical-editor-input'
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.set_focus()
        self.api.require_foreground(hwnd)
        Desktop(backend='win32').window(handle=child).wrapper_object().click_input()
        send_keys('^{F6}', pause=0.1)
        self.api.require_editor_focus(hwnd, child)
        send_keys('^{END}', pause=0.1)
        self.api.require_editor_focus(hwnd, child)
        send_keys(native.literal_keys(marker), with_spaces=True, pause=0.025)
        self.api.require_editor_focus(hwnd, child)
        native.wait_for(lambda: self.api.title(hwnd).startswith('* '), 12)

    def shell_command(self, hwnd, keys):
        from pywinauto import Desktop
        from pywinauto.keyboard import send_keys
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.set_focus()
        self.api.require_foreground(hwnd)
        shell = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
        items = [item for item in shell.descendants(control_type='MenuItem') if item.element_info.name == '파일'
                 and item.element_info.process_id == self.process.pid and item.is_visible() and item.is_enabled()]
        assert len(items) == 1, 'Exact shell-owned File menu is required'
        items[0].click_input()
        self.api.require_foreground(hwnd)
        if keys: send_keys(keys, pause=0.1)

    def new_from_menu(self, hwnd):
        from pywinauto import Desktop
        self.shell_command(hwnd, '')
        candidates = [item for item in Desktop(backend='uia').descendants(control_type='MenuItem')
                      if item.element_info.name == '새 문서' and item.element_info.process_id == self.process.pid
                      and item.is_visible() and item.is_enabled()]
        assert len(candidates) == 1, 'Exact owned shell New Document menu item must be unique'
        self.api.require_foreground(hwnd)
        candidates[0].click_input()

    def dialog(self, owner, title):
        from pywinauto import Desktop
        def find():
            matches = [hwnd for hwnd in self.api.windows(self.process.pid)
                       if self.api.title(hwnd) == title and self.api.user.GetWindow(hwnd, 4) == owner]
            assert len(matches) <= 1, 'Owned dialog identity is ambiguous'
            if not matches: return None
            hwnd = matches[0]
            native.require_dialog_identity(self.api.pid(hwnd), self.process.pid, self.api.user.GetWindow(hwnd, 4),
                                           owner, self.api.title(hwnd), title, self.api.class_name(hwnd))
            return hwnd, Desktop(backend='uia').window(handle=hwnd).wrapper_object()
        return native.wait_for(find, 20)

    def click_dialog(self, owner, title, text, choice, allowed):
        from pywinauto import Desktop
        hwnd, accessible = self.dialog(owner, title)
        def verify():
            require_dialog_action(pid=self.api.pid(hwnd), shell_pid=self.process.pid,
                owner=self.api.user.GetWindow(hwnd, 4), document=owner, title=self.api.title(hwnd),
                expected_title=title, class_name=self.api.class_name(hwnd),
                text=[item.element_info.name for item in accessible.descendants()], expected_text=text,
                button=choice, allowed=allowed)
        verify()
        buttons = [item for item in accessible.descendants(control_type='Button')
                   if item.element_info.name == choice and item.is_visible() and item.is_enabled()]
        assert len(buttons) == 1, 'Exact expected dialog button is missing or ambiguous'
        Desktop(backend='win32').window(handle=hwnd).wrapper_object().set_focus()
        self.api.require_foreground(hwnd)
        verify()
        self.screenshot(hwnd, 'dialog-' + str(len(self.record.get('dialogActions', []))))
        buttons[0].click_input()
        self.record.setdefault('dialogActions', []).append({'hwnd': hwnd, 'owner': owner, 'title': title, 'choice': choice})
        native.wait_for(lambda: not self.api.user.IsWindow(hwnd), 20)
        return hwnd

    def close_choice(self, hwnd, choice):
        self.record['stage'] = 'dirty-close-' + choice
        self.api.request_close(hwnd, self.process.pid)
        return self.click_dialog(hwnd, 'OpenGeul Writer', '변경 내용을 저장하시겠습니까?', choice,
                                 ('저장', '저장하지 않음', '취소'))

    def picker(self, hwnd, target, *, cancel=False):
        from pywinauto import Desktop
        from pywinauto.keyboard import send_keys
        caption = 'OpenGeul Writer — 다른 이름으로 저장'
        dialog, accessible = self.dialog(hwnd, caption)
        edits = [item for item in accessible.descendants(control_type='Edit')
                 if item.element_info.automation_id == '1001' and item.is_visible() and item.is_enabled()]
        assert len(edits) == 1, 'Exact filename Edit 1001 is required'
        Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus()
        self.api.require_foreground(dialog)
        edits[0].click_input()
        send_keys('^a', pause=0.1)
        send_keys(native.literal_keys(str(target)), with_spaces=True, pause=0.01)
        assert edits[0].iface_value.CurrentValue == str(target), 'Picker filename differs from owned target'
        self.screenshot(dialog, 'picker-' + ('cancel' if cancel else 'save'))
        action_id = '2' if cancel else '1'
        buttons = [item for item in accessible.descendants(control_type='Button')
                   if item.element_info.automation_id == action_id and item.is_visible() and item.is_enabled()]
        assert len(buttons) == 1, 'Exact native picker action is missing or ambiguous'
        native.require_dialog_identity(self.api.pid(dialog), self.process.pid, self.api.user.GetWindow(dialog, 4),
                                       hwnd, self.api.title(dialog), caption, self.api.class_name(dialog))
        self.api.require_foreground(dialog)
        buttons[0].click_input()
        return dialog

    def saved(self, hwnd, path, required, forbidden=()):
        self.record['stage'] = 'verify-saved-body'
        def persisted():
            if not path.is_file(): return None
            evidence = writer_evidence(path)
            if any(evidence['bodyText'].count(marker) != 1 for marker in required): return None
            if any(marker in evidence['bodyText'] for marker in forbidden): return None
            return writer_evidence(path, required, forbidden)
        evidence = native.wait_for(persisted, 35)
        native.wait_for(lambda: not self.api.title(hwnd).startswith('* '), 12)
        self.record.setdefault('savedDocuments', []).append({'path': str(path), **evidence})
        return evidence

    def closed(self, hwnd, child):
        native.wait_for(lambda: not self.api.user.IsWindow(hwnd), 25)
        native.wait_for(lambda: not self.api.user.IsWindow(child), 10)

    def finish(self, hwnd=None, child=None):
        if hwnd: native.close_document(self.api, self.process, hwnd, child, self.record)
        native.close_home(self.api, self.process, self.record)
        self.record['cleanClose'] = True


def dirty_cancel_save(case):
    hwnd, _, child = case.attach()
    original = digest(case.source)
    marker, later = '-LIFECYCLE-CANCEL-SAVE-', '-AFTER-CANCEL-'
    case.edit(hwnd, child, marker)
    case.close_choice(hwnd, '취소')
    assert case.api.user.IsWindow(hwnd) and case.api.user.IsWindow(child) and case.process.poll() is None, 'Cancel closed the tested document'
    assert digest(case.source) == original and case.api.title(hwnd).startswith('* '), 'Cancel changed original bytes or cleared dirty state'
    case.edit(hwnd, child, later)
    case.record['cancelPreservedDirtyEditor'] = True
    case.close_choice(hwnd, '저장')
    case.closed(hwnd, child)
    evidence = writer_evidence(case.source, ('Engine-OpenGeul-writer', marker, later))
    assert evidence['sha256'] != original, 'Close Save did not change the generated document'
    case.record.update(closeSavePersisted=True, savedDocuments=[{'path': str(case.source), **evidence}])
    case.finish()


def dirty_discard(case):
    hwnd, _, child = case.attach()
    original = digest(case.source)
    marker = '-LIFECYCLE-DISCARD-'
    case.edit(hwnd, child, marker)
    case.close_choice(hwnd, '저장하지 않음')
    case.closed(hwnd, child)
    evidence = writer_evidence(case.source, ('Engine-OpenGeul-writer',), (marker,))
    assert evidence['sha256'] == original, 'Discard changed original document bytes'
    case.record.update(discardOriginalShaUnchanged=True, discardMarkerAbsent=True,
                       originalSha256=original, afterDiscardSha256=evidence['sha256'],
                       savedDocuments=[{'path': str(case.source), **evidence}])
    case.finish()


def new_saveas_cancel(case):
    hwnd, _, child = case.attach()
    marker, later = '-LIFECYCLE-NEW-', '-AFTER-PICKER-CANCEL-'
    target = owned_target(case.folder, '새 문서 저장 결과 & 한글.docx')
    case.edit(hwnd, child, marker)
    case.shell_command(hwnd, '^s')
    picker = case.picker(hwnd, target, cancel=True)
    native.wait_for(lambda: not case.api.user.IsWindow(picker), 20)
    assert not target.exists() and case.api.user.IsWindow(hwnd) and case.api.title(hwnd).startswith('* '), 'Cancelled first Save As lost dirty new document'
    case.edit(hwnd, child, later)
    case.record['pickerCancelRetainedDirtyEditor'] = True
    case.shell_command(hwnd, '^s')
    picker = case.picker(hwnd, target)
    native.wait_for(lambda: not case.api.user.IsWindow(picker), 20)
    case.saved(hwnd, target, (marker, later))
    case.record['unicodeSaveAsPersisted'] = True
    case.finish(hwnd, child)
    writer_evidence(target, (marker, later))


class ExclusiveRead:
    """Test-owned target only: permit reads so the picker can inspect it, deny writes/deletes."""
    def __init__(self, path):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
        if self.handle == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle): raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


def failed_saveas(case):
    from pywinauto import Desktop
    hwnd, _, child = case.attach()
    original = digest(case.source)
    target = owned_target(case.folder, '잠긴 저장 대상 & 한글.docx')
    shutil.copyfile(case.source, target)
    target_before = digest(target)
    marker, later = '-FAILED-SAVEAS-DIRTY-', '-AFTER-SAVEAS-ERROR-'
    case.edit(hwnd, child, marker)
    lock = ExclusiveRead(target)
    try:
        case.shell_command(hwnd, '^+s')
        picker = case.picker(hwnd, target)
        case.record['stage'] = 'wait-real-saveas-error'
        def expected_error():
            for dialog in case.api.windows(case.process.pid):
                owner = case.api.user.GetWindow(dialog, 4)
                if owner not in (hwnd, picker) or case.api.class_name(dialog) != '#32770': continue
                if case.api.title(dialog) not in ('OpenGeul Office', 'OpenGeul Writer — 다른 이름으로 저장',
                    'Confirm Save As', 'Save As', '다른 이름으로 저장', '다른 이름으로 저장 확인'): continue
                accessible = Desktop(backend='uia').window(handle=dialog).wrapper_object()
                texts = [item.element_info.name for item in accessible.descendants()]
                combined = '\n'.join(texts)
                if target.name in combined and ('already exists' in combined or '이미 있습니다' in combined):
                    return 'overwrite', dialog, owner, accessible, texts
                if (('문서를 저장하지 못했습니다. 문서 창을 유지합니다.' in combined and case.api.title(dialog) == 'OpenGeul Office')
                    or (target.name in combined and any(token in combined.lower() for token in ('in use', 'being used', 'access is denied', 'read-only', 'permission', '사용 중', '액세스', '읽기 전용')))):
                    return 'failure', dialog, owner, accessible, texts
            return None
        observed = native.wait_for(expected_error, 35)
        if observed[0] == 'overwrite':
            _, dialog, owner, accessible, texts = observed
            buttons = [item for item in accessible.descendants(control_type='Button') if item.element_info.automation_id == '6' and item.is_visible() and item.is_enabled()]
            assert len(buttons) == 1, 'Owned overwrite confirmation requires exact Yes control 6'
            native.require_dialog_identity(case.api.pid(dialog), case.process.pid, owner, picker,
                case.api.title(dialog), case.api.title(dialog), case.api.class_name(dialog))
            Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus()
            case.api.require_foreground(dialog)
            buttons[0].click_input()
            native.wait_for(lambda: not case.api.user.IsWindow(dialog), 20)
            observed = native.wait_for(expected_error, 35)
        kind, dialog, owner, accessible, texts = observed
        assert kind == 'failure', 'Save As did not produce a real recognized write denial'
        buttons = [item for item in accessible.descendants(control_type='Button') if item.element_info.automation_id == '1' and item.is_visible() and item.is_enabled()]
        assert len(buttons) == 1, 'Expected actual save-error OK control 1 is missing'
        caption = case.api.title(dialog)
        native.require_dialog_identity(case.api.pid(dialog), case.process.pid, case.api.user.GetWindow(dialog, 4), owner,
                                       caption, caption, case.api.class_name(dialog))
        case.screenshot(dialog, 'actual-saveas-error')
        case.record.update(actualSaveAsFailureVerified=True, failureSurface='suite-worker' if owner == hwnd else 'native-picker',
                           saveErrorCaption=caption, saveErrorText=texts)
        Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus()
        case.api.require_foreground(dialog)
        buttons[0].click_input()
        native.wait_for(lambda: not case.api.user.IsWindow(dialog), 20)
        if case.api.user.IsWindow(picker):
            # The attempted write was denied by the standard picker before dispatch.
            # Cancel this exact still-owned picker, then prove the editor remains usable.
            case.picker(hwnd, target, cancel=True)
            native.wait_for(lambda: not case.api.user.IsWindow(picker), 20)
    finally: lock.close()
    assert digest(case.source) == original and digest(target) == target_before, 'Failed Save As changed an original or locked target'
    assert case.api.user.IsWindow(hwnd) and case.api.user.IsWindow(child) and case.api.title(hwnd).startswith('* '), 'Failed Save As lost the original dirty editor'
    case.record['originalShaPreservedOnFailure'] = True
    case.edit(hwnd, child, later)
    case.shell_command(hwnd, '^s')
    case.saved(hwnd, case.source, ('Engine-OpenGeul-writer', marker, later))
    assert digest(target) == target_before, 'Later direct Save wrote to the failed Save As target'
    case.record['subsequentEditSavePersisted'] = True
    case.finish(hwnd, child)


def home_two_documents(case):
    from pywinauto import Desktop
    home = native.wait_for(lambda: case.api.home(case.process), 30)
    buttons = [item for item in Desktop(backend='uia').window(handle=home).descendants(control_type='Button')
               if item.element_info.name == 'OpenGeul Writer' and item.element_info.process_id == case.process.pid]
    assert len(buttons) == 1, 'Owned Writer home tile must be unique'
    Desktop(backend='win32').window(handle=home).wrapper_object().set_focus()
    case.api.require_foreground(home)
    buttons[0].click_input()
    first, _, child_first = case.attach()
    # First document is clean; Home closes it before the later dirty document cancels.
    case.new_from_menu(first)
    second, _, child_second = case.attach(previous=(first,))
    marker, later = '-HOME-CANCEL-DIRTY-', '-REMAINDER-EDIT-'
    case.edit(second, child_second, marker)
    case.record['stage'] = 'close-home-with-two-documents'
    case.api.request_close(home, case.process.pid)
    case.click_dialog(second, 'OpenGeul Writer', '변경 내용을 저장하시겠습니까?', '취소', ('저장', '저장하지 않음', '취소'))
    case.closed(first, child_first)
    assert case.api.user.IsWindow(home) and case.api.user.IsWindow(second) and case.api.user.IsWindow(child_second), 'Home Cancel lost remaining document or home'
    assert case.process.poll() is None and case.api.title(second).startswith('* '), 'Home Cancel exited or cleared remaining dirty state'
    case.record['homeCancelPreservedRemainder'] = True
    case.edit(second, child_second, later)
    target = owned_target(case.folder, '홈 취소 뒤 남은 문서 & 저장.docx')
    case.shell_command(second, '^s')
    picker = case.picker(second, target)
    native.wait_for(lambda: not case.api.user.IsWindow(picker), 20)
    case.saved(second, target, (marker, later))
    case.record['remainingEditorSavePersisted'] = True
    case.finish(second, child_second)


def resize_restore(case):
    from pywinauto import Desktop
    hwnd, parent, child = case.attach()
    window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
    observations = []
    def fitted():
        host, actual = case.api.bounds(parent, child)
        if host != actual: return None
        dimensions = require_child_bounds(host, actual)
        return {'hostClient': list(host), 'childInHost': list(actual), 'dimensions': dimensions}
    observations.append(native.wait_for(fitted, 15))
    window.restore()
    window.move_window(x=35, y=35, width=950, height=700, repaint=True)
    observations.append(native.wait_for(fitted, 15))
    assert observations[0]['dimensions'] != observations[1]['dimensions'], 'Resize did not change actual host client dimensions'
    window.minimize()
    native.wait_for(lambda: case.api.user.IsIconic(hwnd), 10)
    window.restore()
    native.wait_for(lambda: not case.api.user.IsIconic(hwnd) and case.api.user.IsWindowVisible(child), 15)
    observations.append(native.wait_for(fitted, 15))
    marker = '-AFTER-RESIZE-MINIMIZE-RESTORE-'
    case.edit(hwnd, child, marker)
    case.shell_command(hwnd, '^s')
    case.saved(hwnd, case.source, ('Engine-OpenGeul-writer', marker))
    case.screenshot(hwnd, 'restored-edited')
    case.record.update(childBoundsFollowedHost=True, minimizeRestoreVerified=True,
                       restoredEditorSavePersisted=True, boundsObservations=observations)
    case.finish(hwnd, child)


def _hwp_child_process(shell_pid, executable):
    # Read-only process census; only an exact new child and executable may receive close.
    command = '$p=Get-CimInstance Win32_Process -Filter "ParentProcessId=' + str(int(shell_pid)) + '"; @($p | Select-Object ProcessId,ParentProcessId,ExecutablePath) | ConvertTo-Json -Compress'
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, encoding='utf-8', errors='strict', check=True, timeout=12)
    rows = json.loads(result.stdout.lstrip('\ufeff') or '[]')
    if isinstance(rows, dict): rows = [rows]
    matches = [row for row in rows if row.get('ExecutablePath') and Path(row['ExecutablePath']).resolve() == executable.resolve()]
    assert len(matches) <= 1, 'Bundled HWP launch produced multiple matching child processes'
    return int(matches[0]['ProcessId']) if matches else None


class BoundHwpProcess:
    def __init__(self, pid, executable):
        self.pid = pid
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        try:
            buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, buffer, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            assert Path(buffer.value).resolve() == executable.resolve(), 'HWP process executable changed before binding its native handle'
        except Exception:
            self.close()
            raise

    def live(self):
        state = self.kernel.WaitForSingleObject(self.handle, 0)
        assert state in (0, 258), 'Unable to inspect bound HWP process liveness'
        return state == 258

    def stop(self):
        if self.live():
            subprocess.run(['taskkill.exe', '/PID', str(self.pid), '/T', '/F'], check=True, capture_output=True, timeout=15)
            native.wait_for(lambda: not self.live(), 10)

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle): raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


def hwp_route(case):
    from pywinauto import Desktop
    executable = case.suite / 'HWP' / 'OpenGeul.exe'
    assert executable.is_file(), 'Bundled HWP component is missing'
    home = native.wait_for(lambda: case.api.home(case.process), 30)
    target = generate_hwpx(owned_target(case.folder, '경로 확인 & 한글 문서.hwpx'))
    original = digest(target)
    launches = []

    def verify_and_close(shell, *, path=None):
        pid = native.wait_for(lambda: _hwp_child_process(shell.pid, executable), 45)
        case.record.setdefault('ownedHwpPids', []).append(pid)
        bound = BoundHwpProcess(pid, executable)
        try:
            def ready():
                roots = [hwnd for hwnd in case.api.windows(pid) if case.api.class_name(hwnd) in ('Tauri Window', 'Chrome_WidgetWin_1')]
                assert len(roots) <= 1, 'Bundled HWP editor root is ambiguous'
                if not roots: return None
                hwnd = roots[0]
                tree = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
                children = tree.descendants()
                webviews = [child for child in children if child.class_name() in ('Chrome_WidgetWin_0', 'Chrome_WidgetWin_1', 'Chrome_RenderWidgetHostHWND')]
                if not webviews: return None
                labels = [item.element_info.name for item in Desktop(backend='uia').window(handle=hwnd).descendants()]
                if path and not any(path.name in text for text in [case.api.title(hwnd)] + labels): return None
                return hwnd, [int(child.handle) for child in webviews], labels
            hwnd, webviews, labels = native.wait_for(ready, 75)
            case.screenshot(hwnd, 'hwpx-route' if path else 'hwp-tile')
            launches.append({'pid': pid, 'parentPid': shell.pid, 'executable': str(executable), 'hwnd': int(hwnd),
                             'webviewHwnds': webviews, 'title': case.api.title(hwnd), 'routedFile': path.name if path else None,
                             'filenameObserved': path is None or any(path.name in text for text in [case.api.title(hwnd)] + labels)})
            case.api.request_close(hwnd, pid)
            native.wait_for(lambda: not case.api.user.IsWindow(hwnd), 25)
            native.wait_for(lambda: not bound.live(), 25)
        except Exception:
            # Bound process and exact packaged executable were verified above.
            bound.stop()
            raise
        finally: bound.close()

    buttons = [item for item in Desktop(backend='uia').window(handle=home).descendants(control_type='Button')
               if item.element_info.name == 'OpenGeul HWP' and item.element_info.process_id == case.process.pid]
    assert len(buttons) == 1, 'Exact owned HWP tile must be unique'
    Desktop(backend='win32').window(handle=home).wrapper_object().set_focus()
    case.api.require_foreground(home)
    buttons[0].click_input()
    verify_and_close(case.process)
    case.record['hwpTileBundledProcessVerified'] = True
    case.finish()
    # The extension route is exercised through the real public Suite launch parser.
    routed = native.launch_suite([str(case.suite / 'OpenGeul.Office.exe'), '--file', str(target)],
                                  case.suite, case.output, case.name + '-route')
    try:
        verify_and_close(routed, path=target)
        assert not case.api.document_windows(routed), 'HWPX was routed to an Office editor instead of HWP'
        native.close_home(case.api, routed, case.record)
        case.record['hwpxRouteBundledProcessVerified'] = True
    finally:
        native.stop_owned_test_process(routed, case.record)
    assert digest(target) == original, 'Read-only HWPX route changed generated fixture bytes'
    case.record.update(webview2Verified=True, generatedHwpxUnchanged=True, hwpLaunches=launches, generatedHwpxSha256=original)


def main(argv=None):
    if os.name != 'nt': raise RuntimeError('Actual Windows GUI execution is required; Linux unit checks provide no native proof')
    if not __debug__: raise RuntimeError('Do not disable lifecycle assertions with Python -O')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-saved', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.verify_saved:
        for path in (args.suite, args.output): unlinked(path)
        return verify_saved_with_uno(args.suite.resolve(), args.output.resolve())
    assert args.fixtures is not None, 'Generated baseline --fixtures are required for native cases'
    for path in (args.suite, args.fixtures, args.output): unlinked(path)
    suite, fixtures, output = (path.resolve() for path in (args.suite, args.fixtures, args.output))
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output)), 'Local test paths are required'
    assert suite != output and suite not in output.parents and fixtures != output and fixtures not in output.parents, 'Evidence must be outside payload and baseline fixtures'
    assert suite.is_dir() and fixtures.is_dir(), 'Packaged Suite and generated baseline fixtures are required'
    baseline_hashes = {path.name: digest(path) for path in fixtures.iterdir() if path.is_file()}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'fixtures').mkdir()
    definitions = ((dirty_cancel_save, {}), (dirty_discard, {}), (new_saveas_cancel, {'blank': True}),
                   (failed_saveas, {}), (home_two_documents, {'home': True}), (resize_restore, {}),
                   (hwp_route, {'home': True}))
    cases = [(name, lambda name=name, action=action, options=options:
              Case(suite, fixtures, output, name, **options).run(action))
             for name, (action, options) in zip(CASE_REQUIREMENTS, definitions)]
    records = native.collect_cases(cases, output)
    report = lifecycle_report(records)
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    try:
        with (output / 'packaged-uno.log').open('xb') as log:
            verification = subprocess.run([str(suite / 'Office/program/python.exe'), str(Path(__file__).resolve()),
                '--suite', str(suite), '--output', str(output), '--verify-saved'],
                cwd=suite, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        uno = json.loads((output / 'packaged-uno-result.json').read_text(encoding='utf-8'))
        verified = {item['case']: item for item in uno['cases'] if item.get('success') is True}
        for record in records:
            if record.get('success') is True and 'packagedUnoVerified' in CASE_REQUIREMENTS.get(record.get('case'), ()):
                record['packagedUnoVerified'] = record['case'] in verified
                if not record['packagedUnoVerified']:
                    record.update(success=False, error='Independent packaged UNO saved-body verification failed')
                native.write_result(output, record['case'], record)
        report = lifecycle_report(records)
        report.update(packagedUnoExitCode=verification.returncode, packagedUnoEvidence='packaged-uno-result.json')
        if verification.returncode != 0 or uno.get('success') is not True:
            report.update(success=False, error='Independent packaged UNO lifecycle reopen failed; inspect packaged-uno-result.json and packaged-uno.log')
    except Exception as exc:
        report.update(success=False, error='Independent packaged UNO verification failed: ' + type(exc).__name__ + ': ' + str(exc))
    after = {path.name: digest(path) for path in fixtures.iterdir() if path.is_file()}
    report['baselineFixturesUnchanged'] = after == baseline_hashes
    if after != baseline_hashes:
        report.update(success=False, error='Lifecycle tests changed baseline fixture files')
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f"Lifecycle cases: {report['passedCaseCount']}/{report['expectedCaseCount']} passed", flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__': raise SystemExit(main())
