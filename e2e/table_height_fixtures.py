"""Create bounded synthetic line-spacing controls without renaming XML namespaces."""
from pathlib import Path
from xml.dom import minidom
import zipfile

SPACINGS = (-300, 0, 600)

def generate(folder: Path) -> None:
    with zipfile.ZipFile(folder / 'table-base.hwpx') as archive:
        if sum(i.file_size for i in archive.infolist()) > 2_000_000:
            raise ValueError('Synthetic base unexpectedly large')
        source = {i.filename: archive.read(i) for i in archive.infolist()}
    for spacing in SPACINGS:
        section = minidom.parseString(source['Contents/section0.xml'])
        header = minidom.parseString(source['Contents/header.xml'])
        tables = section.getElementsByTagName('hp:tbl')
        if len(tables) != 1:
            raise ValueError('Expected exactly one synthetic table')
        table = tables[0]
        table.getElementsByTagName('hp:pos')[0].setAttribute('treatAsChar', '1')
        # No declared-height shrink heuristic: isolate measured content height.
        table.getElementsByTagName('hp:sz')[0].setAttribute('height', '0')
        table.getElementsByTagName('hp:cellSz')[0].setAttribute('height', '0')
        table.getElementsByTagName('hp:subList')[0].setAttribute('vertAlign', 'TOP')
        lines = table.getElementsByTagName('hp:lineseg')
        if len(lines) != 5:
            raise ValueError('Expected five one-line paragraphs')
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
