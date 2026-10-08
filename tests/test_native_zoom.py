"""OS-boundary controls for the real native viewport scenario; no Windows pass implied."""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(test, relative, name):
    path = ROOT / relative
    test.assertTrue(path.is_file(), f'Missing native zoom verification: {relative}')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeZoomControls(unittest.TestCase):
    def setUp(self):
        self.m = load(self, 'e2e/native_zoom.py', 'native_zoom_controls')
        self.good = {'width': 960, 'height': 640, 'dpr': 1.0, 'zoom': '150%',
                     'ready': True, 'canvasWidth': 1190.625, 'canvasHeight': 1683.75}
        self.size = (1190.625, 1683.75)

    def test_measured_width_zoom_and_rendered_size_pass(self):
        self.m.validate_observation(self.good, 960, '150%', self.size)

    def test_adjacent_boundary_width_cannot_substitute_for_requested_width(self):
        for actual in (959, 961, 1024):
            with self.assertRaises(AssertionError):
                self.m.validate_observation({**self.good, 'width': actual}, 960, '150%', self.size)

    def test_unchanged_status_label_does_not_hide_reset_canvas_geometry(self):
        with self.assertRaises(AssertionError):
            self.m.validate_observation({**self.good, 'canvasWidth': 793.75}, 960, '150%', self.size)

    def test_wrong_zoom_does_not_pass_even_with_matching_canvas(self):
        with self.assertRaises(AssertionError):
            self.m.validate_observation({**self.good, 'zoom': '100%'}, 960, '150%', self.size)

    def test_missing_or_nonfinite_canvas_does_not_pass(self):
        for value in (None, 0, float('nan'), float('inf'), True):
            with self.assertRaises(AssertionError):
                self.m.validate_observation({**self.good, 'canvasWidth': value}, 960, '150%', self.size)

    def test_invalid_expected_render_geometry_is_not_an_empty_or_nan_pass(self):
        for expected in ((), (1190.625,), (float('nan'), 1683.75), (1190.625, float('inf'))):
            with self.assertRaises(AssertionError):
                self.m.validate_observation(self.good, 960, '150%', expected)

    def resize_boundary(self, *, stuck=False, input_error=False, start=960):
        page = types.SimpleNamespace(width=start)
        page.evaluate = lambda code: {**self.good, 'width': page.width}
        class Deadline(Exception):pass
        def wait(code, **kw):
            if page.width != kw['arg']:raise Deadline('readback did not match')
        page.wait_for_function = wait
        moves = []
        window = types.SimpleNamespace(handle=100, is_maximized=lambda:False, is_minimized=lambda:False,
            rectangle=lambda:types.SimpleNamespace(width=lambda:page.width+16, height=lambda:720))
        def move(**kwargs):
            moves.append(kwargs)
            if input_error:raise OSError('resize dispatched then failed')
            if not stuck:page.width=kwargs['width']-16
        window.move_window = move
        session = types.SimpleNamespace(page=page)
        return session, window, moves, Deadline

    def test_real_resize_helper_uses_native_move_and_measured_readback(self):
        session, window, moves, deadline = self.resize_boundary()
        with patch.object(self.m, 'owned_window', return_value=window), patch.dict(sys.modules, {
                'playwright.sync_api':types.SimpleNamespace(TimeoutError=deadline)}):
            result = self.m.resize_native_viewport(session, 1025)
        self.assertEqual(result['observed']['width'], 1025)
        self.assertEqual(len(moves),1);self.assertEqual(moves[0]['width'],1041)

    def test_resize_input_error_is_not_retried(self):
        session, window, moves, deadline = self.resize_boundary(input_error=True)
        with patch.object(self.m, 'owned_window', return_value=window), patch.dict(sys.modules, {
                'playwright.sync_api':types.SimpleNamespace(TimeoutError=deadline)}):
            with self.assertRaises(OSError):self.m.resize_native_viewport(session,1023)
        self.assertEqual(len(moves),1)

    def test_unreachable_native_width_fails_after_bounded_calibration(self):
        session, window, moves, deadline = self.resize_boundary(stuck=True)
        with patch.object(self.m, 'owned_window', return_value=window), patch.dict(sys.modules, {
                'playwright.sync_api':types.SimpleNamespace(TimeoutError=deadline)}):
            with self.assertRaises(AssertionError):self.m.resize_native_viewport(session,1023)
        self.assertEqual(len(moves),3)

    def test_already_matching_unreviewed_width_is_rejected_before_input(self):
        session, window, moves, deadline = self.resize_boundary(start=777)
        with patch.object(self.m, 'owned_window', return_value=window), patch.dict(sys.modules, {
                'playwright.sync_api':types.SimpleNamespace(TimeoutError=deadline)}):
            with self.assertRaises(ValueError):self.m.resize_native_viewport(session,777)
        self.assertEqual(moves,[])

    def test_editing_readiness_is_required(self):
        with self.assertRaises(AssertionError):
            self.m.validate_observation({**self.good, 'ready': False}, 960, '150%', self.size)

    def test_native_resize_preserves_frame_width(self):
        self.assertEqual(self.m.native_width(1023, 976, self.good), 1039)

    def test_native_resize_scales_only_client_delta_at_higher_dpi(self):
        self.assertEqual(self.m.native_width(1023, 1464, {**self.good, 'dpr': 1.5}), 1558)

    def test_native_resize_rejects_unknown_width_and_bad_dpi(self):
        for width in (0, 959, True, 50000):
            with self.assertRaises(ValueError):self.m.native_width(width, 976, self.good)
        for dpr in (0, None, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):self.m.native_width(960, 976, {**self.good, 'dpr': dpr})

    def test_workspace_or_non_native_session_cannot_resize_windows(self):
        session = types.SimpleNamespace(mode='native')
        good = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted'}
        self.m.require_native_host(session, good, 'nt')
        for env, platform, mode in (({}, 'nt', 'native'), (good, 'posix', 'native'), (good, 'nt', 'browser')):
            with self.assertRaises(RuntimeError):
                self.m.require_native_host(types.SimpleNamespace(mode=mode), env, platform)

    def session(self):
        page = types.SimpleNamespace(is_closed=lambda: False)
        proc = types.SimpleNamespace(pid=42, poll=lambda: None)
        return types.SimpleNamespace(mode='native', page=page, proc=proc,
                                     native_dialog=None, wait_loaded=None)

    def test_open_switch_uses_native_dialog_once_in_the_same_session(self):
        session = self.session(); events = []
        session.native_dialog = lambda p: events.append(('native', p))
        session.wait_loaded = lambda name: events.append(('loaded', name))
        window = types.SimpleNamespace(handle=100)
        module = types.SimpleNamespace(menu=lambda p, cmd: events.append(('menu', cmd)))
        with patch.dict(sys.modules, {'driver': module}), patch.object(self.m, 'owned_window', return_value=window):
            self.m.open_same_window(session, Path('next.hwpx'))
        self.assertEqual(events, [('menu', 'file:open'), ('native', Path('next.hwpx')), ('loaded', 'next.hwpx')])
        self.assertEqual(session.proc.pid, 42)

    def test_failed_native_open_is_not_retried(self):
        session = self.session(); events = []
        def fail(path):events.append(path);raise OSError('native input dispatched then failed')
        session.native_dialog = fail
        module = types.SimpleNamespace(menu=lambda *args: None)
        with patch.dict(sys.modules, {'driver': module}), patch.object(self.m, 'owned_window', return_value=types.SimpleNamespace(handle=100)):
            with self.assertRaises(OSError):self.m.open_same_window(session, Path('next.hwpx'))
        self.assertEqual(events, [Path('next.hwpx')])

    def test_replacement_window_is_not_a_same_window_pass(self):
        session = self.session();session.native_dialog = lambda p: None;session.wait_loaded = lambda n: None
        module = types.SimpleNamespace(menu=lambda *args: None)
        windows = [types.SimpleNamespace(handle=h) for h in (100, 200)]
        with patch.dict(sys.modules, {'driver': module}), patch.object(self.m, 'owned_window', side_effect=windows):
            with self.assertRaises(AssertionError):self.m.open_same_window(session, Path('next.hwpx'))

    def test_scenario_has_no_emulated_viewport_or_private_app_api(self):
        text = (ROOT/'e2e/native_zoom.py').read_text(encoding='utf-8')
        for forbidden in ('set_viewport_size', 'Emulation.', 'window.__wasm', 'self.open(', 'dispatch_event('):
            self.assertNotIn(forbidden, text)
        self.assertIn('.move_window(', text)
        self.assertIn('source-preservation.json', text)


class NativeZoomSuiteContract(unittest.TestCase):
    def setUp(self):self.m = load(self, 'e2e/suite_contract.py', 'zoom_suite_contract')

    def records(self, mode):return [{'test': 'Suite.'+name, 'status': 'passed'} for name in self.m.required_methods(mode)]

    def test_browser_baseline_ten_native_baseline_sixteen_plus_three(self):
        self.assertEqual(len(self.m.required_methods('browser')), 10)
        self.assertEqual(len(self.m.required_methods('native')), 19)
        self.assertEqual(len(self.m.ZOOM_METHODS), 3)
        self.assertTrue(self.m.coverage_ok('browser', self.records('browser')))
        self.assertTrue(self.m.coverage_ok('native', self.records('native')))

    def test_duplicate_cannot_replace_a_required_case_with_the_same_total(self):
        rows = self.records('native');rows[-1] = dict(rows[0])
        self.assertFalse(self.m.coverage_ok('native', rows))

    def test_unknown_passing_case_is_not_required_coverage(self):
        rows = self.records('native');rows[-1]['test'] = 'Suite.test_unknown'
        self.assertFalse(self.m.coverage_ok('native', rows))

    def test_failed_or_skipped_case_is_not_coverage(self):
        for status in ('failed', 'error', 'skipped', None):
            rows = self.records('native');rows[0]['status'] = status
            self.assertFalse(self.m.coverage_ok('native', rows))

    def test_missing_case_or_empty_result_is_not_success(self):
        self.assertFalse(self.m.coverage_ok('native', []))
        self.assertFalse(self.m.coverage_ok('native', self.records('native')[:-1]))

    def test_unsupported_mode_rejected(self):
        with self.assertRaises(ValueError):self.m.required_methods('partial')

    def test_original_source_methods_are_preserved_and_new_methods_are_real(self):
        editor = ast.parse((ROOT/'e2e/test_editor.py').read_text(encoding='utf-8'))
        followups = ast.parse((ROOT/'e2e/test_hop_followups.py').read_text(encoding='utf-8'))
        zoom = ast.parse((ROOT/'e2e/native_zoom.py').read_text(encoding='utf-8'))
        def methods(tree, cls):
            node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
            return {n.name for n in node.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')}
        common = methods(editor, 'EditorTests') | methods(followups, 'FollowupTests')
        native = common | methods(editor, 'NativeTests') | methods(zoom, 'NativeZoomTests')
        self.assertEqual(common, set(self.m.required_methods('browser')))
        self.assertEqual(native, set(self.m.required_methods('native')))
        self.assertEqual(methods(zoom, 'NativeZoomTests'), set(self.m.ZOOM_METHODS))

    def test_runner_requires_identity_coverage_not_only_total(self):
        text = (ROOT/'e2e/run.py').read_text(encoding='utf-8')
        self.assertIn('coverage_ok(mode,result.records)', text)
        self.assertIn('required_methods(mode)', text)
        self.assertIn('NativeZoomTests', (ROOT/'e2e/test_hop_followups.py').read_text())


if __name__=='__main__':unittest.main()
