"""Mandatory portable valid16 wiring; the installed33 gate remains unchanged."""
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]
STEP='구조 문서의 유효 CLI·MCP 16개 필수 검사'
PREFIX='e2e/structured_cli_mcp/'
HELPERS=('valid_companion.py','structured_oracle.py','stage_structured.py','generate_structured.rs','expected.json')

class StructuredMcpWorkflowTests(unittest.TestCase):
    def test_korean_ime_preparation_is_required_before_native_ui_and_keeps_cli_independent(self):
        jobs=yaml.safe_load((ROOT/'.github/workflows/msix.yml').read_text())['jobs']
        for name in ('native-e2e','native-e2e-arm64'):
            steps=jobs[name]['steps'];entries=[s for s in steps if s.get('name')=='한국어 IME의 실제 Windows 기능·사용자 프로필 준비']
            self.assertEqual(len(entries),1);step=entries[0]
            self.assertNotIn('if',step);self.assertNotIn('continue-on-error',step)
            self.assertEqual(step['shell'],'pwsh')
            self.assertEqual(step['run'],'./scripts/ensure-korean-ime.ps1 -ExpectedSource $env:GITHUB_SHA -Output evidence/korean-ime-readiness')
            fixtures=next(s for s in steps if s.get('id')=='mcp-fixtures')
            ui=next(s for s in steps if 'python e2e/run.py' in s.get('run',''))
            self.assertLess(steps.index(fixtures),steps.index(step));self.assertLess(steps.index(step),steps.index(ui))
            for diagnostic in (s for s in steps if 'mcp_worker.py' in s.get('run','') or s.get('name')==STEP):
                self.assertNotIn('steps.ime',diagnostic['if'])
    def test_compiled_example_and_all_helpers_are_source_bound(self):
        import sys
        sys.path.insert(0,str(ROOT/'scripts'))
        import windows_components as c
        mapped='apps/desktop/src-tauri/examples/opengeul-structured-fixtures.rs'
        self.assertEqual(c.COPIED_OVERLAYS.get(mapped),PREFIX+'generate_structured.rs')
        self.assertIn(mapped,c.SOURCE_FILES)
        self.assertTrue({PREFIX+n for n in HELPERS}<=set(c.configured()['helpers']))
        prepare=(ROOT/'scripts/prepare_hwpx.py').read_text()
        self.assertIn("examples/'opengeul-structured-fixtures.rs'",prepare)
    def test_editor_native_graph_builds_stages_and_seals_same_source_inputs(self):
        build=(ROOT/'scripts/build-msix.ps1').read_text()
        compile='cargo build --locked --target $target --example opengeul-structured-fixtures'
        self.assertIn(compile,build)
        self.assertLess(build.index('cargo run --locked --target $target --example opengeul-fixtures'),build.index(compile))
        self.assertIn('python -m pip install Pillow==12.3.0',build)
        self.assertIn('debug/examples/opengeul-structured-fixtures.exe',build)
        self.assertIn("python (Join-Path $root 'e2e/structured_cli_mcp/stage_structured.py') generate",build)
        self.assertIn('e2e/structured_cli_mcp/stage_structured.py seal',build)
        self.assertLess(build.index('scripts/windows_components.py capture --role'),build.index('e2e/structured_cli_mcp/stage_structured.py seal'))
    def test_both_editor_transports_keep_original_inputs_and_sixteen_mib_cap(self):
        jobs=yaml.safe_load((ROOT/'.github/workflows/msix.yml').read_text())['jobs']
        for name in ('windows-editor','windows-editor-arm64'):
            run=next(s['run'] for s in jobs[name]['steps'] if s.get('name')=='네이티브 시험 문서만 준비')
            self.assertIn("'.work/e2e-fixtures', '.work/native-inputs/e2e-fixtures'",run)
            self.assertIn("'.work/structured-fixtures', '.work/native-inputs/structured-fixtures'",run)
            self.assertIn("'.work/structured-input-binding.json', '.work/native-inputs/structured-input-binding.json'",run)
            self.assertIn('size --limit-mib 16 .work/native-inputs',run)
    def test_native_three_require_valid16_even_after_gui_or_original_mcp_failure(self):
        jobs=yaml.safe_load((ROOT/'.github/workflows/msix.yml').read_text())['jobs']
        for name in ('native-e2e','native-e2e-arm64'):
            steps=jobs[name]['steps'];entries=[s for s in steps if s.get('name')==STEP]
            self.assertEqual(len(entries),1)
            step=entries[0]
            guard="always() && !cancelled() && steps.runtime-ready.outcome == 'success' && steps.mcp-fixtures.outcome == 'success'"
            if name.endswith('-arm64'):guard+=" && steps.runner-ready.outcome == 'success'"
            self.assertEqual(step['if'],guard)
            self.assertNotIn('continue-on-error',step)
            run=step['run']
            for flag in ('--fixtures inputs/structured-fixtures','--binding inputs/structured-input-binding.json','--package-provenance package/provenance.json','--expected-sha256 $cliSha','--out evidence/structured-cli-mcp'):
                self.assertIn(flag,run)
            self.assertIn('windowsComponents.components.cli.sha256',run)
            fixtures=next(s for s in steps if s.get('id')=='mcp-fixtures')
            self.assertLess(steps.index(fixtures),steps.index(step))
            qa=next(s for s in steps if 'e2e/mcp_fixtures.py stage' in s.get('run',''))
            self.assertLess(steps.index(step),steps.index(qa))
            self.assertNotIn('always()',qa['if'])
            self.assertIn(name,jobs['release']['needs'])

if __name__=='__main__':unittest.main()
