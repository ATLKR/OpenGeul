"""패키지 child에 현재 실행의 공개 CI 값 여섯 개만 전달하고 원래 검증은 유지한다."""
import ast
from pathlib import Path
import re
import types
import unittest

ROOT=Path(__file__).resolve().parents[2]
FIELDS={'CiActions':'GITHUB_ACTIONS','CiRunnerEnvironment':'RUNNER_ENVIRONMENT',
        'CiRepository':'GITHUB_REPOSITORY','CiCommit':'GITHUB_SHA',
        'CiRunId':'GITHUB_RUN_ID','CiRunAttempt':'GITHUB_RUN_ATTEMPT'}


class InstalledCiBindingTests(unittest.TestCase):
    def setUp(self):
        self.parent=(ROOT/'e2e/msix-install.ps1').read_text()
        self.child=(ROOT/'e2e/installed-cli.ps1').read_text()

    def test_child_public_parameters_are_mandatory_and_exactly_six_environment_keys_are_written(self):
        header=self.child[:self.child.index('Set-StrictMode')]
        for parameter,environment in FIELDS.items():
            self.assertRegex(header,r'\[Parameter\(Mandatory\)\]\[Validate(?:Set|Pattern)\([^\n]+\)\]\[string\]\$'+parameter)
            self.assertIn(environment+'=$'+parameter,self.child)
        self.assertEqual(set(re.findall(r'\b([A-Z_]+)=\$Ci\w+',self.child)),set(FIELDS.values()))
        self.assertNotIn('GetEnvironmentVariables',self.child+self.parent)
        self.assertNotIn('GH_TOKEN',self.child+self.parent)
        self.assertIn('[Environment]::GetEnvironmentVariable',self.child)
        self.assertIn('[Environment]::SetEnvironmentVariable',self.child)
        self.assertLess(self.child.index('환경이 현재 CI 실행과 다릅니다'),self.child.index('[Environment]::SetEnvironmentVariable'))
        self.assertLess(self.child.index('[Environment]::SetEnvironmentVariable'),self.child.index('Add-Type'))

    def test_outer_arguments_come_only_from_current_execution_and_precede_package_side_effects(self):
        for parameter,environment in FIELDS.items():
            self.assertIn(parameter+'=[string]$env:'+environment,self.parent)
            self.assertIn('-'+parameter+' $($publicCiContext.'+parameter+')',self.parent)
        validation=self.parent.index('현재 공개 CI 실행 정보가 올바르지 않습니다')
        self.assertLess(validation,self.parent.index('New-SelfSignedCertificate'))
        self.assertLess(validation,self.parent.index('Invoke-CommandInDesktopPackage'))
        self.assertNotIn('provenance.sourceCommit',self.parent)
        self.assertNotIn('provenance.sourceRun',self.parent)

    def test_unchanged_production_mcp_binding_rejects_null_and_accepts_only_exact_public_values(self):
        source=(ROOT/'e2e/mcp_worker.py').read_text();tree=ast.parse(source)
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('require','current_binding')]
        self.assertEqual(len(nodes),2)
        valid={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_REPOSITORY':'ATLKR/OpenGeul',
               'GITHUB_SHA':'1a969a13553b050398b8e1fd47df666b9684d646','GITHUB_RUN_ID':'38233190637','GITHUB_RUN_ATTEMPT':'1'}
        def invoke(values):
            scope={'os':types.SimpleNamespace(name='nt',getenv=values.get),'re':re}
            exec(compile(ast.Module(body=nodes,type_ignores=[]),'unchanged-production-mcp','exec'),scope)
            return scope['current_binding']()
        with self.assertRaises(ValueError):invoke({})
        self.assertEqual(invoke(valid),{'sourceCommit':valid['GITHUB_SHA'],'sourceRun':valid['GITHUB_RUN_ID'],'runAttempt':'1'})
        for name in valid:
            invalid=dict(valid);invalid[name]=''
            with self.subTest(name=name),self.assertRaises(ValueError):invoke(invalid)

    def test_original_native_mcp_validator_and_failure_timeout_remain_mandatory(self):
        text=self.child
        self.assertLess(text.index("'native_architecture.py'"),text.index("'mcp_worker.py'"))
        self.assertLess(text.index("'mcp_worker.py'"),text.index("'../scripts/mcp_qualification.py'"))
        self.assertLess(text.index("'../scripts/mcp_qualification.py'"),text.index('$result.success=$true'))
        self.assertIn('--expected-sha256 $ExpectedCliSha256 --context installed --package-full-name $PackageFullName',text)
        self.assertIn('--receipt $mcpPath --architecture $Architecture --cli-sha256 $ExpectedCliSha256 --package-full-name $PackageFullName',text)
        self.assertIn('if (-not $result.success) { exit 1 }',text)
        self.assertIn('$PSNativeCommandUseErrorActionPreference=$true',text)
        self.assertIn('Installed CLI package-context probe did not complete within 60 seconds.',self.parent)
        self.assertIn('-PreventBreakaway',self.parent)


if __name__=='__main__':unittest.main()
