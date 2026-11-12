"""Synthetic CLI errors must not echo caller arguments or personal paths."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNNER=Path(__file__).resolve().parents[1]/'engine-build/dotnet_project_graph_regression/runner.py'

class ClosedCliPrivacyTests(unittest.TestCase):
    def invoke(self,arguments):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out';err=root/'err'
            with out.open('xb') as a,err.open('xb') as b:
                p=subprocess.Popen([sys.executable,'-I','-S',str(RUNNER),*arguments],
                    stdin=subprocess.DEVNULL,stdout=a,stderr=b,env={'PATH':'/usr/bin:/bin','PYTHONUTF8':'1'})
                try:code=p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1);raise AssertionError('CLI deadline') from None
            self.assertLessEqual(out.stat().st_size+err.stat().st_size,4096)
            return code,out.read_bytes()+err.read_bytes()

    def test_unknown_argument_is_not_rendered(self):
        marker='SYNTHETIC-CALLER-VALUE-DO-NOT-RENDER'
        code,raw=self.invoke(['--make','/synthetic/make','--pwsh','/synthetic/pwsh',
                             '--output','/synthetic/result.json','--unrecognized',marker])
        self.assertEqual(1,code);self.assertNotIn(marker.encode(),raw);self.assertNotIn(b'/workspace/',raw)

    def test_help_has_fixed_program_identity_and_succeeds(self):
        code,raw=self.invoke(['--help'])
        self.assertEqual(0,code);self.assertNotIn(b'/workspace/',raw)

    def test_missing_required_argument_has_only_closed_failure(self):
        code,raw=self.invoke([])
        self.assertEqual(1,code);self.assertNotIn(b'/workspace/',raw)
