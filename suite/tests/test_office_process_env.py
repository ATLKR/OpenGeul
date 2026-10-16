"""Per-process temp paths must match Firebird's long-path access checks."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'worker'))


class OfficeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.native = importlib.import_module('native_windows')
        self.assertTrue(hasattr(self.native, 'canonicalize_temp_environment'),
                        'Owned Office process must canonicalize its private TEMP/TMP environment')

    def test_short_windows_aliases_are_normalized_only_in_child_environment(self):
        inherited = {'TEMP': r'C:\Users\RUNNER~1\AppData\Local\Temp',
                     'TMP': r'C:\Users\RUNNER~1\AppData\Local\Temp',
                     'PATH': r'C:\toolchain', 'FIREBIRD': r'C:\server-owned-config',
                     'CUSTOM': '한글 secret unchanged'}
        original = dict(inherited)
        long_path = r'C:\Users\runneradmin\AppData\Local\Temp'
        resolved = []
        def resolver(path):
            resolved.append(path)
            return long_path
        child = self.native.canonicalize_temp_environment(inherited, resolver=resolver)
        self.assertEqual(long_path, child['TEMP'])
        self.assertEqual(long_path, child['TMP'])
        self.assertEqual([original['TEMP'], original['TMP']], resolved)
        self.assertEqual(original, inherited)
        self.assertEqual({k: original[k] for k in ('PATH', 'FIREBIRD', 'CUSTOM')},
                         {k: child[k] for k in ('PATH', 'FIREBIRD', 'CUSTOM')})
        self.assertIsNot(child, inherited)

    def test_default_resolver_uses_real_filesystem_path_resolution(self):
        with tempfile.TemporaryDirectory() as folder:
            original = {'TEMP': str(Path(folder) / '..' / Path(folder).name), 'TMP': folder}
            child = self.native.canonicalize_temp_environment(original)
            self.assertEqual(str(Path(folder).resolve()), child['TEMP'])
            self.assertEqual(str(Path(folder).resolve()), child['TMP'])

    def test_absent_empty_and_unrelated_values_are_preserved_without_global_writes(self):
        original_environment = dict(os.environ)
        inherited = {'Temp': 'temp alias', 'tmp': '', 'FIREBIRD_TMP': 'driver-owned', 'HOME': 'unchanged'}
        child = self.native.canonicalize_temp_environment(inherited, resolver=lambda value: 'canonical')
        self.assertEqual({'Temp': 'canonical', 'tmp': '', 'FIREBIRD_TMP': 'driver-owned', 'HOME': 'unchanged'}, child)
        self.assertEqual(original_environment, dict(os.environ))
        self.assertEqual({}, self.native.canonicalize_temp_environment({}))


if __name__ == '__main__':
    unittest.main()
