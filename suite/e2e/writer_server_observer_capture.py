"""Private Writer observer IPC controller. No hook, input, PID reopen or COM call.

IPCv1 is independent of the product's private sink ABI2. All shared accesses
use prepared Interlocked exports. The Linux test port is a synthetic mapping;
it does not establish Windows atomicity or a COM preemption guarantee.
"""
import ctypes as C
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
import re
import struct

FAMILY = 'writer-server-observer-diagnostic'
ENVIRONMENT = 'OPENGEUL_WRITER_SERVER_OBSERVER'
MAGIC, VERSION, CAPACITY, MAPPING_BYTES = 0x57534f31, 1, 2048, 131328
CLOSED, ACTIVE_MASK, MAX_I64 = 0x80000000, 0x7fffffff, (1 << 63)-1
U32, U64, I64 = C.c_uint32, C.c_uint64, C.c_int64


class Code(IntEnum):
    DESCRIPTOR=1
    ABI=2
    NATIVE=3
    BUDGET=4
    GENERATION=5
    STATE=6
    HEADER=7
    OVERFLOW=8
    PARTIAL=9
    ORDER=10
    ROW=11
    ATTESTATION=12
    ACTIVE=13


class CaptureError(RuntimeError):
    __slots__=('_retained_backend',)

    def __init__(self, code, *, cleanup_codes=(), retained_backend=None):
        self.code = Code(code)
        self.cleanup_codes=tuple(cleanup_codes)
        self._retained_backend=retained_backend
        super().__init__('Writer capture failure code ' + str(int(self.code)))

    @property
    def retained_backend(self):
        """Private ownership transfer only; excluded from str/repr/vars/JSON."""
        return self._retained_backend


def _need(value, code):
    if not value:
        raise CaptureError(code)


def _uint(value, bits=32, minimum=0):
    return type(value) is int and minimum <= value < 1 << bits


@dataclass(frozen=True, slots=True, repr=False)
class Descriptor:
    controller_pid: int
    controller_birth: int
    nonce: int

    def __post_init__(self):
        _need(_uint(self.controller_pid,32,1) and _uint(self.controller_birth,64,1)
              and _uint(self.nonce,64,1), Code.DESCRIPTOR)

    def __repr__(self):
        return '<Descriptor private>'

    @classmethod
    def parse(cls, value):
        _need(type(value) is str and len(value)<=128, Code.DESCRIPTOR)
        match = re.fullmatch(r'1:([1-9][0-9]*):([1-9][0-9]*):([0-9a-f]{16}):131328:OpenGeulWriterServerObserver',value)
        _need(match is not None,Code.DESCRIPTOR)
        return cls(int(match[1]),int(match[2]),int(match[3],16))

    def environment_value(self):
        return f'1:{self.controller_pid}:{self.controller_birth}:{self.nonce:016x}:131328:OpenGeulWriterServerObserver'

    def _mapping_name(self):
        return f'Local\\OpenGeulWriterServerObserver-{self.controller_pid}-{self.nonce:016x}'


@dataclass(frozen=True, slots=True, repr=False)
class OriginalOwnerBinding:
    original_engine: object
    suite_hwnd: int
    editor_hwnd: int
    editor_tid: int

    def __repr__(self):
        return '<OriginalOwnerBinding private>'


class Identity(C.Structure):
    _fields_=[('magic',U32),('version',U32),('bytes',U32),('capacity',U32),
        ('controllerPid',U32),('ownerPid',U32),('ownerTid',U32),('reserved0',U32),
        ('controllerBirth',U64),('nonce',U64),('ownerBirth',U64),('ownerHwnd',U64),
        ('startQpc',I64),('deadlineQpc',I64),('qpcFrequency',I64),('cutoffQpc',I64),
        ('namespaceCode',U32),('reserved1',U32),('reserved2',U64*3)]


class Control(C.Structure):
    _fields_=[('admission',U32),('captureGate',U32),('reservedCount',U32),('committedCount',U32),
        ('dropped',U32),('overflow',U32),('incomplete',U32),('sessionState',U32),
        ('rootState',U32),('setupObserved',U32),('rootBoundObserved',U32),('rejected',U32),
        ('expired',U32),('cleanupErrors',U32),('nextScopeOrdinal',U64),
        ('nextThreadOrdinal',U32),('lastStatus',U32),('setupReadyQpc',I64),
        ('rootReadyQpc',I64),('reserved',U32*10)]


class Row(C.Structure):
    _fields_=[('commit',U32),('kind',U32),('phase',U32),('datum',U32),
        ('scopeOrdinal',U64),('parentScopeOrdinal',U64),('qpc',I64),('depth',U32),
        ('threadOrdinal',U32),('eventOrdinal',U32),('reserved0',U32),('reserved1',U64)]


def abi_layout():
    return {**{name:{'bytes':C.sizeof(kind),'alignment':C.alignment(kind),
                'offsets':{field:getattr(kind,field).offset for field,_ in kind._fields_}}
            for name,kind in (('identity',Identity),('control',Control),('row',Row))},
        'mappingBytes':C.sizeof(Identity)+C.sizeof(Control)+C.sizeof(Row)*CAPACITY}


def _layout_valid():
    return (C.sizeof(C.c_void_p)==8 and C.sizeof(Identity)==128 and C.sizeof(Control)==128
        and C.sizeof(Row)==64 and C.alignment(Identity)==C.alignment(Control)==C.alignment(Row)==8
        and Identity.controllerBirth.offset==32 and Identity.startQpc.offset==64
        and Control.nextScopeOrdinal.offset==56 and Control.setupReadyQpc.offset==72
        and Row.scopeOrdinal.offset==16 and Row.qpc.offset==32 and Row.eventOrdinal.offset==48)


def _event_valid(kind,phase,datum):
    if kind==1:
        return (phase in (10,11) and datum==0) or (phase==9 and datum in (1,2,3))
    if kind==2:
        return ((phase in (1,10,11) and datum==0) or (phase==2 and datum in (1,2,3,4,5,6))
            or (phase in (3,4) and datum in (1,2)) or (phase==5 and datum in (0,1,2,3)))
    if kind==3:
        return ((phase==5 and datum in (0,1,3)) or (phase==6 and datum in (2,3))
            or (phase in (7,8,10) and datum in (1,2,3)) or (phase==11 and datum==0))
    return False


class PreparedCapture:
    """Inert constructor keeps partial-create ownership in the caller's finally."""
    def __init__(self,budget,descriptor,backend):
        self._budget,self._descriptor,self._backend=budget,descriptor,backend
        self._mapping=self._view=None
        self._created=self._create_attempted=self._arm_attempted=self._disabled=False
        self._owner=self._witness=self._witness_values=None
        self._errors=[]
        self._cleanup=None
        self._budget_values=None

    def __repr__(self):
        return '<PreparedCapture private>'

    def _error(self,code):
        value=int(code)
        if value not in self._errors:self._errors.append(value)

    def _check(self,observation):
        try:
            b=self._budget
            values=(b.start_qpc,b.deadline_qpc,b.cutoff_qpc,b.frequency)
            _need(all(type(v) is int for v in values),Code.BUDGET)
            if self._budget_values is None:self._budget_values=values
            _need(values==self._budget_values,Code.BUDGET)
            _need(0<b.frequency<=MAX_I64//30 and 0<b.start_qpc<b.cutoff_qpc<b.deadline_qpc<=MAX_I64
                and 5*b.frequency<b.deadline_qpc-b.start_qpc<=30*b.frequency
                and b.cutoff_qpc==b.deadline_qpc-5*b.frequency,Code.BUDGET)
            now=b.check(observation=observation)
            _need(type(now) is int and b.start_qpc<=now<(b.cutoff_qpc if observation else b.deadline_qpc),Code.BUDGET)
            return now
        except Exception:
            raise CaptureError(Code.BUDGET) from None

    def _word(self,offset):
        value=self._backend.read_word(self._view+offset)
        _need(_uint(value),Code.HEADER)
        return value

    def _quad(self,offset):
        value=self._backend.read_quad(self._view+offset)
        _need(_uint(value,64),Code.HEADER)
        return value

    def _put_word(self,offset,value):
        _need(_uint(value),Code.HEADER)
        self._backend.publish_word(self._view+offset,value)

    def _put_quad_before_arm(self,offset,value):
        # Two atomic word stores, ONLY before release-publishing Armed. Neither
        # operation is represented as an atomic 64-bit store.
        _need(_uint(value,64),Code.HEADER)
        self._put_word(offset,value&0xffffffff)
        self._put_word(offset+4,value>>32)

    def create(self):
        _need(not self._create_attempted,Code.STATE)
        self._create_attempted=True
        try:
            self._check(True)
            _need(_layout_valid() and type(self._descriptor) is Descriptor,Code.ABI)
            _need(self._backend.atomic_accessors_attested is True,Code.ATTESTATION)
            _need(self._backend.controller_identity()==(self._descriptor.controller_pid,self._descriptor.controller_birth),Code.GENERATION)
            self._check(True)
            handle,existed=self._backend.create_mapping(self._descriptor._mapping_name(),MAPPING_BYTES)
            _need(_uint(handle,64,1),Code.NATIVE)
            self._mapping=handle
            _need(existed is False,Code.STATE)
            self._view=self._backend.map_view(handle,MAPPING_BYTES)
            _need(_uint(self._view,64,1) and self._view%8==0,Code.ABI)
            self._check(True)
            # PAGE_READWRITE newly created pagefile mappings are initially zero.
            # Check the whole header through atomic accessors, without touching
            # or assuming atomicity of a ctypes Structure memory load.
            _need(all(self._word(offset)==0 for offset in range(0,256,4)),Code.HEADER)
            d,b=self._descriptor,self._budget
            for offset,value in ((0,MAGIC),(4,VERSION),(8,MAPPING_BYTES),(12,CAPACITY),(16,d.controller_pid),(96,1)):
                self._put_word(offset,value)
            for offset,value in ((32,d.controller_birth),(40,d.nonce),(64,b.start_qpc),
                (72,b.deadline_qpc),(80,b.frequency),(88,b.cutoff_qpc)):
                self._put_quad_before_arm(offset,value)
            self._check(True)
            self._created=True
            return self
        except Exception as exc:
            code=exc.code if isinstance(exc,CaptureError) else Code.NATIVE
            self._error(code)
            self.close_local(primary=exc)
            raise CaptureError(code) from None

    @staticmethod
    def _witness_tuple(witness):
        try:
            values=(witness.handle,witness.pid,witness.birth)
            _need(_uint(values[0],64,1) and _uint(values[1],32,1) and _uint(values[2],64,1),Code.GENERATION)
            return values
        except Exception:
            raise CaptureError(Code.GENERATION) from None

    def _verify_owner(self,owner,verify_original):
        self._check(True)
        _need(type(owner) is OriginalOwnerBinding and callable(verify_original),Code.GENERATION)
        _need(_uint(owner.suite_hwnd,64,1) and _uint(owner.editor_hwnd,64,1) and _uint(owner.editor_tid,32,1),Code.GENERATION)
        values=self._witness_tuple(owner.original_engine)
        if self._witness is not None:
            _need(owner.original_engine is self._witness and values==self._witness_values,Code.GENERATION)
        _need(verify_original() is True,Code.GENERATION)
        _need(self._backend.controller_identity()==(self._descriptor.controller_pid,self._descriptor.controller_birth),Code.GENERATION)
        sample=self._backend.process_snapshot(values[0])
        _need(type(sample) is dict and sample.get('pid')==values[1] and sample.get('creationTime')==values[2]
            and sample.get('waitResult')==258 and sample.get('exitCode')==259,Code.GENERATION)
        _need(self._backend.window_binding(owner.editor_hwnd)==(values[1],owner.editor_tid),Code.GENERATION)
        self._check(True)
        return values

    def arm_once(self,owner,verify_original):
        _need(self._created and not self._arm_attempted and not self._disabled and self._cleanup is None,Code.STATE)
        self._arm_attempted=True
        try:
            self._check(True)
            _need(self._backend.compare_exchange_word(self._view+128,1,0)==0,Code.STATE)
            self._witness_values=self._verify_owner(owner,verify_original)
            self._witness=owner.original_engine
            self._owner=owner
            self._put_word(20,self._witness_values[1]);self._put_word(24,owner.editor_tid)
            self._put_quad_before_arm(48,self._witness_values[2]);self._put_quad_before_arm(56,owner.editor_hwnd)
            self._verify_owner(owner,verify_original)
            self._header_matches()
            self._check(True)
            # Last publication, with Interlocked release/full-barrier semantics.
            _need(not self._disabled and self._backend.compare_exchange_word(self._view+128,2,1)==1,Code.STATE)
            self._verify_owner(owner,verify_original)
            return {'armed':True,'originalBindingMatches':True}
        except Exception as exc:
            code=exc.code if isinstance(exc,CaptureError) else Code.NATIVE
            self._error(code);self.disable()
            raise CaptureError(code) from None

    def disable(self):
        self._disabled=True
        result={'admissionClosed':None,'captureGateClosed':None,'activeCount':None,'errors':[]}
        if self._view is None or self._cleanup is not None:return result
        try:self._check(False)
        except Exception:self._error(Code.BUDGET);result['errors'].append(int(Code.BUDGET))
        for offset,close_value in ((128,None),(132,CLOSED)):
            succeeded=False
            try:
                for _ in range(64):
                    old=self._word(offset)
                    if offset==128 and old not in (0,1,2,3):self._error(Code.HEADER)
                    new=3 if offset==128 else old|close_value
                    if old==new or self._backend.compare_exchange_word(self._view+offset,new,old)==old:
                        succeeded=True
                        break
                if not succeeded:raise CaptureError(Code.STATE)
                if offset==128:result['admissionClosed']=True
                else:
                    gate=self._word(132)
                    result['captureGateClosed']=bool(gate&CLOSED)
                    result['activeCount']=gate&ACTIVE_MASK
            except Exception:
                self._error(Code.NATIVE);result['errors'].append(int(Code.NATIVE))
        return result

    def _header_matches(self):
        d,b=self._descriptor,self._budget
        expected32=((0,MAGIC),(4,VERSION),(8,MAPPING_BYTES),(12,CAPACITY),(16,d.controller_pid),
            (28,0),(96,1),(100,0))
        expected64=((32,d.controller_birth),(40,d.nonce),(64,b.start_qpc),(72,b.deadline_qpc),
            (80,b.frequency),(88,b.cutoff_qpc),(104,0),(112,0),(120,0))
        _need(all(self._word(o)==v for o,v in expected32) and all(self._quad(o)==v for o,v in expected64),Code.HEADER)
        _need(self._owner is not None and self._witness_tuple(self._witness)==self._witness_values,Code.GENERATION)
        _need(self._word(20)==self._witness_values[1] and self._word(24)==self._owner.editor_tid
            and self._quad(48)==self._witness_values[2] and self._quad(56)==self._owner.editor_hwnd,Code.GENERATION)
        _need(self._quad(184)==0 and self._word(192)==0 and all(self._word(o)==0 for o in range(216,256,4)),Code.HEADER)

    def snapshot(self):
        errors=list(self._errors)
        def error(code):
            if int(code) not in errors:errors.append(int(code))
        result={'schemaVersion':1,'captureIncomplete':True,'decoderErrors':errors,'rows':[],
            'uncommittedOrdinals':[],'admissionClosed':None,'captureGateClosed':None,'activeCount':None,
            'sessionReadyObserved':None,'rootBoundObserved':None,'reservedCount':None,'committedCount':None,
            'dropped':None,'overflow':None,'incompleteMask':None,'rejected':None,'expired':None,
            'cleanupErrorsCount':None,'originalBindingMatches':None,
            'wholeOriginalIntervalCovered':False,'originalClientAttributionUnknown':True,
            'normalAcceptance':0,'fullEngineQualified':0}
        if self._view is None or self._cleanup is not None:
            error(Code.STATE);return result
        try:
            self._check(False);self._header_matches();result['originalBindingMatches']=True
            admission,gate,reserved,committed=(self._word(o) for o in (128,132,136,140))
            result['admissionClosed']=admission==3
            result['captureGateClosed']=bool(gate&CLOSED)
            result['activeCount']=gate&ACTIVE_MASK
            if admission!=3 or not gate&CLOSED:error(Code.STATE)
            if gate&ACTIVE_MASK:error(Code.ACTIVE)
            result['reservedCount'],result['committedCount']=reserved,committed
            for name,offset in (('dropped',144),('overflow',148),('incompleteMask',152),
                ('sessionReadyObserved',164),('rootBoundObserved',168),('rejected',172),
                ('expired',176),('cleanupErrorsCount',180)):
                result[name]=self._word(offset)
            session,root,status=(self._word(o) for o in (156,160,196))
            _need(admission in (0,1,2,3) and session in (0,1,2,3) and root in (0,1,2,3)
                and status in (0,1,2,3,4) and result['overflow'] in (0,1)
                and result['sessionReadyObserved'] in (0,1) and result['rootBoundObserved'] in (0,1)
                and result['incompleteMask']&~255==0,Code.HEADER)
            if session!=2 or root!=2 or result['sessionReadyObserved']!=1 or result['rootBoundObserved']!=1:error(Code.PARTIAL)
            setup_qpc,root_qpc=self._quad(200),self._quad(208)
            for qpc,observed in ((setup_qpc,result['sessionReadyObserved']),(root_qpc,result['rootBoundObserved'])):
                if (observed==1 and not self._budget.start_qpc<=qpc<self._budget.cutoff_qpc) or (observed==0 and qpc!=0):error(Code.PARTIAL)
            if result['rootBoundObserved']==1 and (result['sessionReadyObserved']!=1 or root_qpc<setup_qpc):error(Code.ORDER)
            if reserved>CAPACITY or committed>reserved or any(result[n] for n in ('dropped','overflow','incompleteMask','rejected','expired','cleanupErrorsCount')):error(Code.OVERFLOW)
            stable_count=0;last_qpc_by_thread={}
            scopes={};stacks={}
            for index in range(min(reserved,CAPACITY)):
                self._check(False)
                offset=256+index*64
                first=self._word(offset)
                if first==0:
                    result['uncommittedOrdinals'].append(index+1);error(Code.PARTIAL);continue
                # Acquire commit -> every body field read atomically -> acquire
                # same commit. Never stop scanning when a preceding slot is a hole.
                kind,phase,datum=(self._word(offset+o) for o in (4,8,12))
                scope,parent,qpc=(self._quad(offset+o) for o in (16,24,32))
                depth,thread,event,res0=(self._word(offset+o) for o in (40,44,48,52))
                res1=self._quad(offset+56);second=self._word(offset)
                if first!=second or first!=index+1 or event!=index+1:
                    error(Code.PARTIAL);continue
                stable_count+=1
                if (not _event_valid(kind,phase,datum) or res0 or res1 or not 1<=depth<=32
                    or not 1<=scope<=CAPACITY or not 1<=thread<=CAPACITY
                    or not 0<=parent<=CAPACITY or parent>=scope or (depth==1)!=(parent==0)
                    or not self._budget.start_qpc<=qpc<self._budget.cutoff_qpc
                    or (result['rootBoundObserved']==1 and qpc<root_qpc)):
                    error(Code.ROW);continue
                # Source sampling precedes slot reservation: another thread can
                # reserve a newer QPC first. Only each non-reused thread ordinal
                # has the synchronous sample -> sink return ordering contract.
                previous_qpc=last_qpc_by_thread.get(thread)
                if previous_qpc is not None and qpc<previous_qpc:error(Code.ORDER)
                last_qpc_by_thread[thread]=qpc
                signature=(kind,parent,depth,thread)
                stack=stacks.setdefault(thread,[])
                if phase==10:
                    if scope in scopes:error(Code.ORDER)
                    if len(stack)!=depth-1 or (stack[-1] if stack else 0)!=parent:error(Code.ORDER)
                    scopes[scope]=(signature,False)
                    stack.append(scope)
                elif scope not in scopes or scopes[scope]!=(signature,False):error(Code.ORDER)
                if not stack or stack[-1]!=scope:error(Code.ORDER)
                if phase==11:
                    scopes[scope]=(signature,True)
                    if stack and stack[-1]==scope:stack.pop()
                result['rows'].append({'kind':kind,'phase':phase,'datum':datum,'scopeOrdinal':scope,
                    'parentScopeOrdinal':parent,'qpc':qpc,'depth':depth,'threadOrdinal':thread,'eventOrdinal':event})
            if any(not ended for _,ended in scopes.values()):error(Code.PARTIAL)
            if stable_count!=committed:error(Code.PARTIAL)
            if (self._word(136),self._word(140))!=(reserved,committed) or self._word(132)&ACTIVE_MASK:error(Code.PARTIAL)
            self._check(False)
        except Exception as exc:
            error(exc.code if isinstance(exc,CaptureError) else Code.NATIVE)
        result['captureIncomplete']=bool(errors)
        return result

    def join_retirement(self,original_witness,evidence):
        result={'remoteRetired':0,'normalClose':None,'originalWitnessMatches':False,
            'observedWithinDeadline':None,'errorCode':0}
        try:
            match=(self._witness is original_witness and evidence is not None
                and evidence.original_witness is original_witness
                and self._witness_tuple(original_witness)==self._witness_values)
            result['originalWitnessMatches']=match
            when=evidence.observed_qpc if evidence is not None else None
            within=(type(when) is int and self._budget.start_qpc<=when<self._budget.deadline_qpc
                and evidence.within_deadline is True)
            result['observedWithinDeadline']=within if evidence is not None else None
            if (match and within and evidence.identity_matches is True and evidence.engine_exit_observed is True
                and evidence.exit_code_observed is True and evidence.remote_retired is True):
                result['remoteRetired']=1
            else:result['errorCode']=int(Code.GENERATION)
            # The lifecycle owns forced disposal. Neither signaled exit nor
            # unmapping is a normal-close receipt, so normalClose stays Unknown.
        except Exception:result['errorCode']=int(Code.GENERATION)
        return result

    def close_local(self,primary=None):
        if self._cleanup is not None:return self._cleanup
        result={'unmapSucceeded':None,'mappingHandleClosed':None,'libraryReleased':None,
            'cleanupErrors':[],'disableErrors':[],'primaryPreserved':primary is not None}
        if self._view is not None:
            try:result['disableErrors']=self.disable()['errors']
            except Exception:result['disableErrors']=[int(Code.NATIVE)]
        self._cleanup=result
        # Independent attempts; never replace a primary exception or pretend a
        # failed local release proves anything about the engine's remote view.
        for code,name,resource,method in ((1,'unmapSucceeded',self._view,self._backend.unmap_view),
            (2,'mappingHandleClosed',self._mapping,self._backend.close_handle),
            (3,'libraryReleased',True,self._backend.release_library)):
            if resource is None:continue
            try:ok=method(resource) if code!=3 else method()
            except Exception:ok=False
            result[name]=ok is True
            if ok is not True:result['cleanupErrors'].append(code)
        return result


REQUIRED_EXPORTS=('ReadWord','ReadQuad','PublishWord','CompareExchangeWord')


def _pe_exports(path):
    """Bounded static PE32+ export validation, BEFORE LoadLibrary/DllMain."""
    try:
        with Path(path).open('rb') as stream:raw=stream.read(32*1024*1024+1)
        _need(64<=len(raw)<=32*1024*1024 and raw[:2]==b'MZ',Code.ATTESTATION)
        def u16(o):return struct.unpack_from('<H',raw,o)[0]
        def u32(o):return struct.unpack_from('<I',raw,o)[0]
        pe=u32(60);_need(raw[pe:pe+4]==b'PE\0\0',Code.ATTESTATION)
        count,opt_size=u16(pe+6),u16(pe+20);opt=pe+24
        _need(1<=count<=96 and opt_size>=120 and u16(opt)==0x20b and u32(opt+108)>=1,Code.ATTESTATION)
        export_rva,export_size=u32(opt+112),u32(opt+116)
        sections=opt+opt_size;headers=u32(opt+60)
        def offset(rva,size):
            if rva<headers and rva+size<=min(headers,len(raw)):return rva
            for i in range(count):
                p=sections+40*i;virtual,va,n,at=u32(p+8),u32(p+12),u32(p+16),u32(p+20)
                if va<=rva and rva+size<=va+n and at+rva-va+size<=len(raw):return at+rva-va
            raise CaptureError(Code.ATTESTATION)
        table=offset(export_rva,40)
        functions,names=u32(table+20),u32(table+24)
        _need(0<names<=functions<=65536,Code.ATTESTATION)
        addresses=offset(u32(table+28),functions*4);name_table=offset(u32(table+32),names*4)
        ordinals=offset(u32(table+36),names*2);found=set()
        for i in range(names):
            at=offset(u32(name_table+4*i),1);end=raw.find(b'\0',at,min(at+129,len(raw)))
            _need(end>=at,Code.ATTESTATION)
            name=raw[at:end].decode('ascii');ordinal=u16(ordinals+2*i)
            _need(ordinal<functions,Code.ATTESTATION)
            rva=u32(addresses+4*ordinal)
            if name in REQUIRED_EXPORTS:
                _need(rva>0 and not export_rva<=rva<export_rva+export_size,Code.ATTESTATION)
                offset(rva,1);_need(name not in found,Code.ATTESTATION);found.add(name)
        _need(found==set(REQUIRED_EXPORTS),Code.ATTESTATION)
        return True
    except Exception:
        raise CaptureError(Code.ATTESTATION) from None


class NativeBackend:
    """Actual Win64 SDK signatures, using an authenticated existing helper DLL.

    Default preparation validator pins source+DLL bytes and native PE machine.
    Export names are statically checked before DLL loading. A test may inject
    SDK loaders/validator for synthetic PE fixtures; this is not Windows proof.
    """
    def __init__(self,prepared_library,architecture,*,validator=None,loader=None):
        self.atomic_accessors_attested=False
        self._library_released=False
        self._release_result=None
        self.kernel=self.user=self.library=None
        try:
            if validator is None:
                from ascii_message_preparation import require_prepared_library
                validator=require_prepared_library
            path=validator(prepared_library,architecture=architecture)
            _pe_exports(path)
            loader=loader if loader is not None else C.WinDLL
            self.kernel=loader('kernel32',use_last_error=True)
            self.kernel.FreeLibrary.argtypes=(C.c_void_p,)
            self.kernel.FreeLibrary.restype=C.c_int32
            self.user=loader('user32',use_last_error=True)
            self.library=loader(str(path),use_last_error=True)
            H,B=C.c_void_p,C.c_int32
            for dll,name,args,result in (
                (self.kernel,'GetCurrentProcessId',(),U32),(self.kernel,'GetCurrentProcess',(),H),
                (self.kernel,'GetProcessId',(H,),U32),
                (self.kernel,'GetProcessTimes',(H,C.POINTER(U64),C.POINTER(U64),C.POINTER(U64),C.POINTER(U64)),B),
                (self.kernel,'GetExitCodeProcess',(H,C.POINTER(U32)),B),
                (self.kernel,'WaitForSingleObject',(H,U32),U32),
                (self.kernel,'CreateFileMappingW',(H,H,U32,U32,U32,C.c_wchar_p),H),
                (self.kernel,'MapViewOfFile',(H,U32,U32,U32,C.c_size_t),H),
                (self.kernel,'UnmapViewOfFile',(H,),B),(self.kernel,'CloseHandle',(H,),B),
                (self.kernel,'FreeLibrary',(H,),B),
                (self.user,'IsWindow',(H,),B),
                (self.user,'GetWindowThreadProcessId',(H,C.POINTER(U32)),U32),
                (self.library,'ReadWord',(C.POINTER(U32),),U32),
                (self.library,'ReadQuad',(C.POINTER(U64),),U64),
                (self.library,'PublishWord',(C.POINTER(U32),U32),None),
                (self.library,'CompareExchangeWord',(C.POINTER(U32),U32,U32),U32)):
                fn=getattr(dll,name);fn.argtypes=args;fn.restype=result
            self.atomic_accessors_attested=True
        except Exception:
            cleanup=[]
            if self.library is not None:
                try:released=self.release_library()
                except Exception:released=False
                if not released:cleanup.append(3)
            raise CaptureError(Code.ATTESTATION,cleanup_codes=cleanup,
                retained_backend=self if cleanup else None) from None

    def __repr__(self):return '<NativeBackend private>'

    def _birth(self,handle):
        created,exited,kernel,user=U64(),U64(),U64(),U64()
        _need(bool(self.kernel.GetProcessTimes(handle,C.byref(created),C.byref(exited),C.byref(kernel),C.byref(user))),Code.NATIVE)
        return created.value

    def controller_identity(self):
        return int(self.kernel.GetCurrentProcessId()),self._birth(self.kernel.GetCurrentProcess())

    def create_mapping(self,name,size):
        C.set_last_error(0)
        handle=self.kernel.CreateFileMappingW(C.c_void_p(-1),None,4,0,size,name)
        error=C.get_last_error();_need(bool(handle),Code.NATIVE)
        return int(handle),error==183

    def map_view(self,handle,size):
        view=self.kernel.MapViewOfFile(handle,0x000f001f,0,0,size)
        _need(bool(view),Code.NATIVE);return int(view)

    def read_word(self,address):
        _need(address%4==0 and not self._library_released,Code.ABI)
        return int(self.library.ReadWord(C.cast(address,C.POINTER(U32))))

    def read_quad(self,address):
        _need(address%8==0 and not self._library_released,Code.ABI)
        return int(self.library.ReadQuad(C.cast(address,C.POINTER(U64))))

    def publish_word(self,address,value):
        _need(address%4==0 and not self._library_released,Code.ABI)
        self.library.PublishWord(C.cast(address,C.POINTER(U32)),value)

    def compare_exchange_word(self,address,exchange,comparand):
        _need(address%4==0 and not self._library_released,Code.ABI)
        return int(self.library.CompareExchangeWord(C.cast(address,C.POINTER(U32)),exchange,comparand))

    def process_snapshot(self,handle):
        pid=int(self.kernel.GetProcessId(handle));birth=self._birth(handle)
        waited=int(self.kernel.WaitForSingleObject(handle,0));code=U32()
        _need(pid>0 and waited in (0,258) and bool(self.kernel.GetExitCodeProcess(handle,C.byref(code))),Code.NATIVE)
        return {'pid':pid,'creationTime':birth,'waitResult':waited,'exitCode':code.value}

    def window_binding(self,hwnd):
        pid=U32();_need(bool(self.user.IsWindow(hwnd)),Code.GENERATION)
        tid=int(self.user.GetWindowThreadProcessId(hwnd,C.byref(pid)))
        _need(tid>0 and pid.value>0,Code.GENERATION);return pid.value,tid

    def unmap_view(self,view):return bool(self.kernel.UnmapViewOfFile(view))
    def close_handle(self,handle):return bool(self.kernel.CloseHandle(handle))
    def release_library(self):
        if self._library_released:return self._release_result is True
        self._library_released=True
        try:self._release_result=bool(self.kernel.FreeLibrary(self.library._handle))
        except Exception:self._release_result=False
        return self._release_result
