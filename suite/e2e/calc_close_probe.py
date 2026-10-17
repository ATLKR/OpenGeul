"""Current-behavior Calc Ctrl+W with ordinary uncommitted cell text.

Three owned-copy cases require the existing Suite Save/Discard/Cancel prompt.
This probe changes no product close behavior and establishes no historical loss.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parent))
import calc_model_barrier
import calc_save_smoke as calc_save
import lifecycle_smoke as lifecycle
import windows_smoke as native

CHOICES=('save','discard','cancel')
BUTTONS={'save':'저장','discard':'저장하지 않음','cancel':'취소'}


def marker(choice):
    assert choice in CHOICES
    return 'UI-OpenGeul-calc-Close-'+choice


def require_three_choices(labels):
    assert all(labels.count(label)==1 for label in BUTTONS.values()),'Expected complete Save/Discard/Cancel prompt'


def require_original_close(record):
    assert record['choice'] in CHOICES and record.get('marker')==marker(record['choice'])
    assert record.get('navigationKeys')==['^{HOME}','{F2}','^{END}']
    assert record.get('commitKeys')==[],'Harness must not accept pending input'
    assert type(record.get('closeShortcutCount')) is int and record['closeShortcutCount']==1
    assert record.get('beforeCloseActions')==['observe-uncommitted','observer-closed','ctrl-w'],'Focus/commit/retry between pending observation and CtrlW'
    assert record.get('uncommittedBeforeCloseVerified') is True


def require_disk_outcome(choice,before,after,baseline):
    assert choice in CHOICES
    if choice=='save':
        calc_save.require_grid(calc_save.read_cells(after),baseline,baseline['a1Text']+marker(choice))
        assert hashlib.sha256(before).hexdigest()!=hashlib.sha256(after).hexdigest()
    else:
        assert after==before,'Discard/Cancel wrote document bytes'
        calc_save.require_grid(calc_save.read_cells(after),baseline,baseline['a1Text'])


def require_cancel_cells(observed,baseline):
    expected=baseline['a1Text']+marker('cancel')
    calc_save.require_grid(observed,baseline,expected)
    assert observed.get('isModified') is True,'Canceled input retention is not proved in the model'


def require_same_native_binding(original,current):
    from writer_model_barrier import BINDING_KEYS
    assert set(original)==set(current)==BINDING_KEYS,'Incomplete original/cancel binding'
    # New read-only helpers have new local proxy addresses. Each independently
    # checks its retained UNO links; only native generations/transport/URL can
    # be compared across the released/restarted observer boundary.
    native_keys=BINDING_KEYS-{'frameIdentity','controllerIdentity','modelIdentity'}
    assert all(current[key]==original[key] for key in native_keys),'Cancel replaced native editor generation or document URL'


def report(rows):
    expected=['calc-close-'+choice for choice in CHOICES]
    counts=Counter(row.get('case') for row in rows)
    missing=[name for name in expected if counts[name]==0]
    duplicate=[name for name,n in counts.items() if n>1]
    unexpected=[name for name in counts if name not in expected]
    failed=[]
    for row in rows:
        choice=row.get('choice')
        proof=all(row.get(key) is True for key in ('promptVerified','originalCloseVerified','diskOutcomeVerified','packagedUnoVerified','cleanClose'))
        proof=proof and type(row.get('choiceClickCount')) is int and row['choiceClickCount']==1
        proof=proof and (row.get('cancelRetainedInputVerified') is True and row.get('cancelNoWriteThroughCleanupVerified') is True if choice=='cancel' else True)
        if row.get('success') is not True or choice not in CHOICES or row.get('case')!='calc-close-'+str(choice) or not proof:
            failed.append(row.get('case'))
    return dict(schemaVersion=1,kind='current-calc-uncommitted-ctrl-w-probe',
        success=not(missing or duplicate or unexpected or failed),expectedCaseCount=3,completedCaseCount=len(rows),
        missingCases=missing,duplicateCases=duplicate,unexpectedCases=unexpected,failedCases=failed,
        productCloseChanged=False,historicalDataLossEstablished=False,asyncValidationQualified=False,tests=rows)


class CalcCloseCase(lifecycle.Case):
    """Reuse owned Suite dialog/window helpers without Writer model operations."""
    def __init__(self,suite,fixtures,output,choice):
        self.suite,self.fixtures,self.root=suite,fixtures,output
        self.choice,self.name=choice,'calc-close-'+choice
        self.output=output/self.name;self.output.mkdir(exist_ok=False)
        self.api=None;self.process=None;self.reader=None;self.deadline=None
        self.record=dict(case=self.name,choice=choice,kind='physical-calc-uncommitted-close',success=False,
            stage='setup',productCloseChanged=False,historicalDataLossEstablished=False,
            marker=marker(choice),navigationKeys=[],commitKeys=[],closeShortcutCount=0,beforeCloseActions=[],
            stderrLog=self.name+'/'+self.name+'-stderr.log')

    def close_reader(self,binding):
        from writer_model_reader import require_model_reader_cleanup
        try:cleanup=self.reader.close(self.deadline)
        finally:self.reader=None
        require_model_reader_cleanup(cleanup,binding,self.deadline,expected_service=calc_model_barrier.SERVICE,
            getter_contract=calc_model_barrier.GETTERS)
        return cleanup

    def start_reader(self,folder):
        from writer_model_reader import OwnedModelReader
        self.deadline=time.monotonic()+calc_model_barrier.MAX_SECONDS
        self.reader=OwnedModelReader(self.suite,self.output/folder,expected_service=calc_model_barrier.SERVICE,
            getter_contract=calc_model_barrier.GETTERS,shell_pid=self.process.pid,
            expected_shell_creation=self.creation,suite_hwnd=self.hwnd,parent_hwnd=self.parent,
            child_hwnd=self.child,office_pid=self.office_pid,expected_url=self.source.as_uri())
        return self.reader.start(self.deadline)

    def choose_existing_prompt(self):
        from pywinauto import Desktop
        dialog,accessible=self.dialog(self.hwnd,'OpenGeul Calc')
        expected=BUTTONS[self.choice]
        def observe():
            labels=[item.element_info.name for item in accessible.descendants()]
            lifecycle.require_dialog_action(pid=self.api.pid(dialog),shell_pid=self.process.pid,
                owner=self.api.user.GetWindow(dialog,4),document=self.hwnd,title=self.api.title(dialog),
                expected_title='OpenGeul Calc',class_name=self.api.class_name(dialog),text=labels,
                expected_text='변경 내용을 저장하시겠습니까?',button=expected,allowed=tuple(BUTTONS.values()))
            buttons=[item for item in accessible.descendants(control_type='Button')
                if item.is_visible() and item.is_enabled()]
            require_three_choices([item.element_info.name for item in buttons])
            selected=[item for item in buttons if item.element_info.name==expected]
            assert len(selected)==1
            ancestry=[]
            lifecycle.require_dialog_button_ancestry(self.api,accessible,selected[0],self.process.pid,dialog,ancestry)
            return selected[0],dict(hwnd=dialog,owner=self.hwnd,pid=self.process.pid,title=self.api.title(dialog),
                text=labels,buttonNames=[item.element_info.name for item in buttons],choice=expected,
                uia=lifecycle.dialog_uia_identity(accessible,dialog,self.process.pid),buttonAncestry=ancestry)
        selected,evidence=observe();self.record['choicePrompt']=evidence
        self.record['promptVerified']=True
        # Focus changes occur only after the original close has shown its prompt.
        Desktop(backend='win32').window(handle=dialog).wrapper_object().set_focus()
        self.api.require_foreground(dialog)
        selected,self.record['choicePromptBeforeClick']=observe()
        self.screenshot(dialog,'choice-'+self.choice)
        selected.click_input()
        self.record['choiceClickCount']=1
        native.wait_for(lambda:not self.api.user.IsWindow(dialog),20)

    def reopen(self,expected):
        # The existing read-only helper has packaged-Python identity, fresh owned
        # Engine, exact cells and byte-preserving cleanup checks. Contain its
        # launcher and descendants in another suspended-before-resume job.
        (self.output/'reopen-input.json').write_text(json.dumps(dict(baseline=self.baseline,expected=expected),ensure_ascii=False),encoding='utf-8')
        sys.path.insert(0,str(self.suite/'worker'))
        from native_windows import OwnedOfficeProcess,ProcessDiagnosticsApi
        command=[str(self.suite/'Office/program/python.exe'),str(Path(calc_save.__file__).resolve()),
            '--verify-reopen','--suite',str(self.suite),'--output',str(self.output),'--owned-fixture',str(self.source)]
        helper=OwnedOfficeProcess(command,self.suite/'Office/program');self.record['reopenJob']={}
        try:
            code=calc_save.await_reopen_job(helper,ProcessDiagnosticsApi(),self.record['reopenJob'])
            assert code==0,'Independent read-only Calc reopen failed'
        finally:helper.close()
        result=json.loads((self.output/'reopen-result.json').read_text(encoding='utf-8'))
        assert result.get('success') is True
        self.record.update(packagedUnoVerified=True,reopen=result)

    def run(self):
        from pywinauto import Desktop
        from pywinauto.keyboard import send_keys
        from writer_style_smoke import _packaged_identity_file
        try:
            original=native.require_engine_fixture(self.fixtures,'calc','xlsx');self.original=original
            raw=original.read_bytes();self.baseline=calc_model_barrier.baseline_from_ooxml(raw)
            folder=self.output/'fixtures';folder.mkdir()
            self.source=folder/'OpenGeul-calc.xlsx'
            with self.source.open('xb') as stream:stream.write(raw)
            self.record.update(baseline=self.baseline,beforeSha256=hashlib.sha256(raw).hexdigest())
            diagnostics=self.output/'diagnostics';diagnostics.mkdir()
            previous=os.environ.get('OPENGEUL_SUITE_DIAGNOSTICS')
            os.environ['OPENGEUL_SUITE_DIAGNOSTICS']=str(diagnostics)
            try:self.process=native.launch_suite([str(self.suite/'OpenGeul.Office.exe'),'--module','calc','--file',str(self.source)],self.suite,self.output,self.name)
            finally:
                if previous is None:os.environ.pop('OPENGEUL_SUITE_DIAGNOSTICS',None)
                else:os.environ['OPENGEUL_SUITE_DIAGNOSTICS']=previous
            self.api=lifecycle.LifecycleWindows();self.record['shellPid']=self.process.pid
            self.record['stage']='attach'
            self.hwnd,self.parent,self.child,self.office_pid=native.verified_attachment(self.api,self.process,'calc')
            self.record.update(windowHwnd=self.hwnd,parentHwnd=self.parent,childHwnd=self.child,officePid=self.office_pid)
            window=Desktop(backend='win32').window(handle=self.hwnd).wrapper_object()
            window.maximize();window.set_focus()
            native.wait_for(lambda:self.api.user.GetAncestor(self.api.user.GetForegroundWindow(),2)==self.hwnd,10)
            self.screenshot(self.hwnd,'before')
            native.prepare_editor_focus(self.api,self.hwnd,self.child,self.process.pid,self.office_pid,self.record,
                lambda:Desktop(backend='win32').window(handle=self.child).wrapper_object().click_input(),
                lambda:send_keys('^{F6}',pause=.1))
            self.record['originalShell']={}
            self.creation=lifecycle.retained_writer_shell(self.process,self.suite,self.record['originalShell'])
            identity,data=_packaged_identity_file(self.suite,'suite-inventory.json');inventory=json.loads(data)
            self.record['stage']='observe-before-input'
            before=self.start_reader('before-close-reader');self.record['beforeInput']=before
            calc_save.require_uncommitted_cells(before,self.baseline)
            self.record['stage']='type-without-enter'
            send_keys('^{HOME}{F2}^{END}',pause=.1);self.record['navigationKeys']=['^{HOME}','{F2}','^{END}']
            self.api.require_editor_focus(self.hwnd,self.child)
            native.ascii_input.type_ascii(self.api,self.hwnd,self.child,marker(self.choice),self.record,pause=.04)
            self.api.require_editor_focus(self.hwnd,self.child)
            pending=self.reader.read(self.deadline);self.record['beforeClose']=pending
            calc_save.require_pending_observation(before,pending,self.baseline,suite=self.suite,inventory=inventory,
                inventory_sha256=identity['sha256'],original_shell=self.record['originalShell'],
                expected_url=self.source.as_uri(),deadline=self.deadline)
            self.record['uncommittedBeforeCloseVerified']=True
            self.record['beforeCloseActions'].append('observe-uncommitted')
            self.record['readerCleanup']=self.close_reader(before['bindingBefore'])
            self.record['beforeCloseActions'].append('observer-closed')
            # Read-only focus check, then one physical Ctrl+W. No focus action,
            # Enter, model setter, dispatch or completion barrier is permitted.
            self.api.require_editor_focus(self.hwnd,self.child)
            self.record['stage']='single-physical-ctrl-w'
            self.record['closeShortcutCount']=1;self.record['beforeCloseActions'].append('ctrl-w')
            send_keys('^w',pause=.1)
            require_original_close(self.record);self.record['originalCloseVerified']=True
            self.record['stage']='require-existing-save-discard-cancel-prompt'
            self.choose_existing_prompt()
            if self.choice=='cancel':
                self.record['stage']='verify-cancel-before-any-later-save'
                assert self.process.poll() is None and self.api.user.IsWindow(self.hwnd) and self.api.user.IsWindow(self.child)
                assert window.is_enabled() and Desktop(backend='win32').window(handle=self.child).wrapper_object().is_enabled(),'Cancel left the retained editor disabled'
                self.record['cancelEditorEnabled']=True
                decision=self.source.read_bytes();require_disk_outcome('cancel',raw,decision,self.baseline)
                self.record.update(diskOutcomeVerified=True,cancelDecisionSha256=hashlib.sha256(decision).hexdigest())
                after=self.start_reader('after-cancel-reader');self.record['afterCancel']=after
                from writer_model_reader import require_owned_model_observation
                require_owned_model_observation(after,after['bindingBefore'],self.suite,
                    expected_service=calc_model_barrier.SERVICE,getter_contract=calc_model_barrier.GETTERS)
                require_same_native_binding(before['bindingBefore'],after['bindingBefore'])
                from writer_model_reader import canonical_profile_projection
                old=before['nativeSnapshots']['controllerBefore'];new=after['nativeSnapshots']['controllerBefore']
                assert old['officeCommandLine']==new['officeCommandLine'] and old['profileUrl']==new['profileUrl']
                assert canonical_profile_projection(old['profileDirectory']['witness'],old['profileUrl'])==canonical_profile_projection(new['profileDirectory']['witness'],new['profileUrl'])
                require_cancel_cells(after,self.baseline)
                self.record['cancelReaderCleanup']=self.close_reader(after['bindingBefore'])
                self.record['cancelRetainedInputVerified']=True
                self.record['stage']='authorized-cleanup-discard-after-cancel-proof'
                self.record['cleanupAction']='owned-WM_CLOSE-then-explicit-discard'
                self.api.request_close(self.hwnd,self.process.pid)
                self.record['cleanupDiscardDialog']=self.click_dialog(self.hwnd,'OpenGeul Calc',
                    '변경 내용을 저장하시겠습니까?','저장하지 않음',tuple(BUTTONS.values()))
                self.closed(self.hwnd,self.child)
                require_disk_outcome('cancel',raw,self.source.read_bytes(),self.baseline)
                self.record['cancelNoWriteThroughCleanupVerified']=True
                expected=self.baseline['a1Text']
            else:
                self.record['stage']='wait-original-close'
                self.closed(self.hwnd,self.child)
                require_disk_outcome(self.choice,raw,self.source.read_bytes(),self.baseline)
                self.record['diskOutcomeVerified']=True
                expected=self.baseline['a1Text']+(marker('save') if self.choice=='save' else '')
            native.close_home(self.api,self.process,self.record)
            self.record['cleanClose']=True
            self.reopen(expected)
            assert original.read_bytes()==raw,'Original generated fixture changed'
            self.record.update(success=True,stage='complete',originalFixtureUnchanged=True)
            return self.record
        except BaseException as exc:
            if self.api is not None and hasattr(self,'hwnd'):
                self.record['documentStillLiveAtFailure']=bool(self.api.user.IsWindow(self.hwnd))
                self.record['editorStillLiveAtFailure']=bool(self.api.user.IsWindow(self.child))
                self.record['observedCloseBeforeExpectedPrompt']=not self.record.get('promptVerified',False) and not self.record['documentStillLiveAtFailure']
            if hasattr(self,'source') and self.source.is_file():
                try:
                    data=self.source.read_bytes();self.record['failureDisk']=dict(sha256=hashlib.sha256(data).hexdigest(),cells=calc_save.read_cells(data))
                except BaseException as later:self.record['failureDiskError']=str(later)
            native.capture_failure(self.output,self.name,self.record,exc)
            raise
        finally:
            if self.reader is not None:
                try:self.record['failedReaderCleanup']=self.reader.close(self.deadline)
                except BaseException as later:self.record['failedReaderCleanupError']=str(later)
                self.reader=None
            if self.process is not None:
                # Authorized cleanup only for this launched generated-copy case;
                # never dismiss an unexpected or foreign dialog to make it pass.
                native.stop_owned_test_process(self.process,self.record)
            log=self.output/(self.name+'-stderr.log')
            if log.is_file() and log.stat().st_size<=16*1024*1024:
                rows=[]
                for line in log.read_text(encoding='utf-8',errors='replace').splitlines():
                    if line.startswith('{'):
                        try:value=json.loads(line)
                        except ValueError:continue
                        if isinstance(value,dict) and value.get('event')=='suite.documentClose':rows.append(value)
                self.record['closeTraceRows']=rows
            native.write_result(self.output,self.name,self.record)
            native.write_result(self.root,self.name,self.record)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',required=True,type=Path);parser.add_argument('--fixtures',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    if os.name!='nt' or not __debug__:raise RuntimeError('Actual Windows execution with assertions is required')
    for path in (args.suite,args.fixtures,args.output):
        assert not str(path).startswith(('\\\\','//')) and '..' not in path.parts
        for part in (path,*path.parents):lifecycle.unlinked(part)
    suite,fixtures,output=args.suite.resolve(),args.fixtures.resolve(),args.output.resolve()
    assert suite!=output and suite not in output.parents and output not in suite.parents
    assert fixtures!=output and fixtures not in output.parents and output not in fixtures.parents
    output.mkdir(parents=True,exist_ok=False)
    definitions=[('calc-close-'+choice,lambda choice=choice:CalcCloseCase(suite,fixtures,output,choice).run()) for choice in CHOICES]
    results=native.collect_cases(definitions,output);summary=report(results)
    (output/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return 0 if summary['success'] else 1


if __name__=='__main__':raise SystemExit(main())
