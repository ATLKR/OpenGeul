"""One owned launcher route, numeric-only evidence and no retry."""
import unittest
import importlib

class ConsoleProbeTests(unittest.TestCase):
    def module(self):return importlib.import_module('reader_console_diagnostic')
    def test_handshake_rejects_extra_fields_nonintegers_and_expired_samples(self):
        m=self.module();good=dict(pid=1,tid=2,consoleHwnd=3,creationTime=7,observedAt=4.0,identityVerified=True)
        m.validate_handshake(good,0,30)
        for change in ({'title':'no'},{'pid':True},{'consoleHwnd':-1},{'observedAt':30.},{'identityVerified':False}):
            with self.assertRaises((AssertionError,ValueError)):m.validate_handshake(dict(good,**change),0,30)
    def test_foreign_console_is_rejected_before_visibility_query(self):
        m=self.module();calls=[]
        class Api:
            def owner(self,h):calls.append('owner');return 9,10
            def visible(self,h):calls.append('visible');return True
        with self.assertRaises(AssertionError):m.observe_owned_console(Api(),3,{1:dict(creationTime=7)},lambda:4.,30)
        self.assertEqual(calls,['owner'])
    def test_console_owner_is_rechecked_and_absence_is_not_inspected(self):
        m=self.module();calls=[]
        class Api:
            def owner(self,h):calls.append('owner');return (1,2) if len(calls)==1 else (9,2)
            def visible(self,h):calls.append('visible');return True
        self.assertEqual(m.observe_owned_console(Api(),0,{},lambda:4.,30),{'hwnd':0,'observedAt':4.,'associated':False})
        with self.assertRaises(AssertionError):m.observe_owned_console(Api(),3,{1:dict(creationTime=7)},lambda:4.,30)
    def test_single_launch_release_and_cleanup_share_original_deadline(self):
        m=self.module();calls=[]
        class Driver:
            def foreground(self):calls.append('foreground');return 5
            def launch(self,d):calls.append(('launch',d))
            def handshake(self,d):calls.append(('handshake',d));return dict(pid=1,tid=2,consoleHwnd=0,creationTime=7,observedAt=1.,identityVerified=True)
            def console(self,h,d):calls.append(('console',d));return {'hwnd':0,'observedAt':4.,'associated':False}
            def release(self):calls.append('release')
            def retire(self,d):calls.append(('retire',d));return True
            def terminate(self,d):calls.append(('terminate',d))
            def close(self):calls.append('close')
        result=m.execute(Driver(),clock=lambda:1.)
        self.assertTrue(result['success']);self.assertFalse(result['causalLinkProved'])
        self.assertEqual([c for c in calls if isinstance(c,tuple)],[('launch',31.),('handshake',26.),('console',26.),('retire',26.)])
        self.assertEqual(calls.count('release'),1);self.assertEqual(calls.count('foreground'),3)
    def test_failed_handshake_requests_retirement_once_then_forces_owned_cleanup(self):
        m=self.module();calls=[]
        class Driver:
            def foreground(self):return 5
            def launch(self,d):calls.append('launch')
            def handshake(self,d):raise TimeoutError()
            def release(self):calls.append('release')
            def retire(self,d):calls.append('retire');raise TimeoutError()
            def terminate(self,d):calls.append(('terminate',d))
            def close(self):calls.append('close')
        r=m.execute(Driver(),clock=lambda:1.)
        self.assertFalse(r['success']);self.assertEqual(calls,['launch','release','retire',('terminate',31.),'close'])
    def test_expiry_never_launches(self):
        m=self.module();times=iter([1.,32.,32.]);calls=[]
        class Driver:
            def foreground(self):return 1
            def launch(self,d):calls.append('launch')
            def close(self):calls.append('close')
        r=m.execute(Driver(),clock=lambda:next(times))
        self.assertFalse(r['success']);self.assertNotIn('launch',calls)

class NativeConsoleJoinTests(unittest.TestCase):
    def test_handshake_requires_actual_core_generation_not_launcher(self):
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        import reader_console_diagnostic as m
        for role,generation in ((1,7),(2,8)):
            driver=object.__new__(m.NativeDriver);driver.started=0
            driver.directory=NS(__truediv__=lambda x:None)
            class Directory:
                def __truediv__(self,n):return NS(exists=lambda:True)
            driver.directory=Directory();driver.process=NS(poll=lambda:None)
            driver.members=lambda deadline:{1:dict(role=role,creationTime=generation)}
            row=dict(pid=1,tid=2,consoleHwnd=3,creationTime=7,observedAt=1.,identityVerified=True)
            with patch.object(m,'read_small',return_value=row):
                with self.assertRaises(AssertionError):driver.handshake(30)
    def test_retained_member_generation_change_fails(self):
        from types import SimpleNamespace as NS
        import reader_console_diagnostic as m
        driver=object.__new__(m.NativeDriver);driver.images={'core':1}
        original=dict(image='core',creationTime=7,pid=1)
        driver.witnesses=NS(retained_snapshot=lambda:[dict(original,alive=True,waitResult=258)],
            members={1:(99,original)},api=NS(identity=lambda handle:dict(image='core',creationTime=8)))
        with self.assertRaises(AssertionError):driver.members(m.time.monotonic()+1)
    def test_owned_console_observation_is_numeric_only(self):
        import reader_console_diagnostic as m
        class Api:
            def owner(self,h):return 1,2
            def visible(self,h):return False
        row=m.observe_owned_console(Api(),3,{1:dict(creationTime=7)},lambda:4.,30)
        self.assertEqual(set(row),{'hwnd','pid','tid','creationTime','visible','observedAt','associated'})
        self.assertTrue(all(type(v) in (int,float,bool) for v in row.values()))
    def test_console_file_close_failure_cannot_report_success(self):
        from types import SimpleNamespace as NS
        import reader_console_diagnostic as m
        driver=object.__new__(m.NativeDriver)
        driver.witnesses=driver.process=None
        driver.console_file=NS(close=lambda:{'result':False,'lastError':6})
        with self.assertRaises(AssertionError):driver.close()
