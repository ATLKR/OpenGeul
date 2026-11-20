"""Fixture isolation with synthetic-only environment values and hostile bulk access."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_ascii_message_preparation as base
import test_native_clang_preparation as clang


class SyntheticSentinelMapping(dict):
    """All values are fixed temporary fixture paths; bulk operations are forbidden."""
    GET_KEYS = ('ProgramFiles(x86)', 'ProgramFiles', 'COMSPEC')

    def __init__(self, fixed_paths):
        assert type(fixed_paths) is dict and set(fixed_paths) == set(self.GET_KEYS)
        assert all(type(value) is str and Path(value).is_absolute() for value in fixed_paths.values())
        dict.__init__(self, fixed_paths)
        self.bulkAttempts = 0
        self.getMask = 0
        self.unknownGets = 0

    def forbidden(self):
        self.bulkAttempts += 1
        raise AssertionError('Synthetic environment forbids bulk access')

    def copy(self): return self.forbidden()
    def __iter__(self): return self.forbidden()
    def items(self): return self.forbidden()
    def keys(self): return self.forbidden()

    def get(self, key, default=None):
        if type(key) is str and key in self.GET_KEYS:
            self.getMask |= 1 << self.GET_KEYS.index(key)
            return dict.get(self, key)
        self.unknownGets += 1
        return None


def sentinel(folder):
    return SyntheticSentinelMapping({'ProgramFiles(x86)':str(folder/'programs'),
        'ProgramFiles':str(folder/'Program Files'), 'COMSPEC':str(folder/'cmd.exe')})


@contextmanager
def synthetic_environment():
    # Explicit directory avoids tempfile's own environment lookup on every OS.
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
        outer = sentinel(Path(folder))
        with patch.object(tempfile, 'tempdir', folder), patch.object(os, 'environ', outer):
            yield outer


class SyntheticEnvironmentTests(unittest.TestCase):
    def test_base_fixture_replaces_mapping_without_copy_or_iteration(self):
        case = base.PreparationTests('test_success_requires_two_naturally_empty_jobs_and_pins_every_output')
        with synthetic_environment() as outer:
            try:
                case.setUp()
                self.assertIs(type(os.environ), dict)
                self.assertEqual(set(os.environ), {'ProgramFiles(x86)'})
                descriptor = case.prepare()
                self.assertEqual(base.m.require_prepared_library(descriptor), case.output/'ascii-message-observer.dll')
            finally:
                self.assertTrue(case.doCleanups())
            self.assertIs(os.environ, outer)
            self.assertEqual(outer.bulkAttempts, 0)
            self.assertEqual(outer.getMask, 0)
            self.assertEqual(outer.unknownGets, 0)

    def test_nested_clang_patch_copies_only_the_fixture_dictionary(self):
        case = clang.NativeClangPreparationTests('test_current_default_uses_native_llvm_and_original_natural_job_contract')
        with synthetic_environment() as outer:
            try:
                case.setUp()
                self.assertIs(type(os.environ), dict)
                self.assertEqual(set(os.environ), {'ProgramFiles(x86)', 'ProgramFiles'})
                descriptor = case.clang()
                self.assertEqual(base.m.require_prepared_library(descriptor), case.output/'ascii-message-observer.dll')
            finally:
                self.assertTrue(case.doCleanups())
            self.assertIs(os.environ, outer)
            self.assertEqual(outer.bulkAttempts, 0)
            self.assertEqual(outer.getMask, 0)
            self.assertEqual(outer.unknownGets, 0)

    def test_production_named_gets_work_while_all_bulk_operations_raise(self):
        probe = sentinel(Path(__file__).resolve().parent/'synthetic-guard-environment')
        for operation in (probe.copy, lambda: iter(probe), probe.items, probe.keys):
            with self.assertRaisesRegex(AssertionError, 'forbids bulk'): operation()
        self.assertEqual(probe.bulkAttempts, 4)
        self.assertIsNone(probe.get('SYNTHETIC_UNKNOWN', 'SYNTHETIC_DEFAULT'))
        case = base.PreparationTests('test_success_requires_two_naturally_empty_jobs_and_pins_every_output')
        with synthetic_environment() as outer:
            try:
                case.setUp()
                observed = sentinel(case.root)
                with patch.object(os, 'environ', observed):
                    descriptor = case.prepare()
                    self.assertEqual(base.m.require_prepared_library(descriptor), case.output/'ascii-message-observer.dll')
                    self.assertEqual(observed.getMask, 5)  # Only ProgramFiles(x86) and COMSPEC.
                    self.assertEqual(observed.unknownGets, 0)
                    self.assertEqual(observed.bulkAttempts, 0)
            finally:
                self.assertTrue(case.doCleanups())
            self.assertIs(os.environ, outer)
            self.assertEqual(outer.bulkAttempts, 0)
            self.assertEqual(outer.getMask, 0)
            self.assertEqual(outer.unknownGets, 0)


if __name__ == '__main__': unittest.main()
