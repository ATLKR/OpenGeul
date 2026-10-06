import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class QueuePolicyTests(unittest.TestCase):
    def setUp(self):
        path=ROOT/'e2e/print_queue.py'
        self.assertTrue(path.is_file(),'Missing disposable-only queue policy')
        spec=importlib.util.spec_from_file_location('pq',path)
        self.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.mod)
    def test_rejects_workstations_and_self_hosted_runners(self):
        for env in [{},{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'self-hosted'}]:
            with self.assertRaises(RuntimeError):self.mod.require_host(env,'nt')
    def test_rejects_non_windows(self):
        with self.assertRaises(RuntimeError):self.mod.require_host({'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'},'posix')
    def test_accepts_disposable_windows(self):
        self.mod.require_host({'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'},'nt')
    def test_hardware_and_existing_printers_are_not_allowed(self):
        name='OpenGeul-CI-'+'a'*32
        good={'pPrinterName':name,'pDriverName':'Microsoft Print To PDF','pPortName':'PORTPROMPT:'}
        self.mod.validate_queue(good,name)
        for key,value in [('pPrinterName','Microsoft Print to PDF'),('pDriverName','Vendor hardware'),('pPortName','IP_192.168.1.1')]:
            with self.assertRaises(ValueError):self.mod.validate_queue({**good,key:value},name)
    def test_name_cannot_be_a_shell_expression_or_wildcard(self):
        for name in ['*','Microsoft Print to PDF','OpenGeul-CI-foo; Remove-Printer *']:
            with self.assertRaises(ValueError):self.mod.validate_queue({},name)
