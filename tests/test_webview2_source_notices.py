import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import collect_notices as notices

REGISTRY = 'registry+https://github.com/rust-lang/crates.io-index'


class WebView2SourceNoticeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root/'source'; self.source.mkdir()
        self.repo = self.root/'repo'; (self.repo/'overlay').mkdir(parents=True)
        self.packages = []
        self.locations = {}
        self.pins = {}
        self.number = 0
        for name in ['skia-safe', 'skia-bindings']:
            self.add_package(name, '0.156.0', 'MIT')
        self.add_package('unreviewed-same-spdx', '1.0.0', 'MIT')
        paths = {'webview2-com': 'crates/webview2-com', 'webview2-com-sys': 'crates/bindings',
                 'webview2-com-macros': 'crates/callback-macros'}
        for index, (name, source_path) in enumerate(paths.items()):
            version = '0.8.1' if name.endswith('macros') else '0.39.1'
            directory, item = self.add_package(name, version, 'MIT')
            commit = ('b' if name.endswith('macros') else 'a')*40
            (directory/'Cargo.toml.orig').write_text('[package]\nname = '+json.dumps(name)+'\nlicense.workspace = true\n')
            (directory/'.cargo_vcs_info.json').write_text(json.dumps({'git': {'sha1': commit}, 'path_in_vcs': source_path}))
            self.pins[name] = {'version': version, 'checksum': chr(ord('c')+index)*64,
                'normalizedManifestSha256': self.sha(directory/'Cargo.toml'),
                'originalManifestSha256': self.sha(directory/'Cargo.toml.orig'),
                'vcsSha256': self.sha(directory/'.cargo_vcs_info.json'),
                'sourceCommit': commit, 'sourcePath': source_path,
                'workspaceManifestSha256': 'f'*64}
        self.lock = self.repo/'overlay/desktop-cargo.lock.toml'
        self.lock.write_text('version = 3\n'+''.join('\n[[package]]\nname = '+json.dumps(name)+'\nversion = '+json.dumps(pin['version'])+'\nsource = '+json.dumps(REGISTRY)+'\nchecksum = '+json.dumps(pin['checksum'])+'\n' for name, pin in self.pins.items()))
        self.mit = self.notice('notices/webview2-rs-LICENSE.txt', b'Synthetic owned MIT permission and copyright\n')
        sdk_files = [self.notice('notices/SDK-LICENSE.txt', b'Synthetic official SDK terms\n'),
                     self.notice('notices/SDK-NOTICE.txt', b'Synthetic SDK component notice\n')]
        for record, member in zip(sdk_files, ['LICENSE.txt', 'NOTICE.txt']): record['archiveMember'] = member
        assets = {}
        sysdir = self.locations['webview2-com-sys']
        for arch in ['arm64', 'x64', 'x86']:
            for filename in ['WebView2Loader.dll', 'WebView2Loader.dll.lib', 'WebView2LoaderStatic.lib']:
                relative = arch+'/'+filename; data = b'\xff\x00synthetic-sdk-'+relative.encode()
                path = sysdir/relative;path.parent.mkdir(exist_ok=True);path.write_bytes(data)
                assets[relative] = {'bytes': len(data), 'sha256': self.sha(path)}
        self.sdk = {'version': '1.0.3800.47', 'archiveSha256': '1'*64,
            'sourceUrl': 'https://example.com/synthetic-sdk.nupkg', 'files': sdk_files, 'assets': assets}
        self.enterContext(patch.object(notices, 'ROOT', self.repo))
        self.enterContext(patch.object(notices, 'WEBVIEW2_NOTICE_PINS', self.pins, create=True))
        self.enterContext(patch.object(notices, 'WEBVIEW2_MIT_NOTICE', self.mit, create=True))
        self.enterContext(patch.object(notices, 'WEBVIEW2_SDK_NOTICE', self.sdk, create=True))

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def notice(self, name, data):
        path = self.repo/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(data)
        return {'path': name, 'sha256': self.sha(path)}

    def add_package(self, name, version, license):
        directory = self.source/(name+'-'+version);directory.mkdir()
        manifest = directory/'Cargo.toml'
        manifest.write_text('[package]\nname = '+json.dumps(name)+'\nversion = '+json.dumps(version)+'\nlicense = '+json.dumps(license)+'\n')
        item = {'id': name+'@'+version, 'name': name, 'version': version, 'license': license,
                'source': REGISTRY, 'manifest_path': str(manifest), 'license_file': None}
        self.packages.append(item);self.locations[name] = directory
        return directory, item

    def collect(self):
        self.number += 1;self.output = self.root/('output-'+str(self.number))
        metadata = SimpleNamespace(stdout=json.dumps({'packages': self.packages}))
        with patch.object(notices.subprocess, 'run', return_value=metadata), \
             patch.object(sys, 'argv', ['collect_notices.py', '--source', str(self.source), '--out', str(self.output)]), \
             contextlib.redirect_stdout(io.StringIO()):
            notices.main()
        return json.loads((self.output/'inventory.json').read_text())

    def test_explicit_inherited_mit_is_copied_for_exactly_three_crates(self):
        result = self.collect()
        for name, pin in self.pins.items():
            row = next(row for row in result['packages'] if row['name'] == name)
            self.assertEqual(row['texts'], ['reviewed/webview2-rs-LICENSE.txt'])
            text = self.output/('cargo-'+name+'-'+pin['version'])/row['texts'][0]
            self.assertEqual(text.read_bytes(), b'Synthetic owned MIT permission and copyright\n')
            self.assertEqual(row['declaredLicense'], 'MIT')
        self.assertEqual(result['status'], 'requires-human-review')
        self.assertEqual(len(result['packages']), 6)
        self.assertEqual(sum(not row['texts'] for row in result['packages']), 1)

    def test_sys_sdk_license_and_notice_are_additional_to_rust_mit(self):
        result = self.collect();row = next(row for row in result['packages'] if row['name'] == 'webview2-com-sys')
        extra = row.get('additionalNotices', [])
        self.assertEqual(len(extra), 2)
        actual = {entry['sourceArchiveMember']:(self.output/'cargo-webview2-com-sys-0.39.1'/entry['file']).read_bytes() for entry in extra}
        self.assertEqual(actual, {'LICENSE.txt': b'Synthetic official SDK terms\n', 'NOTICE.txt': b'Synthetic SDK component notice\n'})
        self.assertEqual(row['texts'], ['reviewed/webview2-rs-LICENSE.txt'])
        self.assertTrue(all(not entry['packageLicenseText'] for entry in extra))

    def test_manifest_vcs_notice_and_each_binary_asset_byte_mutation_is_rejected(self):
        cases = []
        for name, directory in self.locations.items():
            if name in self.pins:
                cases.extend((directory/file, name) for file in ['Cargo.toml', 'Cargo.toml.orig', '.cargo_vcs_info.json'])
        cases.append((self.repo/self.mit['path'], 'webview2-com'))
        cases.extend((self.repo/entry['path'], 'webview2-com-sys') for entry in self.sdk['files'])
        cases.extend((self.locations['webview2-com-sys']/path, 'webview2-com-sys') for path in self.sdk['assets'])
        for path, name in cases:
            original = path.read_bytes();path.write_bytes(bytes([original[0]^1])+original[1:])
            try:
                with self.subTest(name=name, file=path.name), self.assertRaises(ValueError): self.collect()
                self.assertFalse((self.output/('cargo-'+name+'-'+self.pins[name]['version'])/'reviewed').exists())
            finally: path.write_bytes(original)

    def test_missing_wrong_or_duplicate_lock_checksum_fails_closed(self):
        original = self.lock.read_text()
        for changed in ['version = 3\n', original.replace('c'*64, '0'*64), original+original.split('version = 3\n')[1]]:
            self.lock.write_text(changed)
            try:
                with self.subTest(case=changed[:12]), self.assertRaises(ValueError): self.collect()
            finally: self.lock.write_text(original)

    def test_wrong_version_license_or_registry_source_is_not_accepted(self):
        for item in self.packages:
            if item['name'] not in self.pins: continue
            for field, changed in [('version','9.9.9'),('license','Apache-2.0'),('source',None)]:
                original = item[field];item[field] = changed
                try:
                    with self.subTest(package=item['name'], field=field), self.assertRaises(ValueError): self.collect()
                finally: item[field] = original

    def test_inheritance_and_vcs_semantics_remain_required_if_one_byte_pin_is_renewed(self):
        name='webview2-com';directory=self.locations[name];pin=self.pins[name]
        cases=[('Cargo.toml.orig','originalManifestSha256',b'[package]\nlicense = "MIT"\n'),
               ('.cargo_vcs_info.json','vcsSha256',json.dumps({'git':{'sha1':'z'*40},'path_in_vcs':pin['sourcePath']}).encode())]
        for filename, field, changed in cases:
            path=directory/filename;original=path.read_bytes();old_hash=pin[field];path.write_bytes(changed);pin[field]=self.sha(path)
            try:
                with self.subTest(filename=filename),self.assertRaises(ValueError):self.collect()
            finally:path.write_bytes(original);pin[field]=old_hash

    def test_aliases_and_reviewed_path_escape_are_rejected(self):
        for path in [self.repo/self.mit['path'], self.locations['webview2-com-sys']/'x64/WebView2LoaderStatic.lib']:
            original=path.read_bytes();target=self.root/'alias';target.write_bytes(original);path.unlink();path.symlink_to(target)
            try:
                with self.subTest(file=path.name),self.assertRaises(ValueError):self.collect()
            finally:path.unlink();path.write_bytes(original)
        original=self.mit['path'];self.mit['path']='../outside-LICENSE'
        try:
            with self.assertRaises(ValueError):self.collect()
        finally:self.mit['path']=original

    def test_same_spdx_unreviewed_package_is_not_assigned_the_common_text(self):
        (self.source/'LICENSE').write_bytes(b'Synthetic ancestor MIT text\n')
        result=self.collect();row=next(row for row in result['packages'] if row['name']=='unreviewed-same-spdx')
        self.assertEqual(row['texts'],[])
        self.assertNotIn('reviewedNotices',row)


if __name__=='__main__':unittest.main()
