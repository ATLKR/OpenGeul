"""Failed Source61 bytes can diagnose the whole password suite, never qualify it."""
from pathlib import Path
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'e2e'), str(ROOT/'tests')]
from buildkit import manifest, DEV_IDENTITY
import releasekit
import test_windows_components as fixtures
SPEC = importlib.util.spec_from_file_location('package61_transport', ROOT/'probe/download-package61.py')
transport = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)

def checksum(folder):
    (folder/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n'
        for p in sorted(folder.iterdir()) if p.name!='SHA256SUMS.txt'))

def zip_folder(folder, path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(folder.rglob('*')):
            if p.is_file(): archive.write(p,p.relative_to(folder).as_posix())
    return path

class Password61TransportTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.run={'id':38161639847,'head_sha':'9b666ea2ac3210a6219ca9d78b9da96719b43856','run_attempt':1,
            'run_number':61,'event':'push','head_branch':'main','path':'.github/workflows/msix.yml',
            'status':'completed','conclusion':'failure','repository':{'id':42,'full_name':'ATLKR/OpenGeul','private':False},
            'head_repository':{'id':42,'full_name':'ATLKR/OpenGeul','private':False}}
        self.jobs=[{'id':i,'run_id':38161639847,'run_attempt':1,'head_sha':self.run['head_sha'],
            'name':n,'status':'completed','conclusion':'success'} for n,i in [('wasm',114535716813),('build',114545338430)]]

    def metadata(self,spec):
        return {'id':spec['id'],'name':spec['name'],'size_in_bytes':spec['size'],'digest':'sha256:'+spec['sha256'],
            'expired':False,'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
            'workflow_run':{'id':38161639847,'head_sha':self.run['head_sha'],'head_branch':'main',
                            'repository_id':42,'head_repository_id':42}}

    def inputs(self):
        fixture=fixtures.WindowsComponentsTests('test_same_run_components_restore_complete_payload_and_exact_ledger')
        fixture.setUp();self.addCleanup(fixture.doCleanups);source=fixture.source()
        wasm=source/'apps/studio-host/vendor/rhwp-core'
        for p in wasm.iterdir():
            if p.name not in set(transport.wasm_artifacts.FILES)|{'OPEN_GEUL_WASM.json'}:p.unlink()
        package=self.root/'input-package';package.mkdir()
        pe=bytearray(256);pe[:2]=b'MZ';pe[60:64]=(128).to_bytes(4,'little');pe[128:132]=b'PE\0\0';pe[132:134]=(0x8664).to_bytes(2,'little')
        editor=bytes(pe);pe[-1]=1;cli=bytes(pe)
        runtimes={'editor':{'path':'OpenGeul.exe','size':len(editor),'sha256':hashlib.sha256(editor).hexdigest()},
                  'cli':{'path':'Tools/rhwp.exe','size':len(cli),'sha256':hashlib.sha256(cli).hexdigest()}}
        payload={'OpenGeul.exe':editor,'Tools/rhwp.exe':cli,'AppxManifest.xml':manifest(DEV_IDENTITY,'1.1.2').encode(),
                 'Notices/OpenGeul-LICENSE.txt':b'MIT','WebView2Loader.dll':b'owned-loader'}
        msix=package/transport.PACKAGE_NAME
        with zipfile.ZipFile(msix,'w') as z:
            for name,data in payload.items():z.writestr(name,data)
            z.writestr('AppxBlockMap.xml',b'<BlockMap/>');z.writestr('[Content_Types].xml',b'<Types/>')
        with zipfile.ZipFile(package/transport.PORTABLE_NAME,'w') as z:
            for name,data in payload.items():z.writestr(name,data)
        (package/'AppxManifest.xml').write_bytes(payload['AppxManifest.xml']);(package/'rhwp-help.txt').write_text('rhwp usage')
        receipt={'formatVersion':1,**transport.IDENTITY,'sourceContractSha256':transport.SOURCE_CONTRACT_SHA256,'components':{}}
        for role,record in runtimes.items():
            receipt['components'][role]={'artifactName':f'opengeul-{role}-component-{transport.RUN_ID}',
                'runAttempt':'1','provenanceSha256':transport.COMPONENT_PROVENANCE[role],
                'runtime':record['path'],'size':record['size'],'sha256':record['sha256']}
        (source/'.opengeul-windows-components.json').write_text(json.dumps(receipt))
        env={'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_SHA':transport.SOURCE,'GITHUB_RUN_ID':str(transport.RUN_ID),'GITHUB_RUN_ATTEMPT':'1'}
        with patch.dict(os.environ,env):releasekit.finish(package,source,require_components=True)
        ledger=json.loads((source/'.opengeul-overlay.json').read_text())
        for item in [patch.object(transport,'RUNTIMES',runtimes),patch.object(transport,'LEDGER_CANONICAL_SHA256',hashlib.sha256(transport.components.encoded(ledger)).hexdigest())]:
            item.start();self.addCleanup(item.stop)
        return package,wasm,payload

    def test_failed_source_and_exact_successful_package_wasm_jobs_are_required(self):
        self.assertEqual(set(transport.validate_run(self.run,self.jobs)),{'wasm','build'})
        for key,value in [('run_attempt',2),('conclusion','success'),('head_sha','a'*40),('run_number',59)]:
            altered=copy.deepcopy(self.run);altered[key]=value
            with self.assertRaises(ValueError):transport.validate_run(altered,self.jobs)
        for key,value in [('run_attempt',2),('run_attempt',True),('head_sha','a'*40),('id',11),('conclusion','failure')]:
            jobs=copy.deepcopy(self.jobs);jobs[1][key]=value
            with self.assertRaises(ValueError):transport.validate_run(self.run,jobs)

    def test_artifact_api_identity_expiry_and_origin_are_strict(self):
        spec=transport.ARTIFACTS['package'];metadata=self.metadata(spec);transport.validate_artifact(metadata,spec,42)
        for key,value in [('id',1),('size_in_bytes',1),('digest','sha256:'+'0'*64),('expired',True),('expires_at','2000-01-01T00:00:00Z')]:
            changed=copy.deepcopy(metadata);changed[key]=value
            with self.assertRaises(ValueError):transport.validate_artifact(changed,spec,42)
        changed=copy.deepcopy(metadata);changed['workflow_run']['head_sha']='a'*40
        with self.assertRaises(ValueError):transport.validate_artifact(changed,spec,42)

    def test_archive_hash_cap_and_safe_inventory_precede_extraction(self):
        for name,mode in [('../escape',0),('link',stat.S_IFLNK<<16)]:
            raw=self.root/'bad.zip'
            with zipfile.ZipFile(raw,'w') as z:
                entry=zipfile.ZipInfo(name);entry.external_attr=mode;z.writestr(entry,b'bad')
            spec={'size':raw.stat().st_size,'sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'expandedLimit':128*1024*1024,'archiveLimit':64*1024*1024}
            with self.assertRaises(ValueError):transport.extract_verified_archive(raw,spec,self.root/'output')
            self.assertFalse((self.root/'output').exists())
        changed=dict(spec,sha256='0'*64)
        with self.assertRaises(ValueError):transport.extract_verified_archive(raw,changed,self.root/'output')
        changed=dict(spec,archiveLimit=1)
        with self.assertRaises(ValueError):transport.extract_verified_archive(raw,changed,self.root/'output')

    def test_real_msix_portable_checksums_receipt_and_runtime_pass(self):
        package,wasm,_=self.inputs();output=self.root/'runtime'
        result=transport.validate_inputs(package,wasm,output)
        self.assertEqual(result['runtime']['editor']['sha256'],transport.RUNTIMES['editor']['sha256'])
        self.assertEqual(result['wasmRebuild']['artifacts'],result['wasmArtifacts'])
        self.assertEqual((output/'OpenGeul.exe').stat().st_size,256)

    def test_non_executable_portable_mismatch_still_rejects_equal_editor(self):
        package,wasm,payload=self.inputs();payload['WebView2Loader.dll']=b'different'
        with zipfile.ZipFile(package/transport.PORTABLE_NAME,'w') as z:
            for name,data in payload.items():z.writestr(name,data)
        checksum(package)
        with self.assertRaises(ValueError):transport.validate_inputs(package,wasm,self.root/'runtime')
        self.assertFalse((self.root/'runtime').exists())

    def test_package_source_ledger_receipt_and_runtime_substitutions_reject(self):
        package,wasm,_=self.inputs();p=package/'provenance.json';original=p.read_bytes()
        for mutate in [lambda v:v.update(commit='a'*40),lambda v:v['windowsComponents'].update(runAttempt='2'),
                       lambda v:v['sourceParity'].update(version='wrong'),lambda v:v['windowsComponents']['components']['cli'].update(sha256='0'*64)]:
            value=json.loads(original);mutate(value);p.write_text(json.dumps(value));checksum(package)
            with self.assertRaises(ValueError):transport.validate_inputs(package,wasm,self.root/'runtime')
            self.assertFalse((self.root/'runtime').exists())
        p.write_bytes(original);checksum(package)
        with patch.object(transport,'RUNTIMES',{**transport.RUNTIMES,'cli':{**transport.RUNTIMES['cli'],'sha256':'0'*64}}):
            with self.assertRaises(ValueError):transport.validate_inputs(package,wasm,self.root/'runtime')

    def test_missing_extra_outer_file_and_wasm_tamper_reject(self):
        package,wasm,_=self.inputs();(package/'unlisted.txt').write_text('extra');checksum(package)
        with self.assertRaises(ValueError):transport.validate_inputs(package,wasm,self.root/'runtime')
        (package/'unlisted.txt').unlink();checksum(package);(wasm/'rhwp.js').write_text('changed')
        with self.assertRaises(ValueError):transport.validate_inputs(package,wasm,self.root/'runtime')

    def test_success_promotes_only_verified_inputs_without_running_app(self):
        package,wasm,_=self.inputs();archives={'package':zip_folder(package,self.root/'package.zip'),'wasm':zip_folder(wasm,self.root/'wasm.zip')}
        specs={role:{'id':i,'name':'owned-'+role,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                     'archiveLimit':64*1024*1024,'expandedLimit':128*1024*1024} for i,(role,p) in enumerate(archives.items(),1)}
        metadata={role:self.metadata(s) for role,s in specs.items()}
        def gh(endpoint):
            if endpoint.endswith(f'/runs/{transport.RUN_ID}'):return self.run
            if '/jobs?' in endpoint:return {'total_count':2,'jobs':self.jobs}
            if '/artifacts?' in endpoint:return {'total_count':2,'artifacts':list(metadata.values())}
            return metadata['package' if endpoint.endswith('/1') else 'wasm']
        def download(spec,path):shutil.copyfile(archives['package' if spec['id']==1 else 'wasm'],path)
        target=self.root/'diagnostic';target.mkdir()
        with patch.object(transport,'ARTIFACTS',specs),patch.object(transport,'gh_json',side_effect=gh),patch.object(transport,'download_archive',side_effect=download),patch.object(transport.subprocess,'run',side_effect=AssertionError('Never execute app')):
            receipt=transport.prepare(target)
        self.assertTrue(receipt['diagnosticOnly']);self.assertFalse(receipt['sourceQualified']);self.assertFalse(receipt['fullSourceQualified'])
        self.assertEqual(receipt['producerConclusion'],'failure');self.assertTrue((target/'runtime/Tools/rhwp.exe').is_file())

    def test_failed_producer_and_stale_output_block_downloads(self):
        jobs=copy.deepcopy(self.jobs);jobs[1]['conclusion']='failure'
        def gh(endpoint):
            if '/jobs?' in endpoint:return {'total_count':2,'jobs':jobs}
            return self.run
        with patch.object(transport,'gh_json',side_effect=gh),patch.object(transport,'download_archive') as download:
            with self.assertRaises(ValueError):transport.prepare(self.root)
            download.assert_not_called()
        (self.root/'package').mkdir()
        with patch.object(transport,'gh_json') as gh:
            with self.assertRaises(ValueError):transport.prepare(self.root)
            gh.assert_not_called()

    def test_sas_stderr_is_never_exposed(self):
        result=subprocess.CompletedProcess([],1,stdout=b'private',stderr=b'signed URL secret')
        with patch.object(transport.subprocess,'run',return_value=result):
            with self.assertRaisesRegex(ValueError,'^GitHub metadata request failed$'):transport.gh_json('owned')
        with patch.object(transport,'prepare',side_effect=RuntimeError('signed URL secret')),patch.object(sys,'argv',['download-package61.py']),patch('sys.stderr',new_callable=io.StringIO) as error:
            self.assertEqual(transport.main(),1);self.assertEqual(error.getvalue(),'Package61 diagnostic input verification failed.\n')

class Password61WrapperTests(unittest.TestCase):
    def wrapper(self):
        path=ROOT/'probe/password-suite61.py';self.assertTrue(path.is_file(),'Missing full-suite diagnostic wrapper')
        spec=importlib.util.spec_from_file_location('password61_wrapper',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_all_eight_original_results_are_labelled_diagnostic_and_failed_source(self):
        wrapper=self.wrapper()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'evidence').mkdir()  # The verified downloader creates this receipt directory.
            def native(args):
                self.assertEqual(args.expected_source,transport.SOURCE);self.assertEqual(args.expected_run,str(transport.RUN_ID))
                args.output.mkdir(parents=True)
                value={'sourceCommit':transport.SOURCE,'buildRunId':str(transport.RUN_ID),'editorSha256':transport.RUNTIMES['editor']['sha256'],
                    'cliSha256':transport.RUNTIMES['cli']['sha256'],'mode':'native-password','expectedTests':8,
                    'tests':[{'test':name,'status':'passed'} for name in wrapper.CASES],'success':True}
                (args.output/'results.json').write_text(json.dumps(value));return SimpleNamespace(run=lambda:0)
            metadata={'diagnosticOnly':True,'sourceQualified':False,'fullSourceQualified':False,'compiledSourceCommit':transport.SOURCE,
                'sourceRun':transport.RUN_ID,'sourceRunConclusion':'failure','helperCommit':'a'*40,'nativeHelperSha256':'b'*64}
            with patch.object(wrapper,'validate_context',return_value=metadata),patch.object(wrapper,'load_native',return_value=SimpleNamespace(Qualification=native)):
                self.assertEqual(wrapper.run(root),0)
            value=json.loads((root/'evidence/password-native/results.json').read_text())
            self.assertTrue(value['diagnosticOnly']);self.assertFalse(value['fullSourceQualified']);self.assertEqual(len(value['tests']),8)
            self.assertEqual(value['diagnostic']['sourceRunConclusion'],'failure')

    def test_incomplete_or_duplicate_eight_case_results_cannot_pass(self):
        wrapper=self.wrapper()
        for names in [wrapper.CASES[:-1],[*wrapper.CASES[:-1],wrapper.CASES[0]]]:
            value={'sourceCommit':transport.SOURCE,'buildRunId':str(transport.RUN_ID),'editorSha256':transport.RUNTIMES['editor']['sha256'],
                'cliSha256':transport.RUNTIMES['cli']['sha256'],'mode':'native-password','expectedTests':8,'tests':[{'test':name,'status':'passed'} for name in names],'success':True}
            with self.assertRaises(ValueError):wrapper.validate_results(value,0)

    def test_original_failure_is_preserved_even_if_result_claims_success(self):
        wrapper=self.wrapper();value={'sourceCommit':transport.SOURCE,'buildRunId':str(transport.RUN_ID),'editorSha256':transport.RUNTIMES['editor']['sha256'],
            'cliSha256':transport.RUNTIMES['cli']['sha256'],'mode':'native-password','expectedTests':8,'tests':[{'test':name,'status':'passed'} for name in wrapper.CASES],'success':True}
        with self.assertRaises(ValueError):wrapper.validate_results(value,1)

    def context(self, wrapper, root):
        (root/'evidence').mkdir();(root/'e2e/password').mkdir(parents=True)
        shutil.copyfile(ROOT/'e2e/password/native.py',root/'e2e/password/native.py')
        shutil.copyfile(ROOT/'e2e/driver.py',root/'e2e/driver.py')
        runtimes={}
        for role,record in wrapper.transport.RUNTIMES.items():
            path=root/'runtime'/record['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(role.encode())
            runtimes[role]={**record,'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        receipt={'qualification':'native-password-diagnostic-only','diagnosticOnly':True,'qualifiedPackage':False,
            'sourceQualified':False,'fullSourceQualified':False,'sourceCommit':transport.SOURCE,'sourceRun':transport.RUN_ID,
            'producerAttempt':1,'producerConclusion':'failure','runtime':runtimes,
            'artifacts':{role:{'id':s['id'],'name':s['name'],'bytes':s['size'],'sha256':s['sha256']} for role,s in transport.ARTIFACTS.items()}}
        (root/'evidence/source.json').write_text(json.dumps(receipt))
        env={'GITHUB_REPOSITORY':transport.REPOSITORY,'GITHUB_REF':'refs/heads/diagnostic/native-password-61',
             'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1',
             'DIAGNOSTIC_OS':'windows-2022'}
        return receipt,runtimes,env

    def test_real_context_keeps_compiled_and_diagnostic_identities_distinct(self):
        wrapper=self.wrapper()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);receipt,runtimes,env=self.context(wrapper,root)
            with patch.object(wrapper.transport,'RUNTIMES',runtimes),patch.dict(os.environ,env):
                value=wrapper.validate_context(root)
            self.assertEqual(value['compiledSourceCommit'],transport.SOURCE)
            self.assertEqual(value['helperCommit'],'a'*40)
            self.assertEqual(value['nativeHelperSha256'],wrapper.NATIVE_SHA256)
            self.assertFalse(value['fullSourceQualified']);self.assertEqual(value['sourceRunConclusion'],'failure')

    def test_helper_runtime_and_receipt_tampering_block_before_gui(self):
        wrapper=self.wrapper()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);receipt,runtimes,env=self.context(wrapper,root)
            with patch.object(wrapper.transport,'RUNTIMES',runtimes),patch.dict(os.environ,env),patch.object(wrapper,'load_native') as native:
                for key,value in [('fullSourceQualified',True),('sourceRun',59),('producerConclusion','success')]:
                    changed=copy.deepcopy(receipt);changed[key]=value;(root/'evidence/source.json').write_text(json.dumps(changed))
                    with self.assertRaises(ValueError):wrapper.run(root)
                (root/'evidence/source.json').write_text(json.dumps(receipt))
                path=root/'runtime/OpenGeul.exe';original=path.read_bytes();path.write_bytes(b'changed')
                with self.assertRaises(ValueError):wrapper.run(root)
                path.write_bytes(original);(root/'e2e/password/native.py').write_text('different helper')
                with self.assertRaises(ValueError):wrapper.run(root)
                native.assert_not_called();self.assertFalse((root/'evidence/password-native').exists())

    def test_wrong_branch_source_checkout_runner_or_attempt_block_before_gui(self):
        wrapper=self.wrapper()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);receipt,runtimes,env=self.context(wrapper,root)
            with patch.object(wrapper.transport,'RUNTIMES',runtimes),patch.object(wrapper,'load_native') as native:
                for key,value in [('GITHUB_REF','refs/heads/main'),('GITHUB_SHA',transport.SOURCE),
                                  ('DIAGNOSTIC_OS','self-hosted'),('GITHUB_RUN_ATTEMPT','0')]:
                    with patch.dict(os.environ,{**env,key:value}):
                        with self.assertRaises(ValueError):wrapper.run(root)
                native.assert_not_called()

if __name__=='__main__':unittest.main()
