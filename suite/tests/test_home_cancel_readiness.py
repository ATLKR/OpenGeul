"""Canceled-picker owner readiness is read-only and spends the original20s."""
import copy
import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))

class HomeCancelTests(unittest.TestCase):
    def setUp(self):
        self.clock=NS(now=1.);self.process=NS(pid=77,_handle=1234)
        self.read_clock=lambda:self.clock.now
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);native_root=Path(temporary.name).resolve()
        self.identity=dict(pid=77,handleValue=1234,creationTime=134370356496333887,image=str((native_root/'OpenGeul.Office.exe').resolve()),waitResult=258)
        self.doc=dict(hwnd=11,pid=77,threadId=9,rootHwnd=11,visible=True,enabled=False,iconic=False,cloaked=0,rectangle=[0,0,1024,720],className='Home')
        self.value=dict(processBefore=copy.deepcopy(self.identity),processAfter=copy.deepcopy(self.identity),document=copy.deepcopy(self.doc),dialogAlive=False,dialog=None,foreground=dict(hwnd=11,pid=77,threadId=9,rootHwnd=11))
        self.states=[];self.observed=[]
        def observe(*args):
            value=copy.deepcopy(self.states.pop(0)if self.states else self.value);self.observed.append(value);return value
        self.probe=NS(snapshot=observe)
        self.record=dict(originalShell=dict(pid=77,handleValue=1234,nativeImage=self.identity['image'],nativeCreation=dict(fileTime=self.identity['creationTime'])),openDialogs=[])
        self.operation=dict(openDialogReadiness=dict(schemaVersion=1,kind='owned-open-dialog-readiness',ready=True,shellPid=77,documentHwnd=11,dialogHwnd=44,caption='OpenGeul Office에서 문서 열기',nativeAnchor=dict(document=dict(hwnd=11,pid=77,threadId=9,rootHwnd=11,className='Home'),dialog=dict(hwnd=44,pid=77,threadId=9,rootHwnd=44,className='#32770'))))
    def run_wait(self):
        try:module=importlib.import_module('home_cancel_readiness')
        except ModuleNotFoundError:self.fail('Canceled native dialog currently has no owner-reenable readiness contract')
        return module.wait_cancelled_home(None,self.process,11,44,self.record,self.operation,probe=self.probe,clock=self.read_clock,pause=lambda s:setattr(self.clock,'now',self.clock.now+s))
    def test_dialog_destroyed_but_owner_disabled_is_observed_until_original_owner_ready(self):
        disabled=copy.deepcopy(self.value);ready=copy.deepcopy(self.value);ready['document']['enabled']=True;self.states=[disabled,ready]
        receipt=self.run_wait();self.assertTrue(receipt['ready']);self.assertEqual(receipt['pollCount'],2)
        self.assertFalse(receipt['firstObservation']['document']['enabled']);self.assertTrue(receipt['lastObservation']['document']['enabled'])
        self.assertEqual(receipt['deadline'],21.);self.assertLessEqual(receipt['finishedAt'],21.)
    def test_permanently_disabled_owner_expires_without_renewing_original_twenty_seconds(self):
        with self.assertRaisesRegex(AssertionError,'deadline|bound'):self.run_wait()
        receipt=self.operation['cancelOwnerReadiness'];self.assertFalse(receipt['ready']);self.assertEqual(receipt['deadline'],21.)
        self.assertLessEqual(receipt['pollCount'],401);self.assertLessEqual(self.clock.now,21.)
    def test_foreign_focus_replacement_and_changed_generation_are_fatal_not_pending(self):
        for field in ('foreign','thread','generation','hidden','root'):
            with self.subTest(field=field):
                v=copy.deepcopy(self.value);v['document']['enabled']=True
                if field=='foreign':v['foreground']['pid']=88
                elif field=='thread':v['document']['threadId']=10
                elif field=='generation':v['processAfter']['creationTime']+=1
                elif field=='hidden':v['document']['visible']=False
                else:v['document']['rootHwnd']=99
                self.states=[v];before=len(self.observed)
                with self.assertRaises(AssertionError):self.run_wait()
                self.assertEqual(len(self.observed)-before,1);self.assertFalse(self.operation['cancelOwnerReadiness']['ready'])
    def test_rejected_raw_owner_snapshot_is_retained(self):
        self.value['document']['threadId']=10
        with self.assertRaises(AssertionError):self.run_wait()
        self.assertEqual(self.operation['cancelOwnerReadiness']['lastObservation']['document']['threadId'],10)
    def test_late_ready_observation_does_not_pass_original_budget(self):
        self.value['document']['enabled']=True
        def late(*a):self.clock.now=21.;return copy.deepcopy(self.value)
        self.probe.snapshot=late
        with self.assertRaises(AssertionError):self.run_wait()
        self.assertFalse(self.operation['cancelOwnerReadiness']['ready'])
    def test_replay_rejects_boolean_phase_time_even_when_numeric_equality_matches(self):
        self.value['document']['enabled']=True;receipt=self.run_wait();receipt['startedAt']=True
        module=importlib.import_module('home_cancel_readiness')
        with self.assertRaises(AssertionError):module.require_cancelled_home_readiness(receipt,77,11,self.record['originalShell'],open_readiness=self.operation['openDialogReadiness'])
    def test_receipt_must_join_original_open_dialog_and_owner_anchor(self):
        self.value['document']['enabled']=True;receipt=self.run_wait();module=importlib.import_module('home_cancel_readiness')
        for label in ('dialog','thread','caption'):
            with self.subTest(label=label):
                proof=copy.deepcopy(self.operation['openDialogReadiness'])
                if label=='dialog':proof['dialogHwnd']=99
                elif label=='thread':proof['nativeAnchor']['document']['threadId']=10
                else:proof['caption']='another picker'
                error=None
                try:module.require_cancelled_home_readiness(receipt,77,11,self.record['originalShell'],open_readiness=proof)
                except BaseException as exc:error=exc
                self.assertIsInstance(error,AssertionError,'Original Open binding must be an actual replay input, not only fields copied into the cancel receipt')
    def test_final_timestamp_nan_regression_or_boolean_never_returns_ready(self):
        module=importlib.import_module('home_cancel_readiness');actual=module.require_cancelled_home_readiness
        for invalid in (float('nan'),0.,True):
            with self.subTest(invalid=invalid):
                self.value['document']['enabled']=True;state={'validated':False,'after':0}
                def validate(*args,**kwargs):
                    result=actual(*args,**kwargs);state['validated']=True;return result
                def clock():
                    if state['validated']:
                        state['after']+=1
                        if state['after']==2:return invalid
                    return 1.
                self.read_clock=clock
                with patch.object(module,'require_cancelled_home_readiness',side_effect=validate):
                    with self.assertRaises(AssertionError):self.run_wait()
                self.assertFalse(self.operation['cancelOwnerReadiness']['ready'])
    def test_original_native_error_survives_invalid_final_clock_with_secondary_receipt(self):
        state={'failed':False}
        def failure(*args):state['failed']=True;raise OSError('original native query failed')
        self.probe.snapshot=failure;self.read_clock=lambda:float('nan')if state['failed']else 1.
        with self.assertRaisesRegex(OSError,'original native query'):self.run_wait()
        self.assertIn('finalClockError',self.operation['cancelOwnerReadiness']);self.assertFalse(self.operation['cancelOwnerReadiness']['ready'])
    def windows_replay(self):
        self.value['document']['enabled']=True;receipt=copy.deepcopy(self.run_wait());shell=copy.deepcopy(self.record['originalShell'])
        image=r'D:\a\OpenGeul\suite\OpenGeul.Office.exe';shell['nativeImage']=image;receipt['originalProcess']['image']=image
        for phase in ('firstObservation','lastObservation'):
            for key in ('processBefore','processAfter'):receipt[phase][key]['image']=image
        return receipt,shell
    def test_pure_cancel_replay_preserves_raw_windows_image_on_linux(self):
        receipt,shell=self.windows_replay();module=importlib.import_module('home_cancel_readiness');error=None;result=None
        try:result=module.require_cancelled_home_readiness(receipt,77,11,shell,open_readiness=self.operation['openDialogReadiness'])
        except BaseException as exc:error=exc
        self.assertIsNone(error,'Raw already-verified Windows image must not be resolved on the replay host filesystem')
        self.assertIs(result,receipt)
    def test_pure_cancel_replay_rejects_changed_original_native_windows_image(self):
        receipt,shell=self.windows_replay();shell['nativeImage']=r'D:\a\OpenGeul\other\OpenGeul.Office.exe'
        module=importlib.import_module('home_cancel_readiness')
        with self.assertRaises(AssertionError):module.require_cancelled_home_readiness(receipt,77,11,shell,open_readiness=self.operation['openDialogReadiness'])
    def test_fixture_native_image_is_canonical_with_real_parent_alias(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory).resolve();parent=root/'bridge';parent.mkdir();alias=parent/'..'
            nested=HomeCancelTests('test_dialog_destroyed_but_owner_disabled_is_observed_until_original_owner_ready')
            try:
                with patch.object(tempfile,'TemporaryDirectory',return_value=NS(name=str(alias),cleanup=lambda:None)):nested.setUp()
                self.assertEqual(nested.identity['image'],str((alias/'OpenGeul.Office.exe').resolve()))
                nested.value['document']['enabled']=True;self.assertTrue(nested.run_wait()['ready'])
            finally:nested.doCleanups()

if __name__=='__main__':unittest.main()
