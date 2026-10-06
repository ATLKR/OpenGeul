"""Printable synthetic HWPX controls. Installed Arial only; no copied font bytes."""
from pathlib import Path
from xml.dom import minidom
import zipfile

FIRST = 'PRINT-FIRST-123'
LAST = 'PRINT-END-gypq-123'
A4 = [595.276, 841.89]

def make_fixture(base: Path, target: Path, *, pages=1, landscape=False, table=False):
    with zipfile.ZipFile(base) as source:
        assert sum(i.file_size for i in source.infolist()) < 2_000_000
        files = {i.filename: source.read(i) for i in source.infolist()}
    head = minidom.parseString(files['Contents/header.xml'])
    section = minidom.parseString(files['Contents/section0.xml'])
    for font in head.getElementsByTagName('hh:font'):
        font.setAttribute('face', 'Arial'); font.setAttribute('isEmbedded', '0')
    markers = []
    if table:
        texts = section.getElementsByTagName('hp:tbl')[0].getElementsByTagName('hp:t')
        assert len(texts) == 5
        for i, text in enumerate(texts):
            marker = LAST if i == 4 else f'PRINT-ROW-{i}-123'
            while text.firstChild: text.removeChild(text.firstChild)
            text.appendChild(section.createTextNode(marker))
            markers.append(marker)
        expected = [markers]
    else:
        root = section.documentElement
        first = next(n for n in root.childNodes if n.nodeType == n.ELEMENT_NODE and n.tagName == 'hp:p')
        text = first.getElementsByTagName('hp:t')[0]
        while text.firstChild: text.removeChild(text.firstChild)
        text.appendChild(section.createTextNode(FIRST + ' ' + LAST))
        expected = [[FIRST, LAST]]
        for i in range(1, pages):
            para = first.cloneNode(True)
            para.setAttribute('id', str(i)); para.setAttribute('pageBreak', '1')
            for name in ('hp:secPr', 'hp:ctrl'):
                for node in list(para.getElementsByTagName(name)): node.parentNode.removeChild(node)
            text = para.getElementsByTagName('hp:t')[0]
            while text.firstChild: text.removeChild(text.firstChild)
            marker = f'PRINT-PAGE-{i+1}-END'
            text.appendChild(section.createTextNode(marker)); root.appendChild(para)
            expected.append([marker])
    if landscape:
        prop = section.getElementsByTagName('hp:pagePr')[0]
        width, height = prop.getAttribute('width'), prop.getAttribute('height')
        prop.setAttribute('width', height); prop.setAttribute('height', width)
    files['Contents/header.xml'] = head.toxml(encoding='UTF-8')
    files['Contents/section0.xml'] = section.toxml(encoding='UTF-8')
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w') as out:
        for name, data in files.items():
            out.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == 'mimetype' else zipfile.ZIP_DEFLATED)
    return {'pageSize': list(reversed(A4)) if landscape else A4, 'pages': expected,
            'forbidden': ['글꼴 도움말', '도구 상자 라벨 표시']}
