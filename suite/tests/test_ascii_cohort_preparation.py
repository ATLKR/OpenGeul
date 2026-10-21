"""Compiler preparation precedes cohorts and never starts on verify/attach paths."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch, Mock


E2E=Path(__file__).resolve().parents[1]/'e2e'
def load(name):
    spec=importlib.util.spec_from_file_location('ascii_cohort_'+name,E2E/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class AsciiCohortPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.suite=self.root/'suite';self.suite.mkdir()
        self.fixtures=self.root/'fixtures';self.fixtures.mkdir();self.output=self.root/'evidence'
        (self.suite/'suite-inventory.json').write_text(json.dumps(dict(schemaVersion=1,architecture='arm64')))
        self.prepared={'kind':'test-only-prepared'}
    def args(self,*extra):
        return ['test','--suite',str(self.suite),'--fixtures',str(self.fixtures),'--output',str(self.output),*extra]
    def test_validated_inventory_prepares_once_with_exact_native_architecture(self):
        native=load('windows_smoke')
        with patch.object(native.ascii_input,'prepare_observer',return_value=self.prepared) as prepare:
            self.assertIs(self.prepared,native.prepare_ascii_cohort(self.suite,self.output))
        prepare.assert_called_once_with(self.output/'ascii-message-observer',architecture='arm64')
    def test_invalid_inventory_never_acquires_compiler(self):
        native=load('windows_smoke')
        (self.suite/'suite-inventory.json').write_text(json.dumps(dict(schemaVersion=True,architecture='x64')))
        with patch.object(native.ascii_input,'prepare_observer') as prepare:
            with self.assertRaises(AssertionError):native.prepare_ascii_cohort(self.suite,self.output)
        prepare.assert_not_called()
    def test_gui_prepares_before_any_case_and_reuses_one_descriptor_for_three_inputs(self):
        native=load('windows_smoke');events=[];seen=[]
        def prepare(*a):events.append('prepare');return self.prepared
        def edit(*a,**kw):events.append('edit');seen.append(kw['prepared_library']);return {}
        def run(cases,output):
            self.assertEqual(['prepare'],events)
            for name,case in cases:case()
            return 0
        with patch.object(native,'os',NS(name='nt')),patch.object(sys,'argv',self.args()), \
            patch.object(native,'prepare_ascii_cohort',side_effect=prepare) as prepared, \
            patch.object(native,'capture_home',return_value={}),patch.object(native,'edit_module',side_effect=edit), \
            patch.object(native,'attach_module',return_value={}),patch.object(native,'new_module',return_value={}), \
            patch.object(native,'run_cases',side_effect=run):
            self.assertEqual(0,native.main())
        self.assertEqual([self.prepared]*3,seen);prepared.assert_called_once()
    def test_failed_gui_preparation_never_launches_or_collects_case(self):
        native=load('windows_smoke')
        with patch.object(native,'os',NS(name='nt')),patch.object(sys,'argv',self.args()), \
            patch.object(native,'prepare_ascii_cohort',side_effect=RuntimeError('compiler failed')), \
            patch.object(native,'launch_suite') as launch,patch.object(native,'run_cases') as run:
            with self.assertRaisesRegex(RuntimeError,'compiler'):native.main()
        launch.assert_not_called();run.assert_not_called()
    def test_attach_only_adapter_does_not_prepare_a_physical_ascii_observer(self):
        native=load('windows_smoke')
        with patch.object(native,'prepare_ascii_cohort') as prepare,patch.object(native,'document_case',return_value={}) as case:
            native.attach_module(self.suite,self.fixtures,self.output,'draw','odg')
        prepare.assert_not_called();self.assertFalse(case.call_args.kwargs['physical_input'])
    def test_lifecycle_verify_only_skips_preparation_and_editor_launch(self):
        lifecycle=load('lifecycle_smoke')
        with patch.object(lifecycle,'os',NS(name='nt')),patch.object(lifecycle,'verify_saved_with_uno',return_value=0), \
            patch.object(lifecycle.native,'prepare_ascii_cohort') as prepare,patch.object(lifecycle.native,'launch_suite') as launch:
            result=lifecycle.main(['--suite',str(self.suite),'--output',str(self.output),'--verify-saved'])
        self.assertEqual(0,result);prepare.assert_not_called();launch.assert_not_called()
    def test_failed_lifecycle_or_calc_close_preparation_never_launches_case(self):
        for name in ('lifecycle_smoke','calc_close_probe'):
            with self.subTest(name=name):
                module=load(name);output=self.root/name
                args=self.args();args[args.index('--output')+1]=str(output)
                with patch.object(module,'os',NS(name='nt')),patch.object(sys,'argv',args), \
                    patch.object(module.native,'prepare_ascii_cohort',side_effect=RuntimeError('compiler failed')), \
                    patch.object(module.native,'launch_suite') as launch:
                    with self.assertRaisesRegex(RuntimeError,'compiler'):module.main()
                launch.assert_not_called()
    def test_calc_save_verify_reopen_skips_compiler_and_physical_case(self):
        module=load('calc_save_smoke');self.output.mkdir();(self.output/'fixtures').mkdir()
        source=self.output/'fixtures/OpenGeul-calc.xlsx';source.write_bytes(b'fixture-boundary')
        (self.output/'reopen-input.json').write_text(json.dumps(dict(baseline={},expected='expected')))
        args=['test','--suite',str(self.suite),'--output',str(self.output),'--verify-reopen','--owned-fixture',str(source)]
        with patch.object(module,'os',NS(name='nt')),patch.object(sys,'argv',args), \
            patch.object(module,'verify_reopen'),patch.object(module.native,'prepare_ascii_cohort') as prepare, \
            patch.object(module,'physical_case') as physical:
            self.assertEqual(0,module.main())
        prepare.assert_not_called();physical.assert_not_called()


if __name__=='__main__':unittest.main()
