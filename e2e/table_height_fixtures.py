"""Create bounded synthetic line-spacing controls without renaming XML namespaces."""
from pathlib import Path
from xml.dom import minidom
import zipfile

SPACINGS = (-300, 0, 600)
HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
HH = 'http://www.hancom.co.kr/hwpml/2011/head'
# Paragraph::new_empty(), not the empty-document XML template: table cells
# start with segment_width=0. These are authored SOURCE controls, never a
# renderer's runtime layout observation.
SOURCE_ROW = dict(textpos='0', vertpos='0', vertsize='1000', textheight='1000',
                  baseline='850', spacing='600', horzpos='0', horzsize='0', flags='393216')


def _children(element, name):
    return [node for node in element.childNodes
            if node.nodeType == node.ELEMENT_NODE and node.namespaceURI == HP and node.localName == name]


def _one(element, name):
    nodes = element.getElementsByTagNameNS(HP, name)
    if len(nodes) != 1:
        raise ValueError(f'Expected exactly one synthetic {name}')
    return nodes[0]


def _source_rows(section, header):
    """Accept only the known five-row control before authoring missing caches."""
    table = _one(section, 'tbl')
    if table.getAttribute('rowCnt') != '1' or table.getAttribute('colCnt') != '1':
        raise ValueError('Expected a one-row, one-column synthetic table')
    _one(table, 'tr')
    cell = _one(table, 'tc')
    sublist = _one(cell, 'subList')
    paragraphs = _children(sublist, 'p')
    if len(paragraphs) != 5 or len(table.getElementsByTagNameNS(HP, 'p')) != 5:
        raise ValueError('Expected five direct synthetic paragraphs')
    if [node for node in sublist.childNodes if node.nodeType == node.ELEMENT_NODE] != paragraphs:
        raise ValueError('Unexpected synthetic cell content')
    margin = _one(cell, 'cellMargin')
    if any(margin.getAttribute(name) != '141' for name in ('top', 'bottom')):
        raise ValueError('Synthetic cell vertical margins changed')
    chars = [node for node in header.getElementsByTagNameNS(HH, 'charPr') if node.getAttribute('id') == '0']
    styles = [node for node in header.getElementsByTagNameNS(HH, 'paraPr') if node.getAttribute('id') == '0']
    if len(chars) != 1 or chars[0].getAttribute('height') != '1000' or len(styles) != 1:
        raise ValueError('Synthetic text metrics changed')
    spacing = styles[0].getElementsByTagNameNS(HH, 'lineSpacing')
    if len(spacing) != 2 or any(dict(node.attributes.items()) != dict(type='PERCENT', value='160', unit='HWPUNIT') for node in spacing):
        raise ValueError('Synthetic paragraph spacing changed')
    arrays = []
    for index, paragraph in enumerate(paragraphs):
        expected = dict(id=str(index), paraPrIDRef='0', styleIDRef='0', pageBreak='0', columnBreak='0', merged='0')
        if dict(paragraph.attributes.items()) != expected:
            raise ValueError('Synthetic paragraph identity changed')
        runs = _children(paragraph, 'run')
        row_arrays = _children(paragraph, 'linesegarray')
        elements = [node for node in paragraph.childNodes if node.nodeType == node.ELEMENT_NODE]
        if len(runs) != 1 or len(row_arrays) > 1 or elements != runs + row_arrays:
            raise ValueError('Unexpected synthetic paragraph content')
        run = runs[0]
        text = _children(run, 't')
        if dict(run.attributes.items()) != dict(charPrIDRef='0') or len(text) != 1 or [node for node in run.childNodes if node.nodeType == node.ELEMENT_NODE] != text:
            raise ValueError('Synthetic character style changed')
        if text[0].attributes.length or any(node.nodeType not in (node.TEXT_NODE, node.CDATA_SECTION_NODE) for node in text[0].childNodes) or ''.join(node.data for node in text[0].childNodes) != f'Row {index} lastline':
            raise ValueError('Synthetic row text changed')
        arrays.append(row_arrays)
    if any(arrays) and not all(arrays):
        raise ValueError('Mixed stored and missing synthetic caches')
    if not any(arrays):
        for paragraph in paragraphs:
            array = section.createElementNS(HP, 'hp:linesegarray')
            line = section.createElementNS(HP, 'hp:lineseg')
            for name, value in SOURCE_ROW.items():
                line.setAttribute(name, value)
            array.appendChild(line)
            paragraph.appendChild(array)
    lines = []
    for paragraph in paragraphs:
        array = _children(paragraph, 'linesegarray')[0]
        rows = _children(array, 'lineseg')
        if array.attributes.length or len(rows) != 1 or [node for node in array.childNodes if node.nodeType == node.ELEMENT_NODE] != rows or dict(rows[0].attributes.items()) != SOURCE_ROW or rows[0].childNodes:
            raise ValueError('Noncanonical synthetic source row')
        lines.extend(rows)
    if len(table.getElementsByTagNameNS(HP, 'lineseg')) != 5:
        raise ValueError('Expected five one-line paragraphs')
    for name in ('pos', 'sz', 'cellSz'):
        _one(table, name)
    return table, lines

def generate(folder: Path) -> None:
    with zipfile.ZipFile(folder / 'table-base.hwpx') as archive:
        members = archive.infolist()
        if len({i.filename for i in members}) != len(members):
            raise ValueError('Duplicate synthetic archive member')
        if sum(i.file_size for i in members) > 2_000_000:
            raise ValueError('Synthetic base unexpectedly large')
        source = {i.filename: archive.read(i) for i in members}
    for spacing in SPACINGS:
        section = minidom.parseString(source['Contents/section0.xml'])
        header = minidom.parseString(source['Contents/header.xml'])
        table, lines = _source_rows(section, header)
        table.getElementsByTagName('hp:pos')[0].setAttribute('treatAsChar', '1')
        # No declared-height shrink heuristic: isolate measured content height.
        table.getElementsByTagName('hp:sz')[0].setAttribute('height', '0')
        table.getElementsByTagName('hp:cellSz')[0].setAttribute('height', '0')
        table.getElementsByTagName('hp:subList')[0].setAttribute('vertAlign', 'TOP')
        for index, line in enumerate(lines):
            line.setAttribute('spacing', str(spacing))
            line.setAttribute('vertpos', str(index * (1000 + spacing)))
        for value in header.getElementsByTagName('hh:lineSpacing'):
            value.setAttribute('value', str(100 + spacing // 10))
        with zipfile.ZipFile(folder / f'table-spacing-{spacing}.hwpx', 'w') as archive:
            for name, data in source.items():
                if name == 'Contents/section0.xml':
                    data = section.toxml(encoding='UTF-8')
                elif name == 'Contents/header.xml':
                    data = header.toxml(encoding='UTF-8')
                archive.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == 'mimetype' else zipfile.ZIP_DEFLATED)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    generate(parser.parse_args().folder.resolve())
