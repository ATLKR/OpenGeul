"""Controller admission of actual native mode state and a shared QPC budget."""
import copy
import ctypes
import importlib.util
import math
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'ime_thread_mode.py'
mode = None
if SOURCE.is_file():
    spec=importlib.util.spec_from_file_location('tested_ime_thread_mode',SOURCE)
    mode=importlib.util.module_from_spec(spec);spec.loader.exec_module(mode)


class ThreadModeReceiptTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(mode,'Missing native mode receipt and budget validator')
    def receipt(self, command=3):
        value=mode.NativeModeReceipt()
        for name,_ in value._fields_:
            if name.endswith("Hr"):setattr(value,name,mode.NOT_ATTEMPTED)
        value.variantClearHr=0
        value.status=value.cleanupStatus=0
        value.managerHr=value.compartmentManagerHr=value.enumerationHr=value.enumerationNextHr=0
        value.openGetHr=value.conversionGetHr=value.beforeOpenHr=value.beforeConversionHr=0
        value.enumerationCount=2;value.installedMask=3
        value.beforeOpenType=value.beforeConversionType=3
        value.beforeOpen=1;value.beforeConversion=0x20
        value.releaseCalls=1;value.referencesAcquired=value.referencesReleased=5
        for field in ("managerPresent", "compartmentManagerPresent", "enumeratorPresent", "openPresent", "conversionPresent", "modulePresent", "lookupPresent", "managerCallAttempts", "nextFetched"):setattr(value,field,1)
        if command!=1:
            value.clientQueryHr=value.clientHr=value.openSetHr=value.conversionSetHr=0
            value.afterOpenHr=value.afterConversionHr=0
            value.clientId=17;value.openSetCalls=value.conversionSetCalls=1
            value.clientPresent=value.clientIdCalls=1
            value.requestedOpen=1;value.requestedConversion=0x20 if command==2 else 0x21
            value.afterOpen=value.requestedOpen;value.afterConversion=value.requestedConversion
            value.afterOpenType=value.afterConversionType=3
            value.referencesAcquired=value.referencesReleased=6
        return mode.receipt_dict(value)
    def test_original_capture_is_concrete_read_only_and_released(self):
        receipt=self.receipt(1);self.assertIs(mode.require_mode_receipt(receipt,1),receipt)
        receipt['openSetCalls']=1
        with self.assertRaises(AssertionError):mode.require_mode_receipt(receipt,1)
    def test_ascii_and_native_modes_require_exact_readback_and_one_setting_pair(self):
        for command in (2,3):
            receipt=self.receipt(command);mode.require_mode_receipt(receipt,command)
            for field,value in [('afterConversion',9),('clientId',0),('clientQueryHr',-1),('openSetCalls',2),('conversionSetCalls',0),('afterOpenType',0)]:
                changed=copy.deepcopy(receipt);changed[field]=value
                with self.subTest(command=command,field=field),self.assertRaises(AssertionError):mode.require_mode_receipt(changed,command)
    def test_restoration_requires_exact_captured_original_values(self):
        receipt=self.receipt(4)
        mode.require_mode_receipt(receipt,4,previous=(1,0x21))
        with self.assertRaises(AssertionError):mode.require_mode_receipt(receipt,4,previous=(1,0x20))
        with self.assertRaises(AssertionError):mode.require_mode_receipt(receipt,4)
    def test_missing_original_guids_unknown_types_and_cleanup_failures_are_fatal(self):
        receipt=self.receipt()
        for field,value in [('installedMask',1),('enumerationCount',65),('beforeOpenType',0),('beforeConversionType',8),('referencesReleased',5),('releaseCalls',0),('cleanupStatus',-1),('status',-3),('clientId',True),('clientId',2**40)]:
            changed=copy.deepcopy(receipt);changed[field]=value
            with self.subTest(field=field),self.assertRaises(AssertionError):mode.require_mode_receipt(changed,3)
    def test_native_fixed_width_receipt_has_no_pointer_size_dependency(self):
        self.assertEqual(ctypes.sizeof(mode.NativeModeReceipt),184)
        self.assertEqual(ctypes.sizeof(mode.NativeCommandBudget),16)
        self.assertEqual(ctypes.sizeof(mode.NativeCommandRejection),16)
        self.assertTrue(all(ctypes.sizeof(field)==4 for _,field in mode.NativeModeReceipt._fields_))
    def test_counter_budget_uses_original_remaining_time_after_counter_sample(self):
        now=[1.]
        def counter():now[0]=2.;return 5000
        self.assertEqual(mode.counter_budget(3.,clock=lambda:now[0],counter=counter,frequency=1000),(6000,1000))
    def test_expired_and_nonfinite_budgets_never_produce_a_native_deadline(self):
        for deadline in (True,float('nan'),float('inf'),1.,0.):
            with self.subTest(deadline=deadline),self.assertRaises(AssertionError):mode.counter_budget(deadline,clock=lambda:1.,counter=lambda:5000,frequency=1000)
        for frequency in (True,0,-1):
            with self.subTest(frequency=frequency),self.assertRaises(AssertionError):mode.counter_budget(3.,clock=lambda:1.,counter=lambda:5000,frequency=frequency)


class ObserverModeJoinTests(unittest.TestCase):
    receipt=ThreadModeReceiptTests.receipt
    setUp=ThreadModeReceiptTests.setUp
    # Exercise the actual controller without installing hooks or loading a DLL.
    def observer(self, command=3, *, status=0, wrong=False):
        import sys
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        import time
        sys.path.insert(0,str(SOURCE.parent))
        import korean_ime_smoke as ime
        self.assertTrue(hasattr(ime.NativeState,'threadMode'),'Observer does not retain native mode state')
        state=ime.NativeState();state.ack=command;state.status=status
        state.magic=0x4f47494d;state.version=4;state.pid=88;state.tid=44;state.targetHwnd=33;state.rootHwnd=11
        state.snapshotEvidence=dict(copyReturn=1,ackBefore=command,ackAfter=command,stable=True)
        state.tsfCaptured=1;state.profileChangeAttempted=1
        state.previousTsfOpen=1;state.previousTsfConversion=0x20
        state.immContextPresent=state.immConversionSucceeded=state.immOpen=1
        state.immConversion=0x21
        value=self.receipt(command)
        if wrong:value['afterConversion']=0x20
        state.threadMode=type(state.threadMode)(**value)
        observer=ime.CompositionObserver.__new__(ime.CompositionObserver)
        observer.focus=33;observer.child=22;observer.root=11;observer.pid=88;observer.tid=44
        observer.commands=[];observer.activation_attempted=False;observer.restored=False;observer.command_attempts=set()
        observer.original_tsf=((0,3,1),(0,3,0x20));observer.original_context=(0x4f47494d,4,88,44,33,11)
        observer.expected_profile=dict(providerClsid='{A028AE76-01B1-46C2-99C4-ACD9858AE02F}',profileGuid='{B5FE1F02-D5F2-4445-9C03-C568F23C99A1}')
        state.activeLanguage=0x0412
        for field,value in [('activeClsid',observer.expected_profile['providerClsid']),('activeProfile',observer.expected_profile['profileGuid'])]:
            for index,character in enumerate(value):getattr(state,field)[index]=ord(character)
        observer.mapping=bytearray(ctypes.sizeof(ime.NativeState));observer.state=lambda:state
        def publish(pointer,command,counter,frequency):
            target=pointer._obj;slot=target.commandBudgets[command-1]
            if slot.counter or slot.frequency:return 0
            slot.counter=counter;slot.frequency=frequency;target.command=command;return 1
        observer.dll=NS(PublishCommand=publish)
        observer.require_target=lambda:None
        def send(*args):
            incoming=ime.NativeState.from_buffer_copy(observer.mapping)
            state.commandBudgets=incoming.commandBudgets
            return 1
        observer.api=NS(user=NS(SendMessageTimeoutW=send,GetKeyboardLayout=lambda tid:0x04120412))
        self.addCleanup(patch.stopall)
        patch.object(ime.native_mode,'counter_budget',return_value=(100000,1000)).start()
        patch.object(ime,'wait_for',side_effect=lambda fn,seconds:fn()).start()
        return ime,observer,state,time.monotonic()+2
    def test_controller_retains_actual_mode_state_on_success(self):
        ime,observer,state,deadline=self.observer()
        receipt=observer.command(3,setup_deadline=deadline)
        self.assertEqual(receipt['threadMode'],self.receipt(3))
        self.assertEqual(receipt['observerClsid'],mode.OBSERVER_CLSID)
    def test_controller_rejects_wrong_mode_even_with_successful_native_status_and_profile(self):
        ime,observer,state,deadline=self.observer(wrong=True)
        with self.assertRaises(AssertionError):observer.command(3,setup_deadline=deadline)
        self.assertEqual(observer.commands[0]['threadMode']['afterConversion'],0x20)
    def test_himc_minus_three_remains_primary_and_raw_mode_is_retained(self):
        ime,observer,state,deadline=self.observer(status=-3)
        with self.assertRaisesRegex(AssertionError,"'status': -3"):observer.command(3,setup_deadline=deadline)
        self.assertEqual(observer.commands[0]['status'],-3)
        self.assertIn('threadMode',observer.commands[0])
    def test_restore_authority_uses_original_owner_without_foreground_input_authority(self):
        from types import SimpleNamespace as NS
        ime,observer,state,deadline=self.observer()
        observer.require_target=lambda:(_ for _ in ()).throw(AssertionError('foreign foreground'))
        observer.api=NS(pid=lambda hwnd:88,user=NS(IsWindow=lambda hwnd:True,
            GetWindowThreadProcessId=lambda hwnd,arg:44,GetAncestor=lambda hwnd,kind:11,
            IsChild=lambda child,hwnd:True))
        observer.require_restore_target()
        observer.api.pid=lambda hwnd:99
        with self.assertRaises(AssertionError):observer.require_restore_target()

    def test_mode_ack_cannot_switch_to_a_different_korean_profile(self):
        ime,observer,state,deadline=self.observer()
        state.activeProfile[1]=ord('0')
        with self.assertRaises(AssertionError):observer.command(3,setup_deadline=deadline)
    def test_late_ack_readback_cannot_outlive_original_command_subdeadline(self):
        from unittest.mock import patch
        ime,observer,state,deadline=self.observer();now=[0.]
        def late(fn,seconds):
            value=fn();now[0]=6.;return value
        with patch.object(ime.time,'monotonic',side_effect=lambda:now[0]),patch.object(ime,'wait_for',side_effect=late):
            with self.assertRaises(AssertionError):observer.command(3,setup_deadline=60.)

    def test_original_command_cannot_retry_or_republish_a_fresh_budget(self):
        ime,observer,state,deadline=self.observer()
        observer.command(3,setup_deadline=deadline)
        with self.assertRaises(AssertionError):observer.command(3,setup_deadline=deadline+20)
        self.assertEqual(len(observer.commands),1)
    def test_failed_native_send_retains_rejection_evidence_without_ack(self):
        ime,observer,state,deadline=self.observer()
        from unittest.mock import patch
        if hasattr(state,'commandRejection'):
            state.commandRejection.count=1;state.commandRejection.sequence=4
            state.commandRejection.during=3;state.commandRejection.reason=1
        observer.api.user.SendMessageTimeoutW=lambda *args:(_ for _ in ()).throw(RuntimeError('native timeout'))
        with self.assertRaisesRegex(RuntimeError,'native timeout'):observer.command(3,setup_deadline=deadline)
        self.assertEqual(len(observer.commands),1)
        self.assertFalse(observer.commands[0]['acknowledged'])
        self.assertEqual(observer.commands[0]['nativeStateAtFailure']['commandRejection']['count'],1)
    def test_fixed_command_slots_do_not_publish_cleanup_budget_over_original_command(self):
        ime,observer,state,deadline=self.observer()
        self.assertTrue(hasattr(ime.NativeState,'commandBudgets'),'Missing immutable per-command native budgets')
        observer.command(3,setup_deadline=deadline)
        published=ime.NativeState.from_buffer_copy(observer.mapping)
        self.assertEqual(published.commandBudgets[2].counter,100000)
        self.assertEqual(published.commandBudgets[3].counter,0)
    def test_restoration_is_not_retried_after_its_one_original_attempt(self):
        ime,observer,state,deadline=self.observer()
        observer.activation_attempted=True
        observer.command_attempts={4}
        self.assertFalse(observer.restoration_required)

    def test_rejected_native_publication_cannot_send_or_invent_a_command_ack(self):
        from types import SimpleNamespace as NS
        ime,observer,state,deadline=self.observer();sent=[]
        observer.dll=NS(PublishCommand=lambda *args:0)
        observer.api.user.SendMessageTimeoutW=lambda *args:sent.append(args) or 1
        with self.assertRaises(AssertionError):observer.command(3,setup_deadline=deadline)
        self.assertEqual(sent,[])
        self.assertFalse(observer.commands[0]['acknowledged'])

    def test_conflicting_native_command_cannot_authorize_following_physical_input(self):
        ime,observer,state,deadline=self.observer()
        state.commandRejection.count=1;state.commandRejection.sequence=4
        state.commandRejection.during=3;state.commandRejection.reason=1
        with self.assertRaises(AssertionError):observer.command(3,setup_deadline=deadline)
        self.assertFalse(observer.commands[0]['success'])

    def test_controller_acquires_native_ack_before_copying_command_state(self):
        from types import SimpleNamespace as NS
        ime,observer,state,deadline=self.observer();calls=[]
        def read(source,destination,before,after):
            calls.append('native acquire before copy')
            ctypes.memmove(destination,source,ctypes.sizeof(ime.NativeState))
            destination._obj.ack=3;destination._obj.status=123
            before._obj.value=after._obj.value=3
            return 1
        observer.dll=NS(ReadSnapshot=read)
        snapshot=ime.CompositionObserver.state(observer)
        self.assertEqual(calls,['native acquire before copy'])
        self.assertEqual(snapshot.status,123)
        self.assertTrue(snapshot.snapshotEvidence['stable'])
    def test_unstable_ack_snapshot_never_qualifies_a_successful_native_command(self):
        from unittest.mock import patch
        ime,observer,state,deadline=self.observer()
        state.snapshotEvidence=dict(copyReturn=2,ackBefore=2,ackAfter=3,stable=False)
        def wait(predicate,seconds):
            result=predicate()
            if not result:raise AssertionError('ACK snapshot not qualified')
            return result
        with patch.object(ime,'wait_for',side_effect=wait):
            with self.assertRaises(AssertionError):observer.command(3,setup_deadline=deadline)
        self.assertFalse(observer.commands[0]['success'])
