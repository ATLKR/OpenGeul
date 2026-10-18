"""Offline diagnostic boundary controls; no Windows compiler or product execution."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'suite/scripts/probe-native-atl-path-control.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"

class NativeAtlPathControlTests(unittest.TestCase):
    def ps(self, body, success=True):
        self.assertTrue(SCRIPT.is_file(), 'Missing bounded Native28 ATL path controller')
        result=subprocess.run([PWSH,'-NoProfile','-NonInteractive','-Command',"$ErrorActionPreference='Stop'; . "+quote(SCRIPT)+'; '+body],capture_output=True,text=True,timeout=25)
        if success:self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        else:self.assertNotEqual(0,result.returncode,result.stdout+result.stderr)
        return result.stdout

    def test_owned_command_adapter_changes_only_exact_finite_environment_list(self):
        data=json.loads(self.ps("Initialize-AtlPathOwnedCommand|ConvertTo-Json -Depth 8 -Compress"))
        self.assertEqual(['PATH','FIREBIRD','LIB','INCLUDE','CL','_CL_','LINK','_LINK_','VSLANG'],data['allowedEnvironmentNames'])
        self.assertEqual('501680337e44e33e4c58cfdfbdd4d39cc4d4925cf91f458ec93800b663c9a7b4',data['driverSha256'])
        self.assertTrue(data['originalBodyRestoredExactly'])
        self.assertRegex(data['originalDefinitionSha256'],r'^[a-f0-9]{64}$')
        self.assertRegex(data['adaptedDefinitionSha256'],r'^[a-f0-9]{64}$')
        self.assertNotEqual(data['originalDefinitionSha256'],data['adaptedDefinitionSha256'])

    def test_old_driver_rejects_lib_and_new_adapter_rejects_unlisted_key_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(strict=True)
            body="Initialize-AtlPathOwnedCommand|Out-Null; "
            for function,key,name in [('Invoke-LoggedCommand','LIB','old'),('Invoke-AtlPathOwnedCommand','UNREVIEWED','new')]:
                body+=f"try {{{function} 'never-start-native' @() {quote(root)} {quote(root/name)} -EnvironmentOverrides @{{{key}='controlled'}}|Out-Null;throw 'Unexpected admission'}}catch{{if($_.Exception.Message -cne 'Unsupported child environment override.'){{throw}}}}; "
            body+="Write-Output 'both rejected before start'"
            self.ps(body)
            for name in ['old','new']:
                row=json.loads((root/(name+'.command.json')).read_text())
                self.assertNotIn('pid',row);self.assertFalse(row['passed'])
            allowed=['PATH','FIREBIRD','LIB','INCLUDE','CL','_CL_','LINK','_LINK_','VSLANG']
            table=';'.join(name+"='controlled'" for name in allowed)
            self.ps(f"Initialize-AtlPathOwnedCommand|Out-Null;try{{Invoke-AtlPathOwnedCommand {quote(root/'nonexistent-native.exe')} @() {quote(root)} {quote(root/'allowed')} -EnvironmentOverrides @{{{table}}}|Out-Null}}catch{{}};Write-Output 'gate observed'")
            row=json.loads((root/'allowed.command.json').read_text())
            self.assertEqual(set(allowed),set(row['environmentOverrideSha256']))
            self.assertNotIn('Unsupported child environment',row['error']);self.assertNotIn('pid',row)
            self.assertFalse(row['passed'])

    def test_link_arms_differ_only_by_atl_receiver_and_owned_output_paths(self):
        data=json.loads(self.ps("Get-AtlPathLinkArms @('C:/native/lib/arm64','C:/sdk/um/arm64') 'C:/native/atlmfc/lib/spectre/arm64' 'C:/owned/fixture.obj' 'C:/owned'|ConvertTo-Json -Depth 8 -Compress"))
        base,candidate=data['baseline'],data['candidate']
        self.assertIn('atls.lib',base);self.assertNotIn('-LIBPATH:C:/native/atlmfc/lib/spectre/arm64',base)
        self.assertIn('-LIBPATH:C:/native/atlmfc/lib/spectre/arm64',candidate)
        self.assertIn('C:/native/atlmfc/lib/spectre/arm64/atls.lib',candidate)
        normalize=lambda args:[x for x in args if not x.startswith(('-OUT:','-MAP:')) and x not in ('atls.lib','-LIBPATH:C:/native/atlmfc/lib/spectre/arm64','C:/native/atlmfc/lib/spectre/arm64/atls.lib')]
        self.assertEqual(normalize(base),normalize(candidate))
        self.assertEqual(1,base.count('C:/owned/fixture.obj'));self.assertEqual(1,candidate.count('C:/owned/fixture.obj'))

    def test_direct_native_receipts_require_normal_drained_unforced_completion(self):
        self.ps("$r=[pscustomobject]@{passed=$true;exitCode=0;pipeDrainComplete=$true;forcedTermination=$false;directProcessDeathVerified=$true;processTreeCleanup='not-requested';cleanupErrors=@()}; Assert-AtlPathCommandReceipt $r Candidate|Out-Null; $r.passed=$false;$r.exitCode=1104;Assert-AtlPathCommandReceipt $r Baseline|Out-Null; foreach($change in @('pipe','forced','dead','cleanup','exit','passed')){$x=$r.PSObject.Copy();switch($change){pipe{$x.pipeDrainComplete=$false}forced{$x.forcedTermination=$true}dead{$x.directProcessDeathVerified=$false}cleanup{$x.cleanupErrors=@('bad')}exit{$x.exitCode=2}passed{$x.passed=$true}};$rejected=$false;try{Assert-AtlPathCommandReceipt $x Baseline|Out-Null}catch{$rejected=$true};if(-not $rejected){throw ('Accepted '+$change)}}")

    def test_baseline_red_is_only_exact_missing_bare_atls_with_matching_native_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory).resolve(strict=True)/'link.log'
            for text,code,valid in [("LINK : fatal error LNK1104: cannot open file 'atls.lib'",1104,True),("LINK : fatal error LNK1181: cannot open input file 'atls.lib'",1181,True),("LINK : fatal error LNK1104: cannot open file 'kernel32.lib'",1104,False),("LINK : fatal error LNK1104: cannot open file 'atls.lib'\nLINK : error LNK2001: unresolved symbol",1104,False),("LINK : fatal error LNK1104: cannot open file 'atls.lib'",2,False),("LINK : fatal error LNK1104: cannot open file 'C:/foreign/atls.lib'",1104,False)]:
                log.write_text(text+'\n',encoding='utf-8')
                self.ps(f"Assert-AtlPathMissingLibrary @({quote(log)}) {code}|ConvertTo-Json -Compress",success=valid)

    def test_fixture_is_authored_and_never_registers_or_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory).resolve(strict=True)/'owned.cpp'
            self.ps('Write-AtlPathFixture '+quote(target))
            text=target.read_text(encoding='utf-8-sig')
            self.assertIn('#include <atlbase.h>',text);self.assertIn('_Module.GetModuleInstance()',text)
            self.assertNotIn('RegisterServer',text)
        script=SCRIPT.read_text();self.assertNotRegex(script,r'Invoke-\w+\s+\$exe')

    def test_reused_mixed_archive_and_consumption_utilities_are_exact_pinned_copies(self):
        self.assertTrue(SCRIPT.is_file(), 'Missing bounded Native28 ATL path controller')
        root=ROOT/'suite/diagnostics/native-atl-source';manifest=json.loads((root/'path-control-source.json').read_text())
        for row in manifest['reusedInputs']:
            data=(ROOT/row['repositoryPath']).read_bytes()
            self.assertEqual(row['bytes'],len(data));self.assertEqual(row['sha256'],hashlib.sha256(data).hexdigest())
        profiles=json.loads((root/'atl-static-profiles.json').read_text())['profiles']
        self.assertEqual({'regular','spectre'},{r['kind'] for r in profiles})
        self.assertTrue(all(r['aa64ObjectCount']==5 and r['arm64EcObjectCount']==5 for r in profiles))

    def test_dot_sourcing_does_not_erase_the_external_workflow_deadline(self):
        self.ps(". "+quote(SCRIPT)+" -DeadlineUtc '2030-01-01T00:00:00.0000000Z'; if($DeadlineUtc -cne '2030-01-01T00:00:00.0000000Z'){throw 'Workflow deadline was erased by dot-sourced driver parameters'}")

    def test_workflow_reserves_first_step_deadline_and_uploads_only_owned_evidence(self):
        self.assertTrue(SCRIPT.is_file(), 'Missing bounded Native28 ATL path controller')
        text=(ROOT/'.github/workflows/office-native-atl-path-control.yml').read_text()
        self.assertIn('runs-on: windows-11-arm',text);self.assertIn('timeout-minutes: 20',text)
        self.assertLess(text.index("origin='first-user-step'"),text.index('actions/checkout@'))
        self.assertIn('AddMinutes(15)',text);self.assertIn('if: always()',text)
        self.assertIn('include-hidden-files: true',text);self.assertIn('if-no-files-found: error',text)
        self.assertNotIn('${{ env.OPENGEUL_ATL_PATH_BUDGET_ROOT }}/',text)
        self.assertIn('${{ runner.temp }}/native28-atl-budget-${{ github.run_id }}-${{ github.run_attempt }}/',text)
        self.assertNotIn('setup-python',text);self.assertNotIn('contents: write',text)
        self.assertNotIn('build-native-engine.ps1 -Phase',text)

if __name__=='__main__':unittest.main(verbosity=2)
