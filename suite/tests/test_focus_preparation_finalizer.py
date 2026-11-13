"""Final readiness uses its retained full native row, with no hidden requery."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parent))
import test_editor_focus_readiness as fixtures


class FocusPreparationFinalizerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.EditorFocusReadinessTests();self.fixture.setUp()

    def test_ready_row_is_final_authority_without_second_unretained_focus_query(self):
        api=self.fixture.api([0,0,34])
        api.require_editor_focus=lambda *args:self.fail('Second unretained GUI query attempted')
        api.pid=lambda *args:self.fail('Second unretained owner query attempted')
        self.assertEqual(self.fixture.prepare(api),34)
        evidence=self.fixture.record['editorFocusReadiness']
        self.assertEqual(len(api.user.queries),len(evidence['snapshots']))
        self.assertEqual(len(evidence['snapshots']),3)
        row=evidence['snapshots'][-1]
        self.assertEqual(row['focus']['pid'],200);self.assertEqual(row['focus']['threadId'],20)
        self.assertEqual(row['capture']['hwnd'],0)
        self.assertEqual([r['phase'] for r in evidence['snapshots']],
            ['before-click','after-click','after-control-f6'])
        self.assertIs(fixtures.native.require_editor_focus_readiness(evidence,11,33,100,200),evidence)

    def test_owner_identity_comes_from_same_full_row_without_later_pid_query(self):
        api=self.fixture.api([0,0,34]);api.require_editor_focus=lambda *args:34
        api.pid=lambda *args:self.fail('Unretained later PID query attempted')
        self.assertEqual(self.fixture.prepare(api),34)
        self.assertEqual(len(api.user.queries),3)

    def test_capture_settlement_retains_only_existing_wait_phases_and_single_inputs(self):
        api=self.fixture.api([0,34,34,34],captures=[0,33,33,0])
        api.require_editor_focus=lambda *args:self.fail('Capture settlement added an unretained query')
        api.pid=lambda *args:self.fail('Capture settlement added an unretained owner query')
        self.assertEqual(self.fixture.prepare(api),34)
        evidence=self.fixture.record['editorFocusReadiness']
        self.assertEqual([r['phase'] for r in evidence['snapshots']],
            ['before-click','after-click','after-control-f6','wait'])
        self.assertEqual(self.fixture.inputs,['click','CTRL+F6'])
        self.assertEqual(len(api.user.queries),4)
        self.assertEqual(evidence['snapshots'][-1]['capture']['hwnd'],0)

    def test_following_input_guard_can_reject_new_capture_without_rewriting_ready_history(self):
        api=self.fixture.api([34],captures=[0,0,0,33])
        self.assertEqual(self.fixture.prepare(api),34)
        evidence=self.fixture.record['editorFocusReadiness']
        self.assertTrue(evidence['ready']);self.assertEqual(len(api.user.queries),3)
        with self.assertRaisesRegex(AssertionError,'capture'):api.require_editor_focus(11,33)
        self.assertEqual(len(api.user.queries),4)
        self.assertEqual(evidence['snapshots'][-1]['capture']['hwnd'],0)


if __name__=='__main__':unittest.main()
