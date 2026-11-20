"""Real pre-ASCII phase observes owned capture without replaying input."""
import copy
import tempfile
import unittest
from unittest.mock import patch
import test_scenario_editor_shortcuts as fixtures

class PreAsciiReadinessTests(unittest.TestCase):
    def ready(self, navigate=True):
        owner=fixtures.ScenarioEditorShortcutsTests();owner.setUp()
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        f=owner.fixture(temporary.name);session=owner.session(f,'GUI_WRITER',marker='UI-OpenGeul-writer')
        session.__enter__()
        def cleanup():
            error=session.failed_error or RuntimeError('test cleanup')
            session.__exit__(type(error),error,None)
        self.addCleanup(cleanup)
        owner.enter_ready(session,f)
        if navigate:session.press('CTRL_END')
        return session,f
    def capture(self,probe,mutate=None):
        original=probe.scope_snapshot
        def scope(*args):
            row=original(*args);row['capture']=copy.deepcopy(row['before']['editor'])
            if mutate:mutate(row['capture'])
            return row
        probe.scope_snapshot=scope
        return original
    def test_owned_capture_clears_under_same_budget_without_resending_navigation(self):
        s,f=self.ready();clock,probe=f[3:5];deadline=s.deadline;sent=list(probe.sent)
        original=self.capture(probe)
        def release(seconds):clock.now+=seconds;probe.scope_snapshot=original
        with patch('capture_readiness.time.sleep',side_effect=release):focus=s.pre_ascii_focus()
        self.assertEqual(focus,33);self.assertEqual(s.deadline,deadline);self.assertEqual(probe.sent,sent)
        self.assertEqual(s.receipt['preAsciiObservation']['scope']['capture']['hwnd'],0)
        self.assertEqual([row['shortcut'] for row in s.receipt['actions']],['CTRL_F6','CTRL_END'])
        with self.assertRaises(AssertionError):s.pre_ascii_focus()
    def test_phase_mismatch_cannot_enter_pre_ascii_observation(self):
        s,f=self.ready(navigate=False);sent=list(f[4].sent)
        with self.assertRaisesRegex(AssertionError,'program step'):s.pre_ascii_focus()
        self.assertEqual(f[4].sent,sent)
    def test_persistent_capture_and_oversleep_do_not_query_or_allow_input_after_expiry(self):
        for oversleep in (False,True):
            with self.subTest(oversleep=oversleep):
                s,f=self.ready();clock,probe=f[3:5];sent=list(probe.sent);self.capture(probe);queries=[]
                original=probe.scope_snapshot
                def scope(*args):queries.append(clock.now);return original(*args)
                probe.scope_snapshot=scope
                def pause(seconds):clock.now=s.deadline+1 if oversleep else clock.now+seconds
                input_calls=[]
                with patch('capture_readiness.time.sleep',side_effect=pause):
                    with self.assertRaises(AssertionError):
                        s.pre_ascii_focus();input_calls.append('ASCII')
                self.assertEqual(input_calls,[]);self.assertEqual(probe.sent,sent)
                self.assertTrue(all(t<s.deadline for t in queries))
                if oversleep:self.assertEqual(len(queries),1)
    def test_capture_identity_and_retained_process_generation_fail_closed(self):
        for kind in ('foreign','dead','thread','generation'):
            with self.subTest(kind=kind):
                s,f=self.ready();clock,probe=f[3:5];sent=list(probe.sent)
                changes={'foreign':lambda row:row.update(pid=99),'dead':lambda row:row.update(isWindow=False),
                         'thread':lambda row:row.update(threadId=45)}
                self.capture(probe,changes.get(kind))
                def pause(seconds):clock.now+=seconds;probe.engine['creationTime']+=1
                with patch('capture_readiness.time.sleep',side_effect=pause):
                    with self.assertRaises(AssertionError):s.pre_ascii_focus()
                self.assertEqual(probe.sent,sent)
