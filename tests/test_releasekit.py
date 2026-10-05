import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

class ReleaseKitTests(unittest.TestCase):
    def api(self):
        path=Path(__file__).resolve().parents[1]/'scripts/releasekit.py'
        self.assertTrue(path.is_file(), 'Release policy and archive verification are not implemented')
        import releasekit
        return releasekit

    def test_release_policy_never_allows_pull_requests_or_other_repositories(self):
        k=self.api()
        self.assertFalse(k.release_allowed('ATLKR/OpenGeul','pull_request','refs/pull/2/merge'))
        self.assertFalse(k.release_allowed('other/OpenGeul','push','refs/heads/main'))
        self.assertFalse(k.release_allowed('ATLKR/OpenGeul','push','refs/heads/feature'))
        self.assertFalse(k.release_allowed('ATLKR/OpenGeul','pull_request_target','refs/heads/main'))
        self.assertTrue(k.release_allowed('ATLKR/OpenGeul','push','refs/heads/main'))
        self.assertTrue(k.release_allowed('ATLKR/OpenGeul','workflow_dispatch','refs/heads/main'))
        self.assertTrue(k.release_allowed('ATLKR/OpenGeul','push','refs/tags/v1.0.0'))
        self.assertFalse(k.release_allowed('ATLKR/OpenGeul','push','refs/tags/v1.0.0;echo pwn'))

    def test_release_tags_are_immutable_and_version_checked(self):
        k=self.api()
        self.assertEqual(k.release_tag('1.0.0','refs/heads/main','12','2'),'v1.0.0-dev.12.2')
        self.assertEqual(k.release_tag('1.0.0','refs/tags/v1.0.0','12','2'),'v1.0.0')
        for args in [('1.0.0','refs/tags/v9.0.0','1','1'),('1.0.0','refs/heads/main','xx','1')]:
            with self.assertRaises(ValueError): k.release_tag(*args)

    def test_packaged_msix_has_actual_pe_x64_editor_and_cli(self):
        k=self.api()
        from buildkit import manifest,DEV_IDENTITY
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'app.msix'
            pe=bytearray(256);pe[:2]=b'MZ';pe[60:64]=(128).to_bytes(4,'little');pe[128:132]=b'PE\x00\x00';pe[132:134]=(0x8664).to_bytes(2,'little')
            files={'AppxManifest.xml':manifest(DEV_IDENTITY,'1.0.0'),'OpenGeul.exe':bytes(pe),'Tools/rhwp.exe':bytes(pe),'[Content_Types].xml':'<Types/>','AppxBlockMap.xml':'<BlockMap/>','Notices/OpenGeul-LICENSE.txt':'MIT','Assets/StoreLogo.png':b'PNG'}
            with zipfile.ZipFile(p,'w') as z:
                for name,data in files.items(): z.writestr(name,data)
            result=k.verify_msix(p)
            self.assertTrue(result['unsigned']);self.assertEqual(result['architecture'],'x64')
            with zipfile.ZipFile(p,'a') as z:z.writestr('Fonts/hidden.dat',b'wOF2bad')
            with self.assertRaises(ValueError):k.verify_msix(p)

    def test_msix_rejects_traversal_and_wrong_architecture(self):
        k=self.api()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.msix'
            with zipfile.ZipFile(p,'w') as z:z.writestr('../escape','oops')
            with self.assertRaises(ValueError):k.verify_msix(p)
        with self.assertRaises(ValueError):k.pe_machine(b'MZnot really a binary')

    def test_payload_allows_only_reviewed_cli_path(self):
        self.api()
        from buildkit import audit_payload
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'Tools').mkdir();(root/'Tools/rhwp.exe').write_bytes(b'MZ')
            audit_payload(root)
            (root/'Tools/secret.pfx').write_text('private')
            with self.assertRaises(ValueError):audit_payload(root)

    def test_canonical_owner_and_windows_byte_stability(self):
        self.api()
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(json.loads((root/'config/product.json').read_text(encoding='utf-8'))['repository'],'ATLKR/OpenGeul')
        prep=(root/'scripts/prepare_upstream.py').read_text(encoding='utf-8')
        self.assertIn('core.autocrlf=false',prep)
        self.assertIn('--depth=1',prep)
        self.assertIn('test:studio',(root/'scripts/build-msix.ps1').read_text(encoding='utf-8'))
        self.assertNotIn('intentionally\n    # NOT represented as passing',(root/'scripts/build-msix.ps1').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
