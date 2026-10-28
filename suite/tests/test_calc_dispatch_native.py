"""Compile and run the numeric recorder against a portable fake platform."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from native_executable_cleanup import remove_completed_image


class NativeCompileMixin:
    compiler_flags = []

    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            raise unittest.SkipTest('Portable C++ compiler unavailable')
        suite = Path(__file__).resolve().parents[1]
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.image = cls.root / ('calc-recorder.exe' if os.name == 'nt' else 'calc-recorder')
        built = subprocess.run([
            compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pedantic', *cls.compiler_flags,
            '-I', str(suite / 'engine-build/calc-dispatch-diagnostic'),
            str(suite / 'tests/fixtures' / cls.fixture),
            '-o', str(cls.image),
        ], capture_output=True, text=True, timeout=30)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)

    @classmethod
    def tearDownClass(cls):
        remove_completed_image(cls.root, cls.image, cls.last_result)

    def run_case(self, name):
        result = subprocess.run([str(self.image)], input=name, capture_output=True, text=True, timeout=5)
        type(self).last_result = result
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CalcDispatchNativeTests(NativeCompileMixin, unittest.TestCase):
    fixture = 'calc_dispatch_recorder.cpp'

    def test_nested_parent_and_invocation_order(self):
        self.run_case('nested')

    def test_ownership_generation_and_immutable_identity(self):
        self.run_case('identity')

    def test_absolute_deadline_and_clock_failure(self):
        self.run_case('deadline')

    def test_capacity_and_depth_unwind_without_overwrite(self):
        self.run_case('bounds')

    def test_only_original_save_admits_children(self):
        self.run_case('admission')

    def test_publication_and_partial_state_rejection(self):
        self.run_case('publication')


class CalcDispatchRuntimeTests(NativeCompileMixin, unittest.TestCase):
    fixture = 'calc_dispatch_runtime.cpp'
    compiler_flags = ['-D_WIN32', '-DOPENGEUL_CALC_DISPATCH_DIAGNOSTIC_BUILD=1',
                      '-I', str(Path(__file__).resolve().parent / 'fixtures/calc_dispatch_fake_windows')]

    def test_nested_scopes_retain_independent_handles_and_views(self):
        self.run_case('runtime-nested')

    def test_process_generation_window_owner_and_controller_liveness(self):
        self.run_case('runtime-rejection')

    def test_failed_admission_expiry_and_cleanup_release_resources(self):
        self.run_case('runtime-cleanup')

    def test_missing_or_invalid_environment_opens_no_resources(self):
        self.run_case('runtime-normal')


class CalcDispatchDisabledTests(NativeCompileMixin, unittest.TestCase):
    fixture = 'calc_dispatch_disabled.cpp'

    def test_unconfigured_build_has_empty_noexcept_scope(self):
        self.run_case('')
