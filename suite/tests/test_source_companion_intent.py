"""Source intent metadata only; no binary or Full qualification is invented."""
from dataclasses import FrozenInstanceError
import unittest

from suite import source_contracts as contracts


class SourceCompanionIntentTests(unittest.TestCase):
    def intent(self, pin=None, architecture='x64'):
        method = getattr(contracts, 'source_companion_intent', None)
        self.assertTrue(callable(method), 'Missing closed source companion metadata selector')
        return method(dict(contracts.NEW_SOURCE) if pin is None else pin, architecture)

    def test_exact_source_intent_is_immutable_nonqualifying_metadata(self):
        value = self.intent()
        self.assertEqual((value.core, value.architecture, value.path, value.role),
            (contracts.NEW.core, 'x64', 'program/spsupp_x86.dll', 'x86CompatibilityHelper'))
        self.assertIs(value.qualifies_runtime, False)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            value.qualifies_runtime = True
        self.assertFalse(hasattr(value, 'sha256'))
        self.assertFalse(hasattr(value, 'size'))

    def test_other_cores_architectures_and_nonexact_source_metadata_fail(self):
        for architecture in ('arm64', 'x86', None, True):
            with self.subTest(architecture=architecture), self.assertRaises(ValueError):
                self.intent(architecture=architecture)
        for pin in (dict(contracts.LEGACY_SOURCE), dict(contracts.NEW_SOURCE, extra=False),
                dict(contracts.NEW_SOURCE, size=True), dict(contracts.NEW_SOURCE, sha256='0'*64),
                dict(contracts.NEW_SOURCE, version=contracts.LEGACY.version)):
            with self.subTest(fieldCount=len(pin)), self.assertRaises(ValueError):
                self.intent(pin)

    def test_twain_intent_is_separate_immutable_and_never_binary_authority(self):
        method = getattr(contracts, 'source_twain_intent', None)
        self.assertTrue(callable(method), 'Missing separate TWAIN source intent')
        value = method(dict(contracts.NEW_SOURCE), 'x64')
        self.assertEqual((value.core, value.architecture, value.path, value.role, value.kind, value.source_intent),
            (contracts.NEW.core, 'x64', 'program/twain32shim.exe', 'x86CompatibilityHelper',
             'source-built-x86-twain-companion', 'twain-32bit-driver-process-bridge'))
        self.assertIs(value.qualifies_runtime, False)
        self.assertNotEqual(type(value), type(self.intent()))
        self.assertFalse(hasattr(value, 'sha256')); self.assertFalse(hasattr(value, 'size'))
        with self.assertRaises((FrozenInstanceError, AttributeError)): value.path = 'program/other.exe'
        for pin, architecture in ((dict(contracts.LEGACY_SOURCE), 'x64'), (dict(contracts.NEW_SOURCE), 'arm64'),
                (dict(contracts.NEW_SOURCE, extra=False), 'x64'), (dict(contracts.NEW_SOURCE, size=True), 'x64')):
            with self.subTest(architecture=architecture), self.assertRaises(ValueError): method(pin, architecture)


if __name__ == '__main__': unittest.main()
