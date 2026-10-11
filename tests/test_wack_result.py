from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
from wack_result import inspect


class WackReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.report=Path(self.tmp.name)/'wack.xml'
        self.xml='<REPORT OVERALL_RESULT="PASS" PARTIAL_RUN="FALSE" VALIDATION_TYPE="WindowsStore" APP_NAME="OpenGeul.App" APP_VERSION="1.1.2.0"><TEST NAME="launch"><RESULT>PASS</RESULT></TEST></REPORT>'
        self.report.write_text(self.xml)

    def check(self,code=0):return inspect(self.report,'OpenGeul.App','1.1.2.0',code)

    def test_complete_identity_matching_pass_records_report_hash(self):
        result=self.check();self.assertTrue(result['passed']);self.assertEqual(result['status'],'passed')
        self.assertEqual(len(result['reportSha256']),64)

    def test_exit_zero_does_not_hide_failed_warning_partial_interim_or_wrong_package_report(self):
        changes=[('OVERALL_RESULT="PASS"','OVERALL_RESULT="FAIL"'),
                 ('OVERALL_RESULT="PASS"','OVERALL_RESULT="WARNING"'),
                 ('PARTIAL_RUN="FALSE"','PARTIAL_RUN="TRUE"'),
                 ('VALIDATION_TYPE="WindowsStore"',''),
                 ('APP_NAME="OpenGeul.App"','APP_NAME="Other.App"'),
                 ('APP_VERSION="1.1.2.0"','APP_VERSION="1.1.1.0"')]
        for old,new in changes:
            self.report.write_text(self.xml.replace(old,new))
            with self.subTest(new=new):self.assertFalse(self.check()['passed'])
        self.report.write_text(self.xml);self.assertFalse(self.check(-2)['passed'])

    def test_missing_malformed_or_unsafe_report_is_a_failure(self):
        self.report.unlink();self.assertFalse(self.check()['passed'])
        for xml in ('<REPORT', '<!DOCTYPE REPORT><REPORT/>', '<other/>'):
            self.report.write_text(xml);self.assertFalse(self.check()['passed'])


if __name__=='__main__':unittest.main()
