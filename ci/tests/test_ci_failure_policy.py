"""A job-level failure suppression must not bypass the existing step policy."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from policy import audit,PUBLIC

class JobFailurePolicyTests(unittest.TestCase):
    def job(self,**extra):
        return {'on':{'push':{}},'jobs':{'check':{'if':PUBLIC,'runs-on':'ubuntu-24.04',
             'timeout-minutes':5,'steps':[{'run':'exit 1'}],**extra}}}
    def test_no_suppression_remains_valid(self):audit(self.job())
    def test_explicit_false_remains_valid(self):audit(self.job(**{'continue-on-error':False}))
    def test_job_level_true_rejected(self):
        with self.assertRaises(ValueError):audit(self.job(**{'continue-on-error':True}))
    def test_dynamic_suppression_rejected(self):
        with self.assertRaises(ValueError):audit(self.job(**{'continue-on-error':'${{ matrix.experimental }}'}))
    def test_string_true_rejected(self):
        with self.assertRaises(ValueError):audit(self.job(**{'continue-on-error':'true'}))

if __name__=='__main__':unittest.main()
