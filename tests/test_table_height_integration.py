"""Build-graph gates supplement, but never replace, real render-tree regressions."""
from pathlib import Path
import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class TableHeightIntegrationTests(unittest.TestCase):
    def test_native_patch_precedes_wasm_verification_and_app_build(self):
        source = (ROOT/'scripts/build-msix.ps1').read_text(encoding='utf-8')
        apply = "python scripts/patch_table_height.py (Join-Path $source 'third_party/rhwp')"
        self.assertIn(apply, source)
        self.assertLess(source.index(apply), source.index('python scripts/wasm_artifacts.py install'))
        self.assertLess(source.index(apply), source.index('pnpm tauri build'))

    def test_native_render_test_runs_in_isolated_graph_before_cli_build(self):
        source = (ROOT/'scripts/build-msix.ps1').read_text(encoding='utf-8')
        test = 'cargo test --locked --test opengeul_table_height'
        self.assertIn(test, source)
        self.assertLess(source.index('$env:CARGO_TARGET_DIR = $cliTarget'), source.index(test))
        self.assertLess(source.index(test), source.index('cargo build --release'))
        self.assertIn('OPENGEUL_TABLE_FIXTURES', source)
        self.assertIn("Copy-Item 'overlay/table_height_test.rs' $tableTest", source)

    def test_native_and_wasm_use_real_fixture_validator(self):
        source = (ROOT/'scripts/build-msix.ps1').read_text(encoding='utf-8')
        self.assertIn('node e2e/table_height.mjs verify $tableVendor $tableFixtures', source)
        self.assertIn('python e2e/table_height_fixtures.py $tableFixtures', source)
        self.assertIn('if (Test-Path $tableTest)', source)

    def test_wasm_has_required_red_patch_rebuild_green_order(self):
        source = (ROOT/'scripts/build-wasm.sh').read_text(encoding='utf-8')
        stages = ['--expect-clipping', 'python scripts/patch_table_height.py', '"$wasmpack" build',
                  'python scripts/wasm_artifacts.py install',
                  'node e2e/table_height.mjs verify .work/hop/apps/studio-host/vendor/rhwp-core .work/table-fixtures\n']
        offsets = [source.index(stage) for stage in stages]
        self.assertEqual(offsets, sorted(offsets))

    def test_provenance_changes_when_table_patch_changes(self):
        spec = importlib.util.spec_from_file_location('wasm_provenance_test', ROOT/'scripts/wasm_artifacts.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative, data in [('config/upstream.lock.json', '{"rhwp":{"version":"0.8.4"}}'),
                                   ('overlay/hwpx_namespaces.rs', 'namespace helper'),
                                   ('scripts/patch_namespaces.py', 'namespace patch'),
                                   ('scripts/patch_table_height.py', 'table patch v1')]:
                target = root/relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(data)
            with patch.object(module, 'ROOT', root):
                before = module.expected()
                self.assertEqual(before['tableHeightPatcher'], hashlib.sha256(b'table patch v1').hexdigest())
                (root/'scripts/patch_table_height.py').write_text('table patch v2')
                self.assertNotEqual(before['tableHeightPatcher'], module.expected()['tableHeightPatcher'])

if __name__ == '__main__':unittest.main()
