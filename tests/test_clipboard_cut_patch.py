"""Patch ownership, exact-source refusal and build-order contracts for delayed cut."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

def blob(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

class ClipboardCutPatchTests(unittest.TestCase):
    def setUp(self):
        path=ROOT/'scripts/patch_clipboard_cut.py'
        self.assertTrue(path.is_file(),'Missing source-bound clipboard cut patcher')
        spec=importlib.util.spec_from_file_location('cut_patch',path)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)

    def test_source_and_upstream_test_contract_are_pinned(self):
        self.assertEqual(self.m.SOURCE_BLOB,'b53a3a3797734ce9318f4319951807a8c24d90b6')
        self.assertEqual(self.m.TEST_BLOB,'828012ed28a8b8988fc18138a012002a2c7ffddd')

    def sample(self):return '\n'.join(old for old,new in self.m.REPLACEMENTS)

    def test_every_anchor_is_unique_and_destructive_guard_keeps_all_checks(self):
        original=self.sample();updated=self.m.transform(original)
        for old,new in self.m.REPLACEMENTS:self.assertIn(new,updated)
        self.assertIn('copiedSelection.selection === serializeSelection(currentSelection)',updated)
        self.assertIn('services.getInputHandler() === inputHandler',updated)
        self.assertIn('services.wasm.hasLoadedDocument()',updated)

    def test_missing_duplicate_or_modified_anchor_fails(self):
        original=self.sample()
        for old,new in self.m.REPLACEMENTS:
            for text in (original.replace(old,''),original+'\n'+old):
                with self.assertRaises(ValueError):self.m.transform(text)

    def test_upstream_test_double_changes_without_weakening_expectations(self):
        text="// before\n"+self.m.TEST_ANCHOR+"\nexpect(inputHandler.performDelete).toHaveBeenCalledOnce();\n"
        result=self.m.transform_test(text)
        self.assertIn('documentGeneration: 1',result)
        self.assertIn('hasLoadedDocument: () => true',result)
        self.assertTrue(result.endswith('expect(inputHandler.performDelete).toHaveBeenCalledOnce();\n'))

    def fixture(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);folder=root/'apps/studio-host/src/command/commands';folder.mkdir(parents=True)
        source=folder/'edit.ts';source.write_text(self.sample(),encoding='utf-8')
        test=folder/'edit.test.ts';test.write_text(self.m.TEST_ANCHOR,encoding='utf-8')
        ledger=root/'.opengeul-overlay.json';ledger.write_text('{"existing":"preserved"}')
        return root,source,test,ledger

    def test_success_preserves_ledger_and_records_both_file_hashes(self):
        root,source,test,ledger=self.fixture();before=source.read_bytes();test_before=test.read_bytes()
        with patch.object(self.m,'SOURCE_BLOB',blob(before)),patch.object(self.m,'TEST_BLOB',blob(test_before)):
            self.m.apply(root)
        data=json.loads(ledger.read_text());self.assertEqual(data['existing'],'preserved')
        record=data['clipboardCutGuard'];self.assertEqual(record['beforeSha256'],hashlib.sha256(before).hexdigest())
        self.assertEqual(record['afterSha256'],hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(record['testAfterSha256'],hashlib.sha256(test.read_bytes()).hexdigest())

    def test_drift_of_either_source_fails_before_any_mutation(self):
        root,source,test,ledger=self.fixture();before=[p.read_bytes() for p in (source,test,ledger)]
        for source_sha,test_sha in ((blob(before[0]),'0'*40),('0'*40,blob(before[1]))):
            with patch.object(self.m,'SOURCE_BLOB',source_sha),patch.object(self.m,'TEST_BLOB',test_sha):
                with self.assertRaises(ValueError):self.m.apply(root)
            self.assertEqual([p.read_bytes() for p in (source,test,ledger)],before)

    def test_invalid_or_owned_ledger_rejected_before_source_changes(self):
        root,source,test,ledger=self.fixture();before=source.read_bytes()
        for data in ('[]','{"clipboardCutGuard":{}}'):
            ledger.write_text(data)
            with self.assertRaises(ValueError):self.m.apply(root)
            self.assertEqual(source.read_bytes(),before)

    def test_symlinked_input_is_rejected(self):
        root,source,test,ledger=self.fixture();original=source.read_bytes()
        outside=root/'outside';source.rename(outside);source.symlink_to(outside)
        with self.assertRaises(ValueError):self.m.apply(root)
        self.assertEqual(outside.read_bytes(),original)

    def test_both_build_paths_patch_before_source_tests_and_application_build(self):
        for file,arg in (('build-wasm.sh','.work/hop'),('build-msix.ps1','$source')):
            text=(ROOT/'scripts'/file).read_text()
            hook='python scripts/patch_clipboard_cut.py '+arg
            self.assertEqual(text.count(hook),1)
            self.assertLess(text.index('python scripts/prepare_hop_fixes.py'),text.index(hook))
            self.assertLess(text.index(hook),text.index('--test tests/hop/*.test.mjs'))
            self.assertLess(text.index(hook),text.rindex('pnpm run build:studio'))

if __name__=='__main__':unittest.main()
