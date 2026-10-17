"""Portable fixture/reader boundaries; no Windows link-mode claims."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'suite/scripts/probe-native-module-links.ps1'
PWSH=shutil.which('pwsh') or '/workspace/work/opengeul-improvements/work/ime-api-review/powershell/pwsh'

def quote(value):return "'"+str(value).replace("'","''")+"'"

class NativeModuleLinkProbeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(),'The isolated native module-link diagnostic is required')
        self.temp=tempfile.TemporaryDirectory(prefix='module-link-probe-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.generated=self.root/'fixture.py';self.plan=self.root/'pins.json'
        body='Write-ModuleLinkFixturePython '+quote(self.generated)+'; Write-BuildJson '+quote(self.plan)+" ([ordered]@{source=(Get-SourcePin "+quote(ROOT/'suite/config/runtime.arm64.lock.json')+");extras=@(Get-ExtraSourcePins)})"
        self.ps(body)

    def ps(self,body):
        path=self.root/'case.ps1';path.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+'\n'+body)
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(path)],capture_output=True,text=True,timeout=15)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)

    def create(self,repo=ROOT):
        work=self.root/'work';evidence=self.root/'evidence';work.mkdir();evidence.mkdir()
        result=subprocess.run([sys.executable,str(self.generated),'create',str(repo),str(work),str(evidence),str(self.plan)],capture_output=True,text=True,timeout=10)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        return json.loads(result.stdout)

    @unittest.skipUnless(os.name!='nt' and Path('/usr/bin/make').is_file(),'Portable GNU recipe execution only')
    def test_generated_fixtures_use_guarded_helper_and_actual_make_recipe(self):
        plan=self.create();reader=runpy.run_path(str(self.generated))
        self.assertEqual(['current','nativestrict'],[row['mode'] for row in plan['cases']])
        for case in plan['cases']:
            core=Path(case['core']);script=self.root/(case['mode']+'.sh')
            self.ps('Write-ModuleLinkMakeRecipe '+quote(script)+' '+quote(core))
            result=subprocess.run(['/bin/bash',str(script)],cwd=core,capture_output=True,text=True,timeout=10)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            self.assertEqual(3,result.stdout.count('Unpacking libreoffice-'))
            self.assertFalse((core/'git-hooks').exists())
            for row in case['modules']:
                self.assertTrue(Path(row['linkPath']).parent.is_symlink())
                self.assertTrue(reader['read_record'](row['directPath'],row['sha256'])['matches'])
                self.assertTrue(reader['read_record'](row['linkPath'],row['sha256'])['matches'])
            before=Path(case['evidence'])/'original-unpack-sources';after=Path(case['evidence'])/'effective-unpack-sources'
            self.assertEqual(before.read_bytes().replace(b'-type d -path ',b'-type d ! -path '),after.read_bytes())
            for archive in case['archives']:
                self.assertEqual(archive['sha256'],hashlib.sha256(Path(archive['path']).read_bytes()).hexdigest())
                self.assertEqual(Path(archive['path']).read_bytes(),Path(archive['evidencePath']).read_bytes())

    def test_setup_pin_is_the_official_production_sha512_and_url(self):
        path=self.root/'setup-pin.json'
        self.ps('Write-BuildJson '+quote(path)+' (Get-ModuleLinkSetupPin)')
        pin=json.loads(path.read_text())
        self.assertEqual('https://cygwin.com/setup-x86_64.exe',pin['url'])
        self.assertEqual('6acea47c59781c9e7f544a18d53935d59df6e44d5d52ac95ee165671b8e388820455eebf30ccc7d254b00c3d0eb694269a0f8dc84b17944c1f355dac9c5aafcc',pin['sha512'])

    def test_explicit_probe_work_directory_survives_production_driver_import(self):
        child=self.root/'import.ps1';saved=self.root/'arguments.json'
        child.write_text("$ErrorActionPreference='Stop'\n. "+quote(SOURCE)+" -Output sentinel-evidence -WorkDirectory sentinel-work\n"+
                         "[ordered]@{output=$Output;work=$ProbeWorkDirectory}|ConvertTo-Json|Set-Content -LiteralPath "+quote(saved))
        result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-File',str(child)],capture_output=True,text=True,timeout=15)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertEqual(dict(output='sentinel-evidence',work='sentinel-work'),json.loads(saved.read_text()))

    def test_workflow_accepts_normal_powershell_completion_without_native_exit_code(self):
        workflow=(ROOT/'.github/workflows/office-native-module-link-probe.yml').read_text()
        guard=next(line.strip() for line in workflow.splitlines() if "throw 'Native module link diagnostic failed" in line)
        self.ps('$global:LASTEXITCODE=$null; & { Write-Output "normal diagnostic completion" }; '+guard)

    def test_native_reader_records_missing_and_changed_bytes_without_fallback(self):
        plan=self.create();reader=runpy.run_path(str(self.generated));case=plan['cases'][0]
        row=case['modules'][0]
        missing=reader['read_record'](row['linkPath'],row['sha256'])
        self.assertFalse(missing['matches']);self.assertFalse(missing['readable']);self.assertIn('error',missing)
        target=Path(row['directPath']);target.parent.mkdir(parents=True);target.write_bytes(b'wrong marker')
        changed=reader['read_record'](target,row['sha256'])
        self.assertTrue(changed['readable']);self.assertFalse(changed['matches'])

    def test_changed_helper_is_rejected_before_fixture_creation(self):
        repo=self.root/'changed-repo'
        for relative in ('suite/engine-build/enable_firebird_arm64.py','suite/engine-build/source-build.json','suite/tests/fixtures/native-source-tar/unpack-sources','suite/tests/fixtures/native-source-tar/get-submodules.mk','suite/tests/fixtures/native-source-tar/source.json'):
            target=repo/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,target)
        helper=repo/'suite/tests/fixtures/native-source-tar/unpack-sources';helper.write_bytes(helper.read_bytes()+b'changed')
        work=self.root/'work';evidence=self.root/'evidence';work.mkdir();evidence.mkdir()
        result=subprocess.run([sys.executable,str(self.generated),'create',str(repo),str(work),str(evidence),str(self.plan)],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(0,result.returncode);self.assertIn('SHA256',result.stderr)
        self.assertEqual([],list(work.iterdir()));self.assertEqual([],list(evidence.iterdir()))

if __name__=='__main__':unittest.main()
