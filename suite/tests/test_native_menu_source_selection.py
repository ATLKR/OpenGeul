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


if __name__ == '__main__':
    unittest.main()
