"""Synthetic self-termination boundaries; no native process is terminated."""
import ast
import ctypes
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e/native_menu_controller_fence.py'


class ExitTaken(BaseException):
    pass


class NativeFunction:
    def __init__(self, action):
        self.action = action
        self.argtypes = self.restype = None

    def __call__(self, *args):
        return self.action(*args)


class NativeMenuControllerFenceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), 'The opt-in controller fence is missing')
        spec = importlib.util.spec_from_file_location('synthetic_menu_controller_fence', SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.events = []
        self.handlers = []
        self.process = ctypes.c_void_p(-1).value
        self.comtypes = SimpleNamespace(_shutdown=lambda: None,
            __spec__=SimpleNamespace(_initializing=False))
        self.lease = SimpleNamespace(pending=True)
        self.pending = lambda: self.lease
        self.kernel = SimpleNamespace(
            GetCurrentProcess=NativeFunction(self.current_process),
            TerminateProcess=NativeFunction(self.terminate))
        self.enterContext(patch.object(self.module, 'os', SimpleNamespace(name='nt', _exit=self.fallback)))
        self.enterContext(patch.object(self.module, 'sys', SimpleNamespace(modules={'comtypes': self.comtypes})))
        self.enterContext(patch.object(self.module, 'atexit', SimpleNamespace(register=self.register)))
        native = SimpleNamespace(c_void_p=ctypes.c_void_p, c_uint32=ctypes.c_uint32,
            c_int32=ctypes.c_int32, WinDLL=self.load_kernel)
        self.enterContext(patch.object(self.module, 'ctypes', native))

    def load_kernel(self, name, *, use_last_error):
        self.events.append(('load', int(name == 'kernel32'), int(use_last_error is True)))
        return self.kernel

    def current_process(self):
        self.events.append(('current',))
        return self.process

    def terminate(self, handle, code):
        self.events.append(('terminate', int(handle == self.process), code))
        return 0

    def fallback(self, code):
        self.events.append(('fallback', code))
        raise ExitTaken()

    def register(self, function):
        self.handlers.append(function)
        self.events.append(('register',))

    def install(self):
        return self.module.install(self.pending, enabled=True)

    def test_disabled_install_has_no_runtime_pending_or_registration_side_effect(self):
        self.pending = lambda: self.fail('Disabled installation queried pending state')
        self.assertIsNone(self.module.install(self.pending))
        self.assertEqual(len(self.events), 0)
        self.assertEqual(len(self.handlers), 0)

    def test_enable_requires_an_explicit_boolean(self):
        for value in (1, None, 'true'):
            with self.subTest(value=value), self.assertRaises(self.module.FenceUnavailable):
                self.module.install(self.pending, enabled=value)
        self.assertEqual(len(self.events), 0)

    def test_non_windows_or_incomplete_comtypes_import_refuses_enable(self):
        for platform, loaded, initializing in (('posix', True, False),
                ('nt', False, False), ('nt', True, True)):
            with self.subTest(platform=platform, loaded=loaded, initializing=initializing):
                self.module.os.name = platform
                self.module.sys.modules = {'comtypes': self.comtypes} if loaded else {}
                self.comtypes.__spec__._initializing = initializing
                with self.assertRaises(self.module.FenceUnavailable):
                    self.install()
        self.assertEqual(len(self.events), 0)

    def test_missing_shutdown_or_pending_hook_refuses_enable(self):
        self.comtypes._shutdown = None
        with self.assertRaises(self.module.FenceUnavailable): self.install()
        self.comtypes._shutdown = lambda: None
        with self.assertRaises(self.module.FenceUnavailable):
            self.module.install(None, enabled=True)
        self.assertEqual(len(self.events), 0)

    def test_native_function_signatures_and_internal_pseudo_handle_are_fixed(self):
        self.install()
        self.assertTrue(self.kernel.GetCurrentProcess.argtypes == ())
        self.assertTrue(self.kernel.GetCurrentProcess.restype is ctypes.c_void_p)
        self.assertTrue(self.kernel.TerminateProcess.argtypes == (ctypes.c_void_p, ctypes.c_uint32))
        self.assertTrue(self.kernel.TerminateProcess.restype is ctypes.c_int32)
        self.assertTrue(self.events == [('load', 1, 1), ('current',), ('register',)])

    def test_same_pending_hook_registers_once_and_foreign_hook_is_rejected(self):
        first = self.install()
        self.assertTrue(self.install() is first)
        with self.assertRaises(self.module.FenceUnavailable):
            self.module.install(lambda: None, enabled=True)
        self.assertEqual(len(self.handlers), 1)
        self.assertEqual(sum(row[0] == 'current' for row in self.events), 1)

    def test_null_or_invalid_native_handle_refuses_registration(self):
        for handle in (None, 0, True, 'external'):
            self.process = handle
            with self.subTest(code=type(handle).__name__), self.assertRaises(self.module.FenceUnavailable):
                self.install()
        self.assertEqual(len(self.handlers), 0)

    def test_native_binding_failure_does_not_register_or_expose_raw_error(self):
        def broken(*args, **kwargs): raise OSError('synthetic private binding detail')
        self.module.ctypes.WinDLL = broken
        with self.assertRaises(self.module.FenceUnavailable) as failure:
            self.install()
        self.assertFalse('synthetic private' in str(failure.exception))
        self.assertIsNone(failure.exception.__cause__)
        self.assertTrue(failure.exception.__suppress_context__)
        self.assertEqual(len(self.handlers), 0)

    def test_pending_none_or_confirmed_retired_has_no_termination_call(self):
        fence = self.install()
        for lease in (None, SimpleNamespace(pending=False)):
            self.lease = lease
            fence.finish()
        self.assertEqual(sum(row[0] == 'terminate' for row in self.events), 0)
        self.assertEqual(sum(row[0] == 'fallback' for row in self.events), 0)

    def test_pending_capsule_uses_only_bound_self_handle_and_fixed_failure_exit(self):
        fence = self.install()
        with self.assertRaises(ExitTaken): fence.finish()
        self.assertTrue(self.events[-2:] == [('terminate', 1, 86), ('fallback', 86)])

    def test_native_base_exception_cannot_open_normal_python_teardown(self):
        def interrupted(handle, code): raise KeyboardInterrupt()
        self.kernel.TerminateProcess.action = interrupted
        fence = self.install()
        with self.assertRaises(ExitTaken): fence.finish()
        self.assertTrue(self.events[-1] == ('fallback', 86))

    def test_unexpected_nonzero_native_return_still_uses_nonreturning_fallback(self):
        self.kernel.TerminateProcess.action = lambda handle, code: 1
        fence = self.install()
        with self.assertRaises(ExitTaken): fence.finish()
        self.assertTrue(self.events[-1] == ('fallback', 86))

    def test_native_exception_uses_fallback_without_rendering_exception(self):
        class PrivateFailure(Exception):
            def __str__(self): raise AssertionError('Exception text must not be read')
            def __repr__(self): raise AssertionError('Exception representation must not be read')
        def broken(handle, code): raise PrivateFailure()
        self.kernel.TerminateProcess.action = broken
        fence = self.install()
        with self.assertRaises(ExitTaken): fence.finish()
        self.assertTrue(self.events[-1] == ('fallback', 86))

    def test_pending_observation_failure_cannot_fall_through_to_comtypes_teardown(self):
        def broken(): raise RuntimeError('synthetic private registry detail')
        self.pending = broken
        fence = self.install()
        with self.assertRaises(ExitTaken): fence.finish()
        self.assertTrue(self.events[-2:] == [('terminate', 1, 86), ('fallback', 86)])

    def test_malformed_pending_state_is_not_treated_as_confirmed_retirement(self):
        fence = self.install()
        for lease in (object(), SimpleNamespace(pending=0), SimpleNamespace(pending=None)):
            self.lease = lease
            with self.assertRaises(ExitTaken): fence.finish()
        self.assertEqual(sum(row[0] == 'terminate' for row in self.events), 3)

    def test_guard_does_not_retire_wait_release_or_import_anything(self):
        class Lease:
            pending = True
            def retire(self, *args): raise AssertionError('Exit guard must not wait or retire')
        self.lease = Lease()
        fence = self.install()
        with patch('builtins.__import__', side_effect=AssertionError('Exit guard must not import')):
            with self.assertRaises(ExitTaken): fence.finish()
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        finish = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'finish')
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(finish)))

    def test_lifo_backup_runs_before_preexisting_comtypes_shutdown(self):
        self.handlers.append(lambda: self.events.append(('comtypes-shutdown',)))
        self.install()
        with self.assertRaises(ExitTaken):
            for handler in reversed(self.handlers): handler()
        self.assertEqual(sum(row[0] == 'comtypes-shutdown' for row in self.events), 0)

    def test_explicit_finish_can_follow_closed_failure_output_before_python_teardown(self):
        fence = self.install()
        self.events.append(('failure-output-closed',))
        with self.assertRaises(ExitTaken): fence.finish()
        self.assertTrue(self.events[-3:] == [('failure-output-closed',), ('terminate', 1, 86), ('fallback', 86)])


if __name__ == '__main__':
    unittest.main()
