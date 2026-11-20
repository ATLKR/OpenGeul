"""Lossless inventory receipts; synthetic contexts are not Windows IME evidence."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0,str(Path(__file__).parent))
import test_ime_semantic_context as semantic_fixtures


class InventoryEncodingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=semantic_fixtures.SemanticSetupTests()
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.api=self.fixture.api

    def test_current_pre_and_post_keep_exact_inventory_bytes_in_fixed_encoding(self):
        pre,record=self.fixture.run_phase()
        raw=(self.fixture.frame.suite/'suite-inventory.json').read_bytes()
        self.fixture.prefix(record,'writer')
        post,_=self.fixture.run_phase(phase='post',record=record)
        for context in (pre,post,post['preContext']):
            with self.subTest(phase=context['phase']):
                self.assertNotIn('inventoryJson',context.keys())
                evidence=context['inventoryEvidence']
                self.assertEqual(set(evidence),{'encoding','rawBytes','data'})
                self.assertEqual(evidence['encoding'],'zlib-base64-v1')
                decoded=zlib.decompress(base64.b64decode(evidence['data'],validate=True))
                self.assertEqual(decoded,raw)
                self.assertEqual(evidence['rawBytes'],len(raw))
                self.assertEqual(context['inventorySha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(record['imeSemanticContexts']),2)
        self.assertIs(record['imeSemanticContext'],post)

    def context(self):
        context,_=self.fixture.run_phase()
        self.assertIn('inventoryEvidence',context.keys())
        return context

    def replay(self,context,phase='pre'):
        return self.api.require_ime_semantic_context(context,module='writer',
            expected_native=self.fixture.native,setup_deadline=10.,now=self.fixture.now,
            phase=phase,expected_prefix=self.api.PREFIXES['writer'] if phase=='post' else None)

    def replace_raw(self,context,raw):
        context['inventoryEvidence']=dict(encoding='zlib-base64-v1',rawBytes=len(raw),
            data=base64.b64encode(zlib.compress(raw)).decode('ascii'))
        context['inventorySha256']=hashlib.sha256(raw).hexdigest()

    def test_raw_legacy_or_ambiguous_inventory_cannot_bypass_current_contract(self):
        original=self.context()
        raw=(self.fixture.frame.suite/'suite-inventory.json').read_text()
        for keep_encoded in (False,True):
            changed=copy.deepcopy(original);changed['inventoryJson']=raw
            if not keep_encoded:del changed['inventoryEvidence']
            with self.subTest(keep_encoded=keep_encoded),self.assertRaises(AssertionError):
                self.replay(changed)

    def test_encoding_fields_size_and_original_hash_are_exact(self):
        original=self.context()
        mutations=(lambda e:e.update(encoding='gzip-base64-v1'),
            lambda e:e.update(rawBytes=True),lambda e:e.update(rawBytes=0),
            lambda e:e.update(rawBytes=4*1024*1024+1),
            lambda e:e.update(rawBytes=e['rawBytes']-1),
            lambda e:e.update(data='A'*(6*1024*1024+1)),
            lambda e:e.update(data=123),lambda e:e.update(extra='unreviewed'))
        for mutate in mutations:
            changed=copy.deepcopy(original);mutate(changed['inventoryEvidence'])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):self.replay(changed)
        changed=copy.deepcopy(original);changed['inventorySha256']='0'*64
        with self.assertRaises(AssertionError):self.replay(changed)

    def test_malformed_noncanonical_and_nonascii_base64_are_rejected(self):
        original=self.context()
        data=original['inventoryEvidence']['data']
        for malformed in ('','!'+data,data+'\n','한글',data+'=',data[:-1]):
            changed=copy.deepcopy(original);changed['inventoryEvidence']['data']=malformed
            with self.subTest(malformed=malformed[:20]),self.assertRaises(AssertionError):
                self.replay(changed)

    def test_truncated_corrupt_concatenated_and_trailing_streams_are_rejected(self):
        original=self.context()
        packed=base64.b64decode(original['inventoryEvidence']['data'])
        for malformed in (packed[:-1],b'not zlib',packed+zlib.compress(b'{}'),packed+b'x'):
            changed=copy.deepcopy(original)
            changed['inventoryEvidence']['data']=base64.b64encode(malformed).decode('ascii')
            with self.subTest(bytes=len(malformed)),self.assertRaises(AssertionError):self.replay(changed)

    def test_decompression_overflow_is_rejected_without_trusting_declared_size(self):
        changed=self.context()
        self.replace_raw(changed,b'x'*(4*1024*1024+1))
        changed['inventoryEvidence']['rawBytes']=1
        with self.assertRaisesRegex(AssertionError,'decoded.*bound'):self.replay(changed)

    def test_decoded_inventory_must_be_utf8_json_object(self):
        original=self.context()
        for raw in (b'\xff',b'{',b'[]',b'null'):
            changed=copy.deepcopy(original);self.replace_raw(changed,raw)
            with self.subTest(raw=raw),self.assertRaises((AssertionError,ValueError)):self.replay(changed)

    def test_changed_decoded_inventory_cannot_replace_original_python_identity(self):
        changed=self.context()
        raw=(self.fixture.frame.suite/'suite-inventory.json').read_bytes()+b'\n'
        self.replace_raw(changed,raw)
        with self.assertRaises(AssertionError):self.replay(changed)

    def test_original_byte_hash_is_checked_before_utf8_or_json_parsing(self):
        changed=self.context();self.replace_raw(changed,b'\xff')
        changed['inventorySha256']='0'*64
        with self.assertRaisesRegex(AssertionError,'Original inventory hash changed'):self.replay(changed)

    def test_post_reads_current_inventory_and_rejects_a_changed_original_pin(self):
        pre,record=self.fixture.run_phase();self.fixture.prefix(record,'writer')
        path=self.fixture.frame.suite/'suite-inventory.json'
        raw=path.read_bytes()+b'\n';path.write_bytes(raw)
        self.fixture.frame.inventory_sha256=hashlib.sha256(raw).hexdigest()
        with self.assertRaises(AssertionError):self.fixture.run_phase(phase='post',record=record)
        post=record['imeSemanticContext']
        self.assertFalse(post['success'])
        self.assertEqual(post['inventorySha256'],hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(post['inventorySha256'],pre['inventorySha256'])
        self.assertEqual(zlib.decompress(base64.b64decode(post['inventoryEvidence']['data'])),raw)

    def test_lossless_encoding_does_not_bypass_existing_whole_context_bound(self):
        changed=self.context();changed['extraEvidence']='x'*(8*1024*1024)
        with self.assertRaisesRegex(AssertionError,'IME semantic evidence exceeds'):self.replay(changed)

    def test_post_history_identity_cleanup_deadline_and_prefix_remain_mandatory(self):
        pre,record=self.fixture.run_phase();self.fixture.prefix(record,'writer')
        post,_=self.fixture.run_phase(phase='post',record=record)
        self.assertIn('inventoryEvidence',post.keys())
        mutations=(lambda v:v['preContext'].update(finishedAt=v['startedAt']+.01),
            lambda v:v['preContext']['expectedNative'].update(childHwnd=999),
            lambda v:v['cleanup'].update(terminated=True),
            lambda v:v.update(readerDeadline=11.),
            lambda v:v['asciiEvidence']['asciiEditorInputs'][0].update(absoluteDeadline=11.),
            lambda v:v['observations'][0].update(bodyText='lost prefix'))
        for mutate in mutations:
            changed=copy.deepcopy(post);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):self.replay(changed,'post')

    def test_pure_replay_decodes_each_context_once_for_all_retained_samples(self):
        self.fixture.fixture('writer')
        rows=[self.fixture.row('writer','Baseline',ready=False),
            self.fixture.row('writer','Baseline',at=1.2)]
        context,_=self.fixture.run_phase(rows=rows)
        self.assertIn('inventoryEvidence',context.keys())
        with patch.object(self.api,'_inventory',wraps=self.api._inventory) as decode:
            self.replay(context)
        self.assertEqual(decode.call_count,1)

    def test_four_mib_original_inventory_stays_lossless_without_raising_context_bound(self):
        raw=b'{"padding":"'+b'x'*(4*1024*1024-len(b'{"padding":""}'))+b'"}'
        self.assertEqual(len(raw),4*1024*1024)
        evidence=self.api._encode_inventory(raw)
        context=dict(inventoryEvidence=evidence,inventorySha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.api._inventory(context),json.loads(raw))
        self.assertEqual(self.api.MAX_CONTEXT_BYTES,8*1024*1024)
        with self.assertRaises(AssertionError):self.api._encode_inventory(raw+b' ')


if __name__=='__main__':unittest.main()
