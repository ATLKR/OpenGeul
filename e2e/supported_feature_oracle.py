"""지원 UI 출력의 독립 XML/Pillow/PDFium oracle과 소유 합성 입력 생성기."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path, PurePosixPath
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image
from hwpx_oracle import inspect_hwpx

HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
COLORS = ((230, 30, 30), (30, 30, 230))
CELL_MARKERS = ('CELL-00', 'CELL-01', 'CELL-10', 'CELL-11')
A4 = [595.28, 841.89]


def local(node):
    return node.tag.rsplit('}', 1)[-1]


def checkerboard(path: Path):
    image = Image.new('RGB', (32, 16))
    image.putdata([COLORS[(x//4 + y//4) % 2] for y in range(16) for x in range(32)])
    image.save(path, format='PNG')
    return path


def assert_checkerboard(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.format != 'PNG' or image.size != (32, 16):
                raise ValueError('Expected owned 32×16 PNG')
            actual = list(image.convert('RGB').get_flattened_data())
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError('Unreadable PNG') from error
    if actual != [COLORS[(x//4 + y//4) % 2] for y in range(16) for x in range(32)]:
        raise ValueError('PNG checkerboard pattern changed')
    return True


def inspect_supported_hwpx(path):
    data = path.read_bytes() if isinstance(path, Path) else path
    result = inspect_hwpx(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        trees = {name: ET.fromstring(archive.read(name)) for name in archive.namelist()
                 if name.endswith(('.xml', '.hpf'))}
        sections = [tree for name, tree in trees.items() if name.startswith('Contents/section') and name.endswith('.xml')]
        result['tables'] = []
        for section in sections:
            for table in (node for node in section.iter() if local(node) == 'tbl'):
                rows = [node for node in table if local(node) == 'tr']
                cells = [[node for node in row if local(node) == 'tc'] for row in rows]
                declared = (int(table.get('rowCnt', '-1')), int(table.get('colCnt', '-1')))
                if declared[0] != len(rows) or any(len(row) != declared[1] for row in cells):
                    raise ValueError('Table declared/actual cell dimensions differ')
                result['tables'].append({'rows': declared[0], 'cols': declared[1], 'cells': [
                    [''.join(n.text or '' for n in cell.iter() if local(n) == 't') for cell in row] for row in cells]})
        bindings = {}
        for tree in trees.values():
            for node in tree.iter():
                if local(node) == 'item' and node.get('id') and node.get('href'):
                    key = node.get('id')
                    if key in bindings:
                        raise ValueError('Duplicate binary manifest ID')
                    bindings[key] = node.get('href')
        result['pictures'] = []
        for section in sections:
            for picture in (node for node in section.iter() if local(node) == 'pic'):
                images = [node for node in picture.iter() if local(node) == 'img']
                sizes = [node for node in picture if local(node) == 'curSz']
                if len(images) != 1 or len(sizes) != 1:
                    raise ValueError('Picture must have one image binding and current size')
                reference = images[0].get('binaryItemIDRef')
                href = bindings.get(reference, '')
                # content.hpf is in Contents; actual binaries are in root BinData.
                member = str(PurePosixPath(href))
                if member.startswith('../BinData/'):
                    member = member[3:]
                if not member.startswith('BinData/') or member not in archive.namelist():
                    raise ValueError('Picture binary reference is missing or unsafe')
                width, height = int(sizes[0].get('width', '0')), int(sizes[0].get('height', '0'))
                if min(width, height) <= 0:
                    raise ValueError('Picture dimensions must be positive')
                result['pictures'].append({'width_hu': width, 'height_hu': height, 'binary': member,
                                           'data': archive.read(member)})
        shapes = {node.get('id'): node for node in trees['Contents/header.xml'].iter() if local(node) == 'charPr'}
        fonts = {}
        for group in (n for n in trees['Contents/header.xml'].iter() if local(n) == 'fontface'):
            fonts[group.get('lang', '').upper()] = {n.get('id'): n.get('face') for n in group if local(n) == 'font'}
        result['runs'] = []
        for section in sections:
            for run in (n for n in section.iter() if local(n) == 'run'):
                text = ''.join(n.text or '' for n in run if local(n) == 't')
                if not text:
                    continue
                shape = shapes.get(run.get('charPrIDRef'))
                if shape is None:
                    raise ValueError('Text run references a missing charshape')
                refs = [n for n in shape if local(n) == 'fontRef']
                result['runs'].append({'text': text, 'height': int(shape.get('height', '0')),
                    'bold': any(local(n) == 'bold' for n in shape),
                    'latin_font': fonts.get('LATIN', {}).get(refs[0].get('latin')) if len(refs) == 1 else None})
    return result


def assert_table(path, rows):
    result = inspect_supported_hwpx(path)
    if len(result['tables']) != 1:
        raise ValueError('Expected exactly one table')
    table = result['tables'][0]
    if (table['rows'], table['cols']) != (rows, 2):
        raise ValueError('Unexpected table dimensions')
    for marker in CELL_MARKERS:
        if result['text'].count(marker) != 1:
            raise ValueError('Missing or duplicate cell marker')
    if [value for row in table['cells'][:2] for value in row] != list(CELL_MARKERS):
        raise ValueError('Markers moved to the wrong cells')
    return result


def assert_picture(path, count, *, dimensions_mm=(40, 20)):
    result = inspect_supported_hwpx(path)
    if len(result['pictures']) != count:
        raise ValueError('Unexpected picture count')
    if result['binary_parts'] != count or len({p['binary'] for p in result['pictures']}) != count:
        raise ValueError('Owned picture/BinData references are not exactly one per picture')
    for picture in result['pictures']:
        assert_checkerboard(picture['data'])
        wanted = [mm * 7200/25.4 for mm in dimensions_mm]
        if any(abs(picture[key] - expected) > 7200/25.4 for key, expected in
               zip(('width_hu', 'height_hu'), wanted)):
            raise ValueError('Placed picture has unexpected physical dimensions')
    return result


def assert_style(path, marker, *, bold, height=None, font=None):
    result = inspect_supported_hwpx(path)
    text = ''.join(run['text'] for run in result['runs'])
    if text.count(marker) != 1:
        raise ValueError('Style marker must occur exactly once')
    start, end = text.index(marker), text.index(marker) + len(marker)
    offset = 0
    for run in result['runs']:
        stop = offset + len(run['text'])
        if offset < end and stop > start:
            if run['bold'] != bold or height is not None and run['height'] != height or font is not None and run['latin_font'] != font:
                raise ValueError('Selected text range has the wrong saved style')
        offset = stop
    return result


def text_fixture(blank: Path, target: Path, paragraphs, *, page_breaks=()):
    """Only owned input XML is synthesized; exported PDF never supplies expectations."""
    inspect_hwpx(blank)
    with zipfile.ZipFile(blank) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    tree = ET.fromstring(parts['Contents/section0.xml'])
    originals = [n for n in tree if local(n) == 'p']
    if len(originals) != 1:
        raise ValueError('Owned blank must have exactly one paragraph')
    prototype = originals[0]
    for node in originals:
        tree.remove(node)
    for index, text in enumerate(paragraphs):
        paragraph = copy.deepcopy(prototype)
        paragraph.set('id', str(index))
        paragraph.set('pageBreak', '1' if index in page_breaks else '0')
        for node in list(paragraph):
            if local(node) == 'linesegarray':
                paragraph.remove(node)
            elif local(node) == 'run':
                for child in list(node):
                    if local(child) != 'secPr' or index != 0:
                        node.remove(child)
        run = ET.SubElement(paragraph, f'{{{HP}}}run', charPrIDRef='0')
        ET.SubElement(run, f'{{{HP}}}t').text = text
        tree.append(paragraph)
    parts['Contents/section0.xml'] = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
    if target.exists():
        raise ValueError('Refusing to overwrite owned input fixture')
    with zipfile.ZipFile(target, 'w') as archive:
        for name, data in parts.items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == 'mimetype' else zipfile.ZIP_DEFLATED)
    return target


def assert_pdf_pattern(image, page_size, *, dimensions_mm=(40, 20), region=(.1, .1, .9, .9)):
    """Find declared red/blue pixels, then independently sample all 8×4 squares."""
    rgb = image.convert('RGB')
    def colored(pixel):
        r, g, b = pixel
        return g < 100 and (r > 160 and b < 100 or b > 160 and r < 100)
    mask = Image.new('1', rgb.size)
    mask.putdata([colored(pixel) for pixel in rgb.get_flattened_data()])
    box = mask.getbbox()
    if box is None:
        raise ValueError('PDF checkerboard has no actual color ink')
    left, top, right, bottom = box
    physical = ((right-left)/rgb.width*page_size[0], (bottom-top)/rgb.height*page_size[1])
    if any(abs(value - mm*72/25.4) > 4 for value, mm in zip(physical, dimensions_mm)):
        raise ValueError('PDF checkerboard physical size changed')
    if not (region[0] <= left/rgb.width < right/rgb.width <= region[2]
            and region[1] <= top/rgb.height < bottom/rgb.height <= region[3]):
        raise ValueError('PDF checkerboard is outside its declared region')
    for y in range(4):
        for x in range(8):
            pixel = rgb.getpixel((int(left+(x+.5)*(right-left)/8), int(top+(y+.5)*(bottom-top)/4)))
            expected = COLORS[(x+y) % 2]
            if max(abs(a-b) for a, b in zip(pixel, expected)) > 35:
                raise ValueError('PDF checkerboard raster pattern changed')
    return {'bounds_px': list(box), 'size_pt': list(physical), 'squares': 32}


def inspect_gui_pdf(path, expectation, output, *, checkerboard_page=None):
    from print_oracle import inspect_pdf
    result = inspect_pdf(path, expectation, output)
    if checkerboard_page is not None:
        expected = expectation['pages'][checkerboard_page]
        with Image.open(output/f'page-{checkerboard_page+1}.png') as image:
            result['image_pattern'] = assert_pdf_pattern(image, expected['size_pt'])
    (output/'gui-inspection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
