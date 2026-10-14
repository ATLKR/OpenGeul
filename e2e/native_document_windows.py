"""Draft actual Windows page/HWND boundary for document preservation UI cases.

Requires the small opt-in driver.native_dialog(owner_scope=...) patch supplied
with this draft. No product bridge, engine method, synthetic close or IPC input.
Native success must come from a future actual full Windows run.
Activation clicks change the caret: this helper covers committed text, not a
pending selection, drag, clipboard read or live IME-composition preservation.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from native_document_policy import (EDITOR_CLASSES, IDENTITY, choose_editor_hwnd,
    require_editor, require_hit, require_focus_map, require_owned_dialog,
    double_checked_action, require_dialog_action, require_filename_control, unsaved_dialog_action)

class OwnedDocumentWindows:
    def __init__(self, session):
        if session.mode != 'native' or os.name != 'nt' or session.proc.poll() is not None:
            raise AssertionError('Actual running Windows native editor is required')
        from pywinauto import Desktop
        from print_focus import WindowsFocusProbe, _bind_native_print_processes
        self.session = session
        self.desktop = Desktop(backend='win32')
        self.probe = WindowsFocusProbe()
        self.runtime = json.loads((session.folder/'runtime.json').read_text(encoding='utf-8'))
        self.pages = {}; self.windows = {}; self.dialogs = {}; self.records = []; self.fatal_error = None
        self.processes, self.bind_process = _bind_native_print_processes(
            self.probe, session.proc.pid, session.proc.pid, self.runtime, int(session.proc._handle))
        original_handler = getattr(session, 'dialog_handler', None)
        if not callable(original_handler):
            self.probe.close()
            raise AssertionError('Opt-in unexpected-dialog boundary is missing from the driver')
        session.page.remove_listener('dialog', original_handler)
        session.page.on('dialog', self._unexpected_web_dialog('initial'))

    def _unexpected_web_dialog(self, key):
        def unexpected(dialog):
            self.fatal_error = RuntimeError('Unexpected web dialog in an owned native document window')
            self.session.dialogs.append({'type': dialog.type, 'message': dialog.message, 'pageKey': key})
            try:
                dialog.dismiss()
            finally:
                raise self.fatal_error
        return unexpected

    def close(self):
        self.write_evidence()
        self.probe.close()

    def write_evidence(self):
        if len(self.records) > 200:
            raise AssertionError('Owned document input evidence exceeds its bound')
        (self.session.folder/'native-document-ownership.json').write_text(json.dumps({
            'formatVersion': 1, 'kind': 'actual-native-input-observations',
            'sourceQualified': False, 'productTelemetry': False,
            'appPid': self.session.proc.pid, 'records': self.records,
        }, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def _record(self, operation, record):
        if len(self.records) >= 200:
            raise AssertionError('Owned document input evidence exceeds its bound')
        self.records.append({'operation': operation, **record})
        self.write_evidence()

    def _app(self):
        if self.fatal_error is not None:
            raise self.fatal_error
        self.probe.verify_process(self.session.proc.pid, self.processes[self.session.proc.pid])

    def _roots(self):
        self._app()
        values = []
        for window in self.desktop.windows(process=self.session.proc.pid):
            if window.is_visible() and window.class_name() in EDITOR_CLASSES:
                values.append(self.probe.window(window.handle))
        if len(values) > 32:
            raise AssertionError('Actual native editor root inventory exceeds its bound')
        return values

    def _focus_rows(self):
        live = [page for page in self.session.context.pages if not page.is_closed()]
        owned = [page for page in self.pages.values() if not page.is_closed()]
        if len(live) != len(owned) or any(page not in owned for page in live):
            raise AssertionError('An unbound live document page exists in this native session')
        return [{'pageKey': key, 'focused': page.evaluate('document.hasFocus()')}
                for key, page in self.pages.items() if not page.is_closed()]

    def first(self, key='A'):
        if self.pages:
            raise AssertionError('The first page/HWND mapping is already held')
        rows = self._roots()
        hwnd = choose_editor_hwnd([], rows, self.session.proc.pid)
        return self._bind(key, self.session.page, next(row for row in rows if row['hwnd'] == hwnd))

    def _bind(self, key, page, row):
        if key in self.pages or row['hwnd'] in self.windows:
            raise AssertionError('Page/HWND mapping is duplicate')
        self.pages[key] = page
        window = BoundDocumentWindow(self, key, page, row)
        self.windows[row['hwnd']] = window
        window.prepare()
        return window

    def new(self, parent, key='B'):
        from driver import until
        from playwright.sync_api import expect
        before = self._roots()
        with self.session.context.expect_page(timeout=30000) as event:
            parent.menu('file:new-window')
        page = event.value
        page.set_default_timeout(15000)
        page.on('console', lambda message: self.session.messages.append(
            {'type': message.type, 'text': message.text, 'pageKey': key}))
        page.on('pageerror', lambda error: self.session.errors.append(f'{key}: {error}'))
        page.on('request', lambda request: self.session.requests.append(request.url))
        # Unexpected web alert/confirm is a failure, never auto-consented.
        page.on('dialog', self._unexpected_web_dialog(key))
        expect(page.locator('#studio-root')).to_be_visible(timeout=30000)
        page.locator('textarea[aria-label="문서 편집 입력"]').wait_for(state='attached')
        observed = {}
        def one_new():
            rows = self._roots()
            hwnd = choose_editor_hwnd(before, rows, self.session.proc.pid)
            observed['row'] = next(row for row in rows if row['hwnd'] == hwnd)
            return True
        until(one_new, timeout=30, pump=lambda seconds: parent.page.wait_for_timeout(seconds*1000))
        # New WebView processes are inspected from current actual process state.
        from native_architecture import verify_webview2
        self.runtime['webview2Native'] = verify_webview2(
            self.session.proc.pid, self.runtime['nativeArchitecture']['architecture'])
        return self._bind(key, page, observed['row'])

class BoundDocumentWindow:
    def __init__(self, owner, key, page, record):
        self.owner = owner; self.key = key; self.page = page; self.bound = record.copy()
        self.hwnd = record['hwnd']
        self.picker_purpose = None

    def _editor(self, *, modal=False):
        self.owner._app()
        actual = self.owner.probe.window(self.hwnd)
        if modal:
            if ({key: actual[key] for key in IDENTITY} != {key: self.bound[key] for key in IDENTITY}
                    or not actual['visible']):
                raise AssertionError('Modal parent editor identity changed')
            return actual
        return require_editor(actual, self.bound)

    def _bind_pid(self, pid):
        from print_focus import _bind_native_print_processes
        processes, bind = _bind_native_print_processes(self.owner.probe, pid,
            self.owner.session.proc.pid, self.owner.runtime, int(self.owner.session.proc._handle))
        self.owner.processes.update(processes)
        return processes

    def _point_observation(self):
        window = self._editor()
        wrapper = self.owner.desktop.window(handle=self.hwnd).wrapper_object()
        box = self.page.locator('#editor-area').bounding_box()
        viewport = self.page.evaluate('({width: innerWidth, height: innerHeight, ratio: devicePixelRatio})')
        if (not box or any(type(viewport.get(key)) not in (float, int) for key in ('width', 'height', 'ratio'))
                or viewport['ratio'] <= 0 or min(box['width'], box['height']) <= 0):
            raise AssertionError('Actual editor page has no usable physical input bounds')
        css = (box['x']+box['width']/2, box['y']+box['height']/2)
        if not (0 < css[0] < viewport['width'] and 0 < css[1] < viewport['height']):
            raise AssertionError('Actual editor input point is outside its viewport')
        origin = wrapper.client_to_screen((0, 0))
        point = (round(origin[0]+css[0]*viewport['ratio']), round(origin[1]+css[1]*viewport['ratio']))
        hit = self.owner.probe.window(self.owner.probe.hit(point))
        processes = self._bind_pid(hit['pid'])
        for pid, record in processes.items(): self.owner.probe.verify_process(pid, record)
        require_hit(hit, window, processes)
        if self.owner.probe.foreground() != self.hwnd:
            raise AssertionError('Native editor input point is not in the exact foreground HWND')
        return {'pageKey': self.key, 'window': window, 'point': list(point), 'hit': hit,
                'foreground': self.hwnd, 'processes': list(processes.values())}

    def prepare(self):
        """One explicitly owned activation/click, then public read-only focus mapping."""
        from driver import until
        from pywinauto import mouse
        self._editor()
        self.owner.desktop.window(handle=self.hwnd).wrapper_object().set_focus()
        record = double_checked_action(self._point_observation,
            lambda observed: mouse.click(coords=tuple(observed['point'])))
        self.owner._record('editor-physical-focus-click', record)
        until(lambda: require_focus_map(self.key, self.owner._focus_rows()), timeout=10,
              pump=lambda seconds: self.page.wait_for_timeout(seconds*1000))
        return self._ready()

    def _ready(self):
        window = self._editor()
        if self.page.is_closed() or self.owner.probe.foreground() != self.hwnd:
            raise AssertionError('Native page/HWND lost ownership before document input')
        focus = require_focus_map(self.key, self.owner._focus_rows())
        return {'pageKey': self.key, 'window': window, 'foreground': self.hwnd, 'focus': focus}

    def menu(self, command):
        from driver import menu
        self.prepare()
        record = double_checked_action(self._ready, lambda observed: menu(self.page, command))
        self.owner._record(command, record)

    def edit(self, text):
        from driver import edit
        self.prepare()
        record = double_checked_action(self._ready, lambda observed: edit(self.page, text))
        self.owner._record('public-textarea-committed-input', {**record, 'characters': len(text)})

    def request_close(self):
        from pywinauto import keyboard
        self.prepare()
        record = double_checked_action(self._ready,
            lambda observed: keyboard.send_keys('%{F4}', pause=.02, vk_packet=False))
        self.owner._record('native-Alt-F4-on-exact-editor', record)

    def wait_loaded(self, name):
        from playwright.sync_api import expect
        self.page.wait_for_function('(name) => document.querySelector("#sb-message")?.textContent.includes(name)',
                                    arg=name, timeout=60000)
        expect(self.page.locator('#style-bar')).to_have_css('pointer-events', 'auto', timeout=60000)
        self.page.locator('textarea[aria-label="문서 편집 입력"]').wait_for(state='attached')

    def open(self, path):
        self.menu('file:open')
        self.picker(path, purpose='open')
        self.wait_loaded(path.name)

    def picker(self, target, *, cancel=False, purpose='save'):
        # Existing vetted filename controls/readiness path remains authoritative.
        if target is not None and not Path(target).resolve().is_relative_to(self.owner.session.folder.parent.resolve()):
            raise AssertionError('Document picker target is outside this owned UI case')
        if purpose not in ('open', 'save') or self.picker_purpose is not None:
            raise AssertionError('Native document picker purpose is invalid or already pending')
        self.picker_purpose = purpose
        try:
            self.owner.session.native_dialog(target, cancel=cancel, owner_scope=self)
        finally:
            self.picker_purpose = None

    def _dialog_live(self, dialog):
        parent = self._editor(modal=True)
        row = self.owner.probe.window(dialog.handle)
        require_owned_dialog(row, parent, set(self.owner.windows))
        if dialog.process_id() != parent['pid'] or dialog.class_name() != '#32770':
            raise AssertionError('Dialog wrapper no longer belongs to the exact editor')
        if self.picker_purpose is not None:
            titles = {'open': ('Open', '열기'), 'save': ('Save As', '다른 이름으로 저장', 'Save', '저장')}
            if dialog.window_text() not in titles[self.picker_purpose]:
                raise AssertionError('Owned dialog is not the expected Open/Save picker')
        identity = {key: row[key] for key in IDENTITY}
        previous = self.owner.dialogs.get(dialog.handle)
        if previous is not None and previous != identity:
            raise AssertionError('Exact owned dialog HWND/thread identity changed')
        self.owner.dialogs[dialog.handle] = identity
        for hwnd in row['owners']:
            owner = self.owner.probe.window(hwnd)
            if owner['pid'] != parent['pid'] or owner['root'] != hwnd:
                raise AssertionError('Dialog native owner ancestry changed')
        return row

    def bind_dialog(self, dialog):
        return self._dialog_live(dialog)

    def finish_dialog(self, hwnd):
        if self.owner.probe.user.IsWindow(hwnd) and self.owner.probe.user.IsWindowVisible(hwnd):
            raise AssertionError('Exact owned dialog still exists after its action')
        self.owner.dialogs.pop(hwnd, None)
        self.owner._record('native-owned-dialog-ended', {'pageKey': self.key, 'hwnd': hwnd,
                                                        'observedVisible': False})

    def before_filename_input(self, dialog, control):
        row = self._dialog_live(dialog)
        child = self.owner.probe.window(control.handle)
        parent = control.parent()
        combo = self.owner.probe.window(parent.handle)
        require_filename_control(child, combo, row)
        if (control.handle != child['hwnd'] or control.process_id() != row['pid']
                or control.class_name() != 'Edit' or parent.class_name() != 'ComboBox'
                or self.owner.probe.parent(control.handle) != parent.handle):
            raise AssertionError('Native filename wrapper or ComboBox parent changed')
        rect = control.rectangle()
        bounds = [rect.left, rect.top, rect.right, rect.bottom]
        client = dialog.client_rect()
        client_bounds = [client.left, client.top, client.right, client.bottom]
        if (any(type(value) is not int or not -2**31 <= value < 2**31
                for value in (*bounds, *client_bounds))
                or rect.right <= rect.left or rect.bottom <= rect.top
                or client.right <= client.left or client.bottom <= client.top):
            raise AssertionError('Native filename control or picker has no usable actual bounds')
        left, top = dialog.client_to_screen((client.left, client.top))
        right, bottom = dialog.client_to_screen((client.right, client.bottom))
        screen = [left, top, right, bottom]
        if (any(type(value) is not int or not -2**31 <= value < 2**31 for value in screen)
                or right <= left or bottom <= top):
            raise AssertionError('Native filename picker screen bounds are invalid')
        visible = [max(rect.left, left), max(rect.top, top), min(rect.right, right), min(rect.bottom, bottom)]
        if visible[2] <= visible[0] or visible[3] <= visible[1]:
            raise AssertionError('Native filename control has no visible picker client intersection')
        point = ((visible[0]+visible[2])//2, (visible[1]+visible[3])//2)
        hit = self.owner.probe.window(self.owner.probe.hit(point))
        foreground = self.owner.probe.foreground()
        if hit != child or foreground != row['hwnd']:
            raise AssertionError('Native filename screen point or foreground is outside the exact owned Edit')
        return {'pageKey': self.key, 'dialog': row, 'title': dialog.window_text(),
                'purpose': self.picker_purpose, 'filename': child, 'combo': combo,
                'filenameBounds': bounds, 'pickerClientBounds': client_bounds,
                'pickerScreenBounds': screen, 'visibleFilenameBounds': visible,
                'point': list(point), 'hit': hit, 'foreground': foreground}

    def set_filename(self, dialog, control, text):
        if self.picker_purpose not in ('open', 'save'):
            raise AssertionError('Native filename input requires the independently requested picker purpose')
        record = double_checked_action(lambda: self.before_filename_input(dialog, control),
                                       lambda observed: control.set_edit_text(text))
        self.owner._record('native-owned-filename-input-once', {**record, 'characters': len(text)})

    def _prompt_text(self, dialog):
        from pywinauto import Desktop
        from uia_snapshot import snapshot_descendants
        return '\n'.join(control.window_text() for control in snapshot_descendants(
            Desktop(backend='uia').window(handle=dialog.handle), control_type='Text') if control.window_text())

    def _button_observation(self, dialog, button, expected):
        row = self._dialog_live(dialog)
        child = self.owner.probe.window(button.handle)
        rect = button.rectangle()
        bounds = [rect.left, rect.top, rect.right, rect.bottom]
        if (button.process_id() != row['pid'] or button.class_name() != 'Button'
                or child['pid'] != row['pid'] or child['root'] != row['hwnd']
                or not child['visible'] or not child['enabled']
                or any(type(value) is not int for value in bounds)
                or rect.right <= rect.left or rect.bottom <= rect.top):
            raise AssertionError('Native dialog action button is not owned and ready')
        point = (round((rect.left+rect.right)/2), round((rect.top+rect.bottom)/2))
        hit = self.owner.probe.window(self.owner.probe.hit(point))
        parents = []; current = hit['hwnd']
        for _ in range(16):
            if not current or current in parents: break
            parents.append(current)
            if current == row['hwnd']: break
            current = self.owner.probe.parent(current)
        if (hit['pid'] != row['pid'] or hit['root'] != row['hwnd']
                or button.handle not in parents or row['hwnd'] not in parents
                or self.owner.probe.foreground() != row['hwnd']):
            raise AssertionError('Physical dialog button point/foreground is outside the exact owned action')
        semantics = require_dialog_action({
            'controlId': button.control_id(), 'label': button.window_text().replace('&', '').strip(),
            'title': dialog.window_text(),
            'promptText': self._prompt_text(dialog) if expected['promptText'] is not None else None,
        }, expected)
        return {'pageKey': self.key, 'dialog': row, 'button': child, 'controlId': button.control_id(),
                'buttonBounds': bounds, 'point': list(point), 'hit': hit, 'ancestors': parents,
                'foreground': row['hwnd'], 'semantics': semantics}

    def click_dialog_button(self, dialog, button, *, expected_control_id,
                            expected_label=None, expected_title=None, expected_prompt=None):
        from pywinauto import mouse
        self._dialog_live(dialog)
        label = button.window_text().replace('&', '').strip()
        title = dialog.window_text()
        if self.picker_purpose is not None:
            labels = {2: ('Cancel', '취소'), 1: {
                'open': ('Open', '열기', '열기(O)'),
                'save': ('Save', '저장', '저장(S)'),
            }[self.picker_purpose]}
            if expected_control_id not in labels or label not in labels[expected_control_id]:
                raise AssertionError('Picker button ID/label does not match the independent requested action')
        elif expected_label is None or expected_title is None or expected_prompt is None:
            raise AssertionError('TaskDialog input requires the selected document/choice semantics')
        expected = {'controlId': expected_control_id, 'label': expected_label or label,
                    'title': expected_title or title, 'promptText': expected_prompt}
        require_dialog_action(expected, expected)
        dialog.set_focus()
        record = double_checked_action(lambda: self._button_observation(dialog, button, expected),
            lambda observed: mouse.click(coords=tuple(observed['point'])))
        self.owner._record('native-owned-dialog-button-once', record)

    def choose_unsaved(self, choice, expected_name):
        from driver import until
        expected = unsaved_dialog_action(choice, expected_name)
        observed = {}
        def ready():
            rows = [window for window in self.owner.desktop.windows(process=self.owner.session.proc.pid)
                    if window.class_name() == '#32770' and window.is_visible() and window.is_enabled()]
            if len(rows) != 1: return False
            dialog = rows[0]
            self.bind_dialog(dialog)
            if dialog.window_text() != expected['title']:
                raise AssertionError('Expected the exact product unsaved-changes TaskDialog')
            texts = self._prompt_text(dialog)
            if texts != expected['promptText']:
                raise AssertionError('Unsaved dialog is not asking about this exact owned document')
            buttons = [button for button in dialog.descendants(class_name='Button')
                       if button.is_visible() and button.is_enabled()
                       and button.window_text().replace('&', '').strip() == choice]
            if len(buttons) != 1: return False
            if buttons[0].control_id() != expected['controlId']:
                raise AssertionError('Unsaved dialog choice has the wrong locked native button ID')
            observed.update(dialog=dialog, button=buttons[0])
            return True
        until(ready, timeout=20, pump=lambda seconds: self.page.wait_for_timeout(seconds*1000))
        dialog = observed['dialog']; hwnd = dialog.handle
        self.click_dialog_button(dialog, observed['button'], expected_control_id=expected['controlId'],
                                 expected_label=expected['label'], expected_title=expected['title'],
                                 expected_prompt=expected['promptText'])
        until(lambda: not self.owner.probe.user.IsWindow(hwnd)
              or not self.owner.probe.user.IsWindowVisible(hwnd), timeout=20,
              pump=lambda seconds: self.page.wait_for_timeout(seconds*1000))
        self.finish_dialog(hwnd)

    def wait_closed(self):
        from driver import until
        until(lambda: not self.owner.probe.user.IsWindow(self.hwnd) and self.page.is_closed(), timeout=30)

    def save_existing(self, path):
        from driver import until
        from playwright.sync_api import expect
        self.menu('file:save')
        expect(self.page.locator('#sb-message')).to_contain_text('저장 완료', timeout=30000)
        self.page.wait_for_function('!document.title.startsWith("• ")', timeout=30000)
        until(path.is_file)
        return path

    def save_first(self, path, *, cancel=False):
        from driver import until
        from playwright.sync_api import expect
        self.menu('file:save')
        self.picker(path, cancel=cancel)
        if cancel:
            # Picker disappearance alone is not bridge-lock-release success.
            return None
        expect(self.page.locator('#sb-message')).to_contain_text('저장 완료', timeout=30000)
        self.page.wait_for_function('!document.title.startsWith("• ")', timeout=30000)
        until(path.is_file)
        return path
