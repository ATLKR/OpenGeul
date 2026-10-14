"""Strict stage ownership and atomic preparation for PDF base-font resolution."""
from pathlib import Path
import copy
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pdf_font_resolution as subject


class PdfFontResolutionTests(unittest.TestCase):
    def proof(self):
        return {'beforeSha256': copy.deepcopy(subject.INPUT_SOURCE_SHA256),
                'afterSha256': copy.deepcopy(subject.OUTPUT_SOURCE_SHA256),
                'helperSha256': subject.sha(ROOT / subject.HELPER)}

    def validate(self, proof=None, files=None, helpers=None):
        subject.validate_contract(
            self.proof() if proof is None else proof,
            dict(subject.OUTPUT_SOURCE_SHA256) if files is None else files,
            {subject.HELPER: subject.sha(ROOT / subject.HELPER)} if helpers is None else helpers,
        )

    def test_current_renderer_and_read_only_dependencies_are_bound(self):
        self.validate()
        self.assertEqual(set(subject.SOURCE_FILES), {subject.PDF, subject.GUARD, subject.POLICY})
        self.assertEqual(subject.INPUT_SOURCE_SHA256[subject.GUARD], subject.OUTPUT_SOURCE_SHA256[subject.GUARD])
        self.assertEqual(subject.INPUT_SOURCE_SHA256[subject.POLICY], subject.OUTPUT_SOURCE_SHA256[subject.POLICY])

    def test_legacy_missing_or_extra_proof_fails(self):
        for proof in [None, {}, {**self.proof(), 'adopted': True}]:
            with self.subTest(proof=proof):
                with self.assertRaises(ValueError):
                    subject.validate_contract(proof, dict(subject.OUTPUT_SOURCE_SHA256),
                                              {subject.HELPER: subject.sha(ROOT / subject.HELPER)})

    def test_coherent_rehashed_renderer_proof_is_not_adopted(self):
        proof = self.proof(); files = dict(subject.OUTPUT_SOURCE_SHA256)
        proof['afterSha256'][subject.PDF] = files[subject.PDF] = '0' * 64
        with self.assertRaises(ValueError):
            self.validate(proof, files)

    def test_read_only_guard_and_policy_drift_fail(self):
        for name in [subject.GUARD, subject.POLICY]:
            files = dict(subject.OUTPUT_SOURCE_SHA256); files[name] = '0' * 64
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(files=files)

    def test_missing_or_rehashed_helper_is_not_adopted(self):
        with self.assertRaises(ValueError):
            self.validate(helpers={})
        proof = self.proof(); proof['helperSha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.validate(proof, helpers={subject.HELPER: '0' * 64})

    def fixture(self, root):
        inputs = {subject.PDF: subject.REPLACEMENTS[0][0], subject.GUARD: b'owned guard', subject.POLICY: b'owned policy'}
        for name, raw in inputs.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        before = {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()}
        output = inputs[subject.PDF].replace(*subject.REPLACEMENTS[0])
        after = {**before, subject.PDF: hashlib.sha256(output).hexdigest()}
        return inputs, before, after, output

    def test_preparation_writes_only_renderer_and_reapplication_fails(self):
        # Small sealed source fixture exercises the writer; actual full-source
        # pins are independently checked by fresh upstream preparation.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); inputs, before, after, output = self.fixture(root)
            with patch.object(subject, 'INPUT_SOURCE_SHA256', before), patch.object(subject, 'OUTPUT_SOURCE_SHA256', after):
                proof = subject.apply(root)
                self.assertEqual(proof['beforeSha256'], before)
                self.assertEqual(proof['afterSha256'], after)
                self.assertEqual((root / subject.PDF).read_bytes(), output)
                for name in [subject.GUARD, subject.POLICY]:
                    self.assertEqual((root / name).read_bytes(), inputs[name])
                with self.assertRaises(ValueError):
                    subject.apply(root)

    def test_dependency_drift_is_rejected_before_renderer_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); inputs, before, after, _ = self.fixture(root)
            (root / subject.POLICY).write_bytes(b'drift')
            with patch.object(subject, 'INPUT_SOURCE_SHA256', before), patch.object(subject, 'OUTPUT_SOURCE_SHA256', after):
                with self.assertRaises(ValueError):
                    subject.apply(root)
            self.assertEqual((root / subject.PDF).read_bytes(), inputs[subject.PDF])

    def test_symlink_dependency_is_rejected_before_renderer_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); inputs, before, after, _ = self.fixture(root)
            target = root / 'owned-policy'; target.write_bytes(inputs[subject.POLICY])
            link = root / subject.POLICY; link.unlink(); link.symlink_to(target)
            with patch.object(subject, 'INPUT_SOURCE_SHA256', before), patch.object(subject, 'OUTPUT_SOURCE_SHA256', after):
                with self.assertRaises(ValueError):
                    subject.apply(root)
            self.assertEqual((root / subject.PDF).read_bytes(), inputs[subject.PDF])


if __name__ == '__main__':
    unittest.main()
