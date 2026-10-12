"""실패한 Store matrix가 외부 제출이나 성공 증거로 넘어가지 않게 검사한다."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from policy import audit, load_workflow
ROOT=Path(__file__).resolve().parents[2]


class StoreQualificationWorkflowTests(unittest.TestCase):
    def setUp(self): self.w=load_workflow(ROOT/'.github/workflows/store-package.yml'); self.jobs=self.w['jobs']

    def test_external_submission_waits_for_qualified_originals_only(self):
        self.assertEqual(set(self.jobs),{'package','store-wack','qualify','submit','verify-api'})
        self.assertEqual(self.jobs['submit']['needs'],['qualify'])
        self.assertIn('inputs.submit_to_store',self.jobs['submit']['if'])
        self.assertIn("needs.qualify.result == 'success'",self.jobs['submit']['if'])
        self.assertNotIn('store_submit.py',str(self.jobs['package']))

    def test_each_architecture_is_a_real_independent_native_store_gate(self):
        self.assertIn('store-wack',self.jobs)
        job=self.jobs['store-wack'];self.assertEqual(job['needs'],['package'])
        self.assertEqual(job['strategy']['matrix'],{'os':['windows-2025','windows-11-arm']})
        self.assertEqual(job['strategy']['fail-fast'],'false');self.assertEqual(job['strategy']['max-parallel'],'2')
        text=str(job);self.assertIn('-Architecture $env:ARCHITECTURE',text)
        self.assertIn('store_qualification.py select',text);self.assertIn('store_qualification.py collect',text)
        self.assertIn('github.run_id',text)

    def test_readonly_qualification_runs_also_when_submission_is_false(self):
        self.assertIn('qualify',self.jobs)
        job=self.jobs['qualify'];self.assertEqual(job['needs'],['package','store-wack'])
        self.assertNotIn('submit_to_store',job['if'])
        self.assertIn("needs['store-wack'].result == 'success'",job['if'])
        text=str(job);self.assertIn('--download-source-release',text);self.assertIn('store_qualification.py verify',text)
        self.assertNotIn('--publish-release',text);self.assertNotIn('--dispatch-store',text)
        self.assertIn('opengeul-store-qualified-',text)

    def test_store_secrets_and_issue_permission_are_narrowly_scoped(self):
        for name in ('package','store-wack','qualify'):
            self.assertNotIn('STORE_CLIENT_SECRET',str(self.jobs[name]))
            self.assertNotEqual(self.jobs[name].get('permissions',{}).get('issues'),'write')
        self.assertEqual(self.jobs['submit']['permissions']['issues'],'write')
        verify=self.jobs['verify-api'];self.assertIn('scripts/check_store_api.py',str(verify));self.assertNotIn('store_submit.py',str(verify))

    def test_raw_failure_evidence_cannot_suppress_the_actual_job_result(self):
        self.assertIn('store-wack',self.jobs)
        job=self.jobs['store-wack']
        for step in job['steps']:
            self.assertNotIn('continue-on-error',step)
        uploads=[s for s in job['steps'] if s.get('uses','').startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads),1);self.assertEqual(uploads[0]['if'],'always()')
        self.assertEqual(uploads[0]['with']['retention-days'],'1')

    def test_all_jobs_keep_the_public_standard_free_policy(self): audit(self.w)


if __name__=='__main__':unittest.main()
