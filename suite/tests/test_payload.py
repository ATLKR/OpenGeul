"""Synthetic Windows payloads exercise integrity and architecture admission."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from suite.payload import create_inventory, verify_payload
from suite import payload


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def pe(machine=0x8664, *, managed=False, flags=1, dll=False):
    """Small structurally valid PE; managed fixture contains a real CLR header."""
    data = bytearray(1024)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 128)
    data[128:132] = b'PE\0\0'
    size = 224 if machine == 0x14c else 240
    struct.pack_into('<HHIIIHH', data, 132, machine, 1, 0, 0, 0, size, 0x2002 if dll else 2)
    optional = 152
    struct.pack_into('<H', data, optional, 0x10b if machine == 0x14c else 0x20b)
    count_offset = 92 if machine == 0x14c else 108
    struct.pack_into('<I', data, optional + count_offset, 16)
    section = optional + size
    data[section:section+8] = b'.text\0\0\0'
    struct.pack_into('<IIII', data, section+8, 512, 0x1000, 512, 512)
    if managed:
        struct.pack_into('<II', data, optional+count_offset+4+14*8, 0x1010, 72)
        struct.pack_into('<IHHIII', data, 528, 72, 2, 5, 0x1090, 32, flags)
        data[656:660] = b'BSJB'
    return bytes(data)


class PayloadFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'payload'
        self.root.mkdir()
        self.product = {'schemaVersion': 1, 'productName': 'OpenGeul Office', 'version': '0.1.0'}
        self.provenance = {
            'schemaVersion': 1, 'productName': 'OpenGeul Office', 'version': '0.1.0',
            'architecture': 'x64', 'sourceCommit': 'a'*40,
            'runtime': {'sha256': 'b'*64, 'url': 'https://example.org/office.msi',
                        'sourceUrl': 'https://example.org/source.tar.xz', 'sourceSha256': '1'*64},
        }
        for name in ('OpenGeul.Office.exe', 'Office/program/soffice.exe',
                     'Office/program/soffice.bin', 'Office/program/python.exe', 'hostfxr.dll'):
            self.write(name, pe())
        self.write('OpenGeul.Office.dll', pe(0x14c, managed=True, dll=True))
        for name in ('worker/office_worker.py', 'worker/session.py', 'worker/native.py',
                     'worker/native_windows.py', 'worker/dispatch.py'):
            self.write(name, b'# worker source\n')
        for name in ('Notices/OpenGeul-Office-LICENSE.txt', 'Notices/LibreOffice-LICENSE.txt',
                     'Notices/CORRESPONDING_SOURCE.md', 'Office/LICENSE', 'Office/NOTICE'):
            self.write(name, b'Preserved license and corresponding-source information.\n')
        self.write('Office/program/bootstrap.ini', b'ProductKey=OpenGeul Office\n')
        self.branding = {
            'schemaVersion': 1, 'productName': 'OpenGeul Office',
            'manifestSha256': digest(canonical(self.product)), 'inputTreeSha256': 'c'*64,
            'source': {'buildId': 'd'*40, 'productKey': 'LibreOffice 26.8',
                       'sourceUrl': 'https://github.com/LibreOffice/core/tree/'+'d'*40},
            'modifiedFiles': {'program/bootstrap.ini': {
                'beforeSha256': 'e'*64, 'sha256': digest(self.read('Office/program/bootstrap.ini'))}},
            'preservedLegalFiles': {name: digest(self.read('Office/'+name)) for name in ('LICENSE', 'NOTICE')},
        }
        self.source_archive()
        self.save_metadata()

    def source_archive(self, *, commit=None, entries=None, lock_architecture=None, lock_name=None):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.comment = (commit or self.provenance['sourceCommit']).encode()
            architecture = self.provenance['architecture']
            lock = {'schemaVersion': 1, 'architecture': lock_architecture or architecture,
                    'version': self.provenance['version'],
                    'runtime': copy.deepcopy(self.provenance['runtime'])}
            if self.provenance.get('hwp'):
                lock['hwp'] = copy.deepcopy(self.provenance['hwp'])
            lock_name = lock_name or ('suite/config/runtime.arm64.lock.json' if architecture == 'arm64'
                                      else 'suite/config/runtime.lock.json')
            archive.writestr(lock_name, canonical(lock))
            for name, content in (entries or {'suite/worker/office_worker.py': b'# exact source\n'}).items():
                archive.writestr(name, content)
        self.write('Sources/OpenGeul-Office-source.zip', data.getvalue())

    def write(self, name, data):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, name):
        return (self.root/name).read_bytes()

    def write_json(self, name, value):
        self.write(name, json.dumps(value, ensure_ascii=False, indent=2).encode())

    def save_metadata(self):
        self.write_json('suite-product.json', self.product)
        self.write_json('runtime-branding.json', self.branding)
        self.write_json('Office/opengeul-branding.json', self.branding)
        self.provenance['sourceArchiveSha256'] = digest(self.read('Sources/OpenGeul-Office-source.zip'))
        self.provenance['brandingReceiptSha256'] = digest(self.read('runtime-branding.json'))
        self.write_json('suite-provenance.json', self.provenance)


class PayloadTests(PayloadFixture):
    def test_complete_inventory_covers_native_managed_worker_and_legal_files(self):
        receipt = create_inventory(self.root)
        self.assertEqual(set(receipt), {'schemaVersion', 'architecture', 'files'})
        self.assertEqual(receipt['schemaVersion'], 1)
        self.assertEqual(receipt['architecture'], 'x64')
        expected = {p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(set(receipt['files']), expected)
        for name, record in receipt['files'].items():
            self.assertEqual(record, {'size': len(self.read(name)), 'sha256': digest(self.read(name))})
        verify_payload(self.root, receipt)

    def test_x64_provenance_must_explicitly_name_its_matching_architecture(self):
        for architecture in ('arm64', 'x86', None):
            changed = copy.deepcopy(self.provenance)
            changed['architecture'] = architecture
            self.write_json('suite-provenance.json', changed)
            with self.subTest(architecture=architecture), self.assertRaisesRegex(ValueError, 'architecture'):
                create_inventory(self.root)
        changed = copy.deepcopy(self.provenance)
        del changed['architecture']
        self.write_json('suite-provenance.json', changed)
        with self.assertRaisesRegex(ValueError, 'architecture'):
            create_inventory(self.root)

    def test_inventory_deterministic_independent_of_creation_order(self):
        before = create_inventory(self.root)
        data = self.read('worker/session.py')
        (self.root/'worker/session.py').unlink()
        self.write('worker/session.py', data)
        self.assertEqual(create_inventory(self.root), before)

    def test_written_inventory_excludes_only_itself_and_is_verified(self):
        receipt = create_inventory(self.root)
        self.write_json('suite-inventory.json', receipt)
        self.assertEqual(create_inventory(self.root), receipt)
        verify_payload(self.root, receipt)
        changed = copy.deepcopy(receipt)
        changed['files']['worker/session.py']['sha256'] = 'f'*64
        self.write_json('suite-inventory.json', changed)
        with self.assertRaisesRegex(ValueError, 'inventory'):
            verify_payload(self.root, receipt)

    def test_modified_missing_and_extra_files_fail_against_receipt(self):
        receipt = create_inventory(self.root)
        path = self.root/'worker/session.py'
        original = path.read_bytes()
        path.write_bytes(b'# changed\n')
        with self.assertRaises(ValueError):
            verify_payload(self.root, receipt)
        path.unlink()
        with self.assertRaises(ValueError):
            verify_payload(self.root, receipt)
        path.write_bytes(original)
        self.write('Office/program/extra.dat', b'extra')
        with self.assertRaises(ValueError):
            verify_payload(self.root, receipt)

    def test_receipt_path_traversal_aliases_and_malformed_records_rejected(self):
        for name in ('../outside', '/absolute', 'C:/outside', r'Office\program\outside',
                     'Office/./outside', 'Office/../outside', 'Office//outside', 'Office/CON',
                     'Office/trailing.', 'Office/trailing ', 'Office/stream:extra'):
            receipt = create_inventory(self.root)
            receipt['files'][name] = {'size': 1, 'sha256': 'a'*64}
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_payload(self.root, receipt)

    def test_receipt_schema_and_architecture_cannot_be_reinterpreted(self):
        for change in ({'schemaVersion': True}, {'schemaVersion': 2}, {'architecture': 'arm64'},
                       {'files': []}, {'unknown': 'ignored'}):
            receipt = create_inventory(self.root)
            receipt.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_payload(self.root, receipt)
        for record in ({'size': True, 'sha256': 'a'*64}, {'size': -1, 'sha256': 'a'*64},
                       {'size': 1, 'sha256': 'bad'}, {'size': 1, 'sha256': 'a'*64, 'unreviewed': True}):
            receipt = create_inventory(self.root)
            receipt['files']['worker/session.py'] = record
            with self.subTest(record=record), self.assertRaises(ValueError):
                verify_payload(self.root, receipt)

    @unittest.skipIf(os.name == 'nt', 'Windows prevents creating these invalid/aliased fixture paths')
    def test_case_aliases_and_invalid_windows_names_in_actual_tree_rejected(self):
        for name in ('Office/LICENSE.', 'Office/CON.txt', 'Office/colon:stream', r'Office/back\slash'):
            self.write(name, b'unreviewed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                create_inventory(self.root)
            (self.root/name).unlink()
        self.write('Office/license', b'case alias')
        with self.assertRaisesRegex(ValueError, 'alias|collision'):
            create_inventory(self.root)

    @unittest.skipIf(os.name == 'nt', 'Windows prevents creating aliased fixture directories')
    def test_directory_case_aliases_rejected_even_when_file_names_differ(self):
        self.write('office/another.dat', b'aliased directory')
        with self.assertRaisesRegex(ValueError, 'alias|collision'):
            create_inventory(self.root)

    def test_symlink_file_directory_and_root_rejected(self):
        target = self.root/'Office/LICENSE'
        link = self.root/'Office/linked'
        link.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'link|reparse'):
            create_inventory(self.root)
        link.unlink()
        link.symlink_to(target.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'link|reparse'):
            create_inventory(self.root)
        link.unlink()
        alias = self.root.parent/'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'link|reparse'):
            create_inventory(alias)

    def test_required_editor_runtime_worker_legal_and_source_files_cannot_be_missing(self):
        names = ('OpenGeul.Office.exe', 'OpenGeul.Office.dll', 'suite-product.json', 'suite-provenance.json',
                 'runtime-branding.json', 'Office/program/soffice.exe', 'Office/program/soffice.bin',
                 'Office/program/python.exe', 'Office/opengeul-branding.json',
                 'worker/office_worker.py', 'worker/session.py', 'Notices/OpenGeul-Office-LICENSE.txt',
                 'Notices/LibreOffice-LICENSE.txt', 'Notices/CORRESPONDING_SOURCE.md',
                 'Sources/OpenGeul-Office-source.zip')
        for name in names:
            path = self.root/name
            original = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaises(ValueError):
                create_inventory(self.root)
            path.write_bytes(original)

    def test_every_worker_implementation_module_is_required(self):
        for name in ('worker/native.py', 'worker/native_windows.py', 'worker/dispatch.py'):
            path = self.root/name
            original = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Missing required'):
                create_inventory(self.root)
            path.write_bytes(original)

    def test_source_and_branding_provenance_hashes_bind_the_actual_packaged_bytes(self):
        for field in ('sourceArchiveSha256', 'brandingReceiptSha256'):
            for value in (None, 'bad-hash', 'f'*64):
                changed = copy.deepcopy(self.provenance)
                if value is None:
                    changed.pop(field)
                else:
                    changed[field] = value
                self.write_json('suite-provenance.json', changed)
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'provenance'):
                    create_inventory(self.root)

    def test_unexpected_top_level_files_and_worker_binaries_rejected(self):
        for name in ('unreviewed.txt', 'worker/download.exe', 'other/private.txt'):
            self.write(name, pe() if name.endswith('.exe') else b'extra')
            with self.subTest(name=name), self.assertRaises(ValueError):
                create_inventory(self.root)
            (self.root/name).unlink()
        (self.root/'other').rmdir()

    def test_all_native_code_must_be_x64_including_soffice_bin_and_python(self):
        for name in ('OpenGeul.Office.exe', 'Office/program/soffice.bin',
                     'Office/program/python.exe', 'hostfxr.dll', 'Office/program/disguised.dat'):
            existed = (self.root/name).exists()
            original = self.read(name) if existed else None
            for machine in (0xaa64, 0x14c):
                self.write(name, pe(machine))
                with self.subTest(name=name, machine=machine), self.assertRaisesRegex(ValueError, 'x64|architecture'):
                    create_inventory(self.root)
            if existed:
                self.write(name, original)
            else:
                (self.root/name).unlink()

    def test_managed_i386_dll_requires_valid_il_only_anycpu_metadata(self):
        path = 'OpenGeul.Office.dll'
        for data in (pe(0x14c, dll=True), pe(0x14c, managed=True, flags=0, dll=True),
                     pe(0x14c, managed=True, flags=3, dll=True),
                     pe(0x14c, managed=True, flags=17, dll=True),
                     pe(0xaa64, managed=True, dll=True)):
            self.write(path, data)
            with self.subTest(digest=digest(data)), self.assertRaises(ValueError):
                create_inventory(self.root)
        data = bytearray(pe(0x14c, managed=True, dll=True))
        data[656:660] = b'fake'
        self.write(path, data)
        with self.assertRaises(ValueError):
            create_inventory(self.root)

    def test_invalid_or_truncated_pe_never_passes_as_executable(self):
        for data in (b'not a binary', b'MZ', b'MZ'+b'\0'*62, pe()[:250]):
            self.write('Office/program/soffice.bin', data)
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                create_inventory(self.root)

    def test_branding_metadata_matches_manifest_modified_files_and_preserved_licenses(self):
        mutations = (
            lambda: self.product.update(version='9.9.9'),
            lambda: self.write('Office/program/bootstrap.ini', b'ProductKey=LibreOffice\n'),
            lambda: self.write('Office/LICENSE', b'rewritten legal notice'),
            lambda: self.branding.update(preservedLegalFiles={}),
            lambda: self.branding['modifiedFiles'].update({'../escape': {'beforeSha256': None, 'sha256': 'f'*64}}),
            lambda: self.branding.update(inputTreeSha256='missing'),
        )
        product, branding = copy.deepcopy(self.product), copy.deepcopy(self.branding)
        files = {name: self.read(name) for name in ('Office/program/bootstrap.ini', 'Office/LICENSE')}
        for mutation in mutations:
            mutation()
            self.save_metadata()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                create_inventory(self.root)
            self.product, self.branding = copy.deepcopy(product), copy.deepcopy(branding)
            for name, data in files.items():
                self.write(name, data)
            self.save_metadata()

    def test_different_root_and_runtime_branding_receipts_rejected(self):
        self.write_json('Office/opengeul-branding.json', {'schemaVersion': 1})
        with self.assertRaisesRegex(ValueError, 'branding'):
            create_inventory(self.root)

    def test_missing_invalid_source_commit_runtime_hash_url_and_version_rejected(self):
        invalid = (
            lambda value: value.pop('sourceCommit'),
            lambda value: value.update(sourceCommit='not-a-commit'),
            lambda value: value.update(version='latest'),
            lambda value: value['runtime'].update(sha256='not-a-hash'),
            lambda value: value['runtime'].update(sourceSha256='not-a-hash'),
            lambda value: value['runtime'].update(url='http://example.org/runtime.msi'),
            lambda value: value['runtime'].pop('sourceUrl'),
        )
        for mutate in invalid:
            changed = copy.deepcopy(self.provenance)
            mutate(changed)
            self.write_json('suite-provenance.json', changed)
            with self.subTest(provenance=changed), self.assertRaises(ValueError):
                create_inventory(self.root)

    def test_product_identity_and_version_match_provenance_even_with_updated_branding_hash(self):
        original = copy.deepcopy(self.product)
        for change in ({'schemaVersion': True}, {'productName': 'Other Suite'}, {'version': '9.9.9'}):
            self.product = {**original, **change}
            self.branding['manifestSha256'] = digest(canonical(self.product))
            self.save_metadata()
            with self.subTest(change=change), self.assertRaises(ValueError):
                create_inventory(self.root)

    def test_managed_x86_executable_cannot_replace_native_x64_apphost(self):
        self.write('OpenGeul.Office.exe', pe(0x14c, managed=True))
        with self.assertRaisesRegex(ValueError, 'x64|architecture'):
            create_inventory(self.root)

    def test_exact_pinned_companion_remains_completely_inventoried(self):
        name = 'Office/program/twain32shim.exe'
        data = pe(0x14c)
        self.write(name, data)
        with patch.dict(payload.COMPANION_PE_ADMISSIONS, {name: {
                'machine': 0x14c, 'sha256': digest(data), 'role': 'x86CompatibilityHelper'}}):
            receipt = create_inventory(self.root)
            self.assertEqual(receipt['files'][name], {'size': len(data), 'sha256': digest(data)})
            verify_payload(self.root, receipt)
            self.write(name, data+b'altered')
            with self.assertRaisesRegex(ValueError, 'companion'):
                create_inventory(self.root)

    def test_companion_path_and_expected_machine_cannot_be_substituted(self):
        name = 'Office/program/twain32shim.exe'
        data = pe(0xaa64)
        self.write(name, data)
        with patch.dict(payload.COMPANION_PE_ADMISSIONS, {name: {
                'machine': 0x14c, 'sha256': digest(data), 'role': 'x86CompatibilityHelper'}}):
            with self.assertRaisesRegex(ValueError, 'companion'):
                create_inventory(self.root)
        (self.root/name).unlink()
        self.write('Office/program/renamed-helper.exe', pe(0x14c))
        with self.assertRaisesRegex(ValueError, 'x64|architecture'):
            create_inventory(self.root)

    def test_official_companion_path_alone_does_not_allow_unreviewed_bytes(self):
        self.write('Office/program/twain32shim.exe', pe(0x14c))
        with self.assertRaises(ValueError):
            create_inventory(self.root)

    def test_pinned_publisher_policy_can_be_x86_required_without_weakening_anycpu_rule(self):
        name = 'Office/program/policy.1.0.cli_cppuhelper.dll'
        data = pe(0x14c, managed=True, flags=0xb, dll=True)
        self.write(name, data)
        with patch.dict(payload.COMPANION_PE_ADMISSIONS, {name: {
                'machine': 0x14c, 'sha256': digest(data), 'role': 'managedPublisherPolicy'}}):
            create_inventory(self.root)
        self.write('OpenGeul.Office.dll', data)
        (self.root/name).unlink()
        with self.assertRaises(ValueError):
            create_inventory(self.root)

    def test_pinned_arm64_launcher_template_is_a_named_hashed_asset_only(self):
        name = 'Office/program/python-core-3.13.15/lib/setuptools/cli-arm64.exe'
        data = pe(0xaa64)
        self.write(name, data)
        with patch.dict(payload.COMPANION_PE_ADMISSIONS, {name: {
                'machine': 0xaa64, 'sha256': digest(data), 'role': 'pythonLauncherTemplate'}}):
            create_inventory(self.root)
        (self.root/name).unlink()
        self.write('Office/program/python.exe', data)
        with self.assertRaises(ValueError):
            create_inventory(self.root)

    def test_source_archive_requires_safe_source_entries_and_matching_git_commit(self):
        for commit, entries in (
            ('f'*40, {'suite/worker/office_worker.py': b'source'}),
            ('a'*40, {'../escape.py': b'source'}),
            ('a'*40, {'README.txt': b'no suite sources'}),
            ('a'*40, {'suite/a.py': b'source', 'suite/A.py': b'alias'}),
        ):
            self.source_archive(commit=commit, entries=entries)
            self.save_metadata()
            with self.subTest(commit=commit, entries=entries), self.assertRaises(ValueError):
                create_inventory(self.root)
        self.write('Sources/OpenGeul-Office-source.zip', b'not a source archive')
        self.save_metadata()
        with self.assertRaises(ValueError):
            create_inventory(self.root)

    def test_source_archive_runtime_lock_binds_reported_input_and_source_hashes(self):
        for key, replacement in (('sha256', '2'*64), ('sourceSha256', '3'*64),
                                 ('url', 'https://example.org/another.msi'),
                                 ('sourceUrl', 'https://example.org/another-source.tar.xz')):
            changed = copy.deepcopy(self.provenance)
            changed['runtime'][key] = replacement
            self.write_json('suite-provenance.json', changed)
            with self.subTest(key=key), self.assertRaises(ValueError):
                create_inventory(self.root)

    def test_dotnet_publish_companions_and_package_readme_are_inventoried(self):
        for name in ('README.txt', 'OpenGeul.Office.dll.config', 'OpenGeul.Office.deps.json',
                     'OpenGeul.Office.runtimeconfig.json', 'OpenGeul.Office.xml'):
            self.write(name, b'published companion')
        receipt = create_inventory(self.root)
        self.assertIn('README.txt', receipt['files'])
        verify_payload(self.root, receipt)

    def test_dotnet_satellite_assemblies_are_allowed_in_culture_directories(self):
        for culture in ('de', 'ko', 'zh-Hans', 'pt-BR'):
            self.write(culture+'/System.Windows.Forms.resources.dll', pe(0x14c, managed=True, dll=True))
        receipt = create_inventory(self.root)
        self.assertIn('ko/System.Windows.Forms.resources.dll', receipt['files'])
        verify_payload(self.root, receipt)
        self.write('ko/other.txt', b'unreviewed content')
        with self.assertRaises(ValueError):
            create_inventory(self.root)

    def test_duplicate_json_keys_rejected(self):
        self.write('suite-provenance.json', b'{"schemaVersion":1,"schemaVersion":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate|duplicate'):
            create_inventory(self.root)

    def test_optional_hwp_requires_runtime_license_and_provenance(self):
        self.write('HWP/OpenGeul.exe', pe())
        with self.assertRaises(ValueError):
            create_inventory(self.root)
        self.write('HWP/Tools/rhwp.exe', pe())
        self.write('HWP/Notices/OpenGeul-LICENSE.txt', b'Original HWP license\n')
        self.provenance['hwp'] = {'sha256': 'f'*64, 'url': 'https://example.org/hwp.zip'}
        self.source_archive()
        self.save_metadata()
        verify_payload(self.root, create_inventory(self.root))


class Arm64PayloadTests(PayloadFixture):
    def setUp(self):
        super().setUp()
        self.provenance['architecture'] = 'arm64'
        for name in ('OpenGeul.Office.exe', 'Office/program/soffice.exe',
                     'Office/program/soffice.bin', 'Office/program/python.exe', 'hostfxr.dll'):
            self.write(name, pe(0xaa64))
        self.source_archive()
        self.save_metadata()

    def architecture_call(self, function, *args, architecture='arm64'):
        try:
            return function(*args, architecture=architecture)
        except TypeError as error:
            self.fail(f'Explicit Suite architecture contract is required: {error}')

    def inventory(self):
        return self.architecture_call(create_inventory, self.root)

    def test_arm64_inventory_and_receipt_verify_native_hosts_and_anycpu_dll(self):
        receipt = self.inventory()
        self.assertEqual(receipt['architecture'], 'arm64')
        self.assertEqual(receipt['files']['hostfxr.dll']['sha256'], digest(pe(0xaa64)))
        self.assertEqual(receipt['files']['OpenGeul.Office.dll']['sha256'],
                         digest(pe(0x14c, managed=True, dll=True)))
        self.write_json('suite-inventory.json', receipt)
        verify_payload(self.root, receipt)

    def test_pe_accepts_only_the_requested_native_machine(self):
        path = self.root/'hostfxr.dll'
        self.architecture_call(payload._pe, path)
        for machine in (0x8664, 0xa641, 0x14c, 0x1c4):
            self.write('hostfxr.dll', pe(machine, dll=True))
            with self.subTest(machine=machine), self.assertRaisesRegex(ValueError, 'arm64|architecture'):
                self.architecture_call(payload._pe, path)
        self.write('hostfxr.dll', pe(0xaa64))
        with self.assertRaisesRegex(ValueError, 'x64|architecture'):
            payload._pe(path)

    def test_wrong_architecture_hosts_dependencies_and_disguised_pe_are_rejected(self):
        for name in ('OpenGeul.Office.exe', 'Office/program/soffice.exe',
                     'Office/program/soffice.bin', 'Office/program/python.exe',
                     'hostfxr.dll', 'Office/program/extra.pyd', 'Office/program/disguised.dat'):
            existed = (self.root/name).exists()
            original = self.read(name) if existed else None
            for machine in (0x8664, 0xa641, 0x14c):
                self.write(name, pe(machine))
                with self.subTest(name=name, machine=machine), self.assertRaisesRegex(ValueError, 'arm64|architecture'):
                    self.inventory()
            if existed:
                self.write(name, original)
            else:
                (self.root/name).unlink()

    def test_arm64_anycpu_still_rejects_native_x86_and_architecture_required_clr(self):
        for data in (pe(0x14c, dll=True), pe(0x14c, managed=True, flags=0, dll=True),
                     pe(0x14c, managed=True, flags=3, dll=True),
                     pe(0x14c, managed=True, flags=17, dll=True),
                     pe(0x14c, managed=True, flags=0x20001, dll=True)):
            self.write('OpenGeul.Office.dll', data)
            with self.subTest(sha256=digest(data)), self.assertRaises(ValueError):
                self.inventory()

    def test_unknown_architecture_is_rejected_before_scanning_or_parsing(self):
        for architecture in ('x86', 'ARM64', '', None, False, 64, [], {}):
            with self.subTest(architecture=architecture):
                with self.assertRaisesRegex(ValueError, 'architecture'):
                    self.architecture_call(create_inventory, self.root/'missing', architecture=architecture)
                with self.assertRaisesRegex(ValueError, 'architecture'):
                    self.architecture_call(payload._pe, self.root/'missing.exe', architecture=architecture)

    def test_provenance_architecture_must_match_requested_payload_and_receipt(self):
        for architecture in ('x64', 'x86', 'ARM64', None, [], {}):
            changed = copy.deepcopy(self.provenance)
            changed['architecture'] = architecture
            self.write_json('suite-provenance.json', changed)
            with self.subTest(architecture=architecture), self.assertRaisesRegex(ValueError, 'provenance.*architecture|architecture.*provenance'):
                self.inventory()

    def test_missing_provenance_architecture_fails_closed(self):
        changed = copy.deepcopy(self.provenance)
        del changed['architecture']
        self.write_json('suite-provenance.json', changed)
        with self.assertRaisesRegex(ValueError, 'provenance.*architecture|architecture.*provenance'):
            self.inventory()

    def test_receipt_architecture_cannot_transpose_payload_provenance(self):
        receipt = self.inventory()
        for architecture in ('x64', 'x86', None, [], {}):
            changed = copy.deepcopy(receipt)
            changed['architecture'] = architecture
            with self.subTest(architecture=architecture), self.assertRaises(ValueError):
                verify_payload(self.root, changed)

    def test_arm64_source_archive_requires_its_named_architecture_lock(self):
        for lock_architecture, lock_name in (
                ('arm64', 'suite/config/runtime.lock.json'),
                ('x64', 'suite/config/runtime.arm64.lock.json'),
                ('x86', 'suite/config/runtime.arm64.lock.json')):
            self.source_archive(lock_architecture=lock_architecture, lock_name=lock_name)
            self.save_metadata()
            with self.subTest(lock_architecture=lock_architecture, lock_name=lock_name), self.assertRaisesRegex(ValueError, 'source|lock'):
                self.inventory()

    def test_arm64_source_lock_binds_input_and_corresponding_source(self):
        for key, value in (('sha256', '2'*64), ('sourceSha256', '3'*64),
                           ('url', 'https://example.org/another.msi'),
                           ('sourceUrl', 'https://example.org/another.tar.xz')):
            changed = copy.deepcopy(self.provenance)
            changed['runtime'][key] = value
            self.write_json('suite-provenance.json', changed)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'source lock'):
                self.inventory()

    def source_engine(self):
        from suite.tests.test_prepare import source_build_fixture
        _, runtime, receipt_path, receipt = source_build_fixture(Path(self.temp.name))
        self.provenance['runtime'] = runtime
        self.write('Office/opengeul-source-build.json', receipt_path.read_bytes())
        for name in ('concrt140.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
                     'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll',
                     'vcruntime140_1.dll', 'vcruntime140_threads.dll'):
            self.write('Office/program/'+name, pe(0xaa64, dll=True))
        self.write('Office/share/readme/Microsoft-VC145-redistribution.html', b'Official VS2026 redistribution terms')
        self.source_archive(); self.save_metadata()
        return receipt

    def test_source_engine_crt_and_terms_must_match_exact_receipted_bytes_after_inventory_rebuild(self):
        for name in ('Office/program/vcruntime140.dll',
                     'Office/share/readme/Microsoft-VC145-redistribution.html'):
            with self.subTest(name=name):
                self.source_engine()
                self.write(name, self.read(name)+b'changed')
                with self.assertRaisesRegex(ValueError, 'CRT|redistribution'):
                    self.inventory()

    def test_source_engine_payload_keeps_exact_authenticated_receipt_and_immutable_lock(self):
        self.source_engine()
        receipt = self.inventory()
        self.assertIn('Office/opengeul-source-build.json', receipt['files'])
        verify_payload(self.root, receipt)

    def test_source_engine_payload_requires_the_locked_receipt_even_if_inventory_is_rebuilt(self):
        self.source_engine()
        (self.root/'Office/opengeul-source-build.json').unlink()
        with self.assertRaisesRegex(ValueError, 'receipt|source.build'):
            self.inventory()
        self.write('Office/opengeul-source-build.json', b'{"passed":true}')
        with self.assertRaisesRegex(ValueError, 'receipt|source.build'):
            self.inventory()

    def test_source_engine_packaged_lock_binds_all_runtime_source_build_and_format_fields(self):
        self.source_engine()
        original = copy.deepcopy(self.provenance)
        for key, value in (('format', 'msi'), ('size', 123),
                           ('sourceBuild', dict(original['runtime']['sourceBuild'], artifactId=999)),
                           ('sourceBuild', dict(original['runtime']['sourceBuild'], artifactSha256='f'*64)),
                           ('sourceBuild', dict(original['runtime']['sourceBuild'], receiptSha256='f'*64))):
            changed = copy.deepcopy(original); changed['runtime'][key] = value
            self.write_json('suite-provenance.json', changed)
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'source lock'):
                self.inventory()

    def test_source_engine_pinned_receipt_cannot_replace_native_base_qualification(self):
        from suite.tests.test_prepare import pin_source_receipt
        receipt = self.source_engine(); receipt['baseProof']['independentReopenVerified'] = False
        pin_source_receipt(self.provenance['runtime'], self.root/'Office/opengeul-source-build.json', receipt)
        self.source_archive(); self.save_metadata()
        with self.assertRaisesRegex(ValueError, 'Base|source.build'):
            self.inventory()

    def test_x64_companion_admission_does_not_grant_arm64_an_exception(self):
        name = 'Office/program/twain32shim.exe'
        data = pe(0x14c)
        self.write(name, data)
        with patch.dict(payload.COMPANION_PE_ADMISSIONS, {name: {
                'machine': 0x14c, 'sha256': digest(data), 'role': 'x86CompatibilityHelper'}}):
            with self.assertRaisesRegex(ValueError, 'arm64|architecture'):
                self.inventory()

    def test_unknown_arm64_compatibility_bytes_remain_rejected_at_known_path(self):
        self.write('Office/program/python-core-3.13.15/lib/setuptools/gui-32.exe', pe(0x14c))
        with self.assertRaises(ValueError):
            self.inventory()


if __name__ == '__main__':
    unittest.main()
