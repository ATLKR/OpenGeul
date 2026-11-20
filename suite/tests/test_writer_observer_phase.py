"""Creation-owned phase wrapper, synthetic native effects only."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

BASE=Path(__file__).resolve().parents[2]


def module():
    path=BASE/'suite/e2e/writer_server_observer_phase.py'
    if not path.is_file():raise AssertionError('fresh Writer phase child wrapper absent')
    spec=importlib.util.spec_from_file_location('candidate_writer_phase',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


class Api:
    def __init__(self):self.now=1000;self.dead=False;self.calls=[];self.hang=False;self.bad_birth=False;self.fail_close=None
    def qpc_read(self):self.now+=10;return self.now
    def qpc_frequency(self):return 1000
    def retain_current_controller(self):return 21,(31,41)
    def launch(self,argv,cwd,environment,*,controller_binding):
        self.calls.append('launch');self.environment=environment
        return SimpleNamespace(job=11,host=12,thread=13,identity=(51,61),failed=False,uncertain=False,
            resumed=True,creation_job_membership=True,pre_resume_verified=True,local_cleanup_complete=True)
    def identity(self,handle):return (51,62 if self.bad_birth else 61) if handle==12 else (31,41)
    def state(self,handle):return (258,259) if self.hang and not self.dead else (0,0)
    def census(self,job):return (51,) if self.hang and not self.dead else ()
    def terminate_job(self,job):self.calls.append('terminate');self.dead=True;return True
    def release_launch_local(self,owned):self.calls.append('release');return True
    def close(self,handle):self.calls.append('close'+str(handle));return handle!=self.fail_close


class Phase(unittest.TestCase):
    def test_fresh_environment_is_built_from_only_named_bootstrap_keys(self):
        m=module();reads=[];api=Api();runtime=SimpleNamespace(host_python=Path('/synthetic/python.exe'),helper_script=Path('/synthetic/phase.py'))
        def build(read,runtime,descriptor):
            return {key:read(key) for key in ('SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA')}
        result=m.run_phase(api=api,runtime=runtime,child_arguments=['--atomic'],seconds=30,
            read_value=lambda key:reads.append(key) or '/synthetic',environment_builder=build,
            descriptor_factory=lambda *args:SimpleNamespace(nonce=71),pause=lambda value:None)
        self.assertTrue(result['cleanupComplete']);self.assertTrue(result['originalChildExitObserved'])
        self.assertEqual(reads,['SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA'])
        self.assertEqual(set(api.environment),set(reads))
        self.assertNotIn('pid',result);self.assertIs(result['normalAcceptance'],False)

    def invoke(self,api,seconds=6):
        m=module()
        return m.run_phase(api=api,runtime=SimpleNamespace(host_python=Path('/synthetic/python.exe'),helper_script=Path('/synthetic/phase.py')),
            child_arguments=['--atomic'],seconds=seconds,read_value=lambda key:'/synthetic',
            environment_builder=lambda *args:{'SystemRoot':'/synthetic'},descriptor_factory=lambda *args:SimpleNamespace(nonce=71),pause=lambda value:None)

    def test_timeout_uses_original_job_then_same_retained_child_exit(self):
        api=Api();api.hang=True;result=self.invoke(api)
        self.assertTrue(result['timedOut']);self.assertTrue(result['originalChildExitObserved'])
        self.assertEqual(api.calls.count('terminate'),1)
        self.assertFalse(result['passed'])

    def test_birth_change_is_unknown_and_original_host_handle_retained(self):
        api=Api();api.bad_birth=True;result=self.invoke(api)
        self.assertFalse(result['originalChildExitObserved']);self.assertGreater(result['pendingRetainedCount'],0)
        self.assertNotIn('close12',api.calls)

    def test_failed_host_close_is_private_pending_without_retry(self):
        api=Api();api.fail_close=12;result=self.invoke(api)
        self.assertFalse(result['cleanupComplete']);self.assertGreater(result['pendingRetainedCount'],0)
        self.assertEqual(api.calls.count('close12'),1)

    def test_no_default_or_unbounded_phase_budget_is_admitted(self):
        m=module()
        for value in (None,0,5,1201,True):
            with self.subTest(value_type=type(value).__name__):
                api=Api();result=self.invoke(api,value)
                self.assertFalse(result['passed']);self.assertEqual(api.calls,[])

    def test_frequency_failure_remains_unknown_after_frequency_recovers(self):
        api=Api();original=api.qpc_frequency;count=0
        def frequency():
            nonlocal count
            count+=1
            return 999 if count==5 else original()
        api.qpc_frequency=frequency;result=self.invoke(api)
        self.assertFalse(result['originalChildExitObserved'])
        self.assertFalse(result['cleanupComplete'])
        self.assertEqual(api.calls,['launch'])

    def test_return_after_original_deadline_starts_no_new_native_cleanup(self):
        api=Api();original=api.launch
        def launch(*args,**kwargs):
            result=original(*args,**kwargs);api.now+=60000;return result
        api.launch=launch;result=self.invoke(api,60)
        self.assertEqual(api.calls,['launch'])
        self.assertFalse(result['cleanupComplete']);self.assertGreater(result['pendingRetainedCount'],0)

    def test_late_original_identity_starts_no_state_query_or_cleanup(self):
        api=Api();identity=api.identity;state=api.state;state_calls=[]
        def late(handle):
            value=identity(handle)
            if handle==12:api.now+=60000
            return value
        def counted(handle):state_calls.append(1);return state(handle)
        api.identity=late;api.state=counted;result=self.invoke(api,60)
        self.assertEqual(state_calls,[])
        self.assertEqual(api.calls,['launch'])
        self.assertFalse(result['originalChildExitObserved']);self.assertFalse(result['cleanupComplete'])
        self.assertGreater(result['pendingRetainedCount'],0)


if __name__=='__main__':unittest.main()
