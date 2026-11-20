"""The optional reader seal is explicit and never selects a diagnostic menu mode."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]
WORKFLOW=ROOT/'.github/workflows/office-suite.yml'
COMMAND='python suite/e2e/korean_ime_smoke.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --readiness .work/suite-korean-readiness/readiness.json --output .work/suite-korean-ime'
CALC_COMMAND='python suite/e2e/calc_save_smoke.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --output .work/suite-calc-save'

class ConsumerSourceReaderWorkflowTests(unittest.TestCase):
 def steps(self):
  document=yaml.safe_load(WORKFLOW.read_text())
  return [step for job in document['jobs'].values() for step in job.get('steps',[])]
 def step(self):
  rows=[step for step in self.steps() if COMMAND in step.get('run','')]
  self.assertEqual(len(rows),1,'The normal IME entry must be unique')
  return rows[0]
 def calc_step(self):
  rows=[step for step in self.steps() if step.get('id')=='calc-save']
  self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]['if'],"(env.OPENGEUL_SUITE_RUN_MODE == 'acceptance' || (env.OPENGEUL_SUITE_RUN_MODE == 'ime-mode-diagnostic' && matrix.architecture == 'arm64')) && (!cancelled() && steps.fixtures.outcome == 'success')")
  return rows[0]
 def invoke(self,runtime_format,architecture,*,calc=False,mode='acceptance'):
  shell=shutil.which('pwsh');self.assertIsNotNone(shell,'Existing PowerShell is needed for the workflow argument check')
  command=CALC_COMMAND if calc else COMMAND
  run=(self.calc_step() if calc else self.step())['run'];line=next(row for row in run.splitlines() if command in row)
  replacement="$argsValue = Get-Variable -Name sourceReaderArgs -ValueOnly -ErrorAction SilentlyContinue; if ($null -eq $argsValue) { $argsValue = @() }; Write-Output (ConvertTo-Json -Compress @{args=@($argsValue)})"
  script="$ErrorActionPreference = 'Stop'\n$global:LASTEXITCODE=0\n"+run.replace(line,replacement).replace('${{ matrix.architecture }}',architecture)
  with tempfile.TemporaryDirectory() as owned:
   path=Path(owned)/'workflow-arguments.ps1';path.write_text(script)
   child_env={'PATH':str(Path(shell).parent),'SUITE_RUNTIME_FORMAT':runtime_format,'OPENGEUL_SUITE_RUN_MODE':mode,'PYTHONUTF8':'1'}
   if os.name=='nt':child_env['SystemRoot']=os.environ.get('SystemRoot',r'C:\Windows')
   else:child_env['PATH']+=os.pathsep+'/usr/bin'+os.pathsep+'/bin'
   result=subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(path)],env=child_env,capture_output=True,text=True,timeout=15)
  return result
 def test_source_built_native_architectures_select_explicit_reader_context(self):
  for arch in ('x64','arm64'):
   with self.subTest(architecture=arch):
    result=self.invoke('source-built-zip',arch);self.assertEqual(result.returncode,0)
    self.assertEqual(json.loads(result.stdout),dict(args=['--source-qualified-reader',arch]))
 def test_msi_preserves_default_reader_arguments(self):
  for arch in ('x64','arm64'):
   with self.subTest(architecture=arch):
    result=self.invoke('msi',arch);self.assertEqual(result.returncode,0)
    self.assertEqual(json.loads(result.stdout),dict(args=[]))
 def test_unknown_runtime_formats_do_not_reach_the_python_launch(self):
  for value in ('SOURCE-BUILT-ZIP','unknown',''):
   with self.subTest(format=value):self.assertNotEqual(self.invoke(value,'arm64').returncode,0)
 def test_source_built_unknown_architectures_do_not_reach_python_launch(self):
  for value in ('x86','ARM64',''):
   with self.subTest(architecture=value):self.assertNotEqual(self.invoke('source-built-zip',value).returncode,0)
 def test_normal_acceptance_condition_and_diagnostic_commands_are_preserved(self):
  step=self.step()
  self.assertEqual(step['if'],"env.OPENGEUL_SUITE_RUN_MODE == 'acceptance' && (!cancelled() && steps.fixtures.outcome == 'success' && steps.readiness.outcome == 'success')")
  for row in self.steps():
   if row is not step and '--diagnose-' in row.get('run',''):self.assertNotIn('--source-qualified-reader',row['run'])
  self.assertNotIn('--source-qualified-menu',step['run'])
  self.assertNotIn('SendInput',step['run'])

 def test_calc_acceptance_source_built_uses_the_explicit_reader_seal(self):
  for architecture in ('x64','arm64'):
   result=self.invoke('source-built-zip',architecture,calc=True)
   self.assertEqual(result.returncode,0)
   self.assertEqual(json.loads(result.stdout),dict(args=['--source-qualified-reader',architecture]))
 def test_calc_msi_and_diagnostic_arguments_remain_original(self):
  for runtime_format,architecture,mode in (('msi','x64','acceptance'),('source-built-zip','arm64','ime-mode-diagnostic'),('msi','arm64','ime-mode-diagnostic')):
   result=self.invoke(runtime_format,architecture,calc=True,mode=mode)
   self.assertEqual(result.returncode,0)
   self.assertEqual(json.loads(result.stdout),dict(args=[]))
 def test_calc_acceptance_unknown_profiles_fail_before_launch(self):
  for runtime_format,architecture in (('SOURCE-BUILT-ZIP','arm64'),('unknown','arm64'),('source-built-zip','x86'),('source-built-zip','ARM64'),('source-built-zip','')):
   with self.subTest(architecture=architecture):self.assertNotEqual(self.invoke(runtime_format,architecture,calc=True).returncode,0)

if __name__=='__main__':unittest.main()
