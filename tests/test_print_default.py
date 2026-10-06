import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'/'printing'))
import spooler
class PrinterDefaultTests(unittest.TestCase):
    def test_absent_default_is_valid(self):
        api=Mock(); api.GetDefaultPrinter.side_effect=RuntimeError('The default printer was not found.')
        self.assertIsNone(spooler.read_default(api))
    def test_unrelated_error_is_not_ignored(self):
        api=Mock(); api.GetDefaultPrinter.side_effect=RuntimeError('access denied')
        with self.assertRaisesRegex(RuntimeError,'access denied'):spooler.read_default(api)
    def test_restore_existing_default(self):
        api=Mock();api.GetDefaultPrinter.return_value='Owned test queue'
        spooler.restore_default(api,'Previous queue','Owned test queue')
        api.SetDefaultPrinter.assert_called_once_with('Previous queue')
    def test_restore_absence_does_not_choose_another_printer(self):
        api=Mock();api.GetDefaultPrinter.return_value='Owned test queue'
        with patch.object(spooler,'clear_default_device') as clear:
            spooler.restore_default(api,None,'Owned test queue')
            clear.assert_called_once()
        api.SetDefaultPrinter.assert_not_called()
    def test_refuse_to_overwrite_concurrent_default_change(self):
        api=Mock();api.GetDefaultPrinter.return_value='Unrelated printer'
        with self.assertRaisesRegex(RuntimeError,'changed'):
            spooler.restore_default(api,'Previous queue','Owned test queue')
    def test_complete_driver_configuration_is_preserved_without_sharing(self):
        original={'pServerName':None,'pPrinterName':'Microsoft Print to PDF','pShareName':'DO-NOT-SHARE',
          'pPortName':'PORTPROMPT:','pDriverName':'Microsoft Print To PDF','pSecurityDescriptor':'original-only',
          'pPrintProcessor':'winprint','pDevMode':'old','pDatatype':'RAW','Status':0,'Attributes':0}
        value=spooler.isolated_printer_info(original,'Owned queue','new mode',0x140)
        self.assertEqual(set(value),set(original))
        self.assertEqual(value['pPrinterName'],'Owned queue');self.assertEqual(value['pDevMode'],'new mode')
        self.assertIsNone(value['pShareName']);self.assertIsNone(value['pSecurityDescriptor'])
        self.assertEqual(original['pPrinterName'],'Microsoft Print to PDF')
