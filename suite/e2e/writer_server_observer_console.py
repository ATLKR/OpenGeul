"""Writer-only optional system-file/process leases; no normal admission policy."""
from pathlib import Path
import writer_model_reader as reader
from writer_server_observer_cohort import RetainedProcess
from writer_server_observer_lifecycle import DiagnosticFailure, FailureCode


class _RetainedConsoleFile(reader._SystemConsoleHost):
    """Reuse the original file contract while retaining a failed close HANDLE."""
    def close(self):
        handle = self.handle
        self.ever_opened = True
        if getattr(self, 'close_attempted', False):
            return self._close_receipt
        self.close_attempted = True
        self._close_receipt = dict(kind='system-console-file', handleValue=int(handle), result=False, lastError=None)
        reader._clear_last_error()
        result = bool(self.api.close_handle(handle)); error = reader._last_error()
        if result: self.handle = None
        self._close_receipt = dict(kind='system-console-file', handleValue=int(handle), result=result, lastError=error)
        return self._close_receipt


class ConsoleProfile:
    """Private opt-in. The original engine remains the only capture owner."""
    def __init__(self, *, file_api=None):
        self._file_api, self._file, self._path = file_api, None, None
        self._ready = self._file_close_attempted = False
        self.auxiliary = self.cohort = None
        self._auxiliary_closed = self._aux_close_attempted = False
        self.auxiliary_exit_observed = self.job_empty_observed = None

    def __repr__(self): return '<Writer diagnostic console leases private>'

    def prepare(self, layout, budget):
        if self._file is not None: raise DiagnosticFailure(FailureCode.STAGE)
        budget.check(observation=True)
        self._file = _RetainedConsoleFile.__new__(_RetainedConsoleFile)
        reader._SystemConsoleHost.__init__(self._file, budget.cutoff_qpc,
            lambda: budget.check(observation=True), self._file_api)
        budget.check(observation=True)
        self._file.ever_opened = True
        path = Path(self._file.witness['path'])
        # PureWindowsPath preserves the native spelling in portable seam tests.
        from pathlib import PureWindowsPath
        if PureWindowsPath(self._file.witness['path']) != PureWindowsPath(layout.windows) / 'System32' / 'conhost.exe':
            raise DiagnosticFailure(FailureCode.ENVIRONMENT)
        self._path = path
        self._ready = True

    def verify_file(self, budget):
        if not self._ready or self._file is None or not self._file.handle:
            raise DiagnosticFailure(FailureCode.ENVIRONMENT)
        budget.check(observation=True)
        self._file.recheck()
        budget.check(observation=True)
        return True

    def matches(self, image, budget):
        from pathlib import PureWindowsPath
        if not self._ready or PureWindowsPath(image) != PureWindowsPath(self._path): return False
        return self.verify_file(budget)

    def bind(self, handle, identity, host_handle):
        if handle == host_handle: return False
        if self.auxiliary is None:
            self.auxiliary = RetainedProcess(handle, *identity)
        return self.auxiliary.handle == handle and (self.auxiliary.pid, self.auxiliary.birth) == identity

    def transfer_to(self, cohort):
        if cohort.auxiliary is not self.auxiliary: raise DiagnosticFailure(FailureCode.GENERATION)
        self.cohort = cohort

    def pending_count(self):
        file_pending = self._file is not None and bool(getattr(self._file, 'handle', None))
        aux_pending = (self.auxiliary is not None and
            not (self.cohort.auxiliary_closed if self.cohort is not None else self._auxiliary_closed))
        return int(file_pending) + int(aux_pending)

    def close_file(self, budget):
        if self._file is None or not getattr(self._file, 'handle', None): return True
        if self._file_close_attempted: return False
        self._file_close_attempted = True
        try:
            budget.check(observation=False)
            closed = self._file.close()['result'] is True
            budget.check(observation=False)
            return closed
        except BaseException: return False

    def retire_untransferred(self, api, launch, budget, pause):
        if self.auxiliary is None or self.cohort is not None: return True
        original = self.auxiliary
        try:
            for _ in range(4096):
                budget.check(observation=False)
                same = api.identity(original.handle) == (original.pid, original.birth)
                budget.check(observation=False)
                waited, code = api.state(original.handle)
                budget.check(observation=False)
                if not same or waited not in (0, 258) or type(code) is not int or not 0 <= code <= 0xffffffff:
                    return False
                empty = api.census(launch.job) == ()
                budget.check(observation=False)
                self.auxiliary_exit_observed = waited == 0
                self.job_empty_observed = empty
                if waited == 0 and empty:
                    if self._aux_close_attempted: return self._auxiliary_closed
                    self._aux_close_attempted = True
                    self._auxiliary_closed = api.close(original.handle) is True
                    budget.check(observation=False)
                    return self._auxiliary_closed
                pause(min(.01, budget.remaining_ms(observation=False) / 1000))
        except BaseException: pass
        return False
