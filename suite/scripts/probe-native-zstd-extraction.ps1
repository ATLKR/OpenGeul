param([string]$Output='',[string]$WorkRoot='',[string]$Deadline='')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build-native-engine.ps1')

function Write-ZstdProbeHelper([string]$Path) {
@'
"""Actual pinned source recipes and complete archive census; no Office build."""
import ctypes,hashlib,importlib.util,json,os,pathlib,re,stat,sys,tarfile
P=pathlib.Path
SHA='eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3'
SIZE=2434947
NAME='zstd-1.5.7.tar.gz'
def sha(data):return hashlib.sha256(data).hexdigest()
def save(path,value):
    with P(path).open('x',encoding='utf-8') as out:json.dump(value,out,ensure_ascii=False,indent=2);out.write('\n')
def archive_manifest(path):
    members=[];seen=set();total=0
    with tarfile.open(path,'r:gz') as archive:
        for i,item in enumerate(archive):
            parts=pathlib.PurePosixPath(item.name).parts
            if not parts or item.name.startswith('/') or '..' in parts or '\\' in item.name or len(item.name)>500:
                raise ValueError('Unsafe archive member')
            relative='/'.join(parts[1:])
            if relative in seen or i>=5000:raise ValueError('Duplicate or excessive archive members')
            seen.add(relative);row=dict(index=i,path=relative)
            if item.isdir():row.update(kind='directory')
            elif item.isfile():
                if not 0<=item.size<=16777216:raise ValueError('Oversized regular member')
                data=archive.extractfile(item).read(16777217);total+=len(data)
                if len(data)!=item.size or total>33554432:raise ValueError('Archive byte bound exceeded')
                row.update(kind='regular',bytes=len(data),sha256=sha(data))
            elif item.issym():
                if pathlib.PurePosixPath(item.linkname).is_absolute() or '..' in pathlib.PurePosixPath(item.linkname).parts or '\\' in item.linkname:
                    raise ValueError('Unsafe archive link target')
                row.update(kind='symlink',target=item.linkname)
            else:raise ValueError('Unsupported archive member type')
            members.append(row)
    return dict(schemaVersion=1,archiveBytes=P(path).stat().st_size,archiveSha256=sha(P(path).read_bytes()),members=members,
                memberCount=len(members),regularCount=sum(r['kind']=='regular' for r in members),regularBytes=total,
                directoryCount=sum(r['kind']=='directory' for r in members),symlinkCount=sum(r['kind']=='symlink' for r in members))
def census(root,manifest):
    root=P(root);actual={};expected={r['path']:r for r in manifest['members']}
    paths=[root,*root.rglob('*')]
    for path in paths:
        relative=path.relative_to(root).as_posix() if path!=root else ''
        info=path.lstat()
        if stat.S_ISLNK(info.st_mode):row=dict(kind='symlink',target=os.readlink(path))
        elif stat.S_ISREG(info.st_mode):row=dict(kind='regular',bytes=info.st_size,sha256=sha(path.read_bytes()))
        elif stat.S_ISDIR(info.st_mode):row=dict(kind='directory')
        else:raise ValueError('Unexpected extracted file type')
        # A synthetic unit manifest can omit its root; production includes it.
        if relative or relative in expected:actual[relative]=row
    if set(actual)!=set(expected):raise ValueError('Extracted member set differs; no omissions or extras accepted')
    for name,row in actual.items():
        if row!={k:v for k,v in expected[name].items() if k not in ('path','index')}:
            raise ValueError('Extracted member content or link target differs: '+name)
    return dict(schemaVersion=1,passed=True,memberCount=len(actual),members=[dict(path=p,**actual[p]) for p in sorted(actual)])
def make_harness(core,case,archive,windows):
    core,case,archive=map(lambda p:P(p).as_posix(),(core,case,archive))
    if any(c.isspace() or c in '#$' for c in core+case+archive):raise ValueError('Controlled gbuild paths must be whitespace-free')
    # Only build-graph paths/trace/output functions are stubbed. Both complete
    # authenticated .mk files and their actual untar macro/rules are included.
    text='''SHELL := /bin/bash
.DEFAULT_GOAL := probe
OS := WNT
CPUNAME := AARCH64
GNUTAR := /usr/bin/tar
STRIP_COMPONENTS := --strip-components
ZSTD_TARBALL := zstd-1.5.7.tar.gz
MSYSTEM :=
MSYS :=
gb_Helper_PHONY := probe-phony
.PHONY: probe-phony
gb_Helper_abbreviate_dirs = $(1)
gb_Helper_cyg_path = CYGPATH
gb_UnpackedTarget_get_target = CASE/stamps/$(1)
gb_UnpackedTarget_get_clean_target = CASE/clean/$(1)
gb_UnpackedTarball_get_target = CASE/patched/$(1)
gb_UnpackedTarball_get_clean_target = CASE/clean-patched/$(1)
gb_UnpackedTarball_get_version_target = CASE/stamps/version-$(1)
gb_UnpackedTarball_get_preparation_target = CASE/stamps/prep-$(1)
gb_UnpackedTarball_get_final_target = CASE/final/$(1)
gb_UnpackedTarball_workdir := CASE/tree
TARFILE_LOCATION := ARCHIVE
gb_UnpackedTarget_TARFILE_LOCATION := ARCHIVE
GBUILDDIR := CORE/solenv/gbuild
gb_Module_CURRENTMAKEFILE := CORE/external/zstd/UnpackedTarball_zstd.mk
include CORE/solenv/gbuild/UnpackedTarball.mk
include CORE/external/zstd/UnpackedTarball_zstd.mk
.PHONY: probe
probe: $(call gb_UnpackedTarget_get_target,$(ZSTD_TARBALL))
'''
    return text.replace('CYGPATH',"$(shell /usr/bin/cygpath -u '$(1)')" if windows else '$(1)').replace('CASE',case).replace('ARCHIVE',archive).replace('CORE',core)
def prepare(repo,lo,zstd,work,evidence):
    repo,lo,zstd,work,evidence=map(P,(repo,lo,zstd,work,evidence))
    lock=json.loads((repo/'suite/engine-build/source-build.json').read_bytes())
    manifest=archive_manifest(zstd)
    if (manifest['archiveBytes'],manifest['archiveSha256'],manifest['memberCount'],manifest['directoryCount'],manifest['regularCount'],manifest['symlinkCount'],manifest['regularBytes'])!=(SIZE,SHA,743,104,637,2,8354806):
        raise ValueError('Exact authenticated zstd archive contract differs')
    links=[(r['index'],r['path'],r['target']) for r in manifest['members'] if r['kind']=='symlink']
    if links!=[(509,'tests/cli-tests/bin/unzstd','zstd'),(511,'tests/cli-tests/bin/zstdcat','zstd')]:raise ValueError('Expected temporal dangling links differ')
    if manifest['members'][510]['path']!='tests/cli-tests/bin/zstd' or manifest['members'][510]['kind']!='regular':raise ValueError('Archive target ordering differs')
    save(evidence/'archive-manifest.json',manifest)
    wanted={'configure.ac','bin/unpack-sources','external/firebird/UnpackedTarball_firebird.mk','external/firebird/ExternalProject_firebird.mk','external/zstd/UnpackedTarball_zstd.mk','solenv/gbuild/UnpackedTarball.mk','download.lst'}
    prefix='libreoffice-'+lock['libreoffice']['version']+'/';selected={};count=0
    with tarfile.open(lo,'r|xz') as archive:
        for member in archive:
            count+=1
            if count>1000000:raise ValueError('LO archive member bound exceeded')
            path=member.name[len(prefix):] if member.name.startswith(prefix) else ''
            if path not in wanted:continue
            if path in selected or not member.isfile() or not 0<member.size<=4194304:raise ValueError('Invalid selected LO member')
            data=archive.extractfile(member).read(4194305)
            if len(data)!=member.size:raise ValueError('Truncated selected LO member')
            selected[path]=data
    if set(selected)!=wanted:raise ValueError('Missing required actual LO source members')
    for name in ('solenv/gbuild/UnpackedTarball.mk','download.lst'):
        with (evidence/('authenticated-'+P(name).name)).open('xb') as out:out.write(selected[name])
    download=selected['download.lst'].decode()
    if not re.search(r'^ZSTD_SHA256SUM\s*:=\s*'+SHA+r'\s*$',download,re.M) or not re.search(r'^ZSTD_TARBALL\s*:=\s*zstd-1\.5\.7\.tar\.gz\s*$',download,re.M):raise ValueError('LO download.lst zstd pin differs')
    source=work/'source';source.mkdir()
    for name,data in selected.items():
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    spec=importlib.util.spec_from_file_location('actual_source_hook',repo/'suite/engine-build/enable_firebird_arm64.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    hooks=module.install(source, evidence)
    zstd_hook=hooks['zstdSourceLinks']
    original=selected['external/zstd/UnpackedTarball_zstd.mk'];effective=(source/'external/zstd/UnpackedTarball_zstd.mk').read_bytes()
    if sha(original)!=zstd_hook['beforeSha256'] or sha(effective)!=zstd_hook['afterSha256']:raise ValueError('Actual installer receipt/recipe differs')
    strict=work/'pristine-source'
    for name in ('solenv/gbuild/UnpackedTarball.mk','external/zstd/UnpackedTarball_zstd.mk'):
        path=strict/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(selected[name])
    archive_dir=work/'archives';archive_dir.mkdir();(archive_dir/NAME).write_bytes(zstd.read_bytes())
    cases=[]
    for name,core in [('strict-original',strict),('corrected-source',source)]:
        case=work/name;case.mkdir();(case/'stamps').mkdir();(case/'patched').mkdir()
        make=case/'Makefile';make.write_text(make_harness(core,case,archive_dir,os.name=='nt'),encoding='utf-8')
        retained=evidence/(name+'.Makefile');retained.write_bytes(make.read_bytes())
        cases.append(dict(name=name,root=str(case),makefile=str(make),makefileEvidence=str(retained),makefileSha256=sha(make.read_bytes()),tree=str(case/'tree/zstd'),stamp=str(case/'stamps'/NAME)))
    plan=dict(schemaVersion=1,sourceHooks=hooks,archiveManifestSha256=sha((evidence/'archive-manifest.json').read_bytes()),loArchiveMemberCount=count,
        sourceMembers=[dict(path=n,bytes=len(d),sha256=sha(d)) for n,d in selected.items()],gbuildHarnessScope='actual whole macros and actual original/effective zstd recipe; trace/path/graph adapters only',cases=cases)
    save(evidence/'extraction-plan.json',plan)
def native(root,alias,out):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.IsWow64Process2.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ushort),ctypes.POINTER(ctypes.c_ushort)];kernel.IsWow64Process2.restype=ctypes.c_int
    process,native=ctypes.c_ushort(),ctypes.c_ushort()
    if not kernel.IsWow64Process2(kernel.GetCurrentProcess(),ctypes.byref(process),ctypes.byref(native)):raise ctypes.WinError(ctypes.get_last_error())
    if process.value!=0 or native.value!=0xaa64:raise ValueError('Native ARM64 Python is required')
    alias=P(alias);info=alias.lstat();data=alias.read_bytes()
    if not alias.is_symlink() or info.st_reparse_tag!=0xa000000c or data!=b'OpenGeul strict native alias\n':raise ValueError('Native strict alias/read differs')
    portable=[]
    for name in ('unzstd','zstdcat'):
        path=P(root)/'tests/cli-tests/bin'/name;info=path.lstat();raw=path.read_bytes()
        if not info.st_file_attributes&4 or info.st_file_attributes&1024 or path.is_symlink():raise ValueError('Expected source-only SYSTEM link representation')
        portable.append(dict(name=name,attributes=info.st_file_attributes,rawBytes=len(raw),rawSha256=sha(raw)))
    save(out,dict(schemaVersion=1,passed=True,pid=os.getpid(),image=sys.executable,processMachine=process.value,nativeMachine=native.value,
        alias=dict(path=str(alias),reparseTag=info_tag(alias),bytes=len(data),sha256=sha(data)),sourceOnlySystemLinks=portable))
def info_tag(path):return path.lstat().st_reparse_tag
if __name__=='__main__':
    phase=sys.argv[1]
    if phase=='prepare':prepare(*sys.argv[2:])
    elif phase=='census':
        if sys.platform!='cygwin':raise ValueError('Actual extraction census must use the selected Cygwin Python')
        data=P(sys.argv[3]).read_bytes();value=census(sys.argv[2],json.loads(data))
        value.update(manifestSha256=sha(data),root=sys.argv[2],pythonImage=sys.executable,pythonVersion=sys.version,platform=sys.platform)
        save(sys.argv[4],value)
    elif phase=='native':native(*sys.argv[2:])
    else:raise ValueError('Unexpected phase')
'@|Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Get-ZstdCygwinSetupPin {
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'build-native-engine.ps1'),[ref]$tokens,[ref]$errors)
    $hash=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq '$setupHash'},$true))
    $download=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Get-AuthenticatedDownload' -and $n.CommandElements[1].Extent.Text -ceq "'https://cygwin.com/setup-x86_64.exe'"},$true))
    if($errors.Count -or $hash.Count -ne 1 -or $download.Count -ne 1 -or $hash[0].Right.Extent.Text -cnotmatch "^'([0-9a-f]{128})'$"){throw 'Expected exact production Cygwin setup pin.'}
    return @{url=$download[0].CommandElements[1].Value;sha512=$Matches[1]}
}

function Get-ZstdCygwinToolIdentity([string]$Path) {
    # Inventory only: these x64 Cygwin build helpers intentionally use cygwin1.
    # This does not call or change the Windows-only pkgconf/product admission.
    Assert-UnlinkedPath $Path;$data=[IO.File]::ReadAllBytes($Path)
    if($data.Length -lt 64 -or $data[0] -ne 77 -or $data[1] -ne 90){throw 'Cygwin inventory input is not a PE.'}
    [long]$offset=[BitConverter]::ToUInt32($data,60)
    if($offset -lt 64 -or $offset+26 -gt $data.Length -or [BitConverter]::ToUInt32($data,[int]$offset) -ne 17744){throw 'Invalid Cygwin tool PE headers.'}
    $machine=[BitConverter]::ToUInt16($data,[int]$offset+4);$sections=[BitConverter]::ToUInt16($data,[int]$offset+6)
    $optionalSize=[BitConverter]::ToUInt16($data,[int]$offset+20);$flags=[BitConverter]::ToUInt16($data,[int]$offset+22)
    [long]$optional=$offset+24;[long]$table=$optional+$optionalSize
    $dll=[IO.Path]::GetExtension($Path) -ieq '.dll'
    if($machine -ne 0x8664 -or $optionalSize -lt 240 -or $table+$sections*40 -gt $data.Length -or
       $sections -lt 1 -or $sections -gt 96 -or [BitConverter]::ToUInt16($data,[int]$optional) -ne 0x20b -or
       -not($flags -band 2) -or [bool]($flags -band 0x2000) -ne $dll){throw 'Expected selected x64 Cygwin PE32+ EXE/DLL inventory.'}
    for($i=0;$i -lt $sections;$i++) {
        [int]$entry=$table+$i*40;[long]$size=[BitConverter]::ToUInt32($data,$entry+16);[long]$raw=[BitConverter]::ToUInt32($data,$entry+20)
        if($raw+$size -gt $data.Length){throw 'Cygwin tool section exceeds actual bytes.'}
    }
    return [ordered]@{path=[IO.Path]::GetFullPath($Path);machine=[int]$machine;kind=$(if($dll){'dll'}else{'exe'});size=$data.Length;
        sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();buildToolOnly=$true;productPayload=$false;
        nativeArm64Qualified=$false;policy='Cygwin x64 host-tool inventory only; Windows ARM64 emulation allowed'}
}

function Assert-ZstdProbeResult($Result) {
    if($Result.strictOriginal.exitCode -ne 2 -or $Result.strictOriginal.forcedTermination -or -not $Result.strictOriginal.pipeDrainComplete -or -not $Result.strictOriginal.directProcessDeathVerified){throw 'Original strict extraction did not fail normally as expected.'}
    if(-not $Result.correctedSource.passed -or $Result.correctedSource.exitCode -ne 0 -or $Result.correctedSource.forcedTermination -or -not $Result.correctedSource.pipeDrainComplete -or -not $Result.correctedSource.directProcessDeathVerified){throw 'Corrected extraction did not complete normally.'}
    if(-not $Result.completeCensus.passed -or $Result.completeCensus.memberCount -ne 743){throw 'Complete archive census is required.'}
    if($Result.completeCensus.platform -cne 'cygwin' -or $Result.completeCensus.manifestSha256 -cne $Result.extractionPlan.archiveManifestSha256){throw 'Cygwin census input/source differs.'}
    if(-not $Result.nativePython.passed -or $Result.nativePython.processMachine -ne 0 -or $Result.nativePython.nativeMachine -ne 0xaa64 -or $Result.nativePython.alias.reparseTag -ne 2684354572){throw 'Native strict alias proof differs.'}
    if(-not $Result.nativePowerShell.matches -or $Result.nativePowerShell.linkType -cne 'SymbolicLink' -or $Result.nativePython.sourceOnlySystemLinks.Count -ne 2){throw 'Native link/read separation is incomplete.'}
}

function Invoke-NativeZstdExtractionProbe([string]$Output,[string]$WorkRoot,[string]$Deadline) {
    foreach($path in @($Output,$WorkRoot)) {
        if(-not $path){throw 'Explicit owned paths are required.'}
        $parent=[IO.Path]::GetFullPath($path)
        while($parent){if(Test-Path -LiteralPath (Join-Path $parent '.git')){throw 'Diagnostic work/evidence must be outside Git.'};$parent=[IO.Path]::GetDirectoryName($parent)}
    }
    $paths=New-BuildDirectories $WorkRoot $Output;$work=$paths.work;$out=$paths.output
    $oldBudget=$script:NativeEngineBuildBudget
    $receipt=[ordered]@{schemaVersion=1;kind='native-arm64-zstd-source-extraction-diagnostic';passed=$false;engineQualified=$false;productQualified=$false;baseQualified=$false;scope='exact source untar and native link-policy separation only';stage='native-host';startedUtc=[DateTime]::UtcNow.ToString('o')}
    try {
        $script:NativeEngineBuildBudget=New-NativeBuildBudget -DeadlineUtc $Deadline -MaximumMinutes 20
        $receipt.budget=$script:NativeEngineBuildBudget.record;$receipt.host=Get-NativeBuildHost
        $repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$manifest=Join-Path $repo 'suite/engine-build/source-build.json'
        $receipt.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-zstd-extraction.ps1') $manifest $out
        $receipt.productionDriverSha256=(Get-FileHash (Join-Path $PSScriptRoot 'build-native-engine.ps1') -Algorithm SHA256).Hash.ToLowerInvariant()
        Copy-Item $manifest (Join-Path $out 'input-source-build.json')
        if($env:OPENGEUL_ZSTD_BUDGET_RECEIPT){Copy-Item $env:OPENGEUL_ZSTD_BUDGET_RECEIPT (Join-Path $out 'job-budget.json')}
        $python=(Get-Command python -ErrorAction Stop).Source;$controller=(Get-Process -Id $PID).Path
        $receipt.python=Get-ProductPeIdentity $python;$receipt.controller=Get-ProductPeIdentity $controller
        if($receipt.python.role -cne 'nativeArm64' -or $receipt.controller.role -cne 'nativeArm64'){throw 'Native ARM64 readers are required.'}
        $receipt.stage='authenticated-source-inputs';$lo=Join-Path $work 'libreoffice.tar.xz';$zstd=Join-Path $work 'zstd-1.5.7.tar.gz'
        $pin=Get-SourcePin (Join-Path $repo 'suite/config/runtime.arm64.lock.json')
        $receipt.libreoffice=Get-AuthenticatedDownload $pin.url $lo $pin.size SHA256 $pin.sha256 (Join-Path $out 'libreoffice-download.json')
        $receipt.zstd=Get-AuthenticatedDownload 'https://dev-www.libreoffice.org/src/zstd-1.5.7.tar.gz' $zstd 2434947 SHA256 'eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3' (Join-Path $out 'zstd-download.json')
        $receipt.stage='actual-source-hook-and-recipes';$helper=Join-Path $out 'zstd-probe.py';Write-ZstdProbeHelper $helper
        Invoke-LoggedCommand $python @($helper,'prepare',$repo,$lo,$zstd,$work,$out) $work (Join-Path $out 'prepare-actual-source')|Out-Null
        $plan=Get-Content (Join-Path $out 'extraction-plan.json') -Raw|ConvertFrom-Json;$receipt.extractionPlan=$plan
        $receipt.stage='production-pinned-cygwin-bootstrap';$setupPin=Get-ZstdCygwinSetupPin;$setup=Join-Path $work 'setup-x86_64.exe'
        $receipt.cygwinSetup=Get-AuthenticatedDownload $setupPin.url $setup 0 SHA512 $setupPin.sha512 (Join-Path $out 'cygwin-download.json')
        $receipt.cygwinSetupPe=Get-WindowsBuildToolPeIdentity $setup
        $cygwin=Join-Path $work 'cygwin';$receipt.packages='make,python3,tar,coreutils,gzip'
        Invoke-LoggedCommand $setup @('--quiet-mode','--no-admin','--no-shortcuts','--no-startmenu','--no-desktop','--root',$cygwin,'--local-package-dir',(Join-Path $work 'cygwin-cache'),'--site','https://mirrors.kernel.org/sourceware/cygwin/','--packages',$receipt.packages) $work (Join-Path $out 'cygwin-setup')|Out-Null
        $bash=Join-Path $cygwin 'bin/bash.exe';$cygpath=Join-Path $cygwin 'bin/cygpath.exe'
        $receipt.tools=@(foreach($name in @('env.exe','bash.exe','cygpath.exe','make.exe','tar.exe','ln.exe','cygwin1.dll')){Get-ZstdCygwinToolIdentity (Join-Path $cygwin ('bin/'+$name))})
        $commands=Join-Path $work 'commands';New-Item -ItemType Directory $commands|Out-Null
        $receipt.cygwinIdentity=Get-CygwinIdentity $bash $cygpath $commands $work $out
        $convert={param($path,$name)$r=Invoke-LoggedCommand $cygpath @('-u',$path) $work (Join-Path $out ($name+'-path'));(Get-Content -LiteralPath $r.stdout -Raw).Trim()}
        $unixHelper=&$convert $helper 'helper';$unixManifest=&$convert (Join-Path $out 'archive-manifest.json') 'archive-manifest'
        $receipt.inheritedCygwin=$env:CYGWIN
        foreach($case in $plan.cases) {
            $receipt.stage=$case.name;$script=Join-Path $commands ($case.name+'.sh')
            $unixCase=&$convert $case.root ($case.name+'-root');$unixTree=&$convert $case.tree ($case.name+'-tree')
            $lines=@('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH','export LC_ALL=C','export TAR_OPTIONS=--force-local','test "$CYGWIN" = winsymlinks:nativestrict','/usr/bin/cygcheck -c cygwin coreutils make tar python3','/usr/bin/make --version','/usr/bin/tar --version',"cd $(Quote-Bash $unixCase)",'printf ''parentBefore=%s\n'' "$CYGWIN"','/usr/bin/make --no-print-directory -j1 -f Makefile probe','printf ''parentAfter=%s\n'' "$CYGWIN"','test "$CYGWIN" = winsymlinks:nativestrict')
            if($case.name -ceq 'corrected-source') {
                $unixCensus=&$convert (Join-Path $out 'complete-census.json') 'census'
                $lines+=@("/usr/bin/python3 $(Quote-Bash $unixHelper) census $(Quote-Bash $unixTree) $(Quote-Bash $unixManifest) $(Quote-Bash $unixCensus)",'mkdir native-control','printf ''OpenGeul strict native alias\n'' > native-control/target.txt','/usr/bin/ln -s target.txt native-control/alias.txt','set +e','/usr/bin/ln -s absent.txt native-control/dangling.txt','code=$?','set -e','printf ''strictDanglingExit=%s\n'' "$code"','test "$code" -ne 0','test ! -L native-control/dangling.txt','test ! -e native-control/dangling.txt')
            }
            Write-BashScript $script $lines;Copy-Item $script (Join-Path $out ($case.name+'.sh'))
            $prefix=Join-Path $out $case.name
            if($case.name -ceq 'strict-original') {
                try {Invoke-CygwinScript $bash $cygpath $script $work $prefix -NativeLinks|Out-Null;throw 'Original strict source unexpectedly extracted.'}
                catch {
                    $raw=Get-Content -LiteralPath ($prefix+'.command.json') -Raw|ConvertFrom-Json
                    $stderr=Get-Content -LiteralPath ($prefix+'.stderr.log') -Raw
                    if($raw.exitCode -ne 2 -or $stderr -cnotmatch 'tests/cli-tests/bin/unzstd: Cannot create symlink' -or $stderr -cnotmatch 'No such file or directory'){throw}
                    if(Test-Path -LiteralPath $case.stamp){throw 'Failed source extraction created its success stamp.'}
                    $receipt.strictOriginal=$raw
                }
            } else {
                Invoke-CygwinScript $bash $cygpath $script $work $prefix -NativeLinks|Out-Null
                $receipt.correctedSource=Get-Content -LiteralPath ($prefix+'.command.json') -Raw|ConvertFrom-Json
                if(-not (Test-Path -LiteralPath $case.stamp -PathType Leaf)){throw 'Corrected source did not produce actual gbuild stamp.'}
                $receipt.completeCensus=Get-Content (Join-Path $out 'complete-census.json') -Raw|ConvertFrom-Json
                $receipt.stage='native-strict-readers';$alias=Join-Path $case.root 'native-control/alias.txt';$native=Join-Path $out 'native-python.json'
                $result=Invoke-LoggedCommand $python @($helper,'native',$case.tree,$alias,$native) $work (Join-Path $out 'native-python')
                $receipt.nativePython=Get-Content $native -Raw|ConvertFrom-Json;$nativeCommand=Get-Content $result.receipt -Raw|ConvertFrom-Json
                if($receipt.nativePython.pid -ne $nativeCommand.pid -or $receipt.nativePython.image -ine $python){throw 'Native Python command identity differs.'}
                $bytes=[IO.File]::ReadAllBytes($alias);$expected=[Text.Encoding]::UTF8.GetBytes("OpenGeul strict native alias`n")
                $receipt.nativePowerShell=[ordered]@{pid=$PID;linkType=(Get-Item -LiteralPath $alias -Force).LinkType;sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant();bytes=$bytes.Length;matches=([Convert]::ToBase64String($bytes) -ceq [Convert]::ToBase64String($expected))}
                Write-BuildJson (Join-Path $out 'native-powershell.json') $receipt.nativePowerShell
            }
        }
        if($env:CYGWIN -cne $receipt.inheritedCygwin){throw 'Controller link environment changed.'}
        Assert-ZstdProbeResult $receipt;Assert-NativeBuildTimeRemaining
        $receipt.passed=$true;$receipt.stage='complete'
    } catch {$receipt.passed=$false;$receipt.error=$_.Exception.ToString();throw}
    finally {
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        if($receipt.budget){$receipt.budget.elapsedSeconds=$script:NativeEngineBuildBudget.clock.Elapsed.TotalSeconds}
        $script:NativeEngineBuildBudget=$oldBudget
        Write-BuildJson (Join-Path $out 'diagnostic.json') $receipt
    }
}
if($MyInvocation.InvocationName -ne '.'){Invoke-NativeZstdExtractionProbe $Output $WorkRoot $Deadline}
