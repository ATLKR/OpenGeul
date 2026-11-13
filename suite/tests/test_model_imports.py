"""Fresh-process harness imports; no UNO, native, or helper actions are run."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


E2E = Path(__file__).resolve().parents[1] / 'e2e'
MODULE_CALLABLES = {
    'writer_style_smoke': ('validate_python_observation', 'observe_packaged_python', 'require_packaged_python'),
    'writer_model_reader': ('_helper', 'OwnedWriterReader', 'OwnedModelReader'),
    'lifecycle_smoke': ('Case', 'WriterModelContext'),
    'windows_smoke': ('document_case', 'CalcModelContext'),
    'writer_model_barrier': ('require_python_identity', 'freeze_expectation'),
    'calc_model_barrier': ('freeze_expectation', 'validate_observation'),
}
ENTRYPOINTS = {
    'style_first': ('import writer_style_smoke', ('writer_style_smoke',)),
    'helper_order': (
        'import writer_model_reader\n'
        'from writer_style_smoke import observe_packaged_python, require_packaged_python\n'
        'assert callable(observe_packaged_python) and callable(require_packaged_python)',
        ('writer_model_reader', 'writer_style_smoke')),
    'lifecycle_first': ('import lifecycle_smoke', ('lifecycle_smoke',)),
    'native_first': ('import windows_smoke', ('windows_smoke',)),
    'reader_first': ('import writer_model_reader', ('writer_model_reader',)),
    'barrier_first': ('import writer_model_barrier', ('writer_model_barrier',)),
}
PROBE = '''
import json
from pathlib import Path
import sys

e2e = Path(sys.argv[1]).resolve()
checks = json.loads(sys.argv[3])
assert not set(checks).intersection(sys.modules), 'Harness modules were already cached'
assert 'uno' not in sys.modules and 'pyuno' not in sys.modules
sys.path.insert(0, str(e2e))
exec(sys.argv[2])
loaded = {}
for name, callables in checks.items():
    if name in sys.modules:
        module = sys.modules[name]
        assert Path(module.__file__).resolve() == e2e / (name + '.py'), module.__file__
        assert all(callable(getattr(module, member)) for member in callables), name
        loaded[name] = str(Path(module.__file__).resolve())
assert 'uno' not in sys.modules and 'pyuno' not in sys.modules
print(json.dumps(loaded, sort_keys=True))
'''


class ModelImportTests(unittest.TestCase):
    def test_entrypoints_initialize_in_separate_uncached_interpreters(self):
        for name, (imports, required_modules) in ENTRYPOINTS.items():
            with self.subTest(entrypoint=name):
                result = subprocess.run(
                    [sys.executable, '-I', '-B', '-c', PROBE, str(E2E), imports,
                     json.dumps(MODULE_CALLABLES)],
                    cwd=E2E.parent, capture_output=True, text=True, timeout=20, shell=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                loaded = json.loads(result.stdout)
                self.assertTrue(set(required_modules).issubset(loaded), loaded)
                for module, path in loaded.items():
                    self.assertEqual(Path(path), E2E / (module + '.py'))


if __name__ == '__main__':
    unittest.main()
