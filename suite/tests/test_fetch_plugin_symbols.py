"""Exact symbol artifact bytes use the existing authenticated no-redirect clients."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_fetch_source_engine as f
SCRIPT=f.ROOT/'suite/scripts/fetch-plugin-symbols.ps1'

@unittest.skipUnless(f.PWSH,'PowerShell runtime unavailable')
class SymbolFetchTests(unittest.TestCase):
    def execute(self,mode):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture=f.FetchSourceEngineTests();fixture.fixture(root)
            files={'receipt.json':b'{}','vclplug_winlo.dll':b'dll','vclplug_winlo.pdb':b'pdb'}
            entries=[(name,data,0) for name,data in files.items()]
            if mode=='extra':entries.append(('other',b'x',0))
            if mode=='duplicate':entries.append(entries[-1])
            if mode=='linked':entries[-1]=(entries[-1][0],entries[-1][1],0xa000<<16)
            outer=f.zip_bytes(entries);(root/'outer.zip').write_bytes(outer)
            lock=dict(schemaVersion=1,kind='native-arm64-plugin-symbols',architecture='arm64',sourceCommit='a'*40,
                runId=123,runAttempt=1,artifactId=456,artifactSize=len(outer),artifactSha256=f.sha(outer),
                files={name:dict(bytes=len(data),sha256=f.sha(data)) for name,data in files.items()})
            if mode=='wrong-hash':lock['files']['vclplug_winlo.pdb']['sha256']='0'*64
            artifact=json.loads((root/'artifact.json').read_text());artifact.update(name='opengeul-native-arm64-plugin-symbols-123-1',size_in_bytes=len(outer),digest='sha256:'+f.sha(outer))
            if mode=='wrong-source':artifact['workflow_run']['head_sha']='b'*40
            for name,value in (('lock',lock),('artifact',artifact)):(root/(name+'.json')).write_text(json.dumps(value))
            harness=f.HARNESS.replace('Invoke-SourceEngineFetch','Invoke-PluginSymbolFetch').replace('SourceLockPath=','SymbolLockPath=')
            (root/'harness.ps1').write_text(harness)
            env=dict(os.environ);env.pop('GITHUB_TOKEN',None);env['GH_TOKEN']=f.SECRET
            self.assertTrue(SCRIPT.exists(),'symbol artifact fetcher absent')
            result=subprocess.run([f.PWSH,'-NoProfile','-File',str(root/'harness.ps1'),'-Root',str(root),'-Script',str(SCRIPT)],capture_output=True,text=True,env=env,timeout=30)
            self.assertNotIn(f.SECRET,result.stdout+result.stderr);self.assertNotIn(f.SIGNED_SECRET,result.stdout+result.stderr)
            if mode=='success':
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                for name,data in files.items():self.assertEqual((root/'output/pair'/name).read_bytes(),data)
            else:self.assertNotEqual(result.returncode,0)
    def test_exact_artifact_family_and_metadata(self):
        for mode in ('success','extra','duplicate','linked','wrong-hash','wrong-source'):
            with self.subTest(mode=mode):self.execute(mode)

if __name__=='__main__':unittest.main()
