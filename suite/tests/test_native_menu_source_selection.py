"""Actual source admission and epochs guard the common Popen/probe boundaries."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'suite/e2e'))
import native_menu_source_admission as gate
import native_menu_msaa_hit as hit
import windows_smoke as windows
from suite.tests import test_native_menu_source_admission as fixtures


class SourceMenuSelectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceMenuAdmissionTests(
            methodName='test_admits_real_validators_and_freezes_closed_binary_summary')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.suite = self.fixture.root
        self.harness = self.fixture.trusted
        inputs = self.harness/'.work/source-engine-input'
        inputs.mkdir(parents=True)
        self.archive = inputs/'OpenGeul-Office-engine-arm64.zip'
        self.receipt = inputs/'source-build-receipt.json'
        self.archive.write_bytes(self.fixture.archive.read_bytes())
        self.receipt.write_bytes(self.fixture.receipt.read_bytes())
        self.output = Path(self.fixture.temp.name)/'evidence'
        self.output.mkdir()
        self.command = [str(self.suite/'OpenGeul.Office.exe'), '--module', 'writer']
        replacement = patch.object(gate, '_HARNESS_ROOT', self.harness)
        replacement.start()
        self.addCleanup(replacement.stop)

    def implementation(self):
        try:
            return importlib.import_module('native_menu_source_selection')
        except ModuleNotFoundError:
            self.fail('Common source menu selection is not implemented')

    def prepared(self, *, deadline=None, architecture='arm64'):
        return self.implementation().prepare_source_menu_runtime(self.suite, architecture,
            deadline=time.monotonic()+30 if deadline is None else deadline)

    def selected(self, prepared=None, *, deadline=None):
        return self.implementation().source_menu_for_launch(
            self.prepared() if prepared is None else prepared,
            deadline=time.monotonic()+30 if deadline is None else deadline)

    def launch(self, selection, *, pointer=None, command=None, suite=None, name='selected'):
        calls = []
        def popen(actual, **options):
            calls.append('popen')
            return SimpleNamespace(args=actual, pid=71, _handle=72, stderr=options['stderr'])
        def park(*args, **options):
            calls.append('pointer')
            if pointer is not None:
                pointer(*args, **options)
        with patch.object(windows, 'prepare_launch_pointer', park), \
                patch.object(windows.subprocess, 'Popen', popen):
            process = windows.launch_suite(self.command if command is None else command,
                self.suite if suite is None else suite, self.output, name, source_menu=selection)
        self.assertEqual(calls, ['pointer', 'popen'])
        return process

    def reject_launch(self, selection, *, command=None, suite=None, pointer=None):
        calls = []
        def popen(*args, **options):
            calls.append('popen')
            return SimpleNamespace()
        def park(*args, **options):
            calls.append('pointer')
            if pointer is not None:
                pointer(*args, **options)
        with patch.object(windows, 'prepare_launch_pointer', park), \
                patch.object(windows.subprocess, 'Popen', popen), self.assertRaises(ValueError):
            windows.launch_suite(self.command if command is None else command,
                self.suite if suite is None else suite, self.output, 'rejected', source_menu=selection)
        self.assertNotIn('popen', calls)
        return calls

    def test_prepares_actual_bare_gate_context_and_freezes_contexts(self):
        prepared = self.prepared()
        module = self.implementation()
        self.assertIs(type(prepared.admission), gate.SourceMenuAdmission)
        self.assertEqual(prepared.admission.architecture, 'arm64')
        self.assertTrue(prepared.payload_epoch)
        self.assertTrue(prepared.input_epoch)
        selected = self.selected(prepared)
        self.assertIs(selected.prepared, prepared)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            selected.launch_deadline = time.monotonic()+150
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            prepared.admission = None
        for constructor, args in ((module.PreparedSourceMenu, (prepared.admission, (), ())),
                                  (module.SourceMenuSelection, (prepared, time.monotonic()+1))):
            with self.subTest(context=constructor.__name__), self.assertRaises(TypeError):
                constructor(*args)

    def test_selected_popen_keeps_exact_context_and_original_pointer_deadline(self):
        selected = self.selected()
        observed = []
        process = self.launch(selected, pointer=lambda *args, **kwargs: observed.append(kwargs))
        self.assertIs(process.opengeul_source_menu_selection, selected)
        self.assertEqual(process.opengeul_suite_root, self.suite)
        self.assertTrue(process.stderr.closed)
        self.assertEqual(observed, [dict(deadline=selected.launch_deadline)])

    def test_default_off_preserves_launch_without_any_source_validation(self):
        module = self.implementation()
        with patch.object(module, '_verify_source_menu_launch',
                          side_effect=AssertionError('Unexpected source validation')):
            process = self.launch(None, command=['legacy-owned.exe'])
        self.assertFalse(hasattr(process, 'opengeul_source_menu_selection'))

    def test_shared_prepared_runtime_does_not_repeat_gate_for_new_launches(self):
        real = gate.admit_source_menu_runtime
        admitted = []
        def admit(*args, **kwargs):
            admitted.append('full-gate')
            return real(*args, **kwargs)
        with patch.object(gate, 'admit_source_menu_runtime', admit):
            prepared = self.prepared()
            self.launch(self.selected(prepared), name='first')
            self.launch(self.selected(prepared), name='second')
        self.assertEqual(admitted, ['full-gate'])

    def test_rejects_fake_selection_and_wrong_root_or_command_before_popen(self):
        for invalid in (True, object(), self.prepared()):
            with self.subTest(context='unselected-or-forged'):
                self.assertEqual(self.reject_launch(invalid), [])
        selected = self.selected()
        for command in (['OpenGeul.Office.exe'], [str(self.suite/'hostfxr.dll')],
                        [str(self.output/'OpenGeul.Office.exe')]):
            with self.subTest(command='wrong-image'):
                self.assertEqual(self.reject_launch(selected, command=command), [])
        self.assertEqual(self.reject_launch(selected, suite=self.output), [])

    def test_msi_and_wrong_core_fail_real_preparation_without_fallback(self):
        lock = self.harness/'suite/config/runtime.arm64.lock.json'
        original = lock.read_bytes()
        changed = json.loads(original)
        changed['runtime']['sourceCoreCommit'] = 'e'*40
        lock.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            self.prepared()
        lock.write_bytes(original)
        msi = ROOT/'suite/config/runtime.lock.json'
        (self.harness/'suite/config/runtime.lock.json').write_bytes(msi.read_bytes())
        (self.archive.parent/'OpenGeul-Office-engine-x64.zip').write_bytes(self.archive.read_bytes())
        with self.assertRaises(ValueError):
            self.prepared(architecture='x64')

    def test_nonprovider_payload_change_and_same_bytes_replacement_stale_the_epoch(self):
        selected = self.selected()
        target = self.suite/'worker/session.py'
        original = target.read_bytes()
        target.write_bytes(original+b'# changed\n')
        self.reject_launch(selected)
        target.write_bytes(original)
        selected = self.selected()
        replacement = target.with_name('replacement.py')
        replacement.write_bytes(original)
        replacement.replace(target)
        self.reject_launch(selected)

    def test_added_removed_and_case_aliased_entries_stale_the_complete_payload_epoch(self):
        for name in ('Office/program/extra.cache',):
            selected = self.selected()
            target = self.suite/name
            target.write_bytes(b'changed')
            self.reject_launch(selected)
            target.unlink()
        selected = self.selected()
        original = self.suite/'Office/program/soffice.exe'
        alias = original.with_name('SOFFICE.exe')
        temporary = original.with_name('case-epoch-original.tmp')
        original_bytes = original.read_bytes()
        self.assertFalse(temporary.exists())
        try:
            original.rename(temporary)
            temporary.rename(alias)
            self.reject_launch(selected)
        finally:
            if alias.exists():alias.rename(temporary)
            if temporary.exists():temporary.rename(original)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual([path.name for path in original.parent.iterdir()
            if path.name.casefold() == original.name.casefold()], ['soffice.exe'])
        selected = self.selected()
        (self.suite/'worker/session.py').unlink()
        self.reject_launch(selected)

    def test_case_alias_epoch_fixture_restores_original_executable_under_windows_semantics(self):
        original = self.suite/'Office/program/soffice.exe'
        original_bytes = original.read_bytes()
        real_write, real_unlink = Path.write_bytes, Path.unlink
        def target(path):
            return original if path.parent == original.parent and path.name == 'SOFFICE.exe' else path
        def write(path, raw):return real_write(target(path), raw)
        def unlink(path, *args, **kwargs):return real_unlink(target(path), *args, **kwargs)
        outcome = None
        with patch.object(Path, 'write_bytes', write), patch.object(Path, 'unlink', unlink):
            try:self.test_added_removed_and_case_aliased_entries_stale_the_complete_payload_epoch()
            except Exception as exc:outcome = type(exc).__name__
        self.assertIsNone(outcome, 'The alias fixture destroyed an input required by the next selection')
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual([path.name for path in original.parent.iterdir()
            if path.name.casefold() == original.name.casefold()], ['soffice.exe'])

    def test_provider_inventory_and_fixed_source_input_changes_do_not_self_authorize(self):
        for target in (self.suite/'Office/program/UAccCOM.dll', self.suite/'suite-inventory.json',
                       self.receipt, self.archive, self.harness/'suite/config/runtime.arm64.lock.json'):
            selected = self.selected()
            original = target.read_bytes()
            target.write_bytes(original+b'changed')
            self.reject_launch(selected)
            target.write_bytes(original)

    def test_linked_payload_and_input_ancestor_fail_closed(self):
        selected = self.selected()
        office = self.suite/'Office'
        office.rename(self.suite/'real-office')
        office.symlink_to(self.suite/'real-office', target_is_directory=True)
        self.reject_launch(selected)
        office.unlink()
        (self.suite/'real-office').rename(office)
        selected = self.selected()
        inputs = self.archive.parent
        inputs.rename(inputs.with_name('real-inputs'))
        inputs.symlink_to(inputs.with_name('real-inputs'), target_is_directory=True)
        self.reject_launch(selected)

    def test_preparation_rejects_actual_epoch_drift_after_real_gate(self):
        real = gate.admit_source_menu_runtime
        def drift(*args, **kwargs):
            admitted = real(*args, **kwargs)
            target = self.suite/'worker/session.py'
            target.write_bytes(target.read_bytes()+b'# changed\n')
            return admitted
        with patch.object(gate, 'admit_source_menu_runtime', drift), self.assertRaises(ValueError):
            self.prepared()

    def test_rewritten_inventory_after_real_gate_cannot_declare_new_executable_anchors(self):
        real = gate.admit_source_menu_runtime
        def drift(*args, **kwargs):
            admitted = real(*args, **kwargs)
            target = self.suite/'OpenGeul.Office.dll'
            target.write_bytes(target.read_bytes()+b'changed')
            inventory = gate.payload.create_inventory(self.suite, architecture='arm64')
            self.fixture.write_json('suite-inventory.json', inventory)
            return admitted
        with patch.object(gate, 'admit_source_menu_runtime', drift), \
                self.assertRaisesRegex(ValueError, 'inventory differs'):
            self.prepared()

    def test_unadmitted_inventory_bytes_are_rejected_before_interpretation(self):
        real = gate.admit_source_menu_runtime
        def drift(*args, **kwargs):
            admitted = real(*args, **kwargs)
            (self.suite/'suite-inventory.json').write_bytes(b'not inventory JSON')
            return admitted
        with patch.object(gate, 'admit_source_menu_runtime', drift), \
                self.assertRaisesRegex(ValueError, 'inventory differs'):
            self.prepared()

    def test_payload_epoch_has_separate_finite_file_entry_and_depth_bounds(self):
        module = self.implementation()
        for bound in ('_MAX_FILES', '_MAX_ENTRIES', '_MAX_DEPTH'):
            with self.subTest(bound=bound), patch.object(module, bound, 1), self.assertRaises(ValueError):
                self.prepared()

    def test_directory_drift_during_metadata_enumeration_is_rejected_before_gate(self):
        module = self.implementation()
        original = module.os.scandir
        worker = self.suite/'worker'
        class DriftingEntries:
            def __enter__(self):
                self.entries = original(worker)
                return self.entries.__enter__()
            def __exit__(self, *args):
                result = self.entries.__exit__(*args)
                (worker/'extra.py').write_bytes(b'# changed\n')
                return result
        def scan(path):
            return DriftingEntries() if path == worker else original(path)
        with patch.object(module.os, 'scandir', scan), \
                self.assertRaisesRegex(ValueError, 'directory changed'):
            self.prepared()

    def test_io_errors_are_terminal_before_pointer_or_popen(self):
        selected = self.selected()
        real = Path.lstat
        def lstat(path, *args, **kwargs):
            if path == self.suite/'worker/session.py':
                raise PermissionError('Synthetic access failure')
            return real(path, *args, **kwargs)
        with patch.object(Path, 'lstat', lstat):
            self.assertEqual(self.reject_launch(selected), [])

    def test_pending_registry_is_checked_again_immediately_before_popen(self):
        selected = self.selected()
        with patch.object(hit, '_active', object()):
            self.assertEqual(self.reject_launch(selected), [])
        with patch.object(hit, '_active', None):
            calls = self.reject_launch(selected, pointer=lambda *args, **kwargs: setattr(hit, '_active', object()))
            self.assertEqual(calls, ['pointer'])

    def test_pointer_stage_drift_cannot_reach_popen(self):
        selected = self.selected()
        def drift(*args, **kwargs):
            target = self.suite/'worker/session.py'
            target.write_bytes(target.read_bytes()+b'# changed\n')
        self.assertEqual(self.reject_launch(selected, pointer=drift), ['pointer'])

    def test_preparation_and_launch_preserve_absolute_finite_150_second_caps(self):
        for invalid in (True, float('nan'), float('inf'), time.monotonic()-1, time.monotonic()+151):
            with self.subTest(deadline='invalid'), self.assertRaises(ValueError):
                self.prepared(deadline=invalid)
        prepared = self.prepared()
        for invalid in (True, float('nan'), float('inf'), time.monotonic()-1, time.monotonic()+151):
            with self.subTest(deadline='invalid'), self.assertRaises(ValueError):
                self.selected(prepared, deadline=invalid)
        selected = self.selected(prepared, deadline=time.monotonic()+1)
        with patch.object(time, 'monotonic', lambda: selected.launch_deadline+1):
            self.assertEqual(self.reject_launch(selected), [])

    def test_source_deadline_expiring_during_pointer_is_not_renewed(self):
        selected = self.selected(deadline=time.monotonic()+1)
        now = [time.monotonic()]
        def late(*args, **kwargs): now[0] = selected.launch_deadline+1
        with patch.object(time, 'monotonic', lambda: now[0]):
            self.assertEqual(self.reject_launch(selected, pointer=late), ['pointer'])

    def test_deadline_is_rechecked_after_final_pending_read_before_popen(self):
        selected = self.selected(deadline=time.monotonic()+1)
        now, after_pointer = [time.monotonic()], [False]
        def pending():
            if after_pointer[0]: now[0] = selected.launch_deadline+1
            return None
        def pointer(*args, **kwargs): after_pointer[0] = True
        with patch.object(time, 'monotonic', lambda: now[0]), \
                patch.object(hit, 'pending_msaa_hit', pending):
            self.assertEqual(self.reject_launch(selected, pointer=pointer), ['pointer'])

    def test_first_probe_uses_current_action_budget_after_old_launch_deadline(self):
        selected = self.selected(deadline=time.monotonic()+1)
        process = self.launch(selected)
        now = selected.launch_deadline+200
        built = []
        def build(context):
            built.append(context)
            return SimpleNamespace(source_selection=context)
        with patch.object(time, 'monotonic', lambda: now):
            probe = self.implementation().selected_native_menu_probe(process, now+5,
                time.monotonic, build=build)
        self.assertIs(probe.source_selection, selected)
        self.assertEqual(built, [selected])

    def test_first_probe_rechecks_inventory_executables_providers_and_pending(self):
        selected = self.selected()
        process = self.launch(selected)
        built = []
        def build(context):
            built.append('build')
            return SimpleNamespace(source_selection=context)
        target = self.suite/'OpenGeul.Office.dll'
        target.write_bytes(target.read_bytes()+b'changed')
        with self.assertRaises(ValueError):
            self.implementation().selected_native_menu_probe(process,time.monotonic()+5,time.monotonic,build=build)
        self.assertEqual(built, [])

    def test_probe_expiry_or_pending_started_by_constructor_cannot_reach_caller(self):
        selected = self.selected()
        process = self.launch(selected)
        module = self.implementation()
        built = []
        for deadline in (time.monotonic()-1, time.monotonic()+6):
            with self.subTest(deadline='invalid'), self.assertRaises(ValueError):
                module.selected_native_menu_probe(process,deadline,time.monotonic,
                    build=lambda context: built.append('build'))
        self.assertEqual(built, [])
        def build(context):
            hit._active = object()
            return SimpleNamespace(source_selection=context)
        with patch.object(hit, '_active', None), self.assertRaises(ValueError):
            module.selected_native_menu_probe(process,time.monotonic()+5,time.monotonic,build=build)

    def test_probe_deadline_is_rechecked_after_final_pending_read(self):
        selected = self.selected()
        process = self.launch(selected)
        now, after_build = [time.monotonic()], [False]
        deadline = now[0]+5
        def pending():
            if after_build[0]: now[0] = deadline+1
            return None
        def build(context):
            after_build[0] = True
            return SimpleNamespace(source_selection=context)
        with patch.object(time, 'monotonic', lambda: now[0]), \
                patch.object(hit, 'pending_msaa_hit', pending), self.assertRaises(ValueError):
            self.implementation().selected_native_menu_probe(process,deadline,time.monotonic,build=build)

    def test_custom_probe_must_hold_identical_selection_and_default_off_is_unchanged(self):
        selected = self.selected()
        process = self.launch(selected)
        module = self.implementation()
        build = lambda context: SimpleNamespace(source_selection=context)
        supplied = build(selected)
        self.assertIs(module.selected_native_menu_probe(process,time.monotonic()+5,time.monotonic,
            build=build,supplied=supplied),supplied)
        for invalid in (SimpleNamespace(), build(self.selected(selected.prepared)), build(True)):
            with self.subTest(probe='mixed'), self.assertRaises(ValueError):
                module.selected_native_menu_probe(process,time.monotonic()+5,time.monotonic,
                    build=build,supplied=invalid)
        legacy = SimpleNamespace()
        self.assertIs(module.selected_native_menu_probe(SimpleNamespace(), 0, None,
            build=lambda context: legacy), legacy)

    def test_mixed_legacy_markers_or_unknown_pending_cannot_build_selected_probe(self):
        selected = self.selected()
        process = self.launch(selected)
        module = self.implementation()
        built = []
        for key,value in (('opengeul_native_menu_point_profile',True),
                          ('opengeul_native_menu_point_profile_version',2),
                          ('opengeul_native_menu_identity_diagnostic',3)):
            setattr(process,key,value)
            with self.subTest(marker='legacy'),self.assertRaises(ValueError):
                module.selected_native_menu_probe(process,time.monotonic()+5,time.monotonic,
                    build=lambda selection: built.append('build'))
            delattr(process,key)
        with patch.object(hit,'pending_msaa_hit',side_effect=OSError('Synthetic unknown registry')), \
                self.assertRaises(ValueError):
            module.selected_native_menu_probe(process,time.monotonic()+5,time.monotonic,
                build=lambda selection: built.append('build'))
        self.assertEqual(built, [])


class SourceEpochNumericObservationTests(unittest.TestCase):
    def setUp(self):
        self.owner = SourceMenuSelectionTests(methodName='test_prepares_actual_bare_gate_context_and_freezes_contexts')
        self.owner.setUp()
        self.addCleanup(self.owner.doCleanups)
        self.api = self.owner.implementation()
        self.prepared = self.owner.prepared()

    def summary(self, error, prepared=None):
        reader = getattr(self.api, '_source_epoch_failure_summary', None)
        self.assertTrue(callable(reader), 'Numeric epoch failure reader is missing')
        return reader(error, self.prepared if prepared is None else prepared)

    def payload_failure(self, current, *, clock=None):
        with patch.object(self.api, '_payload_epoch', return_value=tuple(current)) as read, \
                patch.object(self.api, '_input_epoch', side_effect=AssertionError('Payload mismatch must short circuit')):
            context = patch.object(self.api.time, 'monotonic', return_value=clock) if clock is not None else patch.object(self.api, '_pending_zero', wraps=self.api._pending_zero)
            with context, self.assertRaises(ValueError) as caught:
                self.api._unchanged_epochs(self.prepared, 1.0 if clock is not None else time.monotonic()+5)
        self.assertEqual(read.call_count, 1)
        self.assertIs(type(caught.exception), ValueError)
        self.assertEqual(caught.exception.args, ('Source menu epoch changed; an explicit new preparation is required',))
        return caught.exception

    def test_payload_six_fields_and_ancestor_masks_preserve_the_original_refusal(self):
        baseline = self.prepared.payload_epoch
        index = next(i for i, row in enumerate(baseline) if len(row.identity)==6 and not row.identity[2] & 0o040000)
        for field, mask in enumerate((1,2,4,8,16,32)):
            current = list(baseline);values = list(current[index].identity);values[field] += 1
            current[index] = self.api._FileEpoch(current[index].path, tuple(values))
            with self.subTest(field=field):
                summary = self.summary(self.payload_failure(current))
                self.assertEqual((summary['branchCode'],summary['countsKnown'],summary['changedCount']), (1,1,1))
                self.assertEqual(summary['rows'], [dict(changeCode=3,roleCode=4,baselineOrdinal=index+1,fieldMask=mask,prefixCode=0)])
        current = list(baseline);values = list(current[0].identity);values[2] += 1
        current[0] = self.api._FileEpoch(current[0].path, tuple(values))
        self.assertEqual(self.summary(self.payload_failure(current))['rows'], [dict(changeCode=3,roleCode=1,baselineOrdinal=1,fieldMask=4,prefixCode=0)])

    def test_input_leaf_and_ancestor_changes_are_not_hidden_by_equal_payload(self):
        from dataclasses import replace
        baseline = self.prepared.input_epoch
        for ancestor in (False,True):
            current = list(baseline);state = current[1].state
            if ancestor:
                ancestors = list(state.ancestors);values = list(ancestors[0]);values[1] += 1;ancestors[0] = tuple(values)
                state = replace(state, ancestors=tuple(ancestors));role, mask = 22,2
            else:
                values = list(state.file);values[4] += 1;state = replace(state,file=tuple(values));role,mask = 12,16
            current[1] = replace(current[1],state=state)
            with self.subTest(ancestor=ancestor), patch.object(self.api,'_payload_epoch',return_value=self.prepared.payload_epoch) as payload, patch.object(self.api,'_input_epoch',return_value=tuple(current)) as inputs, self.assertRaises(ValueError) as caught:
                self.api._unchanged_epochs(self.prepared,time.monotonic()+5)
            summary = self.summary(caught.exception)
            self.assertEqual((payload.call_count,inputs.call_count,summary['branchCode'],summary['changedCount']),(1,1,2,1))
            self.assertEqual((summary['rows'][0]['roleCode'],summary['rows'][0]['fieldMask']),(role,mask))

    def test_added_removed_order_and_bounded_samples_are_distinguished(self):
        baseline = self.prepared.payload_epoch
        extra = [self.api._FileEpoch(str(self.owner.suite/('new-'+str(i))), (1,2,0o100644,3,4,5)) for i in range(20)]
        summary = self.summary(self.payload_failure(list(baseline)+extra))
        self.assertEqual((summary['addedCount'],summary['removedCount'],summary['sampleTruncated'],len(summary['rows'])),(20,0,1,16))
        self.assertTrue(all(row==dict(changeCode=1,roleCode=4,baselineOrdinal=0,fieldMask=0,prefixCode=0) for row in summary['rows']))
        summary = self.summary(self.payload_failure(baseline[1:]))
        self.assertEqual((summary['removedCount'],summary['rows'][0]['baselineOrdinal']),(1,1))
        current = list(baseline);current[0],current[1] = current[1],current[0]
        summary = self.summary(self.payload_failure(current))
        self.assertEqual((summary['orderChanged'],summary['addedCount'],summary['removedCount'],summary['changedCount']),(1,0,0,0))

    def test_comparison_deadline_never_replaces_or_renews_the_epoch_rejection(self):
        current = list(self.prepared.payload_epoch);current.reverse()
        summary = self.summary(self.payload_failure(current,clock=2.0))
        self.assertEqual((summary['comparisonStatusCode'],summary['countsKnown'],summary['rows']),(2,0,[]))

    def test_carrier_is_bound_to_exact_exception_and_actual_prepared_and_has_constant_repr(self):
        import copy
        current = list(self.prepared.payload_epoch);current.reverse();error = self.payload_failure(current)
        summary = self.summary(error)
        self.assertEqual(summary['schemaVersion'],2)
        self.assertIsNone(self.summary(copy.copy(error)))
        self.assertIsNone(self.summary(ValueError(*error.args)))
        other = self.owner.prepared()
        self.assertIsNone(self.summary(error,other))
        self.assertIsNone(self.summary(error,object()))
        carrier = getattr(error,'_source_epoch_observation',None)
        self.assertEqual(repr(carrier),'<source-epoch-observation>')
        summary['rows'].append(dict(changeCode=1,roleCode=4,baselineOrdinal=0,fieldMask=0))
        self.assertEqual(self.summary(error)['rows'],[])

    def test_epoch_read_error_is_preserved_without_fabricating_a_difference(self):
        failure = OSError('Synthetic epoch read failure')
        with patch.object(self.api,'_payload_epoch',side_effect=failure), patch.object(self.api,'_input_epoch',side_effect=AssertionError('No later reads')), self.assertRaises(OSError) as caught:
            self.api._unchanged_epochs(self.prepared,time.monotonic()+5)
        self.assertIs(caught.exception,failure)
        self.assertIsNone(self.summary(failure))

    def test_input_ancestor_structure_is_numeric_and_never_reads_files_again(self):
        from dataclasses import replace
        current = list(self.prepared.input_epoch)
        current[1] = replace(current[1],state=replace(current[1].state,ancestors=current[1].state.ancestors[:-1]))
        with patch.object(self.api,'_payload_epoch',return_value=self.prepared.payload_epoch), \
                patch.object(self.api,'_input_epoch',return_value=tuple(current)), \
                patch.object(Path,'stat',side_effect=AssertionError('No diagnostic stat')), \
                patch.object(Path,'lstat',side_effect=AssertionError('No diagnostic lstat')), \
                patch.object(gate,'_hash_file',side_effect=AssertionError('No diagnostic hash')), \
                self.assertRaises(ValueError) as caught:
            self.api._unchanged_epochs(self.prepared,time.monotonic()+5)
        summary = self.summary(caught.exception)
        self.assertEqual((summary['branchCode'],summary['structureChanged'],summary['removedCount']),(2,1,1))
        self.assertEqual((summary['rows'][0]['changeCode'],summary['rows'][0]['roleCode']),(2,22))
        self.assertEqual(set(summary),{'schemaVersion','branchCode','comparisonStatusCode','baselineCount','currentCount','countsKnown','addedCount','removedCount','changedCount','orderChanged','structureChanged','sampleTruncated','rows'})
        self.assertTrue(all(type(value) is int for key,value in summary.items() if key!='rows'))

    def test_directory_prefixes_are_fixed_component_matches_on_sampled_paths_only(self):
        import stat
        baseline = self.prepared.payload_epoch
        names = (('Office/share/uno_packages/cache',1),
            ('Office/share/uno_packages/cache/child',1),('Office/program/child',2),
            ('Office/share/extensions/child',3),('Office/share/registry/child',4),
            ('worker/child',5),('Office/share/uno_packages/cache-other',0),
            ('Office/program-other',0),('other/Office/program',0),('worker-other',0))
        extra = [self.api._FileEpoch(str(self.owner.suite/name), (1,2,stat.S_IFDIR|0o755,0,4,5))
            for name,_ in names]
        file = self.api._FileEpoch(str(self.owner.suite/'Office/program/file'), (1,2,stat.S_IFREG|0o644,3,4,5))
        current = baseline+tuple(extra)+(file,)
        ticks = []
        def clock():ticks.append(1);return 0.0
        with patch.object(Path,'stat',side_effect=AssertionError('No diagnostic stat')), \
                patch.object(Path,'lstat',side_effect=AssertionError('No diagnostic lstat')), \
                patch.object(Path,'resolve',side_effect=AssertionError('No diagnostic resolve')), \
                patch.object(Path,'open',side_effect=AssertionError('No diagnostic read')), \
                patch.object(self.api.os,'scandir',side_effect=AssertionError('No diagnostic scan')), \
                patch.object(gate,'_hash_file',side_effect=AssertionError('No diagnostic hash')), \
                patch.object(self.api.time,'monotonic',clock):
            error = self.api._source_epoch_exception(self.prepared,1,current,1.0)
            summary = self.summary(error)
        self.assertEqual(summary['schemaVersion'],2)
        self.assertEqual([row['prefixCode'] for row in summary['rows']], [code for _,code in names]+[0])
        self.assertEqual([row['roleCode'] for row in summary['rows']], [3]*len(names)+[4])
        self.assertEqual((summary['addedCount'],summary['removedCount'],summary['changedCount']), (len(names)+1,0,0))
        self.assertEqual(len(ticks),2*(len(baseline)+len(current))+1)
        classify=self.api._epoch_directory_prefix
        self.assertEqual(classify(self.prepared,str(self.owner.suite/'Office/program').replace('/','\\'),3),2)
        for path in (str(self.owner.suite)+'-other/Office/program',
                str(self.owner.suite)+'/../Office/program',str(self.owner.suite)+'/Office//program'):
            self.assertEqual(classify(self.prepared,path,3),0)
        self.assertEqual(classify(self.prepared,str(self.owner.suite),2),0)

    def test_prefix_keeps_baseline_ordinals_masks_removals_and_sixteen_sample_cap(self):
        baseline = self.prepared.payload_epoch
        index = next(i for i,row in enumerate(baseline) if row.path==str(self.owner.suite/'Office/program'))
        current = list(baseline);identity = list(current[index].identity);identity[4] += 1
        current[index] = self.api._FileEpoch(current[index].path,tuple(identity))
        summary = self.summary(self.payload_failure(current))
        self.assertEqual(summary['rows'],[dict(changeCode=3,roleCode=3,baselineOrdinal=index+1,fieldMask=16,prefixCode=2)])
        summary = self.summary(self.payload_failure(baseline[:index]+baseline[index+1:]))
        self.assertEqual(summary['rows'],[dict(changeCode=2,roleCode=3,baselineOrdinal=index+1,fieldMask=0,prefixCode=2)])
        classifier = getattr(self.api,'_epoch_directory_prefix',None)
        self.assertTrue(callable(classifier),'Directory prefix classifier is missing')
        extra = [self.api._FileEpoch(str(self.owner.suite/('worker/extra-'+str(i))), (1,2,0o040755,0,4,5)) for i in range(20)]
        with patch.object(self.api,'_epoch_directory_prefix',wraps=classifier) as classified:
            summary = self.summary(self.payload_failure(list(baseline)+extra))
        self.assertEqual((summary['addedCount'],summary['sampleTruncated'],len(summary['rows']),classified.call_count),(20,1,16,16))
        self.assertTrue(all(row['prefixCode']==5 for row in summary['rows']))

    def test_epoch_summary_versions_have_separate_closed_row_shapes(self):
        from dataclasses import replace
        baseline = self.prepared.payload_epoch
        index = next(i for i,row in enumerate(baseline) if row.path==str(self.owner.suite/'Office/program'))
        current = list(baseline);identity = list(current[index].identity);identity[4] += 1
        current[index] = self.api._FileEpoch(current[index].path,tuple(identity))
        error = self.payload_failure(current)
        carrier = error._source_epoch_observation
        self.assertEqual(self.summary(error)['schemaVersion'],2)
        fields = {'changeCode','roleCode','baselineOrdinal','fieldMask'}
        self.assertEqual(set(self.summary(error)['rows'][0]),fields|{'prefixCode'})
        legacy = replace(carrier,values=(1,)+carrier.values[1:],rows=tuple(row[:4] for row in carrier.rows))
        error._source_epoch_observation=legacy
        self.assertEqual(self.summary(error)['schemaVersion'],1)
        self.assertEqual(set(self.summary(error)['rows'][0]),fields)
        invalid = (replace(carrier,rows=legacy.rows),replace(legacy,rows=carrier.rows),
            replace(carrier,rows=(carrier.rows[0]+(0,),)),
            *(replace(carrier,rows=(carrier.rows[0][:-1]+(value,),)) for value in (True,-1,6)),
            replace(carrier,rows=((3,4,index+1,16,2),)),
            replace(carrier,rows=((3,2,index+1,16,2),)),
            replace(carrier,values=(2,2)+carrier.values[2:]))
        for observation in invalid:
            error._source_epoch_observation=observation
            self.assertIsNone(self.summary(error))
        error._source_epoch_observation=carrier
        self.assertIsNotNone(self.summary(error))


if __name__ == '__main__':
    unittest.main()
