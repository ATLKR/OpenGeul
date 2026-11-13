param([string]$Output='.work/native-crt-probe')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build-native-engine.ps1')

function Get-CrtProbeNames {
    'concrt140.dll','msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','msvcp140_atomic_wait.dll',
    'msvcp140_codecvt_ids.dll','vcruntime140.dll','vcruntime140_threads.dll'
}

function Invoke-CrtProbeCommand([string]$FilePath,[string[]]$Arguments,[string]$WorkingDirectory,
        [string]$Prefix,[ValidateRange(1,120)][int]$TimeoutSeconds=30) {
    $record=[ordered]@{schemaVersion=1;file=$FilePath;arguments=$Arguments;passed=$false;exitCode=$null;
        forcedTermination=$false;pipeDrainComplete=$false;timeoutSeconds=$TimeoutSeconds;startedUtc=[DateTime]::UtcNow.ToString('o')}
    $process=$null;$stdout=$null;$stderr=$null;$clock=[Diagnostics.Stopwatch]::StartNew()
    try {
        $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$FilePath;$info.WorkingDirectory=$WorkingDirectory
        $info.UseShellExecute=$false;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
        foreach($argument in $Arguments) {$info.ArgumentList.Add($argument)}
        $stdout=[IO.File]::Open($Prefix+'.stdout.log',[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
        $stderr=[IO.File]::Open($Prefix+'.stderr.log',[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
        $process=[Diagnostics.Process]::new();$process.StartInfo=$info
        if(-not $process.Start()) {throw 'Owned diagnostic command did not start.'}
        $record.pid=$process.Id;$record.creationUtcTicks=$process.StartTime.ToUniversalTime().Ticks
        $outTask=$process.StandardOutput.BaseStream.CopyToAsync($stdout)
        $errTask=$process.StandardError.BaseStream.CopyToAsync($stderr)
        while($true) {
            $remaining=[int][Math]::Floor($TimeoutSeconds*1000-$clock.Elapsed.TotalMilliseconds)
            if($remaining -le 0) {throw 'Owned CRT diagnostic command exceeded its deadline.'}
            if($process.WaitForExit([Math]::Min(500,$remaining))) {break}
            if($stdout.Length+$stderr.Length -gt 4MB) {throw 'Owned CRT diagnostic output exceeded its bound.'}
        }
        $record.exitCode=$process.ExitCode
        # An exited command can leave a descendant holding its inherited pipe.
        # EOF must fit the original deadline as well; never start another budget.
        $remaining=[int][Math]::Floor($TimeoutSeconds*1000-$clock.Elapsed.TotalMilliseconds)
        if($remaining -le 0 -or -not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($outTask,$errTask),$remaining)) {
            throw 'Owned CRT diagnostic output pipes exceeded the original deadline.'
        }
        $outTask.GetAwaiter().GetResult()|Out-Null;$errTask.GetAwaiter().GetResult()|Out-Null
        $record.pipeDrainComplete=$true
        if($record.exitCode -ne 0) {throw 'Owned CRT diagnostic command exited nonzero.'}
        if($stdout.Length+$stderr.Length -gt 4MB) {throw 'Owned CRT diagnostic output exceeded its bound.'}
        $record.passed=$true
    } catch {$record.error=$_.Exception.Message;throw}
    finally {
        if($process) {
            if(-not $process.HasExited) {
                $record.forcedTermination=$true
                try {$process.Kill($true);if(-not $process.WaitForExit(5000)){throw 'Owned diagnostic process death is unproved.'}}
                catch {$record.cleanupError=$_.Exception.Message}
            }
            $process.Dispose()
        }
        if($stdout){$stdout.Dispose()};if($stderr){$stderr.Dispose()}
        $record.elapsedSeconds=$clock.Elapsed.TotalSeconds;$record.finishedUtc=[DateTime]::UtcNow.ToString('o')
        Write-BuildJson ($Prefix+'.command.json') $record
    }
    return $record
}

function Assert-CrtProbeRuntime($Proof,[int]$ExpectedPid,[string]$Executable,[string]$ProgramDirectory) {
    if($Proof.schemaVersion -ne 1 -or $Proof.pid -ne $ExpectedPid -or $Proof.image -ine $Executable -or
        $Proof.processMachine -ne 0 -or $Proof.nativeMachine -ne 0xaa64 -or
        $Proof.compiledArm64 -ne $true -or $Proof.compiledArm64Ec -ne $false -or
        $Proof.exceptionObserved -ne $true -or $Proof.vectorCount -ne 4096) {throw 'Actual native ARM64 EH/vector proof differs.'}
    $seen=@{}
    foreach($module in @($Proof.loadedModules)) {
        if($seen.ContainsKey($module.name) -or $module.machine -ne 0xaa64) {throw 'Duplicate or foreign loaded CRT module.'}
        $seen[$module.name]=$true
        if($module.name -ieq 'ucrtbase.dll') {
            if($module.path -ine (Join-Path ([Environment]::SystemDirectory) 'ucrtbase.dll')) {throw 'UCRT was not loaded from native System32.'}
        } elseif($module.name -cnotin @(Get-CrtProbeNames) -or $module.path -ine (Join-Path $ProgramDirectory $module.name)) {
            throw 'CRT module was not loaded from the exact eight-file private probe directory.'
        }
    }
    foreach($required in @('msvcp140.dll','vcruntime140.dll')) {if(-not $seen.ContainsKey($required)){throw 'Actual native C++ CRT module was not observed.'}}
}

function Write-CrtProbeSource([string]$Path) {
@'
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <tlhelp32.h>
#include <iostream>
#include <string>
#include <vector>
#include <stdexcept>
#include <cwctype>
#if !defined(_M_ARM64) || defined(_M_ARM64EC)
#error Probe requires the native ARM64 ABI, not x64 or ARM64EC.
#endif
static std::string json(const std::wstring& w) {
    int n=WideCharToMultiByte(CP_UTF8,0,w.data(),(int)w.size(),nullptr,0,nullptr,nullptr);
    std::string s(n,'\0');WideCharToMultiByte(CP_UTF8,0,w.data(),(int)w.size(),s.data(),n,nullptr,nullptr);
    std::string result="\"";for(unsigned char c:s){if(c=='\\'||c=='\"')result+='\\';if(c<32)return "null";result+=(char)c;}return result+'\"';
}
int main() {
    USHORT process=0,native=0;if(!IsWow64Process2(GetCurrentProcess(),&process,&native))return 10;
    if(process!=0||native!=IMAGE_FILE_MACHINE_ARM64)return 11;
    std::vector<std::string> values(4096,std::string(128,'x'));bool caught=false;
    try {throw std::runtime_error("OpenGeul native ARM64 CRT EH probe");}
    catch(const std::runtime_error& e){caught=std::string(e.what())=="OpenGeul native ARM64 CRT EH probe";}
    if(!caught||values.size()!=4096)return 12;
    WCHAR image[32768];DWORD size=GetModuleFileNameW(nullptr,image,32768);if(!size||size>=32768)return 13;
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE,GetCurrentProcessId());if(snapshot==INVALID_HANDLE_VALUE)return 14;
    MODULEENTRY32W row{};row.dwSize=sizeof(row);bool first=true;
    std::cout<<"{\"schemaVersion\":1,\"pid\":"<<GetCurrentProcessId()<<",\"image\":"<<json(image)
      <<",\"processMachine\":"<<process<<",\"nativeMachine\":"<<native
      <<",\"compiledArm64\":true,\"compiledArm64Ec\":false,\"exceptionObserved\":true,\"vectorCount\":4096,\"loadedModules\":[";
    if(!Module32FirstW(snapshot,&row)){CloseHandle(snapshot);return 15;}
    do {
        std::wstring name=row.szModule;for(auto& c:name)c=(wchar_t)towlower(c);
        if(name.rfind(L"vcruntime",0)!=0&&name.rfind(L"msvcp",0)!=0&&name.rfind(L"concrt",0)!=0&&name.rfind(L"vccorlib",0)!=0&&name!=L"ucrtbase.dll")continue;
        auto dos=(IMAGE_DOS_HEADER*)row.modBaseAddr;if(dos->e_magic!=IMAGE_DOS_SIGNATURE){CloseHandle(snapshot);return 16;}
        auto nt=(IMAGE_NT_HEADERS64*)(row.modBaseAddr+dos->e_lfanew);if(nt->Signature!=IMAGE_NT_SIGNATURE){CloseHandle(snapshot);return 17;}
        if(!first)std::cout<<",";first=false;
        std::cout<<"{\"name\":"<<json(name)<<",\"path\":"<<json(row.szExePath)<<",\"machine\":"<<nt->FileHeader.Machine<<"}";
    }while(Module32NextW(snapshot,&row));
    if(GetLastError()!=ERROR_NO_MORE_FILES){CloseHandle(snapshot);return 18;}
    if(!CloseHandle(snapshot))return 19;
    std::cout<<"]}"<<std::endl;return 0;
}
'@ | Set-Content -LiteralPath $Path -Encoding utf8NoBOM
}

function Invoke-NativeCrtProbe([string]$Output) {
    Assert-UnlinkedPath $Output
    if(Test-Path -LiteralPath $Output){throw 'Preserve existing diagnostic evidence; choose a fresh output.'}
    $out=[IO.Path]::GetFullPath($Output);New-Item -ItemType Directory $out|Out-Null
    $receipt=[ordered]@{schemaVersion=1;kind='native-arm64-crt-abi-diagnostic';passed=$false;
        engineQualified=$false;productQualified=$false;scope='diagnostic only; eight native CRTs; suspect DLL evidence only';stage='native-host';startedUtc=[DateTime]::UtcNow.ToString('o')}
    try {
        $receipt.host=Get-NativeBuildHost
        $repo=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
        $receipt.sourceCommit=(& git -C $repo rev-parse HEAD).Trim()
        if($LASTEXITCODE -ne 0 -or $receipt.sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or ($env:GITHUB_SHA -and $env:GITHUB_SHA -cne $receipt.sourceCommit)){throw 'Diagnostic source identity differs.'}
        $receipt.sourceRun=$env:GITHUB_RUN_ID;$receipt.runAttempt=$env:GITHUB_RUN_ATTEMPT
        $receipt.stage='native-vs18-toolchain'
        $vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
        $instances=@(& $vswhere -latest -products '*' -version '[18.0,19.0)' -format json|ConvertFrom-Json)
        if($LASTEXITCODE -ne 0 -or $instances.Count -ne 1){throw 'One actual Visual Studio18 installation is required.'}
        $vs=$instances[0].installationPath
        $toolsVersion=(Get-Content (Join-Path $vs 'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
        if($toolsVersion -cnotmatch '^14\.\d+\.\d+(?:\.\d+)?$'){throw 'Actual selected native compiler version is invalid.'}
        $tools=Join-Path $vs ('VC/Tools/MSVC/'+$toolsVersion);$bin=Join-Path $tools 'bin/Hostarm64/arm64'
        $receipt.compiler=@(foreach($name in @('cl.exe','link.exe','dumpbin.exe')){
            $identity=Get-ProductPeIdentity (Join-Path $bin $name)
            if($identity.role -cne 'nativeArm64'){throw 'Compiler/linker/dumpbin must be native ARM64.'};$identity})
        $v=[Version]$toolsVersion;$minimum=[Version]::new($v.Major,$v.Minor,$v.Build,[Math]::Max(0,$v.Revision))
        $candidates=@();$redist=Join-Path $vs 'VC/Redist/MSVC'
        foreach($directory in Get-ChildItem -LiteralPath $redist -Directory){
            if($directory.Name -match '^v?(14\.\d+\.\d+(?:\.\d+)?)$'){$version=[Version]$Matches[1]}
            elseif($directory.Name -ceq 'v145'){$version=$minimum}else{continue}
            $version=[Version]::new($version.Major,$version.Minor,$version.Build,[Math]::Max(0,$version.Revision))
            if($version -lt $minimum){continue}
            foreach($family in @('Microsoft.VC145.CRT','Microsoft.VC143.CRT')){
                $path=Join-Path $directory.FullName ('arm64/'+$family)
                if(Test-Path $path -PathType Container){$candidates+=@{path=$path;version=$version;family=$family}}
            }
        }
        if($candidates.Count -eq 0){throw 'No same-VS ARM64 CRT folder meets the compiler floor.'}
        $selected=@($candidates|Sort-Object -Property @{Expression={$_.version};Descending=$true},@{Expression={$_.family};Descending=$true})[0]
        $receipt.selectedToolchain=@{installationPath=$vs;compilerRoot=$tools;compilerVersion=$toolsVersion;minimumRuntimeVersion=[string]$minimum;crtDirectory=$selected.path;crtFamily=$selected.family}
        $program=Join-Path $out 'program';$evidenceOnly=Join-Path $out 'evidence-only';New-Item -ItemType Directory $program,$evidenceOnly|Out-Null
        $receipt.stage='retain-suspect-evidence-only'
        $suspect=Join-Path $selected.path 'vcruntime140_1.dll';Assert-UnlinkedPath $suspect
        $suspectCopy=Join-Path $evidenceOnly 'vcruntime140_1.dll';Copy-Item -LiteralPath $suspect -Destination $suspectCopy
        $receipt.suspect=@{sourcePath=$suspect;evidencePath=$suspectCopy;evidenceOnly=$true;signature=(Get-CrtSigningIdentity $suspect);size=(Get-Item $suspect).Length;sha256=(Get-FileHash $suspect -Algorithm SHA256).Hash.ToLowerInvariant()}
        if((Get-FileHash $suspectCopy -Algorithm SHA256).Hash.ToLowerInvariant() -cne $receipt.suspect.sha256){throw 'Suspect evidence copy differs from installed bytes.'}
        $receipt.stage='stage-eight-strict-aa64-crts'
        $receipt.staged=@(foreach($name in Get-CrtProbeNames){
            $file=Assert-CrtFile (Join-Path $selected.path $name) ([string]$minimum)
            $destination=Join-Path $program $name;Copy-Item -LiteralPath $file.sourcePath -Destination $destination
            $actual=Assert-CrtFile $destination ([string]$minimum)
            if($actual.sha256 -cne $file.sha256){throw 'Copied native CRT bytes differ.'}
            @{source=$file;destination=$destination;sha256=$actual.sha256}
        })
        $receipt.stage='compile-native-eh-vector-probe'
        $cpp=Join-Path $out 'probe.cpp';Write-CrtProbeSource $cpp
        $exe=Join-Path $program 'probe.exe';$batch=Join-Path $out 'compile.cmd'
        $dev=Join-Path $vs 'Common7/Tools/VsDevCmd.bat';Assert-UnlinkedPath $dev
        @('@echo off',('call "'+$dev+'" -no_logo -arch=arm64 -host_arch=arm64'),'if errorlevel 1 exit /b %errorlevel%',
          'set CL=','set _CL_=',
          ('"'+(Join-Path $bin 'cl.exe')+'" /nologo /EHsc /MD /std:c++17 /O2 /Fe:"'+$exe+'" /Fo:"'+(Join-Path $out 'probe.obj')+'" "'+$cpp+'" /link /MACHINE:ARM64 /INCREMENTAL:NO'),
          'exit /b %errorlevel%')|Set-Content -LiteralPath $batch -Encoding ascii
        Invoke-CrtProbeCommand -FilePath (Join-Path ([Environment]::SystemDirectory) 'cmd.exe') -Arguments @('/d','/c',$batch) -WorkingDirectory $out -Prefix (Join-Path $out 'compile') -TimeoutSeconds 120|Out-Null
        $receipt.executable=Get-ProductPeIdentity $exe
        if($receipt.executable.role -cne 'nativeArm64'){throw 'Compiled EH probe is not native ARM64.'}
        $receipt.stage='retain-headers-imports-exports'
        $targets=@($exe)+@(Get-CrtProbeNames|ForEach-Object {Join-Path $program $_})+@($suspectCopy)
        foreach($target in $targets){
            Invoke-CrtProbeCommand -FilePath (Join-Path $bin 'dumpbin.exe') -Arguments @('/nologo','/headers','/loadconfig','/imports','/exports',$target) -WorkingDirectory $out -Prefix (Join-Path $out ('dump-'+[IO.Path]::GetFileName($target))) -TimeoutSeconds 30|Out-Null
        }
        $receipt.stage='execute-native-abi-without-x64-one'
        $run=Invoke-CrtProbeCommand -FilePath $exe -Arguments @() -WorkingDirectory $program -Prefix (Join-Path $out 'runtime') -TimeoutSeconds 30
        $observed=Get-Content -LiteralPath (Join-Path $out 'runtime.stdout.log') -Raw|ConvertFrom-Json
        Assert-CrtProbeRuntime $observed $run.pid $exe $program
        $receipt.runtime=$observed;$receipt.passed=$true;$receipt.stage='complete'
    }catch{$receipt.error=$_.Exception.ToString();throw}
    finally{$receipt.finishedUtc=[DateTime]::UtcNow.ToString('o');Write-BuildJson (Join-Path $out 'diagnostic.json') $receipt}
}

if($MyInvocation.InvocationName -ne '.') {Invoke-NativeCrtProbe $Output}
