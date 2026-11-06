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


class DisposedException(RuntimeError):
    """Canonical exception double returned by the public UNO class lookup."""


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


def menu_element(frame, bar):
    # Pinned MenuBarWrapper.getRealInterface returns MenuBarManager, which
    # implements XSystemDependentMenuPeer, not the XMenu interface.
    # Metadata are IDL attributes, not callable generated C++ accessors. The
    # Type property descriptor says OUString, but its getter returns raw Int16.
    element = NS(Frame=frame, ResourceURL='private:resource/menubar/menubar', Type=1,
                 menu=lambda: bar, getRealInterface=lambda: NS(getMenuHandle=lambda *args: 0))
    def read_property(name):
        assert name in ('Frame', 'ResourceURL', 'Type', 'XMenuBar'), 'Only read-only native element properties may be observed'
        return element.menu() if name == 'XMenuBar' else getattr(element, name)
    element.getPropertyValue = read_property
    return element


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
        file_menu = Menu(('vnd.opengeul.office:new-hwp', '.uno:StartModule', '.uno:AddDirect', OPEN[module],
                          '.uno:Save', '.uno:SaveAs', '.uno:CloseDoc', '.uno:Quit'), popup=True)
        bar = Menu(('.uno:PickList', '.uno:EditMenu', '.uno:FormatMenu'))
        bar.popups[1] = file_menu
        element = menu_element(frame, bar)
        def configuration_write(*args):
            calls.append(('settings',))
            self.fail('A native menu observer must not read/write configuration or transient settings')
        element.getSettings = element.setSettings = configuration_write
        element.setPropertyValue = configuration_write
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
                     uno=NS(createUnoStruct=lambda name: NS(),
                            getClass=lambda name: DisposedException if name == 'com.sun.star.lang.DisposedException' else None))
        guard = module_api.NativeMenuSurface(backend)
        return NS(guard=guard, backend=backend, frame=frame, peer=peer, document=document,
                  controller=controller, layout=layout, element=element, bar=bar,
                  popup=file_menu, calls=calls)

    def test_each_real_module_file_command_set_prepares_without_dispatching(self):
        for module in OPEN:
            with self.subTest(module=module):
                f = self.fixture(module)
                self.assertIs(f.guard.prepare(f.backend), True)
                self.assertIs(f.guard.ready(f.backend), True)
                self.assertEqual([c for c in f.calls if c[0] == 'show'],
                                 [('show', 'private:resource/menubar/menubar')])

    def test_pinned_readonly_xmenubar_property_is_distinct_from_the_real_manager(self):
        f = self.fixture()
        manager = f.element.getRealInterface()
        self.assertTrue(callable(manager.getMenuHandle))
        self.assertFalse(hasattr(manager, 'isPopupMenu'))
        self.assertIs(f.bar, f.element.getPropertyValue('XMenuBar'))
        try:
            ready = f.guard.prepare(f.backend)
        except WorkerError as error:
            self.fail('Native readiness must read the XMenuBar property instead of '
                      'calling XMenu methods on its manager: ' + type(error.__cause__).__name__)
        self.assertIs(ready, True)
        self.assertEqual(f.popup.commands[:2], ['vnd.opengeul.office:new-hwp', '.uno:StartModule'])
        self.assertFalse(any(row[0] == 'settings' for row in f.calls))

    def test_idl_attribute_metadata_uses_property_values_without_cpp_only_methods(self):
        f = self.fixture()
        try:
            ready = f.guard.prepare(f.backend)
        except WorkerError as error:
            self.fail('Native readiness must read raw XPropertySet values for IDL '
                      'attributes instead of calling generated C++ getters: ' + type(error.__cause__).__name__)
        self.assertIs(ready, True)

    def test_native_menu_failure_records_one_closed_checkpoint_and_preserves_cause(self):
        f = self.fixture(); phases = []
        primary = RuntimeError('Synthetic document text and private path must not enter numeric phases')
        def fail_menu(): raise primary
        f.element.menu = fail_menu
        f.backend._diagnose = phases.append
        error = self.assertUnavailable(lambda: f.guard.prepare(f.backend))
        self.assertIs(error.__cause__, primary)
        self.assertEqual(phases, ['native-menu-check-06'])
        self.assertIs(error, self.assertUnavailable(lambda: f.guard.ready(f.backend)))
        self.assertIs(error, self.assertUnavailable(lambda: f.guard.prepare(f.backend)))
        self.assertEqual(phases, ['native-menu-check-06'])

    def test_checkpoint_diagnostic_failure_cannot_replace_the_original_menu_error(self):
        f = self.fixture(); phases = []
        primary = ValueError('Synthetic menu provider failure')
        def fail_menu(): raise primary
        def fail_diagnostic(phase):
            phases.append(phase)
            raise OSError('Synthetic optional recorder failure')
        f.element.menu = fail_menu
        f.backend._diagnose = fail_diagnostic
        error = self.assertUnavailable(lambda: f.guard.prepare(f.backend))
        self.assertIs(error.__cause__, primary)
        self.assertEqual(phases, ['native-menu-check-06'])

    def test_required_native_checks_emit_only_their_fixed_numeric_phase(self):
        for boundary, expected in (
                ('anchors', '01'), ('controller', '02'), ('disconnected', '02'), ('show', '03'),
                ('visibility', '04'), ('element', '05'), ('menu', '06'),
                ('menubar', '07'), ('popup', '08'), ('commands', '09'),
                ('own-dispatch', '10'), ('frame-dispatch', '11')):
            with self.subTest(boundary=boundary):
                f = self.fixture(); phases = []; f.backend._diagnose = phases.append
                if boundary == 'anchors': f.frame.getContainerWindow = lambda: object()
                elif boundary == 'controller': f.controller.getModel = lambda: object()
                elif boundary == 'disconnected': f.controller.getFrame = lambda: None
                elif boundary == 'show': f.layout.shown = False
                elif boundary == 'visibility': f.layout.visible = False
                elif boundary == 'element': f.element.Type = 3
                elif boundary == 'menu': f.element.menu = lambda: None
                elif boundary == 'menubar': f.bar.popup = True
                elif boundary == 'popup': f.bar.popups.clear()
                elif boundary == 'commands': f.popup.commands.pop(0)
                elif boundary == 'own-dispatch': f.backend.interceptor.queryDispatch = lambda *args: None
                else: f.frame.queryDispatch = lambda *args: NS(dispatch=lambda *args: None)
                self.assertUnavailable(lambda: f.guard.prepare(f.backend))
                self.assertEqual(phases, ['native-menu-check-' + expected])

    def assertUnavailable(self, call):
        with self.assertRaises(WorkerError) as caught: call()
        self.assertEqual('native_menu_unavailable', caught.exception.code)
        return caught.exception

    def replacement_view(self, f):
        controller = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
        bar = Menu(list(f.bar.commands))
        bar.popups[1] = Menu(list(f.popup.commands), popup=True)
        element = menu_element(f.frame, bar)
        return controller, element

    def replace_view(self, f, view):
        controller, element = view
        f.frame.getController = f.document.getCurrentController = lambda: controller
        f.layout.element = element

    def test_menu_wrapper_replacement_after_owner_sample_is_reobserved_once(self):
        for outcome in ('null', 'disposed'):
            with self.subTest(outcome=outcome):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); f.calls.clear()
                replacement = self.replacement_view(f); reads = []
                def old_menu():
                    reads.append('old'); self.replace_view(f, replacement)
                    if outcome == 'disposed': raise DisposedException('Synthetic old menu disposed')
                    return None
                f.element.menu = old_menu
                self.assertTrue(f.guard.ready(f.backend))
                self.assertEqual(reads, ['old'])
                self.assertEqual(sum(row[0] == 'query' for row in f.calls), 8)
                self.assertFalse(any(row[0] in ('show', 'settings') for row in f.calls))
                self.assertIsNone(f.guard.failure)

    def test_stable_unavailable_wrapper_is_not_retried(self):
        for outcome in ('null', 'disposed'):
            with self.subTest(outcome=outcome):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); reads = []
                primary = DisposedException('Synthetic stable menu disposed')
                def old_menu():
                    reads.append('old')
                    if outcome == 'disposed': raise primary
                    return None
                f.element.menu = old_menu
                error = self.assertUnavailable(lambda: f.guard.ready(f.backend))
                self.assertEqual(reads, ['old'])
                if outcome == 'disposed': self.assertIs(error.__cause__, primary)

    def test_unknown_transport_error_is_fatal_even_when_the_view_changes(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); reads = []
        replacement = self.replacement_view(f); primary = RuntimeError('Synthetic unknown transport error')
        def old_menu():
            reads.append('old'); self.replace_view(f, replacement); raise primary
        f.element.menu = old_menu
        error = self.assertUnavailable(lambda: f.guard.ready(f.backend))
        self.assertIs(error.__cause__, primary)
        self.assertEqual(reads, ['old'])

    def test_replaced_menu_epoch_cannot_hide_foreign_owners_resource_or_dispatch(self):
        for changed in ('anchor', 'controller', 'resource', 'type', 'dispatch'):
            with self.subTest(changed=changed):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
                replacement = self.replacement_view(f)
                def old_menu():
                    self.replace_view(f, replacement)
                    if changed == 'anchor': f.backend.interceptor = object()
                    elif changed == 'controller': replacement[0].getModel = lambda: object()
                    elif changed == 'resource': replacement[1].Frame = object()
                    elif changed == 'type': replacement[1].Type = 3
                    else: f.frame.queryDispatch = lambda *args: NS(dispatch=lambda *args: None)
                    return None
                f.element.menu = old_menu
                self.assertUnavailable(lambda: f.guard.ready(f.backend))

    def test_second_menu_epoch_change_is_fatal_without_a_third_whole_read(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); reads = []
        second, third = self.replacement_view(f), self.replacement_view(f)
        def old_menu():
            reads.append('first'); self.replace_view(f, second); return None
        def second_menu():
            reads.append('second'); self.replace_view(f, third); return None
        f.element.menu = old_menu
        second[1].menu = second_menu
        third[1].menu = lambda: self.fail('A third whole menu read must never occur')
        self.assertUnavailable(lambda: f.guard.ready(f.backend))
        self.assertEqual(reads, ['first', 'second'])

    def test_change_between_candidate_epoch_and_second_read_is_fatal(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); reads = []
        second, third = self.replacement_view(f), self.replacement_view(f)
        def old_menu():
            self.replace_view(f, second); return None
        def element(name):
            reads.append('element')
            if len(reads) == 2:
                self.replace_view(f, third)
                return second[1]
            return f.layout.element
        f.element.menu = old_menu
        f.layout.getElement = element
        third[1].menu = lambda: self.fail('A candidate epoch cannot be silently replaced')
        self.assertUnavailable(lambda: f.guard.ready(f.backend))
        self.assertEqual(len(reads), 2)

    def test_second_observation_end_resource_lookup_cannot_hide_a_third_epoch(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); reads = []
        second, third = self.replacement_view(f), self.replacement_view(f)
        def old_menu():
            self.replace_view(f, second); return None
        def element(name):
            reads.append('element')
            if len(reads) == 4:
                self.replace_view(f, third)
                return second[1]
            return f.layout.element
        f.element.menu = old_menu
        f.layout.getElement = element
        third[1].menu = lambda: self.fail('A third whole menu observation must never occur')
        self.assertUnavailable(lambda: f.guard.ready(f.backend))
        self.assertEqual(len(reads), 4)

    def test_completed_menu_read_with_changed_end_epoch_is_reobserved_once(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); f.calls.clear()
        replacement = self.replacement_view(f); changed = []
        original_query = f.frame.queryDispatch
        def query(url, *args):
            result = original_query(url, *args)
            if url.Complete == '.uno:Quit' and not changed:
                changed.append(True); self.replace_view(f, replacement)
            return result
        f.frame.queryDispatch = query
        self.assertTrue(f.guard.ready(f.backend))
        self.assertEqual(sum(row[0] == 'query' for row in f.calls), 16)
        self.assertFalse(any(row[0] in ('show', 'settings') for row in f.calls))

    def test_disposal_class_name_without_the_canonical_uno_type_is_not_recoverable(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        replacement = self.replacement_view(f)
        primary = type('DisposedException', (RuntimeError,), {})('Synthetic impostor exception')
        def old_menu():
            self.replace_view(f, replacement); raise primary
        f.element.menu = old_menu
        error = self.assertUnavailable(lambda: f.guard.ready(f.backend))
        self.assertIs(error.__cause__, primary)

    def test_disposal_of_fixed_frame_or_actual_dispatch_is_not_retried(self):
        for stage in ('manager', 'dispatch'):
            with self.subTest(stage=stage):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend)); reads = []
                replacement = self.replacement_view(f); primary = DisposedException('Synthetic fixed owner failure')
                def failure(*args):
                    reads.append(stage); self.replace_view(f, replacement); raise primary
                if stage == 'manager': f.frame.getPropertyValue = failure
                else: f.frame.queryDispatch = failure
                error = self.assertUnavailable(lambda: f.guard.ready(f.backend))
                self.assertIs(error.__cause__, primary)
                self.assertEqual(reads, [stage])

    def test_passive_loss_is_fatal_and_never_repeats_show_or_rebinds(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        original = f.layout.element
        f.layout.element = None
        failure = self.assertUnavailable(lambda: f.guard.ready(f.backend))
        f.layout.element = original
        self.assertIs(failure, self.assertUnavailable(lambda: f.guard.ready(f.backend)))
        self.assertIs(failure, self.assertUnavailable(lambda: f.guard.prepare(f.backend)))
        self.assertEqual(sum(c[0] == 'show' for c in f.calls), 1)
        self.assertEqual(sum(c[0] == 'settings' for c in f.calls), 0)

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

    def test_product_commands_are_prebranded_and_no_configuration_is_read_or_written(self):
        f = self.fixture(); original = list(f.popup.commands)
        self.assertTrue(f.guard.prepare(f.backend))
        self.assertTrue(f.guard.ready(f.backend))
        self.assertEqual(original, f.popup.commands)
        self.assertEqual(['vnd.opengeul.office:new-hwp', '.uno:StartModule'], f.popup.commands[:2])
        self.assertFalse(any(row[0] == 'settings' for row in f.calls))

    def test_each_required_file_command_must_be_unique(self):
        for command in ('vnd.opengeul.office:new-hwp', '.uno:StartModule', '.uno:AddDirect',
                        '.uno:OpenFromWriter', '.uno:Save', '.uno:SaveAs', '.uno:CloseDoc', '.uno:Quit'):
            with self.subTest(command=command):
                f = self.fixture(); f.popup.commands.append(command)
                self.assertUnavailable(lambda: f.guard.prepare(f.backend))

    def test_unbranded_initial_menu_is_not_repaired_by_the_observer(self):
        f = self.fixture()
        f.popup.commands = [command for command in f.popup.commands
                            if command not in ('vnd.opengeul.office:new-hwp', '.uno:StartModule')]
        self.assertUnavailable(lambda: f.guard.prepare(f.backend))
        self.assertFalse(any(row[0] == 'settings' for row in f.calls))

    def test_recreated_view_menu_inherits_branded_commands_without_poll_mutation(self):
        for module in OPEN:
            with self.subTest(module=module):
                f = self.fixture(module); self.assertTrue(f.guard.prepare(f.backend))
                replacement = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
                f.frame.getController = f.document.getCurrentController = lambda: replacement
                bar = Menu(list(f.bar.commands))
                bar.popups[1] = Menu(list(f.popup.commands), popup=True)
                f.layout.element = menu_element(f.frame, bar)
                self.assertTrue(f.guard.ready(f.backend))
                self.assertEqual(sum(row[0] == 'show' for row in f.calls), 1)
                self.assertFalse(any(row[0] == 'settings' for row in f.calls))

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

    def test_owned_preview_controller_replacement_and_return_keep_the_same_menu(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        for _ in range(2):
            controller = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
            f.frame.getController = f.document.getCurrentController = lambda: controller
            self.assertTrue(f.guard.ready(f.backend))
        self.assertIsNone(f.guard.failure)
        self.assertEqual(sum(row[0] == 'show' for row in f.calls), 1)
        self.assertEqual(sum(row[0] == 'settings' for row in f.calls), 0)

    def test_one_controller_transition_between_getters_can_be_reobserved(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        replacement = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
        samples = []
        def controller():
            value = f.controller if not samples else replacement
            samples.append(value)
            return value
        f.frame.getController = controller
        f.document.getCurrentController = lambda: replacement
        self.assertTrue(f.guard.ready(f.backend))
        self.assertLessEqual(len(samples), 6, 'Two whole menu observations must use a fixed finite owner read bound')
        self.assertIsNone(f.guard.failure)

    def test_disposed_old_controller_is_reobserved_only_after_the_frame_endpoint_changes(self):
        for detached in ('frame', 'model', 'both'):
            with self.subTest(detached=detached):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
                replacement = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
                samples = []
                def controller():
                    value = f.controller if not samples else replacement
                    samples.append(value)
                    return value
                f.frame.getController = controller
                f.document.getCurrentController = lambda: replacement
                if detached in ('frame', 'both'): f.controller.getFrame = lambda: None
                if detached in ('model', 'both'): f.controller.getModel = lambda: None
                self.assertTrue(f.guard.ready(f.backend))
                self.assertLessEqual(len(samples), 6)

    def test_a_stable_detached_controller_is_not_an_owned_connection(self):
        for part in ('frame', 'model'):
            with self.subTest(part=part):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
                setattr(f.controller, 'getFrame' if part == 'frame' else 'getModel', lambda: None)
                self.assertUnavailable(lambda: f.guard.ready(f.backend))

    def test_repeated_controller_churn_fails_with_a_finite_read_bound(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        samples = []
        def controller():
            value = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
            samples.append(value)
            return value
        f.frame.getController = controller
        f.document.getCurrentController = lambda: samples[-1]
        self.assertUnavailable(lambda: f.guard.ready(f.backend))
        self.assertLessEqual(len(samples), 6)

    def test_replacement_controller_cannot_move_to_a_foreign_frame_or_model(self):
        for part in ('frame', 'model'):
            with self.subTest(part=part):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
                replacement = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
                setattr(replacement, 'getFrame' if part == 'frame' else 'getModel', lambda: object())
                f.frame.getController = f.document.getCurrentController = lambda: replacement
                self.assertUnavailable(lambda: f.guard.ready(f.backend))

    def test_controller_motion_never_excuses_a_foreign_nonnull_owner(self):
        for part in ('frame', 'model'):
            with self.subTest(part=part):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
                replacement = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
                samples = []
                def controller():
                    value = f.controller if not samples else replacement
                    samples.append(value)
                    return value
                f.frame.getController = controller
                f.document.getCurrentController = lambda: replacement
                setattr(f.controller, 'getFrame' if part == 'frame' else 'getModel', lambda: object())
                self.assertUnavailable(lambda: f.guard.ready(f.backend))
                self.assertEqual(len(samples), 1)

    def test_controller_getter_exception_is_primary_and_is_not_retried(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        samples = []
        def controller():
            samples.append(f.controller)
            return f.controller
        f.frame.getController = controller
        primary = RuntimeError('Synthetic controller bridge failure')
        f.controller.getModel = lambda: (_ for _ in ()).throw(primary)
        error = self.assertUnavailable(lambda: f.guard.ready(f.backend))
        self.assertIs(error.__cause__, primary)
        self.assertEqual(len(samples), 1)

    def test_backend_anchor_change_inside_controller_sample_is_not_rebound(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        def current():
            f.backend.interceptor = object()
            return f.controller
        f.document.getCurrentController = current
        self.assertUnavailable(lambda: f.guard.ready(f.backend))

    def test_replacement_controller_does_not_hide_loss_of_product_menu_commands(self):
        for command in ('.uno:StartModule', 'vnd.opengeul.office:new-hwp'):
            with self.subTest(command=command):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
                replacement = NS(getFrame=lambda: f.frame, getModel=lambda: f.document)
                f.frame.getController = f.document.getCurrentController = lambda: replacement
                f.popup.commands.remove(command)
                self.assertUnavailable(lambda: f.guard.ready(f.backend))

    def test_fullscreen_and_user_visibility_toggles_leave_the_owned_menu_connected(self):
        f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
        for visible in (False, True, False, True):
            f.layout.visible = visible
            self.assertTrue(f.guard.ready(f.backend))
        self.assertIsNone(f.guard.failure)
        self.assertEqual(sum(row[0] == 'show' for row in f.calls), 1)
        self.assertEqual(sum(row[0] == 'settings' for row in f.calls), 0)

    def test_initial_connection_requires_actual_visible_menu(self):
        for visible in (False, None, 1):
            with self.subTest(visible=visible):
                f = self.fixture(); f.layout.visible = visible
                self.assertUnavailable(lambda: f.guard.prepare(f.backend))

    def test_hidden_menu_still_requires_real_resource_file_and_dispatch_ownership(self):
        for changed in ('element', 'resource', 'file-disabled', 'dispatch'):
            with self.subTest(changed=changed):
                f = self.fixture(); self.assertTrue(f.guard.prepare(f.backend))
                f.layout.visible = False
                if changed == 'element': f.layout.element = None
                elif changed == 'resource': f.element.Frame = object()
                elif changed == 'file-disabled': f.bar.enabled = False
                else: f.frame.queryDispatch = lambda *args: NS(dispatch=lambda *args: None)
                self.assertUnavailable(lambda: f.guard.ready(f.backend))

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
        f.layout.element = None
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
