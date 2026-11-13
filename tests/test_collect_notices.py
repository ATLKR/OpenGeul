import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import collect_notices as notices
import buildkit


class RuntimeNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
        self.out=self.root/'notices'
        self.packages=[{'name':name,'version':'0.156.0','license':'MIT',
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


class SupplementalNoticeTests(unittest.TestCase):
    def setUp(self):
        RuntimeNoticeTests.setUp(self)

    def fixture(self):
        package=self.source/'pdf-backend';package.mkdir()
        raw={'src/fonts/assets/LICENSE-DejaVu':b'owned font copyright and terms\n',
             'TRADEMARKS.md':b'owned package naming policy\n'}
        for name,data in raw.items():
            path=package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        pins={'pdf-backend':{'version':'1.0.0','license':'MIT OR Apache-2.0',
                            'directory':'vendor/pdf-backend',
                            'files':{name:hashlib.sha256(data).hexdigest() for name,data in raw.items()}}}
        item={'name':'pdf-backend','version':'1.0.0','license':'MIT OR Apache-2.0',
              'manifest_path':str(package/'Cargo.toml')}
        self.enterContext(patch.object(notices,'SUPPLEMENTAL_NOTICES',pins,create=True))
        return package,raw,item

    def test_nested_notice_bytes_and_origin_are_in_the_review_inventory(self):
        _,raw,item=self.fixture()
        payload=self.root/'payload';self.out=payload/'Notices'
        record=notices.collect_cargo([*self.packages,item],self.out)[-1]
        supplements=record.get('supplementalNotices',[])
        self.assertEqual(len(supplements),len(raw))
        for supplement in supplements:
            name=supplement['sourcePath']
            path=self.out/'cargo-pdf-backend-1.0.0'/supplement['file']
            self.assertEqual(path.read_bytes(),raw[name])
            self.assertEqual(supplement['sha256'],hashlib.sha256(raw[name]).hexdigest())
            self.assertIn('vendor/pdf-backend/'+name,supplement['sourceUrl'])
            self.assertIn(supplement['file'],record['texts'])
        self.assertNotIn('runtimeNotice',record)
        buildkit.audit_payload(payload)

    def test_missing_or_changed_supplemental_notice_fails_before_supplement_writes(self):
        package,raw,item=self.fixture()
        for name,data in raw.items():
            for changed in (None,data+b'changed'):
                with self.subTest(name=name,missing=changed is None):
                    path=package/name
                    if changed is None:path.unlink()
                    else:path.write_bytes(changed)
                    with self.assertRaises((FileNotFoundError,ValueError)):
                        notices.collect_cargo([*self.packages,item],self.out)
                    self.assertFalse((self.out/'cargo-pdf-backend-1.0.0'/'supplemental').exists())
                    path.write_bytes(data)

    def test_supplemental_package_version_license_and_symlink_must_match(self):
        package,raw,item=self.fixture()
        for field,value in (('version','2.0.0'),('license','MIT')):
            with self.subTest(field=field),self.assertRaises(ValueError):
                notices.collect_cargo([*self.packages,{**item,field:value}],self.out)
        path=package/next(iter(raw));data=path.read_bytes();path.unlink()
        target=self.source/'unlinked-license';target.write_bytes(data);path.symlink_to(target)
        with self.assertRaises(ValueError):
            notices.collect_cargo([*self.packages,item],self.out)


if __name__=='__main__':unittest.main()
