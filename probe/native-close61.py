"""Observe the original source61 native close selector; never qualify its payload."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

SOURCE = '9b666ea2ac3210a6219ca9d78b9da96719b43856'
SOURCE_RUN = 38161639847
EDITOR_SHA = '6087e550b367adafecd03a08e72132390250da4e31283e4008bd88048e7ab6db'
EDITOR_BYTES = 33641472
MAX_METADATA_BYTES = 16 * 1024
MAX_RECORDED_WINDOWS = 16
MAX_EXAMINED_WINDOWS = 256
FROZEN_HELPERS = {
    "e2e/password/native.py": "9cf0b02d099f3e999096c671eefb00b04d7c9441d091e0b61394a6e51b2faab9",
    "e2e/driver.py": "2421a78683c8e445cb6b915db8d3c94c35c7fa027267597b052adb4d11347025",
    "e2e/native_controls.py": "c972fb0acbcd30b6fa9c703bd5c236be4d69f95dab6dcf9d08d0030b2acbe705",
    "e2e/uia_snapshot.py": "9a395c918e27f0c427649e0dcbf262c02fbb4002ec611f114bcf9f4363c491bc",
    "e2e/webview_debug.py": "854cda2d89c6c32035137d24c0b1aa9148cf8d4dd4cf54f846291f083ec5112b",
    "e2e/hwpx_oracle.py": "f34c85b5469943f57e5616a0b259c4c1ec876f7b4780de8953fd55809c37c342",
    "e2e/password/generate-password-fixtures.mjs": "8101d2c3a50d19df69262e7ad1bbc89f9493d057a1affa847075cc3a076d4a55",
    "e2e/password/verify-password-fixtures.py": "ed18ff339a462a7052b1ee68a8f60c6ce1115cad0b78b26b237c76f8b3cd4fd6"
}


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path, limit=64*1024):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
            'Expected bounded regular metadata')
    def unique(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'Duplicate metadata key')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def verify_source_binding(source, engine):
    require(source.get('sourceCommit') == SOURCE
            and type(source.get('sourceRun')) is int and source['sourceRun'] == SOURCE_RUN
            and source.get('editorSha256') == EDITOR_SHA,
            'Frozen source61 transport binding differs')
    require(source.get('qualification') == 'native-close-diagnostic-only'
            and source.get('diagnosticOnly') is True and source.get('qualifiedPackage') is False,
            'Transport must retain diagnostic-only qualification scope')
    require(isinstance(source.get('wasmRebuild'), dict) and source['wasmRebuild']
            and engine.get('qualification') == 'final-source-bound'
            and engine.get('provenance') == source.get('wasmRebuild'),
            'Synthetic fixture engine differs from frozen Editor61')


def base_result():
    return {'scope': 'source61-native-close-selector-diagnostic-only', 'qualification': False,
            'sourceQualified': False, 'fullPasswordSuiteQualified': False,
            'sourceCommit': SOURCE, 'sourceRun': SOURCE_RUN, 'sourceAttempt': 1,
            'editorSha256': EDITOR_SHA, 'diagnosticCommit': os.environ.get('GITHUB_SHA'),
            'diagnosticRun': os.environ.get('GITHUB_RUN_ID')}


def encode_snapshot(value):
    raw = (json.dumps(value, ensure_ascii=False, separators=(',', ':'))+'\n').encode('utf-8')
    require(len(raw) <= MAX_METADATA_BYTES, 'Window metadata exceeds its budget')
    return raw


def window_snapshot(windows, pid, stage, elapsed):
    """Read only owned top-level wrapper metadata; never descendant text or values."""
    require(type(pid) is int and pid > 0, 'Expected a positive owned process ID')
    require(isinstance(windows, list), 'Expected the actual window enumeration list')
    value = {'stage': stage, 'elapsedSeconds': round(elapsed, 6), 'processId': pid,
             'rawCount': len(windows), 'examinedCount': 0, 'ownedCount': 0,
             'eligibleCount': 0, 'foreignRejectedCount': 0, 'collectionFailureCount': 0,
             'duplicateOwnedHandles': 0, 'enumerationTruncated': len(windows) > MAX_EXAMINED_WINDOWS,
             'metadataTruncated': False, 'windows': []}
    handles = set()
    for wrapper in windows[:MAX_EXAMINED_WINDOWS]:
        value['examinedCount'] += 1
        try:
            actual_pid = wrapper.process_id()
            if actual_pid != pid:
                value['foreignRejectedCount'] += 1
                continue
            value['ownedCount'] += 1
            handle = int(wrapper.handle)
            require(handle > 0, 'Invalid owned window handle')
            if handle in handles:
                value['duplicateOwnedHandles'] += 1
            handles.add(handle)
            visible, enabled = bool(wrapper.is_visible()), bool(wrapper.is_enabled())
            title, class_name = wrapper.window_text(), wrapper.class_name()
            require(isinstance(title, str) and isinstance(class_name, str), 'Invalid native window metadata')
            reasons = []
            if not visible: reasons.append('not-visible')
            if not enabled: reasons.append('not-enabled')
            if not title: reasons.append('empty-title')
            if class_name == '#32770': reasons.append('dialog-class')
            if not reasons:
                value['eligibleCount'] += 1
            row = {'hwnd': handle, 'processId': actual_pid, 'class': class_name[:64],
                   'title': title[:256], 'visible': visible, 'enabled': enabled,
                   'titleTruncated': len(title) > 256, 'classTruncated': len(class_name) > 64,
                   'rejectedReasons': reasons}
            if len(value['windows']) < MAX_RECORDED_WINDOWS:
                value['windows'].append(row)
            else:
                value['metadataTruncated'] = True
        except Exception:
            value['collectionFailureCount'] += 1
    while len((json.dumps(value, ensure_ascii=False, separators=(',', ':'))+'\n').encode('utf-8')) > MAX_METADATA_BYTES:
        require(value['windows'], 'Unbounded metadata outside window records')
        value['windows'].pop()
        value['metadataTruncated'] = True
    return value


def trace_original_selector(function, receiver, session, on_capture):
    """Observe its computed local list without changing code, predicates or input."""
    previous = sys.gettrace()
    captured = False
    def trace(frame, event, arg):
        nonlocal captured
        if frame.f_code is not function.__code__:
            return None
        if event == 'line' and not captured and 'windows' in frame.f_locals:
            windows = frame.f_locals['windows']
            if isinstance(windows, list):
                captured = True
                try:
                    value = window_snapshot(windows, session.proc.pid, 'original-selector-before-require', 0)
                    value.update(selectedCount=len(windows), originalComputedListCaptured=True,
                                 metadataCollectedAfterOriginalPredicates=True)
                    on_capture(value)
                except Exception:
                    # Collection must never shadow or change the real selector outcome.
                    pass
        return trace
    sys.settrace(trace)
    try:
        return function(receiver, session)
    finally:
        sys.settrace(previous)


class CloseObservation:
    def __init__(self, args):
        require(os.name == 'nt', 'Actual close observation requires Windows')
        self.root = args.source_root.resolve()
        self.exe = args.exe.resolve()
        self.fixtures = args.fixtures.resolve()
        self.output = args.output.resolve()
        self.documents = args.documents.resolve()
        require(not self.output.exists() and not self.documents.exists(), 'Refusing stale diagnostic output')
        require(self.exe.name == 'OpenGeul.exe' and self.exe.is_file() and not self.exe.is_symlink()
                and self.exe.stat().st_size == EDITOR_BYTES and sha(self.exe) == EDITOR_SHA,
                'Frozen Editor61 runtime bytes differ')
        require(FROZEN_HELPERS, 'Frozen helper manifest is missing')
        for name, expected in FROZEN_HELPERS.items():
            path = self.root / name
            require(path.is_file() and not path.is_symlink() and sha(path) == expected,
                    'Original source61 helper bytes differ')
        self.source = read_json(self.root/'evidence/source.json')
        self.manifest = read_json(self.fixtures/'manifest.json')
        verify_source_binding(self.source, self.manifest['engine'])
        require(self.manifest['password'] == 'OpenGeul-native-123456'
                and self.manifest['independentVerification'] == {'passed': True, 'path': 'independent-verification.json'},
                'Public synthetic password fixture controls differ')
        selected = [f for f in self.manifest['fixtures'] if f.get('format') == 'hwp']
        require(len(selected) == 1, 'Expected one encrypted HWP input')
        self.encrypted = selected[0]
        require(self.encrypted['path'] == 'protected.hwp'
                and all(self.encrypted[k] is True for k in
                        ('normalOpenRejected', 'wrongPasswordRejected', 'correctPasswordTextVerified')),
                'Encrypted input lacks password controls')
        self.original = self.fixtures/'protected.hwp'
        self.prior_original = self.fixtures/'prior.hwpx'
        for path, record in ((self.original, self.encrypted), (self.prior_original, self.manifest['prior'])):
            require(path.is_file() and not path.is_symlink() and path.stat().st_size == record['bytes']
                    and sha(path) == record['sha256'], 'Synthetic fixture bytes changed')
        self.output.mkdir(parents=True)
        self.documents.mkdir(parents=True)
        self.protected = self.documents/'protected.hwp'
        self.prior = self.documents/'prior.hwpx'
        shutil.copyfile(self.original, self.protected)
        shutil.copyfile(self.prior_original, self.prior)
        for name, target in (('manifest.json','fixture-manifest.json'),
                             ('independent-verification.json','fixture-verification.json')):
            read_json(self.fixtures/name)
            shutil.copyfile(self.fixtures/name, self.output/target)
        sys.path.insert(0, str(self.root/'e2e'))
        from driver import Session, edit, menu, until
        from native_controls import bind_dialog
        from uia_snapshot import snapshot_descendants
        self.Session, self.edit, self.menu, self.until = Session, edit, menu, until
        self.bind_dialog, self.snapshot = bind_dialog, snapshot_descendants
        spec = importlib.util.spec_from_file_location('original_native_close61', self.root/'e2e/password/native.py')
        self.native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.native)
        self.started = time.monotonic()
        self.stage = 'verified-inputs'
        self.events = []
        self.observations = []
        self.selector = None
        self.native_close_input = None
        self.session = None

    def mark(self, stage):
        # Memory-only timestamps do not add Windows enumeration or event-loop waits.
        self.stage = stage
        self.events.append({'stage': stage, 'elapsedSeconds': round(time.monotonic()-self.started, 6)})

    def unchanged(self, encrypted, expected):
        require(sha(encrypted) == expected, 'Protected synthetic source bytes changed')

    def save_snapshot(self, value):
        value['elapsedSeconds'] = round(time.monotonic()-self.started, 6)
        raw = encode_snapshot(value)
        name = 'windows-'+value['stage']+'.json'
        with (self.output/name).open('xb') as target:
            target.write(raw)
        self.observations.append({'stage': value['stage'], 'path': name, 'bytes': len(raw),
                                  'sha256': hashlib.sha256(raw).hexdigest(),
                                  'rawCount': value['rawCount'], 'ownedCount': value['ownedCount'],
                                  'eligibleCount': value['eligibleCount'],
                                  'selectedCount': value.get('selectedCount')})

    def observe_owned_windows(self, stage):
        from pywinauto import Desktop
        desktop = Desktop(backend='win32')
        if stage.startswith('after-selector-error-'):
            # After the preserved failure, include disabled/hidden owned roots
            # explicitly so default filters cannot hide a rejected candidate.
            windows = desktop.windows(process=self.session.proc.pid, top_level_only=True,
                                      visible_only=False, enabled_only=False)
            enumeration = 'explicit owned top-level census, visible_only=False enabled_only=False'
        else:
            windows = desktop.windows(process=self.session.proc.pid)
            enumeration = 'original Desktop(win32).windows(process=ownedPID) defaults'
        value = window_snapshot(windows, self.session.proc.pid, stage, time.monotonic()-self.started)
        value['enumeration'] = enumeration
        self.save_snapshot(value)

    def capture_original_selector(self, value):
        self.selector = {'selectedCount': value['selectedCount'],
                         'originalComputedListCaptured': True,
                         'sourceHelper': 'e2e/password/native.py:Qualification.request_native_close'}
        self.save_snapshot(value)

    def protected_state(self):
        session = self.session
        title = session.page.title()
        status = session.page.locator('#sb-message').inner_text()
        return {'documentTitle': title[:256], 'status': status[:256],
                'dirty': title.startswith('• '), 'protectedPathStillCurrent': self.protected.name in title,
                'protectedSourceSha256': sha(self.protected),
                'protectedSourceUnchanged': sha(self.protected) == self.encrypted['sha256']}

    def exercise(self):
        self.mark('start-production-session')
        session = self.Session('native', self.output/'session', self.prior, executable=self.exe)
        self.session = session
        require(session.page.evaluate("typeof window.__wasm === 'undefined' && typeof window.__inputHandler === 'undefined'"),
                'Production payload exposes a development bridge')
        helper = self.native.Qualification
        self.menu(session.page, 'file:open')
        session.native_dialog(self.protected)
        dialog = helper.password_dialog(self, session)
        dialog.locator('#hwp-password-input').fill(self.manifest['password'])
        dialog.locator('#hwp-password-input').press('Enter')
        dialog.wait_for(state='hidden', timeout=30000)
        session.wait_loaded(self.protected.name)
        self.edit(session.page, ' DIRTY-SAFETY-hwp ')
        helper.protected_still_dirty(self, session, self.protected, self.encrypted['sha256'])
        self.mark('before-replacement-modal')
        self.observe_owned_windows('before-replacement-modal')
        self.menu(session.page, 'file:open')
        session.native_dialog(self.prior)
        helper.unsaved_choice(self, session, self.protected, '취소', self.output, 'replacement-cancel')
        self.mark('after-native-choice-no-enumeration')
        # Preserve the exact failing path's order: no new API reads, waits or
        # enumeration between native Cancel, terminal UI readiness and close.
        helper.wait_cancelled_operation(self, session, '파일 열기 취소', self.protected)
        helper.protected_still_dirty(self, session, self.protected, self.encrypted['sha256'])
        self.mark('after-terminal-cancel-no-enumeration')
        self.mark('original-close-selector')
        observed = trace_original_selector(helper.request_native_close, self, session, self.capture_original_selector)
        self.native_close_input = observed
        self.mark('original-selector-passed-physical-close-sent')
        helper.unsaved_choice(self, session, self.protected, '취소', self.output, 'close-cancel')
        helper.wait_cancelled_operation(self, session, '창 닫기 취소', self.protected)
        helper.protected_still_dirty(self, session, self.protected, self.encrypted['sha256'])
        self.mark('unexpected-pass-safely-cancelled')
        return observed

    def run(self):
        result = base_result()
        result.update(originalSelectorPassed=False, originalSelectorFailureReproduced=False,
                      physicalCloseInputSent=False, diagnosticComplete=False)
        exit_code = 1
        try:
            observed = self.exercise()
            result.update(originalSelectorPassed=True, physicalCloseInputSent=True,
                          originalNativeCloseInput=observed, diagnosticComplete=True)
            exit_code = 0
        except Exception as error:
            if self.native_close_input is not None:
                result.update(originalSelectorPassed=True, physicalCloseInputSent=True,
                              originalNativeCloseInput=self.native_close_input)
            result['originalError'] = {'stage': self.stage, 'type': type(error).__name__, 'message': str(error)[:1024]}
            reproduced = (self.stage == 'original-close-selector' and isinstance(error, AssertionError)
                          and str(error) == 'Expected one owned native editor window before requesting close')
            result['originalSelectorFailureReproduced'] = reproduced
            if reproduced:
                # These reads occur strictly AFTER the original failed assertion.
                # They never retry selection or send a close/save input.
                try:
                    origin = time.monotonic()
                    self.observe_owned_windows('after-selector-error-0ms')
                    result['stateImmediatelyAfterFailure'] = self.protected_state()
                    for delay, label in ((.1,'100ms'),(.5,'500ms'),(1.0,'1000ms')):
                        time.sleep(max(0, origin+delay-time.monotonic()))
                        self.observe_owned_windows('after-selector-error-'+label)
                    result['stateAfterReadOnlyObservations'] = self.protected_state()
                    result['diagnosticComplete'] = self.selector is not None
                except Exception as collection_error:
                    result['postFailureObservationError'] = {'type': type(collection_error).__name__}
            if self.session is not None and self.session.page is not None:
                try:
                    self.session.page.screenshot(path=str(self.output/'failure.png'))
                except Exception:
                    pass
        finally:
            result['selector'] = self.selector
            result['stage'] = self.stage
            result['events'] = self.events
            result['observations'] = self.observations
            if self.session is not None:
                try:
                    self.session.close()
                except Exception as cleanup_error:
                    result['cleanupError'] = {'type': type(cleanup_error).__name__}
                    exit_code = 1
            try:
                result['editorBytesUnchanged'] = (self.exe.stat().st_size == EDITOR_BYTES and sha(self.exe) == EDITOR_SHA)
                result['protectedSourcesUnchanged'] = (sha(self.protected) == sha(self.original) == self.encrypted['sha256'])
                result['priorSourcesUnchanged'] = (sha(self.prior) == sha(self.prior_original) == self.manifest['prior']['sha256'])
                result['frozenHelpersUnchanged'] = all(sha(self.root/p) == expected for p, expected in FROZEN_HELPERS.items())
                if not all(result[k] for k in ('editorBytesUnchanged','protectedSourcesUnchanged','priorSourcesUnchanged','frozenHelpersUnchanged')):
                    exit_code = 1
            except Exception as identity_error:
                result['finalIdentityError'] = {'type': type(identity_error).__name__}
                exit_code = 1
            result['exitCode'] = exit_code
            raw = (json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
            require(len(raw) <= 64*1024, 'Diagnostic result exceeds metadata budget')
            with (self.output/'close-result.json').open('xb') as output:
                output.write(raw)
        print(json.dumps({'scope': result['scope'], 'qualification': False,
                          'originalSelectorPassed': result['originalSelectorPassed'],
                          'originalSelectorFailureReproduced': result['originalSelectorFailureReproduced'],
                          'selectedCount': self.selector.get('selectedCount') if self.selector else None,
                          'exitCode': exit_code}))
        return exit_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=Path('.'))
    parser.add_argument('--exe', type=Path, default=Path('editor-input/payload/OpenGeul.exe'))
    parser.add_argument('--fixtures', type=Path, default=Path('password-fixtures'))
    parser.add_argument('--output', type=Path, default=Path('evidence/close-phase'))
    parser.add_argument('--documents', type=Path, default=Path('diagnostic-documents'))
    args = parser.parse_args()
    try:
        return CloseObservation(args).run()
    except Exception as error:
        result = base_result()
        result.update(diagnosticComplete=False, stage='input-or-runtime-initialization',
                      errorType=type(error).__name__, message=str(error)[:1024], exitCode=1)
        try:
            target = args.output.parent/'close-initialization-error.json'
            if target.parent.is_dir() and not target.parent.is_symlink() and not target.exists():
                with target.open('x', encoding='utf-8') as output:
                    json.dump(result, output, ensure_ascii=False, indent=2)
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
