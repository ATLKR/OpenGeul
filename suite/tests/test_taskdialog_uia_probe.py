"""Pure readiness/binding checks; real UIA evidence comes only from Windows CI."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'suite/e2e/taskdialog_uia_probe.py'

def module():
    assert SOURCE.is_file(),'Owned TaskDialog observer is required'
    spec=importlib.util.spec_from_file_location('taskdialog_probe',SOURCE)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

class TaskDialogProbeTests(unittest.TestCase):
    def sample(self):
        return dict(pid=123,creationTime=123456789012345678,ownerHwnd=10,dialogHwnd=20,
            caption='OpenGeul Calc',dialogOwner=10,visible=True,enabled=True,
            uiaRoot=dict(pid=123,nativeHwnd=20,runtimeId=[42,20]),queryErrors=[],
            controls=[dict(name='변경 내용을 저장하시겠습니까?',controlType=50020),
                      *[dict(name=name,controlType=50000,visible=True,enabled=True,parentTitleBar=name=='Close')
                        for name in ('저장','저장하지 않음','취소','Close')]])

    def test_actual_taskdialog_source_matches_product_and_runtime(self):
        m=module();project,source=m.stub_sources()
        product=(ROOT/'suite/shell/OfficeDocumentForm.cs').read_text()
        for literal in ('변경 내용을 저장하시겠습니까?','저장하지 않음을 선택하면 변경 내용이 사라집니다.','저장하지 않음','취소'):
            self.assertIn(literal,source);self.assertIn(literal,product)
        for literal in ('TaskDialog.ShowDialog(owner, page)','DefaultButton = save','AllowCancel = true','TaskDialogIcon.Information'):
            self.assertIn(literal,source)
        self.assertIn('8.0.32',project);self.assertIn('PerMonitorV2',project)
        self.assertNotIn('MessageBox.Show',source)

    def test_titlebar_close_is_preserved_in_observational_stability_without_product_qualification(self):
        m=module();sample=self.sample();binding=dict(pid=123,creationTime=123456789012345678,ownerHwnd=10)
        self.assertTrue(m.sample_ready(sample,binding))
        result=m.stable_pair([dict(at=1.,sample=sample),dict(at=1.2,sample=copy.deepcopy(sample))],deadline=20.)
        self.assertIsNotNone(result)
        self.assertEqual(4,len([row for row in result['sample']['controls'] if row['controlType']==50000]))
        self.assertEqual('Close',result['sample']['controls'][-1]['name'])

    def test_foreign_generation_owner_root_and_query_errors_never_ready(self):
        m=module();binding=dict(pid=123,creationTime=123456789012345678,ownerHwnd=10)
        for key,value in [('pid',124),('creationTime',123456789012345679),('ownerHwnd',11),('dialogOwner',11),
                          ('queryErrors',[dict(operation='UIA.FindAll',error='denied')]),('visible',False)]:
            sample=self.sample();sample[key]=value
            with self.subTest(key=key):self.assertFalse(m.sample_ready(sample,binding))
        sample=self.sample();sample['uiaRoot']['pid']=124
        self.assertFalse(m.sample_ready(sample,binding))

    def test_stability_needs_original_deadline_and_two_separate_equal_samples(self):
        m=module();sample=self.sample()
        for rows in ([dict(at=1.,sample=sample)],
                     [dict(at=1.,sample=sample),dict(at=1.01,sample=sample)],
                     [dict(at=19.9,sample=sample),dict(at=20.1,sample=sample)]):
            self.assertIsNone(m.stable_pair(rows,deadline=20.))
        different=copy.deepcopy(sample);different['controls'][-1]['enabled']=False
        self.assertIsNone(m.stable_pair([dict(at=1.,sample=sample),dict(at=1.2,sample=different)],deadline=20.))

    def test_workflow_is_lightweight_and_keeps_original_failure_evidence(self):
        path=ROOT/'.github/workflows/office-taskdialog-uia-probe.yml'
        self.assertTrue(path.is_file(),'Focused UIA workflow is required')
        text=path.read_text();self.assertIn('windows-2025',text);self.assertIn('if: always()',text)
        self.assertIn('pywinauto==0.6.9 Pillow==12.3.0',text)
        self.assertNotIn('build-suite.ps1',text);self.assertNotIn('LibreOffice',text)

if __name__=='__main__':unittest.main()
