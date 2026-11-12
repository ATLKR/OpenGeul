"""Mechanical context propagation; tokens here grant no source admission."""
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

CANDIDATE=Path(__file__).resolve().parents[1]/"e2e"
ROOT=Path(__file__).resolve().parents[2]
for value in (str(ROOT/"suite/e2e"),str(ROOT/"suite/tests"),str(CANDIDATE)):
    if value in sys.path:sys.path.remove(value)
    sys.path.insert(0,value)
# Cache actual candidate dependency modules before historical fixtures insert paths.
for name in ("writer_model_reader","writer_model_barrier","calc_model_barrier","windows_smoke","calc_save_smoke"):
    importlib.import_module(name)
def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,CANDIDATE/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
setup=load("reader_calc_setup_candidate","ime_calc_setup.py")
nav=load("reader_calc_navigation_candidate","ime_calc_navigation.py")
import test_ime_calc_setup as setup_fixtures
import test_ime_calc_navigation as nav_fixtures

class CalcReaderContextTests(unittest.TestCase):
    def setup_fixture(self):
        setup_fixtures.ImeCalcSetupTests.api=setup
        fixture=setup_fixtures.ImeCalcSetupTests("test_reader_is_closed_and_validated_before_context_can_return")
        fixture.setUp();self.addCleanup(fixture.doCleanups);return fixture
    def navigation_fixture(self):
        nav_fixtures.api=nav
        fixture=nav_fixtures.CalcNavigationTests("test_f8_initial_then_source_strict_a1_and_release_finish_before_f2")
        fixture.setUp();self.addCleanup(fixture.doCleanups);return fixture
    def spy(self,module,name,token,digest,seen):
        actual=getattr(module,name)
        def check(*args,**kwargs):
            self.assertIs(kwargs.pop("source_admission",None),token)
            # Model cleanup/observation takes both; higher pending-observation uses
            # inventory_sha256 as its original explicit inventory argument.
            self.assertEqual(kwargs["inventory_sha256"],digest)
            if name!="require_pending_observation":kwargs.pop("inventory_sha256")
            seen.append(name)
            return actual(*args,**kwargs)
        return patch.object(module,name,side_effect=check)

    def test_default_setup_preserves_original_call_and_receipt(self):
        fixture=self.setup_fixture();real=setup.observe_calc_setup
        def same(*args,**kwargs):return real(*args,**kwargs,source_admission=None)
        with patch.object(setup,"observe_calc_setup",side_effect=same):
            result,calls,record=fixture.run_reader()
        options=next(item[2] for item in calls if item[0]=="construct")
        self.assertNotIn("source_admission",options)
        self.assertNotIn("inventory_sha256",options)
        self.assertTrue(result["success"]);json.dumps(record)

    def test_setup_passes_only_external_context_and_exact_inventory_to_reader_and_replay(self):
        fixture=self.setup_fixture();token=object();seen=[];real=setup.observe_calc_setup
        def selected(*args,**kwargs):return real(*args,**kwargs,source_admission=token)
        with patch.object(setup,"observe_calc_setup",side_effect=selected),self.spy(setup,"require_owned_model_observation",token,fixture.frame.inventory_sha256,seen),self.spy(setup,"require_model_reader_cleanup",token,fixture.frame.inventory_sha256,seen):
            result,calls,record=fixture.run_reader()
        options=next(item[2] for item in calls if item[0]=="construct")
        self.assertIs(options["source_admission"],token)
        self.assertEqual(options["inventory_sha256"],fixture.frame.inventory_sha256)
        self.assertEqual(seen,["require_owned_model_observation","require_model_reader_cleanup"])
        self.assertTrue(result["success"]);json.dumps(record)

    def test_default_navigation_preserves_original_kwargs(self):
        fixture=self.navigation_fixture();result=fixture.run_navigation(source_admission=None)
        options=next(item[1] for item in fixture.calls if item[0]=="construct")
        self.assertNotIn("source_admission",options);self.assertNotIn("inventory_sha256",options)
        self.assertTrue(result["success"]);json.dumps(fixture.record)

    def test_navigation_keeps_context_external_through_start_read_cleanup_and_final_replay(self):
        fixture=self.navigation_fixture();token=object();seen=[];digest=fixture.data.frame.inventory_sha256
        with self.spy(nav,"require_pending_observation",token,digest,seen),self.spy(nav,"require_model_reader_cleanup",token,digest,seen):
            result=fixture.run_navigation(source_admission=token)
            nav.require_calc_navigation(result,suite=fixture.data.frame.suite,expected_native=fixture.data.native,
                expected_url=fixture.data.source.as_uri(),setup_deadline=10.,now=2.3,source_admission=token)
        options=next(item[1] for item in fixture.calls if item[0]=="construct")
        self.assertIs(options["source_admission"],token);self.assertEqual(options["inventory_sha256"],digest)
        self.assertGreaterEqual(seen.count("require_pending_observation"),5)
        self.assertEqual(seen.count("require_model_reader_cleanup"),3)
        self.assertTrue(result["success"]);json.dumps(fixture.record)

if __name__=="__main__":unittest.main()
