"""Font preparation pins source and inherited ledgers before any product write."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import prepare_upstream as p
import prepare_hwpx


class AsyncFontSelectionPreparationTests(unittest.TestCase):
    def fixture(self, root):
        paths = {name: root/name for name in [*p.ASYNC_FONT_INPUT_SHA256, 'apps/studio-host/src/ui/toolbar.test.ts']}
        for name, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('// unreviewed '+name+'\n').encode())
        return paths

    def test_pinned_or_host_test_change_is_rejected_before_product_writes_or_proof_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            original = {name: path.read_bytes() for name, path in paths.items()}
            inherited = {'unchanged': 'proof'}
            with self.assertRaisesRegex(ValueError, 'Upstream async font selection source changed'):
                p.install_async_font_selection_guard(root, inherited, inherited)
            self.assertEqual(inherited, {'unchanged': 'proof'})
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, original)

    def test_missing_main_is_rejected_before_any_other_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            paths[p.FONT_MAIN].unlink()
            originals = {name: path.read_bytes() for name, path in paths.items() if name != p.FONT_MAIN}
            with self.assertRaises(FileNotFoundError):
                p.install_async_font_selection_guard(root, {}, {})
            self.assertEqual({name: paths[name].read_bytes() for name in originals}, originals)

    def test_inherited_proof_mismatch_is_rejected_before_replacements_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            original = {name: path.read_bytes() for name, path in paths.items()}
            pins = {name: hashlib.sha256(data).hexdigest() for name, data in original.items() if not name.endswith('.test.ts')}
            with patch.object(p, 'ASYNC_FONT_INPUT_SHA256', pins), patch.object(
                    p, 'FONT_TOOLBAR_TEST_SHA256', hashlib.sha256(original['apps/studio-host/src/ui/toolbar.test.ts']).hexdigest()):
                with self.assertRaisesRegex(ValueError, 'requires the current clipboard and image proofs'):
                    p.install_async_font_selection_guard(root, {}, {})
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, original)

    def test_final_proof_validates_raw_main_and_all_shared_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            proof = {'beforeSha256': dict(p.ASYNC_FONT_SOURCE_SHA256),
                     'afterSha256': {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in p.ASYNC_FONT_SOURCE_SHA256}}
            p.validate_async_font_selection_proof(root, proof)
            for name in p.ASYNC_FONT_SOURCE_SHA256:
                with self.subTest(file=name):
                    data = paths[name].read_bytes()
                    paths[name].write_bytes(data+b'// tampered final source\n')
                    with self.assertRaisesRegex(ValueError, 'prepared source hash mismatch'):
                        p.validate_async_font_selection_proof(root, proof)
                    paths[name].write_bytes(data)

    def test_replacement_mismatch_is_rejected_before_any_source_or_proof_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.fixture(root)
            insert = root/'third_party/rhwp/rhwp-studio/src/command/commands/insert.ts'
            insert.parent.mkdir(parents=True, exist_ok=True)
            insert.write_bytes(b'// isolated insert fixture\n')
            originals = {name: path.read_bytes() for name, path in paths.items()}
            digests = {name: hashlib.sha256(data).hexdigest() for name, data in originals.items() if not name.endswith('.test.ts')}
            engine = root/'third_party/rhwp/rhwp-studio/src/engine'
            clipboard = {'beforeSha256': dict(p.ASYNC_CLIPBOARD_SOURCE_SHA256),
                         'afterSha256': {name: hashlib.sha256((engine/name).read_bytes()).hexdigest() for name in p.ASYNC_CLIPBOARD_SOURCE_SHA256}}
            image = {'beforeSha256': dict(p.IMAGE_INSERTION_SOURCE_SHA256),
                     'afterSha256': {'engine/input-handler.ts': clipboard['afterSha256']['input-handler.ts'],
                                    'command/commands/insert.ts': hashlib.sha256(insert.read_bytes()).hexdigest()}}
            import copy
            before_proofs = copy.deepcopy((clipboard, image))
            with patch.object(p, 'ASYNC_FONT_INPUT_SHA256', digests), patch.object(
                    p, 'FONT_TOOLBAR_TEST_SHA256', hashlib.sha256(originals['apps/studio-host/src/ui/toolbar.test.ts']).hexdigest()):
                with self.assertRaises(ValueError):
                    p.install_async_font_selection_guard(root, clipboard, image)
            self.assertEqual((clipboard, image), before_proofs)
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, originals)

    def test_hwpx_stage_rejects_previous_main_tamper_before_native_or_ledger_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            proof = {'beforeSha256': dict(p.ASYNC_FONT_SOURCE_SHA256),
                     'afterSha256': {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in p.ASYNC_FONT_SOURCE_SHA256}}
            import json
            ledger = root/'.opengeul-overlay.json'
            ledger.write_text(json.dumps({'asyncFontSelectionGuard': proof}))
            original_ledger = ledger.read_bytes()
            (root/p.FONT_MAIN).write_bytes(b'// tampered before HWPX extensions\n')
            with self.assertRaisesRegex(ValueError, 'prepared source hash mismatch'):
                prepare_hwpx.patch(root)
            self.assertEqual(ledger.read_bytes(), original_ledger)
            self.assertFalse((root/'apps/desktop/src-tauri/src/opengeul_hwpx_commands.rs').exists())
