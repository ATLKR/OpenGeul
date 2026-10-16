"""One physical Writer Heading 1 shortcut, Suite Save and independent UNO reopen.

Only a fresh copy of a generated engine fixture is edited. This checks that
style commands remain usable after private toolbar customization; it does not
certify the Styles Preview gallery or other notebookbar modes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lifecycle_smoke as lifecycle
import native_accessibility as accessible
import startup_smoke as startup
import windows_smoke as native

WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
CASE = 'writer-heading1'
COPY = 'fixtures/writer-heading1.docx'


def docx_style_evidence(path):
    evidence = lifecycle.writer_evidence(path)
    with zipfile.ZipFile(path) as package:
        root = ET.fromstring(package.read('word/document.xml'))
    first = root.find('w:body/w:p', {'w': WORD_NS})
    assert first is not None, 'Writer fixture has no first body paragraph'
    style = first.find('w:pPr/w:pStyle', {'w': WORD_NS})
    evidence['firstParagraphStyleId'] = style.get('{' + WORD_NS + '}val') if style is not None else None
    return evidence


def require_saved_style(baseline, saved):
    assert baseline['firstParagraphStyleId'] != 'Heading1', 'Writer baseline already has Heading1; shortcut would not prove a change'
    assert saved['firstParagraphStyleId'] == 'Heading1', 'Saved first paragraph must have exact DOCX pStyle Heading1'
    assert saved['bodyText'] == baseline['bodyText'], 'Style-only keyboard input changed the original body text'
    assert saved['sha256'] != baseline['sha256'], 'Style shortcut did not change saved DOCX bytes'
    return saved


def saved_style_ready(baseline, saved):
    # Suite Save is asynchronous. The untouched original is a pending state;
    # changed but incorrect style/text evidence must still fail immediately.
    if saved['sha256'] == baseline['sha256']:
        return None
    return require_saved_style(baseline, saved)


def require_uno_style(expected, observed, before, after):
    assert before == expected['sha256'], 'Saved bytes changed before independent packaged UNO reopen'
    assert after == before, 'Read-only packaged UNO reopen changed saved bytes'
    text = observed['bodyText'].replace('\r\n', '\n').replace('\r', '\n')
    assert text == expected['bodyText'], 'Independent UNO body text differs from the saved DOCX body'
    assert observed['firstParagraphParaStyleName'] == 'Heading 1', 'Independent UNO first paragraph must have exact ParaStyleName Heading 1'
    return {**observed, 'bodyText': text, 'beforeSha256': before, 'afterSha256': after}


def owned_saved_path(output, record):
    assert record.get('copiedFixture') == COPY, 'Saved style target must be the fixed owned generated fixture'
    path = output / COPY
    for item in (output, path.parent, path): lifecycle.unlinked(item)
    assert path.is_file() and path.resolve().parent == (output / 'fixtures').resolve(), 'Saved style fixture escaped its owned directory'
    return path.resolve()


def click_suite_save(api, process, hwnd, record):
    from pywinauto import Desktop
    window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
    window.set_focus()
    api.require_foreground(hwnd)
    root = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
    files = [item for item in root.descendants(control_type='MenuItem')
             if item.element_info.name == '파일' and item.element_info.process_id == process.pid
             and item.is_visible() and item.is_enabled()]
    assert len(files) == 1, 'One exact shell-owned File menu is required'
    files[0].click_input()
    saves = native.wait_for(lambda: lifecycle.owned_menu_items(Desktop(backend='uia'), process.pid, '저장'), 10)
    assert len(saves) == 1, 'One exact shell-owned Save menu item is required'
    assert process.poll() is None and api.pid(hwnd) == process.pid, 'Owned Suite window changed before Save'
    api.require_foreground(hwnd)
    record['saveMenuRuntimeId'] = list(saves[0].element_info.runtime_id)
    saves[0].click_input()
    record['savedViaOwnedSuiteMenu'] = True


def require_office_exit(code):
    # NativeOffice.cleanup may normally end its private Windows job with code1
    # (OwnedOfficeProcess.terminate); native exception statuses never qualify.
    assert type(code) is int and code in (0, 1), 'Owned Office engine has an unexpected native exit status: ' + str(code)
    return code


def close_engine_witness(engine, record):
    try:
        record['officeExitedAfterCleanup'] = engine.exited(5)
        if not record['officeExitedAfterCleanup']:
            record.setdefault('engineCleanupErrors', []).append('Owned Writer engine survived bounded cleanup')
    except Exception as exc:
        record.setdefault('engineCleanupErrors', []).append(type(exc).__name__ + ': ' + str(exc))
    finally:
        try: engine.close()
        except Exception as exc:
            record.setdefault('engineCleanupErrors', []).append(type(exc).__name__ + ': ' + str(exc))
    if record.get('engineCleanupErrors'):
        record.setdefault('error', '; '.join(record['engineCleanupErrors']))
        record.update(success=False, guiVerified=False)


def run_gui(suite, fixtures, output):
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    record = dict(case=CASE, module='writer', kind='native-writer-style', success=False,
                  guiVerified=False, stage='verify-generated-fixture', copiedFixture=COPY,
                  inputMethod='physical-keyboard', unicodeInputUsed=False,
                  keyboardKeys=['CTRL+HOME', 'CTRL+1'], stderrLog=CASE + '-stderr.log')
    process = engine = original = None
    started = time.monotonic()
    try:
        original = native.require_engine_fixture(fixtures, 'writer', 'docx')
        original_sha = lifecycle.digest(original)
        source = lifecycle.owned_target(output / 'fixtures', 'writer-heading1.docx')
        shutil.copyfile(original, source)
        baseline = docx_style_evidence(source)
        assert baseline['firstParagraphStyleId'] != 'Heading1', 'Generated baseline already has Heading1'
        assert lifecycle.digest(source) == original_sha, 'Owned style fixture differs from generated original'
        record.update(originalFixture=str(original), originalSha256=original_sha, baseline=baseline)
        record['stage'] = 'launch'
        process = native.launch_suite([str(suite / 'OpenGeul.Office.exe'), '--module', 'writer', '--file', str(source)], suite, output, CASE)
        api = native.Windows()
        record['shellPid'] = process.pid
        record['stage'] = 'attach'
        hwnd, parent, child, pid = native.verified_attachment(api, process, 'writer')
        initial = startup.EngineProcessWitness(pid)
        try:
            api, engine = accessible._owned_process(child, pid, initial.creation_time, suite / 'Office/program/soffice.bin')
        finally:
            initial.close()
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=pid,
                      officeCreationTime=engine.creation_time, retainedProcessVerified=True,
                      engineImageVerified=True, nativeParentVerified=True)
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        window.set_focus()
        api.require_foreground(hwnd)
        record['stage'] = 'focus-editor'
        native.prepare_editor_focus(api, hwnd, child, process.pid, pid, record,
            lambda: Desktop(backend='win32').window(handle=child).wrapper_object().click_input(),
            lambda: send_keys('^{F6}', pause=0.1, vk_packet=False))
        record['stage'] = 'physical-heading1-shortcut'
        send_keys('^{HOME}', pause=0.1, vk_packet=False)
        api.require_editor_focus(hwnd, child)
        send_keys('^1', pause=0.1, vk_packet=False)
        record['keyboardFocusHwnd'] = api.require_editor_focus(hwnd, child)
        native.wait_for(lambda: api.title(hwnd).startswith('* '), 12)
        assert not engine.exited(0), 'Owned Writer engine exited during physical style input'
        record['physicalStyleShortcutSent'] = True
        record['stage'] = 'save-via-suite-menu'
        click_suite_save(api, process, hwnd, record)
        def persisted():
            evidence = docx_style_evidence(source)
            return saved_style_ready(baseline, evidence)
        record['savedDocument'] = native.wait_for(persisted, 35)
        native.wait_for(lambda: not api.title(hwnd).startswith('* '), 12)
        record.update(docxHeading1Verified=True, textUnchanged=True)
        record['stage'] = 'capture-saved-editor'
        filename = CASE + '-saved.png'
        window.capture_as_image().save(output / filename)
        record.update(screenshot=filename, screenshotCaptured=True)
        assert api.user.IsWindow(child) and api.pid(child) == pid and not engine.exited(0), 'Owned editor identity changed after style Save'
        assert not api.windows(pid), api.external_window_message(pid, 'Writer created an external visible Office window')
        record['noExternalOfficeWindow'] = True
        native.close_document(api, process, hwnd, child, record)
        native.close_home(api, process, record)
        record['officeExited'] = engine.exited(10)
        assert record['officeExited'], 'Owned Writer engine survived normal Suite shutdown'
        record['officeExitCode'] = engine.code()
        require_office_exit(record['officeExitCode'])
        final = docx_style_evidence(source)
        require_saved_style(baseline, final)
        assert final['sha256'] == record['savedDocument']['sha256'], 'Saved style bytes changed during GUI close'
        record['originalFixtureUnchanged'] = lifecycle.digest(original) == original_sha
        assert record['originalFixtureUnchanged'], 'Style check changed the generated original'
        record.update(guiVerified=True, cleanClose=True, stage='gui-complete')
    except Exception as exc:
        native.capture_failure(output, CASE, record, exc)
    finally:
        if process is not None:
            record['forcedCleanupRequired'] = process.poll() is None
            native.stop_owned_test_process(process, record)
            record['shellExitCode'] = process.poll()
            if record['shellExitCode'] != 0 or record['forcedCleanupRequired'] or record.get('cleanupError'):
                record.update(success=False, guiVerified=False)
        if engine is not None: close_engine_witness(engine, record)
        if original is not None and 'originalSha256' in record:
            record['originalFixtureUnchanged'] = lifecycle.digest(original) == record['originalSha256']
            if not record['originalFixtureUnchanged']: record.update(success=False, guiVerified=False)
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
        native.write_result(output, CASE, record)
    return record


def validate_python_observation(suite_root, observed, inventory):
    """Replay observed interpreter/module paths against the packaged inventory.

    LibreOffice's program/python.exe is a launcher, not sys.executable. Its
    pinned pyuno/zipcore/python.cxx starts python-core-VERSION/bin/python.exe
    with PYTHONHOME set to that core and program + core/lib on PYTHONPATH.
    Pure path validation also lets the delivery verifier replay Windows
    observations against the independently verified extracted payload.
    """
    root = PureWindowsPath(suite_root)
    if not root.is_absolute(): root = PurePosixPath(suite_root)
    assert root.is_absolute(), 'Packaged Python suite root must be absolute'
    assert (isinstance(inventory, dict) and type(inventory.get('schemaVersion')) is int
            and inventory['schemaVersion'] == 1 and inventory.get('architecture') == 'x64'), 'Invalid packaged Python inventory'
    files = inventory.get('files')
    assert isinstance(files, dict), 'Missing packaged Python inventory files'
    cores = [(name, re.fullmatch(r'Office/program/python-core-(\d+)\.(\d+)\.(\d+)/bin/python\.exe', name)) for name in files]
    cores = [(name, match) for name, match in cores if match is not None]
    assert len(cores) == 1, 'Packaged Python requires one unique inventory core interpreter'
    executable, version_match = cores[0]
    version = [int(part) for part in version_match.groups()]
    assert observed.get('implementation') == 'cpython', 'Packaged Python implementation must be CPython'
    assert (isinstance(observed.get('version'), list) and len(observed['version']) == 3
            and all(type(part) is int for part in observed['version']) and observed['version'] == version), 'Packaged Python version differs from inventory core'
    core = executable.rsplit('/bin/', 1)[0]
    paths = {'launcher': 'Office/program/python.exe', 'executable': executable,
             'pythonDll': 'Office/program/python' + str(version[0]) + str(version[1]) + '.dll',
             'uno': 'Office/program/uno.py', 'pyuno': 'Office/program/pyuno.pyd',
             'encodings': core + '/lib/encodings/__init__.py', 'os': core + '/lib/os.py'}
    def exact(actual, relative, description):
        assert isinstance(actual, str) and actual, description + ' path is missing'
        path = type(root)(actual)
        assert path.is_absolute() and path == root / relative, description + ' path differs from packaged identity'
    exact(observed.get('processImage'), executable, 'Native Python process image')
    # LO's launcher deliberately supplies pythonhome as argv[0]. CPython's
    # getpath.py may expose that directory as sys.executable, so retain it as
    # metadata while the native process image above proves executable identity.
    metadata = observed.get('executable')
    assert isinstance(metadata, str) and type(root)(metadata).is_absolute(), 'Python interpreter metadata path is missing'
    assert type(root)(metadata) in (root / core, root / executable), 'Python interpreter metadata differs from the packaged launcher or binary'
    for field in ('prefix', 'basePrefix'): exact(observed.get(field), core, 'Packaged Python ' + field + ' prefix')
    exact(observed.get('pythonDll'), paths['pythonDll'], 'Loaded Python DLL')
    modules, origins = observed.get('moduleFiles'), observed.get('moduleOrigins')
    assert isinstance(modules, dict) and set(modules) == {'uno', 'pyuno', 'encodings', 'os'}, 'Packaged Python module paths are missing'
    assert isinstance(origins, dict) and set(origins) == {'uno', 'pyuno', 'encodings'}, 'Packaged Python module origins are missing'
    for module in modules: exact(modules[module], paths[module], 'Packaged Python ' + module + ' module')
    for module in origins: exact(origins[module], paths[module], 'Packaged Python ' + module + ' import origin')
    return paths


def _packaged_identity_file(suite, relative):
    path = suite / relative
    # Reject junctions/reparse points at every owned ancestor, including the
    # suite root; a path spelling alone does not prove where bytes were read.
    ancestors = [suite] + [suite / item for item in reversed(path.relative_to(suite).parents[:-1])]
    for target in ancestors:
        info = target.lstat()
        assert not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400, 'Packaged Python identity has a linked ancestor'
        assert stat.S_ISDIR(info.st_mode), 'Packaged Python identity ancestor is not a directory'
    info = path.lstat()
    assert not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400, 'Packaged Python identity file is linked'
    assert stat.S_ISREG(info.st_mode), 'Packaged Python identity file is not regular'
    data = path.read_bytes()
    after = path.lstat()
    assert (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'Packaged Python identity changed while reading'
    return {'path': str(path), 'relativePath': relative, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}, data


def require_packaged_python(suite, observed):
    inventory_file, data = _packaged_identity_file(suite, 'suite-inventory.json')
    inventory = json.loads(data)
    paths = validate_python_observation(suite, observed, inventory)
    files = {}
    for role, relative in paths.items():
        actual, _ = _packaged_identity_file(suite, relative)
        expected = inventory['files'].get(relative)
        assert (isinstance(expected, dict) and set(expected) == {'size', 'sha256'}
                and type(expected['size']) is int and expected['size'] > 0
                and isinstance(expected['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', expected['sha256'])
                and actual['size'] == expected['size'] and actual['sha256'] == expected['sha256']), 'Packaged Python identity bytes differ from inventory: ' + relative
        files[role] = actual
    return {'schemaVersion': 1, 'verified': True, 'suiteRoot': str(suite),
            'inventorySha256': inventory_file['sha256'], 'observed': observed, 'files': files}


def _windows_python_images():
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint32
    images = {}
    for name, handle in (('processImage', None), ('pythonDll', sys.dllhandle)):
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetModuleFileNameW(ctypes.c_void_p(handle), buffer, len(buffer))
        assert 0 < length < len(buffer), 'Cannot observe native Python ' + name + ' path'
        images[name] = buffer.value
    return images


def observe_packaged_python():
    import encodings
    import uno
    import pyuno
    modules = {'uno': uno, 'pyuno': pyuno, 'encodings': encodings, 'os': os}
    return {'implementation': sys.implementation.name, 'version': list(sys.version_info[:3]),
            'executable': sys.executable, 'prefix': sys.prefix, 'basePrefix': sys.base_prefix,
            **_windows_python_images(),
            'moduleFiles': {name: module.__file__ for name, module in modules.items()},
            'moduleOrigins': {name: modules[name].__spec__.origin for name in ('uno', 'pyuno', 'encodings')}}


def verify_saved(suite, output):
    from engine_smoke import Engine
    record = json.loads((output / (CASE + '-result.json')).read_text(encoding='utf-8'))
    result = dict(kind='packaged-uno-writer-style-reopen', success=False)
    engine, document = Engine(suite), None
    try:
        assert record.get('guiVerified') is True, 'Actual GUI style edit must pass before UNO reopen'
        result['pythonIdentity'] = {'schemaVersion': 1, 'verified': False, 'suiteRoot': str(suite),
                                    'observed': observe_packaged_python()}
        result['pythonIdentity'] = require_packaged_python(suite, result['pythonIdentity']['observed'])
        path = owned_saved_path(output, record)
        before = lifecycle.digest(path)
        engine.start()
        from dispatch import make_interaction_handler
        props = tuple(engine.prop(name, value) for name, value in (
            ('Hidden', True), ('ReadOnly', True), ('MacroExecutionMode', 0), ('UpdateDocMode', 0),
            ('PickListEntry', False), ('AsTemplate', False), ('InteractionHandler', make_interaction_handler())))
        document = engine.desktop.loadComponentFromURL(path.as_uri(), '_blank', 0, props)
        assert document is not None and document.supportsService('com.sun.star.text.TextDocument'), 'Packaged UNO did not reopen Writer'
        assert document.isReadonly() and not document.isModified(), 'Independent Writer model is not read-only and unchanged'
        paragraphs = document.getText().createEnumeration()
        assert paragraphs.hasMoreElements(), 'Independent Writer model has no first paragraph'
        first = paragraphs.nextElement()
        assert first.supportsService('com.sun.star.text.Paragraph'), 'Independent first body object is not a paragraph'
        observed = dict(bodyText=document.getText().getString(), firstParagraphParaStyleName=first.getPropertyValue('ParaStyleName'))
        result.update(observed=observed, beforeSha256=before, readOnlyModelVerified=True)
        assert not document.isModified(), 'Style observation modified the read-only Writer model'
        document.close(False)
        document = None
        result.update(require_uno_style(record['savedDocument'], observed, before, lifecycle.digest(path)), success=True)
    except Exception as exc:
        native.capture_failure(output, 'packaged-uno-writer-style', result, exc)
    finally:
        if document is not None:
            try: document.close(False)
            except Exception as exc: result.update(success=False, closeError=type(exc).__name__ + ': ' + str(exc))
        engine.cleanup()
        if engine.cleanup_errors: result.update(success=False, cleanupErrors=engine.cleanup_errors)
        if result.get('success'):
            try: assert lifecycle.digest(path) == before, 'UNO process cleanup changed saved bytes'
            except Exception as exc: native.capture_failure(output, 'packaged-uno-writer-style', result, exc)
        native.write_result(output, 'packaged-uno', result)
    return 0 if result['success'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, type=Path)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--verify-saved', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if os.name != 'nt' or not __debug__: raise RuntimeError('Actual Windows execution with assertions is required')
    suite, output = args.suite.resolve(), args.output.resolve()
    if args.verify_saved: return verify_saved(suite, output)
    assert args.fixtures, 'Fresh generated engine fixtures are required'
    lifecycle.unlinked(args.output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'fixtures').mkdir()
    record = run_gui(suite, args.fixtures.resolve(), output)
    if record.get('guiVerified') is True:
        try:
            with (output / 'packaged-uno.log').open('xb') as log:
                verification = subprocess.run([str(suite / 'Office/program/python.exe'), str(Path(__file__).resolve()),
                    '--suite', str(suite), '--output', str(output), '--verify-saved'],
                    cwd=suite, stdout=log, stderr=subprocess.STDOUT, timeout=90, shell=False)
            uno = json.loads((output / 'packaged-uno-result.json').read_text(encoding='utf-8'))
            record.update(packagedUnoExitCode=verification.returncode, packagedUnoEvidence='packaged-uno-result.json',
                          packagedUnoVerified=verification.returncode == 0 and uno.get('success') is True)
            assert record['packagedUnoVerified'], 'Independent packaged UNO Heading 1 reopen failed'
            record['originalFixtureUnchanged'] = lifecycle.digest(Path(record['originalFixture'])) == record['originalSha256']
            assert record['originalFixtureUnchanged'], 'Style reopen changed the generated original'
            record.update(success=True, stage='complete')
        except Exception as exc:
            native.capture_failure(output, CASE, record, exc)
    native.write_result(output, CASE, record)
    report = dict(schemaVersion=1, kind='native-writer-style-regression', success=record['success'], tests=[record])
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('Writer Heading 1: ' + ('passed' if record['success'] else 'FAILED: ' + str(record.get('error'))), flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__': raise SystemExit(main())
