"""Numeric projection must not inspect private input or extend callback evidence."""
import copy
import ctypes
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'e2e/ime_compartment_report.py'
SHA = '1' * 40
CONTEXT = dict(sourceCommit=SHA, runId=40743213587, runAttempt=1, architecture=0xaa64)


def environment():
    return dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='ATLKR/OpenGeul',
        GITHUB_JOB='windows-suite', GITHUB_EVENT_NAME='push', GITHUB_RUN_ATTEMPT='1',
        GITHUB_REF='refs/heads/work/opengeul-office-arm64', GITHUB_ACTOR='ATLKR',
        GITHUB_ACTOR_ID='65988341', GITHUB_SHA=SHA, GITHUB_WORKFLOW_SHA=SHA,
        GITHUB_RUN_ID=str(CONTEXT['runId']), RUNNER_ARCH='ARM64',
        OPENGEUL_SUITE_IME_COMPARTMENT_NOTICE='1')


class CompartmentReportTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'numeric compartment projection is missing')
        spec = importlib.util.spec_from_file_location('compartment_report_test', SCRIPT)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def fixture(self, *, claimed=True, cleanup=True):
        # Exercise the real ABI decoder, rather than a copy of its output schema.
        from test_ime_compartment_protocol import CompartmentProtocolTests
        protocol, config, row, kwargs = CompartmentProtocolTests().fixture()
        if not claimed:
            row.sequence = row.lease.claimed = 0
        if cleanup:
            row.lease.armed = row.lease.subscriptionPossible = 0
            for key in ('disabled', 'disconnectAttempts', 'unadviseAttempts', 'disconnected', 'released'):
                setattr(row.lease, key, 1)
            row.api.referencesReleased, row.api.sinkReferences = 5, 1
        caller = protocol.decode(config, row, **kwargs)
        native = dict(officePid=31, officeCreationTime=555, suiteHwnd=61)
        command = copy.deepcopy(kwargs['command3'])
        command['threadMode']['referencesAcquired'] = command['threadMode']['referencesReleased'] = 6
        command.update(nativeContext=dict(pid=31, tid=41, targetHwnd=51, rootHwnd=61),
            modeDeadlineCounter=90, modeCounterFrequency=10,
            requestedBudget=dict(counter=90, frequency=10))
        binding = dict(sourceCommit=SHA, runId=str(CONTEXT['runId']), runAttempt='1',
            architecture='arm64', repository='ATLKR/OpenGeul',
            ref='refs/heads/work/opengeul-office-arm64',
            workflowRef='ATLKR/OpenGeul/.github/workflows/office-suite.yml@refs/heads/work/opengeul-office-arm64',
            job='windows-suite', event='push')
        admission = dict(native=copy.deepcopy(native), editorTid=41, focusHwnd=51,
            runBinding=dict(sourceCommit=SHA, sourceRun=str(CONTEXT['runId']), runAttempt='1',
                architecture='arm64', repository='ATLKR/OpenGeul', job='windows-suite'),
            extraEngine=dict(pid=31, creationTime=555), originalShell=dict(pid=21, creationTime=444))
        case = dict(case='ime-writer', kind='native-ime-mode-diagnostic', success=False,
            stage='physical-dubeolsik-composition', editorTid=41, keyboardFocusHwnd=51,
            imeCompositionOrdinal=1, imeCompositionStartEventCount=0,
            numericFailure=dict(captured=1, exceptionCode=2, fileCode=4, line=123),
            numericFailureFrames=[[4, 123]], imeCommands=[command],
            imeCompartmentDiagnostics=caller,
            imeKeyboardSession=dict(expectedNative=native, engineHandleReleased=True),
            imeEngineRetirement=dict(admission=admission, success=False, close=dict(result=True)),
            imeFailureCleanup=dict(engineExitConfirmed=True, handleReleased=True,
                gracefulShutdownVerified=False, shellExitCode=1, commandExitCode=0,
                engineIdentity=dict(pid=31, creationTime=555),
                engineWait=dict(result=0)))
        report = dict(schemaVersion=1, kind='native-ime-mode-diagnostic', architecture='arm64',
            success=False, acceptanceEligible=False, imeVerified=False, tests=[case],
            runBinding=binding, expectedCaseCount=1, compartmentCallbackEnabled=True,
            notificationCallerEnabled=False,
            pluginFileOrigin=dict(verified=True, released=True, dllSha256='a' * 64,
                matchedIdentity=dict(guid='01234567-89ab-cdef-0123-456789abcdef', age=1)))
        selection = dict(status='selected', evidenceKind='ime-compartment-callback',
            rvas=[100], runtimeCallerProved=False, acceptanceEligible=False,
            pluginIdentity=dict(dllSha256='a' * 64,
                identity=copy.deepcopy(report['pluginFileOrigin']['matchedIdentity'])))
        worker = dict(schemaVersion=1, kind='owned-plugin-symbol-worker', mode='resolve',
            success=True, acceptanceEligible=False, runtimeCallerProved=False,
            temporaryFilesRemoved=True, resolution=dict(schemaVersion=1,
                kind='local-plugin-symbol-resolution', complete=True, cleanupComplete=True,
                acceptance=False, runtimeCallerProved=False, functionAliasUniquenessProved=False,
                nativeCallsPreemptible=False, dllSha256='a' * 64, pdbSha256='b' * 64,
                identity=copy.deepcopy(selection['pluginIdentity']['identity']),
                frames=[dict(returnRva=100, callRva=96, tag='frame-input-context',
                    functionRva=80, functionSize=32)]))
        return report, selection, worker

    def roundtrip(self, value):
        message = self.m.encode_notice(value)
        self.assertLessEqual(len(message.encode('utf-8')), 32768)
        return self.m.decode_notice(message, SHA, CONTEXT['runId'])

    def test_real_decoder_receipt_roundtrip_and_false_claims(self):
        report, selection, worker = self.fixture()
        value = self.m.project(report, selection, worker, context=CONTEXT)
        self.assertEqual(self.roundtrip(value), value)
        self.assertEqual((value['kind'], value['scopeCode'], value['sequence'], value['remainingBudget']), (4, 11, 1, 0))
        self.assertFalse(value['runtimeCallerProved'])
        self.assertFalse(value['acceptanceEligible'])
        self.assertEqual(value['callback']['frames'], [{'moduleId': 14, 'rva': 100}, {'moduleId': 0, 'rva': 0}])
        self.assertEqual(value['case']['compositionStartEventCount'], 0)
        self.assertEqual(value['resolution']['frames'][0]['tagCode'], 5)

    def test_writer_original_clock_is_not_replaced_with_calc_thirty_second_cap(self):
        report, selection, worker = self.fixture()
        report['tests'][0]['imeCompartmentDiagnostics']['deadlineCounter'] = 500
        # Writer's existing setup budget can exceed thirty seconds. Preserve
        # its own clock and selector ordering, without changing the budget.
        self.roundtrip(self.m.project(report, selection, worker, context=CONTEXT))

    def test_command_mode_keeps_original_clean_contract_and_signed_failures(self):
        report, selection, worker = self.fixture()
        mode = report['tests'][0]['imeCommands'][0]['threadMode']
        # Native command3 also acquires ITfClientId: six mode references. The
        # callback's separate five-reference lease must not be applied to it.
        mode['referencesAcquired'] = mode['referencesReleased'] = 6
        self.roundtrip(self.m.project(report, selection, worker, context=CONTEXT))
        report['tests'][0].pop('imeCompartmentDiagnostics')
        command = report['tests'][0]['imeCommands'][0]
        command.update(success=False, status=-20)
        mode.update(status=-20, cleanupStatus=-37, afterOpen=-1, afterConversion=-1,
                    referencesAcquired=1, referencesReleased=1)
        value = self.roundtrip(self.m.project(report, context=CONTEXT))
        self.assertEqual(value['command3']['mode']['cleanupStatus'], -37)
        self.assertEqual(value['command3']['mode']['afterConversion'], -1)

    def test_actual_preinstall_producer_and_unavailable_shapes_preserve_unknowns(self):
        import korean_ime_smoke as ime
        class ReadCompartment:
            def __call__(self, *args):
                return 2  # Native bounded copy before installAttempts publication.
        observer = ime.CompositionObserver.__new__(ime.CompositionObserver)
        observer.capture_ime_compartment = True
        observer.mapping = bytearray(ctypes.sizeof(ime.NativeState))
        observer.dll = SimpleNamespace(ReadCompartment=ReadCompartment())
        observer.commands = []
        raw = observer.compartment_diagnostics()
        self.assertEqual(raw, dict(status='inconclusive', acceptanceEligible=False,
            cleanupStatus='unproved', callerAttributionProved=False, processRetirementVerified=False))
        class Private:
            def __str__(self): raise AssertionError('private exception name was read')
            def __repr__(self): raise AssertionError('private exception name was read')
        partials = (raw, dict(status='unavailable', acceptanceEligible=False, errorType=Private()))
        for partial in partials:
            with self.subTest(status=partial['status']):
                report, _, _ = self.fixture()
                report['tests'][0]['imeCompartmentDiagnostics'] = partial
                value = self.roundtrip(self.m.project(report, context=CONTEXT))
                self.assertEqual(value['statusCode'], 0)
                for key in ('claimed', 'rejected', 'expired', 'foreignRejected', 'lease', 'api',
                            'identity', 'clock', 'frames', 'frameCount', 'unknownFrames', 'pluginStatus'):
                    self.assertIsNone(value['callback'][key])
                self.assertFalse(value['runtimeCallerProved'])
                self.assertFalse(value['acceptanceEligible'])
                malformed = dict(partial, frames=[dict(moduleId=14, rva=100)])
                report['tests'][0]['imeCompartmentDiagnostics'] = malformed
                with self.assertRaises(ValueError): self.m.project(report, context=CONTEXT)

    def test_selected_ack3_requires_all_six_native_mode_references(self):
        for count in (0, 1, 5):
            with self.subTest(count=count):
                report, selection, worker = self.fixture()
                mode = report['tests'][0]['imeCommands'][0]['threadMode']
                mode['referencesAcquired'] = mode['referencesReleased'] = count
                with self.assertRaises(ValueError):
                    self.m.project(report, selection, worker, context=CONTEXT)
                # A failed/unselected operation still retains its partial counts.
                value = self.roundtrip(self.m.project(report, context=CONTEXT))
                self.assertEqual(value['command3']['mode']['referencesAcquired'], count)
        value = self.m.project(*self.fixture(), context=CONTEXT)
        value['command3']['mode']['referencesAcquired'] = value['command3']['mode']['referencesReleased'] = 1
        with self.assertRaises(ValueError): self.m.encode_notice(value)

    def test_unobserved_and_untriggered_are_null_and_inconclusive(self):
        report, _, _ = self.fixture(claimed=False)
        value = self.roundtrip(self.m.project(report, None, None, context=CONTEXT))
        self.assertIsNone(value['callback']['identity'])
        self.assertIsNone(value['callback']['clock'])
        self.assertEqual(value['callback']['statusCode'], 2)
        self.assertIsNone(value['resolution'])
        report['tests'] = []
        value = self.roundtrip(self.m.project(report, context=CONTEXT))
        self.assertIsNone(value['case'])
        self.assertIsNone(value['callback'])
        self.assertIsNone(value['owner'])

    def test_cleanup_failure_and_negative_hresult_remain_numeric(self):
        report, _, _ = self.fixture(cleanup=False)
        raw = report['tests'][0]['imeCompartmentDiagnostics']
        raw['status'], raw['cleanupStatus'] = 'inconclusive', 'inconclusive'
        raw['api']['unadviseHr'] = -2147467259
        report['tests'][0]['imeFailureCleanup']['engineExitConfirmed'] = False
        value = self.roundtrip(self.m.project(report, context=CONTEXT))
        self.assertEqual(value['callback']['api']['unadviseHr'], -2147467259)
        self.assertFalse(value['retirement']['engineExitConfirmed'])
        self.assertEqual(value['statusCode'], 0)

    def test_private_values_are_never_read_or_stringified(self):
        class Poison:
            def __str__(self): raise AssertionError('private value was read')
            def __repr__(self): raise AssertionError('private value was read')
        report, selection, worker = self.fixture()
        case = report['tests'][0]
        for key in ('keyTokens', 'scanCodeInputs', 'text', 'error', 'traceback', 'wparam', 'lparam', 'activeProfile'):
            case[key] = Poison()
        case['imeCompartmentDiagnostics']['interpretation'] = Poison()
        case['imeKeyboardSession']['expectedNative']['expectedImage'] = Poison()
        case['imeFailureCleanup']['engineIdentity']['image'] = Poison()
        worker['resolution']['frames'][0]['symbol'] = Poison()
        value = self.m.project(report, selection, worker, context=CONTEXT)
        encoded = self.m.encode_notice(value)
        self.assertNotIn('guid', encoded)
        self.assertNotIn('symbol', encoded)
        self.assertNotIn('error', encoded.lower())
        self.assertEqual(self.roundtrip(value), value)

    def test_source_generation_clock_cleanup_and_selection_mutations_rejected(self):
        mutations = (
            lambda r,s,w:r['runBinding'].update(sourceCommit='2' * 40),
            lambda r,s,w:r['tests'][0]['imeCompartmentDiagnostics'].update(engineCreationTime=556),
            lambda r,s,w:r['tests'][0]['imeEngineRetirement']['admission']['native'].update(officePid=32),
            lambda r,s,w:r['tests'][0]['imeCompartmentDiagnostics'].update(counter=101),
            lambda r,s,w:r['tests'][0]['imeCommands'][0].update(modeCounterFrequency=11),
            lambda r,s,w:r['tests'][0]['imeCompartmentDiagnostics']['api'].update(referencesReleased=4),
            lambda r,s,w:r['tests'][0]['imeFailureCleanup'].update(handleReleased=False),
            lambda r,s,w:s.update(rvas=[104]),
            lambda r,s,w:w['resolution'].update(dllSha256='c' * 64),
            lambda r,s,w:w['resolution']['frames'][0].update(returnRva=104),
            lambda r,s,w:w.update(temporaryFilesRemoved=False),
        )
        for mutate in mutations:
            report, selection, worker = self.fixture()
            mutate(report, selection, worker)
            with self.subTest(mutation=mutations.index(mutate)), self.assertRaises(ValueError):
                self.m.project(report, selection, worker, context=CONTEXT)

    def test_closed_codec_rejects_extra_keys_bool_as_int_and_malformed_receipts(self):
        value = self.m.project(*self.fixture(), context=CONTEXT)
        mutations = (
            lambda v:v.update(private='leak'), lambda v:v.update(kind=True),
            lambda v:v.update(runtimeCallerProved=True), lambda v:v['case'].update(private='leak'),
            lambda v:v['callback']['api'].update(managerHr=2**31),
            lambda v:v['callback']['lease'].update(claimed=True),
            lambda v:v['callback']['clock'].update(counter=True),
            lambda v:v['callback']['identity'].update(creationTime=556),
            lambda v:v['callback']['frames'][1].update(rva=4),
            lambda v:v['callback']['frames'][0].update(rva=101),
            lambda v:v['resolution']['frames'][0].update(tagCode=99),
            lambda v:v['retirement'].update(handleReleased=False),
            lambda v:v['provenance'].update(pdbSha256='private'),
        )
        for mutate in mutations:
            changed = copy.deepcopy(value); mutate(changed)
            with self.subTest(mutation=mutations.index(mutate)), self.assertRaises(ValueError):
                self.m.encode_notice(changed)
        message = self.m.encode_notice(value)
        for kwargs in (dict(expected_source_commit='2' * 40), dict(expected_run_id=7),
                       dict(expected_run_attempt=2), dict(expected_architecture=0x8664)):
            args = dict(expected_source_commit=SHA, expected_run_id=CONTEXT['runId']); args.update(kwargs)
            with self.assertRaises(ValueError): self.m.decode_notice(message, **args)
        for message in (' ' * 32769, '{"kind":4,"kind":4}', 'NaN', '[]'):
            with self.assertRaises(ValueError): self.m.decode_notice(message, SHA, CONTEXT['runId'])

    def test_maximum_bounded_callback_and_frames(self):
        report, _, _ = self.fixture()
        callback = report['tests'][0]['imeCompartmentDiagnostics']
        callback.update(status='inconclusive', frameCount=16, frameCapReached=True,
            unknownFrames=15, frames=[dict(moduleId=14, rva=100)] + [dict(moduleId=0, rva=0)] * 15)
        report['tests'][0]['numericFailureFrames'] = [[4, 10_000_000]] * 8
        value = self.roundtrip(self.m.project(report, context=CONTEXT))
        self.assertEqual(len(value['callback']['frames']), 16)
        callback['frames'].append(dict(moduleId=0, rva=0))
        with self.assertRaises(ValueError): self.m.project(report, context=CONTEXT)

    def test_emit_requires_exact_context_and_opt_in_and_attempts_only_once(self):
        report, selection, worker = self.fixture()
        output = io.StringIO(); env = environment()
        self.assertTrue(self.m.emit(report, selection, worker, environ=env, stream=output))
        self.assertFalse(self.m.emit(report, selection, worker, environ=env, stream=output))
        line = output.getvalue().strip()
        prefix = '::notice title=OpenGeul IME compartment numeric v1::'
        self.assertTrue(line.startswith(prefix))
        self.m.decode_notice(line[len(prefix):], SHA, CONTEXT['runId'])
        for key, value in (('RUNNER_ARCH','X64'), ('GITHUB_RUN_ATTEMPT','2'),
                           ('GITHUB_EVENT_NAME','workflow_dispatch'), ('OPENGEUL_SUITE_IME_COMPARTMENT_NOTICE','true')):
            spec = importlib.util.spec_from_file_location('fresh_compartment', SCRIPT)
            fresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(fresh)
            changed = dict(env); changed[key] = value
            self.assertFalse(fresh.emit(report, selection, worker, environ=changed, stream=io.StringIO()))
        class Broken:
            def write(self, value): raise BrokenPipeError()
            def flush(self): pass
        spec = importlib.util.spec_from_file_location('broken_compartment', SCRIPT)
        fresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(fresh)
        self.assertFalse(fresh.emit(report, selection, worker, environ=env, stream=Broken()))
        self.assertFalse(fresh.emit(report, selection, worker, environ=env, stream=io.StringIO()))

    def test_cli_verifies_bounded_receipt_with_explicit_source(self):
        value = self.m.project(*self.fixture(), context=CONTEXT)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'callback-numeric.json'
            path.write_text(self.m.encode_notice(value), encoding='utf-8')
            command = [sys.executable, str(SCRIPT), '--verify', str(path), '--source-commit', SHA,
                       '--run-id', str(CONTEXT['runId']), '--run-attempt', '1', '--architecture', 'arm64']
            good = subprocess.run(command, capture_output=True, timeout=10)
            self.assertEqual(good.returncode, 0, good.stderr)
            path.write_text('{"secret":"private"}', encoding='utf-8')
            bad = subprocess.run(command, capture_output=True, timeout=10)
            self.assertEqual(bad.returncode, 1)
            self.assertNotIn(b'private', bad.stdout + bad.stderr)


if __name__ == '__main__': unittest.main()
