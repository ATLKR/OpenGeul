"""One owned blank-Writer numeric diagnostic; no ordinary Suite launch path.

Preparation is a distinct original QPC interval (55 work / 60 cleanup seconds).
Runtime S is created later by the frozen lifecycle. Native calls are not claimed
to be preemptible. No report contains the private launch/owner/provenance data.
"""
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
import argparse
import importlib.util
import json
import os
import secrets
import sys
import time
import threading

MAX_I64 = (1 << 63) - 1
_HANDOFF_SEAL = object()


class Code(IntEnum):
    INPUT = 1
    CLOCK = 2
    LATE = 3
    ADMISSION = 4
    LAUNCH = 5
    CLASSIFICATION = 6
    ATTACHMENT = 7
    FOCUS = 8
    CAPTURE = 9
    CLEANUP = 10
    NUMERIC = 11
    REPEATED = 12
    INTERNAL = 13


class RunnerFailure(RuntimeError):
    def __init__(self, code):
        self.code = Code(code)
        super().__init__('Writer runner failure code ' + str(int(self.code)))


class _Clock:
    def __init__(self, clock):
        self.clock, self.last, self.invalid = clock, None, False
        self.original = None
        try: self.frequency = clock.frequency
        except Exception: raise RunnerFailure(Code.CLOCK) from None
        if type(self.frequency) is not int or not 0 < self.frequency <= MAX_I64 // 60:
            raise RunnerFailure(Code.CLOCK)

    def sample(self):
        try:
            value = self.clock.read()
            good = (not self.invalid and type(value) is int and 0 < value <= MAX_I64 and
                    type(self.clock.frequency) is int and self.clock.frequency == self.frequency and
                    (self.last is None or value >= self.last))
        except Exception: good = False
        if not good:
            self.invalid = True
            raise RunnerFailure(Code.CLOCK)
        self.last = value
        if self.original is None: self.original = value
        return value


class _AdmissionToken:
    def __init__(self, values, clock):
        self.values, self.clock, self.used = values, clock, False


class _AdmissionOwner:
    def __init__(self,clock):self.clock,self.budget,self.completed=clock,None,False


@dataclass(frozen=True, slots=True, repr=False)
class AdmissionProof:
    start_qpc: int
    completed_qpc: int
    deadline_qpc: int
    frequency: int
    _clock: object = field(repr=False,compare=False)
    _token: object = field(repr=False,compare=False)
    _seal: object = field(repr=False,compare=False)

    def __post_init__(self):
        values=(self.start_qpc,self.completed_qpc,self.deadline_qpc,self.frequency)
        if (self._seal is not _HANDOFF_SEAL or type(self._token) is not _AdmissionToken or
                self._token.values != values or self._token.clock is not self._clock or
                type(self._clock) is not _Clock or self._clock.invalid or
                any(type(v) is not int for v in values) or self.start_qpc != self._clock.original or
                not self.start_qpc <= self.completed_qpc < self.deadline_qpc or
                self.deadline_qpc != self.start_qpc+300*self.frequency or
                self.frequency != self._clock.frequency or self.completed_qpc != self._clock.last):
            raise RunnerFailure(Code.CLOCK)

    def __repr__(self):return '<AdmissionProof private one-use handoff>'


@dataclass(frozen=True, slots=True)
class AdmissionBudget:
    start_qpc: int
    deadline_qpc: int
    frequency: int
    _clock: _Clock = field(repr=False,compare=False)
    _state: object = field(repr=False,compare=False)

    def __post_init__(self):
        if (type(self._clock) is not _Clock or
                type(self._state) is not _AdmissionOwner or self._state.clock is not self._clock or
                self._state.budget is not None or
                any(type(v) is not int for v in (self.start_qpc,self.deadline_qpc,self.frequency)) or
                self.start_qpc != self._clock.original or self.frequency != self._clock.frequency or
                self.deadline_qpc != self.start_qpc+300*self.frequency or self.deadline_qpc>MAX_I64):
            raise RunnerFailure(Code.CLOCK)
        self._state.budget=self

    @classmethod
    def start(cls,clock):
        bound=_Clock(clock);start=bound.sample()
        if start>MAX_I64-300*bound.frequency:raise RunnerFailure(Code.CLOCK)
        return cls(start,start+300*bound.frequency,bound.frequency,bound,_AdmissionOwner(bound))

    def check(self,*,observation=True):
        if self._state.budget is not self or self._state.completed:raise RunnerFailure(Code.REPEATED)
        value=self._clock.sample()
        if value>=self.deadline_qpc:raise RunnerFailure(Code.LATE)
        return value

    def complete(self):
        completed=self.check()
        self._state.completed=True
        values=(self.start_qpc,completed,self.deadline_qpc,self.frequency)
        return AdmissionProof(*values,self._clock,_AdmissionToken(values,self._clock),_HANDOFF_SEAL)


@dataclass(frozen=True, slots=True)
class PreparationBudget:
    start_qpc: int
    cutoff_qpc: int
    deadline_qpc: int
    frequency: int
    _clock: _Clock = field(repr=False, compare=False)
    _handoff: object = field(default=None,repr=False,compare=False)

    def __post_init__(self):
        origin=self._clock.original if self._handoff is None and type(self._clock) is _Clock else None
        if self._handoff is not None:
            proof=self._handoff
            if (type(proof) is not AdmissionProof or proof._clock is not self._clock or
                    proof._token.used is not True or proof._seal is not _HANDOFF_SEAL):raise RunnerFailure(Code.CLOCK)
            origin=proof.completed_qpc
        if (type(self._clock) is not _Clock or self.start_qpc != origin or
                any(type(v) is not int for v in (self.start_qpc, self.cutoff_qpc, self.deadline_qpc, self.frequency)) or
                self.frequency != self._clock.frequency or self.start_qpc <= 0 or
                self.cutoff_qpc != self.start_qpc + 55 * self.frequency or
                self.deadline_qpc != self.start_qpc + 60 * self.frequency or self.deadline_qpc > MAX_I64):
            raise RunnerFailure(Code.CLOCK)

    @classmethod
    def start(cls, clock):
        bound = _Clock(clock); start = bound.sample()
        if start > MAX_I64 - 60 * bound.frequency: raise RunnerFailure(Code.CLOCK)
        return cls(start, start + 55 * bound.frequency, start + 60 * bound.frequency, bound.frequency, bound)

    @classmethod
    def from_admission(cls,proof):
        if type(proof) is not AdmissionProof:raise RunnerFailure(Code.CLOCK)
        proof.__post_init__()
        if proof._token.used:raise RunnerFailure(Code.CLOCK)
        proof._token.used=True
        try:
            frequency=proof._clock.clock.frequency
            if type(frequency) is not int or frequency!=proof.frequency:raise ValueError()
        except Exception:
            proof._clock.invalid=True
            raise RunnerFailure(Code.CLOCK) from None
        origin=proof.completed_qpc
        if origin>MAX_I64-60*proof.frequency:raise RunnerFailure(Code.CLOCK)
        # No new clock sample, origin or deadline is introduced in the handoff.
        return cls(origin,origin+55*proof.frequency,origin+60*proof.frequency,proof.frequency,proof._clock,proof)

    def check(self, *, observation=True):
        value = self._clock.sample()
        if value >= (self.cutoff_qpc if observation else self.deadline_qpc): raise RunnerFailure(Code.LATE)
        return value

    def remaining_ms(self, *, observation=True):
        value = self.check(observation=observation)
        return ((self.cutoff_qpc if observation else self.deadline_qpc) - value) * 1000 // self.frequency


_OBSERVATION_MAX = {'schemaVersion': 1, 'verified': 1, 'stageCode': 14, 'hresult': 0xffffffff,
    'rootRole': 0x7fffffff, 'documentRole': 0x7fffffff, 'focusedRole': 0x7fffffff,
    'focusedState': 0x7fffffff, 'focusVariantType': 0xffff, 'parentCount': 32,
    'ia2Supported': 1, 'textSupported': 1, 'ownerBefore': 1, 'ownerAfter': 1,
    'referencesAcquired': 256, 'referencesReleased': 256, 'variantsCreated': 64,
    'variantsCleared': 64, 'cleanupFailure': 1, 'cleanupHresult': 0xffffffff, 'ownerReleased': 1}
_FOCUS_MAX = {'attempted': 1, 'returned': 1, 'hrObserved': 1, 'hr': 0xffffffff, 'vtObserved': 1, 'rejectCode': 5}
_MSAA_RAW_KEYS = {'schemaVersion', 'msaaVerified', 'observation', 'helperIdentityMatches',
    'helperExitObserved', 'helperExitQpc', 'helperExitCode', 'terminationRequested', 'terminationReturned',
    'errors', 'cleanupErrors', 'normalAcceptance', 'fullEngineQualified', 'acceptanceEligible',
    'hardDeadlineEnforcementVerified', 'parentCleanupPidReopens', 'childOriginalReadOnlyAdmissionPathReused',
    'childOwnerAdmissionVerified', 'pendingRetainedCount', 'cleanupComplete'}
MSAA_KEYS = {'msaaVerified', 'stageCode', 'getAccFocusAttempted', 'getAccFocusReturned',
    'hresultObserved', 'hresultUnsigned', 'vtObserved', 'focusVariantType', 'rejectCode',
    'sOkObserved', 'emptyVariantObserved', 'helperExitObserved', 'helperExitZero',
    'helperExitQpc', 'pendingRetainedCount', 'cleanupComplete', 'cleanupFailure', 'cleanupHresult',
    'ownerReleased', 'referencesAcquired', 'referencesReleased', 'variantsCreated', 'variantsCleared'}


def _uint(value, maximum): return type(value) is int and 0 <= value <= maximum


def project_msaa(raw):
    if type(raw) is not dict or not raw.keys() <= _MSAA_RAW_KEYS: raise RunnerFailure(Code.NUMERIC)
    result = {key: None for key in MSAA_KEYS}
    verified = raw.get('msaaVerified')
    if verified is not None and type(verified) is not bool: raise RunnerFailure(Code.NUMERIC)
    result['msaaVerified'] = verified
    for name in ('helperExitObserved', 'cleanupComplete'):
        value = raw.get(name)
        if value is not None and type(value) is not bool: raise RunnerFailure(Code.NUMERIC)
        result[name] = value
    for name, maximum in (('helperExitQpc', MAX_I64), ('pendingRetainedCount', 128)):
        value = raw.get(name)
        if value is not None and not _uint(value, maximum): raise RunnerFailure(Code.NUMERIC)
        result[name] = value
    code = raw.get('helperExitCode')
    if code is not None and not _uint(code, 0xffffffff): raise RunnerFailure(Code.NUMERIC)
    result['helperExitZero'] = code == 0 if code is not None and result['helperExitObserved'] is True else None
    observed = raw.get('observation')
    if observed is None: return result
    if type(observed) is not dict or not observed.keys() <= _OBSERVATION_MAX.keys() | {'focusCall'}:
        raise RunnerFailure(Code.NUMERIC)
    if any(not _uint(value, _OBSERVATION_MAX[key]) for key, value in observed.items() if key != 'focusCall'):
        raise RunnerFailure(Code.NUMERIC)
    if not {'verified', 'stageCode', 'hresult', 'focusVariantType'} <= observed.keys(): raise RunnerFailure(Code.NUMERIC)
    result['stageCode'], result['focusVariantType'] = observed['stageCode'], observed['focusVariantType']
    for key in ('cleanupHresult','referencesAcquired','referencesReleased','variantsCreated','variantsCleared'):
        result[key] = observed.get(key)
    for key in ('cleanupFailure','ownerReleased'):
        if key in observed: result[key] = bool(observed[key])
    if verified is not None and verified != bool(observed['verified']): raise RunnerFailure(Code.NUMERIC)
    focus = observed.get('focusCall')
    if focus is None: return result
    if type(focus) is not dict or focus.keys() != _FOCUS_MAX.keys() or any(not _uint(focus[k], v) for k, v in _FOCUS_MAX.items()):
        raise RunnerFailure(Code.NUMERIC)
    result.update(getAccFocusAttempted=bool(focus['attempted']), getAccFocusReturned=bool(focus['returned']),
        hresultObserved=bool(focus['hrObserved']), hresultUnsigned=focus['hr'], vtObserved=bool(focus['vtObserved']), rejectCode=focus['rejectCode'],
        sOkObserved=focus['hrObserved'] == 1 and focus['hr'] == 0,
        emptyVariantObserved=focus['vtObserved'] == 1 and observed['focusVariantType'] == 0)
    return result


ROW_MAX = {'kind': 3, 'phase': 11, 'datum': 6, 'scopeOrdinal': 2048, 'parentScopeOrdinal': 2048,
           'qpc': MAX_I64, 'depth': 32, 'threadOrdinal': 2048, 'eventOrdinal': 2048}


def _event(kind, phase, datum):
    if phase == 10: return datum in ((1, 2, 3) if kind == 3 else (0,))
    if phase == 11: return datum == 0
    if kind == 2: return (phase == 1 and datum == 0 or phase == 2 and 1 <= datum <= 6 or
        phase in (3, 4) and datum in (1, 2) or phase == 5 and 0 <= datum <= 3)
    if kind == 3: return (phase == 5 and datum in (0, 1, 3) or phase == 6 and datum in (2, 3) or
        phase in (7, 8) and datum in (1, 2, 3))
    return kind == 1 and phase == 9 and datum in (1, 2, 3)


def project_rows(rows):
    if type(rows) is not list or len(rows) > 2048: raise RunnerFailure(Code.NUMERIC)
    result = []
    for row in rows:
        if (type(row) is not dict or row.keys() != ROW_MAX.keys() or
                any(not _uint(row[k], maximum) for k, maximum in ROW_MAX.items()) or
                any(row[k] == 0 for k in ('kind', 'scopeOrdinal', 'qpc', 'depth', 'threadOrdinal', 'eventOrdinal')) or
                not _event(row['kind'], row['phase'], row['datum'])):
            raise RunnerFailure(Code.NUMERIC)
        result.append({key: row[key] for key in ROW_MAX})
    return result


_RUNTIME_BOOL = ('runtime_started armed original_call_attempted original_call_returned original_call_within_cutoff '
    'watchdog_verified disable_attempted disable_completed snapshot_attempted snapshot_completed dispose_attempted '
    'dispose_completed forced_disposal_requested exit_confirmation_attempted exit_confirmation_completed '
    'retirement_join_attempted retirement_join_completed capture_release_attempted capture_release_completed '
    'cohort_release_attempted cohort_release_completed remote_retired capture_incomplete acceptance_eligible '
    'whole_original_interval_covered hard_deadline_enforcement_verified normal_close_verified').split()
_RUNTIME_INT = {'external_release_attempted_count': 8, 'external_release_completed_count': 8,
    'first_failure_code': 7, 'stage_error_count': 64, 'late_or_invalid_clock_count': 64, 'last_completed_qpc': MAX_I64}
_PREP_BOOL = ('started admissionVerified launchAttempted launchResumed rolesClassified cohortAdmitted '
    'attachmentBound focusReady helperPrepared runtimeEntered cleanupAttempted disposalRequested '
    'hostExitObserved originalEngineExitObserved cleanupComplete').split()
_PREP_INT = {'startQpc': MAX_I64, 'cutoffQpc': MAX_I64, 'deadlineQpc': MAX_I64, 'frequency': MAX_I64,
    'lastQpc': MAX_I64, 'classificationCount': 128, 'focusSampleCount': 4096, 'activationCount': 1,
    'inputCount': 0, 'cleanupErrorCount': 64, 'pendingRetainedCount': 256}
_ADMISSION_BOOL=('started consumerAttempted consumerReturned descriptorVerified completedWithinDeadline handoffComplete durationKnown').split()
_ADMISSION_INT={'startQpc':MAX_I64,'deadlineQpc':MAX_I64,'frequency':MAX_I64,'lastObservedQpc':MAX_I64,
    'completedQpc':MAX_I64,'durationQpc':MAX_I64,'errorCode':13}
_FOCUS_BOOL = ('ready query_succeeded foreground_owned focus_within_child capture_clear menu_clear flags_clear').split()
_FOCUS_INT = {'sampled_before_qpc':MAX_I64,'sampled_after_qpc':MAX_I64}
_SNAP_BOOL = ('captureIncomplete admissionClosed captureGateClosed originalBindingMatches '
    'wholeOriginalIntervalCovered originalClientAttributionUnknown').split()
_SNAP_INT = {'schemaVersion': 1, 'activeCount': 0xffffffff, 'sessionReadyObserved': 0xffffffff,
    'rootBoundObserved': 0xffffffff, 'reservedCount': 0xffffffff, 'committedCount': 2048,
    'dropped': 0xffffffff, 'overflow': 0xffffffff, 'incompleteMask': 0xffffffff, 'rejected': 0xffffffff,
    'expired': 0xffffffff, 'cleanupErrorsCount': 0xffffffff, 'normalAcceptance': 0, 'fullEngineQualified': 0}
_SNAP_KEYS = set(_SNAP_BOOL) | _SNAP_INT.keys() | {'decoderErrors', 'rows', 'uncommittedOrdinals'}


def _section(value, booleans, integers):
    if type(value) is not dict or value.keys() != set(booleans) | integers.keys(): raise RunnerFailure(Code.NUMERIC)
    for key in booleans:
        if value[key] is not None and type(value[key]) is not bool: raise RunnerFailure(Code.NUMERIC)
    for key, maximum in integers.items():
        if value[key] is not None and not _uint(value[key], maximum): raise RunnerFailure(Code.NUMERIC)
    return dict(value)


def project_snapshot(value):
    if type(value) is not dict or value.keys() != _SNAP_KEYS: raise RunnerFailure(Code.NUMERIC)
    base = {key: value[key] for key in set(_SNAP_BOOL) | _SNAP_INT.keys()}
    result = _section(base, _SNAP_BOOL, _SNAP_INT)
    for key, maximum in (('decoderErrors', 64), ('uncommittedOrdinals', 2048)):
        items = value[key]
        if type(items) is not list or len(items) > 2048 or any(not _uint(item, maximum) for item in items):
            raise RunnerFailure(Code.NUMERIC)
        result[key] = list(items)
    result['rows'] = project_rows(value['rows'])
    if (result['wholeOriginalIntervalCovered'] is not False or
            result['originalClientAttributionUnknown'] is not True or
            result['normalAcceptance'] != 0 or result['fullEngineQualified'] != 0): raise RunnerFailure(Code.NUMERIC)
    return result


def empty_report():
    snapshot = {key: None for key in _SNAP_KEYS}
    snapshot.update(schemaVersion=1, captureIncomplete=True, wholeOriginalIntervalCovered=False,
        originalClientAttributionUnknown=True, normalAcceptance=0, fullEngineQualified=0,
        decoderErrors=[], rows=[], uncommittedOrdinals=[])
    report={'schemaVersion': 1, 'stageCode': 0, 'failureCode': 0, 'captureIncomplete': True,
        'normalAcceptance': False, 'fullEngineQualified': False, 'acceptanceEligible': False, 'guiVerified': False,
        'wholeOriginalIntervalCovered': False, 'originalClientAttributionUnknown': True,
        'hardDeadlineEnforcementVerified': False, 'preparation': {key: None for key in set(_PREP_BOOL) | _PREP_INT.keys()},
        'runtime': {key: None for key in set(_RUNTIME_BOOL) | _RUNTIME_INT.keys()},
        'editorFocus': {key: None for key in set(_FOCUS_BOOL) | _FOCUS_INT.keys()},
        'msaa': {key: None for key in MSAA_KEYS}, 'snapshot': snapshot, 'pendingRetainedCount': 0, 'caseCount': 1}
    report['admission']={key:None for key in set(_ADMISSION_BOOL)|_ADMISSION_INT.keys()}
    report['preparation']['started']=False
    return report


def validate_public_report(report):
    if type(report) is not dict or report.keys() != empty_report().keys(): raise RunnerFailure(Code.NUMERIC)
    fixed = {'schemaVersion': 1, 'caseCount': 1, 'normalAcceptance': False, 'fullEngineQualified': False,
        'acceptanceEligible': False, 'guiVerified': False, 'wholeOriginalIntervalCovered': False,
        'originalClientAttributionUnknown': True, 'hardDeadlineEnforcementVerified': False}
    for key, expected in fixed.items():
        if type(report[key]) is not type(expected) or report[key] != expected: raise RunnerFailure(Code.NUMERIC)
    if type(report['captureIncomplete']) is not bool: raise RunnerFailure(Code.NUMERIC)
    for key, maximum in (('stageCode', 10), ('failureCode', 13), ('pendingRetainedCount', 512)):
        if not _uint(report[key], maximum): raise RunnerFailure(Code.NUMERIC)
    _section(report['preparation'], _PREP_BOOL, _PREP_INT)
    _section(report['admission'], _ADMISSION_BOOL, _ADMISSION_INT)
    admission,prep=report['admission'],report['preparation']
    if admission['handoffComplete'] is True:
        if (admission['completedWithinDeadline'] is not True or admission['durationKnown'] is not True or
                prep['started'] is not True or admission['completedQpc'] != prep['startQpc'] or
                admission['frequency'] != prep['frequency'] or
                any(type(admission[key]) is not int for key in ('startQpc','completedQpc','durationQpc','deadlineQpc','frequency')) or
                not admission['startQpc'] <= admission['completedQpc'] < admission['deadlineQpc'] or
                admission['durationQpc'] != admission['completedQpc']-admission['startQpc'] or
                admission['deadlineQpc'] != admission['startQpc']+300*admission['frequency']):raise RunnerFailure(Code.NUMERIC)
    _section(report['runtime'], _RUNTIME_BOOL, _RUNTIME_INT)
    _section(report['editorFocus'], _FOCUS_BOOL, _FOCUS_INT)
    project_snapshot(report['snapshot'])
    if type(report['msaa']) is not dict or report['msaa'].keys() != MSAA_KEYS: raise RunnerFailure(Code.NUMERIC)
    for key, value in report['msaa'].items():
        maximum = {'stageCode':14,'hresultUnsigned':0xffffffff,'focusVariantType':0xffff,'rejectCode':5,
            'helperExitQpc':MAX_I64,'pendingRetainedCount':128,'cleanupHresult':0xffffffff,
            'referencesAcquired':256,'referencesReleased':256,'variantsCreated':64,'variantsCleared':64}.get(key)
        if value is not None and not (_uint(value, maximum) if maximum is not None else type(value) is bool):
            raise RunnerFailure(Code.NUMERIC)
    return report


@dataclass(frozen=True, slots=True, repr=False)
class RunnerInputs:
    output: Path
    baseline: Path
    artifact: Path
    diagnostic_lock: Path
    source_lock: Path
    expected_suite_source_commit: str
    prepared_library: dict = field(repr=False)
    host_python: Path
    helper_script: Path
    windows: Path
    work_root: Path
    def __repr__(self): return '<RunnerInputs private>'


class QpcClock:
    def __init__(self, api): self.api, self.frequency = api, api.qpc_frequency()
    def read(self): return self.api.qpc_read()


class NativeComponents:
    """Concrete production imports. Root materializes the prepared Suite layout.

    Import/NativeApi bootstrap precedes the measured preparation interval. It
    does not create an Office process. Synchronous calls are checked on return.
    """
    def __init__(self):
        from writer_server_observer_win32 import NativeApi
        from writer_server_observer_cohort import RetainedCohort
        from writer_server_observer_lifecycle import RuntimeLayout, RuntimeSession, build_launch_environment
        from writer_server_observer_capture import Descriptor, OriginalOwnerBinding, PreparedCapture, NativeBackend
        from writer_server_observer_msaa import HostRuntime, PreparedMsaaHelper
        from writer_server_observer_prepare_native import PreparationNativeApi
        self.api = NativeApi()
        self.clock = QpcClock(self.api)
        self.prep = PreparationNativeApi(self.api)
        self.Cohort, self.Session = RetainedCohort, RuntimeSession
        self.Descriptor, self.Owner, self.Capture = Descriptor, OriginalOwnerBinding, PreparedCapture
        self.Backend, self.Layout, self.HostRuntime, self.Helper = NativeBackend, RuntimeLayout, HostRuntime, PreparedMsaaHelper
        self.environment = build_launch_environment
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'stage-writer-server-observer.py'
        spec = importlib.util.spec_from_file_location('_writer_observer_stage', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.require_stage = module.require_writer_observer_stage


class _CaptureTap:
    def __init__(self, capture): self.capture, self.saved_snapshot, self.saved_cleanup = capture, None, None
    def create(self): return self.capture.create()
    def arm_once(self, owner, verify): return self.capture.arm_once(owner, verify)
    def disable(self): return self.capture.disable()
    def snapshot(self):
        value = self.capture.snapshot()
        self.saved_snapshot = project_snapshot(value)
        return value
    def join_retirement(self, original, evidence): return self.capture.join_retirement(original, evidence)
    def close_local(self, primary=None):
        self.saved_cleanup = self.capture.close_local(primary=primary)
        return self.saved_cleanup
    def local_resources_released(self):
        value = self.saved_cleanup
        return (type(value) is dict and value.keys() == {'unmapSucceeded','mappingHandleClosed','libraryReleased',
                'cleanupErrors','disableErrors','primaryPreserved'} and value.get('libraryReleased') is True and
            value.get('cleanupErrors') == [] and value.get('disableErrors') == [] and
            all(value.get(key) is True or value.get(key) is None for key in
                ('unmapSucceeded','mappingHandleClosed','libraryReleased')))


class _CohortTap:
    def __init__(self, cohort): self.cohort, self.release = cohort, None
    @property
    def original_engine(self): return self.cohort.original_engine
    def verify(self, budget=None): return self.cohort.verify(budget)
    def dispose_owned(self): return self.cohort.dispose_owned()
    def confirm_original_exit(self, budget): return self.cohort.confirm_original_exit(budget)
    def release_local(self):
        self.release = self.cohort.release_local()
        return self.release


# Strong private references only. They are never serialized, inspected by PID,
# retried, or used to authorize another case.
_PENDING_CASES = []
_CASE_LOCK = threading.Lock()
_CASE_STARTED = False


class DedicatedWriterRunner:
    def __init__(self, components, *, read_value=None, pause=time.sleep, nonce=None):
        self.c = components
        self.read_value = read_value if read_value is not None else lambda key: os.environ.get(key)
        self.pause, self.nonce, self.attempted = pause, nonce, False
        self._private_pending = []

    def __repr__(self): return '<DedicatedWriterRunner private>'

    def _fault(self, report, code):
        if report['failureCode'] == 0: report['failureCode'] = int(code)
        report['captureIncomplete'] = True

    def _checked(self, budget, function, *args, **kwargs):
        budget.check(observation=True)
        value = function(*args, **kwargs)
        budget.check(observation=True)
        return value

    def _pause(self, budget):
        self.pause(min(.05, budget.remaining_ms(observation=True) / 1000))
        budget.check(observation=True)

    def _classify(self, launch, images, budget):
        api, handles, roles = self.c.api, [], {}
        try:
            pids = self._checked(budget, api.census, launch.job)
            if type(pids) is not tuple or len(pids) > 128 or len(set(pids)) != len(pids): raise RunnerFailure(Code.CLASSIFICATION)
            if launch.identity[0] not in pids: raise RunnerFailure(Code.CLASSIFICATION)
            for pid in pids:
                handle = launch.host if pid == launch.identity[0] else None
                try:
                    if handle is None:
                        budget.check(observation=True)
                        handle = api.open_initial_member(pid, launch.job)
                        handles.append(handle)
                        budget.check(observation=True)
                    identity = self._checked(budget, api.identity, handle)
                    if (type(identity) is not tuple or len(identity) != 2 or identity[0] != pid or
                            not all(type(v) is int and v > 0 for v in identity) or
                            self._checked(budget, api.member, handle, launch.job) is not True or
                            self._checked(budget, api.state, handle)[0] != 258): raise RunnerFailure(Code.CLASSIFICATION)
                    image = Path(self.c.prep.process_image(handle, check=budget.check)).resolve(strict=True)
                    role = next((name for name, expected in images.items() if image == expected), None)
                    if role is None or role in roles or (role == 'host') != (handle == launch.host): raise RunnerFailure(Code.CLASSIFICATION)
                    if role == 'host' and identity != launch.identity: raise RunnerFailure(Code.CLASSIFICATION)
                    roles[role] = identity
                except Exception as exc:
                    retained = getattr(exc, 'retained_handle', None)
                    if retained is not None and retained not in handles: handles.append(retained)
                    raise
            return roles
        finally:
            for handle in handles:
                try: closed = api.close(handle) is True
                except Exception: closed = False
                if not closed: self._private_pending.append(handle)
            if self._private_pending: raise RunnerFailure(Code.CLEANUP)

    def execute(self, inputs):
        global _CASE_STARTED
        if self.attempted: raise RunnerFailure(Code.REPEATED)
        self.attempted = True
        report, c = empty_report(), self.c
        with _CASE_LOCK:
            if _CASE_STARTED:
                self._fault(report, Code.REPEATED)
                return validate_public_report(report)
            _CASE_STARTED = True
        prep = report['preparation']
        admission = budget = session = launch = cohort = probe = backend = controller = capture = None
        runtime_entered = backend_transferred = controller_closed = False
        if _PENDING_CASES:
            self._fault(report, Code.CLEANUP)
            report['pendingRetainedCount'] = len(_PENDING_CASES)
            return validate_public_report(report)
        try:
            admission=AdmissionBudget.start(c.clock)
            report['admission'].update(started=True,startQpc=admission.start_qpc,deadlineQpc=admission.deadline_qpc,
                frequency=admission.frequency,consumerAttempted=False,consumerReturned=False,descriptorVerified=False,
                completedWithinDeadline=False,handoffComplete=False,durationKnown=False,errorCode=0)
            report['stageCode'] = 1
            if type(inputs) is not RunnerInputs: raise RunnerFailure(Code.INPUT)
            report['admission']['consumerAttempted']=True
            admission.check()
            descriptor = c.require_stage(output=inputs.output, baseline=inputs.baseline,
                artifact=inputs.artifact, diagnostic_lock=inputs.diagnostic_lock, source_lock=inputs.source_lock,
                expected_suite_source_commit=inputs.expected_suite_source_commit, check=admission.check)
            report['admission']['consumerReturned']=True
            admission.check()
            if (type(descriptor) is not dict or descriptor.get('family') != 'writer-server-observer-diagnostic' or
                    descriptor.get('architecture') != 'arm64' or descriptor.get('diagnosticOnly') is not True or
                    any(descriptor.get(k) is not False for k in ('fullEngineQualified','acceptanceEligible','guiVerified')) or
                    Path(descriptor.get('payloadRoot', '')).resolve(strict=True) != Path(inputs.output).resolve(strict=True) or
                    Path(descriptor.get('runtimeRoot','')).resolve(strict=True) != Path(inputs.output).resolve(strict=True)/'Office' or
                    any(type(descriptor.get(k)) is not int or descriptor[k] != v for k,v in
                        (('ipcVersion',1),('sinkAbiVersion',2),('mappingBytes',131328),('descriptorSchemaVersion',1)))):
                raise RunnerFailure(Code.ADMISSION)
            binaries = descriptor.get('binaries')
            if (type(binaries) is not list or len(binaries) != 2 or
                    {item.get('path') for item in binaries if type(item) is dict} != {'program/UAccCOM.dll','program/winaccessibility.dll'} or
                    any(type(item) is not dict or item.keys() != {'path','bytes','sha256','machine'} or
                        not _uint(item.get('bytes'),MAX_I64) or item['bytes'] == 0 or item.get('machine') != 43620 or
                        type(item.get('sha256')) is not str or len(item['sha256']) != 64 or
                        any(c not in '0123456789abcdef' for c in item['sha256']) for item in binaries)):
                raise RunnerFailure(Code.ADMISSION)
            report['admission']['descriptorVerified']=True
            proof=admission.complete()
            report['admission'].update(completedWithinDeadline=True,completedQpc=proof.completed_qpc,
                durationQpc=proof.completed_qpc-proof.start_qpc,durationKnown=True)
            budget=PreparationBudget.from_admission(proof)
            report['admission']['handoffComplete']=True
            prep.update(started=True, startQpc=budget.start_qpc, cutoffQpc=budget.cutoff_qpc,
                deadlineQpc=budget.deadline_qpc, frequency=budget.frequency, activationCount=0, inputCount=0,
                classificationCount=0, focusSampleCount=0, cleanupErrorCount=0, pendingRetainedCount=0)
            prep['admissionVerified'] = True
            work = Path(inputs.work_root)
            budget.check(observation=True)
            if not work.is_absolute() or work.exists() or work.parent.resolve(strict=True) != work.parent:
                raise RunnerFailure(Code.INPUT)
            output = Path(inputs.output).resolve(strict=True)
            baseline = Path(inputs.baseline).resolve(strict=True)
            if work.is_relative_to(output) or work.is_relative_to(baseline): raise RunnerFailure(Code.INPUT)
            work.mkdir(mode=0o700)
            layout = self._checked(budget, c.Layout.validated, output, inputs.windows, work)
            host_runtime = self._checked(budget, c.HostRuntime.validated, inputs.host_python, inputs.helper_script,
                inputs.windows, work, layout.program)
            images = {'host': output/'OpenGeul.Office.exe', 'worker': layout.core/'bin'/'python.exe',
                'engine': layout.program/'soffice.bin', 'launcher': layout.program/'soffice.exe'}
            images = {key: self._checked(budget, path.resolve, strict=True) for key,path in images.items()}
            budget.check(observation=True)
            controller, identity = c.api.retain_current_controller()
            budget.check(observation=True)
            nonce = self.nonce if self.nonce is not None else secrets.randbelow((1 << 64)-1)+1
            private_descriptor = c.Descriptor(*identity, nonce)
            binding = (controller, identity, private_descriptor.nonce)
            environment = self._checked(budget, c.environment, self.read_value, layout, private_descriptor.environment_value())
            report['stageCode'] = 2; prep['launchAttempted'] = True
            # Never discard a returned partial launch before the post-call deadline check.
            budget.check(observation=True)
            launch = c.api.launch([str(images['host']), '--module', 'writer'], str(output), environment, controller_binding=binding)
            budget.check(observation=True)
            if launch.failed is not False or launch.uncertain is not False or launch.resumed is not True: raise RunnerFailure(Code.LAUNCH)
            prep['launchResumed'] = True
            report['stageCode'] = 3
            for _ in range(4096):
                roles = self._classify(launch, images, budget)
                prep['classificationCount'] = len(roles)
                if {'host','worker','engine'} <= roles.keys(): break
                self._pause(budget)
            else: raise RunnerFailure(Code.CLASSIFICATION)
            prep['rolesClassified'] = True
            cohort = _CohortTap(c.Cohort(c.api, launch, expected_worker=roles['worker'], expected_engine=roles['engine']))
            self._checked(budget, cohort.cohort.admit)
            prep['cohortAdmitted'] = True
            attachment = None
            report['stageCode'] = 4
            for _ in range(4096):
                self._checked(budget, cohort.verify, budget)
                attachment = c.prep.find_attachment_once(launch, cohort.original_engine.pid, check=budget.check)
                if attachment is not None: break
                self._pause(budget)
            else: raise RunnerFailure(Code.ATTACHMENT)
            prep['attachmentBound'] = True
            report['stageCode'] = 5
            for _ in range(4096):
                self._checked(budget, cohort.verify, budget)
                focus = c.prep.focus_snapshot(launch, attachment, check=budget.check)
                report['editorFocus'] = _section(focus.numeric_projection(), _FOCUS_BOOL, _FOCUS_INT)
                prep['focusSampleCount'] += 1
                if focus.ready is True: break
                self._pause(budget)
            else: raise RunnerFailure(Code.FOCUS)
            prep['focusReady'] = True
            owner = c.Owner(cohort.original_engine, attachment.document, attachment.child, attachment.engine_thread)
            request = {'officePid':cohort.original_engine.pid,'officeCreationTime':cohort.original_engine.birth,
                'childHwnd':attachment.child,'expectedImage':str(images['engine'])}
            probe = c.Helper(host_runtime, c.api, binding, private_descriptor, request, self.read_value, work/'helper-result')
            self._checked(budget, probe.prepare)
            prep['helperPrepared'] = True
            # Mapping is still inert. Library preparation is pre-S filesystem work.
            budget.check(observation=True)
            backend = c.Backend(inputs.prepared_library, 'arm64')
            budget.check(observation=True)
            session = c.Session(c.clock)

            def verify_original():
                active = session.budget if session.budget is not None else budget
                active.check(observation=True)
                if c.prep.recheck_attachment(launch, attachment, check=lambda: active.check(observation=True)) is not True:
                    return False
                sample = c.prep.focus_snapshot(launch, attachment, check=lambda: active.check(observation=True))
                report['editorFocus'] = _section(sample.numeric_projection(), _FOCUS_BOOL, _FOCUS_INT)
                active.check(observation=True)
                return sample.ready is True

            def capture_factory(runtime_budget):
                nonlocal capture, backend_transferred
                capture = _CaptureTap(c.Capture(runtime_budget, private_descriptor, backend))
                backend_transferred = True
                return capture

            def release_controller():
                nonlocal controller_closed
                if (probe.pending_leases() or (cohort.release is not None and not cohort.release.complete) or
                        (capture is not None and not capture.local_resources_released())):
                    self._private_pending.append((controller, self, probe, cohort)); return False
                try: controller_closed = c.api.close(controller) is True
                except Exception: controller_closed = False
                if not controller_closed: self._private_pending.append((controller, self))
                return controller_closed

            prep['lastQpc'] = budget.check(observation=True)
            report['stageCode'] = 6; runtime_entered = True; prep['runtimeEntered'] = True
            receipt = session.execute(cohort=cohort, owner=owner, capture_factory=capture_factory,
                verify_original=verify_original, original_call=probe.invoke_original,
                external_releases=(probe.close_local, release_controller))
            report['runtime'] = _section(receipt.numeric_projection(), _RUNTIME_BOOL, _RUNTIME_INT)
            report['captureIncomplete'] = receipt.capture_incomplete
            if capture is not None and capture.saved_snapshot is not None: report['snapshot'] = capture.saved_snapshot
            report['msaa'] = project_msaa(probe.numeric_result())
            if receipt.first_failure_code: self._fault(report, Code.CAPTURE)
            report['stageCode'] = 7
        except Exception as exc:
            retained = getattr(exc, 'retained_handle', None)
            if retained is not None: self._private_pending.append(retained)
            retained_backend = getattr(exc, 'retained_backend', None)
            if retained_backend is not None:
                # The constructor already attempted its release exactly once.
                # Keep the original object; do not retry or query its library.
                self._private_pending.append(retained_backend)
            self._fault(report, exc.code if type(exc) is RunnerFailure else Code.INTERNAL)
            if admission is not None and not report['admission']['handoffComplete']:
                report['admission']['errorCode']=report['failureCode']
        finally:
            if admission is not None and not admission._clock.invalid:
                report['admission']['lastObservedQpc']=admission._clock.last if budget is None else budget.start_qpc
            if budget is not None and not runtime_entered:
                prep['cleanupAttempted'] = True
                self._cleanup_preparation(report, budget, launch, cohort)
                if probe is not None:
                    within = self._cleanup_time(budget)
                    try: probe.close_local()
                    except Exception: prep['cleanupErrorCount'] = (prep['cleanupErrorCount'] or 0)+1
                    if not self._cleanup_time(budget) or not within:
                        prep['cleanupComplete'] = False
                        prep['cleanupErrorCount'] = (prep['cleanupErrorCount'] or 0)+1
                if controller is not None:
                    within = self._cleanup_time(budget)
                    try: controller_closed = c.api.close(controller) is True
                    except Exception: controller_closed = False
                    within = self._cleanup_time(budget) and within
                    if not controller_closed: self._private_pending.append((controller, self))
                    if not within or not controller_closed:
                        prep['cleanupComplete'] = False
                        prep['cleanupErrorCount'] = (prep['cleanupErrorCount'] or 0)+1
            if backend is not None and not backend_transferred:
                active = session.budget if session is not None and session.budget is not None else budget
                within = self._cleanup_time(active)
                try: released = backend.release_library() is True
                except Exception: released = False
                within = self._cleanup_time(active) and within
                if not released: self._private_pending.append(backend)
                if not runtime_entered and (not released or not within):
                    prep['cleanupComplete'] = False
                    prep['cleanupErrorCount'] = (prep['cleanupErrorCount'] or 0)+1
            if probe is not None:
                try:
                    pending = probe.pending_leases()
                    self._private_pending.extend(pending)
                    if pending or probe.numeric_result().get('cleanupComplete') is not True:
                        self._fault(report, Code.CLEANUP)
                except Exception:
                    self._private_pending.append(probe); self._fault(report, Code.CLEANUP)
            if cohort is not None and cohort.release is not None and not cohort.release.complete:
                self._private_pending.append(cohort)
            if capture is not None and not capture.local_resources_released():
                self._private_pending.append(capture)
            if self._private_pending:
                # Hold the whole original ownership graph; never stringify it.
                _PENDING_CASES.append((self, launch, cohort, probe, capture, backend, controller, tuple(self._private_pending)))
                report['pendingRetainedCount'] = len(self._private_pending)
                prep['pendingRetainedCount'] = len(self._private_pending)
                self._fault(report, Code.CLEANUP)
            if report['failureCode'] or report['pendingRetainedCount']:
                report['captureIncomplete'] = True
        return validate_public_report(report)

    def _cleanup_preparation(self, report, budget, launch, cohort):
        prep, api = report['preparation'], self.c.api
        errors = 0
        within = self._cleanup_time(budget)
        def call(function, *args):
            nonlocal within
            before = self._cleanup_time(budget)
            try: return function(*args)
            finally: within = self._cleanup_time(budget) and before and within
        if launch is None:
            prep['cleanupComplete'] = not self._private_pending and within
            return
        try: prep['disposalRequested'] = call(cohort.dispose_owned) is True if cohort is not None else call(api.terminate_job,launch.job) is True if launch.job is not None else False
        except Exception: errors += 1
        # No work cutoff reset. Exit proof is from original retained objects only.
        if cohort is not None:
            if cohort.cohort.admitted:
                try:
                    evidence = call(cohort.confirm_original_exit,budget)
                    prep['originalEngineExitObserved'] = evidence.remote_retired is True
                except Exception: errors += 1
            try:
                released = call(cohort.release_local)
                prep['cleanupComplete'] = released.complete and within
            except Exception:
                errors += 1; self._private_pending.append(cohort)
        else:
            host_exited = False
            if launch.host is not None and budget is not None:
                try:
                    for _ in range(4096):
                        budget.check(observation=False)
                        same = call(api.identity,launch.host) == launch.identity
                        state = call(api.state,launch.host)
                        budget.check(observation=False)
                        if not same: break
                        if state[0] == 0:
                            host_exited = True; break
                        self.pause(min(.01, budget.remaining_ms(observation=False)/1000))
                except Exception: errors += 1
                prep['hostExitObserved'] = host_exited
            try:
                if call(api.release_launch_local,launch) is not True: errors += 1; self._private_pending.append(launch)
            except Exception: errors += 1; self._private_pending.append(launch)
            for handle in (launch.thread, launch.host if host_exited else None, launch.job):
                if handle is None: continue
                try: closed = call(api.close,handle) is True
                except Exception: closed = False
                if not closed: errors += 1; self._private_pending.append((handle, launch))
            if launch.host is not None and not host_exited: self._private_pending.append((launch.host, launch))
            prep['cleanupComplete'] = not errors and not self._private_pending and within
        if not within: errors += 1; prep['cleanupComplete'] = False
        prep['cleanupErrorCount'] = (prep['cleanupErrorCount'] or 0) + errors

    @staticmethod
    def _cleanup_time(budget):
        if budget is None: return False
        try: budget.check(observation=False); return True
        except Exception: return False


def _json(path):
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result: raise RunnerFailure(Code.INPUT)
            result[key] = value
        return result
    with Path(path).open('rb') as stream: data = stream.read(131073)
    if len(data) > 131072: raise RunnerFailure(Code.INPUT)
    value = json.loads(data, object_pairs_hook=pairs)
    if type(value) is not dict: raise RunnerFailure(Code.INPUT)
    return value


class _Parser(argparse.ArgumentParser):
    def error(self, message): raise RunnerFailure(Code.INPUT)


def main(argv=None):
    report, output = empty_report(), None
    try:
        parser = _Parser(add_help=False,allow_abbrev=False)
        for key in ('output','baseline','artifact','diagnostic-lock','source-lock','expected-suite-source-commit',
                    'prepared-library','host-python','helper-script','windows','work-root','report'):
            parser.add_argument('--'+key, required=True)
        args = parser.parse_args(argv)
        output = Path(args.report)
        values = vars(args)
        inputs = RunnerInputs(*(Path(values[key]) for key in ('output','baseline','artifact','diagnostic_lock','source_lock')),
            args.expected_suite_source_commit, _json(args.prepared_library), Path(args.host_python),
            Path(args.helper_script), Path(args.windows), Path(args.work_root))
        report = DedicatedWriterRunner(NativeComponents()).execute(inputs)
    except Exception:
        report['failureCode'] = int(Code.INPUT)
    data = json.dumps(validate_public_report(report), separators=(',',':'), sort_keys=True)+'\n'
    # Report is exclusively numeric; even CLI errors do not echo arguments.
    if output is not None:
        try:
            fd = os.open(output, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            with os.fdopen(fd,'w',encoding='ascii') as stream: stream.write(data)
        except Exception:
            report['failureCode'] = int(Code.INPUT); report['captureIncomplete'] = True
            data = json.dumps(validate_public_report(report), separators=(',',':'), sort_keys=True)+'\n'
    sys.stdout.write(data)
    return 0 if not report['captureIncomplete'] and report['failureCode'] == 0 else 1


if __name__ == '__main__': raise SystemExit(main())
