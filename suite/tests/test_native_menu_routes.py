"""Current GUI scenarios consume the native proof, never the old File strip."""
from contextlib import ExitStack
import copy
import importlib
from types import SimpleNamespace as NS
import sys
import unittest
from unittest.mock import patch

import test_owned_native_menu as boundaries


class NativeMenuRouteTests(unittest.TestCase):
    def fixture(self):
        helper=boundaries.OwnedNativeMenuTests();helper.setUp();self.addCleanup(helper.doCleanups)
        policy,api,process,record,clock,probe=helper.fixture()
        menu=importlib.import_module('owned_native_menu');home=importlib.import_module('home_routing_smoke');life=importlib.import_module('lifecycle_smoke')
        api.require_foreground=lambda hwnd:None;api.pid=lambda hwnd:77;api.user.IsWindow=lambda hwnd:True
        current=policy.click_native_menu_action;commands=[];legacy=[]
        def native_action(a,p,h,r,command):
            commands.append(command)
            return current(a,p,h,r,command,probe=probe,clock=clock)
        olditem=NS(element_info=NS(name='파일',process_id=77,runtime_id=[1,2]),is_visible=lambda:True,is_enabled=lambda:True,
                   click_input=lambda:legacy.append('old-item'))
        desktop=lambda **kwargs:NS(window=lambda **kwargs:NS(wrapper_object=lambda:NS(descendants=lambda **kwargs:[olditem])))
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.dict(sys.modules,{'pywinauto':NS(Desktop=desktop)}))
        stack.enter_context(patch.object(menu,'click_native_menu_action',side_effect=native_action))
        stack.enter_context(patch.object(life.native,'activate_owned_suite',side_effect=lambda *a:None))
        if home.native is not life.native:
            stack.enter_context(patch.object(home.native,'activate_owned_suite',side_effect=lambda *a:None))
            stack.enter_context(patch.object(home.native,'click_owned_control',side_effect=lambda *a,**k:legacy.append(k.get('purpose'))))
        stack.enter_context(patch.object(life.native,'click_owned_control',side_effect=lambda *a,**k:legacy.append(k.get('purpose'))))
        stack.enter_context(patch.object(life.native,'send_host_menu_shortcut',side_effect=lambda *a,**k:legacy.append(k.get('shortcut'))))
        stack.enter_context(patch.object(life,'owned_menu_items',return_value=[olditem]))
        case=object.__new__(life.Case);case.api,case.process,case.record=api,process,record
        return home,life,case,commands,legacy,probe
    def test_lifecycle_save_and_saveas_physically_use_native_items(self):
        for keys,expected in (('^s','save'),('^+s','saveAs')):
            with self.subTest(keys=keys):
                _,_,case,commands,legacy,_=self.fixture();case.shell_command(11,keys)
                self.assertEqual(commands,[expected]);self.assertEqual(legacy,[])
                self.assertEqual(case.record['nativeMenuActions'][-1]['kind'],'owned-native-menu-action')
    def test_new_document_uses_native_factory_submenu(self):
        _,_,case,commands,legacy,_=self.fixture();case.new_from_menu(11)
        self.assertEqual(commands,['new-writer']);self.assertEqual(legacy,[])
    def test_home_open_and_close_keep_separate_native_proof(self):
        for label,expected in (('열기…','open'),('닫기','close')):
            with self.subTest(label=label):
                home,_,case,commands,legacy,_=self.fixture()
                result=home.shell_menu_action(case.api,case.process,11,label,case.record)
                self.assertEqual(commands,[expected]);self.assertEqual(legacy,[])
                self.assertEqual(result['kind'],'owned-native-document-menu-route')
                self.assertEqual(result['nativeAction']['command'],expected)
    def test_native_missing_does_not_fall_back_to_winforms(self):
        home,_,case,commands,legacy,probe=self.fixture()
        case.api.user.GetPropW=lambda *args:0
        with self.assertRaises(AssertionError):home.shell_menu_action(case.api,case.process,11,'열기…',case.record)
        self.assertEqual(commands,['open']);self.assertEqual(legacy,[])
        self.assertFalse(any(isinstance(c,tuple) and c[0]=='click' for c in probe.calls))
    def test_base_picker_cannot_predate_native_menu_input(self):
        from test_base_save_readiness import BaseSaveReadinessTests,smoke,CAPTION
        helper=BaseSaveReadinessTests();helper.setUp();self.addCleanup(helper.doCleanups)
        _,record,_,error=helper.run_case([lambda boundary:[boundary.edit,boundary.save]])
        self.assertIsNone(error)
        proof=copy.deepcopy(record['baseSaveDialogReadiness'])
        smoke.require_base_save_dialog_readiness(proof,77,11,CAPTION)
        proof['startedAt']=proof['saveMenuAction']['finishedAt']-.01
        proof['deadline']=proof['startedAt']+20
        with self.assertRaises(AssertionError):smoke.require_base_save_dialog_readiness(proof,77,11,CAPTION)
