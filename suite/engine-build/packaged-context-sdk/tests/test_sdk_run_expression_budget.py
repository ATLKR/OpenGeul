"""Source inference boundary and real pure PS runner selection; no SDK invocation."""
import json,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[2]
LIMIT=21000

def translated_run_length(script):
    # Model the official reader's quote/brace escaping only; never evaluate text.
    matches=list(re.finditer(r'\$\{\{\s*([A-Za-z_.]+)\s*\}\}',script))
    if not matches:return len(script)
    output=[];arguments=[];start=0
    for index,match in enumerate(matches):
        output.extend((script[start:match.start()].replace("'","''").replace('{','{{').replace('}','}}'),'{'+str(index)+'}'))
        arguments.append(match.group(1));start=match.end()
    output.append(script[start:].replace("'","''").replace('{','{{').replace('}','}}'))
    return len("format('"+''.join(output)+"', "+', '.join(arguments)+')')

class SdkRunExpressionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.job=yaml.safe_load((REPO/'.github/workflows/office-suite.yml').read_bytes())['jobs']['packaged-context-sdk']
        self.script=next(row['run']for row in self.job['steps']if row.get('id')=='sdk-compile')
    def test_sdk_run_has_no_github_interpolation(self):
        self.assertNotIn('${{',self.script)
    def test_raw_and_translated_lengths_are_both_within_platform_budget(self):
        self.assertLessEqual(len(self.script),LIMIT)
        self.assertLessEqual(translated_run_length(self.script),LIMIT)
    def test_existing_jobenv_is_snapshotted_once_and_closed_before_paths(self):
        self.assertEqual(self.job['env']['SDK_MATRIX_RUNNER'],'${{ matrix.os }}')
        self.assertEqual(self.script.count('$env:SDK_MATRIX_RUNNER'),1)
        self.assertIn('$sdkRunner = $env:SDK_MATRIX_RUNNER',self.script)
        self.assertIn('switch -CaseSensitive ($sdkRunner)',self.script)
        self.assertIn("('.work/packaged-context-sdk-public/' + $sdkRunner)",self.script)
        self.assertLess(self.script.index('switch -CaseSensitive ($sdkRunner)'),self.script.index('$public = Join-Path'))
    def test_budget_model_distinguishes_raw_safe_but_escaped_oversized_source(self):
        text="x'{}${{ matrix.os }}"
        self.assertEqual(translated_run_length(text),len("format('x''{{}}{0}', matrix.os)"))
        mixed="'"*10500+'${{ matrix.os }}'
        self.assertLess(len(mixed),LIMIT);self.assertGreater(translated_run_length(mixed),LIMIT)
        self.assertEqual(translated_run_length('literal {} PowerShell'),len('literal {} PowerShell'))
    def test_actual_powershell_selects_only_exact_runner_values_before_public_path(self):
        shell=shutil.which('pwsh');self.assertIsNotNone(shell,'Existing PowerShell required')
        start=self.script.index('try {')+len('try {');end=self.script.index('$machine = if ',start)
        preamble=self.script[start:end]
        public=next(line for line in self.script.splitlines()if line.strip().startswith('$public = Join-Path'))
        cases=(('windows-2025',True,0x8664,1),('windows-11-arm',True,0xaa64,2),
          (None,False,0,0),('',False,0,0),('windows-2022',False,0,0),('WINDOWS-2025',False,0,0),
          ('windows-2025/../owned',False,0,0),("windows-2025'; throw 'SYNTHETIC",False,0,0),('windows-11-arm\n',False,0,0))
        for index,(value,accepted,machine,path_code)in enumerate(cases,1):
            with self.subTest(case=index),tempfile.TemporaryDirectory()as td:
                root=Path(td);home=root/'home';home.mkdir();script=root/'select.ps1';output=root/'result.numeric.json'
                # Baseline interpolation is rendered only to reproduce the original fixed runner.
                rendered_runner='windows-11-arm'if value=='windows-11-arm'else'windows-2025'
                body=(preamble+public).replace('${{ matrix.os }}',rendered_runner)
                script.write_text("$ErrorActionPreference='Stop'\n$accepted=$false;$pathObserved=$false;$machine=0;$pathCode=0\ntry {\n"+body+"\n$pathObserved=$true;$accepted=$true\n$machine=if($architecture -ceq 'x64'){34404}elseif($architecture -ceq 'arm64'){43620}else{0}\n$leaf=Split-Path -Leaf $public\n$pathCode=if($leaf -ceq 'windows-2025'){1}elseif($leaf -ceq 'windows-11-arm'){2}else{0}\n}catch{}\n[ordered]@{accepted=$accepted;pathObserved=$pathObserved;machine=$machine;pathCode=$pathCode}|ConvertTo-Json -Compress\n")
                env={'PATH':str(Path(shell).parent)+os.pathsep+'/usr/bin'+os.pathsep+'/bin','HOME':str(home),'XDG_CONFIG_HOME':str(home),'POWERSHELL_TELEMETRY_OPTOUT':'1'}
                if value is not None:env['SDK_MATRIX_RUNNER']=value
                if os.name=='nt':env['SystemRoot']=os.environ.get('SystemRoot',r'C:\Windows')
                with output.open('xb')as stream:
                    child=subprocess.Popen([shell,'-NoLogo','-NoProfile','-NonInteractive','-File',str(script)],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.DEVNULL)
                    try:code=child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        child.kill();child.wait(timeout=1);self.fail('bounded pure PowerShell selection timed out')
                self.assertEqual(code,0);record=json.loads(output.read_bytes())
                self.assertEqual(set(record),{'accepted','pathObserved','machine','pathCode'})
                self.assertIs(record['accepted'],accepted);self.assertIs(record['pathObserved'],accepted)
                self.assertEqual(record['machine'],machine);self.assertEqual(record['pathCode'],path_code)

if __name__=='__main__':unittest.main()
