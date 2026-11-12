"""One-shot pinned native-fixture observation; never Suite acceptance."""
from __future__ import annotations
import argparse
import ast
import contextlib
import ctypes
import hashlib
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

SOURCE_HEAD='3a5b101ba9b66b6c17544f89c9f39cdd6e63d933'
SOURCE_PINS=(
 ('suite/tests/test_ime_command3_finalization.py',26192,'524599a937bf5700af3fb662575ea7bf31dd3c6586eb86eefabbc1e6709649dc'),
 ('suite/tests/test_native_crt_probe.py',69758,'3c8e659a4e28ff707d4c52f83f59f0d9f0626d477a9543d05e8e0d780e7a0569'),
 ('suite/tests/ime_command3_finalization_cases/native_policy.cpp',2427,'0be63f6c8c3475dc05c27128831f71e49cda0c9e2e4381920c3c44f54c6dd953'),
 ('suite/tests/ime_command3_finalization_cases/native_adapter.cpp',3464,'aa4daefefbd9b83cba4558caf62f05b3c2dc783d7193af193d5f929dd6388175'),
 ('suite/tests/ime_command3_finalization_cases/native_negotiation.cpp',4112,'10e07296a030cc04ac267e1b130d0e2d7031f3105c5db9d8e0c797a8ab7b7ce0'),
 ('suite/e2e/ime_command3_finalization.h',3119,'bfb4f0e24e4b3c85d1f89cf50f68059d95bcfbf98f435867982b16acec7de967'),
 ('suite/e2e/ime_command3_finalization_windows.h',3585,'8da200c94a6ab2172746d683cb0862d41a9148823f60e0ed859d4ec352b5a482'),
 ('suite/e2e/korean_ime_smoke.py',185108,'4896642204c0d8ef07c505a9e1791983c9cede350fcb60258f81b93604c04144'),
 ('suite/tests/native_executable_cleanup.py',2232,'98bbf36d12b986e72adf817aa5a224c64d0e33d2b6d3cb634a96410addb3455d'),
)
CASES=(('test_real_portable_policy','native_policy.cpp'),
       ('test_actual_windows_sampling_adapter_pairs_context','native_adapter.cpp'),
       ('test_actual_mapping_negotiation_and_export','native_negotiation.cpp'))
FILES=('native_policy.cpp','native_adapter.cpp','native_negotiation.cpp',
       'ime_command3_finalization.h','ime_command3_finalization_windows.h','native_connect.inc','native_read.inc')

def exception_code(kind):
    return {AssertionError:1,subprocess.TimeoutExpired:2,OSError:3,ValueError:4,
            UnicodeDecodeError:5,FileNotFoundError:6,PermissionError:7}.get(kind,255)

def no_alias(path):
    for item in (path,*path.parents):
        if item.exists() or item.is_symlink():
            info=item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Aliased path rejected')

def checked_root(path):
    path=Path(path)
    if '..' in path.parts or any(c in str(path)for c in '\r\n'):raise ValueError('Source path rejected')
    path=path.absolute();no_alias(path)
    if not path.is_dir():raise ValueError('Source directory required')
    return path.resolve(strict=True)

def read_pinned(root,pin):
    name,size,digest=pin;path=root/name;no_alias(path)
    with path.open('rb')as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size!=size:raise ValueError('Source size differs')
        data=stream.read(size+1);after=os.fstat(stream.fileno())
    final=path.stat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if identity(before)!=identity(after) or identity(after)!=identity(final) or len(data)!=size or hashlib.sha256(data).hexdigest()!=digest:
        raise ValueError('Source identity differs')
    return data

def read_head(root):
    git=shutil.which('git')
    if not git:raise ValueError('Installed Git required')
    names=('SystemRoot','WINDIR','SystemDrive','PATH','PATHEXT','TEMP','TMP','ComSpec')
    environment={k:v for k in names if(v:=os.environ.get(k))is not None}
    environment.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_OPTIONAL_LOCKS='0')
    result=subprocess.run([git,'-C',str(root),'rev-parse','--show-toplevel','HEAD'],
        env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5)
    if result.returncode!=0:raise ValueError('Source HEAD unavailable')
    rows=result.stdout.decode('utf-8','strict').splitlines()
    if len(rows)!=2 or checked_root(rows[0])!=root or not re.fullmatch('[0-9a-f]{40}',rows[1]):raise ValueError('Source HEAD shape differs')
    return rows[1]

def admit_source(path):
    root=checked_root(path)
    if read_head(root)!=SOURCE_HEAD:raise ValueError('Pinned source HEAD differs')
    return root,{name:read_pinned(root,(name,size,digest))for name,size,digest in SOURCE_PINS}

def observer_literal(data):
    values=[]
    for node in ast.parse(data).body:
        if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='OBSERVER_SOURCE'for t in node.targets):
            if not isinstance(node.value,ast.Constant)or type(node.value.value)is not str:raise ValueError('Literal observer required')
            values.append(node.value.value)
    if len(values)!=1:raise ValueError('One literal observer required')
    return values[0]

def project_diagnostics(stdout,stderr,root):
    files={ntpath.normcase(str(root/name)):index for index,name in enumerate(FILES,1)}
    files.update({name:index for index,name in enumerate(FILES,1)})
    located=re.compile(r'^(.*?)\(([1-9][0-9]{0,6})(?:,[1-9][0-9]{0,6})?\)\s*:\s*([^:\r\n]{1,64}?)\s+(C|D|LNK)([0-9]{4})\s*:')
    driver=re.compile(r'^(?:[^:()\r\n]{1,64}\s*:\s*)?([^:()\r\n]{1,64}?)\s+(C|D|LNK)([0-9]{4})\s*:')
    kinds={'C':1,'D':2,'LNK':3};severities={'warning':1,'error':2,'fatal error':3,'command line warning':1,'command line error':2}
    value=dict(scanComplete=1,droppedCount=0,diagnostics=[])
    for stream,text in enumerate((stdout,stderr),1):
        if type(text)is not str:value['scanComplete']=0;continue
        if len(text)>65536:value['scanComplete']=0
        rows=text[:65536].splitlines()
        if len(rows)>512:value['scanComplete']=0
        for row in rows[:512]:
            if len(row)>4096:value['scanComplete']=0;continue
            match=located.match(row)
            if match:
                path,line,severity,kind,number=match.groups();code=files.get(ntpath.normcase(path.strip()),0);line=int(line)if code else 0
            else:
                match=driver.match(row)
                if not match:continue
                severity,kind,number=match.groups();code=line=0
            descriptor=dict(streamCode=stream,severity=severities.get(severity.strip().lower(),0),kind=kinds[kind],number=int(number),fileCode=code,line=line)
            if len(value['diagnostics'])<32:value['diagnostics'].append(descriptor)
            else:value['droppedCount']+=1
    return value

def compiler_observer(original,case):
    def observed(*args,**options):
        case['compileCalls']+=1
        result=original(*args,**options)
        try:
            value=project_diagnostics(result.stdout,result.stderr,Path(options['cwd']))
            value.update(exitCode=result.returncode,projectionFailed=0)
        except Exception:value=dict(exitCode=result.returncode,projectionFailed=1,scanComplete=0,droppedCount=0,diagnostics=[])
        case['compile'].append(value)
        return result
    return observed

class ClosedResult(unittest.TestResult):
    def __init__(self):super().__init__();self.outcome=0;self.exceptionCode=0
    def addFailure(self,test,err):self.failures.append((test,''));self.outcome=1;self.exceptionCode=exception_code(err[0])
    def addError(self,test,err):self.errors.append((test,''));self.outcome=2;self.exceptionCode=exception_code(err[0])
    def addSkip(self,test,reason):self.skipped.append((test,''));self.outcome=3

def host_architecture():
    if os.name!='nt':raise ValueError('Native Windows required')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.argtypes=[];kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.IsWow64Process2.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint16),ctypes.POINTER(ctypes.c_uint16)]
    kernel.IsWow64Process2.restype=ctypes.c_int
    process,native=ctypes.c_uint16(),ctypes.c_uint16()
    if not kernel.IsWow64Process2(kernel.GetCurrentProcess(),ctypes.byref(process),ctypes.byref(native))or process.value!=0 or native.value not in(0x8664,0xaa64):
        raise ValueError('Native host architecture differs')
    return native.value

def run_cases(approved,receipt):
    names=('test_native_crt_probe','native_executable_cleanup','fixed_finalization_cases')
    if any(name in sys.modules for name in names):raise ValueError('Preloaded fixture module rejected')
    def module(name,path,data):
        spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
        sys.modules[name]=value;exec(compile(data,str(path),'exec'),value.__dict__);return value
    try:
        with tempfile.TemporaryDirectory(prefix='opengeul-fixed-finalization-')as folder,open(os.devnull,'w')as sink:
            private=Path(folder).resolve(strict=True)
            for pin in SOURCE_PINS:
                name,size,digest=pin;path=private/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(approved[name])
                read_pinned(private,pin)
            with contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):
                support=module(names[0],private/SOURCE_PINS[1][0],approved[SOURCE_PINS[1][0]])
                module(names[1],private/SOURCE_PINS[8][0],approved[SOURCE_PINS[8][0]])
                cases=module(names[2],private/SOURCE_PINS[0][0],approved[SOURCE_PINS[0][0]])
                literal=observer_literal(approved[SOURCE_PINS[7][0]])
                cases.helper=lambda:SimpleNamespace(OBSERVER_SOURCE=literal)
                original=support._serializer_compile_process
                for code,(method,_)in enumerate(CASES,1):
                    case=dict(caseCode=code,outcome=2,exceptionCode=0,compileCalls=0,compile=[])
                    receipt['cases'].append(case);support._serializer_compile_process=compiler_observer(original,case)
                    result=ClosedResult();cases.NativeTests(method).run(result)
                    case.update(outcome=result.outcome,exceptionCode=result.exceptionCode)
                support._serializer_compile_process=original
    finally:
        for name in names:sys.modules.pop(name,None)

def new_receipt():
    return dict(schemaVersion=1,sourceHead=SOURCE_HEAD,sourceVerified=0,hostArchitecture=0,
        pythonMajor=sys.version_info.major,pythonMinor=sys.version_info.minor,pythonMicro=sys.version_info.micro,
        actualWindowsExecuted=0,acceptanceEligible=0,qualificationEligible=0,stage=1,
        setupExceptionCode=0,sourceFiles=[dict(fileCode=i,size=size,sha256=digest)for i,(_,size,digest)in enumerate(SOURCE_PINS,1)],cases=[])

def final_exit(value):
    return 0 if len(value['cases'])==3 and all(row['outcome']==0 for row in value['cases'])else 1

def prepare_output(path,source):
    path=Path(path)
    if '..'in path.parts or any(c in str(path)for c in '\r\n'):raise ValueError('Output path rejected')
    path=path.absolute();no_alias(path.parent)
    if path.exists()or path.is_symlink()or not path.parent.is_dir():raise ValueError('Fresh output directory required')
    source=Path(source)
    if '..'in source.parts:raise ValueError('Source path rejected')
    source=source.absolute();no_alias(source)
    if path==source or source in path.parents:raise ValueError('Output must be outside source')
    path.mkdir();return path

def main(argv=None):
    class ClosedParser(argparse.ArgumentParser):
        def error(self,message):raise ValueError('Fixed collector arguments rejected')
    parser=ClosedParser();parser.add_argument('--source-root',required=True)
    parser.add_argument('--architecture',required=True,choices=('x64','arm64'));parser.add_argument('--output',required=True)
    try:args=parser.parse_args(argv)
    except Exception:return 1
    receipt=new_receipt()
    try:output=prepare_output(args.output,args.source_root)
    except Exception:return 1
    try:
        receipt['stage']=2;_,approved=admit_source(args.source_root);receipt['sourceVerified']=1
        receipt['stage']=3;receipt['hostArchitecture']=host_architecture()
        if receipt['hostArchitecture']!={'x64':0x8664,'arm64':0xaa64}[args.architecture]:raise ValueError('Expected architecture differs')
        receipt['actualWindowsExecuted']=1;receipt['stage']=4;run_cases(approved,receipt);receipt['stage']=5
    except Exception as error:receipt['setupExceptionCode']=exception_code(type(error))
    code=final_exit(receipt)
    if receipt['setupExceptionCode']or any(row['compileCalls']!=1 or any(item['projectionFailed']for item in row['compile'])for row in receipt['cases']):code=1
    receipt['exitCode']=code
    try:
        data=(json.dumps(receipt,separators=(',',':'),allow_nan=False)+'\n').encode('ascii')
        if len(data)>32768:raise ValueError('Closed report exceeds bound')
        with (output/'report.numeric.json').open('xb')as stream:stream.write(data)
    except Exception:return 1
    return code

if __name__=='__main__':
    raise SystemExit(main())
