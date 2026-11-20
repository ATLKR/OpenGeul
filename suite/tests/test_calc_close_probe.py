"""Portable probe oracles; no Windows execution is implied."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
from test_calc_model_barrier import workbook


class CalcCloseProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api=None
        path=Path(__file__).resolve().parents[1]/'e2e/calc_close_probe.py'
        if path.is_file():
            spec=importlib.util.spec_from_file_location('calc_close_probe_under_test',path)
            cls.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.api)

    def setUp(self):
        self.assertIsNotNone(self.api,'RED: separate current-behavior CtrlW probe is required')
        self.raw=workbook();self.baseline=self.api.calc_save.read_cells(self.raw)

    def test_measured_choice_refuses_an_extra_client_action_without_clicking(self):
        import test_generated_calc_close as fixtures
        f=fixtures.GeneratedCalcCloseTests();f.setUp();self.addCleanup(f.doCleanups)
        Desktop,accessible,buttons,_,_,pane,_=f.titlebar_boundary()
        buttons.append(NS(element_info=NS(handle=40,process_id=7,runtime_id=[42,40],name='Unexpected client action',
            control_type='Button',parent=pane,automation_id='CommandButton_103',class_name='CCPushButton'),
            is_visible=lambda:True,is_enabled=lambda:True))
        case=object.__new__(self.api.CalcCloseCase)
        case.api=f.windows;case.process=f.process;case.hwnd=10;case.choice='discard';case.record={}
        case.dialog=lambda owner,title,**options:(30,accessible);case.screenshot=lambda *a:None
        with patch.dict(sys.modules,{'pywinauto':NS(Desktop=Desktop)}), \
             patch('windows_smoke.wait_for',side_effect=lambda check,seconds=60:check() or (_ for _ in ()).throw(AssertionError('not ready'))), \
             self.assertRaises(AssertionError):
            case.choose_existing_prompt()
        self.assertEqual([],f.clicks);self.assertEqual([],f.closes)

    def test_no_enter_original_close_contract_is_exact_and_has_no_focus_action(self):
        row=dict(choice='save',navigationKeys=['^{HOME}','{F2}','^{END}'],commitKeys=[],
            marker=self.api.marker('save'),closeShortcutCount=1,
            beforeCloseActions=['observe-uncommitted','observer-closed','ctrl-w'],uncommittedBeforeCloseVerified=True,
            pendingInputTextVerified=True)
        self.api.require_original_close(row)
        for key,value in [('commitKeys',['{ENTER}']),('closeShortcutCount',2),
                          ('beforeCloseActions',['observe-uncommitted','observer-closed','set-focus','ctrl-w']),
                          ('uncommittedBeforeCloseVerified',False),('pendingInputTextVerified',False)]:
            changed=dict(row);changed[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.require_original_close(changed)

    def test_prompt_must_offer_all_three_exact_suite_choices(self):
        self.api.require_three_choices(['저장','저장하지 않음','취소'])
        for labels in [['저장','취소'],['저장','저장','취소'],['Save','Discard','Cancel']]:
            with self.assertRaises(AssertionError):self.api.require_three_choices(labels)

    def test_save_requires_full_exact_marker_and_neighbor_formula_semantics(self):
        expected=self.baseline['a1Text']+self.api.marker('save')
        self.api.require_disk_outcome('save',self.raw,workbook(a1=expected),self.baseline)
        for raw in [self.raw,workbook(a1=expected+self.api.marker('save')),workbook(a1=expected,b1='18')]:
            with self.assertRaises(AssertionError):self.api.require_disk_outcome('save',self.raw,raw,self.baseline)

    def test_discard_and_cancel_must_preserve_exact_baseline_bytes_at_decision(self):
        for choice in ('discard','cancel'):
            self.api.require_disk_outcome(choice,self.raw,self.raw,self.baseline)
            with self.assertRaises(AssertionError):
                self.api.require_disk_outcome(choice,self.raw,workbook(a1=self.baseline['a1Text']+self.api.marker(choice)),self.baseline)

    def test_cancel_requires_full_input_proof_without_manufacturing_a_save(self):
        expected=self.baseline['a1Text']+self.api.marker('cancel')
        self.api.require_cancel_cells(dict(self.baseline,a1Text=expected,isModified=True),self.baseline)
        for text,modified in [(self.baseline['a1Text'],False),('lost',True),(expected,False)]:
            with self.subTest(text=text),self.assertRaises(AssertionError):
                self.api.require_cancel_cells(dict(self.baseline,a1Text=text,isModified=modified),self.baseline)

    def test_cancel_rebinds_native_generation_without_comparing_helper_local_proxy_ids(self):
        from writer_model_barrier import BINDING_KEYS
        original={key:1 for key in BINDING_KEYS}
        current=dict(original,frameIdentity='new-helper-frame',controllerIdentity='new-helper-controller',modelIdentity='new-helper-model')
        self.api.require_same_native_binding(original,current)
        for key in ('officeCreationTime','childHwnd','privatePipe','documentUrl'):
            changed=dict(current);changed[key]='foreign'
            with self.subTest(key=key),self.assertRaises(AssertionError):self.api.require_same_native_binding(original,changed)
        with self.assertRaises(AssertionError):self.api.require_same_native_binding({}, {})

    def test_aggregate_requires_all_three_cases_exactly_once_and_every_proof(self):
        rows=[dict(case='calc-close-'+choice,choice=choice,success=True,promptVerified=True,
                   originalCloseVerified=True,diskOutcomeVerified=True,packagedUnoVerified=True,cleanClose=True,choiceClickCount=1,
                   **({'cancelRetainedInputVerified':True,'cancelNoWriteThroughCleanupVerified':True} if choice=='cancel' else {}))
              for choice in self.api.CHOICES]
        self.assertTrue(self.api.report(rows)['success'])
        variants=[rows[:-1],rows+[copy.deepcopy(rows[0])]]
        for changed in variants:self.assertFalse(self.api.report(changed)['success'])
        changed=copy.deepcopy(rows);changed[2]['cancelRetainedInputVerified']=False
        self.assertFalse(self.api.report(changed)['success'])
        changed=copy.deepcopy(rows);changed[2]['cleanClose']=False
        self.assertFalse(self.api.report(changed)['success'])
        changed=copy.deepcopy(rows);changed[0]['choiceClickCount']=0
        self.assertFalse(self.api.report(changed)['success'])
        changed=copy.deepcopy(rows);changed[0]['success']=False
        self.assertFalse(self.api.report(changed)['success'])


if __name__=='__main__':unittest.main()
