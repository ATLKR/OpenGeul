"""Strict preparation phase boundaries, using small owned source fixtures.

These policy fixtures test byte/proof transitions only. Real command routing,
history and WASM behavior are covered by tests/hop/shape_*_history.test.mjs.
"""
from contextlib import contextmanager
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import menu_clipboard as menu
import shape_creation_history as shape
import test_menu_clipboard_preparation as fixtures


SHAPE_SUFFIX = b'\n// miniature reviewed shape history transformation\n'
SHAPE_PHASES = ('prepared-shape-history', 'hwpx-shape-history', 'hwpx-windows-shape-history')


class MenuShapeHistoryPhaseTests(unittest.TestCase):
    @contextmanager
    def fixture(self, root, *, shape_enabled=True):
        base = fixtures.MenuClipboardPreparationTests()
        predecessors, pins, _ = base.fixture(root)
        with base.fixture_pins(root, pins):
            proof = menu.apply(root, *predecessors)
        phase_pins = base._contracts[root]['PHASE_SOURCE_SHA256']
        shape_bytes = (root / menu.HANDLER).read_bytes() + SHAPE_SUFFIX
        shape_digest = menu.digest(shape_bytes)
        for old, new in zip(('prepared', 'hwpx', 'hwpx-windows'), SHAPE_PHASES):
            phase_pins[new] = {**phase_pins[old], menu.HANDLER: shape_digest}
        if shape_enabled:
            (root / menu.HANDLER).write_bytes(shape_bytes)
            proof['afterSha256'] = dict(phase_pins['prepared-shape-history'])
        with base.fixture_pins(root, pins):
            yield base, proof

    def test_reviewed_shape_phases_change_only_the_exact_handler_pin(self):
        self.assertEqual(menu.PHASE_SOURCE_SHA256['prepared'][menu.HANDLER], shape.INPUT_SHA256)
        for old, new in zip(('prepared', 'hwpx', 'hwpx-windows'), SHAPE_PHASES):
            with self.subTest(phase=new):
                self.assertEqual(menu.PHASE_SOURCE_SHA256[new], {
                    **menu.PHASE_SOURCE_SHA256[old], menu.HANDLER: shape.OUTPUT_SHA256,
                })
        self.assertNotEqual(shape.INPUT_SHA256, shape.OUTPUT_SHA256)

    def test_exact_shape_prepared_phase_is_an_intermediate_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.fixture(root) as (base, proof):
                prepared, helpers = base.contract_inputs(root)
                menu.validate_contract(proof, prepared, helpers, final=False, shape_required=True)
                menu.validate(root, proof)
                with self.assertRaises(ValueError):
                    menu.validate_contract(proof, prepared, helpers, shape_required=True)

    def test_legacy_phase_cannot_qualify_when_shape_is_required(self):
        for phase in ('prepared', 'hwpx', 'hwpx-windows'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.fixture(root, shape_enabled=False) as (base, proof):
                    prepared, helpers = base.contract_inputs(root)
                    proof['afterSha256'] = dict(menu.PHASE_SOURCE_SHA256[phase])
                    prepared.update(proof['afterSha256'])
                    if phase != 'prepared':
                        proof['hwpxPatcherSha256'] = helpers['scripts/prepare_hwpx.py']
                    menu.validate_contract(proof, prepared, helpers, final=False)
                    with self.assertRaises(ValueError):
                        menu.validate_contract(proof, prepared, helpers, final=False, shape_required=True)

    def test_refresh_preserves_exact_shape_phase_and_original_claims(self):
        for windows in (False, True):
            with self.subTest(windows=windows), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.fixture(root) as (base, proof):
                    original = copy.deepcopy(proof)
                    lib = (root / menu.LIB).read_bytes() + fixtures.HWPX_SUFFIX.encode()
                    (root / menu.LIB).write_bytes(lib.replace(b'\n', b'\r\n') if windows else lib)
                    before = fixtures.files(root)
                    menu.refresh_hwpx_lib(root, proof)
                    final = 'hwpx-windows-shape-history' if windows else 'hwpx-shape-history'
                    self.assertEqual(proof['afterSha256'], menu.PHASE_SOURCE_SHA256[final])
                    self.assertEqual(proof['beforeSha256'], original['beforeSha256'])
                    self.assertEqual(proof['helperSha256'], original['helperSha256'])
                    prepared, helpers = base.contract_inputs(root)
                    menu.validate_contract(proof, prepared, helpers, shape_required=True)
                    self.assertEqual(fixtures.files(root), before)
                    old = copy.deepcopy(proof)
                    with self.assertRaises(ValueError):
                        menu.refresh_hwpx_lib(root, proof)
                    self.assertEqual(proof, old)
                    self.assertEqual(fixtures.files(root), before)

    def test_cross_phase_refresh_cannot_relabel_legacy_or_shape_bytes(self):
        for shape_enabled in (False, True):
            with self.subTest(shape_enabled=shape_enabled), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.fixture(root, shape_enabled=shape_enabled) as (_, proof):
                    other = 'prepared' if shape_enabled else 'prepared-shape-history'
                    proof['afterSha256'] = dict(menu.PHASE_SOURCE_SHA256[other])
                    with (root / menu.LIB).open('ab') as output:
                        output.write(fixtures.HWPX_SUFFIX.encode())
                    before = fixtures.files(root)
                    old = copy.deepcopy(proof)
                    with self.assertRaises(ValueError):
                        menu.refresh_hwpx_lib(root, proof)
                    self.assertEqual(proof, old)
                    self.assertEqual(fixtures.files(root), before)

    def test_coordinated_unreviewed_shape_pin_and_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.fixture(root) as (base, proof):
                prepared, helpers = base.contract_inputs(root)
                proof['afterSha256'][menu.HANDLER] = '0' * 64
                prepared[menu.HANDLER] = '0' * 64
                with self.assertRaises(ValueError):
                    menu.validate_contract(proof, prepared, helpers, final=False, shape_required=True)

    def test_refresh_rejects_nonobject_proof_without_writing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.fixture(root):
                before = fixtures.files(root)
                for invalid in (None, [], 'invalid'):
                    with self.subTest(proof=invalid), self.assertRaises(ValueError):
                        menu.refresh_hwpx_lib(root, invalid)
                    self.assertEqual(fixtures.files(root), before)


if __name__ == '__main__':
    unittest.main()
