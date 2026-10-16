"""Evidence-policy tests for the Windows lifecycle acceptance harness."""
import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'lifecycle_smoke.py'
SPEC = importlib.util.spec_from_file_location('suite_lifecycle_smoke', SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class LifecycleSmokeTests(unittest.TestCase):
    def test_policy_api_is_present(self):
        for name in ('CASE_REQUIREMENTS', 'lifecycle_report', 'writer_evidence',
                     'owned_target', 'require_dialog_action', 'require_child_bounds',
                     'generate_hwpx', 'copy_writer_fixture'):
            self.assertTrue(hasattr(smoke, name), 'Missing lifecycle evidence policy: ' + name)

    def test_report_requires_every_case_and_concrete_native_evidence(self):
        if not hasattr(smoke, 'CASE_REQUIREMENTS'): self.skipTest('RED: policy API not implemented')
        records = [{'case': name, 'success': True, **{key: True for key in flags}}
                   for name, flags in smoke.CASE_REQUIREMENTS.items()]
        self.assertTrue(smoke.lifecycle_report(records)['success'])
        self.assertEqual(len(records), 7)
        for index, record in enumerate(records):
            for flag in smoke.CASE_REQUIREMENTS[record['case']]:
                invalid = [item.copy() for item in records]
                invalid[index][flag] = False
                self.assertFalse(smoke.lifecycle_report(invalid)['success'], flag)
        for invalid in (records[:-1], records + records[:1], records + [{'case': 'unexpected', 'success': True}]):
            self.assertFalse(smoke.lifecycle_report(invalid)['success'])

    def test_copy_uses_passing_generated_provenance_without_mutating_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures, owned = root / 'fixtures', root / 'owned'
            fixtures.mkdir()
            owned.mkdir()
            source = fixtures / 'OpenGeul-writer.docx'
            with zipfile.ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Engine-OpenGeul-writer UI-OpenGeul-writer</w:t></w:r></w:p></w:body></w:document>')
            record = {'schemaVersion': 1, 'kind': 'engine', 'passed': True,
                      'cases': [{'module': 'writer', 'status': 'passed', 'fixture': str(source.resolve())}]}
            baseline = root / 'engine-smoke.json'
            baseline.write_text(json.dumps(record), encoding='utf-8')
            before = source.read_bytes()
            copied = smoke.copy_writer_fixture(fixtures, owned, '복사 문서 & 한글.docx')
            self.assertEqual(copied.read_bytes(), before)
            self.assertEqual(source.read_bytes(), before)
            record['passed'] = False
            baseline.write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaises(AssertionError): smoke.copy_writer_fixture(fixtures, owned, 'invalid.docx')

    def test_uno_evidence_requires_exact_body_source_sha_and_unchanged_file(self):
        self.assertTrue(hasattr(smoke, 'require_uno_observation'), 'Missing independent UNO evidence policy')
        expected = {'sha256': 'abc123', 'bodyText': 'Owned\n한글 & body'}
        result = smoke.require_uno_observation(expected, 'Owned\r\n한글 & body', 'abc123', 'abc123')
        self.assertEqual(result['bodyText'], expected['bodyText'])
        for actual, before, after in (('Wrong body', 'abc123', 'abc123'),
                                     (expected['bodyText'], 'changed', 'changed'),
                                     (expected['bodyText'], 'abc123', 'changed')):
            with self.assertRaises(AssertionError): smoke.require_uno_observation(expected, actual, before, after)

    def test_independent_uno_reopen_retains_each_case_and_observed_text_after_one_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            fixtures = output / 'fixtures'
            fixtures.mkdir()
            records = []
            for name in ('dirty-writer-cancel-save', 'dirty-writer-discard'):
                target = fixtures / (name + '.docx')
                with zipfile.ZipFile(target, 'w') as package:
                    package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Owned body</w:t></w:r></w:p></w:body></w:document>')
                records.append({'case': name, 'success': True,
                                'savedDocuments': [{'path': str(target), **smoke.writer_evidence(target)}]})
            (output / 'results.json').write_text(json.dumps({'tests': records}), encoding='utf-8')
            class Engine:
                cleanup_errors = []
                def __init__(self, suite): pass
                def start(self): pass
                def cleanup(self): pass
                def close_document(self, document): pass
                def load(self, url):
                    text = 'Wrong observed body' if 'cancel-save' in url else 'Owned body'
                    return SimpleNamespace(supportsService=lambda name: True,
                                           getText=lambda: SimpleNamespace(getString=lambda: text))
            with patch.object(smoke, '_sibling', return_value=SimpleNamespace(Engine=Engine)):
                self.assertEqual(smoke.verify_saved_with_uno(output, output), 1)
            result = json.loads((output / 'packaged-uno-result.json').read_text(encoding='utf-8'))
            self.assertEqual(len(result['cases']), 2, 'One failed document must not hide another case\'s independent result')
            self.assertFalse(result['success'])
            self.assertFalse(result['cases'][0]['success'])
            self.assertTrue(result['cases'][1]['success'])
            self.assertEqual(result['cases'][0]['documents'][0]['observedBodyText'], 'Wrong observed body')

    def test_writer_evidence_reads_only_body_text_and_exact_marker_counts(self):
        if not hasattr(smoke, 'writer_evidence'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'owned.docx'
            with zipfile.ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>BASE-</w:t></w:r><w:r><w:t>MARKER</w:t></w:r></w:p></w:body></w:document>')
                package.writestr('word/comments.xml', '<comment>FORBIDDEN</comment>')
            evidence = smoke.writer_evidence(source, ('BASE-MARKER',), ('FORBIDDEN',))
            self.assertEqual(evidence['bodyText'], 'BASE-MARKER')
            self.assertEqual(len(evidence['sha256']), 64)
            with self.assertRaises(AssertionError): smoke.writer_evidence(source, ('MISSING',))
            with self.assertRaises(AssertionError): smoke.writer_evidence(source, (), ('MARKER',))

    def test_writer_evidence_keeps_actual_soft_breaks_and_tabs_for_exact_uno_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'owned.docx'
            with zipfile.ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Engine-OpenGeul-writer 한글</w:t><w:br/><w:t>-LIFECYCLE-</w:t><w:tab/><w:t>끝</w:t></w:r></w:p><w:p><w:r><w:t>다음 문단</w:t><w:cr/></w:r></w:p></w:body></w:document>')
            evidence = smoke.writer_evidence(source, ('-LIFECYCLE-',))
            expected = 'Engine-OpenGeul-writer 한글\n-LIFECYCLE-\t끝\n다음 문단\n'
            self.assertEqual(evidence['bodyText'], expected)
            self.assertEqual(evidence['bodyParagraphs'], ['Engine-OpenGeul-writer 한글\n-LIFECYCLE-\t끝', '다음 문단\n'])
            smoke.require_uno_observation(evidence, expected, evidence['sha256'], evidence['sha256'])

    def test_owned_menu_search_uses_supported_window_roots_and_deduplicates_runtime_identity(self):
        self.assertTrue(hasattr(smoke, 'owned_menu_items'), 'Owned menu enumeration is missing')
        def item(name, pid, identity, visible=True, enabled=True):
            return SimpleNamespace(element_info=SimpleNamespace(name=name, process_id=pid, runtime_id=identity),
                                   is_visible=lambda: visible, is_enabled=lambda: enabled)
        expected = item('새 문서', 31, [42, 1])
        children = [expected, item('새 문서', 99, [42, 2]), item('다른 이름으로 저장...', 31, [42, 3]),
                    item('새 문서', 31, [42, 4], visible=False)]
        root = SimpleNamespace(element_info=SimpleNamespace(process_id=31), descendants=lambda **kw: children)
        class Desktop:
            def windows(self, **options):
                self.options = options
                return [root, root]
        desktop = Desktop()
        self.assertEqual(smoke.owned_menu_items(desktop, 31, '새 문서'), [expected])
        self.assertEqual(desktop.options, {'process': 31})

    def test_overwrite_yes_button_uses_exact_observed_label_and_owned_process(self):
        self.assertTrue(hasattr(smoke, 'owned_dialog_button'), 'Owned exact-label dialog selection is missing')
        def button(name, pid, automation_id, visible=True, enabled=True):
            return SimpleNamespace(element_info=SimpleNamespace(name=name, process_id=pid, automation_id=automation_id),
                                   is_visible=lambda: visible, is_enabled=lambda: enabled)
        expected = button('Yes', 31, 'CommandButton_6')
        controls = [button('No', 31, '7'), button('Yes', 99, '6'), expected,
                    button('Yes', 31, '6', visible=False)]
        accessible = SimpleNamespace(descendants=lambda **kw: controls)
        self.assertIs(smoke.owned_dialog_button(accessible, 31, ('Yes', '예', '예(&Y)')), expected)
        for controls in ([button('No', 31, '6')], [expected, expected], [button('Yes', 99, '6')]):
            accessible = SimpleNamespace(descendants=lambda **kw: controls)
            with self.assertRaises(AssertionError): smoke.owned_dialog_button(accessible, 31, ('Yes', '예', '예(&Y)'))

    def test_real_save_error_action_targets_exact_owned_ok_without_assuming_automation_id(self):
        class ReachedOwnedOk(Exception): pass
        def click_ok(): raise ReachedOwnedOk('owned OK selected')
        okay = SimpleNamespace(element_info=SimpleNamespace(name='OK', process_id=31, automation_id='CommandButton_1'),
                               is_visible=lambda: True, is_enabled=lambda: True, click_input=click_ok)
        prompt = SimpleNamespace(element_info=SimpleNamespace(name='문서를 저장하지 못했습니다. 문서 창을 유지합니다.'))
        accessible = SimpleNamespace(descendants=lambda **kw: [okay] if kw else [prompt, okay], set_focus=lambda: None)
        desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wrapper_object=lambda: accessible))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'original.docx'
            source.write_bytes(b'owned original')
            case = SimpleNamespace(source=source, folder=folder, record={}, process=SimpleNamespace(pid=31),
                                   attach=lambda: (100, 200, 300), edit=lambda *args: None,
                                   shell_command=lambda *args: None, picker=lambda *args: 500,
                                   screenshot=lambda *args: None)
            case.api = SimpleNamespace(windows=lambda pid: [600], pid=lambda hwnd: 31,
                                       title=lambda hwnd: 'OpenGeul Office', class_name=lambda hwnd: '#32770',
                                       require_foreground=lambda hwnd: None,
                                       user=SimpleNamespace(GetWindow=lambda hwnd, relation: 100))
            with patch.dict('sys.modules', {'pywinauto': SimpleNamespace(Desktop=lambda **kw: desktop)}), \
                 patch.object(smoke, 'ExclusiveRead', return_value=SimpleNamespace(close=lambda: None)):
                with self.assertRaisesRegex(ReachedOwnedOk, 'owned OK selected'):
                    smoke.failed_saveas(case)

    def test_read_only_hwp_label_census_keeps_names_without_instantiating_control_wrappers(self):
        self.assertTrue(hasattr(smoke, 'accessibility_names'), 'Raw accessibility label census is missing')
        children = [SimpleNamespace(name='경로 확인 & 한글 문서.hwpx', control_type=None),
                    SimpleNamespace(name='OpenGeul', control_type='Text')]
        info = SimpleNamespace(name='Owned HWP root', descendants=lambda: children)
        def wrapped_descendants(): raise KeyError(None)
        root = SimpleNamespace(element_info=info, descendants=wrapped_descendants)
        self.assertEqual(smoke.accessibility_names(root), ['Owned HWP root', '경로 확인 & 한글 문서.hwpx', 'OpenGeul'])

    def test_hwp_child_census_uses_native_parent_and_exact_image_without_starting_wmi(self):
        self.assertIn('shell_creation', inspect.signature(smoke._hwp_child_process).parameters,
                      'Snapshot PID reuse is not rejected against retained shell creation')
        class Function:
            def __init__(self, operation): self.operation = operation
            def __call__(self, *args): return self.operation(*args)
        class Kernel:
            def __init__(self, rows, creation_overrides=None):
                self.rows, self.position, self.error = rows, -1, 0
                self.creation_overrides = creation_overrides or {}
                self.opened, self.closed = [], []
                self.CreateToolhelp32Snapshot = Function(lambda flags, pid: 777)
                self.Process32FirstW = Function(lambda handle, entry: self.entry(entry, 0))
                self.Process32NextW = Function(lambda handle, entry: self.entry(entry, self.position + 1))
                self.OpenProcess = Function(self.open)
                self.QueryFullProcessImageNameW = Function(self.image)
                self.GetProcessTimes = Function(self.times)
                self.GetSystemTimeAsFileTime = Function(self.clock)
                self.WaitForSingleObject = Function(lambda handle, timeout: 258)
                self.CloseHandle = Function(lambda handle: self.closed.append(handle) or 1)
            def entry(self, pointer, position):
                self.position = position
                if position >= len(self.rows):
                    self.error = 18
                    return 0
                pid, parent, name, _ = self.rows[position]
                pointer._obj.th32ProcessID, pointer._obj.th32ParentProcessID = pid, parent
                pointer._obj.szExeFile = name
                return 1
            def open(self, access, inherit, pid):
                self.opened.append(pid)
                return 1000 + pid
            def image(self, handle, flags, buffer, length):
                buffer.value = next(row[3] for row in self.rows if row[0] == handle - 1000)
                length._obj.value = len(buffer.value)
                return 1
            def times(self, handle, creation, exit_time, kernel_time, user_time):
                created = self.creation_overrides.get(handle - 1000, (1 << 32) + handle - 1000)
                creation._obj.dwLowDateTime, creation._obj.dwHighDateTime = created & 0xffffffff, created >> 32
                return 1
            def clock(self, pointer):
                pointer._obj.dwLowDateTime, pointer._obj.dwHighDateTime = 1000, 1
        executable = Path('/owned/OpenGeul.exe')
        rows = [(106, 99, 'OpenGeul.exe', str(executable)),
                (107, 31, 'OpenGeul.exe', '/foreign/OpenGeul.exe'),
                (108, 31, 'OpenGeul.exe', str(executable)),
                (109, 31, 'Foreign.exe', '/foreign/Foreign.exe')]
        for additional, expected in (([], 108), ([(110, 31, 'OpenGeul.exe', str(executable))], None)):
            kernel = Kernel(rows + additional)
            with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
                 patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True), \
                 patch.object(smoke.subprocess, 'run', side_effect=AssertionError('WMI subprocess must not run')):
                if additional:
                    with self.assertRaises(AssertionError): smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
                else:
                    observed = smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
                    self.assertEqual(observed, {'pid': expected, 'parentPid': 31, 'creationFileTime': (1 << 32) + expected,
                                                'executable': str(executable)})
            self.assertEqual(kernel.opened[:2], [107, 108])
            self.assertIn(777, kernel.closed)
            self.assertIn(1107, kernel.closed)
            self.assertIn(1108, kernel.closed)
            self.assertIs(kernel.CreateToolhelp32Snapshot.restype, smoke.wintypes.HANDLE)
            self.assertEqual(kernel.Process32FirstW.argtypes, (smoke.wintypes.HANDLE, smoke.ctypes.POINTER(smoke.ProcessEntry32W)))
        self.assertEqual(smoke.ProcessEntry32W.th32DefaultHeapID.offset, 16)
        self.assertEqual(smoke.ProcessEntry32W.th32ParentProcessID.offset, 32)
        self.assertEqual(smoke.ProcessEntry32W.szExeFile.offset, 44)
        kernel = Kernel([rows[0]])
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True):
            self.assertIsNone(smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31))
        self.assertEqual(kernel.closed, [777])
        self.assertFalse(kernel.opened)
        kernel = Kernel(rows)
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True):
            for invalid in (-1, 0, 1 << 32, True):
                with self.assertRaises(AssertionError): smoke._hwp_child_process(invalid, executable, shell_creation=(1 << 32) + 31)
        kernel = Kernel(rows)
        kernel.OpenProcess = Function(lambda *args: 0)
        kernel.error = 5
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True), \
             patch.object(smoke.ctypes, 'WinError', side_effect=lambda error: OSError(error, 'native failure'), create=True):
            with self.assertRaises(OSError): smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
        self.assertEqual(kernel.closed, [777], 'Snapshot must close after a candidate handle failure')
        kernel = Kernel(rows)
        kernel.CreateToolhelp32Snapshot = Function(lambda *args: smoke.ctypes.c_void_p(-1).value)
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(smoke.ctypes, 'get_last_error', return_value=5, create=True), \
             patch.object(smoke.ctypes, 'WinError', side_effect=lambda error: OSError(error, 'native failure'), create=True):
            with self.assertRaises(OSError): smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
        self.assertFalse(kernel.closed, 'An invalid snapshot is never passed to CloseHandle')
        for created in ((1 << 32) + 1, (1 << 32) + 2000):
            kernel = Kernel([rows[2]], {108: created})
            with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
                 patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True):
                self.assertIsNone(smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31),
                                  'Stale PPID or post-snapshot recycled same-image process must never match')
            self.assertEqual(kernel.closed, [1108, 777])
        for failed in ('Process32FirstW', 'Process32NextW', 'QueryFullProcessImageNameW', 'GetProcessTimes'):
            kernel = Kernel(rows)
            setattr(kernel, failed, Function(lambda *args: 0))
            kernel.error = 5
            with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True), \
                 patch.object(smoke.ctypes, 'get_last_error', side_effect=lambda: kernel.error, create=True), \
                 patch.object(smoke.ctypes, 'WinError', side_effect=lambda error: OSError(error, 'native failure'), create=True):
                with self.assertRaises(OSError): smoke._hwp_child_process(31, executable, shell_creation=(1 << 32) + 31)
            self.assertIn(777, kernel.closed, failed)
            if failed in ('QueryFullProcessImageNameW', 'GetProcessTimes'): self.assertIn(1107, kernel.closed, failed)

    def test_retained_hwp_handle_rejects_pid_reuse_with_changed_creation_time(self):
        self.assertIn('expected_creation', inspect.signature(smoke.BoundHwpProcess).parameters,
                      'Retained handle does not verify the native snapshot creation witness')
        class Function:
            def __init__(self, operation): self.operation = operation
            def __call__(self, *args): return self.operation(*args)
        closed = []
        def times(handle, creation, *args):
            creation._obj.dwLowDateTime, creation._obj.dwHighDateTime = 108, 1
            return 1
        def image(handle, flags, buffer, length):
            buffer.value = '/owned/OpenGeul.exe'
            length._obj.value = len(buffer.value)
            return 1
        kernel = SimpleNamespace(**{name: Function(lambda *args: 1) for name in (
            'CreateToolhelp32Snapshot', 'Process32FirstW', 'Process32NextW', 'WaitForSingleObject', 'GetSystemTimeAsFileTime')},
            OpenProcess=Function(lambda *args: 1108), GetProcessTimes=Function(times),
            QueryFullProcessImageNameW=Function(image), CloseHandle=Function(lambda handle: closed.append(handle) or 1))
        with patch.object(smoke.ctypes, 'WinDLL', return_value=kernel, create=True):
            with self.assertRaisesRegex(AssertionError, 'creation'):
                smoke.BoundHwpProcess(108, Path('/owned/OpenGeul.exe'), expected_creation=(1 << 32) + 107)
        self.assertEqual(closed, [1108])

    def test_targets_are_fresh_direct_children_and_never_links(self):
        if not hasattr(smoke, 'owned_target'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = smoke.owned_target(root, '한글 저장 & 결과.docx')
            self.assertEqual(target.parent, root.resolve())
            target.write_bytes(b'owned')
            for name in ('한글 저장 & 결과.docx', '../escape.docx', '/absolute.docx'):
                with self.assertRaises(AssertionError): smoke.owned_target(root, name)
            link = root / 'link.docx'
            try: link.symlink_to(target)
            except OSError: return
            with self.assertRaises(AssertionError): smoke.owned_target(root, link.name)

    def test_dialog_action_checks_all_identity_and_exact_expected_button(self):
        if not hasattr(smoke, 'require_dialog_action'): self.skipTest('RED: policy API not implemented')
        identity = dict(pid=31, shell_pid=31, owner=44, document=44,
                        title='OpenGeul Writer', expected_title='OpenGeul Writer',
                        class_name='#32770', text=['변경 내용을 저장하시겠습니까?'],
                        expected_text='변경 내용을 저장하시겠습니까?', button='취소', allowed=('저장', '저장하지 않음', '취소'))
        smoke.require_dialog_action(**identity)
        for key, value in (('pid', 99), ('owner', 55), ('title', 'Foreign'),
                           ('class_name', 'Foreign'), ('text', ['foreign']), ('button', '확인')):
            with self.assertRaises(AssertionError): smoke.require_dialog_action(**{**identity, key: value})

    def test_bounds_require_child_to_fill_host_client_after_screen_mapping(self):
        if not hasattr(smoke, 'require_child_bounds'): self.skipTest('RED: policy API not implemented')
        self.assertEqual(smoke.require_child_bounds((0, 0, 900, 600), (0, 0, 900, 600)), [900, 600])
        for actual in ((0, 0, 800, 600), (1, 0, 901, 600), (0, 0, 900, 0)):
            with self.assertRaises(AssertionError): smoke.require_child_bounds((0, 0, 900, 600), actual)

    def test_generated_hwpx_contains_only_owned_text_and_leaves_template_intact(self):
        if not hasattr(smoke, 'generate_hwpx'): self.skipTest('RED: policy API not implemented')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '경로 확인 & 문서.hwpx'
            template = Path(__file__).resolve().parents[2] / 'tests/fixtures/advanced-owned/owned-blank.hwpx'
            original = template.read_bytes()
            smoke.generate_hwpx(target)
            with zipfile.ZipFile(target) as package:
                text = ''.join(ET.fromstring(package.read('Contents/section0.xml')).itertext())
                self.assertIn('Suite-HWPX-route-한글 & 123', text)
                self.assertIsNone(package.testzip())
            self.assertEqual(template.read_bytes(), original)
            with self.assertRaises(AssertionError): smoke.generate_hwpx(target)


if __name__ == '__main__': unittest.main()
