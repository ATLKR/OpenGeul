"""Finite native Korean Tabbed UI evidence for four embedded Office modules.

Only copied engine fixtures are opened. One measured editor click and fixed
Ctrl+F6 establish focus; text and save commands are not part of this program.
--probe-only records accessibility without claiming Korean UI verification.
Actual VCL objects are read through the exact owned process's private pipe.
The OS UIA tree is retained separately as diagnostic evidence. Each reader runs
in its own bounded process so a provider cannot hold the Suite lifecycle open.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import startup_smoke as startup
import windows_smoke as native
import native_accessibility as accessible
import writer_os_accessibility as writer_access

MODULES = {'writer': 'docx', 'calc': 'xlsx', 'impress': 'pptx', 'draw': 'odg'}


def normalize_label(value):
    return accessible.normalize_label(value)


def require_korean_tabs(snapshot, office_pid, child):
    return accessible.require_native_tabs(snapshot, office_pid, child, snapshot.get('module'))


def _legacy(wrapper):
    try:
        return wrapper.legacy_properties().get('Role')
    except Exception:
        return None


def capture_controls(child, office_pid):
    from pywinauto import Desktop
    root = Desktop(backend='uia').window(handle=child).wrapper_object()
    assert root.element_info.process_id == office_pid, 'UIA root changed native process ownership'
    wrappers = [root] + root.descendants()
    assert len(wrappers) <= 6000, 'Native accessibility tree exceeds the finite control bound'
    controls = []
    for wrapper in wrappers:
        info = wrapper.element_info
        if info.process_id != office_pid:
            continue  # Do not read or record shell or other-process labels.
        role = _legacy(wrapper)
        item = dict(name=info.name, processId=int(info.process_id), controlType=info.control_type,
                    automationId=info.automation_id, className=info.class_name,
                    runtimeId=list(info.runtime_id or []), legacyRole=role,
                    visible=bool(wrapper.is_visible()))
        rect = info.rectangle
        item['rectangle'] = [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)]
        if info.control_type == 'TabItem' or role == 37:
            parent = wrapper.parent()
            parent_info = parent.element_info
            item.update(parentProcessId=int(parent_info.process_id),
                        parentRuntimeId=list(parent_info.runtime_id or []),
                        parentControlType=parent_info.control_type,
                        parentLegacyRole=_legacy(parent) if parent_info.process_id == office_pid else None)
        controls.append(item)
    return dict(schemaVersion=1, kind='owned-native-accessibility', childHwnd=child,
                officePid=office_pid, rootProcessId=int(root.element_info.process_id),
                controlCount=len(controls), truncated=False, controls=controls)


def _writer_checkpoint(stdout):
    return (type(stdout) is str and stdout.startswith('1\n')
            or type(stdout) is bytes and stdout.startswith((b'1\n', b'1\r\n')))


def capture_bounded(child, office_pid, destination, *, writer_request=None):
    command = [sys.executable, str(Path(__file__).resolve()), '--capture-child', str(child),
               '--office-pid', str(office_pid), '--snapshot', str(destination)]
    if writer_request is None:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, shell=False)
        assert result.returncode == 0, 'Native accessibility collector failed: ' + result.stderr
        return json.loads(destination.read_text(encoding='utf-8'))
    # Same original child and watchdog. Its original UIA snapshot completes
    # before the fixed numeric checkpoint; only later probe failures are held.
    command.extend(['--writer-office-creation-time', str(writer_request['officeCreationTime']),
                    '--writer-office-image', writer_request['expectedImage'], '--writer-msaa'])
    timed_out = False
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace', timeout=45, shell=False)
    except subprocess.TimeoutExpired as exc:
        if not _writer_checkpoint(exc.stdout):
            raise
        timed_out = True
    if timed_out:
        evidence = writer_access.failure(writer_request, 14)
    else:
        if result.returncode != 0:
            assert _writer_checkpoint(result.stdout), 'Native accessibility collector failed: '
            evidence = writer_access.failure(writer_request)
        else:
            evidence = (writer_access.decode(result.stdout[2:], writer_request)
                        if _writer_checkpoint(result.stdout) else writer_access.failure(writer_request))
    snapshot = json.loads(destination.read_text(encoding='utf-8'))
    snapshot['writerOsAccessibility'] = evidence
    return snapshot


def prepare_korean_ui_focus(api,process,hwnd,parent,child,office_pid,module,record):
    """One closed entry program for the four native UI observation modules."""
    assert module in MODULES and record.get('module')==module, 'Unknown Korean UI focus module'
    deadline=time.monotonic()+5
    with native.FirstAdmissionEditorSession(api,process,
            dict(hwnd=hwnd,parent=parent,child=child,officePid=office_pid),
            'KOREAN_UI_ENTRY',record,deadline) as shortcuts:
        focus=native.prepare_editor_focus(api,hwnd,child,process.pid,office_pid,record,
            lambda:native.click_owned_editor(api,process,hwnd,parent,child,office_pid,record),
            lambda:shortcuts.press('CTRL_F6'),seconds=deadline-time.monotonic())
        shortcuts.editor_ready(record['editorFocusReadiness'])
    record.update(keyboardFocusHwnd=focus,nativeInputFocusPrepared=True)
    return focus


def run_case(suite, fixtures, output, module, *, probe_only=False):
    case = 'korean-ui-' + module
    record = dict(case=case, module=module, success=False, stage='verify-fixture',
                  koreanUiVerified=False, tabbedUiVerified=False, cleanClose=False,
                  probeOnly=probe_only, stderrLog=case + '-stderr.log')
    process = api = engine = original = copy = before = None
    started = time.monotonic()
    try:
        original = native.require_engine_fixture(fixtures, module, MODULES[module])
        before = hashlib.sha256(original.read_bytes()).hexdigest()
        copy = output / (case + '-fixture.' + MODULES[module])
        assert not copy.exists(), 'The UI fixture copy must be fresh'
        shutil.copyfile(original, copy)
        record.update(originalFixture=str(original), copiedFixture=copy.name, beforeSha256=before)
        record['stage'] = 'launch'
        process = native.launch_suite([str(suite/'OpenGeul.Office.exe'), '--module', module,
                                       '--file', str(copy)], suite, output, case)
        api = native.Windows()
        record['shellPid'] = process.pid
        record['stage'] = 'attach'
        hwnd, parent, child, office_pid = native.verified_attachment(api, process, module)
        engine = startup.EngineProcessWitness(office_pid)
        record.update(windowHwnd=hwnd, parentHwnd=parent, childHwnd=child, officePid=office_pid,
                      officeCreationTime=engine.creation_time, nativeParentVerified=True)
        from pywinauto import Desktop
        window = Desktop(backend='win32').window(handle=hwnd).wrapper_object()
        window.maximize()
        record['stage'] = 'prepare-owned-native-focus'
        native.activate_owned_suite(api, process, hwnd, record)
        api.require_foreground(hwnd)
        prepare_korean_ui_focus(api,process,hwnd,parent,child,office_pid,module,record)
        record['stage'] = 'capture-screenshot'
        screenshot = case + '-attached.png'
        window.capture_as_image().save(output / screenshot)
        record.update(screenshot=screenshot, screenshotCaptured=True)
        record['stage'] = 'capture-os-accessibility-diagnostic'
        os_name = case + '-os-accessibility.json'
        if module == 'writer':
            writer_request = dict(officePid=office_pid, officeCreationTime=engine.creation_time,
                childHwnd=child, expectedImage=str(suite/'Office/program/soffice.bin'))
            os_snapshot = capture_bounded(child, office_pid, output / os_name, writer_request=writer_request)
            record['writerOsAccessibility'] = os_snapshot.get('writerOsAccessibility',
                writer_access.failure(writer_request))
        else:
            os_snapshot = capture_bounded(child, office_pid, output / os_name)
        record.update(osAccessibilitySnapshot=os_name, osAccessibleControlCount=os_snapshot['controlCount'])
        record['stage'] = 'capture-native-accessible-objects'
        snapshot_name = case + '-accessibility.json'
        snapshot = accessible.capture_bounded(suite, child, office_pid, engine.creation_time,
                                              module, output / snapshot_name)
        assert api.user.IsWindow(child) and api.pid(child) == office_pid, 'Owned editor changed during accessibility capture'
        assert snapshot['module'] == module, 'Native accessible objects belong to another requested module'
        record.update(accessibilitySnapshot=snapshot_name,
                      accessibleControlCount=snapshot['nativeAccessibleContextCount'],
                      osScreenReaderExposureCertified=False)
        assert not api.windows(office_pid), api.external_window_message(office_pid, 'Office created an unowned visible top-level window')
        record['noExternalOfficeWindow'] = True
        if not probe_only:
            record['stage'] = 'assert-korean-tabbed-ui'
            record.update(require_korean_tabs(snapshot, office_pid, child))
            if module == 'writer':
                # Preserve the original VCL collection/tab/focus failure as the
                # primary error. Enforce this new, earlier observation afterward.
                try:
                    writer_evidence = writer_access.validate(record['writerOsAccessibility'], writer_request)
                except Exception:
                    writer_evidence = writer_access.failure(writer_request)
                record['writerOsAccessibility'] = writer_evidence
                record['stage'] = writer_access.failure_stage(writer_evidence)
                assert writer_evidence['verified'] == 1, 'Owned Writer OS accessibility exposure was not verified'
                record['writerOsDocumentExposureVerified'] = True
        record['stage'] = 'close-document'
        calc_proof = None
        if module == 'calc':
            baseline = native.calc_model_barrier.baseline_from_ooxml(original.read_bytes())
            calc_proof = native._verified_saved_calc_close_proof(suite, output, copy, baseline,
                                                               expected_sha256=before, role='korean-ui-copy')
            native.close_document(api, process, hwnd, child, record, calc_close_proof=calc_proof)
        else:
            native.close_document(api, process, hwnd, child, record)
        native.close_home(api, process, record)
        record['stage'] = 'wait-engine-exit'
        record['officeExited'] = engine.exited(10)
        assert record['officeExited'], 'Owned Office engine survived normal shutdown'
        record['officeExitCode'] = engine.code()
        record['stage'] = 'verify-final-fixtures'
        record['fixtureUnchanged'] = hashlib.sha256(copy.read_bytes()).hexdigest() == before
        record['originalFixtureUnchanged'] = hashlib.sha256(original.read_bytes()).hexdigest() == before
        assert record['fixtureUnchanged'] and record['originalFixtureUnchanged'], 'Read-only UI observation changed a generated fixture'
        record.update(success=True, cleanClose=True, stage='complete')
    except Exception as exc:
        native.capture_failure(output, case, record, exc)
        accessible.attach_child_failure(record, exc)
    finally:
        if process is not None:
            record['forcedCleanupRequired'] = process.poll() is None
            native.stop_owned_test_process(process, record)
            record['shellExitCode'] = process.poll()
            if record.get('success') and record['shellExitCode'] != 0:
                record.update(success=False, cleanupError='Owned Suite shell did not exit cleanly')
        if engine is not None:
            try:
                record['officeExitedAfterCleanup'] = engine.exited(5)
                if not record['officeExitedAfterCleanup']:
                    record.update(success=False, cleanupError='Owned Office engine survived bounded cleanup')
            except Exception as cleanup_error:
                record.update(success=False, cleanupError=type(cleanup_error).__name__ + ': ' + str(cleanup_error))
            finally:
                engine.close()
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
        native.write_result(output, case, record)
    return record


def run_modules(suite, fixtures, output, modules, *, probe_only=False):
    records = []
    for module in modules:
        try:
            record = run_case(suite, fixtures, output, module, probe_only=probe_only)
        except Exception as exc:
            record = dict(case='korean-ui-' + module, module=module, success=False)
            native.capture_failure(output, record['case'], record, exc)
            native.write_result(output, record['case'], record)
        records.append(record)
        print(module + ': ' + ('captured' if probe_only and record['success'] else
              'passed' if record['success'] else 'FAILED: ' + str(record.get('error'))), flush=True)
    verified = [record['module'] for record in records if record.get('success') is True
                and record.get('koreanUiVerified') is True and record.get('tabbedUiVerified') is True]
    report = dict(schemaVersion=1, kind='native-korean-ui-probe' if probe_only else 'native-korean-tabbed-ui',
                  success=all(record.get('success') is True for record in records), probeOnly=probe_only,
                  koreanUiVerified=not probe_only and len(verified) == len(modules),
                  expectedModules=list(modules), verifiedModules=verified, tests=records)
    (output/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--modules', choices=tuple(MODULES), nargs='+', default=list(MODULES))
    parser.add_argument('--probe-only', action='store_true')
    parser.add_argument('--capture-child', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--office-pid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--snapshot', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--writer-msaa', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--writer-office-creation-time', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--writer-office-image', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != 'nt' or not __debug__:
        raise RuntimeError('Actual Windows GUI execution with assertions enabled is required')
    if args.capture_child is not None:
        assert args.capture_child > 0 and args.office_pid and args.office_pid > 0 and args.snapshot
        if args.writer_msaa:
            # Existing rich UIA diagnostics are unchanged. Their incidental
            # stdout is discarded by the parent's existing Writer child sink.
            with redirect_stdout(sys.stderr):
                snapshot = capture_controls(args.capture_child, args.office_pid)
        else:
            snapshot = capture_controls(args.capture_child, args.office_pid)
        with args.snapshot.open('x', encoding='utf-8') as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2, allow_nan=False)
        if args.writer_msaa:
            print('1', flush=True)  # Original UIA observation and file close succeeded.
            request = dict(childHwnd=args.capture_child, officePid=args.office_pid,
                officeCreationTime=args.writer_office_creation_time, expectedImage=args.writer_office_image)
            value = writer_access.observe(request)
            encoded = json.dumps(value, separators=(',', ':'), allow_nan=False)
            assert len(encoded.encode('utf-8')) <= 4096, 'Closed Writer result exceeds bound'
            print(encoded, flush=True)
        return 0
    assert args.suite and args.fixtures and args.output, '--suite, --fixtures and --output are required'
    for path in (args.suite, args.fixtures, args.output):
        assert not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'Linked input or evidence directories are not accepted'
    suite, fixtures, output = args.suite.resolve(), args.fixtures.resolve(), args.output.resolve()
    assert suite != output and suite not in output.parents, 'Evidence must be outside the payload'
    assert fixtures != output and fixtures not in output.parents, 'Evidence must be outside generated fixtures'
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output)), 'Only local test paths are accepted'
    assert len(args.modules) == len(set(args.modules)), 'Each module may be observed once'
    output.mkdir(parents=True, exist_ok=False)
    report = run_modules(suite, fixtures, output, args.modules, probe_only=args.probe_only)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
