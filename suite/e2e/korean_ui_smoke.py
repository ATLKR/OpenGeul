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
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import startup_smoke as startup
import windows_smoke as native
import native_accessibility as accessible
import writer_os_accessibility as writer_access

MODULES = {'writer': 'docx', 'calc': 'xlsx', 'impress': 'pptx', 'draw': 'odg'}
_ROOT_DIAGNOSTIC_PENDING = []  # At most one owned child/file pair; never serialized.


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
    if _WRITER_CAPTURE_PENDING:raise WriterCapturePending()
    command = [sys.executable, str(Path(__file__).resolve()), '--capture-child', str(child),
               '--office-pid', str(office_pid), '--snapshot', str(destination)]
    if writer_request is None:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, shell=False)
        assert result.returncode == 0, 'Native accessibility collector failed: ' + result.stderr
        return json.loads(destination.read_text(encoding='utf-8'))
    # Same original child and watchdog. Its original UIA snapshot completes
    # before the fixed numeric checkpoint; only later probe failures are held.
    # This cap begins before the same original 45-second subprocess watchdog.
    # The child may consume only what remains; it never starts another budget.
    command.extend(['--writer-msaa-deadline', repr(time.monotonic() + 45)])
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


def capture_writer_msaa_after_native(request, deadline):
    """One numeric-only observation within the original native reader budget."""
    if _WRITER_CAPTURE_PENDING:raise WriterCapturePending()
    evidence = dict(schemaVersion=1, acceptanceEligible=False, attempted=False,
        completedWithinBudget=False, timeoutSeconds=0,
        result=writer_access.failure(request))
    try:
        command = [sys.executable, str(Path(__file__).resolve()), '--writer-msaa-only',
            '--capture-child', str(request['childHwnd']), '--office-pid', str(request['officePid']),
            '--writer-office-creation-time', str(request['officeCreationTime']),
            '--writer-office-image', request['expectedImage']]
        now = time.monotonic()
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline > now + 45:
            return evidence
        if deadline <= now:
            evidence['result'] = writer_access.failure(request, 14)
            return evidence
        timeout = min(8., deadline - now)
        command.extend(['--writer-msaa-deadline', repr(now + timeout)])
        evidence.update(attempted=True, timeoutSeconds=timeout)
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace', timeout=timeout, shell=False)
        if result.returncode == 0:
            evidence['result'] = writer_access.decode(result.stdout, request)
        if time.monotonic() >= deadline:
            evidence['result'] = writer_access.failure(request, 14)
        else:
            evidence['completedWithinBudget'] = True
    except subprocess.TimeoutExpired:
        evidence['result'] = writer_access.failure(request, 14)
    except Exception:
        evidence['result'] = writer_access.failure(request)  # Keep the original gate primary.
    return evidence


def capture_writer_root_diagnostic(request, deadline, *, enabled=True):
    """Later fresh-root capabilities; never evidence about the primary object.

    No pipe reader/communicate join can outlive the wait deadline. Synchronous
    file/CreateProcess/kill calls themselves cannot be forcibly preempted; late
    outcomes stay unknown. Unretired child/file pairs remain caller-reachable
    in the bounded module registry and prevent another diagnostic launch.
    """
    if _WRITER_CAPTURE_PENDING:raise WriterCapturePending()
    evidence = dict(schemaVersion=1, diagnosticOnly=True, acceptanceEligible=False,
        freshRootLater=True, attempted=False, completedWithinBudget=False, timeoutSeconds=0,
        requestValid=False, cleanupConfirmed=True, retainedPending=False, launchOutcomeUnknown=False, result={})
    child = output = None
    exited = False
    child_deadline = None
    try:
        evidence['result'] = writer_access.root_diagnostic_failure(request, 15)
        evidence['requestValid'] = True
        request = dict(request)
        if type(enabled) is not bool:
            evidence['result'] = writer_access.root_diagnostic_failure(request)
            return evidence
        if _ROOT_DIAGNOSTIC_PENDING:
            evidence.update(cleanupConfirmed=False, retainedPending=True)
            return evidence
        if not enabled:
            return evidence
        now = time.monotonic()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or deadline > now + 45 or deadline <= now):
            return evidence
        timeout = min(8., deadline - now)
        child_deadline = now + timeout
        reserve = min(.25, timeout / 4)
        command = [sys.executable, str(Path(__file__).resolve()), '--writer-root-capabilities-only',
            '--capture-child', str(request['childHwnd']), '--office-pid', str(request['officePid']),
            '--writer-office-creation-time', str(request['officeCreationTime']),
            '--writer-office-image', request['expectedImage']]
        evidence['timeoutSeconds'] = timeout
        output = tempfile.TemporaryFile('w+b')
        if time.monotonic() >= child_deadline - reserve:
            raise subprocess.TimeoutExpired(['writer-root-diagnostic'], timeout)
        evidence.update(attempted=True, cleanupConfirmed=False,
                        result=writer_access.root_diagnostic_failure(request))
        child = subprocess.Popen(command, stdout=output, stderr=subprocess.DEVNULL, shell=False)
        remaining = child_deadline - reserve - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(['writer-root-diagnostic'], timeout)
        code = child.wait(timeout=remaining)
        exited = True
        if time.monotonic() >= child_deadline:
            raise subprocess.TimeoutExpired(['writer-root-diagnostic'], timeout)
        output.seek(0)
        raw = output.read(4097)
        if code == 0 and 0 < len(raw) <= 4096:
            evidence['result'] = writer_access.decode_root_diagnostic(raw.decode('utf-8'), request)
        if time.monotonic() >= child_deadline:
            raise subprocess.TimeoutExpired(['writer-root-diagnostic'], timeout)
        evidence['completedWithinBudget'] = True
    except subprocess.TimeoutExpired:
        if evidence['requestValid']:
            evidence['result'] = writer_access.root_diagnostic_failure(request, 14)
    except Exception:
        if evidence['requestValid']:
            evidence['result'] = writer_access.root_diagnostic_failure(request)
    finally:
        if child is not None and not exited:
            try:
                if time.monotonic() < child_deadline:
                    child.kill()
                remaining = child_deadline - time.monotonic()
                if remaining > 0:
                    child.wait(timeout=remaining)
                    exited = True
            except Exception:
                pass  # No unbounded wait or process-disposal shortcut.
        if output is not None:
            if evidence['attempted'] and child is None:
                # The constructor returned no process object: retain the sink,
                # do not guess a PID, and do not claim the launch was retired.
                _ROOT_DIAGNOSTIC_PENDING.append((None, output))
                evidence.update(cleanupConfirmed=False, retainedPending=True, launchOutcomeUnknown=True)
            elif child is not None and not exited:
                _ROOT_DIAGNOSTIC_PENDING.append((child, output))
                evidence.update(cleanupConfirmed=False, retainedPending=True)
            else:
                try:
                    output.close()
                    evidence['cleanupConfirmed'] = child is None or exited
                except Exception:
                    _ROOT_DIAGNOSTIC_PENDING.append((child, output))
                    evidence.update(cleanupConfirmed=False, retainedPending=True)
        if not evidence['cleanupConfirmed']:
            evidence['completedWithinBudget'] = False
            if evidence['requestValid']:
                evidence['result'] = writer_access.root_diagnostic_failure(request, 14 if child is not None else 13)
        if evidence['attempted'] and child_deadline is not None:
            try:
                if time.monotonic() >= child_deadline:
                    evidence['completedWithinBudget'] = False
                    evidence['result'] = writer_access.root_diagnostic_failure(request, 14)
            except Exception:
                evidence['completedWithinBudget'] = False
                evidence['result'] = writer_access.root_diagnostic_failure(request)
    return evidence


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


def run_case(suite, fixtures, output, module, *, probe_only=False, writer_regular_capture=False, writer_same_root_diagnostic=False):
    if _WRITER_CAPTURE_PENDING:raise WriterCapturePending()
    if type(writer_same_root_diagnostic)is not bool or writer_same_root_diagnostic and not writer_regular_capture:
        raise ValueError('Same-root observation requires bounded Writer transport')
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
            if writer_regular_capture:
                options={'same_root_diagnostic':True} if writer_same_root_diagnostic else {}
                os_snapshot = capture_writer_regular_checkpoint(child,office_pid,output/os_name,writer_request=writer_request,**options)
                record['writerPrimaryCheckpoint']=os_snapshot['writerPrimaryCheckpoint']
                record['writerCaptureTransport']=os_snapshot['writerCaptureTransport']
            else:
                os_snapshot = capture_bounded(child, office_pid, output / os_name, writer_request=writer_request)
            record['writerOsAccessibility'] = os_snapshot.get('writerOsAccessibility',
                writer_access.failure(writer_request))
        else:
            os_snapshot = capture_bounded(child, office_pid, output / os_name)
        record.update(osAccessibilitySnapshot=os_name, osAccessibleControlCount=os_snapshot['controlCount'])
        record['stage'] = 'capture-native-accessible-objects'
        snapshot_name = case + '-accessibility.json'
        native_deadline = time.monotonic() + 45 if module == 'writer' else None
        snapshot = accessible.capture_bounded(suite, child, office_pid, engine.creation_time,
                                              module, output / snapshot_name)
        if module == 'writer':
            record['writerOsAccessibilityAfterNative'] = capture_writer_msaa_after_native(writer_request, native_deadline)
            primary_verified = False
            try:
                primary_verified = writer_access.validate(record['writerOsAccessibility'], writer_request)['verified'] == 1
            except Exception:
                pass  # The original acceptance path still owns protocol failure.
            try:
                record['writerRootIa2Diagnostic'] = capture_writer_root_diagnostic(writer_request, native_deadline,
                    enabled=not primary_verified)
            except Exception:
                # The optional reader may have failed at any point: make no
                # launch/retirement claim and preserve the original gates.
                record['writerRootIa2Diagnostic'] = dict(schemaVersion=1, diagnosticOnly=True,
                    acceptanceEligible=False, freshRootLater=True, invocationFailed=True,
                    attemptKnown=False, cleanupConfirmed=False, result={})
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
    except WriterCapturePending as pending:
        record.update(success=False,writerProbePending=1)
        pending.record=record
        raise
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


def run_modules(suite, fixtures, output, modules, *, probe_only=False, writer_regular_capture=False, writer_same_root_diagnostic=False):
    if type(writer_same_root_diagnostic)is not bool or writer_same_root_diagnostic and not writer_regular_capture:
        raise ValueError('Same-root observation requires bounded Writer transport')
    records = []
    pending_cohort = bool(_WRITER_CAPTURE_PENDING)
    for module in modules:
        if pending_cohort or _WRITER_CAPTURE_PENDING:
            pending_cohort=True;break
        try:
            options={'writer_regular_capture':True} if writer_regular_capture and module=='writer' else {}
            if writer_same_root_diagnostic and module=='writer':options['writer_same_root_diagnostic']=True
            record = run_case(suite, fixtures, output, module, probe_only=probe_only,**options)
        except WriterCapturePending as pending:
            record=pending.record if type(pending.record)is dict else dict(case='korean-ui-'+module,module=module,success=False)
            record.update(success=False,writerProbePending=1)
            native.write_result(output,record['case'],record)
            records.append(record);pending_cohort=True;break
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
                  success=len(records)==len(modules) and all(record.get('success') is True for record in records), probeOnly=probe_only,
                  koreanUiVerified=not probe_only and len(verified) == len(modules),
                  expectedModules=list(modules), verifiedModules=verified, tests=records)
    if pending_cohort:report['writerProbePending']=1
    (output/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return report


_WRITER_CAPTURE_PENDING = []  # Owned child/HANDLE/file/dir; no automatic relaunch.


def _writer_capture_environment(folder):
    """Only five existing public OS/profile path values; never copy host environ."""
    values={}
    for key in ('SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA'):
        value=os.environ.get(key)
        if type(value)is not str or not value or any(c in value for c in ('\0',';','\r','\n')):
            raise ValueError('Writer child public environment unavailable')
        path=Path(value)
        writer_access._primary_checkpoint_path(path/'environment-path-check')
        if not path.is_dir():raise ValueError('Writer child public directory unavailable')
        values[key]=path.resolve(strict=True)
    if (values['SystemRoot']!=values['WINDIR'] or not (values['SystemRoot']/'System32').is_dir()
            or any(not values[k].is_relative_to(values['USERPROFILE'])for k in ('APPDATA','LOCALAPPDATA'))):
        raise ValueError('Writer child public environment differs')
    result={k:str(v)for k,v in values.items()}
    result.update(TEMP=str(folder),TMP=str(folder),
        PATH=';'.join(map(str,(Path(sys.executable).resolve(strict=True).parent,
            values['SystemRoot']/'System32',values['SystemRoot']))),
        PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    return result


def _capture_writer_regular_file(command, *, deadline, checkpoint_folder,
                                 clock=time.monotonic, pause=time.sleep):
    """Scratch opt-in transport core; direct child only, never PIPE/communicate.

    The original absolute 45-second observation deadline is not restarted.
    A synchronous OS operation can return late. At deadline only this original
    creation HANDLE is terminated, then zero-polled; uncertain resources remain
    retained. This does not prove process-tree retirement or hard OS preemption.
    """
    proof=dict(schemaVersion=1,diagnosticOnly=1,acceptanceEligible=0,statusCode=0,
        failureCode=0,launched=0,creationHandleKnown=0,pollCount=0,retired=0,
        naturalExit=0,exitObserved=0,exitCode=0,terminateRequested=0,
        stdoutRead=0,stdoutBytes=0,stdoutPostHashVerified=0,creationHandleClosed=0,
        stdoutClosed=0,pendingRetained=0,withinOriginalDeadline=0,directChildOnly=1,nativeBirthMeasured=0)
    if _WRITER_CAPTURE_PENDING:
        proof.update(statusCode=4,pendingRetained=1,failureCode=1);return proof,None
    if os.name!='nt':proof.update(statusCode=4,failureCode=2);return proof,None
    child=stream=handle=None;original_pid=None;handle_value=None;raw=None;last=None;entered_launch=False
    def now():
        nonlocal last
        value=clock()
        if (type(value)not in(int,float) or not math.isfinite(value)
                or last is not None and value<last):raise ValueError()
        last=value;return value
    def original():
        return (child is not None and handle is not None and child._handle is handle
            and isinstance(handle,int) and type(handle)is not bool and int(handle)==handle_value
            and type(getattr(handle,'closed',None))is bool and not handle.closed
            and type(child.pid)is int and child.pid==original_pid)
    try:
        first=now()
        if type(deadline)not in(int,float) or not math.isfinite(deadline) or not first<deadline<=first+45:raise ValueError()
        writer_access._primary_checkpoint_path(Path(checkpoint_folder)/'stdout-path-check')
        environment=_writer_capture_environment(checkpoint_folder)
        stream=tempfile.TemporaryFile('w+b',dir=checkpoint_folder)
        if now()>=deadline:raise ValueError()
        entered_launch=True
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.DEVNULL,
            shell=False,env=environment,creationflags=0x08000000)  # CREATE_NO_WINDOW: this new diagnostic path only.
        proof['launched']=1;handle=child._handle;original_pid=child.pid
        if (not isinstance(handle,int) or type(handle)is bool or int(handle)<=0
                or type(getattr(handle,'closed',None))is not bool or handle.closed
                or type(original_pid)is not int or original_pid<=0):raise ValueError()
        handle_value=int(handle)
        proof['creationHandleKnown']=1
        while True:
            if not original():proof['failureCode']=3;break
            if now()>=deadline:
                proof['terminateRequested']=1
                child.kill()  # Popen.kill uses this retained creation HANDLE on Windows.
                if not original():proof['failureCode']=3;break
                code=child.poll();proof['pollCount']+=1
                if not original():proof['failureCode']=3;break
                if type(code)is int:
                    proof.update(retired=1,exitObserved=1,exitCode=code)
                proof['statusCode']=3;break
            code=child.poll();proof['pollCount']+=1
            if not original():proof['failureCode']=3;break
            if type(code)is int:
                proof.update(retired=1,naturalExit=1,exitObserved=1,exitCode=code)
                if now()>=deadline:proof['statusCode']=3;break
                import os as file_os
                before=file_os.fstat(stream.fileno())
                if not 0<before.st_size<=4101:raise ValueError()
                stream.seek(0);value=stream.read(4102)
                if len(value)!=before.st_size:raise ValueError()
                digest=hashlib.sha256(value).digest()
                if now()>=deadline:proof['statusCode']=3;break
                stream.seek(0);again=stream.read(4102);after=file_os.fstat(stream.fileno())
                if ((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
                        or hashlib.sha256(again).digest()!=digest):raise ValueError()
                if not original():proof['failureCode']=3;break
                if now()>=deadline:proof['statusCode']=3;break
                raw=value;proof.update(stdoutRead=1,stdoutBytes=len(value),stdoutPostHashVerified=1,
                    statusCode=2,withinOriginalDeadline=1);break
            if proof['pollCount']>=8192:proof['failureCode']=4;break
            remaining=deadline-now()
            if remaining>0:pause(min(.01,remaining))
    except BaseException:
        proof['failureCode']=proof['failureCode'] or 5;proof['statusCode']=4;raw=None
    finally:
        if proof['retired'] and original():
            try:handle.Close();proof['creationHandleClosed']=1
            except BaseException:proof['failureCode']=6
            try:stream.close();proof['stdoutClosed']=1
            except BaseException:proof['failureCode']=6
        elif not entered_launch and stream is not None:
            try:stream.close();proof['stdoutClosed']=1
            except BaseException:proof['failureCode']=6
        if ((entered_launch and not (proof['retired'] and proof['creationHandleClosed'] and proof['stdoutClosed']))
                or stream is not None and not proof['stdoutClosed']):
            _WRITER_CAPTURE_PENDING.append(dict(process=child,handle=handle,stdout=stream,
                checkpointFolder=checkpoint_folder,originalPid=original_pid))
            proof['pendingRetained']=1
        if entered_launch:
            try:
                if now()>=deadline:
                    proof['withinOriginalDeadline']=0
                    if proof['statusCode']==2:proof['statusCode']=3;raw=None
            except BaseException:proof['failureCode']=5
        if proof['failureCode']:proof['statusCode']=4;raw=None
    return proof,raw


class WriterCapturePending(BaseException):
    """Terminal diagnostic cohort state; carries no input or cleanup authority."""
    def __init__(self):
        super().__init__('Owned Writer diagnostic retirement is pending')
        self.record=None


def capture_writer_regular_checkpoint(child, office_pid, destination, *, writer_request, same_root_diagnostic=False):
    """Explicit bounded transport; optional same-root diagnosis is never acceptance."""
    if _WRITER_CAPTURE_PENDING:raise WriterCapturePending()
    if type(same_root_diagnostic)is not bool:raise ValueError('Explicit diagnostic selection required')
    writer_access._request(writer_request)
    if (type(child)is not int or type(office_pid)is not int or child!=writer_request['childHwnd']
            or office_pid!=writer_request['officePid']):
        raise ValueError('Exact original Writer owner tuple required')
    destination=Path(destination)
    writer_access._primary_checkpoint_path(destination.parent/'primary-path-check')
    folder=Path(tempfile.mkdtemp(prefix='.writer-primary-',dir=destination.parent))
    checkpoint=folder/'primary.json'
    deadline=time.monotonic()+45
    command=[sys.executable,str(Path(__file__).resolve()),'--capture-child',str(child),
        '--office-pid',str(office_pid),'--snapshot',str(destination),'--writer-msaa-deadline',repr(deadline),
        '--writer-office-creation-time',str(writer_request['officeCreationTime']),
        '--writer-office-image',writer_request['expectedImage'],'--writer-msaa',
        '--writer-primary-checkpoint',str(checkpoint)]
    if same_root_diagnostic:command.append('--writer-same-root-after-failure')
    transport,raw=_capture_writer_regular_file(command,deadline=deadline,checkpoint_folder=folder)
    # A pending child may still own both files. Neither file is read or removed.
    if transport.get('pendingRetained')==1:raise WriterCapturePending()
    if transport.get('retired')!=1:raise RuntimeError('Owned Writer collector unavailable')
    metadata=dict(schemaVersion=1,diagnosticOnly=1,acceptanceEligible=0,
        primaryPreserved=0,cleanupObserved=0,postDiagnosticObserved=0)
    evidence=writer_access.failure(writer_request,14)
    if (transport.get('statusCode')==2 and transport.get('naturalExit')==1
            and transport.get('exitCode')==0 and type(raw)is bytes):
        prefix=3 if raw.startswith(b'1\r\n')else 2 if raw.startswith(b'1\n')else 0
        if prefix:
            body=raw[prefix:]
            if body.endswith(b'\r\n'):body=body[:-2]
            elif body.endswith(b'\n'):body=body[:-1]
            try:evidence=writer_access.decode(body.decode('ascii'),writer_request)
            except (UnicodeError,ValueError):evidence=writer_access.failure(writer_request)
        else:evidence=writer_access.failure(writer_request)
    if 'postFailureDiagnostic'in evidence and not same_root_diagnostic:
        evidence=writer_access.failure(writer_request)
    try:
        original=writer_access.read_primary_checkpoint(checkpoint,writer_request,deadline=deadline)
        initial=original['primary']
        cleanup={'referencesAcquired','referencesReleased','variantsCreated','variantsCleared',
            'cleanupFailure','cleanupHresult','ownerReleased'}
        facts=writer_access._MAXIMA.keys()-cleanup
        if (any(evidence.get(k)!=initial[k] for k in facts)
                or any(evidence.get(k)!=initial.get(k)for k in ('focusCall','guiFocus'))):
            evidence=initial;metadata['primaryPreserved']=1
        elif same_root_diagnostic and 'postFailureDiagnostic'in evidence:
            metadata['postDiagnosticObserved']=1
    except BaseException:
        pass  # Missing/partial checkpoint never becomes a fabricated primary.
    if 'postFailureDiagnostic'in evidence and not metadata['postDiagnosticObserved']:
        evidence=writer_access.failure(writer_request)
    try:
        snapshot=json.loads(destination.read_text(encoding='utf-8'))
        if type(snapshot)is not dict:raise ValueError()
    except BaseException:
        raise RuntimeError('Owned Writer snapshot unavailable after retirement') from None
    snapshot.update(writerOsAccessibility=evidence,writerPrimaryCheckpoint=metadata,
        writerCaptureTransport=transport)
    return snapshot


def _writer_context_module():
    # Same public owner-push/attempt/source admission used by Korean IME.
    import importlib.util
    path=Path(__file__).resolve().parents[2]/'e2e/native31_suite_prepare.py'
    spec=importlib.util.spec_from_file_location('writer_same_root_ci_admission',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _admit_writer_same_root(suite, architecture):
    admission=_writer_context_module()
    binding=admission.validate_context(os.environ,admission.read_event(),architecture,os.name)
    # Read the same Suite architecture metadata as the existing Korean IME CLI.
    inventory=json.loads((suite/'suite-inventory.json').read_text(encoding='utf-8-sig'))
    if (type(inventory)is not dict or type(inventory.get('schemaVersion'))is not int
            or inventory['schemaVersion']!=1 or inventory.get('architecture')!=architecture):
        raise ValueError('Writer diagnostic architecture differs from Suite inventory')
    return binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--modules', choices=tuple(MODULES), nargs='+', default=list(MODULES))
    parser.add_argument('--probe-only', action='store_true')
    parser.add_argument('--writer-same-root-diagnostic', choices=('x64','arm64'))
    parser.add_argument('--capture-child', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--office-pid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--snapshot', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--writer-msaa', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--writer-msaa-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--writer-root-capabilities-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--writer-office-creation-time', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--writer-office-image', help=argparse.SUPPRESS)
    parser.add_argument('--writer-msaa-deadline', help=argparse.SUPPRESS)
    parser.add_argument('--writer-primary-checkpoint', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--writer-same-root-after-failure', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    # Invalid/missing diagnostic metadata preserves the legacy probe seam.
    try:
        gui_deadline = float(getattr(args, 'writer_msaa_deadline', None))
        if not math.isfinite(gui_deadline) or gui_deadline <= 0:
            gui_deadline = None
    except (TypeError, ValueError, OverflowError):
        gui_deadline = None
    gui_options = {'gui_deadline': gui_deadline} if gui_deadline is not None else {}
    if getattr(args,'writer_primary_checkpoint',None) is not None:
        if not gui_options or not (args.writer_msaa or args.writer_msaa_only) or args.writer_root_capabilities_only:
            raise ValueError('Primary checkpoint requires the original Writer collector')
        gui_options['primary_checkpoint']=args.writer_primary_checkpoint
    if getattr(args,'writer_same_root_after_failure',False):
        if (not args.writer_msaa or args.writer_msaa_only or args.writer_root_capabilities_only
                or args.writer_primary_checkpoint is None or not gui_options
                or not args.capture_child or not args.office_pid or args.snapshot is None):
            raise ValueError('Same-root observation requires the original bounded collector and checkpoint')
        now=time.monotonic()
        if (type(now)not in(int,float) or not math.isfinite(now)
                or not 0 < gui_deadline-now <= 45):
            raise ValueError('Same-root observation exceeds the original 45-second interval')
        gui_options['post_failure_diagnostic']=True
    if getattr(args,'writer_same_root_diagnostic',None) is not None and (
            args.probe_only or 'writer' not in args.modules or args.capture_child is not None
            or args.writer_msaa or args.writer_msaa_only or args.writer_root_capabilities_only
            or args.writer_primary_checkpoint is not None):
        raise ValueError('Explicit Writer observation requires the original cohort path')
    if os.name != 'nt' or not __debug__:
        raise RuntimeError('Actual Windows GUI execution with assertions enabled is required')
    if getattr(args, 'writer_root_capabilities_only', False):
        assert args.capture_child and args.office_pid and not args.snapshot and not args.writer_msaa and not args.writer_msaa_only
        request = dict(childHwnd=args.capture_child, officePid=args.office_pid,
            officeCreationTime=args.writer_office_creation_time, expectedImage=args.writer_office_image)
        with redirect_stdout(sys.stderr):
            value = writer_access.validate_root_diagnostic(writer_access.observe_root_diagnostic(request), request)
        encoded = json.dumps(value, separators=(',', ':'), allow_nan=False)
        assert len(encoded.encode('utf-8')) <= 4096, 'Closed Writer root diagnostic exceeds bound'
        print(encoded, flush=True)
        return 0
    if getattr(args, 'writer_msaa_only', False):
        assert args.capture_child and args.office_pid and not args.snapshot and not args.writer_msaa
        request = dict(childHwnd=args.capture_child, officePid=args.office_pid,
            officeCreationTime=args.writer_office_creation_time, expectedImage=args.writer_office_image)
        with redirect_stdout(sys.stderr):
            value = writer_access.validate(writer_access.observe(request, **gui_options), request)
        encoded = json.dumps(value, separators=(',', ':'), allow_nan=False)
        assert len(encoded.encode('utf-8')) <= 4096, 'Closed Writer result exceeds bound'
        print(encoded, flush=True)
        return 0
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
            value = writer_access.observe(request, **gui_options)
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
    options={}
    if getattr(args,'writer_same_root_diagnostic',None) is not None:
        _admit_writer_same_root(suite,args.writer_same_root_diagnostic)
        options=dict(writer_regular_capture=True,writer_same_root_diagnostic=True)
    output.mkdir(parents=True, exist_ok=False)
    report = run_modules(suite, fixtures, output, args.modules, probe_only=args.probe_only,**options)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
