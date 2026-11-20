"""Closed Writer OS evidence, without importing or invoking a native probe."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))

FIELDS = ('verified', 'stageCode', 'hresult', 'officePid', 'officeCreationTime',
    'childHwnd', 'rootRole', 'documentRole', 'focusedRole', 'focusedState',
    'focusVariantType', 'parentCount', 'ia2Supported', 'textSupported',
    'ownerBefore', 'ownerAfter', 'referencesAcquired', 'referencesReleased',
    'variantsCreated', 'variantsCleared', 'cleanupFailure', 'cleanupHresult',
    'ownerReleased')


def failure_record(*, stage=3, maximum=False):
    import writer_os_accessibility as source
    value = dict.fromkeys(source._MAXIMA, 0)
    if maximum:
        value.update(source._MAXIMA)
    value.update(schemaVersion=1, verified=0, stageCode=stage,
        officePid=0xffffffff if maximum else 200,
        officeCreationTime=2**64-1 if maximum else 300,
        childHwnd=2**64-1 if maximum else 123)
    return dict(case='korean-ui-writer', module='writer', success=False,
        stage=source.STAGES[stage], officePid=value['officePid'],
        officeCreationTime=value['officeCreationTime'], childHwnd=value['childHwnd'],
        writerOsAccessibility=value,
        numericFailure=dict(captured=1, exceptionCode=1, fileCode=5, line=199),
        numericFailureFrames=[[5,199]])


class WriterOsSummaryTests(unittest.TestCase):
    def helper(self):
        self.assertTrue((E2E / 'writer_os_summary.py').is_file(),
                        'Closed Writer OS numeric projection is required')
        return importlib.import_module('writer_os_summary')

    def test_projects_every_existing_numeric_field_in_fixed_order_without_mutating(self):
        from writer_os_accessibility import _MAXIMA
        helper = self.helper()
        self.assertEqual(helper.FIELDS, FIELDS)
        self.assertEqual(FIELDS, tuple(key for key in _MAXIMA if key != 'schemaVersion'))
        record = failure_record()
        record.update(error='PRIVATE DOCUMENT INPUT', path='PRIVATE PATH')
        original = copy.deepcopy(record)
        result = helper.project(record)
        self.assertEqual(result, [record['writerOsAccessibility'][key] for key in FIELDS])
        self.assertTrue(helper.valid(result))
        self.assertEqual(record, original)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_distinct_completed_root_failures_remain_distinct(self):
        helper = self.helper()
        vectors = []
        for hresult, references, variants in ((0x80004005,0,0),
                (0x80004002,1,0),(0,2,1)):
            record = failure_record()
            record['writerOsAccessibility'].update(hresult=hresult,
                referencesAcquired=references, referencesReleased=references,
                variantsCreated=variants, variantsCleared=variants, ownerReleased=1)
            vectors.append(helper.project(record))
        self.assertEqual(len({tuple(value) for value in vectors}), 3)

    def test_rejects_each_boolean_range_extra_or_missing_numeric_value(self):
        from writer_os_accessibility import _MAXIMA
        helper = self.helper()
        original = failure_record()
        for key, maximum in _MAXIMA.items():
            for replacement in (True, -1, maximum+1, 'PRIVATE'):
                record = copy.deepcopy(original)
                record['writerOsAccessibility'][key] = replacement
                with self.subTest(key=key, replacement=replacement):
                    self.assertIsNone(helper.project(record))
            record = copy.deepcopy(original)
            del record['writerOsAccessibility'][key]
            self.assertIsNone(helper.project(record))
        record = copy.deepcopy(original)
        record['writerOsAccessibility']['name'] = 'PRIVATE DOCUMENT'
        self.assertIsNone(helper.project(record))

    def test_retained_pid_generation_child_and_failure_stage_must_match(self):
        helper = self.helper()
        for key in ('officePid', 'officeCreationTime', 'childHwnd'):
            for replacement in (0, True, 999):
                record = failure_record(); record[key] = replacement
                with self.subTest(key=key, replacement=replacement):
                    self.assertIsNone(helper.project(record))
        for change in (dict(case='korean-ui-calc'), dict(module='calc'),
                dict(success=True), dict(stage='writer-os-focus')):
            self.assertIsNone(helper.project(failure_record() | change))

    def test_cleanup_counters_and_success_cannot_become_failure_evidence(self):
        helper = self.helper()
        for change in (dict(referencesReleased=1), dict(variantsCleared=1),
                dict(verified=1), dict(stageCode=0), dict(stageCode=12)):
            record = failure_record(); record['writerOsAccessibility'].update(change)
            self.assertIsNone(helper.project(record))
        for malformed in (None, (), [0], [True]*len(FIELDS)):
            self.assertFalse(helper.valid(malformed))

    def test_maximum_existing_failure_values_remain_valid(self):
        helper = self.helper()
        value = helper.project(failure_record(stage=14, maximum=True))
        self.assertIsNotNone(value)
        self.assertTrue(helper.valid(value))

    def test_decoder_imports_no_producer_or_native_modules(self):
        self.helper()
        program = '''import importlib.util, sys
path=sys.argv[1]
spec=importlib.util.spec_from_file_location('writer_os_summary',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not module.valid([])
assert not any(name in sys.modules for name in ('writer_os_accessibility',
    'windows_smoke','startup_smoke','korean_ui_smoke','ctypes','comtypes'))
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', program,
            str(E2E / 'writer_os_summary.py')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
