"""Fail-closed controls for the pinned native activation source preparation."""
import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('native_activation', ROOT / 'scripts/native_activation.py') if (ROOT / 'scripts/native_activation.py').exists() else None
native = None
if SPEC:
    native = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(native)


def archive(entries):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as tar:
        for name, content, kind in entries:
            item = tarfile.TarInfo(name)
            if kind == 'link':
                item.type = tarfile.SYMTYPE
                item.linkname = '/etc/passwd'
                tar.addfile(item)
            else:
                data = content.encode()
                item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
    return out.getvalue()


class NativeActivationTests(unittest.TestCase):
    def helper(self):
        self.assertIsNotNone(native, 'native activation source helper is missing')
        return native

    def specification(self, content):
        return {'name': 'owned', 'version': '1.0.0', 'checksum': hashlib.sha256(content).hexdigest(),
                'patches': {'src/lib.rs': {'sha256': hashlib.sha256(b'before\n').hexdigest(),
                    'replacements': [('before\n', 'after\n')]}}}

    def test_vendor_is_deterministic_and_records_every_original_and_patched_file(self):
        h = self.helper()
        content = archive([('owned-1.0.0/src/lib.rs', 'before\n', 'file'),
                           ('owned-1.0.0/LICENSE', 'owned license\n', 'file')])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = h.provision_vendor(content, self.specification(content), root / 'a')
            second = h.provision_vendor(content, self.specification(content), root / 'b')
            self.assertEqual(first, second)
            self.assertEqual((root / 'a/src/lib.rs').read_bytes(), b'after\n')
            self.assertEqual(set(first['originalFiles']), {'src/lib.rs', 'LICENSE'})
            self.assertEqual(first['originalFiles']['LICENSE'], first['preparedFiles']['LICENSE'])
            self.assertNotEqual(first['originalFiles']['src/lib.rs'], first['preparedFiles']['src/lib.rs'])

    def test_checksum_mismatch_does_not_create_destination(self):
        h = self.helper()
        content = archive([('owned-1.0.0/src/lib.rs', 'before\n', 'file')])
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'vendor'
            with self.assertRaises(ValueError):
                h.provision_vendor(content + b'tamper', self.specification(content), destination)
            self.assertFalse(destination.exists())

    def test_unsafe_or_duplicate_entries_are_rejected_before_writing(self):
        h = self.helper()
        bad = [('owned-1.0.0/../escape', 'bad', 'file'),
               ('owned-1.0.0/link', '', 'link'),
               ('/owned-1.0.0/absolute', 'bad', 'file'),
               ('foreign-1.0.0/src/lib.rs', 'bad', 'file'),
               ('owned-1.0.0/src\\escape', 'bad', 'file')]
        base = ('owned-1.0.0/src/lib.rs', 'before\n', 'file')
        for extra in bad + [base, ('owned-1.0.0/SRC/LIB.RS', 'before\n', 'file')]:
            with self.subTest(extra=extra[0]), tempfile.TemporaryDirectory() as tmp:
                content = archive([base, extra])
                destination = Path(tmp) / 'vendor'
                with self.assertRaises(ValueError):
                    h.provision_vendor(content, self.specification(content), destination)
                self.assertFalse(destination.exists())

    def test_changed_or_ambiguous_patch_source_is_rejected(self):
        h = self.helper()
        for text in ('upstream changed\n', 'before\nbefore\n'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                content = archive([('owned-1.0.0/src/lib.rs', text, 'file')])
                spec = self.specification(content)
                # The second case exercises anchor cardinality after an exact source checksum.
                if text.startswith('before'):
                    spec['patches']['src/lib.rs']['sha256'] = hashlib.sha256(text.encode()).hexdigest()
                with self.assertRaises(ValueError):
                    h.provision_vendor(content, spec, Path(tmp) / 'vendor')

    def test_desktop_manifest_keeps_nonwindows_open_and_pins_windows_native_paths(self):
        h = self.helper()
        original = '''[package]\nname = "hop-desktop"\nversion = "1.1.3"\n[dependencies]\ntauri = { version = "=2.11.1", features = [] }\nopen = "5"\n[patch.crates-io]\nsvg2pdf = { path = "../../../third_party/rhwp/vendor/svg2pdf" }\n'''
        value = tomllib.loads(h.desktop_manifest(original))
        self.assertNotIn('open', value['dependencies'])
        self.assertEqual(value['target']['cfg(not(windows))']['dependencies']['open'], '5')
        selected = value['target']['cfg(windows)']['dependencies']['open']
        self.assertEqual(selected, {'package': 'opengeul-native-open', 'path': 'opengeul-native/native-open'})
        self.assertEqual(value['dependencies']['tauri']['features'], ['opengeul-store-no-restart'])
        self.assertEqual(value['patch']['crates-io']['tauri']['path'], 'opengeul-native/tauri-2.11.1')
        self.assertEqual(value['workspace']['default-members'], ['.'])
        self.assertEqual(value['workspace']['members'], ['opengeul-native/native-open'])

    def test_desktop_manifest_refuses_changed_dependency_or_repeated_application(self):
        h = self.helper()
        original = '[dependencies]\ntauri = { version = "=2.11.1", features = [] }\nopen = "5"\n[patch.crates-io]\n'
        for value in (original.replace('open = "5"', 'open = "6"'), h.desktop_manifest(original)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                h.desktop_manifest(value)

    def test_lock_preserves_registry_open_and_replaces_only_pinned_vendored_sources(self):
        h = self.helper()
        original = '''version = 4
[[package]]
name = "hop-desktop"
version = "0.4.5"
dependencies = [
 "open",
 "tauri",
]

[[package]]
name = "open"
version = "5.3.3"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "43bb73a7fa3799b198970490a51174027ba0d4ec504b03cd08caf513d40024bc"

[[package]]
name = "openssl-probe"
version = "0.2.1"

[[package]]
name = "tauri"
version = "2.11.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "b93bd86d231f0a8138f11a02a584769fe4b703dc36ae133d783228dbc4801405"
dependencies = [
 "tauri-runtime-wry",
]

[[package]]
name = "tauri-runtime-wry"
version = "2.11.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "a3989df2ae1c476404fe0a2e8ffc4cfbde97e51efd613c2bb5355fbc9ab52cf0"
dependencies = [
 "windows",
]

[[package]]
name = "windows"
version = "0.61.3"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "9babd3a767a4c1aef6900409f85f5d53ce2544ccdfaa86dad48c91782c6d6893"

[[package]]
name = "windows-future"
version = "0.2.1"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "fc6a41e98427b19fe4b73c550f060b59fa592d7d686537eebf9385621bfbad8e"
'''
        value = tomllib.loads(h.transform_lock(original))
        packages = {p['name']: p for p in value['package'] if p['name'] in ('tauri', 'tauri-runtime-wry', 'open', 'opengeul-native-open', 'hop-desktop')}
        for name in ('tauri', 'tauri-runtime-wry'):
            self.assertNotIn('source', packages[name])
            self.assertNotIn('checksum', packages[name])
        self.assertEqual(packages['open']['version'], '5.3.3')
        self.assertIn('source', packages['open'])
        self.assertIn('opengeul-native-open', packages['hop-desktop']['dependencies'])
        self.assertIn('opengeul-native-open', packages['tauri-runtime-wry']['dependencies'])
        self.assertEqual(packages['opengeul-native-open']['dependencies'], ['windows', 'windows-future'])

    def test_prepared_lock_must_not_downgrade_or_lose_local_dependencies(self):
        h = self.helper()
        original = (ROOT / 'overlay/desktop-cargo.lock.toml').read_text()
        if not any(p['name'] == 'opengeul-native-open' for p in tomllib.loads(original)['package']):
            original = h.transform_lock(original)
        self.assertEqual(h.validate_lock(original), original)
        for value in (original.replace('name = "windows"\nversion = "0.61.3"', 'name = "windows"\nversion = "0.61.2"'),
                      original.replace(' "opengeul-native-open",\n', '', 1)):
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                h.validate_lock(value)

    def test_native_registry_source_checksum_change_is_rejected(self):
        h = self.helper()
        original = (ROOT / 'overlay/desktop-cargo.lock.toml').read_text()
        if not any(p['name'] == 'opengeul-native-open' for p in tomllib.loads(original)['package']):
            original = h.transform_lock(original)
        for checksum in ('9babd3a767a4c1aef6900409f85f5d53ce2544ccdfaa86dad48c91782c6d6893',
                         'fc6a41e98427b19fe4b73c550f060b59fa592d7d686537eebf9385621bfbad8e',
                         '43bb73a7fa3799b198970490a51174027ba0d4ec504b03cd08caf513d40024bc'):
            with self.subTest(checksum=checksum), self.assertRaises(ValueError):
                h.validate_lock(original.replace(checksum, 'a' * 64))


if __name__ == '__main__':
    unittest.main()
