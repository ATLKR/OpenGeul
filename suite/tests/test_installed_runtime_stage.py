"""Exercise installed-archive staging with small ZIPs, without executing PE code."""
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'suite/engine-build/stage_installed_runtime.py'
REQUIRED = ('program/soffice.bin', 'program/python.exe', 'program/pyuno.pyd',
            'program/ifbclient.dll', 'program/Engine12.dll', 'program/intl/fbintl.dll')


def helper():
    spec = importlib.util.spec_from_file_location('installed_runtime_stage', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def child_environment():
    # The helper imports only stdlib and launches no children.
    return {'PYTHONUTF8': '1'}


class InstalledRuntimeStageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.output = self.root / 'runtime'
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()
        (self.source / 'config_host.mk').write_text(
            'export PRODUCTNAME_WITHOUT_SPACES=LibreOfficeDev\n'
            'export LIBO_VERSION_MAJOR=26\nexport LIBO_VERSION_MINOR=8\n'
            'export LIBO_VERSION_MICRO=1\nexport LIBO_VERSION_PATCH=1\n'
            'export LIBO_VERSION_SUFFIX=\n', encoding='utf-8')
        self.main_root = 'LibreOfficeDev_26.8.1.1_Win_aarch64_archive_en-US_qtz_ko/LibreOfficeDev26.8/'
        self.main = self.archive('LibreOfficeDev', 'en-US_qtz_ko',
                                 'LibreOfficeDev_26.8.1.1_Win_aarch64_archive_en-US_qtz_ko.zip',
                                 {self.main_root + name: b'fixture-' + name.encode() for name in REQUIRED} |
                                 {self.main_root + 'program/mergedlo.dll': b'fixture-native-merged',
                                  self.main_root + 'LICENSE': b'original license',
                                  self.main_root + 'share/registry/Langpack-ko.xcd': b'Korean UI',
                                  self.main_root + 'help/media/common.css': b'common'})
        self.help = {}
        for language in ('en-US', 'ko'):
            prefix = 'LibreOfficeDev_26.8.1.1_Win_aarch64_archive_helppack_' + language + '/LibreOfficeDev26.8/'
            self.help[language] = self.archive('LibreOfficeDev_helppack', language,
                'LibreOfficeDev_26.8.1.1_Win_aarch64_archive_helppack_' + language + '.zip',
                {prefix + 'help/' + language + '/text/shared/main.xhp': language.encode(),
                 prefix + 'help/media/common.css': b'common',
                 prefix + 'program/unrelated.dll': b'help-only metadata must not replace program'})
        raw = self.source / 'instdir/program'
        raw.mkdir(parents=True)
        (raw / 'avmedialo.dll').write_bytes(b'invalid - merged lib\n')

    def archive(self, product, language, filename, entries):
        path = self.source / 'workdir/installation' / product / 'archive/install' / language / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            for name, value in entries.items():
                archive.writestr(name, value)
        return path

    def append(self, path, name, data=b'extra'):
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr(name, data)

    def stage(self, **options):
        module = helper()
        if options:
            self.assertIn('architecture', inspect.signature(module.stage_runtime).parameters,
                          'Staging has no explicit architecture selector')
        return module.stage_runtime(self.source, self.output, self.evidence, **options)

    def reject(self, message, **options):
        with self.assertRaisesRegex((ValueError, FileExistsError), message):
            self.stage(**options)
        receipt = json.loads((self.evidence / 'installed-runtime-stage.json').read_text(encoding='utf-8'))
        self.assertFalse(receipt['passed'])
        self.assertIn('error', receipt)

    def test_stages_distribution_and_two_help_languages_without_developer_markers(self):
        record = self.stage()
        self.assertTrue(record['passed'])
        self.assertEqual(record['mainLanguageDirectory'], 'en-US_qtz_ko')
        self.assertEqual(record['requiredHelpLanguages'], ['en-US', 'ko'])
        self.assertFalse((self.output / 'program/avmedialo.dll').exists())
        self.assertEqual((self.output / 'program/mergedlo.dll').read_bytes(), b'fixture-native-merged')
        self.assertEqual((self.output / 'LICENSE').read_bytes(), b'original license')
        self.assertEqual((self.output / 'share/registry/Langpack-ko.xcd').read_bytes(), b'Korean UI')
        for language in ('en-US', 'ko'):
            self.assertEqual((self.output / 'help' / language / 'text/shared/main.xhp').read_bytes(), language.encode())
        self.assertFalse((self.output / 'program/unrelated.dll').exists())
        self.assertEqual(len(record['identicalCollisions']), 2)
        self.assertEqual(len(record['omittedHelpMembers']), 2)
        self.assertEqual(record['developerMergedMarker']['sha256'], hashlib.sha256(b'invalid - merged lib\n').hexdigest())
        self.assertTrue(all(row['sha256'] and row['archiveMember'] and row['path'] for row in record['files']))
        self.assertEqual(record['archives'][0]['sha256'], hashlib.sha256(self.main.read_bytes()).hexdigest())

    def test_missing_main_is_rejected_before_output_creation(self):
        self.main.unlink()
        self.reject('unique main archive')
        self.assertFalse(self.output.exists())

    def test_ambiguous_main_is_rejected(self):
        self.main.with_name('duplicate.zip').write_bytes(self.main.read_bytes())
        self.reject('unique main archive')

    def test_missing_or_ambiguous_required_help_is_rejected(self):
        self.help['ko'].unlink()
        self.reject('unique ko help archive')

    def test_ambiguous_help_is_rejected(self):
        path = self.help['ko']
        path.with_name('duplicate.zip').write_bytes(path.read_bytes())
        self.reject('unique ko help archive')

    def test_archive_filename_must_match_configured_product_version_and_architecture(self):
        self.main.rename(self.main.with_name(self.main.name.replace('aarch64', 'x86-64')))
        self.reject('main archive identity')

    def test_multiple_runtime_roots_are_rejected(self):
        self.append(self.main, 'another/program/soffice.bin')
        self.reject('unique runtime root')

    def test_missing_required_native_output_is_rejected(self):
        with zipfile.ZipFile(self.main) as archive:
            rows = {item.filename: archive.read(item) for item in archive.infolist()
                    if not item.filename.endswith('/program/ifbclient.dll')}
        self.main.unlink()
        self.archive('LibreOfficeDev', 'en-US_qtz_ko', self.main.name, rows)
        self.reject('program/ifbclient.dll')

    def test_differing_help_overlap_is_rejected(self):
        self.append(self.main, self.main_root + 'help/ko/text/shared/main.xhp', b'different')
        self.reject('Differing installed archive overlap')

    def test_windows_unsafe_and_case_colliding_members_are_rejected(self):
        module = helper()
        for bad in ('../escape.dll', '/absolute.dll', 'C:/escape.dll', 'a\\b.dll',
                    'a/../escape.dll', 'a//b.dll', 'CON.dll', 'a/trailing. ', 'a/ads:stream',
                    'a/./b.dll'):
            with self.subTest(name=bad):
                with self.assertRaisesRegex(ValueError, 'Unsafe Windows ZIP member'):
                    module.safe_member(bad)
        self.append(self.main, self.main_root + 'PROGRAM/mergedlo.dll')
        self.reject('case-insensitive ZIP collision')

    def test_symlink_in_omitted_help_members_is_still_rejected(self):
        info = zipfile.ZipInfo('outside-symlink')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.help['ko'], 'a') as archive:
            archive.writestr(info, '../target')
        self.reject('ZIP links or special files')

    def test_existing_destination_is_preserved(self):
        self.output.mkdir()
        marker = self.output / 'keep'
        marker.write_bytes(b'unchanged')
        self.reject('runtime destination already exists')
        self.assertEqual(marker.read_bytes(), b'unchanged')

    def test_cli_emits_small_summary_bound_to_separate_member_receipt(self):
        result = subprocess.run([sys.executable, str(HELPER), '--source-root', str(self.source),
            '--destination', str(self.output), '--evidence-directory', str(self.evidence)],
            env=child_environment(), check=True, capture_output=True, text=True, timeout=30)
        summary = json.loads(result.stdout)
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['archiveCount'], 3)
        self.assertNotIn('files', summary)
        self.assertLess(len(result.stdout), 4096)
        receipt = Path(summary['receipt']['path'])
        self.assertEqual(summary['receipt']['bytes'], receipt.stat().st_size)
        self.assertEqual(summary['receipt']['sha256'], hashlib.sha256(receipt.read_bytes()).hexdigest())

    def test_help_archive_without_its_claimed_locale_is_rejected(self):
        path = self.help['ko']
        with zipfile.ZipFile(path) as archive:
            rows = {item.filename.replace('/help/ko/', '/help/fr/'): archive.read(item)
                    for item in archive.infolist()}
        path.unlink()
        self.archive('LibreOfficeDev_helppack', 'ko', path.name, rows)
        self.reject('unique ko help runtime root')

    def use_x64_archives(self):
        old_root = self.main_root
        self.main_root = 'LibreOfficeDev_26.8.1.1_Win_x86-64_archive_en-US_ko_qtz/LibreOfficeDev26.8/'
        with zipfile.ZipFile(self.main) as archive:
            rows = {item.filename.replace(old_root, self.main_root): archive.read(item)
                    for item in archive.infolist()}
        self.main.unlink()
        self.main = self.archive('LibreOfficeDev', 'en-US_ko_qtz',
            'LibreOfficeDev_26.8.1.1_Win_x86-64_archive_en-US_ko_qtz.zip', rows)
        for language, path in self.help.items():
            with zipfile.ZipFile(path) as archive:
                rows = {item.filename.replace('Win_aarch64_archive', 'Win_x86-64_archive'): archive.read(item)
                        for item in archive.infolist()}
            path.unlink()
            self.help[language] = self.archive('LibreOfficeDev_helppack', language,
                path.name.replace('Win_aarch64_archive', 'Win_x86-64_archive'), rows)

    def test_explicit_x64_stages_actual_archive_name_and_both_help_languages(self):
        self.use_x64_archives()
        record = self.stage(architecture='x64')
        self.assertTrue(record['passed'])
        self.assertEqual(record['architecture'], 'x64')
        self.assertEqual(record['mainLanguageDirectory'], 'en-US_ko_qtz')
        self.assertEqual(record['requiredHelpLanguages'], ['en-US', 'ko'])
        self.assertEqual(len(record['archives']), 3)
        self.assertEqual(record['archives'][0]['sha256'], hashlib.sha256(self.main.read_bytes()).hexdigest())
        for name in REQUIRED:
            self.assertEqual((self.output/name).read_bytes(), b'fixture-'+name.encode())
        for language in ('en-US', 'ko'):
            self.assertEqual((self.output/'help'/language/'text/shared/main.xhp').read_bytes(), language.encode())
        self.assertFalse((self.output/'program/avmedialo.dll').exists())
        self.assertFalse((self.output/'program/unrelated.dll').exists())

    def test_explicit_arm64_keeps_original_archive_contract(self):
        record = self.stage(architecture='arm64')
        self.assertTrue(record['passed'])
        self.assertEqual(record['architecture'], 'arm64')
        self.assertEqual(record['mainLanguageDirectory'], 'en-US_qtz_ko')
        self.assertEqual(len(record['archives']), 3)
        self.assertEqual(record['requiredHelpLanguages'], ['en-US', 'ko'])

    def test_selected_main_and_help_reject_other_platform_product_or_version(self):
        ordinal = 0
        for architecture in ('arm64', 'x64'):
            if architecture == 'x64': self.use_x64_archives()
            platform = 'aarch64' if architecture == 'arm64' else 'x86-64'
            other = 'x86-64' if architecture == 'arm64' else 'aarch64'
            for role, path in (('main', self.main), ('help', self.help['ko'])):
                for mutation in ('platform', 'product', 'version'):
                    ordinal += 1
                    self.evidence = self.root/('identity-evidence-'+str(ordinal)); self.evidence.mkdir()
                    name = (path.name.replace('Win_'+platform+'_', 'Win_'+other+'_') if mutation == 'platform'
                            else path.name.replace('LibreOfficeDev_', 'LibreOffice_') if mutation == 'product'
                            else path.name.replace('_26.8.1.1_', '_26.8.1.2_'))
                    changed = path.with_name(name)
                    path.rename(changed)
                    try:
                        with self.subTest(architecture=architecture, role=role, mutation=mutation):
                            self.reject(role+' archive identity', architecture=architecture)
                            self.assertFalse(self.output.exists())
                    finally:
                        changed.rename(path)

    def test_unknown_or_untyped_selector_is_rejected_before_staging(self):
        for index, architecture in enumerate((None, True, 0, 'X64', 'aarch64', 'x86-64', 'auto', [], {})):
            self.evidence = self.root/('selector-evidence-'+str(index)); self.evidence.mkdir()
            with self.subTest(selectorCode=index):
                self.reject('architecture', architecture=architecture)
                self.assertFalse(self.output.exists())

    def test_selected_x64_corrupt_member_crc_does_not_qualify(self):
        self.use_x64_archives()
        with zipfile.ZipFile(self.main) as archive:
            info = archive.getinfo(self.main_root+'program/soffice.bin')
        data = bytearray(self.main.read_bytes())
        start = info.header_offset+30+int.from_bytes(data[info.header_offset+26:info.header_offset+28], 'little')
        start += int.from_bytes(data[info.header_offset+28:info.header_offset+30], 'little')
        data[start] ^= 1
        self.main.write_bytes(data)
        with self.assertRaises(zipfile.BadZipFile):
            self.stage(architecture='x64')
        receipt = json.loads((self.evidence/'installed-runtime-stage.json').read_text())
        self.assertFalse(receipt['passed'])
        self.assertTrue(receipt['error'].startswith('BadZipFile:'))

    def test_cli_selected_x64_summary_binds_architecture_and_member_receipt(self):
        self.use_x64_archives()
        result = subprocess.run([sys.executable, str(HELPER), '--source-root', str(self.source),
            '--destination', str(self.output), '--evidence-directory', str(self.evidence),
            '--architecture', 'x64'], env=child_environment(), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, 'Explicit x64 CLI staging failed')
        summary = json.loads(result.stdout)
        self.assertEqual(summary['architecture'], 'x64')
        self.assertEqual(summary['archiveCount'], 3)
        self.assertEqual(summary['requiredHelpLanguages'], ['en-US', 'ko'])
        receipt = Path(summary['receipt']['path']); raw = receipt.read_bytes()
        self.assertEqual(summary['receipt']['bytes'], len(raw))
        self.assertEqual(summary['receipt']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(json.loads(raw)['architecture'], 'x64')

    def test_cli_unknown_selector_does_not_create_stage_output_or_receipt(self):
        for architecture in ('X64', 'auto', 'x86-64', 'ARM64'):
            with self.subTest(selector=architecture):
                result = subprocess.run([sys.executable, str(HELPER), '--source-root', str(self.source),
                    '--destination', str(self.output), '--evidence-directory', str(self.evidence),
                    '--architecture', architecture], env=child_environment(), capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.output.exists())
                self.assertFalse((self.evidence/'installed-runtime-stage.json').exists())


if __name__ == '__main__':
    unittest.main()
