"""No actual Windows process/COM call: real public schema + synthetic SDK port."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE/'suite/e2e'))
from writer_server_observer_lifecycle import OriginalWriterBudget,WatchdogProof
from writer_server_observer_win32 import OwnedLaunch
from writer_server_observer_capture import Descriptor
import writer_os_accessibility as legacy


def parameters(name,values):
    def decorate(function):function.case_values=values;return function
    return decorate


raises=unittest.TestCase().assertRaises


def modules():
    result=[]
    for name in ('writer_server_observer_msaa_helper','writer_server_observer_msaa'):
        path=BASE/'suite/e2e'/f'{name}.py'
        assert path.is_file(), 'Bounded MSAA helper implementation is missing'
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        result.append(module)
    return tuple(result)


REQUEST={'officePid':101,'officeCreationTime':201,'childHwnd':301,'expectedImage':'SYNTHETIC_PINNED_IMAGE'}


def negative():
    return {'schemaVersion':1,'diagnosticOnly':1,'acceptanceEligible':0,'bodyReturned':1,
        'observation':{'schemaVersion':1,'verified':0,'stageCode':4,'hresult':0,'rootRole':10,
        'documentRole':0,'focusedRole':0,'focusedState':0,'focusVariantType':0,'parentCount':0,
        'ia2Supported':0,'textSupported':0,'ownerBefore':1,'ownerAfter':0,'referencesAcquired':2,
        'referencesReleased':2,'variantsCreated':2,'variantsCleared':2,'cleanupFailure':0,
        'cleanupHresult':0,'ownerReleased':1,'focusCall':{'attempted':1,'returned':1,
        'hrObserved':1,'hr':0,'vtObserved':1,'rejectCode':3}}}


class Clock:
    frequency=10
    value=100
    def read(self):return self.value


class Native:
    """Exact NativeApi methods, replacing only creation/wait SDK effects."""
    def __init__(self,clock):
        self.clock=clock;self.hang=False;self.late=False;self.nonzero=False;self.wrong=False
        self.malformed=False;self.partial_launch=False;self.cleanup_fail=False;self.extra_member=False
        self.terminated=False;self.calls=[];self.result_written=False;self.closed_handles=[]
    def launch(self,argv,cwd,environment,*,controller_binding):
        self.calls.append('launch')
        assert '-E' in argv and '-s' in argv and 'PYTHONHOME' not in environment
        assert 'PYTHONPATH' not in environment and 'UNO_PATH' not in environment
        path=Path(argv[argv.index('--result')+1]);self.result_path=path
        if not self.hang and not self.partial_launch:
            path.write_text('{broken' if self.malformed else json.dumps(negative()))
            self.result_written=True
        return OwnedLaunch(job=11,host=12,thread=13,identity=(21,31),controller_handle=41,
            controller_identity=(51,61),nonce=71,creation_job_membership=True,
            pre_resume_verified=True,resumed=not self.partial_launch,failed=self.partial_launch,
            attributes_released=True,stdio_released=True,local_cleanup_complete=True)
    def identity(self,handle):
        assert handle==12;self.calls.append('identity')
        return (21,32 if self.wrong else 31)
    def state(self,handle):
        assert handle==12;self.calls.append('state');self.clock.value+=10
        if self.hang and not self.terminated:return 258,259
        if self.late and self.clock.value<410:return 258,259
        return 0,1 if self.nonzero else 0
    def member(self,handle,job):
        assert (handle,job)==(12,11);return True
    def census(self,job):
        assert job==11;return (99,) if self.extra_member else ()
    def terminate_job(self,job):
        assert job==11;self.calls.append('terminate');self.terminated=True;return True
    def close(self,handle):
        assert handle in (11,12,13);self.calls.append('close');self.closed_handles.append(handle);return not self.cleanup_fail
    def release_launch_local(self,owned):
        assert type(owned) is OwnedLaunch;self.calls.append('release');return not self.cleanup_fail


def setup(mod,folder):
    root=Path(folder)
    for name in ('host','Windows/System32','temp','Office/program','user/AppData/Roaming','user/AppData/Local','source'):
        (root/name).mkdir(parents=True,exist_ok=True)
    python=root/'host/python.exe';python.write_bytes(b'SYNTHETIC_HOST')
    script=root/'source/helper.py';script.write_text('# synthetic')
    for name in ('writer_os_accessibility.py','writer_os_summary.py','startup_smoke.py','windows_smoke.py'):
        (script.parent/name).write_text('# synthetic prepared public source')
    (script.parent.parent/'payload.py').write_text('# synthetic prepared public guard')
    runtime=mod.HostRuntime.validated(python,script,root/'Windows',root/'temp',root/'Office/program')
    values={'SystemRoot':str(root/'Windows'),'WINDIR':str(root/'Windows'),'USERPROFILE':str(root/'user'),
        'APPDATA':str(root/'user/AppData/Roaming'),'LOCALAPPDATA':str(root/'user/AppData/Local')}
    return root,runtime,values


def prepared(mod,folder):
    root,runtime,values=setup(mod,folder)
    clock=Clock();api=Native(clock)
    probe=mod.PreparedMsaaHelper(runtime,api,(41,(51,61),71),Descriptor(51,61,71),REQUEST,
        values.__getitem__,root/'results')
    probe.prepare()
    return probe,api,clock,OriginalWriterBudget.start(clock)


def test_fresh_host_environment_never_uses_office_python_home(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        root,runtime,values=setup(mod,folder);reads=[]
        env=mod.build_host_environment(lambda key:reads.append(key) or values[key],runtime,Descriptor(51,61,71))
        assert reads==['SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA']
        assert 'PYTHONHOME' not in env and 'PYTHONPATH' not in env and 'URE_BOOTSTRAP' not in env
        assert str(root/'Office') not in env['PATH'] and str(root/'host') in env['PATH']
        assert 'SYNTHETIC_HOST' not in repr(runtime)


def test_office_python_cannot_be_relabelled_host_runtime(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        root,runtime,values=setup(mod,folder)
        python=root/'Office/program/python.exe';python.write_bytes(b'SYNTHETIC_OFFICE')
        with raises(mod.WatchdogError):
            mod.HostRuntime.validated(python,runtime.helper_script,runtime.windows,runtime.temp,runtime.office_program)


def test_runtime_requires_adjacent_prepared_public_msaa_sources(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        root,runtime,values=setup(mod,folder)
        (runtime.helper_script.parent/'writer_os_accessibility.py').unlink()
        with raises(mod.WatchdogError):
            mod.HostRuntime.validated(runtime.host_python,runtime.helper_script,runtime.windows,runtime.temp,runtime.office_program)


def test_runtime_requires_prepared_guard_import_dependency(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        root,runtime,values=setup(mod,folder)
        (runtime.helper_script.parent.parent/'payload.py').unlink()
        with raises(mod.WatchdogError):
            mod.HostRuntime.validated(runtime.host_python,runtime.helper_script,runtime.windows,runtime.temp,runtime.office_program)


def test_valid_negative_msaa_is_completed_transport_without_acceptance(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder)
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert type(proof) is WatchdogProof and proof.budget is budget
        assert proof.completed is True and proof.timed_out is False and proof.partial is False
        assert proof.original_helper is proof.exit_helper
        result=probe.numeric_result()
        assert result['msaaVerified'] is False and result['observation']['focusVariantType']==0
        assert result['observation']['focusCall']['rejectCode']==3
        assert result['normalAcceptance']==0 and result['hardDeadlineEnforcementVerified'] is False
        assert 'terminate' not in api.calls
        assert all(key not in json.dumps(result) for key in ('officePid','childHwnd','expectedImage','nonce'))


@parameters('change',['wrong','nonzero','malformed','partial_launch','extra_member'])
def test_failed_unknown_or_partial_helper_never_becomes_completed(helper,mod,change):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);setattr(api,change,True)
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert proof.completed is False and proof.partial is True


def test_cutoff_terminates_only_original_helper_job_and_observes_exit_by_original_d(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);api.hang=True
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert proof.completed is False and proof.timed_out is True
        assert api.calls.count('terminate')==1
        assert proof.helper_exit_observed is True and proof.helper_exit_qpc<400
        assert proof.original_helper is proof.exit_helper


def test_exit_after_d_is_not_deadline_exit_proof(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);api.hang=api.late=True
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert proof.completed is False and proof.partial is True
        assert proof.helper_exit_qpc is None


@parameters('change',['late','wrong'])
def test_unconfirmed_original_helper_handle_stays_private_and_pending(helper,mod,change):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder)
        if change=='late':api.hang=api.late=True
        else:api.wrong=True
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert proof.completed is False
        assert 12 not in api.closed_handles
        result=probe.numeric_result()
        assert result.get('pendingRetainedCount')==1 and result.get('cleanupComplete') is False
        assert callable(getattr(probe,'pending_leases',None))
        leases=probe.pending_leases()
        assert leases[0].handle==12 and leases[0].expected_identity==(21,31)
        assert '21' not in repr(leases[0])
        calls=len(api.calls);probe.close_local()
        assert len(api.calls)==calls and probe.pending_leases()==leases


def test_close_failure_retains_original_confirmed_helper_lease(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);api.cleanup_fail=True
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert proof.completed is False and proof.helper_exit_observed is True
        result=probe.numeric_result()
        assert result.get('pendingRetainedCount',0)>=3 and result.get('cleanupComplete') is False
        assert callable(getattr(probe,'pending_leases',None))
        host=[lease for lease in probe.pending_leases() if lease.kind_code==2]
        assert len(host)==1 and host[0].handle==12 and host[0].original_witness is proof.original_helper


def test_valid_negative_has_no_pending_retained_resources(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder)
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        result=probe.numeric_result()
        assert proof.completed is True and result['msaaVerified'] is False
        assert result.get('pendingRetainedCount')==0 and result.get('cleanupComplete') is True


def test_cleanup_failures_are_numeric_and_do_not_erase_negative_result(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);api.cleanup_fail=True
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        result=probe.numeric_result()
        assert result['cleanupErrors'] and result['msaaVerified'] is False
        assert result['observation']['focusCall']['rejectCode']==3
        assert proof.partial is True


def test_result_descriptor_close_failure_preserves_observation_and_is_independent(helper,mod):
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder)
        original_close=mod.os.close
        def failed_close(descriptor):
            original_close(descriptor)
            raise OSError('SYNTHETIC_CLOSE_ERROR')
        with patch.object(mod.os,'close',failed_close):
            proof=probe.invoke_original(budget,pause=lambda seconds:None)
        result=probe.numeric_result()
        assert proof.partial is True and proof.completed is False
        assert type(result['observation']) is dict
        assert result['observation']['focusCall']['rejectCode']==3
        assert 5 in result['cleanupErrors'] and 'SYNTHETIC_CLOSE_ERROR' not in json.dumps(result)
        assert result.get('pendingRetainedCount',0)>=1
        assert any(lease.kind_code==5 for lease in probe.pending_leases())


def test_invocation_is_one_time_and_never_rebases_budget(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);probe.invoke_original(budget,pause=lambda seconds:None)
        with raises(mod.WatchdogError):probe.invoke_original(budget,pause=lambda seconds:None)
        assert api.calls.count('launch')==1 and budget.deadline_qpc==400


@parameters('change',['rollback','frequency'])
def test_unknown_clock_failure_is_partial_without_synthesized_timeout(helper,mod,change):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder)
        if change=='rollback':clock.value=99
        else:clock.frequency=11
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert proof.partial is True and proof.completed is False and proof.timed_out is False
        result=probe.numeric_result()
        assert result['childOwnerAdmissionVerified'] is None


def test_closed_helper_cannot_launch_after_local_release(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);probe.close_local()
        with raises(mod.WatchdogError):probe.invoke_original(budget,pause=lambda seconds:None)
        assert 'launch' not in api.calls


def test_failed_resume_still_tracks_creation_retained_helper_for_cleanup(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);api.partial_launch=True
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert proof.completed is False and proof.partial is True
        assert proof.original_helper is not None and proof.original_helper is proof.exit_helper
        assert proof.helper_exit_observed is True and proof.helper_exit_qpc<400


def test_unexpected_job_member_is_explicitly_disposed_on_failure(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        probe,api,clock,budget=prepared(mod,folder);api.extra_member=True
        proof=probe.invoke_original(budget,pause=lambda seconds:None)
        assert proof.partial is True and proof.completed is False
        assert api.calls.count('terminate')==1


@parameters('change',['oversize','duplicate','unknown','nested','identity','gui','nul','partial'])
def test_decoder_rejects_nonclosed_result_without_echo(helper,mod,change):
    value=negative()
    if change=='unknown':value['unknown']=1
    if change=='nested':value['observation']['rootRole']={'Name':'SYNTHETIC_PRIVATE'}
    if change=='identity':value['observation']['officePid']=101
    if change=='gui':value['observation']['guiFocus']={'Text':'SYNTHETIC_PRIVATE'}
    data=json.dumps(value).encode()
    if change=='oversize':data=b' '*4097
    if change=='duplicate':data=b'{"schemaVersion":1,"schemaVersion":1}'
    if change=='nul':data+=b'\0'
    if change=='partial':data=data[:-1]
    with raises(mod.WatchdogError) as caught:mod.decode_result(data,REQUEST)
    assert 'SYNTHETIC_PRIVATE' not in str(caught.exception)


def test_helper_exclusive_write_never_overwrites_existing_result(helper,mod):
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'result.json';path.write_bytes(b'SYNTHETIC_PREEXISTING')
        with raises(helper.HelperError):helper.write_exclusive(path,negative())
        assert path.read_bytes()==b'SYNTHETIC_PREEXISTING'


def test_raw_body_composition_preserves_negative_focus_call_and_avoids_gui_observer(helper,mod):
    class Owner(legacy.WindowsOwner):
        def open(self):pass
        def check(self,*,full=False):pass
        def close(self):return True
    class Raw(legacy.RawComBackend):
        def __init__(self,guard,record):self.record=record
        def root(self,hwnd):self.record['referencesAcquired']=1;return 1
        def identity(self,p):self.record['referencesAcquired']+=1;return p
        def role(self,p):self.record['variantsCreated']+=1;return 10
        def focus(self,p):
            assert not hasattr(self,'_gui_focus_observer')
            self.record['variantsCreated']+=1
            self.record['focusCall']={'attempted':1,'returned':1,'hrObserved':1,'hr':0,'vtObserved':1,'rejectCode':3}
            raise legacy.ProbeFailure()
        def close(self):
            self.record['referencesReleased']=self.record['referencesAcquired']
            self.record['variantsCleared']=self.record['variantsCreated'];return True
    result=helper.run_raw_observation(REQUEST,owner_factory=Owner,raw_backend_factory=Raw)
    assert result==negative()
    assert 'guiFocus' not in result['observation']


def load_tests(loader,tests,pattern):
    suite=unittest.TestSuite()
    for name,function in sorted(tuple(globals().items())):
        if not name.startswith('test_') or not callable(function):continue
        for index,value in enumerate(getattr(function,'case_values',[None])):
            def run(function=function,value=value):
                helper,mod=modules()
                if hasattr(function,'case_values'):function(helper,mod,value)
                else:function(helper,mod)
            suite.addTest(unittest.FunctionTestCase(run,description=f'{name}[{index}]'))
    return suite
