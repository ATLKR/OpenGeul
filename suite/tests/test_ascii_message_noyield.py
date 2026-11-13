"""Exact failed native rows and strict PM_NOYIELD/consumed-bit policy replay."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'e2e/ascii_message_progress.py'
FIXTURE=ROOT/'tests/fixtures/ascii-message-noyield-39549535760-x64.v1.json'


class AsciiMessageNoYieldTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('tested_ascii_noyield_policy',SOURCE)
        self.policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.policy)
        self.fixture=json.loads(FIXTURE.read_bytes())

    def captured(self,index=0):
        case=copy.deepcopy(self.fixture['cases'][index])
        return case,self.policy.CharacterProgress(case['intent'],case['target'],0)

    def resequence(self,rows):
        for index,row in enumerate(rows):row['sequence']=index+1
        return rows

    def replay_actual(self,index):
        case,state=self.captured(index);rows=case['observations'];before=copy.deepcopy(rows)
        self.assertEqual([1,1,2,3,1,1],[r['remove']for r in rows])
        self.assertEqual(4,case['requestedInputs']);self.assertEqual(4,case['insertedInputs'])
        proof=state.observe(rows)
        self.assertTrue(proof['queueConsumed']);self.assertFalse(proof['semanticInsertionProved'])
        self.assertEqual(4,proof['characterSequence']);self.assertEqual(6,proof['finalSequence'])
        self.assertEqual(before,rows);self.assertEqual(before,proof['events'])
        self.assertEqual(39549535760,self.fixture['runId'])
        self.assertEqual(12323104682,self.fixture['artifactId'])

    def test_actual_discard_first_u_rows_replay_without_changing_raw_flags(self):
        self.replay_actual(0)

    def test_actual_cancel_first_u_rows_replay_without_changing_raw_flags(self):
        self.replay_actual(1)

    def test_noyield_nonremoving_char_peeks_without_consumed_char_never_complete(self):
        for index in (0,1):
            with self.subTest(case=index):
                case,state=self.captured(index);rows=case['observations']
                rows[3]['remove']=2
                self.assertIsNone(state.observe(rows))
                self.assertIsNone(state.character_sequence);self.assertFalse(state.complete)
                self.assertEqual(4,state.key_index)

    def test_noyield_key_peeks_never_advance_and_removed_key_messages_still_required(self):
        case,state=self.captured();rows=[]
        for original in case['observations']:
            if original['message'] in (0x100,0x101):
                rows.append(dict(original,remove=2))
                rows.append(dict(original,remove=3))
            else:rows.append(original)
        rows=self.resequence(rows);before=copy.deepcopy(rows)
        self.assertTrue(state.observe(rows)['queueConsumed'])
        self.assertEqual(before,state.events)

    def test_unknown_remove_bits_or_untyped_flags_are_fatal(self):
        for value in (4,5,6,7,8,0x80000000,0x100000000,0xffffffffffffffff,True):
            with self.subTest(value=value):
                case,state=self.captured();case['observations'][2]['remove']=value
                with self.assertRaises(AssertionError):state.observe(case['observations'])
                with self.assertRaisesRegex(AssertionError,'failed'):state.observe([])

    def test_noyield_does_not_admit_foreign_origins_or_event_flags(self):
        for field,value in (('origin',0),('origin',2),('flags',1),('flags',2)):
            with self.subTest(field=field,value=value):
                case,state=self.captured();case['observations'][2][field]=value
                with self.assertRaisesRegex(AssertionError,'source flags'):state.observe(case['observations'])

    def test_duplicate_noyield_consumed_char_remains_fatal(self):
        case,state=self.captured();rows=case['observations'];rows.insert(4,copy.deepcopy(rows[3]))
        with self.assertRaisesRegex(AssertionError,'Duplicate consumed ASCII character'):
            state.observe(self.resequence(rows))

    def test_noyield_keeps_target_epoch_character_and_key_order_guards(self):
        for changed in ('pid','tid','hwnd','layout','actionEpoch','character','key-order','system'):
            with self.subTest(changed=changed):
                case,state=self.captured();rows=case['observations']
                if changed=='character':rows[2]['wParam']=ord('V')
                elif changed=='key-order':rows[0],rows[1]=rows[1],rows[0];self.resequence(rows)
                elif changed=='system':rows[2]['message']=0x104
                else:rows[2][changed]+=1
                with self.assertRaises(AssertionError):state.observe(rows)

    def test_noyield_consumed_char_still_waits_for_final_original_shift_keyup(self):
        case,state=self.captured();rows=case['observations']
        self.assertIsNone(state.observe(rows[:-1]));self.assertFalse(state.complete)
        self.assertTrue(state.observe(rows[-1:])['queueConsumed'])

    def test_noyield_consumed_char_before_main_keydown_remains_fatal(self):
        case,state=self.captured();rows=case['observations']
        rows=[rows[0],rows[2],rows[3],rows[1],rows[4],rows[5]]
        with self.assertRaisesRegex(AssertionError,'preceded its keydown'):
            state.observe(self.resequence(rows))


if __name__=='__main__':unittest.main()
