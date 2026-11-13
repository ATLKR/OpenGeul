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


class ReviewedNoticeGapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        self.source.mkdir()
        self.packages = []
        self.items = {}
        self.locations = {}
        self.pins = {}
        self.run_number = 0
        for name in ['skia-safe', 'skia-bindings']:
            self.add_cargo(name, '0.156.0', 'MIT')
        self.add_cargo('unreviewed-source', '1.0.0', None)
        for version in ['5.3.0', '6.0.0']:
            directory, item = self.add_cargo('r-efi', version, 'MIT OR Apache-2.0 OR LGPL-2.1-or-later')
            self.add_pin('cargo', item, directory, 'AUTHORS', b'Synthetic owned permission and copyright\n', True)
        for name, text in [('rolldown', b'Synthetic additional third-party notice\n'),
                           ('stackback', b'// Synthetic copyright\n// Synthetic permission\n\nfunction MUST_NOT_SHIP() {}\n')]:
            directory = self.source/'node_modules/.pnpm'/(name+'@1.0.0')/'node_modules'/name
            directory.mkdir(parents=True)
            item = {'name': name, 'version': '1.0.0', 'license': 'MIT'}
            (directory/'package.json').write_text(json.dumps(item))
            path = 'THIRD-PARTY-LICENSE' if name == 'rolldown' else 'formatstack.js'
            self.add_pin('npm', item, directory, path, text, False,
                         line_range=[1, 2] if name == 'stackback' else None)
            if name == 'rolldown':
                (directory/'LICENSE').write_bytes(b'Synthetic package MIT license\n')

    def add_cargo(self, name, version, license):
        directory = self.source/(name+'-'+version)
        directory.mkdir()
        manifest = directory/'Cargo.toml'
        manifest.write_text('[package]\nname = '+json.dumps(name)+'\nversion = '+json.dumps(version)+'\n')
        item = {'id': name+'@'+version, 'name': name, 'version': version,
                'license': license, 'license_file': None, 'manifest_path': str(manifest)}
        self.packages.append(item)
        return directory, item

    def add_pin(self, ecosystem, item, directory, path, data, package_text, line_range=None):
        (directory/path).write_bytes(data)
        manifest_name = 'Cargo.toml' if ecosystem == 'cargo' else 'package.json'
        output = data if line_range is None else b'// Synthetic copyright\n// Synthetic permission\n'
        pin = {'license': item['license'], 'manifestSha256': hashlib.sha256((directory/manifest_name).read_bytes()).hexdigest(),
               'sourcePath': path, 'sourceSha256': hashlib.sha256(data).hexdigest(),
               'noticeSha256': hashlib.sha256(output).hexdigest(), 'packageLicenseText': package_text,
               'sourceUrl': 'https://example.com/synthetic/'+path,
               'packageProvenance': {'testFixture': 'synthetic owned source'}}
        if line_range is not None:
            pin['lineRange'] = line_range
        self.pins.setdefault((ecosystem, item['name']), {})[item['version']] = pin
        self.items[(ecosystem, item['name'], item['version'])] = item
        self.locations[(ecosystem, item['name'], item['version'])] = directory

    def collect(self):
        self.run_number += 1
        out = self.root/('out-'+str(self.run_number))
        self.latest_out = out
        metadata = SimpleNamespace(stdout=json.dumps({'packages': self.packages}))
        with patch.object(notices, 'REVIEWED_SOURCE_NOTICES', self.pins, create=True), \
             patch.object(notices.subprocess, 'run', return_value=metadata), \
             patch.object(sys, 'argv', ['collect_notices.py', '--source', str(self.source), '--out', str(out)]), \
             contextlib.redirect_stdout(io.StringIO()):
            notices.main()
        result = json.loads((out/'inventory.json').read_text())
        return out, result

    def test_authors_raw_text_fills_only_the_two_known_package_gaps(self):
        out, result = self.collect()
        for version in ['5.3.0', '6.0.0']:
            row = next(r for r in result['packages'] if r['name'] == 'r-efi' and r['version'] == version)
            self.assertEqual(row['texts'], ['reviewed/AUTHORS.txt'])
            self.assertEqual((out/('cargo-r-efi-'+version)/row['texts'][0]).read_bytes(), b'Synthetic owned permission and copyright\n')
        self.assertEqual(result['status'], 'requires-human-review')
        self.assertEqual(len(result['packages']), 7)
        self.assertEqual(sum(not row['texts'] for row in result['packages']), 2)

    def test_additional_notices_do_not_cover_stackback_declared_mit(self):
        out, result = self.collect()
        for name, source, wanted in [
            ('rolldown', 'THIRD-PARTY-LICENSE', b'Synthetic additional third-party notice\n'),
            ('stackback', 'formatstack.js', b'// Synthetic copyright\n// Synthetic permission\n')]:
            row = next(r for r in result['packages'] if r['name'] == name)
            additions = row.get('additionalNotices', [])
            self.assertEqual(len(additions), 1)
            self.assertEqual(additions[0]['sourcePath'], source)
            self.assertEqual((out/('npm-'+name+'-1.0.0')/additions[0]['file']).read_bytes(), wanted)
            self.assertNotIn(b'MUST_NOT_SHIP', wanted)
            self.assertEqual(row['declaredLicense'], 'MIT')
        self.assertEqual(next(r for r in result['packages'] if r['name'] == 'stackback')['texts'], [])

    def test_each_changed_source_or_manifest_fails_instead_of_copying_unreviewed_bytes(self):
        for key, directory in self.locations.items():
            pin = self.pins[key[:2]][key[2]]
            for path in [directory/pin['sourcePath'], directory/('Cargo.toml' if key[0] == 'cargo' else 'package.json')]:
                original = path.read_bytes()
                path.write_bytes(original+b' ')
                try:
                    with self.subTest(package=key, path=path.name), self.assertRaises(ValueError):
                        self.collect()
                    self.assertFalse((self.latest_out/(key[0]+'-'+key[1]+'-'+key[2])/'reviewed').exists())
                finally:
                    path.write_bytes(original)

    def test_changed_known_package_version_or_license_fails_closed(self):
        for key, item in self.items.items():
            for field, value in [('version', '9.9.9'), ('license', 'UNREVIEWED')]:
                original = item[field]
                item[field] = value
                manifest = self.locations[key]/'package.json'
                if key[0] == 'npm':
                    manifest.write_text(json.dumps(item))
                try:
                    with self.subTest(package=key, field=field), self.assertRaises(ValueError):
                        self.collect()
                finally:
                    item[field] = original
                    if key[0] == 'npm':
                        manifest.write_text(json.dumps(item))

    def test_reviewed_source_symlink_is_rejected_even_for_identical_bytes(self):
        for key, directory in self.locations.items():
            pin = self.pins[key[:2]][key[2]]
            path = directory/pin['sourcePath']
            raw = path.read_bytes()
            target = self.root/'alias-target'
            target.write_bytes(raw)
            path.unlink()
            path.symlink_to(target)
            try:
                with self.subTest(package=key), self.assertRaises(ValueError):
                    self.collect()
            finally:
                path.unlink()
                path.write_bytes(raw)

    def test_path_escape_and_comment_range_changed_to_include_code_fail_closed(self):
        key = ('npm', 'stackback', '1.0.0')
        pin = self.pins[key[:2]][key[2]]
        for field, invalid in [('sourcePath', '../formatstack.js'), ('sourcePath', '/formatstack.js'),
                               ('lineRange', [0, 2]), ('lineRange', [1, 4]), ('lineRange', [2, 1])]:
            original = pin[field]
            pin[field] = invalid
            try:
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    self.collect()
            finally:
                pin[field] = original

    def test_unreviewed_missing_license_is_not_filled_from_an_ancestor_or_same_spdx(self):
        (self.source/'LICENSE').write_bytes(b'Synthetic parent MIT text\n')
        _, result = self.collect()
        row = next(r for r in result['packages'] if r['name'] == 'unreviewed-source')
        self.assertEqual(row['texts'], [])
        self.assertIsNone(row['declaredLicense'])


if __name__ == '__main__':
    unittest.main()
