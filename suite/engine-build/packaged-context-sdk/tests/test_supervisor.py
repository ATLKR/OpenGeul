import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

class Clock:
    def __init__(self):self.value=0.
    def __call__(self):return self.value
    def pause(self,n):self.value+=n

class KernelPort:
    """OS seam only; the actual supervisor owns every state decision."""
    def __init__(self,clock,mode='exit'):
        self.clock=clock;self.mode=mode;self.closed=[];self.kills=0;self.launches=0
        self.events=[];self.terminated=False
    def retain_current_controller(self):return 99,(500,600)
    def launch(self,argv,cwd,environment,*,controller_binding):
        self.events.append('launch');self.launches+=1
        return SimpleNamespace(job=11,host=12,thread=13,identity=(200,300),
          failure_code=0,failed=self.mode=='failed',uncertain=self.mode=='uncertain',
          pre_resume_verified=True,creation_job_membership=True,local_cleanup_complete=True)
    def identity(self,h):return (500,600) if h==99 else (200,301 if self.mode=='generation' else 300)
    def state(self,h):
        if h==99:return 258,259
        if self.mode=='unknown-exit':return 0,259
        if self.terminated:return 0,1
        if self.mode in ('hang','failed','uncertain','late'):return 258,259
        return 0,9 if self.mode=='error' else 0
    def member(self,h,j):return self.mode!='not-member'
    def census(self,j):
        if self.mode=='unknown-census':raise RuntimeError('SYNTHETIC')
        if self.terminated:return ()
        if self.mode in ('hang','failed','uncertain','generation','not-member','late'):return (200,201)
        if self.mode=='descendant':return (201,)
        return ()
    def terminate_job(self,j):
        self.events.append('terminate-job');self.kills+=1
        self.terminated=True
        if self.mode=='late':self.clock.value+=2.
        return self.mode!='kill-failure'
    def release_launch_local(self,j):self.events.append('release-local');return True
    def close(self,h):
        self.closed.append(h)
        return not (self.mode=='close-failure' and h==11)

class SupervisorTests(unittest.TestCase):
    def api(self):
        self.assertTrue((ROOT/'supervisor.py').is_file(),'bounded supervisor implementation required')
        import supervisor
        return supervisor
    def run_mode(self,mode):
        m=self.api();c=Clock();p=KernelPort(c,mode)
        env=m.child_environment(r'C:\Windows',r'C:\Program Files',r'C:\Program Files (x86)',r'C:\owned')
        result=m.Runner(p,clock=c,pause=c.pause).run([r'C:\Windows\System32\cmd.exe','/d','/c','phase.cmd'],r'C:\owned',env,3.)
        return result,p,c
    def test_success_requires_exit_zero_empty_job_and_closed_original_handles(self):
        r,p,c=self.run_mode('exit')
        self.assertTrue(r['completed']);self.assertTrue(r['cleanupProved'])
        self.assertTrue(r['rootExitObserved']);self.assertTrue(r['jobEmptyObserved'])
        self.assertEqual(set(p.closed),{11,12,13,99});self.assertEqual(p.kills,0)
    def test_finished_root_does_not_hide_live_descendant(self):
        r,p,c=self.run_mode('descendant')
        self.assertFalse(r['completed']);self.assertTrue(r['forcedCleanup'])
        self.assertTrue(r['cleanupProved']);self.assertEqual(p.kills,1)
        self.assertLessEqual(c.value,3.)
    def test_timeout_terminates_private_job_and_proves_actual_exit_before_close(self):
        r,p,c=self.run_mode('hang')
        self.assertFalse(r['completed']);self.assertTrue(r['cleanupProved'])
        self.assertTrue(r['rootExitObserved']);self.assertEqual(p.kills,1)
        self.assertEqual(set(p.closed),{11,12,13,99});self.assertLessEqual(c.value,3.)
    def test_unknown_exit_code_is_never_success(self):
        r,p,c=self.run_mode('unknown-exit');self.assertFalse(r['completed'])
    def test_nonzero_exit_is_never_success(self):
        r,p,c=self.run_mode('error');self.assertFalse(r['completed']);self.assertEqual(r['exitCode'],9)
    def test_generation_and_uncertain_launch_never_pass(self):
        for mode in ('generation','uncertain','failed','not-member','unknown-census'):
            with self.subTest(case=mode):
                r,p,c=self.run_mode(mode);self.assertFalse(r['completed'])
                self.assertEqual(set(p.closed),{11,12,13,99})
    def test_failed_close_and_late_cleanup_are_not_proved(self):
        for mode in ('close-failure','late'):
            with self.subTest(case=mode):
                r,p,c=self.run_mode(mode);self.assertFalse(r['completed']);self.assertFalse(r['cleanupProved'])
    def test_unknown_environment_is_rejected_before_retaining_or_launching(self):
        m=self.api();c=Clock();p=KernelPort(c)
        r=m.Runner(p,clock=c,pause=c.pause).run(['owned.exe'],r'C:\owned',{'GH_TOKEN':'SYNTHETIC'},3.)
        self.assertFalse(r['completed']);self.assertEqual(p.launches,0)
    def test_environment_does_not_copy_or_iterate_actual_parent_mapping(self):
        m=self.api()
        class Forbidden:
            def __getattribute__(self,n):raise AssertionError('parent environment accessed')
        from unittest.mock import patch
        import os
        with patch.object(os,'environ',Forbidden()):
            e=m.child_environment(r'C:\Windows',r'C:\Program Files',r'C:\Program Files (x86)',r'C:\owned')
        self.assertEqual(e['PATH'],r'C:\Windows\System32')
        self.assertEqual(e['TEMP'],r'C:\owned\temp')
        self.assertEqual(e['VSCMD_SKIP_SENDTELEMETRY'],'1')
        self.assertNotIn('CL',e);self.assertNotIn('GH_TOKEN',e)
    def test_shared_deadline_is_not_renewed_for_cleanup(self):
        m=self.api();c=Clock();p=KernelPort(c)
        with self.assertRaises(m.GateFailure):m.phase_deadline(5.,5.5,30)
        with self.assertRaises(m.GateFailure):m.phase_deadline(1.,200.,31)
        self.assertEqual(m.phase_deadline(10.,25.,30),25.)
