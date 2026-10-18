"""Real env/bash child inheritance; only Cygwin path conversion is a fixture.

The actual Windows link/read difference is retained in diagnostic39027528344.
These portable tests claim no Windows link or native Office qualification.
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
DRIVER=ROOT/'suite/scripts/build-native-engine.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"

@unittest.skipUnless(os.name!='nt' and Path('/usr/bin/env').is_file() and Path('/bin/bash').is_file(),
                     'Portable GNU child-process boundary; actual Cygwin already separately probed')
class NativeSourceLinkPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='native-link-policy-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);tools=self.root/'tools';tools.mkdir()
        self.bash=tools/'bash.exe';self.env=tools/'env.exe'
        shutil.copyfile('/bin/bash',self.bash);self.bash.chmod(0o755)
        shutil.copyfile('/usr/bin/env',self.env);self.env.chmod(0o755)
        self.cygpath=tools/'cygpath'
        self.cygpath.write_text('#!'+sys.executable+'\nimport sys\nprint(sys.argv[-1])\n');self.cygpath.chmod(0o755)
        self.child=self.root/'owned-child.sh'
        body="import json,os;print(json.dumps({'CYGWIN':os.environ.get('CYGWIN'),'sentinel':os.environ.get('OPENGEUL_LINK_SENTINEL')}))"
        self.child.write_text('exec '+shlex.quote(sys.executable)+' -c '+shlex.quote(body)+'\n')

    def ps(self,body):
        script=self.root/'case.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n. "+quote(DRIVER)+"\n"+
                          "$env:CYGWIN='preserve-controller';$env:OPENGEUL_LINK_SENTINEL='owned-child'\n"+body)
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(script)],capture_output=True,text=True,timeout=15)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)

    def invoke(self,name,native=False):
        prefix=self.root/name;observed=self.root/(name+'.json')
        self.ps('$before=$env:CYGWIN; $result=Invoke-CygwinScript '+quote(self.bash)+' '+quote(self.cygpath)+' '+
                quote(self.child)+' '+quote(self.root)+' '+quote(prefix)+(' -NativeLinks' if native else '')+
                '; Write-BuildJson '+quote(observed)+' ([ordered]@{before=$before;after=$env:CYGWIN;child=(Get-Content -Raw $result.stdout|ConvertFrom-Json)})')
        return json.loads(observed.read_text()),json.loads(Path(str(prefix)+'.command.json').read_text())

    def test_native_policy_is_child_only_and_default_preserves_inherited_mode(self):
        strict,command=self.invoke('strict',True)
        self.assertEqual('winsymlinks:nativestrict',strict['child']['CYGWIN'])
        self.assertEqual('owned-child',strict['child']['sentinel'])
        self.assertEqual('preserve-controller',strict['before']);self.assertEqual(strict['before'],strict['after'])
        self.assertEqual(str(self.env),command['file'])
        self.assertEqual(['CYGWIN=winsymlinks:nativestrict',str(self.bash),'--noprofile','--norc',str(self.child)],command['arguments'])
        inherited,command=self.invoke('inherited')
        self.assertEqual('preserve-controller',inherited['child']['CYGWIN'])
        self.assertEqual(inherited['before'],inherited['after']);self.assertEqual(str(self.bash),command['file'])

    def test_native_child_failure_keeps_original_receipt_and_controller_environment(self):
        self.child.write_text('exit 7\n');prefix=self.root/'failed';state=self.root/'failed.json'
        self.ps('$before=$env:CYGWIN;$caught=$false;try { Invoke-CygwinScript '+quote(self.bash)+' '+quote(self.cygpath)+' '+
                quote(self.child)+' '+quote(self.root)+' '+quote(prefix)+' -NativeLinks | Out-Null } catch {$caught=$true};'+
                'Write-BuildJson '+quote(state)+' ([ordered]@{caught=$caught;before=$before;after=$env:CYGWIN})')
        observed=json.loads(state.read_text());command=json.loads(Path(str(prefix)+'.command.json').read_text())
        self.assertTrue(observed['caught']);self.assertEqual(observed['before'],observed['after'])
        self.assertFalse(command['passed']);self.assertEqual(7,command['exitCode'])
        self.assertTrue(command['pipeDrainComplete']);self.assertFalse(command['forcedTermination'])
        self.assertEqual(str(self.env),command['file'])

    def test_actual_production_make_invocation_selects_native_policy(self):
        prefix=self.root/'make-ExternalProject_firebird';state=self.root/'make.json'
        self.ps(f"""
$bash={quote(self.bash)};$cygpath={quote(self.cygpath)};$script={quote(self.child)};$work={quote(self.root)};$evidence={quote(self.root)};$target='ExternalProject_firebird'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(DRIVER)},[ref]$tokens,[ref]$errors)
$calls=@($ast.FindAll({{param($n) $n -is [Management.Automation.Language.CommandAst] -and
 $n.GetCommandName() -eq 'Invoke-CygwinScript' -and $n.Extent.Text.Contains("'make-'")}},$true))
if($errors.Count -or $calls.Count -ne 1){{throw 'Expected one actual make child invocation'}}
Invoke-Expression $calls[0].Extent.Text|Out-Null
Write-BuildJson {quote(state)} ([ordered]@{{after=$env:CYGWIN}})
""")
        command=json.loads(Path(str(prefix)+'.command.json').read_text())
        child=json.loads(Path(str(prefix)+'.stdout.log').read_text())
        self.assertEqual('winsymlinks:nativestrict',child['CYGWIN'])
        self.assertEqual(str(self.env),command['file'])
        self.assertEqual('preserve-controller',json.loads(state.read_text())['after'])

if __name__=='__main__':unittest.main()
