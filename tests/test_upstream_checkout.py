"""Sparse upstream checkout keeps every literal Rust compile input."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_upstream


class SparseCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repository = Path(self.tmp.name) / 'original'
        self.repository.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Checkout test')
        self.git('config', 'user.email', 'checkout@example.invalid')
        files = {
            'Cargo.toml': '[package]\nname="test"\nversion="0.1.0"\n',
            'src/lib.rs': 'include_bytes!("../saved/blank2010.hwp");\ninclude_str!("../mydocs/pr/embedded.txt");\n',
            'saved/blank2010.hwp': 'template',
            'samples/문서.hwpx': 'sample',
            'tests/fixture.txt': 'test input',
            'mydocs/manual/guide.md': 'manual',
            'mydocs/pr/embedded.txt': 'compile input',
            'mydocs/pr/large-reference.txt': 'reference',
            'mydocs/report/reference.txt': 'reference',
            'pdf/reference.pdf': 'reference',
            'tools/reference.bin': 'reference',
            'future-source/module.rs': '// future source\n',
        }
        for name, content in files.items():
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-qm', 'Pinned fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repository, text=True, encoding='utf-8')

    def test_sparse_checkout_preserves_inputs_and_new_source_directories(self):
        destination = Path(self.tmp.name) / 'checkout'
        prepare_upstream.checkout_rhwp(destination, str(self.repository), self.commit)
        for name in ('saved/blank2010.hwp', 'samples/문서.hwpx', 'tests/fixture.txt',
                     'mydocs/manual/guide.md', 'mydocs/pr/embedded.txt', 'future-source/module.rs'):
            self.assertEqual((destination / name).read_bytes(), (self.repository / name).read_bytes())
        for name in ('mydocs/pr/large-reference.txt', 'mydocs/report/reference.txt',
                     'pdf/reference.pdf', 'tools/reference.bin'):
            self.assertFalse((destination / name).exists(), name)
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination, text=True).strip()
        self.assertEqual(actual, self.commit)

    def test_unknown_commit_and_nonempty_destination_are_rejected(self):
        destination = Path(self.tmp.name) / 'checkout'
        destination.mkdir()
        (destination / 'user.txt').write_text('keep', encoding='utf-8')
        with self.assertRaises(ValueError):
            prepare_upstream.checkout_rhwp(destination, str(self.repository), self.commit)
        self.assertEqual((destination / 'user.txt').read_text(), 'keep')
        with self.assertRaises(ValueError):
            prepare_upstream.checkout_rhwp(Path(self.tmp.name) / 'other', str(self.repository), 'HEAD')

    def test_missing_literal_compile_input_is_not_silently_omitted(self):
        (self.repository / 'src/lib.rs').write_text('include_bytes!("../pdf/missing.pdf");\n', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-qm', 'Invalid compile input')
        commit = self.git('rev-parse', 'HEAD').strip()
        with self.assertRaises(ValueError):
            prepare_upstream.checkout_rhwp(Path(self.tmp.name) / 'broken', str(self.repository), commit)

    def test_workspace_members_and_their_path_dependencies_survive_sparse_checkout(self):
        files = {
            'Cargo.toml': '[workspace]\nmembers=["tools/worker"]\n',
            'tools/worker/Cargo.toml': '[package]\nname="worker"\nversion="0.1.0"\n[dependencies]\nshared={path="../shared"}\n',
            'tools/worker/src/lib.rs': 'include_str!("../fixture.txt");\n',
            'tools/worker/fixture.txt': 'worker compile input',
            'tools/shared/Cargo.toml': '[package]\nname="shared"\nversion="0.1.0"\n',
            'tools/shared/src/lib.rs': '// dependency\n',
        }
        for name, content in files.items():
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        reference = self.repository / 'tools/reference-material/large.bin'
        reference.parent.mkdir(parents=True)
        reference.write_text('reference material', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-qm', 'Workspace fixture')
        destination = Path(self.tmp.name) / 'workspace-checkout'
        prepare_upstream.checkout_rhwp(destination, str(self.repository), self.git('rev-parse', 'HEAD').strip())
        for name in files:
            self.assertEqual((destination / name).read_bytes(), (self.repository / name).read_bytes())
        # Cone checkout retains ancestor files; unrelated reference subtrees
        # remain excluded when a source member under tools is selected.
        self.assertFalse((destination / 'tools/reference-material/large.bin').exists())


if __name__ == '__main__':
    unittest.main()
