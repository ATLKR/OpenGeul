"""Run the independent PowerShell source-proof replay with synthetic files."""
import copy
import importlib.util
import json
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

REGRESSION=Path(__file__).resolve().parents[1]
ROOT=REGRESSION.parents[2]
DRIVER=ROOT/'suite/scripts/build-native-engine.ps1'
PWSH=None  # Explicit existing tool supplied by runner; no discovery/install.
RECIPE_INPUT=None

def q(path):return "'"+str(path).replace("'","''")+"'"

def source_fixture(folder,architecture):
    p=REGRESSION/'tests/test_dotnet_project_graph_source.py'
    spec=importlib.util.spec_from_file_location('dotnet_ps_fixture',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    value=m.DotnetSourceRecipeTests();source,evidence=value.roots(folder)
    proof=m.module()._install_dotnet_project_graph(source,evidence,m.descriptor(),architecture)
    path=folder/'proof.json';path.write_text(json.dumps(proof)+'\n')
    return source,evidence,path

class PowershellGraphReplayTests(unittest.TestCase):
    def execute(self,folder,body,driver=DRIVER):
        script=folder/'case.ps1';script.write_text("$ErrorActionPreference='Stop'\n. "+q(driver)+'\n'+body)
        with open(os.devnull,'wb') as nul:
            p=subprocess.Popen([str(PWSH),'-NoLogo','-NoProfile','-File',str(script)],
                stdin=subprocess.DEVNULL,stdout=nul,stderr=nul,
                env={'PATH':str(PWSH.parent)+':/usr/bin:/bin','PYTHONUTF8':'1'})
            try:return p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill();p.wait(timeout=1);raise AssertionError('PowerShell replay deadline exceeded') from None

    def setup_body(self,proof):
        manifest=ROOT/'suite/engine-build/source-build.json'
        return '$p=Get-Content '+q(proof)+" -Raw|ConvertFrom-Json\n$m=Get-Content "+q(manifest)+" -Raw|ConvertFrom-Json\n"

    def call(self,evidence,architecture):
        return 'Assert-NativeDotnetProjectGraphSourceBinding $p $m.windowsDotnetProjectGraph '+architecture+' '+q(evidence)

    def test_real_powershell_replays_both_architecture_original_and_effective_files(self):
        for arch in ('arm64','x64'):
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp).resolve();source,evidence,proof=source_fixture(folder,arch)
                self.assertEqual(0,self.execute(folder,self.setup_body(proof)+self.call(evidence,arch)+'\n'))

    def test_real_powershell_rejects_forged_or_typed_source_proof_and_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp).resolve();source,evidence,proof=source_fixture(folder,'arm64')
            body=self.setup_body(proof)+self.call(evidence,'arm64')+'\n'
            mutations=("$p.fullEngineQualified=$true", "$p.sources[0].beforeBytes=$true",
                "$p.sources[0].afterSha256=('a'*64)", "$p.sources[0]|Add-Member extra 1",
                "$p.sources=@($p.sources[1],$p.sources[0])", "$p.sources=@($p.sources[0])",
                "$p.architecture='x64'", "$m.windowsDotnetProjectGraph.coreCommit=('a'*40)",
                "$m.windowsDotnetProjectGraph.sources[0].afterSize=$true", "$m.windowsDotnetProjectGraph|Add-Member extra 1",
                "$p.sources[0].evidence.effective=$p.sources[0].evidence.original")
            for i,mutation in enumerate(mutations):
                body+=(self.setup_body(proof)+mutation+'\n$rejected=$false;try{'+self.call(evidence,'arm64')+
                    '|Out-Null}catch{$rejected=$true};if(-not $rejected){exit '+str(10+i)+'}\n')
            self.assertEqual(0,self.execute(folder,body))

    def test_real_powershell_requires_this_owned_evidence_directory_and_exact_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp).resolve();source,evidence,proof=source_fixture(folder,'arm64')
            foreign=folder/'foreign';foreign.mkdir()
            body=(self.setup_body(proof)+self.call(evidence,'arm64')+'\n$rejected=$false;try{'+self.call(foreign,'arm64')+
                '|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 41}\n')
            body+='[IO.File]::AppendAllText('+q(evidence/'effective-DotnetTest.mk')+",'x')\n"
            body+='$rejected=$false;try{'+self.call(evidence,'arm64')+'|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 42}\n'
            self.assertEqual(0,self.execute(folder,body))

    def test_real_top_level_python_install_and_independent_powershell_recipe_binding(self):
        for arch in ('arm64','x64'):
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp).resolve();source=folder/'source';evidence=folder/'evidence';evidence.mkdir()
                shutil.copytree(RECIPE_INPUT,source)
                p=ROOT/'suite/engine-build/apply_native_source.py'
                spec=importlib.util.spec_from_file_location('full_owned_source_recipe',p)
                m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
                proof=m.apply_native_source(source,evidence,architecture=arch)
                proof['nativeTargetsSha256']=m._sha((p.parent/'native-targets.json').read_bytes())
                proof['sourcePortManifestSha256']=m._sha((p.parent/'source-build.json').read_bytes())
                receipt=folder/'full-source-only.json';receipt.write_text(json.dumps(proof)+'\n')
                body='$r=Get-Content '+q(receipt)+' -Raw|ConvertFrom-Json\n'
                call='Assert-NativeSourceRecipeBinding $r '+arch+' '+q(evidence)
                self.assertEqual(0,self.execute(folder,body+call+'\n'))
                # The old recipe cannot consume a new source plan under an old
                # recipe label. The exact manifest/plan remains mandatory.
                body+='$r.sourceRecipeProof.hookOrder=@($r.sourceRecipeProof.hookOrder|Where-Object {$_ -cne \"dotnetProjectGraph\"})\n'
                body+='$rejected=$false;try{'+call+'|Out-Null}catch{$rejected=$true};if(-not $rejected){exit 61}\n'
                self.assertEqual(0,self.execute(folder,body))

if __name__=='__main__':unittest.main()
