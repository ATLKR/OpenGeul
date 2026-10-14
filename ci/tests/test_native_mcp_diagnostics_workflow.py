"""Independent MCP diagnostics never convert a failed native job to a release."""
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PREPARE = '시험 도구 설치와 실제 제품 파일 신원 확인'
FIXTURES = 'GUI 결과와 별개인 MCP 암호 입력 준비'
MCP = '실제 MCP stdio·암호 입력·COM 작업자 실패 격리 검사'


class NativeMcpDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.jobs = yaml.safe_load((ROOT / '.github/workflows/msix.yml').read_text())['jobs']

    def test_independent_mcp_requires_successful_actual_runtime_and_fixture_outcomes(self):
        for name in ('native-e2e', 'native-e2e-arm64'):
            with self.subTest(job=name):
                steps = self.jobs[name]['steps']
                prepare = next(s for s in steps if s.get('name') == PREPARE)
                self.assertEqual(prepare.get('id'), 'runtime-ready')
                fixture = next(s for s in steps if s.get('name') == FIXTURES)
                self.assertEqual(fixture.get('id'), 'mcp-fixtures')
                self.assertNotIn('if', fixture)
                self.assertNotIn('continue-on-error', fixture)
                self.assertIn('node e2e/password/generate-password-fixtures.mjs wasm-input inputs/e2e-fixtures mcp-password-fixtures', fixture['run'])
                self.assertIn('$PSNativeCommandUseErrorActionPreference=$true', fixture['run'])
                mcp = next(s for s in steps if s.get('name') == MCP)
                expected = "always() && !cancelled() && steps.runtime-ready.outcome == 'success' && steps.mcp-fixtures.outcome == 'success'"
                if name.endswith('-arm64'):
                    expected += " && steps.runner-ready.outcome == 'success'"
                    ready = next(s for s in steps if s.get('id') == 'runner-ready')
                    self.assertLess(steps.index(ready), steps.index(fixture))
                self.assertEqual(mcp.get('if'), expected)
                self.assertNotIn('continue-on-error', mcp)
                self.assertIn('--password-fixtures mcp-password-fixtures', mcp['run'])
                self.assertIn('windowsComponents.components.cli.sha256', mcp['run'])
                self.assertNotIn('Get-FileHash', mcp['run'])
                ui = next(s for s in steps if 'python e2e/run.py' in s.get('run', ''))
                self.assertLess(steps.index(prepare), steps.index(fixture))
                self.assertLess(steps.index(fixture), steps.index(ui))
                self.assertLess(steps.index(ui), steps.index(mcp))

    def test_ui_password_and_qa_keep_success_only_release_semantics(self):
        for name in ('native-e2e', 'native-e2e-arm64'):
            with self.subTest(job=name):
                job = self.jobs[name]
                self.assertNotIn('continue-on-error', job)
                for step in job['steps']:
                    run = step.get('run', '')
                    if 'python e2e/run.py' in run or 'python e2e/password/native.py' in run:
                        self.assertNotIn('if', step)
                        self.assertNotIn('continue-on-error', step)
                    if 'python e2e/password/native.py' in run:
                        self.assertIn('node e2e/password/generate-password-fixtures.mjs wasm-input inputs/e2e-fixtures password-fixtures', run)
                    if 'e2e/mcp_fixtures.py stage' in run or step.get('with', {}).get('path') == 'mcp-qa/':
                        self.assertEqual(step['if'], "env.E2E_ARCHITECTURE == 'arm64' || matrix.os == 'windows-2025'")
                        self.assertNotIn('always()', step['if'])
                self.assertIn(name, self.jobs['release']['needs'])
                release_if = self.jobs['release'].get('if', '')
                self.assertNotIn('always()', release_if)
                self.assertNotIn('continue-on-error', self.jobs['release'])

    def test_actual_mcp_conditions_reject_setup_failures_and_cancellation(self):
        def permits(expression, states, *, cancelled=False):
            # Interpret only the small reviewed GitHub condition grammar, never
            # evaluate repository text as Python or normalize failed outcomes.
            for term in expression.split(' && '):
                if term == 'always()':
                    continue
                if term == '!cancelled()':
                    if cancelled:return False
                    continue
                match = re.fullmatch(r"steps\.([a-z-]+)\.outcome == 'success'", term)
                self.assertIsNotNone(match, term)
                if states.get(match[1], {}).get('outcome') != 'success':return False
            return True
        for name in ('native-e2e', 'native-e2e-arm64'):
            steps = self.jobs[name]['steps']
            mcp = next(s for s in steps if s.get('name') == MCP)
            prerequisites = ['runtime-ready','mcp-fixtures']
            if name.endswith('-arm64'):prerequisites.append('runner-ready')
            good = {key:{'outcome':'success','conclusion':'success'} for key in prerequisites}
            # UI/password failures remain job failures while the independent
            # read/write/worker probe still supplies its own real result.
            good.update(ui={'outcome':'failure'}, password={'outcome':'skipped'})
            self.assertTrue(permits(mcp['if'], good))
            self.assertFalse(permits(mcp['if'], good, cancelled=True))
            for key in prerequisites:
                for outcome in ('failure','skipped','cancelled',None):
                    with self.subTest(job=name, prerequisite=key, outcome=outcome):
                        bad = {**good, key:{'outcome':outcome,'conclusion':'success'}}
                        self.assertFalse(permits(mcp['if'], bad))
                absent = dict(good);del absent[key]
                self.assertFalse(permits(mcp['if'], absent))


if __name__ == '__main__':
    unittest.main()
