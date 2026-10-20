"""Suite integration contracts only; no local native desktop qualification."""
import copy
import importlib.util
import json
import hashlib
import shutil
import re
import time
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from suite.tests.test_calc_matrix_workflow import workflow_steps, field, run_code

ROOT=Path(__file__).resolve().parents[2]
ADAPTER=ROOT/'e2e/native31_suite_prepare.py'
CALLER=ROOT/'suite/scripts/prepare-native31.ps1'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

class SuitePreparationContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ADAPTER.is_file(),'Explicit Suite adapter is missing')
        self.m=load('suite_prepare_test',ADAPTER)
        self.core=load('suite_control_test',ROOT/'e2e/native31_desktop_control.py')
        self.env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Windows',RUNNER_ARCH='ARM64',
            GITHUB_REPOSITORY='ATLKR/OpenGeul',GITHUB_EVENT_NAME='push',GITHUB_JOB='windows-suite',
            GITHUB_REF=self.m.BRANCH,GITHUB_WORKFLOW_REF=self.m.WORKFLOW,GITHUB_SHA='a'*40,
            GITHUB_WORKFLOW_SHA='a'*40,GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',GITHUB_ACTOR='ATLKR',GITHUB_ACTOR_ID='65988341')
        self.event=dict(repository=dict(full_name='ATLKR/OpenGeul',id=123,private=False),
            sender=dict(login='ATLKR',id=65988341,type='User'),ref=self.m.BRANCH,deleted=False,after='a'*40)
        self.native=dict(processId=45,processMachine=0,nativeMachine=0xAA64,sessionId=1)

    def test_exact_suite_context_is_explicit_without_spoofing_defaults(self):
        before=copy.deepcopy(self.env);binding=self.m.control_binding(self.core)
        self.core.validate_execution(self.env,self.event,self.native,'nt',prepare_privacy=True,binding=binding)
        self.assertEqual(self.env,before)
        for prepare in (True,False):
            with self.assertRaises(ValueError):self.core.validate_execution(self.env,self.event,self.native,'nt',prepare_privacy=prepare)
        with self.assertRaises(ValueError):self.core.validate_execution(self.env,self.event,self.native,'nt',binding=binding)
        self.assertEqual(binding.observer_entry,'e2e/native31_suite_prepare.py')
        for name in ('e2e/native31_suite_prepare.py','.github/workflows/office-suite.yml','suite/scripts/prepare-native31.ps1'):
            self.assertIn(name,binding.additional_source_files)
        for key,bad in [('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_REF','refs/heads/work/opengeul-office-suite'),
                        ('GITHUB_JOB','prepare'),('GITHUB_ACTOR','other'),('GITHUB_WORKFLOW_SHA','b'*40),('GITHUB_RUN_ATTEMPT','2')]:
            with self.subTest(key=key):
                env={**self.env,key:bad}
                with self.assertRaises(ValueError):self.m.validate_context(env,self.event,'arm64','nt')
                with self.assertRaises(ValueError):self.core.validate_execution(env,self.event,self.native,'nt',prepare_privacy=True,binding=binding)

    def test_arm_delegation_passes_binding_and_never_rebuilds_controller_budget(self):
        fake=SimpleNamespace(ControlBinding=self.core.ControlBinding,controller=lambda args,**kw:seen.append(('controller',args,kw)) or 0,
            observer=lambda args,**kw:seen.append(('observer',args,kw)) or 0)
        for observer in (False,True):
            seen=[];args=SimpleNamespace(architecture='arm64',observer=observer,deadline=123 if observer else None,prepare_privacy=True,output=Path('/unused'))
            with patch.object(self.m,'load_control',return_value=fake),patch.object(self.m,'read_event',return_value=self.event),patch.dict(os.environ,self.env):
                result=self.m.arm_entry(args,platform='nt')
            self.assertEqual(result,0);self.assertEqual(len(seen),1);self.assertIs(seen[0][1],args)
            self.assertEqual(seen[0][0],'observer' if observer else 'controller');self.assertEqual(seen[0][2]['binding'],self.m.control_binding(fake))

    def test_new_workflow_boundary_exists_after_servicing_before_fixtures(self):
        steps=workflow_steps()
        preparation=next(step for step in steps if field(step,'id')=='native31-privacy-prepare')
        index=steps.index(preparation);upload=steps[index+1]
        def setting(step,name):
            # Existing field parser applied to the nested "with" indentation.
            return field('\n'.join(line[2:] for line in step.splitlines()),name)
        def paths(step):
            match=re.search(r'^        path: \|\n((?:          .*\n)+)',step,re.M)
            self.assertIsNotNone(match,'Upload has no literal path block')
            return match.group(1)
        self.assertIn('suite-korean-readiness',setting(steps[index-1],'name'))
        self.assertEqual(field(steps[index+2],'id'),'fixtures');self.assertEqual(field(preparation,'timeout-minutes'),'3')
        self.assertIn(self.m.BRANCH,field(preparation,'if'));self.assertNotIn('matrix.architecture',field(preparation,'if'))
        self.assertIn('always()',field(upload,'if'));self.assertIn(self.m.BRANCH,field(upload,'if'))
        self.assertEqual(setting(upload,'retention-days'),'7');self.assertEqual(setting(upload,'include-hidden-files'),'true')
        self.assertIn('suite-native31-setup-',paths(upload));self.assertIn('suite-native31-privacy-preparation-',paths(upload))
        aggregate=next(step for step in steps if (setting(step,'name') or '').startswith('opengeul-suite-evidence-'))
        self.assertIn('.work/suite-native31-privacy-preparation/',paths(aggregate))
        self.assertNotIn('runner.temp',paths(aggregate))


    def test_workflow_contracts_run_without_site_packages(self):
        names = ['suite.tests.test_native31_suite_preparation.SuitePreparationContracts.test_new_workflow_boundary_exists_after_servicing_before_fixtures',
                 'suite.tests.test_native31_suite_preparation.PowerShellPreparationContracts.test_real_workflow_command_preserves_preparation_and_staging_failures']
        code = ("import importlib.util,sys,unittest; assert importlib.util.find_spec('yaml') is None; "
                "suite=unittest.defaultTestLoader.loadTestsFromNames(" + repr(names) + "); "
                "result=unittest.TextTestRunner(verbosity=2).run(suite); "
                "sys.exit(0 if result.wasSuccessful() and result.testsRun==2 and not result.skipped else 1)")
        run = subprocess.run([sys.executable, '-S', '-B', '-c', code], cwd=ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout)

    def test_x64_native_not_applicable_is_bound_and_imports_no_arm_module(self):
        self.env['RUNNER_ARCH']='X64'
        with tempfile.TemporaryDirectory() as temp:
            args=SimpleNamespace(output=Path(temp)/'capture',observer=False,deadline=None)
            native=dict(processId=45,processMachine=0,nativeMachine=0x8664,peMachine=0x8664,sessionId=1)
            with patch.dict(os.environ,{**self.env,'RUNNER_TEMP':temp}),patch.object(self.m,'read_event',return_value=self.event), \
                 patch.object(self.m,'load_control',side_effect=AssertionError('x64 must not import ARM control')):
                result=self.m.x64_entry(args,platform='nt',native_reader=lambda:native,
                    source_reader=lambda root,sha:{'head':sha,'tree':'b'*40,'files':{'adapter':'c'*64}})
            self.assertEqual(result,0);receipt=json.loads((args.output/'99-not-applicable.json').read_text())
            self.assertEqual(receipt['status'],'not-applicable');self.assertTrue(receipt['readOnly'])
            for key in ('inputsPerformed','closeRequests','physicalPointerGateInvocations'):self.assertEqual(receipt[key],0)
            for key in ('privacyPreparationQualified','physicalTaskbarGatePassed','hostReadyQualified','productQualified','productExecuted'):self.assertFalse(receipt[key])
            self.assertEqual(receipt['consentActions'],[]);self.assertEqual(receipt['sourceCommit'],self.env['GITHUB_SHA'])

    def test_x64_wrong_self_architecture_fails_without_action(self):
        self.env['RUNNER_ARCH']='X64'
        with tempfile.TemporaryDirectory() as temp:
            args=SimpleNamespace(output=Path(temp)/'capture',observer=False,deadline=None)
            with patch.dict(os.environ,{**self.env,'RUNNER_TEMP':temp}),patch.object(self.m,'read_event',return_value=self.event):
                result=self.m.x64_entry(args,platform='nt',native_reader=lambda:{**self.native,'peMachine':0xAA64},
                    source_reader=lambda *args:(_ for _ in ()).throw(AssertionError('wrong architecture must fail before source success')))
            self.assertEqual(result,1);receipt=json.loads((args.output/'99-not-applicable.json').read_text())
            self.assertEqual(receipt['actions'],[]);self.assertFalse(receipt['success'])

    def test_core_controller_owns_suite_observer_argv_with_original_budget_and_environment(self):
        core=self.core;binding=self.m.control_binding(core);seen=[]
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'capture';event=Path(temp)/'event.json';event.write_text(json.dumps(self.event))
            env={**self.env,'RUNNER_TEMP':temp,'GITHUB_EVENT_PATH':str(event)}
            host={**self.native,'process':{'createdFileTime':100},'windowsDirectory':r'C:\Windows'}
            class Owner:
                def __init__(self,probe,environment,argv,budget,expected):
                    self.created=False;self.environment=environment;self.argv=argv;self.budget=budget;self.expected=expected;seen.append(self)
                def create_suspended(self):self.created=True
                def assign(self):pass
                def identity(self):return {'processId':45,'argv':self.argv,'deadline':self.budget.deadline}
                def resume(self):pass
                def wait(self,seconds):
                    evidence=core.Evidence(output,max_files=72)
                    source={'head':env['GITHUB_SHA'],'tree':'b'*40,'dirty':False,'files':self.expected['sourceFiles']}
                    evidence.write('32-observer-context',{'source':source})
                    evidence.write('80-classification',{**core.flags(),'status':'privacy-absent-observed'})
                    evidence.write('p49-preparation',{**core.flags(prepare_privacy=True),'privacyPreparationQualified':True,
                        'physicalTaskbarGatePassed':True,'inputsPerformed':1,'physicalPointerGateInvocations':1})
                    return True
                def exit_code(self):return 0
                def descendants_empty(self):return True
                def close(self):pass
            fake_os=SimpleNamespace(**{**vars(os),'name':'nt','environ':env})
            with patch.object(core,'os',fake_os),patch.object(core,'Probe',return_value=SimpleNamespace(identity=lambda:host)), \
                 patch.object(core,'image_receipt',return_value={'peMachine':0xAA64,'imageBytes':1,'imageSha256':'c'*64}), \
                 patch.object(core,'OwnedObserver',Owner):
                code=core.controller(SimpleNamespace(output=output,prepare_privacy=True),binding=binding)
            self.assertEqual(code,0);self.assertEqual(len(seen),1);owner=seen[0]
            self.assertEqual(owner.argv[2],str(ROOT/'e2e/native31_suite_prepare.py'))
            self.assertIn('--prepare-privacy',owner.argv)
            self.assertEqual(float(owner.argv[owner.argv.index('--deadline')+1]),owner.budget.deadline)
            for key in ('GITHUB_REF','GITHUB_JOB','GITHUB_WORKFLOW_REF'):self.assertEqual(owner.environment[key],env[key])
            self.assertIn('suite/scripts/prepare-native31.ps1',owner.expected['sourceFiles'])
            self.assertTrue(json.loads((output/'99-result.json').read_text())['privacyPreparationQualified'])

    def test_observer_keeps_absolute_deadline_and_injects_only_additional_source_receipt(self):
        core=self.core;binding=self.m.control_binding(core);seen=[]
        class Session:
            def __init__(self,c,probe,evidence,budget,controller,classification,**kwargs):
                seen.append((budget.deadline,kwargs['source_receipt'](budget)))
            def run(self):pass
        with tempfile.TemporaryDirectory() as temp:
            evidence=core.Evidence.create(Path(temp)/'capture',Path(temp),max_files=72);evidence.write('10-controller',{})
            deadline=core.Budget().deadline
            with patch.object(core,'Probe'),patch.object(core,'capture',return_value={'status':'privacy-absent-observed'}) as capture, \
                 patch.object(core,'privacy_preparation_module',return_value=SimpleNamespace(PreparationSession=Session)), \
                 patch.object(core,'source_receipt',side_effect=lambda budget,**kw:{'deadline':budget.deadline,**kw}):
                code=core.observer(SimpleNamespace(output=evidence.path,deadline=deadline,prepare_privacy=True),binding=binding)
            self.assertEqual(code,0);self.assertEqual(seen,[(deadline,{'deadline':deadline,'additional_files':binding.additional_source_files})])
            self.assertIs(capture.call_args.kwargs['binding'],binding)

class PowerShellPreparationContracts(unittest.TestCase):
    def setUp(self):
        self.pwsh=shutil.which('pwsh')
        if not self.pwsh:self.skipTest('PowerShell is required for actual script boundaries')
        self.m=load('suite_prepare_ps_test',ADAPTER)

    def critical_fixture_files(self):
        return ('e2e/native31_desktop_control.py','e2e/runner-ready.py','ci/policy.py',
            '.github/workflows/office-native31-desktop-control.yml','e2e/native31_privacy_prepare.py',
            '.github/workflows/office-native31-privacy-prepare.yml','suite/e2e/native_window_evidence.py',*self.m.ADDITIONAL_SOURCE_FILES)

    def assert_committed_fixture_bytes(self,root,sha):
        for name in self.critical_fixture_files():
            working=(root/name).read_bytes()
            blob=subprocess.check_output(['git','-C',str(root),'show',sha+':'+name],stderr=subprocess.PIPE)
            self.assertTrue(working==blob,
                f'Fixture {name} working bytes differ from Git blob {sha}: '
                f'working={len(working)}/{hashlib.sha256(working).hexdigest()} '
                f'committed={len(blob)}/{hashlib.sha256(blob).hexdigest()}')

    def repository(self,folder):
        root=folder/'main';root.mkdir()
        for name in self.critical_fixture_files():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
        (root/'.gitattributes').write_bytes(b'* text eol=lf\n');(root/'.gitignore').write_bytes(b'.work/\ndist/\n')
        def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
        git('init','-q');git('config','user.email','test@example.invalid');git('config','user.name','Native31 contract')
        git('add','.');git('commit','-qm','fixture');sha=git('rev-parse','HEAD');self.assert_committed_fixture_bytes(root,sha);git('config','core.autocrlf','true')
        (root/'.work').mkdir();(root/'.work/engine.bin').write_bytes(b'generated engine data')
        (root/'dist').mkdir();(root/'dist/package.zip').write_bytes(b'generated package')
        temp=folder/'runner';temp.mkdir()
        return root,temp,sha,git

    def run_script(self,folder,code,env=None,timeout=45):
        script=folder/'boundary.ps1';script.write_text("$ErrorActionPreference = 'Stop'\n. '"+str(CALLER).replace("'","''")+"'\n"+code)
        return subprocess.run([self.pwsh,'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],
            cwd=folder,env={**os.environ,**(env or {})},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)

    def test_real_detached_source_excludes_generated_data_and_preserves_exact_blobs(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);root,runner,sha,git=self.repository(folder)
            hooks=folder/'evil-hooks';hooks.mkdir();marker=folder/'hook-ran'
            hook=hooks/'post-checkout';hook.write_text('#!/bin/sh\ntouch "'+str(marker)+'"\n');hook.chmod(0o755)
            git('config','core.hooksPath',str(hooks));setup=runner/'setup';setup.mkdir();source=runner/'source'
            code="""$state = @{Clock=[Diagnostics.Stopwatch]::StartNew();Commands=[Collections.Generic.List[object]]::new()}
$proof = New-Native31Source $env:TEST_ROOT $env:TEST_SOURCE $env:TEST_SETUP $state
Write-Native31Json $env:TEST_PROOF @{proof=$proof;commands=$state.Commands}
"""
            proof=folder/'proof.json';run=self.run_script(folder,code,{'GITHUB_SHA':sha,'TEST_ROOT':str(root),'TEST_SOURCE':str(source),'TEST_SETUP':str(setup),'TEST_PROOF':str(proof)})
            self.assertEqual(run.returncode,0,run.stdout);record=json.loads(proof.read_text())
            self.assertEqual(record['proof']['action']['head'],sha);self.assertEqual(record['proof']['action']['tree'],git('rev-parse','HEAD^{tree}'))
            self.assertEqual(len(record['commands']),41);self.assertLessEqual(len(record['commands']),64)
            self.assertFalse((source/'.work').exists());self.assertFalse((source/'dist').exists());self.assertFalse(marker.exists())
            self.assertTrue((source/'.git').is_file());self.assertEqual(git('config','core.autocrlf'),'true')
            for name,item in record['proof']['files'].items():
                raw=(source/name).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),item['sha256'])
                self.assertNotIn(b'\r\n',raw);self.assertEqual(raw,subprocess.check_output(['git','-C',str(root),'show',sha+':'+name]))
            entry="import importlib.util,json;from pathlib import Path;s=importlib.util.spec_from_file_location('control',Path('e2e/native31_desktop_control.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.source_receipt(m.Budget())))"
            run_source=lambda:json.loads(subprocess.check_output([sys.executable,'-B','-c',entry],cwd=source,text=True))
            self.assertFalse(run_source()['dirty']);(source/'.work').mkdir();(source/'.work/forbidden').write_text('source dirt')
            self.assertTrue(run_source()['dirty'])
            # Same target is rejected without a second worktree checkout.
            run=self.run_script(folder,code,{'GITHUB_SHA':sha,'TEST_ROOT':str(root),'TEST_SOURCE':str(source),'TEST_SETUP':str(setup),'TEST_PROOF':str(proof)})
            self.assertNotEqual(run.returncode,0);self.assertIn('reuse rejected',run.stdout)

    def test_real_git_root_identity_accepts_spelling_and_rejects_other_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);root,runner,sha,git=self.repository(folder)
            proof=folder/'identity.json'
            code="""$state = @{Clock=[Diagnostics.Stopwatch]::StartNew();Commands=[Collections.Generic.List[object]]::new()}
$identity = Get-Native31Identity $env:TEST_ROOT $state
Write-Native31Json $env:TEST_PROOF @{identity=$identity;commands=$state.Commands}
"""
            run=self.run_script(folder,code,{'TEST_ROOT':str(root)+os.sep,'TEST_PROOF':str(proof)})
            self.assertEqual(run.returncode,0,run.stdout);record=json.loads(proof.read_text())
            self.assertEqual(record['identity']['head'],sha);self.assertEqual(record['identity']['root'],str(root)+os.sep)
            self.assertEqual(record['identity']['insideWorkTree'],'true');self.assertEqual(record['identity']['prefix'],'')
            self.assertEqual(record['identity']['gitTopLevel'],git('rev-parse','--show-toplevel'))
            for mode in ('nested','outside','other-repository'):
                with self.subTest(mode=mode):
                    candidate=root/'e2e' if mode=='nested' else folder
                    if mode=='other-repository':
                        other=folder/'other';other.mkdir();candidate,_,_,_=self.repository(other)
                        subprocess.run(['git','-C',str(candidate),'commit','--allow-empty','-qm','different commit'],check=True)
                    setup=runner/(mode+'-setup');setup.mkdir();source=runner/(mode+'-source')
                    invoke="""$state = @{Clock=[Diagnostics.Stopwatch]::StartNew();Commands=[Collections.Generic.List[object]]::new()}
try { New-Native31Source $env:TEST_ROOT $env:TEST_SOURCE $env:TEST_SETUP $state }
catch { Write-Native31Json $env:TEST_FAILURE @{failure=$_.Exception.Message}; throw }
"""
                    failure=folder/(mode+'-failure.json')
                    rejected=self.run_script(folder,invoke,{'GITHUB_SHA':sha,'TEST_ROOT':str(candidate),'TEST_SOURCE':str(source),'TEST_SETUP':str(setup),'TEST_FAILURE':str(failure)})
                    self.assertNotEqual(rejected.returncode,0,rejected.stdout);self.assertFalse(source.exists())
                    self.assertIn({'nested':'working-tree root','outside':'Git setup returned failure','other-repository':'Main HEAD/tree differs'}[mode],rejected.stdout)
                    if mode=='nested':
                        message=json.loads(failure.read_text())['failure']
                        detail=json.loads(message.split(': ',1)[1])
                        self.assertEqual(detail['requestedRoot'],str(candidate))
                        self.assertEqual(detail['reportedTop'],git('rev-parse','--show-toplevel'))
                        self.assertEqual(detail['insideWorkTree'],'true');self.assertEqual(detail['prefix'],'e2e/')
                        self.assertFalse(detail['valuesTruncated'])

    def test_source_drift_and_setup_budget_fail_before_checkout(self):
        for mode in ('drift','expired'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);root,runner,sha,git=self.repository(folder);setup=runner/'setup';setup.mkdir();source=runner/'source'
                if mode=='drift':(root/'e2e/native31_suite_prepare.py').write_text('changed source')
                clock="[Diagnostics.Stopwatch]::StartNew()" if mode=='drift' else "@{Elapsed=@{TotalSeconds=31}}"
                code="$state = @{Clock="+clock+";Commands=[Collections.Generic.List[object]]::new()}\nNew-Native31Source $env:TEST_ROOT $env:TEST_SOURCE $env:TEST_SETUP $state\n"
                run=self.run_script(folder,code,{'GITHUB_SHA':sha,'TEST_ROOT':str(root),'TEST_SOURCE':str(source),'TEST_SETUP':str(setup)})
                self.assertNotEqual(run.returncode,0);self.assertFalse(source.exists())

    def test_staging_retains_bytes_and_rejects_alias_size_and_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);setup=folder/'setup';setup.mkdir();control=folder/'control';control.mkdir();stage=folder/'stage'
            (setup/'00-setup.json').write_bytes(b'{"exact": true}\r\n');(setup/'hooks').mkdir()
            (control/'99-result.json').write_bytes(b'{"success": false}\n');(control/'foreground-desktop.png').write_bytes(b'png-original-bytes')
            code='Copy-Native31Evidence $env:TEST_SETUP $env:TEST_CONTROL $env:TEST_STAGE\n'
            env={'TEST_SETUP':str(setup),'TEST_CONTROL':str(control),'TEST_STAGE':str(stage)}
            run=self.run_script(folder,code,env);self.assertEqual(run.returncode,0,run.stdout)
            inventory=json.loads((stage/'copy-inventory.json').read_text());self.assertEqual(len(inventory['files']),3)
            for row in inventory['files']:
                self.assertEqual(Path(row['original']).read_bytes(),Path(row['staged']).read_bytes())
                self.assertEqual(hashlib.sha256(Path(row['staged']).read_bytes()).hexdigest(),row['sha256'])
            self.assertFalse((stage/'setup/hooks').exists())
            run=self.run_script(folder,code,env);self.assertNotEqual(run.returncode,0)
            (control/'linked.json').symlink_to(setup/'00-setup.json')
            run=self.run_script(folder,code,{**env,'TEST_STAGE':str(folder/'linked-stage')});self.assertNotEqual(run.returncode,0)
            (control/'linked.json').unlink();(control/'oversize.json').write_bytes(b'x'*262145)
            run=self.run_script(folder,code,{**env,'TEST_STAGE':str(folder/'oversize-stage')});self.assertNotEqual(run.returncode,0)

    def test_owned_setup_process_timeout_is_finite_and_retains_partial_output(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);record=folder/'process.json'
            code="""$result = [Native31BoundedProcess]::Run($env:TEST_PYTHON, @('-c', 'import time; print("partial",flush=True); time.sleep(20)'), $env:TEST_ROOT, 3000, 8192)
Write-Native31Json $env:TEST_RECORD @{timedOut=$result.TimedOut;forced=$result.Forced;seconds=$result.Seconds;stdout=[Text.Encoding]::UTF8.GetString($result.Stdout)}
"""
            run=self.run_script(folder,code,{'TEST_PYTHON':sys.executable,'TEST_ROOT':str(folder),'TEST_RECORD':str(record)},timeout=10)
            self.assertEqual(run.returncode,0,run.stdout);value=json.loads(record.read_text())
            self.assertTrue(value['timedOut']);self.assertTrue(value['forced']);self.assertLess(value['seconds'],3.5);self.assertIn('partial',value['stdout'])

    def write_entry_stub(self,root):
        stub=root/'e2e/native31_suite_prepare.py'
        stub.write_bytes("import json,os,sys\nfrom pathlib import Path\na=sys.argv;out=Path(a[a.index('--output')+1]);out.mkdir();(out/'99-result.json').write_text(json.dumps({'partial':'original','success':False}));Path(os.environ['TEST_INVOCATION']).write_text(json.dumps({'argv':a[1:],'cwd':os.getcwd()}));raise SystemExit(int(os.environ['TEST_ENTRY_EXIT']))\n".encode('utf-8'))
        return stub

    def test_fixture_lf_bytes_match_git_under_windows_text_translation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);root,runner,sha,git=self.repository(folder)
            name='e2e/native31_suite_prepare.py';stub=root/name
            lf=stub.read_bytes();self.assertNotIn(b'\r\n',lf)
            # Controlled negative: actual working CRLF and actual normalized Git LF.
            stub.write_text(lf.decode('utf-8'),encoding='utf-8',newline='\r\n')
            git('add',name);git('commit','--allow-empty','-qm','controlled CRLF fixture')
            sha=git('rev-parse','HEAD');working=stub.read_bytes()
            blob=subprocess.check_output(['git','-C',str(root),'show',sha+':'+name])
            self.assertIn(b'\r\n',working);self.assertEqual(blob,lf);self.assertNotEqual(working,blob)
            code="""$state = @{Clock=[Diagnostics.Stopwatch]::StartNew();Commands=[Collections.Generic.List[object]]::new()}
Get-Native31SourceProof $env:TEST_ROOT $env:GITHUB_SHA $state
"""
            rejected=self.run_script(folder,code,{'TEST_ROOT':str(root),'GITHUB_SHA':sha})
            self.assertNotEqual(rejected.returncode,0);self.assertIn('Critical source bytes differ from exact commit',rejected.stdout)
            print('controlled-newline-proof '+json.dumps(dict(workingBytes=len(working),workingSha256=hashlib.sha256(working).hexdigest(),
                blobBytes=len(blob),blobSha256=hashlib.sha256(blob).hexdigest(),workingCRLF=working.count(b'\r\n'),
                blobCRLF=blob.count(b'\r\n'),strictGuardExit=rejected.returncode,strictGuardRejected=True)))
            original_write_text=Path.write_text
            def windows_write_text(path,data,*args,**kwargs):
                if kwargs.get('newline') is None:kwargs['newline']='\r\n'
                return original_write_text(path,data,*args,**kwargs)
            with patch.object(Path,'write_text',windows_write_text):self.write_entry_stub(root)
            git('add',name);git('commit','-qm','entry fixture under Windows text translation');sha=git('rev-parse','HEAD')
            blob=subprocess.check_output(['git','-C',str(root),'show',sha+':'+name])
            self.assertEqual(stub.read_bytes(),blob,'Committed fixture stub differs from working bytes under Windows text translation')
            self.assertNotIn(b'\r\n',stub.read_bytes());self.assert_committed_fixture_bytes(root,sha)
            admitted=self.run_script(folder,code,{'TEST_ROOT':str(root),'GITHUB_SHA':sha})
            self.assertEqual(admitted.returncode,0,admitted.stdout)

    def test_real_workflow_command_preserves_preparation_and_staging_failures(self):
        step=next(s for s in workflow_steps() if field(s,'id')=='native31-privacy-prepare')
        for arch,exit_code,stage_failure in (('arm64',0,False),('arm64',7,False),('arm64',0,True),('arm64',7,True),('x64',0,False)):
            with self.subTest(arch=arch,exit=exit_code,stage=stage_failure),tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);root,runner,sha,git=self.repository(folder)
                # Real PowerShell/Git/process/caller. Only the committed fixture's
                # Python action entry is a stub, so this also runs on Windows.
                stub=self.write_entry_stub(root)
                git('add','e2e/native31_suite_prepare.py');git('commit','-qm','native entry boundary fixture');sha=git('rev-parse','HEAD')
                self.assert_committed_fixture_bytes(root,sha)
                event=folder/'event.json';event.write_text(json.dumps(dict(repository=dict(full_name='ATLKR/OpenGeul',id=123,private=False),
                    sender=dict(login='ATLKR',id=65988341,type='User'),ref=self.m.BRANCH,deleted=False,after=sha)))
                if stage_failure:(root/'.work/suite-native31-privacy-preparation').mkdir()
                env={**os.environ,'PATH':str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'],'TEST_ENTRY_EXIT':str(exit_code),'TEST_INVOCATION':str(folder/'invocation.json'),
                    'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows','RUNNER_ARCH':'ARM64' if arch=='arm64' else 'X64',
                    'GITHUB_REPOSITORY':'ATLKR/OpenGeul','GITHUB_EVENT_NAME':'push','GITHUB_JOB':'windows-suite',
                    'GITHUB_REF':self.m.BRANCH,'GITHUB_WORKFLOW_REF':self.m.WORKFLOW,'GITHUB_SHA':sha,'GITHUB_WORKFLOW_SHA':sha,
                    'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','GITHUB_ACTOR':'ATLKR','GITHUB_ACTOR_ID':'65988341',
                    'GITHUB_EVENT_PATH':str(event),'GITHUB_WORKSPACE':str(root),'RUNNER_TEMP':str(runner)}
                script=folder/'workflow.ps1';script.write_text("$ErrorActionPreference='Stop'\n"+run_code(step).replace('${{ matrix.architecture }}',arch))
                run=subprocess.run([self.pwsh,'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=45)
                detail=f'arch={arch}, entryExit={exit_code}, stagingFailure={stage_failure}, callerExit={run.returncode}\n{run.stdout}'
                self.assertEqual(run.returncode==0,exit_code==0 and not stage_failure,detail)
                output=runner/f'suite-native31-privacy-preparation-{arch}-123-1';setup=runner/f'suite-native31-setup-{arch}-123-1'
                for required in (output/'99-result.json',folder/'invocation.json',setup/'20-entry-exit.json'):
                    self.assertTrue(required.is_file(),f'Missing required fixture evidence {required}\n{detail}')
                self.assertEqual(json.loads((output/'99-result.json').read_text())['partial'],'original',detail)
                entry=json.loads((setup/'20-entry-exit.json').read_text());self.assertEqual(entry['exitCode'],exit_code,detail)
                invocation=json.loads((folder/'invocation.json').read_text())
                expected=runner/'suite-native31-source-arm64-123-1' if arch=='arm64' else root
                self.assertTrue(Path(invocation['cwd']).samefile(expected),
                    f'Recorded cwd {invocation["cwd"]!r} is not expected directory {str(expected)!r}\n{detail}')
                if arch=='x64':self.assertFalse((runner/'suite-native31-source-x64-123-1').exists())
                if exit_code:self.assertTrue((setup/'90-caller-failure.json').is_file(),detail)
                if stage_failure:
                    self.assertTrue((setup/'99-staging-failure.json').is_file(),detail)
                    record=json.loads((setup/'99-staging-failure.json').read_text());self.assertEqual(bool(record['primaryFailure']),bool(exit_code))
                else:
                    staged=root/'.work/suite-native31-privacy-preparation/control/99-result.json'
                    self.assertTrue(staged.is_file(),detail);self.assertEqual(staged.read_bytes(),(output/'99-result.json').read_bytes(),detail)

if __name__=='__main__':unittest.main()
