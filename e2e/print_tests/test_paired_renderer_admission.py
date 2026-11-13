import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'paired_print_diagnostic.py'
sys.path.insert(0, str(FILE.parent))
spec = importlib.util.spec_from_file_location('paired_renderer_admission_candidate', FILE)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

LEGACY = {
    'version': '1.1.4', 'sourceCommit': '131ccbf3ac10a82e1d6785b4c906fb836b912e73',
    'url': 'https://github.com/ATLKR/OpenGeul/releases/download/v1.1.4/OpenGeul_1.1.4_windows-x64_unsigned-portable.zip',
    'size': 33362247, 'sha256': '6bda733fba96ae692c504630eceb1113f5f11f7cac9208158531960e5d822764',
    'sourceUrl': 'https://github.com/ATLKR/OpenGeul/tree/131ccbf3ac10a82e1d6785b4c906fb836b912e73',
    'provenanceUrl': 'https://github.com/ATLKR/OpenGeul/releases/download/v1.1.4/provenance-x64.json',
}


class RendererAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(api, 'legacy_assets', None)), 'legacy canonical-route admission is absent')
        self.assertTrue(callable(getattr(api, 'admit_current', None)), 'current same-run admission is absent')
        self.upstream = {'rhwp': {'version': '0.9.0', 'commit': 'c9095c5f67632e6721e800ccc7fb43ea49d26682'},
                         'hop': {'version': '0.5.3', 'commit': 'c298160120c9ffbfca7e72f13dc2e7060ddff7fe'}}
        self.wasm_source = {'upstream': self.upstream, 'namespaceHelper': '1' * 64, 'namespacePatcher': '2' * 64}
        wasm = {**copy.deepcopy(self.wasm_source), 'generator': 'wasm-pack 0.14.0 --target web --release --no-opt --no-default-features --features console_error_panic_hook,wasm-api',
                'artifacts': {name: '3' * 64 for name in ('rhwp.js', 'rhwp.d.ts', 'rhwp_bg.wasm', 'rhwp_bg.wasm.d.ts', 'package.json', 'LICENSE')}}
        editor = {'artifactName': 'opengeul-editor-component-17', 'runAttempt': '1', 'provenanceSha256': '4' * 64, 'runtime': 'OpenGeul.exe', 'size': 300, 'sha256': 'b' * 64}
        cli = {'artifactName': 'opengeul-cli-component-17', 'runAttempt': '1', 'provenanceSha256': '5' * 64, 'runtime': 'Tools/rhwp.exe', 'size': 400, 'sha256': '6' * 64}
        self.value = {'unsigned': True, 'architecture': 'x64', 'members': 1760, 'sha256': '7' * 64,
                      'repository': 'ATLKR/OpenGeul', 'commit': 'a' * 40, 'runId': '17',
                      'version': '1.1.5', 'package': 'current.msix', 'upstream': self.upstream,
                      'sourceParity': {'wasmRebuild': wasm}, 'manualWindowsUx': 'not-verified', 'storeCertified': False,
                      'windowsComponents': {'formatVersion': 1, 'repository': 'ATLKR/OpenGeul', 'commit': 'a' * 40,
                                            'runId': '17', 'runAttempt': '1', 'sourceContractSha256': '8' * 64,
                                            'components': {'editor': editor, 'cli': cli}}}

    def current(self, **kw):
        return api.admit_current(self.value, expected_source='a' * 40, run_id=17, attempt=1,
                                 expected_upstream=self.upstream, expected_wasm_source=self.wasm_source,
                                 runtime_sha256=kw.get('runtime_sha256', 'b' * 64), runtime_bytes=300)

    def test_canonical_legacy_route_has_one_fixed_portable_and_provenance(self):
        assets = api.legacy_assets(LEGACY)
        self.assertEqual(assets['portable']['size'], 33362247)
        self.assertEqual(assets['portable']['sha256'], '6bda733fba96ae692c504630eceb1113f5f11f7cac9208158531960e5d822764')
        self.assertEqual(assets['provenance']['size'], 47724)
        self.assertEqual(assets['provenance']['sha256'], 'bf095615f053f1a17d41843f637c4c27ac0110f0bf37324acb2a80c45c7006cb')

    def test_latest_or_other_version_is_not_a_legacy_fallback(self):
        changed = {**LEGACY, 'version': 'latest'}
        with self.assertRaises(api.Rejected): api.legacy_assets(changed)

    def test_alternate_archive_and_boolean_size_are_rejected(self):
        for changed in ({**LEGACY, 'url': 'https://example.invalid/other.zip'}, {**LEGACY, 'size': True}):
            with self.assertRaises(api.Rejected): api.legacy_assets(changed)

    def test_unknown_legacy_key_cannot_request_another_input(self):
        with self.assertRaises(api.Rejected): api.legacy_assets({**LEGACY, 'fallback': 'other'})

    def test_current_binds_source_run_attempt_component_bytes_and_wasm(self):
        result = self.current()
        self.assertEqual(result, {'editorSha256': 'b' * 64, 'editorBytes': 300, 'wasmSha256': '3' * 64, 'jsSha256': '3' * 64})

    def test_receipt_source_cannot_choose_the_expected_source(self):
        self.value['commit'] = '9' * 40
        with self.assertRaises(api.Rejected): self.current()

    def test_same_source_from_another_run_is_rejected(self):
        self.value['runId'] = '18'
        with self.assertRaises(api.Rejected): self.current()

    def test_other_attempt_cannot_supply_the_current_assembly(self):
        self.value['windowsComponents']['runAttempt'] = '2'
        with self.assertRaises(api.Rejected): self.current()

    def test_prepare_runtime_hash_is_independent_of_declared_component_hash(self):
        with self.assertRaises(api.Rejected): self.current(runtime_sha256='9' * 64)

    def test_current_wasm_source_closure_must_match_the_harness_expected_closure(self):
        self.value['sourceParity']['wasmRebuild']['namespaceHelper'] = '9' * 64
        with self.assertRaises(api.Rejected): self.current()

    def test_source_only_or_unknown_top_level_marker_is_rejected(self):
        self.value['publicQaOnly'] = True
        with self.assertRaises(api.Rejected): self.current()

    def test_wrong_component_transport_role_is_rejected(self):
        self.value['windowsComponents']['components']['editor']['artifactName'] = 'opengeul-cli-component-17'
        with self.assertRaises(api.Rejected): self.current()

    def test_unsigned_and_not_store_certified_are_exact_booleans(self):
        self.value['unsigned'] = 1
        with self.assertRaises(api.Rejected): self.current()

    def test_boolean_member_size_is_not_runtime_binding(self):
        self.value['windowsComponents']['components']['editor']['size'] = True
        with self.assertRaises(api.Rejected): self.current()

    def test_unknown_wasm_file_cannot_hide_in_source_provenance(self):
        self.value['sourceParity']['wasmRebuild']['artifacts']['other.wasm'] = '9' * 64
        with self.assertRaises(api.Rejected): self.current()


if __name__ == '__main__': unittest.main()
