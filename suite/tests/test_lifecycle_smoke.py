"""Evidence-policy tests for the Windows lifecycle acceptance harness."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'lifecycle_smoke.py'
SPEC = importlib.util.spec_from_file_location('suite_lifecycle_smoke', SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class LifecycleSmokeTests(unittest.TestCase):
    def test_policy_api_is_present(self):
        for name in ('CASE_REQUIREMENTS', 'lifecycle_report', 'writer_evidence',
                     'owned_target', 'require_dialog_action', 'require_child_bounds',
                     'generate_hwpx', 'copy_writer_fixture'):
            self.assertTrue(hasattr(smoke, name), 'Missing lifecycle evidence policy: ' + name)

    def test_report_requires_every_case_and_concrete_native_evidence(self):
        if not hasattr(smoke, 'CASE_REQUIREMENTS'): self.skipTest('RED: policy API not implemented')
        records = [{'case': name, 'success': True, **{key: True for key in flags}}
                   for name, flags in smoke.CASE_REQUIREMENTS.items()]
        self.assertTrue(smoke.lifecycle_report(records)['success'])
        self.assertEqual(len(records), 7)
        for index, record in enumerate(records):
            for flag in smoke.CASE_REQUIREMENTS[record['case']]:
                invalid = [item.copy() for item in records]
                invalid[index][flag] = False
                self.assertFalse(smoke.lifecycle_report(invalid)['success'], flag)
        for invalid in (records[:-1], records + records[:1], records + [{'case': 'unexpected', 'success': True}]):
            self.assertFalse(smoke.lifecycle_report(invalid)['success'])

    def test_copy_uses_passing_generated_provenance_without_mutating_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures, owned = root / 'fixtures', root / 'owned'
            fixtures.mkdir()
            owned.mkdir()
            source = fixtures / 'OpenGeul-writer.docx'
            with zipfile.ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Engine-OpenGeul-writer UI-OpenGeul-writer</w:t></w:r></w:p></w:body></w:document>')
            record = {'schemaVersion': 1, 'kind': 'engine', 'passed': True,
                      'cases': [{'module': 'writer', 'status': 'passed', 'fixture': str(source.resolve())}]}
            baseline = root / 'engine-smoke.json'
            baseline.write_text(json.dumps(record), encoding='utf-8')
            before = source.read_bytes()
            copied = smoke.copy_writer_fixture(fixtures, owned, '복사 문서 & 한글.docx')
            self.assertEqual(copied.read_bytes(), before)
            self.assertEqual(source.read_bytes(), before)
            record['passed'] = False
            baseline.write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaises(AssertionError): smoke.copy_writer_fixture(fixtures, owned, 'invalid.docx')

    def test_uno_evidence_requires_exact_body_source_sha_and_unchanged_file(self):
        self.assertTrue(hasattr(smoke, 'require_uno_observation'), 'Missing independent UNO evidence policy')
        expected = {'sha256': 'abc123', 'bodyText': 'Owned\n한글 & body'}
        result = smoke.require_uno_observation(expected, 'Owned\r\n한글 & body', 'abc123', 'abc123')
        self.assertEqual(result['bodyText'], expected['bodyText'])
        for actual, before, after in (('Wrong body', 'abc123', 'abc123'),
                                     (expected['bodyText'], 'changed', 'changed'),
                                     (expected['bodyText'], 'abc123', 'changed')):
            with self.assertRaises(AssertionError): smoke.require_uno_observation(expected, actual, before, after)

    def test_writer_evidence_reads_only_body_text_and_exact_marker_counts(self):
        if not hasattr(smoke, 'writer_evidence'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'owned.docx'
            with zipfile.ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>BASE-</w:t></w:r><w:r><w:t>MARKER</w:t></w:r></w:p></w:body></w:document>')
                package.writestr('word/comments.xml', '<comment>FORBIDDEN</comment>')
            evidence = smoke.writer_evidence(source, ('BASE-MARKER',), ('FORBIDDEN',))
            self.assertEqual(evidence['bodyText'], 'BASE-MARKER')
            self.assertEqual(len(evidence['sha256']), 64)
            with self.assertRaises(AssertionError): smoke.writer_evidence(source, ('MISSING',))
            with self.assertRaises(AssertionError): smoke.writer_evidence(source, (), ('MARKER',))

    def test_targets_are_fresh_direct_children_and_never_links(self):
        if not hasattr(smoke, 'owned_target'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = smoke.owned_target(root, '한글 저장 & 결과.docx')
            self.assertEqual(target.parent, root.resolve())
            target.write_bytes(b'owned')
            for name in ('한글 저장 & 결과.docx', '../escape.docx', '/absolute.docx'):
                with self.assertRaises(AssertionError): smoke.owned_target(root, name)
            link = root / 'link.docx'
            try: link.symlink_to(target)
            except OSError: return
            with self.assertRaises(AssertionError): smoke.owned_target(root, link.name)

    def test_dialog_action_checks_all_identity_and_exact_expected_button(self):
        if not hasattr(smoke, 'require_dialog_action'): self.skipTest('RED: policy API not implemented')
        identity = dict(pid=31, shell_pid=31, owner=44, document=44,
                        title='OpenGeul Writer', expected_title='OpenGeul Writer',
                        class_name='#32770', text=['변경 내용을 저장하시겠습니까?'],
                        expected_text='변경 내용을 저장하시겠습니까?', button='취소', allowed=('저장', '저장하지 않음', '취소'))
        smoke.require_dialog_action(**identity)
        for key, value in (('pid', 99), ('owner', 55), ('title', 'Foreign'),
                           ('class_name', 'Foreign'), ('text', ['foreign']), ('button', '확인')):
            with self.assertRaises(AssertionError): smoke.require_dialog_action(**{**identity, key: value})

    def test_bounds_require_child_to_fill_host_client_after_screen_mapping(self):
        if not hasattr(smoke, 'require_child_bounds'): self.skipTest('RED: policy API not implemented')
        self.assertEqual(smoke.require_child_bounds((0, 0, 900, 600), (0, 0, 900, 600)), [900, 600])
        for actual in ((0, 0, 800, 600), (1, 0, 901, 600), (0, 0, 900, 0)):
            with self.assertRaises(AssertionError): smoke.require_child_bounds((0, 0, 900, 600), actual)

    def test_generated_hwpx_contains_only_owned_text_and_leaves_template_intact(self):
        if not hasattr(smoke, 'generate_hwpx'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '경로 확인 & 문서.hwpx'
            template = Path(__file__).resolve().parents[2] / 'tests/fixtures/advanced-owned/owned-blank.hwpx'
            original = template.read_bytes()
            smoke.generate_hwpx(target)
            with zipfile.ZipFile(target) as package:
                text = ''.join(ET.fromstring(package.read('Contents/section0.xml')).itertext())
                self.assertIn('Suite-HWPX-route-한글 & 123', text)
                self.assertIsNone(package.testzip())
            self.assertEqual(template.read_bytes(), original)
            with self.assertRaises(AssertionError): smoke.generate_hwpx(target)


if __name__ == '__main__': unittest.main()
