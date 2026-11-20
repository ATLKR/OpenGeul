import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ast
import re
import shutil
import copy

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / 'scripts/korean_fod_acquire_silent.py'
PWSH = shutil.which('pwsh')

def child_environment(root, source=None, windows=None):
    source = os.environ if source is None else source
    windows = os.name == 'nt' if windows is None else windows
    system = (source.get('SystemRoot') or source.get('WINDIR') or '') if windows else 'X:\\Windows'
    path = str(Path(sys.executable).parent) + os.pathsep + (str(Path(system) / 'System32') if windows else os.defpath)
    return {'SystemRoot':system, 'WINDIR':system, 'PATH':path, 'TEMP':str(root), 'TMP':str(root)}


def assert_gate_numeric(row):
    # Every fixed synthetic gate must complete exactly once.
    expected_ids=frozenset((*range(1,18),*range(21,25),*range(27,31)))
    valid=(type(row) is dict and set(row)=={'schemaVersion','ran','failed','cases','unsafeAttempts'}
           and all(type(row[k]) is int and 0<=row[k]<=32 for k in ('schemaVersion','ran','failed','unsafeAttempts'))
           and type(row['cases']) is list and len(row['cases'])==25
           and all(type(x) is dict and set(x)=={'case','ok'} and type(x['case']) is int and 1<=x['case']<=32 and type(x['ok']) is bool for x in row['cases'])
           and row['unsafeAttempts']==0 and row['schemaVersion']==1 and row['failed']==0
           and row['ran']==25 and len({x['case'] for x in row['cases']})==25
           and {x['case'] for x in row['cases']}==expected_ids
           and all(x['ok'] for x in row['cases']))
    if not valid:raise AssertionError('Synthetic gate result rejected')


class FodGateResultTests(unittest.TestCase):
    def test_empty_missing_duplicate_and_failed_rows_are_rejected(self):
        ids=[*range(1,18),*range(21,25),*range(27,31)]
        good={'schemaVersion':1,'ran':25,'failed':0,'unsafeAttempts':0,
              'cases':[{'case':number,'ok':True} for number in ids]}
        assert_gate_numeric(good)
        bad=[]
        row=copy.deepcopy(good);row.update(ran=0,cases=[]);bad.append(('empty',row))
        row=copy.deepcopy(good);row['cases'].pop();row['ran']=24;bad.append(('missing',row))
        row=copy.deepcopy(good);row['cases'][-1]=dict(row['cases'][0]);bad.append(('duplicate',row))
        row=copy.deepcopy(good)
        for item in row['cases']:item['ok']=False
        bad.append(('all_false',row))
        row=copy.deepcopy(good);row['cases'][0]['ok']=False;bad.append(('one_false',row))
        for kind,row in bad:
            with self.subTest(kind=kind),self.assertRaises(AssertionError):assert_gate_numeric(row)


class WrapperTests(unittest.TestCase):
    def run_fixture(self, body, *, pin_ok=True, poison_env=False):
        self.assertTrue(WRAPPER.is_file())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / 'fixture.py'
            helper.write_text(body)
            pin = hashlib.sha256(helper.read_bytes()).hexdigest() if pin_ok else '0' * 64
            # Only the synthetic module object's pin/path checks are replaced.
            # Production wrapper and helper files remain unchanged.
            launcher = ("import importlib.util,sys,builtins;from pathlib import Path;"
                "s=importlib.util.spec_from_file_location('fixed',sys.argv[1]);"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                "m.HELPER_SHA256=sys.argv[4];builtins._fod_forbidden_count=0;"
                + ("import os;os.environ=type('SyntheticEnvironment',(),"
                   "{'__getitem__':lambda *a:(_ for _ in ()).throw(AssertionError()),"
                   "'get':lambda *a:(_ for _ in ()).throw(AssertionError()),"
                   "'__iter__':lambda *a:(_ for _ in ()).throw(AssertionError()),"
                   "'__contains__':lambda *a:(_ for _ in ()).throw(AssertionError())})();"
                   if poison_env else '')
                + "r=m.main([sys.argv[2],sys.argv[3]]);"
                "raise SystemExit(42 if builtins._fod_forbidden_count else r)")
            env = child_environment(root)
            p = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8', '-c', launcher,
                                  str(WRAPPER), str(helper), str(root / 'source'), pin],
                                 env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            # Match the production parent: accept/read zero console bytes.
            p.stdout.close();p.stderr.close()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill();p.wait(timeout=2)
                raise AssertionError('Bounded owned fixture timeout') from None
            return p.returncode

    def test_noise_and_eof_are_discarded_before_import(self):
        code = "import os\nassert os.read(0,1)==b''\nos.write(1,b'x'*1048576)\nos.write(2,b'y'*1048576)\ndef acquire(output):\n os.write(1,b'z'*1048576)\n return {'success':True}\n"
        self.assertEqual(self.run_fixture(code), 0)

    def test_poison_exception_is_not_formatted(self):
        code = "import builtins\nclass Poison(BaseException):\n def __getattribute__(self,name):\n  if name in ('args','__traceback__','__str__','__repr__'):\n   builtins._fod_forbidden_count+=1\n   raise AssertionError('forbidden')\n  return super().__getattribute__(name)\n def __str__(self):\n  builtins._fod_forbidden_count+=1\n  raise AssertionError('forbidden')\n def __repr__(self):\n  builtins._fod_forbidden_count+=1\n  raise AssertionError('forbidden')\ndef acquire(output):\n raise Poison()\n"
        self.assertEqual(self.run_fixture(code), 1)

    def test_bad_source_pin_prevents_import(self):
        self.assertEqual(self.run_fixture("raise SystemExit(42)\n", pin_ok=False), 1)

    def test_false_or_partial_acquisition_is_not_success(self):
        self.assertEqual(self.run_fixture("def acquire(output): return {'success':False}\n"), 1)
        self.assertEqual(self.run_fixture("def acquire(output): return {}\n"), 1)

    def test_reviewed_helper_and_cab_pins_remain_exact(self):
        helper=ROOT/'suite/scripts/korean_fod_source.py'
        expected='50ee6a3939f5fb01507fbc405196d63e07fa5f846a022e9f35e847fd40b9ab35'
        self.assertEqual(hashlib.sha256(helper.read_bytes()).hexdigest(),expected)
        tree=ast.parse(helper.read_text())
        packages=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id=='PACKAGES' for t in n.targets))
        custody=(ROOT/'scripts/korean_fod_custody.ps1').read_text()
        literal=re.search(r"function Get-OpenGeulFodPackages \{\n    return @'\n(.*?)\n'@",custody,re.S)[1]
        self.assertEqual(json.loads(literal),packages)
        self.assertIn("HELPER_SHA256 = '"+expected+"'",WRAPPER.read_text())

    def test_synthetic_environment_object_is_not_read(self):
        class FiniteSource:
            def get(self,name):
                if name not in ('SystemRoot','WINDIR'):raise AssertionError('Unexpected environment name')
                return 'X:\\Windows'
            def __iter__(self):raise AssertionError('Environment enumeration forbidden')
        self.assertEqual(set(child_environment(Path('fixture'),FiniteSource(),windows=True)),{'SystemRoot','WINDIR','PATH','TEMP','TMP'})
        self.assertEqual(self.run_fixture("def acquire(output): return {'success':True}\n",poison_env=True),0)


@unittest.skipUnless(PWSH, 'PowerShell Core is required for synthetic custody gates')
class FodPowerShellGateTests(unittest.TestCase):
    def test_closed_protocol_clock_and_original_routes(self):
        # Same AST/function gate style as test_korean_ime_readiness; execute only
        # fixed synthetic functions, never the setup entrypoint or servicing.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for part in ('config','cache','data','runner','out'):(root/part).mkdir()
            env=child_environment(root)
            env.update({'PATH':str(Path(PWSH).parent)+os.pathsep+env['PATH'],
                'XDG_CONFIG_HOME':str(root/'config'),'XDG_CACHE_HOME':str(root/'cache'),
                'XDG_DATA_HOME':str(root/'data'),
                'RUNNER_TEMP':str(root/'runner'),'POWERSHELL_TELEMETRY_OPTOUT':'1',
                'POWERSHELL_UPDATECHECK':'Off','DOTNET_CLI_TELEMETRY_OPTOUT':'1'})
            with tempfile.TemporaryFile() as numeric_output:
                result=subprocess.run([PWSH,'-NoLogo','-NoProfile','-NonInteractive','-File',
                    str(ROOT/'tests/fixtures/korean_fod_custody_gates.ps1'),
                    '-CandidateRoot',str(ROOT),'-FixtureRoot',str(root)],env=env,
                    stdin=subprocess.DEVNULL,stdout=numeric_output,stderr=subprocess.DEVNULL,timeout=30)
                length=numeric_output.tell()
                self.assertLessEqual(length,4096,'Numeric gate result exceeded its bound')
                numeric_output.seek(0)
                raw=numeric_output.read(4097)
            try:row=json.loads(raw)
            except (ValueError,UnicodeError):self.fail('Numeric gate result unavailable')
            assert_gate_numeric(row)
            self.gate_numeric=row
            self.assertEqual(result.returncode,0)


if __name__ == '__main__':unittest.main()
