"""Fixed six-module native menu gestures on fresh blank owned documents.

This is one UI gate, not complete Suite acceptance. Save/reopen, Save As cancel,
close cancellation, module switching and Home ownership remain separate gates.
Synthetic boundary checks never establish actual Windows UI verification.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import time

MODULES = ('writer', 'calc', 'impress', 'draw', 'math', 'base')
GESTURES = ('open-escape', 'open-outside', 'keyboard-escape', 'open-escape')
VIEW_MODULES = ('writer', 'calc')
CORE_COMMANDS = ('new-hwp', 'home', 'new', 'open', 'save', 'saveAs', 'close')
EXTERNAL_GATES = ('save-and-reopen', 'save-as-cancel', 'close-cancel',
                  'module-transition', 'home-ownership', 'formatting')


def _initial_focus_unknown(code):
    return dict(schemaVersion=1, attempted=True, known=False, acceptanceEligible=False,
        errorCode=code, gapObserved=False, gapCount=0, eventCompletenessUnknown=True, scope={}, rows=[])


def capture_initial_focus_trace(session, record):
    """One bounded, numeric-only read of this launch's existing C# stderr.

    Unknown codes: 1=owner context, 2=path, 3=bound, 4=unstable/read,
    5=JSON framing, 6=no rows, 7=shape, 8=sequence, 9=generation, 10=budget.
    Missing/partial evidence never certifies a focus attempt or changes a gate.
    """
    code = 1
    deadline = time.monotonic() + 1
    def budget():
        if time.monotonic() >= deadline:
            raise TimeoutError()
    def integer(value, maximum=2**63-1, minimum=0):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError()
        return value
    def flag(value):
        if type(value) is not bool: raise ValueError()
        return value
    def keys(value, expected):
        if type(value) is not dict or set(value) != set(expected.split()): raise ValueError()
    try:
        budget()
        module=record['module'];case='native-menu-'+module
        assert module in MODULES and record['case']==case==session.process.opengeul_evidence_case
        process=session.process;engine=session.engine;output=Path(session.output)
        suite=Path(session.suite)
        assert output==Path(process.opengeul_evidence_output) and suite==Path(process.opengeul_suite_root) and suite.is_absolute()
        shell=record['windowActivations'][0]['originalProcess']
        shell_pid=integer(process.pid,0xffffffff,1);shell_handle=integer(int(process._handle),minimum=1)
        shell_birth=integer(shell['creationTime'],minimum=1)
        office_pid=integer(session.office_pid,0xffffffff,1);office_birth=integer(engine.creation_time,minimum=1)
        assert shell_pid!=office_pid and shell_birth<=office_birth
        assert (record['shellPid'],record['officePid'],record['officeCreationTime'])==(shell_pid,office_pid,office_birth)
        form,panel,child=(integer(value,minimum=1) for value in (session.hwnd,session.parent,session.child))
        assert (record['windowHwnd'],record['parentHwnd'],record['childHwnd'])==(form,panel,child)
        assert len({form,panel,child})==3
        assert session._opening_focus_identity==(shell_pid,shell_handle,int(engine.handle),office_birth,form,panel,child,office_pid)
        expected_shell=PureWindowsPath(str(suite/'OpenGeul.Office.exe'))
        expected_engine=PureWindowsPath(str(suite/'Office/program/soffice.bin'))
        for activation in record['windowActivations']:
            original=activation['originalProcess']
            assert (original['pid'],original['handleValue'],original['creationTime'])==(shell_pid,shell_handle,shell_birth)
            assert PureWindowsPath(original['image'])==expected_shell and original['waitResult']==258
            assert activation['suiteHwnd']==form and activation['shellPid']==shell_pid
        generation=record['nativeArchiveGeneration']
        assert (generation['pid'],generation['creationTime'])==(office_pid,office_birth)
        assert PureWindowsPath(generation['image'])==expected_engine
        opening=record['openingFocusObservations'];assert 1<=len(opening)<=3
        assert [row['phaseCode'] for row in opening]==list(range(1,len(opening)+1))
        host_thread=integer(opening[0]['hostGui']['threadId'],0xffffffff,1)
        editor_thread=integer(opening[0]['engineGui']['threadId'],0xffffffff,1)
        assert all((row['hostGui']['threadId'],row['engineGui']['threadId'])==(host_thread,editor_thread) for row in opening)
        scope=dict(moduleCode=MODULES.index(module)+1,shellPid=shell_pid,shellCreationTime=shell_birth,
            officePid=office_pid,officeCreationTime=office_birth,formHwnd=form,panelHwnd=panel,childHwnd=child,
            shellThreadId=host_thread,editorThreadId=editor_thread)
        code=2
        assert output.is_absolute() and not str(output).startswith(('\\\\','//')) and '..' not in output.parts
        for directory in (output,*output.parents):
            info=directory.lstat()
            assert stat.S_ISDIR(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400
        assert output.resolve()==output
        path=output/(case+'-stderr.log');before=path.lstat()
        assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and not getattr(before,'st_file_attributes',0)&0x400
        code=3
        assert 0<before.st_size<=2*1024*1024
        budget();code=4
        descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NOINHERIT',0))
        def identity(info):
            return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_nlink,
                info.st_mode,getattr(info,'st_file_attributes',0))
        try:
            assert identity(os.fstat(descriptor))==identity(before)
            raw=os.read(descriptor,before.st_size+1)
            assert len(raw)==before.st_size
            assert identity(os.fstat(descriptor))==identity(before)==identity(path.lstat())
        finally:
            os.close(descriptor)
        budget();code=3
        lines=raw.splitlines(keepends=True)
        assert len(lines)<=8192 and all(len(line)<=64*1024 for line in lines)
        code=5
        assert raw.endswith(b'\n')
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value: raise ValueError()
                value[key]=item
            return value
        def invalid_constant(value): raise ValueError()
        prefix=b'{"event":"suite.editorFocus","component":"host",'
        rows=[];sequence=0;gap_count=0;context=None;trace=None;worker=None
        stage_codes={'initial':1,'initial.queued':2,'initial.activation':3}
        reason_codes={'alreadyFocused':1,'editorFocused':2,'initialAlreadyHandled':3,
            'initialPending':4,'initialHandoffUnverified':5,'initialContextCancelled':6}
        window_keys='Hwnd Pid ThreadId Root Parent Exists Visible Enabled ClassName'
        numeric_windows='Form Panel Child Foreground Focus EditorFocus Capture EditorCapture'.split()
        snapshot_keys='Shell Engine '+ ' '.join(numeric_windows)+' CurrentThread GuiQueriesSucceeded GuiFlags FormOwnsPanel PanelOwnsChild FocusWithinEditor EditorFocusWithinEditor RegisteredPanel RegisteredChild HostMenuOwner EditorMenuOwner'
        def attachment_identity(value):
            return tuple(tuple(value[name][key] for key in ('Hwnd','Pid','ThreadId','Root','Parent'))
                for name in ('Form','Panel','Child'))
        def snapshot(value):
            keys(value,snapshot_keys)
            cleaned={}
            for name,pid,birth,image in (('Shell',shell_pid,shell_birth,expected_shell),('Engine',office_pid,office_birth,expected_engine)):
                item=value[name];keys(item,'Pid CreationTime Image Alive')
                assert type(item['Image']) is str and PureWindowsPath(item['Image'])==image
                assert integer(item['Pid'],0xffffffff,1)==pid and integer(item['CreationTime'],minimum=1)==birth
                assert flag(item['Alive'])
                cleaned[name]=dict(Pid=pid,CreationTime=birth,Alive=True)
            for name in numeric_windows:
                item=value[name];keys(item,window_keys)
                assert type(item['ClassName']) is str and len(item['ClassName'])<=255
                cleaned[name]={key:integer(item[key],0xffffffff if key in ('Pid','ThreadId') else 2**63-1)
                    for key in ('Hwnd','Pid','ThreadId','Root','Parent')}
                cleaned[name].update({key:flag(item[key]) for key in ('Exists','Visible','Enabled')})
            for name in ('GuiQueriesSucceeded','FormOwnsPanel','PanelOwnsChild','FocusWithinEditor','EditorFocusWithinEditor'):
                cleaned[name]=flag(value[name])
            for name in ('CurrentThread','GuiFlags','RegisteredPanel','RegisteredChild','HostMenuOwner','EditorMenuOwner'):
                cleaned[name]=integer(value[name],0xffffffff if name in ('CurrentThread','GuiFlags') else 2**63-1)
            for name,hwnd,pid,thread,parent in (('Form',form,shell_pid,host_thread,None),
                    ('Panel',panel,shell_pid,host_thread,form),('Child',child,office_pid,editor_thread,panel)):
                item=cleaned[name]
                assert (item['Hwnd'],item['Pid'],item['ThreadId'],item['Root'])==(hwnd,pid,thread,form)
                assert item['Exists'] and (parent is None or item['Parent']==parent)
            assert cleaned['CurrentThread']==host_thread
            assert (cleaned['RegisteredPanel'],cleaned['RegisteredChild'])==(panel,child)
            assert cleaned['FormOwnsPanel'] and cleaned['PanelOwnsChild']
            return cleaned
        for line in lines:
            budget();code=5
            if not line.startswith(prefix): continue
            value=json.loads(line.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid_constant)
            code=7
            keys(value,'event component stage sequence utc processId managedThreadId workerProcessId traceId details')
            assert value['event']=='suite.editorFocus' and value['component']=='host'
            assert type(value['utc']) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:\d\d)',value['utc'])
            assert integer(value['processId'],0xffffffff,1)==shell_pid
            managed=integer(value['managedThreadId'],0x7fffffff,1)
            pid=integer(value['workerProcessId'],0x7fffffff,1)
            assert type(value['traceId']) is str and re.fullmatch('[0-9a-f]{32}',value['traceId'])
            code=8
            current_sequence=integer(value['sequence'],128,1)
            assert current_sequence>sequence
            gap_count+=current_sequence-sequence-1
            sequence=current_sequence
            assert trace is None or (trace,worker)==(value['traceId'],pid)
            trace,worker=value['traceId'],pid
            code=7
            stage=stage_codes[value['stage']];details=value['details']
            expected='queued pending' if stage==2 else 'available pending result' if stage==1 else 'pending result'
            keys(details,expected)
            row=dict(sequence=sequence,stageCode=stage,reasonCode=0,managedThreadId=managed,workerProcessId=pid,
                pending=flag(details['pending']),availablePresent=stage==1,available=False,
                queuePresent=stage==2,queued=False,resultPresent=stage!=2,attempted=False,verified=False,
                beforePresent=False,before={},afterPresent=False,after={},previousFocus=0,nativeError=0,
                contextInherited=False)
            if stage==1: row['available']=flag(details['available'])
            if stage==2:
                row['queued']=flag(details['queued']);assert context is not None
                row['contextInherited']=True
            else:
                result=details['result'];keys(result,'Verified Attempted Reason Before After PreviousFocus NativeError')
                row.update(verified=flag(result['Verified']),attempted=flag(result['Attempted']),
                    reasonCode=reason_codes[result['Reason']],previousFocus=integer(result['PreviousFocus']),
                    nativeError=integer(result['NativeError'],0x7fffffff,-0x80000000))
                code=9
                for source,target in (('Before','before'),('After','after')):
                    if result[source] is not None:
                        row[target]=snapshot(result[source]);row[target+'Present']=True
                if row['beforePresent']:
                    before_context=attachment_identity(row['before'])
                    assert context is None or before_context==context
                    context=before_context
                else:
                    assert context is not None;row['contextInherited']=True
                if row['afterPresent']:
                    assert context is not None
                    assert attachment_identity(row['after'])==context
            rows.append(row)
        budget();code=4
        assert identity(path.lstat())==identity(before)
        code=6
        assert rows and context is not None
        # Failed writes consume sequence numbers; the logger also has a silent
        # cap and no completion marker. No absent event proves non-execution.
        return dict(schemaVersion=1,attempted=True,known=True,acceptanceEligible=False,errorCode=0,
            gapObserved=gap_count>0,gapCount=gap_count,eventCompletenessUnknown=True,scope=scope,rows=rows)
    except TimeoutError:
        return _initial_focus_unknown(10)
    except Exception:
        return _initial_focus_unknown(code)


def require_hwp_launcher_receipt(value, writer, suite):
    """Replay the one launcher without native calls or a document/Home claim."""
    from owned_native_menu import require_native_menu_action
    from lifecycle_smoke import require_hwp_census_receipt
    from home_routing_smoke import _filetime, _require_live_binding, _require_exit_and_closure
    try:
        assert writer['module']=='writer' and writer['case']=='native-menu-writer'
        assert type(value) is dict and value['kind']=='owned-native-hwp-launcher'
        assert not any(key in value for key in ('errorType','handleReleaseErrorType'))
        assert all(value[key] is True for key in ('success','normalExitVerified','handleReleased',
            'visibleOwnedMainWindow','originalOfficeHomeNativeAvailable'))
        assert all(value[key] is False for key in ('documentCreated','hwpApplicationHomeReady','cleanupPending'))
        assert value['launchKind']=='no-argument-launcher' and value['noArgumentBasis']=='native-new-hwp-shell-route'
        assert type(value['closeRequests']) is int and value['closeRequests']==1
        shell_pid,document=writer['shellPid'],writer['windowHwnd']
        action=value['menuAction'];require_native_menu_action(action,shell_pid,document,'new-hwp')
        assert action['gesture'] is False
        assert action['binding']==dict(document=document,parent=writer['parentHwnd'],child=writer['childHwnd'],officePid=writer['officePid'])
        office=writer['nativeArchiveGeneration'];engine=action['originalEngine']
        assert (engine['pid'],engine['creationTime'])==(office['pid'],office['creationTime'])==(writer['officePid'],writer['officeCreationTime'])
        assert PureWindowsPath(engine['image'])==PureWindowsPath(office['image'])==PureWindowsPath(str(Path(suite)/'Office/program/soffice.bin'))
        shell=value['originalShell'];menu_shell=action['originalProcess']
        assert shell['kind']=='retained-suite-popen-process' and shell['pid']==menu_shell['pid']==shell_pid
        assert type(shell['handleValue']) is int and shell['handleValue']==menu_shell['handleValue']>0
        birth=_filetime(shell['nativeCreation']);assert birth==menu_shell['creationTime']
        shell_image=PureWindowsPath(str(Path(suite)/'OpenGeul.Office.exe'))
        assert PureWindowsPath(shell['nativeImage'])==PureWindowsPath(menu_shell['image'])==shell_image
        assert shell['nativeImageLength']==len(shell['nativeImage'].encode('utf-16-le'))//2
        assert type(shell['waitResult']) is int and shell['waitResult']==258
        assert type(shell['exitCode']) is int and shell['exitCode']==259
        activations=[row['originalProcess'] for row in writer['windowActivations'] if row['suiteHwnd']==document]
        assert activations and all((row['pid'],row['handleValue'],row['creationTime'])==(shell_pid,shell['handleValue'],birth)
            and PureWindowsPath(row['image'])==shell_image and row['waitResult']==258 for row in activations)
        executable=Path(suite)/'HWP/OpenGeul.exe';expected=PureWindowsPath(str(executable))
        censuses=value['censuses'];assert type(censuses) is list and 2<=len(censuses)<=451
        found=[require_hwp_census_receipt(row,shell_pid,birth,executable) for row in censuses]
        assert found[0] is None and found[-1]==value['generation']
        generation=value['generation'];assert set(generation)=={'pid','parentPid','executable','creationFileTime'}
        assert type(generation['pid']) is int and 0<generation['pid']<=0xffffffff
        assert generation['pid'] not in (shell_pid,writer['officePid'])
        assert type(generation['parentPid']) is int and generation['parentPid']==shell_pid
        assert PureWindowsPath(generation['executable'])==expected
        assert type(generation['creationFileTime']) is int and generation['creationFileTime']>censuses[0]['snapshotStartedFileTime']
        assert all(match is None or match==generation for match in found[1:])
        assert type(value['shellBindingChecks']) is int and value['shellBindingChecks']>=2*len(censuses)+3
        live=value['liveBinding'];_require_live_binding(live)
        assert (live['pid'],live['creationTime'])==(generation['pid'],generation['creationFileTime'])
        assert PureWindowsPath(live['nativeImage'])==PureWindowsPath(live['expectedImage'])==expected
        assert type(value['handleValue']) is int and value['handleValue']==live['handleValue']!=shell['handleValue']
        _require_exit_and_closure(value['exit'],[dict(pid=live['pid'],creationTime=live['creationTime'],
            handleValue=value['handleValue'],closeHandleResult=value['handleReleased'])],live)
        assert type(value['windowHwnd']) is int and value['windowHwnd']>0
        assert type(value['windowRootHwnd']) is type(value['windowPid']) is int
        assert value['windowRootHwnd']==value['windowHwnd'] and value['windowPid']==live['pid']
        assert type(value['webviewHwnds']) is list and 1<=len(value['webviewHwnds'])<=4096
        assert all(type(hwnd) is int and hwnd>0 and hwnd!=value['windowHwnd'] for hwnd in value['webviewHwnds'])
        assert type(value['originalOfficeHomeHwnd']) is int and value['originalOfficeHomeHwnd']==writer['originalHomeHwnd']>0
    except (AssertionError,KeyError,TypeError,ValueError,OverflowError,RecursionError):
        raise ValueError('Original native HWP launcher receipt is incomplete or foreign') from None
    return value


def _confirmed_shell_cleanup(record, pid, observed_exit):
    """Join the retained Popen observation to its producer's bounded cleanup."""
    try:
        receipt=record['testProcessCleanup']
        assert type(receipt) is dict and type(pid) is int and pid>0 and type(observed_exit) is int
        assert type(receipt['shellPid']) is int and receipt['shellPid']==pid
        assert type(receipt['shellExitCode']) is int and receipt['shellExitCode']==observed_exit
        assert type(receipt['forceRequested']) is bool and receipt['gracefulShutdownVerified'] is False
        if not receipt['forceRequested']:return receipt['disposition']=='already-exited'
        for key in ('commandBudgetStartedAt','commandBudgetDeadline','commandReturnedAt'):
            assert type(receipt[key]) in (int,float) and math.isfinite(receipt[key])
        assert type(receipt['commandBudgetSeconds']) is int and receipt['commandBudgetSeconds']==15
        assert receipt['commandBudgetDeadline']==receipt['commandBudgetStartedAt']+15
        assert receipt['commandBudgetStartedAt']<=receipt['commandReturnedAt']<=receipt['commandBudgetDeadline']
        assert type(receipt['commandExitCode']) is int
        if receipt['disposition']=='exit-zero-after-taskkill-not-found':
            return (observed_exit==0 and receipt['commandExitCode']==128 and record.get('cleanupExitRaceVerified') is True
                and type(record.get('cleanupProcessExitCode')) is int and record['cleanupProcessExitCode']==0)
        assert receipt['disposition']=='forced-stop-returned' and receipt['commandExitCode'] in (0,128)
        for key in ('exitWaitStartedAt','exitWaitDeadline','exitWaitReturnedAt'):
            assert type(receipt[key]) in (int,float) and math.isfinite(receipt[key])
        assert type(receipt['exitWaitStageCode']) is int and receipt['exitWaitStageCode']==2
        assert type(receipt['exitWaitBudgetSeconds']) is int and receipt['exitWaitBudgetSeconds']==5
        assert receipt['exitWaitStartedAt']==receipt['commandReturnedAt']
        assert receipt['exitWaitDeadline']==receipt['exitWaitStartedAt']+5
        assert receipt['exitWaitStartedAt']<=receipt['exitWaitReturnedAt']<=receipt['exitWaitDeadline']
        return True
    except (AssertionError,KeyError,TypeError,ValueError,OverflowError):return False


class WindowsSession:
    """Real native boundaries; construction itself acquires no resources."""
    actual_windows = True

    def __init__(self, suite, fixtures, output, module):
        self.suite, self.fixtures, self.output, self.module = suite, fixtures, output, module
        self.process = self.api = self.engine = None
        self.hwnd = self.parent = self.child = self.office_pid = 0
        self.home_hwnd = 0

    def open(self, record):
        assert os.name == 'nt' and __debug__, 'Actual Windows GUI with assertions is required'
        import windows_smoke as native
        import startup_smoke as startup
        import owned_native_menu as menu
        from pywinauto import Desktop
        self.native, self.menu, self.desktop = native, menu, Desktop
        self.process = native.launch_suite(native.new_document_command(self.suite, self.module),
            self.suite, self.output, record['case'])
        self.api = native.Windows()
        self.hwnd, self.parent, self.child, self.office_pid = native.verified_attachment(
            self.api, self.process, self.module)
        attachment = dict(hwnd=self.hwnd, parent=self.parent, child=self.child,
                          officePid=self.office_pid)
        record['nativeArchiveGeneration'] = native.capture_native_archive_generation(
            self.api, self.process, attachment)
        self.engine = startup.EngineProcessWitness(self.office_pid)
        record.update(shellPid=self.process.pid, windowHwnd=self.hwnd, parentHwnd=self.parent,
            childHwnd=self.child, officePid=self.office_pid,
            officeCreationTime=self.engine.creation_time, nativeParentVerified=True)
        self.home_hwnd = int(self.api.home(self.process) or 0)
        self._home_ready()
        record['originalHomeHwnd'] = self.home_hwnd
        self._observe_open_focus(record, 1)
        self.desktop(backend='win32').window(handle=self.hwnd).wrapper_object().maximize()
        self._observe_open_focus(record, 2)
        native.activate_owned_suite(self.api, self.process, self.hwnd, record)
        self._observe_open_focus(record, 3)
        self.api.require_foreground(self.hwnd)

    def _observe_open_focus(self, record, phase):
        """Three passive numeric observations; a ready hint is not editor proof.

        In particular phase 1 with attachReadyObserved=0 cannot establish that
        product attachment had completed before the harness maximized the form.
        These fixed native queries introduce no wait, input, or COM client.
        """
        assert type(phase) is int and phase in (1, 2, 3)
        rows = record.get('openingFocusObservations', [])
        assert len(rows) == phase-1 and [row['phaseCode'] for row in rows] == list(range(1, phase))
        def identity():
            return (self.process.pid, int(self.process._handle), int(self.engine.handle), self.engine.creation_time,
                self.hwnd, self.parent, self.child, self.office_pid)
        current = identity()
        original = getattr(self, '_opening_focus_identity', current)
        def owned():
            assert current == original == identity()
            assert self.process.poll() is None and not self.engine.exited(0)
            assert self.api.attachment(self.hwnd) == (self.parent, self.child, self.office_pid)
            generation = record['nativeArchiveGeneration']
            assert (generation['pid'], generation['creationTime']) == (self.office_pid, self.engine.creation_time)
        owned()
        self._opening_focus_identity = original
        def window(hwnd):
            hwnd = int(hwnd or 0)
            return dict(hwnd=hwnd, pid=int(self.api.pid(hwnd)) if hwnd else 0,
                rootHwnd=int(self.api.user.GetAncestor(hwnd, 2) or 0) if hwnd else 0)
        def gui(hwnd):
            thread = int(self.api.user.GetWindowThreadProcessId(hwnd, None))
            assert thread > 0, 'Original focus observation thread is unavailable'
            state = self.native.GuiThreadInfo(cbSize=ctypes.sizeof(self.native.GuiThreadInfo))
            assert self.api.user.GetGUIThreadInfo(thread, ctypes.byref(state)), 'Original focus observation query failed'
            focus = window(state.hwndFocus)
            return dict(threadId=thread, activeHwnd=int(state.hwndActive or 0), focusHwnd=focus['hwnd'],
                focusPid=focus['pid'], focusRootHwnd=focus['rootHwnd'], captureHwnd=int(state.hwndCapture or 0),
                menuOwnerHwnd=int(state.hwndMenuOwner or 0), flags=int(state.flags))
        host, engine = gui(self.hwnd), gui(self.child)
        foreground = window(self.api.user.GetForegroundWindow())
        hint = self.api.user.GetPropW(self.hwnd, 'OpenGeul.Office.NativeMenuReady')
        assert hint is None or type(hint) is int and 0 <= hint < 2**64
        row = dict(phaseCode=phase, nativeReadyHint=int(hint or 0), attachReadyObserved=int(hint == 1),
            hostGui=host, engineGui=engine, foreground=foreground)
        owned()
        assert len(json.dumps(rows+[row], separators=(',', ':')).encode()) <= 128*1024
        record.setdefault('openingFocusObservations', []).append(row)

    def ready(self):
        return self.menu.native_menu_active(self.api, self.process, self.hwnd) is True

    def gesture(self, name, record):
        result = self.menu.inspect_native_menu(self.api, self.process, self.hwnd,
            record, name)
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-native-menu-action' and result.get('gesture') is True
        assert result.get('command') == name, 'Native gesture receipt belongs to another operation'
        return dict(gesture=name, success=True, receipt=result)

    def _owned_blank(self):
        assert self.process.poll() is None and not self.engine.exited(0)
        assert all(self.api.user.IsWindow(h) for h in (self.hwnd, self.parent, self.child))
        assert (self.api.pid(self.hwnd), self.api.pid(self.parent), self.api.pid(self.child)) == (
            self.process.pid, self.process.pid, self.office_pid)
        assert self.api.user.GetAncestor(self.hwnd, 2) == self.hwnd
        assert self.api.user.IsChild(self.hwnd, self.parent) and self.api.user.IsChild(self.parent, self.child)
        assert (int(self.api.user.GetPropW(self.hwnd, 'OpenGeul.Office.ParentHwnd') or 0),
                int(self.api.user.GetPropW(self.hwnd, 'OpenGeul.Office.ChildHwnd') or 0)) == (self.parent, self.child)
        self.api.require_foreground(self.hwnd)

    def screenshot(self, record, *, initial=False):
        assert type(initial) is bool and self.module in MODULES and record.get('case') == 'native-menu-' + self.module
        self._owned_blank()
        capture_error = None
        try:
            image = self.desktop(backend='win32').window(handle=self.hwnd).wrapper_object().capture_as_image()
        except Exception as exc:
            if not initial: raise
            capture_error = type(exc).__name__
        # Ownership failures remain primary even if the optional image failed.
        self._owned_blank()
        if capture_error is not None:
            record['initialScreenshotErrorType'] = capture_error
            return None
        name = record['case'] + ('-initial-chrome.png' if initial else '-chrome.png')
        try:
            cropped = image.crop((0, 0, image.width, min(240, image.height)))
            with (self.output / name).open('xb') as stream:
                cropped.save(stream, format='PNG')
        except Exception as exc:
            if not initial: raise
            record['initialScreenshotErrorType'] = type(exc).__name__
            return None
        record['initialScreenshotScope' if initial else 'screenshotScope'] = 'owned-fresh-blank-form-top-240-pixels'
        return name

    def _native_command(self, command, record):
        result = self.menu.click_native_menu_action(self.api, self.process, self.hwnd, record, command)
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-native-menu-action' and result.get('gesture') is False
        assert result.get('command') == command
        return result

    def view_roundtrip(self, record):
        """Keep the original blank document through measured native view changes."""
        from owned_fullscreen import toggle_native_fullscreen
        from owned_native_menu import decode_status_sequence
        assert self.module in VIEW_MODULES
        self._owned_blank()
        assert self.ready() is True
        value = dict(kind='native-view-roundtrip', module=self.module, success=False,
            previewActions=[], observations=[], fullscreenActions=[], coreCommands=[])
        record['nativeViewRoundtrip'] = value
        identity = None
        previous_status = previous_observation_finish = None
        def checked(receipt, kind):
            nonlocal identity
            assert type(receipt) is dict and receipt.get('success') is True and receipt.get('kind') == kind
            binding = receipt.get('binding')
            expected = dict(document=self.hwnd, parent=self.parent, child=self.child, officePid=self.office_pid)
            assert type(binding) is dict and all(type(binding.get(key)) is int and binding[key] == item
                for key, item in expected.items()), 'Native view receipt belongs to another attachment'
            shell, engine = receipt.get('originalProcess'), receipt.get('originalEngine')
            assert type(shell) is dict and type(engine) is dict
            assert (shell.get('pid'), shell.get('handleValue'), shell.get('waitResult')) == (
                self.process.pid, int(self.process._handle), 258)
            assert Path(shell['image']).resolve() == self.suite/'OpenGeul.Office.exe'
            assert type(shell.get('creationTime')) is int and shell['creationTime'] > 0
            generation = record['nativeArchiveGeneration']
            assert all(type(engine.get(key)) is int and engine[key] == generation[key]
                for key in ('pid', 'creationTime'))
            assert engine['pid'] == self.office_pid and engine.get('waitResult') == 258
            assert Path(engine['image']).resolve() == Path(generation['image']).resolve() == self.suite/'Office/program/soffice.bin'
            current = (shell['creationTime'], engine['pid'], engine['creationTime'])
            assert identity is None or current == identity, 'Native view changed the original process generations'
            identity = current
            assert receipt.get('engineHandleReleased') is True and receipt.get('providerClientReleased') is True
            assert receipt.get('dpiScope', {}).get('verified') is True and receipt['dpiScope'].get('restored') is True
            times = [receipt.get(key) for key in ('startedAt', 'deadline', 'finishedAt')]
            assert all(type(item) in (int, float) and math.isfinite(item) for item in times)
            start, deadline, finish = times
            assert start <= finish < deadline <= start + 5
            return receipt
        def observe(preview, menu_visible):
            nonlocal previous_status, previous_observation_finish
            receipt = checked(self.menu.observe_native_view(self.api, self.process, self.hwnd, record,
                module=self.module, preview=preview, menu_visible=menu_visible, hold_seconds=3, seconds=5),
                'owned-native-view-observation')
            assert receipt.get('module') == self.module and receipt.get('preview') is preview
            assert receipt.get('menuVisible') is menu_visible and receipt.get('holdSeconds') == 3
            observed = receipt.get('observedSeconds')
            assert type(observed) in (int, float) and math.isfinite(observed) and 3 <= observed < 5
            assert observed <= receipt['finishedAt'] - receipt['startedAt'], 'Native view observation exceeds its actual elapsed time'
            assert type(receipt.get('samples')) is list and 2 <= len(receipt['samples']) <= 64
            assert receipt.get('statusRpcProved') is True and type(receipt.get('inputCallAttempts')) is int and receipt['inputCallAttempts'] == 0
            assert type(receipt.get('statusSequenceVersion')) is int and receipt['statusSequenceVersion'] == 1
            baseline, completed = (receipt.get(key) for key in ('firstTargetStartedSequence','lastTargetCompletedSequence'))
            assert all(type(item) is int and 0 <= item < (1 << 28) for item in (baseline,completed))
            assert completed > baseline
            assert previous_observation_finish is None or receipt['startedAt'] >= previous_observation_finish
            first = first_started = last_at = None
            sequence = previous_status
            for sample in receipt['samples']:
                assert type(sample) is dict and type(sample.get('state')) is dict
                state, at = sample['state'], sample.get('observedAt')
                assert type(at) in (int,float) and math.isfinite(at)
                assert receipt['startedAt'] <= at <= receipt['finishedAt'] and at < receipt['deadline']
                assert last_at is None or at >= last_at
                last_at = at
                decoded = decode_status_sequence(state['statusSequenceRaw'])
                supplied = sample.get('statusSequence')
                assert type(supplied) is dict and set(supplied) == {'version','started','completed'}
                assert all(type(item) is int for item in supplied.values()) and supplied == decoded
                assert sequence is None or all(decoded[key] >= sequence[key] for key in ('started','completed'))
                sequence = decoded
                assert all(type(state.get(key)) is int and state[key] in (0,1)
                    for key in ('nativeMenuBarCount','previewIndicatorCount'))
                matched = state['nativeMenuBarCount'] == int(menu_visible) and state['previewIndicatorCount'] == int(preview)
                assert type(sample.get('targetMatched')) is bool and sample['targetMatched'] is matched
                if not matched:
                    first = first_started = None
                elif first is None:
                    first, first_started = at, decoded['started']
            assert first is not None and last_at - first >= 3
            assert type(receipt.get('settledAt')) in (int,float) and math.isfinite(receipt['settledAt'])
            assert receipt['settledAt'] == first and observed == last_at - first
            assert first_started == baseline and sequence['completed'] == completed
            previous_status, previous_observation_finish = sequence, receipt['finishedAt']
            value['observations'].append(receipt)
        def core():
            receipt = checked(self.gesture('core-commands', record)['receipt'], 'owned-native-menu-action')
            assert receipt.get('coreCommandsVerified') is True and receipt.get('coreCommands') == list(CORE_COMMANDS)
            assert receipt.get('focusReturned') is True
            value['coreCommands'].append(receipt)
        record['stage'] = 'print-preview-enter'
        value['previewActions'].append(checked(self._native_command('printPreview', record), 'owned-native-menu-action'))
        observe(True, True)
        record['stage'] = 'print-preview-leave'
        value['previewActions'].append(checked(self._native_command('printPreview', record), 'owned-native-menu-action'))
        observe(False, True)
        core()
        for menu_visible in (False, True):
            record['stage'] = 'fullscreen-enter' if not menu_visible else 'fullscreen-leave'
            receipt = checked(toggle_native_fullscreen(self.api, self.process, self.hwnd, record,
                module=self.module, seconds=5), 'owned-native-fullscreen-toggle')
            assert receipt.get('module') == self.module and receipt.get('focusReturned') is True
            assert all(type(receipt.get(key)) is int for key in ('inputCallAttempts', 'requestedInputs', 'insertedInputs'))
            assert (receipt['inputCallAttempts'], receipt['requestedInputs'], receipt['insertedInputs']) == (1, 6, 6)
            value['fullscreenActions'].append(receipt)
            observe(False, menu_visible)
        core()
        self._owned_blank()
        assert self.ready() is True
        assert self._home_ready(active=False) is True
        value['originalHomeSurvived'] = True
        value['success'] = True
        return value

    def _wait_original_closed(self):
        self.native.wait_for(lambda: not self.api.user.IsWindow(self.hwnd), seconds=20)
        self.native.wait_for(lambda: not self.api.user.IsWindow(self.child), seconds=10)

    def _home_ready(self, *, active=False):
        assert self.home_hwnd and self.process.poll() is None
        assert self.api.home(self.process) == self.home_hwnd
        assert self.api.pid(self.home_hwnd) == self.process.pid
        assert self.api.user.GetAncestor(self.home_hwnd, 2) == self.home_hwnd
        assert not self.api.user.GetPropW(self.home_hwnd, 'OpenGeul.Office.ChildHwnd')
        if not active:
            return True
        foreground = self.api.user.GetForegroundWindow()
        return bool(self.api.user.IsWindowVisible(self.home_hwnd) and foreground
            and self.api.user.GetAncestor(foreground, 2) == self.home_hwnd)

    def _cancel_calc_exit(self, record, *, deadline):
        from owned_menu_cancel import cancel_native_menu_prompt
        caption = 'OpenGeul Calc'
        assert deadline > time.monotonic(), 'Original Calc cancel readiness deadline expired'
        def find():
            dialogs = [h for h in self.api.windows(self.process.pid)
                if self.api.user.GetWindow(h, 4) == self.hwnd and self.api.title(h) == caption]
            assert len(dialogs) <= 1, 'Calc close prompt is ambiguous'
            if not dialogs:
                return None
            dialog, = dialogs
            self.native.require_dialog_identity(self.api.pid(dialog), self.process.pid,
                self.api.user.GetWindow(dialog, 4), self.hwnd, self.api.title(dialog),
                caption, self.api.class_name(dialog))
            return dialog
        dialog = self.native.wait_for(find, seconds=deadline - time.monotonic())
        self.api.require_foreground(dialog)
        remaining = deadline - time.monotonic()
        assert remaining > 0, 'Original Calc cancel readiness deadline expired'
        result = cancel_native_menu_prompt(self.api, self.process, self.hwnd, record,
            dialog, caption, seconds=min(5, remaining))
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-shell-menu-cancel'
        snapshots = result.get('snapshots')
        assert type(snapshots) is list and snapshots and all(type(row) is dict
            and row.get('promptSchemaVerified') is True for row in snapshots), \
            'Bounded Calc prompt schema proof is missing'
        assert not self.api.user.IsWindow(dialog), 'Original Calc prompt survived its one Cancel action'
        record['nativeExitCancelAction'] = result
        return True

    def hwp_launcher(self, record):
        """One no-argument native launcher, never an HWP document-creation claim."""
        import lifecycle_smoke as lifecycle
        from home_routing_smoke import freeze_live_process, retained_exit
        assert self.module == 'writer'
        self._owned_blank()
        self.hwp_unretired = True  # Uncertain dispatch/binding must never reach tree cleanup.
        value = dict(kind='owned-native-hwp-launcher', success=False, launchKind='no-argument-launcher',
            noArgumentBasis='native-new-hwp-shell-route', documentCreated=False,
            hwpApplicationHomeReady=False, originalOfficeHomeHwnd=self.home_hwnd,
            censuses=[], shellBindingChecks=0, cleanupPending=True,
            closeRequests=0, normalExitVerified=False, handleReleased=False)
        record['nativeHwpLauncher'] = value
        executable = (self.suite / 'HWP/OpenGeul.exe').resolve(strict=True)
        assert executable.is_file()
        shell = {}; creation = lifecycle.retained_writer_shell(self.process, self.suite, shell)
        value['originalShell'] = shell
        shell_identity = (self.process.pid, int(self.process._handle), creation)
        bound = None; primary = None
        def owner():
            current = {}
            observed = lifecycle.retained_writer_shell(self.process, self.suite, current)
            assert (self.process.pid, int(self.process._handle), observed) == shell_identity
            value['shellBindingChecks'] += 1
            assert self.api.attachment(self.hwnd) == (self.parent, self.child, self.office_pid)
            assert not self.engine.exited(0)
            assert self._home_ready() is True
            assert self.api.user.IsWindowVisible(self.home_hwnd) and self.api.user.IsWindowEnabled(self.home_hwnd)
        def census():
            owner(); rows = value['censuses']; assert len(rows) < 451
            evidence = {}; rows.append(evidence)
            found = lifecycle._hwp_child_process(self.process.pid, executable,
                shell_creation=creation, evidence=evidence)
            assert lifecycle.require_hwp_census_receipt(evidence,self.process.pid,creation,executable) == found
            owner(); return found
        try:
            assert census() is None, 'The fresh Writer already owns an HWP generation'
            before = value['censuses'][0]['snapshotStartedFileTime']
            value['menuAction'] = self._native_command('new-hwp', record)
            found = self.native.wait_for(census, seconds=45)
            assert found['parentPid'] == self.process.pid and Path(found['executable']).resolve() == executable
            assert type(found['creationFileTime']) is int and found['creationFileTime'] > before
            value['generation'] = dict(found)
            bound = lifecycle.BoundHwpProcess(found['pid'], executable, expected_creation=found['creationFileTime'])
            freeze_live_process(bound, executable, value.setdefault('liveBinding', {}))
            def visible():
                owner(); assert bound.live()
                roots = [h for h in self.api.windows(bound.pid)
                    if self.api.class_name(h) in ('Tauri Window', 'Chrome_WidgetWin_1')]
                assert len(roots) <= 1, 'Owned HWP launcher root is ambiguous'
                if not roots: return None
                hwnd, = roots
                assert self.api.pid(hwnd) == bound.pid and self.api.user.GetAncestor(hwnd,2) == hwnd
                assert self.api.user.IsWindowVisible(hwnd) and self.api.user.IsWindowEnabled(hwnd)
                window = self.desktop(backend='win32').window(handle=hwnd).wrapper_object()
                browsers = [int(item.handle) for item in window.descendants()
                    if item.class_name() in ('Chrome_WidgetWin_0', 'Chrome_WidgetWin_1', 'Chrome_RenderWidgetHostHWND')]
                return (hwnd,browsers) if browsers else None
            hwnd,browsers = self.native.wait_for(visible, seconds=75)
            value.update(windowHwnd=int(hwnd), webviewHwnds=browsers, visibleOwnedMainWindow=True,
                windowPid=bound.pid, windowRootHwnd=int(hwnd), originalOfficeHomeNativeAvailable=True)
            owner(); assert bound.live()
            self.api.request_close(hwnd,bound.pid); value['closeRequests'] = 1
            self.native.wait_for(lambda:not self.api.user.IsWindow(hwnd), seconds=25)
            self.native.wait_for(lambda:not bound.live(), seconds=25)
            retained_exit(bound, value.setdefault('exit', {})); value['normalExitVerified'] = True
            owner()
            self.native.activate_owned_suite(self.api,self.process,self.hwnd,record)
            self._owned_blank()
        except BaseException as exc:
            primary = exc; value['errorType'] = type(exc).__name__; raise
        finally:
            if bound is not None:
                try:
                    value['handleValue'] = int(bound.handle)
                    bound.close(); value['handleReleased'] = bound.handle is None
                    assert value['handleReleased'] is True
                except BaseException as exc:
                    value['handleReleaseErrorType'] = type(exc).__name__
                    if primary is None: raise
            if value['normalExitVerified'] and value['handleReleased']: self.hwp_unretired = False
            value['cleanupPending'] = self.hwp_unretired
        value['success'] = value['normalExitVerified'] and value['handleReleased'] and not value['cleanupPending']
        assert value['success'] is True
        return value

    def finish(self, record):
        saved_base = None
        if self.module == 'base':
            # A private fresh target avoids changing the shared fixture set used
            # by the original two full GUI runs.
            owned = self.output / 'native-menu-base-generated'
            owned.mkdir(exist_ok=False)
            saved_base = self.native.save_new_base(self.api, self.process, self.hwnd,
                owned, self.output, record)
            assert record['baseSaveMenuAction']['kind'] == 'owned-native-menu-action', \
                'Native Base Save must not be qualified by the WinForms fallback'
        if self.module == 'writer':
            self._native_command('home', record)
            self._wait_original_closed()
            self.native.wait_for(lambda: self._home_ready(active=True), seconds=10)
            self.api.require_foreground(self.home_hwnd)
            record['nativeHomeVerified'] = True
        elif self.module in ('draw', 'math'):
            self._native_command('close', record)
            self._wait_original_closed()
            record['nativeCloseVerified'] = True
        elif self.module == 'calc':
            exit_deadline = time.monotonic() + 20  # Existing close-prompt bound, including the menu action.
            self._native_command('exit', record)
            assert self._cancel_calc_exit(record, deadline=exit_deadline) is True
            self._owned_blank()
            assert self.ready() is True
            record['postExitCancelMenu'] = self.gesture('open-escape', record)
            record['nativeExitCancelVerified'] = True
            from generated_calc_close import freeze_generated_blank_calc
            proof = freeze_generated_blank_calc(self.suite, self.api, self.process,
                self.hwnd, self.child, record)
            self.native.close_document(self.api, self.process, self.hwnd, self.child,
                record, calc_close_proof=proof)
        elif self.module == 'base':
            self._native_command('exit', record)
            self._wait_original_closed()
            self.process.wait(timeout=25)
            assert self.process.returncode == 0
            assert not self.api.user.IsWindow(self.home_hwnd), 'Native Exit left the original Home alive'
            record['nativeExitVerified'] = True
        else:
            self.native.close_document(self.api, self.process, self.hwnd, self.child, record)
        if self.module != 'base':
            self.native.close_home(self.api, self.process, record)
        record['officeExited'] = self.engine.exited(10)
        assert record['officeExited'], 'Original native engine survived normal menu scenario shutdown'
        record['officeExitCode'] = self.engine.code()
        assert record['officeExitCode'] == 0 and self.process.returncode == 0
        if saved_base is not None:
            record['savedBaseEvidence'] = self.native.saved_base_evidence(saved_base)
        record['cleanClose'] = True
        return True

    def cleanup(self, record):
        shell_done = True
        engine_done = engine_released = self.process is None
        if self.process is not None:
            record['forcedCleanupRequired'] = self.process.poll() is None
            if getattr(self,'hwp_unretired',False):
                record['shellCleanupSuppressedForHwp'] = True
            else:
                self.native.stop_owned_test_process(self.process, record)
            record['shellExitCode'] = self.process.poll()
            shell_done = _confirmed_shell_cleanup(record,self.process.pid,record['shellExitCode'])
            record['shellCleanupConfirmed'] = shell_done
        if self.engine is not None:
            try:
                engine_done = self.engine.exited(5)
                record['officeExitedAfterCleanup'] = engine_done
            finally:
                handle = self.engine.handle
                engine_released = bool(handle and self.engine.close_handle(handle))
                record['engineHandleReleased'] = engine_released
                if engine_released:
                    self.engine.handle = None
        return bool(shell_done and engine_done and engine_released and not getattr(self,'hwp_unretired',False))


def run_case(suite, fixtures, output, module, *, session_factory=WindowsSession):
    if module not in MODULES:
        raise ValueError('Unknown native menu module')
    record = dict(case='native-menu-' + module, module=module, success=False,
        kind='native-menu-gesture-case', stage='open', gestures=[],
        keyboardInputVerified=False, contentMutationVerified=False,
        scenarioCompleted=False, actualWindowsExecuted=False,
        viewRoundtripCompleted=False, viewPhysicalVerified=False,
        nativeMenuVerified=False, cleanupConfirmed=False, cleanClose=False,
        hwpLauncherCompleted=False, nativeHwpMenuLaunchExecuted=False)
    started = time.monotonic()
    session = None
    try:
        session = session_factory(suite, fixtures, output, module)
        record['actualWindowsExecuted'] = session.actual_windows is True and os.name == 'nt'
        session.open(record)
        record['stage'] = 'require-native-menu'
        assert session.ready() is True, 'The actual native menu surface is unavailable'
        record['stage'] = 'capture-initial-owned-blank-chrome'
        initial = session.screenshot(record, initial=True)
        if initial is not None: record['initialScreenshot'] = initial
        for index, gesture in enumerate(GESTURES):
            record['stage'] = gesture
            result = session.gesture(gesture, record)
            assert type(result) is dict and result.get('success') is True
            assert result.get('gesture') == gesture
            record['gestures'].append(dict(index=index, gesture=gesture, receipt=result))
        if module in VIEW_MODULES:
            record['stage'] = 'native-view-roundtrip'
            result = session.view_roundtrip(record)
            assert type(result) is dict and result.get('success') is True
            assert result.get('kind') == 'native-view-roundtrip' and result.get('module') == module
            record['nativeViewRoundtrip'] = result
            record['viewRoundtripCompleted'] = True
        record['stage'] = 'capture-owned-blank-chrome'
        record['screenshot'] = session.screenshot(record)
        if module == 'writer':
            record['stage'] = 'native-hwp-launcher'
            result = session.hwp_launcher(record)
            assert type(result) is dict and result.get('success') is True
            assert result.get('kind') == 'owned-native-hwp-launcher'
            if type(session) is WindowsSession: require_hwp_launcher_receipt(result,record,suite)
            record['hwpLauncherCompleted'] = True
        record['stage'] = 'close-original-document-and-home'
        assert session.finish(record) is True
        record.update(success=True, scenarioCompleted=True)
    except Exception as exc:
        record['errorType'] = type(exc).__name__
    finally:
        if session is not None:
            try:
                record['initialFocusTrace'] = capture_initial_focus_trace(session, record)
            except Exception:
                record['initialFocusTrace'] = _initial_focus_unknown(11)
            try:
                record['cleanupConfirmed'] = session.cleanup(record) is True
            except Exception as exc:
                record['cleanupErrorType'] = type(exc).__name__
        if not record['cleanupConfirmed']:
            record['success'] = False
        record['nativeMenuVerified'] = record['success'] and record['actualWindowsExecuted']
        record['nativeHwpMenuLaunchExecuted'] = bool(record['nativeMenuVerified'] and record['hwpLauncherCompleted']
            and type(session) is WindowsSession)
        record['viewPhysicalVerified'] = bool(record['nativeMenuVerified'] and record['viewRoundtripCompleted']
            and type(session) is WindowsSession)
        if record['success']:
            record['stage'] = 'complete'
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return record


def run_modules(suite, fixtures, output, *, session_factory=WindowsSession):
    records = []
    for module in MODULES:
        record = run_case(suite, fixtures, output, module, session_factory=session_factory)
        records.append(record)
        with (output / (record['case'] + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False, indent=2)
        print(module + ': ' + ('passed' if record['success'] else 'FAILED: ' + record.get(
            'errorType', record.get('cleanupErrorType', 'unconfirmed cleanup'))), flush=True)
        if not record['cleanupConfirmed']:
            break  # An unretired original engine cannot authorize the next case.
    counts = Counter(row['module'] for row in records)
    complete = tuple(row['module'] for row in records) == MODULES and all(n == 1 for n in counts.values())
    scenario_success = complete and all(row['success'] for row in records)
    native_verified = scenario_success and all(row['nativeMenuVerified'] for row in records)
    view_records = [row for row in records if row['module'] in VIEW_MODULES]
    views_verified = bool(native_verified and tuple(row['module'] for row in view_records) == VIEW_MODULES
        and all(row['viewPhysicalVerified'] for row in view_records))
    hwp_verified = bool(records and records[0]['module']=='writer' and records[0]['nativeHwpMenuLaunchExecuted'])
    report = dict(schemaVersion=1, kind='native-menu-gesture-matrix', success=native_verified and views_verified and hwp_verified,
        scenarioSuccess=scenario_success, actualWindowsExecuted=bool(records) and all(
            row['actualWindowsExecuted'] for row in records), nativeMenuVerified=native_verified,
        acceptanceEligible=False, expectedCaseCount=len(MODULES), completedCaseCount=len(records),
        viewPhysicalVerified=views_verified, viewPhysicalExpectedCaseCount=len(VIEW_MODULES),
        viewPhysicalVerifiedCaseCount=sum(row['viewPhysicalVerified'] for row in view_records),
        nativeHwpMenuLaunchExecuted=hwp_verified, disabledCommandsPhysicalVerified=False,
        passedCaseCount=sum(row['success'] for row in records),
        missingModules=[module for module in MODULES if module not in counts],
        failedModules=[row['module'] for row in records if not row['success']],
        externalAcceptanceGates=list(EXTERNAL_GATES), tests=records)
    with (output / 'results.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'fixtures', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    assert os.name == 'nt' and __debug__, 'Actual Windows GUI with assertions is required'
    paths = (args.suite, args.fixtures, args.output)
    for path in paths:
        for part in (path, *path.parents):
            assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)()
    suite, fixtures, output = (path.resolve() for path in paths)
    assert suite.is_dir() and fixtures.is_dir()
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output))
    assert suite != output and suite not in output.parents
    assert fixtures != output and fixtures not in output.parents
    output.mkdir(parents=True, exist_ok=False)
    return 0 if run_modules(suite, fixtures, output)['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
