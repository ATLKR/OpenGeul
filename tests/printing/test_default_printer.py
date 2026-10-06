import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'e2e'/'printing'))
from virtual_printer import default_printer

class DefaultPrinterTests(unittest.TestCase):
    def read(self,value):
        class API:
            def GetDefaultPrinter(self):
                if isinstance(value,Exception):raise value
                return value
        return default_printer(API())
    def test_runner_without_default_is_supported(self):
        self.assertIsNone(self.read(RuntimeError('The default printer was not found.')))
    def test_existing_default_is_recorded(self):
        self.assertEqual(self.read('Existing printer'),'Existing printer')
    def test_other_spooler_errors_are_not_hidden(self):
        with self.assertRaises(RuntimeError):self.read(RuntimeError('Spooler failure'))
