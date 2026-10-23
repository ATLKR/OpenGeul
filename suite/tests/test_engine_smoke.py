"""Portable boundary regressions for actual-Windows engine evidence."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'e2e' / 'engine_smoke.py'
SPEC = importlib.util.spec_from_file_location('suite_engine_smoke', SOURCE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def observations(module):
    if module == 'base':
        return {'databaseUrl': 'sdbc:embedded:firebird',
                'rows': [{'id': 1, 'text': smoke.marker('base'), 'amount': 42}]}
    if module == 'math':
        return {'formula': smoke.FORMULA}
    result = {'text': smoke.marker(module)}
    if module in smoke.UI_MODULES:
        result['text'] += ' UI-OpenGeul-' + module
    if module == 'calc':
        result.update(formula='=SUM(B1:C1)', value=42)
    if module in ('draw', 'impress'):
        result['pageCount'] = 1
    if module == 'draw':
        result.update(position=[1000, 1000], size=[6000, 2500])
    return result


def successful_cleanup(suite):
    member = dict(pid=42, creationTime=123, handleValue=99, image=str(suite / 'Office/program/soffice.bin'), alive=True, exitCode=259)
    return dict(schemaVersion=1, kind='owned-engine-job-cleanup', jobHandleValue=11,
                expectedEngineImage=member['image'], gracefulQualified=True, forcedTermination=False,
                jobEmptyVerified=True, initialMembers=[member], finalMembers=[dict(member, alive=False, exitCode=0)],
                finalJobPids=[], launcherExitCode=0, errors=[])


class EngineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.suite = self.root / 'suite'
        self.output = self.root / 'evidence'
        self.suite.mkdir()
        (self.output / 'fixtures').mkdir(parents=True)
        self.modules = {module: {'factory': factory, 'filters': {}}
                        for module, factory in smoke.FACTORIES.items()}
        (self.suite / 'suite-product.json').write_text(json.dumps(
            {'schemaVersion': 1, 'modules': self.modules}), encoding='utf-8')
        for name in smoke.FILES.values():
            (self.output / 'fixtures' / name).write_bytes(b'before close')

    def fake_engine(self, path, cleanup_error=False, delete=False):
        class Engine:
            cleanup_errors = []

            def __init__(self, suite):
                self.cleanup_errors = []
                self.cleanup_evidence = successful_cleanup(suite)

            def start(self):
                pass

            def acquire_fixture_lifetime(self):
                pass  # This fixture models only final-byte/cleanup boundaries.

            def _capture_members(self, phase):
                return self.cleanup_evidence['initialMembers']

            def load(self, url):
                return object()

            def close_document(self, document):
                path.write_bytes(b'after model close')

            def cleanup(self):
                if delete:
                    path.unlink()
                else:
                    path.write_bytes(b'final persisted bytes after process cleanup')
                if cleanup_error:
                    self.cleanup_errors.append('owned process remained alive')
        return Engine

    def test_hash_records_final_bytes_after_model_close_and_process_cleanup(self):
        path = self.output / 'fixtures' / smoke.FILES['base']
        with patch.object(smoke, 'Engine', self.fake_engine(path)), \
                patch.object(smoke, 'observe', return_value=observations('base')):
            result = smoke.run_case(self.suite, self.output, 'base', self.modules['base'], True)
        final = path.read_bytes()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['sha256'], hashlib.sha256(final).hexdigest())
        self.assertEqual(result['bytes'], len(final))
        self.assertEqual(result['observed']['rows'], observations('base')['rows'])
        self.assertNotIn('uiSuffix', result['expected'])
        self.assertIn('engineCleanup', result, 'New source qualification must retain the cleanup proof')

    def test_missing_cleanup_proof_never_hashes_a_new_successful_source_case(self):
        path = self.output / 'fixtures' / smoke.FILES['base']
        parent = self.fake_engine(path)
        class MissingProof(parent):
            def cleanup(self):
                super().cleanup()
                self.cleanup_evidence = None
        with patch.object(smoke, 'Engine', MissingProof), patch.object(smoke, 'observe', return_value=observations('base')):
            result = smoke.run_case(self.suite, self.output, 'base', self.modules['base'], True)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('sha256', result)
        self.assertIn('cleanup evidence', result['error']['message'])

    def test_final_hash_failure_is_structured_and_cannot_pass(self):
        path = self.output / 'fixtures' / smoke.FILES['base']
        with patch.object(smoke, 'Engine', self.fake_engine(path, delete=True)), \
                patch.object(smoke, 'observe', return_value=observations('base')):
            result = smoke.run_case(self.suite, self.output, 'base', self.modules['base'], True)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error']['type'], 'FileNotFoundError')
        self.assertNotIn('sha256', result)
        self.assertNotIn('bytes', result)

    def test_cleanup_failure_does_not_publish_a_success_hash(self):
        path = self.output / 'fixtures' / smoke.FILES['base']
        with patch.object(smoke, 'Engine', self.fake_engine(path, cleanup_error=True)), \
                patch.object(smoke, 'observe', return_value=observations('base')):
            result = smoke.run_case(self.suite, self.output, 'base', self.modules['base'], True)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('cleanupErrors', result)
        self.assertNotIn('sha256', result)

    def baseline(self, modules):
        (self.output / 'engine-smoke.json').write_text(json.dumps(
            {'cases': [{'module': module, 'status': 'passed'} for module in modules]}), encoding='utf-8')

    def test_post_gui_reopens_all_six_modules_and_keeps_their_semantic_checks(self):
        self.baseline(smoke.FILES)
        seen = []

        def run_case(suite, output, module, specification, verify_ui):
            seen.append(module)
            self.assertTrue(verify_ui)
            smoke.verify_content(module, observations(module), verify_ui)
            return {'module': module, 'status': 'passed'}

        with patch.object(smoke, 'run_case', side_effect=run_case), redirect_stdout(io.StringIO()):
            code = smoke.main(['--suite', str(self.suite), '--output', str(self.output), '--verify-ui'])
        self.assertEqual(code, 0)
        self.assertEqual(seen, list(smoke.FILES))
        report = json.loads((self.output / 'ui-engine-verification.json').read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['cases']), 6)

    def test_post_gui_rejects_three_module_baseline_before_reopening_anything(self):
        self.baseline(smoke.UI_MODULES)
        with patch.object(smoke, 'run_case') as run, redirect_stderr(io.StringIO()):
            code = smoke.main(['--suite', str(self.suite), '--output', str(self.output), '--verify-ui'])
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_ui_suffix_required_only_for_modules_with_keyboard_edit_cases(self):
        for module in smoke.FILES:
            with self.subTest(module=module):
                value = observations(module)
                smoke.verify_content(module, value, True)
                if module in smoke.UI_MODULES:
                    value['text'] = smoke.marker(module)
                    with self.assertRaisesRegex(AssertionError, 'GUI edit'):
                        smoke.verify_content(module, value, True)

    def test_post_gui_keeps_draw_geometry_math_formula_and_base_sql_guards(self):
        for module, key, wrong in [('draw', 'size', [1, 1]), ('math', 'formula', 'x'),
                                   ('base', 'rows', []), ('base', 'databaseUrl', 'jdbc:')]:
            with self.subTest(module=module, key=key):
                value = observations(module)
                value[key] = wrong
                with self.assertRaises(AssertionError):
                    smoke.verify_content(module, value, True)


class OwnedJobCleanupTests(unittest.TestCase):
    def scenario(self, *, graceful=False, terminate_fails=False, census_fails=False, profile_fails=False, exit_code=0):
        events = []
        suite = Path('/generated-suite')

        class Api:
            alive = True

            def job_pids(self, job, **kwargs):
                events.append('census-while-job-open')
                self_test.assertFalse(process.closed, 'Private job closed before final census')
                if census_fails:
                    error = OSError('private job census failed')
                    error.job_census = dict(classification='failed', calls=[dict(result=False, lastError=5)])
                    raise error
                return [42] if self.alive else []

            def state(self, handle):
                return dict(alive=self.alive, exitCode=259 if self.alive else exit_code)

            def wait_for(self, handle, milliseconds):
                events.append('wait-retained-member')
                if graceful:
                    self.alive = False
                return 258 if self.alive else 0

        self_test, api = self, Api()

        class Witness:
            def __init__(self):
                self.api = api
                self.members = {42: (99, dict(pid=42, creationTime=123, image=str(suite / 'Office/program/soffice.bin')))}

            def snapshot(self):
                self.api.job_pids(11)
                return [dict(identity, **api.state(handle)) for handle, identity in self.members.values()]

            def close(self):
                events.append('close-retained-member-handles')
                self.members.clear()

        class Process:
            job = 11
            closed = False

            def open_diagnostic_witnesses(self):
                events.append('retain-job-member-handles')
                return Witness()

            def wait(self, timeout):
                events.append('launcher-exited')
                return 0  # This alone says nothing about the owned engine child.

            def terminate(self):
                events.append('terminate-private-job')
                if terminate_fails:
                    raise OSError('private job termination failed')
                api.alive = False

            def close(self):
                events.append('close-private-job')
                self.closed = True

        class Profile:
            name = 'private-generated-profile'

            def cleanup(self):
                events.append('remove-private-profile')
                if profile_fails:
                    raise OSError('profile removal failed')

        class Desktop:
            def terminate(self):
                events.append('request-graceful-desktop-exit')
                return True

        process = Process()
        engine = smoke.Engine(suite)
        engine.process, engine.profile, engine.desktop = process, Profile(), Desktop()
        return engine, api, events

    def test_launcher_exit_with_live_child_forces_only_private_job_and_fails_qualification(self):
        engine, api, events = self.scenario()
        engine.cleanup()
        self.assertIn('terminate-private-job', events, 'Launcher-only exit must not prove child exit')
        self.assertFalse(api.alive)
        self.assertTrue(engine.cleanup_errors, 'Forced recovery cannot qualify as graceful shutdown')
        self.assertLess(events.index('terminate-private-job'), events.index('close-private-job'))
        self.assertLess(events.index('close-private-job'), events.index('remove-private-profile'))
        self.assertTrue(engine.cleanup_evidence['jobEmptyVerified'])
        self.assertTrue(engine.cleanup_evidence['forcedTermination'])
        self.assertFalse(engine.cleanup_evidence['gracefulQualified'])

    def test_graceful_exit_retains_members_and_proves_empty_job_before_profile_removal(self):
        engine, api, events = self.scenario(graceful=True)
        engine.cleanup()
        self.assertFalse(engine.cleanup_errors)
        self.assertIn('retain-job-member-handles', events, 'Shared cleanup does not retain job member handles')
        self.assertLess(events.index('retain-job-member-handles'), events.index('request-graceful-desktop-exit'))
        self.assertNotIn('terminate-private-job', events)
        self.assertLess(events.index('close-private-job'), events.index('remove-private-profile'))
        self.assertTrue(hasattr(smoke, 'validate_cleanup_evidence'), 'The qualification cleanup oracle is missing')
        smoke.validate_cleanup_evidence(engine.cleanup_evidence)
        self.assertFalse(engine.cleanup_evidence['finalMembers'][0]['alive'])

    def test_unproved_exit_retains_job_profile_and_original_census_failure(self):
        for defect in ('termination', 'census'):
            with self.subTest(defect=defect):
                engine, api, events = self.scenario(terminate_fails=defect == 'termination', census_fails=defect == 'census')
                engine.cleanup()
                self.assertTrue(engine.cleanup_errors)
                self.assertNotIn('close-private-job', events)
                self.assertNotIn('remove-private-profile', events)
                if defect == 'census':
                    self.assertTrue(any(row.get('jobCensus') for row in engine.cleanup_evidence['errors']))

    def test_partial_start_without_process_never_claims_actual_engine_qualification(self):
        engine = smoke.Engine(Path('/generated-suite'))
        engine.cleanup()
        self.assertTrue(hasattr(engine, 'cleanup_evidence'), 'Missing no-process cleanup evidence')
        self.assertFalse(engine.cleanup_evidence['gracefulQualified'])
        with self.assertRaises((ValueError, AssertionError)):
            smoke.validate_cleanup_evidence(engine.cleanup_evidence)
        for child_alive in (True, False):
            with self.subTest(partial_start_child_alive=child_alive):
                engine, api, events = self.scenario()
                engine.desktop = None  # Failed connect_uno; the owned process may already exist.
                api.alive = child_alive
                engine.cleanup()
                self.assertTrue(engine.cleanup_errors)
                self.assertFalse(engine.cleanup_evidence['gracefulQualified'])
                self.assertNotIn('request-graceful-desktop-exit', events)
                self.assertIn('remove-private-profile', events)
                if child_alive:
                    self.assertIn('terminate-private-job', events)

    def test_profile_removal_failure_and_abnormal_member_exit_fail_qualification(self):
        for defect in ('profile', 'crash'):
            with self.subTest(defect=defect):
                engine, api, events = self.scenario(graceful=True, profile_fails=defect == 'profile', exit_code=0xC0000005 if defect == 'crash' else 0)
                engine.cleanup()
                self.assertTrue(engine.cleanup_errors)
                self.assertTrue(hasattr(engine, 'cleanup_evidence'), 'Missing structured cleanup failure evidence')
                self.assertFalse(engine.cleanup_evidence['gracefulQualified'])
                self.assertEqual(engine.cleanup_evidence['finalMembers'][0]['exitCode'], 0xC0000005 if defect == 'crash' else 0)

    def test_new_qualification_requires_positive_member_and_job_exit_proof(self):
        self.assertTrue(hasattr(smoke, 'validate_cleanup_evidence'), 'The qualification cleanup oracle is missing')
        suite = Path('/generated-suite')
        smoke.validate_cleanup_evidence(successful_cleanup(suite))
        for change in ('forced', 'missing-members', 'live-member', 'nonempty-job', 'missing-proof'):
            evidence = successful_cleanup(suite)
            if change == 'forced': evidence['forcedTermination'] = True
            elif change == 'missing-members': evidence['initialMembers'] = []
            elif change == 'live-member': evidence['finalMembers'][0]['alive'] = True
            elif change == 'nonempty-job': evidence['finalJobPids'] = [42]
            else: evidence['jobEmptyVerified'] = False
            with self.subTest(change=change), self.assertRaises((ValueError, AssertionError)):
                smoke.validate_cleanup_evidence(evidence)


if __name__ == '__main__':
    unittest.main()
