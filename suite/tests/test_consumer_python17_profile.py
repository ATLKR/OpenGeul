"""Source-only Python template selection; no qualified 9dea runtime is made."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from suite import payload
from suite.tests.test_payload import PayloadFixture, pe


CORE = '9dea406ab7695df6325b11b0e19fdca8db4b7276'
OLD_CORE = 'bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1'
URL = 'https://download.documentfoundation.org/libreoffice/src/26.8.2/libreoffice-26.8.2.2.tar.xz'
SHA = 'f0012302d9cc70955bd55890d3aaccf6c55677c4a6a46e1003f996b1b0dae8e7'
PREFIX = 'Office/program/python-core-3.13.17/lib/'


def source_profile():
    # Deliberately lacks artifact URL/hash, qualified receipt and sourceBuild.
    return dict(format='source-built-zip', version='26.8.2.2', sourceCoreCommit=CORE,
                sourceUrl=URL, sourceSha256=SHA)


class Python17ProfileTests(unittest.TestCase):
    def admissions(self, runtime, architecture):
        function = getattr(payload, '_source_python_template_admissions', None)
        self.assertTrue(callable(function), 'Consumer lacks exact source template selection')
        return function(runtime, architecture)

    def test_each_architecture_gets_exactly_its_ten_foreign_named_templates(self):
        common = {'setuptools/cli-32.exe', 'setuptools/cli.exe', 'setuptools/gui-32.exe',
                  'setuptools/gui.exe', 'pip/_vendor/distlib/t32.exe', 'pip/_vendor/distlib/w32.exe'}
        extra = {'x64': {'setuptools/cli-arm64.exe', 'setuptools/gui-arm64.exe',
                         'pip/_vendor/distlib/t64-arm.exe', 'pip/_vendor/distlib/w64-arm.exe'},
                 'arm64': {'setuptools/cli-64.exe', 'setuptools/gui-64.exe',
                           'pip/_vendor/distlib/t64.exe', 'pip/_vendor/distlib/w64.exe'}}
        for architecture, additions in extra.items():
            selected = self.admissions(source_profile(), architecture)
            self.assertEqual(set(selected), {PREFIX+name for name in common|additions})
            self.assertEqual(len(selected), 10)
            self.assertTrue(all(pin['machine'] != payload.NATIVE_MACHINES[architecture]
                                and pin['role'] == 'pythonLauncherTemplate' for pin in selected.values()))
            self.assertEqual(selected[PREFIX+'setuptools/cli.exe']['sha256'],
                             '32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb')

    def test_crosspaired_core_version_archive_format_and_hash_fail_closed(self):
        for field, wrong in [('sourceCoreCommit', OLD_CORE), ('sourceCoreCommit', 'f'*40),
                             ('version', '26.8.1.1'), ('sourceUrl', URL+'?changed=1'),
                             ('sourceSha256', '0'*64), ('format', 'msi')]:
            for architecture in ['x64', 'arm64']:
                runtime = source_profile();runtime[field] = wrong
                with self.subTest(field=field, architecture=architecture), self.assertRaises(ValueError):
                    self.admissions(runtime, architecture)
        for runtime in [None, [], {}]:
            with self.subTest(kind=type(runtime).__name__), self.assertRaises(ValueError):
                self.admissions(runtime, 'x64')

    def test_selection_returns_copies_and_unknown_architectures_are_rejected(self):
        selected = self.admissions(source_profile(), 'x64')
        selected[PREFIX+'setuptools/cli.exe']['sha256'] = '0'*64
        selected.clear()
        fresh = self.admissions(source_profile(), 'x64')
        self.assertEqual(len(fresh), 10)
        self.assertEqual(fresh[PREFIX+'setuptools/cli.exe']['sha256'],
                         '32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb')
        for architecture in ['x86', 'ARM64', '', None, []]:
            with self.subTest(architecture=architecture), self.assertRaises(ValueError):
                self.admissions(source_profile(), architecture)

    def test_legacy_source_profiles_keep_ten_python15_templates_without_msi_helpers(self):
        runtime = dict(format='source-built-zip', version='26.8.1.1', sourceCoreCommit=OLD_CORE,
            sourceUrl='https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz',
            sourceSha256='296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785')
        for architecture in ['x64', 'arm64']:
            selected = self.admissions(runtime, architecture)
            self.assertEqual(len(selected), 10)
            self.assertTrue(all('/python-core-3.13.15/' in name for name in selected))
            self.assertNotIn('Office/program/twain32shim.exe', selected)
            self.assertNotIn('Office/program/policy.1.0.cli_cppuhelper.dll', selected)

    def test_reviewed_path_does_not_allow_unknown_bytes_or_similar_prefix(self):
        selected = self.admissions(source_profile(), 'x64')
        name = PREFIX+'setuptools/cli.exe'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cli.exe';path.write_bytes(pe(0x14c))
            with self.assertRaises(ValueError):
                payload._pe(path, architecture='x64', companion=selected[name])
            self.assertNotIn(PREFIX+'setuptools/unknown.exe', selected)
            self.assertNotIn(name.replace('3.13.17', '3.13.170'), selected)
            self.assertNotIn(name.replace('setuptools', 'Setuptools'), selected)

    def test_validate_routes_only_the_validated_source_profile_on_both_architectures(self):
        from suite import prepare
        self.admissions(source_profile(), 'x64')
        name = PREFIX+'setuptools/cli.exe';raw = pe(0x14c)
        synthetic_pin = dict(machine=0x14c, role='pythonLauncherTemplate', sha256=hashlib.sha256(raw).hexdigest())
        # Replace both upstream authentication boundaries for this routing unit.
        # This opaque value is not a receipt and is never serialized or qualified.
        runtime = source_profile();authenticated_context = object()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);path=root/name;path.parent.mkdir(parents=True);path.write_bytes(raw)
            with patch.object(payload, 'PYTHON17_PE_TEMPLATES', {name: synthetic_pin}), \
                 patch.object(payload, '_metadata', return_value=runtime), \
                 patch.object(prepare, 'validate_source_build_receipt', return_value=authenticated_context) as full, \
                 patch.object(payload, '_source_companion_admissions', return_value={}) as companion:
                for architecture in ['x64', 'arm64']:
                    payload._validate(root, {name: {}}, architecture=architecture)
                self.assertEqual(full.call_count, 1)
                self.assertIs(full.call_args.args[0], runtime)
                self.assertEqual(full.call_args.args[1], root/'Office/opengeul-source-build.json')
                self.assertEqual(full.call_args.kwargs, {'architecture': 'x64'})
                self.assertEqual(companion.call_count, 1)
                self.assertIs(companion.call_args.args[0], runtime)
                self.assertIs(companion.call_args.args[1], authenticated_context)
                self.assertEqual(companion.call_args.kwargs, {'architecture': 'x64'})
            # Keep the byte-rejection check beyond the same authentication seam.
            with patch.object(payload, '_metadata', return_value=runtime), \
                 patch.object(prepare, 'validate_source_build_receipt', return_value=authenticated_context), \
                 patch.object(payload, '_source_companion_admissions', return_value={}):
                for architecture in ['x64', 'arm64']:
                    with self.assertRaises(ValueError):payload._validate(root, {name: {}}, architecture=architecture)
            with patch.object(payload, '_metadata', return_value={'format':'msi'}):
                with self.assertRaises(ValueError):payload._validate(root, {name: {}}, architecture='x64')

    def test_routing_metadata_stub_cannot_replace_the_required_real_x64_full_receipt(self):
        name = PREFIX+'setuptools/cli.exe';raw = pe(0x14c)
        pin = dict(machine=0x14c, role='pythonLauncherTemplate', sha256=hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);path=root/name;path.parent.mkdir(parents=True);path.write_bytes(raw)
            with patch.object(payload, 'PYTHON17_PE_TEMPLATES', {name: pin}), \
                 patch.object(payload, '_metadata', return_value=source_profile()), \
                 patch.object(payload, '_source_companion_admissions') as companion:
                with self.assertRaises(ValueError):payload._validate(root, {name: {}}, architecture='x64')
                self.assertEqual(companion.call_count, 0)

    def test_companion_rejection_cannot_fall_through_to_python_template_acceptance(self):
        from suite import prepare
        name = PREFIX+'setuptools/cli.exe'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);path=root/name;path.parent.mkdir(parents=True);path.write_bytes(pe(0x14c))
            with patch.object(payload, '_metadata', return_value=source_profile()), \
                 patch.object(prepare, 'validate_source_build_receipt', return_value=object()), \
                 patch.object(payload, '_source_companion_admissions', side_effect=ValueError('synthetic companion rejection')) as companion, \
                 patch.object(payload, '_pe') as binary:
                with self.assertRaises(ValueError):payload._validate(root, {name: {}}, architecture='x64')
                self.assertEqual(companion.call_count, 1)
                self.assertEqual(binary.call_count, 0)

    def test_source_profile_does_not_bypass_missing_package_metadata(self):
        self.admissions(source_profile(), 'x64')
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(payload, '_source_python_template_admissions', side_effect=AssertionError('Profile must follow metadata validation')):
            with self.assertRaises((FileNotFoundError, ValueError)):
                payload._validate(Path(directory), {}, architecture='x64')


class ValidatedRuntimeReturnTests(PayloadFixture):
    def test_metadata_returns_only_its_fully_validated_existing_msi_runtime(self):
        files = payload._scan(self.root)
        self.assertEqual(payload._metadata(self.root, files, architecture='x64'), self.provenance['runtime'])
        self.provenance['runtime']['sha256'] = 'not-a-hash';self.save_metadata()
        with self.assertRaises(ValueError):payload._metadata(self.root, payload._scan(self.root), architecture='x64')


if __name__ == '__main__':unittest.main()
