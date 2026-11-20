"""One reviewed Writer failure-diagnostic workflow route, never qualification."""
import hashlib,json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
import yaml
from suite.tests.workflow_scope import suite_workflow_sections
ROOT=Path(__file__).resolve().parents[2]
COMMAND='python suite/e2e/korean_ui_smoke.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --output .work/suite-korean-ui'
EVENT="${{ github.event.repository.full_name == 'ATLKR/OpenGeul' && github.event.repository.private == false && github.event.repository.id > 0 && github.event.sender.login == 'ATLKR' && github.event.sender.id == 65988341 && github.event.sender.type == 'User' && github.event.ref == 'refs/heads/work/opengeul-office-arm64' && github.event.deleted == false && github.event.after == github.sha }}"
class WriterSameRootWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.source=(ROOT/'.github/workflows/office-suite.yml').read_text();self.normal=suite_workflow_sections(self.source)[1]
  self.steps=yaml.safe_load(self.source)['jobs']['windows-suite']['steps']
  matches=[s for s in self.steps if COMMAND in s.get('run','')];self.assertTrue(len(matches)==1);self.entry=matches[0]
  raw=(ROOT/'suite/tests/fixtures/writer-server-observer-normal-workflow.json').read_bytes();self.assertTrue(hashlib.sha256(raw).hexdigest()=='191eb38642ecdc5d885815cea9567c70cdd49c7950d325403e143db113b62e2c');self.golden=json.loads(raw)['normalJobTextSha256']
 def pair(self):
  lines=self.entry['run'].splitlines(True);i=next(i for i,l in enumerate(lines)if l.startswith('python '));return ''.join('        '+l for l in lines[:i+1])
 def accepted(self,normal):
  from suite.tests.reviewed_normal_workflow import original_normal_oracle_text
  try:return hashlib.sha256(original_normal_oracle_text(normal).encode()).hexdigest()==self.golden
  except ValueError:return False
 def context(self,arch):
  return dict(OPENGEUL_SUITE_RUN_MODE='acceptance',GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Windows',RUNNER_ARCH='ARM64'if arch=='arm64'else'X64',GITHUB_REPOSITORY='ATLKR/OpenGeul',GITHUB_EVENT_NAME='push',GITHUB_JOB='windows-suite',GITHUB_REF='refs/heads/work/opengeul-office-arm64',GITHUB_WORKFLOW_REF='ATLKR/OpenGeul/.github/workflows/office-suite.yml@refs/heads/work/opengeul-office-arm64',GITHUB_RUN_ATTEMPT='1',GITHUB_ACTOR='ATLKR',GITHUB_ACTOR_ID='65988341',GITHUB_SHA='a'*40,GITHUB_WORKFLOW_SHA='a'*40,GITHUB_RUN_ID='123')
 def invoke(self,arch,*,changes=None,event=True):
  shell=shutil.which('pwsh');self.assertTrue(shell is not None,'Existing PowerShell required')
  prefix="$ErrorActionPreference='Stop'\n$global:LASTEXITCODE=0\n$script:launches=@()\nfunction global:python { $script:launches += ,@($args); [IO.File]::WriteAllText($env:OWNED_LAUNCH_WITNESS,'1'); $global:LASTEXITCODE=0 }\n"
  code=prefix+self.entry['run'].replace('${{ matrix.architecture }}',arch).replace(EVENT,'true'if event else'false')+"\nWrite-Output (ConvertTo-Json -Compress -Depth 5 @{launches=@($script:launches)})\n"
  with tempfile.TemporaryDirectory()as t:
   own=Path(t);script=own/'writer-route.ps1';script.write_text(code);witness=own/'launch.numeric'
   env=self.context(arch);env.update(changes or {});env.update(PATH=str(Path(shell).parent)+os.pathsep+'/usr/bin'+os.pathsep+'/bin',SUITE_PACKAGE='C:/SyntheticSuite',PYTHONUTF8='1',OWNED_LAUNCH_WITNESS=str(witness),XDG_CACHE_HOME=str(own/'cache'),XDG_CONFIG_HOME=str(own/'config'),XDG_DATA_HOME=str(own/'data'))
   if os.name=='nt':env['SystemRoot']=os.environ.get('SystemRoot',r'C:\Windows')
   result=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(script)],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=15,shell=False)
   self.assertTrue(result.returncode==0 and witness.is_file(),'Original command must still launch exactly once')
  value=json.loads(result.stdout);self.assertTrue(type(value)is dict and value.keys()=={'launches'}and len(value['launches'])==1);return value['launches'][0]
 def expected(self,extra):return ['suite/e2e/korean_ui_smoke.py','--suite','C:/SyntheticSuite','--fixtures','.work/suite-engine/fixtures','--output','.work/suite-korean-ui']+extra
 def test_current_route_is_required_and_preserves_original_historical_digest(self):
  self.assertTrue(' @writerSameRootArgs\n'in self.pair()and self.accepted(self.normal))
  self.assertTrue(self.entry['if']=="env.OPENGEUL_SUITE_RUN_MODE == 'acceptance' && (!cancelled() && steps.fixtures.outcome == 'success')")
  self.assertTrue(self.entry['shell']=='pwsh'and self.entry['run'].count(COMMAND)==1)
 def test_removing_modifying_duplicating_or_moving_current_pair_never_downgrades_to_legacy(self):
  pair=self.pair();self.assertTrue(' @writerSameRootArgs\n'in pair)
  prologue,command=pair.rsplit('        python ',1);command='        python '+command
  cases=[self.normal.replace(pair,command.replace(' @writerSameRootArgs',''),1),self.normal.replace(pair,command,1),self.normal.replace(pair,pair+pair,1),self.normal.replace(pair,'',1)+pair,self.normal.replace(pair,command,1)+prologue]
  for changed in cases:self.assertTrue(not self.accepted(changed))
 def test_partial_condition_architecture_option_and_command_changes_are_rejected(self):
  pair=self.pair();self.assertTrue(' @writerSameRootArgs\n'in pair)
  replacements=[('$writerSameRootArgs = @()\n',''),('-ceq','-eq'),('-cmatch','-match'),("'--writer-same-root-diagnostic'","'--other-probe'"),("'${{ matrix.architecture }}'","'arm64'"),("$env:GITHUB_RUN_ATTEMPT -ceq '1'","$env:GITHUB_RUN_ATTEMPT -ceq '2'"),("$env:GITHUB_ACTOR -ceq 'ATLKR'","$env:GITHUB_ACTOR -ceq 'other'"),('github.event.sender.id == 65988341','github.event.sender.id > 0'),(' @writerSameRootArgs\n','\n'),(' --fixtures .work/suite-engine/fixtures',' --fixtures another')]
  for old,new in replacements:
   self.assertTrue(old in pair);self.assertTrue(not self.accepted(self.normal.replace(pair,pair.replace(old,new,1),1)))
 def test_other_unreviewed_normal_changes_remain_sha_visible(self):
  self.assertTrue(self.accepted(self.normal))
  for changed in(self.normal.replace('timeout-minutes: 150','timeout-minutes: 151'),self.normal+'    - run: unreviewed_gate\n'):
   self.assertTrue(not self.accepted(changed))
 def test_actual_powershell_exact_owner_push_selects_explicit_option_on_both_architectures(self):
  for arch in('arm64','x64'):self.assertTrue(self.invoke(arch)==self.expected(['--writer-same-root-diagnostic',arch]))
 def test_actual_powershell_manual_retry_other_source_or_owner_keeps_original_args(self):
  changes=[{'GITHUB_EVENT_NAME':'workflow_dispatch'},{'GITHUB_RUN_ATTEMPT':'2'},{'GITHUB_ACTOR':'other'},{'GITHUB_ACTOR_ID':'1'},{'GITHUB_REF':'refs/heads/main'},{'GITHUB_WORKFLOW_SHA':'b'*40},{'GITHUB_SHA':'A'*40},{'GITHUB_RUN_ID':'0'},{'GITHUB_JOB':'other'},{'GITHUB_ACTIONS':'false'},{'RUNNER_ENVIRONMENT':'self-hosted'},{'RUNNER_OS':'Linux'},{'GITHUB_REPOSITORY':'other/repo'},{'GITHUB_WORKFLOW_REF':'other'},{'OPENGEUL_SUITE_RUN_MODE':'ime-mode-diagnostic'}]
  for change in changes:self.assertTrue(self.invoke('arm64',changes=change)==self.expected([]))
 def test_actual_powershell_bad_arch_or_unmatched_event_keeps_original_args(self):
  for arch,change,event in(('x86',{},True),('ARM64',{},True),('arm64',{'RUNNER_ARCH':'X64'},True),('x64',{'RUNNER_ARCH':'ARM64'},True),('arm64',{},False)):
   self.assertTrue(self.invoke(arch,changes=change,event=event)==self.expected([]))
 def test_powershell_parser_accepts_exact_run_block_without_execution(self):
  shell=shutil.which('pwsh');self.assertTrue(shell is not None)
  with tempfile.TemporaryDirectory()as t:
   own=Path(t);source=own/'source.ps1';source.write_text(self.entry['run'].replace('${{ matrix.architecture }}','arm64').replace(EVENT,'true'));parser=own/'parse.ps1';parser.write_text('$tokens=$null;$errors=$null;$null=[Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors);[Console]::Write($errors.Count);if($errors.Count){exit 1}')
   env=dict(PATH=str(Path(shell).parent)+os.pathsep+'/usr/bin'+os.pathsep+'/bin',XDG_CACHE_HOME=str(own/'cache'),XDG_CONFIG_HOME=str(own/'config'),XDG_DATA_HOME=str(own/'data'))
   if os.name=='nt':env['SystemRoot']=os.environ.get('SystemRoot',r'C:\Windows')
   for arch in('arm64','x64'):
    for event in('true','false'):
     source.write_text(self.entry['run'].replace('${{ matrix.architecture }}',arch).replace(EVENT,event))
     result=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(parser),str(source)],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=15,shell=False)
     self.assertTrue(result.returncode==0 and result.stdout=='0')
