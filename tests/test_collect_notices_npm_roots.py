"""Alias diagnostics retain rejection and expose only reviewed public context."""
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import collect_notices as notices


class ReviewedNpmRootDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='private-path-must-not-be-diagnosed-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root/'package'
        self.package.mkdir()
        self.item = {'name': 'rolldown', 'version': '1.2.16', 'license': 'MIT'}
        self.manifest = self.package/'package.json'
        self.manifest.write_text(json.dumps(self.item), encoding='utf-8')
        self.raw = b'Synthetic owned third-party permission notice\n'
        self.notice = self.package/'THIRD-PARTY-LICENSE'
        self.notice.write_bytes(self.raw)
        self.pin = {'license': 'MIT',
                    'manifestSha256': hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
                    'sourcePath': self.notice.name,
                    'sourceSha256': hashlib.sha256(self.raw).hexdigest(),
                    'noticeSha256': hashlib.sha256(self.raw).hexdigest(),
                    'packageLicenseText': False,
                    'sourceUrl': 'https://example.invalid/owned-notice',
                    'packageProvenance': {'testFixture': 'synthetic'}}
        self.enterContext(patch.object(notices, 'REVIEWED_SOURCE_NOTICES',
            {('npm', 'rolldown'): {'1.2.16': self.pin}}))
        self.out = self.root/'out'

    def collect(self, location=None, item=None):
        return notices.collect_reviewed_notices('npm', item or self.item,
            location or self.package, self.out)

    def rejected_context(self, role, kind, *, location=None, input_kind='manifest', reparse_tag=None):
        with self.assertRaises(ValueError) as caught:
            self.collect(location)
        message = str(caught.exception)
        self.assertIn('noticeContext=', message)
        expected = {'ecosystem': 'npm', 'package': 'rolldown', 'version': '1.2.16',
                    'input': input_kind, 'role': role, 'kind': kind}
        if reparse_tag is not None:
            expected['reparseTag'] = reparse_tag
        self.assertEqual(json.loads(message.split('noticeContext=', 1)[1]), expected)
        self.assertNotIn(str(self.root), message)
        self.assertLess(len(message.encode('utf-8')), 512)
        self.assertFalse(self.out.exists(), 'Rejected input must not emit a notice')

    def test_real_root_alias_reports_public_context_without_accepting_it(self):
        alias = self.root/'dependency-alias'
        alias.symlink_to(self.package, target_is_directory=True)
        self.rejected_context('root', 'symlink', location=alias)

    def test_real_manifest_leaf_alias_is_not_confused_with_package_root(self):
        target = self.root/'same-manifest-bytes'
        target.write_bytes(self.manifest.read_bytes())
        self.manifest.unlink()
        self.manifest.symlink_to(target)
        self.rejected_context('leaf', 'symlink')

    def test_intermediate_notice_alias_stays_rejected_with_a_distinct_role(self):
        directory = self.root/'same-notice-bytes'
        directory.mkdir()
        (directory/'NOTICE').write_bytes(self.raw)
        (self.package/'nested').symlink_to(directory, target_is_directory=True)
        self.pin['sourcePath'] = 'nested/NOTICE'
        self.rejected_context('intermediate', 'symlink', input_kind='notice')

    def test_windows_reparse_attribute_reports_its_kind_without_a_symlink_claim(self):
        original = Path.lstat

        def observed(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.package:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=0x400)
            return info

        with patch.object(Path, 'lstat', observed):
            self.rejected_context('root', 'reparse')

    def test_observed_windows_mount_point_tag_is_reported_without_resolving_an_alias(self):
        original = Path.lstat

        def observed(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.package:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700,
                    st_file_attributes=0x400, st_reparse_tag=0xA0000003)
            return info

        with patch.object(Path, 'lstat', observed), \
             patch.object(Path, 'resolve', side_effect=AssertionError('Rejected alias must not be resolved')):
            self.rejected_context('root', 'reparse', reparse_tag=0xA0000003)

    def test_regular_reviewed_bytes_and_declared_license_scope_are_unchanged(self):
        records = self.collect()
        self.assertEqual(len(records), 1)
        self.assertEqual((self.out/records[0]['file']).read_bytes(), self.raw)
        self.assertFalse(records[0]['packageLicenseText'])
        self.assertEqual(records[0]['packageProvenance'], {'testFixture': 'synthetic'})

    def test_unreviewed_version_or_license_fails_before_context_or_notice_writes(self):
        for item in ({**self.item, 'version': '9.9.9'}, {**self.item, 'license': 'Other'}):
            with self.subTest(field=item), self.assertRaises(ValueError) as caught:
                self.collect(item=item)
            self.assertNotIn('noticeContext=', str(caught.exception))
            self.assertFalse(self.out.exists())

    def test_changed_or_oversized_reviewed_bytes_still_cannot_emit_a_notice(self):
        for raw in (self.raw+b'changed', b'x'*2_000_001):
            self.notice.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.collect()
            self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
