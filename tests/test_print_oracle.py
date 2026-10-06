import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e' / 'printing'))
from oracle import validate_report, compare_terminal_ink

class PrinterOracleTests(unittest.TestCase):
    def setUp(self):
        self.expected = {'pageSize': [595.276, 841.89], 'pages': [['PRINT-FIRST', 'PRINT-END-gypq-123']]}
        self.report = {'producer': 'Microsoft: Print To PDF', 'pages': [
            {'size': [595.28, 841.89], 'text': 'PRINT-FIRST\nPRINT-END-gypq-123', 'inkPixels': 1234,
             'markers': {'PRINT-FIRST': {'inkPixels': 200, 'withinPage': True},
                         'PRINT-END-gypq-123': {'inkPixels': 280, 'withinPage': True}}}]}
    def test_valid_output(self):
        self.assertEqual(validate_report(self.report, self.expected), {'pages': 1, 'markers': 2})
    def test_extra_blank_page_fails(self):
        self.report['pages'].append(copy.deepcopy(self.report['pages'][0]))
        with self.assertRaisesRegex(AssertionError, 'page count'): validate_report(self.report, self.expected)
    def test_missing_final_line_fails(self):
        self.report['pages'][0]['text'] = 'PRINT-FIRST'
        with self.assertRaisesRegex(AssertionError, 'PRINT-END'): validate_report(self.report, self.expected)
    def test_duplicate_text_fails(self):
        self.report['pages'][0]['text'] += ' PRINT-FIRST'
        with self.assertRaisesRegex(AssertionError, 'PRINT-FIRST'): validate_report(self.report, self.expected)
    def test_blank_raster_fails(self):
        self.report['pages'][0]['inkPixels'] = 0
        with self.assertRaisesRegex(AssertionError, 'blank'): validate_report(self.report, self.expected)
    def test_invisible_extractable_text_fails(self):
        self.report['pages'][0]['markers']['PRINT-END-gypq-123']['inkPixels'] = 0
        with self.assertRaisesRegex(AssertionError, 'invisible'): validate_report(self.report, self.expected)
    def test_outside_paper_fails(self):
        self.report['pages'][0]['markers']['PRINT-FIRST']['withinPage'] = False
        with self.assertRaisesRegex(AssertionError, 'outside'): validate_report(self.report, self.expected)
    def test_wrong_orientation_fails(self):
        self.report['pages'][0]['size'].reverse()
        with self.assertRaisesRegex(AssertionError, 'paper'): validate_report(self.report, self.expected)
    def test_editor_chrome_leaking_into_print_fails(self):
        self.report['pages'][0]['text'] += ' HOP_PRINT_EDITOR_CHROME'
        self.expected['forbidden'] = ['HOP_PRINT_EDITOR_CHROME']
        with self.assertRaisesRegex(AssertionError, 'chrome'): validate_report(self.report, self.expected)
    def test_software_export_is_not_microsoft_printer(self):
        self.report['producer'] = 'Skia/PDF'
        with self.assertRaisesRegex(AssertionError, 'printer producer'): validate_report(self.report, self.expected)
    def test_lower_glyph_loss_fails_even_when_text_extracts(self):
        with self.assertRaisesRegex(AssertionError, 'terminal'): compare_terminal_ink(70, 100)
    def test_zero_control_is_invalid(self):
        with self.assertRaisesRegex(AssertionError, 'control'): compare_terminal_ink(0, 0)
    def test_comparable_terminal_ink_passes(self):
        self.assertEqual(compare_terminal_ink(98, 100), .98)
    def test_empty_fixture_is_not_success(self):
        with self.assertRaises(AssertionError): validate_report({'pages': []}, {'pageSize': [595,842], 'pages': []})

if __name__ == '__main__': unittest.main()
