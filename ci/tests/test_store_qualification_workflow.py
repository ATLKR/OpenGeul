"""실패한 Store 작업가 외부 제출이나 성공 증거로 넘어가지 않게 검사한다."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from policy import audit, load_workflow
ROOT=Path(__file__).resolve().parents[2]


class StoreQualificationWorkflowTests(unittest.TestCase):
    def setUp(self): self.w=load_workflow(ROOT/'.github/workflows/store-package.yml'); self.jobs=self.w['jobs']

    def test_external_submission_waits_for_qualified_originals_only(self):
        self.assertEqual(set(self.jobs),{'package','store-native-arm64','store-wack-x64','store-wack','qualify','submit','verify-api'})
        self.assertEqual(self.jobs['submit']['needs'],['package','store-native-arm64','store-wack-x64','store-wack','qualify'])
        self.assertIn('inputs.submit_to_store',self.jobs['submit']['if'])
        self.assertIn("needs.qualify.result == 'success'",self.jobs['submit']['if'])
        self.assertNotIn('store_submit.py',str(self.jobs['package']))

    def test_each_architecture_requires_native_proof_and_independent_sdk_gate(self):
        for name,architecture,needs in (('store-wack-x64','x64',['package']),
                                         ('store-wack','arm64',['package','store-native-arm64'])):
            job=self.jobs[name];self.assertEqual(job['needs'],needs)
            self.assertNotIn('strategy',job);self.assertEqual(job['runs-on'],'windows-2025')
            self.assertEqual(job['name'],'Store WACK ('+architecture+')')
            self.assertEqual(job['env'],{'ARCHITECTURE':architecture})
            text=str(job);self.assertIn('store_qualification.py select',text)
            self.assertIn('store_qualification.py collect',text);self.assertIn('github.run_id',text)
        self.assertIn('-Architecture $env:ARCHITECTURE',str(self.jobs['store-wack-x64']))
        self.assertNotIn('msix-install.ps1',str(self.jobs['store-wack']))
        self.assertIn('-OriginalDirectory store-output',str(self.jobs['store-wack']))

    def test_source22_and_bound_arch_qa_are_validated_before_store_install(self):
        steps=self.jobs['store-wack-x64']['steps']
        downloads=[(i,s) for i,s in enumerate(steps) if '--download-source-release' in s.get('run','')]
        self.assertEqual(len(downloads),1)
        index,step=downloads[0];self.assertNotIn('if',step)
        self.assertEqual(step['env'],{'GH_TOKEN':'${{ github.token }}','RELEASE_TAG':'${{ inputs.release_tag }}'})
        run=step['run']
        source='scripts/store_package.py --download-source-release --release-tag $env:RELEASE_TAG --output .work/store-source'
        qa='scripts/mcp_qa_download.py store --store-directory store-output --source-directory .work/store-source --architecture $env:ARCHITECTURE --output mcp-qa'
        self.assertIn(source,run);self.assertIn(qa,run);self.assertLess(run.index(source),run.index(qa))
        self.assertIn('ci/evidence.py size --limit-mib 192 .work/store-source',run)
        self.assertIn('ci/evidence.py size --limit-mib 16 mcp-qa',run)
        self.assertIn('$PSNativeCommandUseErrorActionPreference = $true',run)
        install=next(i for i,s in enumerate(steps) if './e2e/msix-install.ps1 ' in s.get('run',''))
        self.assertLess(index,install)

    def test_store_install_receives_source_cli_hash_and_qa_without_binary_hash_fallback(self):
        step=next(s for s in self.jobs['store-wack-x64']['steps'] if './e2e/msix-install.ps1 ' in s.get('run',''))
        run=step['run'];self.assertNotIn('if',step)
        self.assertIn('Get-Content (Join-Path .work/store-source ("provenance-{0}.json" -f $env:ARCHITECTURE))',run)
        self.assertIn('$cliSha=[string]$provenance.windowsComponents.components.cli.sha256',run)
        self.assertIn('-Architecture $env:ARCHITECTURE -PackageDirectory package-wack -OutputDirectory installed -McpFixtureDirectory mcp-qa -ExpectedCliSha256 $cliSha',run)
        self.assertNotIn('Get-FileHash',run)
        self.assertLess(run.index('windowsComponents.components.cli.sha256'),run.index('./e2e/msix-install.ps1'))
        self.assertLess(run.index('./e2e/msix-install.ps1'),run.index('store_qualification.py collect'))
        self.assertNotIn('STORE_CLIENT_SECRET',str(step));self.assertNotIn('GH_TOKEN',step.get('env',{}))

    def test_readonly_qualification_runs_also_when_submission_is_false(self):
        self.assertIn('qualify',self.jobs)
        job=self.jobs['qualify'];self.assertEqual(job['needs'],['package','store-native-arm64','store-wack-x64','store-wack'])
        self.assertNotIn('submit_to_store',job['if'])
        self.assertIn("needs['store-wack'].result == 'success'",job['if'])
        text=str(job);self.assertIn('--download-source-release',text);self.assertIn('store_qualification.py verify',text)
        self.assertNotIn('--publish-release',text);self.assertNotIn('--dispatch-store',text)
        self.assertIn('opengeul-store-qualified-',text)

    def test_store_secrets_and_issue_permission_are_narrowly_scoped(self):
        for name in ('package','store-native-arm64','store-wack-x64','store-wack','qualify'):
            self.assertNotIn('STORE_CLIENT_SECRET',str(self.jobs[name]))
            self.assertNotEqual(self.jobs[name].get('permissions',{}).get('issues'),'write')
        self.assertEqual(self.jobs['submit']['permissions']['issues'],'write')
        verify=self.jobs['verify-api'];self.assertIn('scripts/check_store_api.py',str(verify));self.assertNotIn('store_submit.py',str(verify))

    def test_raw_failure_evidence_cannot_suppress_the_actual_job_result(self):
        for name in ('store-wack-x64','store-wack'):
            job=self.jobs[name]
            for step in job['steps']:self.assertNotIn('continue-on-error',step)
            uploads=[s for s in job['steps'] if s.get('uses','').startswith('actions/upload-artifact@')]
            self.assertEqual(len(uploads),1);self.assertEqual(uploads[0]['if'],'always()')
            self.assertEqual(uploads[0]['with']['retention-days'],'1')
            self.assertEqual(uploads[0]['with']['name'],'opengeul-store-wack-${{ env.ARCHITECTURE }}-${{ github.run_id }}')

    def test_all_jobs_keep_the_public_standard_free_policy(self): audit(self.w)


if __name__=='__main__':unittest.main()
