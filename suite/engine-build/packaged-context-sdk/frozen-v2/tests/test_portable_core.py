from pathlib import Path
import os,subprocess,tempfile,time,unittest
BASE=Path(__file__).resolve().parents[1]
class PortableCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.exe=Path(cls.temp.name)/'core-test';cls.active=[]
        cls.compiled=cls.run_owned(['/usr/bin/g++','-std=c++17','-Wall','-Wextra','-Werror','-pedantic','-I',str(BASE),str(BASE/'tests/core_tests.cpp'),'-o',str(cls.exe)],30)==0
    @classmethod
    def tearDownClass(cls):
        if not any(p.poll() is None for p in cls.active):cls.temp.cleanup()
    @classmethod
    def run_owned(cls,args,seconds):
        p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={'PATH':'/usr/bin:/bin'},close_fds=True);cls.active.append(p);deadline=time.monotonic()+seconds
        while p.poll() is None and time.monotonic()<deadline:time.sleep(.01)
        return p.returncode if p.poll() is not None else 124
    def check(self,case):
        self.assertTrue(self.compiled,'Portable collector is unavailable')
        self.assertEqual(self.run_owned([str(self.exe),str(case)],3),0)
    def test_existing_roots_are_observed_together_and_remain_unqualified(self):self.check(0)
    def test_wrong_package_rejects(self):self.check(1)
    def test_emulated_helper_rejects(self):self.check(2)
    def test_missing_winrt_path_rejects(self):self.check(3)
    def test_missing_existing_directory_preserves_and_closes(self):self.check(4)
    def test_reparse_observation_rejects(self):self.check(5)
    def test_conflated_root_file_ids_reject(self):self.check(6)
    def test_file_id_without_final_path_rejects(self):self.check(7)
    def test_changed_reopened_identity_rejects(self):self.check(8)
    def test_changed_process_generation_rejects(self):self.check(9)
    def test_original_subdeadline_is_not_renewed(self):self.check(10)
    def test_uncertain_handle_close_cannot_succeed(self):self.check(11)
    def test_zero_file_id_rejects(self):self.check(12)
    def test_caller_path_must_match_independent_known_folder_recipe(self):self.check(13)
    def test_parent_alias_path_rejects(self):self.check(14)
    def test_larger_than_ten_second_observer_window_rejects(self):self.check(15)
    def test_actual_qpc_frequency_must_match(self):self.check(16)
    def test_missing_request_digest_rejects(self):self.check(17)
    def test_reserved_dos_component_rejects(self):self.check(18)

    def test_lone_utf16_surrogate_cannot_be_a_native_path_identity(self):self.check(19)

    def test_forged_complete_without_three_directories_cannot_serialize(self):self.check(20)
    def test_zero_origin_clock_is_not_an_observation(self):self.check(21)

    def test_reserved_superscript_dos_alias_rejects(self):self.check(22)
    def test_delete_control_cannot_be_a_path_identity(self):self.check(23)

    def test_initially_expired_request_does_not_initialize_winrt(self):self.check(24)

class WindowsSourceContracts(unittest.TestCase):
    def source(self):
        path=BASE/'context_observer_windows.cpp'
        self.assertTrue(path.is_file(), 'Typed Windows observer source is unavailable')
        return path.read_text()
    def test_only_typed_supported_package_known_folder_and_winrt_apis(self):
        source=self.source()
        for name in ('GetCurrentPackageFullName','GetCurrentPackageFamilyName','TokenUser','SHGetKnownFolderPath','ApplicationData::Current().LocalFolder().Path()', 'FileIdInfo','GetFinalPathNameByHandleW'):
            with self.subTest(api=name):self.assertIn(name,source)
    def test_read_only_existing_open_flags_and_no_mutation_or_launcher(self):
        source=self.source()
        self.assertIn('FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE',source)
        self.assertIn('FILE_READ_ATTRIBUTES',source);self.assertIn('OPEN_EXISTING',source)
        for name in ('CreateDirectoryW(', 'WriteFile(', 'DeleteFileW(', 'TerminateProcess(', 'CreateProcessW(', 'RegSetValue', 'wmain('):
            with self.subTest(api=name):self.assertNotIn(name,source)
    def test_os_port_is_separate_from_unimplemented_owned_launcher(self):
        source=self.source()
        self.assertIn('Result observe_windows(Request const& request) noexcept',source)
        self.assertIn('simulation_only=false',source)
        self.assertIn('winrt::init_apartment',source)

    def test_token_user_buffer_has_native_structure_alignment(self):
        self.assertIn('alignas(TOKEN_USER)',self.source())
    def test_actual_handle_raii_class_is_movable_without_duplicate_close(self):
        source=self.source();begin=source.index('class Handle {');end=source.index('std::wstring final_dos_path',begin)
        fixture='#include "context_observer.hpp"\n#include <cstdint>\nusing HANDLE=void*;\n#define INVALID_HANDLE_VALUE reinterpret_cast<void*>(static_cast<std::intptr_t>(-1))\nint closed=0;bool CloseHandle(HANDLE){++closed;return true;}\nnamespace packaged_context {\n'+source[begin:end]+'}\npackaged_context::Handle make(){packaged_context::Handle h(reinterpret_cast<void*>(1));return h;}\nint main(){{auto h=make();}return closed==1?0:1;}\n'
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);unit=root/'handle.cpp';unit.write_text(fixture);exe=root/'handle'
            code=PortableCoreTests.run_owned(['/usr/bin/g++','-std=c++17','-fno-elide-constructors','-Wall','-Wextra','-Werror','-I',str(BASE),str(unit),'-o',str(exe)],15)
            self.assertEqual(code,0)
            self.assertEqual(PortableCoreTests.run_owned([str(exe)],3),0)

    def test_windows_port_construction_has_no_prevalidation_winrt_initialization(self):
        source=self.source();begin=source.index('explicit WindowsPort(');end=source.index('~WindowsPort()',begin)
        self.assertNotIn('init_apartment',source[begin:end])
    def test_actual_apartment_scope_has_pre_post_budget_and_exact_failure_cleanup(self):
        source=self.source();self.assertIn('class Apartment',source)
        begin=source.index('template<class Check>');end=source.index('class WindowsPort',begin)
        fixture='#include "context_observer.hpp"\n#include <cstdlib>\nint now_value=0,attempts=0,ended=0,mode=0;\nnamespace winrt { enum class apartment_type {multi_threaded}; void init_apartment(apartment_type){++attempts;if(mode==2)now_value=10;if(mode==3)throw packaged_context::Failure{6};}void uninit_apartment(){++ended;if(mode==5)now_value=10;} }\nnamespace packaged_context {\n'+source[begin:end]+'}\nint main(int argc,char**argv){if(argc!=2)return 90;mode=std::atoi(argv[1]);if(mode==1)now_value=10;auto check=[](){if(now_value>=10)throw packaged_context::Failure{10};};bool failed=false;try{packaged_context::Apartment<decltype(check)> apartment(check);if(mode==4)throw packaged_context::Failure{6};apartment.close();}catch(packaged_context::Failure const&){failed=true;}int expected_attempts=mode==1?0:1;int expected_ended=(mode==1||mode==3)?0:1;return attempts==expected_attempts&&ended==expected_ended&&failed==(mode!=0)?0:1;}\n'
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);unit=root/'apartment.cpp';unit.write_text(fixture);exe=root/'apartment'
            self.assertEqual(PortableCoreTests.run_owned(['/usr/bin/g++','-std=c++17','-Wall','-Wextra','-Werror','-I',str(BASE),str(unit),'-o',str(exe)],15),0)
            for case in range(6):
                with self.subTest(case=case):self.assertEqual(PortableCoreTests.run_owned([str(exe),str(case)],3),0)
