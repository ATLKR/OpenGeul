from pathlib import Path
import copy
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

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


class CentennialWackReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.report=Path(self.tmp.name)/'wack.xml'
        self.fixture=Path(__file__).with_name('fixtures')/'wack-centennial-warning.xml'
        self.identity='AllenLabs.OpenGeul.Development'
        self.version='1.1.2.0'

    def check(self,code=0):return inspect(self.report,self.identity,self.version,code)

    def write(self,root):self.report.write_bytes(ET.tostring(root,encoding='utf-8'))

    def synthetic_pass(self):
        root=ET.parse(self.fixture).getroot()
        root.set('OVERALL_RESULT','PASS')
        for test in root.iter('TEST'):test.find('RESULT').text='PASS'
        return root

    def synthetic_optional_failure(self):
        root=ET.parse(self.fixture).getroot()
        root.find(".//TEST[@NAME='DPIAwarenessValidation']/RESULT").text='PASS'
        return root

    def test_actual_centennial_warning_stays_failed_with_correct_identity(self):
        self.report.write_bytes(self.fixture.read_bytes())
        result=self.check()
        self.assertFalse(result['passed'])
        self.assertFalse(result.get('submissionCheckPassed',False))
        self.assertEqual(result['overallResult'],'WARNING')
        self.assertEqual(result['identity'],self.identity)
        self.assertEqual(result['version'],self.version)
        self.assertEqual([(test['name'],test['result']) for test in result['nonPassingTests']],
                         [('Blocked executables','FAIL'),('DPIAwarenessValidation','WARNING')])

    def test_synthetic_complete_centennial_pass_uses_embedded_identity(self):
        self.write(self.synthetic_pass())
        result=self.check()
        self.assertTrue(result['passed'])
        self.assertTrue(result.get('submissionCheckPassed',False))
        self.assertEqual(result['identity'],self.identity)
        self.assertEqual(result['version'],self.version)

    def test_matching_nonblank_root_headers_are_consistent(self):
        root=self.synthetic_pass()
        root.set('APP_NAME',self.identity);root.set('APP_VERSION',self.version)
        self.write(root)
        self.assertTrue(self.check()['passed'])

    def test_wrong_expected_program_embedded_or_root_identity_is_rejected(self):
        self.write(self.synthetic_pass())
        self.assertFalse(inspect(self.report,'Other.App',self.version,0)['passed'])
        self.assertFalse(inspect(self.report,self.identity,'9.0.0.0',0)['passed'])
        cases=[('.', 'APP_NAME', 'Other.App'),('.', 'APP_VERSION', '9.0.0.0'),
               ('./APPLICATIONS/Installed_Programs/Program','Name','Other.App'),
               ('./APPLICATIONS/Installed_Programs/Program','Version','9.0.0.0'),
               ('.//PackageManifest/Package/Identity','Name','Other.App'),
               ('.//PackageManifest/Package/Identity','Version','9.0.0.0')]
        for path,key,value in cases:
            with self.subTest(path=path,key=key):
                root=self.synthetic_pass()
                root.find(path).set(key,value)
                self.write(root)
                self.assertFalse(self.check()['passed'])

    def test_missing_or_ambiguous_appx_program_or_identity_is_rejected(self):
        for change in ('missing-program','multiple-programs','missing-identity','multiple-identities','wrong-source'):
            with self.subTest(change=change):
                root=self.synthetic_pass()
                programs=root.find('./APPLICATIONS/Installed_Programs')
                program=programs.find('Program')
                package=program.find('.//PackageManifest/Package')
                if change=='missing-program':programs.remove(program)
                elif change=='multiple-programs':programs.append(copy.deepcopy(program))
                elif change=='missing-identity':package.remove(package.find('Identity'))
                elif change=='multiple-identities':package.append(copy.deepcopy(package.find('Identity')))
                else:program.set('Source','Other')
                self.write(root)
                self.assertFalse(self.check()['passed'])

    def test_centennial_partial_interim_or_bad_exit_is_rejected(self):
        for key,value in [('PARTIAL_RUN','TRUE'),('VALIDATION_TYPE','')]:
            with self.subTest(key=key):
                root=self.synthetic_pass();root.set(key,value);self.write(root)
                self.assertFalse(self.check()['passed'])
        self.write(self.synthetic_pass())
        self.assertFalse(self.check(1)['passed'])

    def test_optional_failure_allows_submission_check_without_claiming_wack_pass(self):
        self.write(self.synthetic_optional_failure())
        result=self.check()
        self.assertFalse(result['passed'])
        self.assertTrue(result.get('submissionCheckPassed',False))
        self.assertEqual(result['status'],'warning')
        self.assertEqual(result['overallResult'],'WARNING')
        self.assertEqual(result['nonPassingTests'][0]['result'],'FAIL')
        self.assertTrue(result['nonPassingTests'][0]['optional'])
        self.assertTrue(any('"cmd.exe"' in message for message in result['nonPassingTests'][0]['messages']))

    def test_required_warning_failure_or_unknown_result_blocks_submission_check(self):
        for value in ('WARNING','FAIL','UNKNOWN',''):
            with self.subTest(value=value):
                root=self.synthetic_optional_failure()
                root.find(".//TEST[@NAME='DPIAwarenessValidation']/RESULT").text=value
                self.write(root)
                self.assertFalse(self.check().get('submissionCheckPassed',False))

    def test_missing_or_unknown_optional_flag_is_required(self):
        for value in (None,'UNKNOWN'):
            with self.subTest(value=value):
                root=self.synthetic_optional_failure()
                test=root.find(".//TEST[@NAME='Blocked executables']")
                if value is None:test.attrib.pop('OPTIONAL')
                else:test.set('OPTIONAL',value)
                self.write(root)
                self.assertFalse(self.check().get('submissionCheckPassed',False))

    def test_empty_tests_or_required_set_blocks_submission_check(self):
        for empty in (True,False):
            with self.subTest(empty=empty):
                root=self.synthetic_pass()
                if empty:root.remove(root.find('REQUIREMENTS'))
                else:
                    for test in root.iter('TEST'):test.set('OPTIONAL','TRUE')
                self.write(root)
                result=self.check()
                self.assertFalse(result['passed'])
                self.assertFalse(result.get('submissionCheckPassed',False))

    def test_overall_failure_unknown_app_type_or_unknown_optional_result_is_rejected(self):
        for change in ('overall-fail','unknown-app-type','unknown-result'):
            with self.subTest(change=change):
                root=self.synthetic_optional_failure()
                if change=='overall-fail':root.set('OVERALL_RESULT','FAIL')
                elif change=='unknown-app-type':
                    root.set('APP_TYPE','Unknown');root.set('APP_NAME',self.identity);root.set('APP_VERSION',self.version)
                else:root.find(".//TEST[@NAME='Blocked executables']/RESULT").text='UNKNOWN'
                self.write(root)
                self.assertFalse(self.check().get('submissionCheckPassed',False))

    def test_duplicate_or_non_leaf_test_result_is_rejected(self):
        for change in ('duplicate','non-leaf'):
            with self.subTest(change=change):
                root=self.synthetic_pass()
                test=root.find(".//TEST[@NAME='DPIAwarenessValidation']")
                if change=='duplicate':ET.SubElement(test,'RESULT').text='FAIL'
                else:ET.SubElement(test.find('RESULT'),'OTHER').text='FAIL'
                self.write(root)
                self.assertFalse(self.check().get('submissionCheckPassed',False))

    def test_cli_emits_optional_findings_as_warnings_and_preserves_result(self):
        self.write(self.synthetic_optional_failure())
        output=Path(self.tmp.name)/'result.json'
        command=[sys.executable,str(Path(__file__).resolve().parents[1]/'e2e/wack_result.py'),
                 '--report',str(self.report),'--out',str(output),'--identity',self.identity,
                 '--version',self.version,'--exit-code','0']
        completed=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertIn('::warning::',completed.stdout)
        self.assertIn('blocked executable reference',completed.stdout)
        self.assertIn('"cmd.exe"',completed.stdout)
        messages=ET.parse(self.fixture).getroot().find(".//TEST[@NAME='Blocked executables']/MESSAGES")
        for message in messages:self.assertIn(message.get('TEXT'),completed.stdout)
        result=json.loads(output.read_text())
        self.assertFalse(result['passed'])
        self.assertTrue(result['submissionCheckPassed'])
        self.assertEqual(result['overallResult'],'WARNING')


if __name__=='__main__':unittest.main()
