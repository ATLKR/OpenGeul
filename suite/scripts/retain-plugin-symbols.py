#!/usr/bin/env python3
"""Retain a bounded ARM64 DLL/PDB identity pair; never load either binary.

MSF7 directory and information-stream layout: llvm.org/docs/PDB/MsfFile.html
and llvm.org/docs/PDB/PdbStream.html. Identity matching is not semantic symbol validation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import uuid

MAX_DLL=32*1024*1024
MAX_PDB=512*1024*1024
MAX_CONFIG=1024*1024
STAT_FIELDS=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
DLL='instdir/program/vclplug_winlo.dll'
PDB='workdir/LinkTarget/Library/vclplug_winlo.pdb'
MAGIC=b'Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0'


class SymbolError(ValueError):pass

def require(ok,code):
    if not ok:raise SymbolError(code)


def unlinked(path, *, budget=None):
    path=Path(path)
    require(path.is_absolute() and str(path)==os.path.abspath(path),'absolute-normal-path-required')
    # Reject an ancestor junction before looking up a child through it.
    for part in (*reversed(path.parents),path):
        if budget is not None:budget.now()
        info=part.lstat()
        if budget is not None:budget.now()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&1024,'linked-path')
    return path


def read_regular(path,limit, *, budget=None):
    def check():
        if budget is not None:budget.now()
    path=unlinked(path,budget=budget);check();before=path.stat();check()
    require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=limit,'regular-file-size')
    check()
    with path.open('rb') as stream:
        check();opened=os.fstat(stream.fileno());check()
        chunks=[];total=0
        while True:
            check();chunk=stream.read(min(1024*1024,limit+1-total));check()
            if not chunk:break
            total+=len(chunk);require(total<=limit,'read-size');chunks.append(chunk)
        check();after=os.fstat(stream.fileno());check()
    check();final=unlinked(path,budget=budget).stat();check()
    def identity(v,fields=STAT_FIELDS):return tuple(getattr(v,k) for k in fields)
    require(identity(before)==identity(final) and identity(opened)==identity(after),'file-changed')
    require(identity(before,STAT_FIELDS[:3])==identity(opened,STAT_FIELDS[:3]),'file-identity')
    require(total==before.st_size,'read-size')
    return b''.join(chunks)


def take(data,offset,count):
    require(0<=offset<=len(data) and 0<=count<=len(data)-offset,'binary-bounds')
    return data[offset:offset+count]


def unpack(data,offset,fmt):return struct.unpack('<'+fmt,take(data,offset,struct.calcsize('<'+fmt)))


def identity(guid,age):
    require(len(guid)==16 and any(guid) and 0<age<=0xffffffff,'symbol-identity')
    return dict(guid=str(uuid.UUID(bytes_le=guid)),age=age)


def pe_identity(data):
    require(0<len(data)<=MAX_DLL and take(data,0,2)==b'MZ','pe-size-or-magic')
    pe=unpack(data,60,'I')[0]
    require(pe>=64 and take(data,pe,4)==b'PE\0\0','pe-signature')
    machine,count,_,_,_,opt_size,flags=unpack(data,pe+4,'HHIIIHH')
    require(machine==0xaa64 and 1<=count<=96 and flags&2 and flags&0x2000,'native-arm64-dll')
    opt=pe+24;take(data,opt,opt_size)
    require(opt_size>=168 and unpack(data,opt,'H')[0]==0x20b,'pe32plus')
    image_size,headers=unpack(data,opt+56,'II');dirs=unpack(data,opt+108,'I')[0]
    require(7<=dirs<=16 and 112+dirs*8<=opt_size,'pe-directories')
    require(opt+opt_size+count*40<=headers<=len(data) and headers<=image_size,'pe-headers')
    if dirs>14:require(unpack(data,opt+112+14*8,'II')==(0,0),'managed-image')
    sections=[]
    for i in range(count):
        vs,va,size,raw=unpack(data,opt+opt_size+i*40+8,'IIII');span=max(vs,size)
        require(span>0 and va>=headers and va+span<=image_size,'section-range')
        if size:require(raw>=headers,'section-raw');take(data,raw,size)
        for pva,pspan,praw,psize in sections:
            require(va+span<=pva or pva+pspan<=va,'section-overlap')
            require(not size or not psize or raw+size<=praw or praw+psize<=raw,'section-raw-overlap')
        sections.append((va,span,raw,size))
    def rva(addr,size):
        found=[raw+addr-va for va,_,raw,n in sections if va<=addr and addr+size<=va+n]
        require(size>0 and len(found)==1,'debug-rva')
        return found[0]
    debug,amount=unpack(data,opt+112+6*8,'II')
    require(0<amount<=64*28 and amount%28==0,'debug-directory')
    start=rva(debug,amount);matches=[]
    for off in range(start,start+amount,28):
        _,_,_,_,kind,size,addr,raw=unpack(data,off,'IIHHIIII')
        if kind!=2:continue
        require(25<=size<=4096,'codeview-size')
        if addr:require(rva(addr,size)==raw,'codeview-pointer')
        cv=take(data,raw,size)
        require(cv[:4]==b'RSDS','codeview-format')
        name=cv[24:]
        require(name.endswith(b'\0') and b'\0' not in name[:-1],'codeview-name')
        require(name[:-1].replace(b'\\',b'/').rsplit(b'/',1)[-1]==b'vclplug_winlo.pdb','codeview-pdb-name')
        matches.append(identity(cv[4:20],unpack(cv,20,'I')[0]))
    require(len(matches)==1,'unique-codeview-required')
    return matches[0]


def pdb_identity(data):
    require(56<=len(data)<=MAX_PDB and data[:32]==MAGIC,'msf7-header')
    block,fpm,count,directory_size,_,block_map=unpack(data,32,'6I')
    require(block in (512,1024,2048,4096) and fpm in (1,2),'msf-layout')
    require(count>=6 and count*block==len(data),'msf-file-size')
    require(12<=directory_size<=4*1024*1024,'msf-directory-size')
    directory_blocks=(directory_size+block-1)//block
    require(directory_blocks*4<=block,'msf-directory-map-size')
    def valid(index):require(0<index<count and index%block not in (1,2),'msf-block')
    valid(block_map)
    pages=unpack(data,block_map*block,'I'*directory_blocks)
    used={0,block_map}
    def claim(index):
        valid(index);require(index not in used,'msf-block-alias');used.add(index)
    for page in pages:claim(page)
    directory=b''.join(take(data,p*block,block) for p in pages)[:directory_size]
    streams=unpack(directory,0,'I')[0]
    require(2<=streams<=65536,'msf-stream-count')
    sizes=unpack(directory,4,'I'*streams);cursor=4+4*streams;info=None
    for index,size in enumerate(sizes):
        if size==0xffffffff:continue
        require(size<=len(data),'msf-stream-size')
        n=(size+block-1)//block
        indexes=unpack(directory,cursor,'I'*n);cursor+=n*4
        for page in indexes:claim(page)
        if index==1:
            require(size>=28,'pdb-info-size')
            info=take(data,indexes[0]*block,28)
    require(cursor==len(directory) and info is not None,'msf-directory-shape')
    version,_,age=unpack(info,0,'III')
    require(version in (20000404,20030901,20091201,20140508),'pdb-info-version')
    return identity(info[12:28],age)


def pin(data):return dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())


def retain(source_root,output,source_commit,config):
    root=unlinked(source_root);output=Path(output);config=Path(config)
    require(root.is_dir() and re.fullmatch('[0-9a-f]{40}',source_commit) is not None and source_commit!='0'*40,'source-provenance')
    require(config==root/'config_host.mk','fixed-config-path')
    require(output.is_absolute() and str(output)==os.path.abspath(output),'output-path')
    unlinked(output.parent);require(not output.exists() and not output.is_symlink(),'fresh-output-required')
    dll_data=read_regular(root/DLL,MAX_DLL);pdb_data=read_regular(root/PDB,MAX_PDB)
    config_data=read_regular(config,MAX_CONFIG)
    matched=pe_identity(dll_data);require(matched==pdb_identity(pdb_data),'dll-pdb-identity-mismatch')
    result=dict(schemaVersion=1,kind='matched-plugin-symbols',acceptance=False,identityMatched=True,
        symbolContentsValidated=False,sourceCommit=source_commit,configSha256=pin(config_data)['sha256'],
        helperSha256=pin(read_regular(Path(__file__).absolute(),1024*1024))['sha256'],matchedIdentity=matched,
        files={key:dict(name=name,**pin(data)) for key,name,data in
               (('dll','vclplug_winlo.dll',dll_data),('pdb','vclplug_winlo.pdb',pdb_data))})
    raw=json.dumps(result,sort_keys=True,indent=2)+'\n';require(len(raw)<=8192,'receipt-size')
    output.mkdir()
    try:
        for key,data in (('dll',dll_data),('pdb',pdb_data)):
            path=output/result['files'][key]['name']
            with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            require(pin(read_regular(path,MAX_DLL if key=='dll' else MAX_PDB))==pin(data),'copy-identity')
        require(read_regular(config,MAX_CONFIG)==config_data,'configuration-changed')
        with (output/'receipt.json').open('x',encoding='utf-8') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
    except BaseException:
        shutil.rmtree(output)
        raise
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-root','output','source-commit','config'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    try:
        result=retain(Path(args.source_root),Path(args.output),args.source_commit,Path(args.config));code=0
    except Exception as exc:
        result=dict(schemaVersion=1,kind='matched-plugin-symbols',acceptance=False,identityMatched=False,
                    failureClass=type(exc).__name__,reason=str(exc) if type(exc) is SymbolError else 'retention-failure');code=1
    print(json.dumps(result,sort_keys=True))
    return code


if __name__=='__main__':raise SystemExit(main())
