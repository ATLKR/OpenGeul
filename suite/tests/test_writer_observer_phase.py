"""Creation-owned phase wrapper, synthetic native effects only."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys

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


class AtomicFailureExit(unittest.TestCase):
    @staticmethod
    def raised(path,line,error):
        try:
            exec(compile('\n'*(line-1)+'raise error\n',str(path),'exec'),{'error':error})
        except BaseException as captured:
            return captured
        raise AssertionError('Synthetic raise did not execute')

    def test_atomic_source_coordinate_is_closed_numeric_without_formatting_arguments(self):
        m=module();formatted=[]
        class Argument:
            def __str__(self):formatted.append(1);raise AssertionError()
            def __repr__(self):formatted.append(2);raise AssertionError()
        error=self.raised(BASE/'suite/e2e/native_compiler_tools.py',61,AssertionError(Argument()))
        value=m.atomic_failure_exit(error)
        self.assertEqual(value,0x5A000000|(1<<20)|(3<<16)|61)
        self.assertEqual(formatted,[])
        self.assertIs(type(value),int)
        self.assertTrue(0<value<0x80000000)

    def test_only_exact_source_paths_and_supported_builtin_exceptions_are_encoded(self):
        m=module()
        for path,error in ((BASE/'suite/e2e/other.py',AssertionError()),
                (BASE/'suite/e2e/native_compiler_tools.py.extra',AssertionError()),
                (BASE/'suite/e2e/native_compiler_tools.py',KeyboardInterrupt())):
            with self.subTest(case=int(path.name.endswith('.extra'))):
                self.assertEqual(m.atomic_failure_exit(self.raised(path,61,error)),3)
        self.assertEqual(m.atomic_failure_exit(None),3)

    def test_deepest_allowlisted_frame_and_line_cap_are_used(self):
        m=module();inner=self.raised(BASE/'suite/e2e/native_compiler_tools.py',61,ValueError())
        error=self.raised(BASE/'suite/e2e/ascii_message_preparation.py',337,inner)
        self.assertEqual(m.atomic_failure_exit(error),0x5A000000|(5<<20)|(3<<16)|61)
        for line in (20001,65536):
            self.assertEqual(m.atomic_failure_exit(self.raised(BASE/'suite/e2e/native_compiler_tools.py',line,AssertionError())),3)

    def test_traceback_cap_refuses_partial_source_identity(self):
        m=module()
        code='def recur(n):\n if n: return recur(n-1)\n raise AssertionError()\nrecur(70)\n'
        try:exec(compile(code,str(BASE/'suite/e2e/native_compiler_tools.py'),'exec'),{})
        except AssertionError as error:self.assertEqual(m.atomic_failure_exit(error),3)

    def test_projection_never_reads_or_copies_an_ambient_environment_mapping(self):
        m=module();reads=[]
        class Unreadable:
            def reject(self,*args,**kwargs):reads.append(1);raise AssertionError()
            __getitem__=get=__iter__=keys=items=values=copy=__len__=reject
        error=self.raised(BASE/'suite/e2e/native_compiler_tools.py',61,AssertionError())
        # Replace the object itself; patch.dict would first copy the old mapping.
        with patch.object(m.os,'environ',Unreadable()):value=m.atomic_failure_exit(error)
        self.assertEqual(value,0x5A000000|(1<<20)|(3<<16)|61)
        self.assertEqual(reads,[])

    def test_atomic_child_encodes_failure_but_observe_keeps_its_original_exit_contract(self):
        m=module()
        def fail(*args,**kwargs):
            raise self.raised(BASE/'suite/e2e/native_compiler_tools.py',61,AssertionError())
        with patch.dict(sys.modules,{'ascii_message_preparation':SimpleNamespace(prepare_observer=fail),
                'writer_server_observer_runner':SimpleNamespace(main=fail)}):
            atomic=m.child(['atomic','--work','/synthetic/work','--descriptor','/synthetic/descriptor.json'])
            self.assertEqual(atomic,0x5A000000|(1<<20)|(3<<16)|61)
            self.assertEqual(m.child(['observe']),3)
        self.assertEqual(m.child(['unsupported']),3)

    def test_encoded_child_failure_preserves_original_retirement_and_failure_result(self):
        m=module();api=Api();code=0x5A000000|(1<<20)|(3<<16)|61
        api.state=lambda handle:(0,code)
        result=m.run_phase(api=api,runtime=SimpleNamespace(host_python=Path('/synthetic/python.exe'),helper_script=Path('/synthetic/phase.py')),
            child_arguments=['atomic'],seconds=6,read_value=lambda key:'/synthetic',
            environment_builder=lambda *args:{'SystemRoot':'/synthetic'},descriptor_factory=lambda *args:SimpleNamespace(nonce=71),pause=lambda value:None)
        self.assertFalse(result['passed']);self.assertTrue(result['originalChildExitObserved'])
        self.assertEqual(result['originalChildExitCode'],code)
        self.assertTrue(result['ownedJobEmpty']);self.assertTrue(result['cleanupComplete'])
        self.assertFalse(result['forcedDisposalRequested']);self.assertFalse(result['originalEngineRetirementAuthority'])


if __name__=='__main__':unittest.main()
