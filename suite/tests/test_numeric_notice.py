"""Future notices expose only closed observations from the current owned controller."""
import copy
from contextlib import redirect_stdout
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
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
                        {'OPENGEUL_SUITE_NOTICE_SCOPE': ''}, {'OPENGEUL_SUITE_NOTICE_SCOPE': '10'}):
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

    def test_only_nine_product_steps_opt_in_and_unit_steps_never_do(self):
        from suite.tests.test_calc_matrix_workflow import WORKFLOW, workflow_steps, field, run_code
        fragments = ('calc_close_probe.py --suite', 'home_routing_smoke.py --suite',
                     '--output .work/suite-korean-ime\n', 'korean_ui_smoke.py --suite',
                     'writer_style_smoke.py --suite', 'lifecycle_smoke.py --suite',
                     '--output .work/suite-native\n', '--output .work/suite-native-2\n',
                     '--diagnose-calc-dispatch --expected-engine-source-commit')
        expected = [next(step for step in workflow_steps() if field(step,'run')=='|' and fragment in run_code(step))
                    for fragment in fragments]
        actual = [step for step in workflow_steps() if "OPENGEUL_SUITE_NUMERIC_NOTICE: '1'" in step]
        self.assertEqual({step.splitlines()[0] for step in actual}, {step.splitlines()[0] for step in expected})
        for scope,step in enumerate(expected,1):
            self.assertIn("OPENGEUL_SUITE_NOTICE_SCOPE: '"+str(scope)+"'",step)
        traced = [step for step in workflow_steps() if 'OPENGEUL_SUITE_CALC_TRACE_NOTICE' in step]
        self.assertEqual(traced,[expected[-1]])
        self.assertIn("OPENGEUL_SUITE_CALC_TRACE_NOTICE: '1'",traced[0])
        self.assertNotIn('OPENGEUL_SUITE_NUMERIC_NOTICE', WORKFLOW.read_text().split('jobs:')[0])
        self.assertFalse(any('OPENGEUL_SUITE_NUMERIC_NOTICE' in step for step in workflow_steps() if 'unittest discover' in step))

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


if __name__ == '__main__':
    unittest.main()
