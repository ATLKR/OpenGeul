param([string]$Output='', [string]$WorkRoot='', [string]$Deadline='')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build-native-engine.ps1')

function Write-FirebirdHeaderHelper([string]$Path) {
    @'
"""Extract only authenticated header/patch members; never extract a tree."""
import hashlib,json,pathlib,re,sys,tarfile
fb,lo,manifest,root,out=map(pathlib.Path,sys.argv[1:])
pin=json.loads(manifest.read_bytes()); hp=pin['msvcPlatformHeader']; target='src/include/gen/autoconfig_msvc.h'
if hp['path']!=target or len(pin['upstreamWindowsPatches'])!=25: raise ValueError('Unexpected header/source contract')
if root.exists() or any((p/'.git').exists() for p in (root,*root.parents)): raise ValueError('Header source must be fresh outside Git')
def digest(data): return hashlib.sha256(data).hexdigest()
member_counts={}
def selected(path,wanted):
    result={};count=0
    with tarfile.open(path,'r|*') as archive:
        for member in archive:
            count+=1
            if count>1000000: raise ValueError('Source archive member count exceeds bound')
            if member.name not in wanted: continue
            if member.name in result or not member.isfile() or not 0<member.size<=1048576:
                raise ValueError('Ambiguous/nonregular selected archive member')
            data=archive.extractfile(member).read(1048577)
            if len(data)!=member.size or digest(data)!=wanted[member.name]: raise ValueError('Selected member hash/size differs')
            result[member.name]=data
    if set(result)!=set(wanted): raise ValueError('Required exact archive members missing')
    member_counts[path.name]=count
    return result
name='Firebird-'+pin['firebird']['version']+'/'+target
header=selected(fb,{name:hp['archiveSha256']})[name]
if len(header)!=hp['archiveBytes']: raise ValueError('Original header byte count differs')
wanted={};prefix='libreoffice-'+pin['libreoffice']['version']+'/external/firebird/'
for p in pin['upstreamWindowsPatches']:
    if pathlib.PurePosixPath(p['filename']).name!=p['filename']: raise ValueError('Unsafe patch filename')
    wanted[prefix+p['filename']]=p['sha256']
if len(wanted)!=25: raise ValueError('Duplicate upstream patch pin')
data=selected(lo,wanted); touches=[];records=[]
for p in pin['upstreamWindowsPatches']:
    raw=data[prefix+p['filename']];paths=[]
    for match in re.finditer(r'(?m)^\+\+\+ ([^\t\r\n]+)',raw.decode('utf-8')):
        parts=match[1].split('/');path='/'.join(parts[p['strip']:]);paths.append(path)
    if target in paths: touches.append(p['filename'])
    records.append({'filename':p['filename'],'sha256':digest(raw),'size':len(raw),'strip':p['strip'],'headerIncluded':target in paths})
if touches!=hp['upstreamHeaderPatches']: raise ValueError('Upstream header-changing patch set differs')
out.mkdir(parents=True,exist_ok=True); patches=out/'upstream-patches';patches.mkdir()
for p in pin['upstreamWindowsPatches']: (patches/p['filename']).write_bytes(data[prefix+p['filename']])
path=root/target;path.parent.mkdir(parents=True);path.write_bytes(header)
(out/'header-from-archive.h').write_bytes(header)
(out/'header-extraction.json').write_text(json.dumps({'schemaVersion':1,'headerPath':target,'archiveHeaderBytes':len(header),'archiveHeaderSha256':digest(header),'upstreamPatches':records,'headerPatches':touches,'archiveMemberCounts':member_counts,'sourceArchiveMemberLimit':1000000,'onlySelectedRegularMembersExtracted':True},indent=2)+'\n')
'@ | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Save-FirebirdHeaderSnapshot([string]$Header,[string]$Output,[string]$Name,[long]$Size,[string]$Sha256) {
    try { $identity=Confirm-FileIdentity $Header $Size SHA256 $Sha256 }
    catch { throw ('Header snapshot mismatch: '+$Name+'; '+$_.Exception.Message) }
    $path=Join-Path $Output $Name
    if(Test-Path -LiteralPath $path){throw 'Preserve original header snapshots.'}
    Copy-Item -LiteralPath $Header -Destination $path -ErrorAction Stop
    return $identity
}

function Invoke-FirebirdHeaderPreparation([string]$Python,[string]$Git,[string]$Repo,[string]$FirebirdArchive,
    [string]$LibreOfficeArchive,[string]$SourceRoot,[string]$Output,[string]$ManifestPath='') {
    if(-not $ManifestPath){$ManifestPath=Join-Path $Repo 'suite/engine-build/source-build.json'}
    foreach($path in @($ManifestPath,$FirebirdArchive,$LibreOfficeArchive,$SourceRoot,$Output)){Assert-UnlinkedPath $path}
    $manifest=Get-Content -LiteralPath $ManifestPath -Raw|ConvertFrom-Json
    $pin=$manifest.msvcPlatformHeader
    if($pin.path -cne 'src/include/gen/autoconfig_msvc.h'){throw 'Pinned MSVC platform header is required.'}
    $helper=Join-Path $Output 'extract-header.py';Write-FirebirdHeaderHelper $helper
    Invoke-LoggedCommand $Python @($helper,$FirebirdArchive,$LibreOfficeArchive,$ManifestPath,$SourceRoot,$Output) $Output (Join-Path $Output 'extract-selected-members')|Out-Null
    $plan=Get-Content (Join-Path $Output 'header-extraction.json') -Raw|ConvertFrom-Json
    $header=Join-Path $SourceRoot $pin.path
    foreach($item in $plan.upstreamPatches) {
        if(-not $item.headerIncluded){continue}
        $patch=Join-Path (Join-Path $Output 'upstream-patches') $item.filename
        Invoke-LoggedCommand $Git @('apply',('-p'+$item.strip),'--include=src/include/gen/autoconfig_msvc.h',$patch) $SourceRoot (Join-Path $Output ('apply-upstream-'+$item.filename))|Out-Null
    }
    Save-FirebirdHeaderSnapshot $header $Output 'header-before-port.h' $pin.beforeBytes $pin.beforeSha256|Out-Null
    $port=Join-Path (Join-Path $Repo 'suite/engine-build') $manifest.portPatch.filename
    Assert-UnlinkedPath $port
    Confirm-FileIdentity $port 0 SHA256 $manifest.portPatch.sha256|Out-Null
    Copy-Item -LiteralPath $port -Destination (Join-Path $Output 'applied-port.patch')
    Invoke-LoggedCommand $Git @('apply',('-p'+$manifest.portPatch.strip),'--include=src/include/gen/autoconfig_msvc.h',$port) $SourceRoot (Join-Path $Output 'apply-port-header')|Out-Null
    Save-FirebirdHeaderSnapshot $header $Output 'header-after-port.h' $pin.afterBytes $pin.afterSha256|Out-Null
    return $plan
}

function Write-FirebirdHeaderCompileSource([string]$Path) {
    @'
#if !defined(_M_ARM64) || defined(_M_ARM64EC)
#error This diagnostic requires the actual native MSVC ARM64 ABI.
#endif
#include <stddef.h>
#include "src/include/gen/autoconfig_msvc.h"
#ifndef ARM64
#error The actual Firebird header did not select ARM64.
#endif
#ifdef AMD64
#error The ARM64 header selected AMD64.
#endif
static_assert(sizeof(void*) == 8 && SIZEOF_VOID_P == 8, "native pointer width");
static_assert(sizeof(size_t) == 8 && SIZEOF_SIZE_T == 8, "native size_t width");
static_assert(sizeof(long) == 4 && SIZEOF_LONG == 4, "native Windows LLP64 long");
static_assert(alignof(void*) == 8 && FB_ALIGNMENT == 8, "Firebird ARM64 alignment");
static_assert(sizeof(double) == 8 && alignof(double) == 8 && FB_DOUBLE_ALIGN == 8, "Firebird double alignment");
int opengeul_firebird_header_probe() { return SIZEOF_VOID_P + SIZEOF_SIZE_T + SIZEOF_LONG + FB_ALIGNMENT + FB_DOUBLE_ALIGN; }
'@ | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Get-FirebirdHeaderObjectIdentity([string]$Path) {
    Assert-UnlinkedPath $Path;$data=[IO.File]::ReadAllBytes($Path)
    if($data.Length -lt 60){throw 'Truncated ARM64 COFF object.'}
    $machine=[BitConverter]::ToUInt16($data,0);$sections=[BitConverter]::ToUInt16($data,2)
    if($machine -ne 0xaa64 -or $sections -lt 1 -or $sections -gt 96 -or
       [BitConverter]::ToUInt16($data,16) -ne 0 -or 20+$sections*40 -gt $data.Length){throw 'Object is not a regular native ARM64 COFF object.'}
    for($i=0;$i -lt $sections;$i++) {
        $entry=20+$i*40;$length=[BitConverter]::ToUInt32($data,$entry+16);$start=[BitConverter]::ToUInt32($data,$entry+20)
        if([long]$start+$length -gt $data.Length){throw 'COFF section bytes exceed the actual object.'}
    }
    return [ordered]@{path=[IO.Path]::GetFullPath($Path);machine=[int]$machine;kind='native-arm64-coff-object';sections=[int]$sections;size=$data.Length;sha256=(Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function Invoke-NativeFirebirdHeaderProbe([string]$Output,[string]$WorkRoot,[string]$Deadline='') {
    foreach($path in @($Output,$WorkRoot)){if(-not $path){throw 'Explicit fresh output/work paths are required.'};Assert-UnlinkedPath $path;if(Test-Path -LiteralPath $path){throw 'Preserve prior diagnostic paths.'}}
    $out=[IO.Path]::GetFullPath($Output);$work=[IO.Path]::GetFullPath($WorkRoot)
    foreach($path in @($out,$work)) {
        $parent=$path
        while($parent){if(Test-Path -LiteralPath (Join-Path $parent '.git')){throw 'Diagnostic output/work must be outside every Git checkout.'};$parent=[IO.Path]::GetDirectoryName($parent)}
    }
    New-Item -ItemType Directory $out,$work|Out-Null
    $previousBudget=$script:NativeEngineBuildBudget
    $receipt=[ordered]@{schemaVersion=1;kind='native-arm64-firebird-msvc-header-diagnostic';passed=$false;engineQualified=$false;productQualified=$false;baseQualified=$false;scope='compile only actual pinned header; no link or runtime qualification';stage='native-host';startedUtc=[DateTime]::UtcNow.ToString('o')}
    try {
        $script:NativeEngineBuildBudget=New-NativeBuildBudget -DeadlineUtc $Deadline -MaximumMinutes 20
        $receipt.buildBudget=$script:NativeEngineBuildBudget.record
        $receipt.host=Get-NativeBuildHost
        $repo=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
        $manifestPath=Join-Path $repo 'suite/engine-build/source-build.json'
        $binding=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-firebird-header.ps1') $manifestPath $out
        foreach($key in $binding.Keys){$receipt[$key]=$binding[$key]}
        $receipt.buildDriverSha256=(Get-FileHash (Join-Path $PSScriptRoot 'build-native-engine.ps1') -Algorithm SHA256).Hash.ToLowerInvariant()
        Copy-Item $manifestPath (Join-Path $out 'input-source-build.json')
        if($env:OPENGEUL_FB_HEADER_BUDGET_RECEIPT){Copy-Item -LiteralPath $env:OPENGEUL_FB_HEADER_BUDGET_RECEIPT -Destination (Join-Path $out 'job-budget.json')}
        $manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
        $receipt.stage='authenticated-source-archives'
        $fb=Join-Path $work 'firebird.tar.bz2';$lo=Join-Path $work 'libreoffice.tar.xz'
        $receipt.firebirdArchive=Get-AuthenticatedDownload $manifest.firebird.url $fb $manifest.firebird.size SHA256 $manifest.firebird.sha256 (Join-Path $out 'firebird-download.json')
        $pin=Get-SourcePin (Join-Path $repo 'suite/config/runtime.arm64.lock.json')
        $receipt.libreOfficeArchive=Get-AuthenticatedDownload $pin.url $lo $pin.size SHA256 $pin.sha256 (Join-Path $out 'libreoffice-download.json')
        $python=(Get-Command python -ErrorAction Stop).Source;$git=(Get-Command git -ErrorAction Stop).Source
        $receipt.python=Get-ProductPeIdentity $python
        if($receipt.python.role -cne 'nativeArm64'){throw 'Header extraction requires the native ARM64 Python interpreter.'}
        $receipt.stage='exact-header-patch-replay'
        $source=Join-Path $work 'header-source'
        $receipt.headerPreparation=Invoke-FirebirdHeaderPreparation $python $git $repo $fb $lo $source $out
        $receipt.stage='native-msvc-compile'
        $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
        $found=Invoke-LoggedCommand $vswhere @('-latest','-products','*','-version','[18.0,19.0)','-format','json') $work (Join-Path $out 'vswhere')
        $instances=@(Get-Content -LiteralPath $found.stdout -Raw|ConvertFrom-Json)
        if($instances.Count -ne 1){throw 'One actual VS18 installation is required.'}
        $vs=$instances[0].installationPath
        $version=(Get-Content (Join-Path $vs 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
        if($version -cnotmatch '^14\.\d+\.\d+(?:\.\d+)?$'){throw 'Invalid selected MSVC version.'}
        $compiler=Join-Path $vs ('VC/Tools/MSVC/'+$version+'/bin/Hostarm64/arm64/cl.exe')
        $receipt.compiler=Get-ProductPeIdentity $compiler
        if($receipt.compiler.role -cne 'nativeArm64'){throw 'Actual compiler must use native Hostarm64/arm64.'}
        $receipt.compilerVersion=$version
        $cpp=Join-Path $out 'header-probe.cpp';Write-FirebirdHeaderCompileSource $cpp
        $obj=Join-Path $out 'header-probe.obj';$batch=Join-Path $out 'compile.cmd';$dev=Join-Path $vs 'Common7/Tools/VsDevCmd.bat'
        foreach($path in @($compiler,$dev,$cpp,$obj,$source,$batch)){Assert-UnlinkedPath $path;if($path -match '[^\x20-\x7e]|["%&|<>!^]'){throw 'Unexpected batch argument path.'}}
        @('@echo off',('call "'+$dev+'" -no_logo -arch=arm64 -host_arch=arm64'),'if errorlevel 1 exit /b %errorlevel%',
          'set CL=','set _CL_=',('"'+$compiler+'" /nologo /c /TP /std:c++17 /Zl /Fo"'+$obj+'" /I"'+$source+'" "'+$cpp+'"'),'exit /b %errorlevel%')|Set-Content -LiteralPath $batch -Encoding ascii
        $cmd=Join-Path ([Environment]::SystemDirectory) 'cmd.exe';$receipt.commandController=Get-ProductPeIdentity $cmd
        if($receipt.commandController.role -cne 'nativeArm64'){throw 'Compiler command controller must be native ARM64.'}
        Invoke-LoggedCommand $cmd @('/d','/c',$batch) $work (Join-Path $out 'compile-header') -TimeoutMinutes 2|Out-Null
        $receipt.object=Get-FirebirdHeaderObjectIdentity $obj
        $headerPin=$manifest.msvcPlatformHeader
        $receipt.finalHeader=Confirm-FileIdentity (Join-Path $source $headerPin.path) $headerPin.afterBytes SHA256 $headerPin.afterSha256
        $receipt.compileSource=[ordered]@{path=$cpp;size=(Get-Item $cpp).Length;sha256=(Get-FileHash $cpp -Algorithm SHA256).Hash.ToLowerInvariant()}
        Assert-NativeBuildTimeRemaining
        $receipt.passed=$true;$receipt.stage='complete'
    } catch {$receipt.passed=$false;$receipt.error=$_.Exception.ToString();throw}
    finally {
        $receipt.finishedUtc=[DateTime]::UtcNow.ToString('o')
        if($receipt.buildBudget){$receipt.buildBudget.elapsedSeconds=$script:NativeEngineBuildBudget.clock.Elapsed.TotalSeconds}
        $script:NativeEngineBuildBudget=$previousBudget
        Write-BuildJson (Join-Path $out 'diagnostic.json') $receipt
    }
}

if($MyInvocation.InvocationName -ne '.') {Invoke-NativeFirebirdHeaderProbe $Output $WorkRoot $Deadline}
