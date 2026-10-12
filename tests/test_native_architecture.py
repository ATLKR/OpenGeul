"""실제 PE 바이트와 Windows process 관측의 잘못된 결합을 거부한다."""
import importlib.util
import os
from pathlib import Path
import struct
import tempfile
import unittest
import json

ROOT = Path(__file__).resolve().parents[1]


class Probe:
    def __init__(self, executable, *, native=0xAA64, process=0):
        self.executable = executable
        self.native = native
        self.process = process
        self.change = {}
        self.calls = []

    def inspect(self, pid, handle=None):
        self.calls.append((pid, handle))
        value = {'processId': pid, 'imagePath': str(self.executable),
                 'processMachine': self.process, 'nativeMachine': self.native,
                 'exitCode': 259, 'packageFullName': None}
        if pid == os.getpid():
            value['processMachine'] = 0x8664 if self.native == 0xAA64 else 0
        else:
            value.update(self.change)
        return value


class NativeArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.exe = self.folder/'OpenGeul.exe'
        self.pe(self.exe, 0xAA64)

    def pe(self, path, machine):
        raw = bytearray(256);raw[:2] = b'MZ';struct.pack_into('<I', raw, 60, 128)
        raw[128:132] = b'PE\0\0';struct.pack_into('<H', raw, 132, machine)
        path.write_bytes(raw)

    def module(self):
        path = ROOT/'e2e/native_architecture.py'
        self.assertTrue(path.is_file(), '생산 harness에 native PID/PE 검증이 필요합니다')
        spec = importlib.util.spec_from_file_location('native_architecture_tested', path)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_native_arm64_binds_owned_pid_file_and_architecture_while_tracking_emulated_controller(self):
        module = self.module();probe = Probe(self.exe)
        proof = module.verify_process(1234, self.exe, 'arm64', handle=9876, probe=probe)
        self.assertEqual(proof['processId'], 1234)
        self.assertEqual(proof['architecture'], 'arm64')
        self.assertEqual(proof['peMachine'], 0xAA64)
        self.assertEqual(proof['processMachine'], 0)
        self.assertEqual(proof['nativeMachine'], 0xAA64)
        self.assertTrue(proof['native'])
        self.assertEqual(proof['controller']['architecture'], 'x64-emulated')
        self.assertIn((1234, 9876), probe.calls)

    def test_x64_native_remains_supported(self):
        module = self.module();self.pe(self.exe, 0x8664)
        proof = module.verify_process(1234, self.exe, 'x64', probe=Probe(self.exe, native=0x8664))
        self.assertEqual(proof['peMachine'], 0x8664)
        self.assertEqual(proof['nativeMachine'], 0x8664)
        self.assertTrue(proof['native'])

    def test_mislabeled_x64_and_hybrid_pe_fail_before_any_process_query(self):
        module = self.module()
        for machine in (0x8664, 0xA641, 0xA64E):
            with self.subTest(machine=machine):
                self.pe(self.exe, machine);probe = Probe(self.exe)
                with self.assertRaises(ValueError):
                    module.verify_process(1234, self.exe, 'arm64', probe=probe)
                self.assertEqual(probe.calls, [])

    def test_wrong_owned_pid_or_other_executable_is_rejected_even_with_identical_bytes(self):
        module = self.module();other = self.folder/'other.exe';other.write_bytes(self.exe.read_bytes())
        for change in ({'processId': 9999}, {'imagePath': str(other)}):
            with self.subTest(change=change):
                probe = Probe(self.exe);probe.change = change
                with self.assertRaises(ValueError):
                    module.verify_process(1234, self.exe, 'arm64', probe=probe)

    def test_emulated_product_or_wrong_host_cannot_be_native(self):
        module = self.module()
        for change in ({'processMachine': 0x8664}, {'processMachine': 0xA641},
                       {'processMachine': False}, {'nativeMachine': 0x8664},
                       {'nativeMachine': True}):
            with self.subTest(change=change):
                probe = Probe(self.exe);probe.change = change
                with self.assertRaises(ValueError):
                    module.verify_process(1234, self.exe, 'arm64', probe=probe)

    def test_invalid_architecture_pid_and_symlink_are_rejected_before_query(self):
        module = self.module()
        for arch, pid in (('ARM64', 1234), ('arm64ec', 1234), ('arm64', True), ('arm64', 0)):
            with self.subTest(arch=arch, pid=pid):
                probe = Probe(self.exe)
                with self.assertRaises(ValueError):module.verify_process(pid, self.exe, arch, probe=probe)
                self.assertEqual(probe.calls, [])
        link = self.folder/'link.exe';link.symlink_to(self.exe)
        with self.assertRaises(ValueError):module.verify_process(1234, link, 'arm64', probe=Probe(self.exe))

    def test_package_identity_is_bound_to_the_actual_product_process(self):
        module = self.module();probe = Probe(self.exe)
        probe.change['packageFullName'] = 'foreign_package'
        with self.assertRaises(ValueError):
            module.verify_process(1234, self.exe, 'arm64', package_full_name='owned_package', probe=probe)
        probe.change['packageFullName'] = 'owned_package'
        proof = module.verify_process(1234, self.exe, 'arm64', package_full_name='owned_package', probe=probe)
        self.assertEqual(proof['packageFullName'], 'owned_package')

    def test_host_inspection_tracks_controller_without_claiming_it_as_product(self):
        module = self.module();proof = module.verify_host('arm64', probe=Probe(self.exe))
        self.assertEqual(proof['architecture'], 'arm64')
        self.assertEqual(proof['controller']['architecture'], 'x64-emulated')
        self.assertFalse(proof['controller']['native'])
        with self.assertRaises(ValueError):module.verify_host('arm64', probe=Probe(self.exe, native=0x8664))

    def cli_process(self, *, code=0, output=b'Usage: rhwp [OPTIONS]\n'):
        class Child:
            pid = 1234
            _handle = 9876
            returncode = None
            killed = False
            def poll(inner):return inner.returncode
            def communicate(inner, timeout):inner.returncode = code;return output, None
            def kill(inner):inner.killed = True;inner.returncode = -9
            def wait(inner, timeout):return inner.returncode
        return Child()

    def test_cli_proof_uses_its_own_pid_and_package_identity_before_publishing_output(self):
        module = self.module();self.assertTrue(hasattr(module, 'run_cli'), 'CLI 실제 PID 검사 경로가 필요합니다')
        child = self.cli_process();commands = []
        def factory(arguments, **kwargs):
            self.assertEqual(kwargs.get('stdin'), module.subprocess.DEVNULL, '분리된 package probe의 입력 handle을 상속하면 안 됩니다')
            commands.append(arguments);return child
        probe = Probe(self.exe);probe.change['packageFullName'] = 'owned_package'
        output, help_output = self.folder/'cli.json', self.folder/'help.txt'
        proof = module.run_cli(self.exe, 'arm64', output, help_output,
                               package_full_name='owned_package', probe=probe, process_factory=factory)
        self.assertEqual(commands, [[str(self.exe), '--help']])
        self.assertEqual(proof['nativeArchitecture']['processId'], child.pid)
        self.assertEqual(proof['nativeArchitecture']['packageFullName'], 'owned_package')
        self.assertEqual(proof['exitCode'], 0)
        self.assertTrue(proof['success'])
        self.assertEqual(json.loads(output.read_text()), proof)
        self.assertEqual(help_output.read_text(), 'Usage: rhwp [OPTIONS]\n')

    def test_wrong_cli_pid_terminates_only_its_child_and_publishes_no_receipt(self):
        module = self.module();self.assertTrue(hasattr(module, 'run_cli'), 'CLI 실제 PID 검사 경로가 필요합니다')
        child = self.cli_process();probe = Probe(self.exe);probe.change['processId'] = 9999
        with self.assertRaises(ValueError):
            module.run_cli(self.exe, 'arm64', self.folder/'cli.json', self.folder/'help.txt',
                           probe=probe, process_factory=lambda *args, **kwargs:child)
        self.assertTrue(child.killed)
        self.assertFalse((self.folder/'cli.json').exists())
        self.assertFalse((self.folder/'help.txt').exists())

    def test_nonzero_or_oversized_cli_output_never_publishes_a_success_receipt(self):
        module = self.module();self.assertTrue(hasattr(module, 'run_cli'), 'CLI 실제 PID 검사 경로가 필요합니다')
        for code, data in ((1, b'Usage: rhwp'), (0, b'Usage: rhwp'+b'x'*(1024*1024))):
            with self.subTest(code=code, bytes=len(data)):
                child = self.cli_process(code=code, output=data)
                with self.assertRaises(ValueError):
                    module.run_cli(self.exe, 'arm64', self.folder/'cli.json', self.folder/'help.txt',
                                   probe=Probe(self.exe), process_factory=lambda *args, **kwargs:child)
                self.assertFalse((self.folder/'cli.json').exists())
                self.assertFalse((self.folder/'help.txt').exists())

    def test_bad_cli_architecture_or_existing_evidence_blocks_launch(self):
        module = self.module();self.assertTrue(hasattr(module, 'run_cli'), 'CLI 실제 PID 검사 경로가 필요합니다')
        factory = lambda *args, **kwargs:self.fail('검증 전에 제품을 실행하면 안 됩니다')
        self.pe(self.exe, 0x8664)
        with self.assertRaises(ValueError):
            module.run_cli(self.exe, 'arm64', self.folder/'cli.json', self.folder/'help.txt', process_factory=factory)
        self.pe(self.exe, 0xAA64)
        with self.assertRaises(ValueError):
            module.run_cli(self.exe, 'arm64', self.folder/'cli.json', self.folder/'help.txt',
                           probe=Probe(self.exe, native=0x8664), process_factory=factory)
        self.pe(self.exe, 0xAA64);(self.folder/'cli.json').write_text('preserved')
        with self.assertRaises(ValueError):
            module.run_cli(self.exe, 'arm64', self.folder/'cli.json', self.folder/'help.txt', process_factory=factory)
        self.assertEqual((self.folder/'cli.json').read_text(), 'preserved')

    def webview_probe(self):
        path = self.folder/'msedgewebview2.exe';self.pe(path, 0xAA64)
        probe = Probe(path)
        probe.processes = lambda:[
            {'processId': 1234, 'parentProcessId': 10, 'executableName': 'OpenGeul.exe'},
            {'processId': 2000, 'parentProcessId': 1234, 'executableName': 'msedgewebview2.exe'},
            {'processId': 2001, 'parentProcessId': 2000, 'executableName': 'msedgewebview2.exe'},
            {'processId': 9999, 'parentProcessId': 9000, 'executableName': 'msedgewebview2.exe'}]
        return probe, path

    def test_only_owned_webview_descendants_are_inspected_and_bound_to_native_arm64(self):
        module = self.module();self.assertTrue(hasattr(module, 'verify_webview2'), '소유한 실제 WebView2 process 검사가 필요합니다')
        probe, path = self.webview_probe()
        proof = module.verify_webview2(1234, 'arm64', probe=probe)
        self.assertEqual([p['processId'] for p in proof['processes']], [2000, 2001])
        self.assertEqual([p['parentProcessId'] for p in proof['processes']], [1234, 2000])
        self.assertEqual({p['peMachine'] for p in proof['processes']}, {0xAA64})
        self.assertEqual({p['processMachine'] for p in proof['processes']}, {0})
        self.assertNotIn(9999, [p for p, _ in probe.calls])

    def test_missing_or_emulated_owned_webview_cannot_qualify_native_gui(self):
        module = self.module();self.assertTrue(hasattr(module, 'verify_webview2'), '소유한 실제 WebView2 process 검사가 필요합니다')
        probe, path = self.webview_probe();self.pe(path, 0x8664)
        with self.assertRaises(ValueError):module.verify_webview2(1234, 'arm64', probe=probe)
        self.pe(path, 0xAA64);probe.change['processMachine'] = 0x8664
        with self.assertRaises(ValueError):module.verify_webview2(1234, 'arm64', probe=probe)
        probe.processes = lambda:[{'processId': 9999, 'parentProcessId': 9000, 'executableName': 'msedgewebview2.exe'}]
        probe.calls.clear()
        with self.assertRaises(ValueError):module.verify_webview2(1234, 'arm64', probe=probe)
        self.assertNotIn(9999, [p for p, _ in probe.calls])

    def test_webview_actual_image_name_and_unique_snapshot_ids_are_required(self):
        module = self.module();self.assertTrue(hasattr(module, 'verify_webview2'), '소유한 실제 WebView2 process 검사가 필요합니다')
        probe, path = self.webview_probe();probe.executable = self.exe
        with self.assertRaises(ValueError):module.verify_webview2(1234, 'arm64', probe=probe)
        probe, path = self.webview_probe();records = probe.processes();probe.processes = lambda:records+[records[1]]
        with self.assertRaises(ValueError):module.verify_webview2(1234, 'arm64', probe=probe)

    def test_oversized_cli_is_rejected_before_launch(self):
        module = self.module()
        with self.exe.open('r+b') as stream:stream.truncate(96*1024*1024+1)
        with self.assertRaises(ValueError):
            module.run_cli(self.exe, 'arm64', self.folder/'cli.json', self.folder/'help.txt',
                           process_factory=lambda *args, **kwargs:self.fail('초과한 파일을 실행하면 안 됩니다'))


if __name__ == '__main__':unittest.main()
