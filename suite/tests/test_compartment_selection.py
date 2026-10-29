"""A callback receipt needs original-run, retired-engine and file-only joins."""
import unittest
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
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
        case['imeCommands'].append(dict(command=1,nativeAck=1,status=0,success=True,
            nativeContext=dict(case['imeCommands'][0]['nativeContext']),threadMode=dict(
                status=0,cleanupStatus=0,variantClearHr=0,releaseCalls=1,
                referencesAcquired=5,referencesReleased=5,beforeOpenHr=1,
                beforeConversionHr=1,beforeOpenType=0,beforeConversionType=0,
                openSetCalls=0,conversionSetCalls=0)))
        case['imeMessageDiagnostics']={'status':'complete','capacity':128,'observedCount':1,'events':[
            {'sequence':1,'message':0x100,'origin':2,'commandAck':3,'pid':31,'tid':41,'hwnd':51,
             'focusHwnd':51,'wparam':71,'lparam':34<<16,'counter':18,'immContextPresent':1,
             'immConversionSucceeded':1,'immOpen':1,'immConversion':1}]}
        return report

    def test_sixty_three_frames_select_but_capped_first_callback_never_resolves(self):
        report=self.compartment_report();callback=report['tests'][0]['imeCompartmentDiagnostics']
        callback.update(frameCount=63,frameCapReached=False,unknownFrames=62,
            frames=[dict(moduleId=14,rva=100)]+[dict(moduleId=0,rva=0)]*62)
        self.assertEqual(self.m.select_compartment(report)['rvas'],[100])
        callback.update(status='inconclusive',frameCount=64,frameCapReached=True,
            unknownFrames=63,frames=callback['frames']+[dict(moduleId=0,rva=0)])
        calls=[]
        def forbidden(*a,**k):calls.append(1);raise AssertionError('Capped callback cannot resolve or retry')
        selection,resolution=self.m.resolve_compartment_in_memory(report,None,report['runBinding'],worker_run=forbidden)
        self.assertEqual(selection['status'],'inconclusive-callback')
        self.assertTrue(selection['inputSignatureVerified'])
        self.assertIsNone(resolution);self.assertEqual(calls,[])

    def test_larger_capture_keeps_first_key_and_original_origin_guards(self):
        for change in (
            lambda c:c['activeProfile'].update(tsfOrigin='i4'),
            lambda c:c['imeMessageDiagnostics']['events'][0].update(immOpen=0),
            lambda c:c['imeMessageDiagnostics']['events'][0].update(counter=21),
        ):
            report=self.compartment_report();change(report['tests'][0])
            with self.assertRaises(AssertionError):self.m.select_compartment(report)

    def test_cli_routes_thirty_three_compartment_frames_to_the_fixed_compartment_worker(self):
        import ascii_message_preparation as shared
        report=self.compartment_report();rvas=[100+4*i for i in range(33)]
        report['tests'][0]['imeCompartmentDiagnostics'].update(frameCount=33,unknownFrames=0,
            frames=[dict(moduleId=14,rva=r) for r in rvas])
        calls=[]
        def legacy(*a,**k):calls.append('legacy');raise AssertionError('Compartment cannot use legacy32')
        def compartment(pair,*,mode,rvas):
            calls.append(('compartment',mode,rvas))
            identity=report['pluginFileOrigin']
            return dict(success=True,resolution=dict(dllSha256=identity['dllSha256'],
                identity=identity['matchedIdentity'],frames=[dict(returnRva=r,tag='frame-input-context') for r in rvas]))
        worker=SimpleNamespace(shared=shared,run=legacy,run_compartment=compartment)
        admission=SimpleNamespace(validate_context=lambda *a:report['runBinding'],read_event=lambda:{})
        spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input.json';output=root/'output.json'
            source.write_text(json.dumps(report))
            with patch.object(self.m,'os',SimpleNamespace(name='nt',environ={})), \
                    patch.object(self.m.importlib.util,'spec_from_file_location',return_value=spec), \
                    patch.object(self.m.importlib.util,'module_from_spec',return_value=admission), \
                    patch.dict(sys.modules,{'plugin_symbol_worker':worker}):
                code=self.m.main(['--mode','resolve','--pair',str(root/'pair'),
                    '--compartment',str(source),'--output',str(output)])
            self.assertEqual(code,0,'Valid 33-frame compartment CLI must use its fixed64 API')
            self.assertEqual(calls,[('compartment','resolve',rvas)])
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
