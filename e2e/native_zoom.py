"""HOP #94 viewport regression through the real Windows window and file dialogs.

Only the disposable runner's owned app window is resized. Document zoom is set
through user-facing controls; JavaScript only reads DOM/layout evidence. These
checks do not certify toolbar overflow, other operating systems or print output.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import shutil

WIDTHS = (960, 1023, 1025)
OBSERVATION = """() => {
  const canvas = document.querySelector('#scroll-content canvas');
  const box = canvas?.getBoundingClientRect();
  const toolbar = document.querySelector('#style-bar');
  return {width: innerWidth, height: innerHeight, dpr: devicePixelRatio,
    outerWidth, outerHeight, zoom: document.querySelector('#sb-zoom-val')?.textContent.trim(),
    ready: !!toolbar && getComputedStyle(toolbar).pointerEvents === 'auto',
    canvasWidth: box?.width ?? null, canvasHeight: box?.height ?? null,
    title: document.title, message: document.querySelector('#sb-message')?.textContent};
}"""


def finite_positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def require_native_host(session, env=None, platform=None):
    env = os.environ if env is None else env
    platform = os.name if platform is None else platform
    if (session.mode != 'native' or platform != 'nt' or env.get('GITHUB_ACTIONS') != 'true'
            or env.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
        raise RuntimeError('Native zoom QA requires an owned disposable Windows runner')


def native_width(requested, outer_width, observed):
    """Convert a measured CSS-client delta, preserving the existing native frame."""
    if type(requested) is not int or requested not in WIDTHS:
        raise ValueError('Unexpected native viewport case')
    values = (outer_width, observed.get('width'), observed.get('dpr'))
    if not all(finite_positive(v) for v in values) or not .5 <= values[2] <= 4:
        raise ValueError('Invalid measured native viewport dimensions')
    result = round(outer_width + (requested - values[1]) * values[2])
    if not 200 <= result <= 8192:
        raise ValueError('Native window size outside bounded QA limits')
    return result


def validate_observation(observed, width, zoom, rendered_size=None):
    if observed.get('width') != width or observed.get('zoom') != zoom:
        raise AssertionError(f'Viewport/zoom changed: {observed!r}; expected {width}px / {zoom}')
    if observed.get('ready') is not True:
        raise AssertionError('Document editing is not ready')
    actual = (observed.get('canvasWidth'), observed.get('canvasHeight'))
    if not all(finite_positive(v) for v in actual):
        raise AssertionError('No measurable rendered document canvas')
    if rendered_size is not None and (not isinstance(rendered_size, (tuple, list))
            or len(rendered_size) != 2 or not all(finite_positive(v) for v in rendered_size)):
        raise AssertionError('Invalid expected rendered dimensions')
    # Subpixel CSS layout rounding only; never a PDF/raster comparison tolerance.
    if rendered_size is not None and any(abs(a-b) > .5 for a,b in zip(actual, rendered_size)):
        raise AssertionError(f'Rendered zoom changed: {actual!r} != {rendered_size!r}')


def owned_window(session):
    require_native_host(session)
    from pywinauto import Desktop
    if session.proc is None or session.proc.poll() is not None:
        raise AssertionError('The native app is not running')
    windows = [w for w in Desktop(backend='win32').windows(process=session.proc.pid, visible_only=True)
               if w.class_name() == 'Tauri Window']
    if len(windows) != 1 or windows[0].process_id() != session.proc.pid:
        raise AssertionError('Expected exactly one owned native editor window')
    return windows[0]


def resize_native_viewport(session, width):
    if type(width) is not int or width not in WIDTHS:
        raise ValueError('Unexpected native viewport case')
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    window = owned_window(session)
    if window.is_maximized() or window.is_minimized():
        window.restore()
    # Frame/DPI rounding is calibrated against the real WebView innerWidth.
    # An input error escapes; no failed resize or test is silently retried.
    adjustments = []
    for _ in range(3):
        observed = session.page.evaluate(OBSERVATION)
        if observed['width'] == width:
            return {'hwnd': window.handle, 'adjustments': adjustments, 'observed': observed}
        rect = window.rectangle()
        target = native_width(width, rect.width(), observed)
        adjustments.append({'from': observed['width'], 'nativeWidth': target, 'dpr': observed['dpr']})
        window.move_window(x=0, y=0, width=target, height=rect.height(), repaint=True)
        try:
            session.page.wait_for_function('(width) => innerWidth === width', arg=width, timeout=3000)
        except PlaywrightTimeout:
            continue  # Recalculate only a measured frame/DPI delta, not an input failure.
    observed = session.page.evaluate(OBSERVATION)
    if observed['width'] != width:
        raise AssertionError(f'Native resize did not reach {width}px: {observed!r}; {adjustments!r}')
    return {'hwnd': window.handle, 'adjustments': adjustments, 'observed': observed}


def open_same_window(session, path):
    from driver import menu
    page, proc = session.page, session.proc
    handle = owned_window(session).handle
    menu(page, 'file:open')
    session.native_dialog(path)
    session.wait_loaded(path.name)
    if (session.page is not page or session.proc is not proc or proc.poll() is not None
            or page.is_closed() or owned_window(session).handle != handle):
        raise AssertionError('Document switch replaced the original native window/session')


def checkpoint(session, folder, label, width, zoom, rendered_size=None):
    from driver import until
    last = {}
    def read():
        nonlocal last
        last = session.page.evaluate(OBSERVATION)
        validate_observation(last, width, zoom, rendered_size)
        return last
    try:
        observed = until(read, timeout=20, pump=lambda delay: session.page.wait_for_timeout(delay*1000))
        rect = owned_window(session).rectangle()
        observed['nativeRect'] = [rect.left, rect.top, rect.right, rect.bottom]
        return observed
    finally:
        (folder/(label+'.json')).write_text(json.dumps(last, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


class NativeZoomTests:
    def check_native_zoom(self, width):
        from playwright.sync_api import expect
        from driver import digest, edit
        from hwpx_oracle import inspect_hwpx
        from test_editor import FIXTURES
        session, page = self.session, self.page
        require_native_host(session)
        original = self.document
        alternate = self.folder/'zoom-alternate.hwp'
        shutil.copy2(FIXTURES/'basic.hwp', alternate)
        originals = {path: digest(path) for path in (original, alternate)}
        evidence = self.folder/'zoom-evidence'
        evidence.mkdir()
        try:
            sizing = resize_native_viewport(session, width)
            (evidence/'native-resize.json').write_text(json.dumps(sizing, indent=2), encoding='utf-8')
            page.locator('textarea').first.focus()
            page.keyboard.press('Control+0')
            expect(page.locator('#sb-zoom-val')).to_have_text('100%')
            baseline = checkpoint(session, evidence, '01-before', width, '100%')
            for step in range(1, 6):
                page.locator('#sb-zoom-in').click()
                expect(page.locator('#sb-zoom-val')).to_have_text(f'{100+10*step}%')
            rendered = (baseline['canvasWidth']*1.5, baseline['canvasHeight']*1.5)
            checkpoint(session, evidence, '02-selected', width, '150%', rendered)

            # No process restart: exercise the exact document-load boundary being fixed.
            open_same_window(session, alternate)
            checkpoint(session, evidence, '03-hwp-switched', width, '150%', rendered)
            open_same_window(session, original)
            checkpoint(session, evidence, '04-hwpx-returned', width, '150%', rendered)
            marker = f' ZOOM-{width}-SAVED 한글 '
            edit(page, marker)
            saved = self.folder/f'zoom-{width}-saved.hwpx'
            session.save(original, saved, save_as=True)
            self.assertEqual(inspect_hwpx(saved)['text'].count(marker), 1)
            checkpoint(session, evidence, '05-saved', width, '150%', rendered)

            open_same_window(session, alternate)
            checkpoint(session, evidence, '06-away', width, '150%', rendered)
            open_same_window(session, saved)
            checkpoint(session, evidence, '07-reopened', width, '150%', rendered)
            second = f' ZOOM-{width}-AFTER-REOPEN '
            edit(page, second)
            session.save(saved, saved)
            text = inspect_hwpx(saved)['text']
            for expected in (marker, second):self.assertEqual(text.count(expected), 1)
            checkpoint(session, evidence, '08-editable', width, '150%', rendered)
            page.screenshot(path=str(evidence/'final-viewport.png'))
            self.assertFalse(session.errors, session.errors)
        finally:
            preservation = [{'file': path.name, 'before': before, 'after': digest(path)}
                            for path, before in originals.items()]
            (evidence/'source-preservation.json').write_text(json.dumps(preservation, ensure_ascii=False, indent=2), encoding='utf-8')
            self.assertTrue(all(item['before'] == item['after'] for item in preservation), preservation)

    def test_native_zoom_960px_file_switch_save_reopen(self):self.check_native_zoom(960)
    def test_native_zoom_1023px_file_switch_save_reopen(self):self.check_native_zoom(1023)
    def test_native_zoom_1025px_file_switch_save_reopen(self):self.check_native_zoom(1025)
