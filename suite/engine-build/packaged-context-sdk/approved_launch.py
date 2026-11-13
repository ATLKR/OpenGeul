"""Externally hash-pinned, isolated source bootstrap; no SDK/OS action before approval."""
import sys
if __name__=='__main__' and (not sys.flags.isolated or not sys.dont_write_bytecode):
    raise SystemExit(3)

import argparse
import ctypes
import dataclasses
import enum
import hashlib
import importlib
import json
import math
import ntpath
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import time

RUNTIME=('approved_launch.py','ci_entry.py','owned_job_win32.py','run_sdk_gate.py','sdk_smoke.hpp',
 'supervisor.py','toolchain.py','windows_sdk_smoke.cpp')
_SEAL=object()

class ApprovalFailure(RuntimeError):
    def __init__(self):super().__init__('sdk_code_approval_rejected')
    def __repr__(self):return '<ApprovalFailure>'

def _identity(value):return value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_nlink

def _canonical(path,*,directory=False):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts:raise ApprovalFailure()
    for q in (p,*p.parents):
        s=q.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise ApprovalFailure()
    s=p.stat()
    if directory:
        if not stat.S_ISDIR(s.st_mode):raise ApprovalFailure()
    elif not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise ApprovalFailure()
    return p

def _read(path,limit=1024*1024):
    p=_canonical(path);before=p.stat()
    if not 0<before.st_size<=limit:raise ApprovalFailure()
    fd=os.open(p,os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
    try:
        first=os.fstat(fd)
        with os.fdopen(fd,'rb',closefd=False) as stream:b=stream.read(limit+1)
        after=os.fstat(fd)
    finally:os.close(fd)
    if len(b)>limit or _identity(before)!=_identity(first) or _identity(first)!=_identity(after) or _identity(after)!=_identity(_canonical(p).stat()):raise ApprovalFailure()
    return b

def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ApprovalFailure()
        value[key]=item
    return value

def _verify(root,manifest,expected):
    root=_canonical(root,directory=True);manifest=Path(manifest)
    if manifest!=root/'approved-sdk-code.json' or type(expected) is not str or not re.fullmatch('[0-9a-f]{64}',expected):raise ApprovalFailure()
    raw=_read(manifest,65536)
    if hashlib.sha256(raw).hexdigest()!=expected:raise ApprovalFailure()
    value=json.loads(raw,object_pairs_hook=_unique)
    if type(value) is not dict or set(value)!= {'schemaVersion','kind','files'} or type(value['schemaVersion']) is not int or value['schemaVersion']!=1 or value['kind']!='sdk-gate-code-approval':raise ApprovalFailure()
    rows=value['files']
    if type(rows) is not list or len(rows)!=len(RUNTIME):raise ApprovalFailure()
    checked=[]
    for index,row in enumerate(rows):
        if type(row) is not dict or set(row)!= {'path','bytes','sha256'} or row['path']!=RUNTIME[index] or type(row['bytes']) is not int or not 0<row['bytes']<=1024*1024 or type(row['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',row['sha256']):raise ApprovalFailure()
        b=_read(root/row['path'])
        if len(b)!=row['bytes'] or hashlib.sha256(b).hexdigest()!=row['sha256']:raise ApprovalFailure()
        checked.append((row['path'],row['bytes'],row['sha256']))
    # No unapproved root-level module/package may shadow a later import.
    for p in root.iterdir():
        if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&0x400:raise ApprovalFailure()
        if p.is_dir() and p.name not in ('tests','frozen-v2'):raise ApprovalFailure()
        if p.is_file() and p.suffix.lower() in ('.py','.pyd','.so','.dll') and p.name not in RUNTIME and p.name!='run_portable_checks.py':raise ApprovalFailure()
    return tuple(checked)

class CodeAdmission:
    __slots__=('_root','_manifest','_expected','_rows','_seal')
    qualification=False
    can_service=False
    def __init__(self,root,manifest,expected,rows,seal):
        if seal is not _SEAL:raise ApprovalFailure()
        for name,value in (('_root',root),('_manifest',manifest),('_expected',expected),('_rows',rows),('_seal',seal)):
            object.__setattr__(self,name,value)
    def __setattr__(self,name,value):raise ApprovalFailure()
    def __repr__(self):return '<SdkCodeAdmission private>'
    @property
    def manifest_sha256(self):return self._expected
    def require_root(self,root):
        if self._seal is not _SEAL or Path(root)!=self._root or _verify(self._root,self._manifest,self._expected)!=self._rows:raise ApprovalFailure()
    def read_approved(self,name):
        self.require_root(self._root)
        if name not in RUNTIME:raise ApprovalFailure()
        b=_read(self._root/name);row=self._rows[RUNTIME.index(name)]
        if len(b)!=row[1] or hashlib.sha256(b).hexdigest()!=row[2]:raise ApprovalFailure()
        return b

def admit_code(root,manifest,expected):
    try:
        root=Path(root);manifest=Path(manifest);rows=_verify(root,manifest,expected)
        return CodeAdmission(root,manifest,expected,rows,_SEAL)
    except BaseException:raise ApprovalFailure() from None

def require_admission(context,root):
    try:
        if type(context) is not CodeAdmission:raise ApprovalFailure()
        context.require_root(root)
        return context
    except BaseException:raise ApprovalFailure() from None

def admit_batch_code(root,manifest,expected):
    """Same exact eight-file admission, with explicit B cancellation propagation."""
    try:
        root=Path(root);manifest=Path(manifest);rows=_verify(root,manifest,expected)
        return CodeAdmission(root,manifest,expected,rows,_SEAL)
    except (KeyboardInterrupt,SystemExit):raise
    except BaseException:raise ApprovalFailure() from None

def require_batch_admission(context,root):
    try:
        if type(context) is not CodeAdmission:raise ApprovalFailure()
        context.require_root(root)
        return context
    except (KeyboardInterrupt,SystemExit):raise
    except BaseException:raise ApprovalFailure() from None

class Parser(argparse.ArgumentParser):
    def error(self,message):raise ApprovalFailure()

def main(argv=None):
    batch=False
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode:raise ApprovalFailure()
        p=Parser(add_help=False);p.add_argument('--approved-manifest',required=True)
        p.add_argument('--expected-approved-manifest-sha256',required=True)
        args,rest=p.parse_known_args(argv)
        root=Path(__file__).absolute().parent
        batch=rest[:1]==['--instrumented-batch-hints']
        context=(admit_batch_code if batch else admit_code)(root,Path(args.approved_manifest),args.expected_approved_manifest_sha256)
        if any(name in sys.modules for name in ('run_sdk_gate','supervisor','toolchain','owned_job_win32')):raise ApprovalFailure()
        if __name__=='__main__':
            if 'approved_launch' in sys.modules:raise ApprovalFailure()
            sys.modules['approved_launch']=sys.modules[__name__]
        sys.path.insert(0,str(root))
        gate=importlib.import_module('run_sdk_gate')
        if rest[:1]==['--instrumented-batch-hints']:
            try:return gate.batch_main(rest[1:],code_admission=context)
            except (KeyboardInterrupt,SystemExit):return 130
        return gate.main(rest,code_admission=context)
    except (KeyboardInterrupt,SystemExit):return 130 if batch else 3
    except BaseException:return 3

if __name__=='__main__':raise SystemExit(main())
