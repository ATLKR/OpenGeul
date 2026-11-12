"""Opt-in bootstrap diagnostics: bounded raw RAM, closed integers only.

No decoded output, messages, lines, paths, URLs, environments or commands leave
this module. Textual tokens are observations, not authenticated build events.
"""
import re
import ctypes as C
from dataclasses import dataclass,field
from . import sdk_win32 as win

_PREFIX=re.compile(rb'(?<![A-Za-z0-9_])error ')
_CODE=re.compile(rb'(NU|MSB|NETSDK|CS)([0-9]{1,6})\Z')
_FAMILY={b'NU':1,b'MSB':2,b'NETSDK':3,b'CS':4}


class ErrorCodes:
    def __init__(self,*,max_bytes=1024*1024,max_codes=64,max_count=65535):
        if any(type(n) is not int or n<=0 for n in (max_bytes,max_codes,max_count)):
            raise ValueError('bootstrap_bound') from None
        if max_bytes>1024*1024 or max_codes>64 or max_count>65535:
            raise ValueError('bootstrap_bound') from None
        self.max_bytes,self.max_codes,self.max_count=max_bytes,max_codes,max_count
        self.offset=0;self._tail=b'';self._processed=-1;self._counts={}
        self._finished=False;self.unknown=False;self.overflow=False

    def __repr__(self):return '<BootstrapErrorCodes private>'

    def _reject(self,*,overflow=False):
        if overflow:self.overflow=True
        else:self.unknown=True
        raise ValueError('bootstrap_capture_rejected') from None

    def _scan(self,raw,start,*,final):
        for match in _PREFIX.finditer(raw):
            position=start+match.start()
            if position<=self._processed or (match.start()==0 and start>0):continue
            suffix=raw[match.end():match.end()+17]
            colon=suffix.find(b':')
            if colon<0:
                if len(suffix)<17 and not final:continue
                self.unknown=True;self._processed=position;continue
            self._processed=position
            token=_CODE.fullmatch(suffix[:colon])
            if token is None or int(token[2])==0:
                self.unknown=True;continue
            key=(_FAMILY[token[1]],int(token[2]))
            if (key not in self._counts and len(self._counts)>=self.max_codes
                    or self._counts.get(key,0)>=self.max_count):self._reject(overflow=True)
            self._counts[key]=self._counts.get(key,0)+1

    def feed(self,offset,data):
        if type(offset) is not int or offset!=self.offset or type(data) is not bytes or self._finished:
            self._reject()
        if len(data)>self.max_bytes-self.offset:self._reject(overflow=True)
        raw=self._tail+data;start=self.offset-len(self._tail)
        self.offset+=len(data)
        self._scan(raw,start,final=False)
        self._tail=raw[-64:]

    def finish(self):
        if not self._finished:
            self._scan(self._tail,self.offset-len(self._tail),final=True)
            self._tail=b'';self._finished=True
        return {'complete':not(self.unknown or self.overflow),'unknown':self.unknown,
                'overflow':self.overflow,'codeObserved':bool(self._counts),
                'codes':[[family,code,count] for (family,code),count in sorted(self._counts.items())]}


@dataclass(repr=False)
class _Capture:
    controller: int
    reads: list=field(default_factory=lambda:[None,None])
    writes: list=field(default_factory=lambda:[None,None])
    streams: list=field(default_factory=lambda:[ErrorCodes(max_codes=16),ErrorCodes(max_codes=16)])
    eof: list=field(default_factory=lambda:[False,False])
    buffers: list=field(default_factory=list)
    job: int=0
    nul: int=0
    handle_list: bool=False
    startup: bool=False
    failure: int=0
    read_noninherit: bool=False
    def __repr__(self):return '<BootstrapCapture private>'


class BootstrapApi(win.NativeApi):
    """Explicit separate mode; original NativeApi.launch executes ownership gates.

    Only this instance's two typed call seams expand the stdio attribute and
    startup handles. The base constructor/job/controller/resume code is intact.
    With no active capture, both calls are forwarded unchanged.
    """
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        kernel=kwargs.get('kernel')
        if kernel is None:kernel=C.WinDLL('kernel32',use_last_error=True)
        self._bind_capture(kernel)

    def _bind_capture(self,kernel):
        definitions=(
            ('_pipe','CreatePipe',(C.POINTER(win.H),C.POINTER(win.H),C.POINTER(win.SecurityAttributes),win.U32),win.B),
            ('_set_inherit','SetHandleInformation',(win.H,win.U32,win.U32),win.B),
            ('_peek_pipe','PeekNamedPipe',(win.H,win.H,win.U32,C.POINTER(win.U32),C.POINTER(win.U32),C.POINTER(win.U32)),win.B),
            ('_read_pipe','ReadFile',(win.H,win.H,win.U32,C.POINTER(win.U32),win.H),win.B))
        for attribute,name,args,result in definitions:
            function=getattr(kernel,name);function.argtypes,function.restype=args,result;setattr(self,attribute,function)
        self._plain_update,self._plain_create=self._update,self._create
        self._update,self._create=self._capture_update,self._capture_create
        self._capture_active=None

    def _new_capture(self,binding):
        if type(binding) is not tuple or len(binding)!=3:raise win.NativeCallError(win.FailureCode.INVALID_INPUT)
        return _Capture(win._handle(binding[0]))

    def launch_captured(self,argv,cwd,environment,*,controller_binding):
        if self._capture_active is not None:raise win.NativeCallError(win.FailureCode.INVALID_INPUT)
        cap=self._new_capture(controller_binding);self._capture_active=cap;owned=None
        try:
            owned=super().launch(argv,cwd,environment,controller_binding=controller_binding)
            return owned
        finally:
            self._capture_active=None
            if owned is None:self._close_capture_handles(cap,reads=True)

    def _pipe_pair(self,cap,index):
        read,write=win.H(),win.H();security=win.SecurityAttributes(C.sizeof(win.SecurityAttributes),None,1)
        try:made=self._pipe(C.byref(read),C.byref(write),C.byref(security),4096)
        finally:
            for value,dest in ((read.value,cap.reads),(write.value,cap.writes)):
                if value and value!=win.PTR_MAX and value not in (cap.controller,cap.job,cap.nul):dest[index]=value
        if not made:raise win.NativeCallError(win.FailureCode.STDIO)
        r,w=win._handle(read.value),win._handle(write.value)
        handles=[h for h in cap.reads+cap.writes if h]
        if len(handles)!=len(set(handles)) or r not in handles or w not in handles:
            raise win.NativeCallError(win.FailureCode.INHERITANCE)
        if not self._set_inherit(r,1,0) or self._inheritable(r) or not self._inheritable(w):
            raise win.NativeCallError(win.FailureCode.INHERITANCE)

    def _capture_update(self,*values):
        cap=self._capture_active
        if cap is None:return self._plain_update(*values)
        if len(values)!=7 or values[1]!=0 or values[4]!=C.sizeof(win.H):
            raise win.NativeCallError(win.FailureCode.ATTRIBUTE_HANDLES)
        payload=getattr(values[3],'_obj',None)
        if not isinstance(payload,C.Array) or payload._type_ is not win.H or len(payload)!=1:
            raise win.NativeCallError(win.FailureCode.ATTRIBUTE_HANDLES)
        kind=values[2];handle=win._handle(payload[0])
        if kind==0x2000D:
            if cap.job:raise win.NativeCallError(win.FailureCode.ATTRIBUTE_JOB)
            cap.job=handle
        elif kind==0x20002:
            if cap.handle_list or not cap.job:raise win.NativeCallError(win.FailureCode.ATTRIBUTE_HANDLES)
            cap.nul=handle
            if handle in (cap.job,cap.controller) or not self._inheritable(handle):
                raise win.NativeCallError(win.FailureCode.INHERITANCE)
            for index in (0,1):self._pipe_pair(cap,index)
            array=(win.H*3)(cap.nul,*cap.writes);cap.buffers.append(array)
            values=(*values[:3],C.byref(array),C.sizeof(array),*values[5:])
            cap.handle_list=True;cap.read_noninherit=True
        else:raise win.NativeCallError(win.FailureCode.ATTRIBUTE_HANDLES)
        return self._plain_update(*values)

    def _capture_create(self,*values):
        cap=self._capture_active
        if cap is not None:
            if cap.startup or not cap.handle_list or len(values)!=10 or values[4] is not True or values[5]!=0x08080404:
                raise win.NativeCallError(win.FailureCode.CREATE_PROCESS)
            structure=getattr(values[8],'_obj',None)
            if type(structure) is not win.StartupInfoEx:raise win.NativeCallError(win.FailureCode.STDIO)
            startup=structure.startup
            if (startup.flags!=0x100 or startup.cb!=C.sizeof(win.StartupInfoEx)
                    or [startup.stdin,startup.stdout,startup.stderr]!=[cap.nul]*3):
                raise win.NativeCallError(win.FailureCode.STDIO)
            startup.stdout,startup.stderr=cap.writes;cap.startup=True
        return self._plain_create(*values)

    def _close_capture_handles(self,cap,*,reads):
        ok=True;lists=[cap.writes]+([cap.reads] if reads else [])
        handles=list(dict.fromkeys(h for row in lists for h in row if h))
        for handle in handles:
            try:closed=self.close(handle)
            except BaseException:closed=False
            if not closed:ok=False;cap.failure=6;continue
            for row in lists:
                for i,value in enumerate(row):
                    if value==handle:row[i]=None
        return ok

    def release_launch_local(self,owned):
        base=super().release_launch_local(owned)
        cap=getattr(owned,'bootstrap_capture',self._capture_active)
        if cap is None:return base
        owned.bootstrap_capture=cap
        closed=self._close_capture_handles(cap,reads=False)
        if owned.attributes_released:cap.buffers.clear()
        owned.local_cleanup_complete=base and closed
        return owned.local_cleanup_complete

    def drain_capture(self,owned,deadline,clock,*,final=False):
        cap=getattr(owned,'bootstrap_capture',None)
        if cap is None:return False
        try:
            if cap.failure:return False
            for index,handle in enumerate(cap.reads):
                for _ in range(257):
                    if clock()>=deadline:cap.failure=1;return False
                    available=win.U32()
                    ok=self._peek_pipe(win._handle(handle),None,0,None,C.byref(available),None)
                    if clock()>=deadline:cap.failure=1;return False
                    if not ok:
                        if self._last_error()==109:cap.eof[index]=True;break
                        cap.failure=2;return False
                    if not available.value:break
                    remaining=1024*1024-sum(s.offset for s in cap.streams)
                    if remaining<=0:cap.failure=3;return False
                    size=min(int(available.value),4096,remaining)
                    buffer=C.create_string_buffer(size);count=win.U32()
                    if clock()>=deadline:cap.failure=1;return False
                    if not self._read_pipe(handle,buffer,size,C.byref(count),None) or not 0<count.value<=size:
                        cap.failure=2;return False
                    if clock()>=deadline:cap.failure=1;return False
                    scanner=cap.streams[index];scanner.feed(scanner.offset,buffer.raw[:count.value])
                    if scanner.unknown or scanner.overflow:cap.failure=4;return False
                else:cap.failure=3;return False
            if final and not all(cap.eof):cap.failure=5;return False
            if clock()>=deadline:cap.failure=1;return False
            return True
        except ValueError:
            cap.failure=3 if any(s.overflow for s in cap.streams) else 4
            return False
        except BaseException:cap.failure=2;return False

    def close_capture(self,owned):
        cap=getattr(owned,'bootstrap_capture',None)
        return bool(cap is not None and self._close_capture_handles(cap,reads=True))

    def capture_result(self,owned):
        cap=getattr(owned,'bootstrap_capture',None)
        if cap is None:return {'schemaVersion':1,'complete':False,'failureCode':7,'streams':[],'handlesClosed':False}
        streams=[s.finish() for s in cap.streams]
        closed=not any(cap.reads+cap.writes)
        failure=cap.failure
        if not failure:
            if not closed:failure=6
            elif any(s['overflow'] for s in streams):failure=3
            elif any(s['unknown'] for s in streams):failure=4
            elif not (cap.startup and cap.handle_list and cap.read_noninherit and all(cap.eof)):failure=7
        return {'schemaVersion':1,'complete':not failure,'failureCode':failure,'streams':streams,'handlesClosed':closed,
                'parentReadsNoninheritable':cap.read_noninherit,'exactChildHandleList':cap.handle_list,
                'startupObserved':cap.startup}


def validate_capture(value):
    fields={'schemaVersion','complete','failureCode','streams','handlesClosed','parentReadsNoninheritable','exactChildHandleList','startupObserved'}
    if type(value) is not dict or set(value)!=fields:raise ValueError('bootstrap_record') from None
    if type(value['schemaVersion']) is not int or value['schemaVersion']!=1 or type(value['failureCode']) is not int or not 0<=value['failureCode']<=7:
        raise ValueError('bootstrap_record') from None
    flags=fields-{'schemaVersion','failureCode','streams'}
    if any(type(value[k]) is not bool for k in flags) or type(value['streams']) is not list or len(value['streams'])!=2:
        raise ValueError('bootstrap_record') from None
    for stream in value['streams']:
        if type(stream) is not dict or set(stream)!={'complete','unknown','overflow','codeObserved','codes'}:
            raise ValueError('bootstrap_record') from None
        if any(type(stream[k]) is not bool for k in ('complete','unknown','overflow','codeObserved')):
            raise ValueError('bootstrap_record') from None
        rows=stream['codes']
        if type(rows) is not list or len(rows)>16:raise ValueError('bootstrap_record') from None
        seen=[]
        for row in rows:
            if (type(row) is not list or len(row)!=3 or any(type(n) is not int for n in row)
                    or row[0] not in (1,2,3,4) or not 1<=row[1]<=999999 or not 1<=row[2]<=65535):
                raise ValueError('bootstrap_record') from None
            seen.append(tuple(row[:2]))
        if seen!=sorted(set(seen)) or stream['codeObserved']!=bool(rows) or stream['complete']!=(not stream['unknown'] and not stream['overflow']):
            raise ValueError('bootstrap_record') from None
    expected=(not value['failureCode'] and all(value[k] for k in flags-{'complete'}) and all(s['complete'] for s in value['streams']))
    # A producer with no EOF witness must use explicit incomplete failure code 7.
    if value['complete']!=expected:raise ValueError('bootstrap_record') from None
    return value
