"""Numeric-only original-focus diagnostics through the real native cleanup path."""
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
import native_accessibility as native


class NativeOriginalFocusTypeTests(unittest.TestCase):
    def run_native(self, *, widget_type='SwEditWinUIObject', type_failure=False,
                   change_focus=False, focus_query_failure=False, cleanup_failure=False,
                   restore_failure=False, selection_changed=False, invalid_role=False):
        events, registered = [], []
        state = NS(current=None, type_attempted=False)

        class Widget:
            def equals(self, other):
                return self is other

            def getType(self):
                if self is not original:
                    return 'TabControlUIObject'
                events.append('type-query')
                self_test.assertFalse(registered, 'Optional query ran before listener cleanup')
                self_test.assertIn('restore', events)
                self_test.assertIn('selection-check', events)
                state.type_attempted = True
                if change_focus:
                    state.current = target
                if type_failure:
                    raise RuntimeError('synthetic type-query detail must stay private')
                return widget_type

            def getState(self):
                if self is original:
                    raise AssertionError('Original widget state may contain document text')
                restored = 'restore' in events
                if restored:
                    events.append('selection-check')
                return [NS(Name=name, Value=value) for name, value in dict(
                    ID='ContextContainer', Visible='true', ReallyVisible='true',
                    CurrPagePos='2' if selection_changed and restored else '1').items()]

            def executeAction(self, action, parameters):
                self_test.assertEqual((action, parameters), ('FOCUS', ()))
                if self is original:
                    events.append('restore')
                    if not restore_failure:
                        state.current = original
                    return
                events.append('target-focus')
                state.current = target
                for window, listener in registered:
                    listener.focusLost(NS(NextFocus=target_peer))

        class Window:
            def addFocusListener(self, listener):
                registered.append((self, listener))

            def removeFocusListener(self, listener):
                events.append('remove-listener')
                registered.remove((self, listener))
                if cleanup_failure and self is peer:
                    raise RuntimeError('synthetic listener cleanup failed')

            def getWindows(self):
                return ()

            def setFocus(self):
                events.append('component-focus')
                state.current = component_widget

        self_test = self
        original, target, owner = Widget(), Widget(), Widget()
        component_widget = Widget()
        peer, component, toolkit, target_peer = Window(), Window(), Window(), Window()
        state.current = original
        owner.getChild = lambda identifier: target if identifier == 'ContextContainer' else None
        root_context = NS(getAccessibleParent=lambda: None,
                          getAccessibleChild=lambda index: accessible if index == 0 else None)
        parent = NS(getAccessibleContext=lambda: root_context)
        accessible_context = NS(getAccessibleRole=lambda: 23 if invalid_role else 39,
            getAccessibleParent=lambda: parent, getAccessibleIndexInParent=lambda: 0)
        accessible = NS(getAccessibleContext=lambda: accessible_context)
        target_peer.getProperty = lambda name: accessible if name == 'XAccessible' else None

        def get_focus():
            if state.type_attempted:
                events.append('retained-focus-query')
                if focus_query_failure:
                    raise RuntimeError('synthetic retained-focus detail must stay private')
            return state.current

        ui = NS(getFocusWindow=get_focus, getWindow=lambda window:
            {id(peer): owner, id(component): component_widget, id(target_peer): target}[id(window)])
        context = NS(ServiceManager=NS(createInstanceWithContext=lambda service, context:
            ui if service == 'com.sun.star.ui.test.UITest' else toolkit))
        frame = NS(getContainerWindow=lambda: peer, getComponentWindow=lambda: component)
        modules = {'unohelper': ModuleType('unohelper'), 'com.sun.star.awt': ModuleType('com.sun.star.awt')}
        modules['unohelper'].Base = type('Base', (), {})
        modules['com.sun.star.awt'].XFocusListener = type('XFocusListener', (), {})
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules):
            destination = Path(directory) / 'focus-diagnostic.json'
            error = result = None
            try:
                result = native._native_notebookbar(context, frame, peer, destination)
            except AssertionError as exc:
                error = str(exc)
            data = json.loads(destination.read_text(encoding='utf-8'))
        self.assertFalse(registered, 'Listeners must be removed on every exercised path')
        self.assertEqual(events.count('component-focus'), 1)
        self.assertEqual(events.count('target-focus'), 1)
        self.assertEqual(events.count('restore'), 1, 'Optional diagnostics must not add focus actions')
        return data, result, error, events

    def diagnostic(self, data):
        self.assertIn('originalFocusType', data, 'Numeric original-focus diagnostic is missing')
        value = data['originalFocusType']
        self.assertEqual(set(value), {'attempted', 'completed', 'typeCode', 'errorCode',
                                     'retainedFocusEqualsOriginal'})
        for name in ('attempted', 'completed', 'retainedFocusEqualsOriginal'):
            self.assertIs(type(value[name]), bool)
        for name in ('typeCode', 'errorCode'):
            self.assertIs(type(value[name]), int)
        return value

    def test_writer_type_is_numeric_and_observed_after_original_cleanup(self):
        data, result, error, events = self.run_native()
        self.assertIsNone(error)
        self.assertTrue(result[3]['focusRestored'])
        self.assertEqual(self.diagnostic(data), dict(attempted=True, completed=True,
            typeCode=1, errorCode=0, retainedFocusEqualsOriginal=True))
        self.assertEqual(events[-2:], ['type-query', 'retained-focus-query'])
        self.assertNotIn('SwEditWinUIObject', json.dumps(data))

    def test_unknown_type_is_not_serialized_and_does_not_read_original_state(self):
        data, result, error, _ = self.run_native(widget_type='synthetic unlisted widget type')
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(self.diagnostic(data), dict(attempted=True, completed=True,
            typeCode=0, errorCode=0, retainedFocusEqualsOriginal=True))
        self.assertNotIn('synthetic unlisted widget type', json.dumps(data))

    def test_type_query_exception_does_not_replace_success_or_expose_details(self):
        data, result, error, _ = self.run_native(type_failure=True)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertFalse(data['cleanupErrors'])
        self.assertEqual(self.diagnostic(data), dict(attempted=True, completed=False,
            typeCode=0, errorCode=1, retainedFocusEqualsOriginal=True))
        self.assertNotIn('synthetic type-query detail', json.dumps(data))

    def test_changed_focus_after_query_is_reported_without_restoring_again(self):
        data, result, error, _ = self.run_native(change_focus=True)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(self.diagnostic(data), dict(attempted=True, completed=True,
            typeCode=1, errorCode=0, retainedFocusEqualsOriginal=False))

    def test_retained_focus_query_exception_is_optional_and_numeric(self):
        data, result, error, _ = self.run_native(focus_query_failure=True)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(self.diagnostic(data), dict(attempted=True, completed=False,
            typeCode=1, errorCode=3, retainedFocusEqualsOriginal=False))
        self.assertNotIn('synthetic retained-focus detail', json.dumps(data))

    def test_non_string_type_result_is_rejected_without_coercion(self):
        class NoStringConversion:
            def __str__(self):
                raise AssertionError('Unexpected type result must not be rendered')
            __repr__ = __str__
        data, result, error, _ = self.run_native(widget_type=NoStringConversion())
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        self.assertEqual(self.diagnostic(data), dict(attempted=True, completed=False,
            typeCode=0, errorCode=2, retainedFocusEqualsOriginal=True))

    def test_cleanup_or_restoration_failure_skips_optional_query(self):
        for failure in ('cleanup_failure', 'restore_failure', 'selection_changed'):
            with self.subTest(failure=failure):
                data, _, error, events = self.run_native(**{failure: True})
                self.assertIsNotNone(error)
                self.assertNotIn('type-query', events)
                self.assertEqual(self.diagnostic(data), dict(attempted=False, completed=False,
                    typeCode=0, errorCode=0, retainedFocusEqualsOriginal=False))

    def test_original_native_failure_remains_primary_when_type_query_fails(self):
        data, _, error, _ = self.run_native(invalid_role=True, type_failure=True)
        self.assertEqual(error, 'Actual focused notebookbar does not expose the native PAGE_TAB_LIST role')
        self.assertFalse(data['cleanupErrors'])
        self.assertEqual(self.diagnostic(data)['errorCode'], 1)


if __name__ == '__main__':
    unittest.main()
