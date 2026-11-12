"""The first upstream install must use the reviewed toolchain, before UI patches."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_upstream


class PnpmInstallOrderTests(unittest.TestCase):
    def test_fetch_only_selects_the_pinned_manager_without_product_patches(self):
        lock = json.loads((ROOT / 'config/upstream.lock.json').read_text())
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'hop'
            original = {'name': 'hop', 'version': lock['hop']['version'],
                        'packageManager': 'pnpm@10.33.0',
                        'dependencies': {'synthetic-package': '1.0.0'},
                        'scripts': {'test:upstream': 'synthetic-test'}}
            def git(*args, cwd):
                if args[:2] == ('git', 'init'):
                    (source / 'package.json').write_text(json.dumps(original))
                if args[:3] == ('git', 'rev-parse', 'HEAD'):
                    return lock['rhwp' if cwd == source / 'third_party/rhwp' else 'hop']['commit']
                return ''
            with mock.patch.object(sys, 'argv', ['prepare_upstream.py', '--fetch-only', '--directory', str(source)]), \
                 mock.patch.object(prepare_upstream.os, 'environ', {}), \
                 mock.patch.object(prepare_upstream, 'run', side_effect=git), \
                 mock.patch.object(prepare_upstream, 'checkout_rhwp'), \
                 mock.patch.object(prepare_upstream, 'port_windows_contract_test'), \
                 mock.patch.object(prepare_upstream, 'patch') as product_patch, \
                 mock.patch.object(prepare_upstream, 'print', create=True):
                prepare_upstream.main()
            product_patch.assert_not_called()
            selected = json.loads((source / 'package.json').read_text())
            self.assertEqual(selected, {**original, 'packageManager': 'pnpm@' + lock['pnpm']})

    def test_selected_manager_is_idempotent_and_does_not_rewrite_locks(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td)
            package = source / 'package.json'
            original = b'{"packageManager":"pnpm@10.34.9","version":"0.5.3"}\n'
            package.write_bytes(original)
            lock = source / 'pnpm-lock.yaml'
            lock.write_bytes(b'owned-synthetic-frozen-lock\n')
            prepare_upstream.pin_package_manager(source, '10.34.9')
            self.assertEqual(package.read_bytes(), original)
            self.assertEqual(lock.read_bytes(), b'owned-synthetic-frozen-lock\n')

    def test_rejects_unpinned_or_prerelease_manager_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td)
            package = source / 'package.json'
            original = b'{"packageManager":"pnpm@10.33.0"}'
            package.write_bytes(original)
            for version in ('latest', '10.34.9-beta.1', '10.34', '', None, True):
                with self.subTest(version=version), self.assertRaises(ValueError):
                    prepare_upstream.pin_package_manager(source, version)
                self.assertEqual(package.read_bytes(), original)

    def test_does_not_convert_a_different_package_manager(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td)
            package = source / 'package.json'
            original = b'{"packageManager":"yarn@4.0.0"}'
            package.write_bytes(original)
            with self.assertRaises(ValueError):
                prepare_upstream.pin_package_manager(source, '10.34.9')
            self.assertEqual(package.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
