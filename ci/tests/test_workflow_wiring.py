from pathlib import Path
import unittest,yaml
ROOT=Path(__file__).resolve().parents[2]
class WiringTests(unittest.TestCase):
    def load(self):
        data=yaml.safe_load((ROOT/'.github/workflows/msix.yml').read_text())
        if True in data:data['on']=data.pop(True)
        return data
    def test_heavy_build_waits_for_preflight_and_browser_gate(self):
        jobs=self.load()['jobs'];self.assertIn('preflight',jobs)
        self.assertEqual(set(jobs['build']['needs']),{'preflight','wasm','browser-e2e'})
    def test_manual_engine_mode_never_reaches_release(self):
        w=self.load();options=w['on']['workflow_dispatch']['inputs']['mode']
        self.assertEqual(options['default'],'full');self.assertEqual(set(options['options']),{'full','engine','checks'})
        self.assertIn("needs.preflight.outputs.mode == 'full'",w['jobs']['build']['if'])
    def test_all_required_release_gates_remain(self):
        jobs=self.load()['jobs'];self.assertEqual(set(jobs['release']['needs']),{'wasm','build','native-e2e','browser-e2e','msix-install','virtual-print'})
        for job in ('native-e2e','virtual-print'):
            self.assertEqual(set(jobs[job]['strategy']['matrix']['os']),{'windows-2022','windows-2025'})
        self.assertEqual(set(jobs['browser-e2e']['strategy']['matrix']['browser']),{'chromium','firefox','webkit'})
    def test_diagnostics_are_bounded_before_upload(self):
        for job in ('native-e2e','virtual-print','browser-e2e','msix-install'):
            steps=self.load()['jobs'][job]['steps']
            pack=[i for i,s in enumerate(steps) if 'ci/evidence.py pack ' in s.get('run','')]
            self.assertEqual(len(pack),1)
            for i,s in enumerate(steps):
                if s.get('uses','').startswith('actions/upload-artifact'):
                    self.assertGreater(i,pack[0]);self.assertEqual(s['with']['path'],'bounded-evidence/')
    def test_native_input_artifact_no_longer_duplicates_browser_dist(self):
        steps=self.load()['jobs']['build']['steps']
        uploads=[s for s in steps if 'opengeul-e2e-inputs-' in s.get('with',{}).get('name','')]
        self.assertEqual(len(uploads),1);self.assertEqual(uploads[0]['with']['path'],'.work/native-inputs/')
    def test_all_transports_have_pre_upload_size_checks(self):
        for job in ('wasm','build'):
            steps=self.load()['jobs'][job]['steps']
            uploads=sum(s.get('uses','').startswith('actions/upload-artifact') for s in steps)
            checks=sum('ci/evidence.py size ' in s.get('run','') for s in steps)
            self.assertEqual(uploads,checks)
if __name__=='__main__':unittest.main()
