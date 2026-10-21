"""Evidence policy tests for genuine native Korean composition, independent of Windows."""
import copy
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'korean_ime_smoke.py'
sys.path.insert(0, str(SOURCE.parent))
SPEC = importlib.util.spec_from_file_location('suite_korean_ime_smoke', SOURCE)
ime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ime)
from windows_smoke import ascii_input
from ascii_observer_boundary import AsciiObserverBoundary


class KoreanImePolicyTests(unittest.TestCase):
    def ascii_receipt(self, module='writer'):
        # Independent producer-shaped fixture: exact physical US key events,
        # including the literal colon's explicit Shift+semicolon pair.
        scans = {' ': 0x39, 'i': 0x17, 'm': 0x32, 'e': 0x12, '-': 0x0c,
                 'o': 0x18, 'p': 0x19, 'n': 0x31, 'g': 0x22, 'u': 0x16,
                 'l': 0x26, 'w': 0x11, 'r': 0x13, 't': 0x14, 'c': 0x2e,
                 'a': 0x1e, 's': 0x1f, ':': 0x27}
        prefix = ' ime-opengeul-' + module + ':'
        snapshot = {'foregroundVerified': True, 'editorFocusVerified': True,
                    'focusHwnd': 51, 'editorThreadId': 41, 'targetLayout': 0x04090409,
                    'currentThreadLayout': 0x04090409, 'keysDown': [], 'capsLockOn': False}
        actions = []
        for index, char in enumerate(prefix):
            physical = ([0x2a] if char == ':' else []) + [scans[char]]
            events = ([{'vk': 0, 'scan': scan, 'flags': 8} for scan in physical]
                      + [{'vk': 0, 'scan': scan, 'flags': 10} for scan in reversed(physical)])
            actions.append({'index': index, 'character': char, 'events': events,
                'bufferHex': bytes(ascii_input.input_buffer(events)).hex(),
                'requested': len(events), 'inserted': len(events),
                'before': copy.deepcopy(snapshot), 'after': copy.deepcopy(snapshot)})
        return {'schemaVersion': 1, 'success': True, 'text': prefix,
                'inputMethod': 'SendInput-scancode', 'unicodeInputUsed': False,
                'documentHwnd': 11, 'childHwnd': 22, 'inputSize': 40,
                'pauseSeconds': 0.04, 'actions': actions}

    def test_cpp_discovery_failure_preserves_original_output_and_bounded_failure_receipt(self):
        failures = [subprocess.TimeoutExpired('vswhere.exe', 60, output=b'original stdout\n', stderr=b'original stderr\n'),
                    subprocess.CompletedProcess(['vswhere.exe'], 2, 'original stdout\n', 'original stderr\n')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with patch.object(ime.shutil, 'which', return_value=None), patch.object(ime.subprocess, 'run', **kwargs) as run:
                    with self.assertRaises((subprocess.TimeoutExpired, subprocess.CalledProcessError)):
                        ime.compile_observer(folder, 'Local\\owned-test', self.readiness()['profile'])
                self.assertEqual((folder/'compiler-discovery.log').read_bytes(), b'original stdout\noriginal stderr\n')
                import json
                receipt = json.loads((folder/'compiler-discovery.json').read_text())
                self.assertEqual(receipt['stage'], 'discover-msvc')
                self.assertEqual(receipt['timeoutSeconds'], 60)
                self.assertEqual(receipt['outcome'], 'timeout' if isinstance(failure, Exception) else 'nonzero-exit')
                self.assertEqual(run.call_count, 1, 'Discovery must not silently retry or skip failure')

    def readiness(self):
        return {'suiteOnly': True, 'nativeMachine': 0x8664, 'controllerMachine': 0,
                  'capabilityAfter': 'Installed', 'restartNeeded': False,
                  'userLanguageConfigured': True,
                  'profile': {'inputTip': '0412:{A1A1A1A1-1111-2222-3333-444444444444}{B2B2B2B2-1111-2222-3333-444444444444}',
                              'providerClsid': '{A1A1A1A1-1111-2222-3333-444444444444}',
                              'profileGuid': '{B2B2B2B2-1111-2222-3333-444444444444}',
                              'registered': True, 'component': {'signatureStatus': 'Valid',
                              'sha256': 'a' * 64, 'machine': 0x8664,
                              'signerSubject': 'CN=Microsoft Windows, O=Microsoft Corporation, C=US'}}}

    def restoration(self):
        return {'command': 4, 'status': 0, 'layout': 0x04090409,
                'previousLayout': 0x04090409, 'previousProfileType': 2,
                'previousLanguage': 0x0409, 'previousClsid': '{00000000-0000-0000-0000-000000000000}',
                'previousProfile': '{00000000-0000-0000-0000-000000000000}',
                'previousProfileLayout': 0x04090409, 'activeProfileType': 2,
                'activeLanguage': 0x0409, 'activeClsid': '{00000000-0000-0000-0000-000000000000}',
                'activeProfile': '{00000000-0000-0000-0000-000000000000}',
                'activeProfileLayout': 0x04090409, 'profileManagerHresult': 0,
                'previousProfileHresult': 0, 'activateProfileHresult': 0,
                'activeProfileHresult': 0, 'activateLayoutError': 0}

    def record(self):
        events = []
        for composition, result in [('ㅎ', ''), ('하', ''), ('한', ''), ('ㄱ', '한'),
                                    ('그', ''), ('글', ''), ('그', ''), ('글', ''), ('', '글')]:
            events.append({'message': 0x10f, 'pid': 31, 'tid': 41, 'hwnd': 51,
                           'layout': 0x0412, 'composition': composition, 'result': result})
        return {'module': 'writer', 'windowHwnd': 11, 'childHwnd': 22,
                'officePid': 31, 'editorTid': 41, 'keyboardFocusHwnd': 51,
                'inputMethod': 'SendInput-scancode', 'unicodeInputUsed': False,
                'keyTokens': list('gksrmf') + ['BACKSPACE', 'f', 'RIGHT'],
                'activeLayout': 0x0412, 'events': events,
                'readiness': self.readiness(),
                'activeProfile': {'activeLanguage': 0x0412,
                                  'activeClsid': '{A1A1A1A1-1111-2222-3333-444444444444}',
                                  'activeProfile': '{B2B2B2B2-1111-2222-3333-444444444444}'},
                'savedText': 'Engine-OpenGeul-writer 한글\nime-opengeul-writer:한글',
                'reopened': {'text': 'Engine-OpenGeul-writer 한글\nime-opengeul-writer:한글'},
                'asciiPrefix': ' ime-opengeul-writer:', 'prefixInputLayout': 0x04090409,
                'asciiEditorInputs': [self.ascii_receipt()],
                'layoutRestored': True, 'restoration': self.restoration()}

    def test_real_dubeolsik_commit_backspace_save_and_reopen_satisfy_policy(self):
        result = ime.validate_ime_evidence(self.record())
        self.assertTrue(result['imeVerified'])
        self.assertTrue(result['backspaceCompositionVerified'])

    def test_ascii_scaffold_precedes_korean_activation_on_verified_original_english_layout(self):
        for layout in (0x04090409, 0x04120412):
            calls = []
            record = {key: value for key, value in self.record().items()
                      if key in ('module', 'windowHwnd', 'childHwnd', 'editorTid', 'keyboardFocusHwnd')}
            observer = SimpleNamespace(tid=41,
                api=SimpleNamespace(user=SimpleNamespace(GetKeyboardLayout=lambda tid: layout)),
                require_target=lambda: calls.append('owned-focus'),
                command=lambda value: calls.append(('command', value)) or {'command': value})
            def counted_ascii(text):
                calls.append(('ascii', text))
                record['asciiEditorInputs'] = [self.ascii_receipt()]
            if layout & 0xffff == 0x0409:
                result = ime.activate_after_ascii_prefix(observer, 'writer', record, counted_ascii)
                self.assertEqual(calls, ['owned-focus', ('ascii', ' ime-opengeul-writer:'), ('command', 1)])
                self.assertEqual(result, {'command': 1})
                self.assertEqual(record['prefixInputLayout'], layout)
                self.assertEqual(len(record['asciiEditorInputs']), 1)
            else:
                with self.assertRaises(AssertionError):
                    ime.activate_after_ascii_prefix(observer, 'writer', record, counted_ascii)
                self.assertEqual(calls, ['owned-focus'])

    def test_missing_counted_prefix_cannot_activate_korean_even_when_callback_returns(self):
        calls, record = [], {key: value for key, value in self.record().items()
            if key in ('module', 'windowHwnd', 'childHwnd', 'editorTid', 'keyboardFocusHwnd')}
        observer = SimpleNamespace(tid=41,
            api=SimpleNamespace(user=SimpleNamespace(GetKeyboardLayout=lambda tid: 0x04090409)),
            require_target=lambda: calls.append('owned-focus'),
            command=lambda value: calls.append(('command', value)))
        with self.assertRaises(AssertionError):
            ime.activate_after_ascii_prefix(observer, 'writer', record,
                lambda text: calls.append(('ascii', text)))
        self.assertEqual(calls, ['owned-focus', ('ascii', ' ime-opengeul-writer:')])

    def test_one_mandatory_physical_prefix_receipt_rejects_missing_duplicate_counts_and_buffers(self):
        changes = [lambda r: r.pop('asciiEditorInputs'),
                   lambda r: r.update(asciiEditorInputs=[]),
                   lambda r: r['asciiEditorInputs'].append(copy.deepcopy(r['asciiEditorInputs'][0])),
                   lambda r: r['asciiEditorInputs'][0].update(text=' me-opengeul-writer:'),
                   lambda r: r['asciiEditorInputs'][0].update(pauseSeconds=0.025),
                   lambda r: r['asciiEditorInputs'][0].update(documentHwnd=99),
                   lambda r: r['asciiEditorInputs'][0].update(childHwnd=99),
                   lambda r: r['asciiEditorInputs'][0]['actions'][0].update(inserted=0),
                   lambda r: r['asciiEditorInputs'][0]['actions'][0].update(bufferHex='00'),
                   lambda r: r['asciiEditorInputs'][0]['actions'][-1]['events'].pop(0)]
        for change in changes:
            record = self.record()
            change(record)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_prefix_receipt_must_match_observed_editor_focus_thread_and_neutral_us_state(self):
        changes = [lambda r: r['asciiEditorInputs'][0]['actions'][0]['before'].update(focusHwnd=99),
                   lambda r: r['asciiEditorInputs'][0]['actions'][0]['before'].update(editorFocusVerified=False),
                   lambda r: [a[side].update(editorThreadId=99) for a in r['asciiEditorInputs'][0]['actions'] for side in ('before', 'after')],
                   lambda r: r['asciiEditorInputs'][0]['actions'][0]['before'].update(keysDown=[0x10]),
                   lambda r: r['asciiEditorInputs'][0]['actions'][0]['after'].update(capsLockOn=True),
                   lambda r: r['asciiEditorInputs'][0]['actions'][0]['before'].update(targetLayout=0x04120412),
                   lambda r: r['asciiEditorInputs'][0]['actions'][0]['before'].update(currentThreadLayout=0x04120412)]
        for change in changes:
            record = self.record()
            change(record)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_preexisting_or_malformed_receipt_cannot_authorize_korean_activation(self):
        for preexisting in (True, False):
            record, commands = self.record(), []
            if not preexisting:
                record.pop('asciiEditorInputs')
            observer = SimpleNamespace(tid=41,
                api=SimpleNamespace(user=SimpleNamespace(GetKeyboardLayout=lambda tid: 0x04090409)),
                require_target=lambda: None, command=lambda value: commands.append(value))
            def callback(text):
                record['asciiEditorInputs'] = [self.ascii_receipt()]
                record['asciiEditorInputs'][0]['actions'][0]['inserted'] = 0
            with self.subTest(preexisting=preexisting), self.assertRaises(AssertionError):
                ime.activate_after_ascii_prefix(observer, 'writer', record, callback)
            self.assertEqual(commands, [])

    def test_case_routes_only_original_prefix_once_through_physical_producer_before_activation(self):
        class ProbeDone(Exception):
            pass
        for module, extension in ime.INPUT_CASES:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original = root / ('OpenGeul-' + module + '.' + extension)
                original.write_bytes(b'unchanged original fixture')
                calls, sent = [], []
                user = SimpleNamespace(GetKeyboardLayout=lambda tid: 0x04090409,
                    GetAsyncKeyState=lambda key: 0, GetKeyState=lambda key: 0,
                    GetWindowThreadProcessId=lambda hwnd, pointer: 41,
                    GetForegroundWindow=lambda: 11, GetAncestor=lambda hwnd, kind: 11,
                    SendInput=lambda count, payload, size: sent.append((count, bytes(payload), size)) or count)
                api = SimpleNamespace(user=user, require_foreground=lambda hwnd: None,
                    require_editor_focus=lambda hwnd, child: 51, pid=lambda hwnd: 31)
                window = SimpleNamespace(maximize=lambda: None, set_focus=lambda: None, click_input=lambda: None)
                desktop = SimpleNamespace(window=lambda **kw: SimpleNamespace(wrapper_object=lambda: window))
                process = SimpleNamespace(pid=77);prepared=object();semantic_calls=[]
                binding=dict(shellPid=77,officePid=31,suiteHwnd=11,parentHwnd=12,childHwnd=22,rootHwnd=11,
                    shellCreationTime=2**55,officeCreationTime=2**55+100,expectedImage=str(root/'Office/program/soffice.bin'))
                def command(value, **kw):
                    self.assertEqual(kw['setup_deadline'], saved_record[0]['imeSetupBudget']['deadline'])
                    calls.append(('activation', value))
                    raise ProbeDone()
                observer = SimpleNamespace(api=api, tid=41, activation_attempted=False, restoration_required=False, focus=51,
                    native_architecture={'processMachine': 0, 'nativeMachine': 0x8664,
                        'processArchitecture': 'x64', 'nativeArchitecture': 'x64'},
                    target_architecture={'processMachine': 0, 'nativeMachine': 0x8664,
                        'processArchitecture': 'x64', 'nativeArchitecture': 'x64'},
                    require_target=lambda: None, command=command, events=lambda: [], commands=[], close=lambda: None)
                real_type_ascii = ascii_input.type_ascii
                def physical(*args, **kw):
                    calls.append(('physical', args[3], kw['pause']))
                    self.assertEqual(kw['deadline'],saved_record[0]['imeSetupBudget']['deadline'])
                    self.assertIs(kw['original_popen'],process);self.assertIs(kw['native_binding'],binding)
                    self.assertIs(kw['prepared_library'],prepared)
                    return real_type_ascii(*args, **kw)
                send_keys = unittest.mock.Mock()
                saved_record = []
                class Keyboard:
                    def __init__(inner, api,p,hwnd,parent,child,pid,kind,record,deadline):
                        self.assertIs(p,process);self.assertEqual((hwnd,parent,child,pid,kind),(11,12,22,31,module))
                        inner.api=api;inner.process=p;inner.tid=41;inner.focus=51;inner.binding=binding
                        inner.record=record;saved_record.append(record)
                    def start(inner):calls.append('keyboard-admitted')
                    def focus_editor(inner, deadline):calls.append('counted-ctrl-f6')
                    def editor_ready(inner, receipt):
                        self.assertIs(receipt,inner.record['editorFocusReadiness']);calls.append('readiness-acknowledged')
                    def navigate(inner):calls.append(('counted-navigation',module))
                    def require_target(inner):return None
                    def require_context_target(inner,key):self.assertIn(key,inner.record)
                    def require_prefix_ready(inner):
                        self.assertIn(('ack','pre'),semantic_calls);self.assertNotIn(('ack','post'),semantic_calls)
                    def semantic_ready(inner,context,*,phase):
                        self.assertIs(context,inner.record['imeSemanticContext']);semantic_calls.append(('ack',phase))
                    def setup_complete(inner):
                        self.assertIn(('ack','pre'),semantic_calls);self.assertIn(('ack','post'),semantic_calls)
                        calls.append('us-setup-complete')
                    def close(inner, primary=None):calls.append('keyboard-closed')
                def prepare(api,hwnd,child,shell_pid,pid,record,click,ctrl_f6,**kw):
                    self.assertLessEqual(kw['seconds'],5.)
                    record['editorFocusReadiness']={'deadline':record['imeSetupBudget']['deadline']}
                    click();ctrl_f6();return 51
                def calc_context(suite,source,original_bytes,record,deadline,**kw):
                    self.assertEqual(original_bytes,b'unchanged original fixture')
                    self.assertEqual(kw['expected_native'],binding)
                    self.assertIs(kw['original_shell'],retained_shell)
                    ime.require_ascii_prefix(record)
                    record['calcSetupContext']={'success':True,'naturalCleanupCompleted':True};kw['require_current']()
                    calls.append('calc-context-cleaned-before-observer')
                def semantic_context(suite,source,original_bytes,record,deadline,**kw):
                    phase=kw['phase'];self.assertEqual(deadline,record['imeSetupBudget']['deadline'])
                    self.assertEqual(kw['expected_native'],binding);self.assertIs(kw['original_shell'],retained_shell)
                    if phase=='pre':self.assertFalse(record.get('asciiEditorInputs'))
                    else:ime.require_ascii_prefix(record);self.assertEqual(kw['expected_prefix'],record['asciiPrefix'])
                    context=dict(success=True,phase=phase);record['imeSemanticContext']=context
                    record.setdefault('imeSemanticContexts',[]).append(context);kw['require_current']()
                    semantic_calls.append(('getter-cleaned',phase));return context
                def install(*args,**kw):
                    ime.require_ascii_prefix(saved_record[0])
                    if module=='calc':self.assertTrue(saved_record[0]['calcSetupContext']['naturalCleanupCompleted'])
                    self.assertEqual(kw['setup_deadline'],saved_record[0]['imeSetupBudget']['deadline'])
                    calls.append('observer-installed');return observer
                retained_shell={'trueRetainedPopen':True}
                with ExitStack() as stack:
                    activated=stack.enter_context(patch.object(ime,'activate_owned_suite',side_effect=lambda api,process,hwnd,record:api.require_foreground(hwnd)))
                    context=stack.enter_context(patch.object(ime,'observe_calc_setup',side_effect=calc_context))
                    typed=stack.enter_context(patch.object(ascii_input,'type_ascii',side_effect=physical))
                    written=stack.enter_context(patch.object(ime,'write_result'))
                    for patcher in [
                        patch.dict('sys.modules',{'pywinauto':SimpleNamespace(Desktop=lambda **kw:desktop),
                            'pywinauto.keyboard':SimpleNamespace(send_keys=send_keys)}),
                        patch.object(ime,'require_engine_fixture',return_value=original),
                        patch.object(ime,'launch_suite',return_value=process),patch.object(ime,'Windows',return_value=api),
                        patch.object(ime,'verified_attachment',return_value=(11,12,22,31)),
                        patch.object(ime,'CompositionObserver',side_effect=install),patch.object(ime,'IMEKeyboardSession',Keyboard),
                        patch.object(ime,'observe_ime_semantic_setup',side_effect=semantic_context),
                        patch.object(ime,'retained_setup_shell',return_value=retained_shell),
                        patch('windows_smoke.prepare_editor_focus',side_effect=prepare),
                        patch('windows_smoke.click_owned_editor',side_effect=lambda *args:calls.append('owned-editor-click')),
                        patch.object(ascii_input,'_observer',side_effect=AsciiObserverBoundary),
                        patch.object(ascii_input.time,'sleep'),patch.object(ime,'capture_failure'),patch.object(ime,'stop_owned_test_process')]:
                        stack.enter_context(patcher)
                    with self.assertRaises(ProbeDone):
                        ime.case(root, root, root, self.readiness(), module, extension, prepared_library=prepared)
                expected=['keyboard-admitted','owned-editor-click','counted-ctrl-f6','readiness-acknowledged',
                    ('counted-navigation',module),('physical',' ime-opengeul-'+module+':',.04)]
                if module=='calc':expected.append('calc-context-cleaned-before-observer')
                expected.extend(['observer-installed','us-setup-complete',('activation',1),'keyboard-closed'])
                self.assertEqual(calls,expected)
                self.assertEqual(semantic_calls,[('getter-cleaned','pre'),('ack','pre'),('getter-cleaned','post'),('ack','post')])
                self.assertEqual(context.call_count,int(module=='calc'))
                self.assertEqual(typed.call_count, 1)
                self.assertEqual(activated.call_count, 1)
                self.assertGreater(len(sent), 0)
                self.assertNotIn(' ime-opengeul-' + module + ':', [call.args[0] for call in send_keys.call_args_list])
                record = written.call_args.args[2]
                self.assertEqual(len(record['asciiEditorInputs']), 1)
                ascii_input.require_ascii_receipt(record['asciiEditorInputs'][0], record['asciiPrefix'], 11, 22)

    def test_ime_fresh_import_loads_exact_ascii_helper_without_uno_or_native_calls(self):
        script = '''import ctypes,json,pathlib,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
with patch.object(ctypes,'WinDLL',create=True,side_effect=AssertionError('native call during import')):
    import korean_ime_smoke as ime
    import windows_smoke as native
    assert 'uno' not in sys.modules and 'pyuno' not in sys.modules
    assert ime.ascii_input is native.ascii_input
    print(json.dumps({'ime':ime.__file__,'ascii':ime.ascii_input.__file__}))
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(SOURCE.parent)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(Path(receipt['ime']).resolve(), SOURCE.resolve())
        self.assertEqual(Path(receipt['ascii']).resolve(), SOURCE.with_name('ascii_editor_input.py').resolve())

    def test_missing_or_non_english_ascii_setup_receipt_cannot_pass(self):
        for patch in ({'asciiPrefix': ''}, {'prefixInputLayout': 0x04120412}, {'prefixInputLayout': 0}):
            with self.subTest(patch=patch), self.assertRaises(AssertionError):
                ime.validate_ime_evidence({**self.record(), **patch})

    def test_restore_requires_successful_native_calls_and_exact_original_hkl_and_tsf_identity(self):
        for patch in ({'activateProfileHresult': -2147467259}, {'status': -6},
                      {'layout': 0x04120412}, {'activeLanguage': 0x0412},
                      {'activeClsid': '{A028AE76-01B1-46C2-99C4-ACD9858AE02F}'},
                      {'activeProfileType': 1}, {'activeProfileLayout': 0}):
            record = self.record()
            record['restoration'].update(patch)
            with self.subTest(patch=patch), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_unicode_only_input_cannot_claim_ime(self):
        for patch in ({'inputMethod': 'Unicode-SendInput'}, {'unicodeInputUsed': True},
                      {'keyTokens': ['한글']}, {'events': []}):
            with self.subTest(patch=patch), self.assertRaises(AssertionError):
                ime.validate_ime_evidence({**self.record(), **patch})

    def test_missing_or_different_tsf_profile_is_not_microsoft_ime_evidence(self):
        for patch in ({'activeProfile': {}}, {'readiness': {}},
                      {'activeProfile': {'activeLanguage': 0x0412, 'activeClsid': '{UNVERIFIED}',
                                         'activeProfile': '{B2B2B2B2-1111-2222-3333-444444444444}'}}):
            with self.subTest(patch=patch), self.assertRaises(AssertionError):
                ime.validate_ime_evidence({**self.record(), **patch})

    def test_foreign_process_or_thread_composition_cannot_satisfy_policy(self):
        for key in ('pid', 'tid', 'hwnd', 'layout'):
            record = self.record()
            for event in record['events']: event[key] = 123
            with self.subTest(key=key), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_saved_preexisting_korean_without_distinct_new_marker_is_rejected(self):
        for key in ('savedText', 'reopened'):
            record = self.record()
            record[key] = 'Engine-OpenGeul-writer 한글' if key == 'savedText' else {'text': 'Engine-OpenGeul-writer 한글'}
            with self.subTest(key=key), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_missing_backspace_transition_and_missing_commit_are_rejected(self):
        for index in (6, 8):
            record = self.record()
            del record['events'][index]
            with self.subTest(index=index), self.assertRaises(AssertionError):
                ime.validate_ime_evidence(record)

    def test_calc_reopen_must_preserve_formula_and_original_marker(self):
        record = self.record()
        record.update(module='calc', asciiPrefix=' ime-opengeul-calc:', savedText=record['savedText'].replace('writer', 'calc'))
        record['asciiEditorInputs'] = [self.ascii_receipt('calc')]
        record['reopened'] = {'text': record['savedText'], 'formula': '=SUM(B1:C1)', 'value': 42}
        self.assertTrue(ime.validate_ime_evidence(record)['imeVerified'])
        record['reopened']['value'] = 0
        with self.assertRaises(AssertionError): ime.validate_ime_evidence(record)

    def test_incomplete_or_unsigned_readiness_cannot_enable_real_input(self):
        record = self.readiness()
        self.assertEqual(ime.require_readiness(record), record)
        for patch in ({'capabilityAfter': 'NotPresent'}, {'restartNeeded': True}, {'userLanguageConfigured': False}):
            with self.subTest(patch=patch), self.assertRaises(AssertionError):
                ime.require_readiness({**record, **patch})
        unsigned = copy.deepcopy(record)
        unsigned['profile']['component']['signatureStatus'] = 'NotSigned'
        with self.assertRaises(AssertionError): ime.require_readiness(unsigned)

    def test_physical_sequence_contains_scancodes_and_never_vk_packet(self):
        events = ime.scan_events(list('gksrmf') + ['BACKSPACE', 'f', 'RIGHT'])
        self.assertEqual(len(events), 18)
        self.assertTrue(all(row['vk'] == 0 and row['flags'] & 8 and not row['flags'] & 4 for row in events))
        self.assertEqual([row['scan'] for row in events[::2]], [0x22, 0x25, 0x1f, 0x13, 0x32, 0x21, 0x0e, 0x21, 0x4d])
        with self.assertRaises(ValueError): ime.scan_events(['한글'])



class NativeArmImeTests(unittest.TestCase):
    readiness = KoreanImePolicyTests.readiness
    record = KoreanImePolicyTests.record
    ascii_receipt = KoreanImePolicyTests.ascii_receipt
    restoration = KoreanImePolicyTests.restoration
    # Reuse producer-shaped fixture helpers, without duplicating inherited cases.
    def arm_readiness(self):
        record = self.readiness()
        record.update(nativeMachine=0xaa64, controllerMachine=0, source={'architecture': 'arm64'})
        record['profile']['component']['machine'] = 0xaa64
        return record

    def call_architecture(self, function, *args, architecture='arm64'):
        try:
            return function(*args, architecture=architecture)
        except TypeError as error:
            self.fail('Explicit native observer architecture is required: ' + str(error))

    def test_arm_readiness_requires_matching_native_os_and_component(self):
        record = self.arm_readiness()
        self.assertEqual(self.call_architecture(ime.require_readiness, record), record)
        for machine in (0x8664, 0xa641, 0x14c, 0, True):
            changed = copy.deepcopy(record)
            changed['profile']['component']['machine'] = machine
            with self.subTest(component=machine), self.assertRaises(AssertionError):
                self.call_architecture(ime.require_readiness, changed)
        for field, value in (('nativeMachine', 0x8664), ('nativeMachine', True),
                             ('controllerMachine', 0x8664), ('controllerMachine', 0xaa64)):
            with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                self.call_architecture(ime.require_readiness, {**record, field: value})

    def test_readiness_cannot_transpose_requested_architecture(self):
        for architecture in ('x64', 'x86', 'ARM64', None, [], {}):
            with self.subTest(architecture=architecture), self.assertRaises(AssertionError):
                self.call_architecture(ime.require_readiness, self.arm_readiness(), architecture=architecture)

    def test_arm_composition_preserves_the_existing_message_content_and_cleanup_gates(self):
        record = self.record()
        record.update(architecture='arm64', readiness=self.arm_readiness(),
            nativeArchitecture={'processMachine': 0, 'nativeMachine': 0xaa64,
                'processArchitecture': 'arm64', 'nativeArchitecture': 'arm64'},
            targetArchitecture={'processMachine': 0, 'nativeMachine': 0xaa64,
                'processArchitecture': 'arm64', 'nativeArchitecture': 'arm64'})
        self.assertTrue(ime.validate_ime_evidence(record)['imeVerified'])
        record['events'][0]['pid'] += 1
        with self.assertRaisesRegex(AssertionError, 'another process'):
            ime.validate_ime_evidence(record)

    def test_arm_composition_requires_native_controller_and_target_receipts(self):
        for field in ('nativeArchitecture', 'targetArchitecture'):
            for value in (None, {'processMachine': 0x8664, 'nativeMachine': 0xaa64,
                    'processArchitecture': 'x64', 'nativeArchitecture': 'arm64'}):
                record = self.record()
                proof = {'processMachine': 0, 'nativeMachine': 0xaa64,
                         'processArchitecture': 'arm64', 'nativeArchitecture': 'arm64'}
                record.update(architecture='arm64', readiness=self.arm_readiness(),
                    nativeArchitecture=proof, targetArchitecture=proof)
                record[field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(AssertionError, 'architecture|native|Native'):
                    ime.validate_ime_evidence(record)

    def test_compiler_targets_arm64_and_verifies_emitted_dll_before_returning(self):
        import struct
        for emitted in (0xaa64, 0x8664, 0xa641):
            with self.subTest(emitted=emitted), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                vs = folder/'vs'
                vcvars = vs/'VC/Auxiliary/Build/vcvarsall.bat'
                vcvars.parent.mkdir(parents=True)
                vcvars.write_text('@echo off')
                commands = []
                def compile(command, **kwargs):
                    commands.append(command)
                    data = bytearray(1024)
                    data[:2] = b'MZ'
                    struct.pack_into('<I', data, 60, 128)
                    data[128:132] = b'PE\0\0'
                    struct.pack_into('<HHIIIHH', data, 132, emitted, 1, 0, 0, 0, 240, 0x2002)
                    struct.pack_into('<H', data, 152, 0x20b)
                    (folder/'ime-observer.dll').write_bytes(data)
                    return subprocess.CompletedProcess(command, 0, b'original compiler stdout', b'')
                with patch.object(ime.shutil, 'which', return_value='cl.exe'), \
                        patch.object(ime, 'discover_msvc', return_value=str(vs)), \
                        patch.object(ime.subprocess, 'run', side_effect=compile):
                    if emitted == 0xaa64:
                        self.call_architecture(ime.compile_observer, folder, 'Local\\owned', self.arm_readiness()['profile'])
                    else:
                        with self.assertRaisesRegex(AssertionError, 'architecture|ARM64|arm64'):
                            self.call_architecture(ime.compile_observer, folder, 'Local\\owned', self.arm_readiness()['profile'])
                self.assertTrue((folder/'compile-observer.cmd').is_file(), 'ARM64 compiler environment must be selected')
                script = (folder/'compile-observer.cmd').read_text()
                self.assertIn('vcvarsall.bat" arm64', script)
                self.assertIn('/MACHINE:ARM64', script)
                self.assertEqual(commands[0][0], 'cmd.exe')

    def test_architecture_helper_proves_native_controller_and_closes_owned_target_handle(self):
        helper = getattr(ime, 'native_arch', None)
        self.assertIsNotNone(helper, 'Actual IsWow64Process2 observation helper is required')
        class Function:
            def __init__(self, callback): self.callback = callback
            def __call__(self, *args): return self.callback(*args)
        for process_machine, native_machine, expected, accepted in (
                (0, 0xaa64, 'arm64', True), (0, 0x8664, 'x64', True),
                (0x8664, 0xaa64, 'arm64', False), (0, 0x8664, 'arm64', False),
                (0, 0xa641, 'arm64', False)):
            handles, closed = [], []
            def observe(handle, process, native):
                handles.append(handle)
                process._obj.value, native._obj.value = process_machine, native_machine
                return True
            kernel = SimpleNamespace(GetCurrentProcess=Function(lambda: 0x123456789abc),
                IsWow64Process2=Function(observe), OpenProcess=Function(lambda *args: 0x123456789def),
                CloseHandle=Function(lambda handle: closed.append(handle) or True))
            with self.subTest(process=process_machine, native=native_machine), \
                    patch.object(helper.ctypes, 'WinDLL', return_value=kernel, create=True):
                receipt = helper.observe_native_architecture()
                self.assertEqual(handles, [0x123456789abc])
                self.assertEqual(receipt['processMachine'], process_machine)
                self.assertEqual(receipt['nativeMachine'], native_machine)
                if accepted:
                    self.assertEqual(helper.validate_native_architecture(receipt, expected), receipt)
                    helper.observe_owned_process(123, expected)
                else:
                    with self.assertRaises(AssertionError): helper.validate_native_architecture(receipt, expected)
                    with self.assertRaises(AssertionError): helper.observe_owned_process(123, expected)
                self.assertEqual(closed, [0x123456789def])

if __name__ == '__main__': unittest.main()
