"""Controlled partial TWAIN component capture, never a qualified Full fixture."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from test_source_twain import twain_image,peer_image

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'suite/engine-build/capture_source_twain.py'
FIXTURES=Path(__file__).parent/'fixtures/twain-source-9dea'

class TwainCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def fixture(self,label):
        root=self.root/label;source=root/'source';shutil.copytree(FIXTURES,source)
        runtime=root/'runtime';(runtime/'program').mkdir(parents=True);evidence=root/'evidence';evidence.mkdir()
        (source/'config_host.mk').write_text('OS=WNT\nCPUNAME=X86_64\nCOM=MSC\nCXX_X86_BINARY=owned-synthetic-compiler\n'+'SRCDIR='+str(source)+'\nINSTROOT='+str(source/'instdir')+'\nLIBO_LIB_FOLDER=program\nLIBO_BIN_FOLDER=program\n')
        policy=source/'cli_ure/CliNativeLibrary_cli_cppuhelper.mk';original=policy.read_bytes()
        marker=b'$(eval $(call gb_CliNativeLibrary_CliNativeLibrary,cli_cppuhelper))\n'
        added=b'\nifeq ($(OS)_$(CPUNAME),WNT_X86_64)\n$(eval $(call gb_CliNativeLibrary_set_platform,cli_cppuhelper,x64))\nendif\n'
        self.assertEqual(original.count(marker),1);effective=original.replace(marker,marker+added);policy.write_bytes(effective)
        recipe=evidence/'source-recipe';recipe.mkdir()
        original_path=recipe/'original-x64-CliNativeLibrary_cli_cppuhelper.mk';original_path.write_bytes(original)
        effective_path=recipe/'effective-x64-CliNativeLibrary_cli_cppuhelper.mk';effective_path.write_bytes(effective)
        exe=twain_image();peer=peer_image()
        for path,data in [('program/twain32shim.exe',exe),('program/scnlo.dll',peer)]:
            (runtime/path).write_bytes(data)
        for path,data in [('instdir/program/twain32shim.exe',exe),('instdir/program/scnlo.dll',peer)]:
            p=source/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        archive=source/'workdir/installation/owned/archive/install/partial-twain-component.zip';archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('owned/program/twain32shim.exe',exe);z.writestr('owned/program/scnlo.dll',peer)
        sha=lambda b:hashlib.sha256(b).hexdigest()
        rows=[dict(path=p,archivePath=str(archive),archiveMember='owned/'+p,bytes=len(d),sha256=sha(d)) for p,d in [('program/twain32shim.exe',exe),('program/scnlo.dll',peer)]]
        stage=dict(kind='source-built-installed-runtime-stage',passed=True,architecture='x64',runtimeRoot=str(runtime),files=rows,
                   archives=[dict(kind='main',path=str(archive),bytes=archive.stat().st_size,sha256=sha(archive.read_bytes()))])
        stage_path=evidence/'installed-runtime-stage.json';stage_path.write_text(json.dumps(stage))
        context=dict(schemaVersion=1,architecture='x64',coreCommit='9dea406ab7695df6325b11b0e19fdca8db4b7276',buildBinding=dict(sourceCommit='1'*40,sourceTree='2'*40,sourceRun=123,runAttempt=1,recipeSha256='3'*64),stageReceiptSha256=sha(stage_path.read_bytes()),sourceEvidenceDirectory=str(recipe),cliPolicyEvidence=dict(original=str(original_path),effective=str(effective_path)))
        recipe=evidence/'source-recipe';recipe.mkdir(exist_ok=True)
        fixture_root=Path(__file__).parent/'fixtures/twain-source-9dea'
        descriptor=json.loads((ROOT/'suite/engine-build/source-build.json').read_bytes())['windowsX86CompanionStaticRuntime']
        for pin in descriptor['sources']:
            target=source/pin['path'];target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():target.write_bytes((fixture_root/pin['path']).read_bytes())
        spec=importlib.util.spec_from_file_location('capture_fixture_crt',ROOT/'suite/engine-build/apply_x86_companion_crt.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        installed=installer.install(source,recipe,descriptor)
        self.static_runtime_source_hook=installed
        context['sourceEvidenceDirectory']=str(recipe)
        context['x86StaticRuntimeEvidence']=[dict(path=row['path'],**row['evidence'])for row in installed['recipes']]
        context_path=root/'context.json';context_path.write_text(json.dumps(context))
        return source,runtime,stage_path,context_path,evidence
    def run_capture(self,paths,*,validate=False):
        args=[sys.executable,'-I','-B',str(SCRIPT)]
        for name,value in zip(('source','runtime','stage','context','evidence'),paths):args.extend(('--'+name,str(value)))
        if validate:args.append('--validate')
        env={'PATH':'/usr/bin:/bin','PYTHONUTF8':'1'}
        if os.name=='nt':env={'PATH':str(Path(sys.executable).parent),'SystemRoot':os.environ.get('SystemRoot',r'C:\Windows'),'PYTHONUTF8':'1'}
        return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,timeout=10).returncode
    def test_twain_capture_requires_exact_source_effect_and_scanner_peer(self):
        paths=self.fixture('valid');self.assertEqual(self.run_capture(paths),0)
        proof=json.loads((paths[-1]/'source-twain-proof.json').read_text())
        self.assertEqual(proof['kind'],'source-built-x86-twain-companion');self.assertEqual(len(proof['sourceProofs']),25)
        self.assertEqual(proof['nativePeer']['path'],'program/scnlo.dll');self.assertIs(proof['fullEngineQualified'],False)
        self.assertEqual(self.run_capture(paths,validate=True),0)
    def test_same_bytes_from_another_evidence_directory_cannot_claim_this_run(self):
        paths=self.fixture('other-evidence');context=json.loads(paths[3].read_text());previous=self.root/'previous-source-recipe';previous.mkdir()
        for phase in ('original','effective'):
            old=Path(context['cliPolicyEvidence'][phase]);new=previous/old.name;shutil.copy2(old,new);context['cliPolicyEvidence'][phase]=str(new)
        context['sourceEvidenceDirectory']=str(previous);paths[3].write_text(json.dumps(context))
        self.assertNotEqual(self.run_capture(paths),0);self.assertFalse((paths[-1]/'source-twain-proof.json').exists())
    def test_changed_original_or_effective_sources_fail_before_proof(self):
        for kind in ('original','effective','current'):
            with self.subTest(kind=kind):
                paths=self.fixture(kind);context=json.loads(paths[3].read_text())
                target=paths[0]/'cli_ure/CliNativeLibrary_cli_cppuhelper.mk' if kind=='current' else Path(context['cliPolicyEvidence'][kind])
                target.write_bytes(target.read_bytes()+b'x');self.assertNotEqual(self.run_capture(paths),0)
                self.assertFalse((paths[-1]/'source-twain-proof.json').exists())
    def test_cross_run_revalidation_cannot_relabel_a_frozen_component(self):
        paths=self.fixture('replay');self.assertEqual(self.run_capture(paths),0);proof=paths[-1]/'source-twain-proof.json';before=proof.read_bytes()
        context=json.loads(paths[3].read_text());context['buildBinding']['sourceRun']=124;paths[3].write_text(json.dumps(context))
        self.assertNotEqual(self.run_capture(paths,validate=True),0);self.assertEqual(proof.read_bytes(),before)
    def test_only_exact_windows_x64_configuration_can_capture_the_x86_bridge(self):
        for ordinal,config in enumerate(('OS=LINUX\nCPUNAME=X86_64\nCXX_X86_BINARY=owned\n',
                'OS=WNT\nCPUNAME=AARCH64\nCXX_X86_BINARY=owned\n',
                'OS=WNT\nCPUNAME=X86_64\nCXX_X86_BINARY=\n',
                'OS=WNT\nOS=LINUX\nCPUNAME=X86_64\nCXX_X86_BINARY=owned\n',
                'OS=WNT\nCPUNAME=X86_64\nCXX_X86_BINARY=\nOTHER=owned\n')):
            with self.subTest(ordinal=ordinal):
                paths=self.fixture('config-'+str(ordinal));(paths[0]/'config_host.mk').write_text(config)
                self.assertNotEqual(self.run_capture(paths),0);self.assertFalse((paths[-1]/'source-twain-proof.json').exists())
