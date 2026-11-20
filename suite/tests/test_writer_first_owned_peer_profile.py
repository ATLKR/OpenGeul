"""Real coordinator and typed peer adapter with synthetic OS effects only."""
import inspect
import ast
import hashlib
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
import test_writer_server_observer_console as console_fixture
import test_writer_server_observer_prepare_native as native_fixture
from test_writer_server_observer_runner_composition import runner

PROFILE = 'owned-peer-before-first-admission-v1'

def retained_guard_line():
    source=Path(__file__).resolve().parents[1]/'e2e/writer_server_observer_cohort.py'
    tree=ast.parse(source.read_text())
    node=next(fn for cl in tree.body if isinstance(cl,ast.ClassDef) and cl.name=='RetainedCohort'
        for fn in cl.body if isinstance(fn,ast.FunctionDef) and fn.name=='_verify_retained')
    options={'show_empty':True} if 'show_empty' in inspect.signature(ast.dump).parameters else {}
    dump=ast.dump(node,include_attributes=False,**options)
    assert hashlib.sha256(dump.encode()).hexdigest()=='77bc34d82298234d843142c849d7784bba1ca80e536062e6216b0d980f06612e', 'Original retained state guard changed'
    raises=[n for n in ast.walk(node) if isinstance(n,ast.Raise) and isinstance(n.exc,ast.Name) and n.exc.id=='error']
    assert len(raises)==1, 'Exact original retained failure required'
    return raises[0].lineno



class FirstOwnedPeerProfile(unittest.TestCase):
    def setUp(self): self.reset()
    def tearDown(self): self.reset()
    def reset(self):
        runner._PENDING_CASES.clear()
        runner._CASE_STARTED = False

    def fixture(self, folder, *, profile=True):
        self.reset()
        if profile:
            self.assertIn('admission_profile', inspect.signature(runner.DedicatedWriterRunner).parameters,
                          'Explicit opt-in first-owned-peer admission profile absent')
        old, inputs, c, console, file_api, opens = console_fixture.Console().composed(folder)
        api, clock = c.api, c.clock
        identity, member, opened, state, census = (
            api.identity, api.member, api.open_initial_member, api.state, api.census)
        api.images[305] = inputs.output / 'Office/program/soffice.exe'
        api.images[307] = inputs.output / 'Office/program/soffice.bin'
        epoch = [0]
        events, cohorts, peers, rechecked, process_opens = [], [], [], [], []
        hooks = SimpleNamespace(pause=None, before_admit=None, after_admit=None)
        api.identity = lambda h: (601, 611) if h == 305 else (801, 901) if h == 307 else identity(h)
        api.member = lambda h, j: j == 1000 if h in (305, 307) else member(h, j)

        def open_member(pid, job):
            process_opens.append(pid)
            return 305 if pid == 601 else 307 if pid == 801 else opened(pid, job)

        api.open_initial_member = open_member
        api.state = lambda h: ((0, 0) if api.dead else (258, 259)) if h in (305, 307) else (
            (0, 81) if h == 301 and epoch[0] else state(h))
        api.census = lambda job: ((101, 301, 601, 501, 801 if epoch[0] else 401)
                                 if job == 1000 and not api.dead else census(job))
        system = native_fixture.System()
        system.host, system.thread, system.host_pid, system.birth, system.host_tid = 201, 203, 101, 111, 211
        system.engine_pid, system.engine_tid = 401, 611
        system.home, system.document, system.panel, system.child, system.descendant = 590, 600, 602, 601, 603
        system.windows = [system.home, system.document]

        def publish_peer(pid):
            system.engine_pid = pid
            system.facts = {
                system.home: (101, 211, 0, system.home),
                system.document: (101, 211, 0, system.document),
                system.panel: (101, 211, system.document, system.document),
                system.child: (pid, 611, system.panel, system.document),
                system.descendant: (pid, 611, system.child, system.document),
            }
            system.props = {(system.document, 'OpenGeul.Office.ParentHwnd'): system.panel,
                            (system.document, 'OpenGeul.Office.ChildHwnd'): system.child}
            system.focus, system.foreground = system.child, system.document

        publish_peer(401)

        def image(handle, flags, buffer, length):
            system.image = str(api.images[native_fixture.number(handle)])
            return system.process_image(handle, flags, buffer, length)

        system.kernel.QueryFullProcessImageNameW.call = image
        c.prep = native_fixture.M.PreparationNativeApi(api, kernel=system.kernel, user=system.user)
        find, recheck, focus = c.prep.find_attachment_once, c.prep.recheck_attachment, c.prep.focus_snapshot

        def find_peer(*args, **kwargs):
            events.append('peer-attempt')
            value = find(*args, **kwargs)
            peers.append(value)
            events.append('peer-pending' if value is None else 'peer-ready')
            return value

        def recheck_peer(launch, attachment, *, check):
            events.append('peer-recheck')
            rechecked.append(attachment)
            return recheck(launch, attachment, check=check)

        c.prep.find_attachment_once, c.prep.recheck_attachment = find_peer, recheck_peer
        def focus_snapshot(*args, **kwargs):
            events.append('focus-sample')
            return focus(*args, **kwargs)
        c.prep.focus_snapshot = focus_snapshot
        base = c.Cohort

        class Cohort(base):
            def __init__(self, *args, **kwargs):
                events.append('cohort-created')
                super().__init__(*args, **kwargs)
                cohorts.append(self)

            def admit(self):
                events.append('admit-attempt')
                if hooks.before_admit: hooks.before_admit()
                super().admit()
                events.append('admitted')
                if hooks.after_admit: hooks.after_admit()

            def verify(self, budget=None):
                events.append('cohort-verify')
                return super().verify(budget)

        c.Cohort = Cohort
        snapshot, binding = c.Backend({}, 'arm64').process_snapshot, c.Backend({}, 'arm64').window_binding
        backend = api.backend
        backend.process_snapshot = lambda h: {'pid': 801, 'creationTime': 901, 'waitResult': 258, 'exitCode': 259} if h == 307 else snapshot(h)
        backend.window_binding = lambda h: (801, 611) if h == 601 and epoch[0] else binding(h)

        def pause(seconds):
            clock.value += max(1, int(seconds * 1000))
            if hooks.pause: hooks.pause()

        kwargs = {'read_value': old.read_value, 'pause': pause, 'nonce': 71, 'console_profile': console}
        if profile: kwargs['admission_profile'] = PROFILE
        obj = runner.DedicatedWriterRunner(c, **kwargs)
        return SimpleNamespace(obj=obj, inputs=inputs, c=c, api=api, clock=clock, system=system,
            epoch=epoch, events=events, cohorts=cohorts, peers=peers, rechecked=rechecked,
            hooks=hooks, publish_peer=publish_peer, opens=process_opens, file_api=file_api)

    def assert_false_authority(self, report):
        for field in ('normalAcceptance', 'fullEngineQualified', 'acceptanceEligible', 'guiVerified'):
            self.assertIs(report[field], False)

    def test_first_peer_precedes_single_admission_and_retains_the_same_peer(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 0)
        self.assertEqual(x.events.count('admit-attempt'), 1)
        self.assertLess(x.events.index('peer-ready'), x.events.index('cohort-created'))
        self.assertLess(x.events.index('admitted'), x.events.index('peer-recheck'))
        self.assertLess(x.events.index('peer-recheck'), x.events.index('focus-sample'))
        self.assertEqual(len(x.peers), 1)
        self.assertTrue(x.rechecked)
        self.assertTrue(all(value is x.peers[0] for value in x.rechecked))
        self.assertEqual(x.cohorts[0].original_engine.pid, 401)
        self.assertTrue(report['runtime']['runtime_started'])
        self.assertEqual(report['preparation']['inputCount'], 0)
        self.assert_false_authority(report)

    def test_pending_peer_reclassifies_fresh_without_constructing_a_cohort(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            x.system.props.clear()
            x.hooks.pause = lambda: x.publish_peer(401)
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 0)
        self.assertEqual(report['preparation']['classificationAttemptCount'], 2)
        self.assertEqual([value is None for value in x.peers], [True, False])
        self.assertLess(x.events.index('peer-pending'), x.events.index('cohort-created'))
        self.assertEqual(x.events.count('admit-attempt'), 1)

    def test_fresh_pre_admission_snapshot_binds_first_peer_engine_without_adopting_an_admitted_role(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            x.system.props.clear()
            def later():
                x.epoch[0] = 1
                x.publish_peer(801)
            x.hooks.pause = later
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 0)
        self.assertEqual(report['preparation']['classificationAttemptCount'], 2)
        self.assertEqual(len(x.cohorts), 1)
        self.assertEqual((x.cohorts[0].original_engine.pid, x.cohorts[0].original_engine.birth), (801, 901))
        self.assertEqual(x.events.count('admit-attempt'), 1)
        self.assertEqual(x.opens.count(801), 2)
        self.assert_false_authority(report)

    def test_default_still_admits_first_image_and_rejects_that_original_exit81(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder, profile=False)
            x.system.props.clear()
            def later():
                x.epoch[0] = 1
                x.publish_peer(801)
            x.hooks.pause = later
            report = x.obj.execute(x.inputs)
        prep = report['preparation']
        self.assertEqual((report['stageCode'], report['failureCode']), (4, 13))
        self.assertEqual((prep['cohortFailureRoleCode'], prep['cohortFailureWaitResult'], prep['cohortFailureExitCode']), (3, 0, 81))
        self.assertEqual(x.cohorts[0].original_engine.pid, 401)
        self.assertEqual(x.events.count('admit-attempt'), 1)
        self.assertNotIn(801, x.opens)
        self.assertEqual(prep['inputCount'], 0)

    def test_admitted_engine_exit81_is_still_fatal_and_never_searches_a_new_peer(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            x.hooks.after_admit = lambda: (x.epoch.__setitem__(0, 1), x.publish_peer(801))
            report = x.obj.execute(x.inputs)
        prep = report['preparation']
        self.assertEqual((report['stageCode'], report['failureCode']), (4, 13))
        self.assertEqual((prep['preparationFailureKindCode'], prep['preparationFailureSourceCode'], prep['preparationFailureLine']), (14, 7, retained_guard_line()))
        self.assertEqual((prep['cohortFailureRoleCode'], prep['cohortFailureWaitResult'], prep['cohortFailureExitCode']), (3, 0, 81))
        self.assertEqual(len(x.peers), 1)
        self.assertNotIn(801, x.opens)
        self.assertTrue(prep['cleanupComplete'])
        self.assertEqual(report['pendingRetainedCount'], 0)

    def test_birth_change_between_peer_and_admit_rejects_the_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            original = x.api.identity
            x.hooks.before_admit = lambda: setattr(x.api, 'identity', lambda h: (401, 999) if h == 301 else original(h))
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 13)
        self.assertNotIn('admitted', x.events)
        self.assertEqual(len(x.peers), 1)
        self.assertGreater(report['pendingRetainedCount'], 0)
        self.assertIsNot(report['preparation']['cleanupComplete'], True)
        self.assertIsNone(report['preparation']['runtimeEntered'])

    def test_current_census_change_between_peer_and_admit_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            current = x.api.census
            x.hooks.before_admit = lambda: setattr(x.api, 'census', lambda job: (*current(job), 999) if job == 1000 and not x.api.dead else current(job))
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 13)
        self.assertNotIn('admitted', x.events)
        self.assertNotIn(999, x.opens)
        self.assertGreater(report['pendingRetainedCount'], 0)

    def test_changed_peer_after_admit_is_rechecked_without_reenumeration(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            x.hooks.after_admit = lambda: x.system.props.__setitem__((600, 'OpenGeul.Office.ChildHwnd'), 602)
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 13)
        self.assertEqual(len(x.peers), 1)
        self.assertEqual(len(x.rechecked), 1)
        self.assertEqual(x.events.count('admit-attempt'), 1)
        self.assertNotIn('focus-sample', x.events)
        self.assertTrue(report['preparation']['cleanupComplete'])
        self.assertEqual(report['preparation']['inputCount'], 0)

    def test_foreign_peer_pid_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            x.publish_peer(801)
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 13)
        self.assertEqual(report['preparation']['preparationFailureSourceCode'], 6)
        self.assertEqual(x.events.count('peer-attempt'), 1)
        self.assertFalse(x.cohorts)
        self.assertEqual(report['preparation']['classificationAttemptCount'], 1)

    def test_unknown_duplicate_and_dead_current_members_still_reject_before_peer(self):
        for case, reason in (('unknown', 6), ('duplicate', 7), ('dead', 5)):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                x = self.fixture(folder)
                if case == 'dead':
                    current = x.api.state
                    x.api.state = lambda h: (0, 81) if h == 301 else current(h)
                else:
                    current = x.api.census
                    x.api.census = lambda job: (*current(job), 801) if job == 1000 and not x.api.dead else current(job)
                    if case == 'unknown':
                        path = x.inputs.output / 'Office/program/unknown.exe'
                        path.touch()
                        x.api.images[307] = path
                report = x.obj.execute(x.inputs)
                self.assertEqual((report['stageCode'], report['failureCode']), (3, 6))
                self.assertEqual(report['preparation']['classificationReasonCode'], reason)
                self.assertFalse(x.cohorts)
                self.assertNotIn('peer-attempt', x.events)

    def test_missing_peer_expires_at_the_original_cutoff_without_cohort_or_input(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            x.system.props.clear()
            x.hooks.pause = lambda: setattr(x.clock, 'value', x.clock.value + 55000)
            report = x.obj.execute(x.inputs)
        prep = report['preparation']
        self.assertEqual(report['failureCode'], 3)
        self.assertEqual(prep['cutoffQpc'] - prep['startQpc'], 55000)
        self.assertEqual(prep['deadlineQpc'] - prep['startQpc'], 60000)
        self.assertFalse(x.cohorts)
        self.assertEqual(prep['inputCount'], 0)
        self.assertIsNone(prep['runtimeEntered'])

    def test_original_console_auxiliary_birth_change_is_not_adopted_before_admission(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            x.system.props.clear()
            original = x.api.identity
            def later():
                x.api.identity = lambda h: (501, 999) if h == 303 else original(h)
                x.publish_peer(401)
            x.hooks.pause = later
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 6)
        self.assertEqual(report['preparation']['classificationReasonCode'], 11)
        self.assertFalse(x.cohorts)
        self.assertGreater(report['pendingRetainedCount'], 0)

    def test_temporary_handle_close_failure_never_reaches_peer_or_admission(self):
        with tempfile.TemporaryDirectory() as folder:
            x = self.fixture(folder)
            x.api.fail_close = 202
            report = x.obj.execute(x.inputs)
        self.assertEqual(report['failureCode'], 10)
        self.assertNotIn('peer-attempt', x.events)
        self.assertFalse(x.cohorts)
        self.assertGreater(report['pendingRetainedCount'], 0)

    def test_profile_is_explicit_closed_and_unknown_values_fail_before_launch(self):
        self.assertIn('admission_profile', inspect.signature(runner.DedicatedWriterRunner).parameters,
                      'Explicit opt-in first-owned-peer admission profile absent')
        for value in ('unknown', '', True, 1, []):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(runner.RunnerFailure) as caught:
                runner.DedicatedWriterRunner(object(), admission_profile=value)
            self.assertEqual(caught.exception.code, runner.Code.INPUT)

    def test_cli_opt_in_is_forwarded_and_absence_keeps_the_original_order(self):
        self.assertIn('admission_profile', inspect.signature(runner.DedicatedWriterRunner).parameters,
                      'Explicit opt-in first-owned-peer admission profile absent')
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as folder:
                x = self.fixture(folder, profile=False)
                prepared = Path(folder) / 'prepared.numeric.json'
                prepared.write_text('{}')
                report_path = Path(folder) / 'report.numeric.json'
                flags = {'output': x.inputs.output, 'baseline': x.inputs.baseline,
                    'artifact': x.inputs.artifact, 'diagnostic-lock': x.inputs.diagnostic_lock,
                    'source-lock': x.inputs.source_lock,
                    'expected-suite-source-commit': x.inputs.expected_suite_source_commit,
                    'prepared-library': prepared, 'host-python': x.inputs.host_python,
                    'helper-script': x.inputs.helper_script, 'windows': x.inputs.windows,
                    'work-root': x.inputs.work_root, 'report': report_path}
                args = [value for key, item in flags.items() for value in ('--' + key, str(item))]
                if enabled: args.extend(('--admission-profile', PROFILE))
                x.c.ConsoleProfile = lambda: x.obj.console_profile
                user = Path(folder) / 'user'
                synthetic = {'SystemRoot': str(x.inputs.windows), 'WINDIR': str(x.inputs.windows),
                    'USERPROFILE': str(user), 'APPDATA': str(user / 'AppData/Roaming'),
                    'LOCALAPPDATA': str(user / 'AppData/Local')}
                output = io.StringIO()
                with mock.patch.object(runner, 'NativeComponents', lambda: x.c), \
                     mock.patch.object(runner.os, 'environ', synthetic), \
                     mock.patch.object(runner.secrets, 'randbelow', lambda bound: 70), \
                     contextlib.redirect_stdout(output):
                    code = runner.main(args)
                self.assertEqual(code, 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report, json.loads(report_path.read_text()))
                self.assertEqual(report['failureCode'], 0)
                self.assertEqual(x.events.index('peer-ready') < x.events.index('cohort-created'), enabled)

    def test_cli_unknown_profile_fails_before_native_components_are_created(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            prepared = Path(folder) / 'prepared.numeric.json'
            prepared.write_text('{}')
            names = ('output', 'baseline', 'artifact', 'diagnostic-lock', 'source-lock',
                     'expected-suite-source-commit', 'host-python', 'helper-script',
                     'windows', 'work-root')
            args = [value for name in names for value in ('--' + name, 'synthetic')]
            args.extend(('--prepared-library', str(prepared)))
            args.extend(('--report', str(Path(folder) / 'error-report.numeric.json')))
            for profile, expected_calls in (('unknown', 0), (PROFILE, 1)):
                output = io.StringIO()
                with mock.patch.object(runner, 'NativeComponents', lambda: calls.append(1)), \
                     contextlib.redirect_stdout(output):
                    code = runner.main([*args, '--admission-profile', profile])
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), expected_calls)
                self.assertEqual(json.loads(output.getvalue())['failureCode'], 1)


if __name__ == '__main__': unittest.main()
