param([string]$InstalledExecutablePath, [string]$PayloadExecutablePath,
      [string]$OutputDirectory, [switch]$SelfTest)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$deadline=[DateTime]::UtcNow.AddSeconds(90)
$native=@'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class WackPathNative {
 [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
 public struct ACTCTX {
  public uint cbSize, dwFlags;
  [MarshalAs(UnmanagedType.LPWStr)] public string lpSource;
  public ushort wProcessorArchitecture, wLangId;
  [MarshalAs(UnmanagedType.LPWStr)] public string lpAssemblyDirectory;
  public IntPtr lpResourceName;
  [MarshalAs(UnmanagedType.LPWStr)] public string lpApplicationName;
  public IntPtr hModule;
 }
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
 static extern IntPtr CreateActCtxW(ref ACTCTX input);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
 [return:MarshalAs(UnmanagedType.Bool)]
 static extern bool QueryActCtxSettingsW(uint flags, IntPtr context, string nameSpace,
                                       string setting, StringBuilder value, UIntPtr capacity, out UIntPtr written);
 [DllImport("kernel32.dll", ExactSpelling=true)] static extern void ReleaseActCtx(IntPtr context);
 public sealed class Context : SafeHandleZeroOrMinusOneIsInvalid {
  public Context(IntPtr handle):base(true){SetHandle(handle);}
  protected override bool ReleaseHandle(){ReleaseActCtx(handle);return true;}
 }
 public static void SelfCheck() {
  int expected=IntPtr.Size==8?56:32;
  if(Marshal.SizeOf(typeof(ACTCTX))!=expected)throw new InvalidOperationException("ACTCTX ABI size mismatch");
  if(Marshal.OffsetOf(typeof(ACTCTX),"lpResourceName").ToInt32()!=(IntPtr.Size==8?32:20))
    throw new InvalidOperationException("ACTCTX resource pointer offset mismatch");
  using(var zero=new Context(IntPtr.Zero)) {if(!zero.IsInvalid)throw new InvalidOperationException("Zero handle validation failed");}
  using(var invalid=new Context(new IntPtr(-1))) {if(!invalid.IsInvalid)throw new InvalidOperationException("Invalid handle validation failed");}
 }
 public static Dictionary<string,object> Observe(string path) {
  var result=new Dictionary<string,object>();
  var input=new ACTCTX {cbSize=(uint)Marshal.SizeOf(typeof(ACTCTX)),dwFlags=8,
                       lpSource=path,lpResourceName=new IntPtr(1)};
  var handle=CreateActCtxW(ref input);
  int error=Marshal.GetLastWin32Error();
  bool valid=handle!=new IntPtr(-1)&&handle!=IntPtr.Zero;
  result["createSucceeded"]=valid;result["createWin32Error"]=valid?(object)null:error;
  result["flags"]=8;result["resourceId"]=1;result["actctxBytes"]=input.cbSize;
  var queries=new List<Dictionary<string,object>>();result["queries"]=queries;
  if(!valid){result["cleanupRequired"]=false;return result;}
  var context=new Context(handle);
  using(context) {
   string[] spaces={"http://schemas.microsoft.com/SMI/2016/WindowsSettings",
                    "http://schemas.microsoft.com/SMI/2005/WindowsSettings"};
   string[] names={"dpiAwareness","dpiAware"};
   for(int i=0;i<names.Length;i++) {
    var buffer=new StringBuilder(512);UIntPtr written;
    bool success=QueryActCtxSettingsW(0,context.DangerousGetHandle(),spaces[i],names[i],buffer,new UIntPtr((uint)512),out written);
    int queryError=Marshal.GetLastWin32Error();
    queries.Add(new Dictionary<string,object>{{"namespace",spaces[i]},{"setting",names[i]},
      {"success",success},{"win32Error",success?(object)null:queryError},{"writtenOrRequiredCharacters",written.ToUInt64()},
      {"value",success?(object)buffer.ToString():null},{"bufferCharacters",512}});
   }
  }
  result["contextReleased"]=context.IsClosed;return result;
 }
}
'@
Add-Type -TypeDefinition $native
[WackPathNative]::SelfCheck()
if ($SelfTest) { Write-Output 'ACTCTX ABI and invalid safe-handle self-check passed.'; return }
if (-not $InstalledExecutablePath -or -not $PayloadExecutablePath -or -not $OutputDirectory) { throw 'Three path arguments are required.' }
if ($env:GITHUB_ACTIONS -ne 'true' -or -not [Environment]::Is64BitProcess) { throw 'Path diagnostics require a disposable x64 Actions runner.' }
$output=(New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$summaryPath=Join-Path $output 'wack-path-observation.json'
if (Test-Path -LiteralPath $summaryPath) { throw 'Refusing to reuse path observations.' }
$expected='E282955C8E460CB66270949E51E492162BCE7CEBB75AE62562043C05885F8490'
$installed=[IO.Path]::GetFullPath($InstalledExecutablePath)
$payload=[IO.Path]::GetFullPath($PayloadExecutablePath)
$cwd=(Get-Location).ProviderPath
$hostPath=(Get-Process -Id $PID).Path
if ([IO.Path]::GetFileName($hostPath) -ine 'pwsh.exe') { throw 'The control host must be x64 pwsh.' }
$owned=$null; $ownedCreated=$false; $copied=$null
$probes=[Collections.Generic.List[object]]::new()
$contexts=[Collections.Generic.List[object]]::new()
$result=[ordered]@{scope='same-byte installed/payload/writable-copy path observations; no manifest, ACL, registry or gate changes';
                  cwd=$cwd;hostPath=$hostPath;sessionId=(Get-Process -Id $PID).SessionId;
                  totalDeadlineSeconds=90;nativeSelfCheckPassed=$true;paths=@();comProbes=$probes;activationContexts=$contexts}

function DescribePath([string]$Path) {
    $item=Get-Item -LiteralPath $Path
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -gt 64MB) { throw 'Control input must be a bounded regular file.' }
    $hash=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
    if ($hash -ne $expected) { throw 'Path control differs from the exact Run45 editor hash.' }
    return @{path=$item.FullName;characters=$item.FullName.Length;spaces=($item.FullName.ToCharArray() | Where-Object { $_ -eq ' ' } | Measure-Object).Count;
             bytes=$item.Length;sha256Before=$hash}
}

function ProbeCom([string]$Path,[string]$Label) {
    $childResult=Join-Path $output ('wack-binaryinfo-' + $Label + '.json')
    if (Test-Path -LiteralPath $childResult) { throw 'Refusing to reuse a child control result.' }
    $stdout=Join-Path $output ('binaryinfo-' + $Label + '-stdout.log')
    $stderr=Join-Path $output ('binaryinfo-' + $Label + '-stderr.log')
    $remaining=[Math]::Floor(($deadline-[DateTime]::UtcNow).TotalMilliseconds)
    if ($remaining -le 0) { $probes.Add(@{label=$Label;completed=$false;reason='total-deadline'});return }
    $arguments=@('-NoProfile','-NonInteractive','-File',('"'+(Join-Path $PSScriptRoot 'wack-binaryinfo-observation.ps1')+'"'),
                 '-ExecutablePath',('"'+$Path+'"'),'-OutputDirectory',('"'+$output+'"'),'-Label',$Label)
    $process=$null; $timedOut=$false; $logBudget=$false
    try {
        $process=Start-Process -FilePath $hostPath -ArgumentList $arguments -WorkingDirectory $cwd -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $timeout=[DateTime]::UtcNow.AddMilliseconds([Math]::Min(20000,$remaining))
        while (-not $process.WaitForExit(100)) {
            $logBudget=@(@($stdout,$stderr) | ForEach-Object { if(Test-Path -LiteralPath $_){(Get-Item -LiteralPath $_).Length -gt 64KB}else{$false} }) -contains $true
            if ([DateTime]::UtcNow -ge $timeout -or $logBudget) { $timedOut= -not $logBudget;taskkill /PID $process.Id /T /F | Out-Null;break }
        }
        $process.WaitForExit(5000) | Out-Null
        $process.Refresh()
        $record=@{label=$Label;completed=$process.HasExited;timedOut=$timedOut;logBudgetExceeded=$logBudget;exitCode=if($process.HasExited){$process.ExitCode}else{$null};resultPresent=(Test-Path -LiteralPath $childResult)}
        $probes.Add($record)
    } finally {
        if ($process -and -not $process.HasExited) { taskkill /PID $process.Id /T /F | Out-Null }
        foreach ($log in @($stdout,$stderr)) {
            if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 4096) {
                $stream=[IO.File]::OpenRead($log)
                try { $bytes=New-Object byte[] 4096;$count=$stream.Read($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
                if ($count -gt 0) { [IO.File]::WriteAllBytes($log,$bytes[0..($count-1)]) }
                else { [IO.File]::WriteAllBytes($log,[byte[]]@()) }
                $result.logsTruncated=$true
            }
        }
        if ($process) { $process.Dispose() }
    }
}

try {
    $installedInfo=DescribePath $installed; $payloadInfo=DescribePath $payload
    $result.paths=@($payloadInfo,$installedInfo)
    $root=[IO.Path]::GetFullPath($env:RUNNER_TEMP)
    if ([IO.Path]::GetPathRoot($root) -ine [IO.Path]::GetPathRoot($installed)) {
        $root=Join-Path $env:WINDIR 'Temp'
    }
    $root=[IO.Path]::GetFullPath($root).TrimEnd([char[]]'\/')
    $rootItem=Get-Item -LiteralPath $root
    if (-not $rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Owned copy parent must be a regular existing temp directory.' }
    $basename=[IO.Path]::GetFileName($installed)
    $name='OpenGeul '+[Guid]::NewGuid().ToString('N')
    $needed=$installed.Length-($root.Length+2+$basename.Length)-$name.Length
    if ($needed -gt 0 -and $needed -lt 120) { $name+=('x'*$needed) }
    $owned=Join-Path $root $name
    New-Item -ItemType Directory -Path $owned | Out-Null
    $ownedCreated=$true
    $copied=Join-Path $owned $basename
    Copy-Item -LiteralPath $installed -Destination $copied
    $copyInfo=DescribePath $copied
    $result.copyParentChoice=$root; $result.copyCreatedFrom='installed';$result.paths=@($payloadInfo,$installedInfo,$copyInfo)
    $result.copyPathLengthMatchesInstalled=($copied.Length -eq $installed.Length)
    $result.copySpaceCountMatchesInstalled=($copyInfo.spaces -eq $installedInfo.spaces)
    ProbeCom $payload 'replay-payload'
    ProbeCom $installed 'replay-installed'
    ProbeCom $copied 'copied-installed'
    foreach ($path in @($payload,$installed,$copied)) {
        if ([DateTime]::UtcNow -ge $deadline) { $contexts.Add(@{path=$path;completed=$false;reason='total-deadline'});continue }
        $contexts.Add(@{path=$path;completed=$true;native=[WackPathNative]::Observe($path)})
    }
} catch {
    $exception=$_.Exception.GetBaseException()
    $result.failure=@{type=$exception.GetType().FullName;message=$exception.Message.Substring(0,[Math]::Min(4096,$exception.Message.Length))}
}
finally {
    foreach ($description in $result.paths) {
        try { $description.sha256After=(Get-FileHash -LiteralPath $description.path -Algorithm SHA256).Hash;$description.unchanged=($description.sha256After -eq $description.sha256Before) }
        catch { $description.unchanged=$false;$description.afterHashErrorType=$_.Exception.GetBaseException().GetType().Name }
    }
    if ($ownedCreated) {
        try { Remove-Item -LiteralPath $owned -Recurse -Force }
        catch { $result.copyCleanupErrorType=$_.Exception.GetBaseException().GetType().FullName }
    }
    $result.copyRemoved=(-not $ownedCreated -or -not (Test-Path -LiteralPath $owned))
    $result.elapsedWithinDeadline=([DateTime]::UtcNow -le $deadline)
    $json=$result | ConvertTo-Json -Depth 14 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($json) -gt 64KB) { throw 'Path observation exceeds its JSON budget.' }
    [IO.File]::WriteAllText($summaryPath,$json,[Text.UTF8Encoding]::new($false))
}

# Static engine evidence only; retain selected strings and parsed PE imports, never SDK bytes/resources.
$scanner=@'
import hashlib,json,re,struct,sys
from pathlib import Path
p,out=map(Path,sys.argv[1:])
if p.stat().st_size>1024*1024:raise ValueError('engine input budget')
with p.open('rb') as source:data=source.read(1024*1024+1)
if len(data)>1024*1024 or hashlib.sha256(data).hexdigest()!='b991f5c98d16d0e7b12bf0a19dd55d361c79967bd280014748e2ab9d39afcac3':
 raise ValueError('engine identity mismatch')
def u16(n):return struct.unpack_from('<H',data,n)[0]
def u32(n):return struct.unpack_from('<I',data,n)[0]
pe=u32(60);opt=pe+24;wide=u16(opt)==0x20b
sections=[]
for i in range(u16(pe+6)):
 n=opt+u16(pe+20)+40*i;sections.append((u32(n+12),u32(n+8),u32(n+16),u32(n+20)))
def offset(rva):
 if rva<u32(opt+60):return rva
 for base,virtual,size,raw in sections:
  if base<=rva<base+min(virtual,size):return raw+rva-base
 raise ValueError('unmapped RVA')
def string(n):
 end=data.find(b'\0',n,min(n+512,len(data)))
 if end<0:raise ValueError('bounded string missing terminator')
 return data[n:end].decode('ascii')
imports=[];rva=u32(opt+(112 if wide else 96)+8)
if rva:
 n=offset(rva)
 for i in range(64):
  original,stamp,forward,name,first=struct.unpack_from('<IIIII',data,n+20*i)
  if not any((original,stamp,forward,name,first)):break
  functions=[];table=offset(original or first);stride=8 if wide else 4
  for j in range(256):
   token=struct.unpack_from('<Q' if wide else '<I',data,table+j*stride)[0]
   if not token:break
   functions.append('ordinal:'+str(token&65535) if token&(1<<(stride*8-1)) else string(offset(token)+2))
  imports.append({'dll':string(offset(name)),'functions':functions,'truncated':j==255})
terms=re.compile(r'manifest|actctx|dpi|temp|createfile|writefile|assembly|loadlibrary|queryact|filemapping|pathcch|pathcombine',re.I)
selected=[];total=0
for encoding,pattern in [('ascii',rb'[\x20-\x7e]{5,}'),('utf-16le',rb'(?:[\x20-\x7e]\x00){5,}')]:
 for m in re.finditer(pattern,data):
  text=m.group().decode(encoding)
  if terms.search(text):
   total+=1
   if len(selected)<64:selected.append({'encoding':encoding,'offsetBytes':m.start(),'text':text[:256],'truncated':len(text)>256})
j={'scope':'static hash-pinned SDK engine PE imports and selected string literals','sha256':hashlib.sha256(data).hexdigest(),
   'imports':imports,'selectedStrings':selected,'stringMatches':total,'stringsTruncated':total>len(selected)}
encoded=json.dumps(j,separators=(',',':')).encode()
if len(encoded)>65536:raise ValueError('engine metadata output budget')
out.open('xb').write(encoded)
print('Bounded native engine metadata written')
'@
if ([DateTime]::UtcNow -lt $deadline) {
    $engine=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/App Certification Kit/binaryinfo.dll'
    $scanner | python - $engine (Join-Path $output 'wack-binaryinfo-engine-metadata.json')
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Optional static engine metadata capture failed.' }
}
