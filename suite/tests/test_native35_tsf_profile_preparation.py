"""Fixed experimental TSF privacy binding; no native/privacy actions execute."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
ADAPTER=ROOT/'e2e/native35_tsf_profile_prepare.py'
CALLER=ROOT/'suite/scripts/prepare-native35-tsf-profile.ps1'
BRANCH='refs/heads/work/opengeul-office-native35-tsf-diagnostic'
WORKFLOW='ATLKR/OpenGeul/.github/workflows/office-suite-native35-tsf-diagnostic.yml@'+BRANCH
JOB='windows-tsf-profile-diagnostic'
ADDITIONAL=('e2e/native35_tsf_profile_prepare.py','.github/workflows/office-suite-native35-tsf-diagnostic.yml','suite/scripts/prepare-native35-tsf-profile.ps1')
PYTHON_REPLACEMENTS=(('refs/heads/work/opengeul-office-arm64',BRANCH),('.github/workflows/office-suite.yml','.github/workflows/office-suite-native35-tsf-diagnostic.yml'),('windows-suite',JOB),('e2e/native31_suite_prepare.py',ADDITIONAL[0]),('suite/scripts/prepare-native31.ps1',ADDITIONAL[2]))
PS_REPLACEMENTS=PYTHON_REPLACEMENTS+(('suite-native31-setup','suite-native35-tsf-profile-setup'),('suite-native31-privacy-preparation','suite-native35-tsf-profile-privacy-preparation'),('suite-native31-source','suite-native35-tsf-profile-source'))


def rebound(text,replacements):
    for before,after in replacements:text=text.replace(before,after)
    return text


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module


class TSFPreparationContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue(ADAPTER.is_file());self.assertTrue(CALLER.is_file())
        self.m=load('tsf_profile_prepare_contract',ADAPTER)
        self.core=load('tsf_profile_control_contract',ROOT/'e2e/native31_desktop_control.py')
        self.env=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Windows',RUNNER_ARCH='ARM64',GITHUB_REPOSITORY='ATLKR/OpenGeul',GITHUB_EVENT_NAME='push',GITHUB_JOB=JOB,GITHUB_REF=BRANCH,GITHUB_WORKFLOW_REF=WORKFLOW,GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',GITHUB_ACTOR='ATLKR',GITHUB_ACTOR_ID='65988341')
        self.event=dict(repository=dict(full_name='ATLKR/OpenGeul',id=123,private=False),sender=dict(login='ATLKR',id=65988341,type='User'),ref=BRANCH,deleted=False,after='a'*40)
        self.native=dict(processId=45,processMachine=0,nativeMachine=0xAA64,sessionId=1)
    def validate(self,env=None,event=None):
        env=self.env if env is None else env;event=self.event if event is None else event
        value=self.m.validate_context(env,event,'arm64','nt')
        self.core.validate_execution(env,event,self.native,'nt',prepare_privacy=True,binding=self.m.control_binding(self.core))
        return value
    def test_genuine_fixed_diagnostic_owner_push_is_accepted_without_environment_rewrite(self):
        before=copy.deepcopy(self.env);error=None;value=None
        try:value=self.validate()
        except BaseException as exc:error=exc
        self.assertIsNone(error,'The new adapter must bind the genuine diagnostic context')
        self.assertEqual(value['ref'],BRANCH);self.assertEqual(value['workflowRef'],WORKFLOW);self.assertEqual(value['job'],JOB)
        self.assertEqual(self.env,before)
    def test_original_suite_binding_is_rejected_by_both_new_layers(self):
        oldref='refs/heads/work/opengeul-office-arm64';env={**self.env,'GITHUB_REF':oldref,'GITHUB_WORKFLOW_REF':'ATLKR/OpenGeul/.github/workflows/office-suite.yml@'+oldref,'GITHUB_JOB':'windows-suite'};event={**self.event,'ref':oldref}
        with self.assertRaises(ValueError):self.m.validate_context(env,event,'arm64','nt')
        with self.assertRaises(ValueError):self.core.validate_execution(env,event,self.native,'nt',prepare_privacy=True,binding=self.m.control_binding(self.core))
    def test_observer_entry_and_exact_three_additional_paths_are_fixed(self):
        binding=self.m.control_binding(self.core)
        self.assertEqual((binding.ref,binding.workflow,binding.job),(BRANCH,WORKFLOW,JOB))
        self.assertEqual(binding.observer_entry,ADDITIONAL[0]);self.assertEqual(binding.additional_source_files,ADDITIONAL)
    def test_wrong_context_fields_are_rejected_before_any_action(self):
        for key,bad in [('GITHUB_REF','refs/heads/work/opengeul-office-native35-tsf-preparation'),('GITHUB_WORKFLOW_REF','ATLKR/OpenGeul/.github/workflows/other.yml@'+BRANCH),('GITHUB_JOB','windows-suite'),('GITHUB_EVENT_NAME','workflow_dispatch'),('GITHUB_ACTOR','other'),('GITHUB_ACTOR_ID','1'),('GITHUB_WORKFLOW_SHA','b'*40),('GITHUB_SHA','A'*40),('GITHUB_RUN_ATTEMPT','2'),('RUNNER_ARCH','X64'),('RUNNER_ENVIRONMENT','self-hosted')]:
            with self.subTest(key=key):
                env={**self.env,key:bad};before=copy.deepcopy(env)
                with self.assertRaises(ValueError):self.m.validate_context(env,self.event,'arm64','nt')
                with self.assertRaises(ValueError):self.core.validate_execution(env,self.event,self.native,'nt',prepare_privacy=True,binding=self.m.control_binding(self.core))
                self.assertEqual(env,before)
    def test_actual_owner_payload_is_required_and_not_inferred_from_environment(self):
        changes={'ref':lambda e:e.update(ref='refs/heads/other'),'after':lambda e:e.update(after='b'*40),'deleted':lambda e:e.update(deleted=True),'private':lambda e:e['repository'].update(private=True),'repository':lambda e:e['repository'].update(full_name='other/OpenGeul'),'owner':lambda e:e['sender'].update(login='other'),'owner-id':lambda e:e['sender'].update(id=1),'sender-type':lambda e:e['sender'].update(type='Bot')}
        for name,change in changes.items():
            with self.subTest(name=name):
                event=copy.deepcopy(self.event);change(event)
                with self.assertRaises(ValueError):self.m.validate_context(self.env,event,'arm64','nt')
                with self.assertRaises(ValueError):self.core.validate_execution(self.env,event,self.native,'nt',prepare_privacy=True,binding=self.m.control_binding(self.core))
    def test_binding_does_not_change_standalone_core_authority(self):
        for prepare in (False,True):
            with self.assertRaises(ValueError):self.core.validate_execution(self.env,self.event,self.native,'nt',prepare_privacy=prepare)
        with self.assertRaises(ValueError):self.core.validate_execution(self.env,self.event,self.native,'nt',binding=self.m.control_binding(self.core))
    def test_arm_delegation_preserves_original_arguments_and_deadline(self):
        seen=[];fake=SimpleNamespace(ControlBinding=self.core.ControlBinding,controller=lambda args,**kw:seen.append(('controller',args,kw))or 0,observer=lambda args,**kw:seen.append(('observer',args,kw))or 0)
        for observe in (False,True):
            with self.subTest(observer=observe):
                args=SimpleNamespace(architecture='arm64',observer=observe,deadline=123.0 if observe else None,prepare_privacy=True,output=Path('/unused'))
                error=None;code=None
                with patch.dict(os.environ,self.env),patch.object(self.m,'read_event',return_value=self.event),patch.object(self.m,'load_control',return_value=fake):
                    try:code=self.m.arm_entry(args,platform='nt')
                    except BaseException as exc:error=exc
                self.assertIsNone(error,'A genuine diagnostic call must delegate to the unchanged core')
                self.assertEqual(code,0);self.assertIs(seen[-1][1],args);self.assertEqual(seen[-1][2]['binding'],self.m.control_binding(fake));self.assertEqual(args.deadline,123.0 if observe else None)
        self.assertEqual(len(seen),2)
    def test_prepare_mode_is_required_before_loading_control(self):
        args=SimpleNamespace(prepare_privacy=False)
        with patch.dict(os.environ,self.env),patch.object(self.m,'read_event',return_value=self.event),patch.object(self.m,'load_control',side_effect=AssertionError('native core must not load'))as load_core:
            with self.assertRaises(ValueError):self.m.arm_entry(args,platform='nt')
        load_core.assert_not_called()
    def test_python_adapter_is_exact_template_with_only_fixed_rebindings(self):
        expected=rebound((ROOT/'e2e/native31_suite_prepare.py').read_text(),PYTHON_REPLACEMENTS)
        self.assertEqual(ADAPTER.read_text(),expected)
        writes=[n for n in ast.walk(ast.parse(ADAPTER.read_text()))if isinstance(n,(ast.Assign,ast.AugAssign,ast.AnnAssign))and any('environ' in ast.unparse(t)for t in(getattr(n,'targets',[])or[getattr(n,'target',None)])if t is not None)]
        self.assertEqual(writes,[])
    def test_powershell_is_exact_template_and_pins_all_seven_core_plus_new_three(self):
        expected=rebound((ROOT/'suite/scripts/prepare-native31.ps1').read_text(),PS_REPLACEMENTS)
        text=CALLER.read_text();self.assertEqual(text,expected)
        block=re.search(r'\$Native31Critical = @\((.*?)\)\n',text,re.S).group(1)
        critical=tuple(re.findall("'([^']+)'",block));self.assertEqual(critical,(*self.core.SOURCE_FILES,*ADDITIONAL))
        self.assertIn("'--architecture',$Arch,'--prepare-privacy'",text);self.assertIn("NATIVE31_PWSH",text)
        self.assertFalse(re.search(r'\$env:GITHUB_[A-Z_]+\s*=',text))
    def test_powershell_parses_without_running_any_script_statement(self):
        pwsh=shutil.which('pwsh');self.assertIsNotNone(pwsh,'Existing PowerShell parser capability is required; no silent skip')
        code="$tokens=$null; $errors=$null; $ast=[System.Management.Automation.Language.Parser]::ParseFile($env:TEST_PARSE_SOURCE,[ref]$tokens,[ref]$errors); if($errors.Count -ne 0){$errors | Out-String | Write-Output; exit 1}; @{parseErrors=$errors.Count;tokenCount=$tokens.Count;statementCount=$ast.EndBlock.Statements.Count} | ConvertTo-Json -Compress"
        result=subprocess.run([pwsh,'-NoLogo','-NoProfile','-NonInteractive','-Command',code],env={**os.environ,'TEST_PARSE_SOURCE':str(CALLER)},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout);receipt=json.loads(result.stdout);self.assertEqual(receipt['parseErrors'],0);self.assertGreater(receipt['tokenCount'],0)
    def test_bound_source_hashes_and_clean_commit_reject_each_new_source_mutation(self):
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp).resolve();binding=self.m.control_binding(self.core)
            # Both template and diagnostic path fixtures exist; the assertion
            # distinguishes genuine new source pins from the old Suite tuple.
            original=load('tsf_source_original_adapter',ROOT/'e2e/native31_suite_prepare.py')
            for name in dict.fromkeys((*self.core.SOURCE_FILES,*original.ADDITIONAL_SOURCE_FILES,*ADDITIONAL)):
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/name).read_bytes()if(ROOT/name).is_file()else b'# inert committed workflow fixture; never executed\n')
            def git(*a):return subprocess.check_output(['git','-C',str(root),*a],stderr=subprocess.PIPE,text=True).strip()
            git('init','-q');git('config','user.email','contract@example.invalid');git('config','user.name','TSF binding contract');git('add','.');git('commit','-qm','inert source fixture');sha=git('rev-parse','HEAD')
            env={**self.env,'GITHUB_SHA':sha,'GITHUB_WORKFLOW_SHA':sha};event={**self.event,'after':sha}
            with patch.object(self.core,'ROOT',root):
                proof=self.core.bound_source(self.core.Budget(),binding)
                self.assertEqual(set(proof['files']),set((*self.core.SOURCE_FILES,*ADDITIONAL)))
                self.assertFalse(proof['dirty']);self.core.validate_context(env,event,proof,self.native,'nt',prepare_privacy=True,binding=binding)
                for name in ADDITIONAL:
                    with self.subTest(source=name):
                        target=root/name;before=target.read_bytes();target.write_bytes(before+b'\n# changed\n')
                        changed=self.core.bound_source(self.core.Budget(),binding);self.assertTrue(changed['dirty']);self.assertNotEqual(changed['files'][name],proof['files'][name])
                        with self.assertRaises(ValueError):self.core.validate_context(env,event,changed,self.native,'nt',prepare_privacy=True,binding=binding)
                        target.write_bytes(before)
                self.assertEqual(self.core.bound_hashes(binding),proof['files'])
    def test_unaliased_path_checks_remain_fail_closed(self):
        with tempfile.TemporaryDirectory()as temp:
            root=Path(temp).resolve();self.assertEqual(self.m.plain_path(root),root)
            with self.assertRaises(ValueError):self.m.plain_path(root/'..'/'alias')


if __name__=='__main__':unittest.main()
