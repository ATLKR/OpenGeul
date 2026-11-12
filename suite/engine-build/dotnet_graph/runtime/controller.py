"""Explicit Windows-only synthetic MSBuild observation; no engine qualification."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import zipfile
from .bounded import ProbeFailure,Runner,child_environment,phase_deadline,numeric_logger,json_numeric
from .fixture import CORE,NAMES,render,safe_path,verify_assets

MAX_RECEIPT=65536

def package_proof(path,root):
    path=safe_path(path);root=Path(root)
    if not path.is_file() or not 0<path.stat().st_size<=16*1024*1024:raise ProbeFailure(30)
    expected={'lib/netstandard2.0/'+n+'.dll':safe_path(root/'DotnetLibrary'/n/(n+'.dll')).read_bytes() for n in NAMES}
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)>32 or len(names)!=len(set(n.casefold() for n in names)) or any(n.startswith(('/', '\\')) or '..' in Path(n).parts for n in names):raise ProbeFailure(30)
        dlls={n for n in names if n.lower().endswith('.dll')}
        if dlls!=set(expected):raise ProbeFailure(30)
        for n,b in expected.items():
            info=z.getinfo(n)
            if info.file_size!=len(b) or z.read(n)!=b:raise ProbeFailure(30)
        nuspec=[n for n in names if n.endswith('.nuspec')]
        if len(nuspec)!=1 or z.getinfo(nuspec[0]).file_size>16384:raise ProbeFailure(30)
        import xml.etree.ElementTree as ET
        meta=ET.fromstring(z.read(nuspec[0]));ids=[x.text for x in meta.iter() if x.tag.rsplit('}',1)[-1]=='id']
        versions=[x.text for x in meta.iter() if x.tag.rsplit('}',1)[-1]=='version']
        if ids!=['OpenGeul.Diagnostic.Only'] or versions!=['0.0.0-diagnostic']:raise ProbeFailure(30)
    return {'known':1,'dllCount':4,'allOutputBytesEqual':1,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def verifier_record(value,base):
    keys={'schemaVersion','expectedBase','known','success','errorCode','values','publicApi','referenceClosure','copiedReferences'}
    if type(value) is not dict or set(value)!=keys:raise ProbeFailure(31)
    if any(type(value[k]) is not int for k in ('schemaVersion','expectedBase','known','success','errorCode')):raise ProbeFailure(31)
    if (value['schemaVersion'],value['expectedBase'],value['known'],value['success'],value['errorCode'])!=(1,base,1,1,0):raise ProbeFailure(31)
    if value['values']!=[base,base+2,base+6,base+10] or any(type(x) is not int for x in value['values']):raise ProbeFailure(31)
    for k in ('publicApi','referenceClosure','copiedReferences'):
        if type(value[k]) is not list or len(value[k])!=4 or any(type(x) is not int or x!=1 for x in value[k]):raise ProbeFailure(31)
    return value

def compilation_ownership(log):
    code=log['rootProjectCode']
    if code not in (1,2,3,4):raise ProbeFailure(24)
    for i in range(7):
        if log['cscStarted'][i]!=log['cscFinished'][i] or log['cscStarted'][i]!=log['cscSucceeded'][i]:raise ProbeFailure(24)
        if i!=code and log['cscStarted'][i]!=0:raise ProbeFailure(24)
    if log['cscStarted'][code]>1:raise ProbeFailure(24)
    return log['cscStarted'][code]

def reproduction_status(logs):
    known=(type(logs) is list and len(logs)==2 and all(type(l) is dict and l.get('known')==1 and type(l.get('known')) is int and l.get('buildStarted')==1 and l.get('buildFinished')==1 and type(l.get('cs2012Count')) is int and 0<=l['cs2012Count']<=65535 for l in logs))
    observed=any(l['cs2012Count']>0 for l in logs) if known else None
    return {'baselineObservationKnown':known,'baselineCS2012Observed':observed,'baselineNoReproduction':not observed if known else None}

def require_held_descendant_proof(state):
    if (type(state) is not dict or state.get('completed') is not False or state.get('cleanupProved') is not True
        or state.get('forcedCleanup') is not True or state.get('rootExitedWithLiveDescendantObserved') is not True):raise ProbeFailure(14)

def receipt_flags():
    return dict(sourceFullQualified=False,fullEngineQualified=False,acceptanceEligible=False,nativeGuiVerified=False,sourcePortApplied=False)

def pe_machine(path):
    path=safe_path(path)
    if not path.is_file() or not 152<=path.stat().st_size<=128*1024*1024:raise ProbeFailure(12)
    with path.open('rb') as f:
        head=f.read(64)
        if head[:2]!=b'MZ':raise ProbeFailure(12)
        off=struct.unpack_from('<I',head,60)[0]
        if not 64<=off<=path.stat().st_size-26:raise ProbeFailure(12)
        f.seek(off);tail=f.read(26)
    if tail[:4]!=b'PE\0\0' or struct.unpack_from('<H',tail,24)[0]!=0x20b:raise ProbeFailure(12)
    return struct.unpack_from('<H',tail,4)[0]

def context():
    names=('GITHUB_REPOSITORY','GITHUB_REPOSITORY_ID','GITHUB_REPOSITORY_OWNER','GITHUB_ACTOR','GITHUB_EVENT_NAME','GITHUB_REF','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_JOB','OPENGEUL_DOTNET_GRAPH_DIAGNOSTIC_ONLY','GITHUB_ACTIONS')
    v={n:os.environ.get(n) for n in names}
    if (v['GITHUB_ACTIONS']!='true' or v['GITHUB_REPOSITORY_OWNER']!='ATLKR' or v['GITHUB_REPOSITORY']!='ATLKR/OpenGeul' or v['GITHUB_REPOSITORY_ID']!='1405493151'
        or v['GITHUB_ACTOR']!=v['GITHUB_REPOSITORY_OWNER'] or v['GITHUB_EVENT_NAME']!='push'
        or v['GITHUB_REF']!='refs/heads/work/opengeul-office-dotnet-graph-diagnostic'
        or v['GITHUB_RUN_ATTEMPT']!='1' or v['GITHUB_JOB']!='dotnet-graph-diagnostic'
        or v['OPENGEUL_DOTNET_GRAPH_DIAGNOSTIC_ONLY']!='1'
        or not re.fullmatch('[0-9a-f]{40}',v['GITHUB_SHA'] or '') or not re.fullmatch('[1-9][0-9]{0,19}',v['GITHUB_RUN_ID'] or '')):raise ProbeFailure(13)
    return {'runId':int(v['GITHUB_RUN_ID']),'runAttempt':1,'sourceCommit':v['GITHUB_SHA']}

def sdk_plan():
    from ctypes import wintypes as W
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.GetCurrentProcess.argtypes=[];k.GetCurrentProcess.restype=W.HANDLE
    k.IsWow64Process2.argtypes=[W.HANDLE,ctypes.POINTER(W.USHORT),ctypes.POINTER(W.USHORT)];k.IsWow64Process2.restype=W.BOOL
    p,n=W.USHORT(),W.USHORT()
    if not k.IsWow64Process2(k.GetCurrentProcess(),ctypes.byref(p),ctypes.byref(n)) or p.value!=0 or n.value!=0xaa64:raise ProbeFailure(12)
    system=os.environ.get('SystemRoot');program=os.environ.get('ProgramFiles')
    if not system or not program:raise ProbeFailure(12)
    host=safe_path(Path(program)/'dotnet/dotnet.exe')
    if pe_machine(host)!=n.value or pe_machine(Path(sys.executable))!=n.value:raise ProbeFailure(12)
    sdkroot=host.parent/'sdk';versions=[]
    for d in sdkroot.iterdir():
        if d.is_dir() and re.fullmatch(r'(8|9|10)\.[0-9]+\.[0-9]+',d.name):
            safe_path(d);versions.append((tuple(map(int,d.name.split('.'))),d))
    if not versions:raise ProbeFailure(12)
    _,chosen=max(versions)
    if not (chosen/'Microsoft.Build.Framework.dll').is_file():raise ProbeFailure(12)
    return host,chosen,system,{'machine':n.value,'sdkVersion':list(map(int,chosen.name.split('.'))),'hostSha256':hashlib.sha256(host.read_bytes()).hexdigest(),'historicalFullSdkVersionMatched':False}

class Probe:
    def __init__(self,output,assets,host,sdk,system,api,report,overall):
        self.output=output;self.assets=assets;self.host=host;self.sdk=sdk;self.system=system;self.api=api;self.report=report;self.overall=overall;self.phase=0
        self.environment=child_environment(output/'owned-cache',system,host.parent)
    def run(self,args,root,*,logger=None,code=None,seconds=60,parallel=None):
        self.phase+=1;phase=self.phase
        deadline=phase_deadline(time.monotonic(),self.overall,seconds)
        commands=[];outputs=[]
        items=parallel if parallel is not None else [(args,code)]
        for argv,projectcode in items:
            command=[str(self.host),*map(str,argv)]
            if logger is not None:
                outfile=root/'observations'/(str(phase)+'-'+str(projectcode)+'.json')
                command.append('-logger:OpenGeulSynthetic.NumericLogger,'+str(logger)+';root='+str(root)+';output='+str(outfile)+';phase='+str(phase));outputs.append(outfile)
            commands.append((command,root,self.environment))
        state=Runner(self.api).run(commands,deadline)
        row={'phase':phase,'kindCode':self.report.get('currentKindCode',0),**state,'logs':[]};self.report['phases'].append(row)
        if not state['completed']:raise ProbeFailure(20)
        for p in outputs:
            data=numeric_logger(json_numeric(p),phase);row['logs'].append(data)
            if data['rootProjectCode']!=int(p.stem.split('-')[1]):raise ProbeFailure(22)
            if self.report.get('currentKindCode')==2 and (data['known']!=1 or data['loggerFailed'] or data['overflow'] or data['errorCount'] or data['buildStarted']!=1 or data['buildFinished']!=1 or data['buildSucceeded']!=1):raise ProbeFailure(22)
            if self.report.get('currentKindCode')==2:compilation_ownership(data)
        return row
    def require_zero(self,row):
        if any(c['exitCode']!=0 for c in row['children']):raise ProbeFailure(21)
    def build_args(self,project,root,name,variant):
        a=['build',project,'--no-restore','--disable-build-servers','-c','Release','-nologo','-v:quiet','-nodeReuse:false','-p:UseSharedCompilation=false','-p:RestoreFallbackFolders=']
        if variant=='baseline':a+=['-o',root/'DotnetLibrary'/name]
        return a
    def api_check(self,root,base,verifier):
        output=root/'observations'/('api-'+str(self.phase+1)+'.json')
        row=self.run([verifier,root,str(base),output],root);self.require_zero(row)
        proof=verifier_record(json_numeric(output),base);self.report['apiProofs'].append({'variantCode':1 if root.name=='baseline' else 2,'phase':row['phase'],**proof})
    def variant(self,variant,shared_logger=None,shared_verifier=None):
        root=render(self.output/variant,variant,self.sdk.name,self.sdk,self.assets)
        self.report['currentKindCode']=1 if variant=='baseline' else 2
        row=self.run(['restore',root/'Fixture.sln','--configfile',root/'NuGet.Config','--packages',self.environment['NUGET_PACKAGES'],'--disable-parallel','-v:quiet','-p:RestoreFallbackFolders='],root);self.require_zero(row)
        observer=root/'SdkObserver'
        for name in ('NumericLogger','ApiVerifier'):
            row=self.run(['build',observer/name/(name+'.csproj'),'--no-restore','--disable-build-servers','-c','Release','-o',observer/name,'-nologo','-v:quiet','-nodeReuse:false','-p:UseSharedCompilation=false'],root);self.require_zero(row)
        logger=observer/'NumericLogger/NumericLogger.dll';verifier=observer/'ApiVerifier/ApiVerifier.dll'
        if not logger.is_file() or not verifier.is_file():raise ProbeFailure(22)
        initial_logs=[]
        for name in NAMES[:2]:
            row=self.run(self.build_args(root/'DotnetLibrary'/name/(name+'.csproj'),root,name,variant),root,logger=logger,code=NAMES.index(name)+1);self.require_zero(row);initial_logs.extend(row['logs'])
        pair=[(self.build_args(root/'DotnetLibrary'/name/(name+'.csproj'),root,name,variant),NAMES.index(name)+1) for name in NAMES[2:]]
        row=self.run(None,root,logger=logger,parallel=pair)
        if variant=='baseline':self.report['baselinePairReached']=True
        if variant=='candidate':
            self.require_zero(row);initial_logs.extend(row['logs'])
            initial_counts=[sum(l['cscStarted'][i] for l in initial_logs) for i in range(7)]
            if initial_counts[1:5]!=[1,1,1,1] or initial_counts[0]!=0 or not row['siblingOverlapObserved']:raise ProbeFailure(24)
            self.report['candidateInitialCscCounts']=initial_counts
        if variant=='baseline':self.report.update(reproduction_status(row['logs']))
        self.report['graphObservations'].append({'variantCode':1 if variant=='baseline' else 2,'pairPhase':row['phase'],'cscCounts':[sum(l['cscStarted'][i] for l in row['logs']) for i in range(7)],'siblingRoots':2,'bothClean':state_clean(row)})
        if variant=='baseline' and any(c['exitCode']!=0 for c in row['children']):return
        self.api_check(root,1,verifier)
        for name in NAMES:
            d=root/'observations'/('paths-'+name);d.mkdir()
            args=['msbuild',root/'DotnetLibrary'/name/(name+'.csproj'),'-target:GetTargetPath','-property:Configuration=Release','-property:CustomAfterMicrosoftCommonTargets='+str(root/'GraphObserver.targets'),'-property:ProbeOutput='+str(d),'-nodeReuse:false','-verbosity:quiet']
            row=self.run(args,root,logger=logger,code=NAMES.index(name)+1);self.require_zero(row)
            path=d/(name+'.path')
            if not path.is_file() or path.stat().st_size>8:raise ProbeFailure(23)
            match=path.read_bytes().strip()==b'1'
            if variant=='candidate' and (not match or not row['logs'][0]['known'] or row['logs'][0]['targetPathMatched'][NAMES.index(name)+1]<1):raise ProbeFailure(23)
            self.report['pathProofs'].append({'variantCode':1 if variant=='baseline' else 2,'projectCode':NAMES.index(name)+1,'pathMatches':int(match),'typedObserved':int(row['logs'][0]['targetPathMatched'][NAMES.index(name)+1]>0)})
        # Baseline is an observation cohort, not a prerequisite for candidate success.
        if variant=='baseline':return
        unchanged=[]
        for name in NAMES:
            row=self.run(self.build_args(root/'DotnetLibrary'/name/(name+'.csproj'),root,name,variant),root,logger=logger,code=NAMES.index(name)+1);self.require_zero(row);unchanged.extend(row['logs'])
        if sum(sum(l['cscStarted']) for l in unchanged)!=0:raise ProbeFailure(24)
        source=root/'Source/net_ure/source/basetypes/Any.cs';raw=source.read_text()
        if raw.count('=> 1;')!=1:raise ProbeFailure(24)
        source.write_text(raw.replace('=> 1;','=> 2;'),encoding='utf-8')
        counts=[0]*7
        for name in NAMES:
            row=self.run(self.build_args(root/'DotnetLibrary'/name/(name+'.csproj'),root,name,variant),root,logger=logger,code=NAMES.index(name)+1);self.require_zero(row)
            for l in row['logs']:counts=[a+b for a,b in zip(counts,l['cscStarted'])]
        if counts[1]!=1 or any(x not in (0,1) for x in counts[2:5]) or counts[0]!=0:raise ProbeFailure(24)
        self.report['candidateImplementationChangeCscCounts']=counts
        self.api_check(root,2,verifier)
        row=self.run(['pack',root/'DiagnosticPackage/DiagnosticPackage.csproj','--no-build','--no-restore','-c','Release','-o',root/'package','-v:quiet','-p:RestoreFallbackFolders='],root);self.require_zero(row)
        p=root/'package/OpenGeul.Diagnostic.Only.0.0.0-diagnostic.nupkg';self.report['packageProof']=package_proof(p,root)
        # Preserve the real DotnetTest packages/reference model in an owned NUnit fixture.
        consumer=root/'DotnetTest';consumer.mkdir();import xml.etree.ElementTree as ET
        p=ET.Element('Project',Sdk='Microsoft.NET.Sdk');g=ET.SubElement(p,'PropertyGroup')
        for k,v in [('TargetFramework','net'+self.sdk.name.split('.')[0]+'.0'),('IsTestProject','true'),('IsPackable','false'),('BuildProjectReferences','false'),('UseSharedCompilation','false')]:ET.SubElement(g,k).text=v
        items=ET.SubElement(p,'ItemGroup')
        for name in NAMES[2:]:ET.SubElement(items,'ProjectReference',Include=str(root/'DotnetLibrary'/name/(name+'.csproj')),GlobalPropertiesToRemove='OutputPath;OutDir')
        for package,version in [('NUnit','4.1.0'),('NUnit3TestAdapter','4.5.0'),('Microsoft.NET.Test.Sdk','17.10.0')]:ET.SubElement(items,'PackageReference',Include=package,Version=version)
        (consumer/'Consumer.csproj').write_bytes(ET.tostring(p,encoding='utf-8'))
        test_receipt=root/'observations/test-executed.numeric'
        literal=json.dumps(str(test_receipt))
        text='using NUnit.Framework; [TestFixture] public sealed class OwnedGraphTests { [Test] public void ActualReferencedApis() { Assert.That(OpenGeulSynthetic.OfficeValue.Read(),Is.EqualTo(8)); Assert.That(OpenGeulSynthetic.BridgeValue.Read(),Is.EqualTo(12)); System.IO.File.WriteAllText('+literal+',"1"); } }'
        (consumer/'Consumer.cs').write_text(text,encoding='utf-8')
        row=self.run(['restore',consumer/'Consumer.csproj','--configfile',root/'NuGet.Config','--packages',self.environment['NUGET_PACKAGES'],'--disable-parallel','-v:quiet','-p:RestoreFallbackFolders='],root);self.require_zero(row)
        row=self.run(['test',consumer/'Consumer.csproj','--no-restore','--disable-build-servers','-c','Release','-o',consumer/'out','-nologo','-v:quiet','-nodeReuse:false','-p:UseSharedCompilation=false'],root);self.require_zero(row)
        if not test_receipt.is_file() or test_receipt.stat().st_size!=1 or test_receipt.read_bytes()!=b'1':raise ProbeFailure(25)
        copied=[]
        for name in NAMES:
            a=safe_path(consumer/'out'/(name+'.dll'));b=safe_path(root/'DotnetLibrary'/name/(name+'.dll'));copied.append(int(a.is_file() and a.read_bytes()==b.read_bytes()))
        if copied!=[1]*4:raise ProbeFailure(25)
        self.report['consumerProof']={'known':1,'testExecuted':1,'ownedApiAssertionsPassed':1,'copiedReferences':copied}
        self.report['candidateGraphPassed']=True

def state_clean(row):return int(row['completed'] and row['cleanupProved'] and not row['forcedCleanup'])

def main(argv=None):
    class SilentParser(argparse.ArgumentParser):
        def error(self,message):raise ProbeFailure(13)
    parser=SilentParser(add_help=False);parser.add_argument('--diagnostic-only',action='store_true');parser.add_argument('--output',type=Path,required=True)
    try:args=parser.parse_args(argv)
    except BaseException:return 2
    if not args.diagnostic_only:return 2
    report={'schemaVersion':1,'kind':'synthetic-dotnet-graph-diagnostic','coreCommit':CORE,**receipt_flags(),'probeCompleted':False,'candidateGraphPassed':False,**reproduction_status([]),'ciLockCauseProven':False,'historicalLockOwnerObserved':False,'baselineInvocationIdenticalToCI':False,'phases':[],'graphObservations':[],'apiProofs':[],'pathProofs':[],'failureCode':0}
    start=time.monotonic();overall=start+600;output=None
    try:
        if os.name!='nt' or not __debug__:raise ProbeFailure(12)
        report.update(context());output=safe_path(args.output.absolute(),fresh=True);output.mkdir(parents=True)
        assets=Path(__file__).resolve().parent.parent
        verify_assets(assets)
        from .sdk_win32 import NativeApi
        host,sdk,system,plan=sdk_plan();report['sdk']=plan;api=NativeApi();probe=Probe(output,assets,host,sdk,system,api,report,overall)
        environment=child_environment(output/'launcher-preflight',system,host.parent)
        no_op=Runner(api).run([([sys.executable,'-I','-c','raise SystemExit(0)'],output,environment)],phase_deadline(time.monotonic(),overall,10))
        report['launcherNoOp']=no_op
        if not no_op['completed'] or no_op['children'][0]['exitCode']!=0:raise ProbeFailure(14)
        held='import subprocess,sys;subprocess.Popen([sys.executable,"-I","-c","import time;time.sleep(30)"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);raise SystemExit(0)'
        negative=Runner(api).run([([sys.executable,'-I','-c',held],output,environment)],phase_deadline(time.monotonic(),overall,5));report['launcherHeldDescendant']=negative
        require_held_descendant_proof(negative)
        try:probe.variant('baseline')
        except ProbeFailure as error:
            last=report['phases'][-1] if report['phases'] else {}
            if report.get('baselinePairReached') and error.code in (21,23,31) and last.get('completed') and last.get('cleanupProved'):
                report['baselineBoundaryFailureCode']=error.code
            else:raise
        probe.variant('candidate');report['probeCompleted']=True
    except BaseException as e:report['failureCode']=e.code if isinstance(e,ProbeFailure) else 99
    finally:
        report.pop('currentKindCode',None);report['controllerSeconds']=round(time.monotonic()-start,3)
        if report['controllerSeconds']>600:report['candidateGraphPassed']=False;report['failureCode']=2
        try:
            encoded=json.dumps(report,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            if len(encoded)>MAX_RECEIPT:raise ProbeFailure(3)
            if output:
                with (output/'dotnet-graph-diagnostic.json').open('xb') as f:f.write(encoded)
        except BaseException:return 3
    return 0 if report['probeCompleted'] and report['candidateGraphPassed'] else 1
