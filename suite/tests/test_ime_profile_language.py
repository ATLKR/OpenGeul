"""Real compiled C++ policy, synthetic TSF state only; no Windows input."""
import pathlib
import contextlib
import os
import shutil
import subprocess
import tempfile
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ProfileLanguagePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='opengeul-language-policy-');cls.addClassCleanup(cls.temp.cleanup)
        cls.folder=pathlib.Path(cls.temp.name);cls.last=None
        if os.name=='nt':
            # Reuse the existing native SDK selection, allowlisted environment,
            # phase/deadline handling and PE/tool identity checks. No new SDK.
            import test_native_crt_probe as support
            source=cls.folder/'language-policy.cpp';source.write_bytes((ROOT/'tests/ime_profile_language_cases.cpp').read_bytes())
            (cls.folder/'ime_profile_language.h').write_bytes((ROOT/'e2e/ime_profile_language.h').read_bytes())
            with (cls.folder/'compiler.out').open('w',encoding='utf-8') as output,contextlib.redirect_stdout(output):
                cls.binary,_=support._compile_windows_serializer(cls.folder,source,support._serializer_windows_plan())
            cls.environment=support._serializer_environment()
        else:
            compiler=next((path for name in ('c++','g++','clang++') if (path:=shutil.which(name))),None)
            if compiler is None:raise AssertionError('A C++17 compiler is required; no qualification skip')
            cls.binary=cls.folder/'policy';cls.environment={'PATH':os.defpath}
            with (cls.folder/'compiler.out').open('wb') as output:
                try:r=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-pedantic','-I',str(ROOT/'e2e'),str(ROOT/'tests/ime_profile_language_cases.cpp'),'-o',str(cls.binary)],env=cls.environment,stdin=subprocess.DEVNULL,stdout=output,stderr=output,timeout=30)
                except subprocess.TimeoutExpired:raise AssertionError('Synthetic compiler timeout') from None
            if r.returncode:raise AssertionError('Synthetic compile failed (fixed exit code '+str(r.returncode)+')')
        cls.addClassCleanup(cls.cleanup_image)
    @classmethod
    def cleanup_image(cls):
        if cls.last is not None and cls.binary.exists():
            from native_executable_cleanup import remove_completed_image
            remove_completed_image(cls.folder,cls.binary,cls.last)
    def case(self,number):
        with (self.folder/'execution.out').open('wb') as output:
            try:r=subprocess.run([str(self.binary)],env=self.environment,input=str(number).encode('ascii'),stdout=output,stderr=output,timeout=5)
            except subprocess.TimeoutExpired:raise AssertionError('Synthetic execution timeout') from None
        type(self).last=r
        self.assertEqual(r.returncode,0,'Synthetic native policy case '+str(number))
    def test_hkl_us_with_korean_tsf_needs_language_transition_before_exact_hkl_restore(self):self.case(1)
    def test_already_original_language_preserves_one_hkl_one_profile_no_change(self):self.case(2)
    def test_capture_requires_actual_language_equal_to_original_profile(self):self.case(3)
    def test_interface_failure_does_not_get_or_change_language(self):self.case(4)
    def test_getter_failure_does_not_capture_an_original(self):self.case(5)
    def test_captured_original_cannot_be_replaced(self):self.case(6)
    def test_change_failure_does_not_continue_or_retry(self):self.case(7)
    def test_false_success_language_readback_does_not_continue(self):self.case(8)
    def test_foreign_scope_makes_no_api_calls(self):self.case(9)
    def test_budget_or_generation_boundary_loss_never_captures_state(self):self.case(10)
    def test_post_hkl_language_drift_blocks_profile_activation(self):self.case(11)
    def test_restore_scope_loss_never_changes_language(self):self.case(12)
    def test_invalid_original_language_never_becomes_a_memento(self):self.case(13)
    def test_existing_activate_profile_failure_stays_failure(self):self.case(14)
if __name__=='__main__':unittest.main()
