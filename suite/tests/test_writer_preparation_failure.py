"""Fixed preparation-only diagnostics, no real compiler/native input."""
import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

BASE = Path(__file__).resolve().parents[2]
E2E = BASE / 'suite/e2e'
sys.path.insert(0, str(E2E))
import ascii_message_preparation as preparation


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROFILE = 'budget-deadline-caller-v1'


class BudgetCallerProfileTests(unittest.TestCase):
    def setUp(self):
        self.phase = load(E2E / 'writer_server_observer_phase.py', 'writer_prep_phase')

    def expiry(self, now=127):
        with mock.patch.object(preparation.time, 'monotonic', side_effect=[100, now]):
            budget = preparation._Budget()
            try:
                preparation.prepare_observer(Path('/synthetic/uncreated'), architecture='arm64', budget=budget)
            except AssertionError as error:
                return error
        self.fail('real budget deadline did not reject before discovery')

    def test_optin_records_actual_known_caller_without_changing_legacy_encoding(self):
        error = self.expiry()
        legacy = self.phase.atomic_failure_exit(error)
        self.assertEqual(legacy, 0x5A000000 | (1 << 20) | (2 << 16) | 60)
        code = self.phase.atomic_failure_exit(error, profile=PROFILE)
        self.assertEqual(code, 0x5A000000 | (1 << 20) | (2 << 16) | 283)
        self.assertEqual((preparation.LIMIT, preparation.CLEANUP_RESERVE), (30., 3.))

    def test_clock_guard_is_not_skipped(self):
        error = self.expiry(99)
        expected = 0x5A000000 | (1 << 20) | (2 << 16) | 58
        self.assertEqual(self.phase.atomic_failure_exit(error, profile=PROFILE), expected)

    def test_same_filename_line_without_exact_budget_code_is_not_skipped(self):
        try:
            exec(compile('\n' * 59 + 'raise AssertionError()\n', str(E2E / 'ascii_message_preparation.py'), 'exec'), {})
        except AssertionError as error:
            self.assertEqual(self.phase.atomic_failure_exit(error, profile=PROFILE),
                             0x5A000000 | (1 << 20) | (2 << 16) | 60)

    def test_unknown_profile_is_generic_and_no_ambient_values_are_read(self):
        error = self.expiry()
        class Unreadable:
            def reject(self, *args, **kwargs): raise AssertionError('SYNTHETIC-DO-NOT-READ')
            __getitem__ = get = __iter__ = keys = items = values = copy = __len__ = reject
        with mock.patch.object(self.phase.os, 'environ', Unreadable()):
            self.assertEqual(self.phase.atomic_failure_exit(error, profile='unknown'), 3)
            self.assertEqual(self.phase.atomic_failure_exit(error, profile=PROFILE) & 0xffff, 283)

    def test_atomic_child_optin_keeps_original_prepare_arguments_and_failure(self):
        calls = []
        error = self.expiry()
        def captured(*args, **kwargs): calls.append(kwargs); raise error
        with mock.patch.object(preparation, 'prepare_observer', side_effect=captured):
            result = self.phase.child(['atomic', '--work', '/synthetic/private',
                '--descriptor', '/synthetic/descriptor.json', '--failure-origin-profile', PROFILE])
        self.assertEqual(result, 0x5A000000 | (1 << 20) | (2 << 16) | 283)
        self.assertEqual(calls, [{'architecture': 'arm64', 'discovery_policy': 'installed-native'}])

    def test_generic_budget_and_original_phase_lifetime_ast_are_unchanged(self):
        expected = 'b497180853f4684b8caf90f70e7eca1b8a8ff57438cb1784e58823841d4426e1'
        self.assertEqual(hashlib.sha256((E2E / 'ascii_message_preparation.py').read_text().encode()).hexdigest(), expected)
        tree = ast.parse((E2E / 'writer_server_observer_phase.py').read_bytes())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_phase')
        self.assertEqual(hashlib.sha256(ast.dump(run, include_attributes=False).encode()).hexdigest(), 'd4b19bab5440a50cf58a9a49657ffdb91dd11cc9cf02d8a88200aa3e4b5afecc')


class PreparationFailureReaderTests(unittest.TestCase):
    def setUp(self):
        self.api = load(BASE / 'suite/scripts/writer-server-observer-workflow.py', 'writer_prep_workflow')
        self.phase = load(E2E / 'writer_server_observer_phase.py', 'writer_prep_receipt')
        self.context = dict(schemaVersion=1, stageCode=1, passed=True, sourceFileCount=1187,
            errorCode=0, normalAcceptance=False, fullEngineQualified=False,
            acceptanceEligible=False, guiVerified=False)
        self.receipt = self.phase._receipt()
        self.receipt.update(launchAttempted=True, originalChildIdentityMatched=True,
            originalChildExitObserved=True, originalChildExitCode=1511129148,
            ownedJobEmpty=True, cleanupComplete=True)

    def validate(self, context=None, receipt=None, count=1187):
        return self.api.validate_preparation_failure_values(
            self.context if context is None else context,
            self.receipt if receipt is None else receipt,
            expected_source_file_count=count)

    def test_original_nine_and_eighteen_key_failure_is_diagnostic_only(self):
        self.assertEqual((len(self.context), len(self.receipt)), (9, 18))
        before = copy.deepcopy((self.context, self.receipt))
        self.assertTrue(self.validate())
        self.assertEqual((self.context, self.receipt), before)

    def test_context_or_compiler_success_and_any_authority_promotion_are_rejected(self):
        for key in ('passed', 'originalEngineRetirementAuthority', 'normalAcceptance',
                    'fullEngineQualified', 'acceptanceEligible', 'guiVerified', 'hardDeadlineEnforcementVerified'):
            bad = {**self.receipt, key: True}
            with self.subTest(field=key), self.assertRaises(self.api.Rejected):
                self.validate(receipt=bad)
        with self.assertRaises(self.api.Rejected): self.validate(context={**self.context, 'passed': False})

    def test_closed_types_counts_and_exit_identity_correlations_are_required(self):
        bad = [{**self.receipt, 'extra': 1}, {**self.receipt, 'originalChildExitCode': 'opaque'},
               {**self.receipt, 'originalChildExitCode': None},
               {**self.receipt, 'originalChildIdentityMatched': False},
               {**self.receipt, 'timedOut': True},
               {**self.receipt, 'pendingRetainedCount': 1},
               {**self.receipt, 'schemaVersion': True}]
        for code, value in enumerate(bad):
            with self.subTest(caseNumber=code), self.assertRaises(self.api.Rejected): self.validate(receipt=value)
        with self.assertRaises(self.api.Rejected): self.validate(count=1188)
        with self.assertRaises(self.api.Rejected): self.validate(context={**self.context, 'sourceFileCount': True})

    def test_unknown_launch_and_timeout_are_preserved_without_exit_authority(self):
        initial = self.phase._receipt()
        initial['errorCode'] = 1
        self.assertTrue(self.validate(receipt=initial))
        initial.update(launchAttempted=True, timedOut=True, errorCode=2, pendingRetainedCount=1)
        self.assertTrue(self.validate(receipt=initial))

    def test_job_census_requires_original_child_exit_but_none_stays_unknown(self):
        unknown = self.phase._receipt()
        unknown.update(launchAttempted=True, errorCode=1)
        self.assertFalse(unknown['originalChildExitObserved'])
        self.assertIsNone(unknown['originalChildExitCode'])
        for value in (False, True):
            with self.subTest(jobEmpty=value), self.assertRaises(self.api.Rejected):
                self.validate(receipt={**unknown, 'ownedJobEmpty': value})
        self.assertTrue(self.validate(receipt=unknown))

    def test_staged_artifact_contains_only_two_unchanged_bounded_json_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary) / '.work'
            public = work / 'writer-observer-public'
            public.mkdir(parents=True)
            context, compiler = public / 'context.numeric.json', public / 'compiler-phase.numeric.json'
            context.write_bytes(json.dumps(self.context, sort_keys=True).encode())
            compiler.write_bytes(json.dumps(self.receipt, sort_keys=True).encode())
            expected = (context.read_bytes(), compiler.read_bytes())
            output = work / 'writer-preparation-failure-public'
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = self.api.main(['validate-preparation-failure', '--context', str(context),
                    '--compiler-phase', str(compiler), '--output', str(output)])
            self.assertEqual(code, 0)
            validation = json.loads(stdout.getvalue())
            self.assertEqual(validation['stageCode'], 3)
            self.assertTrue(validation['passed'])
            self.assertFalse(validation['normalAcceptance'])
            self.assertFalse(validation['fullEngineQualified'])
            self.assertEqual(sorted(p.name for p in output.iterdir()), ['compiler-phase.numeric.json', 'context.numeric.json'])
            self.assertEqual(((output / context.name).read_bytes(), (output / compiler.name).read_bytes()), expected)
            self.assertEqual((context.read_bytes(), compiler.read_bytes()), expected)
            with self.assertRaises(self.api.Rejected): self.api.require_preparation_failure(context, compiler, output)

    def test_duplicate_oversize_symlink_or_extra_filename_is_not_published(self):
        for code in range(4):
            with self.subTest(caseNumber=code), tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary) / '.work'
                public = work / 'writer-observer-public'
                public.mkdir(parents=True)
                context, compiler = public / 'context.numeric.json', public / 'compiler-phase.numeric.json'
                context.write_bytes(json.dumps(self.context).encode())
                compiler.write_bytes(json.dumps(self.receipt).encode())
                if code == 0: context.write_bytes(b'{"schemaVersion":1,"schemaVersion":1}')
                if code == 1: compiler.write_bytes(b' ' * 4097)
                if code == 2:
                    target = public / 'original.numeric.json'
                    context.rename(target)
                    try: context.symlink_to(target)
                    except OSError: self.skipTest('test host cannot create synthetic symlink')
                if code == 3: context = public / 'other.numeric.json'; context.write_bytes(json.dumps(self.context).encode())
                output = work / 'writer-preparation-failure-public'
                with self.assertRaises(self.api.Rejected): self.api.require_preparation_failure(context, compiler, output)
                self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
