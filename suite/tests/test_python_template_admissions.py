"""Exact source-bound launcher admissions; authenticated bytes never execute."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

from suite import payload


OLD_CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
NEW_CORE = '9dea406ab7695df6325b11b0e19fdca8db4b7276'
SOURCE_PINS = {
    OLD_CORE: ('26.8.1.1', 'https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz',
               '296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785'),
    NEW_CORE: ('26.8.2.2', 'https://download.documentfoundation.org/libreoffice/src/26.8.2/libreoffice-26.8.2.2.tar.xz',
               'f0012302d9cc70955bd55890d3aaccf6c55677c4a6a46e1003f996b1b0dae8e7'),
}


def runtime(core=NEW_CORE):
    version, url, digest = SOURCE_PINS[core]
    return dict(format='source-built-zip', sourceCoreCommit=core, version=version,
                sourceUrl=url, sourceSha256=digest)


class PythonTemplateAdmissionTests(unittest.TestCase):
    def selector(self, value, architecture='x64'):
        self.assertTrue(callable(getattr(payload, '_source_python_template_admissions', None)),
                        'Missing exact authenticated Python source selector')
        return payload._source_python_template_admissions(value, architecture)

    def test_exact_source_pairs_select_only_ten_foreign_templates_per_architecture(self):
        for core, version in ((OLD_CORE, '3.13.15'), (NEW_CORE, '3.13.17')):
            for architecture, machine in (('x64', 0x8664), ('arm64', 0xaa64)):
                with self.subTest(core=core, architecture=architecture):
                    pins = self.selector(runtime(core), architecture)
                    self.assertEqual(len(pins), 10)
                    for name, pin in pins.items():
                        self.assertTrue(name.startswith('Office/program/python-core-'+version+'/lib/'))
                        self.assertEqual(set(pin), {'machine', 'role', 'sha256'})
                        self.assertNotEqual(pin['machine'], machine)
                        self.assertEqual(pin['role'], 'pythonLauncherTemplate')
                        self.assertRegex(pin['sha256'], r'^[0-9a-f]{64}$')

    def test_unknown_cross_paired_or_incomplete_source_identity_cannot_select_templates(self):
        for core in (OLD_CORE, NEW_CORE):
            good = runtime(core)
            changes = [('sourceCoreCommit', 'f'*40), ('sourceCoreCommit', []),
                       ('version', SOURCE_PINS[NEW_CORE if core == OLD_CORE else OLD_CORE][0]),
                       ('version', '26.8.2.3'), ('sourceUrl', 'https://example.org/source.tar.xz'),
                       ('sourceSha256', '0'*64), ('format', 'msi'), ('format', None)]
            for key, value in changes:
                changed = copy.deepcopy(good); changed[key] = value
                with self.subTest(core=core, key=key, value=value):
                    with self.assertRaisesRegex(ValueError, 'source|core|Python'):
                        self.selector(changed)
            for key in good:
                changed = copy.deepcopy(good); del changed[key]
                with self.subTest(core=core, missing=key), self.assertRaises(ValueError):
                    self.selector(changed)
        for value in (None, [], True, '9dea'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.selector(value)

    def test_selector_rejects_unknown_architecture_and_cross_version_paths(self):
        for architecture in ('x86', 'ARM64', None, []):
            with self.subTest(architecture=architecture), self.assertRaises(ValueError):
                self.selector(runtime(), architecture)
        old = self.selector(runtime(OLD_CORE)); new = self.selector(runtime())
        for name in new:
            self.assertNotIn(name, old)
            self.assertNotIn(name.replace('3.13.17', '3.13.16'), new)
            self.assertNotIn(name.upper(), new)
            self.assertNotIn(name.replace('/lib/', '/other/'), new)

    def test_historical_msi_maps_are_retained_without_new_source_paths(self):
        for architecture, historical in (('x64', payload.COMPANION_PE_ADMISSIONS),
                                         ('arm64', payload.ARM64_COMPANION_PE_ADMISSIONS)):
            before = copy.deepcopy(historical)
            self.selector(runtime(), architecture)
            self.assertEqual(historical, before)
            self.assertFalse(any('3.13.17' in name for name in historical))

    def test_validate_uses_the_validated_runtime_returned_by_metadata(self):
        # Only the upstream authentication boundary is replaced here. Real PE
        # bytes and exact hash checks are exercised by the authenticated class.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(payload, '_metadata', return_value=runtime()):
                with patch.object(payload, '_python_template_admissions', wraps=self.selector_impl()) as select:
                    payload._validate(root, {}, architecture='x64')
                    select.assert_called_once_with(NEW_CORE, 'x64', '26.8.2.2')
            for historical in ({}, dict(format='msi')):
                with patch.object(payload, '_metadata', return_value=historical):
                    with patch.object(payload, '_python_template_admissions', side_effect=AssertionError('MSI must retain its historical map')):
                        payload._validate(root, {}, architecture='x64')

    def selector_impl(self):
        self.assertTrue(callable(getattr(payload, '_python_template_admissions', None)),
                        'Missing exact authenticated Python source selector')
        return payload._python_template_admissions


class AuthenticatedPythonTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value = os.environ.get('OPENGEUL_PYTHON17_AUDIT')
        if not value:
            raise unittest.SkipTest('Authenticated Python 3.13.17 audit inputs are required')
        cls.audit = Path(value)
        cls.evidence = json.loads((cls.audit/'authenticated-python17-templates.json').read_text())
        raw = (cls.audit/'Python-3.13.17.tar.xz').read_bytes()
        if (len(raw) != 23233336 or hashlib.sha256(raw).hexdigest() !=
                '6020bd10aff3bf4821be16f088ebb1591beb7b811dcd8fab1da8f7c22a7b27e7'):
            raise AssertionError('Python archive differs from authenticated size/SHA256')
        if len(cls.evidence['templates']) != 14:
            raise AssertionError('Authenticated packaging recipe must select fourteen PE templates')

    def test_all_fourteen_actual_templates_match_exact_machine_hash_and_role(self):
        self.assertTrue(hasattr(payload, 'PYTHON17_PE_TEMPLATES'), 'Missing authenticated template pins')
        self.assertEqual(set(payload.PYTHON17_PE_TEMPLATES), {v['path'] for v in self.evidence['templates']})
        for row in self.evidence['templates']:
            with self.subTest(path=row['path']):
                path = self.audit/'templates'/row['path']; raw = path.read_bytes()
                pin = payload.PYTHON17_PE_TEMPLATES[row['path']]
                self.assertEqual(pin, {key: row[key] for key in ('machine', 'sha256', 'role')})
                self.assertEqual(hashlib.sha256(raw).hexdigest(), pin['sha256'])
                self.assertEqual(len(raw), row['sizeBytes'])
                offset = struct.unpack_from('<I', raw, 60)[0]
                self.assertEqual(struct.unpack_from('<H', raw, offset+4)[0], pin['machine'])
                self.assertEqual(pin['role'], 'pythonLauncherTemplate')
                for architecture in ('x64', 'arm64'):
                    payload._pe(path, companion=pin, architecture=architecture)

    def test_actual_foreign_templates_reject_changed_bytes_machine_and_path_bypasses(self):
        self.assertTrue(callable(getattr(payload, '_python_template_admissions', None)), 'Missing selector')
        for architecture in ('x64', 'arm64'):
            pins = payload._python_template_admissions(NEW_CORE, architecture, '26.8.2.2')
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                for name, pin in pins.items():
                    source = self.audit/'templates'/name; raw = source.read_bytes()
                    path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
                    with self.subTest(architecture=architecture, path=name):
                        with patch.object(payload, '_metadata', return_value=runtime()):
                            payload._validate(root, {name: {}}, architecture=architecture)
                        changed = bytearray(raw); changed[-1] ^= 1; path.write_bytes(changed)
                        with self.assertRaises(ValueError):
                            payload._pe(path, companion=pin, architecture=architecture)
                        # A known foreign path cannot skip its exact pin by
                        # changing the PE header to the product's native machine.
                        changed = bytearray(raw); offset = struct.unpack_from('<I', changed, 60)[0]
                        struct.pack_into('<H', changed, offset+4, payload.NATIVE_MACHINES[architecture])
                        struct.pack_into('<H', changed, offset+24, 0x20b)
                        path.write_bytes(changed)
                        with patch.object(payload, '_metadata', return_value=runtime()):
                            with self.assertRaises(ValueError):
                                payload._validate(root, {name: {}}, architecture=architecture)
                        path.write_bytes(raw)
                        for wrong in (dict(pin, machine=0x8664 if pin['machine'] != 0x8664 else 0xaa64),
                                      dict(pin, role='unreviewedRuntime'), dict(pin, sha256='0'*64)):
                            with self.assertRaises(ValueError):
                                payload._pe(path, companion=wrong, architecture=architecture)
                        # Retaining actual bytes under unknown/cross-version names
                        # must not borrow the authentic file's admission.
                        for renamed in (name.replace('3.13.17', '3.13.15'),
                                        name.replace('3.13.17', '3.13.16'), name+'.dat'):
                            destination = root/renamed; destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, destination)
                            with patch.object(payload, '_metadata', return_value=runtime()):
                                with self.assertRaises(ValueError):
                                    payload._validate(root, {renamed: {}}, architecture=architecture)
                        with patch.object(payload, '_metadata', return_value=runtime(OLD_CORE)):
                            with self.assertRaises(ValueError):
                                payload._validate(root, {name: {}}, architecture=architecture)


if __name__ == '__main__':
    unittest.main()
