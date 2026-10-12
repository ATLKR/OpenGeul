from pathlib import Path
import unittest,yaml
ROOT=Path(__file__).resolve().parents[2]
class WiringTests(unittest.TestCase):
    def load(self):
        data=yaml.safe_load((ROOT/'.github/workflows/msix.yml').read_text())
        if True in data:data['on']=data.pop(True)
        return data
    def test_windows_producers_run_alongside_browsers_and_package_joins_both(self):
        jobs=self.load()['jobs'];self.assertIn('preflight',jobs)
        self.assertEqual(set(jobs['build']['needs']),{'preflight','wasm','windows-editor','windows-cli'})
        for role in ('editor','cli'):
            job=jobs['windows-'+role]
            self.assertEqual(set(job['needs']),{'preflight','wasm'})
            self.assertEqual(job['runs-on'],'windows-2025')
            self.assertIn("needs.preflight.outputs.mode == 'full'",job['if'])
            self.assertEqual(job['permissions'],{'contents':'read','actions':'read'})
            commands='\n'.join(s.get('run','') for s in job['steps'])
            self.assertIn('-Phase '+role.capitalize(),commands)
            self.assertIn('opengeul-wasm-$env:GITHUB_RUN_ID',commands)
        self.assertEqual(jobs['browser-e2e']['needs'],'wasm')
        commands='\n'.join(s.get('run','') for s in jobs['build']['steps'])
        self.assertIn('-Phase Package',commands)
        for role in ('editor','cli'):
            self.assertIn('opengeul-'+role+'-component-$env:GITHUB_RUN_ID',commands)
        self.assertNotIn('cargo ',commands)
    def test_manual_engine_mode_never_reaches_release(self):
        w=self.load();options=w['on']['workflow_dispatch']['inputs']['mode']
        self.assertEqual(options['default'],'full');self.assertEqual(set(options['options']),{'full','engine','checks'})
        self.assertIn("needs.preflight.outputs.mode == 'full'",w['jobs']['build']['if'])
    def test_all_required_release_gates_remain(self):
        jobs=self.load()['jobs'];self.assertEqual(set(jobs['release']['needs']),{'wasm','build','build-arm64','native-e2e','native-e2e-arm64','browser-e2e','msix-install','msix-install-arm64','virtual-print','virtual-print-arm64'})
        for job in ('native-e2e','virtual-print'):
            self.assertEqual(set(jobs[job]['strategy']['matrix']['os']),{'windows-2022','windows-2025'})
            self.assertEqual(jobs[job+'-arm64']['runs-on'],'windows-11-arm')
        self.assertEqual(set(jobs['browser-e2e']['strategy']['matrix']['browser']),{'chromium','firefox','webkit'})
    def test_diagnostics_are_bounded_before_upload(self):
        for job in ('native-e2e','native-e2e-arm64','virtual-print','virtual-print-arm64','browser-e2e','msix-install','msix-install-arm64'):
            steps=self.load()['jobs'][job]['steps']
            pack=[i for i,s in enumerate(steps) if 'ci/evidence.py pack ' in s.get('run','')]
            self.assertEqual(len(pack),1)
            for i,s in enumerate(steps):
                if s.get('uses','').startswith('actions/upload-artifact'):
                    self.assertGreater(i,pack[0]);self.assertEqual(s['with']['path'],'bounded-evidence/')
    def test_native_input_artifact_no_longer_duplicates_browser_dist(self):
        steps=self.load()['jobs']['windows-editor']['steps']
        uploads=[s for s in steps if 'opengeul-e2e-inputs-' in s.get('with',{}).get('name','')]
        self.assertEqual(len(uploads),1);self.assertEqual(uploads[0]['with']['path'],'.work/native-inputs/')
    def test_all_transports_have_pre_upload_size_checks(self):
        for job in ('wasm','windows-editor','windows-cli','build','windows-editor-arm64','windows-cli-arm64','build-arm64'):
            steps=self.load()['jobs'][job]['steps']
            uploads=sum(s.get('uses','').startswith('actions/upload-artifact') for s in steps)
            checks=sum('ci/evidence.py size ' in s.get('run','') for s in steps)
            self.assertEqual(uploads,checks)
    def test_password_ui_is_a_required_same_source_native_gate(self):
        jobs=self.load()['jobs'];steps=jobs['native-e2e']['steps']
        password=[s for s in steps if 'password/native.py' in s.get('run','')]
        self.assertEqual(len(password),1,'Native password safety must gate each Windows matrix member')
        self.assertNotIn('if',password[0]);self.assertFalse(password[0].get('continue-on-error',False))
        run=password[0]['run']
        for binding in ('--expected-source $env:GITHUB_SHA','--expected-run $env:GITHUB_RUN_ID',
                        '--output evidence/password-native'):
            self.assertIn(binding,run)
        self.assertIn('native-e2e',jobs['release']['needs'])
        self.assertTrue(any('opengeul-wasm-$env:GITHUB_RUN_ID' in s.get('run','') for s in steps))
        checkout=next(i for i,s in enumerate(steps) if s.get('uses','').startswith('actions/checkout'))
        self.assertTrue(any('core.autocrlf false' in s.get('run','') for s in steps[:checkout]))
if __name__=='__main__':unittest.main()
