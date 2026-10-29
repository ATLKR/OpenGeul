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
        self.child_id, self.root_hr = 0, 0
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
                    out[0]._.c_void_p = self.nodes['leaf']
                    self.ledger[self.nodes['leaf']] += 1  # Owned by the VARIANT.
                elif self.focus_vt == 3:
                    out[0]._.VT_I4 = self.child_id
                else:
                    out[0]._.c_void_p = 1
                return 0
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
            self.ledger[pointer] -= 1
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


if __name__ == '__main__':
    unittest.main()
