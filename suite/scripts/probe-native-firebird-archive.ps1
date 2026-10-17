param([string]$Output='', [string]$WorkRoot='', [string]$Deadline='')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build-native-engine.ps1')

function Write-ArchiveProbeHelper([string]$Path) {
@'
import hashlib,json,pathlib,re,struct,sys,tarfile
P=pathlib.Path
TARGETS=('builds/posix/make.defaults','builds/posix/Makefile.in')
POST25={
    TARGETS[0]:(12445,'7fb6f45c055210e3110084f736cef00bbdfe6c3b07426aad7ae5d3bac026b0bc'),
    TARGETS[1]:(24301,'d6262fca2a4fa052a8f3627fa54a03ce87774d222a1003c3d2ea996fa72b0a36'),
}
def digest(data):return hashlib.sha256(data).hexdigest()
def selected(path,wanted):
    found={};count=0
    with tarfile.open(path,'r|*') as archive:
        for item in archive:
            count+=1
            if count>1000000:raise ValueError('Source archive member count exceeds bound')
            if item.name not in wanted:continue
            if item.name in found or not item.isfile() or not 0<item.size<=1048576:raise ValueError('Ambiguous/nonregular selected archive member')
            data=archive.extractfile(item).read(1048577)
            if len(data)!=item.size or (wanted[item.name] and digest(data)!=wanted[item.name]):raise ValueError('Selected member hash/size differs')
            found[item.name]=data
    if set(found)!=set(wanted):raise ValueError('Selected source members missing')
    return found,count
def paths(raw,strip):
    return ['/'.join(m[1].split('/')[strip:]) for m in re.finditer(r'(?m)^\+\+\+ ([^ \t\r\n]+)',raw.decode())]
def extract(manifest,fb,lo,source,out):
    pin=json.loads(P(manifest).read_bytes());source,out=P(source),P(out)
    if source.exists() or any((p/'.git').exists() for p in (source,*source.parents)):raise ValueError('Recipe source must be fresh outside Git')
    prefix='Firebird-'+pin['firebird']['version']+'/'
    original,fbcount=selected(fb,{prefix+x:None for x in TARGETS})
    wanted={};loprefix='libreoffice-'+pin['libreoffice']['version']+'/external/firebird/'
    for patch in pin['upstreamWindowsPatches']:
        if P(patch['filename']).name!=patch['filename']:raise ValueError('Unsafe patch filename')
        wanted[loprefix+patch['filename']]=patch['sha256']
    if len(wanted)!=25:raise ValueError('Expected 25 unique upstream patch pins')
    patches,locount=selected(lo,wanted);records=[]
    (out/'upstream-patches').mkdir();(out/'recipe-patches').mkdir();(out/'git-replay-patches').mkdir()
    for target in TARGETS:
        raw=original[prefix+target];path=source/target;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        (out/('original-'+path.name)).write_bytes(raw)
    for patch in pin['upstreamWindowsPatches']:
        raw=patches[loprefix+patch['filename']];(out/'upstream-patches'/patch['filename']).write_bytes(raw)
        # Keep complete input bytes and exact selected diff sections. One
        # upstream patch has malformed context in an unrelated source file;
        # parsing that section is unnecessary for these two authenticated files.
        starts=list(re.finditer(rb'(?m)^--- ([^ \t\r\n]+)[^\r\n]*\r?\n\+\+\+ ([^ \t\r\n]+)[^\r\n]*\r?\n',raw));parts=[]
        for i,start in enumerate(starts):
            target='/'.join(start[2].decode().split('/')[patch['strip']:])
            if target not in TARGETS:continue
            end=starts[i+1].start() if i+1<len(starts) else len(raw)
            section=raw[start.start():end]
            # A diff command for the next file is metadata, not a hunk.
            section=re.split(rb'(?m)^diff ',section,maxsplit=1)[0]
            parts.append(section)
        filtered=b''.join(parts)
        if bool(filtered)!=any(x in TARGETS for x in paths(raw,patch['strip'])):raise ValueError('Selected patch section mismatch')
        replay=filtered;normalization=None
        if patch['filename']=='firebird-307.patch.1':
            # GNU patch accepts this pinned legacy context line without its
            # leading space. Retain the unchanged section separately and make
            # the single missing marker explicit for Git's stricter parser.
            legacy=b'\n\tawk -f $(ODS_AWK) <$(ODS_H) >$(ODS_TEST_CPP)\n'
            if digest(raw)!='8c1ec40878a776b92401fe050f237f4132b92209a3be5e2a9a03cec92e7d0187' or filtered.count(legacy)!=1:
                raise ValueError('Pinned legacy context line differs')
            replay=filtered.replace(legacy,b'\n '+legacy[1:],1)
            normalization=dict(kind='missing-unified-context-marker',insertedByteHex='20',contextLine='\tawk -f $(ODS_AWK) <$(ODS_H) >$(ODS_TEST_CPP)',hunkCountsChanged=False)
        if filtered:
            (out/'recipe-patches'/patch['filename']).write_bytes(filtered)
            (out/'git-replay-patches'/patch['filename']).write_bytes(replay)
        records.append(dict(filename=patch['filename'],sha256=digest(raw),size=len(raw),strip=patch['strip'],recipeIncluded=bool(filtered),selectedDiffSha256=digest(filtered),selectedDiffBytes=len(filtered),gitReplaySha256=digest(replay),gitReplayBytes=len(replay),normalization=normalization))
    result=dict(schemaVersion=1,targets=TARGETS,upstreamPatches=records,archiveMemberCounts=dict(firebird=fbcount,libreoffice=locount),selectedRegularMembersOnly=True)
    (out/'recipe-extraction.json').write_text(json.dumps(result,indent=2)+'\n')
def recipe(source,destination,out):
    source,out=P(source),P(out);defaults=(source/TARGETS[0]).read_text();make=(source/TARGETS[1]).read_text()
    ars=re.findall(r'(?m)^AR=\s*(ar @AR_OPTIONS@)[ \t]*$',defaults)
    links=re.findall(r'(?m)^STATICLIB_LINK = (\$\(AR\) crus)[ \t]*$',defaults)
    blocks=re.findall(r'(?m)^\$\(COMMON_LIB\):\s*\$\(Common_Objects\)\r?\n\t-\$\(RM\) \$@\r?\n\t(\$\(STATICLIB_LINK\) \$@ \$\^)\r?$',make)
    if len(ars)!=1 or len(links)!=1 or len(blocks)!=1:raise ValueError('Expected exact original archive recipe')
    result=json.loads((out/'recipe-extraction.json').read_bytes())
    result.update(archiveTool='ar',archiveToolDefinition=ars[0],arOptions='',arOptionsScope='controlled Windows ARM64 recipe comparison; no full configure replay',staticLibraryLink=links[0],archiveCommand=blocks[0],generatedObjects=['archive-probe.obj'],syntheticPayload=True)
    effective={target:(source/target).read_bytes() for target in TARGETS}
    for target,raw in effective.items():
        if (len(raw),digest(raw))!=POST25[target]:raise ValueError('Full post25 selected file differs: '+target)
    result['fullPost25FilesVerified']=True
    result['effectiveFiles']=[]
    for target,raw in effective.items():
        (out/('effective-'+P(target).name)).write_bytes(raw)
        result['effectiveFiles'].append(dict(path=target,size=len(raw),sha256=digest(raw)))
    P(destination).write_text(json.dumps(result,indent=2)+'\n')
def inspect(path):
    path=P(path);result=dict(path=str(path),exists=path.is_file(),structurallyComplete=False,members=[],linkerMembers=[])
    try:
        if path.stat().st_size>16777216:raise ValueError('Diagnostic archive exceeds 16 MiB bound')
        data=path.read_bytes();result.update(size=len(data),sha256=digest(data),magicHex=data[:8].hex())
        if data[:8]!=b'!<arch>\n':raise ValueError('Not a COFF/ar archive')
        offset=8
        while offset<len(data):
            if len(result['members'])>=1024:raise ValueError('Archive member count exceeds bound')
            if offset+60>len(data) or data[offset+58:offset+60]!=b'`\n':raise ValueError('Truncated archive member header')
            header=data[offset:offset+60];name=header[:16].decode('ascii').strip();size=int(header[48:58].decode('ascii').strip())
            start=offset+60
            if size<0 or start+size>len(data):raise ValueError('Truncated archive member data')
            raw=data[start:start+size];row=dict(name=name,offset=offset,size=size,sha256=digest(raw),prefixHex=raw[:64].hex())
            if name in ('/','/SYM64/'):result['linkerMembers'].append(dict(name=name,offset=offset,size=size,sha256=digest(raw)))
            elif name!='//' and len(raw)>=20:
                row['machine']=struct.unpack_from('<H',raw,6 if raw[:4]==b'\x00\x00\xff\xff' else 0)[0]
            result['members'].append(row);offset=start+size+(size%2)
        if offset!=len(data):raise ValueError('Archive padding exceeds actual bytes')
        result['structurallyComplete']=True
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)
    return result
if __name__=='__main__':
    if sys.argv[1]=='extract':extract(*sys.argv[2:])
    elif sys.argv[1]=='recipe':recipe(*sys.argv[2:])
    elif sys.argv[1]=='inspect':print(json.dumps(inspect(sys.argv[2]),indent=2))
    else:raise ValueError('Unknown diagnostic operation')
'@ | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Invoke-ArchiveRecipePreparation([string]$Python,[string]$Git,[string]$Repo,[string]$FirebirdArchive,[string]$LibreOfficeArchive,[string]$SourceRoot,[string]$Output) {
    foreach($path in @($Repo,$FirebirdArchive,$LibreOfficeArchive,$SourceRoot,$Output)){Assert-UnlinkedPath $path}
    $manifestPath=Join-Path $Repo 'suite/engine-build/source-build.json';$manifest=Get-Content $manifestPath -Raw|ConvertFrom-Json
    $helper=Join-Path $Output 'archive-helper.py';Write-ArchiveProbeHelper $helper
    Invoke-LoggedCommand $Python @($helper,'extract',$manifestPath,$FirebirdArchive,$LibreOfficeArchive,$SourceRoot,$Output) $Output (Join-Path $Output 'extract-recipe') -TimeoutMinutes 3|Out-Null
    $plan=Get-Content (Join-Path $Output 'recipe-extraction.json') -Raw|ConvertFrom-Json
    foreach($patch in $plan.upstreamPatches) {
        if(-not $patch.recipeIncluded){continue}
        Invoke-LoggedCommand $Git @('apply',('-p'+$patch.strip),'--include=builds/posix/make.defaults','--include=builds/posix/Makefile.in',(Join-Path (Join-Path $Output 'git-replay-patches') $patch.filename)) $SourceRoot (Join-Path $Output ('apply-'+$patch.filename)) -TimeoutMinutes 1|Out-Null
    }
    $port=Join-Path (Join-Path $Repo 'suite/engine-build') $manifest.portPatch.filename
    Confirm-FileIdentity $port 0 SHA256 $manifest.portPatch.sha256|Out-Null
    # The frozen ARM64 port must not change the archive recipe under test.
    if((Get-Content $port -Raw) -cmatch '(?m)^\+\+\+ builds/posix/(?:make\.defaults|Makefile\.in)(?:\s|$)'){throw 'Port changes the original recipe; review this diagnostic first.'}
    Copy-Item $port (Join-Path $Output 'input-port.patch')
    Invoke-LoggedCommand $Python @($helper,'recipe',$SourceRoot,(Join-Path $Output 'archive-recipe.json'),$Output) $Output (Join-Path $Output 'verify-recipe') -TimeoutMinutes 1|Out-Null
    return Get-Content (Join-Path $Output 'archive-recipe.json') -Raw|ConvertFrom-Json
}

function Write-ArchiveComparisonMakefile([string]$Path,[string]$Recipe,[string]$Object='archive-probe.obj') {
    $pin=Get-Content $Recipe -Raw|ConvertFrom-Json
    if($pin.archiveToolDefinition -cne 'ar @AR_OPTIONS@' -or $pin.arOptions -cne '' -or $pin.staticLibraryLink -cne '$(AR) crus' -or $pin.archiveCommand -cne '$(STATICLIB_LINK) $@ $^' -or $Object -cnotmatch '^(?:\.\./)?archive-probe\.obj$'){throw 'Unexpected original archive recipe.'}
    Write-BashScript $Path @(('AR='+$pin.archiveToolDefinition.Replace('@AR_OPTIONS@','')),('STATICLIB_LINK = '+$pin.staticLibraryLink),'RM=rm -f',('common.lib: '+$Object),"`t-`$(RM) `$@",("`t"+$pin.archiveCommand))
}

function Write-ArchiveNativeMakefile([string]$Path,[string]$Librarian,[string]$Object) {
    foreach($value in @($Librarian,$Object)){if(-not $value -or $value -match '[^\x20-\x7e]|["%&|<>!^$#`\\]'){throw 'Unsafe native make argument.'}}
    if($Object -match '\s'){throw 'The exact upstream object list requires whitespace-free owned object paths.'}
    Write-BashScript $Path @('RM=rm -f',('common.lib: '+$Object),"`t-`$(RM) `$@",("`t"+'"'+$Librarian+'" /NOLOGO "/OUT:$@" $^'))
}

function Write-ArchiveNativeBatch([string]$Path,[string]$DeveloperBatch,[string]$Tool,[string[]]$Arguments) {
    foreach($value in @($Path,$DeveloperBatch,$Tool)+$Arguments){if(-not $value -or $value -match '[^\x20-\x7e]|["%&|<>!^]'){throw 'Unexpected batch argument path.'}}
    $quoted=@($Arguments|ForEach-Object {'"'+$_+'"'})
    @('@echo off','set LIB=','set LIBPATH=','set INCLUDE=',('call "'+$DeveloperBatch+'" -no_logo -arch=arm64 -host_arch=arm64'),'if errorlevel 1 exit /b %errorlevel%',
      'set CL=','set _CL_=','set LINK=','set _LINK_=',('"'+$Tool+'" '+($quoted -join ' ')),'exit /b %errorlevel%')|Set-Content -LiteralPath $Path -Encoding ascii
}

function Invoke-ArchiveObservedCommand([string]$File,[string[]]$Arguments,[string]$Work,[string]$Prefix) {
    try{Invoke-LoggedCommand $File $Arguments $Work $Prefix -TimeoutMinutes 2|Out-Null}catch{$failure=$_.Exception.ToString()}
    $path=$Prefix+'.command.json';if(-not(Test-Path $path)){throw 'Original command receipt missing.'}
    $record=Get-Content $path -Raw|ConvertFrom-Json
    if(-not $record.directProcessDeathVerified -or -not $record.pipeDrainComplete -or $record.forcedTermination -or @($record.cleanupErrors).Count){throw 'Diagnostic command did not finish cleanly within its original bound.'}
    return [ordered]@{passed=$record.passed;exitCode=$record.exitCode;commandReceipt=$path;error=$failure}
}

function Confirm-ArchiveNativeRun([string]$Prefix) {
    $command=Get-Content ($Prefix+'.command.json') -Raw|ConvertFrom-Json
    if(-not $command.passed -or $command.exitCode -ne 0 -or -not $command.directProcessDeathVerified -or -not $command.pipeDrainComplete -or $command.forcedTermination -or @($command.cleanupErrors).Count){throw 'Native archive control command was not successful.'}
    $raw=Get-Content ($Prefix+'.stdout.log') -Raw|ConvertFrom-Json
    if($raw.kind -cne 'native-arm64-archive-link-probe' -or $raw.pid -ne $command.pid -or $raw.processMachine -ne 0 -or $raw.nativeMachine -ne 0xaa64 -or $raw.value -ne 42){throw 'Actual native archive control runtime/PID/OS/value differs.'}
    return $raw
}

function Confirm-ArchiveNativeControl([string]$Output) {
    foreach($name in @('library','link')) {
        $c=Get-Content (Join-Path $Output ($name+'.command.json')) -Raw|ConvertFrom-Json
        if(-not $c.passed -or $c.exitCode -ne 0 -or -not $c.directProcessDeathVerified -or -not $c.pipeDrainComplete -or $c.forcedTermination -or @($c.cleanupErrors).Count){throw 'Native archive control command was not successful.'}
    }
    return Confirm-ArchiveNativeRun (Join-Path $Output 'run')
}

function Write-ArchiveProbeSources([string]$Output) {
    @'
#if !defined(_MSC_VER) || !defined(_M_ARM64) || defined(_M_ARM64EC)
#error Actual native MSVC ARM64 object required.
#endif
static_assert(sizeof(void*)==8 && sizeof(long)==4,"native Windows ARM64 LLP64 ABI");
extern "C" __declspec(noinline) int opengeul_arm64_archive_value() { return 42; }
'@|Set-Content (Join-Path $Output 'archive-probe.cpp') -Encoding utf8NoBOM
    @'
#if !defined(_MSC_VER) || !defined(_M_ARM64) || defined(_M_ARM64EC)
#error Actual native MSVC ARM64 caller required.
#endif
#include <windows.h>
#include <stdio.h>
extern "C" int opengeul_arm64_archive_value();
int main() {
    USHORT process=0xffff,native=0xffff;
    if(!IsWow64Process2(GetCurrentProcess(),&process,&native)) return 91;
    int value=opengeul_arm64_archive_value();
    printf("{\"kind\":\"native-arm64-archive-link-probe\",\"pid\":%lu,\"processMachine\":%u,\"nativeMachine\":%u,\"value\":%d}\n",GetCurrentProcessId(),(unsigned)process,(unsigned)native,value);
    return process==0 && native==0xaa64 && value==42 ? 0 : 92;
}
'@|Set-Content (Join-Path $Output 'archive-main.cpp') -Encoding utf8NoBOM
}

function Get-ArchiveObjectIdentity([string]$Path) {
    Assert-UnlinkedPath $Path;$data=[IO.File]::ReadAllBytes($Path)
    if($data.Length -lt 60 -or [BitConverter]::ToUInt16($data,0) -ne 0xaa64 -or [BitConverter]::ToUInt16($data,16) -ne 0){throw 'Expected regular native ARM64 COFF object.'}
    $sections=[BitConverter]::ToUInt16($data,2)
    if($sections -lt 1 -or $sections -gt 96 -or 20+40*$sections -gt $data.Length){throw 'Invalid native COFF sections.'}
    for($i=0;$i -lt $sections;$i++){$s=20+40*$i;if([long][BitConverter]::ToUInt32($data,$s+20)+[BitConverter]::ToUInt32($data,$s+16) -gt $data.Length){throw 'Native COFF section exceeds file.'}}
    return [ordered]@{path=$Path;machine=0xaa64;size=$data.Length;sha256=(Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function Get-ArchiveSetupPin {
    $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'build-native-engine.ps1'),[ref]$tokens,[ref]$errors)
    $assign=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq '$setupHash'},$true))
    if($errors.Count -or $assign.Count -ne 1 -or $assign[0].Right.Extent.Text -cnotmatch "^'([0-9a-f]{128})'$"){throw 'Expected one actual production Cygwin setup SHA512 pin.'}
    return $Matches[1]
}

function Get-ArchiveCygwinPe([string]$Path) {
    Assert-UnlinkedPath $Path;$data=[IO.File]::ReadAllBytes($Path)
    if($data.Length -lt 64 -or [BitConverter]::ToUInt16($data,0) -ne 0x5a4d){throw 'Build helper is not a PE.'}
    $offset=[BitConverter]::ToUInt32($data,60)
    if($offset -lt 64 -or $offset+26 -gt $data.Length -or [BitConverter]::ToUInt32($data,[int]$offset) -ne 0x4550 -or [BitConverter]::ToUInt16($data,[int]$offset+4) -ne 0x8664 -or [BitConverter]::ToUInt16($data,[int]$offset+24) -ne 0x20b){throw 'Expected actual x64 Cygwin build helper PE.'}
    return [ordered]@{path=$Path;machine=0x8664;size=$data.Length;sha256=(Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant();role='cygwinBuildHelperOnly';productPayload=$false}
}

function Invoke-NativeFirebirdArchiveProbe([string]$Output,[string]$WorkRoot,[string]$Deadline='') {
    foreach($path in @($Output,$WorkRoot)) {
        if(-not $path){throw 'Explicit fresh output/work paths required.'}
        $ancestor=[IO.Path]::GetFullPath($path)
        while($ancestor){if(Test-Path (Join-Path $ancestor '.git')){throw 'Diagnostic output/work must be outside Git.'};$ancestor=[IO.Path]::GetDirectoryName($ancestor)}
    }
    $paths=New-BuildDirectories $WorkRoot $Output;$work=$paths.work;$out=$paths.output;$previous=$script:NativeEngineBuildBudget
    $receipt=[ordered]@{schemaVersion=1;kind='native-arm64-firebird-archive-link-diagnostic';passed=$false;engineQualified=$false;baseQualified=$false;productQualified=$false;syntheticPayload=$true;scope='one native object archive/link/runtime comparison; not a Firebird engine build';startedUtc=[DateTime]::UtcNow.ToString('o');stage='native-host';cases=@()}
    try {
        $script:NativeEngineBuildBudget=New-NativeBuildBudget -DeadlineUtc $Deadline -MaximumMinutes 20;$receipt.buildBudget=$script:NativeEngineBuildBudget.record
        $receipt.host=Get-NativeBuildHost;$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'));$manifestPath=Join-Path $repo 'suite/engine-build/source-build.json'
        $binding=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-firebird-archive.ps1') $manifestPath $out
        foreach($key in $binding.Keys){$receipt[$key]=$binding[$key]}
        $receipt.productionDriverSha256=(Get-FileHash (Join-Path $PSScriptRoot 'build-native-engine.ps1') -Algorithm SHA256).Hash.ToLowerInvariant()
        Copy-Item $manifestPath (Join-Path $out 'input-source-build.json');Copy-Item (Join-Path $repo 'suite/config/runtime.arm64.lock.json') (Join-Path $out 'input-runtime.lock.json')
        if($env:OPENGEUL_FB_ARCHIVE_BUDGET_RECEIPT){Copy-Item $env:OPENGEUL_FB_ARCHIVE_BUDGET_RECEIPT (Join-Path $out 'job-budget.json')}
        $python=(Get-Command python -ErrorAction Stop).Source;$receipt.python=Get-ProductPeIdentity $python
        $receipt.controller=Get-ProductPeIdentity (Get-Process -Id $PID).Path
        if($receipt.python.role -cne 'nativeArm64' -or $receipt.controller.role -cne 'nativeArm64'){throw 'Native ARM64 controllers required.'}
        $manifest=Get-Content $manifestPath -Raw|ConvertFrom-Json;$pin=Get-SourcePin (Join-Path $repo 'suite/config/runtime.arm64.lock.json')
        $receipt.stage='authenticated-recipe-inputs';$fb=Join-Path $work 'firebird.tar.bz2';$lo=Join-Path $work 'libreoffice.tar.xz'
        $receipt.firebirdArchive=Get-AuthenticatedDownload $manifest.firebird.url $fb $manifest.firebird.size SHA256 $manifest.firebird.sha256 (Join-Path $out 'firebird-download.json')
        $receipt.libreOfficeArchive=Get-AuthenticatedDownload $pin.url $lo $pin.size SHA256 $pin.sha256 (Join-Path $out 'libreoffice-download.json')
        $receipt.recipe=Invoke-ArchiveRecipePreparation $python (Get-Command git -ErrorAction Stop).Source $repo $fb $lo (Join-Path $work 'recipe-source') $out
        $receipt.stage='actual-production-cygwin-tools';$setup=Join-Path $work 'setup-x86_64.exe'
        $receipt.setup=Get-AuthenticatedDownload 'https://cygwin.com/setup-x86_64.exe' $setup 0 SHA512 (Get-ArchiveSetupPin) (Join-Path $out 'cygwin-download.json')
        $receipt.setupPe=Get-ArchiveCygwinPe $setup;$cygwin=Join-Path $work 'cygwin';$receipt.packages=Get-CygwinBuildPackages
        Invoke-LoggedCommand $setup @('--quiet-mode','--no-admin','--no-shortcuts','--no-startmenu','--no-desktop','--root',$cygwin,'--local-package-dir',(Join-Path $work 'cygwin-cache'),'--site','https://mirrors.kernel.org/sourceware/cygwin/','--packages',$receipt.packages) $work (Join-Path $out 'cygwin-setup') -TimeoutMinutes 12|Out-Null
        $bash=Join-Path $cygwin 'bin/bash.exe';$cygpath=Join-Path $cygwin 'bin/cygpath.exe';$envExe=Join-Path $cygwin 'bin/env.exe'
        $receipt.cygwinTools=@(foreach($name in @('bash.exe','env.exe','cygpath.exe','ar.exe','nm.exe','make.exe','cygwin1.dll')){Get-ArchiveCygwinPe (Join-Path $cygwin ('bin/'+$name))})
        $receipt.stage='native-msvc-object';$found=Invoke-LoggedCommand (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe') @('-latest','-products','*','-version','[18.0,19.0)','-format','json') $work (Join-Path $out 'vswhere') -TimeoutMinutes 1
        $instances=@(Get-Content $found.stdout -Raw|ConvertFrom-Json);if($instances.Count -ne 1){throw 'One selected VS18 installation required.'}
        $vs=$instances[0].installationPath;$version=(Get-Content (Join-Path $vs 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
        if($version -cnotmatch '^14\.\d+\.\d+(?:\.\d+)?$'){throw 'Invalid selected MSVC toolset version.'}
        $toolRoot=Join-Path $vs ('VC/Tools/MSVC/'+$version+'/bin/Hostarm64/arm64');$dev=Join-Path $vs 'Common7/Tools/VsDevCmd.bat';$receipt.nativeTools=@()
        foreach($name in @('cl.exe','lib.exe','link.exe','dumpbin.exe')){$pe=Get-ProductPeIdentity (Join-Path $toolRoot $name);if($pe.role -cne 'nativeArm64'){throw 'Actual native Hostarm64/arm64 tool required.'};$receipt.nativeTools+=,$pe}
        $receipt.compilerVersion=$version;$cmd=Join-Path ([Environment]::SystemDirectory) 'cmd.exe';$receipt.commandController=Get-ProductPeIdentity $cmd
        if($receipt.commandController.role -cne 'nativeArm64'){throw 'Native command controller required.'}
        Write-ArchiveProbeSources $out
        foreach($part in @('probe','main')) {
            $source=Join-Path $out ('archive-'+$part+'.cpp');$obj=Join-Path $out ('archive-'+$part+'.obj');$batch=Join-Path $out ('compile-'+$part+'.cmd')
            $flags=@('/nologo','/c','/TP','/std:c++17',('/Fo'+$obj),$source);if($part -ceq 'probe'){$flags+= '/Zl'}else{$flags+='/MT'}
            Write-ArchiveNativeBatch $batch $dev (Join-Path $toolRoot 'cl.exe') $flags
            Invoke-LoggedCommand $cmd @('/d','/c',$batch) $work (Join-Path $out ('compile-'+$part)) -TimeoutMinutes 2|Out-Null
            $receipt[($part+'Object')]=Get-ArchiveObjectIdentity $obj
        }
        $receipt.stage='selected-cygwin-ar-identity';$versions=Join-Path $out 'cygwin-versions.sh'
        Write-BashScript $versions @('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH','printf ''resolvedAr=''; command -v ar','printf ''resolvedArWindows=''; /usr/bin/cygpath -w "$(command -v ar)"','/usr/bin/ar --version','/usr/bin/nm --version','/usr/bin/make --version','/usr/bin/cygcheck -c binutils cygwin make')
        Invoke-CygwinScript $bash $cygpath $versions $work (Join-Path $out 'cygwin-versions') -NativeLinks|Out-Null
        $resolved=@(Get-Content (Join-Path $out 'cygwin-versions.stdout.log')|Where-Object {$_ -clike 'resolvedArWindows=*'})
        if($resolved.Count -ne 1 -or [IO.Path]::GetFullPath($resolved[0].Substring(18)) -ine [IO.Path]::GetFullPath((Join-Path $cygwin 'bin/ar.exe'))){throw 'Shell-selected ar differs from recorded selected Cygwin ar.exe.'}
        $receipt.makeTargetLinkPolicy=[ordered]@{environment='CYGWIN=winsymlinks:nativestrict';scope='owned comparison children only';fallback=$false}
        foreach($mode in @('direct','original','native')) {
            $receipt.stage='compare-'+$mode;$case=Join-Path $out $mode;New-Item -ItemType Directory $case|Out-Null
            $row=[ordered]@{mode=$mode;archive=$null;library=$null;link=$null;run=$null};$receipt.cases+=,$row
            $library=Join-Path $case 'common.lib'
            if($mode -in @('original','native')) {
                $makefile=Join-Path $case 'comparison.mk'
                if($mode -ceq 'original'){Write-ArchiveComparisonMakefile $makefile (Join-Path $out 'archive-recipe.json') '../archive-probe.obj'}
                else{Write-ArchiveNativeMakefile $makefile ((Join-Path $toolRoot 'lib.exe').Replace('\','/')) ((Join-Path $out 'archive-probe.obj').Replace('\','/'))}
                $script=Join-Path $case 'archive.sh';$converted=Invoke-LoggedCommand $cygpath @('-u',$case) $work (Join-Path $case 'path') -TimeoutMinutes 1
                $unix=(Get-Content $converted.stdout -Raw).Trim();Write-BashScript $script @('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH',('cd '+(Quote-Bash $unix)),'/usr/bin/make --trace --no-print-directory -f comparison.mk common.lib')
                $converted=Invoke-LoggedCommand $cygpath @('-u',$script) $work (Join-Path $case 'script-path') -TimeoutMinutes 1
                $row.library=Invoke-ArchiveObservedCommand $envExe @('CYGWIN=winsymlinks:nativestrict',$bash,'--noprofile','--norc',(Get-Content $converted.stdout -Raw).Trim()) $work (Join-Path $case 'library')
            }
            if($mode -cne 'direct') {
                $observed=Invoke-LoggedCommand $python @((Join-Path $out 'archive-helper.py'),'inspect',$library) $work (Join-Path $case 'inspect-archive') -TimeoutMinutes 1
                Copy-Item $observed.stdout (Join-Path $case 'archive-members.json');$row.archive=Get-Content $observed.stdout -Raw|ConvertFrom-Json
                if(Test-Path $library) {
                    foreach($option in @('HEADERS','LINKERMEMBER:1','LINKERMEMBER:2')) {
                        $label=$option.Replace(':','-').ToLowerInvariant();$batch=Join-Path $case ($label+'.cmd')
                        Write-ArchiveNativeBatch $batch $dev (Join-Path $toolRoot 'dumpbin.exe') @('/NOLOGO',('/'+$option),$library)
                        Invoke-ArchiveObservedCommand $cmd @('/d','/c',$batch) $work (Join-Path $case $label)|Out-Null
                    }
                }
            }
            # Both archivers and the direct control must retain the same object.
            $row.payloadObject=Confirm-FileIdentity $receipt.probeObject.path $receipt.probeObject.size SHA256 $receipt.probeObject.sha256
            $payload=if($mode -ceq 'direct'){Join-Path $out 'archive-probe.obj'}else{$library}
            $exe=Join-Path $case 'archive-control.exe';$batch=Join-Path $case 'link.cmd'
            Write-ArchiveNativeBatch $batch $dev (Join-Path $toolRoot 'link.exe') @('/NOLOGO','/MACHINE:ARM64','/SUBSYSTEM:CONSOLE',('/OUT:'+$exe),(Join-Path $out 'archive-main.obj'),$payload,'kernel32.lib')
            $row.link=Invoke-ArchiveObservedCommand $cmd @('/d','/c',$batch) $work (Join-Path $case 'link')
            if($row.link.passed) {
                $row.pe=Get-ProductPeIdentity $exe;if($row.pe.role -cne 'nativeArm64'){throw 'Linked diagnostic PE is not native ARM64.'}
                $row.run=Invoke-ArchiveObservedCommand $exe @() $case (Join-Path $case 'run')
                if($row.run.passed){$row.runtime=Confirm-ArchiveNativeRun (Join-Path $case 'run')}
            }
            if($mode -ceq 'direct' -and (-not $row.link.passed -or -not $row.run.passed)){throw 'Direct-object native link/run control failed.'}
            if($mode -ceq 'native') {
                $row.importArchive=Get-Arm64ImportLibrary $library
                if(-not $row.archive.structurallyComplete -or @($row.archive.linkerMembers).Count -lt 1 -or @($row.archive.members|Where-Object {$_.sha256 -ceq $receipt.probeObject.sha256}).Count -ne 1){throw 'Native library does not retain the exact compiled ARM64 object and linker index.'}
                $row.runtime=Confirm-ArchiveNativeControl $case
            }
            $row.payloadObjectAfter=Confirm-FileIdentity $receipt.probeObject.path $receipt.probeObject.size SHA256 $receipt.probeObject.sha256
        }
        Assert-NativeBuildTimeRemaining;$receipt.passed=$true;$receipt.stage='complete'
    } catch {$receipt.error=$_.Exception.ToString();throw}
    finally {
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o');if($receipt.buildBudget){$receipt.buildBudget.elapsedSeconds=$script:NativeEngineBuildBudget.clock.Elapsed.TotalSeconds}
        Write-BuildJson (Join-Path $out 'diagnostic.json') $receipt;$script:NativeEngineBuildBudget=$previous
    }
}

if($MyInvocation.InvocationName -ne '.') {Invoke-NativeFirebirdArchiveProbe $Output $WorkRoot $Deadline}
