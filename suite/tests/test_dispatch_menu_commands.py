"""Native document-menu commands retain the existing Suite command owner."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


WORKER = Path(__file__).resolve().parents[1] / 'worker'
sys.path.insert(0, str(WORKER))
spec = importlib.util.spec_from_file_location('document_menu_dispatch', WORKER / 'dispatch.py')
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


class NativeProvider:
    def __init__(self):
        self.calls = []
        self.result = object()

    def queryDispatch(self, url, target, flags):
        self.calls.append((url, target, flags))
        return self.result


class DispatchMenuCommandsTests(unittest.TestCase):
    def router(self, module='writer'):
        events = []
        router = dispatch.DispatchRouter(
            lambda command, target_module=None: events.append((command, target_module or module)))
        native = NativeProvider()
        router.setSlaveDispatchProvider(native)
        return router, native, events

    def test_native_add_direct_creates_one_document_in_the_current_module(self):
        for module in dispatch.FACTORIES:
            with self.subTest(module=module):
                router, native, events = self.router(module)
                url = SimpleNamespace(Complete='.uno:AddDirect')
                self.assertIs(router.queryDispatch(url, '_self', 0), router)
                router.dispatch(url, ())
                self.assertEqual(events, [('new', module)])
                self.assertEqual(native.calls, [])
                self.assertIn('.uno:AddDirect', router.getInterceptedURLs())

    def test_actual_writer_and_calc_open_entries_use_the_existing_shell_dialog(self):
        for name, module in (('.uno:OpenFromWriter', 'writer'), ('.uno:OpenFromCalc', 'calc')):
            with self.subTest(command=name):
                router, native, events = self.router(module)
                url = SimpleNamespace(Complete=name)
                self.assertIs(router.queryDispatch(url, '_self', 0), router)
                router.dispatch(url, (SimpleNamespace(Name='URL', Value='file:///ignored.odt'),))
                self.assertEqual(events, [('open', module)])
                self.assertEqual(native.calls, [])
                self.assertIn(name, router.getInterceptedURLs())

    def test_new_native_home_entry_routes_once_from_the_owned_current_module(self):
        for module in dispatch.FACTORIES:
            with self.subTest(module=module):
                router, native, events = self.router(module)
                url = SimpleNamespace(Complete='.uno:StartModule')
                self.assertIs(router.queryDispatch(url, '_self', 0), router)
                router.dispatch(url, (SimpleNamespace(Name='Module', Value='untrusted-target'),))
                self.assertEqual(events, [('home', module)])
                self.assertEqual(native.calls, [])
                self.assertIn('.uno:StartModule', router.getInterceptedURLs())

    def test_native_home_entry_keeps_the_existing_status_listener_contract(self):
        router, native, events = self.router('calc')
        url = SimpleNamespace(Complete='.uno:StartModule')
        self.assertIs(router.queryDispatch(url, '_self', 0), router)
        states = []
        uno = SimpleNamespace(createUnoStruct=lambda name: SimpleNamespace())
        with patch.dict(sys.modules, {'uno': uno}):
            router.addStatusListener(SimpleNamespace(statusChanged=states.append), url)
        self.assertEqual(len(states), 1)
        self.assertIs(states[0].Source, router)
        self.assertIs(states[0].FeatureURL, url)
        self.assertIs(states[0].IsEnabled, True)
        self.assertEqual(events, [])
        self.assertEqual(native.calls, [])

    def test_supported_document_commands_keep_the_original_document_owner(self):
        router, native, events = self.router('calc')
        for name, expected in (('.uno:Save', 'save'), ('.uno:SaveAs', 'saveAs'),
                               ('file:///ignored.ods', 'open'), ('.uno:NewDoc', 'new'),
                               ('.uno:CloseDoc', 'close')):
            url = SimpleNamespace(Complete=name)
            self.assertIs(router.queryDispatch(url, '_self', 0), router)
            router.dispatch(url, ())
            self.assertEqual(events[-1], (expected, 'calc'))
        self.assertEqual(len(events), 5)
        self.assertEqual(native.calls, [])

    def test_explicit_hwp_new_command_preserves_its_target_without_an_office_factory(self):
        router, native, events = self.router('calc')
        self.assertNotIn('hwp', dispatch.FACTORIES)
        self.assertEqual(set(dispatch.FACTORIES), {'writer', 'calc', 'impress', 'draw', 'math', 'base'})
        url = SimpleNamespace(Complete='vnd.opengeul.office:new-hwp')
        self.assertIs(router.queryDispatch(url, '_self', 0), router)
        states = []
        with patch.dict(sys.modules, {'uno': SimpleNamespace(createUnoStruct=lambda name: SimpleNamespace())}):
            router.addStatusListener(SimpleNamespace(statusChanged=states.append), url)
        self.assertEqual(len(states), 1)
        self.assertIs(states[0].IsEnabled, True)
        self.assertIs(states[0].Source, router)
        self.assertIs(states[0].FeatureURL, url)
        router.dispatch(url, ())
        self.assertEqual(events, [('new', 'hwp')])
        self.assertEqual(native.calls, [])
        self.assertIn(url.Complete, router.getInterceptedURLs())

    def test_unknown_and_query_product_commands_cannot_reach_a_native_launcher(self):
        router, native, events = self.router()
        for name in ('vnd.opengeul.office:unknown', 'vnd.opengeul.office:new-hwp?module=writer',
                     'vnd.opengeul.office:new-hwp/unknown'):
            with self.subTest(command=name):
                url = SimpleNamespace(Complete=name)
                self.assertIs(router.queryDispatch(url, '_self', 0), router)
                router.dispatch(url, ())
                states = []
                with patch.dict(sys.modules, {'uno': SimpleNamespace(createUnoStruct=lambda name: SimpleNamespace())}):
                    router.addStatusListener(SimpleNamespace(statusChanged=states.append), url)
                self.assertIs(states[0].IsEnabled, False)
        self.assertEqual(events, [])
        self.assertEqual(native.calls, [])

    def test_quit_and_exit_request_suite_exit_from_the_current_module(self):
        for module in dispatch.FACTORIES:
            for name in ('.uno:Quit', '.uno:Exit'):
                with self.subTest(module=module, command=name):
                    router, native, events = self.router(module)
                    url = SimpleNamespace(Complete=name)
                    self.assertIs(router.queryDispatch(url, '_self', 0), router)
                    router.dispatch(url, ())
                    self.assertEqual(events, [('exit', module)])
                    self.assertEqual(native.calls, [])

    def test_unsupported_file_semantics_are_explicitly_disabled_without_action(self):
        names=('.uno:SaveAll', '.uno:SaveACopy', '.uno:SaveAsTemplate',
               '.uno:SaveAsRemote', '.uno:OpenRemote', '.uno:NewWindow')
        for name in names:
            for suffix in ('', '?unsupported-options'):
                with self.subTest(command=name, suffix=suffix):
                    router, native, events = self.router('calc')
                    url = SimpleNamespace(Complete=name + suffix)
                    self.assertIs(router.queryDispatch(url, '_self', 0), router)
                    states = []
                    with patch.dict(sys.modules, {'uno': SimpleNamespace(createUnoStruct=lambda name: SimpleNamespace())}):
                        router.addStatusListener(SimpleNamespace(statusChanged=states.append), url)
                    self.assertEqual(len(states), 1)
                    self.assertIs(states[0].Source, router)
                    self.assertIs(states[0].FeatureURL, url)
                    self.assertIs(states[0].IsEnabled, False)
                    router.dispatch(url, ())
                    self.assertEqual(events, [])
                    self.assertEqual(native.calls, [])
                    self.assertNotIn(name, dispatch.COMMANDS)
                    self.assertIn(name, router.getInterceptedURLs())

    def test_editing_formatting_and_nonexact_aliases_keep_the_native_provider(self):
        router, native, events = self.router()
        for name in ('.uno:Bold', '.uno:Italic', '.uno:InsertTable',
                     '.uno:AddDirectOther', '.uno:OpenFromWriterOther', '.uno:StartModuleOther'):
            url = SimpleNamespace(Complete=name)
            self.assertIs(router.queryDispatch(url, '_self', 17), native.result)
            self.assertEqual(native.calls[-1], (url, '_self', 17))
        self.assertEqual(events, [])

    def test_exact_known_factories_preserve_the_validated_target_module(self):
        router, native, events = self.router()
        for module, factory in dispatch.FACTORIES.items():
            url = SimpleNamespace(Complete=factory)
            self.assertIs(router.queryDispatch(url, '_blank', 0), router)
            router.dispatch(url, ())
            self.assertEqual(events[-1], ('new', module))
        self.assertEqual(native.calls, [])

    def test_unknown_and_query_factories_never_reach_a_native_launcher(self):
        router, native, events = self.router()
        for name in ('private:factory/unknown', 'private:factory/scalc?Interactive',
                     'private:factory/scalc/../../unknown'):
            url = SimpleNamespace(Complete=name)
            self.assertIs(router.queryDispatch(url, '_blank', 0), router)
            router.dispatch(url, ())
        self.assertEqual(events, [])
        self.assertEqual(native.calls, [])
