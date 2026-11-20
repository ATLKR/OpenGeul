"""One contained, failure-only UIA Discard actor. Never normal input evidence."""
import argparse
import ctypes
from ctypes import wintypes as wt
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from calc_early_cleanup import (MAX_JSON, MAX_SECONDS, SOURCE_FILES, plain, read_json,
                                require_early, source_pins, write_original)


class BasicLimits(ctypes.Structure):
    _fields_ = [('processTime',ctypes.c_int64),('jobTime',ctypes.c_int64),('flags',ctypes.c_uint32),
        ('minimumWorkingSet',ctypes.c_size_t),('maximumWorkingSet',ctypes.c_size_t),
        ('activeProcesses',ctypes.c_uint32),('affinity',ctypes.c_size_t),
        ('priority',ctypes.c_uint32),('scheduling',ctypes.c_uint32)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic',BasicLimits),('ioCounters',ctypes.c_uint64 * 6),
        ('processMemory',ctypes.c_size_t),('jobMemory',ctypes.c_size_t),
        ('peakProcessMemory',ctypes.c_size_t),('peakJobMemory',ctypes.c_size_t)]


def native_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))
    import native_windows
    return native_windows


class ActorProcess:
    """Retain original process/thread/job; never change the product's jobs."""
    def __init__(self, argv, cwd):
        n = native_module()
        self.api = n.ProcessDiagnosticsApi()
        kernel = n.windows_dll('kernel32')
        self.close_handle = n.bind(kernel, 'CloseHandle', [wt.HANDLE], wt.BOOL)
        self.end_job = n.bind(kernel, 'TerminateJobObject', [wt.HANDLE, wt.UINT], wt.BOOL)
        self.kill_suspended = n.bind(kernel, 'TerminateProcess', [wt.HANDLE, wt.UINT], wt.BOOL)
        create_job = n.bind(kernel, 'CreateJobObjectW', [ctypes.c_void_p, wt.LPCWSTR], wt.HANDLE)
        assign = n.bind(kernel, 'AssignProcessToJobObject', [wt.HANDLE, wt.HANDLE], wt.BOOL)
        limits = n.bind(kernel, 'SetInformationJobObject', [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD], wt.BOOL)
        resume = n.bind(kernel, 'ResumeThread', [wt.HANDLE], wt.DWORD)
        create = n.bind(kernel, 'CreateProcessW', [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p,
            ctypes.c_void_p, wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
            ctypes.POINTER(n.StartupInfo), ctypes.POINTER(n.ProcessInfo)], wt.BOOL)
        self.job = create_job(None, None)
        if not self.job: raise ctypes.WinError(ctypes.get_last_error())
        self.handle = self.thread = None
        self.assigned = self.resumed = False
        self.launch = dict(kind='failure-only-uia-actor', argv=list(argv), cwd=str(cwd),
                          inheritHandles=False, calls=[], launchError=None)
        info, startup = n.ProcessInfo(), n.StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        try:
            bound = ExtendedLimits()
            bound.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE for this helper only.
            limited = limits(self.job,9,ctypes.byref(bound),ctypes.sizeof(bound))
            self.launch['calls'].append(dict(api='SetInformationJobObject',result=bool(limited),
                informationClass=9,flags=0x2000,bufferBytes=ctypes.sizeof(bound)))
            if not limited: raise ctypes.WinError(ctypes.get_last_error())
            made = create(argv[0], ctypes.create_unicode_buffer(subprocess.list2cmdline(argv)),
                None, None, False, 0x00000004 | 0x08000000, None, str(cwd),
                ctypes.byref(startup), ctypes.byref(info))
            self.launch['calls'].append(dict(api='CreateProcessW', result=bool(made), flags=0x08000004))
            if not made: raise ctypes.WinError(ctypes.get_last_error())
            self.handle, self.thread, self.pid = info.hProcess, info.hThread, int(info.dwProcessId)
            self.launch.update(processHandleValue=int(self.handle), threadHandleValue=int(self.thread),
                               jobHandleValue=int(self.job), pid=self.pid)
            self.assigned = bool(assign(self.job, self.handle))
            self.launch['calls'].append(dict(api='AssignProcessToJobObject', result=self.assigned))
            if not self.assigned: raise ctypes.WinError(ctypes.get_last_error())
            member = wt.BOOL()
            checked = self.api.is_in_job(self.handle, self.job, ctypes.byref(member))
            self.launch['calls'].append(dict(api='IsProcessInJob', result=bool(checked), inJob=bool(member.value)))
            assert checked and member.value, 'Suspended actor private-job membership not proved'
            self.launch['identity'] = self.api.identity(self.handle)
            assert Path(self.launch['identity']['image']).samefile(argv[0]), 'Actor executable changed'
            assert self.api.job_pids(self.job) == [self.pid], 'Unexpected suspended actor members'
            count = resume(self.thread)
            self.launch['calls'].append(dict(api='ResumeThread', previousSuspendCount=int(count)))
            if count != 1: raise RuntimeError('Actor did not resume from its original suspension')
            self.resumed = True
        except BaseException as exc:
            self.launch['launchError'] = type(exc).__name__ + ': ' + str(exc)[:1024]
            # Return the owned handles even on partial launch, for bounded reap.
            # An unassigned process is still suspended and only its HANDLE may end.

    def snapshot(self):
        rows = []
        pids = self.api.job_pids(self.job, record=rows.append)
        state = self.api.state(self.handle) if self.handle else dict(waitResult=0, exitCode=1)
        return dict(pids=pids, waitResult=state['waitResult'], exitCode=state['exitCode'],
                    census=rows[-1], state=state)

    def terminate(self):
        if self.assigned:
            ok = self.end_job(self.job, 1)
        elif self.handle:
            assert not self.resumed
            ok = self.kill_suspended(self.handle, 1)
        else:
            return
        if not ok: raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        errors = []
        for name in ('thread', 'handle', 'job'):
            handle = getattr(self, name)
            if handle:
                if self.close_handle(handle): setattr(self, name, None)
                else: errors.append(name)
        assert not errors, 'Actor CloseHandle failed: ' + ','.join(errors)


def load_request(path, digest, nonce):
    path = plain(Path(path))
    assert path.name == 'request.json' and path.parent.name == 'failure-cleanup-' + nonce
    assert re.fullmatch('[0-9a-f]{32}', nonce) and re.fullmatch('[0-9a-f]{64}', digest)
    assert path.is_file() and 0 < path.stat().st_size <= MAX_JSON
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest, 'Original actor request bytes changed'
    value = read_json(raw)
    expected = {'schemaVersion','kind','nonce','case','deadline','suite','fixture','fixtureSha256','fixtureBytes',
        'shellPid','shellCreation','enginePid','engineCreation','hwnd','parent','child','command','record','sourcePins'}
    assert set(value) == expected and value['schemaVersion'] == 1 and type(value['schemaVersion']) is int
    assert value['kind'] == 'failed-calc-discard-actor' and value['nonce'] == nonce
    assert value['sourcePins'] == source_pins() and set(value['sourcePins']) == set(SOURCE_FILES), 'Actor source bytes differ'
    for key in ('shellPid','shellCreation','enginePid','engineCreation','hwnd','parent','child','fixtureBytes'):
        assert type(value[key]) is int and value[key] > 0, 'Invalid native actor identity'
        assert value[key] <= (0xffffffff if key in ('shellPid','enginePid') else 0xffffffffffffffff)
    assert value['shellPid'] != value['enginePid'] and value['engineCreation'] >= value['shellCreation']
    assert type(value['deadline']) in (int, float) and 0 < value['deadline'] - time.monotonic() <= MAX_SECONDS
    require_early(value['record'], True, None)
    assert value['case'] == value['record']['case']
    suite, fixture = plain(value['suite']), plain(value['fixture'])
    assert fixture == path.parent.parent / 'fixtures/OpenGeul-calc.xlsx'
    assert suite != fixture.parent and suite not in fixture.parents
    assert value['command'] == [str(suite/'OpenGeul.Office.exe'),'--module','calc','--file',str(fixture)]
    assert re.fullmatch('[0-9a-f]{64}', value['fixtureSha256']) and value['fixtureBytes'] <= 8 * 1024 * 1024
    return value


class Guard:
    def __init__(self, request):
        import lifecycle_smoke as lifecycle
        import windows_smoke as native
        self.request, self.lifecycle = request, lifecycle
        self.api = native.Windows()
        self.shell = self.engine = None
        try:
            self.shell = lifecycle.BoundHwpProcess(request['shellPid'], Path(request['suite'])/'OpenGeul.Office.exe',
                                                 expected_creation=request['shellCreation'])
            self.engine = lifecycle.BoundHwpProcess(request['enginePid'], Path(request['suite'])/'Office/program/soffice.bin',
                                                  expected_creation=request['engineCreation'])
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        r, api = self.request, self.api
        assert time.monotonic() < r['deadline'], 'Actor action deadline expired'
        assert self.shell.live() and self.engine.live(), 'Original retained generation exited'
        for bound, image in ((self.shell, Path(r['suite'])/'OpenGeul.Office.exe'),
                             (self.engine, Path(r['suite'])/'Office/program/soffice.bin')):
            assert self.lifecycle.process_identity(bound.kernel, bound.handle) == (image.resolve(), bound.creation)
        assert all(api.user.IsWindow(r[k]) for k in ('hwnd','parent','child'))
        assert api.user.GetAncestor(r['hwnd'],2) == r['hwnd'], 'Original Suite form is no longer top-level'
        assert api.pid(r['hwnd']) == self.shell.pid and api.pid(r['parent']) == self.shell.pid
        assert api.pid(r['child']) == self.engine.pid
        assert api.user.IsChild(r['hwnd'],r['parent']) and api.user.IsChild(r['parent'],r['child'])
        path = plain(r['fixture'])
        assert path.is_file() and path.stat().st_size == r['fixtureBytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == r['fixtureSha256'], 'Original private fixture changed'

    def close(self):
        errors = []
        for bound in (self.engine, self.shell):
            if bound is not None:
                try: bound.close()
                except BaseException as exc: errors.append(type(exc).__name__ + ': ' + str(exc))
        assert not errors, '; '.join(errors)[:2048]


def invoke_one(guard, emit):
    """Every potentially blocking UIA operation is inside this owned actor."""
    from pywinauto import Desktop
    from generated_calc_close import require_calc_prompt_buttons
    import lifecycle_smoke as lifecycle
    import windows_smoke as native
    r, api = guard.request, guard.api
    dialog = None
    while time.monotonic() < r['deadline']:
        guard.check()
        matches = [h for h in api.windows(r['shellPid']) if api.user.GetWindow(h,4) == r['hwnd']]
        assert len(matches) <= 1, 'Ambiguous original Calc prompt'
        if matches:
            dialog = matches[0]
            break
        time.sleep(.05)
    assert dialog, 'Original Calc prompt missing'
    def inspect():
        guard.check()
        matches = [h for h in api.windows(r['shellPid']) if api.user.GetWindow(h,4) == r['hwnd']]
        assert matches == [dialog], 'Original unique prompt changed'
        native.require_dialog_identity(api.pid(dialog),r['shellPid'],api.user.GetWindow(dialog,4),r['hwnd'],
            api.title(dialog),'OpenGeul Calc',api.class_name(dialog))
        accessible = Desktop(backend='uia').window(handle=dialog).wrapper_object()
        observed = {}
        buttons = require_calc_prompt_buttons(api,accessible,r['shellPid'],dialog,observed)
        assert buttons is not None, 'Original three choices not ready'
        button = next(b for b in buttons if b.element_info.name == '저장하지 않음')
        ancestry = lifecycle.require_dialog_button_ancestry(api,accessible,button,r['shellPid'],dialog)
        handle = ancestry[0]['nativeHandle']
        get_id = api.user.GetDlgCtrlID
        get_id.argtypes, get_id.restype = (wt.HWND,), ctypes.c_int
        control_id = get_id(handle)
        assert control_id > 0 and button.element_info.control_id == control_id, 'Discard native/UIA control ID differs'
        pattern = button.iface_invoke
        assert callable(getattr(pattern,'Invoke',None)), 'Discard has no InvokePattern'
        identity = dict(dialogHwnd=int(dialog),buttonHwnd=handle,controlId=control_id,
            runtimeId=list(button.element_info.runtime_id),shellPid=r['shellPid'],ancestry=ancestry)
        return pattern, identity, observed
    _, original, observed = inspect()
    emit('20-prompt.json', dict(discard=original, observation=observed))
    pattern, refreshed, _ = inspect()
    assert refreshed == original, 'Original Discard identity drifted'
    guard.check()
    emit('30-invoke-intent.json', dict(invokeIntent=True,invokeAttempts=1,discard=original))
    pattern, final_identity, _ = inspect()
    assert final_identity == original, 'Discard changed after retained intent'
    guard.check()  # File I/O or slow provider reads never grant a late action.
    pattern.Invoke()  # Exactly one call. Parent timeout cannot prove remote revocation.
    return dict(success=True,invokeReturned=True,invokeAttempts=1,discard=original)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request',required=True);parser.add_argument('--sha256',required=True);parser.add_argument('--nonce',required=True)
    args = parser.parse_args()
    request = load_request(args.request,args.sha256,args.nonce)
    folder = Path(args.request).parent
    def emit(name, value):
        write_original(folder/name,dict(value,nonce=args.nonce,case=request['case'],requestSha256=args.sha256))
    guard = None
    result = dict(success=False,invokeReturned=False)
    try:
        assert os.name == 'nt' and __debug__, 'Failure actor requires Windows assertions'
        guard = Guard(request)
        emit('10-bound.json',dict(shellCreation=guard.shell.creation,engineCreation=guard.engine.creation,
            shellHandleValue=int(guard.shell.handle),engineHandleValue=int(guard.engine.handle)))
        result = invoke_one(guard,emit)
    except BaseException as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)[:2048]
    finally:
        if guard is not None:
            try: guard.close()
            except BaseException as exc: result.update(success=False,handleError=str(exc)[:2048])
        emit('99-result.json',result)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
