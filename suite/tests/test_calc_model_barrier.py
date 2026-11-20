"""Portable Calc model policy; synthetic raw receipts are not Windows proof."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from test_writer_model_barrier import synthetic_frame, original_shell_fixture, retime_native_cleanup_fixture
from test_writer_model_reader import native_fixture, cleanup_fixture

SOURCE = Path(__file__).resolve().parents[1] / 'e2e/calc_model_barrier.py'


def workbook(a1='Engine-OpenGeul-calc 한글', target='worksheets/actual.xml', b1='17', formula='SUM(B1:C1)'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Smoke" sheetId="9" r:id="chosen"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="chosen" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="'+target+'"/></Relationships>')
        z.writestr('xl/worksheets/actual.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>'+a1+'</t></is></c><c r="B1" t="n"><v>'+b1+'</v></c><c r="C1" t="n"><v>25</v></c><c r="D1" t="n"><f>'+formula+'</f><v>42</v></c></row></sheetData></worksheet>')
        z.writestr('xl/worksheets/sheet1.xml', '<wrong/>')
    return stream.getvalue()


def observation(frame, text, start=0., end=0., modified=False):
    import writer_model_reader as reader
    value=dict(kind='existing-owned-calc-cells',sheetIndex=0,a1Text=text,b1Value=17.,c1Value=25.,
        d1Formula='=SUM(B1:C1)',d1Value=42.,isModified=modified,
        bindingBefore=copy.deepcopy(frame.binding),bindingAfter=copy.deepcopy(frame.binding),
        pythonIdentity=copy.deepcopy(frame.identity),retainedProcessHandle=True,handleSignaled=False,
        readOnlyObservation=True,sameFrameControllerModelVerified=True,readCallCleanupSucceeded=True,
        readerStillRetained=True,readStartedAt=start,readFinishedAt=end,operations=list(reader.CALC_OPERATIONS))
    value.update(native_fixture(frame.binding,str(frame.suite)))
    for row in value['unoSnapshots'].values():row['modelService']='com.sun.star.sheet.SpreadsheetDocument'
    return value


class CalcPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api=None
        if not SOURCE.is_file():return
        spec=importlib.util.spec_from_file_location('calc_policy_under_test',SOURCE)
        cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def setUp(self):
        self.assertIsNotNone(self.api,'RED: strict readonly Calc model completion policy is required')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.frame=synthetic_frame(Path(self.temp.name)/'Suite','unused')
        self.frame.binding['documentUrl']='file:///C:/original.xlsx'
        self.baseline=self.api.baseline_from_ooxml(workbook())
        self.marker='UI-OpenGeul-calc';self.initial=self.baseline['a1Text']
        self.before=observation(self.frame,self.initial)

    def plan(self, before=None, **kw):
        return self.api.freeze_expectation(self.frame.binding,self.baseline,self.marker,before or self.before,
            suite_root=self.frame.suite,original_shell=original_shell_fixture(self.frame.binding,self.frame.suite),
            inventory=self.frame.inventory,inventory_sha256=self.frame.inventory_sha256,
            expected_url='file:///C:/original.xlsx',started_at=0.,**kw)

    def clean(self, plan, at=1.):
        value=cleanup_fixture(self.frame.binding,str(self.frame.suite));value['kind']='owned-calc-reader-cleanup'
        value.update(startedAt=at,finishedAt=at+.01,deadline=plan.deadline)
        retime_native_cleanup_fixture(value)
        return value

    def completed(self):
        plan=self.plan();clock=[.1];record={}
        def read(deadline):
            begin=clock[0];clock[0]+=.1
            return observation(self.frame,self.initial+self.marker,begin,clock[0],True)
        self.api.await_completion(plan,read,clock=lambda:clock[0],pause=lambda delay:None,record=record)
        cleanup=self.clean(plan,clock[0]);clock[0]=cleanup['finishedAt']
        self.api.finalize_completion(plan,record,cleanup,clock[0])
        return plan,record

    def test_baseline_resolves_first_sheet_relationship_and_hashes_independent_bytes(self):
        raw=workbook();value=self.api.baseline_from_ooxml(raw)
        self.assertEqual(value['worksheetPart'],'xl/worksheets/actual.xml')
        self.assertEqual(value['sourceSha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['sourceBytes'],len(raw))
        self.assertEqual(value['a1Text'],'Engine-OpenGeul-calc 한글')
        self.assertEqual((value['b1Value'],value['c1Value'],value['d1Formula'],value['d1Value']),(17,25,'=SUM(B1:C1)',42))

    def test_baseline_rejects_external_escaped_duplicate_and_changed_control_cells(self):
        for raw in [workbook(target='../../foreign.xml'),workbook(target='https://other/sheet.xml'),workbook(b1='18'),workbook(formula='SUM(B1:B1)')]:
            with self.subTest(raw=hashlib.sha256(raw).hexdigest()),self.assertRaises((AssertionError,ValueError,KeyError)):
                self.api.baseline_from_ooxml(raw)
        raw=io.BytesIO(workbook())
        with zipfile.ZipFile(raw,'a') as z:
            with self.assertWarns(UserWarning):z.writestr('xl/workbook.xml','<wrong/>')
        with self.assertRaises(AssertionError):self.api.baseline_from_ooxml(raw.getvalue())

    def test_freeze_requires_independent_clean_before_input_and_exact_expected_url(self):
        for field,value in [('a1Text',self.initial+'x'),('isModified',True),('b1Value',True),('d1Value',float('nan'))]:
            changed=copy.deepcopy(self.before);changed[field]=value
            with self.subTest(field=field),self.assertRaises(AssertionError):self.plan(changed)
        changed=copy.deepcopy(self.frame.binding);changed['documentUrl']='file:///C:/other.xlsx'
        with self.assertRaises(AssertionError):
            self.api.freeze_expectation(changed,self.baseline,self.marker,self.before,suite_root=self.frame.suite,
                original_shell=original_shell_fixture(changed,self.frame.suite),inventory=self.frame.inventory,
                inventory_sha256=self.frame.inventory_sha256,expected_url='file:///C:/original.xlsx',started_at=0.)

    def test_only_monotonic_exact_ordered_prefix_is_pending_and_full_equality_completes(self):
        plan=self.plan();previous=self.initial
        for n in [0,1,3,len(self.marker)]:
            text=self.initial+self.marker[:n];row=observation(self.frame,text,1.,1.,bool(n))
            self.assertEqual(self.api.validate_observation(plan,row,previous),'complete' if n==len(self.marker) else 'pending')
            previous=text
        for text in [self.initial+'IU-',self.initial+self.marker+self.marker,self.initial[1:]+self.marker,self.initial+self.marker+'\n',self.initial+'ui-OpenGeul-calc']:
            with self.subTest(text=text),self.assertRaises(AssertionError):
                self.api.validate_observation(plan,observation(self.frame,text,1.,1.,True),self.initial)
        with self.assertRaises(AssertionError):
            self.api.validate_observation(plan,observation(self.frame,self.initial,1.,1.),self.initial+'UI')

    def test_pending_cannot_hide_control_cell_service_generation_or_python_changes(self):
        plan=self.plan()
        for field,value in [('sheetIndex',True),('b1Value',True),('c1Value',float('inf')),('d1Value',41),('d1Formula','=SUM(B1:B1)')]:
            row=observation(self.frame,self.initial,1.,1.);row[field]=value
            with self.subTest(field=field),self.assertRaises(AssertionError):self.api.validate_observation(plan,row,self.initial)
        for path,value in [(('unoSnapshots','after','modelService'),'com.sun.star.text.TextDocument'),
                           (('bindingAfter','officeCreationTime'),999),
                           (('pythonIdentity','files','uno','sha256'),'0'*64)]:
            row=observation(self.frame,self.initial,1.,1.);target=row
            for key in path[:-1]:target=target[key]
            target[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(AssertionError):self.api.validate_observation(plan,row,self.initial)

    def test_exact_full_text_requires_modified_and_no_string_normalization(self):
        plan=self.plan()
        for text,modified in [(self.initial+self.marker,False),(self.initial.replace('한글','한글')+self.marker,True)]:
            with self.assertRaises(AssertionError):self.api.validate_observation(plan,observation(self.frame,text,1.,1.,modified),self.initial)

    def test_single_budget_and_read_limit_fail_closed_without_reusing_receipt(self):
        plan=self.plan();record={};calls=[]
        def read(deadline):calls.append(deadline);return observation(self.frame,self.initial,1.,1.)
        with self.assertRaisesRegex(AssertionError,'limit'):
            self.api.await_completion(plan,read,clock=lambda:1.,pause=lambda _:None,record=record,max_reads=2)
        self.assertEqual(calls,[12.,12.]);self.assertFalse(record['success'])
        with self.assertRaises(AssertionError):self.api.await_completion(plan,read,clock=lambda:1.,pause=lambda _:None,record=record)
        with self.assertRaises(AssertionError):self.plan(timeout_seconds=13.)

    def test_total_model_read_limit_includes_the_before_input_read(self):
        calls=[]
        def read(deadline):
            calls.append(deadline)
            return observation(self.frame,self.initial,1.,1.)
        with self.assertRaises(AssertionError):
            self.api.await_completion(self.plan(),read,
                clock=lambda:1.,pause=lambda _:None,record={},max_reads=120)
        self.assertEqual(calls,[])

    def test_model_equality_without_normal_same_reader_cleanup_never_qualifies(self):
        plan,good=self.completed()
        for key,value in [('terminated',True),('finalJobPids',[99]),('errors',[{'error':'cleanup'}])]:
            record=dict(state='model-complete',success=True,modelEqualityAt=.2)
            cleanup=self.clean(plan,.2);cleanup[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.finalize_completion(plan,record,cleanup,.3)
            self.assertFalse(record['success'])

    def test_full_receipt_replay_is_pure_and_uses_external_baseline_inventory_url(self):
        plan,record=self.completed()
        kwargs=dict(suite_root=self.frame.suite,inventory=self.frame.inventory,
            inventory_sha256=self.frame.inventory_sha256,binding=self.frame.binding,
            baseline=self.baseline,expected_url='file:///C:/original.xlsx',marker=self.marker)
        with patch.object(Path,'read_bytes',side_effect=AssertionError('filesystem replay forbidden')):
            replay=self.api.replay_completion(record,**kwargs)
        self.assertEqual(replay['expectedA1'],self.initial+self.marker)
        self.assertFalse(record['productFixEstablished'])
        for key,value in [('baseline',dict(self.baseline,a1Text='foreign')),('inventory_sha256','0'*64),('expected_url','file:///C:/other.xlsx')]:
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.replay_completion(record,**dict(kwargs,**{key:value}))
        for mutate in [lambda r:r['observations'][0].update(decision='pending'),
                       lambda r:r.update(finishedAt=13.),lambda r:r.update(productFixEstablished=True),
                       lambda r:r.update(startedAt=999.),lambda r:r.update(originalShell={}),
                       lambda r:r.update(beforeInput={}),
                       lambda r:r['cleanup']['releaseAcknowledgement'].update(readerPid=100)]:
            bad=copy.deepcopy(record);mutate(bad)
            with self.assertRaises(AssertionError):self.api.replay_completion(bad,**kwargs)

    def test_duplicate_raw_fields_preserve_types_instead_of_python_numeric_equality(self):
        plan,record=self.completed();record['beforeInput']['sheetIndex']=False
        with self.assertRaises(AssertionError):
            self.api.replay_completion(record,suite_root=self.frame.suite,inventory=self.frame.inventory,
                inventory_sha256=self.frame.inventory_sha256,binding=self.frame.binding,
                baseline=self.baseline,expected_url='file:///C:/original.xlsx',marker=self.marker)

    def test_frozen_expectation_rejects_boolean_schema_instead_of_integer_one(self):
        plan,record=self.completed();record['expectation']['schemaVersion']=True
        with self.assertRaises(AssertionError):
            self.api.replay_completion(record,suite_root=self.frame.suite,inventory=self.frame.inventory,
                inventory_sha256=self.frame.inventory_sha256,binding=self.frame.binding,
                baseline=self.baseline,expected_url='file:///C:/original.xlsx',marker=self.marker)


if __name__=='__main__':unittest.main()
