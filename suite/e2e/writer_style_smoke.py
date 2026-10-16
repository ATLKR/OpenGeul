"""One physical Writer Heading 1 shortcut, Suite Save and independent UNO reopen.

Only a fresh copy of a generated engine fixture is edited. This checks that
style commands remain usable after private toolbar customization; it does not
certify the Styles Preview gallery or other notebookbar modes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
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
        Desktop(backend='win32').window(handle=child).wrapper_object().click_input()
        send_keys('^{F6}', pause=0.1, vk_packet=False)
        api.require_editor_focus(hwnd, child)
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
        assert not api.windows(pid), 'Writer created an external visible Office window'
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


def verify_saved(suite, output):
    from engine_smoke import Engine
    record = json.loads((output / (CASE + '-result.json')).read_text(encoding='utf-8'))
    result = dict(kind='packaged-uno-writer-style-reopen', success=False)
    engine, document = Engine(suite), None
    try:
        assert record.get('guiVerified') is True, 'Actual GUI style edit must pass before UNO reopen'
        assert Path(sys.executable).resolve() == (suite / 'Office/program/python.exe').resolve(), 'Independent style reopen requires packaged Python'
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
