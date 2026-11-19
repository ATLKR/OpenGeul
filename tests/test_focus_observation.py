"""Only synthetic native observations; original startup helpers remain real."""
import ast
import ctypes as C
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import test_runner_ready as original


class Fn:
    def __init__(self, callback):self.callback=callback
    def __call__(self,*args):return self.callback(*args)


class NativeFake:
    def __init__(self, flags=1, show=0, values=(0,0,1), fail=0, clock=None):
        self.calls=[];self.flags=flags;self.show=show;self.fail=fail;self.clock=clock
        self.functions={}
        for index,name in enumerate(('IsWindowVisible','IsIconic','IsWindowEnabled','GetStartupInfoW'),1):
            def call(*args,i=index,n=name):
                self.calls.append(n)
                if self.fail==i:raise OSError('synthetic private native detail')
                if self.clock and self.fail==5:self.clock[0]=65
                if i<4:return values[i-1]
                info=args[0]._obj;info.dwFlags=self.flags;info.wShowWindow=self.show
            self.functions[name]=Fn(call)
    def dll(self,name,**kwargs):
        class Dll:pass
        dll=Dll()
        for key,value in self.functions.items():setattr(dll,key,value)
        return dll


class ObservationTests(unittest.TestCase):
    def observe(self,value,native,*,before=20,baseline=20,deadline=65,clock=lambda:10):
        self.assertTrue(hasattr(value,'focus_visibility_observation'),'optional observation is absent')
        with patch.object(value.ctypes,'WinDLL',native.dll,create=True):
            return value.focus_visibility_observation(500,before,baseline,deadline,clock=clock)

    def test_hidden_launcher_show_setting_is_diagnostic_and_numeric_only(self):
        value=original.module();native=NativeFake(flags=0xffffffff,show=0)
        receipt=self.observe(value,native)
        self.assertEqual(receipt,dict(schemaVersion=1,knownMask=31,errorCode=0,windowFlags=4,
            startfUseShowWindow=1,wShowWindow=0,beforeForeground=2,afterForeground=3))
        self.assertEqual(len(native.calls),4)
        self.assertTrue(all(type(v)is int for v in receipt.values()))
        self.assertLessEqual(len(json.dumps(receipt).encode()),8192)

    def test_each_metadata_exception_keeps_prefix_and_excludes_private_error(self):
        for fail in range(1,5):
            value=original.module();receipt=self.observe(value,NativeFake(fail=fail))
            self.assertEqual(receipt['errorCode'],fail+2)
            self.assertEqual(receipt['knownMask'],16|((1<<(fail-1))-1))
            self.assertNotIn('private',json.dumps(receipt))

    def test_expired_optional_budget_performs_no_api_and_never_extends_deadline(self):
        value=original.module();native=NativeFake()
        receipt=self.observe(value,native,deadline=10)
        self.assertEqual(receipt['errorCode'],1);self.assertEqual(native.calls,[])
        clock=[10];native=NativeFake(fail=5,clock=clock)
        receipt=self.observe(value,native,deadline=65,clock=lambda:clock[0])
        self.assertEqual(receipt['errorCode'],1);self.assertEqual(len(native.calls),1)
        self.assertEqual(receipt['knownMask'],16)

    def test_original_setter_success_and_false_are_preserved_with_hidden_diagnostic(self):
        for setter in (False,True):
            value=original.module();native=NativeFake()
            fixture=original.StartupFixture(value,setter=setter)
            with patch.object(value.ctypes,'WinDLL',native.dll,create=True):result=fixture.run()
            self.assertEqual(result['setForegroundReturned'],setter)
            self.assertEqual(result['foregroundMatched'],setter)
            self.assertTrue(result['ownedWindowRemoved']);self.assertEqual(len(fixture.calls),1)
            self.assertTrue('foregroundObservation' in result)
            self.assertEqual(result['foregroundObservation']['windowFlags'],4)

    def test_original_none_baseline_and_zero_or_own_foreground_remain_accepted(self):
        for before in (0,500):
            value=original.module();fixture=original.StartupFixture(value,expires=0)
            create=fixture.user.CreateWindowExW
            def create_without_wsl(*args):
                hwnd=create(*args);fixture.fore=before;return hwnd
            fixture.user.CreateWindowExW=original.ApiCall(create_without_wsl)
            fixture.probe.windows=lambda:{'foregroundHwnd':fixture.fore,'windows':[],'truncated':False}
            # The original guard checks the original helper's fixed class/title.
            actual_class=fixture.user.GetClassNameW;actual_title=fixture.user.GetWindowTextW
            def class_name(hwnd,buf,count):
                if hwnd==500:buf.value='OpenGeulRunnerReadyOwnedProbe_100';return len(buf.value)
                return actual_class(hwnd,buf,count)
            def title(hwnd,buf,count):
                if hwnd==500:buf.value='OpenGeul CI owned focus probe';return len(buf.value)
                return actual_title(hwnd,buf,count)
            fixture.user.GetClassNameW=original.ApiCall(class_name);fixture.user.GetWindowTextW=original.ApiCall(title)
            fixture.user.GetWindowTextLengthW=original.ApiCall(lambda hwnd:len('OpenGeul CI owned focus probe'))
            with patch.object(value.ctypes,'WinDLL',NativeFake().dll,create=True):result=fixture.run()
            self.assertTrue(result['setForegroundReturned']);self.assertTrue(result['foregroundMatched'])
            self.assertEqual(len(fixture.calls),1)
            self.assertEqual(result['foregroundObservation']['beforeForeground'],int(before==500))

    def test_optional_internal_exception_never_changes_original_success_or_primary(self):
        for setter in (False,True):
            value=original.module();fixture=original.StartupFixture(value,setter=setter)
            def unavailable(*args,**kwargs):raise OSError('synthetic private optional detail')
            with patch.object(value,'focus_visibility_observation',unavailable):result=fixture.run()
            self.assertEqual(result['setForegroundReturned'],setter)
            self.assertEqual(result['foregroundMatched'],setter);self.assertEqual(len(fixture.calls),1)
            self.assertEqual(result['foregroundObservation']['errorCode'],2)
            self.assertIsNone(result['firstFailure'])
        value=original.module();fixture=original.StartupFixture(value)
        def original_failure(*args):raise ValueError('synthetic original setter failure')
        fixture.user.SetForegroundWindow=original.ApiCall(original_failure)
        with patch.object(value,'focus_visibility_observation',unavailable),self.assertRaises(ValueError):fixture.run()
        self.assertEqual(fixture.probe.last_focus_probe_result['firstFailure']['errorType'],'ValueError')
        self.assertTrue(fixture.probe.last_focus_probe_result['ownedWindowRemoved'])

    def test_native_abi_preserves_large_original_hwnd_and_reads_only_selected_fields(self):
        value=original.module();self.assertEqual(C.sizeof(value._FocusStartupInfo),104)
        self.assertEqual(value._FocusStartupInfo.dwFlags.offset,60)
        self.assertEqual(value._FocusStartupInfo.wShowWindow.offset,64)
        owned=(1<<40)+500;seen=[]
        query=C.CFUNCTYPE(C.c_int32,C.c_void_p)
        visible=query(lambda hwnd:seen.append(hwnd)or 1)
        iconic=query(lambda hwnd:seen.append(hwnd)or 0)
        enabled=query(lambda hwnd:seen.append(hwnd)or 1)
        startup_type=C.CFUNCTYPE(None,C.POINTER(value._FocusStartupInfo))
        def write(pointer):pointer.contents.dwFlags=0xffffffff;pointer.contents.wShowWindow=65535
        startup=startup_type(write)
        class Dll:pass
        def dll(name,**kw):
            result=Dll();result.IsWindowVisible=visible;result.IsIconic=iconic
            result.IsWindowEnabled=enabled;result.GetStartupInfoW=startup;return result
        with patch.object(value.ctypes,'WinDLL',dll,create=True):
            result=value.focus_visibility_observation(owned,0,None,65,clock=lambda:10)
        self.assertTrue(seen==[owned]*3)
        self.assertEqual(result['knownMask'],31);self.assertEqual(result['windowFlags'],5)
        self.assertEqual(result['startfUseShowWindow'],1);self.assertEqual(result['wShowWindow'],65535)

class SourceContracts(unittest.TestCase):
    def test_observer_has_no_input_or_foreground_api_and_no_opaque_startup_reads(self):
        tree=ast.parse((ROOT/'e2e/runner-ready.py').read_text())
        observer=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='focus_visibility_observation')
        attrs={n.attr for n in ast.walk(observer)if isinstance(n,ast.Attribute)}
        self.assertFalse(attrs&{'SetForegroundWindow','SendInput','ShowWindow','GetForegroundWindow',
            'SetWindowPos','AttachThreadInput','AllowSetForegroundWindow','SetPhysicalCursorPos'})
        selected={n.attr for n in ast.walk(observer)if isinstance(n,ast.Attribute)
            and isinstance(n.value,ast.Name)and n.value.id=='startup'and isinstance(n.ctx,ast.Load)}
        self.assertTrue(selected=={'dwFlags','wShowWindow'})


if __name__=='__main__':unittest.main()
