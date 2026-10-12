"""ARM native 검사와 기존 x64 검사를 같은 릴리스 필수 조건으로 연결한다."""
from pathlib import Path
import hashlib
import json
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy import audit, load_workflow
ROOT = Path(__file__).resolve().parents[2]

class Arm64WorkflowTests(unittest.TestCase):
    def setUp(self):self.jobs = load_workflow(ROOT/'.github/workflows/msix.yml')['jobs']
    def commands(self, name):return '\n'.join(step.get('run', '') for step in self.jobs[name]['steps'])
    def test_exact21_expanded_jobs_preserve_all15_x64_checks(self):
        expanded = []
        for name, job in self.jobs.items():
            matrix = job.get('strategy', {}).get('matrix')
            expanded.extend([f'{name} ({value})' for values in matrix.values() for value in values] if matrix else [job.get('name', name)])
        old = {'preflight','wasm','windows-editor','windows-cli','build','msix-install','release','cleanup-transports',
               'browser-e2e (chromium)','browser-e2e (firefox)','browser-e2e (webkit)',
               'native-e2e (windows-2022)','native-e2e (windows-2025)',
               'virtual-print (windows-2022)','virtual-print (windows-2025)'}
        new = {'windows-editor-arm64','windows-cli-arm64','build-arm64','msix-install-arm64',
               'native-e2e (windows-11-arm)','virtual-print (windows-11-arm)'}
        self.assertEqual(set(expanded), old | new);self.assertEqual(len(expanded), 21)
    def test_native_arm_producers_share_wasm_and_never_wait_on_browser(self):
        for role in ('editor','cli'):
            name = 'windows-'+role+'-arm64';self.assertIn(name, self.jobs)
            job = self.jobs[name]
            self.assertEqual(set(job['needs']), {'preflight','wasm'})
            self.assertEqual(job['runs-on'], 'windows-11-arm')
            self.assertEqual(job['permissions'], {'contents':'read','actions':'read'})
            self.assertIn('-Architecture arm64', self.commands(name))
            self.assertIn('opengeul-wasm-$env:GITHUB_RUN_ID', self.commands(name))
        self.assertEqual(set(self.jobs['build-arm64']['needs']), {'preflight','wasm','windows-editor-arm64','windows-cli-arm64'})
        self.assertIn('-Phase Package -Architecture arm64', self.commands('build-arm64'))
    def test_all_native_print_and_install_consumers_use_actual_architecture(self):
        for name in ('native-e2e','virtual-print'):
            job=self.jobs[name]
            self.assertEqual(job['needs'], 'build')
            self.assertEqual(set(job['strategy']['matrix']['os']), {'windows-2022','windows-2025'})
            self.assertEqual(job['env'], {'E2E_ARCHITECTURE':'x64','E2E_INPUT_SUFFIX':''})
            arm=self.jobs[name+'-arm64']
            self.assertEqual(arm['name'], name+' (windows-11-arm)')
            self.assertEqual(arm['needs'], 'build-arm64')
            self.assertEqual(arm['runs-on'], 'windows-11-arm')
            self.assertNotIn('strategy',arm)
            self.assertEqual(arm['env'], {'E2E_ARCHITECTURE':'arm64','E2E_INPUT_SUFFIX':'-arm64'})
            for consumer in (name,name+'-arm64'):
                self.assertIn('--architecture $env:E2E_ARCHITECTURE', self.commands(consumer))
                self.assertIn('opengeul-windows-${env:E2E_ARCHITECTURE}-', self.commands(consumer))
        job=self.jobs['msix-install-arm64']
        self.assertEqual(job['runs-on'],'windows-11-arm');self.assertEqual(set(job['needs']),{'build-arm64','native-e2e-arm64'})
        self.assertIn('-Architecture arm64', self.commands('msix-install-arm64'))
    def test_release_requires_both_architectures_and_full_wack_receipts(self):
        self.assertEqual(set(self.jobs['release']['needs']), {'wasm','build','build-arm64','native-e2e','native-e2e-arm64','browser-e2e','msix-install','msix-install-arm64','virtual-print','virtual-print-arm64'})
        commands=self.commands('release')
        for required in ('--name "opengeul-windows-arm64-$BUILD_RUN_ID" --dir package-arm64',
                         '--name "msix-install-$BUILD_RUN_ID" --dir wack-x64',
                         '--name "msix-install-arm64-$BUILD_RUN_ID" --dir wack-arm64',
                         'scripts/release_pair.py assemble --x64 package --arm64 package-arm64 --wack-x64 wack-x64 --wack-arm64 wack-arm64 --output release-output',
                         '--package-directory release-output'):
            self.assertIn(required,commands)
    def test_original_native_and_print_steps_cases_and_artifacts_remain_exact(self):
        # c689fa5 원본 전체 단계. matrix OS만 실제 ARM 표시명으로 정규화한다.
        original={'native-e2e':'bf842e5d0cc3a3b4e537fabd0a3b2648769d9429bbe62883bcd0f89999b4dcb9',
                  'virtual-print':'dc5a7018b29922bb810bcd94a70d0ea154a35a1b13665e73191c25f8053ea5df'}
        def bind(value):
            if isinstance(value,dict):return {k:bind(v) for k,v in value.items()}
            if isinstance(value,list):return [bind(v) for v in value]
            if isinstance(value,str):return value.replace('${{ matrix.os }}','windows-11-arm')
            return value
        for name,expected in original.items():
            for suffix in ('','-arm64'):
                with self.subTest(job=name+suffix):
                    job=self.jobs[name+suffix]
                    # 새 MCP/QA 계약은 test_workflow_wiring이 별도로 검사한다.
                    # 기존 16+암호8·인쇄 전체 단계의 원래 해시는 갱신하지 않는다.
                    additions={'실제 MCP stdio·암호 입력·COM 작업자 실패 격리 검사',
                               '설치 MCP 시험에 사용할 동일 실행의 공개 QA 원본 준비',
                               '동일 실행의 공개 MCP QA 입력을 하루 동안 보존'} if name=='native-e2e' else set()
                    steps=json.dumps(bind([step for step in job['steps'] if step.get('name') not in additions]),sort_keys=True,separators=(',',':')).encode()
                    self.assertEqual(hashlib.sha256(steps).hexdigest(),expected)
                    self.assertEqual(job['permissions'],{'contents':'read','actions':'read'})
                    self.assertEqual(str(job['timeout-minutes']),'40' if name=='native-e2e' else '30')
                    self.assertNotIn('continue-on-error',job)
    def test_build_commands_are_native_target_explicit_without_changing_feature_graph(self):
        text=(ROOT/'scripts/build-msix.ps1').read_text()
        self.assertIn('$env:RUSTUP_TOOLCHAIN = "$($lock.rust)-$target"',text)
        for line in text.splitlines():
            if line.strip().startswith(('cargo test ', 'cargo run ', 'cargo build ', 'rustc ')):
                self.assertIn('--target $target',line)
        self.assertIn('pnpm tauri build --no-bundle --target $target',text)
        self.assertIn('cargo build --release --locked --target $target --package rhwp --bin rhwp --features native-skia',text)
        self.assertIn('native_architecture.py cli',text)
        self.assertIn('cargo test --locked --target $target --package opengeul-native-open',text)
    def test_standard_free_arm_label_is_allowed_but_unknown_labels_fail(self):
        workflow=load_workflow(ROOT/'.github/workflows/msix.yml')
        workflow['jobs']['windows-editor']['runs-on']='windows-11-arm';audit(workflow)
        workflow['jobs']['windows-editor']['runs-on']='windows-11-arm-64core'
        with self.assertRaises(ValueError):audit(workflow)

class InstalledMcpWiringTests(unittest.TestCase):
    def script(self,name):return (ROOT/'e2e'/name).read_text()
    def test_fixture_and_attested_hash_are_mandatory_in_both_install_layers(self):
        for name in ('installed-cli.ps1','msix-install.ps1'):
            text=self.script(name)
            for argument in ('McpFixtureDirectory','ExpectedCliSha256'):
                self.assertRegex(text,r"\[Parameter\(Mandatory\)\](?:\[ValidatePattern\('[^']+'\)\])?\[string\]\$"+argument)
        install=self.script('msix-install.ps1')
        self.assertIn('-McpFixtureDirectory',install);self.assertIn('-ExpectedCliSha256 $ExpectedCliSha256',install)
        self.assertNotIn('(Get-FileHash $cli',install)
    def test_actual_mcp_then_common_validator_precede_read_and_success(self):
        cli=self.script('installed-cli.ps1')
        call=cli.index("'mcp_worker.py'");validate=cli.index("'../scripts/mcp_qualification.py'")
        read=cli.index('$result.mcp=');success=cli.index('$result.success=$true')
        self.assertLess(call,validate);self.assertLess(validate,read);self.assertLess(read,success)
        for binding in ('--exe $CliPath','--architecture $Architecture','--expected-sha256 $ExpectedCliSha256',
                        '--context installed','--package-full-name $PackageFullName','--out $mcpDirectory',
                        '--fixtures (Join-Path $McpFixtureDirectory \'e2e-fixtures\')',
                        '--password-fixtures (Join-Path $McpFixtureDirectory \'password-fixtures\')',
                        '--receipt $mcpPath','--cli-sha256 $ExpectedCliSha256'):
            self.assertIn(binding,cli)
        self.assertIn("$PSNativeCommandUseErrorActionPreference=$true",cli)
        self.assertNotIn('Get-FileHash',cli)
    def test_complete_original_mcp_proof_is_embedded_in_both_retained_receipts(self):
        cli=self.script('installed-cli.ps1');install=self.script('msix-install.ps1')
        self.assertIn('$result.mcp=Get-Content $mcpPath -Raw | ConvertFrom-Json',cli)
        self.assertIn('mcp=$cliEvidence.mcp',install)
        self.assertRegex(cli,r'\$result \| ConvertTo-Json -Depth 20')
        record=install[install.index("scope='test-only signing")-250:install.index("scope='test-only signing")+600]
        self.assertIn('mcp=$cliEvidence.mcp',record);self.assertIn('ConvertTo-Json -Depth 20',record)
    def test_install_timeout_and_original_unsigned_package_guard_remain(self):
        install=self.script('msix-install.ps1')
        self.assertIn('Installed CLI package-context probe did not complete within 60 seconds.',install)
        self.assertIn("if ((Get-FileHash $original[0].FullName -Algorithm SHA256).Hash -ne $before)",install)
        self.assertIn('Remove-AppxPackage -Package $installed.PackageFullName',install)
        self.assertIn('Move-Item $temporary',self.script('installed-cli.ps1'))

if __name__ == '__main__':unittest.main()
