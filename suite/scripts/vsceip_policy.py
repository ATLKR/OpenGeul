"""Temporary VSCEIP value for an explicit GitHub Windows CI experiment.

This never changes Office policy or deletes shared registry containers. The
original compiler preparation has its own unchanged deadline. Restoring the
OptIn value can leave an empty newly created key on the ephemeral CI runner.
"""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import time


POLICY_KEY = r'SOFTWARE\Policies\Microsoft\VisualStudio\SQM'
POLICY_VALUE = 'OptIn'
PHASE_SECONDS = 5.


def error_record(error):
    return dict(type=type(error).__name__[:128], message=str(error)[:512])


def write_durable(path, value):
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()
    assert len(raw) <= 65536, 'CI policy receipt exceeds bound'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


class Phase:
    def __init__(self, name, receipt, clock):
        self.name, self.clock = name, clock
        self.last = clock()
        assert type(self.last) in (int, float) and math.isfinite(self.last)
        self.row = receipt[name] = dict(startedAt=self.last, deadline=self.last + PHASE_SECONDS)

    def check(self):
        now = self.clock()
        assert type(now) in (int, float) and math.isfinite(now) and now >= self.last, 'CI policy clock changed'
        self.last = now
        self.row['lastObservedAt'] = now
        if now >= self.row['deadline']:
            raise TimeoutError('CI policy ' + self.name + ' deadline expired')


@contextmanager
def temporary_vs_opt_out(output, receipt, *, registry=None, clock=time.monotonic):
    """Admit only absent or DWORD0/1 and restore that exact value state.

    Setup failures occur inside this generator's try/finally, so rollback also
    runs when context entry fails after a registry write. A failed restoration
    never replaces an original preparation exception or permits success.
    """
    if registry is None:
        assert os.name == 'nt' and os.environ.get('GITHUB_ACTIONS') == 'true', 'CI Windows policy experiment only'
        import winreg as registry
    output = Path(output)
    assert output.is_absolute() and output.is_dir()
    for part in (output, *output.parents):
        assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(), 'Linked CI policy output'
    receipt.update(schemaVersion=1, key=POLICY_KEY, valueName=POLICY_VALUE, registryView=64,
                   writeAttempted=False, appliedAndVerified=False, restoredAndVerified=False,
                   emptyCreatedContainerMayRemain=False, restorationScope='OptIn presence/type/data only')
    key, primary, prior = None, None, None
    secondary = []
    access = registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE | registry.KEY_WOW64_64KEY
    try:
        setup = Phase('setup', receipt, clock)
        setup.check()
        try:
            key = registry.OpenKey(registry.HKEY_LOCAL_MACHINE, POLICY_KEY, 0, access)
            key_exists = True
        except FileNotFoundError:
            key_exists = False
        setup.check()
        try:
            if key is None: raise FileNotFoundError()
            value, kind = registry.QueryValueEx(key, POLICY_VALUE)
            setup.check()
            assert kind == registry.REG_DWORD and type(value) is int and value in (0, 1), 'Unsupported prior VSCEIP policy'
            prior = dict(keyExists=key_exists, valueExists=True, kind=kind, value=value)
        except FileNotFoundError:
            setup.check()
            prior = dict(keyExists=key_exists, valueExists=False, kind=None, value=None)
        receipt['prior'] = prior
        write_durable(output / 'vsceip-policy-before.json', receipt)
        setup.check()
        if key is None:
            # Record the possible empty-container residual before creation.
            receipt['emptyCreatedContainerMayRemain'] = True
            key = registry.CreateKeyEx(registry.HKEY_LOCAL_MACHINE, POLICY_KEY, 0, access)
            setup.check()
        receipt['writeAttempted'] = True  # Set may fail after changing the value.
        registry.SetValueEx(key, POLICY_VALUE, 0, registry.REG_DWORD, 0)
        setup.check()
        observed, observed_kind = registry.QueryValueEx(key, POLICY_VALUE)
        setup.check()
        assert observed_kind == registry.REG_DWORD and type(observed) is int and observed == 0, 'VSCEIP setup readback differs'
        receipt['appliedAndVerified'] = True
        yield receipt
    except BaseException as exc:
        primary = exc
        receipt['primaryError'] = error_record(exc)
        raise
    finally:
        if receipt['writeAttempted']:
            try:
                # Even a clock failure must not skip the one mandatory restore.
                restore, clock_error = None, None
                try:
                    restore = Phase('restore', receipt, clock)
                except BaseException as exc:
                    clock_error = exc
                if prior['valueExists']:
                    registry.SetValueEx(key, POLICY_VALUE, 0, prior['kind'], prior['value'])
                else:
                    try:
                        registry.DeleteValue(key, POLICY_VALUE)
                    except FileNotFoundError:
                        pass
                if clock_error is not None: raise clock_error
                restore.check()
                try:
                    restored, restored_kind = registry.QueryValueEx(key, POLICY_VALUE)
                    assert restored_kind == registry.REG_DWORD and type(restored) is int and restored in (0, 1), 'VSCEIP restoration type differs'
                    actual = dict(valueExists=True, kind=restored_kind, value=restored)
                except FileNotFoundError:
                    actual = dict(valueExists=False, kind=None, value=None)
                restore.check()
                assert actual == {k: prior[k] for k in actual}, 'VSCEIP restoration readback differs'
                receipt['restoredAndVerified'] = True
            except BaseException as exc:
                receipt['restoreError'] = error_record(exc)
                secondary.append(exc)
        if key is not None:
            try:
                key.Close()
                receipt['keyHandleClosed'] = True
            except BaseException as exc:
                receipt['keyHandleClosed'] = False
                receipt['closeError'] = error_record(exc)
                secondary.append(exc)
        try:
            write_durable(output / 'vsceip-policy-after.json', receipt)
        except BaseException as exc:
            receipt['receiptError'] = error_record(exc)
            secondary.append(exc)
        if secondary:
            if primary is None:
                raise secondary[0]
            try:
                primary.vsceipPolicySecondaryErrors = [error_record(exc) for exc in secondary]
            except BaseException:
                pass
