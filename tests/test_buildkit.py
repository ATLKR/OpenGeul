import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

class BuildKitTests(unittest.TestCase):
    def setUp(self):
        import buildkit
        self.b = buildkit

    def test_version(self):
        self.assertEqual(self.b.package_version('1.2.3'), '1.2.3.0')
        for value in ('0.2.3', '1.2', '1.2.65536', '1.2.3.4', '1.2.3-beta', '01.2.3', '1.2.3\n'):
            with self.subTest(value=value), self.assertRaises(ValueError): self.b.package_version(value)

    def test_replace_requires_exactly_one_anchor(self):
        self.assertEqual(self.b.replace_once('abc def', 'def', 'ghi'), 'abc ghi')
        for value in ('abc', 'abc abc'):
            with self.assertRaises(ValueError): self.b.replace_once(value, 'abc', 'X', expected=2 if value == 'abc' else 1)

    def test_tauri_brand_and_no_resources_or_updater(self):
        data = {'productName':'HOP', 'identifier':'net.golbin.hop','version':'0.4.4',
          'app': {'windows':[{'label':'main','title':'HOP'}]},
          'plugins': {'updater': {'endpoints':['https://github.com/golbin/hop']}},
          'bundle': {'resources':{'font.ttf':'font.ttf'}, 'publisher':'golbin.net',
                     'fileAssociations':[{'ext':['hwp']}], 'windows':{'wix':{}}, 'macOS': {}}}
        out=self.b.tauri_config(data, '1.0.0')
        self.assertEqual(out['productName'],'OpenGeul')
        self.assertEqual(out['identifier'],'org.allenlabs.opengeul')
        self.assertNotIn('updater',out['plugins'])
        self.assertEqual(out['bundle']['resources'],{})
        self.assertEqual(out['app']['windows'][0]['title'],'OpenGeul')
        self.assertEqual(data['productName'],'HOP')

    def test_manifest_escapes_identity_and_limits_file_types(self):
        identity={'name':'12345.Allen.OpenGeul','publisher':'CN=Example & Co','displayName':'Allen & Co'}
        xml=self.b.manifest(identity,'1.2.3');doc=ET.fromstring(xml)
        ns={'p':'http://schemas.microsoft.com/appx/manifest/foundation/windows10','u':'http://schemas.microsoft.com/appx/manifest/uap/windows10'}
        self.assertEqual(doc.find('p:Identity',ns).get('Publisher'),'CN=Example & Co')
        self.assertEqual(doc.find('p:Identity',ns).get('Version'),'1.2.3.0')
        self.assertEqual([x.text for x in doc.findall('.//u:FileType',ns)],['.hwp','.hwpx'])
        self.assertIn('runFullTrust', xml);self.assertNotIn('runFullTrustAdmin',xml)

    def test_store_identity_rejects_placeholders_and_control_chars(self):
        for data in ({'name':'','publisher':'CN=x','displayName':'x'},
                     {'name':'REPLACE-ME','publisher':'CN=x','displayName':'x'},
                     {'name':'Example.App','publisher':'','displayName':'x'},
                     {'name':'Example.App','publisher':'CN=x\n','displayName':'x'}):
            with self.subTest(data=data), self.assertRaises(ValueError): self.b.validate_identity(data, store=True)
        with self.assertRaises(ValueError): self.b.validate_identity(self.b.DEV_IDENTITY, store=True)

    def test_payload_rejects_fonts_case_insensitively(self):
        for name in ('font.ttf','font.OTF','font.ttc','font.otc','font.woff','font.WOFF2','server.pfx','secrets.pem'):
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp)/name).write_bytes(b'data')
                with self.subTest(name=name), self.assertRaises(ValueError): self.b.audit_payload(Path(tmp))

    def test_payload_allows_only_runtime_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'OpenGeul.exe').write_bytes(b'MZfake')
            (root/'Assets').mkdir(); (root/'Assets/StoreLogo.png').write_bytes(b'PNGfake')
            (root/'Notices').mkdir(); (root/'Notices/LICENSE.txt').write_text('MIT')
            self.b.audit_payload(root)
            (root/'private-notes.txt').write_text('not permitted')
            with self.assertRaises(ValueError): self.b.audit_payload(root)

    def test_payload_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'OpenGeul.exe').write_bytes(b'MZ')
            try: (root/'evil.dll').symlink_to(root/'OpenGeul.exe')
            except OSError: self.skipTest('symlinks unavailable')
            with self.assertRaises(ValueError): self.b.audit_payload(root)

    def test_lock_pinned_and_fonts_not_distributed(self):
        lock=json.loads((ROOT/'config/upstream.lock.json').read_text(encoding='utf-8'))
        self.assertRegex(lock['hop']['commit'],r'^[0-9a-f]{40}$')
        self.assertRegex(lock['rhwp']['commit'],r'^[0-9a-f]{40}$')
        for path in ROOT.rglob('*'):
            if set(path.relative_to(ROOT).parts) & {'.git','.work','node_modules','dist','upstream'}: continue
            if path.is_file(): self.assertNotIn(path.suffix.lower(),self.b.FONT_EXTENSIONS)

    def test_frontend_rejects_font_files_before_exe_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'index.html').write_text('<html></html>')
            self.b.audit_frontend(root)
            (root/'renamed.bin').write_bytes(b'wOF2not-a-real-font')
            with self.assertRaises(ValueError): self.b.audit_frontend(root)

    def test_font_policy_denies_ambiguous_embedding(self):
        for value in (0,8): self.assertTrue(self.b.permits_subset_embedding(value))
        for value in (None,2,4,6,12,0x100,0x108,0x200,0xffff):
            with self.subTest(value=value): self.assertFalse(self.b.permits_subset_embedding(value))

    def test_graphic_assets_have_png_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.b.make_assets(Path(tmp))
            self.assertEqual((Path(tmp)/'Square44x44Logo.png').read_bytes()[:8],b'\x89PNG\r\n\x1a\n')

    def test_help_links_are_allowlisted(self):
        data=json.loads((ROOT/'config/font-resources.json').read_text(encoding='utf-8'))
        self.assertEqual({x['id'] for x in data},{'noto-sans','noto-serif','windows-font-settings'})
        self.assertTrue(all(x['url'].startswith(('https://fonts.google.com/','ms-settings:fonts')) for x in data))

if __name__ == '__main__': unittest.main()
