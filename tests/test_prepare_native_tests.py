from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import prepare_native_tests as gates


class NativeTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.core = Path(self.temp.name)
        (self.core/'Cargo.toml').write_text('[package]\nname = "rhwp"\nversion = "0.8.7"\nautotests = false\n')

    def test_explicit_targets_preserve_disabled_auto_discovery(self):
        gates.prepare(self.core)
        value = tomllib.loads((self.core/'Cargo.toml').read_text())
        self.assertIs(value['package']['autotests'], False)
        targets = {item['name']: item for item in value['test']}
        self.assertEqual(set(targets), set(gates.TARGETS))
        self.assertEqual(targets['opengeul_pdf_policy']['required-features'], ['native-skia'])
        for name in targets:
            self.assertTrue((self.core/targets[name]['path']).is_file())

    def test_existing_target_is_rejected_before_any_source_overwrite(self):
        existing = self.core/'tests/opengeul_table_height.rs'
        existing.parent.mkdir()
        existing.write_text('user-owned')
        original = (self.core/'Cargo.toml').read_bytes()
        with self.assertRaisesRegex(ValueError, 'existing upstream'):
            gates.prepare(self.core)
        self.assertEqual(existing.read_text(), 'user-owned')
        self.assertEqual((self.core/'Cargo.toml').read_bytes(), original)

    def test_existing_manifest_target_is_rejected_without_creating_files(self):
        with (self.core/'Cargo.toml').open('a') as handle:
            handle.write('\n[[test]]\nname = "opengeul_pdf_policy"\npath = "some-other-test.rs"\n')
        with self.assertRaisesRegex(ValueError, 'existing upstream'):
            gates.prepare(self.core)
        self.assertFalse((self.core/'tests').exists())


if __name__ == '__main__':
    unittest.main()
