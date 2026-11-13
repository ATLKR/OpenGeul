"""Synthetic installed-tool capability discovery; no real environment or tools."""
import os
from unittest.mock import patch
import unittest

import test_native_clang_preparation as fixture


class InstalledNativeDiscoveryTests(unittest.TestCase):
    proof=fixture.base.PreparationTests.proof
    mutate=fixture.base.PreparationTests.mutate

    def setUp(self):
        # Existing fixture patch.dict calls must see only this synthetic mapping.
        isolated=patch.object(os,'environ',{'OBSERVER_PREPARATION_TEST':'1'})
        isolated.start();self.addCleanup(isolated.stop)
        fixture.NativeClangPreparationTests.setUp(self)
        self.native.update(nativeMachine=0xaa64,processArchitecture='arm64',nativeArchitecture='arm64')
        self.runtime.machine=0xaa64
        for path in self.bin.iterdir():path.write_bytes(fixture.executable(0xaa64))
        self.start=self.runtime.start

    def installed(self,**kwargs):
        return fixture.base.m.prepare_observer(self.output,architecture='arm64',
            compiler_mode='clang-lld',discovery_policy='installed-native',**kwargs)

    def test_capability_policy_discovers_supported_installation_without_component_metadata(self):
        def start(argv,folder):
            process=self.start(argv,folder)
            if process.index==0 and '-requires ' in (folder/'discover.cmd').read_text():
                (folder/'discovery.stdout').write_bytes(b'')
            return process
        self.runtime.start=start
        descriptor=self.installed();proof=self.proof()
        script=(self.output/'discover.cmd').read_text()
        self.assertIn(' -version "[17.0,19.0)" ',script)
        self.assertNotIn('-requires',script)
        self.assertEqual(proof['discoveryPolicy'],'installed-native')
        self.assertEqual(proof['compiler']['before'],proof['compiler']['after'])
        self.assertTrue(all(tool['machine']==0xaa64 for tool in proof['compiler']['before'].values()))
        self.assertEqual((proof['startedAt'],proof['workDeadline'],proof['deadline']),(100.,127.,130.))
        self.assertTrue(all(row['natural'] and row['handlesClosed'] for row in proof['stages']))
        self.assertEqual(fixture.base.m.require_prepared_library(descriptor,architecture='arm64'),self.output/'ascii-message-observer.dll')

    def test_default_component_policy_remains_unchanged(self):
        fixture.NativeClangPreparationTests.clang(self,'arm64')
        self.assertIn(' -requires Microsoft.VisualStudio.Component.VC.Tools.ARM64 ',(self.output/'discover.cmd').read_text())
        self.assertNotIn('discoveryPolicy',self.proof())

    def test_unknown_policy_and_msvc_capability_mode_start_no_process(self):
        for policy,compiler in (('unknown','clang-lld'),('installed-native','msvc')):
            with self.subTest(compiler=compiler),self.assertRaises(AssertionError):
                fixture.base.m.prepare_observer(self.output,architecture='arm64',compiler_mode=compiler,discovery_policy=policy)
        self.assertEqual(self.runtime.processes,[])
        self.assertFalse(self.output.exists())

    def test_missing_or_oversized_or_empty_decoded_installation_starts_no_compile(self):
        for index,raw in enumerate((b'',b'x'*32769,b' \r\n',b'first\nsecond\n')):
            self.output=self.root/('invalid-'+str(index))
            self.runtime.processes=[]
            def start(argv,folder):
                process=self.start(argv,folder)
                if process.index==0:(folder/'discovery.stdout').write_bytes(raw)
                return process
            self.runtime.start=start
            with self.subTest(case=index),self.assertRaises(AssertionError):self.installed()
            self.assertEqual(len(self.runtime.processes),1)
            self.assertTrue(self.runtime.processes[0].closed)

    def test_non_native_compiler_is_still_rejected_before_compile(self):
        (self.bin/'clang-cl.exe').write_bytes(fixture.executable(0x8664))
        with self.assertRaises(AssertionError):self.installed()
        self.assertEqual(len(self.runtime.processes),1)

    def test_wrong_output_machine_still_rejects_a_completed_compile(self):
        self.runtime.machine=0x8664
        with self.assertRaises(AssertionError):self.installed()
        self.assertEqual(len(self.runtime.processes),2)
        self.assertTrue(all(p.closed and not p.forced for p in self.runtime.processes))

    def test_prepared_validator_rejects_unrecognized_policy(self):
        descriptor=self.installed()
        self.mutate(descriptor,lambda proof:proof.update(discoveryPolicy='unrecognized'))
        with self.assertRaises(AssertionError):fixture.base.m.require_prepared_library(descriptor,architecture='arm64')


if __name__=='__main__':unittest.main()
