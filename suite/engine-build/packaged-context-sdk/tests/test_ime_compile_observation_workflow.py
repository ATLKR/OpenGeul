"""Independent numeric compiler observation; synthetic PS, no checkout/compile/API."""
import ast,copy,hashlib,importlib.util,json,os,shutil,struct,subprocess,tempfile,unittest
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[2]
spec=importlib.util.spec_from_file_location('ime_workflow_existing_sdk',Path(__file__).with_name('test_ci_wiring.py'));fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
PIN='b98b555b646f8fd412057afb880e8b4c35262f9a'
class CompileObservationWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.w=yaml.safe_load((REPO/'.github/workflows/office-suite.yml').read_text());self.job=self.w['jobs'].get('ime-finalization-compile-observation');self.assertTrue(type(self.job)is dict,'Independent compile observation job must exist')
 def selected(self,*,message='',**changes):
  clause="contains(github.event.head_commit.message, '[ime-finalization-compile]')"
  self.assertEqual(self.job['if'].count(clause),1)
  present=type(message)is str and '[ime-finalization-compile]'in message.casefold()
  return fixture.condition(self.job['if'].replace(clause,'true'if present else'false'),**changes)
 def step(self,id):
  rows=[s for s in self.job['steps']if s.get('id')==id];self.assertTrue(len(rows)==1);return rows[0]
 def allowed(self,text,*,cancelled=False,success=False,outcomes=None,outputs=None):
  values=outcomes or {};outputs=outputs or {};text=text.replace('always()','True').replace('!cancelled()',str(not cancelled)).replace('success()',str(success))
  import re
  text=re.sub(r"steps\.([a-z0-9-]+)\.outcome",lambda m:repr(values.get(m[1],'skipped')),text)
  text=re.sub(r"steps\.([a-z0-9-]+)\.outputs\.report_eligible",lambda m:repr(outputs.get(m[1],'')),text)
  text=text.replace('&&',' and ').replace('||',' or ');tree=ast.parse(text,mode='eval');allowed=(ast.Expression,ast.BoolOp,ast.And,ast.Or,ast.Compare,ast.Eq,ast.NotEq,ast.Load,ast.Constant)
  self.assertTrue(all(isinstance(n,allowed)for n in ast.walk(tree)));return bool(eval(compile(tree,'fixed-step-selector','eval'),{'__builtins__':{}}))
 def ps(self,code,root,*,extra=None):
  shell=shutil.which('pwsh');self.assertTrue(shell is not None,'Existing PowerShell required');script=root/'run.ps1';script.write_text(code)
  env=dict(PATH=str(Path(shell).parent)+os.pathsep+'/usr/bin'+os.pathsep+'/bin',RUNNER_TOOL_CACHE=str(root/'tools'),GITHUB_OUTPUT=str(root/'github-output'),OWNED_ARGV_FILE=str(root/'argv.json'),OWNED_COLLECTOR_EXIT='0',OWNED_REPORT_BYTES='32',XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'));env.update(extra or {})
  if os.name=='nt':env['SystemRoot']=os.environ.get('SystemRoot',r'C:\Windows')
  result=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(script)],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,shell=False)
  return result.returncode
 def pe(self,root,arch,*,machine=None):
  p=root/'tools/Python/3.12.14'/arch/'python.exe';p.parent.mkdir(parents=True);data=bytearray(512);data[:2]=b'MZ';struct.pack_into('<I',data,60,64);data[64:68]=b'PE\0\0';struct.pack_into('<H',data,68,machine if machine is not None else(0x8664 if arch=='x64'else 0xaa64));struct.pack_into('<H',data,86,2);struct.pack_into('<H',data,88,0x20b);p.write_bytes(data)
 def observe(self,root,host,*,code=0,size=32,machine=None,get_item_prefix=''):
  arch={'windows-2025':'x64','windows-11-arm':'arm64'}.get(host,'x64');self.pe(root,arch,machine=machine);(root/'.work/ime-finalization-source').mkdir(parents=True,exist_ok=True)
  run=self.step('ime-compile-observe')['run'].replace('${{ matrix.os }}',host);self.assertTrue(run.count('& $python suite/scripts/ime-finalization-compiler-observation/observe-ime-finalization-compile.py ')==1)
  # Only execution is stubbed; actual cache enumeration and PE validation run.
  run=run.replace('& $python suite/scripts/ime-finalization-compiler-observation/observe-ime-finalization-compile.py ','python suite/scripts/ime-finalization-compiler-observation/observe-ime-finalization-compile.py ',1)
  prefix="function global:python { [IO.File]::WriteAllText($env:OWNED_ARGV_FILE,(ConvertTo-Json -Compress -InputObject @($args))); $at=[Array]::IndexOf($args,'--output'); $out=$args[$at+1]; $null=New-Item -ItemType Directory -Path $out; [IO.File]::WriteAllBytes((Join-Path $out 'report.numeric.json'),[byte[]]::new([int]$env:OWNED_REPORT_BYTES)); $global:LASTEXITCODE=[int]$env:OWNED_COLLECTOR_EXIT }\n"
  return self.ps(get_item_prefix+prefix+run,root,extra=dict(OWNED_COLLECTOR_EXIT=str(code),OWNED_REPORT_BYTES=str(size)))
 def test_independent_same_exact_sdk_selector_two_hosts_and_fixed_budgets(self):
  sdk=self.w['jobs']['packaged-context-sdk'];self.assertTrue(self.job['if']==sdk['if'].rstrip()[:-1]+" && contains(github.event.head_commit.message, '[ime-finalization-compile]'))"and'needs'not in self.job)
  self.assertTrue(self.job['strategy']=={'fail-fast':False,'matrix':{'os':['windows-2025','windows-11-arm']}}and self.job['runs-on']=='${{ matrix.os }}'and self.job['timeout-minutes']==8)
  self.assertTrue(sdk['timeout-minutes']==6 and next(s for s in sdk['steps']if s.get('id')=='sdk-compile')['timeout-minutes']==4)
  self.assertTrue(self.selected(message='[ime-finalization-compile]'))
  for change in({'event_name':'workflow_dispatch'},{'event_name':'pull_request'},{'run_attempt':2},{'private':True},{'fork':True},{'actor':'other'},{'ref':'refs/heads/main'}):self.assertTrue(not self.selected(message='[ime-finalization-compile]',**change))
 def test_two_exact_checkouts_keep_source_pin_and_do_not_persist_credentials(self):
  checkouts=[s for s in self.job['steps']if s.get('uses','').startswith('actions/checkout@')];self.assertTrue(len(checkouts)==2)
  self.assertTrue(checkouts[0]['with']=={'persist-credentials':False,'ref':'${{ github.sha }}','fetch-depth':1})
  self.assertTrue(checkouts[1]['with']=={'repository':'ATLKR/OpenGeul','ref':PIN,'path':'.work/ime-finalization-source','persist-credentials':False,'fetch-depth':1})
  self.assertTrue(self.allowed(checkouts[1]['if'],success=True,outcomes={'ime-compile-paths':'success'}));self.assertTrue(not self.allowed(checkouts[1]['if'],success=True,outcomes={'ime-compile-paths':'failure'}))
 def test_collector_is_not_gated_by_sdk_success_and_cancellation_blocks_all_new_work(self):
  step=self.step('ime-compile-observe');text=step['if'];self.assertTrue('sdk-compile'not in text and'needs.'not in text)
  self.assertTrue(self.allowed(text,success=False,outcomes={'ime-compile-source':'success'}));self.assertTrue(not self.allowed(text,cancelled=True,outcomes={'ime-compile-source':'success'}));self.assertTrue(not self.allowed(text,outcomes={'ime-compile-source':'skipped'}))
  upload=next(s for s in self.job['steps']if s.get('uses','').startswith('actions/upload-artifact@'));self.assertTrue(self.allowed(upload['if'],success=False,outputs={'ime-compile-observe':'true'}));self.assertTrue(not self.allowed(upload['if'],cancelled=True,outputs={'ime-compile-observe':'true'}));self.assertTrue(not self.allowed(upload['if'],outputs={'ime-compile-observe':'false'}))
 def test_actual_fresh_path_guard_preserves_existing_source_output_and_other_payload(self):
  for relative in(None,'.work/ime-finalization-source','.work/ime-finalization-compile'):
   with tempfile.TemporaryDirectory()as t:
    root=Path(t);(root/'.work').mkdir();payload=root/'.work/preserved.bin';payload.write_bytes(b'owned-numeric-sentinel')
    if relative is not None:(root/relative).mkdir()
    code=self.ps(self.step('ime-compile-paths')['run'],root);self.assertTrue((code==0)==(relative is None));self.assertTrue(payload.read_bytes()==b'owned-numeric-sentinel')
    if relative is not None:self.assertTrue((root/relative).is_dir())
 def test_actual_native_cache_pe_checks_and_complete_argv_match_on_both_hosts(self):
  for host,arch in(('windows-2025','x64'),('windows-11-arm','arm64')):
   with tempfile.TemporaryDirectory()as t:
    root=Path(t);self.assertTrue(self.observe(root,host)==0)
    args=json.loads((root/'argv.json').read_text());self.assertTrue(args==['suite/scripts/ime-finalization-compiler-observation/observe-ime-finalization-compile.py','--source-root','.work/ime-finalization-source','--architecture',arch,'--output','.work/ime-finalization-compile'])
    self.assertTrue('report_eligible=true'in(root/'github-output').read_text())
 def test_actual_fixture_failure_stays_exit_one_and_numeric_report_is_still_eligible(self):
  with tempfile.TemporaryDirectory()as t:
   root=Path(t);self.assertTrue(self.observe(root,'windows-2025',code=1)==1);self.assertTrue('report_eligible=true'in(root/'github-output').read_text())
 def test_actual_repeat_and_wrong_interpreter_machine_never_launch_collector(self):
  for mode in('repeat','machine'):
   with tempfile.TemporaryDirectory()as t:
    root=Path(t)
    if mode=='repeat':
     p=root/'.work/ime-finalization-compile';p.mkdir(parents=True);(p/'report.numeric.json').write_bytes(b'preserved')
    self.assertTrue(self.observe(root,'windows-2025',machine=0xaa64 if mode=='machine'else None)==1)
    self.assertTrue(not(root/'argv.json').exists())
    if mode=='repeat':self.assertTrue((root/'.work/ime-finalization-compile/report.numeric.json').read_bytes()==b'preserved')
 def test_actual_report_boundary_is_32k_and_larger_or_empty_is_not_uploaded(self):
  for size,accepted in((32768,True),(32769,False),(0,False)):
   with tempfile.TemporaryDirectory()as t:
    root=Path(t);code=self.observe(root,'windows-2025',size=size);self.assertTrue((code==0)==accepted);self.assertTrue(('report_eligible=true'in(root/'github-output').read_text())==accepted)
 def test_fixed_numeric_artifact_and_original_sdk_artifact_remain_separate(self):
  uploads=[s for s in self.job['steps']if s.get('uses','').startswith('actions/upload-artifact@')];self.assertTrue(len(uploads)==1);u=uploads[0]
  self.assertTrue(u['with']['path']=='.work/ime-finalization-compile/report.numeric.json'and u['with']['retention-days']==1 and u['with']['if-no-files-found']=='error')
  self.assertTrue('permissions'not in self.job and not self.job.get('continue-on-error',False)and all(not s.get('continue-on-error',False)for s in self.job['steps']))
  expected={'.work/packaged-context-sdk-public/${{ matrix.os }}/report.numeric.json':'f2739c9168c824d91fae588b4c2b3163d14201ac8ac5f09df6778a83fb1461e7',
    '.work/packaged-context-sdk-batch-public/${{ matrix.os }}/controller.numeric.json\n.work/packaged-context-sdk-batch-public/${{ matrix.os }}/batch-hints.numeric.json\n':'ea16de6365ef4e3a45abd4c840b969ba7b9c8b54e2deb12e3a01499d9407e030'}
  sdk_uploads=[s for s in self.w['jobs']['packaged-context-sdk']['steps']if s.get('uses','').startswith('actions/upload-artifact@')]
  self.assertEqual(len(sdk_uploads),len(expected));self.assertEqual({s['with']['path']for s in sdk_uploads},set(expected))
  for upload in sdk_uploads:
   canonical=copy.deepcopy(upload)
   if upload['with']['path']!='.work/packaged-context-sdk-public/${{ matrix.os }}/report.numeric.json':
    clause="contains(github.event.head_commit.message, '[sdk-batch-codes]')"
    historical="contains(github.event.head_commit.message, '[sdk-batch-hints]')"
    self.assertEqual(canonical['if'].count(clause),1)
    self.assertNotIn(historical,canonical['if'])
    canonical['if']=canonical['if'].replace(clause,historical,1)
   observed=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
   self.assertEqual(observed,expected[upload['with']['path']])
 def test_sdk_artifact_separation_rejects_missing_duplicate_mixed_and_unknown_outputs(self):
  original=self.w
  try:
   for mode in('missing-normal','duplicate-normal','mixed-path','unsafe-admission','unknown-output','legacy-b1-marker','duplicate-b2-marker'):
    self.w=copy.deepcopy(original);steps=self.w['jobs']['packaged-context-sdk']['steps']
    uploads=[s for s in steps if s.get('uses','').startswith('actions/upload-artifact@')]
    normal,batch=uploads
    if mode=='missing-normal':steps.remove(normal)
    elif mode=='duplicate-normal':steps.append(copy.deepcopy(normal))
    elif mode=='mixed-path':batch['with']['path']=normal['with']['path']+'\n'+batch['with']['path']
    elif mode=='unsafe-admission':batch['if']=batch['if'].replace("== '1'","!= '2'")
    elif mode=='legacy-b1-marker':batch['if']=batch['if'].replace('[sdk-batch-codes]','[sdk-batch-hints]')
    elif mode=='duplicate-b2-marker':batch['if']+=" && contains(github.event.head_commit.message, '[sdk-batch-codes]')"
    else:
     unknown=copy.deepcopy(batch);unknown['with']['path']='.work/unreviewed/report.numeric.json';steps.append(unknown)
    with self.subTest(mode=mode),self.assertRaises(AssertionError):self.test_fixed_numeric_artifact_and_original_sdk_artifact_remain_separate()
  finally:self.w=original
 def test_rendered_powershell_and_existing_free_runner_policy_accept_new_job(self):
  shell=shutil.which('pwsh');self.assertTrue(shell is not None)
  with tempfile.TemporaryDirectory()as t:
   root=Path(t);script=root/'parse.ps1';script.write_text('$t=$null;$e=$null;$null=[Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$t,[ref]$e);if($e.Count){exit 1}')
   for host in('windows-2025','windows-11-arm'):
    for s in self.job['steps']:
     if 'run'not in s:continue
     target=root/'source.ps1';target.write_text(s['run'].replace('${{ matrix.os }}',host));env=dict(PATH=str(Path(shell).parent)+os.pathsep+'/usr/bin'+os.pathsep+'/bin',XDG_CACHE_HOME=str(root/'cache'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'))
     if os.name=='nt':env['SystemRoot']=os.environ.get('SystemRoot',r'C:\Windows')
     r=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(script),str(target)],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,shell=False);self.assertTrue(r.returncode==0)
  spec=importlib.util.spec_from_file_location('ime_observation_policy',REPO/'ci/policy.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);self.assertTrue(m.audit(self.w,workflow_path='.github/workflows/office-suite.yml'))

 def test_unknown_path_state_denial_or_io_never_authorizes_checkout_or_collector(self):
  for kind in('UnauthorizedAccessException','IO.IOException','silent-null'):
   shim="function global:Get-Item { [CmdletBinding()] param([string]$LiteralPath,[switch]$Force) if($LiteralPath -in @('.work/ime-finalization-source','.work/ime-finalization-compile')) { $exception=[System."+kind+"]::new('Owned path uncertainty'); $record=[System.Management.Automation.ErrorRecord]::new($exception,'OwnedPathUnknown',[System.Management.Automation.ErrorCategory]::ReadError,$null); $PSCmdlet.WriteError($record); return $null }; Microsoft.PowerShell.Management\\Get-Item @PSBoundParameters }\n"
   if kind=='silent-null':shim="function global:Get-Item { [CmdletBinding()] param([string]$LiteralPath,[switch]$Force) if($LiteralPath -in @('.work/ime-finalization-source','.work/ime-finalization-compile')) { return $null }; Microsoft.PowerShell.Management\\Get-Item @PSBoundParameters }\n"
   with self.subTest(kind=kind,phase='fresh'),tempfile.TemporaryDirectory()as t:
    root=Path(t);code=self.ps(shim+self.step('ime-compile-paths')['run'],root)
    self.assertTrue(code!=0)
    self.assertTrue(not self.allowed(self.step('ime-compile-source')['if'],success=False,outcomes={'ime-compile-paths':'failure'}))
   with self.subTest(kind=kind,phase='collector'),tempfile.TemporaryDirectory()as t:
    root=Path(t);code=self.observe(root,'windows-2025',get_item_prefix=shim)
    self.assertTrue(code==1 and not(root/'argv.json').exists())
    self.assertTrue('report_eligible=false'in(root/'github-output').read_text())

 def test_commit_marker_is_opt_in_and_does_not_gate_the_sdk_job(self):
  for message in(None,'','ordinary SDK observation','ime-finalization-compile','[ime-finalization-compile','[ime-finalization-compile-other]'):
   with self.subTest(case=type(message).__name__):self.assertFalse(self.selected(message=message))
  for message in('[ime-finalization-compile]','explicit [ime-finalization-compile] observation','[IME-FINALIZATION-COMPILE]'):
   self.assertTrue(self.selected(message=message))
  self.assertTrue(fixture.condition(self.w['jobs']['packaged-context-sdk']['if']))
 def test_commit_marker_cannot_override_the_original_owner_ref_or_attempt_guards(self):
  changes=({'repository':'OTHER/OpenGeul'},{'repository_id':'1'},{'repository_owner':'OTHER'},{'actor':'OTHER'},
   {'actor_id':'1'},{'triggering_actor':'OTHER'},{'private':True},{'fork':True},{'event_name':'workflow_dispatch'},
   {'event_name':'pull_request'},{'run_attempt':2},{'ref':'refs/heads/main'})
  for index,change in enumerate(changes):
   with self.subTest(case=index):self.assertFalse(self.selected(message='[ime-finalization-compile]',**change))
