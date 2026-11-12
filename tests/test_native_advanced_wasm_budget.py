"""Role-bounded WASM input sizes; synthetic bytes, no product execution."""
from pathlib import Path
import copy
import hashlib
import io
import json
import sys
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'e2e'),str(ROOT/'tests')]
import test_native_advanced_inputs as boundaries
import test_store_package

MIB=1024*1024
BROWSER_WASM='hop/apps/studio-host/dist/assets/rhwp_bg-abcdef12.wasm'


class NativeAdvancedWasmBudgetTests(unittest.TestCase):
    def setUp(self):
        self.owner=boundaries.NativeAdvancedInputTests('runTest')
        self.owner.setUp();self.addCleanup(self.owner.doCleanups)

    @staticmethod
    def wasm_bytes(size):return b'\0asm\1\0\0\0'+b'x'*(size-8)

    def install_large_wasm(self,size=21*MIB):
        o=self.owner;raw=self.wasm_bytes(size)
        o.wasm_files['rhwp_bg.wasm']=raw
        o.wasm_proof['artifacts']['rhwp_bg.wasm']=hashlib.sha256(raw).hexdigest()
        o.wasm_files['OPEN_GEUL_WASM.json']=(json.dumps(o.wasm_proof,indent=2)+'\n').encode()
        for name,value in o.wasm_files.items():(o.wasm/name).write_bytes(value)
        provenance_path=o.package/'provenance.json'
        provenance=json.loads(provenance_path.read_bytes())
        provenance['sourceParity']['wasmRebuild']=copy.deepcopy(o.wasm_proof)
        provenance_path.write_text(json.dumps(provenance)+'\n')
        test_store_package.StorePackageTests().checksum_directory(o.package)
        advanced=json.loads(o.advanced['provenance.json'])
        advanced['vendorWasmSha256']=o.wasm_proof['artifacts']['rhwp_bg.wasm']
        o.advanced['provenance.json']=(json.dumps(advanced)+'\n').encode()
        o.browser['e2e-fixtures/advanced-owned/provenance.json']=o.advanced['provenance.json']
        o.browser[BROWSER_WASM]=raw
        o.archives={67:o.zip(o.browser),68:o.zip(o.wasm_files)};o.refresh()
        return raw

    def test_large_source_bound_wasm_stages_without_changing_native_baseline(self):
        o=self.owner;raw=self.install_large_wasm()
        try:proof=o.stage()
        except ValueError:self.fail('The source-bound large WASM was rejected before staging')
        after=o.inventory(o.fixture_root)
        self.assertEqual({name:after[name]for name in o.baseline},o.baseline)
        self.assertEqual(len(after),29)
        self.assertEqual(hashlib.sha256((o.wasm/'rhwp_bg.wasm').read_bytes()).hexdigest(),hashlib.sha256(raw).hexdigest())
        self.assertFalse(proof['productExecuted']);self.assertFalse(proof['sourceQualified'])

    def test_original_zip_accepts_only_the_large_original_wasm_role(self):
        o=self.owner;files={**o.wasm_files,'rhwp_bg.wasm':self.wasm_bytes(16*MIB+1)}
        try:admitted=o.module().zip_members(o.zip(files),browser=False)
        except ValueError:self.fail('The exact original large WASM role was rejected')
        with admitted as archive:
            self.assertEqual(archive.getinfo('rhwp_bg.wasm').file_size,16*MIB+1)

    def test_browser_zip_accepts_the_existing_exact_hashed_wasm_role(self):
        o=self.owner;files={**o.browser,BROWSER_WASM:self.wasm_bytes(16*MIB+1)}
        try:admitted=o.module().zip_members(o.zip(files),browser=True)
        except ValueError:self.fail('The exact hashed browser WASM role was rejected')
        with admitted as archive:
            self.assertEqual(archive.getinfo(BROWSER_WASM).file_size,16*MIB+1)

    def test_local_nonwasm_file_still_has_its_original_sixteen_mib_cap(self):
        o=self.owner;(o.wasm/'rhwp.js').write_bytes(b'x'*(16*MIB+1))
        with self.assertRaisesRegex(ValueError,'Input must be a bounded regular file'):
            o.stage()
        self.assertEqual(o.backend.calls,[])
        self.assertEqual(o.inventory(o.fixture_root),o.baseline)
        self.assertFalse(o.receipt.exists())

    def test_local_wasm_cannot_exceed_the_thirty_two_mib_role_cap(self):
        o=self.owner;(o.wasm/'rhwp_bg.wasm').write_bytes(self.wasm_bytes(32*MIB+1))
        with self.assertRaisesRegex(ValueError,'Input must be a bounded regular file'):
            o.stage()
        self.assertEqual(o.backend.calls,[])
        self.assertEqual(o.inventory(o.fixture_root),o.baseline)
        self.assertFalse(o.receipt.exists())

    def test_zip_nonwasm_files_still_have_their_original_sixteen_mib_cap(self):
        o=self.owner
        for browser,name in ((False,'rhwp.js'),(True,'hop/apps/studio-host/dist/assets/index-abcdef12.js')):
            with self.subTest(browser=browser):
                files={**(o.browser if browser else o.wasm_files),name:b'x'*(16*MIB+1)}
                with self.assertRaisesRegex(ValueError,'Unsafe, duplicate or oversized ZIP member'):
                    o.module().zip_members(o.zip(files),browser=browser)

    def test_large_browser_wasm_lookalikes_do_not_gain_a_role(self):
        o=self.owner
        for wrong in ('hop/apps/studio-host/dist/assets/rhwp_bg-abcdef123.wasm',
                'hop/apps/studio-host/dist/assets/rhwp_bg-abcdef12.wasm.extra',
                'foreign/assets/rhwp_bg-abcdef12.wasm'):
            with self.subTest(role=wrong):
                files={name:value for name,value in o.browser.items()if name!=BROWSER_WASM}
                files[wrong]=self.wasm_bytes(16*MIB+1)
                with self.assertRaisesRegex(ValueError,'Unsafe, duplicate or oversized ZIP member'):
                    o.module().zip_members(o.zip(files),browser=True)

    def test_wasm_role_cannot_exceed_the_original_thirty_two_mib_aggregate(self):
        o=self.owner
        for browser in (False,True):
            with self.subTest(browser=browser):
                files=dict(o.browser if browser else o.wasm_files)
                files[BROWSER_WASM if browser else 'rhwp_bg.wasm']=self.wasm_bytes(32*MIB+1)
                with self.assertRaisesRegex(ValueError,'Unexpected ZIP inventory or expansion size'):
                    o.module().zip_members(o.zip(files),browser=browser)

    def test_two_individually_allowed_roles_cannot_exceed_the_aggregate(self):
        o=self.owner
        for browser in (False,True):
            with self.subTest(browser=browser):
                files=dict(o.browser if browser else o.wasm_files)
                files[BROWSER_WASM if browser else 'rhwp_bg.wasm']=self.wasm_bytes(20*MIB)
                files['hop/apps/studio-host/dist/assets/index-abcdef12.js'if browser else 'rhwp.js']=b'x'*(13*MIB)
                with self.assertRaisesRegex(ValueError,'Unexpected ZIP inventory or expansion size'):
                    o.module().zip_members(o.zip(files),browser=browser)

    def test_compressed_transport_still_rejects_more_than_sixteen_mib(self):
        o=self.owner;files={**o.browser,BROWSER_WASM:self.wasm_bytes(16*MIB+1)}
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED)as archive:
            for name,value in files.items():archive.writestr(name,value)
        o.archives[67]=output.getvalue();o.refresh()
        with self.assertRaises(ValueError)as caught:o.stage()
        self.assertEqual(caught.exception._native_input_stage,'browser-archive')
        self.assertFalse(any(isinstance(call,tuple)and call[0]=='zip'for call in o.backend.calls))
        self.assertEqual(o.inventory(o.fixture_root),o.baseline)

    def test_large_local_wasm_still_requires_its_exact_manifest_hash(self):
        o=self.owner;raw=self.install_large_wasm()
        (o.wasm/'rhwp_bg.wasm').write_bytes(raw[:-1]+b'y')
        with self.assertRaisesRegex(ValueError,'Local six WASM payload hashes differ'):o.stage()
        self.assertEqual(o.backend.calls,[])
        self.assertEqual(o.inventory(o.fixture_root),o.baseline)

    def test_large_wasm_cannot_bypass_the_original_source_run_binding(self):
        o=self.owner;self.install_large_wasm();o.run['head_sha']='b'*40;o.refresh()
        with self.assertRaises(ValueError)as caught:o.stage()
        self.assertEqual(caught.exception._native_input_stage,'source-run')
        self.assertEqual(o.inventory(o.fixture_root),o.baseline)
        self.assertFalse(o.receipt.exists())

    def test_advanced_document_payloads_still_have_their_128_kib_cap(self):
        o=self.owner;files={**o.browser,'e2e-fixtures/advanced-owned/owned-blank.hwpx':b'x'*(128*1024+1)}
        with zipfile.ZipFile(io.BytesIO(o.zip(files)))as archive:
            with self.assertRaisesRegex(ValueError,'Owned advanced input size exceeds its bound'):
                o.module().advanced_payload(archive,o.wasm_proof,{})

    def test_large_allowed_wasm_still_requires_the_original_zip_crc(self):
        o=self.owner;files={**o.wasm_files,'rhwp_bg.wasm':self.wasm_bytes(16*MIB+1)}
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED)as archive:
            for name,value in files.items():archive.writestr(name,value)
        raw=bytearray(output.getvalue())
        with zipfile.ZipFile(io.BytesIO(raw))as archive:
            entry=archive.getinfo('rhwp_bg.wasm')
            offset=entry.header_offset+30+len(entry.filename.encode())+len(entry.extra)+8
        raw[offset]^=1
        with self.assertRaisesRegex(ValueError,'Original ZIP CRC differs'):
            o.module().zip_members(bytes(raw),browser=False)


if __name__=='__main__':unittest.main()
