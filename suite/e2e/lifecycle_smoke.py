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
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import time
import traceback
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
    'hwp-tile-hwpx-route': ('hwpTileBundledProcessVerified', 'hwpxRouteBundledProcessVerified', 'webview2Verified', 'postLoadEditorVerified', 'toolbarEnabled', 'generatedHwpxUnchanged', 'cleanClose'),
}
ASCII_EDITOR_MARKERS = {
    'dirty-writer-cancel-save': ('-LIFECYCLE-CANCEL-SAVE-', '-AFTER-CANCEL-'),
    'dirty-writer-discard': ('-LIFECYCLE-DISCARD-',),
    'new-writer-saveas-cancel': ('-LIFECYCLE-NEW-', '-AFTER-PICKER-CANCEL-'),
    'failed-saveas-retains-editor': ('-FAILED-SAVEAS-DIRTY-', '-AFTER-SAVEAS-ERROR-'),
    'home-two-documents-cancel': ('-HOME-CANCEL-DIRTY-', '-REMAINDER-EDIT-'),
    'resize-minimize-restore': ('-AFTER-RESIZE-MINIMIZE-RESTORE-',),
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
        # UNO Text.getString() includes soft line breaks and tabs. The generated
        # Writer baseline itself ends with w:br, so discarding these tokens loses
        # real body content before the independent exact-text comparison.
        text_tokens = {WRITER_NS + 't': None, WRITER_NS + 'br': '\n',
                       WRITER_NS + 'cr': '\n', WRITER_NS + 'tab': '\t'}
        paragraphs = [''.join((node.text or '') if text_tokens[node.tag] is None else text_tokens[node.tag]
                              for node in paragraph.iter() if node.tag in text_tokens)
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


def require_saveas_overwrite_owner(dialog, picker, document, shell_pid, target_name):
    """Validate the explicit document/picker owner chains, never a foreign owner."""
    assert document['live'] is True and document['pid'] == shell_pid and shell_pid > 0, 'Save As document is not the live owned Suite form'
    assert type(document['hwnd']) is int and document['hwnd'] > 0, 'Save As document HWND is invalid'
    assert picker['live'] is True and picker['hwnd'] > 0 and picker['hwnd'] != document['hwnd'], 'Save As picker is not a distinct live owned window'
    native.require_dialog_identity(picker['pid'], shell_pid, picker['owner'], document['hwnd'],
        picker['title'], 'OpenGeul Writer — 다른 이름으로 저장', picker['class'])
    assert dialog['live'] is True and dialog['hwnd'] > 0 and dialog['hwnd'] not in (document['hwnd'], picker['hwnd']), 'Overwrite confirmation is not a distinct live dialog'
    assert dialog['owner'] in (document['hwnd'], picker['hwnd']), 'Overwrite confirmation belongs to a foreign owner'
    assert dialog['title'] in ('Confirm Save As', 'Save As', '다른 이름으로 저장', '다른 이름으로 저장 확인',
                               'OpenGeul Writer — 다른 이름으로 저장'), 'Unexpected overwrite confirmation title'
    native.require_dialog_identity(dialog['pid'], shell_pid, dialog['owner'], dialog['owner'],
        dialog['title'], dialog['title'], dialog['class'])
    prompt = '\n'.join(dialog['texts'])
    assert target_name and target_name in prompt and ('already exists' in prompt or '이미 있습니다' in prompt), 'Overwrite confirmation does not name the exact owned target'
    return 'picker-owned' if dialog['owner'] == picker['hwnd'] else 'document-owned'


def owned_menu_items(desktop, pid, name):
    """A UIA Desktop enumerates windows; descendants belong to each wrapper."""
    found, seen = [], set()
    for root in desktop.windows(process=pid):
        if root.element_info.process_id != pid: continue
        for item in root.descendants(control_type='MenuItem'):
            if (item.element_info.name != name or item.element_info.process_id != pid
                or not item.is_visible() or not item.is_enabled()): continue
            identity = tuple(item.element_info.runtime_id)
            assert identity, 'Owned menu item has no UIA runtime identity'
            if identity not in seen:
                found.append(item)
                seen.add(identity)
    return found


def owned_dialog_button(accessible, pid, labels):
    # The observed hosted-Windows picker displayed Yes without exposing
    # automation_id=6. Its exact label, process and verified dialog identity
    # identify the intended action independently of that implementation detail.
    candidates = [item for item in accessible.descendants(control_type='Button')
                  if item.element_info.process_id == pid and item.element_info.name in labels
                  and item.is_visible() and item.is_enabled()]
    assert len(candidates) == 1, 'Exact owned dialog button is missing or ambiguous: ' + repr(labels)
    return candidates[0]


def dialog_uia_identity(accessible, dialog, shell_pid, evidence=None):
    info = accessible.element_info
    observed = {'nativeHandle': int(info.handle or 0), 'processId': info.process_id,
                'runtimeId': list(info.runtime_id), 'name': info.name, 'controlType': info.control_type}
    if evidence is not None: evidence.update(observed)
    assert observed['nativeHandle'] == dialog and dialog > 0, 'UIA root differs from the selected native dialog'
    assert observed['processId'] == shell_pid and shell_pid > 0, 'UIA dialog belongs to a foreign process'
    assert observed['runtimeId'], 'UIA dialog has no runtime identity'
    return observed


def set_owned_picker_filename(api, shell_pid, document, dialog, accessible, field, target, record, *,
                            expected_title='OpenGeul Writer — 다른 이름으로 저장'):
    """Assign only the verified fixture filename; document text still uses physical input."""
    assert expected_title in ('OpenGeul Writer — 다른 이름으로 저장','OpenGeul Office에서 문서 열기',
                              'OpenGeul Base — 다른 이름으로 저장'), 'Unsupported owned filename dialog'
    filename_id='1148' if expected_title=='OpenGeul Office에서 문서 열기' else '1001'
    receipt = {'method': 'Win32-Edit-EM_REPLACESEL', 'expected': str(target), 'before': None, 'after': None,
               'assignmentAttempts': 0, 'selectionSetAttempts': 0, 'focusClickAttempts': 0, 'success': False,
               'document': {}, 'dialog': {}, 'dialogUia': {}, 'field': {}, 'nativeEdit': {},
               'focusBefore': {}, 'focusAfterClick': {}, 'focusAfterAssignment': {}}
    record.setdefault('pickerFilenameInputs', []).append(receipt)
    try:
        receipt['document'] = {'hwnd': int(document), 'pid': api.pid(document), 'live': bool(api.user.IsWindow(document))}
        receipt['dialog'] = {'hwnd': int(dialog), 'pid': api.pid(dialog), 'live': bool(api.user.IsWindow(dialog)),
                             'owner': int(api.user.GetWindow(dialog, 4) or 0),
                             'title': api.title(dialog), 'class': api.class_name(dialog)}
        info = field.element_info
        field_handle = int(info.handle or 0)
        receipt['field'] = {'nativeHandle': field_handle, 'processId': info.process_id,
                            'runtimeId': list(info.runtime_id or ()), 'automationId': info.automation_id,
                            'controlType': info.control_type, 'name': info.name,
                            'visible': bool(field.is_visible()), 'enabled': bool(field.is_enabled()),
                            'nativePid': api.pid(field_handle), 'nativeLive': bool(api.user.IsWindow(field_handle)),
                            'nativeClass': api.class_name(field_handle),
                            'nativeRoot': int(api.user.GetAncestor(field_handle, 2) or 0),
                            'nativeChildOfDialog': bool(api.user.IsChild(dialog, field_handle))}
        dialog_uia_identity(accessible, dialog, shell_pid, receipt['dialogUia'])
        assert document > 0 and receipt['document']['live'] and receipt['document']['pid'] == shell_pid > 0, 'Picker document is not the live owned Suite form'
        native_dialog = receipt['dialog']
        assert dialog != document and native_dialog['live'], 'Picker is not a distinct live native dialog'
        native.require_dialog_identity(native_dialog['pid'], shell_pid, native_dialog['owner'], document,
                                       native_dialog['title'], expected_title, native_dialog['class'])
        observed = receipt['field']
        assert observed['processId'] == observed['nativePid'] == shell_pid and observed['runtimeId'], 'Filename field belongs to a foreign process or lacks runtime identity'
        assert observed['automationId'] == filename_id and observed['controlType'] == 'Edit', 'Exact native filename Edit '+filename_id+' is required'
        assert observed['nativeClass'] == 'Edit', 'Filename must be a standard native Edit control'
        assert field_handle > 0 and observed['nativeLive'] and observed['nativeChildOfDialog'] and observed['nativeRoot'] == dialog, 'Filename field is outside the owned native picker'
        assert observed['visible'] and observed['enabled'], 'Filename field is not visible and enabled'
        value = field.iface_value
        receipt['readOnly'] = bool(value.CurrentIsReadOnly)
        assert receipt['readOnly'] is False, 'Filename ValuePattern is read-only'
        encoded = receipt['expected'].encode('utf-16-le')
        assert '\0' not in receipt['expected'] and 0 < len(encoded) // 2 < 4095, 'Fixture filename exceeds the bounded Unicode Edit scope'
        edit = receipt['nativeEdit']
        api.user.IsWindowUnicode.argtypes = (wintypes.HWND,)
        api.user.IsWindowUnicode.restype = wintypes.BOOL
        api.user.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        api.user.GetWindowLongW.restype = ctypes.c_int32
        edit['unicodeWindow'] = bool(api.user.IsWindowUnicode(field_handle))
        getattr(ctypes, 'set_last_error', lambda error: None)(0)
        style = int(api.user.GetWindowLongW(field_handle, -16))
        edit['styleRaw'] = style & 0xffffffff
        edit['multiline'] = bool(style & 0x0004)
        if not style and getattr(ctypes, 'get_last_error', lambda: 0)():
            raise OSError(getattr(ctypes, 'get_last_error')(), 'Reading owned filename GWL_STYLE failed')
        assert edit['unicodeWindow'], 'Filename native Edit must be Unicode'
        edit.update(timeoutFlags=3, timeoutMs=1000, replacementUtf16Units=len(encoded) // 2,
                    replacementUtf16LeHex=encoded.hex())
        receipt['before'] = value.CurrentValue
        picker_filename_state(api, shell_pid, dialog, field_handle, receipt['focusBefore'])
        assert receipt['focusBefore']['nativeText'] == receipt['before'], 'Native filename differs from UIA before assignment'
        require_picker_filename_context(receipt['focusBefore'], shell_pid, dialog)
        receipt['focusClickAttempts'] = 1
        field.click_input()
        picker_filename_state(api, shell_pid, dialog, field_handle, receipt['focusAfterClick'])
        require_picker_filename_focus(receipt['focusAfterClick'], shell_pid, dialog, field_handle,
                                      receipt['focusBefore']['threadId'])
        api.require_foreground(dialog)
        thread = receipt['focusBefore']['threadId']
        before_length = receipt['focusAfterClick']['nativeTextLength']
        assert before_length < 4095, 'Old filename exceeds bounded packed Edit selection scope'
        assert before_length == len(receipt['focusAfterClick']['nativeText'].encode('utf-16-le')) // 2, 'Native old filename length is not its exact UTF16 length'
        selection = edit['selectionBefore'] = {}
        picker_edit_message(api, shell_pid, dialog, field_handle, thread, 0x00B0, 0, 0, selection)
        assert 0 <= selection['messageReturn'] <= 0xffffffff, 'Native Edit selection exceeded its packed DWORD scope'
        selection.update(packedResult=selection['messageReturn'], start=selection['messageReturn'] & 0xffff,
                         end=(selection['messageReturn'] >> 16) & 0xffff)
        edit['selectReadOnly'] = bool(value.CurrentIsReadOnly)
        assert edit['selectReadOnly'] is False, 'Filename became read-only before native selection'
        picker_edit_message(api, shell_pid, dialog, field_handle, thread, 0x00B1, 0, -1,
                            edit.setdefault('selectResult', {}), (receipt, 'selectionSetAttempts'))
        selection = edit['selectionAfterSelect'] = {}
        picker_edit_message(api, shell_pid, dialog, field_handle, thread, 0x00B0, 0, 0, selection)
        assert 0 <= selection['messageReturn'] <= 0xffffffff, 'Native Edit selection exceeded its packed DWORD scope'
        selection.update(packedResult=selection['messageReturn'], start=selection['messageReturn'] & 0xffff,
                         end=(selection['messageReturn'] >> 16) & 0xffff)
        assert (selection['start'], selection['end']) == (0, before_length), 'Native Edit did not select the entire old filename'
        replacement = ctypes.create_unicode_buffer(receipt['expected'])
        edit['replaceReadOnly'] = bool(value.CurrentIsReadOnly)
        assert edit['replaceReadOnly'] is False, 'Filename became read-only before native replacement'
        # These standard Edit messages are below WM_USER and Windows marshals the
        # Unicode replacement buffer across processes. No synthetic WM_COMMAND
        # or value-change notification is sent; the native Edit performs one edit.
        picker_edit_message(api, shell_pid, dialog, field_handle, thread, 0x00C2, 1,
                            ctypes.addressof(replacement), edit.setdefault('replaceResult', {}),
                            (receipt, 'assignmentAttempts'))
        receipt['after'] = value.CurrentValue
        picker_filename_state(api, shell_pid, dialog, field_handle, receipt['focusAfterAssignment'])
        assert receipt['after'] == receipt['expected'], 'Picker filename differs from owned target'
        assert receipt['focusAfterAssignment']['nativeText'] == receipt['after'], 'Native filename differs from exact UIA readback'
        require_picker_filename_focus(receipt['focusAfterAssignment'], shell_pid, dialog, field_handle,
                                      receipt['focusBefore']['threadId'])
        require_picker_native_edit_receipt(receipt, shell_pid, dialog, field_handle)
        receipt['success'] = True
        return receipt
    except Exception as exc:
        receipt['error'] = type(exc).__name__ + ': ' + str(exc)
        raise


def picker_filename_context(api, shell_pid, dialog, field, evidence):
    """Read a fresh native owner and input-thread context before touching an Edit."""
    api.user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    api.user.GetWindowThreadProcessId.restype = wintypes.DWORD
    evidence.update(threadId=int(api.user.GetWindowThreadProcessId(field, None)),
                    fieldLive=bool(api.user.IsWindow(field)), fieldPid=api.pid(field),
                    fieldRoot=int(api.user.GetAncestor(field, 2) or 0), fieldClass=api.class_name(field))
    assert evidence['threadId'] > 0 and evidence['fieldLive'], 'Filename native field disappeared before focus observation'
    assert evidence['fieldPid'] == shell_pid > 0 and evidence['fieldRoot'] == dialog, 'Filename ownership changed before native text observation'
    assert evidence['fieldClass'] == 'Edit', 'Filename stopped being a standard native Edit'
    info = native.GuiThreadInfo(cbSize=ctypes.sizeof(native.GuiThreadInfo))
    if not api.user.GetGUIThreadInfo(evidence['threadId'], ctypes.byref(info)):
        raise OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), 'GetGUIThreadInfo for owned filename field failed')
    foreground = int(api.user.GetForegroundWindow() or 0)
    evidence.update(activeHwnd=int(info.hwndActive or 0), focusHwnd=int(info.hwndFocus or 0),
                    captureHwnd=int(info.hwndCapture or 0), menuOwnerHwnd=int(info.hwndMenuOwner or 0),
                    flags=int(info.flags), foregroundHwnd=foreground,
                    foregroundRoot=int(api.user.GetAncestor(foreground, 2) or 0))
    require_picker_filename_context(evidence, shell_pid, dialog)
    return evidence


def picker_filename_state(api, shell_pid, dialog, field, evidence):
    """Read the owned UI thread and Edit text; GetWindowText cannot read a foreign-process Edit."""
    picker_filename_context(api, shell_pid, dialog, field, evidence)
    # WM_GETTEXT is bounded and addressed only to the already verified native Edit.
    # LPARAM and the result pointer must retain their full Win64 pointer width.
    send = api.user.SendMessageTimeoutW
    send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    send.restype = ctypes.c_ssize_t
    text, count = ctypes.create_unicode_buffer(4096), ctypes.c_size_t()
    getattr(ctypes, 'set_last_error', lambda error: None)(0)
    if not send(field, 0x000D, len(text), ctypes.addressof(text), 3, 1000, ctypes.byref(count)):
        raise OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), 'Bounded WM_GETTEXT for owned filename field failed')
    evidence.update(nativeText=text.value, nativeTextLength=int(count.value), nativeTextTimeoutMs=1000)
    assert count.value < len(text) - 1, 'Owned filename text exceeds bounded fixture scope'
    return evidence


def picker_edit_message(api, shell_pid, dialog, field, thread, message, wparam, lparam, evidence, attempt=None):
    """One bounded standard Edit message, with fresh ownership/focus retained first."""
    evidence.update(message=message, wParam=wparam, lParam=lparam, timeoutFlags=3, timeoutMs=1000,
                    sendReturn=None, messageReturn=None, context={})
    picker_filename_context(api, shell_pid, dialog, field, evidence['context'])
    require_picker_filename_focus(evidence['context'], shell_pid, dialog, field, thread)
    evidence['unicodeWindow'] = bool(api.user.IsWindowUnicode(field))
    assert evidence['unicodeWindow'], 'Filename Edit stopped being Unicode before native mutation'
    send = api.user.SendMessageTimeoutW
    send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    send.restype = ctypes.c_ssize_t
    result = ctypes.c_size_t()
    if attempt is not None: attempt[0][attempt[1]] = 1
    getattr(ctypes, 'set_last_error', lambda error: None)(0)
    returned = send(field, message, wparam, lparam, 3, 1000, ctypes.byref(result))
    evidence.update(sendReturn=int(returned or 0), messageReturn=int(result.value))
    if not returned:
        raise OSError(getattr(ctypes, 'get_last_error', lambda: 0)(), 'Bounded native filename Edit message failed: ' + hex(message))
    return int(result.value)


def require_picker_filename_context(observed, shell_pid, dialog):
    assert observed['fieldLive'] is True and observed['fieldPid'] == shell_pid, 'Filename focus field is not live in the owned process'
    assert observed['fieldRoot'] == observed['foregroundRoot'] == dialog, 'Filename focus is outside the owned picker root'
    assert observed['threadId'] > 0, 'Filename native input thread is invalid'


def require_picker_filename_focus(observed, shell_pid, dialog, field, thread):
    require_picker_filename_context(observed, shell_pid, dialog)
    assert observed['threadId'] == thread and observed['focusHwnd'] == field, 'Physical filename focus is outside the exact native Edit'


def require_picker_native_edit_receipt(receipt, shell_pid, dialog, field):
    """Replay one native edit's evidence; callers independently bind its expected fixture target."""
    assert receipt['method'] == 'Win32-Edit-EM_REPLACESEL', 'Unexpected fixture filename edit method'
    assert receipt['selectionSetAttempts'] == receipt['assignmentAttempts'] == receipt['focusClickAttempts'] == 1, 'Fixture filename edit must execute once'
    assert receipt['readOnly'] is False and receipt['field']['nativeClass'] == 'Edit'
    edit = receipt['nativeEdit']
    expected = receipt['expected'].encode('utf-16-le')
    assert '\0' not in receipt['expected'] and 0 < len(expected) // 2 < 4095
    assert edit['unicodeWindow'] is True and edit['selectReadOnly'] is edit['replaceReadOnly'] is False
    assert type(edit['styleRaw']) is int and 0 <= edit['styleRaw'] <= 0xffffffff
    assert edit['multiline'] is bool(edit['styleRaw'] & 0x0004)
    assert (edit['timeoutFlags'], edit['timeoutMs']) == (3, 1000)
    assert edit['replacementUtf16LeHex'] == expected.hex() and edit['replacementUtf16Units'] == len(expected) // 2
    before, clicked, assigned = (receipt[key] for key in ('focusBefore', 'focusAfterClick', 'focusAfterAssignment'))
    thread = before['threadId']
    require_picker_filename_context(before, shell_pid, dialog)
    for observed in (before, clicked, assigned):
        assert observed['fieldClass'] == 'Edit'
        assert observed['nativeTextTimeoutMs'] == 1000
        assert observed['nativeTextLength'] == len(observed['nativeText'].encode('utf-16-le')) // 2 < 4095
    for observed in (clicked, assigned): require_picker_filename_focus(observed, shell_pid, dialog, field, thread)
    assert before['nativeText'] == receipt['before']
    assert assigned['nativeText'] == receipt['after'] == receipt['expected']
    for name, message, wparam, lparam in (('selectionBefore', 0x00B0, 0, 0), ('selectResult', 0x00B1, 0, -1),
                                         ('selectionAfterSelect', 0x00B0, 0, 0), ('replaceResult', 0x00C2, 1, None)):
        observed = edit[name]
        assert (observed['message'], observed['wParam'], observed['timeoutFlags'], observed['timeoutMs']) == (message, wparam, 3, 1000)
        assert type(observed['lParam']) is int and (observed['lParam'] == lparam if lparam is not None else observed['lParam'] > 0)
        assert type(observed['sendReturn']) is int and observed['sendReturn'] != 0
        assert type(observed['messageReturn']) is int and observed['unicodeWindow'] is True
        assert observed['context']['fieldClass'] == 'Edit'
        require_picker_filename_focus(observed['context'], shell_pid, dialog, field, thread)
    for name in ('selectionBefore', 'selectionAfterSelect'):
        observed = edit[name]
        assert 0 <= observed['messageReturn'] <= 0xffffffff and observed['packedResult'] == observed['messageReturn']
        assert (observed['start'], observed['end']) == (observed['packedResult'] & 0xffff, (observed['packedResult'] >> 16) & 0xffff)
    assert (edit['selectionAfterSelect']['start'], edit['selectionAfterSelect']['end']) == (0, clicked['nativeTextLength'])
    return edit


def require_dialog_button_ancestry(api, accessible, button, shell_pid, dialog, evidence=None):
    """Bind an action to its first UIA Window and independently to the native root."""
    root = dialog_uia_identity(accessible, dialog, shell_pid)
    path, info = evidence if evidence is not None else [], button.element_info
    for _ in range(64):
        assert info is not None, 'Dialog button has no owned Window ancestor'
        row = {'nativeHandle': int(info.handle or 0), 'processId': info.process_id,
               'runtimeId': list(info.runtime_id), 'name': info.name, 'controlType': info.control_type}
        path.append(row)
        assert row['processId'] == shell_pid and row['runtimeId'], 'Dialog button ancestry is foreign or lacks runtime identity'
        if row['nativeHandle']:
            handle = row['nativeHandle']
            assert api.user.IsWindow(handle) and api.pid(handle) == shell_pid, 'Dialog button ancestry is not a live owned native window'
            row['nativeRoot'] = int(api.user.GetAncestor(handle, 2) or 0)
            assert row['nativeRoot'] == dialog, 'Dialog button native ancestry reaches another window'
        if row['controlType'] == 'Window':
            assert row['nativeHandle'] == dialog and row['runtimeId'] == root['runtimeId'], 'Dialog button belongs to another UIA Window'
            return path
        info = info.parent
    raise AssertionError('Dialog button ancestry exceeds its bounded dialog scope')


def saveas_error_surface(api, shell_pid, document, picker, target_name, desktop):
    for dialog in api.windows(shell_pid):
        # Owned common dialogs appear inside their picker's UIA descendants.
        # The picker itself must never qualify from that aggregate prompt text.
        if dialog in (document, picker): continue
        owner = api.user.GetWindow(dialog, 4)
        if (not api.user.IsWindow(dialog) or api.pid(dialog) != shell_pid
            or owner not in (document, picker) or api.class_name(dialog) != '#32770'): continue
        caption = api.title(dialog)
        if caption not in ('OpenGeul Office', 'OpenGeul Writer — 다른 이름으로 저장',
            'Confirm Save As', 'Save As', '다른 이름으로 저장', '다른 이름으로 저장 확인'): continue
        accessible = desktop.window(handle=dialog).wrapper_object()
        dialog_uia_identity(accessible, dialog, shell_pid)
        texts = [item.element_info.name for item in accessible.descendants()]
        combined = '\n'.join(texts)
        if target_name in combined and ('already exists' in combined or '이미 있습니다' in combined):
            return 'overwrite', dialog, owner, accessible, texts
        if (('문서를 저장하지 못했습니다. 문서 창을 유지합니다.' in combined and caption == 'OpenGeul Office')
            or (target_name in combined and any(token in combined.lower() for token in ('in use', 'being used', 'access is denied', 'read-only', 'permission', '사용 중', '액세스', '읽기 전용')))):
            return 'failure', dialog, owner, accessible, texts
    return None


def accessibility_names(window):
    # Labels need no control-specific wrappers. During WebView startup a raw
    # element can have no ControlType, which pywinauto 0.6.9 cannot wrap even
    # though its name is available. Keep that real name in the owned census.
    info = window.element_info
    return [info.name] + [item.name for item in info.descendants()]


def hwp_accessibility_snapshot(window):
    """Read public metadata below the already-bound native HWP root, without wrappers."""
    from comtypes import COMError
    infos = [window.element_info] + window.element_info.descendants()
    assert len(infos) <= 4096, 'Owned HWP accessibility census exceeds its bounded fixture scope'
    rows = []
    for info in infos:
        row = {'name': '', 'controlType': None, 'automationId': '', 'processId': None, 'runtimeId': [],
               'enabled': False, 'visible': False, 'bounds': [0, 0, 0, 0]}
        try:
            name = info.name or ''
            assert isinstance(name, str) and len(name) <= 4096, 'Owned HWP accessibility name exceeds its bounded fixture scope'
            row.update(name=name, controlType=info.control_type, automationId=info.automation_id or '',
                       processId=info.process_id, runtimeId=list(info.runtime_id or ()))
            rectangle = info.rectangle
            row.update(enabled=bool(info.enabled), visible=bool(info.visible),
                       bounds=[int(rectangle.left), int(rectangle.top), int(rectangle.right), int(rectangle.bottom)])
        except COMError as exc:
            # A provider may invalidate a node during its normal startup. Keep
            # the failed read in raw evidence; it cannot satisfy readiness.
            row.update(enabled=False, visible=False, metadataError={'hresult': exc.hresult, 'message': str(exc)})
        rows.append(row)
    return rows


def hwp_postload_observation(rows):
    """Pinned HWP releases its inert style bar only after canvas.loadDocument()."""
    def one(kind, match, *, visible):
        candidates = [row for row in rows if row['controlType'] == kind and match(row)
                      and type(row['processId']) is int and row['processId'] > 0 and row['runtimeId']
                      and row['enabled'] is True and (not visible or (row['visible'] is True
                          and row['bounds'][2] > row['bounds'][0] and row['bounds'][3] > row['bounds'][1]))]
        assert len(candidates) <= 1, 'Owned HWP post-load control identity is ambiguous'
        return candidates[0] if candidates else None
    # RHWP deliberately places this IME textarea offscreen (left:-9999px,
    # opacity:0). Requiring its visual bounds would reject the real editor.
    editor = one('Edit', lambda row: row['name'] == '문서 편집 입력', visible=False)
    size = one('Edit', lambda row: row['automationId'] == 'font-size' or row['name'] == '글자 크기 (pt)', visible=True)
    # The pinned custom-select component exposes actual Button triggers using
    # the selected text, rather than visible native ComboBox controls.
    language = one('Button', lambda row: row['name'] == '대표', visible=True)
    style = one('Button', lambda row: row['name'] == '바탕글', visible=True)
    if any(row is None for row in (editor, size, language, style)): return None
    return {'postLoadEditorVerified': True, 'toolbarEnabled': True, 'editorInput': editor,
            'fontSize': size, 'fontLanguage': language, 'style': style}


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
            case_result = {'case': record['case'], 'success': False, 'documents': []}
            result['cases'].append(case_result)
            try:
                saved = record.get('savedDocuments', [])
                assert saved, 'Successful Writer lifecycle case has no saved document evidence'
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
                    # Keep actual observations even when exact-text or byte
                    # validation fails; later independent cases still execute.
                    document_result = {'path': str(path), 'observedBodyText': observed,
                                       'expectedBodyText': expected['bodyText'],
                                       'beforeSha256': before, 'afterSha256': digest(path)}
                    case_result['documents'].append(document_result)
                    document_result.update(require_uno_observation(expected, observed, before, document_result['afterSha256']))
                case_result['success'] = True
            except Exception as exc:
                native.capture_failure(output, 'packaged-uno-' + record['case'], case_result, exc)
        result['success'] = bool(result['cases']) and all(row['success'] is True for row in result['cases'])
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


def retained_writer_shell(process, suite, evidence):
    """Query the actual Popen HANDLE without replacing or closing that handle."""
    evidence.update(kind='retained-suite-popen-process',handleValue=int(process._handle))
    assert evidence['handleValue']>0
    kernel=hwp_kernel()
    kernel.GetProcessId.argtypes=(wintypes.HANDLE,);kernel.GetProcessId.restype=wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes=(wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD));kernel.GetExitCodeProcess.restype=wintypes.BOOL
    evidence['pid']=int(kernel.GetProcessId(evidence['handleValue']))
    if not evidence['pid']:raise ctypes.WinError(ctypes.get_last_error())
    image,creation=process_identity(kernel,evidence['handleValue'],evidence)
    evidence['waitResult']=int(kernel.WaitForSingleObject(evidence['handleValue'],0))
    code=wintypes.DWORD()
    if not kernel.GetExitCodeProcess(evidence['handleValue'],ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
    evidence['exitCode']=int(code.value)
    assert evidence['pid']==process.pid and image==(suite/'OpenGeul.Office.exe').resolve(), 'Original Suite Popen HANDLE identifies another process'
    assert evidence['waitResult']==258 and evidence['exitCode']==259 and process.poll() is None, 'Original Suite Popen process is no longer alive'
    return creation


class WriterModelContext:
    """One attachment's independent baseline and cumulative completion ledger.

    Each edit gets a fresh bounded read-only helper. No helper survives into an
    original close/save action, and a failed edit cannot be retried here.
    """
    def __init__(self, case, attachment):
        self.case, self.attachment = case, dict(attachment)
        self.baseline = case.writer_model_baseline['bodyText']
        self.expected_url = case.source.resolve().as_uri() if case.source else ''
        self.completed_markers = []
        self.native_binding = None
        self.reader = self.plan = self.receipt = None
        self.failed = False

    def begin(self, marker):
        from writer_model_barrier import freeze_expectation, BINDING_KEYS
        from writer_model_reader import OwnedWriterReader
        from writer_style_smoke import _packaged_identity_file
        assert not self.failed and self.reader is None, 'Completion context cannot retry an edit'
        started = time.monotonic()
        self.deadline = started + 12.0
        receipts = self.case.record.setdefault('writerModelCompletions', [])
        expected = ASCII_EDITOR_MARKERS[self.case.name]
        assert len(receipts) < len(expected) and marker == expected[len(receipts)], 'Original case edit order changed'
        self.receipt = {'schemaVersion': 1, 'kind': 'writer-model-completion', 'success': False,
                        'startedAt': started, 'deadline': self.deadline,
                        'originalPhysicalAsciiLossCauseEstablished': False, 'productFixEstablished': False}
        receipts.append(self.receipt)  # Keep startup and before-input failures too.
        try:
            self.receipt['originalShell']={}
            shell_creation=retained_writer_shell(self.case.process,self.case.suite,self.receipt['originalShell'])
            inventory_file, data = _packaged_identity_file(self.case.suite, 'suite-inventory.json')
            self.inventory, self.inventory_sha256 = json.loads(data), inventory_file['sha256']
            attachment = self.attachment
            destination = self.case.output / 'writer-model-readers' / self.case.name / ('edit-%02d' % len(receipts))
            self.receipt['readerOutput'] = str(destination)
            self.reader = OwnedWriterReader(self.case.suite, destination, shell_pid=self.case.process.pid,
                suite_hwnd=attachment['hwnd'], parent_hwnd=attachment['parent'], child_hwnd=attachment['child'],
                office_pid=attachment['officePid'], expected_shell_creation=shell_creation,expected_url=self.expected_url)
            before = self.reader.start(self.deadline)
            self.receipt['beforeInput'] = before
            binding = before['bindingBefore']
            native_binding = {key: binding[key] for key in BINDING_KEYS - {'frameIdentity','controllerIdentity','modelIdentity'}}
            if self.native_binding is not None:
                assert native_binding == self.native_binding, 'Original frame generation changed between edits'
            self.plan = freeze_expectation(binding, self.baseline, self.completed_markers, marker, before,
                suite_root=self.case.suite,original_shell=self.receipt['originalShell'], inventory=self.inventory, inventory_sha256=self.inventory_sha256,
                started_at=started, timeout_seconds=12.0)
            self.native_binding = native_binding
            self.receipt['expectation'] = self.plan.receipt()
            return self.plan
        except BaseException as exc:
            self.abort(exc)
            raise

    def complete(self, plan):
        from writer_model_barrier import await_completion, finalize_completion
        assert plan is self.plan and not self.failed and self.reader is not None
        try:
            await_completion(plan, self.reader.read, clock=time.monotonic, pause=time.sleep, record=self.receipt)
            cleanup = self.reader.close(self.deadline)
            self.reader = None
            finalize_completion(plan, self.receipt, cleanup, time.monotonic())
            self.completed_markers.append(plan.next_marker)
        except BaseException as exc:
            self.abort(exc)
            raise
        finally:
            if not self.failed: self.persist()

    def persist(self):
        if self.receipt is None: return
        destination = Path(self.receipt['readerOutput'])
        if destination.is_dir():
            (destination / 'completion.json').write_text(json.dumps(self.receipt, ensure_ascii=False,
                indent=2, allow_nan=False), encoding='utf-8')

    def abort(self, exc):
        self.failed = True
        if self.receipt is not None:
            self.receipt.update(success=False, state='failed')
            self.receipt.setdefault('error', type(exc).__name__ + ': ' + str(exc))
            self.receipt.setdefault('traceback', traceback.format_exc())
        if self.reader is not None:
            try: self.receipt['cleanup'] = self.reader.close(self.deadline)
            except BaseException as later:
                self.receipt.setdefault('cleanupErrors', []).append(type(later).__name__ + ': ' + str(later))
            finally: self.reader = None
        try: self.persist()
        except BaseException as later:
            # Preserve the first failure; final case JSON still retains this
            # secondary write error even if the reader directory is unavailable.
            self.receipt.setdefault('persistenceErrors', []).append(type(later).__name__ + ': ' + str(later))


class Case:
    def __init__(self, suite, fixtures, output, name, *, blank=False, home=False):
        self.suite, self.fixtures, self.output, self.name = suite, fixtures, output, name
        self.folder = output / 'fixtures' / name
        self.folder.mkdir()
        self.source = None if blank or home else copy_writer_fixture(fixtures, self.folder, '원본 문서 & ' + name + '.docx')
        # Freeze the independent original OOXML body before the editor starts.
        self.writer_model_baseline = writer_evidence(self.source) if self.source else {'bodyText': '', 'kind': 'known-blank-factory'}
        self.writer_model_contexts = {}
        command = [str(suite / 'OpenGeul.Office.exe')]
        if not home: command += ['--module', 'writer'] + (['--file', str(self.source)] if self.source else [])
        self.process = native.launch_suite(command, suite, output, name)
        self.api = LifecycleWindows()
        self.record = {'case': name, 'kind': 'native-lifecycle', 'success': False, 'shellPid': self.process.pid,
                       'stage': 'startup', 'stderrLog': name + '-stderr.log', 'imeVerified': False}

    def run(self, action):
        try:
            action(self)
            from writer_model_barrier import replay_case_completions
            from writer_style_smoke import _packaged_identity_file
            inventory_file, inventory_data = _packaged_identity_file(self.suite, 'suite-inventory.json')
            urls = {key: context.expected_url for key, context in self.writer_model_contexts.items()}
            self.record['writerModelReplay'] = replay_case_completions(self.record, suite_root=self.suite,
                inventory=json.loads(inventory_data), inventory_sha256=inventory_file['sha256'],
                baseline_body=self.writer_model_baseline['bodyText'], expected_urls=urls)
            self.record.update(success=True, stage='complete')
            return self.record
        except Exception as exc:
            native.capture_failure(self.output, self.name, self.record, exc)
            raise
        finally:
            for context in self.writer_model_contexts.values():
                if context.reader is not None:
                    context.abort(AssertionError('Case exited before its owned observation helper was released'))
                    self.record['success'] = False
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
        native.activate_owned_suite(self.api, self.process, hwnd, self.record)
        native.wait_for(lambda: self.api.user.GetAncestor(self.api.user.GetForegroundWindow(), 2) == hwnd, 10)
        return hwnd, parent, child

    def screenshot(self, hwnd, suffix):
        from pywinauto import Desktop
        filename = self.name + '-' + suffix + '.png'
        Desktop(backend='win32').window(handle=hwnd).wrapper_object().capture_as_image().save(self.output / filename)
        self.record.setdefault('screenshots', []).append(filename)

    def _writer_model_context(self, hwnd, child):
        key = (hwnd, child)
        if key not in self.writer_model_contexts:
            matches = [row for row in self.record.get('attachments', []) if (row['hwnd'], row['child']) == key]
            assert len(matches) == 1, 'Model completion requires one original attachment'
            self.writer_model_contexts[key] = WriterModelContext(self, matches[0])
        return self.writer_model_contexts[key]

    def edit(self, hwnd, child, marker):
        from pywinauto import Desktop
        self.record['stage'] = 'physical-editor-input'
        attachments = [row for row in self.record.get('attachments', [])
                       if row['hwnd'] == hwnd and row['child'] == child]
        assert len(attachments) == 1, 'Editor input requires one exact previously owned attachment'
        context = self._writer_model_context(hwnd, child)
        plan = context.begin(marker)
        try:
            window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
            native.activate_owned_suite(self.api, self.process, hwnd, self.record)
            self.api.require_foreground(hwnd)
            entry_deadline=time.monotonic()+5
            with native.FirstAdmissionEditorSession(self.api,self.process,attachments[0],
                    'LIFECYCLE_WRITER',self.record,entry_deadline,marker=marker) as shortcuts:
                shortcuts.join_model(context,plan)
                native.prepare_editor_focus(self.api, hwnd, child, self.process.pid, attachments[0]['officePid'], self.record,
                    lambda: native.click_owned_editor(self.api,self.process,hwnd,attachments[0]['parent'],child,attachments[0]['officePid'],self.record),
                    lambda: shortcuts.press('CTRL_F6'),seconds=min(entry_deadline,context.deadline)-time.monotonic())
                shortcuts.editor_ready(self.record['editorFocusReadiness'])
                self.api.require_editor_focus(hwnd, child)
                shortcuts.press('CTRL_END')
                self.api.require_editor_focus(hwnd, child)
                typed=native.ascii_input.type_ascii(self.api, hwnd, child, marker, self.record, pause=0.025,deadline=shortcuts.deadline)
                shortcuts.typed(typed)
                self.api.require_editor_focus(hwnd, child)
                shortcuts.complete_model(context,plan)
        except BaseException as exc:
            context.abort(exc)
            raise
        native.wait_for(lambda: self.api.title(hwnd).startswith('* '), 12)

    def shell_command(self, hwnd, keys):
        from pywinauto import Desktop
        assert keys in ('','^s','^+s'), 'Unsupported original shell command'
        self.record['stage']='focus-owned-shell-file-menu'
        native.activate_owned_suite(self.api, self.process, hwnd, self.record)
        self.api.require_foreground(hwnd)
        shell = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
        items = [item for item in shell.descendants(control_type='MenuItem') if item.element_info.name == '파일'
                 and item.element_info.process_id == self.process.pid and item.is_visible() and item.is_enabled()]
        assert len(items) == 1, 'Exact shell-owned File menu is required'
        native.click_owned_control(self.api,self.process,hwnd,items[0],self.record,purpose='FILE_MENU')
        if keys:
            self.record['stage']='send-owned-shell-save-shortcut'
            native.send_host_menu_shortcut(self.api,self.process,hwnd,items[0],self.record,
                shortcut='CTRL_S' if keys=='^s' else 'CTRL_SHIFT_S',
                caption='OpenGeul Writer — 다른 이름으로 저장')

    def new_from_menu(self, hwnd):
        from pywinauto import Desktop
        self.shell_command(hwnd, '')
        candidates = owned_menu_items(Desktop(backend='uia'), self.process.pid, '새 문서')
        assert len(candidates) == 1, 'Exact owned shell New Document menu item must be unique'
        self.api.require_foreground(hwnd)
        candidates[0].click_input()

    def dialog(self, owner, title, deadline=None):
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
        seconds=20 if deadline is None else deadline-time.monotonic()
        assert seconds>0,'Original owned dialog deadline expired'
        return native.wait_for(find, seconds)

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
        caption = 'OpenGeul Writer — 다른 이름으로 저장'
        dialog, accessible = self.dialog(hwnd, caption)
        edits = [item for item in accessible.descendants(control_type='Edit')
                 if item.element_info.automation_id == '1001' and item.is_visible() and item.is_enabled()]
        assert len(edits) == 1, 'Exact filename Edit 1001 is required'
        Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus()
        self.api.require_foreground(dialog)
        set_owned_picker_filename(self.api, self.process.pid, hwnd, dialog, accessible, edits[0], target, self.record)
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
    marker, later = ASCII_EDITOR_MARKERS['dirty-writer-cancel-save']
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
    marker, = ASCII_EDITOR_MARKERS['dirty-writer-discard']
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
    marker, later = ASCII_EDITOR_MARKERS['new-writer-saveas-cancel']
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
    marker, later = ASCII_EDITOR_MARKERS['failed-saveas-retains-editor']
    case.edit(hwnd, child, marker)
    lock = ExclusiveRead(target)
    try:
        case.shell_command(hwnd, '^+s')
        picker = case.picker(hwnd, target)
        case.record['stage'] = 'wait-real-saveas-error'
        def expected_error():
            return saveas_error_surface(case.api, case.process.pid, hwnd, picker, target.name, Desktop(backend='uia'))
        observed = native.wait_for(expected_error, 35)
        if observed[0] == 'overwrite':
            _, dialog, owner, accessible, texts = observed
            def identity(handle):
                return {'hwnd': int(handle), 'pid': case.api.pid(handle), 'live': bool(case.api.user.IsWindow(handle)),
                        'owner': int(case.api.user.GetWindow(handle, 4) or 0),
                        'title': case.api.title(handle), 'class': case.api.class_name(handle)}
            ownership = {'dialog': {**identity(dialog), 'texts': texts,
                                    'uia': dialog_uia_identity(accessible, dialog, case.process.pid)},
                         'picker': identity(picker), 'document': identity(hwnd)}
            # A Windows common-dialog overwrite prompt can be owned directly by
            # the document form while its live picker is owned by that same form.
            # Retain the full observed chain before validation or any button input.
            case.record['saveAsOverwriteOwnership'] = ownership
            case.record['saveAsOverwriteOwnerChain'] = require_saveas_overwrite_owner(
                ownership['dialog'], ownership['picker'], ownership['document'], case.process.pid, target.name)
            button = owned_dialog_button(accessible, case.process.pid, ('Yes', '&Yes', '예', '예(&Y)'))
            case.record['saveAsOverwriteYesAncestry'] = []
            # Retain each checked ancestor even if a later node fails closed.
            require_dialog_button_ancestry(case.api, accessible, button, case.process.pid, dialog,
                                          case.record['saveAsOverwriteYesAncestry'])
            case.screenshot(dialog, 'overwrite-confirmation')
            Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus()
            case.api.require_foreground(dialog)
            button.click_input()
            native.wait_for(lambda: not case.api.user.IsWindow(dialog), 20)
            observed = native.wait_for(expected_error, 35)
        kind, dialog, owner, accessible, texts = observed
        assert kind == 'failure', 'Save As did not produce a real recognized write denial'
        caption = case.api.title(dialog)
        case.record['saveErrorUia'] = dialog_uia_identity(accessible, dialog, case.process.pid)
        native.require_dialog_identity(case.api.pid(dialog), case.process.pid, case.api.user.GetWindow(dialog, 4), owner,
                                       caption, caption, case.api.class_name(dialog))
        button = owned_dialog_button(accessible, case.process.pid, ('OK', '&OK', '확인'))
        case.screenshot(dialog, 'actual-saveas-error')
        case.record.update(actualSaveAsFailureVerified=True, failureSurface='suite-worker' if owner == hwnd else 'native-picker',
                           saveErrorCaption=caption, saveErrorText=texts)
        Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus()
        case.api.require_foreground(dialog)
        button.click_input()
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
    native.activate_owned_suite(case.api, case.process, home, case.record)
    case.api.require_foreground(home)
    buttons[0].click_input()
    first, _, child_first = case.attach()
    # First document is clean; Home closes it before the later dirty document cancels.
    case.new_from_menu(first)
    second, _, child_second = case.attach(previous=(first,))
    marker, later = ASCII_EDITOR_MARKERS['home-two-documents-cancel']
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
    marker, = ASCII_EDITOR_MARKERS['resize-minimize-restore']
    case.edit(hwnd, child, marker)
    case.shell_command(hwnd, '^s')
    case.saved(hwnd, case.source, ('Engine-OpenGeul-writer', marker))
    case.screenshot(hwnd, 'restored-edited')
    case.record.update(childBoundsFollowedHost=True, minimizeRestoreVerified=True,
                       restoredEditorSavePersisted=True, boundsObservations=observations)
    case.finish(hwnd, child)


class ProcessEntry32W(ctypes.Structure):
    _fields_ = [('dwSize', ctypes.c_uint32), ('cntUsage', ctypes.c_uint32),
                ('th32ProcessID', ctypes.c_uint32), ('th32DefaultHeapID', ctypes.c_size_t),
                ('th32ModuleID', ctypes.c_uint32), ('cntThreads', ctypes.c_uint32),
                ('th32ParentProcessID', ctypes.c_uint32), ('pcPriClassBase', ctypes.c_int32),
                ('dwFlags', ctypes.c_uint32), ('szExeFile', wintypes.WCHAR * 260)]


def hwp_kernel():
    assert ctypes.sizeof(ctypes.c_void_p) == 8, 'Native HWP census requires the x64 harness'
    if os.name == 'nt': assert ctypes.sizeof(ProcessEntry32W) == 568, 'PROCESSENTRY32W x64 layout is invalid'
    if os.name == 'nt': assert ctypes.sizeof(wintypes.FILETIME) == 8, 'Windows FILETIME layout is invalid'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    bindings = {
        'CreateToolhelp32Snapshot': ((wintypes.DWORD, wintypes.DWORD), wintypes.HANDLE),
        'Process32FirstW': ((wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)), wintypes.BOOL),
        'Process32NextW': ((wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)), wintypes.BOOL),
        'OpenProcess': ((wintypes.DWORD, wintypes.BOOL, wintypes.DWORD), wintypes.HANDLE),
        'QueryFullProcessImageNameW': ((wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)), wintypes.BOOL),
        'GetProcessTimes': ((wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4, wintypes.BOOL),
        'GetSystemTimePreciseAsFileTime': ((ctypes.POINTER(wintypes.FILETIME),), None),
        'WaitForSingleObject': ((wintypes.HANDLE, wintypes.DWORD), wintypes.DWORD),
        'CloseHandle': ((wintypes.HANDLE,), wintypes.BOOL),
    }
    for name, (arguments, result) in bindings.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def valid_pid(pid):
    assert type(pid) is int and 0 < pid <= 0xffffffff, 'Native process PID must fit a positive DWORD'
    return pid


def process_identity(kernel, handle, evidence=None):
    buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
    if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    if evidence is not None: evidence.update(nativeImage=buffer.value, nativeImageLength=int(size.value))
    assert 0 < size.value < 32768 and len(buffer.value.encode('utf-16-le', errors='surrogatepass')) // 2 == size.value, 'Native process image path is invalid or truncated'
    creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    created = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
    if evidence is not None:
        evidence['nativeCreation'] = {'low': int(creation.dwLowDateTime), 'high': int(creation.dwHighDateTime), 'fileTime': created}
    assert 0 < created <= 0xffffffffffffffff, 'Native process creation FILETIME is invalid'
    return Path(buffer.value).resolve(), created


def _hwp_child_process(shell_pid, executable, *, shell_creation, evidence=None):
    # A native snapshot avoids starting PowerShell and WMI just to observe an
    # already-owned child. Only exact PPID/name/image matches become witnesses.
    observed = evidence if evidence is not None else {}
    observed.update(schemaVersion=1, kind='native-hwp-child-census', clockApi='GetSystemTimePreciseAsFileTime',
                    shellPid=shell_pid, shellCreationFileTime=shell_creation, expectedExecutable=str(executable.resolve()),
                    snapshotClock={}, snapshotHandleCreated=False, snapshotClosed=False, enumerationComplete=False,
                    candidates=[], match=None, success=False)
    try:
        valid_pid(shell_pid)
        assert type(shell_creation) is int and 0 < shell_creation <= 0xffffffffffffffff, 'Retained Suite creation FILETIME is required'
        kernel = hwp_kernel()
        clock = wintypes.FILETIME()
        # This UTC boundary needs finer resolution than the ordinary system-time
        # API provides. Precise UTC is still a wall clock; inverted bounds fail
        # closed and retain their original values rather than applying tolerance.
        kernel.GetSystemTimePreciseAsFileTime(ctypes.byref(clock))  # VOID, not a success/error return.
        snapshot_started = (int(clock.dwHighDateTime) << 32) | int(clock.dwLowDateTime)
        observed['snapshotClock'] = {'low': int(clock.dwLowDateTime), 'high': int(clock.dwHighDateTime), 'fileTime': snapshot_started}
        observed['snapshotStartedFileTime'] = snapshot_started
        assert shell_creation <= snapshot_started <= 0xffffffffffffffff, 'Native snapshot timestamp precedes the retained Suite shell'
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS; read only.
        observed['snapshotHandleCreated'] = bool(snapshot and snapshot != ctypes.c_void_p(-1).value)
        if not observed['snapshotHandleCreated']: raise ctypes.WinError(ctypes.get_last_error())
        matches = []
        try:
            entry = ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            present = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while present:
                parent_matches = int(entry.th32ParentProcessID) == shell_pid
                name_matches = entry.szExeFile.casefold() == executable.name.casefold()
                candidate = None
                if parent_matches or name_matches:
                    candidate = {'pid': int(entry.th32ProcessID), 'parentPid': int(entry.th32ParentProcessID),
                        'snapshotExeName': entry.szExeFile, 'parentMatches': parent_matches, 'nameMatches': name_matches,
                        'queryAttempted': False, 'handleOpened': False, 'handleClosed': False, 'matched': False}
                    observed['candidates'].append(candidate)
                if parent_matches and name_matches:
                    pid = valid_pid(int(entry.th32ProcessID))
                    candidate['queryAttempted'] = True
                    handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION.
                    candidate['handleOpened'] = bool(handle)
                    if not handle: raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        image, created = process_identity(kernel, handle, candidate)
                        candidate.update(image=str(image), creationFileTime=created, imageMatches=image == executable.resolve(),
                                         generationWithinSnapshot=shell_creation <= created <= snapshot_started)
                        # Reject a recycled PID opened after the snapshot, and a
                        # process whose generation predates the retained shell.
                        candidate['matched'] = bool(candidate['imageMatches'] and candidate['generationWithinSnapshot'])
                        if candidate['matched']:
                            matches.append({'pid': pid, 'parentPid': shell_pid, 'executable': str(image), 'creationFileTime': created})
                    except Exception as exc:
                        candidate['error'] = type(exc).__name__ + ': ' + str(exc)
                        raise
                    finally:
                        candidate['handleClosed'] = bool(kernel.CloseHandle(handle))
                        if not candidate['handleClosed']: raise ctypes.WinError(ctypes.get_last_error())
                present = kernel.Process32NextW(snapshot, ctypes.byref(entry))
            if ctypes.get_last_error() != 18: raise ctypes.WinError(ctypes.get_last_error())  # ERROR_NO_MORE_FILES.
            observed['enumerationComplete'] = True
        finally:
            observed['snapshotClosed'] = bool(kernel.CloseHandle(snapshot))
            if not observed['snapshotClosed']: raise ctypes.WinError(ctypes.get_last_error())
        assert len(matches) <= 1, 'Bundled HWP launch produced multiple matching child processes'
        observed.update(match=matches[0] if matches else None, success=True)
        require_hwp_census_receipt(observed, shell_pid, shell_creation, executable.resolve())
        return dict(observed['match']) if observed['match'] else None
    except Exception as exc:
        observed.update(success=False, error=type(exc).__name__ + ': ' + str(exc))
        raise


def require_hwp_census_receipt(receipt, shell_pid, shell_creation, executable):
    """Replay a completed precise-clock census without native APIs or host ABI assumptions."""
    assert receipt['schemaVersion'] == 1 and receipt['kind'] == 'native-hwp-child-census'
    assert receipt['success'] is True and 'error' not in receipt
    assert receipt['clockApi'] == 'GetSystemTimePreciseAsFileTime'
    valid_pid(shell_pid)
    assert receipt['shellPid'] == shell_pid and receipt['shellCreationFileTime'] == shell_creation
    assert type(shell_creation) is int and 0 < shell_creation <= 0xffffffffffffffff
    expected = PureWindowsPath(str(executable))
    assert Path(str(executable)).is_absolute() or expected.is_absolute(), 'Expected HWP executable must be absolute'
    assert PureWindowsPath(receipt['expectedExecutable']) == expected
    def filetime(raw):
        assert all(type(raw[key]) is int and 0 <= raw[key] <= 0xffffffff for key in ('low', 'high'))
        combined = (raw['high'] << 32) | raw['low']
        assert type(raw['fileTime']) is int and raw['fileTime'] == combined
        return combined
    started = filetime(receipt['snapshotClock'])
    assert type(receipt['snapshotStartedFileTime']) is int and receipt['snapshotStartedFileTime'] == started
    assert shell_creation <= started <= 0xffffffffffffffff
    assert receipt['snapshotHandleCreated'] is receipt['snapshotClosed'] is receipt['enumerationComplete'] is True
    matches = []
    for candidate in receipt['candidates']:
        parent = candidate['parentPid'] == shell_pid
        name = candidate['snapshotExeName'].casefold() == expected.name.casefold()
        assert parent or name, 'Census contains a process outside its recorded candidate scope'
        assert candidate['parentMatches'] is parent and candidate['nameMatches'] is name
        assert candidate['queryAttempted'] is bool(parent and name)
        if not (parent and name):
            assert candidate['handleOpened'] is candidate['handleClosed'] is candidate['matched'] is False
            continue
        valid_pid(candidate['pid'])
        assert candidate['handleOpened'] is candidate['handleClosed'] is True and 'error' not in candidate
        assert 0 < candidate['nativeImageLength'] < 32768
        assert candidate['nativeImageLength'] == len(candidate['nativeImage'].encode('utf-16-le', errors='surrogatepass')) // 2
        created = filetime(candidate['nativeCreation'])
        assert type(candidate['creationFileTime']) is int and candidate['creationFileTime'] == created and created > 0
        image_matches = PureWindowsPath(candidate['image']) == expected
        assert PureWindowsPath(candidate['nativeImage']) == PureWindowsPath(candidate['image'])
        within = shell_creation <= created <= started
        assert candidate['imageMatches'] is image_matches and candidate['generationWithinSnapshot'] is within
        assert candidate['matched'] is bool(image_matches and within)
        if candidate['matched']:
            matches.append({'pid': candidate['pid'], 'parentPid': shell_pid, 'executable': candidate['image'], 'creationFileTime': created})
    assert len(matches) <= 1, 'Census contains multiple matching generations'
    assert receipt['match'] == (matches[0] if matches else None), 'Selected census match differs from raw candidate identity'
    return receipt['match']


class BoundHwpProcess:
    def __init__(self, pid, executable, *, expected_creation=None):
        self.pid = valid_pid(pid)
        self.kernel = hwp_kernel()
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        try:
            image, self.creation = process_identity(self.kernel, self.handle)
            assert image == executable.resolve(), 'Owned process executable changed before binding its native handle'
            if expected_creation is not None:
                assert self.creation == expected_creation, 'HWP process creation changed before binding its native handle'
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
        case.record['stage'] = 'hwpx-route-native-readiness' if path else 'hwp-tile-native-readiness'
        shell_executable = case.suite / 'OpenGeul.Office.exe'
        shell_bound = BoundHwpProcess(shell.pid, shell_executable)
        try:
            assert shell.poll() is None and shell_bound.live(), 'Owned Suite shell exited before HWP child binding'
            # Popen retains the actual launched process handle. Compare creation
            # time so a recycled numeric PID cannot substitute another process.
            assert process_identity(shell_bound.kernel, int(shell._handle))[1] == shell_bound.creation, 'Suite shell creation changed before HWP observation'
            case.record.setdefault('hwpShellWitnesses', []).append({'pid': shell.pid, 'creationFileTime': shell_bound.creation,
                                                                   'executable': str(shell_executable)})
            matched_census_index = None
            def owned_child():
                nonlocal matched_census_index
                assert shell_bound.live(), 'Retained Suite shell exited during child census'
                censuses = case.record.setdefault('hwpNativeCensus', [])
                census = {'observation': len(censuses) + 1}
                censuses.append(census)  # Retain even an early native clock/binding failure.
                observed = _hwp_child_process(shell.pid, executable, shell_creation=shell_bound.creation, evidence=census)
                assert shell_bound.live(), 'Retained Suite shell exited after child census'
                if observed: matched_census_index = census['observation']
                return observed
            observation = native.wait_for(owned_child, 45)
            pid = observation['pid']
            bound = BoundHwpProcess(pid, executable, expected_creation=observation['creationFileTime'])
            case.record.setdefault('ownedHwpPids', []).append(pid)
        except Exception:
            shell_bound.close()
            raise
        try:
            trace_seen = set()
            trace_name = case.name + '-hwpx-route-readiness.jsonl'
            def ready():
                assert bound.live(), 'Bound bundled HWP process exited before native readiness'
                roots = [hwnd for hwnd in case.api.windows(pid) if case.api.class_name(hwnd) in ('Tauri Window', 'Chrome_WidgetWin_1')]
                assert len(roots) <= 1, 'Bundled HWP editor root is ambiguous'
                if not roots: return None
                hwnd = roots[0]
                tree = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
                children = tree.descendants()
                webviews = [child for child in children if child.class_name() in ('Chrome_WidgetWin_0', 'Chrome_WidgetWin_1', 'Chrome_RenderWidgetHostHWND')]
                if not webviews: return None
                accessible = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
                rows = hwp_accessibility_snapshot(accessible) if path else None
                labels = [row['name'] for row in rows] if path else accessibility_names(accessible)
                case.record['hwpReadiness'] = {'hwnd': int(hwnd), 'pid': pid, 'webviewHwnds': [int(child.handle) for child in webviews],
                                             'labelCount': len(labels), 'filenameObserved': path is None or any(path.name in text for text in [case.api.title(hwnd)] + labels)}
                if path:
                    serialized = json.dumps(rows, ensure_ascii=False, sort_keys=True, allow_nan=False)
                    signature = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
                    if signature not in trace_seen:
                        trace_seen.add(signature)
                        with (case.output / trace_name).open('a', encoding='utf-8') as trace:
                            trace.write(json.dumps({'observation': len(trace_seen), 'hwnd': int(hwnd), 'pid': pid,
                                'rowsSha256': signature, 'rows': rows}, ensure_ascii=False, allow_nan=False) + '\n')
                    case.record['hwpReadinessEvidence'] = trace_name
                if path and not any(path.name in text for text in [case.api.title(hwnd)] + labels): return None
                if path:
                    postload = hwp_postload_observation(rows)
                    if postload is None: return None
                    case.record.update(postLoadEditorVerified=True, toolbarEnabled=True, hwpEditorControls=postload)
                return hwnd, [int(child.handle) for child in webviews], labels
            hwnd, webviews, labels = native.wait_for(ready, 75)
            case.screenshot(hwnd, 'hwpx-route' if path else 'hwp-tile')
            launches.append({'pid': pid, 'parentPid': shell.pid, 'creationFileTime': bound.creation,
                             'parentCreationFileTime': shell_bound.creation, 'executable': str(executable), 'hwnd': int(hwnd),
                             'censusObservation': matched_census_index,
                             'webviewHwnds': webviews, 'title': case.api.title(hwnd), 'routedFile': path.name if path else None,
                             'filenameObserved': path is None or any(path.name in text for text in [case.api.title(hwnd)] + labels)})
            case.api.request_close(hwnd, pid)
            native.wait_for(lambda: not case.api.user.IsWindow(hwnd), 25)
            native.wait_for(lambda: not bound.live(), 25)
        except Exception as exc:
            # Bound process and exact packaged executable were verified above.
            # Capture the actual HWP surface before failure cleanup closes it.
            native.capture_failure(case.output, case.name + ('-hwpx-route' if path else '-hwp-tile'), case.record, exc)
            bound.stop()
            raise
        finally:
            try: bound.close()
            finally: shell_bound.close()

    buttons = [item for item in Desktop(backend='uia').window(handle=home).descendants(control_type='Button')
               if item.element_info.name == 'OpenGeul HWP' and item.element_info.process_id == case.process.pid]
    assert len(buttons) == 1, 'Exact owned HWP tile must be unique'
    native.activate_owned_suite(case.api, case.process, home, case.record)
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
