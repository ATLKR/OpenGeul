"""One public GUI picker observation; never a full password qualification."""
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

SOURCE = '7c712ca538c1bdd9b27d0ae5b1ccb8d0c06384d0'
SOURCE_RUN = 38154760005
EDITOR_SHA = 'e47d4a27ad0f976c9fd37e553c611c07a1e2a22be14c437165e2fdfc918c3194'
EDITOR_BYTES = 33641472


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise AssertionError(message)


def read_json(path, limit=64*1024):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
            'Expected bounded regular JSON metadata')
    return json.loads(path.read_text(encoding='utf-8'))


class PickerObservation:
    def __init__(self, args):
        self.root = args.source_root.resolve()
        self.exe = args.exe.resolve()
        self.fixtures = args.fixtures.resolve()
        self.output = args.output.resolve()
        self.documents = args.documents.resolve()
        require(os.name == 'nt', 'Actual picker observation requires Windows')
        require(not self.output.exists() and not self.documents.exists(), 'Refusing stale diagnostic paths')
        require(self.exe.name == 'OpenGeul.exe' and self.exe.is_file() and not self.exe.is_symlink()
                and self.exe.stat().st_size == EDITOR_BYTES and sha(self.exe) == EDITOR_SHA,
                'Editor57 bytes differ before GUI execution')
        source = read_json(self.root / 'evidence/source.json')
        require(source['sourceCommit'] == SOURCE and source['sourceRun'] == SOURCE_RUN
                and source['editorSha256'] == EDITOR_SHA, 'Transport identity differs')
        self.manifest = read_json(self.fixtures / 'manifest.json')
        engine = self.manifest['engine']
        require(engine['qualification'] == 'final-source-bound'
                and engine['provenance'] == source['wasmRebuild'], 'Fixture engine differs from Editor57')
        require(self.manifest['independentVerification']['passed'] is True,
                'Independent synthetic ciphertext verification failed')
        require(self.manifest['password'] == 'OpenGeul-native-123456', 'Expected public QA password')
        selected = [f for f in self.manifest['fixtures'] if f['format'] == 'hwp']
        require(len(selected) == 1, 'Expected one encrypted HWP fixture')
        self.encrypted = selected[0]
        require(self.encrypted['path'] == 'protected.hwp'
                and all(self.encrypted[k] is True for k in
                        ('normalOpenRejected', 'wrongPasswordRejected', 'correctPasswordTextVerified')),
                'Encrypted HWP fixture lacks password controls')
        self.original = self.fixtures / 'protected.hwp'
        self.prior = self.fixtures / 'prior.hwpx'
        for path, record in ((self.original, self.encrypted), (self.prior, self.manifest['prior'])):
            require(path.is_file() and not path.is_symlink() and path.stat().st_size == record['bytes']
                    and sha(path) == record['sha256'], 'Synthetic fixture bytes changed')
        self.output.mkdir(parents=True)
        self.documents.mkdir(parents=True)
        shutil.copyfile(self.original, self.documents / 'protected.hwp')
        shutil.copyfile(self.prior, self.documents / 'prior.hwpx')
        self.protected = self.documents / 'protected.hwp'
        self.plaintext = self.documents / 'separate.hwp'
        self.started = time.monotonic()
        self.stage = 'verified-inputs'
        self.records = []
        self.session = None
        sys.path.insert(0, str(self.root / 'e2e'))
        from driver import Session, edit, menu, until
        from native_controls import bind_dialog, dismiss_error_dialog
        from uia_snapshot import snapshot_descendants
        self.Session, self.edit, self.menu, self.until = Session, edit, menu, until
        self.bind_dialog, self.dismiss_error, self.snapshot = bind_dialog, dismiss_error_dialog, snapshot_descendants
        verifier = self.root / 'e2e/password/verify-password-fixtures.py'
        spec = importlib.util.spec_from_file_location('picker_fixture_verifier', verifier)
        self.verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.verifier)
        for source_path, name in ((self.fixtures / 'manifest.json', 'fixture-manifest.json'),
                                  (self.fixtures / 'independent-verification.json', 'fixture-verification.json')):
            read_json(source_path)
            shutil.copyfile(source_path, self.output / name)

    def mark(self, stage, **data):
        self.stage = stage
        self.records.append({'stage': stage, 'elapsedSeconds': round(time.monotonic()-self.started, 3), **data})

    def unchanged(self):
        require(sha(self.protected) == self.encrypted['sha256'] and sha(self.original) == self.encrypted['sha256'],
                'Protected synthetic source bytes changed')

    def acknowledge_block(self, session, start):
        from pywinauto import Desktop
        def observed():
            for dialog in session.dialogs[start:]:
                if '암호 문서의 원본 저장' in dialog.get('message', ''):
                    return ('webview', dialog['message'])
            native = Desktop(backend='win32').window(class_name='#32770', process=session.proc.pid)
            if native.exists(timeout=0) and native.is_visible():
                return ('native', None)
            return None
        kind, message = self.until(observed, timeout=25, pump=lambda delay: session.page.wait_for_timeout(delay*1000))
        metadata = {}
        if kind == 'native':
            bound = self.bind_dialog(Desktop(backend='win32'), session.proc.pid)
            actual = bound.wrapper_object()
            metadata = {'hwnd': actual.handle, 'pid': actual.process_id(),
                        'class': actual.class_name(), 'title': actual.window_text()[:256]}
            message = self.dismiss_error(session.proc.pid)
        require('암호 문서의 원본 저장' in message, 'Direct Save did not show the password policy block')
        self.mark('direct-save-block-dismissed', kind=kind, message=message[:512], ownedDialog=metadata)

    def accept_consent(self, session):
        from pywinauto import Desktop
        bound = self.bind_dialog(Desktop(backend='win32'), session.proc.pid)
        native = bound.wrapper_object()
        accessible = Desktop(backend='uia').window(handle=native.handle)
        require(native.window_text() == '암호 없이 저장', 'Unexpected plaintext consent title')
        text = '\n'.join(item.window_text() for item in self.snapshot(accessible, control_type='Text') if item.window_text())
        require('저장한 HWP 파일에는 암호가 적용되지 않습니다' in text, 'Missing HWP plaintext consent')
        buttons = [item for item in native.descendants(class_name='Button') if item.is_visible() and item.is_enabled()
                   and item.window_text().replace('&', '').strip() in ('암호 없이 저장', 'OK', '확인')]
        require(len(buttons) == 1, 'Expected one physical plaintext consent action')
        self.mark('plaintext-consent-observed', hwnd=native.handle, pid=native.process_id(),
                  dialogClass=native.class_name(), title=native.window_text(), message=text[:512])
        native.set_focus()
        buttons[0].click_input()
        bound.wait_not('visible', timeout=20)

    def exercise(self):
        self.mark('start-production-session')
        session = self.Session('native', self.output / 'session', self.documents / 'prior.hwpx', executable=self.exe)
        self.session = session
        require(session.page.evaluate("typeof window.__wasm === 'undefined' && typeof window.__inputHandler === 'undefined'"),
                'Production editor exposes a development bridge')
        self.mark('open-encrypted-hwp')
        self.menu(session.page, 'file:open')
        session.native_dialog(self.protected)
        dialog = session.page.get_by_role('dialog', name='문서 암호 입력', exact=True)
        dialog.wait_for(state='visible', timeout=30000)
        require(dialog.count() == 1, 'Expected one public password dialog')
        # Reproduce the same wrong-password/retry sequence before the old first picker failure.
        dialog.locator('#hwp-password-input').fill('OpenGeul-wrong-123456')
        dialog.locator('#hwp-password-input').press('Enter')
        error = dialog.locator('#hwp-password-error')
        error.wait_for(state='visible', timeout=30000)
        require('다시 입력' in error.inner_text() and dialog.locator('#hwp-password-input').input_value() == '',
                'Wrong-password retry controls differ')
        dialog.locator('#hwp-password-input').fill(self.manifest['password'])
        dialog.locator('#hwp-password-input').press('Enter')
        dialog.wait_for(state='hidden', timeout=30000)
        session.wait_loaded(self.protected.name)
        marker = ' PICKER57-HWP-TO-HWP '
        self.edit(session.page, marker)
        require(session.page.title().startswith('• '), 'Opened encrypted HWP is not observably editable')
        self.mark('request-protected-direct-save')
        start = len(session.dialogs)
        self.menu(session.page, 'file:save')
        self.acknowledge_block(session, start)
        self.unchanged()
        require(session.page.title().startswith('• '), 'Protected Direct Save lost dirty state')
        self.mark('request-first-hwp-save-as')
        self.menu(session.page, 'file:save-as')
        # Exact source7c Session.native_dialog owns HWND binding, filename readiness and failure metadata.
        session.native_dialog(self.plaintext)
        self.mark('strict-filename-picker-completed')
        self.accept_consent(session)
        self.mark('await-plaintext-save')
        session.page.wait_for_function("() => document.querySelector('#sb-message')?.textContent.includes('저장 완료')", timeout=30000)
        session.page.wait_for_function("!document.title.startsWith('• ')", timeout=30000)
        self.until(self.plaintext.is_file, timeout=30, pump=lambda delay: session.page.wait_for_timeout(delay*1000))
        require(self.plaintext.name in session.page.title(), 'Save As did not adopt the separate plaintext path')
        self.verifier.inspect_hwp(self.plaintext, False, self.manifest['expectedText'])
        self.verifier.inspect_hwp(self.plaintext, False, marker)
        self.unchanged()
        self.mark('plaintext-hwp-independent-check', outputSha256=sha(self.plaintext), protectedUnchanged=True)
        session.close()
        self.session = None
        self.mark('fresh-public-gui-reopen')
        session = self.Session('native', self.output / 'fresh-reopen', self.plaintext, executable=self.exe)
        self.session = session
        require(session.page.locator('#hwp-password-input').count() == 0, 'Plaintext fresh reopen asks for a password')
        self.unchanged()
        self.mark('picker-observation-complete', freshReopenWithoutPassword=True)

    def run(self):
        result = {'scope': 'editor57-hwp-picker-diagnostic-only', 'qualification': False,
                  'sourceCommit': SOURCE, 'sourceRun': SOURCE_RUN, 'editorSha256': EDITOR_SHA,
                  'diagnosticCommit': os.environ.get('GITHUB_SHA'), 'diagnosticRun': os.environ.get('GITHUB_RUN_ID')}
        success = False
        try:
            self.exercise()
            success = True
        except Exception as error:
            result['error'] = {'stage': self.stage, 'type': type(error).__name__, 'message': str(error)[:1024]}
            if self.session is not None and self.session.page is not None:
                try:
                    self.session.page.screenshot(path=str(self.output / 'failure.png'))
                except Exception:
                    pass
        finally:
            if self.session is not None:
                try:
                    self.session.close()
                except Exception as error:
                    success = False
                    result['cleanupError'] = {'type': type(error).__name__, 'message': str(error)[:512]}
            try:
                same_exe = self.exe.stat().st_size == EDITOR_BYTES and sha(self.exe) == EDITOR_SHA
                same_protected = sha(self.protected) == self.encrypted['sha256'] and sha(self.original) == self.encrypted['sha256']
            except Exception as error:
                same_exe = same_protected = False
                result['finalIdentityError'] = {'type': type(error).__name__, 'message': str(error)[:512]}
            result.update({'pickerObservationPassed': success and same_exe and same_protected,
                           'editorBytesUnchanged': same_exe, 'protectedSourceUnchanged': same_protected,
                           'stage': self.stage, 'events': self.records})
            data = (json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
            require(len(data) <= 64*1024, 'Diagnostic result exceeds its metadata budget')
            (self.output / 'picker-result.json').write_bytes(data)
        print(json.dumps({'scope': result['scope'], 'qualification': False,
                          'pickerObservationPassed': result['pickerObservationPassed'], 'stage': self.stage}))
        return 0 if result['pickerObservationPassed'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=Path('.'))
    parser.add_argument('--exe', type=Path, default=Path('editor-input/payload/OpenGeul.exe'))
    parser.add_argument('--fixtures', type=Path, default=Path('password-fixtures'))
    parser.add_argument('--output', type=Path, default=Path('evidence/picker-phase'))
    parser.add_argument('--documents', type=Path, default=Path('diagnostic-documents'))
    args = parser.parse_args()
    try:
        return PickerObservation(args).run()
    except Exception as error:
        result = {'scope': 'editor57-hwp-picker-diagnostic-only', 'qualification': False,
                  'pickerObservationPassed': False, 'stage': 'input-or-runtime-initialization',
                  'type': type(error).__name__, 'message': str(error)[:1024]}
        data = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
        # Preserve initialization failures without replacing the actual failed exit status.
        try:
            target = args.output.parent / 'picker-initialization-error.json'
            if target.parent.is_dir() and not target.parent.is_symlink() and not target.exists():
                with target.open('x', encoding='utf-8') as output:
                    output.write(data)
        except Exception:
            pass
        print(json.dumps(result))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
