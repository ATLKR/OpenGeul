"""Strict source/proof policy; real focus behavior is exercised in tests/hop."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import equation_dialog_focus as focus


class EquationDialogFocusProofTests(unittest.TestCase):
    def setUp(self):
        self.helper = hashlib.sha256((ROOT / focus.HELPER).read_bytes()).hexdigest()
        self.proof = {'beforeSha256': dict(focus.INPUT_SOURCE_SHA256),
                      'afterSha256': dict(focus.OUTPUT_SOURCE_SHA256),
                      'helperSha256': self.helper}
        self.files = dict(focus.OUTPUT_SOURCE_SHA256)
        self.helpers = {focus.HELPER: self.helper}

    def test_exact_reviewed_contract(self):
        focus.validate_contract(self.proof, self.files, self.helpers)

    def test_one_source_before_and_after_pins_are_fixed(self):
        self.assertEqual(focus.SOURCE_FILES, (focus.EDITOR,))
        self.assertEqual(focus.INPUT_SOURCE_SHA256, {focus.EDITOR:
            '1e8c382436302ee88714ba2a57d413ffa9172572f712713ce352ea91cc74fffc'})
        self.assertEqual(focus.OUTPUT_SOURCE_SHA256, {focus.EDITOR:
            '76718c71ccb0f20f622d4a1803fcfcf5174249a01bc033d63ccb82dd65cda99e'})
        self.assertNotEqual(focus.INPUT_SOURCE_SHA256, focus.OUTPUT_SOURCE_SHA256)

    def test_legacy_or_coordinated_unreviewed_output_cannot_qualify(self):
        for value in (focus.INPUT_SOURCE_SHA256[focus.EDITOR], '0' * 64):
            proof = copy.deepcopy(self.proof)
            proof['afterSha256'][focus.EDITOR] = value
            with self.assertRaisesRegex(ValueError, 'reviewed'):
                focus.validate_contract(proof, {focus.EDITOR: value}, self.helpers)

    def test_missing_extra_and_forged_proof_members_are_rejected(self):
        for key in self.proof:
            proof = copy.deepcopy(self.proof)
            proof.pop(key)
            with self.assertRaises(ValueError):
                focus.validate_contract(proof, self.files, self.helpers)
        with self.assertRaises(ValueError):
            focus.validate_contract({**self.proof, 'optional': True}, self.files, self.helpers)
        for key in ('beforeSha256', 'afterSha256'):
            for replacement in ({}, {focus.EDITOR: '1' * 64},
                                {**self.proof[key], 'unrelated.ts': '2' * 64}):
                proof = copy.deepcopy(self.proof)
                proof[key] = replacement
                with self.assertRaises(ValueError):
                    focus.validate_contract(proof, self.files, self.helpers)

    def test_actual_prepared_file_and_current_helper_are_required(self):
        for files in ({}, {focus.EDITOR: '3' * 64}):
            with self.assertRaisesRegex(ValueError, 'prepared'):
                focus.validate_contract(self.proof, files, self.helpers)
        for helpers in ({}, {focus.HELPER: '4' * 64}):
            with self.assertRaisesRegex(ValueError, 'helper'):
                focus.validate_contract(self.proof, self.files, helpers)
        proof = copy.deepcopy(self.proof)
        proof['helperSha256'] = '5' * 64
        with self.assertRaisesRegex(ValueError, 'helper'):
            focus.validate_contract(proof, self.files, {focus.HELPER: '5' * 64})

    def test_nonobject_contract_inputs_are_rejected(self):
        for proof, files, helpers in ((None, self.files, self.helpers),
                                     (self.proof, None, self.helpers),
                                     (self.proof, self.files, None)):
            with self.assertRaises(ValueError):
                focus.validate_contract(proof, files, helpers)

    def test_matching_anchors_cannot_admit_unknown_source(self):
        for raw in (focus.REPLACEMENTS[0][0].encode(),
                    '\n'.join(old for old, _ in focus.REPLACEMENTS).encode()):
            with self.assertRaisesRegex(ValueError, 'input changed'):
                focus.transformed(raw)

    def test_missing_tampered_and_symlink_source_are_not_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            path = source / focus.EDITOR
            with self.assertRaises(ValueError):
                focus.apply(source)
            path.parent.mkdir(parents=True)
            raw = focus.REPLACEMENTS[0][0].encode()
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                focus.apply(source)
            self.assertEqual(path.read_bytes(), raw)
            target = source / 'owned-source.ts'
            target.write_bytes(raw)
            path.unlink()
            path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'regular'):
                focus.apply(source)
            self.assertEqual(target.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
