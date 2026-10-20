"""Fresh-path packaging must reject bad inputs before touching a runtime."""
import hashlib
import copy
import io
import importlib.util
import inspect
import json
from pathlib import Path
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


if __name__ == '__main__': unittest.main()
