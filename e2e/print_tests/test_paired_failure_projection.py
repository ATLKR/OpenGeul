"""Closed failure context only; never query files after an exception."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import paired_print_run as api
import paired_print_windows as windows
from paired_print_contract import Rejected


class PairedFailureProjectionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(api, 'project_failure', None)), 'closed failure projector absent')

    def font_failure(self):
        import ctypes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fonts = root / 'Fonts'
            fonts.mkdir()
            original = fonts / 'arial.ttf'
            original.write_bytes(b'SYNTHETIC-FONT-BYTES')
            os.link(original, root / 'alias')
            os.link(original, root / 'second-alias')
            class Getter:
                def __call__(self, buffer, cap):
                    buffer.value = str(root)
                    return len(str(root))
            kernel = types.SimpleNamespace(GetSystemWindowsDirectoryW=Getter())
            with mock.patch.object(ctypes, 'WinDLL', return_value=kernel, create=True):
                try: windows.sampled_fonts()
                except Rejected as error: return error
            self.fail('the unsupported font link count did not reject')

    def test_actual_three_link_font_failure_preserves_existing_stat_and_closed_font_role(self):
        error = self.font_failure()
        with mock.patch.object(Path, 'stat', side_effect=AssertionError()), \
             mock.patch.object(Path, 'lstat', side_effect=AssertionError()), \
             mock.patch.object(Path, 'open', side_effect=AssertionError()):
            result = api.project_failure(error)
        self.assertEqual(result['errorCode'], 20)
        self.assertEqual(result['stageCode'], 6)
        self.assertEqual(result['fontCode'], 1)
        self.assertEqual(result['fileSize'], len(b'SYNTHETIC-FONT-BYTES'))
        self.assertEqual(result['linkCount'], 3)
        self.assertTrue(result['fileSizeKnown'])
        self.assertTrue(result['linkCountKnown'])
        self.assertNotIn('SYNTHETIC', json.dumps(result))
        self.assertNotIn('arial', json.dumps(result))

    def test_foreign_error_text_and_source_paths_are_never_output(self):
        try: raise ValueError('SYNTHETIC-PRIVATE-NEVER-OUTPUT')
        except ValueError as error: result = api.project_failure(error)
        self.assertEqual(result['frames'], [])
        self.assertEqual(result['exceptionCode'], 2)
        self.assertNotIn('SYNTHETIC', json.dumps(result))
        self.assertNotIn('/', json.dumps(result))

    def test_known_owned_source_function_and_line_have_integer_codes(self):
        try: api.run(types.SimpleNamespace(run_paired_print=False))
        except Rejected as error: result = api.project_failure(error)
        self.assertEqual(result['stageCode'], 1)
        self.assertTrue(any(r['fileCode'] == 1 and r['functionCode'] == 1 for r in result['frames']))
        self.assertTrue(all(type(r['line']) is int and 1 <= r['line'] <= 20000 for r in result['frames']))

    def test_unknown_boolean_or_out_of_range_metadata_cannot_become_numeric_context(self):
        error = Rejected(20)
        error.code = True
        error.pairedRole = True
        error.pairedFontCode = 99
        error.pairedFileStats = (True, True)
        result = api.project_failure(error)
        self.assertEqual(result['errorCode'], 0)
        self.assertEqual(result['knownRole'], 0)
        self.assertEqual(result['fontCode'], 0)
        self.assertFalse(result['fileSizeKnown'])
        self.assertFalse(result['linkCountKnown'])

    def test_exception_args_repr_and_unrelated_attributes_are_not_read(self):
        class Error(ValueError):
            def __getattribute__(self, name):
                if name in ('args', 'secret', '__str__', '__repr__'):
                    raise AssertionError()
                return super().__getattribute__(name)
        error = Error('SYNTHETIC-PRIVATE')
        error.secret = object()
        result = api.project_failure(error)
        self.assertEqual(result['exceptionCode'], 0)
        self.assertNotIn('SYNTHETIC', json.dumps(result))

    def main_args(self):
        result = ['paired_print_run.py']
        for name in ('legacy-cache', 'legacy-runtime', 'current-runtime', 'package', 'wasm', 'inputs', 'fixtures', 'work', 'output'):
            result += ['--' + name, 'synthetic-only']
        return result + ['--current-provenance-sha256', 'a' * 64, '--harness-source', 'b' * 40,
                         '--run-id', '17', '--run-attempt', '1']

    def test_main_uses_only_the_closed_projection_for_failure_stdout(self):
        error = self.font_failure()
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', self.main_args()), mock.patch.object(api, 'run', side_effect=error), \
             mock.patch.object(sys, 'stdout', output):
            code = api.main()
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['fontCode'], 1)
        self.assertFalse(result['completed'])
        self.assertFalse(result['qualification'])

    def test_projection_cancellation_cannot_replace_original_failure_or_exit_status(self):
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', self.main_args()), \
             mock.patch.object(api, 'run', side_effect=Rejected(20)), \
             mock.patch.object(api, 'project_failure', side_effect=KeyboardInterrupt()), \
             mock.patch.object(sys, 'stdout', output):
            self.assertEqual(api.main(), 1)
        self.assertFalse(json.loads(output.getvalue())['completed'])

    def test_stat_observation_cancellation_preserves_the_existing_guard_failure(self):
        import stat
        class Info:
            st_mode = stat.S_IFREG
            st_file_attributes = 0
            st_nlink = 2
            @property
            def st_size(self): raise KeyboardInterrupt()
        caught = None
        try: windows._safe(Info())
        except BaseException as error: caught = error
        self.assertIs(type(caught), Rejected)
        self.assertEqual(caught.code, 20)

    def census_record(self):
        return {'schemaVersion': 1, 'diagnosticOnly': True, 'acceptanceEligible': False,
            'rootPid': 1, 'originalRootCreationFileTime': 101, 'sealed': True, 'requireLiveRoot': True,
            'snapshotCount': 5, 'knownCount': 4, 'guardUnexpectedCount': 1,
            'rootSnapshotReachableCount': 1, 'rows': [{'pid': 5, 'parentPid': 1, 'executableRoleCode': 2}]}

    def test_census_failure_v2_projects_only_the_closed_numeric_record(self):
        error = Rejected(15); error.pairedRole = 1; error.pairedCensusObservation = self.census_record()
        with mock.patch.object(Path, 'stat', side_effect=AssertionError()), \
             mock.patch.object(Path, 'lstat', side_effect=AssertionError()), \
             mock.patch.object(Path, 'open', side_effect=AssertionError()):
            result = api.project_failure(error)
        self.assertEqual(result['schemaVersion'], 2)
        self.assertEqual(result['errorCode'], 15)
        self.assertEqual(result['knownRole'], 1)
        self.assertEqual(result.get('censusObservation'), self.census_record())
        self.assertIsNot(result['censusObservation'], error.pairedCensusObservation)
        self.assertFalse(result['qualification'])
        self.assertEqual(set(result), {'schemaVersion','kind','completed','qualification','errorCode','exceptionCode',
            'stageCode','knownRole','fontCode','fileSizeKnown','fileSize','linkCountKnown','linkCount','frames',
            'unknownFrames','truncated','censusObservation'})

    def test_malformed_census_metadata_cannot_escape_or_erase_original_numbers(self):
        def duplicate(record):
            record.update(rootSnapshotReachableCount=2,guardUnexpectedCount=2,
                          rows=record['rows']*2)
        changes = [lambda r:r.update(extra=1), lambda r:r.pop('sealed'), lambda r:r.update(knownCount=True),
            lambda r:r.update(schemaVersion=True), lambda r:r.update(diagnosticOnly=False),
            lambda r:r.update(acceptanceEligible=True), lambda r:r.update(rootPid=0),
            lambda r:r.update(originalRootCreationFileTime=0), lambda r:r.update(sealed=1),
            lambda r:r.update(requireLiveRoot=0), lambda r:r.update(snapshotCount=10001),
            lambda r:r.update(knownCount=65), lambda r:r.update(guardUnexpectedCount=0),
            lambda r:r.update(rootSnapshotReachableCount=2), lambda r:r['rows'][0].update(pid=True),
            lambda r:r['rows'][0].update(pid=1), lambda r:r['rows'][0].update(parentPid=2**32),
            lambda r:r['rows'][0].update(executableRoleCode=4), lambda r:r['rows'][0].update(executableRoleCode=True),
            lambda r:r['rows'][0].update(executableName='SYNTHETIC-PRIVATE'), lambda r:r.update(rows=tuple(r['rows'])),
            duplicate]
        for index, change in enumerate(changes):
            with self.subTest(mutation=index):
                record=self.census_record();change(record);error=Rejected(15);error.pairedCensusObservation=record
                result=api.project_failure(error)
                self.assertEqual(result['schemaVersion'],2)
                self.assertIsNone(result.get('censusObservation'))
                self.assertEqual(result['errorCode'],15)
                self.assertNotIn('SYNTHETIC',json.dumps(result))

    def test_optional_census_projection_fault_keeps_original_failure(self):
        for failure in (MemoryError(), KeyboardInterrupt(), SystemExit()):
            with self.subTest(faultType=type(failure).__name__):
                error=Rejected(15);error.pairedCensusObservation=self.census_record()
                with mock.patch.object(api,'_project_census',side_effect=failure,create=True) as project:
                    result=api.project_failure(error)
                self.assertEqual(project.call_count,1)
                self.assertEqual(result['errorCode'],15)
                self.assertEqual(result['exceptionCode'],1)
                self.assertIn('censusObservation',result)
                self.assertIsNone(result['censusObservation'])

    def test_maximum_census_failure_packet_stays_bounded_and_independent(self):
        record=self.census_record();record.update(snapshotCount=10000,knownCount=1,guardUnexpectedCount=64,
            rootSnapshotReachableCount=64,originalRootCreationFileTime=2**64-1,
            rows=[{'pid':2**32-65+i,'parentPid':1,'executableRoleCode':3}for i in range(64)])
        error=Rejected(15);error.pairedCensusObservation=record
        result=api.project_failure(error)
        self.assertEqual(result.get('censusObservation'),record)
        result['frames']=[{'fileCode':9,'functionCode':102,'line':20000}for _ in range(12)]
        self.assertLessEqual(len(json.dumps(result,sort_keys=True).encode('ascii')),8192)
        record['rows'][0]['pid']=1
        self.assertNotEqual(result['censusObservation'],record)

    def test_failure_main_keeps_original_exit_and_new_closed_census_packet(self):
        error=Rejected(15);error.pairedCensusObservation=self.census_record();output=io.StringIO()
        with mock.patch.object(sys,'argv',self.main_args()),mock.patch.object(api,'run',side_effect=error), \
             mock.patch.object(sys,'stdout',output):
            self.assertEqual(api.main(),1)
        result=json.loads(output.getvalue())
        self.assertEqual(result['schemaVersion'],2)
        self.assertEqual(result['errorCode'],15)
        self.assertEqual(result.get('censusObservation'),self.census_record())


if __name__ == '__main__': unittest.main()
