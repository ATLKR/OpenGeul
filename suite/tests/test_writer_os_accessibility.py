"""Content-free Writer MSAA contracts, without a desktop or user document."""
import ctypes as C
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from types import SimpleNamespace as NS
from unittest.mock import patch

E2E = Path(__file__).resolve().parents[1] / 'e2e'
sys.path.insert(0, str(E2E))
try:
    import writer_os_accessibility as probe
except ImportError:
    probe = None


REQUEST = dict(officePid=200, officeCreationTime=300, childHwnd=123,
               expectedImage=str(Path('/synthetic') / 'Office/program/soffice.bin'))


class Node:
    def __init__(self, identity, role=10, state=4, parent=None):
        self.identity, self.role, self.state, self.parent = identity, role, state, parent
        self.ia2 = self.text = True

    def __getattr__(self, key):
        raise AssertionError('Unexpected property access')


class Owner:
    def __init__(self, request):
        self.events = []
        self.fail_at = None
        self.closed = 0
        self.checks = 0

    def open(self):
        pass

    def check(self, *, full=False):
        self.checks += 1
        self.events.append(('owner', full))
        if self.checks == self.fail_at:
            raise RuntimeError()

    def close(self):
        self.closed += 1
        self.events.append(('owner-close',))
        return True


class Com:
    def __init__(self, guard, record):
        self.guard, self.record = guard, record
        self.root_node = Node(1)
        self.document = Node(2, 15, parent=self.root_node)
        self.leaf = Node(3, 42, parent=self.document)
        self.calls = []
        self.references = []
        self.close_failure = False
        self.focus_vt = 9

    def _get(self, name, node):
        self.guard()
        self.calls.append(name)
        references = {'root': 1, 'identity': 1, 'focus': 1, 'parent': 2, 'ia2': 2, 'text': 2}
        self.record['referencesAcquired'] += references.get(name, 0)
        self.record['variantsCreated'] += int(name in ('role', 'state', 'focus'))
        return node

    def root(self, child):
        self.assert_child = child
        return self._get('root', self.root_node)

    def identity(self, node):
        return self._get('identity', node).identity

    def focus(self, root):
        self.record['focusVariantType'] = self.focus_vt
        self._get('focus', root)
        if self.focus_vt not in (3, 9):
            raise RuntimeError()
        return self.leaf

    def role(self, node):
        return self._get('role', node).role

    def state(self, node):
        return self._get('state', node).state

    def support(self, node, interface):
        self._get(interface, node)
        return node.ia2 if interface == 'ia2' else node.text

    def parent(self, node):
        return self._get('parent', node).parent

    def close(self):
        self.calls.append('close')
        self.record['referencesReleased'] = self.record['referencesAcquired']
        self.record['variantsCleared'] = self.record['variantsCreated']
        return not self.close_failure


class WriterMsaaTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(probe, 'The owned Writer OS observer is missing')
        self.owner = Owner(REQUEST)
        self.com = None

    def observe(self, change=None):
        def backend(guard, record):
            self.com = Com(guard, record)
            if change:
                change(self.com)
            return self.com
        return probe.observe(dict(REQUEST), owner_factory=lambda request: self.owner,
                             backend_factory=backend)

    def test_owned_focused_document_and_text_interfaces_produce_only_closed_numbers(self):
        value = self.observe()
        self.assertEqual(value['verified'], 1)
        self.assertEqual(value['documentRole'], 15)
        self.assertEqual(value['focusedRole'], 42)
        self.assertEqual(value['focusedState'], 4)
        self.assertEqual(value['parentCount'], 2)
        self.assertEqual(value['ia2Supported'], 1)
        self.assertEqual(value['textSupported'], 1)
        self.assertEqual(self.com.calls.count('focus'), 1)
        self.assertEqual(self.owner.closed, 1)
        self.assertTrue(all(type(number) is int for number in value.values()))
        self.assertEqual(probe.validate(value, REQUEST), value)

    def test_failed_initial_owner_proof_refuses_every_com_query_and_closes_handle(self):
        self.owner.fail_at = 1
        value = self.observe()
        self.assertEqual(value['verified'], 0)
        self.assertIsNone(self.com)
        self.assertEqual(self.owner.closed, 1)
        self.assertEqual(probe.failure_stage(value), 'writer-os-owner')

    def test_failed_mid_query_or_final_owner_proof_cannot_qualify(self):
        baseline = self.observe()
        count = self.owner.checks
        for failure in (2, count):
            with self.subTest(check=failure):
                self.owner = Owner(REQUEST)
                self.owner.fail_at = failure
                value = self.observe()
                self.assertEqual(value['verified'], 0)
                self.assertEqual(self.owner.closed, 1)
                self.assertEqual(probe.failure_stage(value), 'writer-os-owner')

    def test_missing_focus_document_or_interfaces_never_become_a_passing_fallback(self):
        changes = (lambda c: setattr(c.leaf, 'state', 0),
                   lambda c: setattr(c.document, 'role', 10),
                   lambda c: setattr(c.leaf, 'ia2', False),
                   lambda c: setattr(c.leaf, 'text', False),
                   lambda c: setattr(c.leaf, 'parent', None))
        for change in changes:
            with self.subTest(change=changes.index(change)):
                self.owner = Owner(REQUEST)
                value = self.observe(change)
                self.assertEqual(value['verified'], 0)
                self.assertEqual(self.com.calls.count('focus'), 1)
                self.assertEqual(self.owner.closed, 1)

    def test_parent_cycle_and_thirty_third_edge_are_rejected_without_extra_focus(self):
        def cycle(c):
            c.document.parent = c.leaf
        def too_deep(c):
            node = c.root_node
            for index in range(33):
                node = Node(10 + index, 15 if index == 0 else 10, parent=node)
            c.leaf.parent = node
        for change in (cycle, too_deep):
            with self.subTest(change=change.__name__):
                value = self.observe(change)
                self.assertEqual(value['verified'], 0)
                self.assertLessEqual(self.com.calls.count('parent'), 32)
                self.assertEqual(self.com.calls.count('focus'), 1)

    def test_cleanup_failure_blocks_success_but_keeps_the_first_failure_stage(self):
        def fail(c):
            c.leaf.ia2 = False
            c.close_failure = True
        value = self.observe(fail)
        self.assertEqual(probe.failure_stage(value), 'writer-os-ia2')
        self.assertEqual(value['cleanupFailure'], 1)
        self.assertEqual(self.owner.closed, 1)
        value = self.observe(lambda c: setattr(c, 'close_failure', True))
        self.assertEqual(probe.failure_stage(value), 'writer-os-cleanup')
        self.assertEqual(value['verified'], 0)

    def test_closed_result_rejects_extra_bool_identity_mismatch_and_unqualified_success(self):
        value = self.observe()
        changes = ({'extra': 1}, {'verified': True}, {'officePid': 201},
                   {'officeCreationTime': 301}, {'childHwnd': 124},
                   {'documentRole': 10}, {'ownerAfter': 0}, {'textSupported': 0})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                probe.validate(dict(value, **change), REQUEST)

    def test_unknown_and_bstr_focus_are_rejected_without_a_payload_getter(self):
        for vt in (0, 8, 13, 0x4009):
            with self.subTest(vt=vt):
                self.owner = Owner(REQUEST)
                value = self.observe(lambda c: setattr(c, 'focus_vt', vt))
                self.assertEqual(value['verified'], 0)
                self.assertEqual(value['focusVariantType'], vt)
                self.assertEqual(self.owner.closed, 1)

    def test_zero_lifetime_counts_or_unknown_roles_cannot_forge_a_success(self):
        baseline = self.observe()
        for changes in ({'referencesAcquired':0,'referencesReleased':0},
                        {'variantsCreated':0,'variantsCleared':0},
                        {'rootRole':0},{'focusedRole':0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                probe.validate(dict(baseline,**changes),REQUEST)

    def test_closed_wire_drops_duplicate_noise_oversize_bool_and_identity_mismatch(self):
        value = self.observe()
        encoded = json.dumps(value)
        bad = ('noise'+encoded,encoded+'\n0',' '*4097,
               encoded[:-1]+',"verified":1}',json.dumps(dict(value,verified=True)),
               json.dumps(dict(value,officeCreationTime=301)),json.dumps(dict(value,stageCode=99)))
        for wire in bad:
            with self.subTest(length=len(wire)):
                result=probe.decode(wire,REQUEST)
                self.assertEqual(result['verified'],0)
                self.assertEqual(probe.failure_stage(result),'writer-os-protocol')

    def test_thirty_two_actual_parent_edges_can_qualify_without_a_thirty_third_query(self):
        def depth32(c):
            node=c.root_node
            for index in range(31):
                node=Node(10+index,15 if index==0 else 10,parent=node)
            c.leaf.parent=node
        value=self.observe(depth32)
        self.assertEqual(value['verified'],1)
        self.assertEqual(value['parentCount'],32)
        self.assertEqual(self.com.calls.count('parent'),32)

    def test_secondary_baseexception_during_com_cleanup_does_not_replace_the_probe_stage(self):
        def change(c):
            c.leaf.ia2=False
            def close():raise KeyboardInterrupt()
            c.close=close
        value=self.observe(change)
        self.assertEqual(value['stageCode'],7)
        self.assertEqual(value['cleanupFailure'],1)
        self.assertEqual(self.owner.closed,1)


class OwnerProofTests(unittest.TestCase):
    def test_failed_native_handle_close_blocks_success_and_keeps_an_existing_primary_stage(self):
        from startup_smoke import EngineProcessWitness
        for first_failure in (False, True):
            with self.subTest(first_failure=first_failure):
                closed = []
                process = EngineProcessWitness.__new__(EngineProcessWitness)
                process.handle = 991
                process.close_handle = lambda handle: closed.append(handle) or 0
                owner = probe.WindowsOwner.__new__(probe.WindowsOwner)
                owner.process = process
                owner.open = lambda: None
                owner.check = lambda **kwargs: None
                def backend(guard, record):
                    value = Com(guard, record)
                    if first_failure:
                        value.leaf.ia2 = False
                    return value
                with patch.object(probe.C, 'get_last_error', return_value=6, create=True):
                    result = probe.observe(dict(REQUEST), owner_factory=lambda request: owner,
                                           backend_factory=backend)
                owner.close()
                self.assertEqual(result['verified'], 0)
                self.assertEqual(result['ownerReleased'], 0)
                self.assertEqual(result['cleanupFailure'], 1)
                self.assertEqual(result['cleanupHresult'], 0x80070006)
                self.assertEqual(result['stageCode'], 7 if first_failure else 11)
                self.assertEqual(closed, [991])

    def test_owner_initialization_and_failed_handle_close_keep_separate_hresult_evidence(self):
        from startup_smoke import EngineProcessWitness
        for close_result in (0, 1):
            with self.subTest(close_result=close_result):
                closed = []
                process = EngineProcessWitness.__new__(EngineProcessWitness)
                process.handle = 991
                process.close_handle = lambda handle: closed.append(handle) or close_result
                primary = probe.ProbeFailure(0x80070005)
                with patch('startup_smoke.EngineProcessWitness', return_value=process), \
                     patch('windows_smoke.Windows', side_effect=primary), \
                     patch.object(probe.C, 'get_last_error', return_value=6, create=True):
                    result = probe.observe(dict(REQUEST))
                self.assertEqual(result['verified'], 0)
                self.assertEqual(result['stageCode'], 1)
                self.assertEqual(result['hresult'], 0x80070005)
                self.assertEqual(result['cleanupFailure'], 1 - close_result)
                self.assertEqual(result['cleanupHresult'], 0x80070006 if close_result == 0 else 0)
                self.assertEqual(result['ownerReleased'], close_result)
                self.assertEqual(result['referencesAcquired'], 0)
                self.assertEqual(closed, [991])

    def test_witness_constructor_unexposed_cleanup_never_claims_a_verified_release(self):
        for close_result in (0, 1):
            with self.subTest(close_result=close_result):
                closed = []
                def close(handle):
                    closed.append(handle)
                    return close_result
                kernel = NS(CloseHandle=close, WaitForSingleObject=lambda *args: 258,
                    GetExitCodeProcess=lambda *args: 1, OpenProcess=lambda *args: 991,
                    GetProcessTimes=lambda *args: 0)
                primary = probe.ProbeFailure(0x80070005)
                with patch.object(probe.C, 'WinDLL', return_value=kernel, create=True), \
                     patch.object(probe.C, 'WinError', return_value=primary, create=True), \
                     patch.object(probe.C, 'get_last_error', return_value=5, create=True), \
                     patch('windows_smoke.Windows', side_effect=AssertionError('No next acquisition')):
                    result = probe.observe(dict(REQUEST))
                self.assertEqual(result['verified'], 0)
                self.assertEqual(result['stageCode'], 1)
                self.assertEqual(result['hresult'], 0x80070005)
                self.assertEqual(result['ownerReleased'], 0)
                self.assertEqual(result['cleanupFailure'], 0)
                self.assertEqual(result['cleanupHresult'], 0)
                self.assertEqual(result['referencesAcquired'], 0)
                self.assertEqual(closed, [991])

    def test_actual_retained_owner_rejects_wrong_generation_pid_window_or_exit_before_query(self):
        for change in ('generation','pid','window','exit'):
            owner=probe.WindowsOwner.__new__(probe.WindowsOwner)
            owner.request=dict(REQUEST)
            owner.process=NS(creation_time=301 if change=='generation' else 300,
                exited=lambda timeout:change=='exit')
            owner.api=NS(user=NS(IsWindow=lambda hwnd:change!='window'),
                         pid=lambda hwnd:201 if change=='pid' else 200)
            with self.subTest(change=change),self.assertRaises(probe.ProbeFailure):
                owner.check()

    def test_actual_owner_close_relinquishes_the_one_handle_once(self):
        closed=[]
        owner=probe.WindowsOwner.__new__(probe.WindowsOwner)
        owner.process=NS(handle=991,close_handle=lambda handle:closed.append(handle) or 1)
        owner.close();owner.close()
        self.assertEqual(closed,[991])

    def test_full_owner_proof_rechecks_only_the_retained_executable_image(self):
        with tempfile.TemporaryDirectory() as directory:
            expected=Path(directory)/'soffice.bin';expected.write_bytes(b'synthetic-image')
            other=Path(directory)/'foreign.bin';other.write_bytes(b'other-image')
            image=[str(expected)];queries=[]
            def query(handle,flags,buffer,size):
                queries.append((handle,flags));buffer.value=image[0];return 1
            owner=probe.WindowsOwner.__new__(probe.WindowsOwner)
            owner.request=dict(REQUEST,expectedImage=str(expected))
            owner.expected=probe.os.path.normcase(str(expected.resolve(strict=True)))
            owner.process=NS(handle=999,creation_time=300,exited=lambda timeout:False)
            owner.api=NS(user=NS(IsWindow=lambda hwnd:True),pid=lambda hwnd:200)
            with patch.object(probe.C,'WinDLL',return_value=NS(QueryFullProcessImageNameW=query),create=True):
                owner.check(full=True)
                image[0]=str(other)
                with self.assertRaises(probe.ProbeFailure):owner.check(full=True)
            self.assertEqual(queries,[(999,0),(999,0)])


class Payload(C.Union):
    _fields_ = [('VT_I4', C.c_int32), ('c_void_p', C.c_void_p), ('record', C.c_uint64 * 2)]


class VariantHead(C.Structure):
    _fields_ = [('vt', C.c_uint16), ('reserved', C.c_uint16 * 3), ('_', Payload)]


class VariantOuter(C.Union):
    _fields_ = [('head', VariantHead), ('decimal', C.c_uint64 * 2)]
    _anonymous_ = ('head',)


class AutoVariant(C.Structure):
    _fields_ = [('inner', VariantOuter)]
    _anonymous_ = ('inner',)

    @property
    def value(self):
        raise AssertionError('Automatic VARIANT text conversion is forbidden')


class Guid(C.Structure):
    _fields_ = [('bytes', C.c_ubyte * 16)]

    def __init__(self, value=None):
        super().__init__()
        if value:
            C.memmove(C.addressof(self), uuid.UUID(value).bytes_le, 16)


class RawFixture:
    """Actual raw ctypes calls into a deterministic external COM vtable."""
    def __init__(self):
        self.Variant = probe.plain_variant(AutoVariant)
        self.functions, self.tables, self.objects, self.ledger = [], [], [], {}
        self.calls, self.clears, self.bad_releases = [], [], []
        self.focus_vt, self.role_vt, self.clear_hr = 9, 3, 0
        self.child_id, self.root_hr, self.focus_hr = 0, 0, 0
        self.focus_null = False
        self.text_reads=[]
        def forbidden(value):
            self.text_reads.append(1)
            raise AssertionError('Forbidden automatic text conversion')
        self.Variant.value=property(forbidden)
        self.supported = {'ia2', 'text'}
        self.nodes, self.service_nodes = {}, {}
        self._build_objects()
        self.bindings = NS(Variant=self.Variant, Guid=Guid, call_type=C.CFUNCTYPE,
                           accessible=self.accessible, clear=self.clear)

    def _callback(self, result, arguments, function):
        callback = C.CFUNCTYPE(result, C.c_void_p, *arguments)(function)
        self.functions.append(callback)
        return C.cast(callback, C.c_void_p).value

    def _build_objects(self):
        class Interface(C.Structure):
            _fields_ = [('vtable', C.POINTER(C.c_void_p))]
        for name in ('root', 'document', 'leaf'):
            for service in (False, True):
                table = (C.c_void_p * (4 if service else 28))()
                obj = Interface(table)
                pointer = C.cast(C.pointer(obj), C.c_void_p).value
                self.tables.append(table)
                self.objects.append(obj)
                (self.service_nodes if service else self.nodes)[name] = pointer
                self.ledger[pointer] = 0
        for name, pointer in list(self.nodes.items()) + list(self.service_nodes.items()):
            obj = C.cast(pointer, C.POINTER(Interface)).contents
            service = pointer in self.service_nodes.values()
            def query(this, iid, out, name=name):
                key = str(uuid.UUID(bytes_le=bytes(iid.contents.bytes)))
                self.calls.append(('qi', name, key))
                target = self.service_nodes[name] if key == '6d5140c1-7436-11ce-8034-00aa006009fa' else self.nodes[name]
                self.ledger[target] += 1
                out[0] = target
                return 0
            def release(this):
                self.ledger[this] -= 1
                if self.ledger[this] < 0:
                    self.bad_releases.append(this)
                self.calls.append(('release', this))
                return max(0, self.ledger[this])
            obj.vtable[0] = self._callback(C.c_int32, (C.POINTER(Guid), C.POINTER(C.c_void_p)), query)
            obj.vtable[2] = self._callback(C.c_uint32, (), release)
            if service:
                def qs(this, sid, iid, out, name=name):
                    self.calls.append(('qs', str(uuid.UUID(bytes_le=bytes(sid.contents.bytes))),
                                       str(uuid.UUID(bytes_le=bytes(iid.contents.bytes)))))
                    key = 'ia2' if bytes(iid.contents.bytes) == uuid.UUID('e89f726e-c4f4-4c19-bb19-b647d7fa8478').bytes_le else 'text'
                    if key not in self.supported:
                        return -2147467262
                    target = self.nodes[name]
                    self.ledger[target] += 1
                    out[0] = target
                    return 0
                obj.vtable[3] = self._callback(C.c_int32,
                    (C.POINTER(Guid), C.POINTER(Guid), C.POINTER(C.c_void_p)), qs)
                continue
            def number(this, child, out, name=name, state=False):
                self.calls.append(('state' if state else 'role', name, child.vt, child._.VT_I4))
                out[0].vt = 3 if state else self.role_vt
                if out[0].vt == 3:
                    out[0]._.VT_I4 = 4 if state else {'root': 10, 'document': 15, 'leaf': 42}[name]
                else:
                    out[0]._.c_void_p = 1  # Never dereference a custom BSTR role.
                return 0
            def state(this, child, out, name=name):
                return number(this, child, out, name, True)
            obj.vtable[13] = self._callback(C.c_int32, (self.Variant, C.POINTER(self.Variant)), number)
            obj.vtable[14] = self._callback(C.c_int32, (self.Variant, C.POINTER(self.Variant)), state)
            def focus(this, out):
                self.calls.append(('focus',))
                out[0].vt = self.focus_vt
                if self.focus_vt == 9:
                    out[0]._.c_void_p = 0 if self.focus_null else self.nodes['leaf']
                    if not self.focus_null:self.ledger[self.nodes['leaf']] += 1  # Owned by the VARIANT.
                elif self.focus_vt == 3:
                    out[0]._.VT_I4 = self.child_id
                else:
                    out[0]._.c_void_p = 1
                return self.focus_hr
            obj.vtable[18] = self._callback(C.c_int32, (C.POINTER(self.Variant),), focus)
            def child(this, identifier, out):
                self.calls.append(('child',identifier.vt,identifier._.VT_I4))
                target=self.nodes['leaf'];self.ledger[target]+=1;out[0]=target
                return 0
            obj.vtable[9]=self._callback(C.c_int32,(self.Variant,C.POINTER(C.c_void_p)),child)
            def parent(this, out, name=name):
                self.calls.append(('parent', name))
                target = self.nodes[{'leaf': 'document', 'document': 'root'}[name]]
                self.ledger[target] += 1
                out[0] = target
                return 0
            obj.vtable[7] = self._callback(C.c_int32, (C.POINTER(C.c_void_p),), parent)

    def accessible(self, hwnd, object_id, iid, out):
        self.calls.append(('root', hwnd, object_id))
        self.ledger[self.nodes['root']] += 1
        C.cast(out, C.POINTER(C.c_void_p))[0] = self.nodes['root']
        return self.root_hr

    def clear(self, address):
        variant = C.cast(address, C.POINTER(self.Variant)).contents
        self.clears.append(variant.vt)
        if self.clear_hr:
            return self.clear_hr
        if variant.vt == 9:
            pointer = variant._.c_void_p
            if pointer:self.ledger[pointer] -= 1
        variant.vt = 0
        return 0


class RawAbiTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(probe, 'plain_variant'), 'The raw non-converting ABI is missing')
        self.owner = Owner(REQUEST)
        self.fixture = RawFixture()

    def observe(self):
        return probe.observe(REQUEST, owner_factory=lambda request: self.owner,
            backend_factory=lambda guard, record: probe.RawComBackend(guard, record, bindings=self.fixture.bindings))

    def test_sdk_slots_by_value_variant_and_service_route_balance_separate_owned_references(self):
        value = self.observe()
        self.assertEqual(value['verified'], 1)
        self.assertEqual(self.fixture.calls.count(('focus',)), 1)
        self.assertIn(('role', 'leaf', 3, 0), self.fixture.calls)
        qs = [call for call in self.fixture.calls if call[0] == 'qs']
        self.assertEqual([call[1] for call in qs], ['618736e0-3c3d-11cf-810c-00aa00389b71'] * 2)
        self.assertEqual([call[2] for call in qs], ['e89f726e-c4f4-4c19-bb19-b647d7fa8478',
                                                  '24fd2ffb-3aad-4a08-8335-a3ad89c0fb4b'])
        self.assertTrue(all(count == 0 for count in self.fixture.ledger.values()))
        self.assertEqual(self.fixture.bad_releases, [])
        self.assertEqual(value['referencesAcquired'], value['referencesReleased'])
        self.assertEqual(value['variantsCreated'], value['variantsCleared'])
        self.assertEqual(self.fixture.text_reads,[])

    def test_raw_output_never_auto_converts_bstr_or_unknown_focus_payload(self):
        for vt in (8, 13, 0x4009):
            with self.subTest(vt=vt):
                self.fixture = RawFixture()
                self.fixture.focus_vt = vt
                value = self.observe()
                self.assertEqual(value['verified'], 0)
                self.assertEqual(value['focusVariantType'], vt)
                self.assertIn(vt, self.fixture.clears)
                self.assertTrue(all(count == 0 for count in self.fixture.ledger.values()))
                self.assertEqual(self.fixture.text_reads,[])

    def test_custom_bstr_role_is_cleared_without_payload_access(self):
        self.fixture.role_vt = 8
        value = self.observe()
        self.assertEqual(value['verified'], 0)
        self.assertIn(8, self.fixture.clears)
        self.assertTrue(all(count == 0 for count in self.fixture.ledger.values()))
        self.assertEqual(self.fixture.text_reads,[])

    def test_failed_queryservice_and_variant_cleanup_keep_the_first_numeric_hresult(self):
        self.fixture.supported.remove('text')
        self.fixture.clear_hr = -2147467259
        value = self.observe()
        self.assertEqual(value['verified'], 0)
        self.assertEqual(value['stageCode'], 8)
        self.assertEqual(value['hresult'], 0x80004002)
        self.assertEqual(value['cleanupFailure'], 1)
        self.assertEqual(value['cleanupHresult'], 0x80004005)
        self.assertEqual(value['referencesAcquired'], value['referencesReleased'])
        self.assertEqual(self.owner.closed, 1)

    def test_runtime_layout_rejects_unknown_variant_shape_before_loading_interfaces(self):
        class Wrong(C.Structure):
            _fields_ = [('vt', C.c_uint16)]
        with self.assertRaises(ValueError):
            probe.plain_variant(Wrong)

    def test_numeric_focus_child_id_uses_by_value_child_variant_without_another_focus_read(self):
        self.fixture.focus_vt=3;self.fixture.child_id=7
        value=self.observe()
        self.assertEqual(value['verified'],1)
        self.assertIn(('child',3,7),self.fixture.calls)
        self.assertEqual(self.fixture.calls.count(('focus',)),1)
        self.assertTrue(all(count==0 for count in self.fixture.ledger.values()))

    def test_failed_hresult_with_nonnull_outptr_still_releases_that_owned_reference(self):
        self.fixture.root_hr=-2147467259
        value=self.observe()
        self.assertEqual(value['stageCode'],3)
        self.assertEqual(value['hresult'],0x80004005)
        self.assertEqual(value['referencesAcquired'],1)
        self.assertEqual(value['referencesReleased'],1)
        self.assertTrue(all(count==0 for count in self.fixture.ledger.values()))

    def test_release_fault_keeps_clearing_and_releasing_every_other_reference(self):
        backends=[]
        def backend(guard,record):
            value=probe.RawComBackend(guard,record,bindings=self.fixture.bindings)
            original=value._invoke
            def invoke(pointer,slot,*args):
                if slot==2 and not backends:
                    backends.append(1)
                    raise RuntimeError()
                return original(pointer,slot,*args)
            value._invoke=invoke
            return value
        result=probe.observe(REQUEST,owner_factory=lambda request:self.owner,backend_factory=backend)
        self.assertEqual(result['verified'],0)
        self.assertEqual(result['stageCode'],11)
        self.assertEqual(result['referencesAcquired']-result['referencesReleased'],1)
        self.assertEqual(result['variantsCreated'],result['variantsCleared'])
        self.assertEqual(sum(self.fixture.ledger.values()),1)
        self.assertEqual(self.owner.closed,1)

    def test_bindings_reuse_existing_com_apartment_without_initializing_or_uninitializing_it(self):
        loads=[]
        def accessible(*args):return 0
        def clear(*args):return 0
        def dll(name):
            loads.append(name)
            if name=='oleacc':return NS(AccessibleObjectFromWindow=accessible)
            if name=='oleaut32':return NS(VariantClear=clear)
            self.fail('A new COM apartment or provider API was requested')
        with patch.dict(sys.modules,{'comtypes':NS(GUID=Guid),'comtypes.automation':NS(VARIANT=AutoVariant)}),\
             patch.object(probe.os,'name','nt'),\
             patch.object(probe.C,'c_long',C.c_int32),\
             patch.object(probe.C,'WINFUNCTYPE',C.CFUNCTYPE,create=True),\
             patch.object(probe.C,'WinDLL',side_effect=dll,create=True):
            bindings=probe._windows_bindings()
        self.assertEqual(loads,['oleacc','oleaut32'])
        self.assertEqual(bindings.accessible.restype,C.c_int32)
        self.assertEqual(C.sizeof(bindings.Variant),24)


class DocumentedGuidInputTests(unittest.TestCase):
    """Exercise the CLSIDFromString input boundary without Windows or a registry.

    uuid.UUID accepts bare UUIDs, while the documented CLSIDFromString form has
    braces. This strict boundary is synthetic; it does not execute that API.
    """
    def setUp(self):
        self.fixture = RawFixture()
        self.record = probe.failure(REQUEST)
        self.owner = Owner(REQUEST)
        self.inputs = []
        supplied = self.inputs

        class DocumentedGuid(Guid):
            def __init__(self, value=None):
                if value is not None:
                    supplied.append(value)
                    if (type(value) is not str or len(value) != 38
                            or value[0] != '{' or value[-1] != '}'):
                        raise OSError('Synthetic CLSIDFromString format boundary')
                super().__init__(value)

        self.fixture.bindings.Guid = DocumentedGuid

    def backend(self):
        value = probe.RawComBackend(lambda: None, self.record,
            bindings=self.fixture.bindings)
        self.addCleanup(value.close)
        return value

    def test_original_root_reaches_oleacc_with_documented_guid_input(self):
        backend = self.backend()
        try:
            root = backend.root(REQUEST['childHwnd'])
        except OSError:
            self.fail('Original root GUID must satisfy CLSIDFromString input format')
        self.assertEqual(root, self.fixture.nodes['root'])
        self.assertEqual(self.fixture.calls, [('root',123,0xfffffffc)])

    def test_canonical_identity_reaches_query_interface_with_documented_guid_input(self):
        backend = self.backend()
        try:
            pointer = backend.identity(self.fixture.nodes['root'])
        except OSError:
            self.fail('Canonical IUnknown GUID must satisfy CLSIDFromString input format')
        self.assertEqual(pointer, self.fixture.nodes['root'])
        self.assertEqual(self.fixture.calls,
            [('qi','root','00000000-0000-0000-c000-000000000046')])

    def test_service_queries_preserve_both_original_interface_identities(self):
        backend = self.backend()
        try:
            for interface in ('ia2','text'):
                self.assertTrue(backend.support(self.fixture.nodes['leaf'],interface))
        except OSError:
            self.fail('Service and requested GUIDs must satisfy CLSIDFromString input format')
        queries = [row for row in self.fixture.calls if row[0] == 'qs']
        self.assertEqual(queries, [
            ('qs','618736e0-3c3d-11cf-810c-00aa00389b71','e89f726e-c4f4-4c19-bb19-b647d7fa8478'),
            ('qs','618736e0-3c3d-11cf-810c-00aa00389b71','24fd2ffb-3aad-4a08-8335-a3ad89c0fb4b')])

    def test_existing_observer_passes_strict_guid_boundary_and_balances_cleanup(self):
        value = probe.observe(REQUEST, owner_factory=lambda request: self.owner,
            backend_factory=lambda guard, record: probe.RawComBackend(
                guard,record,bindings=self.fixture.bindings))
        self.assertEqual(value['verified'],1)
        self.assertEqual(value['stageCode'],12)
        self.assertEqual(value['referencesAcquired'],value['referencesReleased'])
        self.assertEqual(value['variantsCreated'],value['variantsCleared'])
        self.assertTrue(all(count == 0 for count in self.fixture.ledger.values()))
        self.assertEqual(self.owner.closed,1)
        self.assertEqual(self.fixture.text_reads,[])


class RootCapabilityDiagnosticTests(unittest.TestCase):
    """Later fresh-root observations never certify the earlier focused object."""
    def setUp(self):
        self.owner=Owner(REQUEST);self.fixture=RawFixture();self.backends=[]

    def feature(self,name):
        method=getattr(probe,name,None)
        self.assertTrue(callable(method),'Separate numeric root diagnostic API is missing')
        return method

    def observe(self,change=None):
        observer=self.feature('observe_root_diagnostic')
        backend_type=self.feature('RootCapabilityBackend')
        def backend(guard,record):
            value=backend_type(guard,record,bindings=self.fixture.bindings)
            if change:change(value)
            self.backends.append(value)
            return value
        return observer(REQUEST,owner_factory=lambda request:self.owner,backend_factory=backend)

    def test_success_is_closed_fresh_root_evidence_with_no_variant_or_focus_calls(self):
        value=self.observe()
        self.assertEqual((value['known'],value['bridgeReachable'],value['stageCode']),(1,1,8))
        self.assertEqual((value['diagnosticOnly'],value['acceptanceEligible'],value['freshRootLater']),(1,0,1))
        self.assertTrue(all(type(number) is int for number in value.values()))
        self.assertEqual(value['referencesAcquired'],3);self.assertEqual(value['referencesReleased'],3)
        self.assertEqual(value['ownerBefore'],value['ownerAfter']);self.assertEqual(value['ownerReleased'],1)
        for name in ('root','service','ia2'):
            self.assertEqual([value[name+field] for field in ('Attempted','Completed','NonNull','Hresult')],[1,1,1,0])
        self.assertEqual([call[0] for call in self.fixture.calls],['root','qi','qs','release','release','release'])
        self.assertEqual(self.fixture.clears,[]);self.assertEqual(self.fixture.text_reads,[])
        self.assertTrue(all(count==0 for count in self.fixture.ledger.values()))

    def test_documented_service_sid_and_ia2_iid_are_used_on_root_only(self):
        self.observe()
        self.assertEqual(self.fixture.calls[:3],[('root',123,0xfffffffc),
            ('qi','root','6d5140c1-7436-11ce-8034-00aa006009fa'),
            ('qs','618736e0-3c3d-11cf-810c-00aa00389b71','e89f726e-c4f4-4c19-bb19-b647d7fa8478')])

    def test_root_failure_with_nonnull_is_unsigned_and_released(self):
        self.fixture.root_hr=-2147467259
        value=self.observe()
        self.assertEqual((value['known'],value['stageCode'],value['rootHresult']),(0,3,0x80004005))
        self.assertEqual((value['rootCompleted'],value['rootNonNull'],value['serviceAttempted']),(1,1,0))
        self.assertEqual((value['referencesAcquired'],value['referencesReleased']),(1,1))
        self.assertTrue(all(count==0 for count in self.fixture.ledger.values()))

    def test_failed_qi_or_queryservice_nonnull_outptr_is_released_without_next_call(self):
        for slot,prefix,stage,count in ((0,'service',4,2),(3,'ia2',5,3)):
            with self.subTest(stage=stage):
                self.setUp()
                def change(value):
                    original=value._invoke
                    def invoke(pointer,current,*args):
                        result=original(pointer,current,*args)
                        return -2147467259 if current==slot else result
                    value._invoke=invoke
                value=self.observe(change)
                self.assertEqual((value['known'],value['stageCode']),(0,stage))
                self.assertEqual((value[prefix+'Hresult'],value[prefix+'NonNull']),(0x80004005,1))
                self.assertEqual((value['referencesAcquired'],value['referencesReleased']),(count,count))
                self.assertTrue(all(number==0 for number in self.fixture.ledger.values()))

    def test_no_interface_and_s_ok_null_are_unknown_with_separate_completed_flags(self):
        self.fixture.supported.remove('ia2');value=self.observe()
        self.assertEqual((value['known'],value['ia2Hresult'],value['ia2NonNull']),(0,0x80004002,0))
        self.assertEqual((value['ia2Attempted'],value['ia2Completed']),(1,1))
        self.setUp();self.fixture.bindings.accessible=lambda *args:0
        value=self.observe()
        self.assertEqual((value['known'],value['rootHresult'],value['rootNonNull']),(0,0,0))
        self.assertEqual((value['rootAttempted'],value['rootCompleted'],value['serviceAttempted']),(1,1,0))

    def test_owner_failure_before_or_after_capabilities_never_qualifies(self):
        self.owner.fail_at=1;value=self.observe()
        self.assertEqual((value['known'],value['ownerBefore'],value['rootAttempted']),(0,0,0))
        self.assertFalse(self.backends)
        self.setUp();self.observe();last=self.owner.checks
        self.setUp();self.owner.fail_at=last;value=self.observe()
        self.assertEqual((value['known'],value['bridgeReachable'],value['ownerAfter']),(0,0,0))
        self.assertEqual(value['referencesAcquired'],value['referencesReleased'])
        self.assertEqual(self.owner.closed,1)

    def test_owner_loss_between_calls_stops_before_the_next_native_operation(self):
        self.owner.fail_at=3;value=self.observe()
        self.assertEqual(value['known'],0)
        self.assertEqual([call[0] for call in self.fixture.calls],['root','release'])
        self.assertEqual(value['referencesAcquired'],value['referencesReleased'])

    def test_cleanup_fault_releases_other_references_and_cannot_report_known(self):
        def change(value):
            original=value._invoke;failed=[]
            def invoke(pointer,slot,*args):
                if slot==2 and not failed:
                    failed.append(True);raise RuntimeError('synthetic release failure')
                return original(pointer,slot,*args)
            value._invoke=invoke
        result=self.observe(change)
        self.assertEqual((result['known'],result['cleanupFailure'],result['stageCode']),(0,1,7))
        self.assertEqual(result['referencesAcquired']-result['referencesReleased'],1)
        self.assertEqual(self.owner.closed,1)

    def test_native_exception_after_outptr_still_releases_without_inventing_hresult(self):
        accessible=self.fixture.accessible
        def partial(*args):
            accessible(*args);raise RuntimeError('synthetic private native-call failure')
        self.fixture.bindings.accessible=partial
        value=self.observe()
        self.assertEqual((value['known'],value['rootAttempted'],value['rootCompleted']),(0,1,0))
        self.assertEqual((value['rootNonNull'],value['rootHresult']),(1,0))
        self.assertEqual((value['referencesAcquired'],value['referencesReleased']),(1,1))
        self.assertTrue(all(count==0 for count in self.fixture.ledger.values()))

    def test_root_backend_initialization_loads_no_variant_or_oleaut_api(self):
        backend_type=self.feature('RootCapabilityBackend');loads=[]
        class ForbiddenVariant:
            def __init__(self): raise AssertionError('Root diagnostic must not create a VARIANT')
        def accessible(*args):return 0
        def dll(name):
            loads.append(name)
            if name=='oleacc':return NS(AccessibleObjectFromWindow=accessible)
            raise AssertionError('Root diagnostic must not load other COM APIs')
        with patch.dict(sys.modules,{'comtypes':NS(GUID=Guid),'comtypes.automation':NS(VARIANT=ForbiddenVariant)}),\
             patch.object(probe.os,'name','nt'),patch.object(probe.C,'c_long',C.c_int32),\
             patch.object(probe.C,'WINFUNCTYPE',C.CFUNCTYPE,create=True),\
             patch.object(probe.C,'WinDLL',side_effect=dll,create=True):
            try: backend=backend_type(lambda:None,self.feature('root_diagnostic_failure')(REQUEST))
            except Exception:self.fail('Root-only backend requested the original VARIANT ABI')
            self.assertTrue(backend.close())
        self.assertEqual(loads,['oleacc'])

    def test_owner_close_failure_is_numeric_and_does_not_hide_query_failure(self):
        self.fixture.root_hr=-2147467259
        def close():
            self.owner.closed+=1;raise probe.ProbeFailure(0x80070006)
        self.owner.close=close
        value=self.observe()
        self.assertEqual((value['stageCode'],value['rootHresult']),(3,0x80004005))
        self.assertEqual((value['known'],value['cleanupFailure'],value['cleanupHresult']),(0,1,0x80070006))

    def test_protocol_rejects_extra_strings_bool_numbers_duplicate_keys_and_false_success(self):
        good=self.observe();validate=self.feature('validate_root_diagnostic');decode=self.feature('decode_root_diagnostic')
        self.assertEqual(validate(good,REQUEST),good)
        for change in ({'body':'synthetic forbidden body'},{'known':True},{'acceptanceEligible':1},
                {'officeCreationTime':301},{'referencesReleased':0},{'ia2NonNull':0}):
            with self.subTest(field=next(iter(change))),self.assertRaises(ValueError):
                validate(dict(good,**change),REQUEST)
        encoded=json.dumps(good)
        self.assertEqual(decode(encoded,REQUEST),good)
        for raw in (encoded[:-1],encoded.replace('"known": 1','"known": 1,"known": 0'),
                    encoded+' '*4096,'synthetic private failure'):
            value=decode(raw,REQUEST)
            self.assertEqual((value['known'],value['stageCode']),(0,13))


class FocusCallObservationTests(unittest.TestCase):
    def setUp(self):
        self.owner=Owner(REQUEST)
        self.fixture=RawFixture()

    def observe(self, backend=None):
        return probe.observe(REQUEST, owner_factory=lambda request:self.owner,
            backend_factory=backend or (lambda guard,record:probe.RawComBackend(guard,record,bindings=self.fixture.bindings)))

    def focus_call(self, value):
        self.assertTrue('focusCall' in value,'The same focus getter needs a closed numeric observation')
        row=value['focusCall']
        self.assertEqual(set(row),{'attempted','returned','hrObserved','hr','vtObserved','rejectCode'})
        self.assertTrue(all(type(number)is int for number in row.values()))
        return row

    def balanced(self):
        self.assertTrue(all(count==0 for count in self.fixture.ledger.values()),'Owned reference imbalance')
        self.assertTrue(not self.fixture.bad_releases,'Unexpected reference release')
        self.assertTrue(not self.fixture.text_reads,'No text payload may be read')

    def test_s_ok_empty_variant_is_observed_rejection_with_original_cleanup_and_numbers(self):
        self.fixture.focus_vt=0
        value=self.observe();row=self.focus_call(value)
        self.assertEqual(row,dict(attempted=1,returned=1,hrObserved=1,hr=0,vtObserved=1,rejectCode=3))
        self.assertEqual(tuple(value[k] for k in ('verified','stageCode','hresult','focusVariantType','rootRole',
            'ownerBefore','ownerAfter','referencesAcquired','referencesReleased','variantsCreated','variantsCleared',
            'cleanupFailure','ownerReleased')),(0,4,0,0,10,1,0,2,2,2,2,0,1))
        self.assertEqual(self.fixture.calls.count(('focus',)),1);self.balanced()
        self.assertTrue(probe.decode(json.dumps(value),REQUEST)==value)

    def test_same_invoke_exception_before_or_after_output_write_is_not_a_return_or_s_ok(self):
        class Original(Exception):
            def __str__(self):raise AssertionError('Exception text must not be read')
            def __repr__(self):raise AssertionError('Exception object must not be rendered')
        for wrote in (False,True):
            with self.subTest(outputWritten=wrote):
                self.fixture=RawFixture();original=Original();fixture=self.fixture
                class Fault(probe.RawComBackend):
                    def _invoke(self,pointer,slot,result,arguments,*values):
                        if slot==18:
                            if wrote:super()._invoke(pointer,slot,result,arguments,*values)
                            raise original
                        return super()._invoke(pointer,slot,result,arguments,*values)
                value=probe.failure(REQUEST,4)
                backend=Fault(lambda:None,value,bindings=fixture.bindings)
                try:
                    with self.assertRaises(Original) as caught:backend.focus(fixture.nodes['root'])
                    self.assertTrue(caught.exception is original,'Original exception identity changed')
                    row=self.focus_call(value)
                    self.assertEqual(row,dict(attempted=1,returned=0,hrObserved=0,hr=0,vtObserved=0,rejectCode=1))
                    self.assertEqual((value['hresult'],value['focusVariantType']),(0,0))
                finally:self.assertTrue(backend.close())
                self.assertTrue(probe.validate(value,REQUEST)==value)
                self.assertEqual(self.fixture.calls.count(('focus',)),int(wrote));self.balanced()

    def test_failed_hresult_with_dispatch_output_preserves_primary_and_releases_variant_reference(self):
        self.fixture.focus_hr=-2147467259
        value=self.observe();row=self.focus_call(value)
        self.assertEqual(row,dict(attempted=1,returned=1,hrObserved=1,hr=0x80004005,vtObserved=1,rejectCode=2))
        self.assertEqual((value['verified'],value['stageCode'],value['hresult'],value['focusVariantType']),(0,4,0x80004005,9))
        self.assertEqual((value['referencesAcquired'],value['referencesReleased'],value['variantsCreated'],value['variantsCleared']),(2,2,2,2))
        self.assertEqual(self.fixture.calls.count(('focus',)),1);self.balanced()

    def test_existing_dispatch_child_and_self_paths_are_observations_not_new_acceptance(self):
        for vt,child,verified,stage in ((9,0,1,12),(3,7,1,12),(3,0,0,5)):
            with self.subTest(variantType=vt,selfChild=child==0):
                self.fixture=RawFixture();self.owner=Owner(REQUEST)
                self.fixture.focus_vt=vt;self.fixture.child_id=child
                value=self.observe();row=self.focus_call(value)
                self.assertEqual(row,dict(attempted=1,returned=1,hrObserved=1,hr=0,vtObserved=1,rejectCode=0))
                self.assertEqual((value['verified'],value['stageCode'],value['focusVariantType']),(verified,stage,vt))
                self.assertEqual(self.fixture.calls.count(('focus',)),1);self.balanced()

    def test_unsupported_types_null_dispatch_and_invalid_child_do_not_read_or_export_payload(self):
        cases=((0,0,False,3),(8,0,False,3),(13,0,False,3),(0x4009,0,False,3),
               (9,0,True,4),(3,-1,False,5),(3,2**31,False,5))
        for vt,child,null,reject in cases:
            with self.subTest(variantType=vt,rejectCode=reject):
                self.fixture=RawFixture();self.owner=Owner(REQUEST)
                self.fixture.focus_vt=vt;self.fixture.child_id=child;self.fixture.focus_null=null
                value=self.observe();row=self.focus_call(value)
                self.assertEqual((row['rejectCode'],row['returned'],row['hrObserved'],row['vtObserved']),(reject,1,1,1))
                self.assertEqual((value['verified'],value['stageCode'],value['hresult']),(0,4,0))
                self.assertEqual(self.fixture.calls.count(('focus',)),1);self.balanced()

    def test_later_support_or_cleanup_failure_cannot_be_hidden_by_getter_observation(self):
        for missing,cleanup in ((True,False),(False,True)):
            with self.subTest(missingText=missing,cleanupFailure=cleanup):
                self.fixture=RawFixture();self.owner=Owner(REQUEST)
                if missing:self.fixture.supported={'ia2'}
                if cleanup:self.fixture.clear_hr=-2147467259
                value=self.observe();row=self.focus_call(value)
                self.assertEqual(row,dict(attempted=1,returned=1,hrObserved=1,hr=0,vtObserved=1,rejectCode=0))
                self.assertEqual((value['verified'],value['stageCode']),(0,8 if missing else 11))
                self.assertEqual(value['hresult'],0x80004002 if missing else 0)
                self.assertEqual(value['ownerAfter'],0 if missing else 1)
                self.assertEqual(self.fixture.calls.count(('focus',)),1)
        self.owner=Owner(REQUEST);self.owner.fail_at=1;self.fixture=RawFixture()
        value=self.observe();self.assertFalse('focusCall' in value)
        self.assertEqual((value['verified'],value['stageCode']),(0,1))

    def failure_record(self,value):
        return dict(case='korean-ui-writer',module='writer',success=False,stage=probe.STAGES[value['stageCode']],
            **{k:REQUEST[k] for k in ('officePid','officeCreationTime','childHwnd')},writerOsAccessibility=value)

    def test_optional_diagnostic_preserves_base_schema_and_exact_legacy_summary_vector(self):
        import writer_os_summary as summary
        self.fixture.focus_vt=0;value=self.observe();self.focus_call(value)
        base={key:value[key] for key in probe._MAXIMA}
        self.assertTrue(probe.validate(base,REQUEST)==base)
        self.assertEqual(len(summary.FIELDS),23)
        self.assertEqual(tuple(k for k in probe._MAXIMA if k!='schemaVersion'),summary.FIELDS)
        original=summary.project(self.failure_record(base));extended=summary.project(self.failure_record(value))
        self.assertTrue(original is not None and original==extended,'Legacy numeric vector changed')
        self.assertTrue(summary.valid(extended));self.assertEqual(len(extended),23)
        self.assertEqual(value['focusCall']['rejectCode'],3)

    def test_both_closed_consumers_reject_malformed_extension_without_broad_subset_acceptance(self):
        import writer_os_summary as summary
        self.fixture.focus_vt=0;value=self.observe();good=self.focus_call(value)
        malformed=[None,[],{},dict(good,extra=1)]
        limits=dict(attempted=1,returned=1,hrObserved=1,hr=0xffffffff,vtObserved=1,rejectCode=5)
        for key in good:
            for replacement in (True,-1,limits[key]+1,'synthetic'):
                malformed.append(dict(good,**{key:replacement}))
            malformed.append({k:v for k,v in good.items() if k!=key})
        malformed.extend((dict(good,returned=0),dict(good,hrObserved=0),dict(good,vtObserved=0),
                          dict(good,rejectCode=6),dict(good,hr=2**32)))
        for index,row in enumerate(malformed):
            with self.subTest(mutation=index):
                candidate=dict(value,focusCall=row)
                with self.assertRaises(ValueError):probe.validate(candidate,REQUEST)
                self.assertTrue(summary.project(self.failure_record(candidate)) is None)
        with self.assertRaises(ValueError):probe.validate(dict(value,otherDiagnostic=0),REQUEST)
        self.assertTrue(summary.project(self.failure_record(dict(value,otherDiagnostic=0))) is None)

    def test_code_zero_cannot_hide_fully_observed_hresult_or_unsupported_variant_rejection(self):
        import writer_os_summary as summary
        for failure in ('hresult','empty-variant'):
            self.fixture=RawFixture();self.owner=Owner(REQUEST)
            if failure=='hresult':self.fixture.focus_hr=-2147467259
            else:self.fixture.focus_vt=0
            value=self.observe();row=dict(self.focus_call(value),rejectCode=0)
            candidate=dict(value,focusCall=row)
            with self.subTest(failure=failure,consumer='producer'),self.assertRaises(ValueError):
                probe.validate(candidate,REQUEST)
            with self.subTest(failure=failure,consumer='summary'):
                self.assertTrue(summary.project(self.failure_record(candidate)) is None,
                    'Complete getter failure cannot be relabeled as code zero')
            self.assertEqual(self.fixture.calls.count(('focus',)),1);self.balanced()

    def test_code_zero_partial_observations_remain_unknown_and_do_not_promote_old_zero_fields(self):
        import writer_os_summary as summary
        self.fixture.focus_vt=0;value=self.observe();self.focus_call(value)
        partials=(dict(attempted=0,returned=0,hrObserved=0,hr=0,vtObserved=0,rejectCode=0),
            dict(attempted=1,returned=0,hrObserved=0,hr=0,vtObserved=0,rejectCode=0),
            dict(attempted=1,returned=1,hrObserved=0,hr=0,vtObserved=0,rejectCode=0),
            dict(attempted=1,returned=1,hrObserved=1,hr=0,vtObserved=0,rejectCode=0),
            dict(attempted=1,returned=1,hrObserved=1,hr=0x80004005,vtObserved=0,rejectCode=0))
        base={key:value[key] for key in probe._MAXIMA}
        original=summary.project(self.failure_record(base))
        for index,row in enumerate(partials):
            with self.subTest(partial=index):
                candidate=dict(value,focusCall=row)
                self.assertTrue(probe.validate(candidate,REQUEST)==candidate)
                self.assertTrue(summary.project(self.failure_record(candidate))==original)
                self.assertEqual((candidate['verified'],candidate['hresult'],candidate['focusVariantType']),(0,0,0))
                self.assertEqual(candidate['focusCall'],row)
        self.assertEqual(self.fixture.calls.count(('focus',)),1);self.balanced()


if __name__ == '__main__':
    unittest.main()
