"""Synthetic partial-component capture only, never a Full receipt or engine ZIP."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from test_source_companion import image

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'suite/engine-build/capture_source_companion.py'
FIXTURES=Path(__file__).parent/'fixtures/spsupp-source-9dea'

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def fixture(self,label):
        root=self.root/label;source=root/'source';shutil.copytree(FIXTURES,source)
        runtime=root/'runtime';(runtime/'program').mkdir(parents=True);evidence=root/'evidence';evidence.mkdir()
        (source/'config_host.mk').write_text('CXX_X86_BINARY=owned-synthetic-compiler\n')
        dll=image();helper=image(native=True)
        for path,data in [('program/spsupp_x86.dll',dll),('program/spsupp_helper.exe',helper)]:
            (runtime/path).write_bytes(data)
        for path,data in [('workdir/LinkTarget/Library/spsupp_x86.dll',dll),('workdir/LinkTarget/Executable/spsupp_helper.exe',helper)]:
            p=source/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        archive=source/'workdir/installation/owned/archive/install/partial-component.zip';archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('owned/program/spsupp_x86.dll',dll);z.writestr('owned/program/spsupp_helper.exe',helper)
        sha=lambda b:hashlib.sha256(b).hexdigest()
        rows=[dict(path=p,archivePath=str(archive),archiveMember='owned/'+p,bytes=len(d),sha256=sha(d)) for p,d in [('program/spsupp_x86.dll',dll),('program/spsupp_helper.exe',helper)]]
        stage=dict(kind='source-built-installed-runtime-stage',passed=True,architecture='x64',runtimeRoot=str(runtime),files=rows,
                   archives=[dict(kind='main',path=str(archive),bytes=archive.stat().st_size,sha256=sha(archive.read_bytes()))])
        stage_path=evidence/'installed-runtime-stage.json';stage_path.write_text(json.dumps(stage))
        context=dict(schemaVersion=1,architecture='x64',coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276',
                     buildBinding=dict(sourceCommit='1'*40,sourceTree='2'*40,sourceRun=123,runAttempt=1,recipeSha256='3'*64),stageReceiptSha256=sha(stage_path.read_bytes()))
        context_path=root/'context.json';context_path.write_text(json.dumps(context))
        return source,runtime,stage_path,context_path,evidence
    def run_capture(self,paths,*,validate=False):
        args=[sys.executable,'-I','-B',str(SCRIPT)]
        for name,value in zip(('source','runtime','stage','context','evidence'),paths):args.extend(('--'+name,str(value)))
        if validate:args.append('--validate')
        env={'PATH':'/usr/bin:/bin','PYTHONUTF8':'1'}
        if os.name=='nt':env={'PATH':str(Path(sys.executable).parent),'SystemRoot':os.environ.get('SystemRoot',r'C:\Windows'),'PYTHONUTF8':'1'}
        return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,timeout=10).returncode
    def test_exact_source_and_owned_partial_component_capture(self):
        paths=self.fixture('valid');self.assertEqual(self.run_capture(paths),0)
        p=json.loads((paths[-1]/'source-companion-proof.json').read_text())
        self.assertEqual(p['role'],'x86CompatibilityHelper');self.assertIs(p['fullEngineQualified'],False)
        self.assertIs(p['acceptanceEligible'],False);self.assertEqual(len(p['sourceProofs']),13)
    def test_changed_source_or_linktarget_never_emits_a_component_proof(self):
        for kind in ('source','target'):
            with self.subTest(kind=kind):
                paths=self.fixture(kind);path=paths[0]/('shell/Library_spsupp_x86.mk' if kind=='source' else 'workdir/LinkTarget/Library/spsupp_x86.dll')
                path.write_bytes(path.read_bytes()+b'x');self.assertNotEqual(self.run_capture(paths),0)
                self.assertFalse((paths[-1]/'source-companion-proof.json').exists())
    def test_foreign_stage_kind_is_rejected_before_retention(self):
        paths=self.fixture('foreign-stage');stage=json.loads(paths[2].read_text());stage['kind']='other';paths[2].write_text(json.dumps(stage))
        context=json.loads(paths[3].read_text());context['stageReceiptSha256']=hashlib.sha256(paths[2].read_bytes()).hexdigest();paths[3].write_text(json.dumps(context))
        self.assertNotEqual(self.run_capture(paths),0);self.assertFalse((paths[-1]/'source-companion-proof.json').exists())
    def test_final_validation_rechecks_same_build_and_retained_sources_without_relabelling(self):
        paths=self.fixture('validate');self.assertEqual(self.run_capture(paths),0)
        proof_path=paths[-1]/'source-companion-proof.json';original=proof_path.read_bytes()
        self.assertEqual(self.run_capture(paths,validate=True),0);self.assertEqual(proof_path.read_bytes(),original)
        context=json.loads(paths[3].read_text());context['buildBinding']['sourceRun']=124;paths[3].write_text(json.dumps(context))
        self.assertNotEqual(self.run_capture(paths,validate=True),0);self.assertEqual(proof_path.read_bytes(),original)
