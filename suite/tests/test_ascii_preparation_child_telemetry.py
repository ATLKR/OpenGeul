"""Scope the supported DevShell switch to the generated compiler child only.

Portable preparation policy runs against native-boundary fakes. These tests do
not establish that the switch prevents the observed vctip process on Windows.
"""
import os
import unittest
from unittest.mock import patch

import test_ascii_message_preparation as base


class ChildTelemetryScopeTests(unittest.TestCase):
    setUp = base.PreparationTests.setUp
    prepare = base.PreparationTests.prepare
    proof = base.PreparationTests.proof

    def require_child_script(self, architecture):
        script = (self.output / 'compile.cmd').read_text(encoding='ascii')
        lines = script.splitlines()
        self.assertEqual(lines[0], '@echo off')
        self.assertEqual(lines[1], 'set "VSCMD_SKIP_SENDTELEMETRY=1"')
        self.assertEqual(lines[2], 'call "%~1" ' + architecture + ' >"%~2" 2>&1')
        self.assertEqual(script.count('VSCMD_SKIP_SENDTELEMETRY'), 1)
        self.assertNotIn('VSCMD_SKIP_SENDTELEMETRY', (self.output / 'discover.cmd').read_text())
        self.assertNotIn('setx', script.casefold())
        self.assertNotIn('reg.exe', script.casefold())

    def test_x64_compiler_sets_supported_switch_only_inside_child_script(self):
        with patch.dict(os.environ, {'VSCMD_SKIP_SENDTELEMETRY': 'parent-original'}):
            before = dict(os.environ)
            descriptor = self.prepare()
            self.require_child_script('x64')
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(base.m.require_prepared_library(descriptor), self.output / 'ascii-message-observer.dll')
        self.assertTrue(all(row['natural'] for row in self.proof()['stages']))

    def test_arm64_compiler_uses_same_scoped_switch_without_parent_setting(self):
        self.native.update(nativeMachine=0xaa64, processArchitecture='arm64', nativeArchitecture='arm64')
        self.runtime.machine = 0xaa64
        with patch.dict(os.environ):
            os.environ.pop('VSCMD_SKIP_SENDTELEMETRY', None)
            before = dict(os.environ)
            self.prepare('arm64')
            self.require_child_script('arm64')
            self.assertEqual(dict(os.environ), before)
            self.assertNotIn('VSCMD_SKIP_SENDTELEMETRY', os.environ)

    def test_child_switch_does_not_waive_live_job_or_change_timeout_cleanup(self):
        self.runtime.states[1] = [(0, 1, 0)]
        with patch.dict(os.environ, {'VSCMD_SKIP_SENDTELEMETRY': 'parent-original'}):
            before = dict(os.environ)
            with self.assertRaisesRegex(AssertionError, 'Observer preparation deadline expired'):
                self.prepare()
            self.require_child_script('x64')
            self.assertEqual(dict(os.environ), before)
        proof = self.proof()
        self.assertEqual((proof['startedAt'], proof['workDeadline'], proof['deadline']), (100., 127., 130.))
        self.assertFalse(proof['success'])
        self.assertFalse(proof['stages'][1]['natural'])
        self.assertTrue(proof['stages'][1]['forcedOwnedJobCleanup'])
        self.assertEqual(proof['stages'][1]['samples'][-1]['activeProcesses'], 1)
        self.assertEqual(proof['stages'][1]['cleanupLastSample']['activeProcesses'], 0)
        self.assertTrue(all(process.closed for process in self.runtime.processes))


if __name__ == '__main__':
    unittest.main()
