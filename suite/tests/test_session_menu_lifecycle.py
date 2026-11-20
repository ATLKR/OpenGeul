"""Real session transactions remain usable after native menu integration fails."""
import copy
from pathlib import Path
import tempfile
import unittest

from test_worker import FakeBackend, MODULES
from session import DocumentSession, FACTORIES, WorkerError


class MenuBackend(FakeBackend):
    def __init__(self, runtime):
        super().__init__(runtime)
        self.menu_failed = False
        self.cleanup_released = True

    def set_command_handler(self, handler):
        self.on_command = handler

    def document_status(self):
        return super().status()

    def status(self):
        if self.menu_failed:
            raise WorkerError('native_menu_unavailable', 'Synthetic native menu unavailable')
        return dict(self.document_status(), nativeMenuReady=True)

    def prepare_close(self):
        return self.document_status()

    def cleanup(self):
        result = super().cleanup()
        result['resourcesReleased'] = self.cleanup_released
        return result


class SessionMenuLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.backend = MenuBackend(self.root)
        self.modules = copy.deepcopy(MODULES)
        self.modules['hwp'] = {'displayName': 'OpenGeul HWP', 'backend': 'external',
                               'extensions': ['hwp', 'hwpx']}
        self.session = DocumentSession(self.root, self.modules,
                                       backend_factory=lambda runtime: self.backend)

    def attach(self):
        return self.session.dispatch('attach', dict(module='writer', parentHwnd=123,
                                                    width=640, height=480))

    def test_exact_hwp_new_event_is_allowed_without_a_uno_hwp_factory(self):
        self.attach(); events = []; self.session.event_sink = events.append
        self.backend.on_command('new', 'hwp')
        self.backend.on_command('open', 'hwp')
        self.backend.on_command('save', 'hwp')
        self.backend.on_command('new', 'unknown')
        self.assertEqual(events, [dict(event='command', command='new', module='hwp')])
        self.assertNotIn('hwp', FACTORIES)
        fresh = DocumentSession(self.root, self.modules, backend_factory=lambda runtime: self.backend)
        with self.assertRaises(WorkerError) as error:
            fresh.dispatch('attach', dict(module='hwp', parentHwnd=1, width=1, height=1))
        self.assertEqual(error.exception.code, 'unsupported_module')

    def test_hwp_new_without_manifest_entry_is_not_forwarded(self):
        del self.modules['hwp']; self.attach()
        events = []; self.session.event_sink = events.append
        self.backend.on_command('new', 'hwp')
        self.assertEqual(events, [])

    def test_menu_loss_keeps_dirty_close_veto_and_successful_save_result(self):
        self.attach(); self.backend.modified = self.backend.menu_failed = True
        with self.assertRaises(WorkerError) as error:
            self.session.dispatch('status', {})
        self.assertEqual(error.exception.code, 'native_menu_unavailable')
        self.assertTrue(self.session.dispatch('prepare-close', {})['modified'])
        try: closed = self.session.dispatch('close', {})
        except WorkerError: self.fail('Menu loss blocked the original dirty-close veto')
        self.assertTrue(closed['closeCancelled'])
        self.assertNotIn(('cleanup',), self.backend.calls)
        target = self.root / 'retained-document.odt'
        try: saved = self.session.dispatch('save', {'path': str(target)})
        except WorkerError: self.fail('Menu loss masked a completed storage operation')
        self.assertFalse(saved['modified']); self.assertEqual(saved['path'], str(target))
        self.assertEqual([c[0] for c in self.backend.calls].count('save'), 1)
        self.assertTrue(self.session.dispatch('close', {})['closed'])
        self.assertEqual([c[0] for c in self.backend.calls].count('cleanup'), 1)

    def test_menu_loss_does_not_turn_failed_storage_into_discard(self):
        self.attach(); self.backend.modified = self.backend.menu_failed = self.backend.fail_save = True
        with self.assertRaises(WorkerError) as error:
            self.session.dispatch('save', {'path': str(self.root / 'failed.odt')})
        self.assertEqual(error.exception.code, 'save_failed')
        self.assertTrue(self.backend.modified); self.assertIsNone(self.session.path)
        try: closed = self.session.dispatch('close', {})
        except WorkerError: self.fail('Menu loss blocked close protection after failed storage')
        self.assertTrue(closed['closeCancelled'])
        self.assertNotIn(('cleanup',), self.backend.calls)

    def test_final_attach_status_failure_releases_only_the_failed_owner(self):
        self.backend.menu_failed = True
        with self.assertRaises(WorkerError) as error: self.attach()
        self.assertEqual(error.exception.code, 'native_menu_unavailable')
        self.assertEqual([c[0] for c in self.backend.calls].count('cleanup'), 1)
        self.assertIsNone(self.session.backend)
        self.assertEqual(self.session.state, 'idle')

    def test_unconfirmed_failed_attach_retains_owner_and_rejects_replacement(self):
        self.backend.menu_failed = True; self.backend.cleanup_released = False
        with self.assertRaises(WorkerError): self.attach()
        self.assertIs(self.session.backend, self.backend)
        self.assertEqual(self.session.state, 'closed')
        with self.assertRaises(WorkerError) as error: self.attach()
        self.assertEqual(error.exception.code, 'cleanup_pending')
        self.assertEqual([c[0] for c in self.backend.calls].count('attach'), 1)
