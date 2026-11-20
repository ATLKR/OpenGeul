"""Fixed numeric diagnostic protocol; never an input or acceptance authority."""
import ctypes
import hashlib
from pathlib import Path
import re

MAGIC=0x4f474631
VERSION=1
class Unavailable(Exception):
    pass

class Config(ctypes.Structure):
    _fields_=[(k,ctypes.c_uint32)for k in('magic','version','configBytes','sectionBytes','mappingBytes','sectionOffset','enabled','pid','tid','reserved')]+[(k,ctypes.c_uint64)for k in('targetHwnd','rootHwnd','creationTime','epochLow','epochHigh')]
class Row(ctypes.Structure):
    _fields_=[(k,ctypes.c_uint32)for k in('sequence','stage','status','pid','tid','ackAtStart','withinBefore','withinAfter')]+[(k,ctypes.c_uint64)for k in('targetHwnd','rootHwnd','focusBefore','focusAfter','himc','layout','startedCounter','finishedCounter')]+[(k,ctypes.c_uint32)for k in('contextPresent','conversionSucceeded','open','conversion','sentence','releaseAttempts','releaseSucceeded','reserved')]+[(k,ctypes.c_uint64)for k in('deadlineCounter','counterFrequency')]
class Section(ctypes.Structure):
    _fields_=[('config',Config)]+[(k,ctypes.c_uint32)for k in('claimedMask','publishedMask','rejected','reserved')]+[('rows',Row*3)]

def _int(value,maximum,positive=False):
    assert type(value)is int and (1 if positive else 0)<=value<=maximum
    return value
def fields(record):return {k:int(getattr(record,k))for k,_ in record._fields_}
def config(*,state_bytes,pid,tid,hwnd,root,created,epoch):
    _int(state_bytes,2**32-1,True);assert state_bytes%8==0
    for v in(pid,tid):_int(v,2**32-1,True)
    for v in(hwnd,root,created):_int(v,2**64-1,True)
    assert type(epoch)is tuple and len(epoch)==2
    for v in epoch:_int(v,2**64-1,True)
    return Config(MAGIC,VERSION,ctypes.sizeof(Config),ctypes.sizeof(Section),state_bytes+ctypes.sizeof(Section),state_bytes,1,pid,tid,0,hwnd,root,created,*epoch)
def mapping_type(state):
    class Mapping(ctypes.Structure):_fields_=[('state',state),('finalization',Section)]
    assert Mapping.finalization.offset==ctypes.sizeof(state)
    return Mapping
def source_identity(helper):
    helper=Path(helper);digest=hashlib.sha256(b'OpenGeul-command3-finalization-v1\0')
    for path in(helper,helper.with_name('ime_command3_finalization.h'),helper.with_name('ime_command3_finalization_windows.h'),Path(__file__)):
        data=path.read_bytes();digest.update(len(data).to_bytes(8,'little'));digest.update(data)
    return digest.hexdigest()
def render_source(source,expected):
    assert type(source)is str
    binding={}if expected is None else fields(expected)
    if expected is not None:_config(binding,expected)
    values={'ENABLED':int(expected is not None),'PID':binding.get('pid',0),'TID':binding.get('tid',0),
        'HWND':binding.get('targetHwnd',0),'ROOT':binding.get('rootHwnd',0),'CREATED':binding.get('creationTime',0),
        'EPOCH_LOW':binding.get('epochLow',0),'EPOCH_HIGH':binding.get('epochHigh',0)}
    for key,value in values.items():source=source.replace('__FINALIZATION_'+key+'__',str(value)+'ull')
    assert '__FINALIZATION_'not in source
    return source
def _config(value,expected):
    assert type(expected)is Config and type(value)is dict and set(value)==set(fields(expected))
    assert all(type(v)is int for v in value.values())and value==fields(expected)
    assert expected.magic==MAGIC and expected.version==1 and expected.configBytes==80 and expected.sectionBytes==528
    assert expected.mappingBytes==expected.sectionOffset+528 and expected.sectionOffset>0 and expected.sectionOffset%8==0
    assert expected.enabled==1 and expected.reserved==0
    assert all(getattr(expected,k)>0 for k in('pid','tid','targetHwnd','rootHwnd','creationTime','epochLow','epochHigh'))
def decode(section,*,expected,expected_source,expected_budget,ack_before,ack_after):
    assert type(section)is Section and section.reserved==0
    assert type(ack_before)is type(ack_after)is int and 0<=ack_before==ack_after<=4
    value=dict(schemaVersion=1,kind='command3-finalization-diagnostic',sourceSha256=expected_source,config=fields(section.config),
        claimedMask=int(section.claimedMask),publishedMask=int(section.publishedMask),rejected=int(section.rejected),
        ackBefore=ack_before,ackAfter=ack_after,statusCode=1 if section.publishedMask==7 else 2,
        rows=[fields(section.rows[i])for i in range(3)if section.publishedMask&(1<<i)],
        acceptanceEligible=False,causalAttributionProved=False)
    return require_receipt(value,expected=expected,expected_source=expected_source,expected_budget=expected_budget)
def require_receipt(value,*,expected,expected_source,expected_budget):
    assert type(expected_budget)is tuple and len(expected_budget)==2
    for v in expected_budget:_int(v,2**64-1,True)
    keys={'schemaVersion','kind','sourceSha256','config','claimedMask','publishedMask','rejected','ackBefore','ackAfter','statusCode','rows','acceptanceEligible','causalAttributionProved'}
    assert type(expected_source)is str and re.fullmatch('[0-9a-f]{64}',expected_source)
    assert type(value)is dict and set(value)==keys
    assert type(value['schemaVersion'])is int and value['schemaVersion']==1 and value['kind']=='command3-finalization-diagnostic'
    assert value['sourceSha256']==expected_source
    assert value['acceptanceEligible']is False and value['causalAttributionProved']is False
    _config(value['config'],expected)
    claimed=_int(value['claimedMask'],7);published=_int(value['publishedMask'],7)
    assert claimed in(0,1,3,7)and published in(0,1,3,7)and published&claimed==published
    _int(value['rejected'],2**32-1)
    assert type(value['ackBefore'])is type(value['ackAfter'])is int and 0<=value['ackBefore']==value['ackAfter']<=4
    assert type(value['statusCode'])is int and value['statusCode']==(1 if published==7 else 2)
    assert type(value['rows'])is list and len(value['rows'])==published.bit_count()
    for i,row in enumerate(value['rows'],1):
        assert type(row)is dict and set(row)=={k for k,_ in Row._fields_}
        for name,ctype in Row._fields_:_int(row[name],2**(ctypes.sizeof(ctype)*8)-1)
        assert row['sequence']==row['stage']==i and 0<=row['status']<=8 and row['reserved']==0
        assert (row['pid'],row['tid'],row['targetHwnd'],row['rootHwnd'])==(expected.pid,expected.tid,expected.targetHwnd,expected.rootHwnd)
        assert 0<=row['ackAtStart']<=3
        for key in('withinBefore','withinAfter','contextPresent','conversionSucceeded','open','releaseAttempts','releaseSucceeded'):assert row[key]in(0,1)
        assert row['startedCounter']>0 and row['finishedCounter']>=row['startedCounter']
        assert (row['deadlineCounter'],row['counterFrequency'])==expected_budget
        if not row['status']:
            assert row['finishedCounter']<expected_budget[0]
            assert row['withinBefore']==row['withinAfter']==row['contextPresent']==row['conversionSucceeded']==row['releaseAttempts']==row['releaseSucceeded']==1
            assert row['himc']>0 and row['focusBefore']==row['focusAfter']==expected.targetHwnd
    return value

class NativeMappingPort:
    def __init__(self):
        from ctypes import wintypes as W
        import mmap
        self.mmap=mmap;self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateFileMappingW.argtypes=[W.HANDLE,ctypes.c_void_p,W.DWORD,W.DWORD,W.DWORD,W.LPCWSTR]
        self.kernel.CreateFileMappingW.restype=W.HANDLE
        self.kernel.CloseHandle.argtypes=[W.HANDLE];self.kernel.CloseHandle.restype=W.BOOL
    def create(self,name,size):
        ctypes.set_last_error(0)
        handle=self.kernel.CreateFileMappingW(ctypes.c_void_p(-1),None,4,0,size,name)
        return handle,ctypes.get_last_error()==183
    def map(self,name,size):return self.mmap.mmap(-1,size,tagname=name)
    def close(self,handle):return bool(self.kernel.CloseHandle(handle))
def allocate(name,size,port):
    assert type(name)is str and name and len(name)<=256
    _int(size,2**32-1,True)
    handle,already=port.create(name,size)
    if not handle:raise Unavailable(1)
    view=None
    try:
        if already:raise Unavailable(2)
        view=port.map(name,size)
    finally:
        if not port.close(handle):
            if view is not None:view.close()
            raise Unavailable(3)
    return view
