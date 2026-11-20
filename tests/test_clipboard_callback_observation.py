"""Pure reference-forwarding contract; no browser, OS clipboard or product run."""
import ast
import copy
import importlib.util
import json
import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'e2e/native_clipboard.py'
SPEC = importlib.util.spec_from_file_location('clipboard_observation_under_test', SOURCE)
API = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(API)

OWNER = {'hwnd': 101, 'pid': 11, 'creation': 1234567, 'session': 1, 'sequence': 3}
PACKET_KEYS = {
    'schemaVersion', 'diagnosticOnly', 'acceptanceEligible', 'qualification',
    'transportCode', 'clipboardOwner', 'installKnown', 'installed',
    'pageIdentityKnown', 'pageIdentityMatched', 'cleanupKnown', 'ownReferenceReleased',
    'callbackWindowMsKnown', 'callbackWindowMs', 'dirtyWaitMsKnown', 'dirtyWaitMs',
    'events', 'consoleTypeCounts', 'pageErrorNameCounts', 'overflow', 'optionalErrors',
    'errorOverflow', 'actualEventTimingKnown', 'handlerSuccessKnown', 'noErrorGuarantee',
}


class ProbeFault(RuntimeError):
    def __str__(self): raise AssertionError()
    def __repr__(self): raise AssertionError()


class OriginalTimeout(TimeoutError):
    def __str__(self): raise AssertionError()
    def __repr__(self): raise AssertionError()


class OriginalCancellation(KeyboardInterrupt):
    def __str__(self): raise AssertionError()
    def __repr__(self): raise AssertionError()


class SecondaryExit(SystemExit):
    def __str__(self): raise AssertionError()
    def __repr__(self): raise AssertionError()


class Clock:
    def __init__(self, values=(1, 2, 5, 7)):
        self.values = iter(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        value = next(self.values)
        if isinstance(value, BaseException): raise value
        return value


class Page:
    def __init__(self): self.rpc_reads = 0

    def __getattribute__(self, name):
        if name in ('on', 'remove_listener', 'once', 'evaluate', 'context',
                    'is_closed', 'wait_for_timeout', 'expect_event'):
            object.__setattr__(self, 'rpc_reads', object.__getattribute__(self, 'rpc_reads') + 1)
            raise ProbeFault()
        return object.__getattribute__(self, name)


class PoisonOS:
    def __init__(self): self.environment_reads = 0

    @property
    def environ(self):
        self.environment_reads += 1
        raise ProbeFault()


class Session:
    def __init__(self, page, fault=None, slot=None):
        self.page = page
        self.slot = slot
        self.fault = fault

    @property
    def _clipboard_callback_sink(self):
        if self.fault == 'get': raise ProbeFault()
        return self.slot

    @_clipboard_callback_sink.setter
    def _clipboard_callback_sink(self, value):
        action = 'clear' if value is None else 'bind'
        if self.fault == action + '-before': raise ProbeFault()
        self.slot = value
        if self.fault == action + '-after': raise ProbeFault()


class CancellationSession(Session):
    def __init__(self, page, mode, cancellation):
        super().__init__(page)
        self.cancel_mode, self.cancellation = mode, cancellation

    @Session._clipboard_callback_sink.setter
    def _clipboard_callback_sink(self, value):
        if value is None and self.cancel_mode == 'detach-before': raise self.cancellation
        self.slot = value
        if value is None and self.cancel_mode == 'detach-after': raise self.cancellation


class WaitPage(Page):
    def __init__(self, primary):
        super().__init__()
        self.primary, self.wait_calls = primary, 0

    def wait_for_function(self, predicate, *, timeout):
        if predicate != 'document.title.startsWith("• ")' or timeout != 30000:
            raise AssertionError()
        self.wait_calls += 1
        if self.primary is not None: raise self.primary


class Console:
    def __init__(self, value='warning', fault=False):
        self.value, self.fault, self.reads = value, fault, 0
        self.forbidden_reads = 0

    def forbidden(self):
        self.forbidden_reads += 1
        raise ProbeFault()

    @property
    def type(self):
        self.reads += 1
        if self.fault: raise ProbeFault()
        return self.value

    @property
    def text(self): return self.forbidden()
    @property
    def args(self): return self.forbidden()
    @property
    def location(self): return self.forbidden()
    def __str__(self): return self.forbidden()
    def __repr__(self): return self.forbidden()


class PageError:
    def __init__(self, value='TypeError', fault=False):
        self.value, self.fault, self.reads = value, fault, 0
        self.forbidden_reads = 0

    def forbidden(self):
        self.forbidden_reads += 1
        raise ProbeFault()

    @property
    def name(self):
        self.reads += 1
        if self.fault: raise ProbeFault()
        return self.value

    @property
    def message(self): return self.forbidden()
    @property
    def stack(self): return self.forbidden()
    @property
    def args(self): return self.forbidden()
    def __str__(self): return self.forbidden()
    def __repr__(self): return self.forbidden()


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.observation = getattr(API, 'ClipboardCallbackObservation', None)
        self.console = getattr(API, 'forward_clipboard_console', None)
        self.pageerror = getattr(API, 'forward_clipboard_pageerror', None)
        self.assertTrue(all(callable(item) for item in
            (self.observation, self.console, self.pageerror)), 'Required observation API absent')
        self.page = Page()
        self.session = Session(self.page)
        self.clock = Clock()
        self.written = []

    def make(self, **kwargs):
        kwargs.setdefault('enabled', True)
        return self.observation(self.session, self.page, 2, dict(OWNER),
            kwargs.pop('writer', self.written.append),
            clock=kwargs.pop('clock', self.clock), **kwargs)

    def wait(self, sink):
        sink.begin_wait()
        sink.end_wait()

    def closed_packet(self, value):
        self.assertTrue(type(value) is dict and set(value) == PACKET_KEYS)
        self.assertTrue(type(value['schemaVersion']) is int and value['schemaVersion'] == 1)
        self.assertTrue(value['diagnosticOnly'] is True)
        for key in ('acceptanceEligible', 'qualification', 'actualEventTimingKnown',
                    'handlerSuccessKnown', 'noErrorGuarantee'):
            self.assertTrue(value[key] is False)
        self.assertTrue(type(value['transportCode']) is int and value['transportCode'] in (1, 2))
        owner = value['clipboardOwner']
        self.assertTrue(owner is None or type(owner) is dict and set(owner) == set(OWNER)
            and all(type(v) is int for v in owner.values()))
        for known, duration in (('callbackWindowMsKnown', 'callbackWindowMs'),
                                ('dirtyWaitMsKnown', 'dirtyWaitMs')):
            self.assertTrue(type(value[known]) is bool)
            self.assertTrue(type(value[duration]) is int and value[duration] >= 0
                if value[known] else value[duration] is None)
        self.assertTrue(type(value['events']) is list and len(value['events']) <= 8)
        for row in value['events']:
            self.assertTrue(type(row) is list and len(row) == 3
                and type(row[0]) is int and row[0] in (1, 2)
                and type(row[1]) is int and row[1] >= 0 and type(row[2]) is bool)
        for key, length in (('consoleTypeCounts', 20), ('pageErrorNameCounts', 16)):
            self.assertTrue(type(value[key]) is list and len(value[key]) == length
                and all(type(v) is int and v >= 0 for v in value[key]))
        self.assertTrue(type(value['optionalErrors']) is list and len(value['optionalErrors']) <= 4)
        self.assertTrue(all(type(row) is list and len(row) == 2
            and all(type(v) is int for v in row) for row in value['optionalErrors']))
        self.assertTrue(type(value['overflow']) is bool and type(value['errorOverflow']) is bool)
        self.assertTrue(self.page.rpc_reads == 0)

    def test_cached_properties_and_exact_numeric_packet(self):
        with self.make() as sink:
            self.console(self.session, self.page, Console('warning'))
            self.console(self.session, self.page, Console('error'))
            self.pageerror(self.session, self.page, PageError('TypeError'))
            self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(row['events'] == [[1, 19, True], [1, 8, True], [2, 2, True]])
        self.assertTrue(row['consoleTypeCounts'][19] == row['consoleTypeCounts'][8] == 1)
        self.assertTrue(row['pageErrorNameCounts'][2] == 1 and row['pageErrorNameCounts'][0] == 0)
        self.assertTrue(row['installKnown'] is True and row['installed'] is True
            and row['pageIdentityKnown'] is True and row['pageIdentityMatched'] is True)
        self.assertTrue(row['cleanupKnown'] is True and row['ownReferenceReleased'] is True)
        self.assertTrue(row['callbackWindowMs'] == 6000 and row['dirtyWaitMs'] == 3000)
        self.assertTrue(self.clock.calls == 4 and self.session.slot is None
            and row['optionalErrors'] == [] and len(self.written) == 1 and sink.write_known is True)

    def test_unknown_values_are_codes_without_raw_strings(self):
        with self.make() as sink:
            self.console(self.session, self.page, Console('not-an-allowed-console-type'))
            self.pageerror(self.session, self.page, PageError('not-an-allowed-error-name'))
            self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(row['events'] == [[1, 0, False], [2, 0, False]])
        self.assertTrue(row['consoleTypeCounts'][0] == row['pageErrorNameCounts'][0] == 1)

    def test_other_page_and_changed_session_do_not_read_properties(self):
        message, error, other = Console(), PageError(), Page()
        with self.make() as sink:
            self.console(self.session, other, message)
            self.pageerror(self.session, other, error)
            self.session.page = other
            self.console(self.session, self.page, message)
            self.pageerror(self.session, self.page, error)
            self.session.page = self.page
            self.wait(sink)
        self.assertTrue(message.reads == error.reads == 0 and sink.packet()['events'] == [])

    def test_event_cap_preserves_bounded_counts(self):
        ninth, late_error = Console(fault=True), PageError(fault=True)
        with self.make() as sink:
            for _ in range(8): self.console(self.session, self.page, Console('error'))
            self.console(self.session, self.page, ninth)
            self.pageerror(self.session, self.page, late_error)
            self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(len(row['events']) == 8 and row['overflow'] is True
            and row['consoleTypeCounts'][8] == 8 and sum(row['consoleTypeCounts']) == 8
            and sum(row['pageErrorNameCounts']) == 0 and row['optionalErrors'] == [])
        self.assertTrue(ninth.reads == late_error.reads == 0)

    def test_disabled_is_noop_without_clock_or_writer(self):
        foreign = object(); self.session.slot = foreign
        with self.make(enabled=False) as sink: self.wait(sink)
        self.assertTrue(self.clock.calls == 0 and self.written == [] and self.session.slot is foreign)

    def test_constructor_without_enabled_is_noop_before_during_and_after_context(self):
        message, error = Console(), PageError()
        observation = self.observation(self.session, self.page, 2, dict(OWNER),
            self.written.append, clock=self.clock)
        checks = [self.session.slot is None and self.clock.calls == 0 and self.written == []]
        self.console(self.session, self.page, message)
        self.pageerror(self.session, self.page, error)
        with observation as sink:
            self.console(self.session, self.page, message)
            self.pageerror(self.session, self.page, error)
            self.wait(sink)
            checks.append(self.session.slot is None and self.clock.calls == 0 and self.written == [])
        self.console(self.session, self.page, message)
        self.pageerror(self.session, self.page, error)
        checks.append(self.session.slot is None and self.clock.calls == 0 and self.written == []
            and message.reads == error.reads == 0 and self.page.rpc_reads == 0)
        self.assertTrue(all(checks))

    def test_foreign_reference_is_not_overwritten(self):
        foreign = object(); self.session.slot = foreign
        with self.make() as sink: self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(self.session.slot is foreign and row['installed'] is False and len(self.written) == 1)

    def test_foreign_replacement_is_not_cleared(self):
        foreign = object()
        with self.make() as sink:
            self.session.slot = foreign
            self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(self.session.slot is foreign and row['cleanupKnown'] is False)

    def test_wrong_initial_page_is_not_bound(self):
        self.session.page = Page()
        with self.make() as sink: self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(row['pageIdentityKnown'] is True and row['pageIdentityMatched'] is False
            and row['installed'] is False and self.session.slot is None)

    def test_nonfinite_and_backward_window_clock_are_unknown(self):
        for values in ((float('nan'), 2, 5, 7), (1, 2, 5, float('inf')), (5, 6, 7, 4)):
            with self.make(clock=Clock(values)) as sink: self.wait(sink)
            row = sink.packet(); self.closed_packet(row)
            self.assertTrue(row['callbackWindowMsKnown'] is False and row['callbackWindowMs'] is None)

    def test_backward_wait_clock_is_unknown(self):
        with self.make(clock=Clock((1, 5, 4, 7))) as sink: self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(row['dirtyWaitMsKnown'] is False and row['dirtyWaitMs'] is None)

    def test_clock_exception_is_optional(self):
        with self.make(clock=Clock((ProbeFault(), 2, 5, 7))) as sink: self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(row['callbackWindowMsKnown'] is False and len(row['optionalErrors']) >= 1)

    def test_giant_clock_results_preserve_primary_and_mark_timing_unknown(self):
        giant = 10**1000
        cases = [((1, 2, giant, 7), 2), ((1, 2, 5, giant), 3),
                 ((giant, 2, 5, 7), 0), ((1, giant, 5, 7), 1)]
        for index in range(4):
            values = [1, 2, 5, 7]; values[index] = -giant
            cases.append((tuple(values), index))
        checks = []
        for values, index in cases:
            self.session.slot = None
            original, caught = OriginalTimeout(), None
            observation = self.make(clock=Clock(values))
            try:
                with observation as sink:
                    sink.begin_wait()
                    try: raise original
                    finally: sink.end_wait()
            except BaseException as error:
                caught = error
            row = observation.packet(); self.closed_packet(row)
            known, duration = (('callbackWindowMsKnown', 'callbackWindowMs') if index in (0, 3)
                               else ('dirtyWaitMsKnown', 'dirtyWaitMs'))
            checks.append(caught is original and self.session.slot is None
                and row[known] is False and row[duration] is None and len(row['optionalErrors']) >= 1)
            encoded = json.dumps(row, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
            checks.append(len(encoded) <= 8192)
            self.session.slot = None
        self.assertTrue(all(checks))

    def cancellation_case(self, primary, secondary, site):
        self.page = WaitPage(primary)
        self.session = CancellationSession(self.page, site, secondary)
        values = [1, 2, 5, 7]
        if site == 'wait-clock': values[2] = secondary
        if site == 'window-clock': values[3] = secondary
        def writer(_packet):
            if site == 'writer': raise secondary
        observation = self.make(clock=Clock(values), writer=writer)
        fragment = actual_wait_fragment()
        caught = None
        try:
            with observation:
                fragment(self, observation)
        except BaseException as error:
            caught = error
        return caught, observation

    def test_secondary_cancellation_never_replaces_incoming_primary(self):
        checks = []
        for primary_type in (OriginalTimeout, OriginalCancellation):
            for secondary_type in (OriginalCancellation, SecondaryExit):
                for site in ('wait-clock', 'window-clock', 'detach-before', 'detach-after', 'writer'):
                    primary, secondary = primary_type(), secondary_type()
                    caught, observation = self.cancellation_case(primary, secondary, site)
                    checks.append(caught is primary and self.page.wait_calls == 1)
                    if site != 'detach-before': checks.append(self.session.slot is None)
                    if site.startswith('detach-'):
                        checks.append(observation.packet()['cleanupKnown'] is False)
                    if site == 'writer': checks.append(observation.write_known is False)
                    self.session.slot = None
        self.assertTrue(all(checks))

    def test_new_cancellation_without_incoming_primary_propagates(self):
        checks = []
        for secondary_type in (OriginalCancellation, SecondaryExit):
            for site in ('wait-clock', 'window-clock', 'detach-before', 'detach-after', 'writer'):
                secondary = secondary_type()
                caught, _observation = self.cancellation_case(None, secondary, site)
                checks.append(caught is secondary and self.page.wait_calls == 1)
                self.session.slot = None
        self.assertTrue(all(checks))

    def test_reference_registration_faults_are_optional(self):
        for mode in ('bind-before', 'bind-after'):
            self.session.fault = mode
            with self.make(clock=Clock()) as sink:
                self.session.fault = None
                self.wait(sink)
            row = sink.packet(); self.closed_packet(row)
            self.assertTrue(len(row['optionalErrors']) >= 1 and self.session.slot is None)

    def test_reference_cleanup_faults_before_and_after_mutation(self):
        for mode in ('clear-before', 'clear-after'):
            self.session.slot = None
            self.session.fault = None
            with self.make(clock=Clock()) as sink:
                self.wait(sink); self.session.fault = mode
            row = sink.packet(); self.closed_packet(row)
            self.assertTrue(row['cleanupKnown'] is False and len(row['optionalErrors']) >= 1)
            self.assertTrue(self.session.slot is sink if mode == 'clear-before' else self.session.slot is None)
            self.session.fault = None
            late = Console(); self.console(self.session, self.page, late)
            self.assertTrue(late.reads == 0)

    def test_reference_read_fault_is_optional(self):
        self.session.fault = 'get'
        with self.make() as sink:
            self.session.fault = None
            self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(len(row['optionalErrors']) >= 1)

    def test_callback_getter_faults_are_bounded_without_text_access(self):
        with self.make() as sink:
            for _ in range(12):
                self.console(self.session, self.page, Console(fault=True))
                self.pageerror(self.session, self.page, PageError(fault=True))
            self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(len(row['optionalErrors']) == 4 and row['errorOverflow'] is True)

    def test_new_calls_do_not_touch_environment_or_forbidden_event_properties(self):
        original_os, poison = API.os, PoisonOS()
        message, error = Console('warning'), PageError('TypeError')
        API.os = poison
        try:
            with self.make() as sink:
                self.console(self.session, self.page, message)
                self.pageerror(self.session, self.page, error)
                self.wait(sink)
                sink.packet()
            row = sink.packet()
        finally:
            API.os = original_os
        self.closed_packet(row)
        self.assertTrue(poison.environment_reads == 0
            and message.forbidden_reads == error.forbidden_reads == 0
            and message.reads == error.reads == 1 and row['optionalErrors'] == [])

    def test_maximum_packet_is_numeric_bounded_and_ascii_serializable(self):
        with self.make() as sink:
            for _ in range(5): self.console(self.session, self.page, Console(fault=True))
            for _ in range(12): self.console(self.session, self.page, Console('error'))
            self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(len(row['events']) == 8 and len(row['optionalErrors']) == 4
            and row['overflow'] is True and row['errorOverflow'] is True)
        counts = row['consoleTypeCounts'] + row['pageErrorNameCounts']
        self.assertTrue(all(type(value) is int and 0 <= value <= 8 for value in counts)
            and sum(counts) <= 8)
        def numeric(value):
            if type(value) is dict:
                return all(type(key) is str and numeric(child) for key, child in value.items())
            if type(value) is list: return all(numeric(child) for child in value)
            return value is None or type(value) in (int, bool)
        self.assertTrue(numeric(row))
        encoded = json.dumps(row, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
        self.assertTrue(len(encoded) <= 8192)

    def test_writer_fault_is_optional_and_does_not_self_certify(self):
        def writer(_packet): raise ProbeFault()
        with self.make(writer=writer) as sink: self.wait(sink)
        row = sink.packet(); self.closed_packet(row)
        self.assertTrue(sink.write_known is False and len(row['optionalErrors']) >= 1)

    def test_original_timeout_identity_survives_writer_fault(self):
        original = OriginalTimeout()
        def writer(_packet): raise ProbeFault()
        caught = None
        try:
            with self.make(writer=writer) as sink:
                self.wait(sink); raise original
        except BaseException as error: caught = error
        self.assertTrue(caught is original and self.session.slot is None and sink.write_known is False)

    def test_original_cancellation_identity_survives_optional_faults(self):
        original = OriginalCancellation()
        def writer(_packet): raise ProbeFault()
        caught = None
        try:
            with self.make(writer=writer) as sink:
                self.wait(sink); self.session.fault = 'clear-before'; raise original
        except BaseException as error: caught = error
        self.assertTrue(caught is original and sink.write_known is False)

    def test_retired_sink_does_not_read_late_callback_properties(self):
        with self.make() as sink: self.wait(sink)
        self.session.slot = sink
        message, error = Console(), PageError()
        self.console(self.session, self.page, message)
        self.pageerror(self.session, self.page, error)
        self.assertTrue(message.reads == error.reads == 0)


E2E = ROOT / 'e2e'

# Fixed public a64/V2 source contracts; expected values are never derived from the tested output.
BASE_CLIPBOARD_PREFIX_BYTES = 24779
BASE_CLIPBOARD_PREFIX_SHA256 = '289c753ef727d5973424d34fdbb66d46398bf046a3d9be018949f3d1ab33628d'
BASE_CLIPBOARD_AST_ITEMS = 29
BASE_CLIPBOARD_AST_SHA256 = 'fb493593b5d91d0f0c9d61db09ed0fc9b5ef9de97cdcb034f6c571ad43358208'
BASE_EXTERNAL_CASE_AST_SHA256 = 'cb369a99d64fdbe70747e016855c356e7f59551608776e836cb1054291d67296'
BASE_HTML_METHOD_AST_SHA256 = '6e6cc6abed76189bc539aafb2a80ec99687927a06155fef43d89774d282dd93d'
V2_AST_SHA256 = {'native_clipboard.py': '37fd70f9132bc913f54fa4b21ae4c04ec859f07ea3bd610930dd2feeaf4a003a', 'native_clipboard_cases.py': '032c84041ffde8580ff57051f0d35553a883223ce4c6e17c7a3cba547dade4ac'}
V2_UNCHANGED_FILE_SHA256 = {'driver.py': '97ba96f985037a715cbf0df36782b75bdab4c4829b12583f56f047a846b456a6', 'native_document_windows.py': '167dbe3e619cae05ace7ac142c0cbaf0783d4e9f4a1846efabefcad4ae2cc8c2'}
BASE_SUBSCRIPTIONS = {'driver.py': [('on', 'self.page', 'console'), ('on', 'self.page', 'pageerror'), ('on', 'self.page', 'request'), ('on', 'self.page', 'dialog')], 'native_document_windows.py': [('remove_listener', 'session.page', 'dialog'), ('on', 'session.page', 'dialog'), ('on', 'page', 'console'), ('on', 'page', 'pageerror'), ('on', 'page', 'request'), ('on', 'page', 'dialog')]}

LEGACY_APPEND = {
    'driver.py': {
        'console': "self.messages.append({'type':message.type,'text':message.text})",
        'pageerror': 'self.errors.append(str(error))',
    },
    'native_document_windows.py': {
        'console': "self.session.messages.append({'type':message.type,'text':message.text,'pageKey':key})",
        'pageerror': "self.session.errors.append(f'{key}: {error}')",
    },
}


def source_tree(name):
    return ast.parse((E2E / name).read_bytes())


def ast_shape(value):
    # Iterated semantic fields avoid interpreter-specific ast.dump formatting.
    if isinstance(value, ast.AST):
        return [type(value).__name__, [[key, ast_shape(child)]
            for key, child in ast.iter_fields(value)
            if not (key == 'type_params' and child == [])]]
    if isinstance(value, (list, tuple)): return [ast_shape(child) for child in value]
    if isinstance(value, bytes): return ['bytes', value.hex()]
    if value is Ellipsis: return ['ellipsis']
    return value


def ast_digest(value):
    encoded = json.dumps(ast_shape(value), ensure_ascii=True, allow_nan=False,
        separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def same_ast(left, right):
    return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)


def method(tree, owner, name):
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    return next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)


def calls(tree, name):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and (isinstance(node.func, ast.Name) and node.func.id == name
             or isinstance(node.func, ast.Attribute) and node.func.attr == name)]


def without_warning_location_sidecar(tree):
    """Remove only the reviewed opt-in delta, then retain the original v2 hash."""
    tree=copy.deepcopy(tree)
    additions={
        '_cb_native_dict':'f9c19d927447cd5d6a3fad201dfd4ddafdd6805f80de4c72d54bfdcb1d0efe44',
        '_cb_cached_warning_location':'06068432bf7f9195b568a907aed87fd70bdae6219052faea49273116282f8506',
        '_cb_record_warning_location':'a4eba77ecd917e830a30e41984ca121b6e0eb8955b22311b16d70c75fb44de26',
        '_cb_write_warning_locations':'f884d96755e3106084bf9b74cc119248db94ef21052293cd31c4132cdcacdf04',
    }
    for name,digest in additions.items():
        matches=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name]
        assert len(matches)==1 and ast_digest(matches[0])==digest
        tree.body.remove(matches[0])
    for source in ('import sys as _cb_sys','import types as _cb_types'):
        expected=ast.parse(source).body[0]
        matches=[node for node in tree.body if same_ast(node,expected)]
        assert len(matches)==1
        tree.body.remove(matches[0])
    init=method(tree,'ClipboardCallbackObservation','__init__')
    wanted=ast.parse('def f(self,session,page,transport_code,owner,writer,*,clock=time.monotonic,enabled=False,location_writer=None): pass').body[0].args
    assert same_ast(init.args,wanted)
    init.args.kwonlyargs.pop();init.args.kw_defaults.pop()
    for source in reversed(('self._location_writer=location_writer','self._warning_locations=[]')):
        assert same_ast(init.body[-1],ast.parse(source).body[0])
        init.body.pop()
    finalizer=method(tree,'ClipboardCallbackObservation','__exit__')
    writes=[node for node in ast.walk(finalizer) if isinstance(node,ast.FunctionDef) and node.name=='write_packet']
    assert len(writes)==1 and same_ast(writes[0].body[-1],ast.parse('_cb_write_warning_locations(self)').body[0])
    writes[0].body.pop()
    forwards=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_forward_clipboard_callback']
    assert len(forwards)==1
    expected=ast.parse('if kind==1 and code==19 and sink._location_writer is not None:\n    _cb_record_warning_location(sink,event)').body[0]
    assert same_ast(forwards[0].body[0].body[-1],expected)
    forwards[0].body[0].body.pop()
    return tree


FOCUS_FAILURE_INVERSE_SHA256 = 'd6a4e158807b0f9f501f42bb3f47b42352d6c45584647163cb088d4f7da49f46'
FOCUS_FAILURE_INVERSE_PATH = ROOT / 'tests/fixtures/native-focus-failure-inverse-634247d4.json'


def without_reviewed_focus_failure(name, raw):
    """Reverse only this pinned diagnostic hunk before the unchanged v2 byte hash."""
    if name != 'native_document_windows.py':
        return raw
    if type(raw) is not bytes or not 0 < len(raw) <= 1024*1024:
        raise ValueError('Unreviewed native-document bytes')
    encoded = FOCUS_FAILURE_INVERSE_PATH.read_bytes()
    if not 0 < len(encoded) <= 32768 or hashlib.sha256(encoded).hexdigest() != FOCUS_FAILURE_INVERSE_SHA256:
        raise ValueError('Unreviewed focus inverse fixture')
    fixture = json.loads(encoded)
    if (type(fixture) is not dict or set(fixture) != {'schemaVersion','file','beforeBytes','beforeSha256','afterBytes','afterSha256','hunks'}
            or type(fixture['schemaVersion']) is not int or fixture['schemaVersion'] != 1
            or fixture['file'] != name or fixture['beforeSha256'] != V2_UNCHANGED_FILE_SHA256[name]
            or any(type(fixture[key]) is not int or not 0 < fixture[key] <= 1024*1024 for key in ('beforeBytes','afterBytes'))
            or len(raw) != fixture['afterBytes'] or hashlib.sha256(raw).hexdigest() != fixture['afterSha256']
            or type(fixture['hunks']) is not list or len(fixture['hunks']) != 1):
        raise ValueError('Unreviewed focus inverse context')
    lines = raw.splitlines(keepends=True)
    for hunk in reversed(fixture['hunks']):
        if (type(hunk) is not dict or set(hunk) != {'afterStart','beforeLines','afterLines'}
                or type(hunk['afterStart']) is not int or not 0 <= hunk['afterStart'] <= len(lines)
                or any(type(hunk[key]) is not list or not 0 < len(hunk[key]) <= 128
                       or any(type(line) is not str or len(line) > 4096 for line in hunk[key])
                       for key in ('beforeLines','afterLines'))):
            raise ValueError('Unreviewed focus inverse hunk')
        start = hunk['afterStart']; after = [line.encode('utf-8') for line in hunk['afterLines']]
        if lines[start:start+len(after)] != after:
            raise ValueError('Focus inverse slice differs')
        lines[start:start+len(after)] = [line.encode('utf-8') for line in hunk['beforeLines']]
    restored = b''.join(lines)
    if len(restored) != fixture['beforeBytes'] or hashlib.sha256(restored).hexdigest() != V2_UNCHANGED_FILE_SHA256[name]:
        raise ValueError('Original v2 byte guard differs')
    return restored


def actual_wait_fragment():
    current = method(source_tree('native_clipboard_cases.py'), 'NativeClipboardCases', '_external_case')
    wrapper = next(node for node in ast.walk(current) if isinstance(node, ast.With)
        and len(node.items) == 1 and isinstance(node.items[0].context_expr, ast.Name)
        and node.items[0].context_expr.id == 'observation')
    first = next(index for index, node in enumerate(wrapper.body) if calls(node, 'begin_wait'))
    last = next(index for index in range(first, len(wrapper.body)) if isinstance(wrapper.body[index], ast.Try))
    arguments = ast.arguments(posonlyargs=[], args=[ast.arg(arg='self'), ast.arg(arg='observation')],
        kwonlyargs=[], kw_defaults=[], defaults=[])
    function = ast.FunctionDef(name='actual_wait', args=arguments,
        body=copy.deepcopy(wrapper.body[first:last+1]), decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {}
    exec(compile(module, '<public-candidate-wait-fragment>', 'exec'), namespace)
    return namespace['actual_wait']


def primary_capture_try(node):
    if not isinstance(node, ast.Try) or node.orelse or len(node.handlers) != 1 or len(node.finalbody) != 1:
        return False
    handler = node.handlers[0]
    expected_handler = ast.parse('try:\n pass\nexcept BaseException as wait_error:\n wait_primary=wait_error\n raise').body[0].handlers[0]
    expected_final = ast.parse('observation.end_wait(primary=wait_primary)').body[0]
    return same_ast(handler, expected_handler) and same_ast(node.finalbody[0], expected_final)


def subscribed(tree):
    values = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr in ('on', 'remove_listener')]
    return sorted(values, key=lambda node: (node.lineno, node.col_offset))


class StripObservation(ast.NodeTransformer):
    def statements(self, body):
        output = []
        for child in body:
            value = self.visit(child)
            if type(value) is list: output.extend(value)
            elif value is not None: output.append(value)
        return output

    def visit_Assign(self, node):
        if any(isinstance(target, ast.Name) and target.id == 'observation' for target in node.targets):
            return None
        if same_ast(node, ast.parse('wait_primary=None').body[0]):
            return None
        return self.generic_visit(node)

    def visit_Expr(self, node):
        value = node.value
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name) and value.func.value.id == 'observation'
                and value.func.attr in ('begin_wait', 'end_wait')):
            return None
        return self.generic_visit(node)

    def visit_With(self, node):
        if len(node.items) == 1 and isinstance(node.items[0].context_expr, ast.Name) and node.items[0].context_expr.id == 'observation':
            return self.statements(node.body)
        return self.generic_visit(node)

    def visit_Try(self, node):
        if primary_capture_try(node):
            return self.statements(node.body)
        return self.generic_visit(node)


class SourceContractTests(unittest.TestCase):
    def forwarding(self, name, owner, function, session_expression, page_expression):
        candidate = source_tree(name)
        current = method(candidate, owner, function)
        imported = {alias.name for node in candidate.body if isinstance(node, ast.ImportFrom)
            and node.module == 'native_clipboard' for alias in node.names if alias.asname is None}
        self.assertTrue({'forward_clipboard_console', 'forward_clipboard_pageerror'} <= imported)
        for event, parameter, forward in (('console', 'message', 'forward_clipboard_console'),
                                           ('pageerror', 'error', 'forward_clipboard_pageerror')):
            handler_name = 'clipboard_' + ('console' if event == 'console' else 'pageerror') + '_handler'
            handlers = [node for node in ast.walk(current) if isinstance(node, ast.FunctionDef) and node.name == handler_name]
            self.assertTrue(len(handlers) == 1)
            handler = handlers[0]
            self.assertTrue([arg.arg for arg in handler.args.args] == [parameter, 'bound_page']
                and len(handler.args.defaults) == 1
                and same_ast(handler.args.defaults[0], ast.parse(page_expression, mode='eval').body))
            self.assertTrue(len(handler.body) == 2
                and same_ast(handler.body[0], ast.parse(LEGACY_APPEND[name][event]).body[0]))
            expected = ast.parse(forward + '(' + session_expression + ',bound_page,' + parameter + ')').body[0]
            self.assertTrue(same_ast(handler.body[1], expected))
            registrations = [node for node in subscribed(current)
                if node.func.attr == 'on' and isinstance(node.args[0], ast.Constant) and node.args[0].value == event]
            self.assertTrue(len(registrations) == 1 and isinstance(registrations[0].args[1], ast.Name)
                and registrations[0].args[1].id == handler_name)

    def test_helper_is_append_only_without_subscription_or_private_payload_access(self):
        raw = (E2E / 'native_clipboard.py').read_bytes()
        self.assertTrue(len(raw) >= BASE_CLIPBOARD_PREFIX_BYTES
            and hashlib.sha256(raw[:BASE_CLIPBOARD_PREFIX_BYTES]).hexdigest() == BASE_CLIPBOARD_PREFIX_SHA256)
        candidate = source_tree('native_clipboard.py')
        prefix = ast.Module(body=candidate.body[:BASE_CLIPBOARD_AST_ITEMS], type_ignores=[])
        self.assertTrue(ast_digest(prefix) == BASE_CLIPBOARD_AST_SHA256)
        addition = ast.Module(body=candidate.body[BASE_CLIPBOARD_AST_ITEMS:], type_ignores=[])
        forbidden = {'on', 'remove_listener', 'once', 'evaluate', 'evaluate_handle', 'new_cdp_session',
                     'send', 'environ', 'text', 'args', 'location', 'message', 'stack'}
        self.assertTrue(not any(isinstance(node, ast.Attribute) and node.attr in forbidden for node in ast.walk(addition)))
        self.assertTrue(not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ('str', 'repr', 'eval', 'exec') for node in ast.walk(addition)))

    def test_original_subscription_count_and_order_are_unchanged(self):
        for name, expected in BASE_SUBSCRIPTIONS.items():
            actual = subscribed(source_tree(name))
            self.assertTrue(len(actual) == len(expected))
            for node, (operation, receiver, event) in zip(actual, expected):
                self.assertTrue(node.func.attr == operation
                    and same_ast(node.func.value, ast.parse(receiver, mode='eval').body)
                    and same_ast(node.args[0], ast.Constant(value=event)))

    def test_driver_forwards_after_original_append_and_initializes_own_slot(self):
        current = method(source_tree('driver.py'), 'Session', '__init__')
        slots = [node for node in ast.walk(current) if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Attribute) and target.attr == '_clipboard_callback_sink'
                    and isinstance(target.value, ast.Name) and target.value.id == 'self' for target in node.targets)]
        self.assertTrue(len(slots) == 1 and isinstance(slots[0].value, ast.Constant) and slots[0].value.value is None)
        self.forwarding('driver.py', 'Session', '__init__', 'self', 'self.page')

    def test_new_document_forwards_after_original_append_with_bound_page(self):
        self.forwarding('native_document_windows.py', 'OwnedDocumentWindows', 'new', 'self.session', 'page')

    def test_runtime_optin_changes_only_exact_signature_enabled_and_bitmap_keyword(self):
        normalized = copy.deepcopy(source_tree('native_clipboard_cases.py'))
        function = method(normalized, 'NativeClipboardCases', '_external_case')
        new_args = ast.parse('def f(self,kind,transport,*,observe_callbacks=False): pass').body[0].args
        self.assertTrue(same_ast(function.args, new_args))
        function.args = ast.parse('def f(self,kind,transport): pass').body[0].args
        constructors = calls(function, 'ClipboardCallbackObservation')
        self.assertTrue(len(constructors) == 1)
        enabled = next(item for item in constructors[0].keywords if item.arg == 'enabled')
        new_enabled = ast.parse("kind=='bitmap' and observe_callbacks is True and current.page is self.page", mode='eval').body
        self.assertTrue(same_ast(enabled.value, new_enabled))
        enabled.value = ast.parse("kind=='bitmap' and getattr(self,'observe_clipboard_callbacks',False)is True and current.page is self.page", mode='eval').body
        locations=[item for item in constructors[0].keywords if item.arg=='location_writer']
        wanted_location=ast.parse("lambda packet:self._native_input_receipt(f'{kind}-{transport}-warning-location.numeric.json',packet)",mode='eval').body
        self.assertTrue(len(locations)==1 and same_ast(locations[0].value,wanted_location))
        constructors[0].keywords.remove(locations[0])
        bitmap = method(normalized, 'NativeClipboardCases', 'test_supported_external_os_bitmap_menu_keyboard_atomic_roundtrip')
        invocations = calls(bitmap, '_external_case')
        wanted = ast.parse("self._external_case('bitmap',transport,observe_callbacks=True)", mode='eval').body
        self.assertTrue(len(invocations) == 1 and same_ast(invocations[0], wanted))
        invocations[0].keywords = []
        self.assertTrue(ast_digest(normalized) == V2_AST_SHA256['native_clipboard_cases.py'])
        html = method(source_tree('native_clipboard_cases.py'), 'NativeClipboardCases',
            'test_supported_external_os_html_menu_keyboard_atomic_roundtrip')
        self.assertTrue(ast_digest(html) == BASE_HTML_METHOD_AST_SHA256)
        for name, expected_sha in V2_UNCHANGED_FILE_SHA256.items():
            self.assertTrue(hashlib.sha256(without_reviewed_focus_failure(name, (E2E / name).read_bytes())).hexdigest() == expected_sha)
        normalized_helper = without_warning_location_sidecar(source_tree('native_clipboard.py'))
        init = method(normalized_helper, 'ClipboardCallbackObservation', '__init__')
        index = next(i for i, argument in enumerate(init.args.kwonlyargs) if argument.arg == 'enabled')
        self.assertTrue(isinstance(init.args.kw_defaults[index], ast.Constant)
            and init.args.kw_defaults[index].value is False)
        init.args.kw_defaults[index] = ast.Constant(value=True)
        self.assertTrue(ast_digest(normalized_helper) == V2_AST_SHA256['native_clipboard.py'])

    def test_actual_bitmap_and_html_methods_select_only_bitmap_observation(self):
        class Context:
            def __enter__(self): return self
            def __exit__(self, *_): return False
        class Receiver:
            def __init__(self): self.rows = []
            def subTest(self, **_): return Context()
            def _external_case(self, *arguments, **keywords): self.rows.append((arguments, keywords))
        observed = {}
        tree = source_tree('native_clipboard_cases.py')
        for kind in ('bitmap', 'html'):
            name = 'test_supported_external_os_' + kind + '_menu_keyboard_atomic_roundtrip'
            function = copy.deepcopy(method(tree, 'NativeClipboardCases', name))
            module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
            namespace = {}
            exec(compile(module, '<public-candidate-transport-test>', 'exec'), namespace)
            receiver = Receiver(); namespace[name](receiver)
            observed[kind] = receiver.rows
        self.assertTrue(observed['bitmap'] == [
            (('bitmap', 'menu'), {'observe_callbacks': True}),
            (('bitmap', 'keyboard'), {'observe_callbacks': True})])
        self.assertTrue(observed['html'] == [(('html', 'menu'), {}), (('html', 'keyboard'), {})])


    def test_external_case_observer_preserves_original_input_wait_and_saved_oracles(self):
        tree = source_tree('native_clipboard_cases.py')
        current = method(tree, 'NativeClipboardCases', '_external_case')
        wanted_args = ast.parse('def f(self,kind,transport,*,observe_callbacks=False): pass').body[0].args
        self.assertTrue(same_ast(current.args, wanted_args))
        imported = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
            and node.module == 'native_clipboard' for alias in node.names if alias.asname is None}
        self.assertTrue('ClipboardCallbackObservation' in imported)
        constructors = calls(current, 'ClipboardCallbackObservation')
        self.assertTrue(len(constructors) == 1)
        enabled = [item.value for item in constructors[0].keywords if item.arg == 'enabled']
        wanted = ast.parse("kind=='bitmap' and observe_callbacks is True and current.page is self.page", mode='eval').body
        self.assertTrue(len(enabled) == 1 and same_ast(enabled[0], wanted))
        wrappers = [node for node in ast.walk(current) if isinstance(node, ast.With)
            and len(node.items) == 1 and isinstance(node.items[0].context_expr, ast.Name)
            and node.items[0].context_expr.id == 'observation']
        self.assertTrue(len(wrappers) == 1)
        wrapper = wrappers[0]
        self.assertTrue(len(calls(wrapper, 'begin_wait')) == len(calls(wrapper, 'end_wait')) == 1
            and len(calls(wrapper, 'wait_for_function')) == 1 and not calls(wrapper, '_clipboard_save_as'))
        tries = [node for node in wrapper.body if isinstance(node, ast.Try)]
        self.assertTrue(len(tries) == 1 and primary_capture_try(tries[0]))
        preceding = wrapper.body[wrapper.body.index(tries[0])-1]
        self.assertTrue(same_ast(preceding, ast.parse('wait_primary=None').body[0]))
        original_wait = ast.parse('self.page.wait_for_function(\'document.title.startsWith("• ")\',timeout=30000)', mode='eval').body
        self.assertTrue(same_ast(calls(tries[0], 'wait_for_function')[0], original_wait))
        self.assertTrue(any(calls(node, 'begin_wait') for node in wrapper.body[:wrapper.body.index(tries[0])]))
        parents = [node for node in ast.walk(current) if hasattr(node, 'body') and type(node.body) is list and wrapper in node.body]
        self.assertTrue(len(parents) == 1)
        siblings = parents[0].body
        self.assertTrue(wrapper is not siblings[-1] and len(calls(siblings[siblings.index(wrapper)+1], '_clipboard_save_as')) == 1)
        stripped = StripObservation().visit(copy.deepcopy(current))
        stripped.args = ast.parse('def f(self,kind,transport): pass').body[0].args
        self.assertTrue(ast_digest(stripped) == BASE_EXTERNAL_CASE_AST_SHA256)




class ReviewedFocusInverseTests(unittest.TestCase):
    def test_reviewed_postimage_restores_original_v2_bytes(self):
        raw = (E2E/'native_document_windows.py').read_bytes()
        restored = without_reviewed_focus_failure('native_document_windows.py',raw)
        self.assertEqual(hashlib.sha256(restored).hexdigest(),V2_UNCHANGED_FILE_SHA256['native_document_windows.py'])
        self.assertNotEqual(raw,restored)
        self.assertEqual(V2_UNCHANGED_FILE_SHA256,{'driver.py':'97ba96f985037a715cbf0df36782b75bdab4c4829b12583f56f047a846b456a6',
            'native_document_windows.py':'167dbe3e619cae05ace7ac142c0cbaf0783d4e9f4a1846efabefcad4ae2cc8c2'})

    def test_guard_timeout_query_raise_and_unreviewed_byte_mutations_reject(self):
        raw = (E2E/'native_document_windows.py').read_bytes()
        changes = (
            (b'return require_focus_map(self.key, focus_rows)',b'return True'),
            (b'until(focus_ready, timeout=10,',b'until(focus_ready, timeout=11,'),
            (b'focus_rows = self.owner._focus_rows()',b'focus_rows = self.owner._focus_rows(); self.owner._focus_rows()'),
            (b'            raise\n        return self._ready()',b'            return self._ready()\n        return self._ready()'),
        )
        for before,after in changes:
            with self.subTest(kind=len(before)):
                self.assertEqual(raw.count(before),1)
                with self.assertRaises(ValueError):without_reviewed_focus_failure('native_document_windows.py',raw.replace(before,after,1))
        with self.assertRaises(ValueError):without_reviewed_focus_failure('native_document_windows.py',raw+b'\n')

    def test_missing_or_duplicate_observation_is_not_a_bypass(self):
        raw = (E2E/'native_document_windows.py').read_bytes()
        restored = without_reviewed_focus_failure('native_document_windows.py',raw)
        with self.assertRaises(ValueError):without_reviewed_focus_failure('native_document_windows.py',restored)
        fixture = json.loads(FOCUS_FAILURE_INVERSE_PATH.read_bytes())
        block = ''.join(fixture['hunks'][0]['afterLines']).encode('utf-8')
        self.assertEqual(raw.count(block),1)
        with self.assertRaises(ValueError):without_reviewed_focus_failure('native_document_windows.py',raw.replace(block,block+block,1))

    def test_changed_fixture_cannot_supply_arbitrary_inverse(self):
        from unittest import mock
        raw = (E2E/'native_document_windows.py').read_bytes()
        encoded = FOCUS_FAILURE_INVERSE_PATH.read_bytes()
        fixture = json.loads(encoded)
        fixture['hunks'][0]['afterStart'] += 1
        for changed in (encoded+b' ',json.dumps(fixture).encode('utf-8')):
            with self.subTest(size=len(changed)),mock.patch.object(Path,'read_bytes',return_value=changed):
                with self.assertRaises(ValueError):without_reviewed_focus_failure('native_document_windows.py',raw)

    def test_driver_remains_raw_and_every_original_hash_stays_effective(self):
        raw = (E2E/'driver.py').read_bytes()
        self.assertIs(without_reviewed_focus_failure('driver.py',raw),raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),V2_UNCHANGED_FILE_SHA256['driver.py'])
        changed = raw+b'\n'
        self.assertNotEqual(hashlib.sha256(without_reviewed_focus_failure('driver.py',changed)).hexdigest(),V2_UNCHANGED_FILE_SHA256['driver.py'])


if __name__ == '__main__':
    unittest.main()
