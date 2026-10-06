import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'e2e'/'printing'))
from queue_policy import validate_queue

class QueueDefinitionTests(unittest.TestCase):
    def test_all_pywin32_printer_info_2_fields_are_explicit(self):
        from queue_policy import queue_definition
        info=queue_definition('OpenGeul-E2E-123')
        fields={'pServerName','pPrinterName','pShareName','pPortName','pDriverName','pComment',
            'pLocation','pDevMode','pSepFile','pPrintProcessor','pDatatype','pParameters',
            'pSecurityDescriptor','Attributes','Priority','DefaultPriority','StartTime',
            'UntilTime','Status','cJobs','AveragePPM'}
        self.assertEqual(set(info),fields)
        self.assertTrue(validate_queue(info,'OpenGeul-E2E-123'))
        self.assertIsNone(info['pServerName']);self.assertIsNone(info['pShareName'])
        self.assertEqual(info['Attributes'],0x140)
    def test_queue_factory_rejects_other_names(self):
        from queue_policy import queue_definition
        with self.assertRaises(ValueError):queue_definition('Network printer')
