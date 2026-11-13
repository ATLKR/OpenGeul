"""Only complete, original-target callback samples may leave the bounded ABI."""
import ctypes as C
import importlib
from pathlib import Path
import unittest


class CompartmentProtocolTests(unittest.TestCase):
    def fixture(self):
        self.assertTrue((Path(__file__).resolve().parents[1] / 'e2e/ime_compartment_protocol.py').is_file())
        m = importlib.import_module('ime_compartment_protocol')
        import ime_notification_caller as notification
        config = m.Config(version=2, enabled=1)
        binding = notification.Config(version=1, enabled=1, creationTime=555)
        binding.plugin.version = binding.plugin.enabled = 1
        r = m.Record(sequence=1, pid=31, tid=41, hwnd=51, creationTime=555,
                     baselineCounter=10, counter=20, finishedCounter=40,
                     frameCount=2, unknownFrames=1, pluginStatus=1,
                     pluginStarted=25, pluginFinished=30)
        for name in ('installAttempts', 'pinned', 'sourceReady', 'adviseAttempts',
                     'subscriptionPossible', 'installed', 'armed', 'claimed'):
            setattr(r.lease, name, 1)
        r.api.referencesAcquired = 5
        r.api.sinkReferences = 2
        r.api.enumerationCount = 1
        for read in (r.api.baseline, r.api.callback):
            read.type, read.matched, read.attempts = 3, 1, 1
        r.frames[0].moduleId, r.frames[0].rva = 14, 100
        command = dict(success=True, nativeAck=3, status=0, threadMode={
            'status': 0, 'cleanupStatus': 0, 'variantClearHr': 0, 'releaseCalls': 1,
            'referencesAcquired': 5, 'referencesReleased': 5, 'afterOpenHr': 0,
            'afterConversionHr': 0, 'afterOpenType': 3, 'afterConversionType': 3,
            'afterOpen': 1, 'afterConversion': 1})
        kw = dict(expected_config=bytes(config), notification_config=binding,
                  expected_notification=bytes(binding), pid=31, tid=41, hwnd=51,
                  deadline=100, frequency=10, command3=command)
        return m, config, r, kw

    def test_layout_complete_sample_and_no_setter_or_retirement_claim(self):
        m, c, r, kw = self.fixture()
        self.assertEqual((C.sizeof(m.Config), C.sizeof(m.Lease), C.sizeof(m.Read),
                          C.sizeof(m.ApiReceipt), C.sizeof(m.Record)), (8, 60, 20, 108, 784))
        out = m.decode(c, r, **kw)
        self.assertEqual(out['status'], 'complete')
        self.assertFalse(out['callerAttributionProved'])
        self.assertFalse(out['acceptanceEligible'])
        self.assertFalse(out['processRetirementVerified'])
        self.assertEqual(out['cleanupStatus'], 'pending')
        self.assertEqual(out['frames'][1], {'moduleId': 0, 'rva': 0})

    def test_changed_target_config_addresses_or_clock_cannot_qualify(self):
        for change in (lambda c,r,k:setattr(c,'version',1), lambda c,r,k:setattr(r,'pid',32),
                       lambda c,r,k:setattr(r,'creationTime',556), lambda c,r,k:setattr(r,'counter',101),
                       lambda c,r,k:setattr(r.frames[1],'rva',99),
                       lambda c,r,k:k['command3'].update(success=False)):
            m,c,r,kw = self.fixture(); change(c,r,kw)
            with self.assertRaises(AssertionError): m.decode(c,r,**kw)

    def test_partial_reentrant_expired_capped_or_bad_variant_is_inconclusive(self):
        for change in (lambda r:setattr(r,'sequence',0), lambda r:setattr(r.lease,'rejected',256),
                       lambda r:setattr(r,'expired',1), lambda r:setattr(r,'foreignRejected',1),
                       lambda r:setattr(r.api,'variantCleanupFailed',1),
                       lambda r:setattr(r.lease,'activeCallbacks',1),
                       lambda r:(setattr(r,'frameCount',64),setattr(r,'frameCapReached',1),setattr(r,'unknownFrames',63))):
            m,c,r,kw = self.fixture(); change(r)
            self.assertEqual(m.decode(c,r,**kw)['status'],'inconclusive')

    def test_more_than_sixteen_frames_complete_but_sixty_four_remains_capped(self):
        m,c,r,kw=self.fixture()
        self.assertEqual(len(r.frames),64)
        for count in (17,63,64):
            r.frameCount=count;r.frameCapReached=int(count==64);r.unknownFrames=count-1
            out=m.decode(c,r,**kw)
            self.assertEqual(out['schemaVersion'],2)
            self.assertEqual(out['frameCapacity'],64)
            self.assertEqual(len(out['frames']),count)
            self.assertEqual(out['status'],'inconclusive' if count==64 else 'complete')
        r.frameCount=65
        with self.assertRaises(AssertionError):m.decode(c,r,**kw)

    def test_no_callback_is_not_reproduction_and_unsubscribe_is_not_engine_exit(self):
        m,c,r,kw = self.fixture();r.sequence=r.lease.claimed=0
        self.assertEqual(m.decode(c,r,**kw)['status'],'not-triggered')
        r.sequence=r.lease.claimed=1
        r.lease.armed=r.lease.subscriptionPossible=0
        for name in ('disabled','disconnectAttempts','unadviseAttempts','disconnected','released'):
            setattr(r.lease,name,1)
        r.api.referencesReleased=5;r.api.sinkReferences=1
        out=m.decode(c,r,**kw)
        self.assertEqual(out['cleanupStatus'],'unsubscribed')
        self.assertFalse(out['processRetirementVerified'])
        r.api.referencesReleased=4
        self.assertNotEqual(m.decode(c,r,**kw)['cleanupStatus'],'unsubscribed')

    def test_impossible_reference_and_lease_phases_cannot_qualify(self):
        for change in (
            lambda r: (setattr(r.api, 'referencesAcquired', 0), setattr(r.api, 'sinkReferences', 0)),
            lambda r: setattr(r.api, 'enumerationCount', 0),
            lambda r: (setattr(r.lease, 'armed', 0), setattr(r.lease, 'subscriptionPossible', 0)),
        ):
            m,c,r,kw = self.fixture(); change(r)
            self.assertNotEqual(m.decode(c,r,**kw)['status'], 'complete')
        m,c,r,kw = self.fixture()
        r.lease.armed = r.lease.subscriptionPossible = 0
        for name in ('disabled','disconnectAttempts','unadviseAttempts','disconnected','released'):
            setattr(r.lease, name, 1)
        r.api.referencesReleased=5; r.api.sinkReferences=1
        r.lease.installAttempts=r.lease.adviseAttempts=r.lease.installed=0
        r.api.adviseHr=-1
        self.assertNotEqual(m.decode(c,r,**kw)['cleanupStatus'], 'unsubscribed')

    def test_writer_case_admits_only_the_compartment_variant(self):
        from unittest.mock import patch
        import test_ime_case_phases as phases
        original = phases.ime.case
        def diagnostic(*args, **kwargs):
            args=list(args);args[3]=dict(args[3],nativeMachine=0xaa64)
            return original(*args, **kwargs, diagnose_ime_mode=True,
                            capture_ime_compartment=True, plugin_origin={'synthetic': True})
        with patch.object(phases.ime, 'case', side_effect=diagnostic):
            calls, record, result, error = phases.IMECasePhaseTests().run_case('writer')
        self.assertIn(('command', 1), calls)
        # A concrete original does not match the retained empty-origin hypothesis.
        self.assertIsNotNone(error)
        self.assertIn('original empty TSF origin', str(error))
        self.assertNotIn(('command', 2), calls)
        self.assertIn(('command', 4), calls)
