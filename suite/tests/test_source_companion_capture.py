"""Synthetic partial-component capture only, never a Full receipt or engine ZIP."""
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
        (source/'config_host.mk').write_text('OS=WNT\nCPUNAME=X86_64\nCOM=MSC\nCXX_X86_BINARY=owned-synthetic-compiler\n'+'SRCDIR='+str(source)+'\nINSTROOT='+str(source/'instdir')+'\nLIBO_LIB_FOLDER=program\nLIBO_BIN_FOLDER=program\n')
        dll=image();helper=image(native=True)
        for path,data in [('program/spsupp_x86.dll',dll),('program/spsupp_helper.exe',helper)]:
            (runtime/path).write_bytes(data)
        for path,data in [('instdir/program/spsupp_x86.dll',dll),('instdir/program/spsupp_helper.exe',helper)]:
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
    def configure_physical_layout(self,paths,*,move=True,instroot=None):
        source,runtime,_,_,_=paths
        physical=source/'instdir'
        if move:
            for old,name in [('workdir/LinkTarget/Library/spsupp_x86.dll','spsupp_x86.dll'),
                             ('workdir/LinkTarget/Executable/spsupp_helper.exe','spsupp_helper.exe')]:
                target=physical/'program'/name;target.parent.mkdir(parents=True,exist_ok=True)
                if (source/old).exists():(source/old).rename(target)
                else:self.assertTrue(target.is_file())
        (source/'config_host.mk').write_text('OS=WNT\nCPUNAME=X86_64\nCOM=MSC\nCXX_X86_BINARY=owned-synthetic-compiler\n'
            +'SRCDIR='+str(source)+'\nINSTROOT='+str(physical if instroot is None else instroot)
            +'\nLIBO_LIB_FOLDER=program\nLIBO_BIN_FOLDER=program\n')
    def test_real_gbuild_physical_outputs_are_used_without_logical_pe_aliases(self):
        paths=self.fixture('physical-layout');self.configure_physical_layout(paths)
        self.assertEqual(self.run_capture(paths),0)
        self.assertFalse((paths[0]/'workdir/LinkTarget/Library/spsupp_x86.dll').exists())
    def test_instroot_cannot_alias_the_separately_staged_runtime(self):
        paths=self.fixture('same-root');self.configure_physical_layout(paths,move=False,instroot=paths[1])
        self.assertNotEqual(self.run_capture(paths),0)
        self.assertFalse((paths[-1]/'source-companion-proof.json').exists())
    def test_missing_installed_helper_records_exact_role_without_raw_exception(self):
        paths=self.fixture('missing-helper');(paths[1]/'program/spsupp_helper.exe').unlink()
        self.assertNotEqual(self.run_capture(paths),0)
        d=json.loads((paths[-1]/'source-companion-failure.json').read_text())
        self.assertEqual(d['diagnostic']['fileRoleCode'],2)
        self.assertEqual(d['diagnostic']['readCompleteMask'],1)
        self.assertEqual(d['diagnostic']['exceptionTypeCode'],2)
        self.assertNotIn('exceptionMessage',d['diagnostic'])
    def test_exact_source_and_owned_partial_component_capture(self):
        paths=self.fixture('valid');self.assertEqual(self.run_capture(paths),0)
        p=json.loads((paths[-1]/'source-companion-proof.json').read_text())
        self.assertEqual(p['role'],'x86CompatibilityHelper');self.assertIs(p['fullEngineQualified'],False)
        self.assertIs(p['acceptanceEligible'],False);self.assertEqual(len(p['sourceProofs']),13)
    def test_changed_source_or_linktarget_never_emits_a_component_proof(self):
        for kind in ('source','target'):
            with self.subTest(kind=kind):
                paths=self.fixture(kind);path=paths[0]/('shell/Library_spsupp_x86.mk' if kind=='source' else 'instdir/program/spsupp_x86.dll')
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

    def test_static_runtime_original_effective_or_foreign_run_sources_cannot_be_substituted(self):
        for kind in ('original','effective','current','foreign','omitted','aliased-context','aliased-original','foreign-compiler'):
            with self.subTest(kind=kind):
                paths=self.fixture('crt-'+kind);context=json.loads(paths[3].read_text());rows=context['x86StaticRuntimeEvidence']
                if kind in ('original','effective'):target=Path(rows[0][kind]);target.write_bytes(target.read_bytes()+b'x')
                elif kind=='current':target=paths[0]/rows[0]['path'];target.write_bytes(target.read_bytes()+b'x')
                elif kind=='foreign':
                    previous=self.root/'previous';previous.mkdir()
                    for row in rows:
                        for side in ('original','effective'):
                            old=Path(row[side]);new=previous/old.name;shutil.copy2(old,new);row[side]=str(new)
                elif kind=='omitted':rows.pop()
                elif kind=='aliased-context':context['sourceEvidenceDirectory']=str(paths[-1])+'/./source-recipe'
                elif kind=='foreign-compiler':
                    config=paths[0]/'config_host.mk';config.write_text(config.read_text().replace('COM=MSC','COM=GCC'))
                else:rows[0]['original']=str(Path(rows[0]['original']).parent)+'/./'+Path(rows[0]['original']).name
                paths[3].write_text(json.dumps(context));self.assertNotEqual(self.run_capture(paths),0)
                self.assertFalse((paths[-1]/'source-companion-proof.json').exists())
