"""Unreviewed clipboard source must fail preparation before either file is changed."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from prepare_upstream import install_async_clipboard_guard


class AsyncClipboardPreparationTests(unittest.TestCase):
    def test_changed_pinned_source_is_rejected_before_any_file_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            engine = source/'third_party/rhwp/rhwp-studio/src/engine'
            engine.mkdir(parents=True)
            files = {name: b'// unreviewed upstream clipboard source\n' for name in
                     ('input-handler-keyboard.ts', 'input-handler.ts')}
            for name, data in files.items():
                (engine/name).write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'Upstream async clipboard source changed'):
                install_async_clipboard_guard(source)
            for name, data in files.items():
                self.assertEqual((engine/name).read_bytes(), data)

    def test_missing_lifecycle_source_is_rejected_before_keyboard_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            engine = source/'third_party/rhwp/rhwp-studio/src/engine'
            engine.mkdir(parents=True)
            keyboard = engine/'input-handler-keyboard.ts'
            keyboard.write_bytes(b'// incomplete pinned checkout\n')
            with self.assertRaises(FileNotFoundError):
                install_async_clipboard_guard(source)
            self.assertEqual(keyboard.read_bytes(), b'// incomplete pinned checkout\n')
