import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import paired_print_run as api
import paired_print_contract as core
import test_paired_renderer_admission as fixtures


class PreparedBindingTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.RendererAdmissionTests()
        f.setUp()
        self.value, self.wasm = copy.deepcopy(f.value), copy.deepcopy(f.wasm_source)
        self.prepared = {'msix': 'current.msix', 'portable': 'current-portable.zip',
            'architecture': 'x64', 'editorSha256': 'b' * 64, 'verifiedRuntimeFiles': 1700,
            'runtimeManifestSha256': '8' * 64}
        self.fps = {'old.exe': {'sha256': core.LEGACY_EDITOR, 'bytes': 36402688},
                    'current.exe': {'sha256': 'b' * 64, 'bytes': 300},
                    'provenance.json': {'sha256': '6' * 64, 'bytes': 10000},
                    'current.msix': {'sha256': '7' * 64, 'bytes': 10000}}

    def call(self, **kw):
        with mock.patch.object(api, 'fingerprint_file', side_effect=lambda p, *a: self.fps[Path(p).name]), \
             mock.patch.object(api, 'read_json', return_value=self.value):
            return api.bind_prepared(Path('old.exe'), Path('current.exe'), Path('package'),
                self.prepared, kw.get('provenance_sha', '6' * 64), expected_source='a' * 40,
                run_id=17, attempt=1, expected_wasm_source=self.wasm)

    def test_actual_prepared_runtime_and_externally_pinned_provenance_are_joined(self):
        value = self.call()
        self.assertEqual(value['renderers'][0]['appSourceCommit'], core.LEGACY_SOURCE)
        self.assertEqual(value['renderers'][1]['executableSha256'], 'b' * 64)

    def test_different_legacy_binary_does_not_inherit_114_label(self):
        self.fps['old.exe']['sha256'] = '9' * 64
        with self.assertRaises(core.Rejected): self.call()

    def test_unpinned_provenance_does_not_choose_source_or_executable(self):
        with self.assertRaises(core.Rejected): self.call(provenance_sha='9' * 64)

    def test_msix_header_hash_is_compared_to_the_actual_prepared_archive(self):
        self.fps['current.msix']['sha256'] = '9' * 64
        with self.assertRaises(core.Rejected): self.call()

    def test_successful_prepare_does_not_itself_supply_provenance(self):
        self.value['commit'] = '9' * 40
        with self.assertRaises(core.Rejected): self.call()

    def test_other_runtime_cannot_replace_the_prepared_editor(self):
        self.prepared['editorSha256'] = '9' * 64
        with self.assertRaises(core.Rejected): self.call()

    def test_unknown_prepare_shape_cannot_smuggle_another_source(self):
        self.prepared['sourceCommit'] = 'a' * 40
        with self.assertRaises(core.Rejected): self.call()

    def test_component_count_must_be_integer_not_boolean(self):
        self.prepared['verifiedRuntimeFiles'] = True
        with self.assertRaises(core.Rejected): self.call()

    def test_prepared_msix_must_be_exact_safe_basename(self):
        self.prepared['msix'] = '../current.msix'
        self.value['package'] = '../current.msix'
        with self.assertRaises(core.Rejected): self.call()

    def test_actual_current_runtime_fingerprint_is_not_read_from_the_receipt(self):
        self.fps['current.exe']['sha256'] = '9' * 64
        with self.assertRaises(core.Rejected): self.call()


if __name__ == '__main__': unittest.main()
