"""Synthetic controller checks; these do not claim Windows execution."""
import ctypes as C
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


MODULE = Path(__file__).resolve().parents[1] / 'e2e/calc_dispatch_diagnostic.py'


class CalcDispatchTransportTests(unittest.TestCase):
    def test_failed_mapping_acquisition_keeps_failed_handle_cleanup_visible(self):
        kernel = SimpleNamespace(CreateFileMappingW=lambda *args: 79,
            MapViewOfFile=lambda *args: None, CloseHandle=lambda handle: False)
        native = self.d.WindowsApi.__new__(self.d.WindowsApi)
        native.kernel = kernel
        self.api.create_mapping = native.create_mapping
        if hasattr(native, 'map_view'):
            self.api.map_view = native.map_view
        original_close = self.api.close_handle
        self.api.close_handle = lambda handle: False if handle == 79 else original_close(handle)
        with patch.object(C, 'set_last_error', lambda value: None, create=True), \
                patch.object(C, 'get_last_error', lambda: 5, create=True), \
                patch.object(C, 'WinError', lambda code: OSError(code, 'synthetic map failure'), create=True):
            with self.assertRaises(OSError):
                self.arm()
        cleanup = self.transport.receipt['cleanup']
        self.assertEqual(cleanup['mappingReleased'], 0)
        self.assertEqual(cleanup['controllerResourcesReleased'], 0)
        self.assertIn(2, cleanup['errors'])

    def test_real_process_environment_is_copied_before_launch(self):
        with patch.dict(os.environ, {'SYNTHETIC_CHILD': 'original'}, clear=True):
            child = self.transport.child_environment(os.environ)
            self.assertEqual(child['SYNTHETIC_CHILD'], 'original')
            self.assertEqual(child[self.d.ENVIRONMENT], '11:17')
            self.assertNotIn(self.d.ENVIRONMENT, os.environ)
            child['SYNTHETIC_CHILD'] = 'child'
            self.assertEqual(os.environ['SYNTHETIC_CHILD'], 'original')
        self.assertFalse(self.api.calls)

    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'Bounded Calc dispatch transport is missing')
        spec = importlib.util.spec_from_file_location('calc_dispatch_diagnostic', MODULE)
        self.d = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.d)
        self.now = 100.0
        test = self
        d = self.d

        class Api:
            def __init__(self):
                self.state = None; self.calls = []; self.live = True
                self.wrong_generation = False; self.mismatch_abi = False
                self.unmap_fails = False; self.partial_read = False
            def controller_identity(self): return 11, 111
            def abi_layout(self):
                value = list(d.abi_layout())
                if self.mismatch_abi: value[-1] += 4
                return tuple(value)
            def qpc(self): return 100000 + int((test.now - 100) * 1000), 1000
            def process_snapshot(self, handle):
                self.calls.append(('process', handle))
                return dict(pid=22, creationTime=223 if self.wrong_generation else 222,
                            waitResult=258 if self.live else 0, exitCode=259 if self.live else 7)
            def window_binding(self, hwnd): return 22, 33
            def duplicate_handle(self, handle):
                self.calls.append(('duplicate', handle)); return 78
            def create_mapping(self, name, size):
                self.calls.append(('mapping', name, size)); self.state = d.State()
                return 79, False
            def map_view(self, handle, size):
                self.calls.append(('map-view', handle, size))
                return C.addressof(self.state)
            def read_word(self, address):
                self.calls.append(('read32', address))
                return C.c_uint32.from_address(address).value
            def read_quad(self, address):
                self.calls.append(('read64', address))
                return C.c_uint64.from_address(address).value
            def publish_word(self, address, value):
                self.calls.append(('publish', address, value))
                C.c_uint32.from_address(address).value = value
            def unmap_view(self, view):
                self.calls.append(('unmap', view)); return not self.unmap_fails
            def close_handle(self, handle): self.calls.append(('close', handle)); return True
            def pause(self, seconds): test.now += seconds

        self.api = Api()
        self.transport = d.DiagnosticTransport(api=self.api, clock=lambda: self.now, nonce=17)
        self.owner = dict(pid=22, creationTime=222, tid=33, hwnd=44, handleValue=77)

    def arm(self): return self.transport.arm(self.owner, 130.0, 100.0)

    def fill(self, rows=None):
        state = self.api.state
        rows = rows if rows is not None else [(1,1,1,0,1,0),(1,4,2,1,2,0),
                                              (2,4,2,1,2,0),(2,1,1,0,1,0)]
        for index, values in enumerate(rows):
            row = state.events[index]
            row.sequence = index + 1
            row.phase,row.operation,row.invocation,row.parent,row.depth,row.value = values
            row.qpc = 100001 + index
        state.count = len(rows)
        state.nextInvocation = max((row[2] for row in rows if row[0] == 1), default=0)

    def test_launch_environment_is_detached_and_does_not_create_mapping(self):
        base = {'A':'B'}
        env = self.transport.child_environment(base)
        self.assertEqual(env['OPENGEUL_CALC_DISPATCH_DIAGNOSTIC'], '11:17')
        self.assertEqual(base, {'A':'B'})
        self.assertIsNone(self.api.state)

    def test_retains_original_handle_and_publishes_only_after_full_identity(self):
        identity = self.arm()
        self.assertEqual(identity['ownerCreated'], 222)
        self.assertEqual(self.transport.observation_deadline, 125.0)
        self.assertEqual(self.api.state.enabled, 1)
        self.assertIn(('duplicate',77), self.api.calls)
        self.assertEqual(next(c for c in self.api.calls if c[0]=='mapping')[1],
                         'Local\\OpenGeulCalcDispatch-11-17')
        self.assertLessEqual(identity['deadlineQpc']-identity['startQpc'], 30000)

    def test_abi_and_generation_reject_before_mapping(self):
        for field in ('mismatch_abi','wrong_generation'):
            with self.subTest(field=field):
                setattr(self.api,field,True)
                with self.assertRaises((ValueError,RuntimeError)): self.arm()
                self.assertIsNone(self.api.state)
                setattr(self.api,field,False)

    def test_original_deadline_is_not_renewed_or_allowed_past_cleanup_reserve(self):
        for deadline, start, now in ((131,100,100),(130,100,125),(130,101,100)):
            with self.subTest(deadline=deadline,start=start,now=now):
                self.now = now
                with self.assertRaises(ValueError): self.transport.arm(self.owner,deadline,start)
                self.assertIsNone(self.api.state)

    def test_snapshot_disables_and_acquires_each_row_before_copy(self):
        identity = self.arm(); self.fill()
        artifact = self.transport.snapshot()
        self.assertEqual(self.api.state.enabled,0)
        self.assertEqual(artifact['analysis']['complete'],1)
        self.assertEqual(artifact['analysis']['processExitProved'],0)
        self.assertFalse(artifact['acceptanceEligible'])
        self.assertEqual(artifact['identity'],identity)
        base = C.addressof(self.api.state)+self.d.State.events.offset
        for index in range(4):
            self.assertGreaterEqual(self.api.calls.count(('read32',base+index*C.sizeof(self.d.Event))),2)
        self.assertTrue(any(call[0]=='read64' for call in self.api.calls))
        self.assertLess(len(json.dumps(artifact)),32768)

    def test_partial_publication_never_copies_unpublished_row_or_claims_completion(self):
        self.arm(); self.fill(); self.api.state.events[2].sequence=0
        artifact = self.transport.snapshot()
        self.assertEqual(len(artifact['events']),2)
        self.assertEqual(artifact['capture']['partialSequence'],3)
        self.assertEqual(artifact['analysis']['complete'],0)
        self.assertEqual(artifact['analysis']['traceValid'],0)

    def test_decoder_rejects_content_unknown_fields_types_and_nesting(self):
        self.arm(); self.fill(); artifact=self.transport.snapshot()
        mutations = (
            lambda x:x.update(document='private'),
            lambda x:x['events'][1].update(parent=0),
            lambda x:x['events'][1].update(operation=5),
            lambda x:x['events'][1].update(qpc=x['identity']['deadlineQpc']),
            lambda x:x['events'][0].update(value=True),
            lambda x:x['state'].update(count=129),
            lambda x:x['identity'].update(reserved1=1),
            lambda x:x['events'][0].update(phase=9,value=2),
        )
        for mutate in mutations:
            value=json.loads(json.dumps(artifact));mutate(value)
            with self.subTest(value=value):
                with self.assertRaises(ValueError): self.d.decode_artifact(value,artifact['identity'])

    def test_changed_immutable_deadline_or_owner_rejects_snapshot(self):
        self.arm();self.fill();self.api.state.identity.deadlineQpc+=1
        with self.assertRaises(ValueError): self.transport.snapshot()

    def test_unmatched_enter_is_incomplete_even_after_native_unwind(self):
        self.arm();self.fill([(1,1,1,0,1,0)])
        artifact=self.transport.snapshot()
        self.assertEqual(artifact['state']['active'],0)
        self.assertEqual(artifact['analysis']['complete'],0)

    def test_cleanup_disposal_is_independent_of_snapshot_validation(self):
        self.arm(); self.fill(); self.api.state.identity.ownerCreated+=1
        deadlines=[]
        def dispose(deadline): deadlines.append(deadline); self.api.live=False
        result=self.transport.close(dispose=dispose)
        self.assertEqual(deadlines,[130.0])
        self.assertEqual(result['snapshotError'],1)
        self.assertEqual(result['exit']['waitResult'],0)
        self.assertEqual(result['cleanup']['remoteQuiescenceProved'],1)
        self.assertEqual(result['cleanup']['engineHandleReleased'],1)
        self.assertIn(('close',78),self.api.calls)
        self.assertNotIn(('close',77),self.api.calls)

    def test_disposal_is_independent_of_failed_retained_generation_observation(self):
        self.arm();self.fill();self.api.wrong_generation=True
        calls=[]
        artifact=self.transport.close(dispose=lambda deadline:calls.append(deadline))
        self.assertEqual(calls,[130.0])
        self.assertEqual(artifact['analysis']['processExitProved'],0)
        self.assertIn(7,artifact['cleanup']['errors'])

    def test_controller_releases_native_library_even_when_not_armed(self):
        calls=[]
        self.api.close_library=lambda:calls.append('library') or True
        result=self.transport.close()
        self.assertEqual(calls,['library'])
        self.assertEqual(result['cleanup']['libraryReleased'],1)
        self.assertEqual(result['cleanup']['controllerResourcesReleased'],1)

    def test_backward_monotonic_clock_rejects_before_arming(self):
        self.now=99.0
        with self.assertRaises(ValueError):self.transport.arm(self.owner,129.0,99.0)
        self.assertIsNone(self.api.state)

    def test_disposal_runs_even_after_quiescent_trace_and_exit_is_separate(self):
        self.arm(); self.fill()
        deadlines=[]
        def dispose(deadline): deadlines.append(deadline);self.api.live=False
        artifact=self.transport.close(dispose=dispose)
        self.assertEqual(deadlines,[130.0])
        self.assertEqual(artifact['analysis']['complete'],1)
        self.assertEqual(artifact['analysis']['processExitProved'],1)
        self.assertEqual(artifact['cleanup']['controllerResourcesReleased'],1)
        self.assertEqual(self.transport.close(dispose=dispose),artifact)
        self.assertEqual(deadlines,[130.0])

    def test_live_process_without_disposal_does_not_prove_remote_view_retired(self):
        self.arm();self.fill();artifact=self.transport.close()
        self.assertEqual(artifact['analysis']['processExitProved'],0)
        self.assertEqual(artifact['cleanup']['remoteQuiescenceProved'],0)
        self.assertEqual(artifact['cleanup']['scopesObservedIdle'],1)
        self.assertEqual(artifact['cleanup']['remoteViewRetired'],0)

    def test_failed_snapshot_still_has_exact_decodable_numeric_schema(self):
        self.arm(); self.fill(); self.api.state.identity.ownerCreated+=1
        artifact=self.transport.close(dispose=lambda deadline:setattr(self.api,'live',False))
        decoded=self.d.decode_artifact(artifact,self.transport.identity)
        self.assertEqual(decoded['analysis']['complete'],0)
        self.assertEqual(decoded['analysis']['processExitProved'],1)
        self.assertIsNone(decoded['state'])
        self.assertEqual(decoded['events'],[])

    def test_expired_capture_cannot_claim_trace_validity(self):
        self.arm();self.fill();self.now=130.0
        self.assertEqual(self.transport.snapshot()['analysis']['traceValid'],0)

    def test_derived_numeric_flags_do_not_accept_booleans(self):
        self.arm();self.fill();artifact=self.transport.snapshot()
        artifact['analysis']['complete']=True
        with self.assertRaises(ValueError):self.d.decode_artifact(artifact)

    def test_retained_process_exit_proof_rejects_unknown_wait_result(self):
        self.arm();self.fill();artifact=self.transport.snapshot()
        artifact['exit']=dict(observed=1,handleValue=78,pid=22,creationTime=222,
                              waitResult=1,exitCode=7,withinDeadline=1)
        with self.assertRaises(ValueError):self.d.decode_artifact(artifact)

    def test_active_remote_scope_and_expired_deadline_are_never_waited_on_again(self):
        self.arm();self.fill([(1,1,1,0,1,0)])
        self.api.state.active=self.api.state.depth=1;self.api.state.stack[0]=1
        self.now=130.0
        artifact=self.transport.close()
        self.assertEqual(artifact['cleanup']['deadlineExpired'],1)
        self.assertEqual(artifact['cleanup']['remoteQuiescenceProved'],0)
        self.assertEqual(artifact['analysis']['complete'],0)
        self.assertEqual(self.now,130.0)

    def test_native_unmap_failure_remains_visible(self):
        self.arm(); self.fill(); self.api.unmap_fails=True
        artifact=self.transport.close()
        self.assertEqual(artifact['cleanup']['controllerResourcesReleased'],0)
        self.assertIn(1,artifact['cleanup']['errors'])

    def test_native_cpp_and_ctypes_all_field_offsets_match(self):
        compiler=shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')
        if not compiler:self.skipTest('Portable C++ compiler unavailable')
        d=self.d
        entries=['kMagic','kVersion','kCapacity','kDepth','sizeof(Identity)','sizeof(Event)','sizeof(State)',
                 'alignof(Identity)','alignof(Event)','alignof(State)']
        for name,structure in (('Identity',d.Identity),('Event',d.Event),('State',d.State)):
            entries.extend('offsetof('+name+','+field+')' for field,_ in structure._fields_)
        source='#include "wire.h"\n#include <iostream>\nusing namespace opengeul::calc_dispatch;\nint main(){'
        source+=';'.join('std::cout << '+entry+' << " "' for entry in entries)+';}'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);src=root/'abi.cpp';src.write_text(source)
            image=root/'abi'
            subprocess.run([compiler,'-std=c++17','-I',str(MODULE.parents[1]/'engine-build/calc-dispatch-diagnostic'),
                            str(src),'-o',str(image)],check=True,capture_output=True,timeout=30)
            output=subprocess.check_output([str(image)],text=True,timeout=5)
        self.assertEqual(tuple(map(int,output.split())),d.abi_layout())


if __name__=='__main__':unittest.main()
