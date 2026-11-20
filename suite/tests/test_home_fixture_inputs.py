"""Owned producer boundary tests; fake process I/O is not Windows HWP proof."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/home_fixture_inputs.py'
REJECTED = (AssertionError, ValueError, OSError, KeyError, TypeError)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pe_image(machine=0x8664):
    value = bytearray(512)
    value[:2] = b'MZ'
    struct.pack_into('<I', value, 0x3c, 128)
    value[128:132] = b'PE\0\0'
    struct.pack_into('<H', value, 132, machine)
    return bytes(value)


def cfb_image():
    # Synthetic format-boundary bytes, not a real HWP content/Windows oracle.
    value = bytearray(1536)
    value[:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<HHHH', value, 24, 0x3e, 3, 0xfffe, 9)
    struct.pack_into('<H', value, 32, 6)
    struct.pack_into('<I', value, 48, 0)
    return bytes(value)


class HomeFixtureInputTests(unittest.TestCase):
    def api(self):
        if hasattr(self, '_module'): return self._module
        self.assertTrue(SOURCE.is_file(), 'RED: approved owned HWP fixture producer is absent')
        spec = importlib.util.spec_from_file_location('home_fixture_inputs_under_test', SOURCE)
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
        self._module = api
        return api

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.suite = self.root / 'package'
        self.tool = self.suite / 'HWP/Tools/rhwp.exe'
        self.tool.parent.mkdir(parents=True)
        self.tool.write_bytes(pe_image())
        self.inventory = {'schemaVersion': 1, 'architecture': 'x64', 'files': {
            'HWP/Tools/rhwp.exe': {'size': self.tool.stat().st_size, 'sha256': sha(self.tool)}}}
        (self.suite / 'suite-inventory.json').write_text(json.dumps(self.inventory))
        self.output = self.root / 'e2e-fixtures'
        self.calls = []
        self.api()

    def boundary(self, *, failure=None, change=None):
        def run(argv, *, cwd, stdin, stdout, stderr, timeout, check, shell):
            self.calls.append(list(argv))
            self.assertEqual(str(self.tool), argv[0])
            self.assertEqual(['--verify', '--json'], argv[-2:])
            self.assertEqual(str(self.output), str(cwd))
            self.assertEqual(subprocess.DEVNULL, stdin)
            self.assertEqual(60, timeout)
            self.assertIs(check, False)
            self.assertIs(shell, False)
            command, source, target = argv[1], Path(argv[2]), Path(argv[3])
            self.assertTrue(source.is_file())
            self.assertFalse(target.exists())
            stderr.write(b'owned cli diagnostic\n')
            if failure == 'timeout':
                raise subprocess.TimeoutExpired(argv, timeout)
            if failure == 'exit':
                stdout.write(b'{"error":"conversion failed"}')
                return subprocess.CompletedProcess(argv, 9)
            if command == 'convert':
                target.write_bytes(b'PK\x03\x04renamed zip' if change == 'zip-hwp' else cfb_image())
                fmt = 'hwp5'
            else:
                with zipfile.ZipFile(self.output / 'basic.hwpx') as z, zipfile.ZipFile(target, 'x') as out:
                    for item in z.infolist():
                        raw = z.read(item.filename)
                        if change == 'lost-marker' and item.filename == 'Contents/section0.xml':
                            raw = raw.replace(b'Suite-HWPX-route-', b'foreign-')
                        out.writestr(item, raw)
                fmt = 'hwpx'
            value = {'schemaVersion': '1.0', 'source': str(source), 'output': str(target),
                     'format': fmt, 'bytes': target.stat().st_size,
                     'verify': {'identical': True, 'diffCount': 0}}
            if command == 'convert' and change in ('wrong-output', 'wrong-format', 'wrong-size', 'unverified'):
                if change == 'wrong-output': value['output'] = str(self.root / 'foreign.hwp')
                if change == 'wrong-format': value['format'] = 'hwpx'
                if change == 'wrong-size': value['bytes'] += 1
                if change == 'unverified': value['verify']['identical'] = False
            raw = json.dumps(value).encode()
            if change == 'duplicate-json' and command == 'convert':
                raw = b'{"schemaVersion":"1.0",' + raw[1:]
            stdout.write(raw)
            return subprocess.CompletedProcess(argv, 0)
        return run

    def produce(self, **options):
        api = self.api()
        with mock.patch.object(api.subprocess, 'run', side_effect=self.boundary(**options)):
            proof = api.produce_hwp_fixtures(self.suite, self.output)
        return api, proof

    def test_owned_constructor_exact_packaged_two_command_chain_and_replay(self):
        api, proof = self.produce()
        self.assertEqual(2, len(self.calls))
        self.assertEqual(['convert', 'export-hwpx'], [c[1] for c in self.calls])
        self.assertEqual({'hwp', 'hwpx', 'roundtrip'}, set(proof['files']))
        self.assertEqual('owned-home-hwp-fixtures', proof['kind'])
        self.assertIs(proof['success'], True)
        self.assertEqual(sha(self.tool), proof['tool']['sha256'])
        self.assertEqual(sha(self.suite / 'suite-inventory.json'), proof['inventory']['sha256'])
        self.assertEqual((self.output / 'provenance.json').read_text(), json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
        paths = api.require_hwp_fixture_provenance(proof, self.suite, self.output)
        self.assertEqual({'hwp': self.output/'basic.hwp', 'hwpx': self.output/'basic.hwpx',
                          'roundtrip': self.output/'roundtrip.hwpx'}, paths)
        self.assertEqual(proof['validation']['inputXml'], proof['validation']['roundtripXml'])
        for row in proof['commands']:
            self.assertEqual(row['startedAt'] + 60, row['deadline'])
            self.assertLessEqual(row['finishedAt'], row['deadline'])
            self.assertEqual(row['inputBeforeSha256'], row['inputAfterSha256'])
            self.assertEqual(0, row['exitCode'])

    def test_replay_is_read_only_and_never_executes_cli(self):
        api, proof = self.produce()
        before = {p.name: sha(p) for p in self.output.iterdir()}
        with mock.patch.object(api.subprocess, 'run', side_effect=AssertionError('No replay execution')):
            api.require_hwp_fixture_provenance(proof, self.suite, self.output)
        self.assertEqual(before, {p.name: sha(p) for p in self.output.iterdir()})

    def test_unrelated_or_wrong_architecture_cli_is_rejected_before_output(self):
        for change in ('changed', 'unrelated', 'architecture'):
            with self.subTest(change=change):
                self.output = self.root / ('fresh-' + change)
                self.tool.write_bytes(pe_image())
                if change == 'changed': self.tool.write_bytes(pe_image() + b'foreign')
                elif change == 'unrelated': self.tool.write_bytes(b'not an executable')
                else:
                    self.tool.write_bytes(pe_image(0xaa64))
                    value = copy.deepcopy(self.inventory)
                    value['files']['HWP/Tools/rhwp.exe'] = {'size': self.tool.stat().st_size, 'sha256': sha(self.tool)}
                    (self.suite/'suite-inventory.json').write_text(json.dumps(value))
                api = self.api()
                with mock.patch.object(api.subprocess, 'run', side_effect=AssertionError('No CLI on bad input')):
                    with self.assertRaises(REJECTED): api.produce_hwp_fixtures(self.suite, self.output)
                self.assertFalse(self.output.exists())

    def test_existing_namespace_is_never_reused_or_overwritten(self):
        api = self.api()
        self.output.mkdir(); owned = self.output/'keep.txt';owned.write_text('original')
        with self.assertRaises(REJECTED): api.produce_hwp_fixtures(self.suite, self.output)
        self.assertEqual('original', owned.read_text())

    def test_payload_nested_output_and_linked_parent_are_rejected(self):
        api = self.api()
        for target in (self.suite/'fixtures', self.root/'alias/fixtures'):
            if target.parent.name == 'alias': target.parent.symlink_to(self.root, target_is_directory=True)
            with self.subTest(target=target):
                with self.assertRaises(REJECTED): api.produce_hwp_fixtures(self.suite, target)
                self.assertFalse(target.exists())

    def test_linked_packaged_cli_rejected_before_process_or_namespace(self):
        api = self.api(); original=self.root/'real.exe';self.tool.replace(original);self.tool.symlink_to(original)
        with self.assertRaises(REJECTED): api.produce_hwp_fixtures(self.suite, self.output)
        self.assertFalse(self.output.exists())

    def test_failed_and_timed_out_commands_retain_logs_and_never_qualify(self):
        for failure in ('exit', 'timeout'):
            with self.subTest(failure=failure):
                self.output = self.root/('failure-' + failure)
                api = self.api()
                with mock.patch.object(api.subprocess, 'run', side_effect=self.boundary(failure=failure)):
                    with self.assertRaises(REJECTED): api.produce_hwp_fixtures(self.suite, self.output)
                proof=json.loads((self.output/'provenance.json').read_text())
                self.assertIs(proof['success'], False)
                self.assertTrue((self.output/'convert.stderr.log').is_file())
                self.assertEqual(1,len(proof['commands']))
                with self.assertRaises(REJECTED): api.require_hwp_fixture_provenance(proof,self.suite,self.output)

    def test_wrong_cli_envelope_and_duplicate_json_are_not_success(self):
        for change in ('wrong-output','wrong-format','wrong-size','unverified','duplicate-json'):
            with self.subTest(change=change):
                self.output=self.root/change
                with self.assertRaises(REJECTED): self.produce(change=change)
                proof=json.loads((self.output/'provenance.json').read_text())
                self.assertIs(proof['success'],False)
                self.assertEqual(1,len(proof['commands']))

    def test_fake_zip_hwp_and_roundtrip_body_loss_are_rejected(self):
        for change in ('zip-hwp','lost-marker'):
            with self.subTest(change=change):
                self.output=self.root/change
                with self.assertRaises(REJECTED): self.produce(change=change)
                self.assertIs(json.loads((self.output/'provenance.json').read_text())['success'],False)

    def test_proof_foreign_paths_tool_hash_argv_and_source_hash_are_rejected(self):
        api, proof=self.produce()
        for change in ('argv','tool','fixture-root','suite-root','file-path','source'):
            value=copy.deepcopy(proof)
            if change=='argv': value['commands'][0]['argv'][0]=str(self.root/'foreign.exe')
            elif change=='tool': value['tool']['sha256']='a'*64
            elif change=='fixture-root': value['fixtureRoot']=str(self.root/'foreign')
            elif change=='suite-root': value['suiteRoot']=str(self.root/'foreign')
            elif change=='file-path': value['files']['hwp']['path']='../basic.hwp'
            else: value['sources']['constructor']['sha256']='b'*64
            with self.subTest(change=change), self.assertRaises(REJECTED):
                api.require_hwp_fixture_provenance(value,self.suite,self.output)

    def test_log_or_output_byte_changes_reject_even_with_success_flag(self):
        api,proof=self.produce()
        for filename in ('basic.hwp','basic.hwpx','roundtrip.hwpx','convert.stdout.json','convert.stderr.log'):
            path=self.output/filename;original=path.read_bytes();path.write_bytes(original+b'changed')
            with self.subTest(filename=filename),self.assertRaises(REJECTED):
                api.require_hwp_fixture_provenance(proof,self.suite,self.output)
            path.write_bytes(original)

    def test_forged_deadline_or_input_identity_is_rejected(self):
        api,proof=self.produce()
        for field,value in (('deadline',proof['commands'][0]['startedAt']+600),('finishedAt',proof['commands'][0]['deadline']+1),('inputAfterSha256','c'*64),('exitCode',1)):
            changed=copy.deepcopy(proof);changed['commands'][0][field]=value
            with self.subTest(field=field),self.assertRaises(REJECTED):api.require_hwp_fixture_provenance(changed,self.suite,self.output)

    def test_linked_fixture_and_unlisted_outputs_fail_owned_namespace(self):
        api,proof=self.produce();extra=self.output/'unexpected';extra.write_text('extra')
        with self.assertRaises(REJECTED):api.require_hwp_fixture_provenance(proof,self.suite,self.output)
        extra.unlink();target=self.output/'basic.hwp';saved=self.root/'moved.hwp';target.replace(saved);target.symlink_to(saved)
        with self.assertRaises(REJECTED):api.require_hwp_fixture_provenance(proof,self.suite,self.output)

    def test_optimized_cli_rejects_before_creating_output(self):
        self.api()
        result=subprocess.run([sys.executable,'-O',str(SOURCE),'--suite',str(self.suite),'--output',str(self.output)],capture_output=True)
        self.assertNotEqual(0,result.returncode)
        self.assertFalse(self.output.exists())


if __name__=='__main__':unittest.main()
