"""Fail-closed evidence admission and authentic LO CPython source reconstruction."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def identity(path):
    path=Path(path)
    return {'path':str(path), 'bytes':path.stat().st_size, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def tree_digest(root):
    entries=[]
    for path in sorted(root.rglob('*'),key=lambda p:p.relative_to(root).as_posix()):
        if path.is_file():
            entry=identity(path);entry['path']=path.relative_to(root).as_posix();entry['type']='file'
            entries.append(json.dumps(entry,sort_keys=True,separators=(',',':'))+'\n')
    return hashlib.sha256(''.join(entries).encode()).hexdigest()


def verify_file(path, size, digest):
    got=identity(path)
    if (size is not None and got['bytes'] != size) or got['sha256'] != digest:
        raise ValueError('Source pin mismatch: '+str(path))
    return got


def verify_recipes(data):
    pins=json.loads((data/'source-pins.json').read_text())
    for name,digest in pins['recipes'].items(): verify_file(data/name,None,digest)
    return pins


def expected_inputs(data):
    raw=json.loads((data/'pythoncore-actual-link-inputs.json').read_text())
    names=[p.replace('\\','/').split('/')[-1].lower() for p in raw['inputs']]
    if len(names)!=235 or len(set(names))!=235: raise ValueError('Original input ledger corrupt')
    return names


def check_inputs(actual, expected):
    if sorted(actual)!=sorted(expected): raise ValueError('Complete 234 object + 1 resource closure differs')


def windows_path(value):
    import ntpath
    if not ntpath.isabs(value) or not re.match(r'^[A-Za-z]:[\\/]',value):
        raise ValueError('Resolved absolute Windows tool path required')
    return ntpath.normpath(value).replace('\\','/').rstrip('/').casefold()


def bind_tools(log, case, inventory):
    if not inventory:raise ValueError('Actual tool inventory binding required')
    root=windows_path(inventory['toolsRoot'])
    version=inventory['toolsetVersion']
    if version!='14.51.36231' or not root.endswith('/'+version):raise ValueError('Selected toolset version/root differs')
    host='hostx86' if case=='baseline' else 'hostarm64'
    observed={windows_path(t['path']):t for t in inventory['observedTools']}
    expected={windows_path(t['path']):t for t in inventory['tools']}
    matches=re.findall(r'^\s*(?:\d+(?::\d+)?>)?\s*"?([A-Za-z]:[\\/][^\r\n]*?[\\/](?:CL|link)\.exe)"?\s+/',log,re.I|re.M)
    selected=[]
    for path in matches:
        normalized=windows_path(path)
        # Original solution has an x64 freeze helper; only ARM64-target invocations bind this arm.
        if not re.search(r'/host[^/]+/arm64/(?:cl|link)\.exe$',normalized):continue
        selected.append(normalized)
        if normalized not in expected or not normalized.startswith(root+'/bin/'+host+'/arm64/'):
            raise ValueError('Emitted tool path differs from selected inventoried root/host')
    proof=[]
    for name in ['cl.exe','link.exe','c2.dll']:
        path=root+'/bin/'+host+'/arm64/'+name
        before=expected.get(path);after=observed.get(path)
        if not before or not after or any(before.get(k)!=after.get(k) for k in ['sha256','size','machine','fileVersion','productVersion']):
            raise ValueError('Actual selected tool bytes/resource version differ from inventory')
        if before['machine']!=(0x14c if case=='baseline' else 0xAA64) or not before.get('fileVersion'):
            raise ValueError('Selected tool PE/resource version missing')
        if name=='cl.exe' and not re.match(r'^19\.51\.36260(?:\D|$)',before['fileVersion']):
            raise ValueError('Observed compiler resource version differs from Native21')
        if name!='c2.dll':
            if path not in selected:raise ValueError('Actual emitted selected tool command missing')
            proof.append(dict(before,emittedAbsolutePath=path,postBuildIdentity=after))
    roots=re.findall(r'PythonControl actual task override: Platform=ARM64 VCToolsInstallDir=(.*?) VCToolsVersion=(\S+)',log,re.I)
    if not roots or any(windows_path(p)!=root or v!=version for p,v in roots):
        raise ValueError('Evaluated VCToolsInstallDir/version differ from selected inventory')
    return proof


def admit_build(log, code, case, inventory=None):
    if case=='baseline' and code not in [0,1]:raise ValueError('Expected direct MSBuild normal failure exit1; crash/other exit rejected')
    binding=bind_tools(log,case,inventory)
    summaries=re.findall(r'^\s*(\d+) Error\(s\)\s*$',log,re.M)
    diagnostics=[line for line in log.splitlines() if re.search(r'\berror(?:\s+[A-Za-z]+\d+)?\s*:',line,re.I)]
    log=log.replace('\\','/')
    host='HostX86' if case=='baseline' else 'Hostarm64'
    commands='\n'.join(line for line in log.splitlines() if re.search(r'(?:^|/)(?:CL|link)\.exe"?\s+/',line,re.I))
    for tool in ['CL.exe','link.exe']:
        if not re.search(re.escape(host)+r'/arm64/'+re.escape(tool),commands,re.I):
            raise ValueError('Actual selected '+host+' '+tool+' missing')
    for flag in ['/O2','/GL','/MP','/Zm200','/LTCG','/MACHINE:ARM64']:
        if not re.search(re.escape(flag)+r'(?=\s|$)',commands,re.I): raise ValueError('Missing '+flag)
    if case=='baseline' and code==0 and 'Build succeeded.' in log and 'C1002' not in log and summaries and set(summaries)=={'0'} and not diagnostics:
        return {'status':'non-reproduction','causalCorrectionProven':False,'toolBinding':binding}
    if case=='baseline':
        exact=r'Hacl_Hash_SHA2\.c\(243\): fatal error C1002: compiler is out of heap space in pass 2'
        if not summaries or set(summaries)!={'1'} or not diagnostics or any(not re.search(exact,line,re.I) for line in diagnostics):
            raise ValueError('Baseline error summary/diagnostics include unrelated failure')
        required=[r'Hacl_Hash_SHA2\.c\(243\): fatal error C1002: compiler is out of heap space in pass 2',
                  r'32-bit linker.*ran out of heap space',r'restarting link with 64-bit linker.*HostX64/arm64/link.exe',
                  r'Finished generating code',r'pythoncore.vcxproj.*FAILED\.',r'Build FAILED\.']
        if code!=1 or not all(re.search(p,log,re.I) for p in required): raise ValueError('Exact original MSBuild failure not reproduced')
        return {'status':'reproduced','causalCorrectionProven':False,'toolBinding':binding}
    if code!=0 or 'Build succeeded.' not in log or not summaries or set(summaries)!={'0'} or diagnostics: raise ValueError('Candidate MSBuild failure')
    if re.search(r'HostX(?:86|64)/arm64/(?:CL|link)\.exe|/Od\b',commands,re.I) or re.search(r'restarting link|fatal error C1002',log,re.I): raise ValueError('Candidate host fallback or changed optimization')
    return {'status':'passed','toolBinding':binding}


def admit_runtime(proof, exe, dll):
    norm=lambda p: str(p).replace('\\','/').lower()
    if any(norm(proof[k])!=norm(v) for k,v in [('executable',exe),('dll',dll)]): raise ValueError('Runtime image identity differs')
    if proof['processMachine']!=0 or proof['nativeMachine']!=0xAA64 or proof['module']!='built-in' or proof['constructors']!=['_sha2']*4 or proof['testsPassed'] is not True:
        raise ValueError('Native builtin SHA2 identity/KAT failure')


def unpack(archive, target):
    if target.exists(): raise ValueError('Preserve existing source directory')
    target.mkdir()
    with tarfile.open(archive) as tar:
        for m in tar.getmembers():
            parts=Path(m.name).parts
            if m.issym() or m.islnk() or m.isdev() or m.name.startswith('/') or '..' in parts: raise ValueError('Unsafe source archive entry')
            m.name=str(Path(*parts[1:]))
            if m.name!='.': tar.extract(m,target,filter='data')


def unzip(archive,target):
    with zipfile.ZipFile(archive) as z:
        if any(Path(n).is_absolute() or '..' in Path(n).parts for n in z.namelist()): raise ValueError('Unsafe wheel/bootstrap')
        z.extractall(target)


def apply_patch(source, patch, tool, out):
    level=patch.name.rsplit('.',1)[-1]
    argv=[str(tool),'-f','-s','-p'+(level if level.isdigit() else ('0' if patch.name in ['missinginclude.patch','werror-undef.patch'] else '1')),'--fuzz=0','-i',str(patch.resolve())]
    result=subprocess.run(argv,cwd=source,capture_output=True,timeout=90)
    Path(str(out)+'.stdout.log').write_bytes(result.stdout);Path(str(out)+'.stderr.log').write_bytes(result.stderr)
    write_json(str(out)+'.json',{'argv':argv,'cwd':str(source),'exitCode':result.returncode})
    if result.returncode: raise ValueError('Authentic patch failed: '+patch.name)


def prepare(data, cache, work, out, patch_tool):
    pins=verify_recipes(data)
    for name in ['python','zlib','bootstrap']:
        p=pins[name];filename=p.get('filename',Path(p.get('path','')).name)
        verify_file(cache/filename,p.get('bytes'),p['sha256'])
    source=work/'python3';unpack(cache/'Python-3.13.15.tar.xz',source)
    unzip(cache/'python.3.12.8.nupkg',source/'externals/pythonx86')
    shutil.copyfile(source/'PC/pyconfig.h.in',source/'PC/pyconfig.h')
    wheels=[]
    for rel in ['Lib/test/wheeldata/setuptools-79.0.1-py3-none-any.whl','Lib/ensurepip/_bundled/pip-26.2.1-py3-none-any.whl']:
        wheels.append(identity(source/rel));unzip(source/rel,source/'Lib')
    (source/'Lib/setuptools/_vendor/jaraco/text/Lorem ipsum.txt').rename(source/'Lib/setuptools/_vendor/jaraco/text/Lorem_ipsum.txt')
    eols=[source/'PCbuild/libffi.props',source/'PCbuild/pcbuild.sln']
    for p in eols:p.write_bytes(p.read_bytes().replace(b'\r',b''))
    for name in pins['patches']:apply_patch(source,data/name,patch_tool,out/('patch-'+name))
    for p in eols:p.write_bytes((p.read_bytes().replace(b'\r',b'').rstrip(b'\n')+b'\n').replace(b'\n',b'\r\n'))
    zlib=work/'zlib';unpack(cache/'zlib-1.3.2.tar.xz',zlib)
    for name in pins.get('zlibPatches',[]):apply_patch(zlib,data/name,patch_tool,out/('patch-'+name))
    (zlib/'x64').mkdir(exist_ok=True)
    for name in pins.get('zlibX64Copies',[]):shutil.copyfile(zlib/name,zlib/('x64/'+name))
    for key,base in [('python',source),('zlib',zlib)]:
        if tree_digest(base)!=pins['effectiveTrees'][key]:raise ValueError('Effective source content-tree differs from independent authentic gbuild reconstruction: '+key)
    snapshot=[identity(p) for base in [source,zlib] for p in sorted(base.rglob('*')) if p.is_file()]
    write_json(out/'reconstructed-source-inventory.json',snapshot)
    write_json(out/'source-plan.json',{'source':str(source),'zlib':str(zlib),'wheels':wheels,'patches':pins['patches'],'exactOriginalReplay':False,'scope':'Pinned reconstruction; original generated sources, objects and projects not retained. Complete pythoncore and interpreter only; full extensions pending compiled LO dependencies.'})
    # Identical prepared bytes, independently generated build outputs per arm.
    for case in ['baseline','candidate']:shutil.copytree(source,work/case)


def collect(work,out,case):
    src=work/case;dst=out/(case+'-retained');dst.mkdir(exist_ok=False)
    for p in src.rglob('*'):
        if p.is_file() and (p.suffix.lower() in ['.h','.rsp','.tlog','.obj','.res','.vcxproj','.props','.targets','.sln','.dll','.exe','.pdb','.lib','.exp','.txt']):
            target=dst/p.relative_to(src);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
    write_json(out/(case+'-generated-inventory.json'),[identity(p) for p in dst.rglob('*') if p.is_file()])


def admit(data,work,out,case):
    r=json.loads((out/(case+'-build.command.json')).read_text(encoding='utf-8-sig'))
    if r.get('forcedTermination') or not r.get('pipeDrainComplete') or not r.get('directProcessDeathVerified') or r.get('cleanupErrors'):raise ValueError('Build termination/drain incomplete')
    text='\n'.join((out/(case+'-build.'+s+'.log')).read_text(errors='replace') for s in ['stdout','stderr'])
    try:
        inventory=json.loads((out/(case+'-tool-inventory.json')).read_text(encoding='utf-8-sig'))
        proof=admit_build(text,r['exitCode'],case,inventory)
    except ValueError as error:
        write_json(out/(case+'-admission.json'),{'status':'non-reproduction' if case=='baseline' else 'failed','causalCorrectionProven':False,'error':str(error)})
        raise
    obj=work/case/'PCbuild/obj/313arm64_Release/pythoncore'
    inputs=[p.name.lower() for p in obj.iterdir() if p.suffix.lower() in ['.obj','.res']]
    check_inputs(inputs,expected_inputs(data))
    # Check actual logged Link input paths too; directory contents alone can be stale.
    logged=[p.lower() for p in re.findall(r'pythoncore[\\/]+([^\s"<>]+\.(?:obj|res))',text,re.I)]
    check_inputs(sorted(set(logged)),expected_inputs(data))
    proof['completeInputCount']=len(inputs);write_json(out/(case+'-admission.json'),proof)


if __name__=='__main__':
    cmd,*args=sys.argv[1:]
    paths=list(map(Path,args))
    if cmd=='prepare':prepare(*paths)
    elif cmd=='collect':collect(paths[0],paths[1],args[2])
    elif cmd=='admit':admit(paths[0],paths[1],paths[2],args[3])
    else:raise SystemExit('Unknown operation')
