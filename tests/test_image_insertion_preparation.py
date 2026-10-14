"""Image preparation rejects unreviewed bytes before changing any product source."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import prepare_upstream as p


class ImageInsertionPreparationTests(unittest.TestCase):
    def fixture(self, root):
        source = root/'third_party/rhwp/rhwp-studio/src'
        paths = {name: source/name for name in p.IMAGE_INSERTION_SOURCE_SHA256}
        for name, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('// unreviewed '+name+'\n').encode())
        return paths

    def test_changed_pinned_source_is_rejected_without_changing_either_file_or_clipboard_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            original = {name: path.read_bytes() for name, path in paths.items()}
            clipboard = {'unchanged': 'existing proof'}
            with self.assertRaisesRegex(ValueError, 'Upstream image insertion source changed'):
                p.install_image_insertion_guard(root, clipboard)
            self.assertEqual(clipboard, {'unchanged': 'existing proof'})
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, original)

    def test_missing_handler_is_rejected_before_insert_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            paths['engine/input-handler.ts'].unlink()
            before = paths['command/commands/insert.ts'].read_bytes()
            with self.assertRaises(FileNotFoundError):
                p.install_image_insertion_guard(root, {})
            self.assertEqual(paths['command/commands/insert.ts'].read_bytes(), before)

    def test_mismatched_clipboard_proof_is_rejected_before_replacements_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            original = {name: path.read_bytes() for name, path in paths.items()}
            hashes = {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}
            # Isolate the proof contract after byte validation with small owned files.
            with patch.object(p, 'IMAGE_INSERTION_SOURCE_SHA256', hashes), patch.object(
                    p, 'IMAGE_INSERTION_CLIPBOARD_HANDLER_SHA256', hashes['engine/input-handler.ts']):
                with self.assertRaisesRegex(ValueError, 'requires the current async clipboard proof'):
                    p.install_image_insertion_guard(root, {})
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, original)
