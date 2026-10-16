"""Twenty fresh Writer input diagnostics, alternating queue observation and control.

Uses the original lifecycle new_saveas_cancel action and unchanged Case.edit.
Instrumentation can affect scheduling; controls receive no hook or SendInput
wrapper. These diagnostic results never substitute for the Suite acceptance gate.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import lifecycle_smoke as lifecycle
import native_accessibility as accessible
from keyboard_delivery import DeliveryObserver, ObserverLibrary
from korean_ime_smoke import require_readiness
from startup_smoke import EngineProcessWitness


def trial_plan():
    return [{'case': 'input-' + str(index + 1).zfill(2) + ('-observed' if index % 2 == 0 else '-control'),
             'instrumented': index % 2 == 0, 'trial': index + 1} for index in range(20)]


def analyze_delivery(receipt):
    """Locate an observed boundary; never infer model insertion from API counts."""
    expected = receipt['marker']
    calls = receipt['sendInputCalls']
    pairs = [row for call in calls for row in call['events'] if row.get('type') == 1 and row.get('flags', 0) & 4]
    expected_pairs = [row for char in expected for row in (
        {'type': 1, 'vk': 0, 'scan': ord(char), 'flags': 4},
        {'type': 1, 'vk': 0, 'scan': ord(char), 'flags': 6})]
    pairs = [{key: row[key] for key in ('type', 'vk', 'scan', 'flags')} for row in pairs]
    pair_exact = bool(calls) and all(call['requested'] == call['inserted'] for call in calls) and pairs == expected_pairs
    removed = [row for row in receipt['messages'] if row['remove'] is True]
    chars = [row for row in removed if row['message'] == 0x102]
    units = [row['wparam'] for row in chars]
    text = ''.join(chr(value) for value in units if 0 <= value <= 0x10ffff)
    queue_exact = units == [ord(char) for char in expected]
    model_exact = receipt.get('model', {}).get('bodyText') == expected
    owned = bool(removed) and all((row['pid'], row['tid']) == (receipt['officePid'], receipt['editorTid']) for row in removed)
    english = bool(chars) and all(row['layout'] & 0xffff == 0x0409 for row in chars) \
        and receipt['focusAfter']['layout'] & 0xffff == 0x0409
    boundary = 'exact-model-observed' if model_exact else ('dequeued-characters-match-model-differs-order-unresolved' if queue_exact
        else 'character-queue-retrieval-or-earlier' if pair_exact else 'sendinput-insertion')
    return {'sendInputPairsExact': pair_exact, 'dequeuedCharactersExact': queue_exact,
            'modelExact': model_exact, 'ownedMessageIdentity': owned, 'englishLayout': english,
            'boundedComplete': receipt.get('overflow') is False and receipt.get('publishedMessageCount', len(receipt['messages']))
                == receipt.get('reservedMessageCount', len(receipt['messages'])),
            'dequeuedText': text, 'dequeuedCodeUnits': units,
            'removedPacketKeydownCount': sum(row['message'] == 0x100 and row['wparam'] == 0xe7 for row in removed),
            'removedPacketKeyupCount': sum(row['message'] == 0x101 and row['wparam'] == 0xe7 for row in removed),
            'characterFocusHwnds': sorted({row['focus'] for row in chars}),
            'boundary': boundary,
            'limitation': 'Queue retrieval does not prove VCL logical focus, KeyInput handling, or insertion; receipt-end events can follow the model read.'}


@contextmanager
def retained_generation(child, pid, expected_image, witness, *, expected_creation=None):
    """Keep the original generation handle across input and its model snapshot."""
    original = EngineProcessWitness(pid)
    checked = after = None
    primary = None
    try:
        creation = original.creation_time if expected_creation is None else expected_creation
        assert original.creation_time == creation and not original.exited(0), 'Owned process generation changed before observation'
        api, checked = accessible._owned_process(child, pid, creation, expected_image)
        witness.update(officePid=pid, officeCreationTime=creation, childHwnd=child,
                       expectedImage=str(expected_image), retainedProcessHandle=bool(original.handle),
                       imageVerified=True, creationTimeVerified=True, hwndVerifiedBefore=True)
        yield original
    except BaseException as exc:
        primary = exc
        raise
    finally:
        secondary = None
        if checked is not None:
            try:
                assert not original.exited(0), 'Owned process generation exited during observation'
                _, after = accessible._owned_process(child, pid, original.creation_time, expected_image)
                assert api.user.IsWindow(child) and api.pid(child) == pid, 'Owned HWND generation changed during observation'
                witness.update(hwndVerifiedAfter=True, generationVerifiedAfter=True)
            except Exception as exc:
                witness['verificationAfterError'] = type(exc).__name__ + ': ' + str(exc)
                secondary = exc
        for process in (after, checked, original):
            if process is None: continue
            try:
                process.close()
            except Exception as exc:
                witness['cleanupError'] = type(exc).__name__ + ': ' + str(exc)
                if secondary is None: secondary = exc
        if primary is None and secondary is not None: raise secondary


def require_model_witness(result, pid, child, creation, expected_image):
    assert (result.get('officePid'), result.get('childHwnd'), result.get('officeCreationTime')) == (pid, child, creation), 'Model snapshot belongs to a different process generation or HWND'
    assert Path(result.get('expectedImage', '')).resolve() == expected_image.resolve(), 'Model snapshot belongs to a different process image'
    assert result.get('readOnlyObservation') is True, 'Read-only model observation is missing'
    witness = result.get('witness', {})
    assert (witness.get('officePid'), witness.get('childHwnd'), witness.get('officeCreationTime')) == (pid, child, creation), 'Snapshot witness is bound to a different process generation'
    assert all(witness.get(key) is True for key in ('retainedProcessHandle', 'imageVerified', 'creationTimeVerified',
        'hwndVerifiedBefore', 'hwndVerifiedAfter', 'generationVerifiedAfter')), 'Model snapshot lacks retained generation verification'
    return result


def capture_command(command, folder, stem, *, cwd, timeout):
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        (folder / (stem + '-stdout.log')).write_bytes(getattr(exc, 'stdout', None) or b'')
        (folder / (stem + '-stderr.log')).write_bytes(getattr(exc, 'stderr', None) or b'')
        raise
    (folder / (stem + '-stdout.log')).write_bytes(result.stdout)
    (folder / (stem + '-stderr.log')).write_bytes(result.stderr)
    result.check_returncode()
    return result


def observe_model(suite, child, pid, folder, generation):
    # Reuse the exact retained process handle and the established native parser.
    # No WMI, PID-only command-line lookup, or new process enumeration occurs.
    pipe = accessible.private_pipe(accessible._command_line(generation))
    expected_image = suite / 'Office/program/soffice.bin'
    target = folder / 'model-before-picker.json'
    capture_command([str(suite / 'Office/program/python.exe'), str(Path(__file__).resolve()),
        '--suite', str(suite), '--output', str(target), '--observe-model', '--pipe', pipe,
        '--office-pid', str(pid), '--child-hwnd', str(child), '--creation-time', str(generation.creation_time),
        '--expected-image', str(expected_image)], folder, 'model-before-picker', cwd=suite, timeout=25)
    return require_model_witness(json.loads(target.read_text(encoding='utf-8')), pid, child,
                                 generation.creation_time, expected_image)


def read_existing_model(pipe, pid, child, creation, expected_image, output):
    """Bundled Python only: connect once and read the existing exact embedded frame."""
    import uno
    assert type(creation) is int and creation > 0, 'The original process creation identity is required'
    witness = {}
    with retained_generation(child, pid, expected_image, witness, expected_creation=creation) as generation:
        assert accessible.private_pipe(accessible._command_line(generation)) == pipe, 'UNO pipe differs from the retained exact process command line'
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', local)
        context = resolver.resolve('uno:pipe,name=' + pipe + ';urp;StarOffice.ComponentContext')
        desktop = context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', context)
        frames = desktop.getFrames()
        assert frames.getCount() <= 8, 'Owned engine has unexpectedly many frames'
        matches = []
        for index in range(frames.getCount()):
            frame = frames.getByIndex(index)
            peer = frame.getContainerWindow()
            if peer is not None and int(peer.getWindowHandle((), 1)) == child:
                matches.append(frame)
        assert len(matches) == 1, 'Read-only UNO observation did not find the exact owned embedded frame'
        frame = matches[0]
        controller = frame.getController()
        assert controller is not None and controller.getFrame() == frame, 'Read-only UNO controller belongs to another frame'
        model = controller.getModel()
        assert model.supportsService('com.sun.star.text.TextDocument'), 'Observed model is not Writer'
        result = {'readOnlyObservation': True, 'officePid': pid, 'childHwnd': child, 'pipe': pipe,
                  'officeCreationTime': creation, 'expectedImage': str(expected_image), 'witness': witness,
                  'bodyText': model.getText().getString(), 'modified': bool(model.isModified()),
                  'documentUrl': model.getURL(), 'frameName': frame.getName()}
        assert controller.getFrame() == frame and int(frame.getContainerWindow().getWindowHandle((), 1)) == child, 'Owned live frame changed during the model read'
    # No controller activation, cursor move, dispatch, store, setString or close.
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


class ProbeCase(lifecycle.Case):
    def __init__(self, *args, plan, library, **kwargs):
        self.plan, self.library, self.edits = plan, library, 0
        super().__init__(*args, **kwargs)
        self.record.update(diagnosticOnly=True, deliverable=False, trial=plan['trial'], instrumented=plan['instrumented'])

    def edit(self, hwnd, child, marker):
        self.edits += 1
        if self.edits != 1:
            return super().edit(hwnd, child, marker)
        receipt = {'marker': marker, 'instrumented': self.plan['instrumented'], 'officePid': self.api.pid(child)}
        self.record['firstInput'] = receipt
        witness = receipt['processWitness'] = {}
        with retained_generation(child, receipt['officePid'], self.suite / 'Office/program/soffice.bin', witness) as generation:
            witness['retainedFromBeforeInput'] = True
            receipt['officeCreationTime'] = generation.creation_time
            self.first_edit(hwnd, child, marker, receipt, generation)

    def first_edit(self, hwnd, child, marker, receipt, generation):
        observer = None
        try:
            if self.plan['instrumented']:
                observer = DeliveryObserver(self.library, self.api, hwnd, child, receipt['officePid'])
                receipt['focusBefore'] = observer.snapshot()
                with observer.capture_sendinput():
                    super().edit(hwnd, child, marker)
                receipt['focusAfter'] = observer.snapshot()
            else:
                # Exact original method, no hook, wrapper, added delay or model
                # reads until it has completed its original dirty-title check.
                super().edit(hwnd, child, marker)
                tid = int(self.api.user.GetWindowThreadProcessId(child, None))
                self.api.user.GetKeyboardLayout.argtypes = [W.DWORD]
                self.api.user.GetKeyboardLayout.restype = W.HANDLE
                receipt['editorTid'] = tid
                receipt['focusAfter'] = {'focus': self.api.require_editor_focus(hwnd, child),
                    'layout': int(self.api.user.GetKeyboardLayout(tid) or 0), 'pid': receipt['officePid'], 'tid': tid}
            self.record['stage'] = 'read-only-model-before-first-picker'
            # Keep the thread hook alive through the model read, so a character
            # serviced after Case.edit returns is still visible in the receipt.
            receipt['model'] = observe_model(self.suite, child, receipt['officePid'], self.folder, generation)
        finally:
            if observer is not None:
                primary = sys.exc_info()[1]
                secondary = None
                try:
                    receipt.update(observer.receipt())
                except Exception as exc:
                    receipt['observerReceiptError'] = type(exc).__name__ + ': ' + str(exc)
                    secondary = exc
                try:
                    observer.close()
                except Exception as exc:
                    receipt['observerCleanupError'] = type(exc).__name__ + ': ' + str(exc)
                    if secondary is None: secondary = exc
                if primary is None and secondary is not None: raise secondary
        receipt['modelExact'] = receipt['model']['bodyText'] == marker
        assert receipt['model']['documentUrl'] == '', 'First marker model is not the fresh unsaved Writer document'
        assert receipt['model']['modified'] is True, 'First marker did not modify the existing Writer model'
        assert receipt['focusAfter']['layout'] & 0xffff == 0x0409, 'Original lifecycle input did not retain the English thread layout'
        if self.plan['instrumented']:
            receipt['analysis'] = analyze_delivery(receipt)
        lifecycle.native.write_result(self.output, self.name, self.record)
        assert receipt['modelExact'], 'Actual pre-picker Writer UNO body differs from the exact original marker; no input is retried'
        if self.plan['instrumented']:
            required = ('sendInputPairsExact', 'dequeuedCharactersExact', 'ownedMessageIdentity', 'englishLayout', 'boundedComplete')
            assert all(receipt['analysis'][key] for key in required), 'Owned input diagnostic boundary is incomplete: ' + str(receipt['analysis'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', required=True, type=Path)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--readiness', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--trials', type=int, choices=(20,), default=20)
    parser.add_argument('--observe-model', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--pipe', help=argparse.SUPPRESS)
    parser.add_argument('--office-pid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--child-hwnd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--creation-time', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--expected-image', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    assert os.name == 'nt' and __debug__, 'Actual assertion-enabled Windows execution is required'
    if args.observe_model:
        assert args.expected_image.resolve() == (args.suite / 'Office/program/soffice.bin').resolve(), 'Read-only model expected image differs from the supplied Suite'
        return read_existing_model(args.pipe, args.office_pid, args.child_hwnd, args.creation_time, args.expected_image, args.output)
    assert args.fixtures is not None and args.readiness is not None, 'Actual generated fixtures and Microsoft Korean IME readiness are required'
    for path in (args.suite, args.fixtures, args.readiness, args.output): lifecycle.unlinked(path)
    suite, fixtures, output = (path.resolve() for path in (args.suite, args.fixtures, args.output))
    assert suite.is_dir() and fixtures.is_dir(), 'Fresh built Suite and engine fixtures are required'
    assert suite not in output.parents and fixtures not in output.parents and suite != output and fixtures != output, 'Diagnostics must be outside payload and fixtures'
    readiness = require_readiness(json.loads(args.readiness.read_text(encoding='utf-8-sig')))
    output.mkdir(parents=True, exist_ok=False)
    (output / 'fixtures').mkdir()
    compiler = output / 'observer'
    compiler.mkdir()
    provenance = {'diagnosticOnly': True, 'deliverable': False, 'expectedTrials': args.trials,
        'plan': trial_plan(), 'observerEffect': 'The hook and in-memory SendInput wrapper can change scheduling; alternating controls have neither.',
        'inputPath': 'unchanged lifecycle.Case.edit, default pywinauto Unicode VK_PACKET, pause=.025',
        'originalEditSha256': hashlib.sha256(inspect.getsource(lifecycle.Case.edit).encode('utf-8')).hexdigest(),
        'readiness': readiness, 'sourceSha': os.environ.get('GITHUB_SHA'),
        'sources': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                    for name in ('lifecycle_input_probe.py', 'keyboard_delivery.py', 'lifecycle_smoke.py', 'windows_smoke.py')},
        'workers': {name: hashlib.sha256((suite / 'worker' / name).read_bytes()).hexdigest()
                    for name in ('native.py', 'native_windows.py', 'native_diagnostics.py')}}
    (output / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    library = ObserverLibrary(compiler)  # Before constructing or launching ANY Case.
    cases = [(plan['case'], lambda plan=plan: ProbeCase(suite, fixtures, output, plan['case'],
                blank=True, plan=plan, library=library).run(lifecycle.new_saveas_cancel)) for plan in trial_plan()]
    records = lifecycle.native.collect_cases(cases, output)
    result = {'kind': 'native-lifecycle-input-diagnostic', 'diagnosticOnly': True, 'deliverable': False,
        'expectedTrialCount': 20, 'completedTrialCount': len(records), 'observer': library.identity,
        'success': len(records) == 20 and all(row.get('success') is True for row in records),
        'passedTrialCount': sum(row.get('success') is True for row in records), 'tests': records,
        'acceptanceGateReplaced': False}
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
