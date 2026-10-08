import copy
import importlib.util
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class PolicyTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'policy.py'
        self.assertTrue(path.exists(),'Missing free-only CI policy')
        spec=importlib.util.spec_from_file_location('ci_policy',path)
        self.p=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.p)
        self.workflow={'on':{'push':None},'jobs':{'test':{
            'if':'github.event.repository.private == false', 'runs-on':'ubuntu-24.04', 'timeout-minutes':10,
            'steps':[{'uses':'actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09','with':{'persist-credentials':False}}]}}}
    def test_standard_public_is_allowed(self):self.p.audit(self.workflow)
    def test_larger_self_hosted_and_custom_labels_rejected(self):
        for runner in ('ubuntu-24.04-16core','self-hosted','windows-latest-large',{'group':'paid'},['self-hosted','windows']):
            with self.subTest(runner=runner):
                self.workflow['jobs']['test']['runs-on']=runner
                with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_unknown_expression_cannot_select_a_paid_runner(self):
        self.workflow['jobs']['test']['runs-on']='${{ inputs.runner }}'
        with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_static_standard_matrix_allowed(self):
        job=self.workflow['jobs']['test'];job['runs-on']='${{ matrix.os }}'
        job['strategy']={'matrix':{'os':['windows-2022','windows-2025']},'max-parallel':2}
        self.p.audit(self.workflow)
    def test_matrix_include_cannot_override_a_runner(self):
        job=self.workflow['jobs']['test'];job['runs-on']='${{ matrix.os }}'
        job['strategy']={'matrix':{'os':['windows-2022'],'include':[{'os':'windows-64core'}]}}
        with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_no_private_repo_jobs(self):
        for condition in (None,'always()','github.event.repository.private == false || true','!github.event.repository.private'):
            self.workflow['jobs']['test']['if']=condition
            with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_nested_visibility_guard_allowed(self):
        self.workflow['jobs']['test']['if']="github.event.repository.private == false && (github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
        self.p.audit(self.workflow)
    def test_missing_timeout_and_excessive_timeout_fail(self):
        for value in (None,0,361,'${{ inputs.timeout }}'):
            self.workflow['jobs']['test']['timeout-minutes']=value
            with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_pinned_unapproved_action_is_not_implicitly_free(self):
        self.workflow['jobs']['test']['steps']=[{'uses':'external/paid-runner@'+'a'*40}]
        with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_moving_action_versions_fail(self):
        self.workflow['jobs']['test']['steps']=[{'uses':'actions/checkout@v6'}]
        with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_automatic_cache_and_custom_image_fail(self):
        for config in ({'snapshot':'saved-image'},{'container':'paid/custom'}):
            bad=copy.deepcopy(self.workflow);bad['jobs']['test'].update(config)
            with self.assertRaises(ValueError):self.p.audit(bad)
        self.workflow['jobs']['test']['steps']=[{'uses':'actions/cache@'+'a'*40}]
        with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_setup_cache_opt_in_fails(self):
        self.workflow['jobs']['test']['steps']=[{'uses':'actions/setup-node@'+'a'*40,'with':{'cache':'pnpm'}}]
        with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_uploads_need_one_day_retention(self):
        for days in (None,0,2,90):
            self.workflow['jobs']['test']['steps']=[{'uses':'actions/upload-artifact@'+'a'*40,'with':{'path':'out','retention-days':days}}]
            with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_pull_request_target_is_rejected(self):
        self.workflow['on']={'pull_request_target':None}
        with self.assertRaises(ValueError):self.p.audit(self.workflow)
    def test_free_mode_does_not_change_push_or_pr(self):
        for event in ('push','pull_request','schedule'):
            self.assertEqual(self.p.select_mode(event,{'mode':'checks'}),'full')
    def test_manual_modes_are_explicit(self):
        for mode in ('checks','engine','full'):
            self.assertEqual(self.p.select_mode('workflow_dispatch',{'mode':mode}),mode)
        with self.assertRaises(ValueError):self.p.select_mode('workflow_dispatch',{'mode':'skip-all'})
    def test_unknown_visibility_fails_before_heavy_work(self):
        for value in (True,None,'false',0):
            with self.assertRaises(ValueError):self.p.require_public({'repository':{'private':value}})
        self.p.require_public({'repository':{'private':False}})

if __name__=='__main__':unittest.main()
