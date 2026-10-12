"""The storage optimisation cannot weaken any existing release prerequisite."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from policy import audit,load_workflow,guarded
ROOT=Path(__file__).resolve().parents[2]
class WorkflowTransportTests(unittest.TestCase):
    def setUp(self):self.w=load_workflow(ROOT/'.github/workflows/msix.yml')
    def test_existing_release_gate_set_is_preserved_and_requires_arm64(self):
        self.assertEqual(set(self.w['jobs']['release']['needs']),{'wasm','build','build-arm64','native-e2e','browser-e2e','msix-install','msix-install-arm64','virtual-print'})
    def test_cleanup_depends_on_every_consumer_and_publication(self):
        self.assertIn('cleanup-transports',self.w['jobs'],'Missing post-consumer cleanup')
        self.assertEqual(set(self.w['jobs']['cleanup-transports']['needs']),{'preflight','wasm','windows-editor','windows-cli','windows-editor-arm64','windows-cli-arm64','build','build-arm64','native-e2e','browser-e2e','msix-install','msix-install-arm64','virtual-print','release'})
    def test_windows_components_build_in_parallel_and_full_mode_only(self):
        for name in ('windows-editor','windows-cli'):
            with self.subTest(name=name):
                self.assertIn(name,self.w['jobs'],'Missing independent Windows producer')
                job=self.w['jobs'][name]
                self.assertEqual(set(job['needs']),{'preflight','wasm'})
                self.assertEqual(job['runs-on'],'windows-2025')
                self.assertTrue(guarded(job['if']))
                self.assertIn("needs.preflight.outputs.mode == 'full'",job['if'])
                self.assertEqual(job['permissions'],{'contents':'read','actions':'read'})
                self.assertNotIn('continue-on-error',job)
    def test_package_aggregator_waits_for_both_windows_components_without_serializing_browser(self):
        self.assertEqual(set(self.w['jobs']['build']['needs']),{'preflight','wasm','windows-editor','windows-cli'})
        needs=self.w['jobs']['browser-e2e']['needs']
        self.assertEqual(set([needs] if isinstance(needs,str) else needs),{'wasm'})
    def test_component_transports_are_bounded_before_upload_and_expire_in_one_day(self):
        for job_name,prefix,cap in (('windows-editor','opengeul-editor-component',64),
                                  ('windows-cli','opengeul-cli-component',32),
                                  ('windows-editor-arm64','opengeul-editor-component-arm64',64),
                                  ('windows-cli-arm64','opengeul-cli-component-arm64',32)):
            with self.subTest(name=job_name):
                self.assertIn(job_name,self.w['jobs'])
                steps=self.w['jobs'][job_name]['steps']
                uploads=[(i,s) for i,s in enumerate(steps) if s.get('uses','').startswith('actions/upload-artifact@')
                         and s.get('with',{}).get('name')==prefix+'-${{ github.run_id }}']
                self.assertEqual(len(uploads),1)
                index,upload=uploads[0]
                self.assertEqual(str(upload['with']['retention-days']),'1')
                self.assertEqual(upload['with']['if-no-files-found'],'error')
                self.assertNotIn('if',upload)
                self.assertTrue(any(f'ci/evidence.py size --limit-mib {cap} ' in s.get('run','') for s in steps[:index]),
                                'Component cap must be checked before uploading its transport')
    def test_editor_produces_the_existing_bounded_native_fixture_transport(self):
        jobs=self.w['jobs'];self.assertIn('windows-editor',jobs)
        name='opengeul-e2e-inputs-${{ github.run_id }}'
        producers=[job_name for job_name,job in jobs.items() for step in job.get('steps',[])
                   if step.get('uses','').startswith('actions/upload-artifact@') and step.get('with',{}).get('name')==name]
        self.assertEqual(producers,['windows-editor'])
        steps=jobs['windows-editor']['steps'];index=next(i for i,s in enumerate(steps) if s.get('with',{}).get('name')==name)
        self.assertEqual(str(steps[index]['with']['retention-days']),'1')
        self.assertTrue(any('ci/evidence.py size --limit-mib 16 ' in s.get('run','') for s in steps[:index]))
    def test_cleanup_is_same_repo_nonfork_first_attempt_only(self):
        self.assertIn('cleanup-transports',self.w['jobs'])
        job=self.w['jobs']['cleanup-transports'];self.assertTrue(guarded(job['if']))
        for item in ("github.repository == 'ATLKR/OpenGeul'",'github.run_attempt == 1','github.event.pull_request.head.repo.full_name == github.repository',"github.actor != 'dependabot[bot]'",'!cancelled()'):
            self.assertIn(item,job['if'])
        self.assertEqual(job['permissions'],{'contents':'read','actions':'write'})
    def test_engine_does_not_upload_unused_wasm(self):
        step=next(s for s in self.w['jobs']['wasm']['steps'] if s.get('name')=='소스가 일치하는 재빌드 엔진 전달')
        self.assertIn("needs.preflight.outputs.mode == 'full'",step.get('if',''))
    def test_modes_and_full_windows_condition_unchanged(self):
        self.assertEqual(self.w['on']['workflow_dispatch']['inputs']['mode']['options'],['full','engine','checks'])
        self.assertIn("needs.preflight.outputs.mode == 'full'",self.w['jobs']['build']['if'])
    def test_entire_workflow_still_satisfies_free_runner_audit(self):audit(self.w)
    def test_all_browser_and_native_and_print_matrix_members_retained(self):
        jobs=self.w['jobs']
        self.assertEqual(jobs['browser-e2e']['strategy']['matrix']['browser'],['chromium','firefox','webkit'])
        for name in ('native-e2e','virtual-print'):
            self.assertEqual(set(jobs[name]['strategy']['matrix']['os']),{'windows-2022','windows-2025','windows-11-arm'})
if __name__=='__main__':unittest.main()
