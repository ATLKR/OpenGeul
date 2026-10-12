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
        self.assertEqual(job['runs-on'],'windows-11-arm');self.assertEqual(job['needs'],'build-arm64')
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
                    steps=json.dumps(bind(job['steps']),sort_keys=True,separators=(',',':')).encode()
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

if __name__ == '__main__':unittest.main()
