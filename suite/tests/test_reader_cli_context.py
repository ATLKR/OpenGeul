"""Caller context mapping and denied prelaunch checks; no source17 admission proof."""
import sys
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'suite/e2e')]
import windows_smoke as native
import korean_ime_smoke as ime


class ReaderCliContextTests(unittest.TestCase):
    def test_legacy_reader_options_remain_empty(self):
        self.assertEqual(native.source_reader_options(None, inventory_sha256='a'*64), {})

    def test_context_mapping_forwards_an_unsealed_sentinel_without_admitting_it(self):
        # An unsealed object is only a forwarding sentinel, never admitted here.
        sentinel = object()
        options = native.source_reader_options(sentinel, inventory_sha256='a'*64)
        self.assertEqual(set(options), {'source_admission', 'inventory_sha256'})
        self.assertIs(options['source_admission'], sentinel)
        self.assertEqual(options['inventory_sha256'], 'a'*64)

    def test_legacy_ime_does_not_attempt_source_admission(self):
        with patch('native_menu_source_admission.admit_source_menu_runtime', side_effect=AssertionError('unexpected admission')):
            self.assertIsNone(ime._admit_source_reader(Path('/synthetic/suite'), 'x64', None))

    def test_wrong_source_reader_architecture_is_rejected_before_admission(self):
        with patch('native_menu_source_admission.admit_source_menu_runtime', side_effect=AssertionError('unexpected admission')):
            with self.assertRaises(ValueError):
                ime._admit_source_reader(Path('/synthetic/suite'), 'x64', 'arm64')

    def test_source_reader_requires_the_real_factory_before_launch(self):
        # Deliberate factory rejection is not replaced with a fake Full receipt.
        with patch('native_menu_source_admission.admit_source_menu_runtime', side_effect=ValueError('Full source evidence absent')) as gate, \
             patch.object(ime.time, 'monotonic', return_value=10.):
            with self.assertRaisesRegex(ValueError, 'Full source evidence absent'):
                ime._admit_source_reader(Path('/synthetic/suite'), 'arm64', 'arm64')
        self.assertEqual(gate.call_count, 1)
        args, kwargs = gate.call_args
        self.assertEqual(args, (Path('/synthetic/suite'),))
        self.assertEqual(kwargs['architecture'], 'arm64')
        self.assertEqual(kwargs['deadline'], 160.)
        self.assertEqual(kwargs['engine_zip'].name, 'OpenGeul-Office-engine-arm64.zip')
        self.assertEqual(kwargs['receipt'].name, 'source-build-receipt.json')

    def test_verify_one_explicitly_rejects_reader_authority_without_admission_or_reopen(self):
        with tempfile.TemporaryDirectory() as name:
            suite = Path(name)
            (suite/'suite-inventory.json').write_text(json.dumps({'schemaVersion': 1, 'architecture': 'x64'}))
            # Native OS observations are outside this portable ordering test.
            with patch.object(ime, 'os', SimpleNamespace(name='nt')), \
                 patch.object(ime._payload_guard, '_reject_writer_observer'), \
                 patch.object(ime.native_arch, 'observe_native_architecture', return_value={}), \
                 patch.object(ime.native_arch, 'validate_native_architecture', return_value={}), \
                 patch('native_menu_source_admission.admit_source_menu_runtime', side_effect=ValueError('Full source evidence absent')) as gate, \
                 patch.object(ime, 'reopen_one', side_effect=AssertionError('unqualified engine started')) as reopen:
                with self.assertRaisesRegex(ValueError, 'Independent UNO reopen does not consume reader authority'):
                    ime.main(['--suite', str(suite), '--source-qualified-reader', 'x64',
                        '--verify-one', 'writer', '--file', str(suite/'owned.docx'),
                        '--reopen-output', str(suite/'reopened.json')])
            gate.assert_not_called()
            reopen.assert_not_called()

    def test_original_uno_reopen_keeps_its_existing_branch_without_reader_admission(self):
        with tempfile.TemporaryDirectory() as name:
            suite = Path(name)
            (suite/'suite-inventory.json').write_text(json.dumps({'schemaVersion': 1, 'architecture': 'x64'}))
            result = suite/'reopened.json'
            with patch.object(ime, 'os', SimpleNamespace(name='nt')), \
                 patch.object(ime._payload_guard, '_reject_writer_observer'), \
                 patch.object(ime.native_arch, 'observe_native_architecture', return_value={}), \
                 patch.object(ime.native_arch, 'validate_native_architecture', return_value={}), \
                 patch('native_menu_source_admission.admit_source_menu_runtime', side_effect=AssertionError('unexpected reader admission')) as gate, \
                 patch.object(ime, 'reopen_one', return_value={'syntheticControl': True}) as reopen:
                self.assertEqual(ime.main(['--suite', str(suite), '--verify-one', 'writer',
                    '--file', str(suite/'owned.docx'), '--reopen-output', str(result)]), 0)
            gate.assert_not_called()
            reopen.assert_called_once_with(suite.resolve(), (suite/'owned.docx').resolve(), 'writer')
            self.assertEqual(json.loads(result.read_text()), {'syntheticControl': True})

    def test_normal_source_reader_gate_rejects_missing_full_before_case_launch(self):
        with tempfile.TemporaryDirectory() as name:
            suite = Path(name)
            (suite/'suite-inventory.json').write_text(json.dumps({'schemaVersion': 1, 'architecture': 'x64'}))
            output = suite.parent/('uncreated-'+suite.name)
            with patch.object(ime, 'os', SimpleNamespace(name='nt')), \
                 patch.object(ime._payload_guard, '_reject_writer_observer'), \
                 patch.object(ime.native_arch, 'observe_native_architecture', return_value={}), \
                 patch.object(ime.native_arch, 'validate_native_architecture', return_value={}), \
                 patch('native_menu_source_admission.admit_source_menu_runtime', side_effect=ValueError('Full source evidence absent')) as gate, \
                 patch.object(ime, 'case', side_effect=AssertionError('unqualified case started')) as case:
                with self.assertRaisesRegex(ValueError, 'Full source evidence absent'):
                    ime.main(['--suite', str(suite), '--source-qualified-reader', 'x64',
                        '--fixtures', str(suite/'fixtures'), '--readiness', str(suite/'readiness.json'),
                        '--output', str(output)])
            self.assertEqual(gate.call_count, 1)
            case.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
