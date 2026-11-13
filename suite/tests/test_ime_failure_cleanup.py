"""Forced failure disposal preserves original proof handles and primary errors."""
import copy
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_ime_engine_retirement import Fixture, retirement


class FailureCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.f=Fixture(self.tmp.name)
        self.env=patch.dict('os.environ',self.f.environment);self.env.start();self.addCleanup(self.env.stop)
        self.lease=self.f.admit();self.events=[];self.primary=RuntimeError('original composition failure')
        self.f.record.update(success=False,error='original composition failure')
        self.f.process.poll=lambda:self.f.process.returncode
        def shell_wait(timeout):
            self.events.append(('shell-wait',timeout));self.f.clock.now+=2
            self.f.process.returncode=1;return 1
        self.f.process.wait=shell_wait
        def live(handle):
            self.events.append(('live',handle))
            row=self.f.shell if handle==111 else self.f.engine
            return dict(row,handleValue=handle,waitResult=0 if handle==111 and self.f.process.returncode is not None else 258)
        self.f.provider.live=live
        self.f.provider.set_deadline=lambda d:None
        def wait(handle,ms):
            self.events.append(('engine-wait',handle,ms));return dict(api='WaitForSingleObject',handleValue=handle,timeoutMilliseconds=ms,result=0,lastError=0)
        self.f.provider.wait_cleanup=wait
        oldclose=self.f.provider.close
        def close(handle):self.events.append(('close',handle));return oldclose(handle)
        self.f.provider.close=close
        def run(command,**kw):
            self.events.append(('command',command,kw['timeout']));self.f.clock.now+=1
        self.run=run
    def cleanup(self,run=None):
        self.assertTrue(hasattr(self.lease,'cleanup_failed'),'Missing retained failure teardown')
        self.lease.cleanup_failed(self.primary,run=run or self.run)
        return self.f.record['imeFailureCleanup']
    def test_one_command_and_shared_exit_budget_precede_release(self):
        r=self.cleanup()
        commands=[e for e in self.events if e[0]=='command']
        self.assertEqual(commands[0][1],['taskkill.exe','/PID','101','/PID','20','/T','/F'])
        self.assertEqual(len(commands),1)
        self.assertIn(('engine-wait',222,3000),self.events)
        self.assertEqual(self.events[-1],('close',222))
        self.assertTrue(r['engineExitConfirmed']);self.assertFalse(r['gracefulShutdownVerified'])
        self.assertFalse(self.lease.proof['success']);self.assertEqual(self.f.record['error'],'original composition failure')
    def test_shell_already_gone_still_targets_exact_engine(self):
        self.f.process.returncode=1
        r=self.cleanup();self.assertEqual(r['targets'],[20]);self.assertTrue(r['engineExitConfirmed'])
    def test_identity_mismatch_blocks_command_but_releases(self):
        old=self.f.provider.live
        def live(h):
            row=old(h)
            if h==222:row['creationTime']+=1
            return row
        self.f.provider.live=live;r=self.cleanup()
        self.assertFalse(any(e[0]=='command' for e in self.events));self.assertIn('error',r)
        self.assertEqual(self.events[-1],('close',222))
    def test_command_failure_is_not_retried_and_primary_is_unchanged(self):
        def run(*args,**kw):self.run(*args,**kw);raise subprocess.CalledProcessError(1,args[0])
        r=self.cleanup(run);self.assertIn('error',r)
        self.assertEqual(len([e for e in self.events if e[0]=='command']),1)
        self.assertEqual(self.f.record['error'],'original composition failure')
        self.assertEqual(self.events[-1],('close',222))
    def test_persistent_engine_timeout_cannot_qualify(self):
        self.f.provider.wait_cleanup=lambda h,ms:dict(api='WaitForSingleObject',handleValue=h,timeoutMilliseconds=ms,result=258,lastError=0)
        r=self.cleanup();self.assertFalse(r['engineExitConfirmed']);self.assertIn('error',r)
    def test_identity_queries_charge_original_command_allowance(self):
        old=self.f.provider.live
        def live(h):row=old(h);self.f.clock.now+=2;return row
        self.f.provider.live=live;self.cleanup()
        self.assertEqual([e for e in self.events if e[0]=='command'][0][2],11)
    def test_expired_command_allowance_does_not_launch(self):
        old=self.f.provider.live
        def live(h):row=old(h);self.f.clock.now+=16;return row
        self.f.provider.live=live;r=self.cleanup()
        self.assertFalse(any(e[0]=='command' for e in self.events));self.assertIn('error',r)
    def test_late_shell_exit_has_no_new_engine_wait_budget(self):
        def wait(timeout):self.f.clock.now+=6;return 1
        self.f.process.wait=wait;r=self.cleanup()
        self.assertFalse(any(e[0]=='engine-wait' for e in self.events));self.assertIn('error',r)
        self.assertEqual(self.events[-1],('close',222))

    def test_taskkill_race_is_retained_as_unconfirmed_without_retry(self):
        def run(*args,**kw):self.run(*args,**kw);raise subprocess.CalledProcessError(128,args[0])
        r=self.cleanup(run)
        self.assertEqual(r['commandExitCode'],128);self.assertFalse(r['engineExitConfirmed'])
        self.assertEqual(len([e for e in self.events if e[0]=='command']),1)
        self.assertEqual(self.events[-1],('close',222))
    def test_command_timeout_preserves_primary_and_releases(self):
        def run(*args,**kw):self.run(*args,**kw);raise subprocess.TimeoutExpired(args[0],kw['timeout'])
        r=self.cleanup(run);self.assertIn('TimeoutExpired',r['error'])
        self.assertEqual(self.f.record['error'],'original composition failure')
        self.assertEqual(self.events[-1],('close',222))
    def test_release_failure_never_claims_cleanup_success(self):
        self.f.provider.closed=False;r=self.cleanup()
        self.assertFalse(r['handleReleased']);self.assertIn('releaseError',r)
        self.assertTrue(self.lease.proof['cleanupErrors']);self.assertFalse(self.lease.proof['success'])
    def test_positive_wait_returning_late_is_not_exit_proof(self):
        old=self.f.provider.wait_cleanup
        def wait(h,ms):result=old(h,ms);self.f.clock.now+=4;return result
        self.f.provider.wait_cleanup=wait;r=self.cleanup()
        self.assertFalse(r['engineExitConfirmed']);self.assertIn('error',r)
    def test_admission_mutation_fails_closed_and_releases(self):
        self.lease.proof['admission']['native']['officePid']+=1
        r=self.cleanup();self.assertIn('error',r)
        self.assertFalse(any(e[0] in ('command','live') for e in self.events))
        self.assertEqual(self.events[-1],('close',222))
    def test_native_wait_uses_existing_handle_and_bounded_timeout(self):
        from types import SimpleNamespace
        calls=[]
        provider=object.__new__(retirement.NativeRetirementProvider)
        provider.kernel=SimpleNamespace(WaitForSingleObject=lambda h,ms:calls.append((h,ms)) or 0)
        self.assertEqual(provider.wait_cleanup(222,3000)['result'],0)
        self.assertEqual(calls,[(222,3000)])
        for invalid in (-1,5001,True,1.5):
            with self.assertRaises(AssertionError):provider.wait_cleanup(222,invalid)
        self.assertEqual(calls,[(222,3000)])

if __name__=='__main__':unittest.main()
