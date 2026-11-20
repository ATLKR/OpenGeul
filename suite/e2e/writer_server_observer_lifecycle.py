"""Writer-only runtime budget and launch boundary; no normal caller is changed.

Preparation precedes S. This module never claims a whole launch takes 30 seconds.
Opaque bindings and environment dictionaries are private, never report payloads.
"""
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
import re

FAMILY = 'writer-server-observer-diagnostic'
ENVIRONMENT = 'OPENGEUL_WRITER_SERVER_OBSERVER'
MAX_I64 = (1 << 63) - 1
_LAYOUT_SEAL = object()


class FailureCode(IntEnum):
    UNKNOWN = 0
    CLOCK = 1
    LATE = 2
    ENVIRONMENT = 3
    OWNERSHIP = 4
    GENERATION = 5
    NATIVE = 6
    STAGE = 7


class DiagnosticFailure(RuntimeError):
    def __init__(self, code):
        self.code = FailureCode(code)
        super().__init__('Writer diagnostic failure code ' + str(int(self.code)))


class _ClockBound:
    def __init__(self, clock):
        self.clock, self.last, self.invalid = clock, None, False
        self.original_sample = None
        try: self.frequency = clock.frequency
        except Exception: raise DiagnosticFailure(FailureCode.CLOCK) from None
        if type(self.frequency) is not int or not 0 < self.frequency <= MAX_I64 // 30:
            self.invalid = True
            raise DiagnosticFailure(FailureCode.CLOCK)

    def sample(self):
        try:
            value = self.clock.read()
            valid = (not self.invalid and type(self.clock.frequency) is int and
                     self.clock.frequency == self.frequency and type(value) is int and
                     0 < value <= MAX_I64 and (self.last is None or value >= self.last))
        except Exception:
            valid = False
        if not valid:
            self.invalid = True
            raise DiagnosticFailure(FailureCode.CLOCK)
        self.last = value
        if self.original_sample is None: self.original_sample = value
        return value


@dataclass(frozen=True, slots=True)
class OriginalWriterBudget:
    start_qpc: int
    cutoff_qpc: int
    deadline_qpc: int
    frequency: int
    _bound: _ClockBound = field(repr=False, compare=False)

    def __post_init__(self):
        if (type(self._bound) is not _ClockBound or
                any(type(v) is not int for v in (self.start_qpc, self.cutoff_qpc, self.deadline_qpc, self.frequency)) or
                self.frequency != self._bound.frequency or self.frequency <= 0 or
                self.start_qpc != self._bound.original_sample or self.start_qpc <= 0 or
                self.cutoff_qpc != self.start_qpc + 25 * self.frequency or
                self.deadline_qpc != self.start_qpc + 30 * self.frequency or self.deadline_qpc > MAX_I64):
            raise DiagnosticFailure(FailureCode.CLOCK)

    @classmethod
    def start(cls, clock):
        bound = _ClockBound(clock)
        start = bound.sample()
        if start > MAX_I64 - 30 * bound.frequency:
            raise DiagnosticFailure(FailureCode.CLOCK)
        return cls(start, start + 25 * bound.frequency, start + 30 * bound.frequency,
                   bound.frequency, bound)

    def check(self, *, observation):
        value = self._bound.sample()
        if value >= (self.cutoff_qpc if observation else self.deadline_qpc):
            raise DiagnosticFailure(FailureCode.LATE)
        return value

    def remaining_ms(self, *, observation):
        value = self.check(observation=observation)
        end = self.cutoff_qpc if observation else self.deadline_qpc
        return (end - value) * 1000 // self.frequency


class RuntimeSession:
    def __init__(self, clock):
        self._clock, self._begun, self.budget = clock, False, None
        self._execute_attempted = False

    def begin_runtime(self):
        if self._begun:
            raise DiagnosticFailure(FailureCode.STAGE)
        self._begun = True
        self.budget = OriginalWriterBudget.start(self._clock)
        return self.budget

    def execute(self, *, cohort, owner, capture_factory, verify_original,
                original_call, external_releases=()):
        """Sequence one runtime. The consumer owns its bounded MSAA watchdog.

        A callback is not preempted here. Without its same-budget WatchdogProof,
        or with a late/partial/failed helper, capture is incomplete. Retirement
        of the original engine remains an independently observed fact.
        """
        # A rejected second call owns no new resources and must not enter the
        # first call's finally or touch any already-closed HANDLE values.
        if self._execute_attempted or self._begun:
            raise DiagnosticFailure(FailureCode.STAGE)
        self._execute_attempted = True
        receipt, capture, snapshot, primary = LifecycleReceipt(), None, None, None
        releases_valid = (type(external_releases) is tuple and len(external_releases) <= 8 and
                          all(callable(release) for release in external_releases))
        release_callbacks = external_releases if releases_valid else ()

        def fault(exc):
            nonlocal primary
            if primary is None: primary = exc
            receipt.stage_error_count += 1
            code = exc.code if isinstance(exc, DiagnosticFailure) else FailureCode.STAGE
            if receipt.first_failure_code == 0: receipt.first_failure_code = int(code)

        def sample():
            if self.budget is None: return None
            try: return self.budget.check(observation=False)
            except DiagnosticFailure:
                receipt.late_or_invalid_clock_count += 1
                return None

        def cleanup(prefix, function, success=lambda value: value is not False):
            setattr(receipt, prefix + '_attempted', True)
            before = sample()
            try:
                value = function()
                after = sample()
                completed = success(value) and before is not None and after is not None
                setattr(receipt, prefix + '_completed', bool(completed))
                if after is not None: receipt.last_completed_qpc = after
                return value
            except Exception as exc:
                fault(exc)
                return None

        try:
            if not releases_valid:
                raise DiagnosticFailure(FailureCode.STAGE)
            if self._begun:
                raise DiagnosticFailure(FailureCode.STAGE)
            if cohort.verify() is not True or verify_original() is not True:
                raise DiagnosticFailure(FailureCode.OWNERSHIP)
            if getattr(owner, 'original_engine', None) is not cohort.original_engine:
                raise DiagnosticFailure(FailureCode.GENERATION)
            budget = self.begin_runtime()
            receipt.runtime_started = True
            capture = capture_factory(budget)  # Constructor must be inert.
            budget.check(observation=True)
            capture.create()
            budget.check(observation=True)

            def current_owner():
                budget.check(observation=True)
                valid = cohort.verify(budget) is True and verify_original() is True
                budget.check(observation=True)
                return valid

            if not current_owner(): raise DiagnosticFailure(FailureCode.GENERATION)
            capture.arm_once(owner, current_owner)
            budget.check(observation=True)
            receipt.armed = True
            receipt.original_call_attempted = True
            proof = original_call(budget)
            receipt.original_call_returned = True
            observed = budget.check(observation=True)
            receipt.original_call_within_cutoff = True
            receipt.watchdog_verified = _watchdog_valid(proof, budget, observed)
        except Exception as exc:
            fault(exc)
        finally:
            if capture is not None:
                cleanup('disable', capture.disable, lambda value: _capture_cleanup_ok(value, 'disable'))
                snapshot = cleanup('snapshot', capture.snapshot, lambda value: isinstance(value, dict))
            disposed = cleanup('dispose', cohort.dispose_owned, lambda value: value is True)
            receipt.forced_disposal_requested = disposed is True
            evidence = None
            receipt.exit_confirmation_attempted = True
            if self.budget is not None:
                before = sample()
                try:
                    evidence = cohort.confirm_original_exit(self.budget)
                    after = sample()
                    receipt.exit_confirmation_completed = before is not None and after is not None
                    receipt.remote_retired = _engine_retired(evidence, cohort.original_engine, self.budget)
                except Exception as exc:
                    fault(exc)
            if capture is not None:
                cleanup('retirement_join', lambda: capture.join_retirement(cohort.original_engine, evidence),
                        lambda value: isinstance(value, dict) and type(value.get('errorCode')) is int and value['errorCode'] == 0)
                cleanup('capture_release', lambda: capture.close_local(primary=primary),
                        lambda value: _capture_cleanup_ok(value, 'close', primary_present=primary is not None))
            cleanup('cohort_release', cohort.release_local,
                    lambda value: getattr(value, 'complete', False) is True)
            for release in release_callbacks:
                receipt.external_release_attempted_count += 1
                before = sample()
                try:
                    result = release()
                    after = sample()
                    if result is not False and before is not None and after is not None:
                        receipt.external_release_completed_count += 1
                except Exception as exc:
                    fault(exc)
            receipt.capture_incomplete = not (
                receipt.watchdog_verified and receipt.original_call_within_cutoff and
                _snapshot_complete(snapshot) and receipt.disable_completed and receipt.snapshot_completed and
                receipt.dispose_completed and receipt.exit_confirmation_completed and receipt.remote_retired and
                receipt.retirement_join_completed and receipt.capture_release_completed and
                receipt.cohort_release_completed and receipt.stage_error_count == 0 and
                receipt.external_release_attempted_count == receipt.external_release_completed_count)
        return receipt


@dataclass(frozen=True, slots=True, repr=False)
class WatchdogProof:
    budget: OriginalWriterBudget = field(repr=False)
    cutoff_qpc: int
    original_helper: object = field(repr=False)
    exit_helper: object = field(repr=False)
    helper_identity_matches: bool
    helper_exit_observed: bool
    helper_exit_qpc: int
    completed: bool
    timed_out: bool
    partial: bool

    def __repr__(self): return '<WatchdogProof private>'


def _watchdog_valid(proof, budget, observed):
    return bool(type(proof) is WatchdogProof and proof.budget is budget and
        proof.cutoff_qpc == budget.cutoff_qpc and proof.original_helper is not None and
        proof.exit_helper is proof.original_helper and proof.helper_identity_matches is True and
        proof.helper_exit_observed is True and proof.completed is True and proof.timed_out is False and
        proof.partial is False and type(proof.helper_exit_qpc) is int and
        budget.start_qpc <= proof.helper_exit_qpc <= observed < budget.cutoff_qpc)


def _engine_retired(evidence, original, budget):
    from writer_server_observer_cohort import RetainedExitEvidence
    return bool(type(evidence) is RetainedExitEvidence and original is not None and
        evidence.original_witness is original and evidence.identity_matches is True and
        evidence.engine_exit_observed is True and evidence.exit_code_observed is True and
        evidence.within_deadline is True and evidence.remote_retired is True and
        type(evidence.observed_qpc) is int and budget.start_qpc <= evidence.observed_qpc < budget.deadline_qpc)


def _snapshot_complete(value):
    return bool(isinstance(value, dict) and value.get('schemaVersion') == 1 and
        value.get('captureIncomplete') is False and value.get('originalBindingMatches') is True and
        value.get('admissionClosed') is True and value.get('captureGateClosed') is True and
        type(value.get('activeCount')) is int and value['activeCount'] == 0 and value.get('decoderErrors') == [])


def _capture_cleanup_ok(value, stage, *, primary_present=False):
    if not isinstance(value, dict): return False
    if stage == 'disable':
        return bool(value.get('admissionClosed') is True and value.get('captureGateClosed') is True and
                    value.get('errors') == [])
    if stage == 'close':
        # None means unacquired/unattempted. It cannot prove a complete release
        # of the full successful capture; partial create stays incomplete.
        return bool(value.get('unmapSucceeded') is True and value.get('mappingHandleClosed') is True and
                    value.get('libraryReleased') is True and value.get('cleanupErrors') == [] and
                    value.get('disableErrors') == [] and value.get('primaryPreserved') is primary_present)
    return False


@dataclass(slots=True)
class LifecycleReceipt:
    runtime_started: bool = False
    armed: bool = False
    original_call_attempted: bool = False
    original_call_returned: bool = False
    original_call_within_cutoff: bool = False
    watchdog_verified: bool = False
    disable_attempted: bool = False
    disable_completed: bool = False
    snapshot_attempted: bool = False
    snapshot_completed: bool = False
    dispose_attempted: bool = False
    dispose_completed: bool = False
    forced_disposal_requested: bool = False
    exit_confirmation_attempted: bool = False
    exit_confirmation_completed: bool = False
    retirement_join_attempted: bool = False
    retirement_join_completed: bool = False
    capture_release_attempted: bool = False
    capture_release_completed: bool = False
    cohort_release_attempted: bool = False
    cohort_release_completed: bool = False
    external_release_attempted_count: int = 0
    external_release_completed_count: int = 0
    remote_retired: bool = False
    capture_incomplete: bool = True
    first_failure_code: int = 0
    stage_error_count: int = 0
    late_or_invalid_clock_count: int = 0
    last_completed_qpc: object = None
    acceptance_eligible: bool = False
    whole_original_interval_covered: bool = False
    hard_deadline_enforcement_verified: bool = False
    normal_close_verified: bool = False

    def numeric_projection(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True, repr=False)
class RuntimeLayout:
    payload: Path
    windows: Path
    temp: Path
    program: Path
    core: Path
    _validated: object = field(default=None, repr=False, compare=False)

    def __repr__(self):
        return '<RuntimeLayout private>'

    @classmethod
    def validated(cls, payload, windows, temp):
        try:
            supplied = tuple(Path(p) for p in (payload, windows, temp))
            if not all(p.is_absolute() and ';' not in str(p) and
                       all(ord(c) >= 32 for c in str(p)) for p in supplied):
                raise ValueError()
            payload, windows, temp = tuple(p.resolve(strict=True) for p in supplied)
            program = payload / 'Office' / 'program'
            core = program / 'python-core-3.13.15'
            directories = (payload, windows, temp, windows / 'System32', program,
                           core, core / 'bin', core / 'lib', core / 'lib' / 'site-packages')
            if not all(p.is_dir() and p.resolve(strict=True) == p for p in directories):
                raise ValueError()
            if not all(p.is_file() and p.resolve(strict=True) == p for p in
                       (core / 'bin' / 'python.exe', program / 'fundamental.ini')):
                raise ValueError()
            return cls(payload, windows, temp, program, core, _LAYOUT_SEAL)
        except Exception:
            raise DiagnosticFailure(FailureCode.ENVIRONMENT) from None


def _private_descriptor_valid(value):
    if not isinstance(value, str) or len(value) > 128:
        return False
    match = re.fullmatch(r'1:([1-9][0-9]*):([1-9][0-9]*):([0-9a-f]{16}):131328:OpenGeulWriterServerObserver', value)
    return bool(match and int(match[1]) <= 0xffffffff and
                int(match[2]) <= 0xffffffffffffffff and int(match[3], 16) != 0)


def build_launch_environment(read_value, layout, private_descriptor):
    """Get five named bootstrap values, never enumerate or copy the host env.

    WorkerLaunch and native_windows later copy/extend this restricted child
    environment. Those existing copies are not claimed to be absent.
    """
    try:
        if (type(layout) is not RuntimeLayout or layout._validated is not _LAYOUT_SEAL or
                not _private_descriptor_valid(private_descriptor)):
            raise ValueError()
        names = ('SystemRoot', 'WINDIR', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')
        values = {}
        for name in names:
            value = read_value(name)
            if not isinstance(value, str) or not value or '\0' in value or ';' in value:
                raise ValueError()
            path = Path(value)
            if not path.is_absolute() or not path.is_dir():
                raise ValueError()
            values[name] = path.resolve(strict=True)
        if values['SystemRoot'] != layout.windows or values['WINDIR'] != layout.windows:
            raise ValueError()
        for name in ('APPDATA', 'LOCALAPPDATA'):
            values[name].relative_to(values['USERPROFILE'])
        result = {name: str(values[name]) for name in names}
        result.update(TEMP=str(layout.temp), TMP=str(layout.temp),
            PATH=';'.join(map(str, (layout.program, layout.windows / 'System32', layout.windows))),
            PYTHONHOME=str(layout.core),
            PYTHONPATH=';'.join(map(str, (layout.program, layout.core / 'lib', layout.core / 'lib' / 'site-packages'))),
            PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', UNO_PATH=str(layout.program),
            URE_BOOTSTRAP='vnd.sun.star.pathname:' + str(layout.program / 'fundamental.ini'))
        result[ENVIRONMENT] = private_descriptor
        return result
    except Exception:
        raise DiagnosticFailure(FailureCode.ENVIRONMENT) from None
