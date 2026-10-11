param([Parameter(Mandatory)][string]$InstalledExecutablePath,
      [Parameter(Mandatory)][string]$OutputDirectory,
      [Parameter(Mandatory)][string]$ExpectedPackageFullName)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if ($ExpectedPackageFullName.Length -gt 256 -or
    $ExpectedPackageFullName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9.-]{0,99}_[0-9]{1,5}(\.[0-9]{1,5}){3}_x64_[A-Za-z0-9.-]{0,30}_[a-z0-9]{13}$') {
    throw 'Expected package full name has an invalid bounded identity format.'
}
$contextOutput=(New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$contextSummary=Join-Path $contextOutput 'wack-package-context-observation.json'
$contextHost=Join-Path $contextOutput 'package-context-host.json'
if ((Test-Path -LiteralPath $contextSummary) -or (Test-Path -LiteralPath $contextHost)) {
    throw 'Refusing to reuse package-context observations.'
}
$contextProcess=Get-Process -Id $PID
$contextResult=[ordered]@{
    scope='diagnostic package-identity control only; ordinary WACK remains required; no executable, ACL or registry changes';
    processId=$PID;sessionId=$contextProcess.SessionId;hostPath=$contextProcess.Path;
    is64BitProcess=[Environment]::Is64BitProcess;clrVersion=[string][Environment]::Version;
    powershellVersion=[string]$PSVersionTable.PSVersion;cwd=(Get-Location).ProviderPath;
    packageIdentityVerified=$false;captureComplete=$false;finished=$false
}
# The launcher can identify and bound this exact process before any SDK calls occur.
[IO.File]::WriteAllText($contextHost,(@{processId=$PID;sessionId=$contextProcess.SessionId;
    expectedPackageFullName=$ExpectedPackageFullName;scope='owned diagnostic package-context observer';
    hostPath=$contextProcess.Path;startedUtc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
$contextBefore=$null;$contextEditor=$null;$contextStage='environment-verification'

function ContextFailure([Exception]$ErrorObject,[string]$Stage) {
    $base=$ErrorObject.GetBaseException()
    $bits=[BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$base.HResult),0)
    return @{stage=$Stage;exceptionType=$base.GetType().FullName;hresult=('0x{0:X8}' -f $bits)}
}
function ContextCompileActivationApi {
    if (-not ('WackPathNative' -as [type])) {
        . (Join-Path $PSScriptRoot 'wack-path-observation.ps1') -SelfTest | Out-Null
    }
    [WackPathNative]::SelfCheck()
}

try {
    if ($env:GITHUB_ACTIONS -ne 'true' -or -not [Environment]::Is64BitProcess) {
        throw 'Package diagnostics require a disposable x64 Actions runner.'
    }
    $contextResult.expectedPackageFullName=$ExpectedPackageFullName
    $contextStage='editor-identity'
    $contextEditor=[IO.Path]::GetFullPath($InstalledExecutablePath)
    $contextItem=Get-Item -LiteralPath $contextEditor
    if ($contextItem.PSIsContainer -or ($contextItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $contextItem.Length -gt 64MB) {
        throw 'Editor must be a bounded regular file.'
    }
    $contextBefore=(Get-FileHash -LiteralPath $contextEditor -Algorithm SHA256).Hash
    $contextResult.editor=@{path=$contextEditor;bytes=$contextItem.Length;sha256Before=$contextBefore}
    if ($contextBefore -ine 'E282955C8E460CB66270949E51E492162BCE7CEBB75AE62562043C05885F8490') {
        throw 'Editor differs from the exact Run46 bytes.'
    }
    $contextStage='package-identity'
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class WackContextIdentity {
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,ExactSpelling=true)]
 static extern int GetCurrentPackageFullName(ref uint length,StringBuilder value);
 [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr GetCurrentProcess();
 [DllImport("advapi32.dll",ExactSpelling=true,SetLastError=true)]
 [return:MarshalAs(UnmanagedType.Bool)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
 [DllImport("advapi32.dll",ExactSpelling=true,SetLastError=true)]
 [return:MarshalAs(UnmanagedType.Bool)] static extern bool GetTokenInformation(IntPtr token,int kind,out uint value,uint bytes,out uint written);
 [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
 [return:MarshalAs(UnmanagedType.Bool)] static extern bool CloseHandle(IntPtr handle);
 sealed class Token : SafeHandleZeroOrMinusOneIsInvalid {
  public Token(IntPtr handle):base(true){SetHandle(handle);}
  protected override bool ReleaseHandle(){return CloseHandle(handle);}
 }
 public static Dictionary<string,object> Package() {
  uint length=0;int first=GetCurrentPackageFullName(ref length,null);
  var result=new Dictionary<string,object>{{"firstReturnCode",first},{"requiredCharacters",length},{"bufferBudgetCharacters",256}};
  if(first!=122||length==0||length>256){result["queried"]=false;return result;}
  var value=new StringBuilder((int)length);int code=GetCurrentPackageFullName(ref length,value);
  result["queried"]=true;result["returnCode"]=code;result["writtenOrRequiredCharacters"]=length;
  result["fullName"]=code==0?(object)value.ToString():null;return result;
 }
 public static Dictionary<string,object> ProcessToken() {
  IntPtr raw;bool opened=OpenProcessToken(GetCurrentProcess(),8,out raw);int error=Marshal.GetLastWin32Error();
  var result=new Dictionary<string,object>{{"opened",opened},{"openWin32Error",opened?(object)null:error}};
  if(!opened)return result;
  using(var token=new Token(raw)) {
   string[] names={"TokenElevation","TokenIsAppContainer","TokenElevationType","TokenType"};int[] kinds={20,29,18,8};
   for(int i=0;i<names.Length;i++) {
    uint value,written;bool success=GetTokenInformation(token.DangerousGetHandle(),kinds[i],out value,4,out written);
    int queryError=Marshal.GetLastWin32Error();
    result[names[i]]=new Dictionary<string,object>{{"success",success},{"value",success?(object)value:null},
      {"win32Error",success?(object)null:queryError},{"writtenBytes",written}};
   }
  }
  return result;
 }
}
'@
    $contextPackage=[WackContextIdentity]::Package()
    $contextResult.package=$contextPackage
    if (-not $contextPackage.ContainsKey('returnCode') -or $contextPackage.returnCode -ne 0 -or
        -not ([string]$contextPackage.fullName).Equals($ExpectedPackageFullName,[StringComparison]::Ordinal)) {
        throw 'The actual API-calling process lacks the exact candidate package identity.'
    }
    $contextResult.packageIdentityVerified=$true
    try {
        $contextResult.processToken=[WackContextIdentity]::ProcessToken()
        $contextIdentity=$null;$contextThreadIdentity=$null
        try {
            $contextIdentity=[Security.Principal.WindowsIdentity]::GetCurrent()
            $contextResult.windowsIdentityImpersonationLevel=[string]$contextIdentity.ImpersonationLevel
            $contextHasher=[Security.Cryptography.SHA256]::Create()
            try {
                $contextResult.principalSidSha256=([BitConverter]::ToString($contextHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($contextIdentity.User.Value)))).Replace('-','').ToLowerInvariant()
            } finally { $contextHasher.Dispose() }
            $contextThreadIdentity=[Security.Principal.WindowsIdentity]::GetCurrent($true)
            $contextResult.threadImpersonating=($null -ne $contextThreadIdentity)
            if ($contextThreadIdentity) { $contextResult.threadImpersonationLevel=[string]$contextThreadIdentity.ImpersonationLevel }
        } finally {
            if($contextThreadIdentity){$contextThreadIdentity.Dispose()}
            if($contextIdentity){$contextIdentity.Dispose()}
        }
        $contextResult.tokenMetadataCaptured=$true
    } catch {
        $contextResult.tokenMetadataCaptured=$false
        $contextResult.tokenMetadataFailure=ContextFailure $_.Exception 'optional-token-metadata'
    }
    $contextStage='activation-context'
    ContextCompileActivationApi
    $contextResult.nativeSelfCheckPassed=$true
    $contextResult.activationContext=[WackPathNative]::Observe($contextEditor)
    $contextStage='BinaryInfo-same-process'
    # The invocation operator supplies a child PowerShell scope, while keeping this PID/token.
    & (Join-Path $PSScriptRoot 'wack-binaryinfo-observation.ps1') -ExecutablePath $contextEditor -OutputDirectory $contextOutput -Label installed-in-package
    $contextBinaryPath=Join-Path $contextOutput 'wack-binaryinfo-installed-in-package.json'
    $contextResult.binaryInfoObservationPresent=(Test-Path -LiteralPath $contextBinaryPath)
    if (-not $contextResult.binaryInfoObservationPresent -or (Get-Item -LiteralPath $contextBinaryPath).Length -gt 64KB) {
        throw 'Same-process BinaryInfo did not emit its bounded observation.'
    }
    $contextResult.captureComplete=$true
} catch {
    $contextResult.failure=ContextFailure $_.Exception $contextStage
} finally {
    if ($contextBefore) {
        try {
            $contextAfter=(Get-FileHash -LiteralPath $contextEditor -Algorithm SHA256).Hash
            $contextResult.editor.sha256After=$contextAfter
            $contextResult.editor.unchanged=($contextAfter -eq $contextBefore)
            if (-not $contextResult.editor.unchanged) { $contextResult.captureComplete=$false }
        } catch {
            $contextResult.captureComplete=$false
            $contextResult.editorAfterHashFailure=ContextFailure $_.Exception 'editor-unchanged-check'
        }
    }
    $contextResult.finished=$true
    $contextJson=$contextResult | ConvertTo-Json -Depth 12 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($contextJson) -gt 64KB) { throw 'Package-context observation exceeds its JSON budget.' }
    [IO.File]::WriteAllText($contextSummary,$contextJson,[Text.UTF8Encoding]::new($false))
}
Write-Output 'Package-context diagnostic observations written; normal WACK remains required.'
