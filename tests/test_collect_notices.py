import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import collect_notices as notices


class RuntimeNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
        self.out=self.root/'notices'
        self.packages=[{'name':name,'version':'0.153.3','license':'MIT',
                        'manifest_path':str(self.source/'Cargo.toml')} for name in ('skia-safe','skia-bindings')]

    def test_exact_license_is_packaged_for_both_shipped_crates_with_provenance(self):
        inventory=notices.collect_cargo(self.packages,self.out)
        for item in inventory:
            provenance=item['runtimeNotice']
            text=self.out/f"cargo-{item['name']}-{item['version']}"/provenance['file']
            self.assertEqual(hashlib.sha256(text.read_bytes()).hexdigest(),notices.RUST_SKIA_SHA256)
            self.assertIn(b'LongYinan & Armin Sander',text.read_bytes())
            self.assertIn(b'rust-skia Contributors',text.read_bytes())
            self.assertIn(notices.RUST_SKIA_COMMIT,provenance['sourceUrl'])
            self.assertIn(provenance['file'],item['texts'])

    def test_missing_corrupted_or_wrong_version_runtime_notice_fails(self):
        with patch.object(notices,'RUST_SKIA_NOTICE',self.root/'missing.txt'):
            with self.assertRaises(FileNotFoundError):notices.collect_cargo(self.packages,self.out)
        bad=self.root/'bad.txt';bad.write_text('MIT without copyright')
        with patch.object(notices,'RUST_SKIA_NOTICE',bad):
            with self.assertRaisesRegex(ValueError,'license text'):notices.collect_cargo(self.packages,self.out)
        self.packages[0]['version']='0.100.0'
        with self.assertRaisesRegex(ValueError,'version/license'):notices.collect_cargo(self.packages,self.out)

    def test_missing_runtime_metadata_fails_but_dev_only_missing_texts_do_not(self):
        with self.assertRaisesRegex(ValueError,'required shipped'):notices.collect_cargo(self.packages[:1],self.out)
        dev={'name':'dev-only','version':'1.0.0','license':'MIT','manifest_path':str(self.source/'Cargo.toml')}
        inventory=notices.collect_cargo([*self.packages,dev],self.out)
        self.assertEqual(inventory[-1]['texts'],[])


if __name__=='__main__':unittest.main()
