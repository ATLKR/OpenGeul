"""Portable registry-boundary tests; never change the machine registry."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


HELPER = Path(__file__).resolve().parents[1] / 'scripts/vsceip_policy.py'


class Clock:
    value = 0.
    def __call__(self):
        return self.value


class Key:
    def __init__(self, api): self.api = api
    def Close(self): self.api.closed += 1


class Registry:
    HKEY_LOCAL_MACHINE = 1
    KEY_QUERY_VALUE, KEY_SET_VALUE, KEY_WOW64_64KEY = 1, 2, 0x100
    REG_DWORD = 4

    def __init__(self, clock, value=(1, 4), key_exists=True):
        self.clock, self.value, self.key_exists = clock, value, key_exists
        self.calls, self.closed, self.sets, self.queries = [], 0, 0, 0
        self.fail_set_after_write = False
        self.fail_restore = False
        self.wrong_readback = False
        self.expire_set = False
        self.expire_restore = False
        self.wrong_restore_type = False
        self.on_set = None

    def OpenKey(self, root, path, reserved, access):
        self.calls.append(('OpenKey', root, path, access))
        if not self.key_exists: raise FileNotFoundError('missing policy key')
        return Key(self)

    def CreateKeyEx(self, root, path, reserved, access):
        self.calls.append(('CreateKeyEx', root, path, access))
        self.key_exists = True
        return Key(self)

    def QueryValueEx(self, key, name):
        self.calls.append(('QueryValueEx', name))
        self.queries += 1
        if self.wrong_readback and self.queries == 2: return (1, self.REG_DWORD)
        if self.wrong_restore_type and self.queries >= 3: return (True, self.REG_DWORD)
        if self.value is None: raise FileNotFoundError('missing policy value')
        return self.value

    def SetValueEx(self, key, name, reserved, kind, value):
        self.calls.append(('SetValueEx', name, kind, value))
        self.sets += 1
        if self.on_set: self.on_set(self.sets)
        if self.sets > 1 and self.fail_restore: raise OSError('restore denied')
        self.value = (value, kind)
        if self.sets == 1 and self.expire_set: self.clock.value = 6.
        if self.sets > 1 and self.expire_restore: self.clock.value += 6.
        if self.sets == 1 and self.fail_set_after_write: raise OSError('set returned failure after write')

    def DeleteValue(self, key, name):
        self.calls.append(('DeleteValue', name))
        if self.fail_restore: raise OSError('restore delete denied')
        if self.value is None: raise FileNotFoundError('already absent')
        self.value = None


class TemporaryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(HELPER.is_file(), 'CI-only reversible policy helper is missing')
        spec = importlib.util.spec_from_file_location('ci_policy_under_test', HELPER)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name).resolve()
        self.clock = Clock()
        self.api = Registry(self.clock)
        self.receipt = {}

    def context(self):
        return self.module.temporary_vs_opt_out(self.output, self.receipt,
                                                registry=self.api, clock=self.clock)

    def test_existing_dword_one_is_backed_up_before_write_and_exactly_restored(self):
        def verify_before_set(index):
            if index == 1:
                prior = json.loads((self.output / 'vsceip-policy-before.json').read_bytes())
                self.assertEqual(prior['prior'], dict(keyExists=True, valueExists=True, kind=4, value=1))
                self.assertTrue(self.receipt['writeAttempted'])
        self.api.on_set = verify_before_set
        with self.context():
            self.assertEqual(self.api.value, (0, 4))
            self.assertTrue(self.receipt['appliedAndVerified'])
        self.assertEqual(self.api.value, (1, 4))
        self.assertTrue(self.receipt['restoredAndVerified'])
        self.assertEqual(self.api.closed, 1)
        self.assertTrue((self.output / 'vsceip-policy-after.json').is_file())
        self.assertTrue(all(call[3] & self.api.KEY_WOW64_64KEY for call in self.api.calls if call[0] == 'OpenKey'))

    def test_existing_dword_zero_remains_exact_zero_after_restoration(self):
        self.api.value = (0, 4)
        with self.context(): self.assertEqual(self.api.value, (0, 4))
        self.assertEqual(self.api.value, (0, 4))
        self.assertTrue(self.receipt['restoredAndVerified'])

    def test_missing_value_restores_absence_without_deleting_shared_key(self):
        self.api.value = None
        with self.context(): self.assertEqual(self.api.value, (0, 4))
        self.assertIsNone(self.api.value)
        self.assertTrue(self.api.key_exists)
        self.assertIn(('DeleteValue', 'OptIn'), self.api.calls)
        self.assertTrue(self.receipt['restoredAndVerified'])

    def test_missing_key_may_leave_empty_container_but_no_active_policy_value(self):
        self.api.value, self.api.key_exists = None, False
        with self.context(): self.assertEqual(self.api.value, (0, 4))
        self.assertIsNone(self.api.value)
        self.assertTrue(self.api.key_exists)
        self.assertTrue(self.receipt['emptyCreatedContainerMayRemain'])
        self.assertTrue(self.receipt['restoredAndVerified'])

    def test_unknown_kind_or_dword_value_is_rejected_before_any_mutation(self):
        for value in [('private-unexpected-value', 1), (2, 4), (True, 4)]:
            with self.subTest(value=value):
                self.api = Registry(self.clock, value=value)
                self.receipt = {}
                child = self.output / str(len(list(self.output.iterdir())))
                child.mkdir()
                with self.assertRaisesRegex(AssertionError, 'prior'):
                    with self.module.temporary_vs_opt_out(child, self.receipt, registry=self.api, clock=self.clock):
                        self.fail('unadmitted policy reached preparation')
                self.assertEqual(self.api.sets, 0)
                self.assertFalse(any(call[0] in ('CreateKeyEx', 'DeleteValue') for call in self.api.calls))
                self.assertEqual(self.api.value, value)
                self.assertNotIn('private-unexpected-value', json.dumps(self.receipt))

    def test_setup_set_failure_after_write_is_rolled_back_without_entering_body(self):
        self.api.fail_set_after_write = True
        with self.assertRaisesRegex(OSError, 'set returned failure'):
            with self.context(): self.fail('failed setup reached preparation')
        self.assertEqual(self.api.value, (1, 4))
        self.assertTrue(self.receipt['restoredAndVerified'])
        self.assertEqual(self.api.closed, 1)

    def test_setup_readback_mismatch_rolls_back_before_body(self):
        self.api.wrong_readback = True
        with self.assertRaisesRegex(AssertionError, 'readback'):
            with self.context(): self.fail('mismatched setup reached preparation')
        self.assertEqual(self.api.value, (1, 4))
        self.assertTrue(self.receipt['restoredAndVerified'])

    def test_original_preparation_error_is_preserved_and_policy_restored(self):
        primary = RuntimeError('original preparation failed')
        with self.assertRaises(RuntimeError) as caught:
            with self.context(): raise primary
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.api.value, (1, 4))
        self.assertTrue(self.receipt['restoredAndVerified'])

    def test_restore_failure_is_secondary_to_original_preparation_error(self):
        self.api.fail_restore = True
        primary = RuntimeError('original preparation failed')
        with self.assertRaises(RuntimeError) as caught:
            with self.context(): raise primary
        self.assertIs(caught.exception, primary)
        self.assertIn('restore denied', self.receipt['restoreError']['message'])
        self.assertFalse(self.receipt['restoredAndVerified'])
        self.assertEqual(self.api.closed, 1)

    def test_restore_failure_invalidates_otherwise_successful_preparation(self):
        self.api.fail_restore = True
        with self.assertRaisesRegex(OSError, 'restore denied'):
            with self.context(): pass
        self.assertFalse(self.receipt['restoredAndVerified'])
        self.assertEqual(self.api.closed, 1)

    def test_backup_write_failure_never_sets_policy(self):
        original = self.module.write_durable
        def fail_backup(path, value):
            if path.name == 'vsceip-policy-before.json': raise OSError('backup unavailable')
            return original(path, value)
        with patch.object(self.module, 'write_durable', side_effect=fail_backup):
            with self.assertRaisesRegex(OSError, 'backup unavailable'):
                with self.context(): self.fail('missing backup reached preparation')
        self.assertEqual(self.api.sets, 0)
        self.assertEqual(self.api.value, (1, 4))
        self.assertEqual(self.api.closed, 1)

    def test_setup_expiry_after_set_still_restores_outside_preparation_budget(self):
        self.api.expire_set = True
        with self.assertRaisesRegex(TimeoutError, 'setup'):
            with self.context(): self.fail('expired setup reached preparation')
        self.assertEqual(self.api.value, (1, 4))
        self.assertTrue(self.receipt['restoredAndVerified'])

    def test_restore_expiry_is_recorded_without_claiming_verified_restoration(self):
        self.api.expire_restore = True
        with self.assertRaisesRegex(TimeoutError, 'restore'):
            with self.context(): pass
        self.assertEqual(self.api.value, (1, 4))
        self.assertFalse(self.receipt['restoredAndVerified'])
        self.assertEqual(self.api.closed, 1)

    def test_restore_readback_rejects_boolean_instead_of_exact_integer(self):
        self.api.wrong_restore_type = True
        with self.assertRaisesRegex(AssertionError, 'restoration'):
            with self.context(): pass
        self.assertFalse(self.receipt['restoredAndVerified'])

    def run_driver(self, fail_prepare):
        path = HELPER.parent / 'diagnose-ascii-preparation.py'
        spec = importlib.util.spec_from_file_location('ci_policy_driver_under_test', path)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        calls = []
        def prepare(*args, **kwargs):
            calls.append(('prepare', kwargs.get('compiler_mode')))
            if fail_prepare: raise RuntimeError('original preparation failed')
            return dict(fakeDescriptor=True)
        def policy(output, receipt):
            self.fail('Failed policy experiment must not run in the LLVM probe')
        target = self.output / 'driver'
        original_path = list(sys.path)
        try:
            with patch.object(driver, 'os', SimpleNamespace(name='nt', environ={'GITHUB_SHA': 'a' * 40})), \
                 patch.object(driver, 'snapshot_scripts', return_value=dict(complete=False)), \
                 patch.object(sys, 'argv', [str(path), '--architecture', 'x64', '--output', str(target)]), \
                 patch.dict(sys.modules, {'ascii_message_preparation': SimpleNamespace(prepare_observer=prepare),
                                          'vsceip_policy': SimpleNamespace(temporary_vs_opt_out=policy)}):
                code = driver.main()
        finally:
            sys.path[:] = original_path
        return code, calls, json.loads((target / 'diagnosis.json').read_bytes())

    def test_driver_selects_llvm_without_policy_and_binds_all_seven_sources(self):
        code, calls, result = self.run_driver(False)
        self.assertEqual((code, calls), (0, [('prepare', 'clang-lld')]))
        self.assertTrue(result['success'])
        self.assertNotIn('vsceipPolicy', result)
        self.assertEqual(result['compilerMode'], 'clang-lld')
        self.assertEqual(len(result['sourceBefore']), 7)
        self.assertIn('suite/e2e/native_compiler_tools.py', {name.replace('\\', '/') for name in result['sourceBefore']})
        self.assertEqual(result['sourceBefore'], result['sourceAfter'])

    def test_driver_preserves_failed_llvm_preparation_without_policy(self):
        code, calls, result = self.run_driver(True)
        self.assertEqual((code, calls), (1, [('prepare', 'clang-lld')]))
        self.assertFalse(result['success'])
        self.assertNotIn('descriptor', result)
        self.assertEqual(result['error']['message'], 'original preparation failed')


if __name__ == '__main__':
    unittest.main()
