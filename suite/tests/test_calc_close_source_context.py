"""Synthetic Calc Ctrl+W caller glue; no Full receipt, ZIP or Windows input."""
import ast
import contextlib
import copy
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import yaml

ROOT=Path(__file__).resolve().parents[2]
E2E=ROOT/'suite/e2e'
if str(E2E) not in sys.path:sys.path.insert(0,str(E2E))
PATH=E2E/'calc_close_probe.py'
DIGEST='a'*64
COMMAND='python suite/e2e/calc_close_probe.py --suite $env:SUITE_PACKAGE --fixtures .work/suite-engine/fixtures --output .work/suite-calc-close'

def load():
    spec=importlib.util.spec_from_file_location('calc_close_source_glue',PATH)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

def call_expression(name):
    tree=ast.parse(PATH.read_text())
    rows=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and
        ((isinstance(n.func,ast.Attribute) and n.func.attr==name) or isinstance(n.func,ast.Name) and n.func.id==name)]
    if len(rows)!=1:raise AssertionError('Expected one unchanged owned observation callsite')
    return compile(ast.Expression(rows[0]),'<owned-source-glue>','eval')

class CalcCloseSourceContextTests(unittest.TestCase):
    def setUp(self):self.api=load()
    def case(self,context):
        self.assertIn('source_admission',inspect.signature(self.api.CalcCloseCase).parameters,
            'Missing optional opaque Calc close reader context')
        folder=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (folder/'out').mkdir()
        obj=self.api.CalcCloseCase(folder/'suite',folder/'fixtures',folder/'out','cancel',prepared_library=object(),source_admission=context)
        obj._source_inventory_sha256=DIGEST;obj.process=NS(pid=11);obj.creation=12
        obj.hwnd,obj.parent,obj.child,obj.office_pid=13,14,15,16
        obj.source=folder/'OpenGeul-calc.xlsx'
        return obj
    def test_both_live_reader_phases_and_cleanup_forward_the_same_context_inventory(self):
        import writer_model_reader as reader
        for context in (None,object()):
            obj=self.case(context);seen=[];clean=[]
            def constructor(*args,**options):
                seen.append(options)
                return NS(start=lambda deadline:dict(bindingBefore=dict(owner=1)),close=lambda deadline:dict(kind='closed'))
            with patch.object(reader,'OwnedModelReader',side_effect=constructor),patch.object(reader,'require_model_reader_cleanup',side_effect=lambda *a,**k:clean.append(k)):
                for folder in ('before-close-reader','after-cancel-reader'):
                    before=obj.start_reader(folder);obj.close_reader(before['bindingBefore'])
            self.assertEqual(len(seen),2);self.assertEqual(len(clean),2)
            for options in seen+clean:
                if context is None:self.assertNotIn('source_admission',options);self.assertNotIn('inventory_sha256',options)
                else:self.assertIs(options.get('source_admission'),context);self.assertEqual(options.get('inventory_sha256'),DIGEST)
            self.assertEqual(seen[0]['getter_contract'],self.api.calc_save.PENDING_GETTERS)
            self.assertEqual(seen[1]['getter_contract'],self.api.calc_save.LEGACY_PENDING_GETTERS)
    def test_pending_and_cancel_actual_call_expressions_forward_opaque_context(self):
        context=object();obj=self.case(context);received=[];observation=dict(bindingBefore=dict(owner=1))
        obj.baseline={};obj.record=dict(originalShell={})
        def capture(*args,**options):received.append(options)
        pending=call_expression('require_pending_input_observations')
        scope=dict(self=obj,before=observation,selected={},editing={},pending={},inventory={},identity=dict(sha256=DIGEST),marker=self.api.marker,calc_save=NS(require_pending_input_observations=capture),native=self.api.native)
        eval(pending,scope)
        cancel=call_expression('require_owned_model_observation')
        eval(cancel,dict(self=obj,after=observation,require_owned_model_observation=capture,calc_model_barrier=self.api.calc_model_barrier,calc_save=self.api.calc_save,native=self.api.native))
        for options in received:self.assertIs(options.get('source_admission'),context);self.assertEqual(options.get('inventory_sha256'),DIGEST)
    def test_same_inventory_is_captured_before_first_reader_and_not_from_raw_context(self):
        source=PATH.read_text();start=source.index("identity,data=_packaged_identity_file(self.suite,'suite-inventory.json')")
        self.assertIn("self._source_inventory_sha256=identity['sha256']",source[start:source.index("before=self.start_reader('before-close-reader')",start)])
        self.assertEqual(source.count("_packaged_identity_file(self.suite,'suite-inventory.json')"),1)
    def cli_paths(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        for part in ('suite','fixtures'):(root/part).mkdir()
        return root
    def test_explicit_cli_calls_existing_readonly_full_factory_before_any_launch_or_setup(self):
        import native_menu_source_admission as admission
        import native_menu_source_selection as selection
        class StopAtReadOnlyFactory(Exception):pass
        for arch in ('x64','arm64'):
            root=self.cli_paths();calls=[]
            def factory(suite,**options):calls.append((suite,options));raise StopAtReadOnlyFactory()
            argv=['probe','--suite',str(root/'suite'),'--fixtures',str(root/'fixtures'),'--output',str(root/'out'),'--source-qualified-reader',arch]
            with patch.object(self.api,'os',NS(name='nt')),patch.object(sys,'argv',argv),\
                    patch.object(selection,'_input_paths',return_value=(object(),(root/'external-engine-input',),(root/'external-receipt-input',))) as fixed,\
                    patch.object(admission,'admit_source_menu_runtime',side_effect=factory),\
                    patch.object(self.api.native,'prepare_ascii_cohort',side_effect=AssertionError('Setup preceded source admission')):
                try:
                    with contextlib.redirect_stderr(io.StringIO()):self.api.main()
                except StopAtReadOnlyFactory:pass
                except SystemExit:self.fail('Missing explicit source-qualified reader CLI')
                else:self.fail('Read-only Full factory was not reached')
            self.assertEqual(fixed.call_args.args,(arch,));self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][1]['architecture'],arch)
            self.assertFalse((root/'out').exists())
    def test_main_threads_one_context_to_all_choices_without_claiming_case_success(self):
        self.assertIn('--source-qualified-reader',PATH.read_text(),'Missing explicit Calc close source CLI')
        root=self.cli_paths();context=object();seen=[]
        class Case:
            def __init__(self,*args,**kwargs):seen.append(kwargs)
            def run(self):return dict(success=False)
        argv=['probe','--suite',str(root/'suite'),'--fixtures',str(root/'fixtures'),'--output',str(root/'out'),'--source-qualified-reader','arm64']
        with patch.object(self.api,'os',NS(name='nt')),patch.object(sys,'argv',argv),\
                patch.object(self.api.calc_save,'_admit_source_reader',return_value=context),\
                patch.object(self.api.native,'prepare_ascii_cohort',return_value=object()),\
                patch.object(self.api.native,'collect_cases',side_effect=lambda defs,out:[fn() for _,fn in defs]),\
                patch.object(self.api,'CalcCloseCase',Case),patch.object(self.api,'report',return_value=dict(success=False)):
            self.assertEqual(self.api.main(),1)
        self.assertEqual(len(seen),3)
        for options in seen:self.assertIs(options.get('source_admission'),context)
    def test_budget_and_engine_only_reopen_are_unchanged(self):
        source=PATH.read_text()
        self.assertIn('self.deadline=time.monotonic()+calc_model_barrier.MAX_SECONDS',source)
        tree=ast.parse(source);method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='reopen')
        self.assertNotIn('--source-qualified-reader',ast.get_source_segment(source,method))
    def test_generic_verify_reopen_cannot_combine_with_live_source_context(self):
        root=self.cli_paths();argv=['probe','--suite',str(root/'suite'),'--fixtures',str(root/'fixtures'),'--output',str(root/'out'),
            '--source-qualified-reader','arm64','--verify-reopen']
        with patch.object(sys,'argv',argv),patch.object(self.api.calc_save,'_admit_source_reader',side_effect=AssertionError('Generic verify reached live admission')):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):self.api.main()
        self.assertFalse((root/'out').exists())

class CalcCloseSourceWorkflowTests(unittest.TestCase):
    def step(self):
        data=yaml.safe_load((ROOT/'.github/workflows/office-suite.yml').read_text())
        rows=[s for j in data['jobs'].values() for s in j.get('steps',[]) if s.get('id')=='calc-close']
        self.assertEqual(len(rows),1);return rows[0]
    def invoke(self,runtime_format,architecture,mode='acceptance'):
        shell=shutil.which('pwsh');self.assertIsNotNone(shell)
        run=self.step()['run'];line=next(s for s in run.splitlines() if COMMAND in s)
        script="$ErrorActionPreference='Stop'\n$global:LASTEXITCODE=0\n"+run.replace(line,'Write-Output (ConvertTo-Json -Compress @{args=@($sourceReaderArgs)})').replace('${{ matrix.architecture }}',architecture)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'args.ps1';path.write_text(script)
            env=dict(PATH=str(Path(shell).parent),SUITE_RUNTIME_FORMAT=runtime_format,OPENGEUL_SUITE_RUN_MODE=mode,PYTHONUTF8='1')
            if os.name=='nt':env['SystemRoot']=os.environ.get('SystemRoot',r'C:\Windows')
            else:env['PATH']+=os.pathsep+'/usr/bin'+os.pathsep+'/bin'
            return subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(path)],env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=15)
    def test_acceptance_source_native_architectures_get_two_explicit_arguments(self):
        for arch in ('x64','arm64'):
            result=self.invoke('source-built-zip',arch);self.assertEqual(result.returncode,0)
            self.assertEqual(json.loads(result.stdout),dict(args=['--source-qualified-reader',arch]))
    def test_msi_and_ime_diagnostic_keep_empty_arguments(self):
        for format,arch,mode in [('msi','x64','acceptance'),('source-built-zip','arm64','ime-mode-diagnostic')]:
            result=self.invoke(format,arch,mode);self.assertEqual(result.returncode,0);self.assertEqual(json.loads(result.stdout),dict(args=[]))
    def test_unknown_acceptance_format_or_source_architecture_fail_closed(self):
        self.assertNotEqual(self.invoke('unknown','arm64').returncode,0)
        self.assertNotEqual(self.invoke('source-built-zip','x86').returncode,0)
    def test_original_calc_close_acceptance_and_diagnostic_if_is_unchanged(self):
        self.assertEqual(self.step()['if'],"(env.OPENGEUL_SUITE_RUN_MODE == 'acceptance' || (env.OPENGEUL_SUITE_RUN_MODE == 'ime-mode-diagnostic' && matrix.architecture == 'arm64')) && (!cancelled() && steps.fixtures.outcome == 'success')")

if __name__=='__main__':unittest.main()
