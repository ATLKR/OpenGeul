"""Original owned-job HANDLE coordinator; no PID reopen after admission.

NativeApi's concrete syscall implementation is separate. Portable seam tests
exercise these decisions and do not certify Windows job inheritance or cleanup.
"""
from dataclasses import dataclass, field
import time
from writer_server_observer_lifecycle import DiagnosticFailure, FailureCode


@dataclass(frozen=True, slots=True, repr=False)
class RetainedProcess:
    handle: object
    pid: int
    birth: int

    def __repr__(self): return '<RetainedProcess private>'


@dataclass(frozen=True, slots=True, repr=False)
class RetainedExitEvidence:
    original_witness: object = field(default=None, repr=False)
    identity_matches: bool = False
    engine_exit_observed: bool = False
    exit_code_observed: bool = False
    members_exited: bool = False
    job_empty: bool = False
    within_deadline: bool = False
    observed_qpc: object = None
    remote_retired: bool = False
    error_code: int = 0

    def __repr__(self): return '<RetainedExitEvidence numeric-only>'

    def numeric_projection(self):
        return {name: getattr(self, name) for name in (
            'identity_matches', 'engine_exit_observed', 'exit_code_observed',
            'members_exited', 'job_empty', 'within_deadline', 'observed_qpc',
            'remote_retired', 'error_code')}


@dataclass(frozen=True, slots=True)
class LocalRelease:
    closed_count: int
    failed_count: int
    pending_retained_count: int
    complete: bool


def _identity(value):
    return (isinstance(value, tuple) and len(value) == 2 and
            type(value[0]) is int and 0 < value[0] <= 0xffffffff and
            type(value[1]) is int and 0 < value[1] <= 0xffffffffffffffff)


class RetainedCohort:
    def __init__(self, api, launch, *, expected_worker, expected_engine,
                 auxiliary=None, expected_members=None, require_all_exit=False, initial_engine=None):
        self._api, self._launch, self._job = api, launch, launch.job
        self._host_handle, self._thread = launch.host, launch.thread
        self._host_identity = launch.identity
        self._worker_identity, self._engine_identity = expected_worker, expected_engine
        self._controller_handle = launch.controller_handle
        self._controller_identity, self._nonce = launch.controller_identity, launch.nonce
        self._members, self._orphan_handles, self._pending_local = {}, [], []
        self._confirmed_exited, self._closed_handles = set(), set()
        self._admission_attempted, self.admitted, self._retired = False, False, False
        self._released = False
        self._original_engine = None
        self.auxiliary, self._expected_members = auxiliary, expected_members
        self._require_all_exit = require_all_exit
        self.initial_engine=initial_engine
        if type(initial_engine) is RetainedProcess:self._members[initial_engine.pid]=initial_engine
        self.job_empty_observed = None
        if type(auxiliary) is RetainedProcess: self._members[auxiliary.pid] = auxiliary

    def __repr__(self): return '<RetainedCohort private>'

    @property
    def original_engine(self): return self._original_engine

    @property
    def auxiliary_closed(self): return self.auxiliary is None or self.auxiliary.handle in self._closed_handles

    @property
    def auxiliary_exit_observed(self):
        return None if self.auxiliary is None else self.auxiliary.handle in self._confirmed_exited

    @property
    def initial_engine_closed(self):
        return self.initial_engine is None or self.initial_engine.handle in self._closed_handles

    def _controller(self):
        if (self._launch.job != self._job or self._launch.host != self._host_handle or
                self._launch.controller_handle != self._controller_handle or
                self._launch.controller_identity != self._controller_identity or
                self._launch.nonce is not self._nonce or
                not _identity(self._controller_identity) or
                self._api.identity(self._controller_handle) != self._controller_identity or
                self._api.state(self._controller_handle)[0] != 258):
            raise DiagnosticFailure(FailureCode.GENERATION)

    def admit(self):
        """First, pre-S admission only; retains the entire coherent job census."""
        if self._admission_attempted:
            raise DiagnosticFailure(FailureCode.STAGE)
        self._admission_attempted = True
        try:
            l = self._launch
            if (l.failed is not False or l.uncertain is not False or l.resumed is not True or
                    l.creation_job_membership is not True or l.pre_resume_verified is not True or
                    self._job is None or self._host_handle is None):
                raise DiagnosticFailure(FailureCode.OWNERSHIP)
            expected = (self._host_identity, self._worker_identity, self._engine_identity)
            if not all(_identity(v) for v in expected) or len({v[0] for v in expected}) != 3:
                raise DiagnosticFailure(FailureCode.GENERATION)
            if (type(self._require_all_exit) is not bool or
                    (self.auxiliary is not None and (self._require_all_exit is not True or self._expected_members is None or type(self.auxiliary) is not RetainedProcess or
                    not _identity((self.auxiliary.pid, self.auxiliary.birth)) or self.auxiliary.pid in {v[0] for v in expected}))):
                raise DiagnosticFailure(FailureCode.GENERATION)
            if self.initial_engine is not None and (type(self.initial_engine) is not RetainedProcess or
                    self._expected_members is None or
                    (self.initial_engine.pid,self.initial_engine.birth)!=self._engine_identity or
                    self.initial_engine.handle in (self._host_handle,self._controller_handle,self._thread,self._job) or
                    self.auxiliary is not None and self.initial_engine.handle==self.auxiliary.handle):
                raise DiagnosticFailure(FailureCode.GENERATION)
            self._controller()
            pids = self._api.census(self._job)
            if (not isinstance(pids, tuple) or not 3 <= len(pids) <= 128 or len(set(pids)) != len(pids) or
                    any(type(p) is not int or not 0 < p <= 0xffffffff for p in pids) or
                    not {v[0] for v in expected}.issubset(pids)):
                raise DiagnosticFailure(FailureCode.OWNERSHIP)
            if self._expected_members is not None:
                members = self._expected_members
                if (type(members) is not tuple or not 3 <= len(members) <= 128 or
                        not all(_identity(value) for value in members) or len({value[0] for value in members}) != len(members) or
                        set(pids) != {value[0] for value in members} or not set(expected).issubset(members) or
                        (self.auxiliary is not None and (self.auxiliary.pid, self.auxiliary.birth) not in members)):
                    raise DiagnosticFailure(FailureCode.OWNERSHIP)
            for pid in pids:
                handle = self._host_handle if pid == self._host_identity[0] else (
                    self.auxiliary.handle if self.auxiliary is not None and pid == self.auxiliary.pid else None)
                try:
                    if handle is None and self.initial_engine is not None and pid==self.initial_engine.pid:
                        handle=self.initial_engine.handle
                    if handle is None:
                        handle = self._api.open_initial_member(pid, self._job)
                    value = self._api.identity(handle)
                    if not _identity(value) or value[0] != pid:
                        raise DiagnosticFailure(FailureCode.GENERATION)
                    if self._expected_members is not None and value not in self._expected_members:
                        raise DiagnosticFailure(FailureCode.GENERATION)
                    if self.auxiliary is not None and pid == self.auxiliary.pid:
                        if value != (self.auxiliary.pid, self.auxiliary.birth): raise DiagnosticFailure(FailureCode.GENERATION)
                    elif self.initial_engine is not None and pid==self.initial_engine.pid:
                        if value!=(self.initial_engine.pid,self.initial_engine.birth):raise DiagnosticFailure(FailureCode.GENERATION)
                    else: self._members[pid] = RetainedProcess(handle, *value)
                except Exception as exc:
                    retained = getattr(exc, 'retained_handle', None)
                    if retained is not None: self._orphan_handles.append(retained)
                    if handle is not None and pid not in self._members and handle != self._host_handle:
                        self._orphan_handles.append(handle)
                    raise
            for value in expected:
                member = self._members[value[0]]
                if (member.pid, member.birth) != value:
                    raise DiagnosticFailure(FailureCode.GENERATION)
            self._original_engine = self._members[self._engine_identity[0]]
            self._verify_retained(require_alive=True)
            self.admitted = True
        except DiagnosticFailure:
            raise
        except Exception:
            raise DiagnosticFailure(FailureCode.NATIVE) from None

    def _verify_retained(self, *, require_alive):
        self._controller()
        for member in self._members.values():
            if (self._api.identity(member.handle) != (member.pid, member.birth) or
                    self._api.member(member.handle, self._job) is not True):
                raise DiagnosticFailure(FailureCode.GENERATION)
            if require_alive:
                state = self._api.state(member.handle)
                if state[0] != 258:
                    error = DiagnosticFailure(FailureCode.GENERATION)
                    try:
                        if (type(state) is tuple and len(state) == 2 and
                                all(type(value) is int and 0 <= value <= 0xffffffff for value in state) and
                                _identity((member.pid, member.birth))):
                            error._member_state_origin = (member.pid, member.birth, *state)
                    except BaseException:
                        pass
                    raise error

    def verify(self, budget=None):
        if not self.admitted or self._released:
            raise DiagnosticFailure(FailureCode.OWNERSHIP)
        try:
            if budget is not None: budget.check(observation=True)
            self._verify_retained(require_alive=True)
            if set(self._api.census(self._job)) != set(self._members):
                raise DiagnosticFailure(FailureCode.OWNERSHIP)
            if budget is not None: budget.check(observation=True)
            return True
        except DiagnosticFailure:
            raise
        except Exception:
            raise DiagnosticFailure(FailureCode.NATIVE) from None

    def dispose_owned(self):
        """Zero-wait request on only the creation-owned original job HANDLE."""
        try:
            if self._released or self._job is None or self._job in self._closed_handles or self._launch.job != self._job:
                raise DiagnosticFailure(FailureCode.OWNERSHIP)
            if self._api.terminate_job(self._job) is not True:
                raise DiagnosticFailure(FailureCode.NATIVE)
            return True
        except DiagnosticFailure:
            raise
        except Exception:
            raise DiagnosticFailure(FailureCode.NATIVE) from None

    def confirm_original_exit(self, budget, *, sleeper=time.sleep):
        """Only original retained HANDLEs, Wait0 and one absolute D; no discovery."""
        original = self.original_engine
        if (self._released or not self.admitted or original is None or
                original is not self._members.get(self._engine_identity[0]) or
                (original.pid, original.birth) != self._engine_identity):
            return RetainedExitEvidence(original_witness=original, error_code=int(FailureCode.OWNERSHIP))
        try:
            for _ in range(4096):
                budget.check(observation=False)
                # A dead controller cannot authorize a new successful capture.
                self._controller()
                budget.check(observation=False)
                same, all_exited, engine_exited, code_seen = True, True, False, False
                exited_handles = set()
                for member in self._members.values():
                    budget.check(observation=False)
                    matches = self._api.identity(member.handle) == (member.pid, member.birth)
                    budget.check(observation=False)
                    if not matches:
                        raise DiagnosticFailure(FailureCode.GENERATION)
                    waited, code = self._api.state(member.handle)
                    budget.check(observation=False)
                    if waited not in (0, 258) or type(code) is not int or not 0 <= code <= 0xffffffff:
                        raise DiagnosticFailure(FailureCode.NATIVE)
                    all_exited = all_exited and waited == 0
                    if waited == 0: exited_handles.add(member.handle)
                    if member is original:
                        engine_exited, code_seen = waited == 0, True
                empty = self._api.census(self._job) == ()
                observed = budget.check(observation=False)
                self.job_empty_observed = empty
                retired = same and engine_exited and code_seen
                if retired and (not self._require_all_exit or (all_exited and empty)):
                    self._retired = True
                    self._confirmed_exited = exited_handles
                    return RetainedExitEvidence(original, same, engine_exited, code_seen,
                        all_exited, empty, True, observed, True, 0)
                remaining = budget.remaining_ms(observation=False)
                sleeper(min(.01, remaining / 1000))
            return RetainedExitEvidence(original_witness=original, error_code=int(FailureCode.UNKNOWN))
        except DiagnosticFailure as exc:
            return RetainedExitEvidence(original_witness=original, error_code=int(exc.code))
        except Exception:
            return RetainedExitEvidence(original_witness=original, error_code=int(FailureCode.NATIVE))

    def release_local(self):
        """Independent closes; unconfirmed original witnesses remain retained.

        The caller owns this bounded (at most 128-member) pending registry and
        must not start another case while it is nonempty. Closing the owned job
        can request KILL_ON_CLOSE; it still never proves original engine exit.
        The controller HANDLE belongs to the capture/controller owner, not here.
        """
        self._released = True
        closing, retained = [], []
        for member in self._members.values():
            (closing if member.handle in self._confirmed_exited else retained).append(member.handle)
        # A partial launch may have a retained host not yet in the member set.
        if self._host_handle is not None and self._host_handle not in [m.handle for m in self._members.values()]:
            retained.append(self._host_handle)
        closing += self._orphan_handles + [self._thread, self._job]
        closing += self._pending_local
        self._pending_local = []
        unique = []
        for handle in closing:
            if handle is not None and handle not in unique and handle not in self._closed_handles: unique.append(handle)
        closed = failed = 0
        try: launch_local_ok = self._api.release_launch_local(self._launch) is True
        except Exception: launch_local_ok = False
        if not launch_local_ok: failed += 1
        for handle in unique:
            try: succeeded = self._api.close(handle) is True
            except Exception: succeeded = False
            if succeeded: closed += 1; self._closed_handles.add(handle)
            else: failed += 1; self._pending_local.append(handle)
        self._orphan_handles = []
        return LocalRelease(closed, failed, len(retained), not retained and failed == 0)
