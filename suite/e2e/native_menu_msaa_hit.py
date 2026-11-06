"""Isolated provider-local menu hit proof; never authorizes or sends input.

The global UIA Pane/hit mismatch remains separate evidence. Native launch stays
disabled until the controller's unresolved-callback finalization fence is wired.
All SDK slots are derived from the caller's existing generated COM metadata.
"""
import ctypes as C
import _thread
from dataclasses import dataclass
import math
import os
import time
import uuid


_IIDS = dict(client='30cbe57d-d9d0-452a-ab13-7ac5ac4825ee',
    element='d22108aa-8ac5-49a5-837b-37bbb3d7591e',
    legacy='828055ad-355b-4435-86d5-3b51c14a9b1b',
    accessible='618736e0-3c3d-11cf-810c-00aa00389b71',
    unknown='00000000-0000-0000-c000-000000000046',
    dispatch='00020400-0000-0000-c000-000000000046')


def _iid(interface, expected):
    try:
        value=interface._iid_
        return (C.sizeof(value)==16 and C.string_at(C.addressof(value),16)
                ==uuid.UUID(_IIDS.get(expected,expected)).bytes_le)
    except (AttributeError,TypeError,ValueError):
        return False


def _scalar(kind, size, signed):
    try:return (kind._type_ in 'bBhHiIlLqQnN' and C.sizeof(kind)==size
        and type(kind(-1).value) is int and (kind(-1).value==-1)==signed)
    except (TypeError,AttributeError):return False


def _pointer(kind, predicate):
    return isinstance(kind,type) and issubclass(kind,C._Pointer) and predicate(kind._type_)


def _com(kind, iid):
    try:return issubclass(kind,C.c_void_p) and _iid(kind.__com_interface__,iid)
    except (TypeError,AttributeError):return False


def _methods(interface):
    result=[]
    for base in reversed(interface.__mro__):
        result.extend(vars(base).get('_methods_',()))
    names=[item.name for item in result]
    if len(names)!=len(set(names)):raise ValueError('Duplicate COM method metadata')
    if names[:3]!=['QueryInterface','AddRef','Release']:
        raise ValueError('IUnknown prefix required')
    return result


class SdkAbi:
    """Validate used signatures before binding any function pointer.

    comtypes COM pointers are c_void_p subclasses with __com_interface__; their
    outer [out] pointer is an ordinary ctypes pointer. Method arguments exclude
    implicit this. IUnknown STDMETHOD metadata legitimately uses lists/None.
    """
    def __init__(self, *, client_interface, element_interface, legacy_interface,
            accessible_interface, guid_type, hresult_type, variant_type,
            function_factory):
        interfaces=dict(client=client_interface,element=element_interface,
            legacy=legacy_interface,accessible=accessible_interface)
        if (C.sizeof(C.c_void_p)!=8 or C.sizeof(guid_type)!=16
                or not _scalar(hresult_type,4,True)
                or any(not _iid(value,key) for key,value in interfaces.items())):
            raise ValueError('Unsupported COM interface ABI')
        try:
            class RawVariant(C.Structure):
                _anonymous_=tuple(variant_type._anonymous_)
                _fields_=list(variant_type._fields_)
            value=RawVariant()
            if (C.sizeof(value)!=24 or RawVariant.vt.offset!=0 or RawVariant._.offset!=8
                    or type(value._).VT_I4.size!=4 or type(value._).c_void_p.size!=8):
                raise ValueError('Unsupported native VARIANT ABI')
        except (AttributeError,TypeError):
            raise ValueError('Unsupported native VARIANT ABI') from None
        self.Variant=RawVariant;self.Guid=guid_type;self.Hresult=hresult_type
        self.function_factory=function_factory;self.slots={};self.signatures={}
        scalar=lambda kind:_scalar(kind,4,True)
        guid=lambda kind:kind is guid_type
        void=lambda kind:kind is C.c_void_p
        variant=lambda kind:kind is variant_type
        com=lambda name:lambda kind:_com(kind,name)
        out=lambda test:lambda kind:_pointer(kind,test)
        self._use('query',element_interface,'QueryInterface',
            (out(guid),out(void)),None)
        self._use('release',element_interface,'Release',(),None,unsigned=True)
        self._use('pattern',element_interface,'GetCurrentPatternAs',
            (scalar,out(guid),out(void)),(1,1,10))
        self._use('child_id',legacy_interface,'_get_CurrentChildId',(out(scalar),),(10,))
        self._use('accessible',legacy_interface,'GetIAccessible',(out(com('accessible')),),(10,))
        self._use('from_accessible',client_interface,'ElementFromIAccessible',
            (com('accessible'),scalar,out(com('element'))),(1,1,10))
        self._use('compare',client_interface,'CompareElements',
            (com('element'),com('element'),out(scalar)),(1,1,10))
        self._use('hit_test',accessible_interface,'accHitTest',
            (scalar,scalar,out(variant)),(1,1,10))
        # The IDispatch prefix is independently checked; only accHitTest is used.
        accessible_methods=_methods(accessible_interface)
        if ([item.name for item in accessible_methods[:7]]!=[
                'QueryInterface','AddRef','Release','GetTypeInfoCount','GetTypeInfo',
                'GetIDsOfNames','Invoke'] or not any(_iid(base,'dispatch')
                    for base in accessible_interface.__mro__)
                or any(not any(_iid(base,'unknown') for base in value.__mro__)
                    for value in interfaces.values())):
            raise ValueError('COM base interface differs')

    def _use(self,key,interface,name,arguments,flags,unsigned=False):
        methods=_methods(interface)
        matches=[(index,item) for index,item in enumerate(methods) if item.name==name]
        if len(matches)!=1:raise ValueError('Required COM method missing')
        slot,item=matches[0];args=tuple(item.argtypes)
        actual_flags=None if item.paramflags is None else tuple(part[0] for part in item.paramflags)
        if (not _scalar(item.restype,4,not unsigned) or len(args)!=len(arguments)
                or any(not test(kind) for test,kind in zip(arguments,args))
                or actual_flags!=flags
                or key=='child_id' and 'propget' not in item.idlflags):
            raise ValueError('COM method ABI differs')
        self.slots[key]=slot
        # ctypes.HRESULT carries a checker which raises before returning the
        # numeric failed HRESULT. Only the plain ABI type belongs in raw calls.
        self.signatures[key]=(C.c_uint32 if unsigned else C.c_int32,args)

    def call(self,key,pointer,*arguments):
        """Worker-only raw call. Newly returned refs have no Python destructor."""
        value=C.cast(pointer,C.c_void_p).value
        if not value:raise ValueError('Null COM input')
        table=C.cast(C.c_void_p(value),C.POINTER(C.POINTER(C.c_void_p))).contents
        restype,args=self.signatures[key]
        # Canonical opaque pointers preserve the validated SDK ABI while avoiding
        # comtypes [out] conversions, implicit QI and auto-Releasing wrappers.
        raw_args=tuple(C.c_void_p if issubclass(kind,C._Pointer) or _is_com(kind)
            else C.c_int32 for kind in args)
        function=self.function_factory(restype,C.c_void_p,*raw_args)(table[self.slots[key]])
        return function(C.c_void_p(value),*arguments)

    def matches_source(self,source):
        """Check borrowed pointer types without COM calls or new references."""
        def matches(value,expected):
            try:
                kind=type(value)
                interface=kind.__com_interface__
                return (issubclass(kind,C.c_void_p)
                    and any(_iid(base,expected) for base in interface.__mro__)
                    and bool(C.cast(value,C.c_void_p).value))
            except (AttributeError,TypeError,ValueError):return False
        return (isinstance(source,MsaaHitSource) and matches(source.client,'client')
            and all(matches(value,'element') for value in
                (source.file,source.fresh_target,source.retained_target,*source.negative_refs)))


def _is_com(kind):
    return isinstance(kind,type) and issubclass(kind,C.c_void_p)


_OPERATIONS=('pattern','child_id','accessible','from_accessible','hit_test','query','compare')


def worker_record():
    result=dict(localKnown=0,localMatch=0,workerCleanup=0,workerStage=0,workerMta=0,
        comInitialized=0,comUninitialized=0,dpiEntered=0,dpiRestored=0,physicalDpiVerified=0,
        processBefore=0,processAfter=0,referencesAcquired=0,referencesReleased=0,
        variantAttempted=0,variantCleared=0,variantCleanupHresult=0,
        variantType=0,childIdZero=0,fileRoundTrip=0,targetFreshPositive=0,
        targetRetainedPositive=0,negativeCount=0,negativeRejected=0,cleanupError=0)
    for name in _OPERATIONS:
        result.update({name+'Attempted':0,name+'Completed':0,name+'Hresult':0})
    return result


class _Stop(Exception):pass


def run_local_hit(source,scope,sdk,platform):
    """Worker-only typed COM calls, explicit new-ref and VARIANT cleanup.

    Never accesses names, values, document text or VARIANT conversion properties.
    Raw output ownership is registered even if a failed HRESULT accompanies a
    non-null pointer. Borrowed original client/element refs are never Released.
    """
    record=worker_record();refs=[];variant=None;token=0;initialized=False;matched=False
    def call(key,pointer,*arguments):
        record[key+'Attempted']+=1
        hr=sdk.call(key,pointer,*arguments)
        if type(hr) is not int:raise _Stop()
        record[key+'Completed']+=1;record[key+'Hresult']=hr&0xffffffff
        if hr!=0:raise _Stop()
    def out(key,pointer,*arguments):
        value=C.c_void_p()
        try:call(key,pointer,*arguments,C.byref(value))
        finally:
            if value.value:
                refs.append(value.value);record['referencesAcquired']+=1
        if not value.value:raise _Stop()
        return value.value
    def same(first,second):
        equal=C.c_int32()
        call('compare',source.client,first,second,C.byref(equal))
        if equal.value not in (0,1):raise _Stop()
        return equal.value==1
    try:
        record['workerStage']=1
        hr=platform.initialize()
        if hr not in (0,1):raise _Stop()
        initialized=True;record['comInitialized']=1
        if not platform.apartment():raise _Stop()
        record['workerMta']=1;record['workerStage']=2
        token=platform.enter_dpi()
        if not token:raise _Stop()
        record['dpiEntered']=1
        if not platform.physical_dpi():raise _Stop()
        record['physicalDpiVerified']=1
        if not platform.guard():raise _Stop()
        # This lease checks process identity/liveness only. Original attachment,
        # popup exposure and UIA target guards remain the controller's separate
        # mandatory before/after observation; no success here substitutes them.
        record['processBefore']=1;record['workerStage']=3
        pattern_iid=sdk.Guid('{'+_IIDS['legacy']+'}')
        legacy=out('pattern',source.file,10018,C.byref(pattern_iid))
        child=C.c_int32(-1);call('child_id',legacy,C.byref(child))
        if child.value!=0:raise _Stop()
        record['childIdZero']=1;record['workerStage']=4
        accessible=out('accessible',legacy)
        file_round_trip=out('from_accessible',source.client,accessible,0)
        if not same(file_round_trip,source.file):raise _Stop()
        record['fileRoundTrip']=1;record['workerStage']=5
        variant=sdk.Variant();record['variantAttempted']=1
        call('hit_test',accessible,scope.x,scope.y,C.byref(variant))
        record['variantType']=int(variant.vt)
        if variant.vt!=9 or not variant._.c_void_p:raise _Stop()
        iid=sdk.Guid('{'+_IIDS['accessible']+'}')
        hit_accessible=out('query',C.c_void_p(variant._.c_void_p),C.byref(iid))
        hit=out('from_accessible',source.client,hit_accessible,0)
        record['workerStage']=6
        if not same(hit,source.fresh_target):raise _Stop()
        record['targetFreshPositive']=1
        if not same(hit,source.retained_target):raise _Stop()
        record['targetRetainedPositive']=1
        for negative in source.negative_refs:
            record['negativeCount']+=1
            if same(hit,negative):raise _Stop()
            record['negativeRejected']+=1
        if not platform.guard():raise _Stop()
        record['processAfter']=1;record['workerStage']=7;matched=True
    except _Stop:
        # Provider/COM failures remain unknown; no exception string crosses out.
        matched=False
    except BaseException:
        # An interrupted initialization/call can have unobserved side effects.
        # Even explicit best-effort cleanup cannot prove that boundary closed.
        matched=False;record['cleanupError']=1
    finally:
        if variant is not None:
            try:
                hr=platform.clear_variant(variant)
                record['variantCleanupHresult']=hr&0xffffffff
                record['variantCleared']=int(hr==0)
                if hr!=0:record['cleanupError']=1
            except BaseException:record['cleanupError']=1
            variant=None
        for pointer in reversed(refs):
            try:
                sdk.call('release',C.c_void_p(pointer));record['referencesReleased']+=1
            except BaseException:record['cleanupError']=1
        refs.clear()
        if token:
            try:record['dpiRestored']=int(bool(platform.leave_dpi(token)))
            except BaseException:record['cleanupError']=1
            if not record['dpiRestored']:record['cleanupError']=1
        if initialized:
            try:platform.uninitialize();record['comUninitialized']=1
            except BaseException:record['cleanupError']=1
        clean=(not record['cleanupError'] and record['referencesAcquired']==record['referencesReleased']
            and (not record['variantAttempted'] or record['variantCleared'])
            and (not initialized or record['comUninitialized'])
            and (not token or record['dpiRestored']))
        record['workerCleanup']=int(clean)
        if matched and clean:record.update(localKnown=1,localMatch=1,workerStage=8)
    return record


@dataclass(frozen=True)
class MsaaHitScope:
    scope_id:int
    engine_pid:int
    engine_birth:int
    shell_pid:int
    shell_birth:int
    parent_hwnd:int
    child_hwnd:int
    x:int
    y:int

    def valid(self):
        return (all(type(getattr(self,key)) is int and 0<getattr(self,key)<2**64
            for key in ('scope_id','engine_birth','shell_birth','parent_hwnd','child_hwnd'))
            and all(type(getattr(self,key)) is int and 0<getattr(self,key)<2**32
                for key in ('engine_pid','shell_pid'))
            and all(type(value) is int and -2**31<=value<2**31 for value in (self.x,self.y)))


@dataclass(frozen=True)
class MsaaHitSource:
    client:object
    file:object
    fresh_target:object
    retained_target:object
    negative_refs:tuple
    shell_handle:int
    engine_handle:int
    keepalive:tuple=()

    def valid(self):
        return (all(value is not None for value in
            (self.client,self.file,self.fresh_target,self.retained_target))
            and type(self.negative_refs) is tuple and 2<=len(self.negative_refs)<=16
            and type(self.keepalive) is tuple
            and all(value is not None for value in self.negative_refs)
            and all(type(value) is int and value>0
                for value in (self.shell_handle,self.engine_handle)))


# Unresolved foreign callbacks require the controller's separately reviewed
# fail-stop finalization fence. Do not enable as part of standalone helper work.
NATIVE_LAUNCH_ENABLED=False
_active=None
_pending_fence=None
_registry_lock=_thread.allocate_lock()


def _reserve(lease):
    global _active
    # No blocking acquisition and no foreign call while holding the lock.
    if not _registry_lock.acquire(False):return False
    try:
        if _active is not None:return False
        _active=lease
        return True
    finally:_registry_lock.release()


def configure_native_launch(*,pending_fence):
    """Controller-only opt-in after closed-record/explicit/atexit fence setup.

    Retains the controller's reviewed self-only fail-stop function. This helper
    never invokes it; the CLI owns failure serialization and finalization order.
    Per-call native_enabled still defaults False for all other UIA profiles.
    """
    global NATIVE_LAUNCH_ENABLED,_pending_fence
    if not callable(pending_fence) or (_pending_fence is not None and _pending_fence is not pending_fence):
        raise ValueError('One explicit controller fence required')
    _pending_fence=pending_fence;NATIVE_LAUNCH_ENABLED=True


def pending_msaa_hit():
    """A pending lease prohibits new scopes/input and provider teardown."""
    return _active


def _record(scope,synthetic):
    return dict(worker_record(),schemaVersion=1,diagnosticOnly=1,acceptanceEligible=0,
        providerLocalOnly=1,globalHitSubstituted=0,synthetic=int(synthetic),
        scopeId=scope.scope_id if isinstance(scope,MsaaHitScope) and scope.valid() else 0,
        stageCode=0,nativeAttempted=0,nativeExit=0,threadClosed=0,processesClosed=0,
        controllerPid=0,threadId=0,threadBirth=0,threadIdentity=0,
        callbackIdentity=0,exitCodeObserved=0,nativeExitCode=0,
        localKnown=0,localMatch=0,workerCleanup=0,workerException=0,pending=0)


def begin_msaa_hit(source,scope,sdk,deadline,*,native_enabled=False,_kernel=None):
    """One pending capsule, source-owned duplicate process HANDLEs, no input.

    The private kernel hook is synthetic-test-only. Production startup remains
    disabled until the controller's explicit opt-in finalization fence is ready.
    A local match is never an input/acceptance grant: the controller must also
    prove the original popup exposure, live scope and fresh target after return.
    """
    global _active
    lease=MsaaHitLease(source,scope,sdk,deadline,_kernel)
    synthetic=_kernel is not None and getattr(_kernel,'synthetic',False) is True
    if not synthetic and (native_enabled is not True or not NATIVE_LAUNCH_ENABLED):
        lease.record['stageCode']=1
        return lease
    if not _reserve(lease):
        lease.record['stageCode']=2
        return lease
    if not synthetic:
        try:
            _kernel=WindowsKernel()
            if (not isinstance(sdk,SdkAbi) or sdk.function_factory is not C.WINFUNCTYPE
                    or not sdk.matches_source(source)):
                raise ValueError('Native SDK binder required')
            lease.kernel=_kernel
        except BaseException:
            lease.record['stageCode']=3
            lease._clear()
            return lease
    if not lease.valid():
        lease.record['stageCode']=3
        lease._clear()
        return lease
    try:
        if not _kernel.apartment():
            lease.record['stageCode']=4;lease._release_unstarted();return lease
        lease.record['stageCode']=5
        for handle,pid,birth in ((source.shell_handle,scope.shell_pid,scope.shell_birth),
                (source.engine_handle,scope.engine_pid,scope.engine_birth)):
            duplicate=_kernel.duplicate(handle,pid,birth)
            lease.process_handles.append((duplicate,pid,birth))
            adopt=getattr(_kernel,'adopt_duplicate',None)
            if adopt is not None:adopt(duplicate)
            if not _kernel.check_process(duplicate,pid,birth):raise _Stop()
        if _kernel.clock()>=deadline:
            lease.record['stageCode']=11;lease._release_unstarted();return lease
        lease.record.update(stageCode=6,nativeAttempted=1)
        lease.thread,lease.tid,lease.birth=_kernel.start(lease._run)
        if not lease.thread or not lease.tid or not lease.birth:
            # A possibly started callback with no trustworthy HANDLE is retained.
            lease.record['pending']=1
    except BaseException:
        # A start implementation may report an unobservable partial launch. Such
        # kernels must retain that uncertainty instead of claiming no callback.
        if lease.record['nativeAttempted'] and getattr(_kernel,'start_uncertain',False):
            lease.record['pending']=1
        else:lease._release_unstarted()
    return lease


class MsaaHitLease:
    def __init__(self,source,scope,sdk,deadline,kernel):
        self.source=source;self.scope=scope;self.sdk=sdk;self.deadline=deadline;self.kernel=kernel
        self.record=_record(scope,getattr(kernel,'synthetic',False))
        self.process_handles=[];self.thread=0;self.tid=0;self.birth=0
        self.worker=None;self._late=False;self._retired=False;self._worker_exception=False
        self._cleanup_unknown=False
        self._unknown_handles=set();self._closed_handles=set();self._closing_handle=0
        self.runner=lambda:self.kernel.worker(self.source,self.scope,self.sdk)

    @property
    def pending(self):return _active is self

    def valid(self):
        return (isinstance(self.source,MsaaHitSource) and self.source.valid()
            and isinstance(self.scope,MsaaHitScope) and self.scope.valid()
            and type(self.deadline) in (int,float) and math.isfinite(self.deadline)
            and self.kernel.clock()<self.deadline<=self.kernel.clock()+5)

    def _run(self):
        # The callback normal-return boundary must encompass BaseException.
        try:
            result=self.runner()
            if (type(result) is dict and result.keys()==worker_record().keys()
                    and all(type(value) is int and 0<=value<=0xffffffff for value in result.values())):
                self.worker=dict(result)
            else:self._worker_exception=True
        except BaseException:self._worker_exception=True
        return 0

    def _release_unstarted(self):
        if getattr(self.kernel,'duplicate_unknown',False):self._cleanup_unknown=True
        if self._close_processes() and not self._cleanup_unknown:self._clear()
        else:self.record['pending']=1

    def _close_processes(self):
        kept=[]
        for handle,pid,birth in self.process_handles:
            if handle in self._closed_handles:continue
            if handle in self._unknown_handles:
                kept.append((handle,pid,birth));continue
            self._closing_handle=handle
            try:
                closed=self.kernel.close(handle)
                if closed:self._closed_handles.add(handle)
                else:kept.append((handle,pid,birth))
                self._closing_handle=0
            except BaseException:
                self._unknown_handles.add(handle);kept.append((handle,pid,birth))
                self._closing_handle=0
        self.process_handles=kept
        self.record['processesClosed']=int(not kept)
        return not kept

    def _clear(self):
        global _active
        if _active is self:_active=None
        self.record['pending']=0;self.source=None;self.sdk=None;self._retired=True

    def _collect(self,deadline,retiring):
        if not self.pending:return dict(self.record)
        if retiring or self.kernel.clock()>=self.deadline:self._late=True
        self.record['localKnown']=self.record['localMatch']=0
        if self._unknown_handles:
            self.record['stageCode']=10;return self._unknown()
        if not self.thread:
            self.record['pending']=1
            return dict(self.record)
        try:
            self.record.update(controllerPid=int(self.kernel.controller_pid),
                threadId=self.tid,threadBirth=self.birth)
            if not self.kernel.thread_identity(self.thread,self.tid,self.birth):
                self.record['stageCode']=7;return self._unknown()
            self.record['threadIdentity']=1
            remaining=max(0,deadline-self.kernel.clock())
            if not self.kernel.wait(self.thread,min(5000,int(remaining*1000))):
                self.record['stageCode']=8;return self._unknown()
            self.record['nativeExit']=1
            self.record['workerException']=int(self._worker_exception)
            worker=self.worker
            if worker:
                self.record.update(worker)
                self.record['localKnown']=self.record['localMatch']=0
            clean=bool(worker and worker['workerCleanup'])
            self.record['workerCleanup']=int(clean)
            self._cleanup_unknown=not clean
            code=self.kernel.exit(self.thread)
            self.record.update(exitCodeObserved=1,nativeExitCode=code&0xffffffff)
            self.record['callbackIdentity']=int(self.kernel.callback_identity(self.thread,self.tid,self.birth))
            exited=code==0 and self.record['callbackIdentity']==1
            owned=all(self.kernel.check_process(handle,pid,birth)
                for handle,pid,birth in self.process_handles)
            self._closing_handle=self.thread
            if not self.kernel.close(self.thread):
                self._closing_handle=0
                self.record['stageCode']=10;return self._unknown()
            self.thread=0;self.record['threadClosed']=1
            self._closing_handle=0
            if not self._close_processes():
                self.record['stageCode']=10;return self._unknown()
            if not clean:
                self._cleanup_unknown=True;self.record['stageCode']=10
                return self._unknown()
            if (not self._late and self.kernel.clock()<self.deadline and exited and owned
                    and clean and not self.record['workerException']):
                self.record.update(worker);self.record['stageCode']=13
            else:self.record['stageCode']=11 if self._late or self.kernel.clock()>=self.deadline else 9
            self._clear()
            if self.kernel.clock()>=self.deadline:
                self._late=True;self.record.update(localKnown=0,localMatch=0,stageCode=11)
        except BaseException:
            if self._closing_handle:self._unknown_handles.add(self._closing_handle)
            self.record['stageCode']=10
            return self._unknown()
        return dict(self.record)

    def _unknown(self):
        self._late=True;self.record['pending']=1
        self.record['localKnown']=self.record['localMatch']=0
        return dict(self.record)

    def wait(self):return self._collect(self.deadline,False)

    def retire(self,cleanup_deadline):
        """After owned-engine shutdown only; never accepts a late proof."""
        if type(cleanup_deadline) not in (int,float) or not math.isfinite(cleanup_deadline):
            raise ValueError('Finite cleanup deadline required')
        if self.pending and not self.thread and not self.record['nativeAttempted']:
            self._release_unstarted();return dict(self.record)
        if self.pending and self.record['nativeExit'] and not self.thread:
            if self._cleanup_unknown or self._unknown_handles:return self._unknown()
            if self._close_processes():self._clear()
            return dict(self.record)
        return self._collect(cleanup_deadline,True)


def run_native_boundary(platform):
    """No provider access: actual callback MTA/DPI lifetime witness only."""
    record=worker_record();initialized=False;token=0
    try:
        record['workerStage']=1
        if platform.initialize() not in (0,1):raise _Stop()
        initialized=True;record['comInitialized']=1
        if not platform.apartment():raise _Stop()
        record['workerMta']=1
        token=platform.enter_dpi()
        if not token:raise _Stop()
        record['dpiEntered']=1
        if not platform.physical_dpi():raise _Stop()
        record['physicalDpiVerified']=1
        record['workerStage']=8
    except _Stop:pass
    except BaseException:record['cleanupError']=1
    finally:
        if token:
            try:record['dpiRestored']=int(bool(platform.leave_dpi(token)))
            except BaseException:record['cleanupError']=1
            if not record['dpiRestored']:record['cleanupError']=1
        if initialized:
            try:platform.uninitialize();record['comUninitialized']=1
            except BaseException:record['cleanupError']=1
        record['workerCleanup']=int(not record['cleanupError']
            and (not token or record['dpiRestored'])
            and (not initialized or record['comUninitialized']))
    return record


def verify_native_thread_boundary(deadline,*,_kernel=None):
    """One opt-in, input-free startup proof under the CLI's installed fence."""
    global _active
    lease=MsaaHitLease(None,None,None,deadline,_kernel)
    lease.record.update(nativeBoundaryOnly=1,nativeBoundaryPassed=0)
    synthetic=_kernel is not None and getattr(_kernel,'synthetic',False) is True
    if not synthetic and not NATIVE_LAUNCH_ENABLED:
        lease.record['stageCode']=1;return dict(lease.record)
    if not _reserve(lease):
        lease.record['stageCode']=2;return dict(lease.record)
    try:
        kernel=_kernel if synthetic else WindowsKernel()
        lease.kernel=kernel;lease.runner=kernel.boundary_worker
        if (type(deadline) not in (float,int) or not math.isfinite(deadline)
                or not kernel.clock()<deadline<=kernel.clock()+5):
            lease.record['stageCode']=3;lease._clear();return dict(lease.record)
        if not kernel.apartment():
            lease.record['stageCode']=4;lease._release_unstarted();return dict(lease.record)
        lease.record.update(nativeAttempted=1,stageCode=6)
        lease.thread,lease.tid,lease.birth=kernel.start(lease._run)
    except BaseException:
        if lease.record['nativeAttempted'] and getattr(lease.kernel,'start_uncertain',False):
            return lease._unknown()
        lease._release_unstarted();return dict(lease.record)
    result=lease.wait()
    passed=(not lease.pending and result['stageCode']==13
        and kernel.clock()<deadline and result['workerStage']==8
        and result['nativeExit']==result['threadClosed']==result['workerCleanup']==1
        and result['workerMta']==result['dpiEntered']==result['dpiRestored']==1
        and result['physicalDpiVerified']==1
        and result['comInitialized']==result['comUninitialized']==1)
    result['nativeBoundaryPassed']=int(passed)
    lease.record['nativeBoundaryPassed']=int(passed)
    return result


class WindowsKernel:
    """Current-UCRT native thread and source-owned process HANDLE lease.

    Construction/startup is synchronous; late completion is never admitted.
    DLL/ctypes callback references remain owned through actual HANDLE exit.
    No Thread.start/join, pipe reader, thread termination, or borrowed close.
    """
    synthetic=False
    clock=staticmethod(time.monotonic)

    def __init__(self):
        if os.name!='nt' or C.sizeof(C.c_void_p)!=8:
            raise ValueError('Native 64-bit Windows required')
        self.kernel=C.WinDLL('kernel32',use_last_error=True)
        self.ole=C.WinDLL('ole32');self.user=C.WinDLL('user32')
        self.aut=C.WinDLL('oleaut32');self.processes={};self.thread_handle=0
        self.callback=None;self.worker_tid=0;self.worker_birth=0
        self.start_uncertain=False;self.duplicate_ok=True;self.callback_failed=False
        self.duplicate_unknown=False
        self._bind(self.kernel,'GetCurrentProcess',(),C.c_void_p)
        self._bind(self.kernel,'GetCurrentThread',(),C.c_void_p)
        self._bind(self.kernel,'GetCurrentProcessId',(),C.c_uint32)
        self._bind(self.kernel,'GetCurrentThreadId',(),C.c_uint32)
        self._bind(self.kernel,'GetThreadId',(C.c_void_p,),C.c_uint32)
        self._bind(self.kernel,'GetProcessIdOfThread',(C.c_void_p,),C.c_uint32)
        self._bind(self.kernel,'GetProcessId',(C.c_void_p,),C.c_uint32)
        self._bind(self.kernel,'GetModuleHandleW',(C.c_wchar_p,),C.c_void_p)
        self._bind(self.kernel,'CloseHandle',(C.c_void_p,),C.c_int32)
        self._bind(self.kernel,'DuplicateHandle',(C.c_void_p,C.c_void_p,C.c_void_p,
            C.POINTER(C.c_void_p),C.c_uint32,C.c_int32,C.c_uint32),C.c_int32)
        self._bind(self.kernel,'WaitForSingleObject',(C.c_void_p,C.c_uint32),C.c_uint32)
        self._bind(self.kernel,'GetExitCodeThread',(C.c_void_p,C.POINTER(C.c_uint32)),C.c_int32)
        for name in ('GetThreadTimes','GetProcessTimes'):
            self._bind(self.kernel,name,(C.c_void_p,*(C.POINTER(C.c_uint64),)*4),C.c_int32)
        self._bind(self.ole,'CoGetApartmentType',(C.POINTER(C.c_int32),C.POINTER(C.c_int32)),C.c_int32)
        self._bind(self.ole,'CoInitializeEx',(C.c_void_p,C.c_uint32),C.c_int32)
        self._bind(self.ole,'CoUninitialize',(),None)
        self._bind(self.user,'SetThreadDpiAwarenessContext',(C.c_void_p,),C.c_void_p)
        self._bind(self.user,'GetThreadDpiAwarenessContext',(),C.c_void_p)
        self._bind(self.user,'AreDpiAwarenessContextsEqual',(C.c_void_p,C.c_void_p),C.c_int32)
        module=self.kernel.GetModuleHandleW('ucrtbase.dll')
        if not module:raise ValueError('Loaded UCRT required')
        self.crt=C.CDLL('ucrtbase.dll',handle=module)
        self.ThreadProc=C.WINFUNCTYPE(C.c_uint32,C.c_void_p)
        self._bind(self.crt,'_beginthreadex',(C.c_void_p,C.c_uint32,self.ThreadProc,
            C.c_void_p,C.c_uint32,C.POINTER(C.c_uint32)),C.c_size_t)
        self.controller_pid=int(self.kernel.GetCurrentProcessId())

    @staticmethod
    def _bind(library,name,args,result):
        function=getattr(library,name);function.argtypes=args;function.restype=result

    def apartment(self):
        kind=C.c_int32(-1);qualifier=C.c_int32(-1)
        return self.ole.CoGetApartmentType(C.byref(kind),C.byref(qualifier))==0 and kind.value==1

    def _birth(self,handle,thread):
        values=[C.c_uint64() for _ in range(4)]
        function=self.kernel.GetThreadTimes if thread else self.kernel.GetProcessTimes
        if not function(handle,*(C.byref(value) for value in values)):return 0
        return values[0].value

    def duplicate(self,handle,pid,birth):
        out=C.c_void_p();current=self.kernel.GetCurrentProcess()
        self.duplicate_unknown=True
        self.duplicate_ok=bool(self.kernel.DuplicateHandle(current,handle,current,
            C.byref(out),0,False,2))  # DUPLICATE_SAME_ACCESS: no new access rights.
        if not out.value:
            if not self.duplicate_ok:self.duplicate_unknown=False
            raise _Stop()
        self.processes[out.value]=(pid,birth)
        return out.value

    def adopt_duplicate(self,handle):
        if handle not in self.processes:raise _Stop()
        # The lease has now registered cleanup ownership, including exceptions
        # after this return. Before acknowledgement retain uncertain ownership.
        self.duplicate_unknown=False

    def check_process(self,handle,pid,birth):
        return (self.duplicate_ok and self.processes.get(handle)==(pid,birth)
            and self.kernel.GetProcessId(handle)==pid and self._birth(handle,False)==birth
            and self.kernel.WaitForSingleObject(handle,0)==258)

    def start(self,callback):
        def entry(_unused):
            try:
                self.worker_tid=int(self.kernel.GetCurrentThreadId())
                self.worker_birth=self._birth(self.kernel.GetCurrentThread(),True)
                callback()
                return 0
            except BaseException:
                self.callback_failed=True
                return 1
        self.callback=self.ThreadProc(entry)
        tid=C.c_uint32();self.start_uncertain=True
        handle=self.crt._beginthreadex(None,0,self.callback,None,0,C.byref(tid))
        if not handle:
            self.start_uncertain=False
            raise _Stop()
        self.thread_handle=int(handle)
        return self.thread_handle,tid.value,self._birth(self.thread_handle,True)

    def thread_identity(self,handle,tid,birth):
        return (handle==self.thread_handle and tid>0 and birth>0
            and self.kernel.GetThreadId(handle)==tid
            and self.kernel.GetProcessIdOfThread(handle)==self.controller_pid
            and self._birth(handle,True)==birth)

    def wait(self,handle,milliseconds):
        if type(milliseconds) is not int or not 0<=milliseconds<=5000:raise _Stop()
        return self.kernel.WaitForSingleObject(handle,milliseconds)==0

    def exit(self,handle):
        code=C.c_uint32()
        if not self.kernel.GetExitCodeThread(handle,C.byref(code)):raise _Stop()
        return code.value

    def callback_identity(self,handle,tid,birth):
        return (not self.callback_failed and self.worker_tid==tid and self.worker_birth==birth
            and self.thread_identity(handle,tid,birth))

    def close(self,handle):
        if handle!=self.thread_handle and handle not in self.processes:return False
        if not self.kernel.CloseHandle(handle):return False
        if handle==self.thread_handle:self.thread_handle=0
        else:self.processes.pop(handle)
        return True

    def initialize(self):return self.ole.CoInitializeEx(None,0)
    def uninitialize(self):self.ole.CoUninitialize()
    def guard(self):return len(self.processes)==2 and all(
        self.check_process(handle,pid,birth) for handle,(pid,birth) in self.processes.items())

    def enter_dpi(self):
        return self.user.SetThreadDpiAwarenessContext(C.c_void_p(-4))

    def physical_dpi(self):
        return bool(self.user.AreDpiAwarenessContextsEqual(
            self.user.GetThreadDpiAwarenessContext(),C.c_void_p(-4)))

    def leave_dpi(self,token):
        previous=self.user.SetThreadDpiAwarenessContext(token)
        return bool(previous and self.user.AreDpiAwarenessContextsEqual(
            self.user.GetThreadDpiAwarenessContext(),token))

    def clear_variant(self,value):
        clear=self.aut.VariantClear
        clear.argtypes=(C.POINTER(type(value)),);clear.restype=C.c_int32
        return clear(C.byref(value))

    def worker(self,source,scope,sdk):return run_local_hit(source,scope,sdk,self)
    def boundary_worker(self):return run_native_boundary(self)
