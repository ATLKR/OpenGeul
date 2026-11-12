import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class NativeEntryTests(unittest.TestCase):
    def test_fixed_entry_cannot_reach_getters_and_rejects_forged_results(self):
        self.assertTrue((ROOT/'sdk_smoke.hpp').is_file(),'fixed native entry implementation required')
        self.assertTrue(Path('/usr/bin/g++').is_file(),'preinstalled portable compiler required')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);exe=root/'entry-test'
            spec=[['/usr/bin/g++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(ROOT),'-I'+str(ROOT/'frozen-v2'),str(ROOT/'tests/native_entry_tests.cpp'),'-o',str(exe)], [str(exe)]]
            for command in spec:
                p=subprocess.Popen(command,cwd=root,env={'PATH':'/usr/bin:/bin'},stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                try:code=p.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=1);self.fail('owned portable compilation or test timed out')
                self.assertEqual(code,0,'portable fixed-entry contract failed')
