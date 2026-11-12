"""Closed numeric portable tests; not a Full job or source qualification gate."""
from pathlib import Path
import contextlib
import io
import json
import sys
import unittest

def main():
    root=Path(__file__).resolve().parent
    sys.path.insert(0,str(root))
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_*.py')
            result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        value={'schemaVersion':1,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'windowsSdkVerified':False,'sourceFullQualified':False}
        print(json.dumps(value,sort_keys=True))
        return 0 if result.testsRun==74 and result.wasSuccessful() and not result.skipped else 1
    except BaseException:
        print('{"schemaVersion":1,"driverFailure":1,"windowsSdkVerified":false,"sourceFullQualified":false}')
        return 2

if __name__=='__main__':raise SystemExit(main())
