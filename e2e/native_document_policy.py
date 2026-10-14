"""Draft native observation policy; offline tests are not Windows qualification.

The Windows adapter supplies only read-only observations. These functions never
activate, retarget, retry input, call the document engine, or alter a file.
"""
from __future__ import annotations
import copy
import io
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET
from hwpx_oracle import inspect_hwpx

EDITOR_CLASSES = ('Tauri Window', 'Chrome_WidgetWin_1')
IDENTITY = ('hwnd', 'root', 'pid', 'tid', 'cls', 'owners')
HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
HS = 'http://www.hancom.co.kr/hwpml/2011/section'
# tauri-plugin-dialog 2.7.0 enables rfd 0.16.0 common-controls-v6; these are
# win_cid/message_dialog.rs YesNoCancelCustom IDs, never learned from a dialog.
# Cargo.lock rfd checksum: a15ad77d9e70a92437d8f74c35d99b4e4691128df018833e99f90bcd36152672
UNSAVED_CHOICE_IDS = {'저장': 1004, '저장 안 함': 1008, '취소': 1001}

def _window(row, *, ready=True):
    if not isinstance(row, dict):
        raise AssertionError('Missing actual native window observation')
    if any(type(row.get(key)) is not int or row[key] <= 0 for key in ('hwnd', 'root', 'pid', 'tid')):
        raise AssertionError('Native HWND/PID/thread/root must be positive integers')
    if (not isinstance(row.get('cls'), str) or not row['cls'] or len(row['cls']) > 128
            or type(row.get('visible')) is not bool or type(row.get('enabled')) is not bool):
        raise AssertionError('Native class/readiness observation is invalid')
    owners = row.get('owners')
    if (not isinstance(owners, list) or len(owners) > 8
            or any(type(value) is not int or value <= 0 for value in owners)
            or len(set(owners)) != len(owners) or row['hwnd'] in owners):
        raise AssertionError('Native owner chain is invalid or cyclic')
    if ready and (not row['visible'] or not row['enabled']):
        raise AssertionError('Exact native input window is not ready')
    return row

def _identity(row):
    _window(row, ready=False)
    return {key: copy.deepcopy(row[key]) for key in IDENTITY}

def choose_editor_hwnd(before, after, app_pid):
    if type(app_pid) is not int or app_pid <= 0:
        raise AssertionError('Expected owned native process is invalid')
    for rows in (before, after):
        if not isinstance(rows, list) or len(rows) > 32:
            raise AssertionError('Native editor inventory is missing or unbounded')
        seen = set()
        for row in rows:
            _window(row)
            if (row['pid'] != app_pid or row['root'] != row['hwnd']
                    or row['cls'] not in EDITOR_CLASSES or row['owners'] or row['hwnd'] in seen):
                raise AssertionError('Native editor inventory is foreign or ambiguous')
            seen.add(row['hwnd'])
    previous = {row['hwnd'] for row in before}
    current = {row['hwnd'] for row in after}
    if not previous.issubset(current):
        raise AssertionError('Existing owned editor disappeared while creating a new window')
    for row in before:
        actual = next(value for value in after if value['hwnd'] == row['hwnd'])
        if _identity(row) != _identity(actual):
            raise AssertionError('Existing owned editor changed while creating a new window')
    new = current - previous
    if len(new) != 1:
        raise AssertionError('Exactly one new owned native HWND is required')
    return new.pop()

def require_editor(row, expected):
    _window(row)
    if (row['root'] != row['hwnd'] or row['cls'] not in EDITOR_CLASSES or row['owners']
            or _identity(row) != _identity(expected)):
        raise AssertionError('Bound native editor identity changed')
    return row

def require_hit(hit, editor, allowed_pids):
    _window(hit)
    _window(editor)
    if (hit['root'] != editor['hwnd'] or hit['pid'] not in allowed_pids):
        raise AssertionError('Native input point is outside the exact held editor')
    return hit

def require_focus_map(page_key, rows):
    if not isinstance(rows, list) or not rows or len(rows) > 32:
        raise AssertionError('Actual live document-page focus inventory is missing')
    keys = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'pageKey', 'focused'}
                or not isinstance(row['pageKey'], str) or not row['pageKey'] or len(row['pageKey']) > 64
                or type(row['focused']) is not bool):
            raise AssertionError('Actual document-page focus observation is invalid')
        keys.append(row['pageKey'])
    if len(set(keys)) != len(keys) or page_key not in keys:
        raise AssertionError('Document-page mapping is duplicate or missing')
    if [row['pageKey'] for row in rows if row['focused']] != [page_key]:
        raise AssertionError('Foreground native editor does not map to the exact document page')
    return rows

def require_owned_dialog(row, editor, editor_hwnds):
    _window(row)
    _window(editor, ready=False)  # Modal disables its exact parent editor.
    if (row['root'] != row['hwnd'] or row['cls'] != '#32770' or row['pid'] != editor['pid']
            or not row['owners']):
        raise AssertionError('Native dialog is not an owned root dialog')
    editor_owners = [hwnd for hwnd in row['owners'] if hwnd in editor_hwnds]
    if editor_owners != [editor['hwnd']]:
        raise AssertionError('Native dialog belongs to another editor or has no exact owner')
    return row

def require_filename_control(child, combo, dialog):
    """Require the exact ready Win32 Edit/ComboBox route within a held picker."""
    for row in (child, combo, dialog):
        _window(row)
    if (child['cls'] != 'Edit' or combo['cls'] != 'ComboBox'
            or child['hwnd'] in (combo['hwnd'], dialog['hwnd'])
            or combo['hwnd'] == dialog['hwnd']
            or any(row['root'] != dialog['hwnd'] or row['pid'] != dialog['pid']
                   or row['tid'] != dialog['tid'] or row['owners'] != dialog['owners']
                   for row in (child, combo))):
        raise AssertionError('Native filename Edit/ComboBox identity is outside the exact owned picker')
    return child

def double_checked_action(read, action):
    before = copy.deepcopy(read())
    if read() != before:
        raise AssertionError('Owned input target changed immediately before input')
    action(before)
    return before

def require_dialog_action(actual, expected):
    keys = {'controlId', 'label', 'title', 'promptText'}
    for row in (actual, expected):
        if (not isinstance(row, dict) or set(row) != keys
                or type(row['controlId']) is not int or row['controlId'] <= 0
                or not isinstance(row['label'], str) or not row['label'] or len(row['label']) > 128
                or not isinstance(row['title'], str) or not row['title'] or len(row['title']) > 128
                or row['promptText'] is not None and (not isinstance(row['promptText'], str)
                    or not row['promptText'] or len(row['promptText']) > 4096)):
            raise AssertionError('Expected native dialog action semantics are invalid')
    if actual != expected:
        raise AssertionError('Native dialog action label, ID, title or document prompt changed')
    return actual

def unsaved_dialog_action(choice, document_name):
    if (choice not in UNSAVED_CHOICE_IDS or not isinstance(document_name, str)
            or not document_name or len(document_name) > 512
            or any(character in document_name for character in ('\r', '\n', '\0'))):
        raise AssertionError('Expected unsaved-document choice/name is invalid')
    return {'controlId': UNSAVED_CHOICE_IDS[choice], 'label': choice, 'title': '저장 확인',
            'promptText': f'{document_name}의 변경 내용을 저장할까요?'}

def assert_body_markers(data, required, forbidden=(), exact_text=None):
    raw = data.read_bytes() if isinstance(data, Path) else data
    inspection = inspect_hwpx(raw)
    required, forbidden = tuple(required), tuple(forbidden)
    if (not required or len(set(required)) != len(required)
            or any(not isinstance(marker, str) or not marker or len(marker) > 512
                   for marker in (*required, *forbidden))):
        raise AssertionError('Expected body markers must be nonempty and bounded')
    paragraphs = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        sections = sorted((name for name in archive.namelist()
                           if re.fullmatch(r'Contents/section\d+\.xml', name)),
                          key=lambda name: int(re.search(r'(\d+)\.xml$', name)[1]))
        for name in sections:
            section = ET.fromstring(archive.read(name))
            if section.tag != f'{{{HS}}}sec':
                raise AssertionError('Saved section uses an unexpected XML namespace')
            for paragraph in section:
                if paragraph.tag != f'{{{HP}}}p':
                    continue
                paragraphs.append(''.join(node.text or '' for run in paragraph
                    if run.tag == f'{{{HP}}}run' for node in run if node.tag == f'{{{HP}}}t'))
    body = '\n'.join(paragraphs)
    for marker in required:
        if body.count(marker) != 1 or inspection['text'].count(marker) != 1:
            raise AssertionError('Saved marker is missing, duplicated, or outside the direct document body')
    if any(marker in inspection['text'] for marker in forbidden):
        raise AssertionError('Saved document contains another document or replaced-source marker')
    if exact_text is not None and body != exact_text:
        raise AssertionError('Saved new-document body does not exactly match the entered text')
    return {**inspection, 'bodyText': body, 'bodyParagraphs': paragraphs}
