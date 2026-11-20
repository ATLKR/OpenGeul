"""Read-only failure diagnostics must stay within the actual servicing attempt."""
from datetime import datetime
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/korean_servicing_diagnostics.py'
SPEC = importlib.util.spec_from_file_location('suite_korean_servicing_diagnostics', SOURCE)
diag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diag)


class KoreanServicingDiagnosticsTests(unittest.TestCase):
    def test_current_attempt_missing_package_lines_exclude_old_and_future_sessions(self):
        text = '\n'.join([
            '2026-10-16 15:19:00, Error CBS old package missing',
            '2026-10-16 15:20:50, Info CBS Session initialized',
            '2026-10-16 15:20:53, Info CBS Package: Microsoft-Windows-LanguageFeatures-Basic-ko-kr~10.0.26100.33438',
            '2026-10-16 15:21:25, Error CBS Missing source HRESULT 0x800f0912',
            '2026-10-16 15:23:00, Error CBS future package missing'])
        selected = diag.select_attempt_lines(text, datetime(2026, 10, 16, 15, 20, 45), datetime(2026, 10, 16, 15, 21, 27))
        self.assertIn('10.0.26100.33438', selected['text'])
        self.assertIn('0x800f0912', selected['text'])
        self.assertNotIn('old package', selected['text'])
        self.assertNotIn('future package', selected['text'])

    def test_selected_lines_have_a_finite_byte_and_line_budget(self):
        text = '\n'.join('2026-10-16 15:21:25, Error CBS missing package ' + str(i) + 'x' * 500 for i in range(2000))
        selected = diag.select_attempt_lines(text, datetime(2026, 10, 16, 15, 20), datetime(2026, 10, 16, 15, 22), byte_limit=2048, line_limit=3)
        self.assertLessEqual(len(selected['text'].encode('utf-8')), 2048)
        self.assertLessEqual(len(selected['text'].splitlines()), 3)
        self.assertIn('1999', selected['text'])
        self.assertTrue(selected['truncated'])

    def test_bounded_tail_reads_last_bytes_without_copying_the_full_servicing_log(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'CBS.log'
            source.write_bytes(b'a' * 5_000_000 + b'\nnew missing package\n')
            record, payload = diag.read_tail(source, byte_limit=1024)
            self.assertEqual(len(payload), 1024)
            self.assertTrue(payload.endswith(b'new missing package\n'))
            self.assertTrue(record['truncated'])
            self.assertEqual(record['sourceBytes'], source.stat().st_size)

    def test_tail_reader_refuses_zero_or_excessive_byte_budgets(self):
        for limit in (0, -1, 1048577):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                diag.read_tail(Path('CBS.log'), byte_limit=limit)


if __name__ == '__main__': unittest.main()
