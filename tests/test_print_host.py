import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'/'printing'))
from spooler import require_host
class PrintHostTests(unittest.TestCase):
    def test_hosted_windows_allowed(self):
        require_host({'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows'})
    def test_personal_pc_refused(self):
        with self.assertRaises(RuntimeError): require_host({})
    def test_self_hosted_refused(self):
        with self.assertRaises(RuntimeError): require_host({'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'self-hosted','RUNNER_OS':'Windows'})
    def test_linux_refused(self):
        with self.assertRaises(RuntimeError): require_host({'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Linux'})
