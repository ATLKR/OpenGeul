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


def windows_arguments(text):
    """Tokenize non-executable Windows argv with CRT backslash/quote rules."""
    text=re.sub(r'\s+\(TaskId:\d+\)\s*$','',text);out=[];i=0
    while i<len(text):
        while i<len(text) and text[i].isspace():i+=1
        if i==len(text):break
        word=[];quoted=False
        while i<len(text) and (quoted or not text[i].isspace()):
            if text[i]=='\\':
                start=i
                while i<len(text) and text[i]=='\\':i+=1
                count=i-start
                if i<len(text) and text[i]=='"':
                    word.extend('\\'*(count//2))
                    if count%2:word.append('"');i+=1;continue
                else:word.extend('\\'*count);continue
            if text[i]=='"':
                if quoted and i+1<len(text) and text[i+1]=='"':word.append('"');i+=2;continue
                quoted=not quoted;i+=1;continue
            word.append(text[i]);i+=1
        if quoted:raise ValueError('Unterminated Windows argv quote')
        out.append(''.join(word))
    return out


def tool_commands(log):
    """Parse actual executable tokens; Tracker metadata is never part of a tool path."""
    lines=log.split('\n');commands=[]
    first=re.compile(r'^\s*(?:\d+(?::\d+)?>)?\s*"?([A-Za-z]:[\\/][^\r\n]*?\.exe)"?\s+(/[^\r\n]*)',re.I)
    task_end=re.compile(r'\(TaskId:\d+\)\s*$')
    for i,line in enumerate(lines):
        match=first.match(line)
        if not match:continue
        path,args=match.groups();origin='direct';wrapper=None
        if path.replace('\\','/').rsplit('/',1)[-1].lower()=='tracker.exe':
            child=re.search(r'\s/c\s+"([A-Za-z]:[^"\r\n]+\.exe)"\s*(.*)',args,re.I)
            if not child:raise ValueError('Unparsed Tracker child executable')
            wrapper=path;path,args=child.groups();origin='tracker-child'
        if origin=='direct' and path.replace('\\','/').rsplit('/',1)[-1].lower() not in ['cl.exe','link.exe','rc.exe']:continue
        raw=[line];end=i+1;terminated=bool(task_end.search(line))
        if path.lower().endswith('link.exe') and not terminated:
            while end<len(lines):
                next_line=lines[end]
                if first.match(next_line) or re.match(r'^\s*(?:Tracking command:|Task Parameter:|PythonControl |Build |Done )',next_line):break
                raw.append(next_line);args+='\n'+next_line;end+=1
                if task_end.search(next_line):terminated=True;break
        commands.append({'path':path,'arguments':args,'origin':origin,'wrapper':wrapper,'physicalLfStart':i+1,'physicalLfEnd':end,'rawLines':raw,'expandedCommandTerminated':terminated})
    return commands


def scoped_commands(log, inventory):
    root=windows_path(inventory['toolsRoot']);product=[];helpers=[];resources=[]
    source=inventory.get('productSourceRoot')
    for command in tool_commands(log):
        path=windows_path(command['path'])
        if re.search(r'/host[^/]+/arm64/(?:cl|link)\.exe$',path):
            product.append(command);continue
        if path.endswith('/rc.exe'):
            import ntpath
            bins={windows_path(p.strip()) for p in re.findall(r'^\s*SdkBinPath = ([^\r\n]+)',log,re.M)}
            if windows_path(ntpath.dirname(path)) not in bins or not re.search(r'/10\.0\.26100\.0/(?:x86|arm64)/rc\.exe$',path):
                raise ValueError('Resource compiler is outside selected pinned SDK bin scope')
            tokens=windows_arguments(command['arguments'])
            outputs=[t[3:] for t in tokens if t.lower().startswith('/fo')]
            sources=[t for t in tokens if t.lower().endswith('.rc') and not t.startswith('/')]
            expected_output=source+'/PCbuild/obj/313arm64_Release/pythoncore/python_nt.res' if source else ''
            if not source or len(outputs)!=1 or windows_path(outputs[0])!=windows_path(expected_output) or len(sources)!=1 or windows_path(ntpath.join(source,'PCbuild',sources[0]))!=windows_path(source+'/PC/python_nt.rc'):
                raise ValueError('Resource compiler input/output is outside authentic product resource scope')
            resources.append(dict(command,scope='selected SDK10.0.26100.0 resource tool; exact python_nt resource',resourceOutput=outputs[0],resourceSource=sources[0]));continue
        helper=re.fullmatch(re.escape(root)+r'/bin/host(?:x86|x64|arm64)/x64/(cl|link)\.exe',path)
        if not helper:raise ValueError('Unbound compiler/linker outside product or authentic helper scope')
        flag=r'/Fo"([^"\r\n]+)"' if helper[1]=='cl' else r'/OUT:"([^"\r\n]+)"'
        target=re.search(flag,command['arguments'],re.I)
        suffix='PCbuild/obj/313amd64_Release/_freeze_module' if helper[1]=='cl' else 'PCbuild/amd64/_freeze_module.exe'
        if not source or not target or windows_path(target[1])!=windows_path(source+'/'+suffix):
            raise ValueError('x64 build helper output is outside authentic _freeze_module scope')
        helpers.append(dict(command,scope='unchanged x64 _freeze_module build host; same selected VS root'))
    return product,helpers,resources


def link_input_evidence(log, source_root, expected):
    links=[c for c in tool_commands(log) if c['origin']=='direct' and re.search(r'/host[^/]+/arm64/link\.exe$',windows_path(c['path']))]
    if len(links)!=1:raise ValueError('Exactly one actual expanded ARM64 product Link command required')
    command=links[0];args=command['arguments']
    if not command['expandedCommandTerminated']:raise ValueError('Expanded Link argv has no terminal task boundary')
    output=re.search(r'/OUT:"([^"\r\n]+)"',args,re.I)
    if not output or windows_path(output[1])!=windows_path(source_root+'/PCbuild/arm64/python313.dll'):
        raise ValueError('Actual Link output differs from expected product DLL')
    paths=[]
    for token in windows_arguments(args):
        if token.startswith('@'):raise ValueError('Unparsed Link response input is not expanded evidence')
        if token.startswith('/'):
            if re.search(r'\.(?:obj|res)$',token,re.I):raise ValueError('Unsupported Link option embeds object/resource input')
            continue
        if token.lower().endswith(('.obj','.res')):paths.append(token)
        elif not token.lower().endswith('.lib'):raise ValueError('Unparsed Link operand')
    import ntpath
    expected_root=windows_path(source_root+'/PCbuild/obj/313arm64_Release/pythoncore')
    if any(windows_path(ntpath.dirname(p))!=expected_root for p in paths):raise ValueError('Link input escaped product object root')
    names=[ntpath.basename(p).lower() for p in paths];check_inputs(names,expected)
    return {'inputCount':len(names),'inputs':names,'absoluteInputs':paths,'physicalLfStart':command['physicalLfStart'],'physicalLfEnd':command['physicalLfEnd'],'rawLines':command['rawLines'],'rawSpanSha256':hashlib.sha256('\n'.join(command['rawLines']).encode()).hexdigest(),'rawSpanConvention':'Inclusive physical LF lines joined by LF, excluding final LF; CR bytes preserved.'}


def bind_tools(log, case, inventory):
    if not inventory:raise ValueError('Actual tool inventory binding required')
    root=windows_path(inventory['toolsRoot'])
    version=inventory['toolsetVersion']
    if version!='14.51.36231' or not root.endswith('/'+version):raise ValueError('Selected toolset version/root differs')
    host='hostx86' if case=='baseline' else 'hostarm64'
    observed={windows_path(t['path']):t for t in inventory['observedTools']}
    expected={windows_path(t['path']):t for t in inventory['tools']}
    product,_,_=scoped_commands(log,inventory)
    selected=[]
    for command in product:
        normalized=windows_path(command['path']);selected.append(normalized)
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
    product,helpers,resources=scoped_commands(log,inventory)
    log=log.replace('\\','/')
    host='HostX86' if case=='baseline' else 'Hostarm64'
    commands='\n'.join(c['path'].replace('\\','/')+' '+c['arguments'] for c in product)
    for tool in ['CL.exe','link.exe']:
        if not re.search(re.escape(host)+r'/arm64/'+re.escape(tool),commands,re.I):
            raise ValueError('Actual selected '+host+' '+tool+' missing')
    for command in product:
        tokens={t.casefold() for t in windows_arguments(command['arguments'])}
        flags=['/o2','/gl','/mp','/zm200'] if command['path'].lower().endswith('cl.exe') else ['/ltcg','/machine:arm64']
        if any(flag not in tokens for flag in flags):raise ValueError('Required flag missing from an actual product tool invocation')
        if tokens.intersection({'/od','/o1','/gl-','/mp-','/ltcg:off'}):raise ValueError('Product optimization or parallelism disabled')
    if case=='baseline' and code==0 and 'Build succeeded.' in log and 'C1002' not in log and summaries and set(summaries)=={'0'} and not diagnostics:
        return {'status':'non-reproduction','originalSiteReproduced':False,'causalCorrectionProven':False,'toolBinding':binding,'buildHostHelpers':helpers,'resourceCompilers':resources}
    if case=='baseline':
        original=r'Hacl_Hash_SHA2\.c\(243\): fatal error C1002: compiler is out of heap space in pass 2'
        variant=r'Objects[\\/]unicodetype_db\.h\(4295\): fatal error C1002: compiler is out of heap space in pass 2'
        exact_original=bool(diagnostics) and all(re.search(original,line,re.I) for line in diagnostics)
        observed_variant=bool(diagnostics) and all(re.search(variant,line,re.I) for line in diagnostics)
        if not summaries or set(summaries)!={'1'} or not (exact_original or observed_variant):
            raise ValueError('Baseline error summary/diagnostics include unrelated failure')
        if observed_variant:
            source=inventory.get('productSourceRoot')
            sites=[re.search(r'([A-Za-z]:[^\r\n]*?[\\/]Objects[\\/]unicodetype_db\.h)\(4295\)',line,re.I) for line in diagnostics]
            if not source or any(not m or windows_path(m[1])!=windows_path(source+'/Objects/unicodetype_db.h') for m in sites):
                raise ValueError('Observed heap variant source path is not bound to product source root')
        required=[r'32-bit linker.*ran out of heap space',r'restarting link with 64-bit linker.*HostX64/arm64/link.exe',
                  r'Finished generating code',r'pythoncore.vcxproj.*FAILED\.',r'Build FAILED\.']
        if code!=1 or not all(re.search(p,log,re.I) for p in required):raise ValueError('Expected complete MSBuild heap-failure sequence absent')
        return {'status':'reproduced' if exact_original else 'observed-heap-site-variant','originalSiteReproduced':exact_original,'observedHeapSite':'Hacl_Hash_SHA2.c(243)' if exact_original else 'Objects/unicodetype_db.h(4295)','causalCorrectionProven':False,'toolBinding':binding,'buildHostHelpers':helpers,'resourceCompilers':resources}
    if code!=0 or 'Build succeeded.' not in log or not summaries or set(summaries)!={'0'} or diagnostics: raise ValueError('Candidate MSBuild failure')
    if re.search(r'HostX(?:86|64)/arm64/(?:CL|link)\.exe|/Od\b',commands,re.I) or re.search(r'restarting link|fatal error C1002',log,re.I): raise ValueError('Candidate host fallback or changed optimization')
    return {'status':'passed','toolBinding':binding,'buildHostHelpers':helpers,'resourceCompilers':resources}


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


def patch_targets(patch, level):
    targets=[]
    for line in patch.read_bytes().split(b'\n'):
        if not line.startswith(b'+++ '):continue
        name=line[4:].split(b'\t',1)[0].rstrip(b'\r').decode('utf-8')
        if name=='/dev/null':continue
        parts=Path(name).parts[level:]
        if not parts or '..' in parts or Path(*parts).is_absolute():raise ValueError('Unsafe patch target')
        targets.append(Path(*parts))
    if not targets:raise ValueError('No authentic patch target headers')
    return sorted(set(targets))


def snapshot_patch_targets(source, targets, destination, after=False):
    destination.mkdir(parents=True,exist_ok=False)
    records=[]
    for relative in targets:
        for suffix in (['','.orig','.rej'] if after else ['']):
            name=Path(str(relative)+suffix);path=source/name
            if not path.is_file():
                if not suffix:records.append({'path':name.as_posix(),'exists':False})
                continue
            data=path.read_bytes();retained=destination/name;retained.parent.mkdir(parents=True,exist_ok=True);retained.write_bytes(data)
            records.append({'path':name.as_posix(),'exists':True,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'crBytes':data.count(b'\r'),'lfBytes':data.count(b'\n'),'crlfPairs':data.count(b'\r\n'),'retainedPath':str(retained)})
    return records


def apply_patch(source, patch, tool, out):
    suffix=patch.name.rsplit('.',1)[-1]
    level=int(suffix) if suffix.isdigit() else (0 if patch.name in ['missinginclude.patch','werror-undef.patch'] else 1)
    # Authentic LO recipe explicitly requires --binary for Git-bash mixed-EOL patches.
    # Always select byte-preserving I/O; the full effective source-tree pins remain mandatory.
    argv=[str(tool),'-f','-s','-p'+str(level),'--fuzz=0','--binary','-i',str(patch.resolve())]
    evidence=Path(str(out)+'.files');targets=patch_targets(patch,level)
    receipt={'argv':argv,'cwd':str(source),'exitCode':None,'patch':identity(patch),'transport':'binary','before':snapshot_patch_targets(source,targets,evidence/'before')}
    stdout=stderr=b''
    try:
        result=subprocess.run(argv,cwd=source,capture_output=True,timeout=90)
        stdout=result.stdout;stderr=result.stderr;receipt['exitCode']=result.returncode
        if result.returncode:raise ValueError('Authentic patch failed: '+patch.name)
    except BaseException as error:
        receipt['error']=str(error)
        if isinstance(error,subprocess.TimeoutExpired):stdout=error.stdout or b'';stderr=error.stderr or b''
        raise
    finally:
        receipt['after']=snapshot_patch_targets(source,targets,evidence/'after',after=True)
        Path(str(out)+'.stdout.log').write_bytes(stdout);Path(str(out)+'.stderr.log').write_bytes(stderr)
        write_json(str(out)+'.json',receipt)


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
    text='\n'.join((out/(case+'-build.'+s+'.log')).read_bytes().decode('utf-8',errors='replace') for s in ['stdout','stderr'])
    try:
        inventory=json.loads((out/(case+'-tool-inventory.json')).read_text(encoding='utf-8-sig'))
        inventory['productSourceRoot']=r['workingDirectory']
        proof=admit_build(text,r['exitCode'],case,inventory)
    except ValueError as error:
        write_json(out/(case+'-admission.json'),{'status':'non-reproduction' if case=='baseline' else 'failed','causalCorrectionProven':False,'error':str(error)})
        raise
    obj=work/case/'PCbuild/obj/313arm64_Release/pythoncore'
    inputs=[p.name.lower() for p in obj.iterdir() if p.suffix.lower() in ['.obj','.res']]
    check_inputs(inputs,expected_inputs(data))
    proof['linkInputEvidence']=link_input_evidence(text,r['workingDirectory'],expected_inputs(data))
    proof['completeInputCount']=len(inputs);write_json(out/(case+'-admission.json'),proof)


if __name__=='__main__':
    cmd,*args=sys.argv[1:]
    paths=list(map(Path,args))
    if cmd=='prepare':prepare(*paths)
    elif cmd=='collect':collect(paths[0],paths[1],args[2])
    elif cmd=='admit':admit(paths[0],paths[1],paths[2],args[3])
    else:raise SystemExit('Unknown operation')
