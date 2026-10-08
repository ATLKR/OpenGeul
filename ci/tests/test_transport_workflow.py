"""The storage optimisation cannot weaken any existing release prerequisite."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from policy import audit,load_workflow,guarded
ROOT=Path(__file__).resolve().parents[2]
class WorkflowTransportTests(unittest.TestCase):
    def setUp(self):self.w=load_workflow(ROOT/'.github/workflows/msix.yml')
    def test_existing_release_gate_set_is_unchanged(self):
        self.assertEqual(set(self.w['jobs']['release']['needs']),{'wasm','build','native-e2e','browser-e2e','msix-install','virtual-print'})
    def test_cleanup_depends_on_every_consumer_and_publication(self):
        self.assertIn('cleanup-transports',self.w['jobs'],'Missing post-consumer cleanup')
        self.assertEqual(set(self.w['jobs']['cleanup-transports']['needs']),{'preflight','wasm','build','native-e2e','browser-e2e','msix-install','virtual-print','release'})
    def test_cleanup_is_same_repo_nonfork_first_attempt_only(self):
        self.assertIn('cleanup-transports',self.w['jobs'])
        job=self.w['jobs']['cleanup-transports'];self.assertTrue(guarded(job['if']))
        for item in ("github.repository == 'ATLKR/OpenGeul'",'github.run_attempt == 1','github.event.pull_request.head.repo.full_name == github.repository',"github.actor != 'dependabot[bot]'",'!cancelled()'):
            self.assertIn(item,job['if'])
        self.assertEqual(job['permissions'],{'contents':'read','actions':'write'})
    def test_engine_does_not_upload_unused_wasm(self):
        step=next(s for s in self.w['jobs']['wasm']['steps'] if s.get('name')=='Share source-bound rebuilt engine')
        self.assertIn("needs.preflight.outputs.mode == 'full'",step.get('if',''))
    def test_modes_and_full_windows_condition_unchanged(self):
        self.assertEqual(self.w['on']['workflow_dispatch']['inputs']['mode']['options'],['full','engine','checks'])
        self.assertIn("needs.preflight.outputs.mode == 'full'",self.w['jobs']['build']['if'])
    def test_entire_workflow_still_satisfies_free_runner_audit(self):audit(self.w)
    def test_all_browser_and_native_and_print_matrix_members_retained(self):
        jobs=self.w['jobs']
        self.assertEqual(jobs['browser-e2e']['strategy']['matrix']['browser'],['chromium','firefox','webkit'])
        for name in ('native-e2e','virtual-print'):
            self.assertEqual(set(jobs[name]['strategy']['matrix']['os']),{'windows-2022','windows-2025'})
if __name__=='__main__':unittest.main()
