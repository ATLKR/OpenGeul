"""IME save observation retries only its bounded document-byte read."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
import korean_ime_smoke as ime

class IMESavedReadTests(unittest.TestCase):
    def payload(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as package:
            package.writestr('word/document.xml','<p>'+ime.marker('writer')+'</p>')
        return stream.getvalue()
    def run_poll(self, reader):
        clock=[0.];receipt={}
        with patch.object(Path,'read_bytes',side_effect=reader), patch.object(ime.time,'monotonic',side_effect=lambda:clock[0]), patch.object(ime.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            try:return ime.wait_saved_ime_marker(Path('owned.docx'),'writer',.3,receipt),None,receipt
            except Exception as error:return None,error,receipt
    def test_denial_then_exact_marker_passes(self):
        result,error,receipt=self.run_poll([PermissionError(13,'denied'),self.payload()])
        self.assertIsNone(error);self.assertTrue(result)
        self.assertEqual(receipt['imeSavedRead']['attempts'],2)
        self.assertEqual(receipt['imeSavedRead']['transientCount'],1)
    def test_persistent_denial_and_wrong_content_fail(self):
        for reader in (PermissionError(13,'denied'),lambda:b'broken zip'):
            with self.subTest(reader=reader):
                value,error,receipt=self.run_poll(reader)
                self.assertIsNone(value);self.assertIsInstance(error,AssertionError)
                self.assertGreater(receipt['imeSavedRead']['attempts'],0)
    def test_parser_deadline_crossing_rejects_valid_marker(self):
        clock=[0.]
        def parse(stream):clock[0]=.3;return ime.marker('writer')
        with patch.object(Path,'read_bytes',return_value=self.payload()),patch.object(ime.time,'monotonic',side_effect=lambda:clock[0]),patch.object(ime,'package_text',side_effect=parse):
            with self.assertRaises(AssertionError):ime.wait_saved_ime_marker(Path('owned.docx'),'writer',.3,{})
