"""독립 XML·PNG·PDF oracle의 잘못된 결과 거부. 실제 제품 실행은 하지 않는다."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'e2e'))
from supported_feature_oracle import (
    A4, CELL_MARKERS, assert_checkerboard, assert_pdf_pattern, assert_picture,
    assert_style, assert_table, checkerboard, inspect_gui_pdf, text_fixture,
)


def package(*, rows=2, cols=2, markers=CELL_MARKERS, pic=False, image=None,
            binding='image1', width=11339, height=5669, style=1400, bold=True):
    data = io.BytesIO()
    text = ''.join('<hp:tr>'+''.join('<hp:tc><hp:subList><hp:p><hp:run charPrIDRef="0"><hp:t>'+markers[r*cols+c]+
        '</hp:t></hp:run></hp:p></hp:subList></hp:tc>' for c in range(cols))+'</hp:tr>' for r in range(rows))
    section = '<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hc="common"><hp:p><hp:run charPrIDRef="0">'+f'<hp:tbl rowCnt="{rows}" colCnt="{cols}">'+text+'</hp:tbl>'
    if pic:
        section += f'<hp:pic><hp:curSz width="{width}" height="{height}"/><hc:img binaryItemIDRef="{binding}"/></hp:pic>'
    section += '<hp:t>PLAIN-HEAD</hp:t></hp:run><hp:run charPrIDRef="1"><hp:t>FORMAT-MARKER</hp:t></hp:run></hp:p></hp:sec>'
    header = f'<hh:head xmlns:hh="head"><hh:fontface lang="LATIN"><hh:font id="0" face="Arial"/></hh:fontface><hh:charPr id="0" height="1000"><hh:fontRef latin="0"/></hh:charPr><hh:charPr id="1" height="{style}"><hh:fontRef latin="0"/>'+('<hh:bold/>' if bold else '')+'</hh:charPr></hh:head>'
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('mimetype', 'application/hwp+zip')
        archive.writestr('Contents/header.xml', header)
        archive.writestr('Contents/content.hpf', '<package><manifest><item id="image1" href="BinData/image1.png"/></manifest></package>')
        archive.writestr('Contents/section0.xml', section)
        if pic: archive.writestr('BinData/image1.png', image)
    return data.getvalue()


class SupportedOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.png = checkerboard(self.folder/'owned.png').read_bytes()

    def test_table_rows_columns_and_exact_cell_markers(self):
        self.assertEqual(assert_table(package(), 2)['tables'][0]['cells'], [list(CELL_MARKERS[:2]), list(CELL_MARKERS[2:])])
        for markers in (('WRONG', *CELL_MARKERS[1:]), (CELL_MARKERS[1], CELL_MARKERS[0], *CELL_MARKERS[2:]), (CELL_MARKERS[0],)*4):
            with self.subTest(markers=markers), self.assertRaises(ValueError): assert_table(package(markers=markers), 2)
        with self.assertRaises(ValueError): assert_table(package(), 3)
        wrong = package().replace(b'rowCnt="2"', b'rowCnt="3"')
        with self.assertRaises(ValueError): assert_table(wrong, 2)

    def test_png_full_owned_pattern_dimensions_and_decode(self):
        self.assertTrue(assert_checkerboard(self.png))
        for dimensions, color in (((32, 16), (230, 30, 30)), ((16, 32), (30, 30, 230))):
            data = io.BytesIO(); Image.new('RGB', dimensions, color).save(data, format='PNG')
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError): assert_checkerboard(data.getvalue())
        with self.assertRaises(ValueError): assert_checkerboard(b'PNG broken')

    def test_picture_actual_binding_binary_dimensions_and_count(self):
        self.assertEqual(len(assert_picture(package(pic=True, image=self.png), 1)['pictures']), 1)
        for kwargs in ({'binding': 'missing'}, {'width': 0}, {'height': 20000}, {'image': b'broken'}):
            values = {'pic': True, 'image': self.png, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): assert_picture(package(**values), 1)
        with self.assertRaises(ValueError): assert_picture(package(), 1)
        with self.assertRaises(ValueError): assert_picture(package(pic=True, image=self.png), 0)

    def test_style_checks_entire_marker_and_plain_range(self):
        self.assertTrue(assert_style(package(), 'FORMAT-MARKER', bold=True, height=1400, font='Arial'))
        self.assertTrue(assert_style(package(), 'PLAIN-HEAD', bold=False, height=1000))
        for values in ({'style': 1000}, {'bold': False}):
            with self.subTest(values=values), self.assertRaises(ValueError): assert_style(package(**values), 'FORMAT-MARKER', bold=True, height=1400)
        with self.assertRaises(ValueError): assert_style(package(), 'MISSING', bold=True)
        with self.assertRaises(ValueError): assert_style(package(), 'FORMAT-MARKER', bold=True, font='Wrong font')

    def test_owned_two_page_input_generation_is_explicit_and_refuses_overwrite(self):
        blank = self.folder/'blank.hwpx'
        with zipfile.ZipFile(io.BytesIO(package())) as source, zipfile.ZipFile(blank, 'w') as target:
            for item in source.infolist():
                value = source.read(item.filename)
                if item.filename == 'Contents/section0.xml':
                    value = b'<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p id="0"><hp:run charPrIDRef="0"><hp:secPr/><hp:t/></hp:run></hp:p></hp:sec>'
                target.writestr(item, value)
        output = text_fixture(blank, self.folder/'two-pages.hwpx', ['PAGE-ONE', 'PAGE-TWO'], page_breaks=(1,))
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(output) as archive:
            tree = ET.fromstring(archive.read('Contents/section0.xml'))
            self.assertEqual([p.get('pageBreak') for p in tree], ['0', '1'])
        with self.assertRaises(ValueError): text_fixture(blank, output, ['overwrite'])

    def make_pdf(self, *, marker='GUI-PDF-END', pages=1, invisible=False, pattern=True):
        path = self.folder/f'case-{marker}-{pages}-{invisible}-{pattern}.pdf'
        pdf = canvas.Canvas(str(path), pagesize=tuple(A4))
        for _ in range(pages):
            if invisible:
                text = pdf.beginText(72, 750); text.setTextRenderMode(3); text.textLine(marker); pdf.drawText(text)
            else: pdf.drawString(72, 750, marker)
            if pattern: pdf.drawImage(ImageReader(io.BytesIO(self.png)), 210, 420, width=40*72/25.4, height=20*72/25.4)
            pdf.showPage()
        pdf.save(); return path

    def test_pdfium_uses_predeclared_text_pages_a4_and_actual_checkerboard(self):
        expected = {'pages': [{'size_pt': A4, 'markers': ['GUI-PDF-END']}]}
        result = inspect_gui_pdf(self.make_pdf(), expected, self.folder/'inspection', checkerboard_page=0)
        self.assertEqual(result['image_pattern']['squares'], 32)
        for kwargs in ({'marker': 'WRONG'}, {'pages': 2}, {'invisible': True}, {'pattern': False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                inspect_gui_pdf(self.make_pdf(**kwargs), expected, self.folder/'negative', checkerboard_page=0)
        wrong_size = {'pages': [{'size_pt': [612, 792], 'markers': ['GUI-PDF-END']}]}
        with self.assertRaises(ValueError): inspect_gui_pdf(self.make_pdf(), wrong_size, self.folder/'wrongsize')

    def test_pdf_raster_pattern_swapped_colors_size_and_region_are_rejected(self):
        image = Image.new('RGB', (595, 842), 'white')
        with Image.open(io.BytesIO(self.png)) as pattern:
            image.paste(pattern.resize((113, 57), Image.Resampling.NEAREST), (210, 365))
        self.assertEqual(assert_pdf_pattern(image, A4)['squares'], 32)
        for values in ({'dimensions_mm': (20, 40)}, {'region': (.1, .1, .2, .2)}):
            with self.subTest(values=values), self.assertRaises(ValueError): assert_pdf_pattern(image, A4, **values)
        ImageDraw.Draw(image).rectangle((210, 365, 322, 421), fill=(230, 30, 30))
        with self.assertRaises(ValueError): assert_pdf_pattern(image, A4)


if __name__ == '__main__': unittest.main()
