from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'e2e'))
"""Offline IME contract regression; never an OS or product success receipt."""
import copy
import unittest
import windows_ime as ime
from test_native_input_policy import FOCUS,PROCESSES

PROFILE={'layout':0xe0010412,'isIme':True,'underSystemDirectory':True,'fileName':'IMKR.IME',
         'fileSha256':'a'*64,'signatureStatus':'Valid',
         'signerSubject':'CN=Microsoft Windows, O=Microsoft Corporation, C=US'}

class ImeProfileTests(unittest.TestCase):
    def test_changed_bound_document_page_blocks_input_without_activation_click(self):
        class Page:
            def evaluate(self,script):return True
        class Scope:
            page=Page()
            def __init__(self):self.reads=0
            def _ready(self):
                self.reads+=1
                return {'pageKey':'A' if self.reads==1 else 'B','hwnd':101}
            def prepare(self):raise AssertionError('A preservation check must never move the caret')
        keyboard=ime.WindowsKeyboard.__new__(ime.WindowsKeyboard)
        keyboard.owner_scope=Scope();keyboard.snapshot=lambda:dict(FOCUS);keyboard.processes=PROCESSES
        with self.assertRaisesRegex(AssertionError,'page/HWND'):keyboard.ready()

    def test_same_bound_page_checks_focus_without_calling_physical_prepare(self):
        class Page:
            def evaluate(self,script):return True
        class Scope:
            page=Page()
            def _ready(self):return {'pageKey':'A','hwnd':101}
            def prepare(self):raise AssertionError('A preservation check must never move the caret')
        keyboard=ime.WindowsKeyboard.__new__(ime.WindowsKeyboard)
        keyboard.owner_scope=Scope();keyboard.snapshot=lambda:dict(FOCUS);keyboard.processes=PROCESSES
        self.assertEqual(keyboard.ready()['focusTid'],12)

    def test_live_composition_comes_only_from_trusted_bounded_events(self):
        self.assertTrue(hasattr(ime,'inspect_live_composition'),'Live trusted composition parser is missing')
        live=[{'type':'compositionstart','isTrusted':True,'data':''},
              {'type':'compositionupdate','isTrusted':True,'data':'한'},
              {'type':'compositionend','isTrusted':True,'data':'한'},
              {'type':'compositionstart','isTrusted':True,'data':''},
              {'type':'compositionupdate','isTrusted':True,'data':'글'}]
        self.assertEqual(ime.inspect_live_composition(live,'한글')['pending'],'글')
        for rows in (live[:-1],live+[{'type':'compositionend','isTrusted':True,'data':'글'}],
                     [{**row,'isTrusted':False} for row in live],
                     [{**row,'data':'x'*257} for row in live]):
            with self.subTest(rows=rows),self.assertRaises(AssertionError):ime.inspect_live_composition(rows,'한글')

    def test_initial_mode_requires_real_keys_saved_body_and_matching_trusted_events(self):
        self.assertTrue(hasattr(ime,'inspect_mode_probe'),'Actual keyboard/body mode probe contract is missing')
        english=[{'type':'input','isTrusted':True,'data':value,'inputType':'insertText'} for value in 'gks']
        korean=[{'type':'compositionstart','isTrusted':True,'data':''},
                {'type':'compositionupdate','isTrusted':True,'data':'한'},
                {'type':'compositionend','isTrusted':True,'data':'한'}]
        self.assertFalse(ime.inspect_mode_probe(english,'gks')['native'])
        self.assertTrue(ime.inspect_mode_probe(korean,'한')['native'])
        for events,body in (([], 'gks'),(english,'한'),(korean,'gks'),(korean,'unknown'),
                            ([{**row,'isTrusted':False} for row in korean],'한')):
            with self.subTest(body=body),self.assertRaises(AssertionError):ime.inspect_mode_probe(events,body)

    def test_microsoft_identity_requires_actual_ime_system_file_and_valid_publisher(self):
        self.assertTrue(hasattr(ime,'require_microsoft_profile'),'Actual Microsoft IME identity contract is missing')
        self.assertEqual(ime.require_microsoft_profile(PROFILE)['layout'],0xe0010412)
        for key,value in (('layout',0x409),('isIme',False),('underSystemDirectory',False),('fileSha256','x'),
                          ('signatureStatus','NotSigned'),('signerSubject','O=Microsoft Corporation Evil'),
                          ('signerSubject','O=Other Vendor'),('fileName','unverified.exe')):
            row={**PROFILE,key:value}
            with self.subTest(key=key,value=value),self.assertRaises(AssertionError):ime.require_microsoft_profile(row)

    def test_cancel_requires_real_empty_end_after_live_composition_without_ghost_input(self):
        self.assertTrue(hasattr(ime,'inspect_cancelled_composition'),'Actual cancellation receipt contract is missing')
        events=[{'type':'compositionstart','isTrusted':True,'data':''},
                {'type':'compositionupdate','isTrusted':True,'data':'가'},
                {'type':'compositionend','isTrusted':True,'data':''}]
        self.assertTrue(ime.inspect_cancelled_composition(events)['cancelled'])
        for bad in (events[:-1],[{**row,'isTrusted':False} for row in events],
                    [*events[:-1],{**events[-1],'data':'가'}],
                    [*events,{'type':'input','isTrusted':True,'data':'가'}]):
            with self.subTest(events=bad),self.assertRaises(AssertionError):ime.inspect_cancelled_composition(bad)

    def test_profile_switch_cannot_accept_layout_only_or_missing_capability(self):
        self.assertTrue(hasattr(ime,'require_korean_prerequisites'),'Configured input prerequisites guard is missing')
        good={'koreanLanguageConfigured':True,'os':{'koreanBasicState':'Installed'},'layouts':[0xe0010412]}
        self.assertTrue(ime.require_korean_prerequisites(good))
        for key,value in (('koreanLanguageConfigured',False),('os',{'koreanBasicState':'NotPresent'}),('layouts',[0x409])):
            with self.subTest(key=key),self.assertRaises(AssertionError):ime.require_korean_prerequisites({**good,key:value})

if __name__=='__main__':unittest.main(verbosity=2)
