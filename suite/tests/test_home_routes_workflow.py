"""Exercise Home workflow command failures and preserve the matrix's old gates."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
FOCUSED = ROOT / '.github/workflows/office-home-routes.yml'
MATRIX = ROOT / '.github/workflows/office-suite.yml'
BUILD_READY = "'!cancelled() && steps.build.outcome == ''success'''"
HOME_READY = "'!cancelled() && steps.office-features.outcome == ''success'' && steps.home-fixtures.outcome == ''success'''"
BASE_NAMES = (
    '정확한 소스 바이트 보존', '독립 PDF 검증 도구의 고정 해시 확인·설치',
    'Suite 단위 검사와 Windows shell 빌드 검사', '고정 버전의 패키지 경로 선택',
    '고정한 네이티브 ARM64 소스 빌드 입력 확보', '고정 입력으로 별도 Suite 개발 패키지 빌드',
    '실제 한국어 IME와 네이티브 UI 검사 준비', '한국어 입력 환경의 준비·실패 기록 즉시 보존',
    '실제 Office 엔진의 생성·편집·저장·재열기', 'Enter 없이 실제 Calc Ctrl+S·저장·독립 재열기',
    'Calc Ctrl+S 성공·실패 뒤 패키지 불변 확인', 'Calc Ctrl+S 입력·저장·로컬 네이티브 진단 즉시 보존',
    'Enter 없이 실제 Calc Ctrl+W 저장·버림·취소 관측', 'Calc Ctrl+W 성공·실패 뒤 패키지 불변 확인',
    'Calc Ctrl+W 세 선택과 로컬 네이티브 진단 즉시 보존', '문서 형식 15개와 모듈 심화 기능 6개 의미 검증',
    '다섯 모듈 PDF의 실제 페이지·한국어 텍스트 검증', '형식·심화 기능·PDF 원본 검증 기록 즉시 보존',
    '실제 한국어 조합·백스페이스·저장·재열기', 'IME 입력·엔진 크래시 원본 기록 즉시 보존',
    '한국어 탭 메뉴의 실제 접근성·화면 확인', 'korean-ui 원본 검증 기록 즉시 보존',
    '실제 Writer 제목 1 단축키·저장·독립 재열기', 'Writer 스타일 원본 검증 기록 즉시 보존',
    '저장·취소·실패·창 복원·HWP 실행 수명 검사', 'lifecycle 원본 검증 기록 즉시 보존',
    '독립 문서 초기화와 종료 40회 모두 통과', 'startup 원본 검증 기록 즉시 보존',
    '첫 번째 전체 Suite GUI·편집 후 의미 검증', '새 문서 집합으로 전체 UI·E2E를 두 번째 독립 실행',
    '모든 네이티브 진단 보존·해시와 크래시 부재 확인', '원본 GUI·엔진·IME·반복 검증 기록 보존',
    '모든 검증을 통과한 Suite 개발 패키지 전달',
)


def steps(path):
    return re.split(r'^    - name: ', path.read_text(encoding='utf-8'), flags=re.M)[1:]


def field(step, name):
    match = re.search(r'^      ' + re.escape(name) + r': (.+)$', step, re.M)
    return match.group(1) if match else None


def step_by_id(path, name):
    return next(step for step in steps(path) if field(step, 'id') == name)


def run_code(step):
    match = re.search(r'^      run: \|\n((?:        .*\n|\n)+)', step, re.M)
    if not match:
        raise AssertionError('Workflow step needs a literal run block')
    return textwrap.dedent(match.group(1))


class HomeWorkflowChecks:
    def check_focused(self):
        source = FOCUSED.read_text(encoding='utf-8')
        self.assertIn('branches: [work/opengeul-office-home-routes]', source)
        self.assertIn('runs-on: windows-2025', source)
        self.assertIn('architecture: x64', source)
        self.assertIn('persist-credentials: false', source)
        self.assertIn('pywinauto==0.6.9 Pillow==12.3.0', source)
        self.assertIn('./suite/scripts/build-suite.ps1 -Architecture x64', run_code(step_by_id(FOCUSED, 'build')))
        self.assertNotIn('fetch-source-engine.ps1', source)
        self.assertNotIn('cargo ', source)
        tests = next(step for step in steps(FOCUSED) if 'python -m unittest' in step)
        for module in ('test_home_routing_smoke', 'test_home_calc_close', 'test_home_fixture_inputs',
                       'test_home_routes_workflow', 'test_native_cleanup_receipt'):
            self.assertIn('suite.tests.' + module, tests)
        self.assertIn('test_home_routes_workflow.HomeRoutesFocusedWorkflowTests', tests)
        self.check_inputs_and_route(FOCUSED)

    def check_inputs_and_route(self, path):
        feature = step_by_id(path, 'office-features')
        self.assertEqual(field(feature, 'if'), BUILD_READY)
        code = run_code(feature)
        self.assertIn('& "$package/Office/program/python.exe" suite/e2e/office_feature_smoke.py --suite $package --output .work/suite-office-features', code)
        self.assertNotIn('--case', code, 'Home needs all fifteen fresh format fixtures from the canonical twenty-one cases')
        fixture = step_by_id(path, 'home-fixtures')
        self.assertEqual(field(fixture, 'if'), BUILD_READY)
        self.assertIn('python suite/e2e/home_fixture_inputs.py --suite $package --output .work/e2e-fixtures', run_code(fixture))
        self.assertIn('if ($LASTEXITCODE -ne 0)', run_code(fixture))
        home = step_by_id(path, 'home-routes')
        self.assertEqual(field(home, 'if'), HOME_READY)
        code = run_code(home)
        self.assertIn('python suite/e2e/home_routing_smoke.py --suite $package --features .work/suite-office-features --hwp-fixtures .work/e2e-fixtures --output .work/suite-home-routing', code)
        self.assertNotIn('OPENGEUL_SUITE_DIAGNOSTICS:', home, 'Harness owns separate product diagnostics per case')
        self.assertIn('python suite/scripts/verify-suite.py $package', code)
        records = steps(path)
        self.assertLess(records.index(feature), records.index(fixture))
        self.assertLess(records.index(fixture), records.index(home))

    def check_matrix(self):
        self.check_inputs_and_route(MATRIX)
        source = MATRIX.read_text(encoding='utf-8')
        self.assertIn('- architecture: x64\n          runner: windows-2025', source)
        self.assertIn('- architecture: arm64\n          runner: windows-11-arm', source)
        original = [step.splitlines()[0] for step in steps(MATRIX)
                    if step.splitlines()[0] in BASE_NAMES]
        self.assertEqual(tuple(original), BASE_NAMES)
        records = steps(MATRIX)
        pdf = next(step for step in records if 'pdf_export_smoke.py --produce' in step)
        self.assertLess(records.index(step_by_id(MATRIX, 'home-routes')), records.index(pdf))
        delivery = records[-1]
        self.assertEqual(field(delivery, 'if'), "success() && steps.home-routes.outcome == 'success'")

    def check_evidence(self, path):
        evidence = next(step for step in steps(path) if field(step, 'if') == 'always()')
        for folder in ('.work/suite-office-features/', '.work/e2e-fixtures/', '.work/suite-home-routing/'):
            self.assertIn(folder, evidence)
        self.assertIn('include-hidden-files: true', evidence)
        self.assertIn('actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02', evidence)
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', evidence)

    def check_boundary(self, path):
        code = run_code(step_by_id(path, 'home-routes'))
        for home_exit, integrity_exit in ((0, 0), (7, 0), (0, 9), (7, 9)):
            with self.subTest(workflow=path.name, home=home_exit, integrity=integrity_exit), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                package = folder / 'dist/owned-package'
                package.mkdir(parents=True)
                stub = folder / 'tool.py'
                stub.write_text("import json, os, sys\nfrom pathlib import Path\nwith Path(os.environ['HOME_TEST_LOG']).open('a') as log: log.write(json.dumps(sys.argv[1:])+'\\n')\nraise SystemExit(int(os.environ['HOME_TEST_EXIT'] if sys.argv[1].endswith('home_routing_smoke.py') else os.environ['INTEGRITY_TEST_EXIT']))\n", encoding='utf-8')
                script = folder / 'step.ps1'
                script.write_text("$ErrorActionPreference = 'Stop'\nfunction python { & $env:HOME_TEST_PYTHON $env:HOME_TEST_STUB @args }\n" + code, encoding='utf-8')
                environment = dict(os.environ, SUITE_PACKAGE='dist/owned-package',
                                   HOME_TEST_PYTHON=sys.executable, HOME_TEST_STUB=str(stub),
                                   HOME_TEST_LOG=str(folder / 'calls.jsonl'), HOME_TEST_EXIT=str(home_exit),
                                   INTEGRITY_TEST_EXIT=str(integrity_exit))
                process = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)],
                                         cwd=folder, env=environment, capture_output=True, text=True, timeout=15)
                self.assertEqual(process.returncode == 0, home_exit == integrity_exit == 0, process.stdout + process.stderr)
                calls = [json.loads(line) for line in (folder / 'calls.jsonl').read_text().splitlines()]
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0], ['suite/e2e/home_routing_smoke.py', '--suite', str(package.resolve()),
                                         '--features', '.work/suite-office-features', '--hwp-fixtures', '.work/e2e-fixtures',
                                         '--output', '.work/suite-home-routing'])
                self.assertEqual(calls[1], ['suite/scripts/verify-suite.py', str(package.resolve())])


class HomeRoutesFocusedWorkflowTests(HomeWorkflowChecks, unittest.TestCase):
    def test_fresh_qualified_x64_inputs_and_ownership_regressions(self):
        self.check_focused()

    def test_raw_evidence_survives_failure(self):
        self.check_evidence(FOCUSED)

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required for the real command boundary')
    def test_actual_step_rejects_both_failures_and_always_verifies_package(self):
        self.check_boundary(FOCUSED)


class HomeRoutesMatrixWorkflowTests(HomeWorkflowChecks, unittest.TestCase):
    def test_both_architectures_keep_prior_gates_and_require_home_for_delivery(self):
        self.check_matrix()

    def test_raw_evidence_survives_failure(self):
        self.check_evidence(MATRIX)

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required for the real command boundary')
    def test_actual_step_rejects_both_failures_and_always_verifies_package(self):
        self.check_boundary(MATRIX)


if __name__ == '__main__':
    unittest.main()
