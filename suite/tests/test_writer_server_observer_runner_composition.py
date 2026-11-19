"""Actual frozen controller classes; only native effects are synthetic ports."""
import ctypes as C
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE/'suite/e2e'))
import writer_server_observer_runner as runner
from writer_server_observer_win32 import OwnedLaunch
from writer_server_observer_win32 import NativeCallError, FailureCode
from writer_server_observer_lifecycle import RuntimeLayout, RuntimeSession, build_launch_environment
from writer_server_observer_cohort import RetainedCohort
from writer_server_observer_capture import Descriptor, OriginalOwnerBinding, PreparedCapture
from writer_server_observer_capture import NativeBackend
from writer_server_observer_msaa import HostRuntime, PreparedMsaaHelper


class Clock:
    frequency = 1000
    def __init__(self): self.value = 100000
    def read(self): return self.value


def negative():
    observed = {key: 0 for key in runner._OBSERVATION_MAX}
    observed.update(schemaVersion=1, stageCode=4, rootRole=10, ownerBefore=1,
        referencesAcquired=2, referencesReleased=2, variantsCreated=2, variantsCleared=2, ownerReleased=1,
        focusCall={'attempted':1,'returned':1,'hrObserved':1,'hr':0,'vtObserved':1,'rejectCode':3})
    return {'schemaVersion':1,'diagnosticOnly':1,'acceptanceEligible':0,'bodyReturned':1,'observation':observed}


class MemoryBackend:
    atomic_accessors_attested = True
    def __init__(self): self.buffer = C.create_string_buffer(131328); self.base=C.addressof(self.buffer); self.freed=0
    def controller_identity(self): return 701,801
    def create_mapping(self,name,size): return 901,False
    def map_view(self,handle,size): return self.base
    def read_word(self,address): return struct.unpack_from('<I',self.buffer,address-self.base)[0]
    def read_quad(self,address): return struct.unpack_from('<Q',self.buffer,address-self.base)[0]
    def publish_word(self,address,value): struct.pack_into('<I',self.buffer,address-self.base,value)
    def compare_exchange_word(self,address,exchange,comparand):
        old=self.read_word(address)
        if old==comparand:self.publish_word(address,exchange)
        return old
    def process_snapshot(self,handle):
        if handle!=301:raise RuntimeError()
        return {'pid':401,'creationTime':501,'waitResult':258,'exitCode':259}
    def window_binding(self,hwnd): return (401,611) if hwnd==601 else (0,0)
    def unmap_view(self,view): return True
    def close_handle(self,handle): return True
    def release_library(self): self.freed+=1; return True
    def ready(self,clock):
        for offset,value in ((156,2),(160,2),(164,1),(168,1),(196,2)):
            struct.pack_into('<I',self.buffer,offset,value)
        for offset in (200,208):struct.pack_into('<q',self.buffer,offset,clock.value)


class Native:
    def __init__(self,folder,clock,backend):
        self.folder,self.clock,self.backend=folder,clock,backend
        self.calls=[];self.dead=False;self.fail_launch=False;self.late_launch=False;self.bad_role=False
        self.fail_close=None;self.helper_bad=False;self.helper_hang=False;self.extra=False
        self.images={201:folder/'payload/OpenGeul.Office.exe',202:folder/'payload/Office/program/python-core-3.13.17/bin/python.exe',
            301:folder/'payload/Office/program/soffice.bin'}
    def retain_current_controller(self): self.calls.append('controller'); return 700,(701,801)
    def launch(self,argv,cwd,environment,*,controller_binding):
        helper='--result' in argv
        self.calls.append('helper-launch' if helper else 'office-launch')
        if 'SYNTHETIC_SECRET' in json.dumps(environment): raise RuntimeError()
        if helper:
            if not self.helper_hang:
                Path(argv[argv.index('--result')+1]).write_text('{broken' if self.helper_bad else json.dumps(negative()))
            self.backend.ready(self.clock)
            return OwnedLaunch(job=1001,host=302,thread=304,identity=(402,502),controller_handle=700,
                controller_identity=(701,801),nonce=controller_binding[2],creation_job_membership=True,
                pre_resume_verified=True,resumed=True,attributes_released=True,stdio_released=True,local_cleanup_complete=True)
        if argv != [str(self.images[201]),'--module','writer']: raise RuntimeError()
        if self.late_launch:self.clock.value+=56000
        return OwnedLaunch(job=1000,host=201,thread=203,identity=(101,111),controller_handle=700,
            controller_identity=(701,801),nonce=controller_binding[2],creation_job_membership=True,
            pre_resume_verified=True,resumed=not self.fail_launch,failed=self.fail_launch,
            attributes_released=True,stdio_released=True,local_cleanup_complete=True)
    def identity(self,handle):
        return {201:(101,111),202:(301,311),301:(401,501),302:(402,502),700:(701,801)}[handle]
    def state(self,handle):
        if handle==302:
            if self.helper_hang:self.clock.value+=1000;return 258,259
            return 0,0
        return (0,0) if self.dead and handle!=700 else (258,259)
    def member(self,handle,job): return (job==1000 and handle in (201,202,301)) or (job==1001 and handle==302)
    def census(self,job):
        if job==1001:return ()
        return () if self.dead else (101,301,401)
    def open_initial_member(self,pid,job): self.calls.append('initial-open'); return {301:202,401:301}[pid]
    def terminate_job(self,job):
        self.calls.append('dispose-'+str(job))
        if job==1000:self.dead=True
        return True
    def close(self,handle): self.calls.append('close-'+str(handle));return handle!=self.fail_close
    def release_launch_local(self,owned): self.calls.append('release-launch');return True


def setup(folder):
    root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    root=root.resolve(strict=True)
    for name in ('payload/Office/program/python-core-3.13.17/bin','payload/Office/program/python-core-3.13.17/lib/site-packages',
                 'baseline','Windows/System32','host','source/e2e','user/AppData/Roaming','user/AppData/Local'):
        (root/name).mkdir(parents=True,exist_ok=True)
    for name in ('payload/OpenGeul.Office.exe','payload/Office/program/soffice.bin','payload/Office/program/soffice.exe',
        'payload/Office/program/fundamental.ini','payload/Office/program/python-core-3.13.17/bin/python.exe',
        'host/python.exe','source/e2e/helper.py','source/e2e/writer_os_accessibility.py','source/e2e/writer_os_summary.py',
        'source/e2e/startup_smoke.py','source/e2e/windows_smoke.py','source/payload.py'):
        (root/name).write_bytes(b'SYNTHETIC')
    clock,backend=Clock(),MemoryBackend();api=Native(root,clock,backend)
    attachment=SimpleNamespace(document=600,child=601,engine_thread=611)
    def focus(ready=True):
        projection={key:True for key in runner._FOCUS_BOOL}
        projection.update(ready=ready,sampled_before_qpc=clock.value,sampled_after_qpc=clock.value)
        return SimpleNamespace(ready=ready,numeric_projection=lambda:projection)
    prep=SimpleNamespace(process_image=lambda handle,check:str(api.images[handle]),
        find_attachment_once=lambda launch,pid,check:attachment,
        recheck_attachment=lambda launch,original,check:original is attachment,
        focus_snapshot=lambda launch,original,check:focus())
    prep.synthetic_focus = focus
    def admission(**kwargs):
        kwargs['check']();clock.value+=1000;kwargs['check']()
        return {'family':'writer-server-observer-diagnostic','architecture':'arm64','diagnosticOnly':True,
            'payloadRoot':str(root/'payload'),'runtimeRoot':str(root/'payload/Office'),
            'fullEngineQualified':False,'acceptanceEligible':False,'guiVerified':False,
            'ipcVersion':1,'sinkAbiVersion':2,'mappingBytes':131328,'descriptorSchemaVersion':1,
            'binaries':[{'path':p,'bytes':1,'sha256':'0'*64,'machine':43620} for p in ('program/UAccCOM.dll','program/winaccessibility.dll')]}
    c=SimpleNamespace(api=api,clock=clock,prep=prep,require_stage=admission,Layout=RuntimeLayout,
        HostRuntime=HostRuntime,environment=build_launch_environment,Descriptor=Descriptor,Cohort=RetainedCohort,
        Session=RuntimeSession,Owner=OriginalOwnerBinding,Capture=PreparedCapture,Helper=PreparedMsaaHelper,
        Backend=lambda prepared,architecture:backend)
    inputs=runner.RunnerInputs(root/'payload',root/'baseline',root/'artifact',root/'diagnostic-lock',root/'source-lock',
        '0'*40,{},root/'host/python.exe',root/'source/e2e/helper.py',root/'Windows',root/'fresh-work')
    env={'SystemRoot':str(root/'Windows'),'WINDIR':str(root/'Windows'),'USERPROFILE':str(root/'user'),
        'APPDATA':str(root/'user/AppData/Roaming'),'LOCALAPPDATA':str(root/'user/AppData/Local'), 'SECRET':'SYNTHETIC_SECRET'}
    reads=[]
    def read(key):reads.append(key);return env[key]
    instance=runner.DedicatedWriterRunner(c,read_value=read,pause=lambda seconds: setattr(clock,'value',clock.value+max(1,int(seconds*1000))),nonce=71)
    return instance,inputs,c,reads


class Composition(unittest.TestCase):
    def setUp(self): runner._PENDING_CASES.clear();runner._CASE_STARTED=False
    def tearDown(self): runner._PENDING_CASES.clear();runner._CASE_STARTED=False

    def test_actual_retained_guard_reports_each_original_role_and_state_without_admission_changes(self):
        import test_writer_server_observer_console as console_fixture
        for target, role in ((201, 1), (202, 2), (301, 3), (305, 4), (303, 5)):
            for waited in (0, 0xffffffff):
                runner._CASE_STARTED = False
                with tempfile.TemporaryDirectory() as folder:
                    obj, inputs, c, profile, _, _ = console_fixture.Console().composed(folder)
                    identity, member, opened, census = c.api.identity, c.api.member, c.api.open_initial_member, c.api.census
                    c.api.images[305] = inputs.output / 'Office/program/soffice.exe'
                    c.api.identity = lambda handle: (601, 611) if handle == 305 else identity(handle)
                    c.api.member = lambda handle, job: job == 1000 if handle == 305 else member(handle, job)
                    c.api.open_initial_member = lambda pid, job: 305 if pid == 601 else opened(pid, job)
                    c.api.census = lambda job: census(job) + ((601,) if job == 1000 and not c.api.dead else ())
                    original_state = c.api.state; checking = [False]
                    def state(handle):
                        if checking[0] and not c.api.dead and handle == target: return waited, 0xffffffff
                        return original_state(handle)
                    c.api.state = state
                    base = c.Cohort
                    class FaultCohort(base):
                        def verify(self, budget=None):
                            checking[0] = True
                            return super().verify(budget)
                    c.Cohort = FaultCohort
                    report = obj.execute(inputs)
                prep = report['preparation']
                self.assertEqual(report['stageCode'], 4)
                self.assertEqual(report['failureCode'], 13)
                self.assertEqual(tuple(prep.get(key) for key in ('cohortFailureRoleCode',
                    'cohortFailureWaitResult', 'cohortFailureExitCode')), (role, waited, 0xffffffff))
                truncated = json.loads(json.dumps(report))
                truncated['preparation'].update(preparationFailureSourceCode=0, preparationFailureLine=None)
                runner.validate_public_report(truncated)
                self.assertTrue(prep['cohortAdmitted']); self.assertTrue(prep['cleanupComplete'])
                self.assertTrue(prep['originalEngineExitObserved']); self.assertTrue(prep['consoleAuxiliaryExitObserved'])
                self.assertEqual(report['pendingRetainedCount'], 0); self.assertEqual(prep['inputCount'], 0)
                self.assertFalse(report['normalAcceptance']); self.assertNotIn('helper-launch', c.api.calls)

    def test_member_failure_projection_is_exact_typed_and_bound_to_the_actual_exception(self):
        from writer_server_observer_lifecycle import DiagnosticFailure, FailureCode
        from writer_server_observer_cohort import RetainedProcess
        roles = {'host': (1, 11), 'worker': (2, 12), 'engine': (3, 13), 'launcher': (4, 14)}
        aux = RetainedProcess(object(), 5, 15)
        for origin, expected in (((3, 13, 0, 42), (3, 0, 42)), ((5, 15, 0xffffffff, 1), (5, 0xffffffff, 1)),
                ((3, 99, 0, 42), (0, 0, 42)), ((6, 16, 0, 42), (0, 0, 42))):
            error = DiagnosticFailure(FailureCode.GENERATION); error._member_state_origin = origin
            self.assertEqual(runner._cohort_failure_observation(error, roles, aux), expected)
            self.assertEqual(runner._cohort_failure_observation(DiagnosticFailure(FailureCode.GENERATION), roles, aux),
                (None, None, None))
        class Poison:
            def __str__(self): raise AssertionError()
            def __repr__(self): raise AssertionError()
            def __iter__(self): raise AssertionError()
        for origin in (Poison(), [3, 13, 0, 42], (3, 13, 0), (True, 13, 0, 42),
                (3, True, 0, 42), (3, 13, False, 42), (3, 13, 0, True), (3, 13, 0, 1 << 32),
                (1 << 32, 13, 0, 42), (3, 1 << 64, 0, 42), (3, 13, 258, 259)):
            error = DiagnosticFailure(FailureCode.GENERATION); error._member_state_origin = origin
            self.assertEqual(runner._cohort_failure_observation(error, roles, aux), (None, None, None))
        error = DiagnosticFailure(FailureCode.NATIVE); error._member_state_origin = (3, 13, 0, 42)
        self.assertEqual(runner._cohort_failure_observation(error, roles, aux), (None, None, None))

    def test_actual_member_failure_rejects_typed_preparation_code_or_relabelled_first_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            original = c.api.state; checking = [False]
            c.api.state = lambda handle: (0, 42) if checking[0] and not c.api.dead and handle == 201 else original(handle)
            base = c.Cohort
            class FaultCohort(base):
                def verify(self, budget=None):
                    checking[0] = True
                    return super().verify(budget)
            c.Cohort = FaultCohort
            report = obj.execute(inputs)
        self.assertEqual(report['preparation']['cohortFailureRoleCode'], 1)
        self.assertIsNone(report['preparation']['preparationFailureCode'])
        self.assertEqual(report['failureCode'], 13)
        runner.validate_public_report(report)
        for scope, field, value in (('preparation', 'preparationFailureCode', 4), (None, 'failureCode', 6)):
            altered = json.loads(json.dumps(report))
            (altered if scope is None else altered[scope])[field] = value
            with self.subTest(field=field), self.assertRaises(runner.RunnerFailure):
                runner.validate_public_report(altered)

    def test_member_failure_report_is_closed_nullable_and_rejects_impossible_correlations(self):
        fields = {'cohortFailureRoleCode': 5, 'cohortFailureWaitResult': 0xffffffff, 'cohortFailureExitCode': 0xffffffff}
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder); success = obj.execute(inputs)
        self.assertTrue(fields.keys() <= success['preparation'].keys())
        self.assertTrue(all(success['preparation'][key] is None for key in fields))
        runner._CASE_STARTED = False
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            def fail(*args, **kwargs): raise RuntimeError()
            c.prep.find_attachment_once = fail
            report = obj.execute(inputs)
        for key, maximum in fields.items():
            for value in (True, -1, maximum + 1, 'SYNTHETIC_PRIVATE'):
                altered = json.loads(json.dumps(report)); altered['preparation'][key] = value
                with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(altered)
        for values in ((1, None, None), (None, 0, 42), (1, 258, 259)):
            altered = json.loads(json.dumps(report)); altered['preparation'].update(zip(fields, values))
            with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(altered)
        altered = json.loads(json.dumps(success)); altered['preparation'].update(zip(fields, (1, 0, 42)))
        with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(altered)
        altered = json.loads(json.dumps(report)); altered['preparation']['cohortFailurePrivate'] = 1
        with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(altered)

    def test_original_typed_attachment_failure_is_closed_numeric_without_relabeling_runner_failure(self):
        import writer_server_observer_prepare_native as prepare
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder)
            def fail(*args, **kwargs):
                error = prepare.PreparationError(prepare.PreparationCode.GENERATION)
                try: exec(compile('\n' * 316 + 'raise error\n', prepare.__file__, 'exec'), {'error': error})
                except prepare.PreparationError as captured: raise captured
            c.prep.find_attachment_once = fail
            report = obj.execute(inputs)
        prep = report['preparation']
        self.assertEqual(report['failureCode'], 13)
        self.assertTrue('preparationFailureCode' in prep)
        self.assertEqual(prep['preparationFailureCode'], 4)
        self.assertEqual(prep['preparationFailureKindCode'], 18)
        self.assertEqual(prep['preparationFailureSourceCode'], 6)
        self.assertEqual(prep['preparationFailureLine'], 317)
        self.assertEqual(prep['inputCount'], 0)
        self.assertTrue(prep['cleanupComplete'])
        self.assertTrue(prep['originalEngineExitObserved'])
        self.assertNotIn('helper-launch', c.api.calls)

    def test_preparation_failure_metadata_is_unknown_on_success_and_rejects_private_or_noninteger_fields(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            obj, inputs, c, _ = setup(folder); report = obj.execute(inputs)
        fields = {'preparationFailureCode': 7, 'preparationFailureKindCode': 18,
            'preparationFailureSourceCode': 7, 'preparationFailureLine': 20000}
        self.assertTrue(fields.keys() <= report['preparation'].keys())
        self.assertTrue(all(report['preparation'][key] is None for key in fields))
        import writer_server_observer_prepare_native as prepare
        with tempfile.TemporaryDirectory() as folder:
            runner._CASE_STARTED = False
            obj, inputs, c, _ = setup(folder)
            def fail(*args, **kwargs): raise prepare.PreparationError(prepare.PreparationCode.GENERATION)
            c.prep.find_attachment_once = fail
            failure = obj.execute(inputs)
        for key, maximum in fields.items():
            for value in (True, -1, maximum + 1, 'SYNTHETIC_PRIVATE'):
                altered = json.loads(json.dumps(failure)); altered['preparation'][key] = value
                with self.subTest(field=list(fields).index(key)), self.assertRaises(runner.RunnerFailure):
                    runner.validate_public_report(altered)
        altered = json.loads(json.dumps(failure)); altered['preparation']['preparationFailurePrivate'] = 1
        with self.assertRaises(runner.RunnerFailure): runner.validate_public_report(altered)

    def test_fixture_canonicalizes_existing_parent_traversal_before_real_runner_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).resolve(strict=True)
            (base/'hop').mkdir();(base/'case').mkdir()
            supplied=base/'hop'/'..'/'case'
            self.assertTrue(supplied.is_dir())
            self.assertFalse(supplied.is_symlink())
            self.assertNotEqual(supplied,supplied.resolve(strict=True))
            obj,inputs,c,reads=setup(supplied);result=obj.execute(inputs)
            self.assertEqual(result['failureCode'],0)
            self.assertIs(result['runtime']['armed'],True)
            self.assertIs(result['msaa']['msaaVerified'],False)
            self.assertEqual(inputs.work_root.parent,base/'case')

    def test_actual_capture_lifecycle_cohort_and_watchdog_negative_join(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,reads=setup(folder);result=obj.execute(inputs)
            self.assertEqual(result['failureCode'],0)
            self.assertIs(result['captureIncomplete'],False)
            self.assertIs(result['runtime']['armed'],True)
            self.assertIs(result['runtime']['watchdog_verified'],True)
            self.assertIs(result['runtime']['remote_retired'],True)
            self.assertIs(result['runtime']['forced_disposal_requested'],True)
            self.assertIs(result['msaa']['msaaVerified'],False)
            self.assertIs(result['msaa']['getAccFocusAttempted'],True)
            self.assertIs(result['msaa']['emptyVariantObserved'],True)
            self.assertIs(result['editorFocus']['ready'],True)
            self.assertGreaterEqual(result['editorFocus']['sampled_before_qpc'],result['preparation']['startQpc'])
            self.assertIs(result['normalAcceptance'],False)
            self.assertEqual(c.api.calls.count('office-launch'),1)
            self.assertEqual(c.api.calls.count('helper-launch'),1)
            self.assertEqual(reads, ['SystemRoot','WINDIR','USERPROFILE','APPDATA','LOCALAPPDATA']*2)
            self.assertNotIn('SYNTHETIC_SECRET',json.dumps(result))
            with self.assertRaises(runner.RunnerFailure):obj.execute(inputs)

    def test_late_returned_launch_is_still_original_owned_cleanup_target(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);c.api.late_launch=True;result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertIn('dispose-1000',c.api.calls)
            self.assertIn('close-201',c.api.calls)
            self.assertNotIn('helper-launch',c.api.calls)

    def test_late_returned_controller_is_registered_before_postcheck(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.api.retain_current_controller
            def retain():
                value=original();c.clock.value+=55000;return value
            c.api.retain_current_controller=retain;result=obj.execute(inputs)
            self.assertIn('close-700',c.api.calls)
            self.assertIs(result['captureIncomplete'],True)
            self.assertNotIn('office-launch',c.api.calls)

    def test_late_returned_classification_handle_is_registered_before_postcheck(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.api.open_initial_member
            def opened(pid,job):
                value=original(pid,job);c.clock.value+=55000;return value
            c.api.open_initial_member=opened;result=obj.execute(inputs)
            self.assertIn('close-202',c.api.calls)
            self.assertIs(result['captureIncomplete'],True)
            self.assertNotIn('helper-launch',c.api.calls)

    def test_cleanup_late_native_return_cannot_be_reported_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);c.api.fail_launch=True;original=c.api.release_launch_local
            def release(owned):
                value=original(owned);c.clock.value+=61000;return value
            c.api.release_launch_local=release;result=obj.execute(inputs)
            self.assertIs(result['preparation']['cleanupComplete'],False)
            self.assertIs(result['captureIncomplete'],True)

    def test_late_backend_release_cannot_leave_preparation_cleanup_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.Backend
            def backend(prepared,architecture):
                value=original(prepared,architecture)
                def release():c.clock.value+=61000;return True
                value.release_library=release;c.clock.value+=55000;return value
            c.Backend=backend;result=obj.execute(inputs)
            self.assertIs(result['preparation']['cleanupComplete'],False)
            self.assertIs(result['captureIncomplete'],True)

    def test_classification_close_failure_stops_before_arm_and_keeps_private_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);c.api.fail_close=301;result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertGreater(result['pendingRetainedCount'],0)
            self.assertTrue(runner._PENDING_CASES)
            self.assertNotIn('helper-launch',c.api.calls)
            second,other,_,_=setup(Path(folder)/'second');blocked=second.execute(other)
            self.assertIsNone(blocked['preparation']['launchAttempted'])

    def test_wrong_job_or_unknown_native_image_cannot_reach_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);c.api.images[301]=Path(folder)/'payload/OpenGeul.Office.exe'
            result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertNotIn('helper-launch',c.api.calls)

    def test_mixed_ipc_version_in_actual_admission_descriptor_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.require_stage
            def admitted(**kwargs):
                value=original(**kwargs);value['ipcVersion']=2;return value
            c.require_stage=admitted;result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertNotIn('office-launch',c.api.calls)

    def test_no_focus_readiness_does_not_activate_or_start_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder)
            c.prep.focus_snapshot=lambda *args,**kwargs:c.prep.synthetic_focus(False)
            result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertEqual(result['preparation']['activationCount'],0)
            self.assertEqual(result['preparation']['inputCount'],0)
            self.assertNotIn('helper-launch',c.api.calls)

    def test_malformed_helper_keeps_collection_incomplete_and_retires_original_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);c.api.helper_bad=True;result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertIs(result['runtime']['remote_retired'],True)
            self.assertIsNone(result['msaa']['getAccFocusAttempted'])

    def test_failed_original_engine_close_keeps_private_cohort_and_controller(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.api.close;calls=0
            def close(handle):
                nonlocal calls
                if handle==301:
                    calls+=1
                    if calls==2:return False
                return original(handle)
            c.api.close=close;result=obj.execute(inputs)
            self.assertGreater(result['pendingRetainedCount'],0)
            self.assertNotIn('close-700',c.api.calls)
            self.assertIs(result['captureIncomplete'],True)

    def test_failed_capture_unmap_keeps_original_capture_graph_and_controller(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder)
            c.Backend({},'arm64').unmap_view=lambda view:False
            result=obj.execute(inputs)
            self.assertIs(result['runtime']['capture_release_completed'],False)
            self.assertGreater(result['pendingRetainedCount'],0)
            self.assertTrue(runner._PENDING_CASES)
            self.assertNotIn('close-700',c.api.calls)

    def test_incomplete_even_without_pending_disallows_a_second_case_instance(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);c.api.helper_bad=True;first=obj.execute(inputs)
            self.assertIs(first['captureIncomplete'],True)
            second,other,cc,_=setup(Path(folder)/'second');result=second.execute(other)
            self.assertEqual(result['failureCode'],int(runner.Code.REPEATED))
            self.assertEqual(cc.api.calls,[])

    def test_partial_cohort_admission_still_releases_local_bundle_once(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.api.open_initial_member;count=0
            def opened(pid,job):
                nonlocal count
                count+=1
                if count==3:raise NativeCallError(FailureCode.INITIAL_MEMBER,retained_handle=202)
                return original(pid,job)
            c.api.open_initial_member=opened;result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertIn('dispose-1000',c.api.calls)
            self.assertEqual(c.api.calls.count('release-launch'),1)
            self.assertEqual(c.api.calls.count('close-1000'),1)
            self.assertNotIn('close-201',c.api.calls)
            self.assertGreater(result['pendingRetainedCount'],0)

    def test_helper_host_close_failure_keeps_actual_pending_lease_and_original_engine_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);c.api.fail_close=302;result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertIs(result['runtime']['remote_retired'],True)
            self.assertGreater(result['msaa']['pendingRetainedCount'],0)
            self.assertIs(result['msaa']['cleanupComplete'],False)
            self.assertNotIn('close-700',c.api.calls)

    def test_owned_disposal_denial_leaves_original_retirement_unknown_and_other_finally_stages_run(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder)
            def deny(job):c.api.calls.append('dispose-denied');return False
            original=c.api.state
            def state(handle):
                if handle in (201,202,301) and 'dispose-denied' in c.api.calls:c.clock.value+=1000
                return original(handle)
            c.api.terminate_job=deny;c.api.state=state;result=obj.execute(inputs)
            self.assertIs(result['runtime']['remote_retired'],False)
            self.assertIs(result['runtime']['capture_release_attempted'],True)
            self.assertIs(result['runtime']['cohort_release_attempted'],True)
            self.assertGreater(result['pendingRetainedCount'],0)

    def test_required_admission_check_late_return_stops_before_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.require_stage
            def stage(**kwargs):
                result=original(**kwargs);c.clock.value+=300000;return result
            c.require_stage=stage;result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertEqual(c.api.calls,[])

    def test_admission_is_once_in_same_execute_and_handoff_precedes_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.require_stage;calls=[]
            def stage(**kwargs):
                calls.append(type(kwargs['check'].__self__).__name__)
                c.clock.value+=90000
                return original(**kwargs)
            c.require_stage=stage;result=obj.execute(inputs)
            self.assertEqual(calls,['AdmissionBudget'])
            self.assertTrue(result['admission']['completedWithinDeadline'])
            self.assertEqual(result['admission']['completedQpc'],result['preparation']['startQpc'])
            self.assertEqual(result['admission']['durationQpc'],91000)
            self.assertIs(result['captureIncomplete'],False)

    def test_numeric_admission_handoff_fields_cannot_be_rebased(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);result=obj.execute(inputs)
            for field in ('completedQpc','durationQpc','frequency'):
                changed=json.loads(json.dumps(result));changed['admission'][field]+=1
                with self.subTest(field=field):
                    with self.assertRaises(runner.RunnerFailure):runner.validate_public_report(changed)

    def test_admission_late_return_has_no_p_budget_or_p_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.require_stage
            def stage(**kwargs):
                result=original(**kwargs);c.clock.value+=300000;return result
            c.require_stage=stage;result=obj.execute(inputs)
            self.assertIs(result['preparation']['started'],False)
            self.assertIsNone(result['preparation']['cleanupAttempted'])
            self.assertIsNone(result['preparation']['startQpc'])
            self.assertIs(result['admission']['completedWithinDeadline'],False)
            self.assertEqual(c.api.calls,[])

    def test_admission_late_return_is_recorded_as_returned_without_authorizing_p(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder);original=c.require_stage
            def stage(**kwargs):
                result=original(**kwargs);c.clock.value+=300000;return result
            c.require_stage=stage;result=obj.execute(inputs)
            self.assertIs(result['admission']['consumerReturned'],True)
            self.assertIs(result['admission']['durationKnown'],False)
            self.assertIs(result['preparation']['started'],False)

    def test_actual_backend_constructor_failed_free_retains_original_owner_without_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            obj,inputs,c,_=setup(folder)
            # Reuse only the frozen portable PE/SDK fixture constructors, not
            # that component's tests. No platform DLL loader is reached.
            path=Path(__file__).with_name('test_writer_server_observer_capture.py')
            spec=importlib.util.spec_from_file_location('_runner_capture_fixtures',path)
            fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
            library_path=Path(folder)/'synthetic-atomic.dll';fixtures.pe_fixture(library_path)
            calls=[]
            kernel=fixtures.SdkLibrary({'FreeLibrary':lambda handle:calls.append(1) or 0})
            library=fixtures.SdkLibrary({})
            def loader(name,**kwargs):
                return kernel if name=='kernel32' else fixtures.SdkLibrary({}) if name=='user32' else library
            def backend(prepared,architecture):
                return NativeBackend(prepared,architecture,validator=lambda *a,**k:library_path,loader=loader)
            c.Backend=backend;result=obj.execute(inputs)
            self.assertIs(result['captureIncomplete'],True)
            self.assertGreater(result['pendingRetainedCount'],0)
            self.assertEqual(calls,[1])
            self.assertTrue(runner._PENDING_CASES)
            self.assertNotIn('helper-launch',c.api.calls)


if __name__=='__main__':unittest.main()
