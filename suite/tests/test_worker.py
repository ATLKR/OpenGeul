"""Worker tests use fake UNO only at native/process boundaries; no GUI proof."""
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

WORKER = Path(__file__).resolve().parents[1] / 'worker'
sys.path.insert(0, str(WORKER))
MODULES = {
    'writer': {'factory': 'private:factory/swriter', 'displayName': 'OpenGeul Writer',
               'extensions': ['odt', 'docx'], 'filters': {'odt': 'writer8', 'docx': 'Office Open XML Text'}},
    'calc': {'factory': 'private:factory/scalc', 'displayName': 'OpenGeul Calc',
             'extensions': ['ods', 'xlsx'], 'filters': {'ods': 'calc8', 'xlsx': 'Calc MS Excel 2007 XML'}},
}


class FakeBackend:
    def __init__(self, runtime):
        self.modified = False
        self.path = None
        self.calls = []
        self.fail_save = False
        self.fail_close = False
        self.fail_attach = False

    def attach(self, hwnd, module, width, height, path):
        self.calls.append(('attach', hwnd, module, width, height, path))
        if self.fail_attach:
            raise RuntimeError('connection unavailable')
        self.path = path
        return {'parentHwnd': hwnd, 'childHwnd': 456}

    def status(self):
        return {'modified': self.modified, 'title': 'Example'}

    def resize(self, width, height):
        self.calls.append(('resize', width, height))

    def save(self, path, filter_name):
        self.calls.append(('save', path, filter_name))
        if self.fail_save:
            raise RuntimeError('disk full')
        self.path = path
        self.modified = False

    def close(self, discard):
        self.calls.append(('close', discard))
        if self.fail_close:
            raise RuntimeError('close vetoed')

    def cleanup(self):
        self.calls.append(('cleanup',))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((WORKER / 'session.py').is_file(), 'missing worker session implementation')
        self.session_module = importlib.import_module('session')
        self.worker_module = importlib.import_module('office_worker')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.backend = FakeBackend(self.root)
        self.session = self.session_module.DocumentSession(
            self.root, MODULES, backend_factory=lambda runtime: self.backend)

    def attach(self, **kwargs):
        args = {'parentHwnd': 123, 'module': 'writer', 'width': 640, 'height': 480}
        args.update(kwargs)
        return self.session.dispatch('attach', args)

    def assert_code(self, code, command, args):
        with self.assertRaises(self.session_module.WorkerError) as caught:
            self.session.dispatch(command, args)
        self.assertEqual(code, caught.exception.code)

    def test_attach_registers_real_backend_identity_and_module(self):
        status = self.attach()
        self.assertEqual(456, status['childHwnd'])
        self.assertEqual(123, status['parentHwnd'])
        self.assertEqual('writer', status['module'])
        self.assertFalse(status['modified'])

    def test_invalid_transition_does_not_create_backend(self):
        self.assert_code('invalid_state', 'save', {})
        self.assertEqual([], self.backend.calls)
        self.attach()
        self.assert_code('invalid_state', 'attach', {})

    def test_module_and_dimensions_fail_before_native_start(self):
        for changes in ({'module': 'hwp'}, {'width': 0}, {'height': True}, {'parentHwnd': -1}):
            with self.subTest(changes=changes):
                with self.assertRaises(self.session_module.WorkerError):
                    self.attach(**changes)
        self.assertEqual([], self.backend.calls)

    def test_attach_rejects_remote_paths_and_mismatched_module(self):
        for name in ('https://example.test/a.docx', r'\\server\share\a.docx', 'relative.docx'):
            self.assert_code('invalid_path', 'attach',
                             {'parentHwnd': 1, 'module': 'writer', 'width': 1, 'height': 1, 'path': name})
        wrong = self.root / 'book.xlsx'
        wrong.write_bytes(b'x')
        self.assert_code('unsupported_format', 'attach',
                         {'parentHwnd': 1, 'module': 'writer', 'width': 1, 'height': 1, 'path': str(wrong)})
        self.assertEqual([], self.backend.calls)

    def test_unicode_path_is_passed_as_local_path_without_interpretation(self):
        path = self.root / '한글 space $x`file.docx'
        path.write_bytes(b'docx')
        self.attach(path=str(path))
        self.assertEqual(path, self.backend.calls[0][-1])

    def test_attach_failure_cleans_owned_backend_and_permits_retry(self):
        self.backend.fail_attach = True
        self.assert_code('attach_failed', 'attach',
                         {'parentHwnd': 1, 'module': 'writer', 'width': 1, 'height': 1})
        self.assertIn(('cleanup',), self.backend.calls)
        self.backend.fail_attach = False
        self.assertEqual(456, self.attach()['childHwnd'])

    def test_dirty_close_cancels_without_closing_or_cleanup(self):
        self.attach()
        self.backend.modified = True
        result = self.session.dispatch('close', {'discard': False})
        self.assertEqual({'closed': False, 'closeCancelled': True}, result)
        self.assertTrue(self.session.dispatch('status', {})['modified'])
        self.assertNotIn(('cleanup',), self.backend.calls)
        self.assertNotIn(('close', False), self.backend.calls)

    def test_explicit_discard_closes_and_cleans_only_after_success(self):
        self.attach()
        self.backend.modified = True
        result = self.session.dispatch('close', {'discard': True})
        self.assertTrue(result['closed'])
        self.assertEqual([('close', True), ('cleanup',)], self.backend.calls[-2:])
        self.assert_code('invalid_state', 'status', {})


    def test_explicit_discard_can_close_after_runtime_status_failure(self):
        self.attach()
        self.backend.status = lambda: (_ for _ in ()).throw(RuntimeError('engine exited'))
        result = self.session.dispatch('close', {'discard': True})
        self.assertTrue(result['closed'])
        self.assertIn(('close', True), self.backend.calls)

    def test_failed_close_keeps_active_document(self):
        self.attach()
        self.backend.fail_close = True
        self.assert_code('close_failed', 'close', {})
        self.assertEqual('writer', self.session.dispatch('status', {})['module'])
        self.assertNotIn(('cleanup',), self.backend.calls)

    def test_failed_save_preserves_dirty_state_and_allows_retry(self):
        self.attach()
        self.backend.modified = True
        self.backend.fail_save = True
        path = self.root / 'saved.docx'
        self.assert_code('save_failed', 'save', {'path': str(path)})
        self.assertTrue(self.session.dispatch('status', {})['modified'])
        self.assert_code('invalid_state', 'save', {})
        self.backend.fail_save = False
        self.assertEqual(str(path), self.session.dispatch('save', {'path': str(path)})['path'])
        self.assertFalse(self.session.dispatch('status', {})['modified'])

    def test_save_filter_must_match_extension_and_module_allowlist(self):
        self.attach()
        for args in ({'path': str(self.root / 'bad.exe')},
                     {'path': str(self.root / 'ok.docx'), 'filter': 'calc8'},
                     {'filter': 'Office Open XML Text'}):
            with self.subTest(args=args):
                with self.assertRaises(self.session_module.WorkerError):
                    self.session.dispatch('save', args)
        self.assertFalse(any(c[0] == 'save' for c in self.backend.calls))

    def test_save_existing_preserves_format_and_explicit_save_as_selects_filter(self):
        path = self.root / 'open.docx'
        path.write_bytes(b'original')
        self.attach(path=str(path))
        self.session.dispatch('save', {})
        self.assertEqual(('save', None, None), self.backend.calls[-1])
        target = self.root / 'new.odt'
        self.session.dispatch('save', {'path': str(target), 'filter': 'writer8'})
        self.assertEqual(('save', target, 'writer8'), self.backend.calls[-1])

    def test_close_and_shutdown_never_treat_string_false_as_discard(self):
        self.attach()
        self.backend.modified = True
        self.assert_code('invalid_request', 'close', {'discard': 'false'})
        self.assert_code('invalid_request', 'shutdown', {'discard': 1})
        self.assertTrue(self.session.dispatch('status', {})['modified'])

    def test_shutdown_refuses_unsaved_changes_then_terminates_when_clean(self):
        self.attach()
        self.backend.modified = True
        self.assertTrue(self.session.dispatch('shutdown', {})['closeCancelled'])
        self.backend.modified = False
        self.assertTrue(self.session.dispatch('shutdown', {})['shutdown'])
        self.assert_code('invalid_state', 'attach', {})

    def test_resize_is_checked_then_forwarded(self):
        self.attach()
        self.assert_code('invalid_request', 'resize', {'width': 0, 'height': 10})
        self.session.dispatch('resize', {'width': 800, 'height': 600})
        self.assertEqual(('resize', 800, 600), self.backend.calls[-1])

    def test_protocol_reports_errors_preserves_ids_and_continues(self):
        incoming = io.StringIO('bad json\n' + json.dumps({'id': '한글', 'command': 'unknown', 'args': {}}) + '\n'
                               + json.dumps({'id': 9, 'command': 'shutdown', 'args': {}}) + '\n')
        outgoing = io.StringIO()
        self.worker_module.serve(self.session, incoming, outgoing)
        lines = [json.loads(x) for x in outgoing.getvalue().splitlines()]
        self.assertEqual([None, '한글', 9], [x['id'] for x in lines])
        self.assertEqual('invalid_json', lines[0]['error']['code'])
        self.assertEqual('unknown_command', lines[1]['error']['code'])
        self.assertTrue(lines[2]['ok'])

    def test_protocol_rejects_nonobject_args_and_ambiguous_ids(self):
        for request in ({'id': True, 'command': 'status', 'args': {}},
                        {'id': 1, 'command': 'status', 'args': []},
                        {'command': 'status', 'args': {}},
                        {'id': 1, 'command': 'status', 'args': {}, 'extra': 2}):
            with self.subTest(request=request):
                response = self.worker_module.handle_request(self.session, request)
                self.assertFalse(response['ok'])
                self.assertEqual('invalid_request', response['error']['code'])

    def test_missing_manifest_fails_closed(self):
        with self.assertRaises(self.session_module.WorkerError) as caught:
            self.worker_module.load_modules(self.root / 'missing.json')
        self.assertEqual('invalid_manifest', caught.exception.code)

    def test_manifest_rejects_nonfactory_module_for_office_worker(self):
        manifest = self.root / 'product.json'
        manifest.write_text(json.dumps({'schemaVersion': 1, 'modules': MODULES}), encoding='utf-8')
        self.assertEqual(MODULES, self.worker_module.load_modules(manifest))

    def test_protocol_nonfinite_id_does_not_break_json_output(self):
        outgoing = io.StringIO()
        self.worker_module.serve(self.session, io.StringIO('{"id":NaN,"command":"status","args":{}}\n'), outgoing)
        response = json.loads(outgoing.getvalue())
        self.assertIsNone(response['id'])
        self.assertEqual('invalid_request', response['error']['code'])

    def test_native_command_events_are_serialized_with_response_stream(self):
        self.backend.set_command_handler = lambda handler: setattr(self.backend, 'handler', handler)
        original_attach = self.backend.attach
        def attach_and_emit(*args):
            result = original_attach(*args)
            self.backend.handler('saveAs')
            return result
        self.backend.attach = attach_and_emit
        incoming = io.StringIO(json.dumps({'id': 1, 'command': 'attach',
            'args': {'parentHwnd': 123, 'module': 'writer', 'width': 640, 'height': 480}}) + '\n'
            + json.dumps({'id': 2, 'command': 'shutdown', 'args': {}}) + '\n')
        outgoing = io.StringIO()
        self.worker_module.serve(self.session, incoming, outgoing)
        lines = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual({'event': 'command', 'command': 'saveAs', 'module': 'writer'}, lines[0])
        self.assertEqual([1, 2], [line['id'] for line in lines[1:]])


    def test_new_calc_from_writer_preserves_validated_target_module(self):
        native = importlib.import_module('native')
        from types import SimpleNamespace
        events = []
        self.session.event_sink = events.append
        self.backend.set_command_handler = lambda handler: setattr(self.backend, 'handler', handler)
        self.attach()
        router = native.DispatchRouter(self.backend.handler)
        url = SimpleNamespace(Complete='private:factory/scalc')
        router.queryDispatch(url, '_blank', 0).dispatch(url, ())
        self.assertEqual([{'event': 'command', 'command': 'new', 'module': 'calc'}], events)

    def test_generic_new_preserves_current_writer_module(self):
        native = importlib.import_module('native')
        from types import SimpleNamespace
        events = []
        self.session.event_sink = events.append
        self.backend.set_command_handler = lambda handler: setattr(self.backend, 'handler', handler)
        self.attach()
        router = native.DispatchRouter(self.backend.handler)
        url = SimpleNamespace(Complete='.uno:NewDoc')
        router.queryDispatch(url, '_blank', 0).dispatch(url, ())
        self.assertEqual([{'event': 'command', 'command': 'new', 'module': 'writer'}], events)

    def test_malicious_factory_cannot_launch_or_reach_slave(self):
        native = importlib.import_module('native')
        from types import SimpleNamespace
        events, delegated = [], []
        self.session.event_sink = events.append
        self.backend.set_command_handler = lambda handler: setattr(self.backend, 'handler', handler)
        self.attach()
        router = native.DispatchRouter(self.backend.handler)
        router.setSlaveDispatchProvider(SimpleNamespace(queryDispatch=lambda *args: delegated.append(args)))
        for factory in ('private:factory/evil', 'private:factory/scalc?Interactive',
                        'private:factory/scalc/../../evil', 'private:factory/sdatabase?Interactive'):
            url = SimpleNamespace(Complete=factory)
            router.queryDispatch(url, '_blank', 0).dispatch(url, ())
        self.assertEqual([], events)
        self.assertEqual([], delegated)

    def test_protocol_eof_does_not_discard_dirty_document(self):
        self.attach()
        self.backend.modified = True
        self.worker_module.serve(self.session, io.StringIO(''), io.StringIO())
        self.assertTrue(self.session.dispatch('status', {})['modified'])
        self.assertNotIn(('cleanup',), self.backend.calls)


class NativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((WORKER / 'native.py').is_file(), 'missing native UNO backend')
        self.native = importlib.import_module('native')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_owned_runtime_launch_uses_unique_profile_and_private_pipe(self):
        from types import SimpleNamespace
        program = self.root / 'program'
        program.mkdir()
        (program / 'soffice.exe').write_bytes(b'fake boundary')
        (program / 'python.exe').write_bytes(b'fake boundary')
        calls = []
        process = SimpleNamespace(poll=lambda: None)
        backend = self.native.UnoBackend(self.root, process_factory=lambda argv, cwd: calls.append((argv, cwd)) or process)
        backend._start_runtime()
        self.addCleanup(backend.profile.cleanup)
        argv, cwd = calls[0]
        self.assertEqual(str(program / 'soffice.exe'), argv[0])
        self.assertTrue(any(x.startswith('--accept=pipe,name=OpenGeul_') for x in argv))
        self.assertFalse(any('socket' in x or '--headless' == x for x in argv))
        self.assertTrue(any(x.startswith('-env:UserInstallation=file:') for x in argv))
        self.assertNotEqual(self.root, Path(backend.profile.name))
        self.assertEqual(program, cwd)

    def test_connect_retry_has_deadline_and_detects_owned_process_exit(self):
        from types import SimpleNamespace
        ticks = iter([0.0, 0.0, 1.0, 3.0])
        resolver = SimpleNamespace(resolve=lambda url: (_ for _ in ()).throw(RuntimeError('not ready')))
        local = SimpleNamespace(ServiceManager=SimpleNamespace(createInstanceWithContext=lambda service, ctx: resolver))
        uno = SimpleNamespace(getComponentContext=lambda: local)
        with self.assertRaises(self.native.WorkerError) as caught:
            self.native.connect_uno(uno, 'unique', SimpleNamespace(poll=lambda: None),
                                    timeout=2, clock=lambda: next(ticks), sleeper=lambda duration: None)
        self.assertEqual('connect_timeout', caught.exception.code)
        with self.assertRaises(self.native.WorkerError) as caught:
            self.native.connect_uno(uno, 'unique', SimpleNamespace(poll=lambda: 1), timeout=2)
        self.assertEqual('engine_exited', caught.exception.code)

    def test_attach_registers_named_frame_and_loads_through_desktop(self):
        from types import SimpleNamespace
        calls = []
        peer = SimpleNamespace(setPosSize=lambda *a: calls.append(('resize', a)),
                               setVisible=lambda visible: calls.append(('visible', visible)),
                               getWindowHandle=lambda *a: 456)
        frame = SimpleNamespace(initialize=lambda p: calls.append(('initialize', p)),
                                setName=lambda n: calls.append(('name', n)),
                                registerDispatchProviderInterceptor=lambda i: calls.append(('interceptor', i)),
                                activate=lambda: None)
        document = SimpleNamespace(isModified=lambda: False, getTitle=lambda: 'Test')
        desktop = SimpleNamespace(getFrames=lambda: SimpleNamespace(append=lambda f: calls.append(('append', f))),
                                  loadComponentFromURL=lambda *a: calls.append(('load', a)) or document)
        toolkit = SimpleNamespace(createSystemChild=lambda *a: calls.append(('child', a)) or peer)
        services = {'com.sun.star.awt.Toolkit': toolkit, 'com.sun.star.frame.Frame': frame,
                    'com.sun.star.frame.Desktop': desktop}
        context = SimpleNamespace(ServiceManager=SimpleNamespace(createInstanceWithContext=lambda n, c: services[n]))
        uno = SimpleNamespace(Any=lambda t, value: (t, value), createUnoStruct=lambda name: SimpleNamespace())
        windows = SimpleNamespace(validate_parent=lambda hwnd: None, validate_child=lambda child, parent: calls.append(('validated', child, parent)))
        backend = self.native.UnoBackend(self.root, window_api=windows, uno_loader=lambda: uno,
                                         connector=lambda *a: context)
        backend._start_runtime = lambda: None
        with patch.object(self.native, 'make_interceptor', return_value=object()), patch.object(self.native, 'make_interaction_handler', return_value=object()):
            handles = backend.attach(123, MODULES['writer'], 640, 480, None)
        self.assertEqual({'parentHwnd': 123, 'childHwnd': 456}, handles)
        self.assertIs(context, backend.context)
        self.assertEqual(('hyper', 123), next(c[1][0] for c in calls if c[0] == 'child'))
        load = next(c[1] for c in calls if c[0] == 'load')
        self.assertEqual('private:factory/swriter', load[0])
        self.assertTrue(load[1].startswith('OpenGeul_'))
        self.assertEqual(4, load[2])
        props = {p.Name: p.Value for p in load[3]}
        self.assertEqual(0, props['MacroExecutionMode'])
        self.assertEqual(0, props['UpdateDocMode'])
        self.assertFalse(props['ReadOnly'])
        self.assertTrue(calls.index(('append', frame)) < next(i for i, c in enumerate(calls) if c[0] == 'load'))

    def test_native_save_failure_keeps_model_and_discard_close_veto_restores_dirty(self):
        from types import SimpleNamespace
        state = {'modified': True}
        def fail(*args):
            raise RuntimeError('veto or storage error')
        document = SimpleNamespace(isModified=lambda: state['modified'],
                                   setModified=lambda value: state.update(modified=value),
                                   close=fail, store=fail)
        backend = self.native.UnoBackend(self.root)
        backend.document = document
        with self.assertRaises(RuntimeError):
            backend.save(None, None)
        self.assertIs(document, backend.document)
        with self.assertRaises(RuntimeError):
            backend.close(True)
        self.assertTrue(state['modified'])
        self.assertIs(document, backend.document)


    def test_explicit_discard_handles_already_exited_owned_runtime(self):
        from types import SimpleNamespace
        backend = self.native.UnoBackend(self.root)
        backend.process = SimpleNamespace(poll=lambda: 1)
        model = SimpleNamespace(isModified=lambda: (_ for _ in ()).throw(RuntimeError('bridge gone')))
        backend.document = model
        backend.close(True)
        self.assertIsNone(backend.document)

    def test_cleanup_terminates_only_owned_process_before_removing_owned_profile(self):
        from types import SimpleNamespace
        calls = []
        process = SimpleNamespace(poll=lambda: None, wait=lambda timeout: calls.append(('wait', timeout)),
                                  terminate=lambda: calls.append(('terminate',)), close=lambda: calls.append(('close_handles',)))
        backend = self.native.UnoBackend(self.root)
        backend.process = process
        backend.profile = SimpleNamespace(cleanup=lambda: calls.append(('profile',)))
        backend.cleanup()
        self.assertEqual(('profile',), calls[-1])
        self.assertIn(('terminate',), calls)
        self.assertNotIn(('taskkill',), calls)

    def test_interceptor_routes_document_commands_and_delegates_formatting(self):
        from types import SimpleNamespace
        events, delegated = [], []
        router = self.native.DispatchRouter(lambda command, target_module=None: events.append(command))
        sentinel = object()
        router.setSlaveDispatchProvider(SimpleNamespace(queryDispatch=lambda *a: delegated.append(a) or sentinel))
        url = lambda name: SimpleNamespace(Complete=name)
        dispatch = router.queryDispatch(url('.uno:SaveAs'), '_self', 0)
        dispatch.dispatch(url('.uno:SaveAs'), ())
        self.assertEqual(['saveAs'], events)
        self.assertIs(sentinel, router.queryDispatch(url('.uno:Bold'), '_self', 0))
        self.assertEqual('.uno:Bold', delegated[0][0].Complete)
        for name, command in [('.uno:Quit', 'close'), ('.uno:Open', 'open'), ('.uno:NewWindow', 'new'),
                              ('private:factory/scalc', 'new'), ('file:///C:/Other.docx', 'open'),
                              ('.uno:SaveACopy', 'saveAs')]:
            router.queryDispatch(url(name), '_blank', 0).dispatch(url(name), ())
            self.assertEqual(command, events[-1])
        router.setSlaveDispatchProvider(router)
        self.assertIsNone(router.queryDispatch(url('.uno:Italic'), '_self', 0))


    def test_base_readiness_reports_configured_but_unconnected_java_driver(self):
        from types import SimpleNamespace
        data_source = SimpleNamespace(getPropertyValue=lambda name: 'sdbc:embedded:hsqldb')
        document = SimpleNamespace(DataSource=data_source,
                                   getCurrentController=lambda: SimpleNamespace(isConnected=lambda: False))
        readiness = self.native.base_readiness(document)
        self.assertTrue(readiness['dataSourceConfigured'])
        self.assertFalse(readiness['connectionVerified'])
        self.assertTrue(readiness['javaRequired'])
        self.assertIsNone(readiness['javaAvailable'])
        self.assertFalse(readiness['fullyVerified'])
        self.assertEqual('not_connected', readiness['state'])
        self.assertTrue(readiness['message'])

    def test_base_connected_flag_does_not_claim_all_module_dependencies_ready(self):
        from types import SimpleNamespace
        data_source = SimpleNamespace(getPropertyValue=lambda name: 'sdbc:embedded:firebird')
        document = SimpleNamespace(DataSource=data_source,
                                   getCurrentController=lambda: SimpleNamespace(isConnected=lambda: True))
        readiness = self.native.base_readiness(document)
        self.assertEqual('connected', readiness['state'])
        self.assertTrue(readiness['connectionVerified'])
        self.assertFalse(readiness['javaRequired'])
        self.assertIsNone(readiness['javaAvailable'])
        self.assertFalse(readiness['fullyVerified'])

    def test_base_missing_configuration_and_probe_failure_fail_gracefully(self):
        from types import SimpleNamespace
        document = SimpleNamespace(DataSource=SimpleNamespace(getPropertyValue=lambda name: ''),
                                   getCurrentController=lambda: SimpleNamespace(isConnected=lambda: False))
        readiness = self.native.base_readiness(document)
        self.assertEqual('not_configured', readiness['state'])
        self.assertFalse(readiness['dataSourceConfigured'])
        del document.DataSource
        backend = self.native.UnoBackend(self.root)
        backend.document = document
        backend.module_factory = 'private:factory/sdatabase'
        document.isModified = lambda: False
        document.getTitle = lambda: 'Database'
        result = backend.status()
        self.assertEqual('unverified', result['readiness']['state'])
        self.assertEqual('Database', result['title'])
        self.assertFalse(result['readiness']['fullyVerified'])

    def base_probe_boundary(self, url, driver=True, *, enabled=True, started=False,
                            driver_error=False, enabled_error=False):
        from types import SimpleNamespace
        calls = []
        def forbidden(*args):
            calls.append(('forbidden_connection_or_jvm_start',))
            raise AssertionError('A readiness probe must not connect a database or start Java')
        def get_driver(value):
            calls.append(('driver_url', value))
            if driver_error:
                raise RuntimeError('The driver registry could not be inspected')
            return SimpleNamespace(connect=forbidden) if driver else None
        def is_enabled():
            calls.append(('java_enabled',))
            if enabled_error:
                raise RuntimeError('The Java settings could not be inspected')
            return enabled
        vm = SimpleNamespace(isVMEnabled=is_enabled,
                             isVMStarted=lambda: calls.append(('java_started',)) or started,
                             getJavaVM=forbidden)
        manager = SimpleNamespace(getDriverByURL=get_driver, getConnection=forbidden,
                                  getConnectionWithInfo=forbidden)
        def create_service(name, context):
            calls.append(('service', name))
            return {'com.sun.star.sdbc.DriverManager': manager,
                    'com.sun.star.java.JavaVirtualMachine': vm}[name]
        context = SimpleNamespace(ServiceManager=SimpleNamespace(createInstanceWithContext=create_service))
        source = SimpleNamespace(getPropertyValue=lambda name: url, getConnection=forbidden)
        document = SimpleNamespace(DataSource=source,
                                   getCurrentController=lambda: SimpleNamespace(isConnected=lambda: False))
        return document, context, calls

    def test_base_native_driver_is_observed_without_connection_or_java_start(self):
        document, context, calls = self.base_probe_boundary('sdbc:embedded:firebird')
        readiness = self.native.base_readiness(document, context)
        self.assertTrue(readiness['driverAvailable'])
        self.assertFalse(readiness['javaRequired'])
        self.assertIsNone(readiness['javaAvailable'])
        self.assertIsNone(readiness['javaEnabled'])
        self.assertIsNone(readiness['javaStarted'])
        self.assertFalse(readiness['connectionVerified'])
        self.assertFalse(readiness['fullyVerified'])
        self.assertEqual([('service', 'com.sun.star.sdbc.DriverManager'),
                          ('driver_url', 'sdbc:embedded:firebird')], calls)
        self.assertIn('네이티브 드라이버', readiness['message'])
        self.assertIn('연결은 확인되지', readiness['message'])

    def test_base_missing_driver_is_a_fact_and_not_an_unknown_probe(self):
        document, context, calls = self.base_probe_boundary('sdbc:embedded:firebird', driver=False)
        readiness = self.native.base_readiness(document, context)
        self.assertIs(readiness['driverAvailable'], False)
        self.assertIn('드라이버를 찾지 못했습니다', readiness['message'])
        self.assertNotIn(('forbidden_connection_or_jvm_start',), calls)

    def test_base_java_enabled_but_not_started_does_not_establish_a_usable_jre(self):
        document, context, calls = self.base_probe_boundary('sdbc:embedded:hsqldb', enabled=True, started=False)
        readiness = self.native.base_readiness(document, context)
        self.assertTrue(readiness['driverAvailable'])
        self.assertTrue(readiness['javaRequired'])
        self.assertIs(readiness['javaEnabled'], True)
        self.assertIs(readiness['javaStarted'], False)
        self.assertIsNone(readiness['javaAvailable'])
        self.assertIn('JRE는 검증되지', readiness['message'])
        self.assertNotIn(('forbidden_connection_or_jvm_start',), calls)

    def test_base_disabled_java_explains_why_no_hsqldb_driver_accepts_the_url(self):
        document, context, calls = self.base_probe_boundary('sdbc:embedded:hsqldb', driver=False,
                                                          enabled=False, started=False)
        readiness = self.native.base_readiness(document, context)
        self.assertIs(readiness['driverAvailable'], False)
        self.assertIs(readiness['javaEnabled'], False)
        self.assertIs(readiness['javaStarted'], False)
        self.assertIsNone(readiness['javaAvailable'])
        self.assertIn('Java 사용이 꺼져', readiness['message'])
        self.assertNotIn(('forbidden_connection_or_jvm_start',), calls)

    def test_base_running_java_observation_survives_settings_probe_failure(self):
        document, context, calls = self.base_probe_boundary('jdbc:example:local', started=True, enabled_error=True)
        readiness = self.native.base_readiness(document, context)
        self.assertTrue(readiness['driverAvailable'])
        self.assertIsNone(readiness['javaEnabled'])
        self.assertIs(readiness['javaStarted'], True)
        self.assertIs(readiness['javaAvailable'], True)
        self.assertFalse(readiness['connectionVerified'])
        self.assertFalse(readiness['fullyVerified'])
        self.assertNotIn(('forbidden_connection_or_jvm_start',), calls)

    def test_base_driver_probe_failure_stays_unknown_and_java_is_still_observed(self):
        document, context, calls = self.base_probe_boundary('jdbc:example:local', driver_error=True,
                                                          enabled=True, started=False)
        readiness = self.native.base_readiness(document, context)
        self.assertIsNone(readiness['driverAvailable'])
        self.assertIs(readiness['javaEnabled'], True)
        self.assertIs(readiness['javaStarted'], False)
        self.assertIsNone(readiness['javaAvailable'])
        self.assertIn('드라이버 준비 상태를 확인하지 못했습니다', readiness['message'])
        self.assertNotIn(('forbidden_connection_or_jvm_start',), calls)

    def test_base_backend_status_uses_the_attached_runtime_context_for_readiness(self):
        document, context, calls = self.base_probe_boundary('sdbc:embedded:firebird')
        document.isModified = lambda: False
        document.getTitle = lambda: 'Base'
        backend = self.native.UnoBackend(self.root)
        backend.document, backend.context = document, context
        backend.module_factory = 'private:factory/sdatabase'
        self.assertTrue(backend.status()['readiness']['driverAvailable'])
        self.assertIn(('driver_url', 'sdbc:embedded:firebird'), calls)

    def test_base_missing_controller_does_not_turn_unknown_connection_into_disconnected(self):
        document, context, calls = self.base_probe_boundary('sdbc:embedded:firebird')
        document.getCurrentController = lambda: None
        readiness = self.native.base_readiness(document, context)
        self.assertEqual('unverified', readiness['state'])
        self.assertTrue(readiness['driverAvailable'])
        self.assertFalse(readiness['connectionVerified'])
        self.assertFalse(readiness['fullyVerified'])

    def test_uno_import_is_lazy_and_nonwindows_native_host_fails_closed(self):
        import os
        backend = self.native.UnoBackend(self.root)
        if os.name != 'nt':
            with self.assertRaises(self.native.WorkerError) as caught:
                backend.attach(1, MODULES['writer'], 10, 10, None)
            self.assertEqual('unsupported_platform', caught.exception.code)


if __name__ == '__main__':
    unittest.main()
