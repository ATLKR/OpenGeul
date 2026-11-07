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
        # Validate the actual IAccessible prefix independently before its QI.
        # Every owned ref also has this validated IUnknown Release ABI.
        self._use('accessible_query',accessible_interface,'QueryInterface',
            (out(guid),out(void)),None)
        self._use('accessible_release',accessible_interface,'Release',(),None,unsigned=True)
        self._use('pattern',element_interface,'GetCurrentPatternAs',
            (scalar,out(guid),out(void)),(1,1,10))
        self._use('child_id',legacy_interface,'_get_CurrentChildId',(out(scalar),),(10,))
        self._use('control_type',element_interface,'_get_CurrentControlType',(out(scalar),),(10,))
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
                or key in ('child_id','control_type') and 'propget' not in item.idlflags):
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
        if type(source) is MsaaHitSourceV2:
            return (source.valid() and matches(source.client,'client') and all(matches(value,'element')
                for value in (source.retained_file,source.fresh_file,source.fresh_target,
                    source.retained_target,*source.negative_refs)))
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
        variantType=0,childIdZero=0,fileRoundTrip=0,firstCompareRawObserved=0,
        firstCompareRawBits=0,firstCompareIsZeroOrOne=0,targetFreshPositive=0,
        targetRetainedPositive=0,negativeCount=0,negativeRejected=0,cleanupError=0)
    result.update(falseShadowVersion=1,falseShadowStarted=0,falseShadowStatus=0,
        falseShadowStep=0,falseShadowAttempted=0,falseShadowCompleted=0,falseShadowLastHresult=0,
        falseShadowChildObserved=0,falseShadowChildBits=0,falseShadowIdentityObserved=0,
        falseShadowCanonicalEqual=0,falseShadowChildEqual=0,
        falseShadowGuardBefore=0,falseShadowGuardAfter=0,
        falseShadowOriginalControlTypeObserved=0,falseShadowOriginalControlType=0,
        falseShadowOriginalControlTypeHresult=0,falseShadowRoundTripControlTypeObserved=0,
        falseShadowRoundTripControlType=0,falseShadowRoundTripControlTypeHresult=0,
        falseShadowOriginalRepeatAttempted=0,falseShadowOriginalRepeatCompleted=0,
        falseShadowOriginalRepeatLastHresult=0,falseShadowOriginalRepeatObserved=0,
        falseShadowOriginalRepeatCanonicalEqual=0)
    for name in _OPERATIONS:
        result.update({name+'Attempted':0,name+'Completed':0,name+'Hresult':0})
    return result


class _Stop(Exception):pass


def run_local_hit(source,scope,sdk,platform,deadline):
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
        raw=equal.value
        # The first comparison is the File roundtrip below, never a later hit.
        if record['compareCompleted']==1:
            record.update(firstCompareRawObserved=1,firstCompareRawBits=raw&0xffffffff,
                firstCompareIsZeroOrOne=int(raw in (0,1)))
        # BOOL32 uses every nonzero encoding as TRUE; the field above records
        # encoding only and never qualifies the comparison or its cleanup.
        return bool(raw)
    def false_shadow(round_trip,accessible,child_id,pattern_iid,original_pattern):
        # Diagnostic only: canonical COM object + child cannot override UIA FALSE.
        # This bounds new-call admission, not synchronous COM/Release duration.
        record['falseShadowStarted']=1
        def check():
            if (type(deadline) not in (int,float) or not math.isfinite(deadline)
                    or platform.clock()>=deadline):
                record['falseShadowStatus']=2;raise _Stop()
            if not platform.guard():
                record['falseShadowStatus']=3;raise _Stop()
            if platform.clock()>=deadline:
                record['falseShadowStatus']=2;raise _Stop()
        def shadow_call(step,key,pointer,*arguments):
            check()
            record['falseShadowStep']=step;record['falseShadowAttempted']+=1
            hr=sdk.call(key,pointer,*arguments)
            if type(hr) is not int:raise TypeError()
            record['falseShadowCompleted']+=1;record['falseShadowLastHresult']=hr&0xffffffff
            check()
            if hr!=0:
                record['falseShadowStatus']=4;raise _Stop()
        def shadow_out(step,key,pointer,*arguments):
            value=C.c_void_p()
            try:shadow_call(step,key,pointer,*arguments,C.byref(value))
            finally:
                if value.value:
                    refs.append(value.value);record['referencesAcquired']+=1
            if not value.value:
                record['falseShadowStatus']=5;raise _Stop()
            return value.value
        def control_type(side,pointer):
            # A coarse projection observation only; even equal types prove no identity.
            check();value=C.c_int32()
            hr=sdk.call('control_type',pointer,C.byref(value))
            if type(hr) is not int:raise TypeError()
            prefix='falseShadow'+side+'ControlType'
            record[prefix+'Hresult']=hr&0xffffffff
            check()
            if hr!=0:
                record['falseShadowStatus']=4;raise _Stop()
            record[prefix]=value.value&0xffffffff;record[prefix+'Observed']=1
        def repeat_out(key,pointer,*arguments):
            check();value=C.c_void_p()
            record['falseShadowOriginalRepeatAttempted']+=1
            try:
                hr=sdk.call(key,pointer,*arguments,C.byref(value))
                if type(hr) is not int:raise TypeError()
                record['falseShadowOriginalRepeatCompleted']+=1
                record['falseShadowOriginalRepeatLastHresult']=hr&0xffffffff
                check()
                if hr!=0:
                    record['falseShadowStatus']=4;raise _Stop()
            finally:
                if value.value:
                    refs.append(value.value);record['referencesAcquired']+=1
            if not value.value:
                record['falseShadowStatus']=5;raise _Stop()
            return value.value
        try:
            check();record['falseShadowGuardBefore']=1
            legacy=shadow_out(1,'pattern',round_trip,10018,C.byref(pattern_iid))
            child=C.c_int32()
            shadow_call(2,'child_id',legacy,C.byref(child))
            record.update(falseShadowChildObserved=1,falseShadowChildBits=child.value&0xffffffff)
            projected=shadow_out(3,'accessible',legacy)
            iid=sdk.Guid('{'+_IIDS['unknown']+'}')
            original_identity=shadow_out(4,'accessible_query',accessible,C.byref(iid))
            projected_identity=shadow_out(5,'accessible_query',projected,C.byref(iid))
            # Hold both QI acquisitions simultaneously; equal addresses still
            # own two references and must each be released in reverse order.
            record.update(falseShadowIdentityObserved=1,
                falseShadowCanonicalEqual=int(original_identity==projected_identity),
                falseShadowChildEqual=int(child_id==child.value))
            control_type('Original',source.file)
            control_type('RoundTrip',round_trip)
            repeated=repeat_out('accessible',original_pattern)
            repeated_identity=repeat_out('accessible_query',repeated,C.byref(iid))
            # Historical extraction observation only. Complete/trusted data also
            # requires global shadow status, guards, cleanup and lease retirement.
            record.update(falseShadowOriginalRepeatObserved=1,
                falseShadowOriginalRepeatCanonicalEqual=int(original_identity==repeated_identity))
            check();record.update(falseShadowGuardAfter=1,falseShadowStatus=1)
        except _Stop:raise
        except BaseException:
            record['falseShadowStatus']=6;raise
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
        if not same(file_round_trip,source.file):
            false_shadow(file_round_trip,accessible,child.value,pattern_iid,legacy)
            raise _Stop()
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
        if record['falseShadowStatus']==1 and platform.clock()>=deadline:
            record['falseShadowStatus']=2
        if matched and clean:record.update(localKnown=1,localMatch=1,workerStage=8)
    return record


_V2_OPERATIONS=('pattern','child_id','accessible','accessible_query','control_type','hit_test','query','compare')


def worker_record_v2():
    record=dict(workerSchemaVersion=2,localKnown=0,localMatch=0,workerCleanup=0,workerStage=0,
        workerMta=0,comInitialized=0,comUninitialized=0,dpiEntered=0,dpiRestored=0,
        physicalDpiVerified=0,processBefore=0,processAfter=0,referencesAcquired=0,
        referencesReleased=0,variantAttempted=0,variantCleared=0,variantCleanupHresult=0,
        variantType=0,cleanupError=0,canonicalStatus=0,bindingCount=0,selfCount=0,
        filePairEqual=0,fileOriginalRepeatEqual=0,targetPairEqual=0,targetDifferentFromFile=0,
        hitMatchesTarget=0,fileUiPositive=0,targetUiPositive=0,negativeCount=0,negativeRejected=0)
    for name in _V2_OPERATIONS:record.update({name+'Attempted':0,name+'Completed':0,name+'Hresult':0})
    return record


def run_canonical_hit(source,scope,sdk,platform,deadline):
    """A separate native object/SELF target proof, never an inverse retry.

    Four exact UIA bindings, a retained-File repeat and the actual hit must agree
    while all canonical references are held. The original absolute deadline
    bounds admission, not synchronous COM/Release duration. No input is sent.
    """
    record=worker_record_v2();refs=[];variant=None;token=0;initialized=False;matched=False
    def budget():
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or platform.clock()>=deadline:
            record['canonicalStatus']=2;raise _Stop()
    def check():
        budget()
        if not platform.guard():record['canonicalStatus']=3;raise _Stop()
        budget()
    def require(value,code=7):
        if not value:record['canonicalStatus']=code;raise _Stop()
    def call(key,pointer,*arguments):
        check();record[key+'Attempted']+=1
        hr=sdk.call(key,pointer,*arguments)
        if type(hr) is not int:raise TypeError()
        record[key+'Completed']+=1;record[key+'Hresult']=hr&0xffffffff
        check();require(hr==0,4)
    def out(key,pointer,*arguments):
        value=C.c_void_p()
        try:call(key,pointer,*arguments,C.byref(value))
        finally:
            if value.value:refs.append(value.value);record['referencesAcquired']+=1
        require(bool(value.value),5)
        return value.value
    def same(first,second):
        value=C.c_int32();call('compare',source.client,first,second,C.byref(value))
        return bool(value.value)
    try:
        record['workerStage']=1
        require(type(source) is MsaaHitSourceV2 and source.valid(),5)
        require(isinstance(scope,MsaaHitScope) and scope.valid(),5)
        budget()
        hr=platform.initialize()
        if type(hr) is not int:raise TypeError()
        require(hr in (0,1),4);initialized=True;record['comInitialized']=1
        budget()
        require(platform.apartment(),5);budget();record['workerMta']=1;record['workerStage']=2
        token=platform.enter_dpi();require(bool(token),5);record['dpiEntered']=1;budget()
        require(platform.physical_dpi(),5);budget();record['physicalDpiVerified']=1
        check();record['processBefore']=1;record['workerStage']=3
        legacy_iid=sdk.Guid('{'+_IIDS['legacy']+'}');unknown_iid=sdk.Guid('{'+_IIDS['unknown']+'}')
        bindings=[];record['workerStage']=4
        for element in (source.retained_file,source.fresh_file,source.fresh_target,source.retained_target):
            pattern=out('pattern',element,10018,C.byref(legacy_iid))
            child=C.c_int32(-1);call('child_id',pattern,C.byref(child));require(child.value==0,5)
            record['selfCount']+=1
            accessible=out('accessible',pattern)
            identity=out('accessible_query',accessible,C.byref(unknown_iid))
            kind=C.c_int32();call('control_type',element,C.byref(kind));require(kind.value==50011,5)
            bindings.append((pattern,accessible,identity));record['bindingCount']+=1
        record['workerStage']=5
        original,_,fresh_target,retained_target=bindings
        require(original[2]==bindings[1][2]);record['filePairEqual']=1
        repeated=out('accessible',original[0]);repeated_identity=out('accessible_query',repeated,C.byref(unknown_iid))
        require(repeated_identity==original[2]);record['fileOriginalRepeatEqual']=1
        require(fresh_target[2]==retained_target[2]);record['targetPairEqual']=1
        require(fresh_target[2]!=original[2]);record['targetDifferentFromFile']=1
        record['workerStage']=6
        variant=sdk.Variant();record['variantAttempted']=1
        call('hit_test',original[1],scope.x,scope.y,C.byref(variant));record['variantType']=int(variant.vt)
        require(variant.vt==9 and bool(variant._.c_void_p),5)
        accessible_iid=sdk.Guid('{'+_IIDS['accessible']+'}')
        hit=out('query',C.c_void_p(variant._.c_void_p),C.byref(accessible_iid))
        hit_identity=out('accessible_query',hit,C.byref(unknown_iid))
        require(hit_identity==fresh_target[2]);record['hitMatchesTarget']=1
        record['workerStage']=7
        require(same(source.retained_file,source.fresh_file));record['fileUiPositive']=1
        require(same(source.fresh_target,source.retained_target));record['targetUiPositive']=1
        for negative in source.negative_refs:
            record['negativeCount']+=1;require(not same(source.fresh_target,negative));record['negativeRejected']+=1
        check();record['processAfter']=1;matched=True
    except _Stop:pass
    except BaseException:
        record['canonicalStatus']=6;record['cleanupError']=1
    finally:
        cleanup_failed=False
        if variant is not None:
            try:
                hr=platform.clear_variant(variant)
                if type(hr) is not int:raise TypeError()
                record['variantCleanupHresult']=hr&0xffffffff;record['variantCleared']=int(hr==0)
                if hr!=0:cleanup_failed=True
            except BaseException:cleanup_failed=True
        for pointer in reversed(refs):
            try:
                result=sdk.call('release',C.c_void_p(pointer))
                if type(result) is not int or not 0<=result<=0xffffffff:raise TypeError()
                record['referencesReleased']+=1
            except BaseException:cleanup_failed=True
        refs.clear()
        if token:
            try:record['dpiRestored']=int(bool(platform.leave_dpi(token)))
            except BaseException:cleanup_failed=True
            if not record['dpiRestored']:cleanup_failed=True
        if initialized:
            try:platform.uninitialize();record['comUninitialized']=1
            except BaseException:cleanup_failed=True
        if cleanup_failed:record['cleanupError']=1;record['canonicalStatus']=8
        clean=(not record['cleanupError'] and record['referencesAcquired']==record['referencesReleased']
            and (not record['variantAttempted'] or record['variantCleared'])
            and (not initialized or record['comUninitialized']) and (not token or record['dpiRestored']))
        record['workerCleanup']=int(clean)
        try:
            if platform.clock()>=deadline:record['canonicalStatus']=2
            elif matched and clean:record.update(canonicalStatus=1,workerStage=8,localKnown=1,localMatch=1)
        except BaseException:record.update(canonicalStatus=6,cleanupError=1,workerCleanup=0)
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


@dataclass(frozen=True)
class MsaaHitSourceV2:
    client:object
    retained_file:object
    fresh_file:object
    fresh_target:object
    retained_target:object
    negative_refs:tuple
    shell_handle:int
    engine_handle:int
    keepalive:tuple

    def valid(self):
        return (all(value is not None for value in (self.client,self.retained_file,self.fresh_file,
                    self.fresh_target,self.retained_target))
            and type(self.negative_refs) is tuple and 2<=len(self.negative_refs)<=16
            and all(value is not None for value in self.negative_refs)
            and type(self.keepalive) is tuple and bool(self.keepalive) and all(value is not None for value in self.keepalive)
            and all(type(value) is int and value>0 for value in (self.shell_handle,self.engine_handle)))


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


def _record(scope,synthetic,*,profile_version=1):
    if type(profile_version) is not int or profile_version not in (1,2):raise ValueError('Unknown native point profile')
    return dict(worker_record() if profile_version==1 else worker_record_v2(),schemaVersion=profile_version,diagnosticOnly=1,acceptanceEligible=0,
        providerLocalOnly=1,globalHitSubstituted=0,synthetic=int(synthetic),
        scopeId=scope.scope_id if isinstance(scope,MsaaHitScope) and scope.valid() else 0,
        stageCode=0,nativeAttempted=0,nativeExit=0,threadClosed=0,processesClosed=0,
        controllerPid=0,threadId=0,threadBirth=0,threadIdentity=0,
        callbackIdentity=0,exitCodeObserved=0,nativeExitCode=0,
        localKnown=0,localMatch=0,workerCleanup=0,workerException=0,pending=0)


def begin_msaa_hit(source,scope,sdk,deadline,*,native_enabled=False,profile_version=1,_kernel=None):
    """One pending capsule, source-owned duplicate process HANDLEs, no input.

    The private kernel hook is synthetic-test-only. Production startup remains
    disabled until the controller's explicit opt-in finalization fence is ready.
    A local match is never an input/acceptance grant: the controller must also
    prove the original popup exposure, live scope and fresh target after return.
    """
    global _active
    if type(profile_version) is not int or profile_version not in (1,2):raise ValueError('Unknown native point profile')
    lease=MsaaHitLease(source,scope,sdk,deadline,_kernel,profile_version=profile_version)
    synthetic=_kernel is not None and getattr(_kernel,'synthetic',False) is True
    if not synthetic and (native_enabled is not True or not NATIVE_LAUNCH_ENABLED):
        lease.record['stageCode']=1
        return lease
    if not (isinstance(source,MsaaHitSource) if profile_version==1 else type(source) is MsaaHitSourceV2):
        lease.record['stageCode']=3
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
    def __init__(self,source,scope,sdk,deadline,kernel,*,profile_version=1):
        self.source=source;self.scope=scope;self.sdk=sdk;self.deadline=deadline;self.kernel=kernel
        self.record=_record(scope,getattr(kernel,'synthetic',False),profile_version=profile_version)
        self._profile_version=profile_version
        self._status_key='falseShadowStatus' if profile_version==1 else 'canonicalStatus'
        self.process_handles=[];self.thread=0;self.tid=0;self.birth=0
        self.worker=None;self._late=False;self._retired=False;self._worker_exception=False
        self._cleanup_unknown=False
        self._unknown_handles=set();self._closed_handles=set();self._closing_handle=0
        self.runner=lambda:self.kernel.worker(self.source,self.scope,self.sdk,self.deadline)

    @property
    def pending(self):return _active is self

    @property
    def profile_version(self):return self._profile_version

    def valid(self):
        source_type=isinstance(self.source,MsaaHitSource) if self.profile_version==1 else type(self.source) is MsaaHitSourceV2
        return (source_type and self.source.valid()
            and isinstance(self.scope,MsaaHitScope) and self.scope.valid()
            and type(self.deadline) in (int,float) and math.isfinite(self.deadline)
            and self.kernel.clock()<self.deadline<=self.kernel.clock()+5)

    def _run(self):
        # The callback normal-return boundary must encompass BaseException.
        try:
            result=self.runner()
            expected=worker_record() if self.profile_version==1 else worker_record_v2()
            if (type(result) is dict and result.keys()==expected.keys()
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
            if (self._late or self.kernel.clock()>=self.deadline) and self.record[self._status_key]==1:
                self.record[self._status_key]=2 if self.kernel.clock()>=self.deadline else 0
            self._clear()
            if self.kernel.clock()>=self.deadline:
                self._late=True;self.record.update(localKnown=0,localMatch=0,stageCode=11)
                if self.record[self._status_key]==1:self.record[self._status_key]=2
        except BaseException:
            if self._closing_handle:self._unknown_handles.add(self._closing_handle)
            self.record['stageCode']=10
            return self._unknown()
        return dict(self.record)

    def _unknown(self):
        self._late=True;self.record['pending']=1
        self.record['localKnown']=self.record['localMatch']=0
        # Retain bits; containment alone cannot establish deadline expiry.
        if self.record[self._status_key]==1:
            self.record[self._status_key]=0
            try:
                if self.kernel.clock()>=self.deadline:self.record[self._status_key]=2
            except BaseException:pass
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

    def worker(self,source,scope,sdk,deadline):
        if type(source) is MsaaHitSourceV2:return run_canonical_hit(source,scope,sdk,self,deadline)
        if isinstance(source,MsaaHitSource):return run_local_hit(source,scope,sdk,self,deadline)
        raise ValueError('Unknown native point source')
    def boundary_worker(self):return run_native_boundary(self)


# Profile 3 is a separately selected, non-accepting observation. The original
# SDK binder, both positive workers and public begin_msaa_hit stay unchanged.
# This pins actual official IDL content, not an unverified immutable revision.
_IA2_PREFIX=(
    'QueryInterface','AddRef','Release','GetTypeInfoCount','GetTypeInfo',
    'GetIDsOfNames','Invoke','get_accParent','get_accChildCount','get_accChild',
    'get_accName','get_accValue','get_accDescription','get_accRole','get_accState',
    'get_accHelp','get_accHelpTopic','get_accKeyboardShortcut','get_accFocus',
    'get_accSelection','get_accDefaultAction','accSelect','accLocation',
    'accNavigate','accHitTest','accDoDefaultAction','put_accName','put_accValue')
_IA2_DERIVED=('nRelations','relation','relations','role','scrollTo','scrollToPoint',
    'groupPosition','states','extendedRole','localizedExtendedRole','nExtendedStates',
    'extendedStates','localizedExtendedStates','uniqueID','windowHandle',
    'indexInParent','locale','attributes')
_IA2_METADATA=(
    'https://raw.githubusercontent.com/LinuxA11y/IAccessible2/master/api/Accessible2.idl',
    30918,'e3d6a3fa6f72a1e630c746abba9376508cf327a4ae7648fcd176cff8c90317f6',
    'e89f726e-c4f4-4c19-bb19-b647d7fa8478','IAccessible2','IAccessible',
    _IA2_PREFIX,_IA2_DERIVED,
    (('uniqueID','propget',('out','retval'),'HRESULT32','LONG32*'),
     ('windowHandle','propget',('out','retval'),'HRESULT32','HWND*')),
    ('6d5140c1-7436-11ce-8034-00aa006009fa',
     ('QueryInterface','AddRef','Release','QueryService'),
     ('GUID*','GUID*','void**'),(1,1,2)))


def _closed_metadata(actual,expected):
    if type(actual) is not type(expected):return False
    if type(expected) is tuple:
        return len(actual)==len(expected) and all(_closed_metadata(a,b) for a,b in zip(actual,expected))
    return actual==expected


class Ia2SdkAbi(SdkAbi):
    """Typed, content-pinned IA2 getter ABI, selected before a native lease.

    Unused inherited/derived names establish layout only; they are not called.
    The service's real QueryService output supplies the IA2 interface pointer.
    """
    def __init__(self,*,_metadata=None,**arguments):
        metadata=_IA2_METADATA if _metadata is None else _metadata
        if not _closed_metadata(metadata,_IA2_METADATA):raise ValueError('IA2 metadata differs')
        super().__init__(**arguments)
        methods=_methods(arguments['accessible_interface'])
        def normalize(name):
            if name.startswith('_get_acc'):return 'get_'+name[5:]
            if name.startswith('_set_acc'):return 'put_'+name[5:]
            return name
        if (tuple(normalize(item.name) for item in methods)!=metadata[6]
                or len(methods)!=28 or len(metadata[7])!=18
                or not _scalar(C.c_int32,4,True) or C.sizeof(C.c_void_p)!=8):
            raise ValueError('IA2 inherited declaration differs')
        self.slots['service_query']=self.slots['accessible_query']
        self.signatures['service_query']=self.signatures['accessible_query']
        # QueryService follows the declared IUnknown prefix. Its two GUIDs are
        # input refs and the separately owned interface output is void**.
        self.slots['ia2_query']=len(metadata[9][1])-1
        self.signatures['ia2_query']=(C.c_int32,
            (C.POINTER(self.Guid),C.POINTER(self.Guid),C.POINTER(C.c_void_p)))
        for key,name,kind in (('unique_id','uniqueID',C.c_int32),
                ('window_handle','windowHandle',C.c_void_p)):
            self.slots[key]=len(methods)+metadata[7].index(name)
            self.signatures[key]=(C.c_int32,(C.POINTER(kind),))

    def matches_source(self,source):
        if type(source) is not MsaaHitSourceV3:return False
        def matches(value,expected):
            try:
                kind=type(value);interface=kind.__com_interface__
                return (issubclass(kind,C.c_void_p) and bool(C.cast(value,C.c_void_p).value)
                    and any(_iid(base,expected) for base in interface.__mro__))
            except (AttributeError,TypeError,ValueError):return False
        return source.valid() and matches(source.client,'client') and all(matches(value,'element')
            for value in (source.retained_file,source.fresh_file,source.fresh_target,
                source.retained_target,*source.negative_refs))


@dataclass(frozen=True)
class MsaaHitSourceV3(MsaaHitSourceV2):
    captured_at:float
    action_deadline:float
    document_hwnd:int
    popup_hwnd:int
    popup_thread:int
    owner_chain:tuple

    def valid(self):
        return (MsaaHitSourceV2.valid(self)
            and all(type(value) in (int,float) and math.isfinite(value)
                for value in (self.captured_at,self.action_deadline))
            and 0<self.action_deadline-self.captured_at<=5
            and all(type(value) is int and 0<value<2**64
                for value in (self.document_hwnd,self.popup_hwnd))
            and type(self.popup_thread) is int and 0<self.popup_thread<2**32
            and type(self.owner_chain) is tuple and 2<=len(self.owner_chain)<=16
            and all(type(value) is int and 0<value<2**64 for value in self.owner_chain)
            and self.owner_chain[0]==self.popup_hwnd)


_V3_OPERATIONS=_V2_OPERATIONS+('service_query','ia2_query','unique_id','window_handle')


def worker_record_v3():
    record=worker_record_v2()
    record.pop('canonicalStatus')
    record.update(workerSchemaVersion=3,diagnosticComplete=0,ia2Status=0,
        filePairObserved=0,fileOriginalRepeatObserved=0,targetPairObserved=0,
        targetDifferentFromFileObserved=0,hitMatchesTargetObserved=0,
        tupleComparisonsObserved=0,fileTupleEqual=0,targetTupleEqual=0,
        targetDifferentFilesTuple=0,hitMatchesTargetsTuple=0,hitDifferentFilesTuple=0,
        fileAnchorStable=0,targetAnchorStable=0,ia2TupleCount=0,uidZeroCount=0,
        uidNegativeCount=0,hwndDomainMask=0)
    for name in _V3_OPERATIONS:
        record.update({name+'Attempted':0,name+'Completed':0,name+'Hresult':0})
    return record


def run_ia2_diagnostic(source,scope,sdk,platform,deadline):
    """One fixed read-only measurement; no value can authorize input.

    51+N provider calls, 26 acquired refs and a separate owned VARIANT on the
    complete path. Deadline checks bound admission, not synchronous COM/Release.
    """
    record=worker_record_v3();refs=[];variant=None;token=0;initialized=False;finished=False
    expiry=deadline
    if type(source) is MsaaHitSourceV3 and source.valid() and type(deadline) in (int,float):
        expiry=min(deadline,source.action_deadline,source.captured_at+1.5)
    def budget():
        if type(expiry) not in (int,float) or not math.isfinite(expiry) or platform.clock()>=expiry:
            record['ia2Status']=2;raise _Stop()
    def check():
        budget()
        if not platform.guard():record['ia2Status']=3;raise _Stop()
        budget()
    def require(value,code=5):
        if not value:record['ia2Status']=code;raise _Stop()
    def call(key,pointer,*arguments):
        check();record[key+'Attempted']+=1
        hr=sdk.call(key,pointer,*arguments)
        if type(hr) is not int:raise TypeError()
        record[key+'Completed']+=1;record[key+'Hresult']=hr&0xffffffff
        check();require(hr==0,4)
    def out(key,pointer,*arguments):
        value=C.c_void_p()
        try:call(key,pointer,*arguments,C.byref(value))
        finally:
            if value.value:refs.append(value.value);record['referencesAcquired']+=1
        require(bool(value.value))
        return value.value
    def same(first,second):
        value=C.c_int32();call('compare',source.client,first,second,C.byref(value))
        require(value.value in (0,1),5)
        return value.value==1
    def scalars(pointer):
        unique=C.c_int32();window=C.c_void_p()
        call('unique_id',pointer,C.byref(unique))
        call('window_handle',pointer,C.byref(window));require(bool(window.value))
        check();domain=platform.window_domain(window.value,source,scope);check()
        require(type(domain) is int and 1<=domain<=5,7)
        record['hwndDomainMask']|=1<<domain
        return unique.value,window.value
    def identity(accessible):
        service=out('service_query',accessible,C.byref(service_iid))
        ia2=out('ia2_query',service,C.byref(accessible_iid),C.byref(ia2_iid))
        values=scalars(ia2);record['ia2TupleCount']+=1
        record['uidZeroCount']+=int(values[0]==0);record['uidNegativeCount']+=int(values[0]<0)
        return ia2,values
    try:
        record['workerStage']=1
        require(type(source) is MsaaHitSourceV3 and source.valid())
        require(isinstance(scope,MsaaHitScope) and scope.valid())
        require(source.owner_chain[-1] in (scope.child_hwnd,source.document_hwnd))
        require(source.captured_at<=platform.clock())
        budget();hr=platform.initialize()
        if type(hr) is not int:raise TypeError()
        require(hr in (0,1),4);initialized=True;record['comInitialized']=1
        budget();require(platform.apartment());budget();record['workerMta']=1
        token=platform.enter_dpi();require(bool(token));record['dpiEntered']=1;budget()
        require(platform.physical_dpi());budget();record['physicalDpiVerified']=1
        check();record['processBefore']=1;record['workerStage']=2
        # These are source selection guards. Unlike canonical inequality, a
        # FALSE positive or colliding negative stops all subsequent reads.
        require(same(source.retained_file,source.fresh_file),7);record['fileUiPositive']=1
        require(same(source.fresh_target,source.retained_target),7);record['targetUiPositive']=1
        for negative in source.negative_refs:
            record['negativeCount']+=1;require(not same(source.fresh_target,negative),7)
            record['negativeRejected']+=1
        legacy_iid=sdk.Guid('{'+_IIDS['legacy']+'}');unknown_iid=sdk.Guid('{'+_IIDS['unknown']+'}')
        accessible_iid=sdk.Guid('{'+_IIDS['accessible']+'}')
        service_iid=sdk.Guid('{'+_IA2_METADATA[9][0]+'}');ia2_iid=sdk.Guid('{'+_IA2_METADATA[3]+'}')
        bindings=[];record['workerStage']=3
        for element in (source.retained_file,source.fresh_file,source.fresh_target,source.retained_target):
            pattern=out('pattern',element,10018,C.byref(legacy_iid))
            child=C.c_int32(-1);call('child_id',pattern,C.byref(child));require(child.value==0)
            record['selfCount']+=1
            accessible=out('accessible',pattern)
            canonical=out('accessible_query',accessible,C.byref(unknown_iid))
            kind=C.c_int32();call('control_type',element,C.byref(kind));require(kind.value==50011)
            ia2,values=identity(accessible)
            bindings.append((pattern,accessible,canonical,ia2,values));record['bindingCount']+=1
        original,fresh_file,fresh_target,retained_target=bindings
        record.update(filePairObserved=1,filePairEqual=int(original[2]==fresh_file[2]),workerStage=4)
        repeated=out('accessible',original[0]);repeat_identity=out('accessible_query',repeated,C.byref(unknown_iid))
        record.update(fileOriginalRepeatObserved=1,fileOriginalRepeatEqual=int(repeat_identity==original[2]),
            targetPairObserved=1,targetPairEqual=int(fresh_target[2]==retained_target[2]),
            targetDifferentFromFileObserved=1,
            targetDifferentFromFile=int(all(target[2]!=file[2] for target in (fresh_target,retained_target)
                for file in (original,fresh_file))),workerStage=5)
        variant=sdk.Variant();record['variantAttempted']=1
        call('hit_test',original[1],scope.x,scope.y,C.byref(variant));record['variantType']=int(variant.vt)
        require(variant.vt==9 and bool(variant._.c_void_p))
        hit=out('query',C.c_void_p(variant._.c_void_p),C.byref(accessible_iid))
        hit_identity=out('accessible_query',hit,C.byref(unknown_iid))
        record.update(hitMatchesTargetObserved=1,hitMatchesTarget=int(hit_identity==fresh_target[2]))
        _,hit_values=identity(hit);record['workerStage']=6
        file_anchor=scalars(original[3]);target_anchor=scalars(fresh_target[3])
        record.update(tupleComparisonsObserved=1,fileTupleEqual=int(original[4]==fresh_file[4]),
            targetTupleEqual=int(fresh_target[4]==retained_target[4]),
            targetDifferentFilesTuple=int(all(target[4]!=file[4] for target in (fresh_target,retained_target)
                for file in (original,fresh_file))),
            hitMatchesTargetsTuple=int(all(hit_values==target[4] for target in (fresh_target,retained_target))),
            hitDifferentFilesTuple=int(all(hit_values!=file[4] for file in (original,fresh_file))),
            fileAnchorStable=int(file_anchor==original[4]),targetAnchorStable=int(target_anchor==fresh_target[4]))
        check();record['processAfter']=1;finished=True
    except _Stop:pass
    except BaseException:record.update(ia2Status=6,cleanupError=1)
    finally:
        cleanup_failed=False
        if variant is not None:
            try:
                hr=platform.clear_variant(variant)
                if type(hr) is not int:raise TypeError()
                record['variantCleanupHresult']=hr&0xffffffff;record['variantCleared']=int(hr==0)
                if hr!=0:cleanup_failed=True
            except BaseException:cleanup_failed=True
        for pointer in reversed(refs):
            try:
                result=sdk.call('release',C.c_void_p(pointer))
                if type(result) is not int or not 0<=result<=0xffffffff:raise TypeError()
                record['referencesReleased']+=1
            except BaseException:cleanup_failed=True
        refs.clear()
        if token:
            try:record['dpiRestored']=int(bool(platform.leave_dpi(token)))
            except BaseException:cleanup_failed=True
            if not record['dpiRestored']:cleanup_failed=True
        if initialized:
            try:platform.uninitialize();record['comUninitialized']=1
            except BaseException:cleanup_failed=True
        if cleanup_failed:record.update(cleanupError=1,ia2Status=8)
        clean=(not record['cleanupError'] and record['referencesAcquired']==record['referencesReleased']
            and (not record['variantAttempted'] or record['variantCleared'])
            and (not initialized or record['comUninitialized']) and (not token or record['dpiRestored']))
        record['workerCleanup']=int(clean)
        try:
            if platform.clock()>=expiry:record['ia2Status']=2
            elif finished and clean:
                if not platform.guard():record['ia2Status']=3
                elif platform.clock()>=expiry:record['ia2Status']=2
                else:record.update(ia2Status=1,workerStage=7,diagnosticComplete=1)
        except BaseException:record.update(ia2Status=6,cleanupError=1,workerCleanup=0)
        record['localKnown']=record['localMatch']=0
    return record


def _record_v3(scope,synthetic):
    boundary=_record(scope,synthetic,profile_version=2)
    for name in worker_record_v2():boundary.pop(name,None)
    boundary.update(schemaVersion=3)
    return dict(worker_record_v3(),**boundary)


def _valid_v3_worker(result,negative_count):
    expected=worker_record_v3()
    if (type(result) is not dict or result.keys()!=expected.keys()
            or any(type(value) is not int or not 0<=value<=0xffffffff for value in result.values())
            or result['workerSchemaVersion']!=3 or result['localKnown'] or result['localMatch']
            or result['diagnosticComplete'] not in (0,1)):
        return False
    counts=dict(pattern=4,child_id=4,accessible=5,accessible_query=6,control_type=4,
        hit_test=1,query=1,compare=2+negative_count,service_query=5,ia2_query=5,
        unique_id=7,window_handle=7)
    booleans=('workerCleanup','workerMta','comInitialized','comUninitialized','dpiEntered',
        'dpiRestored','physicalDpiVerified','processBefore','processAfter','variantAttempted',
        'variantCleared','cleanupError','fileUiPositive','targetUiPositive','filePairObserved',
        'fileOriginalRepeatObserved','targetPairObserved','targetDifferentFromFileObserved',
        'hitMatchesTargetObserved','tupleComparisonsObserved','filePairEqual','fileOriginalRepeatEqual',
        'targetPairEqual','targetDifferentFromFile','hitMatchesTarget','fileTupleEqual',
        'targetTupleEqual','targetDifferentFilesTuple','hitMatchesTargetsTuple','hitDifferentFilesTuple',
        'fileAnchorStable','targetAnchorStable')
    if (any(result[key] not in (0,1) for key in booleans)
            or not 0<=result['ia2Status']<=8 or not 0<=result['workerStage']<=7
            or not result['referencesReleased']<=result['referencesAcquired']<=26
            or not result['negativeRejected']<=result['negativeCount']<=negative_count
            or not result['selfCount']<=4 or not result['bindingCount']<=4
            or not result['uidZeroCount']+result['uidNegativeCount']<=result['ia2TupleCount']<=5
            or result['hwndDomainMask']&~62 or result['variantType']>65535
            or any(not result[name+'Completed']<=result[name+'Attempted']<=count
                for name,count in counts.items())
            or result['workerCleanup'] and (result['cleanupError']
                or result['referencesAcquired']!=result['referencesReleased']
                or result['variantAttempted']!=result['variantCleared']
                or result['comInitialized']!=result['comUninitialized']
                or result['dpiEntered']!=result['dpiRestored'])):
        return False
    if not result['diagnosticComplete']:return True
    facts=('workerCleanup','workerMta','comInitialized','comUninitialized','dpiEntered',
        'dpiRestored','physicalDpiVerified','processBefore','processAfter','variantAttempted',
        'variantCleared','fileUiPositive','targetUiPositive','filePairObserved',
        'fileOriginalRepeatObserved','targetPairObserved','targetDifferentFromFileObserved',
        'hitMatchesTargetObserved','tupleComparisonsObserved')
    return (all(result[key]==1 for key in facts) and result['ia2Status']==1
        and result['workerStage']==7 and result['referencesAcquired']==result['referencesReleased']==26
        and result['variantType']==9 and result['variantCleanupHresult']==result['cleanupError']==0
        and result['bindingCount']==result['selfCount']==4 and result['ia2TupleCount']==5
        and result['negativeCount']==result['negativeRejected']==negative_count
        and result['uidZeroCount']+result['uidNegativeCount']<=5
        and 0<result['hwndDomainMask']<64 and not result['hwndDomainMask']&1
        and all(result[name+'Attempted']==result[name+'Completed']==count
            and result[name+'Hresult']==0 for name,count in counts.items()))


class Ia2DiagnosticLease(MsaaHitLease):
    def __init__(self,source,scope,sdk,deadline,kernel):
        super().__init__(source,scope,sdk,deadline,kernel,profile_version=2)
        self.record=_record_v3(scope,getattr(kernel,'synthetic',False))
        self._profile_version=3;self._status_key='ia2Status'
        self.action_deadline=deadline
        if type(source) is MsaaHitSourceV3 and source.valid() and type(deadline) in (int,float):
            self.deadline=min(deadline,source.captured_at+1.5)

    def valid(self):
        return (type(self.source) is MsaaHitSourceV3 and self.source.valid()
            and isinstance(self.scope,MsaaHitScope) and self.scope.valid()
            and self.source.action_deadline==self.action_deadline
            and self.source.captured_at<=self.kernel.clock()
            and type(self.action_deadline) in (int,float) and math.isfinite(self.action_deadline)
            and self.kernel.clock()<self.deadline<=self.kernel.clock()+1.5
            and self.action_deadline<=self.kernel.clock()+5)

    def _run(self):
        try:
            result=self.runner()
            if _valid_v3_worker(result,len(self.source.negative_refs)):self.worker=dict(result)
            else:self._worker_exception=True
        except BaseException:self._worker_exception=True
        return 0

    def _collect(self,deadline,retiring):
        result=super()._collect(deadline,retiring)
        if (result['stageCode']!=13 or result['pending'] or result['workerException']
                or not result['workerCleanup'] or result['localKnown'] or result['localMatch']):
            self.record['diagnosticComplete']=0
        # Positive worker packets were rejected in _run, never quiet-coerced.
        self.record['localKnown']=self.record['localMatch']=0
        return dict(self.record)

    def _unknown(self):
        self.record['diagnosticComplete']=0
        return super()._unknown()


def begin_ia2_diagnostic(source,scope,sdk,deadline,*,native_enabled=False,_kernel=None):
    """Separate preselected profile; shares the one pending callback registry."""
    lease=Ia2DiagnosticLease(source,scope,sdk,deadline,_kernel)
    synthetic=_kernel is not None and getattr(_kernel,'synthetic',False) is True
    if not synthetic and (native_enabled is not True or not NATIVE_LAUNCH_ENABLED):
        lease.record['stageCode']=1;return lease
    if type(source) is not MsaaHitSourceV3:
        lease.record['stageCode']=3;return lease
    if not _reserve(lease):lease.record['stageCode']=2;return lease
    if not synthetic:
        try:
            _kernel=Ia2WindowsKernel()
            if (not isinstance(sdk,Ia2SdkAbi) or sdk.function_factory is not C.WINFUNCTYPE
                    or not sdk.matches_source(source)):raise ValueError('Native IA2 SDK binder required')
            lease.kernel=_kernel
        except BaseException:lease.record['stageCode']=3;lease._clear();return lease
    if not lease.valid():lease.record['stageCode']=3;lease._clear();return lease
    try:
        if not _kernel.apartment():lease.record['stageCode']=4;lease._release_unstarted();return lease
        lease.record['stageCode']=5
        for handle,pid,birth in ((source.shell_handle,scope.shell_pid,scope.shell_birth),
                (source.engine_handle,scope.engine_pid,scope.engine_birth)):
            duplicate=_kernel.duplicate(handle,pid,birth);lease.process_handles.append((duplicate,pid,birth))
            adopt=getattr(_kernel,'adopt_duplicate',None)
            if adopt is not None:adopt(duplicate)
            if not _kernel.check_process(duplicate,pid,birth):raise _Stop()
        if _kernel.clock()>=lease.deadline:
            lease.record['stageCode']=11;lease._release_unstarted();return lease
        lease.record.update(stageCode=6,nativeAttempted=1)
        lease.thread,lease.tid,lease.birth=_kernel.start(lease._run)
        if not lease.thread or not lease.tid or not lease.birth:lease.record['pending']=1
    except BaseException:
        if lease.record['nativeAttempted'] and getattr(_kernel,'start_uncertain',False):lease.record['pending']=1
        else:lease._release_unstarted()
    return lease


class Ia2WindowsKernel(WindowsKernel):
    """Original process/HANDLE capsule plus profile3's exact popup guard."""
    def __init__(self):
        super().__init__()
        class Point(C.Structure):_fields_=[('x',C.c_int32),('y',C.c_int32)]
        class Rect(C.Structure):_fields_=[('left',C.c_int32),('top',C.c_int32),('right',C.c_int32),('bottom',C.c_int32)]
        class Gui(C.Structure):
            _fields_=[('cbSize',C.c_uint32),('flags',C.c_uint32),
                *((name,C.c_void_p) for name in ('active','focus','capture','menu','move','caret')),
                ('caretRect',Rect)]
        self.Point=Point;self.Gui=Gui
        for name in ('IsWindow','IsWindowVisible','IsWindowEnabled','IsIconic'):
            self._bind(self.user,name,(C.c_void_p,),C.c_int32)
        self._bind(self.user,'GetWindowThreadProcessId',(C.c_void_p,C.POINTER(C.c_uint32)),C.c_uint32)
        self._bind(self.user,'GetParent',(C.c_void_p,),C.c_void_p)
        self._bind(self.user,'GetAncestor',(C.c_void_p,C.c_uint32),C.c_void_p)
        self._bind(self.user,'GetWindow',(C.c_void_p,C.c_uint32),C.c_void_p)
        self._bind(self.user,'GetForegroundWindow',(),C.c_void_p)
        self._bind(self.user,'WindowFromPhysicalPoint',(Point,),C.c_void_p)
        self._bind(self.user,'GetGUIThreadInfo',(C.c_uint32,C.POINTER(Gui)),C.c_int32)
        self._diagnostic_source=None;self._diagnostic_scope=None

    def _window_process(self,hwnd):
        pid=C.c_uint32();thread=int(self.user.GetWindowThreadProcessId(hwnd,C.byref(pid)))
        return thread,pid.value

    def guard(self):
        if not super().guard():return False
        source,scope=self._diagnostic_source,self._diagnostic_scope
        if type(source) is not MsaaHitSourceV3 or not source.valid() or not scope.valid():return False
        u=self.user;doc=source.document_hwnd;popup=source.popup_hwnd
        windows=(doc,scope.parent_hwnd,scope.child_hwnd,*source.owner_chain)
        if not all(u.IsWindow(hwnd) for hwnd in windows):return False
        if self._window_process(doc)[1]!=scope.shell_pid or self._window_process(scope.parent_hwnd)[1]!=scope.shell_pid:return False
        if any(self._window_process(hwnd)!=(source.popup_thread,scope.engine_pid)
                for hwnd in (scope.child_hwnd,popup)):return False
        if any(self._window_process(hwnd)[1]!=scope.engine_pid for hwnd in source.owner_chain[:-1]):return False
        if int(u.GetParent(scope.child_hwnd) or 0)!=scope.parent_hwnd:return False
        if int(u.GetAncestor(scope.child_hwnd,2) or 0)!=doc:return False
        if not all(u.IsWindowVisible(hwnd) and u.IsWindowEnabled(hwnd) for hwnd in (doc,popup)) or u.IsIconic(doc):return False
        for first,second in zip(source.owner_chain,source.owner_chain[1:]):
            if int(u.GetWindow(first,4) or 0)!=second:return False
        if int(u.GetForegroundWindow() or 0) not in (doc,popup):return False
        if int(u.WindowFromPhysicalPoint(self.Point(scope.x,scope.y)) or 0)!=popup:return False
        gui=self.Gui();gui.cbSize=C.sizeof(gui)
        if not u.GetGUIThreadInfo(source.popup_thread,C.byref(gui)):return False
        if (not gui.focus or self._window_process(gui.focus)[1]!=scope.engine_pid
                or int(u.GetAncestor(gui.focus,2) or 0) not in (doc,popup)
                or int(gui.capture or 0) not in (0,scope.child_hwnd,popup)
                or int(gui.menu or 0) not in (0,scope.child_hwnd,popup)):return False
        return super().guard()

    def window_domain(self,hwnd,source,scope):
        # No identifier/HWND is exported; only this closed relationship code.
        if not self.guard():return 0
        if hwnd==scope.child_hwnd:return 1
        if hwnd==source.popup_hwnd:return 2
        if hwnd==scope.parent_hwnd:return 3
        if hwnd==source.document_hwnd:return 4
        if hwnd in source.owner_chain and self._window_process(hwnd)[1] in (scope.engine_pid,scope.shell_pid):return 5
        return 0

    def worker(self,source,scope,sdk,deadline):
        if type(source) is not MsaaHitSourceV3:raise ValueError('IA2 diagnostic source required')
        self._diagnostic_source,self._diagnostic_scope=source,scope
        return run_ia2_diagnostic(source,scope,sdk,self,deadline)


# A separately selected source-qualified profile. Old profiles and packets are
# not inputs to this live worker; its candidate is not a controller input grant.
def _admission_words_v4(admission,expected):
    from native_menu_source_admission import SourceMenuAdmission
    def digest(value):
        return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    if type(admission) is not SourceMenuAdmission or not digest(expected):
        raise ValueError('A frozen source admission is required')
    summary=admission.summary()
    keys={'schemaVersion','architecture','admissionSha256','lockSha256','receiptSha256',
        'engineZipSha256','inventorySha256','sourceRecipeSha256','sourceCoreCommit','providers'}
    if (set(summary)!=keys or type(summary['schemaVersion']) is not int or summary['schemaVersion']!=1
            or type(summary['architecture']) is not int or summary['architecture'] not in (0x8664,0xaa64)
            or admission.admission_sha256!=expected or summary['admissionSha256']!=expected
            or any(not digest(summary[key]) for key in ('admissionSha256','lockSha256','receiptSha256',
                'engineZipSha256','inventorySha256','sourceRecipeSha256'))
            or summary['sourceCoreCommit']!='bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'):
        raise ValueError('The source admission identity differs')
    providers=summary['providers']
    if (type(providers) is not tuple or len(providers)!=2 or any(
            set(item)!={'role','size','sha256'} or type(item['role']) is not int or item['role']!=index+1
            or type(item['size']) is not int or item['size']<=0 or not digest(item['sha256'])
            for index,item in enumerate(providers))):
        raise ValueError('The source admission providers differ')
    return tuple(int(expected[index:index+8],16) for index in range(0,64,8))


@dataclass(frozen=True)
class MsaaHitSourceV4(MsaaHitSourceV3):
    admission:'SourceMenuAdmission'
    admission_sha256:str

    def valid(self):
        try:
            return MsaaHitSourceV3.valid(self) and len(_admission_words_v4(self.admission,self.admission_sha256))==8
        except (ImportError,AttributeError,KeyError,TypeError,ValueError):return False


class SourceQualifiedIa2SdkAbi(Ia2SdkAbi):
    def matches_source(self,source):
        if type(source) is not MsaaHitSourceV4:return False
        def matches(value,expected):
            try:
                kind=type(value);interface=kind.__com_interface__
                return (issubclass(kind,C.c_void_p) and bool(C.cast(value,C.c_void_p).value)
                    and any(_iid(base,expected) for base in interface.__mro__))
            except (AttributeError,TypeError,ValueError):return False
        return source.valid() and matches(source.client,'client') and all(matches(value,'element')
            for value in (source.retained_file,source.fresh_file,source.fresh_target,
                source.retained_target,*source.negative_refs))


def worker_record_v4():
    record=worker_record_v3();record.pop('diagnosticComplete')
    record.update(workerSchemaVersion=4,pointCandidate=0,sourceBound=0)
    record.update({'admissionDigest'+str(index):0 for index in range(8)})
    return record

def run_source_qualified_ia2_point_v4(source,scope,sdk,platform,deadline):
    """One new live source-qualified point candidate; never sends input.

    51+N provider calls, 26 acquired refs and a separate owned VARIANT on the
    complete path. Deadline checks bound admission, not synchronous COM/Release.
    """
    record=worker_record_v4();refs=[];variant=None;token=0;initialized=False;finished=False
    expiry=deadline
    if type(source) is MsaaHitSourceV4 and source.valid() and type(deadline) in (int,float):
        expiry=min(deadline,source.action_deadline,source.captured_at+1.5)
    def budget():
        if type(expiry) not in (int,float) or not math.isfinite(expiry) or platform.clock()>=expiry:
            record['ia2Status']=2;raise _Stop()
    def check():
        budget()
        if not platform.guard():record['ia2Status']=3;raise _Stop()
        budget()
    def require(value,code=5):
        if not value:record['ia2Status']=code;raise _Stop()
    def call(key,pointer,*arguments):
        check();record[key+'Attempted']+=1
        hr=sdk.call(key,pointer,*arguments)
        if type(hr) is not int:raise TypeError()
        record[key+'Completed']+=1;record[key+'Hresult']=hr&0xffffffff
        check();require(hr==0,4)
    def out(key,pointer,*arguments):
        value=C.c_void_p()
        try:call(key,pointer,*arguments,C.byref(value))
        finally:
            if value.value:refs.append(value.value);record['referencesAcquired']+=1
        require(bool(value.value))
        return value.value
    def same(first,second):
        value=C.c_int32();call('compare',source.client,first,second,C.byref(value))
        require(value.value in (0,1),5)
        return value.value==1
    def scalars(pointer):
        unique=C.c_int32();window=C.c_void_p()
        call('unique_id',pointer,C.byref(unique))
        call('window_handle',pointer,C.byref(window));require(bool(window.value))
        check();domain=platform.window_domain(window.value,source,scope);check()
        require(type(domain) is int and domain==1,7)
        record['hwndDomainMask']|=1<<domain
        return unique.value,window.value
    def identity(accessible):
        service=out('service_query',accessible,C.byref(service_iid))
        ia2=out('ia2_query',service,C.byref(accessible_iid),C.byref(ia2_iid))
        values=scalars(ia2);record['ia2TupleCount']+=1
        record['uidZeroCount']+=int(values[0]==0);record['uidNegativeCount']+=int(values[0]<0)
        require(values[0]!=0,7)
        return ia2,values
    try:
        record['workerStage']=1
        require(type(source) is MsaaHitSourceV4 and source.valid())
        words=_admission_words_v4(source.admission,source.admission_sha256)
        record.update(sourceBound=1,**{'admissionDigest'+str(i):value for i,value in enumerate(words)})
        require(isinstance(scope,MsaaHitScope) and scope.valid())
        require(source.owner_chain[-1] in (scope.child_hwnd,source.document_hwnd))
        require(source.captured_at<=platform.clock())
        budget();hr=platform.initialize()
        if type(hr) is not int:raise TypeError()
        require(hr in (0,1),4);initialized=True;record['comInitialized']=1
        budget();require(platform.apartment());budget();record['workerMta']=1
        token=platform.enter_dpi();require(bool(token));record['dpiEntered']=1;budget()
        require(platform.physical_dpi());budget();record['physicalDpiVerified']=1
        check();record['processBefore']=1;record['workerStage']=2
        # These are source selection guards. Unlike canonical inequality, a
        # FALSE positive or colliding negative stops all subsequent reads.
        require(same(source.retained_file,source.fresh_file),7);record['fileUiPositive']=1
        require(same(source.fresh_target,source.retained_target),7);record['targetUiPositive']=1
        for negative in source.negative_refs:
            record['negativeCount']+=1;require(not same(source.fresh_target,negative),7)
            record['negativeRejected']+=1
        legacy_iid=sdk.Guid('{'+_IIDS['legacy']+'}');unknown_iid=sdk.Guid('{'+_IIDS['unknown']+'}')
        accessible_iid=sdk.Guid('{'+_IIDS['accessible']+'}')
        service_iid=sdk.Guid('{'+_IA2_METADATA[9][0]+'}');ia2_iid=sdk.Guid('{'+_IA2_METADATA[3]+'}')
        bindings=[];record['workerStage']=3
        for element in (source.retained_file,source.fresh_file,source.fresh_target,source.retained_target):
            pattern=out('pattern',element,10018,C.byref(legacy_iid))
            child=C.c_int32(-1);call('child_id',pattern,C.byref(child));require(child.value==0)
            record['selfCount']+=1
            accessible=out('accessible',pattern)
            canonical=out('accessible_query',accessible,C.byref(unknown_iid))
            kind=C.c_int32();call('control_type',element,C.byref(kind));require(kind.value==50011)
            ia2,values=identity(accessible)
            bindings.append((pattern,accessible,canonical,ia2,values));record['bindingCount']+=1
        original,fresh_file,fresh_target,retained_target=bindings
        record.update(fileTupleEqual=int(original[4]==fresh_file[4]),
            targetTupleEqual=int(fresh_target[4]==retained_target[4]),
            targetDifferentFilesTuple=int(all(target[4]!=file[4] for target in (fresh_target,retained_target)
                for file in (original,fresh_file))))
        require(all(record[key]==1 for key in ('fileTupleEqual','targetTupleEqual','targetDifferentFilesTuple')),7)
        record.update(filePairObserved=1,filePairEqual=int(original[2]==fresh_file[2]),workerStage=4)
        repeated=out('accessible',original[0]);repeat_identity=out('accessible_query',repeated,C.byref(unknown_iid))
        record.update(fileOriginalRepeatObserved=1,fileOriginalRepeatEqual=int(repeat_identity==original[2]),
            targetPairObserved=1,targetPairEqual=int(fresh_target[2]==retained_target[2]),
            targetDifferentFromFileObserved=1,
            targetDifferentFromFile=int(all(target[2]!=file[2] for target in (fresh_target,retained_target)
                for file in (original,fresh_file))),workerStage=5)
        require(record['fileOriginalRepeatEqual']==1,7)
        variant=sdk.Variant();record['variantAttempted']=1
        call('hit_test',original[1],scope.x,scope.y,C.byref(variant));record['variantType']=int(variant.vt)
        require(variant.vt==9 and bool(variant._.c_void_p))
        hit=out('query',C.c_void_p(variant._.c_void_p),C.byref(accessible_iid))
        hit_identity=out('accessible_query',hit,C.byref(unknown_iid))
        record.update(hitMatchesTargetObserved=1,hitMatchesTarget=int(hit_identity==fresh_target[2]))
        _,hit_values=identity(hit);record['workerStage']=6
        record.update(hitMatchesTargetsTuple=int(all(hit_values==target[4] for target in (fresh_target,retained_target))),
            hitDifferentFilesTuple=int(all(hit_values!=file[4] for file in (original,fresh_file))))
        require(record['hitMatchesTargetsTuple']==record['hitDifferentFilesTuple']==1,7)
        file_anchor=scalars(original[3]);target_anchor=scalars(fresh_target[3])
        record.update(tupleComparisonsObserved=1,fileTupleEqual=int(original[4]==fresh_file[4]),
            targetTupleEqual=int(fresh_target[4]==retained_target[4]),
            targetDifferentFilesTuple=int(all(target[4]!=file[4] for target in (fresh_target,retained_target)
                for file in (original,fresh_file))),
            hitMatchesTargetsTuple=int(all(hit_values==target[4] for target in (fresh_target,retained_target))),
            hitDifferentFilesTuple=int(all(hit_values!=file[4] for file in (original,fresh_file))),
            fileAnchorStable=int(file_anchor==original[4]),targetAnchorStable=int(target_anchor==fresh_target[4]))
        require(record['fileAnchorStable']==record['targetAnchorStable']==1,7)
        require(record['uidZeroCount']==0 and record['hwndDomainMask']==2,7)
        check();record['processAfter']=1;finished=True
    except _Stop:pass
    except BaseException:record.update(ia2Status=6,cleanupError=1)
    finally:
        cleanup_failed=False
        if variant is not None:
            try:
                hr=platform.clear_variant(variant)
                if type(hr) is not int:raise TypeError()
                record['variantCleanupHresult']=hr&0xffffffff;record['variantCleared']=int(hr==0)
                if hr!=0:cleanup_failed=True
            except BaseException:cleanup_failed=True
        for pointer in reversed(refs):
            try:
                result=sdk.call('release',C.c_void_p(pointer))
                if type(result) is not int or not 0<=result<=0xffffffff:raise TypeError()
                record['referencesReleased']+=1
            except BaseException:cleanup_failed=True
        refs.clear()
        if token:
            try:record['dpiRestored']=int(bool(platform.leave_dpi(token)))
            except BaseException:cleanup_failed=True
            if not record['dpiRestored']:cleanup_failed=True
        if initialized:
            try:platform.uninitialize();record['comUninitialized']=1
            except BaseException:cleanup_failed=True
        if cleanup_failed:record.update(cleanupError=1,ia2Status=8)
        clean=(not record['cleanupError'] and record['referencesAcquired']==record['referencesReleased']
            and (not record['variantAttempted'] or record['variantCleared'])
            and (not initialized or record['comUninitialized']) and (not token or record['dpiRestored']))
        record['workerCleanup']=int(clean)
        try:
            if platform.clock()>=expiry:record['ia2Status']=2
            elif finished and clean:
                if not platform.guard():record['ia2Status']=3
                elif platform.clock()>=expiry:record['ia2Status']=2
                else:record.update(ia2Status=1,workerStage=7,pointCandidate=1)
        except BaseException:record.update(ia2Status=6,cleanupError=1,workerCleanup=0)
        record['localKnown']=record['localMatch']=0
    return record



def _valid_v4_worker(result,negative_count,expected_admission_sha256):
    expected=worker_record_v4()
    if (type(result) is not dict or result.keys()!=expected.keys()
            or type(negative_count) is not int or not 2<=negative_count<=16
            or type(expected_admission_sha256) is not str or len(expected_admission_sha256)!=64
            or any(c not in '0123456789abcdef' for c in expected_admission_sha256)
            or any(type(value) is not int or not 0<=value<=0xffffffff for value in result.values())
            or result['workerSchemaVersion']!=4 or result['localKnown'] or result['localMatch']
            or result['pointCandidate'] not in (0,1) or result['sourceBound']!=1
            or tuple(result['admissionDigest'+str(index)] for index in range(8))!=tuple(
                int(expected_admission_sha256[index:index+8],16) for index in range(0,64,8))):return False
    counts=dict(pattern=4,child_id=4,accessible=5,accessible_query=6,control_type=4,
        hit_test=1,query=1,compare=2+negative_count,service_query=5,ia2_query=5,
        unique_id=7,window_handle=7)
    booleans=('workerCleanup','workerMta','comInitialized','comUninitialized','dpiEntered',
        'dpiRestored','physicalDpiVerified','processBefore','processAfter','variantAttempted',
        'variantCleared','cleanupError','fileUiPositive','targetUiPositive','filePairObserved',
        'fileOriginalRepeatObserved','targetPairObserved','targetDifferentFromFileObserved',
        'hitMatchesTargetObserved','tupleComparisonsObserved','filePairEqual','fileOriginalRepeatEqual',
        'targetPairEqual','targetDifferentFromFile','hitMatchesTarget','fileTupleEqual',
        'targetTupleEqual','targetDifferentFilesTuple','hitMatchesTargetsTuple','hitDifferentFilesTuple',
        'fileAnchorStable','targetAnchorStable')
    if (any(result[key] not in (0,1) for key in booleans)
            or not 0<=result['ia2Status']<=8 or not 0<=result['workerStage']<=7
            or not result['referencesReleased']<=result['referencesAcquired']<=26
            or not result['negativeRejected']<=result['negativeCount']<=negative_count
            or not result['selfCount']<=4 or not result['bindingCount']<=4
            or not result['uidZeroCount']+result['uidNegativeCount']<=result['ia2TupleCount']<=5
            or result['hwndDomainMask']&~62 or result['variantType']>65535
            or any(not result[name+'Completed']<=result[name+'Attempted']<=count for name,count in counts.items())
            or result['workerCleanup'] and (result['cleanupError']
                or result['referencesAcquired']!=result['referencesReleased']
                or result['variantAttempted']!=result['variantCleared']
                or result['comInitialized']!=result['comUninitialized']
                or result['dpiEntered']!=result['dpiRestored'])):return False
    if not result['pointCandidate']:return True
    facts=('workerCleanup','workerMta','comInitialized','comUninitialized','dpiEntered',
        'dpiRestored','physicalDpiVerified','processBefore','processAfter','variantAttempted',
        'variantCleared','fileUiPositive','targetUiPositive','filePairObserved',
        'fileOriginalRepeatObserved','targetPairObserved','targetDifferentFromFileObserved',
        'hitMatchesTargetObserved','tupleComparisonsObserved','fileOriginalRepeatEqual',
        'fileTupleEqual','targetTupleEqual','targetDifferentFilesTuple','hitMatchesTargetsTuple',
        'hitDifferentFilesTuple','fileAnchorStable','targetAnchorStable')
    return (all(result[key]==1 for key in facts) and result['ia2Status']==1
        and result['workerStage']==7 and result['referencesAcquired']==result['referencesReleased']==26
        and result['variantType']==9 and result['variantCleanupHresult']==result['cleanupError']==0
        and result['bindingCount']==result['selfCount']==4 and result['ia2TupleCount']==5
        and result['negativeCount']==result['negativeRejected']==negative_count
        and result['uidZeroCount']==0 and result['hwndDomainMask']==2
        and all(result[name+'Attempted']==result[name+'Completed']==count
            and result[name+'Hresult']==0 for name,count in counts.items()))


def _record_v4(scope,synthetic):
    boundary=_record(scope,synthetic,profile_version=2)
    for name in worker_record_v2():boundary.pop(name,None)
    boundary.update(schemaVersion=4,diagnosticOnly=0)
    return dict(worker_record_v4(),**boundary)


class SourceQualifiedIa2PointLease(MsaaHitLease):
    def __init__(self,source,scope,sdk,deadline,kernel):
        super().__init__(source,scope,sdk,deadline,kernel,profile_version=2)
        self.record=_record_v4(scope,getattr(kernel,'synthetic',False))
        self._profile_version=4;self._status_key='ia2Status';self.action_deadline=deadline
        self._admission=None;self._admission_sha256=None
        if type(source) is MsaaHitSourceV4 and source.valid() and type(deadline) in (int,float):
            self.deadline=min(deadline,source.captured_at+1.5)
            self._admission=source.admission;self._admission_sha256=source.admission.admission_sha256

    def valid(self):
        return (type(self.source) is MsaaHitSourceV4 and self.source.valid()
            and self.source.admission is self._admission and self.source.admission_sha256==self._admission_sha256
            and isinstance(self.scope,MsaaHitScope) and self.scope.valid()
            and self.source.action_deadline==self.action_deadline
            and self.source.captured_at<=self.kernel.clock()
            and type(self.action_deadline) in (int,float) and math.isfinite(self.action_deadline)
            and self.kernel.clock()<self.deadline<=self.kernel.clock()+1.5
            and self.action_deadline<=self.kernel.clock()+5)

    def _run(self):
        try:
            result=self.runner()
            if _valid_v4_worker(result,len(self.source.negative_refs),self._admission_sha256):self.worker=dict(result)
            else:self._worker_exception=True
        except BaseException:self._worker_exception=True
        return 0

    def _collect(self,deadline,retiring):
        result=super()._collect(deadline,retiring)
        if (result['stageCode']!=13 or result['pending'] or result['workerException']
                or not result['workerCleanup'] or result['localKnown'] or result['localMatch']):
            self.record['pointCandidate']=0
        self.record['localKnown']=self.record['localMatch']=0
        return dict(self.record)

    def _unknown(self):
        self.record['pointCandidate']=0
        return super()._unknown()


def begin_source_qualified_ia2_point(source,scope,sdk,deadline,*,native_enabled=False,_kernel=None):
    lease=SourceQualifiedIa2PointLease(source,scope,sdk,deadline,_kernel)
    synthetic=_kernel is not None and getattr(_kernel,'synthetic',False) is True
    if not synthetic and (native_enabled is not True or not NATIVE_LAUNCH_ENABLED):
        lease.record['stageCode']=1;return lease
    if type(source) is not MsaaHitSourceV4 or not source.valid():
        lease.record['stageCode']=3;return lease
    if not _reserve(lease):lease.record['stageCode']=2;return lease
    if not synthetic:
        try:
            _kernel=SourceQualifiedIa2WindowsKernel()
            if (type(sdk) is not SourceQualifiedIa2SdkAbi or sdk.function_factory is not C.WINFUNCTYPE
                    or not sdk.matches_source(source)):raise ValueError('Native source-qualified IA2 SDK binder required')
            lease.kernel=_kernel
        except BaseException:lease.record['stageCode']=3;lease._clear();return lease
    if not lease.valid():lease.record['stageCode']=3;lease._clear();return lease
    try:
        if not _kernel.apartment():lease.record['stageCode']=4;lease._release_unstarted();return lease
        lease.record['stageCode']=5
        for handle,pid,birth in ((source.shell_handle,scope.shell_pid,scope.shell_birth),
                (source.engine_handle,scope.engine_pid,scope.engine_birth)):
            duplicate=_kernel.duplicate(handle,pid,birth);lease.process_handles.append((duplicate,pid,birth))
            adopt=getattr(_kernel,'adopt_duplicate',None)
            if adopt is not None:adopt(duplicate)
            if not _kernel.check_process(duplicate,pid,birth):raise _Stop()
        if _kernel.clock()>=lease.deadline:
            lease.record['stageCode']=11;lease._release_unstarted();return lease
        lease.record.update(stageCode=6,nativeAttempted=1)
        lease.thread,lease.tid,lease.birth=_kernel.start(lease._run)
        if not lease.thread or not lease.tid or not lease.birth:lease.record['pending']=1
    except BaseException:
        if lease.record['nativeAttempted'] and getattr(_kernel,'start_uncertain',False):lease.record['pending']=1
        else:lease._release_unstarted()
    return lease


class SourceQualifiedIa2WindowsKernel(Ia2WindowsKernel):
    def guard(self):
        if not WindowsKernel.guard(self):return False
        source,scope=getattr(self,'_source_qualified_source',None),getattr(self,'_source_qualified_scope',None)
        if type(source) is not MsaaHitSourceV4 or not source.valid() or not scope.valid():return False
        u=self.user;doc=source.document_hwnd;popup=source.popup_hwnd
        windows=(doc,scope.parent_hwnd,scope.child_hwnd,*source.owner_chain)
        if not all(u.IsWindow(hwnd) for hwnd in windows):return False
        if self._window_process(doc)[1]!=scope.shell_pid or self._window_process(scope.parent_hwnd)[1]!=scope.shell_pid:return False
        if any(self._window_process(hwnd)!=(source.popup_thread,scope.engine_pid)
                for hwnd in (scope.child_hwnd,popup)):return False
        if any(self._window_process(hwnd)[1]!=scope.engine_pid for hwnd in source.owner_chain[:-1]):return False
        if int(u.GetParent(scope.child_hwnd) or 0)!=scope.parent_hwnd:return False
        if int(u.GetAncestor(scope.child_hwnd,2) or 0)!=doc:return False
        if not all(u.IsWindowVisible(hwnd) and u.IsWindowEnabled(hwnd) for hwnd in (doc,popup)) or u.IsIconic(doc):return False
        for first,second in zip(source.owner_chain,source.owner_chain[1:]):
            if int(u.GetWindow(first,4) or 0)!=second:return False
        if int(u.GetForegroundWindow() or 0) not in (doc,popup):return False
        if int(u.WindowFromPhysicalPoint(self.Point(scope.x,scope.y)) or 0)!=popup:return False
        gui=self.Gui();gui.cbSize=C.sizeof(gui)
        if not u.GetGUIThreadInfo(source.popup_thread,C.byref(gui)):return False
        if (not gui.focus or self._window_process(gui.focus)[1]!=scope.engine_pid
                or int(u.GetAncestor(gui.focus,2) or 0) not in (doc,popup)
                or int(gui.capture or 0) not in (0,scope.child_hwnd,popup)
                or int(gui.menu or 0) not in (0,scope.child_hwnd,popup)):return False
        return WindowsKernel.guard(self)

    def worker(self,source,scope,sdk,deadline):
        if type(source) is not MsaaHitSourceV4:raise ValueError('Source-qualified IA2 source required')
        self._source_qualified_source,self._source_qualified_scope=source,scope
        try:return run_source_qualified_ia2_point_v4(source,scope,sdk,self,deadline)
        finally:
            # The original lease owns borrowed refs through native retirement.
            # This finished worker must not retain another source/probe cycle or
            # clear a newer context that replaced its own pair.
            if (self._source_qualified_source is source and self._source_qualified_scope is scope):
                self._source_qualified_source=self._source_qualified_scope=None
