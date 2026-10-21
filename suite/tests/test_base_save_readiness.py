"""Actual Base Save As orchestration with only native/UIA boundaries replaced."""
import copy
import ctypes
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('base_save_readiness_source', Path(__file__).resolve().parents[1] / 'e2e/windows_smoke.py')
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)
CAPTION = 'OpenGeul Base — 다른 이름으로 저장'


class ProviderError(Exception):
    hresult = -2147220991


class Clock:
    def __init__(self): self.value = 100.0
    def monotonic(self): return self.value
    def sleep(self, seconds): self.value += seconds


class Element:
    def __init__(self, identity, kind, handle, automation_id='', parent=None, *, pid=77, enabled=True, offscreen=False):
        self.identity, self.parent = identity, parent
        self.CurrentAutomationId, self.CurrentControlType = automation_id, kind
        self.CurrentNativeWindowHandle, self.CurrentProcessId = handle, pid
        self.CurrentIsEnabled, self.CurrentIsOffscreen = enabled, offscreen
        self.CurrentName = 'test-control'
    def __getattribute__(self,name):
        if name == object.__getattribute__(self,'__dict__').get('fail_property'):
            raise ProviderError('property disconnected: '+name)
        return object.__getattribute__(self,name)
    def GetRuntimeId(self): return [42, self.identity]


class Array:
    def __init__(self, elements): self.elements = elements
    @property
    def Length(self): return len(self.elements)
    def GetElement(self, index): return self.elements[index]


class NativeBoundary:
    def __init__(self, states):
        self.clock, self.states, self.calls = Clock(), list(states), []
        self.foreground, self.closed = 11, False
        self.process=SimpleNamespace(pid=77,poll=lambda:None)
        self.root = Element(44, 50032, 44)
        self.edit = Element(101, 50004, 101, '1001', self.root)
        self.save = Element(102, 50000, 102, '1', self.root)
        self.state_index, self.query_count = 0, 0
        self.last_elements, self.current_value = [], ''
        self.root.FindAll = self.find_all
        self.api = SimpleNamespace(user=SimpleNamespace(
            GetWindow=lambda hwnd, flag: 11 if hwnd == 44 else 0,
            IsWindow=lambda hwnd: hwnd in (11, 44, 101, 102, 103, 104) and not (self.closed and hwnd == 44),
            IsChild=lambda parent, child: parent == 44 and child in (101, 102, 103, 104),
            IsWindowVisible=lambda hwnd: True,
            GetAncestor=lambda hwnd, flag: 44 if hwnd in (44, 101, 102, 103, 104) else 11,
            GetForegroundWindow=lambda: self.foreground),
            windows=lambda pid: [] if self.closed else [44],
            title=lambda hwnd: CAPTION if hwnd == 44 else 'OpenGeul Base',
            class_name=lambda hwnd: '#32770' if hwnd == 44 else 'Button' if hwnd == 102 else 'Edit',
            pid=lambda hwnd: 77,
            require_foreground=self.require_foreground,
            _focus_window=self.window)
        self.uia = SimpleNamespace(true_condition=object(), tree_scope={'descendants': 4})
        self.uia.iuia = SimpleNamespace(
            CreateOrCondition=lambda a,b: ('or',a,b),
            CompareElements=lambda a,b: a is b,
            ControlViewWalker=SimpleNamespace(GetParentElement=lambda element: element.parent))
        self.uia.build_condition = lambda **kwargs: kwargs

    def window(self, hwnd):
        return {'hwnd': hwnd, 'isWindow': bool(self.api.user.IsWindow(hwnd)), 'pid': 77,
                'threadId': 90, 'rootHwnd': self.api.user.GetAncestor(hwnd, 2),
                'className': self.api.class_name(hwnd)}
    def require_foreground(self, hwnd):
        if self.foreground != hwnd: raise AssertionError('foreign foreground')
    def find_all(self, scope, condition):
        self.query_count += 1
        state = self.states[min(self.state_index, len(self.states)-1)]
        self.state_index += 1
        if isinstance(state, Exception): raise state
        self.last_elements = state(self) if callable(state) else state
        return Array(self.last_elements)
    def wrapper(self, element):
        boundary = self
        class Wrapper:
            element_info = SimpleNamespace(_element=element, element=element,
                automation_id=element.CurrentAutomationId, process_id=element.CurrentProcessId,
                runtime_id=element.GetRuntimeId(), handle=element.CurrentNativeWindowHandle)
            @property
            def iface_value(self): return SimpleNamespace(CurrentValue=boundary.current_value)
            def is_visible(self): return not element.CurrentIsOffscreen
            def is_enabled(self): return element.CurrentIsEnabled
            def click_input(self):
                boundary.calls.append(('filename-click' if element is boundary.edit else 'save-click', boundary.clock.value))
                if element is boundary.save:
                    boundary.closed=True
                    boundary.target.write_bytes(b'saved-generated-odb')
        return Wrapper()
    def desktop(self, backend):
        boundary=self
        class Window:
            def wrapper_object(self): return self
            def class_name(self): return '#32770'
            def set_focus(self):
                boundary.calls.append(('dialog-focus', boundary.clock.value));boundary.foreground=44
            def capture_as_image(self): return SimpleNamespace(save=lambda path: boundary.calls.append(('screenshot', boundary.clock.value)))
            @property
            def element_info(self): return SimpleNamespace(_element=boundary.root)
            def descendants(self, control_type):
                if control_type=='MenuItem':
                    return [SimpleNamespace(element_info=SimpleNamespace(name='파일',process_id=77),
                        is_visible=lambda:True,is_enabled=lambda:True,
                        click_input=lambda:boundary.calls.append(('file-menu-click',boundary.clock.value)))]
                # Original source's single-pass UIA query is also exercised for RED.
                if control_type=='Edit':
                    boundary.find_all(4,None)
                kind=50004 if control_type=='Edit' else 50000
                return [boundary.wrapper(e) for e in boundary.last_elements if e.CurrentControlType==kind]
        return SimpleNamespace(window=lambda handle:Window())
    def send_keys(self, keys, **kwargs):
        if keys=='^s': self.calls.append(('save-shortcut',self.clock.value))
        elif keys=='^a': self.calls.append(('select-filename',self.clock.value))
        else: self.calls.append(('type-path',self.clock.value));self.current_value=keys
    def assign_filename(self, api, pid, document, dialog, accessible, field, target, record, **kwargs):
        # Readiness orchestration substitutes the separately tested native
        # filename boundary; it does not claim a real Windows Edit transaction.
        field.click_input()
        self.calls.append(('assign-filename',self.clock.value))
        before=self.current_value;self.current_value=str(target)
        record.setdefault('pickerFilenameInputs',[]).append(dict(method='Win32-Edit-EM_REPLACESEL',
            expected=str(target),before=before,after=self.current_value,success=True))
    def measured_click(self, api, process, document, control, record, **kwargs):
        if kwargs['purpose']=='FILE_MENU':self.calls.append(('file-menu-click',self.clock.value))
        else:
            assert kwargs['purpose']=='SAVE_BUTTON'
            control.click_input()
    def counted_shortcut(self, *args, **kwargs):
        assert kwargs['shortcut']=='CTRL_S'
        self.send_keys('^s')
    def modules(self):
        return {'pywinauto':SimpleNamespace(Desktop=lambda backend:self.desktop(backend)),
          'pywinauto.keyboard':SimpleNamespace(send_keys=self.send_keys),
          'pywinauto.uia_defines':SimpleNamespace(IUIA=lambda:self.uia),
          'pywinauto.uia_element_info':SimpleNamespace(UIAElementInfo=lambda element:SimpleNamespace(_element=element,element=element)),
          'pywinauto.controls':SimpleNamespace(),
          'pywinauto.controls.uiawrapper':SimpleNamespace(UIAWrapper=lambda info:self.wrapper(info._element))}


class BaseSaveReadinessTests(unittest.TestCase):
    def run_case(self, states, *, mutate=None, clock_frozen=False):
        import lifecycle_smoke
        boundary=NativeBoundary(states)
        if mutate: mutate(boundary)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixtures=root/'fixtures';fixtures.mkdir()
            boundary.target=fixtures/'New-OpenGeul-base.odb';record={}
            with patch.dict(sys.modules,boundary.modules()), \
                 patch.object(smoke.time,'monotonic',side_effect=boundary.clock.monotonic), \
                 patch.object(smoke.time,'sleep',side_effect=(lambda seconds:None) if clock_frozen else boundary.clock.sleep), \
                 patch.object(smoke,'click_owned_control',side_effect=boundary.measured_click), \
                 patch.object(smoke,'send_host_menu_shortcut',side_effect=boundary.counted_shortcut), \
                 patch.object(lifecycle_smoke,'set_owned_picker_filename',side_effect=boundary.assign_filename), \
                 patch.object(smoke,'saved_base_evidence',return_value={'sha256':'a'*64,'bytes':19,'connection':'sdbc:embedded:firebird'}):
                try: result=smoke.save_new_base(boundary.api,boundary.process,11,fixtures,root,record);error=None
                except Exception as exc: result=None;error=exc
            return boundary,record,result,error

    def no_filename_or_save_input(self,boundary):
        self.assertEqual([name for name,_ in boundary.calls if name in ('filename-click','select-filename','type-path','assign-filename','save-click')],[])
        self.assertEqual(sum(name=='file-menu-click' for name,_ in boundary.calls),1)
        self.assertEqual(sum(name=='save-shortcut' for name,_ in boundary.calls),1)

    def test_existing_dialog_pending_children_then_ready_uses_one_original_input_sequence(self):
        b,r,result,error=self.run_case([[],lambda b:[b.edit,b.save]])
        self.assertIsNone(error, str(error))
        self.assertIsNotNone(result)
        proof=r.get('baseSaveDialogReadiness')
        self.assertIsInstance(proof,dict,'Missing bounded readiness receipt')
        self.assertEqual(len(proof['observations']),2)
        self.assertEqual([o['state'] for o in proof['observations']],['pending','ready'])
        self.assertEqual([n for n,_ in b.calls],['file-menu-click','save-shortcut','dialog-focus','filename-click','assign-filename','screenshot','save-click'])
        self.assertLessEqual(proof['finishedAt'],proof['deadline'])
        smoke.require_base_save_dialog_readiness(proof,77,11,CAPTION)

    def test_missing_children_exhaust_same_twenty_seconds_without_typing(self):
        b,r,_,error=self.run_case([[]])
        self.assertIsNotNone(error)
        self.assertIn('deadline',str(error).lower())
        self.no_filename_or_save_input(b)
        proof=r.get('baseSaveDialogReadiness',{})
        self.assertEqual(proof.get('deadline',0)-proof.get('startedAt',0),20)
        self.assertGreater(len(proof.get('observations',[])),1)
        self.assertLessEqual(len(proof['observations']),201)

    def test_duplicate_even_disabled_exact_id_fails_before_typing(self):
        b,r,_,error=self.run_case([lambda b:[b.edit,b.save,Element(103,50004,103,'1001',b.root,enabled=False)]])
        self.assertIsNotNone(error)
        self.assertIn('ambiguous',str(error).lower())
        self.no_filename_or_save_input(b)
        self.assertEqual(b.query_count,1)

    def test_foreign_candidate_is_rejected_before_typing(self):
        b,r,_,error=self.run_case([lambda b:[Element(101,50004,101,'1001',b.root,pid=999),b.save]])
        self.assertIsNotNone(error)
        self.assertIn('foreign',str(error).lower())
        self.no_filename_or_save_input(b)

    def test_raw_findall_hresult_is_retained_and_never_retried(self):
        b,r,_,error=self.run_case([ProviderError('provider disconnected'),lambda b:[b.edit,b.save]])
        self.assertIsNotNone(error)
        self.no_filename_or_save_input(b)
        self.assertEqual(b.query_count,1)
        proof=r.get('baseSaveDialogReadiness',{})
        self.assertIn('observations',proof,'Missing original raw provider failure receipt')
        self.assertEqual(proof['observations'][0]['apiError']['hresult'],ProviderError.hresult)
        self.assertIn('FindAll',proof['observations'][0]['apiError']['operation'])

    def test_hidden_and_disabled_can_be_pending_but_only_exact_ready_controls_allow_input(self):
        def hidden(b): b.edit.CurrentIsOffscreen=True;return [b.edit,b.save]
        def disabled(b): b.edit.CurrentIsOffscreen=False;b.save.CurrentIsEnabled=False;return [b.edit,b.save]
        def ready(b): b.save.CurrentIsEnabled=True;return [b.edit,b.save]
        b,r,_,error=self.run_case([hidden,disabled,ready])
        self.assertIsNone(error,str(error))
        self.assertEqual([o['state'] for o in r['baseSaveDialogReadiness']['observations']],['pending','pending','ready'])
        self.assertEqual(sum(n=='dialog-focus' for n,_ in b.calls),1)

    def test_unadvancing_clock_has_finite_read_only_observation_limit(self):
        b,r,_,error=self.run_case([[]],clock_frozen=True)
        self.assertIsNotNone(error)
        self.assertIn('observation',str(error).lower())
        self.no_filename_or_save_input(b)
        self.assertLessEqual(b.query_count,201)

    def test_property_hresult_keeps_raw_partial_identity_and_never_types(self):
        def broken(b): b.edit.fail_property='CurrentIsEnabled';return [b.edit,b.save]
        b,r,_,error=self.run_case([broken,lambda b:[b.edit,b.save]])
        self.assertIsNotNone(error)
        self.no_filename_or_save_input(b)
        observation=r['baseSaveDialogReadiness']['observations'][0]
        self.assertEqual(observation['apiError']['operation'],'CurrentIsEnabled')
        self.assertEqual(observation['apiError']['hresult'],ProviderError.hresult)
        self.assertEqual(observation['controls'][0].get('automationId'),'1001','Discarded properties read before failing API')
        self.assertEqual(b.query_count,1)

    def test_array_length_and_element_hresult_are_not_skipped(self):
        for operation in ('Length','GetElement'):
            def setup(b):
                def find(scope,condition):
                    b.query_count+=1
                    class BrokenArray:
                        @property
                        def Length(self):
                            if operation=='Length': raise ProviderError('bad length')
                            return 2
                        def GetElement(self,index): raise ProviderError('bad element')
                    return BrokenArray()
                b.root.FindAll=find
            with self.subTest(operation=operation):
                b,r,_,error=self.run_case([[]],mutate=setup)
                self.assertIsNotNone(error);self.no_filename_or_save_input(b)
                observation=r['baseSaveDialogReadiness']['observations'][0]
                self.assertIn(operation,observation['apiError']['operation'])
                self.assertEqual(observation['apiError']['hresult'],ProviderError.hresult)
                self.assertEqual(b.query_count,1)

    def test_zero_hwnd_directui_control_requires_actual_owned_uia_parent_chain(self):
        def directui(b): b.edit.CurrentNativeWindowHandle=0;return [b.edit,b.save]
        b,r,_,error=self.run_case([directui])
        self.assertIsNone(error,str(error))
        smoke.require_base_save_dialog_readiness(r['baseSaveDialogReadiness'],77,11,CAPTION)
        def foreign(b):
            b.edit.CurrentNativeWindowHandle=0;b.edit.parent=Element(999,50032,999,pid=999)
            return [b.edit,b.save]
        b,r,_,error=self.run_case([foreign])
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)

    def test_native_owner_change_during_findall_fails_before_typing(self):
        def changed(b):
            b.api.user.GetWindow=lambda hwnd,flag:999
            return [b.edit,b.save]
        b,r,_,error=self.run_case([changed])
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        self.assertEqual(r['baseSaveDialogReadiness']['observations'][0]['after']['ownerHwnd'],999)

    def test_uia_root_replacement_after_pending_is_not_a_new_readiness_attempt(self):
        def replaced(b): b.root.identity=444;return [b.edit,b.save]
        b,r,_,error=self.run_case([[],replaced])
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        self.assertEqual(b.query_count,2)

    def test_initial_window_wait_consumes_the_same_original_deadline(self):
        def late_window(b): b.api.windows=lambda pid:[44] if b.clock.value>=119.8 else []
        b,r,_,error=self.run_case([[],[],lambda b:[b.edit,b.save]],mutate=late_window)
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        proof=r['baseSaveDialogReadiness']
        self.assertEqual(proof['deadline'],120)
        self.assertLessEqual(proof['finishedAt'],120.000001)
        self.assertLessEqual(b.query_count,2)

    def test_ready_result_after_deadline_never_types_or_saves(self):
        def late(b): b.clock.value+=20.1;return [b.edit,b.save]
        b,r,_,error=self.run_case([late])
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        self.assertIn('deadline',str(error).lower())

    def test_wrapper_hresult_is_retained_without_filename_input(self):
        def setup(b):
            def broken(element): raise ProviderError('wrapper unavailable')
            b.wrapper=broken
        b,r,_,error=self.run_case([lambda b:[b.edit,b.save]],mutate=setup)
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        proof=r['baseSaveDialogReadiness']
        self.assertIn('bindingError',proof,'Lost wrapper failure HRESULT')
        self.assertEqual(proof['bindingError']['hresult'],ProviderError.hresult)

    def test_portable_replay_rejects_wrong_states_deadlines_and_raw_identity(self):
        _,record,_,error=self.run_case([[],lambda b:[b.edit,b.save]])
        self.assertIsNone(error,str(error))
        original=record['baseSaveDialogReadiness']
        mutations={
            'state':lambda p:p['observations'][0].update(state='ready'),
            'order':lambda p:p['observations'].reverse(),
            'count':lambda p:p['observations'][-1].update(rawCount=99),
            'apiError':lambda p:p['observations'][-1].update(apiError={'operation':'FindAll','hresult':-1}),
            'late':lambda p:p.update(finishedAt=p['deadline']+0.1),
            'earlyInput':lambda p:p.update(filenameInputStartedAt=p['startedAt']-0.1),
            'missingInput':lambda p:p.pop('filenameInputStartedAt'),
            'foreignOwner':lambda p:p['observations'][-1]['after'].update(ownerHwnd=999),
            'rootID':lambda p:p['observations'][-1]['uiaRoot'].update(runtimeId=[42,999]),
            'wrapper':lambda p:p['wrapperBindings'][0].update(rawElementEquals=False),
        }
        for name,mutate in mutations.items():
            proof=copy.deepcopy(original);mutate(proof)
            with self.subTest(name=name),self.assertRaises((AssertionError,ValueError,TypeError,KeyError)):
                smoke.require_base_save_dialog_readiness(proof,77,11,CAPTION)

    def test_portable_replay_rejects_boolean_action_counts_and_changed_native_thread(self):
        _,record,_,error=self.run_case([lambda b:[b.edit,b.save]])
        self.assertIsNone(error,str(error))
        original=record['baseSaveDialogReadiness']
        for name,mutate in {
            'clickCount':lambda p:p.update(fileMenuClicks=True),
            'shortcutCount':lambda p:p.update(saveShortcuts=True),
            'focusCount':lambda p:p['focusAction'].update(count=True),
            'nativeThread':lambda p:p['observations'][0]['after']['dialog'].update(threadId=91),
        }.items():
            proof=copy.deepcopy(original);mutate(proof)
            with self.subTest(name=name),self.assertRaises((AssertionError,ValueError,TypeError,KeyError)):
                smoke.require_base_save_dialog_readiness(proof,77,11,CAPTION)

    def test_raw_candidate_counts_and_fatal_state_survive_failure(self):
        b,r,_,error=self.run_case([lambda b:[b.edit,b.save,Element(103,50004,103,'1001',b.root,enabled=False)]])
        self.assertIsNotNone(error)
        observation=r['baseSaveDialogReadiness']['observations'][0]
        self.assertEqual(observation.get('candidateCounts'),{'filename':2,'save':1})
        self.assertEqual(observation.get('state'),'failed')
        b,r,_,error=self.run_case([ProviderError('broken')])
        observation=r['baseSaveDialogReadiness']['observations'][0]
        self.assertEqual(observation.get('state'),'failed')
        self.assertEqual(observation['apiError'].get('arguments'),['broken'])

    def test_nested_same_process_uia_window_cannot_supply_outer_save_controls(self):
        def nested(b):
            inner=Element(303,50032,0,parent=b.root)
            b.edit.parent=inner
            return [b.edit,b.save]
        b,r,_,error=self.run_case([nested])
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        self.assertIn('nested',str(error).lower())

    def test_missing_window_and_original_process_exit_never_query_or_focus(self):
        def absent(b): b.api.windows=lambda pid:[]
        b,r,_,error=self.run_case([[]],mutate=absent)
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        self.assertEqual(b.query_count,0)
        self.assertEqual(sum(name=='dialog-focus' for name,_ in b.calls),0)
        def exited(b): b.process.poll=lambda:0
        b,r,_,error=self.run_case([lambda b:[b.edit,b.save]],mutate=exited)
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        self.assertEqual(b.query_count,0)

    def test_native_candidate_process_mismatch_and_replaced_bound_dialog_fail_closed(self):
        def foreign_native(b):
            actual=b.api._focus_window
            b.api._focus_window=lambda hwnd:dict(actual(hwnd),pid=999) if hwnd==101 else actual(hwnd)
        b,r,_,error=self.run_case([lambda b:[b.edit,b.save]],mutate=foreign_native)
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        def disappeared(b): b.api.windows=lambda pid:[];return []
        b,r,_,error=self.run_case([disappeared,lambda b:[b.edit,b.save]])
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)
        self.assertEqual(b.query_count,1)

    def test_foreign_wrapper_reference_fails_before_filename_input(self):
        def setup(b):
            original=b.wrapper
            def wrapper(element):
                if element is b.edit:
                    return original(Element(404,50004,101,'1001',b.root))
                return original(element)
            b.wrapper=wrapper
        b,r,_,error=self.run_case([lambda b:[b.edit,b.save]],mutate=setup)
        self.assertIsNotNone(error);self.no_filename_or_save_input(b)

    def test_existing_filename_readback_mismatch_still_prevents_save(self):
        def setup(b):
            original=b.assign_filename
            def assign(*args,**kwargs):
                original(*args,**kwargs)
                b.current_value='wrong target'
            b.assign_filename=assign
        b,r,_,error=self.run_case([lambda b:[b.edit,b.save]],mutate=setup)
        self.assertIsNotNone(error)
        self.assertIn('filename differs',str(error))
        self.assertEqual(sum(name=='assign-filename' for name,_ in b.calls),1)
        self.assertEqual(sum(name=='save-click' for name,_ in b.calls),0)

    def test_lazy_uia_preparation_consumes_the_original_dialog_deadline(self):
        def setup(b):
            original=b.modules
            class DelayedImport:
                def __getattr__(self,name):
                    if name=='IUIA':
                        b.clock.value+=20.1
                        return lambda:b.uia
                    raise AttributeError(name)
            def modules():
                result=original();result['pywinauto.uia_defines']=DelayedImport();return result
            b.modules=modules
        b,r,_,error=self.run_case([lambda b:[b.edit,b.save]],mutate=setup)
        self.assertIsNotNone(error,'UIA preparation received a fresh20s deadline')
        self.no_filename_or_save_input(b)
        self.assertEqual(r['baseSaveDialogReadiness']['startedAt'],100)
        self.assertEqual(r['baseSaveDialogReadiness']['deadline'],120)
        self.assertEqual(b.query_count,0)

    def test_actual_ctypes_null_uia_hwnd_retains_raw_none_and_owned_directui_ancestry(self):
        def null_hwnd(b):
            b.edit.CurrentNativeWindowHandle=ctypes.c_void_p().__ctypes_from_outparam__()
            return [b.edit,b.save]
        b,r,_,error=self.run_case([null_hwnd])
        self.assertIsNone(error,str(error))
        row=r['baseSaveDialogReadiness']['observations'][0]['controls'][0]
        self.assertEqual(row['nativeHwnd'],0)
        self.assertIn('nativeHwndRaw',row)
        self.assertIsNone(row['nativeHwndRaw'])
        smoke.require_base_save_dialog_readiness(r['baseSaveDialogReadiness'],77,11,CAPTION)

    def test_only_successful_null_pointer_or_typed_integer_can_be_uia_hwnd(self):
        for invalid in (False,0.0,'0'):
            def invalid_hwnd(b): b.edit.CurrentNativeWindowHandle=invalid;return [b.edit,b.save]
            with self.subTest(value=repr(invalid)):
                b,r,_,error=self.run_case([invalid_hwnd])
                self.assertIsNotNone(error,'Invalid pointer metadata was treated as native HWND zero')
                self.no_filename_or_save_input(b)


if __name__=='__main__': unittest.main()
