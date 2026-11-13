"""Reviewed npm metadata units; no scripts, runtime or source qualification."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import prepare_upstream
import collect_notices

OLD_SHA='ed88ee7fcf037e64667c18fe2421f9010c543b066cdd423c47ad20235426cba2'
NEW_SHA='9625a90ccd967d8ad49716b8ed00b8fb61b5c78bd8bb81c1d9d02220bf4fcd14'


class FrontendDependencyTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.source=Path(temporary.name)/'hop';self.source.mkdir()
        self.original_lock=(ROOT/'tests/fixtures/tauri-npm/pnpm-lock.original.yaml').read_bytes()
        self.assertEqual(hashlib.sha256(self.original_lock).hexdigest(),OLD_SHA)
        self.populate(self.source)

    def populate(self,source):
        for path,value in {
            'package.json':{'name':'hop','version':'0.5.3','packageManager':'pnpm@10.34.9'},
            'apps/desktop/package.json':{'name':'hop-desktop','version':'0.5.3','devDependencies':{'@tauri-apps/cli':'^2.0.0','synthetic-unrelated':'1.0.0'}},
            'apps/studio-host/package.json':{'name':'@golbin/hop-studio-host','dependencies':{'@tauri-apps/api':'^2.10.1','synthetic-unrelated':'1.0.0'}},
        }.items():
            target=source/path;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(value)+'\n')
        (source/'pnpm-lock.yaml').write_bytes(self.original_lock)

    def apply(self,source=None):
        function=getattr(prepare_upstream,'pin_frontend_dependencies',None)
        self.assertTrue(callable(function),'Apply the exact API/CLI graph before the first frozen install')
        return function(self.source if source is None else source)

    def snapshot(self):
        return {str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}

    def test_applies_only_the_reviewed_pair_and_lock(self):
        before=self.snapshot();self.apply()
        after=self.snapshot()
        for path,field,package in [('apps/desktop/package.json','devDependencies','@tauri-apps/cli'),
                                   ('apps/studio-host/package.json','dependencies','@tauri-apps/api')]:
            expected=json.loads(before[path]);expected[field][package]='2.12.4'
            self.assertEqual(json.loads(after[path]),expected)
        self.assertEqual(after['package.json'],before['package.json'])
        self.assertEqual(hashlib.sha256(after['pnpm-lock.yaml']).hexdigest(),NEW_SHA)
        self.assertEqual(after['pnpm-lock.yaml'],(ROOT/'overlay/frontend-pnpm-lock.txt').read_bytes())

    def test_fetch_only_applies_the_pair_without_product_patches_or_install(self):
        lock=json.loads((ROOT/'config/upstream.lock.json').read_bytes())
        target=self.source.parent/'fetch'
        def git(*args,cwd):
            if args[:2]==('git','init'):self.populate(target)
            if args[:3]==('git','rev-parse','HEAD'):
                return lock['rhwp' if cwd==target/'third_party/rhwp' else 'hop']['commit']
            return ''
        with mock.patch.object(sys,'argv',['prepare_upstream.py','--fetch-only','--directory',str(target)]), \
             mock.patch.object(prepare_upstream.os,'environ',{}), \
             mock.patch.object(prepare_upstream,'run',side_effect=git), \
             mock.patch.object(prepare_upstream,'checkout_rhwp'), \
             mock.patch.object(prepare_upstream,'port_windows_contract_test'), \
             mock.patch.object(prepare_upstream,'patch') as product_patch, \
             mock.patch.object(prepare_upstream,'print',create=True):
            prepare_upstream.main()
        product_patch.assert_not_called()
        self.assertEqual(hashlib.sha256((target/'pnpm-lock.yaml').read_bytes()).hexdigest(),NEW_SHA)
        self.assertEqual(json.loads((target/'apps/desktop/package.json').read_bytes())['devDependencies']['@tauri-apps/cli'],'2.12.4')
        self.assertEqual(json.loads((target/'apps/studio-host/package.json').read_bytes())['dependencies']['@tauri-apps/api'],'2.12.4')

    def test_notice_selector_requires_the_same_reviewed_graph(self):
        self.assertEqual(collect_notices.REVIEWED_NPM_LOCK_SHA256,NEW_SHA)

    def test_npm_api_and_locked_rust_tauri_share_the_supported_minor(self):
        from frontend_dependencies import NPM_TAURI_VERSION
        self.assertEqual(NPM_TAURI_VERSION,'2.12.4')
        self.assertEqual(NPM_TAURI_VERSION.split('.')[:2],prepare_upstream.TAURI_VERSION.split('.')[:2])

    def test_repeated_application_keeps_exact_bytes(self):
        self.apply();before=self.snapshot();self.apply();self.assertEqual(before,self.snapshot())

    def test_unknown_or_single_byte_changed_lock_is_rejected_before_writes(self):
        for data in (b'unknown synthetic graph\n',self.original_lock[:-1]+bytes([self.original_lock[-1]^1])):
            with self.subTest(size=len(data)):
                (self.source/'pnpm-lock.yaml').write_bytes(data);before=self.snapshot()
                with self.assertRaises(ValueError):self.apply()
                self.assertEqual(before,self.snapshot())

    def test_wrong_roles_versions_and_partial_application_are_rejected_before_writes(self):
        path=self.source/'apps/studio-host/package.json';original=path.read_bytes()
        for changed in ({'name':'foreign','dependencies':{'@tauri-apps/api':'^2.10.1'}},
                        {'name':'@golbin/hop-studio-host','dependencies':{'@tauri-apps/api':'2.12.4'}},
                        {'name':'@golbin/hop-studio-host','dependencies':{'@tauri-apps/api':'latest'}}):
            path.write_text(json.dumps(changed));before=self.snapshot()
            with self.subTest(role=changed['name']),self.assertRaises(ValueError):self.apply()
            self.assertEqual(before,self.snapshot())
        path.write_bytes(original)

    def test_changed_overlay_is_rejected_before_writes(self):
        module=__import__('frontend_dependencies')
        changed=self.source.parent/'changed-overlay.txt'
        raw=(ROOT/'overlay/frontend-pnpm-lock.txt').read_bytes();changed.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        before=self.snapshot()
        with mock.patch.object(module,'PREPARED_LOCK',changed),self.assertRaises(ValueError):self.apply()
        self.assertEqual(before,self.snapshot())

    def test_linked_or_hardlinked_input_is_rejected_before_writes(self):
        path=self.source/'pnpm-lock.yaml';raw=path.read_bytes();outside=self.source.parent/'outside.yaml';outside.write_bytes(raw)
        module=__import__('frontend_dependencies');original=Path.lstat
        def reparse(candidate,*args,**kwargs):
            info=original(candidate,*args,**kwargs)
            if candidate==path:
                return SimpleNamespace(st_mode=info.st_mode,st_file_attributes=0x400)
            return info
        before=self.snapshot()
        with mock.patch.object(module.Path,'lstat',reparse),self.assertRaises(ValueError):self.apply()
        self.assertEqual(before,self.snapshot())
        path.unlink();os.link(outside,path)
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(outside.read_bytes(),raw)

    def test_duplicate_keys_oversized_or_nonobject_manifest_fail_before_writes(self):
        path=self.source/'apps/desktop/package.json'
        for raw in (b'{"name":"hop-desktop","name":"hop-desktop"}',b'[]',b' '*131073):
            path.write_bytes(raw);before=self.snapshot()
            with self.subTest(size=len(raw)),self.assertRaises(ValueError):self.apply()
            self.assertEqual(before,self.snapshot())

    def test_unreviewed_installer_is_rejected_before_writes(self):
        path=self.source/'package.json'
        for manager in ('pnpm@10.33.0','pnpm@10.34.9-beta.1','pnpm@latest'):
            path.write_text(json.dumps({'name':'hop','packageManager':manager}));before=self.snapshot()
            with self.subTest(manager=manager),self.assertRaises(ValueError):self.apply()
            self.assertEqual(before,self.snapshot())

    def test_new_overlay_is_in_the_existing_helper_hash_boundary(self):
        tree=ast.parse((ROOT/'scripts/windows_components.py').read_bytes())
        helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='helpers')
        self.assertTrue(any(isinstance(n,ast.Constant) and n.value=='.txt' for n in ast.walk(helper)))
        self.assertEqual(hashlib.sha256((ROOT/'overlay/frontend-pnpm-lock.txt').read_bytes()).hexdigest(),NEW_SHA)


if __name__=='__main__':unittest.main()
