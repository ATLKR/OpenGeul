"""Render only the pinned synthetic graph; never a source-engine input."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from .bounded import ProbeFailure
CORE='9dea406ab7695df6325b11b0e19fdca8db4b7276'
ASSET_MANIFEST_SHA='796a5e67cea7f2ce6e59044a24dac3389d1daa5dea0287729668202e41ff7e27'
NAMES=('net_basetypes','net_uretypes','net_oootypes','net_bridge')
GRAPH={NAMES[0]:[],NAMES[1]:[NAMES[0]],NAMES[2]:[NAMES[1]],NAMES[3]:[NAMES[1]]}
SOURCE_PINS={'solenv/gbuild/DotnetLibrary.mk': {'bytes': 5315, 'sha256': 'f4d2e54af51037267b4027461d7caa6c7a22d3660b99bedeb68f2160d46f476b', 'gitBlob': 'c0967168e92b278e383b33bcd78462401d0616ac'}, 'solenv/gbuild/DotnetTest.mk': {'bytes': 5154, 'sha256': '5391ab97bd1a43c71584afd2819499c1fca75ab95a2e35835dc7e10a02813272', 'gitBlob': '635797cf782f0fec41252ca794c04e3775ce2670'}, 'net_ure/Module_net_ure.mk': {'bytes': 984, 'sha256': 'da85da18dbc52afddc5381d6d1c6230c6e17483959d52adf10c135f870c99ba2', 'gitBlob': '0ae4cd0361c811343f62c895fe9e49a26acd07fb'}, 'net_ure/DotnetLibrary_net_basetypes.mk': {'bytes': 955, 'sha256': 'bdfdc49a9a2fbce2d552615e62e75b347ddf264025b463ae377ff3c36ed2f6af', 'gitBlob': 'ae49c2b78c4b3a86e581cf760651e889d99e2e91'}, 'net_ure/DotnetLibrary_net_uretypes.mk': {'bytes': 802, 'sha256': '6b5702367b60e766ff9ca571a051c79d1e84a6e32514ad385229bfbcb90ef71d', 'gitBlob': 'a796032d8e55fe68f2be7715a9fc5ebf4b8fcd4d'}, 'net_ure/DotnetLibrary_net_oootypes.mk': {'bytes': 801, 'sha256': '4f1ac8905639f44b31bc72b4ceaa5b5a159e826908cace6772800332ffba4437', 'gitBlob': 'b12a32f50ed25fba4cb53c5cc93a378a3c7a5540'}, 'net_ure/DotnetLibrary_net_bridge.mk': {'bytes': 1754, 'sha256': '4b75434ca42850650b2cc2334816d06a9fb72c66fdd143efa1fc0fd953f8af49', 'gitBlob': 'd6a47c947e7e478d4c43de5c379a3db1978f29bd'}, 'net_ure/CustomTarget_net_nuget_pkg.mk': {'bytes': 2452, 'sha256': '1015ccb28dba46cafc30842e8ccfd9b35e508c40bc893c87a44d8bc8ad3ab451', 'gitBlob': '2c92dd4a521382a36aa58446d0e2821c9bc1f52f'}}

def safe_path(path,*,fresh=False):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts or any(c in str(p) for c in '\0;<>%&!|^"\r\n\''):raise ProbeFailure(10)
    for part in (p,*p.parents):
        if part.exists() or part.is_symlink():
            st=part.lstat()
            if part.is_symlink() or getattr(st,'st_file_attributes',0)&0x400:raise ProbeFailure(10)
    if fresh and p.exists():raise ProbeFailure(10)
    return p

def _verify_assets(assets):
    raw=(assets/'asset-pins.json').read_bytes()
    if not 0<len(raw)<=256*1024 or hashlib.sha256(raw).hexdigest()!=ASSET_MANIFEST_SHA:raise ProbeFailure(11)
    manifest=json.loads(raw)
    if set(manifest)!={'schemaVersion','kind','files'} or manifest['schemaVersion']!=1 or manifest['kind']!='synthetic-dotnet-probe-assets' or not 1<=len(manifest['files'])<=128:raise ProbeFailure(11)
    seen=set()
    for item in manifest['files']:
        rel=item.get('path')
        if type(rel) is not str or Path(rel).is_absolute() or '..' in Path(rel).parts or any(x in rel for x in ('\\',':')) or rel.casefold() in seen:raise ProbeFailure(11)
        seen.add(rel.casefold());path=safe_path((assets/rel).absolute())
        if not path.is_file() or path.stat().st_size!=item['bytes'] or not 0<=item['bytes']<=512*1024:raise ProbeFailure(11)
        with path.open('rb') as stream:data=stream.read(512*1024+1)
        if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ProbeFailure(11)
    c=json.loads((assets/'fixtures/contract.json').read_bytes())
    if c.get('coreCommit')!=CORE or c.get('graph')!=GRAPH or c.get('targetFramework')!='netstandard2.0':raise ProbeFailure(11)
    if type(c.get('sourcePins')) is not list or len(c['sourcePins'])!=len(SOURCE_PINS) or {x.get('path') for x in c['sourcePins'] if type(x) is dict}!=set(SOURCE_PINS):raise ProbeFailure(11)
    for p in c['sourcePins']:
        if {k:p.get(k) for k in ('bytes','sha256','gitBlob')}!=SOURCE_PINS[p['path']]:raise ProbeFailure(11)
        path=safe_path((assets/'source-snapshot'/p['path']).absolute())
        data=path.read_bytes()
        if len(data)!=p['bytes'] or hashlib.sha256(data).hexdigest()!=p['sha256'] or hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=p['gitBlob']:raise ProbeFailure(11)
    return c

def verify_assets(assets):
    try:return _verify_assets(assets)
    except ProbeFailure:raise
    except BaseException:raise ProbeFailure(11) from None

def render(root,variant,sdk_version,sdk_dir,assets):
    root=safe_path(root,fresh=True);assets=Path(assets)
    if variant not in ('baseline','candidate') or not re.fullmatch(r'(8|9|10)\.\d+\.\d+',sdk_version):raise ProbeFailure(11)
    verify_assets(assets);root.mkdir(parents=True)
    shutil.copytree(assets/'fixtures/source',root/'Source')
    shutil.copytree(assets/'fixtures/generated',root/'CustomTarget')
    (root/'observations').mkdir()
    (root/'global.json').write_text(json.dumps({'sdk':{'version':sdk_version,'rollForward':'disable','allowPrerelease':False}}),encoding='utf-8')
    for name in NAMES:
        p=root/'DotnetLibrary'/name/(name+'.csproj');p.parent.mkdir(parents=True)
        raw=(assets/'templates'/variant/(name+'.csproj')).read_text()
        raw=raw.replace('@VARIANT_ROOT@',root.as_posix())
        tree=ET.fromstring(raw)
        if tree.findtext('PropertyGroup/TargetFramework')!='netstandard2.0':raise ProbeFailure(11)
        if [Path(x.attrib['Include']).stem for x in tree.findall('ItemGroup/ProjectReference')]!=GRAPH[name]:raise ProbeFailure(11)
        p.write_text(raw,encoding='utf-8')
    config='<configuration><packageSources><clear/><add key="official" value="https://api.nuget.org/v3/index.json"/></packageSources><packageSourceMapping><packageSource key="official"><package pattern="*"/></packageSource></packageSourceMapping></configuration>'
    (root/'NuGet.Config').write_text(config,encoding='utf-8')
    observer=root/'SdkObserver'
    for name in ('NumericLogger','ApiVerifier'):
        d=observer/name;d.mkdir(parents=True)
        shutil.copy2(assets/'runtime/sdk-observer'/(name+'.cs'),d/(name+'.cs'))
        project=ET.Element('Project',Sdk='Microsoft.NET.Sdk');g=ET.SubElement(project,'PropertyGroup')
        for k,v in [('TargetFramework','net'+sdk_version.split('.')[0]+'.0'),('OutputType','Exe' if name=='ApiVerifier' else 'Library'),('ImplicitUsings','disable'),('Nullable','enable'),('AssemblyName',name),('Version','0.1.0'),('UseSharedCompilation','false')]:ET.SubElement(g,k).text=v
        if name=='NumericLogger':
            item=ET.SubElement(project,'ItemGroup');ref=ET.SubElement(item,'Reference',Include='Microsoft.Build.Framework');ET.SubElement(ref,'HintPath').text=str(Path(sdk_dir)/'Microsoft.Build.Framework.dll');ET.SubElement(ref,'Private').text='false'
        (d/(name+'.csproj')).write_bytes(ET.tostring(project,encoding='utf-8'))
    pack_project(root)
    projects=[('DotnetLibrary/'+n+'/'+n+'.csproj',n) for n in NAMES]+[('SdkObserver/'+n+'/'+n+'.csproj',n) for n in ('NumericLogger','ApiVerifier')]+[('DiagnosticPackage/DiagnosticPackage.csproj','DiagnosticPackage')]
    rows=['Microsoft Visual Studio Solution File, Format Version 12.00']
    for i,(path,name) in enumerate(projects,1):
        rows.extend(['Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "'+name+'", "'+path.replace('/','\\')+'", "{00000000-0000-0000-0000-'+str(i).zfill(12)+'}"','EndProject'])
    rows.extend(['Global','\tGlobalSection(SolutionConfigurationPlatforms) = preSolution','\t\tRelease|Any CPU = Release|Any CPU','\tEndGlobalSection','\tGlobalSection(ProjectConfigurationPlatforms) = postSolution'])
    for i in range(1,len(projects)+1):
        guid='{00000000-0000-0000-0000-'+str(i).zfill(12)+'}'
        rows.extend(['\t\t'+guid+'.Release|Any CPU.ActiveCfg = Release|Any CPU','\t\t'+guid+'.Release|Any CPU.Build.0 = Release|Any CPU'])
    rows.extend(['\tEndGlobalSection','EndGlobal'])
    (root/'Fixture.sln').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    # Numeric sidecar proves the actual SDK TargetPath property at GetTargetPath.
    targets=ET.Element('Project');t=ET.SubElement(targets,'Target',Name='OpenGeulTargetPath',AfterTargets='GetTargetPath',Condition="'$(ProbeOutput)' != '' And ('$(MSBuildProjectName)' == 'net_basetypes' Or '$(MSBuildProjectName)' == 'net_uretypes' Or '$(MSBuildProjectName)' == 'net_oootypes' Or '$(MSBuildProjectName)' == 'net_bridge')")
    g=ET.SubElement(t,'PropertyGroup');ET.SubElement(g,'OpenGeulPathMatch').text='0'
    ET.SubElement(g,'OpenGeulPathMatch',Condition="'$([System.IO.Path]::GetFullPath('$(TargetPath)'))' == '$([System.IO.Path]::GetFullPath('$(MSBuildProjectDirectory)/$(MSBuildProjectName).dll'))'").text='1'
    ET.SubElement(t,'WriteLinesToFile',File='$(ProbeOutput)/$(MSBuildProjectName).path',Lines='$(OpenGeulPathMatch)',Overwrite='true',Encoding='ASCII')
    (root/'GraphObserver.targets').write_bytes(ET.tostring(targets,encoding='utf-8'))
    return root

def pack_project(root):
    d=root/'DiagnosticPackage';d.mkdir()
    p=ET.Element('Project',Sdk='Microsoft.NET.Sdk');g=ET.SubElement(p,'PropertyGroup')
    for k,v in [('TargetFramework','netstandard2.0'),('PackageId','OpenGeul.Diagnostic.Only'),('Version','0.0.0-diagnostic'),('IncludeBuildOutput','false'),('EnableDefaultCompileItems','false')]:ET.SubElement(g,k).text=v
    items=ET.SubElement(p,'ItemGroup')
    for n in NAMES:ET.SubElement(items,'Content',Include=str(root/'DotnetLibrary'/n/(n+'.dll')),Pack='true',PackagePath='lib/$(TargetFramework)')
    q=d/'DiagnosticPackage.csproj';q.write_bytes(ET.tostring(p,encoding='utf-8'));return q
