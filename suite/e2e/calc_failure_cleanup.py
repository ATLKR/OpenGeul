"""Explicit cleanup only when a private Calc probe fails before its first input.

This does not qualify the failed probe or replace the product shutdown receipt.
An original Save/Close attempt or even partially attempted navigation excludes it.
"""
from dataclasses import dataclass
from generated_calc_close import SavedCalcCopy,verify_saved_calc_copy,_close_calc_prompt


@dataclass(frozen=True)
class PreInputCleanup:
    saved: SavedCalcCopy
    process: object
    hwnd: int
    parent: int
    child: int
    shell: object
    engine: object
    case: str
    kind: str
    command: tuple


def _command(process,saved):
    assert isinstance(process.args,(list,tuple))
    command=tuple(map(str,process.args))
    assert command==(str(saved.suite/'OpenGeul.Office.exe'),'--module','calc','--file',str(saved.path)), 'Failure cleanup command differs from the private fixture launch'
    return command


def bind_pre_input_cleanup(api,process,hwnd,parent,child,record,saved):
    """Retain the verified attachment before the first observer or input action."""
    import lifecycle_smoke as lifecycle
    assert isinstance(saved,SavedCalcCopy)
    verify_saved_calc_copy(saved)
    assert record.get('module')=='calc'
    kind,case=record.get('kind'),record.get('case')
    assert (kind=='physical-uncommitted-calc-save' and case=='calc-active-cell-save' or
            kind=='physical-calc-uncommitted-close' and record.get('choice') in ('save','discard','cancel') and
            case=='calc-close-'+record['choice']), 'Only the two generated pending-input probes may authorize this cleanup'
    shell=engine=None
    try:
        shell=lifecycle.BoundHwpProcess(process.pid,saved.suite/'OpenGeul.Office.exe')
        engine=lifecycle.BoundHwpProcess(api.pid(child),saved.suite/'Office/program/soffice.bin')
        proof=PreInputCleanup(saved,process,hwnd,parent,child,shell,engine,case,kind,_command(process,saved))
        _verify_attachment(api,process,record,proof)
        return proof
    except BaseException:
        for bound in (engine,shell):
            if bound is not None:
                try:bound.close()
                except BaseException as later:
                    record.setdefault('preInputCleanupBindingHandleErrors',[]).append(type(later).__name__+': '+str(later)[:2048])
        raise


def _verify_attachment(api,process,record,proof):
    import lifecycle_smoke as lifecycle
    assert isinstance(proof,PreInputCleanup) and proof.process is process
    verify_saved_calc_copy(proof.saved)
    assert record.get('module')=='calc' and (record.get('case'),record.get('kind'))==(proof.case,proof.kind)
    assert process.opengeul_evidence_case==proof.case and _command(process,proof.saved)==proof.command
    assert record.get('shellPid')==process.pid==proof.shell.pid
    assert (record.get('windowHwnd'),record.get('parentHwnd'),record.get('childHwnd'))==(proof.hwnd,proof.parent,proof.child)
    assert record.get('officePid')==proof.engine.pid
    assert all(api.user.IsWindow(h) for h in (proof.hwnd,proof.parent,proof.child))
    assert api.user.IsChild(proof.hwnd,proof.parent) and api.user.IsChild(proof.parent,proof.child)
    assert api.pid(proof.hwnd)==proof.shell.pid and api.pid(proof.child)==proof.engine.pid
    assert process.poll() is None and proof.shell.live() and proof.engine.live()
    assert proof.engine.creation>=proof.shell.creation>0
    for bound,image in ((proof.shell,proof.saved.suite/'OpenGeul.Office.exe'),
                        (proof.engine,proof.saved.suite/'Office/program/soffice.bin')):
        assert lifecycle.process_identity(bound.kernel,bound.handle)==(image.resolve(),bound.creation), 'Failure cleanup native generation changed'
    assert lifecycle.process_identity(proof.shell.kernel,int(process._handle))==(proof.saved.suite/'OpenGeul.Office.exe',proof.shell.creation), 'Failure cleanup lost the original Popen generation'


def _require_pre_input(record,observer):
    stages={'physical-uncommitted-calc-save':'observe-clean-before-input',
            'physical-calc-uncommitted-close':'observe-before-input'}
    assert record.get('success') is False and record.get('stage')==stages.get(record.get('kind')), 'Failure occurred outside the first observation boundary'
    assert record.get('navigationKeys')==[] and record.get('commitKeys')==[]
    assert not any(record.get(k) for k in ('physicalAsciiMarker','asciiEditorInputs','pendingInputTextVerified',
        'uncommittedBeforeSaveVerified','uncommittedBeforeCloseVerified','beforeCloseActions'))
    key='saveShortcutCount' if record['kind']=='physical-uncommitted-calc-save' else 'closeShortcutCount'
    assert type(record.get(key)) is int and record[key]==0, 'Original measured action already started'
    # A failed getter remains context-unqualified. Only physical observer
    # release is relevant here; its failure never becomes a passing observation.
    assert isinstance(observer,dict) and observer.get('physicalCleanupSucceeded') is True
    assert observer.get('terminated') is False and observer.get('errors')==[] and observer.get('finalJobPids')==[]
    members=observer.get('readerMembers')
    assert isinstance(members,list) and members and all(m.get('waitResult')==0 and m.get('exitCode')==0 for m in members), 'Observer is not proved quiescent'


def finish_pre_input_cleanup(api,process,record,proof,observer,*,observer_never_started=False):
    """Keep the primary failure; retain forced fallback if explicit cleanup fails."""
    import windows_smoke as native
    if proof is None:return
    evidence=dict(kind='owned-pre-input-calc-failure-cleanup',attempted=False,success=False,
                  productShutdownQualified=False,sourceStage=record.get('stage'))
    failed=record.get('success') is False
    if failed:record['failureCleanup']=evidence
    cleanup_record={k:record.get(k) for k in ('module','shellPid','windowHwnd','parentHwnd','childHwnd','officePid')}
    try:
        if not failed:return
        if observer_never_started is True:
            from calc_early_cleanup import require_early,run_early
            require_early(record,observer_never_started,observer)
            run_early(api,process,record,proof,evidence)
            return
        _require_pre_input(record,observer)
        check=lambda:_verify_attachment(api,process,record,proof)
        check()
        evidence.update(attempted=True,path=str(proof.saved.path),savedSha256=proof.saved.sha256,
                        shellCreationTime=proof.shell.creation,engineCreationTime=proof.engine.creation)
        _close_calc_prompt(api,process,proof.hwnd,proof.child,cleanup_record,check,evidence,'authorizedFailureDiscard')
        verify_saved_calc_copy(proof.saved)
        native.wait_for(lambda:not proof.engine.live(),seconds=10)
        native.close_home(api,process,cleanup_record)
        assert process.poll()==0, 'Failed case shell did not exit normally'
        evidence.update(success=True,baselineBytesUnchanged=True,originalEngineExited=True,shellExitCode=0)
    except BaseException as exc:
        evidence['error']=type(exc).__name__+': '+str(exc)[:2048]
    finally:
        evidence['lastStage']=cleanup_record.get('stage')
        if evidence.get('actor',{}).get('deathProved') is False:
            evidence['productWitnessesRetained']=True
        else:
            for bound in (proof.engine,proof.shell):
                try:bound.close()
                except BaseException as exc:
                    evidence.setdefault('handleErrors',[]).append(type(exc).__name__+': '+str(exc)[:2048])
                    evidence['success']=False
                    record['success']=False
                    record['failureCleanup']=evidence
        if 'parentReceiptPath' in evidence:
            from calc_early_cleanup import write_original
            from pathlib import Path
            evidence['productHandlesReleased']=all(bound.handle is None for bound in (proof.engine,proof.shell))
            try:write_original(Path(evidence['parentReceiptPath']),evidence)
            except BaseException as exc:
                evidence['receiptError']=type(exc).__name__+': '+str(exc)[:2048]
                evidence['success']=False
