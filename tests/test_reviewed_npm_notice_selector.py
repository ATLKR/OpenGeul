"""The finite pnpm caller adapter never grants reviewed input alias permission."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
from pathlib import PureWindowsPath
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import collect_notices as notices


class ReviewedNpmNoticeSelectorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='owned-npm-selector-')
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'source'
        self.store = self.source / 'node_modules/.pnpm'
        self.store.mkdir(parents=True)
        self.item = {'name': 'rolldown', 'version': '1.2.16', 'license': 'MIT'}
        self.canonical = self.store / 'rolldown@1.2.16/node_modules/rolldown'
        self.host = self.store / 'vite@8.3.6/node_modules/vite'
        self.canonical.mkdir(parents=True)
        self.host.mkdir(parents=True)
        self.manifest = self.canonical / 'package.json'
        self.manifest.write_text(json.dumps(self.item), encoding='utf-8')
        self.raw = b'Synthetic reviewed additional notice\n'
        (self.canonical / 'THIRD-PARTY-LICENSE').write_bytes(self.raw)
        self.host_manifest = self.host / 'package.json'
        self.host_manifest.write_text(json.dumps({'name': 'vite', 'version': '8.3.6'}), encoding='utf-8')
        self.alias = self.host.parent / 'rolldown'
        self.alias.symlink_to('../../rolldown@1.2.16/node_modules/rolldown', target_is_directory=True)
        self.source_manifest = self.source / 'package.json'
        self.source_manifest.write_text(json.dumps({'packageManager': 'pnpm@10.34.9'}), encoding='utf-8')
        self.lock = b'Synthetic frozen public pnpm graph\n'
        (self.source / 'pnpm-lock.yaml').write_bytes(self.lock)
        (self.store / 'lock.yaml').write_bytes(self.lock)
        self.modules = self.source / 'node_modules/.modules.yaml'
        self.modules.write_text(json.dumps({'packageManager': 'pnpm@10.34.9', 'layoutVersion': 5,
            'nodeLinker': 'isolated', 'virtualStoreDir': '.pnpm'}), encoding='utf-8')
        self.pin = {'license': 'MIT', 'manifestSha256': self.digest(self.manifest.read_bytes()),
            'sourcePath': 'THIRD-PARTY-LICENSE', 'sourceSha256': self.digest(self.raw),
            'noticeSha256': self.digest(self.raw), 'packageLicenseText': False,
            'sourceUrl': 'https://example.invalid/synthetic-public-notice',
            'packageProvenance': {'synthetic': True}}
        self.enterContext(patch.object(notices, 'REVIEWED_SOURCE_NOTICES',
            {('npm', 'rolldown'): {'1.2.16': self.pin}}))
        self.enterContext(patch.object(notices, 'REVIEWED_NPM_LOCK_SHA256', self.digest(self.lock), create=True))
        self.enterContext(patch.object(notices, 'REVIEWED_NPM_ROOTS',
            {('rolldown', '1.2.16'): {'slot': 'rolldown@1.2.16', 'callerSlot': 'vite@8.3.6',
                'callerName': 'vite', 'callerVersion': '8.3.6',
                'callerManifestSha256': self.digest(self.host_manifest.read_bytes())}}, create=True))
        self.output = self.source.parent / 'out'

    @staticmethod
    def digest(raw):
        return hashlib.sha256(raw).hexdigest()

    def select(self, manifest=None, item=None):
        return notices.reviewed_npm_notice_location(self.source,
            manifest if manifest is not None else self.alias / 'package.json',
            item if item is not None else self.item)

    def rejected(self, manifest=None, item=None):
        with self.assertRaises(ValueError) as caught:
            self.select(manifest, item)
        self.assertNotIn(str(self.source), str(caught.exception))
        self.assertFalse(self.output.exists(), 'Rejected selection cannot emit notices')

    def test_main_keeps_records_and_uses_only_the_regular_owned_notice_source(self):
        nested = self.canonical / 'vendor/embedded/package.json'
        nested.parent.mkdir(parents=True)
        nested.write_text(json.dumps({'name': 'synthetic-nested', 'version': '1'}), encoding='utf-8')
        manifests = [self.manifest, self.alias / 'package.json', nested]
        original_glob = Path.glob

        def glob(path, pattern, **kwargs):
            if path == self.store and pattern == '*/node_modules/**/package.json':
                return iter(manifests)
            return original_glob(path, pattern, **kwargs)

        with patch.object(Path, 'glob', glob), \
             patch.object(notices.subprocess, 'run', return_value=type('Result', (), {'stdout': '{"packages":[]}'})()), \
             patch.object(notices, 'collect_cargo', return_value=[]), \
             patch.object(sys, 'argv', ['collect_notices', '--source', str(self.source), '--out', str(self.output)]), \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                notices.main()
            except ValueError:
                self.fail('The finite valid dependency caller must select its regular owned notice source')
        inventory = json.loads((self.output / 'inventory.json').read_text())
        self.assertEqual(inventory['status'], 'requires-human-review')
        self.assertEqual([(r['name'], r['version']) for r in inventory['packages']],
            [('rolldown', '1.2.16'), ('rolldown', '1.2.16'), ('synthetic-nested', '1')])
        self.assertTrue(all(not r['texts'] for r in inventory['packages']))
        for record in inventory['packages'][:2]:
            additional = record['additionalNotices'][0]
            self.assertFalse(additional['packageLicenseText'])
            self.assertEqual(additional['packageProvenance'], {'synthetic': True})
            self.assertEqual((self.output / 'npm-rolldown-1.2.16' / additional['file']).read_bytes(), self.raw)

    def test_regular_owned_root_and_known_dependency_alias_select_the_same_regular_source(self):
        self.assertTrue(self.select(self.manifest) == self.canonical, 'Regular source identity differs')
        self.assertTrue(self.select() == self.canonical, 'Dependency caller source identity differs')

    def test_direct_reviewed_collector_still_rejects_the_dependency_alias(self):
        with self.assertRaises(notices.ReviewedNoticeAliasError):
            notices.collect_reviewed_notices('npm', self.item, self.alias, self.output)
        self.assertFalse(self.output.exists())

    def test_unreviewed_package_does_not_inspect_the_pnpm_layout(self):
        self.modules.unlink()
        manifest = self.source / 'unrelated/package.json'
        selected = self.select(manifest, {'name': 'unrelated', 'version': '1', 'license': 'MIT'})
        self.assertTrue(selected == manifest.parent, 'Unreviewed caller changed')

    def test_external_alias_target_is_rejected_even_with_identical_manifest_bytes(self):
        external = self.source.parent / 'external'
        external.mkdir()
        (external / 'package.json').write_bytes(self.manifest.read_bytes())
        self.alias.unlink()
        self.alias.symlink_to(external, target_is_directory=True)
        self.rejected()

    def test_alias_cycle_is_rejected_without_reading_its_manifest(self):
        self.alias.unlink()
        self.alias.symlink_to('rolldown', target_is_directory=True)
        self.rejected()

    def test_unsupported_absolute_posix_link_is_not_normalized_into_permission(self):
        self.alias.unlink()
        self.alias.symlink_to(self.canonical, target_is_directory=True)
        self.rejected()

    def test_canonical_root_alias_is_rejected(self):
        moved = self.canonical.with_name('moved')
        self.canonical.rename(moved)
        self.canonical.symlink_to(moved, target_is_directory=True)
        self.rejected()

    def test_ancestor_alias_is_rejected(self):
        original = self.source / 'node_modules'
        moved = self.source / 'moved-modules'
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        self.rejected()

    def test_manifest_leaf_alias_is_rejected_even_with_exact_bytes(self):
        target = self.canonical / 'same-bytes.json'
        self.manifest.rename(target)
        self.manifest.symlink_to(target.name)
        self.rejected()

    def test_unknown_caller_and_nested_manifest_cannot_borrow_a_reviewed_notice(self):
        for relative in ['other@1/node_modules/rolldown/package.json',
                         'rolldown@1.2.16/node_modules/rolldown/vendor/package.json']:
            with self.subTest(case=relative.split('/')[0]):
                self.rejected(self.store / relative)

    def test_peer_or_hashed_additional_slot_is_ambiguous_even_when_exact_slot_exists(self):
        for suffix in ['_peer@1', '_0123456789abcdef0123456789abcdef']:
            extra = self.store / ('rolldown@1.2.16' + suffix)
            extra.mkdir()
            self.rejected(self.manifest)
            extra.rmdir()

    def test_case_colliding_owned_slot_is_ambiguous_on_every_host(self):
        (self.store / 'ROLLDOWN@1.2.16').mkdir()
        self.rejected(self.manifest)

    def test_missing_owned_root_cannot_fall_back_to_the_dependency_alias(self):
        self.manifest.unlink()
        self.rejected()

    def test_package_manager_and_layout_mismatches_are_rejected(self):
        for field, value in [('packageManager', 'pnpm@99.0.0'), ('layoutVersion', True),
                             ('nodeLinker', 'hoisted'), ('virtualStoreDir', '../outside')]:
            obj=json.loads(self.modules.read_text()); original=obj[field]; obj[field]=value
            self.modules.write_text(json.dumps(obj))
            self.rejected()
            obj[field]=original; self.modules.write_text(json.dumps(obj))

    def test_unrecognized_modules_encoding_does_not_get_a_yaml_fallback(self):
        self.modules.write_text('nodeLinker: isolated\npackageManager: pnpm@10.34.9\n')
        self.rejected()

    def test_root_and_installed_locks_are_both_exact_frozen_public_bytes(self):
        for path in [self.source / 'pnpm-lock.yaml', self.store / 'lock.yaml']:
            path.write_bytes(self.lock + b'changed')
            self.rejected()
            path.write_bytes(self.lock)

    def test_manifest_and_host_fingerprints_cannot_be_replaced_by_valid_canonical_notice_bytes(self):
        for path in [self.manifest, self.host_manifest]:
            original=path.read_bytes(); path.write_bytes(original + b' ')
            self.rejected()
            path.write_bytes(original)

    def test_changed_declared_license_fails_before_root_selection(self):
        self.rejected(item={**self.item, 'license': 'Other'})

    def test_observed_link_is_read_once_and_cannot_change_during_selection(self):
        original = os.readlink
        calls = []

        def changed(path):
            calls.append(1)
            target = original(path)
            path.unlink()
            path.symlink_to('../../rolldown@1.2.16/node_modules/rolldown/', target_is_directory=True)
            return target

        with patch.object(os, 'readlink', changed):
            self.rejected()
        self.assertEqual(len(calls), 1)

    def test_bounded_readlink_rejects_oversized_or_noncanonical_text(self):
        for target in ['x' * 32768, '../../rolldown@1.2.16/node_modules/rolldown/../rolldown']:
            with patch.object(os, 'readlink', return_value=target):
                self.rejected()

    def test_canonical_manifest_keeps_the_existing_two_megabyte_bound(self):
        self.manifest.write_bytes(b'x' * 2_000_001)
        self.rejected()

    def test_source_package_manager_mismatch_is_rejected(self):
        self.source_manifest.write_text(json.dumps({'packageManager': 'pnpm@99.0.0'}))
        self.rejected()

    def test_an_ordinary_copy_at_the_dependency_caller_is_not_a_pnpm_link(self):
        self.alias.unlink()
        self.alias.mkdir()
        (self.alias / 'package.json').write_bytes(self.manifest.read_bytes())
        self.rejected()

    def test_missing_metadata_and_source_lock_alias_are_rejected(self):
        self.modules.unlink()
        self.rejected()
        self.modules.write_text(json.dumps({'packageManager': 'pnpm@10.34.9', 'layoutVersion': 5,
            'nodeLinker': 'isolated', 'virtualStoreDir': '.pnpm'}))
        lock = self.source / 'pnpm-lock.yaml'
        target = self.source / 'same-lock-bytes'
        lock.rename(target)
        lock.symlink_to(target.name)
        self.rejected()

    def test_filesystem_rejection_traceback_does_not_disclose_input_paths(self):
        self.modules.unlink()
        rendered = None
        try:
            self.select()
        except ValueError as error:
            rendered = ''.join(traceback.format_exception(error))
        self.assertIsNotNone(rendered, 'Missing metadata must be rejected')
        self.assertFalse(str(self.source) in rendered, 'Selector exception chain must not disclose input paths')

    def test_observed_target_file_identity_must_match_the_owned_root(self):
        original = Path.stat

        def wrong(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.alias and kwargs.get('follow_symlinks', True):
                return type('WrongIdentity', (), {'st_dev': info.st_dev, 'st_ino': info.st_ino + 1})()
            return info

        with patch.object(Path, 'stat', wrong):
            self.rejected()

    def test_linking_from_a_path_outside_the_owned_store_is_rejected(self):
        outside = self.source.parent / 'package.json'
        self.rejected(outside)

    def test_unknown_reviewed_version_keeps_the_existing_version_rejection(self):
        item = {**self.item, 'version': '9.9.9'}
        location = self.select(item=item)
        with self.assertRaises(ValueError):
            notices.collect_reviewed_notices('npm', item, location, self.output)
        self.assertFalse(self.output.exists())

    def test_windows_junction_text_accepts_only_the_pinned_local_drive_target(self):
        caller = PureWindowsPath('C:/owned/node_modules/.pnpm/vite@8.3.6/node_modules/rolldown')
        canonical = PureWindowsPath('C:/owned/node_modules/.pnpm/rolldown@1.2.16/node_modules/rolldown')
        for text in [str(canonical), str(canonical) + '\\', '\\\\?\\' + str(canonical),
                     '\\\\?\\' + str(canonical) + '\\']:
            self.assertTrue(notices._npm_exact_link_target(caller, text, canonical, windows=True),
                'Pinned Windows target spelling was not recognized')
        for text in [str(canonical).replace('C:', 'D:'), '../rolldown',
                     '\\\\server\\share\\rolldown', '\\\\.\\' + str(canonical),
                     str(canonical) + '\\..\\rolldown', str(canonical) + '\\\\']:
            self.assertFalse(notices._npm_exact_link_target(caller, text, canonical, windows=True),
                'Unsupported Windows target spelling was accepted')


if __name__ == '__main__':
    unittest.main()
