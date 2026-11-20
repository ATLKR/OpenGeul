"""Exercise the startup locale preference against the pinned runtime's schema.

langselect.cxx prepareLocale() reads Linguistic/General/UILocale, resolves an
installed UI language, and only then writes Setup/L10N/ooLocale. Seeding the
latter alone leaves the native UI in the host's language.
"""
import gettext
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE))
import runtime_branding as branding
from test_branding import make_runtime, tree_hashes

OOR = '{http://openoffice.org/2001/registry}'
XML = '{http://www.w3.org/XML/1998/namespace}'


def components(runtime, kind, package, name):
    for path in sorted((runtime / 'share/registry').rglob('*.xcd')):
        for node in ET.parse(path).iter(OOR + kind):
            if (node.get(OOR + 'package'), node.get(OOR + 'name')) == (package, name):
                yield node


def named_path(node, names, tag='node'):
    for name in names:
        node = next((child for child in node.findall(tag)
                     if child.get(OOR + 'name') == name), None)
        if node is None:
            return None
    return node


def property_value(runtime, package, component, path, prop):
    # Resolve real schema defaults followed by the packaged data layer. Validate
    # the property against the schema so a typo cannot masquerade as a preference.
    schema, = components(runtime, 'component-schema', package, component)
    group = named_path(schema.find('component'), path, 'group')
    declaration = named_path(group, [prop], 'prop')
    if declaration is None or declaration.get(OOR + 'type') != 'xs:string':
        raise AssertionError('The preference is not declared by the pinned runtime schema')
    result = declaration.find('value').text or ''
    for data in components(runtime, 'component-data', package, component):
        group = named_path(data, path)
        value = named_path(group, [prop], 'prop') if group is not None else None
        if value is not None:
            result = value.find('value').text or ''
    return result


class KoreanRuntimeDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / 'upstream'
        self.output = Path(self.temporary.name) / 'Office'
        make_runtime(self.source)
        self.manifest = json.loads((SUITE / 'config/product.json').read_text(encoding='utf-8'))

    def test_packaged_startup_preference_selects_installed_korean_menu_resources_on_english_host(self):
        before = tree_hashes(self.source)
        branding.brand_runtime(self.source, self.output, self.manifest)
        preference = property_value(self.output, 'org.openoffice.Office', 'Linguistic',
                                    ['General'], 'UILocale')
        # An empty preference falls through to an English host in prepareLocale.
        chosen_ui = preference or 'en-US'
        installed = set()
        for data in components(self.output, 'component-data', 'org.openoffice', 'Setup'):
            locales = named_path(data, ['Office', 'InstalledLocales'])
            if locales is not None:
                installed.update(node.get(OOR + 'name') for node in locales.findall('node'))
        self.assertIn(chosen_ui, installed)
        labels = {}
        for data in components(self.output, 'component-data', 'org.openoffice.Office.UI', 'GenericCommands'):
            popups = named_path(data, ['UserInterface', 'Popups'])
            for command in popups.findall('node'):
                prop = named_path(command, ['Label'], 'prop')
                for value in prop.findall('value'):
                    if value.get(XML + 'lang') == chosen_ui:
                        labels[command.get(OOR + 'name')] = value.text
        self.assertEqual(labels, {'.uno:PickList': '파일(~F)', '.uno:EditMenu': '편집(~E)',
                                  '.uno:InsertMenu': '삽입(~I)'})
        self.assertEqual(property_value(self.output, 'org.openoffice', 'Setup',
                                        ['L10N'], 'ooSetupSystemLocale'), 'ko-KR')
        self.assertEqual(before, tree_hashes(self.source))

    def test_missing_installed_korean_language_is_rejected_without_partial_output(self):
        path = self.source / 'share/registry/localization.xcd'
        tree = ET.parse(path)
        for node in tree.iter('node'):
            if node.get(OOR + 'name') == 'InstalledLocales':
                for language in list(node):
                    if language.get(OOR + 'name') == 'ko':
                        node.remove(language)
        tree.write(path, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Korean.*installed'):
            branding.brand_runtime(self.source, self.output, self.manifest)
        self.assertFalse(self.output.exists())

    def test_locale_preset_is_a_shared_default_that_private_profiles_can_override(self):
        branding.brand_runtime(self.source, self.output, self.manifest)
        preset = self.output / 'share/registry/opengeul.xcd'
        self.assertTrue(preset.is_file(), 'The packaged registry layer must reach every private profile')
        root = ET.parse(preset).getroot()
        self.assertEqual(root.find('dependency').get('file'), 'main')
        self.assertFalse(any(node.get(OOR + 'finalized') == 'true' for node in root.iter()))
        self.assertFalse((self.output / 'user/registrymodifications.xcu').exists())
        bootstrap = (self.output / 'program/bootstrap.ini').read_text(encoding='utf-8')
        self.assertIn('UserInstallation=$SYSUSERCONFIG/OpenGeul/Office/4', bootstrap)

    def test_missing_tabbed_translations_are_replaced_in_four_real_notebookbars(self):
        modules = [('swriter', 'sw'), ('scalc', 'sc'), ('simpress', 'sd'), ('sdraw', 'sd')]
        with ZipFile(SUITE / 'tests/fixtures/tabbed-korean-26.8.1.zip') as archive:
            catalogs = {domain: gettext.GNUTranslations(io.BytesIO(archive.read(
                f'program/resource/ko/LC_MESSAGES/{domain}.mo'))) for _, domain in modules}
            for name in archive.namelist():
                if name == 'PROVENANCE.json':
                    continue
                path = self.source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
        before = tree_hashes(self.source)
        originals, count = {}, 0
        for module, domain in modules:
            path = f'share/config/soffice.cfg/modules/{module}/ui/notebookbar.ui'
            tree = ET.parse(self.source / path)
            originals[path] = tree
            for prop in tree.iter('property'):
                context = prop.get('context', '')
                if context.startswith('Tabbed') and context.endswith('TabLabel'):
                    # Exercise the actual bundled contextual gettext lookup that
                    # VclBuilder uses: all 66 tab labels fall back to English.
                    self.assertEqual(catalogs[domain].pgettext(context, prop.text), prop.text)
                    self.assertNotRegex(prop.text, '[가-힣]')
                    count += 1
        self.assertEqual(count, 66)
        branding.brand_runtime(self.source, self.output, self.manifest)
        for module, domain in modules:
            path = f'share/config/soffice.cfg/modules/{module}/ui/notebookbar.ui'
            original, branded = originals[path], ET.parse(self.output / path)
            self.assertEqual([(node.tag, node.attrib) for node in original.iter()],
                             [(node.tag, node.attrib) for node in branded.iter()])
            for old, prop in zip(original.iter('property'), branded.iter('property')):
                context = prop.get('context', '')
                if not (context.startswith('Tabbed') and context.endswith('TabLabel')):
                    self.assertEqual(old.text, prop.text, 'An unrelated notebookbar property changed')
                    continue
                shown = catalogs[domain].pgettext(context, prop.text)
                if context.endswith('|3DTabLabel'):
                    self.assertEqual(shown, '3D(~D)')
                else:
                    self.assertRegex(shown, '[가-힣]', context + ' still shows an English tab')
                if '~' in old.text:
                    mnemonic = old.text[old.text.index('~') + 1].upper()
                    self.assertTrue(shown.endswith('(~' + mnemonic + ')'), context)
            labels = {prop.get('context', '').split('|')[-1]: prop.text for prop in branded.iter('property')}
            self.assertEqual(labels['HomeTabLabel'], '홈(~H)')
            self.assertEqual(labels['InsertTabLabel'], '삽입(~I)')
            self.assertEqual(labels['LayoutTabLabel'], '레이아웃(~L)')
        self.assertEqual(before, tree_hashes(self.source))
        for domain in catalogs:
            path = f'program/resource/ko/LC_MESSAGES/{domain}.mo'
            self.assertEqual((self.source / path).read_bytes(), (self.output / path).read_bytes())


if __name__ == '__main__':
    unittest.main()
