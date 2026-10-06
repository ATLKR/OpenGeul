import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'e2e'/'printing'))
from queue_policy import validate_environment, validate_queue, completed_job

class QueueSafetyTests(unittest.TestCase):
    def test_only_disposable_hosted_windows_can_provision(self):
        for env in ({},{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'self-hosted','RUNNER_OS':'Windows','GITHUB_RUN_ID':'1'},
                    {'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Linux','GITHUB_RUN_ID':'1'}):
            with self.assertRaises(ValueError):validate_environment(env)
    def test_name_has_validated_run_id(self):
        env={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows','GITHUB_RUN_ID':'123'}
        self.assertEqual(validate_environment(env),'OpenGeul-E2E-123')
        env['GITHUB_RUN_ID']='../../foo'
        with self.assertRaises(ValueError):validate_environment(env)
    def test_never_send_to_physical_driver_or_network_port(self):
        for driver,port in [('Vendor Laser','PORTPROMPT:'),('Microsoft Print To PDF','IP_192.168.1.5')]:
            with self.assertRaises(ValueError):validate_queue({'pPrinterName':'OpenGeul-E2E-1','pDriverName':driver,'pPortName':port},'OpenGeul-E2E-1')
    def test_requires_exact_owned_queue(self):
        with self.assertRaises(ValueError):validate_queue({'pPrinterName':'Other','pDriverName':'Microsoft Print To PDF','pPortName':'PORTPROMPT:'},'OpenGeul-E2E-1')
    def test_completed_job_is_new_and_printed(self):
        self.assertIsNone(completed_job([{'JobId':4,'Status':128}],{4}))
        self.assertIsNone(completed_job([{'JobId':5,'Status':16}],{4}))
        self.assertEqual(completed_job([{'JobId':5,'Status':128}],{4})['JobId'],5)
    def test_errors_and_ambiguous_jobs_are_not_success(self):
        with self.assertRaises(AssertionError):completed_job([{'JobId':5,'Status':128|2}],set())
        with self.assertRaises(AssertionError):completed_job([{'JobId':5,'Status':128},{'JobId':6,'Status':128}],set())
