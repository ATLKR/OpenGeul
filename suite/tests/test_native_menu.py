"""Real menu policy at public UNO boundaries; these are not Windows UI proof."""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

WORKER = Path(__file__).resolve().parents[1] / 'worker'
sys.path.insert(0, str(WORKER))
from session import WorkerError


OPEN = {'swriter': '.uno:OpenFromWriter', 'scalc': '.uno:OpenFromCalc',
        'simpress': '.uno:Open', 'sdraw': '.uno:Open',
        'smath': '.uno:Open', 'sdatabase': '.uno:Open'}


class Menu:
    def __init__(self, commands, *, popup=False):
        self.commands = list(commands)
        self.popup = popup
        self.enabled = True
        self.popups = {}

    def isPopupMenu(self): return self.popup
    def getItemCount(self): return len(self.commands)
    def getItemId(self, index): return index + 1
    def getCommand(self, item): return self.commands[item - 1]
    def isItemEnabled(self, item): return self.enabled
    def getPopupMenu(self, item): return self.popups.get(item)


class Settings:
    def __init__(self, items): self.items = list(items)
    def getCount(self): return len(self.items)
    def getByIndex(self, index): return self.items[index]
    def insertByIndex(self, index, item):
        if len(item) == 2 and item[0] == '[]com.sun.star.beans.PropertyValue':
            item = item[1]  # Simulate marshaling an explicitly typed PyUNO Any.
        self.items.insert(index, item)


def descriptor(command, nested=None):
    props = [NS(Name='CommandURL', Value=command), NS(Name='Label', Value=command), NS(Name='Type', Value=0)]
    if nested is not None: props.append(NS(Name='ItemDescriptorContainer', Value=nested))
    return tuple(props)


class NativeMenuTests(unittest.TestCase):
    def fixture(self, module='swriter', *, peer=None, frame=None, document=None):
        self.assertTrue((WORKER / 'native_menu.py').is_file(),
                        'Owned native menu preparation and passive readiness are missing')
        module_api = importlib.import_module('native_menu')
        from dispatch import DispatchRouter
        calls = []
        peer = object() if peer is None else peer
        frame = NS() if frame is None else frame
        document = NS() if document is None else document
        controller = NS()
        router = DispatchRouter(lambda *a: self.fail('Readiness must never dispatch a document action'))
        file_menu = Menu(('.uno:AddDirect', OPEN[module], '.uno:Save', '.uno:SaveAs', '.uno:CloseDoc', '.uno:Quit'), popup=True)
        bar = Menu(('.uno:PickList', '.uno:EditMenu', '.uno:FormatMenu'))
        bar.popups[1] = file_menu
        element = NS(Frame=frame, ResourceURL='private:resource/menubar/menubar', Type=1,
                     getRealInterface=lambda: bar)
        nested = Settings(descriptor(command) for command in file_menu.commands)
        settings = Settings([descriptor('.uno:PickList', nested), descriptor('.uno:EditMenu'), descriptor('.uno:FormatMenu')])
        element.getSettings = lambda writable: settings
        element.persistent = True
        element.getPropertyValue = lambda name: element.persistent
        def property_value(name, value):
            calls.append(('element-property', name, value)); element.persistent = value
        element.setPropertyValue = property_value
        def set_settings(value):
            calls.append(('settings', value))
            file_menu.commands = [next((p.Value for p in row if p.Name == 'CommandURL'), '') for row in nested.items]
        element.setSettings = set_settings
        layout = NS(visible=True, shown=True, element=element)
        def show(name):
            calls.append(('show', name)); return layout.shown
        layout.showElement = show
        layout.isElementVisible = lambda name: layout.visible
        layout.getElement = lambda name: layout.element
        frame.getContainerWindow = lambda: peer
        frame.getController = lambda: controller
        frame.getPropertyValue = lambda name: layout if name == 'LayoutManager' else None
        def query(url, target, flags):
            calls.append(('query', url.Complete, url.Protocol, url.Path, target, flags))
            return router.queryDispatch(url, target, flags)
        frame.queryDispatch = query
        controller.getFrame = lambda: frame
        controller.getModel = lambda: document
        document.getCurrentController = lambda: controller
        backend = NS(frame=frame, peer=peer, document=document, interceptor=router,
                     module_factory='private:factory/' + module,
                     uno=NS(createUnoStruct=lambda name: NS(), Any=lambda name, value: value))
        guard = module_api.NativeMenuSurface(backend)
        return NS(guard=guard, backend=backend, frame=frame, peer=peer, document=document,
                  controller=controller, layout=layout, element=element, bar=bar,
                  popup=file_menu, calls=calls, settings=settings, nested=nested)

    def test_each_real_module_file_command_set_prepares_without_dispatching(self):
        for module in OPEN:
            with self.subTest(module=module):
                f = self.fixture(module)
                self.assertIs(f.guard.prepare(f.backend), True)
                self.assertIs(f.guard.ready(f.backend), True)
                self.assertEqual([c for c in f.calls if c[0] == 'show'],
                                 [('show', 'private:resource/menubar/menubar')])

    def assertUnavailable(self, call):
        with self.assertRaises(WorkerError) as caught: call()
        self.assertEqual('native_menu_unavailable', caught.exception.code)
        return caught.exception

    def test_passive_loss_is_fatal_and_never_repeats_show_or_rebinds(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        f.layout.visible = False
        failure = self.assertUnavailable(lambda: f.guard.ready(f.backend))
        f.layout.visible = True
        self.assertIs(failure, self.assertUnavailable(lambda: f.guard.ready(f.backend)))
        self.assertIs(failure, self.assertUnavailable(lambda: f.guard.prepare(f.backend)))
        self.assertEqual(sum(c[0] == 'show' for c in f.calls), 1)
        self.assertEqual(sum(c[0] == 'settings' for c in f.calls), 1)

    def test_failed_preparation_is_explicit_and_preserves_boundary_cause(self):
        for outcome in (False, None, 1):
            with self.subTest(outcome=outcome):
                f = self.fixture(); f.layout.shown = outcome
                failure = self.assertUnavailable(lambda: f.guard.prepare(f.backend))
                self.assertIs(failure, self.assertUnavailable(lambda: f.guard.ready(f.backend)))
                self.assertIs(failure, self.assertUnavailable(lambda: f.guard.prepare(f.backend)))
                self.assertEqual(sum(c[0] == 'show' for c in f.calls), 1)
        f = self.fixture(); primary = RuntimeError('native boundary failed')
        f.layout.showElement = lambda name: (_ for _ in ()).throw(primary)
        failure = self.assertUnavailable(lambda: f.guard.prepare(f.backend))
        self.assertIs(primary, failure.__cause__)

    def test_product_commands_use_transient_settings_and_keep_native_items(self):
        f = self.fixture(); original = list(f.nested.items)
        self.assertTrue(f.guard.prepare(f.backend))
        self.assertFalse(f.element.persistent)
        self.assertEqual(original, f.nested.items[2:])
        self.assertEqual(['vnd.opengeul.office:new-hwp', '.uno:StartModule'], f.popup.commands[:2])
        self.assertEqual(['새 HWP 문서', 'OpenGeul 시작 화면'],
                         [next(p.Value for p in row if p.Name == 'Label') for row in f.nested.items[:2]])
        self.assertLess(next(i for i,c in enumerate(f.calls) if c[0]=='element-property'),
                        next(i for i,c in enumerate(f.calls) if c[0]=='settings'))

    def test_duplicate_product_command_or_nontransient_settings_fail(self):
        for change in ('duplicate-home', 'duplicate-hwp', 'persistent'):
            with self.subTest(change=change):
                f = self.fixture()
                if change == 'persistent': f.element.setPropertyValue = lambda *args: None
                else: f.nested.items.append(descriptor('.uno:StartModule' if change=='duplicate-home' else 'vnd.opengeul.office:new-hwp'))
                self.assertUnavailable(lambda: f.guard.prepare(f.backend))

    def test_foreign_backend_bindings_fail_before_querying_a_new_owner(self):
        for name in ('frame', 'peer', 'document', 'interceptor', 'module_factory'):
            with self.subTest(field=name):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); f.calls.clear()
                setattr(f.backend, name, object())
                self.assertUnavailable(lambda: f.guard.ready(f.backend))
                self.assertEqual(f.calls, [])

    def test_foreign_frame_controller_and_resource_do_not_claim_readiness(self):
        for change in ('container', 'controller-frame', 'controller-model', 'current-controller',
                       'resource-frame', 'resource-url', 'resource-type'):
            with self.subTest(change=change):
                f = self.fixture()
                if change == 'container': f.frame.getContainerWindow = lambda: object()
                elif change == 'controller-frame': f.controller.getFrame = lambda: object()
                elif change == 'controller-model': f.controller.getModel = lambda: object()
                elif change == 'current-controller': f.document.getCurrentController = lambda: object()
                elif change == 'resource-frame': f.element.Frame = object()
                elif change == 'resource-url': f.element.ResourceURL = 'private:resource/menubar/foreign'
                else: f.element.Type = 3
                self.assertUnavailable(lambda: f.guard.prepare(f.backend))

    def test_missing_file_popup_or_core_command_is_not_ready(self):
        for change in ('missing-file', 'duplicate-file', 'no-popup', 'not-popup', 'disabled-file',
                       '.uno:AddDirect', '.uno:OpenFromWriter', '.uno:Save', '.uno:SaveAs', '.uno:CloseDoc', '.uno:Quit'):
            with self.subTest(change=change):
                f = self.fixture()
                if change == 'missing-file': f.bar.commands[0] = '.uno:Other'
                elif change == 'duplicate-file': f.bar.commands[1] = '.uno:PickList'
                elif change == 'no-popup': f.bar.popups.clear()
                elif change == 'not-popup': f.popup.popup = False
                elif change == 'disabled-file': f.bar.enabled = False
                else: f.popup.commands.remove(change)
                self.assertUnavailable(lambda: f.guard.prepare(f.backend))

    def test_missing_frame_dispatch_and_nonowned_interceptor_are_not_ready(self):
        f = self.fixture(); f.frame.queryDispatch = lambda *a: None
        self.assertUnavailable(lambda: f.guard.prepare(f.backend))
        f = self.fixture(); f.backend.interceptor = object()
        self.assertUnavailable(lambda: f.guard.prepare(f.backend))

    def test_foreign_callable_frame_dispatch_cannot_claim_owned_menu_commands(self):
        f = self.fixture()
        f.frame.queryDispatch = lambda *args: NS(dispatch=lambda *args: None)
        self.assertUnavailable(lambda: f.guard.prepare(f.backend))

    def test_frame_dispatch_accepts_equivalent_uno_identity_without_requiring_python_is(self):
        f = self.fixture()
        class Adapter:
            def __eq__(self, other): return other is f.backend.interceptor
            def dispatch(self, *args): self.fail('A readiness check cannot dispatch')
        f.frame.queryDispatch = lambda *args: Adapter()
        self.assertTrue(f.guard.prepare(f.backend))

    def test_invalid_or_unbounded_menu_shapes_fail_closed(self):
        for count in (True, -1, 0, 100_000, '3'):
            with self.subTest(count=count):
                f = self.fixture(); f.bar.getItemCount = lambda: count
                self.assertUnavailable(lambda: f.guard.prepare(f.backend))
        f = self.fixture(); f.popup.getItemCount = lambda: 100_000
        self.assertUnavailable(lambda: f.guard.prepare(f.backend))

    def test_status_requires_menu_but_close_keeps_dirty_document_state(self):
        import native
        backend = native.UnoBackend(Path('/unused'))
        backend.document = NS(isModified=lambda: True, getTitle=lambda: 'Document')
        self.assertUnavailable(backend.status)
        self.assertEqual({'modified': True, 'title': 'Document'}, backend.document_status())
        self.assertEqual({'modified': True, 'title': 'Document'}, backend.prepare_close())

    def test_menu_loss_preserves_native_save_and_close_document_verdicts(self):
        import native
        f = self.fixture()
        dirty = [True]
        f.document.isModified = lambda: dirty[0]
        f.document.getTitle = lambda: 'Document'
        f.document.store = lambda: dirty.__setitem__(0, False)
        backend = native.UnoBackend(Path('/unused'))
        for name in ('frame', 'peer', 'document', 'interceptor', 'module_factory', 'uno'):
            setattr(backend, name, getattr(f.backend, name))
        backend.native_menu = f.guard
        self.assertTrue(f.guard.prepare(backend))
        self.assertTrue(backend.status()['nativeMenuReady'])
        f.layout.visible = False
        failure = self.assertUnavailable(backend.status)
        self.assertEqual({'modified': True, 'title': 'Document'}, backend.prepare_close())
        backend.save(None, None)
        self.assertEqual({'modified': False, 'title': 'Document'}, backend.document_status())
        self.assertEqual({'modified': False, 'title': 'Document'}, backend.prepare_close())
        self.assertIs(failure, self.assertUnavailable(backend.status))

    def test_menu_loss_does_not_clear_dirty_state_after_native_save_failure(self):
        import native
        backend = native.UnoBackend(Path('/unused'))
        primary = OSError('Synthetic storage failure')
        backend.document = NS(isModified=lambda: True, getTitle=lambda: 'Document',
                              store=lambda: (_ for _ in ()).throw(primary))
        self.assertUnavailable(backend.status)
        with self.assertRaises(OSError) as caught:
            backend.save(None, None)
        self.assertIs(primary, caught.exception)
        self.assertTrue(backend.prepare_close()['modified'])
