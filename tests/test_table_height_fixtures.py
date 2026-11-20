"""Author source row caches independently of renderer-generated layout caches."""
from pathlib import Path
from xml.dom import minidom
import importlib.util
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
HH = 'http://www.hancom.co.kr/hwpml/2011/head'
ROW = dict(textpos='0', vertpos='0', vertsize='1000', textheight='1000',
           baseline='850', spacing='600', horzpos='0', horzsize='0', flags='393216')


def module():
    spec = importlib.util.spec_from_file_location('table_height_fixture_test', ROOT / 'e2e/table_height_fixtures.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class TableHeightFixtureTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        paragraphs = ''.join(
            f'<hp:p id="{i}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="0"><hp:t>Row {i} lastline</hp:t></hp:run></hp:p>' for i in range(5))
        self.section = minidom.parseString(
            f'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{HP}">'
            '<hp:p id="outside"><hp:run><hp:tbl rowCnt="1" colCnt="1">'
            '<hp:sz width="10000" height="99"/><hp:pos treatAsChar="0"/>'
            '<hp:tr><hp:tc><hp:subList vertAlign="CENTER">' + paragraphs +
            '</hp:subList><hp:cellSz width="10000" height="99"/>'
            '<hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
            '</hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>')
        self.header = minidom.parseString(
            f'<hh:head xmlns:hh="{HH}"><hh:charProperties><hh:charPr id="0" height="1000"/>'
            '</hh:charProperties><hh:paraProperties><hh:paraPr id="0"><hh:switch><hh:case>'
            '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:case><hh:default>'
            '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:default></hh:switch>'
            '</hh:paraPr></hh:paraProperties></hh:head>')

    def paragraphs(self):
        return self.section.getElementsByTagName('hp:subList')[0].getElementsByTagName('hp:p')

    def add_line(self, paragraph, attrs=None):
        array = self.section.createElementNS(HP, 'hp:linesegarray')
        line = self.section.createElementNS(HP, 'hp:lineseg')
        for name, value in (ROW if attrs is None else attrs).items():
            line.setAttribute(name, value)
        array.appendChild(line)
        paragraph.appendChild(array)
        return line

    def write_base(self, *, duplicate=False):
        with zipfile.ZipFile(self.folder / 'table-base.hwpx', 'w') as archive:
            archive.writestr('mimetype', b'application/hwp+zip')
            archive.writestr('Contents/section0.xml', self.section.toxml(encoding='UTF-8'))
            archive.writestr('Contents/header.xml', self.header.toxml(encoding='UTF-8'))
            archive.writestr('META-INF/container.xml', b'<owned-unmodified/>')
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive.writestr('mimetype', b'application/hwp+zip')

    def verify_outputs(self):
        for spacing in (-300, 0, 600):
            with zipfile.ZipFile(self.folder / f'table-spacing-{spacing}.hwpx') as archive:
                self.assertEqual(archive.read('mimetype'), b'application/hwp+zip')
                self.assertEqual(archive.read('META-INF/container.xml'), b'<owned-unmodified/>')
                section = minidom.parseString(archive.read('Contents/section0.xml'))
                header = minidom.parseString(archive.read('Contents/header.xml'))
            self.assertEqual(section.documentElement.getAttribute('xmlns:hp'), HP)
            self.assertNotIn('ns0:', section.toxml())
            table = section.getElementsByTagName('hp:tbl')[0]
            self.assertEqual(table.getElementsByTagName('hp:pos')[0].getAttribute('treatAsChar'), '1')
            self.assertEqual(table.getElementsByTagName('hp:sz')[0].getAttribute('height'), '0')
            self.assertEqual(table.getElementsByTagName('hp:cellSz')[0].getAttribute('height'), '0')
            paragraphs = table.getElementsByTagName('hp:p')
            self.assertEqual(len(paragraphs), 5)
            for index, paragraph in enumerate(paragraphs):
                self.assertEqual(paragraph.getAttribute('id'), str(index))
                self.assertEqual(paragraph.getElementsByTagName('hp:t')[0].firstChild.data,
                                 f'Row {index} lastline')
                rows = paragraph.getElementsByTagName('hp:lineseg')
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].namespaceURI, HP)
                expected = dict(ROW, spacing=str(spacing), vertpos=str(index * (1000 + spacing)))
                self.assertEqual(dict(rows[0].attributes.items()), expected)
            for item in header.getElementsByTagName('hh:lineSpacing'):
                self.assertEqual(item.getAttribute('value'), str(100 + spacing // 10))
                self.assertEqual(item.getAttribute('type'), 'PERCENT')

    def test_zero_runtime_caches_receive_five_independent_canonical_source_rows(self):
        self.write_base()
        original = (self.folder / 'table-base.hwpx').read_bytes()
        module().generate(self.folder)
        self.verify_outputs()
        self.assertEqual((self.folder / 'table-base.hwpx').read_bytes(), original)

    def test_existing_five_canonical_source_rows_keep_the_same_control_contract(self):
        for paragraph in self.paragraphs():
            self.add_line(paragraph)
        self.write_base()
        module().generate(self.folder)
        self.verify_outputs()

    def test_mixed_or_noncanonical_caches_are_not_silently_replaced(self):
        cases = ('mixed', 'duplicate-array', 'runtime-tag', 'placeholder-height', 'unknown-width', 'missing-field')
        for case in cases:
            with self.subTest(case=case):
                # Each case uses a fresh DOM and fixture folder.
                self.setUp()
                paragraphs = self.paragraphs()
                if case == 'mixed':
                    self.add_line(paragraphs[0])
                else:
                    for paragraph in paragraphs:
                        self.add_line(paragraph)
                    first = paragraphs[0].getElementsByTagName('hp:lineseg')[0]
                    if case == 'duplicate-array': self.add_line(paragraphs[0])
                    elif case == 'runtime-tag': first.setAttribute('flags', str(0x80060000))
                    elif case == 'placeholder-height': first.setAttribute('textheight', '0')
                    elif case == 'unknown-width': first.setAttribute('horzsize', '42520')
                    elif case == 'missing-field': first.removeAttribute('baseline')
                self.write_base()
                with self.assertRaises(ValueError): module().generate(self.folder)
                self.assertEqual(list(self.folder.glob('table-spacing-*.hwpx')), [])

    def test_unknown_content_font_or_margin_never_becomes_a_geometry_control(self):
        for case in ('text', 'paragraph-style', 'char-style', 'font-height', 'line-spacing', 'cell-margin', 'second-cell'):
            with self.subTest(case=case):
                self.setUp()
                if case == 'text': self.paragraphs()[2].getElementsByTagName('hp:t')[0].firstChild.data = 'different'
                elif case == 'paragraph-style': self.paragraphs()[0].setAttribute('paraPrIDRef', '1')
                elif case == 'char-style': self.paragraphs()[0].getElementsByTagName('hp:run')[0].setAttribute('charPrIDRef', '1')
                elif case == 'font-height': self.header.getElementsByTagName('hh:charPr')[0].setAttribute('height', '1200')
                elif case == 'line-spacing': self.header.getElementsByTagName('hh:lineSpacing')[0].setAttribute('value', '180')
                elif case == 'cell-margin': self.section.getElementsByTagName('hp:cellMargin')[0].setAttribute('top', '142')
                elif case == 'second-cell':
                    cell = self.section.getElementsByTagName('hp:tc')[0]
                    cell.parentNode.appendChild(cell.cloneNode(deep=True))
                self.write_base()
                with self.assertRaises(ValueError): module().generate(self.folder)
                self.assertEqual(list(self.folder.glob('table-spacing-*.hwpx')), [])

    def test_duplicate_zip_members_are_rejected_before_output(self):
        for paragraph in self.paragraphs():
            self.add_line(paragraph)
        self.write_base(duplicate=True)
        with self.assertRaises(ValueError): module().generate(self.folder)
        self.assertEqual(list(self.folder.glob('table-spacing-*.hwpx')), [])


if __name__ == '__main__':
    unittest.main()
