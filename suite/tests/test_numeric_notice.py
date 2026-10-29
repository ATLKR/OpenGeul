"""Future notices expose only closed observations from the current owned controller."""
import copy
from contextlib import redirect_stdout
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'e2e/numeric_notice.py'


def implementation():
    assert SCRIPT.is_file(), 'Closed numeric notice implementation is required'
    spec = importlib.util.spec_from_file_location('numeric_notice', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment():
    return dict(OPENGEUL_SUITE_NUMERIC_NOTICE='1', GITHUB_ACTIONS='true',
                GITHUB_REPOSITORY='ATLKR/OpenGeul', GITHUB_JOB='windows-suite',
                GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/work/opengeul-office-arm64',
                GITHUB_ACTOR='ATLKR', GITHUB_ACTOR_ID='65988341',
                GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a'*40,
                GITHUB_WORKFLOW_SHA='a'*40, RUNNER_ARCH='ARM64', OPENGEUL_SUITE_NOTICE_SCOPE='1')


class NumericNoticeTests(unittest.TestCase):
    def test_uno_runtime_exception_code_is_append_only_without_importing_uno(self):
        self.assertEqual(self.n.UNO_RUNTIME_EXCEPTION_CODE,13)
        self.assertEqual(list(self.n.EXCEPTIONS.values()),list(range(1,13)))
        failure=dict(captured=1,exceptionCode=13,fileCode=1,line=99)
        self.assertEqual(self.n.validate_failure_code(failure),failure)
        with self.assertRaises(ValueError):self.n.validate_failure_code(failure|{'exceptionCode':14})

    def setUp(self):
        self.n = implementation()
        self.stream = io.StringIO()
        self.env = environment()
        self.emitter = self.n.NoticeEmitter(environ=self.env, stream=self.stream)

    def failure(self):
        try:
            raise AssertionError('SYNTHETIC-PRIVATE-INPUT C:/private/path ::error::caption')
        except AssertionError as exc:
            return self.n.capture_failure_code(exc)

    def messages(self):
        return [line.split('::', 2)[2] for line in self.stream.getvalue().splitlines()]

    def decode(self, message, **kwargs):
        return self.n.decode_notice(message, 'a'*40, 123, expected_architecture=0xaa64, **kwargs)

    def test_privacy_projection_never_serializes_arbitrary_nested_fields(self):
        private = 'SYNTHETIC-PRIVATE-INPUT'
        record = dict(module='calc', stage='save-ctrl-s', success=False, shellPid=42,
                      numericFailure=self.failure(), error=private, traceback=private,
                      file='C:/' + private, title=private, input=private,
                      nested=dict(caption=private, proxyText=private, document=[private]),
                      cleanupErrors=[private])
        self.assertTrue(self.emitter.emit_case_notice('ime-calc', record))
        rendered = self.stream.getvalue()
        self.assertNotIn(private, rendered)
        self.assertNotIn('C:/', rendered)
        self.assertEqual(len(self.messages()), 1)
        decoded = self.decode(self.messages()[0])
        self.assertEqual(decoded['kind'], 1)
        self.assertEqual(decoded['observations']['shellPid'], 42)
        self.assertEqual(decoded['exceptionCode'], self.n.EXCEPTIONS[AssertionError])
        self.assertLessEqual(len(self.messages()[0].encode()), 2048)
        for key, value in decoded.items():
            if key not in ('sourceCommit', 'observations'):
                self.assertIs(type(value), int, key)
        self.assertTrue(all(type(value) is int for value in decoded['observations'].values()))

    def test_unknown_fields_have_zero_values_and_unset_presence_bits(self):
        record = dict(numericFailure=self.failure(), shellPid=True, officePid='42',
                      shellExitCode=0, cleanClose=0, officeCreationTime=-1)
        self.assertTrue(self.emitter.emit_case_notice('calc', record))
        decoded = self.decode(self.messages()[0])
        for name in ('shellPid', 'enginePid', 'officeCreationTime', 'cleanClose'):
            self.assertEqual(decoded['observations'][name], 0)
            self.assertFalse(decoded['fieldPresenceMask'] & (1 << self.n.OBSERVATION_NAMES.index(name)))
        bit = 1 << self.n.OBSERVATION_NAMES.index('shellExitCode')
        self.assertTrue(decoded['fieldPresenceMask'] & bit)
        self.assertEqual(decoded['observations']['shellExitCode'], 0)

    def test_original_calc_save_write_result_emits_one_closed_failure_after_cleanup(self):
        with patch.object(sys, 'path', [str(SCRIPT.parent), *sys.path]):
            import windows_smoke as native
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '13'
        filename = str(SCRIPT.with_name('calc_save_smoke.py'))
        try:
            exec(compile("raise AssertionError('SYNTHETIC-PRIVATE-INPUT C:/private/profile')", filename, 'exec'), {})
        except AssertionError as exc:
            record = dict(case='calc-active-cell-save', module='calc', success=False,
                stage='physical-edit-without-enter', error='SYNTHETIC-PRIVATE-INPUT',
                numericFailure=self.n.capture_failure_code(exc),
                numericFailureFrames=self.n.capture_failure_frames(exc),
                testProcessCleanup=dict(shellExitCode=1, forceRequested=True))
        with tempfile.TemporaryDirectory() as temp, patch.object(native, 'numeric_notice', self.n), \
                patch.object(self.n, '_EMITTER', self.emitter):
            native.write_result(Path(temp), 'calc-active-cell-save', record)
            self.assertTrue((Path(temp)/'calc-active-cell-save-result.json').is_file())
        self.assertEqual(len(self.messages()), 1)
        value = self.decode(self.messages()[0], expected_scope=13)
        self.assertEqual((value['schemaVersion'], value['caseCode'], value['moduleCode'], value['fileCode']), (2,60,2,33))
        self.assertGreater(value['stageCode'], 94)
        self.assertEqual(value['ownedFrames'][-1], [33,1])
        self.assertEqual(value['observations']['cleanupShellExitCode'], 1)
        self.assertEqual(value['observations']['forceRequested'], 1)
        self.assertNotIn('SYNTHETIC-PRIVATE-INPUT', self.stream.getvalue())
        self.assertNotIn('C:/private', self.stream.getvalue())

    def test_normal_calc_save_workflow_opts_into_original_single_notice_path(self):
        from suite.tests.test_calc_matrix_workflow import workflow_steps, field, run_code
        rows = [step for step in workflow_steps() if field(step, 'id') == 'calc-save']
        self.assertEqual(len(rows), 1)
        self.assertIn("        OPENGEUL_SUITE_NUMERIC_NOTICE: '1'", rows[0])
        self.assertIn("        OPENGEUL_SUITE_NOTICE_SCOPE: '13'", rows[0])
        self.assertEqual(run_code(rows[0]).count('python suite/e2e/calc_save_smoke.py '), 1)
        self.assertIn("env.OPENGEUL_SUITE_RUN_MODE == 'acceptance'", field(rows[0], 'if'))

    def test_native_archive_failure_uses_closed_v1_notice_and_owned_source_location(self):
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '10'
        namespace = {}
        filename = str(SCRIPT.with_name('native_archive_completeness.py'))
        try:
            exec(compile("raise ValueError('SYNTHETIC-PRIVATE-INPUT C:/private/profile')", filename, 'exec'), namespace)
        except ValueError as exc:
            failure = self.n.capture_failure_code(exc)
        self.assertTrue(self.emitter.emit_case_notice('native-integrity',
            dict(success=False, stage='verify-native-archives', numericFailure=failure)))
        decoded = self.decode(self.messages()[0], expected_scope=10)
        self.assertEqual(decoded['fileCode'], 23)
        self.assertEqual(decoded['line'], 1)
        self.assertEqual(decoded['caseCode'], 58)
        self.assertEqual(decoded['stageCode'], 93)
        self.assertEqual(decoded['moduleCode'], 0)
        self.assertEqual(len(decoded['observations']), 49)
        self.assertNotIn('PRIVATE', self.stream.getvalue())
        self.assertNotIn('C:/', self.stream.getvalue())
        self.assertEqual(self.n.CASES['ime-calc'][0], 18)
        self.assertEqual(self.n.SOURCE_FILES['calc_pending_input.py'], 22)

    def test_native_archive_success_does_not_invent_failure_notice(self):
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '10'
        self.assertFalse(self.emitter.emit_case_notice('native-integrity',
            dict(success=True, stage='verify-native-archives', expectedGenerations=79)))
        self.assertEqual(self.stream.getvalue(), '')

    def test_transitional_success_false_and_accepted_engine_exit_do_not_emit(self):
        record = dict(success=False, guiVerified=True, cleanClose=True,
                      stage='gui-complete', officeExitCode=1)
        self.assertFalse(self.emitter.emit_case_notice('writer-heading1', record))
        self.assertEqual(self.stream.getvalue(), '')
        record['officeExitedAfterCleanup'] = False
        self.assertTrue(self.emitter.emit_case_notice('writer-heading1', record))

    def test_identical_writes_deduplicate_and_only_two_numeric_changes_per_case(self):
        record = dict(numericFailure=self.failure(), shellPid=42)
        self.assertTrue(self.emitter.emit_case_notice('ime-calc', record))
        record['error'] = 'different private text'
        self.assertFalse(self.emitter.emit_case_notice('ime-calc', record))
        record['cleanClose'] = False
        self.assertTrue(self.emitter.emit_case_notice('ime-calc', record))
        record['cleanClose'] = True
        self.assertFalse(self.emitter.emit_case_notice('ime-calc', record))
        self.assertEqual(len(self.messages()), 2)

    def test_controller_emits_at_most_eight_notices(self):
        record = dict(numericFailure=self.failure())
        for name in ('writer', 'calc', 'impress', 'draw', 'math', 'base', 'home', 'new-writer', 'new-calc'):
            self.emitter.emit_case_notice(name, record)
        self.assertEqual(len(self.messages()), 8)
        final = self.decode(self.messages()[-1])
        self.assertEqual(final['sequence'], 8)
        self.assertEqual(final['remainingBudget'], 0)

    def test_disabled_unit_context_and_invalid_provenance_never_emit(self):
        for changes in ({'OPENGEUL_SUITE_NUMERIC_NOTICE': '0'}, {'GITHUB_SHA': 'PRIVATE'},
                        {'GITHUB_RUN_ATTEMPT': '2'}, {'GITHUB_WORKFLOW_SHA': 'b'*40},
                        {'OPENGEUL_SUITE_NOTICE_SCOPE': ''}, {'OPENGEUL_SUITE_NOTICE_SCOPE': '11'}):
            with self.subTest(changes=changes):
                stream = io.StringIO()
                emitter = self.n.NoticeEmitter(environ=self.env | changes, stream=stream)
                self.assertFalse(emitter.emit_case_notice('writer', dict(numericFailure=self.failure())))
                self.assertEqual(stream.getvalue(), '')

    def test_exception_metadata_uses_owned_code_ids_without_formatting_messages(self):
        class NoStringError(Exception):
            def __str__(self): raise AssertionError('Exception message must never be read')
        namespace = dict(error=NoStringError())
        filename = str(SCRIPT.with_name('calc_close_probe.py'))
        try:
            exec(compile('raise error\n', filename, 'exec'), namespace)
        except NoStringError as exc:
            result = self.n.capture_failure_code(exc)
        self.assertEqual(result, dict(captured=1, exceptionCode=0,
                                     fileCode=self.n.SOURCE_FILES['calc_close_probe.py'], line=1))
        self.assertNotIn('calc_close_probe.py', json.dumps(result))

    def test_receiver_rejects_duplicate_keys_extras_type_coercion_and_wrong_context(self):
        self.emitter.emit_case_notice('writer', dict(numericFailure=self.failure()))
        message = self.messages()[0]
        base = json.loads(message)
        cases = ['{"kind":1,' + message[1:], message + ' ' * 2049]
        for changed in ({'private': 'PRIVATE'}, {'runId': True}, {'exceptionCode': '1'},
                        {'sourceCommit': 'b'*40}, {'runAttempt': 2}, {'architecture': 0x8664}):
            cases.append(json.dumps(base | changed))
        changed = copy.deepcopy(base); changed['observations']['shellPid'] = 'PRIVATE'; cases.append(json.dumps(changed))
        for value in cases:
            with self.subTest(value=value[:45]), self.assertRaises((ValueError, TypeError)):
                self.decode(value)
        with self.assertRaises(ValueError): self.decode(message, title='Unapproved title')

    def test_escaping_and_broken_output_cannot_replace_the_primary_failure(self):
        self.assertEqual(self.n.escape_data('%\r\n::notice::'), '%25%0D%0A::notice::')
        class BrokenStream:
            def write(self, value): raise OSError('PRIVATE stream failure')
            def flush(self): raise OSError('PRIVATE stream failure')
        emitter = self.n.NoticeEmitter(environ=self.env, stream=BrokenStream())
        self.assertFalse(emitter.emit_case_notice('writer', dict(numericFailure=self.failure())))

    def test_no_native_process_filesystem_or_clock_queries_are_needed(self):
        record = dict(numericFailure=self.failure(), cleanClose=False)
        with patch('os.stat', side_effect=AssertionError('No filesystem observation')), \
             patch('subprocess.run', side_effect=AssertionError('No process observation')), \
             patch('time.monotonic', side_effect=AssertionError('No renewed budget')):
            self.assertTrue(self.emitter.emit_case_notice('writer', record))
            self.decode(self.messages()[0])

    def test_closed_helper_failure_is_preferred_over_the_outer_wrapper(self):
        expected = dict(captured=1, exceptionCode=self.n.EXCEPTIONS[ValueError],
                        fileCode=self.n.SOURCE_FILES['writer_model_reader.py'], line=321)
        error = AssertionError('PRIVATE outer wrapper')
        error.raw = dict(error=dict(numericFailure=expected, message='PRIVATE nested content',
                                   traceback='PRIVATE traceback', input=['PRIVATE']))
        self.assertEqual(self.n.capture_failure_code(error), expected)
        self.assertEqual(self.n.validate_failure_code(expected), expected)
        for invalid in (expected | {'path': 'PRIVATE'}, expected | {'captured': True},
                        expected | {'exceptionCode': '7'}, expected | {'fileCode': 0}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.n.validate_failure_code(invalid)

    def test_shared_hooks_capture_before_formatting_and_preserve_write_failure(self):
        import sys
        sys.path.insert(0, str(SCRIPT.parent))
        smoke = importlib.import_module('windows_smoke')
        actual = importlib.import_module('numeric_notice')
        class FormatFailure(Exception):
            def __str__(self): raise RuntimeError('Synthetic existing formatter failure')
        record = dict(module='calc', stage='attach')
        with patch.dict(os.environ, self.env, clear=True), patch.object(actual, '_EMITTER', self.emitter):
            with self.assertRaisesRegex(RuntimeError, 'existing formatter'):
                smoke.capture_failure(Path('/unused'), 'calc', record, FormatFailure())
            self.assertEqual(record['numericFailure']['captured'], 1)
            self.assertEqual(record['numericFailureFrames'],[])
            primary = OSError('Synthetic existing result write failure')
            with patch.object(Path, 'write_text', side_effect=primary):
                with self.assertRaises(OSError) as raised:
                    smoke.write_result(Path('/unused'), 'calc', record)
            self.assertIs(raised.exception, primary)
        self.assertEqual(len(self.messages()), 1)

    def trace_report(self):
        import sys
        sys.path.insert(0, str(SCRIPT.parent))
        import calc_dispatch_diagnostic as diagnostic
        trace = dict(schemaVersion=1, kind=diagnostic.KIND, acceptanceEligible=False,
            fullEngineQualified=False, identity=None, state=None, stack=[], events=[],
            capture=dict(stable=0,partialSequence=0,withinDeadline=0), exit=diagnostic._empty_exit(),
            cleanup=diagnostic._empty_cleanup(), snapshotError=1, analysis=None)
        trace = diagnostic.decode_artifact(trace)
        return dict(schemaVersion=1,kind='calc-save-dispatch-diagnostic',acceptanceEligible=False,
            fullEngineQualified=False,imeVerified=False,expectedCaseCount=1,success=False,
            originalSaveOracle=dict(saveAttempted=True,saveReturned=False,savedMarkerObserved=False),
            numericOracleObserved=True,diagnostic=trace,localCleanup=dict(errors=[],withinDeadline=True),
            runBinding=dict(sourceCommit='a'*40,runId='123',runAttempt='1',architecture='arm64'))

    def test_optional_calc_trace_is_validated_bounded_and_shares_notice_budget(self):
        self.env[self.n.TRACE_OPT_IN] = '1'
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '9'
        self.assertEqual(self.emitter.emit_calc_report(self.trace_report()), 2)
        self.assertEqual(len(self.messages()), 2)
        trace = self.decode(self.messages()[1], title=self.n.TRACE_TITLE)
        self.assertEqual(trace['kind'], 2)
        self.assertEqual(trace['schemaVersion'],1)
        changed=dict(trace,schemaVersion=2)
        with self.assertRaises(ValueError):self.decode(json.dumps(changed),title=self.n.TRACE_TITLE)
        self.assertIs(trace['diagnostic']['acceptanceEligible'], False)
        self.assertLessEqual(len(self.messages()[1].encode()), 32768)
        with self.assertRaises(ValueError):
            self.decode(self.messages()[1] + ' '*32769, title=self.n.TRACE_TITLE)
        record = dict(numericFailure=self.failure())
        for name in ('writer','calc','impress','draw','math','base','home'):
            self.emitter.emit_case_notice(name,record)
        self.assertEqual(len(self.messages()), 8)

    def test_calc_trace_rejects_raw_extras_and_unobserved_oracle_remains_unknown(self):
        self.env[self.n.TRACE_OPT_IN] = '1'
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '9'
        invalid = self.trace_report()
        invalid['diagnostic']['caption'] = 'PRIVATE document caption'
        self.assertEqual(self.emitter.emit_calc_report(invalid), 0)
        self.assertEqual(self.stream.getvalue(), '')
        report = self.trace_report(); report['numericOracleObserved'] = False
        self.assertEqual(self.emitter.emit_calc_report(report), 2)
        summary = self.decode(self.messages()[0])
        for key in ('saveAttempted','saveReturned','savedMarkerObserved'):
            self.assertFalse(summary['fieldPresenceMask'] & (1 << self.n.OBSERVATION_NAMES.index(key)))
            self.assertEqual(summary['observations'][key], 0)

    def test_missing_native_admission_does_not_promote_default_oracle_keys(self):
        self.env[self.n.TRACE_OPT_IN] = '1'
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '9'
        self.assertEqual(self.emitter.emit_calc_report(self.trace_report()),2)
        trace = self.decode(self.messages()[1],title=self.n.TRACE_TITLE)
        self.assertEqual(trace['oraclePresenceMask'],0)
        self.assertEqual(trace['oracleFlags'],[0,0,0])
        summary = self.decode(self.messages()[0])
        bit = 1 << self.n.OBSERVATION_NAMES.index('saveAttempted')
        self.assertFalse(summary['fieldPresenceMask'] & bit)

    def test_product_compartment_and_privacy_steps_opt_in_and_unit_steps_never_do(self):
        from suite.tests.test_calc_matrix_workflow import WORKFLOW, workflow_steps, field, run_code
        fragments = ('calc_close_probe.py --suite', 'home_routing_smoke.py --suite',
                     '--output .work/suite-korean-ime\n', 'korean_ui_smoke.py --suite',
                     'writer_style_smoke.py --suite', 'lifecycle_smoke.py --suite',
                     '--output .work/suite-native\n', '--output .work/suite-native-2\n',
                     '--diagnose-calc-dispatch --expected-engine-source-commit',
                     'verify_native_archive_completeness(')
        expected = [next(step for step in workflow_steps() if field(step,'run')=='|' and fragment in run_code(step))
                    for fragment in fragments]
        actual = [step for step in workflow_steps() if "OPENGEUL_SUITE_NUMERIC_NOTICE: '1'" in step]
        compartment=next(step for step in workflow_steps() if field(step,'id')=='ime-mode-diagnostic')
        privacy=next(step for step in workflow_steps() if field(step,'id')=='native31-privacy-prepare')
        calc_save=next(step for step in workflow_steps() if field(step,'id')=='calc-save')
        self.assertEqual({step.splitlines()[0] for step in actual}, {step.splitlines()[0] for step in (*expected,compartment,privacy,calc_save)})
        self.assertIn("OPENGEUL_SUITE_NOTICE_SCOPE: '3'",compartment)
        self.assertIn("OPENGEUL_SUITE_NOTICE_SCOPE: '12'",privacy)
        self.assertIn("OPENGEUL_SUITE_NOTICE_SCOPE: '13'",calc_save)
        for scope,step in enumerate(expected,1):
            self.assertIn("OPENGEUL_SUITE_NOTICE_SCOPE: '"+str(scope)+"'",step)
        traced = [step for step in workflow_steps() if 'OPENGEUL_SUITE_CALC_TRACE_NOTICE' in step]
        self.assertEqual(traced,[expected[8]])
        self.assertIn("OPENGEUL_SUITE_CALC_TRACE_NOTICE: '1'",traced[0])
        self.assertNotIn('OPENGEUL_SUITE_NUMERIC_NOTICE', WORKFLOW.read_text().split('jobs:')[0])
        unit=next(step for step in workflow_steps() if field(step,'id')=='suite-unit-shell')
        self.assertNotIn('OPENGEUL_SUITE_NUMERIC_NOTICE',unit)
        self.assertIn('python -m suite.scripts.run_unit_checks -s suite/tests -v',run_code(unit))

    def test_maximum_closed_case_values_fit_the_wire_limit(self):
        value=self.n.project_case_notice('calc',dict(numericFailure=dict(captured=1,
            exceptionCode=max(self.n.EXCEPTIONS.values()),fileCode=max(self.n.SOURCE_FILES.values()),
            line=10_000_000)),environ=self.env)
        value['fieldPresenceMask']=(1<<len(self.n._FIELDS))-1
        for key,kind,_ in self.n._FIELDS:
            value['observations'][key]=1 if kind in ('bool','flag') else (2**64-1 if kind=='u64' else 0xffffffff)
        self.assertTrue(self.emitter._emit(self.n.CASE_TITLE,value,value['caseCode']))
        self.assertLessEqual(len(self.messages()[0].encode('utf-8')),self.n.MAX_CASE_BYTES)
        self.decode(self.messages()[0])

    def test_lifecycle_aggregate_uses_only_counts_and_an_explicit_failure_signal(self):
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '6'
        report = dict(success=False, expectedCaseCount=7, completedCaseCount=7,
                      passedCaseCount=6, failedCases=['PRIVATE case'], missingCases=[],
                      duplicateCases=[], unexpectedCases=[], baselineFixturesUnchanged=False,
                      error='PRIVATE error', tests=[dict(document='PRIVATE text')])
        self.assertTrue(self.emitter.emit_case_notice('lifecycle-summary', report))
        decoded = self.decode(self.messages()[0])
        self.assertGreater(decoded['caseCode'], 0)
        self.assertEqual(decoded['observations']['failedCaseCount'], 1)
        self.assertEqual(decoded['observations']['expectedCaseCount'], 7)
        self.assertNotIn('PRIVATE', self.stream.getvalue())

    def test_collector_setup_failure_retains_direct_exception_metadata(self):
        import sys
        sys.path.insert(0, str(SCRIPT.parent))
        smoke = importlib.import_module('windows_smoke')
        actual = importlib.import_module('numeric_notice')
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '7'
        def fail(): raise ValueError('PRIVATE setup text')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,self.env,clear=True), \
             patch.object(actual,'_EMITTER',self.emitter), redirect_stdout(io.StringIO()):
            rows = smoke.collect_cases([('writer',fail)],Path(folder))
        self.assertFalse(rows[0]['success'])
        self.assertEqual(len(self.messages()),1)
        self.assertEqual(self.decode(self.messages()[0])['exceptionCode'],self.n.EXCEPTIONS[ValueError])

    def test_calc_final_report_hook_is_numeric_and_cannot_change_original_exit(self):
        from suite.tests import test_calc_dispatch_integration as integration
        import sys
        actual = importlib.import_module('numeric_notice')
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '9'
        trace = self.trace_report()['diagnostic']
        record = dict(success=False, error='PRIVATE input', traceback='PRIVATE traceback',
                      asciiPrefix='PRIVATE document', numericFailure=self.failure(),
                      calcDispatchDiagnostic=trace,
                      calcDispatchOracle=dict(saveAttempted=True,saveReturned=False,savedMarkerObserved=False),
                      calcDispatchLocalCleanup=dict(errors=[],withinDeadline=True))
        binding = dict(sourceCommit='a'*40,runId='123',runAttempt='1',architecture='arm64')
        for broken in (False,True):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as folder:
                calls = []
                def emit(value):
                    calls.append(copy.deepcopy(value))
                    if broken: raise OSError('PRIVATE emitter failure')
                with patch.dict(os.environ,self.env,clear=True), patch.object(actual,'emit_calc_report',side_effect=emit), \
                     patch.object(integration.ime.ascii_input,'prepare_observer',return_value='synthetic'), \
                     patch.object(integration.ime,'case',return_value=record), \
                     patch.dict(sys.modules,{'calc_dispatch_diagnostic':SimpleNamespace(
                         DiagnosticTransport=lambda **kwargs:SimpleNamespace(close=lambda:None))}):
                    code = integration.ime.run_calc_dispatch_diagnostic(Path('/suite'),Path('/fixtures'),Path(folder),{},'arm64',binding)
                self.assertEqual(code,1)
                self.assertEqual(len(calls),1)
                self.assertNotIn('PRIVATE',json.dumps(calls[0]))
                self.assertIs(calls[0]['numericOracleObserved'],True)
                self.assertEqual(calls[0]['numericFailure'],record['numericFailure'])

    def test_trace_receiver_rejects_oracle_claims_without_original_native_identity(self):
        self.env[self.n.TRACE_OPT_IN] = '1'; self.env['OPENGEUL_SUITE_NOTICE_SCOPE'] = '9'
        self.emitter.emit_calc_report(self.trace_report())
        trace = json.loads(self.messages()[1]); trace.update(oraclePresenceMask=7,oracleFlags=[1,1,1])
        with self.assertRaises(ValueError): self.decode(json.dumps(trace),title=self.n.TRACE_TITLE)

    def test_receiver_rejects_mismatched_case_and_module_codes(self):
        self.emitter.emit_case_notice('writer',dict(numericFailure=self.failure()))
        message = json.loads(self.messages()[0]); message['moduleCode']=self.n.MODULES['calc']
        with self.assertRaises(ValueError): self.decode(json.dumps(message))

    def test_result_write_failure_without_prior_failure_still_preserves_and_emits(self):
        import sys
        sys.path.insert(0,str(SCRIPT.parent))
        smoke=importlib.import_module('windows_smoke'); actual=importlib.import_module('numeric_notice')
        record=dict(success=False,guiVerified=True,cleanClose=True,stage='gui-complete')
        primary=OSError('PRIVATE result write failure')
        with patch.dict(os.environ,self.env,clear=True), patch.object(actual,'_EMITTER',self.emitter), \
             patch.object(Path,'write_text',side_effect=primary):
            with self.assertRaises(OSError) as raised: smoke.write_result(Path('/unused'),'writer-heading1',record)
        self.assertIs(raised.exception,primary)
        self.assertEqual(len(self.messages()),1)
        self.assertEqual(self.decode(self.messages()[0])['exceptionCode'],self.n.EXCEPTIONS[OSError])

    def test_calc_without_source_snapshot_keeps_stage_and_original_failure_unknown(self):
        self.env[self.n.TRACE_OPT_IN]='1'; self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        self.emitter.emit_calc_report(self.trace_report())
        summary=self.decode(self.messages()[0])
        self.assertEqual((summary['stageCode'],summary['exceptionCode'],summary['fileCode'],summary['line']),(0,0,0,0))
        self.assertEqual(summary['observations']['diagnosticRunnerPassed'],0)
        bit=1<<self.n.OBSERVATION_NAMES.index('diagnosticRunnerPassed')
        self.assertTrue(summary['fieldPresenceMask'] & bit)

    def test_calc_success_snapshot_reports_real_cleanup_without_inventing_failure(self):
        self.env[self.n.TRACE_OPT_IN]='1'; self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        self.assertTrue(callable(getattr(self.n,'capture_calc_snapshot',None)))
        record=dict(kind='calc-save-dispatch-diagnostic',module='calc',success=True,stage='save-ctrl-s',
                    calcDispatchShell=dict(shellExitObserved=True,shellHandleReleased=True,exitCode=0,error=0),
                    calcDispatchLocalCleanup=dict(errors=[],withinDeadline=True),
                    imeKeyboardSession=dict(engineHandleReleased=True,cleanupErrors=[]),
                    imeEngineRetirement=dict(close=dict(result=True),cleanupErrors=[]),
                    error='PRIVATE prior text',traceback='PRIVATE traceback')
        snapshot=self.n.capture_calc_snapshot(record,environ=self.env)
        self.assertNotIn('PRIVATE',json.dumps(snapshot))
        report=self.trace_report(); report.update(success=True,numericCaseSnapshot=snapshot)
        self.assertEqual(self.emitter.emit_calc_report(report),2)
        summary=self.decode(self.messages()[0])
        self.assertEqual(summary['stageCode'],self.n.STAGES['save-ctrl-s'])
        self.assertEqual(summary['exceptionCode'],0)
        for field in ('diagnosticRunnerPassed','shellExitObserved','shellHandleReleased','retirementClosed'):
            self.assertEqual(summary['observations'][field],1)
            self.assertTrue(summary['fieldPresenceMask'] & (1<<self.n.OBSERVATION_NAMES.index(field)))

    def test_owned_semantic_and_pending_getter_frames_have_append_only_ids(self):
        for name,expected in (('ime_semantic_context.py',21),('calc_pending_input.py',22)):
            with self.subTest(name=name):
                try: exec(compile('raise ValueError("PRIVATE")\n',str(SCRIPT.with_name(name)),'exec'))
                except ValueError as exc: result=self.n.capture_failure_code(exc)
                self.assertEqual(result['fileCode'],expected)
                self.assertEqual(result['line'],1)

    def test_unapproved_helper_case_names_do_not_create_another_controller_channel(self):
        record=dict(numericFailure=self.failure(),success=False)
        self.assertFalse(self.emitter.emit_case_notice('packaged-uno',record))
        self.assertFalse(self.emitter.emit_case_notice('PRIVATE case',record))
        self.assertEqual(self.stream.getvalue(),'')

    def test_zero_native_identity_is_unknown_even_when_source_key_exists(self):
        record=dict(numericFailure=self.failure(),shellPid=0,officePid=0,officeCreationTime=0)
        self.emitter.emit_case_notice('writer',record)
        value=self.decode(self.messages()[0])
        for field in ('shellPid','enginePid','officeCreationTime'):
            self.assertFalse(value['fieldPresenceMask'] & (1<<self.n.OBSERVATION_NAMES.index(field)))

    def test_source_calc_snapshot_also_marks_unadmitted_oracle_unknown(self):
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        record=dict(kind='calc-save-dispatch-diagnostic',module='calc',stage='save-ctrl-s',
                    calcDispatchOracle=dict(saveAttempted=True,saveReturned=False,savedMarkerObserved=False))
        snapshot=self.n.capture_calc_snapshot(record,environ=self.env)
        for field in ('saveAttempted','saveReturned','savedMarkerObserved'):
            self.assertEqual(snapshot['observations'][field],0)
            self.assertFalse(snapshot['fieldPresenceMask'] & (1<<self.n.OBSERVATION_NAMES.index(field)))

    def test_v2_preserves_owned_frames_and_only_typed_existing_composition_progress(self):
        record=dict(numericFailure=self.failure(),numericFailureFrames=[[13,262],[24,80]],
            imeCompositionOrdinal=3,imeCompositionStartEventCount=0,
            expected='PRIVATE composition',events=[dict(text='PRIVATE')],traceback='PRIVATE path')
        self.assertTrue(self.emitter.emit_case_notice('ime-impress',record))
        value=self.decode(self.messages()[0])
        self.assertEqual(value['schemaVersion'],2)
        self.assertEqual(value['ownedFrames'],[[13,262],[24,80]])
        self.assertEqual(len(self.n.OBSERVATION_NAMES),49)
        self.assertEqual(len(value['observations']),51)
        self.assertNotIn('PRIVATE',self.messages()[0])
        for key,expected in (('imeCompositionOrdinal',3),('imeCompositionStartEventCount',0)):
            self.assertEqual(value['observations'][key],expected)
            self.assertTrue(value['fieldPresenceMask'] & (1<<self.n.OBSERVATION_NAMES_V2.index(key)))

    def test_v1_compatibility_is_preserved_when_no_new_observations_exist(self):
        self.emitter.emit_case_notice('writer',dict(numericFailure=self.failure()))
        value=self.decode(self.messages()[0])
        self.assertEqual(value['schemaVersion'],1)
        self.assertNotIn('ownedFrames',value)
        self.assertEqual(tuple(value['observations']),self.n.OBSERVATION_NAMES)
        self.assertEqual(self.n.SOURCE_FILES['native_archive_completeness.py'],23)
        self.assertEqual(self.n.SOURCE_FILES['capture_readiness.py'],24)
        self.assertEqual(self.n.SOURCE_FILES['ascii_editor_input.py'],25)
        self.assertEqual(self.n.SOURCE_FILES['impress_focused_view.py'],26)

    def test_owned_frame_walk_is_bounded_and_keeps_deepest_eight_observed_frames(self):
        self.assertTrue(callable(getattr(self.n,'capture_failure_frames',None)))
        code=''.join('def f'+str(index)+'():\n '+('return f'+str(index+1)+'()' if index<69 else 'raise ValueError("PRIVATE")')+'\n' for index in range(70))+'f0()\n'
        try:exec(compile(code,str(SCRIPT.with_name('windows_smoke.py')),'exec'),{})
        except ValueError as exc:frames=self.n.capture_failure_frames(exc)
        self.assertEqual(frames,[[1,line] for line in range(110,126,2)])
        self.assertEqual(self.n.capture_failure_frames(None),[])
        self.assertNotIn('PRIVATE',json.dumps(frames))

    def test_capture_readiness_frame_is_appended_without_reading_exception_text(self):
        class NoStringError(Exception):
            def __str__(self):raise AssertionError('Exception text must not be read')
        scope=dict(error=NoStringError())
        exec(compile('def leaf():\n raise error\n',str(SCRIPT.with_name('capture_readiness.py')),'exec'),scope)
        exec(compile('def caller():\n leaf()\n',str(SCRIPT.with_name('scenario_editor_shortcuts.py')),'exec'),scope)
        try:scope['caller']()
        except NoStringError as exc:frames=self.n.capture_failure_frames(exc)
        self.assertEqual(frames,[[13,2],[24,2]])

    def test_shared_hook_retains_actual_ascii_leaf_frames_before_existing_formatter(self):
        import sys
        sys.path.insert(0,str(SCRIPT.parent))
        smoke=importlib.import_module('windows_smoke')
        record={};owner=self
        class ExistingFormatterFailure(Exception):
            def __str__(self):
                owner.assertEqual(record['numericFailureFrames'],[[13,2],[25,2]])
                raise RuntimeError('Synthetic existing formatter failure')
        scope=dict(error=ExistingFormatterFailure())
        exec(compile('def leaf():\n raise error\n',str(SCRIPT.with_name('ascii_editor_input.py')),'exec'),scope)
        exec(compile('def caller():\n leaf()\n',str(SCRIPT.with_name('scenario_editor_shortcuts.py')),'exec'),scope)
        try:scope['caller']()
        except ExistingFormatterFailure as exc:
            with patch.dict(os.environ,self.env,clear=True),self.assertRaisesRegex(RuntimeError,'existing formatter'):
                smoke.capture_failure(Path('/unused'),'writer',record,exc)
        self.assertEqual(record['numericFailure']['fileCode'],25)

    def test_invalid_new_source_fields_fall_back_to_the_original_v1_projection(self):
        record=dict(numericFailure=self.failure(),numericFailureFrames=[dict(path='PRIVATE')],
            imeCompositionOrdinal=True,imeCompositionStartEventCount=1.5)
        self.emitter.emit_case_notice('ime-writer',record)
        value=self.decode(self.messages()[0])
        self.assertEqual(value['schemaVersion'],1)
        self.assertEqual(len(value['observations']),49)
        self.assertNotIn('PRIVATE',self.messages()[0])

    def test_v2_receiver_rejects_frame_types_ranges_extra_fields_and_mixed_versions(self):
        self.emitter.emit_case_notice('ime-calc',dict(numericFailure=self.failure(),
            numericFailureFrames=[[24,80]],imeCompositionOrdinal=1,imeCompositionStartEventCount=4))
        base=json.loads(self.messages()[0])
        self.assertEqual(base['schemaVersion'],2)
        changes=[{'schemaVersion':1},{'ownedFrames':[[24,1]]*9},{'ownedFrames':[[True,1]]},
            {'ownedFrames':[[24,True]]},{'ownedFrames':[[0,0]]},{'ownedFrames':[[max(self.n.SOURCE_FILES.values())+1,1]]},
            {'ownedFrames':[[24,0]]},{'ownedFrames':[[24,10000001]]},{'ownedFrames':[dict(path='PRIVATE')]}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError):self.decode(json.dumps(base|change))
        for key,wrong in (('imeCompositionOrdinal',True),('imeCompositionOrdinal',0),
                          ('imeCompositionOrdinal',9),('imeCompositionStartEventCount','PRIVATE')):
            value=copy.deepcopy(base);value['observations'][key]=wrong
            with self.subTest(key=key,wrong=wrong),self.assertRaises(ValueError):self.decode(json.dumps(value))
        value=copy.deepcopy(base);value['fieldPresenceMask'] &= ~(1<<self.n.OBSERVATION_NAMES_V2.index('imeCompositionOrdinal'))
        with self.assertRaises(ValueError):self.decode(json.dumps(value))

    def test_maximum_legal_v2_case_fits_the_existing_two_kibibyte_limit(self):
        env=self.env|{'GITHUB_RUN_ID':str(2**63-1),'OPENGEUL_SUITE_NOTICE_SCOPE':'10'}
        value=self.n.project_case_notice('native-integrity',dict(numericFailure=self.failure(),
            numericFailureFrames=[[24,10000000]]*8,imeCompositionOrdinal=8,
            imeCompositionStartEventCount=0xffffffff),environ=env)
        self.assertEqual(value['schemaVersion'],2)
        value.update(fileCode=24,line=10000000,exceptionCode=12,stageCode=max(self.n.STAGES.values()))
        for key,kind,_ in self.n._FIELDS:
            value['observations'][key]=1 if kind in ('bool','flag') else (2**64-1 if kind=='u64' else 0xffffffff)
        value['fieldPresenceMask']=(1<<51)-1
        stream=io.StringIO();emitter=self.n.NoticeEmitter(environ=env,stream=stream)
        self.assertTrue(emitter._emit(self.n.CASE_TITLE,value,value['caseCode']))
        message=stream.getvalue().strip().split('::',2)[2]
        self.assertLessEqual(len(message.encode()),2048)
        self.n.decode_notice(message,'a'*40,2**63-1,expected_scope=10)

    def frozen_case_wire(self,version):
        # Freeze the original wire names rather than deriving a compatibility
        # fixture from whichever schema the implementation currently exports.
        names=('shellPid,enginePid,officeCreationTime,shellCreationTime,shellExitCode,officeExitCode,'
            'cleanupShellExitCode,cleanClose,forcedCleanup,forcedCleanupRequired,originalFixtureUnchanged,'
            'originalCloseVerified,diskOutcomeVerified,packagedUnoVerified,promptVerified,officeExitedAfterCleanup,'
            'engineHandleReleased,forceRequested,closeShortcutCount,choiceClickCount,saveAttempted,saveReturned,'
            'savedMarkerObserved,dispatchEntered,dispatchReturned,dispatchOpen,dispatchComplete,processExitProved,'
            'controllerResourcesReleased,withinDeadline,expectedCaseCount,completedCaseCount,passedCaseCount,'
            'failedCaseCount,missingCaseCount,duplicateCaseCount,unexpectedCaseCount,baselineFixturesUnchanged,'
            'packagedUnoExitCode,cleanupErrorCount,diagnosticRunnerPassed,shellExitObserved,shellHandleReleased,'
            'shellDisposalError,shellCleanupExitCode,retirementClosed,localCleanupErrorCount,'
            'keyboardCleanupErrorCount,retirementCleanupErrorCount').split(',')
        value=dict(schemaVersion=version,kind=1,sourceCommit='a'*40,runId=123,runAttempt=1,
            architecture=0xaa64,scopeCode=1,sequence=1,remainingBudget=7,moduleCode=1,caseCode=2,
            stageCode=0,exceptionCode=1,fileCode=0,line=0,fieldPresenceMask=0,
            observations=dict.fromkeys(names,0))
        if version>=2:
            value['ownedFrames']=[[13,262]]
            value['observations'].update(imeCompositionOrdinal=0,imeCompositionStartEventCount=0)
        if version==3:
            value['startup']=[0,0,0]
            value['observations'].update(imeModeSamples=4,imeModeClosed=1,imeModeAlpha=1,imeLastOpen=1,imeLastNative=1)
            value['fieldPresenceMask']=31<<51
        return value

    def test_frozen_v1_and_v2_wire_fixtures_still_decode_exactly(self):
        for version in (1,2):
            value=self.frozen_case_wire(version)
            with self.subTest(version=version):self.assertEqual(self.decode(json.dumps(value)),value)
        self.assertEqual(tuple(self.frozen_case_wire(1)['observations']),self.n.OBSERVATION_NAMES)
        self.assertEqual(tuple(self.frozen_case_wire(2)['observations']),self.n.OBSERVATION_NAMES_V2)

    def test_v3_closed_wire_requires_all_five_sample_fields_and_preserves_older_keys(self):
        value=self.frozen_case_wire(3)
        self.assertEqual(self.decode(json.dumps(value)),value)
        self.assertEqual(tuple(value['observations']),self.n.OBSERVATION_NAMES_V3)
        message=json.dumps(value)
        for malformed in ('{"schemaVersion":3,'+message[1:],message+' '*2049):
            with self.assertRaises(ValueError):self.decode(malformed)
        for change in ('partial','zero','overlap','bool','oversize','last','private','old-version'):
            invalid=copy.deepcopy(value)
            if change=='partial':invalid['fieldPresenceMask'] &= ~(1<<54)
            elif change=='zero':invalid['observations']['imeModeSamples']=0
            elif change=='overlap':invalid['observations'].update(imeModeClosed=4,imeModeAlpha=1)
            elif change=='bool':invalid['observations']['imeModeSamples']=True
            elif change=='oversize':invalid['observations']['imeModeSamples']=129
            elif change=='last':invalid['observations']['imeLastOpen']=2
            elif change=='private':invalid['observations']['modeText']='PRIVATE'
            else:invalid['schemaVersion']=2
            with self.subTest(change=change),self.assertRaises(ValueError):self.decode(json.dumps(invalid))

    def admitted_mode_record(self):
        import sys
        sys.path.insert(0,str(SCRIPT.parent))
        sys.path.insert(0,str(SCRIPT.parents[1]/'tests'))
        from suite.tests.test_ime_mode_summary import admitted_record
        value=admitted_record()
        value.update(numericFailure=self.failure(),numericFailureFrames=[[4,1840]],success=False,
            imeCompositionOrdinal=3,imeCompositionStartEventCount=8,architecture='arm64')
        value['readiness']['nativeMachine']=0xaa64
        value['readiness']['source'].update(sourceRun='123',architecture='arm64')
        return value

    def test_v3_producer_uses_real_admitted_sample_projection_without_exporting_raw_fields(self):
        record=self.admitted_mode_record()
        import ime_mode_summary
        expected=ime_mode_summary.project(record)
        self.assertEqual(expected,dict(imeModeSamples=4,imeModeClosed=1,imeModeAlpha=1,imeLastOpen=1,imeLastNative=1))
        record.update(imeModeSummary=dict(imeModeSamples=128),private=dict(text='PRIVATE',wmChar='PRIVATE'))
        self.assertTrue(self.emitter.emit_case_notice(record['case'],record))
        value=self.decode(self.messages()[0])
        self.assertEqual(value['schemaVersion'],3)
        self.assertEqual({key:value['observations'][key] for key in expected},expected)
        self.assertEqual(value['fieldPresenceMask'] & (31<<51),31<<51)
        self.assertNotIn('PRIVATE',self.messages()[0])

    def test_unadmitted_or_injected_mode_claims_preserve_exact_v2_unknown_projection(self):
        record=dict(numericFailure=self.failure(),numericFailureFrames=[[4,1840]],
            imeModeSummary=dict(imeModeSamples=128,imeModeClosed=0,imeModeAlpha=0,imeLastOpen=1,imeLastNative=1))
        self.emitter.emit_case_notice('ime-writer',record)
        value=self.decode(self.messages()[0])
        self.assertEqual(value['schemaVersion'],2)
        self.assertEqual(len(value['observations']),51)
        for change in ('ack','generation','source-commit','source-run','source-architecture'):
            record=self.admitted_mode_record()
            if change=='ack':next(row for row in record['imeCommands'] if row['command']==3)['acknowledged']=False
            elif change=='generation':record['imeKeyboardSession']['expectedNative']['officeCreationTime']+=1
            elif change=='source-commit':record['readiness']['source']['sourceCommit']='b'*40
            elif change=='source-run':record['readiness']['source']['sourceRun']='124'
            else:
                record['architecture']='x64';record['readiness']['nativeMachine']=0x8664
                record['readiness']['source']['architecture']='x64'
            value=self.n.project_case_notice(record['case'],record,environ=self.env)
            with self.subTest(change=change):
                self.assertEqual(value['schemaVersion'],2)
                self.assertEqual(len(value['observations']),51)

    def test_maximum_legal_v3_wire_fits_existing_two_kibibytes(self):
        value=self.frozen_case_wire(3)
        value.update(runId=2**63-1,scopeCode=10,moduleCode=0,caseCode=58,stageCode=93,
            exceptionCode=12,fileCode=25,line=10000000,ownedFrames=[[25,10000000]]*8,
            fieldPresenceMask=(1<<56)-1)
        for key,kind,_ in self.n._FIELDS:
            value['observations'][key]=1 if kind in ('bool','flag') else (2**64-1 if kind=='u64' else 0xffffffff)
        value['observations'].update(imeCompositionOrdinal=8,imeCompositionStartEventCount=0xffffffff,
            imeModeSamples=128,imeModeClosed=100,imeModeAlpha=28,imeLastOpen=1,imeLastNative=0)
        value['startup']=[3,38,740]
        message=json.dumps(value,separators=(',',':'))
        self.assertLessEqual(len(message.encode()),2048)
        self.n.decode_notice(message,'a'*40,2**63-1,expected_scope=10)

    def startup_record(self):
        import test_startup_diagnostics as startup_tests
        exc=startup_tests.observed_exception(self.env)
        with patch.dict(os.environ,self.env,clear=True):
            code=self.n.capture_failure_code(exc)
        return dict(shellPid=77,numericFailure=code),exc

    def test_actual_startup_receipt_selects_v3_with_mode_fields_unknown(self):
        record,exc=self.startup_record()
        record['_imeModeSummary']=dict(imeModeSamples=128,imeModeClosed=100,imeModeAlpha=28,
            imeLastOpen=1,imeLastNative=0)
        self.assertTrue(self.emitter.emit_case_notice('ime-calc',record))
        value=self.decode(self.messages()[0])
        self.assertEqual(value['schemaVersion'],3)
        self.assertEqual(value['startup'],[2,14,126])
        self.assertEqual(value['fieldPresenceMask'] & (31<<51),0)
        self.assertEqual([value['observations'][key] for key in self.n._MODE_NAMES],[0]*5)
        self.assertEqual(value['ownedFrames'],[])
        self.assertNotIn('PRIVATE',self.messages()[0])
        self.assertNotIn('C:/',self.messages()[0])
        self.assertEqual(str(exc),'SYNTHETIC PRIVATE startup C:/private/profile')

    def test_v3_startup_closed_tuple_rejects_partial_unknown_bool_and_private_fields(self):
        value=self.frozen_case_wire(3)
        value['startup']=[0,0,0]
        self.decode(json.dumps(value))
        for startup in ([0,14,126],[4,14,126],[2,28,126],[2,14,1],[2,True,126],
                [2,14,'private'],[2,14,126,0],dict(phase=2,reason=14,native=126)):
            with self.subTest(startup=startup):
                changed=copy.deepcopy(value);changed['startup']=startup
                with self.assertRaises(ValueError):self.decode(json.dumps(changed))
        for version in (1,2):
            old=self.frozen_case_wire(version);old['startup']=[2,14,126]
            with self.assertRaises(ValueError):self.decode(json.dumps(old))
        for key in self.n._MODE_NAMES:value['observations'][key]=0
        value['fieldPresenceMask'] &= ~(31<<51)
        with self.assertRaises(ValueError):self.decode(json.dumps(value))
        value['startup']=[2,0,0]
        self.assertEqual(self.decode(json.dumps(value))['startup'],[2,0,0])

    def test_injected_cloned_foreign_or_stale_startup_claims_stay_unknown(self):
        record,exc=self.startup_record()
        record['startup']=[3,38,740]
        for change in ('raw-only','cloned-failure','wrong-pid','source-context','stale-exception'):
            changed=dict(record);env=dict(self.env)
            if change=='raw-only':changed['numericFailure']=self.failure()
            elif change=='cloned-failure':changed['numericFailure']=dict(record['numericFailure'])
            elif change=='wrong-pid':changed['shellPid']=78
            elif change=='source-context':env['GITHUB_RUN_ID']='124'
            else:
                env['GITHUB_RUN_ID']='124'
                with patch.dict(os.environ,env,clear=True):changed['numericFailure']=self.n.capture_failure_code(exc)
            value=self.n.project_case_notice('ime-calc',changed,environ=env)
            with self.subTest(change=change):
                self.assertEqual(value['schemaVersion'],1)
                self.assertNotIn('startup',value)

    def test_startup_association_is_bounded_and_returned_tuple_cannot_mutate_evidence(self):
        record,exc=self.startup_record()
        projected=self.n.captured_startup(record,environ=self.env)
        projected[1]=38
        self.assertEqual(self.n.captured_startup(record,environ=self.env),[2,14,126])
        for _ in range(32):last,_=self.startup_record()
        self.assertEqual(len(self.n._STARTUP_FAILURES),32)
        self.assertEqual(self.n.captured_startup(record,environ=self.env),[0,0,0])
        self.assertEqual(self.n.captured_startup(last,environ=self.env),[2,14,126])

    def test_shared_capture_retains_actual_startup_and_calc_snapshot_carries_it(self):
        import windows_smoke as smoke
        import numeric_notice as shared
        import test_startup_diagnostics as startup_tests
        exc=startup_tests.observed_exception(self.env)
        record=dict(shellPid=77)
        with tempfile.TemporaryDirectory() as output, patch.dict(os.environ,self.env,clear=True), \
                patch.dict(sys.modules,{'PIL':SimpleNamespace(ImageGrab=SimpleNamespace(grab=lambda:(_ for _ in ()).throw(OSError('no screen'))))}):
            smoke.capture_failure(Path(output),'ime-calc',record,exc)
        value=shared.project_case_notice('ime-calc',record,environ=self.env)
        self.assertEqual(value['startup'],[2,14,126])
        self.assertEqual(record['numericStartupDiagnostic'],[2,14,126])
        self.assertIn('PRIVATE',record['error'])  # Existing primary persistence is unchanged.
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        self.env[self.n.TRACE_OPT_IN]='1'
        record,exc=self.startup_record()
        record['kind']='calc-save-dispatch-diagnostic'
        record['module']='calc'
        snapshot=self.n.capture_calc_snapshot(record,environ=self.env)
        report=self.trace_report();report['numericCaseSnapshot']=snapshot
        self.assertEqual(self.emitter.emit_calc_report(report),2)
        case=self.decode(self.messages()[0])
        self.assertEqual(case['startup'],[2,14,126])
        trace=self.decode(self.messages()[1],title=self.n.TRACE_TITLE)
        self.assertEqual(trace['schemaVersion'],1)
        self.assertNotIn('startup',trace)

    def focus_record(self):
        from suite.tests.test_focus_summary import admitted_record
        value=admitted_record()
        value.update(numericFailure=self.failure(),numericFailureFrames=[[21,816],[11,445],[1,389]],success=False)
        return value

    def test_v4_preserves_atomic_existing_guard_relations_and_progress_without_private_fields(self):
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        record=self.focus_record();context=record['imeSemanticContext']
        context.update(readerStartAttempted=True,observations=[dict(text='PRIVATE')],cleanup=dict(error='PRIVATE'))
        record['imeKeyboardSession']['lastGuardObservation']['scope']['after']['foreground']=dict(
            hwnd=123,isWindow=True,pid=999,threadId=99,rootHwnd=123,className='PRIVATE')
        with patch('os.stat',side_effect=AssertionError('No filesystem observation')), \
             patch('subprocess.run',side_effect=AssertionError('No process observation')), \
             patch('time.monotonic',side_effect=AssertionError('No renewed budget')):
            self.assertTrue(self.emitter.emit_case_notice('ime-calc',record))
            value=self.decode(self.messages()[0])
        self.assertEqual(value['schemaVersion'],4)
        self.assertEqual(value['focus'],[2,5,2,1,1])
        self.assertEqual(value['ownedFrames'],[[21,816],[11,445],[1,389]])
        self.assertEqual(tuple(value['observations']),self.n.OBSERVATION_NAMES_V2)
        self.assertNotIn('startup',value)
        self.assertNotIn('PRIVATE',self.messages()[0])
        self.assertNotIn('C:/',self.messages()[0])

    def test_unbound_focus_source_or_capture_preserves_exact_prior_v2_unknown(self):
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        for damage in ('source','run','arch','scope','missing','context','injected'):
            record=self.focus_record();env=dict(self.env)
            if damage=='source':record['readiness']['source']['sourceCommit']='b'*40
            elif damage=='run':record['readiness']['source']['sourceRun']='124'
            elif damage=='arch':record['readiness']['source']['architecture']='x64'
            elif damage=='scope':env['OPENGEUL_SUITE_NOTICE_SCOPE']='6'
            elif damage=='missing':record['imeKeyboardSession'].pop('lastGuardObservation')
            elif damage=='context':record['imeSemanticContext']['expectedNative']['officeCreationTime']+=1
            else:
                record['imeKeyboardSession'].pop('lastGuardObservation')
                record['focus']=[5,5,2,120,1]
            value=self.n.project_case_notice('ime-calc',record,environ=env)
            with self.subTest(damage=damage):
                self.assertEqual(value['schemaVersion'],2)
                self.assertEqual(tuple(value['observations']),self.n.OBSERVATION_NAMES_V2)
                self.assertNotIn('focus',value)

    def test_v4_receiver_is_closed_and_rejects_unknown_mixed_or_out_of_range_vectors(self):
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        self.emitter.emit_case_notice('ime-calc',self.focus_record())
        value=json.loads(self.messages()[0]);self.assertEqual(value['schemaVersion'],4)
        invalids=([2,2,0,0], [2,2,0,0,0,0], [6,2,0,0,0], [True,2,0,0,0],
                  [2,2,3,0,0], [2,2,0,121,0], [2,2,0,0,2], [2,2,0,-1,0],
                  [2,2,0,'PRIVATE',0],dict(before=2,after=2))
        for focus in invalids:
            with self.subTest(focus=focus),self.assertRaises(ValueError):self.decode(json.dumps(value|dict(focus=focus)))
        for change in (dict(schemaVersion=3),dict(startup=[0,0,0]),dict(scopeCode=10),
                       dict(stageCode=self.n.STAGES['physical-dubeolsik-composition'])):
            with self.subTest(change=change),self.assertRaises(ValueError):self.decode(json.dumps(value|change))
        changed=copy.deepcopy(value);changed['observations']['imeModeSamples']=1
        with self.assertRaises(ValueError):self.decode(json.dumps(changed))
        for version in (1,2,3):
            old=self.frozen_case_wire(version);old['focus']=[2,2,0,0,0]
            with self.subTest(version=version),self.assertRaises(ValueError):self.decode(json.dumps(old))

    def test_maximum_legal_v4_wire_fits_existing_two_kibibytes(self):
        value=self.frozen_case_wire(2)
        value.update(schemaVersion=4,runId=2**63-1,scopeCode=9,moduleCode=2,caseCode=18,
            stageCode=self.n.STAGES['verify-post-prefix-editing-context'],exceptionCode=12,
            fileCode=25,line=10000000,ownedFrames=[[25,10000000]]*8,
            fieldPresenceMask=(1<<51)-1,focus=[5,5,2,120,1])
        for key,kind,_ in self.n._FIELDS:
            value['observations'][key]=1 if kind in ('bool','flag') else (2**64-1 if kind=='u64' else 0xffffffff)
        value['observations'].update(imeCompositionOrdinal=8,imeCompositionStartEventCount=0xffffffff)
        message=json.dumps(value,separators=(',',':'))
        self.assertLessEqual(len(message.encode()),2048)
        self.n.decode_notice(message,'a'*40,2**63-1,expected_scope=9)

    def test_calc_snapshot_and_final_notice_preserve_v4_focus_after_original_cleanup(self):
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9';self.env[self.n.TRACE_OPT_IN]='1'
        record=self.focus_record();record['imeKeyboardSession'].update(engineHandleReleased=True,cleanupErrors=[])
        record['calcDispatchLocalCleanup']=dict(errors=[],withinDeadline=True)
        snapshot=self.n.capture_calc_snapshot(record,environ=self.env)
        self.assertEqual(snapshot['schemaVersion'],4)
        report=self.trace_report();report['numericCaseSnapshot']=snapshot
        self.assertEqual(self.emitter.emit_calc_report(report),2)
        value=self.decode(self.messages()[0]);trace=self.decode(self.messages()[1],title=self.n.TRACE_TITLE)
        self.assertEqual(value['focus'],[2,2,0,0,0])
        self.assertEqual(value['observations']['engineHandleReleased'],1)
        self.assertEqual(trace['schemaVersion'],1)
        self.assertNotIn('focus',trace)

    def test_actual_calc_keyboard_and_semantic_guard_survive_close_and_final_numeric_roundtrip(self):
        import test_ime_keyboard_session as keyboard_tests
        import ime_semantic_context as semantic
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9';self.env[self.n.TRACE_OPT_IN]='1'
        fixtures=keyboard_tests.IMEKeyboardSessionTests()
        with tempfile.TemporaryDirectory() as directory:
            session,process,binding,api,clock,probe,record=fixtures.fixture(directory,module='calc')
            try:
                session.start();session.focus_editor(6.);fixtures.ready(session);fixtures.navigate(session)
                record.update(case='ime-calc',kind='calc-save-dispatch-diagnostic',imePolicyVersion=4,
                    architecture='arm64',shellPid=process.pid,editorTid=session.tid,
                    stage='verify-pre-prefix-editing-context',imeSetupBudget=dict(startedAt=1.,deadline=10.),
                    readiness=self.focus_record()['readiness'])
                original_scope=probe.scope_snapshot
                def foreign_scope(*args):
                    value=original_scope(*args)
                    value['after']['foreground']=dict(hwnd=123,isWindow=True,pid=999,
                        threadId=99,rootHwnd=123,className='PRIVATE')
                    return value
                probe.scope_snapshot=foreign_scope
                with self.assertRaisesRegex(AssertionError,'owned Suite foreground') as failed:
                    semantic.observe_ime_semantic_setup(process.opengeul_suite_root,
                        Path(directory)/'synthetic.xlsx',b'synthetic never-read fixture',record,10.,
                        original_shell=dict(session.shell),expected_native=dict(session.binding),
                        require_current=lambda:session.require_context_target('imeSemanticContext'),clock=clock)
                primary=failed.exception
                record['numericFailure']=self.n.capture_failure_code(primary)
                # The real session/semantic producers, not a separately shaped
                # fixture, provide all binding, guard, history and progress data.
                self.assertEqual(self.n.capture_calc_snapshot(record,environ=self.env)['focus'],[2,5,0,0,0])
                last_guard=record['imeKeyboardSession']['lastGuardObservation']
                session.close(primary)
                self.assertIs(record['imeKeyboardSession']['lastGuardObservation'],last_guard)
                self.assertEqual(record['imeKeyboardSession']['expectedNative'],session.binding)
                snapshot=self.n.capture_calc_snapshot(record,environ=self.env)
                self.assertEqual(snapshot['focus'],[2,5,0,0,0])
                report=self.trace_report();report['numericCaseSnapshot']=snapshot
                self.assertEqual(self.emitter.emit_calc_report(report),2)
                self.assertEqual(self.decode(self.messages()[0])['focus'],[2,5,0,0,0])
                self.assertEqual(self.decode(self.messages()[0])['observations']['engineHandleReleased'],1)
            finally:
                session.close(RuntimeError('Synthetic bounded test disposal'))
                fixtures.doCleanups()

    def test_actual_initial_calc_target_guard_keeps_unknown_reader_after_cleanup_and_numeric_roundtrip(self):
        import test_ime_keyboard_session as keyboard_tests
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9';self.env[self.n.TRACE_OPT_IN]='1'
        for navigation in (False,True):
            self.stream=io.StringIO()
            self.emitter=self.n.NoticeEmitter(environ=self.env,stream=self.stream)
            fixtures=keyboard_tests.IMEKeyboardSessionTests()
            with tempfile.TemporaryDirectory() as directory:
                session,process,binding,api,clock,probe,record=fixtures.fixture(directory,module='calc')
                try:
                    session.start();session.focus_editor(6.);fixtures.ready(session)
                    record.update(case='ime-calc',kind='calc-save-dispatch-diagnostic',imePolicyVersion=4,
                        architecture='arm64',shellPid=process.pid,stage='focus-editor',
                        imeSetupBudget=dict(startedAt=1.,deadline=10.),readiness=self.focus_record()['readiness'])
                    self.assertNotIn('editorTid',record)
                    original_scope=probe.scope_snapshot
                    def foreign_scope(*args):
                        value=original_scope(*args)
                        value['after']['foreground']=dict(hwnd=123,isWindow=True,pid=999,
                            threadId=99,rootHwnd=123,className='PRIVATE')
                        return value
                    probe.scope_snapshot=foreign_scope
                    try:
                        if navigation:fixtures.navigate(session)
                        else:session.require_calc_navigation_initial_target()
                        self.fail('Foreign foreground was admitted')
                    except AssertionError as exc:
                        primary=exc
                        record['numericFailure']=self.n.capture_failure_code(exc)
                        record['numericFailureFrames']=self.n.capture_failure_frames(exc)
                    self.assertEqual('calcNavigationContext' in record,navigation)
                    self.assertNotIn('imeSemanticContext',record)
                    before=self.n.capture_calc_snapshot(record,environ=self.env)
                    self.assertEqual(before['focus'],[2,5,0,121,0])
                    last_guard=record['imeKeyboardSession']['lastGuardObservation']
                    session.close(primary)
                    self.assertIs(record['imeKeyboardSession']['lastGuardObservation'],last_guard)
                    snapshot=self.n.capture_calc_snapshot(record,environ=self.env)
                    self.assertEqual(snapshot['focus'],[2,5,0,121,0])
                    report=self.trace_report();report['numericCaseSnapshot']=snapshot
                    self.assertEqual(self.emitter.emit_calc_report(report),2)
                    self.assertEqual(self.decode(self.messages()[0])['focus'],[2,5,0,121,0])
                    self.assertEqual(self.decode(self.messages()[0])['observations']['engineHandleReleased'],1)
                    self.assertEqual(self.decode(self.messages()[1],title=self.n.TRACE_TITLE)['schemaVersion'],1)
                finally:
                    session.close(RuntimeError('Synthetic bounded test disposal'))
                    fixtures.doCleanups()

    def test_setup_reader_sentinel_cannot_be_changed_to_a_known_empty_semantic_observation(self):
        from suite.tests.test_focus_summary import initial_record
        self.env['OPENGEUL_SUITE_NOTICE_SCOPE']='9'
        record=initial_record()
        self.assertTrue(self.emitter.emit_case_notice('ime-calc',record))
        value=self.decode(self.messages()[0]);self.assertEqual(value['focus'],[2,2,0,121,0])
        for focus in ([2,2,0,0,0],[2,2,0,120,0],[2,2,1,121,0],[2,2,0,121,1],[2,2,0,122,0]):
            with self.subTest(focus=focus),self.assertRaises(ValueError):self.decode(json.dumps(value|dict(focus=focus)))
        value['stageCode']=self.n.STAGES['verify-pre-prefix-editing-context']
        with self.assertRaises(ValueError):self.decode(json.dumps(value))


if __name__ == '__main__':
    unittest.main()
