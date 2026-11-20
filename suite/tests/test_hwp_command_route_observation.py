"""Synthetic route receipts; no Windows input, process identity or causation proof."""
from pathlib import Path
import copy
import hashlib
import json
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'e2e'))
from test_initial_focus_final_counters import IDENTITY, final_row, prefix_row


def route(**changes):
    value = dict(schemaVersion=1, statusCode=1, ownerGeneration=1, cap=65535,
        attemptCap=16, overflowMask=0, updateFailureMask=0, ownerMismatch=0,
        receivedCount=1, receivedLastSequence=41,
        enqueueReturnedCount=1, enqueueReturnedLastSequence=41,
        executeCount=1, executeLastSequence=41,
        coverageComplete=0, eventCompletenessUnknown=1, zeroCountsUsable=0,
        acceptanceEligible=0)
    value.update(changes)
    return value


def framed(focus=None, section=None):
    return dict(focus=prefix_row() if focus is None else focus,
        route=route() if section is None else section)


class RouteParserTests(unittest.TestCase):
    def parse(self, rows, **changes):
        from hwp_command_route_observation import parse_hwp_command_route
        return parse_hwp_command_route(rows, retained_identity=changes.get('identity', IDENTITY),
            retirement_confirmed=changes.get('retired', True))

    def test_same_original_sequence_is_positive_historical_route_only(self):
        value = self.parse([framed()])
        self.assertEqual((value['snapshotKnown'], value['positiveRouteObserved']), (1, 1))
        self.assertEqual((value['known'], value['coverageComplete'], value['zeroCountsUsable'],
            value['eventCompletenessUnknown'], value['acceptanceEligible']), (0, 0, 0, 1, 0))
        self.assertEqual(value['scope']['ownerGeneration'], 1)

    def test_guard_or_begininvoke_failure_and_zero_are_not_negative_proof(self):
        for section in (route(enqueueReturnedCount=0, enqueueReturnedLastSequence=0,
                              executeCount=0, executeLastSequence=0),
                        route(executeCount=0, executeLastSequence=0),
                        route(receivedCount=0, receivedLastSequence=0,
                              enqueueReturnedCount=0, enqueueReturnedLastSequence=0,
                              executeCount=0, executeLastSequence=0)):
            value = self.parse([framed(section=section)])
            self.assertEqual((value['snapshotKnown'], value['positiveRouteObserved'], value['zeroCountsUsable']), (1, 0, 0))

    def test_callback_may_execute_before_begininvoke_returns(self):
        first = framed(section=route(enqueueReturnedCount=0, enqueueReturnedLastSequence=0))
        last = framed(prefix_row(sequence=5, snapshotRevision=2), route())
        self.assertEqual(self.parse([first])['snapshotKnown'], 1)
        self.assertEqual(self.parse([first, last])['positiveRouteObserved'], 1)

    def test_sequence_arrival_reordering_and_partial_last_pair_do_not_prove_route(self):
        first = framed(section=route(receivedLastSequence=42,
            enqueueReturnedLastSequence=42, executeLastSequence=42))
        last = framed(prefix_row(sequence=5, snapshotRevision=2), route(receivedCount=2,
            receivedLastSequence=40, enqueueReturnedCount=2, enqueueReturnedLastSequence=40,
            executeCount=2, executeLastSequence=39))
        value = self.parse([first, last])
        self.assertEqual((value['snapshotKnown'], value['positiveRouteObserved']), (1, 0))

    def test_owner_generation_and_every_original_scope_member_are_required(self):
        for name in IDENTITY:
            identity = dict(IDENTITY); identity[name] += 1
            with self.subTest(name=name):
                self.assertEqual(self.parse([framed()], identity=identity)['snapshotKnown'], 0)
        for section in (route(ownerGeneration=2), route(ownerGeneration=True)):
            self.assertEqual(self.parse([framed(section=section)])['snapshotKnown'], 0)
        for changes in (dict(identityKnown=0), dict(ownerChanged=1), dict(updateFailed=1), dict(overflowMask=1)):
            self.assertEqual(self.parse([framed(prefix_row(**changes))])['snapshotKnown'], 0)

    def test_unknown_keys_bool_as_int_bad_bounds_and_pair_arithmetic_fail_closed(self):
        bad = [route(extra=1), route(receivedCount=True), route(receivedLastSequence=True),
            route(cap=65536), route(attemptCap=17), route(receivedCount=65536),
            route(receivedLastSequence=2**63), route(receivedCount=0),
            route(executeCount=2), route(enqueueReturnedCount=2), route(coverageComplete=1),
            route(zeroCountsUsable=1), route(eventCompletenessUnknown=0), route(acceptanceEligible=1)]
        missing = route(); del missing['statusCode']; bad.append(missing)
        for section in bad:
            with self.subTest(fields=tuple(section)):
                self.assertEqual(self.parse([framed(section=section)])['snapshotKnown'], 0)

    def test_observer_loss_concurrent_snapshot_and_missing_output_are_unknown(self):
        for section in (route(statusCode=2, overflowMask=1), route(statusCode=2, updateFailureMask=1),
                        route(statusCode=2, ownerMismatch=1), route(statusCode=3), None, {}):
            row = framed(); row['route'] = section
            self.assertEqual(self.parse([row])['snapshotKnown'], 0)
        for rows in ([], None, {}, [framed()] * 129):
            self.assertEqual(self.parse(rows)['snapshotKnown'], 0)

    def test_final_requires_original_retirement_and_increasing_same_generation(self):
        self.assertEqual(self.parse([framed(final_row())], retired=False)['snapshotKnown'], 0)
        self.assertEqual(self.parse([framed(final_row())])['positiveRouteObserved'], 1)
        first = framed()
        for focus, section in ((prefix_row(), route()),
                (prefix_row(sequence=5, snapshotRevision=2, ownerGeneration=2), route(ownerGeneration=2)),
                (prefix_row(sequence=5, snapshotRevision=2), route(receivedLastSequence=40))):
            self.assertEqual(self.parse([first, framed(focus, section)])['snapshotKnown'], 0)

    def test_route_pair_count_cannot_decrease_or_change_last_without_increment(self):
        first = framed(section=route(receivedCount=2))
        for section in (route(receivedCount=1), route(receivedCount=2, receivedLastSequence=42)):
            self.assertEqual(self.parse([first, framed(prefix_row(sequence=5, snapshotRevision=2), section)])['snapshotKnown'], 0)


class SameReadCollectorTests(unittest.TestCase):
    def envelope(self, focus, section='absent'):
        details = dict(focus); sequence = details.pop('sequence')
        if section != 'absent': details['hwpCommandRoute'] = section
        return json.dumps(dict(event='suite.initialEditorFocusFlow', component='host', stage='prefix',
            sequence=sequence, utc='2026-11-19T00:00:00Z', processId=101, managedThreadId=1,
            workerProcessId=501, traceId='synthetic', details=details), separators=(',', ':')).encode()

    def collect(self, lines):
        import native_menu_smoke as smoke
        return smoke._initial_focus_counters(lines, dict(known=True, scope=dict(IDENTITY, moduleCode=1)),
            trace='synthetic', worker=501, managed=1, retirement_confirmed=True, budget=lambda: None)

    def test_new_section_is_split_before_old_parser_receives_byte_equivalent_details(self):
        from initial_focus_final_counters import parse_initial_focus_final_counters
        focus = prefix_row()
        with mock.patch('initial_focus_final_counters.parse_initial_focus_final_counters',
                        wraps=parse_initial_focus_final_counters) as parser:
            value = self.collect([self.envelope(focus, route())])
        self.assertEqual(parser.call_args_list[0].args, ([focus],))
        expected = self.collect([self.envelope(focus)])
        self.assertEqual({key: item for key, item in value.items() if key != 'hwpCommandRoute'}, expected)
        self.assertEqual(value['hwpCommandRoute']['positiveRouteObserved'], 1)

    def test_route_observer_failure_never_changes_old_focus_projection(self):
        focus = prefix_row()
        expected = self.collect([self.envelope(focus)])
        for section in (None, {}, route(extra=1), route(receivedCount=True)):
            value = self.collect([self.envelope(focus, section)])
            self.assertEqual({key: item for key, item in value.items() if key != 'hwpCommandRoute'}, expected)
            self.assertEqual(value['hwpCommandRoute']['snapshotKnown'], 0)
        with mock.patch('hwp_command_route_observation.parse_hwp_command_route', side_effect=RuntimeError()):
            value = self.collect([self.envelope(focus, route())])
        self.assertEqual({key: item for key, item in value.items() if key != 'hwpCommandRoute'}, expected)
        self.assertEqual(value['hwpCommandRoute']['snapshotKnown'], 0)

    def test_optional_parser_import_failure_never_revokes_original_focus_result(self):
        import builtins
        original_import = builtins.__import__
        def failed_optional(name, *args, **options):
            if name == 'hwp_command_route_observation': raise ImportError()
            return original_import(name, *args, **options)
        focus = prefix_row(); expected = self.collect([self.envelope(focus)])
        with mock.patch('builtins.__import__', side_effect=failed_optional):
            value = self.collect([self.envelope(focus, route())])
        self.assertEqual({key: item for key, item in value.items() if key != 'hwpCommandRoute'}, expected)
        self.assertEqual((value['hwpCommandRoute']['snapshotKnown'],value['hwpCommandRoute']['errorCode']), (0,6))

    def test_new_section_does_not_bypass_original_framing_and_owner_identity_guards(self):
        original = json.loads(self.envelope(prefix_row(), route()))
        for key, bad in (('processId',102), ('workerProcessId',502), ('managedThreadId',2),
                         ('traceId','foreign'), ('sequence',True), ('stage','other')):
            row = copy.deepcopy(original); row[key] = bad
            value = self.collect([json.dumps(row,separators=(',',':')).encode()])
            self.assertEqual((value['known'],value['latest']), (0,{}))
            self.assertNotIn('hwpCommandRoute', value)

    def test_missing_section_in_some_frames_remains_unknown_and_duplicate_envelope_rejected(self):
        lines = [self.envelope(prefix_row(), route()), self.envelope(prefix_row(sequence=5, snapshotRevision=2))]
        self.assertEqual(self.collect(lines)['hwpCommandRoute']['snapshotKnown'], 0)
        duplicate = self.envelope(prefix_row(), route()).replace(b'"statusCode":1', b'"statusCode":1,"statusCode":1')
        self.assertEqual(self.collect([duplicate])['known'], 0)


class RouteDeadlineIsolationTests(unittest.TestCase):
    envelope = SameReadCollectorTests.envelope

    def capture(self, *, clock, budget=None):
        import native_menu_smoke as smoke
        if budget is None:
            def budget():
                if clock[0] >= 1.0: raise TimeoutError()
        return smoke._initial_focus_counters([self.envelope(prefix_row(), route())],
            dict(known=True,scope=dict(IDENTITY,moduleCode=1)),trace='synthetic',worker=501,
            managed=1,retirement_confirmed=True,budget=budget)

    def original_result(self):
        return SameReadCollectorTests.collect(self,[self.envelope(prefix_row())])

    def assert_isolated(self, value, expected, code):
        self.assertEqual({key:item for key,item in value.items() if key!='hwpCommandRoute'},expected)
        self.assertEqual((value['hwpCommandRoute']['snapshotKnown'],
            value['hwpCommandRoute']['positiveRouteObserved'],value['hwpCommandRoute']['errorCode']), (0,0,code))

    def test_route_parse_expiry_discards_optional_positive_without_revoking_base(self):
        from hwp_command_route_observation import parse_hwp_command_route
        expected=self.original_result();clock=[0.0]
        def expires(*args,**options):
            value=parse_hwp_command_route(*args,**options);clock[0]=1.0
            return value
        with mock.patch('hwp_command_route_observation.parse_hwp_command_route',side_effect=expires) as parser:
            value=self.capture(clock=clock)
        self.assertEqual(parser.call_count,1)
        self.assert_isolated(value,expected,7)

    def test_import_consumes_deadline_before_optional_parser_and_keeps_base(self):
        import builtins
        original_import=builtins.__import__;expected=self.original_result();clock=[0.0]
        def expires(name,*args,**options):
            value=original_import(name,*args,**options)
            if name=='hwp_command_route_observation':clock[0]=1.0
            return value
        with mock.patch('hwp_command_route_observation.parse_hwp_command_route') as parser, \
                mock.patch('builtins.__import__',side_effect=expires):
            value=self.capture(clock=clock)
        self.assertEqual(parser.call_count,0)
        self.assert_isolated(value,expected,7)

    def test_expiring_import_failure_is_optional_unknown_only(self):
        import builtins
        original_import=builtins.__import__;expected=self.original_result();clock=[0.0]
        def failure(name,*args,**options):
            if name=='hwp_command_route_observation':clock[0]=1.0;raise ImportError()
            return original_import(name,*args,**options)
        with mock.patch('builtins.__import__',side_effect=failure):
            value=self.capture(clock=clock)
        self.assert_isolated(value,expected,6)

    def test_expiring_parse_failure_is_optional_unknown_only(self):
        expected=self.original_result();clock=[0.0]
        def failure(*args,**options):clock[0]=1.0;raise RuntimeError()
        with mock.patch('hwp_command_route_observation.parse_hwp_command_route',side_effect=failure):
            value=self.capture(clock=clock)
        self.assert_isolated(value,expected,6)

    def test_expiry_after_original_final_check_skips_optional_work_without_extending_deadline(self):
        expected=self.original_result();clock=[0.0];checks=[]
        def budget():
            checks.append(clock[0])
            if clock[0]>=1.0:raise TimeoutError()
            # Original one-frame budget checks: entry, line, post-loop, post-base.
            if len(checks)==4:clock[0]=1.0
        with mock.patch('hwp_command_route_observation.parse_hwp_command_route') as parser:
            value=self.capture(clock=clock,budget=budget)
        self.assertEqual(checks[:4],[0.0]*4)
        self.assertEqual(parser.call_count,0)
        self.assert_isolated(value,expected,7)

    def test_original_base_expiry_or_parse_exception_remains_primary_and_skips_optional_work(self):
        from initial_focus_final_counters import parse_initial_focus_final_counters
        for failure,code in ((False,10),(True,11)):
            clock=[0.0]
            def base(*args,**options):
                if failure:raise RuntimeError()
                value=parse_initial_focus_final_counters(*args,**options);clock[0]=1.0
                return value
            with mock.patch('initial_focus_final_counters.parse_initial_focus_final_counters',side_effect=base), \
                    mock.patch('hwp_command_route_observation.parse_hwp_command_route') as parser:
                value=self.capture(clock=clock)
            self.assertEqual((value['errorCode'],value['latest']),(code,{}))
            self.assertNotIn('hwpCommandRoute',value)
            self.assertEqual(parser.call_count,0)


def tokens(source):
    # A closed lexical statement/brace tree: strings and punctuation remain exact.
    # Comments/whitespace alone are ignored; this is not a claim of C# compilation.
    token = r'//[^\n]*|/\*[\s\S]*?\*/|@?"(?:\\.|[^"\\])*"|\w+|[^\s]'
    return [item for item in re.findall(token, source) if not item.startswith(('//', '/*'))]


class RouteSourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.form = (self.root / 'shell/OfficeDocumentForm.cs').read_text()
        self.core = self.root / 'shell/Core/HwpCommandRouteObservation.cs'

    def test_original_command_statement_tree_is_preserved_after_exact_three_sites_removed(self):
        begin = self.form.index('    private void OnWorkerCommand(')
        end = self.form.index('    private Size EditorSize()', begin)
        actual = self.form[begin:end]
        added = ('        var hwpRouteObservation = ObserveHwpRouteReceived(command);\n',
                 'ObserveHwpRoute(hwpRouteObservation, command, 3); ',
                 '            ObserveHwpRoute(hwpRouteObservation, command, 2);\n')
        for site in added:
            self.assertEqual(actual.count(site), 1)
            actual = actual.replace(site, '', 1)
        self.assertEqual(hashlib.sha256(json.dumps(tokens(actual), separators=(',', ':')).encode()).hexdigest(),
            '710f3bd8df4465610aecfc2c0c34277a2c63e5215dc7c3f2f2e250adf36ac17d')
        command = self.form[begin:end]
        self.assertLess(command.index('ObserveHwpRouteReceived(command)'), command.index('var traceSave'))
        self.assertLess(command.index('if (!attached || busy || closing || IsDisposed)'), command.index('ObserveHwpRoute(hwpRouteObservation, command, 3)'))
        self.assertIn('case "new": ObserveHwpRoute(hwpRouteObservation, command, 3); create(command.Module ?? module.Id); break;', command)
        self.assertIn('            });\n            ObserveHwpRoute(hwpRouteObservation, command, 2);\n        }\n        catch (InvalidOperationException e)', command)

    def test_cached_only_nonthrowing_helpers_and_original_export_sink(self):
        block = self.form.split('    private InitialFocusCounters? ObserveHwpRouteReceived(', 1)[1].split('    private void WriteInitialFocusPrefix(', 1)[0]
        self.assertIn('command.Command != "new" || command.Module != "hwp"', block)
        for name in ('initialFocusCounters', 'editorFocus', 'initialFocusOwnerGeneration'):
            self.assertIn('Volatile.Read(ref ' + name + ')', block)
        for token in ('Native.', 'Process.', 'Environment.', 'SendAsync(', 'Console.', 'DateTime', 'Stopwatch', '.Handle', 'BeginInvoke(', 'create('):
            self.assertNotIn(token, block)
        self.assertGreaterEqual(block.count('catch (Exception)'), 4)
        self.assertNotIn('throw', block)
        self.assertNotIn('counters.UpdateFailed', block)
        self.assertIn('hwpCommandRoute = SnapshotHwpRoute(counters)', self.form)
        self.assertEqual(self.form.count('initialFocusFlowDiagnostics.Write(prefix ? "prefix" : "final"'), 1)

    def test_default_command_guard_or_observer_reordering_mutant_cannot_match_original_tree(self):
        source = self.form
        for before, after in (
            ('!attached || busy || closing || IsDisposed','!attached || closing || IsDisposed'),
            ('case "new": ObserveHwpRoute(hwpRouteObservation, command, 3); create(command.Module ?? module.Id); break;',
             'case "new": create(command.Module ?? module.Id); ObserveHwpRoute(hwpRouteObservation, command, 3); break;'),
            ('            });\n            ObserveHwpRoute(hwpRouteObservation, command, 2);',
             '            ObserveHwpRoute(hwpRouteObservation, command, 2);\n            });')):
            self.form = source.replace(before, after, 1)
            with self.assertRaises(AssertionError):
                self.test_original_command_statement_tree_is_preserved_after_exact_three_sites_removed()
        self.form = source

    def test_core_uses_immutable_pairs_bounded_cas_and_double_collect(self):
        source = self.core.read_text()
        self.assertIn('sealed record CountSequence', source)
        self.assertIn('Interlocked.CompareExchange(ref slot, next, before)', source)
        self.assertIn('attempt < AttemptCap', source)
        self.assertIn('public const int CountCap = 65535, AttemptCap = 16;', source)
        self.assertIn('ReferenceEquals(receivedBefore, receivedAfter)', source)
        for token in ('lock (', 'while (', 'Thread.Sleep', 'SpinWait', 'Environment.', 'Process.', 'DateTime', 'Console.', 'Native.'):
            self.assertNotIn(token, source)

    def test_original_workers_launch_logger_and_focus_parser_are_byte_identical(self):
        for path, digest in (
            ('shell/Core/WorkerClient.cs', 'e03d7cfb055f0bb92159fdf45121f2f278c372f89a0f84e24929038cec523190'),
            ('shell/HomeForm.cs', 'e811f469221e67a656712b97c87842abc91f6d9b756100e2992f0aa385b39e05'),
            ('shell/Core/HwpLaunch.cs', 'f6f9b880a9dc796ac17e920c2030df715ba695458df15ac2a2fa30465d54eb8a'),
            ('shell/Core/OwnedEditorFocus.cs', '92c782419aa76412327b728df05496ac913aeb2eb2b0d7a7d3a82a6083bd3004'),
            ('shell/Core/SaveDiagnosticsTrace.cs', 'a6260cfe63ca89762dff49237f4d07b1030a92022aff8ce5cc3cf8ce16232af2'),
            ('e2e/initial_focus_final_counters.py', '6f5a664f0950d974d1e4d5e29b2a94bb7ef10622fc24aebef441670b3eb64e77')):
            self.assertEqual(hashlib.sha256((self.root / path).read_bytes()).hexdigest(), digest)

    def test_csharp_synthetic_cases_are_registered_with_no_added_dependency(self):
        tests = (self.root / 'shell-tests/HwpCommandRouteObservationTests.cs').read_text()
        for case in ('CallbackBeforeReturn', 'GuardedOrEnqueueFailure', 'ObserverFailure', 'OwnerMismatch',
                     'Overflow', 'ConcurrentPairSnapshot', 'ConcurrentWriters'):
            self.assertIn(case, tests)
        self.assertEqual((self.root / 'shell-tests/Program.cs').read_text().count('tests.AddRange(HwpCommandRouteObservationTests.Cases());'), 1)


if __name__ == '__main__':
    unittest.main()
