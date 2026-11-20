"""Portable file checks use synthetic native payloads, never user documents."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch
import warnings
import zipfile

from suite import payload
from suite.tests.test_payload import PayloadFixture, digest, pe


SCRIPT = Path(__file__).resolve().parents[1]/'scripts/portable-package-check.py'


def implementation():
    assert SCRIPT.is_file(), 'Portable final-ZIP file check implementation is required'
    spec = importlib.util.spec_from_file_location('portable_package_check', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PortablePackageTests(PayloadFixture):
    def setUp(self):
        super().setUp()
        self.root = self.root.resolve(strict=True)
        self.write('HWP/OpenGeul.exe', pe())
        self.write('HWP/Tools/rhwp.exe', pe())
        self.write('HWP/Notices/OpenGeul-LICENSE.txt', b'Original synthetic HWP license\n')
        self.provenance['hwp'] = {'sha256': 'f'*64, 'url': 'https://example.org/hwp.zip'}
        self.source_archive()
        self.save_metadata()
        self.inventory = payload.create_inventory(self.root)
        self.write_json(payload.INVENTORY, self.inventory)
        self.archive = self.root.parent/'built-suite.zip'
        self.output = self.root.parent/'portable 검증 root'
        self.receipt = self.root.parent/'portable-check.json'
        self.members = [(path.relative_to(self.root).as_posix(), path.read_bytes())
                        for path in sorted(self.root.rglob('*')) if path.is_file()]
        self.zip(self.members)

    def zip(self, members):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, data in members:
                    archive.writestr(name, data)

    def run_check(self, module=None, **overrides):
        options = dict(baseline=self.root, archive=self.archive,
                       output=self.output, receipt=self.receipt)
        options.update(overrides)
        return (module or implementation()).check_package(**options)

    def snapshot(self, root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def assert_no_writes(self, **overrides):
        with self.assertRaises((ValueError, OSError, zipfile.BadZipFile)):
            self.run_check(**overrides)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.receipt.exists())

    def test_relocation_coexistence_and_new_extraction_repair_preserve_original_bytes(self):
        before = self.snapshot(self.root)
        result = self.run_check()
        installed = self.output/'OpenGeul Office 설치 검증'
        repaired = self.output/'OpenGeul Office 복구 검증'
        self.assertEqual(result, json.loads(self.receipt.read_text(encoding='utf-8')))
        self.assertEqual(result['kind'], 'portable-package-file-check')
        self.assertTrue(result['passed'])
        self.assertEqual(result['sourceCommit'], 'a'*40)
        self.assertEqual(result['architecture'], 'x64')
        self.assertEqual(result['archiveSha256'], digest(self.archive.read_bytes()))
        self.assertEqual(result['inventorySha256'], digest(before[payload.INVENTORY]))
        self.assertEqual(result['extractedRoot'], str(installed))
        self.assertEqual(result['repairedRoot'], str(repaired))
        for flag in ('archiveInventoryMatched', 'relocationVerified',
                     'sameVersionCoexistenceVerified', 'corruptionDetected', 'repairVerified'):
            self.assertIs(result[flag], True, flag)
        for flag in ('updateVerified', 'guiVerified'):
            self.assertIs(result[flag], False, flag)
        corruption = result['corruption']
        self.assertIn(corruption['path'], payload.REQUIRED)
        self.assertTrue(corruption['path'].startswith('Office/'))
        after = self.snapshot(installed)
        self.assertEqual(set(after), set(before))
        self.assertEqual([name for name in before if after[name] != before[name]],
                         [corruption['path']])
        with self.assertRaises(ValueError):
            payload.verify_payload(installed, self.inventory)
        payload.verify_payload(repaired, self.inventory)
        self.assertEqual(self.snapshot(repaired), before)
        self.assertEqual(self.snapshot(self.root), before)
        hwp = result['existingHwpPreserved']
        self.assertIs(hwp['passed'], True)
        self.assertEqual(set(hwp['files']), {name for name in before if name.startswith('HWP/')})
        for name, record in hwp['files'].items():
            expected = digest(before[name])
            self.assertEqual(record, {'baselineSha256': expected, 'extractedSha256': expected,
                                      'repairedSha256': expected})

    def test_creation_receipt_is_durable_before_deliberate_corruption(self):
        module = implementation()
        observed = []
        def verify(root, inventory):
            if Path(root) == self.output/'OpenGeul Office 설치 검증' and self.receipt.exists():
                recorded = json.loads(self.receipt.read_text(encoding='utf-8'))
                observed.append(recorded)
                self.assertIs(recorded['passed'], False)
                self.assertEqual(recorded['creationReceipt']['root'], str(root))
                self.assertIs(recorded['creationReceipt']['inventoryVerified'], True)
            return payload.verify_payload(root, inventory)
        with patch.object(module, 'verify_payload', side_effect=verify):
            self.run_check(module)
        self.assertTrue(observed)

    def test_archive_bytes_sizes_inventory_and_extras_fail_before_output(self):
        original = dict(self.members)
        cases = [
            [(name, b'X'*len(data) if name == 'worker/session.py' else data)
             for name, data in self.members],
            [(name, data+b'X' if name == 'worker/session.py' else data)
             for name, data in self.members],
            [(name, data+b' ' if name == payload.INVENTORY else data)
             for name, data in self.members],
            [(name, data) for name, data in self.members if name != 'worker/session.py'],
            self.members+[('Office/extra.txt', b'extra')],
            self.members+[('Office/empty-extra/', b'')],
            self.members+[('worker/session.py', original['worker/session.py'])],
            self.members+[('WORKER/session.py', original['worker/session.py'])],
        ]
        for members in cases:
            with self.subTest(names=[str(name) for name, _ in members][-2:]):
                self.zip(members)
                self.assert_no_writes()

    def test_unsafe_zip_names_kinds_and_aliases_fail_before_output(self):
        names = ('../outside', '/absolute', 'C:/drive', 'Office\\escape',
                 'Office/./alias', 'Office/bad. ', 'Office/CON.txt',
                 'Office/program/SOFFICE.exe', 'office/program/')
        cases = [self.members+[(name, b'unsafe')] for name in names]
        for mode, attributes in ((stat.S_IFLNK | 0o777, 0), (stat.S_IFIFO | 0o600, 0),
                                 (stat.S_IFREG | 0o600, 0x400)):
            member = zipfile.ZipInfo('Office/program/soffice.exe')
            member.external_attr = (mode << 16) | attributes
            cases.append([(member if name == member.filename else name, data)
                          for name, data in self.members])
        for members in cases:
            with self.subTest(last=str(members[-1][0])):
                self.zip(members)
                self.assert_no_writes()
        self.zip(self.members+[('Office/rawXname', b'unsafe')])
        self.archive.write_bytes(self.archive.read_bytes().replace(b'Office/rawXname', b'Office/raw\0name'))
        self.assert_no_writes()

    def test_existing_or_intersecting_destinations_are_never_overwritten(self):
        self.output.mkdir()
        marker = self.output/'keep.txt'; marker.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            self.run_check()
        self.assertEqual(marker.read_bytes(), b'keep')
        self.assertFalse(self.receipt.exists())
        marker.unlink()
        self.output.rmdir()
        self.receipt.write_bytes(b'keep receipt')
        with self.assertRaises(ValueError):
            self.run_check()
        self.assertEqual(self.receipt.read_bytes(), b'keep receipt')
        self.assertFalse(self.output.exists())
        self.receipt.unlink()
        before = self.snapshot(self.root)
        for overrides in ({'output': self.root/'new'}, {'output': self.root.parent},
                          {'receipt': self.output/'receipt.json'},
                          {'receipt': self.root/'receipt.json'},
                          {'output': self.root.parent/'PAYLOAD'}):
            with self.subTest(overrides=overrides):
                self.assert_no_writes(**overrides)
        self.assertEqual(self.snapshot(self.root), before)

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_linked_inputs_and_parents_fail_before_output(self):
        linked_root = self.root.parent/'linked-root'
        linked_zip = self.root.parent/'linked.zip'
        linked_root.symlink_to(self.root, target_is_directory=True)
        linked_zip.symlink_to(self.archive)
        for overrides in ({'baseline': linked_root}, {'archive': linked_zip},
                          {'output': linked_root/'new'}, {'receipt': linked_root/'receipt.json'}):
            with self.subTest(overrides=overrides):
                self.assert_no_writes(**overrides)

    def test_unverified_baseline_and_missing_hwp_do_not_qualify(self):
        self.write('worker/session.py', b'changed baseline')
        self.assert_no_writes()
        self.write('worker/session.py', dict(self.members)['worker/session.py'])
        import shutil
        shutil.rmtree(self.root/'HWP')
        del self.provenance['hwp']
        self.source_archive(); self.save_metadata()
        self.inventory = payload.create_inventory(self.root)
        self.write_json(payload.INVENTORY, self.inventory)
        self.zip([(path.relative_to(self.root).as_posix(), path.read_bytes())
                  for path in self.root.rglob('*') if path.is_file()])
        self.assert_no_writes()

    def test_explicit_parent_directories_are_safe_and_arm64_identity_is_preserved(self):
        self.provenance['architecture'] = 'arm64'
        for name in ('OpenGeul.Office.exe', 'Office/program/soffice.exe',
                     'Office/program/soffice.bin', 'Office/program/python.exe', 'hostfxr.dll',
                     'HWP/OpenGeul.exe', 'HWP/Tools/rhwp.exe'):
            self.write(name, pe(0xaa64))
        self.source_archive(); self.save_metadata()
        self.inventory = payload.create_inventory(self.root, architecture='arm64')
        self.write_json(payload.INVENTORY, self.inventory)
        self.zip([(path.relative_to(self.root).as_posix()+('/' if path.is_dir() else ''),
                   b'' if path.is_dir() else path.read_bytes())
                  for path in sorted(self.root.rglob('*'))])
        result = self.run_check()
        self.assertEqual(result['architecture'], 'arm64')
        payload.verify_payload(Path(result['repairedRoot']), self.inventory)

    def test_zip_change_during_authentication_fails_before_writes(self):
        module = implementation()
        authenticate = module._authenticate
        def changed(source, expected):
            authenticate(source, expected)
            with self.archive.open('ab') as stream:
                stream.write(b'changed ZIP')
        with patch.object(module, '_authenticate', side_effect=changed):
            self.assert_no_writes(module=module)

    def test_zip_replacement_cannot_separate_hashed_archive_from_open_extraction_source(self):
        module = implementation()
        original_hash = module._hash
        replaced = False
        def replace_after_hash(path):
            nonlocal replaced
            result = original_hash(path)
            if Path(path) == self.archive and not replaced:
                replaced = True
                replacement = self.archive.with_suffix('.replacement')
                replacement.write_bytes(self.archive.read_bytes())
                replacement.replace(self.archive)
            return result
        with patch.object(module, '_hash', side_effect=replace_after_hash):
            self.assert_no_writes(module=module)

    def test_additional_optional_file_loss_cannot_qualify_as_one_file_corruption(self):
        module = implementation()
        removed = False
        def remove_after_creation(root, inventory):
            nonlocal removed
            payload.verify_payload(root, inventory)
            if Path(root) == self.output/'OpenGeul Office 설치 검증' and not removed:
                removed = True
                (Path(root)/'hostfxr.dll').unlink()
        with patch.object(module, 'verify_payload', side_effect=remove_after_creation), \
                self.assertRaises(ValueError):
            self.run_check(module)
        self.assertFalse(json.loads(self.receipt.read_text(encoding='utf-8'))['passed'])
        payload.verify_payload(self.root, self.inventory)

    def test_native_resolved_path_alias_cannot_bypass_overlap_checks(self):
        # Linux cannot create Windows 8.3/SUBST aliases; emulate only the native
        # resolver result and keep all actual filesystem operations real.
        resolve = Path.resolve
        def aliased(path, *args, **kwargs):
            if path == self.output:
                return self.root/'aliased-output'
            return resolve(path, *args, **kwargs)
        with patch.object(Path, 'resolve', autospec=True, side_effect=aliased):
            self.assert_no_writes()

    def test_failed_repair_extraction_leaves_an_unqualified_receipt_and_partial_tree(self):
        module = implementation()
        extract = module._extract
        def fail_second(source, expected, destination):
            if destination.name == 'OpenGeul Office 복구 검증':
                destination.mkdir()
                (destination/'partial').write_bytes(b'incomplete')
                raise OSError('synthetic interrupted extraction')
            return extract(source, expected, destination)
        before = self.snapshot(self.root)
        with patch.object(module, '_extract', side_effect=fail_second), self.assertRaises(OSError):
            self.run_check(module)
        recorded = json.loads(self.receipt.read_text(encoding='utf-8'))
        self.assertIs(recorded['passed'], False)
        self.assertIs(recorded['repairVerified'], False)
        self.assertIs(recorded['guiVerified'], False)
        self.assertTrue((self.output/'OpenGeul Office 복구 검증/partial').exists())
        self.assertEqual(self.snapshot(self.root), before)

    def test_cli_produces_receipt_from_final_zip(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--baseline', str(self.root),
            '--archive', str(self.archive), '--output', str(self.output),
            '--receipt', str(self.receipt)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(self.receipt.read_text(encoding='utf-8'))['passed'])


if __name__ == '__main__':
    unittest.main()
