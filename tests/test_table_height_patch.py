from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('table_patch', ROOT/'scripts/patch_table_height.py')
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)

class TableHeightPatchTests(unittest.TestCase):
    def source(self):
        return ('fn example() {\n' + patch.ANCHOR + '\n}\n') * 2

    def test_changes_exactly_two_terminal_tac_paths(self):
        result = patch.transform(self.source())
        self.assertEqual(result.count('if is_cell_last_line && table.common.treat_as_char'), 2)
        self.assertEqual(result.count('trailing.max(0.0)'), 2)
        self.assertEqual(result.count('h + trailing'), 2)

    def test_missing_duplicate_or_drifted_anchor_fails(self):
        for text in ('', self.source()+patch.ANCHOR, self.source().replace('self.dpi', 'dpi')):
            with self.subTest(text=text[:30]), self.assertRaises(ValueError):patch.transform(text)

    def test_exact_source_bytes_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            core = Path(folder)
            source = core/'src/renderer/height_measurer.rs'
            source.parent.mkdir(parents=True)
            source.write_text(self.source())
            with self.assertRaises(ValueError):patch.apply(core)
            self.assertEqual(source.read_text(), self.source())

    def test_positive_and_nonterminal_formula_remain_unchanged(self):
        result = patch.transform(self.source())
        self.assertIn('} else {\n                                                trailing\n', result)
        self.assertNotIn('line.line_spacing =', result)

    def test_wrong_number_of_original_sites_is_rejected(self):
        for count in (0,1,3,5):
            with self.subTest(count=count), self.assertRaises(ValueError):patch.transform(patch.ANCHOR*count)

    def test_prepatched_source_without_ledger_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            core=Path(folder); target=core/'src/renderer/height_measurer.rs'
            target.parent.mkdir(parents=True); target.write_text(patch.transform(self.source()))
            with self.assertRaises(ValueError):patch.apply(core)

if __name__ == '__main__':unittest.main()
