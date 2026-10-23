"""Owned fixture service lifetime, with real callback shape and no Windows claim."""
import gc
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import test_engine_smoke as fixtures
smoke=fixtures.smoke
observations=fixtures.observations


class UnoBase:pass
class XTerminateListener:pass
class TerminationVetoException(Exception):pass


def uno_modules():
    helper=types.ModuleType('unohelper');helper.Base=UnoBase
    frame=types.ModuleType('com.sun.star.frame')
    frame.XTerminateListener=XTerminateListener
    frame.TerminationVetoException=TerminationVetoException
    return {'unohelper':helper,'com.sun.star.frame':frame}


class Desktop:
    def __init__(self,events):
        self.events=events;self.listeners=[];self.add_error=self.remove_error=None
        self.on_add=self.on_remove=None
    def addTerminateListener(self,listener):
        self.events.append('add');self.listeners.append(listener)
        if self.on_add:self.on_add(listener)
        if self.add_error:raise self.add_error
    def removeTerminateListener(self,listener):
        self.events.append('remove')
        if self.on_remove:self.on_remove(listener)
        if self.remove_error:raise self.remove_error
        assert len(self.listeners)==1 and self.listeners[0] is listener
        self.listeners.remove(listener)
    def terminate(self):
        self.events.append('terminate')
        assert not self.listeners, 'Explicit termination must follow listener removal'
        return True


class FixtureDesktopLeaseTests(unittest.TestCase):
    def setUp(self):
        self.modules=patch.dict(sys.modules,uno_modules());self.modules.start();self.addCleanup(self.modules.stop)
    def engine(self):
        e=smoke.Engine(Path('/generated-suite'));e.desktop=Desktop([]);return e
    def acquire(self,e):
        self.assertTrue(callable(getattr(e,'acquire_fixture_lifetime',None)), 'Explicit fixture lifetime API missing')
        e.acquire_fixture_lifetime();return e.fixture_lifetime
    def test_listener_is_typed_strong_owned_and_not_a_reserved_internal_service(self):
        e=self.engine();lease=self.acquire(e);listener=lease.listener;gc.collect()
        self.assertIs(e.desktop.listeners[0],listener)
        self.assertIsInstance(listener,UnoBase);self.assertIsInstance(listener,XTerminateListener)
        self.assertFalse(hasattr(listener,'getImplementationName'))
        self.assertIs(e.cleanup_evidence['fixtureDesktopLifetime'],lease.receipt)
        self.assertEqual(e.desktop.events,['add'])
    def test_active_query_veto_is_exact_and_callback_uses_only_bounded_local_state(self):
        e=self.engine();lease=self.acquire(e);listener=lease.listener
        with patch.object(e.lifetime_diagnostics,'clock',side_effect=AssertionError('callback clock forbidden')), \
                patch('builtins.open',side_effect=AssertionError('callback I/O forbidden')):
            with self.assertRaises(TerminationVetoException):listener.queryTermination(object())
        self.assertEqual(e.desktop.events,['add']);lease.require_active()
        self.assertEqual(lease.receipt['events'],[dict(event='queryTermination',active=True)])
    def test_unexpected_notify_or_dispose_is_fatal_at_barrier_and_release_still_removes(self):
        for callback in ('notifyTermination','disposing'):
            with self.subTest(callback=callback):
                e=self.engine();lease=self.acquire(e);getattr(lease.listener,callback)(object())
                with self.assertRaises(AssertionError):lease.require_active()
                e.cleanup()
                self.assertEqual(e.desktop.events,['add','remove','terminate'])
                self.assertTrue(e.cleanup_errors)
                self.assertFalse(e.cleanup_evidence['gracefulQualified'])
    def test_callback_overflow_stays_bounded_and_fails_qualification_without_losing_veto(self):
        e=self.engine();lease=self.acquire(e)
        for _ in range(70):
            with self.assertRaises(TerminationVetoException):lease.listener.queryTermination(None)
        self.assertEqual(len(lease.receipt['events']),64)
        self.assertGreater(lease.receipt['omittedEvents'],0)
        with self.assertRaises(AssertionError):lease.require_active()
        e.cleanup();self.assertTrue(e.cleanup_errors)
    def test_callback_metadata_failure_cannot_lose_exact_active_veto_or_sticky_fault(self):
        class BrokenEvents(list):
            def append(self,value):raise MemoryError('recording failed')
        class BrokenReceipt(dict):
            def __getitem__(self,key):
                if key=='events':raise MemoryError('receipt lookup failed')
                return super().__getitem__(key)
        for fault in ('append','receipt'):
            with self.subTest(fault=fault):
                e=self.engine();lease=self.acquire(e);clean=dict(lease.receipt)
                if fault=='append':lease.receipt['events']=BrokenEvents()
                else:lease.receipt=BrokenReceipt(lease.receipt)
                try:lease.listener.queryTermination(None)
                except TerminationVetoException:pass
                except BaseException as exc:self.fail('Metadata fault replaced exact veto: '+type(exc).__name__)
                else:self.fail('Active callback lost its termination veto')
                self.assertTrue(getattr(lease,'callback_fault',False))
                lease.receipt=clean
                with self.assertRaises(TerminationVetoException):lease.listener.queryTermination(None)
                self.assertTrue(lease.callback_fault)
                with self.assertRaises(AssertionError):lease.require_active()
                e.cleanup();self.assertTrue(e.cleanup_errors)
                self.assertEqual(e.desktop.events,['add','remove','terminate'])
    def test_notification_fatal_latch_precedes_fallible_metadata_and_never_clears(self):
        class BrokenEvents(list):
            def append(self,value):raise MemoryError('recording failed')
        for event in ('notifyTermination','disposing'):
            with self.subTest(event=event):
                e=self.engine();lease=self.acquire(e);lease.receipt['events']=BrokenEvents()
                try:getattr(lease.listener,event)(None)
                except BaseException as exc:self.fail('Metadata fault escaped callback: '+type(exc).__name__)
                self.assertTrue(getattr(lease,'unexpected_termination',False))
                self.assertTrue(getattr(lease,'callback_fault',False))
                lease.receipt['events']=[]
                lease.receipt['unexpectedTermination']=False
                with self.assertRaises(TerminationVetoException):lease.listener.queryTermination(None)
                with self.assertRaises(AssertionError):lease.require_active()
                e.cleanup();self.assertTrue(e.cleanup_errors)
    def test_partial_registration_retains_exact_listener_and_attempts_removal_once(self):
        e=self.engine();primary=RuntimeError('add reply lost');e.desktop.add_error=primary
        self.assertTrue(callable(getattr(e,'acquire_fixture_lifetime',None)))
        with self.assertRaises(RuntimeError) as got:e.acquire_fixture_lifetime()
        self.assertIs(got.exception,primary);listener=e.fixture_lifetime.listener
        self.assertIs(e.desktop.listeners[0],listener)
        e.cleanup()
        self.assertEqual(e.desktop.events,['add','remove','terminate'])
        self.assertEqual(e.fixture_lifetime.receipt['registration'],'raised')
        self.assertTrue(e.cleanup_errors)
    def test_removal_failure_disarms_but_keeps_reference_and_remains_fatal(self):
        e=self.engine();lease=self.acquire(e);listener=lease.listener
        primary=RuntimeError('remove failed');e.desktop.remove_error=primary
        with self.assertRaises(RuntimeError) as got:lease.release()
        self.assertIs(got.exception,primary);self.assertIs(lease.listener,listener)
        self.assertIsNone(listener.queryTermination(None))
        with self.assertRaises(AssertionError):lease.release()
        self.assertEqual(e.desktop.events,['add','remove'])
    def test_removal_is_disarmed_and_recorded_before_call_without_duplicate_assumption(self):
        e=self.engine();lease=self.acquire(e)
        def during_remove(listener):
            self.assertEqual(lease.receipt['removal'],'attempted')
            self.assertFalse(lease.active);self.assertIsNone(listener.queryTermination(None))
        e.desktop.on_remove=during_remove;lease.release()
        self.assertIsNone(lease.listener)
        self.assertEqual(lease.receipt['removal'],'returned')
        with self.assertRaises(AssertionError):lease.release()
        self.assertEqual(e.desktop.events,['add','remove'])
    def test_registration_attempt_and_reference_exist_before_registration_callback(self):
        e=self.engine()
        def during_add(listener):
            self.assertIs(e.fixture_lifetime.listener,listener)
            self.assertEqual(e.fixture_lifetime.receipt['registration'],'attempted')
            with self.assertRaises(TerminationVetoException):listener.queryTermination(None)
        e.desktop.on_add=during_add;self.acquire(e)
    def test_opted_generated_close_preserves_original_calls_and_primary_failure(self):
        e=self.engine();lease=self.acquire(e);calls=[];primary=RuntimeError('setModified failed')
        class Doc:
            def setModified(self,value):calls.append(('modified',value));raise primary
            def close(self,value):calls.append(('close',value))
        with self.assertRaises(RuntimeError) as got:e.close_document(Doc())
        self.assertIs(got.exception,primary);self.assertEqual(calls,[('modified',False)])
        self.assertEqual(e.lifetime_diagnostics.receipt['stages'][-1]['stage'],'document.setModified')
    def test_default_engine_and_subclass_do_not_implicitly_acquire_listener_or_handles(self):
        e=self.engine();calls=[]
        class Doc:
            def setModified(self,v):calls.append(('modified',v))
            def close(self,v):calls.append(('close',v))
        e.close_document(Doc())
        self.assertEqual(calls,[('modified',False),('close',False)])
        self.assertIsNone(getattr(e,'fixture_lifetime',None));self.assertEqual(e.desktop.events,[])
        self.assertEqual(e.lifetime_diagnostics.receipt['stages'],[])
        self.assertIsNone(e._job_witness)
    def test_legacy_subclass_custom_init_does_not_gain_a_new_required_field(self):
        calls=[]
        class Legacy(smoke.Engine):
            def __init__(self):self.base_lifetime_enabled=False
        class Doc:
            def setModified(self,v):calls.append(('modified',v))
            def close(self,v):calls.append(('close',v))
        try:Legacy().close_document(Doc())
        except AttributeError as exc:self.fail('Default subclass gained an implicit fixture requirement: '+str(exc))
        self.assertEqual(calls,[('modified',False),('close',False)])


class FixtureRunCaseTests(unittest.TestCase):
    def setUp(self):
        self.modules=patch.dict(sys.modules,uno_modules());self.modules.start();self.addCleanup(self.modules.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name);(self.output/'fixtures').mkdir()
    def scenario(self,*,callback=None,close_error=None,early_error=None,early_rows=None,verify_ui=False):
        events=[];created=[]
        class Document:
            DataSource=None
            def __init__(self,desktop):self.desktop=desktop;self.DataSource=self
            def setPropertyValue(self,*args):pass
            def initNew(self):pass
            def store(self):events.append('store')
            def setModified(self,v):events.append('modified')
            def close(self,v):
                events.append('close')
                if close_error:raise close_error
                if callback:getattr(self.desktop.listeners[0],callback)(None)
                if not self.desktop.listeners:raise RuntimeError('unheld service terminated between documents')
                try:self.desktop.listeners[0].queryTermination(None)
                except TerminationVetoException:events.append('veto')
        class Engine(smoke.Engine):
            def __init__(self,suite):super().__init__(suite);created.append(self)
            def start(self):
                events.append('start')
                old,_,_=fixtures.OwnedJobCleanupTests().scenario(graceful=True)
                self.process,self.profile=old.process,old.profile
                self.desktop=Desktop(events)
            def _capture_members(self,phase):
                events.append(phase)
                if early_error and phase=='fixture-before-first-load':raise early_error
                if early_rows is not None and phase=='fixture-before-first-load':return early_rows
                return super()._capture_members(phase)
            def load(self,url):events.append('load');return Document(self.desktop)
            def service(self,name):events.append('service');return Document(self.desktop)
            def store_new(self,document,path,filter_name):path.write_bytes(b'generated');events.append('store-new')
        return Engine,events,created
    def run_case(self,module='writer',**options):
        verify_ui=options.pop('verify_ui',False);factory,events,created=self.scenario(verify_ui=verify_ui,**options)
        path=self.output/'fixtures'/smoke.FILES[module]
        if verify_ui:path.write_bytes(b'generated')
        spec=dict(factory=smoke.FACTORIES[module],filters={path.suffix[1:]:'fixed'})
        with patch.object(smoke,'Engine',factory),patch.object(smoke,'populate'),patch.object(smoke,'observe',return_value=observations(module)):
            result=smoke.run_case(Path('/generated-suite'),self.output,module,spec,verify_ui)
        return result,events,created[0]
    def test_all_six_fixture_roundtrips_own_lifetime_and_admit_generation_before_first_load(self):
        for module in smoke.FILES:
            with self.subTest(module=module):
                result,events,engine=self.run_case(module)
                self.assertEqual(result['status'],'passed',result)
                self.assertLess(events.index('add'),events.index('fixture-before-first-load'))
                self.assertLess(events.index('fixture-before-first-load'),events.index('load' if module!='base' else 'service'))
                self.assertLess(events.index('close'),events.index('remove'))
                self.assertLess(events.index('remove'),events.index('terminate'))
                self.assertEqual(events.count('close'),2)
                self.assertEqual(events.count('modified'),2)
                self.assertEqual(events.count('load'),1 if module=='base' else 2)
                self.assertTrue(result['engineCleanup']['initialMembers'])
                self.assertTrue(result['engineCleanup']['gracefulQualified'])
                json.dumps(result,allow_nan=False)
    def test_verify_ui_owned_fixture_is_opted_in_too(self):
        result,events,_=self.run_case('writer',verify_ui=True)
        self.assertEqual(result['status'],'passed',result)
        self.assertEqual(events.count('load'),1)
        self.assertLess(events.index('fixture-before-first-load'),events.index('load'))
    def test_early_witness_failure_is_fatal_before_load_and_listener_release_still_runs(self):
        result,events,_=self.run_case(early_error=RuntimeError('no expected native generation'))
        self.assertEqual(result['status'],'failed');self.assertNotIn('load',events)
        self.assertEqual(result['error']['message'],'no expected native generation')
        self.assertIn('remove',events)
        self.assertLess(events.index('remove'),events.index('terminate'))
    def test_original_close_exception_is_never_disposed_as_success_or_retried_for_reopen(self):
        result,events,_=self.run_case(close_error=RuntimeError('bridge disposed'))
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error']['message'],'bridge disposed')
        self.assertEqual(events.count('load'),1);self.assertEqual(events.count('close'),2)
        self.assertIn('remove',events)
        self.assertIn('cleanupErrors',result);self.assertLess(events.index('remove'),events.index('terminate'))
    def test_early_member_identity_or_expected_alive_image_cannot_be_invented(self):
        good=dict(pid=42,creationTime=123,handleValue=99,image='/generated-suite/Office/program/soffice.bin',alive=True)
        rows=[[],[dict(good,error=dict(winerror=5))]]
        rows.extend([dict(good,**{key:value})] for key,value in
            [('pid',True),('creationTime',0),('handleValue',None),('image','/foreign/soffice.bin'),('alive',False),('alive',1)])
        for value in rows:
            with self.subTest(rows=value):
                result,events,_=self.run_case(early_rows=value)
                self.assertEqual(result['status'],'failed');self.assertNotIn('load',events)
                self.assertLess(events.index('remove'),events.index('terminate'))
    def test_unexpected_callback_is_fatal_even_when_fake_close_returns(self):
        for callback in ('notifyTermination','disposing'):
            with self.subTest(callback=callback):
                result,events,_=self.run_case(callback=callback)
                self.assertEqual(result['status'],'failed');self.assertNotIn('sha256',result)
                self.assertIn('remove',events)
                self.assertLess(events.index('remove'),events.index('terminate'))


if __name__=='__main__':unittest.main()
