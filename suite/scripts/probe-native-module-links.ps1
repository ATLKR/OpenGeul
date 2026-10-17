param([string]$Output='.work/native-module-link-probe',[Alias('WorkDirectory')][string]$ProbeWorkDirectory='.work/native-module-link-work')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build-native-engine.ps1')

function Get-ModuleLinkSetupPin {
    $driver=Join-Path $PSScriptRoot 'build-native-engine.ps1';$tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($driver,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'Production driver parse failed.'}
    $hash=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq '$setupHash'},$true))
    $download=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Get-AuthenticatedDownload' -and $n.CommandElements[1].Extent.Text -ceq "'https://cygwin.com/setup-x86_64.exe'"},$true))
    if($hash.Count -ne 1 -or $download.Count -ne 1){throw 'Expected one production Cygwin setup pin.'}
    if($hash[0].Right.Extent.Text -cnotmatch "^'([0-9a-f]{128})'$"){throw 'Production setup SHA512 literal is invalid.'}
    $sha=$Matches[1]
    return [ordered]@{url=$download[0].CommandElements[1].Value;sha512=$sha}
}

function Write-ModuleLinkMakeRecipe([string]$Path,[string]$Source) {
    $driver=Join-Path $PSScriptRoot 'build-native-engine.ps1';$tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($driver,[ref]$tokens,[ref]$errors)
    $writes=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst] -and
        $n.GetCommandName() -eq 'Write-BashScript' -and $n.CommandElements[1].Extent.Text -eq '$script' -and
        $n.Extent.Text.Contains('make -j$Jobs $target')},$true))
    if($errors.Count -or $writes.Count -ne 1){throw 'Expected one production make-target recipe.'}
    $script=$Path;$unixSource=$Source;$Jobs=1;$target='ExternalProject_firebird'
    Invoke-Expression $writes[0].Extent.Text
}

function Write-ModuleLinkFixturePython([string]$Path) {
@'
import ctypes, hashlib, importlib.util, io, json, os, pathlib, shutil, sys, tarfile
P=pathlib.Path
def sha(data): return hashlib.sha256(data).hexdigest()
def create(repo,work,evidence,pins):
    repo,work,evidence=map(P,(repo,work,evidence))
    plan=json.loads(P(pins).read_text(encoding='utf-8-sig'))
    fixtures=repo/'suite/tests/fixtures/native-source-tar'
    provenance=json.loads((fixtures/'source.json').read_text())
    lock=json.loads((repo/'suite/engine-build/source-build.json').read_text())
    helper=(fixtures/'unpack-sources').read_bytes();fragment=(fixtures/'get-submodules.mk').read_bytes()
    if sha(helper)!=lock['moduleBootstrap']['sha256'] or sha(helper)!=provenance['unpackFixture']['sha256']:
        raise ValueError('Pristine helper SHA256 differs from authenticated source')
    if sha(fragment)!=provenance['fragment']['sha256'] or plan['source']!=provenance['sourceArchive']:
        raise ValueError('Source fragment/pin SHA256 binding differs')
    version=plan['source']['version'];roles={'translations':'translations','dictionaries':'dictionaries','help':'helpcontent2'}
    expected={f'libreoffice-{role}-{version}.tar.xz':module for role,module in roles.items()}
    if {x['filename'] for x in plan['extras']}!=set(expected) or len(plan['extras'])!=3:
        raise ValueError('Exact production extra-source filenames required')
    spec=importlib.util.spec_from_file_location('bootstrap',repo/'suite/engine-build/enable_firebird_arm64.py')
    bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
    result=dict(schemaVersion=1,syntheticInputs=True,productQualified=False,cases=[])
    for mode in ('current','nativestrict'):
        core=work/mode/'core';cache=work/mode/'archives';out=evidence/mode
        (core/'bin').mkdir(parents=True);cache.mkdir();out.mkdir()
        target=core/'bin/unpack-sources';target.write_bytes(helper);target.chmod(0o755)
        fix=bootstrap.install_module_bootstrap(core,out)
        (core/'Repository.mk').write_text('# controlled synthetic core\n')
        (core/'sources.ver').write_text('lo_sources_ver='+version+'\n')
        row=dict(mode=mode,core=str(core),evidence=str(out),bootstrap=fix,modules=[],archives=[])
        for pin in plan['extras']:
            filename=pin['filename'];module=expected[filename];basename=filename[:-len('.tar.xz')]
            payload=('OpenGeul native module-link diagnostic '+module+' 한국어\n').encode()
            archive=cache/filename
            with tarfile.open(archive,'w:xz') as output:
                for name,raw in ((module+'/native-probe.txt',payload),(module+'/Module_'+module+'.mk',b'# synthetic module\n'),('git-hooks/pre-commit',b'excluded\n')):
                    info=tarfile.TarInfo(basename+'/'+name);info.size=len(raw);output.addfile(info,io.BytesIO(raw))
            retained=out/filename;shutil.copyfile(archive,retained)
            row['archives'].append(dict(path=str(archive),evidencePath=str(retained),size=archive.stat().st_size,sha256=sha(archive.read_bytes()),productionFilename=filename,synthetic=True))
            row['modules'].append(dict(name=module,sha256=sha(payload),linkPath=str(core/module/'native-probe.txt'),directPath=str(core/'src'/basename/module/'native-probe.txt')))
        # Native C:/ spelling on Windows, as exported by production configure.
        source=core.as_posix();downloads=cache.as_posix()
        if any(c.isspace() for c in source+downloads):raise ValueError('Exact upstream helper requires whitespace-free fixture paths')
        make=('SRCDIR := '+source+'\nTARFILE_LOCATION := '+downloads+'\nGIT_NEEDED_SUBMODULES := translations dictionaries helpcontent2\n'
              '.PHONY: ExternalProject_firebird get-submodules download\nExternalProject_firebird: get-submodules\n\t@printf "synthetic-module-bootstrap-complete\\n"\ndownload:\n\t@true\n'
              'fetch_Download_item_unchecked = $(if $(wildcard $(TARFILE_LOCATION)/$(2)),,$(error Missing owned synthetic archive))\n')
        (core/'Makefile').write_bytes(make.encode()+fragment);result['cases'].append(row)
    return result
def read_record(path,expected):
    result=dict(path=str(path),readable=False,matches=False)
    try:
        data=P(path).read_bytes();result.update(readable=True,size=len(data),sha256=sha(data),matches=sha(data)==expected)
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)
    return result
def native_identity():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.IsWow64Process2.argtypes=(ctypes.c_void_p,ctypes.POINTER(ctypes.c_ushort),ctypes.POINTER(ctypes.c_ushort))
    process,native=ctypes.c_ushort(),ctypes.c_ushort()
    if not kernel.IsWow64Process2(kernel.GetCurrentProcess(),ctypes.byref(process),ctypes.byref(native)):raise ctypes.WinError(ctypes.get_last_error())
    result=dict(pid=os.getpid(),executable=sys.executable,processMachine=process.value,nativeMachine=native.value,pythonVersion=sys.version)
    if process.value!=0 or native.value!=0xaa64:raise RuntimeError('Python reader must be native Windows ARM64')
    return result
def observe(plan,mode):
    case=next(x for x in json.loads(P(plan).read_text(encoding='utf-8-sig'))['cases'] if x['mode']==mode)
    return dict(schemaVersion=1,mode=mode,native=native_identity(),modules=[dict(name=x['name'],direct=read_record(x['directPath'],x['sha256']),link=read_record(x['linkPath'],x['sha256'])) for x in case['modules']])
if __name__=='__main__':
    if sys.argv[1]=='create':print(json.dumps(create(*sys.argv[2:]),ensure_ascii=False))
    elif sys.argv[1]=='observe':
        value=observe(*sys.argv[2:4]);P(sys.argv[4]).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps(value,ensure_ascii=False))
    else:raise ValueError('Unknown diagnostic phase')
'@|Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Get-ModuleLinkToolPe([string]$Path) {
    Assert-UnlinkedPath $Path;$data=[IO.File]::ReadAllBytes($Path)
    if($data.Length -lt 64 -or [BitConverter]::ToUInt16($data,0) -ne 23117){throw 'Invalid diagnostic build-tool PE.'}
    $offset=[BitConverter]::ToUInt32($data,60)
    if($offset -lt 64 -or $offset+26 -gt $data.Length -or [BitConverter]::ToUInt32($data,[int]$offset) -ne 17744){throw 'Invalid build-tool PE offset.'}
    $machine=[BitConverter]::ToUInt16($data,[int]$offset+4)
    if($machine -notin @(0x8664,0xaa64) -or [BitConverter]::ToUInt16($data,[int]$offset+24) -ne 0x20b){throw 'Unexpected diagnostic build-tool machine.'}
    return [ordered]@{path=$Path;machine=$machine;size=$data.Length;sha256=(Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant();buildToolOnly=$true;productPayload=$false}
}

function Invoke-ModuleLinkBash($Bash,$Cygpath,$EnvExe,[string]$Mode,[string]$Script,[string]$Work,[string]$Prefix) {
    if($Mode -ceq 'current'){return Invoke-CygwinScript $Bash $Cygpath $Script $Work $Prefix}
    if($Mode -cne 'nativestrict'){throw 'Unexpected diagnostic mode.'}
    $path=Invoke-LoggedCommand $Cygpath @('-u',$Script) $Work ($Prefix+'-path')
    $unix=(Get-Content -LiteralPath $path.stdout -Raw).Trim()
    # env.exe affects only its owned child; controller CYGWIN stays unchanged.
    return Invoke-LoggedCommand $EnvExe @('CYGWIN=winsymlinks:nativestrict',$Bash,'--noprofile','--norc',$unix) $Work $Prefix
}

function Read-ModuleLinkBytes([string]$Path,[string]$Expected) {
    $result=[ordered]@{path=$Path;readable=$false;matches=$false}
    try {
        $data=[IO.File]::ReadAllBytes($Path)
        $hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($data)).ToLowerInvariant()
        $result.readable=$true;$result.size=$data.Length;$result.sha256=$hash;$result.matches=($hash -ceq $Expected)
    }catch{$result.error=$_.Exception.Message}
    return $result
}

function Invoke-NativeModuleLinkProbe([string]$Output,[string]$WorkDirectory) {
    $paths=New-BuildDirectories $WorkDirectory $Output;$work=$paths.work;$out=$paths.output
    $receipt=[ordered]@{schemaVersion=1;kind='native-module-link-diagnostic';diagnosticComplete=$false;productQualified=$false;engineQualified=$false;
        syntheticInputs=$true;scope='controlled module resource reads only; no Office build';stage='native-host';startedUtc=[DateTime]::UtcNow.ToString('o');cases=@()}
    $oldBudget=$script:NativeEngineBuildBudget
    try {
        $script:NativeEngineBuildBudget=New-NativeBuildBudget -MaximumMinutes 20;$receipt.budget=$script:NativeEngineBuildBudget.record
        $receipt.host=Get-NativeBuildHost;$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
        $receipt.source=Get-SourceRunBinding $repo (Join-Path $PSScriptRoot 'probe-native-module-links.ps1') (Join-Path $repo 'suite/engine-build/source-build.json') $out
        $receipt.productionDriverSha256=(Get-FileHash (Join-Path $PSScriptRoot 'build-native-engine.ps1') -Algorithm SHA256).Hash.ToLowerInvariant()
        $python=(Get-Command python -ErrorAction Stop).Source;$controller=(Get-Process -Id $PID).Path
        $receipt.pythonPe=Get-ProductPeIdentity $python;$receipt.controllerPe=Get-ProductPeIdentity $controller
        if($receipt.pythonPe.role -cne 'nativeArm64' -or $receipt.controllerPe.role -cne 'nativeArm64'){throw 'Both native readers must be ARM64.'}
        $receipt.inheritedCygwin=$env:CYGWIN
        $receipt.stage='pinned-production-cygwin-setup';$pin=Get-ModuleLinkSetupPin
        $setup=Join-Path $work 'setup-x86_64.exe'
        $receipt.setup=Get-AuthenticatedDownload $pin.url $setup 0 SHA512 $pin.sha512 (Join-Path $out 'cygwin-download.json')
        $receipt.setupPe=Get-ModuleLinkToolPe $setup
        $cygwin=Join-Path $work 'cygwin';$packages=Get-CygwinBuildPackages;$receipt.packages=$packages
        Invoke-LoggedCommand $setup @('--quiet-mode','--no-admin','--no-shortcuts','--no-startmenu','--no-desktop','--root',$cygwin,'--local-package-dir',(Join-Path $work 'cygwin-cache'),'--site','https://mirrors.kernel.org/sourceware/cygwin/','--packages',$packages) $work (Join-Path $out 'cygwin-setup')|Out-Null
        $bash=Join-Path $cygwin 'bin/bash.exe';$cygpath=Join-Path $cygwin 'bin/cygpath.exe';$envExe=Join-Path $cygwin 'bin/env.exe'
        $receipt.buildTools=@(foreach($name in @('bash.exe','cygpath.exe','env.exe','make.exe','tar.exe','ln.exe','stat.exe','readlink.exe','cygwin1.dll')){Get-ModuleLinkToolPe (Join-Path $cygwin ('bin/'+$name))})
        $commands=Join-Path $work 'commands';New-Item -ItemType Directory $commands|Out-Null
        $receipt.identity=Get-CygwinIdentity $bash $cygpath $commands $work $out
        $versions=Join-Path $commands 'versions.sh'
        Write-BashScript $versions @('set -euo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH','/usr/bin/cygcheck -c cygwin coreutils make tar python3','/usr/bin/bash --version','/usr/bin/make --version','/usr/bin/tar --version')
        Invoke-CygwinScript $bash $cygpath $versions $work (Join-Path $out 'cygwin-versions')|Out-Null
        $receipt.stage='controlled-authenticated-helper-fixtures'
        $generator=Join-Path $out 'module-link-fixture.py';Write-ModuleLinkFixturePython $generator
        $pins=Join-Path $out 'production-source-pins.json';Write-BuildJson $pins ([ordered]@{source=(Get-SourcePin (Join-Path $repo 'suite/config/runtime.arm64.lock.json'));extras=@(Get-ExtraSourcePins)})
        $created=Invoke-LoggedCommand $python @($generator,'create',$repo,$work,$out,$pins) $work (Join-Path $out 'create-fixtures')
        $planPath=Join-Path $out 'fixture-plan.json';Copy-Item -LiteralPath $created.stdout -Destination $planPath
        $plan=Get-Content -LiteralPath $planPath -Raw|ConvertFrom-Json
        foreach($case in $plan.cases) {
            $receipt.stage='observe-'+$case.mode;$row=[ordered]@{mode=$case.mode;requestedCygwin=$(if($case.mode -ceq 'nativestrict'){'winsymlinks:nativestrict'}else{$env:CYGWIN});bootstrap=$case.bootstrap;archives=$case.archives}
            $receipt.cases+=,$row
            $converted=Invoke-LoggedCommand $cygpath @('-u',$case.core) $work (Join-Path $case.evidence 'source-path')
            $unixCore=(Get-Content -LiteralPath $converted.stdout -Raw).Trim();$recipe=Join-Path $case.evidence 'make-target.sh'
            $permissions=Join-Path $case.evidence 'fixture-permissions.sh'
            Write-BashScript $permissions @('set -euo pipefail',"/usr/bin/chmod 755 -- $(Quote-Bash ($unixCore+'/bin/unpack-sources'))")
            Invoke-CygwinScript $bash $cygpath $permissions $work (Join-Path $case.evidence 'fixture-permissions')|Out-Null
            Write-ModuleLinkMakeRecipe $recipe $unixCore
            try{Invoke-ModuleLinkBash $bash $cygpath $envExe $case.mode $recipe $work (Join-Path $case.evidence 'bootstrap')|Out-Null;$row.bootstrapCommandPassed=$true}
            catch{$row.bootstrapCommandPassed=$false;$row.bootstrapError=$_.Exception.Message}
            $stat=Join-Path $case.evidence 'link-metadata.sh'
            $lines=@('set -uo pipefail','export PATH=/usr/local/bin:/usr/bin:/bin:$PATH','printenv CYGWIN; printf ''cygwinEnvExit=%s\n'' "$?"')
            foreach($module in $case.modules){$link=$unixCore+'/'+$module.name;$lines+=@("printf '%s\n' $(Quote-Bash $module.name)","/usr/bin/stat -c '%F|%f|%a|%N' -- $(Quote-Bash $link)",'printf ''statExit=%s\n'' "$?"',"/usr/bin/readlink -v -- $(Quote-Bash $link)",'printf ''readlinkExit=%s\n'' "$?"')}
            Write-BashScript $stat $lines
            Invoke-ModuleLinkBash $bash $cygpath $envExe $case.mode $stat $work (Join-Path $case.evidence 'link-metadata')|Out-Null
            $nativePath=Join-Path $case.evidence 'native-python.json'
            $nativeCommand=Invoke-LoggedCommand $python @($generator,'observe',$planPath,$case.mode,$nativePath) $work (Join-Path $case.evidence 'native-python') -TimeoutMinutes 1
            $row.nativePython=Get-Content -LiteralPath $nativePath -Raw|ConvertFrom-Json
            $nativeReceipt=Get-Content -LiteralPath $nativeCommand.receipt -Raw|ConvertFrom-Json
            $row.nativePythonCommandReceipt=$nativeCommand.receipt
            if($row.nativePython.native.processMachine -ne 0 -or $row.nativePython.native.nativeMachine -ne 0xaa64 -or
               $row.nativePython.native.pid -ne $nativeReceipt.pid -or $row.nativePython.native.executable -ine $python){throw 'Native reader identity differs.'}
            $row.nativePowerShell=@(foreach($module in $case.modules){[ordered]@{name=$module.name;direct=(Read-ModuleLinkBytes $module.directPath $module.sha256);link=(Read-ModuleLinkBytes $module.linkPath $module.sha256)}})
            Write-BuildJson (Join-Path $case.evidence 'native-powershell.json') ([ordered]@{host=$receipt.host;pe=$receipt.controllerPe;modules=$row.nativePowerShell})
            $row.allNativeReadsMatched=(@($row.nativePython.modules|Where-Object {-not $_.direct.matches -or -not $_.link.matches}).Count -eq 0 -and @($row.nativePowerShell|Where-Object {-not $_.direct.matches -or -not $_.link.matches}).Count -eq 0)
        }
        $receipt.diagnosticComplete=$true;$receipt.stage='complete'
    }catch{$receipt.error=$_.Exception.ToString();throw}
    finally{$receipt.finishedUtc=[DateTime]::UtcNow.ToString('o');Write-BuildJson (Join-Path $out 'diagnostic.json') $receipt;$script:NativeEngineBuildBudget=$oldBudget}
}

if($MyInvocation.InvocationName -ne '.') {Invoke-NativeModuleLinkProbe $Output $ProbeWorkDirectory}
