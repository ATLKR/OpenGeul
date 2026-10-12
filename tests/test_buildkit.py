import json
import hashlib
import zipfile
from unittest.mock import patch
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
        data = {'productName':'HOP', 'identifier':'net.golbin.hop','version':'0.4.5',
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
        self.assertEqual([x.get('Language') for x in doc.findall('p:Resources/p:Resource',ns)],['ko-kr'])
        self.assertIn('runFullTrust', xml);self.assertNotIn('runFullTrustAdmin',xml)

    def test_store_identity_rejects_placeholders_and_control_chars(self):
        for data in ({'name':'','publisher':'CN=x','displayName':'x'},
                     {'name':'REPLACE-ME','publisher':'CN=x','displayName':'x'},
                     {'name':'Example.App','publisher':'','displayName':'x'},
                     {'name':'Example.App','publisher':'CN=x\n','displayName':'x'}):
            with self.subTest(data=data), self.assertRaises(ValueError): self.b.validate_identity(data, store=True)
        with self.assertRaises(ValueError): self.b.validate_identity(self.b.DEV_IDENTITY, store=True)

    def test_manifest_supplies_the_bundled_cli_desktop_runtime(self):
        doc=ET.fromstring(self.b.manifest(self.b.DEV_IDENTITY,'1.2.3'))
        ns={'p':'http://schemas.microsoft.com/appx/manifest/foundation/windows10'}
        deps=doc.findall('p:Dependencies/p:PackageDependency',ns)
        self.assertEqual([dep.attrib for dep in deps],[{
            'Name':'Microsoft.VCLibs.140.00.UWPDesktop','MinVersion':'14.0.30704.0',
            'Publisher':'CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US'}])

    def test_both_architectures_register_the_owned_out_of_process_document_worker(self):
        namespaces = {'p': 'http://schemas.microsoft.com/appx/manifest/foundation/windows10',
                      'com': 'http://schemas.microsoft.com/appx/manifest/com/windows10',
                      'u': 'http://schemas.microsoft.com/appx/manifest/uap/windows10'}
        for architecture in ('x64', 'arm64'):
            with self.subTest(architecture=architecture):
                doc = ET.fromstring(self.b.manifest(self.b.DEV_IDENTITY, '1.1.3', architecture))
                self.assertEqual(doc.find('p:Identity', namespaces).get('ProcessorArchitecture'), architecture)
                server = doc.find('.//com:Extension/com:ComServer/com:ExeServer', namespaces)
                self.assertIsNotNone(server, 'Packaged MCP needs the registered isolated worker')
                self.assertEqual(server.get('Executable'), 'Tools\\rhwp.exe')
                self.assertEqual(server.get('Arguments'),
                                 '--opengeul-com-worker --clsid c6c4d247-b4f0-563d-a649-4765796e3164')
                self.assertEqual(server.find('com:Class', namespaces).get('Id'),
                                 'c6c4d247-b4f0-563d-a649-4765796e3164')
                self.assertNotIn('LaunchAndActivationPermission', server.attrib)
                self.assertEqual(doc.find('.//u:VisualElements', namespaces).get('Description'), 'HWP/HWPX 문서 편집기')

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

class ManifestWriterIntegrationTests(unittest.TestCase):
    """Windows TextIO newline 규칙부터 기존 Source6 검증까지 실제 경로를 잇는다."""
    def fixture(self):
        from test_mcp_qa_download import McpQaDownloadTests
        value = McpQaDownloadTests('runTest'); value.setUp()
        self.addCleanup(value.doCleanups)
        return value

    def replace_manifest(self, package, content):
        from test_store_package import StorePackageTests
        (package/'AppxManifest.xml').write_bytes(content)
        path = package/'provenance.json'; provenance = json.loads(path.read_bytes())
        msix = package/provenance['package']
        for archive_path in (msix,next(package.glob('*portable.zip'))):
            with zipfile.ZipFile(archive_path) as archive:
                members = [(info,archive.read(info)) for info in archive.infolist()]
            with zipfile.ZipFile(archive_path,'w') as archive:
                for info,data in members:
                    archive.writestr(info,content if info.filename=='AppxManifest.xml' else data)
        provenance['sha256'] = hashlib.sha256(msix.read_bytes()).hexdigest()
        path.write_text(json.dumps(provenance)+'\n',encoding='utf-8')
        StorePackageTests().checksum_directory(package)

    def test_windows_manifest_writer_roundtrips_through_strict_source_context(self):
        import buildkit
        fixture = self.fixture()
        # Windows newline=None translates LF to CRLF. Explicit LF must override it.
        def windows_write_text(path,text,encoding=None,errors=None,newline=None):
            with path.open('w',encoding=encoding,errors=errors,
                           newline='\r\n' if newline is None else newline) as stream:
                return stream.write(text)
        for architecture in ('x64','arm64'):
            with self.subTest(architecture=architecture):
                package = fixture.package.with_name(architecture)
                target = package/'AppxManifest.xml'
                with patch.object(Path,'write_text',windows_write_text), patch.object(sys,'argv',
                        ['buildkit.py','manifest','--out',str(target),'--architecture',architecture]):
                    buildkit.main()
                content = target.read_bytes()
                self.replace_manifest(package,content)
                binding,_,observed = fixture.module().source_context(package,fixture.env)
                self.assertEqual(observed,architecture)
                self.assertEqual(binding,fixture.binding)
                self.assertEqual(content,buildkit.manifest(buildkit.DEV_IDENTITY,'1.1.3',architecture).encode())
                self.assertNotIn(b'\r\n',content)

    def test_strict_source_context_still_rejects_self_consistent_crlf_input(self):
        import buildkit
        fixture = self.fixture()
        for architecture in ('x64','arm64'):
            with self.subTest(architecture=architecture):
                package = fixture.package.with_name(architecture)
                content = buildkit.manifest(buildkit.DEV_IDENTITY,'1.1.3',architecture).encode().replace(b'\n',b'\r\n')
                self.replace_manifest(package,content)
                with self.assertRaisesRegex(ValueError,'manifest'):
                    fixture.module().source_context(package,fixture.env)

if __name__ == '__main__': unittest.main()
