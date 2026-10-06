import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'e2e'/'printing'))
from queue_policy import queue_creation_command

class QueueCommandTests(unittest.TestCase):
    def test_supported_command_uses_only_owned_local_pdf_queue(self):
        command=queue_creation_command('OpenGeul-E2E-123')
        self.assertIn("Add-Printer -Name 'OpenGeul-E2E-123'",command)
        self.assertIn("-DriverName 'Microsoft Print To PDF' -PortName 'PORTPROMPT:'",command)
        self.assertIn('-KeepPrintedJobs',command)
        self.assertNotIn('-Shared',command)
        with self.assertRaises(ValueError):queue_creation_command("'; Remove-Printer X #")
