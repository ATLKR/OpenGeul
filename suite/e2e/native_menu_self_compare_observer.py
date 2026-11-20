"""Non-accepting native BOOL observation after a returned retained-self FALSE."""
import ctypes as C
import math
from types import SimpleNamespace

def collect(probe,left,right):
    # Bits: 1 original owner verified, 2 fresh timeout verified, 4 raw HRESULT,
    # 8 S_OK out BOOL, 16 original owner verified after the extra call.
    value=dict(schemaVersion=1,diagnosticOnly=1,acceptanceEligible=0,statusCode=0,
        phaseCode=0,observedMask=0,nativeAttempted=0,nativeReturned=0,
        hresultBits=0,outBoolBits=0)
    missing=object();saved=None
    class Halt(Exception):pass
    def require(condition):
        if not condition:raise Halt()
    try:
        # Normal/default runs have no creator/retained-HANDLE witness. Do not
        # manufacture those prerequisites or initialize an unused COM provider.
        if getattr(probe,'_native_point_profile',False) is not True:return value
        scope=getattr(probe,'_identity_scope',None);context=getattr(probe,'_menu_classification_context',None)
        refs=getattr(probe,'_identity_refs',None);handles=getattr(probe,'_point_source',None)
        creator=getattr(probe,'_provider_creator',None);client=getattr(probe,'provider_client',None)
        uia=getattr(probe,'_uia',None);interop=getattr(probe,'interop',None)
        require(type(scope) is dict and type(context) is tuple and len(context)==2
            and type(context[0]) is dict and callable(context[1]) and type(refs) is dict
            and 1<=len(refs)<=21 and left is right and any(right is ref for ref in refs.values())
            and type(handles) is dict and set(handles)=={'shellHandle','engineHandle'}
            and type(creator) is dict and set(creator)=={'threadId','mta'}
            and type(creator['threadId']) is int and creator['threadId']>0 and creator['mta'] is True
            and client is not None and uia is not None and uia.iuia is client and type(interop) is dict
            and not getattr(probe,'_provider_closed',False)
            and getattr(probe,'_diagnostic_sink',None) is None)
        comparison=interop.get('lastComparison');call=interop.get('lastCall');rows=interop.get('lastRoleComparisons')
        require(type(comparison) is dict and comparison.get('callReturned') is True
            and comparison.get('areSameObserved') is True and comparison.get('areSame') is False
            and comparison.get('returnTypeCode') in (1,2) and type(call) is dict
            and call.get('apiCode')==5 and call.get('calleeEntered') is True
            and call.get('callCompleted') is True and call.get('failed') is False and call.get('phaseCode')==4
            and type(rows) is list and 1<=len(rows)<=21 and type(rows[-1]) is dict
            and rows[-1].get('areSame') is False and rows[-1].get('samePythonObject') is True)
        binding=scope.get('binding');deadline=probe.deadline
        require(type(binding) is dict and set(binding)=={'document','parent','child','officePid'}
            and all(type(n) is int and 0<n<1<<64 for n in binding.values())
            and all(type(handles[k]) is int and 0<handles[k]<1<<64 for k in handles)
            and scope.get('version')==1 and all(type(scope.get(k)) is int and scope[k]>0 for k in
                ('shellPid','shellCreationTime','officeCreationTime'))
            and scope['shellPid']!=binding['officePid'] and scope['officeCreationTime']>=scope['shellCreationTime']
            and all(type(scope.get(k)) in (int,float) and math.isfinite(scope[k]) for k in ('startedAt','deadline'))
            and scope['startedAt']<deadline==scope['deadline']<=scope['startedAt']+5)
        keys=('version','binding','shellPid','shellCreationTime','officeCreationTime','startedAt','deadline')
        require(set(context[0])==set(keys) and all(context[0][k]==scope.get(k) for k in keys))
        anchor={k:(dict(binding) if k=='binding' else scope[k]) for k in keys}
        original_handles=dict(handles);original_creator=dict(creator);original_refs=tuple(refs.items())
        names=('_diagnostic_sink','_observed_call','_last_call_exception','provider_timeout_verified','last_foreground_snapshot')
        saved=[(name,vars(probe).get(name,missing)) for name in names]
        sink={};probe._diagnostic_sink=sink;probe._observed_call=None
        def budget():
            now=probe.clock()
            require(type(now) in (int,float) and math.isfinite(now)
                and probe.deadline==deadline and scope['startedAt']<=now<deadline
                and not probe._provider_pending() and not getattr(probe,'_provider_closed',False)
                and probe.provider_client is client and probe._uia is uia and uia.iuia is client
                and probe.interop is interop and probe._diagnostic_sink is sink
                and probe._identity_scope is scope and all(scope.get(k)==anchor[k] for k in keys)
                and probe._menu_classification_context is context and context[1] is probe._menu_classification_context[1]
                and all(context[0].get(k)==anchor[k] for k in keys)
                and probe._point_source is handles and handles==original_handles
                and probe._provider_creator is creator and creator==original_creator
                and probe._identity_refs is refs and len(refs)==len(original_refs)
                and all(refs.get(k) is old for k,old in original_refs))
            return now
        def owner():
            budget();require(probe._require_provider_creator()==dict(original_creator,sameThread=True));budget()
            context[1]();budget()
            shell=probe.process_snapshot(SimpleNamespace(_handle=handles['shellHandle']));budget()
            engine=probe.engine_snapshot(handles['engineHandle']);budget()
            for row,pid,birth,handle in (
                    (shell,scope['shellPid'],scope['shellCreationTime'],handles['shellHandle']),
                    (engine,binding['officePid'],scope['officeCreationTime'],handles['engineHandle'])):
                require(type(row) is dict and row.get('pid')==pid and row.get('creationTime')==birth
                    and row.get('handleValue')==handle and row.get('waitResult')==258)
            attachment=probe.attachment_snapshot(binding);budget()
            child=probe.window_snapshot(binding['child']);budget()
            require(type(attachment) is dict and attachment.get('valid') is True
                and type(child) is dict and (child.get('hwnd'),child.get('pid'),child.get('rootHwnd'))==
                    (binding['child'],binding['officePid'],binding['document'])
                and child.get('visible') is child.get('enabled') is True
                and type(child.get('threadId')) is int and child['threadId']>0
                and attachment['windows']['child']['threadId']==child['threadId'])
            foreground=probe.foreground();budget();require(foreground==binding['document'])
            return (shell,engine,attachment,child,foreground)
        value['phaseCode']=1;before=owner();value['observedMask']|=1
        from native_menu_msaa_hit import SdkAbi,_iid
        from comtypes import GUID,HRESULT
        from comtypes.automation import VARIANT
        library=probe._uia_library;legacy=library.IUIAutomationLegacyIAccessiblePattern
        method=next(item for item in vars(legacy)['_methods_'] if item.name=='GetIAccessible')
        accessible=method.argtypes[0]._type_.__com_interface__
        factory=getattr(C,'WINFUNCTYPE',None);require(factory is not None)
        sdk=SdkAbi(client_interface=library.IUIAutomation,element_interface=library.IUIAutomationElement,
            legacy_interface=legacy,accessible_interface=accessible,guid_type=GUID,hresult_type=HRESULT,
            variant_type=VARIANT,function_factory=factory)
        for pointer,expected in ((client,'client'),(left,'element'),(right,'element')):
            kind=type(pointer);interface=getattr(kind,'__com_interface__',None)
            require(issubclass(kind,C.c_void_p) and isinstance(interface,type)
                and any(_iid(base,expected) for base in interface.__mro__) and bool(C.cast(pointer,C.c_void_p).value))
        value['phaseCode']=2
        def native():
            require(owner()==before);now=budget()
            observed=probe._observed_call;timeout=observed.get('providerBudget') if type(observed) is dict else None
            require(type(timeout) is dict and timeout.get('setupComplete')==1
                and timeout.get('observedMask')==15 and timeout.get('verifiedMask')==3
                and type(timeout.get('requestedMs')) is int and 1<=timeout['requestedMs']<=1250
                and timeout.get('connectionReadbackMs')==timeout['requestedMs']==timeout.get('transactionReadbackMs')
                and 2*timeout['requestedMs']<(deadline-now)*1000 and probe.provider_timeout_verified is True)
            value['observedMask']|=2;out=C.c_int32()
            value['phaseCode']=3;value['nativeAttempted']=1
            hr=sdk.call('compare',client,left,right,C.byref(out))
            require(type(hr) is int and -(1<<31)<=hr<1<<31)
            value.update(nativeReturned=1,hresultBits=hr&0xffffffff);value['observedMask']|=4
            if hr==0:value.update(outBoolBits=out.value&0xffffffff);value['observedMask']|=8
            return hr
        # Reuse the original timeout/entry/return wrapper without its lazy
        # _ensure_provider path: observation may never create another client.
        probe._observed_call=probe._call_record(5)
        probe._call(native)
        value['phaseCode']=4;require(owner()==before);budget()
        value['observedMask']|=16;value.update(statusCode=1,phaseCode=5)
    except BaseException:
        value['statusCode']=2
    finally:
        if saved is not None:
            for name,old in saved:
                if old is missing:vars(probe).pop(name,None)
                else:setattr(probe,name,old)
    return value
