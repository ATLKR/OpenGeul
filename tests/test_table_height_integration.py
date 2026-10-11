"""Build-graph gates supplement, but never replace, real render-tree regressions."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class TableHeightIntegrationTests(unittest.TestCase):
    def test_absorbed_table_backport_is_not_applied_to_native_or_wasm(self):
        source = (ROOT/'scripts/build-msix.ps1').read_text(encoding='utf-8')
        self.assertNotIn('patch_table_height', source)
        self.assertNotIn('patch_table_height', (ROOT/'scripts/build-wasm.sh').read_text())

    def test_native_render_test_runs_in_isolated_graph_before_cli_build(self):
        source = (ROOT/'scripts/build-msix.ps1').read_text(encoding='utf-8')
        test = 'cargo test --locked --test opengeul_table_height'
        self.assertIn(test, source)
        self.assertLess(source.index('$env:CARGO_TARGET_DIR = $cliTarget'), source.index(test))
        self.assertLess(source.index(test), source.index('cargo build --release'))
        self.assertIn('OPENGEUL_TABLE_FIXTURES', source)
        self.assertIn("python scripts/prepare_native_tests.py (Join-Path $source 'third_party/rhwp')", source)

    def test_native_and_wasm_use_real_fixture_validator(self):
        source = (ROOT/'scripts/build-msix.ps1').read_text(encoding='utf-8')
        self.assertIn('node e2e/table_height.mjs verify $tableVendor $tableFixtures', source)
        self.assertIn('python e2e/table_height_fixtures.py $tableFixtures', source)
        self.assertLess(source.index('python scripts/prepare_native_tests.py'), source.index('cargo test --locked --test opengeul_table_height'))

    def test_wasm_baseline_and_rebuild_both_verify_table_geometry(self):
        source = (ROOT/'scripts/build-wasm.sh').read_text(encoding='utf-8')
        check='node e2e/table_height.mjs verify .work/hop/apps/studio-host/vendor/rhwp-core .work/table-fixtures\n'
        self.assertEqual(source.count(check), 2)
        self.assertNotIn('--expect-clipping', source)
        stages = [check, '"$wasmpack" build',
                  'python scripts/wasm_artifacts.py install',
                  ]
        offsets = [source.index(stage) for stage in stages]
        self.assertEqual(offsets, sorted(offsets))
        self.assertGreater(source.rindex(check), offsets[-1])

    def test_table_provenance_is_bound_to_upstream_commit(self):
        spec = importlib.util.spec_from_file_location('wasm_provenance_test', ROOT/'scripts/wasm_artifacts.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative, data in [('config/upstream.lock.json', '{"rhwp":{"version":"0.8.7","commit":"first-reviewed-commit"}}'),
                                   ('overlay/hwpx_namespaces.rs', 'namespace helper'),
                                   ('scripts/patch_namespaces.py', 'namespace patch')]:
                target = root/relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(data)
            with patch.object(module, 'ROOT', root):
                before = module.expected()
                self.assertNotIn('tableHeightPatcher', before)
                (root/'config/upstream.lock.json').write_text('{"rhwp":{"version":"0.8.7","commit":"different-commit"}}')
                self.assertNotEqual(before['upstream'], module.expected()['upstream'])

if __name__ == '__main__':unittest.main()
