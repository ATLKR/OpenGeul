"""Reject no-op style shortcuts and mismatched saved/reopened Writer evidence."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'writer_style_smoke.py'
if SOURCE.is_file():
    spec = importlib.util.spec_from_file_location('suite_writer_style_smoke', SOURCE)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
else:
    smoke = None


class WriterStyleEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke, 'Focused Writer style proof implementation is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def docx(self, name, paragraphs):
        path = self.folder / name
        body = ''.join('<w:p>' + ('<w:pPr><w:pStyle w:val="' + style + '"/></w:pPr>' if style else '')
                       + '<w:r><w:t>' + text + '</w:t></w:r></w:p>' for style, text in paragraphs)
        with zipfile.ZipFile(path, 'w') as package:
            package.writestr('word/document.xml', '<w:document xmlns:w="' + smoke.WORD_NS + '"><w:body>' + body + '</w:body></w:document>')
        return smoke.docx_style_evidence(path)

    def pair(self):
        before = self.docx('before.docx', [(None, 'Engine-OpenGeul-writer 한글')])
        after = self.docx('after.docx', [('Heading1', 'Engine-OpenGeul-writer 한글')])
        return before, after

    def test_actual_first_paragraph_style_and_exact_body_are_recorded(self):
        before, after = self.pair()
        evidence = smoke.require_saved_style(before, after)
        self.assertEqual(evidence['firstParagraphStyleId'], 'Heading1')
        self.assertEqual(evidence['bodyText'], before['bodyText'])

    def test_heading_in_second_paragraph_cannot_satisfy_first_paragraph(self):
        before = self.docx('before.docx', [(None, 'first'), (None, 'second')])
        after = self.docx('after.docx', [(None, 'first'), ('Heading1', 'second')])
        with self.assertRaisesRegex(AssertionError, 'first paragraph'):
            smoke.require_saved_style(before, after)

    def test_changed_text_is_not_a_successful_style_only_edit(self):
        before, _ = self.pair()
        after = self.docx('after.docx', [('Heading1', 'lost text')])
        with self.assertRaisesRegex(AssertionError, 'text'):
            smoke.require_saved_style(before, after)

    def test_save_poll_waits_for_known_baseline_bytes_before_asserting_style(self):
        before, after = self.pair()
        self.assertTrue(callable(getattr(smoke, 'saved_style_ready', None)), 'Asynchronous Save completion predicate is missing')
        self.assertIsNone(smoke.saved_style_ready(before, before))
        self.assertEqual(smoke.saved_style_ready(before, after), after)

    def test_save_poll_rejects_changed_file_with_wrong_style(self):
        before, _ = self.pair()
        changed = self.docx('wrong-style.docx', [('Heading2', before['bodyText'])])
        self.assertTrue(callable(getattr(smoke, 'saved_style_ready', None)), 'Asynchronous Save completion predicate is missing')
        with self.assertRaisesRegex(AssertionError, 'first paragraph'):
            smoke.saved_style_ready(before, changed)

    def test_shortcut_noop_with_unchanged_bytes_is_rejected(self):
        before, _ = self.pair()
        with self.assertRaisesRegex(AssertionError, 'bytes|first paragraph'):
            smoke.require_saved_style(before, dict(before))

    def test_already_heading1_baseline_cannot_prove_shortcut_worked(self):
        _, after = self.pair()
        changed = dict(after, sha256='a' * 64)
        with self.assertRaisesRegex(AssertionError, 'baseline'):
            smoke.require_saved_style(after, changed)

    def test_independent_uno_requires_exact_style_text_and_stable_saved_bytes(self):
        _, expected = self.pair()
        observed = {'bodyText': expected['bodyText'], 'firstParagraphParaStyleName': 'Heading 1'}
        result = smoke.require_uno_style(expected, observed, expected['sha256'], expected['sha256'])
        self.assertEqual(result['firstParagraphParaStyleName'], 'Heading 1')

    def test_independent_uno_rejects_wrong_style(self):
        _, expected = self.pair()
        for style in ('Standard', 'Heading 10', 'Heading1'):
            with self.subTest(style=style), self.assertRaisesRegex(AssertionError, 'Heading 1'):
                smoke.require_uno_style(expected, {'bodyText': expected['bodyText'], 'firstParagraphParaStyleName': style}, expected['sha256'], expected['sha256'])

    def test_independent_uno_rejects_changed_text(self):
        _, expected = self.pair()
        with self.assertRaisesRegex(AssertionError, 'body'):
            smoke.require_uno_style(expected, {'bodyText': 'changed', 'firstParagraphParaStyleName': 'Heading 1'}, expected['sha256'], expected['sha256'])

    def test_independent_uno_rejects_changes_before_or_during_reopen(self):
        _, expected = self.pair()
        observed = {'bodyText': expected['bodyText'], 'firstParagraphParaStyleName': 'Heading 1'}
        for before, after in [('a' * 64, 'a' * 64), (expected['sha256'], 'a' * 64)]:
            with self.subTest(before=before, after=after), self.assertRaisesRegex(AssertionError, 'bytes'):
                smoke.require_uno_style(expected, observed, before, after)

    def test_native_crash_status_cannot_satisfy_clean_office_exit(self):
        self.assertTrue(callable(getattr(smoke, 'require_office_exit', None)), 'Native crash exit-code validation is missing')
        for code in (0, 1):
            self.assertEqual(smoke.require_office_exit(code), code)
        for code in (0xC0000005, 0xC0000409, -1073741819, 259):
            with self.subTest(code=code), self.assertRaisesRegex(AssertionError, 'exit'):
                smoke.require_office_exit(code)

    def test_witness_query_failure_keeps_original_error_and_cannot_pass(self):
        self.assertTrue(callable(getattr(smoke, 'close_engine_witness', None)), 'Fail-closed engine cleanup is missing')
        class Witness:
            def exited(self, seconds): raise OSError('retained process query failed')
            def close(self): pass
        record = {'guiVerified': True, 'success': False, 'error': 'original input failure'}
        smoke.close_engine_witness(Witness(), record)
        self.assertFalse(record['guiVerified'])
        self.assertFalse(record['success'])
        self.assertEqual(record['error'], 'original input failure')
        self.assertIn('retained process query failed', record['engineCleanupErrors'][0])

    def test_surviving_engine_cannot_pass_clean_style_shutdown(self):
        self.assertTrue(callable(getattr(smoke, 'close_engine_witness', None)), 'Fail-closed engine cleanup is missing')
        class Witness:
            def exited(self, seconds): return False
            def close(self): pass
        record = {'guiVerified': True, 'success': False}
        smoke.close_engine_witness(Witness(), record)
        self.assertFalse(record['guiVerified'])
        self.assertFalse(record['officeExitedAfterCleanup'])

    def test_saved_target_cannot_escape_owned_generated_fixture(self):
        (self.folder / 'fixtures').mkdir()
        path = self.folder / 'fixtures' / 'writer-heading1.docx'
        path.write_bytes(b'fixture')
        self.assertEqual(smoke.owned_saved_path(self.folder, {'copiedFixture': 'fixtures/writer-heading1.docx'}), path.resolve())
        for name in ('../foreign.docx', str(path.resolve()), 'fixtures/other.docx'):
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'owned'):
                smoke.owned_saved_path(self.folder, {'copiedFixture': name})


if __name__ == '__main__': unittest.main()
