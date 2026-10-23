"""Static diagnostic wiring only; these checks do not qualify native input."""
from pathlib import Path
import re
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/suite-native35-input-witness.yml'
MAIN = ROOT / '.github/workflows/office-suite.yml'
BRANCH = 'refs/heads/work/native35-arm64-input-witness'
PINS = {
    'actions/checkout': 'fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09',
    'actions/setup-python': 'ece7cb06caefa5fff74198d8649806c4678c61a1',
    'actions/upload-artifact': 'ea165f8d65b6e75b540449e92b4886f43607fa02',
}


def steps(source):
    return re.split(r'^    - (?=name: |uses: )', source, flags=re.M)[1:]


def field(step, name, indent=6):
    match = re.search(r'^' + ' ' * indent + re.escape(name) + r': (.+)$', step, re.M)
    return match.group(1) if match else None


def run_code(step):
    match = re.search(r'^      run: \|\n((?:        .*\n|\n)+)', step, re.M)
    if match is None:
        raise AssertionError('Expected a literal run block')
    return textwrap.dedent(match.group(1))


def named(source, name):
    return next(step for step in steps(source) if step.splitlines()[0] == 'name: ' + name)


class Native35InputWitnessWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WORKFLOW.is_file(), 'Isolated input witness workflow is missing')
        self.source = WORKFLOW.read_text(encoding='utf-8')
        self.main = MAIN.read_text(encoding='utf-8')
        self.steps = steps(self.source)

    def test_only_diagnostic_owner_push_arm64_job_and_read_permissions(self):
        trigger = self.source.split("'on':\n", 1)[1].split('permissions:\n', 1)[0]
        self.assertEqual(trigger, '  push:\n    branches:\n    - work/native35-arm64-input-witness\n')
        permissions = self.source.split('permissions:\n', 1)[1].split('concurrency:\n', 1)[0]
        self.assertEqual(permissions, '  contents: read\n  actions: read\n')
        concurrency = self.source.split('concurrency:\n', 1)[1].split('env:\n', 1)[0]
        self.assertIn('group: suite-native35-input-witness-${{ github.ref }}', concurrency)
        self.assertIn('cancel-in-progress: false', concurrency)
        job = self.source.split('jobs:\n', 1)[1].split('    steps:\n', 1)[0]
        self.assertEqual(re.findall(r'^  ([a-zA-Z0-9_-]+):$', job, re.M), ['windows-suite'])
        self.assertIn('timeout-minutes: 60', job)
        self.assertIn('architecture: arm64\n          runner: windows-11-arm', job)
        self.assertNotIn('architecture: x64', job)
        self.assertIn('runs-on: ${{ matrix.runner }}', job)
        self.assertIn('github.event.repository.private == false', job)
        self.assertIn("github.ref == '" + BRANCH + "'", job)
        self.assertNotIn('work/opengeul-office-arm64', self.source)

    def test_existing_action_pins_and_no_publication_or_full_tests(self):
        actions = re.findall(r'^\s+(?:- )?uses: (.+)$', self.source, re.M)
        self.assertTrue(actions)
        for action in actions:
            name, pin = action.split('@')
            self.assertEqual(PINS.get(name), pin, action)
        self.assertIn('persist-credentials: false', self.source)
        for forbidden in ('unittest', 'pytest', 'dotnet run', 'windows_smoke.py',
                          'korean_ime_smoke.py', 'startup_smoke.py', 'calc_save_smoke.py',
                          'calc_close_probe.py', 'writer_style_smoke.py', 'gh release',
                          'git push', 'workflow_dispatch', 'pull_request'):
            self.assertNotIn(forbidden, self.source)
        uploads = [step for step in self.steps if 'uses: actions/upload-artifact@' in step]
        self.assertTrue(uploads)
        for upload in uploads:
            self.assertNotIn('${{ env.SUITE_PACKAGE }}.zip', upload)
            self.assertIn('include-hidden-files: true', upload)

    def test_preparation_source_commands_are_copied_from_main(self):
        names = (
            '정확한 소스 바이트 보존',
            '독립 PDF 검증 도구의 고정 해시 확인·설치',
            '고정 버전의 패키지 경로 선택',
            '고정한 네이티브 ARM64 소스 빌드 입력 확보',
            '고정 입력으로 별도 Suite 개발 패키지 빌드',
            '실제 한국어 IME와 네이티브 UI 검사 준비',
            '실제 Office 엔진의 생성·편집·저장·재열기',
        )
        for name in names:
            with self.subTest(step=name):
                self.assertEqual(run_code(named(self.source, name)), run_code(named(self.main, name)))
        fetch = named(self.source, '고정한 네이티브 ARM64 소스 빌드 입력 확보')
        self.assertIn('GH_TOKEN: ${{ github.token }}', fetch)
        self.assertEqual(field(fetch, 'if'), "matrix.architecture == 'arm64'")

    def test_main_privacy_entry_is_omitted_and_diagnostic_preparation_is_separately_recorded(self):
        for forbidden in ('prepare-native31.ps1', 'native31_suite_prepare.py',
                          'suite-native31-privacy-preparation', 'suite-native31-setup'):
            self.assertNotIn(forbidden, self.source)
        metadata = named(self.source, 'Record diagnostic workflow scope')
        code = run_code(metadata)
        for field_name in ('mainNativePrivacySetupPerformed', 'privacyPreparationQualified',
                           'hostReadyQualified', 'productQualified', 'officeReplacementCertified', 'success'):
            self.assertRegex(code, re.escape(field_name) + r'\s*=\s*\$false\b')
        self.assertRegex(code, r'diagnosticOnly\s*=\s*\$true\b')
        self.assertNotRegex(code, r'\bnativePrivacySetupPerformed\b')
        self.assertRegex(code, r'diagnosticPreparationSeparatelyRecorded\s*=\s*\$true\b')
        self.assertIn("diagnosticPreparationEvidence = '.work/suite-input-witness-preparation/'", code)
        self.assertIn('.work/suite-input-witness-context', code)
        self.assertIn('workflow-context.json', code)
        self.assertLess(self.steps.index(metadata), next(i for i, step in enumerate(self.steps) if field(step, 'id') == 'build'))
        # The Main entry stays omitted; diagnostic preparation never spoofs context.
        self.assertNotRegex(self.source, r'\$env:GITHUB_[A-Z_]+\s*=')
        self.assertNotRegex(self.source, r'\$env:RUNNER_[A-Z_]+\s*=')

    def test_witness_and_fixtures_wait_for_separate_diagnostic_preparation(self):
        readiness = next(i for i, step in enumerate(self.steps) if field(step, 'id') == 'readiness')
        preparation = next(i for i, step in enumerate(self.steps) if field(step, 'id') == 'diagnostic-preparation')
        fixtures = next(i for i, step in enumerate(self.steps) if field(step, 'id') == 'fixtures')
        witness = next(i for i, step in enumerate(self.steps) if field(step, 'id') == 'input-witness')
        self.assertLess(readiness, preparation)
        self.assertLess(preparation, fixtures)
        self.assertLess(fixtures, witness)
        prepare = self.steps[preparation]
        self.assertEqual(field(prepare, 'timeout-minutes'), '3')
        preparation_code = run_code(prepare)
        self.assertIn('./suite/scripts/prepare-native35-input-witness.ps1', preparation_code)
        self.assertIn("$ErrorActionPreference = 'Stop'", preparation_code)
        self.assertNotIn('$LASTEXITCODE', preparation_code)
        self.assertIn("steps.readiness.outcome == 'success'", field(prepare, 'if'))
        self.assertIn("steps.diagnostic-preparation.outcome == 'success'", field(self.steps[fixtures], 'if'))
        probe = self.steps[witness]
        code = run_code(probe)
        command = ('python suite/e2e/ime_input_witness.py --suite $env:SUITE_PACKAGE '
                   '--fixtures .work/suite-engine/fixtures '
                   '--readiness .work/suite-korean-readiness/readiness.json '
                   '--output .work/suite-input-witness')
        self.assertIn(command, code)
        self.assertIn("if ($LASTEXITCODE -ne 0) { throw 'Native ARM64 input witness diagnostic failed.' }", code)
        condition = field(probe, 'if')
        for dependency in ('fixtures', 'readiness', 'diagnostic-preparation'):
            self.assertIn('steps.' + dependency + ".outcome == 'success'", condition)
        self.assertIn(BRANCH, condition)
        self.assertIn('!cancelled()', condition)

    def test_preparation_always_uploads_staged_and_original_evidence_without_source_checkout(self):
        upload = named(self.source, 'Preserve diagnostic desktop preparation originals')
        self.assertEqual(field(upload, 'if'), 'always()')
        for value in ('include-hidden-files: true', 'retention-days: 7', '.work/suite-input-witness-preparation/',
                      '${{ runner.temp }}/suite-input-witness-setup-', '${{ runner.temp }}/suite-input-witness-preparation-'):
            self.assertIn(value, upload)
        self.assertNotIn('suite-input-witness-source-', upload)

    def test_witness_inherits_exact_main_worker_diagnostics_root_before_launch(self):
        witness = named(self.source, 'Native ARM64 physical input witness diagnostic')
        production = named(self.main, '실제 한국어 조합·백스페이스·저장·재열기')
        def environment(step):
            match = re.search(r'^      env:\n((?:        .+\n)+)', step, re.M)
            return match.group(1) if match else None
        # Production launches Suite with the inherited environment, then admits
        # retirement against this exact shared root before observer command1.
        # The diagnostic harness delegates that path without setting env itself.
        expected = '        OPENGEUL_SUITE_DIAGNOSTICS: ${{ github.workspace }}/.work/suite-worker-diagnostics\n'
        self.assertEqual(environment(production), expected)
        self.assertEqual(environment(witness), expected)
        self.assertLess(witness.index('      env:\n'), witness.index('      run: |\n'))

    def test_always_uploads_unfiltered_raw_diagnostic_readiness_and_logs(self):
        upload = named(self.source, 'Preserve raw native35 diagnostic evidence on success or failure')
        self.assertEqual(field(upload, 'if'), 'always()')
        self.assertIn('include-hidden-files: true', upload)
        self.assertIn('retention-days: 7', upload)
        for path in ('.work/suite-input-witness/', '.work/suite-input-witness-context/', '.work/suite-korean-readiness/',
                     '.work/suite-input-witness-preparation/',
                     '.work/suite-engine/', '.work/suite-worker-diagnostics/',
                     '.work/office-suite/msi.msi.log', '.work/office-suite/**/*.log',
                     '.work/source-engine-input/*.json', '.work/source-engine-input/*.log'):
            self.assertIn(path, upload)
        self.assertNotRegex(upload, re.compile(r'^\s+!', re.M), 'Raw evidence must not be filtered')
        self.assertNotRegex(self.source, r'Remove-Item|rmtree|unlink\(|del /|rm -')
        self.assertIn('generated native .cpp', self.source)
        self.assertIn('diagnosticOnly', self.source)


if __name__ == '__main__':
    unittest.main()
