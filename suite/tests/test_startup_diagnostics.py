"""Finite startup metadata uses the original retained process and owned windows."""
import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


E2E = Path(__file__).resolve().parents[1] / 'e2e'
if str(E2E) not in sys.path:
    sys.path.insert(0, str(E2E))


def implementation():
    assert E2E.joinpath('startup_diagnostics.py').is_file(), 'Startup diagnostic receiver required'
    return importlib.import_module('startup_diagnostics')


def packed(phase=2, reason=14, native=126, version=1):
    return version << 56 | phase << 48 | reason << 32 | native


def target(value=None):
    calls=[]
    process=SimpleNamespace(pid=77, _handle=707)
    state=dict(dialogPid=77, ownerPid=77, owner=11, root=11, live=True,
        value=packed() if value is None else value)
    def prop(hwnd, name):
        calls.append(('property', hwnd, name))
        return state['value']
    api=SimpleNamespace(pid=lambda hwnd: state['dialogPid'] if hwnd==12 else state['ownerPid'],
        user=SimpleNamespace(IsWindow=lambda hwnd: state['live'], GetPropW=prop,
            GetWindow=lambda hwnd, flag: state['owner'],
            GetAncestor=lambda hwnd, flag: state['root'] if hwnd==11 else hwnd))
    def wait(handle):
        calls.append(('wait', int(handle)))
        return 258
    return api, process, state, calls, wait


def observed_exception(environ=None):
    n=implementation()
    api, process, state, calls, wait=target()
    receipt=n.receive(api,process,12,11,wait_zero=wait,environ=environ or {n.OPT_IN:'1'})
    exc=AssertionError('SYNTHETIC PRIVATE startup C:/private/profile')
    n.attach(exc,receipt)
    return exc


class StartupDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.n=implementation()

    def test_finite_decode_accepts_exact_packed_values_and_rejects_other_bits_types(self):
        self.assertEqual(self.n.decode_property(packed()),[2,14,126])
        self.assertEqual(self.n.decode_property(packed(3,38,740)),[3,38,740])
        self.assertEqual(self.n.decode_property(packed(1,0,0)),[1,0,0])
        for value in (True,0,-1,float(packed()),str(packed()),1<<63,
                packed(version=2),packed(0),packed(4),packed(reason=28),packed(reason=31),
                packed(reason=39),packed(native=1),packed(native=65535)):
            with self.subTest(value=type(value).__name__):
                self.assertIsNone(self.n.decode_property(value))

    def test_missing_property_and_disabled_flag_never_load_or_wait_on_native_handle(self):
        for enabled,value in ((True,0),(False,packed())):
            api,process,state,calls,wait=target(value)
            process.__dict__.pop('_handle')
            with patch.object(self.n,'_native_wait_zero',side_effect=AssertionError('no native handle query')):
                receipt=self.n.receive(api,process,12,11,environ={self.n.OPT_IN:'1' if enabled else '0'})
            self.assertIsNone(receipt)
            self.assertEqual(len(calls),1 if enabled else 0)

    def test_admitted_property_is_bracketed_by_original_handle_and_owned_window_rechecks(self):
        api,process,state,calls,wait=target()
        receipt=self.n.receive(api,process,12,11,wait_zero=wait,environ={self.n.OPT_IN:'1'})
        self.assertEqual([row[0] for row in calls],['property','wait','property','wait'])
        self.assertEqual(calls[1],('wait',707))
        self.assertEqual(calls[2],('property',11,self.n.PROPERTY))
        exc=AssertionError('private message')
        self.n.attach(exc,receipt)
        self.assertEqual(self.n.project_exception(exc),dict(shellPid=77,startup=[2,14,126]))
        self.assertEqual(str(exc),'private message')

    def test_foreign_dead_replaced_or_changed_owner_property_is_unknown(self):
        for mutation in ('foreign-dialog','foreign-owner','dead-window','wrong-root','wrong-owner',
                'dead-process','replacement-handle','replacement-pid','changed-property','removed-property'):
            api,process,state,calls,wait=target()
            if mutation=='foreign-dialog':state['dialogPid']=78
            elif mutation=='foreign-owner':state['ownerPid']=78
            elif mutation=='dead-window':state['live']=False
            elif mutation=='wrong-root':state['root']=15
            elif mutation=='wrong-owner':state['owner']=15
            original_wait=wait
            def changed_wait(handle):
                result=original_wait(handle)
                if mutation=='dead-process':return 0
                if mutation=='replacement-handle':process._handle=708
                if mutation=='replacement-pid':process.pid=78
                if mutation=='changed-property':state['value']=packed(3,38,740)
                if mutation=='removed-property':state['value']=0
                return result
            with self.subTest(mutation=mutation):
                self.assertIsNone(self.n.receive(api,process,12,11,wait_zero=changed_wait,environ={self.n.OPT_IN:'1'}))

    def test_arbitrary_raw_tuple_or_dictionary_cannot_mint_observed_receipt(self):
        for value in ([2,14,126],dict(shellPid=77,startup=[2,14,126]),None):
            exc=AssertionError('private')
            self.n.attach(exc,value)
            self.assertIsNone(self.n.project_exception(exc))

    def test_optional_read_errors_return_unknown(self):
        api,process,state,calls,wait=target()
        api.user.GetPropW=lambda *args: (_ for _ in ()).throw(OSError('private native error'))
        self.assertIsNone(self.n.receive(api,process,12,11,wait_zero=wait,environ={self.n.OPT_IN:'1'}))

    def test_handle_replaced_during_presence_probe_cannot_become_the_original_handle(self):
        api,process,state,calls,wait=target()
        read=api.user.GetPropW
        def replaced(hwnd,name):
            result=read(hwnd,name)
            process._handle=708
            return result
        api.user.GetPropW=replaced
        self.assertIsNone(self.n.receive(api,process,12,11,wait_zero=wait,environ={self.n.OPT_IN:'1'}))

    def test_owner_changed_after_final_wait_is_rejected(self):
        api,process,state,calls,wait=target()
        count=0
        def changed(handle):
            nonlocal count
            count+=1
            if count==2:state['ownerPid']=78
            return wait(handle)
        self.assertIsNone(self.n.receive(api,process,12,11,wait_zero=changed,environ={self.n.OPT_IN:'1'}))

    def test_actual_owned_startup_branch_preserves_original_assertion_and_attaches_receipt(self):
        import windows_smoke as smoke
        from test_numeric_notice import environment
        api,process,state,calls,wait=target()
        original=object.__new__(smoke.Windows)
        original.__dict__.update(api.__dict__)
        original.windows=lambda pid:[12]
        original.title=lambda hwnd:'OpenGeul Office'
        original.class_name=lambda hwnd:'#32770'
        with patch.dict(os.environ,environment(),clear=True), patch.object(self.n,'_native_wait_zero',return_value=wait):
            try:
                original.attached(process)
            except AssertionError as exc:
                self.assertEqual(str(exc),'Owned Suite startup-error dialog HWND 12 owner 11; inspect case stderr log')
                self.assertEqual(self.n.project_exception(exc),dict(shellPid=77,startup=[2,14,126]))
            else:self.fail('Original startup error must remain primary')
        self.assertEqual([row[0] for row in calls],['property','wait','property','wait'])


if __name__=='__main__':
    unittest.main()
