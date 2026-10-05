"""Run all baseline and follow-up UI tests with the existing evidence writer."""
import os
from pathlib import Path
import unittest
from run import EvidenceResult
from test_hop_followups import suite
import json
import sys

output=Path(os.environ['E2E_OUTPUT']);output.mkdir(parents=True,exist_ok=True)
result=unittest.TextTestRunner(verbosity=2,resultclass=EvidenceResult).run(suite())
expected=16 if os.environ.get('E2E_MODE')=='native' else 10
success=result.wasSuccessful() and not result.skipped and result.testsRun==expected
(output/'results.json').write_text(json.dumps({'tests':result.records,'expectedTests':expected,'success':success,'commit':os.environ.get('GITHUB_SHA')},ensure_ascii=False,indent=2))
sys.exit(0 if success else 1)
