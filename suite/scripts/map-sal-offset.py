#!/usr/bin/env python3
"""Static, nonacceptance mapping of the captured SAL return RVA. Never loads code.

ARM64 field layout: https://learn.microsoft.com/en-us/cpp/build/arm64-exception-handling
Only exact exported range starts are attributed; no nearest-symbol heuristic.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import time
import zipfile

RETURN_RVA = 406484
MAX_MEMBER = 32 * 1024 * 1024
MAX_ARCHIVE = 512 * 1024 * 1024


class MappingError(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise MappingError(reason)


def map_pe(data, return_rva, check):
    check()
    require(0 < len(data) <= MAX_MEMBER, 'member-size')
    def take(off, size):
        check()
        require(0 <= off <= len(data) and 0 <= size <= len(data)-off, 'file-range')
        return data[off:off+size]
    def u(off, fmt='I'):
        return struct.unpack('<'+fmt, take(off, struct.calcsize('<'+fmt)))[0]
    require(take(0,2) == b'MZ', 'dos-header')
    pe = u(0x3c)
    require(take(pe,4) == b'PE\0\0' and u(pe+4,'H') == 0xaa64, 'native-arm64-required')
    count, opt_size = u(pe+6,'H'), u(pe+20,'H')
    opt = pe+24
    require(1 <= count <= 96 and opt_size >= 144 and u(opt,'H') == 0x20b, 'pe32plus-header')
    take(opt,opt_size)
    image_size, headers = u(opt+56), u(opt+60)
    dirs = u(opt+108)
    require(4 <= dirs <= 16 and 112+dirs*8 <= opt_size, 'directory-count')
    require(opt+opt_size+count*40 <= headers <= len(data) and headers <= image_size, 'headers-size')
    sections = []
    for i in range(count):
        off = opt+opt_size+i*40
        vs, va, raw_size, raw = struct.unpack('<IIII',take(off+8,16))
        span = max(vs,raw_size)
        require(span > 0 and va >= headers and va+span <= image_size, 'section-rva')
        if raw_size:
            require(raw >= headers, 'section-header-overlap'); take(raw,raw_size)
        for old_va,old_span,old_raw,old_size,_ in sections:
            require(va+span <= old_va or old_va+old_span <= va, 'section-rva-overlap')
            require(not raw_size or not old_size or raw+raw_size <= old_raw or old_raw+old_size <= raw,
                    'section-file-overlap')
        sections.append((va,span,raw,raw_size,u(off+36)))
    def rva(addr,size, executable=False):
        check()
        require(addr > 0 and size > 0 and addr+size <= 0x100000000, 'rva-range')
        matches = [(raw+addr-va,flags) for va,span,raw,rs,flags in sections
                   if va <= addr and addr+size <= va+rs]
        require(len(matches)==1, 'unmapped-rva')
        off,flags = matches[0]
        require(not executable or flags & 0x20000000, 'nonexecutable-range')
        return off
    def word(addr): return u(rva(addr,4))
    exp, exp_size = u(opt+112), u(opt+116)
    pdata, pdata_size = u(opt+136), u(opt+140)
    result = {'status':'inconclusive','returnRva':return_rva,'precedingInstructionRva':return_rva-4,
              'reason':'no-unique-exact-export-range'}
    require(return_rva >= 4 and return_rva % 4 == 0, 'instruction-alignment')
    ranges=[]
    parent_links=False
    if pdata_size:
        require(pdata_size % 8 == 0 and pdata_size//8 <= 100000, 'exception-count')
        base=rva(pdata,pdata_size)
        for i in range(pdata_size//8):
            begin,unwind=struct.unpack('<II',take(base+i*8,8)); flag=unwind&3
            require(begin % 4 == 0, 'function-alignment')
            if flag == 3:
                # Valid parent links are deliberately not followed or attributed.
                parent=unwind&~3
                require(pdata <= parent < pdata+pdata_size and (parent-pdata)%8==0, 'unwind-parent-range')
                parent_links=True
                continue
            fragment = flag == 2
            if flag:
                length=((unwind>>2)&0x7ff)*4
            else:
                h=word(unwind); length=(h&0x3ffff)*4
                require((h>>18)&3 == 0, 'unwind-version')
                e=(h>>21)&1; scopes=(h>>22)&31; codes=(h>>27)&31; head=4
                if scopes == 0 and codes == 0:
                    ext=word(unwind+4); require(ext>>24==0,'unwind-extension-reserved')
                    scopes=ext&0xffff; codes=(ext>>16)&255; head=8
                require(codes>0, 'unwind-empty-codes')
                scope_count=0 if e else scopes
                total=head+scope_count*4+codes*4+(((h>>20)&1)*4)
                xoff=rva(unwind,total)
                for j in range(scope_count):
                    scope=u(xoff+head+j*4)
                    require((scope>>18)&15==0 and (scope&0x3ffff)*4 < length
                            and scope>>22 < codes*4,'unwind-epilog-scope')
                if e: require(scopes<codes*4,'unwind-epilog-index')
                # Conservatively decline any possible chained scope, including nonleading
                # end_c. Operand bytes may also be 0xe5: false-inconclusive is
                # preferable to claiming an exact name without decoding opcodes.
                code_start=xoff+head+scope_count*4
                fragment = 0xe5 in data[code_start:code_start+codes*4]
            require(length>0,'empty-function')
            rva(begin,length,True)
            require(not ranges or begin >= ranges[-1][1], 'exception-overlap-or-order')
            ranges.append((begin,begin+length,fragment))
    if parent_links:
        result['reason']='unsupported-unwind-parent-link'
        return result
    targets=[v for v in ranges if v[0] <= return_rva-4 and return_rva < v[1]]
    if len(targets)!=1: return result
    begin,end,fragment=targets[0]
    result['functionRange']={'beginRva':begin,'endRvaExclusive':end}
    result['unwindFragment']=fragment
    # Validate preceding instruction as BL immediate or BLR register, not raw bytes in receipt.
    insn=word(return_rva-4)
    result['precedingInstructionIsCall'] = (insn&0xfc000000)==0x94000000 or (insn&0xfffffc1f)==0xd63f0000
    names=[]
    if exp_size:
        require(exp_size>=40,'export-directory-size'); eoff=rva(exp,exp_size)
        nf,nn,fa,na,oa=struct.unpack('<IIIII',take(eoff+20,20))
        require(nf<=100000 and nn<=nf, 'export-count')
        foff=rva(fa,nf*4) if nf else 0
        noff=rva(na,nn*4) if nn else 0; ooff=rva(oa,nn*2) if nn else 0
        for i in range(nn):
            ordinal=u(ooff+i*2,'H'); require(ordinal<nf,'export-ordinal')
            address=u(foff+ordinal*4)
            name_rva=u(noff+i*4)
            # Every export name is bounded, but only the exact match is retained.
            chars=[]
            for j in range(256):
                c=u(rva(name_rva+j,1),'B')
                if c==0: break
                require(32<=c<=126,'export-name-encoding'); chars.append(chr(c))
            else: raise MappingError('export-name-bound')
            require(chars and re.fullmatch(r'[A-Za-z_?@$][A-Za-z0-9_?@$.]*',''.join(chars)), 'export-name-form')
            if address==begin and not exp<=address<exp+exp_size: names.append(''.join(chars))
    if len(names)==1 and not fragment and result['precedingInstructionIsCall']:
        result.update(status='exact',exportName=names[0],reason='exact-export-and-unwind-range')
    check()
    return result


def analyze(archive, lock, *, clock=time.monotonic, return_rva=RETURN_RVA):
    deadline=clock()+30
    def check(): require(clock()<deadline,'analysis-deadline')
    check()
    runtime=lock['runtime']; size=runtime['size']; expected=runtime['sha256']
    require(lock.get('architecture')=='arm64' and type(size) is int and 0<size<=MAX_ARCHIVE
            and isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}',expected),'lock-contract')
    path=Path(archive)
    require(not path.is_symlink(),'archive-symlink')
    with path.open('rb') as held:
        before=os.fstat(held.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size==size,'archive-size-or-type')
        check(); blob=held.read(size+1); check()
        require(len(blob)==size,'archive-size')
        digest=hashlib.sha256(blob).hexdigest(); check()
        after=os.fstat(held.fileno())
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'archive-changed')
        require(digest==expected,'archive-sha256')
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            check(); entries=z.infolist(); require(len(entries)<=100000,'zip-entry-count')
            candidates=[v for v in entries if v.filename.replace('\\','/').rstrip('/').split('/')[-1].rstrip(' .').casefold()=='sal3.dll']
            require(len(candidates)==1 and candidates[0].filename=='program/sal3.dll','exact-member-required')
            member=candidates[0]; mode=member.external_attr>>16
            require(not member.is_dir() and not member.external_attr&0x10 and stat.S_IFMT(mode) in (0,stat.S_IFREG)
                    and not member.flag_bits&1 and 0<member.file_size<=MAX_MEMBER,'member-type-or-size')
            with z.open(member) as stream:
                chunks=[]; total=0
                while True:
                    check(); chunk=stream.read(min(1024*1024,MAX_MEMBER+1-total)); check()
                    if not chunk: break
                    total+=len(chunk); require(total<=MAX_MEMBER,'member-decompression-bound'); chunks.append(chunk)
                data=b''.join(chunks)
            require(len(data)==member.file_size,'member-size-mismatch')
        result=map_pe(data,return_rva,check)
        result.update(schemaVersion=1,kind='static-sal-offset-mapping',acceptance=False,
                      archiveSha256=digest,archiveSize=size,member='program/sal3.dll',
                      memberSha256=hashlib.sha256(data).hexdigest(),memberSize=len(data),
                      sourceCoreCommit=runtime.get('sourceCoreCommit') if re.fullmatch('[0-9a-f]{40}',str(runtime.get('sourceCoreCommit'))) else None,
                      analysisBudgetSeconds=30)
        check(); return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True,type=Path)
    parser.add_argument('--lock',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        require(args.lock.stat().st_size<=65536,'lock-size')
        result=analyze(args.archive,json.loads(args.lock.read_text(encoding='utf-8')))
        code=0
    except Exception as exc:
        result={'schemaVersion':1,'kind':'static-sal-offset-mapping','acceptance':False,
                'status':'rejected','failureClass':type(exc).__name__,
                'reason':str(exc) if isinstance(exc,MappingError) else 'input-or-parser-failure'}
        code=1
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return code


if __name__=='__main__': raise SystemExit(main())
