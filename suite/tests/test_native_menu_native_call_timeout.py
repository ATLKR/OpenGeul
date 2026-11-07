"""Synthetic SDK ownership facts; actual WinDLL admission is Windows-only."""
from contextlib import contextmanager
import ctypes as C
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import owned_native_menu as menu
from suite.tests.test_native_menu_provider_timeout import Clock, Provider


class Export:
    def __init__(self, library, name):
        self._objects = {'0': library}
        self.__name__ = name
        self.argtypes = self.restype = self.errcheck = None
        self.calls, self.result, self.effect, self.failure = [], 1, None, None

    def __call__(self, *args):
        self.calls.append(args)
        if self.failure is not None:
            raise self.failure
        if self.effect is not None:
            self.effect()
        return self.result


class Library:
    _func_flags_ = 0

    def __init__(self, name, *, use_last_error=False):
        self._name, self.lookups = name, []
        self._FuncPtr = type('Export', (Export,), {
            '_flags_': C._FUNCFLAG_USE_LASTERROR if use_last_error else 0})

    def __getitem__(self, name):
        return self._FuncPtr(self, name)

    def __getattr__(self, name):
        self.lookups.append(name)
        function = self[name]
        setattr(self, name, function)
        return function


SDK_CALL=Export.__call__


@contextmanager
def sdk_probe(*, factory=Library, **libraries):
    # Model the private platform root explicitly; this is not WinDLL proof.
    with patch.object(menu, '_OWNED_WINDLL_TYPE', Library, create=True), \
         patch.object(menu, '_OWNED_CFUNC_CALL', SDK_CALL, create=True), \
         patch.object(menu.C, 'WinDLL', factory, create=True):
        clock = Clock()
        probe = menu.NativeMenuProbe(5, clock, **libraries)
        probe.provider_client = Provider(clock)
        yield probe


class NativeOnlyCallTimeoutTests(unittest.TestCase):
    def assert_native_record(self, probe, *, phase=4, failed=False, completed=True):
        call = probe.interop['lastCall']
        self.assertEqual((call['apiCode'], call['phaseCode'], call['providerStep']), (0, phase, 0))
        self.assertEqual((call['failed'], call['callCompleted']), (failed, completed))
        self.assertNotIn('providerBudget', call)
        return call

    def test_owned_typed_native_zero_skips_all_provider_operations(self):
        with sdk_probe() as probe:
            probe.provider_timeout_verified = True
            function = probe.user.IsWindow
            lookups = list(probe.user.lookups)
            self.assertEqual(probe._call(function, 7), 1)
            self.assertEqual(probe.provider_client.operations, [])
            self.assertEqual(len(function.calls), 1)
            self.assertEqual(probe.user.lookups, lookups)
            self.assertIs(probe.provider_timeout_verified, True)
            self.assert_native_record(probe)
            self.assertIsNone(probe._observed_call)
        with sdk_probe() as probe:
            probe._call(probe.kernel.GetProcessId, 7)
            self.assertFalse(hasattr(probe, 'provider_timeout_verified'))
            self.assertEqual(probe.provider_client.operations, [])

    def test_nonzero_and_unknown_api_contexts_keep_provider_setup(self):
        class Integer(int):
            pass
        for context in ({'apiCode': 4}, {'apiCode': 5}, {'apiCode': False},
                        {'apiCode': 0.0}, {'apiCode': Integer(0)}, {}, object()):
            with self.subTest(context_type=type(context).__name__), sdk_probe() as probe:
                probe._observed_call = context
                probe._call(probe.user.IsWindow, 7)
                self.assertEqual(len(probe.provider_client.operations), 4)
                self.assertIs(probe._observed_call, context)

    def test_zero_com_unknown_wrappers_other_dll_and_callbacks_keep_setup(self):
        for kind in ('lambda', 'tree', 'collection', 'wrapper', 'dwm', 'other-dll', 'new-object', 'late-export', 'callback'):
            with self.subTest(kind=kind), sdk_probe() as probe:
                class Com:
                    def parent(self): return 1
                    def element(self): return 1
                candidates = {
                    'lambda': lambda: 1,
                    'tree': Com().parent,
                    'collection': Com().element,
                    'wrapper': lambda: probe.user.IsWindow(7),
                    'dwm': probe.dwm.DwmGetWindowAttribute,
                    'other-dll': Library('ole32', use_last_error=True)['IsWindow'],
                    'new-object': probe.user['IsWindow'],
                    'late-export': probe.user.GetWindowLongW,
                    'callback': C.CFUNCTYPE(C.c_int)(lambda: 1),
                }
                probe._call(candidates[kind])
                self.assertEqual(len(probe.provider_client.operations), 4)
                self.assertIn('providerBudget', probe.interop['lastCall'])

    def test_actual_uia_code_four_and_five_paths_keep_setup_for_same_native_object(self):
        for code in (4, 5):
            with self.subTest(code=code), sdk_probe() as probe:
                probe._uia = object()
                probe._uia_call(code, probe.user.IsWindow, 7)
                self.assertEqual(len(probe.provider_client.operations), 4)
                self.assertEqual(probe.interop['lastCall']['apiCode'], code)
                self.assertIsNone(probe._observed_call)

    def test_errcheck_present_at_registration_is_not_admitted(self):
        original = Export.__init__
        def initialize(self, library, name):
            original(self, library, name)
            if name == 'IsWindow': self.errcheck = lambda value, *args: value
        with patch.object(Export, '__init__', initialize), sdk_probe() as probe:
            probe._call(probe.user.IsWindow, 7)
            self.assertEqual(len(probe.provider_client.operations), 4)
        with patch.object(Export, '__call__', lambda self, *args: 1), sdk_probe() as probe:
            probe._call(probe.user.IsWindow, 7)
            self.assertEqual(len(probe.provider_client.operations), 4)

    def test_injected_or_replaced_creators_do_not_create_native_trust(self):
        for libraries in ({'user': Library('user32', use_last_error=True)},
                          {'kernel': Library('kernel32', use_last_error=True)}):
            with sdk_probe(**libraries) as probe:
                function = probe.user.IsWindow if 'user' in libraries else probe.kernel.GetProcessId
                probe._call(function, 7)
                self.assertEqual(len(probe.provider_client.operations), 4)
        with sdk_probe(factory=lambda *a, **k: Library(*a, **k)) as probe:
            probe._call(probe.user.IsWindow, 7)
            self.assertEqual(len(probe.provider_client.operations), 4)
        original = menu.NativeActivationProbe.__init__
        def wrapper(self, *args, **kwargs):
            return original(self, *args, **kwargs)
        with patch.object(menu.NativeActivationProbe, '__init__', wrapper), sdk_probe() as probe:
            probe._call(probe.user.IsWindow, 7)
            self.assertEqual(len(probe.provider_client.operations), 4)

    def test_changed_library_export_owner_signature_flags_or_errcheck_falls_back(self):
        class Name(str):
            pass
        for kind in ('library', 'name', 'dll-name-type', 'export-name-type', 'cached-export', 'deleted-export', 'pointer-type',
                     'owner', 'argtypes', 'restype', 'flags', 'flags-type', 'errcheck', 'call-wrapper'):
            with self.subTest(kind=kind), sdk_probe() as probe:
                library, function = probe.user, probe.user.IsWindow
                lookups = list(library.lookups)
                if kind == 'library': probe.user = Library('user32', use_last_error=True)
                elif kind == 'name': library._name = 'ole32'
                elif kind == 'dll-name-type': library._name = Name('user32')
                elif kind == 'export-name-type': function.__name__ = Name('IsWindow')
                elif kind == 'cached-export': library.IsWindow = library['IsWindow']
                elif kind == 'deleted-export': del library.IsWindow
                elif kind == 'pointer-type': library._FuncPtr = type('Other', (Export,), {'_flags_': 16})
                elif kind == 'owner': function._objects['0'] = object()
                elif kind == 'argtypes': function.argtypes = list(function.argtypes)
                elif kind == 'restype': function.restype = C.c_uint64
                elif kind == 'flags': type(function)._flags_ = 0
                elif kind == 'flags-type': type(function)._flags_ = 16.0
                elif kind == 'errcheck': function.errcheck = lambda value, *args: value
                elif kind == 'call-wrapper': type(function).__call__ = lambda self, *args: 1
                probe._call(function, 7)
                self.assertEqual(len(probe.provider_client.operations), 4)
                if kind != 'library': self.assertEqual(library.lookups, lookups)

    def test_reused_zero_context_has_a_fresh_native_record_and_restores_original(self):
        with sdk_probe() as probe:
            old = probe._call_record(0)
            budget = {'observedMask': 15, 'setupComplete': 1}
            old.update(providerStep=4, providerBudget=budget)
            probe._observed_call = old
            probe._call(probe.user.IsWindow, 7)
            self.assert_native_record(probe)
            self.assertIsNot(probe.interop['lastCall'], old)
            self.assertIs(probe._observed_call, old)
            self.assertIs(old['providerBudget'], budget)
            self.assertEqual(old['providerStep'], 4)

    def test_nested_native_call_does_not_relabel_outer_provider_budget(self):
        with sdk_probe() as probe:
            outer = []
            def com_call():
                outer.append(probe._observed_call)
                return probe._call(probe.kernel.GetProcessId, 7)
            self.assertEqual(probe._call(com_call), 1)
            self.assertEqual(len(probe.provider_client.operations), 4)
            self.assertIsNot(probe.interop['lastCall'], outer[0])
            self.assert_native_record(probe)
            self.assertEqual(outer[0]['providerBudget']['setupComplete'], 1)
            self.assertEqual(outer[0]['providerStep'], 4)
            self.assertEqual(outer[0]['phaseCode'], 4)
            self.assertIsNone(probe._observed_call)

    def test_outer_failure_after_nested_native_success_keeps_its_primary_call(self):
        for mode in ('exception', 'post-deadline'):
            with self.subTest(mode=mode), sdk_probe() as probe:
                primary = RuntimeError()
                outer = []
                def com_call():
                    outer.append(probe._observed_call)
                    probe._call(probe.kernel.GetProcessId, 7)
                    if mode == 'exception': raise primary
                    probe.clock.value = 5
                with self.assertRaises(RuntimeError if mode == 'exception' else AssertionError) as caught:
                    probe._call(com_call)
                if mode == 'exception': self.assertIs(caught.exception, primary)
                probe.capture_primary_failure(caught.exception)
                call = probe.interop['primaryFailureCall']
                self.assertIs(probe.interop['lastCall'], outer[0])
                self.assertIs(probe.interop['primaryFailureFromApi'], True)
                self.assertTrue(call['failed']);self.assertTrue(call['calleeEntered'])
                self.assertEqual((call['phaseCode'], call['callCompleted']),
                    (2, False) if mode == 'exception' else (3, True))
                self.assertEqual(call['providerBudget']['setupComplete'], 1)
                self.assertIsNone(probe._observed_call)

    def test_native_pre_post_deadlines_and_primary_exception_are_preserved(self):
        for mode in ('pre', 'post', 'exception'):
            with self.subTest(mode=mode), sdk_probe() as probe:
                class Failure(Exception):
                    def __str__(self): raise AssertionError('Exception text must not be read')
                primary = Failure()
                previous = None
                if mode == 'exception':
                    previous = probe._call_record(0)
                    previous.update(providerStep=4, providerBudget={'setupComplete': 1})
                    probe._observed_call = previous
                function = probe.user.IsWindow
                if mode == 'pre': probe.clock.value = 5
                elif mode == 'post': function.effect = lambda: setattr(probe.clock, 'value', 5)
                else: function.failure = primary
                with self.assertRaises(Failure if mode == 'exception' else AssertionError) as caught:
                    probe._call(function, 7)
                if mode == 'exception': self.assertIs(caught.exception, primary)
                self.assertIs(probe._last_call_exception, caught.exception)
                self.assertEqual(probe.provider_client.operations, [])
                self.assertIs(probe._observed_call, previous)
                call = self.assert_native_record(probe, phase={'pre': 0, 'post': 3, 'exception': 2}[mode],
                    failed=True, completed=mode == 'post')
                self.assertEqual(call['calleeEntered'], mode != 'pre')

    def test_optional_native_failure_keeps_primary_exception_channel_unchanged(self):
        with sdk_probe() as probe:
            primary, optional = RuntimeError(), RuntimeError()
            probe._last_call_exception = primary
            sink = {}; probe._diagnostic_sink = sink
            probe.user.IsWindow.failure = optional
            with self.assertRaises(RuntimeError) as caught: probe._call(probe.user.IsWindow, 7)
            self.assertIs(caught.exception, optional)
            self.assertIs(probe._last_call_exception, primary)
            self.assertNotIn('lastCall', probe.interop)
            self.assertEqual((sink['lastCall']['phaseCode'], sink['lastCall']['providerStep']), (2, 0))
            self.assertNotIn('providerBudget', sink['lastCall'])
            self.assertIsNone(probe._observed_call)

    def test_admitted_send_message_timeout_keeps_exact_remaining_bound(self):
        for milliseconds in (1000, 1001, 0, True):
            with self.subTest(milliseconds=milliseconds), sdk_probe() as probe:
                probe.clock.value = 4
                function = probe.user.SendMessageTimeoutW
                args = (7, 0x84, 0, 0, 3, milliseconds, None)
                if type(milliseconds) is int and milliseconds == 1000:
                    self.assertEqual(probe._call(function, *args), 1)
                    self.assert_native_record(probe)
                else:
                    with self.assertRaises(AssertionError): probe._call(function, *args)
                    self.assert_native_record(probe, phase=1, failed=True, completed=False)
                    self.assertFalse(function.calls)
                self.assertEqual(probe.provider_client.operations, [])

    def test_inherited_activation_calls_dispatch_through_menu_wrapper(self):
        with sdk_probe() as probe:
            probe.user.GetForegroundWindow.result = 7
            probe.user.GetAncestor.result = 9
            self.assertEqual(probe.foreground(), 9)
            self.assertEqual(probe.last_foreground_snapshot, {'rawHwnd': 7, 'rootHwnd': 9})
            self.assertEqual(probe.provider_client.operations, [])
            self.assert_native_record(probe)


@unittest.skipUnless(sys.platform == 'win32', 'actual WinDLL ownership facts require Windows')
class ActualWinDllAdmissionTests(unittest.TestCase):
    def test_cached_sdk_export_ownership_is_admitted_without_invoking_it(self):
        probe = menu.NativeMenuProbe(5, Clock())
        for library, name in ((probe.user, 'IsWindow'), (probe.kernel, 'GetProcessId')):
            function = vars(library)[name]
            self.assertIs(type(function), vars(library)['_FuncPtr'])
            self.assertIs(function._objects['0'], library)
            self.assertTrue(probe._native_timeout_exempt(function, probe._call_record(0)))


if __name__ == '__main__':
    unittest.main()
