"""ARM native 검사와 기존 x64 검사를 같은 릴리스 필수 조건으로 연결한다."""
from pathlib import Path
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
            expanded.extend([f'{name} ({value})' for values in matrix.values() for value in values] if matrix else [name])
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
            self.assertEqual(set(job['needs']), {'build','build-arm64'})
            self.assertEqual(set(job['strategy']['matrix']['os']), {'windows-2022','windows-2025','windows-11-arm'})
            self.assertIn('E2E_ARCHITECTURE', job['env'])
            self.assertIn('--architecture $env:E2E_ARCHITECTURE', self.commands(name))
            self.assertIn('opengeul-windows-${env:E2E_ARCHITECTURE}-', self.commands(name))
        job=self.jobs['msix-install-arm64']
        self.assertEqual(job['runs-on'],'windows-11-arm');self.assertEqual(job['needs'],'build-arm64')
        self.assertIn('-Architecture arm64', self.commands('msix-install-arm64'))
    def test_release_requires_both_architectures_and_full_wack_receipts(self):
        self.assertEqual(set(self.jobs['release']['needs']), {'wasm','build','build-arm64','native-e2e','browser-e2e','msix-install','msix-install-arm64','virtual-print'})
        commands=self.commands('release')
        for required in ('--name "opengeul-windows-arm64-$BUILD_RUN_ID" --dir package-arm64',
                         '--name "msix-install-$BUILD_RUN_ID" --dir wack-x64',
                         '--name "msix-install-arm64-$BUILD_RUN_ID" --dir wack-arm64',
                         'scripts/release_pair.py assemble --x64 package --arm64 package-arm64 --wack-x64 wack-x64 --wack-arm64 wack-arm64 --output release-output',
                         '--package-directory release-output'):
            self.assertIn(required,commands)
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
