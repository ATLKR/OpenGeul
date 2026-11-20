"""Initial engine authority: real classifier/cohort; synthetic native effects only."""
import ctypes as C
import tempfile
import unittest
from pathlib import Path
import test_writer_server_observer_prepare_native as typed
import test_writer_server_observer_runner_composition as composed
import writer_server_observer_runner as m
prepmod=typed.M
from writer_server_observer_cohort import RetainedCohort

class InitialEngine(unittest.TestCase):
    def setUp(self):m._PENDING_CASES.clear();m._CASE_STARTED=False
    def tearDown(self):m._PENDING_CASES.clear();m._CASE_STARTED=False
    def fixture(self, folder):
        r,i,c,_=composed.setup(folder)
        r.initial_engine_profile='verified-normal-restart-v1'
        r._initial_engine=None
        b=m.PreparationBudget.start(c.clock)
        launch=c.api.launch([str(c.api.images[201]),'--module','writer'],str(i.output),{},controller_binding=(700,(701,801),71))
        images={'host':c.api.images[201],'worker':c.api.images[202],'engine':c.api.images[301],
                'launcher':i.output/'Office/program/soffice.exe'}
        c.prep.process_image_observed=c.prep.process_image
        p=m.empty_report()['preparation'];p['classificationAttemptCount']=0
        return r,i,c,b,launch,images,p
    def classify(self, r,c,b,l,images,p,history=None):
        return r._classify(l,images,b,p,{} if history is None else history,(images['engine'].parent,images['host'].parent,Path('/synthetic/System32')))
    def test_complete_image_census_retains_actual_engine_handle_until_admission(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p=self.fixture(f)
            roles=self.classify(r,c,b,l,images,p)
            self.assertEqual(roles['engine'],(401,501))
            self.assertEqual(c.api.calls.count('close-301'),0)
            self.assertIsNotNone(r._initial_engine)
            self.assertEqual(r._initial_engine.lease.handle,301)
    def test_partial_unknown_census_never_publishes_an_engine_lease(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p=self.fixture(f)
            old_open,old_identity,old_member=c.api.open_initial_member,c.api.identity,c.api.member
            c.api.census=lambda job:(101,301,401,999)
            c.api.open_initial_member=lambda pid,job:999 if pid==999 else old_open(pid,job)
            c.api.identity=lambda handle:(999,9999) if handle==999 else old_identity(handle)
            c.api.member=lambda handle,job:True if handle==999 and job==1000 else old_member(handle,job)
            c.api.images[999]=i.output/'unknown.exe';c.api.images[999].write_bytes(b'SYNTHETIC')
            with self.assertRaises(Exception):self.classify(r,c,b,l,images,p)
            self.assertTrue(r._initial_engine is None or r._initial_engine.lease is None)
            self.assertEqual(c.api.calls.count('close-301'),1)
    def test_history_without_current_verified_image_cannot_authorize_retirement(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p=self.fixture(f)
            error=prepmod.PreparationError(prepmod.PreparationCode.IMAGE);error._image_query_facts=(False,32768,5)
            def image(handle,check):
                if handle==301:raise error
                return str(c.api.images[handle])
            c.prep.process_image=c.prep.process_image_observed=image
            try:self.classify(r,c,b,l,images,p,{'engine':(401,501)})
            except Exception as actual:self.assertIs(actual,error)
            else:self.fail('unverified initial image admitted')
    def test_qfpi_failure_facts_are_captured_before_the_post_call_clock(self):
        api=prepmod.PreparationNativeApi.__new__(prepmod.PreparationNativeApi)
        api._last_qpc=None;api._clock_invalid=False
        value={'error':5,'qpc':100}
        def query(handle,flags,buffer,length):return 0
        api._image=query;api._image_last_error=lambda:value['error']
        def check():value['qpc']+=1;value['error']=99;return value['qpc']
        # The foreign call resets the synthetic last-error, as real use_last_error does.
        def actual_query(*args):value['error']=5;return query(*args)
        api._image=actual_query
        observed=getattr(api,'process_image_observed',api.process_image)
        try:observed(301,check=check)
        except prepmod.PreparationError as error:
            self.assertEqual(error.code,prepmod.PreparationCode.IMAGE)
            self.assertEqual(getattr(error,'_image_query_facts',None),(False,32768,5))
        else:self.fail('IMAGE failure lost')

    def verified(self, folder):
        r,i,c,b,l,images,p=self.fixture(folder)
        roles=self.classify(r,c,b,l,images,p)
        return r,i,c,b,l,images,p,roles
    def attachment(self, launch, pid=401):
        return prepmod.OriginalAttachment(600,602,601,101,71,pid,611,
            _host_handle=launch.host,_thread_handle=launch.thread,_host_birth=111)
    def test_confirmed_normal_exit_retires_same_handle_without_query_then_requires_absence(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p,roles=self.verified(f)
            state=c.api.state
            c.api.state=lambda handle:(0,81) if handle==301 else state(handle)
            image=c.prep.process_image_observed
            def no_dead_query(handle,check):
                self.assertNotEqual(handle,301)
                return image(handle,check=check)
            c.prep.process_image_observed=no_dead_query
            result=self.classify(r,c,b,l,images,p,roles)
            self.assertNotIn('engine',result)
            a=r._initial_engine.record
            self.assertEqual((a['restartCount'],a['retirementOriginCode'],a['retirementWaitResult'],a['retirementExitCode']),(1,1,0,81))
            self.assertEqual(c.api.calls.count('close-301'),1)
            self.assertIsNone(r._initial_engine.lease)
            self.classify(r,c,b,l,images,p,roles)
            self.assertIsNot(a['retiredCandidateAbsent'],True)
            c.api.census=lambda job:(101,301)
            self.classify(r,c,b,l,images,p,roles)
            self.assertIs(a['retiredCandidateAbsent'],True)
    def test_false_image_primary_can_retire_only_its_same_verified_handle(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p,roles=self.verified(f)
            native=c.api.state;dead=[False]
            c.api.state=lambda h:(0,81) if h==301 and dead[0] else ((258,81) if h==301 else native(h))
            error=prepmod.PreparationError(prepmod.PreparationCode.IMAGE)
            error._image_query_facts=(False,32768,5)
            image=c.prep.process_image_observed
            def query(h,check):
                if h==301:dead[0]=True;raise error
                return image(h,check=check)
            c.prep.process_image_observed=query
            self.assertNotIn('engine',self.classify(r,c,b,l,images,p,roles))
            a=r._initial_engine.record
            self.assertEqual((a['retirementOriginCode'],a['imageCallReturned'],a['imageCallSucceeded'],a['imageCallLastError']),(2,True,False,5))
            self.assertEqual(c.api.calls.count('close-301'),1)
    def test_true_invalid_unknown_and_exit79_preserve_the_actual_image_primary(self):
        for facts,exitcode in (((True,32768,None),81),(None,81),((False,32768,5),79)):
            with self.subTest(code=exitcode,factsKnown=facts is not None), tempfile.TemporaryDirectory() as f:
                r,i,c,b,l,images,p,roles=self.verified(f)
                state=c.api.state;c.api.state=lambda h:(258,exitcode) if h==301 else state(h)
                error=prepmod.PreparationError(prepmod.PreparationCode.IMAGE);error._image_query_facts=facts
                image=c.prep.process_image_observed
                def query(h,check):
                    if h==301:raise error
                    return image(h,check=check)
                c.prep.process_image_observed=query
                try:self.classify(r,c,b,l,images,p,roles)
                except Exception as actual:self.assertIs(actual,error)
                else:self.fail('unqualified restart admitted')
                self.assertEqual(r._initial_engine.record['restartCount'],0)
    def test_failed_retirement_close_is_retained_and_never_retried(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p,roles=self.verified(f)
            state=c.api.state;c.api.state=lambda h:(0,81) if h==301 else state(h)
            c.api.fail_close=301
            with self.assertRaises(Exception):self.classify(r,c,b,l,images,p,roles)
            self.assertFalse(r._initial_engine.close_untransferred())
            self.assertEqual(c.api.calls.count('close-301'),1)
            self.assertEqual(r._initial_engine.record['pendingHandleCount'],1)
    def test_typed_peer_freezes_profile_and_cohort_takes_exact_engine_without_reopen(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p,roles=self.verified(f)
            initial=r._initial_engine
            witness=initial.freeze_peer(self.attachment(l),roles)
            cohort=RetainedCohort(c.api,l,expected_worker=roles['worker'],expected_engine=roles['engine'],
                expected_members=tuple(roles.values()),initial_engine=witness)
            initial.transfer_to(cohort)
            before=c.api.calls.count('initial-open')
            cohort.admit()
            self.assertEqual(c.api.calls.count('initial-open')-before,1)
            self.assertIs(cohort.original_engine,witness)
            with self.assertRaises(Exception):self.classify(r,c,b,l,images,p,roles)
            self.assertTrue(initial.close_untransferred())
            self.assertEqual(c.api.calls.count('close-301'),0)
    def test_invalid_typed_peer_or_live_exit81_never_reopens_profile(self):
        for wrongpid in (True,False):
            with self.subTest(wrongpid=wrongpid), tempfile.TemporaryDirectory() as f:
                r,i,c,b,l,images,p,roles=self.verified(f)
                if not wrongpid:
                    state=c.api.state;c.api.state=lambda h:(258,81) if h==301 else state(h)
                with self.assertRaises(Exception):r._initial_engine.freeze_peer(self.attachment(l,999 if wrongpid else 401),roles)
                self.assertTrue(r._initial_engine.frozen)
                with self.assertRaises(Exception):self.classify(r,c,b,l,images,p,roles)
    def test_second_engine_requires_retired_absence_and_second_restart_is_rejected(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p,roles=self.verified(f)
            native_state=c.api.state;c.api.state=lambda h:(0,81) if h==301 else native_state(h)
            self.classify(r,c,b,l,images,p,roles)
            c.api.census=lambda job:(101,301,501)
            opened,identity,member=c.api.open_initial_member,c.api.identity,c.api.member
            c.api.open_initial_member=lambda pid,job:401 if pid==501 else opened(pid,job)
            c.api.identity=lambda h:(501,601) if h==401 else identity(h)
            c.api.member=lambda h,job:True if h==401 and job==1000 else member(h,job)
            c.api.images[401]=images['engine']
            roles=self.classify(r,c,b,l,images,p,roles)
            self.assertEqual(roles['engine'],(501,601))
            self.assertEqual(r._initial_engine.record['leaseCount'],2)
            c.api.state=lambda h:(0,81) if h==401 else native_state(h)
            with self.assertRaises(Exception):self.classify(r,c,b,l,images,p,roles)
            self.assertEqual(r._initial_engine.record['restartCount'],1)

    def composed_case(self, folder, restart=False, deny_original=False, close_boundary=None, **changes):
        m._PENDING_CASES.clear();m._CASE_STARTED=False
        r,i,c,_=composed.setup(folder)
        r.initial_engine_profile='verified-normal-restart-v1'
        r.admission_profile='owned-peer-before-first-admission-v1'
        c.prep.process_image_observed=c.prep.process_image
        state,identity,member,census,opened=c.api.state,c.api.identity,c.api.member,c.api.census,c.api.open_initial_member
        phase=[0]
        if restart:
            c.api.state=lambda h:(0,81) if h==301 and phase[0] else state(h)
            c.api.identity=lambda h:(501,601) if h==401 else identity(h)
            c.api.member=lambda h,j:True if h==401 and j==1000 else member(h,j)
            c.api.open_initial_member=lambda pid,j:401 if pid==501 else opened(pid,j)
            c.api.census=lambda j:((101,301,501) if j==1000 and not c.api.dead and phase[0] and 'close-301' in c.api.calls else census(j))
            c.api.images[401]=c.api.images[301]
            backend=c.Backend({},'arm64')
            backend.process_snapshot=lambda h:({'pid':501,'creationTime':601,'waitResult':258,'exitCode':259} if h==401 else (_ for _ in ()).throw(RuntimeError()))
            backend.window_binding=lambda hwnd:(501,611) if hwnd==601 else (0,0)
        def attachment(launch,pid,check):
            if restart and pid==401:phase[0]=1;return None
            return self.attachment(launch,pid)
        c.prep.find_attachment_once=attachment
        c.prep.recheck_attachment=lambda launch,a,check:type(a) is prepmod.OriginalAttachment
        if close_boundary is not None:
            original_close=c.api.close
            def close(handle):
                if handle==301 and phase[0] and close_boundary=='exception':
                    c.api.calls.append('close-301');raise OSError()
                result=original_close(handle)
                if handle==301 and phase[0] and close_boundary=='false-late':
                    c.clock.value+=56000;return False
                return result
            c.api.close=close
            if close_boundary=='before-close':
                read=c.clock.read
                c.clock.read=lambda:(read()+56000 if r._initial_engine is not None and
                    r._initial_engine.close_attempted and r._initial_engine.lease is not None else read())
        if deny_original:
            terminate,native_state=c.api.terminate_job,c.api.state
            def deny(job):
                if job==1000:c.api.calls.append('dispose-denied');return False
                return terminate(job)
            def still_live(handle):
                if 'dispose-denied' in c.api.calls and handle in (201,202,401):c.clock.value+=1000
                return native_state(handle)
            c.api.terminate_job=deny;c.api.state=still_live
        for name,value in changes.items():setattr(c.api,name,value)
        return r.execute(i),r,c
    def test_actual_composed_no_restart_transfers_one_initial_original_and_retires_it(self):
        with tempfile.TemporaryDirectory() as f:
            report,r,c=self.composed_case(f)
            self.assertEqual(report['failureCode'],0)
            a=report['initialEngineReadiness']
            self.assertEqual((a['leaseCount'],a['restartCount'],a['pendingHandleCount']),(1,0,0))
            self.assertTrue(a['initialPeerMatched'] and a['leaseTransferred'] and a['cleanupComplete'])
            self.assertEqual(c.api.calls.count('close-301'),1)
    def test_actual_composed_retired_e0_and_original_e1_have_distinct_exit_claims(self):
        with tempfile.TemporaryDirectory() as f:
            report,r,c=self.composed_case(f,True)
            self.assertEqual(report['failureCode'],0)
            a=report['initialEngineReadiness']
            self.assertEqual((a['leaseCount'],a['restartCount'],a['pendingHandleCount']),(2,1,0))
            self.assertTrue(a['retiredCandidateAbsent'] and a['leaseTransferred'] and a['cleanupComplete'])
            self.assertTrue(report['runtime']['remote_retired'])
            self.assertEqual((c.api.calls.count('close-301'),c.api.calls.count('close-401')),(1,1))
    def test_initial_numeric_authority_cannot_be_forged_by_typed_fields_alone(self):
        import copy
        with tempfile.TemporaryDirectory() as f:
            report,_,_=self.composed_case(f)
        for key,value in (('initialPeerMatched',None),('leaseCount',0),('activeLeaseCount',1),('restartCount',1)):
            with self.subTest(field=key):
                mutant=copy.deepcopy(report);mutant['initialEngineReadiness'][key]=value
                with self.assertRaises(m.RunnerFailure):m.validate_public_report(mutant)

    def test_actual_cli_passes_only_the_explicit_initial_profile(self):
        import io,contextlib
        from types import SimpleNamespace
        from unittest import mock
        with tempfile.TemporaryDirectory() as f:
            prepared=Path(f)/'prepared.json';prepared.write_text('{}')
            flags=('output','baseline','artifact','diagnostic-lock','source-lock','expected-suite-source-commit',
                'host-python','helper-script','windows','work-root','report')
            args=[v for name in flags for v in ('--'+name,str(Path(f)/name))]
            args+=['--prepared-library',str(prepared),'--admission-profile','owned-peer-before-first-admission-v1',
                '--initial-engine-profile','verified-normal-restart-v1']
            calls=[]
            def factory(c,**options):
                calls.append(options)
                return SimpleNamespace(execute=lambda inputs:m.empty_report())
            with mock.patch.object(m,'NativeComponents',lambda:SimpleNamespace(ConsoleProfile=lambda:None)), \
                    mock.patch.object(m,'DedicatedWriterRunner',factory),contextlib.redirect_stdout(io.StringIO()):
                m.main(args)
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0]['initial_engine_profile'],'verified-normal-restart-v1')
    def test_profile_requires_exact_mode_and_first_peer_admission(self):
        for mode,admission in ((True,None),('unknown',None),('verified-normal-restart-v1',None)):
            with self.subTest(modeKnown=type(mode) is str),self.assertRaises(m.RunnerFailure):
                m.DedicatedWriterRunner(object(),initial_engine_profile=mode,admission_profile=admission)
    def test_failed_generation_or_job_never_authorizes_a_retirement(self):
        for kind in ('birth','member','host'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as f:
                r,i,c,b,l,images,p,roles=self.verified(f)
                original=c.api.identity;member=c.api.member;state=c.api.state
                c.api.state=lambda h:(0,81) if h==301 else state(h)
                if kind=='birth':c.api.identity=lambda h:(401,999) if h==301 else original(h)
                elif kind=='host':c.api.identity=lambda h:(101,999) if h==201 else original(h)
                else:c.api.member=lambda h,j:False if h==301 else member(h,j)
                with self.assertRaises(Exception):self.classify(r,c,b,l,images,p,roles)
                self.assertEqual(r._initial_engine.record['restartCount'],0)
    def test_retirement_api_false_but_unknown_last_error_stays_primary(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p,roles=self.verified(f)
            error=prepmod.PreparationError(prepmod.PreparationCode.IMAGE);error._image_query_facts=(False,32768,None)
            image=c.prep.process_image_observed
            def query(h,check):
                if h==301:raise error
                return image(h,check=check)
            c.prep.process_image_observed=query
            try:self.classify(r,c,b,l,images,p,roles)
            except Exception as actual:self.assertIs(actual,error)
            else:self.fail('unknown native error admitted')
            self.assertEqual(r._initial_engine.record['restartCount'],0)
    def test_closed_numeric_schema_rejects_unknown_bool_overflow_and_impossible_restart(self):
        import copy
        with tempfile.TemporaryDirectory() as f:report,_,_=self.composed_case(f)
        for changes in ({'unknown':0},{'leaseCount':True},{'retirementSampleCount':4097},
                {'retirementConfirmed':True},{'imageCallReturned':True,'imageCallSucceeded':False},
                {'retirementWaitResult':0},{'cleanupComplete':False}):
            with self.subTest(count=len(changes)):
                mutant=copy.deepcopy(report);mutant['initialEngineReadiness'].update(changes)
                with self.assertRaises(m.RunnerFailure):m.validate_public_report(mutant)
    def test_retirement_close_late_return_is_not_closed_again(self):
        with tempfile.TemporaryDirectory() as f:
            r,i,c,b,l,images,p,roles=self.verified(f)
            state=c.api.state;c.api.state=lambda h:(0,81) if h==301 else state(h)
            close=c.api.close
            def late(h):
                result=close(h)
                if h==301:c.clock.value+=56000
                return result
            c.api.close=late
            with self.assertRaises(Exception):self.classify(r,c,b,l,images,p,roles)
            self.assertIsNone(r._initial_engine.lease)
            self.assertTrue(r._initial_engine.record['retiredHandleClosed'])
            r._initial_engine.close_untransferred()
            self.assertEqual(c.api.calls.count('close-301'),1)

    def test_retired_e0_never_claims_live_original_e1_exit_or_complete_cleanup(self):
        with tempfile.TemporaryDirectory() as f:
            report,r,c=self.composed_case(f,True,deny_original=True)
            a=report['initialEngineReadiness']
            self.assertTrue(a['retirementConfirmed'] and a['retiredHandleClosed'])
            self.assertFalse(report['runtime']['remote_retired'])
            self.assertFalse(a['cleanupComplete'])
            self.assertEqual(a['pendingHandleCount'],1)
            self.assertGreater(report['pendingRetainedCount'],0)
            self.assertEqual(c.api.calls.count('close-401'),0)
    def test_composed_prelease_failure_has_no_historical_lease_authority(self):
        with tempfile.TemporaryDirectory() as f:
            report,r,c=self.composed_case(f,member=lambda h,j:False)
            a=report['initialEngineReadiness']
            self.assertEqual(a['leaseCount'],0)
            self.assertIsNone(a['leaseImageVerified'])
            self.assertIsNone(a['leaseTransferred'])
            self.assertNotEqual(report['failureCode'],0)
            self.assertIsNone(report['preparation']['originalEngineExitObserved'])
    def test_default_strict_classifier_has_the_exact_preimage_native_call_sequence(self):
        import importlib.util
        import hashlib
        old_path=Path(__file__).with_name('fixtures')/'writer-r15-strict-classifier.py'
        self.assertEqual(hashlib.sha256(old_path.read_bytes()).hexdigest(),'5b324ff2fd4d1a0d64ff49a13c9ce1ff177cf3756a0466e23c2e8047db9c368e')
        spec=importlib.util.spec_from_file_location('_initial_preimage_runner',old_path)
        old=importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name]=old;spec.loader.exec_module(old)
        traces=[]
        for module in (old,m):
            with tempfile.TemporaryDirectory() as f:
                r,i,c,b,l,images,p=self.fixture(f)
                r=module.DedicatedWriterRunner(c)
                calls=[]
                for name in ('census','open_initial_member','identity','member','state','close'):
                    original=getattr(c.api,name)
                    def wrapped(*args,_original=original,_name=name):
                        calls.append((_name,args));return _original(*args)
                    setattr(c.api,name,wrapped)
                image=c.prep.process_image
                def image_call(handle,check):calls.append(('image',(handle,)));return image(handle,check=check)
                c.prep.process_image=image_call
                result=self.classify(r,c,b,l,images,p)
                self.assertEqual(result['engine'],(401,501));traces.append(calls)
        self.assertEqual(traces[0],traces[1])


    def test_review_close_prefixes_preserve_primary_numeric_report_without_retry(self):
        for boundary,expected_calls,expected_code in (('before-close',0,int(m.Code.LATE)),('exception',1,13),('false-late',1,int(m.Code.LATE))):
            with self.subTest(boundary=boundary),tempfile.TemporaryDirectory() as f:
                report,r,c=self.composed_case(f,True,close_boundary=boundary)
                a=report['initialEngineReadiness']
                self.assertEqual(report['failureCode'],expected_code)
                self.assertFalse(a['cleanupComplete'])
                self.assertEqual(a['pendingHandleCount'],1)
                self.assertTrue(report['captureIncomplete'])
                self.assertGreater(report['pendingRetainedCount'],0)
                self.assertEqual(c.api.calls.count('close-301'),expected_calls)

    def test_typed_fixture_reimport_keeps_the_existing_canonical_class_identity(self):
        import importlib.util,sys
        source=Path(__file__).with_name('test_writer_server_observer_prepare_native.py')
        before=sys.modules['writer_server_observer_prepare_native']
        spec=importlib.util.spec_from_file_location('_initial_repeated_typed_fixture',source)
        other=importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(other)
            self.assertIs(other.M,before)
            self.assertIs(sys.modules['writer_server_observer_prepare_native'],before)
        finally:sys.modules['writer_server_observer_prepare_native']=before

    def test_strict_preimage_fixture_rejects_an_unreviewed_live_guard_mutation(self):
        from unittest import mock
        source=Path(__file__).with_name('fixtures')/'writer-r15-strict-classifier.py'
        original=Path.read_bytes;data=original(source)
        changed=data.replace(b'if waited != 258:',b'if waited == 258:',1)
        self.assertNotEqual(data,changed)
        def read(path):return changed if path==source else original(path)
        with mock.patch.object(Path,'read_bytes',read),self.assertRaises(AssertionError):
            self.test_default_strict_classifier_has_the_exact_preimage_native_call_sequence()

class InitialWorkflow(unittest.TestCase):
    def source(self):return (Path(__file__).resolve().parents[2]/'.github/workflows/office-suite.yml').read_text()
    def test_exact_profile_and_reviewed_normal_inverse_keep_all_historical_writer_gates(self):
        import hashlib
        import test_writer_owned_caption_workflow as caption
        source=self.source()
        self.assertEqual(source.count('--initial-engine-profile'),1)
        self.assertEqual(hashlib.sha256(caption.original_bytes(source).encode()).hexdigest(),caption.T13_SHA256)
    def test_missing_duplicate_unknown_misplaced_profile_and_normal_mutation_are_rejected(self):
        import test_writer_owned_caption_workflow as caption
        source=self.source();option=' --initial-engine-profile verified-normal-restart-v1'
        mutants=(source.replace(option,'',1),source.replace(option,option+option,1),
            source.replace(option,' --initial-engine-profile unknown',1),
            source.replace(option,'',1).replace(' -- atomic --work',' -- atomic'+option+' --work',1),
            source.replace('Pillow==13.0.0','Pillow==13.0.1',1))
        for index,changed in enumerate(mutants):
            with self.subTest(index=index),self.assertRaises(ValueError):caption.original_bytes(changed)
