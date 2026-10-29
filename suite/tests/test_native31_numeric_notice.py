"""Current Suite privacy failures retain owned locations, without desktop text."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from suite.tests.test_numeric_notice import environment, implementation


ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Native31NumericNoticeTests(unittest.TestCase):
    def setUp(self):
        self.adapter = load('native31_numeric_adapter_test', 'e2e/native31_suite_prepare.py')
        self.core = load('native31_numeric_control_test', 'e2e/native31_desktop_control.py')
        self.codec = implementation()
        self.env = environment() | dict(OPENGEUL_SUITE_NOTICE_SCOPE='12',
            RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Windows',
            GITHUB_WORKFLOW_REF=self.adapter.WORKFLOW)
        self.event = dict(repository=dict(full_name='ATLKR/OpenGeul', id=123, private=False),
            sender=dict(login='ATLKR', id=65988341, type='User'),
            ref=self.adapter.BRANCH, deleted=False, after='a'*40)

    def raise_owned_failure(self, relative='e2e/native31_privacy_prepare.py'):
        exec(compile("raise ValueError('SYNTHETIC-PRIVATE-TEXT C:/private/caption')\n",
            str(ROOT / relative), 'exec'), {})

    def test_source_ids_append_and_root_paths_do_not_alias_suite_paths(self):
        self.assertEqual(self.codec.SOURCE_FILES['impress_focused_view.py'], 26)
        names = ('native31_desktop_control.py', 'native31_privacy_prepare.py',
                 'native31_suite_prepare.py', 'runner-ready.py', 'policy.py')
        self.assertEqual([self.codec.SOURCE_FILES[name] for name in names], list(range(27, 32)))
        self.assertEqual(self.codec.SCOPES['native31-privacy'], 12)
        self.assertEqual(self.codec.CASES['native31-privacy'], (59, 0))
        self.assertEqual(self.codec.STAGES['prepare-native31'], 94)
        for relative, code in [('e2e/native31_privacy_prepare.py', 28), ('ci/policy.py', 31),
                               ('suite/e2e/native31_privacy_prepare.py', 0)]:
            try: self.raise_owned_failure(relative)
            except ValueError as exc:
                failure = self.codec.capture_failure_code(exc)
                frames = self.codec.capture_failure_frames(exc)
            self.assertEqual(failure['fileCode'], code)
            self.assertEqual(frames, [[code, 1]] if code else [])

    def test_standalone_error_records_stay_unchanged_without_capture_scope(self):
        try: self.raise_owned_failure()
        except ValueError as exc: raw = self.core.error_record(exc)
        self.assertEqual(set(raw), {'type', 'message'})

    def test_numeric_capture_does_not_read_exception_text_and_scope_is_restored(self):
        class NoText(Exception):
            def __str__(self): raise AssertionError('Numeric capture cannot inspect text')
        try:
            exec(compile('raise error', str(ROOT / 'e2e/native31_privacy_prepare.py'), 'exec'), {'error':NoText()})
        except NoText as exc:
            code = self.codec.capture_failure_code(exc)
            frames = self.codec.capture_failure_frames(exc)
        self.assertEqual((code['fileCode'], code['line'], frames), (28, 1, [[28, 1]]))
        try: self.raise_owned_failure()
        except ValueError as exc:
            with self.core.numeric_failure_capture(self.codec):
                self.assertIn('numericFailure', self.core.error_record(exc))
            self.assertEqual(set(self.core.error_record(exc)), {'type', 'message'})

    def test_unavailable_optional_codec_does_not_replace_preparation_outcome(self):
        with patch.dict(os.environ, self.env), \
                patch.object(self.adapter.importlib.util, 'spec_from_file_location', side_effect=OSError('synthetic')):
            self.assertIsNone(self.adapter.numeric_codec())

    def run_failure(self, changes=None, *, observer=False, early=False):
        core, adapter = self.core, self.adapter
        observed = dict(closed=False, resumed=False)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            event_path = folder / 'event.json'
            event_path.write_text(json.dumps(self.event))
            output = folder / 'capture'
            env = self.env | dict(RUNNER_TEMP=directory, GITHUB_EVENT_PATH=str(event_path)) | (changes or {})
            host = dict(processId=45, processMachine=0, nativeMachine=0xaa64, sessionId=1,
                        process={'createdFileTime': 100}, windowsDirectory=r'C:\Windows')
            owner_test = self

            class Owner:
                def __init__(self, probe, environment, argv, budget, expected):
                    self.created = False; self.cleanup_outcomes = []
                    self.environment, self.budget = environment, budget
                def create_suspended(self): self.created = True
                def assign(self): pass
                def identity(self): return dict(processId=46, createdFileTime=101)
                def resume(self): observed['resumed'] = True
                def wait(self, seconds):
                    args = SimpleNamespace(output=output, deadline=self.budget.deadline, prepare_privacy=True)
                    return_code = core.observer(args, binding=adapter.control_binding(core))
                    owner_test.assertEqual(return_code, 1)
                    owner_test.assertEqual(self.environment.get('OPENGEUL_SUITE_NUMERIC_NOTICE'),
                        '1' if env.get('OPENGEUL_SUITE_NUMERIC_NOTICE') == '1' and env.get('OPENGEUL_SUITE_NOTICE_SCOPE') == '12' else None)
                    return True
                def exit_code(self): return 1
                def accounting(self): return dict(querySucceeded=True, activeProcesses=0)
                def close(self): observed['closed'] = True

            class Stream(io.StringIO):
                def write(self, text):
                    if text:
                        owner_test.assertTrue((output / '99-result.json').is_file())
                        if not early: owner_test.assertTrue(observed['closed'])
                    return super().write(text)

            stream = Stream()
            args = SimpleNamespace(architecture='arm64', observer=observer,
                deadline=core.Budget().deadline if observer else None, prepare_privacy=True, output=output)
            probe = SimpleNamespace(identity=lambda: host)
            if early: probe.identity = lambda: self.raise_owned_failure('e2e/native31_desktop_control.py')
            with patch.dict(os.environ, env), patch.object(adapter, 'read_event', return_value=self.event), \
                    patch.object(adapter, 'load_control', return_value=core), \
                    patch.object(core, 'os', SimpleNamespace(**(vars(os) | {'name':'nt'}))), \
                    patch.object(core, 'Probe', return_value=probe), \
                    patch.object(core, 'image_receipt', return_value={'peMachine':0xaa64}), \
                    patch.object(core, 'OwnedObserver', Owner), \
                    patch.object(core, 'capture', side_effect=lambda *a, **kw: self.raise_owned_failure()), redirect_stdout(stream):
                if observer:
                    core.Evidence.create(output, folder, max_files=72).write('10-controller', {})
                code = adapter.arm_entry(args, platform='nt')
            text = stream.getvalue()
            result = json.loads((output / ('89-observer-failure.json' if observer else '99-result.json')).read_text())
        return code, text, result, observed

    def test_actual_controller_cleanup_precedes_one_v2_notice_for_original_observer_failure(self):
        code, text, result, observed = self.run_failure()
        self.assertEqual(code, 1)
        self.assertTrue(observed['closed'])
        self.assertIn('numericFailure', result['observerFailure']['failure'])
        lines = text.splitlines()
        self.assertEqual(len(lines), 1)
        prefix = '::notice title=' + self.codec.CASE_TITLE + '::'
        self.assertTrue(lines[0].startswith(prefix))
        value = self.codec.decode_notice(lines[0][len(prefix):], 'a'*40, 123,
            expected_architecture=0xaa64, expected_scope=12)
        self.assertEqual(value['schemaVersion'], 2)
        self.assertEqual((value['caseCode'], value['stageCode'], value['moduleCode']), (59, 94, 0))
        self.assertEqual((value['fileCode'], value['line']), (28, 1))
        self.assertEqual(value['ownedFrames'][-1], [28, 1])
        self.assertEqual(value['sequence'], 1)
        self.assertEqual(value['remainingBudget'], 7)
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('C:/', text)
        for name in ('forcedCleanup', 'diagnosticRunnerPassed'):
            self.assertEqual(value['observations'][name], 0)
            self.assertTrue(value['fieldPresenceMask'] & (1 << self.codec.OBSERVATION_NAMES_V2.index(name)))
        self.assertFalse(value['fieldPresenceMask'] & (1 << self.codec.OBSERVATION_NAMES_V2.index('cleanupErrorCount')))

    def test_controller_failure_without_observer_keeps_its_actual_location(self):
        code, text, _, _ = self.run_failure(early=True)
        self.assertEqual(code, 1)
        value = self.codec.decode_notice(text.split('::', 2)[2].strip(), 'a'*40, 123, expected_scope=12)
        self.assertEqual((value['fileCode'], value['line']), (27, 1))

    def test_projection_keeps_cleanup_presence_and_rejects_mismatched_frames(self):
        try: self.raise_owned_failure()
        except ValueError as exc:
            failure = dict(numericFailure=self.codec.capture_failure_code(exc),
                numericFailureFrames=self.codec.capture_failure_frames(exc), cleanupFailures=[{'private':'SYNTHETIC-PRIVATE'}])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            path = output / '99-result.json'
            result = dict(success=False, forced=True, preparationFailure=failure)
            path.write_text(json.dumps(result))
            with patch.dict(os.environ, self.env), redirect_stdout(io.StringIO()) as stream:
                self.adapter.emit_failure_notice(self.core, self.codec, output)
            value = self.codec.decode_notice(stream.getvalue().split('::', 2)[2].strip(), 'a'*40, 123, expected_scope=12)
            self.assertEqual(value['observations']['cleanupErrorCount'], 1)
            self.assertEqual(value['observations']['forcedCleanup'], 1)
            self.assertNotIn('PRIVATE', stream.getvalue())
            failure['numericFailureFrames'][-1][1] += 1
            path.write_text(json.dumps(result))
            with patch.dict(os.environ, self.env), redirect_stdout(io.StringIO()) as stream:
                self.adapter.emit_failure_notice(self.core, self.codec, output)
            self.assertEqual(stream.getvalue(), '')

    def test_opt_out_and_wrong_scope_do_not_add_fields_or_emit(self):
        for changes in ({'OPENGEUL_SUITE_NUMERIC_NOTICE':'0'}, {'OPENGEUL_SUITE_NOTICE_SCOPE':'9'}):
            with self.subTest(changes=changes):
                code, text, result, _ = self.run_failure(changes)
                self.assertEqual(code, 1)
                self.assertEqual(text, '')
                self.assertNotIn('numericFailure', result['observerFailure']['failure'])

    def test_observer_captures_failure_without_emitting(self):
        code, text, result, _ = self.run_failure(observer=True)
        self.assertEqual(code, 1)
        self.assertEqual(text, '')
        self.assertIn('numericFailure', result['failure'])

    def test_unvalidated_context_and_x64_do_not_emit_or_enter_control(self):
        args = SimpleNamespace(architecture='arm64', observer=False, prepare_privacy=True)
        for changes in ({'RUNNER_ARCH':'X64'}, {'GITHUB_ACTOR':'other'}, {'GITHUB_WORKFLOW_SHA':'b'*40}):
            with self.subTest(changes=changes), patch.dict(os.environ, self.env | changes), \
                    patch.object(self.adapter, 'read_event', return_value=self.event), \
                    patch.object(self.adapter, 'load_control', side_effect=AssertionError('must reject before control')), \
                    redirect_stdout(io.StringIO()) as stream:
                with self.assertRaises(ValueError): self.adapter.arm_entry(args, platform='nt')
                self.assertEqual(stream.getvalue(), '')

    def test_action_exception_before_final_receipt_keeps_identity_after_context_unwind(self):
        class NoText(Exception):
            def __str__(self): raise AssertionError('Numeric projection cannot inspect text')
        for observer in (False, True):
            with self.subTest(observer=observer):
                sentinel = NoText()
                def unavailable_evidence(*args, **kwargs):
                    exec(compile('raise error', str(ROOT / 'e2e/native31_desktop_control.py'), 'exec'),
                         {'error':sentinel})
                args = SimpleNamespace(architecture='arm64', observer=observer, prepare_privacy=True,
                    deadline=self.core.Budget().deadline if observer else None, output=ROOT / 'unused')
                unavailable = (patch.object(self.core, 'Evidence', side_effect=unavailable_evidence) if observer
                    else patch.object(self.core.Evidence, 'create', side_effect=unavailable_evidence))
                with patch.dict(os.environ, self.env | {'RUNNER_TEMP':str(ROOT)}), patch.object(self.adapter, 'read_event', return_value=self.event), \
                        patch.object(self.adapter, 'load_control', return_value=self.core), unavailable, \
                        patch.object(self.core, 'Probe', side_effect=AssertionError('No native action before evidence')), \
                        redirect_stdout(io.StringIO()) as stream:
                    try: self.adapter.arm_entry(args, platform='nt')
                    except NoText as exc: self.assertIs(exc, sentinel)
                    else: self.fail('The original action exception must escape unchanged')
                self.assertEqual(set(self.core.error_record(ValueError('synthetic'))), {'type', 'message'})
                if observer:
                    self.assertEqual(stream.getvalue(), '')
                    continue
                lines = stream.getvalue().splitlines()
                self.assertEqual(len(lines), 1)
                value = self.codec.decode_notice(lines[0].split('::', 2)[2], 'a'*40, 123, expected_scope=12)
                self.assertEqual(value['schemaVersion'], 2)
                self.assertEqual((value['fileCode'], value['line']), (27, 1))
                self.assertEqual(value['ownedFrames'][-1], [27, 1])
                self.assertEqual(value['fieldPresenceMask'], 0)
                self.assertNotIn('PRIVATE', stream.getvalue())


if __name__ == '__main__': unittest.main()
