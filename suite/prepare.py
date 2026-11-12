"""Pinned inputs and fresh-path extraction for the separate Office Suite package."""
from __future__ import annotations

import argparse
import configparser
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NATIVE_MACHINES = {'x64': 0x8664, 'arm64': 0xAA64}
try:
    from suite.crt import crt_names, is_vc_crt_file
except ModuleNotFoundError:
    from crt import crt_names, is_vc_crt_file

try:
    from suite.source_contracts import NEW, NEW_SOURCE, contract_for_source_pin, fallback_identity_expectation, new_source_only_expectations, source_companion_intent, source_twain_intent, dotnet_project_graph_expectation
except ModuleNotFoundError:
    from source_contracts import NEW, NEW_SOURCE, contract_for_source_pin, fallback_identity_expectation, new_source_only_expectations, source_companion_intent, source_twain_intent, dotnet_project_graph_expectation

# Compatibility name retains the existing public x64 family.
MSI_VC_DEPENDENCIES = frozenset(crt_names())


def native_machine(architecture: str) -> int:
    try:
        return NATIVE_MACHINES[architecture]
    except (KeyError, TypeError):
        raise ValueError('Unsupported native Suite architecture: '+str(architecture)) from None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
    return digest.hexdigest()


def check_asset(asset: dict, path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
            or getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValueError('Input must be a regular file without reparse points')
    if path.stat().st_size != asset['size'] or sha256(path) != asset['sha256']:
        raise ValueError('Locked input size/SHA256 does not match: ' + path.name)


def download_locked(asset: dict, destination: Path) -> Path:
    url = asset.get('url', '')
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
        or type(asset.get('size')) is not int or asset['size'] <= 0
        or not re.fullmatch(r'[0-9a-f]{64}', asset.get('sha256', ''))):
        raise ValueError('A complete HTTPS input size/SHA256 lock is required')
    if destination.exists() or destination.is_symlink():
        check_asset(asset, destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.partial')
    if temporary.exists() or temporary.is_symlink(): raise ValueError('Partial input already exists')
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'OpenGeul-Office-build/0.1'})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open('xb') as stream:
            if urllib.parse.urlsplit(response.url).scheme != 'https':
                raise ValueError('Input redirected to an insecure URL')
            size = 0
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                size += len(chunk)
                if size > asset['size']: raise ValueError('Download exceeds locked size')
                stream.write(chunk)
        check_asset(asset, temporary)
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def archive_path(name: str) -> str:
    name = name[:-1] if name.endswith('/') else name
    parts = name.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$', *(f'COM{i}' for i in '123456789¹²³'),
                *(f'LPT{i}' for i in '123456789¹²³')}
    if (not name or any(c in name for c in '\\:<>"|?*\x00')
        or PurePosixPath(name).is_absolute() or any(ord(c) < 32 for c in name)
        or any(p in ('', '.', '..') or p.endswith((' ', '.'))
               or p.split('.')[0].rstrip(' ').upper() in reserved for p in parts)):
        raise ValueError('Unsafe archive path: ' + repr(name))
    return name


def _source_build_target(architecture: str) -> dict:
    """Select reviewed policy from fixed tracked bytes, never from a receipt."""
    if not isinstance(architecture,str) or architecture not in NATIVE_MACHINES:
        raise ValueError('Unsupported native source-build architecture')
    folder = Path(__file__).resolve().parent/'engine-build'
    descriptor = dict(filename='native-targets.json', size=1987,
        sha256='ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc')
    check_asset(descriptor, folder/'native-targets.json')
    try:
        from suite.payload import _json_bytes
    except ModuleNotFoundError:
        from payload import _json_bytes
    policy = _json_bytes((folder/'native-targets.json').read_bytes(), 'native target policy')
    manifest = _json_bytes((folder/'source-build.json').read_bytes(), 'native source manifest')
    if (type(policy.get('schemaVersion')) is not int or policy['schemaVersion'] != 1
            or set(policy.get('targets', {})) != {'arm64', 'x64'}
            or manifest.get('nativeTargets') != descriptor):
        raise ValueError('Native source target policy differs from reviewed inputs')
    return policy['targets'][architecture]


def _source_digest(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _source_positive(value) -> bool:
    return type(value) is int and value > 0


def _source_windows_path(value) -> PureWindowsPath:
    if (not isinstance(value, str) or not re.match(r'^[A-Za-z]:[\\/]', value)
            or any(ord(char) < 32 for char in value) or any(part in ('.', '..') for part in re.split(r'[\\/]', value))):
        raise ValueError('Source proof requires an absolute unambiguous Windows path')
    return PureWindowsPath(value)


def _source_file_identity(record, *, machine=None, role=None) -> None:
    if (not isinstance(record, dict) or not _source_positive(record.get('size'))
            or not _source_digest(record.get('sha256'))):
        raise ValueError('Source proof file size/hash identity is incomplete')
    _source_windows_path(record.get('path'))
    if machine is not None and (type(record.get('machine')) is not int or record['machine'] != machine):
        raise ValueError('Source proof native file machine differs')
    if role is not None and record.get('role') != role:
        raise ValueError('Source proof file role differs')


def _source_version(value, major=None) -> tuple:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2,3}', value):
        raise ValueError('Native toolchain version is invalid')
    parts=tuple(map(int,value.split('.')))
    parts=parts+(0,)*(4-len(parts))
    if major is not None and parts[0] != major:
        raise ValueError('Native toolchain version profile differs')
    return parts


def _source_exact(actual, expected) -> bool:
    if type(actual) is not type(expected): return False
    if isinstance(expected,dict):
        return actual.keys() == expected.keys() and all(_source_exact(actual[key],value) for key,value in expected.items())
    if isinstance(expected,list):
        return len(actual) == len(expected) and all(_source_exact(a,b) for a,b in zip(actual,expected))
    return actual == expected


def _source_x64_preflight(proof: dict) -> None:
    preflight=proof.get('nativePreflight'); configured=proof.get('configuredToolchain')
    if (not isinstance(preflight,dict) or type(preflight.get('schemaVersion')) is not int
            or preflight['schemaVersion'] != 1 or preflight.get('passed') is not True
            or preflight.get('architecture') != 'x64' or not isinstance(configured,dict)
            or configured.get('matched') is not True or configured.get('toolset') != 'v143'):
        raise ValueError('x64 source build lacks native toolchain preflight/configuration binding')
    compiler=preflight.get('compiler');sdk=preflight.get('sdk')
    if (not isinstance(compiler,dict) or compiler.get('architecture') != 'x64'
            or compiler.get('compilerYear') != '2022' or compiler.get('toolset') != 'v143'
            or not isinstance(sdk,dict) or sdk.get('architecture') != 'x64'):
        raise ValueError('x64 source build requires the reviewed VS2022 native profile')
    _source_version(compiler.get('installationVersion'),17)
    root=_source_windows_path(compiler.get('compilerRoot'))
    installation=_source_windows_path(compiler.get('installationPath'))
    directory=_source_version(compiler.get('compilerToolsVersion'),14)
    if root != installation/'VC/Tools/MSVC'/compiler['compilerToolsVersion']:
        raise ValueError('Selected native compiler root differs from installation/version')
    metadata=compiler.get('toolsetMetadata')
    if (compiler.get('runtimeFloorBasis') != 'selected-msvc-package-v1'
            or not isinstance(metadata,dict) or set(metadata) != {'path','size','sha256','version'}):
        raise ValueError('Native runtime floor lacks selected MSVC package metadata')
    _source_file_identity(metadata)
    if (metadata['size'] > 4096 or metadata.get('version') != compiler['compilerToolsVersion']
            or _source_windows_path(metadata['path']) != installation/'VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt'
            or compiler.get('minimumRuntimeVersion') != '.'.join(map(str,directory))):
        raise ValueError('Native runtime package floor differs from selected default-tools metadata')
    tools=compiler.get('tools')
    if not isinstance(tools,dict) or set(tools) != {'cl','link','lib'}:
        raise ValueError('Native compiler tool family is incomplete')
    # Tool servicing resources retain their own family/native witnesses;
    # they are not relabelled as CRT package versions.
    for name,item in tools.items():
        _source_file_identity(item,machine=0x8664,role='nativeCompilerTool')
        version=_source_version(item.get('version'),19 if name=='cl' else 14)
        if (item.get('tool') != name or _source_windows_path(item['path']) != root/('bin/Hostx64/x64/'+name+'.exe')
                or version[1] != directory[1] or version[2] < directory[2]):
            raise ValueError('Native compiler tool path/resource version differs')
    sdk_root=_source_windows_path(sdk.get('root'));sdk_version=sdk.get('version')
    if (not isinstance(sdk_version,str) or not re.fullmatch(r'10\.0\.[0-9]+\.0',sdk_version)
            or _source_version(sdk_version) < (10,0,20348,0)):
        raise ValueError('Native SDK version differs from the source-supported profile')
    expected={sdk_root/relative for relative in
        (f'Include/{sdk_version}/um/Windows.h',f'Include/{sdk_version}/shared/sdkddkver.h',
         f'Include/{sdk_version}/ucrt/stdio.h',f'Lib/{sdk_version}/um/x64/kernel32.lib',
         f'Lib/{sdk_version}/ucrt/x64/ucrt.lib')}
    files=sdk.get('files')
    if not isinstance(files,list) or len(files) != 5:
        raise ValueError('Native SDK input family is incomplete')
    for item in files:_source_file_identity(item)
    if {_source_windows_path(item['path']) for item in files} != expected:
        raise ValueError('Native SDK input paths differ')
    resource=sdk.get('resourceCompiler');_source_file_identity(resource,machine=0x8664,role='nativeX64')
    if _source_windows_path(resource['path']) != sdk_root/f'bin/{sdk_version}/x64/rc.exe':
        raise ValueError('Native resource compiler differs from selected SDK')
    if (_source_windows_path(configured.get('compilerRoot')) != root
            or _source_windows_path(configured.get('sdkRoot')) != sdk_root
            or configured.get('sdkVersion') != sdk_version):
        raise ValueError('Configured native toolchain differs from actual preflight')
    config=proof['configuration']
    if config.get('VCTOOLSET') != 'v143' or config.get('VCVER') not in ('17.0','17.14'):
        raise ValueError('Generated native configuration differs from fixed compiler profile')
    # COMPATH/CC and SDK values in config_host.mk can be Cygwin/short paths.
    # The producer resolves those against this canonical independent binding.
    archive=preflight.get('archive');_source_file_identity(archive)
    if archive.get('machines') != [0x8664] or any(type(value) is not int for value in archive['machines']):
        raise ValueError('Native archive probe contains foreign COFF members')
    _source_file_identity(preflight.get('executable'),machine=0x8664,role='nativeX64')
    process=preflight.get('nativeProcess')
    cl=_source_version(tools['cl']['version'])
    if (not isinstance(process,dict) or type(process.get('processMachine')) is not int or process['processMachine'] != 0
            or type(process.get('nativeMachine')) is not int or process['nativeMachine'] != 0x8664
            or type(process.get('libraryValue')) is not int or process['libraryValue'] != 42
            or type(process.get('compilerFullVersion')) is not int
            or process['compilerFullVersion'] != cl[0]*10000000+cl[1]*100000+cl[2]):
        raise ValueError('Native compile/archive/link/run witness differs from selected compiler')
    commands=preflight.get('commands')
    if not isinstance(commands,dict) or set(commands) != {'member','probe','archive','link','run'}:
        raise ValueError('Native command proof is incomplete')
    for item in commands.values():
        if not isinstance(item,dict) or type(item.get('exitCode')) is not int or item['exitCode'] != 0:
            raise ValueError('Native preflight command did not succeed')
        for key in ('receipt','stdout','stderr'):_source_windows_path(item.get(key))


def _source_x64_prerequisites(proof: dict) -> None:
    """Replay retained native Java witnesses and the original workflow deadline."""
    java=proof.get('javaTools');jdk=java.get('jdk') if isinstance(java,dict) else None
    if (not isinstance(jdk,dict) or not _source_digest(jdk.get('releaseSha256'))
            or not isinstance(jdk.get('javaVersion'),str) or not re.fullmatch(r'[0-9]+[^\r\n\x00]*',jdk['javaVersion'])
            or int(re.match(r'[0-9]+',jdk['javaVersion'])[0]) < 8
            or jdk.get('selection') not in ('explicit','JAVA_HOME_21_X64')):
        raise ValueError('x64 source build lacks actual installed native Java prerequisites')
    home=_source_windows_path(jdk.get('home'))
    native=jdk.get('nativeFiles');libraries=jdk.get('importLibraries')
    if not isinstance(native,list) or len(native) != 4 or not isinstance(libraries,list) or len(libraries) != 2:
        raise ValueError('Native JDK/JNI input family is incomplete')
    for item in native:_source_file_identity(item,machine=0x8664,role='nativeX64')
    for item in libraries:
        _source_file_identity(item)
        if item.get('machines') != [0x8664] or any(type(value) is not int for value in item['machines']):
            raise ValueError('JNI import library contains a foreign COFF member')
    if ({_source_windows_path(item['path']) for item in native} !=
            {home/name for name in ('bin/java.exe','bin/javac.exe','bin/server/jvm.dll','bin/jawt.dll')}
            or {_source_windows_path(item['path']) for item in libraries} != {home/'lib/jvm.lib',home/'lib/jawt.lib'}):
        raise ValueError('Native JDK/JNI paths differ from the selected installation')
    budget=proof.get('buildBudget')
    if (not isinstance(budget,dict) or type(budget.get('maximumMinutes')) not in (int,float)
            or budget['maximumMinutes'] != 330 or type(budget.get('timeoutMilliseconds')) is not int
            or not 0 < budget['timeoutMilliseconds'] <= 330*60_000
            or type(budget.get('elapsedSeconds')) not in (int,float)
            or not math.isfinite(budget['elapsedSeconds']) or not 0 <= budget['elapsedSeconds']*1000 <= budget['timeoutMilliseconds']):
        raise ValueError('x64 source build exceeded or reset its original absolute budget')
    def stamp(value):
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{7}Z',value):
            raise ValueError('Native source budget timestamp is not an invariant UTC roundtrip')
        return datetime.fromisoformat(value)
    started,deadline,workflow=map(stamp,(budget.get('startedUtc'),budget.get('deadlineUtc'),budget.get('workflowDeadlineUtc')))
    finished=proof.get('finishedUtc');stamp(finished)
    if (not 0 < (deadline-started).total_seconds()*1000 <= budget['timeoutMilliseconds']+1
            # Fixed UTC roundtrip strings preserve the seventh fractional digit
            # that Python datetime truncates to microseconds.
            or budget['deadlineUtc'] > budget['workflowDeadlineUtc']
            or not budget['startedUtc'] <= finished <= budget['deadlineUtc']):
        raise ValueError('Native source receipt finished outside its original workflow deadline')


def _source_x64_atl_pins(manifest: dict) -> list:
    descriptor=manifest.get('windowsAtlNativePaths')
    paths=('extensions/Library_so_activex.mk','embedserv/Library_emser.mk',
        'extensions/Library_oleautobridge.mk','winaccessibility/Library_uacccom.mk',
        'winaccessibility/Library_winaccessibility.mk','winaccessibility/WinResTarget_uacccom.mk')
    if (type(descriptor) is not dict or set(descriptor)!={'condition','recipes'}
            or descriptor['condition']!='WNT_X86_64_MSC && MAKE_HOST=%-cygwin'
            or type(descriptor['recipes']) is not list or len(descriptor['recipes'])!=6):
        raise ValueError('x64 ATL source plan descriptor differs')
    originals={row['path']:row for row in
        manifest['atlConsumerNativePaths']['recipes']+[manifest['atlNativePaths']['recipe']]}
    for path,row in zip(paths,descriptor['recipes']):
        if (type(row) is not dict or set(row)!={'path','size','sha256','afterSize','afterSha256'}
                or row['path']!=path or path not in originals
                or any(type(row[key]) is not int or not 0<row[key]<=1024*1024 for key in ('size','afterSize'))
                or any(not _source_digest(row[key]) for key in ('sha256','afterSha256'))
                or not _source_exact({key:row[key] for key in ('size','sha256')},
                    {key:originals[path][key] for key in ('size','sha256')})):
            raise ValueError('x64 ATL source plan pins or ordered ARM originals differ')
    return descriptor['recipes']


def _source_x64_atl_inputs(proof: dict) -> None:
    value=proof.get('atlBuildInputs')
    fields={'schemaVersion','kind','passed','compilerRoot','configuredInclude','configuredLibrary',
        'includeRoot','libraryRoot','header','library','productPayload','fullEngineQualified','acceptanceEligible','guiVerified'}
    if (type(value) is not dict or set(value)!=fields
            or type(value['schemaVersion']) is not int or value['schemaVersion']!=1
            or value['kind']!='native-x64-atl-prerequisite' or value['passed'] is not True
            or any(value[key] is not False for key in ('productPayload','fullEngineQualified','acceptanceEligible','guiVerified'))):
        raise ValueError('x64 ATL prerequisite is missing or grants an unsupported qualification')
    def safe(path):
        result=_source_windows_path(path);archive_path('/'.join(result.parts[1:]));return result
    root=safe(value['compilerRoot'])
    if (root!=safe(proof['nativePreflight']['compiler']['compilerRoot'])
            or root!=safe(proof['configuredToolchain']['compilerRoot'])
            or safe(value['includeRoot'])!=root/'atlmfc/include'
            or safe(value['libraryRoot']) not in (root/'atlmfc/lib/x64',root/'atlmfc/lib/spectre/x64')):
        raise ValueError('x64 ATL canonical roots differ from the selected compiler')
    for field,key in (('configuredInclude','ATL_INCLUDE'),('configuredLibrary','ATL_LIB')):
        alias=value[field]
        if (type(alias) is not str or not alias.strip() or any(ord(char)<32 for char in alias)
                or not _source_exact(alias,proof['configuration'].get(key))):
            raise ValueError('x64 ATL configured alias differs from actual configuration')
    generation={'volumeSerialNumber','fileIndexHigh','fileIndexLow','creationHigh','creationLow','writeHigh','writeLow'}
    for field,parent,leaf in (('header','includeRoot','atlbase.h'),('library','libraryRoot','atls.lib')):
        record=value[field]
        if (type(record) is not dict or set(record)!={'path','size','sha256','generation'}
                or type(record['size']) is not int or not 0<record['size']<=1024*1024*1024
                or not _source_digest(record['sha256'])
                or safe(record['path'])!=safe(value[parent])/leaf):
            raise ValueError('x64 ATL selected header/library identity differs')
        stamp=record['generation']
        if (type(stamp) is not dict or set(stamp)!=generation
                or any(type(number) is not int or not 0<=number<=0xffffffff for number in stamp.values())
                or not (stamp['fileIndexHigh'] or stamp['fileIndexLow'])):
            raise ValueError('x64 ATL selected file generation is incomplete')


def _source_x64_harfbuzz_pin(manifest: dict) -> dict:
    pin=manifest.get('windowsHarfbuzzNativeMesonPaths')
    if (type(pin) is not dict or set(pin)!={'path','size','sha256','afterSize','afterSha256','condition'}
            or pin['path']!='external/harfbuzz/ExternalProject_harfbuzz.mk'
            or pin['condition']!='WNT_X86_64_MSC_WNT && MAKE_HOST=%-cygwin'
            or any(type(pin[key]) is not int or not 0<pin[key]<=1024*1024 for key in ('size','afterSize'))
            or any(not _source_digest(pin[key]) for key in ('sha256','afterSha256'))
            or not _source_exact({key:pin[key] for key in ('path','size','sha256')},
                {key:manifest['harfbuzzNativeMesonPaths']['recipe'][key] for key in ('path','size','sha256')})):
        raise ValueError('x64 HarfBuzz source plan pin, profile or ARM original differs')
    return pin


def _source_x64_plan(manifest: dict) -> dict:
    """Independently reconstruct the finite source plan from reviewed metadata."""
    def pin(value, after=None):
        row=dict(path=archive_path(value['path']),beforeSha256=value['sha256'],
                 afterSha256=value['afterSha256'] if after is None else after)
        if not _source_digest(row['beforeSha256']) or not _source_digest(row['afterSha256']):
            raise ValueError('x64 source plan requires exact source hashes')
        for source,target in (('size','beforeBytes'),('afterSize','afterBytes')):
            if source in value:
                if not _source_positive(value[source]) or value[source] > 1024*1024:
                    raise ValueError('x64 source plan byte bounds differ')
                row[target]=value[source]
        return row
    loader=manifest.get('windowsFirebirdLoaderPath')
    if (not isinstance(loader,dict) or set(loader) != {'path','size','sha256','afterSize','afterSha256','condition'}
            or loader.get('condition') != 'WNT_X86_64'
            or loader.get('path') != 'external/firebird/ExternalProject_firebird.mk'):
        raise ValueError('x64 Firebird loader plan has an unknown source or condition')
    zstd=manifest.get('windowsZstdSourceLinks')
    if (not isinstance(zstd,dict) or set(zstd) != {'path','size','sha256','afterSize','afterSha256','condition'}
            or zstd.get('condition') != 'WNT_X86_64'
            or zstd.get('path') != 'external/zstd/UnpackedTarball_zstd.mk'
            or zstd.get('sha256') != manifest['zstdSourceLinks']['sha256']):
        raise ValueError('x64 zstd source-link plan has an unknown source or condition')
    gpg=manifest.get('windowsGpgBuildCompilerPath')
    if (not isinstance(gpg,dict) or set(gpg) != {'path','size','sha256','afterSize','afterSha256','condition'}
            or gpg.get('condition') != 'WNT_X86_64 && BUILD_PLATFORM=%cygwin'
            or gpg.get('path') != 'solenv/gbuild/platform/com_MSC_defs.mk'):
        raise ValueError('x64 GPG compiler-path plan has an unknown source or condition')
    winacc=manifest['winAccFocusOrder']
    common=[pin(manifest['moduleBootstrap'])]
    for source in winacc['sources']:
        common.append(pin(source,winacc['afterSha256'] if source['path']==winacc['path'] else source['sha256']))
    if (len(common) != 4 or common[1]['path'] != winacc['path']
            or common[1]['beforeSha256'] != winacc['sha256'] or common[1].get('beforeBytes') != winacc['beforeBytes']):
        raise ValueError('x64 WinAcc common source-plan identity differs')
    atl=_source_x64_atl_pins(manifest)
    common[1]['afterBytes']=winacc['afterBytes'];common.extend((pin(loader),pin(zstd),pin(gpg)))
    common.extend(pin(row) for row in atl)
    harfbuzz=_source_x64_harfbuzz_pin(manifest);common.append(pin(harfbuzz))
    guarded=[manifest[key] for key in ('configureSource','sourceHook','icuBuildPath','zstdSourceLinks')]
    guarded += [manifest[key]['recipe'] for key in ('mddsEquality','pythonNativeHost','atlNativePaths')]
    guarded += manifest['atlConsumerNativePaths']['recipes']+[manifest['harfbuzzNativeMesonPaths']['recipe']]
    moved={loader['path'],zstd['path'],harfbuzz['path'],*(row['path'] for row in atl)}
    guarded=[pin(source) for source in guarded if source['path'] not in moved]
    payload=winacc['patch'];payload_pin=dict(filename=payload['filename'],sha256=payload['sha256'])
    if 'size' in payload:payload_pin['size']=payload['size']
    plan=dict(recipeId='windows-x64-common-v2',recipe=manifest['nativeSourceRecipes']['windows-x64-common-v2'],
        sources=common+guarded,armGuardedSources=guarded,sourceDependencies=[],payloads=[payload_pin])
    digest=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    if digest != 'cc8aa7c7aed29a5a8708e2aa860b7573a176419e71c05893e60045e8c27a55c6':
        raise ValueError('x64 source plan differs from the reviewed canonical recipe')
    return plan


def _source_x64_loader_evidence(value) -> None:
    if not isinstance(value,dict) or set(value) != {'original','effective'}:
        raise ValueError('x64 Firebird loader evidence descriptors are incomplete')
    paths={}
    for name in ('original','effective'):
        path=_source_windows_path(value[name])
        archive_path('/'.join(path.parts[1:]))
        if path.name != name+'-x64-ExternalProject_firebird.mk':
            raise ValueError('x64 Firebird loader evidence basename differs')
        paths[name]=path
    if paths['original'].parent != paths['effective'].parent or not paths['original'].parent.name:
        raise ValueError('x64 Firebird loader evidence must share one producer directory descriptor')


def _source_x64_zstd_evidence(value) -> None:
    if not isinstance(value,dict) or set(value) != {'original','effective'}:
        raise ValueError('x64 zstd source-link evidence descriptors are incomplete')
    paths={}
    for name in ('original','effective'):
        path=_source_windows_path(value[name])
        archive_path('/'.join(path.parts[1:]))
        if path.name != name+'-x64-UnpackedTarball_zstd.mk':
            raise ValueError('x64 zstd source-link evidence basename differs')
        paths[name]=path
    if paths['original'].parent != paths['effective'].parent or not paths['original'].parent.name:
        raise ValueError('x64 zstd source-link evidence must share one producer directory descriptor')


def _source_x64_gpg_evidence(value) -> None:
    if not isinstance(value,dict) or set(value) != {'original','effective'}:
        raise ValueError('x64 GPG compiler-path evidence descriptors are incomplete')
    paths={}
    for name in ('original','effective'):
        path=_source_windows_path(value[name])
        archive_path('/'.join(path.parts[1:]))
        if path.name != name+'-x64-com_MSC_defs.mk':
            raise ValueError('x64 GPG compiler-path evidence basename differs')
        paths[name]=path
    if paths['original'].parent != paths['effective'].parent or not paths['original'].parent.name:
        raise ValueError('x64 GPG compiler-path evidence must share one producer directory descriptor')


def _source_x64_atl_source(value,manifest,*,evidence_parent: PureWindowsPath) -> None:
    fields=dict(schemaVersion=1,kind='windows-x64-native-atl-source-hooks',
        condition='WNT_X86_64_MSC && MAKE_HOST=%-cygwin',nativeBuildVerified=False,
        fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    if (type(value) is not dict or set(value)!=set(fields)|{'recipes'}
            or not _source_exact({key:value[key] for key in fields},fields)
            or type(value['recipes']) is not list or len(value['recipes'])!=6):
        raise ValueError('x64 ATL source hook group differs from the reviewed source-only contract')
    seen=set()
    for index,(pin,row) in enumerate(zip(_source_x64_atl_pins(manifest),value['recipes']),1):
        expected=dict(path=pin['path'],beforeBytes=pin['size'],afterBytes=pin['afterSize'],
            beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'])
        if (type(row) is not dict or set(row)!=set(expected)|{'evidence'}
                or not _source_exact({key:row[key] for key in expected},expected)
                or type(row['evidence']) is not dict or set(row['evidence'])!={'original','effective'}):
            raise ValueError('x64 ATL source recipe pins or evidence differ')
        for side in ('original','effective'):
            path=_source_windows_path(row['evidence'][side]);archive_path('/'.join(path.parts[1:]))
            name=side+'-x64-atl-'+format(index,'02d')+'-'+pin['path'].rsplit('/',1)[-1]
            if path.name!=name or path.parent!=evidence_parent or not path.parent.name or path in seen:
                raise ValueError('x64 ATL source evidence name, uniqueness or shared producer parent differs')
            seen.add(path)


def _source_x64_harfbuzz_source(value,manifest,*,evidence_parent: PureWindowsPath) -> None:
    pin=_source_x64_harfbuzz_pin(manifest)
    fields=dict(schemaVersion=1,kind='windows-x64-harfbuzz-native-meson-source-hook',
        path=pin['path'],condition=pin['condition'],beforeBytes=pin['size'],afterBytes=pin['afterSize'],
        beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],nativeBuildVerified=False,
        fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    if (type(value) is not dict or set(value)!=set(fields)|{'evidence'}
            or not _source_exact({key:value[key] for key in fields},fields)
            or type(value['evidence']) is not dict or set(value['evidence'])!={'original','effective'}):
        raise ValueError('x64 HarfBuzz source receipt differs from the reviewed source-only hook')
    for side in ('original','effective'):
        path=_source_windows_path(value['evidence'][side]);archive_path('/'.join(path.parts[1:]))
        if (path.name!=side+'-x64-ExternalProject_harfbuzz.mk'
                or path.parent!=evidence_parent or not path.parent.name):
            raise ValueError('x64 HarfBuzz evidence basename or shared loader parent differs')


def _source_new_dotnet_pins(manifest: dict) -> list:
    """Require the exact ordered source pair, never receipt-selected graph pins."""
    expected=dotnet_project_graph_expectation(dict(NEW_SOURCE))
    if (type(manifest) is not dict
            or not _source_exact(manifest.get('windowsDotnetProjectGraph'),expected)):
        raise ValueError('New .NET source graph descriptor differs from its reviewed core/pins')
    return [dict(row) for row in expected['sources']]


def _source_new_plan(manifest: dict, architecture: str) -> dict:
    """Reconstruct only the separate, reviewed 9dea source-only recipe."""
    expected=new_source_only_expectations(dict(NEW_SOURCE),architecture)
    def pin(value,after=None):
        result=dict(path=archive_path(value['path']),beforeSha256=value['sha256'],
            afterSha256=value['afterSha256'] if after is None else after)
        if any(not _source_digest(result[key]) for key in ('beforeSha256','afterSha256')):
            raise ValueError('New source recipe hash differs')
        for old,new in (('size','beforeBytes'),('afterSize','afterBytes')):
            if old in value:
                if not _source_positive(value[old]) or value[old]>1024*1024:
                    raise ValueError('New source recipe byte bound differs')
                result[new]=value[old]
        return result
    try:
        winacc=manifest['winAccFocusOrder'];common=[pin(manifest['moduleBootstrap'])]
        for value in winacc['sources']:
            common.append(pin(value,winacc['afterSha256'] if value['path']==winacc['path'] else value['sha256']))
        common[1]['afterBytes']=winacc['afterBytes'];common.append(pin(manifest['flexFatalCompatibility']))
        common.extend(pin(value) for value in _source_new_dotnet_pins(manifest))
        guarded=[manifest[key] for key in ('configureSource','sourceHook','icuBuildPath','zstdSourceLinks')]
        guarded += [manifest[key]['recipe'] for key in ('mddsEquality','pythonNativeHost','atlNativePaths')]
        guarded += manifest['atlConsumerNativePaths']['recipes']+[manifest['harfbuzzNativeMesonPaths']['recipe']]
        guarded=[pin(value) for value in guarded]
        if architecture=='x64':
            atl=_source_x64_atl_pins(manifest)
            common += [pin(manifest[key]) for key in ('windowsFirebirdLoaderPath','windowsZstdSourceLinks','windowsGpgBuildCompilerPath')]
            common += [pin(value) for value in atl]
            common += [pin(_source_x64_harfbuzz_pin(manifest)),pin(manifest['windowsCliPublisherPolicyPlatform'])]
            moved={manifest[key]['path'] for key in ('windowsFirebirdLoaderPath','windowsZstdSourceLinks','windowsHarfbuzzNativeMesonPaths')}
            moved.update(value['path'] for value in atl)
            guarded=[value for value in guarded if value['path'] not in moved]
        payloads=[('winacc-focus-order.patch',winacc['patch'])];dependencies=[]
        if architecture=='arm64':
            upstream=manifest['mddsEquality']['upstreamPatch']
            dependencies=[dict(path='external/mdds/'+upstream['filename'],beforeSha256=upstream['sha256'],afterSha256=upstream['sha256'])]
            payloads += [('firebird-windows-arm64.patch',manifest['portPatch']),
                ('libreoffice-enable-arm64-firebird.patch',manifest['configurePatch']),
                ('opengeul-arm64-equality.patch.1',manifest['mddsEquality']['patch']),
                ('opengeul-native-arm64-tools.targets',manifest['pythonNativeHost']['targets'])]
        selected=[]
        for name,value in payloads:
            if value['filename']!=name:raise ValueError('New source payload name differs')
            row=dict(filename=name,sha256=value['sha256'])
            if 'size' in value:row['size']=value['size']
            selected.append(row)
        recipe_id=expected.recipe_fields['recipeId']
        plan=dict(recipeId=recipe_id,recipe=manifest['nativeSourceRecipes'][recipe_id],sources=common+guarded,
            armGuardedSources=guarded,sourceDependencies=dependencies,payloads=selected)
        digest=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
        if digest!=expected.recipe_fields['recipeSha256']:
            raise ValueError('New source plan differs from its reviewed architecture recipe')
        return plan
    except (KeyError,TypeError,IndexError,AttributeError) as error:
        raise ValueError('New source plan is malformed') from error


def _source_new_evidence(value, names: dict, *, parent: PureWindowsPath | None = None) -> PureWindowsPath:
    """Validate producer-side descriptors only; raw sources are not ZIP members."""
    if type(value) is not dict or set(value)!=set(names):
        raise ValueError('New source retained evidence fields differ')
    for field,name in names.items():
        path=_source_windows_path(value[field])
        archive_path('/'.join(path.parts[1:]))
        if str(path)!=value[field] or path.name!=name or not path.parent.name:
            raise ValueError('New source evidence descriptor is not canonical')
        if parent is None:parent=path.parent
        if str(path.parent)!=str(parent):
            raise ValueError('New source evidence descriptors belong to different runs')
    return parent


def _source_new_dotnet_hook(value,manifest,architecture,*,parent: PureWindowsPath) -> None:
    """Source-only graph evidence shares the already retained producer parent."""
    if type(architecture) is not str or architecture not in ('arm64','x64'):
        raise ValueError('New .NET source graph architecture differs')
    pins=_source_new_dotnet_pins(manifest)
    fields=dict(schemaVersion=1,kind='windows-dotnet-project-graph-source-hook',
        coreCommit=NEW.core,architecture=architecture,nativeBuildVerified=False,
        fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    if (type(value) is not dict or set(value)!=set(fields)|{'sources'}
            or not _source_exact({key:value[key] for key in fields},fields)
            or type(value['sources']) is not list or len(value['sources'])!=len(pins)):
        raise ValueError('New .NET source graph hook/source-only fields differ')
    for row,pin in zip(value['sources'],pins):
        expected=dict(path=pin['path'],beforeBytes=pin['size'],afterBytes=pin['afterSize'],
            beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'])
        if (type(row) is not dict or set(row)!=set(expected)|{'evidence'}
                or not _source_exact({key:row[key] for key in expected},expected)):
            raise ValueError('New .NET source graph ordered recipe pins differ')
        name=pin['path'].rsplit('/',1)[-1]
        _source_new_evidence(row['evidence'],{side:side+'-'+name for side in ('original','effective')},parent=parent)


def _source_new_arm_hooks(hooks: dict, manifest: dict, parent: PureWindowsPath) -> None:
    """Replay the actual ARM producer's closed hook fields and retained paths."""
    fields=dict(schemaVersion=1,status='source-hook-installed-native-build-pending',architecture='arm64',
        libreofficeVersion=NEW.version,firebirdVersion=NEW.firebird_version,
        sourceHook=manifest['sourceHook']['path'],beforeSha256=manifest['sourceHook']['sha256'],afterSha256=manifest['sourceHook']['afterSha256'],
        portPatchSha256=manifest['portPatch']['sha256'],configurePatchSha256=manifest['configurePatch']['sha256'],
        configureBeforeSha256=manifest['configureSource']['sha256'],configureAfterSha256=manifest['configureSource']['afterSha256'],
        nativeBuildVerified=False,basePersistenceVerified=False)
    names=('icuBuildPath','zstdSourceLinks','mddsEquality','pythonNativeHost','atlNativePaths','atlConsumerNativePaths','harfbuzzNativeMesonPaths')
    if (set(hooks)!=set(fields)|{'moduleBootstrap','dotnetProjectGraph',*names}
            or not _source_exact({key:hooks[key] for key in fields},fields)):
        raise ValueError('New ARM source hook group/pinned source identities differ')
    for field in names:
        if field=='atlConsumerNativePaths':continue
        config=manifest[field];pin=config.get('recipe',config);value=hooks[field]
        expected=dict(path=pin['path'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'])
        if 'scope' in config:expected['scope']=config['scope']
        if field=='zstdSourceLinks':expected['archive']=config['archive']
        if field=='mddsEquality':expected.update(patchSha256=config['patch']['sha256'],upstreamPatchSha256=config['upstreamPatch']['sha256'])
        evidence_names={side:side+'-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')}
        if field=='pythonNativeHost':
            if type(value) is not dict:raise ValueError('New ARM Python source hook differs')
            path=_source_windows_path(value.get('targetsPath'))
            archive_path('/'.join(path.parts[1:]))
            if (str(path)!=value['targetsPath'] or tuple(path.parts[-3:])!=('external','python3','opengeul-native-arm64-tools.targets')
                    or len(path.parts)<5):
                raise ValueError('New ARM generated Python target descriptor differs')
            source_root=path.parents[2]
            if source_root==parent or source_root in parent.parents or parent in source_root.parents:
                raise ValueError('New ARM generated source and retained evidence roots overlap')
            expected.update(targetsSha256=config['targets']['sha256'],targetsPath=value['targetsPath'])
            evidence_names['targets']='effective-opengeul-native-arm64-tools.targets'
        if (type(value) is not dict or set(value)!=set(expected)|{'evidence'}
                or not _source_exact({key:value[key] for key in expected},expected)):
            raise ValueError('New ARM source hook pinned metadata differs')
        _source_new_evidence(value['evidence'],evidence_names,parent=parent)
    value=hooks['atlConsumerNativePaths'];config=manifest['atlConsumerNativePaths']
    if (type(value) is not dict or set(value)!={'scope','recipes'}
            or not _source_exact(value['scope'],config['scope']) or type(value['recipes']) is not list
            or len(value['recipes'])!=len(config['recipes'])):
        raise ValueError('New ARM ATL consumer group differs')
    for row,pin in zip(value['recipes'],config['recipes']):
        expected=dict(path=pin['path'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'])
        if (type(row) is not dict or set(row)!=set(expected)|{'evidence'}
                or not _source_exact({key:row[key] for key in expected},expected)):
            raise ValueError('New ARM ATL consumer recipe order/identity differs')
        _source_new_evidence(row['evidence'],{side:side+'-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')},parent=parent)


def _source_new_recipe(proof: dict, architecture: str) -> None:
    """Source-only recipe/WinAcc/Flex replay; never a normal Full qualification."""
    try:
        if type(proof) is not dict or contract_for_source_pin(proof.get('sourcePin')) is not NEW:
            raise ValueError('New source recipe requires the exact reviewed core/archive tuple')
        expected=new_source_only_expectations(proof['sourcePin'],architecture)
        path=Path(__file__).resolve().parent/'engine-build/source-build.26.8.2.2.json'
        info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or getattr(info,'st_file_attributes',0)&0x400
                or not 0<info.st_size<=1024*1024):
            raise ValueError('New source manifest must be a bounded unaliased snapshot')
        raw=path.read_bytes()
        if (hashlib.sha256(raw).hexdigest()!=expected.source_manifest_sha256
                or proof.get('sourcePortManifestSha256')!=expected.source_manifest_sha256
                or proof.get('nativeTargetsSha256')!=expected.native_targets_sha256):
            raise ValueError('New source manifest/policy differs from its separate reviewed profile')
        manifest=json.loads(raw);plan=_source_new_plan(manifest,architecture)
        recipe=dict(expected.recipe_fields);recipe['hookOrder']=list(expected.hooks)
        recipe['armGuardedSources']=[dict(path=row['path'],beforeSha256=row['beforeSha256'],
            sha256=row['beforeSha256'] if architecture=='x64' else row['afterSha256'],unchanged=architecture=='x64')
            for row in plan['armGuardedSources']]
        if not _source_exact(proof.get('sourceRecipeProof'),recipe):
            raise ValueError('New source recipe/guard identities or typed false flags differ')
        hooks=proof.get('sourceHooks');bootstrap=manifest['moduleBootstrap']
        fields=dict(path=bootstrap['path'],beforeSha256=bootstrap['sha256'],afterSha256=bootstrap['afterSha256'])
        if (type(hooks) is not dict or hooks.get('architecture')!=architecture
                or hooks.get('nativeBuildVerified') is not False or hooks.get('basePersistenceVerified') is not False
                or type(hooks.get('moduleBootstrap')) is not dict
                or set(hooks['moduleBootstrap'])!=set(fields)|{'evidence'}
                or not _source_exact({key:hooks['moduleBootstrap'][key] for key in fields},fields)):
            raise ValueError('New source bootstrap identity/source-only context differs')
        parent=_source_new_evidence(hooks['moduleBootstrap']['evidence'],
            dict(original='original-unpack-sources',effective='effective-unpack-sources'))
        pin=manifest['winAccFocusOrder'];patch=proof.get('winAccFocusOrderSourcePatch');fields=dict(expected.winacc_fields)
        fields['sourceFiles']=[dict(path=row['path'],beforeBytes=row['size'],
            afterBytes=pin['afterBytes'] if row['path']==pin['path'] else row['size'],beforeSha256=row['sha256'],
            afterSha256=pin['afterSha256'] if row['path']==pin['path'] else row['sha256']) for row in pin['sources']]
        if (type(patch) is not dict or set(patch)!=set(fields)|{'evidence'}
                or not _source_exact({key:patch[key] for key in fields},fields)):
            raise ValueError('New WinAcc source-only proof differs')
        _source_new_evidence(patch['evidence'],dict(original='original-AccObjectWinManager.cxx',
            effective='effective-AccObjectWinManager.cxx',patch='winacc-focus-order.patch'),parent=parent)
        flex=proof.get('flexFatalCompatibilitySourcePatch');fields=dict(expected.flex_fields)
        if (type(flex) is not dict or set(flex)!=set(fields)|{'evidence'}
                or not _source_exact({key:flex[key] for key in fields},fields)):
            raise ValueError('New Flex source-only proof differs')
        _source_new_evidence(flex['evidence'],{side:side+'-'+architecture+'-sqlflex.l' for side in ('original','effective')},parent=parent)
        _source_new_dotnet_hook(hooks.get('dotnetProjectGraph'),manifest,architecture,parent=parent)
        if architecture=='arm64':
            _source_new_arm_hooks(hooks,manifest,parent)
            return
        pairs=(('firebirdLoaderPath','windowsFirebirdLoaderPath','windows-firebird-loader-path-source-hook'),
            ('zstdSourceLinks','windowsZstdSourceLinks','windows-zstd-source-links-source-hook'),
            ('gpgBuildCompilerPath','windowsGpgBuildCompilerPath','windows-gpg-build-compiler-path-source-hook'),
            ('harfbuzzNativeMesonPaths','windowsHarfbuzzNativeMesonPaths','windows-x64-harfbuzz-native-meson-source-hook'),
            ('cliPublisherPolicyPlatform','windowsCliPublisherPolicyPlatform','windows-x64-cli-publisher-policy-platform-source-hook'))
        if (set(hooks)!={'kind','architecture','moduleBootstrap','atlNativePaths','dotnetProjectGraph','nativeBuildVerified','basePersistenceVerified',*(row[0] for row in pairs)}
                or hooks.get('kind')!='native-windows-common-source-hooks'):
            raise ValueError('New x64 common hook group differs')
        for field,pin_name,kind in pairs:
            pin=manifest[pin_name];value=hooks[field]
            fields=dict(schemaVersion=1,kind=kind,path=pin['path'],condition=pin['condition'],
                beforeBytes=pin['size'],afterBytes=pin['afterSize'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
                nativeBuildVerified=False,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
            if (type(value) is not dict or set(value)!=set(fields)|{'evidence'}
                    or not _source_exact({key:value[key] for key in fields},fields)):
                raise ValueError('New x64 source-only hook differs')
            _source_new_evidence(value['evidence'],{side:side+'-x64-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')},parent=parent)
        _source_x64_atl_source(hooks['atlNativePaths'],manifest,evidence_parent=parent)
        for index,value in enumerate(hooks['atlNativePaths']['recipes'],1):
            pin=_source_x64_atl_pins(manifest)[index-1]
            _source_new_evidence(value['evidence'],{side:side+'-x64-atl-'+format(index,'02d')+'-'+pin['path'].rsplit('/',1)[-1] for side in ('original','effective')},parent=parent)
    except (KeyError,TypeError,IndexError,AttributeError,OSError) as error:
        raise ValueError('New source-only receipt is incomplete') from error


def _source_x64_recipe(proof: dict) -> None:
    folder=Path(__file__).resolve().parent/'engine-build'
    raw=(folder/'source-build.json').read_bytes();manifest=json.loads(raw)
    if proof.get('sourcePortManifestSha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('x64 source patch manifest differs from reviewed consumer metadata')
    plan=_source_x64_plan(manifest);recipe=proof.get('sourceRecipeProof')
    expected=dict(schemaVersion=1,kind='native-engine-source-recipe-install',architecture='x64',
        recipeId='windows-x64-common-v2',policySha256=proof['nativeTargetsSha256'],
        manifestSha256=proof['sourcePortManifestSha256'],
        recipeSha256='cc8aa7c7aed29a5a8708e2aa860b7573a176419e71c05893e60045e8c27a55c6',
        hookOrder=['moduleBootstrap','firebirdLoaderPath','zstdSourceLinks','gpgBuildCompilerPath','atlNativePaths','harfbuzzNativeMesonPaths','winAccFocusOrder'],nativeBuildVerified=False,
        fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    expected['armGuardedSources']=[dict(path=item['path'],beforeSha256=item['beforeSha256'],sha256=item['beforeSha256'],unchanged=True)
                                  for item in plan['armGuardedSources']]
    if not _source_exact(recipe, expected):
        raise ValueError('x64 source recipe or unchanged ARM-only source identities differ')
    pin=manifest['winAccFocusOrder'];patch=proof.get('winAccFocusOrderSourcePatch')
    source=proof.get('sourcePin');upstream=manifest['libreoffice']
    if (not isinstance(source,dict) or source.get('coreCommit') != pin['coreCommit']
            or any(source.get(key) != upstream[key] for key in ('url','sha256','version'))):
        raise ValueError('x64 source recipe differs from its authenticated upstream core/archive')
    fields=dict(schemaVersion=1,kind='winacc-focus-order-source-patch',passed=True,coreCommit=pin['coreCommit'],
        path=pin['path'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],patchSha256=pin['patch']['sha256'],
        nativeBuildVerified=False,guiVerified=False,currentCiRootCauseConfirmed=False)
    if (not isinstance(patch,dict) or any(patch.get(key) != value or type(patch.get(key)) is not type(value)
            for key,value in fields.items())):
        raise ValueError('x64 WinAcc source patch differs from reviewed recipe')
    files=[dict(path=item['path'],beforeBytes=item['size'],
        afterBytes=pin['afterBytes'] if item['path']==pin['path'] else item['size'],
        beforeSha256=item['sha256'],afterSha256=pin['afterSha256'] if item['path']==pin['path'] else item['sha256'])
        for item in pin['sources']]
    if not _source_exact(patch.get('sourceFiles'), files):
        raise ValueError('x64 WinAcc unchanged dependency/patch identities differ')
    hooks=proof.get('sourceHooks');bootstrap=manifest['moduleBootstrap']
    if (not isinstance(hooks,dict) or set(hooks) != {'kind','architecture','moduleBootstrap','firebirdLoaderPath','zstdSourceLinks','gpgBuildCompilerPath','atlNativePaths','harfbuzzNativeMesonPaths','nativeBuildVerified','basePersistenceVerified'}
            or hooks.get('kind') != 'native-windows-common-source-hooks' or hooks.get('architecture') != 'x64'
            or hooks.get('nativeBuildVerified') is not False or hooks.get('basePersistenceVerified') is not False
            or not isinstance(hooks.get('moduleBootstrap'),dict)
            or any(hooks['moduleBootstrap'].get(key) != value for key,value in
                dict(path=bootstrap['path'],beforeSha256=bootstrap['sha256'],afterSha256=bootstrap['afterSha256']).items())):
        raise ValueError('x64 source hook sequence differs from reviewed common hooks')
    loader=hooks.get('firebirdLoaderPath');pin=manifest['windowsFirebirdLoaderPath']
    fields=dict(schemaVersion=1,kind='windows-firebird-loader-path-source-hook',path=pin['path'],condition='WNT_X86_64',
        beforeBytes=pin['size'],afterBytes=pin['afterSize'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
        nativeBuildVerified=False,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    if (not isinstance(loader,dict) or set(loader) != set(fields)|{'evidence'}
            or not _source_exact({key:loader[key] for key in fields},fields)):
        raise ValueError('x64 Firebird loader source descriptor differs from the reviewed source-only hook')
    _source_x64_loader_evidence(loader['evidence'])
    zstd=hooks.get('zstdSourceLinks');pin=manifest['windowsZstdSourceLinks']
    fields=dict(schemaVersion=1,kind='windows-zstd-source-links-source-hook',path=pin['path'],condition='WNT_X86_64',
        beforeBytes=pin['size'],afterBytes=pin['afterSize'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
        nativeBuildVerified=False,fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    if (not isinstance(zstd,dict) or set(zstd) != set(fields)|{'evidence'}
            or not _source_exact({key:zstd[key] for key in fields},fields)):
        raise ValueError('x64 zstd source-link descriptor differs from the reviewed source-only hook')
    _source_x64_zstd_evidence(zstd['evidence'])
    gpg=hooks.get('gpgBuildCompilerPath');pin=manifest['windowsGpgBuildCompilerPath']
    fields=dict(schemaVersion=1,kind='windows-gpg-build-compiler-path-source-hook',path=pin['path'],
        condition='WNT_X86_64 && BUILD_PLATFORM=%cygwin',beforeBytes=pin['size'],afterBytes=pin['afterSize'],
        beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],nativeBuildVerified=False,
        fullEngineQualified=False,acceptanceEligible=False,guiVerified=False)
    if (not isinstance(gpg,dict) or set(gpg) != set(fields)|{'evidence'}
            or not _source_exact({key:gpg[key] for key in fields},fields)):
        raise ValueError('x64 GPG compiler-path descriptor differs from the reviewed source-only hook')
    _source_x64_gpg_evidence(gpg['evidence'])
    _source_x64_atl_source(hooks.get('atlNativePaths'),manifest,
        evidence_parent=_source_windows_path(loader['evidence']['original']).parent)
    _source_x64_harfbuzz_source(hooks.get('harfbuzzNativeMesonPaths'),manifest,
        evidence_parent=_source_windows_path(loader['evidence']['original']).parent)


def _source_x64_retirement(base: dict) -> None:
    rows=base.get('retirement');hosts=base['nativeProcesses'][1:]
    if not isinstance(rows,list) or len(rows) != 2:
        raise ValueError('x64 Base original process retirement is missing')
    for row,host in zip(rows,hosts):
        if not isinstance(row,dict) or row.get('phase') != host['phase'] or row.get('handlesClosed') is not True:
            raise ValueError('x64 Base retained handle retirement differs')
        cleanup=row.get('cleanup')
        if (not isinstance(cleanup,dict) or type(cleanup.get('schemaVersion')) is not int or cleanup['schemaVersion'] != 1
                or cleanup.get('kind') != 'owned-engine-job-cleanup' or cleanup.get('gracefulQualified') is not True
                or cleanup.get('forcedTermination') is not False or cleanup.get('jobEmptyVerified') is not True
                or cleanup.get('finalJobPids') != [] or cleanup.get('errors') != []
                or type(cleanup.get('launcherExitCode')) is not int or cleanup['launcherExitCode'] != 0
                or not _source_positive(cleanup.get('jobHandleValue'))
                or _source_windows_path(cleanup.get('expectedEngineImage')) != _source_windows_path(host['image'])):
            raise ValueError('x64 Base original owned job did not retire gracefully')
        initial=cleanup.get('initialMembers');final=cleanup.get('finalMembers')
        if not isinstance(initial,list) or not initial or not isinstance(final,list) or not final:
            raise ValueError('x64 Base retained original member handles are incomplete')
        final_identities=set()
        for member in final:
            if (not isinstance(member,dict) or any(not _source_positive(member.get(key)) for key in ('pid','creationTime','handleValue'))
                    or member.get('error') or member.get('alive') is not False
                    or type(member.get('exitCode')) is not int or member['exitCode'] != 0):
                raise ValueError('x64 Base discovered member exit is unverified')
            key=(member['pid'],member['creationTime'],member['handleValue'],_source_windows_path(member.get('image')))
            if key in final_identities:raise ValueError('x64 Base final member identity is duplicated')
            final_identities.add(key)
        identities=set();found=False
        for before in initial:
            if (not isinstance(before,dict) or any(not _source_positive(before.get(key)) for key in ('pid','creationTime','handleValue'))
                    or before.get('error') or type(before.get('alive')) is not bool or type(before.get('exitCode')) is not int):
                raise ValueError('x64 Base original member identity is invalid')
            image=_source_windows_path(before.get('image'))
            key=(before['pid'],before['creationTime'],before['handleValue'],image)
            if key in identities:raise ValueError('x64 Base retained member aliases another identity')
            identities.add(key)
            matches=[item for item in final if isinstance(item,dict)
                and (item.get('pid'),item.get('creationTime'),item.get('handleValue'),_source_windows_path(item.get('image'))) == key]
            if len(matches) != 1 or matches[0].get('alive') is not False or matches[0].get('error'):
                raise ValueError('x64 Base original retained member exit is unverified')
            exit_code=matches[0].get('exitCode')
            if type(exit_code) is not int or exit_code != 0:
                raise ValueError('x64 Base original member exit code differs')
            found |= before['alive'] is True and key[:2] == (host['pid'],host['creationTime']) and image == _source_windows_path(host['image'])
        if not found:raise ValueError('x64 Base retirement lacks the independently observed engine generation')


def _source_python_templates(proof: dict | None = None) -> dict:
    try:
        from suite.payload import COMPANION_PE_ADMISSIONS, _source_python_template_admissions
    except ModuleNotFoundError:
        from payload import COMPANION_PE_ADMISSIONS, _source_python_template_admissions
    source=proof.get('sourcePin') if isinstance(proof,dict) else None
    if isinstance(source,dict) and source.get('coreCommit')==NEW.core:
        if contract_for_source_pin(source) is not NEW:raise ValueError('New Python family requires the exact source profile')
        runtime=dict(format='source-built-zip',version=source['version'],sourceCoreCommit=source['coreCommit'],
            sourceUrl=source['url'],sourceSha256=source['sha256'])
        return {name.removeprefix('Office/'):pin for name,pin in _source_python_template_admissions(runtime,'x64').items()}
    return {name.removeprefix('Office/'):pin for name,pin in COMPANION_PE_ADMISSIONS.items()
            if pin['role']=='pythonLauncherTemplate'}


def _source_x64_companions(proof: dict, runtime: dict | None = None) -> dict:
    """Consume a validated component under the original externally pinned runtime.

    The common wrapper is not a Full factory. Callers authenticate the normal
    Full receipt first and pass that original runtime object, never a source-pin
    reconstruction or a candidate binary hash allowlist.
    """
    if type(proof) is not dict:raise ValueError('Source companion context must be an object')
    source=proof.get('sourcePin')
    if type(source) is not dict or source.get('coreCommit')!=NEW.core:
        if (type(runtime) is dict and runtime.get('sourceCoreCommit')==NEW.core
                or proof.get('sourceCompanionProof') is not None or proof.get('sourceTwainProof') is not None):
            raise ValueError('Source companion cannot be relabelled under a legacy source profile')
        return {}
    intents=(source_companion_intent(source,'x64'),source_twain_intent(source,'x64'))
    if type(runtime) is not dict:
        raise ValueError('New source companion requires the original externally pinned runtime')
    try:
        from suite.payload import _source_companion_admissions
    except ModuleNotFoundError:
        from payload import _source_companion_admissions
    companions=_source_companion_admissions(runtime,proof,architecture='x64')
    if type(companions) is not dict or set(companions)!={intent.path for intent in intents}:
        raise ValueError('Source companion family differs from its exact source intent')
    for intent in intents:
        value=companions[intent.path]
        if (type(value) is not dict or set(value)!={'machine','role','size','sha256'}
                or type(value['machine']) is not int or value['machine']!=0x14c
                or type(value['role']) is not str or value['role']!=intent.role
                or not _source_positive(value['size']) or not _source_digest(value['sha256'])):
            raise ValueError('Source companion admitted identity differs')
    return {intent.path:dict(companions[intent.path]) for intent in intents}


def _source_x64_inventory(proof: dict, runtime: dict | None = None) -> dict:
    root=_source_windows_path(proof['appLocalCrt']['programDirectory']).parent
    inventory=proof.get('productInventory');templates=_source_python_templates(proof)
    companions=_source_x64_companions(proof,runtime)
    if not isinstance(inventory,list) or not 0 < len(inventory) <= 100_000:
        raise ValueError('x64 source product inventory is missing or exceeds bounds')
    result={};counts=dict(nativeX64=0,managedAnyCpu=0,pythonLauncherTemplate=0)
    if companions:counts['x86CompatibilityHelper']=0
    for record in inventory:
        _source_file_identity(record)
        try:name=archive_path(_source_windows_path(record['path']).relative_to(root).as_posix())
        except ValueError:raise ValueError('x64 source product escaped its qualified runtime root') from None
        if name.casefold() in result:raise ValueError('x64 source product inventory path alias')
        role=record.get('role');machine=record.get('machine')
        if type(machine) is not int or role not in counts:
            raise ValueError('x64 source product role/machine is invalid')
        if (role=='nativeX64' and machine != 0x8664 or role=='managedAnyCpu' and machine != 0x14c
                or role=='pythonLauncherTemplate' and (name not in templates or
                    any(record.get(key) != templates[name][key] for key in ('machine','role','sha256')))
                or role=='x86CompatibilityHelper' and (name not in companions or
                    any(record.get(key) != companions[name][key] for key in ('machine','role','size','sha256')))):
            raise ValueError('x64 source product native/managed/pinned template identity differs')
        result[name.casefold()]=(name,record);counts[role]+=1
    expected_counts=dict(productPeCount=len(inventory),nativePeCount=counts['nativeX64'],
        managedAnyCpuCount=counts['managedAnyCpu'],pinnedTemplateCount=counts['pythonLauncherTemplate'])
    if companions:expected_counts['companionPeCount']=counts['x86CompatibilityHelper']
    if (any(type(proof.get(key)) is not int or proof[key] != value for key,value in expected_counts.items())
            or {name for name,record in result.values() if record['role']=='pythonLauncherTemplate'} != set(templates)
            or {name for name,record in result.values() if record['role']=='x86CompatibilityHelper'} != set(companions)):
        raise ValueError('x64 source product counts/template family are incomplete')
    if proof.get('crtImportClosure',{}).get('checkedPeCount') != counts['nativeX64']:
        raise ValueError('x64 source import closure does not cover the full native PE inventory')
    if companions:
        helper=proof['sourceCompanionProof']['nativeHelper']
        item=result.get('program/spsupp_helper.exe')
        if (type(helper) is not dict or set(helper)!={'path','machine','role','size','sha256'}
                or helper.get('path')!='program/spsupp_helper.exe' or item is None
                or item[0]!='program/spsupp_helper.exe' or item[1]['role'] != 'nativeX64'
                or any(item[1].get(key)!=helper.get(key) for key in ('machine','role','size','sha256'))):
            raise ValueError('Source companion native helper differs from its original inventory')
        twain=proof.get('sourceTwainProof')
        peer=twain.get('nativePeer') if type(twain) is dict else None
        item=result.get('program/scnlo.dll')
        if (type(peer) is not dict or set(peer)!={'path','machine','role','size','sha256'}
                or peer.get('path')!='program/scnlo.dll' or item is None
                or item[0]!='program/scnlo.dll' or item[1]['role'] != 'nativeX64'
                or any(item[1].get(key)!=peer.get(key) for key in ('machine','role','size','sha256'))):
            raise ValueError('TWAIN native peer differs from its original inventory')
    for crt in proof['crtPreflight']['files']:
        item=result.get(('program/'+crt['name']).casefold())
        if item is None or any(item[1].get(key) != crt.get(key) for key in ('machine','size','sha256')):
            raise ValueError('x64 source CRT bytes differ from the full native PE inventory')
    critical=('soffice.exe','soffice.bin','python.exe','pyuno.pyd','ifbclient.dll','Engine12.dll','intl/fbintl.dll','winaccessibility.dll')
    for relative in critical:
        item=result.get(('program/'+relative).casefold())
        if item is None or item[0] != 'program/'+relative or item[1]['role'] != 'nativeX64':
            raise ValueError('x64 source critical runtime file is missing or foreign')
    winacc=proof.get('winAccBinary');record=result['program/winaccessibility.dll'][1]
    if (not isinstance(winacc,dict) or winacc.get('path') != 'program/winaccessibility.dll'
            or any(winacc.get(key) != record.get(key) for key in ('machine','role','size','sha256','imports'))):
        raise ValueError('x64 WinAcc native identity differs from actual product inventory')
    imports=winacc.get('imports')
    if not isinstance(imports,dict) or set(imports) != {'normal','delay'} or not imports['normal']:
        raise ValueError('x64 WinAcc normal/delay imports are incomplete')
    for values in imports.values():
        if (not isinstance(values,list) or values != sorted(set(values))
                or any(not isinstance(value,str) or not re.fullmatch(r'[a-z0-9_.-]+\.dll',value) for value in values)):
            raise ValueError('x64 WinAcc import names are malformed or aliased')
    return result


def _source_build_x64(proof: dict, runtime: dict, target: dict) -> None:
    binding=proof.get('workflowBinding')
    expected=dict(workflow=target['workflow'],workflowRef='ATLKR/OpenGeul/'+target['workflow']+'@'+target['ref'],
        ref=target['ref'],job=target['job'],sourceRun=proof['sourceRun'],runAttempt=1,
        sourceCommit=proof['sourceCommit'],sourceTree=proof['sourceTree'])
    if (proof.get('acceptanceEligible') is not True or type(proof.get('runAttempt')) is not int or proof['runAttempt'] != 1
            or not _source_positive(proof.get('host',{}).get('controllerPid'))
            or proof.get('nativeTargetsSha256') != 'ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'
            or not _source_digest(proof.get('configurationSha256')) or not _source_digest(proof.get('configureArgumentsSha256'))
            or proof.get('sourceRecipeChecksExecuted') is not True
            or proof.get('harfbuzzNativeMesonReplayChecksExecuted') is not True or binding != expected
            or not isinstance(binding,dict) or any(type(binding[key]) is not type(value) for key,value in expected.items())):
        raise ValueError('x64 v2 qualification/source/workflow binding is incomplete')
    if _source_windows_path(proof['artifact'].get('path')).name != target['archive']:
        raise ValueError('x64 qualified archive name differs from its fixed target policy')
    _source_x64_preflight(proof)
    _source_x64_atl_inputs(proof)
    _source_x64_prerequisites(proof)
    if proof.get('sourcePin',{}).get('coreCommit')==NEW.core:_source_new_recipe(proof,'x64')
    else:_source_x64_recipe(proof)
    _source_x64_retirement(proof['baseProof'])
    _source_x64_inventory(proof,runtime=runtime)
    external=proof.get('externalSources');stage=proof.get('installedRuntimeStage')
    if (not isinstance(external,dict) or type(external.get('schemaVersion')) is not int or external['schemaVersion'] != 1
            or external.get('pythonSourceVerified') is not True
            or not isinstance(external.get('archives'),list) or not external['archives']
            or not isinstance(external.get('embeddedPythonWheels'),list) or not external['embeddedPythonWheels']
            or not isinstance(stage,dict) or stage.get('passed') is not True
            or stage.get('requiredHelpLanguages') != ['en-US','ko']
            or not _source_positive(stage.get('fileCount')) or stage['fileCount'] < proof['productPeCount']
            or not _source_positive(stage.get('archiveCount')) or stage['archiveCount'] != 3
            or _source_windows_path(stage.get('runtimeRoot')) != _source_windows_path(proof['appLocalCrt']['programDirectory']).parent):
        raise ValueError('x64 source archive/staged runtime provenance is incomplete')
    names=set();python=False
    for record in external['archives']:
        if (not isinstance(record,dict) or not isinstance(record.get('filename'),str)
                or '/' in record['filename'] or '\\' in record['filename']
                or archive_path(record['filename']).casefold() in names
                or not _source_positive(record.get('size')) or not _source_digest(record.get('sha256'))
                or not isinstance(record.get('pinVariable'),str) or not record['pinVariable']):
            raise ValueError('x64 authenticated external source inventory is malformed or aliased')
        names.add(record['filename'].casefold());python |= record['pinVariable']=='PYTHON_TARBALL'
    if not python:raise ValueError('x64 Python source archive lacks authenticated download-list provenance')
    names=set()
    for record in external['embeddedPythonWheels']:
        if (not isinstance(record,dict) or not isinstance(record.get('path'),str)
                or not record['path'].endswith('.whl') or archive_path(record['path']).casefold() in names
                or not _source_positive(record.get('size')) or not _source_digest(record.get('sha256'))
                or record.get('provenance') != 'unpacked authenticated Python source plus source-controlled patches'):
            raise ValueError('x64 bundled Python wheel source inventory is malformed or aliased')
        names.add(record['path'].casefold())
    reference=stage.get('receipt')
    if (not isinstance(reference,dict) or set(reference) != {'path','bytes','sha256'}
            or not _source_positive(reference.get('bytes')) or reference['bytes'] > 32*1024*1024
            or not _source_digest(reference.get('sha256'))):
        raise ValueError('x64 installed source runtime stage receipt identity is incomplete')
    _source_windows_path(reference.get('path'))


def _source_x64_runtime(runtime_root: Path, proof: dict, runtime: dict | None = None) -> None:
    """Replay every PE against the authenticated producer, including disguised PEs."""
    expected=_source_x64_inventory(proof,runtime=runtime);templates=_source_python_templates(proof);actual=set()
    companions=_source_x64_companions(proof,runtime)
    admitted=dict(templates,**companions)
    try:
        from suite.payload import _pe
        from suite.pe_imports import read_pe_imports
    except ModuleNotFoundError:
        from payload import _pe
        from pe_imports import read_pe_imports
    for path in runtime_root.rglob('*'):
        info=path.lstat()
        if path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('x64 source runtime contains a linked path')
        if stat.S_ISDIR(info.st_mode):continue
        if not stat.S_ISREG(info.st_mode):raise ValueError('x64 source runtime contains a nonregular path')
        with path.open('rb') as stream:magic=stream.read(2)
        name=path.relative_to(runtime_root).as_posix();key=name.casefold()
        if magic != b'MZ' and path.suffix.lower() not in ('.exe','.dll','.pyd') and name != 'program/soffice.bin':continue
        if key in actual or key not in expected or expected[key][0] != name:
            raise ValueError('x64 source runtime PE was added, renamed or case aliased')
        actual.add(key);record=expected[key][1]
        check_asset(record,path)
        _pe(path,companion=admitted.get(name) if record['role'] in ('pythonLauncherTemplate','x86CompatibilityHelper') else None,architecture='x64')
        with path.open('rb') as stream:
            stream.seek(60);offset=struct.unpack('<I',stream.read(4))[0];stream.seek(offset+4)
            machine=struct.unpack('<H',stream.read(2))[0]
        if machine != record['machine']:
            raise ValueError('x64 source runtime PE machine differs from producer inventory')
        if name=='program/winaccessibility.dll':
            with path.open('rb') as stream:
                stream.seek(offset+22);flags=struct.unpack('<H',stream.read(2))[0]
            imports={key:list(values) for key,values in read_pe_imports(path).items()}
            if not flags&0x2000 or imports != proof['winAccBinary']['imports']:
                raise ValueError('x64 WinAcc DLL/import bytes differ from authenticated source proof')
    if actual != expected.keys():
        raise ValueError('x64 source runtime lacks inventoried native/managed/template PE bytes')
    if companions:
        try:
            from suite.payload import _source_companion_runtime, _source_twain_runtime
        except ModuleNotFoundError:
            from payload import _source_companion_runtime, _source_twain_runtime
        _source_companion_runtime(runtime_root,proof['sourceCompanionProof'])
        _source_twain_runtime(runtime_root,proof['sourceTwainProof'])


def validate_source_build_lock(runtime: dict, *, architecture: str) -> dict:
    """Require immutable external pins; a receipt never authorizes itself."""
    def digest(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    def positive(value):
        return type(value) is int and value > 0
    if not isinstance(runtime,dict):raise ValueError('Source-build runtime lock must be an object')
    build = runtime.get('sourceBuild')
    if (not isinstance(architecture,str) or architecture not in NATIVE_MACHINES or runtime.get('format') != 'source-built-zip'
            or not isinstance(build, dict) or not positive(runtime.get('size'))
            or not digest(runtime.get('sha256'))
            or not isinstance(runtime.get('sourceCoreCommit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', runtime['sourceCoreCommit'])
            or not isinstance(build.get('sourceCommit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', build['sourceCommit'])
            or any(not digest(build.get(key)) for key in
                   ('receiptSha256', 'artifactSha256', 'patchManifestSha256'))
            or any(not positive(build.get(key)) for key in ('runId', 'artifactId'))):
        raise ValueError('Complete native source-build lock and externally pinned receipt are required')
    for key in ('url', 'sourceUrl'):
        url = runtime.get(key)
        try:
            parsed = urllib.parse.urlsplit(url) if isinstance(url, str) else None
            valid = (parsed and parsed.scheme == 'https' and parsed.hostname
                     and not parsed.username and not parsed.password and not any(ord(c) <= 32 for c in url))
        except ValueError:
            valid = False
        if not valid: raise ValueError('Source-build lock requires complete HTTPS provenance')
    if not digest(runtime.get('sourceSha256')) or not isinstance(runtime.get('version'), str):
        raise ValueError('Source-build lock requires authenticated upstream source provenance')
    if architecture == 'x64':
        target=_source_build_target(architecture)
        if (not isinstance(build.get('sourceTree'),str) or not re.fullmatch(r'[0-9a-f]{40}',build['sourceTree'])
                or not digest(build.get('driverSha256')) or not digest(build.get('nativeTargetsSha256'))
                or build['nativeTargetsSha256'] != 'ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'
                or target['proofVersion'] != 2):
            raise ValueError('x64 v2 source-build lock requires independent source tree, driver and reviewed policy pins')
    elif runtime['sourceCoreCommit']==NEW.core:
        if (not isinstance(build.get('sourceTree'),str) or not re.fullmatch(r'[0-9a-f]{40}',build['sourceTree'])
                or not digest(build.get('driverSha256'))
                or build.get('nativeTargetsSha256')!='ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'):
            raise ValueError('New ARM source lock requires independent tree, driver and policy pins')
    return build


def validate_source_build_receipt(runtime: dict, receipt: Path, *, architecture: str) -> dict:
    """Authenticate exact driver evidence before interpreting its native/Base claims."""
    build = validate_source_build_lock(runtime, architecture=architecture)
    info = receipt.lstat()
    if (not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not 0 < info.st_size <= 8*1024*1024 or sha256(receipt) != build['receiptSha256']):
        raise ValueError('Source-build receipt does not match its external locked SHA256 or size bound')
    try:
        from suite.payload import _json_bytes
    except ModuleNotFoundError:
        from payload import _json_bytes
    proof = _json_bytes(receipt.read_bytes(), 'source-build receipt')
    target = _source_build_target(architecture) if architecture == 'x64' else None
    machine = native_machine(architecture)
    version = 2 if architecture == 'x64' else 1
    def positive(value):
        return type(value) is int and value > 0
    def native(value):
        return (isinstance(value, dict) and type(value.get('processMachine')) is int
                and value['processMachine'] == 0 and type(value.get('nativeMachine')) is int
                and value['nativeMachine'] == machine)
    if (type(proof.get('schemaVersion')) is not int or proof['schemaVersion'] != version
            or proof.get('kind') != 'native-office-engine-source-build'
            or proof.get('phase') != 'Full' or proof.get('architecture') != architecture
            or proof.get('passed') is not True or proof.get('fullEngineQualified') is not True
            or proof.get('guiVerified') is not False or proof.get('stage') != 'complete'
            or proof.get('status') != 'native-engine-source-build-qualified'
            or proof.get('sourceCommit') != build['sourceCommit']
            or type(proof.get('sourceRun')) is not int or proof['sourceRun'] != build['runId']
            or proof.get('sourcePortManifestSha256') != build['patchManifestSha256']
            or not isinstance(proof.get('sourceTree'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', proof['sourceTree'])
            or not positive(proof.get('runAttempt'))
            or not isinstance(proof.get('driverSha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', proof['driverSha256'])
            or not native(proof.get('host')) or proof['host'].get('isWindows') is not True):
        raise ValueError('Source-build receipt does not qualify an authenticated full native engine')
    source = proof.get('sourcePin'); artifact = proof.get('artifact'); config = proof.get('configuration')
    if (not isinstance(source, dict) or any(source.get(a) != runtime.get(b) for a, b in
            (('url', 'sourceUrl'), ('sha256', 'sourceSha256'), ('version', 'version')))
            or not positive(source.get('size')) or not isinstance(artifact, dict)
            or type(artifact.get('size')) is not int or artifact['size'] != runtime['size']
            or artifact.get('sha256') != runtime['sha256']):
        raise ValueError('Source-build receipt artifact/source identity differs from locked input')
    cpu, triple = (('X86_64', 'x86_64-pc-cygwin') if architecture == 'x64' else ('AARCH64', 'aarch64-pc-cygwin'))
    required = {'OS': 'WNT', 'COM': 'MSC', 'CPUNAME': cpu,
                'HOST_PLATFORM': triple, 'BUILD_PLATFORM': triple,
                'ENABLE_FIREBIRD_SDBC': 'TRUE', 'CROSS_COMPILING': '', 'SYSTEM_FIREBIRD': '',
                'PKGFORMAT': 'archive', 'ENABLE_ONLINE_UPDATE': '',
                'ENABLE_ONLINE_UPDATE_MAR': '', 'ENABLE_BREAKPAD': ''}
    if (not isinstance(config, dict) or any(config.get(key) != value for key, value in required.items())
            or not isinstance(config.get('BUILD_TYPE'), str)
            or not ({'FIREBIRD', 'LIBTOMMATH'} | ({'LIBATOMIC_OPS'} if architecture == 'arm64' else set())) <= set(config['BUILD_TYPE'].split())
            or {'BREAKPAD', 'ONLINEUPDATE'} & {token.upper() for token in config['BUILD_TYPE'].split()}):
        raise ValueError('Source-build receipt configuration does not prove native internal Firebird and disabled OEM services')
    _source_build_identity(proof, runtime['sourceCoreCommit'])
    if source.get('coreCommit')==NEW.core:
        if (contract_for_source_pin(source) is not NEW or proof.get('acceptanceEligible') is not True
                or type(proof.get('runAttempt')) is not int or proof['runAttempt']!=1
                or any(proof.get(key)!=build.get(key) for key in ('sourceTree','driverSha256','nativeTargetsSha256'))):
            raise ValueError('New source qualification differs from independent external pins')
        if architecture=='arm64':_source_new_recipe(proof,architecture)
    base = proof.get('baseProof')
    if (not isinstance(base, dict) or type(base.get('schemaVersion')) is not int or base['schemaVersion'] != version
            or base.get('passed') is not True or base.get('guiVerified') is not False
            or base.get('independentReopenVerified') is not True
            or base.get('rows') != [{'id': 1, 'text': 'Engine-OpenGeul-base 한글', 'amount': 42}]
            or type(base['rows'][0]['id']) is not int or type(base['rows'][0]['amount']) is not int
            or not isinstance(base.get('odbSha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', base['odbSha256'])):
        raise ValueError('Source-build receipt lacks exact independent Base persistence proof')
    processes = base.get('nativeProcesses')
    if (not isinstance(processes, list) or len(processes) != 3
            or any(not native(item) or not positive(item.get('pid')) for item in processes)
            or any(item['pid'] == processes[0]['pid'] for item in processes[1:])
            or processes[0].get('role') != 'uno-python'):
        raise ValueError('Source-build Base proof lacks actual native Python/Office process witnesses')
    images = []
    for process, phase in zip(processes[1:], ('create', 'reopen')):
        image = process.get('image')
        if (process.get('role') != 'uno-host' or process.get('jobOwned') is not True
                or process.get('phase') != phase or not positive(process.get('creationTime'))
                or not isinstance(image, str) or '\x00' in image
                or not PureWindowsPath(image).is_absolute()
                or tuple(part.casefold() for part in PureWindowsPath(image).parts[-2:]) != ('program', 'soffice.bin')):
            raise ValueError('Source-build Base proof requires owned actual soffice.bin create/reopen hosts')
        images.append(str(PureWindowsPath(image)).casefold())
    if (images[0] != images[1] or (processes[1]['pid'], processes[1]['creationTime']) ==
            (processes[2]['pid'], processes[2]['creationTime'])):
        raise ValueError('Source-build Base proof must independently reopen with the same engine')
    if architecture == 'x64':
        if any(proof.get(key) != build[key] for key in ('sourceTree','driverSha256','nativeTargetsSha256')):
            raise ValueError('x64 source tree/driver/policy differs from externally reviewed lock')
        try: _source_build_x64(proof, runtime, target)
        except (KeyError, TypeError, AttributeError, IndexError) as error:
            raise ValueError('x64 source-build proof is malformed or incomplete') from error
    _source_build_crt(proof, architecture=architecture)
    return proof


def _source_build_identity(proof: dict, core: str) -> dict:
    """Replay the emitted correction/final proof against the external source core pin."""
    source = proof.get('sourcePin'); identity = proof.get('runtimeBuildIdentity')
    def digest(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    if (not isinstance(core, str) or not re.fullmatch(r'[0-9a-f]{40}', core)
            or not isinstance(source, dict) or source.get('coreCommit') != core
            or not isinstance(identity, dict) or type(identity.get('schemaVersion')) is not int
            or identity['schemaVersion'] != 1
            or identity.get('mechanism') != 'explicit-generated-config-correction-from-authenticated-source-pin'
            or identity.get('expectedBuildId') != core
            or identity.get('sourceArchiveUrl') != source.get('url')
            or identity.get('sourceArchiveSha256') != source.get('sha256')
            or type(identity.get('sourceArchiveSize')) is not int
            or identity['sourceArchiveSize'] != source.get('size')):
        raise ValueError('Source-build runtime identity differs from externally pinned upstream core/source')
    files = identity.get('files'); final = identity.get('finalVerification')
    names = {'program/version.ini', 'program/setup.ini'}
    if (not isinstance(files, dict) or set(files) != names or not isinstance(final, dict)
            or final.get('passed') is not True or final.get('expectedBuildId') != core
            or not isinstance(final.get('files'), dict) or set(final['files']) != names):
        raise ValueError('Source-build runtime identity final verification is missing or incomplete')
    originals = [record.get('originalBuildId') if isinstance(record, dict) else None
                 for record in files.values()]
    if not all(isinstance(value, str) for value in originals) or len(set(originals)) != 1:
        raise ValueError('Source-build original identity modes disagree')
    original = originals[0]
    mode = ('empty' if original == '' else 'pinned-core' if original == core else
            'actual-parent' if original == proof.get('sourceCommit') else 'installed-no-git-fallback')
    if 'identityMode' in identity and identity['identityMode'] != mode:
        raise ValueError('Source-build identity mode differs from original identities')
    if mode == 'installed-no-git-fallback':
        # A mode tag or a general installer-label regex never authorizes admission.
        expected_source = source
        derivation = fallback_identity_expectation(source)
        expected_config = derivation['configuration']
        config = proof.get('configuration')
        if (source != expected_source or core != expected_source['coreCommit']
                or not isinstance(config, dict) or any(config.get(k) != v for k, v in expected_config.items())):
            raise ValueError('Installed identity fallback requires exact authenticated source/configuration')
        fallback = derivation['buildid']
        if (identity.get('identityMode') != mode or original != fallback
                or identity.get('installedFallbackDerivation') != derivation):
            raise ValueError('Installed identity fallback derivation differs from authenticated installer formula')
    if mode == 'installed-no-git-fallback' or 'stageReceipt' in identity or 'originals' in identity:
        # Compact replay checks descriptors and their shared pinned receipt reference.
        # Producer/audit authenticate the separate map and original raw bytes; those
        # diagnostic files are deliberately outside the two-file qualified artifact.
        reference = identity.get('stageReceipt'); stage = proof.get('installedRuntimeStage')
        descriptors = identity.get('originals')
        if (not isinstance(reference, dict) or set(reference) != {'path', 'bytes', 'sha256'}
                or not isinstance(reference.get('path'), str) or not reference['path']
                or '\x00' in reference['path'] or type(reference.get('bytes')) is not int
                or not 0 < reference['bytes'] <= 32*1024*1024 or not digest(reference.get('sha256'))
                or not isinstance(stage, dict) or stage.get('passed') is not True
                or stage.get('receipt') != reference
                or not isinstance(descriptors, dict) or set(descriptors) != names):
            raise ValueError('Installed identity stage/original descriptors are incomplete or inconsistent')
        archives = set(); wrappers = set()
        for name, descriptor in descriptors.items():
            if (not isinstance(descriptor, dict)
                    or set(descriptor) != {'archivePath', 'archiveMember', 'bytes', 'sha256'}
                    or type(descriptor.get('bytes')) is not int or not 0 < descriptor['bytes'] <= 65536
                    or descriptor.get('sha256') != files[name].get('beforeSha256')
                    or not digest(descriptor.get('sha256'))
                    or not isinstance(descriptor.get('archivePath'), str) or not descriptor['archivePath']
                    or '\x00' in descriptor['archivePath']
                    or not isinstance(descriptor.get('archiveMember'), str)
                    or not descriptor['archiveMember'].endswith('/'+name)):
                raise ValueError('Installed identity original descriptor differs: '+name)
            member = archive_path(descriptor['archiveMember'])
            wrappers.add(member[:-len('/'+name)])
            archives.add(descriptor['archivePath'])
        if len(archives) != 1 or len(wrappers) != 1:
            raise ValueError('Installed identity originals do not share one main archive wrapper')
    for name, record in files.items():
        original = record.get('originalBuildId') if isinstance(record, dict) else None
        if (not isinstance(record, dict) or not isinstance(original, str)
                or record.get('buildid') != core or record.get('corrected') is not (original != core)
                or not digest(record.get('beforeSha256')) or not digest(record.get('sha256'))
                or original == core and record['beforeSha256'] != record['sha256']
                or final['files'][name] != {'buildid': core, 'sha256': record['sha256']}):
            raise ValueError('Source-build runtime identity original/corrected/final metadata differs: '+name)
    return identity


def _source_build_crt(proof: dict, *, architecture: str = 'arm64') -> tuple[dict, dict]:
    """Join the driver's preflight, signed sources, copied bytes and legal snapshot."""
    plan = proof.get('crtPreflight'); copied = proof.get('appLocalCrt'); terms = proof.get('crtRedistributionTerms')
    expected = frozenset(crt_names(architecture))
    toolset, year = ('v143', '2022') if architecture == 'x64' else ('v145', '2026')
    def version(value):
        if not isinstance(value, str) or not re.fullmatch(r'14\.[0-9]+\.[0-9]+(?:\.[0-9]+)?', value):
            raise ValueError('Source-build CRT compiler/runtime version is invalid')
        return tuple(map(int, value.split('.'))) + ((0,) if value.count('.') == 2 else ())
    if (not isinstance(plan, dict) or not isinstance(copied, dict)
            or plan.get('schemaVersion') != 1 or copied.get('schemaVersion') != 1
            or plan.get('toolset') != toolset or copied.get('toolset') != toolset
            or plan.get('architecture') != architecture or copied.get('architecture') != architecture
            or not isinstance(plan.get('files'), list) or len(plan['files']) != len(expected)
            or not isinstance(copied.get('files'), list) or len(copied['files']) != len(expected)):
        raise ValueError('Source-build CRT requires the complete native compiler-specific file family')
    if architecture == 'x64' and (type(plan['schemaVersion']) is not int or type(copied['schemaVersion']) is not int):
        raise ValueError('x64 source CRT schema versions require integer identities')
    minimum = version(plan.get('minimumRuntimeVersion'))
    if (architecture == 'arm64' and minimum != version(plan.get('compilerToolsVersion'))
            or architecture == 'x64' and (plan.get('minimumRuntimeVersion') != '.'.join(map(str,version(plan.get('compilerToolsVersion'))))
                or plan != proof.get('nativePreflight', {}).get('crt')
                or plan.get('compilerToolsVersion') != proof.get('nativePreflight', {}).get('compiler', {}).get('compilerToolsVersion')
                or plan.get('minimumRuntimeVersion') != proof.get('nativePreflight', {}).get('compiler', {}).get('minimumRuntimeVersion'))):
        raise ValueError('Source-build CRT version floor differs from selected compiler')
    if architecture == 'x64':
        compiler = _source_windows_path(proof['nativePreflight']['compiler']['compilerRoot'])
        if (_source_windows_path(plan.get('compilerRoot')) != compiler
                or tuple(part.casefold() for part in compiler.parts[-4:-1]) != ('vc', 'tools', 'msvc')
                or compiler.name != plan['compilerToolsVersion']):
            raise ValueError('x64 CRT compiler lineage differs from the selected VS installation')
        redist = compiler.parents[2]/'Redist/MSVC'
        directory = plan.get('redistVersionDirectory')
        match = re.fullmatch(r'[vV]?(14\.[0-9]+\.[0-9]+(?:\.[0-9]+)?)', directory) if isinstance(directory, str) else None
        if ((directory != 'v143' and match is None) or plan.get('redistFamily') != 'Microsoft.VC143.CRT'
                or _source_windows_path(plan.get('redistRoot')) != redist
                or _source_windows_path(plan.get('sourceDirectory')) != redist/directory/'x64/Microsoft.VC143.CRT'):
            raise ValueError('x64 CRT redist lineage/family differs from the selected native compiler')
    source_dir = plan.get('sourceDirectory'); program_dir = copied.get('programDirectory')
    if (not isinstance(source_dir, str) or not isinstance(program_dir, str)
            or '\x00' in source_dir or '\x00' in program_dir
            or not PureWindowsPath(source_dir).is_absolute() or not PureWindowsPath(program_dir).is_absolute()
            or PureWindowsPath(program_dir).name.casefold() != 'program'
            or copied.get('sourceDirectory') != source_dir
            or any(PureWindowsPath(item['image']).parent != PureWindowsPath(program_dir)
                   for item in proof['baseProof']['nativeProcesses'][1:])):
        raise ValueError('Source-build CRT source/runtime directories differ from qualified engine')
    records = {}
    for record in plan['files']:
        if not isinstance(record, dict) or record.get('name') not in expected:
            raise ValueError('Unexpected source-build CRT file')
        name = record['name']; signature = record.get('signature')
        if (name in records or type(record.get('machine')) is not int or record['machine'] != native_machine(architecture)
                or type(record.get('size')) is not int or record['size'] <= 0
                or not isinstance(record.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])
                or not isinstance(record.get('sourcePath'), str) or '\x00' in record['sourcePath']
                or PureWindowsPath(record['sourcePath']) != PureWindowsPath(source_dir)/name
                or not isinstance(signature, dict) or signature.get('status') != 'Valid'
                or not isinstance(signature.get('signerSubject'), str)
                or not re.search(r'(?:^|,\s*)O=Microsoft Corporation(?:,|$)', signature['signerSubject'])
                or not isinstance(signature.get('signerThumbprint'), str)
                or not re.fullmatch(r'[0-9a-fA-F]{40}', signature['signerThumbprint'])
                or signature.get('companyName') != 'Microsoft Corporation'
                or not isinstance(signature.get('originalFilename'), str)
                or signature['originalFilename'].casefold() != name):
            raise ValueError('Source-build CRT native machine/Microsoft signature identity is invalid')
        for field in ('fileVersionParts', 'productVersionParts'):
            parts = signature.get(field)
            if (not isinstance(parts, list) or len(parts) != 4
                    or any(type(part) is not int or part < 0 for part in parts)
                    or parts[0] != 14 or tuple(parts) < minimum):
                raise ValueError('Source-build CRT signed runtime is older than selected compiler')
        records[name] = record
    if set(records) != expected:
        raise ValueError('Source-build CRT exact native file family is incomplete')
    if architecture == 'x64':
        actual_floor=min(tuple(record['signature']['fileVersionParts']) for record in records.values())
        if (plan.get('selectionBasis') != 'actual-signed-crt-files-v1'
                or plan.get('selectedFileVersionFloor') != '.'.join(map(str,actual_floor))):
            raise ValueError('x64 CRT selection does not match the actual signed file-version floor')
    seen = set()
    for item in copied['files']:
        source = item.get('source') if isinstance(item, dict) else None
        name = source.get('name') if isinstance(source, dict) else None
        if (not isinstance(name, str) or name not in records or name in seen or source != records[name]
                or item.get('copiedSha256') != records[name]['sha256']
                or type(item.get('alreadyIdentical')) is not bool
                or not isinstance(item.get('destination'), str) or '\x00' in item['destination']
                or PureWindowsPath(item['destination']) != PureWindowsPath(program_dir)/name):
            raise ValueError('Source-build CRT preflight/source/copied byte identities differ')
        seen.add(name)
    app_terms = copied.get('redistributionTerms')
    if (not isinstance(terms, dict) or not isinstance(app_terms, dict)
            or terms.get('url') != 'https://learn.microsoft.com/en-us/visualstudio/releases/'+year+'/redistribution'
            or type(terms.get('size')) is not int or not 0 < terms['size'] <= 2*1024*1024
            or not isinstance(terms.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', terms['sha256'])
            or app_terms.get('sha256') != terms['sha256'] or not isinstance(app_terms.get('path'), str)
            or '\x00' in app_terms['path'] or PureWindowsPath(app_terms['path']) !=
                PureWindowsPath(program_dir).parent/('share/readme/Microsoft-VC'+toolset[1:]+'-redistribution.html')):
        raise ValueError('Source-build CRT redistribution terms snapshot differs from packaged legal source')
    _source_build_import_closure(proof, architecture=architecture)
    return records, terms


def _source_build_import_closure(proof: dict, *, architecture: str = 'arm64') -> dict:
    closure = proof.get('crtImportClosure')
    expected = list(crt_names(architecture))
    if (not isinstance(closure, dict)
            or set(closure) != {'schemaVersion', 'architecture', 'passed', 'requiredCrtFiles', 'checkedPeCount', 'imports'}
            or type(closure.get('schemaVersion')) is not int or closure['schemaVersion'] != 1
            or closure.get('architecture') != architecture or closure.get('passed') is not True
            or closure.get('requiredCrtFiles') != expected
            or type(closure.get('checkedPeCount')) is not int or not 0 < closure['checkedPeCount'] <= 100_000
            or not isinstance(closure.get('imports'), list) or len(closure['imports']) > closure['checkedPeCount']):
        raise ValueError('Source-build CRT requires an exact successful native normal/delay import closure')
    paths = set()
    for item in closure['imports']:
        if (not isinstance(item, dict) or set(item) != {'path', 'normal', 'delay'}
                or not isinstance(item['path'], str)):
            raise ValueError('Invalid source-build CRT import record')
        name = archive_path(item['path'])
        if name.casefold() in paths:
            raise ValueError('Duplicate source-build CRT import image')
        paths.add(name.casefold())
        for kind in ('normal', 'delay'):
            names = item[kind]
            if (not isinstance(names, list) or any(not isinstance(name, str) or name not in expected for name in names)
                    or names != sorted(set(names))):
                raise ValueError('Unexpected source-build CRT normal/delay import')
        if not item['normal'] and not item['delay']:
            raise ValueError('Empty source-build CRT import record')
    return closure


def validate_source_build_runtime(runtime_root: Path, proof: dict, *, architecture: str = 'arm64', branding: dict | None = None, runtime: dict | None = None) -> None:
    """Replay metadata and CRT bytes after authenticating the receipt against its lock.

    Only the final Suite payload supplies branding; preparation checks the exact
    original metadata hash, and packaging joins that hash to the branded bytes.
    """
    if (not isinstance(architecture,str) or architecture not in NATIVE_MACHINES
            or not isinstance(proof,dict) or proof.get('architecture') != architecture
            or type(proof.get('schemaVersion')) is not int or proof['schemaVersion'] != (2 if architecture == 'x64' else 1)):
        raise ValueError('Source-build runtime expected architecture/version differs from authenticated proof')
    records, terms = _source_build_crt(proof, architecture=architecture)
    core = proof.get('sourcePin', {}).get('coreCommit')
    identity = _source_build_identity(proof, core)
    for name, section in (('program/version.ini', 'Version'), ('program/setup.ini', 'Bootstrap')):
        path = runtime_root/name
        expected_hash = identity['files'][name]['sha256']
        if branding is not None and name == 'program/version.ini':
            changes = branding.get('modifiedFiles') if isinstance(branding, dict) else None
            branded_source = branding.get('source') if isinstance(branding, dict) else None
            change = changes.get(name) if isinstance(changes, dict) else None
            if (not isinstance(change, dict) or change.get('beforeSha256') != expected_hash
                    or not isinstance(change.get('sha256'), str)
                    or not re.fullmatch(r'[0-9a-f]{64}', change['sha256'])
                    or not isinstance(branded_source, dict) or branded_source.get('buildId') != core):
                raise ValueError('Source-build runtime identity is not joined to actual branding input/output')
            expected_hash = change['sha256']
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
                    or not 0 < info.st_size <= 1024*1024 or sha256(path) != expected_hash):
                raise ValueError('Runtime metadata bytes differ')
            metadata = configparser.RawConfigParser()
            text = path.read_text(encoding='utf-8-sig')
            assignments = re.findall(r'(?im)^[ \t]*buildid[ \t]*=([^\r\n]*)', text)
            metadata.read_string(text)
            if (metadata.sections() != [section] or metadata.defaults()
                    or assignments != [core]
                    or metadata.get(section, 'buildid', fallback=None) != core):
                raise ValueError('Effective runtime buildid differs')
        except (OSError, UnicodeError, configparser.Error, ValueError) as error:
            raise ValueError('Source-build runtime identity/buildid bytes are missing, changed or ambiguous: '+name) from error
    try:
        from suite.payload import _pe
    except ModuleNotFoundError:
        from payload import _pe
    for name, record in records.items():
        path = runtime_root/'program'/name
        try:
            check_asset(record, path)
            _pe(path, architecture=architecture)
            with path.open('rb') as stream:
                stream.seek(60); offset = struct.unpack('<I', stream.read(4))[0]
                stream.seek(offset+4)
                if struct.unpack('<H', stream.read(2))[0] != native_machine(architecture):
                    raise ValueError('App-local CRT must use the expected native architecture')
        except (OSError, ValueError, struct.error) as error:
            raise ValueError('Source-build CRT bytes/machine differ from authenticated receipt: '+name) from error
    try:
        check_asset(terms, runtime_root/('share/readme/Microsoft-VC'+('143' if architecture == 'x64' else '145')+'-redistribution.html'))
    except (OSError, ValueError) as error:
        raise ValueError('Source-build CRT redistribution terms bytes differ from authenticated receipt') from error
    try:
        from suite.crt import validate_crt_imports
    except ModuleNotFoundError:
        from crt import validate_crt_imports
    if validate_crt_imports(runtime_root, architecture=architecture) != _source_build_import_closure(proof, architecture=architecture):
        raise ValueError('Source-build CRT normal/delay import closure differs from authenticated receipt')
    if architecture == 'x64':
        _source_x64_runtime(runtime_root, proof, runtime=runtime)


def extract_source_engine_zip(archive: Path, destination: Path, *, runtime: dict, receipt: Path,
                              architecture: str, limit: int = 8*1024*1024*1024,
                              max_files: int = 100_000, max_file_size: int = 1024*1024*1024) -> Path:
    """Extract a locally supplied, externally authenticated qualified source engine."""
    validate_source_build_lock(runtime, architecture=architecture)
    check_asset(runtime, archive)
    proof = validate_source_build_receipt(runtime, receipt, architecture=architecture)
    if destination.exists() or destination.is_symlink(): raise ValueError('Source engine output already exists')
    for parent in destination.absolute().parents:
        if parent.exists() or parent.is_symlink():
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Source engine output requires unlinked regular parent directories')
    with zipfile.ZipFile(archive) as source:
        members = source.infolist(); aliases = {}; explicit = set(); total = 0
        if not members or len(members) > max_files: raise ValueError('Source engine ZIP member count exceeds bound')
        for member in members:
            archive_path(member.orig_filename)
            name = archive_path(member.filename); key = name.casefold()
            kind = stat.S_IFMT(member.external_attr >> 16)
            directory = member.is_dir()
            if (key in explicit or key.split('/')[0] in ('opengeul-source-build.json', 'opengeul-msi-dependencies.json')
                    or member.flag_bits & 1 or member.external_attr & 0x400
                    or kind not in ((0, stat.S_IFDIR) if directory else (0, stat.S_IFREG))):
                raise ValueError('Unsafe source engine ZIP member kind/collision: '+name)
            explicit.add(key)
            parts = name.split('/')
            for index in range(1, len(parts)+1):
                prefix = '/'.join(parts[:index]); alias = prefix.casefold()
                is_directory = index < len(parts) or directory
                if alias in aliases and (aliases[alias][0] != prefix or not aliases[alias][1] or not is_directory):
                    raise ValueError('Source engine ZIP case/path collision: '+name)
                aliases[alias] = (prefix, is_directory)
            total += member.file_size
            if member.file_size > max_file_size or total > limit or (directory and member.file_size):
                raise ValueError('Source engine ZIP exceeds extraction size bound')
        required = {'program/'+name for name in ('soffice.exe', 'soffice.bin', 'python.exe', 'pyuno.pyd',
                     'ifbclient.dll', 'Engine12.dll', 'intl/fbintl.dll')}
        if architecture == 'x64':required.add('program/winaccessibility.dll')
        if any(name.casefold() not in aliases or aliases[name.casefold()][1] for name in required):
            raise ValueError('Source engine ZIP lacks required native Office/Base runtime files')
        destination.mkdir(parents=True)
        for member in members:
            target = destination/archive_path(member.filename)
            if member.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as reader, target.open('xb') as writer:
                    size = 0
                    while chunk := reader.read(1024*1024):
                        size += len(chunk)
                        if size > member.file_size: raise ValueError('Source engine ZIP member exceeds declared size')
                        writer.write(chunk)
                    if size != member.file_size: raise ValueError('Source engine ZIP member size mismatch')
    validate_source_build_runtime(destination, proof, architecture=architecture, runtime=runtime)
    with receipt.open('rb') as reader, (destination/'opengeul-source-build.json').open('xb') as writer:
        shutil.copyfileobj(reader, writer)
    return destination


def extract_hwp_zip(archive: Path, destination: Path, *, limit: int = 512 * 1024 * 1024) -> None:
    if destination.exists() or destination.is_symlink(): raise ValueError('Output already exists')
    with zipfile.ZipFile(archive) as source:
        seen = set(); total = 0
        members = source.infolist()
        if not members or len(members) > 10000: raise ValueError('Invalid HWP archive member count')
        for member in members:
            # ZipInfo may normalize Windows separators or truncate at NUL.
            # Admit the raw central-directory name before using its normalized name.
            archive_path(member.orig_filename)
            name = archive_path(member.filename)
            if name.casefold() in seen: raise ValueError('Archive path collision')
            seen.add(name.casefold())
            if stat.S_ISLNK(member.external_attr >> 16): raise ValueError('Archive symlink is forbidden')
            total += member.file_size
            if member.file_size > 128 * 1024 * 1024 or total > limit:
                raise ValueError('HWP archive exceeds extraction bound')
        if 'opengeul.exe' not in seen: raise ValueError('HWP archive has no root editor')
        destination.mkdir(parents=True)
        for member in members:
            target = destination / archive_path(member.filename)
            if member.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as reader, target.open('xb') as writer:
                    while chunk := reader.read(1024 * 1024): writer.write(chunk)


def normalize_admin_runtime(source: Path, destination: Path, *, admin_metadata: bool = False, msi_name: str | None = None) -> Path:
    """Project INSTALLLOCATION content from the pinned MSI's admin source image.

    Windows honors DefaultDir's source name '.' and places program at TARGETDIR;
    System/System64 and the administrative MSI are not application-root files.
    The original extraction remains unchanged, including non-native merge modules.
    """
    directories = {'help', 'presets', 'program', 'readmes', 'share'}
    files = {'CREDITS.fodt', 'LICENSE.html', 'NOTICE', 'license.txt', 'update-settings.ini'}
    allowed = directories | files
    administrative = {'System', 'System64', 'Fonts', 'Windows', 'Templates'} if admin_metadata else set()
    if admin_metadata and msi_name:
        if Path(msi_name).name != msi_name or not msi_name.lower().endswith('.msi'):
            raise ValueError('Invalid administrative MSI filename')
        administrative.add(msi_name)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Normalized MSI runtime output already exists')
    if (source.is_symlink() or not source.is_dir() or source.resolve() == destination.absolute()
            or source.resolve() in destination.absolute().parents):
        raise ValueError('MSI runtime projection requires separate regular directories')
    entries = {path.name: path for path in source.iterdir()}
    unexpected = set(entries) - allowed - administrative
    if unexpected:
        raise ValueError('Unexpected MSI runtime root entries: '+', '.join(sorted(unexpected)))
    missing = allowed - entries.keys()
    if missing:
        raise ValueError('Missing pinned MSI application root entries: '+', '.join(sorted(missing)))
    for name, path in entries.items():
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('MSI runtime root symlink/reparse point: '+name)
        if name not in allowed:
            continue
        if (name in directories and not path.is_dir()) or (name in files and not path.is_file()):
            raise ValueError('Invalid MSI application root entry kind: '+name)
        for child in path.rglob('*') if path.is_dir() else ():
            child_info = child.lstat()
            if child.is_symlink() or getattr(child_info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('MSI runtime symlink/reparse point: '+str(child))
            if not (child.is_dir() or child.is_file()):
                raise ValueError('MSI runtime special file: '+str(child))
    destination.mkdir(parents=True)
    for name in sorted(allowed):
        if name in directories:
            shutil.copytree(entries[name], destination/name)
        else:
            shutil.copy2(entries[name], destination/name)
    return destination


def extract_msi(archive: Path, destination: Path, *, architecture: str = 'x64') -> Path:
    native_machine(architecture)
    if os.name != 'nt': raise ValueError('GUI MSI extraction requires Windows')
    if destination.exists(): raise ValueError('MSI extraction output already exists')
    destination.mkdir(parents=True)
    log = destination.parent / (destination.name + '.msi.log')
    result = subprocess.run(['msiexec.exe', '/a', str(archive.resolve()), '/qn', '/norestart',
                             'TARGETDIR=' + str(destination.resolve()), '/L*v', str(log.resolve())],
                            timeout=300, check=False)
    if result.returncode != 0: raise ValueError(f'MSI extraction failed ({result.returncode}); see {log.name}')
    matches = list(destination.glob('**/program/soffice.exe'))
    if len(matches) != 1: raise ValueError('MSI must contain one Office runtime')
    runtime = matches[0].parent.parent
    if not (runtime/'program/python.exe').is_file(): raise ValueError('Runtime has no bundled UNO Python')
    runtime = normalize_admin_runtime(runtime, destination.with_name(destination.name+'-runtime'),
                                      admin_metadata=runtime == destination, msi_name=archive.name)
    # Administrative images may flatten ARM64 and AMD64 merge-module rows onto
    # the same System64 filenames. Recover the exact native File IDs from
    # the authenticated original cabinet instead of trusting those paths.
    try:
        from suite.msi_cab import recover_crt
    except ModuleNotFoundError:
        from msi_cab import recover_crt
    crt = destination.with_name(destination.name + '-native-crt')
    crt.mkdir(exist_ok=False)
    recovered = recover_crt(archive, crt/'System64', architecture=architecture)
    files = stage_msi_dependencies(crt, runtime, architecture=architecture)
    for name, record in recovered.items():
        files['program/'+name].update(fileId=record['fileId'], cabinet=record['cabinet'])
    receipt = runtime/'opengeul-msi-dependencies.json'
    with receipt.open('x', encoding='utf-8') as stream:
        marker = 'amd64' if architecture == 'x64' else 'arm64'
        json.dump({'schemaVersion': 1, 'architecture': architecture, 'inputMsiSha256': sha256(archive),
                   'recovery': 'embedded-'+marker+'-file-ids', 'files': files}, stream, indent=2)
        stream.write('\n')
    return runtime


def stage_msi_dependencies(extraction_root: Path, runtime_root: Path, *, architecture: str = 'x64') -> dict:
    """Copy the pinned MSI's native VC++ DLLs into its scratch runtime.

    Administrative extraction puts these files in System64 rather than program.
    Validate every source and existing destination before copying any dependency;
    never use the sibling System directory containing x86 binaries.
    """
    machine = native_machine(architecture)
    try:
        from suite.payload import _pe
    except ModuleNotFoundError:
        from payload import _pe

    def regular(path, *, directory=False):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('MSI dependency symlink/reparse point: '+str(path))
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise ValueError('MSI dependency requires a regular '+('directory' if directory else 'file'))
        return info

    source = extraction_root/'System64'
    target = runtime_root/'program'
    for directory in (extraction_root, source, runtime_root, target):
        regular(directory, directory=True)
    candidates = {}
    for path in source.iterdir():
        name = path.name.lower()
        if not re.fullmatch(r'(?:msvcp140[^/]*|vcruntime140[^/]*|concrt140)\.dll', name):
            continue
        if name in candidates:
            raise ValueError('MSI dependency source case collision: '+name)
        candidates[name] = path
    expected = frozenset(crt_names(architecture))
    if architecture == 'arm64' and candidates.keys() - expected:
        raise ValueError('Unexpected ARM64 CRT family members: '+', '.join(sorted(candidates.keys() - expected)))
    missing = expected - candidates.keys()
    if missing:
        raise ValueError('Missing pinned MSI System64 dependencies: '+', '.join(sorted(missing)))
    existing = {}
    for path in target.iterdir():
        name = path.name.lower()
        if architecture == 'arm64' and is_vc_crt_file(name) and name not in expected:
            raise ValueError('Unexpected ARM64 CRT destination family member: '+name)
        if name in candidates:
            if name in existing:
                raise ValueError('MSI dependency destination case collision: '+name)
            existing[name] = path
    result = {}
    for name, path in sorted(candidates.items()):
        info = regular(path)
        _pe(path, architecture=architecture)
        with path.open('rb') as stream:
            stream.seek(60)
            pe_offset = struct.unpack('<I', stream.read(4))[0]
            stream.seek(pe_offset+4)
            if struct.unpack('<H', stream.read(2))[0] != machine:
                raise ValueError('MSI dependency must use native '+architecture+' architecture: '+name)
        digest = sha256(path)
        if name in existing:
            other = existing[name]
            other_info = regular(other)
            if other_info.st_size != info.st_size or sha256(other) != digest:
                raise ValueError('Conflicting runtime MSI dependency: '+name)
        result['program/'+name] = {'source': 'System64/'+path.name,
                                  'size': info.st_size, 'sha256': digest}
    # All dependency and collision checks have succeeded before any runtime write.
    for name, path in sorted(candidates.items()):
        if name not in existing:
            with path.open('rb') as reader, (target/name).open('xb') as writer:
                shutil.copyfileobj(reader, writer)
            record = result['program/'+name]
            if (target/name).stat().st_size != record['size'] or sha256(target/name) != record['sha256']:
                raise ValueError('Staged MSI dependency differs from its input: '+name)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--shell', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--architecture', choices=tuple(NATIVE_MACHINES), default='x64')
    parser.add_argument('--engine-archive', type=Path,
                        help='Locally authenticated source-built engine ZIP (source-built-zip lock only)')
    parser.add_argument('--engine-receipt', type=Path,
                        help='Exact source-build-receipt.json pinned by the committed runtime lock')
    args = parser.parse_args()
    lock_name = 'runtime.lock.json' if args.architecture == 'x64' else 'runtime.arm64.lock.json'
    lock = json.loads((ROOT/'suite/config'/lock_name).read_text(encoding='utf-8'))
    if lock.get('architecture') != args.architecture:
        raise ValueError('Runtime lock architecture does not match requested native architecture')
    runtime_format = lock['runtime'].get('format', 'msi')
    if runtime_format == 'source-built-zip':
        if (args.engine_archive is None or args.engine_receipt is None
                or not args.engine_archive.exists() or not args.engine_receipt.exists()):
            raise ValueError('Authenticated source-build artifact needed: supply --engine-archive with the local '
                             'inner engine ZIP and --engine-receipt with its externally pinned source-build-receipt.json')
        runtime = extract_source_engine_zip(args.engine_archive, args.work/'source-engine-runtime',
                                            runtime=lock['runtime'], receipt=args.engine_receipt,
                                            architecture=args.architecture)
    elif runtime_format == 'msi':
        if args.engine_archive is not None or args.engine_receipt is not None:
            raise ValueError('Engine archive/receipt options require a source-built-zip runtime lock')
        msi = download_locked(lock['runtime'], args.work/'inputs/office.msi')
    else:
        raise ValueError('Unsupported runtime format: '+str(runtime_format))
    hwp = download_locked(lock['hwp'], args.work/'inputs/hwp.zip')
    if runtime_format == 'msi':
        runtime = extract_msi(msi, args.work/'msi', architecture=args.architecture)
    from package import assemble
    assemble(runtime=runtime, hwp=hwp, shell=args.shell, output=args.output, lock=lock)
    print('OpenGeul Office package prepared and verified:', args.output)


if __name__ == '__main__': main()
