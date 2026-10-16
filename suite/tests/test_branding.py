import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE))
try:
    import runtime_branding as branding
except ImportError:
    branding = None

OOR = '{http://openoffice.org/2001/registry}'
BUILD_ID = 'a' * 40
SERVICES = {
    'writer': 'com.sun.star.text.TextDocument',
    'calc': 'com.sun.star.sheet.SpreadsheetDocument',
    'impress': 'com.sun.star.presentation.PresentationDocument',
    'draw': 'com.sun.star.drawing.DrawingDocument',
    'math': 'com.sun.star.formula.FormulaProperties',
    'base': 'com.sun.star.sdb.OfficeDatabaseDocument',
}


def tree_hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def make_runtime(root):
    (root / 'program/shell').mkdir(parents=True)
    (root / 'share/registry').mkdir(parents=True)
    (root / 'share/config/soffice.cfg/sfx/ui').mkdir(parents=True)
    (root / 'program/soffice.exe').write_bytes(b'UNMODIFIED PE IMAGE')
    (root / 'program/python.exe').write_bytes(b'UNMODIFIED PYTHON PE')
    (root / 'LICENSE').write_bytes(b'Original MPL-2.0 and third-party licenses\r\n')
    (root / 'NOTICE').write_bytes(b'LibreOffice contributors; do not rebrand this notice.\n')
    (root / 'program/bootstrap.ini').write_text(
        '[Bootstrap]\nProductKey=LibreOffice 26.8\nUserInstallation=$SYSUSERCONFIG/LibreOffice/4\n', encoding='utf-8')
    (root / 'program/version.ini').write_text(
        '[Version]\nbuildid=' + BUILD_ID + '\nUpdateURL=https://update.libreoffice.org/check.php\nVendor=The Document Foundation\n', encoding='utf-8')
    factories = ''.join('<node oor:name="' + service + '"><prop oor:name="ooSetupFactoryUIName">'
                        '<value>' + module.title() + '</value></prop><prop oor:name="ooSetupFactoryShortName">'
                        '<value>s' + module + '</value></prop></node>' for module, service in SERVICES.items())
    applications = ''
    for module in ('Writer', 'Calc', 'Impress', 'Draw', 'Formula', 'Base'):
        modes = ('<node oor:name="Default"><prop oor:name="CommandArg"><value>Default</value></prop>'
                 '<prop oor:name="HasNotebookbar"><value>false</value></prop></node>')
        if module in ('Writer', 'Calc', 'Impress', 'Draw'):
            # Pinned ToolbarMode.xcu: the Tabbed node's CommandArg is its UI filename.
            modes += ('<node oor:name="Tabbed"><prop oor:name="CommandArg">'
                      '<value>notebookbar.ui</value></prop><prop oor:name="HasNotebookbar">'
                      '<value>true</value></prop></node>')
        applications += ('<node oor:name="' + module + '"><prop oor:name="Active">'
                         '<value>Default</value></prop><node oor:name="Modes">' + modes + '</node></node>')
    (root / 'share/registry/main.xcd').write_text(
        '<?xml version="1.0"?><oor:data xmlns:oor="http://openoffice.org/2001/registry">'
        '<oor:component-data oor:package="org.openoffice" oor:name="Setup"><node oor:name="Product">'
        '<prop oor:name="ooName"><value>LibreOffice</value></prop></node><node oor:name="Office">'
        '<node oor:name="Factories">' + factories + '</node></node></oor:component-data>'
        '<oor:component-data oor:package="org.openoffice.Office.UI" oor:name="ToolbarMode">'
        '<node oor:name="Applications">' + applications + '</node>'
        '</oor:component-data></oor:data>', encoding='utf-8')
    (root / 'share/config/soffice.cfg/sfx/ui/startcenter.ui').write_text(
        '<interface><object class="GtkButton" id="writer_all"><property name="label" translatable="yes">'
        '_Writer Document</property></object><object class="GtkLabel" id="example"><property name="label" '
        'translatable="yes">%PRODUCTNAME Calc found an error.</property></object></interface>', encoding='utf-8')
    (root / 'program/intro.png').write_bytes(b'old splash')
    (root / 'program/intro-highres.png').write_bytes(b'old large splash')
    (root / 'program/shell/logo.svg').write_text('<svg>LibreOffice</svg>', encoding='utf-8')
    with ZipFile(root / 'share/config/images_colibre.zip', 'w') as archive:
        archive.writestr('res/odt_32_8.png', b'old document icon')
        archive.writestr('cmd/sc_bold.png', b'KEEP EXISTING COMMAND ART')


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(branding, 'The fresh-copy runtime branding implementation is missing')
        self.manifest = json.loads((SUITE / 'config/product.json').read_text(encoding='utf-8'))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'original'
        self.destination = self.root / 'Office'
        make_runtime(self.source)

    def test_manifest_routes_only_explicit_formats_and_preserves_filter_ids(self):
        self.assertEqual(self.manifest['schemaVersion'], 1)
        self.assertEqual(set(self.manifest['modules']), {'hwp', *SERVICES})
        seen = set()
        for module, entry in self.manifest['modules'].items():
            self.assertEqual(entry['displayName'], 'OpenGeul ' + ('HWP' if module == 'hwp' else module.title()))
            self.assertFalse(seen.intersection(entry['extensions']))
            seen.update(entry['extensions'])
            if module != 'hwp':
                self.assertEqual(set(entry['filters']), set(entry['extensions']))
                self.assertTrue(entry['factory'].startswith('private:factory/'))
        self.assertEqual(self.manifest['modules']['writer']['filters']['docx'], 'Office Open XML Text')
        self.assertNotIn('pdf', seen)

    def test_actual_registry_product_factory_and_tabbed_mode_are_changed(self):
        branding.brand_runtime(self.source, self.destination, self.manifest)
        tree = ET.parse(self.destination / 'share/registry/main.xcd')
        factories = {node.get(OOR + 'name'): next((prop.find('value').text for prop in node.findall('prop')
                     if prop.get(OOR + 'name') == 'ooSetupFactoryUIName'), None) for node in tree.iter('node')}
        for module, service in SERVICES.items():
            self.assertEqual(factories[service], self.manifest['modules'][module]['displayName'])
        names = [prop.find('value').text for prop in tree.iter('prop') if prop.get(OOR + 'name') == 'ooName']
        self.assertEqual(names, ['OpenGeul Office'])
        applications = next(n for n in tree.iter('node') if n.get(OOR + 'name') == 'Applications')
        modes = {n.get(OOR + 'name'): n.find('prop/value').text for n in applications.findall('node')}
        self.assertEqual(modes, dict.fromkeys(('Writer', 'Calc', 'Impress', 'Draw'), 'notebookbar.ui') |
                         {'Formula': 'Default', 'Base': 'Default'})
        # SfxNotebookBar::IsActive matches Active against CommandArg, not the node name.
        # bf6ef2662401c7d6dce671ab4deb26ee0af3a7c1/sfx2/source/notebookbar/SfxNotebookBar.cxx:269-287
        for application in applications.findall('node'):
            if application.get(OOR + 'name') not in ('Writer', 'Calc', 'Impress', 'Draw'):
                continue
            definitions = next(n for n in application.findall('node') if n.get(OOR + 'name') == 'Modes')
            active = modes[application.get(OOR + 'name')]
            matching = [n for n in definitions.findall('node') if
                        next(p.find('value').text for p in n.findall('prop')
                             if p.get(OOR + 'name') == 'CommandArg') == active]
            self.assertEqual([n.get(OOR + 'name') for n in matching], ['Tabbed'])
            self.assertEqual(next(p.find('value').text for p in matching[0].findall('prop')
                                  if p.get(OOR + 'name') == 'HasNotebookbar'), 'true')

    def test_registry_preserves_namespaces_used_in_type_attribute_values(self):
        path = self.source / 'share/registry/main.xcd'
        xml = path.read_text().replace('xmlns:oor=', 'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:oor=')
        xml = xml.replace('<prop oor:name="ooName">', '<prop oor:name="ooName" oor:type="xs:string">')
        path.write_text(xml)
        branding.brand_runtime(self.source, self.destination, self.manifest)
        namespaces = dict(value for event, value in ET.iterparse(
            self.destination / 'share/registry/main.xcd', events=('start-ns',)))
        self.assertEqual(namespaces.get('xs'), 'http://www.w3.org/2001/XMLSchema')

    def test_localized_display_labels_change_without_renaming_donation_or_internal_ids(self):
        path = self.source/'share/registry/res/registry_nl.xcd'
        path.parent.mkdir()
        xml = ('<oor:data xmlns:oor="http://openoffice.org/2001/registry">'
               '<oor:component-data oor:package="org.openoffice.Office.UI" oor:name="GenericCommands">'
               '<node oor:name="Commands"><node oor:name=".uno:Notebookbar">'
               '<prop oor:name="Label"><value>LibreOffice lint</value></prop>'
               '<prop oor:name="InternalName"><value>LibreOffice.Internal.Token</value></prop></node>'
               '<node oor:name=".uno:Donation"><prop oor:name="Label">'
               '<value>Aan LibreOffice doneren</value></prop></node></node></oor:component-data>'
               '<oor:component-data oor:package="org.openoffice.Office.UI" oor:name="WriterWindowState">'
               '<node oor:name="private:resource/toolbar/notebookbarshortcuts">'
               '<prop oor:name="UIName"><value>LibreOffice lint sneltoetsen</value></prop></node>'
               '</oor:component-data><oor:component-data oor:package="org.openoffice.Office.UI" '
               'oor:name="ToolbarMode"><node oor:name="TabbedCompact"><prop oor:name="Label">'
               '<value>LibreOffice lint compact</value></prop><prop oor:name="UIName">'
               '<value>Copyright LibreOffice contributors</value></prop></node>'
               '</oor:component-data></oor:data>')
        path.write_text(xml, encoding='utf-8')
        before_ids = [node.get(OOR+'name') for node in ET.fromstring(xml).iter()]
        branding.brand_runtime(self.source, self.destination, self.manifest)
        tree = ET.parse(self.destination/path.relative_to(self.source))
        self.assertEqual([node.get(OOR+'name') for node in tree.iter()], before_ids)
        text = [node.text for node in tree.iter('value')]
        for label in ('OpenGeul Office lint', 'OpenGeul Office lint sneltoetsen', 'OpenGeul Office lint compact'):
            self.assertIn(label, text)
        self.assertIn('Aan LibreOffice doneren', text)
        self.assertIn('LibreOffice.Internal.Token', text)
        self.assertIn('Copyright LibreOffice contributors', text)
        self.assertEqual(path.read_text(encoding='utf-8'), xml)

    def test_source_legal_and_binaries_are_unchanged_and_receipt_hashes_match(self):
        before = tree_hashes(self.source)
        receipt = branding.brand_runtime(self.source, self.destination, self.manifest)
        self.assertEqual(before, tree_hashes(self.source))
        self.assertEqual(receipt['source']['buildId'], BUILD_ID)
        self.assertEqual(receipt['source']['sourceUrl'], 'https://github.com/LibreOffice/core/tree/' + BUILD_ID)
        canonical = json.dumps(self.manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        self.assertEqual(receipt['manifestSha256'], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(receipt, json.loads((self.destination / 'opengeul-branding.json').read_text()))
        after = tree_hashes(self.destination)
        for path, record in receipt['modifiedFiles'].items():
            self.assertEqual(record['sha256'], after[path], path)
            self.assertEqual(record['beforeSha256'], before.get(path), path)
        for path, digest in receipt['preservedLegalFiles'].items():
            self.assertEqual(after[path], digest)
            self.assertEqual(before[path], digest)
        self.assertGreaterEqual(set(receipt['preservedLegalFiles']), {'LICENSE', 'NOTICE'})
        for path in ('program/soffice.exe', 'program/python.exe'):
            self.assertEqual(before[path], after[path])

    def test_profile_startcenter_splash_and_zip_icons_are_real_runtime_files(self):
        branding.brand_runtime(self.source, self.destination, self.manifest)
        bootstrap = (self.destination / 'program/bootstrap.ini').read_text()
        self.assertIn('ProductKey=OpenGeul Office', bootstrap)
        self.assertIn('UserInstallation=$SYSUSERCONFIG/OpenGeul/Office/4', bootstrap)
        version = (self.destination / 'program/version.ini').read_text()
        self.assertIn('UpdateURL=\n', version)
        self.assertIn('Vendor=ATLKR', version)
        ui = ET.parse(self.destination / 'share/config/soffice.cfg/sfx/ui/startcenter.ui')
        self.assertEqual(ui.find(".//object[@id='writer_all']/property").text, 'OpenGeul Writer')
        self.assertIn('OpenGeul Calc found an error.', ET.tostring(ui.getroot(), encoding='unicode'))
        self.assertTrue((self.destination / 'program/intro.png').read_bytes().startswith(b'\x89PNG'))
        self.assertIn('OpenGeul', (self.destination / 'program/shell/logo.svg').read_text())
        with ZipFile(self.destination / 'share/config/images_colibre.zip') as archive:
            self.assertEqual(archive.read('cmd/sc_bold.png'), b'KEEP EXISTING COMMAND ART')
            self.assertTrue(archive.read('res/odt_32_8.png').startswith(b'\x89PNG'))

    def test_existing_destination_and_nested_output_are_rejected(self):
        self.destination.mkdir()
        with self.assertRaises(FileExistsError):
            branding.brand_runtime(self.source, self.destination, self.manifest)
        self.assertEqual(list(self.destination.iterdir()), [])
        with self.assertRaises(ValueError):
            branding.brand_runtime(self.source, self.source / 'nested', self.manifest)
        self.assertFalse((self.source / 'nested').exists())

    def test_missing_legal_files_or_invalid_build_id_never_produce_output(self):
        for file, replacement in [('LICENSE', None), ('program/version.ini', '[Version]\nbuildid=unknown\n')]:
            with self.subTest(file=file):
                path = self.source / file
                original = path.read_bytes()
                if replacement is None:
                    path.unlink()
                else:
                    path.write_text(replacement)
                with self.assertRaises(ValueError):
                    branding.brand_runtime(self.source, self.destination, self.manifest)
                self.assertFalse(self.destination.exists())
                path.write_bytes(original)

    def test_windows_license_names_are_preserved_byte_for_byte(self):
        (self.source / 'LICENSE').rename(self.source / 'license.txt')
        (self.source / 'NOTICE').rename(self.source / 'NOTICE.txt')
        (self.source / 'LICENSE.html').write_bytes(b'<html>LibreOffice legal license text</html>')
        (self.source / 'CREDITS.fodt').write_bytes(b'<office:document>Original contributors</office:document>')
        original = tree_hashes(self.source)
        receipt = branding.brand_runtime(self.source, self.destination, self.manifest)
        for name in ('license.txt', 'NOTICE.txt', 'LICENSE.html', 'CREDITS.fodt'):
            self.assertEqual(receipt['preservedLegalFiles'][name], original[name])
            self.assertEqual((self.destination / name).read_bytes(), (self.source / name).read_bytes())

    def test_symlink_cannot_make_branding_write_through_to_original(self):
        target = self.source / 'program/bootstrap.ini'
        external = self.root / 'external.ini'
        external.write_bytes(target.read_bytes())
        target.unlink()
        try:
            target.symlink_to(external)
        except OSError:
            self.skipTest('symlink creation is unavailable')
        before = external.read_bytes()
        with self.assertRaises(ValueError):
            branding.brand_runtime(self.source, self.destination, self.manifest)
        self.assertEqual(external.read_bytes(), before)
        self.assertFalse(self.destination.exists())

    def test_unrecognized_registry_input_is_rejected_without_partial_destination(self):
        (self.source / 'share/registry/main.xcd').write_text('<not-a-runtime/>')
        with self.assertRaises(ValueError):
            branding.brand_runtime(self.source, self.destination, self.manifest)
        self.assertFalse(self.destination.exists())


@unittest.skipUnless(os.environ.get('OPENGEUL_TEST_RUNTIME'), 'set OPENGEUL_TEST_RUNTIME for actual runtime proof')
class RealRuntimeBrandingTests(unittest.TestCase):
    def test_branded_runtime_converts_without_changing_source(self):
        self.assertIsNotNone(branding)
        source = Path(os.environ['OPENGEUL_TEST_RUNTIME'])
        manifest = json.loads((SUITE / 'config/product.json').read_text())
        before = tree_hashes(source)
        with tempfile.TemporaryDirectory(prefix='opengeul-branding-real-') as directory:
            root = Path(directory)
            destination = root / 'Office'
            receipt = branding.brand_runtime(source, destination, manifest)
            self.assertEqual(before, tree_hashes(source))
            self.assertIn('main.xcd', ' '.join(receipt['modifiedFiles']))
            executable = destination / 'program/soffice'
            if not executable.exists():
                executable = destination / 'program/soffice.exe'
            input_file = root / '한글 문서.txt'
            input_file.write_text('OpenGeul Writer\n한글 문서 브랜딩 검증\n', encoding='utf-8')
            output = root / 'converted'
            output.mkdir()
            result = subprocess.run([str(executable), '-env:UserInstallation=' + (root / 'profile').as_uri(),
                                     '--headless', '--convert-to', 'odt:writer8', '--outdir', str(output),
                                     str(input_file)], capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            with ZipFile(output / (input_file.stem + '.odt')) as document:
                content = ET.fromstring(document.read('content.xml'))
                self.assertIn('OpenGeul Writer', ''.join(content.itertext()))
                metadata = ET.fromstring(document.read('meta.xml'))
                generator = metadata.find('.//{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}generator')
                self.assertIsNotNone(generator)
                self.assertIn('OpenGeul', generator.text)
            self.assertEqual(before, tree_hashes(source))


if __name__ == '__main__':
    unittest.main()
