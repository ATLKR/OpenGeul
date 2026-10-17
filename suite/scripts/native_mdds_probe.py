"""Bounded diagnostic source preparation and admission. No production hook."""
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import sys
import tarfile

HPP = 'include/mdds/flat_segment_tree.hpp'
INL = 'include/mdds/flat_segment_tree_def.inl'
NODE = 'include/mdds/node.hpp'
PINS = {
 'mdds': (648256, '673f5bb94612dbba581fc92b99b5e5dd1a53e29496a5dbc936432f6b0687c112'),
 'lo': (302435508, '296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785'),
 'boost': (21664068, '2f975c10da79511c2f218189fc8a12eef1a92e3bd18206e9841d406296d065eb'),
}
PATCH_SHA='3411f0814815e06914ea1fbf50c5428af86cbed68c82c0481e09dd62bc8a22c6'
SOURCE_PINS={HPP:(29117,'ad0e52219db6c8194cadee54b30cec34f55350c4b587a1bc1764d37701276fa8'),
 INL:(27738,'5afeba9fed6c8e821bb02c4dc654d29c18dcc23d51bffbc3f48986fc2b67b7b7'),
 NODE:(13669,'97583fffc6466c675c2d0ff8f623242f5e7bd0e9b5b8ce5d58954190cbb9aa94')}
DEFINITION = b'template<typename Key, typename Value>\nbool flat_segment_tree<Key, Value>::operator==(const flat_segment_tree& other) const noexcept(nothrow_eq_comparable_v)\n{\n    const node* n1 = m_left_leaf.get();\n    const node* n2 = other.m_left_leaf.get();\n\n    if ((!n1 && n2) || (n1 && !n2))\n        // Either one of them is nullptr;\n        return false;\n\n    while (n1)\n    {\n        if (!n2)\n            return false;\n\n        if (!(n1->key == n2->key))\n            return false;\n\n        if (!(n1->value_leaf == n2->value_leaf))\n            return false;\n\n        n1 = n1->next.get();\n        n2 = n2->next.get();\n    }\n\n    if (n2)\n        // n1 is nullptr, but n2 is not.\n        return false;\n\n    // All leaf nodes are equal.\n    return true;\n}\n\n'
AFTER_DEFINITION = b'template<typename Key, typename Value>\nconst typename flat_segment_tree<Key, Value>::node* flat_segment_tree<Key, Value>::get_insertion_pos_leaf_reverse('
DECL = b'    bool operator==(const flat_segment_tree& other) const noexcept(nothrow_eq_comparable_v);\n'
IN_CLASS = DECL[:-2] + b'\n' + b''.join(b'    '+line if line.strip() else line for line in DEFINITION.split(b'\n',2)[2].splitlines(keepends=True)).rstrip(b'\n') + b'\n'

def sha(data):return hashlib.sha256(data).hexdigest()
def identity(path):
    p=Path(path);h=hashlib.sha256()
    with p.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
    return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def exact(data, pin):
    if (len(data),sha(data))!=pin:raise ValueError('Exact source bytes/hash guard rejected drift or repeat')
def save(path,value):
    with Path(path).open('x',encoding='utf-8') as out:json.dump(value,out,indent=2);out.write('\n')
def write(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as out:out.write(data)
def relocate(hpp,inl):
    exact(hpp,SOURCE_PINS[HPP]);exact(inl,SOURCE_PINS[INL])
    if hpp.count(DECL)!=1 or inl.count(DEFINITION)!=1:raise ValueError('Exact once equality anchors required')
    return hpp.replace(DECL,IN_CLASS),inl.replace(DEFINITION,b'')
def apply_lo_patch(node,patch):
    exact(node,SOURCE_PINS[NODE]);exact(patch,(3732,PATCH_SHA))
    # Apply every actual unified hunk, with exact context once and no fuzz.
    lines=patch.splitlines(keepends=True);headers=[i for i,line in enumerate(lines) if line.startswith(b'@@ ')]
    if len(headers)!=1 or b'+++ mdds/include/mdds/node.hpp\t' not in patch:raise ValueError('Unexpected actual LO patch shape')
    hunk=lines[headers[0]+1:];old=b'';new=b''
    for line in hunk:
        if line[:1] not in (b' ',b'-',b'+'):raise ValueError('Unsupported patch hunk line')
        if line[:1] in (b' ',b'-'):old+=line[1:]
        if line[:1] in (b' ',b'+'):new+=line[1:]
    if node.count(old)!=1:raise ValueError('Original node patch context not found exactly once')
    return node.replace(old,new)
def safe_relative(name,prefix):
    parts=PurePosixPath(name).parts
    if not parts or name.startswith('/') or '\\' in name or ':' in name or '..' in parts or len(name)>700 or parts[0]!=prefix:
        raise ValueError('Unsafe or foreign source archive member')
    return '/'.join(parts[1:])
def extract_complete(archive,root,prefix,count_limit,byte_limit):
    root=Path(root)
    if root.exists():raise ValueError('Preserve existing source tree')
    root.mkdir();seen=set();seen_fold=set();rows=[];total=0
    with tarfile.open(archive,'r|*') as source:
        for item in source:
            relative=safe_relative(item.name,prefix)
            key=relative.casefold()
            if relative in seen or key in seen_fold or len(seen)>=count_limit:raise ValueError('Source duplicate/case collision/member budget')
            seen.add(relative);seen_fold.add(key);target=root/relative
            if item.isdir():
                target.mkdir(parents=True,exist_ok=True);row=dict(path=relative,kind='directory')
            elif item.isfile():
                if not relative or not 0<=item.size<=128*1024*1024:raise ValueError('Regular source member size bound')
                total+=item.size
                if total>byte_limit:raise ValueError('Complete archive source byte budget')
                data=source.extractfile(item).read(item.size+1)
                if len(data)!=item.size:raise ValueError('Truncated archive member')
                write(target,data);row=dict(path=relative,kind='regular',bytes=len(data),sha256=sha(data))
            else:raise ValueError('Complete diagnostic sources must contain only directories and regular files')
            rows.append(row)
    return dict(memberCount=len(rows),regularBytes=total,members=rows)
def selected_lo(archive):
    wanted={'download.lst','external/mdds/Makefile','external/mdds/Module_mdds.mk','external/mdds/README',
            'external/mdds/UnpackedTarball_mdds.mk','external/mdds/gcc-12-silence-use-after-free.patch.1'}
    result={};count=0;prefix='libreoffice-26.8.1.1/'
    with tarfile.open(archive,'r|xz') as source:
        for item in source:
            count+=1
            if count>1000000:raise ValueError('LO archive member budget')
            name=item.name[len(prefix):] if item.name.startswith(prefix) else ''
            if name not in wanted:continue
            if name in result or not item.isfile() or not 0<item.size<=1024*1024:raise ValueError('Invalid selected LO member')
            data=source.extractfile(item).read(item.size+1)
            if len(data)!=item.size:raise ValueError('Truncated selected LO source')
            result[name]=data
    if set(result)!=wanted:raise ValueError('Missing closed LO MDDS recipe members')
    for name, pin in [('MDDS',PINS['mdds'][1]),('BOOST',PINS['boost'][1])]:
        if not re.search(r'^'+name+r'_SHA256SUM\s*:=\s*'+pin+r'\s*$',result['download.lst'].decode(),re.M):raise ValueError('Actual LO external hash pin differs')
    for name,file in [('MDDS','mdds-3.2.1.tar.xz'),('BOOST','boost_1_91_0.tar.xz')]:
        if not re.search(r'^'+name+r'_TARBALL\s*:=\s*'+re.escape(file)+r'\s*$',result['download.lst'].decode(),re.M):raise ValueError('Actual LO external archive filename differs')
    recipe=result['external/mdds/UnpackedTarball_mdds.mk']
    exact(recipe,(645,'f315da733c95aeeae29656318289fae9a90bff2eab46478972a9d8472a10208a'))
    return result,count

def prepare(mdds,lo,boost,work,out,probe):
    work,out=Path(work),Path(out);sources={}
    for name,path in [('mdds',mdds),('lo',lo),('boost',boost)]:
        row=identity(path)
        if (row['bytes'],row['sha256'])!=PINS[name]:raise ValueError('Complete authenticated source archive differs: '+name)
        sources[name]=row
    exact(Path(probe).read_bytes(),(1830,'86b1a4a416bd173587fd1848aecd275611ad0281961eb63204316de8c1a792c3'))
    selected,count=selected_lo(lo)
    for name,data in selected.items():write(out/'lo-source'/name,data)
    patch=selected['external/mdds/gcc-12-silence-use-after-free.patch.1']
    a=work/'original';b=work/'candidate';boost_root=work/'boost'
    manifest=extract_complete(mdds,a,'mdds-3.2.1',20000,64*1024*1024)
    save(out/'mdds-complete-archive-census.json',manifest)
    original_node=(a/NODE).read_bytes();(a/NODE).write_bytes(apply_lo_patch(original_node,patch))
    shutil.copytree(a,b);hpp,inl=relocate((b/HPP).read_bytes(),(b/INL).read_bytes())
    (b/HPP).write_bytes(hpp);(b/INL).write_bytes(inl)
    # Exact complete file census verifies no omissions, extras or hidden edits.
    before={r['path']:r['sha256'] for r in manifest['members'] if r['kind']=='regular'}
    cases=[];actuals={}
    for name,root in [('original',a),('candidate',b)]:
        actual={str(p.relative_to(root)).replace('\\','/'):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
        if set(actual)!=set(before):raise ValueError('Complete MDDS tree closure differs')
        changed={n for n in actual if actual[n]!=before[n]}
        if changed!=({NODE} if name=='original' else {NODE,HPP,INL}):raise ValueError('Unexpected scratch source edits')
        actuals[name]=actual
        touched=[]
        for n in (NODE,HPP,INL):
            p=root/n;write(out/name/n,p.read_bytes());touched.append(identity(p))
        cases.append(dict(name=name,root=str(root),include=str(root/'include'),touchedFiles=touched))
    if actuals['original'][NODE]!=actuals['candidate'][NODE]:raise ValueError('A/B original LO node patch differs')
    diff=''.join(''.join(difflib.unified_diff((a/n).read_text().splitlines(True),(b/n).read_text().splitlines(True),fromfile='original/'+n,tofile='candidate/'+n)) for n in (HPP,INL))
    write(out/'candidate-only.diff',diff.encode())
    boost_manifest=extract_complete(boost,boost_root,'boost_1_91_0',100000,512*1024*1024)
    save(out/'boost-complete-archive-census.json',boost_manifest)
    wrapper=work/'native-wrapper.cpp';write(wrapper,WRAPPER.encode())
    write(out/'native-wrapper.cpp',wrapper.read_bytes());write(out/'mdds-equality-probe.cpp',Path(probe).read_bytes())
    plan=dict(schemaVersion=1,scope='diagnostic scratch A/B only; no production hook or original gnumeric TU/PCH replay',sources=sources,
              loArchiveMemberCount=count,sourceMembers=[dict(path=n,bytes=len(d),sha256=sha(d)) for n,d in selected.items()],
              patch=dict(bytes=len(patch),sha256=sha(patch),strip=1,allActualHunksApplied=True,nodeChangeUnconditional=True),
              mddsFileCount=len(before),boostInclude=str(boost_root),cases=cases,wrapper=str(wrapper),wrapperSha256=sha(wrapper.read_bytes()),
              probe=identity(probe),candidateDiff=identity(out/'candidate-only.diff'))
    save(out/'source-plan.json',plan)

def clean_command(command,expected=None):
    if (expected is not None and command['exitCode']!=expected) or command['forcedTermination'] or not command['pipeDrainComplete'] or not command['directProcessDeathVerified'] or command.get('cleanupErrors'):
        raise ValueError('Owned command exit/death/drain evidence rejected')
    if not isinstance(command.get('creationUtcTicks'),int) or command['creationUtcTicks']<=0 or command.get('pid',0)<=0:raise ValueError('Process creation ownership missing')
def admit_original(command,log):
    # Exact direct cl diagnostic exit; NTSTATUS crashes and unknown failures reject.
    clean_command(command,2)
    errors=[line for line in log.splitlines() if re.search(r'\b(?:fatal )?error [A-Z]+\d+:',line)]
    if not errors or any(not re.search(r'flat_segment_tree_def\.inl\(761\): error C2382:.*operator ==.*different exception specifications',line) for line in errors):raise ValueError('Original failure is unrelated or ambiguous')
    if not re.search(r"flat_segment_tree\.hpp\(501\): note: see declaration of .*operator ==",log):raise ValueError('Matching original equality declaration note missing')
def object_identity(path):
    data=Path(path).read_bytes()
    if len(data)<20:raise ValueError('Truncated COFF object')
    kind='COFF-object'
    if data[:4]==b'\0\0\xff\xff':
        if len(data)<56 or struct.unpack_from('<H',data,4)[0]!=2 or data[12:28]!=bytes.fromhex('c7a1bad1eebaa94baf20faf66aa4dcb8'):
            raise ValueError('Invalid bigobj COFF header')
        machine=struct.unpack_from('<H',data,6)[0];kind='COFF-bigobj'
    else:machine=struct.unpack_from('<H',data)[0]
    if machine!=0xaa64:raise ValueError('Candidate object is not native ARM64 COFF')
    return dict(identity(path),machine=machine,kind=kind)
def admit(out):
    out=Path(out)
    def command(name):return json.loads((out/(name+'.command.json')).read_bytes())
    logs=''.join((out/('original-compile.'+stream+'.log')).read_text(errors='replace') for stream in ('stdout','stderr'))
    admit_original(command('original-compile'),logs)
    for name in ('candidate-compile','candidate-runtime'):clean_command(command(name),0)
    obj=object_identity(out/'program/probe.obj')
    runtime=json.loads((out/'candidate-runtime.stdout.log').read_bytes())
    if runtime['pid']!=command('candidate-runtime')['pid'] or runtime['processMachine']!=0 or runtime['nativeMachine']!=0xaa64 or runtime['checksExit']!=0:raise ValueError('Actual native runtime identity/behavior differs')
    staged=json.loads((out/'crt-install.json').read_bytes());allowed={r['source']['name'].lower():r for r in staged['files']}
    seen=set()
    for module in runtime['loadedModules']:
        name=module['name'].lower();seen.add(name)
        if module['machine']!=0xaa64:raise ValueError('Foreign runtime CRT module')
        if name=='ucrtbase.dll':expected=str(Path(os.environ['SystemRoot'])/'System32/ucrtbase.dll')
        elif name in allowed:expected=allowed[name]['destination']
        else:raise ValueError('Unexpected CRT family module')
        if os.path.normcase(module['path'])!=os.path.normcase(expected):raise ValueError('Runtime CRT did not load from selected native location')
    if not {'msvcp140.dll','vcruntime140.dll','ucrtbase.dll'}<=seen:raise ValueError('Native runtime CRT observation incomplete')
    save(out/'admission.json',dict(schemaVersion=1,passed=True,originalRed='actual C2382 inl761 declaration hpp501',candidateObject=obj,
         runtime=runtime,engineQualified=False,originalTwoGnumericObjectsRebuilt=False,limits='No retained original two-object TU/PCH/argv; header diagnostic only. Full Native21 remains later proof.'))

# The authenticated probe remains byte-identical. This wrapper adds only native
# identity/module observations before/after invoking its unmodified main body.
WRAPPER = r'''#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <tlhelp32.h>
#include <iostream>
#include <string>
#include <cwctype>
#if !defined(_M_ARM64) || defined(_M_ARM64EC)
#error Native ARM64 ABI required
#endif
#define main mdds_original_probe_main
#include "mdds-equality-probe.cpp"
#undef main
static std::string json(const std::wstring& w) {
    int n=WideCharToMultiByte(CP_UTF8,0,w.data(),(int)w.size(),nullptr,0,nullptr,nullptr);
    std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,w.data(),(int)w.size(),s.data(),n,nullptr,nullptr);
    std::string result="\"";for(unsigned char c:s){if(c=='\\'||c=='\"')result+='\\';if(c<32)return "null";result+=(char)c;}return result+'\"';
}
int main() {
    USHORT process=0,native=0;if(!IsWow64Process2(GetCurrentProcess(),&process,&native))return 10;
    if(process!=0||native!=IMAGE_FILE_MACHINE_ARM64)return 11;
    int checked=mdds_original_probe_main();if(checked)return checked;
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE,GetCurrentProcessId());if(snapshot==INVALID_HANDLE_VALUE)return 12;
    MODULEENTRY32W row{};row.dwSize=sizeof(row);bool first=true;
    std::cout<<"{\"schemaVersion\":1,\"pid\":"<<GetCurrentProcessId()<<",\"processMachine\":"<<process<<",\"nativeMachine\":"<<native
      <<",\"checksExit\":"<<checked<<",\"loadedModules\":[";
    if(!Module32FirstW(snapshot,&row)){CloseHandle(snapshot);return 13;}
    do {
        std::wstring name=row.szModule;for(auto& c:name)c=(wchar_t)towlower(c);
        if(name.rfind(L"vcruntime",0)!=0&&name.rfind(L"msvcp",0)!=0&&name.rfind(L"concrt",0)!=0&&name.rfind(L"vccorlib",0)!=0&&name!=L"ucrtbase.dll")continue;
        auto dos=(IMAGE_DOS_HEADER*)row.modBaseAddr;if(dos->e_magic!=IMAGE_DOS_SIGNATURE){CloseHandle(snapshot);return 14;}
        auto nt=(IMAGE_NT_HEADERS64*)(row.modBaseAddr+dos->e_lfanew);if(nt->Signature!=IMAGE_NT_SIGNATURE){CloseHandle(snapshot);return 15;}
        if(!first)std::cout<<",";first=false;
        std::cout<<"{\"name\":"<<json(name)<<",\"path\":"<<json(row.szExePath)<<",\"machine\":"<<nt->FileHeader.Machine<<"}";
    }while(Module32NextW(snapshot,&row));
    if(GetLastError()!=ERROR_NO_MORE_FILES){CloseHandle(snapshot);return 16;}
    if(!CloseHandle(snapshot))return 17;
    std::cout<<"]}"<<std::endl;return 0;
}
'''

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare(*sys.argv[2:])
    elif sys.argv[1]=='admit-original':
        out=Path(sys.argv[2]);command=json.loads((out/'original-compile.command.json').read_bytes())
        log=''.join((out/('original-compile.'+s+'.log')).read_text(errors='replace') for s in ('stdout','stderr'))
        admit_original(command,log)
        save(out/'original-red-admission.json',dict(passed=True,reason='actual original C2382 inl761 with matching hpp501 declaration'))
    elif sys.argv[1]=='admit':admit(*sys.argv[2:])
    else:raise ValueError('Unexpected diagnostic phase')
