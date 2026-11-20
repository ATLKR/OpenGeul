"""Fail-closed controls for the pinned native activation source preparation."""
import hashlib
import importlib.util
import io
import json
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
        original = '''[package]\nname = "hop-desktop"\nversion = "1.1.3"\n[dependencies]\ntauri = { version = "=2.12.5", features = [] }\nopen = "5"\n[patch.crates-io]\nsvg2pdf = { path = "../../../third_party/rhwp/vendor/svg2pdf" }\n'''
        value = tomllib.loads(h.desktop_manifest(original))
        self.assertNotIn('open', value['dependencies'])
        self.assertEqual(value['target']['cfg(not(windows))']['dependencies']['open'], '5')
        selected = value['target']['cfg(windows)']['dependencies'].get('opengeul-native-open')
        self.assertEqual(selected, {'path': 'opengeul-native/native-open'})
        self.assertNotIn('open', value['target']['cfg(windows)']['dependencies'])
        self.assertEqual(value['dependencies']['tauri']['features'], ['opengeul-store-no-restart'])
        self.assertEqual(value['patch']['crates-io']['tauri']['path'], 'opengeul-native/tauri-2.12.5')
        self.assertEqual(value['workspace']['default-members'], ['.'])
        self.assertEqual(value['workspace']['members'], ['opengeul-native/native-open'])

    def test_native_package_exports_open_without_reusing_registry_dependency_key(self):
        self.helper()
        shim = tomllib.loads((ROOT/'overlay/native-open/Cargo.toml').read_text())
        self.assertEqual(shim['package']['name'], 'opengeul-native-open')
        self.assertEqual(shim.get('lib', {}).get('name'), 'open')

    def test_desktop_manifest_refuses_changed_dependency_or_repeated_application(self):
        h = self.helper()
        original = '[dependencies]\ntauri = { version = "=2.12.5", features = [] }\nopen = "5"\n[patch.crates-io]\n'
        for value in (original.replace('open = "5"', 'open = "6"'), h.desktop_manifest(original)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                h.desktop_manifest(value)

    def test_desktop_manifest_adds_missing_patch_table_for_hop_053(self):
        original = '[dependencies]\ntauri = { version = "=2.12.5", features = [] }\nopen = "5"\n'
        try:
            prepared = self.helper().desktop_manifest(original)
        except ValueError as error:
            self.fail('The new HOP manifest has no existing registry patches: ' + str(error))
        value = tomllib.loads(prepared)
        self.assertEqual(value['patch']['crates-io']['tauri']['path'], 'opengeul-native/tauri-2.12.5')
        self.assertEqual(value['patch']['crates-io']['tauri-runtime-wry']['path'], 'opengeul-native/tauri-runtime-wry-2.12.3')
        self.assertEqual(value['target']['cfg(windows)']['dependencies']['opengeul-native-open']['path'],
                         'opengeul-native/native-open')
        with self.assertRaises(ValueError):
            self.helper().desktop_manifest(prepared)

    def test_security_updated_tauri_keeps_the_reviewed_distinct_runtime_pair(self):
        h=self.helper()
        original='[dependencies]\ntauri = { version = "=2.12.5", features = [] }\nopen = "5"\n'
        prepared=tomllib.loads(h.desktop_manifest(original))
        self.assertEqual(prepared['dependencies']['tauri'],
                         {'version':'=2.12.5','features':['opengeul-store-no-restart']})
        self.assertEqual(prepared['patch']['crates-io'],{
            'tauri':{'path':'opengeul-native/tauri-2.12.5'},
            'tauri-runtime-wry':{'path':'opengeul-native/tauri-runtime-wry-2.12.3'}})
        with self.assertRaises(ValueError):
            h.desktop_manifest(original.replace('2.12.5','2.11.1'))

    def reviewed_mixed_windows_lock(self):
        registry='registry+https://github.com/rust-lang/crates.io-index'
        records=[{'name':'hop-desktop','version':'0.5.3','dependencies':['opengeul-native-open']},
                 {'name':'tauri','version':'2.12.5'},
                 {'name':'tauri-runtime-wry','version':'2.12.3','dependencies':['opengeul-native-open']},
                 {'name':'opengeul-native-open','version':'1.0.0',
                  'dependencies':['windows 0.61.3','windows-future 0.2.1']}]
        bindings=[('windows','0.61.3','9babd3a767a4c1aef6900409f85f5d53ce2544ccdfaa86dad48c91782c6d6893'),
                  ('windows-future','0.2.1','fc6a41e98427b19fe4b73c550f060b59fa592d7d686537eebf9385621bfbad8e'),
                  ('windows','0.62.2','527fadee13e0c05939a6a05d5bd6eec6cd2e3dbd648b9f8e447c6518133d8580'),
                  ('windows-future','0.3.2','e1d6f90251fe18a279739e78025bd6ddc52a7e22f921070ccdc67dde84c605cb'),
                  ('open','5.3.3','43bb73a7fa3799b198970490a51174027ba0d4ec504b03cd08caf513d40024bc')]
        records.extend({'name':name,'version':version,'source':registry,'checksum':checksum}
                       for name,version,checksum in bindings)
        return 'version = 4\n'+''.join('[[package]]\n'+''.join(
            key+' = '+json.dumps(value)+'\n' for key,value in item.items())+'\n' for item in records)

    def test_mixed_windows_bindings_are_exact_and_the_native_shim_keeps_its_abi(self):
        h=self.helper();lock=self.reviewed_mixed_windows_lock()
        self.assertEqual(h.validate_lock(lock),lock)
        changes=[lock.replace('"windows 0.61.3"','"windows 0.62.2"'),
                 lock.replace('"windows-future 0.2.1"','"windows-future 0.3.2"'),
                 lock.replace('name = "tauri"\nversion = "2.12.5"','name = "tauri"\nversion = "2.11.1"'),
                 lock.replace('527fadee13e0c05939a6a05d5bd6eec6cd2e3dbd648b9f8e447c6518133d8580','0'*64),
                 lock.replace('e1d6f90251fe18a279739e78025bd6ddc52a7e22f921070ccdc67dde84c605cb','0'*64),
                 lock.replace('9babd3a767a4c1aef6900409f85f5d53ce2544ccdfaa86dad48c91782c6d6893','0'*64),
                 lock.replace('name = "tauri-runtime-wry"\nversion = "2.12.3"',
                              'name = "tauri-runtime-wry"\nversion = "2.12.5"'),
                 lock.replace('name = "windows"\nversion = "0.62.2"',
                              'name = "windows"\nversion = ["0.62.2"]'),
                 lock.replace('registry+https://github.com/rust-lang/crates.io-index',
                              'registry+https://example.invalid/unreviewed-index',1),
                 lock+'[[package]]\nname = "windows"\nversion = "0.60.0"\n']
        for changed in changes:
            with self.subTest(case=changes.index(changed)),self.assertRaises(ValueError):
                h.validate_lock(changed)

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
version = "2.12.5"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "5fb0244332cfb9cee7e2a568bf5da29a36ed8fdbd717f6f47a66b6b7b358c072"
dependencies = [
 "tauri-runtime-wry",
]

[[package]]
name = "tauri-runtime-wry"
version = "2.12.3"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "e1aa9d8b7a120f879f44fdc1053f7b7dbf416bf0bbc6a72b714dec46b782b52f"
dependencies = [
 "windows 0.62.2",
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

[[package]]
name = "windows"
version = "0.62.2"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "527fadee13e0c05939a6a05d5bd6eec6cd2e3dbd648b9f8e447c6518133d8580"

[[package]]
name = "windows-future"
version = "0.3.2"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "e1d6f90251fe18a279739e78025bd6ddc52a7e22f921070ccdc67dde84c605cb"
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
        self.assertEqual(packages['opengeul-native-open']['dependencies'], ['windows 0.61.3', 'windows-future 0.2.1'])

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
