"""Dedicated CLI opt-in, closed records and original cleanup budget seams."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import test_native_menu_smoke as boundary


def preflight():
    ones=('schemaVersion','diagnosticOnly','providerLocalOnly','nativeBoundaryOnly','nativeBoundaryPassed',
        'nativeAttempted','nativeExit','threadClosed','processesClosed','workerCleanup','workerMta',
        'comInitialized','comUninitialized','dpiEntered','dpiRestored','physicalDpiVerified',
        'threadIdentity','callbackIdentity','exitCodeObserved')
    zeros=('acceptanceEligible','globalHitSubstituted','synthetic','scopeId','localKnown','localMatch',
        'workerException','pending','nativeExitCode','referencesAcquired','referencesReleased',
        'variantAttempted','cleanupError')
    return dict({key:1 for key in ones},**{key:0 for key in zeros},stageCode=13,workerStage=8,
        controllerPid=33,threadId=124,threadBirth=300)


class NativeMenuPointCliTests(unittest.TestCase):
    def fixture(self,passed=True):
        smoke=boundary.load_smoke();output=Path(self.enterContext(tempfile.TemporaryDirectory()))
        events=[];helper=NS(verify_native_thread_boundary=lambda deadline:dict(preflight(),nativeBoundaryPassed=int(passed)))
        streams=[];original=Path.open
        def opened(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            if args and any(flag in args[0] for flag in ('x','w')):streams.append(stream)
            return stream
        def finish():
            self.assertTrue(all(stream.closed for stream in streams));events.append('fence')
        setup=lambda:(NS(finish=finish),helper)
        self.enterContext(patch.object(Path,'open',opened))
        return smoke,output,events,setup

    def test_only_dedicated_cli_enables_actual_windows_session_profile_after_preflight(self):
        smoke,output,events,setup=self.fixture()
        def modules(suite,fixtures,folder,*,session_factory,point_preflight,identity_diagnostic):
            self.assertTrue((output/'native-point-preflight.json').is_file())
            self.assertEqual(point_preflight,preflight())
            session=session_factory(suite,fixtures,folder,'writer')
            self.assertIs(type(session),smoke.WindowsSession)
            self.assertTrue(session.native_point_profile)
            self.assertEqual(session.native_identity_diagnostic,3)
            self.assertEqual(identity_diagnostic,3)
            events.append('modules');return dict(success=False)
        with patch.object(smoke,'run_modules',side_effect=modules):
            result=smoke._run_point_profile(Path('/suite'),Path('/fixtures'),output,setup=setup)
        self.assertEqual(result,1);self.assertEqual(events,['modules','fence'])
        default=smoke.WindowsSession(Path('/suite'),Path('/fixtures'),output,'writer')
        self.assertFalse(default.native_point_profile)

    def test_preflight_replay_rejects_synthetic_or_unconfirmed_native_lifetime(self):
        smoke=boundary.load_smoke();smoke.require_native_point_preflight(preflight())
        for key,value in (('synthetic',1),('nativeExit',0),('callbackIdentity',0),('threadClosed',0),
                ('controllerPid',0),('physicalDpiVerified',0),('localMatch',1),('pending',1),('stageCode',11)):
            with self.subTest(key=key),self.assertRaises(AssertionError):
                smoke.require_native_point_preflight(dict(preflight(),**{key:value}))

    def test_failed_native_boundary_stops_before_ui_and_closes_failure_record_before_fence(self):
        smoke,output,events,setup=self.fixture(False)
        with patch.object(smoke,'run_modules',side_effect=AssertionError('UI must not run')):
            self.assertEqual(smoke._run_point_profile(Path('/suite'),Path('/fixtures'),output,setup=setup),1)
        self.assertEqual(events,['fence'])
        self.assertEqual(json.loads((output/'native-point-preflight.json').read_text())['nativeBoundaryPassed'],0)

    def test_base_exception_closes_emergency_numeric_record_before_explicit_fence(self):
        smoke,output,events,setup=self.fixture()
        with patch.object(smoke,'run_modules',side_effect=KeyboardInterrupt()),self.assertRaises(KeyboardInterrupt):
            smoke._run_point_profile(Path('/suite'),Path('/fixtures'),output,setup=setup)
        value=json.loads((output/'native-point-controller-failure.json').read_text())
        self.assertEqual(value['exceptionCode'],2);self.assertFalse(value['success'])
        self.assertFalse(value['acceptanceEligible']);self.assertEqual(events,['fence'])

    def test_pending_callback_retires_only_after_original_engine_exit_with_original_remainder(self):
        smoke=boundary.load_smoke();clock=NS(now=10.);calls=[]
        session=smoke.WindowsSession(Path('/suite'),Path('/fixtures'),Path('/output'),'writer')
        session.native_point_profile=True;session.process=NS(pid=77,poll=lambda:0)
        def exited(seconds):calls.append(('engine-exit',seconds));clock.now+=4.;return True
        session.engine=NS(handle=9,exited=exited,close_handle=lambda handle:True)
        session.native=NS(stop_owned_test_process=lambda process,record:None)
        lease=NS(pending=True)
        def retire(deadline):
            self.assertEqual(deadline,15.);self.assertEqual(clock.now,14.)
            calls.append(('retire',deadline));lease.pending=False;return dict(pending=0,nativeExit=1)
        lease.retire=retire
        import native_menu_msaa_hit as helper
        with patch.object(smoke.time,'monotonic',side_effect=lambda:clock.now), \
                patch.object(smoke,'_confirmed_shell_cleanup',return_value=True), \
                patch.object(helper,'pending_msaa_hit',return_value=lease):
            self.assertTrue(session.cleanup({}))
        self.assertEqual(calls,[('engine-exit',5),('retire',15.)])

    def test_unconfirmed_engine_never_retires_callback_or_authorizes_next_case(self):
        smoke=boundary.load_smoke();session=smoke.WindowsSession(Path('/suite'),Path('/fixtures'),Path('/output'),'writer')
        session.native_point_profile=True;session.process=NS(pid=77,poll=lambda:0)
        session.engine=NS(handle=9,exited=lambda seconds:False,close_handle=lambda handle:True)
        session.native=NS(stop_owned_test_process=lambda process,record:None)
        lease=NS(pending=True,retire=lambda deadline:self.fail('Unconfirmed engine cannot authorize retirement'))
        import native_menu_msaa_hit as helper
        with patch.object(smoke,'_confirmed_shell_cleanup',return_value=True),patch.object(helper,'pending_msaa_hit',return_value=lease):
            record={};self.assertFalse(session.cleanup(record))
        self.assertFalse(record['nativePointCallbackRetired'])


if __name__=='__main__':unittest.main()
