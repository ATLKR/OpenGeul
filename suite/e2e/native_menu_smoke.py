"""Fixed six-module native menu gestures on fresh blank owned documents.

This is one UI gate, not complete Suite acceptance. Save/reopen, Save As cancel,
close cancellation, module switching and Home ownership remain separate gates.
Synthetic boundary checks never establish actual Windows UI verification.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import time

MODULES = ('writer', 'calc', 'impress', 'draw', 'math', 'base')
GESTURES = ('open-escape', 'open-outside', 'keyboard-escape', 'open-escape')
EXTERNAL_GATES = ('save-and-reopen', 'save-as-cancel', 'close-cancel',
                  'module-transition', 'home-ownership', 'formatting')


class WindowsSession:
    """Real native boundaries; construction itself acquires no resources."""
    actual_windows = True

    def __init__(self, suite, fixtures, output, module):
        self.suite, self.fixtures, self.output, self.module = suite, fixtures, output, module
        self.process = self.api = self.engine = None
        self.hwnd = self.parent = self.child = self.office_pid = 0
        self.home_hwnd = 0

    def open(self, record):
        assert os.name == 'nt' and __debug__, 'Actual Windows GUI with assertions is required'
        import windows_smoke as native
        import startup_smoke as startup
        import owned_native_menu as menu
        from pywinauto import Desktop
        self.native, self.menu, self.desktop = native, menu, Desktop
        self.process = native.launch_suite(native.new_document_command(self.suite, self.module),
            self.suite, self.output, record['case'])
        self.api = native.Windows()
        self.hwnd, self.parent, self.child, self.office_pid = native.verified_attachment(
            self.api, self.process, self.module)
        attachment = dict(hwnd=self.hwnd, parent=self.parent, child=self.child,
                          officePid=self.office_pid)
        record['nativeArchiveGeneration'] = native.capture_native_archive_generation(
            self.api, self.process, attachment)
        self.engine = startup.EngineProcessWitness(self.office_pid)
        record.update(shellPid=self.process.pid, windowHwnd=self.hwnd, parentHwnd=self.parent,
            childHwnd=self.child, officePid=self.office_pid,
            officeCreationTime=self.engine.creation_time, nativeParentVerified=True)
        self.home_hwnd = int(self.api.home(self.process) or 0)
        self._home_ready()
        record['originalHomeHwnd'] = self.home_hwnd
        self.desktop(backend='win32').window(handle=self.hwnd).wrapper_object().maximize()
        native.activate_owned_suite(self.api, self.process, self.hwnd, record)
        self.api.require_foreground(self.hwnd)

    def ready(self):
        return self.menu.native_menu_active(self.api, self.process, self.hwnd) is True

    def gesture(self, name, record):
        result = self.menu.inspect_native_menu(self.api, self.process, self.hwnd,
            record, name)
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-native-menu-action' and result.get('gesture') is True
        assert result.get('command') == name, 'Native gesture receipt belongs to another operation'
        return dict(gesture=name, success=True, receipt=result)

    def _owned_blank(self):
        assert self.process.poll() is None and not self.engine.exited(0)
        assert all(self.api.user.IsWindow(h) for h in (self.hwnd, self.parent, self.child))
        assert (self.api.pid(self.hwnd), self.api.pid(self.parent), self.api.pid(self.child)) == (
            self.process.pid, self.process.pid, self.office_pid)
        assert self.api.user.GetAncestor(self.hwnd, 2) == self.hwnd
        assert self.api.user.IsChild(self.hwnd, self.parent) and self.api.user.IsChild(self.parent, self.child)
        assert (int(self.api.user.GetPropW(self.hwnd, 'OpenGeul.Office.ParentHwnd') or 0),
                int(self.api.user.GetPropW(self.hwnd, 'OpenGeul.Office.ChildHwnd') or 0)) == (self.parent, self.child)
        self.api.require_foreground(self.hwnd)

    def screenshot(self, record):
        self._owned_blank()
        image = self.desktop(backend='win32').window(handle=self.hwnd).wrapper_object().capture_as_image()
        self._owned_blank()
        name = record['case'] + '-chrome.png'
        image.crop((0, 0, image.width, min(240, image.height))).save(self.output / name)
        record['screenshotScope'] = 'owned-fresh-blank-form-top-240-pixels'
        return name

    def _native_command(self, command, record):
        result = self.menu.click_native_menu_action(self.api, self.process, self.hwnd, record, command)
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-native-menu-action' and result.get('gesture') is False
        assert result.get('command') == command
        return result

    def _wait_original_closed(self):
        self.native.wait_for(lambda: not self.api.user.IsWindow(self.hwnd), seconds=20)
        self.native.wait_for(lambda: not self.api.user.IsWindow(self.child), seconds=10)

    def _home_ready(self, *, active=False):
        assert self.home_hwnd and self.process.poll() is None
        assert self.api.home(self.process) == self.home_hwnd
        assert self.api.pid(self.home_hwnd) == self.process.pid
        assert self.api.user.GetAncestor(self.home_hwnd, 2) == self.home_hwnd
        assert not self.api.user.GetPropW(self.home_hwnd, 'OpenGeul.Office.ChildHwnd')
        if not active:
            return True
        foreground = self.api.user.GetForegroundWindow()
        return bool(self.api.user.IsWindowVisible(self.home_hwnd) and foreground
            and self.api.user.GetAncestor(foreground, 2) == self.home_hwnd)

    def _cancel_calc_exit(self, record, *, deadline):
        from owned_menu_cancel import cancel_native_menu_prompt
        caption = 'OpenGeul Calc'
        assert deadline > time.monotonic(), 'Original Calc cancel readiness deadline expired'
        def find():
            dialogs = [h for h in self.api.windows(self.process.pid)
                if self.api.user.GetWindow(h, 4) == self.hwnd and self.api.title(h) == caption]
            assert len(dialogs) <= 1, 'Calc close prompt is ambiguous'
            if not dialogs:
                return None
            dialog, = dialogs
            self.native.require_dialog_identity(self.api.pid(dialog), self.process.pid,
                self.api.user.GetWindow(dialog, 4), self.hwnd, self.api.title(dialog),
                caption, self.api.class_name(dialog))
            return dialog
        dialog = self.native.wait_for(find, seconds=deadline - time.monotonic())
        self.api.require_foreground(dialog)
        remaining = deadline - time.monotonic()
        assert remaining > 0, 'Original Calc cancel readiness deadline expired'
        result = cancel_native_menu_prompt(self.api, self.process, self.hwnd, record,
            dialog, caption, seconds=min(5, remaining))
        assert type(result) is dict and result.get('success') is True
        assert result.get('kind') == 'owned-shell-menu-cancel'
        snapshots = result.get('snapshots')
        assert type(snapshots) is list and snapshots and all(type(row) is dict
            and row.get('promptSchemaVerified') is True for row in snapshots), \
            'Bounded Calc prompt schema proof is missing'
        assert not self.api.user.IsWindow(dialog), 'Original Calc prompt survived its one Cancel action'
        record['nativeExitCancelAction'] = result
        return True

    def finish(self, record):
        saved_base = None
        if self.module == 'base':
            # A private fresh target avoids changing the shared fixture set used
            # by the original two full GUI runs.
            owned = self.output / 'native-menu-base-generated'
            owned.mkdir(exist_ok=False)
            saved_base = self.native.save_new_base(self.api, self.process, self.hwnd,
                owned, self.output, record)
            assert record['baseSaveMenuAction']['kind'] == 'owned-native-menu-action', \
                'Native Base Save must not be qualified by the WinForms fallback'
        if self.module == 'writer':
            self._native_command('home', record)
            self._wait_original_closed()
            self.native.wait_for(lambda: self._home_ready(active=True), seconds=10)
            self.api.require_foreground(self.home_hwnd)
            record['nativeHomeVerified'] = True
        elif self.module in ('draw', 'math'):
            self._native_command('close', record)
            self._wait_original_closed()
            record['nativeCloseVerified'] = True
        elif self.module == 'calc':
            exit_deadline = time.monotonic() + 20  # Existing close-prompt bound, including the menu action.
            self._native_command('exit', record)
            assert self._cancel_calc_exit(record, deadline=exit_deadline) is True
            self._owned_blank()
            assert self.ready() is True
            record['postExitCancelMenu'] = self.gesture('open-escape', record)
            record['nativeExitCancelVerified'] = True
            from generated_calc_close import freeze_generated_blank_calc
            proof = freeze_generated_blank_calc(self.suite, self.api, self.process,
                self.hwnd, self.child, record)
            self.native.close_document(self.api, self.process, self.hwnd, self.child,
                record, calc_close_proof=proof)
        elif self.module == 'base':
            self._native_command('exit', record)
            self._wait_original_closed()
            self.process.wait(timeout=25)
            assert self.process.returncode == 0
            assert not self.api.user.IsWindow(self.home_hwnd), 'Native Exit left the original Home alive'
            record['nativeExitVerified'] = True
        else:
            self.native.close_document(self.api, self.process, self.hwnd, self.child, record)
        if self.module != 'base':
            self.native.close_home(self.api, self.process, record)
        record['officeExited'] = self.engine.exited(10)
        assert record['officeExited'], 'Original native engine survived normal menu scenario shutdown'
        record['officeExitCode'] = self.engine.code()
        assert record['officeExitCode'] == 0 and self.process.returncode == 0
        if saved_base is not None:
            record['savedBaseEvidence'] = self.native.saved_base_evidence(saved_base)
        record['cleanClose'] = True
        return True

    def cleanup(self, record):
        shell_done = True
        engine_done = engine_released = self.process is None
        if self.process is not None:
            record['forcedCleanupRequired'] = self.process.poll() is None
            self.native.stop_owned_test_process(self.process, record)
            record['shellExitCode'] = self.process.poll()
            shell_done = record['shellExitCode'] is not None
        if self.engine is not None:
            try:
                engine_done = self.engine.exited(5)
                record['officeExitedAfterCleanup'] = engine_done
            finally:
                handle = self.engine.handle
                engine_released = bool(handle and self.engine.close_handle(handle))
                record['engineHandleReleased'] = engine_released
                if engine_released:
                    self.engine.handle = None
        return bool(shell_done and engine_done and engine_released)


def run_case(suite, fixtures, output, module, *, session_factory=WindowsSession):
    if module not in MODULES:
        raise ValueError('Unknown native menu module')
    record = dict(case='native-menu-' + module, module=module, success=False,
        kind='native-menu-gesture-case', stage='open', gestures=[],
        keyboardInputVerified=False, contentMutationVerified=False,
        scenarioCompleted=False, actualWindowsExecuted=False,
        nativeMenuVerified=False, cleanupConfirmed=False, cleanClose=False)
    started = time.monotonic()
    session = None
    try:
        session = session_factory(suite, fixtures, output, module)
        record['actualWindowsExecuted'] = session.actual_windows is True and os.name == 'nt'
        session.open(record)
        record['stage'] = 'require-native-menu'
        assert session.ready() is True, 'The actual native menu surface is unavailable'
        for index, gesture in enumerate(GESTURES):
            record['stage'] = gesture
            result = session.gesture(gesture, record)
            assert type(result) is dict and result.get('success') is True
            assert result.get('gesture') == gesture
            record['gestures'].append(dict(index=index, gesture=gesture, receipt=result))
        record['stage'] = 'capture-owned-blank-chrome'
        record['screenshot'] = session.screenshot(record)
        record['stage'] = 'close-original-document-and-home'
        assert session.finish(record) is True
        record.update(success=True, scenarioCompleted=True)
    except Exception as exc:
        record['errorType'] = type(exc).__name__
    finally:
        if session is not None:
            try:
                record['cleanupConfirmed'] = session.cleanup(record) is True
            except Exception as exc:
                record['cleanupErrorType'] = type(exc).__name__
        if not record['cleanupConfirmed']:
            record['success'] = False
        record['nativeMenuVerified'] = record['success'] and record['actualWindowsExecuted']
        if record['success']:
            record['stage'] = 'complete'
        record['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return record


def run_modules(suite, fixtures, output, *, session_factory=WindowsSession):
    records = []
    for module in MODULES:
        record = run_case(suite, fixtures, output, module, session_factory=session_factory)
        records.append(record)
        with (output / (record['case'] + '.json')).open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False, indent=2)
        print(module + ': ' + ('passed' if record['success'] else 'FAILED: ' + record.get(
            'errorType', record.get('cleanupErrorType', 'unconfirmed cleanup'))), flush=True)
        if not record['cleanupConfirmed']:
            break  # An unretired original engine cannot authorize the next case.
    counts = Counter(row['module'] for row in records)
    complete = tuple(row['module'] for row in records) == MODULES and all(n == 1 for n in counts.values())
    scenario_success = complete and all(row['success'] for row in records)
    native_verified = scenario_success and all(row['nativeMenuVerified'] for row in records)
    report = dict(schemaVersion=1, kind='native-menu-gesture-matrix', success=native_verified,
        scenarioSuccess=scenario_success, actualWindowsExecuted=bool(records) and all(
            row['actualWindowsExecuted'] for row in records), nativeMenuVerified=native_verified,
        acceptanceEligible=False, expectedCaseCount=len(MODULES), completedCaseCount=len(records),
        nativeHwpMenuLaunchExecuted=False, disabledCommandsPhysicalVerified=False,
        passedCaseCount=sum(row['success'] for row in records),
        missingModules=[module for module in MODULES if module not in counts],
        failedModules=[row['module'] for row in records if not row['success']],
        externalAcceptanceGates=list(EXTERNAL_GATES), tests=records)
    with (output / 'results.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
    return report


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('suite', 'fixtures', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    assert os.name == 'nt' and __debug__, 'Actual Windows GUI with assertions is required'
    paths = (args.suite, args.fixtures, args.output)
    for path in paths:
        for part in (path, *path.parents):
            assert not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)()
    suite, fixtures, output = (path.resolve() for path in paths)
    assert suite.is_dir() and fixtures.is_dir()
    assert not any(str(path).startswith(('\\\\', '//')) for path in (suite, fixtures, output))
    assert suite != output and suite not in output.parents
    assert fixtures != output and fixtures not in output.parents
    output.mkdir(parents=True, exist_ok=False)
    return 0 if run_modules(suite, fixtures, output)['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
