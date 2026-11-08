"""Synthetic mapping tests; no Windows process, DLL, hook, or input is started."""
import ctypes as C
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import struct
import sys

import unittest


def parameters(name, values):
    def decorate(function):
        function.case_values = values
        return function
    return decorate


raises = unittest.TestCase().assertRaises

BASE = Path(__file__).resolve().parents[2]
FRONT = BASE / 'suite' / 'e2e'
sys.path.insert(0, str(FRONT))
from writer_server_observer_lifecycle import OriginalWriterBudget


def mod():
    path = BASE / 'suite' / 'e2e' / 'writer_server_observer_capture.py'
    assert path.is_file(), 'Writer capture implementation is missing'
    spec = importlib.util.spec_from_file_location('candidate_writer_capture', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Clock:
    frequency = 10
    value = 100
    def read(self):
        return self.value


@dataclass(frozen=True, repr=False)
class Witness:
    handle: int = 301
    pid: int = 401
    birth: int = 501


@dataclass(frozen=True, repr=False)
class ExitEvidence:
    original_witness: object
    identity_matches: bool = True
    engine_exit_observed: bool = True
    exit_code_observed: bool = True
    members_exited: bool = True
    job_empty: bool = True
    within_deadline: bool = True
    observed_qpc: object = 390
    remote_retired: bool = True
    error_code: int = 0


class MemoryBackend:
    """Same port methods as NativeBackend, replacing only Windows/Interlocked."""
    atomic_accessors_attested = True
    def __init__(self):
        self.buffer = C.create_string_buffer(131328)
        self.base = C.addressof(self.buffer)
        self.collided = False
        self.process_birth = 501
        self.controller_birth = 801
        self.before_cas = None
        self.commit_changed = False
        self.fail_unmap = self.fail_close = self.fail_library = False
        self.created = self.mapped = self.unmapped = self.closed = self.freed = 0
        self.opened_pid = 0
    def controller_identity(self):
        return 701, self.controller_birth
    def create_mapping(self, name, size):
        assert size == 131328 and name.startswith('Local\\OpenGeulWriterServerObserver-')
        self.created += 1
        return 901, self.collided
    def map_view(self, handle, size):
        assert handle == 901 and size == 131328
        self.mapped += 1
        return self.base
    def read_word(self, address):
        value = struct.unpack_from('<I', self.buffer, address-self.base)[0]
        if self.commit_changed and address == self.base+256:
            struct.pack_into('<I', self.buffer, 256, value+1)
            self.commit_changed = False
        return value
    def read_quad(self, address):
        return struct.unpack_from('<Q', self.buffer, address-self.base)[0]
    def publish_word(self, address, value):
        struct.pack_into('<I', self.buffer, address-self.base, value)
    def compare_exchange_word(self, address, exchange, comparand):
        if self.before_cas is not None:
            callback, self.before_cas = self.before_cas, None
            callback(address, exchange, comparand)
        old = self.read_word(address)
        if old == comparand:
            self.publish_word(address, exchange)
        return old
    def process_snapshot(self, handle):
        assert handle == 301
        return {'pid':401, 'creationTime':self.process_birth, 'waitResult':258, 'exitCode':259}
    def window_binding(self, hwnd):
        assert hwnd == 601
        return 401, 611
    def unmap_view(self, view):
        assert view == self.base
        self.unmapped += 1
        return not self.fail_unmap
    def close_handle(self, handle):
        assert handle == 901
        self.closed += 1
        return not self.fail_close
    def release_library(self):
        self.freed += 1
        return not self.fail_library


def prepared(mod):
    clock, native, witness = Clock(), MemoryBackend(), Witness()
    budget = OriginalWriterBudget.start(clock)
    descriptor = mod.Descriptor(701, 801, 0x123456789abcdef0)
    capture = mod.PreparedCapture(budget, descriptor, native)
    capture.create()
    owner = mod.OriginalOwnerBinding(witness, 600, 601, 611)
    return capture, native, clock, witness, owner


def ready(native):
    # Independently hand-checked wire offsets: sessionReady/rootReady/control flags.
    for offset, value in ((156,2),(160,2),(164,1),(168,1),(196,2)):
        struct.pack_into('<I',native.buffer,offset,value)
    struct.pack_into('<q',native.buffer,200,101)
    struct.pack_into('<q',native.buffer,208,102)


def row(native, slot, *, commit=None, phase=10, datum=0, qpc=None,
        kind=2, scope=1, parent=0, depth=1, event=None, reserved=0):
    event = slot+1 if event is None else event
    commit = slot+1 if commit is None else commit
    qpc = 105+slot if qpc is None else qpc
    struct.pack_into('<IIIIQQqIIIIQ',native.buffer,256+64*slot,
        commit,kind,phase,datum,scope,parent,qpc,depth,1,event,reserved,0)


def valid_rows(native):
    ready(native)
    struct.pack_into('<II',native.buffer,136,6,6)
    for slot,(phase,datum) in enumerate(((10,0),(1,0),(2,3),(3,1),(5,1),(11,0))):
        row(native,slot,phase=phase,datum=datum)


def armed(mod):
    capture,native,clock,witness,owner = prepared(mod)
    capture.arm_once(owner,lambda: True)
    return capture,native,clock,witness,owner


def test_private_descriptor_canonical_roundtrip_and_redaction(mod):
    value = '1:701:801:123456789abcdef0:131328:OpenGeulWriterServerObserver'
    descriptor = mod.Descriptor.parse(value)
    assert descriptor.environment_value() == value
    assert '701' not in repr(descriptor) and '12345678' not in repr(descriptor)
    assert not hasattr(descriptor,'start_qpc')


@parameters('value',[
    '', '1:0:801:123456789abcdef0:131328:OpenGeulWriterServerObserver',
    '1:0701:801:123456789abcdef0:131328:OpenGeulWriterServerObserver',
    '1:701:801:0000000000000000:131328:OpenGeulWriterServerObserver',
    '1:701:801:123456789ABCDEF0:131328:OpenGeulWriterServerObserver',
    '1:701:801:123456789abcdef0:131328:OpenGeulWriterServerObserver:100:400',
    '1:4294967296:801:123456789abcdef0:131328:OpenGeulWriterServerObserver'])
def test_descriptor_rejects_noncanonical_or_runtime_fields_without_echo(mod,value):
    with raises(mod.CaptureError) as caught:
        mod.Descriptor.parse(value)
    assert value not in str(caught.exception) if value else True


def test_layout_matches_every_backend_field(mod):
    schema=json.loads((BASE/'suite/engine-build/writer-server-observer-diagnostic/wire-schema.json').read_text())
    layout=mod.abi_layout()
    for name in ('identity','control','row'):
        assert layout[name]['bytes']==schema[name]['bytes']
        assert layout[name]['alignment']==schema[name]['alignment']
        assert layout[name]['offsets']==schema[name]['offsets']
    assert layout['mappingBytes']==131328


def test_fresh_mapping_arm_once_private_header_and_single_budget(mod):
    capture,native,clock,witness,owner=prepared(mod)
    assert struct.unpack_from('<qqqq',native.buffer,64)==(100,400,10,350)
    calls=[]
    capture.arm_once(owner,lambda:calls.append(1) or True)
    assert len(calls)>=2 and struct.unpack_from('<I',native.buffer,128)[0]==2
    with raises(mod.CaptureError):capture.arm_once(owner,lambda:True)
    assert '401' not in repr(capture) and '501' not in repr(owner)


def test_collision_rejected_and_partial_resources_released(mod):
    clock,native=Clock(),MemoryBackend();native.collided=True
    capture=mod.PreparedCapture(OriginalWriterBudget.start(clock),mod.Descriptor(701,801,2),native)
    with raises(mod.CaptureError):capture.create()
    assert native.mapped==0 and native.closed==1 and native.freed==1


@parameters('change',['birth','verify','cutoff','frequency','controller'])
def test_arm_rejects_wrong_generation_deadline_clock_or_owner(mod,change):
    capture,native,clock,witness,owner=prepared(mod)
    verify=lambda:True
    if change=='birth':native.process_birth=502
    if change=='verify':verify=lambda:False
    if change=='cutoff':clock.value=350
    if change=='frequency':clock.frequency=11
    if change=='controller':native.controller_birth=802
    with raises(mod.CaptureError):capture.arm_once(owner,verify)
    assert struct.unpack_from('<I',native.buffer,128)[0]!=2


def test_disable_wins_while_arming_and_cannot_reenable(mod):
    capture,native,clock,witness,owner=prepared(mod)
    calls=0
    def verify():
        nonlocal calls
        calls+=1
        if calls==2:capture.disable()
        return True
    with raises(mod.CaptureError):capture.arm_once(owner,verify)
    assert struct.unpack_from('<I',native.buffer,128)[0]==3
    with raises(mod.CaptureError):capture.arm_once(owner,lambda:True)


def test_disable_cas_preserves_concurrent_active_increment(mod):
    capture,native,clock,witness,owner=armed(mod)
    struct.pack_into('<I',native.buffer,132,1)
    def concurrent_enter(address,exchange,comparand):
        if address==native.base+132:
            struct.pack_into('<I',native.buffer,132,2)
        else:
            native.before_cas=concurrent_enter
    native.before_cas=concurrent_enter
    result=capture.disable()
    assert result['admissionClosed'] is True and result['captureGateClosed'] is True
    assert struct.unpack_from('<I',native.buffer,132)[0]==0x80000002


def test_snapshot_decodes_closed_numeric_rows_without_identity(mod):
    capture,native,clock,witness,owner=armed(mod);valid_rows(native);capture.disable()
    result=capture.snapshot()
    assert result['captureIncomplete'] is False and len(result['rows'])==6
    assert result['wholeOriginalIntervalCovered'] is False
    assert result['originalClientAttributionUnknown'] is True
    assert result['normalAcceptance']==0 and result['fullEngineQualified']==0
    encoded=json.dumps(result)
    for private in ('ownerPid','ownerBirth','ownerHwnd','controllerPid','nonce','handle'):
        assert private not in encoded


def test_snapshot_preserves_later_commits_after_hole(mod):
    capture,native,clock,witness,owner=armed(mod);ready(native)
    struct.pack_into('<II',native.buffer,136,3,2)
    row(native,0,commit=0);row(native,1,phase=10);row(native,2,phase=11)
    capture.disable();result=capture.snapshot()
    assert result['captureIncomplete'] is True
    assert result['uncommittedOrdinals']==[1]
    assert [r['eventOrdinal'] for r in result['rows']]==[2,3]


@parameters('change',['unknown_kind','unknown_phase','unknown_datum','reserved',
    'event','commit','qpc_before','qpc_cutoff','depth','parent','order','header_reserved',
    'unknown_header_enum','overflow','partial','active'])
def test_snapshot_marks_malformed_or_partial_capture_incomplete(mod,change):
    capture,native,clock,witness,owner=armed(mod);valid_rows(native)
    if change=='unknown_kind':struct.pack_into('<I',native.buffer,260,99)
    if change=='unknown_phase':struct.pack_into('<I',native.buffer,264,99)
    if change=='unknown_datum':struct.pack_into('<I',native.buffer,268,99)
    if change=='reserved':struct.pack_into('<I',native.buffer,308,1)
    if change=='event':struct.pack_into('<I',native.buffer,304,2)
    if change=='commit':struct.pack_into('<I',native.buffer,256,2)
    if change=='qpc_before':struct.pack_into('<q',native.buffer,288,99)
    if change=='qpc_cutoff':struct.pack_into('<q',native.buffer,288,350)
    if change=='depth':struct.pack_into('<I',native.buffer,296,33)
    if change=='parent':struct.pack_into('<Q',native.buffer,280,1)
    if change=='order':struct.pack_into('<q',native.buffer,352,104)
    if change=='header_reserved':struct.pack_into('<I',native.buffer,216,1)
    if change=='unknown_header_enum':struct.pack_into('<I',native.buffer,156,99)
    if change=='overflow':struct.pack_into('<I',native.buffer,148,1)
    if change=='partial':native.commit_changed=True
    if change=='active':struct.pack_into('<I',native.buffer,132,1)
    capture.disable();result=capture.snapshot()
    assert result['captureIncomplete'] is True and result['decoderErrors']


def test_snapshot_cannot_treat_late_or_unclosed_as_complete(mod):
    capture,native,clock,witness,owner=armed(mod);valid_rows(native)
    assert capture.snapshot()['captureIncomplete'] is True
    capture.disable();clock.value=400
    assert capture.snapshot()['captureIncomplete'] is True


@parameters('change',['different_object','wrong_generation','late','not_signaled','missing'])
def test_retirement_requires_same_original_witness_and_native_exit_by_deadline(mod,change):
    capture,native,clock,witness,owner=armed(mod);capture.disable()
    kwargs={}
    supplied=witness
    if change=='different_object':supplied=Witness()
    if change=='wrong_generation':kwargs['identity_matches']=False
    if change=='late':kwargs['observed_qpc']=400
    if change=='not_signaled':kwargs['engine_exit_observed']=False
    evidence=None if change=='missing' else ExitEvidence(supplied,**kwargs)
    assert capture.join_retirement(witness,evidence)['remoteRetired']==0


def test_retirement_proof_and_local_release_are_independent(mod):
    capture,native,clock,witness,owner=armed(mod);capture.disable()
    assert capture.join_retirement(witness,ExitEvidence(witness))['remoteRetired']==1
    cleanup=capture.close_local()
    assert cleanup['unmapSucceeded'] is True and cleanup['mappingHandleClosed'] is True
    assert cleanup['libraryReleased'] is True
    assert native.opened_pid==0


def test_cleanup_records_all_failures_without_raising_or_erasing_primary(mod):
    capture,native,clock,witness,owner=armed(mod);capture.disable()
    native.fail_unmap=native.fail_close=native.fail_library=True
    primary=RuntimeError('synthetic-primary')
    result=capture.close_local(primary=primary)
    assert result['cleanupErrors']==[1,2,3] and result['primaryPreserved'] is True
    assert capture.close_local(primary=primary)==result
    assert (native.unmapped,native.closed,native.freed)==(1,1,1)


def test_no_attribution_or_success_synthesized_from_unobserved_rows(mod):
    capture,native,clock,witness,owner=armed(mod);capture.disable()
    result=capture.snapshot()
    assert result['captureIncomplete'] is True and result['rows']==[]
    assert result['sessionReadyObserved']==0 and result['rootBoundObserved']==0
    assert capture.join_retirement(witness,None)['remoteRetired']==0


def test_header_must_be_revalidated_before_armed_publication(mod):
    capture,native,clock,witness,owner=prepared(mod)
    struct.pack_into('<Q',native.buffer,40,2)
    with raises(mod.CaptureError):capture.arm_once(owner,lambda:True)
    assert struct.unpack_from('<I',native.buffer,128)[0]==3


def test_budget_cannot_be_rebased_after_create(mod):
    capture,native,clock,witness,owner=prepared(mod)
    object.__setattr__(capture._budget,'deadline_qpc',390)
    object.__setattr__(capture._budget,'cutoff_qpc',340)
    with raises(mod.CaptureError):capture.arm_once(owner,lambda:True)


def test_scope_nesting_rejects_nonexistent_parent(mod):
    capture,native,clock,witness,owner=armed(mod);ready(native)
    struct.pack_into('<II',native.buffer,136,2,2)
    row(native,0,scope=2,parent=1,depth=2)
    row(native,1,scope=2,parent=1,depth=2,phase=11)
    capture.disable()
    assert capture.snapshot()['captureIncomplete'] is True


def test_local_release_first_closes_admission_and_preserves_primary(mod):
    capture,native,clock,witness,owner=armed(mod)
    result=capture.close_local(primary=RuntimeError('synthetic-primary'))
    assert struct.unpack_from('<I',native.buffer,128)[0]==3
    assert struct.unpack_from('<I',native.buffer,132)[0]==0x80000000
    assert result['disableErrors']==[] and result['primaryPreserved'] is True


def test_mapping_failure_releases_acquired_handle_without_unmap(mod):
    clock,native=Clock(),MemoryBackend()
    def fail_map(handle,size):raise RuntimeError('SYNTHETIC_PRIVATE_SENTINEL')
    native.map_view=fail_map
    capture=mod.PreparedCapture(OriginalWriterBudget.start(clock),mod.Descriptor(701,801,2),native)
    with raises(mod.CaptureError) as caught:capture.create()
    assert 'SYNTHETIC_PRIVATE_SENTINEL' not in str(caught.exception)
    assert native.unmapped==0 and native.closed==1 and native.freed==1


def test_scan_reaches_capacity_after_2047_holes(mod):
    capture,native,clock,witness,owner=armed(mod);ready(native)
    struct.pack_into('<II',native.buffer,136,2048,1)
    row(native,2047,qpc=120)
    capture.disable();result=capture.snapshot()
    assert result['captureIncomplete'] is True and len(result['uncommittedOrdinals'])==2047
    assert [r['eventOrdinal'] for r in result['rows']]==[2048]


def pe_fixture(path,missing=False):
    raw=bytearray(2048);raw[:2]=b'MZ';struct.pack_into('<I',raw,60,128)
    raw[128:132]=b'PE\0\0';struct.pack_into('<HH',raw,132,0x8664,2)
    struct.pack_into('<H',raw,148,240);opt=152
    struct.pack_into('<H',raw,opt,0x20b);struct.pack_into('<I',raw,opt+60,512)
    struct.pack_into('<I',raw,opt+108,16);struct.pack_into('<II',raw,opt+112,4096,256)
    section=392
    struct.pack_into('<IIII',raw,section+8,1024,4096,1024,512)
    struct.pack_into('<IIII',raw,section+48,512,8192,512,1536)
    struct.pack_into('<IIIII',raw,512+20,4,4,4160,4192,4224)
    names=(b'ReadWord',b'ReadQuad',b'PublishWord',b'NotCompareExchange' if missing else b'CompareExchangeWord')
    for index,name in enumerate(names):
        struct.pack_into('<I',raw,576+4*index,8192+4*index)
        struct.pack_into('<I',raw,608+4*index,4352+32*index)
        struct.pack_into('<H',raw,640+2*index,index)
        raw[768+32*index:768+32*index+len(name)+1]=name+b'\0'
    path.write_bytes(raw)


def test_invalid_pe_exports_are_rejected_before_any_dll_load(mod):
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'synthetic.dll';pe_fixture(path,missing=True)
        loads=[]
        with raises(mod.CaptureError):
            mod.NativeBackend({},'x64',validator=lambda *a,**k:path,
                loader=lambda *a,**k:loads.append(1))
        assert loads==[]


class SdkFunction:
    def __init__(self,callback):self.callback=callback
    def __call__(self,*args):return self.callback(*args)


class SdkLibrary:
    _handle=997
    def __init__(self,functions):
        for name,function in functions.items():setattr(self,name,SdkFunction(function))


def test_native_adapter_uses_existing_sdk_shapes_and_compare_exchange_old_value(mod):
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'synthetic.dll';pe_fixture(path)
        memory=C.create_string_buffer(131328)
        def process_times(handle,created,exited,kernel,user):
            C.cast(created,C.POINTER(C.c_uint64))[0]=801 if handle==999 else 501
            return 1
        def window_thread(hwnd,pid):
            C.cast(pid,C.POINTER(C.c_uint32))[0]=401
            return 611
        def exit_code(handle,code):
            C.cast(code,C.POINTER(C.c_uint32))[0]=259
            return 1
        def cas(pointer,exchange,comparand):
            old=pointer[0]
            if old==comparand:pointer[0]=exchange
            return old
        kernel=SdkLibrary({'GetCurrentProcessId':lambda:701,'GetCurrentProcess':lambda:999,
            'GetProcessId':lambda h:401,'GetProcessTimes':process_times,
            'GetExitCodeProcess':exit_code,'WaitForSingleObject':lambda h,t:258,
            'CreateFileMappingW':lambda *a:901,'MapViewOfFile':lambda *a:C.addressof(memory),
            'UnmapViewOfFile':lambda v:1,'CloseHandle':lambda h:1,'FreeLibrary':lambda h:1})
        user=SdkLibrary({'IsWindow':lambda h:1,'GetWindowThreadProcessId':window_thread})
        library=SdkLibrary({'ReadWord':lambda p:p[0],'ReadQuad':lambda p:p[0],
            'PublishWord':lambda p,v:p.__setitem__(0,v),'CompareExchangeWord':cas})
        def loader(name,**kwargs):return kernel if name=='kernel32' else user if name=='user32' else library
        backend=mod.NativeBackend({},'x64',validator=lambda *a,**k:path,loader=loader)
        assert backend.atomic_accessors_attested is True
        address=C.addressof(memory)
        backend.publish_word(address,5)
        assert backend.compare_exchange_word(address,9,5)==5
        assert backend.read_word(address)==9
        assert backend.compare_exchange_word(address,11,5)==9
        assert backend.read_word(address)==9
        assert backend.controller_identity()==(701,801)
        assert backend.process_snapshot(301)=={'pid':401,'creationTime':501,'waitResult':258,'exitCode':259}
        assert backend.window_binding(601)==(401,611)
        assert len(library.CompareExchangeWord.argtypes)==3
        assert len(kernel.GetProcessTimes.argtypes)==5
        kernel.FreeLibrary.callback=lambda handle:0
        assert backend.release_library() is False
        assert backend.release_library() is False


def test_native_adapter_refuses_unattested_preparation_without_loading(mod):
    loads=[]
    def reject(*a,**k):raise RuntimeError('SYNTHETIC_PRIVATE_SOURCE')
    with raises(mod.CaptureError) as caught:
        mod.NativeBackend({},'x64',validator=reject,loader=lambda *a,**k:loads.append(1))
    assert loads==[] and 'SYNTHETIC_PRIVATE_SOURCE' not in str(caught.exception)


def test_partial_native_backend_load_releases_only_loaded_library(mod):
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'synthetic.dll';pe_fixture(path)
        released=[]
        kernel=SdkLibrary({'FreeLibrary':lambda handle:released.append(handle) or 1})
        library=SdkLibrary({})
        def loader(name,**kwargs):return kernel if name=='kernel32' else SdkLibrary({}) if name=='user32' else library
        with raises(mod.CaptureError):
            mod.NativeBackend({},'x64',validator=lambda *a,**k:path,loader=loader)
        assert released==[997]


@parameters('release_succeeds',[False,True])
def test_attestation_failure_transfers_only_unreleased_private_backend(mod,release_succeeds):
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'SYNTHETIC_PRIVATE_DLL.dll';pe_fixture(path)
        released=[]
        kernel=SdkLibrary({'FreeLibrary':lambda handle:released.append(handle) or int(release_succeeds)})
        library=SdkLibrary({})
        def loader(name,**kwargs):return kernel if name=='kernel32' else SdkLibrary({}) if name=='user32' else library
        with raises(mod.CaptureError) as caught:
            mod.NativeBackend({},'x64',validator=lambda *a,**k:path,loader=loader)
        error=caught.exception
        owner=getattr(error,'retained_backend',None)
        if release_succeeds:
            assert owner is None and error.cleanup_codes==()
        else:
            assert type(owner) is mod.NativeBackend
            assert owner.library is library and owner.kernel is kernel
            assert owner.atomic_accessors_attested is False and error.cleanup_codes==(3,)
        assert released==[997]
        assert 'retained_backend' not in vars(error) and '_retained_backend' not in vars(error)
        encoded=json.dumps(vars(error))
        assert '997' not in encoded and 'SYNTHETIC_PRIVATE_DLL' not in encoded
        assert json.loads(json.dumps(error,default=vars))=={'code':12,'cleanup_codes':[] if release_succeeds else [3]}
        assert 'SYNTHETIC_PRIVATE_DLL' not in str(error) and 'SYNTHETIC_PRIVATE_DLL' not in repr(error)


def test_clock_rollback_is_not_accepted_after_successful_create(mod):
    capture,native,clock,witness,owner=prepared(mod);clock.value=99
    with raises(mod.CaptureError):capture.arm_once(owner,lambda:True)
    assert struct.unpack_from('<I',native.buffer,128)[0]!=2


@parameters('offset',[28,100,104,112,120,184,192,216,252])
def test_every_reserved_header_region_is_rejected(mod,offset):
    capture,native,clock,witness,owner=armed(mod);valid_rows(native)
    struct.pack_into('<I',native.buffer,offset,1)
    capture.disable();assert capture.snapshot()['captureIncomplete'] is True


def test_future_commit_cannot_fill_hole_during_same_snapshot(mod):
    capture,native,clock,witness,owner=armed(mod);ready(native)
    struct.pack_into('<II',native.buffer,136,2,1)
    row(native,0,commit=0);row(native,1,phase=11)
    original_read=native.read_word
    def delayed_commit(address):
        value=original_read(address)
        if address==native.base+256 and value==0:
            struct.pack_into('<I',native.buffer,256,1)
            struct.pack_into('<I',native.buffer,140,2)
        return value
    native.read_word=delayed_commit
    capture.disable();result=capture.snapshot()
    assert result['captureIncomplete'] is True and result['uncommittedOrdinals']==[1]
    assert [r['eventOrdinal'] for r in result['rows']]==[2]


@parameters('change',['root_before_setup','row_before_root'])
def test_ready_qpc_order_cannot_hide_delayed_callback_sample(mod,change):
    capture,native,clock,witness,owner=armed(mod);valid_rows(native)
    if change=='root_before_setup':
        struct.pack_into('<q',native.buffer,200,115)
        struct.pack_into('<q',native.buffer,208,110)
    else:
        struct.pack_into('<q',native.buffer,208,110)
    capture.disable();assert capture.snapshot()['captureIncomplete'] is True


def test_scope_counter_over_capacity_is_not_exported(mod):
    capture,native,clock,witness,owner=armed(mod);ready(native)
    struct.pack_into('<II',native.buffer,136,2,2)
    row(native,0,scope=1<<40);row(native,1,scope=1<<40,phase=11)
    capture.disable();result=capture.snapshot()
    assert result['captureIncomplete'] is True and result['rows']==[]


def test_thread_counter_over_capacity_is_not_exported(mod):
    capture,native,clock,witness,owner=armed(mod);ready(native)
    struct.pack_into('<II',native.buffer,136,2,2)
    row(native,0);row(native,1,phase=11)
    struct.pack_into('<I',native.buffer,300,2049)
    struct.pack_into('<I',native.buffer,364,2049)
    capture.disable();result=capture.snapshot()
    assert result['captureIncomplete'] is True and result['rows']==[]


def test_interleaved_threads_allow_global_qpc_decrease(mod):
    capture,native,clock,witness,owner=armed(mod);ready(native)
    struct.pack_into('<II',native.buffer,136,4,4)
    row(native,0,scope=1,qpc=110)
    row(native,1,scope=2,qpc=105)
    row(native,2,scope=2,qpc=106,phase=11)
    row(native,3,scope=1,qpc=111,phase=11)
    struct.pack_into('<I',native.buffer,256+64+44,2)
    struct.pack_into('<I',native.buffer,256+128+44,2)
    capture.disable();result=capture.snapshot()
    assert result['captureIncomplete'] is False
    assert [r['qpc'] for r in result['rows']]==[110,105,106,111]


def test_qpc_reversal_on_same_thread_is_incomplete(mod):
    capture,native,clock,witness,owner=armed(mod);ready(native)
    struct.pack_into('<II',native.buffer,136,2,2)
    row(native,0,qpc=110);row(native,1,qpc=109,phase=11)
    capture.disable();assert capture.snapshot()['captureIncomplete'] is True


@parameters('compiler_declaration', ('', '#ifdef __declspec\n#undef __declspec\n#endif\n#define __declspec(x) __attribute__((x))\n'))
def test_compare_exchange_export_old_value_with_fake_windows_primitive(mod, compiler_declaration):
    import subprocess
    import tempfile
    candidate=BASE/'suite/e2e/ascii_message_observer.cpp'
    assert candidate.is_file(), 'CAS accessor candidate is missing'
    source=candidate.read_text()
    start=source.index('extern "C" __declspec(dllexport) unsigned int CompareExchangeWord(')
    function=source[start:source.index('\n}',start)+2]
    preamble='''#include <cstdint>\n#include <cassert>\n#ifdef __declspec\n#undef __declspec\n#endif\n#define __declspec(x)\nusing LONG=std::int32_t;\nLONG InterlockedCompareExchange(volatile LONG* p,LONG e,LONG c){LONG old=*p;if(old==c)*p=e;return old;}\n'''
    main='''\nint main(){std::uint32_t x=5;assert(CompareExchangeWord(&x,9,5)==5&&x==9);assert(CompareExchangeWord(&x,11,5)==9&&x==9);assert(CompareExchangeWord(&x,0x80000009u,9)==9&&x==0x80000009u);assert(CompareExchangeWord(&x,3,0x80000009u)==0x80000009u&&x==3);}\n'''
    with tempfile.TemporaryDirectory() as folder:
        code=Path(folder)/'atomic.cpp';binary=Path(folder)/'atomic'
        code.write_text(compiler_declaration+preamble+function+main)
        compiled=subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(code),'-o',str(binary)],capture_output=True)
        assert compiled.returncode==0, 'Synthetic CAS C++ compilation failed'
        assert subprocess.run([str(binary)],capture_output=True).returncode==0


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, function in sorted(tuple(globals().items())):
        if not name.startswith('test_') or not callable(function):
            continue
        values = getattr(function, 'case_values', [None])
        for index, value in enumerate(values):
            def run(function=function, value=value):
                module = mod()
                if hasattr(function, 'case_values'):
                    function(module, value)
                else:
                    function(module)
            suite.addTest(unittest.FunctionTestCase(run, description=f'{name}[{index}]'))
    return suite
