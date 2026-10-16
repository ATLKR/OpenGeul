"""Fresh-path packaging must reject bad inputs before touching a runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from suite.tests.test_payload import pe

VC_DLLS = ('concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
           'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll',
           'vcruntime140_1.dll', 'vcruntime140_threads.dll')

ROOT = Path(__file__).resolve().parents[2]


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
            def recover(msi, destination):
                self.assertEqual(msi, archive)
                destination.mkdir()
                result = {}
                for name in module.MSI_VC_DEPENDENCIES:
                    destination.joinpath(name).write_bytes(pe(dll=True))
                    result[name] = {'path': destination/name, 'fileId': name+'_amd64.GUID', 'cabinet':'#official.cab'}
                return result
            with patch.object(module, 'os', SimpleNamespace(name='nt')), \
                 patch.object(module.subprocess, 'run', side_effect=admin), \
                 patch('suite.msi_cab.recover_x64_crt', side_effect=recover) as recovered:
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
            def recover(msi, destination):
                destination.mkdir()
                for name in VC_DLLS: (destination/name).write_bytes(pe(dll=True))
                return {name: {'path': destination/name, 'fileId': name+'_amd64.GUID',
                               'cabinet': '#official.cab'} for name in VC_DLLS}
            with patch.object(module, 'os', SimpleNamespace(name='nt')), \
                 patch.object(module.subprocess, 'run', side_effect=administrative_extract), \
                 patch('suite.msi_cab.recover_x64_crt', side_effect=recover):
                runtime = module.extract_msi(archive, output)
            receipt = json.loads((runtime/'opengeul-msi-dependencies.json').read_text())
            self.assertEqual(receipt['schemaVersion'], 1)
            self.assertEqual(receipt['architecture'], 'x64')
            self.assertEqual(set(receipt['files']), {'program/'+name for name in VC_DLLS})
            self.assertTrue(all((runtime/path).is_file() for path in receipt['files']))
            self.assertEqual(archive.read_bytes(), b'authenticated input unchanged')

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


if __name__ == '__main__': unittest.main()
