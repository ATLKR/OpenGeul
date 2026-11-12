"""Closed numeric local regression runner; never invokes the Windows entry."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import unittest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parent
    start=time.monotonic();suite=unittest.defaultTestLoader.discover(str(root/'tests'),pattern='test_*.py')
    result=unittest.TestResult();suite.run(result)
    value={'schemaVersion':1,'kind':'sdk-gate-portable-regression','tests':result.testsRun,
      'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
      'seconds':round(time.monotonic()-start,3),'actualWindowsExecuted':False,'nativeSdkCompiled':False,
      'qualification':False,'canService':False}
    output=Path(args.output)
    with output.open('x') as stream:json.dump(value,stream,sort_keys=True);stream.write('\n')
    print(json.dumps(value,sort_keys=True))
    return int(bool(result.failures or result.errors))

if __name__=='__main__':raise SystemExit(main())
