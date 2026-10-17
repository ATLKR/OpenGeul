"""Reject no-op style shortcuts and mismatched saved/reopened Writer evidence."""
import copy
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'writer_style_smoke.py'
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location('suite_writer_style_smoke', SOURCE)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
else:
    smoke = None

# Actual run38951093947/source98f metadata, retained without inventing OS-image evidence.
ACTUAL_98_SUITE_ROOT = 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64'
ACTUAL_98_PYTHON_OBSERVATION = {'implementation': 'cpython',
 'version': [3, 13, 15],
 'executable': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\python-core-3.13.15',
 'prefix': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\\\python-core-3.13.15',
 'basePrefix': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\\\python-core-3.13.15',
 'pythonDll': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\python313.dll',
 'moduleFiles': {'uno': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\uno.py',
                 'pyuno': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\pyuno.pyd',
                 'encodings': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\python-core-3.13.15\\lib\\encodings\\__init__.py',
                 'os': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\python-core-3.13.15\\Lib\\os.py'},
 'moduleOrigins': {'uno': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\uno.py',
                   'pyuno': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\pyuno.pyd',
                   'encodings': 'D:\\a\\OpenGeul\\OpenGeul\\dist\\OpenGeul-Office-0.1.1-dev-windows-x64\\Office\\program\\python-core-3.13.15\\lib\\encodings\\__init__.py'}}


class WriterStyleEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke, 'Focused Writer style proof implementation is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def docx(self, name, paragraphs):
        path = self.folder / name
        body = ''.join('<w:p>' + ('<w:pPr><w:pStyle w:val="' + style + '"/></w:pPr>' if style else '')
                       + '<w:r><w:t>' + text + '</w:t></w:r></w:p>' for style, text in paragraphs)
        with zipfile.ZipFile(path, 'w') as package:
            package.writestr('word/document.xml', '<w:document xmlns:w="' + smoke.WORD_NS + '"><w:body>' + body + '</w:body></w:document>')
        return smoke.docx_style_evidence(path)

    def pair(self):
        before = self.docx('before.docx', [(None, 'Engine-OpenGeul-writer 한글')])
        after = self.docx('after.docx', [('Heading1', 'Engine-OpenGeul-writer 한글')])
        return before, after

    def test_actual_first_paragraph_style_and_exact_body_are_recorded(self):
        before, after = self.pair()
        evidence = smoke.require_saved_style(before, after)
        self.assertEqual(evidence['firstParagraphStyleId'], 'Heading1')
        self.assertEqual(evidence['bodyText'], before['bodyText'])

    def test_heading_in_second_paragraph_cannot_satisfy_first_paragraph(self):
        before = self.docx('before.docx', [(None, 'first'), (None, 'second')])
        after = self.docx('after.docx', [(None, 'first'), ('Heading1', 'second')])
        with self.assertRaisesRegex(AssertionError, 'first paragraph'):
            smoke.require_saved_style(before, after)

    def test_changed_text_is_not_a_successful_style_only_edit(self):
        before, _ = self.pair()
        after = self.docx('after.docx', [('Heading1', 'lost text')])
        with self.assertRaisesRegex(AssertionError, 'text'):
            smoke.require_saved_style(before, after)

    def test_save_poll_waits_for_known_baseline_bytes_before_asserting_style(self):
        before, after = self.pair()
        self.assertTrue(callable(getattr(smoke, 'saved_style_ready', None)), 'Asynchronous Save completion predicate is missing')
        self.assertIsNone(smoke.saved_style_ready(before, before))
        self.assertEqual(smoke.saved_style_ready(before, after), after)

    def test_save_poll_rejects_changed_file_with_wrong_style(self):
        before, _ = self.pair()
        changed = self.docx('wrong-style.docx', [('Heading2', before['bodyText'])])
        self.assertTrue(callable(getattr(smoke, 'saved_style_ready', None)), 'Asynchronous Save completion predicate is missing')
        with self.assertRaisesRegex(AssertionError, 'first paragraph'):
            smoke.saved_style_ready(before, changed)

    def test_shortcut_noop_with_unchanged_bytes_is_rejected(self):
        before, _ = self.pair()
        with self.assertRaisesRegex(AssertionError, 'bytes|first paragraph'):
            smoke.require_saved_style(before, dict(before))

    def test_already_heading1_baseline_cannot_prove_shortcut_worked(self):
        _, after = self.pair()
        changed = dict(after, sha256='a' * 64)
        with self.assertRaisesRegex(AssertionError, 'baseline'):
            smoke.require_saved_style(after, changed)

    def test_independent_uno_requires_exact_style_text_and_stable_saved_bytes(self):
        _, expected = self.pair()
        observed = {'bodyText': expected['bodyText'], 'firstParagraphParaStyleName': 'Heading 1'}
        result = smoke.require_uno_style(expected, observed, expected['sha256'], expected['sha256'])
        self.assertEqual(result['firstParagraphParaStyleName'], 'Heading 1')

    def test_independent_uno_rejects_wrong_style(self):
        _, expected = self.pair()
        for style in ('Standard', 'Heading 10', 'Heading1'):
            with self.subTest(style=style), self.assertRaisesRegex(AssertionError, 'Heading 1'):
                smoke.require_uno_style(expected, {'bodyText': expected['bodyText'], 'firstParagraphParaStyleName': style}, expected['sha256'], expected['sha256'])

    def test_independent_uno_rejects_changed_text(self):
        _, expected = self.pair()
        with self.assertRaisesRegex(AssertionError, 'body'):
            smoke.require_uno_style(expected, {'bodyText': 'changed', 'firstParagraphParaStyleName': 'Heading 1'}, expected['sha256'], expected['sha256'])

    def test_independent_uno_rejects_changes_before_or_during_reopen(self):
        _, expected = self.pair()
        observed = {'bodyText': expected['bodyText'], 'firstParagraphParaStyleName': 'Heading 1'}
        for before, after in [('a' * 64, 'a' * 64), (expected['sha256'], 'a' * 64)]:
            with self.subTest(before=before, after=after), self.assertRaisesRegex(AssertionError, 'bytes'):
                smoke.require_uno_style(expected, observed, before, after)

    def test_native_crash_status_cannot_satisfy_clean_office_exit(self):
        self.assertTrue(callable(getattr(smoke, 'require_office_exit', None)), 'Native crash exit-code validation is missing')
        for code in (0, 1):
            self.assertEqual(smoke.require_office_exit(code), code)
        for code in (0xC0000005, 0xC0000409, -1073741819, 259):
            with self.subTest(code=code), self.assertRaisesRegex(AssertionError, 'exit'):
                smoke.require_office_exit(code)

    def test_witness_query_failure_keeps_original_error_and_cannot_pass(self):
        self.assertTrue(callable(getattr(smoke, 'close_engine_witness', None)), 'Fail-closed engine cleanup is missing')
        class Witness:
            def exited(self, seconds): raise OSError('retained process query failed')
            def close(self): pass
        record = {'guiVerified': True, 'success': False, 'error': 'original input failure'}
        smoke.close_engine_witness(Witness(), record)
        self.assertFalse(record['guiVerified'])
        self.assertFalse(record['success'])
        self.assertEqual(record['error'], 'original input failure')
        self.assertIn('retained process query failed', record['engineCleanupErrors'][0])

    def test_surviving_engine_cannot_pass_clean_style_shutdown(self):
        self.assertTrue(callable(getattr(smoke, 'close_engine_witness', None)), 'Fail-closed engine cleanup is missing')
        class Witness:
            def exited(self, seconds): return False
            def close(self): pass
        record = {'guiVerified': True, 'success': False}
        smoke.close_engine_witness(Witness(), record)
        self.assertFalse(record['guiVerified'])
        self.assertFalse(record['officeExitedAfterCleanup'])

    def test_saved_target_cannot_escape_owned_generated_fixture(self):
        (self.folder / 'fixtures').mkdir()
        path = self.folder / 'fixtures' / 'writer-heading1.docx'
        path.write_bytes(b'fixture')
        self.assertEqual(smoke.owned_saved_path(self.folder, {'copiedFixture': 'fixtures/writer-heading1.docx'}), path.resolve())
        for name in ('../foreign.docx', str(path.resolve()), 'fixtures/other.docx'):
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'owned'):
                smoke.owned_saved_path(self.folder, {'copiedFixture': name})


class PackagedPythonIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.suite = Path(self.temp.name).resolve()
        self.configure_runtime()

    def configure_runtime(self, version=(3, 13, 15), architecture='x64'):
        core = 'Office/program/python-core-' + '.'.join(str(part) for part in version)
        self.core = self.suite / core
        self.paths = {
            'launcher': 'Office/program/python.exe',
            'executable': core + '/bin/python.exe',
            'pythonDll': 'Office/program/python' + str(version[0]) + str(version[1]) + '.dll',
            'uno': 'Office/program/uno.py', 'pyuno': 'Office/program/pyuno.pyd',
            'encodings': core + '/lib/encodings/__init__.py',
            'os': core + '/lib/os.py',
        }
        self.inventory = {'schemaVersion': 1, 'architecture': architecture, 'files': {}}
        for role, relative in self.paths.items():
            path = self.suite / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = ('fixed packaged bytes for ' + role).encode()
            path.write_bytes(data)
            self.inventory['files'][relative] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        self.store_inventory()
        self.observed = {
            'implementation': 'cpython', 'version': list(version),
            'executable': str(self.suite / self.paths['executable']),
            'processImage': str(self.suite / self.paths['executable']),
            'nativeArchitecture': self.native_architecture(architecture),
            'prefix': str(self.core), 'basePrefix': str(self.core),
            'pythonDll': str(self.suite / self.paths['pythonDll']),
            'moduleFiles': {name: str(self.suite / self.paths[name]) for name in ('uno', 'pyuno', 'encodings', 'os')},
            'moduleOrigins': {name: str(self.suite / self.paths[name]) for name in ('uno', 'pyuno', 'encodings')},
        }

    @staticmethod
    def native_architecture(architecture):
        return {'processMachine': 0, 'nativeMachine': {'x64': 0x8664, 'arm64': 0xAA64}[architecture],
                'processArchitecture': architecture, 'nativeArchitecture': architecture}

    def store_inventory(self):
        (self.suite / 'suite-inventory.json').write_text(json.dumps(self.inventory), encoding='utf-8')

    def verify(self, observed=None):
        self.assertTrue(callable(getattr(smoke, 'require_packaged_python', None)), 'Packaged interpreter and module identity validation is missing')
        return smoke.require_packaged_python(self.suite, observed or self.observed)

    def test_actual_core_interpreter_and_exact_packaged_modules_are_accepted(self):
        receipt = self.verify()
        self.assertTrue(receipt['verified'])
        self.assertEqual(receipt['observed'], self.observed)
        self.assertEqual(set(receipt['files']), set(self.paths))
        for name, relative in self.paths.items():
            self.assertEqual(receipt['files'][name]['relativePath'], relative)
            self.assertEqual(receipt['files'][name]['sha256'], self.inventory['files'][relative]['sha256'])

    def test_native_arm64_interpreter_preserves_all_seven_packaged_identity_roles(self):
        self.configure_runtime(architecture='arm64')
        receipt = self.verify()
        self.assertTrue(receipt['verified'])
        self.assertEqual(receipt['observed']['nativeArchitecture'], self.native_architecture('arm64'))
        self.assertEqual(set(receipt['files']), set(self.paths))
        for role, relative in self.paths.items():
            with self.subTest(role=role):
                self.assertEqual(receipt['files'][role]['relativePath'], relative)
                self.assertEqual(receipt['files'][role]['sha256'], self.inventory['files'][relative]['sha256'])

    def test_frozen_x64_observation_without_native_architecture_remains_replayable(self):
        observed = copy.deepcopy(self.observed)
        del observed['nativeArchitecture']
        receipt = self.verify(observed)
        self.assertTrue(receipt['verified'])
        self.assertEqual(receipt['observed'], observed)

    def test_arm64_observation_requires_new_native_architecture_evidence(self):
        self.configure_runtime(architecture='arm64')
        for evidence in (None, 'arm64', {}):
            observed = copy.deepcopy(self.observed)
            observed['nativeArchitecture'] = evidence
            with self.subTest(evidence=evidence), self.assertRaisesRegex(AssertionError, 'architecture'):
                self.verify(observed)
        del observed['nativeArchitecture']
        with self.assertRaisesRegex(AssertionError, 'architecture'):
            self.verify(observed)

    def test_runtime_core_version_is_derived_for_both_supported_architectures(self):
        for architecture in ('x64', 'arm64'):
            self.configure_runtime(version=(3, 12, 9), architecture=architecture)
            with self.subTest(architecture=architecture):
                receipt = self.verify()
                self.assertEqual(receipt['files']['executable']['relativePath'], 'Office/program/python-core-3.12.9/bin/python.exe')
                self.assertEqual(receipt['files']['pythonDll']['relativePath'], 'Office/program/python312.dll')

    def test_inventory_rejects_unknown_or_missing_architecture(self):
        for architecture in (None, '', 'ARM64', 'amd64', 'arm', 'x86', 0xAA64, True):
            self.inventory['architecture'] = architecture
            self.store_inventory()
            with self.subTest(architecture=architecture), self.assertRaisesRegex(AssertionError, 'inventory'):
                self.verify()
        del self.inventory['architecture']
        self.store_inventory()
        with self.assertRaisesRegex(AssertionError, 'inventory'):
            self.verify()

    def test_inventory_architecture_must_match_native_interpreter_and_os(self):
        for architecture, other in (('x64', 'arm64'), ('arm64', 'x64')):
            self.configure_runtime(architecture=architecture)
            observed = copy.deepcopy(self.observed)
            observed['nativeArchitecture'] = self.native_architecture(other)
            with self.subTest(architecture=architecture), self.assertRaisesRegex(AssertionError, 'architecture'):
                self.verify(observed)

    def test_missing_emulated_or_inconsistent_native_architecture_cannot_qualify(self):
        bad = [None, 'x64', {},
               dict(self.native_architecture('x64'), processMachine=0x8664),
               dict(self.native_architecture('x64'), nativeMachine=0xAA64),
               dict(self.native_architecture('x64'), nativeMachine=0),
               dict(self.native_architecture('x64'), nativeMachine=True),
               dict(self.native_architecture('x64'), processArchitecture='arm64'),
               dict(self.native_architecture('x64'), nativeArchitecture='arm64')]
        for evidence in bad:
            observed = copy.deepcopy(self.observed)
            # A present invalid field is never a legacy receipt, even on x64.
            observed['nativeArchitecture'] = evidence
            with self.subTest(evidence=evidence), self.assertRaisesRegex(AssertionError, 'architecture'):
                self.verify(observed)

    def test_packaged_observation_captures_native_architecture_with_module_identity(self):
        modules = {name: SimpleNamespace(__file__=self.observed['moduleFiles'][name],
                    __spec__=SimpleNamespace(origin=self.observed['moduleOrigins'][name]))
                   for name in ('uno', 'pyuno', 'encodings')}
        self.assertTrue(hasattr(smoke, 'native_arch'), 'Shared native architecture observation is missing')
        for architecture in ('x64', 'arm64'):
            evidence = self.native_architecture(architecture)
            with self.subTest(architecture=architecture), mock.patch.dict('sys.modules', modules), \
                    mock.patch.object(smoke, '_windows_python_images', return_value={
                        name: self.observed[name] for name in ('processImage', 'pythonDll')}), \
                    mock.patch.object(smoke.native_arch, 'observe_native_architecture', return_value=evidence) as capture:
                observed = smoke.observe_packaged_python()
                self.assertEqual(observed['nativeArchitecture'], evidence)
                self.assertEqual(observed['moduleFiles']['uno'], self.observed['moduleFiles']['uno'])
                capture.assert_called_once_with()

    def test_windows_observation_is_replayed_portably_without_running_interpreter(self):
        root = PureWindowsPath('D:/a/OpenGeul/dist/OpenGeul-Office')
        observed = copy.deepcopy(self.observed)
        observed['prefix'] = observed['basePrefix'] = str(root / 'Office/program/python-core-3.13.15')
        for role in ('executable', 'processImage', 'pythonDll'):
            observed[role] = str(root / self.paths['executable' if role == 'processImage' else role])
        for field in ('moduleFiles', 'moduleOrigins'):
            observed[field] = {role: str(root / self.paths[role]) for role in observed[field]}
        self.assertEqual(smoke.validate_python_observation(str(root), observed, self.inventory), self.paths)
        observed['moduleOrigins']['uno'] = str(root / 'Office/program/../foreign/uno.py')
        with self.assertRaisesRegex(AssertionError, 'origin'):
            smoke.validate_python_observation(str(root), observed, self.inventory)

    def test_actual_launcher_core_directory_metadata_requires_new_native_image_evidence(self):
        observed = copy.deepcopy(ACTUAL_98_PYTHON_OBSERVATION)
        with self.assertRaisesRegex(AssertionError, 'process image'):
            smoke.validate_python_observation(ACTUAL_98_SUITE_ROOT, observed, self.inventory)
        # Synthetic NEW capture for a pure unit test; no old run is backfilled.
        observed['processImage'] = str(PureWindowsPath(ACTUAL_98_SUITE_ROOT) / self.paths['executable'])
        self.assertEqual(smoke.validate_python_observation(ACTUAL_98_SUITE_ROOT, observed, self.inventory), self.paths)
        self.assertEqual(observed['executable'], ACTUAL_98_PYTHON_OBSERVATION['executable'])

    def test_core_directory_metadata_is_accepted_only_with_exact_native_process_image(self):
        observed = copy.deepcopy(self.observed)
        observed['executable'] = str(self.core)
        self.assertTrue(self.verify(observed)['verified'])
        observed['processImage'] = str(self.suite / 'foreign/python.exe')
        with self.assertRaisesRegex(AssertionError, 'process image'):
            self.verify(observed)

    def test_launcher_or_missing_native_image_never_qualifies(self):
        for image in (None, str(self.suite / self.paths['launcher']), str(self.core)):
            observed = copy.deepcopy(self.observed)
            observed['processImage'] = image
            with self.subTest(image=image), self.assertRaisesRegex(AssertionError, 'process image'):
                self.verify(observed)

    def test_native_image_capture_uses_null_module_and_preserves_full_python_dll_handle(self):
        self.assertTrue(callable(getattr(smoke, '_windows_python_images', None)), 'Native Python process image capture is missing')
        calls = []
        images = ['D:\\Office\\python-core-3.13.15\\bin\\python.exe', 'D:\\Office\\python313.dll']
        class ModuleName:
            def __call__(self, handle, buffer, capacity):
                calls.append((handle.value, capacity))
                buffer.value = images[len(calls) - 1]
                return len(buffer.value)
        api = ModuleName()
        with mock.patch.object(ctypes, 'WinDLL', return_value=SimpleNamespace(GetModuleFileNameW=api), create=True) as load, \
                mock.patch.object(smoke.sys, 'dllhandle', 0x12345678ABCDEF01, create=True):
            self.assertEqual(smoke._windows_python_images(), {'processImage': images[0], 'pythonDll': images[1]})
        load.assert_called_once_with('kernel32', use_last_error=True)
        self.assertEqual(api.argtypes, [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32])
        self.assertIs(api.restype, ctypes.c_uint32)
        self.assertEqual(calls, [(None, 32768), (0x12345678ABCDEF01, 32768)])

    def test_failed_or_truncated_native_image_api_cannot_create_identity_receipt(self):
        self.assertTrue(callable(getattr(smoke, '_windows_python_images', None)), 'Native Python process image capture is missing')
        for bad_call, returned in ((0, 0), (0, 32768), (1, 0), (1, 32768)):
            calls = []
            class ModuleName:
                def __call__(self, handle, buffer, capacity):
                    index = len(calls)
                    calls.append(handle.value)
                    buffer.value = 'D:\\known.exe'
                    return returned if index == bad_call else len(buffer.value)
            with self.subTest(call=bad_call, returned=returned), \
                    mock.patch.object(ctypes, 'WinDLL', return_value=SimpleNamespace(GetModuleFileNameW=ModuleName()), create=True), \
                    mock.patch.object(smoke.sys, 'dllhandle', 0x12345678ABCDEF01, create=True), \
                    self.assertRaisesRegex(AssertionError, 'observe'):
                smoke._windows_python_images()

    def test_public_launcher_is_not_mistaken_for_actual_interpreter(self):
        observed = copy.deepcopy(self.observed)
        observed['executable'] = str(self.suite / self.paths['launcher'])
        with self.assertRaisesRegex(AssertionError, 'interpreter'):
            self.verify(observed)

    def test_foreign_python_with_same_basename_cannot_qualify(self):
        observed = copy.deepcopy(self.observed)
        observed['executable'] = str(self.suite / 'foreign/python-core-3.13.15/bin/python.exe')
        with self.assertRaisesRegex(AssertionError, 'interpreter'):
            self.verify(observed)

    def test_foreign_or_virtual_environment_prefix_cannot_qualify(self):
        for field in ('prefix', 'basePrefix'):
            observed = copy.deepcopy(self.observed)
            observed[field] = str(self.suite / 'foreign')
            with self.subTest(field=field), self.assertRaisesRegex(AssertionError, 'prefix'):
                self.verify(observed)

    def test_foreign_uno_python_or_native_modules_cannot_qualify(self):
        for architecture in ('x64', 'arm64'):
            self.configure_runtime(architecture=architecture)
            for field in self.observed['moduleFiles']:
                observed = copy.deepcopy(self.observed)
                observed['moduleFiles'][field] = str(self.suite / ('foreign/' + field + '.py'))
                with self.subTest(architecture=architecture, module=field), self.assertRaisesRegex(AssertionError, 'module'):
                    self.verify(observed)

    def test_forged_module_file_with_foreign_import_origin_is_rejected(self):
        for architecture in ('x64', 'arm64'):
            self.configure_runtime(architecture=architecture)
            for field in self.observed['moduleOrigins']:
                observed = copy.deepcopy(self.observed)
                observed['moduleOrigins'][field] = str(self.suite / ('foreign/' + field + '.py'))
                with self.subTest(architecture=architecture, module=field), self.assertRaisesRegex(AssertionError, 'origin'):
                    self.verify(observed)

    def test_foreign_loaded_python_dll_is_rejected(self):
        observed = copy.deepcopy(self.observed)
        observed['pythonDll'] = str(self.suite / 'foreign/python313.dll')
        with self.assertRaisesRegex(AssertionError, 'DLL'):
            self.verify(observed)

    def test_observed_version_must_match_unique_inventory_interpreter(self):
        for version in ([3, 12, 15], [3, 13, 14], [3, 13, '15']):
            observed = copy.deepcopy(self.observed)
            observed['version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(AssertionError, 'version'):
                self.verify(observed)

    def test_multiple_inventory_core_interpreters_are_not_ambiguously_accepted(self):
        self.inventory['files']['Office/program/python-core-3.12.12/bin/python.exe'] = dict(self.inventory['files'][self.paths['executable']])
        self.store_inventory()
        with self.assertRaisesRegex(AssertionError, 'unique'):
            self.verify()

    def test_modified_interpreter_launcher_dll_or_module_bytes_fail(self):
        for architecture in ('x64', 'arm64'):
            self.configure_runtime(architecture=architecture)
            for name, relative in self.paths.items():
                path = self.suite / relative
                original = path.read_bytes()
                path.write_bytes(original[:-1] + b'!')
                with self.subTest(architecture=architecture, file=name), self.assertRaisesRegex(AssertionError, 'inventory'):
                    self.verify()
                path.write_bytes(original)

    def test_required_identity_file_must_be_in_inventory(self):
        del self.inventory['files'][self.paths['uno']]
        self.store_inventory()
        with self.assertRaisesRegex(AssertionError, 'inventory'):
            self.verify()

    def test_reparse_point_in_module_or_ancestor_is_rejected(self):
        original_lstat = Path.lstat
        for linked in (self.suite / self.paths['uno'], self.suite / 'Office/program'):
            def lstat(path, *args, **kwargs):
                value = original_lstat(path, *args, **kwargs)
                if path == linked:
                    return type('ReparseStat', (), {'st_file_attributes': 0x400, 'st_mode': value.st_mode})()
                return value
            with self.subTest(path=linked), mock.patch.object(Path, 'lstat', lstat), self.assertRaisesRegex(AssertionError, 'linked'):
                self.verify()




class WriterNativeGuiTests(unittest.TestCase):
    def test_gui_rejects_emulated_controller_shell_or_office_before_editor_input(self):
        import sys
        class Function:
            def __init__(self, callback): self.callback = callback
            def __call__(self, *args): return self.callback(*args)
        for bad_role in ('controller', 'shell', 'office', None):
            with self.subTest(bad_role=bad_role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                suite, output = root/'suite', root/'evidence'
                suite.mkdir(); (output/'fixtures').mkdir(parents=True)
                (suite/'suite-inventory.json').write_text(json.dumps({
                    'schemaVersion': 1, 'architecture': 'arm64', 'files': {}}))
                original = root/'fixture.docx'; original.write_bytes(b'original generated fixture')
                roles = {100: 'controller', 200: 'shell', 300: 'office'}
                opened, closed = [], []
                def observe(handle, process, native):
                    process._obj.value = 0x8664 if roles[handle] == bad_role else 0
                    native._obj.value = 0xaa64
                    return True
                def open_process(access, inherit, pid):
                    handle = {77: 200, 31: 300}[pid]
                    opened.append(handle)
                    return handle
                kernel = SimpleNamespace(GetCurrentProcess=Function(lambda: 100),
                    IsWow64Process2=Function(observe), OpenProcess=Function(open_process),
                    CloseHandle=Function(lambda handle: closed.append(handle) or True))
                desktop, keys = mock.Mock(), mock.Mock()
                process = SimpleNamespace(pid=77, poll=lambda: 0)
                def failure(out, name, record, exc): record['error'] = str(exc)
                with mock.patch.dict(sys.modules, {'pywinauto': SimpleNamespace(Desktop=desktop),
                        'pywinauto.keyboard': SimpleNamespace(send_keys=keys)}), \
                        mock.patch.object(smoke.native_arch.ctypes, 'WinDLL', return_value=kernel, create=True), \
                        mock.patch.object(smoke.native, 'require_engine_fixture', return_value=original), \
                        mock.patch.object(smoke, 'docx_style_evidence', return_value={
                            'firstParagraphStyleId': 'Normal', 'sha256': hashlib.sha256(original.read_bytes()).hexdigest()}), \
                        mock.patch.object(smoke.native, 'launch_suite', return_value=process) as launched, \
                        mock.patch.object(smoke.native, 'Windows', return_value=SimpleNamespace()), \
                        mock.patch.object(smoke.native, 'verified_attachment', return_value=(11, 12, 22, 31)), \
                        mock.patch.object(smoke.startup, 'EngineProcessWitness', side_effect=RuntimeError('native-probes-complete')), \
                        mock.patch.object(smoke.native, 'capture_failure', side_effect=failure), \
                        mock.patch.object(smoke.native, 'stop_owned_test_process') as cleanup, \
                        mock.patch.object(smoke.native, 'write_result'):
                    record = smoke.run_gui(suite, root, output)
                self.assertFalse(record['guiVerified'])
                if bad_role is None:
                    self.assertEqual(record['error'], 'native-probes-complete')
                    self.assertIn('targetArchitecture', record, 'Actual owned Office native identity receipt is required')
                    self.assertEqual(record['targetArchitecture']['nativeMachine'], 0xaa64)
                else:
                    self.assertIn('architecture', record['error'])
                self.assertEqual(opened, closed, 'Every owned target query handle must close on success/failure')
                self.assertEqual(launched.call_count, 0 if bad_role == 'controller' else 1)
                self.assertEqual(cleanup.call_count, launched.call_count)
                desktop.assert_not_called(); keys.assert_not_called()
                self.assertEqual(original.read_bytes(), b'original generated fixture')


if __name__ == '__main__': unittest.main()
