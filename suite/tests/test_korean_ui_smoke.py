import importlib.util
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
try:
    import korean_ui_smoke as smoke
except ImportError:
    smoke = None


def tab(name, index, *, role=38, parent=None):
    path = [0, 1] if parent is None else parent
    return dict(name=name, index=index, role=role, visible=True,
                indexPath=path+[index], parentIndexPath=path,
                liveParentVerified=True, liveIndexReadbackVerified=True,
                rectangle=[20+index*70, 20, 80+index*70, 40])


def snapshot(controls):
    return dict(kind='owned-native-vcl-accessibility', roleNamespace='com.sun.star.accessibility.AccessibleRole',
                roleConstants={'PAGE_TAB':38, 'PAGE_TAB_LIST':39}, officePid=200, childHwnd=123,
                module='writer', loadedModuleService='com.sun.star.text.TextDocument',
                containerHwnd=123, sameLiveFrameVerified=True, ownedPeerAccessibleParentAbsent=True,
                nativeNotebookbarBinding=dict(ownedPeerWidgetVerified=True,targetWidgetType='TabControlUIObject',
                                             targetWidgetId='ContextContainer',nextFocusMatchesTargetWidget=True,
                                             focusRestored=True,selectionUnchanged=True),
                rootRectangle=[0, 0, 1024, 768], boundsDpiContext='per-monitor-v2', truncated=False,
                witness=dict(retainedProcessHandle=True,imageVerified=True,creationTimeVerified=True,
                             hwndVerifiedBefore=True,hwndVerifiedAfter=True,boundsDpiContextRestored=True),
                tabContainers=[dict(role=39,visible=True,sameLiveParentVerified=True,
                                    distinctLiveObjectsVerified=True,indexReadbackVerified=True,
                                    rectangle=[0,10,1024,150],indexPath=[0,1],tabs=controls)])


class KoreanUiEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(smoke, 'The bounded native Korean UI collector is missing')

    def test_actual_korean_tab_items_in_same_native_tab_control_pass(self):
        evidence = smoke.require_korean_tabs(snapshot([tab('홈', 1), tab('삽입', 2)]), 200, 123)
        self.assertEqual(evidence['koreanTabLabels'], ['삽입', '홈'])
        self.assertTrue(evidence['koreanUiVerified'])
        self.assertTrue(evidence['tabbedUiVerified'])

    def test_english_native_tabs_plus_korean_shell_file_menu_fail(self):
        controls = [tab('Home', 1), tab('Insert', 2), tab('파일', 3, role=35)]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(controls), 200, 123)

    def test_korean_menus_and_document_text_do_not_prove_a_tabbed_ui(self):
        for role in (35, 61, 43, 13, 37):
            with self.subTest(role=role), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(snapshot([tab('홈', 1, role=role),
                                                    tab('삽입', 2, role=role)]), 200, 123)

    def test_config_without_accessible_controls_does_not_prove_language(self):
        data = snapshot([])
        data.update(UILocale='ko', ActiveWriter='notebookbar.ui')
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(data, 200, 123)

    def test_tabs_must_be_visible_and_share_an_owned_tab_container(self):
        bad = [tab('홈', 1), tab('삽입', 2, parent=[0,2])]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(bad), 200, 123)
        bad[1] = tab('삽입', 2)
        bad[1]['visible'] = False
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(bad), 200, 123)

    def test_native_ownership_cannot_be_replaced_by_matching_labels(self):
        for key in ('childHwnd', 'officePid', 'containerHwnd'):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            data[key] += 1
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_mnemonic_markup_is_removed_without_accepting_label_substrings(self):
        self.assertEqual(smoke.normalize_label('삽입(~I)'), '삽입')
        self.assertEqual(smoke.normalize_label('~홈'), '홈')
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot([tab('홈페이지', 1), tab('삽입', 2)]), 200, 123)

    def test_unrendered_contextual_tabs_do_not_replace_or_hide_rendered_required_tabs(self):
        hidden = tab('문맥별 도구', 3)
        hidden['rectangle'] = [0, 0, 0, 0]  # VCL may retain SHOWING on an unused context page.
        evidence = smoke.require_korean_tabs(snapshot([tab('홈', 1), tab('삽입', 2), hidden]), 200, 123)
        self.assertTrue(evidence['koreanUiVerified'])

    def test_duplicate_actual_indices_cannot_claim_distinct_native_tabs(self):
        controls = [tab('홈', 1), tab('삽입', 1)]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(controls), 200, 123)

    def test_live_parent_object_and_index_readback_are_required(self):
        baseline = snapshot([tab('홈', 1), tab('삽입', 2)])
        for key in ('sameLiveParentVerified', 'distinctLiveObjectsVerified', 'indexReadbackVerified'):
            data = deepcopy(baseline)
            data['tabContainers'][0][key] = False
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)
        for key in ('liveParentVerified', 'liveIndexReadbackVerified'):
            data = deepcopy(baseline)
            data['tabContainers'][0]['tabs'][1][key] = False
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_retained_process_image_creation_and_window_witnesses_are_required(self):
        for key in ('retainedProcessHandle', 'imageVerified', 'creationTimeVerified', 'hwndVerifiedBefore', 'hwndVerifiedAfter'):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            data['witness'][key] = False
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_wrong_frame_module_or_role_namespace_cannot_supply_korean_text(self):
        baseline = snapshot([tab('홈', 1), tab('삽입', 2)])
        for change in ({'loadedModuleService': 'com.sun.star.sheet.SpreadsheetDocument'},
                       {'sameLiveFrameVerified': False},
                       {'roleNamespace': 'Microsoft.ActiveAccessibility'},
                       {'roleConstants': {'PAGE_TAB':37, 'PAGE_TAB_LIST':60}}):
            data = deepcopy(baseline)
            data.update(change)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_foreign_widget_focus_or_unrestored_selection_cannot_bind_native_tabs(self):
        for key, value in (('ownedPeerWidgetVerified', False), ('targetWidgetType', 'ButtonUIObject'),
                           ('targetWidgetId', 'foreign frame'), ('nextFocusMatchesTargetWidget', False),
                           ('focusRestored', False), ('selectionUnchanged', False)):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            data['nativeNotebookbarBinding'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)

    def test_required_tab_outside_owned_native_window_cannot_qualify(self):
        controls = [tab('홈', 1), tab('삽입', 2)]
        controls[1]['rectangle'] = [1500, 0, 1600, 20]
        with self.assertRaises(AssertionError):
            smoke.require_korean_tabs(snapshot(controls), 200, 123)

    def test_rendered_bounds_require_verified_scoped_physical_pixel_context(self):
        for missing in ('boundsDpiContext', 'boundsDpiContextRestored'):
            data = snapshot([tab('홈', 1), tab('삽입', 2)])
            if missing == 'boundsDpiContext':
                data.pop(missing)
            else:
                data['witness'][missing] = False
            with self.subTest(missing=missing), self.assertRaises(AssertionError):
                smoke.require_korean_tabs(data, 200, 123)


class PrivateNativeTransportTests(unittest.TestCase):
    def test_exact_owned_gui_pipe_is_accepted_without_publishing_it(self):
        value = 'OpenGeul_' + 'a'*32
        args = ['soffice.bin', '--invisible', '--accept=pipe,name='+value+';urp;StarOffice.ServiceManager']
        self.assertEqual(value, smoke.accessible.private_pipe(args))

    def test_public_socket_malformed_duplicate_or_headless_transport_is_rejected(self):
        valid = '--accept=pipe,name=OpenGeul_'+'a'*32+';urp;StarOffice.ServiceManager'
        for args in (['--invisible', '--accept=socket,host=localhost,port=2002;urp;StarOffice.ServiceManager'],
                     ['--invisible', valid, valid], ['--headless', valid],
                     ['--invisible', valid.replace('a'*32, 'foreign')]):
            with self.subTest(args=args), self.assertRaises(AssertionError):
                smoke.accessible.private_pipe(args)


def numeric_environment():
    return dict(OPENGEUL_SUITE_NUMERIC_NOTICE='1', OPENGEUL_SUITE_NOTICE_SCOPE='4',
        GITHUB_ACTIONS='true', GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_JOB='windows-suite',
        GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/work/opengeul-office-arm64',
        GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341', GITHUB_RUN_ID='123',
        GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a'*40, GITHUB_WORKFLOW_SHA='a'*40, RUNNER_ARCH='ARM64')


class NativeChildFailureTests(unittest.TestCase):
    def request(self):
        return dict(childHwnd=123, officePid=200, creationTime=300, module='writer',
            expectedImage='synthetic/Office/program/soffice.bin', pipe='OpenGeul_'+'a'*32,
            snapshot='synthetic-snapshot.json')

    def payload(self):
        return dict(schemaVersion=1, officePid=200, officeCreationTime=300, childHwnd=123,
            moduleCode=1, ownershipStage=2,
            failure=dict(captured=1, exceptionCode=7, fileCode=19, line=321),
            ownedFrames=[[19, 445], [19, 321]])

    def feature(self, name):
        method = getattr(smoke.accessible, name, None)
        self.assertTrue(callable(method), 'Same-child closed numeric failure forwarding is required: '+name)
        return method

    def capture(self, output, *, join='valid', close_error=None):
        events, calls = [], []
        class Result:
            returncode = 1
            stdout = output
            @property
            def stderr(self):
                raise AssertionError('Raw stderr must not be read')
        def exited(seconds):
            events.append(('exited', seconds))
            if join == 'error': raise OSError('synthetic join unavailable')
            return join == 'exited'
        def close():
            events.append('close')
            if close_error is not None: raise close_error
        retained = NS(creation_time=300, exited=exited, close=close)
        def is_window(hwnd):
            events.append(('window', hwnd));return join != 'window'
        def pid(hwnd):
            events.append(('pid', hwnd));return 201 if join == 'pid' else 200
        api = NS(user=NS(IsWindow=is_window), pid=pid)
        def run(command, **kwargs):
            calls.append((command, kwargs));return Result()
        caught = None
        with patch.object(smoke.accessible, '_owned_process', return_value=(api, retained)), \
             patch.object(smoke.accessible, '_command_line', return_value=['--invisible',
                 '--accept=pipe,name=OpenGeul_'+'a'*32+';urp;StarOffice.ServiceManager']), \
             patch.object(smoke.accessible.subprocess, 'run', side_effect=run):
            try:
                smoke.accessible.capture_bounded(Path('/synthetic'), 123, 200, 300,
                    'writer', Path('/synthetic-evidence.json'))
            except BaseException as exc: caught = exc
        return caught, events, calls

    def test_nonzero_child_keeps_original_assertion_after_one_join_and_one_handle_close(self):
        caught, events, calls = self.capture(json.dumps(self.payload()))
        self.assertIs(type(caught), AssertionError)
        self.assertEqual(str(caught), 'Owned native accessibility collector failed: ')
        self.assertEqual(vars(caught).get('_opengeul_native_accessibility_failure'), self.payload())
        self.assertEqual(events, [('exited', 0), ('window', 123), ('pid', 123), 'close'])
        self.assertEqual(len(calls), 1)
        command, options = calls[0]
        self.assertEqual(command[0], str(Path('/synthetic')/'Office/program/python.exe'))
        self.assertEqual(command[2:], ['--collect-live'])
        self.assertNotIn('capture_output', options)
        self.assertEqual({key: options[key] for key in ('timeout', 'shell', 'stdout', 'stderr', 'text', 'encoding')},
            dict(timeout=45, shell=False, stdout=-1, stderr=-3, text=True, encoding='utf-8'))
        request = json.loads(options['input'])
        self.assertEqual(set(request), {'childHwnd','officePid','creationTime','expectedImage','module','pipe','snapshot'})

    def test_join_mismatch_or_error_discards_child_metadata_without_replacing_original_failure(self):
        for join in ('exited', 'window', 'pid', 'error'):
            with self.subTest(join=join):
                caught, events, calls = self.capture(json.dumps(self.payload()), join=join)
                self.assertIs(type(caught), AssertionError)
                self.assertEqual(str(caught), 'Owned native accessibility collector failed: ')
                self.assertNotIn('_opengeul_native_accessibility_failure', vars(caught))
                self.assertEqual(events.count('close'), 1)
                self.assertEqual(len(calls), 1)

    def test_existing_handle_close_failure_keeps_its_original_priority(self):
        error = OSError('synthetic original handle close failure')
        caught, events, calls = self.capture(json.dumps(self.payload()), close_error=error)
        self.assertIs(caught, error)
        self.assertEqual(events[-1], 'close');self.assertEqual(len(calls), 1)
        self.assertNotIn('_opengeul_native_accessibility_failure', vars(caught))

    def test_decoder_drops_incomplete_noisy_unknown_or_foreign_records(self):
        decode = self.feature('_decode_child_failure')
        valid = self.payload()
        self.assertEqual(decode(json.dumps(valid), self.request()), valid)
        bad = [json.dumps(valid)[:-1], json.dumps(valid)+'\nPRIVATE', '', '[]',
            json.dumps(valid).replace('"schemaVersion": 1', '"schemaVersion": 1, "schemaVersion": 1'),
            ' '*1025, '\ud800',
            json.dumps(valid|{'extra':'PRIVATE'}), json.dumps(valid|{'schemaVersion':True}),
            json.dumps(valid|{'officePid':True}), json.dumps(valid|{'officePid':201}),
            json.dumps(valid|{'officeCreationTime':301}), json.dumps(valid|{'childHwnd':124}),
            json.dumps(valid|{'moduleCode':2}), json.dumps(valid|{'ownershipStage':3}),
            json.dumps(valid|{'ownershipStage':True}), json.dumps(valid|{'ownedFrames':[]}),
            json.dumps(valid|{'ownedFrames':[[19,320]]}), json.dumps(valid|{'ownedFrames':[[19,321]]*9}),
            json.dumps(valid|{'ownedFrames':[[True,321]]}), json.dumps(valid|{'ownedFrames':[[999,321]]}),
            json.dumps(valid|{'ownedFrames':[[19,0]]}), json.dumps(valid|{'ownedFrames':[[19,True]]}),
            json.dumps(valid|{'failure':valid['failure']|{'fileCode':0,'line':0}}),
            json.dumps(valid|{'failure':valid['failure']|{'line':float('nan')}}),
            json.dumps(valid|{'failure':valid['failure']|{'captured':True}}),
            json.dumps(valid|{'failure':valid['failure']|{'message':'PRIVATE'}}),
            json.dumps(valid|{'failure':dict(captured=1,exceptionCode=1,fileCode=1,line=321),
                'ownedFrames':[[1,321]]})]
        for value in bad:
            with self.subTest(index=bad.index(value)):
                self.assertIsNone(decode(value, self.request()))
                caught, _, calls = self.capture(value)
                self.assertIs(type(caught), AssertionError)
                self.assertNotIn('_opengeul_native_accessibility_failure', vars(caught))
                self.assertEqual(len(calls), 1)

    def test_success_keeps_existing_snapshot_join_and_does_not_read_child_output(self):
        events = []
        class Result:
            returncode = 0
            @property
            def stdout(self): raise AssertionError('Successful child output is not diagnostic evidence')
            @property
            def stderr(self): raise AssertionError('Raw stderr must not be read')
        retained = NS(exited=lambda seconds:events.append('join') or False,
            close=lambda:events.append('close'))
        api = NS(user=NS(IsWindow=lambda hwnd:True), pid=lambda hwnd:200)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)/'snapshot.json'
            destination.write_text('{"witness":{"retainedProcessHandle":false}}', encoding='utf-8')
            with patch.object(smoke.accessible, '_owned_process', return_value=(api, retained)), \
                 patch.object(smoke.accessible, '_command_line', return_value=['--invisible',
                     '--accept=pipe,name=OpenGeul_'+'a'*32+';urp;StarOffice.ServiceManager']), \
                 patch.object(smoke.accessible.subprocess, 'run', return_value=Result()):
                value = smoke.accessible.capture_bounded(Path('/synthetic'),123,200,300,'writer',destination)
            self.assertEqual(value, {'witness':{'retainedProcessHandle':True}})
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8')), value)
        self.assertEqual(events, ['join','close'])

    def test_echo_cannot_turn_boolean_request_identity_into_verified_integer_identity(self):
        decode = self.feature('_decode_child_failure')
        for request_key, wire_key in (('officePid','officePid'), ('creationTime','officeCreationTime'),
                                      ('childHwnd','childHwnd')):
            with self.subTest(field=request_key):
                request = self.request();request[request_key] = True
                value = self.payload();value[wire_key] = 1
                self.assertIsNone(decode(json.dumps(value),request))

    def test_invalid_utf8_child_output_drops_metadata_and_preserves_parent_assertion(self):
        # Exercise the actual subprocess decoder; only the synthetic executable
        # is substituted for Office at this external process boundary.
        real_run = smoke.accessible.subprocess.run
        calls, events = [], []
        def run(command, **kwargs):
            calls.append(command)
            return real_run([sys.executable,'-c',
                'import sys;sys.stdout.buffer.write(bytes([255]));sys.stderr.buffer.write(bytes([255]));sys.exit(1)'], **kwargs)
        retained = NS(exited=lambda seconds:False, close=lambda:events.append('close'))
        api = NS(user=NS(IsWindow=lambda hwnd:True), pid=lambda hwnd:200)
        with patch.object(smoke.accessible, '_owned_process', return_value=(api,retained)), \
             patch.object(smoke.accessible, '_command_line', return_value=['--invisible',
                 '--accept=pipe,name=OpenGeul_'+'a'*32+';urp;StarOffice.ServiceManager']), \
             patch.object(smoke.accessible.subprocess,'run',side_effect=run):
            try: smoke.accessible.capture_bounded(Path('/synthetic'),123,200,300,'writer',Path('/unused'))
            except BaseException as exc: caught = exc
        self.assertIs(type(caught), AssertionError)
        self.assertEqual(str(caught), 'Owned native accessibility collector failed: ')
        self.assertNotIn('_opengeul_native_accessibility_failure', vars(caught))
        self.assertEqual(len(calls), 1);self.assertEqual(events, ['close'])

    def test_real_collector_reports_only_completed_ownership_stages_after_unwind(self):
        collect_main = self.feature('_collect_main')
        for stage in (0,1,2):
            with self.subTest(stage=stage):
                events = []
                def fail(*args): raise ValueError('synthetic private text')
                retained = NS(close=lambda:events.append('close'))
                peer = NS(getWindowHandle=lambda *args:123)
                frame = NS(getContainerWindow=lambda:peer)
                controller = NS(getFrame=lambda:frame, getModel=lambda:NS(supportsService=lambda name:True))
                frame.getController = lambda:controller
                frames = NS(getCount=lambda:1, getByIndex=lambda index:frame)
                remote = NS(ServiceManager=NS(createInstanceWithContext=lambda *args:NS(getFrames=lambda:frames)))
                local = NS(ServiceManager=NS(createInstanceWithContext=lambda *args:NS(resolve=lambda value:remote)))
                uno = NS(getComponentContext=fail if stage==1 else lambda:local, getConstantByName=fail)
                def owned(*args):
                    if stage==0: fail()
                    return NS(), retained
                stream = io.StringIO()
                with patch.dict(os.environ,numeric_environment(),clear=True), \
                     patch.dict(sys.modules,uno=uno), \
                     patch.object(smoke.accessible,'_owned_process',side_effect=owned), redirect_stdout(stream):
                    self.assertEqual(collect_main(self.request()), 1)
                decoded = self.feature('_decode_child_failure')(stream.getvalue(),self.request())
                self.assertIsNotNone(decoded)
                self.assertEqual(decoded['ownershipStage'], stage)
                self.assertEqual(events, [] if stage==0 else ['close'])

    def test_child_retained_close_failure_stays_above_inner_failure(self):
        collect_main = self.feature('_collect_main')
        events = []
        def fail(): raise ValueError('synthetic inner failure')
        def close(): events.append('close');raise OSError('synthetic original cleanup failure')
        stream = io.StringIO()
        with patch.dict(os.environ,numeric_environment(),clear=True), \
             patch.dict(sys.modules,uno=NS(getComponentContext=fail)), \
             patch.object(smoke.accessible,'_owned_process',return_value=(NS(),NS(close=close))), redirect_stdout(stream):
            self.assertEqual(collect_main(self.request()), 1)
        decoded = self.feature('_decode_child_failure')(stream.getvalue(),self.request())
        self.assertEqual(decoded['failure']['exceptionCode'], 6)
        self.assertEqual(decoded['ownershipStage'], 1)
        self.assertEqual(events, ['close'])

    def test_child_emits_only_closed_numeric_actual_trace_after_all_existing_cleanup(self):
        collect_main = self.feature('_collect_main')
        events = []
        class NoTextError(ValueError):
            def __str__(self): raise AssertionError('Exception text must not be read')
        scope = dict(error=NoTextError(), events=events)
        exec(compile('def collect(request, diagnostic):\n diagnostic["ownershipStage"]=2\n try:\n  raise error\n finally:\n  events.append("cleanup")\n',
            str(E2E/'native_accessibility.py'), 'exec'), scope)
        class Stream(io.StringIO):
            def write(self, value):
                self_test.assertEqual(events, ['cleanup']);return super().write(value)
        self_test = self;stream = Stream()
        with patch.dict(os.environ, numeric_environment(), clear=True), \
             patch.object(smoke.accessible, 'collect_live', side_effect=scope['collect']), \
             patch.object(smoke.native.numeric_notice, 'emit_case_notice', side_effect=AssertionError('No child GHA notice')), \
             redirect_stdout(stream):
            result = collect_main(self.request())
        self.assertEqual(result, 1)
        self.assertLessEqual(len(stream.getvalue().encode('utf-8')), 1024)
        decoded = self.feature('_decode_child_failure')(stream.getvalue(), self.request())
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded['ownershipStage'], 2)
        self.assertEqual(decoded['failure']['exceptionCode'], 0)  # Unknown exact subclass stays unknown.
        self.assertEqual(decoded['failure']['fileCode'], 19)
        self.assertEqual(decoded['ownedFrames'][-1], [19, 4])
        self.assertNotIn('PRIVATE', stream.getvalue());self.assertNotIn('::notice', stream.getvalue())

    def test_child_optional_output_failure_never_retries_or_replaces_nonzero_result(self):
        collect_main = self.feature('_collect_main')
        class BrokenStream:
            def __init__(self): self.writes = 0
            def write(self, value): self.writes += 1;raise OSError('synthetic partial stdout')
            def flush(self): raise AssertionError('Do not flush a failed write')
        stream = BrokenStream()
        with patch.dict(os.environ, numeric_environment(), clear=True), \
             patch.object(smoke.accessible, 'collect_live', side_effect=ValueError()), redirect_stdout(stream):
            self.assertEqual(collect_main(self.request()), 1)
        self.assertEqual(stream.writes, 1)

    def test_handoff_keeps_controller_audit_and_only_actual_child_frames_in_one_parent_notice(self):
        handoff = self.feature('attach_child_failure')
        import numeric_notice
        caught, _, _ = self.capture(json.dumps(self.payload()))
        record = dict(case='korean-ui-writer', module='writer', stage='capture-native-accessible-objects',
            officePid=200, officeCreationTime=300, childHwnd=123)
        stream = io.StringIO();emitter = numeric_notice.NoticeEmitter(environ=numeric_environment(), stream=stream)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, numeric_environment(), clear=True), \
             patch.object(numeric_notice, '_EMITTER', emitter):
            smoke.native.capture_failure(Path(directory), 'korean-ui-writer', record, caught)
            original_code = deepcopy(record['numericFailure']);original_frames = deepcopy(record['numericFailureFrames'])
            self.assertEqual(stream.getvalue(), '')
            with patch.object(smoke.accessible.subprocess, 'run', side_effect=AssertionError('No second process')), \
                 patch('time.monotonic', side_effect=AssertionError('No new deadline')), \
                 patch('os.stat', side_effect=AssertionError('No new filesystem observation')):
                self.assertTrue(handoff(record, caught))
            self.assertEqual(record['nativeAccessibilityControllerFailure'], original_code)
            self.assertEqual(record['nativeAccessibilityControllerFrames'], original_frames)
            self.assertEqual(record['nativeAccessibilityChildFailure'], self.payload())
            self.assertEqual(record['numericFailureFrames'], [[19,445],[19,321]])
            smoke.native.write_result(Path(directory), 'korean-ui-writer', record)
        notices = stream.getvalue().strip().splitlines()
        self.assertEqual(len(notices), 1)
        payload = notices[0].split('::', 2)[2]
        decoded = numeric_notice.decode_notice(payload, 'a'*40, 123, expected_scope=4)
        self.assertEqual(decoded['schemaVersion'], 2)
        self.assertEqual(decoded['ownedFrames'], [[19,445],[19,321]])
        self.assertEqual((decoded['exceptionCode'],decoded['fileCode'],decoded['line']), (7,19,321))

    def test_exact_loaded_uno_runtime_class_changes_only_unknown_exception_code(self):
        classify = self.feature('_child_failure_code')
        calls = []
        class UnoRuntime(Exception):
            __pyunostruct__ = 'com.sun.star.uno.RuntimeException'
            @property
            def Message(self): raise AssertionError('No exception Message getter')
            @property
            def Context(self): raise AssertionError('No exception Context getter')
            def __str__(self): raise AssertionError('No exception text')
        scope = dict(error=UnoRuntime())
        exec(compile('def fail():\n raise error\n', str(E2E/'native_accessibility.py'), 'exec'), scope)
        def get_class(name): calls.append(name);return UnoRuntime
        try: scope['fail']()
        except UnoRuntime as exc:
            with patch.dict(sys.modules, uno=NS(getClass=get_class)), \
                 patch.object(smoke.accessible.subprocess,'run',side_effect=AssertionError('No process query')), \
                 patch('time.monotonic',side_effect=AssertionError('No clock query')):
                failure = classify(exc)
        self.assertEqual(failure, dict(captured=1,exceptionCode=13,fileCode=19,line=2))
        self.assertEqual(calls, ['com.sun.star.uno.RuntimeException'])

    def test_uno_subclasses_other_classes_and_existing_codes_do_not_trigger_class_lookup(self):
        classify = self.feature('_child_failure_code')
        class UnoRuntime(Exception): __pyunostruct__ = 'com.sun.star.uno.RuntimeException'
        class Child(UnoRuntime): pass
        class Disposed(UnoRuntime): __pyunostruct__ = 'com.sun.star.lang.DisposedException'
        class Marker:
            def __eq__(self, other): raise AssertionError('No dynamic marker comparison')
        class TextMarker(str):
            def __eq__(self, other): raise AssertionError('No string-subclass comparison')
        class DynamicMarker(Exception): __pyunostruct__ = Marker()
        class SubclassMarker(Exception): __pyunostruct__ = TextMarker('com.sun.star.uno.RuntimeException')
        known = UnoRuntime()
        known.raw = dict(error=dict(numericFailure=dict(captured=1,exceptionCode=7,fileCode=19,line=55)))
        def forbidden(*args): self.fail('Unknown/subclass/known code cannot query the UNO class')
        for exc, expected in ((Child(),0),(Disposed(),0),(DynamicMarker(),0),(SubclassMarker(),0),
                              (Exception(),0),(RuntimeError(),9),(known,7)):
            with self.subTest(kind=type(exc).__name__), patch.dict(sys.modules,uno=NS(getClass=forbidden)):
                failure = classify(exc)
                self.assertEqual(failure['exceptionCode'],expected)
                if exc is known: self.assertEqual(failure,known.raw['error']['numericFailure'])

    def test_missing_failed_or_nonidentical_loaded_uno_class_keeps_original_unknown_metadata(self):
        classify = self.feature('_child_failure_code')
        class UnoRuntime(Exception): __pyunostruct__ = 'com.sun.star.uno.RuntimeException'
        class Other(Exception): pass
        def broken(name): raise ImportError('synthetic optional class lookup failure')
        for module in (None, NS(), NS(getClass=broken), NS(getClass=lambda name:Other)):
            with self.subTest(module_kind=type(module).__name__), patch.dict(sys.modules,uno=module):
                self.assertEqual(classify(UnoRuntime()),dict(captured=1,exceptionCode=0,fileCode=0,line=0))

    def test_actual_child_runtime_family_survives_cleanup_and_one_existing_v2_parent_notice(self):
        import numeric_notice
        self.feature('_child_failure_code')
        events = []
        class UnoRuntime(Exception):
            __pyunostruct__ = 'com.sun.star.uno.RuntimeException'
            def __getattr__(self,name): raise AssertionError('No exception property getter')
            def __str__(self): raise AssertionError('No exception text')
        scope = dict(error=UnoRuntime(),events=events)
        exec(compile('def collect(request,diagnostic):\n diagnostic["ownershipStage"]=2\n try:\n  raise error\n finally:\n  events.append("cleanup")\n',
            str(E2E/'native_accessibility.py'),'exec'),scope)
        def get_class(name):
            self.assertEqual(events,['cleanup']);return UnoRuntime
        child_stream = io.StringIO()
        with patch.dict(os.environ,numeric_environment(),clear=True), \
             patch.dict(sys.modules,uno=NS(getClass=get_class)), \
             patch.object(smoke.accessible,'collect_live',side_effect=scope['collect']), redirect_stdout(child_stream):
            self.assertEqual(smoke.accessible._collect_main(self.request()),1)
        child = smoke.accessible._decode_child_failure(child_stream.getvalue(),self.request())
        self.assertEqual(child['failure']['exceptionCode'],13)
        self.assertEqual(child['ownedFrames'][-1],[19,4])
        caught, events, calls = self.capture(child_stream.getvalue())
        self.assertEqual(events[-1],'close');self.assertEqual(len(calls),1)
        record = dict(case='korean-ui-writer',module='writer',stage='capture-native-accessible-objects',
            officePid=200,officeCreationTime=300,childHwnd=123)
        stream = io.StringIO();emitter = numeric_notice.NoticeEmitter(environ=numeric_environment(),stream=stream)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,numeric_environment(),clear=True), \
             patch.object(numeric_notice,'_EMITTER',emitter):
            smoke.native.capture_failure(Path(directory),'korean-ui-writer',record,caught)
            self.assertTrue(smoke.accessible.attach_child_failure(record,caught))
            smoke.native.write_result(Path(directory),'korean-ui-writer',record)
        notices = stream.getvalue().strip().splitlines()
        self.assertEqual(len(notices),1)
        decoded = numeric_notice.decode_notice(notices[0].split('::',2)[2],'a'*40,123,expected_scope=4)
        self.assertEqual((decoded['schemaVersion'],decoded['exceptionCode']),(2,13))
        self.assertEqual(decoded['ownedFrames'],child['ownedFrames'])

    def test_optional_class_lookup_baseexceptions_keep_primary_unknown_frames_and_retained_cleanup(self):
        import numeric_notice
        class UnoRuntime(Exception):
            __pyunostruct__ = 'com.sun.star.uno.RuntimeException'
            def __getattr__(self,name): raise AssertionError('No exception property getter')
            def __str__(self): raise AssertionError('No exception text')
        for secondary in (KeyboardInterrupt(),SystemExit(7)):
            with self.subTest(secondary=type(secondary).__name__):
                primary=UnoRuntime();events=[];captured=[];stream=io.StringIO()
                def context():raise primary
                def lookup(name):
                    self.assertEqual(name,'com.sun.star.uno.RuntimeException')
                    self.assertEqual(events,['retained-close'])
                    raise secondary
                original_capture=numeric_notice.capture_failure_code
                def observe(exc):
                    self.assertIs(exc,primary)
                    value=original_capture(exc)
                    captured.append((dict(value),numeric_notice.capture_failure_frames(exc)))
                    return value
                retained=NS(close=lambda:events.append('retained-close'))
                with patch.dict(os.environ,numeric_environment(),clear=True), \
                     patch.dict(sys.modules,uno=NS(getComponentContext=context,getClass=lookup)), \
                     patch.object(smoke.accessible,'_owned_process',return_value=(NS(),retained)), \
                     patch.object(numeric_notice,'capture_failure_code',side_effect=observe),redirect_stdout(stream):
                    try:result=smoke.accessible._collect_main(self.request())
                    except BaseException as escaped:
                        self.fail('Optional class metadata escaped: '+type(escaped).__name__)
                self.assertEqual(result,1)
                self.assertEqual(events,['retained-close'])
                self.assertEqual(len(captured),1)
                decoded=smoke.accessible._decode_child_failure(stream.getvalue(),self.request())
                self.assertIsNotNone(decoded)
                self.assertEqual(decoded['failure'],captured[0][0])
                self.assertEqual(decoded['failure']['exceptionCode'],0)
                self.assertEqual(decoded['ownedFrames'],captured[0][1])


if __name__ == '__main__':
    unittest.main()
