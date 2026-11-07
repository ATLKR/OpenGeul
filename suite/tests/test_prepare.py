"""Fresh-path packaging must reject bad inputs before touching a runtime."""
import hashlib
import copy
import io
import importlib.util
import inspect
import json
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from suite.tests.test_payload import pe

VC_DLLS = ('concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
           'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll',
           'vcruntime140_1.dll', 'vcruntime140_threads.dll')
ARM_VC_DLLS = tuple(name for name in VC_DLLS if name != 'vcruntime140_1.dll')
SOURCE_CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'

ROOT = Path(__file__).resolve().parents[2]


def source_build_fixture(root):
    """A pinned receipt uses the source driver's actual JSON field names."""
    archive = root/'engine.zip'
    metadata = {'program/version.ini': ('[Version]\nbuildid='+SOURCE_CORE+'\nVendor=The Document Foundation\n').encode(),
                'program/setup.ini': ('[Bootstrap]\nbuildid='+SOURCE_CORE+'\n').encode()}
    with zipfile.ZipFile(archive, 'w') as source:
        for name in ('soffice.exe', 'soffice.bin', 'python.exe', 'pyuno.pyd',
                     'ifbclient.dll', 'Engine12.dll', 'intl/fbintl.dll'):
            source.writestr('program/'+name, pe(0xaa64))
        source.writestr('LICENSE.html', b'Original upstream license')
        for name, raw in metadata.items(): source.writestr(name, raw)
        for name in ARM_VC_DLLS: source.writestr('program/'+name, pe(0xaa64, dll=True))
        source.writestr('share/readme/Microsoft-VC145-redistribution.html', b'Official VS2026 redistribution terms')
    runtime = {'format': 'source-built-zip', 'version': '26.8.1.1',
               'url': 'https://example.org/engine.zip', 'size': archive.stat().st_size,
               'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
               'sourceUrl': 'https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz',
               'sourceSha256': '296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785',
               'sourceCoreCommit': SOURCE_CORE,
               'sourceBuild': {'receiptSha256': '0'*64, 'sourceCommit': 'a'*40,
                               'runId': 123, 'artifactId': 456, 'artifactSha256': '2'*64,
                               'patchManifestSha256': '3'*64}}
    native = {'processMachine': 0, 'nativeMachine': 0xaa64}
    receipt = {'schemaVersion': 1, 'kind': 'native-office-engine-source-build',
               'phase': 'Full', 'architecture': 'arm64', 'status': 'native-engine-source-build-qualified',
               'passed': True, 'fullEngineQualified': True, 'guiVerified': False, 'stage': 'complete',
               'sourceCommit': 'a'*40, 'sourceTree': 'b'*40, 'sourceRun': 123, 'runAttempt': 1,
               'sourcePortManifestSha256': '3'*64, 'driverSha256': '4'*64,
               'host': dict(native, isWindows=True, controllerPid=1),
               'sourcePin': {'url': runtime['sourceUrl'], 'sha256': runtime['sourceSha256'],
                             'version': runtime['version'], 'size': 302435508, 'coreCommit': SOURCE_CORE},
               'configuration': {'OS': 'WNT', 'COM': 'MSC', 'CPUNAME': 'AARCH64',
                                 'HOST_PLATFORM': 'aarch64-pc-cygwin', 'BUILD_PLATFORM': 'aarch64-pc-cygwin',
                                 'ENABLE_FIREBIRD_SDBC': 'TRUE', 'CROSS_COMPILING': '', 'SYSTEM_FIREBIRD': '',
                                 'PKGFORMAT': 'archive', 'ENABLE_ONLINE_UPDATE': '',
                                 'ENABLE_ONLINE_UPDATE_MAR': '', 'ENABLE_BREAKPAD': '',
                                 'BUILD_TYPE': 'FIREBIRD LIBATOMIC_OPS LIBTOMMATH'},
               'baseProof': {'schemaVersion': 1, 'passed': True, 'guiVerified': False,
                             'independentReopenVerified': True,
                             'nativeProcesses': [dict(native, pid=10, role='uno-python'),
                                  dict(native, pid=11, role='uno-host', phase='create', jobOwned=True,
                                       image='C:\\build\\instdir\\program\\soffice.bin', creationTime=100),
                                  dict(native, pid=12, role='uno-host', phase='reopen', jobOwned=True,
                                       image='C:\\build\\instdir\\program\\soffice.bin', creationTime=200)],
                             'rows': [{'id': 1, 'text': 'Engine-OpenGeul-base 한글', 'amount': 42}],
                             'odb': 'C:\\build\\proof.odb', 'odbSha256': '5'*64},
               'artifact': {'path': str(archive), 'size': runtime['size'], 'sha256': runtime['sha256']}}
    files = {name: dict(originalBuildId='a'*40, buildid=SOURCE_CORE, corrected=True,
                       beforeSha256=hashlib.sha256(raw.replace(SOURCE_CORE.encode(), b'a'*40)).hexdigest(),
                       sha256=hashlib.sha256(raw).hexdigest()) for name, raw in metadata.items()}
    receipt['runtimeBuildIdentity'] = dict(schemaVersion=1,
        mechanism='explicit-generated-config-correction-from-authenticated-source-pin',
        expectedBuildId=SOURCE_CORE, sourceArchiveUrl=runtime['sourceUrl'],
        sourceArchiveSha256=runtime['sourceSha256'], sourceArchiveSize=302435508, files=files,
        finalVerification=dict(passed=True, expectedBuildId=SOURCE_CORE,
            files={name:dict(buildid=SOURCE_CORE, sha256=item['sha256']) for name,item in files.items()}))
    source_directory = 'C:\\VS\\VC\\Redist\\MSVC\\14.50.35717\\arm64\\Microsoft.VC145.CRT'
    files = [{'name': name, 'sourcePath': source_directory+'\\'+name, 'machine': 0xaa64,
              'size': len(pe(0xaa64, dll=True)), 'sha256': hashlib.sha256(pe(0xaa64, dll=True)).hexdigest(),
              'signature': {'status': 'Valid', 'signerSubject': 'CN=Microsoft, O=Microsoft Corporation, C=US',
                  'signerThumbprint': 'a'*40, 'signerIssuer': 'Microsoft CA',
                  'fileVersion': '14.50.35717.0', 'productVersion': '14.50.35717.0',
                  'fileVersionParts': [14, 50, 35717, 0], 'productVersionParts': [14, 50, 35717, 0],
                  'companyName': 'Microsoft Corporation', 'originalFilename': name}} for name in ARM_VC_DLLS]
    receipt['crtPreflight'] = {'schemaVersion': 1, 'architecture': 'arm64', 'toolset': 'v145',
        'compilerToolsVersion': '14.50.35717', 'minimumRuntimeVersion': '14.50.35717.0',
        'sourceDirectory': source_directory, 'files': files}
    receipt['appLocalCrt'] = {'schemaVersion': 1, 'architecture': 'arm64', 'toolset': 'v145', 'sourceDirectory': source_directory,
        'programDirectory': 'C:\\build\\instdir\\program',
        'files': [{'source': copy.deepcopy(file), 'destination': 'C:\\build\\instdir\\program\\'+file['name'],
                   'alreadyIdentical': False, 'copiedSha256': file['sha256']} for file in files],
        'redistributionTerms': {'path': 'C:\\build\\instdir\\share\\readme\\Microsoft-VC145-redistribution.html',
            'sha256': hashlib.sha256(b'Official VS2026 redistribution terms').hexdigest()}}
    receipt['crtRedistributionTerms'] = {'url': 'https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution',
        'path': 'C:\\evidence\\terms.html', 'size': len(b'Official VS2026 redistribution terms'),
        'sha256': hashlib.sha256(b'Official VS2026 redistribution terms').hexdigest()}
    receipt['crtImportClosure'] = dict(schemaVersion=1, architecture='arm64', passed=True,
        requiredCrtFiles=list(ARM_VC_DLLS), checkedPeCount=15, imports=[])
    receipt_path = root/'source-build-receipt.json'
    pin_source_receipt(runtime, receipt_path, receipt)
    return archive, runtime, receipt_path, receipt


def pin_source_receipt(runtime, path, receipt):
    path.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
    runtime['sourceBuild']['receiptSha256'] = hashlib.sha256(path.read_bytes()).hexdigest()


def x64_source_build_fixture(root, *, runtime_templates=False):
    """Synthetic v2 unit evidence, never a qualified runtime lock or build result."""
    archive, runtime, receipt_path, proof = source_build_fixture(root)
    manifest_path = ROOT/'suite/engine-build/source-build.json'
    manifest = json.loads(manifest_path.read_text())
    policy_sha = 'ba8d627adefb2dfe90e048546f6f55d54c8e739d0f4f21afbe8a556af54768bc'
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    program = 'C:\\build\\instdir\\program'
    compiler_root = 'C:\\VS\\VC\\Tools\\MSVC\\14.44.35207'
    sdk_root = 'C:\\SDK'; sdk_version = '10.0.26100.0'
    native = dict(processMachine=0, nativeMachine=0x8664)
    with zipfile.ZipFile(archive) as original:
        entries = {info.filename: original.read(info) for info in original.infolist()
                   if not info.filename.endswith('.dll') and not info.filename.endswith('/fbintl.dll')
                   and not info.filename.startswith('share/readme/')}
    for name in ('soffice.exe','soffice.bin','python.exe','pyuno.pyd','ifbclient.dll','Engine12.dll','intl/fbintl.dll'):
        entries['program/'+name] = pe(0x8664, dll=name.endswith(('.dll','.pyd')))
    from suite.tests.test_pe_imports import imports_pe
    winacc=imports_pe(('kernel32.dll',))
    import struct
    struct.pack_into('<H',winacc,0x84,0x8664)
    entries['program/winaccessibility.dll'] = bytes(winacc)
    entries['program/policy.1.0.cli_cppuhelper.dll'] = pe(0x14c, managed=True, dll=True)
    for name in VC_DLLS: entries['program/'+name] = pe(0x8664,dll=True)
    terms = b'Official VS2022 redistribution terms'
    entries['share/readme/Microsoft-VC143-redistribution.html'] = terms
    with zipfile.ZipFile(archive,'w') as target:
        for name,raw in entries.items(): target.writestr(name,raw)
    runtime.update(size=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    runtime['sourceBuild']['patchManifestSha256'] = manifest_sha
    runtime['sourceBuild'].update(sourceTree='b'*40,driverSha256='4'*64,nativeTargetsSha256=policy_sha)
    proof.update(schemaVersion=2,architecture='x64',acceptanceEligible=True,
                 sourcePortManifestSha256=manifest_sha,nativeTargetsSha256=policy_sha,
                 artifact=dict(path='C:\\evidence\\OpenGeul-Office-engine-x64.zip',size=runtime['size'],sha256=runtime['sha256']),
                 host=dict(native,isWindows=True,controllerPid=1),
                 configurationSha256='6'*64,configureArgumentsSha256='7'*64,
                 sourceRecipeChecksExecuted=True)
    proof['configuration'].update(CPUNAME='X86_64',HOST_PLATFORM='x86_64-pc-cygwin',
                                  BUILD_PLATFORM='x86_64-pc-cygwin',BUILD_TYPE='FIREBIRD LIBTOMMATH',
                                  VCTOOLSET='v143',VCVER='17.0',COMPATH=compiler_root,
                                  WINDOWS_SDK_HOME=sdk_root,WINDOWS_SDK_VERSION=sdk_version)
    proof['workflowBinding'] = dict(workflow='.github/workflows/office-native-engine-x64.yml',
        workflowRef='ATLKR/OpenGeul/.github/workflows/office-native-engine-x64.yml@refs/heads/work/opengeul-office-native-engine-x64',
        ref='refs/heads/work/opengeul-office-native-engine-x64',job='native-firebird-and-office-x64',
        sourceCommit=proof['sourceCommit'],sourceTree=proof['sourceTree'],sourceRun=123,runAttempt=1)
    tools={}
    for name in ('cl','link','lib'):
        tools[name]=dict(path=compiler_root+'\\bin\\Hostx64\\x64\\'+name+'.exe',machine=0x8664,
            role='nativeCompilerTool',tool=name,size=1024,sha256='8'*64,
            version=('19' if name=='cl' else '14')+'.44.35229.0')
    metadata_raw=b'14.44.35207\r\n'
    compiler=dict(architecture='x64',compilerYear='2022',toolset='v143',installationPath='C:\\VS',
        installationVersion='17.14.37827.9',compilerRoot=compiler_root,compilerToolsVersion='14.44.35207',
        minimumRuntimeVersion='14.44.35207.0',runtimeFloorBasis='selected-msvc-package-v1',
        toolsetMetadata=dict(path='C:\\VS\\VC\\Auxiliary\\Build\\Microsoft.VCToolsVersion.default.txt',
            size=len(metadata_raw),sha256=hashlib.sha256(metadata_raw).hexdigest(),version='14.44.35207'),tools=tools)
    sdk_files=[]
    for relative in (f'Include/{sdk_version}/um/Windows.h',f'Include/{sdk_version}/shared/sdkddkver.h',
                     f'Include/{sdk_version}/ucrt/stdio.h',f'Lib/{sdk_version}/um/x64/kernel32.lib',
                     f'Lib/{sdk_version}/ucrt/x64/ucrt.lib'):
        sdk_files.append(dict(path=sdk_root+'\\'+relative.replace('/','\\'),size=100,sha256='9'*64))
    proof['nativePreflight']=dict(schemaVersion=1,passed=True,architecture='x64',compiler=compiler,
        sdk=dict(root=sdk_root,version=sdk_version,architecture='x64',files=sdk_files,
                 resourceCompiler=dict(path=sdk_root+'\\bin\\'+sdk_version+'\\x64\\rc.exe',
                     machine=0x8664,role='nativeX64',size=100,sha256='a'*64)),
        archive=dict(path='C:\\probe\\owned.lib',size=100,sha256='b'*64,machines=[0x8664]),
        executable=dict(path='C:\\probe\\probe.exe',size=100,sha256='c'*64,machine=0x8664,role='nativeX64'),
        nativeProcess=dict(native,compilerFullVersion=194435229,libraryValue=42),
        commands={name:dict(exitCode=0,receipt='C:\\evidence\\'+name+'.json',
            stdout='C:\\evidence\\'+name+'.stdout.log',stderr='C:\\evidence\\'+name+'.stderr.log')
            for name in ('member','probe','archive','link','run')})
    proof['configuredToolchain']=dict(matched=True,compilerRoot=compiler_root,toolset='v143',
                                     sdkRoot=sdk_root,sdkVersion=sdk_version)
    proof['javaTools']=dict(jdk=dict(home='C:\\JDK',javaVersion='21.0.8',selection='JAVA_HOME_21_X64',releaseSha256='d'*64,
        nativeFiles=[dict(path='C:\\JDK\\'+name.replace('/','\\'),machine=0x8664,role='nativeX64',size=100,sha256='e'*64)
            for name in ('bin/java.exe','bin/javac.exe','bin/server/jvm.dll','bin/jawt.dll')],
        importLibraries=[dict(path='C:\\JDK\\lib\\'+name,size=100,sha256='f'*64,machines=[0x8664])
            for name in ('jvm.lib','jawt.lib')]))
    proof['buildBudget']=dict(startedUtc='2026-11-07T00:00:00.0000000Z',deadlineUtc='2026-11-07T05:30:00.0000000Z',
        workflowDeadlineUtc='2026-11-07T05:30:00.0000000Z',maximumMinutes=330,timeoutMilliseconds=19800000,elapsedSeconds=60.0)
    proof['finishedUtc']='2026-11-07T00:01:00.0000000Z'
    proof['baseProof']['schemaVersion']=2
    for process in proof['baseProof']['nativeProcesses']: process.update(native)
    retirements=[]
    for host in proof['baseProof']['nativeProcesses'][1:]:
        member=dict(pid=host['pid'],creationTime=host['creationTime'],handleValue=host['pid']+100,
                    image=host['image'],alive=True,exitCode=259,error=None)
        final=dict(member,alive=False,exitCode=0)
        retirements.append(dict(phase=host['phase'],handlesClosed=True,cleanup=dict(schemaVersion=1,
            kind='owned-engine-job-cleanup',gracefulQualified=True,forcedTermination=False,
            jobEmptyVerified=True,finalJobPids=[],launcherExitCode=0,errors=[],jobHandleValue=42,
            expectedEngineImage=host['image'],initialMembers=[member],finalMembers=[final])))
    proof['baseProof']['retirement']=retirements
    source_dir='C:\\VS\\VC\\Redist\\MSVC\\14.44.35112\\x64\\Microsoft.VC143.CRT'
    crt=[]
    for name in VC_DLLS:
        old=copy.deepcopy(proof['crtPreflight']['files'][0])
        old.update(name=name,sourcePath=source_dir+'\\'+name,machine=0x8664,
                   size=len(entries['program/'+name]),sha256=hashlib.sha256(entries['program/'+name]).hexdigest())
        old['signature'].update(originalFilename=name,fileVersion='14.44.35211.0',productVersion='14.44.35211.0',
                                fileVersionParts=[14,44,35211,0],productVersionParts=[14,44,35211,0])
        crt.append(old)
    proof['crtPreflight']=dict(schemaVersion=1,architecture='x64',toolset='v143',
        compilerRoot=compiler_root,compilerToolsVersion='14.44.35207',minimumRuntimeVersion='14.44.35207.0',
        redistRoot='C:\\VS\\VC\\Redist\\MSVC',redistVersionDirectory='14.44.35112',
        redistFamily='Microsoft.VC143.CRT',selectionBasis='actual-signed-crt-files-v1',
        selectedFileVersionFloor='14.44.35211.0',sourceDirectory=source_dir,files=crt)
    proof['nativePreflight']['crt']=copy.deepcopy(proof['crtPreflight'])
    proof['appLocalCrt']=dict(schemaVersion=1,architecture='x64',toolset='v143',sourceDirectory=source_dir,
        programDirectory=program,files=[dict(source=copy.deepcopy(item),destination=program+'\\'+item['name'],
            alreadyIdentical=False,copiedSha256=item['sha256']) for item in crt],
        redistributionTerms=dict(path='C:\\build\\instdir\\share\\readme\\Microsoft-VC143-redistribution.html',
                                 sha256=hashlib.sha256(terms).hexdigest()))
    proof['crtRedistributionTerms']=dict(url='https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution',
        path='C:\\evidence\\terms.html',size=len(terms),sha256=hashlib.sha256(terms).hexdigest())
    proof['crtImportClosure']=dict(schemaVersion=1,architecture='x64',passed=True,
        requiredCrtFiles=list(VC_DLLS),checkedPeCount=18,imports=[])
    pin=manifest['winAccFocusOrder']
    proof['winAccFocusOrderSourcePatch']=dict(schemaVersion=1,kind='winacc-focus-order-source-patch',passed=True,
        coreCommit=SOURCE_CORE,path=pin['path'],beforeSha256=pin['sha256'],afterSha256=pin['afterSha256'],
        patchSha256=pin['patch']['sha256'],nativeBuildVerified=False,guiVerified=False,currentCiRootCauseConfirmed=False,
        sourceFiles=[dict(path=item['path'],beforeBytes=item['size'],
            afterBytes=pin['afterBytes'] if item['path']==pin['path'] else item['size'],
            beforeSha256=item['sha256'],afterSha256=pin['afterSha256'] if item['path']==pin['path'] else item['sha256'])
            for item in pin['sources']],evidence={})
    bootstrap=manifest['moduleBootstrap']
    proof['sourceHooks']=dict(kind='native-windows-common-source-hooks',architecture='x64',nativeBuildVerified=False,
        basePersistenceVerified=False,moduleBootstrap=dict(path=bootstrap['path'],beforeSha256=bootstrap['sha256'],
            afterSha256=bootstrap['afterSha256'],evidence={}))
    guarded=[manifest[key] for key in ('configureSource','sourceHook','icuBuildPath','zstdSourceLinks')]
    guarded += [manifest[key]['recipe'] for key in ('mddsEquality','pythonNativeHost','atlNativePaths')]
    guarded += manifest['atlConsumerNativePaths']['recipes']+[manifest['harfbuzzNativeMesonPaths']['recipe']]
    proof['sourceRecipeProof']=dict(schemaVersion=1,kind='native-engine-source-recipe-install',architecture='x64',
        recipeId='windows-x64-common-v2',policySha256=policy_sha,manifestSha256=manifest_sha,
        recipeSha256='d85a584577bea857fc58ae8afc30fe729190aa02f2fb414f670a5693bc5d23ec',
        hookOrder=['moduleBootstrap','winAccFocusOrder'],nativeBuildVerified=False,fullEngineQualified=False,
        acceptanceEligible=False,guiVerified=False,
        armGuardedSources=[dict(path=item['path'],beforeSha256=item['sha256'],sha256=item['sha256'],unchanged=True)
                           for item in guarded])
    inventory=[]
    for name,raw in entries.items():
        if not raw.startswith(b'MZ'): continue
        managed=name.endswith('policy.1.0.cli_cppuhelper.dll')
        inventory.append(dict(path='C:\\build\\instdir\\'+name.replace('/','\\'),
            machine=0x14c if managed else 0x8664,role='managedAnyCpu' if managed else 'nativeX64',
            size=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
    proof['winAccBinary']=dict(path='program/winaccessibility.dll',machine=0x8664,role='nativeX64',
        size=len(entries['program/winaccessibility.dll']),sha256=hashlib.sha256(entries['program/winaccessibility.dll']).hexdigest(),
        imports=dict(normal=['kernel32.dll'],delay=[]))
    for item in inventory:
        if item['path'].endswith('winaccessibility.dll'): item['imports']=copy.deepcopy(proof['winAccBinary']['imports'])
    # Receipt identity tests can use the real reviewed template pins without
    # treating synthetic PE bytes as those upstream executable templates.
    from suite.payload import COMPANION_PE_ADMISSIONS
    for name,pin in COMPANION_PE_ADMISSIONS.items():
        if pin['role']=='pythonLauncherTemplate':
            relative=name.removeprefix('Office/')
            raw=pe(pin['machine']) if runtime_templates else None
            if raw is not None:entries[relative]=raw
            inventory.append(dict(path='C:\\build\\instdir\\'+relative.replace('/','\\'),
                machine=pin['machine'],role=pin['role'],size=len(raw) if raw is not None else 100,
                sha256=hashlib.sha256(raw).hexdigest() if raw is not None else pin['sha256']))
    proof.update(productInventory=inventory,productPeCount=len(inventory),
        nativePeCount=sum(item['role']=='nativeX64' for item in inventory),managedAnyCpuCount=1,pinnedTemplateCount=10)
    proof['crtImportClosure']['checkedPeCount']=proof['nativePeCount']
    proof['externalSources']=dict(schemaVersion=1,pythonSourceVerified=True,
        archives=[dict(filename='Python-3.13.15.tar.xz',size=100,sha256='1'*64,pinVariable='PYTHON_TARBALL')],
        embeddedPythonWheels=[dict(path='Lib/ensurepip/_bundled/pip-unit.whl',size=100,sha256='2'*64,
            provenance='unpacked authenticated Python source plus source-controlled patches')])
    proof['installedRuntimeStage']=dict(passed=True,runtimeRoot='C:\\build\\instdir',fileCount=100,archiveCount=3,
        requiredHelpLanguages=['en-US','ko'],receipt=dict(path='C:\\evidence\\installed-runtime-stage.json',bytes=100,sha256='3'*64))
    if runtime_templates:
        with zipfile.ZipFile(archive,'w') as target:
            for name,raw in entries.items():target.writestr(name,raw)
        runtime.update(size=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        proof['artifact'].update(size=runtime['size'],sha256=runtime['sha256'])
        proof['crtImportClosure']['checkedPeCount']=proof['nativePeCount']
    pin_source_receipt(runtime,receipt_path,proof)
    return archive,runtime,receipt_path,proof


def synthetic_source_template_pins(proof):
    """Expected identities for explicitly synthetic launcher-byte unit fixtures."""
    return {PureWindowsPath(item['path']).relative_to('C:\\build\\instdir').as_posix():
            {key:item[key] for key in ('machine','role','sha256')}
            for item in proof['productInventory'] if item['role']=='pythonLauncherTemplate'}


def implementation():
    path = ROOT / 'suite/prepare.py'
    assert path.is_file(), 'Suite preparation implementation is required'
    spec = importlib.util.spec_from_file_location('suite_prepare_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrepareTests(unittest.TestCase):
    def app_root_fixture(self, runtime):
        for name in ('help', 'presets', 'program', 'readmes', 'share'):
            (runtime/name).mkdir(parents=True, exist_ok=True)
        for name in ('CREDITS.fodt', 'LICENSE.html', 'NOTICE', 'license.txt', 'update-settings.ini'):
            (runtime/name).write_bytes(('original '+name).encode())
        for name in ('soffice.exe', 'python.exe'):
            (runtime/'program'/name).write_bytes(pe())

    def test_flat_admin_image_projects_only_official_runtime_root_without_modifying_source(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'admin'; source.mkdir()
            self.app_root_fixture(source)
            for name, machine in (('System', 0x14c), ('System64', 0xaa64)):
                (source/name).mkdir(); (source/name/'concrt140.dll').write_bytes(pe(machine, dll=True))
            (source/'Fonts').mkdir(); (source/'Fonts/font.txt').write_bytes(b'admin font payload')
            (source/'input.msi').write_bytes(b'original MSI copy')
            before = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            target = Path(folder)/'runtime'
            module.normalize_admin_runtime(source, target, admin_metadata=True, msi_name='input.msi')
            self.assertEqual({p.name for p in target.iterdir()}, {
                'help', 'presets', 'program', 'readmes', 'share', 'CREDITS.fodt',
                'LICENSE.html', 'NOTICE', 'license.txt', 'update-settings.ini'})
            self.assertEqual((target/'NOTICE').read_bytes(), b'original NOTICE')
            self.assertEqual(before, {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_nested_source_root_is_copied_to_fresh_runtime_without_including_admin_siblings(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'admin/LibreOffice'; self.app_root_fixture(source)
            (source.parent/'System').mkdir(); (source.parent/'System/concrt140.dll').write_bytes(pe(0x14c, dll=True))
            target = Path(folder)/'runtime'
            module.normalize_admin_runtime(source, target)
            self.assertTrue((target/'program/soffice.exe').is_file())
            self.assertFalse((target/'System').exists())
            with self.assertRaises(ValueError): module.normalize_admin_runtime(source, target)

    def test_unknown_admin_root_entry_is_rejected_before_projection(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'admin'; self.app_root_fixture(source)
            (source/'unexpected.dll').write_bytes(pe(0x14c, dll=True))
            target = Path(folder)/'runtime'
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                module.normalize_admin_runtime(source, target, admin_metadata=True, msi_name='input.msi')
            self.assertFalse(target.exists())

    def test_msi_extraction_uses_exact_cabinet_members_instead_of_flattened_system64(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root/'input.msi'; archive.write_bytes(b'authenticated-msi')
            def admin(*args, **kwargs):
                self.app_root_fixture(root/'extracted')
                runtime = root/'extracted/program'
                (runtime/'soffice.exe').write_bytes(b'office')
                (runtime/'python.exe').write_bytes(b'python')
                raw = root/'extracted/System64'; raw.mkdir()
                for name in module.MSI_VC_DEPENDENCIES: (raw/name).write_bytes(b'flattened ARM64')
                x86 = root/'extracted/System'; x86.mkdir()
                (x86/'concrt140.dll').write_bytes(pe(0x14c, dll=True))
                (root/'extracted/input.msi').write_bytes(archive.read_bytes())
                return SimpleNamespace(returncode=0)
            def recover(msi, destination, *, architecture='x64'):
                self.assertEqual(architecture, 'x64')
                self.assertEqual(msi, archive)
                destination.mkdir()
                result = {}
                for name in module.MSI_VC_DEPENDENCIES:
                    destination.joinpath(name).write_bytes(pe(dll=True))
                    result[name] = {'path': destination/name, 'fileId': name+'_amd64.GUID', 'cabinet':'#official.cab'}
                return result
            with patch.object(module, 'os', SimpleNamespace(name='nt')), \
                 patch.object(module.subprocess, 'run', side_effect=admin), \
                 patch('suite.msi_cab.recover_crt', side_effect=recover) as recovered:
                runtime = module.extract_msi(archive, root/'extracted')
            self.assertEqual(recovered.call_count, 1)
            self.assertEqual(runtime, root/'extracted-runtime')
            self.assertFalse((runtime/'System').exists())
            self.assertFalse((runtime/'System64').exists())
            self.assertFalse((runtime/'input.msi').exists())
            self.assertEqual((root/'extracted/System/concrt140.dll').read_bytes(), pe(0x14c, dll=True))
            receipt = json.loads((runtime/'opengeul-msi-dependencies.json').read_text())
            self.assertEqual(receipt['inputMsiSha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
            for name in module.MSI_VC_DEPENDENCIES:
                self.assertEqual((runtime/'program'/name).read_bytes(), pe(dll=True))
                self.assertEqual(receipt['files']['program/'+name]['fileId'], name+'_amd64.GUID')

    def msi_fixture(self, folder):
        root = Path(folder)/'extract'
        runtime = root/'LibreOffice'
        (runtime/'program').mkdir(parents=True)
        (root/'System64').mkdir()
        (root/'System').mkdir()
        for name in VC_DLLS:
            (root/'System64'/name).write_bytes(pe(dll=True))
            (root/'System'/name).write_bytes(pe(0x14c, dll=True))
        return root, runtime

    def test_msi_dependencies_are_copied_original_and_receipted(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root, runtime = self.msi_fixture(folder)
            original = {name: (root/'System64'/name).read_bytes() for name in VC_DLLS}
            receipt = module.stage_msi_dependencies(root, runtime)
            self.assertEqual(set(receipt), {'program/'+name for name in VC_DLLS})
            for name, data in original.items():
                self.assertEqual((root/'System64'/name).read_bytes(), data)
                self.assertEqual((runtime/'program'/name).read_bytes(), data)
                self.assertEqual(receipt['program/'+name], {
                    'source': 'System64/'+name, 'size': len(data),
                    'sha256': hashlib.sha256(data).hexdigest()})

    def test_arm64_dependencies_are_staged_without_changing_original_bytes(self):
        module = implementation()
        self.assertIn('architecture', inspect.signature(module.stage_msi_dependencies).parameters)
        with tempfile.TemporaryDirectory() as folder:
            root, runtime = self.msi_fixture(folder)
            (root/'System64/vcruntime140_1.dll').unlink()
            for name in ARM_VC_DLLS:
                (root/'System64'/name).write_bytes(pe(0xAA64, dll=True))
            receipt = module.stage_msi_dependencies(root, runtime, architecture='arm64')
            for name in ARM_VC_DLLS:
                self.assertEqual((runtime/'program'/name).read_bytes(), pe(0xAA64, dll=True))
                self.assertEqual((root/'System64'/name).read_bytes(), pe(0xAA64, dll=True))
                self.assertEqual(receipt['program/'+name]['sha256'], hashlib.sha256(pe(0xAA64, dll=True)).hexdigest())

    def test_arm64_dependency_rejects_x64_x86_and_arm64ec_before_any_copy(self):
        module = implementation()
        self.assertIn('architecture', inspect.signature(module.stage_msi_dependencies).parameters)
        for machine in (0x8664, 0x14C, 0xA641):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as folder:
                root, runtime = self.msi_fixture(folder)
                (root/'System64/vcruntime140_1.dll').unlink()
                for name in ARM_VC_DLLS:
                    (root/'System64'/name).write_bytes(pe(0xAA64, dll=True))
                (root/'System64/vcruntime140_threads.dll').write_bytes(pe(machine, dll=True))
                with self.assertRaisesRegex(ValueError, 'arm64|architecture'):
                    module.stage_msi_dependencies(root, runtime, architecture='arm64')
                self.assertEqual([], list((runtime/'program').iterdir()))

    def test_arm64_staging_rejects_extra_one_even_if_marked_native_before_copy(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            root,runtime=self.msi_fixture(folder)
            for name in VC_DLLS:(root/'System64'/name).write_bytes(pe(0xaa64,dll=True))
            with self.assertRaisesRegex(ValueError,'family|Unexpected|unexpected'):
                module.stage_msi_dependencies(root,runtime,architecture='arm64')
            self.assertEqual([],list((runtime/'program').iterdir()))

    def test_arm64_staging_rejects_existing_extra_one_before_any_copy(self):
        module=implementation()
        for machine in (0xaa64,0x8664):
            with self.subTest(machine=machine),tempfile.TemporaryDirectory() as folder:
                root,runtime=self.msi_fixture(folder)
                (root/'System64/vcruntime140_1.dll').unlink()
                for name in ARM_VC_DLLS:(root/'System64'/name).write_bytes(pe(0xaa64,dll=True))
                extra=runtime/'program/vcruntime140_1.dll';raw=pe(machine,dll=True);extra.write_bytes(raw)
                with self.assertRaisesRegex(ValueError,'family|Unexpected|unexpected'):
                    module.stage_msi_dependencies(root,runtime,architecture='arm64')
                self.assertEqual([extra],list((runtime/'program').iterdir()))
                self.assertEqual(raw,extra.read_bytes())

    def test_unsupported_dependency_architecture_is_rejected_before_writing(self):
        module = implementation()
        self.assertIn('architecture', inspect.signature(module.stage_msi_dependencies).parameters)
        with tempfile.TemporaryDirectory() as folder:
            root, runtime = self.msi_fixture(folder)
            with self.assertRaisesRegex(ValueError, 'architecture'):
                module.stage_msi_dependencies(root, runtime, architecture='x86')
            self.assertEqual([], list((runtime/'program').iterdir()))

    def test_missing_x64_dependency_never_falls_back_to_system_x86_or_writes(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root, runtime = self.msi_fixture(folder)
            (root/'System64/vcruntime140_1.dll').unlink()
            with self.assertRaisesRegex(ValueError, 'missing|Missing'):
                module.stage_msi_dependencies(root, runtime)
            self.assertEqual(list((runtime/'program').iterdir()), [])

    def test_conflicting_existing_runtime_dll_is_preserved_before_any_copy(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root, runtime = self.msi_fixture(folder)
            target = runtime/'program/vcruntime140_threads.dll'
            target.write_bytes(b'preserve conflicting user bytes')
            with self.assertRaisesRegex(ValueError, 'conflict|Conflict'):
                module.stage_msi_dependencies(root, runtime)
            self.assertEqual(list((runtime/'program').iterdir()), [target])
            self.assertEqual(target.read_bytes(), b'preserve conflicting user bytes')

    def test_identical_existing_dependency_is_accepted_without_replacement(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root, runtime = self.msi_fixture(folder)
            target = runtime/'program/concrt140.dll'
            target.write_bytes((root/'System64/concrt140.dll').read_bytes())
            before = target.stat().st_mtime_ns
            module.stage_msi_dependencies(root, runtime)
            self.assertEqual(target.stat().st_mtime_ns, before)

    def test_mixed_architecture_dependency_fails_before_any_copy(self):
        module = implementation()
        for machine in (0x14c, 0xaa64):
            with self.subTest(machine=machine), tempfile.TemporaryDirectory() as folder:
                root, runtime = self.msi_fixture(folder)
                (root/'System64/vcruntime140_threads.dll').write_bytes(pe(machine, dll=True))
                with self.assertRaisesRegex(ValueError, 'x64|architecture'):
                    module.stage_msi_dependencies(root, runtime)
                self.assertEqual(list((runtime/'program').iterdir()), [])

    def test_symlink_dependency_rejected_without_touching_its_target(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root, runtime = self.msi_fixture(folder)
            path = root/'System64/concrt140.dll'
            data = path.read_bytes()
            outside = Path(folder)/'original.dll'; outside.write_bytes(data)
            path.unlink()
            try: path.symlink_to(outside)
            except OSError: self.skipTest('Symlink creation unavailable')
            with self.assertRaisesRegex(ValueError, 'link|reparse'):
                module.stage_msi_dependencies(root, runtime)
            self.assertEqual(outside.read_bytes(), data)
            self.assertEqual(list((runtime/'program').iterdir()), [])

    def test_extract_msi_stages_dependencies_and_writes_runtime_input_receipt(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder)/'input.msi'; archive.write_bytes(b'authenticated input unchanged')
            output = Path(folder)/'extract'
            def administrative_extract(*args, **kwargs):
                # extract_msi owns an existing fresh output directory at this point.
                runtime = output/'LibreOffice'; (runtime/'program').mkdir(parents=True)
                self.app_root_fixture(runtime)
                (output/'System64').mkdir()
                for name in VC_DLLS: (output/'System64'/name).write_bytes(pe(dll=True))
                for name in ('soffice.exe', 'python.exe'): (runtime/'program'/name).write_bytes(pe())
                return type('Result', (), {'returncode': 0})()
            def recover(msi, destination, *, architecture='x64'):
                self.assertEqual(architecture, 'x64')
                destination.mkdir()
                for name in VC_DLLS: (destination/name).write_bytes(pe(dll=True))
                return {name: {'path': destination/name, 'fileId': name+'_amd64.GUID',
                               'cabinet': '#official.cab'} for name in VC_DLLS}
            with patch.object(module, 'os', SimpleNamespace(name='nt')), \
                 patch.object(module.subprocess, 'run', side_effect=administrative_extract), \
                 patch('suite.msi_cab.recover_crt', side_effect=recover):
                runtime = module.extract_msi(archive, output)
            receipt = json.loads((runtime/'opengeul-msi-dependencies.json').read_text())
            self.assertEqual(receipt['schemaVersion'], 1)
            self.assertEqual(receipt['architecture'], 'x64')
            self.assertEqual(set(receipt['files']), {'program/'+name for name in VC_DLLS})
            self.assertTrue(all((runtime/path).is_file() for path in receipt['files']))
            self.assertEqual(archive.read_bytes(), b'authenticated input unchanged')

    def test_arm64_extraction_recovers_native_members_and_records_architecture(self):
        module = implementation()
        self.assertIn('architecture', inspect.signature(module.extract_msi).parameters)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root/'input.msi'; archive.write_bytes(b'authenticated arm64 input')
            output = root/'extract'
            def admin(*args, **kwargs):
                self.app_root_fixture(output)
                (output/'System64').mkdir()
                for name in ARM_VC_DLLS: (output/'System64'/name).write_bytes(pe(dll=True))
                return SimpleNamespace(returncode=0)
            def recover(msi, destination, *, architecture):
                self.assertEqual(architecture, 'arm64')
                destination.mkdir()
                for name in ARM_VC_DLLS: (destination/name).write_bytes(pe(0xAA64, dll=True))
                return {name: {'path': destination/name, 'fileId': name+'_arm64.GUID',
                               'cabinet': '#official.cab'} for name in ARM_VC_DLLS}
            with patch.object(module, 'os', SimpleNamespace(name='nt')), \
                 patch.object(module.subprocess, 'run', side_effect=admin), \
                 patch('suite.msi_cab.recover_crt', side_effect=recover):
                runtime = module.extract_msi(archive, output, architecture='arm64')
            receipt = json.loads((runtime/'opengeul-msi-dependencies.json').read_text())
            self.assertEqual(receipt['architecture'], 'arm64')
            self.assertEqual(receipt['recovery'], 'embedded-arm64-file-ids')
            self.assertEqual(receipt['inputMsiSha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
            for name in ARM_VC_DLLS:
                self.assertEqual((runtime/'program'/name).read_bytes(), pe(0xAA64, dll=True))
                self.assertEqual(receipt['files']['program/'+name]['fileId'], name+'_arm64.GUID')

    def test_matching_cached_download_is_reused_without_network(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'runtime.msi'; path.write_bytes(b'checked input')
            asset = {'url': 'https://example.com/runtime.msi', 'size': path.stat().st_size,
                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            self.assertEqual(module.download_locked(asset, path), path)

    def test_bad_cached_download_is_preserved_and_rejected(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'runtime.msi'; path.write_bytes(b'user file')
            asset = {'url': 'https://example.com/runtime.msi', 'size': 9, 'sha256': '0' * 64}
            with self.assertRaises(ValueError): module.download_locked(asset, path)
            self.assertEqual(path.read_bytes(), b'user file')

    def test_non_https_and_incomplete_input_lock_are_rejected(self):
        module = implementation()
        for asset in ({'url':'http://example.com/a', 'size':1, 'sha256':'0'*64},
                      {'url':'https://example.com/a', 'size':0, 'sha256':'0'*64},
                      {'url':'https://example.com/a', 'size':1, 'sha256':'wrong'}):
            with self.subTest(asset=asset), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    module.download_locked(asset, Path(folder)/'input')

    def archive(self, folder, names):
        path = Path(folder)/'input.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in names:
                # Set the exact archive bytes after ZipInfo's OS path normalization.
                info = zipfile.ZipInfo('fixture')
                info.filename = name
                info.orig_filename = name
                archive.writestr(info, data)
        return path

    def test_hwp_archive_extracts_original_relative_paths(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            path = self.archive(folder, [('OpenGeul.exe',b'editor'),('Tools/rhwp.exe',b'cli')])
            destination = Path(folder)/'out'
            module.extract_hwp_zip(path, destination)
            self.assertEqual((destination/'OpenGeul.exe').read_bytes(), b'editor')
            self.assertEqual((destination/'Tools/rhwp.exe').read_bytes(), b'cli')

    def test_unsafe_archive_is_rejected_before_creating_output(self):
        module = implementation()
        for name in ('../escape', '/absolute', 'C:/absolute', 'bad\\file', 'CON.txt', 'name:stream'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                path = self.archive(folder, [('OpenGeul.exe',b'editor'),(name,b'bad')])
                destination = Path(folder)/'out'
                with self.assertRaises(ValueError): module.extract_hwp_zip(path, destination)
                self.assertFalse(destination.exists())


    def test_raw_zip_names_remain_rejected_after_windows_reader_normalization(self):
        module = implementation()
        original_init = zipfile.ZipInfo.__init__
        def windows_init(info, *args, **kwargs):
            original_init(info, *args, **kwargs)
            info.filename = info.filename.replace('\\', '/')
        for name in ('bad\\file', 'nul\x00truncated.txt'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                path = self.archive(folder, [('OpenGeul.exe', b'editor'), (name, b'bad')])
                destination = Path(folder)/'out'
                with patch.object(zipfile.ZipInfo, '__init__', windows_init):
                    with self.assertRaises(ValueError):
                        module.extract_hwp_zip(path, destination)
                self.assertFalse(destination.exists())

    def test_case_collision_and_over_limit_archives_are_rejected(self):
        module = implementation()
        for names, limit in (([('OpenGeul.exe',b'a'),('opengeul.exe',b'b')],100),
                             ([('OpenGeul.exe',b'ab')],1)):
            with tempfile.TemporaryDirectory() as folder:
                path = self.archive(folder,names); destination = Path(folder)/'out'
                with self.assertRaises(ValueError): module.extract_hwp_zip(path,destination,limit=limit)
                self.assertFalse(destination.exists())

    def test_existing_output_is_never_replaced(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            path = self.archive(folder,[('OpenGeul.exe',b'new')])
            destination = Path(folder)/'out'; destination.mkdir()
            (destination/'mine').write_text('keep')
            with self.assertRaises(ValueError): module.extract_hwp_zip(path,destination)
            self.assertEqual((destination/'mine').read_text(),'keep')


class SourceEngineTests(unittest.TestCase):
    def test_source_receipt_requires_effective_archive_format_and_oem_services_disabled(self):
        module = implementation()
        for field in ('PKGFORMAT', 'ENABLE_ONLINE_UPDATE', 'ENABLE_ONLINE_UPDATE_MAR', 'ENABLE_BREAKPAD'):
            for value in (None, 'TRUE'):
                with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as folder:
                    _, lock, path, proof = source_build_fixture(Path(folder))
                    if value is None: del proof['configuration'][field]
                    else: proof['configuration'][field] = value
                    pin_source_receipt(lock, path, proof)
                    with self.assertRaisesRegex(ValueError, 'configuration|OEM'):
                        module.validate_source_build_receipt(lock, path, architecture='arm64')
        for token in ('BREAKPAD', 'ONLINEUPDATE', 'breakpad', 'OnlineUpdate'):
            with self.subTest(token=token), tempfile.TemporaryDirectory() as folder:
                _, lock, path, proof = source_build_fixture(Path(folder))
                proof['configuration']['BUILD_TYPE'] += ' '+token
                pin_source_receipt(lock, path, proof)
                with self.assertRaisesRegex(ValueError, 'configuration|OEM'):
                    module.validate_source_build_receipt(lock, path, architecture='arm64')

    def test_external_core_pin_and_final_emitted_build_identity_are_required(self):
        module = implementation()
        mutations = (
            lambda lock,p:lock.pop('sourceCoreCommit'),
            lambda lock,p:lock.update(sourceCoreCommit='f'*40),
            lambda lock,p:p['sourcePin'].pop('coreCommit'),
            lambda lock,p:p['sourcePin'].update(coreCommit='f'*40),
            lambda lock,p:p.pop('runtimeBuildIdentity'),
            lambda lock,p:p['runtimeBuildIdentity'].update(expectedBuildId='f'*40),
            lambda lock,p:p['runtimeBuildIdentity'].update(sourceArchiveSha256='f'*64),
            lambda lock,p:p['runtimeBuildIdentity'].update(sourceArchiveSize=123),
            lambda lock,p:p['runtimeBuildIdentity']['files']['program/version.ini'].update(buildid='f'*40),
            lambda lock,p:p['runtimeBuildIdentity']['files']['program/version.ini'].update(corrected=False),
            lambda lock,p:p['runtimeBuildIdentity']['files']['program/setup.ini'].update(originalBuildId='f'*40),
            lambda lock,p:p['runtimeBuildIdentity'].pop('finalVerification'),
            lambda lock,p:p['runtimeBuildIdentity']['finalVerification'].update(passed=False),
            lambda lock,p:p['runtimeBuildIdentity']['finalVerification'].update(expectedBuildId='f'*40),
            lambda lock,p:p['runtimeBuildIdentity']['finalVerification']['files']['program/version.ini'].update(sha256='f'*64),
            lambda lock,p:p['runtimeBuildIdentity']['finalVerification']['files'].pop('program/setup.ini'),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as folder:
                _, lock, path, proof = source_build_fixture(Path(folder)); mutate(lock,proof)
                pin_source_receipt(lock, path, proof)
                with self.assertRaisesRegex(ValueError, 'core|identity|source.build|Source.build'):
                    module.validate_source_build_receipt(lock, path, architecture='arm64')

    def test_extracted_metadata_bytes_and_effective_buildid_match_final_proof(self):
        module = implementation()
        for name in ('program/version.ini', 'program/setup.ini'):
            for damage in ('missing', 'hash', 'wrong-id', 'duplicate-key'):
                with self.subTest(name=name, damage=damage), tempfile.TemporaryDirectory() as folder:
                    root=Path(folder); archive, lock, path, proof=source_build_fixture(root)
                    destination=module.extract_source_engine_zip(archive, root/'runtime', runtime=lock,
                                                                 receipt=path, architecture='arm64')
                    target=destination/name
                    if damage=='missing':target.unlink()
                    else:
                        raw=target.read_bytes()
                        if damage=='hash':raw+=b'; changed bytes\n'
                        elif damage=='wrong-id':raw=raw.replace(SOURCE_CORE.encode(),b'f'*40)
                        else:raw+=b' buildid ='+SOURCE_CORE.encode()+b'\n'
                        target.write_bytes(raw)
                        # Even a separately re-pinned receipt cannot turn wrong/ambiguous IDs into the external core.
                        if damage!='hash':
                            proof['runtimeBuildIdentity']['files'][name]['sha256']=hashlib.sha256(raw).hexdigest()
                            proof['runtimeBuildIdentity']['finalVerification']['files'][name]['sha256']=hashlib.sha256(raw).hexdigest()
                    with self.assertRaisesRegex(ValueError, 'identity|buildid'):
                        module.validate_source_build_runtime(destination, proof)

    def installed_identity_fixture(self,root):
        archive,lock,path,proof=source_build_fixture(root)
        config=dict(LIBO_VERSION_MAJOR='26',LIBO_VERSION_MINOR='8',LIBO_VERSION_MICRO='1',LIBO_VERSION_PATCH='1',LIBO_VERSION_SUFFIX='')
        proof['configuration'].update(config)
        identity=proof['runtimeBuildIdentity']
        reference=dict(path='C:/evidence/installed-runtime-stage.json',bytes=9071483,sha256='d'*64)
        proof['installedRuntimeStage']=dict(passed=True,runtimeRoot='C:/runtime',receipt=reference.copy())
        identity.update(identityMode='installed-no-git-fallback',stageReceipt=reference.copy(),originals={},
            installedFallbackDerivation=dict(rule='libreoffice-26.8.1.1-installer-no-git-v1',configuration=config.copy(),
                build='2680',normalizedBuild='680',installerBuildId='1',buildid='680(Build:1)'))
        with zipfile.ZipFile(archive) as source:
            for name,record in identity['files'].items():
                before=source.read(name).replace(SOURCE_CORE.encode(),b'680(Build:1)')
                record.update(originalBuildId='680(Build:1)',corrected=True,beforeSha256=hashlib.sha256(before).hexdigest())
                identity['originals'][name]=dict(archivePath='C:/main.zip',archiveMember='wrapper/'+name,
                    bytes=len(before),sha256=record['beforeSha256'])
        return archive,lock,path,proof

    def test_installed_fallback_independent_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            _,lock,path,proof=self.installed_identity_fixture(Path(folder))
            pin_source_receipt(lock,path,proof)
            implementation().validate_source_build_receipt(lock,path,architecture='arm64')

    def test_installed_fallback_rejects_self_authorization_and_descriptor_drift(self):
        changes=[
            lambda p:p['sourcePin'].update(version='26.8.2.1'),
            lambda p:p['sourcePin'].update(coreCommit='f'*40),
            lambda p:p['sourcePin'].update(size=123),
            lambda p:p['sourcePin'].update(sha256='f'*64),
            lambda p:p['configuration'].update(LIBO_VERSION_PATCH='2'),
            lambda p:p['runtimeBuildIdentity']['installedFallbackDerivation'].update(buildid='2680(Build:1)'),
            lambda p:p['runtimeBuildIdentity']['installedFallbackDerivation']['configuration'].update(LIBO_VERSION_MINOR='9'),
            lambda p:p['runtimeBuildIdentity'].pop('installedFallbackDerivation'),
            lambda p:p['runtimeBuildIdentity'].pop('stageReceipt'),
            lambda p:p['installedRuntimeStage']['receipt'].update(sha256='f'*64),
            lambda p:p['runtimeBuildIdentity']['originals']['program/setup.ini'].update(sha256='f'*64),
            lambda p:p['runtimeBuildIdentity']['originals']['program/setup.ini'].update(bytes=0),
            lambda p:p['runtimeBuildIdentity']['originals']['program/setup.ini'].update(archivePath='C:/other.zip'),
            lambda p:p['runtimeBuildIdentity']['originals']['program/setup.ini'].update(archiveMember='other/program/setup.ini'),
            lambda p:p['runtimeBuildIdentity']['files']['program/setup.ini'].update(originalBuildId='a'*40),
            lambda p:p['runtimeBuildIdentity']['files']['program/setup.ini'].update(originalBuildId='f'*40)]
        for change in changes:
            with self.subTest(change=changes.index(change)),tempfile.TemporaryDirectory() as folder:
                _,lock,path,proof=self.installed_identity_fixture(Path(folder));change(proof)
                pin_source_receipt(lock,path,proof)
                with self.assertRaises(ValueError):
                    implementation().validate_source_build_receipt(lock,path,architecture='arm64')

    def test_actual_emitter_accepts_empty_and_already_official_original_build_ids(self):
        module = implementation()
        for original in ('', SOURCE_CORE):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as folder:
                archive, lock, path, proof = source_build_fixture(Path(folder))
                with zipfile.ZipFile(archive) as source:
                    for name, record in proof['runtimeBuildIdentity']['files'].items():
                        before = source.read(name).replace(SOURCE_CORE.encode(), original.encode())
                        record.update(originalBuildId=original, corrected=original != SOURCE_CORE,
                                      beforeSha256=hashlib.sha256(before).hexdigest())
                pin_source_receipt(lock, path, proof)
                module.extract_source_engine_zip(archive, Path(folder)/'runtime', runtime=lock,
                                                 receipt=path, architecture='arm64')

    def test_source_receipt_requires_matching_signed_native_eight_crt_metadata_and_terms(self):
        module = implementation()
        for mutation in ('missing', 'count', 'copied', 'source', 'machine', 'signature', 'version', 'terms'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); archive, lock, path, receipt = source_build_fixture(root)
                if mutation == 'missing': del receipt['crtPreflight']
                elif mutation == 'count': receipt['appLocalCrt']['files'].pop()
                elif mutation == 'copied': receipt['appLocalCrt']['files'][0]['copiedSha256'] = 'f'*64
                elif mutation == 'source': receipt['appLocalCrt']['files'][0]['source']['sha256'] = 'f'*64
                elif mutation == 'machine': receipt['crtPreflight']['files'][0]['machine'] = 0x8664
                elif mutation == 'signature': receipt['crtPreflight']['files'][0]['signature']['status'] = 'UnknownError'
                elif mutation == 'version': receipt['crtPreflight']['files'][0]['signature']['productVersionParts'] = [14, 40, 1, 0]
                else: receipt['crtRedistributionTerms']['sha256'] = 'f'*64
                pin_source_receipt(lock, path, receipt)
                with self.assertRaisesRegex(ValueError, 'CRT|redistribution'):
                    module.extract_source_engine_zip(archive, root/'runtime', runtime=lock,
                                                     receipt=path, architecture='arm64')
                self.assertFalse((root/'runtime').exists())

    def test_source_receipt_requires_exact_successful_arm64_import_closure(self):
        module=implementation()
        for mutation in ('missing','passed','architecture','count','names','imports'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);archive,lock,path,proof=source_build_fixture(root)
                if mutation=='missing':del proof['crtImportClosure']
                elif mutation=='passed':proof['crtImportClosure']['passed']=False
                elif mutation=='architecture':proof['crtImportClosure']['architecture']='x64'
                elif mutation=='count':proof['crtImportClosure']['checkedPeCount']=0
                elif mutation=='names':proof['crtImportClosure']['requiredCrtFiles'].append('vcruntime140_1.dll')
                else:proof['crtImportClosure']['imports']=[dict(path='program/soffice.bin',normal=['vcruntime140_1.dll'],delay=[])]
                pin_source_receipt(lock,path,proof)
                with self.assertRaisesRegex(ValueError,'CRT|import'):
                    module.extract_source_engine_zip(archive,root/'runtime',runtime=lock,receipt=path,architecture='arm64')
                self.assertFalse((root/'runtime').exists())

    def test_extracted_runtime_replays_import_closure_count_after_authenticated_receipt(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive,lock,path,proof=source_build_fixture(root)
            destination=module.extract_source_engine_zip(archive,root/'runtime',runtime=lock,receipt=path,architecture='arm64')
            (destination/'program/extra-native.dll').write_bytes(pe(0xaa64,dll=True))
            with self.assertRaisesRegex(ValueError,'CRT|import'):
                module.validate_source_build_runtime(destination,proof)

    def test_locked_qualified_engine_extracts_original_bytes_and_exact_receipt_without_msi_metadata(self):
        module = implementation()
        self.assertTrue(callable(getattr(module, 'extract_source_engine_zip', None)),
                        'Source-built ZIP ingestion is required')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive, lock, receipt_path, receipt = source_build_fixture(root)
            destination = root/'runtime'
            module.extract_source_engine_zip(archive, destination, runtime=lock,
                                             receipt=receipt_path, architecture='arm64')
            self.assertEqual((destination/'program/soffice.bin').read_bytes(), pe(0xaa64))
            self.assertEqual((destination/'opengeul-source-build.json').read_bytes(), receipt_path.read_bytes())
            self.assertFalse((destination/'opengeul-msi-dependencies.json').exists())
            self.assertEqual(json.loads(receipt_path.read_text()), receipt)

    def test_input_size_hash_and_external_receipt_pin_are_required_before_extraction(self):
        module = implementation()
        for mutation in ('size', 'hash', 'receipt', 'no-pin', 'untrusted-outer-artifact'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); archive, lock, receipt_path, receipt = source_build_fixture(root)
                if mutation == 'size': lock['size'] += 1
                elif mutation == 'hash': lock['sha256'] = 'f'*64
                elif mutation == 'receipt': receipt_path.write_bytes(receipt_path.read_bytes()+b' ')
                elif mutation == 'no-pin': del lock['sourceBuild']['receiptSha256']
                else: lock['sourceBuild']['artifactSha256'] = 'invalid'
                with self.assertRaisesRegex(ValueError, 'lock|Locked|receipt|Receipt|source.build'):
                    module.extract_source_engine_zip(archive, root/'runtime', runtime=lock,
                                                     receipt=receipt_path, architecture='arm64')
                self.assertFalse((root/'runtime').exists())

    def test_source_zip_preserves_existing_output_and_rejects_linked_inputs_or_parent(self):
        module = implementation()
        for linked in ('existing', 'archive', 'receipt', 'parent'):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); archive, lock, receipt, _ = source_build_fixture(root)
                output = root/'runtime'
                if linked == 'existing':
                    output.mkdir(); (output/'sentinel').write_bytes(b'keep')
                else:
                    target = root/'alias'
                    original = {'archive': archive, 'receipt': receipt, 'parent': root/'outside'}[linked]
                    if linked == 'parent': original.mkdir()
                    try: target.symlink_to(original, target_is_directory=linked == 'parent')
                    except OSError: self.skipTest('Symlink creation unavailable')
                    if linked == 'archive': archive = target
                    elif linked == 'receipt': receipt = target
                    else: output = target/'runtime'
                with self.assertRaises(ValueError):
                    module.extract_source_engine_zip(archive, output, runtime=lock,
                                                     receipt=receipt, architecture='arm64')
                if linked == 'existing': self.assertEqual((output/'sentinel').read_bytes(), b'keep')
                else: self.assertFalse(output.exists())

    def test_pinned_receipt_still_must_prove_native_full_engine_source_and_independent_base_reopen(self):
        module = implementation()
        changes = [('passed', False), ('phase', 'Firebird'), ('fullEngineQualified', False),
                   ('architecture', 'x64'), ('host.processMachine', 0x8664),
                   ('host.nativeMachine', 0x8664), ('sourceCommit', 'f'*40), ('sourceRun', 999),
                   ('sourcePortManifestSha256', 'f'*64), ('sourcePin.sha256', 'f'*64),
                   ('sourcePin.url', 'https://example.org/other'), ('artifact.size', 123),
                   ('artifact.sha256', 'f'*64), ('configuration.CPUNAME', 'X86_64'),
                   ('configuration.ENABLE_FIREBIRD_SDBC', ''), ('configuration.CROSS_COMPILING', 'yes'),
                   ('baseProof.independentReopenVerified', False), ('baseProof.rows', []),
                   ('baseProof.rows', [{'id': 1, 'text': 'wrong', 'amount': 42}]),
                   ('baseProof.nativeProcesses', [])]
        for field, value in changes:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); archive, lock, receipt_path, receipt = source_build_fixture(root)
                target = receipt
                parts = field.split('.')
                for part in parts[:-1]: target = target[part]
                target[parts[-1]] = value
                pin_source_receipt(lock, receipt_path, receipt)
                with self.assertRaises(ValueError):
                    module.extract_source_engine_zip(archive, root/'runtime', runtime=lock,
                                                     receipt=receipt_path, architecture='arm64')
                self.assertFalse((root/'runtime').exists())

    def test_native_base_witnesses_require_actual_owned_separate_soffice_hosts(self):
        module = implementation()
        for field, value in (('image', 'C:\\runtime\\program\\soffice.exe'), ('jobOwned', False),
                             ('phase', 'create'), ('creationTime', 0), ('pid', 11),
                             ('processMachine', 0x8664), ('role', 'launcher')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); archive, lock, receipt_path, receipt = source_build_fixture(root)
                receipt['baseProof']['nativeProcesses'][2][field] = value
                if field == 'pid':
                    receipt['baseProof']['nativeProcesses'][2]['creationTime'] = 100
                pin_source_receipt(lock, receipt_path, receipt)
                with self.assertRaises(ValueError):
                    module.extract_source_engine_zip(archive, root/'runtime', runtime=lock,
                                                     receipt=receipt_path, architecture='arm64')
                self.assertFalse((root/'runtime').exists())

    def test_native_base_reopen_uses_process_identity_when_windows_reuses_a_pid(self):
        module = implementation()
        for pid, creation_time in ((11, 200), (12, 100)):
            with self.subTest(pid=pid, creationTime=creation_time), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); _, lock, receipt_path, receipt = source_build_fixture(root)
                receipt['baseProof']['nativeProcesses'][2].update(pid=pid, creationTime=creation_time)
                pin_source_receipt(lock, receipt_path, receipt)
                try:
                    observed = module.validate_source_build_receipt(lock, receipt_path, architecture='arm64')
                except ValueError as error:
                    self.fail('Separate native process identities must qualify: '+str(error))
                self.assertEqual(observed, receipt)

    def test_native_base_host_cannot_share_the_still_live_python_pid(self):
        module = implementation()
        for host in (1, 2):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); _, lock, receipt_path, receipt = source_build_fixture(root)
                receipt['baseProof']['nativeProcesses'][host]['pid'] = 10
                pin_source_receipt(lock, receipt_path, receipt)
                with self.assertRaisesRegex(ValueError, 'process witnesses'):
                    module.validate_source_build_receipt(lock, receipt_path, architecture='arm64')

    def test_source_zip_rejects_unsafe_regular_member_names_kinds_aliases_and_bounds_before_output(self):
        module = implementation()
        cases = [('../escape', 0, b'x'), ('C:/escape', 0, b'x'), ('bad\\file', 0, b'x'),
                 ('CON.txt', 0, b'x'), ('COM¹.txt', 0, b'x'), ('bad:stream', 0, b'x'),
                 ('CONIN$', 0, b'x'), ('CONOUT$', 0, b'x'), ('CON .txt', 0, b'x'),
                 ('AUX .bin', 0, b'x'), ('COM1 .dll', 0, b'x'), ('LPT1 .x', 0, b'x'),
                 ('nul\x00hidden', 0, b'x'), ('program/SOFFICE.bin', 0, b'x'),
                 ('Program/extra', 0, b'x'), ('program/soffice.bin/child', 0, b'x'),
                 ('linked', (0o120777 << 16), b'outside'),
                 ('fifo', (0o010600 << 16), b'x'), ('reparse', 0x400, b'x'),
                 ('opengeul-source-build.json', 0, b'forged receipt'),
                 ('opengeul-source-build.json/child', 0, b'forged receipt directory'),
                 ('opengeul-msi-dependencies.json/child', 0, b'forged MSI receipt directory')]
        for name, attributes, data in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); archive, lock, receipt_path, receipt = source_build_fixture(root)
                with zipfile.ZipFile(archive, 'a') as source:
                    info = zipfile.ZipInfo('fixture'); info.filename = info.orig_filename = name
                    info.external_attr = attributes
                    source.writestr(info, data)
                lock['size'] = archive.stat().st_size; lock['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
                receipt['artifact'].update(size=lock['size'], sha256=lock['sha256'])
                pin_source_receipt(lock, receipt_path, receipt)
                with self.assertRaises(ValueError):
                    module.extract_source_engine_zip(archive, root/'runtime', runtime=lock,
                                                     receipt=receipt_path, architecture='arm64')
                self.assertFalse((root/'runtime').exists())
        for bound in ('limit', 'max_files', 'max_file_size'):
            with self.subTest(bound=bound), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); archive, lock, receipt_path, _ = source_build_fixture(root)
                with self.assertRaises(ValueError):
                    module.extract_source_engine_zip(archive, root/'runtime', runtime=lock,
                        receipt=receipt_path, architecture='arm64', **{bound: 1})
                self.assertFalse((root/'runtime').exists())


class PrepareCommandTests(unittest.TestCase):
    def command_fixture(self, folder):
        root = Path(folder)
        config = root/'suite/config'; config.mkdir(parents=True)
        inputs = root/'work/inputs'; inputs.mkdir(parents=True)
        assets = {}
        for label, filename in (('runtime', 'office.msi'), ('hwp', 'hwp.zip')):
            data = (label+' authenticated input').encode()
            (inputs/filename).write_bytes(data)
            assets[label] = {'url': 'https://example.org/'+filename, 'size': len(data),
                             'sha256': hashlib.sha256(data).hexdigest()}
        for architecture, filename in (('x64', 'runtime.lock.json'), ('arm64', 'runtime.arm64.lock.json')):
            (config/filename).write_text(json.dumps(dict(assets, architecture=architecture)))
        return root

    def run_command(self, module, root, arguments):
        def extract(archive, destination, *, architecture=None):
            return destination.with_name('native-'+str(architecture))
        def assemble(**kwargs):
            kwargs['output'].write_text(json.dumps({'architecture': kwargs['lock']['architecture'],
                                                   'runtime': kwargs['runtime'].name}))
        argv = ['prepare', '--work', str(root/'work'), '--shell', str(root/'shell'),
                '--output', str(root/'output.json'), *arguments]
        with patch.object(module, 'ROOT', root), patch.object(module.sys, 'argv', argv), \
             patch.object(module, 'extract_msi', side_effect=extract), \
             patch.dict('sys.modules', {'package': SimpleNamespace(assemble=assemble)}), redirect_stdout(io.StringIO()):
            try:
                module.main()
            except SystemExit as error:
                self.fail('Preparation command must accept supported architecture: '+str(error))

    def test_arm64_command_selects_fixed_arm64_lock_and_native_extraction(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root = self.command_fixture(folder)
            self.run_command(module, root, ['--architecture', 'arm64'])
            self.assertEqual({'architecture': 'arm64', 'runtime': 'native-arm64'},
                             json.loads((root/'output.json').read_text()))

    def test_default_command_preserves_x64_lock_and_native_extraction(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root = self.command_fixture(folder)
            self.run_command(module, root, [])
            self.assertEqual({'architecture': 'x64', 'runtime': 'native-x64'},
                             json.loads((root/'output.json').read_text()))

    def test_source_mode_uses_explicit_local_engine_and_receipt_without_downloading_a_runtime(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root = self.command_fixture(folder)
            archive, runtime, receipt_path, _ = source_build_fixture(root)
            lockfile = root/'suite/config/runtime.arm64.lock.json'
            lock = json.loads(lockfile.read_text()); lock['runtime'] = runtime
            lockfile.write_text(json.dumps(lock))
            with patch.object(module, 'download_locked', wraps=module.download_locked) as downloaded, \
                 patch.object(module, 'extract_msi', side_effect=AssertionError('ZIP must not use MSI')):
                self.run_command(module, root, ['--architecture', 'arm64', '--engine-archive', str(archive),
                                                '--engine-receipt', str(receipt_path)])
            self.assertEqual(downloaded.call_count, 1)
            self.assertEqual(downloaded.call_args.args[0], lock['hwp'])
            self.assertEqual(json.loads((root/'output.json').read_text()),
                             {'architecture': 'arm64', 'runtime': 'source-engine-runtime'})

    def test_source_mode_requires_both_local_inputs_before_any_download(self):
        module = implementation()
        for inputs in ([], ['--engine-archive', 'engine.zip'], ['--engine-receipt', 'receipt.json']):
            with self.subTest(inputs=inputs), tempfile.TemporaryDirectory() as folder:
                root = self.command_fixture(folder)
                _, runtime, _, _ = source_build_fixture(root)
                lockfile = root/'suite/config/runtime.arm64.lock.json'
                lock = json.loads(lockfile.read_text()); lock['runtime'] = runtime
                lockfile.write_text(json.dumps(lock))
                with patch.object(module, 'download_locked', side_effect=AssertionError('No downloads allowed')):
                    with self.assertRaisesRegex(ValueError, 'source.build artifact|source-build artifact'):
                        self.run_command(module, root, ['--architecture', 'arm64', *inputs])
                self.assertFalse((root/'output.json').exists())

    def test_source_mode_reports_missing_local_inputs_before_any_download(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root = self.command_fixture(folder)
            _, runtime, _, _ = source_build_fixture(root)
            lockfile = root/'suite/config/runtime.arm64.lock.json'
            lock = json.loads(lockfile.read_text()); lock['runtime'] = runtime
            lockfile.write_text(json.dumps(lock))
            with patch.object(module, 'download_locked', side_effect=AssertionError('No downloads allowed')):
                with self.assertRaisesRegex(ValueError, 'source.build artifact|source-build artifact'):
                    self.run_command(module, root, ['--architecture', 'arm64', '--engine-archive', str(root/'absent.zip'),
                                                    '--engine-receipt', str(root/'absent.json')])

    def test_unknown_runtime_format_and_msi_source_options_fail_before_download(self):
        module = implementation()
        for mode in ('unknown', 'msi-inputs'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = self.command_fixture(folder)
                arguments = []
                if mode == 'unknown':
                    lockfile = root/'suite/config/runtime.lock.json'
                    lock = json.loads(lockfile.read_text()); lock['runtime']['format'] = 'unknown'
                    lockfile.write_text(json.dumps(lock))
                else: arguments = ['--engine-archive', 'engine.zip', '--engine-receipt', 'receipt.json']
                with patch.object(module, 'download_locked', side_effect=AssertionError('No downloads allowed')):
                    with self.assertRaisesRegex(ValueError, 'format|source.build|source-built'):
                        self.run_command(module, root, arguments)

    def test_lock_architecture_mismatch_is_rejected_before_any_extraction(self):
        module = implementation()
        with tempfile.TemporaryDirectory() as folder:
            root = self.command_fixture(folder)
            lockfile = root/'suite/config/runtime.arm64.lock.json'
            lock = json.loads(lockfile.read_text()); lock['architecture'] = 'x64'
            lockfile.write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError, 'architecture'):
                self.run_command(module, root, ['--architecture', 'arm64'])
            self.assertFalse((root/'output.json').exists())


class NativeX64SourceAdmissionTests(unittest.TestCase):
    def runtime_fixture(self,root,module):
        archive,runtime,path,proof=x64_source_build_fixture(root,runtime_templates=True)
        pins=synthetic_source_template_pins(proof)
        # This private unit seam substitutes synthetic launcher identities only.
        # The receipt-only tests above exercise the actual reviewed ten pins.
        replacement=patch.object(module,'_source_python_templates',return_value=pins)
        replacement.start();self.addCleanup(replacement.stop)
        return archive,runtime,path,proof

    def test_v2_runtime_replays_native_managed_and_template_bytes(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive,runtime,path,proof=self.runtime_fixture(root,module)
            output=root/'runtime'
            module.extract_source_engine_zip(archive,output,runtime=runtime,receipt=path,architecture='x64')
            module.validate_source_build_runtime(output,proof,architecture='x64')
            with self.assertRaises(ValueError):module.validate_source_build_runtime(output,proof,architecture='arm64')
            managed=output/'program/policy.1.0.cli_cppuhelper.dll'
            managed.write_bytes(managed.read_bytes()+b'changed')
            with self.assertRaises(ValueError):module.validate_source_build_runtime(output,proof,architecture='x64')

    def test_v2_zip_aliases_and_reparse_members_fail_before_output_creation(self):
        module=implementation()
        for bad in ('../escape.dll','program/WINACCESSIBILITY.dll','program/linked.dll'):
            with self.subTest(member=bad),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);archive,runtime,path,proof=self.runtime_fixture(root,module)
                with zipfile.ZipFile(archive,'a') as target:
                    if bad.endswith('linked.dll'):
                        member=zipfile.ZipInfo(bad);member.create_system=3;member.external_attr=0xa1ff<<16
                        target.writestr(member,b'target')
                    else:target.writestr(bad,pe(0x8664,dll=True))
                runtime.update(size=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
                proof['artifact'].update(size=runtime['size'],sha256=runtime['sha256'])
                pin_source_receipt(runtime,path,proof);output=root/'output'
                with self.assertRaises(ValueError):module.extract_source_engine_zip(archive,output,
                    runtime=runtime,receipt=path,architecture='x64')
                self.assertFalse(output.exists())

    def test_v2_retirement_accepts_additional_discovered_members_only_if_all_exited(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            _,runtime,path,proof=x64_source_build_fixture(Path(folder))
            cleanup=proof['baseProof']['retirement'][0]['cleanup']
            extra=copy.deepcopy(cleanup['finalMembers'][0]);extra.update(pid=99,creationTime=999,handleValue=199)
            cleanup['finalMembers'].append(extra)
            pin_source_receipt(runtime,path,proof)
            module.validate_source_build_receipt(runtime,path,architecture='x64')
            extra['exitCode']=1;pin_source_receipt(runtime,path,proof)
            with self.assertRaises(ValueError):module.validate_source_build_receipt(runtime,path,architecture='x64')

    def test_v2_external_tree_driver_policy_pins_cannot_be_missing_or_swapped(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            _,runtime,path,_=x64_source_build_fixture(Path(folder))
            original=copy.deepcopy(runtime)
            for key in ('sourceTree','driverSha256','nativeTargetsSha256'):
                for value in (None,'0'*(40 if key=='sourceTree' else 64),True):
                    runtime=copy.deepcopy(original)
                    if value is None:runtime['sourceBuild'].pop(key)
                    else:runtime['sourceBuild'][key]=value
                    with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                        module.validate_source_build_receipt(runtime,path,architecture='x64')

    def test_v2_receipt_is_selected_only_by_independent_x64_expectation(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            _,runtime,path,proof=x64_source_build_fixture(Path(folder))
            self.assertEqual(module.validate_source_build_receipt(runtime,path,architecture='x64'),proof)
            with self.assertRaises(ValueError): module.validate_source_build_receipt(runtime,path,architecture='arm64')
            with self.assertRaises(ValueError): module.validate_source_build_runtime(Path(folder),proof)

    def test_v2_one_field_qualification_and_workflow_mutations_are_rejected(self):
        changes=[('schemaVersion',1),('schemaVersion',True),('architecture','arm64'),('acceptanceEligible',False),
                 ('runAttempt',2),('runAttempt',True),('nativeTargetsSha256','0'*64),
                 ('configurationSha256',None),('configureArgumentsSha256','bad'),('sourceRecipeChecksExecuted',False)]
        with tempfile.TemporaryDirectory() as folder:
            _,runtime,path,original=x64_source_build_fixture(Path(folder));module=implementation()
            for field,value in changes:
                with self.subTest(field=field,value=value):
                    proof=copy.deepcopy(original);proof[field]=value;pin_source_receipt(runtime,path,proof)
                    with self.assertRaises(ValueError): module.validate_source_build_receipt(runtime,path,architecture='x64')
            for field in original['workflowBinding']:
                with self.subTest(workflow=field):
                    proof=copy.deepcopy(original);proof['workflowBinding'][field]='untrusted'
                    pin_source_receipt(runtime,path,proof)
                    with self.assertRaises(ValueError): module.validate_source_build_receipt(runtime,path,architecture='x64')

    def test_v2_preflight_tool_config_sdk_and_process_witnesses_are_joined(self):
        mutations=[lambda p:p['nativePreflight'].update(passed=False),
            lambda p:p['nativePreflight']['nativeProcess'].update(processMachine=0x14c),
            lambda p:p['nativePreflight']['nativeProcess'].update(libraryValue=True),
            lambda p:p['nativePreflight']['compiler']['tools']['cl'].update(machine=0xaa64),
            lambda p:p['nativePreflight']['compiler']['tools']['link'].update(sha256='bad'),
            lambda p:p['nativePreflight']['commands']['run'].update(exitCode=True),
            lambda p:p['configuredToolchain'].update(compilerRoot='C:\\Other'),
            lambda p:p['configuredToolchain'].update(sdkVersion='10.0.11111.0'),
            lambda p:p['nativePreflight']['sdk']['files'].pop(),
            lambda p:p['configuration'].update(VCTOOLSET='v145')]
        self.reject_mutations(mutations)

    def test_v2_native_java_and_original_deadline_cannot_be_missing_or_reset(self):
        mutations=[lambda p:p.pop('javaTools'),lambda p:p['javaTools']['jdk']['nativeFiles'].pop(),
            lambda p:p['javaTools']['jdk']['nativeFiles'][0].update(machine=0xaa64),
            lambda p:p['javaTools']['jdk']['importLibraries'][0].update(machines=[0xaa64]),
            lambda p:p['javaTools']['jdk'].update(selection='JAVA_HOME'),
            lambda p:p['buildBudget'].update(maximumMinutes=360),
            lambda p:p['buildBudget'].update(timeoutMilliseconds=True),
            lambda p:p['buildBudget'].update(elapsedSeconds=19801.0),
            lambda p:p['buildBudget'].update(workflowDeadlineUtc='2026-11-07T00:30:00.0000000Z'),
            lambda p:p.update(finishedUtc='2026-11-07T05:30:00.0000001Z')]
        self.reject_mutations(mutations)

    def test_v2_authenticated_python_and_installed_source_provenance_are_required(self):
        mutations=[lambda p:p['externalSources'].update(pythonSourceVerified=False),
            lambda p:p['externalSources'].update(archives=[]),
            lambda p:p['externalSources']['archives'][0].update(pinVariable='untrusted'),
            lambda p:p['externalSources'].update(embeddedPythonWheels=[]),
            lambda p:p['externalSources']['embeddedPythonWheels'][0].update(sha256='bad'),
            lambda p:p['installedRuntimeStage'].update(runtimeRoot='C:\\other'),
            lambda p:p['installedRuntimeStage'].update(archiveCount=True),
            lambda p:p['installedRuntimeStage']['receipt'].update(bytes=0)]
        self.reject_mutations(mutations)

    def test_v2_recipe_and_winacc_source_identity_cannot_be_omitted_or_relabelled(self):
        mutations=[lambda p:p.pop('sourceRecipeProof'),lambda p:p.pop('winAccFocusOrderSourcePatch'),
            lambda p:p['sourceRecipeProof'].update(recipeSha256='0'*64),
            lambda p:p['sourceRecipeProof']['armGuardedSources'][0].update(unchanged=False),
            lambda p:p['sourceRecipeProof'].update(hookOrder=['arm64Full','winAccFocusOrder']),
            lambda p:p['winAccFocusOrderSourcePatch'].update(afterSha256='0'*64),
            lambda p:p['sourceHooks']['moduleBootstrap'].update(afterSha256='0'*64)]
        self.reject_mutations(mutations)

    def test_v2_native_inventory_and_winacc_imports_are_required(self):
        mutations=[lambda p:p.pop('winAccBinary'),lambda p:p['winAccBinary'].update(machine=0xaa64),
            lambda p:p['winAccBinary'].update(sha256='0'*64),
            lambda p:p['winAccBinary']['imports'].update(normal=[]),
            lambda p:p['productInventory'].pop(),lambda p:p['productInventory'].append(copy.deepcopy(p['productInventory'][0])),
            lambda p:p['productInventory'][0].update(path='C:\\other\\soffice.exe'),
            lambda p:p['productInventory'][0].update(role='pythonLauncherTemplate'),
            lambda p:p['artifact'].update(path='C:\\evidence\\OpenGeul-Office-engine-arm64.zip'),
            lambda p:p['crtImportClosure'].update(checkedPeCount=p['nativePeCount']-1)]
        self.reject_mutations(mutations)

    def test_v2_base_retirement_requires_original_generation_and_closed_handles(self):
        mutations=[lambda p:p['baseProof'].pop('retirement'),
            lambda p:p['baseProof']['retirement'][0].update(handlesClosed=False),
            lambda p:p['baseProof']['retirement'][0]['cleanup'].update(forcedTermination=True),
            lambda p:p['baseProof']['retirement'][0]['cleanup'].update(finalJobPids=[11]),
            lambda p:p['baseProof']['retirement'][0]['cleanup']['finalMembers'][0].update(handleValue=999),
            lambda p:p['baseProof']['retirement'][0]['cleanup']['finalMembers'][0].update(exitCode=True),
            lambda p:p['baseProof']['retirement'][1].update(phase='create')]
        self.reject_mutations(mutations)

    def test_v2_crt_nine_file_family_terms_and_compiler_floor_are_required(self):
        mutations=[lambda p:p['crtPreflight']['files'].pop(),
            lambda p:p['crtPreflight'].update(minimumRuntimeVersion='14.0.0.0'),
            lambda p:p['crtRedistributionTerms'].update(url='https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution'),
            lambda p:p['crtImportClosure'].update(architecture='arm64'),
            lambda p:p['crtPreflight']['files'][0].update(machine=0xaa64)]
        self.reject_mutations(mutations)

    @staticmethod
    def rebind_crt_plan(proof, **changes):
        """Keep synthetic CRT/copy claims self-consistent while testing lineage."""
        plan=proof['crtPreflight'];plan.update(changes)
        source=plan['sourceDirectory'];copied=proof['appLocalCrt']
        copied['sourceDirectory']=source
        for record,item in zip(plan['files'],copied['files']):
            record['sourcePath']=source+'\\'+record['name']
            item['source']=copy.deepcopy(record)
        proof['nativePreflight']['crt']=copy.deepcopy(plan)

    def test_v2_package_floor_preserves_distinct_tool_resources_crt_files_and_folder(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            _,runtime,path,proof=x64_source_build_fixture(Path(folder))
            observed=module.validate_source_build_receipt(runtime,path,architecture='x64')
            compiler=observed['nativePreflight']['compiler'];crt=observed['crtPreflight']
            self.assertEqual(compiler['minimumRuntimeVersion'],'14.44.35207.0')
            self.assertEqual(compiler['tools']['cl']['version'],'19.44.35229.0')
            self.assertEqual(crt['selectedFileVersionFloor'],'14.44.35211.0')
            self.assertEqual(crt['redistVersionDirectory'],'14.44.35112')
            self.assertEqual(observed['nativePreflight']['nativeProcess']['compilerFullVersion'],194435229)

    def test_v2_package_floor_requires_bound_default_tools_metadata(self):
        mutations=[lambda p:p['nativePreflight']['compiler'].pop('runtimeFloorBasis'),
            lambda p:p['nativePreflight']['compiler'].update(runtimeFloorBasis='tool-resource-maximum'),
            lambda p:p['nativePreflight']['compiler'].pop('toolsetMetadata'),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].pop('path'),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].update(path='D:\\OtherVS\\VC\\Auxiliary\\Build\\Microsoft.VCToolsVersion.default.txt'),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].update(path='C:\\VS\\VC\\Auxiliary\\Build\\Microsoft.VCToolsRedistVersion.default.txt'),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].update(size=0),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].update(size=True),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].update(size=4097),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].update(sha256='bad'),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].update(version='14.43.35207'),
            lambda p:p['nativePreflight']['compiler']['toolsetMetadata'].update(version='14.44.35229'),
            lambda p:p['nativePreflight']['compiler'].update(minimumRuntimeVersion='14.44.35229.0')]
        self.reject_mutations(mutations)

    def test_v2_package_floor_preserves_resource_family_and_native_compiler_witness(self):
        self.reject_mutations([
            lambda p:p['nativePreflight']['compiler']['tools']['cl'].update(version='19.43.35229.0'),
            lambda p:p['nativePreflight']['compiler']['tools']['link'].update(version='14.45.35229.0'),
            lambda p:p['nativePreflight']['compiler']['tools']['lib'].update(version='19.44.35229.0'),
            lambda p:p['nativePreflight']['nativeProcess'].update(compilerFullVersion=194435207)])

    def test_v2_actual_crt_file_floor_requires_derived_minimum_and_selection_basis(self):
        mutations=[]
        for changes in ({'selectionBasis':None},{'selectionBasis':'directory-name'},
                        {'selectedFileVersionFloor':None},{'selectedFileVersionFloor':'14.44.35229.0'},
                        {'selectedFileVersionFloor':'14.44.35207.0'},{'selectedFileVersionFloor':'14.44.35211'},
                        {'selectedFileVersionFloor':True}):
            mutations.append(lambda p,changes=changes:self.rebind_crt_plan(p,**changes))
        self.reject_mutations(mutations)

    def test_v2_new_redist_folder_cannot_hide_old_unsigned_or_foreign_actual_dll(self):
        def bad_file(proof,kind):
            plan=proof['crtPreflight'];record=plan['files'][0]
            if kind in ('old-file','old-product'):
                field='file' if kind=='old-file' else 'product'
                record['signature'][field+'VersionParts']=[14,44,35206,0]
                record['signature'][field+'Version']='14.44.35206.0'
                if kind=='old-file':plan['selectedFileVersionFloor']='14.44.35206.0'
            elif kind=='unsigned':record['signature']['status']='NotSigned'
            else:record['signature']['companyName']='Foreign vendor'
            self.rebind_crt_plan(proof,redistVersionDirectory='14.99.99999',
                sourceDirectory='C:\\VS\\VC\\Redist\\MSVC\\14.99.99999\\x64\\Microsoft.VC143.CRT')
        self.reject_mutations([lambda p,kind=kind:bad_file(p,kind) for kind in
                               ('old-file','old-product','unsigned','foreign')])

    def test_v2_external_receipt_pin_detects_replaced_metadata_hash(self):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            _,runtime,path,proof=x64_source_build_fixture(Path(folder))
            proof['nativePreflight']['compiler']['toolsetMetadata']['sha256']='c'*64
            path.write_text(json.dumps(proof),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'locked SHA256'):
                module.validate_source_build_receipt(runtime,path,architecture='x64')

    def test_v2_crt_plan_requires_all_emitted_lineage_fields(self):
        mutations=[]
        for name in ('compilerRoot','redistRoot','redistVersionDirectory','redistFamily'):
            def missing(proof,name=name):
                proof['crtPreflight'].pop(name)
                proof['nativePreflight']['crt']=copy.deepcopy(proof['crtPreflight'])
            mutations.append(missing)
        self.reject_mutations(mutations)

    def test_v2_crt_plan_rejects_foreign_vs_family_and_escaped_redist(self):
        self.reject_mutations([
            lambda p:self.rebind_crt_plan(p,compilerRoot='D:\\OtherVS\\VC\\Tools\\MSVC\\14.44.35207'),
            lambda p:self.rebind_crt_plan(p,redistRoot='D:\\OtherVS\\VC\\Redist\\MSVC'),
            lambda p:self.rebind_crt_plan(p,redistVersionDirectory='14.44'),
            lambda p:self.rebind_crt_plan(p,redistVersionDirectory='../14.44.35207'),
            lambda p:self.rebind_crt_plan(p,redistVersionDirectory='v145'),
            lambda p:self.rebind_crt_plan(p,redistFamily='Microsoft.VC145.CRT',
                sourceDirectory='C:\\VS\\VC\\Redist\\MSVC\\14.44.35207\\x64\\Microsoft.VC145.CRT'),
            lambda p:self.rebind_crt_plan(p,redistRoot='D:\\OtherVS\\VC\\Redist\\MSVC',
                sourceDirectory='D:\\OtherVS\\VC\\Redist\\MSVC\\14.44.35207\\x64\\Microsoft.VC143.CRT'),
            lambda p:self.rebind_crt_plan(p,
                sourceDirectory='C:\\VS\\VC\\Redist\\MSVC\\..\\MSVC\\14.44.35207\\x64\\Microsoft.VC143.CRT')])

    def test_v2_crt_plan_accepts_only_producer_supported_version_directory_forms(self):
        module=implementation()
        for directory in ('14.44.35112','14.44.35207','14.44.35207.0','v14.44.35207','V14.44.35207','v143'):
            with self.subTest(directory=directory),tempfile.TemporaryDirectory() as folder:
                _,runtime,path,proof=x64_source_build_fixture(Path(folder))
                self.rebind_crt_plan(proof,redistVersionDirectory=directory,
                    sourceDirectory='C:\\VS\\VC\\Redist\\MSVC\\'+directory+'\\x64\\Microsoft.VC143.CRT')
                pin_source_receipt(runtime,path,proof)
                module.validate_source_build_receipt(runtime,path,architecture='x64')

    def reject_mutations(self,mutations):
        module=implementation()
        with tempfile.TemporaryDirectory() as folder:
            _,runtime,path,original=x64_source_build_fixture(Path(folder))
            for index,mutate in enumerate(mutations):
                with self.subTest(mutation=index):
                    proof=copy.deepcopy(original);mutate(proof);pin_source_receipt(runtime,path,proof)
                    with self.assertRaises(ValueError): module.validate_source_build_receipt(runtime,path,architecture='x64')


if __name__ == '__main__': unittest.main()
