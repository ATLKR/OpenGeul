"""Diagnostic telemetry must never weaken the real source61 close selector."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'probe/native-close61.py'

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

OBS = load(PROBE, 'native_close61_observation') if PROBE.exists() else None
NATIVE = load(ROOT / 'e2e/password/native.py', 'original_native_password61')

class Window:
    def __init__(self, handle=10, pid=77, visible=True, enabled=True, title='OpenGeul', class_name='Tauri Window'):
        self.handle=handle;self.pid=pid;self.visible=visible;self.enabled=enabled;self.title=title;self.cls=class_name
        self.inputs=[];self.reads=[]
    def process_id(self):self.reads.append('pid');return self.pid
    def is_visible(self):self.reads.append('visible');return self.visible
    def is_enabled(self):self.reads.append('enabled');return self.enabled
    def window_text(self):self.reads.append('title');return self.title
    def class_name(self):self.reads.append('class');return self.cls
    def set_focus(self):self.inputs.append('focus')
    def type_keys(self,*args,**kwargs):self.inputs.append(('keys',args,kwargs))
    def descendants(self,*args,**kwargs):raise AssertionError('Telemetry must not read descendant text or inputs')

class NativeClose61ObservationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(OBS, 'Source61 bounded observation helper is not implemented')
    def original_call(self, windows, on_capture=None):
        class Desktop:
            def __init__(self, backend):assert backend=='win32'
            def windows(self, *, process):assert process==77;return windows
        session=types.SimpleNamespace(proc=types.SimpleNamespace(pid=77))
        captured=[]
        callback=on_capture if on_capture is not None else captured.append
        with patch.dict(sys.modules, {'pywinauto':types.SimpleNamespace(Desktop=Desktop)}):
            try:
                result=OBS.trace_original_selector(NATIVE.Qualification.request_native_close, None, session, callback)
            except AssertionError as e:
                result=e
        return result,captured
    def test_zero_candidates_preserves_original_assertion_and_has_no_close_input(self):
        w=Window(enabled=False)
        result,captured=self.original_call([w])
        self.assertIsInstance(result,AssertionError)
        self.assertEqual(str(result),'Expected one owned native editor window before requesting close')
        self.assertEqual(captured[0]['selectedCount'],0)
        self.assertEqual(w.inputs,[])
    def test_multiple_candidates_preserves_original_assertion_and_has_no_close_input(self):
        windows=[Window(handle=10),Window(handle=11)]
        result,captured=self.original_call(windows)
        self.assertIsInstance(result,AssertionError)
        self.assertEqual(captured[0]['selectedCount'],2)
        self.assertTrue(all(not w.inputs for w in windows))
    def test_one_original_candidate_uses_unmodified_physical_alt_f4_once(self):
        w=Window();result,captured=self.original_call([w])
        self.assertEqual(result['hwnd'],10)
        self.assertEqual(result['input'],'physical Alt+F4')
        self.assertEqual(captured[0]['selectedCount'],1)
        self.assertEqual(w.inputs,['focus',('keys',('%{F4}',),{'set_foreground':True})])
    def test_callback_failure_does_not_shadow_original_selector_failure(self):
        def broken(_):raise RuntimeError('observation failed')
        before=sys.gettrace();result,_=self.original_call([],broken)
        self.assertIsInstance(result,AssertionError)
        self.assertEqual(str(result),'Expected one owned native editor window before requesting close')
        self.assertIs(sys.gettrace(),before)
    def test_trace_is_restored_after_original_success(self):
        before=sys.gettrace();self.original_call([Window()]);self.assertIs(sys.gettrace(),before)
    def test_foreign_window_metadata_is_never_read_or_serialized(self):
        foreign=Window(pid=88,title='FOREIGN_PRIVATE_TEXT')
        data=OBS.window_snapshot([foreign,Window()],77,'before-modal',0)
        self.assertEqual(data['foreignRejectedCount'],1)
        self.assertEqual(foreign.reads,['pid'])
        self.assertNotIn('FOREIGN_PRIVATE_TEXT',json.dumps(data))
        self.assertEqual(data['ownedCount'],1)
    def test_rejected_flags_are_explained_without_descendant_reads(self):
        windows=[Window(handle=1,visible=False),Window(handle=2,enabled=False),Window(handle=3,title=''),Window(handle=4,class_name='#32770')]
        data=OBS.window_snapshot(windows,77,'after-error',0)
        self.assertEqual(data['eligibleCount'],0)
        self.assertEqual([r['rejectedReasons'] for r in data['windows']],[['not-visible'],['not-enabled'],['empty-title'],['dialog-class']])
    def test_title_class_and_whole_snapshot_are_bounded(self):
        windows=[Window(handle=i+1,title='한'*500,class_name='한'*200) for i in range(100)]
        data=OBS.window_snapshot(windows,77,'after-error',0)
        raw=OBS.encode_snapshot(data)
        self.assertLessEqual(len(raw),16*1024)
        self.assertTrue(data['metadataTruncated'])
        self.assertEqual(data['rawCount'],100)
        self.assertEqual(data['ownedCount'],100)
        self.assertTrue(all(len(w['title'])<=256 and len(w['class'])<=64 for w in data['windows']))
    def test_duplicate_hwnds_remain_visible_in_counts(self):
        data=OBS.window_snapshot([Window(handle=10),Window(handle=10)],77,'after-error',0)
        self.assertEqual(data['eligibleCount'],2)
        self.assertEqual(data['duplicateOwnedHandles'],1)
    def test_foreign_pid_cannot_be_used_as_diagnostic_owner(self):
        with self.assertRaises(AssertionError):OBS.window_snapshot([],0,'after-error',0)
    def test_transport_source_and_engine_must_match_frozen_editor61(self):
        source={'sourceCommit':OBS.SOURCE,'sourceRun':OBS.SOURCE_RUN,'editorSha256':OBS.EDITOR_SHA,'wasmRebuild':{'artifacts':{'rhwp.js':'a'*64}},'qualification':'native-close-diagnostic-only','diagnosticOnly':True,'qualifiedPackage':False}
        engine={'qualification':'final-source-bound','provenance':source['wasmRebuild']}
        OBS.verify_source_binding(source,engine)
        for key,value in (('sourceCommit','b'*40),('sourceRun',57),('editorSha256','b'*64)):
            altered={**source,key:value}
            with self.subTest(key=key),self.assertRaises(AssertionError):OBS.verify_source_binding(altered,engine)
        with self.assertRaises(AssertionError):OBS.verify_source_binding(source,{**engine,'qualification':'preliminary-pinned-vendor'})
    def test_absent_rebuild_proof_cannot_acquire_source_bound_label(self):
        source={'sourceCommit':OBS.SOURCE,'sourceRun':OBS.SOURCE_RUN,'editorSha256':OBS.EDITOR_SHA,'wasmRebuild':None,'qualification':'native-close-diagnostic-only','diagnosticOnly':True,'qualifiedPackage':False}
        with self.assertRaises(AssertionError):OBS.verify_source_binding(source,{'qualification':'final-source-bound','provenance':None})
    def test_full_package_qualification_claim_cannot_enter_diagnostic(self):
        source={'sourceCommit':OBS.SOURCE,'sourceRun':OBS.SOURCE_RUN,'editorSha256':OBS.EDITOR_SHA,'wasmRebuild':{'artifacts':{'rhwp.js':'a'*64}},'qualification':'native-close-diagnostic-only','diagnosticOnly':True,'qualifiedPackage':True}
        with self.assertRaises(AssertionError):OBS.verify_source_binding(source,{'qualification':'final-source-bound','provenance':source['wasmRebuild']})
    def test_result_never_qualifies_failed_source_or_full_password_suite(self):
        result=OBS.base_result()
        self.assertIs(result['qualification'],False)
        self.assertIs(result['sourceQualified'],False)
        self.assertIs(result['fullPasswordSuiteQualified'],False)
        self.assertEqual(result['sourceCommit'],OBS.SOURCE)
        self.assertEqual(result['sourceRun'],38161639847)

if __name__=='__main__':unittest.main()
