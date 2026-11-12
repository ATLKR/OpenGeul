import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def explicit_environment(module):
    return {**{k:'synthetic' for k in module.ENV_KEYS},'DOTNET_GENERATE_ASPNET_CERTIFICATE':'false','DOTNET_ADD_GLOBAL_TOOLS_TO_PATH':'false'}

class RuntimeTests(unittest.TestCase):
    def module(self):
        self.assertTrue((ROOT/'runtime/bounded.py').is_file(),'bounded runtime is required')
        from runtime import bounded
        return bounded
    def test_deadline_is_shared_and_cannot_be_renewed(self):
        m=self.module();self.assertEqual(m.phase_deadline(8.,9.5,60),9.5)
        with self.assertRaises(m.ProbeFailure):m.phase_deadline(9.,9.,60)
        with self.assertRaises(m.ProbeFailure):m.phase_deadline(1.,90.,61)
    def test_child_environment_contains_only_fresh_allowlist(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as td:
            e=m.child_environment(Path(td),r'C:\Windows',r'C:\Program Files\dotnet')
            self.assertEqual(set(e),m.ENV_KEYS)
            self.assertEqual(e['DOTNET_CLI_TELEMETRY_OPTOUT'],'1')
            self.assertNotIn('GH_TOKEN',e);self.assertNotIn('HOME',e)
            self.assertTrue(all(type(v) is str for v in e.values()))
    def test_numeric_logger_cannot_accept_unknown_or_string_payload(self):
        m=self.module()
        valid={k:0 for k in ('rootProjectCode','known','loggerFailed','overflow','buildStarted','buildFinished','buildSucceeded','copyLocalKnown','copyLocalSeen','errorCount','cs2012Count','otherErrorCount')}
        valid.update(schemaVersion=1,phase=2,rootProjectCode=3)
        valid.update({k:[0]*7 for k in ('projectStarted','projectFinished','cscStarted','cscFinished','cscSucceeded','targetPathSeen','targetPathMatched','targetPathForeign','targetPathUnknown')})
        accepted=True
        try:m.numeric_logger(valid,2)
        except m.ProbeFailure:accepted=False
        self.assertTrue(accepted,'exact typed logger protocol must be admitted')
        for key,value in [('raw','never-copy'),('errorCount','0')]:
            x=dict(valid);x[key]=value
            with self.assertRaises(m.ProbeFailure):m.numeric_logger(x,2)
    def test_retained_job_cleanup_never_reopens_pid_or_extends_deadline(self):
        m=self.module();clock=Clock();api=FakeApi(clock,root_exits=False,held_child=True)
        runner=m.Runner(api,clock=clock,pause=clock.pause)
        result=runner.run([(['owned.exe'],r'C:\owned',explicit_environment(m))],3.)
        self.assertFalse(result['completed']);self.assertTrue(result['cleanupProved'])
        self.assertLessEqual(clock.now,3.);self.assertEqual(api.terminations,1)
        self.assertEqual(api.closed,{11,12,13,99})
    def test_completed_parent_does_not_hide_live_descendant(self):
        m=self.module();clock=Clock();api=FakeApi(clock,root_exits=True,held_child=True)
        result=m.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],r'C:\owned',explicit_environment(m))],3.)
        self.assertFalse(result['completed']);self.assertTrue(result['forcedCleanup'])
        self.assertEqual(api.terminations,1);self.assertLessEqual(clock.now,3.)
    def test_sibling_jobs_keep_one_original_deadline(self):
        m=self.module();clock=Clock();api=FakeApi(clock,root_exits=True,held_child=False)
        result=m.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],r'C:\owned',explicit_environment(m)),(['owned.exe'],r'C:\owned',explicit_environment(m))],3.)
        self.assertTrue(result['completed']);self.assertEqual(len(result['children']),2)
        self.assertEqual(result['deadline'],3.);self.assertFalse(result['forcedCleanup'])
    def test_foreign_or_uncertain_launch_is_failure_and_is_not_resumed_again(self):
        m=self.module();clock=Clock();api=FakeApi(clock,root_exits=True,held_child=False,failed=True)
        result=m.Runner(api,clock=clock,pause=clock.pause).run([(['owned.exe'],r'C:\owned',explicit_environment(m))],3.)
        self.assertFalse(result['completed']);self.assertLessEqual(clock.now,3.)
    def test_framework_and_project_reference_are_not_silently_retargeted(self):
        self.assertTrue((ROOT/'runtime/fixture.py').is_file(),'fixture renderer is required')
        from runtime import fixture
        self.assertTrue(callable(fixture.render))
        self.assertEqual(fixture.CORE,'9dea406ab7695df6325b11b0e19fdca8db4b7276')
class Clock:
    def __init__(self):self.now=0.
    def __call__(self):return self.now
    def pause(self,n):self.now+=n
class FakeApi:
    def __init__(self,clock,root_exits,held_child,failed=False):
        self.clock=clock;self.root_exits=root_exits;self.held=held_child;self.failed=failed;self.closed=set();self.terminations=0;self.count=0
    def retain_current_controller(self):return 99,(100,101)
    def launch(self,argv,cwd,env,controller_binding):
        self.count+=1;n=self.count
        return SimpleNamespace(job=10*n+1,host=10*n+2,thread=10*n+3,identity=(200+n,300+n),failed=self.failed,uncertain=False,resumed=True,creation_job_membership=True,pre_resume_verified=True,local_cleanup_complete=True,failure_code=0)
    def identity(self,h):return (100,101) if h==99 else (200+h//10,300+h//10)
    def state(self,h):return (0,0) if self.root_exits or self.terminations else (258,259)
    def member(self,h,j):return True
    def census(self,j):return (500,) if self.held and not self.terminations else ()
    def terminate_job(self,j):self.terminations+=1;return True
    def close(self,h):self.closed.add(h);return True
