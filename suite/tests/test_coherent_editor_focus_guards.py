"""One freshly guarded scope supplies strict focus; no second GUI query."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'e2e'))
import test_counted_editor_shortcuts as fixtures
import counted_editor_shortcuts as counted
import scenario_editor_shortcuts as scenarios
import ime_keyboard_session as ime


class CoherentEditorFocusGuardsTests(unittest.TestCase):
    families = ('reader-bound', 'first-admission', 'ime')

    def fixture(self, directory, family, deadline=6.):
        process, binding, api, clock, probe, record = fixtures.CountedEditorShortcutsTests().fixture(directory)
        if family == 'reader-bound':
            session = counted.CountedEditorShortcuts(api, process, binding, record, deadline, probe=probe, clock=clock)
            session._prepare()
        elif family == 'first-admission':
            attachment = dict(hwnd=11, parent=12, child=22, officePid=88)
            session = scenarios.FirstAdmissionEditorSession(api, process, attachment, 'WRITER_STYLE',
                record, deadline, probe=probe, clock=clock)
            session._prepare()
        else:
            session = ime.IMEKeyboardSession(api, process, 11, 12, 22, 88, 'writer', record,
                deadline, probe=probe, clock=clock)
            session.start()
        end = RuntimeError('Guard-only fixture has no input program to complete')
        self.addCleanup(lambda: session.close(end) if family == 'ime' else session._finish(end))
        second_queries = []
        def unjoined_query(*args):
            second_queries.append(args)
            raise AssertionError('Unjoined second GUI query observed a later capture')
        api.require_editor_focus = unjoined_query
        return session, api, clock, probe, second_queries

    def test_each_family_uses_the_exact_fresh_capture_free_guard_scope(self):
        for family in self.families:
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                session, api, clock, probe, second = self.fixture(directory, family)
                original = probe.scope_snapshot
                rows = []
                def observe(*args):
                    row = original(*args); rows.append(row); return row
                probe.scope_snapshot = observe
                result = session._guard()
                self.assertIs(result, session.receipt['lastGuardObservation'])
                self.assertIs(result['scope'], rows[0])
                self.assertEqual(len(rows), 1)
                self.assertEqual(result['scope']['focus']['hwnd'], 33)
                self.assertEqual(result['scope']['capture']['hwnd'], 0)
                self.assertEqual(second, [])
                self.assertEqual(probe.sent, [])

    def test_owned_capture_settles_with_all_fresh_guards_and_no_new_input(self):
        for family in self.families:
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                session, api, clock, probe, second = self.fixture(directory, family)
                original = probe.scope_snapshot
                rows = []
                def observe(*args):
                    row = original(*args); rows.append(row)
                    if len(rows) <= 2: row['capture'] = copy.deepcopy(row['before']['editor'])
                    return row
                probe.scope_snapshot = observe
                before = len(probe.calls)
                deadline = session.deadline
                with patch('time.sleep', side_effect=lambda seconds: setattr(clock, 'now', clock.now + seconds)):
                    result = session._guard()
                self.assertEqual(len(rows), 3)
                self.assertEqual(probe.calls[before:].count('shell'), 3)
                self.assertEqual(probe.calls[before:].count(('engine', 2**41)), 3)
                self.assertIs(result['scope'], rows[-1])
                self.assertEqual(session.receipt['captureReadiness']['pollCount'], 2)
                self.assertEqual(session.receipt['captureReadiness']['deadline'], deadline)
                self.assertEqual(session.deadline, deadline)
                self.assertEqual(second, [])
                self.assertEqual(probe.sent, [])

    def test_every_family_rejects_foreign_capture_or_changed_guard_during_settlement(self):
        for family in self.families:
            for change in ('foreign-capture', 'generation', 'focus', 'layout', 'neutral-keys'):
                with self.subTest(family=family, change=change), tempfile.TemporaryDirectory() as directory:
                    session, api, clock, probe, second = self.fixture(directory, family)
                    original = probe.scope_snapshot
                    rows = []
                    def observe(*args):
                        row = original(*args); rows.append(row)
                        row['capture'] = copy.deepcopy(row['before']['editor'])
                        if change == 'foreign-capture': row['capture']['pid'] = 999
                        return row
                    def pause(seconds):
                        clock.now += seconds
                        if change == 'generation': probe.engine['creationTime'] += 1
                        elif change == 'focus': probe.focus = 999
                        elif change == 'layout': probe.layout = 0x04120412
                        elif change == 'neutral-keys': probe.keys_down = [0x11]
                    probe.scope_snapshot = observe
                    with patch('time.sleep', side_effect=pause), self.assertRaises(AssertionError):
                        session._guard()
                    self.assertEqual(len(rows), 1 if change == 'foreign-capture' else 2)
                    self.assertIs(session.receipt['lastGuardObservation']['scope'], rows[-1])
                    self.assertEqual(second, [])
                    self.assertEqual(probe.sent, [])

    def test_each_family_expires_at_the_same_original_deadline_without_input(self):
        for family in self.families:
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory:
                session, api, clock, probe, second = self.fixture(directory, family, deadline=1.12)
                original = probe.scope_snapshot
                def observe(*args):
                    row = original(*args); row['capture'] = copy.deepcopy(row['before']['editor']); return row
                probe.scope_snapshot = observe
                with patch('time.sleep', side_effect=lambda seconds: setattr(clock, 'now', clock.now + seconds)):
                    with self.assertRaisesRegex(AssertionError, 'deadline'): session._guard()
                self.assertEqual(clock.now, 1.12)
                self.assertEqual(session.deadline, 1.12)
                self.assertEqual(session.receipt['captureReadiness']['deadline'], 1.12)
                self.assertEqual(second, [])
                self.assertEqual(probe.sent, [])


if __name__ == '__main__': unittest.main()
