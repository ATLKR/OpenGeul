"""Shared setup budget caps existing discovery/compile/command limits."""
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import korean_ime_smoke as ime
import test_ime_mode_receipts as mode_fixtures


class SetupDeadlineTests(unittest.TestCase):
    def observer(self, now, *, status=0):
        value=ime.NativeState();value.ack=1;value.status=status
        value.magic=0x4f47494d;value.version=4;value.pid=88;value.tid=44;value.targetHwnd=33;value.rootHwnd=11
        value.snapshotEvidence=dict(copyReturn=1,ackBefore=1,ackAfter=1,stable=True)
        value.tsfCaptured=1;value.profileChangeAttempted=1
        value.threadMode=ime.native_mode.NativeModeReceipt(**mode_fixtures.ThreadModeReceiptTests().receipt(1))
        counter=patch.object(ime.native_mode,"counter_budget",return_value=(100000,1000))
        counter.start();self.addCleanup(counter.stop)
        def send(*args):
            now[0]+=1.
            value.commandBudgets=ime.NativeState.from_buffer_copy(observer.mapping).commandBudgets
            return 1
        observer=ime.CompositionObserver.__new__(ime.CompositionObserver)
        observer.api=NS(user=NS(SendMessageTimeoutW=send,GetKeyboardLayout=lambda tid:0x04120412))
        observer.focus=33;observer.tid=44;observer.commands=[];observer.activation_attempted=False;observer.command_attempts=set()
        observer.root=11;observer.child=22;observer.pid=88;observer.original_tsf=observer.original_context=None
        observer.mapping=bytearray(__import__('ctypes').sizeof(ime.NativeState))
        def publish(pointer,command,counter,frequency):
            target=pointer._obj;slot=target.commandBudgets[command-1]
            if slot.counter or slot.frequency:return 0
            slot.counter=counter;slot.frequency=frequency;target.command=command;return 1
        observer.dll=NS(PublishCommand=publish)
        observer.require_target=lambda:None;observer.state=lambda:value
        return observer
    def test_setup_command_send_and_ack_share_remaining_five_second_subdeadline(self):
        now=[1.];observer=self.observer(now)
        def wait(predicate,seconds):
            self.assertEqual(seconds,1.);return predicate()
        with patch.object(ime.time,'monotonic',side_effect=lambda:now[0]),patch.object(ime,'wait_for',side_effect=wait):
            observer.command(1,setup_deadline=3.)
        self.assertTrue(observer.activation_attempted)
    def test_setup_command_keeps_native_minus_three_failure_and_does_not_retry(self):
        now=[1.];observer=self.observer(now,status=-3)
        with patch.object(ime.time,'monotonic',side_effect=lambda:now[0]),patch.object(ime,'wait_for',side_effect=lambda fn,seconds:fn()):
            with self.assertRaisesRegex(AssertionError,"'status': -3"):
                observer.command(1,setup_deadline=3.)
        self.assertEqual(len(observer.commands),1)
        self.assertEqual(observer.commands[0]['status'],-3)
    def test_budget_never_renews_or_accepts_nonfinite_and_boolean_deadlines(self):
        function=getattr(ime,'remaining_setup',None)
        self.assertTrue(callable(function),'Missing shared IME setup budget')
        self.assertEqual(function(10.,60,clock=lambda:8.),2.)
        for deadline in (8.,7.,True,float('nan'),float('inf')):
            with self.subTest(deadline=deadline),self.assertRaises(AssertionError):function(deadline,60,clock=lambda:8.)
    def test_discovery_uses_and_retains_the_remaining_budget_once(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            result=subprocess.CompletedProcess(['vswhere'],0,'C:/VS\n','')
            with patch.object(ime.subprocess,'run',return_value=result) as run:
                found=ime.discover_msvc(folder,folder/'vswhere.exe',setup_deadline=10.,clock=lambda:8.)
            self.assertEqual(found,'C:/VS');self.assertEqual(run.call_args.kwargs['timeout'],2.)
            import json
            receipt=json.loads((folder/'compiler-discovery.json').read_text())
            self.assertEqual(receipt['timeoutSeconds'],2.)
            self.assertEqual(receipt['setupDeadline'],10.)
    def test_compile_consumes_same_budget_after_discovery_instead_of_new_sixty_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);vs=folder/'VS';vcvars=vs/'VC/Auxiliary/Build/vcvars64.bat'
            vcvars.parent.mkdir(parents=True);vcvars.write_text('existing build setup')
            now=[1.]
            def discover(*args,**kw):
                self.assertEqual(kw['setup_deadline'],10.);now[0]=9.;return str(vs)
            def compile(*args,**kw):
                self.assertEqual(kw['timeout'],1.);(folder/'ime-observer.dll').write_bytes(b'fake native boundary')
                return subprocess.CompletedProcess(args[0],0,b'',b'')
            with patch.object(ime.shutil,'which',return_value=None),patch.object(ime,'discover_msvc',side_effect=discover),patch.object(ime.subprocess,'run',side_effect=compile),patch.object(ime.native_arch,'require_native_pe',side_effect=lambda path,arch:path):
                ime.compile_observer(folder,'Local\\test',{'providerClsid':'cl','profileGuid':'pf'},setup_deadline=10.,clock=lambda:now[0])
    def test_expired_setup_cannot_start_a_compiler_or_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ime.subprocess,'run') as run,self.assertRaises(AssertionError):
                ime.compile_observer(Path(directory),'Local\\test',{'providerClsid':'cl','profileGuid':'pf'},setup_deadline=10.,clock=lambda:10.)
            run.assert_not_called()
