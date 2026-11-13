"""Standalone Calc reader CLI contracts; no source17/Windows qualification."""
import ast
from contextlib import redirect_stdout, redirect_stderr
import importlib
import inspect
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/"e2e"
if str(SOURCE) not in sys.path:sys.path.insert(0,str(SOURCE))
calc=importlib.import_module("calc_save_smoke")

class CalcReaderCliContextTests(unittest.TestCase):
    def paths(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name).resolve();suite=root/"Suite";suite.mkdir()
        fixtures=root/"generated";fixtures.mkdir();output=root/"evidence"
        return suite,fixtures,output
    def command(self,suite,fixtures,output,*extra):
        return ["calc_save_smoke.py","--suite",str(suite),"--fixtures",str(fixtures),"--output",str(output),*extra]
    def run_main(self,args):
        with patch.object(calc,"os",SimpleNamespace(name="nt")),patch.object(sys,"argv",args),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            return calc.main()

    def test_default_reader_admission_is_absent_and_does_not_call_factory(self):
        with patch("native_menu_source_admission.admit_source_menu_runtime",side_effect=AssertionError("unexpected admission")) as factory:
            self.assertIsNone(calc._admit_source_reader(Path("/synthetic/Suite"),None))
        factory.assert_not_called()

    def test_unreviewed_architecture_rejected_before_external_paths_or_factory(self):
        with patch("native_menu_source_admission.admit_source_menu_runtime",side_effect=AssertionError("unexpected admission")) as factory:
            for architecture in (True,"x86","ARM64",""):
                with self.subTest(architecture=architecture),self.assertRaises(ValueError):
                    calc._admit_source_reader(Path("/synthetic/Suite"),architecture)
        factory.assert_not_called()

    def test_missing_full_uses_exact_external_inputs_and_one_prelaunch_budget(self):
        with patch("native_menu_source_admission.admit_source_menu_runtime",side_effect=ValueError("Full evidence absent")) as factory,patch.object(calc.time,"monotonic",return_value=10.):
            with self.assertRaisesRegex(ValueError,"Full evidence absent"):
                calc._admit_source_reader(Path("/synthetic/Suite"),"arm64")
        self.assertEqual(factory.call_count,1)
        args,kwargs=factory.call_args
        self.assertEqual(args,(Path("/synthetic/Suite"),))
        self.assertEqual(kwargs["architecture"],"arm64");self.assertEqual(kwargs["deadline"],160.)
        self.assertEqual(kwargs["engine_zip"].name,"OpenGeul-Office-engine-arm64.zip")
        self.assertEqual(kwargs["receipt"].name,"source-build-receipt.json")

    def test_reopen_and_reader_flag_rejected_before_admission_or_engine(self):
        suite,fixtures,output=self.paths()
        with patch("native_menu_source_admission.admit_source_menu_runtime",side_effect=AssertionError("unexpected admission")) as factory,patch.object(calc,"verify_reopen",side_effect=AssertionError("unexpected reopen")) as reopen,patch.object(calc,"physical_case",side_effect=AssertionError("unexpected UI")) as physical,patch.object(calc.native,"prepare_ascii_cohort",side_effect=AssertionError("unexpected observer")) as prepare:
            with self.assertRaises(ValueError):
                self.run_main(self.command(suite,fixtures,output,"--verify-reopen","--source-qualified-reader","x64"))
        for call in (factory,reopen,physical,prepare):call.assert_not_called()
        self.assertFalse(output.exists())

    def test_source_full_missing_prevents_observer_output_and_ui_launch(self):
        suite,fixtures,output=self.paths()
        with patch("native_menu_source_admission.admit_source_menu_runtime",side_effect=ValueError("Full evidence absent")) as factory,patch.object(calc.native,"prepare_ascii_cohort",side_effect=AssertionError("unexpected observer")) as prepare,patch.object(calc,"physical_case",side_effect=AssertionError("unexpected UI")) as physical:
            with self.assertRaisesRegex(ValueError,"Full evidence absent"):
                self.run_main(self.command(suite,fixtures,output,"--source-qualified-reader","x64"))
        self.assertEqual(factory.call_count,1);prepare.assert_not_called();physical.assert_not_called();self.assertFalse(output.exists())

    def test_default_cli_preserves_exact_original_physical_kwargs(self):
        suite,fixtures,output=self.paths();library=object()
        with patch("native_menu_source_admission.admit_source_menu_runtime",side_effect=AssertionError("unexpected admission")) as factory,patch.object(calc.native,"prepare_ascii_cohort",return_value=library),patch.object(calc,"physical_case",return_value=dict(success=True)) as physical:
            self.assertEqual(self.run_main(self.command(suite,fixtures,output)),0)
        factory.assert_not_called();self.assertEqual(physical.call_args.args,(suite,fixtures,output))
        self.assertEqual(physical.call_args.kwargs,{"prepared_library":library})

    def test_opaque_forwarding_is_only_a_packet_not_an_admission_claim(self):
        # This unsealed sentinel never reaches Windows or a real reader. The
        # actual reader rejects it; the test covers only opaque call forwarding.
        suite,fixtures,output=self.paths();sentinel=object();library=object()
        with patch.object(calc,"_admit_source_reader",return_value=sentinel) as forward,patch.object(calc.native,"prepare_ascii_cohort",return_value=library),patch.object(calc,"physical_case",return_value=dict(success=True)) as physical:
            self.assertEqual(self.run_main(self.command(suite,fixtures,output,"--source-qualified-reader","arm64")),0)
        self.assertEqual(forward.call_args.args,(suite,"arm64"))
        self.assertIs(physical.call_args.kwargs["source_admission"],sentinel)
        self.assertIs(physical.call_args.kwargs["prepared_library"],library)
        json.dumps(json.loads((output/"results.json").read_text()))

    def test_independent_reopen_command_has_no_source_authority_or_new_flag(self):
        function=ast.parse(inspect.getsource(calc.physical_case)).body[0]
        commands=[node.value for node in ast.walk(function) if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=="command" for target in node.targets)]
        self.assertEqual(len(commands),1)
        literals=[node.value for node in ast.walk(commands[0]) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
        self.assertIn("--verify-reopen",literals);self.assertNotIn("--source-qualified-reader",literals)
        self.assertNotIn("source_admission",{node.id for node in ast.walk(commands[0]) if isinstance(node,ast.Name)})
        parameters=inspect.signature(calc.physical_case).parameters
        self.assertIsNone(parameters["source_admission"].default)

if __name__=="__main__":unittest.main()
