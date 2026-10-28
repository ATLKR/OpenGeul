"""Bounded, numeric-only observation of the original Calc save dispatch.

No input, hooks, model readers or save retries live here. The caller owns its
single Ctrl+S and passes the original absolute deadline, including cleanup.
Only a duplicate of the caller's retained original engine HANDLE is acquired.
"""
from __future__ import annotations

import ctypes as C
from collections.abc import Mapping
import math
import secrets
import time


MAGIC, VERSION, CAPACITY, MAX_DEPTH = 0x4344474f, 1, 128, 8
KIND = 'calc-save-dispatch-diagnostic'
ENVIRONMENT = 'OPENGEUL_CALC_DISPATCH_DIAGNOSTIC'
U32, U64, I64 = C.c_uint32, C.c_uint64, C.c_int64


class Identity(C.Structure):
    _pack_ = 8
    _fields_ = [(name,U32) for name in ('magic','version','bytes','controllerPid','ownerPid',
        'ownerTid','reserved0','reserved1')] + [(name,U64) for name in
        ('nonce','controllerCreated','ownerCreated','ownerHwnd')] + [(name,I64) for name in
        ('startQpc','deadlineQpc','qpcFrequency')]


class Event(C.Structure):
    _pack_ = 8
    _fields_ = [(name,U32) for name in ('sequence','phase','operation','invocation','parent',
        'depth','value','reserved')] + [('qpc',I64)]


class State(C.Structure):
    _pack_ = 8
    _fields_ = [('identity',Identity)] + [(name,U32) for name in ('enabled','count','rejected',
        'overflow','expired','active','depth','cleanupErrors','nextInvocation','reserved')] + [
        ('stack',U32*MAX_DEPTH),('events',Event*CAPACITY)]


def abi_layout():
    """Every size, alignment and field offset is checked against compiled C++."""
    result = [MAGIC,VERSION,CAPACITY,MAX_DEPTH,C.sizeof(Identity),C.sizeof(Event),C.sizeof(State),
              C.alignment(Identity),C.alignment(Event),C.alignment(State)]
    for structure in (Identity,Event,State):
        result.extend(getattr(structure,name).offset for name,_ in structure._fields_)
    return tuple(result)


def _require(condition, message):
    if not condition: raise ValueError(message)


def _keys(value, names):
    _require(type(value) is dict and set(value) == set(names), 'Invalid numeric diagnostic schema')


def _number(value, maximum=0xffffffff, minimum=0):
    _require(type(value) is int and minimum <= value <= maximum, 'Invalid numeric diagnostic field')
    return value


def _identity(value):
    _keys(value,(name for name,_ in Identity._fields_))
    for name,kind in Identity._fields_:
        _number(value[name],0xffffffff if kind is U32 else (2**63-1 if kind is I64 else 2**64-1))
    _require((value['magic'],value['version'],value['bytes']) == (MAGIC,VERSION,C.sizeof(State)),
             'Diagnostic identity ABI differs')
    _require(value['reserved0'] == value['reserved1'] == 0, 'Nonzero reserved identity')
    _require(all(value[name] for name in ('controllerPid','ownerPid','ownerTid','nonce',
        'controllerCreated','ownerCreated','ownerHwnd')), 'Missing diagnostic generation')
    _require(value['controllerPid'] != value['ownerPid'], 'Controller owns engine PID')
    _require(0 < value['qpcFrequency'] <= (2**63-1)//30 and
        0 < value['deadlineQpc']-value['startQpc'] <= 30*value['qpcFrequency'],
        'Diagnostic deadline is invalid or renewed')


def _empty_exit():
    return dict(observed=0,handleValue=0,pid=0,creationTime=0,waitResult=0,exitCode=0,withinDeadline=0)


def _empty_cleanup():
    return dict(controllerResourcesReleased=0,viewReleased=0,mappingReleased=0,
        engineHandleReleased=0,libraryReleased=0,scopesObservedIdle=0,remoteQuiescenceProved=0,
        remoteViewRetired=0,deadlineExpired=0,errors=[])


def decode_artifact(value, expected_identity=None):
    """Reject extra/content fields; derive trace completeness and exit separately.

    An unpublished suffix remains a partial observation. Missing exit rows never
    become returned calls, even when native cleanup unwound the numeric stack.
    """
    fields=('schemaVersion','kind','acceptanceEligible','fullEngineQualified','identity','state',
            'stack','events','capture','exit','cleanup','snapshotError','analysis')
    _keys(value,fields)
    _require(type(value['schemaVersion']) is int and value['schemaVersion']==1 and
        type(value['kind']) is str and value['kind']==KIND,
             'Invalid diagnostic artifact version')
    _require(value['acceptanceEligible'] is False and value['fullEngineQualified'] is False,
             'Diagnostic runtime cannot qualify acceptance')
    _number(value['snapshotError'],1)
    identity=value['identity']
    if identity is not None:_identity(identity)
    else:_require(value['snapshotError']==1,'Missing diagnostic identity')
    if expected_identity is not None:
        _identity(expected_identity)
        _require(identity==expected_identity,'Immutable diagnostic identity changed')
    status=value['state'];names=[name for name,kind in State._fields_ if kind is U32]
    if status is None:
        _require(value['snapshotError']==1 and value['stack']==[] and value['events']==[],
                 'Absent snapshot contains event observations')
        status=dict.fromkeys(names,0)  # Used only for derivation, never exported as observations.
    else:
        _require(identity is not None,'State lacks an admitted identity')
        _keys(status,names)
        for number in status.values():_number(number)
    _require(status['enabled']<=1 and status['count']<=CAPACITY and
        status['active']<=MAX_DEPTH and status['depth']<=MAX_DEPTH and not status['reserved'],
        'Invalid bounded recorder state')
    stack=value['stack']
    _require(type(stack) is list and len(stack)==(MAX_DEPTH if value['state'] is not None else 0),
             'Invalid bounded recorder stack')
    for number in stack:_number(number)
    capture=value['capture'];_keys(capture,('stable','partialSequence','withinDeadline'))
    _number(capture['stable'],1);_number(capture['partialSequence'],CAPACITY);_number(capture['withinDeadline'],1)
    _require(value['state'] is not None or capture==dict(stable=0,partialSequence=0,withinDeadline=0),
             'Absent snapshot claims capture evidence')
    rows=value['events']
    _require(type(rows) is list and len(rows)<=status['count'],'Invalid bounded event count')
    _require(capture['partialSequence']==(len(rows)+1 if len(rows)<status['count'] else 0),
             'Incomplete publication suffix differs')
    open_calls=[];next_invocation=0;roots=0;last_qpc=identity['startQpc'] if identity else 0;returns=0
    for index,row in enumerate(rows):
        _keys(row,(name for name,_ in Event._fields_))
        for name,kind in Event._fields_:
            _number(row[name],2**63-1 if kind is I64 else 0xffffffff)
        _require(row['sequence']==index+1 and not row['reserved'],'Invalid event publication sequence')
        _require(1<=row['operation']<=4 and 1<=row['phase']<=9 and 1<=row['depth']<=MAX_DEPTH,
                 'Unknown numeric dispatch enum')
        _require(row['value'] <= (1 if row['phase'] in (3,9) else 0),'Invalid numeric dispatch outcome')
        _require(last_qpc<=row['qpc']<identity['deadlineQpc'],'Event is outside original deadline')
        last_qpc=row['qpc']
        if row['phase']==1:
            next_invocation+=1
            if not open_calls:
                roots+=1
                _require(roots==1 and row['operation']==1,'Only original ExecuteSave root is admitted')
            _require(row['invocation']==next_invocation and row['depth']==len(open_calls)+1 and
                row['parent']==(open_calls[-1]['invocation'] if open_calls else 0),
                'Broken invocation parent or depth')
            open_calls.append(row)
        else:
            _require(bool(open_calls),'Dispatch event lacks an entered scope')
            _require(all(row[name]==open_calls[-1][name] for name in
                ('invocation','parent','depth','operation')),'Dispatch scope nesting differs')
            if row['phase']==2:open_calls.pop();returns+=1
    exit_row=value['exit'];_keys(exit_row,_empty_exit())
    for name,number in exit_row.items():
        _number(number,2**64-1 if name in ('handleValue','creationTime') else
                (1 if name in ('observed','withinDeadline') else 0xffffffff))
    if exit_row['observed']:
        _require(identity is not None and exit_row['handleValue']>0 and exit_row['pid']==identity['ownerPid'] and
            exit_row['creationTime']==identity['ownerCreated'],'Process exit generation differs')
        _require(exit_row['waitResult'] in (0,258),'Unverified retained process wait')
    else:_require(exit_row==_empty_exit(),'Unobserved process proof has data')
    exit_proved=int(bool(exit_row['observed'] and exit_row['withinDeadline'] and
                          exit_row['waitResult']==0 and exit_row['exitCode']!=259))
    cleanup=value['cleanup'];_keys(cleanup,_empty_cleanup())
    for name,number in cleanup.items():
        if name=='errors':
            _require(type(number) is list and len(number)<=16,'Unbounded cleanup errors')
            for error in number:_number(error,8,1)
        else:_number(number,1)
    _require(not cleanup['remoteViewRetired'] or exit_proved,'Local unmap cannot retire target view')
    _require(not cleanup['remoteQuiescenceProved'] or exit_proved,'Remote lifetime is not proved')
    _require(not cleanup['scopesObservedIdle'] or (capture['stable'] and not status['active'] and
        not status['enabled']),'Scope idle sample is unavailable')
    if cleanup['controllerResourcesReleased']:
        _require(cleanup['viewReleased'] and cleanup['mappingReleased'] and cleanup['engineHandleReleased'],
                 'Controller resources remain owned')
        _require(cleanup['libraryReleased'],'Controller IPC library remains owned')
    clean=not any(status[name] for name in ('enabled','rejected','overflow','expired','cleanupErrors'))
    trace_valid=int(bool(clean and capture['stable'] and capture['withinDeadline'] and not capture['partialSequence'] and
        not value['snapshotError'] and status['nextInvocation']==next_invocation))
    complete=int(bool(trace_valid and roots==1 and not open_calls and not any(stack) and
                      not status['active'] and not status['depth']))
    analysis=dict(traceValid=trace_valid,complete=complete,entered=next_invocation,returned=returns,
                  openInvocations=len(open_calls),processExitProved=exit_proved)
    if value['analysis'] is not None:
        _keys(value['analysis'],analysis)
        for number in value['analysis'].values():_number(number)
        _require(value['analysis']==analysis,'Diagnostic conclusion differs from numeric evidence')
    # JSON round-tripping is unnecessary: all admitted leaves are exact primitives.
    return dict(value,identity=dict(identity) if identity else None,
        state=dict(status) if value['state'] is not None else None,stack=list(stack),
        events=[dict(row) for row in rows],capture=dict(capture),exit=dict(exit_row),
        cleanup=dict(cleanup,errors=list(cleanup['errors'])),analysis=analysis)


class WindowsApi:
    """Windows bindings only; construction is deferred for injected portable tests."""
    def __init__(self, library):
        from ascii_message_preparation import require_prepared_library
        library_path=require_prepared_library(library)
        self.kernel=C.WinDLL('kernel32',use_last_error=True)
        self.user=C.WinDLL('user32',use_last_error=True)
        self.library=C.WinDLL(str(library_path),use_last_error=True)
        H,B=C.c_void_p,C.c_int32
        signatures=(
            (self.kernel,'GetCurrentProcessId',(),U32),(self.kernel,'GetCurrentProcess',(),H),
            (self.kernel,'GetProcessId',(H,),U32),
            (self.kernel,'GetProcessTimes',(H,C.POINTER(U64),C.POINTER(U64),C.POINTER(U64),C.POINTER(U64)),B),
            (self.kernel,'GetExitCodeProcess',(H,C.POINTER(U32)),B),
            (self.kernel,'WaitForSingleObject',(H,U32),U32),
            (self.kernel,'DuplicateHandle',(H,H,H,C.POINTER(H),U32,B,U32),B),
            (self.kernel,'CreateFileMappingW',(H,H,U32,U32,U32,C.c_wchar_p),H),
            (self.kernel,'MapViewOfFile',(H,U32,U32,U32,C.c_size_t),H),
            (self.kernel,'UnmapViewOfFile',(H,),B),(self.kernel,'CloseHandle',(H,),B),
            (self.kernel,'FreeLibrary',(H,),B),
            (self.kernel,'QueryPerformanceCounter',(C.POINTER(I64),),B),
            (self.kernel,'QueryPerformanceFrequency',(C.POINTER(I64),),B),
            (self.user,'IsWindow',(H,),B),(self.user,'GetWindowThreadProcessId',(H,C.POINTER(U32)),U32))
        for dll,name,args,result in signatures:
            function=getattr(dll,name);function.argtypes=args;function.restype=result
        if self.library is not None:
            for name,args,result in (('ReadWord',(C.POINTER(U32),),U32),
                ('ReadQuad',(C.POINTER(U64),),U64),('PublishWord',(C.POINTER(U32),U32),None)):
                function=getattr(self.library,name);function.argtypes=args;function.restype=result

    def _created(self,handle):
        created,exited,kernel,user=U64(),U64(),U64(),U64()
        if not self.kernel.GetProcessTimes(handle,C.byref(created),C.byref(exited),C.byref(kernel),C.byref(user)):
            raise C.WinError(C.get_last_error())
        return created.value

    def controller_identity(self):
        return int(self.kernel.GetCurrentProcessId()),self._created(self.kernel.GetCurrentProcess())

    def abi_layout(self):
        if self.library is None:raise ValueError('Prepared diagnostic IPC library is required')
        _require((C.sizeof(Identity),C.sizeof(Event),C.sizeof(State))==(88,40,5280),
                 'Win64 diagnostic ctypes packing differs')
        # The focused C++ test compares every offset to authenticated wire.h.
        # The generic Interlocked library deliberately owns no duplicate schema.
        return abi_layout()

    def qpc(self):
        counter,frequency=I64(),I64()
        if not self.kernel.QueryPerformanceCounter(C.byref(counter)) or not self.kernel.QueryPerformanceFrequency(C.byref(frequency)):
            raise C.WinError(C.get_last_error())
        return counter.value,frequency.value

    def process_snapshot(self,handle):
        pid=int(self.kernel.GetProcessId(handle))
        if not pid:raise C.WinError(C.get_last_error())
        created=self._created(handle)
        waited=int(self.kernel.WaitForSingleObject(handle,0))
        if waited not in (0,258):raise C.WinError(C.get_last_error())
        code=U32()
        if not self.kernel.GetExitCodeProcess(handle,C.byref(code)):
            raise C.WinError(C.get_last_error())
        return dict(pid=pid,creationTime=created,waitResult=waited,exitCode=code.value)

    def window_binding(self,hwnd):
        pid=U32()
        if not self.user.IsWindow(hwnd):raise ValueError('Original engine HWND no longer exists')
        tid=int(self.user.GetWindowThreadProcessId(hwnd,C.byref(pid)))
        return pid.value,tid

    def duplicate_handle(self,handle):
        process=self.kernel.GetCurrentProcess();duplicate=C.c_void_p()
        if not self.kernel.DuplicateHandle(process,handle,process,C.byref(duplicate),0,False,2):
            raise C.WinError(C.get_last_error())
        return int(duplicate.value)

    def create_mapping(self,name,size):
        C.set_last_error(0)
        handle=self.kernel.CreateFileMappingW(C.c_void_p(-1),None,4,0,size,name)
        error=C.get_last_error()
        if not handle:raise C.WinError(error)
        return int(handle),error==183

    def map_view(self,handle,size):
        view=self.kernel.MapViewOfFile(handle,0x000f001f,0,0,size)
        if not view:raise C.WinError(C.get_last_error())
        return int(view)

    def read_word(self,address):return int(self.library.ReadWord(C.cast(address,C.POINTER(U32))))
    def read_quad(self,address):return int(self.library.ReadQuad(C.cast(address,C.POINTER(U64))))
    def publish_word(self,address,value):self.library.PublishWord(C.cast(address,C.POINTER(U32)),value)
    def unmap_view(self,view):return bool(self.kernel.UnmapViewOfFile(view))
    def close_handle(self,handle):return bool(self.kernel.CloseHandle(handle))
    def close_library(self):
        if self.library is None:return True
        result=bool(self.kernel.FreeLibrary(self.library._handle))
        if result:self.library=None
        return result
    def pause(self,seconds):time.sleep(seconds)


class DiagnosticTransport:
    """Prepare env before launch, arm once, observe within D-5, close within D."""
    def __init__(self, *, library=None, api=None, clock=time.monotonic, nonce=None):
        self.api=api if api is not None else WindowsApi(library)
        self.clock=clock;self.nonce=nonce if nonce is not None else secrets.randbits(64) or 1
        self.last_clock=None;self._now()
        _number(self.nonce,2**64-1,1)
        self.controller_pid,self.controller_created=self.api.controller_identity()
        _number(self.controller_pid,0xffffffff,1);_number(self.controller_created,2**64-1,1)
        self.mapping=self.view=self.engine_handle=None
        self.identity=None;self.closed=False;self.receipt=None;self.deadline=None
        self.observation_deadline=None

    def child_environment(self,base):
        _require(isinstance(base, Mapping),'Child environment must be a mapping')
        _require(self.identity is None and not self.closed,'Diagnostic launch already admitted')
        return dict(base,**{ENVIRONMENT:str(self.controller_pid)+':'+str(self.nonce)})

    def _remaining(self,reserve=0):
        remaining=self.deadline-self._now()-reserve
        _require(remaining>0,'Original diagnostic deadline expired')
        return remaining

    def _now(self):
        now=self.clock()
        _require(type(now) in (int,float) and math.isfinite(now) and
            (self.last_clock is None or now>=self.last_clock),'Original monotonic clock changed')
        self.last_clock=now
        return now

    def _owner_snapshot(self):
        row=self.api.process_snapshot(self.engine_handle)
        _keys(row,('pid','creationTime','waitResult','exitCode'))
        for name,number in row.items():_number(number,2**64-1 if name=='creationTime' else 0xffffffff)
        _require(row['pid']==self.identity['ownerPid'] and row['creationTime']==self.identity['ownerCreated'],
                 'Original retained process generation changed')
        return row

    def arm(self,owner,deadline,started_at,engine_handle=None):
        _require(not self.closed and self.identity is None and self.engine_handle is None,'Diagnostic may arm once')
        _keys(owner,('pid','creationTime','tid','hwnd','handleValue'))
        for name,number in owner.items():_number(number,0xffffffff if name in ('pid','tid') else 2**64-1,1)
        _require(all(type(number) in (int,float) and math.isfinite(number) for number in (deadline,started_at)),
                 'Invalid original monotonic budget')
        now=self._now()
        _require(started_at<=now<deadline-5 and 0<deadline-started_at<=30,'Original save budget must include cleanup reserve')
        self.deadline=deadline;self.observation_deadline=deadline-5
        _require(tuple(self.api.abi_layout())==abi_layout(),'Compiled native diagnostic ABI differs')
        self._remaining(5)
        original=owner['handleValue'] if engine_handle is None else engine_handle
        _number(original,2**64-1,1)
        _require(original==owner['handleValue'],'Retained original engine HANDLE differs')
        source=self.api.process_snapshot(original)
        _require(source==dict(pid=owner['pid'],creationTime=owner['creationTime'],waitResult=258,exitCode=259),
                 'Retained original engine is not the admitted live generation')
        _require(self.api.window_binding(owner['hwnd'])==(owner['pid'],owner['tid']),'Original HWND/TID generation changed')
        self._remaining(5)
        self.engine_handle=self.api.duplicate_handle(original)
        try:
            before=self._now();counter,frequency=self.api.qpc();after=self._now()
            _require(started_at<=before<=after<deadline-5,'Original deadline expired while arming')
            _number(counter,2**63-1);_number(frequency,(2**63-1)//30,1)
            identity=dict(magic=MAGIC,version=VERSION,bytes=C.sizeof(State),controllerPid=self.controller_pid,
                ownerPid=owner['pid'],ownerTid=owner['tid'],reserved0=0,reserved1=0,nonce=self.nonce,
                controllerCreated=self.controller_created,ownerCreated=owner['creationTime'],ownerHwnd=owner['hwnd'],
                startQpc=counter-int((before-started_at)*frequency),
                deadlineQpc=counter+int((deadline-after)*frequency)-1,qpcFrequency=frequency)
            _identity(identity);self.identity=identity
            _require(self._owner_snapshot()['waitResult']==258,'Original retained engine exited during admission')
            name='Local\\OpenGeulCalcDispatch-'+str(self.controller_pid)+'-'+str(self.nonce)
            self.mapping,already_exists=self.api.create_mapping(name,C.sizeof(State))
            _require(not already_exists,'Diagnostic mapping already exists')
            self.view=self.api.map_view(self.mapping,C.sizeof(State))
            C.memset(self.view,0,C.sizeof(State))
            initial=Identity(**identity)
            C.memmove(self.view,C.byref(initial),C.sizeof(initial))
            self._remaining(5)
            self.api.publish_word(self.view+State.enabled.offset,1)
            return dict(identity)
        except BaseException:
            self.close()
            raise

    def disable(self):
        if self.view is not None:self.api.publish_word(self.view+State.enabled.offset,0)

    def _read_identity(self):
        result={}
        for name,kind in Identity._fields_:
            address=self.view+getattr(Identity,name).offset
            result[name]=(self.api.read_word(address) if kind is U32 else self.api.read_quad(address))
        return result

    def _read_status(self):
        return {name:self.api.read_word(self.view+getattr(State,name).offset)
                for name,kind in State._fields_ if kind is U32}

    def snapshot(self):
        _require(self.view is not None and not self.closed,'Diagnostic mapping is not armed')
        started=self._now()
        self.disable()
        identity=self._read_identity();_require(identity==self.identity,'Immutable diagnostic identity changed')
        status=self._read_status();_require(status['count']<=CAPACITY,'Native event capacity exceeded')
        stack=[self.api.read_word(self.view+State.stack.offset+4*index) for index in range(MAX_DEPTH)]
        rows=[]
        for index in range(status['count']):
            address=self.view+State.events.offset+index*C.sizeof(Event)
            sequence=self.api.read_word(address)
            if not sequence:break
            _require(sequence==index+1,'Unexpected native event publication')
            copy=Event.from_buffer_copy(C.string_at(address,C.sizeof(Event)))
            _require(self.api.read_word(address)==sequence==copy.sequence,'Native event publication changed')
            rows.append({name:int(getattr(copy,name)) for name,_ in Event._fields_})
        stable=int(self._read_status()==status and self._read_identity()==identity and
                   [self.api.read_word(self.view+State.stack.offset+4*i) for i in range(MAX_DEPTH)]==stack)
        result=dict(schemaVersion=1,kind=KIND,acceptanceEligible=False,fullEngineQualified=False,
            identity=identity,state=status,stack=stack,events=rows,
            capture=dict(stable=stable,partialSequence=len(rows)+1 if len(rows)<status['count'] else 0,
                         withinDeadline=int(started<=self._now()<self.deadline)),
            exit=_empty_exit(),cleanup=_empty_cleanup(),snapshotError=0,analysis=None)
        return decode_artifact(result,self.identity)

    def close(self,dispose=None):
        """Dispose independently; never grant a new allowance or infer view retirement.

        Cleanup error codes: 1 unmap, 2 mapping handle, 3 duplicate handle,
        4 disable, 5 deadline, 6 disposal, 7 retained process observation,
        8 snapshot/native state or IPC library. The original handle is never closed.
        """
        if self.closed:return self.receipt
        cleanup=_empty_cleanup();exit_row=_empty_exit();result=None
        try:
            try:self.disable()
            except BaseException:cleanup['errors'].append(4)
            if self.view is not None:
                try:result=self.snapshot()
                except BaseException:cleanup['errors'].append(8)
            if self.engine_handle is not None and self.identity is not None:
                def observe():
                    before=self._now();row=self._owner_snapshot();after=self._now()
                    return dict(row,observed=1,handleValue=self.engine_handle,
                                withinDeadline=int(before<=after<self.deadline))
                already_signaled=False
                try:
                    exit_row=observe()
                    already_signaled=exit_row['waitResult']==0
                except BaseException:cleanup['errors'].append(7)
                if not already_signaled and dispose is not None:
                    try:
                        self._remaining()
                    except ValueError:cleanup['errors'].append(5)
                    else:
                        try:dispose(self.deadline)
                        except BaseException:cleanup['errors'].append(6)
                    try:
                        while self._now()<self.deadline:
                            exit_row=observe()
                            if exit_row['waitResult']==0:break
                            self.api.pause(min(.01,max(0,self.deadline-self._now())))
                    except BaseException:cleanup['errors'].append(7)
                if exit_row['observed'] and exit_row['waitResult']==0 and exit_row['exitCode']!=259 and exit_row['withinDeadline']:
                    cleanup['remoteQuiescenceProved']=cleanup['remoteViewRetired']=1
            if result is not None:
                cleanup['scopesObservedIdle']=int(result['capture']['stable'] and
                    not result['state']['active'] and not result['state']['enabled'])
        finally:
            for resource,code,release,key in ((self.view,1,self.api.unmap_view,'viewReleased'),
                (self.mapping,2,self.api.close_handle,'mappingReleased'),
                (self.engine_handle,3,self.api.close_handle,'engineHandleReleased')):
                try:
                    cleanup[key]=int(resource is None or bool(release(resource)))
                    if not cleanup[key]:cleanup['errors'].append(code)
                except BaseException:cleanup['errors'].append(code)
            try:
                cleanup['libraryReleased']=int(bool(getattr(self.api,'close_library',lambda:True)()))
                if not cleanup['libraryReleased']:cleanup['errors'].append(8)
            except BaseException:cleanup['errors'].append(8)
            cleanup['controllerResourcesReleased']=int(all(cleanup[key] for key in
                ('viewReleased','mappingReleased','engineHandleReleased','libraryReleased')))
            try:cleanup['deadlineExpired']=int(self.deadline is not None and self._now()>=self.deadline)
            except ValueError:cleanup['deadlineExpired']=1;cleanup['errors'].append(5)
            self.closed=True
        if result is None:
            # No rows are invented after a failed capture. Keep independent exit
            # and release receipts accessible even when the wire is malformed.
            result=dict(schemaVersion=1,kind=KIND,acceptanceEligible=False,fullEngineQualified=False,
                        identity=dict(self.identity) if self.identity else None,state=None,stack=[],events=[],
                        capture=dict(stable=0,partialSequence=0,withinDeadline=0),snapshotError=1,
                        exit=exit_row,cleanup=cleanup,analysis=None)
        else:
            result.update(exit=exit_row,cleanup=cleanup,analysis=None)
        result=decode_artifact(result,self.identity)
        self.receipt=result
        return result
