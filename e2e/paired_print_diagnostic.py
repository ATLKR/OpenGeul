"""Additive nonqualifying print comparison; no OS operations at import time."""
import copy
import math
import re
import time
from pathlib import Path

from paired_print_contract import Rejected, digest, integer, require, shape

LEGACY_HWP = {
    'version': '1.1.4', 'sourceCommit': '131ccbf3ac10a82e1d6785b4c906fb836b912e73',
    'url': 'https://github.com/ATLKR/OpenGeul/releases/download/v1.1.4/OpenGeul_1.1.4_windows-x64_unsigned-portable.zip',
    'size': 33362247, 'sha256': '6bda733fba96ae692c504630eceb1113f5f11f7cac9208158531960e5d822764',
    'sourceUrl': 'https://github.com/ATLKR/OpenGeul/tree/131ccbf3ac10a82e1d6785b4c906fb836b912e73',
    'provenanceUrl': 'https://github.com/ATLKR/OpenGeul/releases/download/v1.1.4/provenance-x64.json',
}
LEGACY_PROVENANCE_SHA = 'bf095615f053f1a17d41843f637c4c27ac0110f0bf37324acb2a80c45c7006cb'
WASM_FILES = ('rhwp.js', 'rhwp.d.ts', 'rhwp_bg.wasm', 'rhwp_bg.wasm.d.ts', 'package.json', 'LICENSE')
CURRENT_WASM_GENERATOR = 'wasm-pack 0.14.0 --target web --release --no-opt --no-default-features --features console_error_panic_hook,wasm-api'
PROVENANCE_KEYS = {'unsigned', 'architecture', 'members', 'sha256', 'repository', 'commit', 'runId',
                   'version', 'package', 'upstream', 'sourceParity', 'manualWindowsUx', 'storeCertified', 'windowsComponents'}


def legacy_assets(canonical_hwp):
    """Only the existing canonical 1.1.4 portable route; no fallback transport."""
    shape(canonical_hwp, LEGACY_HWP)
    require(canonical_hwp == LEGACY_HWP and all(type(canonical_hwp[key]) is type(value)
                                             for key, value in LEGACY_HWP.items()), 12)
    return {
        'portable': {key: canonical_hwp[key] for key in ('url', 'size', 'sha256')},
        'provenance': {'url': canonical_hwp['provenanceUrl'], 'size': 47724,
                       'sha256': LEGACY_PROVENANCE_SHA},
    }


def admit_current(value, *, expected_source, run_id, attempt, expected_upstream,
                  expected_wasm_source, runtime_sha256, runtime_bytes):
    """Current package authority is the external same-run caller, not its receipt."""
    digest(expected_source, 40)
    integer(run_id, 1)
    integer(attempt, 1)
    digest(runtime_sha256)
    integer(runtime_bytes, 1, 96 * 1024 * 1024)
    shape(value, PROVENANCE_KEYS)
    require(value['repository'] == 'ATLKR/OpenGeul' and value['commit'] == expected_source
            and value['runId'] == str(run_id) and value['architecture'] == 'x64', 13)
    require(value['unsigned'] is True and value['storeCertified'] is False
            and value['manualWindowsUx'] == 'not-verified', 13)
    integer(value['members'], 1, 10000)
    digest(value['sha256'])
    require(type(value['package']) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,180}\.msix', value['package']), 13)
    require(value['upstream'] == expected_upstream and type(expected_upstream) is dict
            and expected_upstream.get('rhwp', {}).get('version') == '0.9.0'
            and expected_upstream.get('rhwp', {}).get('commit') == 'c9095c5f67632e6721e800ccc7fb43ea49d26682', 13)
    receipt = value['windowsComponents']
    shape(receipt, ('formatVersion', 'repository', 'commit', 'runId', 'runAttempt',
                    'sourceContractSha256', 'components'))
    require(type(receipt['formatVersion']) is int and receipt['formatVersion'] == 1
            and receipt['repository'] == 'ATLKR/OpenGeul' and receipt['commit'] == expected_source
            and receipt['runId'] == str(run_id) and receipt['runAttempt'] == str(attempt), 13)
    digest(receipt['sourceContractSha256'])
    shape(receipt['components'], ('editor', 'cli'))
    for role, runtime in (('editor', 'OpenGeul.exe'), ('cli', 'Tools/rhwp.exe')):
        component = receipt['components'][role]
        shape(component, ('artifactName', 'runAttempt', 'provenanceSha256', 'runtime', 'size', 'sha256'))
        require(component['artifactName'] == f'opengeul-{role}-component-{run_id}'
                and component['runtime'] == runtime, 13)
        require(type(component['runAttempt']) is str
                and re.fullmatch('[1-9][0-9]{0,18}', component['runAttempt'])
                and int(component['runAttempt']) <= attempt, 13)
        integer(component['size'], 1, 96 * 1024 * 1024)
        digest(component['sha256'])
        digest(component['provenanceSha256'])
    editor = receipt['components']['editor']
    require(editor['sha256'] == runtime_sha256 and editor['size'] == runtime_bytes, 13)
    require(type(value['sourceParity']) is dict and 'wasmRebuild' in value['sourceParity'], 13)
    wasm = value['sourceParity']['wasmRebuild']
    shape(expected_wasm_source, ('upstream', 'namespaceHelper', 'namespacePatcher'))
    require(expected_wasm_source['upstream'] == expected_upstream, 13)
    shape(wasm, (*expected_wasm_source, 'artifacts', 'generator'))
    require(all(wasm[key] == expected for key, expected in expected_wasm_source.items())
            and wasm['generator'] == CURRENT_WASM_GENERATOR, 13)
    shape(wasm['artifacts'], WASM_FILES)
    for fingerprint in wasm['artifacts'].values():
        digest(fingerprint)
    return {'editorSha256': editor['sha256'], 'editorBytes': editor['size'],
            'wasmSha256': wasm['artifacts']['rhwp_bg.wasm'], 'jsSha256': wasm['artifacts']['rhwp.js']}


def _observe_census_failure(rows, parents, known, descendants, root_pid, creation,
                            *, sealed, require_live_root):
    """Already-read PID-chain hints only; no generation or ownership authority."""
    reachable = {root_pid}
    for _ in range(65):
        expanded = reachable | {pid for pid, parent in parents.items() if parent in reachable}
        if expanded == reachable:
            break
        reachable = expanded
    else:
        raise Rejected(15)
    unexpected = descendants - known
    selected = unexpected & reachable
    roles = {'msedgewebview2.exe': 1, 'conhost.exe': 2, 'werfault.exe': 3}
    observed = []
    for row in rows:
        pid = row['processId']
        if pid not in selected:
            continue
        name = row.get('executableName')
        role = roles.get(name.lower(), 0) if type(name) is str and len(name) <= 260 and name.isascii() else 0
        observed.append({'pid': pid, 'parentPid': parents[pid], 'executableRoleCode': role})
    return {'schemaVersion': 1, 'diagnosticOnly': True, 'acceptanceEligible': False,
        'rootPid': root_pid, 'originalRootCreationFileTime': creation,
        'sealed': sealed, 'requireLiveRoot': require_live_root, 'snapshotCount': len(rows),
        'knownCount': len(known), 'guardUnexpectedCount': len(unexpected),
        'rootSnapshotReachableCount': len(selected), 'rows': sorted(observed, key=lambda row: row['pid'])}


class RetainedLease:
    """Original root plus a sealed known cohort; never all potential descendants.

    Query-only print handles are used only to verify the live generation. Each
    WebView gets a separate QUERY_LIMITED_INFORMATION | SYNCHRONIZE handle.
    No process is activated, terminated, adopted late, or reopened after exit.
    """
    def __init__(self, session, runtime, *, probe=None, binder=None,
                 clock=time.monotonic, sleeper=time.sleep):
        if probe is None or binder is None:
            from print_focus import WindowsFocusProbe, _bind_native_print_processes
            probe = probe or WindowsFocusProbe()
            binder = binder or _bind_native_print_processes
        self.probe, self.clock, self.sleeper = probe, clock, sleeper
        self.kernel = probe.process.api
        self.handles = {}
        self.closed = False
        self.sealed = False
        self.checkpoint_error = None
        self.operation_error = None
        self.session = session  # Keep its original Popen HANDLE owner alive.
        self.root_pid = session.proc.pid
        self.root_handle = int(session.proc._handle)
        integer(self.root_pid, 1, 0xffffffff)
        integer(self.root_handle, 1)
        probe.architecture = 'x64'
        wait = self.kernel.WaitForSingleObject
        wait.argtypes, wait.restype = [probe.W.HANDLE, probe.W.DWORD], probe.W.DWORD
        try:
            app = runtime['nativeArchitecture']
            web = runtime['webview2Native']
            require(app['processId'] == self.root_pid and web['rootProcessId'] == self.root_pid, 14)
            require(type(web['processes']) is list and 1 <= len(web['processes']) <= 64, 14)
            for row in web['processes']:
                # The real helper returns (processes, bind), and one invocation
                # binds only this PID's ancestry. Visit every known WebView.
                processes, bound = binder(probe, row['processId'], self.root_pid,
                                          runtime, self.root_handle)
                require(type(processes) is dict and callable(bound), 14)
            require(len(probe.handles) == len(web['processes']) + 1, 14)
            for pid, (_, _, record, _) in sorted(probe.handles.items()):
                if pid == self.root_pid:
                    handle, own = self.root_handle, False
                else:
                    handle, own = self.kernel.OpenProcess(0x101000, False, pid), True
                    require(handle is not None and int(handle) > 0, 14)
                self.handles[pid] = {'handle': int(handle), 'own': own,
                                     'creation': record['creation']}
                require(int(self.kernel.GetProcessId(handle)) == pid, 14)
                require(self._creation(handle) == record['creation'], 14)
                native = probe._times_session(pid, handle)
                require(native['pid'] == pid and native['creation'] == record['creation']
                        and native['session'] == record['session'], 14)
                probe.verify_process(pid, record)
            self.retained_count = len(self.handles)
            self._census(require_live_root=True)
        except BaseException:
            try:
                self.close()
            except BaseException:
                pass  # A cleanup error cannot replace this binding failure.
            raise

    def _creation(self, handle):
        values = [self.probe.W.FILETIME() for _ in range(4)]
        require(self.kernel.GetProcessTimes(handle, *[self.probe.ctypes.byref(x) for x in values]), 14)
        return int(values[0].dwHighDateTime) << 32 | int(values[0].dwLowDateTime)

    def _state(self, pid):
        record = self.handles[pid]
        handle = record['handle']
        require(int(self.kernel.GetProcessId(handle)) == pid, 14)
        require(self._creation(handle) == record['creation'], 14)
        state = int(self.kernel.WaitForSingleObject(handle, 0))
        require(state in (0, 258), 14)
        return state

    def _census(self, *, require_live_root):
        # Native WindowsProbe.processes checks ERROR_NO_MORE_FILES and its cap.
        rows = self.probe.process.processes()
        require(type(rows) is list and 0 < len(rows) <= 10000, 15)
        parents = {}
        for row in rows:
            pid = integer(row['processId'], 0, 0xffffffff)
            parent = integer(row['parentProcessId'], 0, 0xffffffff)
            require(pid not in parents, 15)
            parents[pid] = parent
        if require_live_root:
            require(self.root_pid in parents and self._state(self.root_pid) == 258, 15)
        known = set(self.handles)
        descendants = set(known)
        while True:
            expanded = descendants | {pid for pid, parent in parents.items() if parent in descendants}
            require(len(expanded) <= 65, 15)
            if expanded == descendants:
                break
            descendants = expanded
        try:
            require(descendants <= known, 15)
        except Rejected as error:
            try:
                error.pairedCensusObservation = _observe_census_failure(
                    rows, parents, known, descendants, self.root_pid,
                    self.handles[self.root_pid]['creation'], sealed=self.sealed,
                    require_live_root=require_live_root)
            except BaseException:
                pass  # Optional observation cannot replace the original guard.
            raise
        if require_live_root:
            for pid in known & set(parents):
                require(self._state(pid) == 258, 15)
            for pid in known:
                require(self._state(pid) != 258 or pid in parents, 15)

    def remember_primary(self, error):
        if self.operation_error is None and error is not None:
            self.operation_error = error

    def __exit__(self, error_type, error, traceback):
        # ExitStack invokes this before the original stop_session. Preserve its
        # primary, perform no input, and defer any observation cancellation until
        # the original queue/session cleanup has happened.
        self.sealed = True
        self.remember_primary(error)
        try:
            self._census(require_live_root=True)
        except BaseException as failure:
            self.checkpoint_error = failure
        return False

    def wait_retired(self):
        require(not self.closed and self.sealed, 15)
        start = self.clock()
        require(type(start) in (float, int) and math.isfinite(start) and start >= 0, 16)
        deadline, last = start + 10, start
        failure = self.checkpoint_error
        while True:
            states = [self._state(pid) for pid in self.handles]
            try:
                self._census(require_live_root=False)
            except BaseException as error:
                if failure is None:
                    failure = error
            now = self.clock()
            require(type(now) in (float, int) and math.isfinite(now)
                    and last <= now < deadline, 16)
            last = now
            if all(state == 0 for state in states):
                if failure is not None:
                    raise failure
                return {'retainedRootExited': True,
                        'retainedWebviewCount': len(self.handles) - 1,
                        'retainedWebviewsExited': True}
            self.sleeper(.05)

    def close(self):
        if self.closed:
            return
        self.closed = True
        first = None
        for record in self.handles.values():
            if record['own']:
                try:
                    require(bool(self.kernel.CloseHandle(record['handle'])), 14)
                except BaseException as error:
                    if first is None:
                        first = error
        self.handles.clear()
        try:
            self.probe.close()
        except BaseException as error:
            if first is None:
                first = error
        if first is not None:
            raise first


def invoke_print(printer, executable, fixture, case, folder, admit, oracle_error):
    """Keep the original exception; retire only handles captured by admission.

    The call shape matches virtual_print.print_document. A constructor failure
    before the callback yields no owned lease and cannot become an observation.
    """
    lease = None
    primary = None
    report = None
    retirement = None
    cleanup_error = None

    def admission(session, observed_folder):
        nonlocal lease
        require(lease is None and observed_folder == folder, 10)
        lease = admit(session, observed_folder)
        require(lease is not None and callable(getattr(lease, 'wait_retired', None))
                and callable(getattr(lease, 'close', None)), 10)
        return lease

    try:
        report = printer(executable, fixture, case, folder, admission=admission)
    except BaseException as error:
        primary = error
    if lease is not None:
        try:
            operation_error = getattr(lease, 'operation_error', None)
        except BaseException as error:
            operation_error = None
            cleanup_error = error
        if operation_error is not None:
            if primary is not operation_error:
                cleanup_error = primary if primary is not None else Rejected(11)
            primary = operation_error
    if lease is not None:
        try:
            retirement = lease.wait_retired()
            shape(retirement, ('retainedRootExited', 'retainedWebviewCount', 'retainedWebviewsExited'))
            require(retirement['retainedRootExited'] is True
                    and retirement['retainedWebviewsExited'] is True, 11)
            integer(retirement['retainedWebviewCount'], 1, 64)
        except BaseException as error:
            cleanup_error = error
        finally:
            try:
                lease.close()
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
    if cleanup_error is not None:
        if primary is not None:
            try:
                observed = BaseException.__getattribute__(cleanup_error, '__dict__').get('pairedCensusObservation')
                if type(observed) is dict and 'pairedCensusObservation' not in BaseException.__getattribute__(primary, '__dict__'):
                    primary.pairedCensusObservation = observed
            except BaseException:
                pass  # Keep the original operation/cancellation and cleanup priority.
        raise primary if primary is not None else cleanup_error
    if primary is not None:
        if lease is None:
            raise primary
        try:
            matched = oracle_error(primary) is True
        except BaseException:
            raise primary
        if not matched:
            raise primary
    require(lease is not None and retirement is not None, 10)
    return report, primary, retirement
