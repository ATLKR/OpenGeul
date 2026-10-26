"""A callback receipt needs original-run, retired-engine and file-only joins."""
import unittest
import test_notification_selection as notification_fixture
import test_ime_compartment_protocol as compartment_fixture

class CompartmentSelectionTests(unittest.TestCase):
    def setUp(self):
        self.base=notification_fixture.NotificationSelectionTests();self.base.setUp();self.m=self.base.m
    def compartment_report(self):
        report=self.base.report();report['notificationCallerEnabled']=False
        report['compartmentCallbackEnabled']=True
        case=report['tests'][0];case['case']='ime-writer'
        m,c,row,kw=compartment_fixture.CompartmentProtocolTests().fixture()
        row.lease.armed=row.lease.subscriptionPossible=0
        for key in ('disabled','disconnectAttempts','unadviseAttempts','disconnected','released'):
            setattr(row.lease,key,1)
        row.api.referencesReleased=5;row.api.sinkReferences=1
        case['imeCompartmentDiagnostics']=m.decode(c,row,**kw)
        case['imeCommands']=[dict(command=3,**kw['command3'])]
        case['activeProfile']={'tsfOrigin':'empty'}
        case.update(keyTokens=['g'],scanCodeInputs=[{'vk':0,'scan':34,'flags':8},{'vk':0,'scan':34,'flags':10}],
                    inputMethod='SendInput-scancode',unicodeInputUsed=False,
                    error='AssertionError: Native UI condition did not become true: False')
        case['imeKeyboardSession']['expectedNative']['suiteHwnd']=11
        case['imeCommands'][0].update(policyVersion=4,
            nativeContext={'magic':0x4f47494d,'version':4,'pid':31,'tid':41,'targetHwnd':51,'rootHwnd':11},
            requestedBudget={'counter':15,'frequency':10},modeDeadlineCounter=15,modeCounterFrequency=10)
        case['imeMessageDiagnostics']={'status':'complete','capacity':128,'observedCount':1,'events':[
            {'sequence':1,'message':0x100,'origin':2,'commandAck':3,'pid':31,'tid':41,'hwnd':51,
             'focusHwnd':51,'wparam':71,'lparam':34<<16,'counter':18,'immContextPresent':1,
             'immConversionSucceeded':1,'immOpen':1,'immConversion':1}]}
        return report
    def test_callback_selection_has_no_setter_or_acceptance_claim(self):
        self.assertTrue(hasattr(self.m,'select_compartment'))
        selected=self.m.select_compartment(self.compartment_report())
        self.assertEqual(selected['rvas'],[100])
        self.assertEqual(selected['status'],'selected')
        self.assertFalse(selected['runtimeCallerProved'])
        self.assertFalse(selected['acceptanceEligible'])
    def test_partial_cleanup_and_other_failure_never_select(self):
        self.assertTrue(hasattr(self.m,'select_compartment'))
        for change in (
            lambda c:c['imeCompartmentDiagnostics'].update(status='inconclusive'),
            lambda c:c['imeCompartmentDiagnostics'].update(cleanupStatus='pending'),
            lambda c:c.update(stage='save-ctrl-s'),
            lambda c:c.update(keyTokens=[]),
            lambda c:c.update(keyTokens=['g','k']),
            lambda c:c['imeMessageDiagnostics'].update(status='partial'),
        ):
            report=self.compartment_report();change(report['tests'][0])
            self.assertNotEqual(self.m.select_compartment(report)['status'],'selected')
    def test_foreign_engine_or_unproved_exit_is_rejected(self):
        self.assertTrue(hasattr(self.m,'select_compartment'))
        for change in (
            lambda c:c['imeCompartmentDiagnostics'].update(engineCreationTime=556),
            lambda c:c['imeFailureCleanup'].update(engineExitConfirmed=False),
            lambda c:c['imeCompartmentDiagnostics']['frames'][1].update(rva=88),
            lambda c:c['imeCommands'][0]['nativeContext'].update(pid=999),
            lambda c:c['imeCommands'][0].update(modeCounterFrequency=99),
        ):
            report=self.compartment_report();change(report['tests'][0])
            with self.assertRaises(AssertionError):self.m.select_compartment(report)
