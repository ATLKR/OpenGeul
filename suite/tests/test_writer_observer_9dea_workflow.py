"""Exact ARM9 producer dispatch and artifact isolation, without running a build."""
import re
import json
import unittest
import yaml
from suite.tests.test_writer_observer_producer import ROOT, ProducerPowerShellHarness, quote

PATH=ROOT/'.github/workflows/office-native-engine.yml'
REF='refs/heads/work/opengeul-office-native-writer-observer-9dea'
WRITER='OPENGEUL_WRITER_SERVER_OBSERVER_BUILD'
CALC='OPENGEUL_CALC_DISPATCH_BUILD'


def selected(condition, values, *, success=True):
    # Evaluate only this finite status/env grammar, never arbitrary workflow code.
    if condition is None:return success
    body=condition.removeprefix('${{').removesuffix('}}').strip()
    if body=='always()':return True
    atoms=body.split(' && ')
    result=True
    for atom in atoms:
        match=re.fullmatch(r"env\.([A-Z_]+) (==|!=) '(true|false)'",atom)
        if match is None:raise ValueError('Unsupported artifact condition')
        key,operator,expected=match.groups()
        result=result and ((values.get(key)==expected) if operator=='==' else (values.get(key)!=expected))
    return success and result


class WorkflowContract(unittest.TestCase):
    def setUp(self):
        self.value=yaml.safe_load(PATH.read_text())
        self.job=self.value['jobs']['native-firebird-and-office']

    def test_exact_branch_single_job_runner_and_closed_permissions(self):
        self.assertEqual(['native-firebird-and-office'],list(self.value['jobs']))
        self.assertIn(REF.removeprefix('refs/heads/'),self.value['on']['push']['branches'])
        self.assertEqual({'contents':'read'},self.value['permissions'])
        self.assertEqual('windows-11-arm',self.job['runs-on'])
        self.assertEqual(360,self.job['timeout-minutes'])
        self.assertNotIn('strategy',self.job);self.assertNotIn('continue-on-error',self.job)
        self.assertEqual("${{ github.ref == '"+REF+"' && 'true' || 'false' }}",self.job['env'][WRITER])
        self.assertEqual('false',self.job['env'][CALC])
        self.assertIn('AddMinutes(330)',self.job['steps'][0]['run'])
        for step in self.job['steps']:
            self.assertNotIn('continue-on-error',step)
            if 'uses' in step:self.assertRegex(step['uses'],r'@[0-9a-f]{40}$')

    def test_only_evidence_and_writer_family_upload_on_success_and_evidence_on_failure(self):
        uploads=[s for s in self.job['steps'] if s.get('uses','').startswith('actions/upload-artifact@')]
        def names(writer,calc,success=True):
            values={WRITER:writer,CALC:calc}
            return [s['with']['name'] for s in uploads if selected(s.get('if'),values,success=success)]
        evidence='opengeul-native-arm64-engine-evidence-${{ github.run_id }}-${{ github.run_attempt }}'
        writer='opengeul-native-arm64-writer-server-observer-${{ github.run_id }}-${{ github.run_attempt }}'
        self.assertEqual([evidence,writer],names('true','false'))
        self.assertEqual([evidence],names('true','false',False)) # failure/cancelled default success gate
        self.assertEqual([evidence],names('true','true')) # mixed flags fail closed at upload too
        for unknown in ('','TRUE','unknown'):
            self.assertEqual([evidence],names(unknown,'false'))
        self.assertEqual([evidence,'opengeul-native-arm64-engine-${{ github.run_id }}-${{ github.run_attempt }}',
                          'opengeul-native-arm64-plugin-symbols-${{ github.run_id }}-${{ github.run_attempt }}'],names('false','false'))
        isolated=next(s for s in uploads if s['with']['name']==writer)
        self.assertEqual(['.work/native-engine-evidence/OpenGeul-Office-engine-arm64-writer-server-observer.zip',
                          '.work/native-engine-evidence/writer-server-observer-source-build-receipt.json'],isolated['with']['path'].splitlines())
        evidence_step=next(s for s in uploads if s['with']['name']==evidence)
        self.assertIn('!.work/native-engine-evidence/*.zip',evidence_step['with']['path'].splitlines())
        self.assertIn('!.work/native-engine-evidence/plugin-symbols/**',evidence_step['with']['path'].splitlines())
        self.assertEqual(len(uploads),5)
        self.assertTrue(all(s['with']['if-no-files-found']=='error' for s in uploads))


class WorkflowDispatch(ProducerPowerShellHarness):
    def test_real_workflow_selects_writer_without_symbols_or_calc_and_rejects_unknown(self):
        value=yaml.safe_load(PATH.read_text());steps=value['jobs']['native-firebird-and-office']['steps']
        step=next(s for s in steps if s.get('name')=='Build and verify native Firebird before the full Office engine')
        body=step['run'].replace('./suite/scripts/build-native-engine.ps1','Get-WorkflowSelectedMode')
        wrapper="function Get-WorkflowSelectedMode {param($Phase,$WorkDirectory,$OutputDirectory,$SourceLockPath,$DeadlineUtc,[switch]$MutexSymbols,[switch]$CalcDispatchDiagnostic,[switch]$WriterServerObserverDiagnostic);if($WriterServerObserverDiagnostic -and $MutexSymbols){throw 'Mixed symbols'};Get-NativeEngineBuildMode $Phase -CalcDispatchDiagnostic:$CalcDispatchDiagnostic -WriterServerObserverDiagnostic:$WriterServerObserverDiagnostic|ConvertTo-Json -Compress}\n"
        for writer,calc,kind in [('true','false','native-office-engine-writer-server-observer-diagnostic'),
                                 ('false','false','native-office-engine-source-build'),
                                 ('false','true','native-office-engine-calc-dispatch-diagnostic')]:
            result=json.loads(self.ps('$env:'+WRITER+'='+quote(writer)+';$env:'+CALC+'='+quote(calc)+';\n'+wrapper+body).splitlines()[-1])
            self.assertEqual(kind,result['kind']);self.assertEqual(writer==calc=='false',result['fullEngineQualified'])
        for writer,calc in [('true','true'),('unknown','false'),('false','unknown'),('','false')]:
            self.ps('$env:'+WRITER+'='+quote(writer)+';$env:'+CALC+'='+quote(calc)+';\n'+wrapper+"$rejected=$false;try{\n"+body+"\n}catch{$rejected=$true};if(-not $rejected){throw 'Unknown or mixed workflow mode admitted'}")


if __name__=='__main__':unittest.main()
