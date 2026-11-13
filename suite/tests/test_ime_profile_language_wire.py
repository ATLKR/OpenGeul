"""Pure wire/source checks; no import of the Windows controller or source docs."""
import ast
import copy
import ctypes
import hashlib
import json
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'e2e/korean_ime_smoke.py'
TREE=ast.parse(SOURCE.read_bytes())
NAMES={'NativeProfileLanguageRecord','validate_profile_language','validate_restoration'}
namespace={'ctypes':ctypes,'re':re}
exec(compile(ast.Module(body=[node for node in TREE.body if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in NAMES],type_ignores=[]),str(SOURCE),'exec'),namespace)
# Independently frozen from original source SHA256
# 47cdabd1b6a062e4082e30adfc396b66c3314f350e85492319aa371e7626e393.
# No scratch tree, Git command or receipt-selected baseline is used at runtime.
# Python 3.12 added empty type_params to FunctionDef; all nonempty fields remain bound.
ORIGINAL_RESTORATION_AST_SHA256='ddbd4c8a785f7433c167c49ab0de1fa7f4e692edff688c7e6de5efe385efed56'
ORIGINAL_NATIVE_STATE_FIELDS_AST_SHA256='4bfa8a440949a7589c6082d8560478eaf3a3e6a31a6f33654af8589062072c9d'
def _ast_identity(node):
    if isinstance(node,ast.AST):
        return [type(node).__name__,[[key,_ast_identity(value)]for key,value in ast.iter_fields(node)
            if not(key=='type_params' and value==[])]]
    if isinstance(node,list):return [_ast_identity(value)for value in node]
    return node
def _ast_sha256(node):
    return hashlib.sha256(json.dumps(_ast_identity(node),ensure_ascii=True,separators=(',',':')).encode('ascii')).hexdigest()
class LanguageWireTests(unittest.TestCase):
    def record(self,command=4,changed=True):
        fields=namespace['NativeProfileLanguageRecord']._fields_
        r={name:0 for name,_ in fields};r.update(schemaVersion=1,command=command,complete=1,originalLanguage=0x409,
            observedBefore=0x412 if command==4 and changed else 0x409,interfaceAttempts=1,getterAttempts=1,observedMask=3)
        if command==4:
            r.update(observedAfterHkl=0x409,getterAttempts=3 if changed else 2,changeAttempts=int(changed),observedMask=31 if changed else 19)
            if changed:r['observedAfterChange']=0x409
        return r
    def test_fixed_record_size_and_all_integer_field_types(self):
        record=namespace['NativeProfileLanguageRecord'];self.assertEqual(ctypes.sizeof(record),68)
        self.assertEqual(len(record._fields_),17)
        self.assertTrue(all(kind in (ctypes.c_uint32,ctypes.c_int32) for _,kind in record._fields_))
    def test_capture_changed_and_unchanged_restore_records(self):
        for command,changed in ((1,False),(4,False),(4,True)):
            r=self.record(command,changed);self.assertIs(namespace['validate_profile_language'](r,command,0x409),r)
    def test_record_is_not_self_authenticating_and_incomplete_or_wrong_types_reject(self):
        for key,value in (('complete',0),('status',1),('observedAfterHkl',0x412),('originalLanguage',0x412),
                ('observedAfterChange',0x412),('changeHresult',-2147024809),('getBeforeHresult',1),
                ('getterAttempts',4),('changeAttempts',2),('observedMask',19),('interfaceAttempts',True),
                ('getAfterHklHresult',-1),('interfaceHresult',-1)):
            r=self.record();r[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):namespace['validate_profile_language'](r,4,0x409)
    def test_optional_new_record_cannot_invent_a_capture_or_skip_a_needed_transition(self):
        for command,changed,key,value in ((1,False,'observedAfterChange',0x409),(1,False,'observedBefore',0x412),
                (4,False,'observedBefore',0x412),(4,True,'observedBefore',0x409)):
            r=self.record(command,changed);r[key]=value
            with self.subTest(command=command,key=key),self.assertRaises(AssertionError):namespace['validate_profile_language'](r,command,0x409)
    def test_old_complete_profile_hkl_validator_is_byte_for_byte_ast_unchanged(self):
        candidate=next(node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name=='validate_restoration')
        self.assertEqual(_ast_sha256(candidate),ORIGINAL_RESTORATION_AST_SHA256)
    def test_wire_addition_keeps_the_entire_previous_native_state_field_prefix(self):
        def fields(tree):
            cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NativeState')
            return next(n.value.elts for n in cls.body if isinstance(n,ast.Assign))
        after=fields(TREE)
        self.assertEqual(_ast_sha256(after[:-1]),ORIGINAL_NATIVE_STATE_FIELDS_AST_SHA256)
        self.assertEqual(ast.literal_eval(after[-1].elts[0]),'profileLanguage')
    def test_new_producer_requires_language_evidence_before_restoration_success(self):
        source=SOURCE.read_text();start=source.index('            if command == 4:\n                assert int(self.api.user.GetKeyboardLayout')
        end=source.index("                self.restored = True",start)
        block=source[start:end]
        self.assertLess(block.index('validate_restoration(row)'),block.index("validate_profile_language(row['profileLanguage'],4"))
        self.assertLess(block.index('validate_profile_language'),block.index('profileHklRestored=True'))
        self.assertIn("'ime_profile_language.h'",source)
    def test_windows_adapter_has_formal_qi_release_and_no_global_activation_flags(self):
        source=SOURCE.read_text();start=source.index('class ProfileLanguageApi {');end=source.index('static bool same_profile',start);adapter=source[start:end]
        self.assertIn('QueryInterface(__uuidof(ITfInputProcessorProfiles)',adapter)
        self.assertIn('if(reader)reader->Release()',adapter)
        self.assertIn('original_target(target,sequence!=4)&&budget(limits)',adapter)
        self.assertNotIn('CoCreateInstance',adapter)
        self.assertNotIn('TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE',source)
        self.assertNotIn('TF_IPPMF_FORPROCESS',source);self.assertNotIn('TF_IPPMF_FORSESSION',source)
if __name__=='__main__':unittest.main()
